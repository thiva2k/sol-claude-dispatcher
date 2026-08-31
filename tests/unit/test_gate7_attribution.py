from __future__ import annotations

from dataclasses import replace

import pytest

from sol_claude_dispatcher.errors import AttributionClosureViolated
from sol_claude_dispatcher.evidence.attribution import (
    _assert_attribution_closure,
    attribute_snapshots,
)
from sol_claude_dispatcher.evidence.fssnap import FsEntry, FsSnapshot
from sol_claude_dispatcher.evidence.inventory import RepoPath


def _entry(path: bytes, value: str) -> FsEntry:
    return FsEntry(
        path=RepoPath(path),
        kind="regular",
        perm=0o644,
        size=1,
        mtime_ns=1,
        ctime_ns=1,
        ino=1,
        dev=1,
        nlink=1,
        content_hash=value * 40,
        link_target=None,
        read_error=None,
    )


def _snap(role: str, values: dict[bytes, str]) -> FsSnapshot:
    return FsSnapshot.from_entries(
        root=b"/repo",
        role=role,
        entries=tuple(_entry(path, value) for path, value in sorted(values.items())),
        fidelity="content_hash_all",
    )


def test_final_delta_is_contained_in_the_union() -> None:
    start = _snap(
        "task_worktree_start",
        {b"worker": "a", b"both": "a", b"reverted": "a"},
    )
    worker = _snap(
        "task_worktree_worker_exit",
        {b"worker": "b", b"both": "b", b"reverted": "b"},
    )
    post = _snap(
        "task_worktree_post_validation",
        {
            b"worker": "b",
            b"both": "c",
            b"reverted": "a",
            b"validation": "d",
        },
    )

    result = attribute_snapshots(start, worker, post, base_commit="f" * 40)

    worker_paths = {bytes(c.path) for c in result.worker_delta.changes}
    validation_paths = {bytes(c.path) for c in result.validation_delta.changes}
    final_paths = {bytes(c.path) for c in result.final_delta.changes}
    assert worker_paths == {b"worker", b"both", b"reverted"}
    assert validation_paths == {b"both", b"reverted", b"validation"}
    assert final_paths == {b"worker", b"both", b"validation"}
    assert tuple(map(bytes, result.worker_only)) == (b"worker",)
    assert tuple(map(bytes, result.validation_only)) == (b"validation",)
    assert tuple(map(bytes, result.both_authors)) == (b"both", b"reverted")
    assert tuple(map(bytes, result.validation_reverted)) == (b"reverted",)
    assert final_paths <= worker_paths | validation_paths
    assert all((worker_paths, validation_paths, final_paths))
    assert result.verdict == "attributable"
    assert result.method == "three_snapshot_identity_symmetric_difference"
    assert {bytes(item.path): item.author for item in result.paths} == {
        b"both": "both",
        b"reverted": "both",
        b"validation": "validation",
        b"worker": "worker",
    }


def test_no_validation_uses_worker_delta_without_inventing_a_fourth_snapshot() -> None:
    start = _snap("task_worktree_start", {b"x": "a"})
    worker = _snap("task_worktree_worker_exit", {b"x": "b"})
    result = attribute_snapshots(start, worker, None, base_commit="f" * 40)
    assert result.post_validation_digest is None
    assert result.validation_delta is None
    assert result.final_delta is None
    assert tuple(map(bytes, result.worker_only)) == (b"x",)
    assert result.verdict == "attributable"


def test_worker_exit_measurement_ambiguity_cannot_report_attributable() -> None:
    start = _snap("task_worktree_start", {b"x": "a"})
    worker = _snap("task_worktree_worker_exit", {b"x": "b"})
    bad_entry = replace(worker.entries[0], content_hash=None, read_error="changed_during_measurement")
    worker = FsSnapshot.from_entries(
        root=worker.root,
        role=worker.role,
        entries=(bad_entry,),
        fidelity=worker.fidelity,
    )

    result = attribute_snapshots(start, worker, None, base_commit="f" * 40)

    assert result.verdict == "worker_ambiguous"
    assert len(result.ambiguous) == 1
    assert result.ambiguous[0].path == RepoPath(b"x")
    assert result.paths[0].author == "ambiguous"


def test_closure_theorem_holds_under_a_changed_ignored_path() -> None:
    start = _snap("task_worktree_start", {b"ignored/cache": "a"})
    worker = _snap("task_worktree_worker_exit", {b"ignored/cache": "b"})
    result = attribute_snapshots(
        start,
        worker,
        None,
        base_commit="f" * 40,
        ignored_paths={RepoPath(b"ignored/cache")},
    )
    assert tuple(bytes(c.path) for c in result.worker_delta.changes) == (
        b"ignored/cache",
    )
    assert result.worker_delta.changes[0].ignored_by_base is True


def test_closure_violation_raises_instead_of_logging_and_continuing() -> None:
    with pytest.raises(AttributionClosureViolated) as caught:
        _assert_attribution_closure(
            final_paths={RepoPath(b"escaped")},
            worker_paths=set(),
            validation_paths=set(),
        )
    assert caught.value.details["unattributed_count"] == 1
