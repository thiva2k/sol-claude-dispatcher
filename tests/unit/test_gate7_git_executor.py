from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from sol_claude_dispatcher.evidence.git_order import (
    DISPATCHER_GIT_ENV,
    GitPath,
)
from sol_claude_dispatcher.errors import GitBeforeEstablishment
from sol_claude_dispatcher.git import Gate7GitExecutor
from sol_claude_dispatcher.phase import begin_tool_execution


def _executor(
    repo: Path, tmp_path: Path, *, executable: Path | None = None
) -> Gate7GitExecutor:
    hooks = tmp_path / "empty-hooks"
    hooks.mkdir(exist_ok=True)
    return Gate7GitExecutor(
        repository_root=repo,
        journal_path=tmp_path / "git-invocations.jsonl",
        empty_hooks_path=hooks,
        path=GitPath.DISPATCH,
        git_executable=executable,
    )


def test_executor_refuses_before_current_prepare_establishment(
    git_repo: Path, tmp_path: Path
) -> None:
    executor = _executor(git_repo, tmp_path)
    with begin_tool_execution("dispatch"):
        with pytest.raises(GitBeforeEstablishment):
            executor.verify_exact_base("a" * 40)


def test_executor_constructs_child_environment_by_exact_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    probe = tmp_path / "git-probe"
    probe.write_text("#!/bin/sh\nexit 0\n")
    probe.chmod(0o755)
    executor = _executor(repo, tmp_path, executable=probe)
    captured: dict[str, str] = {}

    def fake_run(argv, **kwargs):
        captured.update(kwargs["env"])
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with begin_tool_execution("dispatch"):
        executor.establish()
        executor.run("G1", values={"base_commit": "a" * 40})
    assert captured == dict(DISPATCHER_GIT_ENV)


def test_real_dispatch_rows_create_a_detached_worktree(
    git_repo: Path, tmp_path: Path
) -> None:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    executor = _executor(git_repo, tmp_path)
    target = tmp_path / "worktrees" / "sol-11111111"

    with begin_tool_execution("dispatch"):
        executor.establish()
        assert executor.verify_exact_base(sha) == sha
        assert executor.capture_base_tree(sha)
        assert b"worktree " in executor.list_worktrees()
        created = executor.create_detached_worktree(target, sha)

    assert created.branch is None
    assert created.head_commit == sha
    assert (target / ".git").is_file()
    branch = subprocess.run(
        ["git", "symbolic-ref", "-q", "HEAD"],
        cwd=target,
        capture_output=True,
        text=True,
    )
    assert branch.returncode == 1
    rows = [record.permitted_by for record in executor.journal.records()]
    assert rows == ["PREPARE_ADMIN_GATE", "G1", "G2", "G3", "G4"]
