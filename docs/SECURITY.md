# SECURITY

§23 of the build brief is blunt: "Do not pretend prompts equal sandboxing."
This document draws the line explicitly. Every protection below is labeled
**HARD** (enforced by the OS, the CLI, or code that a worker process cannot
override from inside its own session) or **POLICY** (enforced by
configuration, tool restriction, or written instruction that a sufficiently
determined or confused worker could in principle work around, absent
further OS-level isolation).

Read `CLAUDE.md` §5 first: "Prompts are not sandboxing." That rule governs
how this document is written, not just what it says.

---

## 1. Honest boundary table

| Protection | Enforcement | Why it's in that column |
|---|---|---|
| Isolated git worktree per task | **HARD** | `--worktree <name>` creates a separate working directory; a worker's file writes land there, not in the primary tree. The dispatcher independently confirms this with `git.primary_tree_status()` after every run — it does not merely trust that the flag worked. |
| MCP stripped from workers | **HARD** | Three independent mechanisms stacked: `--strict-mcp-config`, `--mcp-config` pointed at `config/empty-mcp.json` (`{"mcpServers": {}}`), and `mcp__*` in `ALWAYS_DISALLOWED_TOOLS` (`runner.py`) — non-configurable, appended regardless of what `config/dispatcher.toml` says. A worker has no MCP server to call even if every other layer failed. |
| Omitted tools | **HARD** | `config.claude.worker_tools` is an allow-list, not a deny-list: `Agent`/`Task`/`Subagent` are simply never in it, and `runner._assert_invocation_sane()` raises `InternalDispatcherError` if a caller ever tries to grant one (§22 layer 2). A tool that was never granted cannot be invoked regardless of what the prompt says. |
| `SOL_WORKER` refuse-init | **HARD** | `security.assert_no_recursion()` raises `RecursionDetected` whenever `SOL_WORKER=1` is present in the environment, called at server startup and at the top of every dispatch/resume tool. This is a process-environment check, not a request the worker could decline. |
| Depth cap | **HARD** | `security.assert_dispatch_depth()` compares `dispatch_depth` against `config.security.max_dispatch_depth` (fixed at ≤1 by `SecuritySettings`, `ge=0, le=1` — the config schema itself refuses a value above 1). Persisted in `TaskEnvelope.lineage.dispatch_depth`, not caller-suppliable per request. |
| Repository allowlist with resolved-ancestry | **HARD** | `security.validate_repository_root()` resolves symlinks and `..` (`Path.resolve()`) *before* comparing against `config.security.allowed_repository_roots`, using `path == root or root in path.parents` — never a string `startswith`. A symlink inside an allowed root pointing outside it is rejected because it was already resolved away before the comparison ran. |
| argv, never shell | **HARD** | Every subprocess in `runner.py`, `git.py`, and `validation.py` is `asyncio.create_subprocess_exec` / `subprocess.run` with an argv **list**. `shell=True` and interpolated command strings do not appear anywhere in the codebase — a worker cannot smuggle a second command through shell metacharacters in an argument, because there is no shell parsing the argument. |
| Scope inspection | **HARD** | `git.check_scope()` runs against the *real* `git diff`/`git status`/`git ls-files --others` output of the worktree — including untracked files, so a worker cannot add a new unauthorized file and have it slip past because it was never staged. This is a measurement, not something the worker's report can influence (§16). |
| Process-group timeout | **HARD** | `start_new_session=True` gives the worker its own process group; on timeout the dispatcher signals the whole group (`SIGTERM` → grace → `SIGKILL`), so a worker that spawns children cannot outlive its own termination by hiding work in a subprocess. |
| Secret-stripped worker env | **HARD** | `security.worker_environment()` drops every variable whose name matches a `SECRET_ENV_MARKERS` substring (`TOKEN`, `API_KEY`, `SECRET`, `PASSWORD`, `PRIVATE_KEY`, `CREDENTIAL`, `COOKIE`, `AUTHORIZATION`, …) and every `SOL_DISPATCHER_*` key, unconditionally, before a worker process is ever spawned. The dispatcher does not read, log, or forward Anthropic credentials at all — the Claude CLI manages its own auth. |
| Non-configurable `ALWAYS_DISALLOWED_TOOLS` | **HARD** | `runner.ALWAYS_DISALLOWED_TOOLS = ("mcp__*", "Agent", "Task", "Bash(claude:*)", "Bash(codex:*)")` is a Python constant, appended to whatever `config.claude.disallowed_tools` says (`_deduped(config.claude.disallowed_tools, ALWAYS_DISALLOWED_TOOLS)`). An operator cannot misconfigure these away — editing `dispatcher.toml` cannot remove them. |
| Total network prohibition | **POLICY** | `security.allow_network` is a config flag consulted by policy/prompt, not an actual firewall or network namespace. A worker process on this host has the same network reachability as any other process the operating user can run, unless an operator adds OS-level network isolation themselves. |
| Shell-escape completeness | **POLICY** | The dispatcher never builds a shell string, so *it* cannot be tricked by shell metacharacters. But the worker is still granted a real `Bash` tool inside its worktree (minus the specific `disallowed_tools` patterns like `Bash(git push:*)`); the pattern-based deny list is necessarily a finite enumeration and cannot claim to anticipate every command a worker could type inside its own shell tool. |
| Writes outside the repository, given host permissions | **POLICY** | Everything above constrains *where the dispatcher looks* (the worktree, the scope check) and *what git tools report*. If the host OS permissions available to the worker process would allow writing somewhere outside the repository entirely (e.g. `/tmp`, a world-writable path, another directory the same Unix user owns), nothing here is a filesystem sandbox that would stop that write from happening — it would simply not show up in `git diff` and would not be reported as part of the task's evidence. |

---

## 2. Recursion defense — all 7 layers (§22)

| Layer | Defense | Implementation site |
|---|---|---|
| 1 | MCP isolation — worker gets no MCP servers at all | `runner.build_worker_invocation()` sets `mcp_config_path=config.empty_mcp_file` and always includes `--strict-mcp-config`; `runner.build_argv()` emits `--mcp-config <path>`; `ALWAYS_DISALLOWED_TOOLS` includes `"mcp__*"`. Config: `config/empty-mcp.json` = `{"mcpServers": {}}`. |
| 2 | No subagents — worker tool set excludes Agent/Task | `config.ClaudeSettings.worker_tools` (and `reviewer_tools`) simply never lists `Agent`/`Task`/`Subagent`; `runner.SUBAGENT_TOOL_NAMES = ("Agent", "Task", "Subagent")` and `runner._assert_invocation_sane()` raises `InternalDispatcherError` if any invocation is ever built with one of them in `tools`, so a future config or call-site bug fails loudly instead of silently granting the capability. |
| 3 | No child orchestrators — worker cannot start `codex`/`claude` | `runner.ALWAYS_DISALLOWED_TOOLS` includes `"Bash(claude:*)"` and `"Bash(codex:*)"`, unconditionally appended regardless of config. Reinforced at the policy layer: `prompts/worker-policy.md` explicitly lists "invoke Codex" and "invoke another Claude session" under "What you may not do." |
| 4 | Environment markers + startup refusal | `security.worker_environment()` sets `SOL_WORKER=1`, `SOL_DISPATCH_DEPTH=str(depth+1)`, `SOL_TASK_ID=<id>` on every worker's environment. `security.assert_no_recursion()` raises `RecursionDetected` whenever the *dispatcher's own* environment carries `SOL_WORKER=1` (i.e., it is itself running inside a worker) — called from `server.main()` at startup and required at the top of the dispatch/resume tool bodies. Escape hatch: `SOL_DISPATCHER_TEST_OVERRIDE=1`, used only by this project's own test suite. |
| 5 | Depth cap | `TaskEnvelope.lineage.dispatch_depth`, persisted per task. `security.assert_dispatch_depth(depth, config)` raises `RecursionDetected` if `depth > config.security.max_dispatch_depth`. `SecuritySettings.max_dispatch_depth` is itself constrained to `0 ≤ n ≤ 1` at config-parse time (`Field(default=1, ge=0, le=1)`) — V1 cannot even be configured to allow depth 2. |
| 6 | Resume cap | `sessions.assert_resume_allowed()` raises `ResumeLimitReached` once `record.resume_count >= envelope.execution.max_resume_count` (default 4). Checked exactly once, at the `RESUME_REQUESTED` transition boundary — see `docs/STATE-MACHINE.md` §5 for why the state machine's shape guarantees this is the only place it needs to be checked. |
| 7 | No dispatcher credentials forwarded | `security.worker_environment()` strips every `SECRET_ENV_MARKERS`-matching key and every `SOL_DISPATCHER_*` key from the base environment before building the worker's environment; it also never synthesizes or copies an Anthropic credential into that environment in the first place. |

Layers 1–3 remove the *capability* to recurse (no MCP tool exists to call, no
subagent tool exists to spawn one, no shell pattern exists to launch a
sibling orchestrator). Layers 4–6 are the *belt-and-braces* checks that fire
even if a capability leak occurred anyway — process ancestry, depth
counting, and a hard resume ceiling. Layer 7 denies a compromised worker the
one thing that would make a leaked capability dangerous: dispatcher-level
credentials.

---

## 3. Future optional hard-isolation mode

`bwrap` (bubblewrap) is present on this host (`/usr/bin/bwrap`, confirmed in
`docs/DISCOVERY.md` Phase A). It is **not a V1 dependency** and nothing in
this codebase invokes it. It is documented here only because §23 asks for
the option to be named: a future version could wrap `runner.run_worker`'s
subprocess launch in a `bwrap` sandbox (mount namespace restricted to the
worktree, network namespace disabled) to convert the two POLICY rows above —
network prohibition and writes outside the repository — into HARD ones. That
would need its own design and test pass before being wired in; it must not
be added in a way that disturbs the existing argv-based invocation path or
any of the seven recursion-prevention layers above.
