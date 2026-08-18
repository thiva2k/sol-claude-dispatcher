"""Repository locking (brief §25). — Wave 2.

V1 permits exactly one mutating worker per repository. The lock identity is
derived from the *canonical* repository path, so two different spellings of the
same directory contend for the same lock::

    state/locks/<sha256(canonical_repository_path)>.lock

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

__all__ = ["RepositoryLock", "lock_name_for"]


def lock_name_for(repository_root: Path) -> str:
    """Return ``<sha256-of-canonical-path>.lock``.

    The path is resolved first, so ``/a/b``, ``/a/b/`` and a symlink pointing
    at ``/a/b`` all produce the same lock name.
    """
    canonical = str(Path(repository_root).resolve())
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{digest}.lock"


class RepositoryLock:
    """Exclusive, path-derived, advisory filesystem lock for one repository."""

    def __init__(self, repository_root: Path, locks_dir: Path) -> None:
        self._repository_root = Path(repository_root).resolve()
        self._locks_dir = Path(locks_dir)
        self._locks_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._fd: int | None = None

    @property
    def lock_path(self) -> Path:
        return self._locks_dir / lock_name_for(self._repository_root)

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
