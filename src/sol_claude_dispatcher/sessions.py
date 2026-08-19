"""Session lifecycle: creation, resume, and caps (brief §11, §18, §22). — Wave 3.

Invariants that resume must never break:

* **Same session id.** Retrieved from persisted state. §7.2: "Never trust the
  caller to supply a replacement session ID."
* **Same model.** A Sonnet task never silently becomes an Opus task. Escalation
  means a *new* task with lineage, not a mutated one (§18).
* **Same worktree.** No second worktree is created on resume (§18).
* **Same scope, constraints and acceptance criteria.** They come from the
  stored envelope, not from the resume call.
* **Cap enforced.** ``resume_count`` increments; exceeding ``max_resume_count``
  returns ``requires_orchestrator_decision`` / ``resume_limit_reached`` (§7.2).

Contract (authoritative, see ``docs/INTERFACES.md``)::

    def new_session(envelope: TaskEnvelope) -> str
    def resume_plan(envelope, record, instruction) -> ResumePlan
    def assert_resume_allowed(envelope: TaskEnvelope, record: TaskRecord) -> None

Additions beyond that contract (purely additive, nothing else imports them
yet): :func:`resume_limit_response` renders the §7.2 refusal payload, and
:class:`EscalationHandoff` / :func:`escalation_handoff` implement the §18
"escalation creates a NEW task" rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .errors import InvalidTaskEnvelope, ResumeLimitReached, StateCorruption
from .models import (
    RequestedModel,
    RepositoryRequest,
    RoutingSpec,
    TaskEnvelope,
    TaskRecord,
    TaskRequest,
    TaskSpec,
    new_session_id,
)

__all__ = [
    "ResumePlan",
    "new_session",
    "assert_resume_allowed",
    "resume_plan",
    "resume_limit_response",
    "EscalationHandoff",
    "escalation_handoff",
    "MAX_HANDOFF_SECTION_CHARS",
]

#: Each handoff evidence section is capped; the full artefacts already live in
#: the task's evidence directory and the new worker can read them from disk.
MAX_HANDOFF_SECTION_CHARS: int = 4_000

#: ``TaskSpec.context`` is capped at 20_000 chars by the model. Stay under it
#: with room to spare so a handoff can never fail validation on length alone.
MAX_HANDOFF_CONTEXT_CHARS: int = 19_000


@dataclass(frozen=True)
class ResumePlan:
    """A validated plan to continue an existing worker conversation."""

    task_id: str
    session_id: str
    model: str
    worktree_path: str
    instruction: str
    timeout_seconds: int
    next_resume_count: int


def new_session(envelope: TaskEnvelope) -> str:
    """Generate the session id for a task's first run (§11).

    ``--session-id`` demands a UUID, so this is always ``uuid4``. The envelope
    is accepted (and validated as present) purely so call sites read as
    "a session for *this* task" and cannot mint an id for nothing.
    """
    if not envelope.task_id:
        raise InvalidTaskEnvelope(
            "Cannot create a session for an envelope without a task id."
        )
    return new_session_id()


def assert_resume_allowed(envelope: TaskEnvelope, record: TaskRecord) -> None:
    """Raise ``ResumeLimitReached`` when the cap is exhausted (§22 layer 6).

    Checked exactly once, at the ``RESUME_REQUESTED`` boundary. The MCP layer
    converts the exception into the §7.2 ``requires_orchestrator_decision``
    payload — a *successful* tool response describing a refusal.
    """
    limit = envelope.execution.max_resume_count
    if record.resume_count >= limit:
        raise ResumeLimitReached(
            "Resume limit reached; the orchestrator must decide what happens next.",
            details={
                "task_id": record.task_id,
                "resume_count": record.resume_count,
                "max_resume_count": limit,
            },
            remediation=(
                "Accept the work as-is, escalate to a new task with lineage, "
                "or close the task. The dispatcher will not resume again."
            ),
        )


def resume_plan(
    envelope: TaskEnvelope,
    record: TaskRecord,
    instruction: str,
    *,
    timeout_seconds: int | None = None,
    config: Config | None = None,
) -> ResumePlan:
    """Build a resume plan from *stored* state only.

    The caller contributes the instruction and (optionally) a timeout. Session
    id, model and worktree are read from the record and are not overridable —
    that is the whole §7.2/§18 guarantee. ``config`` is optional and used only
    to clamp a caller-supplied timeout.
    """
    if not instruction or not instruction.strip():
        raise InvalidTaskEnvelope(
            "A resume requires a non-empty instruction.",
            details={"task_id": record.task_id},
        )
    if record.task_id != envelope.task_id:
        raise StateCorruption(
            "Record and envelope describe different tasks.",
            details={"record_task_id": record.task_id, "envelope_task_id": envelope.task_id},
        )

    assert_resume_allowed(envelope, record)

    missing = [
        name
        for name in ("session_id", "selected_model", "worktree_path")
        if not getattr(record, name)
    ]
    if missing:
        raise StateCorruption(
            "Stored task state is missing the fields a resume must reuse.",
            details={"task_id": record.task_id, "missing": missing},
            remediation=(
                "The task never reached a running worker, or state.json was "
                "damaged. Do not resume; inspect the task with get_task."
            ),
        )

    requested = (
        timeout_seconds if timeout_seconds is not None else envelope.execution.timeout_seconds
    )
    if config is not None:
        requested = config.clamp_timeout(requested)

    return ResumePlan(
        task_id=record.task_id,
        session_id=str(record.session_id),
        model=str(record.selected_model),
        worktree_path=str(record.worktree_path),
        instruction=instruction,
        timeout_seconds=requested,
        next_resume_count=record.resume_count + 1,
    )


def resume_limit_response(error: ResumeLimitReached) -> dict[str, Any]:
    """Render the §7.2 refusal payload for the MCP layer.

    This is a successful tool response, not a protocol error: the dispatcher is
    reporting that it will not decide, and handing the decision back to Sol.
    """
    details = dict(error.details or {})
    return {
        "status": "requires_orchestrator_decision",
        "reason": "resume_limit_reached",
        "task_id": details.get("task_id"),
        "resume_count": details.get("resume_count"),
        "max_resume_count": details.get("max_resume_count"),
        "remediation": error.remediation,
    }


# ---------------------------------------------------------------------------
# escalation (§18) — a NEW task, never an in-place model change
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EscalationHandoff:
    """A structured handoff from a finished worker to a fresh, stronger one.

    §18 is explicit: a Sonnet task never becomes an Opus task inside its own
    lifecycle. Escalation produces a *new* task carrying lineage back to the
    original — parent task id, the previous session id, and the reason.

    ``request`` is ready for ``TaskEnvelope.from_request(...)``; pass
    ``previous_session_id`` and ``escalation_reason`` from this object so the
    new envelope's ``LineageSpec`` is complete.
    """

    parent_task_id: str
    previous_session_id: str
    escalation_reason: str
    requested_model: RequestedModel
    request: TaskRequest
    handoff_context: str
    sections: dict[str, str] = field(default_factory=dict)


def _clip(text: str, limit: int = MAX_HANDOFF_SECTION_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[...truncated at {limit} chars; full artefact is in the task's evidence directory]"


def escalation_handoff(
    envelope: TaskEnvelope,
    record: TaskRecord,
    *,
    reason: str,
    requested_model: RequestedModel = RequestedModel.OPUS,
    worker_report: str | None = None,
    sol_review: str | None = None,
    diff_text: str | None = None,
) -> EscalationHandoff:
    """Build the §18 escalation handoff. Mutates nothing.

    The original envelope and record are read-only inputs: the escalated work
    is a new ``TaskRequest`` with the same objective, scope, validation and
    constraints, an augmented context carrying the evidence, and lineage
    pointing back at the task that ran out of road.
    """
    if not reason or not reason.strip():
        raise InvalidTaskEnvelope(
            "An escalation must state why.", details={"task_id": envelope.task_id}
        )
    if requested_model is RequestedModel.AUTO:
        raise InvalidTaskEnvelope(
            "An escalation must name the model it escalates to.",
            details={"task_id": envelope.task_id, "requested_model": "auto"},
        )
    if not record.session_id:
        raise StateCorruption(
            "Cannot escalate a task that never had a session.",
            details={"task_id": envelope.task_id},
        )

    sections: dict[str, str] = {
        "escalation_reason": reason.strip(),
        "original_objective": envelope.task.objective,
        "parent_task_id": envelope.task_id,
        "previous_session_id": record.session_id,
        "previous_model": record.selected_model or "unknown",
        "base_commit": envelope.repository.base_commit,
    }
    if worker_report:
        sections["previous_worker_report"] = _clip(worker_report)
    if sol_review:
        sections["sol_review"] = _clip(sol_review)
    if diff_text:
        sections["current_diff"] = _clip(diff_text)

    body = [
        "## Escalation handoff",
        "",
        f"This task is an escalation of task `{envelope.task_id}` "
        f"(previous session `{record.session_id}`, model "
        f"`{record.selected_model or 'unknown'}`).",
        "",
        f"**Reason for escalation:** {sections['escalation_reason']}",
        "",
        f"**Base commit:** `{envelope.repository.base_commit}`",
    ]
    for label, key in (
        ("Previous worker report", "previous_worker_report"),
        ("Sol review", "sol_review"),
        ("Current diff", "current_diff"),
    ):
        if key in sections:
            body += ["", f"### {label}", "", sections[key]]
    handoff_context = "\n".join(body)

    original_context = envelope.task.context.strip()
    merged_context = _clip(
        f"{original_context}\n\n{handoff_context}" if original_context else handoff_context,
        MAX_HANDOFF_CONTEXT_CHARS,
    )

    request = TaskRequest(
        repository=RepositoryRequest(
            root=envelope.repository.root,
            # Pin the escalated task to the exact commit the parent started
            # from, so the new worker sees the same ground truth.
            base_ref=envelope.repository.base_commit,
            workspace_mode=envelope.repository.workspace_mode,
        ),
        task=TaskSpec(
            kind=envelope.task.kind,
            objective=envelope.task.objective,
            context=merged_context,
            acceptance_criteria=list(envelope.task.acceptance_criteria),
        ),
        scope=envelope.scope.model_copy(deep=True),
        validation=envelope.validation.model_copy(deep=True),
        routing=RoutingSpec(
            requested_model=requested_model,
            complexity=envelope.routing.complexity,
            risk=envelope.routing.risk,
        ),
        execution=envelope.execution.model_copy(deep=True),
        constraints=envelope.constraints.model_copy(deep=True),
        parent_task_id=envelope.task_id,
    )

    return EscalationHandoff(
        parent_task_id=envelope.task_id,
        previous_session_id=record.session_id,
        escalation_reason=sections["escalation_reason"],
        requested_model=requested_model,
        request=request,
        handoff_context=handoff_context,
        sections=sections,
    )
