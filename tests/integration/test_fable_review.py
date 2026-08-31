"""Independent Fable review against the fake worker (§7.3, §19, §25, §41).

Two things matter here and are asserted from the fake binary's own invocation
log rather than from the dispatcher's return value: Fable is read-only, and
Fable never touches the implementation worker's conversation.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import sol_claude_dispatcher.server as server_module
from sol_claude_dispatcher.models import TaskState
from sol_claude_dispatcher.runner import (
    ALWAYS_DISALLOWED_TOOLS,
    MUTATING_TOOL_NAMES,
    WorkerInvocation,
)


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
    """§5.11: the prompt has exactly six complete, labelled sections."""
    request_payload["validation"] = {"commands": [{"argv": ["/bin/true"]}]}
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)

    await dispatcher.review_task_with_fable(dispatched["task_id"], ["correctness"])

    prompt = worker_invocations()[-1]["prompt"]
    envelope = dispatcher.store.load_envelope(dispatched["task_id"])
    assert envelope.task.objective in prompt
    assert envelope.task.acceptance_criteria[0] in prompt
    assert envelope.repository.base_commit in prompt
    assert "src/deploy/deploy.py" in prompt
    assert "Worker report (claims, not evidence):" in prompt
    assert dispatched["worker_claims"]["summary"] in prompt
    assert prompt.count("## SECTION ") == 6
    for number, title in (
        (1, "TASK"),
        (2, "ENTIRE FROZEN WORKER PATCH"),
        (3, "COMPLETE WORKER CHANGE INVENTORY"),
        (4, "DISPATCHER VALIDATION"),
        (5, "VALIDATION FILESYSTEM EFFECTS"),
        (6, "COMPLETENESS"),
    ):
        assert f"## SECTION {number} — {title}" in prompt
    assert '"change": "modified"' in prompt
    assert '"mode": "100644"' in prompt
    assert '"size":' in prompt
    assert '"sha256":' in prompt
    assert "Executed by the dispatcher after the worker exited. NOT Claude's work." in prompt
    assert "validation_only:\nnone" in prompt
    assert "both_authors:\nnone" in prompt
    assert "validation_reverted:\nnone" in prompt
    assert "Every changed path is represented above." in prompt
    assert "- correctness" in prompt


async def test_review_ignores_same_size_schema_valid_run_journal_forgery(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """Claims and validation come from the frozen prompt artefact, not the journal."""
    request_payload["validation"] = {
        "commands": [{"argv": ["/bin/echo", "ORIGINAL"]}]
    }
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    run_result = dispatcher.store.run_dir(task_id, 1) / "dispatcher-result.json"
    original_bytes = run_result.read_bytes()
    original_value = json.loads(original_bytes)
    original_summary = original_value["worker_claims"]["summary"]
    forged_summary = "X" * len(original_summary)
    assert forged_summary != original_summary
    assert original_value["validation_results"][0]["stdout_tail"] == "ORIGINAL"

    forged_bytes = original_bytes.replace(
        json.dumps(original_summary).encode(),
        json.dumps(forged_summary).encode(),
        1,
    ).replace(
        b'"stdout_tail": "ORIGINAL"',
        b'"stdout_tail": "FORGERY!"',
        1,
    )
    assert len(forged_bytes) == len(original_bytes)
    assert forged_bytes != original_bytes
    # The forged record remains schema-valid, which arms the control against
    # a parser-only defence.
    run_result.write_bytes(forged_bytes)
    forged_run = dispatcher.store.load_runs(task_id)[0]
    assert forged_run.worker_claims is not None
    assert forged_run.worker_claims.summary == forged_summary
    assert forged_run.validation_results[0].stdout_tail == "FORGERY!"

    reviewed = await dispatcher.review_task_with_fable(task_id, ["correctness"])

    assert "error" not in reviewed, reviewed
    prompt = worker_invocations()[-1]["prompt"]
    assert original_summary in prompt
    assert forged_summary not in prompt
    assert '"stdout_tail": "ORIGINAL"' in prompt
    assert '"stdout_tail": "FORGERY!"' not in prompt


async def test_review_refuses_tampered_frozen_claims_before_spawn(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """The minimal claims+validation artefact is itself load-bearing."""
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    frozen_input = dispatcher.store.run_dir(task_id, 1) / "fable-run-evidence.json"
    before = frozen_input.read_bytes()
    marker = dispatched["worker_claims"]["summary"]
    replacement = "X" * len(marker)
    tampered = before.replace(
        json.dumps(marker).encode(), json.dumps(replacement).encode(), 1
    )
    assert len(tampered) == len(before)
    assert tampered != before
    frozen_input.write_bytes(tampered)
    before_spawns = len(worker_invocations())
    state_path = dispatcher.store.task_dir(task_id) / "state.json"
    before_state = state_path.read_bytes()

    result = await dispatcher.review_task_with_fable(task_id)

    assert result["error"] == "EvidenceFreezeViolated", result
    assert len(worker_invocations()) == before_spawns
    assert state_path.read_bytes() == before_state
    refusal = json.loads(
        (dispatcher.store.task_dir(task_id) / "refusals.jsonl")
        .read_text()
        .splitlines()[-1]
    )
    assert refusal["tool"] == "review"
    assert refusal["phase"] == "PREPARE"
    assert refusal["code"] == "EvidenceFreezeViolated"


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


async def test_redundant_review_is_refused_before_every_review_side_effect(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """FABLE_REVIEWED cannot launch or append before failing its transition."""
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    first = await dispatcher.review_task_with_fable(task_id)
    assert first["status"] == TaskState.FABLE_REVIEWED.value

    task_dir = dispatcher.store.task_dir(task_id)
    state_path = task_dir / "state.json"
    refusal_path = task_dir / "refusals.jsonl"
    before_state = state_path.read_bytes()
    before_refusals = refusal_path.read_bytes() if refusal_path.exists() else b""
    before_spawns = len(worker_invocations())
    before_runs = dispatcher.store.load(task_id).run_count
    before_reviews = dispatcher.store.load(task_id).fable_review_count
    before_review_files = sorted((task_dir / "reviews").glob("fable-*.json"))
    review_input_path = task_dir / "evidence" / "fable-review-input.json"
    before_review_input = review_input_path.read_bytes()

    async def forbidden_impl(*args, **kwargs):
        raise AssertionError("illegal review reached repository-lock implementation")

    monkeypatch.setattr(dispatcher, "_review_impl", forbidden_impl)

    refused = await dispatcher.review_task_with_fable(task_id)

    assert refused["error"] == "InvalidStateTransition", refused
    assert refused["details"] == {
        "from": TaskState.FABLE_REVIEWED.value,
        "to": TaskState.FABLE_REVIEWED.value,
        "allowed": [
            TaskState.AWAITING_SOL_REVIEW.value,
            TaskState.RESUME_REQUESTED.value,
            TaskState.REVIEW_COMPLETE.value,
        ],
    }
    assert state_path.read_bytes() == before_state
    assert len(worker_invocations()) == before_spawns
    record = dispatcher.store.load(task_id)
    assert record.run_count == before_runs == 2
    assert record.fable_review_count == before_reviews == 1
    assert not dispatcher.store.run_dir(task_id, before_runs + 1).exists()
    assert sorted((task_dir / "reviews").glob("fable-*.json")) == before_review_files
    assert review_input_path.read_bytes() == before_review_input

    after_refusals = refusal_path.read_bytes()
    assert after_refusals.startswith(before_refusals)
    new_rows = after_refusals[len(before_refusals) :].splitlines()
    assert len(new_rows) == 1
    row = json.loads(new_rows[0])
    assert row["tool"] == "review"
    assert row["phase"] == "PREPARE"
    assert row["code"] == "InvalidStateTransition"


async def test_review_rechecks_transition_legality_after_lock_acquisition(
    dispatcher,
    request_payload,
    fake_env,
    monkeypatch,
    worker_invocations,
    integration_config,
):
    """A real concurrent winner between preflight and lock closes the launch."""
    from sol_claude_dispatcher.server import Dispatcher

    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    task_dir = dispatcher.store.task_dir(task_id)
    state_path = task_dir / "state.json"
    refusal_path = task_dir / "refusals.jsonl"
    before_refusals = refusal_path.read_bytes() if refusal_path.exists() else b""
    before_spawns = len(worker_invocations())

    # Pause a second Dispatcher instance after its public PREPARE state check
    # but before its implementation can acquire repository authority. The
    # first instance then completes a real review, including its run, review,
    # and state transition. The stale contender must re-read and refuse.
    contender = Dispatcher(integration_config)
    original_impl = contender._review_impl
    preflight_passed = asyncio.Event()
    winner_finished = asyncio.Event()

    async def delayed_impl(task_id_arg, focus, *, execution):
        preflight_passed.set()
        await winner_finished.wait()
        return await original_impl(task_id_arg, focus, execution=execution)

    monkeypatch.setattr(contender, "_review_impl", delayed_impl)
    contender_task = asyncio.create_task(contender.review_task_with_fable(task_id))
    await preflight_passed.wait()

    won = await dispatcher.review_task_with_fable(task_id)
    assert won["status"] == TaskState.FABLE_REVIEWED.value
    won_state = state_path.read_bytes()
    winner_finished.set()
    refused = await contender_task

    assert refused["error"] == "InvalidStateTransition", refused
    assert refused["details"]["from"] == TaskState.FABLE_REVIEWED.value
    # The winner's complete state is retained byte-for-byte; the stale review
    # itself adds only its refusal audit row.
    assert state_path.read_bytes() == won_state
    assert len(worker_invocations()) == before_spawns + 1
    record = dispatcher.store.load(task_id)
    assert record.run_count == 2
    assert record.fable_review_count == 1
    assert not dispatcher.store.run_dir(task_id, 3).exists()
    assert len(dispatcher.store.load_reviews(task_id)) == 1

    after_refusals = refusal_path.read_bytes()
    new_rows = after_refusals[len(before_refusals) :].splitlines()
    assert len(new_rows) == 1
    row = json.loads(new_rows[0])
    assert row["phase"] == "PREPARE"
    assert row["code"] == "InvalidStateTransition"


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


async def test_review_refuses_an_absent_sealed_identity_before_reviewer_spawn(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    seal = dispatcher.store.task_dir(task_id) / "evidence" / "preworker-seal"
    (seal / "identity-record.json").unlink()
    before = len(worker_invocations())

    result = await dispatcher.review_task_with_fable(task_id)

    assert result["error"] == "SealIntegrityFailed"
    assert result["details"]["relpath"] == "identity-record.json"
    assert len(worker_invocations()) == before


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


async def test_malformed_review_retry_uses_latest_implementer_evidence(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """A failed REVIEW run cannot replace the implementer evidence selector."""
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    patch = dispatcher.store.read_evidence(task_id, "diff.patch")
    assert patch
    claim_summary = dispatched["worker_claims"]["summary"]

    monkeypatch.setenv("FAKE_CLAUDE_STDOUT", "malformed reviewer output")
    first = await dispatcher.review_task_with_fable(task_id)
    assert first["error"] == "ClaudeStructuredOutputInvalid"
    assert dispatcher.store.load(task_id).run_count == 2

    monkeypatch.delenv("FAKE_CLAUDE_STDOUT")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    second = await dispatcher.review_task_with_fable(task_id)
    assert second["status"] == TaskState.FABLE_REVIEWED.value
    retry_prompt = worker_invocations()[-1]["prompt"]
    assert f"```diff\n{patch}\n```" in retry_prompt
    assert claim_summary in retry_prompt
    measurement = json.loads(
        (dispatcher.store.task_dir(task_id) / "evidence" / "fable-review-input.json").read_text()
    )
    assert measurement["implementer_run_index"] == 1
    assert measurement["proposed_review_run_index"] == 3


async def test_both_authors_sentence_is_paired_with_explicit_empty_rendering(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations, tmp_path
):
    validation = tmp_path / "rewrite_worker_path.py"
    validation.write_text(
        "from pathlib import Path\n"
        "Path('src/deploy/deploy.py').write_text('rewritten by validation\\n')\n"
    )
    request_payload["validation"] = {
        "commands": [{"argv": [sys.executable, str(validation)]}]
    }
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    await dispatcher.review_task_with_fable(dispatched["task_id"])
    prompt = worker_invocations()[-1]["prompt"]
    mandatory = (
        "1 path(s) shown above were modified by dispatcher validation after the "
        "worker exited. The patch above is the worktree as the worker left it, "
        "not as it is now: src/deploy/deploy.py."
    )
    assert mandatory in prompt
    assert "both_authors:\n- src/deploy/deploy.py" in prompt
    assert "validation_only:\nnone" in prompt
    assert "validation_reverted:\nnone" in prompt


async def test_review_prepare_refusal_is_journalled_without_state_or_spawn(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    run_dir = dispatcher.store.run_dir(task_id, 1)
    (run_dir / "review-evidence-freeze.json").unlink()
    state_path = dispatcher.store.task_dir(task_id) / "state.json"
    refusal_path = dispatcher.store.task_dir(task_id) / "refusals.jsonl"
    before_state = state_path.read_bytes()
    before_refusals = refusal_path.read_bytes() if refusal_path.exists() else b""
    before_spawns = len(worker_invocations())

    result = await dispatcher.review_task_with_fable(task_id)

    assert result["error"] == "EvidenceFreezeViolated"
    assert state_path.read_bytes() == before_state
    assert len(worker_invocations()) == before_spawns
    after_refusals = refusal_path.read_bytes()
    assert after_refusals.startswith(before_refusals)
    new_rows = after_refusals[len(before_refusals) :].splitlines()
    assert len(new_rows) == 1
    row = json.loads(new_rows[0])
    assert row["tool"] == "review"
    assert row["phase"] == "PREPARE"
    assert row["code"] == "EvidenceFreezeViolated"


def test_measured_review_budget_has_real_byte_boundaries(tmp_path: Path):
    """Exact headroom succeeds; +1 and sub-120k real overflow both refuse."""
    prefix = "P" * 50_000
    suffix = "S"

    def invocation(patch: bytes) -> WorkerInvocation:
        return WorkerInvocation(
            binary="/bin/true",
            model="fable",
            session_id="00000000-0000-4000-8000-000000000000",
            cwd=tmp_path,
            prompt=prefix + patch.decode("ascii") + suffix,
            timeout_seconds=60,
            role="reviewer",
            env={"LANG": "C"},
            tools=["Read"],
            disallowed_tools=list(ALWAYS_DISALLOWED_TOOLS),
        )

    probe = server_module._argv_transport_measurement(
        invocation(b""), prefix=prefix, suffix=suffix, patch_data=b""
    )
    budget = probe["review_patch_budget_bytes"]
    assert budget < 120_000

    exact = server_module._argv_transport_measurement(
        invocation(b"x" * budget),
        prefix=prefix,
        suffix=suffix,
        patch_data=b"x" * budget,
    )
    assert exact["review_input_complete"] is True

    over = server_module._argv_transport_measurement(
        invocation(b"x" * (budget + 1)),
        prefix=prefix,
        suffix=suffix,
        patch_data=b"x" * (budget + 1),
    )
    assert over["review_input_complete"] is False
    assert over["patch_bytes"] < 120_000

    # The prompt is not privileged: every other argv element is measured too.
    # Persist only its position and byte count, never its potentially sensitive
    # content.
    private_oversized_model = "private-model-" + "m" * (
        server_module.MEASURED_SINGLE_ARGV_LIMIT_BYTES
    )
    other_argv_over = server_module._argv_transport_measurement(
        replace(invocation(b""), model=private_oversized_model),
        prefix=prefix,
        suffix=suffix,
        patch_data=b"",
    )
    assert other_argv_over["review_input_complete"] is False
    assert other_argv_over["base_transportable"] is False
    assert other_argv_over["oversized_element_count"] == 1
    assert other_argv_over["oversized_elements"][0]["kind"] == "argv"
    assert private_oversized_model not in json.dumps(other_argv_over)


async def test_measured_review_budget_refuses_before_spawn_or_run_consumption(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """The review path consumes the measured verdict, not just its helper test."""
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    state_path = dispatcher.store.task_dir(task_id) / "state.json"
    before_state = state_path.read_bytes()
    before_spawns = len(worker_invocations())
    real_sysconf = server_module.os.sysconf

    def constrained_sysconf(name):
        if name == "SC_ARG_MAX":
            return server_module._FABLE_ARGV_SAFETY_RESERVE_BYTES + 1
        return real_sysconf(name)

    monkeypatch.setattr(server_module.os, "sysconf", constrained_sysconf)
    result = await dispatcher.review_task_with_fable(task_id)

    assert result["error"] == "EvidenceExceedsReviewBudget", result
    assert len(worker_invocations()) == before_spawns
    assert state_path.read_bytes() == before_state
    assert dispatcher.store.load(task_id).run_count == 1
    assert not dispatcher.store.run_dir(task_id, 2).exists()
    measurement = json.loads(
        (dispatcher.store.task_dir(task_id) / "evidence" / "fable-review-input.json").read_text()
    )
    assert measurement["review_input_complete"] is False
    assert measurement["base_transportable"] is False


async def test_review_preflight_measures_every_envp_element_before_spawn(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """An oversized envp element refuses; its exact legal boundary executes."""
    dispatched = await _dispatched(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    task_dir = dispatcher.store.task_dir(task_id)
    state_path = task_dir / "state.json"
    before_state = state_path.read_bytes()
    before_spawns = len(worker_invocations())
    key = "FABLE_TRANSPORT_BOUNDARY"
    secret_marker = "do-not-persist-this-value"
    oversized_value = secret_marker + "x" * (
        server_module.MEASURED_SINGLE_ARGV_LIMIT_BYTES
    )
    monkeypatch.setenv(key, oversized_value)

    refused = await dispatcher.review_task_with_fable(task_id)

    assert refused["error"] == "EvidenceExceedsReviewBudget", refused
    assert refused["details"]["binding_constraint"] == "envp_element"
    assert refused["details"]["oversized_element_count"] == 1
    assert len(worker_invocations()) == before_spawns
    assert state_path.read_bytes() == before_state
    assert dispatcher.store.load(task_id).run_count == 1
    assert not dispatcher.store.run_dir(task_id, 2).exists()
    measurement_path = task_dir / "evidence" / "fable-review-input.json"
    refused_measurement_text = measurement_path.read_text()
    refused_measurement = json.loads(refused_measurement_text)
    assert refused_measurement["review_input_complete"] is False
    assert refused_measurement["base_transportable"] is False
    assert refused_measurement["oversized_element_count"] == 1
    assert refused_measurement["oversized_elements"][0] == {
        "kind": "envp",
        "index": refused_measurement["oversized_elements"][0]["index"],
        "encoded_bytes": len(key) + 1 + len(oversized_value),
        "maximum_bytes": server_module.MEASURED_SINGLE_ARGV_LIMIT_BYTES,
    }
    assert key not in refused_measurement_text
    assert secret_marker not in refused_measurement_text
    assert key not in json.dumps(refused)
    assert secret_marker not in json.dumps(refused)

    # Opposite live control: KEY=value is exactly the measured per-element
    # ceiling.  It must reach the fake reviewer, proving the check is > rather
    # than >= and is not an unconditional rejection of a large environment.
    legal_value = "y" * (
        server_module.MEASURED_SINGLE_ARGV_LIMIT_BYTES - len(key) - 1
    )
    monkeypatch.setenv(key, legal_value)
    accepted = await dispatcher.review_task_with_fable(task_id)

    assert "error" not in accepted, accepted
    assert len(worker_invocations()) == before_spawns + 1
    accepted_measurement = json.loads(measurement_path.read_text())
    assert accepted_measurement["review_input_complete"] is True
    assert accepted_measurement["base_transportable"] is True
    assert accepted_measurement["oversized_element_count"] == 0
    assert accepted_measurement["oversized_elements"] == []
    assert (
        accepted_measurement["largest_envp_element_bytes"]
        == server_module.MEASURED_SINGLE_ARGV_LIMIT_BYTES
    )


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
