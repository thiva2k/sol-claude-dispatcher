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

from pathlib import Path

__all__ = ["RepositoryLock", "lock_name_for"]


def lock_name_for(repository_root: Path) -> str:
    """Return ``<sha256-of-canonical-path>.lock``."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §locks")


class RepositoryLock:
    """Exclusive, path-derived, advisory filesystem lock for one repository."""

    def __init__(self, repository_root: Path, locks_dir: Path) -> None:
        raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §locks")
