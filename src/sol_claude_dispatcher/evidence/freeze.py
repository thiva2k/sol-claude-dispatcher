"""Per-file evidence freeze used around trusted validation."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from ..errors import EvidenceFreezeViolated
from ..models import utc_now


@dataclass(frozen=True)
class FrozenEvidenceEntry:
    relpath: bytes
    sha256: str
    size: int

    def to_dict(self) -> dict[str, object]:
        return {
            "relpath": os.fsdecode(self.relpath),
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True)
class EvidenceFreeze:
    schema_version: int
    taken_at: str
    entries: tuple[FrozenEvidenceEntry, ...]
    root_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "taken_at": self.taken_at,
            "entries": [entry.to_dict() for entry in self.entries],
            "root_digest": self.root_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "EvidenceFreeze":
        try:
            raw_entries = value["entries"]
            if not isinstance(raw_entries, list):
                raise TypeError("entries must be a list")
            entries: list[FrozenEvidenceEntry] = []
            for raw in raw_entries:
                if not isinstance(raw, Mapping):
                    raise TypeError("entry must be an object")
                relpath = raw["relpath"]
                sha256 = raw["sha256"]
                size = raw["size"]
                if not isinstance(relpath, str) or not isinstance(sha256, str):
                    raise TypeError("entry text fields have the wrong type")
                if len(sha256) != 64 or any(
                    character not in "0123456789abcdef" for character in sha256
                ):
                    raise ValueError("entry sha256 is malformed")
                if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                    raise TypeError("entry size has the wrong type")
                encoded = os.fsencode(relpath)
                _validate_relpath(encoded)
                entries.append(FrozenEvidenceEntry(encoded, sha256, size))
            schema_version = value["schema_version"]
            taken_at = value["taken_at"]
            root_digest = value["root_digest"]
            if not isinstance(schema_version, int) or isinstance(schema_version, bool):
                raise TypeError("schema version has the wrong type")
            if not isinstance(taken_at, str) or not isinstance(root_digest, str):
                raise TypeError("freeze text fields have the wrong type")
            if entries != sorted(entries, key=lambda entry: entry.relpath):
                raise ValueError("freeze entries are not sorted")
            if len({entry.relpath for entry in entries}) != len(entries):
                raise ValueError("freeze entries contain duplicates")
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceFreezeViolated(
                "The persisted evidence freeze record is malformed.",
                details={"changed_files": ["<freeze-record>"]},
            ) from exc
        return cls(
            schema_version=schema_version,
            taken_at=taken_at,
            entries=tuple(entries),
            root_digest=root_digest,
        )


def _validate_relpath(relpath: bytes) -> None:
    if not relpath or relpath.startswith(b"/"):
        raise ValueError("evidence freeze paths must be relative")
    parts = relpath.split(b"/")
    if any(part in (b"", b".") for part in parts):
        raise ValueError("evidence freeze path has an empty component")
    if any(part == b".." for part in parts):
        raise ValueError("evidence freeze path contains a parent component")
    if b"\0" in relpath:
        raise ValueError("evidence freeze path contains NUL")


def _measure(root: bytes, relpath: bytes) -> FrozenEvidenceEntry:
    _validate_relpath(relpath)
    root_st = os.lstat(root)
    if not stat.S_ISDIR(root_st.st_mode):
        raise OSError("evidence root is not a directory")
    cursor = root
    for component in relpath.split(b"/")[:-1]:
        cursor = os.path.join(cursor, component)
        component_st = os.lstat(cursor)
        if not stat.S_ISDIR(component_st.st_mode):
            raise OSError("evidence path has a non-directory parent")
    path = os.path.join(root, relpath)
    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode):
        raise OSError("frozen evidence path is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise OSError("frozen evidence changed before open")
        digest = hashlib.sha256()
        measured = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            measured += len(chunk)
        after = os.fstat(fd)
        if (
            measured != opened.st_size
            or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        ):
            raise OSError("frozen evidence changed during measurement")
    finally:
        os.close(fd)
    return FrozenEvidenceEntry(relpath=relpath, sha256=digest.hexdigest(), size=measured)


def _root_digest(entries: Iterable[FrozenEvidenceEntry]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(str(len(entry.relpath)).encode("ascii"))
        digest.update(b":")
        digest.update(entry.relpath)
        digest.update(entry.sha256.encode("ascii"))
        digest.update(b":")
        digest.update(str(entry.size).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def capture_evidence_freeze(
    root: str | os.PathLike[str] | bytes, relpaths: Iterable[bytes]
) -> EvidenceFreeze:
    """Freeze the exact declared evidence set; no directory discovery occurs."""

    raw_root = root if isinstance(root, bytes) else os.fsencode(os.fspath(root))
    declared = tuple(relpaths)
    if len(declared) != len(set(declared)):
        raise ValueError("evidence freeze contains a duplicate path")
    for relpath in declared:
        _validate_relpath(relpath)
    ordered = tuple(sorted(declared))
    try:
        entries = tuple(_measure(raw_root, relpath) for relpath in ordered)
    except OSError as exc:
        raise EvidenceFreezeViolated(
            "The evidence freeze could not measure every declared file.",
            details={"operation": "capture"},
        ) from exc
    return EvidenceFreeze(
        schema_version=1,
        taken_at=utc_now().isoformat(),
        entries=entries,
        root_digest=_root_digest(entries),
    )


def verify_evidence_freeze(
    root: str | os.PathLike[str] | bytes, frozen: EvidenceFreeze
) -> None:
    """Re-measure every record and name all altered/missing/type-changed files."""

    if frozen.schema_version != 1 or _root_digest(frozen.entries) != frozen.root_digest:
        raise EvidenceFreezeViolated(
            "The evidence freeze record itself does not verify.",
            details={"changed_files": ["<freeze-record>"]},
        )
    raw_root = root if isinstance(root, bytes) else os.fsencode(os.fspath(root))
    changed: list[bytes] = []
    for expected in frozen.entries:
        try:
            current = _measure(raw_root, expected.relpath)
        except OSError:
            changed.append(expected.relpath)
            continue
        if current.size != expected.size or current.sha256 != expected.sha256:
            changed.append(expected.relpath)
    if changed:
        raise EvidenceFreezeViolated(
            "Trusted validation changed frozen worker evidence.",
            details={"changed_files": [os.fsdecode(path) for path in changed]},
        )
