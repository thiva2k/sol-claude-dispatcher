"""Gate 7 resume boundary tests against the fake worker only."""

from __future__ import annotations

import json
from pathlib import Path

import sol_claude_dispatcher.server as server_module
from sol_claude_dispatcher.errors import ClaudeBinaryNotFound
from sol_claude_dispatcher.models import TaskState


async def test_resume_does_not_publish_running_or_charge_resume_before_spawn(
    dispatcher,
    request_payload,
    fake_env,
    monkeypatch,
) -> None:
    first = await dispatcher.dispatch_claude_task(request_payload)
    assert first["status"] == TaskState.AWAITING_SOL_REVIEW.value, first
    before = dispatcher.store.load(first["task_id"])
    before_history_length = len(before.state_history)

    async def fail_before_spawn(invocation):
        # ``run_worker`` has received the invocation but has not called its
        # on_spawn hook. The durable state may record the reservation, but it
        # must not claim RUNNING or consume a resume attempt until a real child
        # exists.
        current = dispatcher.store.load(first["task_id"])
        assert current.state is TaskState.RESUME_REQUESTED
        assert current.resume_count == before.resume_count
        assert current.run_count == before.run_count
        admin_start = (
            Path(dispatcher.store.run_dir(first["task_id"], before.run_count + 1))
            / "git-admin-worker-start.json"
        )
        persisted = json.loads(admin_start.read_text())
        assert persisted["registration_exact_entries"]
        raise ClaudeBinaryNotFound("Synthetic pre-spawn refusal.")

    monkeypatch.setattr(server_module, "run_worker", fail_before_spawn)

    refused = await dispatcher.resume_claude_task(
        first["task_id"], "Continue without changing the approved scope."
    )

    assert refused["error"] == "ClaudeBinaryNotFound"
    after = dispatcher.store.load(first["task_id"])
    assert after.state is TaskState.RESUME_REQUESTED
    assert after.resume_count == before.resume_count
    assert after.run_count == before.run_count
    new_transitions = after.state_history[before_history_length:]
    assert [item["to"] for item in new_transitions] == ["resume_requested"]
