from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sol_claude_dispatcher.evidence.gitadmin import (
    capture_repository_administration,
    write_baseline,
)
from sol_claude_dispatcher.evidence.prepare import prepare_dispatch
from sol_claude_dispatcher.errors import (
    GitAdministrativeCaptureFailed,
    RepositoryAdministrationUnestablished,
)
from sol_claude_dispatcher.phase import begin_tool_execution


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_prepare_dispatch_builds_detached_sealed_authority(
    git_repo: Path, tmp_path: Path
) -> None:
    state = tmp_path / "state"
    write_baseline(state, capture_repository_administration(git_repo))
    hooks = tmp_path / "empty-hooks"
    hooks.mkdir()
    task_id = "11111111-1111-4111-8111-111111111111"
    target = tmp_path / "worktrees" / "sol-11111111"

    with begin_tool_execution("dispatch"):
        prepared = prepare_dispatch(
            repository_root=git_repo,
            state_root=state,
            worktree_path=target,
            task_id=task_id,
            base_commit=_head(git_repo),
            empty_hooks_path=hooks,
        )

    assert prepared.worktree.branch is None
    assert prepared.worktree_start.capture_complete is True
    assert prepared.primary_prepare.entries == prepared.primary_worker_start.entries
    assert prepared.seal.manifest.task_id == task_id
    assert prepared.seal.manifest_path.is_file()
    assert prepared.seal.identity_record is not None
    identity = prepared.seal.identity_record
    assert identity.task_id == task_id
    assert identity.base_commit == _head(git_repo)
    assert identity.base_commit_verified_by == "g1_byte_equality"
    assert identity.canonical_root == prepared.repository_authority.canonical_root
    assert identity.git_dir == prepared.repository_authority.git_dir
    assert identity.common_dir == prepared.repository_authority.common_dir
    assert identity.root_commit_provenance == "absent"
    assert identity.origin_url_provenance == "absent"
    assert identity.provenance == "sealed_at_prepare"
    assert identity.pins_applied == ("PIN1", "PIN2", "PIN3", "PIN4")
    assert "identity-record.json" in {
        item.relpath for item in prepared.seal.manifest.artefacts
    }
    journal = state / "preflight" / task_id / "git-invocations.jsonl"
    assert [
        json.loads(line)["permitted_by"]
        for line in journal.read_text().splitlines()
    ] == ["PREPARE_ADMIN_GATE", "G1", "G2", "G3", "G4", "G8", "G9"]


def test_prepare_refuses_without_operator_baseline_and_creates_no_worktree(
    git_repo: Path, tmp_path: Path
) -> None:
    hooks = tmp_path / "empty-hooks"
    hooks.mkdir()
    target = tmp_path / "worktrees" / "sol-22222222"
    with begin_tool_execution("dispatch"):
        with pytest.raises(RepositoryAdministrationUnestablished):
            prepare_dispatch(
                repository_root=git_repo,
                state_root=tmp_path / "state",
                worktree_path=target,
                task_id="22222222-2222-4222-8222-222222222222",
                base_commit=_head(git_repo),
                empty_hooks_path=hooks,
            )
    assert not target.exists()
