"""Server-side blocking semantics for the MCP tools (GATE 6). — Wave 6.

The problem this module exists to solve
---------------------------------------

``dispatch_claude_task`` is supposed to be *one* MCP call per worker run. Sol
issues it, the request stays pending while Claude works, and it returns when the
run reaches a state that requires a decision from Sol. Sol must never have to
poll ``get_task`` to find out whether the worker finished: polling burns model
tokens and, worse, ends Sol's turn — which needs a human to restart the loop and
defeats the whole product goal of an autonomous ``Sol -> Claude -> Sol`` handoff.

Awaiting the run inside the tool body gets the *waiting* right on its own. What
it gets wrong is **ownership**. An ``await`` chain from an MCP request down to
``asyncio.create_subprocess_exec`` couples the worker's lifetime to the caller's
patience: cancel the request — because the MCP client's tool timeout fired,
because the transport dropped, because Sol's turn was interrupted — and the
cancellation propagates straight through the tool body. The lock's ``finally``
releases, the evidence is never collected, the task is left frozen in
``RUNNING``, and a retry is free to start a *second* worker against the same
repository while the first is still alive.

That is the defect this module closes. Two rules, and they are the whole design:

**1. The dispatcher owns the run; the waiter only observes it.**
Every tool body that starts a worker runs as an :class:`asyncio.Task` created
and held by :class:`RunRegistry`. The MCP request awaits it through
:func:`asyncio.shield`, so cancelling the request cancels *the wait* and never
the run. The run keeps its repository lock, finishes its Claude process,
collects its evidence, records its state transition, and lands in one of the
:data:`WORKER_ACTIONABLE_STATES`. A later ``get_task`` recovers the authoritative
result, because the run persisted it exactly as it always did.

**2. A duplicate waiter attaches; it never starts a second run.**
Keys are supplied by the caller (see ``server._resume_key`` /
``server._review_key``). A second waiter arriving with the same key while a run
is in flight awaits the *same* task and receives the *same* result object.

Deliberately not here
---------------------

No fifth MCP tool. This module is an internal execution primitive; it adds
nothing to the tool surface, and it must not grow a "watch" or "subscribe"
entry point — §1 of the gate brief is non-negotiable.

No pushing, no waking, no callbacks to the client. The server never contacts
Sol. The original tool call simply stays in flight.

No timeout of its own. The *Claude execution* timeout belongs to
``runner.run_worker`` and produces a real ``TIMED_OUT`` transition; the *MCP
client* timeout belongs to the client and simply cancels the waiter. Adding a
third, waiter-side deadline here would conflate the two and is exactly the
mistake §7 of the gate brief forbids.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from .models import TaskState

__all__ = [
    "WORKER_ACTIONABLE_STATES",
    "blocking_envelope",
    "RunRegistry",
]

logger = logging.getLogger("sol_claude_dispatcher.waiting")

#: The states a *worker run* can land in that require Sol to decide what happens
#: next. A blocking tool call returns the moment the run reaches one of them and
#: never waits through one.
#:
#: There is no ``APPROVED`` member of :class:`~sol_claude_dispatcher.models.TaskState`
#: and there must not be one, so nothing in this set can be read as approval —
#: ``AWAITING_SOL_REVIEW`` in particular means "the worker stopped and the
#: evidence is on disk", never "the work is good". ``FABLE_REVIEWED`` and
#: ``REVIEW_COMPLETE`` are deliberately absent: they are outcomes of *Sol's* own
#: actions, not of a worker run.
WORKER_ACTIONABLE_STATES: frozenset[TaskState] = frozenset(
    {
        TaskState.AWAITING_SOL_REVIEW,
        TaskState.TIMED_OUT,
        TaskState.BLOCKED,
        TaskState.FAILED,
        TaskState.POLICY_VIOLATION,
    }
)


def blocking_envelope(state: TaskState) -> dict[str, Any]:
    """The ``blocking`` block attached to every blocking tool's result.

    It restates, in the payload itself, what the tool descriptions and the
    server instructions say in prose: this call already waited, no polling is
    required, and the next move belongs to Sol. Stating it in-band matters
    because the instructions are read once at initialise time while this travels
    with every single result.

    ``worker_actionable`` is measured, not asserted: a state outside
    :data:`WORKER_ACTIONABLE_STATES` (a completed Fable review, say) is reported
    honestly as ``False`` rather than being dressed up as a worker outcome.
    """
    return {
        "waited_server_side": True,
        "polling_required": False,
        "worker_actionable": state in WORKER_ACTIONABLE_STATES,
        "sol_must_decide_next_action": True,
    }


class RunRegistry:
    """Dispatcher-owned registry of in-flight tool runs (§5).

    One instance per :class:`~sol_claude_dispatcher.server.Dispatcher`. Holds a
    strong reference to every running task, so a run whose waiter has gone away
    is never garbage collected mid-flight.
    """

    def __init__(self) -> None:
        self._runs: dict[str, asyncio.Task[dict[str, Any]]] = {}

    # -- inspection --------------------------------------------------------

    def keys(self) -> tuple[str, ...]:
        """Keys of the runs still executing. Sorted, for stable diagnostics."""
        return tuple(sorted(key for key, task in self._runs.items() if not task.done()))

    def snapshot(self) -> tuple[asyncio.Task[dict[str, Any]], ...]:
        """Every task currently held, done or not."""
        return tuple(self._runs.values())

    # -- execution ---------------------------------------------------------

    async def run(
        self, key: str, factory: Callable[[], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        """Start (or attach to) the run under *key* and wait for its result.

        The coroutine ``factory`` builds is executed as a task owned by this
        registry. The caller awaits it through :func:`asyncio.shield`, so:

        * cancelling the caller cancels **only** the wait;
        * the run continues, keeps its lock, and persists its own outcome;
        * a later waiter with the same key attaches instead of starting a
          second worker.

        ``factory`` is expected to return a payload rather than raise — the
        server wraps every tool body in its error guard before handing it
        here — so an attaching waiter always receives the same object the first
        waiter would have.
        """
        task = self._runs.get(key)
        if task is None or task.done():
            task = asyncio.get_running_loop().create_task(
                factory(), name=f"sol-dispatcher-run:{key}"
            )
            self._runs[key] = task
            task.add_done_callback(lambda finished, k=key: self._retire(k, finished))
        else:
            logger.info("attaching an additional waiter to in-flight run %s", key)

        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                # The run itself finished (or was cancelled with the loop); this
                # cancellation is not a detached waiter and there is nothing to
                # report.
                raise
            # §5: the waiter is gone, the worker is not. Say so in the log — it
            # is the only trace of the disconnect, and an operator looking for
            # the task later needs to know the dispatcher still owns it.
            logger.warning(
                "MCP waiter for run %s was cancelled; the worker keeps running "
                "and its final state will be persisted for get_task recovery",
                key,
            )
            raise

    async def drain(self, timeout: float | None = None) -> None:
        """Wait for every held run to finish.

        Used by the tests, and available to a shutdown path that wants to let
        dispatcher-owned workers land their evidence rather than abandoning
        them. Never cancels anything: cancelling here would recreate exactly the
        coupling this module removes.
        """
        pending = [task for task in self._runs.values() if not task.done()]
        if not pending:
            return
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True), timeout
        )

    # -- internals ---------------------------------------------------------

    def _retire(self, key: str, task: asyncio.Task[dict[str, Any]]) -> None:
        """Drop a finished run, and retrieve its exception so asyncio stays quiet.

        The identity check matters: a fresh run may already have been registered
        under the same key by the time this callback fires, and it must not be
        evicted by its predecessor's completion.
        """
        if self._runs.get(key) is task:
            del self._runs[key]
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:  # pragma: no cover - the server guards tool bodies
            logger.error(
                "dispatcher-owned run %s raised past the error guard: %s",
                key,
                exception,
                exc_info=exception,
            )
