"""Integration fixtures: a real git repo, a real store, a fake worker (§32).

Nothing here spawns a real ``claude`` or ``codex``. ``claude.binary`` always
points at ``tests/fixtures/claude_worktree_shim.py``, which creates the isolated
worktree (the one CLI behaviour the fake cannot emulate) and then ``exec``s
``tests/fake_bin/claude``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sol_claude_dispatcher.config import load_config
from sol_claude_dispatcher.server import Dispatcher

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHIM = PROJECT_ROOT / "tests" / "fixtures" / "claude_worktree_shim.py"


@pytest.fixture
def fake_claude_log(tmp_path: Path) -> Path:
    """Path the fake binary appends one JSON record per invocation to."""
    return tmp_path / "fake-claude.log.jsonl"


@pytest.fixture
def worker_invocations(fake_claude_log: Path):
    """Callable returning every recorded fake-worker invocation, in order.

    The fake binary appends one JSON object per line, so tests can assert on
    what was passed *and* on what was stripped from the environment.
    """

    def _read() -> list[dict]:
        if not fake_claude_log.exists():
            return []
        return [
            json.loads(line)
            for line in fake_claude_log.read_text().splitlines()
            if line.strip()
        ]

    return _read


@pytest.fixture
def seeded_repo(git_repo: Path) -> Path:
    """``git_repo`` plus committed files inside the task's allowed paths.

    The fake worker overwrites tracked files, so the dispatcher observes a real
    unified diff rather than only untracked additions.
    """
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "PATH": "/usr/bin:/bin",
        "HOME": str(git_repo.parent),
    }
    (git_repo / "src" / "deploy").mkdir(parents=True)
    (git_repo / "src" / "deploy" / "deploy.py").write_text("def deploy():\n    ...\n")
    (git_repo / "tests").mkdir(exist_ok=True)
    (git_repo / "tests" / "test_deploy.py").write_text("def test_deploy():\n    ...\n")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed"], cwd=git_repo, check=True, env=env
    )
    return git_repo


@pytest.fixture
def integration_config_file(tmp_path: Path, git_repo: Path) -> Path:
    """A config allowlisting the test repository's exact git top level.

    ``project_root`` resolves to ``tmp_path`` (the config file's own directory),
    so ``state_dir`` lands in the temporary tree while the prompt/schema paths
    are absolute references back into the real project.

    The allowlist names ``tmp_path/repo`` — the ``git_repo`` fixture's exact git
    top level — and **not** ``tmp_path``. Under P0-2, allowlisting a parent
    directory no longer authorises the repositories inside it: every entry in
    ``allowed_repository_roots`` must be a repository's own top level. Widening
    this back to ``tmp_path`` would only pass by re-opening the descendant hole
    that finding closed.

    The dependency on ``git_repo`` is load-bearing twice over: it fixes the
    fixture ordering (``config.security.allowed_repository_roots`` entries must
    exist on disk when the config is loaded) and it makes the allowlisted path
    the same object the tests dispatch against.
    """
    path = tmp_path / "dispatcher.toml"
    path.write_text(
        f"""
[dispatcher]
state_dir = "./state"
default_timeout_seconds = 60
max_timeout_seconds = 120
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

[claude]
binary = "{SHIM}"
permission_mode = "auto"
worker_policy_path = "{PROJECT_ROOT}/prompts/worker-policy.md"
fable_policy_path = "{PROJECT_ROOT}/prompts/fable-reviewer-policy.md"
empty_mcp_config_path = "{PROJECT_ROOT}/config/empty-mcp.json"
worker_result_schema_path = "{PROJECT_ROOT}/schemas/worker-result.schema.json"
fable_review_schema_path = "{PROJECT_ROOT}/schemas/fable-review.schema.json"

[logging]
level = "WARNING"
"""
    )
    return path


@pytest.fixture
def integration_config(integration_config_file: Path):
    return load_config(integration_config_file)


@pytest.fixture
def dispatcher(integration_config) -> Dispatcher:
    return Dispatcher(integration_config)


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch, fake_claude_log: Path, tmp_path: Path):
    """Point the fake binary at this test's log and keep it deterministic.

    ``worker_environment`` copies ``os.environ`` into the child (minus secrets
    and ``SOL_DISPATCHER_*``), so setting these here is how the fake is
    steered.
    """
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(fake_claude_log))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")
    monkeypatch.setenv("FAKE_CLAUDE_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    monkeypatch.delenv("SOL_WORKER", raising=False)
    monkeypatch.delenv("SOL_DISPATCH_DEPTH", raising=False)
    return fake_claude_log


@pytest.fixture
def request_payload(seeded_repo: Path) -> dict:
    """A dispatch request scoped to ``src/deploy/**`` and ``tests/**``."""
    return {
        "repository": {"root": str(seeded_repo), "base_ref": "HEAD"},
        "task": {
            "kind": "implementation",
            "objective": "Implement atomic configuration deployment.",
            "context": "Deployment can leave partial state after interruption.",
            "acceptance_criteria": ["Deployment must be atomic."],
        },
        "scope": {
            "allowed_paths": ["src/deploy/**", "tests/**"],
            "forbidden_paths": [".github/**"],
        },
        "routing": {"model": "auto", "complexity": "medium", "risk": "medium"},
        "execution": {"timeout_seconds": 60, "max_turns": 40, "max_resume_count": 4},
    }
