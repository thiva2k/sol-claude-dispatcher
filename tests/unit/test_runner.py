"""Runner tests (brief §11, §20, §22, §31, §32).

Every process in this file is ``tests/fake_bin/claude``. Nothing here may spawn
the real Claude CLI — that is the §32 rule and the reason the fake exists.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from sol_claude_dispatcher.config import load_config_from_mapping
from sol_claude_dispatcher.errors import (
    ClaudeBinaryNotFound,
    ConfigurationError,
    InternalDispatcherError,
    RecursionDetected,
)
from sol_claude_dispatcher.models import TaskEnvelope, TaskRequest
from sol_claude_dispatcher.runner import (
    ALWAYS_DISALLOWED_TOOLS,
    CLI_CAPABILITIES,
    FORBIDDEN_FLAGS,
    STDERR_TAIL_CHARS,
    WorkerInvocation,
    WorkerRun,
    build_argv,
    build_fable_invocation,
    build_worker_invocation,
    cli_failure,
    run_worker,
    schema_for_claude_cli,
)
from sol_claude_dispatcher.security import assert_no_recursion

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAKE_CLAUDE = PROJECT_ROOT / "tests" / "fake_bin" / "claude"
BASE_COMMIT = "a" * 40


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dispatcher_config(tmp_path: Path):
    """Config whose Claude binary is the fake, resolved against the real repo
    so the shipped policy files and schemas are used verbatim."""
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
    """Base environment handed to the fake. Deliberately carries a secret so
    tests can prove ``worker_environment`` strips it (§22 layer 7)."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "LANG": "C.UTF-8",
        "FAKE_CLAUDE_MODE": "success",
        "FAKE_CLAUDE_LOG": str(tmp_path / "fake-claude.log"),
        "GITHUB_TOKEN": "ghp_supersecret",
        "AWS_SECRET_ACCESS_KEY": "nope",
        "SOL_DISPATCHER_CONFIG": "/etc/dispatcher.toml",
    }


def read_fake_log(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


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


# ---------------------------------------------------------------------------
# argv construction — worker
# ---------------------------------------------------------------------------


def test_worker_argv_shape(dispatcher_config, envelope, fake_env, git_repo):
    spec = build_worker_invocation(
        envelope,
        dispatcher_config,
        model="sonnet",
        session_id="11111111-1111-4111-8111-111111111111",
        prompt="Implement the objective.",
        cwd=git_repo,
        base_env=fake_env,
    )
    argv = build_argv(spec)

    assert argv[0] == str(FAKE_CLAUDE)
    assert argv[1] == "-p"
    assert flag_value(argv, "--model") == "sonnet"
    assert flag_value(argv, "--output-format") == "json"
    assert flag_value(argv, "--permission-mode") == "auto"
    # Gate 4.5 §2: no inherited customization surface. See tests/unit/test_safe_mode.py.
    assert "--safe-mode" in argv
    assert "--bare" not in argv
    assert "--strict-mcp-config" in argv
    assert flag_value(argv, "--mcp-config").endswith("config/empty-mcp.json")
    assert flag_value(argv, "--session-id") == "11111111-1111-4111-8111-111111111111"
    assert flag_value(argv, "--worktree") == envelope.worktree_name
    assert argv[-1] == "Implement the objective."
    # The prompt is the ONLY positional.
    assert argv.count("Implement the objective.") == 1


def test_worker_argv_strips_mcp_and_subagents(dispatcher_config, envelope, git_repo, fake_env):
    argv = build_argv(
        build_worker_invocation(
            envelope,
            dispatcher_config,
            model="sonnet",
            session_id=str(uuid.uuid4()),
            prompt="p",
            cwd=git_repo,
            base_env=fake_env,
        )
    )
    disallowed = flag_values(argv, "--disallowedTools")
    for pattern in ALWAYS_DISALLOWED_TOOLS:
        assert pattern in disallowed
    assert "mcp__*" in disallowed
    assert "Bash(claude:*)" in disallowed
    assert "Bash(codex:*)" in disallowed
    # Gate 4.5 deny-set holes P1/P2, closed in the core (non-configurable) set.
    assert "Bash(git bisect:*)" in disallowed
    assert "Bash(gh:*)" in disallowed
    # Granted tools never include a subagent spawner (§22 layer 2).
    granted = flag_values(argv, "--tools")
    assert "Agent" not in granted and "Task" not in granted
    assert "Read" in granted and "Write" in granted


def test_worker_argv_json_schema_is_minified_inline(dispatcher_config, envelope, git_repo, fake_env):
    argv = build_argv(
        build_worker_invocation(
            envelope, dispatcher_config, model="sonnet",
            session_id=str(uuid.uuid4()), prompt="p", cwd=git_repo, base_env=fake_env,
        )
    )
    schema = flag_value(argv, "--json-schema")
    parsed = json.loads(schema)
    # Minified: identical to its own compact re-encoding, and strictly smaller
    # than the pretty-printed file on disk.
    assert schema == json.dumps(parsed, separators=(",", ":"))
    raw = (PROJECT_ROOT / "schemas" / "worker-result.schema.json").read_text()
    assert len(schema) < len(raw)
    assert parsed["properties"]["status"]  # it really is the worker schema


def test_worker_argv_policy_is_inline_text_not_a_path(dispatcher_config, envelope, git_repo, fake_env):
    argv = build_argv(
        build_worker_invocation(
            envelope, dispatcher_config, model="sonnet",
            session_id=str(uuid.uuid4()), prompt="p", cwd=git_repo, base_env=fake_env,
        )
    )
    policy = flag_value(argv, "--append-system-prompt")
    on_disk = (PROJECT_ROOT / "prompts" / "worker-policy.md").read_text()
    assert policy == on_disk
    assert not policy.endswith(".md")
    assert "--append-system-prompt-file" not in argv


def test_worker_argv_never_emits_max_turns(dispatcher_config, envelope, git_repo, fake_env):
    """§Wave-1 finding: Claude Code 2.1.234 has no --max-turns."""
    spec = build_worker_invocation(
        envelope, dispatcher_config, model="sonnet",
        session_id=str(uuid.uuid4()), prompt="p", cwd=git_repo, base_env=fake_env,
    )
    assert envelope.execution.max_turns == 40
    assert spec.max_turns == 40           # recorded policy...
    assert "--max-turns" not in build_argv(spec)   # ...but never emitted
    assert CLI_CAPABILITIES["max_turns"] is False


def test_max_turns_gate_can_be_flipped_without_touching_call_sites(
    dispatcher_config, envelope, git_repo, fake_env, monkeypatch
):
    monkeypatch.setitem(CLI_CAPABILITIES, "max_turns", True)
    argv = build_argv(
        build_worker_invocation(
            envelope, dispatcher_config, model="sonnet",
            session_id=str(uuid.uuid4()), prompt="p", cwd=git_repo, base_env=fake_env,
        )
    )
    assert flag_value(argv, "--max-turns") == "40"


def test_worker_argv_never_contains_a_forbidden_flag(dispatcher_config, envelope, git_repo, fake_env):
    argv = build_argv(
        build_worker_invocation(
            envelope, dispatcher_config, model="sonnet",
            session_id=str(uuid.uuid4()), prompt="p", cwd=git_repo, base_env=fake_env,
        )
    )
    assert FORBIDDEN_FLAGS.isdisjoint(argv)


def test_worker_env_carries_markers_and_drops_secrets(
    dispatcher_config, envelope, git_repo, fake_env
):
    spec = build_worker_invocation(
        envelope, dispatcher_config, model="sonnet",
        session_id=str(uuid.uuid4()), prompt="p", cwd=git_repo, base_env=fake_env,
    )
    assert spec.env["SOL_WORKER"] == "1"
    assert spec.env["SOL_DISPATCH_DEPTH"] == "1"
    assert spec.env["SOL_TASK_ID"] == envelope.task_id
    assert "GITHUB_TOKEN" not in spec.env
    assert "AWS_SECRET_ACCESS_KEY" not in spec.env
    assert "SOL_DISPATCHER_CONFIG" not in spec.env


# ---------------------------------------------------------------------------
# argv construction — resume
# ---------------------------------------------------------------------------


def test_resume_argv_uses_resume_and_no_new_worktree(dispatcher_config, envelope, git_repo, fake_env):
    argv = build_argv(
        build_worker_invocation(
            envelope, dispatcher_config, model="sonnet",
            session_id="ignored-on-resume", prompt="Fix R1 only.",
            cwd=git_repo, base_env=fake_env,
            resume_session_id="22222222-2222-4222-8222-222222222222",
        )
    )
    assert flag_value(argv, "--resume") == "22222222-2222-4222-8222-222222222222"
    assert "--session-id" not in argv
    assert "--worktree" not in argv
    assert argv[-1] == "Fix R1 only."


def test_resume_with_worktree_is_refused():
    spec = WorkerInvocation(
        binary="claude", model="sonnet", session_id="s", cwd=Path("/tmp"),
        prompt="p", timeout_seconds=10, role="implementer",
        worktree_name="sol-abcd1234", resume_session_id="sess",
    )
    with pytest.raises(InternalDispatcherError):
        build_argv(spec)


# ---------------------------------------------------------------------------
# argv construction — Fable
# ---------------------------------------------------------------------------


def test_fable_argv_is_read_only_and_fresh(dispatcher_config, envelope, git_repo, fake_env):
    spec = build_fable_invocation(
        envelope, dispatcher_config,
        session_id="33333333-3333-4333-8333-333333333333",
        prompt="Review the diff.", cwd=git_repo, base_env=fake_env,
    )
    argv = build_argv(spec)

    assert spec.role == "reviewer"
    assert flag_value(argv, "--model") == "fable"
    tools = flag_values(argv, "--tools")
    assert tools == ["Read", "Glob", "Grep"]
    for banned in ("Edit", "Write", "Bash", "NotebookEdit", "Agent", "Task"):
        assert banned not in tools
    disallowed = flag_values(argv, "--disallowedTools")
    assert "Edit" in disallowed and "Write" in disallowed and "Bash" in disallowed
    assert "mcp__*" in disallowed
    assert "--worktree" not in argv
    assert "--resume" not in argv
    assert flag_value(argv, "--session-id") == "33333333-3333-4333-8333-333333333333"
    # Gate 4.5 §2: the reviewer is isolated on exactly the same terms as the
    # worker — Fable reads the tree, so an inherited hook or Skill would be
    # shaping the review the dispatcher records as evidence.
    assert "--safe-mode" in argv
    assert "--bare" not in argv
    assert "--strict-mcp-config" in argv
    assert flag_value(argv, "--mcp-config").endswith("config/empty-mcp.json")
    # Reviewer policy, inline, verbatim.
    assert flag_value(argv, "--append-system-prompt") == (
        PROJECT_ROOT / "prompts" / "fable-reviewer-policy.md"
    ).read_text()


def test_fable_config_with_write_tools_is_refused(dispatcher_config, envelope, git_repo, fake_env):
    dispatcher_config.claude.reviewer_tools = ["Read", "Edit"]
    with pytest.raises(ConfigurationError):
        build_fable_invocation(
            envelope, dispatcher_config, session_id="s", prompt="p",
            cwd=git_repo, base_env=fake_env,
        )


# ---------------------------------------------------------------------------
# --json-schema compatibility projection (Gate 4 live defect, CLI 2.1.237)
#
# Claude Code 2.1.237 rejects the draft 2020-12 dialect declaration on
# ``--json-schema`` ("no schema with key or ref
# https://json-schema.org/draft/2020-12/schema"). The canonical schema files
# stay 2020-12; only the argv value drops the top-level declaration. These tests
# pin BOTH halves of that: the files must not drift, and the projection must not
# grow into a general-purpose stripper.
# ---------------------------------------------------------------------------

CANONICAL_DIALECT = "https://json-schema.org/draft/2020-12/schema"
WORKER_SCHEMA_FILE = PROJECT_ROOT / "schemas" / "worker-result.schema.json"
FABLE_SCHEMA_FILE = PROJECT_ROOT / "schemas" / "fable-review.schema.json"


def worker_cli_schema(config, envelope, cwd, env) -> dict:
    argv = build_argv(
        build_worker_invocation(
            envelope, config, model="sonnet", session_id=str(uuid.uuid4()),
            prompt="p", cwd=cwd, base_env=env,
        )
    )
    return json.loads(flag_value(argv, "--json-schema"))


def fable_cli_schema(config, envelope, cwd, env) -> dict:
    argv = build_argv(
        build_fable_invocation(
            envelope, config, session_id=str(uuid.uuid4()),
            prompt="p", cwd=cwd, base_env=env,
        )
    )
    return json.loads(flag_value(argv, "--json-schema"))


def test_canonical_worker_schema_stays_draft_2020_12_on_disk(
    dispatcher_config, envelope, git_repo, fake_env
):
    """(1) The projection is a consumer workaround, not a schema downgrade."""
    before = WORKER_SCHEMA_FILE.read_bytes()
    assert json.loads(before)["$schema"] == CANONICAL_DIALECT
    worker_cli_schema(dispatcher_config, envelope, git_repo, fake_env)
    # Building the invocation must not rewrite the source file.
    assert WORKER_SCHEMA_FILE.read_bytes() == before


def test_canonical_fable_schema_stays_draft_2020_12_on_disk(
    dispatcher_config, envelope, git_repo, fake_env
):
    """(2) Same for the reviewer schema."""
    before = FABLE_SCHEMA_FILE.read_bytes()
    assert json.loads(before)["$schema"] == CANONICAL_DIALECT
    fable_cli_schema(dispatcher_config, envelope, git_repo, fake_env)
    assert FABLE_SCHEMA_FILE.read_bytes() == before


def test_worker_argv_schema_has_no_top_level_dialect(
    dispatcher_config, envelope, git_repo, fake_env
):
    """(3) The exact thing the live CLI rejected must not reach argv."""
    projected = worker_cli_schema(dispatcher_config, envelope, git_repo, fake_env)
    assert "$schema" not in projected
    assert CANONICAL_DIALECT not in json.dumps(projected)


def test_fable_argv_schema_has_no_top_level_dialect(
    dispatcher_config, envelope, git_repo, fake_env
):
    """(4) The reviewer invocation failed live too; it is projected as well."""
    projected = fable_cli_schema(dispatcher_config, envelope, git_repo, fake_env)
    assert "$schema" not in projected
    assert CANONICAL_DIALECT not in json.dumps(projected)


@pytest.mark.parametrize(
    "which, schema_file",
    [("worker", WORKER_SCHEMA_FILE), ("fable", FABLE_SCHEMA_FILE)],
)
def test_projection_removes_only_the_dialect_declaration(
    which, schema_file, dispatcher_config, envelope, git_repo, fake_env
):
    """(5) Every other top-level field survives, byte-for-value."""
    canonical = json.loads(schema_file.read_text())
    projected = (
        worker_cli_schema(dispatcher_config, envelope, git_repo, fake_env)
        if which == "worker"
        else fable_cli_schema(dispatcher_config, envelope, git_repo, fake_env)
    )
    for key in ("$id", "title", "type", "properties", "required", "additionalProperties"):
        assert key in projected, key
        assert projected[key] == canonical[key], key
    # Nothing added, nothing else removed.
    assert set(projected) == set(canonical) - {"$schema"}


def test_projection_preserves_nested_schema_structures(
    dispatcher_config, envelope, git_repo, fake_env
):
    """(6) Constraints are semantics, not metadata — none of them are touched."""
    canonical = json.loads(WORKER_SCHEMA_FILE.read_text())
    projected = worker_cli_schema(dispatcher_config, envelope, git_repo, fake_env)
    assert projected["properties"] == canonical["properties"]
    assert projected["required"] == canonical["required"]
    status = projected["properties"]["status"]
    assert status["enum"] == canonical["properties"]["status"]["enum"]
    changes = projected["properties"]["changes"]
    assert changes["items"] == canonical["properties"]["changes"]["items"]


def test_projected_schema_is_valid_minified_json(
    dispatcher_config, envelope, git_repo, fake_env
):
    """(7) Still a single valid JSON document, still minified."""
    for builder in (worker_cli_schema, fable_cli_schema):
        projected = builder(dispatcher_config, envelope, git_repo, fake_env)
        assert isinstance(projected, dict)
    for schema_file, what in (
        (WORKER_SCHEMA_FILE, "Worker result schema"),
        (FABLE_SCHEMA_FILE, "Fable review schema"),
    ):
        text = schema_for_claude_cli(schema_file, what=what)
        assert text == json.dumps(json.loads(text), separators=(",", ":"))
        assert len(text) < len(schema_file.read_text())


async def test_fake_worker_lifecycle_still_green_with_projected_schema(
    dispatcher_config, envelope, git_repo, fake_env, tmp_path
):
    """(8) End-to-end through the fake: the projected schema is what is passed,
    and the run still completes and parses."""
    run = await run_worker(invocation(dispatcher_config, envelope, git_repo, fake_env))
    assert run.exit_code == 0
    assert json.loads(run.stdout)["structured_output"]["status"] == "completed"

    log = read_fake_log(tmp_path / "fake-claude.log")
    seen = json.loads(log[0]["json_schema"])
    assert "$schema" not in seen
    assert seen["properties"]["status"]["enum"]


def test_projection_keeps_a_nested_property_named_schema(tmp_path: Path):
    """A property literally named ``$schema`` is part of the contract we ask the
    model to satisfy, not dialect metadata. Only the TOP-LEVEL key is removed —
    a recursive strip would silently change what the worker must return."""
    fixture = tmp_path / "nested-dollar-schema.schema.json"
    fixture.write_text(
        json.dumps(
            {
                "$schema": CANONICAL_DIALECT,
                "$id": "https://example.invalid/nested.schema.json",
                "title": "NestedDollarSchema",
                "type": "object",
                "additionalProperties": False,
                "required": ["$schema"],
                "properties": {
                    "$schema": {"type": "string", "description": "a real field"},
                    "nested": {
                        "type": "object",
                        "properties": {"$schema": {"type": "string"}},
                    },
                },
                "$defs": {"inner": {"$schema": CANONICAL_DIALECT, "type": "string"}},
            }
        ),
        encoding="utf-8",
    )

    projected = json.loads(schema_for_claude_cli(fixture, what="Fixture schema"))

    assert "$schema" not in projected                      # top level: gone
    assert projected["properties"]["$schema"] == {          # nested: intact
        "type": "string",
        "description": "a real field",
    }
    assert projected["properties"]["nested"]["properties"]["$schema"] == {"type": "string"}
    assert projected["$defs"]["inner"]["$schema"] == CANONICAL_DIALECT
    assert projected["required"] == ["$schema"]
    # And the fixture on disk is untouched.
    assert json.loads(fixture.read_text())["$schema"] == CANONICAL_DIALECT


# ---------------------------------------------------------------------------
# argv construction — fail-closed guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"permission_mode": "bypassPermissions"},
        {"tools": ["Read", "Agent"]},
        {"prompt": "   "},
    ],
)
def test_build_argv_fails_closed(kwargs):
    base = dict(
        binary="claude", model="sonnet", session_id="s", cwd=Path("/tmp"),
        prompt="p", timeout_seconds=10, role="implementer",
    )
    base.update(kwargs)
    with pytest.raises(InternalDispatcherError):
        build_argv(WorkerInvocation(**base))  # type: ignore[arg-type]


def test_reviewer_may_not_receive_a_worktree():
    spec = WorkerInvocation(
        binary="claude", model="fable", session_id="s", cwd=Path("/tmp"),
        prompt="p", timeout_seconds=10, role="reviewer", worktree_name="sol-abcd1234",
    )
    with pytest.raises(InternalDispatcherError):
        build_argv(spec)


# ---------------------------------------------------------------------------
# run_worker — the fake binary, §32
# ---------------------------------------------------------------------------


def invocation(config, envelope, cwd, env, **overrides) -> WorkerInvocation:
    kwargs = dict(
        model="sonnet",
        session_id=str(uuid.uuid4()),
        prompt="Implement the objective.",
        cwd=cwd,
        base_env=env,
        timeout_seconds=30,
        grace_seconds=0.5,
    )
    kwargs.update(overrides)
    return build_worker_invocation(envelope, config, **kwargs)  # type: ignore[arg-type]


async def test_run_worker_success(dispatcher_config, envelope, git_repo, fake_env, tmp_path):
    run = await run_worker(invocation(dispatcher_config, envelope, git_repo, fake_env))

    assert run.exit_code == 0
    assert run.timed_out is False
    assert run.killed_with_sigkill is False
    assert run.start_failed is False
    payload = json.loads(run.stdout)
    assert payload["structured_output"]["status"] == "completed"
    assert run.duration_ms >= 0

    log = read_fake_log(tmp_path / "fake-claude.log")
    assert len(log) == 1
    assert log[0]["cwd"] == str(git_repo)
    assert log[0]["has_worktree"] is True
    assert log[0]["has_resume"] is False


async def test_run_worker_records_env_markers_and_no_secrets(
    dispatcher_config, envelope, git_repo, fake_env, tmp_path
):
    await run_worker(invocation(dispatcher_config, envelope, git_repo, fake_env))
    record = read_fake_log(tmp_path / "fake-claude.log")[0]

    assert record["env_markers"]["SOL_WORKER"] == "1"
    assert record["env_markers"]["SOL_DISPATCH_DEPTH"] == "1"
    assert record["env_markers"]["SOL_TASK_ID"] == envelope.task_id
    assert "GITHUB_TOKEN" not in record["env_keys"]
    assert "AWS_SECRET_ACCESS_KEY" not in record["env_keys"]
    assert "SOL_DISPATCHER_CONFIG" not in record["env_keys"]


async def test_worker_environment_would_refuse_a_nested_dispatcher(
    dispatcher_config, envelope, git_repo, fake_env
):
    """§22 layer 4: the env we hand the worker is exactly the env that makes a
    dispatcher refuse to initialise."""
    spec = invocation(dispatcher_config, envelope, git_repo, fake_env)
    with pytest.raises(RecursionDetected):
        assert_no_recursion(dispatcher_config, env=spec.env)
    # ...and the override escape hatch is test-only, never in the worker env.
    assert "SOL_DISPATCHER_TEST_OVERRIDE" not in spec.env


async def test_run_worker_nonzero_exit_is_reported_not_raised(
    dispatcher_config, envelope, git_repo, fake_env
):
    fake_env["FAKE_CLAUDE_MODE"] = "failure"
    run = await run_worker(invocation(dispatcher_config, envelope, git_repo, fake_env))

    assert run.exit_code == 2
    assert run.timed_out is False
    assert "simulated worker failure" in run.stderr


async def test_run_worker_timeout_terminates_and_preserves_evidence(
    dispatcher_config, envelope, git_repo, fake_env, tmp_path
):
    """§20/§31: TERM → status=timeout → partial output and task state survive."""
    fake_env["FAKE_CLAUDE_MODE"] = "timeout"
    fake_env["FAKE_CLAUDE_SLEEP"] = "60"
    spec = invocation(
        dispatcher_config, envelope, git_repo, fake_env,
        timeout_seconds=1, grace_seconds=0.5,
    )
    run = await run_worker(spec)

    assert run.timed_out is True
    assert run.killed_with_sigkill is False          # SIGTERM was enough
    assert run.exit_code == -15                      # died on SIGTERM
    assert "partial stdout before timeout" in run.stdout
    assert "still working" in run.stderr
    assert run.duration_ms < 30_000

    # State that must never be lost on a timeout (§20).
    assert spec.session_id
    assert spec.worktree_name == envelope.worktree_name
    assert flag_value(run.argv, "--session-id") == spec.session_id
    assert flag_value(run.argv, "--worktree") == envelope.worktree_name
    record = read_fake_log(tmp_path / "fake-claude.log")[0]
    assert record["session_id"] == spec.session_id


async def test_run_worker_escalates_to_sigkill_when_sigterm_ignored(
    dispatcher_config, envelope, git_repo, fake_env
):
    fake_env["FAKE_CLAUDE_MODE"] = "hang"
    fake_env["FAKE_CLAUDE_SLEEP"] = "60"
    run = await run_worker(
        invocation(
            dispatcher_config, envelope, git_repo, fake_env,
            timeout_seconds=1, grace_seconds=0.5,
        )
    )

    assert run.timed_out is True
    assert run.killed_with_sigkill is True
    assert run.exit_code == -9
    assert "partial stdout before timeout" in run.stdout


async def test_run_worker_missing_binary(dispatcher_config, envelope, git_repo, fake_env, tmp_path):
    dispatcher_config.claude.binary = str(tmp_path / "no-such-claude")
    with pytest.raises(ClaudeBinaryNotFound):
        await run_worker(invocation(dispatcher_config, envelope, git_repo, fake_env))


async def test_run_worker_non_executable_binary(
    dispatcher_config, envelope, git_repo, fake_env, tmp_path
):
    dud = tmp_path / "claude-not-executable"
    dud.write_text("#!/bin/sh\n")
    dud.chmod(0o644)
    dispatcher_config.claude.binary = str(dud)
    with pytest.raises(ClaudeBinaryNotFound):
        await run_worker(invocation(dispatcher_config, envelope, git_repo, fake_env))


async def test_run_worker_malformed_json_is_not_the_runners_problem(
    dispatcher_config, envelope, git_repo, fake_env
):
    fake_env["FAKE_CLAUDE_MODE"] = "malformed-json"
    run = await run_worker(invocation(dispatcher_config, envelope, git_repo, fake_env))

    assert run.exit_code == 0
    assert run.timed_out is False
    with pytest.raises(json.JSONDecodeError):
        json.loads(run.stdout)


async def test_run_worker_blocked_mode(dispatcher_config, envelope, git_repo, fake_env):
    fake_env["FAKE_CLAUDE_MODE"] = "blocked"
    run = await run_worker(invocation(dispatcher_config, envelope, git_repo, fake_env))

    payload = json.loads(run.stdout)["structured_output"]
    assert payload["status"] == "blocked"
    assert payload["blockers"]


async def test_run_worker_scope_violation_mode_writes_outside_allowed_paths(
    dispatcher_config, envelope, git_repo, fake_env
):
    fake_env["FAKE_CLAUDE_MODE"] = "scope-violation"
    run = await run_worker(invocation(dispatcher_config, envelope, git_repo, fake_env))

    assert run.exit_code == 0
    # The worker CLAIMS success while having touched a forbidden path — the
    # exact divergence dispatcher observations exist to catch (§16).
    assert json.loads(run.stdout)["structured_output"]["status"] == "completed"
    assert (git_repo / ".github" / "workflows" / "pwn.yml").exists()
    assert (git_repo / "src" / "unrelated" / "leak.py").exists()


async def test_fake_resume_mode_distinguishes_resume_from_fresh(
    dispatcher_config, envelope, git_repo, fake_env, tmp_path
):
    fake_env["FAKE_CLAUDE_MODE"] = "resume"

    fresh = await run_worker(invocation(dispatcher_config, envelope, git_repo, fake_env))
    assert fresh.exit_code == 3          # no --resume: the fake refuses

    resumed = await run_worker(
        invocation(
            dispatcher_config, envelope, git_repo, fake_env,
            resume_session_id="44444444-4444-4444-8444-444444444444",
        )
    )
    assert resumed.exit_code == 0
    payload = json.loads(resumed.stdout)
    assert payload["resumed_session_id"] == "44444444-4444-4444-8444-444444444444"
    assert "Resumed session" in payload["structured_output"]["summary"]

    records = read_fake_log(tmp_path / "fake-claude.log")
    assert [r["has_resume"] for r in records] == [False, True]
    assert records[1]["has_worktree"] is False


async def test_fable_review_mode_returns_review_shaped_json(
    dispatcher_config, envelope, git_repo, fake_env, tmp_path
):
    fake_env["FAKE_CLAUDE_MODE"] = "fable-review"
    spec = build_fable_invocation(
        envelope, dispatcher_config, session_id=str(uuid.uuid4()),
        prompt="Review the diff.", cwd=git_repo, base_env=fake_env,
        timeout_seconds=30, grace_seconds=0.5,
    )
    run = await run_worker(spec)

    payload = json.loads(run.stdout)["structured_output"]
    assert payload["verdict"] == "changes_required"
    assert payload["recommended_next_action"] == "resume_worker"
    assert payload["findings"][0]["severity"] == "high"

    record = read_fake_log(tmp_path / "fake-claude.log")[0]
    assert record["tools"] == ["Read", "Glob", "Grep"]
    assert record["has_worktree"] is False
    assert record["model"] == "fable"


# ---------------------------------------------------------------------------
# DEFECT-L2-02: a present-but-broken CLI must not be misreported as bad model
# output. ``ClaudeBinaryNotFound`` only covers absent/non-executable binaries;
# a partially installed CLI starts fine, exits non-zero, and writes nothing.
# ---------------------------------------------------------------------------


def _run(**overrides) -> WorkerRun:
    fields = {
        "argv": ["claude", "-p"],
        "exit_code": 1,
        "stdout": "",
        "stderr": "",
        "duration_ms": 12,
    }
    fields.update(overrides)
    return WorkerRun(**fields)  # type: ignore[arg-type]


def test_cli_failure_names_the_environment_fault_with_the_stderr_tail():
    run = _run(
        exit_code=1,
        stdout="",
        stderr=(
            "Error: claude native binary not installed.\n"
            "Run the postinstall manually.\n"
        ),
    )

    error = cli_failure(run, binary="/usr/bin/claude", role="implementer")

    assert error is not None
    assert error.code == "ClaudeExecutionFailed"
    assert "claude native binary not installed" in error.details["stderr_tail"]
    assert error.details["exit_code"] == 1
    assert error.details["binary"] == "/usr/bin/claude"
    assert error.details["role"] == "implementer"
    # The operator must not be told the model produced bad JSON.
    assert "JSON" not in error.message


def test_cli_failure_redacts_secret_shaped_stderr():
    """§28: stderr is diagnostics and may quote a secret-shaped value."""
    run = _run(stderr='ANTHROPIC_API_KEY=sk-live-abcdef\nfatal: cannot start\n')

    error = cli_failure(run, binary="claude", role="implementer")

    assert error is not None
    assert "sk-live-abcdef" not in error.details["stderr_tail"]
    assert "REDACTED" in error.details["stderr_tail"]


def test_cli_failure_tail_is_bounded():
    run = _run(stderr="x" * 50_000)

    error = cli_failure(run, binary="claude", role="reviewer")

    assert error is not None
    assert len(error.details["stderr_tail"]) <= STDERR_TAIL_CHARS


def test_cli_failure_ignores_a_run_that_produced_output():
    """A non-zero exit that still emitted a result is a parsing question."""
    run = _run(exit_code=2, stdout='{"structured_output": {}}', stderr="noisy")

    assert cli_failure(run, binary="claude", role="implementer") is None


def test_cli_failure_ignores_success_timeout_and_start_failure():
    assert cli_failure(_run(exit_code=0), binary="claude", role="implementer") is None
    assert (
        cli_failure(
            _run(exit_code=None, timed_out=True), binary="claude", role="implementer"
        )
        is None
    )
    assert (
        cli_failure(
            _run(exit_code=None, start_failed=True), binary="claude", role="implementer"
        )
        is None
    )


async def test_cli_failure_diagnoses_a_real_broken_binary_stub(
    dispatcher_config, envelope, git_repo, fake_env, tmp_path
):
    """End to end through ``run_worker``, against a stub shaped like the real
    breakage: present, executable, exits non-zero, empty stdout."""
    stub = tmp_path / "broken-claude"
    stub.write_text(
        "#!/bin/sh\necho 'Error: claude native binary not installed.' >&2\nexit 1\n"
    )
    stub.chmod(0o755)
    dispatcher_config.claude.binary = str(stub)

    run = await run_worker(invocation(dispatcher_config, envelope, git_repo, fake_env))

    assert run.exit_code == 1
    assert run.stdout == ""
    error = cli_failure(run, binary=str(stub), role="implementer")
    assert error is not None
    assert "claude native binary not installed" in error.details["stderr_tail"]
