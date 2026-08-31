"""Killer tests for Gate 7 refusal/state coupling.

The phase is context authority, not an error-handler argument.  A failure
before a child exists is append-only audit evidence and must never rewrite the
task's authoritative state record.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import InternalDispatcherError, InvalidTaskEnvelope
from sol_claude_dispatcher.models import TaskEnvelope, TaskRequest, TaskState
from sol_claude_dispatcher.phase import (
    ExecutionPhase,
    ToolExecution,
    begin_tool_execution,
)
from sol_claude_dispatcher.server import Dispatcher
from sol_claude_dispatcher.state import TaskStore


def _envelope(valid_request_dict: dict) -> TaskEnvelope:
    return TaskEnvelope.from_request(
        TaskRequest.model_validate(valid_request_dict),
        canonical_root="/tmp/canonical/repository",
        base_commit="a" * 40,
    )


def _dispatcher_with_store(store: TaskStore) -> Dispatcher:
    dispatcher = object.__new__(Dispatcher)
    dispatcher.store = store
    return dispatcher


def _failure() -> InvalidTaskEnvelope:
    return InvalidTaskEnvelope(
        "Gate 7 pre-child refusal.",
        details={"control": "phase-refusal-killer"},
        remediation="Correct the request and retry.",
    )


@pytest.mark.parametrize("phase", [ExecutionPhase.PREPARE, ExecutionPhase.LAUNCH])
def test_pre_child_failure_appends_refusal_without_mutating_task_state(
    phase: ExecutionPhase, valid_request_dict: dict, tmp_path: Path
) -> None:
    store = TaskStore(tmp_path / "tasks")
    envelope = _envelope(valid_request_dict)
    store.create(envelope)
    if phase is ExecutionPhase.LAUNCH:
        store.transition(envelope.task_id, TaskState.ROUTED, reason="test_reserved")

    state_path = store.task_dir(envelope.task_id) / "state.json"
    before = state_path.read_bytes()
    dispatcher = _dispatcher_with_store(store)

    with begin_tool_execution("dispatch", task_id=envelope.task_id) as execution:
        if phase is ExecutionPhase.LAUNCH:
            execution.mark_reserved(object())
            execution.enter(ExecutionPhase.LAUNCH)
            assert execution.worker is None
        dispatcher._record_failure(execution, _failure())

    assert state_path.read_bytes() == before
    refusals = store.load_refusals(task_id=envelope.task_id)
    assert len(refusals) == 1
    assert refusals[0]["tool"] == "dispatch"
    assert refusals[0]["phase"] == phase.name
    assert refusals[0]["code"] == "InvalidTaskEnvelope"
    assert refusals[0]["details"] == {"control": "phase-refusal-killer"}


def test_post_spawn_failure_control_may_transition_running_task_to_failed(
    valid_request_dict: dict, tmp_path: Path
) -> None:
    """Control: the no-mutation rule ends once a real child is attached."""
    store = TaskStore(tmp_path / "tasks")
    envelope = _envelope(valid_request_dict)
    store.create(envelope)
    store.transition(envelope.task_id, TaskState.ROUTED, reason="test_reserved")
    store.transition(envelope.task_id, TaskState.RUNNING, reason="worker_spawned")
    dispatcher = _dispatcher_with_store(store)

    with begin_tool_execution("dispatch", task_id=envelope.task_id) as execution:
        execution.mark_reserved(object())
        execution.enter(ExecutionPhase.LAUNCH)
        execution.mark_spawned(object())
        dispatcher._record_failure(execution, _failure())

    assert store.load(envelope.task_id).state is TaskState.FAILED
    assert store.load_refusals(task_id=envelope.task_id) == []


def test_record_failure_signature_has_one_execution_authority() -> None:
    """No caller-supplied task or phase may compete with ToolExecution."""
    parameters = inspect.signature(Dispatcher._record_failure).parameters

    assert list(parameters) == ["self", "execution", "exc", "repository_key"]
    assert parameters["execution"].default is inspect.Parameter.empty
    assert parameters["exc"].default is inspect.Parameter.empty
    assert parameters["repository_key"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["repository_key"].default is None


def test_record_failure_refuses_foreign_execution_before_touching_storage(
    valid_request_dict: dict, tmp_path: Path
) -> None:
    """A forged execution cannot exploit best-effort diagnostic suppression."""
    store = TaskStore(tmp_path / "tasks")
    envelope = _envelope(valid_request_dict)
    store.create(envelope)
    state_path = store.task_dir(envelope.task_id) / "state.json"
    before = state_path.read_bytes()
    dispatcher = _dispatcher_with_store(store)

    with begin_tool_execution("dispatch", task_id=envelope.task_id):
        foreign = ToolExecution("dispatch", task_id=envelope.task_id)
        with pytest.raises(InternalDispatcherError, match="not current"):
            dispatcher._record_failure(foreign, _failure())

    assert state_path.read_bytes() == before
    assert store.load_refusals(task_id=envelope.task_id) == []
