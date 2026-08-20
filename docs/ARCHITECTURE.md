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
| `locks.py` | 2 | `RepositoryLock` — one exclusive `flock` per canonical repository identity, which is the *git top level* (§25), non-blocking by default so a busy repo fails fast as `RepositoryBusy` instead of stalling an MCP call. Dispatch, resume **and Fable review** all take it. |
| `git.py` | 2 | Evidence collection and scope checking (§12, §13): repository identity (`git_top_level`), base-commit resolution, worktree lookup, diff/status/diff-check collection, full-patch streaming, glob-based scope matching. Every authoritative command fails closed with `GitEvidenceCollectionFailed` rather than degrading to an empty result. Read-only with respect to git state — never commits, merges, pushes, or touches the primary tree. |
| `security.py` | 2 | Task-id validation (`validate_task_id`), repository allowlist validation (§24), the recursion-prevention checks that don't belong to `runner.py` (§22 layers 4/5/7), and secret redaction (§28). |
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
  → security.validate_repository_root      (git top level, EXACT allowlist match)
  → security.assert_dispatch_depth
  → RepositoryLock.acquire()                   (exclusive, non-blocking)
  → git.resolve_base_commit
  → TaskEnvelope.from_request                  (dispatcher truth is born here)
  → store.create                                (state.json: CREATED)
  → router.route + explain_route                (deterministic Sonnet/Opus)
  → store.transition → ROUTED                    (records model + reason)
  → sessions.new_session                         (uuid4)
  → snapshot_primary_tree                        (BASELINE, before the worker;
                                                   written to evidence/ at once)
  → store.transition → RUNNING
  → runner.run_worker                            (--worktree, --session-id,
                                                   complete streams spooled 0600)
  → git.worktree_path_for
  → git.collect_diff_evidence                    (EVIDENCE A — as the worker
                                                   left it; persisted first)
  → results.parse_worker_result                  (claim, not evidence)
  → validation.run_validations                   (independent re-run, §17,
                                                   sanitized environment)
  → git.collect_diff_evidence                    (EVIDENCE B — after validation)
  → attribute_changed_paths                      (A vs B: who produced what)
  → check_scope on the FINAL state
  → snapshot_primary_tree + compare              (post_state == pre_state?)
  → write evidence bundle                         (before any state decision)
  → build DispatcherObservations                  (measurement, not claim)
  → store.append_run
  → store.transition → IMPLEMENTED | TIMED_OUT | BLOCKED | FAILED |
                        POLICY_VIOLATION
  → (on IMPLEMENTED) store.transition → AWAITING_SOL_REVIEW
  → lock.release()                                (always, in a finally)
```

Returns `task_id`, `run_id`, `selected_model`, `session_id`, `worktree`,
`status`, `worker_claims`, `dispatcher_observations`, `validation_results`,
`evidence_attribution`, `primary_tree`, and the scope verdict — claims and
observations kept in clearly separate fields (§16, see §4 below).

Two things in that sequence are load-bearing and easy to get wrong if this
document is read as a mere ordering:

* **Evidence is collected twice.** Validation commands mutate worktrees
  routinely (formatters, coverage files, lockfiles, snapshot updates), so
  post-worker evidence is stale the moment one runs. The *decision* is taken on
  the final state, because that is what is actually on disk; the *attribution*
  keeps a dispatcher-generated path from being charged to the worker. See
  `docs/SECURITY.md` §1.3.
* **The primary-tree baseline is taken before the worker starts**, inside the
  lock, and written to `evidence/primary-tree-before.txt` immediately so it
  survives whatever happens next. The invariant is `post == pre`, not "clean".
  A divergence lands `POLICY_VIOLATION` and can never fall through to
  `AWAITING_SOL_REVIEW`. It is *detection*, not containment —
  `docs/SECURITY.md` §1.2 states the limitation in full.

### `resume_claude_task` (§7.2)

Same evidence pipeline as above, but session ID, model, and worktree all
come from the stored `TaskRecord` — never from the caller:

```text
assert_no_recursion
  → security.validate_task_id                      (canonical UUID or refuse)
  → store.load                                    (authoritative state)
  → sessions.resume_plan                           (session/model/worktree
                                                      pinned from state; calls
                                                      assert_resume_allowed —
                                                      cap check, §22 layer 6)
  → store.transition → RESUME_REQUESTED            (nothing has moved until here)
  → store.transition → RUNNING
  → runner.run_worker                              (--resume, no --worktree)
  → [same evidence/validation/observation pipeline as dispatch]
  → resume_count += 1
```

The plan is built *before* the first transition, so a refusal leaves the task
exactly where it was. If the resume cap is exhausted, the tool returns
`{"status": "requires_orchestrator_decision", "reason": "resume_limit_reached"}`
— a *successful* MCP response describing a refusal, not a protocol error. Sol
decides what happens next; the dispatcher does not guess. If the stored session
id, model or worktree is missing, the tool refuses with `StateCorruption`
rather than starting a fresh conversation.

Every off-ramp can be resumed — `TIMED_OUT`, `BLOCKED`, `POLICY_VIOLATION`
**and `FAILED`**. A run that lands `FAILED` (unparseable output, non-zero exit,
evidence that could not be collected) still holds its session id, model and
worktree, so a corrective resume is exactly what it is there for. The legality
of the edge lives in `ALLOWED_TRANSITIONS`; whether the resume can actually be
carried out lives in `sessions.resume_plan`. See `docs/STATE-MACHINE.md` §3.

### `review_task_with_fable` (§7.3)

```text
assert_no_recursion
  → security.validate_task_id                (canonical UUID or refuse)
  → store.load
  → RepositoryLock.acquire()                 (EXCLUSIVE, non-blocking —
                                               refuses with RepositoryBusy)
  → store.load again, inside the lock         (run_index names a directory)
  → fresh session_id, config.models.fable, reviewer_tools only (Read/Glob/Grep)
  → no --worktree, no --resume — Fable never touches the worker's
    conversation or creates a worktree of its own
  → cwd = the worker's own worktree; prompt assembled from objective,
    acceptance criteria, base commit, changed files, a bounded read of the
    stored evidence/diff.patch, the paths the dispatcher's own validation
    produced, the worker's report, and Sol's review focus
  → runner.run_worker
  → results.parse_fable_review
  → store.append_review
  → store.transition → FABLE_REVIEWED
  → lock.release()                            (always, in a finally)
```

**Takes the same exclusive repository lock as dispatch and resume**, on the
same canonical identity, for the whole snapshot. "Read-only" describes the
reviewer, not the repository: a concurrent `resume_claude_task` mutates the
very worktree the reviewer is reading, and the resulting verdict would
describe a state that never existed as a whole. One exclusive lock, no
reader/writer split — deliberately simple for V1.

Operational consequence: a long review blocks dispatch and resume on that
repository for its duration, and a review requested while a worker is running
is refused immediately with `RepositoryBusy`. That refusal is retryable and is
not a review failure; see `docs/SECURITY.md` §1.6.

### `get_task` (§7.4)

Read-only. No transition, no subprocess, no lock — but the caller-supplied
`task_id` still goes through `security.validate_task_id` first, and `TaskStore`
still proves every derived path resolves inside `state/tasks/`. Reads the envelope,
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

Three observation fields are easy to confuse and are deliberately distinct:

| Field | Question it answers |
|---|---|
| `primary_worktree_clean` | Does the primary tree have uncommitted changes *right now*? A literal measurement. An ordinary developer's checkout makes this `False` with no violation. |
| `primary_tree_unchanged` | Is the primary tree's fingerprint identical to the baseline taken before the worker started? This is the non-interference verdict. `None` means the comparison was not performed for that run. |
| `diff_bytes` vs `diff_total_bytes` | How much diff the dispatcher held in memory, vs how much git actually produced. A difference means the in-memory value was capped; `evidence/diff.patch` is still complete, or is explicitly marked incomplete. |

The measurement layer also refuses to answer when it cannot measure:
`GitEvidenceCollectionFailed` is a distinct outcome from "nothing changed", and
a run whose evidence could not be collected lands `FAILED` with diagnostics
rather than being reported as a clean tree.

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
