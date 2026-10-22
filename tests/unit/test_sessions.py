"""Session lifecycle tests (brief §7.2, §11, §18, §22 layer 6, §31)."""

from __future__ import annotations

import inspect
import uuid
from pathlib import Path

import pytest

from sol_claude_dispatcher.config import load_config_from_mapping
from sol_claude_dispatcher.errors import (
    InvalidTaskEnvelope,
    ResumeLimitReached,
    StateCorruption,
)
from sol_claude_dispatcher.models import (
    SCHEMA_VERSION,
    TaskEnvelope,
    TaskRecord,
    TaskRequest,
    TaskState,
    utc_now,
)
from sol_claude_dispatcher.sessions import (
    ResumePlan,
    assert_resume_allowed,
    new_session,
    resume_limit_response,
    resume_plan,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASE_COMMIT = "b" * 40


@pytest.fixture
def envelope(valid_request_dict: dict, git_repo: Path) -> TaskEnvelope:
    request = TaskRequest.model_validate(valid_request_dict)
    return TaskEnvelope.from_request(
        request, canonical_root=str(git_repo), base_commit=BASE_COMMIT
    )


@pytest.fixture
def record(envelope: TaskEnvelope) -> TaskRecord:
    now = utc_now()
    return TaskRecord(
        schema_version=SCHEMA_VERSION,
        task_id=envelope.task_id,
        state=TaskState.AWAITING_SOL_REVIEW,
        selected_model="sonnet",
        session_id="55555555-5555-4555-8555-555555555555",
        worktree_path=f"/repo/.claude/worktrees/{envelope.worktree_name}",
        resume_count=0,
        run_count=1,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def dispatcher_config(tmp_path: Path):
    return load_config_from_mapping(
        {
            "dispatcher": {"state_dir": str(tmp_path / "state"), "max_timeout_seconds": 900},
            "models": {"sonnet": "sonnet", "opus": "opus", "fable": "fable"},
            "routing": {"default_model": "sonnet"},
            "security": {
                "max_dispatch_depth": 1,
                "allowed_repository_roots": [str(tmp_path)],
            },
        },
        project_root=PROJECT_ROOT,
    )


# ---------------------------------------------------------------------------
# new_session
# ---------------------------------------------------------------------------


def test_new_session_is_a_fresh_uuid4(envelope):
    first = new_session(envelope)
    second = new_session(envelope)

    assert first != second
    for value in (first, second):
        parsed = uuid.UUID(value)      # --session-id demands a real UUID
        assert parsed.version == 4
        assert str(parsed) == value


# ---------------------------------------------------------------------------
# resume caps (§22 layer 6, §7.2)
# ---------------------------------------------------------------------------


def test_resume_allowed_below_the_cap(envelope, record):
    assert envelope.execution.max_resume_count == 4
    for count in range(4):
        record.resume_count = count
        assert_resume_allowed(envelope, record)   # n-1 is fine


def test_resume_refused_at_the_cap(envelope, record):
    record.resume_count = envelope.execution.max_resume_count
    with pytest.raises(ResumeLimitReached) as exc:
        assert_resume_allowed(envelope, record)

    assert exc.value.details["resume_count"] == 4
    assert exc.value.details["max_resume_count"] == 4
    assert exc.value.details["task_id"] == envelope.task_id


def test_resume_limit_response_is_the_orchestrator_decision_shape(envelope, record):
    record.resume_count = 99
    with pytest.raises(ResumeLimitReached) as exc:
        assert_resume_allowed(envelope, record)

    payload = resume_limit_response(exc.value)
    assert payload["status"] == "requires_orchestrator_decision"
    assert payload["reason"] == "resume_limit_reached"
    assert payload["task_id"] == envelope.task_id
    assert payload["resume_count"] == 99
    assert payload["max_resume_count"] == 4


def test_zero_max_resume_count_refuses_the_first_resume(valid_request_dict, git_repo):
    valid_request_dict["execution"]["max_resume_count"] = 0
    request = TaskRequest.model_validate(valid_request_dict)
    env = TaskEnvelope.from_request(
        request, canonical_root=str(git_repo), base_commit=BASE_COMMIT
    )
    now = utc_now()
    rec = TaskRecord(
        schema_version=SCHEMA_VERSION, task_id=env.task_id,
        state=TaskState.AWAITING_SOL_REVIEW, selected_model="sonnet",
        session_id="s", worktree_path="/w", created_at=now, updated_at=now,
    )
    with pytest.raises(ResumeLimitReached):
        assert_resume_allowed(env, rec)


# ---------------------------------------------------------------------------
# resume_plan — everything comes from stored state
# ---------------------------------------------------------------------------


def test_resume_plan_reuses_session_model_and_worktree(envelope, record):
    plan = resume_plan(envelope, record, "Fix findings R1 and R3 only.")

    assert isinstance(plan, ResumePlan)
    assert plan.session_id == record.session_id
    assert plan.model == record.selected_model
    assert plan.worktree_path == record.worktree_path
    assert plan.task_id == envelope.task_id
    assert plan.instruction == "Fix findings R1 and R3 only."
    assert plan.timeout_seconds == envelope.execution.timeout_seconds


def test_resume_plan_increments_the_count_once_per_resume(envelope, record):
    assert resume_plan(envelope, record, "go").next_resume_count == 1
    record.resume_count = 1
    assert resume_plan(envelope, record, "go").next_resume_count == 2
    record.resume_count = 3
    assert resume_plan(envelope, record, "go").next_resume_count == 4


def test_resume_plan_has_no_way_for_a_caller_to_supply_a_session_id(envelope, record):
    """§7.2: 'Never trust the caller to supply a replacement session ID.'"""
    params = set(inspect.signature(resume_plan).parameters)
    assert "session_id" not in params
    assert "model" not in params
    assert "worktree_path" not in params
    assert params == {"envelope", "record", "instruction", "timeout_seconds", "config"}


def test_resume_plan_clamps_a_caller_timeout(envelope, record, dispatcher_config):
    plan = resume_plan(
        envelope, record, "go", timeout_seconds=99_999, config=dispatcher_config
    )
    assert plan.timeout_seconds == 900     # dispatcher.max_timeout_seconds

    plan = resume_plan(envelope, record, "go", timeout_seconds=120, config=dispatcher_config)
    assert plan.timeout_seconds == 120


def test_resume_plan_refuses_when_the_cap_is_exhausted(envelope, record):
    record.resume_count = 4
    with pytest.raises(ResumeLimitReached):
        resume_plan(envelope, record, "go")


@pytest.mark.parametrize("missing", ["session_id", "selected_model", "worktree_path"])
def test_resume_plan_refuses_incomplete_state(envelope, record, missing):
    setattr(record, missing, None)
    with pytest.raises(StateCorruption) as exc:
        resume_plan(envelope, record, "go")
    assert missing in exc.value.details["missing"]


def test_resume_plan_refuses_an_empty_instruction(envelope, record):
    with pytest.raises(InvalidTaskEnvelope):
        resume_plan(envelope, record, "   ")


def test_resume_plan_refuses_mismatched_record_and_envelope(envelope, record):
    record.task_id = "00000000-0000-4000-8000-000000000000"
    with pytest.raises(StateCorruption):
        resume_plan(envelope, record, "go")
