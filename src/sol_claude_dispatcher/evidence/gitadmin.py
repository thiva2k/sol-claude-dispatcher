"""Raw Git-administration capture and operator-baseline reconciliation.

This module intentionally does not import :mod:`subprocess` or the dispatcher's
Git wrapper.  Its job is to decide whether it is safe to start the first Git
process, so asking Git to produce any of its inputs would invert the trust
boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..errors import (
    GitAdministrativeCaptureFailed,
    RepositoryAdministrationUnestablished,
    RepositoryAdministrationUnreconciled,
    RepositoryAdministrationUnsupported,
    RepositoryObjectStoreEntryUnsupported,
    RepositoryObjectStoreMalformed,
    SnapshotBudgetExceeded,
    UnsupportedObjectFormat,
)

__all__ = [
    "ADMIN_BASELINE_SCHEMA",
    "ConfigAssignment",
    "GitAdminSnapshot",
    "LooseObjectValidation",
    "ObjectEntry",
    "ReconciliationResult",
    "RepositoryLayout",
    "baseline_path",
    "capture_repository_administration",
    "load_baseline",
    "read_repository_object_format",
    "reconcile_repository_administration",
    "repository_identity_key",
    "resolve_repository_layout",
    "validate_loose_object_sha1",
    "write_baseline",
]

ADMIN_BASELINE_SCHEMA = "git-admin-baseline/1"
_LOOSE_DIR_RE = re.compile(rb"[0-9a-f]{2}\Z")
_LOOSE_TAIL_RE = re.compile(rb"[0-9a-f]{38}\Z")
_OID_RE = re.compile(r"[0-9a-f]{40}\Z")
_CONFIG_SECTION_RE = re.compile(
    r'^\[([A-Za-z0-9.-]+)(?:\s+"((?:[^"\\]|\\.)*)")?\]$'
)
_CONFIG_KEY_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*\Z")
_MAX_CONFIG_BYTES = 4 * 1024 * 1024
_MAX_INCLUDE_DEPTH = 8
_DEFAULT_MAX_EXPANDED_OBJECT_BYTES = 256 * 1024 * 1024
_CHUNK = 64 * 1024


def _error(error_type, message: str, *, path: bytes | None = None, **details):
    if path is not None:
        details["path"] = os.fsdecode(path)
    return error_type(message, details=details)


@dataclass(frozen=True, order=True)
class ObjectEntry:
    """One protected regular file; unsupported types have no representation."""

    relative_path: str
    entry_type: Literal["regular"]
    size: int
    sha256_digest: str

    def __post_init__(self) -> None:
        if self.entry_type != "regular":
            raise ValueError("ObjectEntry is a regular-file record")
        if self.size < 0:
            raise ValueError("ObjectEntry.size must be non-negative")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256_digest):
            raise ValueError("ObjectEntry.sha256_digest must be 64 lowercase hex")

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "entry_type": self.entry_type,
            "size": self.size,
            "sha256_digest": self.sha256_digest,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ObjectEntry":
        return cls(
            relative_path=str(value["relative_path"]),
            entry_type=value["entry_type"],
            size=int(value["size"]),
            sha256_digest=str(value["sha256_digest"]),
        )


@dataclass(frozen=True, order=True)
class ConfigAssignment:
    key: str
    value: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "value": self.value, "source": self.source}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ConfigAssignment":
        return cls(key=str(value["key"]), value=str(value["value"]), source=str(value["source"]))


@dataclass(frozen=True)
class RepositoryLayout:
    canonical_root: str
    gitdir: str
    common_dir: str
    repository_key: str


@dataclass(frozen=True)
class LooseObjectValidation:
    oid: str
    object_type: str
    expanded_size: int


@dataclass(frozen=True)
class GitAdminSnapshot:
    schema: str
    canonical_root: str
    repository_key: str
    gitdir: str
    common_dir: str
    object_format: str
    exact_entries: tuple[ObjectEntry, ...]
    exact_directories: tuple[str, ...]
    loose_objects: tuple[ObjectEntry, ...]
    loose_fanouts: tuple[str, ...]
    validated_loose_paths: tuple[str, ...]
    config_assignments: tuple[ConfigAssignment, ...]
    exec_assignments: tuple[ConfigAssignment, ...]
    registration_exact_entries: tuple[ObjectEntry, ...] = ()
    registration_exact_directories: tuple[str, ...] = ()
    registration_report_entries: tuple[ObjectEntry, ...] = ()
    registration_report_directories: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "canonical_root": self.canonical_root,
            "repository_key": self.repository_key,
            "gitdir": self.gitdir,
            "common_dir": self.common_dir,
            "object_format": self.object_format,
            "exact_entries": [entry.to_dict() for entry in self.exact_entries],
            "exact_directories": list(self.exact_directories),
            "loose_objects": [entry.to_dict() for entry in self.loose_objects],
            "loose_fanouts": list(self.loose_fanouts),
            "validated_loose_paths": list(self.validated_loose_paths),
            "config_assignments": [item.to_dict() for item in self.config_assignments],
            "exec_assignments": [item.to_dict() for item in self.exec_assignments],
            "registration_exact_entries": [
                entry.to_dict() for entry in self.registration_exact_entries
            ],
            "registration_exact_directories": list(
                self.registration_exact_directories
            ),
            "registration_report_entries": [
                entry.to_dict() for entry in self.registration_report_entries
            ],
            "registration_report_directories": list(
                self.registration_report_directories
            ),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GitAdminSnapshot":
        if value.get("schema") != ADMIN_BASELINE_SCHEMA:
            raise GitAdministrativeCaptureFailed(
                "Administrative baseline has an unsupported schema.",
                details={"found": value.get("schema"), "expected": ADMIN_BASELINE_SCHEMA},
            )
        try:
            return cls(
                schema=ADMIN_BASELINE_SCHEMA,
                canonical_root=str(value["canonical_root"]),
                repository_key=str(value["repository_key"]),
                gitdir=str(value["gitdir"]),
                common_dir=str(value["common_dir"]),
                object_format=str(value["object_format"]),
                exact_entries=tuple(ObjectEntry.from_dict(v) for v in value["exact_entries"]),
                exact_directories=tuple(str(v) for v in value["exact_directories"]),
                loose_objects=tuple(ObjectEntry.from_dict(v) for v in value["loose_objects"]),
                loose_fanouts=tuple(str(v) for v in value["loose_fanouts"]),
                validated_loose_paths=tuple(str(v) for v in value["validated_loose_paths"]),
                config_assignments=tuple(
                    ConfigAssignment.from_dict(v) for v in value["config_assignments"]
                ),
                exec_assignments=tuple(
                    ConfigAssignment.from_dict(v) for v in value["exec_assignments"]
                ),
                registration_exact_entries=tuple(
                    ObjectEntry.from_dict(v)
                    for v in value.get("registration_exact_entries", ())
                ),
                registration_exact_directories=tuple(
                    str(v) for v in value.get("registration_exact_directories", ())
                ),
                registration_report_entries=tuple(
                    ObjectEntry.from_dict(v)
                    for v in value.get("registration_report_entries", ())
                ),
                registration_report_directories=tuple(
                    str(v) for v in value.get("registration_report_directories", ())
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GitAdministrativeCaptureFailed(
                "Administrative baseline failed schema validation.",
                details={"reason": str(exc)},
            ) from exc


@dataclass(frozen=True)
class ReconciliationResult:
    reconciled: bool
    new_loose_objects: tuple[str, ...] = ()


def _canonical_root_bytes(root: os.PathLike[str] | str) -> bytes:
    raw = os.fsencode(os.fspath(root))
    if not os.path.isabs(raw):
        raise _error(
            RepositoryAdministrationUnsupported,
            "Repository root must be absolute.",
            path=raw,
            shape="relative",
        )
    return os.path.realpath(raw)


def repository_identity_key(root: os.PathLike[str] | str) -> str:
    """SHA-256 of ``os.fsencode(canonical realpath)`` — the sole directory key."""

    return hashlib.sha256(_canonical_root_bytes(root)).hexdigest()


def _lstat(path: bytes) -> os.stat_result:
    try:
        return os.lstat(path)
    except OSError as exc:
        raise _error(
            GitAdministrativeCaptureFailed,
            "Administrative path could not be classified.",
            path=path,
            reason=str(exc),
        ) from exc


def _read_regular(path: bytes, *, what: str, maximum_bytes: int | None = None) -> bytes:
    before = _lstat(path)
    if not stat.S_ISREG(before.st_mode):
        raise _error(
            RepositoryObjectStoreEntryUnsupported,
            f"{what} is not a regular file.",
            path=path,
            entry_type=_mode_name(before.st_mode),
        )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb", closefd=True) as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev != before.st_dev or opened.st_ino != before.st_ino
            ):
                raise OSError("entry changed between lstat and open")
            data = stream.read() if maximum_bytes is None else stream.read(maximum_bytes + 1)
    except RepositoryObjectStoreEntryUnsupported:
        raise
    except OSError as exc:
        raise _error(
            GitAdministrativeCaptureFailed,
            f"{what} could not be read without following a link.",
            path=path,
            reason=str(exc),
        ) from exc
    if maximum_bytes is not None and len(data) > maximum_bytes:
        raise _error(
            GitAdministrativeCaptureFailed,
            f"{what} exceeds its byte budget.",
            path=path,
            maximum_bytes=maximum_bytes,
        )
    return data


def _mode_name(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "regular"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    return "other"


def resolve_repository_layout(root: os.PathLike[str] | str) -> RepositoryLayout:
    canonical = _canonical_root_bytes(root)
    root_st = _lstat(canonical)
    if not stat.S_ISDIR(root_st.st_mode):
        raise _error(
            RepositoryAdministrationUnsupported,
            "Repository root is not a real directory.",
            path=canonical,
            shape=_mode_name(root_st.st_mode),
        )

    dotgit = os.path.join(canonical, b".git")
    dotgit_st = _lstat(dotgit)
    if stat.S_ISDIR(dotgit_st.st_mode):
        gitdir = dotgit
    elif stat.S_ISREG(dotgit_st.st_mode):
        raw = _read_regular(dotgit, what=".git file", maximum_bytes=16 * 1024)
        if not raw.startswith(b"gitdir: ") or not raw.endswith(b"\n") or raw.count(b"\n") != 1:
            raise _error(
                RepositoryAdministrationUnsupported,
                "Repository .git file is malformed.",
                path=dotgit,
                shape="gitfile",
            )
        target = raw[len(b"gitdir: ") : -1]
        if not target or b"\x00" in target:
            raise _error(
                RepositoryAdministrationUnsupported,
                "Repository .git file has an unusable target.",
                path=dotgit,
                shape="gitfile",
            )
        gitdir = os.path.realpath(
            target if os.path.isabs(target) else os.path.join(canonical, target)
        )
    else:
        target = os.fsdecode(os.readlink(dotgit)) if stat.S_ISLNK(dotgit_st.st_mode) else None
        raise _error(
            RepositoryAdministrationUnsupported,
            "Repository .git entry has an unsupported filesystem type.",
            path=dotgit,
            shape=_mode_name(dotgit_st.st_mode),
            target=target,
        )

    if not stat.S_ISDIR(_lstat(gitdir).st_mode):
        raise _error(
            RepositoryAdministrationUnsupported,
            "Resolved gitdir is not a real directory.",
            path=gitdir,
            shape=_mode_name(_lstat(gitdir).st_mode),
        )
    commondir_file = os.path.join(gitdir, b"commondir")
    try:
        commondir_st = os.lstat(commondir_file)
    except FileNotFoundError:
        common = gitdir
    except OSError as exc:
        raise _error(
            GitAdministrativeCaptureFailed,
            "commondir could not be classified.",
            path=commondir_file,
            reason=str(exc),
        ) from exc
    else:
        if not stat.S_ISREG(commondir_st.st_mode):
            raise _error(
                RepositoryAdministrationUnsupported,
                "commondir is not a regular file.",
                path=commondir_file,
                shape=_mode_name(commondir_st.st_mode),
            )
        raw = _read_regular(commondir_file, what="commondir", maximum_bytes=16 * 1024)
        target = raw.rstrip(b"\n")
        if not target or b"\n" in target or b"\x00" in target:
            raise _error(
                RepositoryAdministrationUnsupported,
                "commondir has an unusable target.",
                path=commondir_file,
            )
        common = os.path.realpath(
            target if os.path.isabs(target) else os.path.join(gitdir, target)
        )
    common_st = _lstat(common)
    if not stat.S_ISDIR(common_st.st_mode):
        raise _error(
            RepositoryAdministrationUnsupported,
            "Resolved common directory is not a real directory.",
            path=common,
            shape=_mode_name(common_st.st_mode),
        )
    return RepositoryLayout(
        canonical_root=os.fsdecode(canonical),
        gitdir=os.fsdecode(gitdir),
        common_dir=os.fsdecode(common),
        repository_key=hashlib.sha256(canonical).hexdigest(),
    )


def _entry(path: bytes, label: str) -> ObjectEntry:
    before = _lstat(path)
    if not stat.S_ISREG(before.st_mode):
        raise _error(
            RepositoryObjectStoreEntryUnsupported,
            "Protected administrative entry is not a regular file.",
            path=path,
            relative_path=label,
            entry_type=_mode_name(before.st_mode),
        )
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb", closefd=True) as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev != before.st_dev or opened.st_ino != before.st_ino
            ):
                raise OSError("entry changed between lstat and open")
            while True:
                chunk = stream.read(_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise _error(
            GitAdministrativeCaptureFailed,
            "Protected administrative entry could not be hashed.",
            path=path,
            relative_path=label,
            reason=str(exc),
        ) from exc
    return ObjectEntry(label, "regular", before.st_size, digest.hexdigest())


def _strip_config_comment(line: str) -> str:
    escaped = False
    quoted = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif char in "#;" and not quoted and (index == 0 or line[index - 1].isspace()):
            return line[:index].rstrip()
    if escaped or quoted:
        raise ValueError("unterminated quote or escape")
    return line.strip()


def _unescape_config(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        if len(value) < 2 or not value.endswith('"'):
            raise ValueError("unterminated quoted value")
        value = value[1:-1]
    output: list[str] = []
    index = 0
    escapes = {"n": "\n", "t": "\t", "b": "\b", "\\": "\\", '"': '"'}
    while index < len(value):
        if value[index] != "\\":
            output.append(value[index])
            index += 1
            continue
        index += 1
        if index >= len(value) or value[index] not in escapes:
            raise ValueError("unsupported config escape")
        output.append(escapes[value[index]])
        index += 1
    return "".join(output)


def _split_assignment(line: str) -> tuple[str, str]:
    if "=" in line:
        key, value = line.split("=", 1)
    else:
        parts = line.split(None, 1)
        key = parts[0]
        value = parts[1] if len(parts) == 2 else "true"
    key = key.strip()
    if not _CONFIG_KEY_RE.fullmatch(key):
        raise ValueError("invalid config key")
    return key.lower(), _unescape_config(value)


def _config_label(path: bytes, common: bytes, primary: bytes) -> str:
    if path == primary:
        return "config"
    separator = os.fsencode(os.sep)
    if path.startswith(common + separator):
        return os.fsdecode(os.path.relpath(path, common)).replace(os.sep, "/")
    return "include:" + hashlib.sha256(path).hexdigest() + ":" + os.fsdecode(path)


def _parse_config_tree(
    primary: bytes, common: bytes
) -> tuple[tuple[ConfigAssignment, ...], tuple[ObjectEntry, ...]]:
    assignments: list[ConfigAssignment] = []
    files: dict[bytes, ObjectEntry] = {}

    def visit(path: bytes, *, depth: int, stack: tuple[bytes, ...]) -> None:
        canonical = os.path.realpath(path)
        if depth > _MAX_INCLUDE_DEPTH:
            raise ValueError("config include depth exceeds 8")
        if canonical in stack:
            raise ValueError("config include cycle")
        raw = _read_regular(canonical, what="Git config", maximum_bytes=_MAX_CONFIG_BYTES)
        label = _config_label(canonical, common, primary)
        files[canonical] = _entry(canonical, label)
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("config is not UTF-8") from exc
        section: str | None = None
        for line_number, raw_line in enumerate(text.splitlines(), 1):
            line = _strip_config_comment(raw_line.strip())
            if not line:
                continue
            if line.startswith("["):
                match = _CONFIG_SECTION_RE.fullmatch(line)
                if match is None:
                    raise ValueError(f"malformed section at line {line_number}")
                section = match.group(1).lower()
                if match.group(2) is not None:
                    section += "." + _unescape_config(match.group(2)).lower()
                continue
            if section is None:
                raise ValueError(f"assignment outside a section at line {line_number}")
            key, value = _split_assignment(line)
            full_key = f"{section}.{key}"
            assignment = ConfigAssignment(full_key, value, label)
            assignments.append(assignment)
            if (section == "include" or section.startswith("includeif.")) and key == "path":
                if not value or "\x00" in value or value.startswith("%("):
                    raise ValueError(f"unsupported include path at line {line_number}")
                expanded = os.path.expanduser(os.fsencode(value))
                target = (
                    expanded
                    if os.path.isabs(expanded)
                    else os.path.join(os.path.dirname(canonical), expanded)
                )
                visit(target, depth=depth + 1, stack=(*stack, canonical))

    try:
        visit(primary, depth=0, stack=())
    except (GitAdministrativeCaptureFailed, RepositoryObjectStoreEntryUnsupported):
        raise
    except (OSError, ValueError) as exc:
        raise GitAdministrativeCaptureFailed(
            "Raw Git config parsing was incomplete.",
            details={"config": os.fsdecode(primary), "reason": str(exc)},
        ) from exc
    return tuple(assignments), tuple(sorted(files.values()))


def _effective_object_format(assignments: tuple[ConfigAssignment, ...]) -> str:
    values = [item.value.strip().lower() for item in assignments if item.key == "extensions.objectformat"]
    return values[-1] if values else "sha1"


def _is_exec_key(key: str) -> bool:
    return bool(
        re.fullmatch(r"filter\.[^.]+\.(clean|smudge|process)", key)
        or re.fullmatch(r"diff\.[^.]+\.(textconv|command)", key)
        or key
        in {
            "diff.external",
            "core.fsmonitor",
            "core.hookspath",
            "core.sshcommand",
            "core.gitproxy",
            "core.alternaterefscommand",
            "credential.helper",
        }
        or re.fullmatch(r"remote\.[^.]+\.(url|promisor|partialclonefilter)", key)
        or re.fullmatch(r"url\..+\.insteadof", key)
        or key in {"extensions.partialclone", "core.repositoryformatversion"}
    )


def read_repository_object_format(root: os.PathLike[str] | str) -> str:
    """Read object format from raw config/includes without walking objects."""

    layout = resolve_repository_layout(root)
    common = os.fsencode(layout.common_dir)
    config = os.path.join(common, b"config")
    assignments, _ = _parse_config_tree(config, common)
    object_format = _effective_object_format(assignments)
    if object_format != "sha1":
        raise UnsupportedObjectFormat(
            "Wave 0 supports SHA-1 object repositories only.",
            details={"object_format": object_format, "supported": ["sha1"]},
            remediation="Use a SHA-1 repository or wait for format-sealed SHA-256 support.",
        )
    return object_format


def validate_loose_object_sha1(
    path: os.PathLike[str] | str,
    *,
    expected_oid: str,
    maximum_expanded_bytes: int = _DEFAULT_MAX_EXPANDED_OBJECT_BYTES,
) -> LooseObjectValidation:
    """Boundedly validate one canonical zlib-encoded SHA-1 loose object."""

    if not _OID_RE.fullmatch(expected_oid):
        raise RepositoryObjectStoreMalformed(
            "Loose-object pathname is not a full SHA-1 object id.",
            details={"expected_oid": expected_oid},
        )
    raw_path = os.fsencode(os.fspath(path))
    parent = os.path.dirname(raw_path)
    grandparent = os.path.dirname(parent)
    for candidate, role in ((grandparent, "objects"), (parent, "fanout")):
        candidate_st = _lstat(candidate)
        if not stat.S_ISDIR(candidate_st.st_mode):
            raise _error(
                RepositoryObjectStoreEntryUnsupported,
                "Loose-object parent is not a real directory.",
                path=candidate,
                role=role,
                entry_type=_mode_name(candidate_st.st_mode),
            )
    file_st = _lstat(raw_path)
    if not stat.S_ISREG(file_st.st_mode):
        raise _error(
            RepositoryObjectStoreEntryUnsupported,
            "Loose-object entry is not a regular file.",
            path=raw_path,
            entry_type=_mode_name(file_st.st_mode),
        )

    decompressor = zlib.decompressobj()
    header = bytearray()
    header_done = False
    object_type = ""
    declared_size = -1
    content_size = 0
    digest = hashlib.sha1()

    def consume(expanded: bytes) -> None:
        nonlocal header_done, object_type, declared_size, content_size
        if not expanded:
            return
        if not header_done:
            header.extend(expanded)
            nul = header.find(0)
            if nul < 0:
                if len(header) > 128:
                    raise ValueError("canonical header exceeds 128 bytes")
                return
            if nul > 128:
                raise ValueError("canonical header exceeds 128 bytes")
            raw_header = bytes(header[:nul])
            rest = bytes(header[nul + 1 :])
            try:
                kind_raw, size_raw = raw_header.split(b" ", 1)
                object_type = kind_raw.decode("ascii")
                size_text = size_raw.decode("ascii")
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError("malformed canonical object header") from exc
            if object_type not in {"blob", "tree", "commit", "tag"}:
                raise ValueError("unsupported canonical object type")
            if not re.fullmatch(r"0|[1-9][0-9]*", size_text):
                raise ValueError("non-canonical object size")
            declared_size = int(size_text)
            if declared_size > maximum_expanded_bytes:
                raise SnapshotBudgetExceeded(
                    "Loose object exceeds the expanded-byte budget.",
                    details={
                        "path": os.fsdecode(raw_path),
                        "declared_size": declared_size,
                        "maximum_bytes": maximum_expanded_bytes,
                    },
                )
            digest.update(raw_header + b"\0")
            header_done = True
            header.clear()
            expanded = rest
        content_size += len(expanded)
        if content_size > maximum_expanded_bytes or (
            declared_size >= 0 and content_size > declared_size
        ):
            raise ValueError("object expands beyond its declared size or budget")
        digest.update(expanded)

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(raw_path, flags)
        with os.fdopen(fd, "rb", closefd=True) as stream:
            while True:
                compressed = stream.read(_CHUNK)
                if not compressed:
                    break
                expanded = decompressor.decompress(compressed)
                consume(expanded)
                if decompressor.unused_data:
                    raise ValueError("trailing data or a second zlib member")
            consume(decompressor.flush())
        if not decompressor.eof:
            raise ValueError("truncated zlib member")
        if decompressor.unused_data or decompressor.unconsumed_tail:
            raise ValueError("trailing compressed data")
        if not header_done:
            raise ValueError("canonical object header has no NUL terminator")
        if content_size != declared_size:
            raise ValueError("expanded size disagrees with canonical header")
        actual_oid = digest.hexdigest()
        if actual_oid != expected_oid:
            raise ValueError("canonical SHA-1 disagrees with pathname")
    except SnapshotBudgetExceeded:
        raise
    except (OSError, ValueError, zlib.error) as exc:
        raise _error(
            RepositoryObjectStoreMalformed,
            "Loose object is not canonical for its SHA-1 pathname.",
            path=raw_path,
            expected_oid=expected_oid,
            reason=str(exc),
        ) from exc
    return LooseObjectValidation(expected_oid, object_type, content_size)


def _walk_exact(base: bytes, label: str) -> tuple[list[ObjectEntry], list[str]]:
    try:
        base_st = os.lstat(base)
    except FileNotFoundError:
        return [], []
    except OSError as exc:
        raise _error(
            GitAdministrativeCaptureFailed,
            "Exact administrative tree could not be classified.",
            path=base,
            reason=str(exc),
        ) from exc
    if not stat.S_ISDIR(base_st.st_mode):
        raise _error(
            RepositoryObjectStoreEntryUnsupported,
            "Exact administrative tree is not a real directory.",
            path=base,
            entry_type=_mode_name(base_st.st_mode),
        )
    entries: list[ObjectEntry] = []
    directories: list[str] = [label]
    try:
        children = sorted(os.scandir(base), key=lambda item: item.name)
    except OSError as exc:
        raise _error(
            GitAdministrativeCaptureFailed,
            "Exact administrative tree could not be listed.",
            path=base,
            reason=str(exc),
        ) from exc
    for child in children:
        child_path = os.path.join(base, child.name)
        child_st = _lstat(child_path)
        child_label = f"{label}/{os.fsdecode(child.name)}"
        if stat.S_ISDIR(child_st.st_mode):
            child_entries, child_directories = _walk_exact(child_path, child_label)
            entries.extend(child_entries)
            directories.extend(child_directories)
        elif stat.S_ISREG(child_st.st_mode):
            entries.append(_entry(child_path, child_label))
        else:
            raise _error(
                RepositoryObjectStoreEntryUnsupported,
                "Exact administrative entry has an unsupported filesystem type.",
                path=child_path,
                relative_path=child_label,
                entry_type=_mode_name(child_st.st_mode),
            )
    return entries, directories


def capture_repository_administration(
    root: os.PathLike[str] | str,
    *,
    baseline: GitAdminSnapshot | None = None,
    validate_all_loose: bool | None = None,
    maximum_expanded_object_bytes: int = _DEFAULT_MAX_EXPANDED_OBJECT_BYTES,
    selected_worktree_gitdir: os.PathLike[str] | str | bytes | None = None,
) -> GitAdminSnapshot:
    """Capture raw administrative authority without spawning any process.

    Onboarding supplies no ``baseline`` and validates every loose object.  The
    PREPARE gate supplies the operator baseline and validates only newly-seen
    paths; existing objects remain capturable even when corrupt so the equality
    relation can report the load-bearing byte divergence rather than laundering
    it into an apparent absence.
    """

    if validate_all_loose is None:
        validate_all_loose = baseline is None
    baseline_loose_paths = (
        set() if baseline is None else {entry.relative_path for entry in baseline.loose_objects}
    )

    layout = resolve_repository_layout(root)
    common = os.fsencode(layout.common_dir)
    gitdir = os.fsencode(layout.gitdir)
    config_path = os.path.join(common, b"config")
    assignments, config_entries = _parse_config_tree(config_path, common)
    object_format = _effective_object_format(assignments)
    if object_format != "sha1":
        raise UnsupportedObjectFormat(
            "Wave 0 supports SHA-1 object repositories only.",
            details={"object_format": object_format, "supported": ["sha1"]},
        )

    exact: dict[str, ObjectEntry] = {entry.relative_path: entry for entry in config_entries}
    exact_directories: set[str] = set()
    for name in (b"packed-refs", b"shallow"):
        path = os.path.join(common, name)
        try:
            os.lstat(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise _error(
                GitAdministrativeCaptureFailed,
                "Administrative entry could not be classified.",
                path=path,
                reason=str(exc),
            ) from exc
        entry = _entry(path, os.fsdecode(name))
        exact[entry.relative_path] = entry
    for base, label in (
        (os.path.join(common, b"refs"), "refs"),
        (os.path.join(common, b"objects", b"info"), "objects/info"),
        (os.path.join(common, b"objects", b"pack"), "objects/pack"),
    ):
        tree_entries, tree_directories = _walk_exact(base, label)
        exact_directories.update(tree_directories)
        for entry in tree_entries:
            exact[entry.relative_path] = entry
    # Worktree-local authority which may differ from the common directory.
    for relative in (b"config.worktree", b"HEAD", b"commondir", b"gitdir"):
        path = os.path.join(gitdir, relative)
        try:
            os.lstat(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise _error(
                GitAdministrativeCaptureFailed,
                "Worktree administrative entry could not be classified.",
                path=path,
                reason=str(exc),
            ) from exc
        label = "gitdir/" + os.fsdecode(relative)
        exact[label] = _entry(path, label)

    registration_exact: tuple[ObjectEntry, ...] = ()
    registration_exact_directories: tuple[str, ...] = ()
    registration_report: tuple[ObjectEntry, ...] = ()
    registration_report_directories: tuple[str, ...] = ()
    if selected_worktree_gitdir is not None:
        # This is a provenance selection, not a name/prefix exemption.  The
        # caller supplies the exact gitdir from the sealed
        # WorktreeAuthorityRecord; arbitrary worktrees/* children are never
        # swept into the dispatcher's accounted set.
        selected = os.path.realpath(os.fsencode(os.fspath(selected_worktree_gitdir)))
        registrations_root = os.path.realpath(os.path.join(common, b"worktrees"))
        if (
            os.path.dirname(selected) != registrations_root
            or not stat.S_ISDIR(_lstat(selected).st_mode)
        ):
            raise _error(
                RepositoryAdministrationUnsupported,
                "Selected linked-worktree registration is outside sealed authority.",
                path=selected,
                common_worktrees=os.fsdecode(registrations_root),
            )
        registration_id = os.fsdecode(os.path.basename(selected))
        label = f"worktree-registration/{registration_id}"
        registration_entries, registration_directories = _walk_exact(selected, label)
        exact_items: list[ObjectEntry] = []
        report_items: list[ObjectEntry] = []
        for item in registration_entries:
            relative = item.relative_path.removeprefix(label + "/")
            if relative == "index" or relative.startswith("logs/"):
                report_items.append(item)
            else:
                exact_items.append(item)
        registration_exact = tuple(sorted(exact_items))
        registration_report = tuple(sorted(report_items))
        registration_exact_directories = tuple(
            directory
            for directory in registration_directories
            if not directory.removeprefix(label + "/").startswith("logs")
        )
        registration_report_directories = tuple(
            directory
            for directory in registration_directories
            if directory.removeprefix(label + "/").startswith("logs")
        )

    objects = os.path.join(common, b"objects")
    objects_st = _lstat(objects)
    if not stat.S_ISDIR(objects_st.st_mode):
        raise _error(
            RepositoryObjectStoreEntryUnsupported,
            "Object store is not a real directory.",
            path=objects,
            entry_type=_mode_name(objects_st.st_mode),
        )
    loose: list[ObjectEntry] = []
    fanouts: list[str] = []
    validated: list[str] = []
    try:
        object_children = sorted(os.scandir(objects), key=lambda item: item.name)
    except OSError as exc:
        raise _error(
            GitAdministrativeCaptureFailed,
            "Object store could not be listed.",
            path=objects,
            reason=str(exc),
        ) from exc
    total_expanded = 0
    for child in object_children:
        name = os.fsencode(child.name)
        if name in {b"info", b"pack"}:
            continue
        fanout_path = os.path.join(objects, name)
        fanout_st = _lstat(fanout_path)
        if not _LOOSE_DIR_RE.fullmatch(name) or not stat.S_ISDIR(fanout_st.st_mode):
            raise _error(
                RepositoryObjectStoreEntryUnsupported,
                "Loose-object fanout has an unsupported name or type.",
                path=fanout_path,
                entry_type=_mode_name(fanout_st.st_mode),
            )
        fanouts.append(os.fsdecode(name))
        try:
            tails = sorted(os.scandir(fanout_path), key=lambda item: item.name)
        except OSError as exc:
            raise _error(
                GitAdministrativeCaptureFailed,
                "Loose-object fanout could not be listed.",
                path=fanout_path,
                reason=str(exc),
            ) from exc
        for tail_entry in tails:
            tail = os.fsencode(tail_entry.name)
            path = os.path.join(fanout_path, tail)
            path_st = _lstat(path)
            if not _LOOSE_TAIL_RE.fullmatch(tail) or not stat.S_ISREG(path_st.st_mode):
                raise _error(
                    RepositoryObjectStoreEntryUnsupported,
                    "Loose-object child has an unsupported name or type.",
                    path=path,
                    entry_type=_mode_name(path_st.st_mode),
                )
            label = f"objects/{os.fsdecode(name)}/{os.fsdecode(tail)}"
            loose.append(_entry(path, label))
            if validate_all_loose or label not in baseline_loose_paths:
                result = validate_loose_object_sha1(
                    path,
                    expected_oid=os.fsdecode(name + tail),
                    maximum_expanded_bytes=maximum_expanded_object_bytes - total_expanded,
                )
                total_expanded += result.expanded_size
                if total_expanded > maximum_expanded_object_bytes:
                    raise SnapshotBudgetExceeded(
                        "Loose objects exceed the aggregate expanded-byte budget.",
                        details={
                            "actual_bytes": total_expanded,
                            "maximum_bytes": maximum_expanded_object_bytes,
                        },
                    )
                validated.append(label)

    exec_assignments = tuple(item for item in assignments if _is_exec_key(item.key))
    return GitAdminSnapshot(
        schema=ADMIN_BASELINE_SCHEMA,
        canonical_root=layout.canonical_root,
        repository_key=layout.repository_key,
        gitdir=layout.gitdir,
        common_dir=layout.common_dir,
        object_format=object_format,
        exact_entries=tuple(sorted(exact.values())),
        exact_directories=tuple(sorted(exact_directories)),
        loose_objects=tuple(sorted(loose)),
        loose_fanouts=tuple(sorted(fanouts)),
        validated_loose_paths=tuple(sorted(validated)),
        config_assignments=assignments,
        exec_assignments=exec_assignments,
        registration_exact_entries=registration_exact,
        registration_exact_directories=registration_exact_directories,
        registration_report_entries=registration_report,
        registration_report_directories=registration_report_directories,
    )


def _entry_map(entries: tuple[ObjectEntry, ...]) -> dict[str, ObjectEntry]:
    result = {entry.relative_path: entry for entry in entries}
    if len(result) != len(entries):
        raise GitAdministrativeCaptureFailed(
            "Administrative capture contains duplicate relative paths."
        )
    return result


def reconcile_repository_administration(
    baseline: GitAdminSnapshot, current: GitAdminSnapshot
) -> ReconciliationResult:
    """Apply ZI-86; compare only, never update the operator baseline."""

    identity_fields = ("schema", "canonical_root", "repository_key", "gitdir", "common_dir", "object_format")
    identity_changed = {
        field: {"baseline": getattr(baseline, field), "current": getattr(current, field)}
        for field in identity_fields
        if getattr(baseline, field) != getattr(current, field)
    }
    baseline_exact = _entry_map(baseline.exact_entries)
    current_exact = _entry_map(current.exact_entries)
    removed_exact = sorted(set(baseline_exact) - set(current_exact))
    added_exact = sorted(set(current_exact) - set(baseline_exact))
    changed_exact = sorted(
        path
        for path in set(baseline_exact) & set(current_exact)
        if baseline_exact[path] != current_exact[path]
    )
    exact_directories_changed = baseline.exact_directories != current.exact_directories
    baseline_registration = _entry_map(baseline.registration_exact_entries)
    current_registration = _entry_map(current.registration_exact_entries)
    removed_registration = sorted(set(baseline_registration) - set(current_registration))
    added_registration = sorted(set(current_registration) - set(baseline_registration))
    changed_registration = sorted(
        path
        for path in set(baseline_registration) & set(current_registration)
        if baseline_registration[path] != current_registration[path]
    )
    registration_directories_changed = (
        baseline.registration_exact_directories
        != current.registration_exact_directories
    )
    baseline_loose = _entry_map(baseline.loose_objects)
    current_loose = _entry_map(current.loose_objects)
    removed_loose = sorted(set(baseline_loose) - set(current_loose))
    changed_loose = sorted(
        path
        for path in set(baseline_loose) & set(current_loose)
        if baseline_loose[path] != current_loose[path]
    )
    new_loose = sorted(set(current_loose) - set(baseline_loose))
    validated = set(current.validated_loose_paths)
    unvalidated_new = sorted(set(new_loose) - validated)
    if (
        identity_changed
        or removed_exact
        or added_exact
        or changed_exact
        or exact_directories_changed
        or removed_registration
        or added_registration
        or changed_registration
        or registration_directories_changed
        or removed_loose
        or changed_loose
        or unvalidated_new
    ):
        raise RepositoryAdministrationUnreconciled(
            "Repository administrative authority does not reconcile with its operator baseline.",
            details={
                "identity_changed": identity_changed,
                "removed_exact": removed_exact,
                "added_exact": added_exact,
                "changed_exact": changed_exact,
                "exact_directories_changed": exact_directories_changed,
                "removed_registration": removed_registration,
                "added_registration": added_registration,
                "changed_registration": changed_registration,
                "registration_directories_changed": registration_directories_changed,
                "removed_loose": removed_loose,
                "changed_loose": changed_loose,
                "unvalidated_new_loose": unvalidated_new,
            },
            remediation="Inspect the divergence. Re-baselining is an explicit operator action.",
        )
    return ReconciliationResult(True, tuple(new_loose))


def baseline_path(state_root: os.PathLike[str] | str, root: os.PathLike[str] | str) -> Path:
    key = repository_identity_key(root)
    return Path(state_root) / "repos" / key / "git-admin-baseline.json"


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def write_baseline(
    state_root: os.PathLike[str] | str,
    snapshot: GitAdminSnapshot,
    *,
    replace: bool = False,
) -> Path:
    """Atomically write an operator baseline; never called by reconciliation."""

    path = baseline_path(state_root, snapshot.canonical_root)
    # lexists, not exists: a dangling symlink is an existing entry that
    # exists() reports as absent, which would let onboarding replace a planted
    # link without the operator ever passing --replace.
    if os.path.lexists(path):
        if not path.is_symlink() and path.is_file():
            if not replace:
                raise RepositoryAdministrationUnreconciled(
                    "An administrative baseline already exists; replacement must be explicit.",
                    details={"baseline": str(path)},
                    remediation="Re-run the operator command with --replace after reviewing the divergence.",
                )
        else:
            # --replace exists to approve a reviewed divergence, not to clear
            # an artefact nobody can explain. Whatever is here is not a
            # baseline this code wrote, so a human looks before it is removed.
            raise GitAdministrativeCaptureFailed(
                "The administrative baseline path is not a regular file.",
                details={"baseline": str(path), "is_symlink": path.is_symlink()},
                remediation=(
                    "Inspect the path by hand and remove it deliberately. It was "
                    "not written by this dispatcher, and --replace will not "
                    "overwrite it."
                ),
            )
    content = (json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(path, content)
    return path


def load_baseline(
    state_root: os.PathLike[str] | str, root: os.PathLike[str] | str
) -> GitAdminSnapshot:
    path = baseline_path(state_root, root)
    try:
        # O_NOFOLLOW so the trust anchor's bytes can only come from the state
        # directory the dispatcher owns. A symlink here -- live or dangling --
        # fails with ELOOP and is refused below, never silently followed to
        # content some other process chose.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError as exc:
        # No baseline has ever been established for this repository. That is a
        # distinct condition from a baseline that exists and cannot be read,
        # and GATE7-DESIGN.md ORDER 1 R6 names it: "no baseline ->
        # RepositoryAdministrationUnestablished -> row 0". Both refuse, but only
        # this one is remediable by onboarding the repository, so the operator
        # is told which of the two situations they are actually in.
        raise RepositoryAdministrationUnestablished(
            "Repository administration is not established.",
            details={"baseline": str(path), "reason": str(exc)},
            remediation=(
                "Establish the operator baseline once, after reviewing the "
                "repository's trusted execution and transport assignments: "
                ".venv/bin/python scripts/trust-repo-admin.py <repository> "
                "--state-root <state>"
            ),
        ) from exc
    except OSError as exc:
        # ELOOP lands here: the path exists but is a symbolic link. It is
        # deliberately NOT reported as unestablished -- that answer would send
        # the operator to trust-repo-admin.py, and onboarding would then turn
        # the planted link into an approved baseline.
        raise GitAdministrativeCaptureFailed(
            "Administrative baseline could not be read.",
            details={
                "baseline": str(path),
                "reason": str(exc),
                "is_symlink": path.is_symlink(),
            },
            remediation=(
                "The path exists but is not a readable regular file. Inspect it "
                "by hand; do not onboard the repository to make this go away."
            ),
        ) from exc
    try:
        stat_result = os.fstat(fd)
        if not stat.S_ISREG(stat_result.st_mode):
            raise GitAdministrativeCaptureFailed(
                "The administrative baseline is not a regular file.",
                details={"baseline": str(path), "mode": stat_result.st_mode},
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GitAdministrativeCaptureFailed(
            "Administrative baseline is not valid JSON.",
            details={"baseline": str(path), "reason": str(exc)},
        ) from exc
    if not isinstance(data, dict):
        raise GitAdministrativeCaptureFailed(
            "Administrative baseline must contain one JSON object.",
            details={"baseline": str(path)},
        )
    snapshot = GitAdminSnapshot.from_dict(data)
    expected_key = repository_identity_key(root)
    if snapshot.repository_key != expected_key:
        raise GitAdministrativeCaptureFailed(
            "Administrative baseline belongs to a different repository identity.",
            details={"baseline": str(path), "expected": expected_key, "found": snapshot.repository_key},
        )
    return snapshot
