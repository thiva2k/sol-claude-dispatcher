"""Execution-boundary regression tests (findings P1-6, P1-8, P1-9).

Three boundaries are pinned here, each of which was previously either
fail-open or merely advisory:

* **P1-6** — a dispatcher-run validation subprocess must never inherit the
  dispatcher's own environment. Secrets are stripped, ordinary settings are
  preserved, and the child is *not* labelled as a worker.
* **P1-8** — worker output beyond the in-memory retention cap must not be
  silently discarded. The structured result stays recoverable, truncation is
  reported as a fact, and the complete stream is spooled to disk when the
  caller supplies a path.
* **P1-9** — the V1-prohibited git operations are code-level invariants, not
  configuration. Operator config may add deny rules; it can never remove one.

Every subprocess in this file is either ``tests/fake_bin/claude`` or a plain
``sys.executable`` one-liner. Nothing here may spawn the real Claude CLI (§32).
"""

from __future__ import annotations

import json
import os
import stat
import sys
import uuid
from pathlib import Path

import pytest

from sol_claude_dispatcher.config import load_config_from_mapping
from sol_claude_dispatcher.errors import ConfigurationError, InternalDispatcherError
from sol_claude_dispatcher.models import (
    ConstraintsSpec,
    TaskEnvelope,
    TaskRequest,
    ValidationCommand,
)
from sol_claude_dispatcher.results import parse_worker_result
from sol_claude_dispatcher.runner import (
    ALWAYS_DISALLOWED_TOOLS,
    CORE_DENIED_GIT_OPERATIONS,
    MAX_CAPTURED_BYTES,
    WorkerInvocation,
    build_argv,
    build_fable_invocation,
    build_worker_invocation,
    run_worker,
)
from sol_claude_dispatcher.validation import (
    run_validation_command,
    run_validations,
    validation_environment,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAKE_CLAUDE = PROJECT_ROOT / "tests" / "fake_bin" / "claude"
BASE_COMMIT = "a" * 40

#: A tiny program that dumps its own environment as JSON. Used instead of
#: ``env`` so the test does not depend on coreutils layout.
ENV_PRINTER = "import json, os, sys; sys.stdout.write(json.dumps(dict(os.environ)))"


# ---------------------------------------------------------------------------
# fixtures
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
def dirty_environ(monkeypatch, tmp_path: Path) -> None:
    """Give the *dispatcher process* a realistically contaminated environment."""
    monkeypatch.setenv("DEPLOY_API_KEY", "deploy-key-do-not-leak")
    monkeypatch.setenv("AUTH_TOKEN", "auth-token-do-not-leak")
    monkeypatch.setenv("SOL_DISPATCHER_SECRET", "dispatcher-secret-do-not-leak")
    monkeypatch.setenv("SOL_DISPATCHER_CONFIG", "/etc/dispatcher.toml")
    monkeypatch.setenv("MY_PASSWORD", "hunter2")
    monkeypatch.setenv("SERVICE_CREDENTIAL", "cred")
    monkeypatch.setenv("HARMLESS_SETTING", "keep-me")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("TERM", "dumb")
    monkeypatch.setenv("HOME", str(tmp_path))


def _envelope_with_commands(git_repo: Path, argv_list: list[list[str]]) -> TaskEnvelope:
    request = TaskRequest.model_validate(
        {
            "repository": {"root": str(git_repo), "base_ref": "HEAD"},
            "task": {"kind": "implementation", "objective": "Do the thing."},
            "validation": {
                "commands": [{"argv": argv, "timeout_seconds": 15} for argv in argv_list]
            },
        }
    )
    return TaskEnvelope.from_request(
        request, canonical_root=str(git_repo.resolve()), base_commit=BASE_COMMIT
    )


def _flag_values(argv: list[str], flag: str) -> list[str]:
    start = argv.index(flag) + 1
    out: list[str] = []
    for token in argv[start:]:
        if token.startswith("-"):
            break
        out.append(token)
    return out


# ===========================================================================
# P1-6 — validation environment sanitization
# ===========================================================================


def test_validation_environment_strips_secret_shaped_keys():
    env = validation_environment(
        {
            "PATH": "/usr/bin",
            "DEPLOY_API_KEY": "x",
            "AUTH_TOKEN": "x",
            "MY_PASSWORD": "x",
            "SERVICE_CREDENTIAL": "x",
            "SSH_PRIVATE_KEY": "x",
            "SESSION_COOKIE": "x",
            "SOME_AUTHORIZATION": "x",
            "APP_SECRET": "x",
            "MY_APIKEY": "x",
        }
    )
    assert set(env) == {"PATH"}


def test_validation_environment_strips_dispatcher_internal_keys():
    env = validation_environment(
        {"PATH": "/usr/bin", "SOL_DISPATCHER_CONFIG": "/etc/x.toml"}
    )
    assert "SOL_DISPATCHER_CONFIG" not in env
    assert env["PATH"] == "/usr/bin"


def test_validation_environment_keeps_runtime_essentials():
    base = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/home/dev",
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "HARMLESS_SETTING": "keep-me",
    }
    assert validation_environment(base) == base


def test_validation_environment_does_not_label_the_child_a_worker():
    """A validation command is dispatcher-run, not worker-run.

    Setting ``SOL_WORKER=1`` here would both misreport provenance and break any
    validation suite that legitimately exercises dispatcher code paths, so the
    marker is neither injected nor forwarded.
    """
    env = validation_environment(
        {"PATH": "/usr/bin", "SOL_WORKER": "1", "SOL_DISPATCH_DEPTH": "1", "SOL_TASK_ID": "t"}
    )
    assert "SOL_WORKER" not in env
    assert "SOL_DISPATCH_DEPTH" not in env
    assert "SOL_TASK_ID" not in env


async def test_validation_subprocess_does_not_inherit_dispatcher_secrets(
    tmp_path, dirty_environ
):
    """The real regression: default env must be sanitized, never inherited."""
    cmd = ValidationCommand(argv=[sys.executable, "-c", ENV_PRINTER], timeout_seconds=15)
    result = await run_validation_command(cmd, tmp_path)
    assert result.passed is True
    child_env = json.loads(result.stdout_tail)

    assert "DEPLOY_API_KEY" not in child_env
    assert "AUTH_TOKEN" not in child_env
    assert "SOL_DISPATCHER_SECRET" not in child_env
    assert "SOL_DISPATCHER_CONFIG" not in child_env
    assert "MY_PASSWORD" not in child_env
    assert "SERVICE_CREDENTIAL" not in child_env
    # ...and ordinary settings survive.
    assert child_env["HARMLESS_SETTING"] == "keep-me"
    assert child_env["LANG"] == "C.UTF-8"
    assert "PATH" in child_env


async def test_run_validations_sanitizes_the_environment_for_every_command(
    git_repo, tmp_path, dirty_environ, dispatcher_config
):
    envelope = _envelope_with_commands(
        git_repo, [[sys.executable, "-c", ENV_PRINTER], [sys.executable, "-c", ENV_PRINTER]]
    )
    results = await run_validations(envelope, git_repo, dispatcher_config)
    assert len(results) == 2
    for result in results:
        child_env = json.loads(result.stdout_tail)
        assert "DEPLOY_API_KEY" not in child_env
        assert "SOL_DISPATCHER_SECRET" not in child_env
        assert child_env["HARMLESS_SETTING"] == "keep-me"


async def test_explicitly_supplied_validation_env_is_honoured(tmp_path):
    cmd = ValidationCommand(argv=[sys.executable, "-c", ENV_PRINTER], timeout_seconds=15)
    result = await run_validation_command(
        cmd, tmp_path, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "EXPLICIT": "1"}
    )
    child_env = json.loads(result.stdout_tail)
    assert child_env["EXPLICIT"] == "1"


async def test_validation_timeout_still_preserves_partial_output(tmp_path, monkeypatch):
    """Adjacent race: a timed-out command used to lose everything it wrote."""
    from sol_claude_dispatcher import validation as validation_module

    monkeypatch.setattr(validation_module, "_GRACE_SECONDS", 0.3)
    script = (
        "import signal, sys, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "sys.stdout.write('PARTIAL-EVIDENCE-BEFORE-TIMEOUT'); sys.stdout.flush(); "
        "sys.stderr.write('PARTIAL-STDERR'); sys.stderr.flush(); "
        "time.sleep(30)"
    )
    cmd = ValidationCommand(argv=[sys.executable, "-c", script], timeout_seconds=1)
    result = await run_validation_command(cmd, tmp_path)
    assert result.timed_out is True
    assert "PARTIAL-EVIDENCE-BEFORE-TIMEOUT" in result.stdout_tail
    assert "PARTIAL-STDERR" in result.stderr_tail


async def test_validation_output_over_the_cap_is_marked_truncated(tmp_path):
    script = "import sys; sys.stdout.write('x' * 200000); sys.stdout.write('TAIL-MARKER')"
    cmd = ValidationCommand(argv=[sys.executable, "-c", script], timeout_seconds=15)
    result = await run_validation_command(cmd, tmp_path)
    assert result.stdout_truncated is True
    assert result.stdout_tail.endswith("TAIL-MARKER")


# ===========================================================================
# P1-8 — worker output preservation
# ===========================================================================


def _huge_output_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "FAKE_CLAUDE_MODE": "huge-output",
    }
    env.update(extra)
    return env


def _invocation(tmp_path: Path, env: dict[str, str], **extra) -> WorkerInvocation:
    return WorkerInvocation(
        binary=str(FAKE_CLAUDE),
        model="sonnet",
        session_id=str(uuid.uuid4()),
        cwd=tmp_path,
        prompt="do the thing",
        timeout_seconds=60,
        role="implementer",
        disallowed_tools=list(ALWAYS_DISALLOWED_TOOLS),
        env=env,
        **extra,
    )


async def test_huge_worker_stdout_still_yields_the_structured_result(tmp_path):
    """Output larger than the cap with the JSON result at the very END."""
    env = _huge_output_env(tmp_path, FAKE_CLAUDE_NOISE_BYTES=str(3 * MAX_CAPTURED_BYTES))
    run = await run_worker(_invocation(tmp_path, env))

    assert run.exit_code == 0
    assert run.stdout_total_bytes > 3 * MAX_CAPTURED_BYTES
    assert run.stdout_truncated is True
    # The structured result survives and parses.
    result = parse_worker_result(run.stdout_for_parsing)
    assert result.status == "completed"


async def test_huge_worker_stdout_truncation_is_reported_not_silent(tmp_path):
    env = _huge_output_env(tmp_path, FAKE_CLAUDE_NOISE_BYTES=str(3 * MAX_CAPTURED_BYTES))
    run = await run_worker(_invocation(tmp_path, env))

    assert run.stdout_truncated is True
    assert run.stdout_total_bytes > len(run.stdout.encode("utf-8", errors="replace"))
    # The retained evidence says so in-band, so nobody can mistake it for the
    # complete stream.
    assert "[dispatcher]" in run.stdout and "omitted" in run.stdout


async def test_worker_stdout_spool_holds_the_complete_stream(tmp_path):
    spool = tmp_path / "stdout.raw"
    env = _huge_output_env(tmp_path, FAKE_CLAUDE_NOISE_BYTES=str(3 * MAX_CAPTURED_BYTES))
    run = await run_worker(_invocation(tmp_path, env, stdout_spool_path=spool))

    assert run.stdout_spool_path == str(spool)
    assert spool.stat().st_size == run.stdout_total_bytes
    assert stat.S_IMODE(spool.stat().st_mode) == 0o600
    assert spool.read_bytes().rstrip().endswith(b"}")
    # Recovery uses the complete spooled stream, not just the retained tail.
    assert parse_worker_result(run.stdout_for_parsing).status == "completed"


async def test_huge_worker_stderr_is_bounded_marked_and_spooled(tmp_path):
    spool = tmp_path / "stderr.raw"
    env = _huge_output_env(
        tmp_path,
        FAKE_CLAUDE_NOISE_BYTES="1000",
        FAKE_CLAUDE_STDERR_NOISE_BYTES=str(3 * MAX_CAPTURED_BYTES),
    )
    run = await run_worker(_invocation(tmp_path, env, stderr_spool_path=spool))

    assert run.stderr_truncated is True
    assert run.stderr_total_bytes > 3 * MAX_CAPTURED_BYTES
    # Bounded in memory: head + tail + marker, never the whole stream.
    assert len(run.stderr.encode("utf-8", errors="replace")) <= 2 * MAX_CAPTURED_BYTES + 512
    assert spool.stat().st_size > 0


async def test_worker_stderr_spool_is_redacted(tmp_path):
    spool = tmp_path / "stderr.raw"
    env = _huge_output_env(
        tmp_path,
        FAKE_CLAUDE_NOISE_BYTES="10",
        FAKE_CLAUDE_STDERR_TEXT="GITHUB_TOKEN=ghp_supersecretvalue\n",
    )
    run = await run_worker(_invocation(tmp_path, env, stderr_spool_path=spool))

    spooled = spool.read_text()
    assert "ghp_supersecretvalue" not in spooled
    assert "***REDACTED***" in spooled
    assert run.stderr_spool_path == str(spool)


async def test_small_worker_output_is_retained_verbatim(tmp_path):
    """No behaviour change for ordinary runs: nothing added, nothing marked."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "FAKE_CLAUDE_MODE": "success",
    }
    run = await run_worker(_invocation(tmp_path, env))
    assert run.stdout_truncated is False
    assert run.stderr_truncated is False
    assert run.stdout_for_parsing == run.stdout
    assert run.stdout_total_bytes == len(run.stdout.encode("utf-8"))
    assert json.loads(run.stdout)["type"] == "result"


# ===========================================================================
# P1-9 — prohibited operations are invariants, not configuration
# ===========================================================================


def test_core_git_denials_are_non_configurable(dispatcher_config, envelope, git_repo, tmp_path):
    """An operator who empties ``disallowed_tools`` still gets the core set."""
    dispatcher_config.claude.disallowed_tools = []
    argv = build_argv(
        build_worker_invocation(
            envelope,
            dispatcher_config,
            model="sonnet",
            session_id=str(uuid.uuid4()),
            prompt="p",
            cwd=git_repo,
            base_env={"PATH": "/usr/bin", "HOME": str(tmp_path)},
        )
    )
    denied = _flag_values(argv, "--disallowedTools")
    for pattern in ALWAYS_DISALLOWED_TOOLS:
        assert pattern in denied, pattern
    for pattern in CORE_DENIED_GIT_OPERATIONS:
        assert pattern in denied, pattern
    assert "Bash(git push:*)" in denied
    assert "Bash(git merge:*)" in denied
    assert "Bash(git commit:*)" in denied
    assert "Bash(git rebase:*)" in denied
    assert "Bash(git reset:*)" in denied
    assert "Bash(git clean:*)" in denied
    assert "Bash(git worktree:*)" in denied


def test_operator_deny_rules_are_additive(dispatcher_config, envelope, git_repo, tmp_path):
    dispatcher_config.claude.disallowed_tools = ["Bash(rm:*)"]
    argv = build_argv(
        build_worker_invocation(
            envelope,
            dispatcher_config,
            model="sonnet",
            session_id=str(uuid.uuid4()),
            prompt="p",
            cwd=git_repo,
            base_env={"PATH": "/usr/bin", "HOME": str(tmp_path)},
        )
    )
    denied = _flag_values(argv, "--disallowedTools")
    assert "Bash(rm:*)" in denied
    for pattern in ALWAYS_DISALLOWED_TOOLS:
        assert pattern in denied


def test_fable_argv_also_carries_the_core_denials(dispatcher_config, envelope, git_repo, tmp_path):
    dispatcher_config.claude.disallowed_tools = []
    argv = build_argv(
        build_fable_invocation(
            envelope,
            dispatcher_config,
            session_id=str(uuid.uuid4()),
            prompt="review",
            cwd=git_repo,
            base_env={"PATH": "/usr/bin", "HOME": str(tmp_path)},
        )
    )
    denied = _flag_values(argv, "--disallowedTools")
    for pattern in ALWAYS_DISALLOWED_TOOLS:
        assert pattern in denied


def test_build_argv_refuses_an_invocation_missing_a_core_denial(tmp_path):
    """Last line of defence: a hand-built invocation cannot skip the core set."""
    spec = WorkerInvocation(
        binary=str(FAKE_CLAUDE),
        model="sonnet",
        session_id=str(uuid.uuid4()),
        cwd=tmp_path,
        prompt="p",
        timeout_seconds=60,
        role="implementer",
        disallowed_tools=["Bash(rm:*)"],
    )
    with pytest.raises(InternalDispatcherError) as exc:
        build_argv(spec)
    assert "disallow" in str(exc.value).lower() or "deny" in str(exc.value).lower()


@pytest.mark.parametrize("field", ["allow_push", "allow_merge", "allow_commit", "allow_subagents"])
def test_task_constraints_refuse_to_enable_prohibited_operations(field):
    with pytest.raises(Exception) as exc:
        ConstraintsSpec(**{field: True})
    assert field in str(exc.value)


@pytest.mark.parametrize("field", ["allow_push", "allow_merge", "allow_commit", "allow_subagents"])
def test_task_request_refuses_constraints_that_enable_prohibited_operations(
    valid_request_dict, field
):
    payload = dict(valid_request_dict)
    payload["constraints"] = {field: True}
    with pytest.raises(Exception):
        TaskRequest.model_validate(payload)


@pytest.mark.parametrize("field", ["allow_push", "allow_merge", "allow_commit", "allow_subagents"])
def test_security_config_refuses_to_enable_prohibited_operations(tmp_path, field):
    with pytest.raises(ConfigurationError):
        load_config_from_mapping(
            {
                "dispatcher": {"state_dir": str(tmp_path / "state")},
                "models": {"sonnet": "sonnet", "opus": "opus", "fable": "fable"},
                "routing": {"default_model": "sonnet"},
                "security": {
                    "max_dispatch_depth": 1,
                    "allowed_repository_roots": [str(tmp_path)],
                    field: True,
                },
            },
            project_root=PROJECT_ROOT,
        )


def test_allow_network_remains_a_real_policy_flag(tmp_path):
    """Honesty: ``allow_network`` is POLICY, not a prohibited operation.

    It genuinely changes the instructions given to the worker, so it stays a
    settable flag rather than becoming an always-false stub.
    """
    config = load_config_from_mapping(
        {
            "dispatcher": {"state_dir": str(tmp_path / "state")},
            "models": {"sonnet": "sonnet", "opus": "opus", "fable": "fable"},
            "routing": {"default_model": "sonnet"},
            "security": {
                "max_dispatch_depth": 1,
                "allowed_repository_roots": [str(tmp_path)],
                "allow_network": True,
            },
        },
        project_root=PROJECT_ROOT,
    )
    assert config.security.allow_network is True
    assert ConstraintsSpec(allow_network=True).allow_network is True
