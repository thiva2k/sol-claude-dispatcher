"""Ignore-blind, raw-byte filesystem snapshots for Gate 7 evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass
from typing import Iterable, Literal, Mapping

from ..errors import FilesystemSnapshotFailed, SnapshotBudgetExceeded
from ..models import utc_now
from .inventory import RepoPath, path_repr, repo_path_from_repr

SnapshotRole = Literal[
    "task_worktree_start",
    "task_worktree_worker_exit",
    "task_worktree_post_validation",
    "primary_pre",
    "primary_post",
]
SnapshotFidelity = Literal["content_hash_all", "stat_identity"]
EntryKind = Literal[
    "regular",
    "directory",
    "symlink",
    "fifo",
    "socket",
    "block_device",
    "char_device",
    "unknown",
]

_TASK_ROLES = {
    "task_worktree_start",
    "task_worktree_worker_exit",
    "task_worktree_post_validation",
}
_PRIMARY_ROLES = {"primary_pre", "primary_post"}
_ALL_ROLES = _TASK_ROLES | _PRIMARY_ROLES
_READ_CHUNK = 1024 * 1024


def _kind(mode: int) -> EntryKind:
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
    if stat.S_ISBLK(mode):
        return "block_device"
    if stat.S_ISCHR(mode):
        return "char_device"
    return "unknown"


class _ChangedDuringMeasurement(Exception):
    pass


def _hash_regular_file(raw_path: bytes, expected_size: int) -> str:
    """Hash one regular file without following a replacement symlink."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(raw_path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size != expected_size:
            raise _ChangedDuringMeasurement
        digest = hashlib.sha1(
            b"blob " + str(expected_size).encode("ascii") + b"\0"
        )
        total = 0
        while True:
            chunk = os.read(fd, _READ_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
        after = os.fstat(fd)
        if total != expected_size or (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise _ChangedDuringMeasurement
        return digest.hexdigest()
    finally:
        os.close(fd)


def _symlink_hash(target: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(target)).encode("ascii") + b"\0" + target
    ).hexdigest()


@dataclass(frozen=True)
class FsEntry:
    path: RepoPath
    kind: EntryKind
    perm: int
    size: int
    mtime_ns: int
    ctime_ns: int
    ino: int
    dev: int
    nlink: int
    content_hash: str | None
    link_target: bytes | None
    read_error: str | None

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "FsEntry":
        """Decode the lossless JSON form used inside the immutable task seal."""
        raw_target = value.get("link_target_b64")
        if raw_target is not None and not isinstance(raw_target, str):
            raise ValueError("snapshot link target is not base64 text")
        try:
            link_target = (
                None
                if raw_target is None
                else base64.b64decode(raw_target, validate=True)
            )
            return cls(
                path=repo_path_from_repr(value["path"]),  # type: ignore[arg-type]
                kind=value["kind"],  # type: ignore[arg-type]
                perm=int(value["perm"]),
                size=int(value["size"]),
                mtime_ns=int(value["mtime_ns"]),
                ctime_ns=int(value["ctime_ns"]),
                ino=int(value["ino"]),
                dev=int(value["dev"]),
                nlink=int(value["nlink"]),
                content_hash=(
                    None
                    if value.get("content_hash") is None
                    else str(value["content_hash"])
                ),
                link_target=link_target,
                read_error=(
                    None
                    if value.get("read_error") is None
                    else str(value["read_error"])
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("snapshot entry is malformed") from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "path": path_repr(self.path),
            "kind": self.kind,
            "perm": self.perm,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "ctime_ns": self.ctime_ns,
            "ino": self.ino,
            "dev": self.dev,
            "nlink": self.nlink,
            "content_hash": self.content_hash,
            "link_target_b64": (
                None
                if self.link_target is None
                else base64.b64encode(self.link_target).decode("ascii")
            ),
            "read_error": self.read_error,
        }


def _snapshot_digest(
    *,
    root: bytes,
    role: SnapshotRole,
    fidelity: SnapshotFidelity,
    entries: tuple[FsEntry, ...],
    admin_excluded: tuple[RepoPath, ...],
) -> str:
    payload = {
        "root_b64": base64.b64encode(root).decode("ascii"),
        "role": role,
        "fidelity": fidelity,
        "entries": [entry.to_dict() for entry in entries],
        "admin_excluded": [path_repr(path) for path in admin_excluded],
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FsSnapshot:
    schema_version: int
    root: bytes
    role: SnapshotRole
    entries: tuple[FsEntry, ...]
    fidelity: SnapshotFidelity
    hash_algo: Literal["git-blob-sha1"]
    counts: dict[str, int]
    total_regular_bytes: int
    unreadable: tuple[RepoPath, ...]
    admin_excluded: tuple[RepoPath, ...]
    ambiguities: tuple[RepoPath, ...]
    capture_complete: bool
    truncated_at_entry: RepoPath | None
    captured_at: str
    duration_ms: int
    digest: str

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "FsSnapshot":
        """Rehydrate and self-verify a snapshot from its canonical JSON form."""
        try:
            root_raw = value["root_b64"]
            if not isinstance(root_raw, str):
                raise ValueError("snapshot root is not base64 text")
            root = base64.b64decode(root_raw, validate=True)
            entries_value = value["entries"]
            excluded_value = value["admin_excluded"]
            if not isinstance(entries_value, list) or not isinstance(
                excluded_value, list
            ):
                raise ValueError("snapshot entry sets are malformed")
            restored = cls.from_entries(
                root=root,
                role=value["role"],  # type: ignore[arg-type]
                entries=(FsEntry.from_dict(item) for item in entries_value),
                fidelity=value["fidelity"],  # type: ignore[arg-type]
                admin_excluded=(
                    repo_path_from_repr(item) for item in excluded_value
                ),
                captured_at=str(value["captured_at"]),
                duration_ms=int(value["duration_ms"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("filesystem snapshot is malformed") from exc
        if value.get("schema_version") != 1:
            raise ValueError("unsupported filesystem snapshot schema")
        if value.get("hash_algo") != "git-blob-sha1":
            raise ValueError("unsupported filesystem snapshot hash algorithm")
        if restored.digest != value.get("digest"):
            raise ValueError("filesystem snapshot digest does not verify")
        if restored.to_dict() != dict(value):
            raise ValueError("filesystem snapshot derived fields do not verify")
        return restored

    @classmethod
    def from_entries(
        cls,
        *,
        root: bytes,
        role: SnapshotRole,
        entries: Iterable[FsEntry],
        fidelity: SnapshotFidelity,
        admin_excluded: Iterable[RepoPath] = (),
        captured_at: str | None = None,
        duration_ms: int = 0,
    ) -> "FsSnapshot":
        if role not in _ALL_ROLES:
            raise ValueError(f"unsupported snapshot role: {role!r}")
        if role in _TASK_ROLES and fidelity != "content_hash_all":
            raise ValueError("task worktree snapshots require content_hash_all fidelity")
        ordered = tuple(sorted(entries, key=lambda entry: bytes(entry.path)))
        if len({bytes(entry.path) for entry in ordered}) != len(ordered):
            raise ValueError("snapshot contains a duplicate raw path")
        excluded = tuple(sorted(admin_excluded, key=bytes))
        unreadable = tuple(
            entry.path for entry in ordered if entry.read_error is not None
        )
        ambiguities = tuple(
            entry.path
            for entry in ordered
            if entry.read_error == "changed_during_measurement"
        )
        counts: dict[str, int] = {}
        for entry in ordered:
            counts[entry.kind] = counts.get(entry.kind, 0) + 1
        total = sum(entry.size for entry in ordered if entry.kind == "regular")
        return cls(
            schema_version=1,
            root=root,
            role=role,
            entries=ordered,
            fidelity=fidelity,
            hash_algo="git-blob-sha1",
            counts=counts,
            total_regular_bytes=total,
            unreadable=unreadable,
            admin_excluded=excluded,
            ambiguities=ambiguities,
            capture_complete=not unreadable,
            truncated_at_entry=None,
            captured_at=captured_at
            or utc_now().isoformat().replace("+00:00", "Z"),
            duration_ms=duration_ms,
            digest=_snapshot_digest(
                root=root,
                role=role,
                fidelity=fidelity,
                entries=ordered,
                admin_excluded=excluded,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "root_b64": base64.b64encode(self.root).decode("ascii"),
            "role": self.role,
            "entries": [entry.to_dict() for entry in self.entries],
            "fidelity": self.fidelity,
            "hash_algo": self.hash_algo,
            "counts": self.counts,
            "total_regular_bytes": self.total_regular_bytes,
            "unreadable": [path_repr(path) for path in self.unreadable],
            "admin_excluded": [path_repr(path) for path in self.admin_excluded],
            "ambiguities": [path_repr(path) for path in self.ambiguities],
            "capture_complete": self.capture_complete,
            "truncated_at_entry": (
                None
                if self.truncated_at_entry is None
                else path_repr(self.truncated_at_entry)
            ),
            "captured_at": self.captured_at,
            "duration_ms": self.duration_ms,
            "digest": self.digest,
        }


def _snapshot_failure(message: str, *, raw_path: bytes, reason: str) -> FilesystemSnapshotFailed:
    return FilesystemSnapshotFailed(
        message,
        details={
            "path_b64": base64.b64encode(raw_path).decode("ascii"),
            "reason": reason[:240],
        },
    )


def capture_snapshot(
    root: bytes | os.PathLike[str] | os.PathLike[bytes],
    *,
    role: SnapshotRole,
    fidelity: SnapshotFidelity = "content_hash_all",
    max_entries: int = 250_000,
    max_regular_bytes: int = 4_000_000_000,
    baseline_entries: int | None = None,
    post_growth_factor: float | None = None,
    exclude_admin: bool = True,
) -> FsSnapshot:
    """Walk ``root`` without Git, decoding, symlink traversal, or ignore rules."""
    raw_root = os.fsencode(os.fspath(root))
    if role not in _ALL_ROLES:
        raise ValueError(f"unsupported snapshot role: {role!r}")
    if role in _TASK_ROLES and fidelity != "content_hash_all":
        raise ValueError("task worktree snapshots require content_hash_all fidelity")
    if max_entries < 0 or max_regular_bytes < 0:
        raise ValueError("snapshot budgets must be non-negative")

    started = time.monotonic_ns()
    entries: list[FsEntry] = []
    excluded: list[RepoPath] = []
    regular_bytes = 0
    stack: list[tuple[bytes, bytes]] = [(raw_root, b"")]

    try:
        root_stat = os.lstat(raw_root)
    except OSError as exc:
        raise _snapshot_failure(
            "Filesystem snapshot root could not be measured.",
            raw_path=raw_root,
            reason=f"{type(exc).__name__}:{exc}",
        ) from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise _snapshot_failure(
            "Filesystem snapshot root is not a directory.",
            raw_path=raw_root,
            reason="not_a_directory",
        )

    while stack:
        directory, relative_directory = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            raise _snapshot_failure(
                "Filesystem snapshot directory could not be enumerated.",
                raw_path=directory,
                reason=f"{type(exc).__name__}:{exc}",
            ) from exc

        descending: list[tuple[bytes, bytes]] = []
        for child in children:
            name = child.name
            if not isinstance(name, bytes):  # bytes scandir must preserve bytes
                raise _snapshot_failure(
                    "Filesystem snapshot decoded a raw path unexpectedly.",
                    raw_path=directory,
                    reason="scandir_returned_str",
                )
            relative = name if not relative_directory else relative_directory + b"/" + name
            if exclude_admin and relative == b".git":
                excluded.append(RepoPath(relative))
                continue

            measured_entries = len(entries) + 1
            if measured_entries > max_entries:
                raise SnapshotBudgetExceeded(
                    "Filesystem snapshot entry budget was exceeded.",
                    details={
                        "maximum_entries": max_entries,
                        "measured_entries": measured_entries,
                        "path_b64": base64.b64encode(relative).decode("ascii"),
                    },
                )
            if (
                baseline_entries is not None
                and post_growth_factor is not None
                and measured_entries > max(1, int(baseline_entries * post_growth_factor))
            ):
                raise SnapshotBudgetExceeded(
                    "Filesystem snapshot growth budget was exceeded.",
                    details={
                        "baseline_entries": baseline_entries,
                        "growth_factor": post_growth_factor,
                        "measured_entries": measured_entries,
                    },
                )

            raw_path = directory + b"/" + name
            try:
                before = os.lstat(raw_path)
            except OSError as exc:
                raise _snapshot_failure(
                    "Filesystem snapshot entry could not be classified.",
                    raw_path=raw_path,
                    reason=f"{type(exc).__name__}:{exc}",
                ) from exc

            kind = _kind(before.st_mode)
            content_hash: str | None = None
            link_target: bytes | None = None
            read_error: str | None = None
            if kind == "regular":
                regular_bytes += before.st_size
                if regular_bytes > max_regular_bytes:
                    raise SnapshotBudgetExceeded(
                        "Filesystem snapshot regular-byte budget was exceeded.",
                        details={
                            "maximum_regular_bytes": max_regular_bytes,
                            "measured_regular_bytes": regular_bytes,
                            "path_b64": base64.b64encode(relative).decode("ascii"),
                        },
                    )
                if fidelity == "content_hash_all":
                    try:
                        content_hash = _hash_regular_file(raw_path, before.st_size)
                        after = os.lstat(raw_path)
                        if (
                            before.st_dev,
                            before.st_ino,
                            before.st_size,
                            before.st_mtime_ns,
                            before.st_ctime_ns,
                            stat.S_IFMT(before.st_mode),
                        ) != (
                            after.st_dev,
                            after.st_ino,
                            after.st_size,
                            after.st_mtime_ns,
                            after.st_ctime_ns,
                            stat.S_IFMT(after.st_mode),
                        ):
                            raise _ChangedDuringMeasurement
                    except _ChangedDuringMeasurement:
                        content_hash = None
                        read_error = "changed_during_measurement"
                    except OSError as exc:
                        content_hash = None
                        read_error = f"{type(exc).__name__}:{exc.errno}"
            elif kind == "symlink" and fidelity == "content_hash_all":
                try:
                    link_target = os.readlink(raw_path)
                    if not isinstance(link_target, bytes):
                        raise TypeError("bytes readlink returned str")
                    after = os.lstat(raw_path)
                    if (
                        before.st_dev,
                        before.st_ino,
                        before.st_size,
                        before.st_mtime_ns,
                        before.st_ctime_ns,
                    ) != (
                        after.st_dev,
                        after.st_ino,
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                    ):
                        raise _ChangedDuringMeasurement
                    content_hash = _symlink_hash(link_target)
                except _ChangedDuringMeasurement:
                    link_target = None
                    content_hash = None
                    read_error = "changed_during_measurement"
                except OSError as exc:
                    link_target = None
                    content_hash = None
                    read_error = f"{type(exc).__name__}:{exc.errno}"

            entries.append(
                FsEntry(
                    path=RepoPath(relative),
                    kind=kind,
                    perm=stat.S_IMODE(before.st_mode),
                    size=before.st_size,
                    mtime_ns=before.st_mtime_ns,
                    ctime_ns=before.st_ctime_ns,
                    ino=before.st_ino,
                    dev=before.st_dev,
                    nlink=before.st_nlink,
                    content_hash=content_hash,
                    link_target=link_target,
                    read_error=read_error,
                )
            )
            if kind == "directory":
                descending.append((raw_path, relative))

        # Stack reverses; push reverse-sorted so the smallest raw path is walked
        # first.  Final entry ordering is sorted independently as a safeguard.
        stack.extend(reversed(descending))

    duration_ms = (time.monotonic_ns() - started) // 1_000_000
    return FsSnapshot.from_entries(
        root=raw_root,
        role=role,
        entries=entries,
        fidelity=fidelity,
        admin_excluded=excluded,
        duration_ms=duration_ms,
    )


__all__ = ["FsEntry", "FsSnapshot", "capture_snapshot"]
