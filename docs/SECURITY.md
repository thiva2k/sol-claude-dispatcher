# SECURITY

§23 of the build brief is blunt: "Do not pretend prompts equal sandboxing."
This document draws the line explicitly. Every protection below is labeled
**HARD** (enforced by the OS, the CLI, or code that a worker process cannot
override from inside its own session) or **POLICY** (enforced by
configuration, tool restriction, written instruction, or after-the-fact
detection that a sufficiently determined or confused worker could in principle
work around, absent further OS-level isolation).

Read `CLAUDE.md` §5 first: "Prompts are not sandboxing." That rule governs
how this document is written, not just what it says.

A protection that only *detects* a violation after it has happened is
**POLICY**, not HARD, however reliable the detection is. Detection is worth
having — it is what turns "we hope the worker behaved" into "we measured
whether it did" — but it is not containment, and this document does not let
the two share a column.

---

## 1. Honest boundary table

| Protection | Enforcement | Why it's in that column |
|---|---|---|
| Isolated git worktree per task | **HARD** *(that the worktree exists and is separate)* / **POLICY** *(that the worker stays in it)* | `--worktree <name>` genuinely creates a separate working directory and the worker's `cwd` is that directory, so its ordinary edits land there and the dispatcher's diff is taken against it. That much is real and non-negotiable. It is **not** a filesystem barrier: a worker holding a `Bash` tool can name an absolute path outside the worktree, and nothing here refuses the write. The dispatcher's answer to that is *detection* after the fact (see the primary-tree row), never containment. Do not read "isolated worktree" as "the primary tree is protected". |
| MCP stripped from workers | **HARD** | Three independent mechanisms stacked: `--strict-mcp-config`, `--mcp-config` pointed at `config/empty-mcp.json` (`{"mcpServers": {}}`), and `mcp__*` in `ALWAYS_DISALLOWED_TOOLS` (`runner.py`) — non-configurable, appended regardless of what `config/dispatcher.toml` says. A worker has no MCP server to call even if every other layer failed. |
| Omitted tools | **HARD** | `config.claude.worker_tools` is an allow-list, not a deny-list: `Agent`/`Task`/`Subagent` are simply never in it, and `runner._assert_invocation_sane()` raises `InternalDispatcherError` if a caller ever tries to grant one (§22 layer 2). A tool that was never granted cannot be invoked regardless of what the prompt says. |
| `SOL_WORKER` refuse-init | **HARD** | `security.assert_no_recursion()` raises `RecursionDetected` whenever `SOL_WORKER=1` is present in the environment, called at server startup and at the top of every dispatch/resume tool. This is a process-environment check, not a request the worker could decline. |
| Depth cap | **HARD** | `security.assert_dispatch_depth()` compares `dispatch_depth` against `config.security.max_dispatch_depth` (fixed at ≤1 by `SecuritySettings`, `ge=0, le=1` — the config schema itself refuses a value above 1). Persisted in `TaskEnvelope.lineage.dispatch_depth`, not caller-suppliable per request. |
| **Repository identity is the exact git top level** | **HARD** | `security.validate_repository_root()` resolves symlinks and `..`, then asks *git itself* (`git rev-parse --show-toplevel`, argv, never a shell) which repository the path belongs to, and requires the resolved path to **be** that top level and to be **exactly equal** to a configured entry in `[security].allowed_repository_roots`. No ancestry matching, no string prefixes. See §1.1 — this is a behaviour change operators will notice. |
| **Task-id containment, at two independent layers** | **HARD** | `security.validate_task_id()` accepts only a canonical lowercase hyphenated UUID and is called at every MCP entry point that takes a caller-supplied id (`get_task`, `resume_claude_task`, `review_task_with_fable`). Independently, `TaskStore` re-derives and **resolves** every path it is about to read or write and refuses anything that does not land inside `state/tasks/`, so a call site that forgot the validator still cannot escape the state root. Neither layer depends on the other having run. |
| **Git evidence fails closed** | **HARD** | Every authoritative git command (`status --porcelain`, `diff --name-only`, `diff --stat`, `diff`, `diff --check`, `ls-files --others --exclude-standard`) has explicit success/failure handling. A failure, a timeout, a missing `git` binary, or unusable output raises `GitEvidenceCollectionFailed` and the task lands in an explicit failure state with diagnostics preserved. "git could not tell us" is never rendered as `changed_paths=[] / scope_valid=true`. `git.py` also strips `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_CEILING_DIRECTORIES` and `GIT_NAMESPACE` from every git invocation, so an inherited environment cannot redirect an answer. |
| argv, never shell | **HARD** | Every subprocess in `runner.py`, `git.py`, and `validation.py` is `asyncio.create_subprocess_exec` / `subprocess.run` with an argv **list**. `shell=True` and interpolated command strings do not appear anywhere in the codebase — a worker cannot smuggle a second command through shell metacharacters in an argument, because there is no shell parsing the argument. |
| Scope inspection | **HARD** | `git.check_scope()` runs against the *real* `git diff`/`git status`/`git ls-files --others` output of the worktree — including untracked files, so a worker cannot add a new unauthorized file and have it slip past because it was never staged. This is a measurement, not something the worker's report can influence (§16). The measurement is taken on the **final** state of the worktree; see §1.3. |
| Process-group timeout | **HARD** | `start_new_session=True` gives the worker its own process group; on timeout the dispatcher signals the whole group (`SIGTERM` → grace → `SIGKILL`), so a worker that spawns children cannot outlive its own termination by hiding work in a subprocess. |
| Secret-stripped worker env | **HARD** | `security.worker_environment()` drops every variable whose name matches a `SECRET_ENV_MARKERS` substring (`TOKEN`, `API_KEY`, `APIKEY`, `AUTHORIZATION`, `COOKIE`, `SECRET`, `PASSWORD`, `PRIVATE_KEY`, `CREDENTIAL`) and every `SOL_DISPATCHER_*` key, unconditionally, before a worker process is ever spawned. The dispatcher does not read, log, or forward Anthropic credentials at all — the Claude CLI manages its own auth. |
| **Secret-stripped validation env** | **HARD** | Dispatcher-run validation commands are a second spawn path and used to inherit the dispatcher's entire environment. `validation.validation_environment()` now applies the same stripping policy (sharing `SECRET_ENV_MARKERS` with `security.py` so the list has one definition), and `env=None` *means* "build a sanitized environment", never "inherit". It deliberately does **not** set `SOL_WORKER`: a validation command is dispatcher-run, and mislabelling its provenance is exactly the confusion §16 exists to prevent. Scope caveat in §1.4. |
| **Core deny set is non-configurable** | **HARD** *(in one specific sense — read the next row)* | `runner.ALWAYS_DISALLOWED_TOOLS` = `("mcp__*", "Agent", "Task", "Bash(claude:*)", "Bash(codex:*)")` **+** `CORE_DENIED_GIT_OPERATIONS` = `Bash(git push:*)`, `Bash(git merge:*)`, `Bash(git rebase:*)`, `Bash(git commit:*)`, `Bash(git reset:*)`, `Bash(git clean:*)`, `Bash(git worktree:*)`. Both builders append them unconditionally via `_deduped(config.claude.disallowed_tools, ALWAYS_DISALLOWED_TOOLS)`, and `_assert_invocation_sane()` refuses to build argv for an invocation missing any of them. **Operator configuration may ADD deny rules; it can never REMOVE one of these.** Editing `dispatcher.toml` — even to `disallowed_tools = []` — changes nothing about this set. |
| What a deny pattern actually is | **POLICY** | A deny pattern is a **prefix match on the Bash command text**, performed by the Claude CLI's own permission engine. It does not resolve the executable, so an absolute path, a wrapper script, `env git …`, or an alias is not covered by it. It is not an exec-level restriction and it is not an OS boundary. What actually *detects* a prohibited mutation is the post-run evidence: the diff/scope checks and the primary-tree comparison. Two separate claims, deliberately split across two rows: *the set cannot be configured away* (HARD) and *the set is not a complete enumeration of ways to run git* (POLICY). |
| **Fable review holds the exclusive repository lock** | **HARD** | `review_task_with_fable` acquires the same `fcntl.flock(LOCK_EX \| LOCK_NB)` on the same canonical identity that dispatch and resume use, before it reads any evidence, and releases it in a `finally` covering the whole snapshot (evidence read, prompt build, reviewer process, run recording, review append, transition). A review of a repository a worker is mutating is refused with `RepositoryBusy`; so is a resume during a review. This is a filesystem lock, not advice. Operational consequence in §1.5. |
| **Primary-tree non-interference** | **POLICY** — *detection, not containment* | The dispatcher fingerprints the primary tree (HEAD commit + full `git status --porcelain`) **before** the worker starts, writes that baseline to `evidence/primary-tree-before.txt` immediately, and compares it afterwards. The invariant is `post_state == pre_state` — **not** "the tree started clean", so an ordinary developer's dirty checkout is not a violation. Divergence lands `POLICY_VIOLATION` and can never reach `AWAITING_SOL_REVIEW`. Read §1.2 for the honest limitation; it is a limitation, not a caveat. |
| Total network prohibition | **POLICY** | `constraints.allow_network` is a config/envelope flag consulted by policy and rendered into the worker prompt, not a firewall or a network namespace. A worker process on this host has the same network reachability as any other process the operating user can run, unless an operator adds OS-level network isolation themselves. |
| Shell-escape completeness | **POLICY** | The dispatcher never builds a shell string, so *it* cannot be tricked by shell metacharacters. But the worker is granted a real `Bash` tool inside its worktree, and a pattern-based deny list is necessarily a finite enumeration; it cannot claim to anticipate every command a worker could type inside its own shell tool. |
| Writes outside the repository, given host permissions | **POLICY** | Everything above constrains *where the dispatcher looks* and *what git reports*. If the host OS permissions available to the worker process would allow writing somewhere outside the repository entirely (`/tmp`, a world-writable path, another directory the same Unix user owns), nothing here is a filesystem sandbox that would stop that write. It would simply not appear in `git diff` and would not be part of the task's evidence. |

### 1.1 Repository identity: allowlisting a parent no longer authorises what is inside it

The historical check accepted `path == root or root in path.parents`, so an
allowlist entry of `/srv/app` authorised `/srv/app/src`. That was not merely
loose: `canonical_root` is the value used for the repository **lock**, for
worktree lookup, for evidence collection, and as the worker's `cwd`.
Dispatching once against `/srv/app` and once against `/srv/app/src` produced
**two different lock files for one working tree**, so "exactly one mutating
worker per repository" did not actually hold.

Post-remediation:

* every repository must be listed by its **exact git top-level path** in
  `[security].allowed_repository_roots`;
* a request naming a **subdirectory** of an allowed repository is refused with
  `InvalidRepository`, with a remediation pointing at `[scope].allowed_paths`
  (scoping a task to a subdirectory is a scope question, not an identity one);
* a **linked worktree** is its own top level and needs its own entry;
* trailing slashes, `..` segments and symlink aliases all canonicalise to the
  same root and therefore to the same lock.

Operators upgrading from a pre-remediation config will see
`RepositoryNotAllowed` on a config that used to work. The fix is to list the
repositories, not to widen the check.

### 1.2 The primary-tree check is detection, not containment

> The primary-tree non-interference check is **detection, not containment**.
> The dispatcher fingerprints the primary tree before the worker starts and
> compares afterwards. A worker that modifies a file and restores it before
> exiting is not detected. A change to a git-ignored file is not detected,
> because `git status --porcelain` does not report one. A change made and
> reverted between two runs is not detected. Nothing here *prevents* a worker
> from writing outside its worktree — it only makes the common cases visible
> after the fact. Without OS-level sandboxing (the preserved Bubblewrap
> extension point, §3) this is not a sandbox, and it must not be described as
> one.

The same text is embedded in every `evidence/primary-tree-invariant.json` the
dispatcher writes, so the limitation travels with the evidence rather than
living only here.

What it *does* catch — and "catch" here means *notice afterwards*, never
*stop* — because the fingerprint is HEAD **and** porcelain status together: a
modification, a deletion, an untracked addition, a staged change, a checkout,
and a commit, each of them still present in the tree when the run ends.
`status` alone cannot see a commit; `HEAD` alone cannot see a working-tree
edit. None of this narrows the limitation above: an interference that has been
undone by the time evidence is collected leaves no trace for either half of the
fingerprint, and a git-ignored path is outside what `git status --porcelain`
reports at all.

Divergence is reported as `policy_violations` entries prefixed
`primary_tree_head:`, `primary_tree_appeared:` and
`primary_tree_disappeared:`, and as the typed observation
`DispatcherObservations.primary_tree_unchanged`. That field is the invariant
verdict; `primary_worktree_clean` is a *different* and deliberately literal
measurement ("the primary tree has no uncommitted changes right now"), and an
already-dirty tree makes it `False` without being a violation.

If the primary tree cannot be fingerprinted at all, the run fails closed
(`GitEvidenceCollectionFailed`) rather than being read as unchanged.

### 1.3 The scope decision is taken on post-validation state

Evidence is collected in two phases:

* **Phase A** — immediately after the worker exits, persisted as
  `evidence/pre-validation-{changed-paths.json,status.txt,diff-stat.txt}`
  *before* a single validation command runs;
* **Phase B** — after the dispatcher's own validation commands have run
  (skipped, and equal to A by construction, when none ran).

The authoritative scope and policy decision uses the **final** state, because
that is what is actually on disk. The consequence an operator must know: a
dispatcher validation command that writes outside the task's declared scope
will land the task in `POLICY_VIOLATION`. The record attributes it —
`evidence/evidence-phases.json` and the tool response's
`evidence_attribution` carry `worker_changed_paths`, `final_changed_paths`,
`validation_added_paths`, `validation_removed_paths` — so Sol must read the
attribution before blaming the worker, and the Fable prompt names
dispatcher-generated paths explicitly so the reviewer does not raise findings
against the worker for them. Set difference cannot separate authorship of a
single path both touched; that caveat is recorded in the artefact rather than
glossed. Keep validation commands inside the task's scope.

### 1.4 What the sanitized validation environment is not

Environment hygiene, not a sandbox. A validation command still runs as the same
Unix user, with the same filesystem and network reach, executing
repository-controlled code that the worker may have just written. It can read
any secret that lives on disk rather than in the environment. What is
guaranteed is only that the dispatcher does not *hand* it one.

### 1.5 Worker output retention

Per stream, the dispatcher retains the first and last 1 MB in memory, with an
explicit in-band marker naming the exact number of omitted bytes, plus
`WorkerRun.stdout_truncated` / `stderr_truncated` and exact
`stdout_total_bytes` / `stderr_total_bytes` (surfaced on `RunMetadata`). The
**complete** stream is streamed to `runs/NNN/stdout.raw` and
`runs/NNN/stderr.log` at `0600`; stderr is redacted line-by-line on the way to
disk. When stdout is truncated, the trailing structured JSON document is
recovered by a real `json.loads` over bounded trailing-line candidates — never
a regex scrape — so the dispatcher never reports "no structured output" because
of its own cap. A bounded excerpt is never presented as a complete stream.

### 1.6 Operational consequence of the review lock

A Fable review holds the repository's exclusive lock for its entire duration,
including the reviewer subprocess. **A long Fable review therefore blocks
`dispatch_claude_task` and `resume_claude_task` on that repository for as long
as it runs**, and those calls are refused immediately with `RepositoryBusy`
rather than queuing. The reverse holds too: a review requested while a worker
is running is refused the same way.

This is the intended trade — correctness over throughput; a review of a moving
worktree describes a state that never existed as a whole — but it is a
behaviour an operator will notice. Sol's playbook should treat `RepositoryBusy`
from `review_task_with_fable` as "retry once the worker finishes", never as a
review failure.

---

## 2. Recursion defense — all 7 layers (§22)

| Layer | Defense | Implementation site |
|---|---|---|
| 1 | MCP isolation — worker gets no MCP servers at all | `runner.build_worker_invocation()` sets `mcp_config_path=config.empty_mcp_file` and always includes `--strict-mcp-config`; `runner.build_argv()` emits `--mcp-config <path>`; `ALWAYS_DISALLOWED_TOOLS` includes `"mcp__*"`. Config: `config/empty-mcp.json` = `{"mcpServers": {}}`. |
| 2 | No subagents — worker tool set excludes Agent/Task | `config.ClaudeSettings.worker_tools` (and `reviewer_tools`) simply never lists `Agent`/`Task`/`Subagent`; `runner.SUBAGENT_TOOL_NAMES = ("Agent", "Task", "Subagent")` and `runner._assert_invocation_sane()` raises `InternalDispatcherError` if any invocation is ever built with one of them in `tools`, so a future config or call-site bug fails loudly instead of silently granting the capability. `constraints.allow_subagents` is an always-false validator: setting it to `true` is refused at the model, request and config layers rather than silently coerced. |
| 3 | No child orchestrators — worker cannot start `codex`/`claude` | `runner.ALWAYS_DISALLOWED_TOOLS` includes `"Bash(claude:*)"` and `"Bash(codex:*)"`, unconditionally appended regardless of config. Reinforced at the policy layer: `prompts/worker-policy.md` explicitly lists "invoke Codex" and "invoke another Claude session" under "What you may not do." Deny patterns are prefix text matches — see the boundary table. |
| 4 | Environment markers + startup refusal | `security.worker_environment()` sets `SOL_WORKER=1`, `SOL_DISPATCH_DEPTH=str(depth+1)`, `SOL_TASK_ID=<id>` on every worker's environment. `security.assert_no_recursion()` raises `RecursionDetected` whenever the *dispatcher's own* environment carries `SOL_WORKER=1` — called from `server.main()` at startup and at the top of the dispatch/resume tool bodies. Escape hatch: `SOL_DISPATCHER_TEST_OVERRIDE=1`, used only by this project's own test suite. Validation subprocesses deliberately do **not** carry the worker markers, and inherited copies are stripped, so a validation command's provenance is never mislabelled. |
| 5 | Depth cap | `TaskEnvelope.lineage.dispatch_depth`, persisted per task. `security.assert_dispatch_depth(depth, config)` raises `RecursionDetected` if `depth > config.security.max_dispatch_depth`. `SecuritySettings.max_dispatch_depth` is itself constrained to `0 ≤ n ≤ 1` at config-parse time — V1 cannot even be configured to allow depth 2. |
| 6 | Resume cap | `sessions.assert_resume_allowed()` raises `ResumeLimitReached` once `record.resume_count >= envelope.execution.max_resume_count` (default 4). Checked exactly once, at the `RESUME_REQUESTED` transition boundary — see `docs/STATE-MACHINE.md` §5 for why the state machine's shape guarantees this is the only place it needs to be checked. |
| 7 | No dispatcher credentials forwarded | `security.worker_environment()` strips every `SECRET_ENV_MARKERS`-matching key and every `SOL_DISPATCHER_*` key from the base environment before building the worker's environment; it also never synthesizes or copies an Anthropic credential into that environment in the first place. `validation.validation_environment()` applies the same policy to the dispatcher's own validation subprocesses. |

Layers 1–3 remove the *capability* to recurse (no MCP tool exists to call, no
subagent tool exists to spawn one, no shell pattern exists to launch a
sibling orchestrator). Layers 4–6 are the *belt-and-braces* checks that fire
even if a capability leak occurred anyway — process ancestry, depth
counting, and a hard resume ceiling. Layer 7 denies a compromised worker the
one thing that would make a leaked capability dangerous: dispatcher-level
credentials.

---

## 2a. Caller-facing flags that are not switches

`constraints.allow_push`, `allow_merge`, `allow_commit` and `allow_subagents`
are **always false**. They are validated as such on `ConstraintsSpec`, on
`TaskRequest`, and in `SecuritySettings`: setting one to `true` is *refused*
with an explicit message, not silently coerced. The operations they name are
prohibited by code-level invariants (`CORE_DENIED_GIT_OPERATIONS`,
`_assert_invocation_sane`) that no flag can influence, so there is no honest
"true" branch to offer, and a switch that appears to grant something it cannot
grant is worse than no switch. The fields are kept rather than deleted because
`TaskRequest` and `Config` are `extra="forbid"`, so removing them would turn
every existing config and stored envelope that mentions them into a hard parse
error.

`constraints.allow_network` is different and remains a **real** flag: it is
honestly labelled POLICY above, it genuinely changes the instructions rendered
into the worker prompt, and no code-level invariant contradicts it.

---

## 3. Future optional hard-isolation mode

`bwrap` (bubblewrap) is present on this host (`/usr/bin/bwrap`, confirmed in
`docs/DISCOVERY.md` Phase A). It is **not a V1 dependency** and nothing in
this codebase invokes it. It is documented here only because §23 asks for
the option to be named: a future version could wrap `runner.run_worker`'s
subprocess launch in a `bwrap` sandbox (mount namespace restricted to the
worktree, network namespace disabled) to convert the POLICY rows above —
network prohibition, writes outside the repository, and primary-tree
interference, which would become *prevented* rather than *detected* — into
HARD ones. That would need its own design and test pass before being wired in;
it must not be added in a way that disturbs the existing argv-based invocation
path or any of the seven recursion-prevention layers above.

**Nothing in this repository implements a sandbox today.** This section
describes an extension point, not a feature.
