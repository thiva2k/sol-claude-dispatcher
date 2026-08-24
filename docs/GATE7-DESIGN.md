# GATE 7 — ARCHITECTURE

**Lifecycle, evidence and recovery integrity.**
Status: **DESIGN — REVISION 2. NOT APPROVED FOR IMPLEMENTATION.**
Revision 1 (`d098d4b`) received an independent architecture review
(`GATE7-DESIGN-REVIEW.md`, Lane W) whose verdict was **APPROVED WITH REQUIRED
CHANGES**. Sol accepted that verdict and issued fifteen required amendments.
This revision applies them.

**No implementation code may be written until this revision receives a SECOND
independent review with ZERO blocking findings.** The production freeze remains
absolute until then.

| | |
|---|---|
| Baseline | `e6321d191afc4bd869732e92ff0ac4945f41fead` (1368 tests passing) |
| Revision 1 | `d098d4b` — reviewed by Lane W |
| Author lane | Lane V (design only — this lane writes no `src/**` and no `tests/**`) |
| Independent review | `GATE7-DESIGN-REVIEW.md` (Lane W) — R-1 … R-14, M-1 … M-10, D-1 … D-8 |
| Capability probe | `GATE7-CAPABILITY-PROBE.md` (Lane U) — **published**; §6 is now measured, not conditional |
| Adjacent-mechanism probe | `GATE7-V1-ADJACENT-PROBE.md` (Lane X) — **NOT YET PUBLISHED.** §5.4A is deliberately left OPEN pending it. |
| Governing brief | `/home/dev/.claude/auto-mode/commissioning/GATE7-BRIEF.md` |
| Installed clients | Claude Code **2.1.237**, Codex CLI **0.149.0** (not 0.147.0 — the brief is stale) |

### Amendment record — Sol's fifteen required changes

| # | Amendment | Where applied | Review finding |
|---|---|---|---|
| 1 | Introduce **WAVE 0** ahead of Wave A for V-1 and V-2 | §12 | R-1, R-2 |
| 2 | V-1 is an **AUTHORITY boundary**, not an evidence-quality issue; do not solve it only by denying `git config` | §5.4A (**OPEN — pending Lane X**) | R-1 |
| 3 | V-2 path inventory unambiguous and machine-safe; NUL-delimited; explicit fail-closed policy; never scope-match the C-quoted display form | §5.4B | R-2 |
| 4 | Separate inventory → scope → content evidence. **Scope violation OUTRANKS evidence-content refusal** | §5.3A, §5.8, §8 | R-4 |
| 5 | Replace class-based prelaunch safety with an explicit **EXECUTION PHASE**; RUNNING begins only after a child process was successfully created | §3.1 | R-3 |
| 6 | Lifecycle feasibility cannot remain disabled in production; Gate 7 cannot PASS while the canonical config bypasses it | §4.13, §9.3 | R-6 |
| 7 | Add the missed crash point: `_land_state` / terminal-state application, with deterministic idempotent restart completion | §5.5A, §5.9 | R-10 |
| 8 | New wave order: **0 → A → B → D → C → E** (D now precedes C) | §12 | R-11 |
| 9 | File-backed streams are **not** redacted; ONE bounded rendering boundary; raw contents never returned directly | §7.4A | R-7 |
| 10 | Persist `hard_deadline_at`; on restart, terminate an `ALIVE_SAME` run past its deadline; never invent exit status | §7.6A | R-5, OQ-D2 |
| 11 | Distinguish `patch_file_complete` from `review_input_complete`; refuse the review if Fable cannot consume the whole authoritative evidence | §5.4C | R-8 |
| 12 | Delete the unkillable A-d formulation; mutants run against the **production-active** lifecycle config; every critical mutant needs a named targeted killer | §11 | R-9, R-14 |
| 13 | Capability/docs baseline is **Codex 0.149.0** | header, §6 | Lane U |
| 14 | Preserve Lane U's capability findings verbatim | §6.0 | Lane U |
| 15 | No implementation until a SECOND independent review with zero blocking findings | this header, §15 | — |

Secondary review findings also applied: R-12 (§4.3 — three profiles in V1),
R-13 (§5.4C — the binary cliff), R-11 (§6.4 — `stdout_bytes` definition),
M-1 … M-10 (§15.2).

> **PRODUCTION FREEZE IS IN FORCE.** `/home/dev/full-voice-agent` is read-only
> (`06bfcd61`, 11 dirty porcelain entries). Nothing in this document is to be
> exercised against it. The three forensic tasks (`3dbd78d6`, `49231f6e`,
> `c5e385c9`) and the `Rakesh` worktree are evidence and are not to be touched.

---

## 0. How to read this document

Sections 1–3 are the part that matters most. The brief is explicit that the
eight defects must **not** be attacked as eight unrelated patches, and §1–§3
are where the shared structure is named. Sections 4–7 are the four subsystems,
each carrying the nine headings §3 demands: *current failure · new invariant ·
state transitions · persistent data · error taxonomy · crash points · tests ·
mutation cases · backward compatibility*. Sections 8–14 are the cross-cutting
obligations (failure ordering, size economics, test doubles, the persisted
mutation suite, wave sequencing, compatibility, open questions).

Everything marked **DECISION** is a choice this document makes that the brief
left open. Revision 1 marked parts of Subsystem C **CONDITIONAL** on Lane U;
that probe has since been published, so nothing in this revision is conditional
— §6.0 records the measured findings and §6.5/§6.6 are written against them. Everything marked **OQ-n** is an open
question aimed at the independent architecture reviewer; §14 collects them.

Measured numbers in this document were produced during design against the
baseline commit, read-only, in disposable temporary repositories. Their
provenance is in Appendix A.

---

## 1. What actually went wrong: three shapes, not eight bugs

The eight defects in §1 of the brief are instances of three structural
mistakes. Naming them is the whole point of designing before implementing,
because a patch aimed at an instance will leave the shape intact.

### Shape 1 — Irreversible state is taken before the decision to take it is
### provably safe

The dispatcher repeatedly commits something it cannot take back, and only
afterwards discovers it should not have.

| Defect | The irreversible thing taken too early |
|---|---|
| **G7-6** | `RESUME_REQUESTED → RUNNING` and `resume_count += 1` happen before context verification, projection and the B1 transport check. A worker that never launches poisons the task as `FAILED`. |
| **G7-7** | `runs/NNN/` is created (as a spool target) before any authoritative run record exists. `run_count` only moves when `dispatcher-result.json` lands. The window between them leaks index identity. |
| **G7-1** | The *dispatch* is committed — worktree created, session minted, worker paid for — while a resume profile that the stored envelope will later demand is already impossible to construct. The irreversible act is starting a task whose own legal future cannot be represented. |

G7-1 is the deep one, and it is why §6 asks for a *future-phase* preflight
rather than a bigger current-phase check. A preflight that only proves "this
run can be built" is structurally incapable of seeing G7-1: the dispatch
profile is legal, and it is the *resume* profile — which does not exist yet and
which the caller cannot influence, because task kind, complexity and risk are
frozen in the envelope — that is infeasible. The only way to see it before the
irreversible act is to evaluate every automatically reachable future lifecycle
phase at dispatch time.

So G7-6 and G7-7 are both "when is irreversible state taken", and G7-1 is
"irreversible state was taken on the strength of a check whose horizon was too
short". One mechanism answers all three: **a PREPARE phase that mutates
nothing, proves the whole reachable lifecycle, and hands an explicit
reservation to an EXECUTE phase that is the only thing allowed to mutate.**

### Shape 2 — A measurement is reported as complete when the thing it measures
### was partly not looked at

| Defect | The claim | What was not looked at |
|---|---|---|
| **G7-2** | `diff_patch_complete: true` | untracked files' contents — `changed_paths` folds them in from `git ls-files --others`, but every byte-producing artefact (`diff_text`, `diff_stat`, `diff_total_bytes`, `evidence/diff.patch`, `git diff --check`, Fable's patch) comes from `git diff <base>`, which does not see them |
| **G7-3** | `"partial stdout preserved in the run directory"` | whether any bytes exist at all. The string is unconditional (`server.py:2054`) |
| **G7-5/G7-1** | "the selection fits" | the *composed* payload of a phase other than the current one |
| **G7-8** | "the run is ours" | whether the process recorded as ours is still that process |

The unifying rule is one sentence, and it is already the house style (`git.py`
fails closed rather than returning an empty `DiffEvidence`, precisely because
"git could not tell us what changed" and "nothing changed" must not produce the
same observation): **a completeness flag must be produced by the same component
that produced the artefact, from its own accounting of what it covered — never
asserted by a caller that happened not to hit an exception.**

### Shape 3 — Process-local knowledge is treated as durable knowledge

| Defect | Held only in one Python process |
|---|---|
| **G7-8** | `RunRegistry`'s `asyncio.Task` objects, and the `asyncio.subprocess` pipe read ends |
| **G7-7** | the intent that `runs/NNN` belongs to the run currently executing |
| **G7-4** | there is *no* durable phase state to report progress from — progress today would have to be invented in the request coroutine |

Gate 6 was explicit that `RunRegistry` is in-process waiter-cancellation
machinery and nothing more (`waiting.py` module docstring), and Lane L's
closeout pinned that with a killed mutant. It was correct then and remains
correct; it simply is not, and never claimed to be, ownership.

The honest consequence, and Sol has said so directly: **a newly started Python
process cannot re-own the previous process's `asyncio` subprocess pipes.**
Subsystem D therefore does not try. It removes the pipes.

---

## 2. The four subsystems and their seams

```
                    ┌──────────────────────────────────────────────┐
   PREPARE          │ A. LIFECYCLE CONTEXT PLANNING & PREFLIGHT     │
   (mutates         │    G7-1  G7-5  G7-6                          │
    nothing)        │    LifecycleFeasibilityReport (all phases)    │
                    └───────────────────┬──────────────────────────┘
                                        │ feasible + composed payload in hand
                                        ▼
                    ┌──────────────────────────────────────────────┐
   RESERVE          │ B1. RUN TRANSACTION                          │
   (first           │     G7-7                                     │
    irreversible    │     reserve_run() -> RunReservation           │
    act)            │     owns runs/NNN, run_id, run_index forever  │
                    └───────────────────┬──────────────────────────┘
                                        ▼
                    ┌──────────────────────────────────────────────┐
   EXECUTE          │ C. TIMEOUT / PROGRESS EXECUTION               │
                    │    G7-3  G7-4                                │
                    │ D. DURABLE OWNERSHIP                         │
                    │    G7-8   ownership record written AFTER the │
                    │           process exists                     │
                    └───────────────────┬──────────────────────────┘
                                        ▼
                    ┌──────────────────────────────────────────────┐
   FINALIZE         │ B2. CANONICAL EVIDENCE                       │
                    │     G7-2                                     │
                    │     one generator -> one patch -> one         │
                    │     accounting -> one completeness verdict    │
                    └──────────────────────────────────────────────┘
```

Seams, stated so a reviewer can attack them:

- **A → B1.** A produces a `LifecycleFeasibilityReport` and, for the phase
  about to run, a fully composed `--append-system-prompt` string already
  measured against the 122,880-byte ceiling. B1 consumes that. A never writes
  task state; B1 is the first write.
- **B1 → C/D.** The `RunReservation` is the only thing that names `runs/NNN`.
  C writes streams into it; D writes ownership into it. Neither allocates.
- **C/D → B2.** B2 is handed a worktree path, a base commit and a
  `RunReservation`. It re-derives nothing about identity.
- **D ↔ B1.** D's restart reconciliation reads reservations. It never creates
  one, never advances the allocator, and never deletes a directory.

---

## 3. Cross-cutting model

### 3.1 REFUSAL is not FAILURE (§7) — carried by an explicit EXECUTION PHASE

**Revision 2. Amendment 5 / review finding R-3.** Revision 1 proposed a
`PrelaunchRefusal` marker base plus an AST test. The reviewer demonstrated that
the AST test **cannot fail**: zero of the reclassified exception classes are
raised in `server.py` at all — they are raised in `runner.py`,
`worker_context.py`, `skills.py` and `validation.py` and merely *propagate
through* the mutation block. An AST scan of `server.py` for
`raise <PrelaunchRefusal subclass>` finds nothing today, nothing after the
regression, and nothing under the mutant meant to exercise it. It also showed
that `ContextTooLarge` is raised in **both** phases from the same class
(`runner.py:811` in preflight, `runner.py:1465` on kernel `E2BIG` at spawn), so
a class-keyed guard would silently swallow a genuine spawn failure and strand
the task in `RUNNING` with no `last_error` — the exact laundering the marker was
supposed to prevent.

**The marker base is deleted from this design.** No `PrelaunchRefusal` class,
no reclassification table, no MRO question, no AST test.

#### DECISION D-1 (revised): the mechanism carries the phase, not the class

```python
class ExecutionPhase(IntEnum):
    """Where the tool body is. Advanced by explicit calls at fixed points.

    NEVER derived from an exception, a state value, or a timestamp. The
    caller's own position in the code is the only input.
    """
    PREPARE  = 1   # nothing has been written. Nothing at all.
    RESERVE  = 2   # run identity allocated; no child exists
    LAUNCH   = 3   # spawn attempted
    EXECUTE  = 4   # a child process exists and is ours
    FINALIZE = 5   # child gone; evidence in flight
    LAND     = 6   # task state being applied

class PhaseTracker:
    """Created at the top of every tool body. `enter()` is a statement, not an
    inference. `phase` is what `_record_failure` keys on."""
    def enter(self, phase: ExecutionPhase) -> None: ...
    @property
    def phase(self) -> ExecutionPhase: ...
```

`_record_failure` becomes:

```python
def _record_failure(self, task_id, exc, *, phase: ExecutionPhase) -> None:
    if phase is ExecutionPhase.PREPARE:
        self._record_refusal(task_id, exc)      # audit only; NO lifecycle write
        return
    ...                                          # existing FAILED transition
```

**Why this is safe where the marker was not.** A mis-wiring — a future edit that
moves a refusal-capable call into the mutation block, or forgets an `enter()` —
leaves the tracker reading a *later* phase than the code actually is. The guard
then **records a failure that should have been a refusal**. That is the safe
direction: a spurious `FAILED` is visible, reportable and recoverable
(`FAILED → RESUME_REQUESTED` is legal). The unsafe direction — swallowing a real
failure into silence — is not reachable, because reaching it requires the
tracker to read *earlier* than the code is, which requires deleting an
`enter()` call that the phase-transition test asserts.

This dissolves OQ-A4, OQ-A5 and OQ-A6 together, exactly as the reviewer
concluded:

- **OQ-A4** — structure stays primary; the laundering mechanism no longer
  exists. The real pin is the per-refusal-class **byte-identical `state.json`**
  integration test (§4.10), which *can* fail.
- **OQ-A5** — `WorktreeBaseMismatch` keeps one class and two meanings, and that
  is now correct *by construction* rather than a documented asymmetry: the phase
  decides, the class does not. **It is not split.**
- **OQ-A6** — no multiple inheritance, no `SkillPolicyViolation(PolicyViolation,
  PrelaunchRefusal)`, no class that means both "a policy was violated" and
  "nothing happened".

#### The second half of amendment 5: RUNNING begins only after a child exists

Today `RUNNING` is entered before the worker is launched — `server.py:937`
(dispatch) and `:1200` (resume) — so every failure between the transition and
the spawn strands the task in `RUNNING`. The new rule:

> **`RUNNING` is the state of "a child process was successfully created and is
> ours". It is entered on the line after `create_subprocess_exec` returns, and
> never before.**

```
dispatch:  PREPARE ─(pure)─► store.create() ─► CREATED ─► ROUTED
                                  ─► RESERVE ─► worktree + B2 verify + anchor
                                  ─► LAUNCH ─► spawn
                                        │ spawn failed  ─► ROUTED ─► FAILED
                                        └ spawn ok      ─► RUNNING ─► EXECUTE …

resume:    PREPARE ─(pure, state.json byte-identical on refusal)
                                  ─► RESERVE
                                  ─► RESUME_REQUESTED
                                  ─► LAUNCH ─► spawn
                                        │ spawn failed  ─► RESUME_REQUESTED ─► FAILED
                                        └ spawn ok      ─► RUNNING (+resume_count) ─► …
```

Both `ROUTED → FAILED` and `RESUME_REQUESTED → FAILED` are already legal
(`models.ALLOWED_TRANSITIONS`), so no transition-table change is needed.

Consequences, all of them wanted:

- **Kernel `E2BIG` never leaves `RUNNING`.** It is a LAUNCH-phase failure and
  lands `FAILED` from `ROUTED`/`RESUME_REQUESTED`. `ContextTooLarge` therefore
  does **not** need splitting — R-3(ii) dissolves.
- `ClaudeBinaryNotFound`, spool-open failure and every other spawn-time fault
  behave the same way.
- **`resume_count` moves with the `RUNNING` transition**, i.e. only when a
  worker really started. A resume whose spawn failed lands `FAILED` with the
  resume budget *unconsumed*. That is more honest than today and costs nothing:
  `FAILED → RESUME_REQUESTED` requires Sol to act, so it is not an infinite
  retry loop, it is a reported failure per attempt.
- `_land_state`'s existing precedence is untouched.

#### Auditability: refusals are recorded, without touching lifecycle state

The reviewer noted a real loss in revision 1: today a refusal on a task in
`AWAITING_SOL_REVIEW` takes `_record_failure`'s *else* branch and persists
`last_error` (`server.py:2712-2714`), so Sol can see via `get_task` **why** a
resume was refused. A guard that simply returns would delete that.

**DECISION D-13.** A PREPARE-phase refusal is appended to
`state/tasks/<id>/refusals.jsonl` (append-only, 0600, one JSON object per line:
`{at, phase, code, message, details, remediation}`) and surfaced by `get_task`
as a bounded `recent_refusals` list. `state.json` is **not** touched.

This preserves auditability while keeping §7's guarantee exact, because §7's
guarantee is about *task lifecycle state* — `state`, `resume_count`,
`run_count` — not about whether the dispatcher may keep a log. The
byte-identical test is deliberately scoped to `state.json` and says so.

#### Byte-identical refusal — the real pin

§7 requires a refused resume to leave task state, `run_count` and
`resume_count` unchanged. The test is not "the values are equal"; it is that
`state/tasks/<id>/state.json` is **byte-identical before and after**, sha256
compared, including `updated_at` and `state_history`. `TaskStore.save()`
rewrites `updated_at` unconditionally, so any path that so much as calls
`save()` on a refusal is caught. This test exists once per refusal class
(§4.10) and is the mechanism's primary proof.

#### Which errors are PREPARE-phase refusals

Not a class hierarchy — a statement about **where each is raised**, which the
phase tracker records at the moment it happens:

| Error | Raised in | Phase(s) it can occur in |
|---|---|---|
| `ValidationBudgetExceeded` | `validation.py:455` | PREPARE only |
| `LifecycleInfeasible` (new) | `lifecycle.py` | PREPARE only |
| `LifecycleProjectionStale` (new) | `lifecycle.py` | PREPARE only |
| `ApprovedSkillChanged` | `worker_context.py:752`, `skills.py:1006` | PREPARE only |
| `SkillPolicyViolation` | `skills.py:948`, `:1116`, `:1128` | PREPARE only |
| `ProjectGuidance*` | `worker_context.py:666`, `:770`, `:786` | PREPARE only |
| `RepositoryBusy` | `locks.py:130` | PREPARE only (retryable) |
| `RepositoryRecoveryRequired` (new) | `locks.py` | PREPARE only (**not** retryable) |
| `EvidenceIncompleteForReview` (new) | `server.py` review path | PREPARE only |
| `ContextTooLarge` | `runner.py:811` **and** `runner.py:1465` | **PREPARE and LAUNCH** — the phase distinguishes them, the class does not |
| `WorktreeBaseMismatch` | `server.py:405` via three call sites | **PREPARE (resume identity) and FINALIZE (post-run choke point)** — same class, two meanings, correct |
| `ClaudeBinaryNotFound` | `runner.py:1440`, `:1448` | LAUNCH only |
| `GitEvidenceCollectionFailed` | `git.py` | FINALIZE only |

The last three rows are the point: **three of the classes in this table appear
in more than one phase, and under a class-keyed guard each would have been a
laundering hazard.** Under a phase-keyed guard none of them is.

### 3.2 The phase model

```
PREPARE ──► RESERVE ──► LAUNCH ──► EXECUTE ──► FINALIZE ──► LAND
mutates     allocates   spawns     child runs   collects     applies the
NOTHING     run         the child  (RUNNING)    evidence     task state
            identity                                          (idempotent)
   │            │           │           │            │            │
   │            │           │           │            │            └─ LAND_INCOMPLETE
   │            │           │           │            └─ FINALIZATION_FAILED
   │            │           │           └─ ORPHANED / TIMED_OUT
   │            │           └─ spawn failed ─► FAILED from ROUTED /
   │            │                              RESUME_REQUESTED. NEVER RUNNING.
   │            └─ ABORTED_PRELAUNCH (index consumed, never reused)
   └─ refusal: state.json BYTE-IDENTICAL. Logged to refusals.jsonl. No FAILED.
```

Two states in that diagram carry the phase model's honest admissions:

`ABORTED_PRELAUNCH` exists because §7's "no run id consumed **if possible**" has
one honest exception: a failure *after* the reservation and *before* the child
exists. Under the revised phase ordering that window contains only RESERVE and
LAUNCH — worktree creation, B2 verification, and the spawn itself — because
everything refusal-capable has already run in PREPARE. The index is burnt and
the run directory records why.

`LAND_INCOMPLETE` is new in revision 2 and answers **amendment 7 / R-10**: the
window between "this run's evidence is complete and `dispatcher-result.json` is
written" and "the task's terminal state has been applied". See §5.5A.

### 3.3 Run identity is allocated, not derived

Every place in `server.py` that says `run_index = record.run_count + 1`
(`server.py:941`, `:1207`, `:1359`) is deleted. Run identity comes from
`reserve_run()` and nowhere else.

### 3.4 What must not regress

The §2 list, restated as the acceptance surface every wave re-runs:

B2 exact-full-SHA `worktree HEAD == envelope.repository.base_commit`
(`server.assert_worktree_base`, three call sites, ancestry/merge-base/prefix/adopt
all refused) · the primary-tree invariant `post_state == pre_state` with **no
excusal path and no ignore list** · scope enforcement · untracked PATH detection
· dispatcher-created external worktrees at `state/worktrees/` · `--safe-mode` ·
no native Skill runtime · no Claude/Codex recursive delegation · no
push/merge/commit/gh/bisect worker authority · blocking MCP semantics with
`asyncio.shield` · zero model-driven `get_task` polling · duplicate-run
prevention (registry key **and** repository lock) · B3 provider-limit
classification from the CLI envelope only, behind the payload veto · exactly
four MCP tools · B4 config authority (`SOL_DISPATCHER_CONFIG` read only to
refuse) · worker/Fable separation (Fable gets zero skill projection) ·
fail-closed everywhere · **no dispatcher-owned `APPROVED` state**.

#### Three §2 items the review found already broken or weakened

The reviewer's §2 audit returned three verdicts that this revision must carry
rather than quietly fix in passing:

| §2 item | Verdict | Where revision 2 answers it |
|---|---|---|
| **scope enforcement** | **already broken at the baseline** for non-ASCII paths, tracked *and* untracked (R-2); and revision 1 **weakened it further** by letting an evidence refusal preempt the scope verdict (R-4) | §5.4B (Wave 0) and §5.3A / §8 (ordering reversed) |
| **primary-tree invariant** | preserved in code, but **blind to `.git/**` writes** that corrupt the primary repository's own diffs. Not a design regression — a pre-existing gap that revision 1 silently depended on | §5.4A, stated explicitly as a limitation of `compare_primary_tree` |
| no push/merge/commit/gh/bisect authority | **arguably already incomplete** — `git config` is a repository-authority mutation and is not on the deny list | §5.4A (Wave 0), pending Lane X's measured set |

These are not new work items invented by the review. They are the honest state
of the baseline, and Wave 0 exists because of them.

---

## 4. SUBSYSTEM A — Lifecycle context planning and preflight

Covers **G7-1** (impossible future profile), **G7-5** (oversized/repetitive
payload), **G7-6** (preflight that mutates).

### 4.1 Current failure

**Measured, at the baseline commit, against the shipped
`config/approved-skills.json` (manifest `2026-08-20.1`) and the shipped
`[skills].max_projected_bytes = 72000`:**

| | |
|---|---|
| Legal envelope shapes (`TaskKind` × `Complexity` × `RiskLevel`) | **120** |
| Dispatch profiles that already exceed the 72,000 B cap | **36 / 120** |
| Resume profiles that exceed it | **50 / 120** |
| Shapes where dispatch fits but resume can never be built — **the exact G7-1 trap** | **14 / 120** |
| Shapes where at least one phase is infeasible | **50 / 120** |

The brief's example (`implementation` / high / high: dispatch 70,623 B, resume
76,708 B) is one of the 14. It is not the worst: `security_sensitive` / high /
high is 89,376 B at dispatch and 95,461 B at resume, and `refactor` / low / low
— a task nobody would think of as large — is **76,513 B at dispatch**, i.e.
already refused today.

So the accurate statement of G7-1 is stronger than "resume adds one skill". It
is: **the selection algebra is set-union over whole general-purpose documents,
and the resulting profile space is 42% infeasible against its own transport
budget.** The 14 traps are the subset where the infeasibility is invisible
until the money has been spent.

Three separate mechanical failures produce this:

1. **Whole-document union.** `SkillProjectionEngine.select` (`skills.py:839`)
   unions four tables and projects each selected file in full. Nothing
   deduplicates *content*; the four selectors happily select seven documents
   that restate the same five ideas.
2. **The caller cannot narrow it.** Selection inputs are `task.kind`,
   `routing.complexity`, `routing.risk`, `RunKind`. The first three are frozen
   in `envelope.json` and the fourth is dispatcher-owned. `ContextTooLarge`'s
   remediation says "narrow the task's allowed_paths so fewer scopes are
   selected" — true for project guidance, **false for skills**. The refusal is
   honest and un-actionable at the same time.
3. **The horizon is one run long.** `_assert_context_fits_the_transport`
   (`runner.py:793`) measures the payload of the invocation being built. There
   is no code anywhere that asks a question about a phase other than the
   current one.

And G7-6, mechanically: on the resume path, `RESUME_REQUESTED` and `RUNNING`
are transitioned at `server.py:1197-1205`, `resume_count` is written there, and
`verify_dispatch_anchor` / `for_worker` / `build_worker_invocation` — the three
things that can raise `ApprovedSkillChanged`, `ProjectGuidance*` and
`ContextTooLarge` — all run at `server.py:1218-1246`, *after*. Every one of
those refusals currently lands the task in `FAILED` via `_record_failure`,
having burnt a resume.

### 4.2 New invariants

- **A-I1 (feasibility).** A task MUST NOT reach `RUNNING` for the first time
  unless every automatically reachable future lifecycle phase has been proven
  constructible **and** transportable, and the proof has been persisted with
  the task.
- **A-I2 (determinism).** The lifecycle profile for a phase is a total function
  of stored task facts and the dispatcher-owned phase. No caller text, no file
  contents, no model, no clock, no filesystem scan enters the selection.
- **A-I3 (monotone lattice).** `VALIDATION_ONLY_RESUME ⊆ CORRECTION_RESUME`
  as a set of projected artifacts. A phase that is proven feasible therefore
  proves every phase below it feasible, and a mis-ordered selection can only
  ever produce a *larger* feasible context, never a smaller infeasible one.
- **A-I4 (provenance).** Every byte of projected methodology is traceable to an
  approved source id, an approved source path, an approved source SHA-256, an
  enumerated section/concept list, a projection SHA-256 and a projection
  version. A source-hash change invalidates the projection until re-reviewed.
- **A-I5 (no runtime shaping).** No runtime summarizer, no LLM compression at
  task time, no truncation anywhere. Size is reduced by review, once, in source
  control.
- **A-I6 (zero mutation).** PREPARE mutates no lifecycle state. On refusal,
  `state.json` is byte-identical.
- **A-I7 (composition is what is measured).** Feasibility is decided on the
  final composed `--append-system-prompt` UTF-8 byte string for each phase, not
  on per-component sums. (This preserves B1's rule; per-component caps summing
  to something legal proves nothing.)

### 4.3 The four profiles

**DECISION D-2.** `LifecyclePhase` is a new dispatcher-owned enum, distinct
from `RunKind` (which stays as the *run* classification). Mapping:

| `LifecyclePhase` | Reached by | `RunKind` | Purpose |
|---|---|---|---|
| `DISPATCH_IMPLEMENTATION` | first worker run | `DISPATCH` | enough methodology to start and complete |
| `CORRECTION_RESUME` | `resume_claude_task` | `RESUME` | respond to Sol/Fable findings. **No initial planning material.** |
| `VALIDATION_ONLY_RESUME` | **never selected in V1** — proven in preflight only (D-3, R-12) | `RESUME` | verification and fixup only |
| `FABLE_REVIEW` | `review_task_with_fable` | `REVIEW` | independent review context. **Zero implementation methodology** (unchanged from Gate 4.5 §15). |

**DECISION D-3 (revised — review finding R-12, answering OQ-A2):
`VALIDATION_ONLY_RESUME` is PROVEN in preflight and NEVER SELECTED in V1.**

Revision 1 proposed selecting it from a predicate over four dispatcher
measurements ANDed with one worker claim (`worker_claims.status == completed`).
The reviewer's objection is accepted in full, and it is sharper than the
byte-consequence argument revision 1 used to defend it:

- `CLAUDE.md` §2 says *"'Implementation complete', 'review complete' and 'user
  approved' are three different things"*, and the predicate concludes that the
  implementation phase is over.
- It would have been **the only place in the entire design where a worker claim
  changes dispatcher behaviour**. That is a boundary worth keeping absolute.
- A-I3's monotone lattice bounds the *byte* cost of choosing wrong. It does not
  bound the *methodology* cost: a task wrongly classified validation-only sends
  a correction worker with no correction-response material.

So, in V1:

```
LifecyclePhase.DISPATCH_IMPLEMENTATION  <- RunKind.DISPATCH
LifecyclePhase.CORRECTION_RESUME        <- RunKind.RESUME    (always)
LifecyclePhase.FABLE_REVIEW             <- RunKind.REVIEW
LifecyclePhase.VALIDATION_ONLY_RESUME   <- proven feasible at preflight,
                                           never selected by any code path
```

The phase stays in the enum and stays in the feasibility matrix, because §6
requires the matrix to cover it and because proving a subset feasible is free
once its superset is proven (A-I3). A test asserts that **no runtime path
returns it** — the selector is a total function over three values, and the
fourth is reachable only from the preflight enumerator. When a future gate wants
it, the question to answer is "what stored fact makes this Sol's decision rather
than the dispatcher's?", not "is the predicate accurate enough?".

Cost: correction resumes carry the correction profile's bytes rather than the
validation-only profile's — 12,000 B against a possible 6,000 B (§9.2). The
compaction has bought that back many times over.

### 4.4 Hash-pinned compact projections (§5)

**DECISION D-4.** Compact lifecycle artifacts are **new source-controlled files
in this repository**, derived by human/Sol review from already-approved skill
sources. They are not generated at runtime and not generated by a build step.

```
config/
  approved-skills.json                  (unchanged — still the source of truth
                                         for what may be read at all)
  approved-lifecycle-profiles.json      (NEW — the provenance manifest)
  lifecycle/
    v1/
      core-engineering-loop.md          (NEW — reviewed compact artifact)
      correction-response.md            (NEW)
      validation-discipline.md          (NEW)
      planning-and-decomposition.md     (NEW)
      security-review-checklist.md      (NEW)
      ...
```

`approved-lifecycle-profiles.json` schema (strict, `extra="forbid"`, loaded by a
new `lifecycle.py` with the same fail-closed discipline as `skills.py`):

```jsonc
{
  "schema_version": "1.0",
  "manifest_version": "2026-08-24.1",
  "approved_by": "...",
  "projection_mode": "inert_text",          // Literal, like skills.projection_mode
  "native_skill_runtime": false,            // Literal false
  "fail_on_drift": true,                    // Literal true
  "artifacts": [
    {
      "id": "lc.core-engineering-loop",
      "path": "config/lifecycle/v1/core-engineering-loop.md",
      "projection_sha256": "…64 hex…",
      "projection_bytes": 4211,
      "projection_version": "v1",
      "derived_from": [
        {
          "source_skill_id": "agent-skills.incremental-implementation",
          "source_path": "/home/dev/.claude/plugins/.../SKILL.md",
          "source_sha256": "…64 hex…",       // MUST equal approved-skills.json
          "source_sections": ["## The loop", "## When to stop"],
          "concepts": ["small verified increments", "run the real command"]
        },
        { "source_skill_id": "superpowers.test-driven-development", … }
      ]
    }
  ],
  "profiles": {
    "DISPATCH_IMPLEMENTATION": ["lc.core-engineering-loop", "lc.validation-discipline"],
    "CORRECTION_RESUME":       ["lc.correction-response", "lc.validation-discipline"],
    "VALIDATION_ONLY_RESUME":  ["lc.validation-discipline"],
    "FABLE_REVIEW":            []
  },
  "conditional": {
    "by_task_kind":  { "security_sensitive": ["lc.security-review-checklist"], … },
    "by_complexity": { "high": ["lc.planning-and-decomposition"] },
    "by_risk":       { "high": [], "critical": [] }
  }
}
```

Verification pipeline, per artifact, at every projection:

```
manifest entry
  -> for each derived_from: source id must be an APPROVED skills.json entry
  -> source_sha256 must equal approved-skills.json's skill_md_sha256 for it
  -> source file on disk must still hash to that value  (reuses skills._verified_bytes)
  -> projection file must hash to projection_sha256
  -> projection file must pass the SAME content refusal rules as skills.py
     (_frontmatter_keys / ALLOWED_FRONTMATTER_KEYS / DYNAMIC_COMMAND_MARKERS)
  -> INERT TEXT
```

Two properties follow, and both are load-bearing:

- **A source hash change invalidates the compact projection.** The projection
  file itself is unchanged, so a naive hash check on the artifact would pass;
  the manifest binds the *source* hash too, so an upstream plugin update raises
  `LifecycleProjectionStale` until the artifact is re-reviewed. This is the
  §5 requirement and the reason the manifest cannot just be a list of files.
- **No directory is trusted, nothing is discovered, nothing executes.** The
  same rules `skills.py` already enforces (§11 of Gate 4.5) apply verbatim; the
  compact artifacts are additionally *inside this repository*, so they are
  reviewed under the same commit discipline as the code.

**Dispatcher policy still overrides projected methodology.** The
`ENVELOPE_PRECEDENCE_PREAMBLE` (`worker_context.py:141`) is emitted unchanged,
immediately before the first projected block, and the §14 section order is
preserved. Compact artifacts occupy the `CORE_APPROVED_SKILLS` /
`CONTEXTUAL_SKILLS` sections; no new section is introduced, so
`SECTION_ORDER` and the fingerprint recipe stay stable.

**Relationship to `skills.py`.** `SkillProjectionEngine` is *not* deleted. It
remains the verifier of source approval and hashes; `lifecycle.py` depends on
it for `_verified_bytes` and reuses its content-refusal rules. What changes is
that the composer selects **lifecycle artifacts** rather than whole skill
documents. Behind a config flag (`[lifecycle].enabled`), so a dispatcher
configured exactly as today behaves exactly as today — see §4.10.

### 4.5 Preflight and the feasibility matrix (§25 — INTERNAL, not a tool)

```python
# lifecycle.py — INTERNAL. Never registered with MCPServer. §1: four tools, forever.

@dataclass(frozen=True)
class PhaseFeasibility:
    phase: LifecyclePhase
    profile_id: str
    profile_version: str
    artifact_ids: tuple[str, ...]
    skill_source_ids: tuple[str, ...]
    projected_skill_bytes: int
    projected_guidance_bytes: int
    dispatcher_authored_bytes: int
    composed_append_system_prompt_bytes: int     # THE number that decides
    transport_ceiling_bytes: int                 # MAX_APPEND_SYSTEM_PROMPT_BYTES
    approved_hashes_verified: bool
    required_deny_patterns_present: bool
    supporting_files_verified: bool
    review_context_available: bool               # FABLE_REVIEW only
    feasible: bool
    refusal_code: str | None
    refusal_detail: str | None

@dataclass(frozen=True)
class LifecycleFeasibilityReport:
    schema_version: Literal["1.0"]
    task_id: str
    envelope_digest: str            # sha256 over the envelope's selection-relevant facts
    manifest_version: str
    computed_at: datetime
    phases: tuple[PhaseFeasibility, ...]
    feasible: bool                  # AND over phases

def feasibility_report(envelope, *, config, composer, identity) -> LifecycleFeasibilityReport
def assert_lifecycle_feasible(report) -> None      # raises LifecycleInfeasible
```

Rules:

- **Every automatically reachable phase, and no others.** `FABLE_REVIEW` is
  included because `review_task_with_fable` is reachable from
  `AWAITING_SOL_REVIEW` for every task. The resume phases are included because
  `AWAITING_SOL_REVIEW → RESUME_REQUESTED` is legal for every task with
  `max_resume_count > 0`. §25's "do not include optional future actions the
  current task can never reach" is honoured concretely: **when
  `envelope.execution.max_resume_count == 0`, the two resume phases are
  excluded from the report** and recorded as `unreachable`, because that task
  can never resume.
- **Composition, not summation.** Each phase's number is produced by actually
  composing the context through `WorkerContextComposer` and measuring
  `len(append_system_prompt.encode("utf-8"))`. This costs four compositions at
  dispatch time; they are pure CPU over already-read, already-hashed files.
- **Persisted.** `state/tasks/<id>/preflight/lifecycle-feasibility.json`, plus a
  summary on `TaskRecord` (see §4.7).
- **Re-checked, not re-derived, on resume.** A resume recomputes the report for
  the phase it is about to run and compares `manifest_version` and the phase's
  `profile_id`/`profile_version` against the persisted one. A *drift* is a
  refusal (`LifecycleProjectionStale`); an unchanged manifest with a still-
  feasible phase proceeds. The dispatch-time report is never rewritten.

**Why this catches G7-1 and the current design cannot.** At dispatch, phase
`CORRECTION_RESUME` is composed and measured even though no resume has been
requested. For the 14 trap shapes the composed byte count exceeds the ceiling,
`feasible` is `False`, and `assert_lifecycle_feasible` raises
`LifecycleInfeasible` **in PREPARE** — before `store.create()`, before the
worktree, before the session, before a single token is paid for.

### 4.6 State transitions

PREPARE adds no `TaskState`. That is deliberate and is the point: **Subsystem A
introduces zero new task states.** The transitions it touches are the ones it
must now happen *before*:

```
dispatch:  (no task exists)
             │
             ├── PREPARE: budget · repo authorization · base resolution ·
             │            lifecycle feasibility (4 phases) · guidance identity ·
             │            composition · B1 transport check
             │   refusal ──► nothing exists. No task id. PREPARE-phase refusal.
             ▼
           CREATED ──► ROUTED ──► (RESERVE) ──► RUNNING ──► …

resume:    AWAITING_SOL_REVIEW | FABLE_REVIEWED | TIMED_OUT | BLOCKED |
           FAILED | POLICY_VIOLATION
             │
             ├── PREPARE: resume_plan (cap) · budget · repo authorization ·
             │            repo lock strategy · worktree identity + B2 base ·
             │            dispatch-anchor verification · phase selection ·
             │            lifecycle artifact + source hash verification ·
             │            guidance verification · composition ·
             │            B1 transport check · CLI argv construction ·
             │            schema projection · reservation readiness
             │   refusal ──► state.json BYTE-IDENTICAL. PREPARE-phase refusal.
             ▼
           RESUME_REQUESTED ──► RUNNING ──► …
```

The critical structural change: **`build_argv(spec)` is called in PREPARE**, so
`ContextTooLarge` is raised before `RESUME_REQUESTED`. The argv it produces is
carried into EXECUTE rather than rebuilt, so the thing measured is the thing
executed. (`build_argv` is already pure and deterministic — `runner.py:625` —
which is what makes this safe.)

### 4.7 Persistent data

New file `state/tasks/<id>/preflight/lifecycle-feasibility.json` — the full
`LifecycleFeasibilityReport`.

New `TaskRecord` fields (all `| None`, all defaulting to `None`, so every
existing `state.json` still loads):

```python
class LifecyclePreflightRecord(StrictModel):
    schema_version: Literal["1.0"]
    manifest_version: NonEmptyStr
    envelope_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    computed_at: datetime
    feasible: bool
    phases: list[str]                      # phase ids proven
    unreachable_phases: list[str] = []     # e.g. resume phases when cap == 0
    max_composed_bytes: int = Field(ge=0)  # worst phase, for auditing
    report_path: str

class TaskRecord(StrictModel):
    ...
    lifecycle_preflight: LifecyclePreflightRecord | None = None
```

New `RunMetadata` field: `lifecycle_phase: str | None = None` — which phase this
run was composed for. `None` for pre-Gate-7 runs.

`_TRANSITION_UPDATABLE_FIELDS` in `state.py:64` gains nothing: the preflight
record is written by an explicit `save()` in PREPARE… **no.** It is written by
the first EXECUTE-phase write, together with `store.create()` for dispatch.
PREPARE writes nothing. For resume, the recomputed report is written as part of
the `RESUME_REQUESTED` transition. This is a small point that a reviewer should
check hard (**OQ-A3**): persisting the proof is itself a mutation, so it must be
sequenced after the last refusal, which means the proof lands *with* the first
mutation rather than before it.

### 4.8 Error taxonomy

| Code | Class | Phase | Retryable | Meaning |
|---|---|---|---|---|
| `LifecycleInfeasible` | `DispatcherError` | PREPARE | no | Some automatically reachable phase cannot be composed or transported. Details name the phase, its composed bytes, the ceiling, the artifact ids, and every phase's number so Sol can see the shape. |
| `LifecycleProjectionStale` | `DispatcherError` | PREPARE | no | A compact artifact's `projection_sha256` or one of its `derived_from[].source_sha256` no longer matches. Never recalculated and accepted. |
| `LifecycleProfileChanged` | `DispatcherError` | PREPARE | no | A task dispatched under one lifecycle configuration is being resumed under another (OQ-A7). Fail closed in both directions. |
| `LifecycleProfileUnknown` | `ConfigurationError` | load | no | Manifest names a phase or artifact that does not exist, or `profiles` is not exhaustive over `LifecyclePhase`. Fails at config load, like `SelectionMap._exhaustive`. |
| `ContextTooLarge` | existing class, **unchanged and unsplit** | PREPARE **and** LAUNCH | no | The phase distinguishes the preflight refusal from the kernel-`E2BIG` spawn failure. Revision 1 would have had to split it; §3.1 does not. |
| `ApprovedSkillChanged` | existing class, unchanged | PREPARE | no | Raised by `verify_dispatch_anchor` / `skills.verify`, now *called* in PREPARE. |
| `ProjectGuidance*` | existing classes, unchanged | PREPARE | no | Same. |
| `SkillPolicyViolation` | existing class, **unchanged** | PREPARE | no | Stays a plain `PolicyViolation` subclass. No marker base, no multiple inheritance, no MRO hazard — OQ-A6 dissolved by §3.1. |

**No exception class in this table is modified.** That is the point of the
phase-carrying mechanism: the taxonomy describes *where* each error can occur,
and `_record_failure` keys on the phase the caller declares, not on the type it
caught.

Every refusal payload is bounded per §29: ids and byte counts, never text.
Specifically, `LifecycleInfeasible` must **not** quote the composed payload,
the projected artifacts, or the guidance — a size failure must not become a
content leak, exactly as `runner._context_too_large` already guarantees.

### 4.9 Crash points

| Crash after | Consequence | Recovery |
|---|---|---|
| feasibility computed, before `store.create()` | nothing on disk | none needed — the task does not exist |
| `store.create()`, before preflight record written | task exists with `lifecycle_preflight is None` | treated as a pre-Gate-7 task on the next touch; a resume recomputes and refuses if infeasible. **Never assumed feasible.** |
| preflight written, before reservation | task exists, no run | next dispatch/resume reserves normally |
| resume PREPARE crash (process death) | `state.json` untouched | task is exactly where it was |

The dangerous shape to design against is "preflight record exists but is
stale". Guarded by `envelope_digest` + `manifest_version`: a resume that
recomputes a different digest treats the persisted report as absent and
re-proves.

### 4.10 Tests (§29, §30)

Unit (`tests/unit/test_lifecycle.py`, `test_lifecycle_preflight.py`):

- **the 120×2 matrix is enumerated as a test.** Every legal
  `TaskKind × Complexity × RiskLevel × LifecyclePhase` combination is composed
  and measured, and the test asserts **zero infeasible phases**. This is the
  single most valuable test in Subsystem A: it is the assertion that would have
  failed at the baseline commit for 50 of 120 shapes, and it makes a future
  manifest edit that reintroduces a trap fail immediately rather than in
  production.
- A-I2 determinism: the matrix is computed twice in one process and once in a
  fresh interpreter; all three must be identical.
- A-I3 monotone lattice: `artifacts(VALIDATION_ONLY_RESUME) ⊆
  artifacts(CORRECTION_RESUME)` for every shape, by set containment.
- profile selection is a pure function: given the same stored facts it returns
  the same profile with no filesystem, clock or environment access — asserted
  by running the selector with `os.environ` cleared and the CWD moved.
- `approved-lifecycle-profiles.json` exhaustiveness: a missing `LifecyclePhase`
  key, an unknown artifact id, or a `derived_from` naming a skill absent from
  `approved-skills.json` all fail at load with `LifecycleProfileUnknown`.
- content refusal parity: a compact artifact carrying frontmatter mechanisms or
  a dynamic-command construct is refused by the same rules `skills.py` applies.

Real disposable integration (`tests/integration/test_lifecycle_preflight.py`):

- **deliberately oversized future resume refuses the INITIAL dispatch.** A
  temporary manifest whose `CORRECTION_RESUME` profile exceeds the ceiling is
  dispatched against a real temp repository; the call returns
  `LifecycleInfeasible`, **no task directory is created**, no worktree exists,
  and no worker binary was executed (asserted by a fake binary that writes a
  marker file when run).
- **high/high dispatch fits and resume also fits** under the new profiles —
  the positive control, so the refusal test cannot pass by refusing everything.
- **resume preflight refusal leaves state byte-identical.** `sha256` of
  `state.json` before and after, plus explicit assertions on `resume_count`,
  `run_count` and `state`. Run once per refusal class
  (`LifecycleInfeasible`, `LifecycleProjectionStale`, `ContextTooLarge`,
  `ApprovedSkillChanged`, `ProjectGuidanceResumeDrift`,
  `ValidationBudgetExceeded`).
- **source hash drift invalidates the compact projection.** A **copy** of the
  pinned install root in `tmp_path` has one source `SKILL.md` byte changed; the
  projection file is untouched; the resume refuses with
  `LifecycleProjectionStale`. (The real install root is never written.)
- **planning is omitted from correction resume where designed**, and there is
  **no redundant full code-review + receiving-review pair** — asserted on the
  composed text by artifact id, not by byte count.
- **all four phases are proven before the first worker**, asserted by reading
  the persisted `lifecycle-feasibility.json` and checking each phase is present
  with `feasible: true`, or listed under `unreachable_phases` with a reason.
- `max_resume_count == 0` excludes both resume phases as `unreachable` (§25's
  "do not include optional future actions the current task can never reach").

Static/structural:

- **a call-site whitelist, asserted by AST.** An explicit, source-controlled list
  of the functions permitted inside the mutation block. A mutant that moves a
  refusal-capable call in must **also edit the whitelist**, which is a visible
  act in the diff. This replaces revision 1's `raise`-statement scan, which
  could not fail (R-3): the classes are raised in `runner.py`,
  `worker_context.py`, `skills.py` and `validation.py` and merely propagate
  through `server.py`.
- **a phase-transition test**: every tool body's `PhaseTracker` must pass through
  the phases in order, and a missing `enter()` is caught by asserting the phase
  observed at each recorded artefact write.

### 4.11 Mutation cases

| # | Mutant | Killer |
|---|---|---|
| 1 | resume profile adds full planning again | correction-resume artifact-id assertion; the 120×2 matrix |
| 2 | resume profile adds the overlapping review skill again | no-redundant-pair assertion; the matrix |
| 3 | skip lifecycle future-phase preflight (evaluate only the current phase) | oversized-future-resume refuses initial dispatch |
| 4 | move preflight after the `RUNNING` transition | byte-identical `state.json` test |
| A-a | accept a drifted source hash and recompute | source-hash-drift test |
| A-b | let `_record_failure` transition on a PREPARE-phase failure | `test_resume_refusal_leaves_state_byte_identical` (per refusal class) |
| A-c′ | move a refusal-capable **call** back inside the mutation block | `test_mutation_block_call_site_whitelist` (AST) — the mutant must also edit the whitelist |
| A-g | delete an `enter()` call so the tracker reads an earlier phase | `test_phase_advances_at_every_artefact_write` |
| A-h | enter `RUNNING` before the spawn returns | `test_spawn_failure_never_leaves_running` (kernel E2BIG + missing binary) |
| A-d | measure per-component byte sums instead of the composed payload | matrix test with a shape whose components each fit and whose composition does not |
| A-e | make profile selection read the resume instruction text | determinism test (cleared env, moved CWD) |
| A-f | drop `unreachable_phases` and prove resume phases for a `max_resume_count == 0` task | §25 exclusion test |

### 4.12 Production activation is part of Wave A, not a later decision

**Amendment 6 / review finding R-6. This section overrides any reading of §4.13
that suggests the flag may stay off.**

Revision 1 said `[lifecycle] enabled = false` by default. The reviewer showed
why that cannot stand: with the flag off, the whole-document union is still what
production composes, so §35's report rows — *dispatch bytes · correction-resume
bytes · validation-resume bytes · G7-5 compact lifecycle profiles + bytes
before/after per phase* — are **unchanged**, and **G7-5 cannot be reported green
on a default install**. Gate 7 would be claiming a fix that no running
dispatcher performs.

Worse, the two halves of Wave A interact badly if only one is on. Flag **off**
plus preflight **on** converts 36/120 dispatch shapes and 50/120 overall from
"fails late, after burning a task id, three transitions and a real git worktree"
into "refused at PREPARE". That is *correct*, and it is a hard functional
regression for anyone living with the late failure — `refactor` (12/12),
`large_refactor` (12/12), `security_sensitive` (6/12) and `migration` (6/12) all
simply stop dispatching.

**DECISION D-14. The flag exists for one wave and then flips.**

| | |
|---|---|
| During Wave A development | `[lifecycle].enabled` defaults `false`; both halves are built and tested behind it |
| **Wave A acceptance criterion** | the canonical production `config/dispatcher.toml` sets `[lifecycle].enabled = true` **and** `[lifecycle].preflight_required = true`, and the full 120×2 matrix is feasible under it |
| After Wave A | the flag remains only as a rollback lever; a dispatcher started with it `false` **logs a startup warning naming Gate 7** |
| Gate 7 PASS | **impossible while the canonical production configuration bypasses lifecycle profiles or future-phase preflight.** `scripts/check-production-activation.py` gains a check for both, and §35's report states the shipped default explicitly. |

The feasibility preflight is precisely the safety net that makes flipping safe —
without it, compaction changes what workers are told with nothing proving the
result is transportable; without compaction, the preflight refuses 42% of the
envelope space. **They land together or the wave has moved the failure earlier
without removing it.** That is the whole of R-6, and it is accepted.

### 4.13 Backward compatibility

- Existing `state.json` files load unchanged (all new fields default `None`).
- Existing `envelope.json` files are untouched; `SCHEMA_VERSION` does **not**
  bump, because nothing in `TaskEnvelope` changes.
- `TaskRecord.context_fingerprint` and `RunMetadata.context_fingerprint` keep
  their recipes. Enabling `[lifecycle]` changes the *selection*, which is the
  same class of change as the manifest adding `receiving-code-review` on
  resume — legitimately different, deliberately not drift (`worker_context.py`
  `verify_dispatch_anchor` docstring). **OQ-A7, now decided:** a task dispatched
  with `[lifecycle]` off and resumed with it on would silently change the
  worker's methodology, so it is a **PREPARE-phase refusal**
  (`LifecycleProfileChanged`), symmetric with the existing "dispatched with
  skills, now disabled" refusal at `worker_context.py:752`. The same fail-closed
  rule in both directions. Because D-14 flips the default at Wave A acceptance,
  this refusal is a one-time migration condition for tasks dispatched before the
  flip, not an ongoing behaviour — and those tasks are returned to Sol rather
  than silently resumed under different methodology.

---

## 5. SUBSYSTEM B — Complete evidence and the run transaction

Covers **G7-2** (untracked content absent from evidence) and **G7-7** (run
directory without an authoritative reservation).

They are one subsystem because they share a consumer: `evidence/diff.patch`
and `runs/NNN/` are the two artefacts a reader treats as authoritative, and both
are currently produced by code that can be wrong without saying so.

### 5.1 Current failure — evidence (G7-2 and three findings beyond it)

**G7-2 as briefed.** `collect_diff_evidence` (`git.py:660`) folds untracked
paths into `changed_paths` via `git ls-files --others --exclude-standard`, but
`diff_text`, `diff_stat`, `diff_total_bytes` and `diff_check_passed` all come
from `git diff <base>`, which cannot see an untracked file.
`write_full_diff` (`git.py:755`) runs the same `git diff <base>` into
`evidence/diff.patch`. `Dispatcher._write_evidence` (`server.py:2431`) then sets
`diff_patch_complete = True` on the sole basis that `write_full_diff` did not
raise. Fable reads `evidence/diff.patch` via `_prompt_diff_text`
(`server.py:2353`). So a 191-line new test file is listed in `changed_paths`,
absent from every byte of evidence, and the record says the patch is complete.

**Finding V-1 (new, found while designing this document; verified live in a
disposable repository — Appendix A).** The evidence pipeline honours in-tree
`.gitattributes`. `Bash(git config:*)` is **not** in
`CORE_DENIED_GIT_OPERATIONS` and `.gitattributes` is an ordinary file, so a
worker can install a diff driver and change what the evidence says:

| Attribute | Effect on `git diff <base>` today |
|---|---|
| `path diff=x` + `diff.x.textconv=/bin/echo LIE` | the patch shows `+LIE` instead of the real added line, for **tracked and untracked** paths. Defeated by `--no-textconv`. |
| `path -diff` | the patch shows `Binary files a/X and b/X differ` — **content omitted entirely** — while `diff_patch_complete` is `true`; `--stat` reports `Bin 2 -> 10 bytes`; `--numstat` reports `-\t-`; and **`git diff --check` returns exit 0 (clean) for a file with trailing whitespace**. `--no-textconv` does *not* help. `--text` restores the content but **does not** restore `--check`. |

That last row is the important one: `diff_check_passed = True` can be produced
today by a file that was never checked. It is the same shape as G7-2 — a
completeness claim asserted by a caller that did not hit an exception.

**Finding V-2 (new).** `_fold_untracked` (`git.py:645`) splits
`git ls-files --others` on newlines. Git's default `core.quotePath=true` emits
C-quoted, backslash-escaped names for anything non-ASCII or containing special
bytes. Verified: a file named `café.txt` enters `changed_paths` as the literal
9-character-plus-quotes string `"caf\303\251.txt"`. That string is then handed
to `check_scope`, whose globs will not match it. **Scope enforcement is
currently blind to non-ASCII new files**, and a tab or newline in a name is
worse — a newline in a filename would split one path into two bogus entries.

**Finding V-3 (new).** `git diff --no-index --check` exits **3** when it finds
whitespace problems (1 for "differences exist" + 2 for "problems found").
`_git_checked`'s `ok_returncodes=(0, 1, 2)` at `git.py:722` would treat that as
a collection failure. Any implementation that reuses the existing helper for
the untracked check must widen it deliberately, not accidentally. Latent — no
`--no-index` call site exists today — so it is a Wave B item, not a live defect.
It interacts with V-1: the `-diff` attribute also suppresses `--check` under
`--no-index`.

**Findings V-4 and V-5 (Lane X — both live, both worse than V-1).** Full
treatment in §5.4A(a2); named here because they belong in the list of what is
actually wrong today:

- **V-4 — `git update-index --assume-unchanged` / `--skip-worktree`.** Not
  denied, and not reached by any deny prefix. Erases a modified *or deleted*
  tracked file from **every** surface including **`changed_paths` itself** — the
  one surface every other suppression vector still populated. Verified end to
  end through the real dispatcher code: `changed_paths=[]`, `scope.valid=True`,
  backdoor on disk. Run as `git -C <primary>` it also blinds
  `primary_tree_status` and `compare_primary_tree`. **It defeats scope
  enforcement and the primary-tree interference check simultaneously.**
- **V-5 — a self-hiding `.gitignore`.** `changed_paths=[]`, `valid=True`, using
  the **`Write` tool alone** — there is no git subcommand for a deny to catch.
  `$GIT_COMMON_DIR/info/exclude` does the same and blinds the primary tree as
  well.

Neither is among the brief's eight defects. Both are G7-2 bypasses simpler than
G7-2 itself, and both are *scope-enforcement* bypasses rather than mere
evidence-completeness defects. **They set the scope of Wave 0.**

### 5.2 Current failure — run transaction (G7-7)

```
server.py:941    run_index = record.run_count + 1        # derived, not allocated
server.py:1031   invocation = self._with_run_spools(...)  # -> _run_dir() -> mkdir runs/NNN
server.py:2204   self.store.append_run(...)               # -> run_count = max(run_count, N)
```

Between `_run_dir()` (which does `mkdir(parents=True, exist_ok=True)`) and
`append_run()` there is the entire worker run, evidence collection and
validation. Any failure in that window — and there are many, including every
`WorktreeBaseMismatch`, every `GitEvidenceCollectionFailed`, and process death
— leaves `runs/NNN/` populated with real streams while `run_count` still reads
`N-1`. The next run computes `N` again, `exist_ok=True` silently accepts the
existing directory, and `stdout.raw`/`stderr.log` are **truncated and
overwritten** (`_open_spool` uses `O_TRUNC`, `runner.py:1304`).

Note also `server.py:1346`: the review path re-reads the record under the lock
specifically because `run_count + 1` would otherwise be stale. That comment is
a description of the defect, worked around in one place out of three.

### 5.3 New invariants

**Evidence**

- **B-I1 (one generator).** Exactly one component produces the canonical patch,
  the stat, the byte accounting, the check verdict and the changed-path set.
  `collect_diff_evidence`, `write_full_diff`, `diff_stat`, `diff_total_bytes`,
  `diff_check` and Fable's patch input are all views of its single output.
- **B-I2 (completeness is produced, not asserted).** Every completeness flag is
  computed by the component that produced the artefact, from its own accounting
  of what it covered. No caller may set one. *(The reviewer called this the
  design's best idea; revision 2 extends it to a second flag — see B-I7.)*
- **B-I3 (no silent omission — a per-path BUCKET, never a run-fatal).** Every
  changed path lands in exactly one of `represented`, `content_omitted`
  (honest, with a reason) or `refused` (typed, with a reason).
  `patch_file_complete` is `False` whenever the second or third is non-empty.
  **A per-path refusal never prevents the changed-path inventory from being
  produced, and therefore never prevents the scope and primary-tree verdicts
  from being decided** (§5.3A, amendment 4 / R-4). Revision 1's §5.8, which made
  `EvidenceUnsupportedFile` fatal to the run, contradicted this invariant and is
  deleted.
- **B-I4 (evidence authority — revised, amendment 2 / R-1).** Worker-controlled
  repository configuration, attributes and index state **cannot alter what
  evidence says, and cannot cause dispatcher evidence collection to execute a
  worker-selected program.** This is an authority boundary, not a diff-flag
  question; it is specified in §5.4A and is **OPEN pending Lane X's measured
  set**.
- **B-I5 (no index mutation).** The task worktree's index is never written.
  `git add -N` is not used. `git update-index` is not used. Untracked content is
  obtained with `git diff --no-index`, which reads two paths and touches
  nothing.
- **B-I6 (path identity — revised, amendment 3 / R-2).** The authoritative
  changed-path inventory is byte-oriented and NUL-delimited, produced by **every**
  path-producing git call (not only `ls-files`), and **git's C-quoted display
  representation never reaches scope matching**. A path the dispatcher's path
  model cannot represent is refused explicitly, fail-closed. §5.4B.
- **B-I7 (Fable receives complete evidence or refuses — two flags, amendment 11
  / R-8).** `patch_file_complete` describes the file on disk;
  `review_input_complete` describes what the reviewer will actually *receive*.
  The review is gated on **both**. A complete 400 KB patch clipped to a
  120,000-character prompt is not a complete review. §5.4C.
- **B-I12 (finalisation is idempotent — amendment 7 / R-10).** A run whose
  evidence is complete but whose task state was never applied is completable,
  deterministically and idempotently, by a restarted dispatcher. §5.5A.

**Run transaction**

- **B-I8 (allocation, never derivation).** `run_index` comes only from
  `reserve_run()`.
- **B-I9 (exclusive ownership).** A reservation owns `runs/NNN`, its `run_id`
  and its `run_index` permanently. No later run reuses the index, whatever
  happened to the earlier one.
- **B-I10 (monotone allocation across restart).** The allocator is monotone and
  survives process death, crash between any two steps, and an orphan directory
  left by a previous process.
- **B-I11 (never erase).** A failed run is never deleted, never decremented,
  never renumbered. Its reservation records the terminal run state.

### 5.3A Three separated concerns, in a fixed order (amendment 4 / R-4)

Revision 1 fused path inventory, scope enforcement and content generation into
one component and one failure mode. The reviewer showed the consequence:
§8's ladder put *unsupported untracked file → evidence failure → FAILED* **above**
*scope violation → POLICY_VIOLATION*, so a worker that went out of scope **and**
left one symlink, FIFO, oversized or unreadable file would land `FAILED` with
the scope verdict **never computed at all**. That is a one-command downgrade
from POLICY_VIOLATION to FAILED — and POLICY_VIOLATION is the signal Sol reads
to know a boundary was breached. It is a regression against §2's "scope
enforcement" and §28's "scope violation **still** outranks worker success", and
it is not possible today, because `_fold_untracked` merely lists paths.

**DECISION D-15. Three components, three outputs, strictly ordered:**

```
 1. INVENTORY  ──►  PathInventory        cannot fail on file content or type.
    (§5.4B)         (authoritative        Answers only: which repo-relative byte
                     changed-path set)    paths changed? Enumerates tracked
                                          (diff --name-only -z) and untracked
                                          (ls-files -z --others). lstat is NOT
                                          consulted. A symlink, FIFO, 70 KB name
                                          or unreadable file is a PATH like any
                                          other and is inventoried.
                          │
                          ▼
 2. POLICY    ──►  ScopeCheck +          decided on the INVENTORY, always, for
                   primary-tree verdict  every run that produced one. Never
                                         downstream of content generation.
                          │
                          ▼
 3. CONTENT   ──►  CanonicalEvidence     may bucket individual paths as
    (§5.4)          + patch_file_complete `content_omitted` or `refused`.
                    + review_input_       Refusals are per-path facts, not run
                      complete            outcomes (B-I3).
```

Only step 1 can fail the run outright, and only for reasons that make the
*inventory itself* untrustworthy — git could not be run, git exited non-zero,
`--show-toplevel` disagreed. That is the existing fail-closed rule in `git.py`
and it is unchanged.

Three consequences, each of which reverses a revision-1 position:

- **A symlink / oversized / unsupported file that is OUTSIDE SCOPE still lands
  `POLICY_VIOLATION`,** on the strength of its authoritative path. It is not
  laundered into `FAILED`.
- **A benign symlink no longer fails an otherwise complete run.** A
  `node_modules` link or a symlinked config buckets as `refused`, forces
  `patch_file_complete = False` (so Fable refuses per B-I7), and the run lands
  wherever the policy ladder puts it. Revision 1 would have failed the whole run
  after all the work was done, with no remediation but manual deletion.
- **B-I3 is the design; revision 1's §5.8 was wrong** and is deleted.
  `EvidenceUnsupportedFile` survives only as a *per-path reason string*, not as
  a raised exception that ends a run.

If the run must additionally fail because evidence is unusable, it fails **after
the policy ladder has run**, not instead of it (§8, rows reordered).

### 5.4 Design — the canonical evidence generator

New module `evidence.py`. `git.py` keeps its primitives; `collect_diff_evidence`
and `write_full_diff` become thin wrappers, or are folded in (**OQ-B4**: keep
them as a compatibility surface, or delete and update the ~6 call sites?).

**Git invocation policy.** Revision 1 specified a diff-only hardened prefix here.
The reviewer showed that a diff-only prefix leaves the authority hole open, so
the invocation policy is no longer a property of this generator — it is a
**global dispatcher-wide policy specified in §5.4A**, which every git call in
`src/**` uses, and which is **OPEN pending Lane X's measured set**. The
generator consumes it; it does not define it.

**Per-path classification.** For every untracked path **taken from the
authoritative `PathInventory` (§5.4B), which was already produced and already
scope-checked (§5.3A)**, the generator does an **`lstat` first**, before
anything opens the file. Every verdict below is a **per-path bucket**, never a
run outcome (B-I3):

| lstat result / test | Verdict |
|---|---|
| regular file, readable, size ≤ `[evidence].max_untracked_file_bytes` | candidate |
| symlink | `refused: symlink` — note git would otherwise happily render it as `new file mode 120000` with the link target as content (verified) |
| FIFO / socket / block or char device | `refused: not_a_regular_file` (git's `ls-files --others` does not list FIFOs in the version measured, but the gate is not conditional on that) |
| directory | `refused: directory` |
| realpath escapes the worktree | `refused: path_escapes_worktree` |
| unreadable | `refused: unreadable` |
| size > hard bound | `refused: oversized` with measured size and bound |
| `st_size`/`st_mtime_ns`/`st_ino` differ between the pre-read lstat and a post-read lstat | `refused: changed_during_measurement` |
| contains a NUL byte in the first 8 KiB, or is not valid UTF-8 | **binary** — see below |

**DECISION D-5 (revised — review finding R-13, answering OQ-B1): binary files
are represented honestly, AND "omitted binary" is a different fact from "omitted
supported file".**

Revision 1 chose honest representation over `EvidenceUnsupportedFile`, which the
reviewer endorsed — but it composed D-5 with B-I7 ("Fable refuses when the patch
is incomplete") without noticing the result: **any task that adds an image, a
fixture binary, a `.pdf` or a compiled asset could never be Fable-reviewed**,
with no path forward but deleting the file. A flag that is routinely false is a
flag people learn to ignore, and B-I2 is the design's best idea; it must not be
spent on ordinary tasks.

So the completeness accounting distinguishes two kinds of absence:

| Bucket | Meaning | Blocks Fable? |
|---|---|---|
| `represented` | the patch carries the content | — |
| `content_omitted_untextual` | the file **has no text representation** — binary by the dispatcher's own NUL/UTF-8 classification. Recorded by path, size and sha256. | **no** |
| `content_omitted_capped` | the file *could* have been carried but a configured bound stopped it (oversized) | **yes** |
| `refused` | symlink, FIFO, socket, device, directory, escaping path, unreadable, changed-during-measurement | **yes** |

§27's concern is *"a **supported** changed file being absent"*. A binary file is
not a supported text file; saying so, by name and hash, is honest and is §27's
own escape hatch (*"unless the review mode explicitly supports an
incomplete-evidence refusal"*) used deliberately rather than by accident.

A binary file is recorded as:

```
diff --git a/assets/logo.png b/assets/logo.png
new file mode 100644
Binary files /dev/null and b/assets/logo.png differ
[dispatcher] content omitted: binary file, 20841 bytes, sha256 3f9c…
[dispatcher] reason: untextual — this file has no text representation and was
             never expected to have one. It is NOT a suppressed text file.
```

and the Fable prompt is **told**, by name, size and hash, which files were
omitted as untextual, so the reviewer knows exactly what it is not seeing and
can say so in its verdict. `patch_file_complete` is `False`;
`review_input_complete` (§5.4C) is `True` when the only absences are untextual.
The strict alternative — `EvidenceUnsupportedFile` failing the run — is rejected
for the reason R-4 gives: it also collides with the scope ordering.

**Synthetic new-file patches.** For each supported untracked text file, run from
`cwd = worktree` with a repository-relative path:

```
git … diff --no-index -- /dev/null <relative-path>      # exit 1 == differences found
```

Verified output shape (Appendix A): `diff --git a/X b/X`, `new file mode
100644`, `index 0000000..<blob>`, `--- /dev/null`, `+++ b/X`, `@@ -0,0 +1,N @@`,
`+`-prefixed content. The four §9 edge cases were all verified against git
2.43.0 and are produced correctly by git itself, which is the argument for
using git rather than hand-rolling a unified diff:

- **empty file** → header only, no `---`/`+++`/`@@`. This is git's own canonical
  representation of an empty new file and is emitted verbatim.
- **no final newline** → `\ No newline at end of file` present.
- **filename with a space** → `+++ b/with space.txt` followed by a **trailing
  tab** git emits for disambiguation. It is preserved byte-for-byte; nothing
  post-processes patch lines.
- **non-ASCII / unusual bytes** → with `core.quotePath=false`, `b/café.txt`
  unquoted; without it, `"b/caf\303\251.txt"`. The generator always sets it.

`--no-index` reads two paths from the filesystem. It does not read, write or
lock the index, which is what makes B-I5 satisfiable without `git add -N`.

**Assembly.** The canonical patch is the tracked patch (`git … diff <base>`)
followed by the synthetic sections, ordered by path in a stable, documented
collation (byte-wise ascending on the raw path). It is streamed to
`evidence/diff.patch` through the existing atomic temp-file-then-rename dance,
and the generator returns:

```python
@dataclass(frozen=True)
class PathEntry:
    """One changed path. Applies to tracked and untracked alike — a tracked
    binary file buckets exactly like an untracked one (see §5.4A item 3)."""
    path: bytes               # REAL BYTES, repo-relative. Never a display form.
    tracked: bool
    status: Literal["represented", "content_omitted_untextual",
                    "content_omitted_capped", "refused"]
    reason: str | None
    size_bytes: int
    sha256: str | None
    patch_bytes: int

@dataclass(frozen=True)
class CanonicalEvidence:
    base_commit: str
    inventory: PathInventory            # §5.4B — authoritative, produced FIRST
    entries: tuple[PathEntry, ...]      # one per inventoried path
    patch_path: Path                    # evidence/diff.patch
    patch_bytes: int                    # size of the file on disk
    # --- the two completeness flags (B-I7 / amendment 11). Produced here. ---
    patch_file_complete: bool           # the FILE carries every supported path
    review_input_complete: bool         # what the REVIEWER receives is complete
                                        #   (set by §5.4C, which knows the
                                        #    prompt budget; the generator
                                        #    reports the inputs it needs)
    omitted_untextual: tuple[bytes, ...]
    omitted_capped: tuple[bytes, ...]
    refused_paths: tuple[bytes, ...]
    diff_stat: str                      # tracked stat + dispatcher-composed
                                        # untracked rows (git's own
                                        # "/dev/null => X" label is NOT pasted)
    insertions: int
    deletions: int
    files_changed: int
    check_passed: bool                  # dispatcher-computed, §5.4A item 4
    check_findings: tuple[CheckFinding, ...]
    porcelain_status: str
```

Note `path: bytes`, not `str`. That is B-I6 made structural: the inventory
carries the filesystem's bytes, and any conversion to `str` for display happens
at a rendering boundary that cannot feed scope matching (§5.4B).

**The check (§11).** A dispatcher-side scanner runs over the canonical patch's
added lines (`+` prefixed, excluding the `+++` header) and reports trailing
whitespace, space-before-tab, and leftover conflict markers
(`<<<<<<< `, `======= `, `>>>>>>> ` at line start). `git diff --check` is still
run and its findings are unioned in, but it is **corroborating, not
authoritative** — because of Finding V-1 it can be silenced by an in-tree
attribute (measured: `--text --check` does **not** restore it), and because of
G7-2 it never saw the untracked half. The final verdict is
`check_passed = not check_findings`.

**One accounting.** `diff_patch_bytes`, `diff_total_bytes`, `diff_stat`,
`diff_check_passed` and the Fable prompt patch are all read off the single
`CanonicalEvidence` object. `DispatcherObservations.diff_bytes` keeps its
existing meaning (what was held in memory) but is now derived from the same
object. §10's rule — "do not calculate 'complete' using one source and review
another" — becomes structurally true rather than a convention.

**Fable (§27).** See §5.4C — the gate is now two flags, not one, and a clipped
prompt is a refusal.

### 5.4A V-1 — evidence AUTHORITY (amendment 2 / R-1), against Lane X's measured set

> **Designed against `GATE7-V1-ADJACENT-PROBE.md` (Lane X), which was published
> while this revision was being written.** Every mechanism named below is
> **OBSERVED** in that probe, live, in throwaway repositories reproducing the
> dispatcher's exact evidence surface — and the severe ones were additionally run
> through the **real dispatcher Python** (`sol_claude_dispatcher.git`). Nothing
> here is guessed, and the "not exploitable" list is equally measured.
>
> **Lane X's probe changed this section substantially.** Revision 2's pre-probe
> draft named `.gitattributes`, `$GIT_COMMON_DIR/info/attributes`,
> `core.fsmonitor` and `core.hooksPath`. That was roughly a third of the real
> surface, and it missed the two worst mechanisms entirely — see §5.4A(a2).

#### (a) The frame: this is an authority boundary, not a diff-flag question

Revision 1 called V-1 "the evidence pipeline honours in-tree `.gitattributes`"
and answered it with four flags on `git diff`. The reviewer measured three facts
that break that framing, and they are accepted in full:

1. **The damage is worse than documented.** With a `textconv` driver installed,
   a *modified tracked file does not appear in the patch at all* — both sides
   textconv to the same string, so git emits no hunk and no file header — while
   `git diff --stat` still lists it. The exploit is therefore not "the patch
   shows fabricated content"; it is **"a worker can delete its own tracked edit
   from the evidence Fable reviews, while the stat still counts it."**
2. **The delivery vector revision 1 named is the least dangerous of three.**

   | Vector | Alters evidence? | Visible in `changed_paths` / porcelain? | Beaten by `core.attributesFile=/dev/null`? |
   |---|---|---|---|
   | in-tree `.gitattributes` | yes | **yes** | no |
   | `$GIT_COMMON_DIR/info/attributes` | yes — **and poisons the primary repository's diffs, permanently** | **no. Invisible to every evidence channel.** | no |
   | `core.attributesFile` outside the tree | yes | no | yes |

   A dispatcher-created worktree **shares `$GIT_COMMON_DIR` with the primary
   repository**. `compare_primary_tree` cannot see this, because that invariant
   is `porcelain_status + HEAD` (`server.py:319-364`) and `.git/**` appears in
   neither. **This is the pre-existing primary-tree blindness recorded in §3.4.**
3. **The root cause is write authority, not diff configuration.**
   `CORE_DENIED_GIT_OPERATIONS` (`runner.py:161-178`) covers
   push/merge/rebase/commit/reset/clean/worktree/bisect. **`git config` is not on
   it, and there is no path allowlist on `Write`/`Edit` anywhere.** From a linked
   worktree, `git config` writes the **shared** `.git/config`. That reaches past
   diff: `core.fsmonitor` names **a program git executes during index refresh** —
   i.e. during `git status`, `git diff`, `git ls-files`, which are commands *the
   dispatcher* runs, after the worker exited, with the dispatcher's privileges,
   against the primary repository. `core.hooksPath` is the same shape.

**The invariant (B-I4, restated):** worker-controlled repository configuration,
attributes, and index/presentation state **cannot alter what dispatcher evidence
says, and cannot cause dispatcher evidence collection to execute a
worker-selected program.**

#### (a2) Two mechanisms Lane X found that are WORSE than V-1, and were not in the brief

These are new defect classes. Neither was in `GATE7-BRIEF.md` §1, neither was in
revision 1, and both are live at the baseline commit. They are severe enough
that Wave 0's scope is set by them rather than by V-1.

**V-4 — index bits erase a change from EVERY surface, including
`changed_paths`.** `git update-index` is **not denied** — not
`--assume-unchanged`, not `--skip-worktree`, not `--index-info`; no deny prefix
reaches it. Measured through the real dispatcher code (probe F3/F4/F6):

| | `changed_paths` | `status` | `--stat` | patch bytes | `--check` | scope verdict |
|---|---|---|---|---|---|---|
| `update-index --assume-unchanged <f>` | **gone** | empty | empty | **0** | exit 0 | **`valid=True`** |
| `update-index --skip-worktree <f>` | **gone** | empty | empty | **0** | exit 0 | **`valid=True`** |
| assume-unchanged then `rm <f>` | **gone** | empty | empty | **0** | exit 0 | a tracked **deletion** vanishes entirely |

This is strictly worse than the `.gitattributes` vector this gate was convened
over: `-diff` at least leaves ` M <file>` in `changed_paths`; the index bits
erase the file from every surface at once. **And it reaches the primary tree** —
a worker running `git -C <primary> update-index --assume-unchanged` blinds
`primary_tree_status()` and `compare_primary_tree` for that dispatch while the
backdoor sits on disk (F6). `git -C` is not denied either.

**V-5 — a self-hiding `.gitignore` makes a created file invisible, using the
`Write` tool alone.** `_fold_untracked` uses `--exclude-standard`, which honours
every ignore source. A worker writes `.gitignore` containing the new file's name
**and `.gitignore` itself**, and the result is `changed_paths=[]`,
`status` empty, `scope.valid=True` (probe A1b/F1). **No git subcommand is
involved**, so no command-level deny can ever catch it. `$GIT_COMMON_DIR/info/
exclude` does the same and additionally blinds the primary tree (A2/F2);
`core.excludesFile` does it via the shared config (A3).

Both are direct G7-2 bypasses that are simpler than the one G7-2 describes, and
both defeat scope enforcement, not merely evidence completeness.

#### (b) Layer 1 — a GLOBAL, ARGV-EXPRESSED git invocation policy

Lane X's decisive general lesson, measured (D11): **the dispatcher's own
command-line `-c KEY=VALUE` and explicit flags override worker repo-config.**
Anything the dispatcher *inherits* from the repository is worker-controlled;
anything it states on its own argv is not.

**DECISION D-16 (revised against Lane X).** The hardening is **not** a diff-only
prefix. `git._run_git` — the single chokepoint every git call in `src/**`
already passes through (`git.py:139`) — applies it to **every** invocation:
`status`, `rev-parse`, `ls-files`, `worktree list`, `worktree add`, `cat-file`,
`diff`, all of them.

```
env:   GIT_CONFIG_NOSYSTEM=1          # ignore /etc/gitconfig
       GIT_CONFIG_GLOBAL=/dev/null    # ignore ~/.gitconfig
       GIT_TERMINAL_PROMPT=0          # existing
       GIT_OPTIONAL_LOCKS=0           # existing — MEASURED to matter: it is what
                                      #   stops .git/hooks/post-index-change
                                      #   firing on status/diff (Lane X C7c)
       + the existing _GIT_ENV_REDIRECTS stripping (GIT_DIR, GIT_WORK_TREE, …)
       + GIT_CONFIG_COUNT / GIT_CONFIG_KEY_* / GIT_CONFIG_VALUE_* stripped
         (Lane X C23: they fire; a worker cannot set the dispatcher's env today,
          so this is defence in depth, not a live hole)

argv:  git -c core.fsmonitor=false          # Lane X E1
           -c core.hooksPath=<empty dir>    # Lane X C7d/C21
           -c core.attributesFile=/dev/null # partial — see the caveat below
           -c core.excludesFile=/dev/null   # partial — see layer 4
           --no-pager
           <subcommand> …

diff-producing subcommands additionally:
           --no-ext-diff --no-textconv --no-color   # Lane X E2
           --attr-source=<envelope.base_commit>     # Lane X E4
```

Three measured caveats that the design must state rather than assume away:

1. **`core.attributesFile=/dev/null` and `GIT_ATTR_NOSYSTEM` do NOT disable
   in-tree `.gitattributes`** (Lane X E3/E4). The lever that does is
   **`--attr-source=<base_commit>`**, which reads attributes from the frozen
   base rather than the worktree — a good fit here, since the base commit is
   exactly what the envelope already pins and what B2 already enforces.
2. **`--attr-source` does NOT neutralise `$GIT_COMMON_DIR/info/attributes`**
   (Lane X E4, last block): `info/attributes` is consulted regardless. That
   vector is closed by layer 2's detection, not by an argv flag.
3. **There is NO general flag for `filter.*.clean` / `.smudge` / `.process`**
   (Lane X E3/C5). A clean filter fires on `git diff` and `git status` **even
   under `--no-textconv --no-ext-diff`**, and a smudge filter fires during the
   `git worktree add` checkout of the *next* task. The only argv lever is
   `-c filter.<name>.clean=` **per named driver**, which is enumerative and
   therefore not a defence. This is closed by layer 3 (the clean index and the
   base attribute source together mean no filter is selected) plus layer 2's
   detection.

**The dispatcher's git command repertoire is a load-bearing invariant.** Lane X
measured that `core.editor`, `credential.helper`, `core.gitProxy`,
`core.sshCommand`, `uploadpack.packObjectsHook`, `core.alternateRefsCommand`,
`gpg.program`, `merge.*.driver`, `trailer.*.command`, `pre-auto-gc` and aliases
over builtins are **NOT** exploitable — *only because* the repertoire is exactly
`{status, diff, diff --stat, diff --check, ls-files, rev-parse, worktree add,
worktree list, cat-file}`. Adding a `git log --show-signature` re-arms
`gpg.program`; adding a paged call re-arms `core.pager`. A test therefore pins
the repertoire: an AST scan of `src/**` asserting the set of git subcommands
passed to `_run_git` is exactly the approved list, so widening it is a visible,
reviewed act.

A second AST test asserts **no module in `src/**` constructs a git argv except
through `_run_git`**, so the policy cannot be bypassed by a new call site.
Both tests *can* fail, unlike the one revision 1 proposed (R-3).

#### (c) Layer 2 — detection, because prevention is measurably insufficient

Lane X settles the question revision 2's draft left open: **denying
`Bash(git config:*)` would not close the config path at all**, because `Write`
has no path allowlist and reaches `.git/config`, `.git/info/attributes`,
`.git/info/exclude`, `.git/hooks/*` and `.git/worktrees/*/config.worktree` as
plain files, with no git command involved (E7). And a `.git/config` *grep* is
not a defence either, because `include.path` indirection and worktree-scoped
`config.worktree` both hide the key from it (C16, C22, E8).

So the deny-list change is worth making but is **not** the mechanism:

1. **`Bash(git config:*)` and `Bash(git update-index:*)` join
   `CORE_DENIED_GIT_OPERATIONS`**, and `Bash(git -C:*)` is denied as well —
   Lane X measured that `git -C <primary>` lets a worker address the primary
   tree directly and is outside every current prefix. Honestly labelled as what
   it is: a prefix match on Bash command text by the CLI's own permission
   engine, so it raises the cost and closes the naive path. It is not an OS
   boundary and `Write` walks around all of it.
2. **The real mechanism is a git-administrative fingerprint**, taken before and
   after every run exactly as the porcelain snapshot is, and compared with the
   same `post_state == pre_state` rule. `PrimaryTreeSnapshot` gains:

   ```
   sha256 of:  .git/config
               .git/info/attributes
               .git/info/exclude
               $GIT_COMMON_DIR/config           (may differ from the above)
               $GIT_COMMON_DIR/info/attributes
               $GIT_COMMON_DIR/info/exclude
               sorted listing + sha256 of .git/hooks/**
               .git/worktrees/*/config.worktree
               `git ls-files -v` output          (index bits — see layer 4)
   ```

   Any change is `primary_tree_interference`, i.e. `POLICY_VIOLATION`, with a
   marker naming which administrative file moved. **This closes the §3.4
   blindness** — `compare_primary_tree` currently sees `porcelain_status + HEAD`
   and `.git/**` appears in neither — rather than documenting it as a known gap.
3. **In-tree `.gitattributes` and `.gitignore` are in the `PathInventory`**, so
   a write to either is caught by an unconditional inventory check and marked as
   an evidence-authority tamper attempt, separately from ordinary scope.

#### (d) Layer 3 — the dispatcher decides binariness, for tracked files too (answers R-1 item 3)

Revision 1 applied `--text` to the tracked diff while defining binariness
classification only over `ls-files --others`. The reviewer correctly identified
the unresolved conflict: a **modified tracked binary file** under `--text` puts
raw bytes into `evidence/diff.patch`, corrupting the patch, the byte accounting,
and the dispatcher-side whitespace scanner (which would report "trailing
whitespace" in binary noise).

**DECISION D-17: classify first, then diff only the textual set.**

```
1. inventory the tracked changed paths            (§5.4B, -z, clean index)
2. for each, classify binariness FROM BYTES:
      worktree side: read the file
      base side:     git cat-file blob <base>:<path>
      binary  <=>  NUL byte in the first 8 KiB of EITHER side,
                   or either side is not valid UTF-8
   -> never from a git attribute, never from git's own "Binary files … differ"
3. textual set  -> ONE `git diff --text <base> -- <paths…>` (batched, below)
   binary set   -> dispatcher-composed honest sections:
                     diff --git a/X b/X
                     index <base-sha>..<work-sha> <mode>
                     Binary files a/X and b/X differ
                     [dispatcher] content omitted: binary, <n> bytes,
                                  sha256 base <…> work <…>
                   bucketed content_omitted_untextual (D-5)
```

**Measured constraint on step 3:** `git diff` on 2.43.0 does **not** support
`--pathspec-from-file` / `--pathspec-file-nul` (verified: it prints usage and
the option is unrecognised — those flags exist on `add`/`commit`/`checkout`, not
`diff`). Pathspecs must therefore be passed in argv after `--`, which meets the
same 131,071-byte-per-element and total-argv limits B1 already documents. The
generator batches pathspecs at a documented argv budget, orders batches by path,
and concatenates the fragments in batch order — deterministic, and the
concatenation is the canonical patch.

#### (d2) Layer 4 — a CLEAN INDEX and a POSITIVE AUDIT (closes V-4 and V-5)

This layer is new in revision 2 and exists entirely because of Lane X. It is the
highest-value part of Wave 0.

**Neutralise: collect evidence against a fresh temporary index.** Measured lever
(Lane X E5):

```
tmp = <run_dir>/index.tmp            # never the worktree's .git/index
GIT_INDEX_FILE=$tmp  git read-tree <envelope.base_commit>
GIT_INDEX_FILE=$tmp  git diff <base_commit> …
GIT_INDEX_FILE=$tmp  git ls-files --others …
```

`read-tree` populates a throwaway index from the frozen base, so **no worker-set
`assume-unchanged` or `skip-worktree` bit is honoured** and the diff re-reads the
worktree from disk. This satisfies B-I5 exactly: the *task worktree's* index is
never written — the temporary index is a dispatcher-owned file inside the run
directory, and `git add -N` is still not used anywhere. (Lane X also measured
that `update-index --really-refresh` does **not** clear the bit, so the clean
index is not merely convenient; it is the only lever that works.)

**Detect, do not merely bypass.** Bypassing silently would mean the dispatcher
sees the change and never tells anyone the worker tried to hide it. Two positive
audits run every time and their findings are policy violations:

| Audit | Detects | Lane X |
|---|---|---|
| `git ls-files -v` — flag any lowercase letter (assume-unchanged) or `S` (skip-worktree) | V-4 index-bit tampering | E5 |
| `ls-files --others` **without** `--exclude-standard`, differenced against the `--exclude-standard` list | V-5: every file an ignore source is hiding | E6 |

The second audit's delta is not merely reported — **the suppressed files are
folded into the `PathInventory`**, so a self-hiding `.gitignore` no longer makes
a created file invisible; the file appears in `changed_paths`, is scope-checked
normally, and the `.gitignore` write itself is flagged. `core.excludesFile=/dev/null`
is *not* sufficient on its own (Lane X E6 measured that it does not re-expose an
in-tree `.gitignore`), which is why the delta method is the mechanism and the
`-c` is only defence in depth.

**Consequence for `changed_paths` semantics.** The inventory becomes "every path
git can see has changed, **plus** every path an ignore source is suppressing".
Legitimately-ignored build output (`node_modules/`, `__pycache__/`, `.venv/`)
would therefore enter the inventory and could trip scope. That is a real
ergonomic cost and the design takes it deliberately: the alternative is trusting
a file the worker can write. It is mitigated by recording the ignore *source*
per suppressed path, so `changed-paths.json` distinguishes "ignored by a
pre-existing committed `.gitignore` unchanged since the base commit" from
"ignored by a rule that appeared during this run" — and **only the second is a
tamper marker**. The first is reported and scope-checked but carries no
violation marker. **OQ-B6 (new, for the second reviewer):** is scope-checking
pre-existing ignored paths too aggressive? The conservative alternative is to
scope-check only the second class, at the cost of a worker who writes into a
directory that was already ignored before the task began.

#### (e) What this does NOT close, stated plainly

- **A worker that writes `.gitattributes`, `.gitignore`, `.git/config` or a
  `.git/hooks/*` file still *ran*.** Layers 2 and 4 detect it and land
  `POLICY_VIOLATION`; they do not prevent it, because the worker is an
  unsandboxed same-user process and `docs/SECURITY.md` is already honest that no
  OS boundary exists. **The change is that the dispatcher's own measurements are
  no longer worker-influenced, and the attempt is now visible.**
- **`$GIT_COMMON_DIR/info/attributes` is neutralised by nothing on the argv.**
  `--attr-source` does not reach it (Lane X E4). Detection (layer 2) is the only
  answer, and the design says so rather than implying a flag covers it.
- **`filter.*` has no general disable.** Layer 3's clean index plus the base
  attribute source means no filter is *selected* for the diff path; a filter
  configured to fire on `git status` is caught by layer 2's fingerprint, not
  prevented. Stated, not papered over.
- **The deny-list additions are prefix matches on Bash text**, and `Write`
  reaches every one of those paths without a Bash command. They are a cost
  increase, not a boundary.
- **`docs/SECURITY.md` must be amended in the same wave.** It is honest that the
  worker is unsandboxed, but it does not say "the dispatcher's own measurement
  commands are worker-influenced". After Wave 0 that sentence becomes false —
  which is the point — but the document must be updated with the fix, not later.

#### (f) The measured set — Lane X's answers to §5.4A's open questions

| # | Question | Lane X's measured answer | Where answered in this design |
|---|---|---|---|
| X-1 | Which config keys make the dispatcher execute a worker-chosen program? | **13 mechanisms OBSERVED**: `core.fsmonitor` (fires 6× per evidence run, and on the primary tree), `diff.*.textconv`, `diff.*.command`, `diff.external`, `filter.*.clean`/`.smudge`/`.process`, `core.attributesFile`+textconv, `include.path` indirection, `core.hooksPath`, `.git/hooks/post-checkout`, `.git/hooks/reference-transaction`, worktree-scoped `config.worktree`. **11 further keys measured NOT exploitable**, contingent on the command repertoire. | (b), plus the repertoire-pinning test |
| X-2 | Can `.gitignore` / `info/exclude` hide a new file? | **YES — and the self-hiding `.gitignore` needs only the `Write` tool, no git command.** `changed_paths=[]`, `scope.valid=True` through real dispatcher code (F1). `info/exclude` also blinds the primary tree (F2). | V-5, (d2) layer 4 |
| X-3 | Do `assume-unchanged` / `skip-worktree` suppress a tracked modification? | **YES, and worse than X-2**: the file is erased from *every* surface including `changed_paths`; a tracked *deletion* vanishes entirely; and `git -C <primary>` reaches the primary tree (F3, F4, F6). `git update-index` is not denied. | V-4, (d2) layer 4 |
| X-4 | Any other suppression mechanism? | `status.showUntrackedFiles=no` blinds `status` but not `ls-files --others` — so the fold still catches it, but any surface trusting `status` alone is blind (A4). | (d2); the inventory is authoritative, `status` is human-only |
| X-5 | Does `$GIT_COMMON_DIR/info/attributes` reach the primary repository, and does a fingerprint detect it? | **YES to the reach** (B8) — and `--attr-source` does not neutralise it. The fingerprint file list in (c)(2) is set from Lane X's enumeration. | (c)(2), (e) |

**Two of Lane X's findings changed the design's shape, not just its contents**,
and they are the reason Wave 0 is now the largest of the early waves: V-4 and
V-5 are *scope-enforcement* bypasses reachable without any denied command, and
neither was in the brief's list of eight defects.

### 5.4B V-2 — authoritative path identity (amendment 3 / R-2)

#### The defect, corrected

Revision 1 described this as an untracked-only reporting problem and cited a
newline hazard. Both were wrong, and the reviewer's corrections are adopted:

- **It is a live scope-enforcement bypass, not a reporting defect.** Running the
  real `check_scope` against the real quoted path:

  ```
  path: '"secrets/caf\303\251.txt"'
  forbidden_paths=['secrets/**'], allowed_paths=[]   ->  valid=True   <-- BYPASS
  control 'secrets/cafe.txt'                          ->  valid=False, forbidden=[…]
  ```

  `ScopeSpec.allowed_paths` defaults to empty = unrestricted
  (`models.py:422-431`), so **for any task that expresses its boundary as
  `forbidden_paths` only** — which is exactly how one says "do not touch
  `secrets/`, `infra/`, `.github/`" — a worker writing a non-ASCII filename
  inside a forbidden path is reported `valid=True`.
- **It is not untracked-only.** `git diff --name-only` C-quotes identically
  (verified: `"caf\303\251-mod.txt"`), so **tracked** paths at `git.py:683-692`
  are affected the same way. Revision 1's B-I6 named only `ls-files -z`; that is
  half the fix.
- **The newline claim is deleted.** C-quoting *escapes* a newline to a literal
  `\n`, so `we\nird.txt` stays one line. The splitting hazard exists only if
  `core.quotePath=false` is applied **without** `-z` — i.e. it is a hazard the
  fix would create, not one that exists. The correct motivation for `-z` is
  therefore: **`-z` is required *because* `quotePath=false` is being added.**
  Revision 1's mutant aimed at the non-existent failure mode is retired (§11).

#### The design

**DECISION D-18 (revised against Lane X): one `PathInventory`, produced from
NUL-delimited byte-oriented output, and it is the SOLE authoritative path list.**

Lane X's verdict on amendment 3 is that `-z` is *the right primitive* but
`"just add -z"` is **not sufficient** — it introduces two parsing hazards and
covers only three of the surfaces. Both are specified here.

```python
@dataclass(frozen=True)
class PathInventory:
    """The authoritative changed-path set. REAL BYTES. Produced once, per run.

    This object — not a diff, not a patch, not a status string, not a --stat —
    is what scope enforcement is decided on (§5.3A step 2), and NOTHING else
    may re-derive a path.
    """
    base_commit: str
    tracked: tuple[bytes, ...]        # git diff --name-only -z <base>   [clean index]
    untracked: tuple[bytes, ...]      # git ls-files -z --others          [clean index]
    suppressed: tuple[SuppressedPath, ...]   # §5.4A(d2) ignore-delta audit
    index_tamper: tuple[bytes, ...]          # §5.4A(d2) ls-files -v audit
    unrepresentable: tuple[bytes, ...]       # fail-closed, see rule 5
```

`-z` support measured on git 2.43.0 (Lane X D4/D5/D6/D8/D9, corroborated by this
lane's own probe):

| Command | `-z` accepted | Raw bytes for `café.txt`, spaces, newlines? |
|---|---|---|
| `ls-files --others --exclude-standard -z` | yes | **yes** — NUL-separated, newline-safe |
| `diff --name-only -z <base>` | yes | **yes** |
| `status --porcelain -z` | yes | yes, **but see hazard 1** |
| `diff --numstat -z`, `diff --raw -z` | yes | yes, **but see hazard 1** |
| `diff --stat -z` | accepted and **IGNORED** — still C-quotes, still splits on newlines inside its own text |
| `diff --check -z` | accepted, **no effect** |

Byte-level proof (Lane X, `od -c`): the café name appears as
`c a f 303 251 . t x t \0`; a name containing a newline appears as
`n e w \n l i n e . t x t \0` — the embedded `\n` is **data inside the record**
and the `\0` is the only separator. Through the real dispatcher code with `-z`
decoding, `check_scope` correctly returns `valid=False` with
`forbidden=[café.txt, naïve.key, plain.txt]` (Lane X F2_v2).

##### Hazard 1 — renames emit TWO NUL fields, the second with no status prefix

Measured (Lane X D7, verbatim): a rename in `status --porcelain -z` produces
`b'RM secrets/renamed target.txt'` followed by a **separate NUL-terminated
field** `b'secrets/with space.txt'` carrying the **old** path and **no status
column**. `diff --raw -z` and `diff --name-status -z` have the same
two-paths-per-record shape. A naive "split on NUL, take `line[3:]`" yields the
old path with a bogus or missing status.

**Resolution: `diff --name-only -z` and `ls-files --others -z` are the
authoritative sources**, because neither has a status column and each lists a
path exactly once. `status --porcelain -z` is parsed **rename-aware** — a record
whose status begins `R` or `C` consumes the following field as the old path —
and its output is used for *human-readable evidence only*, never for scope.
Both the old and new paths of a rename are inventoried, because a rename out of
a forbidden directory and a rename into one are both scope-relevant.

##### Hazard 2 — `--stat`, `--check` and patch headers have no `-z` at all

Measured (Lane X D9): a patch header for a newline-containing filename is
`diff --git "a/secrets/new\nline.txt" ...` — C-quoted, with the escape inside
the header text. `--stat` likewise ignores `-z` entirely.

**Resolution, and it is a rule rather than a parser:** **nothing may re-derive a
path from `--stat`, from `--check` output, or from the patch body.** The
canonical patch is *generated from* the inventory (§5.4A(d)), never parsed back
into one. A test asserts this structurally: the only functions that produce a
path into `changed_paths` are the two `-z` readers, verified by AST, and
`CheckFinding` carries the path it was *given*, not one it scraped.

##### Rules

1. **Byte-oriented end to end.** Paths are `bytes` from git's stdout to
   `check_scope`. There is no `str` conversion on the enforcement path.
   `check_scope` and `_translate_glob` operate on `bytes`, and `ScopeSpec`
   patterns are encoded once (UTF-8) at envelope validation.
2. **`-z` is the mechanism; `core.quotePath` is NOT the fix.** Lane X measured
   (D10) that `-c core.quotePath=false` emits raw bytes but **keeps newline
   separation**, so a filename containing `\n` still splits into two rows — it
   is strictly weaker than `-z`. Revision 2's earlier draft had this backwards.
   `-c core.quotePath=false` is still set on every invocation, for the different
   reason Lane X gives (D11): a worker can flip `core.quotePath` in the shared
   config, and the dispatcher's own `-c` overrides repo config. So `-z` makes
   parsing unambiguous and `-c` makes the setting worker-proof; **neither
   substitutes for the other**, and a mutant covers dropping each.
3. **Git's C-quoted display representation never reaches scope matching.** A
   test asserts no quoted form (bytes beginning `"` and containing `\`) is ever
   passed to `check_scope`.
4. **Nothing re-derives paths from patch text** (hazard 2).
5. **Fail-closed for unrepresentable names.** A path whose bytes the
   dispatcher's path model cannot represent — not valid UTF-8, or containing a
   byte the evidence-file encoding cannot round-trip — goes into
   `unrepresentable`. That is **not** a bucket to be diffed around: the run
   lands `FAILED` with `PathInventoryUnrepresentable`, naming the paths by
   `repr` and byte length. **Fail-closed is correct here and B-I3 does not
   apply**, because B-I3 is about *content* and this is about *identity*: a path
   the dispatcher cannot name cannot be scope-checked, and §5.3A's ordering
   depends on the inventory being trustworthy.
6. **The inventory is produced under the clean temporary index** (§5.4A(d2)), so
   `assume-unchanged` / `skip-worktree` cannot remove a path from it, and it
   **includes the ignore-suppression delta**, so a self-hiding `.gitignore`
   cannot either. Without those two, a byte-perfect `-z` inventory would still
   be an inventory of whatever the worker allowed git to see.
7. **`.gitattributes` at any depth, `.gitignore` at any depth, `.git/**` and
   `$GIT_COMMON_DIR/**` are checked against §5.4A(c) on this inventory**, before
   scope, so an evidence-authority attack carries its own marker rather than
   appearing as an ordinary out-of-scope path.

##### Why amendment 4's ordering is expressed against this object

§5.3A says scope is decided on the inventory and outranks any content refusal.
That is only meaningful because the inventory is now **independently
trustworthy**: it is byte-exact (`-z`), index-proof (clean `GIT_INDEX_FILE`),
ignore-proof (the `--exclude-standard` delta), and it is the only thing
permitted to produce a path. An ordering rule that ran scope first against a
*suppressible* path list would be ceremony — the worker would simply remove the
path before the ordering mattered. **Amendment 4 and Lane X's findings are the
same fix seen from two ends**, and neither is complete without the other.

#### Sequencing

**Wave 0, with V-1, V-4 and V-5, before everything else.** These are live
scope-enforcement bypasses at the baseline commit, two of them reachable with no
denied command at all. Revision 1 scheduled V-2 behind Wave B; the reviewer's
position — *"fix first, on its own"* — is accepted, and it answers OQ-V2.
### 5.4C Fable evidence completeness — two flags (amendment 11 / R-8)

#### The defect revision 1 preserved

`_MAX_PROMPT_DIFF_CHARS = 120_000` and `_MAX_PROMPT_PATCH_BYTES = 240_000`
(`server.py:277-286`). Revision 1's B-I7 gated the review on the **file's**
completeness and said nothing about what the reviewer actually *received*; §13's
compatibility table said `evidence/diff.patch` "now contains untracked content …
only Fable's prompt reads it, and it clips as before". So revision 1 knowingly
preserved the clip **while making patches strictly larger**, and therefore
clipping strictly more likely, while claiming §27 compliance.

§27 is explicit: *"Fable must never receive a patch marked complete that omits a
supported changed file."* A 400 KB complete patch clipped to 120,000 characters
is exactly that. It is the G7-2 shape in a new place.

#### The design

**DECISION D-19: two flags, both produced, both gating.**

| Flag | Produced by | True when |
|---|---|---|
| `patch_file_complete` | the evidence generator (§5.4) | `evidence/diff.patch` carries every **supported** changed path's content — i.e. `omitted_capped` and `refused` are both empty. Untextual omissions do not falsify it (D-5). |
| `review_input_complete` | the **review** path, before any reviewer process starts | the reviewer will receive the **entire** authoritative patch — i.e. `patch_file_complete` **and** `patch_bytes ≤ the prompt's patch budget` **and** no section was clipped |

`review_task_with_fable` refuses in PREPARE, before any reviewer process starts,
when either is false:

```
patch_file_complete == false      -> EvidenceIncompleteForReview
                                     details: omitted_capped[], refused[], reasons
review_input_complete == false    -> EvidenceExceedsReviewBudget
                                     details: patch_bytes, budget_bytes, excess
```

Both are **PREPARE-phase refusals** (§3.1): no reviewer tokens are spent, no run
index is consumed, and `state.json` is byte-identical.

**Untextual omissions are carried, not clipped.** When the only absences are
`content_omitted_untextual`, `review_input_complete` is `True` and the prompt
carries an explicit block naming each omitted binary by path, size and sha256,
with the sentence *"these files have no text representation; they were never
part of the reviewable text and their absence is not a gap in the patch."* The
reviewer is told, which is §27's own escape hatch used deliberately.

**Remediation for `EvidenceExceedsReviewBudget`** is honest and actionable:
narrow `allowed_paths` and dispatch the review against a smaller task, or split
the work. The dispatcher does **not** offer to review half — that is precisely
the silent clipping being removed. The full patch remains on disk for Sol.

**Why not raise the budget instead?** Because the budget is not arbitrary: the
prompt travels in the same argv block as everything else, under the same
131,071-byte-per-element and total-argv limits B1 measured. A larger clip
threshold trades a silent-omission bug for an `E2BIG`. **OQ-B5 (new, for the
second reviewer):** should the review prompt deliver the patch by *path* rather
than inline, given Fable has `Read` and the patch is on disk at a path Fable can
open? That would remove the budget question entirely, at the cost of making the
review depend on a file read the dispatcher cannot prove happened. This design
does not adopt it, because "the reviewer was given the evidence" would become
unverifiable — but it is the obvious alternative and deserves an explicit answer.

### 5.5 Design — the run reservation

```python
# state.py (or a new runs.py)

class RunState(str, Enum):
    RESERVED           = "reserved"            # dir exists, nothing launched
    STARTING           = "starting"            # ownership record being written
    RUNNING            = "running"             # process confirmed owned
    FINALIZING         = "finalizing"          # process exited, evidence in flight
    COMPLETE           = "complete"            # dispatcher-result.json written
    ABORTED_PRELAUNCH  = "aborted_prelaunch"   # refused after reserve, before spawn
    FINALIZATION_FAILED = "finalization_failed"
    ORPHANED           = "orphaned"            # owner gone, liveness unresolved (§D)

@dataclass(frozen=True)
class RunReservation:
    task_id: str
    run_index: int
    run_id: str
    kind: RunKind
    role: WorkerRole
    lifecycle_phase: str
    run_dir: Path
    reserved_at: datetime

def reserve_run(store, task_id, *, kind, role, lifecycle_phase) -> RunReservation
def set_run_state(store, reservation, state, *, detail=None) -> None
```

**DECISION D-6: the directory is the allocation token.** `reserve_run` allocates
by `os.mkdir` — which is atomic and fails with `EEXIST` — rather than by a
counter:

```
n = max(persisted runs_allocated, highest existing runs/NNN) + 1
loop:
    try: os.mkdir(runs/NNN, 0o700)          # ATOMIC. No exist_ok.
    except FileExistsError: n += 1; continue
    break
write runs/NNN/reservation.json atomically   (state = RESERVED)
persist TaskRecord.runs_allocated = n        (monotone high-water mark)
return RunReservation
```

Consequences, each of which is a §12/§13 requirement:

- An orphan `runs/NNN` from a crashed previous process **can never be reused**,
  because `mkdir` fails on it. The defect is closed by the filesystem, not by
  bookkeeping.
- Allocation is correct even if `runs_allocated` was never persisted (crash
  between `mkdir` and the record write): the directory scan re-derives the
  floor. `runs_allocated` is an optimisation and a durability marker, not the
  authority.
- Allocation is correct across process restart and across a second dispatcher
  process, without a lock — although in practice the repository lock already
  serialises it. Defence in depth, deliberately.

**`run_count` versus `runs_allocated`.** `TaskRecord.run_count` today means
"highest index that finalised" (`state.py:477`). Gate 7 adds
`runs_allocated: int | None = None` meaning "highest index ever allocated".
`run_count` keeps its meaning and its wire format, so `get_task` consumers do
not break; `runs_allocated` is what the allocator reads. Migration is
deterministic: on first reservation for a task with `runs_allocated is None`,
it is materialised as `max(run_count, highest existing runs/NNN directory)` —
a measurement, not a guess.

**Where the reservation happens.** Immediately after PREPARE succeeds and
immediately before the first state transition that means "a run is starting":

```
dispatch:  PREPARE ok → store.create() → ROUTED → reserve_run() → RUNNING → spawn
resume:    PREPARE ok → reserve_run() → RESUME_REQUESTED → RUNNING → spawn
review:    PREPARE ok → reserve_run() → (no task transition) → spawn
```

The `ABORTED_PRELAUNCH` window is therefore exactly: reservation written →
`RUNNING` transition → `run_worker` spawn. Everything that can refuse has
already refused. What remains in that window is genuine execution failure
(`ClaudeBinaryNotFound`, kernel `E2BIG`, spool open failure), and burning an
index for it is correct — those are runs that were attempted.

### 5.5A The task-state landing is itself a transaction (amendment 7 / R-10)

**The crash point revision 1 missed entirely, and it is reachable on every single
run.** The reviewer traced the post-conditions of a crash *after* `append_run` /
`dispatcher-result.json` but *during* `_land_state`:

- the reservation is `COMPLETE`, so §7.6's reconciliation **skips it** (terminal);
- §7.7 **removes the repository claim** at `COMPLETE`;
- the task is left in `RUNNING`, **permanently**;
- no `recovery` block, because that is `ORPHANED`-only;
- no resume is legal from `RUNNING`.

The task is unrecoverable, invisible, and looks identical to a live run.

**DECISION D-20: the landing is a two-phase commit with a durable intent.**

A new run state `LAND_INCOMPLETE` and a new artefact
`runs/NNN/landing.json`, written **before** the first `transition()` of the
landing sequence:

```python
class LandingIntent(StrictModel):
    """What _land_state has DECIDED, written before it is APPLIED.

    Computed purely from artefacts already durable on disk — dispatcher-result
    .json, the canonical evidence, the validation results — so recomputing it
    after a restart yields the identical answer. That is what makes replay
    deterministic rather than a re-derivation from live state.
    """
    schema_version: Literal["1.0"]
    task_id: str
    run_index: int
    run_id: str
    decided_at: datetime
    target_state: TaskState          # the ladder's verdict (§8)
    reason: str
    transitions: list[str]           # e.g. ["implemented", "awaiting_sol_review"]
    updates: dict[str, Any]          # last_error / policy_violations / resume_count
    applied: bool = False            # flipped true after the LAST transition lands
```

Sequence:

```
FINALIZE  ──► dispatcher-result.json written        (run evidence is complete)
          ──► reservation -> LAND_INCOMPLETE
          ──► landing.json written  (intent, applied=false)
          ──► apply transitions one at a time
          ──► landing.json  applied=true
          ──► reservation -> COMPLETE
          ──► repository claim released
```

**Recovery rule (B-I12).** On startup, reconciliation finds any reservation in
`LAND_INCOMPLETE` and:

1. re-reads `landing.json`;
2. if `applied` is true — finish the bookkeeping (reservation → `COMPLETE`,
   release the claim) and stop;
3. if `applied` is false — **re-apply the recorded transitions, idempotently**:
   for each target in `transitions`, if the task is already in that state, skip
   it; if the transition is legal from the current state, apply it; if it is
   neither, the landing is inconsistent with the task and the run is marked
   `FINALIZATION_FAILED` with the discrepancy recorded, and the task is **left
   alone** rather than forced.

Idempotence comes from the intent being a *recorded decision*, not a
recomputation: replay never re-runs the ladder, never re-reads the worker's
output, and never produces a different verdict than the one the original process
decided from evidence that is already immutable on disk. That is the difference
between "deterministic replay" and "guessing what should have happened".

**The repository claim is held through `LAND_INCOMPLETE`** — it is released only
at `COMPLETE`. So the window R-10 identified no longer both strands the task
*and* frees the repository for a new worker.

Two secondary gaps the reviewer flagged in the same finding, also closed:

- **crash between `evidence/diff.patch` and `changed-paths.json`.** The latter
  carries the completeness flags that B-I7 reads, so a patch without its
  accounting is a run whose evidence cannot be judged. The generator therefore
  writes **`changed-paths.json` last**, and its presence is the marker that
  evidence collection completed; a run directory with `diff.patch` and no
  `changed-paths.json` reconciles to `FINALIZATION_FAILED`, never to "complete
  with an assumed-true flag".
- **crash during a claims-directory write** (§7.7) — the writes that stand
  between a dead dispatcher and a duplicate worker. Claims are written with the
  same atomic temp-then-rename as everything else, and a **partial or
  unparseable claim file is treated as an ACTIVE claim** (fail closed), not
  skipped.

### 5.6 State transitions

No new `TaskState`. Run state is a **new, separate** state machine living in
`runs/NNN/reservation.json` and it deliberately does not interact with the task
state machine except through `_land_state`, whose *decision* is unchanged and
whose *application* is now transactional (§5.5A).

```
RESERVED ──► STARTING ──► RUNNING ──► FINALIZING ──► LAND_INCOMPLETE ──► COMPLETE
    │            │            │            │                │
    │            │            │            │                └──► FINALIZATION_FAILED
    │            │            │            └──► FINALIZATION_FAILED
    │            │            └──► ORPHANED            (subsystem D)
    │            └──► ORPHANED                          (subsystem D)
    └──► ABORTED_PRELAUNCH
```

Justification for each state, against §12's "do not add states for decoration":

- `RESERVED` — the directory exists and nothing else does. Without it, a crashed
  reservation is indistinguishable from a crashed run.
- `STARTING` — the window between `create_subprocess_exec` returning and the
  ownership record being durable. Subsystem D needs it: a crash here means "a
  process may exist that we cannot name", which is a different recovery
  decision from "no process was started".
- `RUNNING` — ownership record durable.
- `FINALIZING` — the process is gone and evidence is being written. Distinguishes
  "died mid-evidence" from "died mid-run"; the first is recoverable by re-running
  evidence collection, the second is not.
- `LAND_INCOMPLETE` — the run's evidence is durable and the task's terminal
  state has been *decided* but not fully *applied*. **Not decoration: it is the
  only state that distinguishes "the task is genuinely running" from "the task
  is stuck in `RUNNING` because a process died between two `transition()`
  calls"** (§5.5A / R-10), and without it that window is silent and permanent.
- `COMPLETE`, `ABORTED_PRELAUNCH`, `FINALIZATION_FAILED`, `ORPHANED` — terminal,
  each named by the brief.

Rejected as decoration: `QUEUED`, `LOCKED`, `VALIDATING`, `REVIEWED`,
`CANCELLED`. The first two are implied by `RESERVED`, the third by
`FINALIZING`, and the last two are task-level facts.

### 5.7 Persistent data

```
state/tasks/<task-id>/
  state.json                      + runs_allocated
                                  + lifecycle_preflight
  refusals.jsonl                  NEW  append-only PREPARE-phase refusal log
                                       (D-13). state.json is NOT touched.
  preflight/lifecycle-feasibility.json          (subsystem A)
  runs/NNN/
    reservation.json              NEW  {schema_version, task_id, run_index, run_id,
                                        kind, role, lifecycle_phase, state,
                                        reserved_at, state_history[], detail}
    expectation.json              NEW  pre-spawn expectation record (M-8, §7.9)
    ownership.json                NEW  (subsystem D)
    landing.json                  NEW  LandingIntent (§5.5A) — written before the
                                       first landing transition, applied=true after
    events.jsonl                  NEW  raw stream-json NDJSON (subsystem C —
                                       now unconditional; Lane U measured support)
    stdout.raw                    (existing; becomes the child's direct stdout — §7.4)
    stderr.log                    (existing; becomes the child's direct stderr — §7.4)
    stdout.json                   (existing retained excerpt)
    worker-result.json            (existing)
    validation.json               (existing)
    claim-verification.json       (existing)
    timeout.json                  NEW  (subsystem C)
    dispatcher-result.json        (existing — evidence-complete marker)
  evidence/
    diff.patch                    (existing — now the CANONICAL patch)
    path-inventory.json           NEW  the authoritative PathInventory (§5.4B),
                                       written BEFORE scope is decided
    changed-paths.json            (existing + entries[], omitted_untextual[],
                                   omitted_capped[], refused[],
                                   patch_file_complete + review_input_complete,
                                   both produced by the generator)
                                   **written LAST — its presence is the marker
                                   that evidence collection completed** (§5.5A)
    diff-check.json               NEW  (dispatcher findings, tracked + untracked)
    git-admin-fingerprint.json    NEW  (§5.4A(c)(2) — .git/config, info/attributes,
                                        info/exclude, hooks listing; before + after)
    …unchanged: diff-stat.txt, status.txt, evidence-phases.json,
      primary-tree-*.{txt,json}, worktree-base.json
```

`reservation.json` is written with the existing `atomic_write_json` (temp file,
fsync, `os.replace`, 0600 inside 0700). Its `state_history` is append-only.

### 5.8 Error taxonomy

**Revision 2: `EvidenceUnsupportedFile` is no longer an exception.** Revision 1
made it a raised error that failed the run, which contradicted B-I3 and gave a
worker a one-command downgrade from `POLICY_VIOLATION` to `FAILED` (R-4). It is
now a **per-path reason string** on a `refused` bucket entry. Nothing about an
individual file's type or size ends a run.

| Code | Class | Phase | Meaning |
|---|---|---|---|
| *(no exception)* `refused: <reason>` | — | FINALIZE | Per-path bucket for symlink / FIFO / socket / device / directory / escaping path / unreadable / changed-during-measurement / oversized. Forces `patch_file_complete = False` (so Fable refuses). **Does not end the run and does not preempt the scope verdict** (§5.3A, B-I3). |
| `PathInventoryUnrepresentable` | `GitEvidenceCollectionFailed` subclass | INVENTORY | A changed path's bytes cannot be represented by the dispatcher's path model, so it cannot be scope-checked. **Fail-closed, run lands `FAILED`** — this is about *identity*, not content, and B-I3 does not apply (§5.4B rule 4). |
| `EvidenceIncompleteForReview` | `DispatcherError` | PREPARE (review) | `patch_file_complete == false`. No reviewer started; `state.json` byte-identical. |
| `EvidenceExceedsReviewBudget` | `DispatcherError` | PREPARE (review) | `review_input_complete == false` — the complete patch is larger than the prompt can carry (§5.4C). No reviewer started. |
| `RunReservationFailed` | `InternalDispatcherError` subclass | RESERVE | `mkdir` failed for a reason other than `EEXIST` (permissions, ENOSPC), or the allocator exceeded a sane bound. |
| `RunFinalizationFailed` | `DispatcherError` | FINALIZE | `dispatcher-result.json` or `changed-paths.json` could not be written. Reservation → `FINALIZATION_FAILED`. Streams and evidence preserved. Index never reused. |
| `GitEvidenceCollectionFailed` | existing | INVENTORY / FINALIZE | unchanged semantics: git could not be run, timed out, or exited outside its expected set |

§28 ordering interaction, **reversed from revision 1**: an evidence *content*
refusal is a per-path bucket and ranks **below** the policy ladder entirely —
scope and primary-tree verdicts are decided on the inventory before content
generation runs. Only an *inventory* failure (`GitEvidenceCollectionFailed`,
`PathInventoryUnrepresentable`) ranks above the policy ladder, because without a
trustworthy inventory there is nothing to decide policy on.

### 5.9 Crash points (§13 requires injection at each)

| # | Crash point | Required post-condition |
|---|---|---|
| 1 | after `mkdir runs/NNN`, before `reservation.json` | index N is never reused (mkdir EEXIST); next run gets N+1; N is reconciled to `ORPHANED` on startup |
| 2 | after `reservation.json`, before spawn | N never reused; reconciles to `ABORTED_PRELAUNCH` |
| 3 | after spawn, before `ownership.json` | N never reused; reconciles to `ORPHANED` (subsystem D: a process may exist that cannot be named) |
| 4 | after worker exit, before stream persistence | N never reused; streams already on disk (§6 file-backed); reconciles to `FINALIZING` → recoverable |
| 5 | after streams, before evidence A | N never reused; `pre-validation-*` absent; reconciles to `FINALIZATION_FAILED` |
| 6 | after evidence A, before validation | as above, evidence A preserved |
| 7 | after validation, before evidence B | `validation.json` preserved |
| 8 | after evidence B, before `diff.patch` write | partial `.tmp` removed, no unmarked short patch |
| 9 | after `diff.patch`, **before `changed-paths.json`** | **NEW (R-10 secondary).** The completeness flags B-I7 reads do not exist. Reconciles to `FINALIZATION_FAILED`; the flags are **never defaulted to true**. |
| 10 | after `changed-paths.json`, before `dispatcher-result.json` | run is `FINALIZATION_FAILED`, `run_count` unmoved, `runs_allocated` == N, **next resume gets N+1** |
| 11 | after `dispatcher-result.json`, before `landing.json` | **NEW (amendment 7 / R-10).** Reservation is `FINALIZING`, not `COMPLETE`; the claim is retained; reconciliation re-decides the landing from the durable evidence and applies it. |
| 12 | **during `_land_state`, between two `transition()` calls** | **NEW — the reachable-on-every-run point revision 1 missed.** Reservation is `LAND_INCOMPLETE`, `landing.json` has `applied=false`; the claim is **retained**; reconciliation replays the recorded transitions idempotently (§5.5A). The task is never left silently stuck in `RUNNING`. |
| 13 | after the last transition, before `landing.json applied=true` | Replay finds every target state already current, skips each, flips `applied`, and reservation → `COMPLETE`. **Idempotence is what makes this safe**, and it is tested by running recovery twice. |
| 14 | during a claims-directory write (§7.7) | **NEW (R-10 secondary).** A partial or unparseable claim file is treated as an **ACTIVE** claim, never skipped. Fail-closed. |
| 15 | after `dispatcher-result.json`, before `run_count` save | `append_run` is already atomic per file; `run_count` recovers as `max(run_count, highest COMPLETE index)` on load |

Injection mechanism: a test-only fault hook keyed by point id, injected through
the store/generator seams (not through monkeypatching `os` globally), so the
same test can assert "process was killed here" with a real `os._exit` in a
subprocess for points 3, 4, 10 and 12 (the ones where a genuine process death
matters) and an exception for the rest. **Point 12 is run twice in the same
test** — kill, recover, kill again during recovery, recover again — because
idempotence that is only exercised once is an assumption.

### 5.10 Tests (§29, §30)

Unit (`tests/unit/test_evidence.py`, `tests/unit/test_run_reservation.py`):

- canonical patch shape for each of: multi-line new file, empty file, no final
  newline, filename with a space, nested path, non-ASCII path, path with a tab;
- `patch_file_complete` false whenever `omitted_capped` or `refused` is non-empty —
  and there is **no setter**, asserted by reflection;
- check scanner: trailing whitespace, space-before-tab, all three conflict
  markers, in tracked and untracked halves;
- allocator: EEXIST loop, `runs_allocated` migration from `run_count`, monotone
  under concurrent callers.

Real disposable integration (`tests/integration/test_evidence_completeness.py`,
`test_run_transaction.py`) — real `git init`, real `git worktree add`, real
files, no mocks of git:

- **§10's headline case**: a **191-line untracked test file** appears in
  `changed_paths`, in `evidence/diff.patch` with all 191 lines, in
  `diff_total_bytes`, in `diff_stat`, and **in the Fable prompt** — asserted by
  capturing the argv the fake reviewer receives, not by asserting on a
  dispatcher-written log;
- symlink / FIFO / oversized / directory-masquerade / escaping-path → typed
  per-path `refused` bucket, **run NOT failed**, scope still decided, `patch_file_complete` false;
- **Finding V-1 regression**: a worktree containing `.gitattributes` with
  `secret.txt diff=lie` plus a local `diff.lie.textconv` — the canonical patch
  must contain the real content; and `x.txt -diff` with trailing whitespace —
  `check_passed` must be `False`;
- **Finding V-2 regression**: `café.txt` and `tab\there.txt` appear in
  `changed_paths` as their real bytes and are matched/refused correctly by
  `check_scope`;
- untracked whitespace error makes `diff_check` fail;
- `patch_file_complete=false` → Fable refuses, zero reviewer processes started;
- a complete patch larger than the prompt budget → `EvidenceExceedsReviewBudget`,
  zero reviewer processes started (§5.4C);
- crash injection at all ten points, each asserting index non-reuse.

### 5.11 Mutation cases

Every mutant below has a **named targeted killer** (amendment 12 / R-14). The
120x2 matrix is coverage, never the sole proof of any of them.

**Wave 0 — evidence authority and path identity**

| Mutant | Named targeted killer |
|---|---|
| drop the clean `GIT_INDEX_FILE`; diff against the worktree index | `test_v4_assume_unchanged_still_inventoried` |
| drop the `ls-files -v` tamper audit | `test_v4_index_bits_reported_as_policy_violation` |
| drop the `--exclude-standard` ignore-delta audit | `test_v5_self_hiding_gitignore_still_inventoried` |
| fold the suppressed set into evidence but not into scope | `test_v5_suppressed_path_still_scope_checked` |
| drop `-c core.fsmonitor=false` | `test_v1_fsmonitor_program_not_executed` (a sentinel-writing script that must not run) |
| drop `--attr-source=<base>` | `test_v1_in_tree_gitattributes_cannot_suppress_content` |
| drop `--no-textconv` | `test_v1_textconv_cannot_fabricate_content` |
| drop `--no-ext-diff` | `test_v1_diff_external_not_executed` |
| drop `--text` on the textual set | `test_v1_minus_diff_attribute_cannot_omit_content` |
| drop the git-administrative fingerprint | `test_v1_common_dir_info_attributes_is_policy_violation` |
| widen the git subcommand repertoire | `test_git_command_repertoire_is_pinned` (AST) |
| construct a git argv outside `_run_git` | `test_all_git_invocations_go_through_run_git` (AST) |
| use `-z` without `-c core.quotePath=false` | `test_v2_quotepath_flip_by_worker_is_overridden` |
| use `core.quotePath=false` without `-z` | `test_v2_newline_filename_is_one_inventory_entry` |
| parse `status --porcelain -z` rename-unaware | `test_v2_rename_two_field_record_parsed` |
| re-derive a path from `--stat` or the patch body | `test_paths_only_from_z_readers` (AST) |
| scope-match the C-quoted display form | `test_v2_forbidden_nonascii_path_is_caught` |

**Wave B — evidence content and the run transaction**

| Mutant | Named targeted killer |
|---|---|
| set `patch_file_complete = True` unconditionally | `test_completeness_flag_has_no_setter` + the omitted/refused tests |
| set `review_input_complete = True` unconditionally | `test_oversized_patch_refuses_review` |
| drop the synthetic untracked sections but keep the inventory | `test_191_line_untracked_file_reaches_fable` |
| skip the untracked half of the check | `test_untracked_whitespace_fails_diff_check` |
| delegate the check verdict to `git diff --check` alone | `test_minus_diff_attribute_cannot_silence_check` |
| **reorder the §8 ladder so an evidence refusal preempts the scope verdict** | `test_out_of_scope_symlink_lands_policy_violation` **(R-14 gap: revision 1 had no mutant for this at all)** |
| make a per-path refusal fatal to the run | same test |
| `git add -N` or any write to the worktree index | `test_worktree_index_untouched_by_evidence` (sha256 + mtime of `.git/index`) |
| replace `reserve_run()` with `run_count + 1` | `test_orphan_run_directory_never_reused` |
| `mkdir(exist_ok=True)` in the allocator | same test |
| increment `runs_allocated` only on successful finalisation | `test_crash_after_patch_write_allocates_next_index` |
| delete the run directory on evidence failure | `test_failed_run_directory_preserved` |
| let Fable review an incomplete patch | `test_incomplete_patch_refuses_review` |
| let Fable review a clipped prompt | `test_oversized_patch_refuses_review` |
| skip `landing.json`; apply transitions directly | `test_crash_during_land_state_recovers` |
| make landing replay non-idempotent | `test_land_recovery_is_idempotent` (recover twice) |
| treat an unparseable claim file as absent | `test_partial_claim_file_is_active_claim` |

### 5.12 Backward compatibility

- `changed-paths.json` gains keys; existing keys keep their meaning. Readers
  that ignore unknown keys are unaffected.
- `evidence/diff.patch` becomes strictly larger (it now contains content it
  should always have contained). Nothing parses it structurally except Fable's
  prompt builder, which clips at `_MAX_PROMPT_DIFF_CHARS` as before.
- `RunRecord` / `dispatcher-result.json` unchanged in shape; `RunMetadata` gains
  optional fields.
- Existing tasks with `runs/NNN` directories and no `reservation.json` are
  handled: the allocator's directory scan sees them, so their indexes are never
  reused, and reconciliation classifies a directory with `dispatcher-result.json`
  as `COMPLETE` and one without as `ORPHANED` (never as reusable).
- `SCHEMA_VERSION` does not bump. `state.json` gains optional fields only.

---

## 6. SUBSYSTEM C — Timeout and progress execution

Covers **G7-3** (timeout evidence and recovery) and **G7-4** (event-driven
progress).

**Revision 2: this subsystem is no longer conditional.**
`GATE7-CAPABILITY-PROBE.md` (Lane U) was published and every question revision 1
left open is now measured. §6.0 records the findings verbatim, as amendment 14
requires; the sections that follow are written against them.

### 6.0 Lane U's capability findings — preserved verbatim (amendment 14)

**Installed clients: Claude Code 2.1.237, Codex CLI 0.149.0.** Amendment 13:
the brief's "0.147.0" is stale; every Codex finding below describes **0.149.0**,
and client behaviour is version-specific enough that the probe must be re-run on
any Codex upgrade. Historical reports keep their historical numbers; this design
does not.

| # | Question (§14/§15/§18) | **Measured verdict** |
|---|---|---|
| U-1 | Claude CLI incremental machine-readable events | **SUPPORTED.** `--print --verbose --output-format stream-json` emits a structured, incrementally-flushed NDJSON event stream with exactly one authoritative `type: "result"` final event. |
| U-1b | Do partial events survive a mid-run kill? | **YES — the decisive G7-3 result.** SIGKILL at 12 s (wait status 137): **34/34 lines valid JSON, no torn final line, 0 `result` events, 10 recovered `tool_use` events matching 10 files actually on disk.** Line-oriented flushing means a killed stream is never syntactically corrupt, and **absence of the final result event is measurable**. |
| U-1c | Cost accounting on kill | **ABSENT.** A killed run emits no `result`, therefore no `usage` and no `total_cost_usd`. Killed runs really do consume tokens; the CLI provides no accounting for them. |
| U-2 | Soft-deadline / finalization mechanism | **NOT AVAILABLE on 2.1.237.** SIGTERM kills in under 1 s, exit 143, stream did not grow by one line, **no `result` event** — a marginally politer kill, nothing more. `--input-format stream-json` delivers a message but **does not interrupt**: a "STOP" injected at t=10 s was honoured only after the entire in-flight turn completed, with **eight more files written after the stop request**. It is a queued message at a turn boundary, and time-to-finalization equals the remaining turn duration — exactly the unbounded quantity a soft deadline must bound. |
| U-2b | B3 hazard in stream-json **input** mode | **`--input-format stream-json` does NOT reliably yield one `result` event** — mid-flight injection coalesced two logical turns into a single envelope. Default `--input-format text` produced exactly one `result` in every run. **Adopting stream-json input would weaken B3.** |
| U-3 | Does Codex send a `progressToken`? | **YES.** `progress_token: 1` captured on the `tools/call` `_meta` of a real `sol_claude_dispatcher` call, protocol `2025-06-18`. |
| U-4 | Does Codex receive `notifications/progress`? | **YES — all 10 crossed the wire** into Codex's stdin during a single 30 s blocking call, one every ~3 s, captured by a raw JSON-RPC wire-tap. |
| U-4b | Does Codex **surface** them? | **NO.** Zero progress events in the `--json` stream (6 events, none progress), zero in human-readable output (`started` / `(completed)` only), zero in the session rollout. |
| U-5 | **Does progress cause model inference turns?** | **ZERO.** Counted from the session rollout, not asserted: exactly one `task_started` / `task_complete` pair. A/B control with identical prompt and duration: 10 ticks → 1 turn, 0 ticks → 1 turn; structurally identical. Every `progress` substring in the rollout is a field *name* echoed inside the tool *result*, never notification content. |
| U-0 | Server-side positive control | **WORKS.** With a `progress_callback`: 6 sent, **6 received**, no errors. Without a token: 6 "sent", **0 received, NO ERROR** — the SDK silently no-ops, which is the §18 requirement satisfied by the SDK itself. |

**§35 classification: G7-4 = CLIENT-LIMITATION.** Server side protocol-correct
and provably emitting; Codex receives and discards; zero model turns; zero
polling; no-token path error-free. This **does not block the correctness gate**.

**What Lane U says the design MUST NOT assume**, carried here as binding:

- **that any soft-deadline or finalization mechanism exists — it does not.** Do
  not ship a finalization window; budget evidence/validation time *after* the
  kill instead.
- that a timed-out run yields any `usage` or cost data.
- that `--input-format stream-json` yields exactly one `result` event. **Stay on
  default `text` input.**
- that `stream-json` works without `--verbose` (it does not, in print mode).
- **that Sol will ever see the progress.** Progress must be strictly
  fire-and-forget: nothing may block on, await, or condition behaviour upon a
  client acknowledging it, and no user-visible promise may be made that Sol sees
  it.
- that the absence of a `progressToken` is an error condition — it is a silent
  no-op.

One operational finding with a one-line fix: without explicit stdin redirection
the CLI **stalls 3 s per run** and warns on stderr. The runner already passes
`stdin=DEVNULL`, which is exactly the recommended `< /dev/null`; a test pins it
so a future edit cannot reintroduce the stall.

### 6.1 Current failure

**The remediation lies by construction.** Two unconditional strings:

```python
# server.py:2054 — in _finalise_worker_run
if worker_run.timed_out:
    worker_result_error = ("worker timed out before emitting structured output; "
                           "partial stdout preserved in the run directory")

# server.py:2588 — in _land_state
remediation=("Partial output, the session and the worktree are preserved. "
             "Resume with a narrower instruction, or accept the partial state.")
```

Neither consults `worker_run.stdout_total_bytes`. A worker that emitted nothing
produces both strings verbatim.

**Trusted validation is skipped on the wrong grounds.** `server.py:2100`:

```python
if not worker_run.timed_out and not worker_run.start_failed:
    validation_results = await run_validations(...)
```

The predicate is the *process outcome*, not the *state of the worktree*. A
worker that made complete, in-scope, correct changes and then hung has its
`pytest` skipped — even though the filesystem changes are preserved, the B2
base invariant has just been re-verified two dozen lines earlier, and the
commands are caller-declared and trusted. Sol is handed "timed out, no
validation" when the dispatcher could have handed over "timed out, and by the
way all 341 tests pass."

**There is no deadline structure.** One number (`spec.timeout_seconds`) drives
`asyncio.wait_for`; then SIGTERM, 5 s grace, SIGKILL, 10 s reap, 10 s pipe
drain. There is no soft deadline, and no separation between "time the model
gets" and "time the dispatcher needs afterwards".

**There is no progress surface at all.** A one-hour blocking call emits nothing
between `worker_start` and `run_complete` except stderr log lines nobody is
subscribed to.

### 6.2 New invariants

- **C-I1 (measured remediation).** Every statement about preserved output is
  derived from a counter. If zero bytes were written, the remediation says
  *"Claude emitted no stdout before timeout."*
- **C-I2 (timeout stays TIMED_OUT).** Post-timeout validation is evidence. It
  never changes the landed state. `_land_state`'s timeout branch is not
  conditioned on validation results, and a test asserts that all-passing
  post-timeout validation still yields `TIMED_OUT`.
- **C-I3 (validation preconditions are about the tree, not the process).**
  Post-timeout validation runs iff the enumerated preconditions hold; when it
  does not run, the reason is typed and recorded.
- **C-I4 (dispatcher evidence, never a worker claim).** Post-timeout results are
  `ValidationResult` with `source="dispatcher"` and a new
  `phase="post_timeout"`. They are never merged into `worker_claims`.
- **C-I5 (zero polling, zero model turns).** Progress is emitted only through
  request-scoped MCP progress notifications. Nothing instructs Sol to call
  `get_task`. No fifth tool. If progress causes model turns on the installed
  client, progress is disabled rather than kept.
- **C-I6 (progress is observational and bounded).** Only phase transitions and a
  sparse heartbeat. Never prompt, skill text, guidance, raw stdout/stderr,
  argv, file contents, or model reasoning.
- **C-I7 (no manufactured progress).** If the installed CLI cannot produce
  useful incremental events, the design says so and reports only what the
  dispatcher itself measures. No synthesised narration.

### 6.3 The four deadlines (§15)

```
t0 ── soft deadline ──── hard deadline ── SIGTERM ── grace ── SIGKILL ── reap
│                        │                                                │
│◄── model working time ─┤                                                │
│                        │◄──────── termination tail (25 s today) ────────┤
└─────────────────────────────────────────────────────────────────────────┴──►
                                                     evidence + validation window
                                                     (already inside the aggregate
                                                      run budget, config.py)
```

- **soft deadline** — `hard_deadline − [execution].finalization_window_seconds`
  (proposed default 120 s, config key, clamped). Its *only* unconditional effect
  is a progress event and a recorded fact. Whether it can additionally *ask* the
  worker to wrap up was an open question in revision 1; Lane U measured that
  **no such mechanism exists** (§6.6), so the soft deadline is a measurement and
  nothing else.
- **hard deadline** — today's `spec.timeout_seconds`. Unchanged semantics.
- **grace** — `DEFAULT_GRACE_SECONDS = 5.0`. Unchanged.
- **evidence/validation window** — already accounted for in the aggregate run
  budget (`UNDECLARED_RUN_OVERHEAD_SECONDS = 1845`,
  `MAX_TOTAL_RUN_BUDGET_CEILING = 8955`). Introducing the soft deadline changes
  no budget arithmetic: it subdivides time the worker already had.

### 6.4 Timeout evidence (§16) — unconditional, no probe needed

**R-11 first: `stdout_bytes` has ONE definition, fixed before either wave.**
The reviewer showed that revision 1 sourced it "from `StreamCapture.total` /
spool stat" while `stderr.log` is today *redacted and re-rendered* on the way to
disk (`runner.py:1258-1298`) — so its size is not the child's byte count — and
that after D-9 both files hold raw child bytes. A Wave C test asserting
"partial-output timeout preserves exact measured partial bytes" would have been
written against one definition and silently reinterpreted under another.

Two corrections, both adopted:

1. **Definition, from Wave C onward and unchanged by Wave D:**
   `stdout_bytes` / `stderr_bytes` are **the number of bytes the child process
   wrote to that stream**. Nothing else. Not the retained excerpt's length, not
   the rendered file's size, not the redacted spool's size.
2. **Ordering: Wave D runs BEFORE Wave C** (amendment 8). Once the streams are
   file-backed, `st_size` *is* the child's byte count, so the definition and its
   source agree by construction and no re-interpretation is possible. Doing C
   first would mean establishing the gate's central "measured, not asserted"
   number on a source whose meaning was about to move.

**B3 tail-read invariant (R-11, related).** After D-9 the retained excerpt is a
**read-time** policy, and the authoritative CLI envelope is at the **end** of
the stream. The design asserts as an invariant, with a named test
(`test_b3_envelope_recovered_from_multi_megabyte_stream`), that **the tail is
always read** — a multi-megabyte stdout with a trailing `result` event must
still classify. §2 lists B3 as a non-regression, and a silent degradation on
large runs would be exactly the kind of regression this gate exists to catch.


New `runs/NNN/timeout.json` and a new `TimeoutEvidence` block on the run record:

```python
class TimeoutEvidence(StrictModel):
    timed_out: bool
    killed_with_sigkill: bool
    soft_deadline_seconds: int | None
    hard_deadline_seconds: int
    elapsed_ms: int
    stdout_bytes: int                    # from StreamCapture.total / spool stat
    stderr_bytes: int
    stdout_partial_available: bool       # stdout_bytes > 0
    stderr_partial_available: bool
    structured_result_available: bool    # a trailing JSON object was recovered
    worker_patch_available: bool         # canonical evidence has >0 changed paths
    last_output_at: datetime | None      # last time the spool grew
    post_timeout_validation: Literal["ran", "skipped", "not_applicable"]
    post_timeout_validation_skip_reason: str | None
```

Remediation text is composed from these facts. The zero case reads, verbatim:

> Claude emitted no stdout before timeout. No structured result was produced.
> stderr: 0 bytes. The worktree contains N changed path(s), preserved at
> `<path>`, and the session id is preserved for resume.

and the non-zero case names the exact byte counts. Nothing says "partial output
preserved" unless `stdout_bytes > 0`.

### 6.5 Streaming events (§14) — MEASURED SUPPORTED, no longer conditional

Lane U proved the capability exists and is sufficient (U-1, U-1b). Revision 1's
fallback is retired; the design adopts the real mechanism.

**Invocation** (the only change to `build_argv`'s shape):

```
claude --print --verbose --output-format stream-json  …  < /dev/null
```

`--verbose` is required in print mode (measured; undocumented in `--help`).
`--input-format` stays at its default **`text`** — the prompt remains the
trailing positional — because `--input-format stream-json` was measured **not**
to yield exactly one `result` event, and adopting it would weaken B3 (U-2b).

**Handling:**

- the raw NDJSON is spooled **unparsed and complete** to `runs/NNN/events.jsonl`,
  which after D-9 (§7.4) is the child's own stdout file — so it is durable by
  construction, survives dispatcher death, and needs no pump;
- the structured result is extracted **only** from the single
  `type: "result"` event. Intermediate `assistant` / `text` / `tool_use` /
  `user` / `rate_limit_event` / `system` events are never treated as the result;
- **B3 is intact and strengthened.** The `result` event carries
  `api_error_status`, `terminal_reason`, `subtype`, `is_error`, `stop_reason`,
  `usage` and `session_id` — every field `runner.envelope_facts` reads. The
  payload veto and the marker-key check are unchanged, and the "exactly one
  authoritative envelope" property is now *measured* rather than assumed;
- **absence of a `result` event is the definitive kill/timeout signal** (U-1b).
  It is measured, not inferred from the exit code, and it is what
  `structured_result_available` (§6.4) reports;
- the parser tolerates a truncated trailing line on principle, even though none
  was ever observed under SIGKILL;
- §16's remediation facts — `stdout_bytes`, `structured_result_available`, tool
  activity, `last_output_at` — are derived from the recovered event stream.

**What G7-3 actually gains, measured:** today a timeout yields an empty
`stdout.raw`. With stream-json a SIGKILLed run yielded 34 valid JSON lines,
zero `result` events, and 10 recovered `tool_use` events that matched 10 files
actually on disk. The dispatcher can state precisely what the worker did before
the kill, instead of saying "partial stdout preserved" about nothing.

**The cost-accounting gap is carried honestly (U-1c).** A killed run emits no
`usage` and no `total_cost_usd`, but really does consume tokens. `TimeoutEvidence`
therefore has **no cost field** for timed-out runs, and the remediation says
*"the provider consumed tokens for this run; the CLI emits no accounting for a
killed run, so the dispatcher cannot state the cost."* Inventing a zero or
extrapolating from `num_turns` would be exactly the manufactured fact §14
forbids.

### 6.6 Soft deadline — MEASURED NOT AVAILABLE; the deadline stays as a measurement

Lane U tested both candidate mechanisms live and both fail as a finalization
window (U-2):

- **SIGTERM is not a graceful finalization.** Sent at 12 s: dead in under one
  second, exit 143, the stream did not grow by a single line, **no `result`
  event**. It is a politer kill.
- **`--input-format stream-json` is a queued message, not an interrupt.** A
  "STOP, do not create any more files" injected at t=10 s was received and
  eventually honoured — after the entire in-flight turn ran to completion, with
  **eight more files written after the stop request**. Time-to-finalization
  equals the remaining duration of the current agentic turn, which is precisely
  the unbounded quantity a soft deadline exists to bound. It also breaks B3's
  one-envelope property (U-2b).

**DECISION D-7 (confirmed by measurement, not by caution): V1 ships no
soft-deadline signalling.** The child's stdin stays `DEVNULL`. §15 is answered
**"not available on 2.1.237"**, and the evidence/validation budget is taken
*after* the kill rather than before it.

**But the soft deadline itself stays** (M-4, and this design agrees). It is not
a "deadline that does nothing"; it is a **measurement**: the run crossed its
finalization window at time T, recorded in `timeout.json`, emitted as a progress
phase, and available to Sol as evidence about how close the run came. It is also
the hook a future mechanism attaches to if one ever ships. **It must not grow a
behaviour before a mechanism is proven** — a test asserts no signal, no write and
no process action is taken at the soft deadline.
### 6.7 Post-timeout trusted validation (§17)

Preconditions, all measured, evaluated in this order:

1. B2 base invariant still holds — `_verify_worktree_base` already ran and
   returned (it is the choke point at `server.py:2006`, ahead of everything);
2. the worktree is still registered with the repository at the recorded path
   (`resolve_worktree`);
3. the primary-tree fingerprint was measurable (`snapshot_primary_tree`
   succeeded both before and after);
4. canonical evidence A was collected successfully;
5. the canonical evidence generator produced a `PathInventory` and did not
   raise an inventory-level failure (a per-path `refused` bucket does **not**
   block post-timeout validation — B-I3);
6. validation commands are the envelope's own trusted commands, unchanged —
   which is structural, since `run_validations` reads
   `envelope.validation.commands` and nothing else;
7. the aggregate run budget still has room (`assert_validation_budget` already
   passed in PREPARE; the remaining wall-clock is checked so a post-timeout
   validation cannot itself blow the MCP tool timeout).

If all hold, `run_validations` is invoked exactly as on the normal path, and the
results are recorded with `phase="post_timeout"`. If any fails, validation is
skipped with a typed reason recorded in
`TimeoutEvidence.post_timeout_validation_skip_reason` — never silently.

**`_land_state` is not touched.** The timeout branch still fires on
`worker_run.timed_out`, still ahead of the provider branch, still behind the
policy branch. Validation results are attached to the `RunRecord`; they do not
enter the state decision. C-I2 is therefore true by construction, and the
mutant "let passing post-timeout validation land `IMPLEMENTED`" is killed by
the state machine itself as well as by an explicit test.

### 6.8 Progress (§18, §19) — server side is expressible today

Verified against the installed SDK at the baseline commit (`mcp` 2.0.0, the
`MCPServer` API, not FastMCP):

```python
# mcp/server/context.py
async def report_progress(self, progress: float, total: float | None = None,
                          message: str | None = None) -> None:
    """Report progress for this request, if the peer supplied a progress token.

    A no-op when no token was supplied.
    """
```

That is exactly the §18 requirement: request-scoped, and a **no-op** when the
caller did not request progress. So "no `progressToken` → no error, no polling"
is a property of the SDK, not something this design must build.

**The architectural problem is Gate 6, not the SDK.** Progress is *request*
scoped; the run is deliberately *not* request scoped (`RunRegistry` +
`asyncio.shield`, so a cancelled waiter never kills a worker). A naive
implementation would hand the run a `Context` and reintroduce exactly the
coupling Gate 6 removed.

**DECISION D-8: a per-run-key progress bus inside `RunRegistry`.**

```python
class RunProgress:
    """Latest phase + a bounded ring of phase transitions for one run key.

    The RUN publishes. WAITERS subscribe. A waiter that goes away unsubscribes
    and the run does not notice — which is the Gate 6 property, preserved.
    """
    def publish(self, phase: str, *, step: int, total: int, message: str) -> None
    def subscribe(self) -> AsyncIterator[ProgressEvent]

class RunRegistry:
    async def run(self, key, factory, *, on_progress: ProgressFn | None = None): ...
```

- the tool body receives a `Context` (via the `@server.tool` adapter — the
  installed SDK injects it by parameter annotation) and passes
  `context.report_progress` as `on_progress`;
- `RunRegistry.run` starts a **separate** relay task that drains the bus and
  calls `on_progress`. The relay is cancelled with the waiter; the run is not;
- two waiters attached to the same resume key each get their own relay, so both
  see progress;
- if `on_progress` is `None` (no `Context`, or a client that sent no token), the
  bus still records phases for the run record and nothing is emitted.

**Throttle.** Phase transitions are emitted immediately; a heartbeat is emitted
at most once every `[progress].heartbeat_seconds` (proposed 30) and only if the
phase has not changed. Absolute ceiling of one notification per second,
enforced in the relay. No per-token, no per-line, no per-byte emission — the
byte pump never publishes.

**Content.** `message` is drawn from a **closed set of format strings** in the
source, with only bounded, non-secret substitutions (integers, ISO timestamps,
phase names, `k/n`). There is no code path from stdout, stderr, prompt, argv,
guidance or skill text to `report_progress`. A test asserts the closed set by
reflection and a second test plants a credential-shaped string in every stream
and asserts it never appears in any emitted notification.

**Zero model turns — measured, not argued.** Structurally, the dispatcher never
returns progress as tool *content*; it is an out-of-band notification on a
pending request. Lane U counted the consequence on the real client: **exactly
one model turn**, with an A/B control at identical prompt and duration showing
10 progress ticks and 0 ticks producing structurally identical rollouts. Every
`progress` substring in the session rollout is a field *name* echoed back inside
the tool *result* payload, never notification content.

**Fire-and-forget is a hard rule, not a style preference.** Codex 0.149.0
receives every notification and surfaces none — not in `--json`, not in
human-readable output, not in the rollout. So nothing in the dispatcher may
block on, await, retry, or condition any behaviour upon a client acknowledging
progress, and **no user-visible text may promise that Sol sees it**. A test
asserts `report_progress` failures are swallowed and never propagate into the
tool result.

### 6.9 Confirmed by measurement — nothing in Subsystem C is now open

Revision 1 listed five questions with fallbacks. Lane U answered all five
(§6.0). The table is kept, with the answers, so a future reader can see which
way each branch went and why:

| # | Question | Measured answer | Branch taken |
|---|---|---|---|
| U-1 | Print-mode incremental machine-readable events? | **YES** — `stream-json` + `--verbose`, one authoritative `result` event, partial stream survives SIGKILL intact | build the streaming parser (§6.5). The spool-growth fallback is **retired**. |
| U-2 | Supported mechanism to request completion before hard kill? | **NO** — SIGTERM does not flush; stream-json input is queued behind the in-flight turn | **D-7 stands: no signalling.** The soft deadline remains a recorded measurement only (§6.6). |
| U-3 | Does Codex 0.149.0 send a `progressToken`? | **YES** | implement `Context.report_progress` (§6.8) |
| U-4 | Does Codex deliver the notifications? | **received on the wire, NOT surfaced** anywhere | server side correct and tested; **G7-4 = CLIENT-LIMITATION** |
| U-5 | Does progress cause a model inference turn? | **ZERO**, counted from the rollout with an A/B control | progress proceeds; C-I5 holds |

§35 permits G7-4 = CLIENT-LIMITATION without blocking the correctness gate,
provided zero-poll behaviour holds, progress never triggers model turns, the
server side is correct and tested, and the limitation is documented honestly.
**All four conditions are measured true.** The limitation is the client's, and
this design does not paper over it: nothing in the dispatcher may promise that
Sol sees progress, and §19's content whitelist still holds — Lane U is explicit
that "notification text never reaches the model" is a *client-version-dependent*
property, not a guarantee, so the whitelist must not be relaxed on the strength
of it.

**Re-probe condition.** Client behaviour is version-specific. Any Codex upgrade
invalidates U-3/U-4/U-5 and the probe must be re-run before the gate report is
signed. The design records the probed version (**0.149.0**) next to the claim.

### 6.9.1 HAZARD — `codex exec` mutates `~/.codex/config.toml` as a side effect

**Discovered live by Lane U while probing U-3/U-4/U-5, and it constrains the
design, not just the probe.**

`codex exec` **auto-writes a project trust entry into `~/.codex/config.toml`**
for whatever directory it is run in. `--ignore-user-config` prevents the user
config from being *loaded*; it does **not** prevent the trust **write-back**.
Lane U hit this and restored the file, verified byte-identical by sha256
(`e41ef3bd…d498e`).

This matters to Gate 7 in three places:

1. **Wave E's conformance measurement is the only way to answer U-3/U-4/U-5**,
   and the only honest way to answer them is to run the *real* installed Codex
   against the *real* dispatcher over real MCP stdio. So Wave E necessarily
   shells out to `codex exec`, and therefore necessarily mutates the operator's
   config unless the harness prevents it.
2. **The §34/hard-line rule "do not change `~/.codex`" is violated by the act of
   measuring**, not by any code the dispatcher ships. That is exactly the kind
   of thing that gets discovered after the fact and reported as "no semantic
   changes" on the strength of nobody having looked.
3. **B4's config-authority property is adjacent.** B4 established that the
   environment cannot redirect the registered MCP server. A tool that silently
   appends trust entries to the file that *registers* that server is writing to
   the same authority surface from a different direction. It does not defeat B4
   (a trust entry is not a server redirection), but any Gate 7 harness that
   leaves stray trust entries behind has degraded the reviewability of the file
   B4 depends on.

**DECISION D-12: every Gate 7 procedure that invokes `codex exec` runs inside a
snapshot/restore/verify wrapper, and the verification is mandatory, not
best-effort.**

```
scripts/mutation/… and any Wave E harness:

  before:  sha256(~/.codex/config.toml) -> recorded; full byte copy -> scratch
  run:     codex exec …                  (trust entry may be appended)
  after:   restore the byte copy
  verify:  sha256(~/.codex/config.toml) == recorded sha256
           -> MISMATCH is a HARD FAILURE of the procedure, reported as such.
              Never "restored, probably fine".
  report:  the recorded sha256 goes into the gate report as evidence that
           "~/.codex semantic changes: NONE" was measured, not assumed.
```

Rules that follow:

- **No Gate 7 test in `tests/**` may shell out to `codex exec`.** The suite must
  remain runnable without touching the operator's home. Codex conformance lives
  in a deliberately-invoked harness under `scripts/`, run once per gate, never
  in `pytest`.
- **The wrapper snapshots before the first invocation and verifies after the
  last**, and also verifies between invocations, so a mid-sequence divergence is
  attributed to the invocation that caused it.
- **`--ignore-user-config` is used anyway** — it is correct for isolating what
  Codex *reads* — but the design must not record it as protection against the
  write. Believing a flag does something it does not do is the same class of
  error as claiming pipe reattachment.
- If a future Codex release removes the write-back, the wrapper stays: its cost
  is two hashes and a copy, and its absence is undetectable until it matters.

The §35 report row **"`~/.codex` semantic changes: NONE unless separately
approved"** is therefore backed by a recorded before/after sha256 pair, not by a
statement of intent.

### 6.10 State transitions, persistent data, error taxonomy

No new `TaskState`. Run state gains no members. Persistent additions:
`runs/NNN/timeout.json`, `runs/NNN/events.jsonl` (conditional), and
`ValidationResult.phase`.

| Code | Class | Meaning |
|---|---|---|
| `ClaudeTimedOut` | existing | unchanged, but its `remediation` is now composed from `TimeoutEvidence` |
| `PostTimeoutValidationSkipped` | *not an error* | recorded as a typed reason string on `TimeoutEvidence`; skipping is not a failure |
| `ProgressChannelUnavailable` | *not an error* | logged at DEBUG; the no-token case is the normal case |

### 6.11 Crash points

| Crash after | Post-condition |
|---|---|
| soft deadline fired, before hard deadline | nothing persisted yet beyond the spool; run reconciles as `ORPHANED` (subsystem D) |
| SIGTERM sent, before SIGKILL | the child may survive; subsystem D's reconciliation is what notices |
| worker exit, before `timeout.json` | streams on disk; `FINALIZING`; remediation recomputed on recovery |
| post-timeout validation half-run | `validation.json` holds what completed; `phase="post_timeout"` distinguishes it |

### 6.12 Tests

- unit: remediation composition for (0 bytes, some bytes, structured result
  present/absent, patch present/absent) — the zero case asserts the literal
  sentence;
- unit: precondition matrix for post-timeout validation, each false case
  producing its own typed reason;
- unit: throttle behaviour, closed-message-set reflection, credential
  non-leakage;
- integration (real fake-binary worker that sleeps past its timeout): zero-output
  timeout says zero output; partial-output timeout preserves exact measured
  bytes; changed worktree + timeout runs trusted validation; timeout + unsafe B2
  state skips validation with a recorded reason; **passing validation does not
  convert `TIMED_OUT` to success**; the worktree is preserved;
- integration over **real MCP stdio** with a client that supplies a
  `progressToken`: notifications arrive while one blocking call is pending;
  `get_task` call count is **0**; no secrets in any notification; throttling
  holds; and a second run with **no** token produces no error and no polling.

### 6.13 Mutation cases

| # | Mutant | Killer |
|---|---|---|
| 13 | claim partial stdout when zero bytes | zero-output remediation test asserting the literal sentence |
| 14 | skip timeout validation unconditionally | changed-worktree-plus-timeout runs trusted validation |
| 15 | progress handler invokes `get_task` | real-MCP-stdio test asserting **0** `get_task` calls |
| 16 | progress causes a model-facing poll loop | same test — the client transcript must show no tool call issued in response to a notification |
| C-a | let passing post-timeout validation land `IMPLEMENTED` | `TIMED_OUT`-stays-`TIMED_OUT` test **and** the state machine itself |
| C-b | gate post-timeout validation on `worker_run.timed_out` again | precondition-matrix test |
| C-c | skip validation silently, without a typed reason | `timeout.json` asserts a non-null `post_timeout_validation_skip_reason` whenever the status is `skipped` |
| C-d | emit progress per output line or per byte | throttle test (≤ 1 notification/second, heartbeat ≥ 30 s when the phase is unchanged) |
| C-e | interpolate stdout/stderr/argv into a progress `message` | closed-format-set reflection test + planted-credential leakage test |
| C-f | call `report_progress` from the run instead of the waiter relay | Gate 6 regression: cancel the waiter, assert the run still completes and persists |
| C-g | treat an intermediate stream event as the final structured result | (conditional on U-1) authoritative-final-event test |
| C-h | signal the child's stdin at the soft deadline | test asserting `stdin=DEVNULL` and that no write is attempted |
| C-i | invoke `codex exec` from `tests/**` | a repository-wide grep test forbidding `codex` invocation under `tests/` |
| C-j | drop the sha256 verification from the Codex config wrapper | harness self-test: deliberately corrupt the restore and assert the wrapper fails |

### 6.14 Backward compatibility

`ValidationResult` gains `phase: Literal["post_run","post_timeout"] = "post_run"`,
so persisted results load unchanged. `RunRecord` gains an optional
`timeout_evidence`. The `blocking` envelope on every tool result is unchanged.
Progress is additive and invisible to a client that does not ask for it.

---

## 7. SUBSYSTEM D — Durable worker ownership and recovery

Covers **G7-8**.

### 7.1 Current failure

`RunRegistry` holds `asyncio.Task` objects in one process (`waiting.py:123`).
The Claude child is created with `asyncio.create_subprocess_exec(...,
stdout=PIPE, stderr=PIPE, start_new_session=True)` (`runner.py:1428`), so the
only handle on it is a pipe pair owned by that process's event loop.

If the dispatcher process dies while a worker lives:

- there is **no persisted record** of the child's identity — no pid, no start
  time, no process group, no expected executable;
- the `flock` on `state/locks/<sha256>.lock` is released by the kernel when the
  process dies, so a new dispatcher will happily acquire it and start a second
  worker against the same repository — the §24 violation;
- the child's stdout/stderr pipes have their read ends closed. The child will
  get `EPIPE`/`SIGPIPE` **the next time it writes**, which may be much later or
  never. It is in its own session (`start_new_session=True`), so it gets no
  `SIGHUP`. It can therefore keep mutating the worktree indefinitely, unobserved
  and undrained;
- the task is frozen in `RUNNING` with a `runs/NNN` directory containing a
  truncated `stdout.raw`.

Lane R's verification found a concrete artefact of exactly this: a stale
`state/locks/4d692f0c….lock` naming a dead pid. And Lane J recorded that
`Dispatcher.drain()` exists but `main()` never calls it, so SIGTERM orphans
in-flight workers today.

### 7.2 New invariants

- **D-I1 (ownership is durable, not process-local).** Before a run is treated as
  `RUNNING`, an ownership record naming the child's identity is durable on disk.
  A dispatcher that never wrote one owns nothing and must say so.
- **D-I2 (write after, never before).** The ownership record is written **after**
  `create_subprocess_exec` returns and the real pid is known. A record written
  before the process exists would name a process that may never have started.
- **D-I3 (PID alone is never identity).** Liveness is decided on
  `(boot_id, pid, /proc starttime ticks)` corroborated by `/proc/<pid>/exe`
  realpath and process group. PID reuse is assumed to happen.
- **D-I4 (never guess).** The probe returns exactly `ALIVE_SAME`, `GONE` or
  `AMBIGUOUS`. `AMBIGUOUS` is never resolved by inference and never optimistically
  read as `GONE`.
- **D-I5 (no fictional reattachment).** The design never claims to re-own a
  previous process's `asyncio` pipes. It eliminates the pipes (D-9) and, where
  a run still cannot be resolved, declares `ORPHANED` / `RECOVERY_REQUIRED`
  honestly.
- **D-I6 (no duplicate, ever).** A repository with a run that is provably alive
  or unresolved refuses new work — across process restart, where `flock` alone
  cannot help because the kernel released it when the owner died.
- **D-I7 (recovery destroys nothing).** Reconciliation never deletes a run
  directory, never reuses a run index, never reuses a worktree, never marks a
  run successful, and never calls an orphan a normal timeout.
- **D-I8 (recovery decides nothing for Sol).** Reconciliation records facts and
  surfaces them; it does not transition the task on the strength of its own
  inference.

### 7.3 The thing this design refuses to pretend

**A newly started Python process cannot re-own the previous process's
`asyncio` subprocess pipes.** File descriptors do not survive process death, and
`/proc/<pid>/fd/1` of a still-running child points at the *write* end; there is
no supported way to acquire the read end of a pipe whose reader is gone. Any
design that claims reattachment is lying.

Sol's ruling is explicit: **explicit degraded recovery beats fictional
reattachment.** So the design does two things — it removes the need for
reattachment where it can, and it declares an honest degraded state where it
cannot.

### 7.4 DECISION D-9: file-backed child streams instead of pipes

**The child's stdout and stderr are opened files, handed to the child as its own
fd 1 and fd 2.** Not `PIPE`.

```python
stdout_fd = os.open(run_dir / "stdout.raw", O_WRONLY|O_CREAT|O_EXCL, 0o600)
stderr_fd = os.open(run_dir / "stderr.log", O_WRONLY|O_CREAT|O_EXCL, 0o600)
proc = await asyncio.create_subprocess_exec(
    *argv, cwd=..., stdout=stdout_fd, stderr=stderr_fd,
    stdin=asyncio.subprocess.DEVNULL, env=..., start_new_session=True)
```

What this buys, and why it is the right answer to §22's "the design MUST solve
pipe ownership":

- **There is no pipe to re-own.** The stream is a file in the run directory. A
  restarted dispatcher opens it and reads it. This solves pipe ownership by
  removing pipes, which is simpler and more robust than a supervisor process.
- **The child never blocks on a full pipe** and never receives `EPIPE` when the
  dispatcher dies. Its behaviour stops depending on the dispatcher's liveness.
- **The complete stream is durable by construction**, not by a pump that a
  cancelled task might have missed. §13's "streams may exist before the final
  result" is satisfied trivially.
- **Progress across restart is free** (§6.5 fallback): `stat(stdout.raw)` gives
  size and mtime, so "last output at" survives the dispatcher.
- **Truncation handling gets simpler**: the in-memory head/tail excerpt is
  produced by *reading* the file at the end, so `MAX_CAPTURED_BYTES` becomes a
  read-time policy rather than a write-time one, and the structured-result
  recovery (`_recover_from_spool`) already works exactly this way.

What it costs, and this is a genuine trade the reviewer must weigh
(**OQ-D1**):

- **stderr redaction moves from write time to read time.** Today
  `StreamCapture._render_spool` redacts line by line on the way to disk
  (`runner.py:1258`). With direct fd handoff, `stderr.log` holds the child's
  raw bytes. Mitigation: the file is 0600 inside a 0700 task tree, and every
  *egress* is already redacted — `_write_run_streams` (`server.py:1592`),
  `cli_failure`'s stderr tail, `_redact_argv`, the `_RedactingFormatter` on the
  log handler, and `_provider_message`. Arguably this is *better* evidence
  discipline (keep the true artefact, redact at every boundary) but it is a
  change to a documented security property and must be stated in
  `docs/SECURITY.md`, not slipped in.
- Live monitoring of stdout for a streaming event parser (§6.5, conditional)
  becomes a tail-follow rather than a pipe read. That is more code, but it is
  the same code the restart path needs anyway.

**DECISION D-10 (revised — reviewer's OQ-D2 answer accepted): no supervisor
process, BUT reconciliation enforces the deadline.**

§22 asks for the supervisor shape to be *evaluated*. Revision 1 evaluated it and
declined it, and the reviewer agreed with the conclusion while showing the
evaluation was missing three things:

1. **D-9 removes today's de-facto reaper.** Today `stdout=PIPE`; when the
   dispatcher dies the read ends close and a chatty child takes `EPIPE`/`SIGPIPE`
   on its next write, which usually terminates it. §7.4 listed *"the child never
   receives `EPIPE`"* as a **benefit** — it is simultaneously the deletion of the
   only thing that currently stops an orphan. **D-9 and D-10 must be weighed on
   one ledger**, and on that ledger revision 1 was a net regression on
   termination: after Gate 7 an orphaned worker would be *more* durable than
   today.
2. **The exit status becomes unrecoverable.** §22 named "writes exit status
   atomically" as a supervisor function; deleting the supervisor deletes the
   function without replacing it (see §7.5A).
3. **"The repository is held closed by a durable claim" is the wrong
   reassurance.** The claim stops *the dispatcher* starting new work. It does
   nothing about what the orphan is doing: for hours past its deadline it keeps
   mutating the worktree, keeps writing to its stdout file unbounded, keeps
   spending the caller's model budget — and since scope and primary-tree
   enforcement are *post-hoc measurements*, not containment, it does so with no
   boundary at all. When recovery finally happens, the evidence describes a
   worktree that a process the dispatcher declared "not ours" continued to
   change.

The supervisor is still the wrong answer, and revision 1's reasoning about *its*
costs stands: a second process lifecycle, a second crash-recovery story, and a
second thing that can hold the repository lock, all to gain one action.

**The right answer uses parts the design already has.** `ownership.json` records
`hard_deadline_at`, `pid`, `boot_id`, `starttime_ticks`, `process_group_id` and
`exe_realpath` — exactly enough to identify and kill the correct process group
with no PID-reuse risk. Reconciliation already computes `ALIVE_SAME`. So §7.6A
adds deadline enforcement at reconciliation time, which closes the entire
residual **for any case where a dispatcher ever restarts**, at the cost of about
thirty lines and no new process.

It does **not** close the case where no dispatcher ever restarts. That residual
is real, is genuinely unclosable without a supervisor, and §23 blesses an honest
degraded state for it. **That** residual is what V1 accepts — a strictly smaller
one than revision 1 proposed.

### 7.4A File-backed streams are NOT redacted (amendment 9 / R-7)

Revision 1 said redaction moves "from write time to read time" and listed five
egresses to redact at. The reviewer's objection is accepted: **"redact at every
egress" is an unbounded obligation whose completeness cannot be tested**, and
revision 1 *added readers in the same document* (restart recovery,
`_recover_from_spool`, the stream-event parser, the `recovery` block). Every
future feature that reads a stream is a new egress, the enumeration lived in
prose, and the planted-credential test proves only that the egresses the author
listed are covered — the same author writes the plant and the assertion set.
That is the B2-shim shape again.

Two facts make the direction right anyway, and the design should state them
because they strengthen the case rather than weaken it:

- **The property being surrendered is already weak.** `runner.py:1268` documents
  it: spool redaction is line-oriented, so a `"key": "value"` pair split across a
  newline **survives into `stderr.log` today**. The choice is "*mostly* redacted
  at rest" versus "raw at rest", not "redacted" versus "raw".
- **`state/tasks/*` is gitignored** (verified), so the commit-a-secret risk is
  already absent. The residual exposure is *copying* — forensic bundles, gate
  attachments, backups.

**DECISION D-21: stop claiming redaction at rest, and make the obligation
structural instead of enumerated.**

1. **`stdout.raw`, `stderr.log` and `events.jsonl` are declared
   PRIVATE, 0600, POTENTIALLY-SENSITIVE INTERNAL EVIDENCE.** No document, no
   docstring and no payload says they are redacted. `docs/SECURITY.md` §1.5 is
   **rewritten**, not amended in passing — it currently states the write-time
   property as a guarantee.
2. **ONE bounded rendering boundary.** A single accessor module — call it
   `streams.py` — is the *only* thing in `src/**` permitted to open those paths.
   Everything that leaves the dispatcher goes through it, and it returns
   **bounded, redacted `str`**. Raw bytes are reachable through exactly one
   explicitly-named function, `read_raw_for_parser()`, used in exactly one place
   (the stream-event parser), which itself emits no text outward.
3. **Raw stream contents are NEVER returned directly** via MCP, logs or
   diagnostics. Not in a tool payload, not in `last_error`, not in a progress
   message, not in the `recovery` block, not in a prompt.
4. **A reflection/AST test asserts no other module in `src/**` opens those
   paths.** This test *can* fail — unlike the one revision 1 proposed — because
   the property it checks ("nobody else opens the file") is decidable from the
   source, whereas "every egress redacts" is not.
5. **A mutation covers it**: *delete the redaction call from the accessor*, and
   *open `stderr.log` directly from a second module*. §11 had neither.

The two alternatives are worse and the design says why, since OQ-D1 asked: a
redacting supervisor reintroduces the process D-10 deleted **and** puts a
redaction bug between the child and the durable artefact — the worst place for
one; a post-exit redaction pass destroys the true artefact, has its own crash
window, and **cannot run at all in the orphan case**, which is the case that
made file-backing necessary.

### 7.5 Durable ownership record (§20)

Written **after** the process exists — `create_subprocess_exec` has returned and
`proc.pid` is known — and before the run is treated as `RUNNING`:

```python
class ProcessIdentity(StrictModel):
    """Everything needed to decide, later and from another process, whether the
    process we started is still the process that is there.

    PID ALONE IS NEVER ENOUGH. PID reuse exists.
    """
    pid: int
    process_group_id: int          # os.getpgid(pid); == pid under start_new_session
    boot_id: str                   # /proc/sys/kernel/random/boot_id
    starttime_ticks: int           # /proc/<pid>/stat field 22
    clock_ticks_per_second: int    # os.sysconf("SC_CLK_TCK")
    exe_realpath: str              # readlink /proc/<pid>/exe at write time
    expected_binary_realpath: str  # os.path.realpath(config.claude.binary)
    argv0: str

class RunOwnership(StrictModel):
    schema_version: Literal["1.0"]
    task_id: str
    run_id: str
    run_index: int
    role: WorkerRole
    kind: RunKind
    lifecycle_phase: str
    state: RunState
    dispatcher_owner_instance_id: str   # uuid4, minted once per Dispatcher
    dispatcher_pid: int
    dispatcher_boot_id: str
    process: ProcessIdentity
    started_at: datetime
    hard_deadline_at: datetime
    soft_deadline_at: datetime | None
    worktree_path: str
    repository_root: str
    session_id: str
    model: str
    stdout_path: str
    stderr_path: str
```

Persisted at `runs/NNN/ownership.json`, atomically, 0600.

**Why `(boot_id, pid, starttime_ticks)` and not pid.** `starttime` is the
process's start time in clock ticks since boot, read from `/proc/<pid>/stat`
field 22. Two processes with the same pid cannot share it except by a
coincidence requiring the reused pid to have started on the identical tick;
`boot_id` removes the cross-reboot case entirely. This is the strongest
practical Linux identity available **without claiming an OS sandbox**, which is
precisely how §21 frames the requirement. `pidfd_open` is deliberately not used:
a pidfd is a file descriptor and does not survive the dispatcher's death, so it
solves nothing for restart recovery.

### 7.5A The exit status is NOT recoverable after dispatcher death (R-5(i))

Revision 1's reconciliation said *"`GONE` → `FINALIZING` if streams **and exit**
are recoverable"*. **No component in this design ever writes an exit marker, and
none can.** Only the parent may `wait()` a child; if the dispatcher died, the
orphan reparents to `init` and its exit code is gone permanently. §22 named
"writes exit status atomically" as a supervisor function, and D-10 declines the
supervisor, so the function is simply absent.

**The design states this rather than implying otherwise**, and the honest
substitute is named:

> A **trailing authoritative `type: "result"` event in `events.jsonl`** is
> evidence that the child ran to completion. It is not an exit status. A child
> killed mid-write is distinguishable from one still writing only by the
> liveness probe, never by the stream alone.

So the reconciliation branch is rebased on that fact:

- `GONE` **and** a trailing `result` event present → the run genuinely finished;
  reconcile to `FINALIZING` and complete the evidence pipeline. `exit_code` is
  recorded as **`None` with `exit_status_recoverable: false`**, never invented,
  never inferred from `is_error`.
- `GONE` **and no** trailing `result` event → **`ORPHANED`**. The run may have
  been killed, may have crashed, may have been reaped by the OS; the dispatcher
  cannot tell and does not guess.

§21's "determine whether it can safely reattach to output/evidence finalization"
is therefore answered **"evidence finalization yes, output ownership never, exit
status never"** — explicitly, in the document, rather than by a branch that
looked reachable and was not.

### 7.6 Restart reconciliation (§21, §23)

On `Dispatcher.__init__` — before any tool can run, and therefore before any
lock can be acquired — every persisted non-terminal run is reconciled:

```
for each task, for each runs/NNN:
    if no reservation.json:                       # R-5(iv): defined, not undefined
        if the directory is empty or holds only index.tmp:
                                    -> ABORTED_PRELAUNCH, NO claim
        else                        -> ORPHANED,           claim written
        # either way the INDEX IS BURNT: mkdir(EEXIST) guarantees it is never
        # reused, which is the property that actually matters.
    elif reservation.state ∈ terminal ∪ {COMPLETE}:  skip
    elif reservation.state == LAND_INCOMPLETE:    -> replay landing (§5.5A)
    elif no ownership.json:
        RESERVED  -> ABORTED_PRELAUNCH   (nothing was started)
        STARTING  -> consult expectation.json (§7.9 M-8) before deciding
    else:
        verdict = probe(ownership.process)
        ALIVE_SAME  and past hard_deadline_at  -> TERMINATE (§7.6A), then re-probe
        ALIVE_SAME  and within deadline        -> ORPHANED + claim
        GONE        and trailing result event  -> FINALIZING  (§7.5A)
        GONE        and no result event        -> ORPHANED + claim
        AMBIGUOUS                              -> ORPHANED + claim
```

`probe()` — **never guesses**:

| Observation | Verdict |
|---|---|
| `boot_id` differs from the current one | **GONE** (machine rebooted; that process cannot exist) |
| `/proc/<pid>` does not exist | **GONE** |
| `/proc/<pid>/stat` field 22 ≠ recorded `starttime_ticks` | **GONE** (pid reuse — a *different* process) |
| starttime matches **and** `/proc/<pid>/exe` realpath == recorded `exe_realpath` **and** `os.getpgid(pid)` == recorded pgid | **ALIVE_SAME** |
| starttime matches but exe or pgid differs | **AMBIGUOUS** |
| `/proc` unreadable, `stat` unparseable, permission denied, or any exception | **AMBIGUOUS** |

`AMBIGUOUS` is never resolved by inference and never optimistically treated as
`GONE`. It is the fail-closed direction.

**ORPHANED / RECOVERY_REQUIRED semantics (§23), exactly:**

- do **not** launch a duplicate worker;
- do **not** mark the run or the task successful;
- do **not** call it a normal timeout — `ClaudeTimedOut` means *the dispatcher
  killed it*, and an orphan was killed by nobody;
- do **not** reuse the worktree or the run index;
- **preserve** every stream and every evidence artefact already on disk;
- surface explicit recovery information to Sol through `get_task` — a
  `recovery` block naming the run index, the recorded process identity, the
  probe verdict, whether a trailing `result` event was present, the preserved
  paths, and the operator remediation. **Bounded and rendered through
  `streams.py` (§7.4A); never raw stream content.**
- the dispatcher **never** silently resumes or starts another worker.

**Task state for an orphaned run — OQ-D3 decided: leave it `RUNNING`** (M-7).
Reconciliation is a read-mostly startup step; transitioning to `BLOCKED` would
be the dispatcher saying what happened, which is Sol's call, and D-I8 forbids
it. `get_task` reports `state: running` alongside the `recovery` block, so the
situation is unambiguous rather than laundered into a terminal state. If Sol
wants orphans on an actionable list, that is a listing concern, not a state
transition.

### 7.6A Reconciliation-time deadline enforcement (amendment 10 / OQ-D2)

**DECISION D-22.** On reconciliation, a run whose probe is `ALIVE_SAME` **and**
whose recorded `hard_deadline_at` has passed is **terminated**:

```
SIGTERM  -> recorded process_group_id     (never a bare pid; never a pgid we
                                           did not record)
wait grace_seconds
SIGKILL  -> same pgid, if still ALIVE_SAME
re-probe -> GONE expected; if still ALIVE_SAME or AMBIGUOUS, record the failure
            and land ORPHANED with the claim retained
```

Rules that keep this from becoming the dispatcher making a judgement call:

- **The deadline is the caller's own declared contract.** `hard_deadline_at` is
  computed from `envelope.execution.timeout_seconds`, which Sol set. Enforcing
  it after a restart is the same class of act as `asyncio.wait_for` enforcing it
  in-process — the dispatcher is not deciding the run should stop, it is
  applying a decision already recorded.
- **`AMBIGUOUS` is NEVER killed.** Identity that cannot be proven is not a
  target. This is the PID-reuse guard doing its real job.
- **A run still inside its deadline is NEVER killed**, however long the
  dispatcher was away.
- **The termination is recorded as a dispatcher action** in
  `reservation.json`'s history, with the exact identity it was performed
  against — pid, pgid, boot_id, starttime_ticks, exe_realpath — so an operator
  can verify the right process was signalled.
- **Exit status is still not recovered** (§7.5A). Terminating an orphan does not
  make its outcome knowable; it stops it doing more damage.

This closes the entire residual **for any case where a dispatcher restarts**.
The case where no dispatcher ever restarts remains open, is genuinely unclosable
without a supervisor, and is what §23's degraded state is for.

**`hard_deadline_at` is therefore load-bearing** and is persisted in
`ownership.json` at launch (§7.5), not derived at recovery time from a timeout
value that a later config edit could have changed.

### 7.7 Repository lock after restart (§24)

`flock` alone cannot express "a prior run may still be active" because the
kernel releases it on process death. Gate 7 adds a **durable claim** beside it:

```
state/locks/<sha256-of-canonical-repo>.lock          (existing flock file)
state/locks/<sha256-of-canonical-repo>.claims/       (NEW)
    <task-id>-<run-index>.json   -> {task_id, run_index, run_dir, verdict,
                                     recorded_at, ownership_path}
```

`RepositoryLock.acquire()` gains a pre-flock step: read the claims directory,
and for each claim re-run `probe()`.

| Claim probe | Result |
|---|---|
| `GONE` and the run has a terminal reservation state | claim is stale — removed, acquisition proceeds |
| `GONE` but the run is non-terminal | claim removed, run reconciled per §7.6; acquisition proceeds only if the reconciliation did not land `ORPHANED` |
| `ALIVE_SAME`, within deadline | **refuse** with `RepositoryBusy` (retryable — the worker is genuinely running) |
| `ALIVE_SAME`, past deadline | terminate per §7.6A, then re-evaluate |
| `AMBIGUOUS` | **refuse** with `RepositoryRecoveryRequired` (**not** retryable) |
| claim file partial or unparseable | **treat as ACTIVE** — refuse with `RepositoryRecoveryRequired`. Fail closed (crash point 14). |

#### Claim retention — the authoritative table (R-5(iii))

Revision 1 contradicted itself: prose said a claim is *"not removed for
`ORPHANED`"* while the table three lines above said a `GONE` non-terminal run
*"claim removed, acquisition proceeds"*. Both cannot hold, and it decides
whether a dead-dispatcher run permanently closes a production repository. **This
table is authoritative and no prose overrides it:**

| Reservation state | Claim | Rationale |
|---|---|---|
| `RESERVED` | **none** | nothing was started; nothing can be running |
| `STARTING` | **held** | a process may exist that we cannot name |
| `RUNNING` | **held** | that is what a claim is for |
| `FINALIZING` | **held** | the child is gone but evidence is in flight; a second worker would race it |
| `LAND_INCOMPLETE` | **held** | §5.5A — released only at `COMPLETE` |
| `COMPLETE` | **released** | terminal and successful |
| `ABORTED_PRELAUNCH` | **released** | no process ever existed |
| `FINALIZATION_FAILED` | **released** | the child is provably gone; the run is terminal and preserved. A failed finalisation must not close a production repository forever. |
| `ORPHANED` | **HELD** | the whole point: unresolved liveness keeps the repository closed until a human or Sol resolves it |

**And the bare-directory case (R-5(iv)) is defined, not undefined.** Revision 1
classified crash point 1 (`mkdir` succeeded, `reservation.json` did not) as
`ORPHANED`, while the reconciliation loop iterated *"each `runs/NNN` with
`reservation.state ∉ terminal`"* — which cannot evaluate a state that was never
written. If it *had* landed `ORPHANED` with a retained claim, **a crash in a
microsecond window before anything was launched would have closed the repository
permanently.** §7.6's loop now handles a missing `reservation.json` explicitly,
and an empty run directory is `ABORTED_PRELAUNCH` with **no claim** — the index
stays burnt (which is the property that matters) and the repository stays open.

**Interaction with Gate 6, preserved.** The in-process `RunRegistry` still
prevents a duplicate *within* one process (key attach) and the flock still
prevents concurrent mutation *between* live processes. The durable claim adds
the third case — a dead process's live worker — which neither of the first two
can see.

**SIGTERM handling.** `main()` gains a signal handler that calls
`Dispatcher.drain(timeout)` and then exits, so a graceful shutdown lets
in-flight runs land their evidence instead of becoming orphans. It cancels
nothing (`drain` already never cancels). This closes Lane J §9.5.

### 7.8 State transitions, persistent data, error taxonomy

Run states used by D: `STARTING`, `RUNNING`, `ORPHANED`, and the terminal ones.
No new `TaskState`.

Persistent: `runs/NNN/expectation.json`, `runs/NNN/ownership.json`,
`state/locks/<digest>.claims/*.json`.

| Code | Class | Retryable | Meaning |
|---|---|---|---|
| `RepositoryRecoveryRequired` | `DispatcherError`, PREPARE phase | **no** | A prior run against this repository is unresolved (`ORPHANED`, or an `AMBIGUOUS` identity, or an unparseable claim). Details name the task, run index, run directory and probe verdict, plus operator remediation. |
| `RunOwnershipUnavailable` | `InternalDispatcherError`, LAUNCH phase | no | `/proc` could not be read to *write* the ownership record. See the termination contract below. |

**`RunOwnershipUnavailable` termination contract (R-10 secondary).** Revision 1
said the run "is terminated and lands `ABORTED_PRELAUNCH`" without saying with
what identity, in what order, or what happens if the kill fails. By this point
the process **exists**, so terminating it is a real kill and needs a contract:

1. the pre-spawn `expectation.json` (below) already names the expected binary
   and the reservation, and `proc.pid` is in hand from `create_subprocess_exec`;
2. write the **repository claim first**, before signalling — if the kill fails
   and the dispatcher then dies, the claim is what stops a duplicate;
3. `SIGTERM` the child's process group (`os.getpgid(proc.pid)`, which is the
   pid itself under `start_new_session=True`), wait `grace_seconds`, `SIGKILL`;
4. if the process is confirmed gone → `ABORTED_PRELAUNCH`, claim released;
5. **if the kill fails or liveness cannot be confirmed → `ORPHANED`, claim
   retained.** A process we could not name and could not kill is exactly the
   case `ORPHANED` exists for; calling it `ABORTED_PRELAUNCH` would assert
   something unproven.

### 7.9 Crash points

**Pre-spawn expectation record (OQ-D4 decided — M-8).** The reviewer's answer is
adopted: narrow the window rather than accept it. `runs/NNN/expectation.json` is
written **immediately before** `create_subprocess_exec` and carries the
reservation identity, `expected_binary_realpath`, `expected_argv0`,
`dispatcher_owner_instance_id`, `boot_id` and `hard_deadline_at`.

It is **explicitly typed as an EXPECTATION, not an ownership claim** — the file
carries `kind: "expectation"` and no `pid` — so D-I2 ("write ownership only
after the process exists") stays intact. Its only use is to make the unnameable
`STARTING` crash *resolvable*: a reconciling dispatcher can scan for a process
matching the expected binary, session and start-time window and report a
**candidate** to the operator, rather than reporting only "something may exist".
A candidate is **never** auto-adopted as ownership and **never** auto-killed —
it is information in the `recovery` block.

| Crash after | Reconciliation verdict |
|---|---|
| `mkdir runs/NNN`, before `reservation.json` | directory is empty → **`ABORTED_PRELAUNCH`, NO claim** (§7.7 R-5(iv)); index burnt by `mkdir(EEXIST)` |
| `reservation.json`, before `expectation.json` | `RESERVED` → **`ABORTED_PRELAUNCH`**, no claim |
| `expectation.json`, before spawn | `STARTING` with an expectation and no pid → **`ORPHANED`**, claim held, `recovery` block reports "no process was confirmed started; a candidate scan found N matches" |
| spawn, before `ownership.json` | `STARTING` → **`ORPHANED`**, claim held, candidate scan reported |
| `ownership.json`, worker alive, **within** deadline | probe → `ALIVE_SAME` → **`ORPHANED`** + claim → repository refuses new work |
| `ownership.json`, worker alive, **past** deadline | probe → `ALIVE_SAME` → **terminate per §7.6A**, then reconcile |
| `ownership.json`, worker already exited, trailing `result` event present | probe → `GONE` → **`FINALIZING`**; evidence pipeline completes; `exit_code = None`, `exit_status_recoverable = false` (§7.5A) |
| `ownership.json`, worker already exited, **no** `result` event | probe → `GONE` → **`ORPHANED`** — the design does not guess whether it finished |
| machine reboot mid-run | `boot_id` differs → **`GONE`** → reconciled without ever probing a reused pid |
| pid reused by an unrelated process | starttime differs → **`GONE`**. Test: ownership record with a real live pid and a deliberately wrong `starttime_ticks`. |
| during a claim write | partial/unparseable claim → **treated as ACTIVE** (§7.7), fail closed |

### 7.10 Tests

- unit: `probe()` truth table, including a synthetic `/proc` fixture directory
  so every branch is reachable without spawning;
- unit: claim lifecycle against the §7.7 authoritative table — one case per
  reservation state, asserting held/released;
- unit: `streams.py` accessor — bounded output, redaction applied, and the
  AST test that no other module opens the stream paths (§7.4A);
- **real-process integration** (§29 demands actual subprocesses and process
  groups). **The fake worker must be UNCOOPERATIVE** — the reviewer's §29 note:
  the existing fake binary exits promptly, and Subsystem D's whole point is a
  child that does not. So these use a child that **ignores `SIGTERM`**, forcing
  the grace/`SIGKILL` path to be exercised rather than assumed:
  - MCP waiter cancel → worker continues (the Gate 6 regression test, unchanged);
  - dispatcher `SIGKILL`ed while a real child sleeps → a second dispatcher
    process starts, reconciles, refuses to launch, and reports the recovery
    block;
  - **deadline enforcement (§7.6A)**: same setup with `hard_deadline_at` in the
    past → the recorded pgid is signalled, the child dies, the action is
    recorded with the identity it was performed against;
  - **`AMBIGUOUS` is never killed**: same setup with a corrupted `exe_realpath`
    → no signal is sent, `ORPHANED`, claim retained;
  - **pid-reuse simulation**: ownership record pointing at a live pid with a
    wrong starttime → verdict `GONE`, no attachment, no kill;
  - identity ambiguity (unreadable `/proc` entry, simulated) → fail closed;
  - a run whose child completed while the dispatcher was dead → **streams**
    recoverable from the file-backed spool, and the trailing `result` event
    drives `FINALIZING`; **exit status is asserted to be `None`**, proving the
    design does not invent one;
  - `SIGTERM` to the dispatcher → `drain()` lets the run land, no orphan.

### 7.11 Mutation cases

| Mutant | Named targeted killer |
|---|---|
| remove `ownership.json` write | `test_restart_reconciles_unowned_run` |
| treat pid existence as sufficient identity | `test_pid_reuse_is_not_attachment` |
| treat `AMBIGUOUS` as `GONE` | `test_ambiguous_identity_fails_closed` |
| **kill an `AMBIGUOUS` run** | `test_ambiguous_identity_is_never_signalled` |
| **skip deadline enforcement on `ALIVE_SAME` past deadline** | `test_orphan_past_deadline_is_terminated` |
| **kill a run still inside its deadline** | `test_orphan_within_deadline_is_not_terminated` |
| derive `hard_deadline_at` at recovery time instead of reading it | `test_deadline_read_from_ownership_not_config` |
| launch a duplicate after restart | `test_no_duplicate_worker_after_restart` |
| remove the repository claim on `ORPHANED` | `test_orphaned_run_holds_repository` |
| **retain the claim on `FINALIZATION_FAILED`** | `test_finalization_failed_releases_repository` |
| **retain a claim for a bare run directory** | `test_bare_run_directory_does_not_close_repository` |
| treat an unparseable claim as absent | `test_partial_claim_file_is_active_claim` |
| write `ownership.json` **before** the process exists | `test_recorded_pid_is_the_real_child` |
| **write a pid into `expectation.json`** | `test_expectation_record_carries_no_pid` |
| **auto-adopt a candidate from the expectation scan** | `test_candidate_is_reported_never_adopted` |
| mark an orphaned run `TIMED_OUT` | `test_orphan_is_not_a_timeout` |
| **invent an exit code for a `GONE` run** | `test_exit_status_not_recoverable_is_none` |
| go back to `stdout=PIPE` | `test_streams_recovered_after_dispatcher_death` |
| **open `stderr.log` from outside `streams.py`** | `test_only_streams_module_opens_raw_streams` (AST) |
| **delete the redaction call in the accessor** | `test_accessor_output_is_redacted` |

### 7.12 Backward compatibility

Tasks with existing `runs/NNN` and no `ownership.json` reconcile as `COMPLETE`
(if `dispatcher-result.json` is present) or `ORPHANED` (if not) and are never
reused as indexes. No `TaskRecord` field is required. `RunRegistry`'s public
surface is unchanged apart from the optional `on_progress` argument. The
`stdout.raw`/`stderr.log` paths and semantics are unchanged from a reader's
point of view; only the writer changes.

---

## 8. Failure ordering (§28) — REORDERED (amendment 4 / R-4)

Revision 1 put *unsupported untracked file → evidence failure → FAILED* **above**
*scope violation → POLICY_VIOLATION*. That gave a worker a one-command downgrade
from the signal Sol reads to know a boundary was breached. **The ordering is
reversed, and the reason it can be reversed is that the path inventory is now
produced before, and independently of, content generation (§5.3A, §5.4B).**

```
 0. PREPARE refusals            -> NO lifecycle mutation. state.json byte-identical.
                                   Logged to refusals.jsonl. NEVER FAILED.
                                   (lifecycle infeasibility, hash drift, budget,
                                    ContextTooLarge-in-preflight, RepositoryBusy,
                                    RepositoryRecoveryRequired,
                                    EvidenceIncompleteForReview,
                                    EvidenceExceedsReviewBudget)

 1. LAUNCH failures             -> FAILED from ROUTED / RESUME_REQUESTED.
                                   NEVER leaves the task in RUNNING (§3.1).
                                   (spawn failure, kernel E2BIG,
                                    ClaudeBinaryNotFound, spool-open failure)

 2. worktree base mismatch      -> FAILED, BEFORE any evidence is collected.
                                   No inventory, no diff, nothing measured.

 3. INVENTORY failure           -> FAILED. The authoritative path list could not
                                   be produced or cannot be represented, so no
                                   policy question can be answered.
                                   (GitEvidenceCollectionFailed,
                                    PathInventoryUnrepresentable)

 --- from here the inventory EXISTS, so policy is ALWAYS decided ---

 4. evidence-authority tamper   -> POLICY_VIOLATION.
                                   (.gitattributes / .gitignore / .git/** write,
                                    index tamper bits, git-admin fingerprint moved)

 5. scope violation /           -> POLICY_VIOLATION. Outranks worker success, and
    primary-tree interference      now also outranks every content-level refusal.
                                   A symlink, oversized or unreadable file that is
                                   OUT OF SCOPE lands here on its authoritative
                                   path — it is NOT laundered into FAILED.

 6. timeout                     -> TIMED_OUT. Stays TIMED_OUT even if
                                   post-timeout validation passes.

 7. provider limit / API error  -> FAILED (B3 classification, unchanged).

 8. unusable worker report      -> FAILED (cli_unusable / unparseable)

 9. non-zero exit               -> FAILED

10. worker-reported blocked/    -> BLOCKED / FAILED
    failed

11. otherwise                    -> IMPLEMENTED -> AWAITING_SOL_REVIEW
```

**Per-path content refusals are not in this ladder at all.** They are buckets on
`CanonicalEvidence` (B-I3): they set `patch_file_complete = False`, they make
Fable refuse (B-I7), and they are reported — but they never decide the task's
state. This is the whole of amendment 4.

Orthogonal to the ladder, not competing with it:

- **run finalization failure** → the run is preserved with reservation state
  `FINALIZATION_FAILED`; the index is never reused; the repository claim is
  released; the task lands wherever the ladder put it, or stays where it was if
  the ladder never ran.
- **landing interrupted** → reservation `LAND_INCOMPLETE`, claim **retained**,
  transitions replayed idempotently on restart (§5.5A).
- **orphaned run** → no task transition; `get_task` carries a `recovery` block;
  the repository stays claimed (§7.6, §7.7).

Rows 2, 5, 6, 7 are today's behaviour and are asserted unchanged. Rows 0, 1, 3
and 4 are new. Every row is pinned by an integration test, **and** by a
deliberately-conflicting test that constructs a timeout **plus** an out-of-scope
change **plus** a 429 envelope in partial stdout **plus** an untracked symlink,
and asserts `POLICY_VIOLATION` — the row that must win, and the one revision 1
would have lost.

## 9. Size economics (§26)

### 9.1 Where the duplication is, conceptually

The seven general-purpose documents that dominate the payload restate the same
small set of ideas. Measured projected sizes at baseline (after frontmatter
stripping and delimiters, co-projected supporting files included once):

| Document | Bytes | Core idea it carries that no other document carries |
|---|---|---|
| `superpowers.test-driven-development` | 17,538 | write the failing test first |
| `agent-skills.code-review-and-quality` | 18,339 | the five review axes |
| `agent-skills.security-and-hardening` | 18,751 | the threat checklist |
| `agent-skills.code-simplification` | 13,413 | reduce complexity without changing behaviour |
| `agent-skills.incremental-implementation` | 13,176 | *(mostly overlap)* |
| `agent-skills.planning-and-task-breakdown` | 11,547 | decomposition with acceptance criteria |
| `agent-skills.debugging-and-error-recovery` | 10,484 | reproduce before fixing |
| `superpowers.receiving-code-review` | 6,083 | *(mostly overlap)* |
| `superpowers.verification-before-completion` | 3,553 | evidence before claiming done |

The overlap map — each ✓ is a full restatement of the same idea in a different
document's voice:

| Idea | incr | plan | debug | TDD | verify | review | recv-review |
|---|---|---|---|---|---|---|---|
| work in small verified increments | ✓ | ✓ | | ✓ | | | |
| run the real command, read the real output | ✓ | | ✓ | ✓ | ✓ | | ✓ |
| evidence before claims | ✓ | | ✓ | ✓ | ✓ | ✓ | ✓ |
| do not declare done without proof | ✓ | ✓ | | ✓ | ✓ | | ✓ |
| reproduce before you fix | | | ✓ | ✓ | | | ✓ |
| state what you did not verify | | | ✓ | | ✓ | ✓ | ✓ |
| address the finding, not the reviewer | | | | | | ✓ | ✓ |

Five ideas appear in five or more documents. That is the duplication, and it is
conceptual, not textual — which is exactly why a runtime de-duplicator cannot
find it and a reviewer can.

### 9.2 Targets

Targets are **review outcomes, not runtime caps.** The engine's cap stays at
`[skills].max_projected_bytes = 72_000` and still fails closed; the targets
below are what the reviewed compact artifacts must come in under for the profile
space to be feasible with headroom. **Nothing truncates at runtime, ever.**

| Profile | Current (typical → worst) | Target | Rationale |
|---|---|---|---|
| `DISPATCH_IMPLEMENTATION` | 44,757 → 89,376 | **≤ 24,000 B**, typical ~16,000 | core loop + validation discipline + at most one conditional artifact |
| `CORRECTION_RESUME` | 50,842 → 95,461 | **≤ 12,000 B** | correction response + validation discipline. **No planning material** (§4). |
| `VALIDATION_ONLY_RESUME` | n/a (identical to correction today) | **≤ 6,000 B** | validation discipline only |
| `FABLE_REVIEW` | 0 (skills) | **0 B (skills)** | unchanged — Fable receives no implementation methodology (Gate 4.5 §15). Its 16,602 B composed context is guidance + policy and is out of scope here. |

Consequences at the target sizes, against `MAX_APPEND_SYSTEM_PROMPT_BYTES =
122,880` and the measured production guidance worst case of 41,955 B plus 4,718 B
of dispatcher-authored text:

```
worst dispatch today:   89,376 + 41,955 + 4,718 = 136,049  -> INFEASIBLE
worst resume today:     95,461 + 41,955 + 4,718 = 142,134  -> INFEASIBLE (= the
                                                              142,006 B figure
                                                              Lane G measured)
worst dispatch target:  24,000 + 41,955 + 4,718 =  70,673  -> 57% of ceiling
worst resume target:    12,000 + 41,955 + 4,718 =  58,673  -> 48% of ceiling
```

The 42%-infeasible profile space becomes **0% infeasible with 52,000 B of
headroom**, and the G7-1 trap disappears not because the check was relaxed but
because the payload stopped being absurd.

**What the targets must not do.** They must not be met by cutting approved
methodology. The acceptance criterion for each compact artifact is a review
finding — *"does this preserve the approved methodology of its sources?"* —
recorded in `approved-lifecycle-profiles.json` alongside the enumerated
concepts. If a target cannot be met without losing methodology, **the target
moves, not the methodology.** That is why the engine cap stays at 72,000 and why
`LifecycleInfeasible` exists: an over-target-but-feasible profile ships; an
infeasible one refuses.

### 9.2A The matrix must be parameterised by the CAP, not by a fixture (R-9)

The reviewer found a hole in the design's own headline test, and it is the
B2-shim shape: **composed bytes are a function of the target repository's
project guidance** (measured production worst case 41,955 B), which is **not**
part of `TaskKind × Complexity × RiskLevel`. A unit matrix composed against a
small fixture's guidance would assert "zero infeasible" while real shapes are
infeasible — a double whose simplification is the precise inverse of the
production fault, violating this design's own §10.2 rule 1.

**DECISION D-23. The matrix is evaluated against the guidance CAP, not a
fixture's actual size.** Each phase's feasibility number is

```
composed = skills_projected_bytes
         + [project_guidance].max_projected_bytes      # the CAP, 42,000
         + dispatcher_authored_bytes                    # measured, policy + preamble
```

so the matrix answers *"is this phase feasible for **any** legal repository this
dispatcher is configured to serve?"* rather than *"for this fixture"*. The
runtime preflight (§4.5) still composes and measures the **actual** payload —
that is the authoritative check — but the matrix, which is the test that would
have to fail for a trap to be caught early, is cap-parameterised and therefore
cannot be made to pass by choosing a convenient fixture.

**A second R-9 hole: the matrix depends on the operator's `~/.claude` plugin
cache**, because `derived_from[].source_sha256` must still match the real
install root. On a host whose cache differs, the "single most valuable test in
Subsystem A" does not measure — it raises `ApprovedSkillChanged`. **Decision:
the test SKIPS with an explicit `NOT-MEASURED` marker naming the drifted skill
id, and the gate report carries that marker.** It does **not** skip hash
verification — the tempting answer, and exactly the property that must not be
weakened. A `NOT-MEASURED` matrix is never counted as a pass (§10.2 rule 6), and
the gate cannot be signed with one outstanding.

### 9.3 Reporting (§35)

The final gate report must carry, per phase, the before/after byte pair for at
least: `implementation`/medium/medium, `implementation`/high/high,
`security_sensitive`/high/high (the worst shape), and `refactor`/low/low (the
surprising one). The full 120×2 matrix is produced by a script under `scripts/`
and attached, **with the guidance cap it was evaluated against stated on the
report**, since the numbers are meaningless without it.

It must also state, explicitly (amendment 6 / R-6): **the shipped default of
`[lifecycle].enabled` and `[lifecycle].preflight_required` in the canonical
production config.** Gate 7 cannot be reported PASS while either bypasses the
lifecycle machinery, because the §35 byte rows would then describe a
configuration nobody runs.

---

## 10. Test strategy and what the doubles must not do (§29)

### 10.1 Per-invariant coverage

| Invariant | Unit | Real disposable integration |
|---|---|---|
| A-I1 feasibility before first worker | ✓ | ✓ (dispatch of a trap shape is refused with no task created) |
| A-I2 determinism | ✓ (120×2 matrix is stable across runs) | — |
| A-I3 monotone lattice | ✓ (set containment) | — |
| A-I4 provenance / hash drift | ✓ | ✓ (mutate a source file on disk in a temp install root) |
| A-I6 zero mutation | ✓ | ✓ (**sha256 of `state.json` before/after**) |
| B-I1 one generator | ✓ (single-producer reflection) | ✓ |
| B-I2/3 completeness produced | ✓ | ✓ (real git, real untracked files) |
| B-I4 attribute-proof | — | ✓ (real `.gitattributes` + real `git config`) |
| B-I5 no index mutation | ✓ | ✓ (`.git/index` mtime+sha256 unchanged across evidence collection) |
| B-I6 path fidelity | ✓ | ✓ (real non-ASCII filenames) |
| B-I8/9/10 run identity | ✓ | ✓ (crash injection, real process death) |
| C-I1 measured remediation | ✓ | ✓ (fake worker emitting exactly 0 bytes) |
| C-I2 timeout stays timeout | ✓ | ✓ |
| C-I3 preconditions | ✓ | ✓ |
| C-I5/6 progress | ✓ | ✓ (**real MCP stdio** client supplying a progressToken) |
| D ownership / probe | ✓ (synthetic `/proc` fixture) | ✓ (**real subprocesses and process groups**) |
| D no duplicate after restart | — | ✓ (real dispatcher process killed and restarted) |

A **small final live gate** with the real Claude CLI, in a disposable
repository, covers only what fake behaviour would make meaningless: that a real
worker's real stdout lands in a file-backed spool, that a real timeout produces
factual remediation, and that a real MCP stdio client sees progress. **No
full-voice-agent.**

### 10.2 What the doubles must NOT do — the B2 lesson, stated as rules

The B2 diagnosis is unambiguous, and the sentence must be carried forward
verbatim into the test design: the old `tests/fixtures/claude_worktree_shim.py`
diverged from the real CLI on exactly the two axes where the two production
faults lived, and the divergences were *"honest, reasonable simplifications that
happen to be the precise inverse of the two production faults. No amount of
testing against this double could have found either defect."*

Concretely, the shim ran `git worktree add -b <name> <target>` with **no
start-point**, so the worktree's base always equalled `HEAD` and B2 was
unreachable by construction; and it placed the worktree at
`<repo-parent>/.sol-test-worktrees` — *"outside the repository, so the primary
tree stays clean"* — so K-2 was unreachable by construction.

The rules, which every Gate 7 double must satisfy:

1. **A double must not make the production failure mode unreachable by
   construction.** If the real dependency can disagree with the dispatcher, the
   double must be *able* to disagree. A double that always agrees can never fail
   the check the double exists to exercise.
2. **A double must not tidy away the real dependency's inconvenient side
   effects.** Convenience-for-the-suite and fidelity-to-production pull in
   opposite directions, and the tidy choice is reliably the one that hides the
   defect.
3. **A fixture must not pre-create the condition under test.** (Lane P
   deliberately omitted the Gate 6 fixture's `.claude/worktrees/` placeholder so
   that K-2's resolution was *tested*, not assumed.)
4. **Prefer removing the double from the causal path over enriching it.** Lane O
   did not teach the shim about start-points; it made the dispatcher create the
   worktree so the shim decides nothing. Gate 7 follows the same pattern:
   - **evidence**: no git double at all. Real `git init`, real worktrees, real
     untracked files, real `.gitattributes`. The only fake is the worker binary.
   - **run transaction**: no filesystem double. Real directories, real crashes
     (`os._exit` in a real subprocess) at the ten injection points.
   - **ownership**: no `/proc` double for the integration arm. Real children,
     real process groups, a real dispatcher process killed with `SIGKILL`. A
     synthetic `/proc` fixture is used **only** in unit tests, to reach branches
     (unreadable `stat`, malformed field 22) that cannot be produced on demand.
   - **progress**: no MCP double. A real stdio subprocess and a real client that
     supplies a `progressToken`.
5. **Specifically forbidden for Gate 7**, each because it would encode the
   inverse of the defect:
   - a fake evidence generator that returns `patch_file_complete=True`;
   - a git double that never emits quoted paths (V-2 becomes unreachable);
   - a git double with no `.gitattributes` support (V-1 becomes unreachable);
   - a run-directory double where `mkdir` is idempotent (G7-7 becomes
     unreachable);
   - a process-identity double that returns `ALIVE` for any live pid (the
     pid-reuse case becomes unreachable);
   - a `Context` double whose `report_progress` records without a token check
     (the "no token → no-op" property becomes unreachable).
6. **NOT-TESTABLE is a first-class result** and is never recorded as PASS. A
   429/zero-token run is never a pass and never suppression evidence, and a
   `NOT-MEASURED` matrix (§9.2A) is never counted as a green row.
7. **A double must not be more cooperative than the real thing.** The existing
   fake worker exits promptly; Subsystem D's entire point is a child that does
   not. Subsystem D's and Subsystem C's process tests use a child that
   **ignores `SIGTERM`**, so the grace/`SIGKILL` path is exercised rather than
   assumed.

### 10.2A Where revision 1 repeated the mistake anyway

The reviewer found §10.2 to be the best-written section of revision 1 and then
found three places the document violated its own rules. All three are fixed, and
they are recorded here because the pattern is the reason this gate exists —
**in each case the design stated a property and named a proof that could not
observe it**:

| Revision 1 proof | Why it could not fail | Fixed by |
|---|---|---|
| the AST test pinning the refusal/failure split | **zero** `PrelaunchRefusal` subclasses are raised in `server.py`; they propagate in from four other modules. The scan found nothing before, after, or under its own mutant. | §3.1 — mechanism replaced entirely; the byte-identical `state.json` test is the pin, and a **call-site whitelist** AST test replaces the `raise` scan |
| the planted-credential redaction test | the same author writes the plant and the assertion list, so it cannot observe an egress nobody thought of | §7.4A — one accessor module, and an AST test that **no other module opens the stream paths**, which is decidable |
| the 120×2 feasibility matrix | composed against a fixture's ~0 B guidance while production is ~42 KB — the precise inverse of the production fault | §9.2A — parameterised by the guidance **cap**, not a fixture |
| mutant A-d | unkillable under the shipped config, because the config cross-validator makes the skills cap strictly binding | §11.2 — deleted with a written equivalence proof, replaced by A-d′ |

### 10.3 The suite must not touch the operator's home

Two rules, one of which is new and was found the hard way (§6.9.1):

- **`tests/**` never shells out to `codex exec`.** `codex exec` auto-writes a
  project trust entry into `~/.codex/config.toml` for whatever directory it runs
  in, and `--ignore-user-config` stops the *load*, not the *write-back*. A test
  suite that invoked it would silently mutate the operator's config on every
  run. Codex conformance is measured once per gate, by a deliberately-invoked
  harness under `scripts/`, wrapped in snapshot/restore/**verify-by-sha256**
  (D-12). A restore that does not verify is a hard failure of the procedure.
- **`tests/**` never reads or writes `~/.claude`.** `tests/conftest.py` already
  sets `HOME` into `tmp_path` for its git fixture; every Gate 7 fixture that
  spawns a subprocess does the same. The approved-skill manifest's pinned plugin
  install paths *are* read (they must be — that is the hash verification), but
  read-only, and the hash-drift tests operate on a **copied** install root in
  `tmp_path`, never on the real one.

---

## 11. The mutation suite lives in source control (§31)

**Finding, confirmed while writing this document: the `/tmp` mutants are already
gone.** `find /tmp -iname '*mutant*'` returns nothing at the baseline commit.
Lane R's F2 said a reboot would destroy 38 of 52 mutants' replayability; the
window has closed. Gate 7 must not repeat it.

**DECISION D-11.** A canonical, source-controlled mutation runner:

```
scripts/mutation/
  run_mutations.py          # canonical runner: apply, run killers, restore,
                            # verify sha256 restoration, report
  mutants/
    gate7/
      A01_resume_profile_adds_full_planning.py
      A02_resume_profile_adds_overlapping_review_skill.py
      …
  README.md                 # how to add a mutant; why survivors are never
                            # "equivalent" without proof
```

Each mutant is a declarative patch (target file, exact anchor text,
replacement) plus its expected killer test node ids. The runner:
1. records `sha256` of every target file;
2. applies the mutant;
3. runs the declared killers **and** the full suite;
4. restores and **verifies byte-identical restoration by sha256**, failing the
   whole run if restoration is not exact;
5. emits a machine-readable report (`mutations.json`) with per-mutant
   caught/survived and first-killer node id.

The 38 existing Gate-6-era mutants (Lanes J 9, N 5, O 16, Q 8) are **ported into
this runner** as part of Wave A so that the persisted suite is the whole suite,
not just the new half. Lane L's 14 unreplayable mutants are recorded as
`NOT_REPLAYABLE` with their provenance, never invented.

### 11.1 The §31 named mutants and their owning subsystem

| # | Mutant | Owner |
|---|---|---|
| 1 | resume profile adds full planning again | **A** |
| 2 | resume profile adds overlapping review skill again | **A** |
| 3 | skip lifecycle future-phase preflight | **A** |
| 4 | move preflight after the `RUNNING` transition | **A** |
| 5 | mark untracked-omitting patch complete | **B** |
| 6 | drop the synthetic untracked patch | **B** |
| 7 | skip the untracked diff-check | **B** |
| 8 | reuse `run_count + 1` orphan directory | **B** |
| 9 | increment `run_count` only on successful finalization | **B** |
| 10 | remove the durable ownership record | **D** |
| 11 | treat PID existence as sufficient identity | **D** |
| 12 | launch a duplicate after restart | **D** |
| 13 | claim partial stdout when zero bytes | **C** |
| 14 | skip timeout validation unconditionally | **C** |
| 15 | progress handler invokes `get_task` | **C** |
| 16 | progress causes a model-facing poll loop | **C** |

Beyond §31's sixteen, this design requires the mutants listed per subsystem in
§4.11, §5.11, §6.13 and §7.11 — including the eight the reviewer identified as
missing (R-14), each of which attacks an invariant **this design introduces**:

| Missing in revision 1 | Now at |
|---|---|
| reorder the §8 ladder (evidence refusal above/below policy violation) | §5.11 — R-4 is exactly this, and nothing would have caught it |
| delete the redaction call from one egress | §7.11 — the whole OQ-D1 risk surface had no mutant |
| open a raw stream from outside the accessor | §7.11 |
| move a refusal-capable **call** back inside the mutation block | §4.11 A-c′ — the mutant that matters for R-3 |
| `git add -N` / any index write | §5.11 — B-I5 had a test, no mutant |
| drop `--no-ext-diff`; drop the hardened prefix from a **non-diff** git call | §5.11 — R-1 item 1 |
| make `_record_failure`'s early return silent | superseded: the phase-carrying mechanism (§3.1) removes the silent-return path entirely |
| read only the head of `stdout.raw` for the retained excerpt | §6.13 — R-11's B3 tail invariant |

### 11.2 Amendment 12 — three rules the runner must enforce

**(1) Mutants execute against the PRODUCTION-ACTIVE lifecycle configuration.**
Not a fixture config, not `[lifecycle].enabled = false`. A mutation suite that
runs against a configuration production does not use proves nothing about
production — and after D-14 the production-active configuration is the only one
Gate 7 may pass with. The runner asserts the config it loaded has
`[lifecycle].enabled = true` and `preflight_required = true` before it starts,
and refuses otherwise.

**(2) The 120×2 matrix is coverage, never the sole proof of any critical
invariant.** Revision 1 leaned on it as the headline test for Subsystem A. That
is the B2-shim shape: one broad assertion standing in for many specific ones,
which fails silently when its parameterisation drifts (R-9). **Every critical
mutant in §4.11, §5.11, §6.13 and §7.11 names a targeted killer test**, and the
matrix is listed as an *additional* killer, never the only one.

**(3) Mutant A-d is DELETED, not weakened.** Revision 1's A-d — "measure
per-component byte sums instead of the composed payload" — was declared killed
by *"a shape whose components each fit and whose composition does not"*. The
reviewer measured that **under the shipped config no such shape can exist**:
`config.py:596-640` refuses any configuration where
`skills_cap + guidance_cap + 8192 > 122,880`, and the shipped values are
72,000 + 42,000 + 8,192 = 122,192, so the skills cap is **strictly the binding
gate**. A-d was an equivalent mutant by construction and would have survived —
and §31 forbids papering a survivor over as equivalent without written proof.

It is replaced by **A-d′**, which is killable: *"compose the feasibility check
from per-component sums"*, killed by
`test_dispatcher_authored_growth_is_caught_by_composed_check` — a case that
deliberately grows the dispatcher-authored text past its 8,192 B reserve, where
the component sums still pass and only the composed measurement fails. The
design states the equivalence proof for the deleted A-d in the runner's README,
as §31 requires, rather than silently dropping it.

**Also retired: revision 1's newline mutant.** It was scoped to "a newline in a
filename splits one path into two entries", which the reviewer measured to be
**false** — C-quoting escapes the newline. A mutant aimed at a non-existent
failure mode is a mutant that gets quietly retired later, so it is retired now,
deliberately, and replaced by `test_v2_newline_filename_is_one_inventory_entry`
(§5.11), which targets the hazard that **does** exist: `core.quotePath=false`
applied *without* `-z`.

### 11.3 Runtime — the suite must be fast enough to actually run

The reviewer's process risk is real: revision 1 had the runner execute the
declared killers **and the full suite** per mutant. With ~65 mutants (38 ported
+ 16 named + 11 additional) that is 65 full-suite runs at ~3.5 minutes each —
nearly four hours. **A suite too slow to run is a suite that does not run, which
is precisely how the `/tmp` corpus died.**

| Mode | What it runs | When |
|---|---|---|
| `--fast` (default) | each mutant's **declared killers only** | routine use, per wave, per PR |
| `--full` | declared killers **and** the full suite, per mutant | gate time, once, and after any change to the runner itself |

`--fast` is what a developer runs; `--full` is what signs the gate. The report
records which mode produced it, and a `--fast` report may not be attached to a
gate submission.

---

## 12. Wave sequencing and `server.py` conflict control (§32, §33)

**Revised: amendments 1 and 8.** Wave 0 is inserted ahead of everything, and
D now precedes C.

```
WAVE 0  evidence AUTHORITY + path IDENTITY        (V-1, V-2, V-4, V-5)
        -> the git invocation policy, the clean temporary index, the
           ignore-suppression and index-tamper audits, the -z inventory,
           the git-administrative fingerprint, the deny-list additions
        -> docs/SECURITY.md updated IN THIS WAVE
        -> FULL SUITE + FULL MUTATION REPLAY

WAVE A  lifecycle profiles + feasibility preflight (G7-1, G7-5, G7-6)
        -> the EXECUTION PHASE mechanism (§3.1) lands here
        -> ACCEPTANCE REQUIRES [lifecycle].enabled = true in the canonical
           production config (D-14 / amendment 6)
        -> FULL SUITE + FULL MUTATION REPLAY

WAVE B  run reservation + canonical evidence       (G7-2, G7-7)
        -> depends on Wave A: EvidenceIncompleteForReview is a PREPARE-phase
           refusal, so the phase mechanism must be settled first
        -> the LAND_INCOMPLETE transaction (§5.5A) lands here
        -> FULL SUITE + FULL MUTATION REPLAY

WAVE D  durable ownership + file-backed streams     (G7-8)
        -> MOVED AHEAD OF C (amendment 8 / R-11): file-backing is what makes
           stdout_bytes mean "bytes the child wrote", and Wave C's central
           claim is that the number is measured rather than asserted. Doing C
           first would found that claim on a definition about to move.
        -> streams.py, the single rendering boundary (§7.4A)
        -> FULL SUITE + FULL MUTATION REPLAY

WAVE C  stream-json timeout evidence + post-timeout validation   (G7-3)
        -> now unconditional: Lane U measured stream-json SUPPORTED
        -> FULL SUITE + FULL MUTATION REPLAY

WAVE E  MCP progress notifications                  (G7-4)
        -> server side is protocol-correct and testable regardless
        -> its Codex conformance harness invokes `codex exec`, which auto-writes
           a trust entry into ~/.codex/config.toml. Snapshot / restore /
           verify-by-sha256 around every invocation (D-12, §6.9.1).
           NOT run from pytest. Sol's explicit consent recorded BEFORE it runs
           (M-9 / OQ-E1).
        -> expected outcome: CLIENT-LIMITATION, which does not block the gate
        -> FULL SUITE + FULL MUTATION REPLAY

FINAL   all waves together · full tests · `--full` mutation replay · doctor ·
        skills audit · guidance audit · activation checker · B4 check ·
        real MCP stdio · disposable live Claude
```

**Why Wave 0 is first and is no longer small.** Revision 1 called it "the
cheapest wave in the plan". Lane X's findings changed that: V-4 and V-5 are
scope-enforcement bypasses reachable with **no denied command at all**, and
closing them needs the clean temporary index, two positive audits, and an
extension of the primary-tree invariant. It is now a substantial wave — and it
is still first, because the production freeze is held partly *because evidence
integrity is in doubt*, and scheduling known live holes behind five other waves
would mean the freeze is held for defects that were known and deferred.

**Each wave starts from the previously accepted wave**, not from the baseline.
No wave merges until its suite and the *cumulative* mutation suite are green.

**`server.py` is integrated SEQUENTIALLY.** Every wave touches
`Dispatcher._dispatch`, `_resume`, `_review` or `_finalise_worker_run`. Parallel
lanes are permitted only on disjoint ownership:

| Parallelisable | Serial (one lane at a time) |
|---|---|
| `lifecycle.py`, `evidence.py`, `runs.py`, `ownership.py`, `streams.py` (new modules) | **`server.py` orchestration** |
| the compact artifact authoring + review | `git.py` (Wave 0 owns `_run_git`; Wave B owns the generator) |
| `scripts/mutation/**` | `runner.py` (Waves D and C both touch `run_worker`) |
| tests for a new module | `models.py` / `state.py` schema additions |
| capability probes (Lanes U, X) | `locks.py` (Wave D) |

Concretely: the wave that owns `server.py` for its slot holds it exclusively;
other lanes deliver modules and tests that the `server.py` owner then wires in.
**No blind merge of two branches that both edited `server.py`.**

**Rebase discipline.** Wave N+1 branches from Wave N's accepted commit. If Wave
N's review requires changes, Wave N+1 **rebases rather than merging**, so the
`server.py` history stays linear and each wave's diff is reviewable in
isolation. §33 is the requirement most likely to be quietly violated under
schedule pressure, which is why it is stated twice.

## 13. Backward compatibility summary

| Surface | Change | Compatibility |
|---|---|---|
| MCP tool surface | **none** — still exactly four | the lifecycle feasibility API is INTERNAL (§25) |
| `TaskEnvelope` / `envelope.json` | none | `SCHEMA_VERSION` stays `"1.0"` |
| `TaskRecord` / `state.json` | `+lifecycle_preflight`, `+runs_allocated` (both optional) | old files load; `run_count` keeps its meaning |
| `RunRecord` / `dispatcher-result.json` | `+timeout_evidence`, `RunMetadata.+lifecycle_phase` (optional) | old files load |
| `ValidationResult` | `+phase` defaulting to `"post_run"` | old files load |
| run directory | `+reservation.json`, `+ownership.json`, `+timeout.json`, `+events.jsonl` (conditional) | additive |
| `evidence/diff.patch` | now contains untracked content | strictly more complete; only Fable's prompt reads it, and it clips as before |
| `changed-paths.json` | new keys; `diff_patch_complete` now produced by the generator | additive; the key's *meaning* is unchanged, its *truthfulness* improves |
| `stdout.raw` / `stderr.log` / `events.jsonl` | written by the child directly, not by the pump | same paths; **no redaction claim is made about them at all** — they are declared private 0600 internal evidence, and every egress goes through one accessor (§7.4A). `docs/SECURITY.md` §1.5 is **rewritten** in Wave D. |
| `[lifecycle].enabled` | ships **`true`** at Wave A acceptance (D-14) | a dispatcher started with it `false` logs a startup warning naming Gate 7; Gate 7 cannot PASS with the canonical config bypassing it |
| worker deny list | `+ Bash(git config:*)`, `+ Bash(git update-index:*)`, `+ Bash(git -C:*)` | additive to `CORE_DENIED_GIT_OPERATIONS`; config may still only add, never remove |
| `check_scope` / `ScopeSpec` | operate on **`bytes`**, not `str` | patterns encoded once at envelope validation; no envelope change, no `SCHEMA_VERSION` bump |
| config | `+[lifecycle]` (default off), `+[evidence].max_untracked_file_bytes`, `+[execution].finalization_window_seconds`, `+[progress].heartbeat_seconds` | strict sections, fail closed on unknown keys as today |
| existing tasks on disk | reconciled, never reused, never rewritten | the three forensic tasks are read-only and stay so |
| `~/.codex/config.toml` | **no dispatcher change** — but any Wave E harness invoking `codex exec` mutates it as a side effect | D-12: snapshot / restore / verify-by-sha256 around every invocation; no `tests/**` invocation at all (§6.9.1, §10.3) |

---

## 14. What the SECOND independent review should attack

**Amendment 15: no implementation code may be written until this revision
receives a second independent review with ZERO blocking findings.** The first
review's six blocking findings are resolved above; what follows is what a second
reviewer should aim at, in the order a wrong answer does most damage.

### 14.1 New in revision 2 — the decisions that carry the most risk

**N-1 — the EXECUTION PHASE mechanism (§3.1).** The phase is advanced by
explicit `enter()` calls. That makes mis-wiring fail *safe* (a spurious `FAILED`)
rather than *unsafe* (a swallowed failure) — but it also means the phase is
carried by discipline at ~12 call sites. Is a `PhaseTracker` whose correctness
depends on those calls actually better than the class marker it replaces, or has
the failure mode simply moved? The design's claim is that the direction of
failure is what matters, not its probability. **Attack that claim.**

**N-2 — Wave 0's clean temporary index (§5.4A(d2)).** Collecting evidence
against `GIT_INDEX_FILE=<tmp>` + `read-tree <base>` is the only measured lever
that defeats `assume-unchanged` / `skip-worktree`. It also means the dispatcher's
diff no longer reflects the worktree's *own* index at all. Is there a case — a
legitimately staged change, a partial index state — where that produces a diff
that misrepresents what the worker did? The design believes not, because the
comparison is always worktree-vs-base and never index-vs-anything, but this is
the single most mechanically novel change in the plan.

**N-3 — folding ignore-suppressed paths into the inventory (§5.4A(d2), OQ-B6).**
`changed_paths` becomes "everything git sees, plus everything an ignore source
is hiding". Legitimately-ignored build output enters the inventory and can trip
scope. The design mitigates by recording the ignore *source* and marking only
rules that appeared during the run as tampering — but a task in a repo with a
large `.gitignore` may now surface hundreds of paths. **Is the mitigation
sufficient, or does this need a different shape entirely?**

**N-4 — `review_input_complete` makes large tasks unreviewable (§5.4C).**
Refusing the review when the patch exceeds the prompt budget is honest, and it
is what amendment 11 requires. It also means a genuinely large, legitimate
change cannot be Fable-reviewed at all, with remediation "split the task". Is
that acceptable, or is **OQ-B5** (deliver the patch by path, since Fable has
`Read`) the better trade despite making "the reviewer received the evidence"
unverifiable?

**N-5 — reconciliation-time termination (§7.6A).** The dispatcher now kills a
process group on startup. The identity guard is strong and `AMBIGUOUS` is never
signalled — but this is the first place the dispatcher takes a destructive
action against a process it did not start in this lifetime. **Is the
`hard_deadline_at`-is-the-caller's-contract argument sound**, or is any
cross-restart kill a judgement call the dispatcher should not make?

**N-6 — the git command repertoire as a load-bearing invariant (§5.4A(b)).**
Eleven exec vectors are safe *only because* the dispatcher never runs a signed,
paged, or log command. The design pins the repertoire with an AST test. Is a
test the right enforcement for something whose violation is a future
convenience, or does this want a louder mechanism?

### 14.2 Carried forward from revision 1, resolved but worth re-checking

| Was | Resolution | Where |
|---|---|---|
| OQ-D1 — stderr redaction at rest | trade taken; obligation made **structural** via a single accessor + AST test, not enumerated in prose | §7.4A |
| OQ-D2 — no supervisor | stands, **conditional on** §7.6A deadline enforcement, §7.5A's honest exit-status statement, and §7.7's resolved claim table | §7.4, §7.5A, §7.6A, §7.7 |
| OQ-A4/A5/A6 — refusal vs failure | marker base **deleted**; phase-carrying mechanism; `WorktreeBaseMismatch` **not** split | §3.1 |
| OQ-A2 — `VALIDATION_ONLY_RESUME` | **never selected in V1**; proven in preflight only | §4.3 D-3 |
| OQ-B1 — binary files | represented honestly, and **`untextual` separated from `capped`/`refused`** so ordinary tasks stay reviewable | §5.4 D-5 |
| OQ-D3 — orphan task state | leave `RUNNING` + `recovery` block | §7.6 |
| OQ-D4 — unnameable `STARTING` crash | pre-spawn **expectation** record (typed as expectation, no pid) | §7.9 |
| OQ-C1 — soft deadline | **kept**, as a measurement only; a test asserts it takes no action | §6.6 |
| OQ-B4 — `git.py` wrappers | keep only if they cannot produce a patch independently (M-5) | §5.4 |
| OQ-A3 — persisting the proof | direction right; "unproven" never read as "proven elsewhere" | §4.9 |
| OQ-E1 — Codex consent | a verified restore is **not** consent; Sol's consent recorded before Wave E runs | §12, §6.9.1 |
| OQ-V1 / OQ-V2 — sequencing | **Wave 0, first** | §12 |
| OQ-S1 — the 36 infeasible shapes | operational note; affected kinds named: `refactor` (12/12), `large_refactor` (12/12), `security_sensitive` (6/12), `migration` (6/12) | §15.2 |

### 14.3 Still open, and honestly so

- **OQ-B5** — deliver Fable's patch by path rather than inline (§5.4C).
- **OQ-B6** — scope-checking pre-existing ignored paths (§5.4A(d2)).
- **The compact artifacts do not exist yet.** The reviewer named this the
  largest unquantified risk in Wave A, and it stands: §9.2's targets (24,000 /
  12,000 / 6,000 B) are asserted achievable without losing approved methodology,
  and **nobody has written the artifacts to find out**. §9.2's rule — *if a
  target cannot be met without losing methodology, the target moves, not the
  methodology* — is the right rule, and **the schedule should assume the target
  moves.**

---

## 15. Amendment 15 — the gate on implementation

**No `src/**` or `tests/**` change may be written for Gate 7 until this document
receives a second independent architecture review returning ZERO blocking
findings.** The reviewer must not be the author, and must not implement the
fixes (§3 of the brief).

### 15.1 What the second review inherits

- Lane W's first review (`GATE7-DESIGN-REVIEW.md`) — R-1 … R-14, M-1 … M-10.
- Lane U's capability probe (`GATE7-CAPABILITY-PROBE.md`) — U-1 … U-5, measured.
- Lane X's adjacent-mechanism probe (`GATE7-V1-ADJACENT-PROBE.md`) — the V-1
  authority surface, V-4, V-5, and the `-z` matrix, measured.
- This revision, which applies Sol's fifteen amendments.

### 15.2 Minor items carried, from the first review

- **M-1.** `config/dispatcher.toml:170` and `config/dispatcher.example.toml:209`
  say "95,333-byte worst-case skill profile"; the true worst is **95,461**. The
  design doc is right; the config comments are 128 B stale. Fixed in Wave A.
- **M-2.** V-3 (`--no-index --check` exit 3) is latent — no `--no-index` call
  site exists today. Wave B item. It interacts with V-1: the `-diff` attribute
  also suppresses `--check` under `--no-index`.
- **M-3.** `git ls-files --others` does **not** list a FIFO but **does** list a
  symlink — the case that matters for R-4, and the one §5.3A is built around.
- **M-10 / OQ-S1.** Between now and Wave 0/A landing, 36 of 120 legal envelope
  shapes fail *late* — after burning a task id, three transitions and a real git
  worktree. No interim mitigation is built for a window Wave A closes, but the
  freeze notice names the affected kinds so nobody spends a worker discovering
  them: **`refactor` (12/12), `large_refactor` (12/12), `security_sensitive`
  (6/12), `migration` (6/12).**

### 15.3 Hard lines, restated

Production freeze absolute. No worker, real or fake, against
`/home/dev/full-voice-agent` (`06bfcd61`, 11 dirty). The `Rakesh` worktree and
the three forensic tasks are evidence and are not touched. `~/.claude` and
`~/.codex` are not modified — and per §6.9.1, *measuring* Codex mutates
`~/.codex/config.toml`, so Wave E's harness needs snapshot/restore/verify **and**
recorded consent. `scripts/gate/**` and the probe documents belong to Lanes U
and X. **This document is design only; it contains no implementation.**

## Appendix A — Measured data and its provenance

All measurements taken at `e6321d191afc4bd869732e92ff0ac4945f41fead`,
read-only, in disposable temporary directories. No production repository, no
`~/.claude`, no `~/.codex`, no config change, no worker.

### A.1 Lifecycle profile matrix

Produced by driving `SkillProjectionEngine` (the shipped
`config/approved-skills.json`, manifest `2026-08-20.1`) over the full
`TaskKind × Complexity × RiskLevel × {DISPATCH, RESUME}` space with the
effective deny list (config + `ALWAYS_DISALLOWED_TOOLS`).

```
envelope shapes (kind × complexity × risk):        120
dispatch profiles over the 72,000 B cap:            36 / 120
resume profiles over the cap:                       50 / 120
G7-1 TRAP (dispatch fits, resume cannot be built):  14 / 120
shapes where some phase is infeasible:              50 / 120

implementation/medium/medium  dispatch 44,757  resume 50,842
implementation/high/high      dispatch 70,623  resume 76,708   <- the brief's example
refactor/low/low              dispatch 76,513  resume 82,598   <- already infeasible
security_sensitive/high/high  dispatch 89,376  resume 95,461   <- worst
FABLE_REVIEW (all shapes)     skills 0 B                       <- correct, unchanged
```

Per-artifact projected bytes are in §9.1.

### A.2 Git behaviour (git 2.43.0), disposable repository

**Synthetic new-file patches** — `git diff --no-index -- /dev/null <path>`, run
from the worktree with a repo-relative path, exit 1 when differences exist:

| Case | Result |
|---|---|
| 2-line text file | `diff --git a/X b/X` / `new file mode 100644` / `index 0000000..<blob>` / `--- /dev/null` / `+++ b/X` / `@@ -0,0 +1,2 @@` / content |
| empty file | header only — no `---`, `+++` or `@@`. Git's own canonical form. |
| no final newline | `\ No newline at end of file` present |
| filename with a space | `+++ b/with space.txt` followed by a **trailing tab** |
| nested path | `b/sub/nested.txt` — repo-relative, correct |
| symlink | rendered as `new file mode 120000` with the **link target as content** — git does not refuse it, so the dispatcher must |
| binary | `Binary files /dev/null and b/bin.dat differ` (content omitted); `--binary` produces a `GIT binary patch` base85 block |
| UTF-8 filename, default | `"b/caf\303\251.txt"` (C-quoted) |
| UTF-8 filename, `-c core.quotePath=false` | `b/café.txt` |
| `--no-index --check` on a clean file | exit **1** |
| `--no-index --check` on trailing whitespace | finding printed, exit **3** |
| `--no-index --check` on conflict markers | three findings, exit **3** |

`git ls-files --others --exclude-standard` did **not** list a FIFO. It **did**
list a symlink. Default output C-quotes non-ASCII and special names;
`ls-files -z` emits real bytes NUL-delimited.

**Finding V-1 — attribute-driven evidence corruption:**

| Setup | `git diff <base>` | With `--no-textconv` | With `--text` |
|---|---|---|---|
| `.gitattributes: X diff=lie` + `diff.lie.textconv=/bin/echo LIE` | `+LIE tracked.txt` (content replaced) | real content restored | not sufficient alone |
| `.gitattributes: X -diff` | `Binary files a/X and b/X differ` (content omitted); `--stat` → `Bin 2 -> 10 bytes`; `--numstat` → `-\t-`; **`--check` exit 0 on a file with trailing whitespace** | no help | content restored, **but `--check` still exit 0** |

Hence: the generator needs `--no-textconv` **and** `--text` **and**
`--no-ext-diff`, and the whitespace/conflict verdict must be computed by the
dispatcher, not by `git diff --check`.

### A.3 Installed MCP SDK progress surface

`mcp` 2.0.0, `MCPServer` API (not FastMCP). `mcp.server.context.Context`
exposes:

```python
async def report_progress(self, progress: float, total: float | None = None,
                          message: str | None = None) -> None:
    """Report progress for this request, if the peer supplied a progress token.
    A no-op when no token was supplied."""
```

Server-side progress is therefore expressible at the baseline commit with no
SDK change. Client behaviour (Codex) is Lane U's measurement.

### A.3A Lane X — adjacent mutable mechanisms (measured, live)

`GATE7-V1-ADJACENT-PROBE.md`. Every finding demonstrated live in `mktemp -d`
repositories reproducing the dispatcher's exact evidence surface — the five
commands `collect_diff_evidence()` runs, plus `check_scope`,
`primary_tree_status`, `compare_primary_tree` — and the severe ones re-run
through the **real `sol_claude_dispatcher.git` code**. Probe scripts committed
at `a378567` under `docs/gate7-probes/lane-x/`.

- **Tier 0 — dispatcher executes a worker-chosen program (13 mechanisms
  OBSERVED):** `core.fsmonitor` (6× per evidence run, and on the primary tree),
  `diff.*.textconv`, `diff.*.command`, `diff.external` (no `.gitattributes`
  needed), `filter.*.clean` / `.smudge` / `.process`, `core.attributesFile`
  +textconv (invisible), `include.path`, `core.hooksPath`,
  `.git/hooks/post-checkout`, `.git/hooks/reference-transaction`,
  worktree-scoped `config.worktree`. The last two fire on the dispatcher's own
  `git worktree add`.
- **11 further keys measured NOT exploitable** — `post-index-change` (only
  because `GIT_OPTIONAL_LOCKS=0`), `core.pager` (only because pipes, not a TTY),
  `core.editor`, `credential.helper`, `core.gitProxy`/`sshCommand`,
  `uploadpack.packObjectsHook`, `core.alternateRefsCommand`, `gpg.program`,
  alias-over-builtin, `merge.*.driver`/`trailer.*.command`, `pre-auto-gc` —
  **contingent on the dispatcher's narrow command repertoire**, which is
  therefore load-bearing.
- **Tier 1 — V-4:** `update-index --assume-unchanged` / `--skip-worktree` erases
  a modified *or deleted* tracked file from **every** surface including
  `changed_paths`; `changed_paths=[]`, `scope.valid=True` through real code
  (F3/F4); reaches the primary tree via `git -C <primary>` (F6).
- **Tier 2 — V-5:** self-hiding `.gitignore` → `changed_paths=[]`,
  `valid=True`, **`Write` tool alone** (A1b/F1); `info/exclude` also blinds the
  primary tree (A2/F2).
- **Tier 3 — V-2 confirmed through real code:** `"secrets/caf\303\251.txt"` vs
  `forbidden_paths=['secrets/**']` → `valid=True`, `forbidden=[]` (F3_v2clean).
  With `-z` decoding → `valid=False`, `forbidden=[café.txt, naïve.key,
  plain.txt]` (F2_v2).
- **`-z` matrix:** accepted and effective on `ls-files --others`,
  `diff --name-only`, `status --porcelain`, `diff --numstat`, `diff --raw`;
  **accepted and IGNORED** on `diff --stat`; **no effect** on `diff --check`.
  `status --porcelain -z` and `diff --raw -z` emit **two NUL fields per rename**,
  the second carrying the old path with no status prefix.
- **Working levers:** `-c core.fsmonitor=false` (E1); `--no-textconv
  --no-ext-diff` (E2); `--attr-source=<base>` for in-tree `.gitattributes` (E4,
  and it does **not** help for `$GIT_COMMON_DIR/info/attributes`); a fresh
  `GIT_INDEX_FILE` + `read-tree` for index bits (E5); the `--exclude-standard`
  delta for ignore suppression (E6). **No general flag exists for `filter.*`**
  (E3). `core.attributesFile=/dev/null` and `GIT_ATTR_NOSYSTEM` do **not**
  disable in-tree `.gitattributes`. Dispatcher `-c` on argv **beats** worker repo
  config (D11).

### A.4 Codex trust write-back (Lane U, live)

`codex exec` auto-writes a project trust entry into `~/.codex/config.toml` for
the directory it runs in. `--ignore-user-config` prevents the user config from
being **loaded**; it does **not** prevent the trust **write-back**. Lane U hit
this during the U-3/U-4/U-5 probes and restored the file, verified byte-identical
by sha256 (`e41ef3bd…d498e`). Design consequence: §6.9.1 / D-12, §10.3, §12.

### A.5 Mutation-suite volatility

`find /tmp -iname '*mutant*'` returns nothing. The 38 mutants Lane R replayed
are no longer on disk. §11 exists because of this.

---

## Appendix B — Requirement traceability

| Brief § | Where it is answered |
|---|---|
| §1 G7-1 | §1 Shape 1, §4 |
| §1 G7-2 | §5.1, §5.3A, §5.4, §5.4A, §5.4B |
| §1 G7-3 | §6.1, §6.4, §6.7 |
| §1 G7-4 | §6.8, §6.9 |
| §1 G7-5 | §4.4, §9 |
| §1 G7-6 | §3.1 (EXECUTION PHASE), §4.6 |
| §1 G7-7 | §5.2, §5.5 |
| §1 G7-8 | §7 |
| §2 must-not-regress | §3.4, §10.1, §13 |
| §3 architecture first | this document |
| §4 lifecycle profiles | §4.3 |
| §5 hash-pinned compact projections | §4.4 |
| §6 lifecycle preflight | §4.5 |
| §7 preflight must not mutate | §3.1, §4.6 — phase-keyed, not class-keyed |
| §8 complete untracked evidence | §5.3A, §5.4, §5.4A (authority), §5.4B (identity) |
| §9 untracked patch requirements | §5.4, A.2 |
| §10 one canonical patch | §5.4, §5.10 |
| §11 diff check for untracked | §5.4 (dispatcher-side checker; `git diff --check` is corroborating only) |
| §12 run reservation | §5.5 |
| §13 run directory atomicity | §5.5, §5.9 |
| §14 timeout output / CLI capability | §6.0, §6.5 — **MEASURED SUPPORTED**, no longer conditional |
| §15 soft deadline | §6.0, §6.6 — **MEASURED NOT AVAILABLE**; kept as a measurement only |
| §16 factual remediation | §6.4 |
| §17 trusted validation after timeout | §6.7 |
| §18 event-driven progress | §6.8 |
| §19 progress content | §6.8 |
| §20 durable run ownership | §7.5 |
| §21 restart recovery policy | §7.6 |
| §22 preferred durable shape | §7.4 D-10 (declined) **conditional on** §7.6A deadline enforcement; §7.5A states exit status is unrecoverable |
| §23 explicit orphan state | §7.6, §7.7 (authoritative claim-retention table) |
| §24 repository lock after restart | §7.7 |
| §25 full lifecycle preflight matrix | §4.5 (INTERNAL — no fifth tool) |
| §26 size targets | §9, §9.2A (cap-parameterised matrix) |
| §27 Fable evidence completeness | §5.4C — two flags, clipped prompt refuses |
| §28 failure ordering | §8 — **reordered**: scope outranks content refusal |
| §29 test doubles | §10, §10.2A (where revision 1 broke its own rules) |
| §30 required adversarial cases | §5.10, §6.12, §7.9, §10.1 |
| §31 mutation suite in source control | §11, §11.2 (production-active config, named killers, A-d deleted), §11.3 (runtime) |
| §32 implementation waves | §12 — **0 → A → B → D → C → E** |
| §33 server.py conflict control | §12 |
| §34 production freeze | header, §10.1 |
| §35 final gate report rows | §9.3, §6.9 |

---

## Appendix C — Revision 2 change log

| Section | Change | Driver |
|---|---|---|
| header | amendment record; Codex **0.149.0**; second-review gate | amendments 13, 15 |
| §3.1 | `PrelaunchRefusal` marker **deleted**; `ExecutionPhase` + `PhaseTracker`; **RUNNING only after the child exists**; `refusals.jsonl` | amendment 5 / R-3 |
| §3.2 | phase model gains LAUNCH and `LAND_INCOMPLETE` | amendments 5, 7 |
| §3.4 | three §2 items recorded as already-broken or weakened | R-2, R-4, R-1 |
| §4.3 | `VALIDATION_ONLY_RESUME` **never selected in V1** | R-12 |
| §4.12 | **D-14**: lifecycle active in production is a Wave A acceptance criterion | amendment 6 / R-6 |
| §5.3A | inventory → policy → content, **scope outranks content refusal** | amendment 4 / R-4 |
| §5.4 | `patch_file_complete` + `review_input_complete`; `untextual` separated from `capped`/`refused` | amendments 4, 11 / R-8, R-13 |
| §5.4A | V-1 as an authority boundary; **four layers**; V-4 and V-5 named; Lane X's measured set | amendment 2 / R-1 + Lane X |
| §5.4B | `-z` inventory, rename-aware, sole authoritative path list; newline claim **retracted** | amendment 3 / R-2 + Lane X |
| §5.4C | clipped prompt is a refusal | amendment 11 / R-8 |
| §5.5A | `LandingIntent`, idempotent replay | amendment 7 / R-10 |
| §5.9 | crash points 9, 11, 12, 13, 14 added | amendment 7 / R-10 |
| §6.0 | Lane U's findings verbatim | amendment 14 |
| §6.4 | `stdout_bytes` definition fixed before either wave | R-11 |
| §6.5 | stream-json **adopted**; fallback retired | Lane U U-1 |
| §6.6 | soft deadline **not available**; kept as a measurement | Lane U U-2, M-4 |
| §7.4A | **no redaction claim**; one accessor; AST test | amendment 9 / R-7 |
| §7.5A | exit status **not recoverable**; trailing `result` event is the honest substitute | R-5(i) |
| §7.6A | reconciliation-time deadline enforcement | amendment 10 / OQ-D2 |
| §7.7 | authoritative claim-retention table; bare-directory case defined | R-5(iii), R-5(iv) |
| §7.9 | pre-spawn **expectation** record; `RunOwnershipUnavailable` contract | M-8, R-10 |
| §8 | ladder reordered | amendment 4 / R-4 |
| §9.2A | matrix parameterised by the **cap**; `NOT-MEASURED` on hash drift | R-9 |
| §10.2A | the three revision-1 proofs that could not fail | R-3, R-7, R-9 |
| §11.2 | production-active config; named killers; **A-d deleted** with proof | amendment 12 / R-9, R-14 |
| §11.3 | `--fast` / `--full` runner modes | R-14 |
| §12 | **Wave 0**; **D before C** | amendments 1, 8 / R-11 |
| §14, §15 | second-review targets; amendment 15 gate | amendment 15 |
