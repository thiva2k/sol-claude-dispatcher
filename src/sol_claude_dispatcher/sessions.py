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

Additions beyond that contract: :func:`resume_limit_response` renders the
§7.2 refusal payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Config
from .errors import InvalidTaskEnvelope, ResumeLimitReached, StateCorruption
from .models import TaskEnvelope, TaskRecord, new_session_id

__all__ = [
    "ResumePlan",
    "new_session",
    "assert_resume_allowed",
    "resume_plan",
    "resume_limit_response",
]


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
