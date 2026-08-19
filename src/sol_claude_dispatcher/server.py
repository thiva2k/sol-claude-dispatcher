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
import json
import logging
import os
import stat
import sys
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, TYPE_CHECKING, cast

from pydantic import ValidationError

from . import __version__
from .config import Config, DEFAULT_CONFIG_FILENAME, load_config
from .errors import (
    ClaudeExecutionFailed,
    ClaudeStructuredOutputInvalid,
    ClaudeTimedOut,
    DispatcherError,
    GitEvidenceCollectionFailed,
    InternalDispatcherError,
    InvalidTaskEnvelope,
    PolicyViolation,
    ResumeLimitReached,
    StateCorruption,
    WorktreeCreationFailed,
)
from .git import (
    DiffEvidence,
    ScopeCheck,
    check_scope,
    collect_diff_evidence,
    primary_tree_status,
    resolve_base_commit,
    worktree_path_for,
    write_full_diff,
)
from .locks import RepositoryLock
from .models import (
    RunKind,
    RunMetadata,
    RunRecord,
    TaskEnvelope,
    TaskRecord,
    TaskRequest,
    TaskState,
    WorkerResult,
    WorkerRole,
    WorkerStatus,
    new_run_id,
    new_session_id,
    new_task_id,
    utc_now,
)
from .results import build_dispatcher_observations, parse_fable_review, parse_worker_result
from .router import explain_route
from .runner import (
    WorkerInvocation,
    WorkerRun,
    build_fable_invocation,
    build_worker_invocation,
    run_worker,
)
from .security import (
    assert_dispatch_depth,
    assert_no_recursion,
    redact,
    validate_repository_root,
    validate_task_id,
)
from .sessions import new_session, resume_limit_response, resume_plan
from .state import TaskStore, atomic_write_json, atomic_write_text
from .validation import compare_claims_to_validation, run_validations

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp.server import MCPServer

__all__ = [
    "SERVER_INSTRUCTIONS",
    "TOOL_NAMES",
    "TOOL_DESCRIPTIONS",
    "Dispatcher",
    "build_dispatcher",
    "build_server",
    "configure_logging",
    "resolve_config_path",
    "main",
]

#: §6 — the first thing Sol reads about this server.
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
must not be collapsed.
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
        "observations separately. Completion is evidence, never approval."
    ),
    "resume_claude_task": (
        "Continue an existing task's worker conversation in the same session, "
        "model and worktree. Session identity comes from stored state, never "
        "from the caller. Refuses past the configured resume cap."
    ),
    "review_task_with_fable": (
        "Run an independent, read-only Fable review of a task's recorded "
        "evidence in a fresh session. The verdict is advisory to Sol and never "
        "changes approval state."
    ),
    "get_task": (
        "Read a task's authoritative state: envelope, status, model, worktree, "
        "session, resume count, run and validation history, latest worker "
        "result, latest Fable review, policy violations and timeout info. "
        "Read-only."
    ),
}

#: Environment variable naming the config file for ``main()``.
CONFIG_ENV_VAR = "SOL_DISPATCHER_CONFIG"

#: Where ``main()`` looks when :data:`CONFIG_ENV_VAR` is unset.
DEFAULT_CONFIG_PATH = Path("config") / DEFAULT_CONFIG_FILENAME

#: ``security.assert_no_recursion`` ignores its ``config`` argument (the check
#: is unconditional). Startup runs it *before* config loading so a dispatcher
#: launched inside a worker refuses immediately, whatever the config says.
_NO_CONFIG = cast("Config", None)

#: argv elements longer than this are elided in ``RunMetadata.argv_redacted``.
#: The full policy text and JSON schema are already on disk; repeating them in
#: every run record would bloat state for no audit value.
_MAX_RECORDED_ARGV_ELEMENT = 512

#: Cap on the unified diff injected into Fable's prompt (§7.3: prefer state
#: over enormous command-line arguments). The full patch stays in
#: ``evidence/diff.patch``.
_MAX_PROMPT_DIFF_CHARS = 120_000

#: Cap on any single evidence section rendered into a prompt.
_MAX_PROMPT_SECTION_CHARS = 8_000

#: Cap on how much of ``evidence/diff.patch`` is *read* to build a review
#: prompt. The file is the complete patch and therefore unbounded; the prompt
#: clips at :data:`_MAX_PROMPT_DIFF_CHARS` regardless, so reading beyond this
#: would only let a runaway worker choose the dispatcher's allocation size.
_MAX_PROMPT_PATCH_BYTES = 2 * _MAX_PROMPT_DIFF_CHARS

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


def _interference_markers(divergence: dict[str, Any]) -> list[str]:
    """Policy-violation strings for a primary-tree divergence, for state."""
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
    changed_paths: list[str],
    worker_claims: WorkerResult | None,
    validation_results: list[Any],
    focus: list[str],
    validation_added_paths: list[str] | None = None,
) -> str:
    """Render the independent review prompt from *stored* evidence (§7.3, §19)."""
    lines = [
        "# Independent review",
        "",
        "You are reviewing work produced by a different agent. You do not "
        "implement, and you do not modify files.",
        "",
        "## Original objective",
        "",
        envelope.task.objective.strip(),
    ]
    if envelope.task.acceptance_criteria:
        lines += ["", "## Acceptance criteria", ""]
        lines += [f"{i}. {c}" for i, c in enumerate(envelope.task.acceptance_criteria, 1)]

    lines += [
        "",
        "## Revision under review",
        "",
        f"Base commit: {envelope.repository.base_commit}",
        f"Worktree: {envelope.worktree_name}",
        "",
        "### Changed paths",
        "",
    ]
    lines += [f"- {p}" for p in changed_paths] or ["(no changed paths recorded)"]

    if validation_added_paths:
        # P1-7: without this the reviewer attributes a coverage file or a
        # formatter's rewrite to the worker under review.
        lines += [
            "",
            "### Paths produced by the dispatcher's own validation, not by the worker",
            "",
        ]
        lines += [f"- {p}" for p in validation_added_paths]
        lines.append("")
        lines.append("Do not raise findings against the worker for those paths.")

    lines += ["", "## Unified diff", "", "```diff", _clip(diff_text, _MAX_PROMPT_DIFF_CHARS), "```"]

    lines += ["", "## Worker report (claims, not evidence)", ""]
    if worker_claims is None:
        lines.append("(the worker produced no parseable structured report)")
    else:
        lines += ["```json", _clip(json.dumps(_dump(worker_claims), indent=2)), "```"]

    lines += ["", "## Dispatcher validation (independently measured)", ""]
    if not validation_results:
        lines.append("(dispatcher validation was not run for this task)")
    else:
        lines += [
            "```json",
            _clip(json.dumps([_dump(v) for v in validation_results], indent=2)),
            "```",
        ]

    if focus:
        lines += ["", "## Review focus requested by the orchestrator", ""]
        lines += [f"- {item}" for item in focus]

    lines += [
        "",
        "## Output contract",
        "",
        "Return exactly one JSON object matching the supplied --json-schema. "
        "Do not manufacture findings to appear useful. Every material finding "
        "needs evidence. Your verdict is advisory.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# the dispatcher — one instance per server process
# ---------------------------------------------------------------------------


class Dispatcher:
    """Deterministic implementation of the four MCP tools.

    Holds no authoritative in-memory state: every tool reloads the task from
    disk through :class:`~sol_claude_dispatcher.state.TaskStore`, so a restarted
    server sees exactly what the previous one persisted (§27).
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.store = TaskStore(config.tasks_path)

    # -- public tool surface ------------------------------------------------
    #
    # Each public method is the *whole* error contract: typed dispatcher errors
    # become concise structured payloads here (§29), so calling these directly
    # exercises exactly what an MCP client would receive.

    async def dispatch_claude_task(
        self, request: dict[str, Any] | TaskRequest
    ) -> dict[str, Any]:
        """§7.1. Dispatch a worker. Returns the result payload or an error payload."""
        return await _guarded(lambda: self._dispatch(request))

    async def resume_claude_task(
        self, task_id: str, instruction: str, timeout_seconds: int | None = None
    ) -> dict[str, Any]:
        """§7.2. Continue a task's stored session."""
        return await _guarded(lambda: self._resume(task_id, instruction, timeout_seconds))

    async def review_task_with_fable(
        self, task_id: str, focus: list[str] | None = None
    ) -> dict[str, Any]:
        """§7.3. Independent read-only review. Advisory."""
        return await _guarded(lambda: self._review(task_id, focus))

    async def get_task(self, task_id: str) -> dict[str, Any]:
        """§7.4. Read-only aggregation of authoritative state."""
        return await _guarded(lambda: self._get_task(task_id))

    # -- tool 1: dispatch ---------------------------------------------------

    async def _dispatch(self, request: dict[str, Any] | TaskRequest) -> dict[str, Any]:
        """§7.1. Create a new implementation worker and record what it did."""
        assert_no_recursion(self.config)

        task_request = self._validate_request(request)
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
            base_commit = await asyncio.to_thread(
                resolve_base_commit, canonical_root, task_request.repository.base_ref
            )
            envelope = TaskEnvelope.from_request(
                task_request,
                canonical_root=str(canonical_root),
                base_commit=base_commit,
                task_id=new_task_id(),
                dispatch_depth=dispatch_depth,
            )
            task_id = envelope.task_id
            self.store.create(envelope)
            _event("task_created", task_id=task_id, repository=str(canonical_root))

            model, reason = explain_route(envelope, self.config)
            self.store.transition(
                task_id, TaskState.ROUTED, reason=f"route:{reason}", selected_model=model
            )

            session_id = new_session(envelope)
            record = self.store.transition(
                task_id, TaskState.RUNNING, reason="dispatch", session_id=session_id
            )

            run_index = record.run_count + 1
            run_id = new_run_id()
            prompt = build_worker_prompt(envelope)

            invocation = build_worker_invocation(
                envelope,
                self.config,
                model=model,
                session_id=session_id,
                prompt=prompt,
                # The worktree does not exist yet: the Claude CLI creates it
                # from --worktree (§12), so run 1 starts in the repository root
                # and the worktree path is resolved afterwards, from
                # `git worktree list --porcelain`, for evidence collection.
                cwd=canonical_root,
            )
            invocation = self._with_run_spools(invocation, task_id, run_index)

            # P1-5: the baseline is taken *before* the worker can touch
            # anything. Post-run "is the primary tree clean" cannot tell an
            # already-dirty tree from one the worker dirtied.
            primary_tree_before = await asyncio.to_thread(
                snapshot_primary_tree, canonical_root
            )
            self._write_primary_tree_snapshot(task_id, "before", primary_tree_before)

            started_at = utc_now()
            _event("worker_start", task_id=task_id, run_id=run_id, model=model, kind="dispatch")
            worker_run = await run_worker(invocation)
            finished_at = utc_now()

            worktree_path = await asyncio.to_thread(
                worktree_path_for, canonical_root, envelope.worktree_name
            )

            if worktree_path is not None:
                # Record it immediately: a later failure during evidence
                # collection must not leave the task unable to name the
                # worktree Sol has to inspect (§12 "preserve the worktree").
                record = self.store.load(task_id)
                record.worktree_path = str(worktree_path)
                self.store.save(record)

            if worktree_path is None:
                # Evidence first, refusal second (§20): the run is recorded so
                # Sol can see the stdout/stderr that explains the failure.
                self._write_run_streams(task_id, run_index, worker_run)
                # P1-5 still applies on this path: a worker that produced no
                # worktree may still have touched the primary tree. Best-effort
                # here — this branch is already landing an explicit safe state,
                # and a second git failure must not mask the original refusal.
                self._record_primary_tree_on_failure_path(
                    task_id, canonical_root, primary_tree_before
                )
                error = WorktreeCreationFailed(
                    "Claude did not create the task's isolated worktree.",
                    details={
                        "task_id": task_id,
                        "worktree_name": envelope.worktree_name,
                        "exit_code": worker_run.exit_code,
                        "stderr_tail": _tail_text(worker_run.stderr),
                    },
                    remediation=(
                        "Inspect the recorded stderr; the worker exited without "
                        "an isolated worktree, so no change can be attributed to it."
                    ),
                )
                self._record_bare_run(
                    envelope=envelope,
                    run_kind=RunKind.DISPATCH,
                    role=WorkerRole.IMPLEMENTER,
                    run_index=run_index,
                    run_id=run_id,
                    session_id=session_id,
                    model=model,
                    worktree_path=None,
                    worker_run=worker_run,
                    started_at=started_at,
                    finished_at=finished_at,
                )
                self.store.transition(
                    task_id,
                    TaskState.FAILED,
                    reason="worktree_missing",
                    last_error=error.to_payload(),
                )
                raise error

            return await self._finalise_worker_run(
                envelope=envelope,
                run_kind=RunKind.DISPATCH,
                run_index=run_index,
                run_id=run_id,
                session_id=session_id,
                model=model,
                worktree_path=worktree_path,
                worker_run=worker_run,
                started_at=started_at,
                finished_at=finished_at,
                repository_root=canonical_root,
                primary_tree_before=primary_tree_before,
            )
        except DispatcherError as exc:
            self._record_failure(task_id, exc)
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
    ) -> dict[str, Any]:
        """§7.2. Continue the *stored* session — never a caller-supplied one."""
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

        canonical_root = validate_repository_root(envelope.repository.root, self.config)

        lock = RepositoryLock(canonical_root, self.config.locks_path)
        lock.acquire()
        try:
            self.store.transition(
                task_id, TaskState.RESUME_REQUESTED, reason="resume_requested"
            )
            record = self.store.transition(
                task_id,
                TaskState.RUNNING,
                reason="resume",
                resume_count=plan.next_resume_count,
            )

            run_index = record.run_count + 1
            run_id = new_run_id()

            invocation = build_worker_invocation(
                envelope,
                self.config,
                model=plan.model,
                session_id=plan.session_id,
                resume_session_id=plan.session_id,
                prompt=build_resume_prompt(envelope, plan.instruction),
                # Same worktree, no new one (§18). build_worker_invocation
                # refuses to emit --worktree alongside --resume.
                cwd=Path(plan.worktree_path),
                timeout_seconds=plan.timeout_seconds,
            )
            invocation = self._with_run_spools(invocation, task_id, run_index)

            # P1-5: same baseline discipline as dispatch. A resume runs inside
            # the worktree, so any primary-tree change is by definition
            # interference.
            primary_tree_before = await asyncio.to_thread(
                snapshot_primary_tree, canonical_root
            )
            self._write_primary_tree_snapshot(task_id, "before", primary_tree_before)

            started_at = utc_now()
            _event(
                "worker_start",
                task_id=task_id,
                run_id=run_id,
                model=plan.model,
                kind="resume",
                resume_count=plan.next_resume_count,
            )
            worker_run = await run_worker(invocation)
            finished_at = utc_now()

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
                primary_tree_before=primary_tree_before,
            )
        except DispatcherError as exc:
            self._record_failure(task_id, exc)
            raise
        finally:
            lock.release()

    # -- tool 3: fable review -----------------------------------------------

    async def _review(
        self, task_id: str, focus: list[str] | None = None
    ) -> dict[str, Any]:
        """§7.3. Independent, read-only review in a fresh session. Advisory."""
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

        canonical_root = validate_repository_root(envelope.repository.root, self.config)

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

            latest = self.store.latest_run(task_id)
            diff_text = self._prompt_diff_text(task_id)
            changed_paths = (
                list(latest.dispatcher_observations.changed_paths)
                if latest is not None and latest.dispatcher_observations is not None
                else []
            )
            validation_results = list(latest.validation_results) if latest is not None else []
            worker_claims = latest.worker_claims if latest is not None else None

            session_id = new_session_id()  # fresh session, never the worker's (§19)
            run_index = record.run_count + 1
            run_id = new_run_id()

            invocation = build_fable_invocation(
                envelope,
                self.config,
                session_id=session_id,
                prompt=build_fable_prompt(
                    envelope,
                    diff_text=diff_text,
                    changed_paths=changed_paths,
                    worker_claims=worker_claims,
                    validation_results=validation_results,
                    focus=list(focus or []),
                    validation_added_paths=self._validation_added_paths(task_id),
                ),
                cwd=worktree,
            )
            invocation = self._with_run_spools(invocation, task_id, run_index)

            started_at = utc_now()
            _event(
                "review_start", task_id=task_id, run_id=run_id, model=self.config.models.fable
            )
            worker_run = await run_worker(invocation)
            finished_at = utc_now()

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
            )

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
    ) -> RunMetadata:
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
        primary_tree_before: PrimaryTreeSnapshot,
    ) -> dict[str, Any]:
        """Collect evidence, record the run, and land the task in a state.

        Shared by dispatch and resume so both go through *identical* evidence
        collection, scope enforcement and state accounting (§13, §16, §17).

        Evidence is collected in two phases (P1-7): phase A immediately after
        the worker exits, phase B after the dispatcher's own validation
        commands have run. The authoritative scope and policy decision uses the
        **final** state — that is what is actually on disk — while the record
        keeps the attribution so a dispatcher-generated file is never charged
        to the worker.
        """
        task_id = envelope.task_id

        self._write_run_streams(task_id, run_index, worker_run)

        # --- evidence A: the worktree as the worker left it (§16, P1-7) ---
        worker_evidence = await asyncio.to_thread(
            collect_diff_evidence, worktree_path, envelope.repository.base_commit
        )
        self._write_phase_evidence(task_id, "pre-validation", worker_evidence)

        # --- what the worker CLAIMED (§16) --------------------------------
        worker_result: WorkerResult | None = None
        worker_result_error: str | None = None
        if worker_run.timed_out:
            worker_result_error = (
                "worker timed out before emitting structured output; partial "
                "stdout preserved in the run directory"
            )
        elif worker_run.start_failed:
            worker_result_error = "worker process could not be started"
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
        if not worker_run.timed_out and not worker_run.start_failed:
            # env is deliberately not passed: ``run_validations`` treats
            # ``env=None`` as "build the sanitized environment" (P1-6).
            validation_results = await run_validations(envelope, worktree_path, self.config)
        atomic_write_json(
            self._run_dir(task_id, run_index) / "validation.json",
            [_dump(v) for v in validation_results],
        )

        # --- evidence B: after validation (P1-7) --------------------------
        # Validation commands mutate worktrees routinely — formatters, coverage
        # files, lockfiles, snapshot updates. Post-worker evidence is stale the
        # moment one of them runs, so the state that gets policed is re-measured
        # here. Skipped only when nothing ran, in which case B is A by
        # construction rather than by assumption.
        if validation_results:
            final_evidence = await asyncio.to_thread(
                collect_diff_evidence, worktree_path, envelope.repository.base_commit
            )
        else:
            final_evidence = worker_evidence
        attribution = attribute_changed_paths(worker_evidence, final_evidence)

        scope = check_scope(final_evidence.changed_paths, envelope.scope)

        # --- primary-tree non-interference (P1-5) -------------------------
        primary_tree_after = await asyncio.to_thread(
            snapshot_primary_tree, repository_root
        )
        primary_tree_divergence = compare_primary_tree(
            primary_tree_before, primary_tree_after
        )
        self._write_primary_tree_snapshot(task_id, "after", primary_tree_after)
        self._write_primary_tree_invariant(
            task_id, primary_tree_before, primary_tree_after, primary_tree_divergence
        )

        # Evidence is on disk before any state decision is taken (§13, §20).
        await self._write_evidence(
            task_id,
            worktree_path=worktree_path,
            base_commit=envelope.repository.base_commit,
            diff_evidence=final_evidence,
            scope=scope,
            attribution=attribution,
            primary_status=primary_tree_after.porcelain_status,
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
            # Literal measurement, not the invariant: this says the primary tree
            # has no uncommitted changes *now*. Non-interference
            # (post_state == pre_state) is a different question and is decided
            # by ``primary_tree_divergence`` below — an already-dirty tree is
            # not a violation.
            primary_worktree_clean=(primary_tree_after.porcelain_status.strip() == ""),
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
            worker_run=worker_run,
            worker_result=worker_result,
            worker_result_error=worker_result_error,
            primary_tree_divergence=primary_tree_divergence,
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
            },
            "evidence_attribution": attribution,
            "primary_tree": {
                "unchanged": primary_tree_divergence is None,
                "divergence": primary_tree_divergence,
            },
            "last_error": record.last_error,
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

    def _prompt_diff_text(self, task_id: str) -> str:
        """Bounded read of ``evidence/diff.patch`` for the review prompt.

        ``diff.patch`` is the *complete* patch now (Lane A R3), so it has no
        upper bound — reading it whole to build a prompt that clips at
        ``_MAX_PROMPT_DIFF_CHARS`` anyway would let a runaway worker decide how
        much memory the dispatcher allocates. The full patch stays on disk; the
        prompt gets a marked head.
        """
        path = self.store.task_dir(task_id) / "evidence" / "diff.patch"
        try:
            info = path.lstat()
        except OSError:
            return ""
        if stat.S_ISLNK(info.st_mode):
            # A symlinked evidence file is not evidence (Lane A's containment
            # rule, applied here because this read bypasses read_evidence).
            raise StateCorruption(
                "The task's diff evidence is a symlink, not a file.",
                details={"task_id": task_id, "name": "diff.patch"},
                remediation="Task state has been tampered with; do not review it.",
            )
        if info.st_size <= _MAX_PROMPT_PATCH_BYTES:
            return self.store.read_evidence(task_id, "diff.patch") or ""
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(_MAX_PROMPT_PATCH_BYTES)
        return head + (
            f"\n[dispatcher] patch clipped at {_MAX_PROMPT_PATCH_BYTES} bytes for "
            f"this prompt; the complete {info.st_size}-byte patch is "
            "evidence/diff.patch\n"
        )

    def _validation_added_paths(self, task_id: str) -> list[str]:
        """Paths the dispatcher's validation created, from stored evidence (P1-7)."""
        raw = self.store.read_evidence(task_id, "evidence-phases.json")
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        added = data.get("validation_added_paths")
        return [str(p) for p in added] if isinstance(added, list) else []

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
        worktree_path: Path,
        base_commit: str,
        diff_evidence: DiffEvidence,
        scope: ScopeCheck,
        attribution: dict[str, Any],
        primary_status: str,
    ) -> None:
        """Persist the §27 evidence artefacts. Never deleted on failure (§13).

        ``diff.patch`` is the **complete** patch, streamed straight from git to
        the file (Lane A R3), because Fable reviews that file: a silently
        shortened patch is a review of something other than the change. If the
        stream cannot be written the truncated in-memory text is kept *with* its
        explicit marker — never an unmarked short patch.
        """
        evidence_dir = self.store.task_dir(task_id) / "evidence"
        diff_patch_complete = True
        try:
            patch_bytes = await asyncio.to_thread(
                write_full_diff, worktree_path, base_commit, evidence_dir / "diff.patch"
            )
        except GitEvidenceCollectionFailed as exc:
            diff_patch_complete = False
            patch_bytes = 0
            logger.warning(
                "full diff could not be streamed for task %s: %s", task_id, exc.message
            )
            diff_text = diff_evidence.diff_text
            marker = (
                "\n[dispatcher] diff.patch is INCOMPLETE: the full patch could "
                "not be streamed from git, and the in-memory value "
                f"{'was truncated at the configured byte cap' if diff_evidence.truncated else 'is all that was retained'}"
                f" ({len(diff_evidence.diff_text)} of {diff_evidence.diff_total_bytes} bytes)\n"
            )
            self.store.write_evidence(task_id, "diff.patch", diff_text + marker)

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
                    # So a reader can always tell the on-disk patch from the
                    # in-memory one rather than trusting that "no marker" means
                    # "complete" (Lane A R3).
                    "diff_bytes_retained": len(
                        diff_evidence.diff_text.encode("utf-8", errors="replace")
                    ),
                    "diff_total_bytes": diff_evidence.diff_total_bytes,
                    "diff_patch_bytes": patch_bytes,
                    "diff_patch_complete": diff_patch_complete,
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
        worker_run: WorkerRun,
        worker_result: WorkerResult | None,
        worker_result_error: str | None,
        primary_tree_divergence: dict[str, Any] | None = None,
    ) -> TaskRecord:
        """Decide the post-run state. Deterministic, in a fixed precedence.

        Policy enforcement is checked first: §13 says an unauthorised change is
        a policy violation whatever else happened, and the evidence is kept
        rather than deleted. That covers two independent measurements — a change
        outside the declared scope inside the worktree, and any change at all to
        the *primary* tree (P1-5). A timeout is next (§20), then an unusable
        worker report, then the process outcome, then the worker's own status.

        A primary-tree divergence never falls through to
        ``AWAITING_SOL_REVIEW``: the worker escaped its isolation, and that is a
        refusal whatever the worker claimed and whatever the exit code was.
        """
        # The worktree path is recorded the moment it is resolved, not here, so
        # it survives a failure between the run and this decision.
        updates: dict[str, Any] = {}

        if not scope.valid or primary_tree_divergence is not None:
            details: dict[str, Any] = {
                "task_id": task_id,
                "out_of_scope": list(scope.out_of_scope),
                "forbidden": list(scope.forbidden),
            }
            reasons: list[str] = []
            if not scope.valid:
                reasons.append("scope_violation")
            if primary_tree_divergence is not None:
                reasons.append("primary_tree_interference")
                details["primary_tree_divergence"] = primary_tree_divergence
            parts: list[str] = []
            if not scope.valid:
                parts.append("changed paths outside the task's declared scope")
            if primary_tree_divergence is not None:
                parts.append(
                    "changed the primary working tree, which it must never touch"
                )
            message = "Worker " + " and ".join(parts) + "."
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
            violations += [f"forbidden:{p}" for p in scope.forbidden]
            if primary_tree_divergence is not None:
                violations += _interference_markers(primary_tree_divergence)
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

        if worker_result is None:
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

    def _record_failure(self, task_id: str | None, exc: DispatcherError) -> None:
        """Best-effort: persist the error into task state before it is returned.

        §29: diagnostics live in state, the MCP response stays concise. A
        failure to record must never mask the original error.
        """
        if not task_id or not self.store.exists(task_id):
            return
        try:
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
                    reason=f"error:{exc.code}",
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
    """Config path precedence: explicit argument, env var, project default."""
    if config_path is not None:
        return Path(config_path)
    from_env = os.environ.get(CONFIG_ENV_VAR)
    if from_env:
        return Path(from_env)
    return Path(__file__).resolve().parents[2] / DEFAULT_CONFIG_PATH


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
    """Console-script entrypoint: build the server and run it over stdio."""
    try:
        server = build_server()
    except DispatcherError as exc:
        # Startup diagnostics go to stderr; stdout is the transport (§28).
        print(json.dumps(exc.to_payload()), file=sys.stderr)
        raise SystemExit(2) from exc
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":  # pragma: no cover - console entrypoint
    main()
