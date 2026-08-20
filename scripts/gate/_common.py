"""Shared machinery for the Gate 4.5 disposable live adversarial harness.

Nothing in this package is a pytest test and nothing here is imported by
``src/sol_claude_dispatcher``. It spawns the REAL Claude CLI, so it must never
be collected by the unit suite (repository rule: "never spawn a real claude or
codex child process from a test"). It lives under ``scripts/`` for exactly that
reason and is run by hand, deliberately, with a recorded cost.

Two ideas carry the whole design:

1. **A suppression proof is worthless without a positive control.** Every
   sentinel is first proven to FIRE under a normal, un-isolated invocation.
   Only a sentinel with a demonstrated firing baseline is admissible evidence
   that safe mode suppressed anything.

2. **Two independent detection channels per sentinel where possible.** A
   *token* channel (a nonce string the model can only emit if it read the
   planted text) and a *file* channel (a ``touch`` of a uniquely named file
   inside the throwaway tree). The file channel is model-independent for hooks
   and MCP: the file exists if and only if the customization actually
   executed.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Absolute paths that must never appear beneath a sentinel's write target.
#: A sentinel that writes outside the throwaway tree is a defect in this
#: harness, not a finding, so the check is a hard abort rather than a warning.
FORBIDDEN_WRITE_ROOTS: tuple[str, ...] = (
    "/home/dev/full-voice-agent",
    "/home/dev/.claude",
    "/home/dev/.codex",
    "/home/dev/worktrees",
    str(REPO_ROOT),
)

#: Environment variables that would sabotage the positive control if inherited
#: from the harness's own (Claude-Code-hosted) process. ``CLAUDE_CODE_DISABLE_
#: AUTO_MEMORY`` is the dangerous one: inheriting it would suppress CLAUDE.md
#: loading in the child and make the positive control fail for a reason that
#: has nothing to do with safe mode.
_STRIPPED_ENV_PREFIXES: tuple[str, ...] = ("CLAUDE_", "SOL_")
_STRIPPED_ENV_EXACT: frozenset[str] = frozenset(
    {"CLAUDECODE", "ANTHROPIC_LOG", "CLAUDE_PID", "CLAUDE_EFFORT"}
)


def assert_write_target_safe(path: Path) -> None:
    """Abort unless ``path`` is inside a throwaway tree.

    Called before any sentinel that writes is planted. Deliberately a bare
    ``SystemExit`` rather than a logged warning: there is no safe way to
    continue after discovering the harness is about to arm a write outside
    its own sandbox.
    """
    resolved = str(Path(path).resolve())
    for forbidden in FORBIDDEN_WRITE_ROOTS:
        if resolved == forbidden or resolved.startswith(forbidden.rstrip("/") + "/"):
            raise SystemExit(
                f"REFUSING to plant a sentinel that writes under {forbidden}: {resolved}"
            )
    if not resolved.startswith("/tmp/"):
        raise SystemExit(
            f"REFUSING to plant a sentinel outside /tmp: {resolved}"
        )


def clean_child_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """A plain-user-shell approximation of the environment.

    The harness itself runs inside a Claude Code session, so ``os.environ``
    carries a dozen ``CLAUDE_CODE_*`` markers. A child that inherited them is
    not a "normal invocation" and its result would not be a valid baseline.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in _STRIPPED_ENV_EXACT
        and not any(k.startswith(p) for p in _STRIPPED_ENV_PREFIXES)
    }
    if extra:
        env.update(extra)
    return env


def new_nonce() -> str:
    """A run-unique token stem that cannot occur by chance in model output."""
    return "G45" + secrets.token_hex(6).upper()


# ---------------------------------------------------------------------------
# Invocation + cost accounting
# ---------------------------------------------------------------------------


@dataclass
class Invocation:
    """One real CLI execution and everything measured about it."""

    label: str
    argv: list[str]
    cwd: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0
    timed_out: bool = False
    parsed: dict[str, Any] | None = None
    cost_usd: float = 0.0

    @property
    def result_text(self) -> str:
        """The model's own reply text, or the raw stdout if unparseable.

        Assertions search this rather than the whole stdout so that a token
        appearing only inside, say, an echoed argv cannot be mistaken for the
        model having emitted it. When parsing fails the raw stream is returned
        so a broken run reads as "token absent", never as "token present".
        """
        if self.parsed is None:
            return ""
        value = self.parsed.get("result")
        return value if isinstance(value, str) else json.dumps(value or "")

    def to_record(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "argv": self.argv,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "duration_s": round(self.duration_s, 2),
            "cost_usd": self.cost_usd,
            "stdout_bytes": len(self.stdout),
            "stderr_bytes": len(self.stderr),
            "result_text": self.result_text,
            "stderr_tail": self.stderr[-2000:],
        }


@dataclass
class CostLedger:
    """Every live invocation's cost, so the envelope is a measurement."""

    invocations: list[Invocation] = field(default_factory=list)

    def add(self, inv: Invocation) -> Invocation:
        self.invocations.append(inv)
        return inv

    @property
    def total_usd(self) -> float:
        return round(sum(i.cost_usd for i in self.invocations), 6)

    def table(self) -> str:
        lines = ["| # | invocation | exit | duration s | cost USD |", "|---|---|---|---|---|"]
        for n, inv in enumerate(self.invocations, 1):
            lines.append(
                f"| {n} | `{inv.label}` | {inv.exit_code} | {inv.duration_s:.1f} | "
                f"{inv.cost_usd:.6f} |"
            )
        lines.append(f"| | **TOTAL** | | | **{self.total_usd:.6f}** |")
        return "\n".join(lines)


def run_cli(
    label: str,
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout_s: int = 300,
    ledger: CostLedger | None = None,
) -> Invocation:
    """Execute the real CLI once. argv is a list — never a shell string."""
    inv = Invocation(label=label, argv=list(argv), cwd=str(cwd))
    started = time.monotonic()
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            list(argv),
            cwd=str(cwd),
            env=dict(env) if env is not None else clean_child_env(),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            # The CLI waits on stdin when it is a pipe it cannot read, and a
            # probe that stalled there would look like a suppressed sentinel.
            stdin=subprocess.DEVNULL,
        )
        inv.exit_code = proc.returncode
        inv.stdout = proc.stdout
        inv.stderr = proc.stderr
    except OSError as exc:
        # E2BIG: one argv element exceeded MAX_ARG_STRLEN, so execve never ran.
        # Recorded as a real result rather than crashing the harness — "the
        # process could not start" is exactly the finding claim I is looking
        # for, and it must land in the report, not in a traceback.
        inv.exit_code = None
        inv.stderr = f"{type(exc).__name__}: {exc}"
    except subprocess.TimeoutExpired as exc:
        inv.timed_out = True
        inv.stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        inv.stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    inv.duration_s = time.monotonic() - started

    try:
        parsed = json.loads(inv.stdout)
        if isinstance(parsed, dict):
            inv.parsed = parsed
            cost = parsed.get("total_cost_usd")
            inv.cost_usd = float(cost) if isinstance(cost, (int, float)) else 0.0
    except (ValueError, TypeError):
        inv.parsed = None

    if ledger is not None:
        ledger.add(inv)
    return inv


# ---------------------------------------------------------------------------
# Assertion recording
# ---------------------------------------------------------------------------


@dataclass
class Assertion:
    """One independently reported PASS/FAIL with its raw evidence pointer."""

    ident: str
    surface: str
    statement: str
    passed: bool
    evidence: str
    detail: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.ident,
            "surface": self.surface,
            "statement": self.statement,
            "result": "PASS" if self.passed else "FAIL",
            "evidence": self.evidence,
            "detail": self.detail,
        }


def write_evidence(evidence_dir: Path, name: str, payload: str) -> str:
    """Persist a raw evidence blob and return its absolute path."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    target = evidence_dir / name
    target.write_text(payload, encoding="utf-8")
    return str(target)


def cleanup(path: Path, *, keep: bool) -> str:
    """Remove a throwaway tree unless the operator asked to keep it."""
    if keep:
        return f"KEPT (operator requested): {path}"
    shutil.rmtree(path, ignore_errors=True)
    return f"REMOVED: {path} (exists after cleanup: {path.exists()})"


def stray_sentinel_scan(nonce: str, roots: Iterable[str]) -> list[str]:
    """Prove no sentinel file leaked outside the throwaway tree.

    Searches by the run nonce, which appears in every planted filename. A hit
    anywhere under a protected root is reported verbatim; the caller decides
    what to do, but the intended answer is "fail the run loudly".
    """
    hits: list[str] = []
    for root in roots:
        base = Path(root)
        if not base.exists():
            continue
        try:
            found = subprocess.run(  # noqa: S603 - argv list, no shell
                ["find", str(base), "-maxdepth", "6", "-name", f"*{nonce}*"],
                capture_output=True,
                text=True,
                timeout=90,
            )
            hits.extend(line for line in found.stdout.splitlines() if line.strip())
        except (subprocess.SubprocessError, OSError) as exc:  # pragma: no cover
            hits.append(f"<scan failed for {root}: {exc}>")
    return hits


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr, flush=True)
