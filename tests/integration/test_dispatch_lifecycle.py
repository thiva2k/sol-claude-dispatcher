"""Full dispatch lifecycle against the fake worker (§31, §42 phase L).

Every test here drives ``Dispatcher`` end to end: real config, real ``TaskStore``
on disk, real git worktree, real subprocess — and a fake ``claude`` binary. No
test in this file (or any other) may spawn the real CLI.

The tool bodies are called directly rather than through a stdio client: the
lifecycle assertions are about state on disk and process behaviour, and an
in-process call keeps them deterministic. ``test_server_surface.py`` covers the
MCP surface itself, including a real stdio handshake.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sol_claude_dispatcher.models import TaskState


async def test_dispatch_success_records_evidence_and_awaits_sol_review(
    dispatcher, request_payload, fake_env, worker_invocations, monkeypatch
):
    """Happy path: worker edits in-scope files, dispatcher measures, Sol reviews."""
    # "scope-violation" is really "touch these paths, then report success"; the
    # paths decide whether it is a violation. Here they are all in scope.
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", "src/deploy/deploy.py,tests/test_deploy.py")
    request_payload["validation"] = {"commands": [{"argv": ["/bin/true"], "timeout_seconds": 30}]}

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert "error" not in result, result
    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert result["selected_model"] == "sonnet"
    assert result["scope"]["valid"] is True
    assert result["worktree"].endswith("sol-" + result["task_id"].replace("-", "")[:8])

    # §16: claims and observations are different objects with no shared fields.
    claims = result["worker_claims"]
    observations = result["dispatcher_observations"]
    assert claims["status"] == "completed"
    assert set(claims) & set(observations) == set()
    assert sorted(observations["changed_paths"]) == [
        "src/deploy/deploy.py",
        "tests/test_deploy.py",
    ]
    assert observations["worker_result_parsed"] is True
    assert observations["scope_valid"] is True
    assert observations["primary_worktree_clean"] is True
    assert observations["diff_bytes"] > 0

    # §17: the dispatcher re-ran the envelope's command itself.
    assert [v["argv"] for v in result["validation_results"]] == [["/bin/true"]]
    assert result["validation_results"][0]["passed"] is True
    assert result["validation_results"][0]["source"] == "dispatcher"

    # §27: state, envelope, run and evidence all landed on disk.
    task_dir = Path(dispatcher.store.task_dir(result["task_id"]))
    assert (task_dir / "envelope.json").exists()
    assert (task_dir / "state.json").exists()
    assert (task_dir / "runs" / "001" / "dispatcher-result.json").exists()
    assert (task_dir / "runs" / "001" / "worker-result.json").exists()
    assert (task_dir / "runs" / "001" / "stdout.json").exists()
    diff = (task_dir / "evidence" / "diff.patch").read_text()
    assert "deploy.py" in diff
    changed = json.loads((task_dir / "evidence" / "changed-paths.json").read_text())
    assert changed["base_commit"] == json.loads(
        (task_dir / "envelope.json").read_text()
    )["repository"]["base_commit"]

    # The worker got a fresh session, a worktree, and the recursion markers.
    log = worker_invocations()
    assert len(log) == 1
    invocation = log[0]
    assert invocation["has_session_id"] is True
    assert invocation["has_resume"] is False
    assert invocation["has_worktree"] is True
    assert invocation["env_markers"]["SOL_WORKER"] == "1"
    assert invocation["env_markers"]["SOL_DISPATCH_DEPTH"] == "1"
    assert invocation["env_markers"]["SOL_TASK_ID"] == result["task_id"]
    assert "--max-turns" not in invocation["argv"]
    assert "--dangerously-skip-permissions" not in invocation["argv"]
    assert "mcp__*" in invocation["disallowed_tools"]


async def test_worker_argv_carries_the_hard_enforcement_surface(
    dispatcher, request_payload, fake_env, worker_invocations
):
    """§11, §14, §22: the guarantees that are argv, not prose."""
    from sol_claude_dispatcher.runner import ALWAYS_DISALLOWED_TOOLS, FORBIDDEN_FLAGS

    await dispatcher.dispatch_claude_task(request_payload)
    call = worker_invocations()[0]
    argv = call["argv"]

    # Runner-enforced regardless of config: the config's disallowed list does
    # not mention Agent/Task, and they are denied anyway.
    assert "Agent" not in dispatcher.config.claude.disallowed_tools
    for pattern in ALWAYS_DISALLOWED_TOOLS:
        assert pattern in call["disallowed_tools"]
    for tool in ("Agent", "Task", "Subagent"):
        assert tool not in call["tools"]

    for flag in FORBIDDEN_FLAGS:
        assert flag not in argv
    assert "--strict-mcp-config" in argv
    assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--permission-mode") + 1] != "bypassPermissions"

    # Policy text and result schema are passed inline (DISCOVERY deltas 1/2).
    policy = Path(dispatcher.config.worker_policy_file).read_text()
    assert call["append_system_prompt"] == policy
    assert json.loads(call["json_schema"])["title"] or True

    # The envelope's objective reached the worker; internal ids never came
    # from the caller.
    assert request_payload["task"]["objective"] in call["prompt"]

    # §22 layer 7: no dispatcher secret is forwarded into the worker.
    assert not [k for k in call["env_keys"] if k.startswith("SOL_DISPATCHER_")]


async def test_secrets_never_reach_the_worker_or_the_run_record(
    dispatcher, request_payload, fake_env, worker_invocations, monkeypatch
):
    """§22 layer 7 and §28, proven end to end rather than unit-tested only."""
    monkeypatch.setenv("DEPLOY_API_KEY", "s3cr3t-value")
    monkeypatch.setenv("HARMLESS_SETTING", "keep-me")

    result = await dispatcher.dispatch_claude_task(request_payload)

    call = worker_invocations()[0]
    assert "DEPLOY_API_KEY" not in call["env_keys"]
    assert "HARMLESS_SETTING" in call["env_keys"]

    run = dispatcher.store.latest_run(result["task_id"])
    assert run is not None
    assert "s3cr3t-value" not in json.dumps(run.metadata.argv_redacted)
    # Bulky argv elements (policy text, JSON schema) are elided, not stored.
    assert all(len(element) < 700 for element in run.metadata.argv_redacted)


async def test_dispatch_state_history_walks_created_routed_running(
    dispatcher, request_payload, fake_env
):
    result = await dispatcher.dispatch_claude_task(request_payload)
    record = dispatcher.store.load(result["task_id"])
    assert [h["to"] for h in record.state_history] == [
        "routed",
        "running",
        "implemented",
        "awaiting_sol_review",
    ]
    assert record.state_history[0]["reason"].startswith("route:")


async def test_malformed_worker_json_fails_safely_with_evidence_kept(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """§15: unparseable output is a recorded fact, never prose-scraped."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "malformed-json")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.FAILED.value
    assert result["worker_claims"] is None
    assert "not_json" in result["worker_result_error"]
    assert result["dispatcher_observations"]["worker_result_parsed"] is False
    assert result["last_error"]["error"] == "ClaudeStructuredOutputInvalid"

    # Evidence survives the failure (§13, §20).
    run_dir = Path(dispatcher.store.run_dir(result["task_id"], 1))
    assert "prose was clearer" in (run_dir / "stdout.json").read_text()
    assert (Path(dispatcher.store.task_dir(result["task_id"])) / "evidence").is_dir()


async def test_scope_violation_becomes_policy_violation_with_paths_reported(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """§13: an unauthorised change is never silently accepted."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")
    # Default touch list: a forbidden path and an out-of-scope path.

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.POLICY_VIOLATION.value
    assert result["scope"]["valid"] is False
    assert result["scope"]["forbidden"] == [".github/workflows/pwn.yml"]
    assert result["scope"]["out_of_scope"] == ["src/unrelated/leak.py"]
    assert result["dispatcher_observations"]["scope_valid"] is False

    record = dispatcher.store.load(result["task_id"])
    assert record.state is TaskState.POLICY_VIOLATION
    assert sorted(record.policy_violations) == [
        "forbidden:.github/workflows/pwn.yml",
        "out_of_scope:src/unrelated/leak.py",
    ]
    # The worker claimed success; the dispatcher measured otherwise. Both kept.
    assert result["worker_claims"]["status"] == "completed"
    assert result["last_error"]["error"] == "PolicyViolation"

    # Evidence is preserved, not deleted (§13).
    changed = json.loads(
        (Path(dispatcher.store.task_dir(result["task_id"])) / "evidence" / "changed-paths.json").read_text()
    )
    assert ".github/workflows/pwn.yml" in changed["changed_paths"]


async def test_timeout_preserves_partial_output_session_and_worktree(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """§20: a timeout must not destroy evidence."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "timeout")
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "30")
    request_payload["execution"]["timeout_seconds"] = 1

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.TIMED_OUT.value
    assert result["dispatcher_observations"]["timed_out"] is True
    assert result["worker_claims"] is None
    assert "timed out" in result["worker_result_error"]
    assert result["last_error"]["error"] == "ClaudeTimedOut"

    record = dispatcher.store.load(result["task_id"])
    assert record.session_id  # session preserved for a later resume
    assert Path(record.worktree_path).is_dir()  # worktree preserved

    run_dir = Path(dispatcher.store.run_dir(result["task_id"], 1))
    assert "partial stdout before timeout" in (run_dir / "stdout.json").read_text()

    run = dispatcher.store.latest_run(result["task_id"])
    assert run is not None and run.metadata.timed_out is True


async def test_blocked_worker_lands_in_blocked_state(
    dispatcher, request_payload, fake_env, monkeypatch
):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "blocked")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.BLOCKED.value
    assert result["worker_claims"]["status"] == "blocked"
    assert result["worker_claims"]["blockers"]
    assert dispatcher.store.load(result["task_id"]).state is TaskState.BLOCKED


async def test_nonzero_exit_lands_in_failed(
    dispatcher, request_payload, fake_env, monkeypatch
):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "failure")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.FAILED.value
    assert result["last_error"]["error"] in {
        "ClaudeStructuredOutputInvalid",
        "ClaudeExecutionFailed",
    }


async def test_caller_supplied_identifiers_are_refused(
    dispatcher, request_payload, fake_env
):
    """§7.1: the caller may not supply internal identifiers. Not ignored — refused."""
    request_payload["task_id"] = "attacker-chosen"

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["error"] == "InvalidTaskEnvelope"
    assert any("task_id" in issue["location"] for issue in result["details"]["issues"])
    assert "traceback" not in json.dumps(result).lower()


async def test_repository_outside_allowlist_is_refused(
    dispatcher, request_payload, fake_env, tmp_path
):
    outside = tmp_path.parent / "not-allowed"
    outside.mkdir(exist_ok=True)
    request_payload["repository"]["root"] = str(outside)

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["error"] in {"RepositoryNotAllowed", "InvalidRepository"}
    assert result["retryable"] is False


async def test_dispatcher_validation_can_be_disabled(
    dispatcher, request_payload, fake_env
):
    """§17: validation commands come from config + envelope, never the worker."""
    dispatcher.config.validation.run_dispatcher_validation = False
    request_payload["validation"] = {"commands": [{"argv": ["/bin/false"]}]}

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["validation_results"] == []


async def test_worker_test_claim_is_marked_uncorroborated_without_validation(
    dispatcher, request_payload, fake_env
):
    """The worker claims ``pytest -q`` passed; nothing re-ran it. Say so."""
    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["claim_verification"] == [
        {
            "command": "pytest -q",
            "claimed_status": "passed",
            "validation_found": False,
            "validation_passed": None,
            "verdict": "uncorroborated",
        }
    ]


async def test_get_task_is_read_only_and_aggregates_everything(
    dispatcher, request_payload, fake_env
):
    dispatched = await dispatcher.dispatch_claude_task(request_payload)
    task_id = dispatched["task_id"]
    before = dispatcher.store.load(task_id)

    view = await dispatcher.get_task(task_id)

    after = dispatcher.store.load(task_id)
    assert after.state == before.state
    assert after.updated_at == before.updated_at  # no write of any kind

    assert view["task_id"] == task_id
    assert view["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert view["envelope"]["schema_version"] == "1.0"
    assert view["model"] == "sonnet"
    assert view["worktree"] == dispatched["worktree"]
    assert view["session_id"] == dispatched["session_id"]
    assert view["resume_count"] == 0
    assert len(view["runs"]) == 1
    assert view["latest_worker_result"]["status"] == "completed"
    assert view["latest_fable_review"] is None
    assert view["policy_violations"] == []
    assert view["timeout"]["timeout_seconds"] == 60
    assert view["timeout"]["timed_out"] is False
    assert view["validation_history"][0]["run_index"] == 1


async def test_get_task_unknown_id_is_a_concise_error(dispatcher):
    result = await dispatcher.get_task("11111111-2222-4333-8444-555555555555")
    assert result["error"] == "TaskNotFound"
    assert len(result["message"]) < 200


@pytest.mark.parametrize("mode", ["success", "blocked"])
async def test_worktree_is_never_merged_into_the_primary_tree(
    dispatcher, request_payload, fake_env, monkeypatch, git_repo, mode
):
    """§12: the dispatcher never applies worktree changes to the primary tree."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    head_before = (git_repo / ".git" / "HEAD").read_text()

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert (git_repo / ".git" / "HEAD").read_text() == head_before
    assert result["dispatcher_observations"]["primary_worktree_clean"] is True
