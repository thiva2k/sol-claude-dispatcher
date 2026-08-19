"""Independent Fable review against the fake worker (§7.3, §19, §25, §41).

Two things matter here and are asserted from the fake binary's own invocation
log rather than from the dispatcher's return value: Fable is read-only, and
Fable never touches the implementation worker's conversation.
"""

from __future__ import annotations

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


async def test_review_takes_no_repository_lock(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """§25: review is read-only, so a busy repository must not block it."""
    from sol_claude_dispatcher.locks import RepositoryLock

    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    root = dispatcher.store.load_envelope(dispatched["task_id"]).repository.root

    with RepositoryLock(root, dispatcher.config.locks_path):
        result = await dispatcher.review_task_with_fable(dispatched["task_id"])

    assert result["status"] == TaskState.FABLE_REVIEWED.value


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
