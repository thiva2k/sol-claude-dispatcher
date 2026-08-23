"""GATE 6 §2–§7 — the MCP call blocks server-side, and the worker outlives it.

Every test here runs against the fake worker. Nothing spawns a real ``claude``.

Two facts are proved separately and must never be conflated (§7):

A. the **Claude execution timeout** is a real dispatcher state transition to
   ``TIMED_OUT``, persisted and returned to Sol;
B. the **MCP client/tool timeout** merely stops the waiter. The worker keeps
   running, its true final state is persisted, and ``get_task`` recovers it. An
   MCP timeout must never fabricate ``FAILED`` or ``TIMED_OUT``.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from sol_claude_dispatcher.config import load_config
from sol_claude_dispatcher.models import TaskState
from sol_claude_dispatcher.server import Dispatcher, build_dispatcher

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_SHIM = PROJECT_ROOT / "tests" / "fixtures" / "claude_worktree_shim.py"

#: A worker binary that takes a controllable amount of wall-clock time before
#: doing anything, then hands over to the project's own worktree shim (which in
#: turn ``exec``s ``tests/fake_bin/claude``). It exists so a test can observe a
#: dispatch that is genuinely still in flight — and cancel its waiter — without
#: ever going near a real agent, the network, or a real repository.
SLOW_SHIM_SOURCE = '''#!/usr/bin/env python3
"""Test-only slow front end for tests/fixtures/claude_worktree_shim.py."""
import os
import sys
import time

time.sleep(float(os.environ.get("SLOW_CLAUDE_DELAY", "1.0")))
os.execv(sys.executable, [sys.executable, {shim!r}, *sys.argv[1:]])
'''


@pytest.fixture
def slow_claude_config_file(tmp_path: Path, integration_config_file: Path) -> Path:
    """``integration_config_file`` with ``claude.binary`` pointed at the slow shim."""
    shim = tmp_path / "slow-claude-shim.py"
    shim.write_text(SLOW_SHIM_SOURCE.format(shim=str(REAL_SHIM)))
    shim.chmod(0o755)

    original = integration_config_file.read_text()
    patched = re.sub(r'binary = "[^"]+"', f'binary = "{shim}"', original)
    assert patched != original, "the config no longer declares claude.binary"

    path = tmp_path / "dispatcher-slow.toml"
    path.write_text(patched)
    return path


@pytest.fixture
def slow_dispatcher(slow_claude_config_file: Path) -> Dispatcher:
    return Dispatcher(load_config(slow_claude_config_file))


@pytest.fixture
def slow_env(fake_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "1.0")
    return fake_env


async def _drain(dispatcher: Dispatcher) -> None:
    await dispatcher.drain(timeout=120)


# ---------------------------------------------------------------------------
# §2 — dispatch keeps the MCP request pending while Claude runs
# ---------------------------------------------------------------------------


async def test_dispatch_stays_pending_while_the_worker_is_still_running(
    slow_dispatcher, request_payload, slow_env
):
    call = asyncio.create_task(slow_dispatcher.dispatch_claude_task(request_payload))
    await asyncio.sleep(0.35)

    # The MCP request has NOT returned: the dispatcher is waiting server-side.
    assert call.done() is False
    assert len(slow_dispatcher.inflight_runs()) == 1

    result = await asyncio.wait_for(call, timeout=120)

    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert result["blocking"]["waited_server_side"] is True
    assert result["blocking"]["polling_required"] is False
    assert result["blocking"]["worker_actionable"] is True
    # Nothing is left running once the call returns.
    assert slow_dispatcher.inflight_runs() == ()


async def test_the_normal_path_needs_no_get_task_call_at_all(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """§8: one dispatch, zero polls. The result already carries everything."""
    calls: list[str] = []
    real_get_task = Dispatcher.get_task

    async def counting_get_task(self, task_id: str):
        calls.append(task_id)
        return await real_get_task(self, task_id)

    monkeypatch.setattr(Dispatcher, "get_task", counting_get_task)

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert calls == []
    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value
    # Everything Sol needs to decide is in the single response.
    for key in (
        "task_id",
        "session_id",
        "worktree",
        "selected_model",
        "worker_claims",
        "dispatcher_observations",
        "validation_results",
        "claim_verification",
        "scope",
        "last_error",
        "blocking",
    ):
        assert key in result, key
    assert result["worker_claims"]["status"] == "completed"


@pytest.mark.parametrize(
    "mode,expected,extra",
    [
        ("success", TaskState.AWAITING_SOL_REVIEW, {}),
        ("blocked", TaskState.BLOCKED, {}),
        ("failure", TaskState.FAILED, {}),
        ("scope-violation", TaskState.POLICY_VIOLATION, {}),
        ("timeout", TaskState.TIMED_OUT, {"execution": {"timeout_seconds": 1}}),
    ],
)
async def test_dispatch_returns_as_soon_as_a_worker_actionable_state_is_reached(
    dispatcher, request_payload, fake_env, monkeypatch, mode, expected, extra
):
    """§2: each of the five states ends the wait. None is waited through."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "30")
    for section, values in extra.items():
        request_payload[section].update(values)

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == expected.value
    assert result["blocking"]["worker_actionable"] is True
    assert result["blocking"]["polling_required"] is False
    assert result["blocking"]["sol_must_decide_next_action"] is True
    # The returned state is the persisted state; the dispatcher decided nothing
    # further and left nothing running.
    assert dispatcher.store.load(result["task_id"]).state is expected
    assert dispatcher.inflight_runs() == ()


# ---------------------------------------------------------------------------
# §3 — resume blocks identically
# ---------------------------------------------------------------------------


async def test_resume_blocks_until_the_resumed_run_is_actionable(
    slow_dispatcher, request_payload, slow_env, monkeypatch, worker_invocations
):
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "0.2")
    first = await slow_dispatcher.dispatch_claude_task(request_payload)
    assert first["status"] == TaskState.AWAITING_SOL_REVIEW.value

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "1.0")

    call = asyncio.create_task(
        slow_dispatcher.resume_claude_task(first["task_id"], "Fix finding R1 only.")
    )
    await asyncio.sleep(0.35)
    assert call.done() is False
    assert len(slow_dispatcher.inflight_runs()) == 1

    result = await asyncio.wait_for(call, timeout=120)

    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert result["blocking"]["waited_server_side"] is True
    assert result["blocking"]["polling_required"] is False
    assert result["resume_count"] == 1
    assert worker_invocations()[-1]["has_resume"] is True


# ---------------------------------------------------------------------------
# §4 — Fable blocks until the advisory review is complete
# ---------------------------------------------------------------------------


async def test_fable_review_blocks_until_the_review_is_complete(
    slow_dispatcher, request_payload, slow_env, monkeypatch
):
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "0.2")
    first = await slow_dispatcher.dispatch_claude_task(request_payload)
    assert first["status"] == TaskState.AWAITING_SOL_REVIEW.value

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "1.0")

    call = asyncio.create_task(slow_dispatcher.review_task_with_fable(first["task_id"]))
    await asyncio.sleep(0.35)
    assert call.done() is False
    assert len(slow_dispatcher.inflight_runs()) == 1

    result = await asyncio.wait_for(call, timeout=120)

    assert result["review"]["verdict"] == "changes_required"
    assert result["advisory"] is True
    assert result["status"] == TaskState.FABLE_REVIEWED.value
    assert result["blocking"]["waited_server_side"] is True
    assert result["blocking"]["polling_required"] is False
    # Fable is never approval, so its state is deliberately NOT worker-actionable.
    assert result["blocking"]["worker_actionable"] is False


# ---------------------------------------------------------------------------
# §5 — the worker's lifetime is NOT coupled to the MCP waiter
# ---------------------------------------------------------------------------


async def test_cancelling_the_mcp_waiter_does_not_cancel_the_worker(
    slow_dispatcher, request_payload, slow_env, monkeypatch, worker_invocations
):
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "1.0")

    call = asyncio.create_task(slow_dispatcher.dispatch_claude_task(request_payload))
    await asyncio.sleep(0.35)
    assert call.done() is False

    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call

    # The dispatcher still owns the run. The worker was not killed with it.
    assert len(slow_dispatcher.inflight_runs()) == 1

    await _drain(slow_dispatcher)

    assert len(worker_invocations()) == 1
    task_ids = slow_dispatcher.store.list_tasks()
    assert len(task_ids) == 1
    record = slow_dispatcher.store.load(task_ids[0])
    assert record.state is TaskState.AWAITING_SOL_REVIEW
    assert record.last_error is None


async def test_the_worker_result_persists_and_get_task_recovers_it_later(
    slow_dispatcher, slow_claude_config_file, request_payload, slow_env, monkeypatch
):
    """§5: a lost waiter loses nothing. A *different* dispatcher object recovers it."""
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "1.0")

    call = asyncio.create_task(slow_dispatcher.dispatch_claude_task(request_payload))
    await asyncio.sleep(0.35)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    await _drain(slow_dispatcher)

    task_id = slow_dispatcher.store.list_tasks()[0]
    reborn = build_dispatcher(slow_claude_config_file)  # as if the server restarted
    view = await reborn.get_task(task_id)

    assert view["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert view["session_id"]
    assert Path(view["worktree"]).is_dir()
    assert len(view["runs"]) == 1
    assert view["runs"][0]["dispatcher_observations"]["exit_code"] == 0
    assert view["latest_worker_result"]["status"] == "completed"
    assert view["last_error"] is None
    # Evidence written by the detached worker, after its waiter was gone.
    evidence = reborn.store.task_dir(task_id) / "evidence" / "changed-paths.json"
    assert evidence.is_file()


async def test_identity_is_persisted_before_the_wait_begins(
    slow_dispatcher, request_payload, slow_env, monkeypatch
):
    """§5: task/session/state exist on disk while the worker is still running."""
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "1.5")

    call = asyncio.create_task(slow_dispatcher.dispatch_claude_task(request_payload))
    await asyncio.sleep(0.5)

    task_ids = slow_dispatcher.store.list_tasks()
    assert len(task_ids) == 1
    mid_flight = slow_dispatcher.store.load(task_ids[0])
    assert mid_flight.state is TaskState.RUNNING
    assert mid_flight.session_id
    assert mid_flight.selected_model
    envelope = slow_dispatcher.store.load_envelope(task_ids[0])
    assert envelope.worktree_name.startswith("sol-")

    await asyncio.wait_for(call, timeout=120)


async def test_a_duplicate_resume_waiter_does_not_start_a_second_worker(
    slow_dispatcher, request_payload, slow_env, monkeypatch, worker_invocations
):
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "0.2")
    first = await slow_dispatcher.dispatch_claude_task(request_payload)
    task_id = first["task_id"]

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "1.0")
    instruction = "Fix finding R1 only. Do not change the public API."

    a = asyncio.create_task(slow_dispatcher.resume_claude_task(task_id, instruction))
    await asyncio.sleep(0.35)
    b = asyncio.create_task(slow_dispatcher.resume_claude_task(task_id, instruction))

    result_a, result_b = await asyncio.wait_for(asyncio.gather(a, b), timeout=120)

    assert result_a is result_b
    assert result_a["status"] == TaskState.AWAITING_SOL_REVIEW.value
    resumes = [call for call in worker_invocations() if call["has_resume"]]
    assert len(resumes) == 1
    record = slow_dispatcher.store.load(task_id)
    assert record.resume_count == 1
    assert record.run_count == 2


async def test_a_reconnected_dispatch_does_not_start_a_second_worker(
    slow_dispatcher, request_payload, slow_env, monkeypatch, worker_invocations
):
    """§5 + §25: the detached worker still holds the repository lock."""
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "1.0")

    call = asyncio.create_task(slow_dispatcher.dispatch_claude_task(request_payload))
    await asyncio.sleep(0.35)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call

    # Sol reconnects and retries while the original worker is still running.
    retry = await slow_dispatcher.dispatch_claude_task(dict(request_payload))
    assert retry["error"] == "RepositoryBusy"
    assert retry["retryable"] is True

    await _drain(slow_dispatcher)

    assert len(worker_invocations()) == 1
    assert len(slow_dispatcher.store.list_tasks()) == 1


async def test_one_worker_per_repository_still_holds_across_dispatcher_objects(
    slow_dispatcher, slow_claude_config_file, request_payload, slow_env, monkeypatch
):
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "1.0")
    other = Dispatcher(load_config(slow_claude_config_file))

    first, second = await asyncio.gather(
        slow_dispatcher.dispatch_claude_task(dict(request_payload)),
        other.dispatch_claude_task(dict(request_payload)),
    )

    busy = [r for r in (first, second) if r.get("error") == "RepositoryBusy"]
    assert len(busy) == 1, (first, second)
    assert len(slow_dispatcher.store.list_tasks()) == 1


# ---------------------------------------------------------------------------
# §7 — the two timeouts, proved in both directions
# ---------------------------------------------------------------------------


async def test_a_claude_execution_timeout_is_a_real_persisted_timed_out_state(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """§7A: the dispatcher's own timeout transitions the task and returns it."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "timeout")
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "30")
    request_payload["execution"]["timeout_seconds"] = 1

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.TIMED_OUT.value
    assert result["dispatcher_observations"]["timed_out"] is True
    assert result["last_error"]["error"] == "ClaudeTimedOut"
    assert result["blocking"]["worker_actionable"] is True

    view = await dispatcher.get_task(result["task_id"])
    assert view["status"] == TaskState.TIMED_OUT.value
    assert view["timeout"]["timed_out"] is True


async def test_an_mcp_timeout_never_fabricates_failed_or_timed_out_worker_state(
    slow_dispatcher, slow_claude_config_file, request_payload, slow_env, monkeypatch
):
    """§7B: the waiter gives up; the worker does not, and neither does the state."""
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "1.0")

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await asyncio.wait_for(
            slow_dispatcher.dispatch_claude_task(request_payload), timeout=0.35
        )

    # Mid-flight: still RUNNING, and emphatically not FAILED or TIMED_OUT.
    task_id = slow_dispatcher.store.list_tasks()[0]
    mid_flight = slow_dispatcher.store.load(task_id)
    assert mid_flight.state is TaskState.RUNNING
    assert mid_flight.last_error is None

    await _drain(slow_dispatcher)

    view = await build_dispatcher(slow_claude_config_file).get_task(task_id)
    assert view["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert view["status"] != TaskState.FAILED.value
    assert view["status"] != TaskState.TIMED_OUT.value
    assert view["timeout"]["timed_out"] is False
    assert view["last_error"] is None


async def test_an_mcp_timeout_during_a_resume_leaves_the_resume_recoverable(
    slow_dispatcher, request_payload, slow_env, monkeypatch, worker_invocations
):
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "0.2")
    first = await slow_dispatcher.dispatch_claude_task(request_payload)
    task_id = first["task_id"]

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    monkeypatch.setenv("SLOW_CLAUDE_DELAY", "1.0")

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await asyncio.wait_for(
            slow_dispatcher.resume_claude_task(task_id, "Fix finding R1 only."),
            timeout=0.35,
        )

    await _drain(slow_dispatcher)

    view = await slow_dispatcher.get_task(task_id)
    assert view["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert view["resume_count"] == 1
    assert view["last_error"] is None
    assert len([c for c in worker_invocations() if c["has_resume"]]) == 1
