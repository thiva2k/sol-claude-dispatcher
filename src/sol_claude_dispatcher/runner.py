"""Async Claude subprocess execution (brief §11, §20). — Wave 3.

Hard requirements:

* ``asyncio.create_subprocess_exec`` with an argv **list**. Never ``shell=True``,
  never a single interpolated command string.
* ``start_new_session=True`` so the child gets its own process group.
* On timeout: SIGTERM the group, short grace period, then SIGKILL. Record which
  signal was needed.
* Evidence survives a timeout. Partial stdout, stderr, the session id, and the
  worktree must all still be recorded (§20).
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
    ConfigurationError,
    InternalDispatcherError,
)
from .models import TaskEnvelope
from .security import worker_environment

__all__ = [
    "WorkerInvocation",
    "WorkerRun",
    "run_worker",
    "build_argv",
    "build_worker_invocation",
    "build_fable_invocation",
    "build_worker_argv",
    "build_fable_argv",
    "CLI_CAPABILITIES",
    "SUBAGENT_TOOL_NAMES",
    "ALWAYS_DISALLOWED_TOOLS",
    "FORBIDDEN_FLAGS",
    "MUTATING_TOOL_NAMES",
    "DEFAULT_GRACE_SECONDS",
    "MAX_CAPTURED_BYTES",
]

#: Feature flags for the installed Claude CLI. Keyed by flag name; values are
#: set from ``docs/DISCOVERY.md`` findings and may become runtime-probed later.
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

#: Deny patterns the runner appends unconditionally, whatever the config says.
#: Config is operator-editable; these are not. ``mcp__*`` strips every MCP tool
#: including this dispatcher's own (§22 layer 1); the Agent/Task entries close
#: the subagent path (§22 layer 2); the ``claude``/``codex`` bash patterns close
#: the child-orchestrator path (§22 layer 3).
ALWAYS_DISALLOWED_TOOLS: tuple[str, ...] = (
    "mcp__*",
    "Agent",
    "Task",
    "Bash(claude:*)",
    "Bash(codex:*)",
)

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

#: Retained stream cap. The *full* streams are written to the run directory by
#: the caller; this only bounds what is carried around in memory (§12 of
#: INTERFACES: every unbounded field gets a documented cap).
MAX_CAPTURED_BYTES: int = 1_000_000


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
    #: Recorded policy only. Never emitted while
    #: ``CLI_CAPABILITIES["max_turns"]`` is False (the flag does not exist on
    #: Claude Code 2.1.234). Kept here so the gate has something to gate.
    max_turns: int | None = None


@dataclass
class WorkerRun:
    """Raw process outcome. No interpretation, no parsing."""

    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    killed_with_sigkill: bool = False
    start_failed: bool = False


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


async def _drain(stream: asyncio.StreamReader | None, cap: int) -> bytes:
    """Read a pipe to EOF, retaining at most *cap* bytes.

    Draining continues past the cap so the child never blocks on a full pipe;
    only what we *keep* is bounded.
    """
    if stream is None:
        return b""
    chunks: list[bytes] = []
    kept = 0
    while True:
        try:
            chunk = await stream.read(65536)
        except (asyncio.LimitOverrunError, ValueError):  # pragma: no cover - defensive
            continue
        if not chunk:
            break
        if kept < cap:
            room = cap - kept
            chunks.append(chunk[:room])
            kept += min(room, len(chunk))
    return b"".join(chunks)


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
        raise ClaudeBinaryNotFound(
            "The configured Claude binary was not found.",
            details={"binary": spec.binary, "cwd": str(spec.cwd)},
            remediation="Set claude.binary in the dispatcher config to an existing executable.",
        ) from exc
    except PermissionError as exc:
        raise ClaudeBinaryNotFound(
            "The configured Claude binary is not executable.",
            details={"binary": spec.binary, "cwd": str(spec.cwd)},
            remediation="chmod +x the binary or point claude.binary elsewhere.",
        ) from exc
    except OSError as exc:
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
    # already written is still recoverable (§20).
    stdout_task = asyncio.ensure_future(_drain(proc.stdout, MAX_CAPTURED_BYTES))
    stderr_task = asyncio.ensure_future(_drain(proc.stderr, MAX_CAPTURED_BYTES))

    timed_out = False
    killed_with_sigkill = False

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
    # stray grandchild holding the pipe open cannot wedge the dispatcher.
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            asyncio.gather(stdout_task, stderr_task), timeout=10.0
        )
    except (asyncio.TimeoutError, TimeoutError):  # pragma: no cover - defensive
        stdout_task.cancel()
        stderr_task.cancel()
        stdout_bytes, stderr_bytes = b"", b""

    duration_ms = int((time.monotonic() - started) * 1000)
    return WorkerRun(
        argv=argv,
        exit_code=proc.returncode,
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        duration_ms=duration_ms,
        timed_out=timed_out,
        killed_with_sigkill=killed_with_sigkill,
    )
