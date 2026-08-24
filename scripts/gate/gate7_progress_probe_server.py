#!/usr/bin/env python3
"""GATE 7 §18 disposable MCP conformance probe server.

Read-only capability discovery only. This is NOT production code and is not
imported by the dispatcher. It exposes a single long-running tool that emits
``notifications/progress`` via the installed Python MCP SDK so we can measure
what the installed Codex client actually does with them.

Usage (never against production config)::

    python scripts/gate/gate7_progress_probe_server.py

Environment:
    G7_PROBE_LOG   path to append structured probe observations (JSONL)
    G7_PROBE_SECS  total tool duration in seconds (default 20)
    G7_PROBE_TICKS number of progress notifications to emit (default 10)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

from mcp.server import MCPServer
from mcp.server.mcpserver.context import Context

LOG = os.environ.get("G7_PROBE_LOG", "/tmp/g7-progress-probe.jsonl")
SECS = float(os.environ.get("G7_PROBE_SECS", "20"))
TICKS = int(os.environ.get("G7_PROBE_TICKS", "10"))


def log(event: str, **fields: object) -> None:
    rec = {"ts": time.time(), "event": event, **fields}
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(rec, default=repr) + "\n")
        handle.flush()


server = MCPServer(
    name="sol_claude_dispatcher",
    instructions=(
        "Disposable Gate 7 progress conformance probe. Call probe_long_task "
        "exactly once and report its returned text."
    ),
    version="0.0.0-probe",
)


@server.tool(
    name="probe_long_task",
    description=(
        "Blocking probe task that runs for a while and emits MCP progress "
        "notifications. Call this once, then report the returned text verbatim."
    ),
)
async def probe_long_task(label: str, ctx: Context) -> dict[str, object]:
    meta = None
    token = None
    try:
        rc = ctx.request_context
        meta = getattr(rc, "meta", None)
        for key in ("progressToken", "progress_token"):
            if token is not None:
                break
            token = getattr(meta, key, None)
            if token is None and isinstance(meta, dict):
                token = meta.get(key)
    except Exception as exc:  # pragma: no cover - probe only
        log("meta_error", error=repr(exc))

    log(
        "tool_called",
        label=label,
        meta=repr(meta),
        progress_token=repr(token),
        progress_token_present=token is not None,
        client_capabilities=repr(getattr(ctx, "client_capabilities", None)),
        protocol_version=repr(getattr(ctx, "protocol_version", None)),
    )

    interval = SECS / max(TICKS, 1)
    sent = 0
    errors = []
    for i in range(1, TICKS + 1):
        await asyncio.sleep(interval)
        msg = f"probe phase {i}/{TICKS}: worker active"
        try:
            await ctx.report_progress(progress=float(i), total=float(TICKS), message=msg)
            sent += 1
            log("progress_sent", n=i, message=msg)
        except Exception as exc:  # pragma: no cover - probe only
            errors.append(repr(exc))
            log("progress_error", n=i, error=repr(exc))

    log("tool_returning", progress_sent=sent, errors=errors)
    return {
        "probe": "gate7-progress",
        "label": label,
        "progress_token_present": token is not None,
        "progress_notifications_sent": sent,
        "progress_send_errors": errors,
        "answer": "PROBE_COMPLETE_SENTINEL",
    }


def main() -> None:
    log("server_start", argv=sys.argv, pid=os.getpid())
    server.run()


if __name__ == "__main__":
    main()
