"""Tests for :mod:`sol_claude_dispatcher.state` (brief §26, §27, §31).

Covers: atomic write behaviour (including a simulated crash that leaves a temp
file behind), directory/file permissions, every legal transition, a sample of
illegal ones, corruption failing closed, evidence writers, run/review append,
and reload after a fresh ``TaskStore`` instantiation (restart recovery).
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from sol_claude_dispatcher.errors import (
    InvalidStateTransition,
    InvalidTaskEnvelope,
    StateCorruption,
    TaskNotFound,
)
from sol_claude_dispatcher.models import (
    DispatcherObservations,
    FableCategory,
    FableFinding,
    FableReview,
    FableSeverity,
    FableVerdict,
    RecommendedNextAction,
    RunKind,
    RunMetadata,
    RunRecord,
    TaskEnvelope,
    TaskRequest,
    TaskState,
    WorkerRole,
    WorkerResult,
    WorkerStatus,
    new_run_id,
    new_session_id,
    utc_now,
)
from sol_claude_dispatcher.state import TaskStore, atomic_write_json, atomic_write_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(valid_request_dict: dict, **kw) -> TaskEnvelope:
    return TaskEnvelope.from_request(
        TaskRequest(**valid_request_dict),
        canonical_root="/tmp/canonical/repo",
        base_commit="a" * 40,
        **kw,
    )


def _run_record(task_id: str, run_index: int, *, worker_claims=True) -> RunRecord:
    now = utc_now()
    metadata = RunMetadata(
        run_id=new_run_id(),
        run_index=run_index,
        task_id=task_id,
        kind=RunKind.DISPATCH,
        role=WorkerRole.IMPLEMENTER,
        model="sonnet",
        session_id=new_session_id(),
        worktree_path="/tmp/worktree",
        started_at=now,
        finished_at=now,
        duration_ms=1234,
        exit_code=0,
        timed_out=False,
        killed_with_sigkill=False,
        argv_redacted=["claude", "-p"],
        stdout_bytes=10,
        stderr_bytes=0,
    )
    claims = None
    if worker_claims:
        claims = WorkerResult(status=WorkerStatus.COMPLETED, summary="Did the thing.")
    observations = DispatcherObservations(
        task_id=task_id,
        run_id=metadata.run_id,
        session_id=metadata.session_id,
        model="sonnet",
        base_commit="a" * 40,
        duration_ms=1234,
        exit_code=0,
    )
    return RunRecord(
        metadata=metadata,
        worker_claims=claims,
        dispatcher_observations=observations,
        validation_results=[],
    )


def _review() -> FableReview:
    return FableReview(
        verdict=FableVerdict.APPROVE,
        findings=[
            FableFinding(
                id="f1",
                severity=FableSeverity.LOW,
                category=FableCategory.MAINTAINABILITY,
                finding="Minor nit.",
            )
        ],
        recommended_next_action=RecommendedNextAction.ACCEPT,
    )


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(tmp_path / "state" / "tasks")


@pytest.fixture
def created(store: TaskStore, valid_request_dict: dict):
    env = _envelope(valid_request_dict)
    record = store.create(env)
    return store, env, record


# ---------------------------------------------------------------------------
# atomic_write_text / atomic_write_json
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_writes_content(self, tmp_path: Path):
        path = tmp_path / "a" / "b.txt"
        atomic_write_text(path, "hello")
        assert path.read_text() == "hello"

    def test_overwrite_replaces_content(self, tmp_path: Path):
        path = tmp_path / "b.txt"
        atomic_write_text(path, "first")
        atomic_write_text(path, "second")
        assert path.read_text() == "second"

    def test_no_temp_file_left_behind_on_success(self, tmp_path: Path):
        path = tmp_path / "c.txt"
        atomic_write_text(path, "content")
        leftovers = [p for p in tmp_path.iterdir() if p.name != "c.txt"]
        assert leftovers == []

    def test_file_mode_is_0600(self, tmp_path: Path):
        path = tmp_path / "d.txt"
        atomic_write_text(path, "content")
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600

    def test_custom_mode_respected(self, tmp_path: Path):
        path = tmp_path / "e.txt"
        atomic_write_text(path, "content", mode=0o640)
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o640

    def test_json_round_trips(self, tmp_path: Path):
        path = tmp_path / "f.json"
        atomic_write_json(path, {"a": 1, "b": [1, 2, 3]})
        assert json.loads(path.read_text()) == {"a": 1, "b": [1, 2, 3]}

    def test_crash_simulation_leaves_no_partial_file(self, tmp_path: Path, monkeypatch):
        """Simulate a crash mid-write: os.replace never runs, temp file stays
        behind, but the destination file must not exist or be corrupted, and
        a subsequent real write must succeed and be ignored/cleaned up
        (§31: 'temp file left behind is ignored')."""
        path = tmp_path / "g.txt"

        real_replace = os.replace

        def boom(*a, **kw):
            raise OSError("simulated crash before replace")

        monkeypatch.setattr(os, "replace", boom)
        with pytest.raises(OSError):
            atomic_write_text(path, "will not land")
        monkeypatch.setattr(os, "replace", real_replace)

        # Destination was never created.
        assert not path.exists()
        # The temp file was cleaned up by the failure path.
        assert list(tmp_path.iterdir()) == []

        # A later, successful write is unaffected by the earlier failure.
        atomic_write_text(path, "final")
        assert path.read_text() == "final"

    def test_stray_leftover_temp_file_is_ignored_by_readers(self, tmp_path: Path):
        """A leftover ``.name.tmp-*`` file (e.g. from a real process crash
        that died before cleanup) must not be picked up by anything that
        reads ``tmp_path`` for the real file."""
        path = tmp_path / "h.txt"
        atomic_write_text(path, "real content")
        # Plant a stray temp file as a real crash would leave one.
        stray = tmp_path / ".h.txt.tmp-99999-deadbeef"
        stray.write_text("stale partial data")

        assert path.read_text() == "real content"
        # Overwriting again must still succeed and not be confused by the
        # stray file sharing a similar name.
        atomic_write_text(path, "updated content")
        assert path.read_text() == "updated content"
        assert stray.exists()  # untouched, but harmless — not the real file


# ---------------------------------------------------------------------------
# TaskStore.__init__ / directory permissions
# ---------------------------------------------------------------------------


class TestTaskStoreInit:
    def test_creates_root_directory(self, tmp_path: Path):
        root = tmp_path / "state" / "tasks"
        assert not root.exists()
        TaskStore(root)
        assert root.is_dir()

    def test_root_directory_mode_0700(self, tmp_path: Path):
        root = tmp_path / "state" / "tasks"
        TaskStore(root)
        mode = stat.S_IMODE(root.stat().st_mode)
        assert mode == 0o700

    def test_idempotent_on_existing_root(self, tmp_path: Path):
        root = tmp_path / "state" / "tasks"
        TaskStore(root)
        TaskStore(root)  # must not raise
        assert root.is_dir()


class TestTaskIdContainment:
    """P0-1: the store is safe on its own, without the MCP-layer validator.

    The exhaustive adversarial matrix lives in ``test_boundary_adversarial.py``;
    these pin the behaviour where ``TaskStore``'s own tests live.
    """

    def test_task_dir_refuses_a_traversing_id(self, store: TaskStore):
        with pytest.raises(InvalidTaskEnvelope):
            store.task_dir("../escape")

    def test_task_dir_refuses_an_absolute_id(self, store: TaskStore):
        with pytest.raises(InvalidTaskEnvelope):
            store.task_dir("/etc")

    def test_task_dir_refuses_a_nested_id(self, store: TaskStore):
        with pytest.raises(InvalidTaskEnvelope):
            store.task_dir("foo/bar")

    def test_a_safe_non_uuid_id_is_still_usable(self, store: TaskStore):
        """Unknown-but-safe ids must still report "not found", not "invalid"."""
        with pytest.raises(TaskNotFound):
            store.load("does-not-exist")


# ---------------------------------------------------------------------------
# create / load_envelope / load / exists
# ---------------------------------------------------------------------------


class TestCreate:
    def test_creates_task_directory_tree(self, store: TaskStore, valid_request_dict):
        env = _envelope(valid_request_dict)
        store.create(env)
        task_dir = store.task_dir(env.task_id)
        assert (task_dir / "envelope.json").is_file()
        assert (task_dir / "state.json").is_file()
        assert (task_dir / "runs").is_dir()
        assert (task_dir / "reviews").is_dir()
        assert (task_dir / "evidence").is_dir()

    def test_directories_are_0700(self, store: TaskStore, valid_request_dict):
        env = _envelope(valid_request_dict)
        store.create(env)
        task_dir = store.task_dir(env.task_id)
        for d in (task_dir, task_dir / "runs", task_dir / "reviews", task_dir / "evidence"):
            assert stat.S_IMODE(d.stat().st_mode) == 0o700

    def test_files_are_0600(self, store: TaskStore, valid_request_dict):
        env = _envelope(valid_request_dict)
        store.create(env)
        task_dir = store.task_dir(env.task_id)
        for f in (task_dir / "envelope.json", task_dir / "state.json"):
            assert stat.S_IMODE(f.stat().st_mode) == 0o600

    def test_initial_record_state_is_created(self, store: TaskStore, valid_request_dict):
        env = _envelope(valid_request_dict)
        record = store.create(env)
        assert record.state == TaskState.CREATED
        assert record.resume_count == 0
        assert record.run_count == 0
        assert record.task_id == env.task_id

    def test_duplicate_create_raises(self, store: TaskStore, valid_request_dict):
        env = _envelope(valid_request_dict)
        store.create(env)
        with pytest.raises(InvalidTaskEnvelope):
            store.create(env)

    def test_exists_true_after_create_false_before(self, store: TaskStore, valid_request_dict):
        env = _envelope(valid_request_dict)
        assert store.exists(env.task_id) is False
        store.create(env)
        assert store.exists(env.task_id) is True

    def test_load_envelope_round_trips(self, store: TaskStore, valid_request_dict):
        env = _envelope(valid_request_dict)
        store.create(env)
        loaded = store.load_envelope(env.task_id)
        assert loaded == env

    def test_load_missing_task_raises_task_not_found(self, store: TaskStore):
        with pytest.raises(TaskNotFound):
            store.load("does-not-exist")

    def test_load_envelope_missing_task_raises_task_not_found(self, store: TaskStore):
        with pytest.raises(TaskNotFound):
            store.load_envelope("does-not-exist")


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSave:
    def test_save_persists_changes(self, created):
        store, env, record = created
        record.selected_model = "sonnet"
        store.save(record)
        reloaded = store.load(env.task_id)
        assert reloaded.selected_model == "sonnet"

    def test_save_updates_updated_at(self, created):
        store, env, record = created
        original_updated_at = record.updated_at
        record.selected_model = "opus"
        store.save(record)
        reloaded = store.load(env.task_id)
        assert reloaded.updated_at >= original_updated_at


# ---------------------------------------------------------------------------
# transition — valid transitions (every legal edge)
# ---------------------------------------------------------------------------


class TestTransitionValid:
    def test_created_to_routed(self, created):
        store, env, record = created
        result = store.transition(
            env.task_id, TaskState.ROUTED, reason="explicit_request:sonnet",
            selected_model="sonnet",
        )
        assert result.state == TaskState.ROUTED
        assert result.selected_model == "sonnet"

    def test_created_to_failed(self, created):
        store, env, record = created
        result = store.transition(env.task_id, TaskState.FAILED, reason="boom")
        assert result.state == TaskState.FAILED

    def test_full_happy_path(self, created):
        store, env, record = created
        tid = env.task_id
        store.transition(tid, TaskState.ROUTED, selected_model="sonnet")
        store.transition(tid, TaskState.RUNNING, session_id="s1", worktree_path="/tmp/w")
        store.transition(tid, TaskState.IMPLEMENTED)
        store.transition(tid, TaskState.AWAITING_SOL_REVIEW)
        store.transition(tid, TaskState.FABLE_REVIEWED)
        store.transition(tid, TaskState.RESUME_REQUESTED)
        store.transition(tid, TaskState.RUNNING)
        store.transition(tid, TaskState.IMPLEMENTED)
        store.transition(tid, TaskState.AWAITING_SOL_REVIEW)
        final = store.transition(tid, TaskState.REVIEW_COMPLETE)
        assert final.state == TaskState.REVIEW_COMPLETE

    def test_running_off_ramps(self, store: TaskStore, valid_request_dict):
        for target in (
            TaskState.IMPLEMENTED,
            TaskState.TIMED_OUT,
            TaskState.BLOCKED,
            TaskState.FAILED,
            TaskState.POLICY_VIOLATION,
        ):
            env = _envelope(valid_request_dict)
            store.create(env)
            store.transition(env.task_id, TaskState.ROUTED)
            store.transition(env.task_id, TaskState.RUNNING)
            result = store.transition(env.task_id, target)
            assert result.state == target

    def test_off_ramps_go_through_resume_requested_not_directly_to_running(
        self, store: TaskStore, valid_request_dict
    ):
        """§26: no off-ramp jumps straight back to RUNNING."""
        for off_ramp in (TaskState.TIMED_OUT, TaskState.BLOCKED, TaskState.POLICY_VIOLATION):
            env = _envelope(valid_request_dict)
            store.create(env)
            store.transition(env.task_id, TaskState.ROUTED)
            store.transition(env.task_id, TaskState.RUNNING)
            store.transition(env.task_id, off_ramp)
            with pytest.raises(InvalidStateTransition):
                store.transition(env.task_id, TaskState.RUNNING)
            # But it can reach RUNNING via RESUME_REQUESTED.
            store.transition(env.task_id, TaskState.RESUME_REQUESTED)
            result = store.transition(env.task_id, TaskState.RUNNING)
            assert result.state == TaskState.RUNNING

    def test_failed_can_request_a_corrective_resume(
        self, store: TaskStore, valid_request_dict
    ):
        """§26: FAILED is an off-ramp, not a dead end.

        The session id and the worktree are still on disk when a run lands
        FAILED, so Sol must be able to ask for a corrective resume — through
        RESUME_REQUESTED, like every other off-ramp, so the cap is consulted.
        """
        env = _envelope(valid_request_dict)
        store.create(env)
        store.transition(env.task_id, TaskState.ROUTED)
        store.transition(env.task_id, TaskState.RUNNING)
        store.transition(env.task_id, TaskState.FAILED)

        with pytest.raises(InvalidStateTransition):
            store.transition(env.task_id, TaskState.RUNNING)

        store.transition(env.task_id, TaskState.RESUME_REQUESTED, resume_count=1)
        result = store.transition(env.task_id, TaskState.RUNNING)
        assert result.state == TaskState.RUNNING
        assert result.resume_count == 1

    def test_failed_can_reach_awaiting_sol_review(self, store: TaskStore, valid_request_dict):
        env = _envelope(valid_request_dict)
        store.create(env)
        store.transition(env.task_id, TaskState.ROUTED)
        store.transition(env.task_id, TaskState.RUNNING)
        store.transition(env.task_id, TaskState.FAILED)
        result = store.transition(env.task_id, TaskState.AWAITING_SOL_REVIEW)
        assert result.state == TaskState.AWAITING_SOL_REVIEW

    def test_transition_records_history_entry(self, created):
        store, env, record = created
        store.transition(env.task_id, TaskState.ROUTED, reason="kind:concurrency")
        reloaded = store.load(env.task_id)
        assert len(reloaded.state_history) == 1
        entry = reloaded.state_history[0]
        assert entry["from"] == "created"
        assert entry["to"] == "routed"
        assert entry["reason"] == "kind:concurrency"
        assert "at" in entry

    def test_resume_count_increments_via_update(self, created):
        store, env, record = created
        store.transition(env.task_id, TaskState.ROUTED)
        store.transition(env.task_id, TaskState.RUNNING)
        store.transition(env.task_id, TaskState.TIMED_OUT)
        result = store.transition(
            env.task_id, TaskState.RESUME_REQUESTED, resume_count=1
        )
        assert result.resume_count == 1


# ---------------------------------------------------------------------------
# transition — invalid transitions
# ---------------------------------------------------------------------------


class TestTransitionInvalid:
    def test_created_to_running_is_rejected(self, created):
        store, env, record = created
        with pytest.raises(InvalidStateTransition) as exc:
            store.transition(env.task_id, TaskState.RUNNING)
        payload = exc.value.details
        assert payload["from"] == "created"
        assert payload["to"] == "running"
        assert "allowed" in payload

    def test_review_complete_is_terminal(self, store: TaskStore, valid_request_dict):
        env = _envelope(valid_request_dict)
        store.create(env)
        tid = env.task_id
        store.transition(tid, TaskState.ROUTED)
        store.transition(tid, TaskState.RUNNING)
        store.transition(tid, TaskState.IMPLEMENTED)
        store.transition(tid, TaskState.AWAITING_SOL_REVIEW)
        store.transition(tid, TaskState.REVIEW_COMPLETE)
        for target in (TaskState.RUNNING, TaskState.FAILED, TaskState.AWAITING_SOL_REVIEW):
            with pytest.raises(InvalidStateTransition):
                store.transition(tid, target)

    def test_created_to_implemented_is_rejected(self, created):
        store, env, record = created
        with pytest.raises(InvalidStateTransition):
            store.transition(env.task_id, TaskState.IMPLEMENTED)

    def test_invalid_transition_does_not_mutate_state(self, created):
        store, env, record = created
        with pytest.raises(InvalidStateTransition):
            store.transition(env.task_id, TaskState.RUNNING)
        reloaded = store.load(env.task_id)
        assert reloaded.state == TaskState.CREATED
        assert reloaded.state_history == []

    def test_unknown_update_field_is_rejected(self, created):
        store, env, record = created
        with pytest.raises(InvalidStateTransition):
            store.transition(env.task_id, TaskState.ROUTED, bogus_field="nope")

    def test_transition_missing_task_raises_task_not_found(self, store: TaskStore):
        with pytest.raises(TaskNotFound):
            store.transition("does-not-exist", TaskState.ROUTED)


# ---------------------------------------------------------------------------
# corruption — fails closed
# ---------------------------------------------------------------------------


class TestCorruption:
    def test_unparseable_json_state_raises_state_corruption(self, created):
        store, env, record = created
        (store.task_dir(env.task_id) / "state.json").write_text("{not json")
        with pytest.raises(StateCorruption):
            store.load(env.task_id)

    def test_unparseable_json_envelope_raises_state_corruption(self, created):
        store, env, record = created
        (store.task_dir(env.task_id) / "envelope.json").write_text("not json at all")
        with pytest.raises(StateCorruption):
            store.load_envelope(env.task_id)

    def test_missing_schema_version_raises_state_corruption(self, created):
        store, env, record = created
        path = store.task_dir(env.task_id) / "state.json"
        data = json.loads(path.read_text())
        del data["schema_version"]
        path.write_text(json.dumps(data))
        with pytest.raises(StateCorruption):
            store.load(env.task_id)

    def test_wrong_schema_version_raises_state_corruption(self, created):
        store, env, record = created
        path = store.task_dir(env.task_id) / "state.json"
        data = json.loads(path.read_text())
        data["schema_version"] = "9.9"
        path.write_text(json.dumps(data))
        with pytest.raises(StateCorruption):
            store.load(env.task_id)

    def test_non_object_json_raises_state_corruption(self, created):
        store, env, record = created
        path = store.task_dir(env.task_id) / "state.json"
        path.write_text(json.dumps([1, 2, 3]))
        with pytest.raises(StateCorruption):
            store.load(env.task_id)

    def test_schema_mismatch_content_raises_state_corruption(self, created):
        store, env, record = created
        path = store.task_dir(env.task_id) / "state.json"
        data = json.loads(path.read_text())
        data["state"] = "not-a-real-state"
        path.write_text(json.dumps(data))
        with pytest.raises(StateCorruption):
            store.load(env.task_id)

    def test_corruption_is_never_repaired(self, created):
        """A second load of corrupt state still raises; nothing silently
        rewrites or 'fixes' the file."""
        store, env, record = created
        path = store.task_dir(env.task_id) / "state.json"
        path.write_text("{broken")
        with pytest.raises(StateCorruption):
            store.load(env.task_id)
        # Still broken — no silent repair happened.
        assert path.read_text() == "{broken"
        with pytest.raises(StateCorruption):
            store.load(env.task_id)


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


class TestRuns:
    def test_append_run_writes_dispatcher_result(self, created):
        store, env, record = created
        run = _run_record(env.task_id, 1)
        store.append_run(env.task_id, run)
        run_dir = store.run_dir(env.task_id, 1)
        assert (run_dir / "dispatcher-result.json").is_file()
        assert stat.S_IMODE((run_dir / "dispatcher-result.json").stat().st_mode) == 0o600
        assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700

    def test_append_run_increments_run_count(self, created):
        store, env, record = created
        store.append_run(env.task_id, _run_record(env.task_id, 1))
        reloaded = store.load(env.task_id)
        assert reloaded.run_count == 1
        store.append_run(env.task_id, _run_record(env.task_id, 2))
        reloaded = store.load(env.task_id)
        assert reloaded.run_count == 2

    def test_run_directories_numbered_001_002(self, created):
        store, env, record = created
        store.append_run(env.task_id, _run_record(env.task_id, 1))
        store.append_run(env.task_id, _run_record(env.task_id, 2))
        task_dir = store.task_dir(env.task_id)
        assert (task_dir / "runs" / "001").is_dir()
        assert (task_dir / "runs" / "002").is_dir()

    def test_load_runs_ordered_by_run_index(self, created):
        store, env, record = created
        store.append_run(env.task_id, _run_record(env.task_id, 1))
        store.append_run(env.task_id, _run_record(env.task_id, 2))
        store.append_run(env.task_id, _run_record(env.task_id, 3))
        runs = store.load_runs(env.task_id)
        assert [r.metadata.run_index for r in runs] == [1, 2, 3]

    def test_load_runs_empty_when_none(self, created):
        store, env, record = created
        assert store.load_runs(env.task_id) == []

    def test_latest_run_returns_highest_index(self, created):
        store, env, record = created
        store.append_run(env.task_id, _run_record(env.task_id, 1))
        store.append_run(env.task_id, _run_record(env.task_id, 2))
        latest = store.latest_run(env.task_id)
        assert latest is not None
        assert latest.metadata.run_index == 2

    def test_latest_run_none_when_no_runs(self, created):
        store, env, record = created
        assert store.latest_run(env.task_id) is None

    def test_run_record_preserves_claims_and_observations_separately(self, created):
        store, env, record = created
        run = _run_record(env.task_id, 1)
        store.append_run(env.task_id, run)
        loaded = store.load_runs(env.task_id)[0]
        assert loaded.worker_claims is not None
        assert loaded.dispatcher_observations is not None
        assert loaded.worker_claims.summary == run.worker_claims.summary
        assert loaded.dispatcher_observations.model == run.dispatcher_observations.model

    def test_run_with_no_worker_claims_survives(self, created):
        store, env, record = created
        run = _run_record(env.task_id, 1, worker_claims=False)
        store.append_run(env.task_id, run)
        loaded = store.load_runs(env.task_id)[0]
        assert loaded.worker_claims is None


# ---------------------------------------------------------------------------
# reviews
# ---------------------------------------------------------------------------


class TestReviews:
    def test_append_review_writes_fable_001(self, created):
        store, env, record = created
        number = store.append_review(env.task_id, _review())
        assert number == 1
        path = store.task_dir(env.task_id) / "reviews" / "fable-001.json"
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_append_review_numbers_sequentially(self, created):
        store, env, record = created
        n1 = store.append_review(env.task_id, _review())
        n2 = store.append_review(env.task_id, _review())
        assert (n1, n2) == (1, 2)
        assert (store.task_dir(env.task_id) / "reviews" / "fable-002.json").is_file()

    def test_append_review_bumps_fable_review_count(self, created):
        store, env, record = created
        store.append_review(env.task_id, _review())
        reloaded = store.load(env.task_id)
        assert reloaded.fable_review_count == 1

    def test_load_reviews_returns_all_in_order(self, created):
        store, env, record = created
        store.append_review(env.task_id, _review())
        store.append_review(env.task_id, _review())
        reviews = store.load_reviews(env.task_id)
        assert len(reviews) == 2
        assert all(isinstance(r, FableReview) for r in reviews)

    def test_load_reviews_empty_when_none(self, created):
        store, env, record = created
        assert store.load_reviews(env.task_id) == []


# ---------------------------------------------------------------------------
# evidence
# ---------------------------------------------------------------------------


class TestEvidence:
    def test_write_and_read_evidence(self, created):
        store, env, record = created
        path = store.write_evidence(env.task_id, "diff.patch", "diff --git a b\n")
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert store.read_evidence(env.task_id, "diff.patch") == "diff --git a b\n"

    def test_read_missing_evidence_returns_none(self, created):
        store, env, record = created
        assert store.read_evidence(env.task_id, "nope.txt") is None

    def test_evidence_name_rejects_path_separator(self, created):
        store, env, record = created
        with pytest.raises(InvalidTaskEnvelope):
            store.write_evidence(env.task_id, "sub/dir.txt", "x")

    def test_evidence_name_rejects_traversal(self, created):
        store, env, record = created
        with pytest.raises(InvalidTaskEnvelope):
            store.write_evidence(env.task_id, "../escape.txt", "x")

    def test_evidence_name_rejects_an_absolute_path(self, created):
        store, env, record = created
        with pytest.raises(InvalidTaskEnvelope):
            store.write_evidence(env.task_id, "/etc/passwd", "x")

    def test_evidence_name_rejects_a_control_character(self, created):
        store, env, record = created
        with pytest.raises(InvalidTaskEnvelope):
            store.write_evidence(env.task_id, "diff\x00.patch", "x")

    def test_evidence_names_from_layout(self, created):
        store, env, record = created
        store.write_evidence(env.task_id, "diff.patch", "patch")
        store.write_evidence(env.task_id, "diff-stat.txt", "1 file changed")
        store.write_evidence(
            env.task_id, "changed-paths.json", json.dumps(["a.py"])
        )
        evidence_dir = store.task_dir(env.task_id) / "evidence"
        assert {p.name for p in evidence_dir.iterdir()} == {
            "diff.patch",
            "diff-stat.txt",
            "changed-paths.json",
        }


# ---------------------------------------------------------------------------
# persistence across store re-instantiation (restart recovery)
# ---------------------------------------------------------------------------


class TestPersistenceAcrossRestart:
    def test_new_store_instance_sees_same_task(self, tmp_path: Path, valid_request_dict):
        root = tmp_path / "state" / "tasks"
        store1 = TaskStore(root)
        env = _envelope(valid_request_dict)
        store1.create(env)
        store1.transition(env.task_id, TaskState.ROUTED, selected_model="sonnet")

        # Fresh instance, as after an MCP server restart. TaskStore holds no
        # authoritative in-memory state — every read re-reads from disk.
        store2 = TaskStore(root)
        reloaded = store2.load(env.task_id)
        assert reloaded.state == TaskState.ROUTED
        assert reloaded.selected_model == "sonnet"
        assert store2.load_envelope(env.task_id) == env

    def test_list_tasks_reconstructs_from_disk(self, tmp_path: Path, valid_request_dict):
        root = tmp_path / "state" / "tasks"
        store1 = TaskStore(root)
        env1 = _envelope(valid_request_dict)
        env2 = _envelope(valid_request_dict)
        store1.create(env1)
        store1.create(env2)

        store2 = TaskStore(root)
        task_ids = set(store2.list_tasks())
        assert task_ids == {env1.task_id, env2.task_id}

    def test_load_all_reconstructs_records(self, tmp_path: Path, valid_request_dict):
        root = tmp_path / "state" / "tasks"
        store1 = TaskStore(root)
        env = _envelope(valid_request_dict)
        store1.create(env)
        store1.transition(env.task_id, TaskState.ROUTED)

        store2 = TaskStore(root)
        records = store2.load_all()
        assert len(records) == 1
        assert records[0].task_id == env.task_id
        assert records[0].state == TaskState.ROUTED

    def test_runs_and_reviews_survive_restart(self, tmp_path: Path, valid_request_dict):
        root = tmp_path / "state" / "tasks"
        store1 = TaskStore(root)
        env = _envelope(valid_request_dict)
        store1.create(env)
        store1.append_run(env.task_id, _run_record(env.task_id, 1))
        store1.append_review(env.task_id, _review())

        store2 = TaskStore(root)
        assert len(store2.load_runs(env.task_id)) == 1
        assert len(store2.load_reviews(env.task_id)) == 1
