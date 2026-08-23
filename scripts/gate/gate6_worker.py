#!/usr/bin/env python3
"""GATE 6 / Lane K — a *delayed* disposable worker binary.

Why this exists and why it is not ``tests/fake_bin/claude``
-----------------------------------------------------------

Gate 6 has to observe a dispatch **while it is still running**: the MCP request
must be provably PENDING, the worker must provably exist exactly once, and the
``get_task`` call count must provably be zero for the whole window. None of that
is observable against a worker that finishes instantly, and the existing fake
binary has no "sleep, *then* succeed" mode — its sleeping modes exist to be
killed by the deadline, which is the opposite of what this gate needs.

Modifying the shared test binary was rejected: Lane J runs the suite
concurrently, and a shared fixture is the wrong place to put a gate-only
behaviour. This file is owned by ``scripts/gate/**`` and executed only by
``scripts/gate/blocking_live.py``.

What it does, in order
----------------------

1. Appends **one line** to ``$GATE6_LAUNCH_LOG`` per invocation, before doing
   anything else. That file is the *measurement* behind "the worker was started
   exactly once" — a count, not an assumption. It records pid, ppid, session id,
   worktree name and whether ``--resume`` was present, so a second launch is not
   merely detected but attributable.
2. Creates the isolated worktree the dispatcher expects, exactly as
   ``tests/fixtures/claude_worktree_shim.py`` does
   (``git worktree add -b <name> <root>/<name>``), and chdirs into it. The
   dispatcher resolves the worktree by final path component, so the location is
   irrelevant to it.
3. Writes one real file inside the worktree, so the dispatcher's own diff
   evidence is non-empty and the run is a genuine dispatch rather than a no-op.
4. Sleeps ``$GATE6_SLEEP`` seconds, appending a **heartbeat** line to
   ``$GATE6_HEARTBEAT`` roughly twice a second. The heartbeat is the measurement
   behind the single most important Gate 6 assertion: after the MCP waiter is
   cancelled, heartbeats must keep arriving. A worker killed by a disconnected
   waiter stops writing, and that is detectable rather than inferred.
5. Emits a valid ``--output-format json`` envelope carrying a schema-valid
   ``WorkerResult`` on stdout and exits 0.

Signals are deliberately **not** trapped. SIGTERM kills this process normally,
so "the dispatcher's timeout discipline still works" and "the waiter did not
kill the worker" stay independently observable.

This file never contacts the network, never launches a real agent, and only
writes inside the throwaway tree it is pointed at.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

#: Flags that take a value, so a value is never mistaken for the next flag.
_VALUE_FLAGS = {
    "--session-id",
    "--resume",
    "-r",
    "--worktree",
    "-w",
    "--model",
    "--output-format",
    "--permission-mode",
    "--mcp-config",
    "--json-schema",
    "--append-system-prompt",
    "--max-budget-usd",
    "-p",
}


def parse_argv(argv: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in _VALUE_FLAGS and i + 1 < len(argv):
            values[token] = argv[i + 1]
            i += 2
            continue
        i += 1
    return values


def _append(path: str | None, line: str) -> None:
    """Append one line, flushed and fsynced.

    A heartbeat that is still sitting in a buffer when the process is killed is
    a heartbeat the gate cannot see, and an unseen heartbeat would be scored as
    a dead worker. Durability here is load-bearing, not tidiness.
    """
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _make_worktree(name: str) -> Path | None:
    repo = Path.cwd()
    root = Path(
        os.environ.get("GATE6_WORKTREE_ROOT", str(repo.parent / ".gate6-worktrees"))
    )
    root.mkdir(parents=True, exist_ok=True)
    target = root / name
    if target.exists():
        os.chdir(target)
        return target
    result = subprocess.run(  # noqa: S603 - argv list, no shell
        ["git", "worktree", "add", "-b", name, str(target)],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(
            f"gate6_worker: git worktree add failed: {result.stderr.strip()}\n"
        )
        return None
    os.chdir(target)
    return target


def _envelope(session_id: str | None, summary: str, changed: str) -> dict:
    """The shape ``claude -p --output-format json`` produces."""
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 0,
        "num_turns": 2,
        "session_id": session_id or "00000000-0000-4000-8000-000000000000",
        "total_cost_usd": 0.0,
        "result": "gate6 delayed worker complete",
        "structured_output": {
            "status": "completed",
            "summary": summary,
            "changes": [
                {
                    "path": changed,
                    "type": "added",
                    "description": "gate6 delayed-worker marker",
                }
            ],
            "acceptance_criteria": [
                {
                    "criterion": "The worker runs long enough to be observed mid-flight.",
                    "status": "satisfied",
                    "evidence": f"heartbeat log at {os.environ.get('GATE6_HEARTBEAT', '<unset>')}",
                }
            ],
            "tests": [],
            "risks": [],
            "blockers": [],
            "needs_review": True,
        },
    }


def main(argv: list[str]) -> int:
    parsed = parse_argv(argv)
    session_id = parsed.get("--session-id")
    resume_id = parsed.get("--resume") or parsed.get("-r")
    worktree = parsed.get("--worktree") or parsed.get("-w")

    launch_log = os.environ.get("GATE6_LAUNCH_LOG")
    heartbeat = os.environ.get("GATE6_HEARTBEAT")
    sleep_seconds = float(os.environ.get("GATE6_SLEEP", "30"))

    # (1) Record the launch FIRST. If this process is killed a millisecond
    # later, the gate must still be able to count it.
    _append(
        launch_log,
        json.dumps(
            {
                "event": "launch",
                "ts": time.time(),
                "pid": os.getpid(),
                "ppid": os.getppid(),
                "session_id": session_id,
                "resume_session_id": resume_id,
                "worktree": worktree,
                "cwd": os.getcwd(),
            }
        ),
    )

    # (2) The one real-CLI behaviour the dispatcher depends on.
    if worktree:
        if _make_worktree(worktree) is None:
            return 70

    # (3) A real change, so the dispatcher's diff evidence is genuine.
    changed_rel = "gate6-marker.txt"
    Path(changed_rel).write_text(
        f"gate6 delayed worker\npid={os.getpid()}\nsession={session_id}\n",
        encoding="utf-8",
    )

    # (4) Sleep, audibly. Untrapped signals: a SIGTERM ends the heartbeat here.
    deadline = time.monotonic() + sleep_seconds
    while time.monotonic() < deadline:
        _append(
            heartbeat,
            json.dumps({"ts": time.time(), "pid": os.getpid(), "session_id": session_id}),
        )
        time.sleep(0.5)
    _append(
        heartbeat,
        json.dumps(
            {"ts": time.time(), "pid": os.getpid(), "session_id": session_id, "final": True}
        ),
    )

    # (5) The structured result the dispatcher parses.
    print(
        json.dumps(
            _envelope(
                session_id,
                f"Delayed gate6 worker slept {sleep_seconds}s and completed.",
                changed_rel,
            )
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
