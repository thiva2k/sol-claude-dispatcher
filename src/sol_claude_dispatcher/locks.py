"""Repository locking (brief §25). — Wave 2.

V1 permits exactly one mutating worker per repository. The lock identity is
derived from the *canonical git top level*, so every spelling of the same
repository — a trailing slash, a symlink alias, or a subdirectory of the work
tree — contends for the same lock::

    state/locks/<sha256(canonical_git_top_level)>.lock

Deriving identity from the caller's spelling would have let ``/repo`` and
``/repo/src`` hold two different locks on one repository, which is not
mutual exclusion at all (P0-2).

Uses ``fcntl.flock`` with ``LOCK_EX | LOCK_NB``. Non-blocking by default: a
busy repository raises :class:`~sol_claude_dispatcher.errors.RepositoryBusy`
immediately rather than stalling an MCP tool call until Codex's tool timeout.

Contract (authoritative, see ``docs/INTERFACES.md``)::

    class RepositoryLock:
        def __init__(self, repository_root: Path, locks_dir: Path) -> None
        @property
        def lock_path(self) -> Path
        def acquire(self, *, blocking: bool = False, timeout: float = 0.0) -> None
        def release(self) -> None
        def __enter__(self) -> "RepositoryLock"
        def __exit__(self, *exc) -> None

Fable review does not take this lock: it is read-only and runs only against
stable post-worker state.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import os
import time
from pathlib import Path
from types import TracebackType

from .errors import RepositoryBusy
from .git import git_top_level_or_none

__all__ = ["RepositoryLock", "lock_name_for", "lock_identity_for"]


def lock_identity_for(repository_root: Path) -> Path:
    """Canonical identity of the repository ``repository_root`` belongs to.

    The git top level when there is one, otherwise the resolved path. Two
    spellings of the same repository — including a subdirectory of its work
    tree — always produce the same identity, which is what makes "one mutating
    worker per repository" actually hold.

    A non-git directory legitimately has no top level (the lock primitive is
    useful on its own and its unit tests exercise plain directories), so that
    case falls back to the resolved path rather than refusing. Security
    decisions never come through here: ``security.validate_repository_root``
    has already refused anything that is not an allowed git top level before a
    lock is ever constructed in production.
    """
    resolved = Path(repository_root).resolve()
    top_level = git_top_level_or_none(resolved)
    return top_level if top_level is not None else resolved


def lock_name_for(repository_root: Path) -> str:
    """Return ``<sha256-of-canonical-repository-identity>.lock``.

    Identity comes from :func:`lock_identity_for`, so ``/a/b``, ``/a/b/``, a
    symlink pointing at ``/a/b`` and ``/a/b/src`` (when ``/a/b`` is the git top
    level) all produce the same lock name.
    """
    return _digest_name(lock_identity_for(repository_root))


def _digest_name(identity: Path) -> str:
    digest = hashlib.sha256(str(identity).encode("utf-8")).hexdigest()
    return f"{digest}.lock"


class RepositoryLock:
    """Exclusive, identity-derived, advisory filesystem lock for one repository."""

    def __init__(self, repository_root: Path, locks_dir: Path) -> None:
        # Identity is resolved once, at construction: the lock file must not
        # change under a long-lived lock because the filesystem changed shape.
        self._repository_root = lock_identity_for(repository_root)
        self._lock_name = _digest_name(self._repository_root)
        self._locks_dir = Path(locks_dir)
        self._locks_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._fd: int | None = None

    @property
    def lock_path(self) -> Path:
        return self._locks_dir / self._lock_name

    def acquire(self, *, blocking: bool = False, timeout: float = 0.0) -> None:
        """Acquire the exclusive lock.

        Non-blocking by default (§25): a contended repository raises
        ``RepositoryBusy`` immediately rather than stalling until an
        orchestrator's own tool-call timeout fires. Idempotent if this
        instance already holds the lock.
        """
        if self._fd is not None:
            return

        path = self.lock_path
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)

        try:
            if blocking and timeout > 0:
                self._flock_with_timeout(fd, timeout)
            elif blocking:
                fcntl.flock(fd, fcntl.LOCK_EX)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            os.close(fd)
            raise RepositoryBusy(
                "Repository is locked by another process.",
                details={
                    "repository": str(self._repository_root),
                    "lock_path": str(path),
                },
            ) from exc

        # Best-effort holder metadata for debuggability (§25). Truncate first:
        # the lock file is never unlinked, so a stale previous holder's line
        # must not linger underneath ours.
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"pid={os.getpid()}\n".encode("utf-8"))
        except OSError:
            pass

        self._fd = fd

    def _flock_with_timeout(self, fd: int, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def release(self) -> None:
        """Release the lock. Idempotent; safe to call more than once.

        The lock *file* is never unlinked here — unlinking races with another
        process that has already opened it and is about to flock it (§25).
        """
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError as exc:
            if exc.errno != errno.EBADF:
                raise

    def __enter__(self) -> "RepositoryLock":
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
