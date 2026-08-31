"""Unforgeable execution-phase authority for Gate 7 tool bodies.

The phase is carried by one context-local :class:`ToolExecution`, not by a
caller-supplied argument.  This makes PREPARE refusal semantics depend on the
furthest point the tool actually reached rather than on a literal a failure
handler could accidentally misstate.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from enum import IntEnum
from typing import Any, Iterator, final

from .errors import InternalDispatcherError, PhaseRegression

__all__ = [
    "ExecutionPhase",
    "ToolExecution",
    "begin_tool_execution",
    "current_execution",
    "require_current_execution",
]


class ExecutionPhase(IntEnum):
    """Monotone phases of one dispatcher tool execution."""

    PREPARE = 1
    RESERVE = 2
    LAUNCH = 3
    EXECUTE = 4
    FINALIZE = 5
    LAND = 6


_CURRENT: ContextVar[ToolExecution | None] = ContextVar(
    "sol_dispatcher_tool_execution", default=None
)


@final
class ToolExecution:
    """The sole carrier of a tool body's phase and associated authority.

    Construction accepts no phase: every instance begins in PREPARE.  The
    reservation and worker slots are deliberately write-once so an execution
    cannot claim to be earlier than durable authority it already acquired.
    Use :func:`begin_tool_execution`; direct construction does not install the
    instance as the current execution and therefore cannot pass the identity
    check used by failure handling.
    """

    __slots__ = ("_tool", "_task_id", "_phase", "_reservation", "_worker")

    def __init__(self, tool: str, task_id: str | None = None) -> None:
        if not isinstance(tool, str) or not tool.strip():
            raise InternalDispatcherError("Tool execution requires a non-empty tool name.")
        self._tool = tool
        self._task_id = task_id
        self._phase = ExecutionPhase.PREPARE
        self._reservation: Any | None = None
        self._worker: Any | None = None

    @property
    def tool(self) -> str:
        return self._tool

    @property
    def task_id(self) -> str | None:
        return self._task_id

    @property
    def phase(self) -> ExecutionPhase:
        return self._phase

    @property
    def reservation(self) -> Any | None:
        return self._reservation

    @property
    def worker(self) -> Any | None:
        return self._worker

    def bind_task(self, task_id: str) -> None:
        """Bind the task id once it exists; never silently replace it."""
        if not isinstance(task_id, str) or not task_id:
            raise InternalDispatcherError("Tool execution requires a non-empty task id.")
        if self._task_id is not None and self._task_id != task_id:
            raise InternalDispatcherError(
                "Tool execution cannot be rebound to a different task.",
                details={"tool": self._tool},
            )
        self._task_id = task_id

    def enter(self, phase: ExecutionPhase) -> None:
        """Advance monotonically; an attempted regression is always loud."""
        if not isinstance(phase, ExecutionPhase):
            raise InternalDispatcherError(
                "Tool execution received an invalid execution phase.",
                details={"tool": self._tool, "phase": repr(phase)},
            )
        if phase < self._phase:
            raise PhaseRegression(
                "Tool execution phase cannot move backwards.",
                details={
                    "tool": self._tool,
                    "from": self._phase.name,
                    "to": phase.name,
                },
            )
        self._phase = phase

    def assert_phase(self, expected: ExecutionPhase) -> None:
        """Fail loudly unless the execution is at ``expected`` exactly."""
        if self._phase is not expected:
            raise InternalDispatcherError(
                "Tool execution is in the wrong execution phase.",
                details={
                    "tool": self._tool,
                    "expected": expected.name,
                    "actual": self._phase.name,
                },
            )

    def mark_reserved(self, reservation: Any) -> None:
        """Attach a write-once reservation and enter RESERVE."""
        self.assert_phase(ExecutionPhase.PREPARE)
        if reservation is None or self._reservation is not None:
            raise InternalDispatcherError(
                "Tool execution reservation is missing or already set.",
                details={"tool": self._tool},
            )
        self._reservation = reservation
        self.enter(ExecutionPhase.RESERVE)

    def mark_spawned(self, worker: Any) -> None:
        """Attach proof that a child exists and advance LAUNCH to EXECUTE."""
        self.assert_phase(ExecutionPhase.LAUNCH)
        if worker is None or self._worker is not None:
            raise InternalDispatcherError(
                "Tool execution worker is missing or already set.",
                details={"tool": self._tool},
            )
        self._worker = worker
        self.enter(ExecutionPhase.EXECUTE)


def current_execution() -> ToolExecution | None:
    """Return the context-local execution, if a tool body is active."""
    return _CURRENT.get()


def require_current_execution() -> ToolExecution:
    """Return the current execution or raise a typed internal error."""
    execution = current_execution()
    if execution is None:
        raise InternalDispatcherError("No dispatcher tool execution is current.")
    return execution


@contextmanager
def begin_tool_execution(
    tool: str, *, task_id: str | None = None
) -> Iterator[ToolExecution]:
    """Create and install the one execution for a tool body; refuse nesting."""
    if current_execution() is not None:
        raise InternalDispatcherError(
            "Dispatcher tool executions may not be nested.",
            details={"tool": tool},
        )
    execution = ToolExecution(tool, task_id)
    token = _CURRENT.set(execution)
    try:
        yield execution
    finally:
        _CURRENT.reset(token)
