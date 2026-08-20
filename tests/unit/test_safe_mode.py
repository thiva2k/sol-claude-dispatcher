"""Gate 4.5 lane C — runner hardening.

Three things are pinned here, and each one closes a hole that was open at
commit ``c4c0d58``:

1. **``--safe-mode`` adoption** (GATE4.5-DECISION §2). The installed Claude
   Code 2.1.237 accepts ``--safe-mode``, which starts the child with *all*
   customizations disabled — CLAUDE.md, skills, plugins, hooks, MCP servers,
   custom commands and agents, output styles, workflows, themes, keybindings
   — while auth, model selection, built-in tools and permissions keep working
   (verbatim help text recorded in
   ``~/.claude/auto-mode/commissioning/SAFEMODE-VERIFICATION.md``). Without
   it, every dispatched worker inherits the operator's entire personal
   customization surface: a SessionStart hook from an enabled plugin runs
   before the worker reads its own policy, and every Skill on the box is
   resolvable. The dispatcher grants authority explicitly or not at all, so
   the flag is emitted for **both** roles.

2. **``Bash(git bisect:*)`` denied** (deny-set hole P1). ``git bisect run
   <cmd>`` executes an arbitrary command at every bisection step across
   *checked-out historical commits*, and ``git bisect start`` detaches HEAD.
   Neither is covered by the seven prefixes the core deny set carried before,
   and ``Bash`` is in ``worker_tools`` — so the instruction executed. It
   corrupts both the primary-tree invariant and the git evidence the
   dispatcher collects after a run.

3. **``Bash(gh:*)`` denied** (deny-set hole P2). ``gh api …`` performs
   *authenticated mutations of remote GitHub state* with the operator's
   credentials — a network-side write that no local git deny pattern reaches
   and that leaves no trace in the worktree evidence.

Both new denies are CORE, i.e. non-configurable: operator config may ADD deny
rules, never REMOVE one of these. The tests below prove that with an emptied
``disallowed_tools``.

Nothing in this file spawns the real Claude CLI (§32) — argv is asserted, not
executed. The one authorized live probe of the combined argv shape was run out
of band and recorded in ``SAFEMODE-COMBINED-PROBE.txt``.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from sol_claude_dispatcher.config import load_config_from_mapping
from sol_claude_dispatcher.models import TaskEnvelope, TaskRequest
from sol_claude_dispatcher.runner import (
    ALWAYS_DISALLOWED_TOOLS,
    CLI_CAPABILITIES,
    CORE_DENIED_GIT_OPERATIONS,
    FORBIDDEN_FLAGS,
    build_argv,
    build_fable_invocation,
    build_worker_invocation,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAKE_CLAUDE = PROJECT_ROOT / "tests" / "fake_bin" / "claude"
BASE_COMMIT = "a" * 40


# ---------------------------------------------------------------------------
# fixtures (same shape as tests/unit/test_runner.py — the fake binary is never
# actually executed here, but the config must resolve the real policy files)
# ---------------------------------------------------------------------------


@pytest.fixture
def dispatcher_config(tmp_path: Path):
    return load_config_from_mapping(
        {
            "dispatcher": {"state_dir": str(tmp_path / "state")},
            "models": {"sonnet": "sonnet", "opus": "opus", "fable": "fable"},
            "routing": {"default_model": "sonnet"},
            "security": {
                "max_dispatch_depth": 1,
                "allowed_repository_roots": [str(tmp_path)],
            },
            "validation": {"run_dispatcher_validation": True},
            "claude": {"binary": str(FAKE_CLAUDE)},
        },
        project_root=PROJECT_ROOT,
    )


@pytest.fixture
def envelope(valid_request_dict: dict, git_repo: Path) -> TaskEnvelope:
    request = TaskRequest.model_validate(valid_request_dict)
    return TaskEnvelope.from_request(
        request, canonical_root=str(git_repo), base_commit=BASE_COMMIT
    )


@pytest.fixture
def fake_env(tmp_path: Path) -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LANG": "C.UTF-8"}


def flag_value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def flag_values(argv: list[str], flag: str) -> list[str]:
    start = argv.index(flag) + 1
    out: list[str] = []
    for token in argv[start:]:
        if token.startswith("-"):
            break
        out.append(token)
    return out


def worker_argv(config, envelope, cwd, env, **kwargs) -> list[str]:
    return build_argv(
        build_worker_invocation(
            envelope,
            config,
            model="sonnet",
            session_id=str(uuid.uuid4()),
            prompt="Implement the objective.",
            cwd=cwd,
            base_env=env,
            **kwargs,
        )
    )


def fable_argv(config, envelope, cwd, env) -> list[str]:
    return build_argv(
        build_fable_invocation(
            envelope,
            config,
            session_id=str(uuid.uuid4()),
            prompt="Review the diff.",
            cwd=cwd,
            base_env=env,
        )
    )


# ===========================================================================
# 1. --safe-mode adoption (§2)
# ===========================================================================


def test_safe_mode_capability_is_declared_and_on():
    """The capability gate exists and is enabled for the installed 2.1.237."""
    assert CLI_CAPABILITIES["safe_mode"] is True


def test_worker_argv_carries_safe_mode(dispatcher_config, envelope, git_repo, fake_env):
    argv = worker_argv(dispatcher_config, envelope, git_repo, fake_env)
    assert "--safe-mode" in argv
    assert argv.count("--safe-mode") == 1


def test_fable_argv_carries_safe_mode(dispatcher_config, envelope, git_repo, fake_env):
    argv = fable_argv(dispatcher_config, envelope, git_repo, fake_env)
    assert "--safe-mode" in argv
    assert argv.count("--safe-mode") == 1


def test_resume_argv_carries_safe_mode(dispatcher_config, envelope, git_repo, fake_env):
    """§15: a resumed turn must not silently regain the customization surface."""
    argv = worker_argv(
        dispatcher_config,
        envelope,
        git_repo,
        fake_env,
        resume_session_id="22222222-2222-4222-8222-222222222222",
    )
    assert "--resume" in argv
    assert "--safe-mode" in argv


def test_safe_mode_is_capability_gated(
    dispatcher_config, envelope, git_repo, fake_env, monkeypatch
):
    """Flip the gate off and the flag disappears — no call site knows about it.

    This is the same pattern ``max_turns`` uses: when a future CLI release
    renames or removes the flag, the dispatcher stops emitting it by editing
    one dict entry rather than by touching the builders.
    """
    monkeypatch.setitem(CLI_CAPABILITIES, "safe_mode", False)
    assert "--safe-mode" not in worker_argv(dispatcher_config, envelope, git_repo, fake_env)
    assert "--safe-mode" not in fable_argv(dispatcher_config, envelope, git_repo, fake_env)


def test_bare_is_never_emitted(dispatcher_config, envelope, git_repo, fake_env):
    """``--bare`` is NOT a substitute for ``--safe-mode`` and must never appear.

    Its own help text says Skills still resolve via ``/skill-name`` — i.e. it
    leaves open exactly the surface §2 requires closed. Confusing the two would
    look like hardening while re-admitting every Skill on the box.
    """
    for argv in (
        worker_argv(dispatcher_config, envelope, git_repo, fake_env),
        fable_argv(dispatcher_config, envelope, git_repo, fake_env),
    ):
        assert "--bare" not in argv


def test_safe_mode_does_not_displace_the_mcp_flags(
    dispatcher_config, envelope, git_repo, fake_env
):
    """Defence in depth: both mechanisms converge on zero MCP, and both stay.

    ``--safe-mode`` claims to disable MCP servers outright; ``--strict-mcp-config``
    plus an empty ``--mcp-config`` independently guarantees the same end state.
    Keeping both means a CLI release that narrows either one still leaves the
    worker with no MCP tools. Redundant on purpose — do not "simplify" this.
    """
    for argv in (
        worker_argv(dispatcher_config, envelope, git_repo, fake_env),
        fable_argv(dispatcher_config, envelope, git_repo, fake_env),
    ):
        assert "--safe-mode" in argv
        assert "--strict-mcp-config" in argv
        assert flag_value(argv, "--mcp-config").endswith("config/empty-mcp.json")


# ===========================================================================
# 2. deny-set hole P1 — git bisect
# ===========================================================================


def test_git_bisect_is_in_the_core_deny_set():
    assert "Bash(git bisect:*)" in CORE_DENIED_GIT_OPERATIONS
    assert "Bash(git bisect:*)" in ALWAYS_DISALLOWED_TOOLS


def test_worker_argv_denies_git_bisect(dispatcher_config, envelope, git_repo, fake_env):
    argv = worker_argv(dispatcher_config, envelope, git_repo, fake_env)
    assert "Bash(git bisect:*)" in flag_values(argv, "--disallowedTools")


def test_fable_argv_denies_git_bisect(dispatcher_config, envelope, git_repo, fake_env):
    argv = fable_argv(dispatcher_config, envelope, git_repo, fake_env)
    assert "Bash(git bisect:*)" in flag_values(argv, "--disallowedTools")


def test_operator_config_cannot_remove_the_git_bisect_deny(
    dispatcher_config, envelope, git_repo, fake_env
):
    dispatcher_config.claude.disallowed_tools = []
    argv = worker_argv(dispatcher_config, envelope, git_repo, fake_env)
    assert "Bash(git bisect:*)" in flag_values(argv, "--disallowedTools")


# ===========================================================================
# 3. deny-set hole P2 — gh
# ===========================================================================


def test_gh_is_in_the_core_deny_set():
    assert "Bash(gh:*)" in ALWAYS_DISALLOWED_TOOLS


def test_worker_argv_denies_gh(dispatcher_config, envelope, git_repo, fake_env):
    argv = worker_argv(dispatcher_config, envelope, git_repo, fake_env)
    assert "Bash(gh:*)" in flag_values(argv, "--disallowedTools")


def test_fable_argv_denies_gh(dispatcher_config, envelope, git_repo, fake_env):
    argv = fable_argv(dispatcher_config, envelope, git_repo, fake_env)
    assert "Bash(gh:*)" in flag_values(argv, "--disallowedTools")


def test_operator_config_cannot_remove_the_gh_deny(
    dispatcher_config, envelope, git_repo, fake_env
):
    dispatcher_config.claude.disallowed_tools = []
    argv = worker_argv(dispatcher_config, envelope, git_repo, fake_env)
    assert "Bash(gh:*)" in flag_values(argv, "--disallowedTools")


def test_operator_config_cannot_remove_either_new_core_deny_for_fable(
    dispatcher_config, envelope, git_repo, fake_env
):
    dispatcher_config.claude.disallowed_tools = []
    denied = flag_values(fable_argv(dispatcher_config, envelope, git_repo, fake_env),
                         "--disallowedTools")
    assert "Bash(git bisect:*)" in denied
    assert "Bash(gh:*)" in denied


# ===========================================================================
# 4. §14 full invariant sweep of the emitted argv, both roles
# ===========================================================================

#: Every deny pattern §14 requires, spelled out literally rather than derived
#: from the module under test — a refactor that empties
#: ``ALWAYS_DISALLOWED_TOOLS`` must fail here, not pass vacuously.
REQUIRED_DENIES: tuple[str, ...] = (
    "mcp__*",
    "Agent",
    "Task",
    "Bash(claude:*)",
    "Bash(codex:*)",
    "Bash(git push:*)",
    "Bash(git merge:*)",
    "Bash(git rebase:*)",
    "Bash(git commit:*)",
    "Bash(git reset:*)",
    "Bash(git clean:*)",
    "Bash(git worktree:*)",
    "Bash(git bisect:*)",
    "Bash(gh:*)",
)


def _sweep(argv: list[str]) -> None:
    """Assert the §14 invariant set on one emitted argv."""
    assert "--safe-mode" in argv
    assert "--strict-mcp-config" in argv
    assert flag_value(argv, "--mcp-config").endswith("config/empty-mcp.json")

    denied = flag_values(argv, "--disallowedTools")
    for pattern in REQUIRED_DENIES:
        assert pattern in denied, pattern

    assert FORBIDDEN_FLAGS.isdisjoint(argv)
    assert "--dangerously-skip-permissions" not in argv
    assert flag_value(argv, "--permission-mode") != "bypassPermissions"


def test_worker_argv_invariant_sweep(dispatcher_config, envelope, git_repo, fake_env):
    argv = worker_argv(dispatcher_config, envelope, git_repo, fake_env)
    _sweep(argv)
    granted = flag_values(argv, "--tools")
    # §14: the native Skill tool is never granted — projected guidance is inert
    # text in the prompt, not a runtime capability.
    assert "Skill" not in granted
    assert "Agent" not in granted and "Task" not in granted
    assert "Skill" not in dispatcher_config.claude.worker_tools


def test_fable_argv_invariant_sweep(dispatcher_config, envelope, git_repo, fake_env):
    argv = fable_argv(dispatcher_config, envelope, git_repo, fake_env)
    _sweep(argv)
    # §14: Fable stays Read/Glob/Grep only.
    assert flag_values(argv, "--tools") == ["Read", "Glob", "Grep"]


def test_resume_argv_invariant_sweep(dispatcher_config, envelope, git_repo, fake_env):
    argv = worker_argv(
        dispatcher_config,
        envelope,
        git_repo,
        fake_env,
        resume_session_id="22222222-2222-4222-8222-222222222222",
    )
    _sweep(argv)
    assert "--worktree" not in argv
