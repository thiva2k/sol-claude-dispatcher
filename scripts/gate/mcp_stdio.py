"""§7 — the MCP stdio boundary. Previously unexercised after B1.

Lane H proved the oversize refusal in-process, through
``Dispatcher.dispatch_claude_task``, and said so plainly in its §10: "Not proven
live: that the refusal reaches Sol through MCP. … the MCP stdio boundary was not
exercised." Sol reaches the dispatcher through exactly one channel, so a typed
error that never crosses it is not a typed error Sol will ever see.

This module speaks real JSON-RPC over a real subprocess's stdin/stdout to the
real ``sol_claude_dispatcher.server`` entrypoint. Nothing is stubbed and the
in-process ``Dispatcher`` is never called directly.

Two servers are driven, because a server cannot change its own configuration:

* **healthy** — the ordinary ephemeral gate config: initialize, exactly four
  tools, dispatch, get_task, resume, Fable review.
* **oversize** — the same config with the worker policy file padded past the
  ceiling, which is the operator-error shape Lane H's own integration test
  drives. The dispatch must come back as a structured failure naming
  ``ContextTooLarge``, and the server must still answer afterwards.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from _common import clean_child_env, eprint, write_evidence

from sol_claude_dispatcher.config import MAX_APPEND_SYSTEM_PROMPT_BYTES
from sol_claude_dispatcher.server import TOOL_NAMES

DISPATCHER_REPO = Path(__file__).resolve().parents[2]
PROTOCOL_VERSION = "2025-06-18"


class StdioClient:
    """A minimal MCP stdio client. Real pipes, real framing, real subprocess."""

    def __init__(self, config_path: Path, cwd: Path, label: str) -> None:
        self.label = label
        env = clean_child_env({"SOL_DISPATCHER_CONFIG": str(config_path)})
        env["PYTHONPATH"] = str(DISPATCHER_REPO / "src")
        self.proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
            [str(DISPATCHER_REPO / ".venv" / "bin" / "python"), "-m",
             "sol_claude_dispatcher.server"],
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._id = 0
        self._stderr: list[str] = []
        self._drain = threading.Thread(target=self._drain_stderr, daemon=True)
        self._drain.start()
        self.transcript: list[dict[str, Any]] = []

    def _drain_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self._stderr.append(line)

    @property
    def stderr(self) -> str:
        return "".join(self._stderr)

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        self.transcript.append({"direction": "->", "payload": payload})

    def request(self, method: str, params: dict[str, Any] | None = None,
                timeout: float = 900.0) -> dict[str, Any]:
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method,
                    "params": params or {}})
        deadline = time.monotonic() + timeout
        assert self.proc.stdout is not None
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(
                    f"{self.label}: server closed stdout during {method}; "
                    f"stderr tail: {self.stderr[-800:]}"
                )
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            self.transcript.append({"direction": "<-", "payload": msg})
            if msg.get("id") == rid:
                return msg
        raise TimeoutError(f"{self.label}: no response to {method} within {timeout}s")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self) -> dict[str, Any]:
        resp = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "gate45-stdio-probe", "version": "1.0.0"},
        })
        self.notify("notifications/initialized")
        return resp

    def call_tool(self, name: str, arguments: dict[str, Any],
                  timeout: float = 900.0) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments},
                            timeout=timeout)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=20)
        except Exception:  # pragma: no cover - best effort teardown
            self.proc.kill()


def _payload_of(response: dict[str, Any]) -> dict[str, Any]:
    """Unwrap a tools/call result into the dispatcher's own payload dict."""
    result = response.get("result")
    if not isinstance(result, dict):
        return {}
    if isinstance(result.get("structuredContent"), dict):
        inner = result["structuredContent"]
        # FastMCP wraps a bare dict return under "result".
        return inner.get("result", inner) if set(inner) == {"result"} else inner
    for block in result.get("content", []) or []:
        if block.get("type") == "text":
            try:
                return json.loads(block["text"])
            except ValueError:
                continue
    return result


def run(gate, *, live: bool) -> None:
    if not live:
        gate.not_testable(
            "MCP-all", "MCP stdio boundary (§7)",
            "the four tools and the oversize refusal cross the real stdio "
            "boundary",
            "the live arm was not selected for this run",
        )
        return

    _healthy_server(gate)
    _oversize_server(gate)


# ---------------------------------------------------------------------------


def _healthy_server(gate) -> None:
    eprint("[mcp] healthy server")
    client = StdioClient(gate.fx.config_path, gate.fx.repo, "healthy")
    task_id = None
    try:
        init = client.initialize()
        ev = write_evidence(
            gate.fx.evidence_dir, "mcp.initialize.json", json.dumps(init, indent=2)
        )
        server_info = (init.get("result") or {}).get("serverInfo") or {}
        gate.check(
            "MCP-1", "MCP stdio boundary (§7)",
            "the server initializes over real stdio and identifies itself",
            "result" in init and server_info.get("name") == "sol-claude-dispatcher",
            ev, f"serverInfo={server_info}",
        )

        listed = client.request("tools/list")
        names = sorted(t["name"] for t in (listed.get("result") or {}).get("tools", []))
        ev = write_evidence(
            gate.fx.evidence_dir, "mcp.tools-list.json", json.dumps(listed, indent=2)
        )
        gate.check(
            "MCP-2", "MCP stdio boundary (§7)",
            "the surface is EXACTLY the four dispatcher tools — no fifth",
            names == sorted(TOOL_NAMES), ev,
            f"exposed={names}",
        )

        request = {
            "repository": {"root": str(gate.fx.repo), "base_ref": "HEAD"},
            "task": {
                "kind": "implementation",
                "objective": "Report the curated root reference value.",
                "context": "Disposable Gate 4.5 MCP stdio boundary probe.",
                "acceptance_criteria": ["The curated root reference value is reported."],
            },
            # Root scope. A SubAgent-scoped task has no approved REVIEW
            # projection in this fixture, so Fable would correctly fail closed
            # (Sol ruling 1) and the happy path of review_task_with_fable would
            # never be exercised. The fail-closed path is proven separately
            # below, and costs nothing because no worker is started.
            "scope": {"allowed_paths": ["notes/**"], "forbidden_paths": []},
            "routing": {"model": "sonnet", "complexity": "low", "risk": "low"},
            "execution": {"timeout_seconds": 600, "max_turns": 6},
        }
        resp = client.call_tool("dispatch_claude_task", {"request": request})
        payload = _payload_of(resp)
        ev = write_evidence(
            gate.fx.evidence_dir, "mcp.dispatch.json",
            json.dumps({"response": resp, "payload": payload}, indent=2),
        )
        task_id = payload.get("task_id")
        gate.check(
            "MCP-3", "MCP stdio boundary (§7)",
            "dispatch_claude_task works through the stdio path and returns a "
            "task id",
            bool(task_id) and "error" not in payload, ev,
            f"task_id={task_id} state={payload.get('state')} "
            f"error={payload.get('error')}",
        )

        if task_id:
            resp = client.call_tool("get_task", {"task_id": task_id})
            got = _payload_of(resp)
            ev = write_evidence(
                gate.fx.evidence_dir, "mcp.get-task.json", json.dumps(got, indent=2)
            )
            gate.check(
                "MCP-4", "MCP stdio boundary (§7)",
                "get_task works through the stdio path",
                got.get("task_id") == task_id, ev, f"state={got.get('state')}",
            )

            resp = client.call_tool("resume_claude_task", {
                "task_id": task_id,
                "instruction": (
                    "Using only the context you already have, state the curated "
                    "root reference value, or UNKNOWN."
                ),
            })
            resumed = _payload_of(resp)
            ev = write_evidence(
                gate.fx.evidence_dir, "mcp.resume.json", json.dumps(resumed, indent=2)
            )
            gate.check(
                "MCP-5", "MCP stdio boundary (§7)",
                "resume_claude_task works through the stdio path",
                "error" not in resumed and resumed.get("task_id") == task_id, ev,
                f"error={resumed.get('error')} state={resumed.get('state')}",
            )

            resp = client.call_tool("review_task_with_fable", {"task_id": task_id})
            review = _payload_of(resp)
            ev = write_evidence(
                gate.fx.evidence_dir, "mcp.fable.json", json.dumps(review, indent=2)
            )
            gate.check(
                "MCP-6", "MCP stdio boundary (§7)",
                "review_task_with_fable works through the stdio path",
                "error" not in review, ev, f"error={review.get('error')}",
            )

        # Sol ruling 1 crossing MCP: a scope with no approved projection must
        # fail closed as a typed error. Free — the refusal happens before any
        # worker is started.
        unapproved = dict(request)
        unapproved["scope"] = {"allowed_paths": ["Unreviewed/**"], "forbidden_paths": []}
        unapproved["task"] = dict(request["task"])
        unapproved["task"]["objective"] = "This dispatch must fail closed."
        resp = client.call_tool("dispatch_claude_task", {"request": unapproved},
                                timeout=300)
        refused = _payload_of(resp)
        ev = write_evidence(
            gate.fx.evidence_dir, "mcp.unapproved-scope.json",
            json.dumps(refused, indent=2),
        )
        gate.check(
            "MCP-6b", "unapproved scope across MCP (§7, §12)",
            "a task touching an unapproved scope fails closed across the stdio "
            "boundary as a typed ProjectGuidanceNotApproved, with the operator "
            "text intact and no worker started",
            refused.get("error") == "ProjectGuidanceNotApproved"
            and len(str((refused.get("details") or {}).get("operator_text", ""))) > 200
            and (refused.get("details") or {}).get("fallback_to_root_only") is False,
            ev,
            f"error={refused.get('error')} "
            f"fallback={(refused.get('details') or {}).get('fallback_to_root_only')}",
        )
        gate.mcp_task_id = task_id
    finally:
        write_evidence(
            gate.fx.evidence_dir, "mcp.healthy.transcript.json",
            json.dumps(client.transcript, indent=2)[:400_000],
        )
        write_evidence(gate.fx.evidence_dir, "mcp.healthy.stderr.txt", client.stderr)
        client.close()


# ---------------------------------------------------------------------------


def _oversize_server(gate) -> None:
    """A config whose dispatcher-authored policy alone blows the ceiling.

    This is the operator-error shape, not a contrived one: Lane H's §10 records
    that the 8,192-byte reserve is a policy choice and that pointing
    ``worker_policy_path`` at a much larger file is exactly what the preflight
    measurement — rather than the reserve — is there to catch.
    """
    eprint("[mcp] oversize server")
    work = gate.fx.root / "mcp-oversize"
    work.mkdir(parents=True, exist_ok=True)
    policy = work / "oversized-worker-policy.md"
    original = (DISPATCHER_REPO / "prompts" / "worker-policy.md").read_text(
        encoding="utf-8"
    )
    filler = "Inert padding line; only the byte count of this file matters.\n"
    body = original
    while len(body.encode()) < MAX_APPEND_SYSTEM_PROMPT_BYTES + 4096:
        body += filler
    policy.write_text(body, encoding="utf-8")

    import tomllib

    data = tomllib.loads(gate.fx.config_path.read_text(encoding="utf-8"))
    data["claude"]["worker_policy_path"] = str(policy)
    data["dispatcher"]["state_dir"] = str(work / "state")
    cfg = work / "oversize.toml"
    cfg.write_text(_emit(data), encoding="utf-8")

    client = StdioClient(cfg, gate.fx.repo, "oversize")
    try:
        client.initialize()
        request = {
            "repository": {"root": str(gate.fx.repo), "base_ref": "HEAD"},
            "task": {
                "kind": "implementation",
                "objective": "This dispatch must be refused before any worker starts.",
                "context": "Disposable Gate 4.5 oversize-context probe.",
                "acceptance_criteria": ["The dispatch is refused."],
            },
            "scope": {"allowed_paths": ["SubAgent/**"], "forbidden_paths": []},
            "routing": {"model": "sonnet", "complexity": "low", "risk": "low"},
            "execution": {"timeout_seconds": 300, "max_turns": 4},
        }
        resp = client.call_tool("dispatch_claude_task", {"request": request},
                                timeout=300)
        payload = _payload_of(resp)
        rendered = json.dumps({"response": resp, "payload": payload}, indent=2)
        ev = write_evidence(gate.fx.evidence_dir, "mcp.oversize-refusal.json", rendered)

        details = payload.get("details") or {}
        gate.check(
            "MCP-7", "B1 refusal across MCP (§7)",
            "an oversized composed context is refused across the stdio boundary "
            "as a STRUCTURED, typed ContextTooLarge payload — the server does "
            "not crash and does not return a raw traceback",
            payload.get("error") == "ContextTooLarge", ev,
            f"error={payload.get('error')} actual={details.get('actual_bytes')} "
            f"max={details.get('maximum_bytes')}",
        )
        gate.check(
            "MCP-8", "B1 refusal across MCP (§7)",
            "the structured refusal carries the byte arithmetic Sol needs",
            details.get("maximum_bytes") == MAX_APPEND_SYSTEM_PROMPT_BYTES
            and (details.get("actual_bytes") or 0) > MAX_APPEND_SYSTEM_PROMPT_BYTES,
            ev,
            f"actual={details.get('actual_bytes')} "
            f"excess={details.get('excess_bytes')} source={details.get('source')}",
        )
        gate.check(
            "MCP-9", "B1 refusal across MCP (§7)",
            "the refusal that crosses MCP leaks no projected prompt content",
            gate.proj_tokens["PROJROOT"] not in rendered
            and "Inert padding line" not in rendered, ev,
            f"payload_bytes={len(rendered)}",
        )

        alive = client.alive()
        listed = client.request("tools/list", timeout=60)
        names = sorted(t["name"] for t in (listed.get("result") or {}).get("tools", []))
        ev2 = write_evidence(
            gate.fx.evidence_dir, "mcp.post-refusal-health.json",
            json.dumps({"alive_before_probe": alive, "tools": names}, indent=2),
        )
        gate.check(
            "MCP-10", "B1 refusal across MCP (§7)",
            "the server remains HEALTHY after the refused oversize request and "
            "still answers with exactly the four tools",
            alive and names == sorted(TOOL_NAMES), ev2,
            f"alive={alive} tools={names}",
        )
    finally:
        write_evidence(
            gate.fx.evidence_dir, "mcp.oversize.transcript.json",
            json.dumps(client.transcript, indent=2)[:200_000],
        )
        write_evidence(gate.fx.evidence_dir, "mcp.oversize.stderr.txt", client.stderr)
        client.close()


def _emit(data: dict[str, Any]) -> str:
    out: list[str] = ["# THROWAWAY oversize-policy config for the §7 MCP probe.", ""]
    for table, body in data.items():
        if not isinstance(body, dict):
            continue
        out.append(f"[{table}]")
        for key, value in body.items():
            if isinstance(value, bool):
                out.append(f"{key} = {'true' if value else 'false'}")
            elif isinstance(value, (int, float)):
                out.append(f"{key} = {value!r}")
            elif isinstance(value, list):
                out.append(f"{key} = [{', '.join(json.dumps(v) for v in value)}]")
            elif value is None:
                continue
            else:
                out.append(f"{key} = {json.dumps(value)}")
        out.append("")
    return "\n".join(out)
