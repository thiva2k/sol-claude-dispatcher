"""The stdio MCP server (brief §6, §7). — Wave 4.

Exactly four tools, no more:

* ``dispatch_claude_task``     — create a new implementation worker (§7.1)
* ``resume_claude_task``       — continue an existing conversation (§7.2)
* ``review_task_with_fable``   — independent read-only review (§7.3)
* ``get_task``                 — read authoritative state, read-only (§7.4)

This layer contains no intelligence. It validates input, calls the deterministic
modules, and returns structured results. It never decides architecture, never
decides approval, and never invents a next action.

Transport is **stdio**. §28: application logging goes to stderr or a file, never
to stdout — stdout belongs to the MCP JSON-RPC transport, and a stray ``print``
corrupts the protocol.

SDK reality (see ``docs/DISCOVERY.md``) — mcp 2.0.0::

    from mcp.server import MCPServer          # NOT mcp.server.fastmcp
    server = MCPServer(name=..., instructions=..., version=...)

    @server.tool(name="dispatch_claude_task", description=...)
    async def dispatch(...) -> dict: ...

    server.run(transport="stdio")             # or: await server.run_stdio_async()

Startup refuses to initialise when ``SOL_WORKER=1`` is present in the
environment without the explicit internal test override (§22 layer 4).

Layering note
-------------

The tool bodies live on :class:`Dispatcher` rather than inside the decorated
functions. The MCP decorators are three-line adapters over those methods, so
the whole lifecycle is testable without a stdio client, and the registered tool
surface stays trivially auditable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import stat
import sys
import traceback
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, TYPE_CHECKING, cast

from pydantic import ValidationError

from . import __version__
from .config import (
    Config,
    MAX_APPEND_SYSTEM_PROMPT_BYTES,
    MEASURED_SINGLE_ARGV_LIMIT_BYTES,
    load_config,
)
from .config_authority import (
    CONFIG_ENV_VAR,
    DEFAULT_CONFIG_PATH,
    assert_production_config_authority,
    canonical_production_config_path,
)
from .errors import (
    ClaudeExecutionFailed,
    ClaudeStructuredOutputInvalid,
    ClaudeTimedOut,
    DispatcherError,
    EvidenceExceedsReviewBudget,
    GitEvidenceCollectionFailed,
    EvidenceFreezeViolated,
    EvidenceIncompleteForReview,
    InternalDispatcherError,
    InvalidStateTransition,
    InvalidTaskEnvelope,
    PolicyViolation,
    RepositoryAdministrationUnreconciled,
    ResumeLimitReached,
    StateCorruption,
    WorktreeBaseMismatch,
    WorktreeCreationFailed,
)
from .git import (
    DiffEvidence,
    ScopeCheck,
    check_scope,
    create_worktree,
    primary_tree_status,
    resolve_base_commit,
    resolve_worktree,
    worktree_head,
)
from .evidence.prepare import (
    PreparedDispatch,
    PreparedResume,
    capture_matching_repository_authority,
    capture_primary_head,
    primary_snapshots_equal,
    prepare_dispatch,
    prepare_resume,
)
from .evidence.identity import (
    RepositoryAuthoritySnapshot,
    capture_repository_authority,
    classify_dot_git,
)
from .evidence.identity_record import (
    ApprovedIdentityFacts,
    RepositoryIdentityRecord,
)
from .evidence.attribution import attribute_snapshots, require_attributable
from .evidence.content import ContentInput, classify_inventory
from .evidence.fssnap import FsEntry, FsSnapshot, capture_snapshot
from .evidence.freeze import EvidenceFreeze, capture_evidence_freeze, verify_evidence_freeze
from .evidence.gitadmin import (
    capture_repository_administration,
    reconcile_repository_administration,
    repository_identity_key,
)
from .evidence.inventory import ScopeSpecBytes, decide_scope
from .evidence.patch import build_canonical_evidence
from .evidence.prepare import read_snapshot_entry_bytes
from .evidence.scope import (
    ScopeVerdictSet,
    decide_scope_verdicts,
    load_prior_cumulative_worker,
)
from .evidence.seal import load_task_seal
from .evidence.worktreeauth import (
    decode_worktree_authority,
    verify_worktree_authority,
)
from .phase import (
    ExecutionPhase,
    ToolExecution,
    begin_tool_execution,
    current_execution,
)
from .locks import RepositoryLock
from .models import (
    ALLOWED_TRANSITIONS,
    RunKind,
    RunMetadata,
    RunRecord,
    TaskEnvelope,
    TaskRecord,
    TaskRequest,
    TaskState,
    ValidationResult,
    WorkerResult,
    WorkerRole,
    WorkerStatus,
    WorktreeBaseAnchor,
    is_transition_allowed,
    new_run_id,
    new_session_id,
    new_task_id,
    utc_now,
)
from .results import build_dispatcher_observations, parse_fable_review, parse_worker_result
from .router import explain_route
from .runner import (
    ALWAYS_DISALLOWED_TOOLS,
    EXECVE_ARGV_SAFETY_RESERVE_BYTES,
    WorkerInvocation,
    WorkerRun,
    build_argv,
    build_fable_invocation,
    build_worker_invocation,
    cli_failure,
    envelope_facts,
    fable_policy_text,
    measure_execve_transport,
    provider_failure,
    run_worker,
    worker_policy_text,
)
from .lifecycle import (
    LifecyclePhase,
    LifecycleProfileEngine,
    PhaseComposition,
    compose_append_system_prompt,
    preflight_lifecycle,
)
from .security import (
    assert_dispatch_depth,
    assert_no_recursion,
    authorize_repository_root,
    redact,
    validate_repository_root,
    validate_task_id,
)
from .sessions import new_session, resume_limit_response, resume_plan
from .state import TaskStore, atomic_write_json, atomic_write_text
from .validation import (
    assert_validation_budget,
    compare_claims_to_validation,
    run_validations,
)
from .waiting import WORKER_ACTIONABLE_STATES, RunRegistry, blocking_envelope
from .worker_context import WorkerContext, WorkerContextComposer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp.server import MCPServer

__all__ = [
    "SERVER_INSTRUCTIONS",
    "TOOL_NAMES",
    "TOOL_DESCRIPTIONS",
    "WORKER_ACTIONABLE_STATES",
    "Dispatcher",
    "build_dispatcher",
    "build_server",
    "configure_logging",
    "resolve_config_path",
    "canonical_production_config_path",
    "assert_production_config_authority",
    "CONFIG_ENV_VAR",
    "DEFAULT_CONFIG_PATH",
    "main",
]

#: §6 — the first thing Sol reads about this server.
#:
#: GATE 6 §8: the blocking paragraphs below are load-bearing. A correct
#: server-side wait is still defeated if the model is told to poll, so the
#: no-poll instruction is treated as part of the implementation and is pinned by
#: literal assertions in ``tests/unit/test_blocking_contract.py``.
SERVER_INSTRUCTIONS = """\
Sol is the sole orchestrator and final reviewer.
Use dispatch_claude_task for new implementation work.
Use resume_claude_task only to continue an existing implementation.
Use review_task_with_fable only for independent review.
Worker completion is evidence, never approval.
Workers must never delegate recursively.

This dispatcher is a deterministic execution and control layer. It makes no
architectural decisions, and it never marks work approved. Implementation
completion, review completion, and user approval are three distinct states and
must not be collapsed. Fable's verdict is advisory: it informs Sol and never
changes approval state.

dispatch_claude_task and resume_claude_task block: the tool call stays pending
server-side for the whole Claude run and returns only when the run reaches a
state that requires a decision from Sol — awaiting_sol_review, timed_out,
blocked, failed or policy_violation. review_task_with_fable blocks until Fable's
review is complete. One call is one worker run, and its result already carries
the final state, the worker's claims, the dispatcher's own observations and the
validation results.

Do NOT poll get_task after dispatch_claude_task or resume_claude_task. The
result you already received is the authoritative outcome; calling get_task to
find out whether the worker finished wastes tokens and ends the turn for no
information.

Do not call get_task while a dispatch, resume or review call is still pending
either. If the runtime hands you a background-task handle, or reports the call
as "still running", that is not permission to poll: it is the runtime waiting on
your behalf. Stay idle, and continue the goal when the result arrives. Do not
start a second worker because the first call has not returned yet.

get_task is recovery and status tooling only. Call it when a tool call was
interrupted before it returned, or to inspect a task this turn did not just
run — never as a wait loop, and never in a retry loop against a running worker.

If a dispatch or resume call is interrupted, the worker keeps running: the
dispatcher owns it, not the tool call. Its state and evidence are still
persisted, and get_task on that task id returns the authoritative result.
"""

#: The complete tool surface. Four, deliberately (§7). Anything else belongs to
#: Sol, not to the dispatcher.
TOOL_NAMES: tuple[str, ...] = (
    "dispatch_claude_task",
    "resume_claude_task",
    "review_task_with_fable",
    "get_task",
)

TOOL_DESCRIPTIONS: dict[str, str] = {
    "dispatch_claude_task": (
        "Dispatch a new Claude implementation worker into an isolated git "
        "worktree. The dispatcher generates every identifier (task id, run id, "
        "session id, worktree name) and returns worker claims and dispatcher "
        "observations separately. Completion is evidence, never approval. "
        "This call BLOCKS until the worker reaches a state requiring a decision "
        "from Sol: awaiting_sol_review, timed_out, blocked, failed or "
        "policy_violation. Do not call get_task while this call is pending. "
        "Do not poll get_task afterwards — the returned "
        "payload is already the final state of this run."
    ),
    "resume_claude_task": (
        "Continue an existing task's worker conversation in the same session, "
        "model and worktree. Session identity comes from stored state, never "
        "from the caller. Refuses past the configured resume cap. "
        "This call BLOCKS until the resumed worker reaches a state requiring a "
        "decision from Sol: awaiting_sol_review, timed_out, blocked, failed or "
        "policy_violation. Do not call get_task while this call is pending. "
        "Do not poll get_task afterwards — the returned "
        "payload is already the final state of this run."
    ),
    "review_task_with_fable": (
        "Run an independent, read-only Fable review of a task's recorded "
        "evidence in a fresh session. The verdict is advisory to Sol and never "
        "changes approval state. This call BLOCKS until the review is complete "
        "and returns it in one result. No polling is required while it is "
        "pending. Do not poll get_task afterwards."
    ),
    "get_task": (
        "Read a task's authoritative state: envelope, status, model, worktree, "
        "session, resume count, run and validation history, latest worker "
        "result, latest Fable review, policy violations and timeout info. "
        "Read-only recovery and status tooling. It is not needed on the normal "
        "path, because dispatch_claude_task and resume_claude_task already wait "
        "for the worker. Use it when a tool call was interrupted before it "
        "returned, or to inspect a task this turn did not just run. Never call "
        "it in a loop to wait for a worker, and never use it to poll an active "
        "dispatch, resume or review."
    ),
}

#: B4. ``CONFIG_ENV_VAR`` and ``DEFAULT_CONFIG_PATH`` are re-exported from
#: :mod:`sol_claude_dispatcher.config_authority`, which now owns both. The
#: variable is a TEST/DEVELOPMENT selector for the disposable stdio harness; it
#: chooses nothing on the production path, where it is read only in order to
#: refuse startup. See that module for the whole boundary.

#: ``security.assert_no_recursion`` ignores its ``config`` argument (the check
#: is unconditional). Startup runs it *before* config loading so a dispatcher
#: launched inside a worker refuses immediately, whatever the config says.
_NO_CONFIG = cast("Config", None)

#: argv elements longer than this are elided in ``RunMetadata.argv_redacted``.
#: The full policy text and JSON schema are already on disk; repeating them in
#: every run record would bloat state for no audit value.
_MAX_RECORDED_ARGV_ELEMENT = 512

#: Kernel argv headroom deliberately left unused by Fable.  This is distinct
#: from the authored-context reserve: it protects the complete argv+envp
#: transport accounting performed immediately before reviewer launch.
_FABLE_ARGV_SAFETY_RESERVE_BYTES = EXECVE_ARGV_SAFETY_RESERVE_BYTES

#: Cap on any single evidence section rendered into a prompt.
_MAX_PROMPT_SECTION_CHARS = 8_000

logger = logging.getLogger("sol_claude_dispatcher.server")


# ---------------------------------------------------------------------------
# primary-tree non-interference (P1-5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrimaryTreeSnapshot:
    """A fingerprint of the *primary* working tree at one instant (P1-5).

    Two facts, both measured by git and both cheap: the commit ``HEAD`` points
    at, and the full ``git status --porcelain`` text. Together they detect a
    commit, a checkout, a tracked-file modification or deletion, a staged
    change, and an untracked addition.

    Deliberately **not** a security boundary. See :func:`compare_primary_tree`.
    """

    head_commit: str
    porcelain_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "head_commit": self.head_commit,
            "porcelain_status": self.porcelain_status,
            "status_lines": self.porcelain_status.splitlines(),
        }


def snapshot_primary_tree(repository_root: Path) -> PrimaryTreeSnapshot:
    """Fingerprint the primary tree, failing closed (P0-3, P1-5).

    Both underlying git calls raise rather than degrade: ``primary_tree_status``
    raises :class:`GitEvidenceCollectionFailed` and ``resolve_base_commit``
    raises :class:`~sol_claude_dispatcher.errors.InvalidRepository`. A snapshot
    that could not be taken must never look like an unchanged one, so neither is
    caught here.
    """
    status = primary_tree_status(repository_root)
    head = resolve_base_commit(repository_root, "HEAD")
    return PrimaryTreeSnapshot(head_commit=head, porcelain_status=status)


def compare_primary_tree(
    before: PrimaryTreeSnapshot, after: PrimaryTreeSnapshot
) -> dict[str, Any] | None:
    """Return a divergence report, or ``None`` when the invariant held (P1-5).

    The invariant is ``post_state == pre_state`` — **not** "the primary tree is
    clean". A tree that was already dirty when the worker started and is dirty
    in exactly the same way afterwards satisfies it; requiring cleanliness would
    refuse ordinary working repositories and would still miss the interesting
    case (a worker that dirties an already-dirty tree).

    Honest limitation, and it must stay in the docs: without OS-level sandboxing
    a worker could modify a file and restore it before exiting, and this
    comparison would not see it. It also cannot see a change to a git-ignored
    file. This is *detection*, not containment.
    """
    before_lines = before.porcelain_status.splitlines()
    after_lines = after.porcelain_status.splitlines()
    appeared = sorted(set(after_lines) - set(before_lines))
    disappeared = sorted(set(before_lines) - set(after_lines))
    head_changed = before.head_commit != after.head_commit

    if not head_changed and not appeared and not disappeared:
        return None

    return {
        "head_changed": head_changed,
        "head_before": before.head_commit,
        "head_after": after.head_commit,
        "status_entries_appeared": appeared,
        "status_entries_disappeared": disappeared,
    }


# ---------------------------------------------------------------------------
# worktree base identity (B2)
# ---------------------------------------------------------------------------


def assert_worktree_base(
    worktree_path: Path,
    *,
    expected_base_commit: str,
    task_id: str,
    worktree_name: str,
    base_ref: str,
    phase: str,
) -> str:
    """INVARIANT B2. Return the measured head, or raise ``WorktreeBaseMismatch``.

    ::

        actual worktree HEAD == envelope.repository.base_commit

    Exact, full-40-character equality, measured by ``git rev-parse HEAD``
    **inside** the worktree. Deliberately **not**:

    * an ancestry test — task ``49231f6e``'s recorded base was a genuine
      ancestor of the commit its worktree was actually on, and an
      ancestry-tolerant check would have waved through 120 commits of other
      people's work reported as that worker's output;
    * a merge-base test — same hole, wider;
    * a prefix or short-SHA comparison;
    * "adopt what we observed" — the recorded base is what Sol approved, and
      rewriting it to match reality is the silent repair ``CLAUDE.md`` §2
      forbids.

    A descendant is not "close enough" either: it still contributes foreign
    commits to every diff the dispatcher takes.
    """
    actual = worktree_head(worktree_path)
    if actual != expected_base_commit:
        raise WorktreeBaseMismatch(
            "The isolated worktree is not on the commit this task recorded as "
            "its base, so no measurement taken in it can be trusted.",
            details={
                "task_id": task_id,
                "phase": phase,
                "worktree_name": worktree_name,
                "worktree_path": str(worktree_path),
                "base_ref": base_ref,
                "expected_base_commit": expected_base_commit,
                "actual_head_commit": actual,
            },
            remediation=(
                "No evidence was collected for this run, because it would have "
                "described a tree that never existed: base divergence would be "
                "attributed to the worker, and a worker change that happens to "
                "restore a file to the recorded base's content would vanish "
                f"entirely. The worktree is on {actual}. Re-dispatch with "
                "repository.base_ref naming the commit you intend, or "
                "reconcile the worktree so it is on the recorded base. The "
                "dispatcher will not adopt the observed commit as the base."
            ),
        )
    return actual


def _interference_markers(divergence: dict[str, Any]) -> list[str]:
    """Policy-violation strings for a primary-tree divergence, for state."""
    if "worker" in divergence or "validation" in divergence:
        markers: list[str] = []
        for actor in ("worker", "validation"):
            interval = divergence.get(actor)
            if interval is None:
                continue
            actor_markers = _interference_markers(interval)
            markers.extend(f"{actor}:{marker}" for marker in actor_markers)
            # Retain the established worker marker surface for stored-state
            # compatibility.  Validation markers are always actor-qualified:
            # they must never be reported as worker interference.
            if actor == "worker":
                markers.extend(actor_markers)
        return markers
    if "status_entries_appeared" not in divergence:
        markers = [
            "primary_tree_snapshot:"
            f"{str(divergence.get('before_digest', 'unknown'))[:12]}->"
            f"{str(divergence.get('after_digest', 'unknown'))[:12]}"
        ]
        markers += [
            f"primary_tree_appeared:?? {path}"
            for path in divergence.get("appeared", [])
        ]
        markers += [
            f"primary_tree_disappeared:{path}"
            for path in divergence.get("disappeared", [])
        ]
        markers += [
            f"primary_tree_changed:{path}"
            for path in divergence.get("changed", [])
        ]
        if divergence.get("head_changed"):
            markers.append(
                "primary_tree_head:"
                f"{divergence['head_before']['digest'][:12]}->"
                f"{divergence['head_after']['digest'][:12]}"
            )
        return markers
    markers: list[str] = []
    if divergence["head_changed"]:
        markers.append(
            "primary_tree_head:"
            f"{divergence['head_before'][:12]}->{divergence['head_after'][:12]}"
        )
    markers += [f"primary_tree_appeared:{line}" for line in divergence["status_entries_appeared"]]
    markers += [
        f"primary_tree_disappeared:{line}" for line in divergence["status_entries_disappeared"]
    ]
    return markers


def _primary_terminal_divergence(
    before_tree: FsSnapshot,
    before_head: Any,
    after_tree: FsSnapshot,
    after_head: Any,
    *,
    expected_root: bytes,
    attributed_to: str,
    interval: str,
) -> dict[str, Any] | None:
    """Return one raw primary-authority interval, or ``None`` if it held.

    The function deliberately compares adjacent terminals.  Comparing only
    WORKER_START with VALIDATION_EXIT would let validation restore a worker
    escape and erase the evidence of who caused it.
    """

    tree_changed = not primary_snapshots_equal(
        before_tree,
        after_tree,
        expected_root=expected_root,
    )
    head_changed = before_head != after_head
    if not tree_changed and not head_changed:
        return None

    before_by_path = {bytes(entry.path): entry for entry in before_tree.entries}
    after_by_path = {bytes(entry.path): entry for entry in after_tree.entries}
    before_paths = set(before_by_path)
    after_paths = set(after_by_path)
    return {
        "attributed_to": attributed_to,
        "interval": interval,
        "before_digest": before_tree.digest,
        "after_digest": after_tree.digest,
        "head_before": before_head.to_dict(),
        "head_after": after_head.to_dict(),
        "head_changed": head_changed,
        "appeared": sorted(os.fsdecode(path) for path in after_paths - before_paths),
        "disappeared": sorted(
            os.fsdecode(path) for path in before_paths - after_paths
        ),
        "changed": sorted(
            os.fsdecode(path)
            for path in before_paths & after_paths
            if before_by_path[path] != after_by_path[path]
        ),
    }


def _combine_primary_terminal_divergences(
    worker: dict[str, Any] | None,
    validation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Preserve both adjacent divergences plus a compatibility summary."""

    intervals = [item for item in (worker, validation) if item is not None]
    if not intervals:
        return None
    return {
        "worker": worker,
        "validation": validation,
        "attributed_to": [item["attributed_to"] for item in intervals],
        "head_changed": any(bool(item["head_changed"]) for item in intervals),
        "appeared": sorted(
            {path for item in intervals for path in item.get("appeared", [])}
        ),
        "disappeared": sorted(
            {path for item in intervals for path in item.get("disappeared", [])}
        ),
        "changed": sorted(
            {path for item in intervals for path in item.get("changed", [])}
        ),
    }


def _administrative_markers(
    divergences: list[dict[str, Any]],
) -> list[str]:
    """Stable state markers for worker/validation administrative tampering."""

    markers: list[str] = []
    for divergence in divergences:
        actor = str(divergence["attributed_to"])
        details = divergence.get("details", {})
        named = False
        for key in (
            "removed_exact",
            "added_exact",
            "changed_exact",
            "removed_registration",
            "added_registration",
            "changed_registration",
            "removed_loose",
            "changed_loose",
            "unvalidated_new_loose",
        ):
            for path in details.get(key, []):
                markers.append(f"git_admin_{actor}:{key}:{path}")
                named = True
        if not named:
            markers.append(f"git_admin_{actor}:unknown")
    return markers


# ---------------------------------------------------------------------------
# logging (§28) — stderr or a file. Never stdout.
# ---------------------------------------------------------------------------


class _RedactingFormatter(logging.Formatter):
    """Applies :func:`security.redact` to every rendered record."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(config: Config) -> None:
    """Attach a redacting handler on stderr (or the configured log file).

    Never attaches a stdout handler: stdout is the MCP JSON-RPC transport and a
    single stray byte on it corrupts the protocol (§28).
    """
    root = logging.getLogger("sol_claude_dispatcher")
    for existing in list(root.handlers):
        root.removeHandler(existing)

    handler: logging.Handler
    log_file = config.logging.log_file
    if log_file:
        path = Path(log_file)
        if not path.is_absolute():
            path = Path(config.project_root) / path
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    else:
        handler = logging.StreamHandler(stream=sys.stderr)

    handler.setFormatter(
        _RedactingFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root.addHandler(handler)
    root.setLevel(config.logging.level)
    root.propagate = False


def _event(event: str, **fields: Any) -> None:
    """Structured operational log line (§28): task_id, run_id, event, ..."""
    logger.info("%s %s", event, json.dumps(fields, default=str, sort_keys=True))


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _compact_issues(exc: ValidationError) -> list[dict[str, str]]:
    """Compact pydantic errors — never a raw dump across the MCP boundary (§29)."""
    return [
        {
            "location": ".".join(str(part) for part in err["loc"]) or "<root>",
            "problem": err["msg"],
        }
        for err in exc.errors()
    ]


def _redact_argv(argv: list[str]) -> list[str]:
    """Redact secrets and elide bulky elements for the persisted run record."""
    out: list[str] = []
    for element in argv:
        safe = redact(element)
        if len(safe) > _MAX_RECORDED_ARGV_ELEMENT:
            safe = (
                safe[:_MAX_RECORDED_ARGV_ELEMENT]
                + f"...[elided {len(safe) - _MAX_RECORDED_ARGV_ELEMENT} chars]"
            )
        out.append(safe)
    return out


def _clip(text: str, limit: int = _MAX_PROMPT_SECTION_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[...truncated at {limit} characters by the dispatcher]"


def _dump(model: Any) -> Any:
    """Model -> plain JSON-safe data for a tool response."""
    if model is None:
        return None
    return json.loads(model.model_dump_json())


def _argument_digest(*parts: Any) -> str:
    """Stable short digest of a tool call's arguments (GATE 6 §5).

    Used only to key the in-flight run registry, never for security and never
    persisted. Two calls digest the same exactly when their arguments are
    identical, which is what makes "a reconnect retry attaches, a different
    instruction does not" a mechanical rule rather than a judgement.
    """
    material = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _resume_key(task_id: str, instruction: str, timeout_seconds: int | None) -> str:
    return f"resume:{task_id}:{_argument_digest(instruction, timeout_seconds)}"


def _review_key(task_id: str, focus: list[str] | None) -> str:
    return f"review:{task_id}:{_argument_digest(list(focus or []))}"


def _assert_fable_review_transition_allowed(record: TaskRecord) -> None:
    """Refuse a review whose eventual state transition is already illegal.

    Review legality is a PREPARE invariant, not something to discover after a
    reviewer has run and a review has been appended. Keep the error shape
    identical to :meth:`TaskStore.transition`; the state machine in
    ``models.py`` remains the sole authority for which source states are legal.
    """
    target = TaskState.FABLE_REVIEWED
    if is_transition_allowed(record.state, target):
        return
    raise InvalidStateTransition(
        f"Cannot transition task from {record.state.value} to {target.value}.",
        details={
            "from": record.state.value,
            "to": target.value,
            "allowed": sorted(
                state.value for state in ALLOWED_TRANSITIONS[record.state]
            ),
        },
    )


def attribute_changed_paths(
    worker_evidence: DiffEvidence, final_evidence: DiffEvidence
) -> dict[str, Any]:
    """Split the final changed-path set by who produced it (P1-7).

    Dispatcher validation commands legitimately mutate a worktree — formatters,
    coverage files, lockfiles, snapshot updates. The *authoritative* scope and
    policy decision uses the final state (that is what is really on disk), but
    the record has to keep the attribution, or Claude gets blamed for a file the
    dispatcher's own validation created.

    Set difference is enough for V1: a path present after validation and absent
    before it was added by validation, and vice versa. A path in both sets whose
    *contents* validation rewrote is still attributed to the worker — noted
    honestly rather than papered over.
    """
    worker_paths = list(worker_evidence.changed_paths)
    final_paths = list(final_evidence.changed_paths)
    worker_set = set(worker_paths)
    final_set = set(final_paths)
    return {
        "worker_changed_paths": worker_paths,
        "final_changed_paths": final_paths,
        "validation_added_paths": sorted(final_set - worker_set),
        "validation_removed_paths": sorted(worker_set - final_set),
        "attribution_method": "set_difference",
        "attribution_caveat": (
            "A path changed by the worker and then rewritten by a validation "
            "command appears only under worker_changed_paths; set difference "
            "cannot separate authorship of a single path."
        ),
    }


def _content_kind(entry: FsEntry) -> str:
    return {
        "block_device": "block",
        "char_device": "char",
        "unknown": "fifo",
    }.get(entry.kind, entry.kind)


def _snapshot_content_input(
    entry: FsEntry | None,
    *,
    root: Path,
    sealed_start_root: Path | None = None,
) -> ContentInput:
    """Build content authority from a measured snapshot without Git."""
    if entry is None:
        return ContentInput.absent()
    kind = _content_kind(entry)
    if entry.read_error is not None:
        return ContentInput(kind, None, entry.perm, entry.read_error)  # type: ignore[arg-type]
    if entry.kind not in {"regular", "symlink"}:
        return ContentInput(kind, None, entry.perm)  # type: ignore[arg-type]
    if sealed_start_root is not None:
        if entry.content_hash is None:
            return ContentInput(kind, None, entry.perm, "sealed_identity_absent")  # type: ignore[arg-type]
        path = sealed_start_root / "start-content" / entry.content_hash
        try:
            data = path.read_bytes()
        except OSError:
            return ContentInput(kind, None, entry.perm, "sealed_content_absent")  # type: ignore[arg-type]
    else:
        data = read_snapshot_entry_bytes(root, entry)
    if entry.kind == "symlink":
        return ContentInput.symlink(data)
    return ContentInput.regular(data, executable=bool(entry.perm & 0o111))


def _canonical_evidence_record(canonical: Any, *, run_index: int) -> dict[str, Any]:
    """Return the durable, single-source completeness and byte record."""

    patch_file_complete = bool(canonical.patch_file_complete)
    changes = {bytes(change.path): change for change in canonical.changes}
    inventory: list[dict[str, Any]] = []
    for row in canonical.per_path:
        change = changes[bytes(row.path)]
        carried = change.new if change.new.kind != "absent" else change.old
        inventory.append(
            {
                "path": os.fsdecode(row.path),
                "change": change.change,
                "mode": None if carried.mode is None else f"{carried.mode:06o}",
                "size": carried.size,
                "sha256": carried.sha256_digest,
                "content_class": row.content_class.value,
                "section_count": len(row.sections),
                "omission_reason": row.omission_reason,
                "inventory_complete": row.inventory_complete,
            }
        )
    return {
        "schema": "canonical-evidence/1",
        "implementer_run_index": run_index,
        "base_commit": canonical.base_commit,
        "patch_relpath": "evidence/diff.patch",
        "patch_file_complete": patch_file_complete,
        "patch_bytes": canonical.patch_bytes,
        "patch_sha256": canonical.patch_sha256,
        "per_path": inventory,
    }


# ---------------------------------------------------------------------------
# prompt assembly — deterministic text, no LLM, no caller-controlled flags
# ---------------------------------------------------------------------------


def build_worker_prompt(envelope: TaskEnvelope) -> str:
    """Render the implementation worker's task prompt from the envelope (§11).

    Everything here comes from the *validated envelope*. The prompt is data for
    the worker; the enforcement lives in the tool list, the deny list, the
    environment and the post-run scope check (§13, §22). Prompts are not
    sandboxing.
    """
    lines = [
        "# Implementation task",
        "",
        envelope.task.objective.strip(),
        "",
        f"Task id: {envelope.task_id}",
        f"Repository: {envelope.repository.root}",
        f"Base commit: {envelope.repository.base_commit}",
        f"Isolated worktree: {envelope.worktree_name}",
    ]

    if envelope.task.context.strip():
        lines += ["", "## Context", "", _clip(envelope.task.context.strip())]

    if envelope.task.acceptance_criteria:
        lines += ["", "## Acceptance criteria", ""]
        lines += [f"{i}. {c}" for i, c in enumerate(envelope.task.acceptance_criteria, 1)]

    lines += ["", "## Scope", ""]
    if envelope.scope.allowed_paths:
        lines.append("Only these paths may be changed:")
        lines += [f"- {p}" for p in envelope.scope.allowed_paths]
    else:
        lines.append("No explicit allow-list was supplied; stay inside the task's subject area.")
    if envelope.scope.forbidden_paths:
        lines += ["", "These paths must not be changed under any circumstance:"]
        lines += [f"- {p}" for p in envelope.scope.forbidden_paths]
    lines += [
        "",
        "The dispatcher independently diffs the worktree after you exit and "
        "flags any change outside this scope as a policy violation.",
    ]

    constraints = envelope.constraints
    lines += [
        "",
        "## Constraints",
        "",
        f"- network access allowed: {str(constraints.allow_network).lower()}",
        f"- git push allowed: {str(constraints.allow_push).lower()}",
        f"- git merge allowed: {str(constraints.allow_merge).lower()}",
        f"- git commit allowed: {str(constraints.allow_commit).lower()}",
        f"- subagents allowed: {str(constraints.allow_subagents).lower()}",
        "- you must not dispatch, spawn or delegate to another agent",
    ]

    if envelope.validation.commands:
        lines += [
            "",
            "## Validation the dispatcher will re-run independently",
            "",
        ]
        lines += [f"- {' '.join(cmd.argv)}" for cmd in envelope.validation.commands]

    lines += [
        "",
        "## Output contract",
        "",
        "Return exactly one JSON object matching the supplied --json-schema. "
        "Report honestly: 'blocked' and 'failed' are valid, useful outcomes. "
        "Your report is a claim; the dispatcher measures the repository itself.",
    ]
    return "\n".join(lines)


def build_resume_prompt(envelope: TaskEnvelope, instruction: str) -> str:
    """Render the resume prompt (§7.2). Only ``instruction`` comes from Sol."""
    lines = [
        "# Continue this task",
        "",
        instruction.strip(),
        "",
        "## Unchanged task constraints",
        "",
        f"Task id: {envelope.task_id}",
        f"Base commit: {envelope.repository.base_commit}",
        f"Objective: {envelope.task.objective.strip()}",
    ]
    if envelope.scope.allowed_paths:
        lines += ["", "Allowed paths:"] + [f"- {p}" for p in envelope.scope.allowed_paths]
    if envelope.scope.forbidden_paths:
        lines += ["", "Forbidden paths:"] + [f"- {p}" for p in envelope.scope.forbidden_paths]
    lines += [
        "",
        "Scope, constraints and acceptance criteria are unchanged from the "
        "original dispatch. Stay in this worktree; do not create another.",
        "",
        "Return exactly one JSON object matching the supplied --json-schema.",
    ]
    return "\n".join(lines)


def build_fable_prompt(
    envelope: TaskEnvelope,
    *,
    diff_text: str,
    inventory: list[dict[str, Any]],
    worker_claims: WorkerResult | None,
    validation_results: list[Any],
    focus: list[str],
    attribution: dict[str, list[str]],
) -> str:
    """Render exactly §5.11's six Fable sections from one worker run."""
    prefix, suffix = _fable_prompt_parts(
        envelope,
        inventory=inventory,
        worker_claims=worker_claims,
        validation_results=validation_results,
        focus=focus,
        attribution=attribution,
    )
    return prefix + diff_text + suffix


def _fable_prompt_parts(
    envelope: TaskEnvelope,
    *,
    inventory: list[dict[str, Any]],
    worker_claims: WorkerResult | None,
    validation_results: list[Any],
    focus: list[str],
    attribution: dict[str, list[str]],
) -> tuple[str, str]:
    """Return the exact prompt bytes before and after the frozen patch."""
    lines = [
        "## SECTION 1 — TASK",
        "",
        "You are reviewing work produced by a different agent. You do not "
        "implement, and you do not modify files.",
        "",
        f"Task id: {envelope.task_id}",
        f"Base commit: {envelope.repository.base_commit}",
        f"Objective: {envelope.task.objective.strip()}",
    ]
    if envelope.task.acceptance_criteria:
        lines += ["", "Acceptance criteria:"]
        lines += [f"{i}. {c}" for i, c in enumerate(envelope.task.acceptance_criteria, 1)]
    lines += ["", "Worker report (claims, not evidence):"]
    if worker_claims is None:
        lines.append("none")
    else:
        lines += [
            "```json",
            json.dumps(_dump(worker_claims), indent=2, ensure_ascii=True),
            "```",
        ]
    if focus:
        lines += ["", "Review focus:"] + [f"- {item}" for item in focus]
    lines += ["", "## SECTION 2 — ENTIRE FROZEN WORKER PATCH", "", "```diff"]
    prefix = "\n".join(lines) + "\n"

    lines = [
        "```",
        "",
        "## SECTION 3 — COMPLETE WORKER CHANGE INVENTORY",
        "",
    ]
    if inventory:
        lines += ["```json", json.dumps(inventory, indent=2, ensure_ascii=True), "```"]
    else:
        lines.append("none")

    lines += [
        "",
        "## SECTION 4 — DISPATCHER VALIDATION",
        "",
        "Executed by the dispatcher after the worker exited. NOT Claude's work.",
    ]
    if not validation_results:
        lines.append("none")
    else:
        lines += [
            "```json",
            json.dumps([_dump(v) for v in validation_results], indent=2),
            "```",
        ]
    lines += ["", "## SECTION 5 — VALIDATION FILESYSTEM EFFECTS", ""]
    for field in ("validation_only", "both_authors", "validation_reverted"):
        paths = attribution[field]
        lines.append(f"{field}:")
        lines.extend([f"- {path}" for path in paths] or ["none"])
    both = attribution["both_authors"]
    if both:
        rendered = ", ".join(both)
        lines += [
            "",
            f"{len(both)} path(s) shown above were modified by dispatcher validation "
            "after the worker exited. The patch above is the worktree as the worker "
            f"left it, not as it is now: {rendered}.",
        ]
    lines += [
        "",
        "## SECTION 6 — COMPLETENESS",
        "",
        "Every changed path is represented above.",
        "The patch is complete, frozen worker-exit evidence and is shown whole.",
        "",
        "Return exactly one JSON object matching the supplied --json-schema. "
        "Do not manufacture findings to appear useful. Every material finding "
        "needs evidence. Your verdict is advisory.",
    ]
    return prefix, "\n" + "\n".join(lines)


@dataclass(frozen=True)
class FableEvidenceBundle:
    """One selected IMPLEMENTER run and only its review evidence."""

    run_index: int
    worker_claims: WorkerResult | None
    validation_results: tuple[ValidationResult, ...]
    patch_data: bytes
    patch_text: str
    patch_sha256: str
    patch_file_complete: bool
    inventory: list[dict[str, Any]]
    attribution: dict[str, list[str]]


def _argv_transport_measurement(
    invocation: WorkerInvocation,
    *,
    prefix: str,
    suffix: str,
    patch_data: bytes,
) -> dict[str, Any]:
    """Measure the exact Fable argv+envp headroom for one composed call."""

    patch_text = os.fsdecode(patch_data)
    expected_prompt = prefix + patch_text + suffix
    if invocation.prompt != expected_prompt:
        raise InternalDispatcherError(
            "Fable transport measurement did not receive the launch prompt."
        )
    encoded_prefix = os.fsencode(prefix)
    encoded_suffix = os.fsencode(suffix)
    encoded_prompt = os.fsencode(invocation.prompt)
    if encoded_prompt != encoded_prefix + patch_data + encoded_suffix:
        raise EvidenceFreezeViolated(
            "The frozen patch bytes cannot be transported inline without alteration.",
            details={"changed_files": ["evidence/diff.patch"]},
        )

    provisional = replace(invocation, prompt=prefix + suffix)
    provisional_argv = build_argv(provisional)
    provisional_transport = measure_execve_transport(
        provisional_argv, invocation.env
    )
    provisional_argv_element_bytes = list(
        provisional_transport.argv_element_bytes
    )
    env_element_bytes = list(provisional_transport.envp_element_bytes)
    argv_bytes_without_patch = provisional_transport.argv_bytes
    env_bytes = provisional_transport.envp_bytes
    pointer_bytes = provisional_transport.pointer_bytes
    argv_total_limit = provisional_transport.arg_max_bytes
    base_prompt_bytes = len(encoded_prefix) + len(encoded_suffix)
    aggregate_headroom = max(
        0,
        provisional_transport.aggregate_limit_bytes
        - provisional_transport.total_bytes,
    )
    element_headroom = max(
        0, MEASURED_SINGLE_ARGV_LIMIT_BYTES - base_prompt_bytes
    )
    budget = min(aggregate_headroom, element_headroom)
    patch_bytes = len(patch_data)
    oversized_base_elements = [
        {
            "kind": "argv",
            "index": index,
            "encoded_bytes": encoded_bytes,
            "maximum_bytes": MEASURED_SINGLE_ARGV_LIMIT_BYTES,
        }
        for index in provisional_transport.oversized_argv_indices
        for encoded_bytes in [provisional_argv_element_bytes[index]]
    ] + [
        {
            "kind": "envp",
            "index": index,
            "encoded_bytes": encoded_bytes,
            "maximum_bytes": MEASURED_SINGLE_ARGV_LIMIT_BYTES,
        }
        for index in provisional_transport.oversized_envp_indices
        for encoded_bytes in [env_element_bytes[index]]
    ]
    base_transportable = provisional_transport.transportable
    review_input_complete = base_transportable and patch_bytes <= budget

    # Rebuild the exact final argv now. The same immutable invocation is later
    # handed to run_worker; any authored growth or different prompt would make
    # this equality fail before a process exists.
    final_argv = build_argv(invocation)
    final_transport = measure_execve_transport(final_argv, invocation.env)
    final_argv_element_bytes = list(final_transport.argv_element_bytes)
    final_total_bytes = final_transport.total_bytes
    oversized_final_elements = [
        {
            "kind": "argv",
            "index": index,
            "encoded_bytes": encoded_bytes,
            "maximum_bytes": MEASURED_SINGLE_ARGV_LIMIT_BYTES,
        }
        for index in final_transport.oversized_argv_indices
        for encoded_bytes in [final_argv_element_bytes[index]]
    ] + [
        {
            "kind": "envp",
            "index": index,
            "encoded_bytes": encoded_bytes,
            "maximum_bytes": MEASURED_SINGLE_ARGV_LIMIT_BYTES,
        }
        for index in final_transport.oversized_envp_indices
        for encoded_bytes in [env_element_bytes[index]]
    ]
    if review_input_complete and (
        not final_transport.transportable
    ):
        raise InternalDispatcherError(
            "Fable argv budget and final invocation measurement diverged."
        )

    return {
        "schema": "fable-review-input/1",
        "patch_bytes": patch_bytes,
        "patch_sha256": hashlib.sha256(patch_data).hexdigest(),
        "patch_file_complete": True,
        "review_input_complete": review_input_complete,
        "review_patch_budget_bytes": budget,
        "argv_total_limit_bytes": argv_total_limit,
        "argv_safety_reserve_bytes": _FABLE_ARGV_SAFETY_RESERVE_BYTES,
        "argv_element_limit_bytes": MEASURED_SINGLE_ARGV_LIMIT_BYTES,
        "argv_bytes_without_patch": argv_bytes_without_patch,
        "argv_count": len(provisional_argv),
        "env_bytes": env_bytes,
        "env_count": len(invocation.env),
        "pointer_bytes": pointer_bytes,
        "base_prompt_bytes": base_prompt_bytes,
        "base_transportable": base_transportable,
        # Index, kind and encoded size are sufficient to diagnose the refusal.
        # Never persist argv text, environment keys, or environment values in
        # this record: transport failures must not turn into content leaks.
        "oversized_element_count": len(oversized_final_elements),
        "oversized_elements": oversized_final_elements,
        "largest_argv_element_bytes": max(final_argv_element_bytes, default=0),
        "largest_envp_element_bytes": max(env_element_bytes, default=0),
        "aggregate_headroom_bytes": aggregate_headroom,
        "element_headroom_bytes": element_headroom,
        "binding_constraint": (
            oversized_final_elements[0]["kind"] + "_element"
            if oversized_final_elements
            else "aggregate"
            if aggregate_headroom < element_headroom
            else "element"
        ),
        "final_prompt_bytes": len(encoded_prompt),
        "final_total_bytes": final_total_bytes,
        "final_prompt_sha256": hashlib.sha256(encoded_prompt).hexdigest(),
    }


# ---------------------------------------------------------------------------
# the dispatcher — one instance per server process
# ---------------------------------------------------------------------------


class Dispatcher:
    """Deterministic implementation of the four MCP tools.

    Holds no authoritative in-memory state: every tool reloads the task from
    disk through :class:`~sol_claude_dispatcher.state.TaskStore`, so a restarted
    server sees exactly what the previous one persisted (§27).

    The one in-memory structure it does hold is :attr:`_runs`, the registry of
    *in-flight* runs (GATE 6 §5). It is not authoritative state — everything it
    tracks is also on disk — it exists so a cancelled MCP request cannot take a
    running Claude worker down with it.
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.store = TaskStore(config.tasks_path)
        #: Gate 4.5 §14/§16. Holds the two projection engines and composes the
        #: final worker context. Both engines stay unbuilt — and no manifest is
        #: read — while their feature flags are off, so a dispatcher configured
        #: exactly as it was before Gate 4.5 behaves exactly as it did.
        self.context = WorkerContextComposer(config)
        #: GATE 6 §5. Runs are owned here, not by whoever is waiting on them.
        self._runs = RunRegistry()

    # -- public tool surface ------------------------------------------------
    #
    # Each public method is the *whole* error contract: typed dispatcher errors
    # become concise structured payloads here (§29), so calling these directly
    # exercises exactly what an MCP client would receive.
    #
    # GATE 6 §2/§3/§4: the three tools that start a Claude process run their
    # body as a dispatcher-owned task and await it through the registry's
    # shield. The request stays pending for the whole run — that is the point —
    # but the run does not belong to the request, so an MCP timeout or a dropped
    # transport cannot kill a worker, release its repository lock, or strand a
    # task in RUNNING with no evidence.

    async def dispatch_claude_task(
        self, request: dict[str, Any] | TaskRequest
    ) -> dict[str, Any]:
        """§7.1. Dispatch a worker and WAIT for it. Result payload or error payload.

        Returns when the run reaches one of
        :data:`~sol_claude_dispatcher.waiting.WORKER_ACTIONABLE_STATES`. No
        polling is required, or wanted: see :data:`SERVER_INSTRUCTIONS`.

        Each call gets its own registry key. Dispatch is deliberately **not**
        deduplicated by request content: two dispatches are two tasks, and the
        dispatcher must not guess that identically-worded requests are the same
        piece of work. A retry issued while an earlier worker is still running
        is refused by the repository lock with a retryable ``RepositoryBusy``
        (§25) — which is exactly the "no second worker" guarantee, stated as a
        refusal rather than as a silent alias.
        """
        return await self._runs.run(
            f"dispatch:{new_run_id()}",
            lambda: _guarded(lambda: self._dispatch_execution(request)),
        )

    async def _dispatch_execution(
        self, request: dict[str, Any] | TaskRequest
    ) -> dict[str, Any]:
        with begin_tool_execution("dispatch") as execution:
            return await self._dispatch(request, execution=execution)

    async def resume_claude_task(
        self, task_id: str, instruction: str, timeout_seconds: int | None = None
    ) -> dict[str, Any]:
        """§7.2. Continue a task's stored session, and WAIT for the resumed run.

        Keyed on the caller's own arguments, so a *duplicate* resume — the shape
        a reconnect-and-retry produces — attaches to the run already in flight
        and receives its result, instead of launching a second worker into the
        same worktree. A resume carrying a *different* instruction is a
        different key and contends on the repository lock as before.
        """
        return await self._runs.run(
            _resume_key(task_id, instruction, timeout_seconds),
            lambda: _guarded(
                lambda: self._resume_execution(task_id, instruction, timeout_seconds)
            ),
        )

    async def _resume_execution(
        self, task_id: str, instruction: str, timeout_seconds: int | None
    ) -> dict[str, Any]:
        with begin_tool_execution("resume", task_id=task_id) as execution:
            return await self._resume(
                task_id, instruction, timeout_seconds, execution=execution
            )

    async def review_task_with_fable(
        self, task_id: str, focus: list[str] | None = None
    ) -> dict[str, Any]:
        """§7.3. Independent read-only review. Advisory. Blocks until it completes."""
        return await self._runs.run(
            _review_key(task_id, focus),
            lambda: _guarded(lambda: self._review_execution(task_id, focus)),
        )

    async def _review_execution(
        self, task_id: str, focus: list[str] | None
    ) -> dict[str, Any]:
        with begin_tool_execution("review", task_id=task_id) as execution:
            return await self._review(task_id, focus, execution=execution)

    async def get_task(self, task_id: str) -> dict[str, Any]:
        """§7.4. Read-only aggregation of authoritative state.

        Recovery and status tooling. Never part of the normal dispatch path:
        the three tools above already wait. Deliberately *not* routed through
        the run registry — it starts nothing, so there is nothing to own.
        """
        return await _guarded(lambda: self._get_task(task_id))

    # -- in-process introspection (not an MCP tool, never registered) -------

    def inflight_runs(self) -> tuple[str, ...]:
        """Keys of the runs this dispatcher currently owns (GATE 6 §5).

        For operators, shutdown handling and tests. It is not reachable over
        MCP and must never become a fifth tool: §1 fixes the surface at four.
        """
        return self._runs.keys()

    async def drain(self, timeout: float | None = None) -> None:
        """Wait for every dispatcher-owned run to finish. Cancels nothing."""
        await self._runs.drain(timeout)

    # -- tool 1: dispatch ---------------------------------------------------

    async def _dispatch(
        self,
        request: dict[str, Any] | TaskRequest,
        *,
        execution: ToolExecution | None = None,
    ) -> dict[str, Any]:
        """§7.1. Create a new implementation worker and record what it did."""
        if execution is None:
            # Private-call compatibility for tests; production always enters
            # through ``_dispatch_execution`` above.
            with begin_tool_execution("dispatch") as owned:
                return await self._dispatch(request, execution=owned)
        assert_no_recursion(self.config)

        task_request = self._validate_request(request)

        # GATE 6 (FINDING K-1): refuse a run the transport cannot carry BEFORE
        # anything exists to clean up — no task id, no lock, no worktree, no
        # worker. The check reads the request the caller sent and the clamp this
        # config will apply; it never edits either.
        assert_validation_budget(task_request, self.config, phase="dispatch")

        canonical_root = validate_repository_root(task_request.repository.root, self.config)

        dispatch_depth = _inherited_dispatch_depth()
        assert_dispatch_depth(dispatch_depth, self.config)

        lock = RepositoryLock(canonical_root, self.config.locks_path)
        # Non-blocking (§25): a busy repository is reported immediately as a
        # concise, retryable structured error rather than stalling Sol's tool
        # call until its own timeout fires.
        lock.acquire()

        task_id: str | None = None
        try:
            # Gate 7 R0-R8. Caller intent is already an exact object name; Git
            # verifies that exact token only after raw repository authority and
            # the operator administration baseline reconcile.
            base_commit = task_request.repository.base_ref
            envelope = TaskEnvelope.from_request(
                task_request,
                canonical_root=str(canonical_root),
                base_commit=base_commit,
                task_id=new_task_id(),
                dispatch_depth=dispatch_depth,
            )
            task_id = envelope.task_id
            prompt = build_worker_prompt(envelope)
            preflight_result: dict[str, Any] = {}

            def identity_preflight(
                authority: RepositoryAuthoritySnapshot,
            ) -> ApprovedIdentityFacts:
                """R8: assemble context only after R6 and R7 are complete."""
                approved_identity = self.context.approved_identity_facts()
                self.context.assert_repository_reviewed()
                identity = approved_identity.to_repository_identity(authority)
                worker_context = self.context.for_worker(
                    envelope,
                    run_kind=RunKind.DISPATCH,
                    policy_text=worker_policy_text(self.config),
                    task_prompt=prompt,
                    identity=identity,
                )
                correction_context = self.context.for_worker(
                    envelope,
                    run_kind=RunKind.RESUME,
                    policy_text=worker_policy_text(self.config),
                    task_prompt=build_resume_prompt(envelope, "Lifecycle preflight"),
                    identity=identity,
                )
                review_context = self.context.for_review(
                    envelope,
                    policy_text=fable_policy_text(self.config),
                    task_prompt="Lifecycle review preflight",
                    identity=identity,
                )
                project_root = Path(__file__).resolve().parents[2]
                lifecycle_engine = LifecycleProfileEngine.from_file(
                    project_root / "config" / "approved-lifecycle-profiles.json",
                    source_root=project_root,
                    effective_deny_patterns=ALWAYS_DISALLOWED_TOOLS,
                )
                envelope_digest = hashlib.sha256(
                    json.dumps(
                        _dump(envelope),
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()
                lifecycle_report = preflight_lifecycle(
                    lifecycle_engine,
                    task_id=task_id,
                    envelope_digest=envelope_digest,
                    task_kind=envelope.task.kind,
                    complexity=envelope.routing.complexity,
                    risk=envelope.routing.risk,
                    max_resume_count=envelope.execution.max_resume_count,
                    phase_compositions={
                        LifecyclePhase.DISPATCH_IMPLEMENTATION: PhaseComposition(
                            worker_context.append_system_prompt
                        ),
                        LifecyclePhase.CORRECTION_RESUME: PhaseComposition(
                            correction_context.append_system_prompt
                        ),
                        LifecyclePhase.VALIDATION_ONLY_RESUME: PhaseComposition(
                            correction_context.append_system_prompt
                        ),
                        LifecyclePhase.FABLE_REVIEW: PhaseComposition(
                            review_context.append_system_prompt,
                            review_context_available=True,
                        ),
                    },
                    transport_ceiling_bytes=MAX_APPEND_SYSTEM_PROMPT_BYTES,
                    computed_at=utc_now(),
                )
                dispatch_lifecycle = lifecycle_engine.project(
                    LifecyclePhase.DISPATCH_IMPLEMENTATION,
                    task_kind=envelope.task.kind,
                    complexity=envelope.routing.complexity,
                    risk=envelope.routing.risk,
                )
                preflight_result.update(
                    worker_context=worker_context,
                    lifecycle_report=lifecycle_report,
                    append_system_prompt=compose_append_system_prompt(
                        worker_context.append_system_prompt,
                        dispatch_lifecycle.text,
                        "",
                    ),
                )
                return approved_identity

            model, reason = explain_route(envelope, self.config)
            session_id = new_session(envelope)
            run_index = 1
            run_id = new_run_id()
            expected_worktree = self._worktree_root() / envelope.worktree_name

            prepared = await asyncio.to_thread(
                prepare_dispatch,
                repository_root=canonical_root,
                state_root=self.config.state_path,
                worktree_path=expected_worktree,
                task_id=task_id,
                base_commit=base_commit,
                empty_hooks_path=Path(__file__).resolve().parents[2]
                / "config"
                / "empty-hooks",
                identity_preflight=identity_preflight,
            )
            worker_context = cast(WorkerContext, preflight_result["worker_context"])
            lifecycle_report = preflight_result["lifecycle_report"]

            invocation = build_worker_invocation(
                envelope,
                self.config,
                model=model,
                session_id=session_id,
                prompt=prompt,
                append_system_prompt=cast(
                    str, preflight_result["append_system_prompt"]
                ),
                # Diagnostics only (B1): named back to Sol if the composed
                # context turns out to be too large to transport.
                skill_ids=worker_context.skill_ids,
                guidance_scope_ids=worker_context.guidance_scope_ids,
                # B2: the worktree already exists and has already been verified
                # to be on the recorded base, so the worker starts *inside* it.
                # ``build_worker_invocation`` emits no ``--worktree`` on any
                # path, and ``_assert_invocation_sane`` refuses one that tries.
                cwd=expected_worktree,
            )
            invocation = self._with_run_spools(invocation, task_id, run_index)

            # First lifecycle mutation: the whole PREPARE proof already exists.
            execution.bind_task(task_id)
            execution.mark_reserved(envelope)
            self.store.create(envelope)
            evidence_dir = self.store.task_dir(task_id) / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.replace(prepared.seal.materialisation, evidence_dir / "preworker-seal")
            _event("task_created", task_id=task_id, repository=str(canonical_root))
            self.store.transition(
                task_id, TaskState.ROUTED, reason=f"route:{reason}", selected_model=model
            )
            record = self.store.load(task_id)
            record.worktree_path = str(prepared.worktree.path)
            self.store.save(record)
            self._anchor_worktree_base(
                envelope, prepared.worktree.path, envelope.repository.base_commit
            )
            self._write_worktree_base_evidence(
                envelope,
                worktree_path=prepared.worktree.path,
                actual_head_commit=envelope.repository.base_commit,
                held=True,
                phase="dispatch",
            )
            self._anchor_dispatch_context(task_id, worker_context)
            self.store.write_evidence(
                task_id,
                "lifecycle-feasibility.json",
                json.dumps(lifecycle_report.to_dict(), indent=2),
            )

            def worker_spawned(proc: asyncio.subprocess.Process) -> None:
                execution.mark_spawned({"pid": proc.pid})
                self.store.transition(
                    task_id,
                    TaskState.RUNNING,
                    reason="dispatch",
                    session_id=session_id,
                )

            invocation = replace(invocation, on_spawn=worker_spawned)

            # Durable before LAUNCH: a dispatcher death or spawn refusal must
            # not erase the exact administrative operand later used to
            # attribute worker-side tampering.
            atomic_write_json(
                self._run_dir(task_id, run_index) / "git-admin-worker-start.json",
                prepared.admin_worker_start.to_dict(),
            )

            started_at = utc_now()
            _event("worker_start", task_id=task_id, run_id=run_id, model=model, kind="dispatch")
            execution.enter(ExecutionPhase.LAUNCH)
            worker_run = await run_worker(invocation)
            if execution.phase is ExecutionPhase.LAUNCH:
                # A runner returning without the spawn callback is not allowed
                # to manufacture RUNNING. Preserve the launch refusal.
                raise InternalDispatcherError(
                    "The worker runner returned without proving a child existed."
                )
            finished_at = utc_now()
            execution.enter(ExecutionPhase.FINALIZE)

            return await self._finalise_worker_run(
                envelope=envelope,
                run_kind=RunKind.DISPATCH,
                run_index=run_index,
                run_id=run_id,
                session_id=session_id,
                model=model,
                worktree_path=prepared.worktree.path,
                worker_run=worker_run,
                started_at=started_at,
                finished_at=finished_at,
                repository_root=canonical_root,
                primary_tree_before=prepared.primary_prepare,
                worker_context=worker_context,
                prepared_dispatch=prepared,
            )
        except DispatcherError as exc:
            self._record_failure(
                execution,
                exc,
                repository_key=repository_identity_key(canonical_root),
            )
            raise
        finally:
            # §25: always, on every path, including a raised DispatcherError.
            lock.release()

    # -- tool 2: resume -----------------------------------------------------

    async def _resume(
        self,
        task_id: str,
        instruction: str,
        timeout_seconds: int | None = None,
        *,
        execution: ToolExecution | None = None,
    ) -> dict[str, Any]:
        """§7.2. Continue the *stored* session — never a caller-supplied one."""
        if execution is None:
            with begin_tool_execution("resume", task_id=task_id) as owned:
                return await self._resume(
                    task_id,
                    instruction,
                    timeout_seconds,
                    execution=owned,
                )
        assert_no_recursion(self.config)

        # Defence in depth (P0-1 / Lane A R2). ``TaskStore`` independently
        # refuses any path that does not resolve inside ``state/tasks/``, so the
        # escape is already closed; validating here makes the refusal happen at
        # the boundary, with a precise message instead of a deeper one.
        task_id = validate_task_id(task_id)

        envelope = self.store.load_envelope(task_id)
        record = self.store.load(task_id)

        try:
            # Reads session id, model and worktree from state only, and checks
            # the cap exactly once, before anything is mutated.
            plan = resume_plan(
                envelope,
                record,
                instruction,
                timeout_seconds=timeout_seconds,
                config=self.config,
            )
        except ResumeLimitReached as exc:
            # §7.2: a *successful* tool response describing a refusal. The
            # dispatcher does not decide what happens next; Sol does.
            _event("resume_refused", task_id=task_id, reason="resume_limit_reached")
            return resume_limit_response(exc)

        # GATE 6 (FINDING K-1). A resume is the one path that can legitimately
        # RAISE the effective worker timeout above what the envelope declared,
        # so it is also the one path that could smuggle an over-budget run past
        # a check done only at dispatch. The plan's already-clamped timeout is
        # what this run will actually use, so that is what is budgeted — and no
        # state has been mutated yet when it is refused.
        assert_validation_budget(
            envelope,
            self.config,
            phase="resume",
            execution_timeout_seconds=plan.timeout_seconds,
            task_id=task_id,
        )

        canonical_root = authorize_repository_root(
            envelope.repository.root, self.config
        )

        lock = RepositoryLock(canonical_root, self.config.locks_path)
        lock.acquire()
        try:
            run_index = record.run_count + 1
            run_id = new_run_id()
            resume_prompt = build_resume_prompt(envelope, plan.instruction)

            preflight_result: dict[str, Any] = {}

            def context_preflight(
                authority: RepositoryAuthoritySnapshot,
                sealed_identity: RepositoryIdentityRecord,
            ) -> None:
                """P4, injected between raw P3 and authenticated P5."""
                identity = self.context.sealed_repository_identity(sealed_identity)
                self.context.verify_dispatch_anchor(
                    record, identity=identity, envelope=envelope
                )
                worker_context = self.context.for_worker(
                    envelope,
                    run_kind=RunKind.RESUME,
                    policy_text=worker_policy_text(self.config),
                    task_prompt=resume_prompt,
                    identity=identity,
                )
                project_root = Path(__file__).resolve().parents[2]
                lifecycle_engine = LifecycleProfileEngine.from_file(
                    project_root / "config" / "approved-lifecycle-profiles.json",
                    source_root=project_root,
                    effective_deny_patterns=ALWAYS_DISALLOWED_TOOLS,
                )
                try:
                    persisted_lifecycle = json.loads(
                        (
                            self.store.task_dir(task_id)
                            / "evidence"
                            / "lifecycle-feasibility.json"
                        ).read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    raise StateCorruption(
                        "The task's lifecycle feasibility evidence is unavailable.",
                        details={"task_id": task_id},
                    ) from exc
                if (
                    persisted_lifecycle.get("manifest_version")
                    != lifecycle_engine.manifest.manifest_version
                ):
                    raise PolicyViolation(
                        "The approved lifecycle manifest changed after dispatch.",
                        details={"task_id": task_id},
                    )
                correction_lifecycle = lifecycle_engine.project(
                    LifecyclePhase.CORRECTION_RESUME,
                    task_kind=envelope.task.kind,
                    complexity=envelope.routing.complexity,
                    risk=envelope.routing.risk,
                )
                preflight_result["worker_context"] = worker_context
                preflight_result["append_system_prompt"] = (
                    compose_append_system_prompt(
                        worker_context.append_system_prompt,
                        correction_lifecycle.text,
                        "",
                    )
                )

            seal_path = self.store.task_dir(task_id) / "evidence" / "preworker-seal"
            prepared = await asyncio.to_thread(
                prepare_resume,
                repository_root=canonical_root,
                state_root=self.config.state_path,
                worktree_path=Path(plan.worktree_path),
                task_id=task_id,
                run_index=run_index,
                base_commit=envelope.repository.base_commit,
                seal_path=seal_path,
                empty_hooks_path=Path(__file__).resolve().parents[2]
                / "config"
                / "empty-hooks",
                context_preflight=context_preflight,
            )
            worker_context = cast(WorkerContext, preflight_result["worker_context"])
            append_system_prompt = cast(
                str, preflight_result["append_system_prompt"]
            )

            invocation = build_worker_invocation(
                envelope,
                self.config,
                model=plan.model,
                session_id=plan.session_id,
                resume_session_id=plan.session_id,
                prompt=resume_prompt,
                append_system_prompt=append_system_prompt,
                skill_ids=worker_context.skill_ids,
                guidance_scope_ids=worker_context.guidance_scope_ids,
                # Same worktree, no new one (§18). build_worker_invocation
                # refuses to emit --worktree alongside --resume.
                cwd=Path(plan.worktree_path),
                timeout_seconds=plan.timeout_seconds,
            )
            invocation = self._with_run_spools(invocation, task_id, run_index)

            # The complete PREPARE proof exists before the first lifecycle
            # mutation. RUNNING is not durable until the child exists.
            execution.mark_reserved(plan)
            self.store.transition(
                task_id, TaskState.RESUME_REQUESTED, reason="resume_requested"
            )

            def worker_spawned(proc: asyncio.subprocess.Process) -> None:
                execution.mark_spawned({"pid": proc.pid})
                self.store.transition(
                    task_id,
                    TaskState.RUNNING,
                    reason="resume",
                    resume_count=plan.next_resume_count,
                )

            invocation = replace(invocation, on_spawn=worker_spawned)

            atomic_write_json(
                self._run_dir(task_id, run_index) / "git-admin-worker-start.json",
                prepared.admin_worker_start.to_dict(),
            )

            started_at = utc_now()
            _event(
                "worker_start",
                task_id=task_id,
                run_id=run_id,
                model=plan.model,
                kind="resume",
                resume_count=plan.next_resume_count,
            )
            execution.enter(ExecutionPhase.LAUNCH)
            worker_run = await run_worker(invocation)
            if execution.phase is ExecutionPhase.LAUNCH:
                raise InternalDispatcherError(
                    "The worker runner returned without proving a child existed."
                )
            finished_at = utc_now()
            execution.enter(ExecutionPhase.FINALIZE)

            return await self._finalise_worker_run(
                envelope=envelope,
                run_kind=RunKind.RESUME,
                run_index=run_index,
                run_id=run_id,
                session_id=plan.session_id,
                model=plan.model,
                worktree_path=Path(plan.worktree_path),
                worker_run=worker_run,
                started_at=started_at,
                finished_at=finished_at,
                repository_root=canonical_root,
                primary_tree_before=prepared.primary_prepare,
                worker_context=worker_context,
                prepared_dispatch=prepared,
            )
        except DispatcherError as exc:
            self._record_failure(execution, exc)
            raise
        finally:
            lock.release()

    # -- tool 3: fable review -----------------------------------------------

    async def _review(
        self,
        task_id: str,
        focus: list[str] | None = None,
        *,
        execution: ToolExecution | None = None,
    ) -> dict[str, Any]:
        """§7.3. Independent, read-only review in a fresh session. Advisory."""
        if execution is None:
            with begin_tool_execution("review", task_id=task_id) as owned:
                return await self._review(task_id, focus, execution=owned)
        try:
            # Install the refusal journal boundary before PREPARE.
            task_id = validate_task_id(task_id)
            envelope = self.store.load_envelope(task_id)
            # Legality is a PREPARE condition. Refuse before taking repository
            # authority or constructing any reviewer/run/review artefact; the
            # surrounding failure boundary records exactly one typed refusal.
            _assert_fable_review_transition_allowed(self.store.load(task_id))
            assert_validation_budget(
                envelope, self.config, phase="review", task_id=task_id
            )
            # The budget check above precedes _review_impl's
            # RepositoryLock.lock.acquire() call, so an over-budget review
            # cannot contend for repository authority.
            return await self._review_impl(task_id, focus, execution=execution)
        except DispatcherError as exc:
            # PREPARE refusals are journalled exactly like dispatch/resume. A
            # refusal before reviewer spawn appends refusals.jsonl and leaves
            # the task state byte-identical.
            self._record_failure(execution, exc)
            raise

    async def _review_impl(
        self,
        task_id: str,
        focus: list[str] | None,
        *,
        execution: ToolExecution,
    ) -> dict[str, Any]:
        """Run the review after the failure-recording boundary is installed."""
        assert_no_recursion(self.config)

        # Defence in depth (P0-1 / Lane A R2).
        task_id = validate_task_id(task_id)

        envelope = self.store.load_envelope(task_id)
        record = self.store.load(task_id)

        if not record.worktree_path:
            raise StateCorruption(
                "This task has no recorded worktree to review.",
                details={"task_id": task_id, "state": record.state.value},
                remediation="Dispatch or inspect the task first; there is nothing to review.",
            )
        worktree = Path(record.worktree_path)
        if not worktree.is_dir():
            raise StateCorruption(
                "The task's recorded worktree no longer exists.",
                details={"task_id": task_id, "worktree_path": str(worktree)},
            )

        canonical_root = authorize_repository_root(
            envelope.repository.root, self.config
        )
        primary_dot_git = await asyncio.to_thread(classify_dot_git, canonical_root)

        # P0/P1-4: Fable used to take no lock, on the reasoning that a review is
        # read-only. Read-only is not the same as *consistent*: a resume (or a
        # second review) mutating the same worktree while Fable reads it
        # produces a review of a state that never existed as a whole, and the
        # review counter contends as well. V1 fix, deliberately simple: the same
        # exclusive repository lock the mutating tools take, held for the whole
        # snapshot — evidence read, prompt built, reviewer run, review recorded.
        # No reader/writer split yet; a busy repository is refused immediately
        # with RepositoryBusy rather than reviewing a moving target.
        lock = RepositoryLock(canonical_root, self.config.locks_path)
        lock.acquire()
        try:
            # Re-read under the lock. The record loaded above was read before
            # the lock existed, so its ``run_count`` may already be stale — and
            # ``run_count + 1`` is the run *directory*, so a stale value would
            # have the review overwrite a worker run's evidence.
            record = self.store.load(task_id)
            # Close the check-to-lock race. Another Dispatcher instance may
            # have completed a review after the public PREPARE check but before
            # this execution acquired repository authority. Re-check before
            # reading review evidence or creating any reviewer artefact.
            _assert_fable_review_transition_allowed(record)

            seal_path = self.store.task_dir(task_id) / "evidence" / "preworker-seal"
            seal = await asyncio.to_thread(
                load_task_seal, seal_path, require_identity=True
            )
            try:
                sealed_repo_authority = RepositoryAuthoritySnapshot.from_json_dict(
                    json.loads((seal_path / "repository-authority.json").read_bytes())
                )
                sealed_worktree_authority = decode_worktree_authority(
                    (seal_path / "worktree-authority.json").read_bytes()
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise StateCorruption(
                    "The task's sealed review authority is unavailable.",
                    details={"task_id": task_id},
                ) from exc
            if (
                seal.manifest.task_id != task_id
                or seal.manifest.base_commit != envelope.repository.base_commit
            ):
                raise StateCorruption(
                    "The task seal identity does not match the stored envelope.",
                    details={"task_id": task_id},
                )
            sealed_identity = seal.identity_record
            if sealed_identity is None:  # require_identity makes this unreachable
                raise InternalDispatcherError(
                    "Verified task seal returned no repository identity."
                )
            if (
                os.fsencode(canonical_root) != sealed_repo_authority.canonical_root
                or os.fsencode(canonical_root) != sealed_identity.canonical_root
                or primary_dot_git.shape is not sealed_repo_authority.dot_git_shape
            ):
                raise WorktreeBaseMismatch(
                    "Repository authority changed before Fable review.",
                    details={"task_id": task_id},
                )
            authority_verdict = await asyncio.to_thread(
                verify_worktree_authority, sealed_worktree_authority
            )
            if authority_verdict.verdict != "base_held":
                raise WorktreeBaseMismatch(
                    "Worktree authority changed before Fable review.",
                    details={
                        "task_id": task_id,
                        "verdict": authority_verdict.verdict,
                        "expected_base_commit": envelope.repository.base_commit,
                        "actual_head_commit": (
                            authority_verdict.observed_head_bytes.decode(
                                "ascii", errors="replace"
                            ).strip()
                            if authority_verdict.observed_head_bytes is not None
                            else None
                        ),
                    },
                )

            evidence = self._load_fable_evidence(task_id)
            session_id = new_session_id()  # fresh session, never the worker's (§19)
            run_index = record.run_count + 1
            run_id = new_run_id()

            prompt_prefix, prompt_suffix = _fable_prompt_parts(
                envelope,
                inventory=evidence.inventory,
                worker_claims=evidence.worker_claims,
                validation_results=list(evidence.validation_results),
                focus=list(focus or []),
                attribution=evidence.attribution,
            )
            review_prompt = prompt_prefix + evidence.patch_text + prompt_suffix

            # Gate 4.5 §15. Fable gets a SEPARATE review-context guidance
            # projection — different artifacts, different hashes, disjoint from
            # the worker's — and no skill projection at all. A scope whose
            # review projection was never approved fails closed here; it must
            # not degrade to root-only review context (RULINGS §7).
            review_identity = self.context.sealed_repository_identity(sealed_identity)
            review_context = self.context.for_review(
                envelope,
                policy_text=fable_policy_text(self.config),
                task_prompt=review_prompt,
                identity=review_identity,
            )

            invocation = build_fable_invocation(
                envelope,
                self.config,
                session_id=session_id,
                prompt=review_prompt,
                append_system_prompt=review_context.append_system_prompt,
                guidance_scope_ids=review_context.guidance_scope_ids,
                cwd=worktree,
            )
            transport = _argv_transport_measurement(
                invocation,
                prefix=prompt_prefix,
                suffix=prompt_suffix,
                patch_data=evidence.patch_data,
            )
            transport.update(
                {
                    "task_id": task_id,
                    "implementer_run_index": evidence.run_index,
                    "proposed_review_run_index": run_index,
                }
            )
            self.store.write_evidence(
                task_id,
                "fable-review-input.json",
                json.dumps(transport, indent=2),
            )
            if not transport["review_input_complete"]:
                raise EvidenceExceedsReviewBudget(
                    "The complete Fable review invocation cannot be transported "
                    "intact within the measured execve limits.",
                    details={
                        "task_id": task_id,
                        "implementer_run_index": evidence.run_index,
                        "patch_bytes": transport["patch_bytes"],
                        "budget_bytes": transport["review_patch_budget_bytes"],
                        "binding_constraint": transport["binding_constraint"],
                        "oversized_element_count": transport[
                            "oversized_element_count"
                        ],
                        "oversized_elements": transport["oversized_elements"],
                    },
                    remediation=(
                        "Narrow the task scope, split the work, or remove the "
                        "oversized argv/environment element; evidence and "
                        "invocation entries will not be clipped."
                    ),
                )
            atomic_write_json(
                self.store.run_dir(task_id, run_index) / "fable-review-input.json",
                transport,
            )
            invocation = self._with_run_spools(invocation, task_id, run_index)

            execution.mark_reserved({"seal_manifest": seal.manifest.manifest_hash})

            def reviewer_spawned(proc: asyncio.subprocess.Process) -> None:
                execution.mark_spawned({"pid": proc.pid})

            invocation = replace(invocation, on_spawn=reviewer_spawned)

            started_at = utc_now()
            _event(
                "review_start", task_id=task_id, run_id=run_id, model=self.config.models.fable
            )
            execution.enter(ExecutionPhase.LAUNCH)
            worker_run = await run_worker(invocation)
            if execution.phase is ExecutionPhase.LAUNCH:
                raise InternalDispatcherError(
                    "The reviewer runner returned without proving a child existed."
                )
            finished_at = utc_now()
            execution.enter(ExecutionPhase.FINALIZE)

            self._write_run_streams(task_id, run_index, worker_run)
            self._record_bare_run(
                envelope=envelope,
                run_kind=RunKind.REVIEW,
                role=WorkerRole.REVIEWER,
                run_index=run_index,
                run_id=run_id,
                session_id=session_id,
                model=self.config.models.fable,
                worktree_path=str(worktree),
                worker_run=worker_run,
                started_at=started_at,
                finished_at=finished_at,
                worker_context=review_context,
            )

            # B3: the provider may have refused the review outright — a 429
            # usage limit arrives as a well-formed envelope, with exit 0 and no
            # payload. Checked before the parser, which would otherwise call an
            # exhausted quota a malformed review.
            provider_error = provider_failure(
                worker_run, binary=self.config.claude.binary, role="reviewer"
            )
            if provider_error is not None:
                provider_error.details["task_id"] = task_id
                raise provider_error

            # DEFECT-L2-02: a reviewer CLI that exited non-zero without writing
            # anything failed as a *process*. Raise that, with its stderr tail,
            # rather than letting the parser report the empty stdout as invalid
            # model output.
            cli_error = cli_failure(
                worker_run, binary=self.config.claude.binary, role="reviewer"
            )
            if cli_error is not None:
                cli_error.details["task_id"] = task_id
                raise cli_error

            # Lane B R1: the retained stream carries an in-band truncation
            # marker for a very large run and is deliberately not JSON then.
            review = parse_fable_review(worker_run.stdout_for_parsing)
            review_number = self.store.append_review(task_id, review)

            record = self.store.transition(
                task_id,
                TaskState.FABLE_REVIEWED,
                reason=f"fable_review:{review.verdict.value}",
            )
            _event(
                "review_complete",
                task_id=task_id,
                run_id=run_id,
                verdict=review.verdict.value,
                findings=len(review.findings),
            )
        finally:
            # Released on every path: a malformed review result, a failed
            # reviewer process, a refused state transition, or success.
            lock.release()

        return {
            "task_id": task_id,
            "run_id": run_id,
            "session_id": session_id,
            "model": self.config.models.fable,
            "status": record.state.value,
            "state": record.state.value,
            "review_number": review_number,
            "review": _dump(review),
            # §7.3/§41: Fable never approves. The verdict informs Sol; it does
            # not move the task toward any approval state.
            "advisory": True,
            # GATE 6 §4. ``worker_actionable`` is False here on purpose:
            # FABLE_REVIEWED is not a worker outcome, and a review must never
            # read as one. The call still waited server-side and still needs no
            # polling.
            "blocking": blocking_envelope(record.state),
        }

    # -- tool 4: get_task ---------------------------------------------------

    async def _get_task(self, task_id: str) -> dict[str, Any]:
        """§7.4. Read-only aggregation. No transition, no subprocess, no lock."""
        # Defence in depth (P0-1 / Lane A R2). Read-only is still a path
        # derivation, so the id is validated at the boundary here too.
        task_id = validate_task_id(task_id)

        envelope = self.store.load_envelope(task_id)
        record = self.store.load(task_id)
        runs = self.store.load_runs(task_id)
        reviews = self.store.load_reviews(task_id)

        latest_run = runs[-1] if runs else None
        latest_worker_result = None
        for run in reversed(runs):
            if run.worker_claims is not None:
                latest_worker_result = run.worker_claims
                break

        validation_history = [
            {
                "run_id": run.metadata.run_id,
                "run_index": run.metadata.run_index,
                "results": [_dump(v) for v in run.validation_results],
            }
            for run in runs
        ]

        return {
            "task_id": task_id,
            "status": record.state.value,
            "state": record.state.value,
            "envelope": _dump(envelope),
            "model": record.selected_model,
            "worktree": record.worktree_path,
            "session_id": record.session_id,
            "resume_count": record.resume_count,
            "max_resume_count": envelope.execution.max_resume_count,
            "run_count": record.run_count,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "state_history": list(record.state_history),
            "runs": [_dump(run) for run in runs],
            "validation_history": validation_history,
            "latest_worker_result": _dump(latest_worker_result),
            "latest_fable_review": _dump(reviews[-1] if reviews else None),
            "fable_review_count": record.fable_review_count,
            "policy_violations": list(record.policy_violations),
            "timeout": {
                "timeout_seconds": envelope.execution.timeout_seconds,
                "timed_out": bool(latest_run and latest_run.metadata.timed_out),
                "killed_with_sigkill": bool(
                    latest_run and latest_run.metadata.killed_with_sigkill
                ),
            },
            "last_error": record.last_error,
        }

    # -- internals ----------------------------------------------------------

    def _validate_request(self, request: dict[str, Any] | TaskRequest) -> TaskRequest:
        """Validate caller input (§7.1). ``extra='forbid'`` is the guarantee."""
        if isinstance(request, TaskRequest):
            return request
        if not isinstance(request, dict):
            raise InvalidTaskEnvelope(
                "Task request must be a JSON object.",
                details={"got": type(request).__name__},
            )
        try:
            return TaskRequest.model_validate(request)
        except ValidationError as exc:
            raise InvalidTaskEnvelope(
                "Task request failed validation.",
                details={"issues": _compact_issues(exc)},
                remediation=(
                    "Fix the listed fields. The dispatcher generates task_id, "
                    "run_id, session_id, worktree and base_commit itself; "
                    "supplying them is rejected, not ignored."
                ),
            ) from exc

    def _run_dir(self, task_id: str, run_index: int) -> Path:
        """The run directory, created 0700. Containment is checked by the store."""
        run_dir = self.store.run_dir(task_id, run_index)
        run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(run_dir, 0o700)
        return run_dir

    def _with_run_spools(
        self, invocation: WorkerInvocation, task_id: str, run_index: int
    ) -> WorkerInvocation:
        """Point the runner's complete-stream spools at the run directory (P1-8).

        Lane B R2: ``run_worker`` streams every byte the child writes to these
        files, so the complete stream is on disk even when the in-memory
        retention cap truncates what is returned. The run directory has to exist
        before the worker starts — the runner refuses to launch a worker whose
        evidence it already knows it cannot keep.
        """
        run_dir = self._run_dir(task_id, run_index)
        return replace(
            invocation,
            stdout_spool_path=run_dir / "stdout.raw",
            stderr_spool_path=run_dir / "stderr.log",
        )

    def _write_run_streams(self, task_id: str, run_index: int, worker_run: WorkerRun) -> None:
        """Persist the retained stdout/stderr for a run (§20).

        ``stdout.json`` is the *retained* stream — complete for any run inside
        the cap, and an explicitly-marked head+tail excerpt beyond it. The
        untruncated stream lives in ``stdout.raw``, written by the runner.

        ``stderr.log`` is only written here when the runner did **not** spool
        it; otherwise this would overwrite the complete, line-by-line redacted
        spool with a bounded excerpt of the same stream (Lane B R2).
        """
        run_dir = self._run_dir(task_id, run_index)
        atomic_write_text(run_dir / "stdout.json", worker_run.stdout)
        if worker_run.stderr_spool_path is None:
            atomic_write_text(run_dir / "stderr.log", redact(worker_run.stderr))

    def _worktree_root(self) -> Path:
        """Where the dispatcher puts the worktrees it creates (B2, K-2).

        Under the dispatcher's own state directory — deliberately **outside**
        every repository it dispatches against. The Claude CLI put its
        worktrees at ``<repo>/.claude/worktrees/<name>``, inside the primary
        work tree, where git reports the container as a new untracked entry:
        that entry trips the primary-tree non-interference invariant, so the
        first dispatch into any newly-authorised repository was refused
        (K-2). Owning creation lets the container live somewhere that cannot
        dirty the user's tree at all, which resolves K-2 without excusing
        anything and without weakening a single check.
        """
        return Path(self.config.state_path) / "worktrees"

    def _verify_worktree_base(
        self,
        envelope: TaskEnvelope,
        worktree_path: Path,
        *,
        phase: str,
        anchor_on_success: bool = False,
    ) -> str:
        """Enforce INVARIANT B2 and record the verdict as evidence, either way.

        Returns the measured head on success. On mismatch the evidence file is
        written **before** the error propagates, so the refusal is auditable,
        and the recorded base is left exactly as Sol approved it.
        """
        expected = envelope.repository.base_commit
        try:
            measured = assert_worktree_base(
                worktree_path,
                expected_base_commit=expected,
                task_id=envelope.task_id,
                worktree_name=envelope.worktree_name,
                base_ref=envelope.repository.base_ref,
                phase=phase,
            )
        except WorktreeBaseMismatch as exc:
            self._write_worktree_base_evidence(
                envelope,
                worktree_path=worktree_path,
                actual_head_commit=str(exc.details.get("actual_head_commit", "")),
                held=False,
                phase=phase,
            )
            _event(
                "worktree_base_mismatch",
                task_id=envelope.task_id,
                phase=phase,
                expected_base_commit=expected,
                actual_head_commit=exc.details.get("actual_head_commit"),
            )
            raise

        self._write_worktree_base_evidence(
            envelope,
            worktree_path=worktree_path,
            actual_head_commit=measured,
            held=True,
            phase=phase,
        )
        if anchor_on_success:
            self._anchor_worktree_base(envelope, worktree_path, measured)
        return measured

    def _assert_resume_worktree_identity(
        self,
        envelope: TaskEnvelope,
        record: TaskRecord,
        repository_root: Path,
        worktree_path: Path,
    ) -> str:
        """Everything a resume must be true about its worktree, before launch (B2 §6).

        Three separate facts, checked in this order because each is cheaper and
        more fundamental than the next:

        1. **Anchor vs envelope.** The baseline identity pinned at dispatch
           must still be the one the envelope names. This is the check that
           refuses a *normalised* base — a task quietly redefined to match
           whatever its tree ended up on. It needs no subprocess and it catches
           the case where the tree and the envelope were moved together.
        2. **Worktree identity.** Git must still register a worktree of this
           task's name, at the recorded path. A path that exists but is no
           longer a registered worktree is not this task's tree.
        3. **The invariant.** HEAD inside that tree must equal the recorded
           base, exactly.

        Nothing here adopts, repairs or normalises anything. Legacy tasks
        dispatched before the anchor existed skip step 1 and are still held to
        steps 2 and 3.
        """
        anchor = record.worktree_base_anchor
        if anchor is not None:
            if anchor.base_commit != envelope.repository.base_commit:
                raise WorktreeBaseMismatch(
                    "This task's recorded baseline is not the base the resume "
                    "would run under.",
                    details={
                        "task_id": envelope.task_id,
                        "phase": "resume",
                        "anchored_base_commit": anchor.base_commit,
                        "expected_base_commit": envelope.repository.base_commit,
                        "worktree_name": envelope.worktree_name,
                        "worktree_path": str(worktree_path),
                        "base_ref": envelope.repository.base_ref,
                    },
                    remediation="The base a task was approved with is "
                    "immutable. A resume may not adopt a different one; "
                    "dispatch a new task if a different base is intended.",
                )
            if Path(anchor.worktree_path) != worktree_path:
                raise WorktreeBaseMismatch(
                    "This task's recorded worktree is not the one the resume "
                    "would run in.",
                    details={
                        "task_id": envelope.task_id,
                        "phase": "resume",
                        "anchored_worktree_path": anchor.worktree_path,
                        "worktree_path": str(worktree_path),
                        "worktree_name": envelope.worktree_name,
                        "expected_base_commit": envelope.repository.base_commit,
                        "anchored_base_commit": anchor.base_commit,
                    },
                    remediation="A resume reuses the exact worktree the "
                    "dispatch created (§18). Task state has been altered; do "
                    "not resume it.",
                )

        registered = resolve_worktree(repository_root, envelope.worktree_name)
        if registered is None or registered.path != worktree_path:
            raise WorktreeBaseMismatch(
                "The task's isolated worktree is not registered with the "
                "repository at the recorded path.",
                details={
                    "task_id": envelope.task_id,
                    "phase": "resume",
                    "worktree_name": envelope.worktree_name,
                    "worktree_path": str(worktree_path),
                    "registered_path": (
                        str(registered.path) if registered is not None else None
                    ),
                    "expected_base_commit": envelope.repository.base_commit,
                },
                remediation="Evidence is only meaningful from the worktree "
                "this task was dispatched into. Do not resume into a "
                "different tree; return the task to Sol.",
            )

        return self._verify_worktree_base(envelope, worktree_path, phase="resume")

    def _anchor_worktree_base(
        self, envelope: TaskEnvelope, worktree_path: Path, initial_head: str
    ) -> None:
        """Pin the task's baseline identity, once (B2 §6).

        Written when the worktree is created and verified, and never updated:
        it is the value a resume's baseline is measured against, so refreshing
        it would erase the thing being measured — the same reason the context
        fingerprint anchor is write-once.
        """
        record = self.store.load(envelope.task_id)
        if record.worktree_base_anchor is not None:
            return
        record.worktree_base_anchor = WorktreeBaseAnchor(
            base_ref=envelope.repository.base_ref,
            base_commit=envelope.repository.base_commit,
            worktree_name=envelope.worktree_name,
            worktree_path=str(worktree_path),
            initial_head_commit=initial_head,
        )
        self.store.save(record)
        _event(
            "worktree_base_anchored",
            task_id=envelope.task_id,
            base_commit=envelope.repository.base_commit,
            worktree_path=str(worktree_path),
        )

    def _write_worktree_base_evidence(
        self,
        envelope: TaskEnvelope,
        *,
        worktree_path: Path,
        actual_head_commit: str,
        held: bool,
        phase: str,
    ) -> None:
        """Persist the B2 verdict for a run — on **both** outcomes (§20)."""
        self.store.write_evidence(
            envelope.task_id,
            "worktree-base.json",
            json.dumps(
                {
                    "invariant": "worktree_head == recorded_base_commit",
                    "held": held,
                    "phase": phase,
                    "worktree_name": envelope.worktree_name,
                    "worktree_path": str(worktree_path),
                    "base_ref": envelope.repository.base_ref,
                    "expected_base_commit": envelope.repository.base_commit,
                    "actual_head_commit": actual_head_commit,
                    "note": (
                        "The dispatcher creates this worktree itself, at the "
                        "commit the envelope froze, and measures HEAD inside it "
                        "before any evidence is collected. Equality is exact: "
                        "an ancestor or a descendant of the recorded base is a "
                        "refusal, because either one contributes commits the "
                        "worker did not write to every diff taken here."
                    ),
                },
                indent=2,
            ),
        )

    def _anchor_dispatch_context(self, task_id: str, context: WorkerContext) -> None:
        """Persist the dispatch-time context as the task's anchor (§16).

        Written **before** the worker starts, so the evidence survives a crash,
        and written **once**: a task already carrying an anchor keeps it. Resume
        legitimately projects a different skill profile, and overwriting the
        anchor with it would erase the value drift is measured against. The
        per-run values live on :class:`RunMetadata`.
        """
        record = self.store.load(task_id)
        if record.context_fingerprint is not None:
            return
        record.skill_policy = context.skill_record
        record.project_guidance = context.guidance_record
        record.context_fingerprint = context.fingerprint
        self.store.save(record)
        _event(
            "worker_context_anchored",
            task_id=task_id,
            context_fingerprint=context.fingerprint,
            sections=list(context.sections),
            skill_ids=list(context.skill_projection.skill_ids)
            if context.skill_projection is not None
            else [],
            guidance_logical_ids=list(context.guidance_projection.logical_ids)
            if context.guidance_projection is not None
            else [],
        )

    def _record_bare_run(
        self,
        *,
        envelope: TaskEnvelope,
        run_kind: RunKind,
        role: WorkerRole,
        run_index: int,
        run_id: str,
        session_id: str,
        model: str,
        worktree_path: str | None,
        worker_run: WorkerRun,
        started_at: Any,
        finished_at: Any,
        worker_context: WorkerContext | None = None,
    ) -> None:
        """Record a run that produced no diff evidence (review, or no worktree)."""
        metadata = self._run_metadata(
            envelope=envelope,
            run_kind=run_kind,
            role=role,
            run_index=run_index,
            run_id=run_id,
            session_id=session_id,
            model=model,
            worktree_path=worktree_path,
            worker_run=worker_run,
            started_at=started_at,
            finished_at=finished_at,
            worker_context=worker_context,
        )
        self.store.append_run(envelope.task_id, RunRecord(metadata=metadata))

    def _run_metadata(
        self,
        *,
        envelope: TaskEnvelope,
        run_kind: RunKind,
        role: WorkerRole,
        run_index: int,
        run_id: str,
        session_id: str,
        model: str,
        worktree_path: str | None,
        worker_run: WorkerRun,
        started_at: Any,
        finished_at: Any,
        worker_context: WorkerContext | None = None,
    ) -> RunMetadata:
        skill_fingerprint: str | None = None
        guidance_fingerprint: str | None = None
        context_fingerprint: str | None = None
        if worker_context is not None:
            context_fingerprint = worker_context.fingerprint
            if worker_context.skill_projection is not None:
                skill_fingerprint = worker_context.skill_projection.fingerprint
            if (
                worker_context.guidance_projection is not None
                and worker_context.guidance_projection.mode != "disabled"
            ):
                guidance_fingerprint = worker_context.guidance_projection.fingerprint
        return RunMetadata(
            run_id=run_id,
            run_index=run_index,
            task_id=envelope.task_id,
            kind=run_kind,
            role=role,
            model=model,
            session_id=session_id,
            worktree_path=worktree_path,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=worker_run.duration_ms,
            exit_code=worker_run.exit_code,
            timed_out=worker_run.timed_out,
            killed_with_sigkill=worker_run.killed_with_sigkill,
            argv_redacted=_redact_argv(worker_run.argv),
            # Lane B R3: the runner's exact counters, not the length of the
            # retained excerpt. Recording the excerpt's size for a truncated run
            # would understate what the worker actually emitted, which is the
            # "never silently claim full evidence" failure P1-8 is about.
            # ``max`` covers the start-failure path, where the runner never read
            # a child stream (counters 0) but synthesised a diagnostic into
            # ``stderr``: the recorded size must never be *less* than what is
            # actually on disk.
            stdout_bytes=max(
                worker_run.stdout_total_bytes,
                len(worker_run.stdout.encode("utf-8", errors="replace")),
            ),
            stderr_bytes=max(
                worker_run.stderr_total_bytes,
                len(worker_run.stderr.encode("utf-8", errors="replace")),
            ),
            # Lane C C-R1: without these a reader cannot tell from the run
            # record that ``stdout.json`` is an excerpt — they would have to
            # compare its size against ``stdout_bytes`` or open ``stdout.raw``.
            stdout_truncated=worker_run.stdout_truncated,
            stderr_truncated=worker_run.stderr_truncated,
            # Gate 4.5 §15/§16: per-run context evidence. These move when a
            # resume legitimately selects a different profile; the dispatch
            # anchor on ``TaskRecord`` does not.
            skill_policy_fingerprint=skill_fingerprint,
            project_guidance_fingerprint=guidance_fingerprint,
            context_fingerprint=context_fingerprint,
        )

    async def _finalise_worker_run(
        self,
        *,
        envelope: TaskEnvelope,
        run_kind: RunKind,
        run_index: int,
        run_id: str,
        session_id: str,
        model: str,
        worktree_path: Path,
        worker_run: WorkerRun,
        started_at: Any,
        finished_at: Any,
        repository_root: Path,
        primary_tree_before: PrimaryTreeSnapshot | FsSnapshot,
        worker_context: WorkerContext | None = None,
        prepared_dispatch: PreparedDispatch | PreparedResume | None = None,
    ) -> dict[str, Any]:
        """Collect evidence, record the run, and land the task in a state.

        Shared by dispatch and resume so both go through *identical* evidence
        collection, scope enforcement and state accounting (§13, §16, §17).

        Evidence is collected at adjacent terminals (P1-7): WORKER_START,
        WORKER_EXIT, and VALIDATION_EXIT.  The worker-exit delta is the
        immutable canonical patch and owns the scope verdict.  The separate
        post-validation snapshot attributes dispatcher-created drift without
        charging it to the worker or rewriting reviewer evidence.  Primary
        filesystem, HEAD, and repository authority use the same terminal split
        so validation cannot restore and erase worker interference.
        """
        task_id = envelope.task_id
        if prepared_dispatch is None:
            raise InternalDispatcherError(
                "Worker finalization requires Gate 7 prepared evidence."
            )

        scope_spec = ScopeSpecBytes.from_strings(
            allowed_paths=envelope.scope.allowed_paths,
            forbidden_paths=envelope.scope.forbidden_paths,
        )
        prior_cumulative_worker = None
        prior_scope_raw = self.store.read_evidence(task_id, "scope-verdicts.json")
        if run_index == 1:
            if prior_scope_raw is not None:
                raise StateCorruption(
                    "A first worker run unexpectedly has prior scope history.",
                    details={"task_id": task_id, "run_index": run_index},
                )
        else:
            if prior_scope_raw is None:
                raise StateCorruption(
                    "The prior cumulative worker scope history is absent.",
                    details={"task_id": task_id, "run_index": run_index},
                )
            try:
                prior_scope_value = json.loads(prior_scope_raw)
                if not isinstance(prior_scope_value, dict):
                    raise ValueError("scope evidence root is not an object")
                prior_cumulative_worker = load_prior_cumulative_worker(
                    prior_scope_value,
                    scope=scope_spec,
                    base_commit=envelope.repository.base_commit,
                )
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise StateCorruption(
                    "The prior cumulative worker scope history is malformed.",
                    details={"task_id": task_id, "run_index": run_index},
                ) from exc

        self._write_run_streams(task_id, run_index, worker_run)
        worker_exit_repository_authority = await asyncio.to_thread(
            capture_matching_repository_authority,
            repository_root,
            prepared_dispatch.repository_authority,
            phase="worker_exit",
        )
        primary_worker_exit = await asyncio.to_thread(
            capture_snapshot,
            repository_root,
            role="primary_post",
            fidelity="stat_identity",
        )
        primary_worker_exit_head = await asyncio.to_thread(
            capture_primary_head, worker_exit_repository_authority
        )
        primary_worker_divergence = _primary_terminal_divergence(
            prepared_dispatch.primary_worker_start,
            prepared_dispatch.primary_worker_start_head,
            primary_worker_exit,
            primary_worker_exit_head,
            expected_root=worker_exit_repository_authority.canonical_root,
            attributed_to="worker",
            interval="worker_start_to_worker_exit",
        )

        run_dir = self._run_dir(task_id, run_index)
        worker_start_primary_evidence = {
            "phase": "worker_start",
            "repository_authority": (
                prepared_dispatch.repository_authority.to_json_dict()
            ),
            "tree": prepared_dispatch.primary_worker_start.to_dict(),
            "head": prepared_dispatch.primary_worker_start_head.to_dict(),
        }
        worker_exit_primary_evidence = {
            "phase": "worker_exit",
            "repository_authority": worker_exit_repository_authority.to_json_dict(),
            "tree": primary_worker_exit.to_dict(),
            "head": primary_worker_exit_head.to_dict(),
        }
        self.store.write_evidence(
            task_id,
            "primary-tree-worker-start.json",
            json.dumps(worker_start_primary_evidence, indent=2),
        )
        self.store.write_evidence(
            task_id,
            "primary-tree-worker-exit.json",
            json.dumps(worker_exit_primary_evidence, indent=2),
        )
        atomic_write_json(
            run_dir / "git-admin-worker-start.json",
            prepared_dispatch.admin_worker_start.to_dict(),
        )
        administrative_divergences: list[dict[str, Any]] = []
        admin_worker_exit = None
        try:
            admin_worker_exit = await asyncio.to_thread(
                capture_repository_administration,
                repository_root,
                baseline=prepared_dispatch.admin_worker_start,
                selected_worktree_gitdir=(
                    prepared_dispatch.worktree_authority.gitdir_realpath
                ),
            )
            atomic_write_json(
                run_dir / "git-admin-worker-exit.json",
                admin_worker_exit.to_dict(),
            )
            try:
                await asyncio.to_thread(
                    reconcile_repository_administration,
                    prepared_dispatch.admin_worker_start,
                    admin_worker_exit,
                )
            except RepositoryAdministrationUnreconciled as exc:
                administrative_divergences.append(
                    {
                        "attributed_to": "worker",
                        "verdict": "tamper",
                        "code": exc.code,
                        "details": exc.details,
                    }
                )
        except DispatcherError as exc:
            # An unreadable or unsupported FINALIZE capture is unknown, never
            # clean.  Validation is not launched against authority the worker
            # may already have poisoned.
            administrative_divergences.append(
                {
                    "attributed_to": "worker",
                    "verdict": "unknown_treated_as_tamper",
                    "code": exc.code,
                    "details": exc.details,
                }
            )

        native_worker_snapshot: FsSnapshot | None = None
        native_worker_attribution = None
        native_scope_verdict = None
        if prepared_dispatch is not None:
            # Gate 7: post-worker authority is raw and literal.  Exactly the
            # four sealed linked-worktree authority files are re-read; no Git
            # process exists on this side of the worker boundary.
            authority_verdict = await asyncio.to_thread(
                verify_worktree_authority, prepared_dispatch.worktree_authority
            )
            if authority_verdict.verdict != "base_held":
                observed_head = (
                    authority_verdict.observed_head_bytes.decode(
                        "ascii", errors="replace"
                    ).strip()
                    if authority_verdict.observed_head_bytes is not None
                    else ""
                )
                self._write_worktree_base_evidence(
                    envelope,
                    worktree_path=worktree_path,
                    actual_head_commit=observed_head,
                    held=False,
                    phase=run_kind.value,
                )
                self._record_bare_run(
                    envelope=envelope,
                    run_kind=run_kind,
                    role=WorkerRole.IMPLEMENTER,
                    run_index=run_index,
                    run_id=run_id,
                    session_id=session_id,
                    model=model,
                    worktree_path=str(worktree_path),
                    worker_run=worker_run,
                    started_at=started_at,
                    finished_at=finished_at,
                    worker_context=worker_context,
                )
                raise WorktreeBaseMismatch(
                    "The sealed worktree authority changed during the worker run.",
                    details={
                        "task_id": task_id,
                        "verdict": authority_verdict.verdict,
                        "expected_base_commit": envelope.repository.base_commit,
                        "actual_head_commit": observed_head or None,
                        "differences": [
                            asdict(item) for item in authority_verdict.differences
                        ],
                    },
                )
            worktree_head_commit = envelope.repository.base_commit
            native_worker_snapshot = await asyncio.to_thread(
                capture_snapshot,
                worktree_path,
                role="task_worktree_worker_exit",
            )
            native_worker_attribution = attribute_snapshots(
                prepared_dispatch.worktree_start,
                native_worker_snapshot,
                None,
                base_commit=envelope.repository.base_commit,
            )
            require_attributable(native_worker_attribution)
            native_scope_verdict = decide_scope(
                native_worker_attribution.worker_delta,
                ScopeSpecBytes.from_strings(
                    allowed_paths=envelope.scope.allowed_paths,
                    forbidden_paths=envelope.scope.forbidden_paths,
                ),
            )
            start_by_path = {
                bytes(entry.path): entry
                for entry in prepared_dispatch.worktree_start.entries
            }
            worker_by_path = {
                bytes(entry.path): entry for entry in native_worker_snapshot.entries
            }
            sealed_start = self.store.task_dir(task_id) / "evidence" / "preworker-seal"
            authority_by_path = {
                bytes(change.path): (
                    _snapshot_content_input(
                        start_by_path.get(bytes(change.path)),
                        root=worktree_path,
                        sealed_start_root=sealed_start,
                    ),
                    _snapshot_content_input(
                        worker_by_path.get(bytes(change.path)), root=worktree_path
                    ),
                )
                for change in native_worker_attribution.worker_delta.changes
            }
            classified = classify_inventory(
                native_worker_attribution.worker_delta,
                native_scope_verdict,
                authority_by_path,
            )
            canonical = build_canonical_evidence(
                classified,
                base_commit=envelope.repository.base_commit,
                patch_path=self.store.task_dir(task_id) / "evidence" / "diff.patch",
            )
            worker_evidence = canonical.to_diff_evidence()
        self._write_phase_evidence(task_id, "pre-validation", worker_evidence)

        # Step 16: persist the exact canonical byte/completeness record and the
        # three raw inputs that produced it, then freeze that declared set
        # before any trusted validation command can run.  The freeze detects
        # same-uid overwrites; it does not claim to prevent them.
        canonical_record = _canonical_evidence_record(canonical, run_index=run_index)
        self.store.write_evidence(
            task_id,
            "canonical-evidence.json",
            json.dumps(canonical_record, indent=2),
        )
        atomic_write_json(run_dir / "canonical-evidence.json", canonical_record)
        atomic_write_json(
            run_dir / "fs-snapshot-start.json",
            prepared_dispatch.worktree_start.to_dict(),
        )
        atomic_write_json(
            run_dir / "fs-snapshot-worker-exit.json",
            native_worker_snapshot.to_dict(),
        )
        atomic_write_json(
            run_dir / "path-inventory.json",
            {
                "schema": "path-inventory/1",
                "identity": classified.identity.to_dict(),
                "scope_verdict": classified.verdict.to_dict(),
                "classes": [
                    {
                        "path": os.fsdecode(row.path),
                        "content_class": row.content_class.value,
                        "ignored_by_base": row.ignored_by_base,
                        "inventory_complete": row.inventory_complete,
                    }
                    for row in classified.classes
                ],
            },
        )
        frozen_relpaths = (
            b"evidence/diff.patch",
            b"evidence/canonical-evidence.json",
            b"evidence/pre-validation-diff-stat.txt",
            b"evidence/pre-validation-status.txt",
            b"evidence/pre-validation-changed-paths.json",
            f"runs/{run_index:03d}/fs-snapshot-start.json".encode("ascii"),
            f"runs/{run_index:03d}/fs-snapshot-worker-exit.json".encode("ascii"),
            f"runs/{run_index:03d}/path-inventory.json".encode("ascii"),
            f"runs/{run_index:03d}/canonical-evidence.json".encode("ascii"),
        )
        evidence_freeze = await asyncio.to_thread(
            capture_evidence_freeze,
            self.store.task_dir(task_id),
            frozen_relpaths,
        )
        atomic_write_json(run_dir / "evidence-freeze.json", evidence_freeze.to_dict())

        # --- what the worker CLAIMED (§16) --------------------------------
        worker_result: WorkerResult | None = None
        worker_result_error: str | None = None
        # B3: the trusted half of the CLI's own result envelope, read once.
        # ``None`` when there is no envelope worth trusting (never started,
        # killed, not JSON, or not the CLI's own object). Nothing the model
        # wrote reaches this dict — see ``runner.envelope_facts``.
        cli_envelope = envelope_facts(worker_run) or {}
        if worker_run.timed_out:
            worker_result_error = (
                "worker timed out before emitting structured output; partial "
                "stdout preserved in the run directory"
            )
        elif worker_run.start_failed:
            worker_result_error = "worker process could not be started"
        elif (provider_error := provider_failure(
            worker_run, binary=self.config.claude.binary, role="implementer"
        )) is not None:
            # B3: the provider ended this run — an HTTP 429 usage limit, or
            # another API error — and said so in its own envelope. The payload
            # of a run that died upstream of the model is not a worker result,
            # so it is not parsed and not stored as one; the trusted envelope
            # facts are recorded instead. Deliberately ahead of the parser: the
            # CLI exits 0 here, so nothing else would notice.
            worker_result_error = (
                f"{provider_error.code}: {provider_error.message} "
                f"{json.dumps(provider_error.details, default=str)}"
            )
        elif (cli_error := cli_failure(
            worker_run, binary=self.config.claude.binary, role="implementer"
        )) is not None:
            # DEFECT-L2-02: a present-but-broken CLI exits non-zero with empty
            # stdout. Reporting "stdout was not valid JSON" here blames the
            # model for an environment failure; the real cause is on stderr.
            worker_result_error = f"{cli_error.message} {json.dumps(cli_error.details, default=str)}"
        else:
            try:
                # Lane B R1: never ``worker_run.stdout`` — beyond the retention
                # cap that string carries an in-band truncation marker and is
                # deliberately not JSON. ``stdout_for_parsing`` is identical for
                # every run that fits, and the recovered trailing document
                # otherwise.
                worker_result = parse_worker_result(worker_run.stdout_for_parsing)
            except ClaudeStructuredOutputInvalid as exc:
                # Not an invitation to guess (§15). It is recorded as a fact.
                worker_result_error = f"{exc.message} {json.dumps(exc.details, default=str)}"

        if worker_result is not None:
            atomic_write_json(
                self._run_dir(task_id, run_index) / "worker-result.json",
                _dump(worker_result),
            )

        # --- independent validation (§17) ---------------------------------
        validation_results: list[Any] = []
        if (
            not worker_run.timed_out
            and not worker_run.start_failed
            and not administrative_divergences
        ):
            # env is deliberately not passed: ``run_validations`` treats
            # ``env=None`` as "build the sanitized environment" (P1-6).
            validation_results = await run_validations(
                envelope,
                worktree_path,
                self.config,
                journal_path=run_dir / "validation-invocations.jsonl",
            )
        atomic_write_json(
            self._run_dir(task_id, run_index) / "validation.json",
            [_dump(v) for v in validation_results],
        )
        try:
            await asyncio.to_thread(
                verify_evidence_freeze,
                self.store.task_dir(task_id),
                evidence_freeze,
            )
        except EvidenceFreezeViolated as exc:
            administrative_divergences.append(
                {
                    "attributed_to": "validation",
                    "verdict": "tamper",
                    "code": exc.code,
                    "details": exc.details,
                }
            )
        validation_exit_repository_authority = await asyncio.to_thread(
            capture_matching_repository_authority,
            repository_root,
            prepared_dispatch.repository_authority,
            phase="validation_exit",
        )
        primary_validation_exit = await asyncio.to_thread(
            capture_snapshot,
            repository_root,
            role="primary_post",
            fidelity="stat_identity",
        )
        primary_validation_exit_head = await asyncio.to_thread(
            capture_primary_head, validation_exit_repository_authority
        )
        primary_validation_divergence = _primary_terminal_divergence(
            primary_worker_exit,
            primary_worker_exit_head,
            primary_validation_exit,
            primary_validation_exit_head,
            expected_root=validation_exit_repository_authority.canonical_root,
            attributed_to="validation",
            interval="worker_exit_to_validation_exit",
        )
        validation_exit_primary_evidence = {
            "phase": "validation_exit",
            "repository_authority": (
                validation_exit_repository_authority.to_json_dict()
            ),
            "tree": primary_validation_exit.to_dict(),
            "head": primary_validation_exit_head.to_dict(),
        }
        self.store.write_evidence(
            task_id,
            "primary-tree-validation-exit.json",
            json.dumps(validation_exit_primary_evidence, indent=2),
        )

        # --- evidence B: after validation (P1-7) --------------------------
        # Validation commands can mutate worktrees — formatters, coverage
        # files, lockfiles, snapshot updates.  Re-measure them for attribution,
        # but never replace the authoritative worker-exit evidence or verdict.
        # Skipped only when nothing ran, in which case B is A by construction.
        if prepared_dispatch is not None:
            assert native_worker_snapshot is not None
            post_validation = (
                await asyncio.to_thread(
                    capture_snapshot,
                    worktree_path,
                    role="task_worktree_post_validation",
                )
                if validation_results
                else None
            )
            # Capture #2 follows the post-validation filesystem terminal.  It
            # is compared only with capture #1, so no worker-side or primary-
            # ref exception can erase validation attribution.
            admin_validation_exit = admin_worker_exit
            if validation_results and admin_worker_exit is not None:
                try:
                    admin_validation_exit = await asyncio.to_thread(
                        capture_repository_administration,
                        repository_root,
                        baseline=admin_worker_exit,
                        selected_worktree_gitdir=(
                            prepared_dispatch.worktree_authority.gitdir_realpath
                        ),
                    )
                    atomic_write_json(
                        run_dir / "git-admin-validation-exit.json",
                        admin_validation_exit.to_dict(),
                    )
                    try:
                        await asyncio.to_thread(
                            reconcile_repository_administration,
                            admin_worker_exit,
                            admin_validation_exit,
                        )
                    except RepositoryAdministrationUnreconciled as exc:
                        administrative_divergences.append(
                            {
                                "attributed_to": "validation",
                                "verdict": "tamper",
                                "code": "ValidationTouchedAdministrativeState",
                                "details": exc.details,
                            }
                        )
                except DispatcherError as exc:
                    administrative_divergences.append(
                        {
                            "attributed_to": "validation",
                            "verdict": "unknown_treated_as_tamper",
                            "code": "ValidationTouchedAdministrativeState",
                            "capture_error": exc.code,
                            "details": exc.details,
                        }
                    )
            elif admin_validation_exit is not None:
                atomic_write_json(
                    run_dir / "git-admin-validation-exit.json",
                    admin_validation_exit.to_dict(),
                )
            if administrative_divergences:
                atomic_write_json(
                    run_dir / "git-admin-divergence.json",
                    {"divergences": administrative_divergences},
                )
            native_worker_attribution = attribute_snapshots(
                prepared_dispatch.worktree_start,
                native_worker_snapshot,
                post_validation,
                base_commit=envelope.repository.base_commit,
            )
            require_attributable(native_worker_attribution)
            final_evidence = worker_evidence
            attribution = native_worker_attribution.to_dict()
            attribution["implementer_run_index"] = run_index
            final_delta = (
                native_worker_attribution.final_delta
                or native_worker_attribution.worker_delta
            )
            attribution.update(
                worker_changed_paths=[
                    os.fsdecode(bytes(change.path))
                    for change in native_worker_attribution.worker_delta.changes
                ],
                final_changed_paths=[
                    os.fsdecode(bytes(change.path))
                    for change in final_delta.changes
                ],
                validation_added_paths=[
                    os.fsdecode(bytes(path))
                    for path in native_worker_attribution.validation_only
                ],
                validation_removed_paths=[
                    os.fsdecode(bytes(path))
                    for path in native_worker_attribution.validation_reverted
                ],
            )
            scope_verdicts = decide_scope_verdicts(
                prior_cumulative_worker=prior_cumulative_worker,
                attribution=native_worker_attribution,
                scope=scope_spec,
                base_commit=envelope.repository.base_commit,
            )
            scope = ScopeCheck(
                valid=scope_verdicts.valid,
                out_of_scope=[
                    os.fsdecode(bytes(path))
                    for path in scope_verdicts.outside_allowed
                ],
                forbidden=[
                    os.fsdecode(bytes(path))
                    for path in scope_verdicts.forbidden_hits
                ],
            )
            scope_verdict_evidence = scope_verdicts.to_dict()
            attribution["scope_verdicts"] = scope_verdict_evidence
            atomic_write_json(run_dir / "scope-verdicts.json", scope_verdict_evidence)
            atomic_write_json(run_dir / "evidence-attribution.json", attribution)
            self.store.write_evidence(
                task_id,
                "scope-verdicts.json",
                json.dumps(scope_verdict_evidence, indent=2),
            )
            assert isinstance(primary_tree_before, FsSnapshot)
            primary_tree_divergence = _combine_primary_terminal_divergences(
                primary_worker_divergence,
                primary_validation_divergence,
            )
            self.store.write_evidence(
                task_id,
                "primary-tree-before.json",
                json.dumps(worker_start_primary_evidence, indent=2),
            )
            self.store.write_evidence(
                task_id,
                "primary-tree-after.json",
                json.dumps(validation_exit_primary_evidence, indent=2),
            )
            self.store.write_evidence(
                task_id,
                "primary-tree-invariant.json",
                json.dumps(
                    {
                        "invariant": (
                            "PRIMARY_WORKER_START == PRIMARY_WORKER_EXIT and "
                            "PRIMARY_WORKER_EXIT == PRIMARY_VALIDATION_EXIT"
                        ),
                        "held": primary_tree_divergence is None,
                        "before": worker_start_primary_evidence,
                        "after": validation_exit_primary_evidence,
                        "worker_interval": {
                            "held": primary_worker_divergence is None,
                            "repository_authority_held": (
                                prepared_dispatch.repository_authority
                                == worker_exit_repository_authority
                            ),
                            "before": worker_start_primary_evidence,
                            "after": worker_exit_primary_evidence,
                            "divergence": primary_worker_divergence,
                        },
                        "validation_interval": {
                            "held": primary_validation_divergence is None,
                            "repository_authority_held": (
                                worker_exit_repository_authority
                                == validation_exit_repository_authority
                            ),
                            "before": worker_exit_primary_evidence,
                            "after": validation_exit_primary_evidence,
                            "divergence": primary_validation_divergence,
                        },
                        "divergence": primary_tree_divergence,
                    },
                    indent=2,
                ),
            )
            primary_status = "RAW_SNAPSHOT_UNMEASURED_CLEANLINESS\n"

        # Evidence is on disk before any state decision is taken (§13, §20).
        await self._write_evidence(
            task_id,
            diff_evidence=final_evidence,
            scope=scope,
            attribution=attribution,
            primary_status=primary_status,
            canonical_record=canonical_record,
        )
        # Fable must not consume claims or validation from the mutable run
        # journal.  Persist the minimal prompt input from these in-memory
        # values, then bind those exact bytes into the review freeze below.
        # The normal dispatcher-result remains an audit record, but is not an
        # authority for review input.
        atomic_write_json(
            run_dir / "fable-run-evidence.json",
            {
                "schema": "fable-run-evidence/1",
                "implementer_run_index": run_index,
                "worker_claims": _dump(worker_result),
                "validation_results": [_dump(row) for row in validation_results],
            },
        )
        # The Fable consumer is keyed to this implementer run, not to whichever
        # subprocess happened most recently. Freeze the run-specific metadata
        # and attribution together with the task-level canonical patch after
        # validation has finished and no further trusted command will run.
        review_freeze = await asyncio.to_thread(
            capture_evidence_freeze,
            self.store.task_dir(task_id),
            (
                b"evidence/diff.patch",
                f"runs/{run_index:03d}/canonical-evidence.json".encode("ascii"),
                f"runs/{run_index:03d}/evidence-attribution.json".encode("ascii"),
                f"runs/{run_index:03d}/fable-run-evidence.json".encode("ascii"),
            ),
        )
        atomic_write_json(
            run_dir / "review-evidence-freeze.json", review_freeze.to_dict()
        )

        claim_verification = compare_claims_to_validation(worker_result, validation_results)
        atomic_write_json(
            self._run_dir(task_id, run_index) / "claim-verification.json",
            claim_verification,
        )

        observations = build_dispatcher_observations(
            task_id=task_id,
            run_id=run_id,
            session_id=session_id,
            model=model,
            base_commit=envelope.repository.base_commit,
            duration_ms=worker_run.duration_ms,
            exit_code=worker_run.exit_code,
            timed_out=worker_run.timed_out,
            diff_evidence=final_evidence,
            scope_check=scope,
            worker_result=worker_result,
            worker_result_error=worker_result_error,
            # B3: the trusted envelope signals for THIS run. ``cli_envelope``
            # is derived from this run's own ``WorkerRun`` object, never by
            # searching the task directory, so a resumed run is never
            # classified from an earlier run's envelope.
            api_error_status=cli_envelope.get("api_error_status"),
            terminal_reason=cli_envelope.get("terminal_reason"),
            # B2: established by exact byte equality over the sealed worktree
            # authority paths. Equal to ``base_commit`` on every run that gets
            # this far; no post-worker Git process is used to derive it.
            worktree_head_commit=worktree_head_commit,
            # Raw equality cannot answer Git-cleanliness, so this field remains
            # explicitly unmeasured. Non-interference (post_state == pre_state)
            # is the separate, authoritative verdict below.
            primary_worktree_clean=None,
            # The invariant verdict itself, typed rather than only inferable
            # from the ``primary_tree_*`` prefixes in ``policy_violations``.
            primary_tree_unchanged=primary_tree_divergence is None,
        )

        metadata = self._run_metadata(
            envelope=envelope,
            run_kind=run_kind,
            role=WorkerRole.IMPLEMENTER,
            run_index=run_index,
            run_id=run_id,
            session_id=session_id,
            model=model,
            worktree_path=str(worktree_path),
            worker_run=worker_run,
            started_at=started_at,
            finished_at=finished_at,
            worker_context=worker_context,
        )
        self.store.append_run(
            task_id,
            RunRecord(
                metadata=metadata,
                # Two fields, permanently separate. Never merged (§16).
                worker_claims=worker_result,
                dispatcher_observations=observations,
                validation_results=validation_results,
            ),
        )

        record = self._land_state(
            task_id=task_id,
            scope=scope,
            scope_verdicts=scope_verdicts,
            worker_run=worker_run,
            worker_result=worker_result,
            worker_result_error=worker_result_error,
            primary_tree_divergence=primary_tree_divergence,
            administrative_divergences=administrative_divergences,
        )

        if record.state not in WORKER_ACTIONABLE_STATES:  # pragma: no cover - invariant
            # GATE 6 §2. A blocking call must end on a state Sol can act on.
            # Landing anywhere else means ``_land_state`` grew a path that
            # returns mid-lifecycle, which would silently reintroduce polling.
            # Logged rather than raised: the state is already persisted, and
            # turning a completed run into an error payload would destroy
            # evidence to report a dispatcher bug. The payload says
            # ``worker_actionable: false`` either way, so nothing is claimed
            # that is not true.
            logger.error(
                "run for task %s ended in %s, which is not worker-actionable",
                task_id,
                record.state.value,
            )

        _event(
            "run_complete",
            task_id=task_id,
            run_id=run_id,
            status=record.state.value,
            duration=worker_run.duration_ms,
            exit_code=worker_run.exit_code,
            timed_out=worker_run.timed_out,
            scope_valid=scope.valid,
            primary_tree_unchanged=primary_tree_divergence is None,
        )

        return {
            "task_id": task_id,
            "run_id": run_id,
            "selected_model": model,
            "session_id": session_id,
            "worktree": str(worktree_path),
            "status": record.state.value,
            "state": record.state.value,
            "resume_count": record.resume_count,
            "worker_claims": _dump(worker_result),
            "worker_result_error": worker_result_error,
            "dispatcher_observations": _dump(observations),
            "validation_results": [_dump(v) for v in validation_results],
            "claim_verification": claim_verification,
            "scope": {
                "valid": scope.valid,
                "out_of_scope": list(scope.out_of_scope),
                "forbidden": list(scope.forbidden),
                "verdicts": scope_verdict_evidence,
            },
            "evidence_attribution": attribution,
            "primary_tree": {
                "unchanged": primary_tree_divergence is None,
                "divergence": primary_tree_divergence,
            },
            "administrative_authority": {
                "unchanged": not administrative_divergences,
                "divergences": administrative_divergences,
            },
            "last_error": record.last_error,
            # GATE 6 §2/§3. Restated in-band, because the server instructions
            # are read once at initialise time while this travels with every
            # result: this call already waited, nothing needs polling, and the
            # next decision is Sol's.
            "blocking": blocking_envelope(record.state),
        }

    # -- evidence -----------------------------------------------------------

    def _write_phase_evidence(
        self, task_id: str, phase: str, diff_evidence: DiffEvidence
    ) -> None:
        """Persist one evidence phase under a ``<phase>-`` prefix (P1-7).

        Phase A (``pre-validation``) is written before the dispatcher runs a
        single validation command, so the worker's own footprint survives even
        if validation, or anything after it, fails.
        """
        self.store.write_evidence(
            task_id, f"{phase}-diff-stat.txt", diff_evidence.diff_stat
        )
        self.store.write_evidence(
            task_id, f"{phase}-status.txt", diff_evidence.porcelain_status
        )
        self.store.write_evidence(
            task_id,
            f"{phase}-changed-paths.json",
            json.dumps(
                {
                    "phase": phase,
                    "base_commit": diff_evidence.base_commit,
                    "changed_paths": list(diff_evidence.changed_paths),
                    "diff_total_bytes": diff_evidence.diff_total_bytes,
                },
                indent=2,
            ),
        )

    def _write_primary_tree_snapshot(
        self, task_id: str, phase: str, snapshot: PrimaryTreeSnapshot
    ) -> None:
        """Persist one primary-tree fingerprint (P1-5). Both phases are kept."""
        self.store.write_evidence(
            task_id,
            f"primary-tree-{phase}.txt",
            f"HEAD {snapshot.head_commit}\n{snapshot.porcelain_status}",
        )

    def _write_primary_tree_invariant(
        self,
        task_id: str,
        before: PrimaryTreeSnapshot,
        after: PrimaryTreeSnapshot,
        divergence: dict[str, Any] | None,
    ) -> None:
        """Persist the before/after comparison and its verdict (P1-5)."""
        self.store.write_evidence(
            task_id,
            "primary-tree-invariant.json",
            json.dumps(
                {
                    "invariant": "post_state == pre_state",
                    "held": divergence is None,
                    "before": before.as_dict(),
                    "after": after.as_dict(),
                    "divergence": divergence,
                    "limitation": (
                        "Detection only. Without OS-level sandboxing a worker "
                        "can modify a file and restore it before exiting, and "
                        "changes to git-ignored files are invisible to "
                        "git status. This is not a sandbox."
                    ),
                },
                indent=2,
            ),
        )

    def _load_fable_evidence(self, task_id: str) -> FableEvidenceBundle:
        """Load one latest IMPLEMENTER run's complete, frozen review bundle."""
        implementer_runs = [
            run
            for run in self.store.load_runs(task_id)
            if run.metadata.role is WorkerRole.IMPLEMENTER
        ]
        if not implementer_runs:
            raise EvidenceIncompleteForReview(
                "The task has no canonical worker evidence to review.",
                details={"task_id": task_id},
            )
        selected_run = implementer_runs[-1]
        run_index = selected_run.metadata.run_index
        run_dir = self.store.run_dir(task_id, run_index)
        freeze_path = run_dir / "review-evidence-freeze.json"
        try:
            freeze_value = json.loads(freeze_path.read_bytes())
            if not isinstance(freeze_value, dict):
                raise ValueError("freeze record is not an object")
            frozen = EvidenceFreeze.from_dict(freeze_value)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise EvidenceFreezeViolated(
                "The selected implementer run's review freeze is unavailable.",
                details={"changed_files": ["<freeze-record>"], "task_id": task_id},
            ) from exc
        verify_evidence_freeze(self.store.task_dir(task_id), frozen)

        try:
            raw_run_evidence = json.loads(
                (run_dir / "fable-run-evidence.json").read_bytes()
            )
            if not isinstance(raw_run_evidence, dict) or set(raw_run_evidence) != {
                "schema",
                "implementer_run_index",
                "worker_claims",
                "validation_results",
            }:
                raise ValueError("Fable run evidence has the wrong schema")
            if raw_run_evidence["schema"] != "fable-run-evidence/1":
                raise ValueError("Fable run evidence has an unsupported version")
            if raw_run_evidence["implementer_run_index"] != run_index:
                raise ValueError("Fable run evidence belongs to another run")
            raw_claims = raw_run_evidence["worker_claims"]
            worker_claims = (
                None if raw_claims is None else WorkerResult.model_validate(raw_claims)
            )
            raw_validation = raw_run_evidence["validation_results"]
            if not isinstance(raw_validation, list):
                raise ValueError("Fable validation evidence is not a list")
            validation_results = tuple(
                ValidationResult.model_validate(row) for row in raw_validation
            )
        except (
            KeyError,
            OSError,
            TypeError,
            ValueError,
            ValidationError,
            json.JSONDecodeError,
        ) as exc:
            raise EvidenceFreezeViolated(
                "The selected implementer run's frozen claims or validation are malformed.",
                details={
                    "changed_files": [
                        f"runs/{run_index:03d}/fable-run-evidence.json"
                    ],
                    "task_id": task_id,
                },
            ) from exc

        try:
            metadata = json.loads((run_dir / "canonical-evidence.json").read_bytes())
            if not isinstance(metadata, dict):
                raise ValueError("canonical metadata is not an object")
            if metadata["implementer_run_index"] != run_index:
                raise ValueError("canonical metadata belongs to another run")
            patch_bytes = metadata["patch_bytes"]
            patch_sha256 = metadata["patch_sha256"]
            patch_file_complete = metadata["patch_file_complete"]
            inventory = metadata["per_path"]
            if (
                not isinstance(patch_bytes, int)
                or isinstance(patch_bytes, bool)
                or patch_bytes < 0
                or not isinstance(patch_sha256, str)
                or len(patch_sha256) != 64
                or not isinstance(patch_file_complete, bool)
                or not isinstance(inventory, list)
            ):
                raise ValueError("canonical metadata fields have invalid types")
            required = {"path", "change", "mode", "size", "sha256"}
            if any(
                not isinstance(row, dict)
                or not required.issubset(row)
                or not isinstance(row["path"], str)
                or not isinstance(row["change"], str)
                or (row["mode"] is not None and not isinstance(row["mode"], str))
                or (row["size"] is not None and not isinstance(row["size"], int))
                or (row["sha256"] is not None and not isinstance(row["sha256"], str))
                for row in inventory
            ):
                raise ValueError("worker inventory is malformed")
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EvidenceFreezeViolated(
                "The selected implementer run's canonical evidence is malformed.",
                details={
                    "changed_files": [f"runs/{run_index:03d}/canonical-evidence.json"],
                    "task_id": task_id,
                },
            ) from exc

        omissions = [
            {"path": row.get("path"), "reason": row.get("omission_reason")}
            for row in metadata.get("per_path", [])
            if isinstance(row, dict) and row.get("omission_reason") is not None
        ]
        if not patch_file_complete:
            raise EvidenceIncompleteForReview(
                "The canonical worker patch omits changed content.",
                details={"task_id": task_id, "omitted": omissions},
                remediation="Inspect the inventory and use a human review path for unsupported content.",
            )

        path = self.store.task_dir(task_id) / "evidence" / "diff.patch"
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise OSError("diff.patch is not a regular file")
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(
                os, "O_NOFOLLOW", 0
            )
            fd = os.open(path, flags)
            try:
                opened = os.fstat(fd)
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                patch_data = b"".join(chunks)
                after = os.fstat(fd)
            finally:
                os.close(fd)
        except OSError as exc:
            raise EvidenceFreezeViolated(
                "The canonical patch cannot be read as a regular frozen file.",
                details={"changed_files": ["evidence/diff.patch"], "task_id": task_id},
            ) from exc
        if (
            (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or len(patch_data) != patch_bytes
            or info.st_size != patch_bytes
            or hashlib.sha256(patch_data).hexdigest() != patch_sha256
        ):
            raise EvidenceFreezeViolated(
                "The canonical patch no longer matches its exact byte record.",
                details={"changed_files": ["evidence/diff.patch"], "task_id": task_id},
            )
        try:
            raw_attribution = json.loads(
                (run_dir / "evidence-attribution.json").read_bytes()
            )
            if (
                not isinstance(raw_attribution, dict)
                or raw_attribution.get("implementer_run_index") != run_index
                or raw_attribution.get("verdict") != "attributable"
            ):
                raise ValueError("attribution does not identify the selected run")
            rendered_attribution: dict[str, list[str]] = {}
            for field in (
                "validation_only",
                "both_authors",
                "validation_reverted",
            ):
                rows = raw_attribution[field]
                if not isinstance(rows, list):
                    raise ValueError(f"{field} is not a list")
                rendered: list[str] = []
                for row in rows:
                    if isinstance(row, str):
                        rendered.append(row)
                    elif isinstance(row, dict) and isinstance(row.get("display"), str):
                        rendered.append(row["display"])
                    else:
                        raise ValueError(f"{field} contains a malformed path")
                rendered_attribution[field] = rendered
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EvidenceIncompleteForReview(
                "The selected implementer run's validation attribution is unavailable.",
                details={"task_id": task_id, "run_index": run_index},
            ) from exc

        return FableEvidenceBundle(
            run_index=run_index,
            worker_claims=worker_claims,
            validation_results=validation_results,
            patch_data=patch_data,
            patch_text=os.fsdecode(patch_data),
            patch_sha256=patch_sha256,
            patch_file_complete=patch_file_complete,
            inventory=inventory,
            attribution=rendered_attribution,
        )

    def _record_primary_tree_on_failure_path(
        self,
        task_id: str,
        repository_root: Path,
        before: PrimaryTreeSnapshot,
    ) -> None:
        """Best-effort primary-tree check on a path already landing a failure.

        The caller is about to raise a specific, useful error. A second git
        failure here must not replace it, so this records what it can and
        returns; the state the task lands in is explicit either way.
        """
        try:
            after = snapshot_primary_tree(repository_root)
        except DispatcherError:
            logger.warning(
                "primary-tree fingerprint unavailable for task %s on the "
                "worktree-missing path", task_id, exc_info=True
            )
            return
        divergence = compare_primary_tree(before, after)
        try:
            self._write_primary_tree_snapshot(task_id, "after", after)
            self._write_primary_tree_invariant(task_id, before, after, divergence)
        except DispatcherError:  # pragma: no cover - defensive
            logger.warning("could not persist primary-tree evidence for %s", task_id)
            return
        if divergence is not None:
            _event(
                "primary_tree_interference",
                task_id=task_id,
                markers=_interference_markers(divergence),
            )

    async def _write_evidence(
        self,
        task_id: str,
        *,
        diff_evidence: DiffEvidence,
        scope: ScopeCheck,
        attribution: dict[str, Any],
        primary_status: str,
        canonical_record: dict[str, Any],
    ) -> None:
        """Persist the §27 evidence artefacts. Never deleted on failure (§13).

        ``diff.patch`` and its exact metadata were written and frozen before
        validation.  This method never repairs or regenerates that file: a
        validation overwrite must remain visible to the freeze verdict.
        """
        self.store.write_evidence(task_id, "diff-stat.txt", diff_evidence.diff_stat)
        self.store.write_evidence(
            task_id,
            "changed-paths.json",
            json.dumps(
                {
                    "base_commit": diff_evidence.base_commit,
                    "changed_paths": list(diff_evidence.changed_paths),
                    "out_of_scope": list(scope.out_of_scope),
                    "forbidden": list(scope.forbidden),
                    "diff_bytes_retained": canonical_record["patch_bytes"],
                    "diff_total_bytes": diff_evidence.diff_total_bytes,
                    "diff_patch_bytes": canonical_record["patch_bytes"],
                    "diff_patch_sha256": canonical_record["patch_sha256"],
                    "diff_patch_complete": canonical_record["patch_file_complete"],
                    "patch_file_complete": canonical_record["patch_file_complete"],
                },
                indent=2,
            ),
        )
        self.store.write_evidence(
            task_id, "evidence-phases.json", json.dumps(attribution, indent=2)
        )
        self.store.write_evidence(task_id, "status.txt", diff_evidence.porcelain_status)
        self.store.write_evidence(
            task_id, "diff-check.txt", diff_evidence.diff_check_output
        )
        self.store.write_evidence(task_id, "primary-tree-status.txt", primary_status)

    def _land_state(
        self,
        *,
        task_id: str,
        scope: ScopeCheck,
        scope_verdicts: ScopeVerdictSet,
        worker_run: WorkerRun,
        worker_result: WorkerResult | None,
        worker_result_error: str | None,
        primary_tree_divergence: dict[str, Any] | None = None,
        administrative_divergences: list[dict[str, Any]] | None = None,
    ) -> TaskRecord:
        """Decide the post-run state. Deterministic, in a fixed precedence.

        Policy enforcement is checked first: §13 says an unauthorised change is
        a policy violation whatever else happened, and the evidence is kept
        rather than deleted. That covers two independent measurements — a change
        outside the declared scope inside the worktree, and any change at all to
        the *primary* tree (P1-5). A timeout is next (§20), then a run the
        provider itself ended (B3), then an unusable worker report, then the
        process outcome, then the worker's own status.

        The timeout branch stays ahead of the provider branch on purpose: a run
        the dispatcher killed is a timeout, and a 429 envelope sitting in its
        partial stdout does not turn it into a provider limit. The provider
        branch stays ahead of everything after it for the mirror-image reason:
        a limited run produced no work, so neither its exit code nor its
        envelope's ``subtype: "success"`` says anything about the task.

        A primary-tree divergence never falls through to
        ``AWAITING_SOL_REVIEW``: the worker escaped its isolation, and that is a
        refusal whatever the worker claimed and whatever the exit code was.
        """
        # The worktree path is recorded the moment it is resolved, not here, so
        # it survives a failure between the run and this decision.
        updates: dict[str, Any] = {}

        administrative_divergences = administrative_divergences or []
        if (
            not scope.valid
            or primary_tree_divergence is not None
            or administrative_divergences
        ):
            details: dict[str, Any] = {
                "task_id": task_id,
                "out_of_scope": list(scope.out_of_scope),
                "forbidden": list(scope.forbidden),
                "scope_verdicts": scope_verdicts.to_dict(),
            }
            reasons: list[str] = []
            if not scope.valid:
                reasons.append("scope_violation")
            if scope_verdicts.validation.forbidden_hits:
                reasons.append("validation_forbidden_path")
            if primary_tree_divergence is not None:
                primary_actors = list(
                    primary_tree_divergence.get("attributed_to", ["worker"])
                )
                reasons.extend(
                    f"primary_tree_{actor}_interference"
                    for actor in primary_actors
                )
                details["primary_tree_divergence"] = primary_tree_divergence
            if administrative_divergences:
                reasons.append("administrative_authority_tamper")
                details["administrative_divergences"] = administrative_divergences
            parts: list[str] = []
            if (
                scope_verdicts.run_worker.outside_allowed
                or scope_verdicts.run_worker.forbidden_hits
                or scope_verdicts.cumulative_worker.outside_allowed
                or scope_verdicts.cumulative_worker.forbidden_hits
            ):
                parts.append("Worker changed paths outside the task's declared scope")
            if scope_verdicts.validation.forbidden_hits:
                parts.append("Validation changed caller-forbidden paths")
            if primary_tree_divergence is not None:
                primary_actor_text = " and ".join(primary_actors).capitalize()
                parts.append(
                    f"{primary_actor_text} changed the primary repository "
                    "authority during its measured interval"
                )
            if administrative_divergences:
                actors = sorted(
                    {
                        str(item["attributed_to"])
                        for item in administrative_divergences
                    }
                )
                parts.append(
                    "Protected repository administrative authority changed "
                    f"(attributed to {', '.join(actors)})"
                )
            message = "; ".join(parts) + "."
            error = PolicyViolation(
                message,
                details=details,
                remediation=(
                    "Evidence is preserved, before and after. Reject the work, "
                    "or issue a corrective resume; the dispatcher will not decide."
                ),
            )
            record = self.store.load(task_id)
            violations = list(record.policy_violations)
            violations += [f"out_of_scope:{p}" for p in scope.out_of_scope]
            validation_forbidden = {
                os.fsdecode(bytes(path))
                for path in scope_verdicts.validation.forbidden_hits
            }
            violations += [
                f"forbidden:{p}"
                for p in scope.forbidden
                if p not in validation_forbidden
            ]
            violations += [
                f"forbidden_validation:{p}" for p in sorted(validation_forbidden)
            ]
            if primary_tree_divergence is not None:
                violations += _interference_markers(primary_tree_divergence)
            violations += _administrative_markers(administrative_divergences)
            violations = list(dict.fromkeys(violations))
            return self.store.transition(
                task_id,
                TaskState.POLICY_VIOLATION,
                reason="+".join(reasons),
                last_error=error.to_payload(),
                policy_violations=violations,
                **updates,
            )

        if worker_run.timed_out:
            error = ClaudeTimedOut(
                "Worker exceeded its timeout and was terminated.",
                details={
                    "task_id": task_id,
                    "killed_with_sigkill": worker_run.killed_with_sigkill,
                },
                remediation=(
                    "Partial output, the session and the worktree are "
                    "preserved. Resume with a narrower instruction, or accept "
                    "the partial state."
                ),
            )
            return self.store.transition(
                task_id,
                TaskState.TIMED_OUT,
                reason="timeout",
                last_error=error.to_payload(),
                **updates,
            )

        # B3: a run the *provider* ended. Checked ahead of every remaining
        # branch — including the worker's own report — because a usage limit
        # returns a well-formed envelope with exit 0 and no work behind it, and
        # every downstream reading of that is vacuous. A limited run is never
        # an implementation, however complete its envelope looks; Gate 4.5
        # refuses to score one for the same reason.
        provider_error = provider_failure(
            worker_run, binary=self.config.claude.binary, role="implementer"
        )
        if provider_error is not None:
            provider_error.details["task_id"] = task_id
            return self.store.transition(
                task_id,
                TaskState.FAILED,
                reason=str(provider_error.details["reason"]),
                last_error=provider_error.to_payload(),
                **updates,
            )

        if worker_result is None:
            # DEFECT-L2-02: distinguish "the CLI never produced anything" from
            # "the model's output did not parse". A present-but-broken binary
            # exits non-zero with empty stdout, and calling that a structured
            # output problem sends the operator hunting the wrong layer.
            cli_error = cli_failure(
                worker_run, binary=self.config.claude.binary, role="implementer"
            )
            if cli_error is not None:
                cli_error.details["task_id"] = task_id
                return self.store.transition(
                    task_id,
                    TaskState.FAILED,
                    reason="cli_unusable",
                    last_error=cli_error.to_payload(),
                    **updates,
                )
            error = ClaudeStructuredOutputInvalid(
                "Worker produced no usable structured result.",
                details={"task_id": task_id, "reason": worker_result_error},
                remediation=(
                    "Raw stdout is preserved in the run directory. The "
                    "dispatcher does not scrape prose (§15)."
                ),
            )
            return self.store.transition(
                task_id,
                TaskState.FAILED,
                reason="unparseable_worker_result",
                last_error=error.to_payload(),
                **updates,
            )

        if worker_run.exit_code != 0:
            error = ClaudeExecutionFailed(
                "Worker exited with a non-zero status.",
                details={"task_id": task_id, "exit_code": worker_run.exit_code},
            )
            return self.store.transition(
                task_id,
                TaskState.FAILED,
                reason=f"exit_code:{worker_run.exit_code}",
                last_error=error.to_payload(),
                **updates,
            )

        if worker_result.status is WorkerStatus.BLOCKED:
            return self.store.transition(
                task_id, TaskState.BLOCKED, reason="worker_blocked", **updates
            )

        if worker_result.status is WorkerStatus.FAILED:
            error = ClaudeExecutionFailed(
                "Worker reported that it failed.",
                details={"task_id": task_id, "summary": worker_result.summary[:500]},
            )
            return self.store.transition(
                task_id,
                TaskState.FAILED,
                reason="worker_reported_failure",
                last_error=error.to_payload(),
                **updates,
            )

        self.store.transition(
            task_id, TaskState.IMPLEMENTED, reason="worker_completed", **updates
        )
        # Implementation completion is not approval (§26, §41). The task waits
        # for Sol; the dispatcher has no APPROVED state to move it to.
        return self.store.transition(
            task_id, TaskState.AWAITING_SOL_REVIEW, reason="awaiting_sol_review"
        )

    def _record_failure(
        self,
        execution: ToolExecution,
        exc: DispatcherError,
        *,
        repository_key: str | None = None,
    ) -> None:
        """Best-effort: persist the error into task state before it is returned.

        §29: diagnostics live in state, the MCP response stays concise. A
        failure to record must never mask the original error.
        """
        current = current_execution()
        if current is not execution:
            raise InternalDispatcherError(
                "Failure recording execution is not current.",
                details={"tool": execution.tool},
            )

        task_id = execution.task_id
        try:
            if execution.worker is None:
                refusal = {
                    "at": utc_now().isoformat(),
                    "tool": execution.tool,
                    "phase": execution.phase.name,
                    "code": exc.code,
                    "message": exc.message,
                    "details": dict(exc.details),
                }
                if task_id and self.store.exists(task_id):
                    self.store.append_refusal(refusal, task_id=task_id)
                elif repository_key is not None:
                    self.store.append_refusal(
                        refusal, repository_key=repository_key
                    )
                return
            if not task_id or not self.store.exists(task_id):
                return
            record = self.store.load(task_id)
            if record.state in {
                TaskState.CREATED,
                TaskState.ROUTED,
                TaskState.RUNNING,
                TaskState.RESUME_REQUESTED,
            }:
                self.store.transition(
                    task_id,
                    TaskState.FAILED,
                    reason=(
                        "worktree_base_mismatch"
                        if exc.code == "WorktreeBaseMismatch"
                        else f"error:{exc.code}"
                    ),
                    last_error=exc.to_payload(),
                )
            else:
                record.last_error = exc.to_payload()
                self.store.save(record)
        except Exception:  # pragma: no cover - defensive
            logger.warning("could not record failure for task %s", task_id, exc_info=True)


def _inherited_dispatch_depth() -> int:
    """Read ``SOL_DISPATCH_DEPTH`` from the environment (§22 layer 5).

    A dispatcher started by a worker would carry a depth marker; an
    unparseable value is treated as the maximum-suspicion case rather than as
    zero, so the depth check fails closed.
    """
    raw = os.environ.get("SOL_DISPATCH_DEPTH")
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 1_000_000


def _tail_text(text: str, limit: int = 2000) -> str:
    return text[-limit:] if len(text) > limit else text


# ---------------------------------------------------------------------------
# MCP wiring
# ---------------------------------------------------------------------------


async def _guarded(call: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    """Run a tool body, converting every failure into a concise payload (§29).

    Never returns a traceback to Sol. A ``DispatcherError`` becomes its own
    structured payload; anything else is a bug in this codebase, logged with a
    traceback to **stderr** and reported as ``InternalDispatcherError``.
    """
    try:
        return await call()
    except DispatcherError as exc:
        logger.warning("tool refused: %s: %s", exc.code, exc.message)
        return exc.to_payload()
    except Exception as exc:  # noqa: BLE001 - the MCP boundary catches everything
        logger.error("unhandled error in tool body\n%s", traceback.format_exc())
        return InternalDispatcherError(
            "The dispatcher hit an unexpected internal error.",
            details={"exception": type(exc).__name__},
            remediation="Check the dispatcher log on stderr; the traceback is recorded there.",
        ).to_payload()


def resolve_config_path(config_path: str | os.PathLike[str] | None = None) -> Path:
    """Config path precedence: explicit argument, else the canonical config.

    B4. There is deliberately no environment branch here. ``SOL_DISPATCHER_CONFIG``
    used to sit in the middle of this precedence chain, which made the
    registered production server's repository allowlist changeable by a
    process-local environment (see
    :mod:`sol_claude_dispatcher.config_authority`). The environment is now read
    in exactly one place, for exactly one purpose — to *refuse* startup — and
    selects nothing anywhere.

    Tests and the disposable harness pass ``config_path`` explicitly; that is
    the supported way to run against a temporary configuration, and it still
    works unchanged.
    """
    if config_path is not None:
        return Path(config_path)
    return canonical_production_config_path()


def build_dispatcher(config_path: str | os.PathLike[str] | None = None) -> Dispatcher:
    """Load config and construct the :class:`Dispatcher`, refusing recursion."""
    # §22 layer 4, before any I/O: a dispatcher running inside a worker refuses
    # to initialise at all. assert_no_recursion ignores its config argument.
    assert_no_recursion(_NO_CONFIG)
    config = load_config(resolve_config_path(config_path))
    assert_no_recursion(config)
    return Dispatcher(config)


def build_server(config_path: str | os.PathLike[str] | None = None) -> "MCPServer":
    """Construct the configured ``MCPServer`` with the four tools registered."""
    from mcp.server import MCPServer

    dispatcher = build_dispatcher(config_path)
    configure_logging(dispatcher.config)

    server = MCPServer(
        name="sol-claude-dispatcher",
        instructions=SERVER_INSTRUCTIONS,
        version=__version__,
    )

    @server.tool(
        name="dispatch_claude_task",
        description=TOOL_DESCRIPTIONS["dispatch_claude_task"],
    )
    async def dispatch_claude_task(request: dict[str, Any]) -> dict[str, Any]:
        return await dispatcher.dispatch_claude_task(request)

    @server.tool(
        name="resume_claude_task",
        description=TOOL_DESCRIPTIONS["resume_claude_task"],
    )
    async def resume_claude_task(
        task_id: str, instruction: str, timeout_seconds: int | None = None
    ) -> dict[str, Any]:
        return await dispatcher.resume_claude_task(task_id, instruction, timeout_seconds)

    @server.tool(
        name="review_task_with_fable",
        description=TOOL_DESCRIPTIONS["review_task_with_fable"],
    )
    async def review_task_with_fable(
        task_id: str, focus: list[str] | None = None
    ) -> dict[str, Any]:
        return await dispatcher.review_task_with_fable(task_id, focus)

    @server.tool(name="get_task", description=TOOL_DESCRIPTIONS["get_task"])
    async def get_task(task_id: str) -> dict[str, Any]:
        return await dispatcher.get_task(task_id)

    # Keep the adapters referenced so linters do not strip them; the decorators
    # already registered them with the server.
    _ = (dispatch_claude_task, resume_claude_task, review_task_with_fable, get_task)
    return server


def main() -> None:
    """PRODUCTION console-script entrypoint: canonical config, stdio transport.

    This is the command registered as ``sol_claude_dispatcher`` in
    ``~/.codex/config.toml``. B4: it loads the canonical production
    configuration and refuses to start under one the environment chose, so
    widening ``security.allowed_repository_roots`` requires a deliberate,
    persistent edit to the canonical file rather than a process-local variable.

    To run a temporary configuration, use
    ``python -m sol_claude_dispatcher.dev_server <config>`` (test/development
    only, refuses the production boundary) or call ``build_server(path)``.
    """
    try:
        # The environment is consulted here and nowhere else, and only to
        # refuse. The path handed to build_server is the canonical one on every
        # path through this function.
        canonical = assert_production_config_authority()
        server = build_server(canonical)
    except DispatcherError as exc:
        # Startup diagnostics go to stderr; stdout is the transport (§28).
        print(json.dumps(exc.to_payload()), file=sys.stderr)
        raise SystemExit(2) from exc
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":  # pragma: no cover - console entrypoint
    main()
