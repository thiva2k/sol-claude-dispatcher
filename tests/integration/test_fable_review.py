"""Independent Fable review against the fake worker (§7.3, §19, §25, §41).

Two things matter here and are asserted from the fake binary's own invocation
log rather than from the dispatcher's return value: Fable is read-only, and
Fable never touches the implementation worker's conversation.
"""

from __future__ import annotations

import json

from sol_claude_dispatcher.models import TaskState
from sol_claude_dispatcher.runner import MUTATING_TOOL_NAMES


async def _dispatched(dispatcher, payload, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", "src/deploy/deploy.py")
    result = await dispatcher.dispatch_claude_task(payload)
    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value, result
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    return result


async def test_review_persists_findings_and_marks_fable_reviewed(
    dispatcher, request_payload, fake_env, monkeypatch
):
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]

    result = await dispatcher.review_task_with_fable(
        task_id, ["correctness", "architecture", "security", "tests"]
    )

    assert "error" not in result, result
    assert result["status"] == TaskState.FABLE_REVIEWED.value
    assert result["model"] == "fable"
    assert result["advisory"] is True
    assert result["review_number"] == 1
    assert result["review"]["verdict"] == "changes_required"
    assert result["review"]["findings"][0]["id"] == "F1"
    assert result["review"]["recommended_next_action"] == "resume_worker"

    # Persisted, and visible through the read-only tool.
    review_file = dispatcher.store.task_dir(task_id) / "reviews" / "fable-001.json"
    assert review_file.exists()
    view = await dispatcher.get_task(task_id)
    assert view["latest_fable_review"]["verdict"] == "changes_required"
    assert view["fable_review_count"] == 1
    assert view["status"] == TaskState.FABLE_REVIEWED.value


async def test_review_is_read_only_and_uses_a_fresh_session(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)

    result = await dispatcher.review_task_with_fable(dispatched["task_id"], ["security"])

    review_call = worker_invocations()[-1]
    # §19: a fresh session, never a resume of the worker's conversation.
    assert review_call["has_resume"] is False
    assert review_call["session_id"] == result["session_id"]
    assert review_call["session_id"] != dispatched["session_id"]
    # §7.3: read-only tools, no worktree creation, no mutation path.
    assert review_call["tools"] == ["Read", "Glob", "Grep"]
    assert review_call["has_worktree"] is False
    assert review_call["model"] == "fable"
    for mutating in MUTATING_TOOL_NAMES:
        assert mutating not in review_call["tools"]
        assert mutating in review_call["disallowed_tools"]
    assert "mcp__*" in review_call["disallowed_tools"]
    assert "Agent" in review_call["disallowed_tools"]
    # Reviews run inside the worker's worktree, reading what it produced.
    assert review_call["cwd"] == dispatched["worktree"]


async def test_review_prompt_carries_the_stable_evidence_bundle(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """§19: objective, criteria, base commit, diff, worker report, validation."""
    request_payload["validation"] = {"commands": [{"argv": ["/bin/true"]}]}
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)

    await dispatcher.review_task_with_fable(dispatched["task_id"], ["correctness"])

    prompt = worker_invocations()[-1]["prompt"]
    envelope = dispatcher.store.load_envelope(dispatched["task_id"])
    assert envelope.task.objective in prompt
    assert envelope.task.acceptance_criteria[0] in prompt
    assert envelope.repository.base_commit in prompt
    assert "src/deploy/deploy.py" in prompt
    assert "Worker report (claims, not evidence)" in prompt
    assert '"source": "dispatcher"' in prompt
    assert "- correctness" in prompt


async def test_review_never_approves(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """§26/§41: there is no approval state and a review cannot invent one."""
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)

    await dispatcher.review_task_with_fable(dispatched["task_id"])

    record = dispatcher.store.load(dispatched["task_id"])
    assert record.state is TaskState.FABLE_REVIEWED
    assert "approved" not in {s.value for s in type(record.state)}
    assert all(h["to"] != "review_complete" for h in record.state_history)


async def test_review_is_refused_while_the_repository_lock_is_held(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """P0/P1-4: a review of a repository being mutated is a review of nothing.

    This replaces ``test_review_takes_no_repository_lock``, which asserted the
    pre-fix behaviour. Read-only is not the same as consistent: while a worker
    (or a second review) holds the repository, Fable would be reading a moving
    target, so it now refuses immediately with ``RepositoryBusy`` rather than
    reviewing mixed state. The assertion is inverted deliberately, and the
    coverage is not reduced — the lock interaction is still exercised, plus the
    three concurrency cases in ``test_lifecycle_invariants.py``.
    """
    from sol_claude_dispatcher.locks import RepositoryLock

    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    root = dispatcher.store.load_envelope(dispatched["task_id"]).repository.root

    with RepositoryLock(root, dispatcher.config.locks_path):
        result = await dispatcher.review_task_with_fable(dispatched["task_id"])

    assert result["error"] == "RepositoryBusy"
    assert result["retryable"] is True
    # Nothing was recorded against the task: no review, no state change.
    record = dispatcher.store.load(dispatched["task_id"])
    assert record.state is TaskState.AWAITING_SOL_REVIEW
    assert record.fable_review_count == 0

    # And the refusal did not wedge the repository: the very next review works.
    after = await dispatcher.review_task_with_fable(dispatched["task_id"])
    assert after["status"] == TaskState.FABLE_REVIEWED.value


async def test_review_of_a_task_with_no_worktree_is_refused(
    dispatcher, request_payload, fake_env, monkeypatch
):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")
    dispatched = await dispatcher.dispatch_claude_task(request_payload)

    record = dispatcher.store.load(dispatched["task_id"])
    record.worktree_path = None
    dispatcher.store.save(record)

    result = await dispatcher.review_task_with_fable(dispatched["task_id"])
    assert result["error"] == "StateCorruption"


async def test_unparseable_review_output_is_reported_not_guessed(
    dispatcher, request_payload, fake_env, monkeypatch
):
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    monkeypatch.setenv("FAKE_CLAUDE_STDOUT", "not json at all")

    result = await dispatcher.review_task_with_fable(dispatched["task_id"])

    assert result["error"] == "ClaudeStructuredOutputInvalid"
    # The task did not move; the review run is still recorded as evidence.
    record = dispatcher.store.load(dispatched["task_id"])
    assert record.state is TaskState.AWAITING_SOL_REVIEW
    assert record.run_count == 2
    assert record.fable_review_count == 0


async def test_reviewer_cli_failure_is_reported_as_a_cli_failure_not_bad_output(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """DEFECT-L2-02, reviewer half: the Fable path shares the same trap.

    ``_review`` parsed the reviewer's stdout directly, so a reviewer CLI that
    exited non-zero without writing anything surfaced as
    ``ClaudeStructuredOutputInvalid`` — the review's failure attributed to the
    model rather than to the CLI that never ran.
    """
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "failure")

    result = await dispatcher.review_task_with_fable(dispatched["task_id"], ["security"])

    assert result["error"] == "ClaudeExecutionFailed"
    assert "simulated worker failure" in result["details"]["stderr_tail"]
    assert result["details"]["role"] == "reviewer"
    assert result["details"]["exit_code"] == 2
    assert "not valid JSON" not in json.dumps(result)

    # The task is not marked reviewed on a CLI failure, and the repository lock
    # is released — a second attempt is refused for the CLI reason, not for a
    # stale lock.
    record = dispatcher.store.load(dispatched["task_id"])
    assert record.state is not TaskState.FABLE_REVIEWED
    again = await dispatcher.review_task_with_fable(dispatched["task_id"], ["security"])
    assert again["error"] == "ClaudeExecutionFailed"
