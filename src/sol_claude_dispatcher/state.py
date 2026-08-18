"""Task persistence and the state machine (brief §26, §27). — Wave 2.

Filesystem JSON only. No database. Directories 0700, files 0600. Every write is
atomic (temp file in the same directory, ``fsync``, ``os.replace``). Corrupt or
unversioned state fails closed with ``StateCorruption`` — it is never repaired
or guessed at.

The transition table is *not* defined here. It lives in
:data:`sol_claude_dispatcher.models.ALLOWED_TRANSITIONS` so that the state
machine and the models can never drift apart. This module enforces it.

Contract (authoritative, see ``docs/INTERFACES.md``)::

    class TaskStore:
        def __init__(self, root: Path) -> None
        def create(self, envelope: TaskEnvelope) -> TaskRecord
        def exists(self, task_id: str) -> bool
        def load_envelope(self, task_id: str) -> TaskEnvelope
        def load(self, task_id: str) -> TaskRecord
        def save(self, record: TaskRecord) -> None
        def transition(self, task_id, target, *, reason=None, **updates) -> TaskRecord
        def append_run(self, task_id: str, run: RunRecord) -> None
        def load_runs(self, task_id: str) -> list[RunRecord]
        def append_review(self, task_id: str, review: FableReview) -> int
        def load_reviews(self, task_id: str) -> list[FableReview]
        def write_evidence(self, task_id, name, content) -> Path
        def read_evidence(self, task_id, name) -> str | None
        def task_dir(self, task_id: str) -> Path
        def run_dir(self, task_id: str, run_index: int) -> Path
"""

from __future__ import annotations

from pathlib import Path

from .models import FableReview, RunRecord, TaskEnvelope, TaskRecord, TaskState

__all__ = ["TaskStore", "atomic_write_json", "atomic_write_text"]


def atomic_write_text(path: Path, content: str, *, mode: int = 0o600) -> None:
    """Write ``content`` to ``path`` atomically (§27)."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §state")


def atomic_write_json(path: Path, data: object, *, mode: int = 0o600) -> None:
    """Serialise ``data`` to JSON and write it atomically (§27)."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §state")


class TaskStore:
    """Authoritative on-disk task state under ``state/tasks/<task-id>/``."""

    def __init__(self, root: Path) -> None:
        raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §state")

    def transition(
        self,
        task_id: str,
        target: TaskState,
        *,
        reason: str | None = None,
        **updates: object,
    ) -> TaskRecord:
        """Validate and apply a state transition, persisting atomically."""
        raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §state")
