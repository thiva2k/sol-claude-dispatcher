# STATE MACHINE

Authoritative source: `sol_claude_dispatcher.models.TaskState` and
`ALLOWED_TRANSITIONS`. `state.py`'s `TaskStore.transition()` enforces this
table and adds nothing to it — if you are reading this document to
understand what a transition does, the table below *is* the implementation,
not a summary of it.

---

## 1. The 12 states

| State | Meaning |
|---|---|
| `CREATED` | Envelope persisted; nothing has run yet. |
| `ROUTED` | Model selected (`router.explain_route`); reason recorded in `state_history`. |
| `RUNNING` | A worker subprocess is (or was about to be) in flight for this run. |
| `IMPLEMENTED` | The worker exited, its output parsed cleanly, exit code zero, no scope violation, no timeout, status was not `blocked`. |
| `AWAITING_SOL_REVIEW` | The dispatcher has finished collecting evidence for the current run and is waiting on Sol. |
| `FABLE_REVIEWED` | An independent Fable review has been recorded against this task. |
| `RESUME_REQUESTED` | Sol asked to continue the conversation; the resume cap has been checked and a `ResumePlan` built from stored state. |
| `REVIEW_COMPLETE` | Sol has finished reviewing. **Terminal.** |
| `TIMED_OUT` | The worker exceeded its dispatcher timeout and was terminated (SIGTERM → grace → SIGKILL). An off-ramp, not a verdict on the implementation (§20). |
| `BLOCKED` | The worker itself reported `status: "blocked"` — it stopped and said it needed something rather than fabricating a result. |
| `FAILED` | Non-zero exit, unparseable/schema-invalid structured output, or any other run that didn't produce a usable implementation. |
| `POLICY_VIOLATION` | The dispatcher's own diff inspection found changes outside `scope.allowed_paths` or touching `scope.forbidden_paths`. Evidence is preserved; Sol decides what happens next. |

---

## 2. Full transition table

```text
CREATED             -> ROUTED, FAILED
ROUTED              -> RUNNING, FAILED
RUNNING             -> IMPLEMENTED, TIMED_OUT, BLOCKED, FAILED, POLICY_VIOLATION
IMPLEMENTED         -> AWAITING_SOL_REVIEW
AWAITING_SOL_REVIEW -> FABLE_REVIEWED, RESUME_REQUESTED, REVIEW_COMPLETE
FABLE_REVIEWED      -> RESUME_REQUESTED, REVIEW_COMPLETE, AWAITING_SOL_REVIEW
RESUME_REQUESTED    -> RUNNING, FAILED
TIMED_OUT           -> AWAITING_SOL_REVIEW, RESUME_REQUESTED, FAILED
BLOCKED             -> AWAITING_SOL_REVIEW, RESUME_REQUESTED, FAILED
POLICY_VIOLATION    -> AWAITING_SOL_REVIEW, RESUME_REQUESTED, FAILED
FAILED              -> AWAITING_SOL_REVIEW
REVIEW_COMPLETE     -> (terminal — no outbound transitions)
```

As a diagram, collapsing the four off-ramps of `RUNNING` into one shape
since they all behave identically from here on:

```text
CREATED
   │
   ▼
ROUTED
   │
   ▼
RUNNING
   │
   ├──► IMPLEMENTED ──────────────────► AWAITING_SOL_REVIEW ─┐
   │                                            ▲            │
   ├──► TIMED_OUT ──────┐                       │            │
   ├──► BLOCKED ─────────┼──► (Sol decides) ─────┘            │
   ├──► POLICY_VIOLATION ┘         │                          │
   │                               ▼                          │
   └──► FAILED ─────────────► AWAITING_SOL_REVIEW              │
                                                                │
                       ┌─────────────────────────────────────┘
                       ▼
              AWAITING_SOL_REVIEW ──► FABLE_REVIEWED ──┐
                       │                    │           │
                       │                    ▼           │
                       ├──────────► RESUME_REQUESTED ◄──┘
                       │                    │
                       │                    ▼
                       │                 RUNNING  (loop back to the top)
                       │
                       ▼
              REVIEW_COMPLETE  (terminal)
```

`TaskStore.transition()` mechanics: load the current `TaskRecord` → check
`is_transition_allowed(current.state, target)`, raising
`InvalidStateTransition` with `details={"from", "to", "allowed"}` if not →
apply the caller's `**updates` to record fields (an unknown field name is
also `InvalidStateTransition`) → append
`{"from", "to", "at", "reason"}` to `state_history` → atomic save → return
the new record. Every transition is therefore self-documenting in
`state_history` without any separate audit log.

---

## 3. Off-ramp semantics

`TIMED_OUT`, `BLOCKED`, `FAILED`, and `POLICY_VIOLATION` all sit at the same
structural position: they are things that can happen to a `RUNNING` worker
other than a clean `IMPLEMENTED`, and they all funnel into the same next
choice — `AWAITING_SOL_REVIEW`, `RESUME_REQUESTED`, or (for the first three)
straight to `FAILED` if Sol decides the task is simply dead. None of them
means "the code is wrong":

- **`TIMED_OUT`** is explicitly not a verdict on correctness (§20). The
  worker may have been seconds from finishing. Evidence — session ID,
  worktree, partial stdout/stderr, whatever diff had accumulated — survives
  the kill and is exactly what lets Sol decide whether to resume.
- **`BLOCKED`** is a *good* outcome by the worker policy's own standard
  (`prompts/worker-policy.md`: "A blocked report is a good outcome. A
  fabricated success is not."). The worker stopped and said what it needed
  instead of guessing.
- **`POLICY_VIOLATION`** means the dispatcher's own `git diff` inspection —
  not the worker's claim — found changes outside the declared scope. The
  changes are not reverted or hidden; they are reported so Sol can judge
  whether the extra change was actually fine and widen scope, or reject it.
- **`FAILED`** is the catch-all for a run that didn't produce anything
  usable (bad exit code, unparseable output, schema mismatch). It is a
  dispatcher-level fact about the run, not the dispatcher's opinion of the
  work.

All four route back into human/Sol judgement rather than the dispatcher
silently retrying, silently discarding evidence, or silently deciding the
task is done.

---

## 4. No `APPROVED` state — rationale

`TaskState` has 12 members and none of them is `APPROVED`. This is not an
omission; §26 states it as a rule and §41 explains why: "implementation
complete," "review complete," and "user approved" are three different
things, and the dispatcher only ever gets to be the author of the first
two. `TERMINAL_STATES = frozenset({REVIEW_COMPLETE})` — the one state with
no outbound transitions — represents "Sol has finished reviewing," which is
as far into the approval question as software that cannot ask a human a
question is allowed to get. A merge, a push, a deploy, or telling the human
"this is ready" are decisions that happen *outside* this state machine, by
a human, and nothing in this codebase infers consent from a task merely
reaching `REVIEW_COMPLETE`.

---

## 5. Resume-through-`RESUME_REQUESTED`-only rule

Look again at the off-ramp rows in the table:

```text
TIMED_OUT           -> AWAITING_SOL_REVIEW, RESUME_REQUESTED, FAILED
BLOCKED             -> AWAITING_SOL_REVIEW, RESUME_REQUESTED, FAILED
POLICY_VIOLATION    -> AWAITING_SOL_REVIEW, RESUME_REQUESTED, FAILED
```

None of them lists `RUNNING` as a direct target, and neither does
`AWAITING_SOL_REVIEW` or `FABLE_REVIEWED`. **No state jumps straight back
to `RUNNING`.** Every path back into a running worker passes through
`RESUME_REQUESTED` first, and `RESUME_REQUESTED -> RUNNING` is the only edge
that leads there.

This is deliberate, not an accident of table construction: `RESUME_REQUESTED`
is the single place `sessions.assert_resume_allowed()` is consulted, which
is the single place the resume cap (`max_resume_count`, default 4, §22
layer 6) is enforced. If a timeout, a block, or a policy violation could
transition directly back to `RUNNING`, the resume cap would need to be
checked at three or four separate call sites instead of one, and a future
change that adds a fifth off-ramp would have to remember to add the check
again. Funneling every resume through one edge means the cap is checked
exactly once, in exactly one place (`state.py` calling into `sessions.py`),
for every possible path into a second worker turn.
