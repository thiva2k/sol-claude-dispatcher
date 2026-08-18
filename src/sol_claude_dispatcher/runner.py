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

from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["WorkerInvocation", "WorkerRun", "run_worker", "build_argv", "CLI_CAPABILITIES"]

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
    grace_seconds: float = 5.0


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


def build_argv(spec: WorkerInvocation) -> list[str]:
    """Assemble the Claude argv. Pure and deterministic, so tests can assert it."""
    raise NotImplementedError("Wave 3: implement per docs/INTERFACES.md §runner")


async def run_worker(spec: WorkerInvocation) -> WorkerRun:
    """Execute Claude with a process-group timeout. Never raises on non-zero exit."""
    raise NotImplementedError("Wave 3: implement per docs/INTERFACES.md §runner")
