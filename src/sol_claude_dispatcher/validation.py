"""Independent dispatcher validation (brief §9, §17). — Wave 3.

The dispatcher re-runs the *trusted* validation commands from the task envelope
after the worker exits, and stores the outcome next to — never merged with —
the worker's own test claims.

Two prohibitions, both absolute:

* Commands are structured argv executed via ``asyncio.create_subprocess_exec``.
  Never ``shell=True`` (§9).
* Commands that appear inside a Claude result are **never** executed, and the
  worker result may never redefine which commands run (§9, §17). The only
  source of truth is ``envelope.validation.commands``, which is why
  :func:`run_validation_command` refuses anything that is not already a
  :class:`~sol_claude_dispatcher.models.ValidationCommand` — that type can
  only be constructed by validating the trusted envelope, so a caller cannot
  smuggle a worker-supplied string through this function by construction.

Contract (authoritative, see ``docs/INTERFACES.md``)::

    async def run_validation_command(cmd: ValidationCommand, cwd: Path) -> ValidationResult
    async def run_validations(envelope: TaskEnvelope, cwd: Path, config: Config) -> list[ValidationResult]
"""

from __future__ import annotations

import asyncio
import os
import shlex
import signal
import time
from pathlib import Path
from typing import Any

from .config import Config
from .models import TaskEnvelope, ValidationCommand, ValidationResult, WorkerResult

__all__ = [
    "run_validation_command",
    "run_validations",
    "compare_claims_to_validation",
]

#: Last-N bytes of each stream kept as evidence (§9: "bounded, e.g. last 4KB").
#: We keep a little more headroom (8KB) since ValidationResult text fields
#: allow up to 20,000 characters.
_TAIL_BYTES = 8 * 1024

#: Grace period between SIGTERM and SIGKILL when a command overruns its
#: timeout — same discipline as ``runner.run_worker`` (§20).
_GRACE_SECONDS = 5.0


def _tail(text: str, limit: int = _TAIL_BYTES) -> str:
    return text[-limit:] if len(text) > limit else text


async def _drain(proc: "asyncio.subprocess.Process", timeout: float) -> tuple[bytes, bytes]:
    """Wait up to ``timeout`` for a signalled process to exit and be reaped."""
    try:
        return await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        return b"", b""


async def _terminate(proc: "asyncio.subprocess.Process") -> tuple[bytes, bytes, bool]:
    """SIGTERM, wait a grace period, SIGKILL if still alive (§9/§20 discipline).

    Returns whatever stdout/stderr could be drained and whether SIGKILL was
    needed. ``ProcessLookupError`` is swallowed at every step — the process
    may have exited between the timeout firing and the signal being sent.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass

    stdout_bytes, stderr_bytes = await _drain(proc, _GRACE_SECONDS)
    if proc.returncode is not None:
        return stdout_bytes, stderr_bytes, False

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass

    more_stdout, more_stderr = await _drain(proc, _GRACE_SECONDS)
    return stdout_bytes + more_stdout, stderr_bytes + more_stderr, True


async def run_validation_command(
    cmd: ValidationCommand, cwd: Path, *, env: dict[str, str] | None = None
) -> ValidationResult:
    """Execute one trusted argv command and capture its outcome (§9).

    ``cmd`` must already be a :class:`ValidationCommand` — i.e. it must have
    come from a validated task envelope. This is a hard runtime check, not a
    style preference: a worker result is never allowed to define what runs
    here, and this function is the last line of defence against a caller
    accidentally wiring worker-supplied text into a subprocess.
    """
    if not isinstance(cmd, ValidationCommand):
        raise TypeError(
            "run_validation_command only executes commands sourced from the "
            "trusted task envelope (a models.ValidationCommand instance); "
            f"got {type(cmd).__name__}. Worker-supplied commands must never "
            "reach this function (§9, §17)."
        )

    argv = list(cmd.argv)
    start = time.monotonic()

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        # Binary missing, not executable, cwd unusable, etc. Validation
        # commands are trusted in origin but not guaranteed to be runnable on
        # this host; report the failure rather than raising, so one bad
        # command does not abort the whole validation pass.
        duration_ms = int((time.monotonic() - start) * 1000)
        return ValidationResult(
            argv=argv,
            exit_code=None,
            passed=False,
            timed_out=False,
            duration_ms=duration_ms,
            stdout_tail="",
            stderr_tail=_tail(f"could not start command: {exc}"),
        )

    timed_out = False
    killed_with_sigkill = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=cmd.timeout_seconds
        )
    except asyncio.TimeoutError:
        timed_out = True
        stdout_bytes, stderr_bytes, killed_with_sigkill = await _terminate(proc)

    duration_ms = int((time.monotonic() - start) * 1000)
    exit_code = proc.returncode
    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")

    if timed_out and killed_with_sigkill:
        # Make the SIGKILL fallback legible in the evidence even though
        # ValidationResult has no dedicated field for it.
        stderr_text = stderr_text + "\n[dispatcher] command timed out; SIGKILL sent"

    return ValidationResult(
        argv=argv,
        exit_code=exit_code,
        passed=(exit_code == 0 and not timed_out),
        timed_out=timed_out,
        duration_ms=duration_ms,
        stdout_tail=_tail(stdout_text),
        stderr_tail=_tail(stderr_text),
    )


async def run_validations(
    envelope: TaskEnvelope, cwd: Path, config: Config
) -> list[ValidationResult]:
    """Run every envelope validation command when enabled by config (§17).

    Commands come from ``envelope.validation.commands`` **only** — never from
    a worker result, even if the worker's structured output contains commands
    of its own. Returns ``[]`` when
    ``config.validation.run_dispatcher_validation`` is ``False``. Every
    command runs to completion regardless of whether an earlier one failed;
    interpreting the results is left to the caller.
    """
    if not config.validation.run_dispatcher_validation:
        return []

    results: list[ValidationResult] = []
    for cmd in envelope.validation.commands:
        results.append(await run_validation_command(cmd, cwd))
    return results


def _claimed_argv(command: str) -> list[str] | None:
    """Best-effort tokenisation of a worker-claimed command string for matching."""
    try:
        return shlex.split(command)
    except ValueError:
        return None


def compare_claims_to_validation(
    worker_result: WorkerResult | None,
    validation_results: list[ValidationResult],
) -> list[dict[str, Any]]:
    """Cross-check worker test claims against independently re-run commands.

    For each :class:`~sol_claude_dispatcher.models.TestReport` the worker
    claimed, look for a :class:`ValidationResult` whose ``argv`` matches the
    claimed command (matched by tokenising the claim with ``shlex`` — the
    canonical comparison, since ``ValidationResult.argv`` is already a list).
    Every claim is classified:

    * ``"uncorroborated"`` — no independently re-run command matches this
      claim (including when the worker claimed ``skipped``/``not_run``, which
      asserts nothing to corroborate), or dispatcher validation was not run.
    * ``"corroborated"`` — a matching command was re-run and its pass/fail
      outcome agrees with the claim (both passed, or both failed).
    * ``"contradicted"`` — a matching command was re-run and its outcome
      disagrees with the claim.

    Returns ``[]`` when there is no worker result to compare (e.g. the run
    timed out or the structured output failed to parse).
    """
    if worker_result is None:
        return []

    by_argv: dict[tuple[str, ...], ValidationResult] = {
        tuple(vr.argv): vr for vr in validation_results
    }

    comparisons: list[dict[str, Any]] = []
    for claim in worker_result.tests:
        tokens = _claimed_argv(claim.command)
        match = by_argv.get(tuple(tokens)) if tokens is not None else None

        if match is None or claim.status not in {"passed", "failed"}:
            verdict = "uncorroborated"
            validation_passed: bool | None = None
        elif (claim.status == "passed") == match.passed:
            verdict = "corroborated"
            validation_passed = match.passed
        else:
            verdict = "contradicted"
            validation_passed = match.passed

        comparisons.append(
            {
                "command": claim.command,
                "claimed_status": claim.status,
                "validation_found": match is not None,
                "validation_passed": validation_passed,
                "verdict": verdict,
            }
        )
    return comparisons
