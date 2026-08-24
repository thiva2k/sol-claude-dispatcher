# GATE 7 — ARCHITECTURE

**Lifecycle, evidence and recovery integrity.**
Status: **DESIGN — NOT IMPLEMENTED.** Written to satisfy `GATE7-BRIEF.md` §3, which
requires this document to exist and to be independently reviewed *before* any
implementation begins.

| | |
|---|---|
| Baseline | `e6321d191afc4bd869732e92ff0ac4945f41fead` (HEAD == `origin/main`) |
| Baseline suite | 1368 tests passing |
| Author lane | Lane V (design only — this lane writes no `src/**` and no `tests/**`) |
| Companion | `GATE7-CAPABILITY-PROBE.md` (Lane U, capability probes — **not yet published at the time of writing**) |
| Governing brief | `/home/dev/.claude/auto-mode/commissioning/GATE7-BRIEF.md` |

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
left open. Everything marked **CONDITIONAL** depends on a Lane U probe result
and carries its own stated fallback. Everything marked **OQ-n** is an open
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

### 3.1 REFUSAL is not FAILURE (§7)

Today, `Dispatcher._dispatch` and `Dispatcher._resume` both wrap their body in
`except DispatcherError as exc: self._record_failure(task_id, exc)`, and
`_record_failure` transitions `CREATED/ROUTED/RUNNING/RESUME_REQUESTED → FAILED`
(`server.py:2694`). Any typed refusal raised after the task exists therefore
becomes a task failure. That is exactly the G7-6 poisoning.

**DECISION D-1: two independent mechanisms, both required.**

1. **Structural.** Every refusal-capable preparation step is moved *outside*
   the `try` that calls `_record_failure`. The PREPARE phase runs before the
   task record is loaded-for-mutation and before the first `transition()`. This
   is the primary guarantee: a refusal cannot be recorded as a failure because
   there is no recording code on that path.
2. **Typed, as defence in depth.** A new marker base:

   ```python
   class PrelaunchRefusal(DispatcherError):
       """A refusal taken in PREPARE. By contract it has mutated nothing.

       Never a run outcome. `_record_failure` refuses to transition on one, and
       a test asserts that every subclass is raised only from a PREPARE-phase
       call site.
       """
       lifecycle_mutation = "none"
   ```

   `_record_failure` gains, as its first statement, `if isinstance(exc,
   PrelaunchRefusal): return`.

The second mechanism is deliberately *not* sufficient on its own, and the
reviewer should attack it (**OQ-A4**): a typed marker is a way to launder a
genuine mid-run failure into "nothing happened" if it is ever applied to an
exception raised after mutation began. The mitigation is that the marker
carries an assertion, not a promise: a test walks the AST of `server.py` and
fails if any `PrelaunchRefusal` subclass is raised from inside the mutation
block.

Which existing errors become `PrelaunchRefusal` subclasses:

| Error | Today | Under Gate 7 |
|---|---|---|
| `ValidationBudgetExceeded` | already pre-lock, pre-state | `PrelaunchRefusal` (formalises what it already is) |
| `ContextTooLarge` | raised in `build_argv`, **after** `RUNNING` on the resume path | `PrelaunchRefusal`, moved into PREPARE |
| `ApprovedSkillChanged` | raised by `verify_dispatch_anchor` **after** `RUNNING` | `PrelaunchRefusal`, moved into PREPARE |
| `ProjectGuidance*Changed / *Drift / NotApproved / ScopeError` | same | `PrelaunchRefusal`, moved into PREPARE |
| `SkillPolicyViolation` | same | `PrelaunchRefusal`, moved into PREPARE |
| `LifecycleInfeasible` (new) | — | `PrelaunchRefusal` |
| `LifecycleProjectionStale` (new) | — | `PrelaunchRefusal` |
| `WorktreeBaseMismatch` **on the resume path only** | already pre-transition (`server.py:1190`) | stays as it is — it is already correct, and it is *not* reclassified, because the same error on the post-run path (`server.py:2006`) is a genuine run failure |
| `RepositoryBusy` | pre-state | unchanged (already retryable, already refusal-shaped) |
| `RepositoryRecoveryRequired` (new, §7.7) | — | `PrelaunchRefusal`, non-retryable |

Note the deliberate asymmetry on `WorktreeBaseMismatch`. The *same exception
class* is a refusal in PREPARE and a failure in FINALIZE. That is correct and
must stay correct: it is the phase, not the class, that decides. This is why
mechanism 1 is primary. (**OQ-A5**: is a single class carrying two meanings a
liability, or is splitting it into two classes worse because it invites a
future edit to catch only one?)

**Byte-identical refusal.** §7 requires that a refused resume leaves task
state, `run_count` and `resume_count` unchanged. The test for that is not "the
values are equal"; it is that `state/tasks/<id>/state.json` is **byte-identical
before and after**, `sha256` compared, including `updated_at` and
`state_history`. `TaskStore.save()` rewrites `updated_at` unconditionally, so
any code path that so much as calls `save()` on a refusal is caught.

### 3.2 The phase model

```
PREPARE ─────────────► RESERVE ─────► EXECUTE ─────► FINALIZE ─────► LAND
mutates nothing        allocates      runs the       collects        transitions
                       run identity   process        evidence        task state
 refusals here          ▲              ▲              ▲
 leave the task         │              │              │
 byte-identical         │              │              └─ FINALIZATION_FAILED
                        │              └─ ORPHANED / TIMED_OUT
                        └─ ABORTED_PRELAUNCH (index consumed, never reused)
```

`ABORTED_PRELAUNCH` exists because §7's "no run id consumed **if possible**"
has one honest exception: a refusal that happens *after* the reservation and
*before* the process starts. That window is small by construction (see §5.2)
but it is real, and the design does not pretend otherwise — the index is burnt
and the run directory records why.

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
| `VALIDATION_ONLY_RESUME` | `resume_claude_task` when the record says implementation is settled | `RESUME` | verification and fixup only |
| `FABLE_REVIEW` | `review_task_with_fable` | `REVIEW` | independent review context. **Zero implementation methodology** (unchanged from Gate 4.5 §15). |

**DECISION D-3: how `VALIDATION_ONLY_RESUME` is selected without inference.**
The dispatcher must not read Sol's instruction prose to guess intent — that is
the judgement call `CLAUDE.md` §1 forbids. The selector is therefore a
predicate over *dispatcher observations already on disk*:

```
VALIDATION_ONLY_RESUME  iff  task.state ∈ {AWAITING_SOL_REVIEW, FABLE_REVIEWED}
                        and  latest implementer run has worker_claims.status == completed
                        and  latest implementer run has dispatcher_observations.scope_valid
                        and  latest implementer run has primary_tree_unchanged is True
                        and  every ValidationResult on that run has passed == True
otherwise               CORRECTION_RESUME
```

Every clause is a dispatcher measurement, not a claim, except
`worker_claims.status` — which is a claim, and is used only to *reduce* context.
Because of A-I3 the failure mode of picking wrongly is bounded: choosing
`CORRECTION_RESUME` when validation-only would do costs bytes; choosing
`VALIDATION_ONLY_RESUME` requires the record to say, in the dispatcher's own
measurements, that scope held, the primary tree held, and every trusted
validation passed. **OQ-A2**: is even this too clever? The conservative
alternative is to ship only three profiles in V1 and treat
`VALIDATION_ONLY_RESUME` as a preflight-only phase — proven feasible, never
selected — which satisfies §6's matrix without ever acting on the predicate.

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
             │   refusal ──► nothing exists. No task id. Typed PrelaunchRefusal.
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
             │   refusal ──► state.json BYTE-IDENTICAL. Typed PrelaunchRefusal.
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
| `LifecycleInfeasible` | `PrelaunchRefusal` | PREPARE | no | Some automatically reachable phase cannot be composed or transported. Details name the phase, its composed bytes, the ceiling, the artifact ids, and every phase's number so Sol can see the shape. |
| `LifecycleProjectionStale` | `PrelaunchRefusal` | PREPARE | no | A compact artifact's `projection_sha256` or one of its `derived_from[].source_sha256` no longer matches. Never recalculated and accepted. |
| `LifecycleProfileUnknown` | `ConfigurationError` | load | no | Manifest names a phase or artifact that does not exist, or `profiles` is not exhaustive over `LifecyclePhase`. Fails at config load, like `SelectionMap._exhaustive`. |
| `ContextTooLarge` | `PrelaunchRefusal` | PREPARE | no | Existing class, reclassified. Kernel-`E2BIG` variant stays a run-time error (it is raised at spawn and is not a refusal). |
| `ApprovedSkillChanged` | `PrelaunchRefusal` | PREPARE | no | Existing class, reclassified. |
| `ProjectGuidance*` | `PrelaunchRefusal` | PREPARE | no | Existing classes, reclassified. |
| `SkillPolicyViolation` | `PrelaunchRefusal` | PREPARE | no | Existing class, reclassified. It is a `PolicyViolation` subclass today; the MRO becomes `SkillPolicyViolation(PolicyViolation, PrelaunchRefusal)` — **OQ-A6**: is multiple inheritance here worth it, or should `PrelaunchRefusal` be a protocol/flag attribute rather than a base class? |

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

- an **AST test** over `server.py` asserting no `PrelaunchRefusal` subclass is
  raised from inside the block guarded by `_record_failure`, and that
  `_record_failure`'s first statement is the `PrelaunchRefusal` early return.

### 4.11 Mutation cases

| # | Mutant | Killer |
|---|---|---|
| 1 | resume profile adds full planning again | correction-resume artifact-id assertion; the 120×2 matrix |
| 2 | resume profile adds the overlapping review skill again | no-redundant-pair assertion; the matrix |
| 3 | skip lifecycle future-phase preflight (evaluate only the current phase) | oversized-future-resume refuses initial dispatch |
| 4 | move preflight after the `RUNNING` transition | byte-identical `state.json` test |
| A-a | accept a drifted source hash and recompute | source-hash-drift test |
| A-b | let `_record_failure` transition on a `PrelaunchRefusal` | byte-identical test + AST test |
| A-c | raise a `PrelaunchRefusal` from inside the mutation block | AST test |
| A-d | measure per-component byte sums instead of the composed payload | matrix test with a shape whose components each fit and whose composition does not |
| A-e | make profile selection read the resume instruction text | determinism test (cleared env, moved CWD) |
| A-f | drop `unreachable_phases` and prove resume phases for a `max_resume_count == 0` task | §25 exclusion test |

### 4.12 Backward compatibility

- `[lifecycle] enabled = false` by default. With it off, `WorkerContextComposer`
  behaves exactly as today (whole-skill projection through
  `SkillProjectionEngine`), and preflight still runs but proves the *current*
  profiles. That means Gate 7's feasibility check applies to the old profiles
  too — which is desirable, because 36/120 dispatch shapes are already
  infeasible and today they fail *late*, inside `project()`, with a
  `SkillPolicyViolation` after the task exists.
- Existing `state.json` files load unchanged (all new fields default `None`).
- Existing `envelope.json` files are untouched; `SCHEMA_VERSION` does **not**
  bump, because nothing in `TaskEnvelope` changes.
- `TaskRecord.context_fingerprint` and `RunMetadata.context_fingerprint` keep
  their recipes. Enabling `[lifecycle]` changes the *selection*, which is the
  same class of change as the manifest adding `receiving-code-review` on
  resume — legitimately different, deliberately not drift (`worker_context.py`
  `verify_dispatch_anchor` docstring). **OQ-A7**: a task dispatched with
  `[lifecycle]` off and resumed with it on would silently change the worker's
  methodology. Should that be a `PrelaunchRefusal` (symmetric with the existing
  "dispatched with skills, now disabled" refusal at `worker_context.py:752`)?
  This design says **yes** — the same fail-closed rule, in both directions.

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
the untracked check must widen it deliberately, not accidentally.

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
- **B-I2 (completeness is produced, not asserted).** `patch_complete` is
  computed by the generator as: *every path in `changed_paths` has a
  represented section in the canonical patch, no path was refused, no cap
  clipped it.* No caller may set it.
- **B-I3 (no silent omission).** Every changed path is in exactly one of
  `represented`, `content_omitted` (honest, with a reason) or `refused`
  (typed). `patch_complete` is `False` whenever the second or third is
  non-empty.
- **B-I4 (attribute-proof).** The generator's git invocations are immune to
  in-tree `.gitattributes` and to operator git config. Binariness is decided by
  the dispatcher, not by git attributes. The whitespace/conflict-marker verdict
  is computed by the dispatcher over the canonical patch, not delegated to
  `git diff --check`.
- **B-I5 (no index mutation).** The task worktree's index is never written.
  `git add -N` is not used. `git update-index` is not used. Untracked content is
  obtained with `git diff --no-index`, which reads two paths and touches
  nothing.
- **B-I6 (path fidelity).** Paths are enumerated NUL-delimited
  (`ls-files -z`) and rendered with `core.quotePath=false`, so a path in
  `changed_paths` is the real byte sequence and is what `check_scope` sees.
- **B-I7 (Fable refuses incomplete evidence).** `review_task_with_fable`
  refuses when the authoritative patch is not complete, rather than reviewing
  partial evidence unannounced (§27's stated preference).

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

### 5.4 Design — the canonical evidence generator

New module `evidence.py`. `git.py` keeps its primitives; `collect_diff_evidence`
and `write_full_diff` become thin wrappers, or are folded in (**OQ-B4**: keep
them as a compatibility surface, or delete and update the ~6 call sites?).

**Hardened invocation prefix**, used for every diff the generator runs:

```
git -c core.quotePath=false
    -c core.attributesFile=/dev/null
    --no-pager
    diff --no-ext-diff --no-textconv --text --no-color …
```

- `--no-textconv` defeats the textconv rewrite (verified).
- `--text` defeats the `-diff` content suppression (verified) and forces a
  textual diff for everything, which is safe **only because** the generator
  classifies binariness itself and never sends a binary file through this path.
- `--no-ext-diff` defeats `diff.external`.
- `core.attributesFile=/dev/null` removes the operator's global attributes;
  in-tree `.gitattributes` cannot be disabled by any flag in git 2.43, which is
  precisely why the three flags above and dispatcher-side checking are required
  rather than optional.

**Per-path classification.** For every path from
`git ls-files -z --others --exclude-standard` the generator does an **`lstat`
first**, before anything opens the file:

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

**DECISION D-5: binary untracked files are represented honestly, not refused.**
§9 permits either. This design chooses representation because a docs or asset
task adding a `.png` is legitimate and should not fail the run, and because the
§8 requirement ("no silent omission") is satisfied by honesty rather than by
refusal. A binary file is recorded as:

```
diff --git a/assets/logo.png b/assets/logo.png
new file mode 100644
Binary files /dev/null and b/assets/logo.png differ
[dispatcher] content omitted: binary file, 20841 bytes, sha256 3f9c…  (patch_complete=false)
```

and the path lands in `content_omitted`, which forces `patch_complete = False`,
which (B-I7) makes Fable refuse. The alternative — `EvidenceUnsupportedFile`, a
typed refusal that fails the run — is documented as **OQ-B1** for the reviewer,
because it is the stricter reading of §8's "unsupported binary representation"
bullet and a reviewer may prefer it.

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
class UntrackedEntry:
    path: str                 # real bytes, repo-relative
    status: Literal["represented", "content_omitted", "refused"]
    reason: str | None
    size_bytes: int
    sha256: str | None
    patch_bytes: int

@dataclass(frozen=True)
class CanonicalEvidence:
    base_commit: str
    changed_paths: tuple[str, ...]      # tracked ∪ untracked, real bytes
    tracked_paths: tuple[str, ...]
    untracked: tuple[UntrackedEntry, ...]
    patch_path: Path                    # evidence/diff.patch
    patch_bytes: int                    # size of the file on disk
    patch_complete: bool                # B-I2 — produced here, nowhere else
    omitted_paths: tuple[str, ...]
    refused_paths: tuple[str, ...]
    diff_stat: str                      # tracked stat + dispatcher-composed
                                        # untracked rows (git's own
                                        # "/dev/null => X" label is NOT pasted)
    insertions: int
    deletions: int
    files_changed: int
    check_passed: bool                  # dispatcher-computed, B-I4
    check_findings: tuple[CheckFinding, ...]
    porcelain_status: str
```

**The check (§11).** A dispatcher-side scanner runs over the canonical patch's
added lines (`+` prefixed, excluding the `+++` header) and reports trailing
whitespace, space-before-tab, and leftover conflict markers
(`<<<<<<< `, `======= `, `>>>>>>> ` at line start). `git diff --check` is still
run against the tracked half and its findings are unioned in, but it is
**corroborating, not authoritative** — because of Finding V-1 it can be silenced
by an in-tree attribute, and because of G7-2 it never saw the untracked half.
The final verdict is `check_passed = not check_findings`.

**One accounting.** `diff_patch_bytes`, `diff_total_bytes`, `diff_stat`,
`diff_check_passed` and the Fable prompt patch are all read off the single
`CanonicalEvidence` object. `DispatcherObservations.diff_bytes` keeps its
existing meaning (what was held in memory) but is now derived from the same
object. §10's rule — "do not calculate 'complete' using one source and review
another" — becomes structurally true rather than a convention.

**Fable (§27).** `_review` reads `changed-paths.json`'s `patch_complete`. If it
is `False`, the review is refused with a typed
`EvidenceIncompleteForReview` **before any reviewer process starts**, naming the
omitted and refused paths. No reviewer tokens are spent reviewing a patch that
is missing a file. (This is a `PrelaunchRefusal`: it mutates nothing.)

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

### 5.6 State transitions

No new `TaskState`. Run state is a **new, separate** state machine living in
`runs/NNN/reservation.json` and it deliberately does not interact with the task
state machine except through `_land_state`, which is unchanged.

```
RESERVED ──► STARTING ──► RUNNING ──► FINALIZING ──► COMPLETE
    │            │            │            │
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
  preflight/lifecycle-feasibility.json          (subsystem A)
  runs/NNN/
    reservation.json              NEW  {schema_version, task_id, run_index, run_id,
                                        kind, role, lifecycle_phase, state,
                                        reserved_at, state_history[], detail}
    ownership.json                NEW  (subsystem D)
    stdout.raw                    (existing; becomes the child's direct stdout — §6)
    stderr.log                    (existing; becomes the child's direct stderr — §6)
    stdout.json                   (existing retained excerpt)
    worker-result.json            (existing)
    validation.json               (existing)
    claim-verification.json       (existing)
    timeout.json                  NEW  (subsystem C)
    dispatcher-result.json        (existing — written last, still the COMPLETE marker)
  evidence/
    diff.patch                    (existing — now the CANONICAL patch)
    changed-paths.json            (existing + untracked[], omitted_paths[],
                                   refused_paths[], patch_complete produced by
                                   the generator)
    diff-check.json               NEW  (dispatcher findings, tracked + untracked)
    …unchanged: diff-stat.txt, status.txt, evidence-phases.json,
      primary-tree-*.{txt,json}, worktree-base.json
```

`reservation.json` is written with the existing `atomic_write_json` (temp file,
fsync, `os.replace`, 0600 inside 0700). Its `state_history` is append-only.

### 5.8 Error taxonomy

| Code | Class | Phase | Meaning |
|---|---|---|---|
| `EvidenceUnsupportedFile` | `GitEvidenceCollectionFailed` subclass | FINALIZE | An untracked path is a symlink, FIFO, socket, device, directory, escapes the worktree, is unreadable, changed during measurement, or exceeds the hard bound. Details name the path, the lstat mode and the reason. Run lands `FAILED`; **all evidence collected so far is preserved**. |
| `EvidenceIncompleteForReview` | `PrelaunchRefusal` | PREPARE (review) | `patch_complete == false`. No reviewer started. |
| `RunReservationFailed` | `InternalDispatcherError` subclass | RESERVE | `mkdir` failed for a reason other than `EEXIST` (permissions, ENOSPC), or the allocator exceeded a sane bound. |
| `RunFinalizationFailed` | `DispatcherError` | FINALIZE | `dispatcher-result.json` could not be written. Reservation → `FINALIZATION_FAILED`. Streams and evidence preserved. Index never reused. |
| `GitEvidenceCollectionFailed` | existing | FINALIZE | unchanged semantics |

§28 ordering interaction: `EvidenceUnsupportedFile` is an evidence failure and
therefore ranks **above** any Fable invocation and **below** the B2 base check
(which is already the first thing `_finalise_worker_run` does).

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
| 9 | after `diff.patch`, before `dispatcher-result.json` | run is `FINALIZATION_FAILED`, `run_count` unmoved, `runs_allocated` == N, **next resume gets N+1** |
| 10 | after `dispatcher-result.json`, before `run_count` save | `append_run` is already atomic per file; `run_count` recovers as `max(run_count, highest COMPLETE index)` on load |

Injection mechanism: a test-only fault hook keyed by point id, injected through
the store/generator seams (not through monkeypatching `os` globally), so the
same test can assert "process was killed here" with a real `os._exit` in a
subprocess for points 3, 4 and 9 (the ones where a genuine process death
matters) and an exception for the rest.

### 5.10 Tests (§29, §30)

Unit (`tests/unit/test_evidence.py`, `tests/unit/test_run_reservation.py`):

- canonical patch shape for each of: multi-line new file, empty file, no final
  newline, filename with a space, nested path, non-ASCII path, path with a tab;
- `patch_complete` false whenever `omitted_paths` or `refused_paths` non-empty —
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
  refusal, run `FAILED`, evidence preserved, `patch_complete` false;
- **Finding V-1 regression**: a worktree containing `.gitattributes` with
  `secret.txt diff=lie` plus a local `diff.lie.textconv` — the canonical patch
  must contain the real content; and `x.txt -diff` with trailing whitespace —
  `check_passed` must be `False`;
- **Finding V-2 regression**: `café.txt` and `tab\there.txt` appear in
  `changed_paths` as their real bytes and are matched/refused correctly by
  `check_scope`;
- untracked whitespace error makes `diff_check` fail;
- `patch_complete=false` → Fable refuses, zero reviewer processes started;
- crash injection at all ten points, each asserting index non-reuse.

### 5.11 Mutation cases

| Mutant | Killer must exist |
|---|---|
| set `patch_complete = True` unconditionally in the generator | the omitted/refused tests |
| drop the synthetic untracked sections but keep `changed_paths` | the 191-line test |
| skip the untracked half of the check | untracked-whitespace test |
| delegate the check verdict to `git diff --check` alone | Finding V-1 `-diff` test |
| drop `--no-textconv` | Finding V-1 textconv test |
| drop `--text` | Finding V-1 `-diff` content test |
| drop `core.quotePath=false` / use line-split instead of `-z` | Finding V-2 test |
| replace `reserve_run()` with `run_count + 1` | orphan-directory reuse test |
| `mkdir(exist_ok=True)` in the allocator | orphan-directory reuse test |
| increment `runs_allocated` only on successful finalisation | crash-point 9 test |
| delete the run directory on evidence failure | "never erase" test |
| let Fable review an incomplete patch | §27 test |

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
progress). Parts of this subsystem are **CONDITIONAL** on Lane U's
`GATE7-CAPABILITY-PROBE.md`, which did not exist when this was written. Every
conditional part carries a fallback that requires no capability at all.

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
  worker to wrap up is CONDITIONAL (§6.5).
- **hard deadline** — today's `spec.timeout_seconds`. Unchanged semantics.
- **grace** — `DEFAULT_GRACE_SECONDS = 5.0`. Unchanged.
- **evidence/validation window** — already accounted for in the aggregate run
  budget (`UNDECLARED_RUN_OVERHEAD_SECONDS = 1845`,
  `MAX_TOTAL_RUN_BUDGET_CEILING = 8955`). Introducing the soft deadline changes
  no budget arithmetic: it subdivides time the worker already had.

### 6.4 Timeout evidence (§16) — unconditional, no probe needed

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

### 6.5 Streaming events (§14) — CONDITIONAL on Lane U

The brief is emphatic that the runner already pumps incrementally, so "add
streaming pipe reads" is not the fix. The open question Lane U is answering is
whether the installed Claude CLI supports a print-mode output format that
yields machine-readable *incremental* events.

**If Lane U proves such a mode exists and is stable**, the design is:

- the raw event stream is written incrementally to `runs/NNN/events.jsonl`
  (0600), unparsed, complete;
- a bounded, redacted diagnostic projection is kept for the run record;
- the final structured result is extracted **only from an authoritative final
  event** (the CLI's own result envelope). Intermediate model text and tool
  events are never treated as the result;
- the B3 trusted-envelope distinction is preserved exactly: `envelope_facts`
  continues to read only whitelisted top-level scalars of the final envelope,
  behind the payload veto. A streaming mode must not become a new door through
  which model output reaches classification;
- progress phases gain "worker active; last tool activity `<ts>`" derived from
  event *types*, never from event *text*.

**Fallback if no such mode exists (or it is unstable).** Progress is derived
entirely from transport-level facts the dispatcher already owns:

| Progress event | Source, with no CLI capability at all |
|---|---|
| worker launched | the spawn returned |
| worker active; last output `<ts>` | `stat(runs/NNN/stdout.raw).st_size` growth |
| soft deadline approaching | the clock |
| worker exited; collecting evidence | `proc.wait()` returned |
| evidence A complete | the generator returned |
| validation k/n started/finished: exit `c` | `run_validations` |
| collecting final evidence | the generator |
| Fable review started | `_review` |

Every item in §19's list is covered by the fallback. **The event-stream mode is
therefore an enhancement, not a dependency**, and Wave C is not blocked on Lane
U for G7-3. This is deliberate: §14's honest-if-absent instruction is satisfied
by having a design that does not need it.

### 6.6 Soft-deadline signalling — CONDITIONAL, default OFF

§15 permits using a supported completion-request mechanism **only after live
proof**, and explicitly forbids signalling arbitrary input into a
non-interactive `-p` process.

**DECISION D-7: V1 ships with no soft-deadline signalling.** The child's stdin
is `asyncio.subprocess.DEVNULL` (`runner.py:1433`) and stays that way. The soft
deadline is a *dispatcher-side* concept: it fires a progress event and is
recorded in `timeout.json`. If Lane U produces live proof of a supported
mechanism, it is added behind a config flag in a later wave, with its own live
gate. Nothing in this design invents a finalization feature.

### 6.7 Post-timeout trusted validation (§17)

Preconditions, all measured, evaluated in this order:

1. B2 base invariant still holds — `_verify_worktree_base` already ran and
   returned (it is the choke point at `server.py:2006`, ahead of everything);
2. the worktree is still registered with the repository at the recorded path
   (`resolve_worktree`);
3. the primary-tree fingerprint was measurable (`snapshot_primary_tree`
   succeeded both before and after);
4. canonical evidence A was collected successfully;
5. no `EvidenceUnsupportedFile` / unsupported condition was raised;
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

**Zero model turns.** Structurally, the dispatcher never returns progress as
tool *content*; it is an out-of-band notification on a pending request.
Whether the installed Codex client turns a `notifications/progress` into a model
inference turn is **Lane U's measurement**, and it is the one thing this design
cannot guarantee from the server side.

### 6.9 What must be confirmed before Wave C / Wave E starts

| # | Question for Lane U | If YES | If NO |
|---|---|---|---|
| U-1 | Does the installed Claude CLI have a print-mode output format producing incremental machine-readable events? | build the `events.jsonl` streaming parser (§6.5); extract the result only from the authoritative final event | fallback in §6.5 — progress from spool growth. **Wave C proceeds either way.** |
| U-2 | Is there a supported mechanism to request completion before hard kill? | add behind a flag, in a later wave, with its own live gate | D-7 stands: no signalling, soft deadline is dispatcher-side only |
| U-3 | Does Codex 0.147.0/0.149.0 send a `progressToken` on a dispatcher tool call? | proceed | server-side implementation still correct and tested; `report_progress` no-ops; G7-4 = **CLIENT-LIMITATION** |
| U-4 | Does Codex deliver `notifications/progress` to its TUI/event stream? | proceed | as above |
| U-5 | Does receiving progress cause a **model inference turn**? | **disable progress** — C-I5 forbids it | proceed |

§35 permits G7-4 = CLIENT-LIMITATION without blocking the gate, provided
zero-poll behaviour holds, progress never triggers model turns, the server side
is correct and tested, and the limitation is documented honestly. This design is
built so that outcome is reachable without any dishonesty: the server side is
protocol-correct and fully tested against a real MCP stdio client that *does*
send a token, and the limitation, if any, is the client's.

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

**DECISION D-10: no supervisor process in V1.** §22 asks for the supervisor
shape to be *evaluated*. Evaluated: with file-backed streams, the only thing a
supervisor would add is **reaping and termination enforcement** — someone to
SIGKILL the child at the hard deadline when the dispatcher is gone. That is
real, and it is exactly the residual §7.6 declares as `ORPHANED`. A supervisor
would convert a subset of `ORPHANED` outcomes into automatic terminations, at
the cost of a whole new process lifecycle, its own crash-recovery story, and a
second thing that can hold the repository lock. Given §23's explicit blessing of
a degraded state, V1 takes the simpler shape and records the supervisor as the
named upgrade path. **OQ-D2** puts this to the reviewer directly.

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

### 7.6 Restart reconciliation (§21, §23)

On `Dispatcher.__init__` — before any tool can run, and therefore before any
lock can be acquired — every persisted non-terminal run is reconciled:

```
for each task, for each runs/NNN with reservation.state ∉ terminal:
    if no ownership.json:
        state ∈ {RESERVED} -> ABORTED_PRELAUNCH      (nothing was started)
        state ∈ {STARTING} -> ORPHANED               (a process MAY exist, unnameable)
    else:
        verdict = probe(ownership.process)
        ALIVE_SAME       -> ORPHANED + durable repository claim (see below)
        GONE             -> FINALIZING if streams+exit are recoverable, else ORPHANED
        AMBIGUOUS        -> ORPHANED + durable repository claim
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
  killed it*, and this run was not killed by anyone;
- do **not** reuse the worktree or the run index;
- **preserve** every stream and every evidence artefact already on disk;
- surface explicit recovery information to Sol through `get_task` — a new
  `recovery` block naming the run index, the recorded process identity, the
  probe verdict, the preserved paths, and the operator remediation;
- the dispatcher **never** silently resumes or starts another worker.

**Task state for an orphaned run.** The task is left in `RUNNING` and is
**not** transitioned by reconciliation. Reconciliation is a read-mostly startup
step; inventing a task transition from it would be the dispatcher deciding what
happened, which is Sol's call. `get_task` reports `state: running` alongside the
`recovery` block, so the situation is unambiguous rather than laundered into a
terminal state. **OQ-D3**: is leaving the task in `RUNNING` right, or should
`RUNNING → BLOCKED` (already a legal transition) be used so the task appears on
Sol's actionable list? The argument for `RUNNING` is honesty; the argument for
`BLOCKED` is that a task nobody will ever advance should not look active.

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
| `GONE` but the run is non-terminal | claim removed, run reconciled to `ORPHANED`; acquisition proceeds (nothing is alive) |
| `ALIVE_SAME` | **refuse** with `RepositoryBusy` (retryable — the worker is genuinely running) |
| `AMBIGUOUS` | **refuse** with `RepositoryRecoveryRequired` (**not** retryable — a human or Sol must resolve it) |

A claim is written at `RUNNING` and removed at `COMPLETE` /
`FINALIZATION_FAILED` / `ABORTED_PRELAUNCH`. It is **not** removed for
`ORPHANED` — that is the whole point; an orphaned run keeps the repository
closed until it is resolved.

This is what makes "no duplicate worker after server restart" true rather than
hoped for.

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

Persistent: `runs/NNN/ownership.json`, `state/locks/<digest>.claims/*.json`.

| Code | Class | Retryable | Meaning |
|---|---|---|---|
| `RepositoryRecoveryRequired` | `PrelaunchRefusal` | **no** | A prior run against this repository is unresolved (`ORPHANED`, or an `AMBIGUOUS` identity). Details name the task, run index, run directory and probe verdict, plus operator remediation. |
| `RunOwnershipUnavailable` | `InternalDispatcherError` | no | `/proc` could not be read to *write* the ownership record. Fail closed: the run is terminated and lands `ABORTED_PRELAUNCH`, rather than running unowned. |

### 7.9 Crash points

| Crash after | Reconciliation verdict |
|---|---|
| spawn, before `ownership.json` | reservation is `STARTING` → **ORPHANED** (a process may exist that we cannot name). Repository claim written pessimistically from the reservation. |
| `ownership.json`, worker alive | probe → `ALIVE_SAME` → **ORPHANED** + claim → repository refuses new work |
| `ownership.json`, worker already exited | probe → `GONE` → **FINALIZING** if `stdout.raw` and an exit marker exist, else **ORPHANED** |
| machine reboot mid-run | `boot_id` differs → **GONE** → run reconciled without probing a reused pid |
| pid reused by an unrelated process | starttime differs → **GONE**. Test: simulate by writing an ownership record with a real live pid and a deliberately wrong `starttime_ticks`. |

Note the pessimistic claim in row 1: we cannot name the process, so we cannot
prove it is gone, so the repository stays closed. That is the correct
fail-closed direction and it is also the most annoying one operationally —
**OQ-D4**: is an unnameable `STARTING` crash worth closing the repository, or
should the window be narrowed instead by writing a *pre-spawn* record containing
the expected binary and the reservation, so that at worst we can scan for a
matching process?

### 7.10 Tests

- unit: `probe()` truth table, including a synthetic `/proc` fixture directory
  so every branch is reachable without spawning;
- unit: claim lifecycle (written at `RUNNING`, removed at each terminal state,
  retained at `ORPHANED`);
- **real-process integration** (§29 demands actual subprocesses and process
  groups):
  - MCP waiter cancel → worker continues (the Gate 6 regression test, unchanged);
  - dispatcher process killed with `SIGKILL` while a real child sleeps →
    a second dispatcher process starts, reconciles, refuses to launch, and
    reports the recovery block;
  - **pid-reuse simulation**: ownership record pointing at a live pid with a
    wrong starttime → verdict `GONE`, no attachment;
  - identity ambiguity (unreadable `/proc` entry, simulated) → fail closed;
  - a run whose child completed while the dispatcher was dead → streams and
    exit status recoverable from the file-backed spool after restart;
  - `SIGTERM` to the dispatcher → `drain()` lets the run land, no orphan.

### 7.11 Mutation cases

| Mutant | Killer |
|---|---|
| remove `ownership.json` write | restart-reconciliation test |
| treat pid existence as sufficient identity | pid-reuse simulation |
| treat `AMBIGUOUS` as `GONE` | ambiguity fail-closed test |
| launch a duplicate after restart | duplicate-prevention test |
| remove the repository claim on `ORPHANED` | §24 test |
| write `ownership.json` **before** the process exists | test asserting the recorded pid is the real child's |
| mark an orphaned run `TIMED_OUT` | §23 test ("do not call it a normal timeout") |
| go back to `stdout=PIPE` | restart-recovers-streams test |

### 7.12 Backward compatibility

Tasks with existing `runs/NNN` and no `ownership.json` reconcile as `COMPLETE`
(if `dispatcher-result.json` is present) or `ORPHANED` (if not) and are never
reused as indexes. No `TaskRecord` field is required. `RunRegistry`'s public
surface is unchanged apart from the optional `on_progress` argument. The
`stdout.raw`/`stderr.log` paths and semantics are unchanged from a reader's
point of view; only the writer changes.

---

## 8. Failure ordering (§28)

One precedence, tested end to end, applied in `_land_state` and in the
finalisation sequence around it:

```
 0. PREPARE refusals               -> no lifecycle mutation at all. Typed
                                      PrelaunchRefusal. Never FAILED.
                                      (includes ContextTooLarge, lifecycle
                                      infeasibility, hash drift, budget,
                                      RepositoryBusy, RepositoryRecoveryRequired)
 1. worktree base mismatch          -> FAILED, BEFORE any evidence is collected.
                                      No diff evidence is produced at all.
 2. unsupported untracked file      -> evidence failure -> FAILED. NO Fable.
                                      Everything already collected is preserved.
 3. scope violation / primary-tree  -> POLICY_VIOLATION. Outranks worker success.
    interference
 4. timeout                          -> TIMED_OUT. Stays TIMED_OUT even if
                                      post-timeout validation passes.
 5. provider limit / API error      -> FAILED (B3 classification, unchanged).
                                      Behind timeout, ahead of everything after.
 6. unusable worker report          -> FAILED (cli_unusable / unparseable)
 7. non-zero exit                   -> FAILED
 8. worker-reported blocked/failed  -> BLOCKED / FAILED
 9. otherwise                        -> IMPLEMENTED -> AWAITING_SOL_REVIEW
```

Orthogonal, not in the ladder:

- **run finalization failure** → the run is preserved with reservation state
  `FINALIZATION_FAILED`; the index is never reused; the task lands wherever the
  ladder put it, or stays where it was if the ladder never ran.
- **orphaned run** → no task transition; `get_task` carries a `recovery` block;
  the repository stays claimed.

Rows 1, 3, 4, 5 are today's behaviour and are asserted unchanged. Rows 0 and 2
are new. The ladder is pinned by an integration test per row **and** by a test
that constructs deliberately conflicting conditions (timeout + out-of-scope
change + a 429 envelope in partial stdout) and asserts `POLICY_VIOLATION`.

---

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

### 9.3 Reporting (§35)

The final gate report must carry, per phase, the before/after byte pair for at
least: `implementation`/medium/medium, `implementation`/high/high,
`security_sensitive`/high/high (the worst shape), and `refactor`/low/low (the
surprising one). The full 120×2 matrix is produced by a script under `scripts/`
and attached.

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
   - a fake evidence generator that returns `patch_complete=True`;
   - a git double that never emits quoted paths (V-2 becomes unreachable);
   - a git double with no `.gitattributes` support (V-1 becomes unreachable);
   - a run-directory double where `mkdir` is idempotent (G7-7 becomes
     unreachable);
   - a process-identity double that returns `ALIVE` for any live pid (the
     pid-reuse case becomes unreachable);
   - a `Context` double whose `report_progress` records without a token check
     (the "no token → no-op" property becomes unreachable).
6. **NOT-TESTABLE is a first-class result** and is never recorded as PASS. A
   429/zero-token run is never a pass and never suppression evidence.

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

Additional mutants this design requires beyond §31's minimum: A-hash-drift
accepted (A), `PrelaunchRefusal` raised from inside the mutation block (A),
`--no-textconv` dropped (B), `--text` dropped (B), `core.quotePath=false`
dropped (B), `mkdir(exist_ok=True)` (B), run directory deleted on evidence
failure (B), post-timeout validation converts `TIMED_OUT` to `IMPLEMENTED` (C),
`AMBIGUOUS` treated as `GONE` (D), repository claim removed on `ORPHANED` (D),
`stdout=PIPE` restored (D).

**Every mutant must be caught. No survivor is papered over as "equivalent"
without a written proof of equivalence in the runner's README.**

---

## 12. Wave sequencing and `server.py` conflict control (§32, §33)

```
WAVE A  lifecycle profiles + feasibility preflight   (G7-1, G7-5, G7-6)
        -> FULL SUITE + FULL MUTATION REPLAY
WAVE B  run reservation + complete evidence          (G7-2, G7-7)
        -> FULL SUITE + FULL MUTATION REPLAY
WAVE C  timeout evidence + post-timeout validation   (G7-3)
        -> FULL SUITE + FULL MUTATION REPLAY
WAVE D  durable ownership + restart recovery         (G7-8)
        -> FULL SUITE + FULL MUTATION REPLAY
WAVE E  MCP progress notifications                   (G7-4)
        -> only after Lane U's conformance probe
        -> its harness invokes `codex exec`, which auto-writes a trust entry
           into ~/.codex/config.toml. Snapshot / restore / verify-by-sha256
           around every invocation (D-12, §6.9.1). NOT run from pytest.
        -> FULL SUITE + FULL MUTATION REPLAY
FINAL   all waves together · full tests · mutation replay · doctor ·
        skills audit · guidance audit · activation checker · B4 check ·
        real MCP stdio · disposable live Claude
```

**Each wave starts from the previously accepted wave**, not from the baseline.
No wave is merged until its suite and the *cumulative* mutation suite are green.

**`server.py` is integrated SEQUENTIALLY.** Every wave touches
`Dispatcher._dispatch`, `_resume`, `_review` or `_finalise_worker_run`. Parallel
lanes are permitted only on disjoint ownership:

| Parallelisable | Serial (one lane at a time) |
|---|---|
| `lifecycle.py`, `evidence.py`, `runs.py`, `ownership.py` (new modules) | **`server.py` orchestration** |
| the compact artifact authoring + review | `waiting.py` (Wave E touches it) |
| `scripts/mutation/**` | `runner.py` (Waves C and D both touch `run_worker`) |
| tests for a new module | `models.py` / `state.py` schema additions |
| capability probes (Lane U) | |

Concretely: the wave that owns `server.py` for its slot holds it exclusively;
other lanes deliver modules and tests that the `server.py` owner then wires in.
**No blind merge of two branches that both edited `server.py`.**

**Rebase discipline.** Wave N+1 branches from Wave N's accepted commit. If Wave
N's review requires changes, Wave N+1 rebases rather than merging, so the
`server.py` history stays linear and each wave's diff is reviewable in
isolation.

---

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
| `stdout.raw` / `stderr.log` | written by the child directly, not by the pump | same paths, same content; **stderr is no longer redacted at rest** — see OQ-D1 and a required `docs/SECURITY.md` update |
| config | `+[lifecycle]` (default off), `+[evidence].max_untracked_file_bytes`, `+[execution].finalization_window_seconds`, `+[progress].heartbeat_seconds` | strict sections, fail closed on unknown keys as today |
| existing tasks on disk | reconciled, never reused, never rewritten | the three forensic tasks are read-only and stay so |
| `~/.codex/config.toml` | **no dispatcher change** — but any Wave E harness invoking `codex exec` mutates it as a side effect | D-12: snapshot / restore / verify-by-sha256 around every invocation; no `tests/**` invocation at all (§6.9.1, §10.3) |

---

## 14. Open questions for the independent architecture reviewer

Ordered by how much damage a wrong answer does.

**OQ-D1 — stderr is no longer redacted at rest.** File-backed child streams
(D-9) move redaction from write time to read time. `stderr.log` would hold the
child's raw bytes at 0600 inside a 0700 tree, with redaction at every egress.
Is that an acceptable trade for solving pipe ownership by eliminating pipes, or
does it break a security property that must be preserved? If it must be
preserved, the alternatives are (a) a supervisor process that redacts as it
drains — which reintroduces the process this design deleted — or (b) a
post-exit redaction pass that rewrites the file, which loses the true artefact
and has its own crash window.

**OQ-D2 — no supervisor process.** D-10 evaluates §22's supervisor shape and
declines it, on the grounds that file-backed streams solve pipe ownership and
§23 blesses an explicit `ORPHANED` state. The residual the supervisor would
close is *termination enforcement when the dispatcher is dead*: an orphaned
worker keeps mutating the worktree past its hard deadline with nobody to kill
it. Is that residual acceptable, given the repository is held closed by a
durable claim?

**OQ-A4/A5/A6 — the `PrelaunchRefusal` marker.** A typed marker that makes
`_record_failure` skip is a mechanism for laundering a real failure into
"nothing happened" if it is ever applied to an exception raised after mutation
began. The design's answer is that structure is primary and the marker is
defence in depth, with an AST test pinning the call sites. Is that enough? And
is `WorktreeBaseMismatch` meaning *refusal* in PREPARE and *failure* in FINALIZE
a liability, or is splitting it worse?

**OQ-B1 — binary untracked files.** D-5 represents them honestly with content
omitted and `patch_complete=false` (so Fable refuses), rather than raising
`EvidenceUnsupportedFile` and failing the run. §8 lists "unsupported binary
representation" among the things to refuse; §9 permits either. Which reading
governs?

**OQ-A2 — `VALIDATION_ONLY_RESUME` selection.** D-3 selects it from a predicate
over dispatcher observations plus one worker claim. Is any automatic selection
here the dispatcher making a judgement call it should not make? The conservative
alternative — prove it in preflight, never select it in V1 — satisfies §6's
matrix and removes the question.

**OQ-D3 — task state for an orphaned run.** Leave the task in `RUNNING`
(honest, but it looks active forever) or transition to `BLOCKED` (legal, appears
on Sol's actionable list, but is the dispatcher deciding what happened)?

**OQ-D4 — the unnameable `STARTING` crash.** A crash between spawn and the
ownership write closes the repository pessimistically. Narrow the window with a
pre-spawn expectation record, or accept it?

**OQ-A3 — persisting the feasibility proof is itself a mutation.** It must
therefore land *with* the first mutation rather than before it, which means a
crash between the last refusal and the first write leaves a task with no
persisted proof. The design treats such a task as unproven and re-proves on the
next touch. Is that the right direction?

**OQ-B4 — `git.py` compatibility surface.** Keep `collect_diff_evidence` /
`write_full_diff` as thin wrappers over `evidence.py`, or delete them and update
every call site? Wrappers preserve `docs/INTERFACES.md`; deletion removes a
second way to get a patch, which is what B-I1 is about.

**OQ-C1 — the soft deadline with no signalling.** D-7 makes the soft deadline a
progress event and a recorded fact only. Is a deadline that does nothing worth
having, or should it be dropped until Lane U proves a mechanism exists?

**OQ-V1 — Finding V-1 scope.** The `.gitattributes`/textconv hole affects
**tracked** evidence too, which is arguably a B2-adjacent regression rather than
a G7-2 item. Should the canonical generator's hardening ship in Wave B as
designed, or be pulled forward as its own fix?

**OQ-V2 — Finding V-2 scope.** Quoted paths currently defeat `check_scope` for
non-ASCII new files. That is a live scope-enforcement hole at the baseline
commit, not a Gate 7 defect. Wave B fixes it as a side effect; should it be
fixed first, on its own?

**OQ-E1 — measuring Codex costs a mutation of the operator's config.** §6.9.1:
`codex exec` auto-writes a trust entry into `~/.codex/config.toml`, and
`--ignore-user-config` does not prevent it. D-12 answers with
snapshot/restore/verify-by-sha256 and a ban on `codex exec` inside `tests/**`.
Is a verified restore sufficient, or does Wave E need explicit operator consent
recorded in the gate report before it runs at all — given that the §35 row says
"`~/.codex` semantic changes: NONE **unless separately approved**"?

**OQ-S1 — the 36 already-infeasible dispatch shapes.** Between now and Wave A
landing, 36 of 120 legal envelope shapes cannot be dispatched at all (they fail
inside `project()` with `SkillPolicyViolation`, after the task record exists).
Is that an operational note, or does it want an interim mitigation?

---

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
| §1 G7-2 | §5.1, §5.4 |
| §1 G7-3 | §6.1, §6.4, §6.7 |
| §1 G7-4 | §6.8, §6.9 |
| §1 G7-5 | §4.4, §9 |
| §1 G7-6 | §3.1, §4.6 |
| §1 G7-7 | §5.2, §5.5 |
| §1 G7-8 | §7 |
| §2 must-not-regress | §3.4, §10.1, §13 |
| §3 architecture first | this document |
| §4 lifecycle profiles | §4.3 |
| §5 hash-pinned compact projections | §4.4 |
| §6 lifecycle preflight | §4.5 |
| §7 preflight must not mutate | §3.1, §4.6 |
| §8 complete untracked evidence | §5.4 |
| §9 untracked patch requirements | §5.4, A.2 |
| §10 one canonical patch | §5.4, §5.10 |
| §11 diff check for untracked | §5.4 (dispatcher-side checker) |
| §12 run reservation | §5.5 |
| §13 run directory atomicity | §5.5, §5.9 |
| §14 timeout output / CLI capability | §6.5 (CONDITIONAL, with fallback) |
| §15 soft deadline | §6.3, §6.6 (D-7: none in V1) |
| §16 factual remediation | §6.4 |
| §17 trusted validation after timeout | §6.7 |
| §18 event-driven progress | §6.8 |
| §19 progress content | §6.8 |
| §20 durable run ownership | §7.5 |
| §21 restart recovery policy | §7.6 |
| §22 preferred durable shape | §7.4, D-10 (evaluated, declined, with reasons) |
| §23 explicit orphan state | §7.6 |
| §24 repository lock after restart | §7.7 |
| §25 full lifecycle preflight matrix | §4.5 (INTERNAL — no fifth tool) |
| §26 size targets | §9 |
| §27 Fable evidence completeness | §5.4 (B-I7) |
| §28 failure ordering | §8 |
| §29 test doubles | §10 |
| §30 required adversarial cases | §5.10, §6.12, §7.9, §10.1 |
| §31 mutation suite in source control | §11 |
| §32 implementation waves | §12 |
| §33 server.py conflict control | §12 |
| §34 production freeze | header, §10.1 |
| §35 final gate report rows | §9.3, §6.9 |
