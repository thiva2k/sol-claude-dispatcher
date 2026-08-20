"""Core model validation (brief §8, §9, §15, §16, §19, §26).

The theme of this file is *what the type system refuses to let happen*: a caller
inventing an internal identifier, a worker claim masquerading as dispatcher
evidence, an envelope loading without a schema version, a state machine growing
an APPROVED state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from sol_claude_dispatcher import errors
from sol_claude_dispatcher.models import (
    ALLOWED_TRANSITIONS,
    ESCALATING_TASK_KINDS,
    SCHEMA_VERSION,
    TERMINAL_STATES,
    WORKTREE_NAME_RE,
    AcceptanceCriterionResult,
    ChangedFile,
    DispatcherObservations,
    FableReview,
    RunKind,
    RunMetadata,
    RunRecord,
    TaskEnvelope,
    TaskRequest,
    TaskState,
    TestReport,
    ValidationCommand,
    ValidationResult,
    WorkerResult,
    WorkerRole,
    is_transition_allowed,
    new_session_id,
    new_task_id,
    short_task_id,
    utc_now,
    worktree_name_for,
)

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"


# ---------------------------------------------------------------------------
# TaskRequest — the untrusted boundary
# ---------------------------------------------------------------------------


class TestTaskRequestHappyPath:
    def test_accepts_a_well_formed_request(self, valid_request_dict):
        req = TaskRequest(**valid_request_dict)
        assert req.task.objective.startswith("Implement atomic")
        assert req.scope.allowed_paths == ["src/deploy/**", "tests/**"]
        assert req.routing.requested_model.value == "auto"
        assert req.execution.timeout_seconds == 1800

    def test_optional_sections_default(self, git_repo):
        req = TaskRequest(
            repository={"root": str(git_repo)},
            task={"objective": "Do the thing."},
        )
        assert req.scope.allowed_paths == []
        assert req.validation.commands == []
        assert req.routing.requested_model.value == "auto"
        assert req.constraints.allow_push is False
        assert req.constraints.allow_subagents is False

    def test_routing_accepts_both_model_and_requested_model_spellings(self, git_repo):
        base = {"repository": {"root": str(git_repo)}, "task": {"objective": "x"}}
        a = TaskRequest(**base, routing={"model": "opus"})
        b = TaskRequest(**base, routing={"requested_model": "opus"})
        assert a.routing.requested_model == b.routing.requested_model


class TestTaskRequestRejectsInternalFields:
    """§7.1: the caller MUST NOT be trusted to provide internal identifiers."""

    @pytest.mark.parametrize(
        "field",
        [
            "task_id",
            "run_id",
            "session_id",
            "worktree_name",
            "worktree",
            "base_commit",
            "schema_version",
            "resume_count",
            "dispatch_depth",
            "created_at",
            "selected_model",
            "state",
        ],
    )
    def test_internal_field_at_top_level_is_rejected(self, valid_request_dict, field):
        payload = dict(valid_request_dict)
        payload[field] = "attacker-supplied"
        with pytest.raises(ValidationError) as exc:
            TaskRequest(**payload)
        assert "extra" in str(exc.value).lower()

    def test_base_commit_inside_repository_is_rejected(self, valid_request_dict):
        payload = dict(valid_request_dict)
        payload["repository"] = {**payload["repository"], "base_commit": "deadbeef"}
        with pytest.raises(ValidationError):
            TaskRequest(**payload)

    def test_lineage_dispatch_depth_is_not_caller_settable(self, valid_request_dict):
        payload = dict(valid_request_dict)
        payload["lineage"] = {"dispatch_depth": 0}
        with pytest.raises(ValidationError):
            TaskRequest(**payload)

    def test_unknown_field_anywhere_is_rejected(self, valid_request_dict):
        payload = dict(valid_request_dict)
        payload["task"] = {**payload["task"], "priority": "urgent"}
        with pytest.raises(ValidationError):
            TaskRequest(**payload)

    def test_parent_task_id_is_allowed_because_sol_owns_lineage(self, git_repo):
        req = TaskRequest(
            repository={"root": str(git_repo)},
            task={"objective": "x"},
            parent_task_id="abc",
        )
        assert req.parent_task_id == "abc"


class TestTaskRequestPathSafety:
    def test_relative_repository_root_is_rejected(self, valid_request_dict):
        payload = dict(valid_request_dict)
        payload["repository"] = {"root": "relative/path"}
        with pytest.raises(ValidationError, match="absolute"):
            TaskRequest(**payload)

    @pytest.mark.parametrize(
        "pattern", ["/etc/**", "../outside/**", "src/../../etc/**", "~/secrets/**"]
    )
    def test_unsafe_scope_patterns_are_rejected(self, valid_request_dict, pattern):
        payload = dict(valid_request_dict)
        payload["scope"] = {"allowed_paths": [pattern]}
        with pytest.raises(ValidationError):
            TaskRequest(**payload)

    def test_forbidden_paths_are_validated_too(self, valid_request_dict):
        payload = dict(valid_request_dict)
        payload["scope"] = {"forbidden_paths": ["../elsewhere/**"]}
        with pytest.raises(ValidationError):
            TaskRequest(**payload)


class TestRoutingNeverSelectsFable:
    """§10: never automatically route implementation to Fable."""

    def test_fable_cannot_be_requested_as_implementation_model(self, valid_request_dict):
        payload = dict(valid_request_dict)
        payload["routing"] = {"model": "fable"}
        with pytest.raises(ValidationError):
            TaskRequest(**payload)

    def test_only_auto_sonnet_opus_are_requestable(self, valid_request_dict):
        from sol_claude_dispatcher.models import RequestedModel

        assert {m.value for m in RequestedModel} == {"auto", "sonnet", "opus"}


# ---------------------------------------------------------------------------
# ValidationCommand — §9 structured argv, never a shell string
# ---------------------------------------------------------------------------


class TestValidationCommand:
    def test_accepts_structured_argv(self):
        cmd = ValidationCommand(argv=["pytest", "-q"], timeout_seconds=600)
        assert cmd.argv == ["pytest", "-q"]

    def test_empty_argv_is_rejected(self):
        with pytest.raises(ValidationError):
            ValidationCommand(argv=[])

    @pytest.mark.parametrize("shell", ["sh", "bash", "zsh", "dash", "fish"])
    def test_shell_interpreters_are_rejected(self, shell):
        with pytest.raises(ValidationError, match="shell"):
            ValidationCommand(argv=[shell, "-c", "rm -rf /"])

    def test_there_is_no_shell_field_to_set(self):
        with pytest.raises(ValidationError):
            ValidationCommand(argv=["pytest"], shell=True)

    def test_timeout_must_be_positive_and_bounded(self):
        with pytest.raises(ValidationError):
            ValidationCommand(argv=["pytest"], timeout_seconds=0)
        with pytest.raises(ValidationError):
            ValidationCommand(argv=["pytest"], timeout_seconds=999_999)


# ---------------------------------------------------------------------------
# TaskEnvelope — dispatcher truth
# ---------------------------------------------------------------------------


class TestTaskEnvelope:
    def _envelope(self, request, **kw):
        return TaskEnvelope.from_request(
            request,
            canonical_root="/tmp/canonical/repo",
            base_commit="a" * 40,
            **kw,
        )

    def test_from_request_generates_internal_fields(self, valid_request_dict):
        env = self._envelope(TaskRequest(**valid_request_dict))
        assert env.schema_version == SCHEMA_VERSION
        assert env.task_id
        assert env.repository.base_commit == "a" * 40
        assert env.repository.root == "/tmp/canonical/repo"
        assert env.lineage.dispatch_depth == 0
        assert isinstance(env.created_at, datetime)

    def test_caller_scope_and_criteria_are_carried_through_unchanged(
        self, valid_request_dict
    ):
        req = TaskRequest(**valid_request_dict)
        env = self._envelope(req)
        assert env.scope.allowed_paths == req.scope.allowed_paths
        assert env.task.acceptance_criteria == req.task.acceptance_criteria

    def test_worktree_name_derives_from_task_id(self, valid_request_dict):
        env = self._envelope(TaskRequest(**valid_request_dict))
        assert env.worktree_name == worktree_name_for(env.task_id)
        assert WORKTREE_NAME_RE.fullmatch(env.worktree_name)

    def test_worktree_name_never_contains_user_text(self, valid_request_dict):
        payload = dict(valid_request_dict)
        payload["task"] = {**payload["task"], "objective": "rm -rf / ; evil name"}
        env = self._envelope(TaskRequest(**payload))
        assert WORKTREE_NAME_RE.fullmatch(env.worktree_name)
        assert "evil" not in env.worktree_name

    def test_mismatched_worktree_name_is_rejected(self, valid_request_dict):
        env = self._envelope(TaskRequest(**valid_request_dict))
        data = env.model_dump()
        data["worktree_name"] = "sol-deadbeef"
        with pytest.raises(ValidationError, match="does not derive"):
            TaskEnvelope(**data)

    def test_malformed_worktree_name_is_rejected(self, valid_request_dict):
        env = self._envelope(TaskRequest(**valid_request_dict))
        data = env.model_dump()
        data["worktree_name"] = "../escape"
        with pytest.raises(ValidationError):
            TaskEnvelope(**data)

    def test_schema_version_is_required_not_defaulted(self, valid_request_dict):
        """§27: an unversioned envelope fails closed rather than being guessed."""
        env = self._envelope(TaskRequest(**valid_request_dict))
        data = env.model_dump()
        del data["schema_version"]
        with pytest.raises(ValidationError) as exc:
            TaskEnvelope(**data)
        assert "schema_version" in str(exc.value)

    def test_wrong_schema_version_is_rejected(self, valid_request_dict):
        env = self._envelope(TaskRequest(**valid_request_dict))
        data = env.model_dump()
        data["schema_version"] = "2.0"
        with pytest.raises(ValidationError):
            TaskEnvelope(**data)

    def test_base_commit_must_look_like_a_sha(self, valid_request_dict):
        with pytest.raises(ValidationError):
            TaskEnvelope.from_request(
                TaskRequest(**valid_request_dict),
                canonical_root="/tmp/repo",
                base_commit="not-a-sha",
            )

    def test_round_trips_through_json(self, valid_request_dict):
        env = self._envelope(TaskRequest(**valid_request_dict))
        restored = TaskEnvelope.model_validate_json(env.model_dump_json())
        assert restored == env

    def test_lineage_records_escalation(self, valid_request_dict):
        env = self._envelope(
            TaskRequest(**valid_request_dict),
            previous_session_id="prev-session",
            escalation_reason="Sonnet could not resolve the race condition.",
        )
        assert env.lineage.previous_session_id == "prev-session"
        assert "race condition" in env.lineage.escalation_reason


class TestIdentityHelpers:
    def test_task_ids_are_unique(self):
        assert len({new_task_id() for _ in range(200)}) == 200

    def test_session_id_is_a_uuid(self):
        import uuid

        uuid.UUID(new_session_id())  # raises if malformed

    def test_short_task_id_is_eight_hex_chars(self):
        tid = new_task_id()
        short = short_task_id(tid)
        assert len(short) == 8
        assert all(c in "0123456789abcdef" for c in short)

    def test_short_task_id_rejects_non_hex_input(self):
        with pytest.raises(ValueError):
            short_task_id("not-a-task-id-at-all!!")

    def test_utc_now_is_timezone_aware(self):
        assert utc_now().tzinfo is not None


# ---------------------------------------------------------------------------
# TaskState machine — §26
# ---------------------------------------------------------------------------


class TestTaskStateEnum:
    EXPECTED = {
        "CREATED",
        "ROUTED",
        "RUNNING",
        "IMPLEMENTED",
        "AWAITING_SOL_REVIEW",
        "FABLE_REVIEWED",
        "RESUME_REQUESTED",
        "REVIEW_COMPLETE",
        "TIMED_OUT",
        "BLOCKED",
        "FAILED",
        "POLICY_VIOLATION",
    }

    def test_every_state_from_the_brief_exists(self):
        assert {s.name for s in TaskState} == self.EXPECTED

    def test_there_is_no_approved_state(self):
        """§26/§41: the dispatcher must never decide APPROVED."""
        names = {s.name for s in TaskState}
        assert "APPROVED" not in names
        assert "USER_APPROVED" not in names
        assert "ACCEPTED" not in names

    def test_states_serialise_as_strings(self):
        assert TaskState.POLICY_VIOLATION.value == "policy_violation"
        assert json.dumps({"s": TaskState.RUNNING.value}) == '{"s": "running"}'


class TestTransitionTable:
    def test_every_state_has_an_entry(self):
        assert set(ALLOWED_TRANSITIONS) == set(TaskState)

    def test_every_target_is_a_real_state(self):
        for src, targets in ALLOWED_TRANSITIONS.items():
            for dst in targets:
                assert isinstance(dst, TaskState), (src, dst)

    def test_no_state_transitions_to_itself(self):
        for src, targets in ALLOWED_TRANSITIONS.items():
            assert src not in targets

    def test_the_happy_path_from_the_brief_is_walkable(self):
        path = [
            TaskState.CREATED,
            TaskState.ROUTED,
            TaskState.RUNNING,
            TaskState.IMPLEMENTED,
            TaskState.AWAITING_SOL_REVIEW,
            TaskState.FABLE_REVIEWED,
            TaskState.RESUME_REQUESTED,
            TaskState.RUNNING,
        ]
        for src, dst in zip(path, path[1:]):
            assert is_transition_allowed(src, dst), f"{src} -> {dst}"

    def test_running_can_reach_every_off_ramp(self):
        for off_ramp in (
            TaskState.TIMED_OUT,
            TaskState.BLOCKED,
            TaskState.FAILED,
            TaskState.POLICY_VIOLATION,
        ):
            assert is_transition_allowed(TaskState.RUNNING, off_ramp)

    def test_off_ramps_cannot_jump_straight_back_to_running(self):
        """A resume must pass through RESUME_REQUESTED so the cap is consulted."""
        for off_ramp in (
            TaskState.TIMED_OUT,
            TaskState.BLOCKED,
            TaskState.POLICY_VIOLATION,
        ):
            assert not is_transition_allowed(off_ramp, TaskState.RUNNING)
            assert is_transition_allowed(off_ramp, TaskState.RESUME_REQUESTED)

    def test_failed_is_not_a_dead_end(self):
        """A FAILED run keeps its session id and worktree, so Sol may correct it.

        Malformed structured output and a non-zero worker exit both land here
        with everything a resume needs still on disk. Making FAILED terminal in
        practice would strand exactly the recoverable cases; the resume still
        goes through RESUME_REQUESTED so the cap is consulted in one place.
        """
        assert is_transition_allowed(TaskState.FAILED, TaskState.RESUME_REQUESTED)
        assert is_transition_allowed(TaskState.FAILED, TaskState.AWAITING_SOL_REVIEW)
        assert not is_transition_allowed(TaskState.FAILED, TaskState.RUNNING)
        assert TaskState.FAILED not in TERMINAL_STATES

    def test_all_four_off_ramps_offer_the_same_choices(self):
        """TIMED_OUT / BLOCKED / FAILED / POLICY_VIOLATION are structurally equal."""
        for off_ramp in (
            TaskState.TIMED_OUT,
            TaskState.BLOCKED,
            TaskState.FAILED,
            TaskState.POLICY_VIOLATION,
        ):
            targets = ALLOWED_TRANSITIONS[off_ramp]
            assert TaskState.AWAITING_SOL_REVIEW in targets, off_ramp
            assert TaskState.RESUME_REQUESTED in targets, off_ramp
            assert TaskState.RUNNING not in targets, off_ramp

    def test_review_complete_is_terminal(self):
        assert ALLOWED_TRANSITIONS[TaskState.REVIEW_COMPLETE] == frozenset()
        assert TaskState.REVIEW_COMPLETE in TERMINAL_STATES

    @pytest.mark.parametrize(
        "src,dst",
        [
            (TaskState.CREATED, TaskState.RUNNING),
            (TaskState.CREATED, TaskState.IMPLEMENTED),
            (TaskState.ROUTED, TaskState.IMPLEMENTED),
            (TaskState.RUNNING, TaskState.REVIEW_COMPLETE),
            (TaskState.IMPLEMENTED, TaskState.REVIEW_COMPLETE),
            (TaskState.REVIEW_COMPLETE, TaskState.RUNNING),
            (TaskState.POLICY_VIOLATION, TaskState.IMPLEMENTED),
        ],
    )
    def test_illegal_shortcuts_are_refused(self, src, dst):
        assert not is_transition_allowed(src, dst)


class TestEscalatingKinds:
    def test_brief_kinds_all_escalate(self):
        names = {k.value for k in ESCALATING_TASK_KINDS}
        assert names == {
            "security_sensitive",
            "concurrency",
            "migration",
            "deep_debugging",
            "large_refactor",
        }


# ---------------------------------------------------------------------------
# WorkerResult — claims
# ---------------------------------------------------------------------------


class TestWorkerResult:
    MINIMAL = {"status": "completed", "summary": "Did the thing."}

    def test_minimal_result_validates(self):
        r = WorkerResult(**self.MINIMAL)
        assert r.needs_review is True
        assert r.changes == []

    def test_full_result_validates(self):
        r = WorkerResult(
            status="completed",
            summary="Implemented atomic deploy.",
            changes=[
                ChangedFile(path="src/deploy/atomic.py", type="added", description="x")
            ],
            acceptance_criteria=[
                AcceptanceCriterionResult(
                    criterion="Deployment must be atomic.",
                    status="satisfied",
                    evidence="tests/test_atomic.py::test_interrupt",
                )
            ],
            tests=[TestReport(command="pytest -q", status="passed", exit_code=0)],
            risks=["Symlink handling on exotic filesystems is untested."],
            blockers=[],
            needs_review=True,
        )
        assert r.tests[0].exit_code == 0

    def test_missing_required_field_is_rejected(self):
        with pytest.raises(ValidationError):
            WorkerResult(status="completed")

    def test_unknown_field_is_rejected(self):
        with pytest.raises(ValidationError):
            WorkerResult(**self.MINIMAL, tests_passed=341)

    def test_unknown_status_is_rejected(self):
        with pytest.raises(ValidationError):
            WorkerResult(status="approved", summary="x")

    def test_worker_cannot_declare_itself_approved(self):
        """There is no field through which a worker can grant approval."""
        fields = set(WorkerResult.model_fields)
        assert not any("approv" in f for f in fields)

    def test_empty_summary_is_rejected(self):
        with pytest.raises(ValidationError):
            WorkerResult(status="completed", summary="")

    def test_changed_file_type_is_constrained(self):
        with pytest.raises(ValidationError):
            ChangedFile(path="a.py", type="mangled")

    def test_model_matches_the_published_json_schema(self):
        schema = json.loads(
            (SCHEMAS_DIR / "worker-result.schema.json").read_text()
        )
        assert set(schema["properties"]) == set(WorkerResult.model_fields)
        assert schema["additionalProperties"] is False


# ---------------------------------------------------------------------------
# FableReview — advisory
# ---------------------------------------------------------------------------


class TestFableReview:
    MINIMAL = {"verdict": "approve", "recommended_next_action": "accept"}

    def test_minimal_review_validates(self):
        r = FableReview(**self.MINIMAL)
        assert r.findings == []

    def test_finding_shape_from_the_brief(self):
        r = FableReview(
            verdict="changes_required",
            findings=[
                {
                    "id": "F1",
                    "severity": "high",
                    "category": "correctness",
                    "path": "src/example.py",
                    "line": 91,
                    "finding": "Partial write is not rolled back.",
                    "evidence": "os.replace is skipped on the error branch.",
                    "recommendation": "Wrap in try/finally and unlink the temp file.",
                }
            ],
            missing_tests=["interrupted deploy"],
            architecture_notes=[],
            recommended_next_action="resume_worker",
        )
        assert r.findings[0].id == "F1"
        assert r.findings[0].line == 91

    def test_unknown_verdict_is_rejected(self):
        with pytest.raises(ValidationError):
            FableReview(verdict="lgtm", recommended_next_action="accept")

    def test_unknown_field_is_rejected(self):
        with pytest.raises(ValidationError):
            FableReview(**self.MINIMAL, patch="--- a/x.py")

    def test_reviewer_cannot_supply_a_patch_or_edit(self):
        """Fable reports; it never implements. No field carries a change."""
        fields = set(FableReview.model_fields)
        assert not (fields & {"patch", "diff", "changes", "edits", "fix"})

    def test_line_must_be_positive(self):
        with pytest.raises(ValidationError):
            FableReview(
                verdict="approve",
                recommended_next_action="accept",
                findings=[
                    {
                        "id": "F1",
                        "severity": "low",
                        "category": "tests",
                        "finding": "x",
                        "line": 0,
                    }
                ],
            )

    def test_model_matches_the_published_json_schema(self):
        schema = json.loads((SCHEMAS_DIR / "fable-review.schema.json").read_text())
        assert set(schema["properties"]) == set(FableReview.model_fields)
        assert schema["additionalProperties"] is False


# ---------------------------------------------------------------------------
# §16 — claims and observations must stay separate types
# ---------------------------------------------------------------------------


class TestClaimsVersusObservations:
    def test_the_two_types_share_no_field_names(self):
        """§16 calls this distinction fundamental. Enforce it mechanically."""
        overlap = set(WorkerResult.model_fields) & set(
            DispatcherObservations.model_fields
        )
        assert overlap == set(), f"claim/observation field collision: {overlap}"

    def test_run_record_keeps_them_in_labelled_slots(self):
        meta = RunMetadata(
            run_id="abc123",
            run_index=1,
            task_id="t1",
            kind=RunKind.DISPATCH,
            role=WorkerRole.IMPLEMENTER,
            model="sonnet",
            session_id=new_session_id(),
            started_at=utc_now(),
        )
        record = RunRecord(
            metadata=meta,
            worker_claims=WorkerResult(status="completed", summary="done"),
            dispatcher_observations=DispatcherObservations(
                task_id="t1",
                run_id="abc123",
                session_id=meta.session_id,
                model="sonnet",
                base_commit="b" * 40,
                duration_ms=1234,
                exit_code=0,
            ),
        )
        assert record.worker_claims.summary == "done"
        assert record.dispatcher_observations.exit_code == 0
        dumped = record.model_dump()
        assert "worker_claims" in dumped and "dispatcher_observations" in dumped

    def test_a_run_can_have_observations_without_claims(self):
        """Timeout and malformed output both leave evidence but no claim (§20)."""
        meta = RunMetadata(
            run_id="r2",
            run_index=2,
            task_id="t1",
            kind=RunKind.RESUME,
            role=WorkerRole.IMPLEMENTER,
            model="opus",
            session_id=new_session_id(),
            started_at=utc_now(),
            timed_out=True,
        )
        record = RunRecord(
            metadata=meta,
            dispatcher_observations=DispatcherObservations(
                task_id="t1",
                run_id="r2",
                session_id=meta.session_id,
                model="opus",
                base_commit="c" * 40,
                duration_ms=1800_000,
                timed_out=True,
                worker_result_parsed=False,
                worker_result_error="process terminated before producing output",
            ),
        )
        assert record.worker_claims is None
        assert record.dispatcher_observations.timed_out is True

    def test_observations_reject_unknown_fields(self):
        with pytest.raises(ValidationError):
            DispatcherObservations(
                task_id="t",
                run_id="r",
                session_id="s",
                model="sonnet",
                base_commit="d" * 40,
                duration_ms=1,
                tests_passed=341,
            )


class TestValidationResult:
    def test_source_is_pinned_to_dispatcher(self):
        """§17: a worker can never contribute a validation result."""
        r = ValidationResult(argv=["pytest", "-q"], passed=True, duration_ms=10)
        assert r.source == "dispatcher"
        with pytest.raises(ValidationError):
            ValidationResult(
                argv=["pytest"], passed=True, duration_ms=1, source="worker"
            )

    def test_argv_must_be_non_empty(self):
        with pytest.raises(ValidationError):
            ValidationResult(argv=[], passed=True, duration_ms=1)

    def test_records_failure_faithfully(self):
        r = ValidationResult(
            argv=["pytest", "-q"],
            exit_code=1,
            passed=False,
            duration_ms=900,
            stdout_tail="1 failed",
        )
        assert r.passed is False and r.exit_code == 1


class TestRunMetadata:
    def test_completion_fields_are_optional_so_a_record_exists_before_the_run(self):
        meta = RunMetadata(
            run_id="r1",
            run_index=1,
            task_id="t1",
            kind=RunKind.DISPATCH,
            role=WorkerRole.IMPLEMENTER,
            model="sonnet",
            session_id=new_session_id(),
            started_at=utc_now(),
        )
        assert meta.finished_at is None
        assert meta.exit_code is None
        assert meta.timed_out is False

    def test_run_index_starts_at_one(self):
        with pytest.raises(ValidationError):
            RunMetadata(
                run_id="r",
                run_index=0,
                task_id="t",
                kind=RunKind.DISPATCH,
                role=WorkerRole.IMPLEMENTER,
                model="sonnet",
                session_id=new_session_id(),
                started_at=utc_now(),
            )


# ---------------------------------------------------------------------------
# Error taxonomy — §29
# ---------------------------------------------------------------------------


class TestErrorTaxonomy:
    def _all_subclasses(self, cls):
        out = set()
        for sub in cls.__subclasses__():
            out.add(sub)
            out |= self._all_subclasses(sub)
        return out

    def test_every_error_from_the_brief_exists(self):
        required = {
            "InvalidRepository",
            "RepositoryNotAllowed",
            "RepositoryBusy",
            "InvalidTaskEnvelope",
            "InvalidStateTransition",
            "ClaudeBinaryNotFound",
            "ClaudeExecutionFailed",
            "ClaudeStructuredOutputInvalid",
            "ClaudeTimedOut",
            "ResumeLimitReached",
            "PolicyViolation",
            "ValidationFailed",
            "WorktreeCreationFailed",
            "RecursionDetected",
            "ConfigurationError",
        }
        assert required <= {c.__name__ for c in self._all_subclasses(errors.DispatcherError)}

    def test_error_codes_constant_is_in_sync(self):
        actual = {c.__name__ for c in self._all_subclasses(errors.DispatcherError)}
        actual.add("DispatcherError")
        assert actual == set(errors.ERROR_CODES)

    def test_code_attribute_matches_class_name(self):
        for cls in self._all_subclasses(errors.DispatcherError):
            assert cls.code == cls.__name__

    def test_payload_is_concise_and_structured(self):
        err = errors.RepositoryNotAllowed(
            "Repository is outside the configured allowlist.",
            details={"root": "/etc"},
            remediation="Add it to allowed_repository_roots.",
        )
        payload = err.to_payload()
        assert payload["error"] == "RepositoryNotAllowed"
        assert payload["details"] == {"root": "/etc"}
        assert payload["remediation"]
        assert "Traceback" not in json.dumps(payload)

    def test_repository_busy_is_the_retryable_one(self):
        assert errors.RepositoryBusy("busy").retryable is True
        assert errors.PolicyViolation("nope").retryable is False

    def test_payload_omits_empty_optional_keys(self):
        payload = errors.ConfigurationError("Broken.").to_payload()
        assert "details" not in payload
        assert "remediation" not in payload
