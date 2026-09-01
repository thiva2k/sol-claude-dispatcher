"""Gate 7 Wave-0 execution-phase authority."""

from __future__ import annotations

import inspect

import pytest

from sol_claude_dispatcher.errors import InternalDispatcherError, PhaseRegression
from sol_claude_dispatcher.phase import (
    ExecutionPhase,
    begin_tool_execution,
    current_execution,
    require_current_execution,
)


def test_execution_phase_order_is_the_normative_monotone_order() -> None:
    assert list(ExecutionPhase) == [
        ExecutionPhase.PREPARE,
        ExecutionPhase.RESERVE,
        ExecutionPhase.LAUNCH,
        ExecutionPhase.EXECUTE,
        ExecutionPhase.FINALIZE,
        ExecutionPhase.LAND,
    ]
    assert [phase.value for phase in ExecutionPhase] == [1, 2, 3, 4, 5, 6]


def test_tool_execution_starts_in_prepare_and_advances_monotonically() -> None:
    with begin_tool_execution("dispatch", task_id="task-1") as execution:
        assert current_execution() is execution
        assert require_current_execution() is execution
        assert execution.tool == "dispatch"
        assert execution.task_id == "task-1"
        assert execution.phase is ExecutionPhase.PREPARE
        assert execution.reservation is None
        assert execution.worker is None

        execution.enter(ExecutionPhase.RESERVE)
        execution.enter(ExecutionPhase.RESERVE)  # idempotent assertion/entry
        execution.enter(ExecutionPhase.LAUNCH)
        assert execution.phase is ExecutionPhase.LAUNCH

    assert current_execution() is None


def test_phase_regression_is_a_loud_internal_error() -> None:
    with begin_tool_execution("resume") as execution:
        execution.enter(ExecutionPhase.FINALIZE)
        with pytest.raises(PhaseRegression) as caught:
            execution.enter(ExecutionPhase.EXECUTE)

    assert caught.value.details == {
        "tool": "resume",
        "from": "FINALIZE",
        "to": "EXECUTE",
    }


def test_mark_spawned_requires_launch_and_proves_worker_presence() -> None:
    worker = object()
    with begin_tool_execution("dispatch") as execution:
        with pytest.raises(InternalDispatcherError):
            execution.mark_spawned(worker)

        execution.enter(ExecutionPhase.LAUNCH)
        execution.mark_spawned(worker)
        assert execution.phase is ExecutionPhase.EXECUTE
        assert execution.worker is worker


def test_reservation_cannot_be_bound_after_launch_or_replaced() -> None:
    reservation = object()
    with begin_tool_execution("dispatch") as execution:
        execution.mark_reserved(reservation)
        assert execution.phase is ExecutionPhase.RESERVE
        assert execution.reservation is reservation
        with pytest.raises(InternalDispatcherError):
            execution.mark_reserved(object())


def test_task_id_may_be_bound_once_when_created_after_preflight() -> None:
    with begin_tool_execution("dispatch") as execution:
        execution.bind_task("task-1")
        execution.bind_task("task-1")
        assert execution.task_id == "task-1"
        with pytest.raises(InternalDispatcherError):
            execution.bind_task("task-2")


def test_nested_tool_execution_is_refused_and_context_resets_on_exception() -> None:
    with pytest.raises(RuntimeError):
        with begin_tool_execution("dispatch") as outer:
            with pytest.raises(InternalDispatcherError):
                with begin_tool_execution("review"):
                    pass
            assert current_execution() is outer
            raise RuntimeError("boom")

    assert current_execution() is None
    with pytest.raises(InternalDispatcherError):
        require_current_execution()


def test_constructor_does_not_accept_a_phase() -> None:
    from sol_claude_dispatcher.phase import ToolExecution

    assert "phase" not in inspect.signature(ToolExecution).parameters

