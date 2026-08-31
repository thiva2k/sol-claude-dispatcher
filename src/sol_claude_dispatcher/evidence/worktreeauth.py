"""Raw linked-worktree authority sealing and post-worker equality checks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from ..errors import (
    RepositoryAuthorityCaptureFailed,
    WorktreeGitdirNotDispatcherOwned,
    WorktreeGitfileMalformed,
    WorktreeGitfileNotRegular,
    WorktreeHeadNotRegular,
    WorktreeBaseMismatch,
    WorktreeSealSchemaUnsupported,
)


_SHA1_RE = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True)
class WorktreeAuthorityRecord:
    schema_version: int
    worktree_id: str
    expected_base_commit: str
    created_argv_sha256: str
    worktree_gitfile_path: bytes
    gitfile_bytes: bytes
    gitfile_mode: int
    gitdir_realpath: bytes
    gitdir_dev: int
    gitdir_ino: int
    commondir_bytes: bytes
    common_dir_realpath: bytes
    gitdir_backptr_bytes: bytes
    head_bytes: bytes
    head_mode: int

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "worktree_id": self.worktree_id,
            "expected_base_commit": self.expected_base_commit,
            "created_argv_sha256": self.created_argv_sha256,
            "gitfile_mode": self.gitfile_mode,
            "gitdir_dev": self.gitdir_dev,
            "gitdir_ino": self.gitdir_ino,
            "head_mode": self.head_mode,
        }
        for name in (
            "worktree_gitfile_path",
            "gitfile_bytes",
            "gitdir_realpath",
            "commondir_bytes",
            "common_dir_realpath",
            "gitdir_backptr_bytes",
            "head_bytes",
        ):
            result[f"{name}_hex"] = getattr(self, name).hex()
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "WorktreeAuthorityRecord":
        if value.get("schema_version") != 2:
            raise WorktreeSealSchemaUnsupported(
                "The persisted worktree authority schema is unsupported.",
                details={"schema_version": value.get("schema_version")},
            )
        try:
            return cls(
                schema_version=2,
                worktree_id=str(value["worktree_id"]),
                expected_base_commit=str(value["expected_base_commit"]),
                created_argv_sha256=str(value["created_argv_sha256"]),
                worktree_gitfile_path=bytes.fromhex(str(value["worktree_gitfile_path_hex"])),
                gitfile_bytes=bytes.fromhex(str(value["gitfile_bytes_hex"])),
                gitfile_mode=int(value["gitfile_mode"]),
                gitdir_realpath=bytes.fromhex(str(value["gitdir_realpath_hex"])),
                gitdir_dev=int(value["gitdir_dev"]),
                gitdir_ino=int(value["gitdir_ino"]),
                commondir_bytes=bytes.fromhex(str(value["commondir_bytes_hex"])),
                common_dir_realpath=bytes.fromhex(str(value["common_dir_realpath_hex"])),
                gitdir_backptr_bytes=bytes.fromhex(str(value["gitdir_backptr_bytes_hex"])),
                head_bytes=bytes.fromhex(str(value["head_bytes_hex"])),
                head_mode=int(value["head_mode"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RepositoryAuthorityCaptureFailed(
                "The persisted worktree authority record is malformed."
            ) from exc


@dataclass(frozen=True)
class AuthorityDifference:
    comparison: int
    field: str
    expected: str | int | None
    observed: str | int | None


@dataclass(frozen=True)
class WorktreeVerdictRecord:
    schema_version: int
    verdict: Literal["base_held", "base_mismatch", "indirection_changed", "unknown"]
    observed_head_bytes: bytes | None
    differences: tuple[AuthorityDifference, ...]
    checks_passed: tuple[int, ...]


def _bytes_path(path: str | os.PathLike[str] | bytes) -> bytes:
    return path if isinstance(path, bytes) else os.fsencode(os.fspath(path))


def _stable_file_identity(st: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Return the fields which must not change while authority bytes are read."""

    return (
        st.st_dev,
        st.st_ino,
        st.st_mode,
        st.st_size,
        st.st_mtime_ns,
        st.st_ctime_ns,
    )


def _read_open_regular(fd: int, opened: os.stat_result) -> tuple[bytes, os.stat_result]:
    """Read an already-open regular file and prove its object stayed stable."""

    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 64 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(fd)
    if _stable_file_identity(after) != _stable_file_identity(opened):
        raise OSError("authority file changed while its descriptor was read")
    return b"".join(chunks), after


def _open_regular_descriptor(path: bytes) -> tuple[int, bytes, os.stat_result]:
    """Open and read a path without yet releasing its identity anchor."""

    before = os.lstat(path)
    if not stat.S_ISREG(before.st_mode):
        raise OSError("authority path is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _stable_file_identity(opened) != _stable_file_identity(before)
        ):
            raise OSError("authority path changed before descriptor open")
        data, after = _read_open_regular(fd, opened)
        return fd, data, after
    except BaseException:
        os.close(fd)
        raise


def _regular_path_still_names(path: bytes, anchored: os.stat_result) -> bool:
    """Return whether ``path`` still names the open regular-file object."""

    final = os.lstat(path)
    return stat.S_ISREG(final.st_mode) and (
        _stable_file_identity(final) == _stable_file_identity(anchored)
    )


def _read_regular_descriptor(path: bytes) -> tuple[bytes, os.stat_result]:
    """Read one authority file without following a last-component replacement.

    The lstat/open/fstat identity comparison closes the check-then-open window.
    The second fstat and lstat close in-place mutation and replacement windows;
    callers therefore never accept bytes from an object that is no longer the
    regular file named by ``path``.
    """

    fd, data, after = _open_regular_descriptor(path)
    try:
        if not _regular_path_still_names(path, after):
            raise OSError("authority path changed after its descriptor was read")
        return data, after
    finally:
        os.close(fd)


def _open_directory_anchor(
    path: bytes, *, expected_dev: int, expected_ino: int
) -> tuple[int, os.stat_result]:
    """Open the sealed gitdir and bind subsequent child reads to its inode."""

    before = os.lstat(path)
    sealed_identity = (expected_dev, expected_ino)
    if (
        not stat.S_ISDIR(before.st_mode)
        or (before.st_dev, before.st_ino) != sealed_identity
    ):
        raise OSError("authority directory no longer has its sealed identity")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != sealed_identity
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise OSError("authority directory changed before descriptor open")
        return fd, opened
    except BaseException:
        os.close(fd)
        raise


def _directory_path_still_names(path: bytes, anchored: os.stat_result) -> bool:
    """Return whether the sealed pathname still names the anchored directory."""

    final = os.lstat(path)
    return stat.S_ISDIR(final.st_mode) and (final.st_dev, final.st_ino) == (
        anchored.st_dev,
        anchored.st_ino,
    )


def _read_regular_at(directory_fd: int, name: bytes) -> tuple[bytes, os.stat_result]:
    """Read a direct gitdir child through the anchored directory descriptor."""

    if os.path.basename(name) != name or name in (b"", b".", b".."):
        raise OSError("authority child name is not a single path component")
    before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise OSError("authority child is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, dir_fd=directory_fd)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _stable_file_identity(opened) != _stable_file_identity(before)
        ):
            raise OSError("authority child changed before descriptor open")
        data, after = _read_open_regular(fd, opened)
        final = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(final.st_mode)
            or _stable_file_identity(final) != _stable_file_identity(after)
        ):
            raise OSError("authority child changed after its descriptor was read")
        return data, after
    finally:
        os.close(fd)


def _read_regular(path: bytes, error_type: type[Exception], label: str) -> tuple[bytes, os.stat_result]:
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise RepositoryAuthorityCaptureFailed(
            f"The worktree {label} authority path is unreadable.",
            details={"path_hex": path.hex()},
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise error_type(
            f"The worktree {label} authority path is not a regular file.",
            details={"path_hex": path.hex()},
        )
    try:
        data, opened = _read_regular_descriptor(path)
        if (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
            raise OSError("authority path changed between classification and read")
        return data, opened
    except OSError as exc:
        raise RepositoryAuthorityCaptureFailed(
            f"The worktree {label} authority bytes are unreadable.",
            details={"path_hex": path.hex()},
        ) from exc


def _one_line_target(raw: bytes, *, prefix: bytes = b"") -> bytes:
    if not raw.endswith(b"\n") or raw.count(b"\n") != 1 or b"\0" in raw:
        raise WorktreeGitfileMalformed("A worktree authority pointer is malformed.")
    value = raw[len(prefix) : -1] if raw.startswith(prefix) else b""
    if not value:
        raise WorktreeGitfileMalformed("A worktree authority pointer is malformed.")
    return value


def _is_within(path: bytes, root: bytes) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _argv_digest(argv: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for token in argv:
        encoded = token.encode("utf-8", "surrogateescape")
        digest.update(str(len(encoded)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded)
    return digest.hexdigest()


def capture_worktree_authority(
    worktree: str | os.PathLike[str] | bytes,
    *,
    worktree_id: str,
    expected_base_commit: str,
    created_argv: Sequence[str],
    dispatcher_owned_gitdir_root: str | os.PathLike[str] | bytes,
) -> WorktreeAuthorityRecord:
    """Seal the four raw authority files immediately after detached creation."""

    if _SHA1_RE.fullmatch(expected_base_commit) is None:
        raise RepositoryAuthorityCaptureFailed(
            "The expected detached-worktree base is not canonical SHA-1."
        )
    if not created_argv or created_argv[-1] != expected_base_commit:
        raise RepositoryAuthorityCaptureFailed(
            "The sealed base does not equal the worktree-add argv token."
        )
    root = _bytes_path(worktree)
    gitfile_path = os.path.join(root, b".git")
    gitfile, gitfile_st = _read_regular(
        gitfile_path, WorktreeGitfileNotRegular, ".git file"
    )
    target = _one_line_target(gitfile, prefix=b"gitdir: ")
    if not os.path.isabs(target):
        target = os.path.join(root, target)
    gitdir = os.path.realpath(target)
    owned_root = os.path.realpath(_bytes_path(dispatcher_owned_gitdir_root))
    if not _is_within(gitdir, owned_root):
        raise WorktreeGitdirNotDispatcherOwned(
            "The linked-worktree gitdir is outside dispatcher-owned authority.",
            details={"gitdir_hex": gitdir.hex()},
        )
    try:
        gitdir_st = os.lstat(gitdir)
    except OSError as exc:
        raise RepositoryAuthorityCaptureFailed("The linked-worktree gitdir is unreadable.") from exc
    if not stat.S_ISDIR(gitdir_st.st_mode):
        raise WorktreeGitdirNotDispatcherOwned(
            "The linked-worktree gitdir is not a directory."
        )

    commondir_path = os.path.join(gitdir, b"commondir")
    commondir, _ = _read_regular(
        commondir_path, WorktreeGitfileNotRegular, "commondir"
    )
    common_target = _one_line_target(commondir)
    if not os.path.isabs(common_target):
        common_target = os.path.join(gitdir, common_target)
    common_real = os.path.realpath(common_target)
    if common_real != owned_root:
        raise WorktreeGitdirNotDispatcherOwned(
            "The linked-worktree commondir does not resolve to sealed authority."
        )

    backptr, _ = _read_regular(
        os.path.join(gitdir, b"gitdir"), WorktreeGitfileNotRegular, "gitdir backpointer"
    )
    _one_line_target(backptr)
    head, head_st = _read_regular(
        os.path.join(gitdir, b"HEAD"), WorktreeHeadNotRegular, "HEAD"
    )
    normalised = head[:-1] if head.endswith(b"\n") else head
    if normalised != expected_base_commit.encode("ascii"):
        raise WorktreeBaseMismatch(
            "The newly-created detached worktree HEAD does not equal its base.",
            details={
                "expected_base_commit": expected_base_commit,
                "actual_head_commit": normalised.decode("ascii", errors="replace"),
                "phase": "dispatch",
            },
            remediation=(
                "Refuse this dispatch; the recorded base is immutable and the "
                "dispatcher never adopts the observed worktree HEAD "
                f"{normalised.decode('ascii', errors='replace')}."
            ),
        )
    return WorktreeAuthorityRecord(
        schema_version=2,
        worktree_id=worktree_id,
        expected_base_commit=expected_base_commit,
        created_argv_sha256=_argv_digest(created_argv),
        worktree_gitfile_path=gitfile_path,
        gitfile_bytes=gitfile,
        gitfile_mode=gitfile_st.st_mode,
        gitdir_realpath=gitdir,
        gitdir_dev=gitdir_st.st_dev,
        gitdir_ino=gitdir_st.st_ino,
        commondir_bytes=commondir,
        common_dir_realpath=common_real,
        gitdir_backptr_bytes=backptr,
        head_bytes=head,
        head_mode=head_st.st_mode,
    )


def authority_file_paths(record: WorktreeAuthorityRecord) -> tuple[bytes, ...]:
    """The exact four file paths V6 may read; never a prefix exemption."""

    return (
        record.worktree_gitfile_path,
        os.path.join(record.gitdir_realpath, b"commondir"),
        os.path.join(record.gitdir_realpath, b"gitdir"),
        os.path.join(record.gitdir_realpath, b"HEAD"),
    )


def _difference(
    comparison: int, field: str, expected: object, observed: object
) -> AuthorityDifference:
    def safe(value: object) -> str | int | None:
        if isinstance(value, bytes):
            return value.hex()
        if isinstance(value, (str, int)) or value is None:
            return value
        if isinstance(value, tuple):
            return ":".join(str(item) for item in value)
        return repr(value)

    return AuthorityDifference(comparison, field, safe(expected), safe(observed))


def verify_worktree_authority(record: WorktreeAuthorityRecord) -> WorktreeVerdictRecord:
    """Run ZI-77's eight comparisons through stable authority anchors."""

    checks: list[int] = []
    differences: list[AuthorityDifference] = []
    observed_head_bytes: bytes | None = None
    gitfile_fd: int | None = None
    gitdir_fd: int | None = None
    try:
        gitfile_st = os.lstat(record.worktree_gitfile_path)
        if not stat.S_ISREG(gitfile_st.st_mode):
            differences.append(_difference(1, "gitfile_type", "regular", gitfile_st.st_mode))
            return WorktreeVerdictRecord(1, "indirection_changed", None, tuple(differences), tuple(checks))
        checks.append(1)

        # Keep this descriptor open until every gitdir child has been read.
        # Matching bytes alone are insufficient if the worktree's .git file is
        # replaced with a matching decoy while verification is in progress.
        gitfile_fd, gitfile_live, gitfile_anchor = _open_regular_descriptor(
            record.worktree_gitfile_path
        )
        if gitfile_live != record.gitfile_bytes:
            differences.append(_difference(2, "gitfile_bytes", record.gitfile_bytes, gitfile_live))
            return WorktreeVerdictRecord(1, "indirection_changed", None, tuple(differences), tuple(checks))
        checks.append(2)

        gitdir_st = os.lstat(record.gitdir_realpath)
        live_identity = (gitdir_st.st_dev, gitdir_st.st_ino)
        sealed_identity = (record.gitdir_dev, record.gitdir_ino)
        if not stat.S_ISDIR(gitdir_st.st_mode) or live_identity != sealed_identity:
            differences.append(_difference(3, "gitdir_identity", sealed_identity, live_identity))
            return WorktreeVerdictRecord(1, "indirection_changed", None, tuple(differences), tuple(checks))
        gitdir_fd, gitdir_anchor = _open_directory_anchor(
            record.gitdir_realpath,
            expected_dev=record.gitdir_dev,
            expected_ino=record.gitdir_ino,
        )
        checks.append(3)

        commondir_live, _ = _read_regular_at(gitdir_fd, b"commondir")
        if commondir_live != record.commondir_bytes:
            differences.append(_difference(4, "commondir_bytes", record.commondir_bytes, commondir_live))
            return WorktreeVerdictRecord(1, "indirection_changed", None, tuple(differences), tuple(checks))
        checks.append(4)

        common_target = _one_line_target(commondir_live)
        if not os.path.isabs(common_target):
            common_target = os.path.join(record.gitdir_realpath, common_target)
        common_live = os.path.realpath(common_target)
        if common_live != record.common_dir_realpath:
            differences.append(_difference(5, "common_dir_realpath", record.common_dir_realpath, common_live))
            return WorktreeVerdictRecord(1, "indirection_changed", None, tuple(differences), tuple(checks))
        checks.append(5)

        backptr_live, _ = _read_regular_at(gitdir_fd, b"gitdir")
        if backptr_live != record.gitdir_backptr_bytes:
            differences.append(_difference(6, "gitdir_backptr_bytes", record.gitdir_backptr_bytes, backptr_live))
            return WorktreeVerdictRecord(1, "indirection_changed", None, tuple(differences), tuple(checks))
        checks.append(6)

        head_st = os.stat(b"HEAD", dir_fd=gitdir_fd, follow_symlinks=False)
        if not stat.S_ISREG(head_st.st_mode):
            differences.append(_difference(7, "head_type", "regular", head_st.st_mode))
            return WorktreeVerdictRecord(1, "base_mismatch", None, tuple(differences), tuple(checks))
        checks.append(7)

        observed_head_bytes, _ = _read_regular_at(gitdir_fd, b"HEAD")
        if observed_head_bytes != record.head_bytes:
            differences.append(_difference(8, "head_bytes", record.head_bytes, observed_head_bytes))
            return WorktreeVerdictRecord(
                1, "base_mismatch", observed_head_bytes, tuple(differences), tuple(checks)
            )
        checks.append(8)

        # The fd-relative reads above remain on the sealed inode even if its
        # pathname is renamed.  That is useful only if we also prove, after all
        # reads, that the sealed pathname still selects the anchored objects.
        if not _regular_path_still_names(record.worktree_gitfile_path, gitfile_anchor):
            differences.append(
                _difference(2, "gitfile_identity", "anchored", "path_replaced")
            )
            return WorktreeVerdictRecord(
                1, "indirection_changed", observed_head_bytes, tuple(differences), tuple(checks)
            )
        if not _directory_path_still_names(record.gitdir_realpath, gitdir_anchor):
            differences.append(
                _difference(3, "gitdir_identity", sealed_identity, "path_replaced")
            )
            return WorktreeVerdictRecord(
                1, "indirection_changed", observed_head_bytes, tuple(differences), tuple(checks)
            )
        return WorktreeVerdictRecord(
            1, "base_held", observed_head_bytes, (), tuple(checks)
        )
    except (OSError, WorktreeGitfileMalformed) as exc:
        differences.append(_difference(0, "capture", "readable", type(exc).__name__))
        return WorktreeVerdictRecord(
            1, "unknown", observed_head_bytes, tuple(differences), tuple(checks)
        )
    finally:
        if gitdir_fd is not None:
            os.close(gitdir_fd)
        if gitfile_fd is not None:
            os.close(gitfile_fd)


def encode_worktree_authority(record: WorktreeAuthorityRecord) -> bytes:
    return json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def decode_worktree_authority(payload: bytes) -> WorktreeAuthorityRecord:
    try:
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError("not an object")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RepositoryAuthorityCaptureFailed(
            "The persisted worktree authority record is malformed."
        ) from exc
    return WorktreeAuthorityRecord.from_dict(value)
