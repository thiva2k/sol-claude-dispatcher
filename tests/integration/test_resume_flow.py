"""Resume lifecycle against the fake worker (§7.2, §18, §22 layer 6).

The fake binary's ``resume`` mode is adversarial on purpose: it exits 3 when
``--resume`` is missing and 4 when ``--session-id`` is passed alongside it, so a
dispatcher that quietly starts a fresh conversation fails loudly here instead of
passing silently.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from sol_claude_dispatcher.models import TaskState, is_transition_allowed
from sol_claude_dispatcher.server import Dispatcher


async def _dispatch_then(dispatcher, payload, monkeypatch):
    result = await dispatcher.dispatch_claude_task(payload)
    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value, result
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    return result


async def test_resume_continues_the_same_session_model_and_worktree(
    dispatcher, request_payload, fake_env, worker_invocations, monkeypatch
):
    first = await _dispatch_then(dispatcher, request_payload, monkeypatch)

    result = await dispatcher.resume_claude_task(
        first["task_id"], "Fix finding R1 only. Do not change the public API."
    )

    assert "error" not in result, result
    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert result["session_id"] == first["session_id"]      # §7.2
    assert result["selected_model"] == first["selected_model"]  # §18
    assert result["worktree"] == first["worktree"]          # §18
    assert result["resume_count"] == 1
    assert result["worker_claims"]["summary"].startswith("Resumed session")

    resume_call = worker_invocations()[-1]
    # Exit codes 3/4 would have fired had either of these been wrong.
    assert resume_call["has_resume"] is True
    assert resume_call["has_session_id"] is False
    assert resume_call["has_worktree"] is False        # no second worktree (§18)
    assert resume_call["resume_session_id"] == first["session_id"]
    assert resume_call["cwd"] == first["worktree"]
    assert resume_call["model"] == first["selected_model"]

    record = dispatcher.store.load(first["task_id"])
    assert record.resume_count == 1
    assert record.run_count == 2
    assert [h["to"] for h in record.state_history][-4:] == [
        "resume_requested",
        "running",
        "implemented",
        "awaiting_sol_review",
    ]


async def test_resume_takes_no_session_argument_at_all(dispatcher):
    """§7.2: 'Never trust the caller to supply a replacement session ID.'

    Structural guarantee, not a runtime check: the tool has no parameter a
    caller could put one in.
    """
    params = set(inspect.signature(Dispatcher.resume_claude_task).parameters)
    assert params == {"self", "task_id", "instruction", "timeout_seconds"}


async def test_resume_cap_returns_requires_orchestrator_decision(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """§7.2: the cap produces a *successful* refusal, not a protocol error."""
    request_payload["execution"]["max_resume_count"] = 1
    first = await _dispatch_then(dispatcher, request_payload, monkeypatch)
    task_id = first["task_id"]

    allowed = await dispatcher.resume_claude_task(task_id, "One more pass.")
    assert allowed["resume_count"] == 1

    refused = await dispatcher.resume_claude_task(task_id, "And another.")

    assert refused == {
        "status": "requires_orchestrator_decision",
        "reason": "resume_limit_reached",
        "task_id": task_id,
        "resume_count": 1,
        "max_resume_count": 1,
        "remediation": refused["remediation"],
    }
    assert "error" not in refused
    # The refusal changed nothing: no extra run, no state churn.
    record = dispatcher.store.load(task_id)
    assert record.resume_count == 1
    assert record.run_count == 2
    assert record.state is TaskState.AWAITING_SOL_REVIEW


async def test_resume_after_timeout_reuses_preserved_session_and_worktree(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """§20: a timed-out task still carries everything a resume needs."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "timeout")
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "30")
    request_payload["execution"]["timeout_seconds"] = 1
    timed_out = await dispatcher.dispatch_claude_task(request_payload)
    assert timed_out["status"] == TaskState.TIMED_OUT.value

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    result = await dispatcher.resume_claude_task(
        timed_out["task_id"], "Continue from where you stopped."
    )

    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert result["session_id"] == timed_out["session_id"]
    assert worker_invocations()[-1]["resume_session_id"] == timed_out["session_id"]


async def test_resume_after_malformed_worker_output_reuses_the_same_session(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """§15/§26: unparseable output lands FAILED with the session still intact.

    FAILED is an off-ramp, not a verdict on the work: the session id, the model
    and the worktree all survive, so a corrective resume is exactly the
    recoverable case the off-ramp exists for.
    """
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "malformed-json")
    failed = await dispatcher.dispatch_claude_task(request_payload)
    assert failed["status"] == TaskState.FAILED.value
    task_id = failed["task_id"]
    broken = dispatcher.store.load(task_id)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    result = await dispatcher.resume_claude_task(
        task_id, "Your last reply was not valid JSON. Re-emit the structured result."
    )

    assert "error" not in result, result
    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert result["session_id"] == broken.session_id      # §7.2 same session
    assert result["selected_model"] == broken.selected_model  # §18 same model
    assert result["worktree"] == broken.worktree_path     # §18 same worktree
    assert result["resume_count"] == 1

    resume_call = worker_invocations()[-1]
    assert resume_call["has_resume"] is True
    assert resume_call["has_worktree"] is False
    assert resume_call["resume_session_id"] == broken.session_id
    assert resume_call["cwd"] == broken.worktree_path

    record = dispatcher.store.load(task_id)
    assert [h["to"] for h in record.state_history][-5:] == [
        "failed",
        "resume_requested",
        "running",
        "implemented",
        "awaiting_sol_review",
    ]


async def test_resume_after_nonzero_worker_exit_recovers_the_task(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """A non-zero exit is a fact about the run, not a dead end (§26)."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "failure")
    failed = await dispatcher.dispatch_claude_task(request_payload)
    assert failed["status"] == TaskState.FAILED.value
    task_id = failed["task_id"]
    broken = dispatcher.store.load(task_id)
    assert broken.session_id and Path(broken.worktree_path).is_dir()

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    result = await dispatcher.resume_claude_task(
        task_id, "The previous run exited non-zero. Continue from the same session."
    )

    assert "error" not in result, result
    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert result["session_id"] == broken.session_id
    assert result["worktree"] == broken.worktree_path
    assert worker_invocations()[-1]["resume_session_id"] == broken.session_id
    assert dispatcher.store.load(task_id).resume_count == 1


async def test_resume_from_failed_without_a_stored_worktree_is_refused(
    dispatcher, request_payload, fake_env, monkeypatch, tmp_path
):
    """Legality is not feasibility: ``resume_plan`` still refuses damaged state.

    The transition table permits FAILED -> RESUME_REQUESTED; it says nothing
    about whether the state a resume must reuse actually exists. A worker that
    never produced a worktree leaves nothing to resume into, and the refusal is
    a structured error, not a traceback and certainly not a silent success.
    """
    # A file where the shim expects a directory: no worktree can be created.
    not_a_dir = tmp_path / "worktree-root-is-a-file"
    not_a_dir.write_text("not a directory\n")
    monkeypatch.setenv("FAKE_CLAUDE_WORKTREE_ROOT", str(not_a_dir))

    failed = await dispatcher.dispatch_claude_task(request_payload)
    assert failed["error"] == "WorktreeCreationFailed"
    task_id = failed["details"]["task_id"]
    record = dispatcher.store.load(task_id)
    assert record.state is TaskState.FAILED
    assert not record.worktree_path

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    refused = await dispatcher.resume_claude_task(task_id, "Try that again.")

    # The refusal comes from resume_plan's feasibility check, not from the
    # transition table — the table itself permits this edge.
    assert is_transition_allowed(TaskState.FAILED, TaskState.RESUME_REQUESTED)
    assert refused["error"] == "StateCorruption"
    assert refused["details"]["missing"] == ["worktree_path"]
    assert "traceback" not in json.dumps(refused).lower()

    # Nothing ran and nothing moved.
    after = dispatcher.store.load(task_id)
    assert after.state is TaskState.FAILED
    assert after.resume_count == 0
    assert after.run_count == record.run_count


async def test_resume_cap_still_holds_from_failed(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """§22 layer 6: the cap is consulted on the FAILED path too, in one place."""
    request_payload["execution"]["max_resume_count"] = 1
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "failure")

    failed = await dispatcher.dispatch_claude_task(request_payload)
    assert failed["status"] == TaskState.FAILED.value
    task_id = failed["task_id"]

    # The worker fails again, so the task is still FAILED when the cap binds.
    allowed = await dispatcher.resume_claude_task(task_id, "Try once more.")
    assert allowed["status"] == TaskState.FAILED.value
    assert allowed["resume_count"] == 1

    refused = await dispatcher.resume_claude_task(task_id, "And again.")

    assert refused == {
        "status": "requires_orchestrator_decision",
        "reason": "resume_limit_reached",
        "task_id": task_id,
        "resume_count": 1,
        "max_resume_count": 1,
        "remediation": refused["remediation"],
    }
    assert "error" not in refused
    record = dispatcher.store.load(task_id)
    assert record.state is TaskState.FAILED
    assert record.resume_count == 1
    assert record.run_count == 2


async def test_resume_of_unknown_task_is_a_concise_error(dispatcher):
    result = await dispatcher.resume_claude_task(
        "99999999-8888-4777-8666-555555555555", "go"
    )
    assert result["error"] == "TaskNotFound"
    assert "details" in result


async def test_resume_requires_a_non_empty_instruction(
    dispatcher, request_payload, fake_env, monkeypatch
):
    first = await _dispatch_then(dispatcher, request_payload, monkeypatch)
    result = await dispatcher.resume_claude_task(first["task_id"], "   ")
    assert result["error"] == "InvalidTaskEnvelope"


async def test_resume_survives_a_store_restart(
    dispatcher, request_payload, fake_env, monkeypatch, integration_config
):
    """§27: nothing authoritative lives in memory."""
    first = await _dispatch_then(dispatcher, request_payload, monkeypatch)

    reborn = Dispatcher(integration_config)  # a "restarted" server process
    result = await reborn.resume_claude_task(first["task_id"], "Carry on.")

    assert result["session_id"] == first["session_id"]
    assert result["worktree"] == first["worktree"]
    assert Path(result["worktree"]).is_dir()
