"""Raw-byte path identity and scope policy for Gate 7.

This module deliberately has no filesystem API calls.  Snapshotting is stage
one's producer; this module freezes its identity-wise delta and decides policy
from that frozen value.  Content classification happens later and therefore
cannot make a path disappear before the scope verdict exists.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, NewType

RepoPath = NewType("RepoPath", bytes)

ChangeType = Literal[
    "added",
    "removed",
    "modified",
    "kind_changed",
    "mode_changed",
    "link_target_changed",
]
ChangeOrigin = Literal["this_run", "prior_run", "both"]

_CHANGE_TYPES = {
    "added",
    "removed",
    "modified",
    "kind_changed",
    "mode_changed",
    "link_target_changed",
}
_CHANGE_ORIGINS = {"this_run", "prior_run", "both"}
_ENTRY_KINDS = {
    "regular",
    "directory",
    "symlink",
    "fifo",
    "socket",
    "block_device",
    "char_device",
    "unknown",
}
_PATH_CHANGE_KEYS = {
    "path",
    "change",
    "origin",
    "tracked_at_base",
    "ignored_by_base",
    "admin_significant",
    "old_kind",
    "new_kind",
    "old_hash",
    "new_hash",
    "old_size",
    "new_size",
}
_PATH_IDENTITY_KEYS = {
    "schema_version",
    "base_commit",
    "changes",
    "run_delta_count",
    "cumulative_delta_count",
    "unchanged_count",
    "unrepresentable",
    "fidelity",
    "digest",
}


def _raw_b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def path_repr(path: RepoPath) -> dict[str, object]:
    """Return the lossless JSON representation of a repository path."""
    raw = bytes(path)
    try:
        display = raw.decode("utf-8")
        utf8 = True
    except UnicodeDecodeError:
        display = raw.decode("utf-8", errors="replace")
        utf8 = False
    return {"raw_b64": _raw_b64(raw), "display": display, "utf8": utf8}


def repo_path_from_repr(value: Mapping[str, object]) -> RepoPath:
    """Load only the authoritative ``raw_b64`` field; display is never read."""
    encoded = value.get("raw_b64")
    if not isinstance(encoded, str):
        raise ValueError("path representation has no raw_b64 string")
    try:
        return RepoPath(base64.b64decode(encoded, validate=True))
    except (ValueError, TypeError) as exc:
        raise ValueError("path representation has invalid raw_b64") from exc


@dataclass(frozen=True)
class PathChange:
    path: RepoPath
    change: ChangeType
    origin: ChangeOrigin
    tracked_at_base: bool
    ignored_by_base: bool
    admin_significant: bool
    old_kind: str | None
    new_kind: str | None
    old_hash: str | None
    new_hash: str | None
    old_size: int | None
    new_size: int | None

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PathChange":
        """Strictly decode one persisted worker-delta entry.

        Scope history is policy input, not display metadata.  Accepting a
        partial or type-coerced row here could silently erase a prior policy
        breach on resume, so the persisted schema is deliberately exact.
        """
        if set(value) != _PATH_CHANGE_KEYS:
            raise ValueError("path change has an unsupported field set")

        path_value = value["path"]
        if not isinstance(path_value, Mapping) or set(path_value) != {
            "raw_b64",
            "display",
            "utf8",
        }:
            raise ValueError("path change path representation is malformed")
        path = repo_path_from_repr(path_value)
        if path_repr(path) != dict(path_value):
            raise ValueError("path change display metadata disagrees with raw path")
        raw_path = bytes(path)
        if (
            not raw_path
            or raw_path.startswith(b"/")
            or b"\0" in raw_path
            or any(part in {b"", b".", b".."} for part in raw_path.split(b"/"))
        ):
            raise ValueError("path change path is not repository-relative")

        change = value["change"]
        origin = value["origin"]
        if not isinstance(change, str) or change not in _CHANGE_TYPES:
            raise ValueError("path change type is unsupported")
        if not isinstance(origin, str) or origin not in _CHANGE_ORIGINS:
            raise ValueError("path change origin is unsupported")

        bool_fields = (
            "tracked_at_base",
            "ignored_by_base",
            "admin_significant",
        )
        if any(type(value[field]) is not bool for field in bool_fields):
            raise ValueError("path change boolean field is malformed")

        def optional_kind(field: str) -> str | None:
            item = value[field]
            if item is not None and (
                not isinstance(item, str) or item not in _ENTRY_KINDS
            ):
                raise ValueError(f"path change {field} is malformed")
            return item

        def optional_hash(field: str) -> str | None:
            item = value[field]
            if item is not None and (
                not isinstance(item, str)
                or re.fullmatch(r"[0-9a-f]{40}", item) is None
            ):
                raise ValueError(f"path change {field} is malformed")
            return item

        def optional_size(field: str) -> int | None:
            item = value[field]
            if item is not None and (type(item) is not int or item < 0):
                raise ValueError(f"path change {field} is malformed")
            return item

        return cls(
            path=path,
            change=change,  # type: ignore[arg-type]
            origin=origin,  # type: ignore[arg-type]
            tracked_at_base=value["tracked_at_base"],  # type: ignore[arg-type]
            ignored_by_base=value["ignored_by_base"],  # type: ignore[arg-type]
            admin_significant=value["admin_significant"],  # type: ignore[arg-type]
            old_kind=optional_kind("old_kind"),
            new_kind=optional_kind("new_kind"),
            old_hash=optional_hash("old_hash"),
            new_hash=optional_hash("new_hash"),
            old_size=optional_size("old_size"),
            new_size=optional_size("new_size"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "path": path_repr(self.path),
            "change": self.change,
            "origin": self.origin,
            "tracked_at_base": self.tracked_at_base,
            "ignored_by_base": self.ignored_by_base,
            "admin_significant": self.admin_significant,
            "old_kind": self.old_kind,
            "new_kind": self.new_kind,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
            "old_size": self.old_size,
            "new_size": self.new_size,
        }


def _change_digest(changes: tuple[PathChange, ...]) -> str:
    # JSON contains base64, never a lossy display form.  Separators and sorted
    # keys pin one canonical byte sequence across Python processes.
    payload = [change.to_dict() for change in changes]
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PathIdentitySet:
    schema_version: int
    base_commit: str
    changes: tuple[PathChange, ...]
    run_delta_count: int
    cumulative_delta_count: int
    unchanged_count: int
    unrepresentable: tuple[RepoPath, ...]
    fidelity: Literal["content_hash_all"]
    digest: str

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "PathIdentitySet":
        """Strictly decode and authenticate a persisted identity ledger."""
        if set(value) != _PATH_IDENTITY_KEYS:
            raise ValueError("path identity has an unsupported field set")
        if value["schema_version"] != 1:
            raise ValueError("path identity schema version is unsupported")
        base_commit = value["base_commit"]
        if not isinstance(base_commit, str) or re.fullmatch(
            r"[0-9a-f]{40}", base_commit
        ) is None:
            raise ValueError("path identity base commit is malformed")
        raw_changes = value["changes"]
        if not isinstance(raw_changes, list) or any(
            not isinstance(item, Mapping) for item in raw_changes
        ):
            raise ValueError("path identity changes are malformed")
        changes = tuple(PathChange.from_dict(item) for item in raw_changes)

        run_count = value["run_delta_count"]
        cumulative_count = value["cumulative_delta_count"]
        unchanged_count = value["unchanged_count"]
        if type(run_count) is not int or run_count != len(changes):
            raise ValueError("path identity run count is inconsistent")
        if type(cumulative_count) is not int or cumulative_count < len(changes):
            raise ValueError("path identity cumulative count is inconsistent")
        if type(unchanged_count) is not int or unchanged_count < 0:
            raise ValueError("path identity unchanged count is malformed")
        if value["fidelity"] != "content_hash_all":
            raise ValueError("path identity fidelity is unsupported")

        raw_unrepresentable = value["unrepresentable"]
        if not isinstance(raw_unrepresentable, list) or any(
            not isinstance(item, Mapping) for item in raw_unrepresentable
        ):
            raise ValueError("path identity unrepresentable list is malformed")
        unrepresentable: list[RepoPath] = []
        for item in raw_unrepresentable:
            if set(item) != {"raw_b64", "display", "utf8"}:
                raise ValueError("unrepresentable path is malformed")
            path = repo_path_from_repr(item)
            if path_repr(path) != dict(item):
                raise ValueError("unrepresentable path metadata is inconsistent")
            unrepresentable.append(path)

        digest = value["digest"]
        if not isinstance(digest, str) or re.fullmatch(
            r"[0-9a-f]{64}", digest
        ) is None:
            raise ValueError("path identity digest is malformed")
        decoded = cls.create(
            base_commit=base_commit,
            changes=changes,
            unchanged_count=unchanged_count,
            cumulative_delta_count=cumulative_count,
            unrepresentable=unrepresentable,
        )
        if decoded.digest != digest:
            raise ValueError("path identity digest does not match its changes")
        return decoded

    @classmethod
    def create(
        cls,
        *,
        base_commit: str,
        changes: Iterable[PathChange],
        unchanged_count: int,
        fidelity: Literal["content_hash_all"] = "content_hash_all",
        cumulative_delta_count: int | None = None,
        unrepresentable: Iterable[RepoPath] = (),
    ) -> "PathIdentitySet":
        ordered = tuple(sorted(changes, key=lambda item: bytes(item.path)))
        if len({bytes(item.path) for item in ordered}) != len(ordered):
            raise ValueError("a PathIdentitySet may contain each raw path only once")
        unrep = tuple(sorted(unrepresentable, key=bytes))
        return cls(
            schema_version=1,
            base_commit=base_commit,
            changes=ordered,
            run_delta_count=len(ordered),
            cumulative_delta_count=(
                len(ordered)
                if cumulative_delta_count is None
                else cumulative_delta_count
            ),
            unchanged_count=unchanged_count,
            unrepresentable=unrep,
            fidelity=fidelity,
            digest=_change_digest(ordered),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "base_commit": self.base_commit,
            "changes": [change.to_dict() for change in self.changes],
            "run_delta_count": self.run_delta_count,
            "cumulative_delta_count": self.cumulative_delta_count,
            "unchanged_count": self.unchanged_count,
            "unrepresentable": [path_repr(path) for path in self.unrepresentable],
            "fidelity": self.fidelity,
            "digest": self.digest,
        }


def _mode_identity(entry: Any) -> int:
    # Git-significant mode identity: executable or not for regular files;
    # permission changes on directories and special files are not content
    # changes.  Kind is compared independently.
    return int(bool(entry.perm & 0o111)) if entry.kind == "regular" else 0


def _identity(entry: Any | None) -> tuple[object, ...] | None:
    if entry is None:
        return None
    return (
        entry.kind,
        _mode_identity(entry),
        entry.content_hash,
        entry.link_target,
    )


def _change_type(old: Any | None, new: Any | None) -> ChangeType:
    if old is None:
        return "added"
    if new is None:
        return "removed"
    if old.kind != new.kind:
        return "kind_changed"
    if _mode_identity(old) != _mode_identity(new):
        return "mode_changed"
    if old.link_target != new.link_target:
        return "link_target_changed"
    return "modified"


def build_path_identity_set(
    before: Any,
    after: Any,
    *,
    base_commit: str,
    origin: ChangeOrigin = "this_run",
    tracked_paths: Iterable[RepoPath] = (),
    ignored_paths: Iterable[RepoPath] = (),
    admin_paths: Iterable[RepoPath] = (),
    cumulative_delta_count: int | None = None,
) -> PathIdentitySet:
    """Build an identity-wise delta from two complete-fidelity snapshots.

    No path-name symmetric difference is used: existing paths whose content,
    executable bit, kind, or symlink target changed are first-class entries.
    """
    if before.root != after.root:
        raise ValueError("snapshot roots differ")
    if before.fidelity != "content_hash_all" or after.fidelity != "content_hash_all":
        raise ValueError("task-worktree identity requires content_hash_all snapshots")

    old = {bytes(entry.path): entry for entry in before.entries}
    new = {bytes(entry.path): entry for entry in after.entries}
    tracked = {bytes(path) for path in tracked_paths}
    ignored = {bytes(path) for path in ignored_paths}
    admin = {bytes(path) for path in admin_paths}
    changes: list[PathChange] = []
    unchanged = 0

    for raw in sorted(old.keys() | new.keys()):
        old_entry = old.get(raw)
        new_entry = new.get(raw)
        if _identity(old_entry) == _identity(new_entry):
            unchanged += 1
            continue
        changes.append(
            PathChange(
                path=RepoPath(raw),
                change=_change_type(old_entry, new_entry),
                origin=origin,
                tracked_at_base=raw in tracked,
                ignored_by_base=raw in ignored,
                admin_significant=(
                    raw == b".git"
                    or raw.startswith(b".git/")
                    or raw in admin
                ),
                old_kind=None if old_entry is None else old_entry.kind,
                new_kind=None if new_entry is None else new_entry.kind,
                old_hash=None if old_entry is None else old_entry.content_hash,
                new_hash=None if new_entry is None else new_entry.content_hash,
                old_size=None if old_entry is None else old_entry.size,
                new_size=None if new_entry is None else new_entry.size,
            )
        )

    return PathIdentitySet.create(
        base_commit=base_commit,
        changes=changes,
        unchanged_count=unchanged,
        cumulative_delta_count=cumulative_delta_count,
    )


@dataclass(frozen=True)
class ScopeSpecBytes:
    allowed_paths: tuple[bytes, ...] = ()
    forbidden_paths: tuple[bytes, ...] = ()

    @classmethod
    def from_strings(
        cls,
        *,
        allowed_paths: Iterable[str] = (),
        forbidden_paths: Iterable[str] = (),
    ) -> "ScopeSpecBytes":
        def encode(pattern: str) -> bytes:
            if not isinstance(pattern, str):
                raise TypeError("scope patterns must be strings")
            raw = pattern.encode("utf-8")
            if raw.startswith(b"/") or b"\0" in raw or b".." in raw.split(b"/"):
                raise ValueError("scope patterns must be safe repository-relative paths")
            return raw

        return cls(
            allowed_paths=tuple(encode(item) for item in allowed_paths),
            forbidden_paths=tuple(encode(item) for item in forbidden_paths),
        )


def _translate_glob(pattern: bytes) -> re.Pattern[bytes]:
    out = bytearray(b"^")
    index = 0
    while index < len(pattern):
        byte = pattern[index]
        if byte == ord("*"):
            if index + 1 < len(pattern) and pattern[index + 1] == ord("*"):
                # ``.`` does not match LF, but LF is a legal filesystem byte.
                out.extend(b"[\\x00-\\xff]*")
                index += 2
            else:
                out.extend(b"[^/]*")
                index += 1
        elif byte == ord("?"):
            out.extend(b"[^/]")
            index += 1
        else:
            out.extend(re.escape(bytes((byte,))))
            index += 1
    out.extend(b"$")
    return re.compile(bytes(out))


def _matches_any(path: RepoPath, patterns: tuple[bytes, ...]) -> bool:
    raw = bytes(path)
    return any(_translate_glob(pattern).fullmatch(raw) is not None for pattern in patterns)


@dataclass(frozen=True)
class ScopeVerdict:
    decided_over_digest: str
    valid: bool
    forbidden_hits: tuple[RepoPath, ...]
    outside_allowed: tuple[RepoPath, ...]
    primary_tree_interference: bool
    tamper: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "decided_over_digest": self.decided_over_digest,
            "valid": self.valid,
            "forbidden_hits": [path_repr(path) for path in self.forbidden_hits],
            "outside_allowed": [path_repr(path) for path in self.outside_allowed],
            "primary_tree_interference": self.primary_tree_interference,
            "tamper": list(self.tamper),
        }


def decide_scope(
    identity: PathIdentitySet,
    scope: ScopeSpecBytes,
    *,
    primary_tree_interference: bool = False,
    tamper: Iterable[str] = (),
    enforce_allowed: bool = True,
) -> ScopeVerdict:
    """Decide policy over frozen raw path identities, with no filesystem I/O."""
    forbidden: list[RepoPath] = []
    outside: list[RepoPath] = []
    for change in identity.changes:
        # Repository scope is a content-path policy. Directory scaffolding is
        # retained in the complete identity inventory, but an added/removed
        # directory is not independently chargeable when every material child
        # is already decided. This also prevents an in-scope new file from
        # being refused merely because its previously-absent parent directory
        # does not itself match a file-shaped allow rule.
        if {change.old_kind, change.new_kind} <= {None, "directory"}:
            continue
        path = change.path
        if _matches_any(path, scope.forbidden_paths):
            forbidden.append(path)
        elif enforce_allowed and scope.allowed_paths and not _matches_any(
            path, scope.allowed_paths
        ):
            outside.append(path)

    tamper_tuple = tuple(tamper)
    return ScopeVerdict(
        decided_over_digest=identity.digest,
        valid=not forbidden and not outside and not primary_tree_interference and not tamper_tuple,
        forbidden_hits=tuple(sorted(forbidden, key=bytes)),
        outside_allowed=tuple(sorted(outside, key=bytes)),
        primary_tree_interference=primary_tree_interference,
        tamper=tamper_tuple,
    )


__all__ = [
    "PathChange",
    "PathIdentitySet",
    "RepoPath",
    "ScopeSpecBytes",
    "ScopeVerdict",
    "build_path_identity_set",
    "decide_scope",
    "path_repr",
    "repo_path_from_repr",
]
