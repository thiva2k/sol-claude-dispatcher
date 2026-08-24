"""TEST/DEVELOPMENT stdio harness. **Never** the registered production server.

Run it as::

    python -m sol_claude_dispatcher.dev_server /path/to/throwaway.toml

Why it exists
-------------

Live gates need a real MCP server process speaking real stdio against a
*disposable* configuration: a throwaway repository, a throwaway state
directory, and whatever feature flags the gate is proving. Before B4 they got
one by setting ``SOL_DISPATCHER_CONFIG`` and starting the production
entrypoint — which is precisely the mechanism that let a process-local
environment redirect the registered production server. The capability was real
and worth keeping; the entrypoint that carried it was the wrong one.

So the capability moved here, and it moved off the environment:

* the config path is a **required argv argument**, not an ambient variable —
  the harness reads no environment at all when choosing what to serve;
* :func:`~sol_claude_dispatcher.config_authority.assert_disposable_config`
  refuses the canonical production config, and refuses any config declaring a
  repository root that is, contains, or lies inside a root the production
  configuration authorises;
* it is **not** in ``[project.scripts]``, so no console script installs it, and
  it is **not** registered in ``~/.codex/config.toml``.

It is the same server object as production — ``build_server`` with the same
four tools — differing only in which configuration it is permitted to load. A
fifth tool is no more available here than there.

This module must not grow an environment-variable fallback. That would relocate
the B4 defect rather than fix it.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from .config_authority import assert_disposable_config
from .errors import DispatcherError

__all__ = ["main"]

USAGE = (
    "usage: python -m sol_claude_dispatcher.dev_server <config.toml>\n"
    "\n"
    "Disposable TEST/DEVELOPMENT MCP stdio server. The configuration path is\n"
    "required and is taken from argv; no environment variable selects it. The\n"
    "canonical production configuration and any config reaching a production\n"
    "repository are refused.\n"
)


def main(argv: list[str] | None = None) -> None:
    """Serve one disposable configuration over stdio, or refuse.

    Diagnostics go to **stderr**: stdout is the MCP JSON-RPC transport (§28),
    and a refusal that printed to stdout would corrupt a transport that should
    never have been opened in the first place.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] in {"-h", "--help"}:
        print(USAGE, file=sys.stderr)
        raise SystemExit(2)

    try:
        config_path = assert_disposable_config(Path(args[0]))
    except DispatcherError as exc:
        print(json.dumps(exc.to_payload()), file=sys.stderr)
        raise SystemExit(2) from exc

    # Imported here, not at module scope: the guard above must run before any
    # server machinery is constructed.
    from .server import build_server

    try:
        server = build_server(config_path)
    except DispatcherError as exc:
        print(json.dumps(exc.to_payload()), file=sys.stderr)
        raise SystemExit(2) from exc

    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    main()
