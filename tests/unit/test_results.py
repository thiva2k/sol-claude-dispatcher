"""Tests for structured result parsing (brief §15, §16, §19, §31)."""

from __future__ import annotations

import json

import pytest

from sol_claude_dispatcher.errors import ClaudeStructuredOutputInvalid
from sol_claude_dispatcher.git import DiffEvidence, ScopeCheck
from sol_claude_dispatcher.models import FableReview, WorkerResult
from sol_claude_dispatcher.results import (
    build_dispatcher_observations,
    extract_structured_payload,
    parse_fable_review,
    parse_worker_result,
)

VALID_WORKER_PAYLOAD = {
    "status": "completed",
    "summary": "Implemented atomic config deployment.",
    "changes": [
        {"path": "src/deploy/atomic.py", "type": "added", "description": "New writer."}
    ],
    "acceptance_criteria": [
        {
            "criterion": "Deployment must be atomic.",
            "status": "satisfied",
            "evidence": "test_atomic_write passes.",
        }
    ],
    "tests": [
        {"command": "pytest -q", "status": "passed", "exit_code": 0, "summary": "12 passed"}
    ],
    "risks": [],
    "blockers": [],
    "needs_review": True,
}

VALID_REVIEW_PAYLOAD = {
    "verdict": "approve",
    "findings": [],
    "missing_tests": [],
    "architecture_notes": [],
    "recommended_next_action": "accept",
}


# ---------------------------------------------------------------------------
# extract_structured_payload — the six-step resolution order
# ---------------------------------------------------------------------------


def test_extract_structured_output_key():
    envelope = {"structured_output": VALID_WORKER_PAYLOAD, "other": "noise"}
    assert extract_structured_payload(json.dumps(envelope)) == VALID_WORKER_PAYLOAD


def test_extract_result_as_object():
    envelope = {"result": VALID_WORKER_PAYLOAD, "type": "result"}
    assert extract_structured_payload(json.dumps(envelope)) == VALID_WORKER_PAYLOAD


def test_extract_result_as_string_double_encoded():
    envelope = {"result": json.dumps(VALID_WORKER_PAYLOAD), "type": "result"}
    assert extract_structured_payload(json.dumps(envelope)) == VALID_WORKER_PAYLOAD


def test_extract_result_as_string_not_json_falls_through_to_no_payload():
    envelope = {"result": "not actually json {{{"}
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        extract_structured_payload(json.dumps(envelope))
    assert exc_info.value.details["reason"] == "no_structured_payload"


def test_extract_top_level_direct_worker_shape():
    # No wrapper at all: the payload itself looks like a worker result.
    assert extract_structured_payload(json.dumps(VALID_WORKER_PAYLOAD)) == VALID_WORKER_PAYLOAD


def test_extract_top_level_direct_review_shape():
    assert extract_structured_payload(json.dumps(VALID_REVIEW_PAYLOAD)) == VALID_REVIEW_PAYLOAD


def test_extract_invalid_json_raises():
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        extract_structured_payload("{not json")
    assert exc_info.value.code == "ClaudeStructuredOutputInvalid"
    assert exc_info.value.details["reason"] == "not_json"


def test_extract_empty_stdout_raises():
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        extract_structured_payload("")
    assert exc_info.value.details["reason"] == "not_json"


def test_extract_non_object_top_level_raises():
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        extract_structured_payload(json.dumps([1, 2, 3]))
    assert exc_info.value.details["reason"] == "top_level_not_object"
    assert exc_info.value.details["top_level_type"] == "list"


def test_extract_no_structured_payload_raises():
    envelope = {"type": "system", "subtype": "init"}
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        extract_structured_payload(json.dumps(envelope))
    assert exc_info.value.details["reason"] == "no_structured_payload"
    assert exc_info.value.details["top_level_keys"] == ["subtype", "type"]


def test_extract_structured_output_key_precedes_result_key():
    envelope = {"structured_output": VALID_WORKER_PAYLOAD, "result": {"status": "failed"}}
    payload = extract_structured_payload(json.dumps(envelope))
    assert payload["status"] == "completed"


# ---------------------------------------------------------------------------
# parse_worker_result
# ---------------------------------------------------------------------------


def test_parse_worker_result_valid():
    stdout = json.dumps({"result": VALID_WORKER_PAYLOAD})
    result = parse_worker_result(stdout)
    assert isinstance(result, WorkerResult)
    assert result.status.value == "completed"
    assert result.summary == VALID_WORKER_PAYLOAD["summary"]


def test_parse_worker_result_invalid_json():
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        parse_worker_result("not json at all")
    assert exc_info.value.details["reason"] == "not_json"


def test_parse_worker_result_valid_json_wrong_schema():
    # Valid JSON, valid envelope shape (an object under "result", so
    # extraction succeeds unconditionally per step 3), but the payload is a
    # review, not a worker result (has "verdict", not "status"/"summary") —
    # so *schema* validation is what fails, not extraction.
    stdout = json.dumps({"result": VALID_REVIEW_PAYLOAD})
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        parse_worker_result(stdout)
    assert exc_info.value.details["reason"] == "schema_mismatch"


def test_parse_worker_result_missing_required_field():
    bad = dict(VALID_WORKER_PAYLOAD)
    del bad["summary"]
    stdout = json.dumps({"result": bad})
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        parse_worker_result(stdout)
    assert exc_info.value.details["reason"] == "schema_mismatch"
    locations = [issue["location"] for issue in exc_info.value.details["issues"]]
    assert "summary" in locations


def test_parse_worker_result_extra_field_rejected():
    bad = dict(VALID_WORKER_PAYLOAD)
    bad["totally_made_up_field"] = "nope"
    stdout = json.dumps({"result": bad})
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        parse_worker_result(stdout)
    assert exc_info.value.details["reason"] == "schema_mismatch"


def test_parse_worker_result_nonzero_exit_empty_stdout():
    # A worker that exits nonzero without ever emitting structured output
    # (crash, permission denial before it could print) must fail closed
    # rather than being silently treated as "no result".
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        parse_worker_result("")
    assert exc_info.value.details["reason"] == "not_json"


def test_parse_worker_result_wrong_type_for_status():
    bad = dict(VALID_WORKER_PAYLOAD)
    bad["status"] = "in_progress"  # not a member of WorkerStatus
    stdout = json.dumps({"result": bad})
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        parse_worker_result(stdout)
    assert exc_info.value.details["reason"] == "schema_mismatch"


# ---------------------------------------------------------------------------
# parse_fable_review
# ---------------------------------------------------------------------------


def test_parse_fable_review_valid():
    stdout = json.dumps({"result": VALID_REVIEW_PAYLOAD})
    review = parse_fable_review(stdout)
    assert isinstance(review, FableReview)
    assert review.verdict.value == "approve"


def test_parse_fable_review_invalid_json():
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        parse_fable_review("{{{broken")
    assert exc_info.value.details["reason"] == "not_json"


def test_parse_fable_review_missing_required_field():
    bad = dict(VALID_REVIEW_PAYLOAD)
    del bad["verdict"]
    # Wrapped under "result" as an object, so extraction succeeds
    # unconditionally (step 3 of the resolution order does not inspect
    # shape); it is *schema* validation against FableReview that then fails
    # because "verdict" is a required field.
    stdout = json.dumps({"result": bad})
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        parse_fable_review(stdout)
    assert exc_info.value.details["reason"] == "schema_mismatch"
    locations = [issue["location"] for issue in exc_info.value.details["issues"]]
    assert "verdict" in locations


def test_parse_fable_review_missing_required_field_unwrapped_no_structured_payload():
    # Same missing field, but with *no* wrapper at all: extraction now falls
    # to step 6 ("does the top level look like the target?"), and without
    # "verdict" it does not, so the failure surfaces one step earlier, as
    # "no structured payload", instead of reaching schema validation.
    bad = dict(VALID_REVIEW_PAYLOAD)
    del bad["verdict"]
    stdout = json.dumps(bad)
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        parse_fable_review(stdout)
    assert exc_info.value.details["reason"] == "no_structured_payload"


def test_parse_fable_review_wrong_schema_bad_verdict_value():
    bad = dict(VALID_REVIEW_PAYLOAD)
    bad["verdict"] = "meh"
    stdout = json.dumps({"result": bad})
    with pytest.raises(ClaudeStructuredOutputInvalid) as exc_info:
        parse_fable_review(stdout)
    assert exc_info.value.details["reason"] == "schema_mismatch"


# ---------------------------------------------------------------------------
# build_dispatcher_observations — never merges claims into observations
# ---------------------------------------------------------------------------


def _diff_evidence(**overrides) -> DiffEvidence:
    base = dict(
        base_commit="a" * 40,
        changed_paths=["src/deploy/atomic.py"],
        diff_text="diff --git a/x b/x\n+hello\n",
        diff_stat="1 file changed",
        porcelain_status=" M src/deploy/atomic.py\n",
        diff_check_passed=True,
        diff_check_output="",
        truncated=False,
    )
    base.update(overrides)
    return DiffEvidence(**base)


def test_build_dispatcher_observations_shape():
    worker_result = WorkerResult.model_validate(VALID_WORKER_PAYLOAD)
    diff_evidence = _diff_evidence()
    scope_check = ScopeCheck(valid=True, out_of_scope=[], forbidden=[])

    obs = build_dispatcher_observations(
        task_id="task-1",
        run_id="run-1",
        session_id="session-1",
        model="sonnet",
        base_commit="a" * 40,
        duration_ms=1234,
        exit_code=0,
        timed_out=False,
        diff_evidence=diff_evidence,
        scope_check=scope_check,
        worker_result=worker_result,
        worker_result_error=None,
        primary_worktree_clean=True,
    )

    assert obs.task_id == "task-1"
    assert obs.run_id == "run-1"
    assert obs.session_id == "session-1"
    assert obs.model == "sonnet"
    assert obs.base_commit == "a" * 40
    assert obs.duration_ms == 1234
    assert obs.exit_code == 0
    assert obs.timed_out is False
    assert obs.changed_paths == ["src/deploy/atomic.py"]
    assert obs.diff_stat == "1 file changed"
    assert obs.scope_valid is True
    assert obs.out_of_scope_paths == []
    assert obs.forbidden_paths_touched == []
    assert obs.diff_check_passed is True
    assert obs.worker_result_parsed is True
    assert obs.worker_result_error is None
    assert obs.primary_worktree_clean is True


def test_build_dispatcher_observations_worker_result_none_marks_unparsed():
    diff_evidence = _diff_evidence()
    scope_check = ScopeCheck(valid=False, out_of_scope=["bad/path.py"], forbidden=[])

    obs = build_dispatcher_observations(
        task_id="task-2",
        run_id="run-2",
        session_id="session-2",
        model="opus",
        base_commit="b" * 40,
        duration_ms=500,
        exit_code=1,
        timed_out=False,
        diff_evidence=diff_evidence,
        scope_check=scope_check,
        worker_result=None,
        worker_result_error="ClaudeStructuredOutputInvalid: not_json",
    )

    assert obs.worker_result_parsed is False
    assert obs.worker_result_error == "ClaudeStructuredOutputInvalid: not_json"
    assert obs.scope_valid is False
    assert obs.out_of_scope_paths == ["bad/path.py"]


def test_build_dispatcher_observations_never_contains_worker_claim_fields():
    # WorkerResult and DispatcherObservations share zero field names (models.py
    # enforces this globally); this test additionally proves that even when a
    # rich worker_result is supplied, none of its data leaks into the object
    # this function returns — only presence/absence and the error string.
    worker_result = WorkerResult.model_validate(VALID_WORKER_PAYLOAD)
    diff_evidence = _diff_evidence(changed_paths=[])
    scope_check = ScopeCheck(valid=True, out_of_scope=[], forbidden=[])

    obs = build_dispatcher_observations(
        task_id="task-3",
        run_id="run-3",
        session_id="session-3",
        model="sonnet",
        base_commit="c" * 40,
        duration_ms=1,
        exit_code=0,
        timed_out=False,
        diff_evidence=diff_evidence,
        scope_check=scope_check,
        worker_result=worker_result,
    )

    observation_fields = set(type(obs).model_fields)
    worker_fields = set(type(worker_result).model_fields)
    assert observation_fields.isdisjoint(worker_fields)
    # And the summary text the worker claimed never appears anywhere on obs.
    assert worker_result.summary not in obs.model_dump_json()
