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
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import TaskEnvelope, TaskRecord

__all__ = ["ResumePlan", "new_session", "assert_resume_allowed", "resume_plan"]


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
    """Generate the session id for a task's first run (§11)."""
    raise NotImplementedError("Wave 3: implement per docs/INTERFACES.md §sessions")


def assert_resume_allowed(envelope: TaskEnvelope, record: TaskRecord) -> None:
    """Raise ``ResumeLimitReached`` when the cap is exhausted (§22 layer 6)."""
    raise NotImplementedError("Wave 3: implement per docs/INTERFACES.md §sessions")


def resume_plan(
    envelope: TaskEnvelope, record: TaskRecord, instruction: str, *,
    timeout_seconds: int | None = None,
) -> ResumePlan:
    """Build a resume plan from *stored* state only. Caller input is the instruction."""
    raise NotImplementedError("Wave 3: implement per docs/INTERFACES.md §sessions")
