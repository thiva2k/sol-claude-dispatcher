# Phase A — Environment Discovery (read-only)

Recorded 2026-08-18 on the build VPS. Every command below was read-only; no
config, session, or installed tool was modified.

## Toolchain

| Thing | Location | Version |
|---|---|---|
| Python | `/usr/bin/python3` | 3.12.3 |
| git | `/usr/bin/git` | 2.43.0 |
| Claude Code CLI | `/home/dev/.nvm/versions/node/v24.18.0/bin/claude` | 2.1.234 |
| Codex CLI | `/home/dev/.local/bin/codex` | codex-cli 0.147.0 |
| `uv` | — | **not installed** |
| `pip3` | `/usr/bin/pip3` | present |
| `bwrap` (bubblewrap) | `/usr/bin/bwrap` | present (future hard-isolation option, §23 — not a V1 dependency) |

Python 3.12 means `tomllib` is in the stdlib — no `tomli` dependency needed for
config parsing.

## Python environment

Nothing relevant is installed globally: `mcp`, `pydantic`, and `pytest` were all
absent from the system interpreter. Nothing was installed globally by this build
(§4: "Do not install global Python packages").

`uv` is unavailable, so per §4 we fell back to `python3 -m venv .venv` inside the
project. PyPI is reachable from this host (HTTP 200 on `pypi.org/simple/mcp/`),
so the venv was populated with pip.

Installed into `/home/dev/sol-claude-dispatcher/.venv` only:

```
mcp             2.0.0
pydantic        2.13.4
pytest          9.1.1
pytest-asyncio  1.4.0
```

## MCP SDK v2 surface (verified by introspection)

`from mcp.server import MCPServer` works exactly as the brief predicted (§4).
Notes for the MCP-layer implementer:

- **`mcp.server.fastmcp` does not exist in SDK v2.** `FastMCP` was folded into
  `MCPServer`. Do not write `from mcp.server.fastmcp import FastMCP`.
- `MCPServer(name=..., instructions=..., version=...)` — `instructions` is the
  parameter that carries the §6 hierarchy text.
- Tool registration: `@server.tool(name=..., description=..., structured_output=...)`
  decorator, or `server.add_tool(...)`.
- Transport: `server.run(transport="stdio")` (sync) or
  `await server.run_stdio_async()`. stdio is what we ship (§4).
- Also available on the class: `list_tools`, `call_tool`, `remove_tool`,
  `custom_route`, `middleware`, `lifespan` — none needed for V1.

## Claude Code CLI flag reality check (IMPORTANT — two deltas from the brief)

The brief's §11 sketch of the worker argv was written against an assumed CLI.
Verified against `claude --help` on 2.1.234:

Present and usable as described:
`-p/--print`, `--model`, `--session-id <uuid>`, `-r/--resume [value]`,
`-w/--worktree [name]`, `--output-format json`, `--json-schema <schema>`,
`--permission-mode auto`, `--strict-mcp-config`, `--mcp-config <files...>`,
`--disallowedTools`, `--allowedTools`, `--tools <tools...>`,
`--max-budget-usd`, `--add-dir`, `--settings`, `--fork-session`,
`--no-session-persistence`.

**Delta 1 — `--max-turns` does not exist on this CLI.** There is no turn-cap
flag. `max_turns` therefore stays in the task envelope as recorded policy, but
the runner must NOT emit it as argv on this version. Runaway bounds in V1 come
from the dispatcher timeout (§20) and optionally `--max-budget-usd`. The runner
should hold a capability map so the flag can be re-enabled when the CLI grows
it, rather than hard-coding its absence.

**Delta 2 — `--append-system-prompt` takes an inline string, not a path.**
The documented option is `--append-system-prompt <prompt>`. A
`--append-system-prompt-file` spelling appears only inside the `--bare` help
text and is not listed as its own option, so we do not rely on it. The
dispatcher reads `prompts/worker-policy.md` itself and passes the contents
inline. This is also the more testable path: the exact policy text becomes
visible in the recorded argv.

**Delta 2a — the inline string has a hard size cliff (BLOCKER B1).** Because it
is one argv element, Linux applies `MAX_ARG_STRLEN` to it: **131,071 bytes**,
measured by bisection against `/bin/true` on this host during Gate 4.5's live
gate. Above it `execve` fails with `E2BIG`; the worker never starts. Measured
live: 128,992 bytes launched and answered with **nothing truncated**; 144,486
bytes could not launch at all. The dispatcher's V1 ceiling is therefore
**122,880 bytes (120 KiB) of UTF-8** on the final composed value, enforced
before spawn (`ContextTooLarge`), with the raw `E2BIG` translated to the same
typed error as defence in depth. See `docs/INTERFACES.md` and
`src/sol_claude_dispatcher/config.py`.

**Re-checked on the installed CLI 2.1.237 (2026-08-21, read-only `claude
--help`): `--append-system-prompt-file` still does NOT exist as its own
option.** `--append-system-prompt <prompt>` and `--system-prompt <prompt>` are
each listed; neither `-file` variant has an entry anywhere in the 242-line help
output. The only occurrence of the spelling is inside the `--bare` description,
`"--system-prompt[-file], --append-system-prompt[-file], --add-dir"`, which
hints at a hidden or aliased flag but proves nothing. Lane C's original finding
stands.

**Follow-up design item — DO NOT IMPLEMENT WITHOUT COMMISSIONING.** A
file-based system-prompt transport is the preferred way to remove the
single-argv limit while preserving the default system prompt. It is recorded
here, not built. A future commissioning must prove, at minimum: the installed
CLI actually supports the flag (the datum above says it is undocumented today);
a 0600 prompt file written atomically; a dispatcher-owned contained path; no
symlink substitution between write and exec; an exact content hash carried into
the run record; resume integrity (the resumed turn gets the same bytes);
worker/Fable parity; cleanup and retention semantics; no prompt content exposed
through argv; and one live invocation above 131 KiB that actually succeeds.
Until every one of those is proven, inline transport plus the 122,880-byte
ceiling is the contract.

`--permission-mode` accepts: `acceptEdits`, `auto`, `bypassPermissions`,
`manual`, `dontAsk`, `plan`. `auto` (as the brief specifies) is valid.

**Delta 3 — `--safe-mode` exists (2.1.237) and is now emitted.** The installed
CLI is 2.1.237, three patch versions past the 2.1.234 this document and the
`CLI_CAPABILITIES` docstring are otherwise pinned to (the drift note is
deliberate; Gate 4.5 did not repin the rest of this document). Verified live in
combination with the dispatcher's full argv (raw evidence:
`SAFEMODE-COMBINED-PROBE.txt`). It starts the child with all customizations
(`CLAUDE.md`, skills, plugins, hooks, MCP servers, custom commands/agents,
output styles, workflows, custom themes, keybindings) disabled and sets
`CLAUDE_CODE_SAFE_MODE=1`. Gated behind `CLI_CAPABILITIES["safe_mode"]`, and
currently emitted unconditionally for worker, Fable, and resume invocations
alike. Do **not** substitute `--bare`: its own help text states Skills still
resolve via `/skill-name`, so it is never emitted by this dispatcher.

## Existing-system state (untouched, existence only)

- `~/.codex/config.toml` exists (880 bytes, mode 0600). **Not read, not
  modified.** The Codex snippet is generated for the user to apply by hand (§21).
- `~/.claude/settings.json` exists (2990 bytes). **Not read, not modified.**
- No Codex or Claude session state was inspected, listed, or altered.
- No `claude -p` or `codex` child process was spawned by this build (§2, §32).

## Project location

`/home/dev/sol-claude-dispatcher` did not exist before this build; it was
created fresh and `git init`-ed with no remote (§3).
