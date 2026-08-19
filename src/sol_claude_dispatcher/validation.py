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

A third prohibition, added by finding P1-6:

* Validation subprocesses **never inherit the dispatcher's environment**. They
  used to be spawned with ``env=None``, which handed every dispatcher
  credential in ``os.environ`` to an arbitrary trusted-but-third-party command
  (a repo's own ``pytest``, ``npm test``, ``make check`` …). The environment is
  now built explicitly by :func:`validation_environment` and passed to every
  spawn.

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
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .config import Config
from .models import TaskEnvelope, ValidationCommand, ValidationResult, WorkerResult
from .runner import StreamCapture
from .security import SECRET_ENV_MARKERS

__all__ = [
    "run_validation_command",
    "run_validations",
    "compare_claims_to_validation",
    "validation_environment",
]

#: Last-N bytes of each stream kept as evidence (§9: "bounded, e.g. last 4KB").
#: We keep a little more headroom (8KB) since ValidationResult text fields
#: allow up to 20,000 characters.
_TAIL_BYTES = 8 * 1024

#: Grace period between SIGTERM and SIGKILL when a command overruns its
#: timeout — same discipline as ``runner.run_worker`` (§20).
_GRACE_SECONDS = 5.0

#: Environment keys that name the dispatcher's own control plane. A validation
#: command is run *by* the dispatcher, not by a worker, so it must not be
#: labelled as one: injecting ``SOL_WORKER=1`` here would misreport provenance
#: and would break any validation suite that legitimately exercises dispatcher
#: code paths (this repository's own test suite, for one). Inherited copies are
#: dropped for the same reason — the child gets a deterministic environment.
_WORKER_MARKER_KEYS: tuple[str, ...] = (
    "SOL_WORKER",
    "SOL_DISPATCH_DEPTH",
    "SOL_TASK_ID",
)

#: Prefix marking dispatcher-internal configuration (paths, tokens, overrides).
_DISPATCHER_ENV_PREFIX = "SOL_DISPATCHER_"


def validation_environment(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the environment for a dispatcher-run validation subprocess (P1-6).

    Denylist, not allowlist: ordinary settings (``PATH``, ``HOME``, ``LANG``,
    ``TERM``, toolchain variables a project's test suite legitimately needs)
    are preserved, while every key whose name matches a
    :data:`~sol_claude_dispatcher.security.SECRET_ENV_MARKERS` substring
    (case-insensitive), every ``SOL_DISPATCHER_*`` key and every worker marker
    is dropped.

    Note (consolidation candidate): this deliberately mirrors
    :func:`security.worker_environment` and shares its marker list, but it is a
    *different* policy — no ``SOL_WORKER``/``SOL_DISPATCH_DEPTH``/``SOL_TASK_ID``
    is added, because this child is not a worker. The two builders should be
    unified behind one sanitiser once ``security.py`` is next touched; they must
    not be collapsed into a single function that also sets the worker markers.
    """
    source = os.environ if base_env is None else base_env
    env: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if upper.startswith(_DISPATCHER_ENV_PREFIX):
            continue
        if upper in _WORKER_MARKER_KEYS:
            continue
        if any(marker in upper for marker in SECRET_ENV_MARKERS):
            continue
        env[key] = value
    return env


def _tail(text: str, limit: int = _TAIL_BYTES) -> str:
    return text[-limit:] if len(text) > limit else text


async def _pump_streams(
    proc: "asyncio.subprocess.Process",
    stdout_capture: StreamCapture,
    stderr_capture: StreamCapture,
) -> tuple[asyncio.Future, asyncio.Future]:
    """Start dedicated readers so a timeout cannot discard partial output.

    ``communicate()`` loses everything it has buffered when the surrounding
    ``wait_for`` cancels it, which meant a timed-out validation command
    reported empty stdout/stderr — exactly the "could not inspect ⇒ assume
    nothing happened" pattern the engineering standard forbids.
    """
    return (
        asyncio.ensure_future(_read_into(proc.stdout, stdout_capture)),
        asyncio.ensure_future(_read_into(proc.stderr, stderr_capture)),
    )


async def _read_into(stream: "asyncio.StreamReader | None", capture: StreamCapture) -> None:
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


async def _await_streams(
    tasks: tuple[asyncio.Future, asyncio.Future], timeout: float
) -> None:
    """Wait for both readers to hit EOF, bounded; cancel and keep what we have."""
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError):
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _terminate(proc: "asyncio.subprocess.Process") -> bool:
    """SIGTERM, wait a grace period, SIGKILL if still alive (§9/§20 discipline).

    Returns whether SIGKILL was needed. ``ProcessLookupError`` is swallowed at
    every step — the process may have exited between the timeout firing and the
    signal being sent. Output collection is not this function's job any more:
    the reader tasks keep running throughout, so nothing is lost.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass

    try:
        await asyncio.wait_for(proc.wait(), timeout=_GRACE_SECONDS)
        return False
    except (asyncio.TimeoutError, TimeoutError):
        pass

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass

    try:
        await asyncio.wait_for(proc.wait(), timeout=_GRACE_SECONDS)
    except (asyncio.TimeoutError, TimeoutError):  # pragma: no cover - defensive
        pass
    return True


async def run_validation_command(
    cmd: ValidationCommand, cwd: Path, *, env: Mapping[str, str] | None = None
) -> ValidationResult:
    """Execute one trusted argv command and capture its outcome (§9).

    ``cmd`` must already be a :class:`ValidationCommand` — i.e. it must have
    come from a validated task envelope. This is a hard runtime check, not a
    style preference: a worker result is never allowed to define what runs
    here, and this function is the last line of defence against a caller
    accidentally wiring worker-supplied text into a subprocess.

    ``env=None`` means "build a sanitized environment from ``os.environ``"
    (P1-6) — it never means "inherit whatever the dispatcher happens to hold".
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
    child_env = validation_environment() if env is None else dict(env)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=child_env,
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

    # Dedicated readers, owned here: a timeout cancels the *wait*, never the
    # evidence already read (§20, P1-8 adjacent).
    stdout_capture = StreamCapture(_TAIL_BYTES)
    stderr_capture = StreamCapture(_TAIL_BYTES)
    tasks = await _pump_streams(proc, stdout_capture, stderr_capture)

    timed_out = False
    killed_with_sigkill = False
    try:
        try:
            await asyncio.wait_for(proc.wait(), timeout=cmd.timeout_seconds)
        except (asyncio.TimeoutError, TimeoutError):
            timed_out = True
            killed_with_sigkill = await _terminate(proc)
        await _await_streams(tasks, timeout=_GRACE_SECONDS)
    finally:
        stdout_capture.close()
        stderr_capture.close()

    duration_ms = int((time.monotonic() - start) * 1000)
    exit_code = proc.returncode

    stdout_text = stdout_capture.text()
    stdout_tail = _tail(stdout_text)
    stderr_text = stderr_capture.text()
    stderr_tail = _tail(stderr_text)
    # "Truncated" means: this tail is not the whole stream. Recorded as a fact
    # so a reader never mistakes a bounded excerpt for complete evidence.
    stdout_truncated = stdout_capture.truncated or stdout_tail != stdout_text
    stderr_truncated = stderr_capture.truncated or stderr_tail != stderr_text

    if timed_out and killed_with_sigkill:
        # Make the SIGKILL fallback legible in the evidence even though
        # ValidationResult has no dedicated field for it.
        stderr_tail = stderr_tail + "\n[dispatcher] command timed out; SIGKILL sent"

    return ValidationResult(
        argv=argv,
        exit_code=exit_code,
        passed=(exit_code == 0 and not timed_out),
        timed_out=timed_out,
        duration_ms=duration_ms,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        stdout_bytes=stdout_capture.total,
        stderr_bytes=stderr_capture.total,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
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

    The sanitized environment (P1-6) is built once and shared by every command
    in the pass, so all of them see an identical, dispatcher-secret-free
    environment.
    """
    if not config.validation.run_dispatcher_validation:
        return []

    child_env = validation_environment()
    results: list[ValidationResult] = []
    for cmd in envelope.validation.commands:
        results.append(await run_validation_command(cmd, cwd, env=child_env))
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
