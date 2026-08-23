"""An over-budget envelope is refused BEFORE a worker starts (GATE 6, Lane L).

Closes Lane K's FINDING K-1. The measurements that motivate it are recorded in
``tests/unit/test_validation_budget.py``; this file proves the behaviour end to
end, against the fake worker, on all three tool paths that start a Claude
process — dispatch, resume and the Fable review, which share one MCP transport
and therefore one tool timeout.

The property under test is *refusal*, and the negative half matters as much as
the positive one: no worker is launched, no task state is created or mutated,
no validation command is dropped, and no declared timeout is truncated to make
the envelope fit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sol_claude_dispatcher.config import load_config
from sol_claude_dispatcher.models import TaskState
from sol_claude_dispatcher.server import Dispatcher

#: A budget small enough that the fixture config's 120 s worker ceiling is a
#: meaningful share of it. The real shipped budget (7,115 s) is pinned in the
#: unit tests; here the boundary needs to be reachable without declaring
#: hour-long validation commands.
TIGHT_BUDGET = 200


def _budgeted_config_file(base: Path, tmp_path: Path, budget: int, name: str) -> Path:
    text = base.read_text()
    patched = text.replace(
        "run_dispatcher_validation = true",
        f"run_dispatcher_validation = true\nmax_total_seconds = {budget}",
    )
    assert patched != text, "the fixture config no longer has a [validation] section"
    path = tmp_path / name
    path.write_text(patched)
    return path


@pytest.fixture
def budget_config_file(integration_config_file: Path, tmp_path: Path) -> Path:
    return _budgeted_config_file(
        integration_config_file, tmp_path, TIGHT_BUDGET, "dispatcher-budget.toml"
    )


@pytest.fixture
def budget_dispatcher(budget_config_file: Path) -> Dispatcher:
    return Dispatcher(load_config(budget_config_file))


def _with_validation(payload: dict, execution: int, *timeouts: int) -> dict:
    request = dict(payload)
    request["execution"] = dict(payload["execution"], timeout_seconds=execution)
    request["validation"] = {
        "commands": [
            {"argv": ["/bin/true", f"marker-{i}"], "timeout_seconds": t}
            for i, t in enumerate(timeouts)
        ]
    }
    return request


def _tasks_on_disk(dispatcher: Dispatcher) -> list[Path]:
    tasks = dispatcher.config.tasks_path
    return sorted(tasks.iterdir()) if tasks.exists() else []


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


async def test_an_at_budget_dispatch_is_accepted_and_runs_every_command(
    budget_dispatcher: Dispatcher, request_payload: dict, fake_env, worker_invocations
):
    request = _with_validation(request_payload, 120, 40, 40)  # 120 + 80 == 200
    result = await budget_dispatcher.dispatch_claude_task(request)

    assert "error" not in result, result
    assert len(worker_invocations()) == 1
    assert len(result["validation_results"]) == 2


async def test_one_second_over_budget_is_refused_before_any_worker_starts(
    budget_dispatcher: Dispatcher, request_payload: dict, fake_env, worker_invocations
):
    request = _with_validation(request_payload, 120, 40, 41)  # 120 + 81 == 201
    result = await budget_dispatcher.dispatch_claude_task(request)

    assert result["error"] == "ValidationBudgetExceeded"
    assert result["details"]["excess_seconds"] == 1
    assert result["details"]["budget_seconds"] == TIGHT_BUDGET
    assert worker_invocations() == [], "a worker was launched for a refused envelope"


async def test_a_refused_dispatch_creates_no_task_state(
    budget_dispatcher: Dispatcher, request_payload: dict, fake_env
):
    request = _with_validation(request_payload, 120, 3_600, 3_600)
    result = await budget_dispatcher.dispatch_claude_task(request)

    assert result["error"] == "ValidationBudgetExceeded"
    assert _tasks_on_disk(budget_dispatcher) == []


async def test_the_refusal_names_the_commands_without_their_arguments(
    budget_dispatcher: Dispatcher, request_payload: dict, fake_env
):
    request = _with_validation(request_payload, 120, 3_600)
    request["validation"]["commands"][0]["argv"] = ["/usr/bin/env", "SECRET=hunter2"]
    result = await budget_dispatcher.dispatch_claude_task(request)

    contributing = result["details"]["contributing_commands"]
    assert [c["program"] for c in contributing] == ["env"]
    assert "hunter2" not in str(result)
    assert request_payload["task"]["objective"] not in str(result)


async def test_a_refusal_does_not_shrink_the_envelope_and_retrying_is_identical(
    budget_dispatcher: Dispatcher, request_payload: dict, fake_env, worker_invocations
):
    """No truncation, no dropping: the second attempt refuses exactly as hard."""
    request = _with_validation(request_payload, 120, 3_600, 3_600, 3_600)
    first = await budget_dispatcher.dispatch_claude_task(request)
    second = await budget_dispatcher.dispatch_claude_task(request)

    assert first["details"] == second["details"]
    assert first["details"]["validation_command_count"] == 3
    assert first["details"]["validation_total_seconds"] == 10_800
    assert len(request["validation"]["commands"]) == 3
    assert [c["timeout_seconds"] for c in request["validation"]["commands"]] == [
        3_600,
        3_600,
        3_600,
    ]
    assert worker_invocations() == []


# ---------------------------------------------------------------------------
# resume — the bypass vector, because resume may raise the execution timeout
# ---------------------------------------------------------------------------


async def test_a_resume_cannot_bypass_the_budget(
    budget_dispatcher: Dispatcher, request_payload: dict, fake_env, worker_invocations
):
    """Dispatch fits at 60 s of execution; a 120 s resume no longer does."""
    request = _with_validation(request_payload, 60, 140)  # 60 + 140 == 200
    dispatched = await budget_dispatcher.dispatch_claude_task(request)
    assert "error" not in dispatched, dispatched
    task_id = dispatched["task_id"]
    assert len(worker_invocations()) == 1

    result = await budget_dispatcher.resume_claude_task(
        task_id, "Keep going.", timeout_seconds=120
    )

    assert result["error"] == "ValidationBudgetExceeded"
    assert result["details"]["phase"] == "resume"
    assert result["details"]["execution_timeout_seconds"] == 120
    assert result["details"]["declared_total_seconds"] == 260
    assert len(worker_invocations()) == 1, "the refused resume launched a worker"


async def test_a_refused_resume_leaves_the_task_state_untouched(
    budget_dispatcher: Dispatcher, request_payload: dict, fake_env
):
    request = _with_validation(request_payload, 60, 140)
    dispatched = await budget_dispatcher.dispatch_claude_task(request)
    task_id = dispatched["task_id"]
    before = await budget_dispatcher.get_task(task_id)

    refused = await budget_dispatcher.resume_claude_task(
        task_id, "Keep going.", timeout_seconds=120
    )
    assert refused["error"] == "ValidationBudgetExceeded"

    after = await budget_dispatcher.get_task(task_id)
    assert after["state"] == before["state"] == TaskState.AWAITING_SOL_REVIEW.value
    assert after["resume_count"] == before["resume_count"] == 0
    assert after["run_count"] == before["run_count"] == 1


async def test_a_resume_within_the_budget_still_works(
    budget_dispatcher: Dispatcher, request_payload: dict, fake_env, worker_invocations
):
    request = _with_validation(request_payload, 60, 140)
    dispatched = await budget_dispatcher.dispatch_claude_task(request)
    result = await budget_dispatcher.resume_claude_task(
        dispatched["task_id"], "Keep going.", timeout_seconds=60
    )
    assert "error" not in result, result
    assert len(worker_invocations()) == 2


# ---------------------------------------------------------------------------
# review — the third path over the same transport
# ---------------------------------------------------------------------------


async def test_the_fable_review_is_refused_when_the_envelope_exceeds_the_budget(
    integration_config_file: Path,
    tmp_path: Path,
    request_payload: dict,
    fake_env,
    worker_invocations,
):
    """Same state directory, a budget lowered underneath a stored envelope.

    A Fable review starts a Claude process on the same MCP transport, so an
    envelope the transport can no longer carry must be refused there too rather
    than reviewed on a call that will be cancelled part-way.
    """
    roomy = Dispatcher(
        load_config(_budgeted_config_file(integration_config_file, tmp_path, 800, "roomy.toml"))
    )
    request = _with_validation(request_payload, 120, 600)  # 720 <= 800
    dispatched = await roomy.dispatch_claude_task(request)
    assert "error" not in dispatched, dispatched
    task_id = dispatched["task_id"]
    launched = len(worker_invocations())

    tight = Dispatcher(
        load_config(_budgeted_config_file(integration_config_file, tmp_path, TIGHT_BUDGET, "tight.toml"))
    )
    result = await tight.review_task_with_fable(task_id)

    assert result["error"] == "ValidationBudgetExceeded"
    assert result["details"]["phase"] == "review"
    assert len(worker_invocations()) == launched, "the refused review ran a reviewer"


async def test_a_review_within_the_budget_still_works(
    budget_dispatcher: Dispatcher,
    request_payload: dict,
    fake_env,
    monkeypatch: pytest.MonkeyPatch,
):
    request = _with_validation(request_payload, 60, 140)
    dispatched = await budget_dispatcher.dispatch_claude_task(request)
    assert "error" not in dispatched, dispatched
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    result = await budget_dispatcher.review_task_with_fable(dispatched["task_id"])
    assert "error" not in result, result


# ---------------------------------------------------------------------------
# the shipped default, unmodified
# ---------------------------------------------------------------------------


async def test_the_default_budget_refuses_lane_ks_structural_worst_case(
    dispatcher: Dispatcher, request_payload: dict, fake_env, worker_invocations
):
    """32 x 3,600 s — the 115,520 s path that no tool timeout can cover."""
    request = _with_validation(request_payload, 120, *([3_600] * 32))
    result = await dispatcher.dispatch_claude_task(request)

    assert result["error"] == "ValidationBudgetExceeded"
    assert result["details"]["validation_total_seconds"] == 115_200
    assert result["details"]["budget_seconds"] == 7_115
    assert worker_invocations() == []


async def test_the_default_budget_accepts_an_ordinary_envelope(
    dispatcher: Dispatcher, request_payload: dict, fake_env
):
    request = _with_validation(request_payload, 60, 600, 600)
    result = await dispatcher.dispatch_claude_task(request)
    assert "error" not in result, result


def test_the_refusal_happens_before_the_repository_lock_is_taken():
    """Ordering, read from the source: refusing must not depend on acquiring."""
    import inspect

    from sol_claude_dispatcher import server

    source = inspect.getsource(server.Dispatcher._dispatch)
    budget = source.index("assert_validation_budget")
    lock = source.index("lock.acquire()")
    assert budget < lock

    resume_source = inspect.getsource(server.Dispatcher._resume)
    assert resume_source.index("assert_validation_budget") < resume_source.index(
        "lock.acquire()"
    )
    review_source = inspect.getsource(server.Dispatcher._review)
    assert review_source.index("assert_validation_budget") < review_source.index(
        "lock.acquire()"
    )


def test_no_source_file_clamps_the_declared_totals(project_root: Path):
    """A mutation that clamps instead of refusing must not slip in unnoticed."""
    text = (project_root / "src" / "sol_claude_dispatcher" / "validation.py").read_text()
    body = text[text.index("def assert_validation_budget") :]
    for forbidden in ("min(", "commands[:", "del ", ".pop(", "truncat"):
        assert forbidden not in body, f"{forbidden!r} in the budget assertion"
    assert re.search(r"raise ValidationBudgetExceeded", body)
