"""Focused acceptance tests for Gate 7's sealed resume PREPARE path."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from sol_claude_dispatcher.evidence.gitadmin import (
    capture_repository_administration,
    write_baseline,
)
from sol_claude_dispatcher.evidence.identity import capture_repository_authority
from sol_claude_dispatcher.evidence.prepare import (
    capture_primary_head,
    prepare_dispatch,
    prepare_resume,
)
from sol_claude_dispatcher.errors import (
    BaseObjectVerificationFailed,
    FilesystemSnapshotFailed,
    RepositoryIdentityUnsealed,
    WorktreeBaseMismatch,
)
from sol_claude_dispatcher.phase import begin_tool_execution


TASK_ID = "77777777-7777-4777-8777-777777777777"


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _dispatch_preparation(git_repo: Path, tmp_path: Path):
    state = tmp_path / "state"
    hooks = tmp_path / "empty-hooks"
    hooks.mkdir()
    write_baseline(state, capture_repository_administration(git_repo))
    with begin_tool_execution("dispatch"):
        prepared = prepare_dispatch(
            repository_root=git_repo,
            state_root=state,
            worktree_path=tmp_path / "worktrees" / "sol-77777777",
            task_id=TASK_ID,
            base_commit=_head(git_repo),
            empty_hooks_path=hooks,
        )
    return prepared, state, hooks


def test_primary_head_snapshot_detects_a_size_preserving_ref_change(
    git_repo: Path,
) -> None:
    authority = capture_repository_authority(git_repo, authorized_root=git_repo)
    before = capture_primary_head(authority)
    assert before.ref_path is not None
    ref_path = Path(os.fsdecode(before.ref_path))
    original = ref_path.read_bytes()
    replacement = (b"f" if original[:1] != b"f" else b"e") + original[1:]
    assert len(replacement) == len(original)
    ref_path.write_bytes(replacement)

    after = capture_primary_head(authority)

    assert after.digest != before.digest
    assert after.ref_bytes == replacement


def test_primary_head_snapshot_refuses_a_symlinked_loose_ref(
    git_repo: Path, tmp_path: Path
) -> None:
    authority = capture_repository_authority(git_repo, authorized_root=git_repo)
    before = capture_primary_head(authority)
    assert before.ref_path is not None
    ref_path = Path(os.fsdecode(before.ref_path))
    outside = tmp_path / "outside-ref"
    outside.write_bytes(before.ref_bytes or b"")
    ref_path.unlink()
    ref_path.symlink_to(outside)

    with pytest.raises(FilesystemSnapshotFailed, match="not a regular file"):
        capture_primary_head(authority)


def _resume(prepared, state: Path, hooks: Path):
    with begin_tool_execution("resume", task_id=TASK_ID):
        return prepare_resume(
            repository_root=Path(os.fsdecode(prepared.repository_authority.canonical_root)),
            state_root=state,
            worktree_path=prepared.worktree.path,
            task_id=TASK_ID,
            run_index=2,
            base_commit=prepared.base_commit,
            seal_path=prepared.seal.materialisation,
            empty_hooks_path=hooks,
        )


def test_prepare_resume_executes_only_the_declared_g1_prime_row(
    git_repo: Path, tmp_path: Path
) -> None:
    prepared, state, hooks = _dispatch_preparation(git_repo, tmp_path)

    resumed = _resume(prepared, state, hooks)

    assert resumed.worktree.path == prepared.worktree.path
    assert resumed.worktree.head_commit == prepared.base_commit
    assert resumed.worktree.branch is None
    assert resumed.worktree_start.capture_complete is True
    assert resumed.primary_prepare.entries == resumed.primary_worker_start.entries
    assert resumed.admin_worker_start.registration_exact_entries
    assert resumed.admin_worker_start.registration_report_entries
    assert {
        entry.relative_path.rsplit("/", 1)[-1]
        for entry in resumed.admin_worker_start.registration_exact_entries
    } >= {"HEAD", "commondir", "gitdir"}
    rows = [
        json.loads(line)
        for line in resumed.git_journal_path.read_text().splitlines()
        if line.strip()
    ]
    assert [row["permitted_by"] for row in rows] == [
        "PREPARE_ADMIN_GATE",
        "G1_PRIME",
    ]
    assert [row["subcommand"] for row in rows] == [
        None,
        "worktree",
    ]
    assert [row["path"] for row in rows] == ["resume", "resume"]
    assert rows[1]["cwd_role"] == "primary"


def test_prepare_resume_refuses_an_absent_identity_before_git(
    git_repo: Path, tmp_path: Path
) -> None:
    prepared, state, hooks = _dispatch_preparation(git_repo, tmp_path)
    (prepared.seal.materialisation / "identity-record.json").unlink()

    with pytest.raises(RepositoryIdentityUnsealed, match="identity"):
        _resume(prepared, state, hooks)

    assert not (state / "tasks" / TASK_ID / "runs" / "0002").exists()


def test_prepare_resume_refuses_live_repository_authority_drift_before_git(
    git_repo: Path, tmp_path: Path
) -> None:
    prepared, state, hooks = _dispatch_preparation(git_repo, tmp_path)
    before_mode = os.lstat(git_repo).st_mode
    # Repository-root mode is part of the raw sealed authority. Changing only
    # it leaves Git's logical view intact, proving the raw comparison is the
    # load-bearing refusal rather than a Git-derived repository check.
    os.chmod(git_repo, 0o700 if (before_mode & 0o777) != 0o700 else 0o755)
    try:
        with pytest.raises(
            BaseObjectVerificationFailed,
            match="primary repository authority differs",
        ):
            _resume(prepared, state, hooks)
    finally:
        os.chmod(git_repo, before_mode & 0o7777)

    assert not (state / "tasks" / TASK_ID / "runs" / "0002").exists()


def test_prepare_resume_refuses_live_worktree_authority_drift_before_git(
    git_repo: Path, tmp_path: Path
) -> None:
    prepared, state, hooks = _dispatch_preparation(git_repo, tmp_path)
    head_path = Path(os.fsdecode(prepared.worktree_authority.gitdir_realpath)) / "HEAD"
    original = head_path.read_bytes()
    replacement = ("f" * 40 + "\n").encode("ascii")
    assert replacement != original
    head_path.write_bytes(replacement)

    with pytest.raises(
        WorktreeBaseMismatch,
        match="worktree authority differs",
    ) as raised:
        _resume(prepared, state, hooks)

    assert raised.value.details["verdict"] == "base_mismatch"
    assert not (state / "tasks" / TASK_ID / "runs" / "0002").exists()
