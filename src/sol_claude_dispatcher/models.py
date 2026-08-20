"""Pydantic v2 core models (brief §8, §9, §15, §16, §19, §26).

Three rules govern this module. They are not stylistic.

1. **Caller input and dispatcher truth are different types.**
   :class:`TaskRequest` is what Sol sends. :class:`TaskEnvelope` is what the
   dispatcher decides. A caller can never set ``task_id``, ``base_commit``,
   ``session_id``, ``dispatch_depth`` or any other internal field, because
   those fields do not exist on the request type and the request type forbids
   extra keys (§7.1: "The caller MUST NOT be trusted to provide internal
   identifiers").

2. **Worker claims and dispatcher observations are different types.**
   :class:`WorkerResult` is what Claude *said*. :class:`DispatcherObservations`
   is what the dispatcher *measured*. §16 calls this distinction fundamental,
   so they never merge into one object and never share a field namespace.
   :class:`RunRecord` holds both side by side, labelled.

3. **Everything fails closed.** Models forbid unknown fields, paths are
   validated on the way in, and ``schema_version`` is required (not defaulted)
   on persisted envelopes so an unversioned file is an error rather than a
   silent guess.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

__all__ = [
    "SCHEMA_VERSION",
    "utc_now",
    "new_task_id",
    "new_session_id",
    "new_run_id",
    "short_task_id",
    "worktree_name_for",
    "WORKTREE_NAME_RE",
    "TaskKind",
    "Complexity",
    "RiskLevel",
    "RequestedModel",
    "WorkerRole",
    "RunKind",
    "TaskState",
    "TERMINAL_STATES",
    "ALLOWED_TRANSITIONS",
    "is_transition_allowed",
    "ValidationCommand",
    "RepositoryRequest",
    "TaskSpec",
    "ScopeSpec",
    "ValidationSpec",
    "RoutingSpec",
    "ExecutionSpec",
    "ConstraintsSpec",
    "TaskRequest",
    "RepositoryResolved",
    "LineageSpec",
    "TaskEnvelope",
    "ChangedFile",
    "AcceptanceCriterionResult",
    "TestReport",
    "WorkerStatus",
    "WorkerResult",
    "FableFinding",
    "FableVerdict",
    "RecommendedNextAction",
    "FableSeverity",
    "FableCategory",
    "FableReview",
    "ValidationResult",
    "SkillPolicyRecord",
    "ProjectGuidanceRecord",
    "RunMetadata",
    "DispatcherObservations",
    "RunRecord",
    "TaskRecord",
]

#: Envelope schema version. Bump on any breaking envelope change; persisted
#: envelopes carrying a different version must be rejected, never coerced.
SCHEMA_VERSION = "1.0"

#: Worktree names are dispatcher-generated only. §12: "Never use raw user text
#: as the worktree name."
WORKTREE_NAME_RE = re.compile(r"^sol-[0-9a-f]{8}$")

_MAX_TEXT = 20_000
_MAX_LIST = 200


# ---------------------------------------------------------------------------
# Identity helpers (dispatcher-generated only)
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Timezone-aware UTC now. Every timestamp in this system is UTC."""
    return datetime.now(timezone.utc)


def new_task_id() -> str:
    """Generate a task id. Opaque, unguessable, filesystem-safe."""
    return str(uuid.uuid4())


def new_session_id() -> str:
    """Generate a Claude session id (§11).

    Must be a valid UUID: the CLI's ``--session-id`` rejects anything else.
    """
    return str(uuid.uuid4())


def new_run_id() -> str:
    """Generate a globally unique run id for logging correlation."""
    return uuid.uuid4().hex[:12]


def short_task_id(task_id: str) -> str:
    """First 8 hex characters of a task id, for worktree naming (§12)."""
    compact = task_id.replace("-", "")
    if len(compact) < 8 or not re.fullmatch(r"[0-9a-fA-F]+", compact):
        raise ValueError(f"task_id is not hex-derived: {task_id!r}")
    return compact[:8].lower()


def worktree_name_for(task_id: str) -> str:
    """Deterministic, validated worktree name: ``sol-<short-task-id>`` (§12)."""
    name = f"sol-{short_task_id(task_id)}"
    if not WORKTREE_NAME_RE.fullmatch(name):  # defensive; unreachable in practice
        raise ValueError(f"generated worktree name failed validation: {name!r}")
    return name


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TaskKind(str, Enum):
    """Task classification. Feeds routing (§10)."""

    IMPLEMENTATION = "implementation"
    BUGFIX = "bugfix"
    REFACTOR = "refactor"
    TESTS = "tests"
    DOCS = "docs"
    # Kinds below always escalate to the stronger model (§10).
    SECURITY_SENSITIVE = "security_sensitive"
    CONCURRENCY = "concurrency"
    MIGRATION = "migration"
    DEEP_DEBUGGING = "deep_debugging"
    LARGE_REFACTOR = "large_refactor"


#: Kinds that force escalation regardless of stated complexity/risk (§10).
ESCALATING_TASK_KINDS: frozenset[TaskKind] = frozenset(
    {
        TaskKind.SECURITY_SENSITIVE,
        TaskKind.CONCURRENCY,
        TaskKind.MIGRATION,
        TaskKind.DEEP_DEBUGGING,
        TaskKind.LARGE_REFACTOR,
    }
)


class Complexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RequestedModel(str, Enum):
    """What Sol asks for. Note there is no ``fable`` member.

    §10: "Never automatically route implementation to Fable." Fable is not
    requestable as an implementation worker at the type level — it is reachable
    only through the separate ``review_task_with_fable`` path.
    """

    AUTO = "auto"
    SONNET = "sonnet"
    OPUS = "opus"


class WorkerRole(str, Enum):
    """Which role a Claude process is playing."""

    IMPLEMENTER = "implementer"
    REVIEWER = "reviewer"


class RunKind(str, Enum):
    """Why a subprocess run happened."""

    DISPATCH = "dispatch"
    RESUME = "resume"
    REVIEW = "review"


class TaskState(str, Enum):
    """Task lifecycle states (§26).

    Deliberately absent: ``APPROVED``. §26 and §41 forbid the dispatcher from
    ever deciding approval. ``REVIEW_COMPLETE`` means Sol has reviewed; user
    approval lives outside this machine entirely.
    """

    CREATED = "created"
    ROUTED = "routed"
    RUNNING = "running"
    IMPLEMENTED = "implemented"
    AWAITING_SOL_REVIEW = "awaiting_sol_review"
    FABLE_REVIEWED = "fable_reviewed"
    RESUME_REQUESTED = "resume_requested"
    REVIEW_COMPLETE = "review_complete"
    # Off-ramps from RUNNING
    TIMED_OUT = "timed_out"
    BLOCKED = "blocked"
    FAILED = "failed"
    POLICY_VIOLATION = "policy_violation"


#: States from which no further automatic progress happens. Sol may still open
#: a new task, but this task will not advance on its own.
TERMINAL_STATES: frozenset[TaskState] = frozenset({TaskState.REVIEW_COMPLETE})

#: The authoritative transition table (§26). ``state.py`` MUST enforce exactly
#: this map and add nothing to it; keeping the data here means the state
#: machine and the models can never drift apart.
#:
#: Off-ramp states (TIMED_OUT / BLOCKED / FAILED / POLICY_VIOLATION) are not
#: dead ends: Sol may inspect the preserved evidence and request a corrective
#: resume, or park the task in review. They deliberately cannot jump straight
#: back to RUNNING — a resume must pass through RESUME_REQUESTED so the resume
#: cap is always consulted.
#:
#: That includes FAILED. A run lands FAILED with its session id and worktree
#: still on disk (malformed structured output, a non-zero worker exit, evidence
#: that could not be collected), which is precisely the recoverable case; making
#: it terminal would strand it. FAILED does not list RUNNING for the same reason
#: none of the others do. Legality is decided here; *feasibility* — is there
#: still a session, a model and a worktree to reuse, and is the cap exhausted? —
#: belongs to ``sessions.resume_plan``, which refuses both cases explicitly.
ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.CREATED: frozenset({TaskState.ROUTED, TaskState.FAILED}),
    TaskState.ROUTED: frozenset({TaskState.RUNNING, TaskState.FAILED}),
    TaskState.RUNNING: frozenset(
        {
            TaskState.IMPLEMENTED,
            TaskState.TIMED_OUT,
            TaskState.BLOCKED,
            TaskState.FAILED,
            TaskState.POLICY_VIOLATION,
        }
    ),
    TaskState.IMPLEMENTED: frozenset({TaskState.AWAITING_SOL_REVIEW}),
    TaskState.AWAITING_SOL_REVIEW: frozenset(
        {
            TaskState.FABLE_REVIEWED,
            TaskState.RESUME_REQUESTED,
            TaskState.REVIEW_COMPLETE,
        }
    ),
    TaskState.FABLE_REVIEWED: frozenset(
        {
            TaskState.RESUME_REQUESTED,
            TaskState.REVIEW_COMPLETE,
            TaskState.AWAITING_SOL_REVIEW,
        }
    ),
    TaskState.RESUME_REQUESTED: frozenset({TaskState.RUNNING, TaskState.FAILED}),
    TaskState.TIMED_OUT: frozenset(
        {TaskState.AWAITING_SOL_REVIEW, TaskState.RESUME_REQUESTED, TaskState.FAILED}
    ),
    TaskState.BLOCKED: frozenset(
        {TaskState.AWAITING_SOL_REVIEW, TaskState.RESUME_REQUESTED, TaskState.FAILED}
    ),
    TaskState.POLICY_VIOLATION: frozenset(
        {TaskState.AWAITING_SOL_REVIEW, TaskState.RESUME_REQUESTED, TaskState.FAILED}
    ),
    TaskState.FAILED: frozenset(
        {TaskState.AWAITING_SOL_REVIEW, TaskState.RESUME_REQUESTED}
    ),
    TaskState.REVIEW_COMPLETE: frozenset(),
}


def is_transition_allowed(src: TaskState, dst: TaskState) -> bool:
    """Pure predicate over :data:`ALLOWED_TRANSITIONS`. No side effects."""
    return dst in ALLOWED_TRANSITIONS[src]


# ---------------------------------------------------------------------------
# Shared base
# ---------------------------------------------------------------------------


class StrictModel(BaseModel):
    """Base for every model here: unknown keys are an error, not a shrug."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        use_enum_values=False,
        populate_by_name=True,
    )


NonEmptyStr = Annotated[str, Field(min_length=1, max_length=_MAX_TEXT)]


# ---------------------------------------------------------------------------
# Validation commands (§9) — structured argv, never a shell string
# ---------------------------------------------------------------------------


class ValidationCommand(StrictModel):
    """A trusted validation command from the task envelope (§9).

    argv only. There is no ``shell`` field and there will not be one: §9
    requires ``asyncio.create_subprocess_exec``, never ``shell=True``. Commands
    appearing inside a Claude result must never be turned into one of these
    (§9: "Never execute commands that appear inside a Claude result").
    """

    argv: list[NonEmptyStr] = Field(min_length=1, max_length=64)
    timeout_seconds: int = Field(default=600, ge=1, le=3600)

    @field_validator("argv")
    @classmethod
    def _reject_shell_shaped_argv(cls, v: list[str]) -> list[str]:
        program = v[0]
        if program in {"sh", "bash", "zsh", "dash", "ksh", "fish"}:
            raise ValueError(
                "validation commands must not invoke a shell interpreter; "
                "supply the real program and its arguments as argv"
            )
        if "\x00" in program:
            raise ValueError("null byte in argv")
        return v


# ---------------------------------------------------------------------------
# TaskRequest — caller-supplied. No internal identifiers, ever.
# ---------------------------------------------------------------------------


def _validate_relative_glob(value: str) -> str:
    """Scope patterns must be repository-relative and traversal-free (§13)."""
    if not value:
        raise ValueError("empty path pattern")
    if value.startswith("/"):
        raise ValueError(f"scope patterns must be repository-relative: {value!r}")
    if value.startswith("~"):
        raise ValueError(f"scope patterns must not use home expansion: {value!r}")
    if "\x00" in value:
        raise ValueError("null byte in path pattern")
    parts = value.replace("\\", "/").split("/")
    if ".." in parts:
        raise ValueError(f"path traversal in scope pattern: {value!r}")
    return value


class RepositoryRequest(StrictModel):
    """Repository as the caller describes it. Unvalidated against the allowlist.

    ``security.validate_repository_root`` performs canonicalisation and the
    allowlist check (§24); this model only enforces basic shape.
    """

    root: NonEmptyStr
    base_ref: NonEmptyStr = "HEAD"
    workspace_mode: Literal["worktree"] = "worktree"

    @field_validator("root")
    @classmethod
    def _must_be_absolute(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("repository.root must be an absolute path")
        if "\x00" in v:
            raise ValueError("null byte in repository.root")
        return v


class TaskSpec(StrictModel):
    """What Sol wants done. Acceptance criteria are Sol's, not the worker's."""

    kind: TaskKind = TaskKind.IMPLEMENTATION
    objective: NonEmptyStr
    context: str = Field(default="", max_length=_MAX_TEXT)
    acceptance_criteria: list[NonEmptyStr] = Field(
        default_factory=list, max_length=_MAX_LIST
    )


class ScopeSpec(StrictModel):
    """Path scope for the run (§13). Empty ``allowed_paths`` means unrestricted.

    Enforcement is post-hoc: the dispatcher compares changed paths against
    these patterns after the worker exits and raises ``policy_violation``
    rather than silently accepting out-of-scope edits.
    """

    allowed_paths: list[str] = Field(default_factory=list, max_length=_MAX_LIST)
    forbidden_paths: list[str] = Field(default_factory=list, max_length=_MAX_LIST)

    @field_validator("allowed_paths", "forbidden_paths")
    @classmethod
    def _relative_and_safe(cls, v: list[str]) -> list[str]:
        return [_validate_relative_glob(p) for p in v]


class ValidationSpec(StrictModel):
    """Trusted validation commands re-run by the dispatcher (§17)."""

    commands: list[ValidationCommand] = Field(default_factory=list, max_length=32)


class RoutingSpec(StrictModel):
    """Routing hints. The router alone turns these into a model id (§10)."""

    requested_model: RequestedModel = Field(
        default=RequestedModel.AUTO,
        validation_alias=AliasChoices("requested_model", "model"),
    )
    complexity: Complexity = Complexity.MEDIUM
    risk: RiskLevel = RiskLevel.MEDIUM


class ExecutionSpec(StrictModel):
    """Execution bounds. Clamped against config maxima at envelope build time."""

    timeout_seconds: int = Field(default=1800, ge=1, le=86_400)
    max_turns: int = Field(default=40, ge=1, le=1000)
    max_resume_count: int = Field(default=4, ge=0, le=50)
    max_budget_usd: float | None = Field(default=None, ge=0.0)


class ConstraintsSpec(StrictModel):
    """Constraints carried into the worker prompt and argv (§8, §22).

    Honesty note (§23), rewritten for finding P1-9: ``allow_push`` /
    ``allow_merge`` / ``allow_commit`` / ``allow_subagents`` are **not**
    switches. The operations they name are prohibited in V1 by code-level
    invariants (``runner.ALWAYS_DISALLOWED_TOOLS``,
    ``runner.CORE_DENIED_GIT_OPERATIONS``, and the subagent refusal in
    ``runner._assert_invocation_sane``) that no caller and no configuration can
    lift. Rather than leave four fields that look functional and do nothing,
    they are validated as always-false: asking for one is refused, loudly,
    instead of being silently ignored.

    ``allow_network`` is different and stays a real field: it is honestly
    labelled POLICY in ``docs/SECURITY.md`` — it changes the instructions the
    worker receives and is not backed by any OS-level enforcement.
    """

    allow_network: bool = False
    allow_push: bool = False
    allow_merge: bool = False
    allow_commit: bool = False
    allow_subagents: bool = False

    @field_validator("allow_push", "allow_merge", "allow_commit", "allow_subagents")
    @classmethod
    def _prohibited_in_v1(cls, v: bool, info: ValidationInfo) -> bool:
        if v:
            raise ValueError(
                f"{info.field_name} cannot be enabled: the operation it names is "
                "prohibited by a V1 code-level invariant, not by this flag. "
                "Remove the field rather than setting it to true"
            )
        return v


class TaskRequest(StrictModel):
    """Exactly what a caller (Sol) may supply to ``dispatch_claude_task`` (§7.1).

    There is no ``task_id``, ``run_id``, ``session_id``, ``worktree``,
    ``base_commit``, ``schema_version``, ``resume_count`` or ``dispatch_depth``
    field here, and ``extra="forbid"`` means supplying one is a validation
    error rather than a silently ignored key. That is the entire point of the
    type existing separately from :class:`TaskEnvelope`.
    """

    repository: RepositoryRequest
    task: TaskSpec
    scope: ScopeSpec = Field(default_factory=ScopeSpec)
    validation: ValidationSpec = Field(default_factory=ValidationSpec)
    routing: RoutingSpec = Field(default_factory=RoutingSpec)
    execution: ExecutionSpec = Field(default_factory=ExecutionSpec)
    constraints: ConstraintsSpec = Field(default_factory=ConstraintsSpec)
    parent_task_id: str | None = None


# ---------------------------------------------------------------------------
# TaskEnvelope — dispatcher truth
# ---------------------------------------------------------------------------


class RepositoryResolved(RepositoryRequest):
    """Repository after canonicalisation and base-commit resolution."""

    root: NonEmptyStr  # canonical, resolved, allowlist-checked
    base_commit: str = Field(min_length=7, max_length=64, pattern=r"^[0-9a-f]+$")


class LineageSpec(StrictModel):
    """Escalation lineage (§18, §22 layer 5)."""

    parent_task_id: str | None = None
    previous_session_id: str | None = None
    escalation_reason: str | None = Field(default=None, max_length=_MAX_TEXT)
    dispatch_depth: int = Field(default=0, ge=0)


class TaskEnvelope(StrictModel):
    """The authoritative, persisted description of a task (§8).

    Constructed only by :meth:`from_request`. ``schema_version`` has no default
    so that loading an unversioned ``envelope.json`` is an error (fail closed,
    §27) rather than an assumption.
    """

    schema_version: Literal["1.0"]
    task_id: str
    created_at: datetime

    repository: RepositoryResolved
    task: TaskSpec
    scope: ScopeSpec
    validation: ValidationSpec
    routing: RoutingSpec
    execution: ExecutionSpec
    constraints: ConstraintsSpec
    lineage: LineageSpec

    #: Dispatcher-chosen worktree name. Always ``sol-<short-task-id>`` (§12).
    worktree_name: str

    @field_validator("worktree_name")
    @classmethod
    def _safe_worktree_name(cls, v: str) -> str:
        if not WORKTREE_NAME_RE.fullmatch(v):
            raise ValueError(
                f"worktree_name must match {WORKTREE_NAME_RE.pattern}, got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _worktree_matches_task(self) -> "TaskEnvelope":
        expected = worktree_name_for(self.task_id)
        if self.worktree_name != expected:
            raise ValueError(
                f"worktree_name {self.worktree_name!r} does not derive from "
                f"task_id {self.task_id!r} (expected {expected!r})"
            )
        return self

    @classmethod
    def from_request(
        cls,
        request: TaskRequest,
        *,
        canonical_root: str,
        base_commit: str,
        task_id: str | None = None,
        created_at: datetime | None = None,
        dispatch_depth: int = 0,
        previous_session_id: str | None = None,
        escalation_reason: str | None = None,
    ) -> "TaskEnvelope":
        """Build the envelope. The *only* supported construction path.

        Callers of this function are dispatcher internals that have already
        canonicalised the repository root (``security.validate_repository_root``)
        and resolved the base commit (``git.resolve_base_commit``).
        """
        tid = task_id or new_task_id()
        return cls(
            schema_version=SCHEMA_VERSION,
            task_id=tid,
            created_at=created_at or utc_now(),
            repository=RepositoryResolved(
                root=canonical_root,
                base_ref=request.repository.base_ref,
                workspace_mode=request.repository.workspace_mode,
                base_commit=base_commit,
            ),
            task=request.task,
            scope=request.scope,
            validation=request.validation,
            routing=request.routing,
            execution=request.execution,
            constraints=request.constraints,
            lineage=LineageSpec(
                parent_task_id=request.parent_task_id,
                previous_session_id=previous_session_id,
                escalation_reason=escalation_reason,
                dispatch_depth=dispatch_depth,
            ),
            worktree_name=worktree_name_for(tid),
        )


# ---------------------------------------------------------------------------
# WorkerResult (§15) — CLAIMS. Not evidence.
# ---------------------------------------------------------------------------


class ChangedFile(StrictModel):
    path: NonEmptyStr
    type: Literal["added", "modified", "deleted", "renamed"]
    description: str = Field(default="", max_length=_MAX_TEXT)


class AcceptanceCriterionResult(StrictModel):
    criterion: NonEmptyStr
    status: Literal["satisfied", "partially_satisfied", "not_satisfied", "unknown"]
    evidence: str = Field(default="", max_length=_MAX_TEXT)


class TestReport(StrictModel):
    """A test run *the worker claims* it performed. Unverified until re-run."""

    #: Not a pytest test class, despite the name. Stops pytest trying to
    #: collect it wherever this module is imported into a test file.
    __test__ = False

    command: NonEmptyStr
    status: Literal["passed", "failed", "skipped", "not_run"]
    exit_code: int | None = None
    summary: str = Field(default="", max_length=_MAX_TEXT)


class WorkerStatus(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class WorkerResult(StrictModel):
    """The structured result Claude returns via ``--json-schema`` (§15).

    This object is *what the worker says happened*. §16: "Claude saying '341
    tests passed' is a claim until independent evidence supports it." Nothing
    in this model may be treated as verified. It is always stored under a
    ``worker_claims`` key, never merged into dispatcher observations.

    Kept field-for-field in lockstep with ``schemas/worker-result.schema.json``
    (``additionalProperties: false`` there, ``extra="forbid"`` here).
    """

    status: WorkerStatus
    summary: NonEmptyStr
    changes: list[ChangedFile] = Field(default_factory=list, max_length=_MAX_LIST)
    acceptance_criteria: list[AcceptanceCriterionResult] = Field(
        default_factory=list, max_length=_MAX_LIST
    )
    tests: list[TestReport] = Field(default_factory=list, max_length=_MAX_LIST)
    risks: list[NonEmptyStr] = Field(default_factory=list, max_length=_MAX_LIST)
    blockers: list[NonEmptyStr] = Field(default_factory=list, max_length=_MAX_LIST)
    needs_review: bool = True


# ---------------------------------------------------------------------------
# FableReview (§19) — advisory only
# ---------------------------------------------------------------------------


class FableSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FableCategory(str, Enum):
    CORRECTNESS = "correctness"
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    TESTS = "tests"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"
    REQUIREMENTS = "requirements"


class FableVerdict(str, Enum):
    APPROVE = "approve"
    CHANGES_REQUIRED = "changes_required"
    REJECT = "reject"


class RecommendedNextAction(str, Enum):
    ACCEPT = "accept"
    RESUME_WORKER = "resume_worker"
    ESCALATE_TO_OPUS = "escalate_to_opus"
    REJECT = "reject"
    HUMAN_REVIEW = "human_review"


class FableFinding(StrictModel):
    id: NonEmptyStr
    severity: FableSeverity
    category: FableCategory
    path: str | None = None
    line: int | None = Field(default=None, ge=1)
    finding: NonEmptyStr
    evidence: str = Field(default="", max_length=_MAX_TEXT)
    recommendation: str = Field(default="", max_length=_MAX_TEXT)


class FableReview(StrictModel):
    """Independent review output (§7.3, §19).

    Advisory. Sol decides whether Fable is correct. The dispatcher never acts
    on ``recommended_next_action`` by itself — it records it and returns it.
    Kept in lockstep with ``schemas/fable-review.schema.json``.
    """

    verdict: FableVerdict
    findings: list[FableFinding] = Field(default_factory=list, max_length=_MAX_LIST)
    missing_tests: list[NonEmptyStr] = Field(
        default_factory=list, max_length=_MAX_LIST
    )
    architecture_notes: list[NonEmptyStr] = Field(
        default_factory=list, max_length=_MAX_LIST
    )
    recommended_next_action: RecommendedNextAction


# ---------------------------------------------------------------------------
# Dispatcher-side evidence (§16, §17) — OBSERVATIONS. Not claims.
# ---------------------------------------------------------------------------


class ValidationResult(StrictModel):
    """Result of the dispatcher independently re-running a trusted command (§17).

    ``source`` is pinned to ``"dispatcher"``: a worker can never contribute one
    of these, and the worker result can never redefine which commands run.
    """

    source: Literal["dispatcher"] = "dispatcher"
    argv: list[NonEmptyStr] = Field(min_length=1)
    exit_code: int | None = None
    passed: bool
    timed_out: bool = False
    duration_ms: int = Field(ge=0)
    stdout_tail: str = Field(default="", max_length=_MAX_TEXT)
    stderr_tail: str = Field(default="", max_length=_MAX_TEXT)
    #: Bytes the command actually wrote, versus what the bounded tail retains.
    #: ``*_truncated`` says plainly that the tail is an excerpt, so a reader
    #: never mistakes bounded evidence for the complete stream (P1-8).
    stdout_bytes: int = Field(default=0, ge=0)
    stderr_bytes: int = Field(default=0, ge=0)
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class SkillPolicyRecord(StrictModel):
    """The approved-skill policy a run was dispatched under (Gate 4.5 §15).

    Skill policy is part of execution context, so it is persisted as evidence
    at dispatch and re-verified on resume. ``fingerprint`` is a SHA-256 over
    the manifest identity plus every selected skill's resolved path and pinned
    hashes (see ``skills.SkillProjection.fingerprint``); a resume that
    recomputes a different value must fail closed rather than silently pick up
    a new skill, a new plugin version, or changed contents.
    """

    mode: Literal["projected"] = "projected"
    manifest_schema_version: NonEmptyStr
    manifest_version: NonEmptyStr
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    skill_ids: list[str] = Field(default_factory=list, max_length=_MAX_LIST)
    projected_bytes: int = Field(default=0, ge=0)
    approx_tokens: int = Field(default=0, ge=0)


class ProjectGuidanceRecord(StrictModel):
    """The curated project-guidance context a run was dispatched under (§16).

    Project guidance is execution context in exactly the way skill policy is,
    so it is persisted as evidence at dispatch and re-verified on resume.
    ``fingerprint`` follows ``approved-guidance.json``'s
    ``resume_fingerprint.spec`` verbatim: it covers each emitted entry's
    instruction-source hashes plus both of its projection-artifact hashes, in
    emission order, combined with the graph-refresh variant and the task
    envelope identity. A resume that recomputes a different value must fail
    closed rather than silently adopt a re-approved projection or a changed
    CLAUDE.md.

    ``logical_ids`` is the selected set, so resume re-verifies exactly the
    scopes the dispatch ran under — it does not re-select from allowed_paths,
    because a changed selection is a different question from changed guidance.
    """

    mode: Literal["projected", "disabled"] = "projected"
    manifest_schema_version: NonEmptyStr
    approval_version: NonEmptyStr
    audience: NonEmptyStr
    repository_id: NonEmptyStr
    logical_ids: list[str] = Field(default_factory=list, max_length=_MAX_LIST)
    graph_variant: NonEmptyStr
    task_envelope_id: NonEmptyStr
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    projected_bytes: int = Field(default=0, ge=0)
    approx_tokens: int = Field(default=0, ge=0)


class RunMetadata(StrictModel):
    """Identity and process facts for one subprocess run.

    Written *before* the subprocess starts (minus the completion fields) so
    that a crash or timeout still leaves a durable record (§20: "Do not lose
    session ID, worktree, partial stdout, stderr, git diff, task state").
    """

    run_id: str
    run_index: int = Field(ge=1)
    task_id: str
    kind: RunKind
    role: WorkerRole
    model: NonEmptyStr
    session_id: str
    worktree_path: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    exit_code: int | None = None
    timed_out: bool = False
    killed_with_sigkill: bool = False
    argv_redacted: list[str] = Field(default_factory=list)
    #: Bytes the child actually wrote, not the size of the retained excerpt
    #: (P1-8). When the corresponding ``*_truncated`` flag is set, the run
    #: directory's ``stdout.json`` holds head+tail with an in-band marker and
    #: ``stdout.raw`` holds the complete stream.
    stdout_bytes: int = Field(default=0, ge=0)
    stderr_bytes: int = Field(default=0, ge=0)
    #: Whether the retained in-memory excerpt is short of the full stream.
    #: Defaults to ``False`` so a record persisted before this field existed
    #: still loads (it could not have been truncated: the retention policy that
    #: makes truncation possible landed with the flag).
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    #: Fingerprint of the approved-skill policy this run was invoked under
    #: (Gate 4.5 §15). ``None`` means no skill guidance was projected — which
    #: is also what every run recorded before skill projection existed says.
    skill_policy_fingerprint: str | None = None
    #: Fingerprint of the curated project-guidance context this run was invoked
    #: under (Gate 4.5 addendum §16). ``None`` means no project guidance was
    #: projected — which is also what every run recorded before the guidance
    #: engine existed says.
    project_guidance_fingerprint: str | None = None


class DispatcherObservations(StrictModel):
    """What the dispatcher itself measured (§16). The trusted half of a run.

    This is deliberately a *different type* from :class:`WorkerResult`. Never
    add a field here that mirrors a worker claim, and never populate a field
    here from parsed worker output. Everything on this model must come from
    the dispatcher's own subprocess handling, git inspection, or scope checks.
    """

    task_id: str
    run_id: str
    session_id: str
    model: NonEmptyStr
    base_commit: str

    duration_ms: int = Field(ge=0)
    exit_code: int | None = None
    timed_out: bool = False

    changed_paths: list[str] = Field(default_factory=list)
    diff_stat: str = Field(default="", max_length=_MAX_TEXT)
    #: Size of the diff the dispatcher held in memory, capped at
    #: ``[validation].max_diff_bytes``.
    diff_bytes: int = Field(default=0, ge=0)
    #: Size of the *whole* diff as git produced it. Greater than
    #: ``diff_bytes`` means the in-memory value was capped; ``evidence/diff.patch``
    #: is still the complete patch (or is explicitly marked incomplete).
    #: Without this a reader cannot tell a small diff from a truncated one.
    diff_total_bytes: int = Field(default=0, ge=0)

    scope_valid: bool = True
    out_of_scope_paths: list[str] = Field(default_factory=list)
    forbidden_paths_touched: list[str] = Field(default_factory=list)
    diff_check_passed: bool = True

    worker_result_parsed: bool = False
    worker_result_error: str | None = Field(default=None, max_length=_MAX_TEXT)

    #: Literal measurement: the primary tree has no uncommitted changes *now*.
    #: Not the non-interference verdict — an already-dirty tree is not a
    #: violation.
    primary_worktree_clean: bool | None = None
    #: The non-interference verdict (P1-5): the primary tree's fingerprint
    #: (HEAD commit + ``git status --porcelain``) is byte-identical to the
    #: baseline taken before the worker started. ``None`` means the comparison
    #: was not performed for this run — including every run recorded before
    #: this field existed. **Detection, not containment**: see
    #: ``docs/SECURITY.md``.
    primary_tree_unchanged: bool | None = None


class RunRecord(StrictModel):
    """One run: claims and observations side by side, never merged (§16)."""

    metadata: RunMetadata
    #: What Claude said. May be ``None`` (timeout, crash, malformed output).
    worker_claims: WorkerResult | None = None
    #: What the dispatcher measured. Present for every completed run.
    dispatcher_observations: DispatcherObservations | None = None
    #: Independent re-runs of trusted envelope commands (§17).
    validation_results: list[ValidationResult] = Field(default_factory=list)


class TaskRecord(StrictModel):
    """Mutable per-task state persisted as ``state.json`` (§27).

    The envelope is immutable and lives in ``envelope.json``; everything that
    changes over a task's life lives here.
    """

    schema_version: Literal["1.0"]
    task_id: str
    state: TaskState
    selected_model: str | None = None
    session_id: str | None = None
    worktree_path: str | None = None
    resume_count: int = Field(default=0, ge=0)
    run_count: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
    state_history: list[dict[str, Any]] = Field(default_factory=list)
    last_error: dict[str, Any] | None = None
    policy_violations: list[str] = Field(default_factory=list)
    fable_review_count: int = Field(default=0, ge=0)
    #: Approved-skill policy captured at dispatch (Gate 4.5 §15). Resume must
    #: verify it and fail closed on drift. ``None`` means the task was
    #: dispatched with no projected skill guidance.
    skill_policy: SkillPolicyRecord | None = None
    #: Curated project-guidance context captured at dispatch (addendum §16).
    #: Resume must verify it and fail closed on drift. ``None`` means the task
    #: was dispatched with no projected project guidance.
    project_guidance: ProjectGuidanceRecord | None = None
