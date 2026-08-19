# ARCHITECTURE

This document describes what the codebase actually does, not what it aspires
to do. It is written against the modules as implemented; where a module was
still a stub at the time of writing, that is called out explicitly rather
than described as finished.

---

## 1. Hierarchy

```text
                              USER
                               │
                               ▼
                    ┌─────────────────────┐
                    │  SOL (on Codex)     │   orchestrator, tech lead,
                    │                     │   final reviewer, sole holder
                    └──────────┬──────────┘   of "approved"
                               │
                               │  MCP over stdio
                               │  (4 tools, no more)
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

Sol is the only client the MCP server talks to. Sol is the only place
architectural judgement, retry decisions, and approval live. The dispatcher's
job is to make Sol's decisions executable, auditable, and safe to run
unattended — never to make them (§46).

---

## 2. Module map

The package is 13 Python modules plus `__init__.py` (14 files under
`src/sol_claude_dispatcher/`). Each has one job and a strict boundary.

| Module | Wave | What it actually does |
|---|---|---|
| `models.py` | 1 | The full data contract: enums (`TaskState`, `RequestedModel`, …), the state machine table (`ALLOWED_TRANSITIONS`), ID/time helpers, and every Pydantic model — `TaskRequest` (caller input), `TaskEnvelope` (dispatcher truth), `WorkerResult`/`FableReview` (worker claims), `DispatcherObservations`/`RunRecord`/`TaskRecord` (dispatcher's own measurements). Nothing else in the package defines a type that crosses a module boundary. |
| `errors.py` | 1 | The typed error taxonomy (§29). One `DispatcherError` base class with `.code`/`.details`/`.remediation`/`.retryable` and `.to_payload()`; every failure that reaches Sol is one of its subclasses, never a raw traceback. |
| `config.py` | 1 | Fail-closed TOML loading (§35). Validates `[dispatcher]`, `[models]`, `[routing]`, `[security]`, `[validation]`, `[claude]`, `[logging]`; derives filesystem paths (`state_path`, `worker_policy_file`, …) so no other module hand-builds a path from config. |
| `router.py` | 2 | `route()`/`explain_route()` — pure, deterministic Sonnet/Opus selection. No I/O, no randomness, never returns Fable. |
| `state.py` | 2 | `TaskStore` — atomic JSON persistence, the on-disk layout of §27, and the only code path allowed to call `is_transition_allowed()` and commit a state change. |
| `locks.py` | 2 | `RepositoryLock` — one exclusive `flock` per canonical repository path (§25), non-blocking by default so a busy repo fails fast as `RepositoryBusy` instead of stalling an MCP call. |
| `git.py` | 2 | Evidence collection and scope checking (§12, §13): base-commit resolution, worktree lookup, diff/status/diff-check collection, glob-based scope matching. Read-only with respect to git state — never commits, merges, pushes, or touches the primary tree. |
| `security.py` | 2 | Repository allowlist validation (§24), the recursion-prevention checks that don't belong to `runner.py` (§22 layers 4/5/7), and secret redaction (§28). |
| `runner.py` | 3 | Builds the exact Claude CLI `argv` (`build_argv`) and runs it as a subprocess with process-group timeout/SIGTERM/SIGKILL discipline (`run_worker`, §20). The only module that spawns a worker process. |
| `results.py` | 3 | Parses `--output-format json` stdout into `WorkerResult`/`FableReview`, following the §15 resolution order. Never regex-scrapes prose; an unparseable result is reported as such, not guessed at. |
| `sessions.py` | 3 | Session lifecycle (§18): new session IDs, resume plans built only from stored state (never from the caller), the resume cap, and the §18 escalation-is-a-new-task handoff. |
| `validation.py` | 3 | Re-runs the envelope's own trusted validation commands after a worker exits (§17) — independent of, and never influenced by, anything the worker claimed. |
| `server.py` | 4 | The stdio MCP server: registers exactly four tools, wires the modules above into the flows described below, and refuses to start under `SOL_WORKER=1` (§22 layer 4). |

---

## 3. Data flow for the four tools

All four tools are implemented as thin orchestration over the modules in
§2 — the tool bodies themselves contain no business logic beyond call
ordering and error-to-payload translation.

### `dispatch_claude_task` (§7.1)

```text
assert_no_recursion
  → validate TaskRequest (pydantic, extra="forbid")
  → security.validate_repository_root         (allowlist + git check)
  → security.assert_dispatch_depth
  → RepositoryLock.acquire()                   (exclusive, non-blocking)
  → git.resolve_base_commit
  → TaskEnvelope.from_request                  (dispatcher truth is born here)
  → store.create                                (state.json: CREATED)
  → router.route + explain_route                (deterministic Sonnet/Opus)
  → store.transition → ROUTED                    (records model + reason)
  → sessions.new_session                         (uuid4)
  → store.transition → RUNNING
  → runner.run_worker                            (--worktree, --session-id)
  → git.worktree_path_for
  → git.collect_diff_evidence + check_scope
  → results.parse_worker_result                  (claim, not evidence)
  → validation.run_validations                   (independent re-run, §17)
  → build DispatcherObservations                  (measurement, not claim)
  → store.append_run
  → store.transition → IMPLEMENTED | TIMED_OUT | BLOCKED | FAILED |
                        POLICY_VIOLATION
  → (on IMPLEMENTED) store.transition → AWAITING_SOL_REVIEW
  → lock.release()                                (always, in a finally)
```

Returns `task_id`, `run_id`, `selected_model`, `session_id`, `worktree`,
`status`, `worker_claims`, `dispatcher_observations`, `validation_results`,
and the scope verdict — claims and observations kept in clearly separate
fields (§16, see §4 below).

### `resume_claude_task` (§7.2)

Same evidence pipeline as above, but session ID, model, and worktree all
come from the stored `TaskRecord` — never from the caller:

```text
assert_no_recursion
  → store.load                                    (authoritative state)
  → sessions.assert_resume_allowed                 (cap check, §22 layer 6)
  → store.transition → RESUME_REQUESTED
  → sessions.resume_plan                           (session/model/worktree
                                                      pinned from state)
  → store.transition → RUNNING
  → runner.run_worker                              (--resume, no --worktree)
  → [same evidence/validation/observation pipeline as dispatch]
  → resume_count += 1
```

If the resume cap is exhausted, the tool returns
`{"status": "requires_orchestrator_decision", "reason": "resume_limit_reached"}`
— a *successful* MCP response describing a refusal, not a protocol error. Sol
decides what happens next; the dispatcher does not guess.

### `review_task_with_fable` (§7.3)

```text
assert_no_recursion
  → store.load
  → fresh session_id, config.models.fable, reviewer_tools only (Read/Glob/Grep)
  → no --worktree, no --resume — Fable never touches the worker's
    conversation or creates a worktree of its own
  → cwd = the worker's own worktree; prompt assembled from objective,
    acceptance criteria, base commit, changed files, the stored
    evidence/diff.patch, the worker's report, and Sol's review focus
  → runner.run_worker
  → results.parse_fable_review
  → store.append_review
  → store.transition → FABLE_REVIEWED
```

Does **not** take the repository lock (§25: review is read-only and runs
only against stable post-worker state).

### `get_task` (§7.4)

Read-only. No transition, no subprocess, no lock. Reads the envelope,
current `TaskRecord`, run history, validation history, latest worker result,
and latest Fable review straight off disk and returns them.

---

## 4. `worker_claims` vs `dispatcher_observations` (§16)

This is the doctrine the rest of the architecture exists to serve:

> **Claude's output is not authoritative.**

Every run produces two separate objects, stored in separate fields, with
**zero overlapping field names** (a unit test enforces this on the models
directly):

| | `WorkerResult` (worker claims) | `DispatcherObservations` (dispatcher observations) |
|---|---|---|
| Who produces it | Claude, in its structured JSON output | The dispatcher, from its own subprocess handling and git inspection |
| What it says | "341 tests passed", which files it believes it changed, its own assessment of blockers/risks | The actual exit code, actual timing, the actual `git diff`, the actual changed paths, whether they matched scope, whether the dispatcher's own re-run of the validation commands agreed |
| Trust level | A claim until corroborated | Measured fact |
| Where it lives | `worker_claims` on `RunRecord` | `dispatcher_observations` on `RunRecord` |

Nothing in the codebase ever copies a value from one into the other. A
worker saying its own diff touched only `src/foo.py` does not populate
`changed_paths` — that field comes only from `git.collect_diff_evidence`
walking the real worktree. If a worker's structured output cannot be parsed
at all, `worker_claims` is `None` and `dispatcher_observations` still exists
and is still trustworthy (`worker_result_parsed=False`,
`worker_result_error` populated) — the measurement layer does not depend on
the claim layer succeeding.

---

## 5. Hub-and-spoke (§40)

Agents never talk to each other directly. Every exchange of information
passes back through Sol:

```text
Sol
 │
 ├── asks Opus to implement ──────────► Opus returns evidence
 │
 ▼
Sol reviews the evidence
 │
 ├── asks Fable to challenge it ──────► Fable returns findings
 │
 ▼
Sol evaluates the findings
 │
 ├── resumes Opus with accepted findings ──► Opus fixes
 │
 ▼
Sol reviews again
```

There is no path in this codebase from a worker session to another worker
session, to Fable, or back to Sol except through a completed MCP tool call
returning to Sol. Concretely: `runner.py` strips MCP entirely from every
worker (`--strict-mcp-config` + empty `mcpServers` + `mcp__*` denied), so a
worker process has no mechanism to call *any* MCP tool, including this
dispatcher's own. Fable is invoked by Sol, reports to Sol, and never resumes
or addresses the worker's session (§19). "Opus ↔ Fable ↔ Sol ↔ Opus" free-form
conversation is not a mode this system has.

---

## 6. Approval semantics trichotomy (§41)

Three states are never collapsed into one, in code, in documentation, or in
what a tool response claims:

| State | Means | Who reaches it | Where it lives |
|---|---|---|---|
| **Implementation complete** | Claude stopped and returned a result | The worker, observed by the dispatcher | `TaskState.IMPLEMENTED` |
| **Review complete** | Sol (optionally with Fable's input) has reviewed the implementation | Sol | `TaskState.REVIEW_COMPLETE` / `FABLE_REVIEWED` |
| **User approved** | The human has accepted the proposal or next action where approval is required | The human, outside this state machine entirely | Not represented in `TaskState` at all |

There is deliberately **no `APPROVED` state**. `models.TaskState` has no such
member, `ALLOWED_TRANSITIONS` has no such target, and nothing in `server.py`
synthesizes one. `TERMINAL_STATES = {REVIEW_COMPLETE}` — the machine's
terminal state means "Sol is done reviewing," not "the human signed off" and
not "this may now be merged, pushed, or deployed." See
`docs/STATE-MACHINE.md` for the full transition table and the reasoning
behind the specific off-ramp shape that makes this guarantee hold.
