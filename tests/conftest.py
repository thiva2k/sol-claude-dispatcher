"""Shared fixtures.

Nothing here touches the real environment: no Claude, no Codex, no user config,
no repository outside ``tmp_path``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A real, tiny git repository with one commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
    }
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
    (repo / "README.md").write_text("test repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True, env=env
    )
    return repo


@pytest.fixture
def valid_request_dict(git_repo: Path) -> dict:
    """A minimal well-formed ``TaskRequest`` payload."""
    return {
        "repository": {"root": str(git_repo), "base_ref": "HEAD"},
        "task": {
            "kind": "implementation",
            "objective": "Implement atomic configuration deployment.",
            "context": "Deployment can leave partial state after interruption.",
            "acceptance_criteria": [
                "Deployment must be atomic.",
                "Destination symlinks must be rejected.",
            ],
        },
        "scope": {
            "allowed_paths": ["src/deploy/**", "tests/**"],
            "forbidden_paths": [".github/**"],
        },
        "routing": {"model": "auto", "complexity": "high", "risk": "medium"},
        "execution": {"timeout_seconds": 1800, "max_turns": 40, "max_resume_count": 4},
    }


@pytest.fixture
def config_text(tmp_path: Path, git_repo: Path) -> str:
    """A valid config whose allowlist names the ``git_repo`` fixture exactly.

    It must be the repository's own git top level, never a parent directory
    (P0-2): ``validate_repository_root`` requires exact equality, so
    allowlisting ``tmp_path`` would refuse ``tmp_path/repo`` — and the obvious
    "fix" for that refusal is the one P0-2 exists to forbid.
    """
    return f"""
[dispatcher]
state_dir = "./state"
default_timeout_seconds = 1800
max_timeout_seconds = 3600
default_max_turns = 40
default_max_resume_count = 4

[models]
sonnet = "sonnet"
opus = "opus"
fable = "fable"

[routing]
default_model = "sonnet"

[security]
max_dispatch_depth = 1
allowed_repository_roots = ["{git_repo}"]

[validation]
run_dispatcher_validation = true
"""


@pytest.fixture
def config_file(tmp_path: Path, config_text: str) -> Path:
    path = tmp_path / "dispatcher.toml"
    path.write_text(config_text)
    return path
