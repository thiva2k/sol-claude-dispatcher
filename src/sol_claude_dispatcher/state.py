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
        def latest_run(self, task_id: str) -> RunRecord | None
        def append_review(self, task_id: str, review: FableReview) -> int
        def load_reviews(self, task_id: str) -> list[FableReview]
        def write_evidence(self, task_id, name, content) -> Path
        def read_evidence(self, task_id, name) -> str | None
        def task_dir(self, task_id: str) -> Path
        def run_dir(self, task_id: str, run_index: int) -> Path
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from pydantic import ValidationError

from .errors import InvalidStateTransition, InvalidTaskEnvelope, StateCorruption, TaskNotFound
from .models import (
    SCHEMA_VERSION,
    FableReview,
    RunRecord,
    TaskEnvelope,
    TaskRecord,
    TaskState,
    is_transition_allowed,
    utc_now,
)

__all__ = ["TaskStore", "atomic_write_json", "atomic_write_text"]

_DIR_MODE = 0o700
_FILE_MODE = 0o600

# Fields on TaskRecord that a transition's **updates may legally set. Anything
# else is refused rather than silently ignored — the caller almost certainly
# made a typo or is trying to mutate something outside the state machine's
# authority (e.g. task_id, created_at, state_history directly).
_TRANSITION_UPDATABLE_FIELDS = frozenset(
    {
        "selected_model",
        "session_id",
        "worktree_path",
        "resume_count",
        "run_count",
        "last_error",
        "policy_violations",
        "fable_review_count",
    }
)


# A task id is only ever used here as a single path component. This is the
# structural gate that makes that safe *without* depending on the MCP layer
# having called security.validate_task_id first (P0-1, defense in depth):
# one component, no separators, no traversal, no leading dot, no control
# characters, bounded length. The authoritative caller-facing rule is stricter
# still (canonical UUID only) and lives in security.validate_task_id; this one
# is deliberately permissive enough to keep the store usable with the
# dispatcher's own internal identifiers while still being impossible to escape
# with.
_SAFE_ID_COMPONENT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

def _reject_unsafe_component(value: object, *, what: str) -> str:
    """Refuse anything that is not a single, traversal-free path component."""
    if not isinstance(value, str):
        raise InvalidTaskEnvelope(
            f"{what} must be a string.", details={"type": type(value).__name__}
        )
    if "\x00" in value:
        raise InvalidTaskEnvelope(
            f"{what} contains a null byte.", details={what: repr(value)}
        )
    if value != value.strip():
        raise InvalidTaskEnvelope(
            f"{what} has leading or trailing whitespace.", details={what: repr(value)}
        )
    if not _SAFE_ID_COMPONENT_RE.match(value):
        raise InvalidTaskEnvelope(
            f"{what} is not a safe path component.", details={what: repr(value)}
        )
    return value


def _mkdir(path: Path) -> None:
    """Create ``path`` (and parents) with 0700, tightening an existing dir too."""
    path.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
    # mkdir's `mode` is affected by umask; force the bit pattern explicitly so
    # a permissive umask never leaves task state world- or group-readable.
    os.chmod(path, _DIR_MODE)


def atomic_write_text(path: Path, content: str, *, mode: int = 0o600) -> None:
    """Write ``content`` to ``path`` atomically (§27).

    Temp file in the same directory -> write -> flush -> fsync -> os.replace.
    The mode is set on the temp file *before* the replace so the final file is
    never briefly world-readable. Best-effort fsync of the containing
    directory afterwards. On any failure the temp file is removed and the
    exception re-raised.
    """
    directory = path.parent
    _mkdir(directory)
    tmp_path = directory / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        # O_EXCL: the random suffix means a collision is already near
        # impossible, but fail loudly rather than silently overwrite another
        # writer's in-flight temp file.
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        # os.open's mode is subject to umask; force the exact bits so the
        # temp file (and thus the file `os.replace` produces) is never
        # briefly more permissive than intended.
        os.chmod(tmp_path, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise
    else:
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            # Best-effort only (§27): some filesystems / platforms cannot
            # fsync a directory. Not fatal to the write we already committed.
            pass


def atomic_write_json(path: Path, data: object, *, mode: int = 0o600) -> None:
    """Serialise ``data`` to JSON and write it atomically (§27)."""
    content = json.dumps(data, indent=2, default=str, sort_keys=False)
    atomic_write_text(path, content, mode=mode)


def _read_json_plain(path: Path, *, task_id: str, what: str) -> dict:
    """Read and parse a JSON file into an object, failing closed per §27.

    Unparseable JSON, an unreadable file, or a non-object top level raises
    ``StateCorruption``. Never repaired, never guessed at. Used for artefacts
    that carry no ``schema_version`` of their own (runs, reviews) — their
    container files (``envelope.json`` / ``state.json``) are the versioned
    ones; see :func:`_read_json`.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise TaskNotFound(
            f"No {what} found for task.",
            details={"task_id": task_id, "path": str(path)},
        ) from exc
    except OSError as exc:
        raise StateCorruption(
            f"{what} could not be read.",
            details={"task_id": task_id, "path": str(path), "reason": str(exc)},
        ) from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StateCorruption(
            f"{what} is not valid JSON.",
            details={"task_id": task_id, "path": str(path), "reason": str(exc)},
        ) from exc

    if not isinstance(data, dict):
        raise StateCorruption(
            f"{what} did not deserialise to an object.",
            details={"task_id": task_id, "path": str(path)},
        )
    return data


def _read_json(path: Path, *, task_id: str, what: str) -> dict:
    """Read and parse a *versioned* JSON file, failing closed per §27.

    Unparseable JSON or a missing/mismatched ``schema_version`` raises
    ``StateCorruption``. Never repaired, never guessed at. Used for
    ``envelope.json`` and ``state.json`` — the two artefacts whose models
    (``TaskEnvelope``, ``TaskRecord``) carry ``schema_version``.
    """
    data = _read_json_plain(path, task_id=task_id, what=what)

    schema_version = data.get("schema_version")
    if schema_version is None:
        raise StateCorruption(
            f"{what} is missing schema_version.",
            details={"task_id": task_id, "path": str(path)},
        )
    if schema_version != SCHEMA_VERSION:
        raise StateCorruption(
            f"{what} has an unsupported schema_version.",
            details={
                "task_id": task_id,
                "path": str(path),
                "found": schema_version,
                "expected": SCHEMA_VERSION,
            },
        )
    return data


class TaskStore:
    """Authoritative on-disk task state under ``state/tasks/<task-id>/``.

    Holds no authoritative in-memory state: every read re-reads from disk, so
    a fresh ``TaskStore`` instance after an MCP server restart reconstructs
    identical state (§27).
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        _mkdir(self.root)
        # Canonical form of the state root, captured once. Every path this
        # store derives is checked against it, so a symlink planted *inside*
        # state/tasks/ cannot redirect a read or a write outside the root.
        self._canonical_root = self.root.resolve()

    # -- paths --------------------------------------------------------

    def _contained(self, path: Path, *, task_id: str) -> Path:
        """Return ``path`` only if it resolves inside the task-state root.

        The last line of defence for P0-1: containment is re-derived here for
        every path, so the store is safe even when a caller skipped
        ``security.validate_task_id``, and even when part of the tree has been
        replaced by a symlink since the directory was created. Checked before
        any read or write touches the filesystem.
        """
        resolved = path.resolve()
        root = self._canonical_root
        if resolved != root and root not in resolved.parents:
            raise InvalidTaskEnvelope(
                "Refusing to touch a path outside the task-state root.",
                details={
                    "task_id": repr(task_id),
                    "resolved_path": str(resolved),
                    "state_root": str(root),
                },
            )
        return path

    def task_dir(self, task_id: str) -> Path:
        """``state/tasks/<task_id>``, proven to stay inside the state root."""
        safe_id = _reject_unsafe_component(task_id, what="task_id")
        return self._contained(self.root / safe_id, task_id=safe_id)

    def run_dir(self, task_id: str, run_index: int) -> Path:
        if not isinstance(run_index, int) or isinstance(run_index, bool):
            raise InvalidTaskEnvelope(
                "run_index must be an integer.",
                details={"task_id": repr(task_id), "type": type(run_index).__name__},
            )
        if run_index < 0:
            raise InvalidTaskEnvelope(
                "run_index must not be negative.",
                details={"task_id": repr(task_id), "run_index": run_index},
            )
        path = self.task_dir(task_id) / "runs" / f"{run_index:03d}"
        return self._contained(path, task_id=task_id)

    def _envelope_path(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "envelope.json"

    def _state_path(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "state.json"

    def _metadata_path(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "metadata.json"

    def _reviews_dir(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "reviews"

    def _evidence_dir(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "evidence"

    # -- existence / creation -------------------------------------------

    def exists(self, task_id: str) -> bool:
        return self._envelope_path(task_id).exists()

    def list_tasks(self) -> list[str]:
        """All task ids with a persisted envelope, reconstructed from disk.

        Entries whose name is not a safe path component, or whose directory
        resolves outside the state root (a planted symlink), are skipped rather
        than returned — this method's output is fed straight back into
        ``load()``.
        """
        if not self.root.exists():
            return []
        found: list[str] = []
        for entry in self.root.iterdir():
            if not _SAFE_ID_COMPONENT_RE.match(entry.name):
                continue
            resolved = entry.resolve()
            if self._canonical_root not in resolved.parents:
                continue
            if entry.is_dir() and (entry / "envelope.json").exists():
                found.append(entry.name)
        return sorted(found)

    def load_all(self) -> list[TaskRecord]:
        """Reconstruct every task's record from disk (restart recovery, §27)."""
        return [self.load(task_id) for task_id in self.list_tasks()]

    def create(self, envelope: TaskEnvelope) -> TaskRecord:
        """Create the directory tree (0700) and write envelope.json/state.json.

        Raises ``InvalidTaskEnvelope`` if the task already exists.
        """
        task_id = envelope.task_id
        if self.exists(task_id):
            raise InvalidTaskEnvelope(
                "A task with this task_id already exists.",
                details={"task_id": task_id},
            )

        task_dir = self.task_dir(task_id)
        _mkdir(task_dir)
        _mkdir(task_dir / "runs")
        _mkdir(self._reviews_dir(task_id))
        _mkdir(self._evidence_dir(task_id))

        envelope_payload = json.loads(envelope.model_dump_json())
        atomic_write_json(self._envelope_path(task_id), envelope_payload, mode=_FILE_MODE)

        now = utc_now()
        record = TaskRecord(
            schema_version=SCHEMA_VERSION,
            task_id=task_id,
            state=TaskState.CREATED,
            selected_model=None,
            session_id=None,
            worktree_path=None,
            resume_count=0,
            run_count=0,
            created_at=now,
            updated_at=now,
            state_history=[],
            last_error=None,
            policy_violations=[],
            fable_review_count=0,
        )
        self._save_record(record)
        return record

    # -- envelope / record load-save -------------------------------------

    def load_envelope(self, task_id: str) -> TaskEnvelope:
        data = _read_json(self._envelope_path(task_id), task_id=task_id, what="envelope.json")
        try:
            return TaskEnvelope.model_validate(data)
        except ValidationError as exc:
            raise StateCorruption(
                "envelope.json failed schema validation.",
                details={"task_id": task_id, "reason": str(exc)},
            ) from exc

    def load(self, task_id: str) -> TaskRecord:
        data = _read_json(self._state_path(task_id), task_id=task_id, what="state.json")
        try:
            return TaskRecord.model_validate(data)
        except ValidationError as exc:
            raise StateCorruption(
                "state.json failed schema validation.",
                details={"task_id": task_id, "reason": str(exc)},
            ) from exc

    def save(self, record: TaskRecord) -> None:
        """Persist ``record``, setting ``updated_at``, atomically."""
        record.updated_at = utc_now()
        self._save_record(record)

    def _save_record(self, record: TaskRecord) -> None:
        payload = json.loads(record.model_dump_json())
        atomic_write_json(self._state_path(record.task_id), payload, mode=_FILE_MODE)

    # -- state machine ----------------------------------------------------

    def transition(
        self,
        task_id: str,
        target: TaskState,
        *,
        reason: str | None = None,
        **updates: object,
    ) -> TaskRecord:
        """Validate and apply a state transition, persisting atomically."""
        record = self.load(task_id)
        current = record.state

        if not is_transition_allowed(current, target):
            raise InvalidStateTransition(
                f"Cannot transition task from {current.value} to {target.value}.",
                details={
                    "from": current.value,
                    "to": target.value,
                    "allowed": sorted(s.value for s in _allowed_targets(current)),
                },
            )

        unknown = set(updates) - _TRANSITION_UPDATABLE_FIELDS
        if unknown:
            raise InvalidStateTransition(
                "Transition update touched fields outside the state record's "
                "mutable surface.",
                details={
                    "task_id": task_id,
                    "unknown_fields": sorted(unknown),
                    "allowed_fields": sorted(_TRANSITION_UPDATABLE_FIELDS),
                },
            )

        for key, value in updates.items():
            setattr(record, key, value)

        record.state = target
        record.state_history.append(
            {
                "from": current.value,
                "to": target.value,
                "at": utc_now().isoformat(),
                "reason": reason,
            }
        )

        self.save(record)
        return record

    # -- runs ---------------------------------------------------------------

    def append_run(self, task_id: str, run: RunRecord) -> None:
        """Write ``run_dir/dispatcher-result.json``; increments ``run_count``."""
        record = self.load(task_id)
        run_index = run.metadata.run_index
        run_dir = self.run_dir(task_id, run_index)
        _mkdir(run_dir)

        payload = json.loads(run.model_dump_json())
        atomic_write_json(run_dir / "dispatcher-result.json", payload, mode=_FILE_MODE)

        record.run_count = max(record.run_count, run_index)
        self.save(record)

    def load_runs(self, task_id: str) -> list[RunRecord]:
        """All runs, ordered by run_index."""
        runs_root = self.task_dir(task_id) / "runs"
        if not runs_root.exists():
            return []
        runs: list[RunRecord] = []
        for entry in sorted(runs_root.iterdir(), key=lambda p: p.name):
            result_path = entry / "dispatcher-result.json"
            if not result_path.exists():
                continue
            # A planted symlink under runs/ must not turn a state read into a
            # read of an arbitrary file elsewhere on the host.
            self._contained(result_path, task_id=task_id)
            data = _read_json_plain(
                result_path,
                task_id=task_id,
                what=f"runs/{entry.name}/dispatcher-result.json",
            )
            try:
                runs.append(RunRecord.model_validate(data))
            except ValidationError as exc:
                raise StateCorruption(
                    f"runs/{entry.name}/dispatcher-result.json failed schema validation.",
                    details={"task_id": task_id, "reason": str(exc)},
                ) from exc
        runs.sort(key=lambda r: r.metadata.run_index)
        return runs

    def latest_run(self, task_id: str) -> RunRecord | None:
        runs = self.load_runs(task_id)
        return runs[-1] if runs else None

    # -- reviews --------------------------------------------------------

    def append_review(self, task_id: str, review: FableReview) -> int:
        """Write ``reviews/fable-NNN.json``; returns the review number.

        Bumps ``fable_review_count``.
        """
        record = self.load(task_id)
        review_number = record.fable_review_count + 1
        reviews_dir = self._reviews_dir(task_id)
        _mkdir(reviews_dir)

        payload = json.loads(review.model_dump_json())
        review_path = self._contained(
            reviews_dir / f"fable-{review_number:03d}.json", task_id=task_id
        )
        atomic_write_json(review_path, payload, mode=_FILE_MODE)

        record.fable_review_count = review_number
        self.save(record)
        return review_number

    def load_reviews(self, task_id: str) -> list[FableReview]:
        reviews_dir = self._reviews_dir(task_id)
        if not reviews_dir.exists():
            return []
        reviews: list[FableReview] = []
        for entry in sorted(reviews_dir.glob("fable-*.json")):
            self._contained(entry, task_id=task_id)
            data = _read_json_plain(entry, task_id=task_id, what=f"reviews/{entry.name}")
            # FableReview is not itself versioned; its container (state.json /
            # dispatcher-result.json) carries schema_version. We still require
            # the review file's own JSON to parse and validate.
            try:
                reviews.append(FableReview.model_validate(data))
            except ValidationError as exc:
                raise StateCorruption(
                    f"reviews/{entry.name} failed schema validation.",
                    details={"task_id": task_id, "reason": str(exc)},
                ) from exc
        return reviews

    # -- evidence -------------------------------------------------------

    def _evidence_path(self, task_id: str, name: str) -> Path:
        if "/" in name or "\\" in name or ".." in name or name in {"", ".", ".."}:
            raise InvalidTaskEnvelope(
                "Invalid evidence file name.",
                details={"task_id": repr(task_id), "name": repr(name)},
            )
        # The checks above are kept verbatim (never weaken an existing check);
        # the allowlist below additionally refuses control characters, absolute
        # spellings, leading dots and unbounded names, and the containment
        # check refuses a symlinked evidence file pointing out of the tree.
        safe_name = _reject_unsafe_component(name, what="evidence name")
        return self._contained(
            self._evidence_dir(task_id) / safe_name, task_id=task_id
        )

    def write_evidence(self, task_id: str, name: str, content: str) -> Path:
        """Write ``evidence/<name>``; ``name`` is validated (no ``/``, no ``..``)."""
        path = self._evidence_path(task_id, name)
        atomic_write_text(path, content, mode=_FILE_MODE)
        return path

    def read_evidence(self, task_id: str, name: str) -> str | None:
        path = self._evidence_path(task_id, name)
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StateCorruption(
                "evidence file could not be read.",
                details={"task_id": task_id, "name": name, "reason": str(exc)},
            ) from exc


def _allowed_targets(state: TaskState) -> frozenset[TaskState]:
    from .models import ALLOWED_TRANSITIONS

    return ALLOWED_TRANSITIONS[state]
