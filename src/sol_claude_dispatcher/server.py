"""The stdio MCP server (brief §6, §7). — Wave 4.

Exactly four tools, no more:

* ``dispatch_claude_task``     — create a new implementation worker (§7.1)
* ``resume_claude_task``       — continue an existing conversation (§7.2)
* ``review_task_with_fable``   — independent read-only review (§7.3)
* ``get_task``                 — read authoritative state, read-only (§7.4)

This layer contains no intelligence. It validates input, calls the deterministic
modules, and returns structured results. It never decides architecture, never
decides approval, and never invents a next action.

Transport is **stdio**. §28: application logging goes to stderr or a file, never
to stdout — stdout belongs to the MCP JSON-RPC transport, and a stray ``print``
corrupts the protocol.

SDK reality (see ``docs/DISCOVERY.md``) — mcp 2.0.0::

    from mcp.server import MCPServer          # NOT mcp.server.fastmcp
    server = MCPServer(name=..., instructions=..., version=...)

    @server.tool(name="dispatch_claude_task", description=...)
    async def dispatch(...) -> dict: ...

    server.run(transport="stdio")             # or: await server.run_stdio_async()

Startup refuses to initialise when ``SOL_WORKER=1`` is present in the
environment without the explicit internal test override (§22 layer 4).
"""

from __future__ import annotations

__all__ = ["SERVER_INSTRUCTIONS", "build_server", "main"]

#: §6 — the first thing Sol reads about this server.
SERVER_INSTRUCTIONS = """\
Sol is the sole orchestrator and final reviewer.
Use dispatch_claude_task for new implementation work.
Use resume_claude_task only to continue an existing implementation.
Use review_task_with_fable only for independent review.
Worker completion is evidence, never approval.
Workers must never delegate recursively.

This dispatcher is a deterministic execution and control layer. It makes no
architectural decisions, and it never marks work approved. Implementation
completion, review completion, and user approval are three distinct states and
must not be collapsed.
"""


def build_server(config_path: str | None = None) -> object:
    """Construct the configured ``MCPServer`` with the four tools registered."""
    raise NotImplementedError("Wave 4: implement per docs/INTERFACES.md §server")


def main() -> None:
    """Console-script entrypoint: build the server and run it over stdio."""
    raise NotImplementedError("Wave 4: implement per docs/INTERFACES.md §server")
