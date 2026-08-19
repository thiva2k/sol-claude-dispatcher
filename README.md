# sol-claude-dispatcher

A local MCP server that lets **Sol** (running on Codex) delegate
implementation work to **Claude Code workers**, and independent review to
**Fable**, without ever handing over orchestration or approval authority.

```text
                              USER
                               │
                               ▼
                    ┌─────────────────────┐
                    │  SOL (on Codex)     │   orchestrator, tech lead,
                    │                     │   final reviewer, sole holder
                    └──────────┬──────────┘   of "approved"
                               │
                               │  MCP over stdio (4 tools, no more)
                               ▼
                    ┌─────────────────────┐
                    │ sol-claude-dispatcher│  deterministic execution
                    │      (this repo)     │  and control layer —
                    └──────────┬──────────┘  contains no judgement
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
      ┌──────────────┐ ┌──────────────┐  ┌──────────────────┐
      │ Sonnet worker │ │ Opus worker  │  │  Fable reviewer   │
      │ implementation│ │ implementation│  │  read-only,       │
      │               │ │ (hard tasks) │  │  advisory verdict │
      └──────────────┘ └──────────────┘  └──────────────────┘
        isolated git       isolated git       cwd = worker's
        worktree           worktree           worktree, no writes
```

The dispatcher contains **no intelligence**. It is deterministic execution
plumbing: routing, subprocess control, state, git evidence, and policy
enforcement. The judgement lives in Sol. The final authority lives with the
human. See `docs/ARCHITECTURE.md` for the full module map and data flow.

## The distinction that matters most

Claude saying *"341 tests passed"* is a **claim**.
The dispatcher re-running `pytest -q` itself is **evidence**.

These are stored as separate types in separate fields — `worker_claims` and
`dispatcher_observations` — sharing zero field names, and the system never
merges them. Everything else here follows from taking that seriously.
Details: `docs/ARCHITECTURE.md` §4.

Three states that are never collapsed into one:

| State | Means |
|---|---|
| implementation complete | Claude stopped and returned a result |
| review complete | Sol has reviewed the implementation |
| user approved | the human accepted it |

The dispatcher can reach the first. It records the second. It can never
grant the third, and there is no `APPROVED` state in the machine — see
`docs/STATE-MACHINE.md`.

## Layout

```text
src/sol_claude_dispatcher/   the package — 4 MCP tools over 13 modules
schemas/                     JSON Schemas for structured worker/reviewer/proposal output
prompts/                     system-prompt policies appended to worker sessions
config/                      dispatcher.example.toml, empty-mcp.json
scripts/                     doctor, codex config generator, smoke tests, cleanup
docs/                        architecture, security, state machine, operations, phase-2 design
tests/                       unit, integration, fixtures, fake_bin
state/                       runtime task state (0700; contents git-ignored)
```

Docs:

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — module map, the four
  tools' data flow, the claims-vs-observations doctrine, hub-and-spoke,
  approval semantics
- [`docs/SECURITY.md`](docs/SECURITY.md) — the honest hard/policy boundary
  table and all 7 recursion-prevention layers mapped to code
- [`docs/STATE-MACHINE.md`](docs/STATE-MACHINE.md) — the 12 states, the
  full transition table, and why no off-ramp jumps straight back to `RUNNING`
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — running doctor, reading task
  state, the error taxonomy, cleanup, lock troubleshooting
- [`docs/PHASE2-OVERNIGHT-INTELLIGENCE.md`](docs/PHASE2-OVERNIGHT-INTELLIGENCE.md) —
  the (unbuilt) overnight-analysis design and its read-only law
- [`docs/INTERFACES.md`](docs/INTERFACES.md) — the exact contract every
  module was implemented against
- [`docs/DISCOVERY.md`](docs/DISCOVERY.md) — read-only environment findings
  from before anything was built

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
section, a repository root that does not exist, or `/` as a root will all
stop it from starting. That is deliberate: an unconfigured dispatcher must
not dispatch.

## Quickstart

```bash
scripts/doctor.sh              # 1. read-only diagnostic — nothing modified
scripts/smoke-test-fake.sh     # 2. full pytest suite against the fake binary
scripts/generate-codex-config.sh   # 3. PRINT the Codex MCP snippet (does not install it)
# 4. apply the printed snippet to ~/.codex/config.toml yourself, then restart Codex
scripts/smoke-test-live.sh     # 5. optional — costs real Claude usage, asks first
```

## Activation (brief §45)

Exact commands, in order. Steps 1–4 are safe to run yourself right now;
**step 5 is manual and intentionally not automated by anything in this
repository.**

1. **Inspect the dispatcher**
   ```bash
   .venv/bin/python -m compileall -q src
   .venv/bin/python -c "import sol_claude_dispatcher; print(sol_claude_dispatcher.__version__)"
   ```
2. **Run doctor**
   ```bash
   scripts/doctor.sh
   ```
3. **Run the fake-binary smoke tests**
   ```bash
   scripts/smoke-test-fake.sh
   ```
4. **Optionally run the live smoke test** (spends real Claude usage — it
   will ask for interactive confirmation, or refuse without a TTY unless
   `FORCE=1` is set):
   ```bash
   scripts/smoke-test-live.sh
   ```
5. **Add the MCP server to Codex** — manual, by design:
   ```bash
   scripts/generate-codex-config.sh
   ```
   prints the `[mcp_servers.sol_claude_dispatcher]` TOML block. Copy it into
   `~/.codex/config.toml` yourself, back the file up first, and preserve
   every other `[mcp_servers.*]` entry already there. **This step is never
   performed automatically by this project** — no script in `scripts/`
   writes to `~/.codex/config.toml`.

## Running the tests

```bash
.venv/bin/python -m pytest
```

Tests never spawn a real Claude or Codex process. The full suite (unit +
integration) runs against `tests/fake_bin/claude`, a scriptable,
deterministic, offline stand-in (`success`, `failure`, `timeout`, `hang`,
`malformed-json`, `scope-violation`, `blocked`, `resume`, `fable-review`
modes — see the file's own docstring).

## Safety boundaries

Some protections are hard-enforced by the OS or the CLI; others are policy
that a determined worker could in principle work around absent further OS
isolation. The difference is documented honestly, protection-by-protection,
in `docs/SECURITY.md` — this project does not pretend a prompt is a
sandbox.

**Hard:** isolated git worktree, MCP stripped from workers
(`--strict-mcp-config` + empty `mcp-config` + `mcp__*` denied,
non-configurably), subagent tools never granted, `SOL_WORKER=1` refuse-init,
dispatch-depth cap, resume cap, repository allowlist with symlink-resolved
ancestry checks, argv-only subprocess execution (never a shell), real-diff
scope inspection (including untracked files), process-group timeouts,
secret-stripped worker environment.

**Policy:** total network prohibition, preventing every conceivable shell
escape inside the worker's own `Bash` tool, preventing writes outside the
repository when the host OS permissions available to the worker process
would themselves allow it.

`bwrap` (bubblewrap) is present on this host as a documented **future**
optional hard-isolation mode — not a V1 dependency, and nothing here invokes
it yet. See `docs/SECURITY.md` §3.

## What this never does

No autonomous merging. No autonomous PR creation. No autonomous deployment.
No pushing. No overnight code modification — overnight analysis (§Phase 2,
unbuilt) is read-only by construction and cannot invoke
`dispatch_claude_task`/`resume_claude_task` even in principle; see
`docs/PHASE2-OVERNIGHT-INTELLIGENCE.md`. No agent-to-agent chat — information
flows hub-and-spoke through Sol, and Claude never calls Fable, Sol, or
another Claude (`docs/ARCHITECTURE.md` §5).
