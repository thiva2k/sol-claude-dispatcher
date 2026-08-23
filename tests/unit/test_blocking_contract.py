"""GATE 6 §1/§2/§8 — the *stated* contract, asserted against literal text.

This module is deliberately literal. Every assertion names the exact words the
token/autonomy contract depends on, so deleting a sentence from
``SERVER_INSTRUCTIONS`` or emptying a tool description **fails** rather than
passing vacuously. A correct blocking implementation is still defeated if the
model is told to poll, so the instructions are treated as load-bearing code.

Nothing here starts a process. The behavioural proof lives in
``tests/integration/test_blocking_semantics.py``.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from sol_claude_dispatcher.models import TaskState
from sol_claude_dispatcher.server import (
    SERVER_INSTRUCTIONS,
    TOOL_DESCRIPTIONS,
    TOOL_NAMES,
    Dispatcher,
)
from sol_claude_dispatcher.waiting import (
    WORKER_ACTIONABLE_STATES,
    RunRegistry,
    blocking_envelope,
)

#: Every name a "just add a waiting tool" refactor reaches for. §1 forbids all
#: of them: the four tools are the whole surface.
FORBIDDEN_FIFTH_TOOLS = (
    "wait_for_task",
    "poll_task",
    "subscribe_task",
    "watch_task",
    "await_task",
    "watch",
    "wait",
    "poll",
    "subscribe",
    "stream_task",
    "tail_task",
)


# ---------------------------------------------------------------------------
# §1 — exactly four tools
# ---------------------------------------------------------------------------


def test_the_tool_surface_is_exactly_the_four_named_tools():
    assert TOOL_NAMES == (
        "dispatch_claude_task",
        "resume_claude_task",
        "review_task_with_fable",
        "get_task",
    )
    assert len(TOOL_NAMES) == 4


def test_no_fifth_watch_or_wait_tool_exists_on_the_surface():
    for forbidden in FORBIDDEN_FIFTH_TOOLS:
        assert forbidden not in TOOL_NAMES
        assert forbidden not in TOOL_DESCRIPTIONS


def test_the_dispatcher_exposes_no_fifth_public_tool_method():
    """A public coroutine on ``Dispatcher`` is one MCP call away from being a tool."""
    public_coroutines = {
        name
        for name, member in inspect.getmembers(Dispatcher, inspect.isfunction)
        if not name.startswith("_") and inspect.iscoroutinefunction(member)
    }
    assert public_coroutines == {
        "dispatch_claude_task",
        "resume_claude_task",
        "review_task_with_fable",
        "get_task",
        # Not a tool and not reachable over MCP: an in-process helper the
        # server process and the tests use to await dispatcher-owned workers.
        "drain",
    }
    for forbidden in FORBIDDEN_FIFTH_TOOLS:
        assert forbidden not in public_coroutines


def test_every_tool_name_has_a_description():
    assert set(TOOL_DESCRIPTIONS) == set(TOOL_NAMES)
    for name, description in TOOL_DESCRIPTIONS.items():
        assert description.strip(), name


# ---------------------------------------------------------------------------
# §2 — the worker-actionable state set
# ---------------------------------------------------------------------------


def test_worker_actionable_states_are_exactly_the_five_states_sol_must_decide_on():
    assert WORKER_ACTIONABLE_STATES == frozenset(
        {
            TaskState.AWAITING_SOL_REVIEW,
            TaskState.TIMED_OUT,
            TaskState.BLOCKED,
            TaskState.FAILED,
            TaskState.POLICY_VIOLATION,
        }
    )
    assert len(WORKER_ACTIONABLE_STATES) == 5
    assert {s.value for s in WORKER_ACTIONABLE_STATES} == {
        "awaiting_sol_review",
        "timed_out",
        "blocked",
        "failed",
        "policy_violation",
    }


def test_no_approval_state_is_ever_treated_as_worker_actionable():
    """§2: there is no ``APPROVED`` state, and nothing collapses into one."""
    assert not hasattr(TaskState, "APPROVED")
    assert "approved" not in {s.value for s in WORKER_ACTIONABLE_STATES}
    # REVIEW_COMPLETE is Sol's decision, never a state a worker run lands in.
    assert TaskState.REVIEW_COMPLETE not in WORKER_ACTIONABLE_STATES
    assert TaskState.FABLE_REVIEWED not in WORKER_ACTIONABLE_STATES
    # Intermediate states must never end a blocking call.
    assert TaskState.RUNNING not in WORKER_ACTIONABLE_STATES
    assert TaskState.IMPLEMENTED not in WORKER_ACTIONABLE_STATES
    assert TaskState.CREATED not in WORKER_ACTIONABLE_STATES
    assert TaskState.ROUTED not in WORKER_ACTIONABLE_STATES
    assert TaskState.RESUME_REQUESTED not in WORKER_ACTIONABLE_STATES


def test_blocking_envelope_states_the_contract_in_literal_values():
    envelope = blocking_envelope(TaskState.AWAITING_SOL_REVIEW)
    assert envelope == {
        "waited_server_side": True,
        "polling_required": False,
        "worker_actionable": True,
        "sol_must_decide_next_action": True,
    }
    # An intermediate state is reported honestly rather than claimed actionable.
    assert blocking_envelope(TaskState.RUNNING)["worker_actionable"] is False
    for state in WORKER_ACTIONABLE_STATES:
        assert blocking_envelope(state)["worker_actionable"] is True
        assert blocking_envelope(state)["polling_required"] is False


# ---------------------------------------------------------------------------
# §8 — the token / autonomy contract, word for word
# ---------------------------------------------------------------------------


def test_server_instructions_forbid_polling_get_task_in_so_many_words():
    text = SERVER_INSTRUCTIONS
    folded = " ".join(text.split())
    assert "Do NOT poll get_task after dispatch_claude_task or resume_claude_task." in folded
    assert "get_task is recovery and status tooling only." in folded
    assert "never as a wait loop" in folded


def test_server_instructions_state_that_dispatch_and_resume_block():
    text = SERVER_INSTRUCTIONS
    # The instructions are hard-wrapped, so sentences that span a line break are
    # matched against the same text with newlines folded to spaces. The words
    # asserted are still literal: deleting the sentence fails this test.
    folded = " ".join(text.split())
    assert (
        "dispatch_claude_task and resume_claude_task block: the tool call stays "
        "pending server-side for the whole Claude run" in folded
    )
    assert "review_task_with_fable blocks until Fable's review is complete." in folded
    assert "One call is one worker run" in folded


def test_server_instructions_name_every_state_that_ends_the_wait():
    for state in WORKER_ACTIONABLE_STATES:
        assert state.value in SERVER_INSTRUCTIONS, state.value


def test_server_instructions_preserve_the_pre_existing_orchestration_law():
    """§8: the new wording is additive. None of this may be lost."""
    assert SERVER_INSTRUCTIONS.startswith(
        "Sol is the sole orchestrator and final reviewer.\n"
        "Use dispatch_claude_task for new implementation work.\n"
        "Use resume_claude_task only to continue an existing implementation.\n"
        "Use review_task_with_fable only for independent review.\n"
        "Worker completion is evidence, never approval.\n"
        "Workers must never delegate recursively.\n"
    )
    folded = " ".join(SERVER_INSTRUCTIONS.split())
    assert "it never marks work approved" in folded
    assert (
        "Implementation completion, review completion, and user approval are "
        "three distinct states and must not be collapsed." in folded
    )
    assert "Fable's verdict is advisory" in folded


def test_dispatch_description_communicates_blocking_semantics():
    text = " ".join(TOOL_DESCRIPTIONS["dispatch_claude_task"].split())
    assert "BLOCKS until the worker reaches a state requiring a decision from Sol" in text
    assert "awaiting_sol_review, timed_out, blocked, failed or policy_violation" in text
    assert "Do not poll get_task afterwards" in text
    assert "Completion is evidence, never approval." in text


def test_resume_description_communicates_blocking_semantics():
    text = " ".join(TOOL_DESCRIPTIONS["resume_claude_task"].split())
    assert "BLOCKS until the resumed worker reaches a state requiring a decision from Sol" in text
    assert "Do not poll get_task afterwards" in text


def test_fable_description_communicates_blocking_semantics():
    text = " ".join(TOOL_DESCRIPTIONS["review_task_with_fable"].split())
    assert "BLOCKS until the review is complete" in text
    assert "advisory" in text
    assert "Do not poll get_task afterwards" in text


def test_get_task_description_says_it_is_recovery_only_and_not_a_wait_loop():
    text = " ".join(TOOL_DESCRIPTIONS["get_task"].split())
    assert "Read-only recovery and status tooling." in text
    assert "not needed on the normal path" in text
    assert "Never call it in a loop to wait for a worker" in text


# ---------------------------------------------------------------------------
# the registry primitive (§5) — unit level, no subprocesses
# ---------------------------------------------------------------------------


async def test_registry_shields_the_run_from_a_cancelled_waiter():
    registry = RunRegistry()
    started = 0
    release = asyncio.Event()

    async def body() -> dict:
        nonlocal started
        started += 1
        await release.wait()
        return {"ok": True}

    waiter = asyncio.create_task(registry.run("k", body))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    # The run is still owned by the registry, still running.
    assert registry.keys() == ("k",)
    release.set()
    await registry.drain(timeout=5)
    assert started == 1
    assert registry.keys() == ()


async def test_registry_attaches_a_duplicate_waiter_instead_of_starting_a_second_run():
    registry = RunRegistry()
    started = 0
    release = asyncio.Event()

    async def body() -> dict:
        nonlocal started
        started += 1
        await release.wait()
        return {"ok": True}

    first = asyncio.create_task(registry.run("same", body))
    await asyncio.sleep(0)
    second = asyncio.create_task(registry.run("same", body))
    await asyncio.sleep(0)
    release.set()
    a, b = await asyncio.gather(first, second)

    assert started == 1
    assert a is b


async def test_registry_starts_a_fresh_run_once_the_previous_one_finished():
    registry = RunRegistry()
    started = 0

    async def body() -> dict:
        nonlocal started
        started += 1
        return {"n": started}

    first = await registry.run("same", body)
    second = await registry.run("same", body)

    assert (first, second) == ({"n": 1}, {"n": 2})
    assert started == 2
    assert registry.keys() == ()
