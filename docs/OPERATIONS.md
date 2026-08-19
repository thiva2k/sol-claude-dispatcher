# OPERATIONS

Day-to-day operation of a running dispatcher: diagnostics, inspecting task
state on disk, finding logs, understanding a failure, cleaning up, and
un-sticking a stuck repository lock.

---

## 1. Running the doctor

```bash
scripts/doctor.sh
```

Read-only. It never installs anything, never modifies a config (this
project's or anyone else's), never spawns a Claude or Codex worker, and
never kills a process — see `scripts/doctor.sh` itself, and §30 of the build
brief. It checks, in order:

- the project's own venv Python and its version
- `mcp`, `pydantic`, `pytest` package versions inside that venv
- `git --version`
- whether `claude` is on `PATH`, probed with `--version` only — never `-p`
- whether `codex` is on `PATH`, probed with `--version` only
- `state/` directory permissions (must be `0700`)
- whether `config/dispatcher.toml` exists and parses (fail-closed: a config
  with the placeholder root, an unknown key, or a missing section is
  reported as a failing check, not silently skipped)
- the three `prompts/*.md` files are present
- every `schemas/*.schema.json` file is valid JSON
- `config/empty-mcp.json` is exactly `{"mcpServers": {}}`
- `tests/fake_bin/claude` is present and executable

Exit code is `0` only when every check passes. A missing `config/dispatcher.toml`
(the shipped state before you've configured anything) is an expected `FAIL`
line, not a bug in the script — it means you haven't run the setup step in
`README.md` yet.

---

## 2. Reading task state directly

Every task's full history is plain files under `state/tasks/<task-id>/`
(directories `0700`, files `0600` — §27). You do not need a running MCP
server to inspect a task; `cat`/`jq`/`less` on these files is a legitimate
operational tool:

```text
state/tasks/<task-id>/
├── envelope.json          # immutable: what was asked for, resolved (base
│                           # commit, canonical repo root, worktree name)
├── state.json             # mutable: current TaskState, selected model,
│                           # session id, worktree path, resume_count,
│                           # full state_history, last_error
├── runs/
│   ├── 001/
│   │   ├── worker-result.json     # the worker's CLAIM (WorkerResult)
│   │   ├── dispatcher-result.json # the dispatcher's OBSERVATION
│   │   ├── stdout.json            # RETAINED stdout: head+tail, with an
│   │   │                          # in-band marker when truncated
│   │   ├── stdout.raw             # the COMPLETE stdout, every byte
│   │   ├── stderr.log             # the complete stderr, redacted
│   │   ├── validation.json        # independent validation command results
│   │   └── claim-verification.json # worker's claims vs validation outcomes
│   └── 002/                       # a resume creates the next run directory
├── reviews/
│   └── fable-001.json     # FableReview, one file per review
└── evidence/                       # latest run wins; per-run history is in runs/
    ├── diff.patch                  # the COMPLETE unified diff, or explicitly
    │                               # marked incomplete — never an unmarked
    │                               # short patch
    ├── diff-stat.txt
    ├── diff-check.txt
    ├── status.txt
    ├── changed-paths.json          # + diff_bytes_retained, diff_total_bytes,
    │                               #   diff_patch_bytes, diff_patch_complete
    ├── pre-validation-changed-paths.json   # EVIDENCE A: as the worker left it
    ├── pre-validation-status.txt
    ├── pre-validation-diff-stat.txt
    ├── evidence-phases.json        # attribution: worker_changed_paths,
    │                               #   final_changed_paths,
    │                               #   validation_added_paths,
    │                               #   validation_removed_paths
    ├── primary-tree-before.txt     # baseline fingerprint, written before the
    │                               #   worker started
    ├── primary-tree-after.txt
    ├── primary-tree-invariant.json # verdict + the honest limitation text
    └── primary-tree-status.txt
```

Two of these answer questions the others cannot:

* **`evidence-phases.json`** distinguishes what the *worker* changed from what
  the dispatcher's *own validation commands* changed. The scope decision is
  taken on the final state, so a validation command that writes outside the
  declared scope lands the task in `POLICY_VIOLATION` — read the attribution
  before blaming the worker (`docs/SECURITY.md` §1.3).
* **`primary-tree-invariant.json`** carries the before/after fingerprints, the
  divergence, the verdict, and the limitation text stating that this is
  detection and not containment. That text is embedded in every such file on
  purpose, so it travels with the evidence.

A truncated run is visible without opening any stream:
`runs/NNN/dispatcher-result.json`'s sibling `state.json` run metadata carries
`stdout_bytes` / `stderr_bytes` (what the child actually wrote) alongside
`stdout_truncated` / `stderr_truncated`. If a `*_truncated` flag is `true`,
`stdout.json` is an excerpt and `stdout.raw` is the whole thing.

Fast ways to answer common questions:

```bash
# Current state + full history of how it got there
jq '.state, .state_history' state/tasks/<task-id>/state.json

# What Claude claimed vs what the dispatcher actually measured, side by side
jq -s '{claims: .[0], observed: .[1]}' \
  state/tasks/<task-id>/runs/001/worker-result.json \
  state/tasks/<task-id>/runs/001/dispatcher-result.json

# Did the dispatcher's own validation agree with the worker's?
jq . state/tasks/<task-id>/runs/001/validation.json

# The actual diff a worker produced, without touching its worktree
less state/tasks/<task-id>/evidence/diff.patch

# Every Fable review recorded against this task
jq . state/tasks/<task-id>/reviews/fable-*.json
```

`get_task` (the MCP tool) returns the same information assembled into one
payload; reading the files directly is useful when the MCP server isn't
running, or when you want to grep across many tasks at once:

```bash
# Every task currently sitting in AWAITING_SOL_REVIEW
for f in state/tasks/*/state.json; do
  jq -e 'select(.state == "awaiting_sol_review") | input_filename' "$f" 2>/dev/null
done
```

---

## 3. Task lifecycle inspection

To follow one task end to end:

1. `jq '.task, .scope, .routing' state/tasks/<id>/envelope.json` — what was
   asked, and under what constraints.
2. `jq '.state_history' state/tasks/<id>/state.json` — every transition,
   with a reason and a timestamp, in order. This is the audit trail; see
   `docs/STATE-MACHINE.md` for what each state means.
3. `ls state/tasks/<id>/runs/` — how many worker turns ran (a fresh dispatch
   plus each resume is its own numbered run directory).
4. For the run you care about, read `worker-result.json` (claim) next to
   `dispatcher-result.json` (measurement) — see §16 in `docs/ARCHITECTURE.md`
   for why these are never merged.
5. `jq '.scope' state/tasks/<id>/runs/<n>/dispatcher-result.json` — whether
   the run's changes matched the declared scope, and which paths didn't if
   not.
6. `jq . state/tasks/<id>/evidence/primary-tree-invariant.json` — whether the
   primary working tree came out of the run exactly as it went in, and (if
   not) precisely what appeared, disappeared, or moved.
7. `jq . state/tasks/<id>/evidence/evidence-phases.json` — which changed paths
   the worker produced and which the dispatcher's own validation commands
   produced. Do this before concluding a policy violation was the worker's.
8. `ls state/tasks/<id>/reviews/` — whether Fable has weighed in, and what
   it found.

A task's `last_error` field on `state.json` (present only after a failure)
is the same `DispatcherError.to_payload()` shape that was returned to Sol —
`{"error", "message", "retryable", "details", "remediation"}` — so a
task's own state file is enough to understand why it stopped, without
needing to correlate against a separate log.

---

## 4. Log locations

Application logs go to **stderr**, or to `logging.log_file` if configured in
`config/dispatcher.toml` (§28). They never go to stdout — stdout is the MCP
JSON-RPC transport, and a stray `print()` there would corrupt the protocol
stream Sol is reading. If you started the server directly from a shell,
stderr is whatever your terminal or process supervisor captured it to; if
Codex launched it as an MCP server subprocess, check wherever Codex routes
its child processes' stderr (Codex's own logs, not this project's).

Every operational log line carries `task_id`, `run_id`, `timestamp`,
`event`, `duration`, `status` where applicable (§28). Secret-shaped values
(`TOKEN`, `API_KEY`, `APIKEY`, `AUTHORIZATION`, `COOKIE`, `SECRET`,
`PASSWORD`, `PRIVATE_KEY`, `CREDENTIAL`) are redacted before anything is
logged or written to `argv_redacted` — see `security.redact()`. The full
environment is never persisted.

Worker *output* is a different thing from application logs and **is** kept, in
the task's own run directory at `0600` (`stdout.json`, `stdout.raw`,
`stderr.log`), because §20 requires evidence to survive a timeout or a crash.
Stderr is redacted on the way to disk; stdout is not, because redacting it
would corrupt the structured JSON result. Redaction of the spooled stream is
line-oriented, so a `"key": "value"` pair split across a newline is not masked
there.

---

## 5. Error taxonomy (§29)

Every failure that reaches Sol is one of these (`sol_claude_dispatcher.errors`),
returned as `{"error": <code>, "message": ..., "retryable": bool,
"details": {...}, "remediation": "..."}` — never a raw Python traceback.

| Code | Retryable | Meaning | Typical remediation |
|---|---|---|---|
| `InvalidRepository` | no | Path missing, not a directory, not inside a git work tree, **or not itself the git top level** | Fix the path or `git init` it. If you dispatched against a subdirectory, dispatch against the repository root and use `[scope].allowed_paths` to narrow the task |
| `InvalidTaskEnvelope` (malformed `task_id`) | no | A `task_id` that is not a canonical lowercase UUID reached `get_task` / `resume_claude_task` / `review_task_with_fable` | Use the `task_id` `dispatch_claude_task` returned, verbatim. The dispatcher refuses rather than repairing the id, and refuses it at the boundary rather than deeper in the stack |
| `RepositoryNotAllowed` | no | The repository's git top level is not **exactly** one of `allowed_repository_roots` | Add the repository's own top-level path. A parent directory does not authorise the repositories inside it |
| `RepositoryBusy` | **yes** | Another mutating worker **or a Fable review** already holds the repo's lock | Wait and retry. Not a failure of the call that was refused — check `state/locks/` (§7 below) |
| `WorktreeCreationFailed` | no | Worker exited without leaving a worktree the dispatcher can find | Inspect `runs/<n>/stderr.log`; the worker may have failed before `--worktree` took effect |
| `GitEvidenceCollectionFailed` | no | An authoritative git command failed, timed out, produced unusable output, or `git` could not be run at all | **Never read this as "nothing changed".** It means the evidence could not be obtained, so no scope or non-interference verdict is available for that run. Check the error's `details` (command, cwd, stderr excerpt); the task lands in an explicit failure state with the diagnostics preserved |
| `InvalidTaskEnvelope` | no | Caller input or a persisted envelope failed model validation | Fix the request; extra/unknown fields are rejected, not ignored |
| `InvalidStateTransition` | no | Requested a transition `ALLOWED_TRANSITIONS` does not permit | Check `docs/STATE-MACHINE.md`; the task is not where you think it is |
| `TaskNotFound` | no | No persisted task for that `task_id` | Check the id; `get_task` against a wrong id fails the same way |
| `StateCorruption` | no | `state.json`/`envelope.json` is unparseable or missing `schema_version` | Never auto-repaired. Inspect the file by hand; if truly corrupt, the task is unrecoverable — do not delete it before you've captured whatever evidence exists |
| `ClaudeBinaryNotFound` | no | Configured `claude` binary is absent or not executable | Fix `[claude].binary` or install the CLI; `doctor.sh` catches this ahead of time |
| `ClaudeExecutionFailed` | no | Claude could not be started, or exited in a way the runner treats as a hard failure | Check `stderr.log` for the run |
| `ClaudeStructuredOutputInvalid` | no | stdout wasn't JSON, or didn't match the worker/reviewer schema | Read `runs/<n>/stdout.json`; `worker_result_error` on the dispatcher observation names the specific reason (`not_json`, `no_structured_payload`, `schema_mismatch`) |
| `ClaudeTimedOut` | no | Exceeded `execution.timeout_seconds`; SIGTERM→grace→SIGKILL ran | Not a correctness verdict (§20) — evidence (session id, worktree, partial output) survives; resume or re-dispatch with more time |
| `ResumeLimitReached` | no | `resume_count >= max_resume_count` | Not actually surfaced as this error code from the MCP tool — see below |
| `PolicyViolation` | no | Diff touched paths outside declared scope, **and/or** the primary working tree diverged from its pre-run baseline | Inspect `dispatcher-result.json`'s `out_of_scope_paths`/`forbidden_paths_touched` and `state.json`'s `policy_violations` (primary-tree entries are prefixed `primary_tree_head:` / `primary_tree_appeared:` / `primary_tree_disappeared:`), plus `evidence/primary-tree-invariant.json` and `evidence/evidence-phases.json`. A path the dispatcher's own validation produced is attributed as such — check before blaming the worker |
| `ValidationFailed` | no | A trusted dispatcher validation command failed | Check `runs/<n>/validation.json` |
| `RecursionDetected` | no | `SOL_WORKER=1` was present at startup/dispatch, or depth exceeded the max | Should never happen outside a bug; if it does, something is invoking the dispatcher from inside a worker |
| `ConfigurationError` | no | Config missing, malformed, or semantically invalid | Fail-closed by design; fix the named key |
| `InternalDispatcherError` | no | Unexpected internal fault | Traceback is in the stderr log only, never in the response Sol sees |

`ResumeLimitReached` is raised internally by `sessions.assert_resume_allowed()`
but `resume_claude_task` converts it (via `sessions.resume_limit_response()`)
into a *successful* tool response —
`{"status": "requires_orchestrator_decision", "reason": "resume_limit_reached", ...}` —
rather than an error payload, because the dispatcher refusing to guess what
happens next is the correct behavior, not a failure (§7.2).

---

## 6. Cleanup

```bash
scripts/cleanup-task.sh <task-id>
```

Removes exactly one task's `state/tasks/<task-id>/` directory, after an
interactive confirmation (`-y` or `FORCE=1` to skip it non-interactively).
It refuses non-alphanumeric task ids outright (blocks path traversal through
the id) and double-checks the resolved path is actually inside
`state/tasks/` before deleting anything.

It **never** deletes or modifies a git worktree in any target repository.
If the task recorded a `worktree_path`, the script prints the exact
`git worktree remove` command for you to run yourself, from inside that
repository — deciding that a worktree's contents are safe to discard is a
human decision.

There is no bulk-cleanup script by design: clearing many tasks at once is
easy to script from the shell (`for d in state/tasks/*/; do ...; done`)
once you've decided which ones are safe to remove, and a single-task tool
keeps the default action narrow.

---

## 7. Lock troubleshooting

V1 allows exactly one mutating worker per repository at a time (§25). The lock
file lives at `state/locks/<sha256-of-canonical-repo-path>.lock`, where the
canonical path is the repository's **git top level** — so a subdirectory of a
repository contends with the repository itself, which is the point. It is
acquired with `flock(LOCK_EX | LOCK_NB)` — non-blocking, so a busy repo
raises `RepositoryBusy` immediately rather than stalling an MCP call until
Codex's own tool-call timeout fires.

**Three tools take this lock: `dispatch_claude_task`, `resume_claude_task`,
and `review_task_with_fable`.**

If a dispatch or resume fails with `RepositoryBusy`:

1. Check what's actually running: `RepositoryLock.acquire()` writes the
   holder's `pid=<n>` into the lock file (truncated and rewritten on each
   acquire — never trust a stale pid without checking it's alive):
   ```bash
   cat state/locks/<hash>.lock
   ps -p "$(grep -o '[0-9]*' state/locks/<hash>.lock)"
   ```
2. If that pid is a live, legitimately-running worker: wait for it. This is
   the lock working as designed — V1 deliberately serializes mutating work
   per repository (§25) rather than risking two workers racing in the same
   tree.
3. If that pid is dead (crashed dispatcher, killed process, host reboot):
   the lock file itself is **never unlinked automatically** — release()
   only calls `flock(LOCK_UN)` and closes the fd; the file is left in place
   because unlinking races with another process that has already opened it
   (§25, `locks.py`). A dead holder's `flock` is released by the kernel the
   moment its process exits, so a *new* `acquire()` will succeed cleanly
   even though the stale file is still sitting there with an outdated pid
   line. You do not need to delete the lock file to recover from a crashed
   holder — only delete it if you want to tidy up disk clutter, and only
   after confirming (step 1) that no live process holds it.
4. To find which repository a lock hash corresponds to, resolve candidate
   repository roots yourself and compare:
   ```bash
   .venv/bin/python -c "
   from sol_claude_dispatcher.locks import lock_name_for
   from pathlib import Path
   print(lock_name_for(Path('/path/to/candidate/repo')))
   "
   ```
   and compare against the `.lock` filename. Use `lock_name_for` rather than
   hashing a path by hand: identity is the git top level, so hashing the
   spelling you happen to have typed can give the wrong answer.

### Fable review holds the lock — expect this

A Fable review takes the **same exclusive lock**, for its whole duration,
including the reviewer subprocess.

* **A long Fable review blocks `dispatch_claude_task` and
  `resume_claude_task` on that repository until it finishes.** Those calls are
  refused immediately with `RepositoryBusy`; they do not queue.
* A review requested while a worker is running is refused the same way.
* Two concurrent reviews of the same repository: one wins, one is refused.

This is deliberate. A review that reads a worktree while a resume is rewriting
it produces a verdict describing a state that never existed as a whole. Sol
should treat `RepositoryBusy` from `review_task_with_fable` as "retry once the
worker finishes", **never** as a review failure — nothing is recorded against
the task when a review is refused, and the repository is usable again the
moment the holder releases.

Earlier versions of this document (and of `locks.py`'s own docstring) said
Fable takes no lock. That was true, and it was the defect.
