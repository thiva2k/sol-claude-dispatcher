from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import SnapshotBudgetExceeded
from sol_claude_dispatcher.evidence import fssnap
from sol_claude_dispatcher.evidence.inventory import build_path_identity_set


def _blob_oid(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def test_content_hash_snapshot_preserves_hostile_raw_names_and_never_follows_symlinks(
    tmp_path: Path,
) -> None:
    root = os.fsencode(tmp_path)
    hostile = (
        b"caf\xc3\xa9.txt",
        b"new\nline.txt",
        b"tab\there.txt",
        b"nonutf8-\xff.txt",
    )
    for name in hostile:
        fd = os.open(root + b"/" + name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, b"payload:" + name)
        os.close(fd)
    os.symlink(b"../outside\xff", root + b"/dangling")

    snapshot = fssnap.capture_snapshot(
        root,
        role="task_worktree_start",
        fidelity="content_hash_all",
    )

    assert tuple(entry.path for entry in snapshot.entries) == tuple(
        sorted((*hostile, b"dangling"))
    )
    by_path = {bytes(entry.path): entry for entry in snapshot.entries}
    assert by_path[b"dangling"].kind == "symlink"
    assert by_path[b"dangling"].link_target == b"../outside\xff"
    assert by_path[b"dangling"].content_hash == _blob_oid(b"../outside\xff")
    assert snapshot.capture_complete is True


def test_task_worktree_fidelity_is_content_hash_all(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="task worktree"):
        fssnap.capture_snapshot(
            os.fsencode(tmp_path),
            role="task_worktree_start",
            fidelity="stat_identity",
        )


def test_mtime_forged_modification_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "same-size"
    path.write_bytes(b"AAAA")
    start = fssnap.capture_snapshot(
        os.fsencode(tmp_path), role="task_worktree_start"
    )
    original_mtime = path.stat().st_mtime_ns
    path.write_bytes(b"BBBB")
    os.utime(path, ns=(original_mtime, original_mtime))
    worker_exit = fssnap.capture_snapshot(
        os.fsencode(tmp_path), role="task_worktree_worker_exit"
    )

    delta = build_path_identity_set(start, worker_exit, base_commit="a" * 40)

    assert tuple(bytes(change.path) for change in delta.changes) == (b"same-size",)
    assert delta.changes[0].change == "modified"
    assert start.entries[0].size == worker_exit.entries[0].size
    assert start.entries[0].mtime_ns == worker_exit.entries[0].mtime_ns
    assert start.entries[0].content_hash != worker_exit.entries[0].content_hash


def test_primary_snapshot_may_use_explicit_stat_identity(tmp_path: Path) -> None:
    (tmp_path / "file").write_bytes(b"content")
    snapshot = fssnap.capture_snapshot(
        os.fsencode(tmp_path), role="primary_pre", fidelity="stat_identity"
    )
    assert snapshot.fidelity == "stat_identity"
    assert snapshot.entries[0].content_hash is None
    assert snapshot.capture_complete is True


def test_snapshot_budget_exhaustion_refuses_instead_of_returning_a_clean_snapshot(
    tmp_path: Path,
) -> None:
    (tmp_path / "a").write_bytes(b"a")
    (tmp_path / "b").write_bytes(b"b")

    with pytest.raises(SnapshotBudgetExceeded) as caught:
        fssnap.capture_snapshot(
            os.fsencode(tmp_path),
            role="task_worktree_start",
            max_entries=1,
        )

    assert caught.value.details["maximum_entries"] == 1
    assert caught.value.details["measured_entries"] == 2


def test_changed_during_read_is_recorded_as_incomplete_not_as_an_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "moving"
    path.write_bytes(b"aaaa")
    real = fssnap._hash_regular_file

    def mutate_after_read(raw_path: bytes, expected_size: int):
        answer = real(raw_path, expected_size)
        os.utime(raw_path, ns=(1, 1))
        return answer

    monkeypatch.setattr(fssnap, "_hash_regular_file", mutate_after_read)
    snapshot = fssnap.capture_snapshot(
        os.fsencode(tmp_path), role="task_worktree_worker_exit"
    )
    entry = snapshot.entries[0]
    assert entry.read_error == "changed_during_measurement"
    assert entry.content_hash is None
    assert snapshot.capture_complete is False
    assert snapshot.ambiguities == (entry.path,)


def test_repository_admin_tree_is_excluded_visibly(tmp_path: Path) -> None:
    (tmp_path / ".git" / "objects").mkdir(parents=True)
    (tmp_path / ".git" / "objects" / "secret").write_bytes(b"x")
    (tmp_path / "kept").write_bytes(b"y")

    snapshot = fssnap.capture_snapshot(
        os.fsencode(tmp_path), role="task_worktree_start"
    )

    assert snapshot.admin_excluded == (b".git",)
    assert tuple(bytes(entry.path) for entry in snapshot.entries) == (b"kept",)
