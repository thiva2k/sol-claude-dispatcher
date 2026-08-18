# sol-claude-dispatcher

A local MCP server that lets **Sol** (running on Codex) delegate implementation
work to **Claude Code workers**, and independent review to **Fable**, without
ever handing over orchestration or approval authority.

```
USER
 │
 ▼
SOL  — orchestrator / tech lead / final reviewer
 │  MCP (stdio)
 ▼
sol-claude-dispatcher
 ├── Sonnet worker ── implementation
 ├── Opus worker ──── difficult implementation
 └── Fable reviewer ─ independent read-only review
```

The dispatcher contains **no intelligence**. It is deterministic execution
plumbing: routing, subprocess control, state, git evidence, and policy
enforcement. The judgement lives in Sol. The final authority lives with the
human.

## The distinction that matters most

Claude saying *"341 tests passed"* is a **claim**.
The dispatcher re-running `pytest -q` itself is **evidence**.

These are stored as separate types in separate fields — `worker_claims` and
`dispatcher_observations` — and the system never merges them. Everything else
here follows from taking that seriously.

Three states that are never collapsed into one:

| State | Means |
|---|---|
| implementation complete | Claude stopped and returned a result |
| review complete | Sol has reviewed the implementation |
| user approved | the human accepted it |

The dispatcher can reach the first. It records the second. It can never grant
the third, and there is no `APPROVED` state in the machine.

## Status

**V1 foundation, under construction.** Built so far:

- `models.py` — the full type contract
- `errors.py` — typed error taxonomy
- `config.py` — fail-closed TOML configuration
- JSON schemas, worker/reviewer policies, project skeleton

Still to come: router, state store, locks, git layer, security layer, runner,
sessions, results parsing, validation, and the MCP server itself. See
`docs/INTERFACES.md` for the contract every remaining module is written
against.

Autonomous overnight code modification is **explicitly out of scope**. The
design for it lives in `docs/PHASE2-OVERNIGHT-INTELLIGENCE.md`, and its
defining property is that overnight analysis is read-only and cannot dispatch
anything.

## Layout

```
src/sol_claude_dispatcher/   the package (see docs/INTERFACES.md)
schemas/                     JSON Schemas for structured worker/reviewer output
prompts/                     system-prompt policies appended to worker sessions
config/                      dispatcher.example.toml, empty-mcp.json
scripts/                     doctor, codex config generator, smoke tests
docs/                        architecture, security, state machine, operations
tests/                       unit, integration, fixtures, fake_bin
state/                       runtime task state (0700; contents git-ignored)
```

## Setup

```bash
cd ~/sol-claude-dispatcher
python3 -m venv .venv                 # or: uv venv
.venv/bin/python -m pip install -e ".[dev]"

cp config/dispatcher.example.toml config/dispatcher.toml
# then edit [security].allowed_repository_roots — the example ships with a
# "/CONFIGURE/ME" placeholder and REFUSES TO LOAD until you replace it.
```

The dispatcher fails closed on configuration. An unknown key, a missing
section, a repository root that does not exist, or `/` as a root will all stop
it from starting. That is deliberate: an unconfigured dispatcher must not
dispatch.

## Running the tests

```bash
.venv/bin/python -m pytest
```

Tests never spawn a real Claude or Codex process. Integration tests run against
`tests/fake_bin/claude`, a scriptable stand-in.

## Safety boundaries

Some protections are hard-enforced by the operating system or the CLI; others
are policy that a determined worker could talk its way around. The difference
is documented honestly in `docs/SECURITY.md` — this project does not pretend a
prompt is a sandbox.

**Hard:** isolated git worktree, MCP servers stripped
(`--strict-mcp-config` + empty config + `mcp__*` denied), subagent tools not
granted, dispatcher depth checks, repository allowlist with symlink-resolved
ancestry checks, argv-only subprocess execution, changed-path inspection
against the real diff, process-group timeouts.

**Policy:** total network prohibition, preventing every conceivable shell
escape, preventing writes outside the repository when the host process itself
has permission.

## What this never does

No autonomous merging. No autonomous PR creation. No autonomous deployment. No
pushing. No overnight code modification. No agent-to-agent chat — information
flows hub-and-spoke through Sol, and Claude never calls Fable, Sol, or another
Claude.
