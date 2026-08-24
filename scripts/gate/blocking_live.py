#!/usr/bin/env python3
"""GATE 6 / Lane K — the LIVE DISPOSABLE blocking-dispatch harness (§11).

What this proves, and how each claim is *measured*
--------------------------------------------------

Gate 6 makes ``dispatch_claude_task`` block server-side until the worker reaches
an actionable state, so that Sol never has to poll. Three properties have to be
true at once, and each one is a measurement here rather than an assumption:

``PENDING``
    The MCP request is still outstanding while the worker runs. Measured by an
    id-demultiplexing client: the request id is sent, and the client records at
    every sample whether a response carrying **that same id** has arrived yet.

``EXACTLY ONE WORKER``
    Measured two ways that must agree — the delayed worker appends one line per
    launch to a log (an attributable count, with pid and session id), and the
    harness independently counts live matching processes with ``pgrep`` during
    the window.

``ZERO POLLING``
    Measured by a **counter**, never claimed. ``CountingStdioClient`` increments
    a per-tool-name counter on every ``tools/call`` it emits, and the assertion
    reads ``counts["get_task"] == 0``. The client's own JSON-RPC transcript is
    written out as corroborating evidence, so the count can be re-derived from
    the wire record rather than trusted.

``CANCELLATION SURVIVAL`` — the most important assertion in this gate
    A worker whose lifetime is coupled to the MCP waiter would silently lose
    work the moment a client disconnects. The delayed worker writes a heartbeat
    roughly twice a second; the harness records the heartbeat count immediately
    before cancelling the waiter and again several seconds after. Continued
    growth is positive evidence that the worker outlived its waiter. It then
    **reconnects with a brand new server process** against the same state
    directory and asks ``get_task`` for the authoritative state.

Disposability
-------------

Everything lives under one ``mktemp -d``: the throwaway git repository, the
ephemeral dispatcher config, the state directory, the worktrees and the
evidence. ``/home/dev/full-voice-agent`` is never named, never configured as an
allowed root, and never touched. The production ``config/dispatcher.toml`` is
read to inherit its hardened settings and is never written.

The 429 trap
------------

A usage-limit response returns a *well-formed* envelope carrying zero tokens.
It parses, it looks like a successful run, and every downstream assertion then
passes vacuously. Following ``run_gate.py``'s hardened detection, the live arm
classifies such a run as **NOT-TESTABLE** and refuses to score it. A
suspiciously empty success is never a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import clean_child_env, eprint  # noqa: E402
from fixture import _emit_toml  # noqa: E402

DISPATCHER_REPO = Path(__file__).resolve().parents[2]
PROTOCOL_VERSION = "2025-06-18"
WORKER_BIN = Path(__file__).resolve().parent / "gate6_worker.py"

#: States the gate treats as "actionable" — the set Sol is allowed to be handed
#: back. Kept as literals here rather than imported from ``models.TaskState`` so
#: that a change to the server's own notion of actionable shows up as a gate
#: failure to be reviewed, not as a silently moving goalpost.
#:
#: These are the *wire* values. ``TaskState`` is a ``str`` enum whose members
#: are lowercase (``AWAITING_SOL_REVIEW = "awaiting_sol_review"``), and the
#: payload carries the value, not the member name. Comparing against the member
#: names would fail every actionable state for a purely cosmetic reason — a
#: false red, which is as useless as a false green.
ACTIONABLE = {
    "awaiting_sol_review",
    "timed_out",
    "blocked",
    "failed",
    "policy_violation",
}


def is_actionable(state: Any) -> bool:
    return isinstance(state, str) and state.lower() in ACTIONABLE

#: A path this harness must never be pointed at, at any point, for any reason.
FORBIDDEN_ROOTS = ("/home/dev/full-voice-agent",)


# ---------------------------------------------------------------------------
# Result accounting
# ---------------------------------------------------------------------------


@dataclass
class Assertion:
    ident: str
    statement: str
    verdict: str  # PASS | FAIL | NOT-TESTABLE
    detail: str


@dataclass
class Results:
    assertions: list[Assertion] = field(default_factory=list)
    measurements: dict[str, Any] = field(default_factory=dict)

    def check(self, ident: str, statement: str, ok: bool, detail: str) -> bool:
        verdict = "PASS" if ok else "FAIL"
        self.assertions.append(Assertion(ident, statement, verdict, detail))
        eprint(f"  [{verdict:>4}] {ident}: {statement} — {detail}")
        return ok

    def not_testable(self, ident: str, statement: str, reason: str) -> None:
        """Record that we could not check — never that we checked and it was fine.

        "We could not check" and "we checked and it was fine" are different
        facts, and only one of them is evidence.
        """
        self.assertions.append(Assertion(ident, statement, "NOT-TESTABLE", reason))
        eprint(f"  [ N/T] {ident}: {statement} — {reason}")

    @property
    def failed(self) -> int:
        return sum(1 for a in self.assertions if a.verdict == "FAIL")

    @property
    def not_testable_count(self) -> int:
        return sum(1 for a in self.assertions if a.verdict == "NOT-TESTABLE")


# ---------------------------------------------------------------------------
# An MCP stdio client that COUNTS what it sends
# ---------------------------------------------------------------------------


class CountingStdioClient:
    """Real JSON-RPC over real pipes, with per-tool call counters.

    Differs from ``mcp_stdio.StdioClient`` in the two ways this gate needs:

    * **Non-blocking sends.** ``send_tool_call`` returns the request id
      immediately and a background reader demultiplexes responses by id, so the
      harness can observe the world *while the request is outstanding*. The
      existing client's ``request()`` blocks until the answer arrives, which
      makes the pending window unobservable by construction.
    * **Counters.** Every ``tools/call`` increments ``counts[name]``. The
      "zero polling" claim is read off this counter.
    """

    def __init__(self, config_path: Path, cwd: Path, label: str) -> None:
        self.label = label
        # B4: ARGV to the disposable test/development harness, never
        # SOL_DISPATCHER_CONFIG to the production entrypoint. See
        # ``sol_claude_dispatcher.config_authority``.
        env = clean_child_env()
        env["PYTHONPATH"] = str(DISPATCHER_REPO / "src")
        self.proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
            [
                str(DISPATCHER_REPO / ".venv" / "bin" / "python"),
                "-m",
                "sol_claude_dispatcher.dev_server",
                str(config_path),
            ],
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._id = 0
        self._lock = threading.Lock()
        self._responses: dict[int, dict[str, Any]] = {}
        self._stderr: list[str] = []
        self.transcript: list[dict[str, Any]] = []
        self.counts: dict[str, int] = {}
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._drain = threading.Thread(target=self._read_stderr, daemon=True)
        self._drain.start()

    # -- plumbing ----------------------------------------------------------

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            with self._lock:
                self.transcript.append({"direction": "<-", "payload": msg})
                if isinstance(msg.get("id"), int):
                    self._responses[msg["id"]] = msg

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self._stderr.append(line)

    @property
    def stderr(self) -> str:
        return "".join(self._stderr)

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        with self._lock:
            self.transcript.append({"direction": "->", "payload": payload})
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    # -- API ---------------------------------------------------------------

    def send(self, method: str, params: dict[str, Any] | None = None) -> int:
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        return rid

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def send_tool_call(self, name: str, arguments: dict[str, Any]) -> int:
        """Emit a ``tools/call`` and COUNT it. Returns immediately."""
        self.counts[name] = self.counts.get(name, 0) + 1
        return self.send("tools/call", {"name": name, "arguments": arguments})

    def pending(self, rid: int) -> bool:
        with self._lock:
            return rid not in self._responses

    def response(self, rid: int) -> dict[str, Any] | None:
        with self._lock:
            return self._responses.get(rid)

    def wait(self, rid: int, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            got = self.response(rid)
            if got is not None:
                return got
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"{self.label}: server exited (rc={self.proc.returncode}) while "
                    f"request {rid} was outstanding; stderr tail: {self.stderr[-800:]}"
                )
            time.sleep(0.1)
        raise TimeoutError(f"{self.label}: request {rid} unanswered after {timeout}s")

    def request(self, method: str, params: dict[str, Any] | None = None,
                timeout: float = 120.0) -> dict[str, Any]:
        return self.wait(self.send(method, params), timeout)

    def call_tool(self, name: str, arguments: dict[str, Any],
                  timeout: float = 120.0) -> dict[str, Any]:
        return self.wait(self.send_tool_call(name, arguments), timeout)

    def initialize(self) -> dict[str, Any]:
        resp = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "gate6-lane-k", "version": "1.0.0"},
            },
        )
        self.notify("notifications/initialized")
        return resp

    def cancel(self, rid: int, reason: str = "gate6 waiter cancelled") -> None:
        """MCP-level cancellation of one outstanding request."""
        self.notify("notifications/cancelled", {"requestId": rid, "reason": reason})

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self, *, hard: bool = False) -> None:
        try:
            if hard:
                self.proc.kill()
            elif self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=20)
        except Exception:  # pragma: no cover - best-effort teardown
            try:
                self.proc.kill()
            except Exception:
                pass


def payload_of(response: dict[str, Any]) -> dict[str, Any]:
    """Unwrap a ``tools/call`` result into the dispatcher's own payload dict."""
    result = response.get("result")
    if not isinstance(result, dict):
        return {}
    inner = result.get("structuredContent")
    if isinstance(inner, dict):
        return inner.get("result", inner) if set(inner) == {"result"} else inner
    for block in result.get("content", []) or []:
        if block.get("type") == "text":
            try:
                return json.loads(block["text"])
            except ValueError:
                continue
    return result


# ---------------------------------------------------------------------------
# Throwaway world
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    )


def build_repo(root: Path) -> Path:
    """A minimal, disposable git repository. Nothing borrowed from any real tree.

    FINDING K-2, encoded here rather than only described in prose.

    The real Claude CLI creates ``--worktree`` under ``<repo>/.claude/worktrees/``
    — *inside* the repository. In a repository that has never hosted a worker,
    that directory does not exist yet, so the primary tree gains a brand new
    ``?? .claude/`` entry between the dispatcher's before- and after-snapshots.
    ``compare_primary_tree`` compares those two snapshots, so it correctly reports
    a divergence and the task lands in ``POLICY_VIOLATION`` — even though the
    worker did nothing wrong and its scope check passed cleanly.

    The authorised production repository does not hit this because
    ``?? .claude/worktrees/`` is already one of its pre-existing untracked
    entries: it is present in the *before* snapshot, so no new entry appears.

    Pre-creating the directory here makes the fixture match that real
    precondition. It is not a workaround for a gate that would otherwise fail —
    it is the difference between a first-ever dispatch and every subsequent one,
    and Gate 6 is measuring blocking semantics, not first-run repository setup.
    """
    repo = root / "throwaway-repo"
    (repo / "notes").mkdir(parents=True, exist_ok=True)
    (repo / "notes" / "README.md").write_text(
        "Gate 6 disposable repository. Created by scripts/gate/blocking_live.py.\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "gate6@example.invalid")
    _git(repo, "config", "user.name", "Gate 6 Lane K")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "gate6 disposable base")

    # See FINDING K-2 above. Matches the authorised repository's real state.
    #
    # Created AFTER the base commit and deliberately left UNTRACKED, because the
    # entry that has to be in the before-snapshot is the untracked marker
    # `?? .claude/` — committing it would remove the entry entirely and the
    # divergence would reappear. The placeholder file is required rather than
    # decorative for the same reason: git does not report empty directories, so
    # an empty `.claude/worktrees/` produces no status entry at all.
    worktrees = repo / ".claude" / "worktrees"
    worktrees.mkdir(parents=True, exist_ok=True)
    (worktrees / ".gate6-placeholder").write_text(
        "Present so `?? .claude/` is in the primary tree's BEFORE snapshot.\n",
        encoding="utf-8",
    )
    status = _git(repo, "status", "--porcelain").stdout
    if "?? .claude/" not in status:
        raise SystemExit(
            "gate6 fixture precondition failed: the throwaway repo's primary tree "
            f"does not show `?? .claude/` before dispatch. status={status!r}"
        )
    return repo


def build_config(root: Path, repo: Path, *, binary: str, tag: str,
                 timeout_seconds: int) -> tuple[Path, Path]:
    """Write an ephemeral config derived from the production one.

    Inherits every hardened setting verbatim — the deny set, the four
    non-negotiable ``allow_*`` flags, ``max_dispatch_depth``, the B1 caps — and
    changes only what disposability requires: the state directory, the single
    allowed repository root (the throwaway repo, never a real one), and the
    worker binary. Skill/guidance projection is switched OFF: this gate is about
    blocking semantics, and dragging the manifest machinery in would add failure
    modes that have nothing to do with what is being measured.
    """
    production = DISPATCHER_REPO / "config" / "dispatcher.toml"
    data = tomllib.loads(production.read_text(encoding="utf-8"))

    for key in (
        "worker_policy_path",
        "fable_policy_path",
        "empty_mcp_config_path",
        "worker_result_schema_path",
        "fable_review_schema_path",
    ):
        value = data.get("claude", {}).get(key)
        if isinstance(value, str) and value.startswith("./"):
            data["claude"][key] = str((DISPATCHER_REPO / value[2:]).resolve())

    state_dir = root / f"state-{tag}"
    state_dir.mkdir(parents=True, exist_ok=True)

    data.setdefault("dispatcher", {})["state_dir"] = str(state_dir)
    data["dispatcher"]["default_timeout_seconds"] = timeout_seconds
    data.setdefault("security", {})["allowed_repository_roots"] = [str(repo)]
    data.setdefault("claude", {})["binary"] = binary
    data["skills"] = {
        "enabled": False,
        "mode": "projected",
        "fail_on_drift": True,
        "manifest_path": data["skills"]["manifest_path"],
    }
    data["project_guidance"] = {
        "enabled": False,
        "mode": "projected",
        "fail_on_drift": True,
        "manifest_path": data["project_guidance"]["manifest_path"],
    }
    for key in ("manifest_path",):
        for section in ("skills", "project_guidance"):
            value = data[section][key]
            if isinstance(value, str) and value.startswith("./"):
                data[section][key] = str((DISPATCHER_REPO / value[2:]).resolve())

    roots = data["security"]["allowed_repository_roots"]
    for forbidden in FORBIDDEN_ROOTS:
        if any(str(r).startswith(forbidden) for r in roots):
            raise SystemExit(
                f"REFUSING: ephemeral config would authorise {forbidden}. "
                "Gate 6 is disposable-only."
            )

    cfg = root / f"gate6-{tag}.toml"
    cfg.write_text(_emit_toml(data), encoding="utf-8")
    return cfg, state_dir


def dispatch_request(repo: Path, *, objective: str, timeout_seconds: int) -> dict:
    return {
        "repository": {"root": str(repo), "base_ref": "HEAD"},
        "task": {
            "kind": "implementation",
            "objective": objective,
            "context": "GATE 6 Lane K disposable blocking-dispatch probe.",
            "acceptance_criteria": ["The marker file exists."],
        },
        "scope": {"allowed_paths": ["**"], "forbidden_paths": [".github/**"]},
        "routing": {"model": "sonnet", "complexity": "low", "risk": "low"},
        "execution": {"timeout_seconds": timeout_seconds, "max_turns": 6},
    }


# ---------------------------------------------------------------------------
# Measurement helpers — every claim in this gate resolves to one of these
# ---------------------------------------------------------------------------


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def live_worker_processes(marker: str) -> list[int]:
    """Independent process-table count, so the launch log is corroborated."""
    result = subprocess.run(  # noqa: S603
        ["pgrep", "-f", marker], capture_output=True, text=True, check=False
    )
    return [int(p) for p in result.stdout.split() if p.isdigit()]


def newest_task_id(state_dir: Path) -> str | None:
    """Read the task id off disk.

    Needed by the cancellation arm: the dispatch response is exactly what gets
    thrown away there, so the id has to come from the authoritative store.
    """
    tasks = state_dir / "tasks"
    if not tasks.is_dir():
        return None
    dirs = [d for d in tasks.iterdir() if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime).name


def envelope_health(state_dir: Path, task_id: str) -> dict[str, Any]:
    """Inspect the worker's RAW stdout for the 429 zero-token shape.

    This is the trap the brief names: a usage-limit response is a well-formed
    envelope carrying an API error and no tokens. It parses cleanly and every
    assertion downstream of it passes for a reason that has nothing to do with
    what was being tested. Anything suspicious here makes the arm NOT-TESTABLE.
    """
    task_dir = state_dir / "tasks" / task_id
    candidates = sorted(task_dir.rglob("*stdout*"))
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            if doc.get("type") != "result":
                continue
            return {
                "found": True,
                "path": str(path),
                "api_error_status": doc.get("api_error_status"),
                "is_error": doc.get("is_error"),
                "num_turns": doc.get("num_turns"),
                "total_cost_usd": doc.get("total_cost_usd"),
                "subtype": doc.get("subtype"),
                "result_text": str(doc.get("result", ""))[:200],
            }
    return {"found": False, "searched": [str(p) for p in candidates]}


def poisoned(health: dict[str, Any]) -> str | None:
    """Return a reason string when a run must not be scored, else ``None``."""
    if not health.get("found"):
        return "no result envelope was recovered from the worker's raw stdout"
    if health.get("api_error_status"):
        return (
            f"HTTP {health['api_error_status']} from the API "
            f"({health.get('result_text')!r}) — a zero-token envelope"
        )
    turns = health.get("num_turns")
    if isinstance(turns, int) and turns <= 0:
        return "the envelope reports zero model turns — a suspiciously empty success"
    return None


# ---------------------------------------------------------------------------
# ARM 1 — the fake delayed worker: pending, exactly once, zero polling
# ---------------------------------------------------------------------------


def arm_fake_blocking(root: Path, repo: Path, res: Results, evidence: Path,
                      sleep_seconds: float) -> None:
    eprint("\n[ARM 1] fake delayed worker — pending / exactly-once / zero polling")
    tag = "fake"
    launch_log = root / f"{tag}-launches.jsonl"
    heartbeat = root / f"{tag}-heartbeat.jsonl"
    cfg, state_dir = build_config(
        root, repo, binary=str(WORKER_BIN), tag=tag, timeout_seconds=600
    )

    os.environ["GATE6_LAUNCH_LOG"] = str(launch_log)
    os.environ["GATE6_HEARTBEAT"] = str(heartbeat)
    os.environ["GATE6_SLEEP"] = str(sleep_seconds)
    os.environ["GATE6_WORKTREE_ROOT"] = str(root / "worktrees-fake")

    client = CountingStdioClient(cfg, repo, "arm1")
    samples: list[dict[str, Any]] = []
    try:
        client.initialize()

        # t = 0 — Sol calls dispatch ONCE, and nothing else, ever.
        t0 = time.monotonic()
        rid = client.send_tool_call(
            "dispatch_claude_task",
            {"request": dispatch_request(repo, objective="Write the gate6 marker.",
                                         timeout_seconds=600)},
        )
        res.check(
            "K-B1", "dispatch is called exactly once at t=0",
            client.counts.get("dispatch_claude_task") == 1,
            f"dispatch_claude_task call count = {client.counts.get('dispatch_claude_task')}",
        )

        # During the delay: sample the world. No get_task, no second dispatch.
        window_end = t0 + sleep_seconds * 0.7
        while time.monotonic() < window_end:
            samples.append(
                {
                    "t": round(time.monotonic() - t0, 2),
                    "mcp_request_pending": client.pending(rid),
                    "launches_recorded": count_lines(launch_log),
                    "live_worker_pids": live_worker_processes(str(WORKER_BIN)),
                    "heartbeats": count_lines(heartbeat),
                    "get_task_calls_so_far": client.counts.get("get_task", 0),
                }
            )
            time.sleep(1.0)

        observed = [s for s in samples if s["launches_recorded"] > 0]
        res.measurements["arm1_samples"] = samples

        res.check(
            "K-B2", "the MCP request stays PENDING for the whole worker run",
            bool(observed) and all(s["mcp_request_pending"] for s in samples),
            f"{sum(1 for s in samples if s['mcp_request_pending'])}/{len(samples)} "
            f"samples pending over {round(time.monotonic() - t0, 1)}s",
        )
        res.check(
            "K-B3", "the worker exists EXACTLY ONCE while the request is pending",
            bool(observed)
            and all(s["launches_recorded"] == 1 for s in observed)
            and all(len(s["live_worker_pids"]) <= 1 for s in samples),
            f"launch-log counts={sorted({s['launches_recorded'] for s in observed})} "
            f"max live pids={max((len(s['live_worker_pids']) for s in samples), default=0)}",
        )
        res.check(
            "K-B4", "ZERO get_task calls occur during the pending window (measured)",
            all(s["get_task_calls_so_far"] == 0 for s in samples)
            and client.counts.get("get_task", 0) == 0,
            f"counter get_task={client.counts.get('get_task', 0)} across "
            f"{len(samples)} samples",
        )

        # On completion: the SAME request id answers.
        resp = client.wait(rid, timeout=sleep_seconds + 600)
        elapsed = time.monotonic() - t0
        payload = payload_of(resp)
        res.measurements["arm1_dispatch_payload"] = payload
        res.measurements["arm1_elapsed_seconds"] = round(elapsed, 2)

        res.check(
            "K-B5", "the SAME MCP request returns (id matches the one sent at t=0)",
            resp.get("id") == rid,
            f"sent id={rid} answered id={resp.get('id')} after {elapsed:.1f}s",
        )
        state = payload.get("state")
        res.check(
            "K-B6", "the blocked call returns an ACTIONABLE state",
            is_actionable(state), f"state={state} (actionable set={sorted(ACTIONABLE)})",
        )
        res.check(
            "K-B7", "that state is AWAITING_SOL_REVIEW for a clean completion",
            state == "awaiting_sol_review", f"state={state}",
        )
        res.check(
            "K-B8", "the call blocked for essentially the whole worker run",
            elapsed >= sleep_seconds * 0.9,
            f"elapsed={elapsed:.1f}s vs worker sleep={sleep_seconds}s",
        )
        res.check(
            "K-B9", "the worker was launched exactly once for the whole task",
            count_lines(launch_log) == 1,
            f"launch log lines = {count_lines(launch_log)}",
        )
        res.check(
            "K-B10", "ZERO get_task calls occurred for the ENTIRE task (measured)",
            client.counts.get("get_task", 0) == 0,
            f"final counters = {client.counts}",
        )
        (evidence / "arm1-transcript.json").write_text(
            json.dumps(client.transcript, indent=2, default=str), encoding="utf-8"
        )
        wire_get_task = sum(
            1
            for e in client.transcript
            if e["direction"] == "->"
            and e["payload"].get("method") == "tools/call"
            and (e["payload"].get("params") or {}).get("name") == "get_task"
        )
        res.check(
            "K-B11", "the wire transcript independently confirms the zero-poll count",
            wire_get_task == 0,
            f"get_task tools/call frames on the wire = {wire_get_task}",
        )
    finally:
        (evidence / "arm1-samples.json").write_text(
            json.dumps(samples, indent=2, default=str), encoding="utf-8"
        )
        (evidence / "arm1-server-stderr.log").write_text(client.stderr, encoding="utf-8")
        client.close()


# ---------------------------------------------------------------------------
# ARM 2 — cancellation survival. The assertion that matters most.
# ---------------------------------------------------------------------------


def arm_cancellation(root: Path, repo: Path, res: Results, evidence: Path,
                     sleep_seconds: float) -> None:
    eprint("\n[ARM 2] cancel the waiter — does the worker survive?")
    tag = "cancel"
    launch_log = root / f"{tag}-launches.jsonl"
    heartbeat = root / f"{tag}-heartbeat.jsonl"
    cfg, state_dir = build_config(
        root, repo, binary=str(WORKER_BIN), tag=tag, timeout_seconds=600
    )
    os.environ["GATE6_LAUNCH_LOG"] = str(launch_log)
    os.environ["GATE6_HEARTBEAT"] = str(heartbeat)
    os.environ["GATE6_SLEEP"] = str(sleep_seconds)
    os.environ["GATE6_WORKTREE_ROOT"] = str(root / "worktrees-cancel")

    timeline: list[dict[str, Any]] = []
    client = CountingStdioClient(cfg, repo, "arm2")
    task_id = None
    try:
        client.initialize()
        t0 = time.monotonic()
        rid = client.send_tool_call(
            "dispatch_claude_task",
            {"request": dispatch_request(repo, objective="Write the gate6 marker (cancel arm).",
                                         timeout_seconds=600)},
        )

        # Wait until the worker is unambiguously alive before cancelling —
        # cancelling before the worker starts would prove nothing.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and count_lines(heartbeat) < 3:
            time.sleep(0.25)
        beats_before = count_lines(heartbeat)
        pids_before = live_worker_processes(str(WORKER_BIN))
        timeline.append({"phase": "pre-cancel", "t": round(time.monotonic() - t0, 2),
                         "heartbeats": beats_before, "pids": pids_before})
        res.check(
            "K-C1", "the worker is demonstrably running before the waiter is cancelled",
            beats_before >= 3 and len(pids_before) == 1,
            f"heartbeats={beats_before} live pids={pids_before}",
        )

        # CANCEL THE WAITER.
        client.cancel(rid)
        cancel_t = time.monotonic()
        timeline.append({"phase": "cancel-sent", "t": round(cancel_t - t0, 2),
                         "heartbeats": count_lines(heartbeat)})

        # Watch for continued life. The worker must not notice.
        time.sleep(6.0)
        beats_after = count_lines(heartbeat)
        pids_after = live_worker_processes(str(WORKER_BIN))
        timeline.append({"phase": "post-cancel", "t": round(time.monotonic() - t0, 2),
                         "heartbeats": beats_after, "pids": pids_after})

        res.check(
            "K-C2",
            "THE WORKER SURVIVES WAITER CANCELLATION — heartbeats keep arriving",
            beats_after > beats_before,
            f"heartbeats {beats_before} -> {beats_after} over 6s after cancel; "
            f"live pids {pids_before} -> {pids_after}",
        )
        res.check(
            "K-C3", "cancellation did not spawn a replacement worker",
            count_lines(launch_log) == 1,
            f"launch log lines = {count_lines(launch_log)}",
        )
        res.check(
            "K-C4", "the server process itself survives the cancelled request",
            client.alive(), f"server alive = {client.alive()}",
        )

        # Whether the server ACKNOWLEDGES the cancellation is a separate,
        # non-graded fact — MCP cancellation is advisory and a server that
        # simply completes the request has not violated anything. What matters
        # is that the work was not destroyed.
        cancelled_ack = client.response(rid) is not None
        res.measurements["arm2_cancel_acknowledged_within_6s"] = cancelled_ack

        # Let the worker finish on its own, unattended.
        deadline = time.monotonic() + sleep_seconds + 600
        while time.monotonic() < deadline:
            task_id = newest_task_id(state_dir)
            if task_id and not live_worker_processes(str(WORKER_BIN)):
                break
            time.sleep(1.0)
        timeline.append({"phase": "worker-exited", "t": round(time.monotonic() - t0, 2),
                         "heartbeats": count_lines(heartbeat), "task_id": task_id})
        res.measurements["arm2_final_heartbeats"] = count_lines(heartbeat)

        # Give the server a moment to finalise the record it is still holding.
        time.sleep(5.0)

        res.check(
            "K-C5", "the worker ran to natural completion after its waiter was cancelled",
            count_lines(heartbeat) > beats_after,
            f"heartbeats at cancel={beats_before}, +6s={beats_after}, "
            f"final={count_lines(heartbeat)}",
        )
    finally:
        (evidence / "arm2-timeline.json").write_text(
            json.dumps(timeline, indent=2, default=str), encoding="utf-8"
        )
        (evidence / "arm2-transcript.json").write_text(
            json.dumps(client.transcript, indent=2, default=str), encoding="utf-8"
        )
        (evidence / "arm2-server-stderr.log").write_text(client.stderr, encoding="utf-8")
        client.close()

    # RECONNECT — a brand new server process against the same state directory.
    task_id = task_id or newest_task_id(state_dir)
    if not task_id:
        res.not_testable(
            "K-C6", "the completed authoritative state is available after reconnect",
            "no task directory was created, so there is nothing to read back",
        )
        return

    client2 = CountingStdioClient(cfg, repo, "arm2-reconnect")
    try:
        client2.initialize()
        resp = client2.call_tool("get_task", {"task_id": task_id}, timeout=120)
        got = payload_of(resp)
        (evidence / "arm2-reconnect-get-task.json").write_text(
            json.dumps(got, indent=2, default=str), encoding="utf-8"
        )
        res.measurements["arm2_reconnect_state"] = got.get("state")
        res.check(
            "K-C6",
            "after reconnecting, get_task returns the task the cancelled waiter started",
            got.get("task_id") == task_id,
            f"task_id={got.get('task_id')} state={got.get('state')}",
        )
        res.check(
            "K-C7",
            "the state recovered after cancellation is the COMPLETED authoritative one",
            is_actionable(got.get("state")),
            f"state={got.get('state')} (actionable={sorted(ACTIONABLE)})",
        )
        res.check(
            "K-C8",
            "recovery cost exactly ONE get_task call — the recovery path, not polling",
            client2.counts.get("get_task") == 1,
            f"reconnect counters = {client2.counts}",
        )
    finally:
        (evidence / "arm2-reconnect-stderr.log").write_text(client2.stderr, encoding="utf-8")
        client2.close()


# ---------------------------------------------------------------------------
# ARM 3 — the same shape, end to end, with a REAL short Sonnet worker
# ---------------------------------------------------------------------------


def arm_live_sonnet(root: Path, repo: Path, res: Results, evidence: Path,
                    timeout_seconds: int) -> None:
    eprint("\n[ARM 3] REAL Sonnet worker — same shape, end to end")
    binary = shutil.which("claude")
    if not binary:
        res.not_testable(
            "K-L1", "a real short Sonnet task shows the same blocking shape",
            "no `claude` binary on PATH",
        )
        return

    tag = "live"
    cfg, state_dir = build_config(
        root, repo, binary=binary, tag=tag, timeout_seconds=timeout_seconds
    )
    marker = str(uuid.uuid4())[:8]
    samples: list[dict[str, Any]] = []
    client = CountingStdioClient(cfg, repo, "arm3")
    try:
        client.initialize()
        t0 = time.monotonic()
        rid = client.send_tool_call(
            "dispatch_claude_task",
            {
                "request": dispatch_request(
                    repo,
                    objective=(
                        "Create a file notes/gate6-live.txt whose entire contents are "
                        f"the single line: GATE6-LIVE-{marker}. Change nothing else."
                    ),
                    timeout_seconds=timeout_seconds,
                )
            },
        )
        res.check(
            "K-L1", "the real dispatch is called exactly once",
            client.counts.get("dispatch_claude_task") == 1,
            f"counters = {client.counts}",
        )

        # Sample the pending window for as long as the worker is actually alive.
        while client.pending(rid) and time.monotonic() - t0 < timeout_seconds + 120:
            samples.append(
                {
                    "t": round(time.monotonic() - t0, 2),
                    "mcp_request_pending": True,
                    "get_task_calls_so_far": client.counts.get("get_task", 0),
                }
            )
            time.sleep(2.0)

        resp = client.wait(rid, timeout=60)
        elapsed = time.monotonic() - t0
        payload = payload_of(resp)
        (evidence / "arm3-dispatch-payload.json").write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        task_id = payload.get("task_id") or newest_task_id(state_dir)
        health = envelope_health(state_dir, task_id) if task_id else {"found": False}
        (evidence / "arm3-envelope-health.json").write_text(
            json.dumps(health, indent=2, default=str), encoding="utf-8"
        )
        res.measurements["arm3_envelope_health"] = health
        res.measurements["arm3_elapsed_seconds"] = round(elapsed, 2)
        res.measurements["arm3_dispatch_payload_state"] = payload.get("state")

        # THE 429 TRAP. A well-formed zero-token envelope is not a pass.
        reason = poisoned(health)
        if reason is not None:
            for ident, statement in (
                ("K-L2", "the real MCP request stayed pending for the whole run"),
                ("K-L3", "the real blocked call returned an actionable state"),
                ("K-L4", "ZERO get_task calls occurred for the real task (measured)"),
            ):
                res.not_testable(
                    ident, statement,
                    f"{reason}. Nothing about this run is evidence — re-run the arm.",
                )
            return

        res.check(
            "K-L2", "the real MCP request stayed pending for the whole run",
            len(samples) > 0 and all(s["mcp_request_pending"] for s in samples),
            f"{len(samples)} pending samples over {elapsed:.1f}s",
        )
        res.check(
            "K-L3", "the real blocked call returned an actionable state on the SAME id",
            resp.get("id") == rid and is_actionable(payload.get("state")),
            f"id={resp.get('id')} state={payload.get('state')}",
        )
        res.check(
            "K-L4", "ZERO get_task calls occurred for the real task (measured)",
            client.counts.get("get_task", 0) == 0,
            f"final counters = {client.counts}",
        )
        obs = payload.get("dispatcher_observations") or {}
        res.check(
            "K-L5",
            "the real task completed CLEANLY — scope held and the primary tree "
            "was not disturbed, so AWAITING_SOL_REVIEW is a real result",
            payload.get("state") == "awaiting_sol_review"
            and obs.get("scope_valid") is True
            and obs.get("primary_tree_unchanged") is True,
            f"state={payload.get('state')} scope_valid={obs.get('scope_valid')} "
            f"primary_tree_unchanged={obs.get('primary_tree_unchanged')} "
            f"turns={health.get('num_turns')} cost=${health.get('total_cost_usd')}",
        )
    finally:
        (evidence / "arm3-samples.json").write_text(
            json.dumps(samples, indent=2, default=str), encoding="utf-8"
        )
        (evidence / "arm3-server-stderr.log").write_text(client.stderr, encoding="utf-8")
        client.close()


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arms", default="fake,cancel",
                    help="comma-separated: fake, cancel, live")
    ap.add_argument("--sleep", type=float, default=25.0,
                    help="seconds the fake delayed worker sleeps")
    ap.add_argument("--live-timeout", type=int, default=600)
    ap.add_argument("--keep", action="store_true", help="keep the throwaway tree")
    ap.add_argument("--out", default="", help="write the JSON result here")
    args = ap.parse_args()

    root = Path(
        subprocess.run(  # noqa: S603
            ["mktemp", "-d", "-t", "gate6-lane-k.XXXXXXXX"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    )
    evidence = root / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    eprint(f"[gate6] disposable root: {root}")

    repo = build_repo(root)
    res = Results()
    res.measurements["disposable_root"] = str(root)
    res.measurements["throwaway_repo"] = str(repo)
    res.measurements["dispatcher_head"] = subprocess.run(  # noqa: S603
        ["git", "rev-parse", "HEAD"], cwd=str(DISPATCHER_REPO),
        capture_output=True, text=True, check=False,
    ).stdout.strip()

    arms = {a.strip() for a in args.arms.split(",") if a.strip()}
    try:
        if "fake" in arms:
            arm_fake_blocking(root, repo, res, evidence, args.sleep)
        if "cancel" in arms:
            arm_cancellation(root, repo, res, evidence, args.sleep)
        if "live" in arms:
            arm_live_sonnet(root, repo, res, evidence, args.live_timeout)
    finally:
        report = {
            "assertions": [a.__dict__ for a in res.assertions],
            "measurements": res.measurements,
            "summary": {
                "pass": sum(1 for a in res.assertions if a.verdict == "PASS"),
                "fail": res.failed,
                "not_testable": res.not_testable_count,
            },
        }
        (evidence / "results.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        if args.out:
            Path(args.out).write_text(
                json.dumps(report, indent=2, default=str), encoding="utf-8"
            )
        eprint("\n=== GATE 6 LANE K — LIVE RESULTS ===")
        for a in res.assertions:
            eprint(f"{a.verdict:>12}  {a.ident}  {a.statement}")
            eprint(f"              {a.detail}")
        eprint(f"\npass={report['summary']['pass']} fail={report['summary']['fail']} "
               f"not-testable={report['summary']['not_testable']}")
        eprint(f"[gate6] evidence: {evidence}")
        if not args.keep:
            eprint(f"[gate6] (throwaway tree kept for inspection: {root})")

    return 1 if res.failed else 0


if __name__ == "__main__":
    sys.exit(main())
