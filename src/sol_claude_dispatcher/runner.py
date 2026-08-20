"""Async Claude subprocess execution (brief §11, §20). — Wave 3.

Hard requirements:

* ``asyncio.create_subprocess_exec`` with an argv **list**. Never ``shell=True``,
  never a single interpolated command string.
* ``start_new_session=True`` so the child gets its own process group.
* On timeout: SIGTERM the group, short grace period, then SIGKILL. Record which
  signal was needed.
* Evidence survives a timeout. Partial stdout, stderr, the session id, and the
  worktree must all still be recorded (§20).
* Evidence survives *volume*, too (P1-8). Retained buffers are bounded, but the
  bound is never allowed to silently swallow the structured result: the complete
  stream is spooled to disk when the caller supplies a path, truncation is
  reported as a fact on :class:`WorkerRun`, and the trailing structured JSON
  document is recovered explicitly (:attr:`WorkerRun.stdout_for_parsing`).
* Never forward dispatcher secrets into the child (§22 layer 7); build the
  environment with ``security.worker_environment``.

Contract (authoritative, see ``docs/INTERFACES.md``)::

    async def run_worker(spec: WorkerInvocation) -> WorkerRun

Verified CLI reality (see ``docs/DISCOVERY.md``) — Claude Code 2.1.234:

* ``--max-turns`` **does not exist**. Do not emit it. ``max_turns`` stays in the
  envelope as recorded policy; the timeout and ``--max-budget-usd`` provide the
  runaway bounds. Gate the flag behind :data:`CLI_CAPABILITIES` so it can be
  re-enabled without touching call sites.
* ``--append-system-prompt`` takes an inline **string**, not a path. The runner
  reads the policy file and passes its contents.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .config import Config
from .errors import (
    ClaudeBinaryNotFound,
    ClaudeExecutionFailed,
    ConfigurationError,
    InternalDispatcherError,
)
from .models import TaskEnvelope
from .security import redact, worker_environment

__all__ = [
    "WorkerInvocation",
    "WorkerRun",
    "StreamCapture",
    "run_worker",
    "cli_failure",
    "STDERR_TAIL_CHARS",
    "build_argv",
    "build_worker_invocation",
    "build_fable_invocation",
    "build_worker_argv",
    "build_fable_argv",
    "CLI_CAPABILITIES",
    "SUBAGENT_TOOL_NAMES",
    "ALWAYS_DISALLOWED_TOOLS",
    "CORE_DENIED_GIT_OPERATIONS",
    "FORBIDDEN_FLAGS",
    "MUTATING_TOOL_NAMES",
    "DEFAULT_GRACE_SECONDS",
    "MAX_CAPTURED_BYTES",
    "MAX_RECOVERED_BYTES",
]

#: Feature flags for the installed Claude CLI. Keyed by flag name; values are
#: set from ``docs/DISCOVERY.md`` findings and may become runtime-probed later.
#:
#: Drift risk (NOTE-L2-A), recorded rather than engineered around: this dict is
#: pinned to one verified CLI release while the CLI can auto-update unattended.
#: An update that *adds* ``--max-turns`` would leave the dispatcher silently not
#: enforcing a turn cap; one that *removes* a flag emitted unconditionally would
#: make every dispatch fail. ``scripts/doctor.sh`` now prints the actual
#: installed ``--version`` and fails closed when the probe does not, so the drift
#: is visible at the gate instead of at dispatch time. Runtime capability
#: probing is deliberately NOT built here — that is a design change, not a fix.
CLI_CAPABILITIES: dict[str, bool] = {
    "max_turns": False,          # absent in 2.1.234
    "append_system_prompt_file": False,  # inline string only
    "json_schema": True,
    "worktree": True,
    "session_id": True,
    "resume": True,
    "strict_mcp_config": True,
    "max_budget_usd": True,
}

#: Built-in tools that would let a worker spawn a nested agent (§22 layer 2).
#: They are refused in the *granted* tool list and denied explicitly on top.
SUBAGENT_TOOL_NAMES: tuple[str, ...] = ("Agent", "Task", "Subagent")

#: Tools that can mutate the tree. Fable must never receive one (§7.3).
MUTATING_TOOL_NAMES: tuple[str, ...] = (
    "Bash",
    "Edit",
    "MultiEdit",
    "Write",
    "NotebookEdit",
    "WebFetch",
    "WebSearch",
)

#: Git operations V1 prohibits outright (P1-9). These used to live only in
#: ``config.claude.disallowed_tools``, i.e. an operator could delete them by
#: editing a TOML file. They are code-level invariants now: config may *add*
#: deny rules, never remove one of these.
#:
#: Honesty (§23, ``docs/SECURITY.md``): a deny pattern is a **prefix match on
#: the Bash command text** performed by the Claude CLI's own permission engine.
#: It is HARD in the sense that no configuration can remove it, and it is not
#: an OS boundary: it does not inspect the resolved executable, so a command
#: that reaches git without the literal ``git push``-style prefix (absolute
#: path, wrapper script, alias) is not covered by it. The post-run evidence and
#: primary-tree checks — not this list — are what actually detect a violation.
CORE_DENIED_GIT_OPERATIONS: tuple[str, ...] = (
    "Bash(git push:*)",
    "Bash(git merge:*)",
    "Bash(git rebase:*)",
    "Bash(git commit:*)",
    "Bash(git reset:*)",
    "Bash(git clean:*)",
    "Bash(git worktree:*)",
)

#: Deny patterns the runner appends unconditionally, whatever the config says.
#: Config is operator-editable; these are not. ``mcp__*`` strips every MCP tool
#: including this dispatcher's own (§22 layer 1); the Agent/Task entries close
#: the subagent path (§22 layer 2); the ``claude``/``codex`` bash patterns close
#: the child-orchestrator path (§22 layer 3); the git entries are the
#: V1-prohibited repository mutations (P1-9).
ALWAYS_DISALLOWED_TOOLS: tuple[str, ...] = (
    "mcp__*",
    "Agent",
    "Task",
    "Bash(claude:*)",
    "Bash(codex:*)",
) + CORE_DENIED_GIT_OPERATIONS

#: Flags this dispatcher will never emit, at any call site, for any reason.
FORBIDDEN_FLAGS: frozenset[str] = frozenset(
    {
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions",
    }
)

#: Default SIGTERM→SIGKILL grace. There is no config key for this (see the
#: report note); callers may override per invocation, and the tests do.
DEFAULT_GRACE_SECONDS: float = 5.0

#: Retained stream cap, per end. Up to this many bytes of the *head* and this
#: many bytes of the *tail* of each stream are kept in memory, so a stream up to
#: ``2 * MAX_CAPTURED_BYTES`` is retained in full and anything larger keeps both
#: ends with an explicit in-band marker naming the omitted byte count. Nothing
#: is ever discarded silently (§12 of INTERFACES: every unbounded field gets a
#: documented cap; P1-8: a cap must not destroy the structured result).
MAX_CAPTURED_BYTES: int = 1_000_000

#: Ceiling on how much of a spooled stream is re-read to recover the trailing
#: structured JSON document after truncation. Bounded so a runaway worker
#: cannot make the dispatcher read an arbitrarily large file into memory.
MAX_RECOVERED_BYTES: int = 32 * 1024 * 1024

#: How many trailing lines the structured-result recovery scan will consider.
_MAX_RECOVERY_LINES: int = 4096

#: Characters without which ``security.redact`` cannot match anything. Used to
#: skip redaction of bulk output (see ``StreamCapture._render_spool``).
_REDACTION_TRIGGERS: tuple[bytes, ...] = (b"=", b'"')


@dataclass(frozen=True)
class WorkerInvocation:
    """Everything needed to launch one Claude process. Fully resolved."""

    binary: str
    model: str
    session_id: str
    cwd: Path
    prompt: str
    timeout_seconds: int
    role: str                       # "implementer" | "reviewer"
    worktree_name: str | None = None       # None on resume and on review
    resume_session_id: str | None = None   # set only on resume
    json_schema: str | None = None         # minified schema string
    append_system_prompt: str | None = None
    tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    mcp_config_path: Path | None = None
    permission_mode: str = "auto"
    max_budget_usd: float | None = None
    env: dict[str, str] = field(default_factory=dict)
    grace_seconds: float = DEFAULT_GRACE_SECONDS
    #: When set, every byte the child writes to stdout is streamed to this file
    #: (created 0600) so the complete stream survives the in-memory cap (P1-8).
    stdout_spool_path: Path | None = None
    #: Same for stderr, except the spool is redacted line by line on the way to
    #: disk (§28) — stderr is diagnostics and may quote a secret-shaped value.
    stderr_spool_path: Path | None = None
    #: Recorded policy only. Never emitted while
    #: ``CLI_CAPABILITIES["max_turns"]`` is False (the flag does not exist on
    #: Claude Code 2.1.234). Kept here so the gate has something to gate.
    max_turns: int | None = None


@dataclass
class WorkerRun:
    """Raw process outcome. No interpretation, no parsing.

    ``stdout``/``stderr`` are the *retained* streams. When the corresponding
    ``*_truncated`` flag is set they carry an explicit in-band marker naming the
    omitted byte count, and ``*_total_bytes`` records what the child actually
    wrote — a caller must never treat them as the complete stream without
    checking (P1-8: "never silently claim full evidence").
    """

    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    killed_with_sigkill: bool = False
    start_failed: bool = False
    #: Bytes the child actually wrote, regardless of what was retained.
    stdout_total_bytes: int = 0
    stderr_total_bytes: int = 0
    #: True when the retained stream is a head+tail excerpt, not the whole thing.
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    #: Where the complete stream was spooled, when the caller asked for one.
    stdout_spool_path: str | None = None
    stderr_spool_path: str | None = None
    #: The trailing structured JSON document, recovered from the complete
    #: spooled stream (or the retained tail) after truncation. ``None`` when
    #: nothing was truncated — ``stdout`` is then already the whole thing.
    structured_stdout: str | None = None

    @property
    def stdout_for_parsing(self) -> str:
        """The text a structured-result parser should be handed.

        Identical to :attr:`stdout` for every run that fit inside the retention
        cap; the recovered structured document when it did not. Call sites that
        parse worker output must use this rather than :attr:`stdout`, otherwise
        a very large run loses its result to the truncation marker.
        """
        return self.structured_stdout if self.structured_stdout is not None else self.stdout


#: How much of the captured stderr is quoted back in a CLI-failure diagnostic.
#: Bounded (and taken from the tail, where the fatal message is) so an error
#: payload crossing the MCP boundary stays short — §29.
STDERR_TAIL_CHARS: int = 1200


def cli_failure(run: WorkerRun, *, binary: str, role: str) -> ClaudeExecutionFailed | None:
    """Diagnose a CLI that ran but produced nothing to parse (DEFECT-L2-02).

    ``ClaudeBinaryNotFound`` only covers an *absent* or *non-executable* binary
    (FileNotFoundError / PermissionError at spawn time). A binary that is present
    and executable but broken — a partially installed CLI whose launcher exits
    non-zero writing "claude native binary not installed" to stderr — starts
    fine, exits non-zero, and writes nothing to stdout. Handing that empty stdout
    to :func:`results.extract_structured_payload` produced
    ``ClaudeStructuredOutputInvalid("Claude's stdout was not valid JSON.")``,
    which blames the model for an environment fault and buries the real cause one
    layer away in stderr.

    So: before parsing, a non-zero exit with empty stdout is reported as what it
    is, with the stderr tail quoted. Returns ``None`` for every other outcome —
    a run that produced output is still parsed exactly as before, and a
    timed-out or never-started run already has its own reporting path. Redacted
    on the way out (§28): stderr is diagnostics and may quote a secret-shaped
    value.
    """
    if run.start_failed or run.timed_out:
        return None
    if run.exit_code is None or run.exit_code == 0:
        return None
    if run.stdout_for_parsing.strip():
        return None

    tail = redact(run.stderr).strip()[-STDERR_TAIL_CHARS:]
    return ClaudeExecutionFailed(
        "The Claude CLI exited non-zero and wrote nothing to stdout: the CLI or "
        "its environment failed, so there is no model output to parse.",
        details={
            "binary": binary,
            "role": role,
            "exit_code": run.exit_code,
            "stderr_tail": tail or "<empty>",
        },
        remediation=(
            "Run ./scripts/doctor.sh (or the binary's own --version) — a broken, "
            "partially installed, or mis-pathed CLI reports the cause on stderr."
        ),
    )


# ---------------------------------------------------------------------------
# argv construction
# ---------------------------------------------------------------------------


def build_argv(spec: WorkerInvocation) -> list[str]:
    """Assemble the Claude argv. Pure and deterministic, so tests can assert it.

    Order is fixed by ``docs/INTERFACES.md`` §7 and must not drift: the prompt
    is the single trailing positional, and the variadic tool flags are always
    followed by a further flag so they cannot swallow it.
    """
    _assert_invocation_sane(spec)

    argv: list[str] = [
        spec.binary,
        "-p",
        "--model",
        spec.model,
        "--output-format",
        "json",
        "--permission-mode",
        spec.permission_mode,
        "--strict-mcp-config",
    ]

    if spec.mcp_config_path is not None:
        argv += ["--mcp-config", str(spec.mcp_config_path)]

    if spec.disallowed_tools:
        argv += ["--disallowedTools", *spec.disallowed_tools]

    if spec.tools:
        argv += ["--tools", *spec.tools]

    if spec.json_schema:
        argv += ["--json-schema", spec.json_schema]

    if spec.append_system_prompt:
        # Inline text, not a path (DISCOVERY delta 2). The exact policy the
        # worker received is therefore visible in the recorded argv.
        argv += ["--append-system-prompt", spec.append_system_prompt]

    if spec.max_budget_usd is not None:
        argv += ["--max-budget-usd", _format_budget(spec.max_budget_usd)]

    # Capability-gated, currently OFF: Claude Code 2.1.234 has no --max-turns.
    if CLI_CAPABILITIES.get("max_turns") and spec.max_turns is not None:
        argv += ["--max-turns", str(spec.max_turns)]

    if spec.resume_session_id:
        argv += ["--resume", spec.resume_session_id]
    else:
        argv += ["--session-id", spec.session_id]

    if spec.worktree_name:
        argv += ["--worktree", spec.worktree_name]

    argv.append(spec.prompt)

    # Belt and braces: a refactor that reintroduces a banned flag dies here
    # rather than at a live repository.
    banned = FORBIDDEN_FLAGS.intersection(argv)
    if banned:
        raise InternalDispatcherError(
            "Refusing to emit a forbidden Claude flag.",
            details={"flags": sorted(banned)},
        )
    return argv


def _format_budget(amount: float) -> str:
    """Stable textual budget: no scientific notation, no trailing noise."""
    return f"{amount:.6f}".rstrip("0").rstrip(".") or "0"


def _assert_invocation_sane(spec: WorkerInvocation) -> None:
    """Fail closed on invocation shapes that would break a safety invariant."""
    if spec.permission_mode == "bypassPermissions":
        raise InternalDispatcherError(
            "permission_mode 'bypassPermissions' is never permitted.",
            details={"permission_mode": spec.permission_mode},
        )
    if spec.resume_session_id and spec.worktree_name:
        raise InternalDispatcherError(
            "A resume must reuse the existing worktree, not create another (§18).",
            details={"worktree_name": spec.worktree_name},
        )
    if spec.role == "reviewer":
        if spec.worktree_name:
            raise InternalDispatcherError(
                "Fable review is read-only and never creates a worktree (§7.3).",
                details={"worktree_name": spec.worktree_name},
            )
        if spec.resume_session_id:
            raise InternalDispatcherError(
                "Fable never resumes the worker's conversation (§19).",
                details={"resume_session_id": spec.resume_session_id},
            )
        mutating = [t for t in spec.tools if t in MUTATING_TOOL_NAMES]
        if mutating:
            raise InternalDispatcherError(
                "Reviewer tool set must be read-only.",
                details={"tools": mutating},
            )
    if not spec.resume_session_id and not spec.session_id:
        raise InternalDispatcherError(
            "A new session requires a session id.", details={"role": spec.role}
        )
    granted_subagents = [t for t in spec.tools if t in SUBAGENT_TOOL_NAMES]
    if granted_subagents:
        raise InternalDispatcherError(
            "Subagent tools are never granted to a dispatched worker (§22 layer 2).",
            details={"tools": granted_subagents},
        )
    if not spec.prompt.strip():
        raise InternalDispatcherError(
            "Refusing to launch a worker with an empty prompt.",
            details={"role": spec.role},
        )
    # P1-9: the core deny set is an invariant, not configuration. The builders
    # append it unconditionally; this catches a hand-assembled invocation (or a
    # future refactor) that drops one of the prohibited operations.
    missing_denies = [t for t in ALWAYS_DISALLOWED_TOOLS if t not in spec.disallowed_tools]
    if missing_denies:
        raise InternalDispatcherError(
            "Refusing to launch: the non-configurable disallowed-tool set is "
            "incomplete. Operator config may add deny rules, never remove one.",
            details={"missing": missing_denies},
        )


# ---------------------------------------------------------------------------
# invocation builders (config + envelope -> WorkerInvocation)
# ---------------------------------------------------------------------------


def _read_text_file(path: Path, *, what: str) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigurationError(
            f"{what} file not found.",
            details={"path": str(path)},
            remediation=f"Create {path} or point the config at an existing file.",
        ) from exc
    except OSError as exc:
        raise ConfigurationError(
            f"{what} file is unreadable.",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    except UnicodeDecodeError as exc:
        raise ConfigurationError(
            f"{what} file is not valid UTF-8.", details={"path": str(path)}
        ) from exc
    if not text.strip():
        raise ConfigurationError(
            f"{what} file is empty.", details={"path": str(path)}
        )
    return text


def _minified_schema(path: Path, *, what: str) -> str:
    raw = _read_text_file(path, what=what)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"{what} file is not valid JSON.",
            details={"path": str(path), "error": str(exc)},
        ) from exc
    return json.dumps(parsed, separators=(",", ":"))


def _deduped(*groups: object) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for item in group:  # type: ignore[attr-defined]
            if item not in seen:
                seen.add(item)
                out.append(item)
    return out


def build_worker_invocation(
    envelope: TaskEnvelope,
    config: Config,
    *,
    model: str,
    session_id: str,
    prompt: str,
    cwd: Path,
    resume_session_id: str | None = None,
    include_worktree: bool | None = None,
    timeout_seconds: int | None = None,
    base_env: Mapping[str, str] | None = None,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
) -> WorkerInvocation:
    """Resolve an implementation-worker invocation from config + envelope.

    ``include_worktree`` defaults to "yes on a fresh session, never on resume"
    (§18). The environment is always built through
    :func:`security.worker_environment`, so ``SOL_WORKER=1`` and the depth
    marker are present and dispatcher secrets are stripped (§22 layers 4, 7).
    """
    if include_worktree is None:
        include_worktree = resume_session_id is None

    timeout = timeout_seconds if timeout_seconds is not None else envelope.execution.timeout_seconds
    timeout = config.clamp_timeout(timeout)

    return WorkerInvocation(
        binary=config.claude.binary,
        model=model,
        session_id=session_id,
        cwd=cwd,
        prompt=prompt,
        timeout_seconds=timeout,
        role="implementer",
        worktree_name=envelope.worktree_name if include_worktree else None,
        resume_session_id=resume_session_id,
        json_schema=_minified_schema(config.worker_schema_file, what="Worker result schema"),
        append_system_prompt=_read_text_file(
            config.worker_policy_file, what="Worker policy"
        ),
        tools=list(config.claude.worker_tools),
        disallowed_tools=_deduped(config.claude.disallowed_tools, ALWAYS_DISALLOWED_TOOLS),
        mcp_config_path=config.empty_mcp_file,
        permission_mode=config.claude.permission_mode,
        max_budget_usd=envelope.execution.max_budget_usd,
        env=worker_environment(
            base_env if base_env is not None else os.environ,
            task_id=envelope.task_id,
            dispatch_depth=envelope.lineage.dispatch_depth,
        ),
        grace_seconds=grace_seconds,
        max_turns=envelope.execution.max_turns,
    )


def build_fable_invocation(
    envelope: TaskEnvelope,
    config: Config,
    *,
    session_id: str,
    prompt: str,
    cwd: Path,
    timeout_seconds: int | None = None,
    base_env: Mapping[str, str] | None = None,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
) -> WorkerInvocation:
    """Resolve the read-only Fable review invocation (§7.3, §19).

    Always a fresh session: Fable never resumes the worker's conversation, and
    never receives a worktree — it reads the one the worker already produced.
    """
    timeout = timeout_seconds if timeout_seconds is not None else envelope.execution.timeout_seconds
    timeout = config.clamp_timeout(timeout)

    tools = list(config.claude.reviewer_tools)
    mutating = [t for t in tools if t in MUTATING_TOOL_NAMES]
    if mutating:
        raise ConfigurationError(
            "claude.reviewer_tools must be read-only; Fable may not modify files (§7.3).",
            details={"offending_tools": mutating},
            remediation="Restrict reviewer_tools to Read/Glob/Grep.",
        )

    return WorkerInvocation(
        binary=config.claude.binary,
        model=config.models.fable,
        session_id=session_id,
        cwd=cwd,
        prompt=prompt,
        timeout_seconds=timeout,
        role="reviewer",
        worktree_name=None,
        resume_session_id=None,
        json_schema=_minified_schema(config.fable_schema_file, what="Fable review schema"),
        append_system_prompt=_read_text_file(
            config.fable_policy_file, what="Fable reviewer policy"
        ),
        tools=tools,
        disallowed_tools=_deduped(
            config.claude.disallowed_tools,
            ALWAYS_DISALLOWED_TOOLS,
            MUTATING_TOOL_NAMES,
        ),
        mcp_config_path=config.empty_mcp_file,
        permission_mode=config.claude.permission_mode,
        # Reuses the envelope's budget verbatim — deliberately: the reviewer is
        # a separate CLI invocation, so the cap applies per run, not shared.
        # Calibration note, measured live during commissioning (LANE2-REPORT
        # §"Budget calibration"): a *one-word* Fable turn cost $0.39 against
        # $0.11 for Sonnet, because ~18.8k cache-creation input tokens are spent
        # on the system prompt alone; a real review adds the reviewer policy,
        # the review schema, and file reads on top. A caller that sizes
        # ``execution.max_budget_usd`` for a cheap worker turn (~$0.50 or less)
        # will therefore have the review killed mid-flight, and it will read as
        # a Fable failure rather than a budget failure. Default is ``None`` — no
        # ``--max-budget-usd`` is emitted and nothing is capped — so this is a
        # caller-side hazard, not a dispatcher default. Do not "fix" it by
        # inventing a second budget field.
        max_budget_usd=envelope.execution.max_budget_usd,
        env=worker_environment(
            base_env if base_env is not None else os.environ,
            task_id=envelope.task_id,
            dispatch_depth=envelope.lineage.dispatch_depth,
        ),
        grace_seconds=grace_seconds,
        max_turns=None,
    )


def build_worker_argv(envelope: TaskEnvelope, config: Config, **kwargs: object) -> list[str]:
    """Convenience: :func:`build_worker_invocation` then :func:`build_argv`."""
    return build_argv(build_worker_invocation(envelope, config, **kwargs))  # type: ignore[arg-type]


def build_fable_argv(envelope: TaskEnvelope, config: Config, **kwargs: object) -> list[str]:
    """Convenience: :func:`build_fable_invocation` then :func:`build_argv`."""
    return build_argv(build_fable_invocation(envelope, config, **kwargs))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# process execution
# ---------------------------------------------------------------------------


class StreamCapture:
    """Bounded in-memory capture of one pipe, plus an optional complete spool.

    Keeps the first ``cap`` bytes and the last ``cap`` bytes. A stream of at
    most ``2 * cap`` bytes is therefore reconstructed exactly; anything larger
    is rendered as ``head`` + an explicit marker naming the omitted byte count
    + ``tail``. The counters are always exact, so the caller can state what was
    dropped instead of implying nothing was.

    The capture object is owned by the caller, not by the pumping task, so a
    cancelled or timed-out drain still leaves every byte read so far in hand
    (§20: a timeout must not destroy evidence).
    """

    def __init__(
        self,
        cap: int,
        spool_path: Path | None = None,
        *,
        redact_spool: bool = False,
    ) -> None:
        self.cap = cap
        self.total = 0
        self.spool_path = spool_path
        self._head = bytearray()
        self._tail = bytearray()
        self._redact_spool = redact_spool
        self._pending = b""
        self._spool = None if spool_path is None else _open_spool(spool_path)

    def feed(self, chunk: bytes) -> None:
        self.total += len(chunk)
        if len(self._head) < self.cap:
            self._head += chunk[: self.cap - len(self._head)]
        self._tail += chunk
        if len(self._tail) > self.cap:
            del self._tail[: len(self._tail) - self.cap]
        self._spool_write(chunk)

    def close(self) -> None:
        if self._spool is None:
            return
        try:
            if self._pending:
                self._spool.write(self._render_spool(self._pending))
                self._pending = b""
            self._spool.flush()
        finally:
            self._spool.close()
            self._spool = None

    # -- rendering --------------------------------------------------------

    @property
    def truncated(self) -> bool:
        return self.total > 2 * self.cap

    def text(self) -> str:
        if self.total <= self.cap:
            return self._head.decode("utf-8", errors="replace")
        if self.total <= 2 * self.cap:
            # head and tail overlap and together cover the whole stream.
            overlap = 2 * self.cap - self.total
            return (bytes(self._head) + bytes(self._tail)[overlap:]).decode(
                "utf-8", errors="replace"
            )
        omitted = self.total - len(self._head) - len(self._tail)
        marker = (
            f"\n\n[dispatcher] {omitted} bytes omitted from the middle of this "
            f"stream ({self.total} bytes total, retention cap {self.cap} bytes "
            f"per end). This excerpt is NOT the complete stream.\n\n"
        )
        return (
            self._head.decode("utf-8", errors="replace")
            + marker
            + self._tail.decode("utf-8", errors="replace")
        )

    def tail_text(self) -> str:
        return self._tail.decode("utf-8", errors="replace")

    # -- spooling ---------------------------------------------------------

    def _render_spool(self, raw: bytes) -> bytes:
        """Redact a block on its way to disk, line by line.

        ``security.redact`` only ever rewrites ``KEY=value`` or ``"key": "value"``
        shaped text, so a line containing neither ``=`` nor ``"`` is passed
        through untouched. This is now purely an optimisation —
        ``security.redact`` is linear since its pattern was anchored — but it
        is kept because the drain runs on the event loop and skipping bulk
        non-secret output keeps that cheap.

        Known limitation, unchanged: redaction here is line-oriented, so a
        ``"key": "value"`` pair split across a newline is not masked in the
        spool. The in-memory path redacts whole blocks and is unaffected.
        """
        if not self._redact_spool:
            return raw
        if not any(trigger in raw for trigger in _REDACTION_TRIGGERS):
            return raw
        rendered: list[bytes] = []
        for line in raw.splitlines(keepends=True):
            if any(trigger in line for trigger in _REDACTION_TRIGGERS):
                rendered.append(redact(line.decode("utf-8", errors="replace")).encode("utf-8"))
            else:
                rendered.append(line)
        return b"".join(rendered)

    def _spool_write(self, chunk: bytes) -> None:
        if self._spool is None:
            return
        if not self._redact_spool:
            self._spool.write(chunk)
            return
        # Redaction is line-oriented, so only complete lines are written; the
        # remainder is held back until the next newline or close().
        buffered = self._pending + chunk
        cut = buffered.rfind(b"\n")
        if cut == -1:
            self._pending = buffered
            return
        self._spool.write(self._render_spool(buffered[: cut + 1]))
        self._pending = buffered[cut + 1 :]


def _open_spool(path: Path):
    """Open a run-stream spool file 0600, failing closed if that is impossible."""
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, "wb")
    except OSError as exc:
        raise InternalDispatcherError(
            "Could not open the worker output spool file.",
            details={"path": str(path), "error": str(exc)},
        ) from exc


async def _pump(stream: asyncio.StreamReader | None, capture: StreamCapture) -> None:
    """Read a pipe to EOF into *capture*.

    Reading continues past the retention cap so the child never blocks on a
    full pipe; only what is *kept in memory* is bounded.
    """
    if stream is None:
        return
    while True:
        try:
            chunk = await stream.read(65536)
        except (asyncio.LimitOverrunError, ValueError):  # pragma: no cover - defensive
            continue
        if not chunk:
            break
        capture.feed(chunk)


def _recover_structured_json(text: str) -> str | None:
    """Return the trailing JSON *object* in ``text``, or ``None``.

    Used only after truncation: the structured result Claude emits sits at the
    very end of stdout, so losing it to a retention cap would mean discarding
    the one part of the stream the dispatcher actually parses. This is a real
    ``json.loads``, never a regex scrape (§15) — a candidate that does not
    parse is not accepted.
    """
    stripped = text.strip()
    if not stripped:
        return None
    try:
        if isinstance(json.loads(stripped), dict):
            return stripped
    except (json.JSONDecodeError, RecursionError, ValueError):
        pass

    lines = stripped.splitlines()
    lowest = max(0, len(lines) - _MAX_RECOVERY_LINES)
    for start in range(len(lines) - 1, lowest - 1, -1):
        candidate = "\n".join(lines[start:]).strip()
        for attempt in _json_candidates(candidate):
            try:
                if isinstance(json.loads(attempt), dict):
                    return attempt
            except (json.JSONDecodeError, RecursionError, ValueError):
                continue
    return None


def _json_candidates(candidate: str):
    """The candidate itself, plus the same text from its first ``{``."""
    if candidate.startswith("{"):
        yield candidate
        return
    brace = candidate.find("{")
    if brace > 0:
        yield candidate[brace:]


def _recover_from_spool(path: Path | None) -> str | None:
    """Recover the trailing structured document from a complete spooled stream."""
    if path is None:
        return None
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > MAX_RECOVERED_BYTES:
                handle.seek(size - MAX_RECOVERED_BYTES)
            raw = handle.read(MAX_RECOVERED_BYTES)
    except OSError:  # pragma: no cover - defensive
        return None
    return _recover_structured_json(raw.decode("utf-8", errors="replace"))


def _killpg(proc: asyncio.subprocess.Process, sig: int) -> bool:
    """Signal the child's whole process group. True if the signal was sent."""
    try:
        os.killpg(os.getpgid(proc.pid), sig)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        # Already reaped, or the group vanished between check and signal.
        return False


async def run_worker(spec: WorkerInvocation) -> WorkerRun:
    """Execute Claude with a process-group timeout. Never raises on non-zero exit.

    Timeout discipline (§20): SIGTERM the group, wait ``grace_seconds``, then
    SIGKILL. Whatever the process already wrote is still collected and returned
    — a timeout must not destroy evidence.
    """
    argv = build_argv(spec)
    started = time.monotonic()

    # Opened before the process starts: an unusable spool path is a dispatcher
    # configuration fault, and it is better to refuse than to run a worker whose
    # evidence we already know we cannot keep.
    stdout_capture = StreamCapture(MAX_CAPTURED_BYTES, spec.stdout_spool_path)
    try:
        stderr_capture = StreamCapture(
            MAX_CAPTURED_BYTES, spec.stderr_spool_path, redact_spool=True
        )
    except InternalDispatcherError:
        stdout_capture.close()
        raise

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(spec.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=dict(spec.env),
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        stdout_capture.close()
        stderr_capture.close()
        raise ClaudeBinaryNotFound(
            "The configured Claude binary was not found.",
            details={"binary": spec.binary, "cwd": str(spec.cwd)},
            remediation="Set claude.binary in the dispatcher config to an existing executable.",
        ) from exc
    except PermissionError as exc:
        stdout_capture.close()
        stderr_capture.close()
        raise ClaudeBinaryNotFound(
            "The configured Claude binary is not executable.",
            details={"binary": spec.binary, "cwd": str(spec.cwd)},
            remediation="chmod +x the binary or point claude.binary elsewhere.",
        ) from exc
    except OSError as exc:
        stdout_capture.close()
        stderr_capture.close()
        return WorkerRun(
            argv=argv,
            exit_code=None,
            stdout="",
            stderr=f"failed to start worker process: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
            start_failed=True,
        )

    # Read the pipes in dedicated tasks rather than via communicate(): when the
    # deadline fires we cancel only the *wait*, so everything the worker had
    # already written is still recoverable (§20). The captures are owned here,
    # not by the tasks, so even a cancelled pump leaves its bytes behind.
    stdout_task = asyncio.ensure_future(_pump(proc.stdout, stdout_capture))
    stderr_task = asyncio.ensure_future(_pump(proc.stderr, stderr_capture))

    timed_out = False
    killed_with_sigkill = False

    try:
        try:
            await asyncio.wait_for(proc.wait(), timeout=spec.timeout_seconds)
        except (asyncio.TimeoutError, TimeoutError):
            timed_out = True
            _killpg(proc, signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=max(spec.grace_seconds, 0.0))
            except (asyncio.TimeoutError, TimeoutError):
                killed_with_sigkill = _killpg(proc, signal.SIGKILL)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10.0)
                except (asyncio.TimeoutError, TimeoutError):  # pragma: no cover - defensive
                    pass

        # EOF arrives once the (now dead) process closes its pipes. Bounded so a
        # stray grandchild holding the pipe open cannot wedge the dispatcher —
        # and if that bound fires, whatever was already read is still kept.
        try:
            await asyncio.wait_for(
                asyncio.gather(stdout_task, stderr_task), timeout=10.0
            )
        except (asyncio.TimeoutError, TimeoutError):  # pragma: no cover - defensive
            stdout_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
    finally:
        stdout_capture.close()
        stderr_capture.close()

    structured_stdout: str | None = None
    if stdout_capture.truncated:
        # The complete stream (when spooled) is the authoritative source for
        # recovery; the retained tail is the fallback.
        structured_stdout = _recover_from_spool(
            spec.stdout_spool_path
        ) or _recover_structured_json(stdout_capture.tail_text())

    duration_ms = int((time.monotonic() - started) * 1000)
    return WorkerRun(
        argv=argv,
        exit_code=proc.returncode,
        stdout=stdout_capture.text(),
        stderr=stderr_capture.text(),
        duration_ms=duration_ms,
        timed_out=timed_out,
        killed_with_sigkill=killed_with_sigkill,
        stdout_total_bytes=stdout_capture.total,
        stderr_total_bytes=stderr_capture.total,
        stdout_truncated=stdout_capture.truncated,
        stderr_truncated=stderr_capture.truncated,
        stdout_spool_path=(
            str(spec.stdout_spool_path) if spec.stdout_spool_path is not None else None
        ),
        stderr_spool_path=(
            str(spec.stderr_spool_path) if spec.stderr_spool_path is not None else None
        ),
        structured_stdout=structured_stdout,
    )
