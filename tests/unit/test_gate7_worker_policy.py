from __future__ import annotations

from pathlib import Path

from sol_claude_dispatcher.runner import CORE_DENIED_GIT_OPERATIONS


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_branch_creating_symbolic_head_prefixes_are_denied() -> None:
    required = {
        "Bash(git checkout:*)",
        "Bash(git switch:*)",
        "Bash(git symbolic-ref:*)",
        "Bash(git update-ref:*)",
    }

    assert required <= set(CORE_DENIED_GIT_OPERATIONS)


def test_git_restore_is_not_denied() -> None:
    assert "Bash(git restore:*)" not in CORE_DENIED_GIT_OPERATIONS


def test_worker_policy_requires_git_restore_mitigation() -> None:
    policy = (PROJECT_ROOT / "prompts" / "worker-policy.md").read_text()

    assert "git restore <path>" in policy
    assert "git restore --source <commit> <path>" in policy
    assert "do not retry with `git checkout --`" in policy
