#!/usr/bin/env python3
"""GATE 7 §18 positive-control client for the progress conformance probe.

Drives the probe server with the installed Python MCP SDK, requesting progress,
so we can prove the server side genuinely emits ``notifications/progress``.
Without this control, a negative Codex result would be uninterpretable.

Disposable discovery tooling. Not production code.
"""

from __future__ import annotations

import anyio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "gate7_progress_probe_server.py")

received: list[tuple[float, float | None, str | None]] = []


async def on_progress(progress: float, total: float | None, message: str | None) -> None:
    received.append((progress, total, message))
    print(f"  [client] progress {progress}/{total} :: {message}", flush=True)


async def main(with_token: bool) -> None:
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools], flush=True)
            kwargs = {}
            if with_token:
                kwargs["progress_callback"] = on_progress
            result = await session.call_tool(
                "probe_long_task", {"label": "positive-control"}, **kwargs
            )
            print("structured:", getattr(result, "structured_content", None), flush=True)
    print(f"RESULT: progress callbacks received = {len(received)}", flush=True)


if __name__ == "__main__":
    anyio.run(main, "--no-token" not in sys.argv)
