"""Pre-worker base-tree identity and content sealing.

This module deliberately consumes outputs supplied by the Git execution layer.
It never starts Git itself.  Paths stay as bytes from ``ls-tree -z`` through to
the persisted snapshot.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Iterable, Literal, Mapping

from ..errors import BaseObjectVerificationFailed, BaseTreeSnapshotFailed


_OID_RE = re.compile(r"[0-9a-f]{40}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}\Z")
_VALID_MODES = {
    b"100644": (0o100644, "blob"),
    b"100755": (0o100755, "blob"),
    b"120000": (0o120000, "symlink"),
    b"160000": (0o160000, "gitlink"),
}


def git_blob_oid(data: bytes) -> str:
    """Return Git's SHA-1 blob identity for *data*."""

    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data).hexdigest()


@dataclass(frozen=True)
class TreeIdentityEntry:
    path: bytes
    mode: int
    kind: Literal["blob", "symlink", "gitlink"]
    oid: str


@dataclass(frozen=True)
class ContentRef:
    oid: str
    size: int
    source: Literal["start_walk", "cat_file_batch"]


@dataclass(frozen=True)
class SealedTreeEntry:
    path: bytes
    mode: int
    kind: Literal["blob", "symlink", "gitlink"]
    oid: str
    content: ContentRef | None

    def to_dict(self) -> dict[str, object]:
        return {
            "path_hex": self.path.hex(),
            "mode": self.mode,
            "kind": self.kind,
            "oid": self.oid,
            "content": asdict(self.content) if self.content is not None else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SealedTreeEntry":
        raw_content = value.get("content")
        content = None
        if isinstance(raw_content, Mapping):
            source = raw_content.get("source")
            if source not in ("start_walk", "cat_file_batch"):
                raise ValueError("invalid content source")
            content = ContentRef(
                oid=str(raw_content["oid"]),
                size=int(raw_content["size"]),
                source=source,
            )
        kind = value.get("kind")
        if kind not in ("blob", "symlink", "gitlink"):
            raise ValueError("invalid tree-entry kind")
        return cls(
            path=bytes.fromhex(str(value["path_hex"])),
            mode=int(value["mode"]),
            kind=kind,
            oid=str(value["oid"]),
            content=content,
        )


@dataclass(frozen=True)
class BaseTreeSnapshot:
    schema_version: int
    base_commit: str
    entries: tuple[SealedTreeEntry, ...]
    total_content_bytes: int
    sealed_count: int
    gitlink_count: int
    complete: Literal[True]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "base_commit": self.base_commit,
            "entries": [entry.to_dict() for entry in self.entries],
            "total_content_bytes": self.total_content_bytes,
            "sealed_count": self.sealed_count,
            "gitlink_count": self.gitlink_count,
            "complete": True,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "BaseTreeSnapshot":
        if value.get("schema_version") != 1 or value.get("complete") is not True:
            raise ValueError("unsupported or partial base-tree snapshot")
        raw_entries = value.get("entries")
        if not isinstance(raw_entries, list):
            raise ValueError("base-tree entries must be a list")
        entries = tuple(SealedTreeEntry.from_dict(item) for item in raw_entries)
        snapshot = cls(
            schema_version=1,
            base_commit=str(value["base_commit"]),
            entries=entries,
            total_content_bytes=int(value["total_content_bytes"]),
            sealed_count=int(value["sealed_count"]),
            gitlink_count=int(value["gitlink_count"]),
            complete=True,
        )
        _validate_snapshot_shape(snapshot)
        return snapshot


def _failed(message: str, **details: object) -> BaseTreeSnapshotFailed:
    return BaseTreeSnapshotFailed(message, details=details)


def parse_ls_tree_z(output: bytes) -> tuple[TreeIdentityEntry, ...]:
    """Parse exact ``ls-tree -r -z <commit>`` output.

    The parser intentionally rejects the fourth header field produced by
    ``--long``.  It splits on the first TAB because a raw filename may itself
    contain TABs and newlines.
    """

    if not output:
        return ()
    if not output.endswith(b"\0"):
        raise _failed("Base-tree output is not NUL terminated.")
    entries: list[TreeIdentityEntry] = []
    seen: set[bytes] = set()
    for index, record in enumerate(output[:-1].split(b"\0")):
        try:
            head, path = record.split(b"\t", 1)
        except ValueError as exc:
            raise _failed("A base-tree record has no path delimiter.", record=index) from exc
        fields = head.split(b" ")
        if len(fields) != 3 or any(not field for field in fields):
            raise _failed(
                "A base-tree header is malformed or came from --long.", record=index
            )
        mode_raw, type_raw, oid_raw = fields
        if mode_raw not in _VALID_MODES:
            raise _failed("A base-tree mode is unsupported.", record=index)
        mode, kind = _VALID_MODES[mode_raw]
        expected_type = b"commit" if kind == "gitlink" else b"blob"
        if type_raw != expected_type:
            raise _failed("A base-tree mode and object type disagree.", record=index)
        try:
            oid = oid_raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise _failed("A base-tree object id is not ASCII.", record=index) from exc
        if _OID_RE.fullmatch(oid) is None:
            raise _failed("A base-tree object id is not canonical SHA-1.", record=index)
        if not path or path.startswith(b"/") or b"\0" in path:
            raise _failed("A base-tree path is not repository relative.", record=index)
        if path in seen:
            raise _failed("The base-tree output contains a duplicate path.", path_hex=path.hex())
        seen.add(path)
        entries.append(TreeIdentityEntry(path=path, mode=mode, kind=kind, oid=oid))
    # Recursive tree traversal order is not global raw-path order (a tree named
    # ``a`` may emit ``a/file`` before the root entry ``a.txt``).  The persisted
    # snapshot nevertheless has one canonical, raw-byte ordering.
    return tuple(sorted(entries, key=lambda entry: entry.path))


def parse_cat_file_batch(
    expected_oids: Iterable[str], output: bytes
) -> dict[str, bytes]:
    """Parse an injected ``cat-file --batch`` response without line-reading data."""

    expected = tuple(expected_oids)
    if len(set(expected)) != len(expected):
        raise _failed("The requested batch contains duplicate object ids.")
    result: dict[str, bytes] = {}
    cursor = 0
    for position, expected_oid in enumerate(expected):
        newline = output.find(b"\n", cursor)
        if newline < 0:
            raise _failed("A cat-file response header is missing.", position=position)
        header = output[cursor:newline]
        cursor = newline + 1
        fields = header.split(b" ")
        if len(fields) == 2 and fields[1] == b"missing":
            raise _failed("A base blob is absent from the cat-file batch.", oid=expected_oid)
        if len(fields) != 3:
            raise _failed("A cat-file response header is malformed.", position=position)
        oid_raw, object_type, size_raw = fields
        if oid_raw != expected_oid.encode("ascii") or object_type != b"blob":
            raise _failed("A cat-file response does not match its request.", oid=expected_oid)
        if not size_raw.isdigit() or (len(size_raw) > 1 and size_raw.startswith(b"0")):
            raise _failed("A cat-file response size is not canonical.", oid=expected_oid)
        size = int(size_raw)
        end = cursor + size
        if end >= len(output) or output[end : end + 1] != b"\n":
            raise _failed("A cat-file payload is truncated or misframed.", oid=expected_oid)
        data = output[cursor:end]
        cursor = end + 1
        if git_blob_oid(data) != expected_oid:
            raise BaseObjectVerificationFailed(
                "Base-object bytes do not match their requested object id.",
                details={"oid": expected_oid},
            )
        result[expected_oid] = data
    if cursor != len(output):
        raise _failed("The cat-file response contains unrequested trailing data.")
    return result


def build_base_tree_snapshot(
    base_commit: str,
    identities: Iterable[TreeIdentityEntry],
    content_by_oid: Mapping[str, bytes],
    *,
    source_by_oid: Mapping[str, Literal["start_walk", "cat_file_batch"]] | None = None,
) -> BaseTreeSnapshot:
    """Build the total representation; partial content cannot be represented."""

    if _COMMIT_RE.fullmatch(base_commit) is None:
        raise _failed("The sealed base commit is not a canonical full object id.")
    sources = source_by_oid or {}
    entries: list[SealedTreeEntry] = []
    unique_sizes: dict[str, int] = {}
    gitlinks = 0
    for identity in identities:
        if identity.kind == "gitlink":
            gitlinks += 1
            entries.append(
                SealedTreeEntry(
                    path=identity.path,
                    mode=identity.mode,
                    kind=identity.kind,
                    oid=identity.oid,
                    content=None,
                )
            )
            continue
        data = content_by_oid.get(identity.oid)
        if data is None:
            raise _failed(
                "A complete base-tree snapshot cannot be built with a blob missing.",
                oid=identity.oid,
                path_hex=identity.path.hex(),
            )
        if git_blob_oid(data) != identity.oid:
            raise BaseObjectVerificationFailed(
                "Base-object bytes do not match the tree object id.",
                details={"oid": identity.oid, "path_hex": identity.path.hex()},
            )
        source = sources.get(identity.oid, "cat_file_batch")
        unique_sizes[identity.oid] = len(data)
        entries.append(
            SealedTreeEntry(
                path=identity.path,
                mode=identity.mode,
                kind=identity.kind,
                oid=identity.oid,
                content=ContentRef(oid=identity.oid, size=len(data), source=source),
            )
        )
    snapshot = BaseTreeSnapshot(
        schema_version=1,
        base_commit=base_commit,
        entries=tuple(entries),
        total_content_bytes=sum(unique_sizes.values()),
        sealed_count=len(entries) - gitlinks,
        gitlink_count=gitlinks,
        complete=True,
    )
    _validate_snapshot_shape(snapshot)
    return snapshot


def _validate_snapshot_shape(snapshot: BaseTreeSnapshot) -> None:
    paths = tuple(entry.path for entry in snapshot.entries)
    if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
        raise ValueError("base-tree snapshot paths are not unique and sorted")
    sealed = 0
    gitlinks = 0
    unique_sizes: dict[str, int] = {}
    for entry in snapshot.entries:
        if entry.kind == "gitlink":
            gitlinks += 1
            if entry.content is not None:
                raise ValueError("gitlink cannot have sealed content")
        else:
            sealed += 1
            if entry.content is None or entry.content.oid != entry.oid:
                raise ValueError("non-gitlink entry has no matching content reference")
            unique_sizes[entry.oid] = entry.content.size
    if sealed != snapshot.sealed_count or gitlinks != snapshot.gitlink_count:
        raise ValueError("base-tree snapshot counters disagree")
    if sum(unique_sizes.values()) != snapshot.total_content_bytes:
        raise ValueError("base-tree snapshot byte total disagrees")
