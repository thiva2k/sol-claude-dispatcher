"""B3 — a provider usage limit through the whole dispatch lifecycle.

The fake binary is driven with ``FAKE_CLAUDE_STDOUT`` set to the **real**
``c5e385c9`` result envelope (redacted; see
``tests/unit/test_provider_limit.py`` for provenance) and exits **0**, which is
exactly what the production CLI did: a well-formed envelope carrying
``is_error: true``, ``terminal_reason: "api_error"`` and ``api_error_status:
429``, with no structured payload anywhere inside it.

Before B3 that landed ``FAILED / unparseable_worker_result`` with a
``ClaudeStructuredOutputInvalid`` payload — a false diagnosis blaming the
model's output schema for a provider quota. These tests pin the corrected
behaviour end to end, including that the task remains resumable and that the
persisted state leaks neither the prompt nor a secret.
"""

from __future__ import annotations

import json
from pathlib import Path

from sol_claude_dispatcher.models import TaskState

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REAL_429_ENVELOPE = (FIXTURES / "claude_429_usage_limit_envelope.json").read_text()

SECRET = "ANTHROPIC_API_KEY=sk-ant-live-do-not-log-me"


def _limit_stdout(**overrides) -> str:
    envelope = json.loads(REAL_429_ENVELOPE)
    envelope.update(overrides)
    return json.dumps(envelope)


async def test_a_429_lands_failed_as_a_provider_limit_not_a_schema_defect(
    dispatcher, request_payload, fake_env, monkeypatch
):
    monkeypatch.setenv("FAKE_CLAUDE_STDOUT", REAL_429_ENVELOPE)

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.FAILED.value
    last_error = result["last_error"]
    assert last_error["error"] == "ClaudeProviderLimit"
    assert last_error["retryable"] is True
    assert last_error["details"]["api_error_status"] == 429
    assert last_error["details"]["terminal_reason"] == "api_error"
    assert last_error["details"]["exit_code"] == 0
    assert "weekly limit" in last_error["details"]["provider_message"]

    record = dispatcher.store.load(result["task_id"])
    assert record.state is TaskState.FAILED
    assert record.state_history[-1]["reason"] == "provider_usage_limit"
    assert record.last_error["error"] == "ClaudeProviderLimit"

    # The old, wrong verdict is gone from every reported surface.
    blob = json.dumps(result, default=str)
    assert "ClaudeStructuredOutputInvalid" not in blob
    assert "unparseable_worker_result" not in blob


async def test_the_measured_half_records_the_trusted_envelope_signals(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """§16: this is dispatcher-measured evidence, not a worker claim."""
    monkeypatch.setenv("FAKE_CLAUDE_STDOUT", REAL_429_ENVELOPE)

    result = await dispatcher.dispatch_claude_task(request_payload)

    observations = result["dispatcher_observations"]
    assert observations["api_error_status"] == 429
    assert observations["terminal_reason"] == "api_error"
    assert observations["exit_code"] == 0
    assert observations["timed_out"] is False
    assert observations["worker_result_parsed"] is False
    assert "ClaudeProviderLimit" in observations["worker_result_error"]
    # Evidence still exists: a provider limit is not an excuse to lose it.
    task_dir = Path(dispatcher.store.task_dir(result["task_id"]))
    assert (task_dir / "runs" / "001" / "stdout.json").exists()
    assert (task_dir / "evidence" / "diff.patch").exists()


async def test_persisted_state_leaks_neither_the_prompt_nor_a_secret(
    dispatcher, request_payload, fake_env, monkeypatch
):
    request_payload["task"]["context"] = (
        "SENTINEL-CONTEXT-STRING that must never reach an error payload."
    )
    monkeypatch.setenv(
        "FAKE_CLAUDE_STDOUT",
        _limit_stdout(result=f"You've hit your weekly limit. {SECRET}"),
    )

    result = await dispatcher.dispatch_claude_task(request_payload)
    state = json.loads(
        (Path(dispatcher.store.task_dir(result["task_id"])) / "state.json").read_text()
    )

    payload = json.dumps(state["last_error"], default=str)
    assert "sk-ant-live-do-not-log-me" not in payload
    assert "SENTINEL-CONTEXT-STRING" not in payload
    assert "--append-system-prompt" not in payload
    assert len(payload) < 4000


async def test_a_worker_that_merely_writes_429_still_completes_normally(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """Model-generated text can never trigger the provider-limit branch."""
    envelope = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 12,
        "num_turns": 3,
        "session_id": "00000000-0000-4000-8000-000000000000",
        "total_cost_usd": 0.1,
        "result": "Hit a 429 rate limit in the fixture I wrote; terminal_reason api_error.",
        "structured_output": {
            "status": "completed",
            "summary": "Added retry handling for HTTP 429 rate limit responses.",
            "changes": [],
            "acceptance_criteria": [],
            "tests": [],
            "risks": ["api_error_status 429 is only simulated in tests"],
            "blockers": [],
            "needs_review": True,
        },
    }
    monkeypatch.setenv("FAKE_CLAUDE_STDOUT", json.dumps(envelope))

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert result["last_error"] is None
    assert result["worker_claims"]["status"] == "completed"
    assert result["dispatcher_observations"]["api_error_status"] is None


async def test_a_task_killed_by_a_provider_limit_is_still_resumable(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    monkeypatch.setenv("FAKE_CLAUDE_STDOUT", REAL_429_ENVELOPE)
    limited = await dispatcher.dispatch_claude_task(request_payload)
    assert limited["status"] == TaskState.FAILED.value

    # The limit window resets; the same session, worktree and model continue.
    monkeypatch.delenv("FAKE_CLAUDE_STDOUT")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    resumed = await dispatcher.resume_claude_task(
        limited["task_id"], "The weekly limit reset; continue where you stopped."
    )

    assert "error" not in resumed, resumed
    assert resumed["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert resumed["session_id"] == limited["session_id"]
    assert resumed["worktree"] == limited["worktree"]
    assert worker_invocations()[-1]["resume_session_id"] == limited["session_id"]

    record = dispatcher.store.load(limited["task_id"])
    assert [h["to"] for h in record.state_history][-5:] == [
        "failed",
        "resume_requested",
        "running",
        "implemented",
        "awaiting_sol_review",
    ]


async def test_the_classification_follows_the_run_not_the_task(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """Run 001 is healthy; the resume hits the limit. Neither borrows the
    other's envelope.

    Lane P found the mirror-image bug in the gate harness: an envelope selected
    per *task* (first parseable file wins) always answered for run 001, so a
    limited resume could hide behind a healthy dispatch. The dispatcher is
    structurally immune — ``provider_failure`` reads the in-memory ``WorkerRun``
    of the run being finalised and never searches the task directory — and this
    test pins that rather than leaving it to inspection.
    """
    first = await dispatcher.dispatch_claude_task(request_payload)
    assert first["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert first["dispatcher_observations"]["api_error_status"] is None

    monkeypatch.setenv("FAKE_CLAUDE_STDOUT", REAL_429_ENVELOPE)
    resumed = await dispatcher.resume_claude_task(first["task_id"], "Carry on.")

    assert resumed["status"] == TaskState.FAILED.value
    assert resumed["last_error"]["error"] == "ClaudeProviderLimit"
    assert resumed["dispatcher_observations"]["api_error_status"] == 429

    # Both runs are on disk, each carrying its own verdict.
    assert dispatcher.store.load(first["task_id"]).run_count == 2
    runs = dispatcher.store.load_runs(first["task_id"])
    assert len(runs) == 2
    assert runs[0].dispatcher_observations.api_error_status is None
    assert runs[0].worker_claims is not None
    assert runs[1].dispatcher_observations.api_error_status == 429
    assert runs[1].worker_claims is None


async def test_a_reviewer_that_hits_the_limit_reports_it_as_one(
    dispatcher, request_payload, fake_env, monkeypatch
):
    first = await dispatcher.dispatch_claude_task(request_payload)
    assert first["status"] == TaskState.AWAITING_SOL_REVIEW.value

    monkeypatch.setenv("FAKE_CLAUDE_STDOUT", REAL_429_ENVELOPE)
    review = await dispatcher.review_task_with_fable(first["task_id"])

    assert review["error"] == "ClaudeProviderLimit"
    assert review["details"]["api_error_status"] == 429
    assert review["details"]["role"] == "reviewer"
    assert review["retryable"] is True
    # The advisory review never landed, and the task did not move.
    assert dispatcher.store.load(first["task_id"]).state is TaskState.AWAITING_SOL_REVIEW


async def test_a_non_limit_api_error_is_reported_as_an_execution_failure(
    dispatcher, request_payload, fake_env, monkeypatch
):
    monkeypatch.setenv("FAKE_CLAUDE_STDOUT", _limit_stdout(api_error_status=503))

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.FAILED.value
    assert result["last_error"]["error"] == "ClaudeExecutionFailed"
    assert result["last_error"]["details"]["reason"] == "provider_api_error"
    record = dispatcher.store.load(result["task_id"])
    assert record.state_history[-1]["reason"] == "provider_api_error"


async def test_a_genuine_schema_failure_still_lands_as_a_schema_failure(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """The taxonomy's other branches are untouched by B3."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "malformed-json")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.FAILED.value
    assert result["last_error"]["error"] == "ClaudeStructuredOutputInvalid"
    record = dispatcher.store.load(result["task_id"])
    assert record.state_history[-1]["reason"] == "unparseable_worker_result"
