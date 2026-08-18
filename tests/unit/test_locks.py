"""Tests for ``sol_claude_dispatcher.locks`` (§25, §31)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sol_claude_dispatcher import locks
from sol_claude_dispatcher.errors import RepositoryBusy


# ---------------------------------------------------------------------------
# lock_name_for
# ---------------------------------------------------------------------------


def test_lock_name_is_deterministic(tmp_path: Path) -> None:
    assert locks.lock_name_for(tmp_path) == locks.lock_name_for(tmp_path)


def test_lock_name_ends_with_lock_suffix(tmp_path: Path) -> None:
    assert locks.lock_name_for(tmp_path).endswith(".lock")


def test_lock_name_same_for_trailing_slash(tmp_path: Path) -> None:
    with_slash = Path(str(tmp_path) + "/")
    assert locks.lock_name_for(tmp_path) == locks.lock_name_for(with_slash)


def test_lock_name_same_for_symlink_alias(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    assert locks.lock_name_for(real) == locks.lock_name_for(alias)


def test_lock_name_differs_for_different_repos(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert locks.lock_name_for(a) != locks.lock_name_for(b)


# ---------------------------------------------------------------------------
# RepositoryLock — contention
# ---------------------------------------------------------------------------


def test_second_lock_on_same_repo_raises_repository_busy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    locks_dir = tmp_path / "locks"

    lock1 = locks.RepositoryLock(repo, locks_dir)
    lock1.acquire()
    try:
        lock2 = locks.RepositoryLock(repo, locks_dir)
        with pytest.raises(RepositoryBusy):
            lock2.acquire()
    finally:
        lock1.release()


def test_second_lock_via_symlinked_alias_raises_repository_busy(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(repo, target_is_directory=True)
    locks_dir = tmp_path / "locks"

    lock1 = locks.RepositoryLock(repo, locks_dir)
    lock1.acquire()
    try:
        lock2 = locks.RepositoryLock(alias, locks_dir)
        with pytest.raises(RepositoryBusy):
            lock2.acquire()
        # both spellings must resolve to the exact same lock file
        assert lock1.lock_path == lock2.lock_path
    finally:
        lock1.release()


def test_different_repos_do_not_contend(tmp_path: Path) -> None:
    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    repo_a.mkdir()
    repo_b.mkdir()
    locks_dir = tmp_path / "locks"

    lock_a = locks.RepositoryLock(repo_a, locks_dir)
    lock_b = locks.RepositoryLock(repo_b, locks_dir)
    lock_a.acquire()
    try:
        lock_b.acquire()  # must not raise
        lock_b.release()
    finally:
        lock_a.release()


def test_repository_busy_details_carry_repo_and_lock_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    locks_dir = tmp_path / "locks"

    lock1 = locks.RepositoryLock(repo, locks_dir)
    lock1.acquire()
    try:
        lock2 = locks.RepositoryLock(repo, locks_dir)
        with pytest.raises(RepositoryBusy) as excinfo:
            lock2.acquire()
        details = excinfo.value.details
        assert details["repository"] == str(repo.resolve())
        assert details["lock_path"] == str(lock2.lock_path)
    finally:
        lock1.release()


# ---------------------------------------------------------------------------
# RepositoryLock — release / re-acquire / idempotence
# ---------------------------------------------------------------------------


def test_release_then_reacquire_succeeds(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    locks_dir = tmp_path / "locks"

    lock = locks.RepositoryLock(repo, locks_dir)
    lock.acquire()
    lock.release()
    lock.acquire()
    lock.release()


def test_double_release_is_safe(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    locks_dir = tmp_path / "locks"

    lock = locks.RepositoryLock(repo, locks_dir)
    lock.acquire()
    lock.release()
    lock.release()  # must not raise


def test_release_without_acquire_is_safe(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    locks_dir = tmp_path / "locks"

    lock = locks.RepositoryLock(repo, locks_dir)
    lock.release()  # must not raise


def test_lock_file_is_never_unlinked_on_release(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    locks_dir = tmp_path / "locks"

    lock = locks.RepositoryLock(repo, locks_dir)
    lock.acquire()
    assert lock.lock_path.exists()
    lock.release()
    assert lock.lock_path.exists()


# ---------------------------------------------------------------------------
# RepositoryLock — context manager
# ---------------------------------------------------------------------------


def test_context_manager_releases_on_normal_exit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    locks_dir = tmp_path / "locks"

    with locks.RepositoryLock(repo, locks_dir):
        pass

    # a fresh lock must be acquirable now that the context has exited
    second = locks.RepositoryLock(repo, locks_dir)
    second.acquire()
    second.release()


def test_context_manager_releases_on_exception(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    locks_dir = tmp_path / "locks"

    with pytest.raises(ValueError):
        with locks.RepositoryLock(repo, locks_dir):
            raise ValueError("boom")

    second = locks.RepositoryLock(repo, locks_dir)
    second.acquire()
    second.release()


def test_context_manager_returns_self(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    locks_dir = tmp_path / "locks"

    lock = locks.RepositoryLock(repo, locks_dir)
    with lock as ctx:
        assert ctx is lock
