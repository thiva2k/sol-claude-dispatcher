# GATE 7 — ARCHITECTURE

**Lifecycle, evidence and recovery integrity.**

Status: **DESIGN — REVISION 4. NOT APPROVED FOR IMPLEMENTATION.**

Revision 1 (`d098d4b`) was independently reviewed (Lane W) → *APPROVED WITH
REQUIRED CHANGES*, six blocking findings. Revision 2 (`619b63e`) applied Sol's
fifteen amendments and was independently reviewed a second time → **S-1 … S-7,
N-a … N-e, Y-1 … Y-10**. Sol ruled on that review and issued **twenty directives,
A–T**. This revision integrates three parallel drafting lanes against those
directives.

Revision 3 (`d268f70`, pushed and verified as `origin/main`) received a **third**
independent review: **4 BLOCKING · 7 non-blocking · WAVE 0 APPROVED TO IMPLEMENT:
NO.** Six of the seven prior blockers were confirmed **closed by mechanism**, the
evidence-authority architecture was judged right, and `filter.*` was independently
reproduced as genuinely closed by class deletion. **Revision 4 fixes the four
blockers and the seven non-blocking findings.**

> **NO SOURCE CODE MAY BE WRITTEN until a FOURTH independent review returns ZERO
> blocking findings and WAVE 0 APPROVED TO IMPLEMENT: YES.** That is directive T,
> and it is not discretionary. The production freeze remains absolute until then.

### What revision 4 changes

| # | Blocker | Fix |
|---|---|---|
| **B-1** | *"post-worker the pipeline runs exactly ONE git command"* was **false in the design's own text** — B2's `assert_worktree_base` runs `rev-parse` post-worker on every run — and the journal test named as the last line of defence **would have failed on the happy path** | §0.2, §2, §5.4.5, §5.5.2, §16, §17: the post-worker set is **`{cat-file, rev-parse}`** with the `rev-parse` **argv pinned** and its **count tied to a seam counter**. **The claim and the test are corrected; the command is not.** Three tempting exits are named and refused. |
| **B-2** | Appendix A.2's *"`--no-checkout` executes nothing"* came from an experiment that **could not have produced a positive result** — it never armed `reference-transaction`. **A third execution surface exists.** | §5.4.1 gains **S-γ (ref update)**; the repertoire is re-measured on all three; A.2 carries a **methodological correction** stating what it could and could not have detected; `# executes NOTHING` is deleted; **Z-4 is demoted from "structural" to "gated" and held OPEN pending Lane Z5** |
| **B-3** | `patch_file_complete` was **`true` while content was omitted**, for the precise attack directive C names — a modification to `.venv/bin/activate` was detected, scope-exempted, rolled up, and shipped to Fable as complete | §5.5.9A: **ZI-25/26/27.** A base-ignored path whose change is anything but `added` is **represented in full, never rolled up, never budgeted, no configuration elides it**, and is **scope-checked normally**. Only bulk **creation** rolls up, and **the rollup clears the flag.** |
| **B-4** | **S-7 was not closed.** Three Wave-0 refusals land in §8 **row 0**, which revision 3 assigned to Wave A — so Wave 0 alone would have landed the task **`FAILED` on the first dispatch against every repository**, reintroducing G7-6 | §12.2 **D-24**: the PREPARE-phase mechanism and row 0 **move into Wave 0**, because Wave 0 owns the gate that needs them. §12.2's sentence is now true rather than load-bearing and false. |

Non-blocking: **N-1** repertoire completeness (three live commands were unlisted;
three `REQUIRES-PROBE` rows retired as clean) · **N-2** `read-tree`
prohibited-and-prescribed, resolved · **N-3** promisor vector closed as
non-exploitable, operator trust-print widened · **N-4** two documentation mutants
were **red on day one**, re-specified structurally · **N-5** ZI-18 was
**unachievable as written**, restated with a raw gitdir resolver · **N-6**
directive T **does exist and is satisfied** · **N-7** the two config-softened §2
items, carried for Sol.

| | |
|---|---|
| Baseline | `e6321d1` (1368 tests passing) |
| Revision 1 | `d098d4b` — reviewed by Lane W |
| Revision 2 | `619b63e` — reviewed a second time |
| Revision 3 | `d268f70` — **pushed, `origin/main` verified**; reviewed a third time; **the artefact this revision replaces** |
| Author | Lane V (integrator). **This lane wrote no `src/**`, no `tests/**`.** |
| Drafting lanes | **Z1** (evidence authority, §A–F) · **Z2** (phase & ownership, §G–J, §P) · **Z3** (structure & policy, §K–S, Y-mapping) |
| Probes | `GATE7-CAPABILITY-PROBE.md` (Lane U) · `GATE7-V1-ADJACENT-PROBE.md` (Lane X) |
| Reviews | `GATE7-DESIGN-REVIEW.md` (W) · `GATE7-DESIGN-REVIEW-2.md` (Y) · `GATE7-DESIGN-REVIEW-3.md` (Z4) |
| Pending probe | `GATE7-Z5-PREPARE-PROBE.md` (Lane Z5) — **§5.5.5 / Z-4 is OPEN until it is published and cited** |
| Installed clients | Claude Code **2.1.237**, Codex CLI **0.149.0** |

---

## 0. How to read this document, and the one rule it is written under

Two independent reviews have now found **asserted-but-unprovable safety claims**
in this design: an AST pin that could not fail (R-3), a planted-credential test
that could not observe an unlisted egress (R-7), a feasibility matrix that could
not see production guidance (R-9), a mutant that could not be killed (A-d), and
`filter.*` declared closed *by inference* (S-1). Every one shares a shape.

> ### Z-RULE-1 — THE PROOF DISCIPLINE
>
> **Any test whose pass condition is "the bad thing did not happen" MUST contain,
> in the same test body and against the same fixture, a positive control that
> makes the bad thing happen through a deliberately un-hardened path, and MUST
> assert that the control fired.**
>
> A negative security assertion without a positive control in the same test is
> not evidence; it is an untested sentinel.

Concretely: `test_v1_filter_program_not_executed` must (a) arm the sentinel,
(b) run the **un-hardened** legacy invocation and assert the sentinel **exists**,
(c) delete it, (d) run the production pipeline and assert it **does not exist**.
Step (b) is what makes step (d) mean anything. Revision 2's version of that test
had no step (b) and **would have passed on the day S-1 was live**.

And a second discipline, applied to every property this document claims:

> **PROVEN BY** — the named test or structural obligation.
> **COULD IT PASS WHILE FALSE?** — the honest answer, including the residue.
> **IF MIS-WIRED** — which direction the failure goes, and why that direction is
> safe (or, where it is not, that it is not).

Where a mechanism rests on a **convention** rather than a type or the kernel,
this document says so **in bold at the point of use**. Python has no private
constructors. Every "impossible" below is one of: (a) impossible because the
value has no parameter to carry it, (b) impossible because the kernel refuses, or
(c) *detectable*, by a named runtime check plus a named AST test whose whitelist
a mutant must **visibly edit**. The three are never blurred.

### Reading order

§1–§3 are the shared structure and the cross-cutting mechanisms. §4–§7 are the
four subsystems, each carrying the nine headings §3 of the brief demands. §8–§16
are the cross-cutting obligations. §17 is the Y-1…Y-10 mapping. §18 is what Sol
must rule on. Appendix A is measured data; Appendix C is the revision-3 change
log.

**`REQUIRES-PROBE`** marks a statement that is reasoned but **not measured**. It
must not be read as a measurement, and Wave acceptance may not depend on one
without discharging it first.

---

## 0.1 Sol's twenty directives, and where each lands

| # | Directive | Where |
|---|---|---|
| **A** | post-worker git presentation commands are not evidence authority | §5.4 |
| **B** | the authority pipeline: base snapshot, start snapshot, delta | §5.5 |
| **C** | self-hiding and ignored paths | §5.6 |
| **D** | path model / V-2 | §5.7 |
| **E** | git administrative safety; make the index irrelevant | §5.8 |
| **F** | the primary tree | §5.9 |
| **G** | unforgeable execution phase; no fake worker run | §3.1 |
| **H** | legacy reconciliation | §7.6 |
| **I** | concurrent Codex sessions | §7.7 |
| **J** | recovery deadline, prior ruling preserved | §7.8 |
| **K** | the inventory data structure; OQ-B6 removed | §5.5.3 |
| **L** | Wave 0 must be independent | §12.2 |
| **M** | scope precedence preserved and made structural | §5.3A, §8 |
| **N** | activation enforcement — the runtime refuses | §4.12 |
| **O** | Fable — every "clips as before" deleted | §5.11 |
| **P** | the canonical crash matrix — one table, referenced by row id | §15 |
| **Q** | mutations — registry, production-active, named killers | §11 |
| **R** | wave order kept: 0 → A → B → D → C → E | §12.1 |
| **S** | capability findings stay, not softened | §6.0 |
| **T** | **REVIEW REQUIREMENT** — push the revision, verify `origin/main`, run an independent architecture review, **no implementation source before blocking findings = 0 and WAVE 0 APPROVED = YES**, and return the SHA, verdict, blocking findings, approval flag and the Y-1…Y-10 map | §18.5, §17 |

---

## 0.2 The four reconciliations between the drafting lanes

Three lanes drafted in parallel and disagreed in four places. **Measurement
decides, and Z1 measured last.** Each resolution is recorded here rather than
silently applied.

### Reconciliation 1 — the permitted git set: Z1's is narrower, and correct

Z3's producer **P-A** used `ls-tree -r -z`, `ls-files -z --others`,
`ls-files --others --exclude-standard -z`, `ls-files -v` and `cat-file blob`, on
the strength of a **correct** measurement: *"none of P-A's five commands invokes
a worker-set clean filter."* Z1 re-ran the same commands against **both**
execution surfaces and found the statement true and **scoped to one of two**:

```
===== poison = filter.myf.clean ONLY =====      ===== poison = core.fsmonitor ONLY =====
  FIRED   POSCTRL-plain-diff                      FIRED   POSCTRL-plain-diff
  FIRED   diff--name-only-z                       FIRED   diff--name-only-z
  clean   ls-files--others-z                      FIRED   ls-files--others-z        <-- P-A
  clean   ls-files--others-exclstd                FIRED   ls-files--others-exclstd  <-- P-A
  clean   ls-files-v                              FIRED   ls-files-v                <-- P-A
  clean   ls-tree-r-z-long                        clean   ls-tree-r-z-long
  clean   cat-file-blob                           clean   cat-file-blob
  clean   rev-parse                               clean   rev-parse
```

**Three of P-A's five commands execute a worker-chosen program on surface S-β.**
They can be neutralised with `-c core.fsmonitor=false` — the lever works — but
that is precisely the *enumerated, version-scoped* defence Y-1 rejected, and it
is the defence Z3's own argument for P-A over P-B rests on avoiding.

**RESOLVED: adopt Z1's permitted set.** Only `ls-tree -r -z --long`, `cat-file`
(bare) and `rev-parse` are measured clean on **both** surfaces. `ls-files` in
every form is prohibited. **Z3's dispatcher-side git-blob-sha1 is kept** — Z1
verified it independently, byte-exact on a normal file, an **empty** file, a file
with **no trailing newline** and a **symlink** — which lets `cat-file` come off
the PREPARE hot path entirely and be invoked lazily, for changed paths only.

> **Consequence: after the worker is launched, the dispatcher runs exactly TWO
> git commands — `cat-file`, which reads object ids and never paths, and
> `rev-parse --verify HEAD^{commit}`, which is B2's post-worker base check. Both
> are measured clean on every armed surface. NO PRESENTATION COMMAND RUNS.**

**Revision 3 stated this as "exactly ONE command", and that was false in its own
text** — §5.5.2 keeps `assert_worktree_base` untouched, §3.1.7 lists
`WorktreeBaseMismatch` in FINALIZE, and §8 row 2 requires the check *before any
evidence is collected*, which in code is `server.py:2005` → `git.py:532` →
`git rev-parse --verify HEAD^{commit}`, inside the task worktree, after the worker
exits. So §5.4.5's journal test — **the one test §5.4.6 marked NO in the *could it
pass while false?* column, and called the one check that survives a refactor** —
**would have failed on the happy path of every single run.**

The correction is to the *claim and the test*, **not** to the command. Three exits
were available and all three are refused explicitly:

| Tempting exit | Why it is refused |
|---|---|
| delete B2's post-worker verification | regresses a **§2 non-regression by name** and reopens task `49231f6e`'s exact defect, which `assert_worktree_base`'s own docstring cites as the reason it exists |
| weaken the journal assertion to an editable allowlist | that is R-3's disease and S-2's disease — a proof that cannot fail |
| move `assert_worktree_base` off `_run_git` | blinds the journal entirely and defeats §5.4.5's whole purpose |

`rev-parse --verify HEAD^{commit}` **is already in the permitted repertoire** and
is measured clean on S-α, S-β **and** S-γ (§5.4.1). The defect was never the
command; it was a sentence that overstated, and a test written to the sentence
rather than to the pipeline.

### Reconciliation 2 — §C's model: Z1's is strictly stronger

Z3 proposed a pre/post delta **of the ignore-suppressed set**, computed from two
`ls-files --others` listings. Z1 proposed **no suppressed set and no ignore query
at all**: `changed_paths` is the difference between two dispatcher-owned,
**ignore-blind** filesystem snapshots.

**RESOLVED: adopt Z1's model.** It is strictly stronger:

- no `.gitignore`, `info/exclude`, `core.excludesFile`, `status.showUntrackedFiles`,
  `assume-unchanged` or `skip-worktree` can remove a path, because none is
  consulted — rather than because a delta cancels them out;
- it needs no `ls-files`, which reconciliation 1 just prohibited;
- `.venv` is byte-identical in both snapshots, so it is in **neither** delta and
  collapses to a scalar `unchanged_count`. The 0 → 3,842 explosion **cannot
  occur**, rather than being subtracted away.

**Sol's Y-9 becomes MOOT rather than answered.** Y-9 asks whether a
`.gitignore` write is tamper (i) always, (ii) when it suppresses a path, or
(iii) when it suppresses a path this run created. **Under an ignore-blind
measurement, no worker write suppresses anything**, so writing `.gitignore` is
not an attack — it is an ordinary file change, scope-checked like any other. That
is a better answer than any of the three, and §5.6.5 says so explicitly. This
disposes of Z3's §M.4 cost (a legitimate "generate `dist/`, then gitignore it"
task landing `POLICY_VIOLATION`): it does not.

**Z3's F5 insight is preserved and confirmed.** A file created during the run
*inside an already-ignored directory* (`.venv/evil.py`) must still appear. Under
Z1's model it does, trivially: POST has it, START does not. Z1's model also
catches the case Z3's could not express — **a modification to an
already-existing** ignored file (`.venv/bin/activate`), which Sol's §C requires
by name (§5.6.3).

### Reconciliation 3 — the inventory type: Z3's structure, Z1's coverage

Z3's `PathIdentitySet` → `ScopeVerdict` → `ClassifiedInventory` ordering, with
**`ScopeVerdict` a required constructor argument** so content classification
cannot precede the scope verdict, is right and is *structural* rather than
conventional. Keep it.

But Z1 found Z3's six-value `ChangeKind` cannot express two facts:

1. **a modification to an existing suppressed file** — Sol's explicit §C
   requirement. `SUPPRESSED_NEW` covers creation only; there is no
   `suppressed_modified`, so the persistence-backdoor case has no kind;
2. **deletion of an untracked path** — a file created by run 1 and deleted by
   run 2 is neither `TRACKED_DELETED` nor any `*_NEW`.

**RESOLVED: keep Z3's staged types; replace the closed enum with Z1's orthogonal
tuple** `(change, origin, ignored_by_base, tracked_at_base)`, which is closed
under both cases and from which every one of Z3's six kinds is derivable (§5.5.4
gives the mapping). A closed enum that cannot express a required observation is
the same defect as revision 2's type that could not express `assume-unchanged &&
rm`.

### Reconciliation 4 — a methodological note that must be recorded

Z1 found the cause of the Z3/Lane-Y disagreement about whether
`status --porcelain -z` fires a clean filter:

> **If `GIT_INDEX_FILE` names a file that does not exist and `read-tree` has not
> been run, the index is empty, every tracked file reads as *deleted*, no content
> is compared, and no filter fires.**

Revision 2's layer 4 *requires* the `read-tree`, so the production shape is the
one that fires. **Any probe of a hardened invocation that omits the `read-tree`
measures a repository state the design never produces.** This is Z-RULE-1's
failure mode occurring inside a *probe* rather than inside a test, and it is the
third time in this gate a negative result came from an experiment that could not
have produced a positive one. It is recorded in §10.4 so it is not rediscovered.

---

## 0.3 New defects found by the drafting lanes

None of these is in either review. All are addressed in this revision.

| id | Defect | Where addressed |
|---|---|---|
| **Z1-N1** | **`git worktree add` executes a worker-chosen smudge filter and `post-checkout` hook during PREPARE**, from a *previous* task's poisoning of shared administrative state. Revision 2's hardening suppresses the hook and **not** the smudge (measured: the checkout wrote `SMUDGED:payload\r\n`). `--no-checkout` executes nothing. | §5.5.6, §5.8 |
| **Z1-N2** | **Revision 2 §8 row 3 is a live laundering hole.** `PathInventoryUnrepresentable` ranks *above* the policy rows, so **one `Write` of a non-UTF-8 filename downgrades `POLICY_VIOLATION` to `FAILED`.** Same shape as R-4, which revision 2 was adopted to fix. | §5.7.4, §8 row 5a |
| **Z2-G-F1** | **The code already fabricates a fake worker run.** `runner.py:1475-1482` builds `WorkerRun(start_failed=True)` on a generic spawn `OSError`; it flows into evidence collection, `append_run` and `_land_state`. Sol's §G forbids "no fake worker run" **by name**; revision 2 never mentions this exists. | §3.1.4 |
| **Z2-G-F2** | **Resuming a task whose worker is still alive marks the live task `FAILED`.** No PREPARE-phase legality check; legality is enforced by `transition()` *inside* the mutation block, and `_record_failure`'s mutable set contains `RUNNING`. **Masked today only by the repository flock — and S-5 is exactly the condition that removes the mask**, since the kernel releases a dead dispatcher's flock while its worker lives. | §3.1.4, §7.7 |
| **Z2-G-F3** | `TaskStore.transition` has **no compare-and-set** — last-writer-wins — so concurrent-replay exclusion rests on convention. | §15.3, P-M6 |
| **Z2-I-F1** | The liveness `flock` is defeatable by **fd inheritance** (measured live). Python's default is safe (PEP 446) and the failure direction is over-conservative. Named guard + named test. | §7.7.3 |
| **Z3-N1** | **Production has ONE ignored symlink** (and this repository four). Under revision 2's fold plus its `refused`-blocks-Fable rule, **that one symlink kills every Fable review of production, forever**, for a reason unrelated to any task. | §5.11.5 (Y-10) |

---

## 1. What actually went wrong: three shapes, not eight bugs

The eight defects in §1 of the brief are instances of three structural mistakes.
Naming them is the point of designing before implementing, because a patch aimed
at an instance leaves the shape intact.

### Shape 1 — Irreversible state is taken before the decision to take it is provably safe

| Defect | The irreversible thing taken too early |
|---|---|
| **G7-6** | `RESUME_REQUESTED → RUNNING` and `resume_count += 1` happen before context verification, projection and the transport check. A worker that never launches poisons the task as `FAILED`. |
| **G7-7** | `runs/NNN/` is created as a spool target before any authoritative run record exists; `run_count` moves only when `dispatcher-result.json` lands. |
| **G7-1** | The *dispatch* is committed — worktree created, session minted, worker paid for — while a resume profile the stored envelope will later demand is already impossible to construct. |

G7-1 is the deep one, and it is why §6/§25 of the brief ask for a **future-phase**
preflight. A preflight that only proves "this run can be built" is structurally
incapable of seeing G7-1: the dispatch profile is legal, and the caller cannot
alter the stored kind/complexity/risk that select the resume profile.

**One mechanism answers all three: a PREPARE phase that mutates nothing, proves
the whole reachable lifecycle, and hands an explicit reservation to an EXECUTE
phase that is the only thing allowed to mutate.**

### Shape 2 — A measurement is reported as complete when the thing it measures was partly not looked at

| Defect | The claim | What was not looked at |
|---|---|---|
| **G7-2** | `diff_patch_complete: true` | untracked files' contents |
| **G7-3** | `"partial stdout preserved"` | whether any bytes exist at all |
| **G7-5 / G7-1** | "the selection fits" | the composed payload of a phase other than the current one |
| **G7-8** | "the run is ours" | whether the process recorded as ours is still that process |
| **V-1** *(rev 2)* | "`filter.*` is closed" | whether it actually fires — **it does** |

**The rule, and it is already the house style:** a completeness flag must be
produced by the same component that produced the artefact, from its own
accounting of what it covered — never asserted by a caller that happened not to
hit an exception.

### Shape 3 — Process-local knowledge is treated as durable knowledge

| Defect | Held only in one Python process |
|---|---|
| **G7-8** | `RunRegistry`'s `asyncio.Task` objects, and the subprocess pipe read ends |
| **G7-7** | the intent that `runs/NNN` belongs to the run currently executing |
| **G7-4** | there is no durable phase state to report progress *from* |
| **S-5** *(rev 2)* | which dispatcher owns a run — recorded, and **never read** |

The honest consequence: **a newly started Python process cannot re-own the
previous process's `asyncio` subprocess pipes.** Subsystem D does not try. It
removes the pipes.

### Shape 4 — added in revision 3: *the measuring instrument is controlled by the thing being measured*

This shape was invisible until Lane X and Lane Z1 measured it, and it is the
whole of directives A–F.

Every evidence surface in the dispatcher — `git status`, `git diff`,
`git diff --name-only`, `git ls-files`, `git diff --check`, `git diff --stat` —
is a **git presentation command**. Presentation commands resolve *attributes* and
refresh the *index*, and both are worker-writable. So the dispatcher's own
measurement, taken after the worker exited with the dispatcher's privileges,
executes a program the worker chose, and reports what that program says.

Hardening cannot close it: `filter.*` has **no** general argv lever (measured),
in-tree `.gitattributes` is disableable by **no flag** on git 2.43, and
`$GIT_COMMON_DIR/info/attributes` is reachable by the `Write` tool with no git
command at all. **The answer is not a better flag. It is to stop asking git what
the working tree contains.**

---

## 2. The subsystems and their seams

```
              ┌───────────────────────────────────────────────────────────┐
  PREPARE     │ §5.8  RAW ADMINISTRATIVE PREFLIGHT — plain file I/O only  │
  (mutates    │        NO GIT PROCESS HAS BEEN CREATED YET                │
   nothing)   └───────────────────────┬───────────────────────────────────┘
                                      │ trusted baseline reconciled
              ┌───────────────────────▼───────────────────────────────────┐
              │ A. LIFECYCLE PLANNING & FUTURE-PHASE PREFLIGHT            │
              │    G7-1 G7-5 G7-6   LifecycleFeasibilityReport (4 phases) │
              └───────────────────────┬───────────────────────────────────┘
  RESERVE     ┌───────────────────────▼───────────────────────────────────┐
              │ B1. RUN TRANSACTION  G7-7  reserve_run() owns runs/NNN    │
              └───────────────────────┬───────────────────────────────────┘
  LAUNCH      ┌───────────────────────▼───────────────────────────────────┐
              │ WorkerHandle — PROOF a child exists. RUNNING begins HERE. │
              └───────────────────────┬───────────────────────────────────┘
  EXECUTE     ┌───────────────────────▼───────────────────────────────────┐
              │ C. TIMEOUT / PROGRESS   G7-3 G7-4                         │
              │ D. DURABLE OWNERSHIP    G7-8                              │
              └───────────────────────┬───────────────────────────────────┘
  FINALIZE    ┌───────────────────────▼───────────────────────────────────┐
              │ B2. THE AUTHORITY PIPELINE  G7-2                          │
              │     two dispatcher-owned filesystem snapshots →           │
              │     inventory → SCOPE → content → one representation      │
              │     post-worker git: cat-file + rev-parse (B2) ONLY       │
              └───────────────────────┬───────────────────────────────────┘
  LAND        ┌───────────────────────▼───────────────────────────────────┐
              │ LandingIntent — recorded, then applied idempotently       │
              └───────────────────────────────────────────────────────────┘
```

Seams, stated so a reviewer can attack them:

- **§5.8 → everything.** The administrative preflight is step 0 and runs with
  **plain file I/O**. Nothing else in PREPARE may run until it passes, because
  `git worktree add` itself executes repository-configured programs (Z1-N1).
- **A → B1.** A produces a `LifecycleFeasibilityReport` and a composed
  `--append-system-prompt` already measured against the transport ceiling. A
  never writes task state; B1 is the first write.
- **B1 → LAUNCH.** The `RunReservation` is the only thing that names `runs/NNN`.
- **LAUNCH → EXECUTE.** A `WorkerHandle` is proof a child exists. `RUNNING` is
  entered on the line after `create_subprocess_exec` returns, and never before.
- **EXECUTE → B2.** B2 is handed a worktree path, a base commit, a reservation
  and the START snapshot. It re-derives nothing about identity.
- **B2 → LAND.** The landing decision is a **pure function of durable artefacts**,
  recorded before it is applied.

---

## 3. Cross-cutting model

### 3.1 REFUSAL is not FAILURE — an unforgeable execution phase (directive G, fixes S-2)

#### 3.1.1 What the code does today, measured at `619b63e`

```python
# server.py:2694
def _record_failure(self, task_id, exc) -> None:
    record = self.store.load(task_id)
    if record.state in {CREATED, ROUTED, RUNNING, RESUME_REQUESTED}:   # :2704-2709
        self.store.transition(task_id, TaskState.FAILED, ...)          # :2710-2715
```

Two call sites, each wrapping an entire mutation block (`server.py:1121`,
`:1285`). Order inside `_dispatch`: `store.create()` 928 → `ROUTED` 932 →
**`RUNNING` 937** → bookkeeping 941 → worktree 952 → B2 verify 976 → context 1005
→ argv 1014 → **spawn 1043**. `RUNNING` is entered roughly a hundred lines before
a child exists, on both paths, and `resume_count` is spent with it.

#### 3.1.2 Why revision 2's fix does not hold

Revision 2 kept the guard and keyed it on a phase:

```python
def _record_failure(self, task_id, exc, *, phase: ExecutionPhase) -> None:
    if phase is ExecutionPhase.PREPARE: ...
```

`phase` is an ordinary caller-supplied keyword. The second review grepped all
4,459 lines for `tracker.phase` and `phase=tracker`: **zero occurrences.**
Revision 2's safety argument — *"the unsafe direction is not reachable"* — is an
argument about `PhaseTracker`, and **`PhaseTracker` is not what the guard reads**.
One wrong literal at a FINALIZE call site swallows a real failure, the task
strands in `RUNNING` holding its repository claim, and revision 2's own mutants
all exercise the other direction. **This is R-3's disease with a new coat of
paint.**

#### 3.1.3 DECISION D-1 (revision 3) — the guard reads an object, not an argument

```python
# phase.py — NEW. Nothing else defines or transports ExecutionPhase.

class ExecutionPhase(IntEnum):
    PREPARE  = 1   # nothing has been written. Nothing at all.
    RESERVE  = 2   # run identity allocated; no child exists
    LAUNCH   = 3   # spawn attempted
    EXECUTE  = 4   # a child process exists and is ours
    FINALIZE = 5   # child gone; evidence in flight
    LAND     = 6   # task state being applied

_CURRENT: ContextVar[ToolExecution | None] = ContextVar("tool_execution", default=None)

@final
class ToolExecution:
    """One per tool body. The ONLY carrier of 'where the code is'.

    The constructor takes NO phase: every execution starts at PREPARE and can
    only be advanced by a statement. There is no way to EXPRESS an execution
    that claims to be in PREPARE while holding a reservation.
    """
    __slots__ = ("_tool", "_task_id", "_phase", "_reservation", "_handle")

    def enter(self, phase: ExecutionPhase) -> None:
        if phase < self._phase:                       # MONOTONE
            raise PhaseRegression(f"{self._tool}: {self._phase.name} -> {phase.name}")
        self._phase = phase

    def mark_spawned(self, handle: WorkerHandle) -> None:
        """LAUNCH -> EXECUTE. Requires PROOF that a child exists."""
        if self._phase is not ExecutionPhase.LAUNCH:
            raise InternalDispatcherError(f"mark_spawned from {self._phase.name}")
        self._handle = handle
        self.enter(ExecutionPhase.EXECUTE)

@contextmanager
def begin_tool_execution(tool: str) -> Iterator[ToolExecution]:
    """The ONLY sanctioned construction site. Refuses to nest."""
```

and the guard:

```python
def _record_failure(self, execution: ToolExecution, exc: DispatcherError) -> None:
    """There is NO `phase` parameter and NO `task_id` parameter. Both come from
    `execution`. A wrong literal is not merely discouraged: it CANNOT BE
    WRITTEN, because there is nowhere to write it."""
    if execution is not current_execution():
        raise InternalDispatcherError("failure recorded against a non-current execution")

    phase   = execution.phase          # THE ONLY SOURCE OF THE PHASE
    task_id = execution.task_id

    if phase is ExecutionPhase.PREPARE:
        if execution.reservation is not None or execution.worker is not None:
            self._record_internal_inconsistency(execution, exc)   # loud; does NOT return
        else:
            self._append_refusal(execution, exc)   # refusals.jsonl only
            return                                  # state.json BYTE-IDENTICAL

    if phase in (ExecutionPhase.RESERVE, ExecutionPhase.LAUNCH):
        self._record_launch_failure(execution, exc)    # run record only
        return

    # EXECUTE / FINALIZE / LAND — a worker existed. Existing behaviour.
    ...
```

**Invariants:**

| id | Invariant |
|---|---|
| **G-I1** | `_record_failure` accepts **no** phase — not a parameter, not a literal, not a default — and **no `task_id`** either, so a mismatched `(task_id, phase)` pair cannot be constructed. |
| **G-I2** | `ExecutionPhase` literals appear in exactly two places: the enum, and `enter(...)`/`assert_phase(...)` statements inside whitelisted tool bodies. |
| **G-I3** | `phase` is **monotone non-decreasing**. A regression raises `PhaseRegression`. The tracker can never read *earlier* than the furthest point the code reached. |
| **G-I4** | Exactly one `ToolExecution` is current per tool body; `_record_failure` refuses a foreign one. |
| **G-I5** | `RUNNING` requires a `WorkerHandle`, which cannot exist unless `create_subprocess_exec` returned. |
| **G-I6** | **No `WorkerRun` is ever constructed for a spawn that did not happen.** |
| **G-I7** | A RESERVE- or LAUNCH-phase failure leaves `state`, `resume_count`, `run_count` and `state_history` **unchanged**. |
| **G-I8** | A PREPARE-phase refusal leaves `state.json` **byte-identical** (sha256, including `updated_at` and `state_history`). |

#### 3.1.4 Two live defects this closes, which revision 2 never mentioned

**Z2-G-F1 — the code fabricates a fake worker run today.** `runner.py:1475-1482`
returns `WorkerRun(..., start_failed=True)` when `create_subprocess_exec` raised
a generic `OSError`. **No child was created.** The object flows into
`_finalise_worker_run` (which collects evidence against a worktree no worker ever
touched), into `append_run` (so `run_count` advances), and into `_land_state`.
Sol's directive G forbids a fake worker run **by name**.

```python
async def start_worker(spec: WorkerInvocation) -> WorkerHandle:
    """Create the child. Return a handle, or RAISE. NEVER a WorkerRun."""
    ...
    except OSError as exc:
        spools.close()
        if exc.errno == errno.E2BIG:  raise _context_too_large(...) from exc
        raise WorkerSpawnFailed(...) from exc      # replaces runner.py:1475-1482
    return WorkerHandle(proc=proc, spec=spec)      # <- only construction site
```

`run_worker(spec) -> WorkerRun` is **deleted**.

**Z2-G-F2 — resuming a live task marks it `FAILED`.** `resume_plan`
(`sessions.py:115`) checks instruction, task-id agreement, the resume cap and
stored fields — **not the state**. Legality is enforced by
`store.transition(task_id, RESUME_REQUESTED)` at `server.py:1197`, *inside* the
mutation block. `RESUME_REQUESTED ∉ ALLOWED_TRANSITIONS[RUNNING]`, so it raises
`InvalidStateTransition`, which `_record_failure` converts to **`FAILED`** —
on a task whose worker is still running.

Masked today by the repository flock. **S-5 is exactly the condition that removes
the mask.** New: a PREPARE-phase `assert_resume_legal_from(record.state)`
producing `ResumeNotPermittedFromState`, a byte-identical refusal.

#### 3.1.5 RUNNING begins only after a child exists — and a spawn failure changes nothing

```
dispatch: PREPARE ─(pure; nothing on disk)
          store.create() ─► CREATED ─► ROUTED
          RESERVE  ─► reserve_run(); worktree; B2 verify; anchor; context; argv
          LAUNCH   ─► expectation.json ─► start_worker
                        │ raises  ─► reservation ABORTED_PRELAUNCH
                        │            TASK STATE UNCHANGED (stays ROUTED)
                        └ handle  ─► ownership.json ─► EXECUTE ─► RUNNING
          FINALIZE ─► evidence ─► LAND ─► landing.json ─► terminal state

resume:   PREPARE ─(pure; state.json byte-identical on refusal)
                     assert_resume_legal_from(record.state)        [Z2-G-F2]
          RESERVE  ─► reserve_run(); RESUME_REQUESTED
          LAUNCH   ─► start_worker
                        │ raises  ─► ABORTED_PRELAUNCH; TASK STAYS
                        │            RESUME_REQUESTED; resume_count UNCONSUMED
                        └ handle  ─► ownership.json ─► EXECUTE
                                     ─► RUNNING (+ resume_count)
```

**This changes revision 2.** Revision 2 sent a spawn failure to `FAILED` from
`ROUTED`/`RESUME_REQUESTED`. Sol's directive G is explicit: kernel `E2BIG`,
missing binary and spawn `OSError` **leave task lifecycle unchanged** — task
state unchanged, `resume_count` unchanged, no fake worker run, no `RUNNING`.

**Consequence, stated honestly:** a dispatch whose spawn fails leaves the task in
`ROUTED`, which is neither terminal nor worker-actionable. It is not *silent* —
the tool call returns the typed error, `reservation.json` records
`ABORTED_PRELAUNCH` with the cause, and `get_task` surfaces both — and it is not
*dangerous* — no claim held, no worktree work, no budget spent. But it is a state
Sol must choose to leave or re-dispatch. **See escalation Z2-Q1 (§18.2).**

#### 3.1.6 Auditability without lifecycle mutation

A PREPARE-phase refusal appends to `state/tasks/<id>/refusals.jsonl`
(append-only, 0600: `{at, tool, phase, code, message, details, remediation}`,
where `phase` is written **from `execution.phase`, never a literal**) and is
surfaced by `get_task` as a bounded `recent_refusals` list. `state.json` is not
touched. LAUNCH failures are surfaced the same way as `launch_failures`.

The byte-identical guarantee is scoped to `state.json` — task lifecycle state —
and says so.

#### 3.1.7 Which errors occur in which phase

Not a class hierarchy. **No exception class is modified.** The phase distinguishes
what the class never could:

| Error | Raised in | Phase(s) |
|---|---|---|
| `ValidationBudgetExceeded`, `LifecycleInfeasible`, `LifecycleProjectionStale`, `LifecycleProfileChanged` | validation/lifecycle | PREPARE only |
| `ApprovedSkillChanged`, `SkillPolicyViolation`, `ProjectGuidance*` | skills/guidance | PREPARE only |
| `RepositoryBusy` (retryable), `RepositoryRecoveryRequired`, `RepositoryRecoveryInProgress` | locks | PREPARE only |
| `RepositoryAdministrationUnestablished` / `Unreconciled` | gitadmin | PREPARE only |
| `EvidenceIncompleteForReview`, `EvidenceExceedsReviewBudget` | review path | PREPARE only |
| `ResumeNotPermittedFromState` **NEW** | resume path | PREPARE only |
| **`ContextTooLarge`** | `runner.py:811` **and** `runner.py:1465` | **PREPARE and LAUNCH** |
| `ClaudeBinaryNotFound`, `WorkerSpawnFailed` **NEW** | spawn | LAUNCH only |
| **`WorktreeBaseMismatch`** | three call sites | **PREPARE and FINALIZE** |
| `GitEvidenceCollectionFailed`, `FilesystemSnapshotFailed` | evidence | PREPARE / FINALIZE |
| `PhaseRegression` **NEW** | `phase.py` | any — loud |

**Three classes appear in more than one phase.** Under a class-keyed guard each
would have been a laundering hazard; under a phase-keyed guard none is, and
`WorktreeBaseMismatch` is **not split**.

#### 3.1.8 PROOF DISCIPLINE

**Property: a wrong phase literal cannot swallow a real failure.**
**PROVEN BY** — construction. `test_record_failure_takes_no_phase_parameter`
(`inspect.signature`: parameters are exactly `("self","execution","exc")`; none
named `phase`, none annotated `ExecutionPhase`, none with an `ExecutionPhase`
default) and `test_execution_phase_literals_are_confined` (AST).
**COULD IT PASS WHILE FALSE?** No for the literal case — there is nothing to
pass. **Yes for one residue:** a caller could construct a fresh `ToolExecution`
(which starts at PREPARE) and hand it in. Closed by the contextvar identity check
(`test_record_failure_rejects_a_foreign_execution`) and by the single-construction-site
AST test — **which is a convention pinned by a whitelist, not a type.**
**IF MIS-WIRED** — a forged execution raises `InternalDispatcherError` at the
moment of use. Loud, not silent.

**Property: `RUNNING` implies a child existed.**
**PROVEN BY** — `_enter_running` cannot be called without a `RunOwnership`, which
cannot be built without a `WorkerHandle`, whose constructor reads `/proc/<pid>`
and raises for a pid that does not exist.
**COULD IT PASS WHILE FALSE?** Only by fabricating a handle, which requires a
live pid *and* editing the AST whitelist.
**IF MIS-WIRED** — the fabrication raises before any transition. Safe direction.

**Property: a mis-wiring reads a LATER phase, never an earlier one.**
**PROVEN BY** — `enter()` is monotone, and **every durable write asserts the
phase it expects** (`test_phase_is_asserted_at_every_durable_write`), so a
deleted `enter()` fails at the first artefact past the deletion. This is the
argument revision 2 made; it is true here **because the guard now reads the
object the argument is about.**
**COULD IT PASS WHILE FALSE?** Only if someone deletes both the `enter()` and the
assertion at the same artefact — two visible edits in one diff.

### 3.2 The phase model

```
PREPARE ──► RESERVE ──► LAUNCH ──► EXECUTE ──► FINALIZE ──► LAND
mutates     allocates   spawns     child runs   collects     applies the
NOTHING     run         the child  (RUNNING)    evidence     recorded intent
            identity                                          (idempotent)
   │            │           │           │            │            │
   │            │           │           │            │            └─ LAND_INCOMPLETE
   │            │           │           │            └─ FINALIZATION_FAILED
   │            │           │           └─ ORPHANED / TIMED_OUT
   │            │           └─ spawn failed ─► ABORTED_PRELAUNCH,
   │            │                              TASK LIFECYCLE UNCHANGED
   │            └─ ABORTED_PRELAUNCH (index consumed, never reused)
   └─ refusal: state.json BYTE-IDENTICAL. refusals.jsonl. No FAILED.
```

`LAND_INCOMPLETE` answers R-10: the window between "evidence is durable and
`dispatcher-result.json` is written" and "the terminal state has been applied".

### 3.3 Run identity is allocated, not derived

Every `run_index = record.run_count + 1` in `server.py` (`:941`, `:1207`,
`:1359`) is deleted. Run identity comes from `reserve_run()` and nowhere else.

### 3.4 What must not regress

B2 exact-full-SHA `worktree HEAD == envelope.repository.base_commit` · the
primary-tree invariant · scope enforcement · untracked PATH detection ·
dispatcher-created external worktrees · `--safe-mode` · no native Skill runtime ·
no recursive delegation · no push/merge/commit/gh/bisect worker authority ·
blocking MCP semantics with `asyncio.shield` · **zero model-driven `get_task`
polling** · duplicate-run prevention · B3 provider-limit classification · exactly
four MCP tools · B4 config authority · worker/Fable separation · fail-closed ·
**no dispatcher-owned `APPROVED` state**.

#### Four §2 items the reviews found already broken

| §2 item | Verdict | Answered in |
|---|---|---|
| **scope enforcement** | **already broken at the baseline** for non-ASCII paths, tracked *and* untracked (R-2); revision 1 weakened it further (R-4); **revision 2 re-broke it** via `PathInventoryUnrepresentable` at row 3 (Z1-N2) | §5.7, §5.3A, §8 |
| **primary-tree invariant** | blind to `.git/**`; and `snapshot_primary_tree` is `git status`, which executes worker programs and is blindable by `assume-unchanged`, `info/exclude` and `status.showUntrackedFiles` | §5.8, §5.9 |
| no push/merge/commit/gh authority | **incomplete** — `git config`, `git update-index` and `git -C` are not on the deny list | §5.8.3 |
| **fail-closed** | weakened by revision 2's silent `return` in `_record_failure` | §3.1.3 |

These are the honest state of the baseline. **Wave 0 exists because of them.**

### 3.5 One canonical crash matrix

> **There is exactly ONE crash-point table in this document. It has FIFTEEN rows,
> C1…C15, in §15. Every other section references it by row id and states no count
> of its own.**

Revision 2 had fifteen rows in §5.9 and then said *"all ten points"* twice, so
amendment 7's five new rows — including the one revision 2 itself called *"the
reachable-on-every-run point revision 1 missed"* — shipped **with no test plan**.
A **documentation mutant** (P-M9) is the only thing that can fail for that, and
§15.5 carries it.

---

## 4. SUBSYSTEM A — Lifecycle context planning and preflight

Covers **G7-1** (impossible future profile), **G7-5** (oversized/repetitive
payload), **G7-6** (preflight that mutates). Directive **N** makes its activation
enforceable rather than asserted.

### 4.1 Current failure

Measured at the baseline against the shipped `config/approved-skills.json`
(manifest `2026-08-20.1`) and `[skills].max_projected_bytes = 72000`:

| | |
|---|---|
| Legal envelope shapes (`TaskKind` × `Complexity` × `RiskLevel`) | **120** |
| Dispatch profiles already over the cap | **36 / 120** |
| Resume profiles over the cap | **50 / 120** |
| Shapes where dispatch fits but resume can never be built — **the G7-1 trap** | **14 / 120** |

Independently reproduced by Lane W against the real engine, Δ=0 on every figure.
The brief's example (`implementation`/high/high: 70,623 → 76,708) is one of the
14 and is **not** the worst: `security_sensitive`/high/high is 89,376 → 95,461,
and `refactor`/low/low is **76,513 at dispatch** — already infeasible today.

So the accurate statement of G7-1 is stronger than "resume adds one skill": **the
selection algebra is set-union over whole general-purpose documents, and 42% of
the profile space is infeasible against its own transport budget.**

Three mechanical causes: whole-document union (`skills.py:839`); the caller
cannot narrow it (kind/complexity/risk are frozen in the envelope, so
`ContextTooLarge`'s remediation is honest and un-actionable); and the horizon is
one run long (`_assert_context_fits_the_transport`, `runner.py:793`, measures
only the invocation being built).

And G7-6 mechanically: `RESUME_REQUESTED`/`RUNNING` and `resume_count` are
written at `server.py:1197-1205`, while `verify_dispatch_anchor`, `for_worker`
and `build_worker_invocation` — the three things that can refuse — run at
`:1218-1246`, *after*.

Lane W also measured that the failure is **later than revision 1 described**: a
36/120 shape burns a task id, three transitions **and a real `git worktree add`
on disk** before `project_for()` refuses at `server.py:1005`.

### 4.2 New invariants

- **A-I1 (feasibility).** A task MUST NOT reach `RUNNING` for the first time
  unless **every automatically reachable future lifecycle phase** has been proven
  constructible **and** transportable, and the proof persisted.
- **A-I2 (determinism).** The profile for a phase is a total function of stored
  task facts and the dispatcher-owned phase. No caller text, no file contents, no
  model, no clock, no filesystem scan.
- **A-I3 (monotone lattice).** `VALIDATION_ONLY_RESUME ⊆ CORRECTION_RESUME`, so a
  proven phase proves every phase below it.
- **A-I4 (provenance).** Every projected byte traces to an approved source id,
  path, SHA-256, enumerated sections/concepts, projection SHA-256 and version. A
  source-hash change invalidates the projection until re-reviewed.
- **A-I5 (no runtime shaping).** No runtime summarizer, no LLM compression at
  task time, **no truncation anywhere**. Size is reduced by review, once, in
  source control.
- **A-I6 (zero mutation).** PREPARE mutates no lifecycle state; on refusal
  `state.json` is byte-identical.
- **A-I7 (composition is what is measured).** Feasibility is decided on the final
  composed `--append-system-prompt` UTF-8 byte string per phase, not on
  per-component sums.
- **A-I8 (activation, directive N).** The **registered production entrypoint
  refuses to start** if lifecycle profiles or future-phase preflight are disabled
  in the configuration it is authorised to load.

### 4.3 The four profiles

`LifecyclePhase` is dispatcher-owned and distinct from `RunKind`.

| `LifecyclePhase` | Reached by | `RunKind` | Purpose |
|---|---|---|---|
| `DISPATCH_IMPLEMENTATION` | first worker run | `DISPATCH` | enough methodology to start and complete |
| `CORRECTION_RESUME` | `resume_claude_task` | `RESUME` | respond to Sol/Fable findings. **No initial planning material.** |
| `VALIDATION_ONLY_RESUME` | **never selected in V1** — proven in preflight only | `RESUME` | verification and fixup only |
| `FABLE_REVIEW` | `review_task_with_fable` | `REVIEW` | independent review context. **Zero implementation methodology.** |

**DECISION D-3 — `VALIDATION_ONLY_RESUME` is PROVEN and NEVER SELECTED in V1.**
Revision 1 selected it from a predicate ANDing four dispatcher measurements with
one **worker claim**. Rejected, for the reason Lane W gave: it would have been
**the only place in the entire design where a worker claim changes dispatcher
behaviour**, and A-I3 bounds the *byte* cost of choosing wrong but not the
*methodology* cost. The phase stays in the enum and in the feasibility matrix
because §6/§25 require the matrix to cover it; a test asserts **no runtime path
returns it**.

### 4.4 Hash-pinned compact projections (§5)

Compact lifecycle artifacts are **new source-controlled files in this
repository**, derived by human/Sol review from already-approved skill sources.
Not generated at runtime, not generated by a build step.

```
config/
  approved-skills.json                  (unchanged — still the source of truth
                                         for what may be read at all)
  approved-lifecycle-profiles.json      NEW — the provenance manifest
  lifecycle/v1/*.md                     NEW — reviewed compact artifacts
```

The manifest binds, per artifact: `path`, `projection_sha256`,
`projection_bytes`, `projection_version`, and a `derived_from[]` list carrying
`source_skill_id`, `source_path`, `source_sha256`, `source_sections[]` and
`concepts[]`. Verification, at every projection:

```
manifest entry
  -> each derived_from source id must be an APPROVED approved-skills.json entry
  -> its source_sha256 must equal that entry's skill_md_sha256
  -> the source file on disk must still hash to it   (reuses skills._verified_bytes)
  -> the projection file must hash to projection_sha256
  -> the projection must pass the SAME content-refusal rules as skills.py
     (ALLOWED_FRONTMATTER_KEYS / FRONTMATTER_MECHANISM_KEYS / DYNAMIC_COMMAND_MARKERS)
  -> INERT TEXT
```

Two properties follow, and both are load-bearing. **A source hash change
invalidates the compact projection** even though the projection file is
unchanged — which is the §5 requirement and the reason the manifest cannot be a
list of files. And **no directory is trusted, nothing is discovered, nothing
executes** — the rules `skills.py` already enforces, applied to artifacts that
are additionally inside this repository and reviewed under the same commit
discipline.

`ENVELOPE_PRECEDENCE_PREAMBLE` is emitted unchanged, immediately before the first
projected block; `SECTION_ORDER` and the fingerprint recipe are untouched.
`SkillProjectionEngine` is **not** deleted — it remains the verifier of source
approval and hashes.

### 4.5 Preflight and the feasibility matrix (§25 — INTERNAL, not a tool)

```python
# lifecycle.py — INTERNAL. Never registered with MCPServer. Four tools, forever.

@dataclass(frozen=True)
class PhaseFeasibility:
    phase: LifecyclePhase
    profile_id: str; profile_version: str
    artifact_ids: tuple[str, ...]; skill_source_ids: tuple[str, ...]
    projected_skill_bytes: int
    guidance_cap_bytes: int              # THE CAP, not a fixture's size — §9.2A
    dispatcher_authored_bytes: int
    composed_append_system_prompt_bytes: int   # THE number that decides
    transport_ceiling_bytes: int
    approved_hashes_verified: bool
    required_deny_patterns_present: bool
    supporting_files_verified: bool
    review_context_available: bool       # FABLE_REVIEW only
    feasible: bool
    refusal_code: str | None; refusal_detail: str | None

@dataclass(frozen=True)
class LifecycleFeasibilityReport:
    schema_version: Literal["1.0"]
    task_id: str; envelope_digest: str; manifest_version: str
    computed_at: datetime
    phases: tuple[PhaseFeasibility, ...]
    unreachable_phases: tuple[str, ...]
    feasible: bool
```

- **Every automatically reachable phase, and no others.** `FABLE_REVIEW` is
  included (reachable from `AWAITING_SOL_REVIEW` for every task); the resume
  phases are included when `max_resume_count > 0` and are recorded as
  `unreachable` when it is `0` — §25's *"do not include optional future actions
  the current task can never reach"*, answered concretely.
- **Composition, not summation.** Each number is produced by actually composing
  through `WorkerContextComposer` and measuring UTF-8 bytes.
- **Persisted**, and re-checked (not re-derived) on resume: a resume recomputes
  the report for the phase it is about to run and compares `manifest_version` and
  `profile_id`/`profile_version` against the persisted one. Drift is a refusal
  (`LifecycleProjectionStale`); the dispatch-time report is never rewritten.

**Why this catches G7-1 and revision 0 could not.** At dispatch, phase
`CORRECTION_RESUME` is composed and measured even though no resume has been
requested. For the 14 trap shapes the composed count exceeds the ceiling,
`feasible` is `False`, and `LifecycleInfeasible` is raised **in PREPARE** —
before `store.create()`, before the worktree, before a token is spent.

### 4.6 State transitions

**Subsystem A introduces zero new `TaskState`s.** The transitions it touches are
the ones it must now happen *before*:

```
dispatch:  (no task exists)
             ├── PREPARE: admin preflight (§5.8) · budget · repo authorization ·
             │            base resolution · lifecycle feasibility (4 phases) ·
             │            guidance identity · composition · transport check
             │   refusal ──► nothing exists. No task id. PREPARE-phase refusal.
             ▼
           CREATED ──► ROUTED ──► (RESERVE) ──► (LAUNCH) ──► RUNNING ──► …

resume:    AWAITING_SOL_REVIEW | FABLE_REVIEWED | TIMED_OUT | BLOCKED |
           FAILED | POLICY_VIOLATION
             ├── PREPARE: assert_resume_legal_from(state) [Z2-G-F2] · resume_plan
             │            (cap) · budget · repo authorization · admin preflight ·
             │            repo lock strategy · worktree identity + B2 base ·
             │            dispatch-anchor verification · phase selection ·
             │            artifact + source hash verification · guidance
             │            verification · composition · transport check ·
             │            CLI argv construction · schema projection
             │   refusal ──► state.json BYTE-IDENTICAL. PREPARE-phase refusal.
             ▼
           RESERVE ──► RESUME_REQUESTED ──► LAUNCH ──► RUNNING ──► …
```

**`build_argv(spec)` is called in PREPARE**, so `ContextTooLarge` is raised
before `RESUME_REQUESTED`; the argv it produces is carried into LAUNCH rather
than rebuilt, so the thing measured is the thing executed. (`build_argv` is
already pure and deterministic — `runner.py:625` — which is what makes this safe.)

### 4.7 Persistent data

`state/tasks/<id>/preflight/lifecycle-feasibility.json` — the full report.

New optional `TaskRecord` fields (all default `None`, so every existing
`state.json` loads): `lifecycle_preflight: LifecyclePreflightRecord | None`
carrying `manifest_version`, `envelope_digest`, `computed_at`, `feasible`,
`phases[]`, `unreachable_phases[]`, `max_composed_bytes`, `report_path`.
New optional `RunMetadata.lifecycle_phase: str | None`.

The proof is written **with the first mutation**, not before it — persisting it
is itself a mutation, so it lands together with `store.create()` (dispatch) or
with the `RESUME_REQUESTED` transition (resume). A task with no persisted proof
is treated as **unproven and re-proved**, never as proven elsewhere.

### 4.8 Error taxonomy

| Code | Class | Phase | Retryable | Meaning |
|---|---|---|---|---|
| `LifecycleInfeasible` | `DispatcherError` | PREPARE | no | Some automatically reachable phase cannot be composed or transported. Details name the phase, its composed bytes, the ceiling, the artifact ids, and every phase's number. |
| `LifecycleProjectionStale` | `DispatcherError` | PREPARE | no | A `projection_sha256` or a `derived_from[].source_sha256` no longer matches. **Never recalculated and accepted.** |
| `LifecycleProfileChanged` | `DispatcherError` | PREPARE | no | A task dispatched under one lifecycle configuration is being resumed under another. Fail closed **in both directions**. |
| `LifecycleProfileUnknown` | `ConfigurationError` | load | no | Manifest not exhaustive over `LifecyclePhase`, or names an unknown artifact. Fails at config load. |
| `ProductionActivationDisabled` | `ConfigurationError` | startup | no | §4.12. |
| `ContextTooLarge` | existing, **unsplit** | PREPARE **and** LAUNCH | no | The phase distinguishes preflight refusal from kernel `E2BIG`. |

Every refusal payload is bounded (§29): ids and byte counts, **never text**. A
size failure must not become a content leak.

### 4.9 Crash points

Subsystem A contributes **no canonical crash rows** (§15). Its four durable-write
points are recorded in §15.4 as non-crash-points with named tests, because each
is self-healing rather than requiring reconciliation:

| Crash after | Post-condition | Named test |
|---|---|---|
| feasibility computed, before `store.create()` | **nothing durable exists** | `test_prepare_crash_leaves_no_durable_state` |
| `store.create()`, before the preflight record | `lifecycle_preflight is None`; next touch recomputes and refuses if infeasible. **Never assumed feasible.** | `test_missing_preflight_record_is_recomputed_never_assumed` |
| preflight written, before reservation | `envelope_digest` + `manifest_version` invalidate a stale record | `test_stale_preflight_record_is_reproved` |
| resume PREPARE crash | `state.json` untouched | `test_prepare_crash_leaves_state_byte_identical` |

### 4.10 Tests

Unit:

- **the 120×2 matrix**, enumerated: every legal
  `TaskKind × Complexity × RiskLevel × LifecyclePhase` composed and measured,
  asserting **zero infeasible phases** — and **parameterised by the guidance
  CAP, not a fixture's size** (§9.2A). This is the assertion that would have
  failed at the baseline for 50 of 120 shapes.
- A-I2 determinism: computed twice in one process and once in a fresh
  interpreter with `os.environ` cleared and the CWD moved; all three identical.
- A-I3: `artifacts(VALIDATION_ONLY_RESUME) ⊆ artifacts(CORRECTION_RESUME)` for
  every shape.
- `test_validation_only_resume_is_never_selected_at_runtime`.
- manifest exhaustiveness; content-refusal parity with `skills.py`.

Real disposable integration:

- **deliberately oversized future resume refuses the INITIAL dispatch** — a
  temporary manifest whose `CORRECTION_RESUME` exceeds the ceiling; the call
  returns `LifecycleInfeasible`, **no task directory is created**, no worktree
  exists, and no worker binary ran (asserted by a fake binary that writes a
  marker file when executed);
- **high/high dispatch fits and resume also fits** — the positive control, so the
  refusal test cannot pass by refusing everything;
- **resume refusal leaves `state.json` byte-identical**, sha256 compared, once
  per PREPARE refusal class including `ResumeNotPermittedFromState`;
- **source hash drift invalidates the projection** — a **copy** of the pinned
  install root in `tmp_path` with one source byte changed; the real install root
  is never written;
- planning omitted from correction resume; no redundant full code-review +
  receiving-review pair — asserted **by artifact id**, not by byte count;
- all four phases proven before the first worker, read from the persisted report;
- `max_resume_count == 0` excludes both resume phases as `unreachable`.

Structural: the `_record_failure` reflection test and the phase tests of §3.1.8.

**COULD THE MATRIX PASS WHILE THE PROPERTY IS FALSE?** Yes, in two ways, both
closed. (1) Composed against a fixture's ~0 B guidance while production is
~42 KB — the B2-shim shape; closed by §9.2A's cap-parameterisation. (2) On a host
whose `~/.claude` plugin cache differs, hash verification raises rather than
measuring; the test then **skips with an explicit `NOT-MEASURED` marker naming
the drifted skill id**, which is never counted as a pass and blocks gate signing.
It does **not** skip hash verification — the tempting answer, and exactly the
property that must not be weakened.

### 4.11 Mutation cases

| # | Mutant | Named targeted killer |
|---|---|---|
| 1 | resume profile adds full planning again | `test_correction_resume_excludes_planning_artifact` **(targeted)**; the 120×2 matrix (additional) |
| 2 | resume profile adds the overlapping review skill again | `test_correction_resume_has_no_redundant_review_pair` **(targeted)**; the matrix (additional) |
| 3 | skip lifecycle future-phase preflight | `test_oversized_future_resume_refuses_initial_dispatch` |
| 4 | move preflight after the `RUNNING` transition | `test_resume_refusal_leaves_state_byte_identical` |
| **A-d′** | **compose the feasibility check from per-component sums instead of measuring the composed payload** | `test_dispatcher_authored_growth_is_caught_by_composed_check` — grows the dispatcher-authored text past its 8,192 B reserve, where the component sums still pass and only the composed measurement fails |
| A-e | accept a drifted source hash and recompute | `test_source_hash_drift_invalidates_projection` |
| A-f | make profile selection read the resume instruction text | `test_profile_selection_is_pure` |
| A-g | prove resume phases for a `max_resume_count == 0` task | `test_unreachable_phases_are_excluded` |
| A-h | select `VALIDATION_ONLY_RESUME` at runtime | `test_validation_only_resume_is_never_selected_at_runtime` |
| A-i | compose the matrix against a fixture's guidance size | `test_matrix_is_parameterised_by_the_guidance_cap` |

> **Revision 2's mutant `A-d` is DELETED, not weakened, and it is deleted HERE —
> in the table the Wave A implementer works from.** Revision 2 deleted it in its
> §11.2 and left it alive in its §4.11, which is precisely how a mutant Sol
> ordered deleted gets built and survives. A-d claimed *"measure per-component
> sums instead of the composed payload"* killed by *"a shape whose components
> each fit and whose composition does not"* — and Lane W measured that **under
> the shipped config no such shape can exist**: `config.py:596-640` refuses any
> configuration where `skills_cap + guidance_cap + 8192 > 122,880`, and the
> shipped values are 72,000 + 42,000 + 8,192 = 122,192, so **the skills cap is
> strictly the binding gate**. A-d was an equivalent mutant by construction. The
> equivalence proof is recorded in `scripts/mutation/README.md` as §31 requires,
> and A-d′ above is its killable replacement.

### 4.12 Production activation — the runtime refuses (directive N, fixes N-a)

Revision 2's D-14 claimed *"Gate 7 PASS: impossible while the canonical
production configuration bypasses lifecycle profiles"*, enforced by *"the
activation checker gains a check"*. Measured, that is **stated, not enforced**:

- `config/dispatcher.toml` is **gitignored (`.gitignore:26`)** and host-local. **No
  test in `tests/**` can assert its contents.**
- `check-production-activation.py` **requires** `--expect active|inert`, has no
  default, and its own docstring says it *"never infers what the state ought to
  be … Guessing the expectation would make the check unfalsifiable."*
  **`--expect inert` passes with lifecycle disabled**, and nothing forces
  `--expect active` to be the invocation that signs the gate.
- Revision 2's §13 contradicted itself two rows apart (`ships true` vs
  `default off`), and its §4.4 still said *"a dispatcher configured exactly as
  today behaves exactly as today."*

**DECISION D-14 (revision 3): the registered production entrypoint refuses to
start.** Built on B4's existing production/development split, which already draws
the line exactly where this needs it.

```python
# config_authority.py — the module that already owns "what production may run".
def production_activation_defects(config: Config) -> tuple[str, ...]:
    """Return the reasons this configuration is not production-active. PURE."""

def assert_production_activation(config: Config) -> None:
    if production_activation_defects(config):
        raise ProductionActivationDisabled(...)      # typed, retryable=False
```

```python
def main() -> None:                                   # server.py
    try:
        canonical = assert_production_config_authority()   # B4, unchanged
        config    = load_config(canonical)
        assert_production_activation(config)               # <<< NEW
        server    = build_server(canonical)
    except DispatcherError as exc:
        print(json.dumps(exc.to_payload()), file=sys.stderr)
        raise SystemExit(2) from exc
    asyncio.run(server.run_stdio_async())
```

The refusal is B4's proven shape: **typed payload to stderr, `SystemExit(2)`,
stdout untouched, no `MCPServer` constructed, no `initialize` possible.**

| Invariant | Statement |
|---|---|
| **Z-I11** | The registered production entrypoint **fails startup**, before the transport opens, if lifecycle or preflight are disabled. |
| **Z-I12** | **Absence is refusal.** A canonical config with no `[lifecycle]` section is refused. **There is no production default.** |
| **Z-I13** | Opt-out is explicit, **on argv, non-production**: `dev_server <config> --allow-inert-lifecycle`. **Never an environment variable** — that would reconstruct exactly the defect B4 closed. |
| **Z-I14** | Gate 7 PASS requires **runtime evidence** under an unmodified environment and **no operator-supplied expectation flag**. |

**`build_server(path)` does NOT enforce.** It is the library API 1,368 existing
tests use. **Enforcement is a property of the entrypoint, not of the library, and
this design says so rather than implying otherwise.** The gap is closed from the
other side: B4's `TestRegistrationSurface` already asserts `[project.scripts]`
has exactly one entry and it is `server:main`; revision 3 adds an AST assertion
that `server.main` calls `assert_production_activation` on every path.

**The repository-visible artefact (Y-8).** `config/dispatcher.example.toml` **is
tracked** and gains `[lifecycle] enabled = true`, `preflight_required = true`. A
test loads it through the real `load_config` and asserts
`production_activation_defects(...) == ()`. **This is the shipped default made
assertible in `tests/**`, which the gitignored canonical file can never be.**

#### The proof chain — each conjunct independently falsifiable

| # | Conjunct | Proven by | Mutant |
|---|---|---|---|
| 1 | the predicate returns non-empty for every inert shape | `test_activation_predicate_table` (missing section, `enabled=false`, `preflight_required=false`, both, neither) | Z-M21 |
| 2 | `server.main` calls it on every path | `test_production_main_asserts_activation` (AST: the call dominates every route to `build_server`) | Z-M22 |
| 3 | the call happens **before the transport opens** | `test_production_entrypoint_refuses_inert_before_stdout` — live subprocess: **stdout empty**, payload on stderr, exit 2 | Z-M23 |
| 4 | `main` loads the canonical config and nothing else | B4's existing `TestProductionRefusesRedirection`, unchanged | B4 M1–M5 |
| 5 | the registered console script **is** `server:main` | B4's `TestRegistrationSurface` | Z-M24 |
| 6 | `main` reads no argv, so `--allow-inert-lifecycle` cannot reach production | `test_production_entrypoint_takes_no_argv` (live: pass the flag; still refuses) + AST | Z-M25 |
| 7 | the shipped example config is production-active | `test_example_config_ships_lifecycle_active` | Z-M26 |

**The end-to-end negative control that does not touch production.**
`canonical_production_config_path()` is derived from
`Path(__file__).resolve().parents[2]`, so **a copy of the package tree in
`tmp_path` has its own canonical path.** The live test copies `src/` and a
`config/dispatcher.toml` carrying `enabled = false` into `tmp_path`, runs the
**real `server.main()`** as a real subprocess with `cwd` and `sys.path` in that
tree, and asserts exit 2, stdout empty, stderr carrying
`ProductionActivationDisabled`. **Zero risk to the canonical config, the
production repository, `~/.codex` or `~/.claude`.**

**COULD THE WHOLE CHAIN PASS WHILE THE PROPERTY IS FALSE?** Yes, in exactly one
way, and it is the residual B4 already records honestly: **an operator who edits
`~/.codex/config.toml` to register a different command, or replaces the installed
package, is running something other than the registered production entrypoint.**
The honest claim is therefore *"the registered production entrypoint refuses to
start inert"* — **not** *"production cannot run inert"*. §16's report row uses
the first sentence, and `docs/SECURITY.md` gains the same qualification.

`check-production-activation.py` is **demoted, not deleted**: it keeps `--expect`
and keeps refusing to infer — that property is correct and must not be weakened —
and becomes a host-state corroborator that §16 labels as such.

### 4.13 Backward compatibility

- **A production host that upgrades to Wave A without editing
  `config/dispatcher.toml` will not start.** It refuses with a typed payload
  naming the exact edit. **Deliberate and fail-closed**: the alternative is a
  production dispatcher silently bypassing the fix Gate 7 exists to deliver.
- **There is no production default and no in-production rollback lever.**
  Revision 2's *"the flag remains only as a rollback lever"* is **deleted**;
  rolling back means reverting code or running `dev_server`. **Escalated as
  Z3-AMB-3 (§18.3).**
- **Revision 2's §4.4 sentence *"a dispatcher configured exactly as today behaves
  exactly as today"* is deleted.** After Wave A it is false for the production
  entrypoint, which is the point.
- Existing `state.json` / `envelope.json` load unchanged; `SCHEMA_VERSION` does
  not bump.
- A task dispatched with lifecycle off and resumed with it on is a
  `LifecycleProfileChanged` PREPARE refusal — a one-time migration condition,
  returned to Sol rather than silently resumed under different methodology.
- `dev_server`, `build_server(path)`, `load_config(path)` and all 1,368 existing
  tests are unaffected.

---

## 5. SUBSYSTEM B — Evidence authority and the run transaction

Covers **G7-2** and **G7-7**, and absorbs directives **A, B, C, D, E, F, K, M, O**.

They are one subsystem because they share a consumer: `evidence/diff.patch` and
`runs/NNN/` are the two artefacts a reader treats as authoritative, and both are
currently produced by code that can be wrong without saying so — or, worse, by
code the worker controls.

### 5.1 Current failure — evidence

**G7-2 as briefed.** `collect_diff_evidence` (`git.py:660`) folds untracked paths
into `changed_paths` via `ls-files --others --exclude-standard`, but `diff_text`,
`diff_stat`, `diff_total_bytes` and `diff_check_passed` all come from
`git diff <base>`, which cannot see an untracked file. `_write_evidence`
(`server.py:2431`) sets `diff_patch_complete = True` on the sole basis that
`write_full_diff` did not raise. Fable reads that file.

**V-1 — the evidence pipeline honours worker-controlled attributes and config.**
Lane X enumerated 13 mechanisms by which a dispatcher git command executes a
worker-chosen program. Revision 2 answered with an argv policy and a fingerprint,
and closed the one vector with **no argv lever** — `filter.*` — *by inference*:

> *"This is closed by layer 3 (the clean index and the base attribute source
> together mean no filter is selected) plus layer 2's detection."*

**That sentence is false in two independent ways, both now measured twice** (Lane
Y S-1, reproduced independently by Lane Z1 in under fifteen minutes without
reading Lane Y's script):

1. **A filter is selected by an attribute, not by an index entry.** `read-tree`
   into a throwaway `GIT_INDEX_FILE` changes nothing about which attribute
   applies.
2. **`--attr-source=<base>` *selects* attributes from a different source; it does
   not suppress them** — and Lane X's own E4, quoted approvingly by revision 2,
   already measured that it does not reach `$GIT_COMMON_DIR/info/attributes` at
   all: a plain file the `Write` tool reaches, in the `.git` a dispatcher-created
   linked worktree **shares with the primary repository**.

Measured, under revision 2's *complete* hardening — `--attr-source=$BASE`,
`--no-textconv`, `--no-ext-diff`, `--text`, `core.attributesFile=/dev/null`, the
clean `GIT_INDEX_FILE` — with the "worker" using only the `Write` tool:

```
FIRED   REV2-hardened-diff    -> FIRED:REV2-hardened-diff:clean
FIRED   REV2-hardened-status  -> FIRED:REV2-hardened-status:clean
FIRED   plain-diff            -> FIRED:plain-diff:clean
clean   ls-tree
clean   cat-file-blob
clean   rev-parse
```

The consequence is **arbitrary code execution as the dispatcher process, with the
dispatcher's privileges, after the worker exited, against the primary
repository** — and revision 2's §8 ordering guarantees it happens **before** the
row that would report it (row 3 = inventory, row 4 = tamper verdict).

Two further failures follow from the *framing* rather than any flag. **The
enumeration is version-scoped** — Lane X's "NOT exploitable" list is explicitly
contingent on git 2.43.0 and on the current command repertoire, so a git upgrade
re-opens the question with no signal that it did. And **detection is downstream
of execution**: the pre-run fingerprint is written 0600 as the same uid the
worker's dispatcher-invoked program runs as, so a program that runs during
evidence collection can rewrite the stored pre-state until `post == pre` holds.

**And `diff --name-only -z` — revision 2's own authoritative tracked-path
source — fires the filter.** Measured independently by Z1 (M-22) and Z3. So
under revision 2's producer, **Wave 0's own inventory command is a Tier-0
execution vector, ordered by §8 before the row that would report it.**

**V-2 — a live scope-enforcement bypass.** Running the **real** `check_scope`
against the **real** quoted path:

```
path: '"secrets/caf\303\251.txt"'
forbidden_paths=['secrets/**'], allowed_paths=[]   ->  valid=True   <-- BYPASS
control 'secrets/cafe.txt'                          ->  valid=False, forbidden=[…]
```

`ScopeSpec.allowed_paths` defaults to empty = unrestricted, so **for any task
that expresses its boundary as `forbidden_paths` only** — which is exactly how
one says "do not touch `secrets/`, `infra/`, `.github/`" — a worker writing a
non-ASCII filename inside a forbidden path is reported `valid=True`. It affects
**tracked** paths identically (`diff --name-only` C-quotes the same way).
Revision 1's newline sub-claim was **wrong** — C-quoting escapes a newline to a
literal `\n` — and is retracted; the real reason `-z` is required is that
`core.quotePath=false` **keeps newline separation** and is therefore strictly
weaker.

**V-4 — index bits erase a change from EVERY surface.** `git update-index` is not
denied and no deny prefix reaches it. Verified through the **real dispatcher
code**:

| | `changed_paths` | `status` | `--stat` | patch bytes | `--check` | scope |
|---|---|---|---|---|---|---|
| `--assume-unchanged <f>` | **gone** | empty | empty | **0** | exit 0 | **`valid=True`** |
| `--skip-worktree <f>` | **gone** | empty | empty | **0** | exit 0 | **`valid=True`** |
| assume-unchanged then `rm <f>` | **gone** | empty | empty | **0** | exit 0 | a tracked **deletion** vanishes entirely |

Strictly worse than the `.gitattributes` vector: `-diff` at least leaves
` M <file>` in `changed_paths`; the index bits erase the file from every surface
at once. **And it reaches the primary tree** via `git -C <primary>`, which is not
denied either — blinding `primary_tree_status` and `compare_primary_tree`.

**V-5 — a self-hiding `.gitignore`, using the `Write` tool alone.** POST:
`changed_paths=[]`, `status` empty, `scope.valid=True`. **No git subcommand is
involved**, so no command-level deny can ever catch it.
`$GIT_COMMON_DIR/info/exclude` does the same and additionally blinds the primary
tree; `core.excludesFile` does it through the shared config.

**Z1-N1 — the PREPARE checkout executes a previous task's program.** New in
revision 3, and not in Lane X's matrix in this form:

| Invocation | smudge filter | `post-checkout` hook |
|---|---|---|
| `git worktree add` | **fires** | **fires** |
| `git -c core.hooksPath=<empty> -c core.fsmonitor=false worktree add` | **STILL FIRES** — the created file contained `SMUDGED:payload\r\n` | suppressed |
| `git worktree add --no-checkout` | **does not fire** | **does not fire** |

**Revision 2's argv policy does not close the PREPARE checkout.** A worker from
task N poisons `filter.*`; the dispatcher for task N+1 runs `git worktree add`;
the checkout executes task N's program, in PREPARE, before task N+1's worker
exists.

**Z1-N2 — revision 2 re-created the R-4 laundering hole.** Revision 2 put
`PathInventoryUnrepresentable` at §8 **row 3**, above the policy rows, reasoning
that *"without a trustworthy inventory there is nothing to decide policy on"*.
So: **a worker writes into `secrets/` and creates one file with a non-UTF-8 name;
the run lands `FAILED` at row 3 and the scope verdict is never computed. One
`Write` call downgrades `POLICY_VIOLATION` to `FAILED`.** Neither review named
it; it is the same shape as R-4 and R-13.

**V-3 (latent).** `git diff --no-index --check` exits **3**, outside
`_git_checked`'s `ok_returncodes=(0,1,2)`. Under directive A `--no-index` is never
used, so the hazard is **gone by deletion** rather than by widening a tuple.

### 5.2 Current failure — run transaction (G7-7)

```
server.py:941    run_index = record.run_count + 1        # derived, not allocated
server.py:1031   invocation = self._with_run_spools(...)  # -> mkdir runs/NNN
server.py:2204   self.store.append_run(...)               # -> run_count = max(...)
```

Between them lies the entire worker run, evidence collection and validation. Any
failure in that window leaves `runs/NNN/` populated with real streams while
`run_count` still reads `N-1`; the next run computes `N` again, `exist_ok=True`
accepts the existing directory, and the spools are **truncated and overwritten**
(`O_TRUNC`, `runner.py:1304`). `server.py:1346` re-reads the record under the
lock specifically because `run_count + 1` would otherwise be stale — a
description of the defect, worked around in one place out of three.

### 5.3 New invariants

**Evidence authority**

- **ZI-1 (EVIDENCE AUTHORITY).** *No git command that renders, formats, filters,
  transforms or **presents** repository content may be used to decide or generate
  authoritative evidence at any point after the worker has been launched.*
  **This applies identically to task-worktree evidence and to primary-tree
  non-interference evidence.** There is no "it is only the primary tree"
  exemption: the primary tree is the more valuable target.
- **ZI-2 (NO SECOND SOURCE).** There is exactly **one** completeness source.
  `diff.patch`, `diff_stat`, `diff_total_bytes`, `diff_check`, `changed_paths`
  and the Fable prompt are all generated by dispatcher-native code from **one**
  canonical content representation. **No git-derived value corroborates,
  cross-checks or supplements any of them.** A second source is not defence in
  depth here; it is a second thing to be lied to — and revision 2's
  *"corroborating, not authoritative"* `git diff --check` is exactly that.
- **ZI-3.** The changed-path measurement **consults no ignore source at any
  point**. It is the difference between two dispatcher-owned filesystem
  snapshots.
- **ZI-4.** Ignore rules **classify** paths already in the inventory, never
  suppress them, and only rules **committed in the base tree** are consulted.
- **ZI-5.** **No path enters `changed_paths` merely because it exists.** A path
  enters iff it *changed*.
- **ZI-6 (path model).** A repository-relative path is `bytes`, from the syscall
  or from `ls-tree -z`, all the way to `check_scope`. **No `str` on the
  enforcement path, and no C-quoted display form is ever produced on it.**
- **ZI-7.** Paths are produced by exactly **two** mechanisms: the `FsSnapshot`
  walk and `ls-tree -r -z --long`. **Nothing** parses a path out of `--stat`,
  `--check`, a patch header or a status line. The canonical patch is *generated
  from* the inventory; it is never read back into one.
- **ZI-8 (precedence).** `authoritative path inventory → scope verdict → content
  evidence`. An out-of-scope path lands `POLICY_VIOLATION` **even if its content
  is unsupported**.
- **ZI-9 (no content channel into policy).** No `ContentClass`, no `lstat` result
  and no read byte can reach `check_scope` or `ScopeVerdict`.
- **ZI-10 (refusals are per-path facts).** A per-path refusal is never a run
  outcome and never removes a path from the inventory.
- **ZI-11/12/13/14** — production activation, §4.12.
- **ZI-15/16/17** — Fable input is never clipped, §5.11.
- **ZI-18 (admin capture) — RESTATED so it is achievable (N-5).** The
  repository's security-relevant administrative state is captured with **plain
  file I/O only**, and that capture happens **before any git command that could
  execute a repository-supplied program** — in particular before `worktree add`,
  and before anything that reads the working tree, refreshes the index, or
  mutates a ref. *Revision 3 said "before `rev-parse`, before any git process is
  created at all", and that was **not achievable**:
  `security.validate_repository_root` (`security.py:217`) and the lock digest
  (`locks.py:72`) both run `rev-parse --show-toplevel` to establish repository
  identity before anything else, and the capture itself is keyed on `<gitdir>` /
  `$GIT_COMMON_DIR`, which revision 3 obtained from `rev-parse
  --absolute-git-dir`. An implementer could not have satisfied it as written.*
  **The `rev-parse` variants that may precede the capture are measured clean on
  all three armed surfaces (§5.4.3), and the capture prefers a raw resolver over
  even those (§5.8.2A).**
- **ZI-19 (index irrelevance).** Worker-controlled index state has **no authority
  over evidence**. The evidence pipeline never reads the index, never writes one,
  and **never creates a temporary one**. `assume-unchanged` and `skip-worktree`
  are therefore *structurally irrelevant* rather than defeated.
- **ZI-20 — RESTATED (N-5).** A dispatch whose administrative state does not
  match the recorded trusted baseline **refuses in PREPARE**, and **the refusal
  path runs no git command beyond the identity resolution needed to locate the
  repository at all** — the raw resolver of §5.8.2A where it succeeds, and at
  most `rev-parse --show-toplevel` / `--absolute-git-dir` / `--git-common-dir`
  where it does not. **No presentation command, no `worktree add`, no ref
  mutation, and nothing that could execute a repository-supplied program.**
- **ZI-21 (primary tree).** `post_primary_state == pre_primary_state` is measured
  by dispatcher-owned raw filesystem code and raw ref reads. **No git command
  participates, before or after the worker.**

**Completeness and the run transaction**

- **B-I2 (produced, not asserted).** Every completeness flag is computed by the
  component that produced the artefact, from its own accounting. **No caller may
  set one.**
- **B-I3 (bucket, never run-fatal).** Every changed path lands in exactly one
  bucket; a per-path refusal never prevents the inventory, and therefore never
  prevents the scope and primary-tree verdicts, from being produced.
- **B-I5 (no index mutation).** The task worktree's index is never written.
  `git add -N` is not used. **No temporary index is created either** (ZI-19).
- **B-I7 (two flags).** `patch_file_complete` describes the file on disk;
  `review_input_complete` describes what the reviewer will actually *receive*.
  The review is gated on **both**.
- **B-I8/9/10.** Run identity is allocated by `reserve_run()`; a reservation owns
  `runs/NNN`, its `run_id` and its `run_index` permanently; allocation is
  monotone across crash and restart.
- **B-I11 (never erase).** A failed run is never deleted, decremented or
  renumbered.
- **B-I12 (idempotent landing).** A run whose evidence is complete but whose task
  state was never applied is completable, deterministically and idempotently, by
  a restarted dispatcher.

### 5.3A Three separated concerns, in a fixed order (directive M)

Revision 1 fused path inventory, scope enforcement and content generation into
one component and one failure mode, so *unsupported untracked file → FAILED*
ranked **above** *scope violation → POLICY_VIOLATION*. Revision 2 fixed the
ordering and the second review confirmed the fix is sound. **Revision 3 changes
nothing about the ordering; it makes the ordering structurally impossible to
violate**, and it removes the two ways revision 2 could still be laundered
(Z1-N2, and content classification touching `lstat` too early).

```
 1. IDENTITY   ──►  PathIdentitySet     cannot fail on file content or type.
    (§5.5, §5.7)     (authoritative)    NO lstat. NO open(). NO content byte.
                                        A symlink, a FIFO, a 70 KB name and an
                                        unreadable file are PATHS like any other.
                          │
                          ▼
 2. POLICY     ──►  ScopeVerdict        decided over the frozen identity set,
    (§8 rows 4,5)    + primary verdict  ALWAYS, for every run that produced one.
                          │
                          ▼
 3. CLASSIFY   ──►  ClassifiedInventory lstat happens HERE and only here.
    (§5.5.5)         + ContentClass     May bucket a path. NEVER removes one.
                          │
                          ▼
 4. CONTENT    ──►  CanonicalEvidence   authoritative bytes only. NO git diff.
    (§5.5.7)
```

**Why it cannot be reordered by accident:** `ClassifiedInventory` requires a
`ScopeVerdict` **as a required constructor argument**. There is no expression in
the codebase that produces a `ContentClass` before a `ScopeVerdict` exists. A
mutant that reorders must change a dataclass signature — which an AST test
asserts and the diff shows.

**PROVEN BY** — `test_classification_cannot_be_constructed_without_a_verdict`
(reflection: the argument is required and positional) **and**
`test_no_lstat_before_the_scope_verdict` (dynamic: monkeypatch `os.lstat`,
`os.stat` and `open` to raise, run stages 1–2, assert the verdict is still
produced). **COULD EITHER PASS WHILE FALSE?** The reflection test could, if the
ordering were violated through a second construction path — which the dynamic
test cannot miss, because the syscalls themselves raise. **This is the pair: a
structural test that is cheap and a dynamic test that cannot be fooled.**

Consequences, each of which reverses a revision-1 or revision-2 position:

- **A symlink / oversized / unsupported / non-UTF-8-named path that is OUT OF
  SCOPE still lands `POLICY_VIOLATION`,** on its authoritative path.
- **A benign symlink no longer fails an otherwise complete run.**
- **`EvidenceUnsupportedFile` is not an exception.** It is a per-path reason
  string. Revision 1's §5.8, which made it fatal, is deleted.
- **`PathIdentityUnrepresentable` moves from row 3 to row 5a** (§5.7.4, §8), so
  it can no longer preempt a boundary breach.

### 5.4 Directive A — post-worker git presentation commands are not evidence authority

#### 5.4.1 THREE independent execution surfaces, and a command is safe only if measured against ALL THREE

This is the most important correction the design makes, and **revision 3 got the
count wrong** — which is itself the lesson, so it is recorded rather than
quietly amended.

| Surface | Selected by | Triggered by |
|---|---|---|
| **S-α — attribute-selected content transform** | an *attribute* (`filter=`, `diff=`, `-diff`, `working-tree-encoding`) resolved from `.gitattributes`, `info/attributes` or `core.attributesFile`, plus a config-defined driver | any command that **reads working-tree content through git's content pipeline** |
| **S-β — index refresh** | the `core.fsmonitor` key **alone; no attribute is needed** | any command that **refreshes the index**, whether or not it reads content |
| **S-γ — ref update** *(NEW in revision 4)* | **no attribute and no index refresh** — the hook `$GIT_COMMON_DIR/hooks/reference-transaction` (also `post-checkout`, `post-index-change`, `pre-auto-gc`, and any dir named by `core.hooksPath`) | any command that **creates, moves or deletes a ref** |

`git ls-files --others` reads no content, so it is clean on S-α — and it
refreshes the index, so it **executes the worker's program on S-β**.
**`git worktree add` creates a branch ref, so it executes the worker's program on
S-γ — even with `--no-checkout`, which revision 3 annotated `# executes
NOTHING`.**

> **S-γ was found because revision 3's own Appendix A.2 armed smudge,
> `post-checkout` and `fsmonitor` and never armed `reference-transaction`. Its
> `no-checkout log: []` was therefore a negative result from an experiment that
> could not have produced a positive one — the exact hazard this document records
> in reconciliation 4 and §10.4 about somebody else's probe.** It is the fourth
> occurrence of that pattern in this gate and **the first inside this document's
> own measured appendix.** Z1's honest caveat — *"S-α and S-β are the two surfaces
> I know about, not the two that exist"* — is now **demonstrated true rather than
> conceded**, and §18.5's attack item 1 is answered **yes**.

**What survives and what does not.** The repertoire's **conclusion** survives:
all three permitted commands are measured **clean on S-γ**, because none of them
updates a ref. Its **method** does not: "measured against BOTH" was the rule, and
two was the wrong number.

> **Only three commands are measured clean on ALL THREE surfaces:
> `ls-tree -r -z --long`, `cat-file` (bare), and `rev-parse`.**

**A fourth surface may exist.** The design does not claim otherwise. What it
claims is that the permitted set is **object-store reads and ref resolution**,
which touch neither the working tree, nor the index, nor any ref *mutation* — a
structural property rather than a per-key enumeration. **That argument is why the
set is expected to survive a git upgrade; the measurements are why it is believed
today; and Z-RULE-1 requires both to be re-run as tests with positive controls
whenever git moves.**

#### 5.4.2 The prohibited set, by name and by class

| Prohibited after worker launch | S-α filter | S-β fsmonitor |
|---|---|---|
| `git status` (any form, including `--porcelain -z`) | **FIRES** | **FIRES** |
| `git diff` (any form) | **FIRES** | **FIRES** |
| **`git diff --name-only -z <base>`** — revision 2's authoritative source | **FIRES** | **FIRES** |
| `git diff --check` | a diff; also silenceable by `-diff` | a diff |
| `git diff --stat` | a diff; also C-quotes, no `-z` | a diff |
| `git ls-files --others [-z] [--exclude-standard]` | clean | **FIRES** |
| `git ls-files -v` | clean | **FIRES** |
| `git cat-file --filters`, `--textconv` | **FIRES** | — |
| `git check-attr`, `git check-ignore` | consult worker-writable sources **by design** | — |
| any attribute-selected transform | textconv, external diff, clean/smudge/process, `ident`, `working-tree-encoding` | — |
| any command that refreshes or writes **the worktree's** index | — | the refresh **is** the trigger. `read-tree` into an external `GIT_INDEX_FILE` is **not** this — see §5.4.3 (N-2). |

#### 5.4.3 The permitted repertoire — exhaustive; widening it is a Sol decision

| Command | Phase | Purpose | S-α | S-β | S-γ |
|---|---|---|---|---|---|
| `rev-parse --verify <ref>^{commit}` | PREPARE **and FINALIZE** (B2, §5.5.2) | resolve the base SHA; verify the worktree head | clean | clean | clean |
| `rev-parse --show-toplevel` | PREPARE | repository identity / lock digest (`security.py:217`, `locks.py:72`) | clean | clean | clean |
| `rev-parse --absolute-git-dir` / `--git-common-dir` | PREPARE | gitdir identity for §5.8 | **clean** | **clean** | **clean** |
| `rev-parse --is-inside-work-tree` | PREPARE | `git.is_git_repository` (`git.py:248`) | **clean** | **clean** | **clean** |
| `ls-tree -r -z --long <base>` | PREPARE | `BaseTreeSnapshot` | clean | clean | clean |
| `cat-file --batch` **fed object ids** (never `--filters`, never `--textconv`) | PREPARE for a bounded set; **lazily at FINALIZE** | raw blob contents | clean | clean | clean |
| `cat-file blob <oid>` | same | single raw blob | clean | clean | clean |
| `rev-list --max-parents=0 HEAD` | PREPARE | repository root-commit pin (`git.py:363`) | **clean** | **clean** | **clean** |
| `config --get remote.origin.url` | PREPARE | repository identity pin (`git.py:359`) | **clean** | **clean** | **clean** |
| `worktree list --porcelain` | PREPARE | registration facts, B2 | **clean** | **clean** | **clean** |
| `read-tree <base>` with an **external `GIT_INDEX_FILE`** | PREPARE, `dispatcher_raw` only (§5.5.5) | populate a throwaway index | **clean** | **clean** | **clean** |
| `worktree add` | PREPARE, once per task, **only after §5.8's preflight passes** | create the isolated tree | **FIRES smudge** | **FIRES** | **FIRES `reference-transaction`** |

**Four rows changed status in revision 4.** `--absolute-git-dir`,
`--git-common-dir` and `worktree list --porcelain` move from `REQUIRES-PROBE` to
**permitted**, measured clean on all three surfaces with a positive control.
Three rows are **new because the code already used them and no revision listed
them** — `rev-parse --is-inside-work-tree`, `rev-list --max-parents=0` and
`config --get remote.origin.url`, all measured clean on all three. The repertoire
was described as *exhaustive* while three live call sites sat outside it; **that
is now true rather than aspirational**, and `test_git_repertoire_is_exactly_the_permitted_set`
is what makes it stay true.

> **`config --get` is permitted here and prohibited in §5.8.2, and both are
> correct.** §5.8.2's rule is that the **administrative capture** must use plain
> file I/O and never ask git what the configuration says — because that capture
> is the thing that decides whether the configuration is trusted. The identity
> producer's single `config --get remote.origin.url` is a different question
> asked at a different time, of a repository whose administrative state §5.8 has
> **already reconciled**. §5.8.2's sentence is narrowed to say *"the capture runs
> no git command"* rather than *"no `git config`"*, and a test asserts the
> capture's own journal window is empty.

> **`read-tree` is permitted here and prohibited by §5.4.2's final row, and that
> contradiction is resolved rather than left standing** (N-2). §5.4.2's row is
> narrowed from *"any command that refreshes or writes the index"* to **"any
> command that refreshes or writes THE WORKTREE'S index"**. `read-tree` into an
> **external `GIT_INDEX_FILE`** touches no worktree index, is measured clean on
> all three surfaces, and appears only in `dispatcher_raw` materialisation. B-I5
> is unaffected: the *task worktree's* index is still never written, and the
> temporary index is a dispatcher-owned file. **A `read-tree` without an external
> `GIT_INDEX_FILE` remains prohibited**, and `ZM-E7`'s killer catches its return.

**Everything else is removed from the dispatcher.** `git status`, `git diff` in
all forms, `git ls-files` in all forms, `git diff --check`, `git diff --stat`
disappear from `src/**`. **This is a deletion, not a hardening.**

**Why the permitted set is exec-safe, as a mechanism rather than a list.**
`ls-tree` and bare `cat-file` read the **object database** and never touch the
working tree or the index; `rev-parse` resolves refs. None refreshes the index
(which is what arms `core.fsmonitor`); none applies attributes (which is what
selects `filter.*`, `diff.*.textconv`, `diff.*.command`). That is a **structural**
property of object-store reads rather than a per-key enumeration, which is why it
is expected to survive a git upgrade where Lane X's "NOT-exploitable" list will
not. **It is still measured, not assumed**, and Z-RULE-1 requires the measurement
to exist as a test with a positive control, not as this paragraph.

**Three commands are carried as `REQUIRES-PROBE`, not as permitted**, until armed
against both surfaces. Z1's own words: *"'I expect it for the same structural
reason' is exactly the sentence this gate exists to distrust."*

#### 5.4.4 `git.py` splits

```
git.py            ONLY the permitted invocations, each a named function.
                  `_run_git` keeps the single-chokepoint role and gains the
                  argv/env policy. collect_diff_evidence, write_full_diff,
                  primary_tree_status and _fold_untracked are DELETED —
                  not wrapped, not deprecated. DELETED.
evidence/
  basetree.py     BaseTreeSnapshot          (ls-tree + lazy cat-file)
  fssnap.py       FsSnapshot                (dispatcher-owned lstat/readlink/hash)
  reconcile.py    BaseReconciliation
  inventory.py    PathIdentitySet, ScopeVerdict, ClassifiedInventory   [WAVE 0]
  ignore.py       base-committed ignore matcher (classification only)
  patch.py        dispatcher-native unified diff, stat, check
  gitadmin.py     raw administrative capture + reconciliation
```

**OQ-B4 is decided: NO compatibility wrappers.** Revision 2 asked whether to keep
`collect_diff_evidence` / `write_full_diff`. **No.** A retained wrapper is a live
`git diff` call site that a future edit can reach, and the whole of directive A is
that no such call site may exist. `DiffEvidence` keeps its **name and every field
name**, so `results.build_dispatcher_observations` and `DispatcherObservations`
are unchanged; it is now produced by `evidence/patch.py` from `CanonicalEvidence`,
and `porcelain_status` becomes a **dispatcher-rendered** status text whose
docstring says so.

#### 5.4.5 The auditable journal

```
state/tasks/<id>/runs/NNN/git-invocations.jsonl     NEW, append-only
  {"ts":…, "phase":"PREPARE"|"FINALIZE", "subcommand":"ls-tree",
   "argv_sha256":"…", "cwd_role":"primary"|"task_worktree",
   "permitted_by":"repertoire row 4", "returncode":0, "duration_ms":12}
```

Every call through `_run_git` appends one record.

> **The FINALIZE phase must contain only `cat-file` and `rev-parse` rows — and
> the `rev-parse` rows must be exactly the B2 base check (`--verify
> HEAD^{commit}`, `cwd_role == "task_worktree"`).**

That is a decidable post-condition an integration test asserts directly, and it
is the one check that survives a refactor which bypasses the AST tests.

**The set is TWO commands, not one, and the second is load-bearing.** B2's
post-worker verification is a §2 non-regression: a worker has Bash and its own
git, and if HEAD moved during the run **every measurement below it would describe
a tree that never existed** (`server.py:1995-2002`). The permitted FINALIZE set
is therefore `{cat-file, rev-parse}`, with the `rev-parse` variant **pinned to one
argv**, so it remains a closed set rather than an allowlist a mutant can extend.

**PROVEN BY** `test_finalize_journal_is_catfile_and_b2_revparse_only`, which
asserts (i) every FINALIZE row's `subcommand` is in `{cat-file, rev-parse}`,
(ii) every `rev-parse` row's `argv_sha256` equals the single canonical B2 argv
hash, and (iii) **the count of `rev-parse` rows equals the number of
`_verify_worktree_base` calls the run made**, read from a seam counter.
**COULD IT PASS WHILE FALSE?** Not for a presentation command, and not for a
second `rev-parse` variant — (ii) and (iii) close the widening a bare membership
test would allow. It still cannot see a call that bypasses `_run_git`, which is
what the audit-hook test is for. **IF MIS-WIRED** — a new post-worker git call
appears in the journal and the test fails; the only route to green is to edit the
pinned argv hash or the seam counter, **both visible in the diff**.

#### 5.4.6 Tests — and whether each could pass while the property is false

| Test | Proves | Could it pass while false? |
|---|---|---|
| `test_git_repertoire_is_exactly_the_permitted_set` (AST) | the source names no other subcommand | **YES** — an `os.system`, a `subprocess.run` outside `_run_git`, or a subcommand built from a variable defeats it. **Not sufficient alone.** |
| `test_all_git_argv_constructed_in_run_git` (AST) | no second construction site | **YES**, same reasons. Not sufficient alone. |
| **`test_finalize_journal_is_catfile_and_b2_revparse_only`** *(renamed from `test_no_git_presentation_command_after_worker_launch`, which was written against a false claim)* | reads `git-invocations.jsonl` after a complete run and asserts the three conditions in §5.4.5 | **NO** for a presentation command, **and** no for a second `rev-parse` variant, because the argv hash and the seam count are pinned. Still yes for a call that bypasses `_run_git` — which is why the audit-hook row exists. |
| **`test_v1_filter_program_not_executed`** — **Z-RULE-1 positive control mandatory** | arms `$GIT_COMMON_DIR/info/attributes` + `.git/config` with a sentinel `filter.myf.clean`; **(b) runs the revision-2 hardened diff and asserts the sentinel FIRED**; (c) clears; (d) runs the production finalisation and asserts it did **not** | **NO.** Step (b) is what forecloses a mis-armed sentinel. **This is the test whose absence made S-1 shippable.** |
| `test_v1_fsmonitor_program_not_executed` | same shape, `core.fsmonitor` | as above |
| `test_v1_textconv_and_external_diff_not_executed` | same shape | as above |
| `test_v1_hooks_not_executed_during_finalisation` | same shape, arming **`reference-transaction`, `post-checkout`, `post-index-change`, `pre-auto-gc`** and `core.hooksPath` **by name** | as above. **`reference-transaction` is named because revision 3 omitted it and that omission produced B-2.** |
| **`test_repertoire_is_clean_on_all_three_surfaces`** | the full permitted set run under each of S-α, S-β and S-γ armed separately, **each pass carrying its own positive control that fires** | **NO** for the three surfaces armed. **YES for a fourth surface nobody has armed** — which is stated, not hidden, and is why §5.4.3's safety argument is structural rather than enumerative. |
| `test_subprocess_audit_hook_accounts_for_every_git_child` | a bypass of the chokepoint | uses `sys.addaudithook` on `subprocess.Popen` in the test process — **the only mechanism found that can observe a bypass from inside the suite**. **`REQUIRES-PROBE`:** not verified against this codebase's `asyncio.to_thread` execution model. |

#### 5.4.7 Named mutants (directive A)

| Mutant | Named killer |
|---|---|
| **ZM-A1** re-introduce `git diff <base>` as the content source | `test_v1_filter_program_not_executed` (sentinel fires at step (d)) |
| **ZM-A2** re-introduce `git status --porcelain -z` for the inventory | `test_finalize_journal_is_catfile_and_b2_revparse_only` + `test_v1_filter_program_not_executed` |
| **ZM-A3** re-introduce `git diff --check` as a corroborating source | `test_check_findings_have_single_source` (asserts every finding's provenance is `dispatcher` **and** no `diff` row exists in the journal) |
| **ZM-A4** use `cat-file --filters` for the old side | `test_old_side_bytes_are_raw_blob` (clean/smudge rewrite content; the old side must equal the raw blob **and** the sentinel must not fire) |
| **ZM-A5** call `subprocess.run(["git", …])` outside `_run_git` | `test_all_git_argv_constructed_in_run_git` (AST) **and** `test_subprocess_audit_hook_accounts_for_every_git_child` |
| **ZM-A6** move the §5.8 preflight to after `worktree add` | `test_unreconciled_admin_state_refuses_before_worktree_add` |
| **ZM-A7** run a second `rev-parse` variant post-worker (e.g. `--show-toplevel`) | `test_finalize_journal_is_catfile_and_b2_revparse_only` — condition (ii), the pinned argv hash |
| **ZM-A8** **delete B2's post-worker verification to make the journal test pass** | `test_worktree_head_moved_during_run_is_refused` — a fake worker that checks out another commit inside its worktree; the run must land `FAILED` with `WorktreeBaseMismatch` **before any evidence exists** |
| **ZM-A11b** replace the identity producer with `diff --name-only -z` | `test_inventory_never_executes_a_worker_filter` — **measured to fire, so this mutant is killable, which it was not in revision 2** |

### 5.5 Directive B — the authority pipeline

#### 5.5.1 Shape, and the order is load-bearing

```
── PREPARE, in this order ─────────────────────────────────────────────
 0. RAW ADMINISTRATIVE PREFLIGHT  (§5.8)     NO git process has run yet
 1. resolve the immutable base SHA           rev-parse
 2. BaseTreeSnapshot                         ls-tree   (lazy cat-file at FINALIZE)
 3. materialise the task worktree            worktree add  ← the ONE PREPARE
                                                             exec vector
 4. START FsSnapshot                         dispatcher-owned lstat/readlink/hash
 5. BaseReconciliation(2 vs 4)               dispatcher-owned; DECIDES the old side
── worker runs ────────────────────────────────────────────────────────
 6. POST FsSnapshot                          dispatcher-owned. NO git status.
 7. WorkerDelta(4 vs 6) + CumulativeDelta(2 vs 6) → PathIdentitySet
 8. SCOPE + primary-tree policy on the identity set
 9. classification (lstat) → content from authoritative BYTES. NO git diff.
10. diff.patch, diff_stat, diff_total_bytes, diff_check — ONE representation
```

Steps 2 and 5 happen **once per task**, at worktree materialisation; steps 4 and
6–10 happen once per run. §5.5.5 explains why that distinction is required for
**correctness on resume**, not merely for speed.

#### 5.5.2 Step 1–2 — the base tree, and the content hash IS the git blob oid

`resolve_base_commit` and `assert_worktree_base` are **not touched**. B2 stands
exactly as it is: exact full-SHA equality, ancestry and merge-base refused.

> **And `assert_worktree_base` runs POST-WORKER**, at §8 row 2, before any
> evidence is collected — `server.py:2005` → `git.py:532` →
> `git rev-parse --verify HEAD^{commit}` inside the task worktree. **That is the
> second of the two post-worker git commands** (§5.4.5). It is measured clean on
> all three armed surfaces, and it is a §2 non-regression that **must not be
> deleted to make a journal assertion pass** (§0.2).

```python
@dataclass(frozen=True)
class TreeEntry:
    path: bytes          # repo-relative, RAW bytes
    mode: int            # 0o100644 | 0o100755 | 0o120000 | 0o160000
    kind: Literal["blob", "symlink", "gitlink"]
    oid: str             # 40-hex — THIS IS the content hash
    blob_size: int       # from --long; -1 for gitlink
```

**DECISION Z-5 — the content hash is the git blob object id.**

```python
def git_blob_oid(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
```

Verified byte-exact against `git ls-tree` for a normal file, an **empty** file, a
file with **no trailing newline**, and a **symlink** (where the blob is the raw
target bytes, so `os.readlink` in bytes mode feeds the same function). Four
cases, four exact. Adopted from Z3 and independently verified by Z1.

Consequences: `BaseTreeSnapshot` needs **no blob reads at all** — the `ls-tree`
oid *is* the hash — so `cat-file --batch` comes off the PREPARE hot path and is
invoked **lazily at FINALIZE, for the old side of changed paths only**, removing
a 22.6 MB read from every dispatch on the production repository. Base-vs-filesystem
comparison becomes a **string compare of two object ids**. One hash serves both
the base-comparison axis and the START↔POST axis.

sha1 runs at 200 MB/s here against blake2b's 301: on the production task worktree
(22.6 MB) that is 113 ms vs 75 ms — **38 ms for removing an entire read pass and
for direct interoperability with git's own identity. Worth it.** sha1 is used as
a *content identity function interoperable with the object store*, never as a
security primitive; a collision attack would have to produce a file whose git oid
matches the base blob, which is the assumption git already makes about the
repository. **Recorded, not hidden.**

**Parsing `ls-tree -r -z --long`, precisely.** Records are NUL-terminated. Within
a record, split on the **first** `0x09`: head is
`<mode> SP <type> SP <oid> SP <space-padded-size>`, tail is the **raw path**.
Splitting on the last TAB, or on any newline, is a defect — **a filename may
contain a TAB**. `-r` means `tree` never appears; `commit` means a gitlink and
`size` is `-`.

**`-z` is the mechanism and `core.quotePath` is irrelevant here.** Measured:
under `-z`, `café.txt` is emitted as raw `caf\303\251` bytes and
`-c core.quotePath=false` changes **nothing**. Without `-z` the same path is
`"caf\303\251.txt"`. The `-c` stays on the argv as defence in depth against a
worker flipping it; **nothing depends on it**.

**`cat-file` is fed OBJECT IDS, never paths.** `<rev>:<path>` transport would
re-introduce a path-encoding problem into the one place ZI-7 says paths must
never be re-derived, and `--batch` is line-oriented so a path containing a
newline would corrupt the stream. Object ids are 40 hex characters and cannot.
Response records are `<oid> SP <type> SP <size> LF <raw bytes> LF` — **read
exactly `size` bytes, then consume one LF. Never `readline()` the payload.**
`--filters` and `--textconv` are **forbidden by name** (both measured to fire),
and a test asserts the literal strings never appear in `src/**`.

Fail-closed: a missing object, a size mismatch, an unparseable record or a
non-zero exit raises `BaseTreeSnapshotFailed`. **There is no partial
`BaseTreeSnapshot`.**

#### 5.5.3 Step 4 — `FsSnapshot`, dispatcher-owned filesystem code

```python
@dataclass(frozen=True)
class FsEntry:
    path: bytes                 # root-relative, RAW bytes
    kind: Literal["regular","directory","symlink","fifo","socket",
                  "block_device","char_device","unknown"]
    perm: int; size: int; mtime_ns: int; ctime_ns: int
    ino: int; dev: int; nlink: int
    content_hash: str | None    # git blob oid. Regular files AND symlinks.
                                # None iff fidelity == "stat_identity".
    link_target: bytes | None   # symlink only. RAW bytes. NEVER resolved.
    read_error: str | None      # set instead of content_hash on EACCES/EIO/…

@dataclass(frozen=True)
class FsSnapshot:
    schema_version: int
    root: bytes
    role: Literal["task_worktree_start","task_worktree_post",
                  "primary_pre","primary_post"]
    entries: tuple[FsEntry, ...]          # sorted by RAW path bytes, ascending
    fidelity: Literal["content_hash_all","stat_identity"]
    hash_algo: Literal["git-blob-sha1"]
    counts: dict[str, int]; total_regular_bytes: int
    unreadable: tuple[bytes, ...]
    admin_excluded: tuple[bytes, ...]
    captured_at: str; duration_ms: int
```

**The walk, specified so two implementers produce the same bytes:**

1. Start from `root` as a **`bytes`** path. `os.scandir` on a `bytes` path yields
   `bytes` names; **nothing is ever decoded.**
2. `os.lstat` every entry. **`follow_symlinks=False` everywhere, without
   exception.** A symlink is recorded, never traversed. There is therefore no
   symlink loop, no `realpath`, and **no `path_escapes_worktree` bucket** —
   revision 2 needed one because it `lstat`ed and then opened; this walk never
   opens a non-regular file.
3. Descend into directories only; record `st_dev`, note a mount boundary, and
   **still descend**. The budget bounds the consequence.
4. Regular files: `O_RDONLY | O_NOFOLLOW`, 1 MiB chunks, git-blob-sha1 with the
   `blob <size>\0` prefix taken from the `lstat` size **and re-verified against
   the bytes actually read** (a mismatch is `changed_during_measurement`).
   Symlinks: `os.readlink` in **bytes** mode through the same function. On
   `OSError`, set `read_error` and leave `content_hash` `None` — **an unreadable
   file is recorded, never skipped.**
5. **The repository's own administrative state is excluded and captured by §5.8
   instead.** Every excluded path is listed in `admin_excluded`, so "excluded" is
   visible rather than silent.
6. Entries sorted by raw `path` bytes ascending — the documented collation for
   everything downstream.

**What this walk cannot be lied to about, and what it can.** It cannot be
suppressed by `.gitignore`, `info/exclude`, `core.excludesFile`,
`status.showUntrackedFiles`, `assume-unchanged`, `skip-worktree`, an attribute, a
filter, or **any git configuration whatsoever** — it consults none of them. It
**can** be defeated by a worker that changes a file and restores its exact bytes
before exiting (a hash is a hash), and by a same-uid worker that deletes the
dispatcher's own snapshot artefacts. **Both residuals are inherent to the
same-user threat model `docs/SECURITY.md` already states, and neither is worse
than today.**

##### The fail-closed budget (directive C's cost requirement, answered with numbers)

Measured: the production *task worktree* is 584 files / 22.6 MB; the *primary
tree* is 46,565 entries / 789.9 MB.

```toml
[evidence]
snapshot_max_entries        = 250_000        # per snapshot
snapshot_max_regular_bytes  = 4_000_000_000  # per snapshot
snapshot_post_growth_factor = 20.0           # POST entries / START entries
snapshot_fidelity_task_worktree = "content_hash_all"   # NOT configurable downward
snapshot_fidelity_primary       = "stat_identity"
```

- **PREPARE (START walk).** Exceeding a bound raises `SnapshotBudgetExceeded` as
  a **PREPARE-phase refusal**: no worker launched, no run index consumed,
  `state.json` byte-identical, the measured counts and the bound in
  `refusals.jsonl`. **The operator learns the repository is too large before
  spending a worker.**
- **FINALIZE (POST walk).** Exceeding a bound, or the growth factor, raises in
  FINALIZE. The run lands `FAILED`, the partial snapshot is **preserved** with
  `truncated_at_entry` recorded, and **`changed_paths` is NOT produced.** There
  is no degraded mode and no silent skip: an unbounded tree and a clean tree must
  never produce the same evidence.
- The walk counts as it goes and aborts at the bound.

##### Fidelity, and the one place a weaker default is recommended

- **Task worktree: `content_hash_all`, not configurable downward.** A
  `stat_identity` task-worktree snapshot would let a worker hide a modification
  with `os.utime` plus a size-preserving edit — reopening, in a new place,
  exactly the class of hole this gate exists to close. Cost measured and small.
- **Primary tree: `stat_identity` by default** — §5.9.4, with the residual.
- **`fidelity` is written into every artefact and into
  `DispatcherObservations`.** Nobody can be in the weaker mode without it being
  legible in the evidence, and a test asserts the task-worktree snapshot's
  fidelity in every integration run.

#### 5.5.4 Step 5 — reconciliation: base object representation vs starting filesystem

**Why this step exists, measured.** A repository whose **committed**
`.gitattributes` says `* text eol=crlf` has base blob `line1\nline2\n` and
worktree bytes `line1\r\nline2\r\n`. No worker is involved. Under `git-lfs` — the
most common real-world case — the blob is a 130-byte pointer and the worktree
file is the asset. **The base tree and the starting filesystem are routinely not
byte-identical, and assuming they are is a correctness bug before it is a
security bug:** every such file would appear in `diff.patch` as *"the worker
rewrote this file"*, attributing a pre-worker checkout transform to Claude, which
Sol forbids in as many words.

> **DECISION Z-2. The evidence old-side is the captured pre-worker filesystem
> bytes wherever the base object representation and the starting filesystem
> representation differ. The base blob is the old side only where the two are
> byte-identical. Option (B) — refuse with `UnsupportedCheckoutTransformation` —
> is REJECTED.**

Why (A) and not (B): **(B) refuses legitimate repositories** — a two-line
ordinary `.gitattributes` triggers it, `git-lfs` triggers it on every asset, and
it would refuse *at the last moment*, after the worktree exists. **(A) makes the
evidence's own claim true** — the old side is by construction the bytes on disk
when the worker started, so a checkout transform contributes **zero** to the
diff. **(B) is not more secure, only more brittle** — the security question
(*did a worker-controlled filter corrupt the starting tree?*) is answered by
§5.8's administrative reconciliation, which refuses **before the checkout**;
refusing on the *symptom* while permitting the *cause* is the wrong gate in the
wrong place. And it preserves the property Sol names explicitly: **a pre-worker
checkout transform is never attributed to Claude.**

**The residual, stated plainly.** Under (A), if the transform was itself produced
by a hostile filter, the old-side bytes are attacker-chosen. The attacker cannot
thereby hide a *worker* change (the run delta is still START→POST), but they can
make the *starting state* a lie about the base commit. **That is exactly what
§5.8's preflight is for, and it is why Z-2 is "(A) plus the §5.8 gate", never
"(A) alone".**

```python
@dataclass(frozen=True)
class BaseReconciliation:
    base_commit: str
    identical_count: int
    diverged: tuple[DivergedPath, ...]      # base_oid, start hash/size, captured_ref
    missing_from_fs: tuple[bytes, ...]
    extra_on_fs: tuple[bytes, ...]
    kind_mismatch: tuple[KindMismatch, ...]
    gitlinks: tuple[bytes, ...]
    captured_bytes: int
    verdict: Literal["identical", "transformed", "refused"]
```

Diverged START bytes are captured **content-addressed** under
`materialisation/start-bytes/<hash>.bin` (0600 inside 0700), so N identical CRLF
files cost one copy. Bounded by
`reconciliation_max_captured_bytes = 200_000_000` and
`reconciliation_max_diverged_paths = 20_000`; exceeding either is a PREPARE
refusal (`CheckoutTransformationBudgetExceeded`) **on a budget, not on the
existence of a transform** — which is what keeps Z-2 as (A) and not a disguised
(B).

**Computed once per task, and frozen — this matters for correctness on resume.**
On run 2 the worktree already contains run 1's output, so START ≠ base tree for
reasons unrelated to any transform. Recomputing per run would classify run 1's
legitimate edits as `diverged` and capture their bytes as "the old side", making
run 2's cumulative `diff.patch` show run 1's work as absent.

```
old_side(p) =
    start-bytes[p]          if p in reconciliation.diverged     (Z-2 case A)
    raw blob(base_oid[p])   elif p in base_tree                  (lazy cat-file)
    /dev/null               otherwise (created after materialisation)
```

Pinned by `test_resume_old_side_is_base_not_run1`.

**Submodules (`gitlink`)** are recorded, never descended, never content-diffed.
**`REQUIRES-PROBE`:** no repository with a real submodule was exercised; the
production repository has none.

#### 5.5.5 Step 3 — materialisation, and the one PREPARE execution vector

**DECISION Z-3 — materialisation is gated, not hardened.** `git worktree add`
remains the default mechanism and is permitted **only after §5.8's raw
administrative preflight has passed**. §5.8 reads the filter/attribute/hook
configuration with plain file I/O — **no git command** — and refuses the dispatch
if it does not match the recorded trusted baseline. **That ordering is the entire
safety argument for step 3.**

**DECISION Z-4 — `dispatcher_raw` materialisation. STATUS: OPEN, pending
`GATE7-Z5-PREPARE-PROBE.md`.**

> **Revision 3 annotated the first line of this block `# executes NOTHING`, rested
> Z-4's claim to being *structural rather than gated* on that annotation, and the
> annotation is FALSE.** Measured on git 2.43.0 with a positive control:
>
> ```
> POSITIVE CONTROL   git branch poscontrol                       FIRED:reference-transaction
> Z-4's own argv     worktree add --no-checkout -b b1 …          FIRED:reference-transaction
>   + -c core.hooksPath=<empty>                                  clean
> the DEFAULT argv   worktree add --quiet -b b3 …                FIRED:reference-transaction
> the repertoire     ls-tree / cat-file / rev-parse              clean
> ```
>
> `--no-checkout --detach` fires it too. The hook is
> `$GIT_COMMON_DIR/hooks/reference-transaction`, **reachable with the `Write` tool
> and no git command at all** — the identical topology as the original
> `filter.*` finding.

```
git … worktree add --no-checkout -b <branch> <path> <base>
      # FIRES $GIT_COMMON_DIR/hooks/reference-transaction (S-γ). NOT "nothing".
GIT_INDEX_FILE=<run_dir>/index.tmp git … read-tree <base>     # external index, no -u
for each TreeEntry: write raw blob bytes / symlink / mkdir, mode from `mode`
```

Because the dispatcher writes the bytes, the starting filesystem **is** the base
object representation by construction, and `BaseReconciliation` becomes a
*verification* rather than a measurement. **That property is unaffected by B-2
and remains Z-4's real value.**

**What B-2 removes is Z-4's claim to be *structural*.** Creating the branch ref
executes a worker-plantable hook, so a `dispatcher_raw` PREPARE still runs a
program a *previous* task could have left behind — which is Z1-N1, the very
defect Z-4 exists to escape. **Z-4 is therefore demoted from "structural" to
"gated, like the default", unless Lane Z5 measures a fire-nothing materialisation
path.**

> **THIS SECTION IS NOT FINAL.** Sibling **Lane Z5** is measuring, right now:
> (i) what actually neutralises `reference-transaction` — and whether
> `-c core.hooksPath=<empty dir>` is acceptable given it is exactly the
> flag-hardening this section rejects on principle; (ii) whether a materialisation
> path exists that fires **nothing** on any armed surface **and** is usable by a
> real worker; and (iii) whether §5.8-as-precondition ordering is achievable at
> all, given a previous task's poisoning persists in the **shared** common dir.
> **Z-4 and the default's gating argument must not be finalised until
> `GATE7-Z5-PREPARE-PROBE.md` is published and cited here.**

Two things are decided regardless of Z5's result, because they do not depend on
it:

1. **The default path is not newly unsafe.** §5.8 captures `hooks/**` in the
   trusted baseline, hashes every file and mode, and **refuses before any git
   command runs**. A `reference-transaction` hook a worker planted is an
   administrative divergence on the *next* dispatch and a `POLICY_VIOLATION` on
   *this* one. What B-2 changes is the document's safety accounting, not the
   gate.
2. **`REQUIRES-PROBE` stands on the worker-usability half**: whether a worker can
   build and test in a tree with LFS pointers instead of assets, LF where the
   repository wants CRLF, and its own `git status` showing every
   attribute-affected file as modified, is **untested**.

#### 5.5.6 Steps 6–7 — the POST snapshot and the worker-attributable delta

Step 6 is the same walk, `role="task_worktree_post"`, `content_hash_all`, subject
to the FINALIZE budget. **No `git status`. No `git ls-files`. No `git diff`.**

**Two deltas, and `changed_paths` is their union.**

- **`run_delta`** = START vs POST. **This is the worker-attributable set** and it
  is what `origin` derives from — Sol's step 6.
- **`cumulative_delta`** = the base representation (base blob, or the captured
  START bytes for a diverged path) vs POST. This is what `diff.patch` has always
  meant and must keep meaning.
- `changed_paths = sorted(run_delta ∪ cumulative_delta)`, each labelled
  `origin ∈ {this_run, prior_run, both}`.

The union matters in **both** directions, and revision 2 had only one:

- A path changed by run 1 and untouched by run 2 is in `cumulative` only. **It
  must still be scope-checked in run 2** — otherwise a resume laundering exists:
  make the forbidden write in run 1 (which lands `POLICY_VIOLATION`), resume, and
  run 2 reports a clean scope.
- A path the worker changed **and reverted to the base representation** within
  one run is in `run_delta` only. **It must still be reported:** touching a
  forbidden path and putting it back is still touching it.

**This is a deliberate widening of directive B's literal text** (which says
compare POST against START and apply scope to *that* inventory) and is
**escalated as Z1-G-4 (§18.1)**.

#### 5.5.7 The authoritative type (directive K, reconciliation 3)

Z3's staged structure, with the closed enum replaced by an orthogonal tuple.

```python
# inventory.py — WAVE 0. Imports nothing from Wave A, B, C, D or E.

RepoPath = NewType("RepoPath", bytes)   # RAW filesystem bytes. No str, ever.

# ---------- STAGE 1: IDENTITY. No lstat. No open(). No content byte. ----------

@dataclass(frozen=True)
class PathChange:
    path: RepoPath
    change: Literal["added","removed","modified",
                    "kind_changed","mode_changed","link_target_changed"]
    origin: Literal["this_run","prior_run","both"]
    tracked_at_base: bool
    ignored_by_base: bool          # CLASSIFICATION ONLY — §5.6
    admin_significant: bool        # under .git/ or $GIT_COMMON_DIR/
    old_kind: str | None; new_kind: str | None
    old_hash: str | None; new_hash: str | None
    old_size: int | None; new_size: int | None

@dataclass(frozen=True)
class PathIdentitySet:
    """THE authoritative changed-path set. RAW BYTES. Produced once per run.
    Nothing else in src/** may produce a path into scope enforcement."""
    schema_version: int
    base_commit: str
    changes: tuple[PathChange, ...]          # sorted by raw path bytes
    run_delta_count: int
    cumulative_delta_count: int
    unchanged_count: int                     # <<< AN INT. 3,842 lives HERE and
                                             #     CANNOT become a path list.
    unrepresentable: tuple[UnrepresentablePath, ...]
    fidelity: Literal["content_hash_all"]
    digest: str            # sha256 over the ordered (raw path, change) records

# ---------- STAGE 2: POLICY. Decided over STAGE 1 ONLY. ----------

@dataclass(frozen=True)
class ScopeVerdict:
    decided_over_digest: str                 # MUST equal PathIdentitySet.digest
    valid: bool
    forbidden_hits: tuple[RepoPath, ...]
    outside_allowed: tuple[RepoPath, ...]
    primary_tree_interference: bool
    tamper: tuple[TamperMarker, ...]

# ---------- STAGE 3: CLASSIFICATION. lstat happens HERE, and only here. ----------

class ContentClass(str, Enum):
    TEXT_CANDIDATE             = "text_candidate"
    UNTEXTUAL                  = "untextual"              # NUL in first 8 KiB / not UTF-8
    UNREPRESENTABLE_KIND       = "unrepresentable_kind"   # symlink/FIFO/socket/device  (Y-10)
    IGNORED_BY_BASE            = "ignored_by_base"        # per-directory rollup
    OVERSIZED                  = "oversized"
    UNREADABLE                 = "unreadable"
    CHANGED_DURING_MEASUREMENT = "changed_during_measurement"
    ABSENT                     = "absent"                 # the deleted side

@dataclass(frozen=True)
class ClassifiedInventory:
    identity: PathIdentitySet
    verdict: ScopeVerdict          # <<< REQUIRED. Stage 3 cannot exist before stage 2.
    classes: tuple[PathClass, ...] # one per identity entry, same order
```

**Why the enum was replaced.** Z3's six-value `ChangeKind` could not express **a
modification to an already-existing suppressed file** — Sol's explicit §C
requirement, the `.venv/bin/activate` persistence-backdoor case — nor **deletion
of an untracked path**, which is how "the worker deleted the previous run's work"
appears on a resume. A closed enum that cannot express a required observation is
the same defect as revision 2's type that could not express `assume-unchanged &&
rm`. Every one of Z3's six kinds remains derivable:

| Z3 `ChangeKind` | derived from |
|---|---|
| `tracked_modified` | `change="modified"` ∧ `tracked_at_base` |
| `tracked_deleted` | `change="removed"` ∧ `tracked_at_base` |
| `tracked_typechanged` | `change="kind_changed"` ∧ `tracked_at_base` |
| `untracked_new` | `change="added"` ∧ ¬`ignored_by_base` |
| `suppressed_new` | `change="added"` ∧ `ignored_by_base` |
| `submodule_boundary` | `BaseReconciliation.gitlinks` |
| **`suppressed_modified`** *(inexpressible in Z3)* | `change="modified"` ∧ `ignored_by_base` |
| **`untracked_deleted`** *(inexpressible in Z3)* | `change="removed"` ∧ ¬`tracked_at_base` |

**Wave B's `CanonicalEvidence` consumes a `ClassifiedInventory` and adds only**
`patch_bytes`, per-path patch bytes, `diff_stat`, `check_findings`,
`patch_file_complete` and `review_input_complete`. **Wave B defines nothing Wave 0
needs.** That is directive L expressed as a type boundary.

#### 5.5.8 Steps 9–10 — content from authoritative bytes, one representation

```
old bytes := old_side(path)      # §5.5.4 — one of three sources, NEVER git diff
new bytes := read POST file      # O_RDONLY|O_NOFOLLOW, hash re-verified against
                                 #   the POST snapshot; mismatch ->
                                 #   changed_during_measurement
```

Binariness is decided **from those bytes and nothing else** — NUL in the first
8 KiB of either side, or either side not valid UTF-8. `git`'s
`Binary files … differ` never appears except as text the dispatcher composes.

| Artefact | Producer | Notes |
|---|---|---|
| `diff.patch` | dispatcher-native unified diff | byte lines, **pinned** algorithm; sections ordered by raw path bytes; headers rendered from the inventory's bytes, **never parsed back** |
| `diff_stat` | counted from the same hunks | dispatcher-composed rows; git's `/dev/null => X` label is never pasted |
| `diff_total_bytes` | `len` of the assembled patch | the file on disk and this number are the same object |
| `diff_check` | dispatcher scanner over the patch's added lines | trailing whitespace, space-before-tab, `<<<<<<< ` / `======= ` / `>>>>>>> ` at line start. **`git diff --check` is not run, not unioned, not consulted.** |

**Patch header rendering for hostile paths.** The dispatcher emits git's C-quoted
form **for display in the patch text only**, and ZI-7 makes it a structural rule
that nothing reads it back. A test asserts a `new\nline.txt` patch round-trips
through `git apply --check` in a **disposable** repository — the only external
validation that does not put git back on the authority path (it validates a
*format*, post-hoc, in a throwaway tree, and its result never feeds evidence).
**`REQUIRES-PROBE`:** `git apply --check` acceptance of a dispatcher-composed
patch for the four §9 edge cases is **not verified**. Revision 2 got those shapes
from git itself; hand-composing them is a genuine new risk that a probe **must
retire before Wave B**.

#### 5.5.9 Per-path buckets

| Bucket | Trigger | Clears `patch_file_complete`? | Blocks Fable? |
|---|---|---|---|
| `represented` | content in the patch | — | — |
| `content_omitted_untextual` | binary by the dispatcher's NUL/UTF-8 test | **no** — it has no text representation and never had one | **no** |
| `content_omitted_unrepresentable` | symlink, FIFO, socket, device, gitlink — **Y-10** | **no** — same reason | **no** |
| `content_omitted_bulk_created` | **ONLY** `change == "added"` ∧ `ignored_by_base` ∧ over the volume budget — §5.6.5 | **YES — the flag goes FALSE** | **no** (the reviewer is told by prefix, count and bytes) |
| `content_omitted_capped` | over `[evidence].max_file_bytes` | **YES** | **yes** |
| `refused` | unreadable, `changed_during_measurement` | **YES** | **yes** |

> **`content_omitted_ignored_by_base` is DELETED as a bucket.** Revision 3 made
> it the **only** content-omitted class that did not clear `patch_file_complete`,
> which reproduced **Shape 2** — the design's own §1 taxonomy — for the precise
> attack directive C names by name. See §5.5.9A.

Note what has **disappeared** relative to revision 2: `refused: directory` (a
directory is a `kind`, not a file to read), `refused: path_escapes_worktree`
(nothing resolves a symlink), and `refused: symlink` (moved to
`content_omitted_unrepresentable`). **`refused` now means only "we could not see
it" or "it moved while we looked"**, which is what makes `patch_file_complete` a
flag worth reading.

#### 5.5.9A A modification to a base-ignored file is represented IN FULL (B-3)

**The defect revision 3 shipped.** Trace the `.venv/bin/activate` persistence
backdoor — the case directive C names explicitly and §5.6.3 answers:

1. **Inventory** — `content_hash` differs between START and POST →
   `change="modified"`, `ignored_by_base=True`. **Detected.** This half is right
   and is a real improvement over revision 2 and over the baseline.
2. **Policy** — `scope_check_base_ignored = false` exempted it from
   `allowed_paths`. Not `outside_allowed`.
3. **Content** — bucketed `content_omitted_ignored_by_base`; the modified bytes
   never entered `diff.patch`; `diff_stat` got one rollup row.
4. **Completeness** — `patch_file_complete` **unaffected → `true`**.
5. **Review** — did not block Fable, which was handed a patch **marked complete**
   that omitted a supported, changed, regular text file, and told only
   *".venv/ — 1 modified, N bytes"*.

**So the one attack directive C names was detected in the inventory and then
neutralised in policy and erased from the evidence, by default, while the
completeness flag said the evidence was complete.** That violates the brief at
§9 (*"No `diff_patch_complete=true` when content was omitted"*) and §27
verbatim, and it is Shape 2 reproduced inside the pipeline built to eliminate it.

**The line that fixes it without reintroducing the explosion: creation is bulk;
modification is not.**

> **ZI-25.** A base-ignored path whose change is anything other than `added` —
> `modified`, `removed`, `kind_changed`, `mode_changed`, `link_target_changed` —
> is **represented in the canonical patch in full**, exactly like any other
> changed file. It is **never** rolled up, **never** volume-budgeted, and there
> is **no configuration that elides it.**
>
> **ZI-26.** A base-ignored path whose change is `added` is represented in full
> **by default**, and is rolled up **only** when the run's added-ignored volume
> exceeds `[evidence].bulk_created_ignored_budget`. When any path is rolled up,
> **`patch_file_complete` is `False`.**
>
> **ZI-27.** `scope_check_base_ignored` exempts **only `added` paths.** A
> `modified` / `removed` / `kind_changed` base-ignored path is scope-checked
> exactly like any other path, whatever the setting.

**Why this line and not another.** The rollup exists for one real case: a worker
runs the project's own build and **creates** thousands of legitimately-ignored
artefacts. Build output is *created*. **A file that existed before the run and
changed during it is not build churn** — there is no legitimate workflow in which
a task's correct behaviour is to silently modify a pre-existing ignored file and
have the dispatcher not show it. So `added` gets a volume escape hatch (with the
flag going false when it fires) and nothing else does.

**The explosion does not return.** The 3,842 `.venv` paths are **unchanged**, so
they are in neither delta and never reach a bucket at all (§5.6.2) —
`unchanged_count` remains a scalar. ZI-25 applies to paths that are already, by
construction, in the run delta. On the two repositories measured, that set is
**empty** for a task that does not run a build.

**PROVEN BY** — `test_modification_to_existing_ignored_file_is_in_the_patch_in_full`:
the `.venv/bin/activate` fixture; assert the modified bytes appear as a full
patch section, `patch_file_complete` is **`True`** (nothing was omitted), the
path is **scope-checked** (ZI-27), and a `forbidden_paths` entry for it fires.
Paired with `test_bulk_created_ignored_files_roll_up_and_clear_the_flag`: 5,000
**added** ignored files, assert a rollup, `patch_file_complete` **`False`**, and
Fable **not** blocked.
**COULD EITHER PASS WHILE FALSE?** The first could pass if the fixture's file
were `added` rather than `modified` — so the fixture **creates the file, commits
it to the base, and only then modifies it**, and the test asserts
`tracked_at_base or ignored_by_base` **and** `change == "modified"` before it
asserts anything about the patch. The second could pass if the budget were
infinite — so it asserts the rollup **row exists** and names the prefix, not
merely that the run succeeded.
**IF MIS-WIRED** — a `modified` ignored path that gets rolled up fails the first
test at the patch-section assertion; a rollup that leaves the flag `true` fails
the second at the flag assertion. Both failures are loud and neither is silent.

### 5.6 Directive C — self-hiding and ignored paths

#### 5.6.1 Current failure

Revision 2 §5.4A(d2) made the inventory *"every path git can see has changed,
plus every path an ignore source is suppressing"*. Measured: `sol-claude-dispatcher`
**0 → 3,842** paths including 71 MB of `.venv` and **four** ignored symlinks;
`full-voice-agent` **9 → 927** including **exactly one** ignored symlink.

Four consequences compose: unconditional `POLICY_VIOLATION`, tens of megabytes of
third-party source in `diff.patch`, an inventory that is no longer a changed-path
set — and, through revision 2's `refused`-blocks-Fable rule, **that one symlink
kills every Fable review of the production repository, on every task, forever.**
Neither review recorded that number.

#### 5.6.2 The model: there is no ignore query at all

`.venv` is present in START and present, byte-identical, in POST. **It is
therefore in neither delta.** There is no fold, no absolute set, and no ignore
query. The 3,842 paths are `unchanged_count`, a scalar.

**This is strictly stronger than a suppressed-set delta** (reconciliation 2): no
`.gitignore`, `info/exclude`, `core.excludesFile`, `status.showUntrackedFiles`,
`assume-unchanged` or `skip-worktree` can remove a path, because **none is
consulted** — rather than because a subtraction cancels them out. It also needs
no `ls-files`, which §5.4 prohibits.

#### 5.6.3 The four cases Sol requires to still appear

| Case | Why it appears |
|---|---|
| a new file hidden by a worker-written `.gitignore` (F1) | POST has it, START does not → `added`, `origin=this_run`. **The `.gitignore` was never consulted.** |
| a new file created inside an **already-ignored directory** (F5) | same — the *path* is new |
| **a modification to a pre-existing ignored regular file** — Sol's explicit requirement | `content_hash` differs between START and POST. `content_hash_all` fidelity makes this true for **every** regular file regardless of any ignore rule, and **is not configurable downward**. |
| a removed path | START has it, POST does not → `removed`. `git status` could be blinded to this by `assume-unchanged` + `rm`; **a snapshot difference cannot.** |
| a write to `$GIT_COMMON_DIR/info/exclude` | not in the `FsSnapshot` at all — §5.8 owns it, and a change is an administrative divergence |

**Cost of that guarantee, measured.** Production task worktree 22.6 MB →
< 300 ms per snapshot; this repository including `.venv` 133.9 MB → 3.14 s cold /
0.59 s warm. The fail-closed preflight bound is §5.5.3, in entries and bytes,
refusing in PREPARE before a worker is launched. **This is Sol's "measure the
cost and place a fail-closed preflight bound rather than silently skipping",
answered with numbers.**

#### 5.6.4 The base-committed ignore matcher — classification only

`evidence/ignore.py`. Sources, in git's precedence order, **all read from the
base tree or the trusted administrative baseline**: every `.gitignore` blob in
the `BaseTreeSnapshot`; the **trusted-baseline** `$GIT_COMMON_DIR/info/exclude`
(§5.8's recorded copy, **never the live file**). **`core.excludesFile` is NOT
consulted at all** — it points outside the repository and is worker-writable, and
the honest consequence of ignoring it is that the dispatcher classifies *fewer*
paths as ignored, i.e. **reports more**, which is the safe direction.

Supported syntax is a deliberate subset (comments, `!` negation, leading `/`
anchor, trailing `/` directory restriction, `*`/`?`/`**`, POSIX classes,
last-matching-rule-wins with deeper files ranking later).

> **Fail-open toward reporting.** Any pattern the matcher does not fully support
> is **discarded** and recorded in `unsupported_ignore_rules` with source oid,
> line number and raw bytes. A discarded rule means the paths it would have
> hidden are `ignored_by_base = False` — **reported and scope-checked**. The
> matcher may never classify a path as ignored on a rule it did not fully
> understand.

Matching operates on **raw bytes**.

#### 5.6.5 What the classification is used for — and what it is not

| Consumer | Behaviour for `ignored_by_base = True` |
|---|---|
| `PathIdentitySet` membership | **no effect.** The path is present. |
| `forbidden_paths` matching | **no effect. Forbidden always wins.** |
| `allowed_paths` matching | **exempt by default for `added` paths ONLY** (`[scope].scope_check_base_ignored = false`, ZI-27). A worker running the project's own build **creates** thousands of legitimately-ignored artefacts; treating those as out-of-scope makes `POLICY_VIOLATION` routine. **A `modified` / `removed` / `kind_changed` base-ignored path is scope-checked exactly like any other path, whatever the setting.** |
| content generation | **`modified` and every non-`added` change: represented IN FULL, never rolled up (ZI-25).** `added`: represented in full by default; rolled up only above the volume budget, and **the rollup clears `patch_file_complete`** (ZI-26). |
| `diff_stat` | full rows for everything represented; one rollup row per prefix only for bulk-created |
| tamper marking | **none** — see below |

#### 5.6.6 Y-9 is MOOT, not answered

Revision 2 §8 row 4 made any `.gitignore` / `.gitattributes` write an
unconditional `POLICY_VIOLATION`, which criminalises the ordinary task "add the
build output to `.gitignore`". Z3 proposed option (iii) — tamper iff the write
suppresses a path this run created — and stated its cost honestly: a legitimate
"generate `dist/`, then gitignore it" task lands `POLICY_VIOLATION`.

**Under ZI-3/ZI-4 that cost disappears, because a worker-written `.gitignore`
cannot suppress anything.** Writing one is not an attack; it is an ordinary file
change, scope-checked like any other. The tamper marker narrows to what is
actually dangerous:

```
admin_significant = True  iff the path is under `.git/` or `$GIT_COMMON_DIR/`
                          (which the FsSnapshot excludes and §5.8 owns)
```

A `.gitignore` or `.gitattributes` write is recorded with
`ignore_or_attribute_write = True` for the audit trail and lands
`POLICY_VIOLATION` **only** if it is out of scope or forbidden — by the ordinary
rule. **Sol's Y-9 asked which of three answers is right; this design makes the
question moot, which is a better answer than any of them.** *Escalated for
explicit ratification as Y-9 in §17.*

### 5.7 Directive D — the path model / V-2

#### 5.7.1 The model

`check_scope`, `_translate_glob` and `_matches_any` take **`bytes`**.
`ScopeSpec.allowed_paths` / `forbidden_paths` remain `list[str]` on the public
`TaskEnvelope` and are encoded **once**, UTF-8, at envelope validation, into a
frozen `ScopeSpecBytes`. `café.txt` reaches `check_scope` as
`b"caf\xc3\xa9.txt"` — the filesystem's own bytes — and matches `b"secrets/**"`
exactly.

**Serialisation — `PathRepr`.** JSON has no bytes.

```json
{"raw_b64": "c2VjcmV0cy9jYWbDqS50eHQ=", "display": "secrets/café.txt", "utf8": true}
```

`raw_b64` is **always present and is the authoritative field**; every
dispatcher-internal reader uses it and nothing else. `display` is best-effort
(`errors="replace"`) and is for humans and the Fable prompt. **A reader that uses
`display` for anything but rendering has a bug**, and an AST test asserts
`display` is never passed to `check_scope`, `open()`, or a path constructor.

#### 5.7.2 Never re-derive a path

Paths are produced by exactly two mechanisms: the `FsSnapshot` walk
(`os.scandir` on a `bytes` root) and `ls-tree -r -z --long`. Lane X measured why
this must be a **rule** and not a parser: `--stat` accepts `-z` and **ignores
it**, and patch headers C-quote regardless. Under §5.4 none of those commands is
run at all, so the rule is now cheap to keep: **the only rendered path forms in
the system are ones the dispatcher itself emitted.**

Enforced by `test_paths_only_from_two_producers` (AST) **and** — because an AST
test can pass while the property is false — by
`test_hostile_names_survive_the_whole_pipeline`, whose fixture contains
`café.txt`, `new\nline.txt`, `tab\there.txt`, `with space.txt`, `"quoted".txt`,
`back\\slash.txt` and a 200-byte name, and which asserts each appears **exactly
once** in `changed_paths` with byte-exact identity, is matched correctly by
`check_scope`, and appears in `diff.patch`.

#### 5.7.3 Renames

Revision 2 specified rename-aware parsing of `status --porcelain -z`'s two-field
record. **That command is prohibited, so the hazard is gone by deletion.** The
filesystem snapshot has no rename concept: a rename is `removed(old) +
added(new)`, and **both paths are inventoried and both are scope-checked** —
which is the property revision 2 wanted from rename-awareness. Rename *detection*
for human evidence, if wanted later, is a dispatcher-native pass over equal
`content_hash` values in the `removed`/`added` sets; **it never affects scope.**

#### 5.7.4 Unrepresentable paths — and the correction to revision 2's ladder

**It never disappears.** The inventory holds `bytes`; `raw_b64` holds every byte
losslessly; scope matching is on bytes and is **total** — a non-UTF-8 path is
matched byte-wise against UTF-8-encoded patterns and always yields a decidable
answer. So an unrepresentable path is **always inventoried, always scope-checked,
always in `changed_paths`.**

**It fails closed — but AFTER the policy ladder, not before.** Revision 2 put
`PathInventoryUnrepresentable` at row 3, reasoning that *"without a trustworthy
inventory there is nothing to decide policy on"*. Under ZI-6 that reasoning no
longer holds, and leaving the row there **recreates exactly the R-4 laundering
hole amendment 4 was adopted to close** (Z1-N2):

```
 3. INVENTORY failure    -> FAILED.  GitEvidenceCollectionFailed,
                            BaseTreeSnapshotFailed, FilesystemSnapshotFailed,
                            SnapshotBudgetExceeded, InventoryFilesystemUnsupported.
                            `PathIdentityUnrepresentable` is NOT here.

 --- inventory EXISTS, policy is ALWAYS decided ---

 4. evidence-authority tamper  -> POLICY_VIOLATION   (§5.8)
 5. scope / primary-tree       -> POLICY_VIOLATION
 5a. PATH IDENTITY             -> FAILED, with PathIdentityUnrepresentable,
     unrepresentable              ONLY if rows 4 and 5 did not fire.
                                  Fail-closed, and it cannot preempt a breach.
```

Renamed from `PathInventoryUnrepresentable` because it is **no longer an
inventory failure**. Remediation is honest: *"this path cannot be carried by the
public task-envelope path model; the evidence records its exact bytes. Rename or
remove it, or the task must be resolved by hand."*

**`REQUIRES-PROBE`:** whether the Claude CLI, the MCP transport and the JSON
schema layer round-trip a `PathRepr` for a non-UTF-8 path end to end is
**untested**. That is why the outcome is fail-closed rather than "carry it
through".

**Case-insensitive or Unicode-normalising filesystems** would make byte identity
and git identity disagree. Both hosts are ext4 on Linux. **Stated as an
assumption with a named refusal (`InventoryFilesystemUnsupported`) rather than
silently assumed.**

### 5.8 Directive E — git administrative safety

#### 5.8.1 Current failure

Four, three of them recorded by the reviews and one new:

1. **`compare_primary_tree` is blind to `.git/**`.** It compares
   `porcelain_status + head_commit` (`server.py:296-364`), and `.git/**` appears
   in neither. A worker writing `$GIT_COMMON_DIR/info/attributes` poisons the
   primary repository's own diffs permanently and no dispatcher surface sees it.
2. **Revision 2's fingerprint is ordered after the commands it protects.** §8 row
   3 (inventory) precedes row 4 (tamper verdict), and row 3 is the row that
   executes the program. **Detection after execution is not containment.**
3. **The recorded pre-state is writable by the program being detected.** Same
   uid, 0600.
4. **Z1-N1 — the *next* dispatch's `git worktree add` executes the *previous*
   worker's smudge filter**, in PREPARE, under the full revision-2 hardening. So
   administrative state is not only an evidence-integrity question; it is a
   **cross-dispatch execution vector**.

#### 5.8.2 What is captured, and how

`evidence/gitadmin.py`. **Every read is `open(path, "rb")`. The capture runs NO
git command of any kind** — not `git config`, not `git ls-files -v`, not
`git check-attr`. **PROVEN BY** `test_admin_capture_runs_no_git_command`, which
asserts the `git-invocations.jsonl` window covering the capture is **empty**,
under a `subprocess.Popen` audit hook.

> **This is narrower than revision 3's "no `git config`", deliberately.** The
> identity producer's single `config --get remote.origin.url` (`git.py:359`) is
> **permitted** (§5.4.3) — it is a different question, asked at a different time,
> of a repository whose administrative state this capture has **already
> reconciled**. What must never happen is *asking git what the configuration
> says in order to decide whether the configuration is trusted*. The rule is
> about **this capture**, not about the string `git config`.

| Item | Path | Recorded |
|---|---|---|
| worktree config | `<gitdir>/config` | full bytes + hash |
| common config | `$GIT_COMMON_DIR/config` | full bytes + hash |
| worktree-scoped config | `$GIT_COMMON_DIR/worktrees/*/config.worktree` | per file |
| `include.path` / `includeIf` targets | resolved **transitively**, from the raw config text, depth ≤ 8 | path + hash; a target outside the repository is `external_include` |
| attributes | `<gitdir>/info/attributes`, `$GIT_COMMON_DIR/info/attributes` | full bytes + hash |
| excludes | `<gitdir>/info/exclude`, `$GIT_COMMON_DIR/info/exclude` | full bytes + hash |
| hooks | `<gitdir>/hooks/**`, `$GIT_COMMON_DIR/hooks/**`, plus any `core.hooksPath` dir | sorted listing + per-file mode + hash |
| fsmonitor | every `core.fsmonitor` assignment in any config reached | key, value, source file |
| filters / diff drivers | every `filter.*.{clean,smudge,process}`, `diff.*.{textconv,command}`, `diff.external` | key, value, source file |
| index bits (report only) | `<gitdir>/index` | hash + `mtime_ns` + size. **Not parsed** — ZI-19 makes the flags irrelevant; the hash exists so "the index moved" is visible. |
| worktree registrations | `$GIT_COMMON_DIR/worktrees/*/{gitdir,commondir,HEAD}` | contents |
| **transport and promisor keys** | any config reached above | `remote.*.url`, `url.*.insteadOf`, `extensions.partialClone`, `core.alternateRefsCommand`, `credential.helper` — **recorded and PRINTED VERBATIM to the operator** (see below) |

**`include.path` is resolved by the dispatcher's own minimal INI reader**, not by
git — the whole point is not to run git. **Anything it cannot parse makes the
whole capture `parse_incomplete = True`, which is treated as a divergence
(fail-closed), never as "nothing found".**

#### 5.8.2A The raw gitdir resolver — so ZI-18 is achievable, not aspirational

The capture is keyed on `<gitdir>` and `$GIT_COMMON_DIR`. **A dispatcher-created
linked worktree's `.git` is a FILE, not a directory**, and revision 3 specified a
raw *HEAD* reader (§5.9.2) but **no raw *gitdir* reader** — so the only mechanism
it named for obtaining those two paths was `rev-parse`, which its own ZI-18
forbade. That is N-5, and it is closed by specifying the resolver:

```
resolve_gitdir(root: bytes) -> (gitdir: bytes, common_dir: bytes)
  1. p = root / b".git"
  2. if p is a DIRECTORY  -> gitdir = p
     elif p is a FILE     -> read it; it must be exactly
                             b"gitdir: " + <path> + b"\n";
                             gitdir = that path, resolved relative to root
     else                 -> RepositoryLayoutUnreadable   (fail closed)
  3. c = gitdir / b"commondir"
     if c exists -> common_dir = contents, stripped, resolved relative to gitdir
     else        -> common_dir = gitdir
  4. both must be existing directories, or RepositoryLayoutUnreadable
```

Plain `open()` and `stat()`; **no git process**. It matches the layout the
dispatcher itself creates (`gitdir: …/.git/worktrees/<name>`).

**Fallback, and it is honest.** Where the resolver cannot decide — an unusual
layout, a relative `commondir` chain it does not model — the capture falls back
to `rev-parse --absolute-git-dir` / `--git-common-dir`, **measured clean on S-α,
S-β and S-γ**, and **records `resolver="rev-parse-fallback"` in the snapshot**, so
the weaker path is legible in the evidence rather than silent.

**PROVEN BY** `test_gitdir_resolver_matches_rev_parse_on_every_layout` — a
throwaway primary repository, a linked worktree and a detached worktree; the raw
resolver's answer must equal `rev-parse`'s for each, byte for byte.
**COULD IT PASS WHILE FALSE?** Only for a layout the fixture does not contain —
which is exactly why the fallback exists **and is recorded**, rather than the
resolver being asserted total. **IF MIS-WIRED** — the resolver disagrees with
`rev-parse` and the test fails; a resolver that silently returned the wrong
gitdir would make the capture read the wrong files, which
`test_unreconciled_admin_state_refuses_before_worktree_add` catches from the other
end, because its poisoned config would no longer be seen.

#### 5.8.3 The trusted baseline and the reconciliation gate

**PREPARE, step 0, before any git process exists:**

```
current := capture(role="pre_run")
if no baseline exists:
    -> RepositoryAdministrationUnestablished          (PREPARE refusal)
       remediation: an operator runs `scripts/trust-repo-admin.py <repo>`,
       which records the baseline and PRINTS VERBATIM every exec key it is
       about to trust. Establishing a baseline is a HUMAN act, once per
       repository, and it is where a legitimate git-lfs or fsmonitor setup is
       acknowledged.

       The printed set is NOT only the diff/filter keys. It includes
       `remote.*.url`, `url.*.insteadOf`, `extensions.partialClone`,
       `core.alternateRefsCommand` and `credential.helper`, because a
       transport or promisor key can reach a program through a lazy fetch
       and the human trust step must see it. (Measured on git 2.43.0: an
       `ext::<program>` transport reached through `cat-file` in a partial
       clone did NOT execute the helper — `rc=128` — and neither repository
       on this host is a partial clone. **Closed as non-exploitable today,
       and recorded so it is not re-opened as a hypothetical** — but the
       key list an operator is shown is widened regardless, because
       §5.8.2 hashes the whole config file while the PRINTED list is what
       a human actually reads.)
if current != baseline:
    -> RepositoryAdministrationUnreconciled           (PREPARE refusal, NOT retryable)
```

**No git command that could execute a repository-supplied program runs before
this gate passes** — only the identity resolution of §5.8.2A, whose fallback
`rev-parse` variants are measured clean on all three armed surfaces. That is
ZI-20, and it is the
whole safety argument for the PREPARE checkout: **the checkout can only execute a
repository-configured program if that program was in the trusted baseline.**

**FINALIZE:** `post != pre_run` is `evidence_authority_tamper` →
**`POLICY_VIOLATION`** (§8 row 4), with a marker naming each administrative file
and each exec key that moved. **Because the post-worker pipeline runs no
presentation command, this comparison is now upstream of every execution risk
rather than downstream of it** — which repairs the ordering complaint
structurally rather than by moving a row.

**A dispatch after a tamper verdict refuses until reconciled**, at step 0,
**before running any git command** — Sol's *"it must not run a dangerous git
command first"*, satisfied by ordering rather than by intent.

**Deny-list additions**, worth making and **not the mechanism**:
`Bash(git config:*)`, `Bash(git update-index:*)` and `Bash(git -C:*)` join
`CORE_DENIED_GIT_OPERATIONS`. Honestly labelled: a prefix match on Bash command
text by the CLI's own permission engine. **`Write` reaches `.git/config`,
`.git/info/*` and `.git/hooks/*` as plain files with no git command at all**, so
the deny list raises the cost and closes the naive path. **The fingerprint is the
mechanism.**

**What is NOT protected, deliberately.** The dispatcher's own worktree
registrations (`$GIT_COMMON_DIR/worktrees/sol-<id>/{gitdir,commondir,HEAD,index,logs}`
and the branch ref) are on an explicit allowlist keyed by the `sol-` prefix
`worktree_name_for` guarantees. **`config.worktree` under those directories is
NOT allowlisted** — it is worker-writable and is exactly the documented hiding
place. Objects are immutable and content-addressed; a new object cannot change an
existing one.

#### 5.8.4 The residual, stated plainly

The baseline is a file owned by the same uid as the worker. **Under a same-user
threat model, no dispatcher-side artefact is tamper-proof, and this design does
not claim otherwise.** What is genuinely different from revision 2:

- the post-worker pipeline gives the worker **no execution** with which to do it
  (that was the mechanism, and it is closed **by deletion, not by detection**);
- the baseline is written **once, by an operator command**, not on every run, so
  a worker cannot launder a change by waiting for the next capture;
- an optional HMAC (`git-admin-baseline.sig`) keyed by a file the operator places
  **outside** the repository and outside `state/`. If the key is absent the gate
  report says so and the protection degrades to *"detectable by an operator
  reading the JSON"*, **not** to *"protected"*. **`REQUIRES-PROBE`:** this is a
  containment claim about filesystem permissions, **not a measurement**.

#### 5.8.5 ZI-19 deletes revision 2's layer 4, and returns a cost

Revision 2's clean `GIT_INDEX_FILE` + `read-tree` + `ls-files -v` audit is
**deleted**. The clean index existed to make `git diff` trustworthy, and **there
is no `git diff`.** `ls-files -v` is deleted too: it is a prohibited command and
its finding has no consumer. **`assume-unchanged` and `skip-worktree` become
structurally irrelevant rather than defeated** — Sol's *"prefer making the
worker-controlled index irrelevant rather than proving every flag unset"*, taken
literally.

**Note the cost this returns:** a stat-cache-less temporary index forced a full
content re-read on *every* git call. That disappears with it.

> **Lane V's integration warning, carried forward verbatim:** revision 2's
> §5.4A(d2) and this section are **mutually exclusive designs for the same
> problem**. The integrated document must not carry both. Every clean-index,
> `ls-files -v` and `--exclude-standard`-delta sentence is **deleted**, not
> amended.

### 5.9 Directive F — the primary tree

#### 5.9.1 Current failure

`snapshot_primary_tree` (`server.py:319`) is `primary_tree_status()` +
`resolve_base_commit(repo, "HEAD")` — i.e. **`git status --porcelain` executed
against the primary repository, after the worker exited, as the dispatcher.** It
is the single most attractive target in the system: it executes `core.fsmonitor`
and `filter.*.clean` **against the primary repository**; it can be blinded by
`git -C <primary> update-index --assume-unchanged`, by `info/exclude`, and by
`status.showUntrackedFiles=no`; and it is called **twice per run** plus once on
the failure path.

#### 5.9.2 Mechanism

```python
@dataclass(frozen=True)
class PrimaryTreeSnapshot:          # SAME NAME, new contents
    schema_version: int
    head_commit: str                # RAW ref resolution, below
    head_ref: bytes | None
    fs: FsSnapshot                  # role="primary_pre" | "primary_post"
    admin: GitAdminSnapshot         # §5.8
    porcelain_status: str           # retained, now DISPATCHER-RENDERED
```

**Raw HEAD resolution** (no `rev-parse`, because this runs post-worker too): read
`<gitdir>/HEAD`; if it starts `ref: `, resolve against `<common_dir>/<ref>` or
scan `packed-refs`; else it must be exactly 40 hex. At most 5 symbolic hops; the
result must match `^[0-9a-f]{40}$` or it is a fail-closed `RefResolutionFailed`.
**Nothing here can execute a program.**

**`REQUIRES-PROBE`: reftable** (`extensions.refStorage = reftable`, git ≥ 2.45)
is **not supported** by this reader. The capture records
`extensions.refStorage` and **refuses** (`UnsupportedRefStorage`) rather than
mis-reading. The loose-ref and `packed-refs` layouts were verified on 2.43.0;
reftable was not, and the refusal path is untested.

**Comparison** is `pre` vs `post`, entry by entry, on
`(kind, perm, size, mtime_ns, ino, dev, nlink, content_hash, link_target)`:

| Class | Verdict |
|---|---|
| `head_changed` | `POLICY_VIOLATION` |
| any change to a path **tracked at primary HEAD** or **not `ignored_by_base`** | `POLICY_VIOLATION` |
| change confined to `ignored_by_base` paths | `primary_tree_ignored_divergence`, **reported, enumerated, not a violation by default** — §5.9.4 |
| administrative divergence (§5.8) | `POLICY_VIOLATION`, §8 row 4 |

The 11 dirty entries in the production repository are eleven paths whose stat
identity is the same before and after. **The invariant holds trivially and no
cleanliness is required** — same as today, now measured on the filesystem rather
than on git's opinion of it. **The dispatcher does not clean, reset, stash or
checkout the primary tree.**

#### 5.9.3 Fidelity, and the cost that forces the question

Measured: the production primary tree is **46,565 entries / 789.9 MB**.
`stat_identity` costs **466 ms** per walk; `content_hash_all` costs **~18 s cold /
~3.5 s warm** per walk. **Two walks per run.**

**Default: `stat_identity`**, and the rationale is that it is **strictly stronger
than what it replaces on every axis that matters**: it sees ignored paths
(`git status` cannot), it sees `.git/**` via §5.8 (`git status` cannot), it cannot
be blinded by index bits, ignore sources or `status.showUntrackedFiles`, and it
detects content change through `st_size` and `st_mtime_ns` where `git status`
detected it through the index's stat cache — **the same signal, minus git's
ability to be told to ignore it.**

**The residual:** a same-uid worker can modify a file, restore its exact size,
and `os.utime` its `mtime_ns` back. **`st_ctime_ns` also changes, is recorded,
and cannot be set by `utime`** — so a naive restoration **is** caught. A worker
that can `ctime`-forge needs to change the clock or the inode, a larger
capability. **`REQUIRES-PROBE`: `ctime` forgery resistance is reasoned, not
tested.**

`content_hash_all` is available and bounded; **Sol should decide whether the
production repository runs with it on.** The numbers are here; the decision is
policy, not engineering. *(Escalated as Z1-G-2, §18.1.)*

#### 5.9.4 The tension with §3.4's "no ignore list", named rather than papered over

§3.4 lists *"the primary-tree invariant with no excusal path and no ignore
list"*. §5.9.2's `primary_tree_ignored_divergence` class **looks** like an ignore
list. The distinction is precise enough to test:

- **Nothing is suppressed.** Every divergence is enumerated in
  `primary-tree-invariant.json` by `PathRepr` with its class. **There is no path
  the dispatcher observes and does not report.**
- **The previously-observable set keeps its previous verdict.** Everything
  `git status --porcelain` could have seen — tracked changes, non-ignored
  untracked additions, deletions, HEAD movement — is `POLICY_VIOLATION`, exactly
  as today. **Not one case is downgraded.**
- **The graded class is entirely new observation.** `git status` never saw
  ignored paths at all. Firing `POLICY_VIOLATION` on `__pycache__` churn, an
  editor swap file, or a concurrently-running test suite in the operator's own
  checkout would make the flag routine — the failure revision 2 itself names.
- `[policy].primary_ignored_divergence_is_violation = false` is the switch, it is
  reported in the gate report, and `test_primary_ignored_divergence_is_reported`
  asserts the paths are enumerated **regardless of the switch**.

**This is a real tension with a §3.4 line and it is escalated, not integrated
silently (Z1-G-2, §18.1).** The judgement offered: §3.4 was written against an
*excusal* (a rule that makes a violation not count), whereas this is a
*classification* of a strictly larger observation. If Sol disagrees, the switch
defaults to `true` and the cost is false `POLICY_VIOLATION`s on any repository
with build churn.

#### 5.9.5 `porcelain_status` — a compatibility surface, not an authority

`PrimaryTreeSnapshot.porcelain_status` and
`DispatcherObservations.primary_worktree_clean` are retained and **re-derived by
dispatcher code** from the primary `FsSnapshot` against a `BaseTreeSnapshot` of
the primary's own HEAD. Under `stat_identity` a same-size content change cannot
be distinguished, so **`primary_worktree_clean` becomes a tri-state**
(`True`/`False`/`None`) with a new `primary_clean_fidelity` field saying which.

**`None` never reads as clean.** Nothing in the ladder consumes
`primary_worktree_clean`; the verdict is `primary_tree_unchanged`, which is
`False` on any divergence and `None` on any failure to measure. **A reader that
treated `None` as `True` was already wrong** and now sees `None` more often.

*(Directive A vs the retained fields is escalated as Z1-G-3, §18.1: the
alternative — deleting them — is cleaner but touches `DispatcherObservations`,
which §2 protects. Compatibility was chosen.)*

### 5.10 The run reservation and the landing transaction

#### 5.10.1 Reservation — the directory is the allocation token

```python
class RunState(str, Enum):
    RESERVED = "reserved"; STARTING = "starting"; RUNNING = "running"
    FINALIZING = "finalizing"; LAND_INCOMPLETE = "land_incomplete"
    COMPLETE = "complete"; ABORTED_PRELAUNCH = "aborted_prelaunch"
    FINALIZATION_FAILED = "finalization_failed"; ORPHANED = "orphaned"
```

```
n = max(persisted runs_allocated, highest existing runs/NNN) + 1
loop:
    try: os.mkdir(runs/NNN, 0o700)          # ATOMIC. No exist_ok.
    except FileExistsError: n += 1; continue
    break
write runs/NNN/reservation.json atomically   (state = RESERVED)
persist TaskRecord.runs_allocated = n        (monotone high-water mark)
```

**An orphan `runs/NNN` can never be reused, because `mkdir` fails on it.** The
defect is closed by the filesystem, not by bookkeeping. Allocation is correct
even if `runs_allocated` was never persisted: the directory scan re-derives the
floor. `run_count` keeps its meaning and wire format; `runs_allocated` is what
the allocator reads, materialised on first use as
`max(run_count, highest existing runs/NNN)` — **a measurement, not a guess.**

Justification for each state, against §12's *"do not add states for
decoration"*: `RESERVED` (a crashed reservation is otherwise indistinguishable
from a crashed run) · `STARTING` (the window between spawn and a durable
ownership record — a different recovery decision from "no process was started")
· `RUNNING` · `FINALIZING` (distinguishes "died mid-evidence" from "died
mid-run") · **`LAND_INCOMPLETE`** (the only state that distinguishes "genuinely
running" from "stuck in `RUNNING` because a process died between two
`transition()` calls") · and four terminal states each named by the brief.
Rejected as decoration: `QUEUED`, `LOCKED`, `VALIDATING`, `REVIEWED`,
`CANCELLED`.

#### 5.10.2 The landing is a two-phase commit with a durable intent

```python
class LandingIntent(StrictModel):
    """What _land_state has DECIDED, written before it is APPLIED.

    Computed purely from artefacts already durable on disk, so recomputing it
    after a restart yields the identical answer. That is what makes replay
    DETERMINISTIC rather than a re-derivation from live state."""
    task_id: str; run_index: int; run_id: str; decided_at: datetime
    target_state: TaskState; reason: str
    transitions: list[str]
    updates: dict[str, Any]
    applied: bool = False
```

```
FINALIZE ──► dispatcher-result.json  ──► reservation = LAND_INCOMPLETE
         ──► landing.json (applied=false)
         ──► apply transitions one at a time
         ──► landing.json applied=true ──► reservation = COMPLETE
         ──► repository claim released
```

**Recovery (B-I12).** Reconciliation finds a `LAND_INCOMPLETE` reservation and:
if `applied` is true, finishes the bookkeeping; if false, **re-applies the
recorded transitions idempotently** — already in that state, skip; legal from the
current state, apply; **neither**, mark `FINALIZATION_FAILED` with the
discrepancy and **leave the task alone rather than forcing it**.

Idempotence comes from the intent being a *recorded decision*, not a
recomputation: **replay never re-runs the ladder.**

**The repository claim is held through `LAND_INCOMPLETE`** and released only at
`COMPLETE`, so the window never both strands the task **and** frees the
repository.

**PROVEN BY** — three tests, not one:
`test_landing_decision_is_a_pure_function_of_durable_artefacts` (run
`decide_landing` over the same run directory in **two fresh interpreter
processes**, compare canonical JSON with `decided_at` excluded; then again with
`os.environ` cleared and the CWD moved); `test_land_recovery_is_idempotent`
(**recovery run twice** in the same test); and
`test_apply_landing_is_a_fixed_point` (table-driven over the cross product of
every `TaskState` and every `transitions` list any ladder branch can emit,
asserting `apply(apply(x)) == apply(x)` and that the third rule never forces a
state).
**COULD THEY PASS WHILE FALSE?** The purity test could, if the impurity is a read
of live task state that happens to be identical in both runs — which is why it is
**paired with `test_landing_decision_reads_no_task_state` (AST: `decide_landing`
and everything it calls may not reference `self.store`)**, which is decidable.
The single-process idempotence test could pass if the ladder were re-run and
happened to agree — which is why the replay **asserts the ladder function was not
called**, via a seam counter rather than a mock of the world.
**IF MIS-WIRED** — a non-idempotent replay double-applies a transition, which
`state_history` records and the test reads directly.

**Two secondary ordering rules**, from R-10:
`changed-paths.json` is **written LAST** and its presence is the marker that
evidence collection completed — a run directory with `diff.patch` and no
`changed-paths.json` reconciles to `FINALIZATION_FAILED`, **never to "complete
with an assumed-true flag"**. And a **partial or unparseable claim file is
treated as an ACTIVE claim** (fail closed), not skipped.

### 5.11 Directive O — Fable completeness; every "clips as before" is deleted

#### 5.11.1 The contradiction revision 2 shipped

Revision 2 §5.4C quoted revision 1's compatibility sentence **as the defect** and
then left the same sentence standing in **both** compatibility tables:

- §5.12: *"…only Fable's prompt builder, which **clips at
  `_MAX_PROMPT_DIFF_CHARS` as before**."*
- §13: *"only Fable's prompt reads it, and **it clips as before**."*

An implementer checking "what changes for existing consumers?" reads §13,
implements the clip, and never builds `EvidenceExceedsReviewBudget`. **Amendment
11 is reported as applied and contradicted at the two places an implementer would
look.** Both sentences are **deleted** in revision 3, and §13 carries the
replacement text.

#### 5.11.2 Invariants

- **ZI-15 (no code path clips review input).** There is **no truncation, slice or
  `[:N]`** applied to the patch text anywhere on the review path.
  `_MAX_PROMPT_DIFF_CHARS` becomes a **comparison threshold that produces a
  refusal**, never an argument to a slice.
- **ZI-16 (what was measured is what was sent).** The bytes handed to the
  reviewer's argv are **byte-identical** to the bytes of `evidence/diff.patch`
  that `review_input_complete` was computed over. *(This is the G7-2 shape —
  "calculate complete using one source and review another" — closed for the
  review path.)*
- **ZI-17.** No sentence in `docs/**` asserts that the review input is clipped,
  truncated, elided or shortened.

#### 5.11.3 Mechanism

```python
# Wave B, review path, PREPARE phase — before any reviewer process starts.
patch_bytes = evidence.patch_path.stat().st_size
budget      = measured_review_input_budget(argv_block_without_patch)
review_input_complete = evidence.patch_file_complete and patch_bytes <= budget

if not evidence.patch_file_complete:
    raise EvidenceIncompleteForReview(omitted_capped=…, refused=…, reasons=…)
if not review_input_complete:
    raise EvidenceExceedsReviewBudget(patch_bytes=…, budget_bytes=budget, excess=…)
# else: the ENTIRE file is read and passed. No slice exists on this path.
```

Both are **PREPARE-phase refusals**: no reviewer tokens spent, no run index
consumed, `state.json` byte-identical.

#### 5.11.4 The budget is measured argv headroom, not a constant

```
budget = ARGV_TOTAL_LIMIT
       - sum(len(e) for e in the composed argv block EXCLUDING the patch)
       - ARGV_SAFETY_RESERVE
   capped at PER_ELEMENT_LIMIT (131,071 B, measured)
```

so the refusal fires **only when the patch genuinely cannot travel**, rather than
at an arbitrary 120,000. `_MAX_PROMPT_DIFF_CHARS` / `_MAX_PROMPT_PATCH_BYTES`
are **deleted as clip thresholds** and survive, if at all, only as the safety
reserve constant.

**OQ-B5 stays closed as revision 2 closed it:** the patch is delivered
**inline**, not by path. *"The reviewer received the evidence"* must remain
verifiable, and a file Fable may or may not `Read` is unobservable to the
dispatcher. Not re-litigated.

#### 5.11.5 Untextual and unrepresentable absences are carried, not clipped (Y-10)

| `ContentClass` | Blocks `patch_file_complete`? | Blocks the review? | Carried into the prompt as |
|---|---|---|---|
| `TEXT_CANDIDATE` | no | no | the content |
| `UNTEXTUAL` | yes | **no** | path, size, sha256 + *"no text representation"* |
| `UNREPRESENTABLE_KIND` (symlink/FIFO/socket/device) — **Y-10** | yes | **no** | path, `st_mode`, type name, link-target hash + the same sentence |
| **`BULK_CREATED_IGNORED`** *(`added` ∧ `ignored_by_base` ∧ over budget only)* | **YES** | **no** | per-directory rollup: prefix, count, total bytes |
| `OVERSIZED` | yes | **yes** | refusal |
| `UNREADABLE` / `CHANGED_DURING_MEASUREMENT` | yes | **yes** | refusal |

> **`IGNORED_BY_BASE` is gone from this table.** It was the only content-omitted
> class that did not clear `patch_file_complete`, and it is what made the
> directive-C attack land (§5.5.9A, B-3). **A `modified` base-ignored path is now
> in the patch in full and this table never sees it.**

**Why `UNREPRESENTABLE_KIND` must not block the review — measured:** this
repository contains **4** ignored symlinks and the production repository
contains **1**. Under revision 2's rule (`refused` non-empty ⇒
`patch_file_complete = False` ⇒ Fable refuses) **every Fable review of either
repository is dead**, for a reason that has nothing to do with the task. R-13's
reasoning applies unchanged: **a symlink has no text representation either.**
`refused` is reserved for the classes that genuinely mean *"we could not see
it"*. *Escalated for explicit ratification as Y-10 in §17.*

### 5.11A State transitions

**Subsystem B introduces no new `TaskState`.** It introduces one *run* state
machine, which lives in `runs/NNN/reservation.json` and interacts with the task
state machine only through `_land_state`, whose *decision* is unchanged and whose
*application* is now transactional (§5.10.2):

```
RESERVED ─► STARTING ─► RUNNING ─► FINALIZING ─► LAND_INCOMPLETE ─► COMPLETE
    │           │           │           │               │
    │           │           │           │               └─► FINALIZATION_FAILED
    │           │           │           └─► FINALIZATION_FAILED
    │           │           └─► ORPHANED                       (§7)
    │           └─► ORPHANED                                   (§7)
    └─► ABORTED_PRELAUNCH
```

The task-state effects Subsystem B can cause are exactly §8 rows 2, 3, 4, 5 and
5a. **Every one of them is reachable without Wave A's phase mechanism** (§12.2),
which is what makes Wave 0 self-sufficient.

### 5.11B Persistent data

```
state/repos/<repo-identity>/
  git-admin-baseline.json          NEW  operator-established, once per repository
  git-admin-baseline.sig           NEW  optional HMAC (§5.8.4)
  git-admin-divergence.json        NEW  written on a tamper verdict

state/tasks/<task-id>/
  state.json                       + runs_allocated, + lifecycle_preflight
  refusals.jsonl                   NEW  append-only PREPARE refusals (§3.1.6)
  preflight/lifecycle-feasibility.json                              (§4.7)
  materialisation/                 NEW  once per task, immutable
    base-tree.json                       BaseTreeSnapshot (no blob bytes)
    base-reconciliation.json             BaseReconciliation
    start-bytes/<hash>.bin               captured pre-worker bytes, content-addressed
  runs/NNN/
    reservation.json               NEW  run state + append-only history
    expectation.json               NEW  pre-spawn expectation; carries NO pid
    ownership.json                 NEW  written ONLY from a WorkerHandle
    landing.json                   NEW  LandingIntent; applied=true after the last
                                        transition
    git-invocations.jsonl          NEW  every _run_git call (§5.4.5)
    git-admin-pre.json             NEW  §5.8
    git-admin-post.json            NEW  §5.8
    fs-snapshot-start.json         NEW  FsSnapshot(role=task_worktree_start)
    fs-snapshot-post.json          NEW  FsSnapshot(role=task_worktree_post)
    events.jsonl                   NEW  raw stream-json NDJSON (§6.5)
    stdout.raw / stderr.log              the child's own files (§7.3)
    stdout.json                          retained excerpt
    worker-result.json / validation.json / claim-verification.json / timeout.json
    dispatcher-result.json               evidence-complete marker
  evidence/
    path-inventory.json            NEW  PathIdentitySet — written BEFORE scope
    diff.patch                           the canonical, dispatcher-composed patch
    changed-paths.json                   schema "changed-paths/2"; flags produced by
                                         the generator; **written LAST** — its
                                         presence is the evidence-complete marker
    diff-stat.txt / diff-check.json      dispatcher-composed
    ignore-classification.json     NEW  sources, oids, unsupported rules
    primary-fs-pre.json            NEW  FsSnapshot(role=primary_pre)
    primary-fs-post.json           NEW  FsSnapshot(role=primary_post)
    primary-tree-invariant.json          + divergence classes, fidelity, head_ref,
                                         admin verdict
    …retained: status.txt, evidence-phases.json, primary-tree-{before,after}.txt,
      worktree-base.json
```

Every path field in every artefact introduced here is a `PathRepr` object
(§5.7.1), never a bare string. Every file is written with the existing
`atomic_write_json` (temp file, fsync, `os.replace`, 0600 inside 0700).

### 5.12 Error taxonomy (Subsystem B)

| Code | Class | Phase | Landing |
|---|---|---|---|
| *(no exception)* `refused: <reason>` | — | FINALIZE | per-path bucket. **Never ends the run, never preempts the scope verdict.** |
| `PathIdentityUnrepresentable` | `DispatcherError` | FINALIZE | `FAILED` at ladder **row 5a**, never above rows 4/5 |
| `InventoryFilesystemUnsupported` | `GitEvidenceCollectionFailed` | PREPARE/FINALIZE | row 3 |
| `BaseTreeSnapshotFailed`, `BaseBlobUnreadable` | `GitEvidenceCollectionFailed` | PREPARE | refusal, no run consumed |
| `FilesystemSnapshotFailed` | `DispatcherError` | PREPARE / FINALIZE | PREPARE → refusal; FINALIZE → row 3 |
| `SnapshotBudgetExceeded` | `DispatcherError` | PREPARE **or** FINALIZE | PREPARE → refusal; FINALIZE → `FAILED`, partial snapshot preserved, `changed_paths` **absent** |
| `CheckoutTransformationBudgetExceeded` | `DispatcherError` | PREPARE | refusal |
| `RepositoryAdministrationUnestablished` / `Unreconciled` | `DispatcherError` | PREPARE | refusal; the second **not retryable** |
| `GitAdministrativeCaptureFailed` | `DispatcherError` | PREPARE / FINALIZE | PREPARE → refusal; **FINALIZE → the tamper verdict is `unknown`, treated as TAMPER, never as clean** |
| `RefResolutionFailed` | `DispatcherError` | PREPARE / FINALIZE | FINALIZE → `primary_tree_unchanged = None`, **not clean** |
| `UnsupportedRefStorage` | `DispatcherError` | PREPARE | refusal, with the measured value |
| `RepositoryLayoutUnreadable` | `DispatcherError` | PREPARE | refusal — the raw resolver could not decide **and** the `rev-parse` fallback failed (§5.8.2A) |
| `ForbiddenGitInvocation` | `InternalDispatcherError` | any | **a dispatcher defect. Raised, never logged-and-continued.** |
| `EvidenceIncompleteForReview` / `EvidenceExceedsReviewBudget` | `DispatcherError` | PREPARE (review) | refusal; `state.json` byte-identical |
| `RunReservationFailed` | `InternalDispatcherError` | RESERVE | `mkdir` failed for a reason other than `EEXIST` |
| `RunFinalizationFailed` | `DispatcherError` | FINALIZE | `FINALIZATION_FAILED`; streams and evidence preserved; index never reused |

### 5.13 Crash points

Subsystem B's rows are **C1–C13 and C15 of the canonical matrix (§15)**. This
section states **no count of its own**, per §3.5. Five points are new in
revision 3 relative to revision 1 and are named explicitly in §15.2:
**C9, C11, C12, C13, C14**.

### 5.14 Tests

Real disposable integration — real `git init`, real `git worktree add`, real
files, **no mocks of git**:

- **§10's headline case**: a **191-line untracked test file** appears in
  `changed_paths`, in `evidence/diff.patch` with all 191 lines, in
  `diff_total_bytes`, in `diff_stat`, and **in the Fable prompt** — asserted by
  capturing the argv the fake reviewer receives, not by a dispatcher-written log;
- `test_base_tree_snapshot_matches_ls_tree_for_hostile_names` — `café.txt`,
  `new\nline.txt`, `tab\there.txt`, `with space.txt`, an executable, a symlink,
  an empty file. Each appears once, with raw bytes;
- `test_base_blobs_are_raw_not_filtered` — **Z-RULE-1: `cat-file --filters` in
  the same test DOES fire the sentinel**;
- `test_checkout_transform_is_not_attributed_to_the_worker` — the
  `* text eol=crlf` fixture; a fake worker changes **one** line; `diff.patch`
  contains **exactly** that change and no CRLF churn;
- `test_lfs_shaped_repository_is_not_refused` — the test that pins Z-2 as (A);
- `test_resume_old_side_is_base_not_run1`;
- `test_snapshot_budget_refuses_in_prepare` / `test_post_snapshot_budget_fails_closed`
  (asserts `changed_paths` is **absent**, distinguishing truncation-with-empty-result
  from a real refusal);
- `test_baseline_venv_does_not_enter_changed_paths` — 4,000 pre-existing ignored
  files, unmodified; `changed_paths` empty, `unchanged_count == 4000`,
  `scope.valid is True`. **The direct killer for S-3.**
- `test_modification_to_existing_ignored_file_is_detected` — the persistence
  backdoor;
- `test_forbidden_ignored_path_is_still_forbidden`;
- `test_v5_self_hiding_gitignore_still_inventoried` — **Z-RULE-1: the same
  fixture through `git ls-files --others --exclude-standard` yields the empty
  list, proving the fixture really is the attack**;
- `test_index_bits_have_no_authority` — `--assume-unchanged` **and**
  `--skip-worktree` plus modification; both appear. **Z-RULE-1: the same fixture
  through the legacy `collect_diff_evidence` yields `changed_paths == []`**;
- `test_v2_forbidden_nonascii_path_is_caught` — **Z-RULE-1: the legacy `str`
  `check_scope` given the C-quoted form returns `valid=True`**, proving the
  fixture is the bypass;
- `test_hostile_names_survive_the_whole_pipeline`;
- `test_unrepresentable_path_does_not_preempt_policy_violation` — **the killer
  for Z1-N2**;
- `test_unrepresentable_path_in_scope_fails_closed` — asserts the path is
  *present* in the evidence with `raw_b64`;
- `test_unreconciled_admin_state_refuses_before_worktree_add` — **Z-RULE-1: with
  the baseline re-trusted to include the poisoned config, the worktree IS created
  and the sentinel DOES fire**, proving the gate is what stopped it;
- `test_info_attributes_write_is_policy_violation`, and the next dispatch refuses
  **having run zero git commands**;
- `test_config_worktree_hiding_is_caught`, `test_include_path_indirection_is_followed`,
  `test_unparseable_config_is_divergence_not_silence`;
- `test_primary_tree_measured_without_git` — no journal row with
  `cwd_role == "primary"` after worker launch;
- `test_assume_unchanged_on_primary_does_not_blind_primary_check` — **Z-RULE-1:
  the same fixture through `git status --porcelain` yields the empty string**;
- `test_primary_dirty_tree_invariant_holds` — an 11-entry dirty fixture
  reproducing production's shape; **nothing is cleaned, reset or stashed**;
- `test_worktree_index_untouched_by_evidence` — sha256 + mtime of the worktree's
  index across the whole pipeline. **Under ZI-19 this should now be trivially
  true; keeping it is cheap and it is the killer for a regression to a
  `read-tree` design.**
- crash injection at the canonical points (§15), **C12 run twice**.

`test_ignore_matcher_agrees_with_git_on_a_corpus` is **advisory only, never
gating** — `check-ignore` is prohibited in production and this is a development
aid. **`REQUIRES-PROBE`: the corpus does not exist.**

**The honest residual on agreement tests.** An agreement test cannot prove
agreement on inputs nobody generated. That is why the producer's limits — renames,
submodules, filesystem semantics — are enumerated with a **named refusal** for the
one that would silently corrupt identity.

### 5.15 Mutation cases

**Wave 0 — evidence authority, identity, admin, primary tree**

| Mutant | Named targeted killer |
|---|---|
| ZM-A1…ZM-A6, ZM-A11b | §5.4.7 |
| **ZM-B1** use the base blob as the old side unconditionally | `test_checkout_transform_is_not_attributed_to_the_worker` |
| **ZM-B2** recompute `BaseReconciliation` per run | `test_resume_old_side_is_base_not_run1` |
| **ZM-B3** capture `start-bytes` lazily at FINALIZE | `test_worker_cannot_forge_the_old_side` |
| **ZM-B4** use `cat-file <rev>:<path>` instead of object ids | `test_base_blob_fetch_survives_newline_path` |
| **ZM-B5** `readline()` the `--batch` payload | same, plus `test_base_blob_with_embedded_newlines` |
| **ZM-B6** follow symlinks in the walk | `test_symlink_to_outside_worktree_is_recorded_not_followed` |
| **ZM-B7** skip unreadable files instead of recording them | `test_unreadable_file_is_recorded_with_read_error` |
| **ZM-B8** silently truncate at the budget instead of raising | `test_post_snapshot_budget_fails_closed` |
| **ZM-B9** degrade the task worktree to `stat_identity` | `test_task_worktree_fidelity_is_content_hash_all` + `test_mtime_forged_modification_is_detected` |
| **ZM-B10** re-walk after a crash instead of reusing the durable POST snapshot | `test_crash_before_inventory_recovers_from_durable_snapshots` |
| **ZM-C1** consult the live worktree `.gitignore` | `test_v5_self_hiding_gitignore_still_inventoried` |
| **ZM-C2** fold the ignored set into `changed_paths` | `test_baseline_venv_does_not_enter_changed_paths` |
| **ZM-C3** let `ignored_by_base` suppress a `forbidden_paths` match | `test_forbidden_ignored_path_is_still_forbidden` |
| **ZM-C4** classify as ignored on an unsupported rule | `test_unsupported_ignore_rule_reports_rather_than_hides` |
| **ZM-C5** consult `core.excludesFile` | `test_excludes_file_is_not_consulted` |
| **ZM-C6** compute the delta from the absolute POST set | `test_baseline_venv_does_not_enter_changed_paths` |
| **ZM-D1** decode paths to `str` before `check_scope` | `test_v2_forbidden_nonascii_path_is_caught` |
| **ZM-D2** use `PathRepr.display` for matching | `test_display_form_never_reaches_check_scope` |
| **ZM-D3** move `PathIdentityUnrepresentable` back above the policy rows | `test_unrepresentable_path_does_not_preempt_policy_violation` |
| **ZM-D4** drop the unrepresentable path instead of failing | `test_unrepresentable_path_in_scope_fails_closed` |
| **ZM-D5** parse paths out of the composed patch header | `test_paths_only_from_two_producers` (AST) + `test_hostile_names_survive_the_whole_pipeline` |
| **ZM-D6** split `ls-tree -z --long` on the last TAB | `test_base_tree_snapshot_matches_ls_tree_for_hostile_names` |
| **ZM-E1** run the admin capture after `worktree add` | `test_unreconciled_admin_state_refuses_before_worktree_add` |
| **ZM-E2** capture with `git config --list` | `test_admin_capture_runs_no_git_command` |
| **ZM-E3** treat a missing baseline as "trust current" | `test_missing_baseline_refuses` |
| **ZM-E4** treat a FINALIZE capture failure as clean | `test_admin_capture_failure_is_tamper` |
| **ZM-E5** re-establish the baseline automatically after divergence | `test_divergence_persists_across_dispatches` |
| **ZM-E6** stop following `include.path` | `test_include_path_indirection_is_followed` |
| **ZM-E7** re-introduce the clean `GIT_INDEX_FILE` + `ls-files -v` audit | `test_finalize_journal_is_catfile_and_b2_revparse_only` |
| **ZM-E8** allowlist `config.worktree` | `test_config_worktree_hiding_is_caught` |
| **ZM-F1** restore `snapshot_primary_tree -> git status` | `test_primary_tree_measured_without_git` + `test_v1_filter_program_not_executed` |
| **ZM-F2** use `resolve_base_commit(repo,"HEAD")` post-worker | `test_primary_tree_measured_without_git` |
| **ZM-F3** require the primary tree to be clean rather than unchanged | `test_primary_dirty_tree_invariant_holds` |
| **ZM-F4** clean/reset/stash the primary before measuring | same |
| **ZM-F5** treat a snapshot failure as `unchanged` | `test_primary_snapshot_failure_is_unknown_not_clean` |
| **ZM-F7** degrade `primary_worktree_clean` to a bool defaulting `True` | `test_primary_clean_is_none_under_stat_identity_size_match` |
| **Z-M6** `lstat` during stage 1 and let a `ContentClass` drop a path | `test_no_lstat_before_the_scope_verdict` + `test_out_of_scope_symlink_lands_policy_violation` |
| **Z-M9** make `decided_over_digest` a copy of itself | `test_scope_verdict_digest_matches_identity_digest` |

**Wave B — content, transaction, review**

| Mutant | Named targeted killer |
|---|---|
| set `patch_file_complete = True` unconditionally | `test_completeness_flag_has_no_setter` + the omitted/refused tests |
| **Z-M16** reorder the ladder so an evidence refusal preempts scope | `test_out_of_scope_symlink_lands_policy_violation` + `test_deliberately_conflicting_run_lands_policy_violation` |
| **Z-M17** make a per-path refusal fatal to the run | same |
| **Z-M27** reintroduce the clip in the prompt builder | `test_review_input_bytes_equal_patch_file_bytes` + `test_review_prompt_builder_has_no_truncation` |
| **Z-M28** compare the patch **file** size but send a clipped string | `test_review_input_bytes_equal_patch_file_bytes` |
| **Z-M29** set `review_input_complete = True` unconditionally | `test_oversized_patch_refuses_review` |
| **Z-M30** express the budget as the old constant | `test_review_budget_is_derived_from_measured_argv_headroom` |
| **Z-M31** let `UNREPRESENTABLE_KIND` block the review | `test_symlink_only_absences_do_not_block_review` |
| **Z-M32** let `OVERSIZED` **not** block the review | `test_oversized_patch_refuses_review` |
| **Z-M33** restore the clip sentence to §13 | `test_no_document_claims_the_review_input_is_clipped` |
| replace `reserve_run()` with `run_count + 1` / `mkdir(exist_ok=True)` | `test_orphan_run_directory_never_reused` |
| `git add -N`, or create a temporary index | `test_worktree_index_untouched_by_evidence` |
| delete the run directory on evidence failure | `test_failed_run_directory_preserved` |
| skip `landing.json`; apply transitions directly | `test_crash_during_land_state_recovers` |
| make landing replay non-idempotent | `test_land_recovery_is_idempotent` + `test_apply_landing_is_a_fixed_point` |

> `test_no_document_claims_the_review_input_is_clipped` scans `docs/**` for a
> banned-phrase list. **It could pass while the property is false — a paraphrase
> evades it.** Stated plainly: it catches *recurrence of the known sentence*,
> which is what actually happened twice. **It is a tripwire, not a proof. The
> proof is `test_review_input_bytes_equal_patch_file_bytes`.**

### 5.16 Backward compatibility

- `changed-paths.json` gains `schema: "changed-paths/2"` and new keys; **every v1
  key keeps its meaning**, and v1 readers that ignore unknown keys still work.
- **Two deliberate, visible behaviour changes**, which must not be buried as
  additive keys: (i) a worker-created file inside a base-ignored directory now
  **appears** in `changed_paths` where `--exclude-standard` hid it — that is the
  G7-2 fix; (ii) some runs that previously landed `FAILED` now land
  `POLICY_VIOLATION` — strictly more informative, and the direction §28 requires.
- `evidence/diff.patch` becomes strictly larger. **Fable's prompt reads it in
  full or the review is refused; it is never clipped.**
- `DiffEvidence` keeps its name and every field name.
  `DispatcherObservations.changed_paths` / `out_of_scope_paths` /
  `forbidden_paths_touched` keep `list[str]`, populated from `display`, with
  `*_v2` `PathRepr` companions. **`check_scope` is never given either.**
- `primary_worktree_clean` widens to a genuine tri-state within the same Python
  type; `PrimaryTreeSnapshot` keeps its class name and its two public fields.
- `SCHEMA_VERSION` does **not** bump. `TaskEnvelope` is untouched.
- **A new PREPARE refusal at the first Gate-7 dispatch against any repository:**
  every repository needs a trusted administrative baseline established once, by
  an operator command. **This is a migration step and it is in §13.**
- `docs/INTERFACES.md` §5 changes in the same wave: `check_scope` takes bytes;
  `collect_diff_evidence`, `write_full_diff` and `primary_tree_status` are
  removed from the contract.
- `docs/SECURITY.md` is amended **in Wave 0**, and the honest sentence is:
  > *"The dispatcher's post-worker evidence pipeline executes no
  > repository-supplied program. The dispatcher's PREPARE-time `git worktree add`
  > performs a checkout, which does execute repository-configured filters and
  > hooks; it is gated on the administrative reconciliation in §5.8, and that
  > gate is detection-plus-refusal, not an OS boundary."*
  **Revision 2's version of that sentence must not ship — it would be false for
  PREPARE.**

---

## 6. SUBSYSTEM C — Timeout and progress execution

Covers **G7-3** and **G7-4**. **Nothing in this subsystem is conditional.** Lane
U's probe answered every question revision 1 left open; directive S carries the
findings as binding and forbids softening them.

### 6.0 Lane U's capability findings — carried verbatim, not re-litigated

**Installed clients: Claude Code 2.1.237, Codex CLI 0.149.0.** The brief's
"0.147.0" is stale; every Codex finding describes **0.149.0**.

| # | Question | **Measured verdict** |
|---|---|---|
| U-1 | Claude CLI incremental machine-readable events | **SUPPORTED.** `--print --verbose --output-format stream-json` emits incrementally-flushed NDJSON with **exactly one** authoritative `type: "result"` final event. |
| U-1b | Do partial events survive a mid-run kill? | **YES — the decisive G7-3 result.** SIGKILL at 12 s (wait status 137): **34/34 lines valid JSON, no torn final line, 0 `result` events, 10 recovered `tool_use` events matching 10 files actually on disk.** Line-oriented flushing means a killed stream is never syntactically corrupt, and **absence of the final result event is measurable.** |
| U-1c | Cost accounting on kill | **ABSENT.** No `result` ⇒ no `usage`, no `total_cost_usd`. Killed runs really do consume tokens; the CLI provides no accounting. |
| U-2 | Soft-deadline / finalization mechanism | **NOT AVAILABLE on 2.1.237.** SIGTERM: dead in under 1 s, exit 143, the stream did not grow by one line, **no `result` event**. `--input-format stream-json`: a "STOP" injected at t=10 s was honoured only after the entire in-flight turn completed, with **eight more files written after the stop request**. Time-to-finalization equals the remaining turn duration — **exactly the unbounded quantity a soft deadline must bound.** |
| U-2b | B3 hazard in stream-json **input** mode | **`--input-format stream-json` does NOT reliably yield one `result` event** — mid-flight injection coalesced two logical turns into one envelope. Default `text` input produced exactly one in every run. **Adopting stream-json input would weaken B3.** |
| U-3 | Does Codex send a `progressToken`? | **YES.** `progress_token: 1`, protocol `2025-06-18`. |
| U-4 | Does Codex receive the notifications? | **YES — all 10 crossed the wire** during a single 30 s blocking call. |
| U-4b | Does Codex **surface** them? | **NO.** Zero in `--json`, zero in human output, zero in the rollout. |
| U-5 | **Does progress cause model inference turns?** | **ZERO.** Counted from the session rollout, not asserted: exactly one `task_started`/`task_complete` pair. A/B control at identical prompt and duration: 10 ticks → 1 turn, 0 ticks → 1 turn. Every `progress` substring in the rollout is a field **name** echoed inside the tool *result*, never notification content. |
| U-0 | Server-side positive control | **WORKS.** With a callback: 6 sent, **6 received**, no errors. Without a token: **0 received, NO ERROR** — the SDK silently no-ops, which is the §18 requirement satisfied by the SDK itself. |

**§35 classification: G7-4 = CLIENT-LIMITATION.** Server side protocol-correct
and provably emitting; Codex receives and discards; zero model turns; zero
polling; no-token path error-free. **This does not block the correctness gate.**

**Binding prohibitions carried from Lane U:** do not assume any soft-deadline
mechanism exists (**there is none**); do not assume a timed-out run yields cost
data; do not adopt `--input-format stream-json`; do not assume `stream-json`
works without `--verbose`; **do not assume Sol will ever see the progress**; do
not treat an absent `progressToken` as an error. **And do not reintroduce
`get_task` polling — zero model-driven polling is a §2 non-regression item and is
not negotiable.**

**Version pin (Z-I22).** `scripts/gate/client_versions.py` records
`claude --version` and `codex --version` at gate time and compares against
`docs/gate7-probes/CLIENT-VERSIONS.txt`. A mismatch is a **gate failure with a
named remediation: re-run Lane U's probe.** *This is a gate-time script, never a
pytest test* — `CLAUDE.md` §3 forbids spawning a real `claude` or `codex` child
from a test or build step, **and that rule is not bent for convenience.**
**COULD IT PASS WHILE FALSE?** Yes in one way: it proves the versions match, not
that the findings still hold. That is why a mismatch **mandates re-running the
probe** rather than re-asserting the table.

### 6.1 Current failure

**The remediation lies by construction.** `server.py:2054` and `:2588` emit
*"partial stdout preserved in the run directory"* unconditionally, without ever
consulting `worker_run.stdout_total_bytes`. A worker that emitted nothing
produces both strings verbatim.

**Trusted validation is skipped on the wrong grounds.** `server.py:2100` gates
`run_validations` on `not worker_run.timed_out` — the *process outcome*, not the
*state of the worktree*. A worker that made complete, in-scope, correct changes
and then hung has its `pytest` skipped, even though the changes are preserved and
the B2 invariant has just been re-verified.

**There is no deadline structure**, and **no progress surface at all**.

### 6.2 New invariants

- **C-I1 (measured remediation).** Every statement about preserved output is
  derived from a counter. Zero bytes ⇒ *"Claude emitted no stdout before
  timeout."*
- **C-I2 (timeout stays TIMED_OUT).** Post-timeout validation is evidence. It
  never changes the landed state.
- **C-I3 (preconditions are about the tree, not the process).**
- **C-I4 (dispatcher evidence, never a worker claim).** `source="dispatcher"`,
  `phase="post_timeout"`.
- **C-I5 (zero polling, zero model turns).** No fifth tool. If progress caused
  model turns it would be disabled rather than kept.
- **C-I6 (observational and bounded).** Phase transitions plus a sparse
  heartbeat. Never prompt, skill text, guidance, raw stdout/stderr, argv, file
  contents or model reasoning.
- **C-I7 (no manufactured progress).**
- **Z-I23 (no polling path exists).** No code path in the progress or timeout
  implementation references `get_task`.
- **Z-I24 (fire-and-forget).** Nothing blocks on, awaits or conditions behaviour
  upon a client acknowledging progress, and **no user-visible promise is made
  that Sol sees it.**

### 6.3 The deadlines

```
t0 ── soft deadline ──── hard deadline ── SIGTERM ── grace ── SIGKILL ── reap
                                                                          │
                                          evidence + validation window ◄──┘
```

**There is no finalization window.** Lane U measured that no mechanism exists to
request completion before the kill, so evidence and validation time is budgeted
**after** the kill. The soft deadline survives **only as a measurement** — a
recorded instant and a progress phase — and **a test asserts no signal, no write
and no process action is taken at it.** *(OQ-C1 decided: keep it. It is not a
"deadline that does nothing"; it is evidence about how close the run came, and
the hook a future mechanism would attach to. It must not grow a behaviour before
one is proven.)*

**DECISION D-7, confirmed by measurement rather than caution: V1 ships no
soft-deadline signalling.** The child's stdin stays `DEVNULL`.

### 6.4 Timeout evidence — and `stdout_bytes` has ONE definition

**R-11 first.** Revision 1 sourced `stdout_bytes` "from `StreamCapture.total` /
spool stat" while `stderr.log` was redacted and re-rendered on the way to disk,
so its size was not the child's byte count — and after file-backing both files
hold raw child bytes. A Wave C test asserting *"partial-output timeout preserves
exact measured partial bytes"* would have been written against one definition and
silently reinterpreted two waves later.

1. **Definition, fixed before either wave:** `stdout_bytes` / `stderr_bytes` are
   **the number of bytes the child process wrote to that stream**. Not the
   retained excerpt's length, not the rendered file's size, not a pump counter.
   **After Wave D it is `st_size` of the child's own stdout file**, so the
   definition and its source agree by construction.
2. **Wave D runs BEFORE Wave C** (§12) precisely so this is true when C's central
   claim — *the number is measured, not asserted* — is made.

```python
class TimeoutEvidence(StrictModel):
    timed_out: bool; killed_with_sigkill: bool
    soft_deadline_seconds: int | None; hard_deadline_seconds: int
    elapsed_ms: int
    stdout_bytes: int; stderr_bytes: int          # st_size of the child's files
    stdout_partial_available: bool; stderr_partial_available: bool
    structured_result_available: bool             # a `result` EVENT was present
    worker_patch_available: bool
    last_output_at: datetime | None
    post_timeout_validation: Literal["ran","skipped","not_applicable"]
    post_timeout_validation_skip_reason: str | None
    # deliberately ABSENT: any cost field for a timed-out run (U-1c)
```

The zero case reads, verbatim: *"Claude emitted no stdout before timeout. No
structured result was produced. stderr: 0 bytes. The worktree contains N changed
path(s), preserved at `<path>`, and the session id is preserved for resume."*
The non-zero case names exact byte counts. **Nothing says "partial output
preserved" unless `stdout_bytes > 0`.**

**The cost gap is carried honestly.** A killed run emits no `usage` and no
`total_cost_usd` but really does consume tokens, so `TimeoutEvidence` has **no
cost field** for a timed-out run and the remediation says *"the provider consumed
tokens for this run; the CLI emits no accounting for a killed run, so the
dispatcher cannot state the cost."* **Inventing a zero, or extrapolating from
`num_turns`, would be exactly the manufactured fact §14 forbids.**

### 6.5 Streaming events — MEASURED SUPPORTED, adopted

```
claude --print --verbose --output-format stream-json  …  < /dev/null
```

`--verbose` is required in print mode (measured; undocumented). `--input-format`
stays at its default **`text`** because stream-json input was measured **not** to
yield exactly one `result` event.

- the raw NDJSON is spooled **unparsed and complete** to `runs/NNN/events.jsonl`
  — which, after file-backing, is the child's own stdout file, **durable by
  construction, surviving dispatcher death, needing no pump**;
- the structured result is extracted **only** from the single `type: "result"`
  event. Intermediate `assistant`/`text`/`tool_use`/`user`/`system` events are
  never treated as the result;
- **B3 is intact and strengthened**: the `result` event carries
  `api_error_status`, `terminal_reason`, `subtype`, `is_error`, `stop_reason`,
  `usage`, `session_id` — every field `envelope_facts` reads. The payload veto
  and marker-key check are unchanged, and "exactly one authoritative envelope" is
  now **measured** rather than assumed;
- **absence of a `result` event is the definitive kill/timeout signal**, measured,
  not inferred from an exit code;
- the parser tolerates a truncated trailing line **on principle**, even though
  none was observed under SIGKILL — and a **genuinely corrupt** stream is
  **refused, not repaired** (`test_torn_final_line_is_refused_not_repaired`);
- §16's remediation facts derive from the recovered event stream, and recovered
  `tool_use` events are listed as **dispatcher-observed activity, never as a
  worker claim.**

**B3 tail-read invariant.** After file-backing, the retained excerpt is a
**read-time** policy and the authoritative envelope is at the **end** of the
stream. `test_b3_envelope_recovered_from_multi_megabyte_stream` asserts the tail
is always read. §2 lists B3 as a non-regression, and a silent degradation on
large runs is exactly the kind this gate exists to catch.

### 6.6 Post-timeout trusted validation

Preconditions, all measured, in order: the B2 base invariant held; the worktree
is still registered at the recorded path; the primary-tree fingerprint was
measurable both before and after; the canonical evidence produced a
`PathIdentitySet` **and did not raise an inventory-level failure** (a per-path
`refused` bucket does **not** block validation — B-I3); the commands are the
envelope's own, which is structural; and the remaining wall-clock fits the
aggregate budget.

If all hold, `run_validations` runs exactly as on the normal path and the results
are recorded with `phase="post_timeout"`. If any fails, validation is **skipped
with a typed reason recorded — never silently.**

**`_land_state` is not touched.** The timeout branch still fires on
`worker_run.timed_out`, still ahead of the provider branch, still behind the
policy branch. Validation results are attached to the `RunRecord`; they do not
enter the state decision, **so C-I2 is true by construction as well as by test.**

### 6.7 Progress — server side, and the honest limit

The installed SDK's `Context.report_progress(progress, total, message)` is
request-scoped and documented as *"a no-op when no token was supplied"* — so
"no `progressToken` → no error, no polling" is a property of the SDK.

**The architectural problem is Gate 6, not the SDK.** Progress is *request*
scoped; the run is deliberately *not* (`RunRegistry` + `asyncio.shield`). A naive
implementation would hand the run a `Context` and reintroduce exactly the
coupling Gate 6 removed.

**DECISION D-8: a per-run-key progress bus inside `RunRegistry`.** The run
**publishes**; waiters **subscribe**. `RunRegistry.run(key, factory, *,
on_progress)` starts a **separate relay task** that drains the bus; **the relay
is cancelled with the waiter, the run is not.** Two waiters on the same key each
get their own relay. With no `on_progress`, the bus still records phases for the
run record and nothing is emitted.

**Throttle:** phase transitions immediately; a heartbeat at most every
`[progress].heartbeat_seconds` (proposed 30) and only if the phase has not
changed; an absolute ceiling of one notification per second, enforced in the
relay. **The byte pump never publishes.**

**Content:** `message` is drawn from a **closed set of format strings** with only
bounded, non-secret substitutions. **There is no code path from stdout, stderr,
prompt, argv, guidance or skill text to `report_progress`**, asserted by a
closed-set reflection test and a planted-credential test.

**Fire-and-forget is a hard rule.** Codex receives every notification and
surfaces none, so nothing may block on, await, retry or condition behaviour upon
acknowledgement, and **no user-visible text may promise that Sol sees it.** A
test asserts `report_progress` failures are swallowed and never propagate into
the tool result.

### 6.8 The `codex exec` hazard

**`codex exec` auto-writes a project trust stanza into `~/.codex/config.toml`**
for whatever directory it runs in, and **`--ignore-user-config` prevents the
*load*, not the *write-back*.** Lane U hit this and restored the file, verified
byte-identical by sha256.

**DECISION D-12:** every Gate-7 procedure invoking `codex exec` runs inside
snapshot → run → restore → **verify-by-sha256**, and **a mismatch is a HARD
FAILURE of the procedure, never "restored, probably fine"**. The recorded sha256
goes into the gate report as evidence that *"`~/.codex` semantic changes: NONE"*
was **measured, not assumed**.

**No Gate-7 test in `tests/**` may shell out to `codex exec`** — `CLAUDE.md` §3
forbids it and the suite must remain runnable without touching the operator's
home. Codex conformance lives in a deliberately-invoked harness under `scripts/`.
**`--ignore-user-config` is used anyway** (it correctly isolates what Codex
*reads*) but **must not be recorded as protection against the write** — believing
a flag does something it does not is the same class of error as claiming pipe
reattachment.

### 6.9 State transitions, persistent data, error taxonomy

No new `TaskState`, no new `RunState`. Additions: `runs/NNN/timeout.json`,
`runs/NNN/events.jsonl` (**additive and unconditional** — U-1 discharged the
condition), and `ValidationResult.phase`.

| Code | Class | Meaning |
|---|---|---|
| `ClaudeTimedOut` | existing | unchanged, but its `remediation` is composed from `TimeoutEvidence` |
| *(not an error)* `post_timeout_validation_skip_reason` | — | skipping is not a failure |
| *(not an error)* absent `progressToken` | — | the normal case |

### 6.10 Crash points

Subsystem C introduces **no canonical rows**. Its four durable-write points map
onto **C3, C4 and C7** and are listed in §15.4.

### 6.11 Tests

- unit: remediation composition for (0 bytes, some bytes, structured result
  present/absent, patch present/absent) — the zero case asserts the **literal
  sentence**;
- unit: the precondition matrix, each false case producing its own typed reason;
- unit: throttle, closed-message-set reflection, credential non-leakage;
- `test_absent_result_event_is_classified_as_timeout` (fixture NDJSON: 34 valid
  lines, no `result`); `test_torn_final_line_is_refused_not_repaired`;
- `test_input_format_is_text`; `test_no_finalization_window_is_requested_of_the_child`
  (AST: nothing writes to the child's stdin);
- `test_b3_envelope_recovered_from_multi_megabyte_stream`;
- integration with a **child that ignores `SIGTERM`** (§10.2 rule 7): zero-output
  timeout says zero output; partial-output timeout preserves exact measured
  bytes; changed worktree + timeout runs trusted validation; timeout + unsafe B2
  state skips with a recorded reason; **passing validation does not convert
  `TIMED_OUT` to success**; the worktree is preserved;
- integration over **real MCP stdio** with a client supplying a `progressToken`:
  notifications arrive while one blocking call is pending; **`get_task` call
  count is 0**; no secrets in any notification; throttling holds; and a second
  run with **no** token produces no error and no polling;
- gate-time only: `client_versions.py`, and the A/B rollout turn count.

### 6.12 Mutation cases

| Mutant | Named targeted killer |
|---|---|
| claim partial stdout when zero bytes | `test_zero_output_timeout_says_zero_output` |
| skip timeout validation unconditionally | `test_timeout_with_valid_worktree_runs_trusted_validation` |
| progress handler invokes `get_task` | `test_no_progress_path_references_get_task` (AST) + the real-stdio zero-poll assertion |
| progress causes a model-facing poll loop | `test_progress_send_is_never_awaited_for_acknowledgement` + the gate-time rollout count |
| let passing post-timeout validation land `IMPLEMENTED` | `test_timed_out_stays_timed_out` **and** the state machine itself |
| gate post-timeout validation on `worker_run.timed_out` again | the precondition-matrix test |
| skip validation silently | `timeout.json` asserts a non-null skip reason whenever the status is `skipped` |
| emit progress per output line or per byte | the throttle test |
| interpolate stdout/stderr/argv into a `message` | closed-set reflection + planted-credential |
| call `report_progress` from the run instead of the relay | Gate 6 regression: cancel the waiter, assert the run still completes |
| **Z-M42** treat a missing `result` event as success | `test_absent_result_event_is_classified_as_timeout` |
| **Z-M43** switch to `--input-format stream-json` | `test_input_format_is_text` |
| **Z-M44** send a stop message to the child's stdin as a "soft deadline" | `test_no_finalization_window_is_requested_of_the_child` |
| **Z-M45** read only the head of the child's stdout for the excerpt | `test_b3_envelope_recovered_from_multi_megabyte_stream` |
| signal the child's stdin at the soft deadline | `test_stdin_is_devnull_and_never_written` |
| invoke `codex exec` from `tests/**` | a repository-wide grep test |
| drop the sha256 verification from the Codex config wrapper | harness self-test: deliberately corrupt the restore, assert the wrapper fails |

### 6.13 Backward compatibility

`ValidationResult` gains `phase: Literal["post_run","post_timeout"] = "post_run"`,
so persisted results load unchanged. `RunRecord` gains an optional
`timeout_evidence`. `events.jsonl` is additive and **no longer described as
"conditional" anywhere**. The `blocking` envelope on every tool result is
unchanged. Progress is additive and invisible to a client that does not ask.
`~/.codex/config.toml` receives **no dispatcher change**.

---

## 7. SUBSYSTEM D — Durable worker ownership and recovery

Covers **G7-8**, and absorbs directives **H** (legacy reconciliation, fixes S-4),
**I** (concurrent Codex sessions, fixes S-5) and **J** (the recovery deadline).

### 7.1 Current failure

`RunRegistry` holds `asyncio.Task` objects in one process. The child is created
with `stdout=PIPE, stderr=PIPE, start_new_session=True`, so the only handle on it
is a pipe pair owned by that process's event loop. If the dispatcher dies while a
worker lives: **no persisted record of the child's identity**; the `flock` is
released by the kernel, so a new dispatcher acquires it and starts a **second
worker**; the child's pipe read ends are closed, so it gets `EPIPE` on its next
write — which may be much later or never, and it is in its own session so it gets
no `SIGHUP`; and the task is frozen in `RUNNING`.

Two facts the reviews added:

- **`Dispatcher.drain()` exists and `main()` never calls it**, so `SIGTERM`
  orphans in-flight workers today.
- **Revision 2's `RunOwnership` carries `dispatcher_owner_instance_id`,
  `dispatcher_pid` and `dispatcher_boot_id` — and §7.6 never reads them.**
  Opening a second Codex session while a long worker runs could therefore kill
  that worker, mark its run `ORPHANED`, and close its repository. That is S-5.

### 7.2 New invariants

| id | Invariant |
|---|---|
| **D-I1** | Ownership is durable, not process-local: before a run is `RUNNING`, a record naming the child's identity is on disk. |
| **D-I2** | **Write after, never before.** The ownership record is written **after** `create_subprocess_exec` returns and the real pid is known. |
| **D-I3** | **PID alone is never identity.** Liveness uses `(boot_id, pid, /proc starttime)` corroborated by `/proc/<pid>/exe` realpath and process group. **PID reuse is assumed to happen.** |
| **D-I4** | **Never guess.** The probe returns exactly `ALIVE_SAME`, `GONE` or `AMBIGUOUS`. `AMBIGUOUS` is never resolved by inference. |
| **D-I5** | **No fictional reattachment.** The design never claims to re-own a previous process's pipes. It **eliminates the pipes** and, where a run cannot be resolved, declares `ORPHANED` honestly. |
| **D-I6** | No duplicate worker, ever — across process restart, where `flock` alone cannot help. |
| **D-I7** | Recovery destroys nothing: never deletes a run directory, never reuses an index, never reuses a worktree, never marks a run successful, never calls an orphan a normal timeout. |
| **D-I8** | Recovery decides nothing for Sol. It records facts and surfaces them. |
| **I-I1** | **No production-wide singleton.** Multiple Dispatcher instances may run concurrently on the same host against different repositories, indefinitely. **Any change that prevents this is a regression with its own killer test.** |
| **I-I4** | Reconciliation **classifies the OWNER first**. No other action is evaluated before the classification. |
| **I-I5** | `OWNER_ALIVE_SAME` → do not signal · do not rewrite the claim · do not mark orphaned · the repository remains **busy** to the second server. |
| **I-I8** | Owner classification uses **two independent signals** — the `/proc` triple and a kernel-held liveness lock — and **disagreement is `OWNER_AMBIGUOUS`**, never resolved by preferring one. |
| **I-I9** | The code path that emits a signal is **reachable only while holding the dead owner's liveness lock**, which the kernel will not grant while that owner lives. |
| **I-I10** | Recovery of one repository's claims is **single-flight across processes**. |
| **H-I1** | Startup reconciliation operates **ONLY** on a persisted Gate-7 claim. |
| **H-I2** | **An ownership claim is NEVER inferred** — not from `TaskState.RUNNING`, not from a task directory, not from a `runs/NNN` directory, not from the `pid=` line in the flock file. |
| **H-I3** | A run directory with no `reservation.json` is **LEGACY**. Not `ORPHANED`. **Not modified — not one byte, not `mtime`, not mode.** |

### 7.3 File-backed streams, and what is NOT claimed about them

**DECISION D-9.** The child's stdout and stderr are **opened files handed to the
child as its own fd 1 and fd 2** — not `PIPE`.

This solves pipe ownership **by removing pipes**: there is nothing to reattach,
the child never gets `EPIPE` when the dispatcher dies, the complete stream is
durable by construction, restart can read it, and progress-across-restart is free
(`st_size` growth). It is also what makes `stdout_bytes` mean *bytes the child
wrote* (§6.4).

**DECISION D-21: no redaction claim is made about them.** Revision 1 said
redaction moves "from write time to read time" and enumerated five egresses; the
reviewer showed that is **an unbounded obligation whose completeness cannot be
tested**, and revision 1 *added readers in the same document*. Two facts make the
direction right anyway, and the design states them because they strengthen the
case: the surrendered property is **already weak** (spool redaction is
line-oriented, so a `"key": "value"` pair split across a newline **survives into
`stderr.log` today**), and `state/tasks/*` is **gitignored**, so the
commit-a-secret risk is already absent; the residual is *copying*.

1. `stdout.raw`, `stderr.log` and `events.jsonl` are **PRIVATE, 0600,
   POTENTIALLY-SENSITIVE INTERNAL EVIDENCE.** **No document, docstring or payload
   says they are redacted.** `docs/SECURITY.md` §1.5 is **rewritten**, not
   amended in passing.
2. **ONE bounded rendering boundary.** A single accessor module (`streams.py`) is
   the *only* thing in `src/**` permitted to open those paths, and it returns
   **bounded, redacted `str`**. Raw bytes are reachable through exactly one
   explicitly-named function used in exactly one place (the event parser), which
   itself emits no text outward.
3. **Raw stream contents are NEVER returned directly** via MCP, logs or
   diagnostics — not in a tool payload, not in `last_error`, not in a progress
   message, not in the `recovery` block, not in a prompt.
4. **PROVEN BY** a reflection/AST test that **no other module in `src/**` opens
   those paths**. **COULD IT PASS WHILE FALSE?** Only through an indirection the
   AST cannot follow — but unlike "every egress redacts", the property *"nobody
   else opens the file"* **is decidable from the source**, which is the whole
   difference from revision 1.
5. **Mutations exist for it**: delete the redaction call in the accessor; open
   `stderr.log` from a second module. §11 had neither.

The alternatives are worse and the design says why: a redacting supervisor
reintroduces the process D-10 deleted **and** puts a redaction bug between the
child and the durable artefact; a post-exit redaction pass destroys the true
artefact, has its own crash window, and **cannot run at all in the orphan case**,
which is the case that made file-backing necessary.

### 7.4 No supervisor — conditional on reconciliation-time enforcement

**DECISION D-10 (revised).** §22 asks for the supervisor shape to be *evaluated*.
Evaluated and declined — but revision 1's evaluation was missing three things:

1. **D-9 removes today's de-facto reaper.** Today a dispatcher death usually
   kills a chatty child via `SIGPIPE`. Revision 1 listed *"the child never
   receives `EPIPE`"* as a **benefit**; it is simultaneously the deletion of the
   only thing that currently stops an orphan. **D-9 and D-10 must be weighed on
   one ledger**, and on that ledger revision 1 was a **net regression on
   termination**.
2. **The exit status becomes unrecoverable** (§7.5).
3. **"The repository is held closed by a claim" is the wrong reassurance.** The
   claim stops *the dispatcher* starting new work. It does nothing about what the
   orphan is doing: for hours past its deadline it keeps mutating the worktree,
   writing unbounded output, and spending the caller's budget — and since scope
   and primary-tree enforcement are *post-hoc measurements, not containment*, it
   does so with no boundary at all.

The supervisor is still the wrong answer — a second process lifecycle, a second
crash-recovery story, and a second thing that can hold the repository lock, all
to gain one action. **The right answer uses parts the design already has**:
`ownership.json` records `hard_deadline_at`, `pid`, `boot_id`,
`starttime_ticks`, `process_group_id`, `exe_realpath` — exactly enough to
identify and kill the correct process group with no PID-reuse risk — and
reconciliation already computes `ALIVE_SAME`. **§7.8 adds deadline enforcement at
reconciliation time**, which closes the entire residual **for any case where a
dispatcher ever restarts**, at the cost of about thirty lines and no new process.

It does **not** close the case where no dispatcher ever restarts. That residual
is real, genuinely unclosable without a supervisor, and §23 blesses an honest
degraded state for it. **That is the residual V1 accepts — strictly smaller than
revision 1 proposed.** §7.7.5 widens it marginally and says so.

### 7.5 The exit status is NOT recoverable after dispatcher death

Revision 1's reconciliation said *"`GONE` → `FINALIZING` if streams **and exit**
are recoverable"*. **No component in this design ever writes an exit marker, and
none can.** Only the parent may `wait()` a child; if the dispatcher died, the
orphan reparents to `init` and its exit code is gone permanently. §22 named
"writes exit status atomically" as a supervisor function; declining the
supervisor deletes the function without replacing it.

**The honest substitute is named:**

> A **trailing authoritative `type: "result"` event in `events.jsonl`** is
> evidence that the child ran to completion. **It is not an exit status.** A
> child killed mid-write is distinguishable from one still writing **only by the
> liveness probe**, never by the stream alone.

So: `GONE` **and** a trailing `result` event → reconcile to `FINALIZING` and
complete the evidence pipeline, with `exit_code = None` and
`exit_status_recoverable = false`, **never invented, never inferred from
`is_error`**. `GONE` **and no** `result` event → **`ORPHANED`**.

§21's *"determine whether it can safely reattach to output/evidence
finalization"* is therefore answered **"evidence finalization yes, output
ownership never, exit status never"** — explicitly, rather than by a branch that
looked reachable and was not.

### 7.6 Legacy reconciliation (directive H, fixes S-4)

#### 7.6.1 The measured problem

All five existing task directories on this host are **populated** and **none is
in `RUNNING`**:

| task | state | `run_count` | runs | `dispatcher-result.json` | `reservation.json` | `ownership.json` |
|---|---|---|---|---|---|---|
| `3dbd78d6` | `policy_violation` | 1 | `001` | **yes** | no | no |
| `49231f6e` | `policy_violation` | 1 | `001` | **yes** | no | no |
| `9244462a` | `awaiting_sol_review` | 1 | `001` | **yes** | no | no |
| `c5e385c9` | `failed` | 1 | `001` | **yes** | no | no |
| `df2a4a24` | `failed` | 1 | `001` | **yes** | no | no |

Revision 2 §7.6 said a populated run directory with no `reservation.json` →
`ORPHANED` + claim, and §7.7 said an `ORPHANED` claim refuses with
`RepositoryRecoveryRequired`, **not retryable**. So the first Gate-7 dispatcher
start would write **five `ORPHANED` claims for `/home/dev/full-voice-agent`**, and
**the moment the production freeze lifts, production is permanently closed by
five runs that completed weeks ago — three of which the brief designates as
evidence that must not be touched.** Revision 2's §7.12 said the opposite, and
§7.7's table could not reach the case because it is keyed on a reservation state
that does not exist. **The document contained both rules.**

**There is no live-worker ambiguity to resolve. There is only bookkeeping that
revision 2 would have invented.**

#### 7.6.2 The single rule

```python
def classify_run_directory(run_dir: Path) -> RunDirectoryClass:
    """Gate-7 reconciliation's ONLY entry classifier.
    LEGACY is TERMINAL: no claim, no probe, no signal, no write."""
    if not (run_dir / "reservation.json").exists():
        return RunDirectoryClass.LEGACY          # H-I3. Never ORPHANED.
```

and the loop is **claim-driven**:

```python
def reconcile_repository(self, digest: str) -> ReconciliationReport:
    claims_dir = self.config.locks_path / f"{digest}.claims"
    if not claims_dir.is_dir():
        return ReconciliationReport.empty()      # nothing was ever claimed here
    with reconciliation_lock(digest):            # §7.7.4
        for claim in sorted(claims_dir.iterdir()):
            record  = read_claim(claim)          # unparseable -> ACTIVE (C14)
            verdict = classify_owner(record.owner)         # §7.7.3 — FIRST
            ...
```

**`state/tasks/**` is never walked at startup**, asserted by
`test_reconciliation_never_walks_the_task_tree` (AST: no function reachable from
the entry point calls `iterdir`/`glob`/`walk` on `config.tasks_path`).

#### 7.6.3 Why claim-driven reconciliation is complete, not merely convenient

> **Theorem (claim coverage).** For every run state whose reconciliation action
> is non-empty — `STARTING`, `RUNNING`, `FINALIZING`, `LAND_INCOMPLETE`,
> `ORPHANED` — §7.7.6 says the claim is **held**. For every state whose claim is
> released or absent — `RESERVED`, `COMPLETE`, `ABORTED_PRELAUNCH`,
> `FINALIZATION_FAILED` — the reconciliation action is **empty**. **Therefore the
> claim set is a superset of the recoverable set.**

**PROVEN BY** `test_claim_coverage_matches_the_authoritative_table` — table-driven
over every `RunState`, asserting the §7.7.6 claim value and that
`reconcile_action(state)` is `NONE` for exactly the released set. **It fails the
moment someone adds a run state with a recovery action and no claim, which is the
only way the theorem can break.**

Two consequences: a crash after `mkdir runs/NNN` and before `reservation.json`
(**C1**) leaves a bare directory with **no claim**, and reconciliation never
visits it — **correct**, because the property that matters is index non-reuse and
that comes from `mkdir(EEXIST)`. And a `RESERVED` reservation that never launched
holds no claim, so a **task-scoped, read-only** sweep may additionally transition
it to `ABORTED_PRELAUNCH` when a caller is already touching that task — safe by
the theorem, since a claimless reservation cannot be executing.

#### 7.6.4 `get_task` for a legacy task

```json
{"state": "policy_violation",
 "ownership": {"tracked": false,
   "reason": "pre-Gate-7 run: no reservation.json",
   "runs": ["001"],
   "note": "This run predates Gate 7 durable ownership. The dispatcher makes no
            liveness claim about it and holds no repository claim for it."}}
```

**No `recovery` block**, because a `recovery` block asserts unresolved liveness
and the dispatcher has no basis to assert that.

**Migration, if ever wanted**, is
`scripts/gate7-migrate-legacy-runs.py --task <id> --run <NNN> --confirm`: not
invoked by the server, not by any tool, **not part of Gate 7 PASS**, and it would
write a terminal `reservation.json` and **never a claim**.

**A pre-Gate-7 task genuinely stuck in `RUNNING`** — none exists today — would be
reported `LEGACY-RUNNING` forever, with no claim and no recovery block. That is
**exactly today's behaviour**, Gate 7 promised not to modify legacy tasks, and
inventing a claim for it is the S-4 bug wearing a different hat. *(Escalated as
Z2-Q6, §18.2.)*

### 7.7 Concurrent Codex sessions (directive I, fixes S-5)

#### 7.7.1 The measured problem

`server.main()` runs `run_stdio_async()`; **an stdio MCP server is spawned per
client process**, and **there is no single-instance guard anywhere in `src/**`**
— the only `fcntl` in the tree is `locks.py`, which is per-repository.
`CLAUDE.md` §3 records that this VPS has live Codex and Claude sessions, so
**concurrent dispatchers are the normal condition.** Revision 2 then put
reconciliation in `__init__` and made §7.6A **terminate** any run whose child
probe is `ALIVE_SAME` past its deadline — **without ever classifying who owns
it.**

#### 7.7.2 Dispatcher identity and the liveness lock

```python
class DispatcherIdentity(StrictModel):
    instance_id: str          # uuid4, minted once per process
    boot_id: str; pid: int; starttime_ticks: int; clock_ticks_per_second: int
    exe_realpath: str; argv0: str
    liveness_path: str        # state/dispatchers/<instance_id>.alive
    started_at: datetime
```

```python
fd = os.open(liveness_path, os.O_CREAT | os.O_RDWR, 0o600)  # non-inheritable (PEP 446)
assert os.get_inheritable(fd) is False                       # I-F1 guard, measured
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)               # held for process lifetime
# retained on the Dispatcher, NEVER closed until exit, NEVER passed to a child.
```

**Why a second signal at all.** The `/proc` triple answers *"does a process with
this identity exist?"*. It does not answer *"is that process still the dispatcher
that owned this run?"* with kernel authority. The flock answers a different
question **with kernel authority** — **the kernel releases an `flock` when the
holding process dies, including under `SIGKILL`** (measured) — and it is exactly
the fact §7.7.6 correctly observes about the repository lock, applied to the
*owner* instead of the repository.

**The hazard, measured (I-F1).** If the liveness fd is ever marked inheritable
and handed to a child, **the lock survives the dispatcher's death** and a second
dispatcher reads a dead owner as alive. **IF MIS-WIRED, this fails SAFE:** the
false reading is `OWNER_ALIVE_SAME`, whose action set is *do nothing and keep the
repository closed*. The cost is an over-conservative refusal a human resolves;
the cost of the opposite direction would be killing a live worker. The guard is
nonetheless explicit — the assertion above, `close_fds=True`/no `pass_fds` on
every spawn, and `test_liveness_fd_is_not_inherited_by_the_worker`.

#### 7.7.3 Owner classification — evaluated BEFORE anything else

| # | `instance_id` | `boot_id` | `/proc/<pid>` | starttime | exe | liveness flock | **Verdict** |
|---|---|---|---|---|---|---|---|
| 1 | == mine | — | — | — | — | (held by me) | **OWNER_SELF** |
| 2 | ≠ mine | **differs** | — | — | — | — | **OWNER_GONE** (rebooted; the lock is definitionally released) |
| 3 | ≠ mine | same | absent | — | — | acquirable | **OWNER_GONE** |
| 4 | ≠ mine | same | present | matches | matches | **EAGAIN** | **OWNER_ALIVE_SAME** |
| 5 | ≠ mine | same | present | **differs** | — | acquirable | **OWNER_GONE** (pid reuse) |
| 6 | ≠ mine | same | absent | — | — | **EAGAIN** | **OWNER_AMBIGUOUS** — signals disagree (inherited fd) |
| 7 | ≠ mine | same | present | matches | matches | acquirable | **OWNER_AMBIGUOUS** |
| 8 | ≠ mine | same | present | matches | **differs** | any | **OWNER_AMBIGUOUS** |
| 9 | ≠ mine | same | present | **differs** | — | **EAGAIN** | **OWNER_AMBIGUOUS** |
| 10 | ≠ mine | same | any | any | any | liveness file **missing** | **OWNER_AMBIGUOUS** — absence is not proof of death |
| 11 | any | unreadable / unparseable / permission denied / any exception | | | | | **OWNER_AMBIGUOUS** |
| 12 | claim partial or unparseable | | | | | | **OWNER_AMBIGUOUS**, claim treated **ACTIVE** (C14) |

Row 2 is evaluated first and short-circuits. Rows 6–11 are the fail-closed set.
**Nothing here resolves a disagreement by preferring the more convenient signal.**

| Verdict | Signal? | Rewrite claim? | Mark `ORPHANED`? | Replay landing? | Acquisition by *this* dispatcher |
|---|---|---|---|---|---|
| `OWNER_SELF` | no | no | no | no | proceeds (registry + flock govern) |
| **`OWNER_ALIVE_SAME`** | **never** | **never** | **never** | **never** | **`RepositoryBusy` (retryable)** |
| **`OWNER_GONE`** | only per §7.8 | yes, atomically | per §7.8 | yes, single-flight | proceeds unless recovery landed `ORPHANED` |
| **`OWNER_AMBIGUOUS`** | **never** | **never** | **no** (leave the claim exactly as found) | **never** | `RepositoryRecoveryRequired` (**not** retryable) |

Note the deliberate asymmetry: `OWNER_ALIVE_SAME` refuses **retryably**, because
nothing is wrong — another dispatcher's worker is simply running. **Revision 2
would have reported this as `ORPHANED` and therefore as
`RepositoryRecoveryRequired`, telling a human to intervene in a healthy run.**

**Two probes, two questions, never conflated:** `classify_owner` asks *whose run
is this?*; `probe` (the child identity truth table, unchanged from revision 2)
asks *is the child still there?* **Revision 2 asked only the second.**

#### 7.7.4 Preventing two servers from racing recovery

**(a) A cross-process reconciliation lock, per repository** —
`state/locks/<digest>.recovery`, `LOCK_EX|LOCK_NB`; `EAGAIN` raises
`RepositoryRecoveryInProgress` (**retryable**). It serialises the *whole*
classify-and-act sequence, which is what stops two dispatchers interleaving. It
is a separate file from the repository lock deliberately: reconciliation must run
*before* the repository lock without either being reentrant.

**(b) An atomic claim transition, per claim** — `os.rename(claim,
claim.recovering.<instance>.json)`. Measured: **two racing processes produce
exactly one winner and one `ENOENT`.** The lock makes interleaving impossible;
the rename makes the winner **durable**, so a crash during recovery leaves an
inspectable marker rather than a lost claim. A `.recovering.*` file is itself a
claim for classification purposes, so a dispatcher that dies mid-recovery is
handled by the ordinary rules rather than a special case.

**(c) The physical guarantee about signalling.**

```python
@final
class TerminationAuthority:
    """The ONLY object that may signal a worker. Constructible only by
    DeadOwnerReclaim.acquire(), which requires BOTH the repository
    reconciliation lock AND an flock on the OWNER's liveness file. The kernel
    will not grant the second while the owner process lives."""
    def signal_recorded_group(self, sig: signal.Signals) -> SignalOutcome:
        """Signals self._identity.process_group_id. There is NO pgid parameter,
        NO pid parameter and NO target parameter — the same reason
        _record_failure has no phase parameter: a wrong literal must be
        impossible to write."""
```

`os.kill` / `os.killpg` appear in exactly **two** places — `ownership.py` and the
in-process timeout path in `runner.py` — asserted by
`test_signals_are_emitted_from_exactly_two_places` (AST).

> **This is the answer to "physically unable".** A second Codex session's
> dispatcher cannot reach `killpg` for a worker owned by a live first dispatcher,
> because constructing the only object that can signal requires an `flock` the
> kernel refuses while the first dispatcher lives. It is not a policy check a
> future edit can forget to call; **the object cannot be built.**
>
> **What remains conventional**, stated rather than overclaimed: nothing stops a
> *different program*, or a hand-written `os.kill`, from signalling the same pid.
> Same-uid processes can always signal each other; **this design is not an OS
> sandbox.** The claim is exactly: **the dispatcher's own code path cannot do
> it**, and the AST test pins that no second code path is introduced.

#### 7.7.5 Where reconciliation runs — NOT in `Dispatcher.__init__`

Measured reasons: `__init__` **cannot report an error except by exception**, and
`main()` converts a `DispatcherError` into a stderr payload and `SystemExit(2)`
**before the MCP transport exists** — so a recovery problem on one repository
would kill an entire Codex session's dispatcher. It runs on **every** MCP server
spawn, i.e. once per Codex session, and would perform host-wide I/O and possibly
signal a process group before the transport is up. And **the repository is not
known at construction time**; reconciling every repository on the host to serve
one is exactly the over-reach that produced S-4 and S-5.

**Instead:** reconciliation is a **per-repository step invoked from
`RepositoryLock.acquire()`'s pre-flock phase**, under the reconciliation lock,
**inside a tool call, in PREPARE**, where a refusal is a typed `DispatcherError`
the caller sees. `Dispatcher.__init__` gains only the identity mint and the
liveness lock, asserted by
`test_dispatcher_init_performs_no_reconciliation_and_no_signals`.

**Honest cost, stated:** a repository that no dispatcher ever touches again is
never reconciled. Its claim keeps it closed — the fail-closed direction — and
`get_task` still reports the run. **The residual "no dispatcher ever restarts"
therefore widens marginally to "no dispatcher ever touches this repository
again". That is a real widening and it is stated rather than absorbed.**
*(Escalated as Z2-Q4, §18.2.)*

#### 7.7.6 Claim retention — the authoritative table

Revision 1 contradicted itself: prose said a claim is *"not removed for
`ORPHANED`"* while the table three lines above said a `GONE` non-terminal run
*"claim removed, acquisition proceeds"*. **This table is authoritative and no
prose overrides it:**

| Reservation state | Claim | Rationale |
|---|---|---|
| `RESERVED` | **none** | nothing was started |
| `STARTING` | **held** | a process may exist that we cannot name |
| `RUNNING` | **held** | that is what a claim is for |
| `FINALIZING` | **held** | the child is gone but evidence is in flight |
| `LAND_INCOMPLETE` | **held** | released only at `COMPLETE` |
| `COMPLETE` | **released** | terminal and successful |
| `ABORTED_PRELAUNCH` | **released** | no process ever existed |
| `FINALIZATION_FAILED` | **released** | the child is provably gone and the run is terminal and preserved. **A failed finalisation must not close a production repository forever.** |
| `ORPHANED` | **HELD** | unresolved liveness keeps the repository closed until a human or Sol resolves it |
| *(no `reservation.json`)* | **none — LEGACY** | §7.6 |

**And the bare-directory case is defined, not undefined.** Revision 1 classified
crash point C1 as `ORPHANED`, while its reconciliation loop iterated *"each
`runs/NNN` with `reservation.state ∉ terminal`"* — **which cannot evaluate a
state that was never written.** If it *had* landed `ORPHANED` with a retained
claim, **a crash in a microsecond window before anything was launched would have
closed the repository permanently.** An empty run directory is
`ABORTED_PRELAUNCH` with **no claim**: the index stays burnt, the repository
stays open.

`RepositoryLock.acquire()`'s pre-flock step re-runs `classify_owner` for each
claim; a **partial or unparseable claim file is treated as ACTIVE** and refuses
with `RepositoryRecoveryRequired`.

**Interaction with Gate 6, preserved.** The in-process `RunRegistry` prevents a
duplicate *within* one process; the flock prevents concurrent mutation *between*
live processes; the durable claim adds the third case — **a dead process's live
worker** — which neither of the first two can see.

**SIGTERM handling.** `main()` gains a handler that calls
`Dispatcher.drain(timeout)` and then exits, so a graceful shutdown lets in-flight
runs land their evidence instead of becoming orphans. It **cancels nothing**.

### 7.8 Reconciliation-time deadline enforcement (directive J)

**Every row below is inside `OWNER_GONE`.** If the owner classifies
`OWNER_SELF`, `OWNER_ALIVE_SAME` or `OWNER_AMBIGUOUS`, **none of this applies and
no signal is sent.**

| Owner | Child probe | Deadline | Action |
|---|---|---|---|
| **gone** | `ALIVE_SAME` | **before** `hard_deadline_at` | hold the repository closed, no duplicate, **NO SIGNAL**. Reservation → `ORPHANED`, claim **held**. |
| **gone** | `ALIVE_SAME` | **past** `hard_deadline_at` | **`SIGTERM` → grace → `SIGKILL`, to the EXACT recorded process group.** Never a bare pid. Never an unrecorded pgid. Re-probe; if still `ALIVE_SAME` or `AMBIGUOUS`, record the failure and land `ORPHANED` with the claim retained. |
| **gone** | **AMBIGUOUS** | any | **`ORPHANED` / `RECOVERY_REQUIRED`, NO SIGNAL.** Identity that cannot be proven is not a target. |

- **`hard_deadline_at` is read from `ownership.json`**, persisted at launch,
  **never re-derived at recovery time** from a config value a later edit could
  have changed.
- **The deadline is the caller's own declared contract**
  (`envelope.execution.timeout_seconds`). Enforcing it after a restart is the
  same class of act as `asyncio.wait_for` enforcing it in-process. **The
  dispatcher is not deciding the run should stop; it is applying a decision
  already recorded.**
- **The termination is journalled** in `reservation.json`'s history with the
  exact identity it was performed against — pid, pgid, boot_id,
  starttime_ticks, exe_realpath — **and the classifying dispatcher's
  `instance_id` and the owner verdict**, so an operator can verify both *which*
  process was signalled and *by what authority*.
- **Never invent an exit status** (§7.5).
- **An orphan is not a timeout.** `ClaudeTimedOut` means *the dispatcher killed
  it under `asyncio.wait_for`*; a reconciliation-time termination is recorded as
  its own action.

**PROOF DISCIPLINE.** `test_orphan_within_deadline_is_not_terminated` **could
pass while the property is false in one way**: if the test's owner is alive, the
owner gate stops the signal and the deadline rule is never exercised. The test
therefore **kills the owner first** (`SIGKILL` on a dispatcher the test itself
created) so `OWNER_GONE` holds and the deadline comparison is the only thing
between the child and a signal. Its paired positive control,
`test_orphan_past_deadline_is_terminated`, uses the identical setup with the
deadline moved — **the two differ in exactly one variable.**

### 7.8A State transitions

**Subsystem D introduces no new `TaskState` and no new `RunState`.** What it
introduces is the **gate** in front of the existing ones:

```
claim ──► classify_owner ──┬─ OWNER_SELF       ──► (no action)
                           ├─ OWNER_ALIVE_SAME ──► (no action) ─► RepositoryBusy
                           ├─ OWNER_AMBIGUOUS  ──► (no action) ─► RepositoryRecoveryRequired
                           └─ OWNER_GONE ──► reconciliation_lock(digest)
                                          ──► atomic rename to .recovering.<me>
                                          ──► probe(ownership.process)   ← the CHILD probe
                                              ├─ ALIVE_SAME, within deadline ─► ORPHANED, claim held, NO SIGNAL
                                              ├─ ALIVE_SAME, past deadline   ─► §7.8 terminate, then re-probe
                                              ├─ GONE + trailing result      ─► FINALIZING
                                              ├─ GONE, no result             ─► ORPHANED, claim held
                                              └─ AMBIGUOUS                   ─► ORPHANED, claim held, NO SIGNAL
                                          ──► LAND_INCOMPLETE ─► replay the landing
                                          ──► rename back to a settled claim, or release it
```

**An orphaned run causes no task transition** (D-I8). The task is left in
`RUNNING` and `get_task` reports `state: running` alongside an explicit
`recovery` block — honest and unambiguous, rather than laundered into a terminal
state. *(OQ-D3 decided: leave it `RUNNING`. `BLOCKED` would be the dispatcher
saying what happened, which is Sol's call. If Sol wants orphans on an actionable
list, that is a listing concern, not a state transition.)*

### 7.9 Persistent data

```
state/dispatchers/<instance-id>.alive        NEW  0600, flock held for process life
state/locks/<digest>.lock                    existing flock
state/locks/<digest>.recovery                NEW  cross-process reconciliation lock
state/locks/<digest>.claims/
    <task-id>-<run-index>.json               NEW  RunClaim (owner: DispatcherIdentity)
    <task-id>-<run-index>.recovering.<instance-id>.json   NEW  transient
state/tasks/<id>/runs/NNN/
    expectation.json                         NEW  pre-spawn expectation; carries NO pid
    ownership.json                           NEW  written ONLY from a WorkerHandle
```

`RunOwnership` replaces revision 2's three flat dispatcher fields with the same
embedded `owner: DispatcherIdentity`, **so the claim and the ownership record
cannot drift.**

**The pre-spawn expectation record (OQ-D4 decided).** Written immediately before
`create_subprocess_exec`, carrying the reservation identity,
`expected_binary_realpath`, `expected_argv0`, `dispatcher_owner_instance_id`,
`boot_id` and `hard_deadline_at`. It is **explicitly typed as an EXPECTATION, not
an ownership claim** — `kind: "expectation"`, **no `pid`** — so D-I2 stays
intact. Its only use is to make the unnameable `STARTING` crash *resolvable*: a
reconciling dispatcher can scan for a process matching the expected binary and
report a **candidate**. **A candidate is never auto-adopted as ownership and
never auto-killed** — it is information in the `recovery` block.

**`RunOwnershipUnavailable` termination contract.** By that point the process
**exists**, so terminating it is a real kill and needs a contract: (1) the
expectation record already names the expected binary and `proc.pid` is in hand;
(2) **write the repository claim first, before signalling** — if the kill fails
and the dispatcher then dies, the claim is what stops a duplicate; (3) `SIGTERM`
the child's process group, wait `grace_seconds`, `SIGKILL`; (4) confirmed gone →
`ABORTED_PRELAUNCH`, claim released; (5) **kill failed or liveness unconfirmed →
`ORPHANED`, claim retained** — calling it `ABORTED_PRELAUNCH` would assert
something unproven.

### 7.10 Error taxonomy

| Code | Class | Phase | Retryable | Meaning |
|---|---|---|---|---|
| `RepositoryBusy` | existing | PREPARE | **yes** | flock held, **or** a claim's owner is `OWNER_ALIVE_SAME`. Details name the owning `instance_id` and `pid` — **not the worker's**. |
| `RepositoryRecoveryRequired` | `DispatcherError` **NEW** | PREPARE | **no** | `ORPHANED`, an `AMBIGUOUS` child identity, an `OWNER_AMBIGUOUS` claim, or an unparseable claim. Details name task, run index, run dir, **both verdicts**, and operator remediation. |
| `RepositoryRecoveryInProgress` | `DispatcherError` **NEW** | PREPARE | **yes** | another dispatcher holds the reconciliation lock |
| `DispatcherIdentityUnavailable` | `InternalDispatcherError` **NEW** | PREPARE | no | `/proc/self` unreadable, or the liveness lock could not be taken. **The server still starts and still serves `get_task`; `dispatch`/`resume`/`review` refuse.** A dispatcher that cannot name itself must not launch a worker it could never prove it owned. |
| `RunOwnershipUnavailable` | `InternalDispatcherError` | LAUNCH | no | §7.9 contract |

*(Z2-Q5 escalated: reuse `RepositoryBusy` for "another dispatcher owns this", or
add a distinct retryable code for observability? This design reuses it — the
condition genuinely is "busy", and a not-retryable code here would recreate S-5's
"a healthy run needs human intervention" outcome.)*

### 7.11 Crash points

Subsystem D's rows are **C1–C4 and C11–C15** of the canonical matrix (§15). This
section states **no count of its own**.

### 7.12 Tests

Unit: `classify_owner` truth table (all twelve rows, synthetic `/proc` fixture +
a real lock file); the child `probe` truth table;
`test_owner_classification_runs_before_any_action` (AST: no `probe`,
`TerminationAuthority`, claim write or `transition` appears before the
`classify_owner` call); claim lifecycle against §7.7.6, one case per reservation
state; `streams.py` accessor tests including the AST no-other-opener test.

**Real-process integration.** **The fake worker must be UNCOOPERATIVE** — the
existing fake binary exits promptly, and Subsystem D's whole point is a child
that does not. These use a child that **ignores `SIGTERM` and journals every
signal it receives**.

- **`test_startup_leaves_legacy_tasks_byte_identical`** — the S-4 headline. A
  fixture tree copied from the measured shape above, including one task in each
  of `policy_violation`, `awaiting_sol_review` and `failed`. Take a recursive
  manifest of `(relpath, sha256, st_mode, st_mtime_ns, st_size)` **covering the
  whole state tree, including `state/locks/`**. Start a real dispatcher. Assert
  the manifest is **identical** and `state/locks/*.claims/` does not exist.
- **`test_production_repository_is_acquirable_after_first_gate7_start`** — the
  outcome that actually matters: reconcile a pre-Gate-7 tree with all five tasks
  naming one repository, then `RepositoryLock.acquire()` **succeeds**.
- `test_legacy_running_task_creates_no_claim` — no claim, **no probe, no signal**
  (an `os.kill` seam counts calls and must be zero), no write.
- `test_pre_gate7_run_directory_is_legacy_not_orphaned`;
  `test_legacy_run_index_is_never_reused`;
  `test_reconciliation_never_walks_the_task_tree` (AST);
  `test_claim_coverage_matches_the_authoritative_table`;
  `test_migration_requires_explicit_confirmation`.
- **`test_second_dispatcher_never_signals_first_dispatchers_worker`** — the S-5
  headline. Dispatcher **A** (a real process) launches a real uncooperative child
  with `hard_deadline_at` **in the past** and stays alive. Dispatcher **B** (a
  second real process, as a second Codex session would spawn) starts and attempts
  the same repository. Assertions: (1) the child is **still alive**; (2) the
  child's **own signal journal is empty** — zero `SIGTERM`, zero `SIGKILL`;
  (3) the claims directory is **byte-identical** before and after; (4) B refuses
  with **`RepositoryBusy` (retryable)**, naming A's `instance_id`; (5) **A's own
  in-process deadline path still terminates the child afterwards**, proving the
  guard did not disable enforcement — only relocated its authority.
- **`test_dead_owner_worker_past_deadline_is_terminated_by_the_second_dispatcher`**
  — the **positive control** for the above: identical setup, but A is `SIGKILL`ed
  first. **Without this, test 1 could pass by never recovering anything.**
- **`test_inherited_liveness_fd_is_ambiguous_not_gone`** — built directly from
  the I-F1 measurement: A leaks the fd to its child and is killed; B finds
  `/proc/<A.pid>` absent but the lock held (row 6) → **AMBIGUOUS** → no signal.
- `test_two_dispatchers_recover_one_run_once` — A killed; B and C start
  barrier-synchronised. Assert **exactly one `.recovering.*` marker existed**,
  one set of transitions, one reservation-history entry.
- `test_two_dispatchers_replaying_one_landing_produce_one_landing` — S-5 race 3.
- **`test_two_dispatchers_serve_different_repositories_concurrently`** — the
  **anti-singleton control** for I-I1. **Any global instance lock fails this.**
- `test_dispatcher_init_performs_no_reconciliation_and_no_signals`.
- `test_orphan_past_deadline_is_terminated` / `test_orphan_within_deadline_is_not_terminated`
  / `test_ambiguous_identity_is_never_signalled` /
  `test_deadline_read_from_ownership_not_config` /
  `test_exit_status_not_recoverable_is_none` / `test_orphan_is_not_a_timeout` /
  `test_signal_targets_the_recorded_process_group`.
- `test_streams_recovered_after_dispatcher_death` — streams recoverable from the
  file-backed spool; **`exit_code` asserted to be `None`**, proving the design
  does not invent one.
- `test_pid_reuse_is_not_attachment`; `test_ambiguous_identity_fails_closed`;
  `SIGTERM` to the dispatcher → `drain()` lets the run land, no orphan.

### 7.13 Mutation cases

| Mutant | Named targeted killer |
|---|---|
| **H-M1** infer a claim from `TaskState.RUNNING` | `test_legacy_running_task_creates_no_claim` |
| **H-M2** classify a run dir without `reservation.json` as `ORPHANED` | `test_pre_gate7_run_directory_is_legacy_not_orphaned` + `test_production_repository_is_acquirable_after_first_gate7_start` |
| **H-M3** walk `state/tasks/**` at startup | `test_reconciliation_never_walks_the_task_tree` + `test_startup_leaves_legacy_tasks_byte_identical` |
| **H-M4** write anything into a legacy task | `test_startup_leaves_legacy_tasks_byte_identical` |
| **H-M5** run migration automatically at startup | `test_migration_requires_explicit_confirmation` |
| **H-M6** treat a legacy run index as reusable | `test_legacy_run_index_is_never_reused` |
| **H-M7** add a run state with a recovery action and no claim | `test_claim_coverage_matches_the_authoritative_table` |
| **I-M1** skip owner classification entirely | `test_second_dispatcher_never_signals_first_dispatchers_worker` |
| **I-M2** treat `OWNER_AMBIGUOUS` as `OWNER_GONE` | truth table + `test_inherited_liveness_fd_is_ambiguous_not_gone` |
| **I-M3** classify from `/proc` alone | `test_inherited_liveness_fd_is_ambiguous_not_gone` (**the only signal that separates rows 3 and 6**) |
| **I-M4** classify from the liveness lock alone | truth-table rows 5 and 9 (pid reuse) |
| **I-M5** mark a live owner's run `ORPHANED` | S-5 headline, assertion 3 |
| **I-M6** refuse `OWNER_ALIVE_SAME` as not-retryable | S-5 headline, assertion 4 |
| **I-M7** drop the reconciliation lock | `test_two_dispatchers_recover_one_run_once` |
| **I-M8** replace the atomic rename with read-then-write | same |
| **I-M9** **introduce a production-wide singleton** | `test_two_dispatchers_serve_different_repositories_concurrently` |
| **I-M10** run reconciliation in `__init__` again | `test_dispatcher_init_performs_no_reconciliation_and_no_signals` |
| **I-M11** signal from a second code path | `test_signals_are_emitted_from_exactly_two_places` (AST) |
| **I-M12** make the liveness fd inheritable | `test_liveness_fd_is_not_inherited_by_the_worker` |
| **I-M13** classify the owner *after* probing the child | `test_owner_classification_runs_before_any_action` (AST) |
| **J-M1** apply the deadline rule without the owner gate | S-5 headline |
| **J-M2** give `signal_recorded_group` a pgid parameter | `test_signal_function_takes_no_target_parameter` (reflection) |
| **J-M3** construct `TerminationAuthority` outside `DeadOwnerReclaim` | `test_termination_authority_constructed_only_by_reclaim` (AST) |
| **J-M4** journal the termination without the owner verdict | `test_termination_journal_records_authority_and_identity` |
| remove `ownership.json`; treat pid existence as identity; kill an `AMBIGUOUS` run; kill within the deadline; derive the deadline at recovery; launch a duplicate after restart; remove the claim on `ORPHANED`; **retain the claim on `FINALIZATION_FAILED`**; **retain a claim for a bare run directory**; write `ownership.json` before the process exists; **write a pid into `expectation.json`**; **auto-adopt a candidate**; mark an orphan `TIMED_OUT`; invent an exit code; restore `stdout=PIPE`; open a raw stream outside `streams.py`; delete the accessor's redaction call | §7.12's correspondingly-named tests |

### 7.14 Backward compatibility

- **Every existing task remains readable and unchanged.** `get_task` gains one
  additive `ownership` block.
- `state/locks/<digest>.claims/` and `state/dispatchers/` are created lazily;
  **their absence is a valid, complete cold-start state.**
- **Revision 2's §7.12 sentence** — *"Tasks with existing `runs/NNN` and no
  `ownership.json` reconcile as `COMPLETE` … or `ORPHANED`"* — is **DELETED, not
  reconciled.** Both of its branches assert something about a run Gate 7 never
  owned. The replacement is H-I3/H-I4.
- A claim written by an older Gate-7 build without an `owner` block classifies
  `OWNER_AMBIGUOUS` and fails closed. **No claims exist on this host today**, so
  the case is theoretical and failing closed on it is right.
- `RepositoryLock`'s public API is unchanged; `acquire()` gains a pre-flock
  reconciliation step and two new refusal codes.
- `stdout.raw` / `stderr.log` keep their paths and their meaning to a reader;
  only the writer changes — **and no redaction claim is made about them.**

---

## 8. Failure ordering (§28)

```
 0. PREPARE refusals            -> NO lifecycle mutation. state.json byte-identical.
                                   [WAVE 0 — D-24. Wave 0's own §5.8 and §5.5
                                    refusals land here, so the phase mechanism
                                    ships with them, not a wave later.]
                                   Logged to refusals.jsonl. NEVER FAILED.
                                   (admin unreconciled, lifecycle infeasibility,
                                    hash drift, budget, ContextTooLarge-in-preflight,
                                    RepositoryBusy, RepositoryRecoveryRequired,
                                    RepositoryRecoveryInProgress,
                                    ResumeNotPermittedFromState,
                                    EvidenceIncompleteForReview,
                                    EvidenceExceedsReviewBudget,
                                    SnapshotBudgetExceeded (PREPARE),
                                    CheckoutTransformationBudgetExceeded)

 1. LAUNCH failures             -> reservation ABORTED_PRELAUNCH.   [WAVE A]
                                   TASK LIFECYCLE UNCHANGED. NEVER RUNNING.
                                   NO FAKE WORKER RUN.
                                   (spawn OSError, kernel E2BIG,
                                    ClaudeBinaryNotFound, WorkerSpawnFailed,
                                    spool-open failure)

 2. worktree base mismatch      -> FAILED, BEFORE any evidence is collected.
                                   No inventory, no snapshot, nothing measured.

 3. INVENTORY failure           -> FAILED. The authoritative path list could not
                                   be produced, so no policy question is
                                   answerable.
                                   (GitEvidenceCollectionFailed,
                                    BaseTreeSnapshotFailed,
                                    FilesystemSnapshotFailed,
                                    SnapshotBudgetExceeded (FINALIZE),
                                    InventoryFilesystemUnsupported)
                                   `PathIdentityUnrepresentable` is NOT here.

 --- from here the inventory EXISTS, so policy is ALWAYS decided ---

 4. evidence-authority tamper   -> POLICY_VIOLATION.
                                   Administrative divergence (§5.8): a .git/**
                                   or $GIT_COMMON_DIR/** write, a moved config,
                                   attributes, exclude or hook, a new exec key,
                                   or a FINALIZE capture failure (`unknown` is
                                   treated as TAMPER, never as clean).

 5. scope violation /           -> POLICY_VIOLATION. Outranks worker success, and
    primary-tree interference      outranks EVERY content-level refusal.
                                   A symlink, FIFO, oversized, unreadable or
                                   non-UTF-8-named path that is OUT OF SCOPE
                                   lands HERE on its authoritative path.
                                   It is NOT laundered into FAILED.

 5a. path identity              -> FAILED, PathIdentityUnrepresentable,
     unrepresentable               ONLY IF rows 4 AND 5 did not fire.

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
Fable refuse where §5.11.5 says so, and they are reported — **but they never
decide the task's state.**

Orthogonal to the ladder: **run finalization failure** → run preserved,
`FINALIZATION_FAILED`, index never reused, **claim released**; **landing
interrupted** → `LAND_INCOMPLETE`, **claim retained**, transitions replayed
idempotently; **orphaned run** → **no task transition**, `get_task` carries a
`recovery` block, the repository stays claimed.

**Three rows are new relative to revision 2, and two are corrections of it.**
Row 1 changes (a spawn failure no longer lands `FAILED`); row 5a is new and is
the correction of Z1-N2; row 4's source becomes §5.8's administrative
reconciliation rather than an inventory check on `.gitignore`/`.gitattributes`
(§5.6.6).

**PROVEN BY** — one integration test per row, **and**
`test_deliberately_conflicting_run_lands_policy_violation`: a run that is
simultaneously a **timeout**, an **out-of-scope change**, a **429 envelope in
partial stdout**, an **untracked symlink**, a **FIFO**, an **oversized file** and
a **non-UTF-8 filename**, asserting `POLICY_VIOLATION`. **This is revision 2's
best test, kept verbatim and extended with the three rows that would have
laundered it.**

---

## 9. Size economics (§26)

### 9.1 Where the duplication is, conceptually

Measured projected sizes at baseline (frontmatter stripped, delimiters and
co-projected support files included once):

| Document | Bytes | The idea it carries that no other does |
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

| Idea | incr | plan | debug | TDD | verify | review | recv |
|---|---|---|---|---|---|---|---|
| work in small verified increments | ✓ | ✓ | | ✓ | | | |
| run the real command, read the real output | ✓ | | ✓ | ✓ | ✓ | | ✓ |
| evidence before claims | ✓ | | ✓ | ✓ | ✓ | ✓ | ✓ |
| do not declare done without proof | ✓ | ✓ | | ✓ | ✓ | | ✓ |
| reproduce before you fix | | | ✓ | ✓ | | | ✓ |
| state what you did not verify | | | ✓ | | ✓ | ✓ | ✓ |
| address the finding, not the reviewer | | | | | | ✓ | ✓ |

**Five ideas appear in five or more documents.** That is the duplication, and it
is *conceptual, not textual* — which is exactly why a runtime de-duplicator
cannot find it and a reviewer can.

### 9.2 Targets

**Targets are review outcomes, not runtime caps.** The engine cap stays at
`[skills].max_projected_bytes = 72_000` and still fails closed. **Nothing
truncates at runtime, ever.**

| Profile | Current typical → worst | Target |
|---|---|---|
| `DISPATCH_IMPLEMENTATION` | 44,757 → 89,376 | **≤ 24,000 B**, typical ~16,000 |
| `CORRECTION_RESUME` | 50,842 → 95,461 | **≤ 12,000 B** — no planning material |
| `VALIDATION_ONLY_RESUME` | n/a | **≤ 6,000 B** (proven, never selected) |
| `FABLE_REVIEW` | 0 B skills | **0 B** — unchanged |

```
worst dispatch today:   89,376 + 41,955 + 4,718 = 136,049  -> INFEASIBLE
worst resume today:     95,461 + 41,955 + 4,718 = 142,134  -> INFEASIBLE
worst dispatch target:  24,000 + 41,955 + 4,718 =  70,673  -> 57% of ceiling
worst resume target:    12,000 + 41,955 + 4,718 =  58,673  -> 48% of ceiling
```

The 42%-infeasible profile space becomes **0% infeasible with ~52,000 B of
headroom**, and the G7-1 trap disappears **not because the check was relaxed but
because the payload stopped being absurd.**

**What the targets must not do.** They must not be met by cutting approved
methodology. The acceptance criterion for each artifact is a **review finding**
recorded in the manifest alongside the enumerated concepts. **If a target cannot
be met without losing methodology, the target moves, not the methodology.** An
over-target-but-feasible profile ships; an infeasible one refuses.

### 9.2A The matrix is parameterised by the CAP, not by a fixture (R-9)

Composed bytes are a function of the target repository's project guidance
(measured production worst case 41,955 B), which is **not** part of
`TaskKind × Complexity × RiskLevel`. A unit matrix composed against a small
fixture's guidance would assert "zero infeasible" while real shapes are
infeasible — **a double whose simplification is the precise inverse of the
production fault, violating this design's own §10.2 rule 1.**

```
composed = skills_projected_bytes
         + [project_guidance].max_projected_bytes    # THE CAP (42,000)
         + dispatcher_authored_bytes                 # measured: policy + preamble
```

The matrix answers *"is this phase feasible for **any** legal repository this
dispatcher is configured to serve?"*. The **runtime preflight still composes and
measures the actual payload** — that is the authoritative check — but the matrix,
which is the test that must fail for a trap to be caught early, **cannot be made
to pass by choosing a convenient fixture.**

### 9.3 Reporting (§35)

The gate report carries, per phase, the before/after byte pair for at least
`implementation`/medium/medium, `implementation`/high/high,
`security_sensitive`/high/high and `refactor`/low/low. The full 120×2 matrix is
produced by a script under `scripts/` and attached, **with the guidance cap it
was evaluated against stated on the report** — the numbers are meaningless
without it. It must also state **the shipped default of `[lifecycle].enabled` and
`[lifecycle].preflight_required` in the canonical production config**, with the
runtime evidence of §4.12's proof chain.

---

## 10. Test strategy and what the doubles must not do (§29)

### 10.1 Per-invariant coverage

| Invariant | Unit | Real disposable integration |
|---|---|---|
| A-I1 feasibility before first worker | ✓ | ✓ (trap shape refused, no task created) |
| A-I2/3 determinism, lattice | ✓ | — |
| A-I4 provenance / hash drift | ✓ | ✓ (mutated **copy** of the install root) |
| A-I6 zero mutation | ✓ | ✓ (**sha256 of `state.json`**) |
| A-I8 activation | ✓ | ✓ (**live subprocess, isolated package tree**) |
| ZI-1 evidence authority | — | ✓ (**Z-RULE-1 positive control mandatory**) |
| ZI-2 no second source | ✓ (provenance reflection) | ✓ (journal has no `diff` row) |
| ZI-3/4/5 ignore-blind inventory | ✓ | ✓ (real `.gitignore`, real `info/exclude`) |
| ZI-6/7 path model | ✓ | ✓ (real hostile filenames) |
| ZI-8/9 ordering | ✓ (required constructor arg) | ✓ (**dynamic: syscalls raise**) |
| ZI-18/19/20 admin | ✓ | ✓ (real poisoned repo, **positive control**) |
| ZI-21 primary tree | — | ✓ (11-entry dirty fixture) |
| B-I5 no index mutation | ✓ | ✓ (`.git/index` sha256 + mtime) |
| B-I8/9/10 run identity | ✓ | ✓ (crash injection, **real process death**) |
| B-I12 idempotent landing | ✓ | ✓ (**recovery run twice**) |
| G-I1…G-I8 phase | ✓ (reflection + AST) | ✓ (**real E2BIG, real ENOENT**) |
| C-I1/2/3 timeout | ✓ | ✓ (**child that ignores SIGTERM**) |
| C-I5/6, Z-I23/24 progress | ✓ | ✓ (**real MCP stdio with a progressToken**) |
| D-I1…D-I8, I-I1…I-I10 | ✓ (synthetic `/proc`) | ✓ (**two real dispatcher processes**) |
| H-I1…H-I3 legacy | ✓ | ✓ (**byte manifest of the whole state tree**) |

A **small final live gate** with the real Claude CLI, in a disposable repository,
covers only what fake behaviour would make meaningless. **No full-voice-agent.**

### 10.2 What the doubles must NOT do

The B2 lesson, carried verbatim: the old shim's divergences were *"honest,
reasonable simplifications that happen to be the precise inverse of the two
production faults. No amount of testing against this double could have found
either defect."*

1. **A double must not make the production failure mode unreachable by
   construction.**
2. **A double must not tidy away the real dependency's inconvenient side
   effects.**
3. **A fixture must not pre-create the condition under test.**
4. **Prefer removing the double from the causal path over enriching it.**
   - **evidence**: no git double at all. Real `git init`, real worktrees, real
     untracked files, real `.gitattributes`, real `.gitignore`, real
     `info/exclude`, real `update-index` bits.
   - **run transaction**: no filesystem double. Real crashes (`os._exit` in a
     real subprocess) at the **canonical injection points (§15)**.
   - **ownership**: no `/proc` double for the integration arm. **Real children,
     real process groups, a real dispatcher killed with `SIGKILL`, and a second
     real dispatcher process.** A synthetic `/proc` fixture is used **only** in
     unit tests, to reach branches that cannot be produced on demand.
   - **progress**: no MCP double. Real stdio, real `progressToken`.
5. **Specifically forbidden for Gate 7**: a fake evidence generator returning
   `patch_file_complete=True`; a git double that never emits quoted paths; a git
   double with no `.gitattributes` support; a run-directory double where `mkdir`
   is idempotent; a process-identity double returning `ALIVE` for any live pid; a
   `Context` double whose `report_progress` records without a token check; **a
   sentinel test with no positive control (Z-RULE-1)**; **a single-process double
   standing in for a concurrent dispatcher.**
6. **NOT-TESTABLE is a first-class result** and is never recorded as PASS. A
   429/zero-token run is never a pass; a `NOT-MEASURED` matrix is never a green
   row.
7. **A double must not be more cooperative than the real thing.** The existing
   fake worker exits promptly; Subsystems C and D use a child that **ignores
   `SIGTERM`** and **journals every signal it receives**.
8. **A double must not make a CONCURRENT dispatcher unreachable.** Subsystem D's
   and §7.7's tests use **two real dispatcher processes**, not one process
   pretending.

### 10.3 Where earlier revisions repeated the mistake anyway

**In each case the design stated a property and named a proof that could not
observe it.** All are fixed, and the pattern is the reason this gate exists.

| Earlier proof | Why it could not fail | Fixed by |
|---|---|---|
| the AST pin on `_record_failure` | **zero** reclassified classes are raised in `server.py`; they propagate in from four other modules | §3.1.3 — the guard reads an object; a **call-site whitelist** replaces the `raise` scan |
| revision 2's phase parameter | **`PhaseTracker` was not what the guard read** — zero occurrences of `tracker.phase` in 4,459 lines | §3.1.3 |
| the planted-credential redaction test | the same author writes the plant and the assertion list | §7.3 — one accessor, and an AST test that **no other module opens the paths**, which is decidable |
| the 120×2 matrix | composed against a fixture's ~0 B guidance while production is ~42 KB | §9.2A — parameterised by the **cap** |
| mutant A-d | unkillable under the shipped config | §4.11 — deleted **in the implementer's table**, with a written equivalence proof, replaced by A-d′ |
| **`filter.*` "closed by inference"** | **no experiment was run at all** | §5.4 — deleted, plus **Z-RULE-1** as a standing rule |
| revision 2's `test_v1_fsmonitor_program_not_executed` | **no positive control — it would have passed on the day S-1 was live** | Z-RULE-1 |
| **revision 3's own Appendix A.2** | **armed three sentinels and drew a four-sentinel conclusion** — `reference-transaction` was never armed, so *"executes nothing"* was a negative result from an experiment that could not have produced a positive one | §5.4.1 (S-γ), Appendix A.2's methodological correction. **This is the first occurrence inside this document's own measured appendix, one page after it recorded the same hazard about somebody else's probe.** |
| **revision 3's `test_no_git_presentation_command_after_worker_launch`** | asserted `subcommand == "cat-file"` for every FINALIZE row while the design itself keeps B2's post-worker `rev-parse` — **the test could not pass against the pipeline it guarded** | §5.4.5 (B-1) |
| **revision 3's two documentation mutants** | bare string-absence scans, **red on day one** against quotations of the deleted text; the only route to green was to weaken them | §11.6 (N-4) — structural primary, string tripwire secondary |

### 10.4 A probe hazard that must not be rediscovered

> **If `GIT_INDEX_FILE` names a file that does not exist and `read-tree` has not
> been run, the index is empty, every tracked file reads as *deleted*, no content
> is compared, and no filter fires.**

Revision 2's layer 4 *required* the `read-tree`, so the production shape is the
one that fires. **Any probe of a hardened invocation that omits the `read-tree`
measures a repository state the design never produces.** This is Z-RULE-1's
failure mode occurring inside a *probe*, and it is the third time in this gate a
negative result came from an experiment that could not have produced a positive
one. A second such hazard, recorded for the same reason: creating a test file
whose name contains **literal backslashes** (`"caf\303\251.txt"` in a bash
double-quoted string is not UTF-8) and concluding that `ls-tree -z` C-quotes. It
does not. Use `CAFE=$(printf 'caf\303\251.txt')`.

### 10.5 The suite must not touch the operator's home

- **`tests/**` never shells out to `codex exec`** (§6.8) — nor to `claude` or
  `codex` at all (`CLAUDE.md` §3).
- **`tests/**` never reads or writes `~/.claude`.** `tests/conftest.py` already
  sets `HOME` into `tmp_path`; every Gate-7 fixture that spawns a subprocess does
  the same. The approved-skill manifest's pinned install paths *are* read — that
  is the hash verification — but **read-only**, and hash-drift tests operate on a
  **copied** install root.

---

## 11. The mutation suite (directive Q, §31)

### 11.1 Measured state

`scripts/mutation/` **does not exist** at the baseline. `find /tmp -iname
'*mutant*'` returns **six ephemeral text artefacts in a session-scoped
scratchpad** (two ad-hoc driver scripts, four result logs) — **none is a
declarative mutant, none is a runner, none is source-controlled, all vanish with
the session.** The replayable corpus is gone.

### 11.2 Invariants

- **Z-I18 (registry).** Every critical invariant named in this design appears in
  a source-controlled registry with **≥1 named mutant and ≥1 named killer test
  node id**. The runner **refuses to emit a gate-signing report** if any row is
  incomplete.
- **Z-I19 (matrix demotion, machine-checked).** **No mutant may name the 120×2
  matrix as its only killer.** The runner rejects such a row.
- **Z-I20 (production-active).** The runner refuses to start unless
  `production_activation_defects(config) == ()` — **the same predicate
  `server.main()` uses**, so the runner and production cannot drift.
- **Z-I21 (in source control).** `scripts/mutation/**` is tracked. **No mutant
  lives outside the repository, ever.**

### 11.3 Mechanism

```
scripts/mutation/
  run_mutations.py     canonical runner
  invariants.toml      NEW — the registry
  mutants/gate7/*.py   declarative: target file, exact anchor, replacement
  README.md            how to add a mutant; the A-d equivalence proof
```

```toml
[[invariant]]
id             = "ZI-3"
statement      = "the changed-path measurement consults no ignore source"
owning_wave    = "0"
design_section = "5.6"
mutants        = ["ZM-C1", "ZM-C2", "ZM-C6"]
killers        = ["tests/integration/test_inventory.py::test_baseline_venv_does_not_enter_changed_paths"]
```

Before applying a single mutant the runner asserts: (1)
`production_activation_defects(loaded_config) == ()`; (2) every row has ≥1 mutant
and ≥1 killer; (3) **no killer list consists solely of matrix node ids**; (4)
**every invariant id appearing as a heading token in `docs/GATE7-DESIGN.md`
(`A-I*`, `B-I*`, `C-I*`, `D-I*`, `G-I*`, `H-I*`, `I-I*`, `ZI-*`, `Z-I*`) appears
in the registry** — so an invariant cannot ship un-mutated by being omitted; (5)
**every declared killer node id exists** (`--collect-only`), so a typo is a hard
failure rather than a silent pass.

Then, per mutant: record `sha256` of every target → apply → run declared killers
(and, in `--full`, the whole suite) → restore → **verify byte-identical
restoration by sha256, failing the whole run if restoration is not exact** →
emit `mutations.json` with per-mutant caught/survived and first-killer node id.

**COULD STEP 4 PASS WHILE THE PROPERTY IS FALSE?** Yes — if an invariant is
removed from the design **and** from the registry in the same commit. That is a
**visible, reviewed act** rather than an omission, which is the achievable bar.
**Stated rather than claimed away.**

### 11.4 Runtime — the suite must be fast enough to actually run

| Mode | Runs | When |
|---|---|---|
| `--fast` (default) | each mutant's **declared killers only** | routine, per wave, per PR |
| `--full` | declared killers **and** the full suite, per mutant | gate time, once, and after any change to the runner itself |

**A `--fast` report may not be attached to a gate submission**, and
`mutations.json` records the mode. *A suite too slow to run is a suite that does
not run, which is precisely how the `/tmp` corpus died.*

### 11.5 The §31 named mutants, and their owning subsystem

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

Revision 3 adds the tables in §4.11, §5.4.7, §5.15, §6.12, §7.13 and §11.6 —
**each with a named targeted killer, none relying on the matrix alone.**

### 11.6 Mutants on the runner and the documentation itself

| Mutant | Named killer |
|---|---|
| **Z-M34** runner accepts a config with lifecycle disabled | `test_runner_refuses_an_inert_lifecycle_config` |
| **Z-M35** runner skips the registry completeness check | `test_runner_refuses_an_invariant_with_no_mutant` |
| **Z-M36** runner accepts a matrix-only killer list | `test_runner_refuses_a_matrix_only_killer_list` |
| **Z-M37** runner reports `caught` for a nonexistent killer node id | `test_runner_refuses_a_nonexistent_killer_node_id` |
| **Z-M38** runner skips sha256 restoration verification | `test_runner_fails_when_restoration_is_not_byte_identical` |
| **Z-M39** a `--fast` report is accepted as a gate artefact | `test_fast_report_cannot_sign_a_gate` |
| **Z-M40** derive `stdout_bytes` from a pump counter instead of the child's file | `test_stdout_bytes_is_the_child_file_size` |
| **Z-M41** accept a wave whose branch point is not the previous accepted wave | `test_wave_acceptance_report_names_the_previous_wave_commit` |
| **P-M9** state a crash-point count anywhere outside §15 | **`test_crash_point_count_is_stated_once`** — see the specification note below |
| **Z-M33** restore the "clips as before" sentence | `test_no_document_claims_the_review_input_is_clipped` — see the specification note below |

> **Both killers were MIS-SPECIFIED in revision 3, and a naive implementation of
> either is red on day one (N-4).** Revision 3 specified them as bare
> string-absence scans. Measured against revision 3 itself: *"ten injection
> points"* / *"all ten points"* appear **6** times and *"clips as before"* appears
> **6** times — **every occurrence a quotation of the deleted text**, in a
> blockquote or a table cell that records what was removed and why. Directives O
> and P are substantively satisfied; the *tests* were not implementable.
>
> **An implementer meeting a red test whose only route to green is to weaken it
> produces exactly the unfalsifiable assertion these two mutants exist to
> prevent.** So both are re-specified **structurally**, and the string scan is
> narrowed to live prose:
>
> | Killer | Structural assertion (primary) | String assertion (secondary) |
> |---|---|---|
> | `test_crash_point_count_is_stated_once` | §15's table has **exactly fifteen** `C`-prefixed rows; **no other `##`/`###` section in `docs/**` contains a markdown table whose first column matches `^\*\*C[0-9]+\*\*$`** | the banned strings do not appear **outside a blockquote, a fenced block or a table cell** |
> | `test_no_document_claims_the_review_input_is_clipped` | **no `[:N]` slice, `.truncate`, `textwrap.shorten` or equivalent is applied to the patch binding on the review path** (AST over `src/**`) | as above |
>
> The structural half is the proof; the string half is a tripwire for the
> **recurrence of the known sentence**, which is what actually happened twice.
> **The tripwire can still be evaded by a paraphrase and that is stated, not
> hidden** — the proof for the review path is
> `test_review_input_bytes_equal_patch_file_bytes`.

**P-M9 and Z-M33 are deliberately documentation mutants.** §18.5 makes this
document the specification, and the defects they guard are *document* defects
that shipped untested coverage. **A docs test is the only thing that can fail for
them.**

### 11.7 Backward compatibility

The 38 Gate-6-era mutants (Lanes J 9, N 5, O 16, Q 8) are **ported into this
runner as part of Wave A**, so the persisted suite is the whole suite. Lane L's
14 unreplayable mutants are recorded as `NOT_REPLAYABLE` with their provenance —
**never invented, never reconstructed from memory.**

**One measured caveat Sol must rule on:** Z-I20 requires a production-active
config, and `config/dispatcher.toml` is **gitignored and host-local**. On a fresh
clone or in CI it does not exist. Proposal: the runner loads the canonical config
when present, else `config/dispatcher.example.toml`, and `mutations.json` records
**which file it loaded and its sha256**; **a `--full` run that signs the gate must
record the canonical file.** *(Escalated as Z3-AMB-5, §18.3.)*

---

## 12. Waves (directives L and R)

### 12.1 The order

```
WAVE 0   AUTHORITY FOUNDATION
         §5.4 deletions + permitted repertoire · §5.5 base/fs snapshots +
         reconciliation + the inventory type · §5.6 ignore-blind measurement ·
         §5.7 byte path model · §5.8 administrative preflight + fingerprint +
         deny list · §5.9 primary tree · the native content primitive ·
         §3.1's EXECUTION PHASE mechanism (phase.py, _record_failure,
         refusals.jsonl)  [D-24] · §8 row 0 · §8 rows 3, 4, 5a ·
         docs/SECURITY.md amended IN THIS WAVE
WAVE A   LIFECYCLE / PREFLIGHT
         G7-1 · G7-5 · G7-6 · lifecycle profiles + future-phase preflight ·
         §8 row 1 (LAUNCH failures: start_worker, WorkerHandle) ·
         ACCEPTANCE REQUIRES production activation (§4.12)
WAVE B   RUN TRANSACTION / EVIDENCE INTEGRATION
         G7-2 · G7-7 · canonical patch · completeness flags · Fable refusal ·
         LAND_INCOMPLETE · INTEGRATES Wave 0's content primitive
WAVE D   DURABLE OWNERSHIP + FILE-BACKED STREAMS
         G7-8 · streams.py · owner classification · legacy reconciliation
WAVE C   STREAM-JSON TIMEOUT + POST-TIMEOUT VALIDATION
         G7-3
WAVE E   PROGRESS
         G7-4 · expected CLIENT-LIMITATION
FINAL    all waves · full suite · `--full` mutation replay · doctor · skills
         audit · guidance audit · activation checker · B4 check · real MCP
         stdio · disposable live Claude
```

**Wave 0 first**, because V-1, V-4 and V-5 are **live scope-enforcement bypasses
at the baseline reachable with the `Write` tool and no denied command**, and the
production freeze is held partly because evidence integrity is in doubt.
**Scheduling known live holes behind five waves is the outcome the freeze exists
to prevent.**

**D before C**, and the rationale is unchanged and was confirmed by the second
review: file-backing is what makes `stdout_bytes` mean *"bytes the child wrote"*,
and Wave C's central claim is that the number is **measured** rather than
asserted. **Doing C first would found that claim on a definition about to move.**

**Each wave starts from the previously accepted wave**, and **rebases rather than
merges**. No wave merges until its suite and the *cumulative* mutation suite are
green.

### 12.2 Wave 0 must be independent (directive L, fixes S-7)

Revision 2 gave Wave 0 the inventory and the two audits and required FULL SUITE +
FULL MUTATION REPLAY at its end — while the buckets, the completeness flags, the
ladder rows and the per-path classification that make the inventory *safe* landed
in Wave B, and the PREPARE-refusal mechanism landed in Wave A. Its own conflict
table conceded it: *"`git.py` — Wave 0 owns `_run_git`; Wave B owns the
generator"* — and the inventory **is** the generator's front half. **Wave 0 as
drawn could not be accepted on its own terms.**

> **Z-I7 (wave closure).** Every invariant a wave claims to close is closable by
> code that wave owns, with a killer test that wave owns, against a policy
> outcome that wave defines. **A wave that produces a finding with no landing
> state has not closed anything.** Machine-checked: the registry carries an
> `owning_wave` column, and the runner **refuses a wave-acceptance report in
> which any invariant attributed to that wave names a killer test or a ladder row
> owned by a later wave.**

**Revision 3's argument here was FALSE three times over (B-4).** It said:
*"§8's rows 0 and 1 belong to Wave A's phase mechanism — but rows 3, 4 and 5a do
not … **Wave 0 produces no finding that needs them.**"* That was the entire claim
that S-7 was closed, and §12.1 placed §5.8 and §5.5 in Wave 0 while §8 row 0
enumerates three refusals those exact sections produce:

| Wave-0 refusal | Defined in | Phase | §8 row |
|---|---|---|---|
| `RepositoryAdministrationUnestablished` / `Unreconciled` | §5.8.3 (Wave 0) | **PREPARE only** | **row 0** |
| `SnapshotBudgetExceeded` (PREPARE) | §5.5.3 (Wave 0) | PREPARE | **row 0** |
| `CheckoutTransformationBudgetExceeded` | §5.5.4 (Wave 0) | PREPARE | **row 0** |

**The first fires on the first dispatch against every repository** — §13's own
migration row says so in as many words. Shipped alone under revision 3's plan, a
Wave-0 PREPARE refusal would have propagated into the **baseline**
`_record_failure` (`server.py:2694`), whose mutable set is
`{CREATED, ROUTED, RUNNING, RESUME_REQUESTED}`; on the dispatch path `RUNNING` is
entered at `server.py:937`, ~100 lines before the spawn. **The refusal would have
landed the task `FAILED`, with `resume_count` and `run_count` already spent —
G7-6, the defect Gate 7 exists to fix, reintroduced by Gate 7's own first wave,
on every repository, on its first dispatch.**

And **Wave 0 could not have passed its own machine check**: Z-I7 refuses a
wave-acceptance report in which any invariant attributed to that wave names a
ladder row owned by a later wave, and **ZI-20**'s landing row is row 0. §11.3
check (4) requires every `ZI-*` heading token to be in the registry, so it could
not be omitted to dodge the check either. *A wave that produces a finding with no
landing state has not closed anything* — Z-I7's own words, applied to Z-I7's own
wave.

**DECISION D-24 — the PREPARE-refusal mechanism moves into Wave 0.** §3.1's
`phase.py`, `ToolExecution`, the parameterless `_record_failure`,
`refusals.jsonl` and **§8 row 0** are Wave 0's, **because Wave 0 owns the gate
that needs them.** Wave A keeps the lifecycle profiles, the future-phase
preflight, production activation, and **§8 row 1** — the LAUNCH row, which
belongs with `start_worker`/`WorkerHandle` and which Wave 0 does not touch.

The corrected statement, now true rather than load-bearing and false:

> **Wave 0 owns every ladder row its own findings land in — rows 0, 3, 4 and 5a.
> It produces no finding whose landing state is owned by a later wave.**
> `EvidenceIncompleteForReview` / `EvidenceExceedsReviewBudget` are Wave B
> refusals and land in row 0, which Wave 0 will already have built.

**PROVEN BY** `test_every_wave0_invariant_names_a_wave0_killer` — the registry
cross-check, which is the thing that would have caught the original defect —
**and** `test_wave0_prepare_refusal_leaves_state_byte_identical`, an integration
test that runs a Wave-0-only build against a repository with **no administrative
baseline**, asserts `RepositoryAdministrationUnestablished`, and asserts
`state.json` is **byte-identical** with no task directory created.
**COULD IT PASS WHILE FALSE?** No — it is the exact day-one path, and under
revision 3's plan it would have landed `FAILED`. **IF MIS-WIRED** — the task
lands `FAILED` and the byte-identity assertion fails immediately, loudly.

### 12.3 The honest resize — Wave 0 is the largest wave

The honest measure available before implementation is the count of named
artefacts each wave must deliver:

| Wave | New/moved modules | Invariants closed | Named tests | Named mutants | Ladder rows |
|---|---|---|---|---|---|
| **0** | `inventory.py`, `basetree.py`, `fssnap.py`, `reconcile.py`, `ignore.py`, `gitadmin.py`, `content.py`, `git.py` policy, **`phase.py`** | **~22** | **~55** | **~57** | **4** (0, 3, 4, 5a) |
| A | `lifecycle.py`, compact artifacts, `config_authority` activation | 9 | ~28 | ~15 | **1** (row 1) |
| B | `evidence.py`, `runs.py` | 8 | ~24 | ~17 | 0 |
| D | `ownership.py`, `streams.py` | 12 | ~24 | ~28 | 0 |
| C | timeout / stream-json / post-timeout validation | 7 | ~16 | ~16 | 0 |
| E | progress | 3 | ~8 | 4 | 0 |

**Wave 0 is the largest wave in the plan by every column except ladder rows** —
roughly Wave A and Wave B's mutant counts combined. Revision 1 called it *"the
cheapest wave"*; revision 2 said it was *"no longer small"* **without resizing
anything**; **revision 3 states the size and accepts it.**

**Why the size is accepted rather than reduced**, and this is where revision 3
departs from the second review's own recommendation (Y-7): shrinking Wave 0 to
argv + deny list + fingerprint + `-z` identity defers **V-4 and V-5 — two live
scope-enforcement bypasses reachable with the `Write` tool and no denied
command** — behind Waves A and B. Directive L takes the third option: **make Wave
0 self-sufficient rather than smaller.** The cost is schedule; the alternative
cost is correctness.

### 12.4 `server.py` is integrated SEQUENTIALLY

| Parallelisable | Serial (one lane at a time) |
|---|---|
| `inventory.py`, `basetree.py`, `fssnap.py`, `reconcile.py`, `ignore.py`, `gitadmin.py`, `content.py`, **`phase.py`** (all Wave 0), `lifecycle.py`, `evidence.py`, `runs.py`, `ownership.py`, `streams.py` | **`server.py` orchestration** |
| the compact artifact authoring + review | `git.py` — **Wave 0 owns it outright** (`_run_git` policy *and* the identity producer) |
| `scripts/mutation/**`, `scripts/gate/**` | `runner.py` (Waves D and C both touch worker execution) |
| tests for a new module | `models.py` / `state.py` schema additions |
| capability probes (Lanes U, X) | `locks.py` (Wave D) |
| `config_authority.py` activation predicate (Wave A, additive) | `config.py` `[lifecycle]` section (Wave A) |

**Revision 2's line *"`git.py`: Wave 0 owns `_run_git`; Wave B owns the
generator" is DELETED.*** That split was the mechanical cause of S-7. Wave 0 owns
`git.py` entirely for its slot; **Wave B builds `evidence.py` on top of a frozen
`inventory.py` API.**

**No blind merge of two branches that both edited `server.py`.** §33 is the
requirement most likely to be quietly violated under schedule pressure, which is
why it is stated twice.

### 12.5 Tests for wave independence

| Test | Proves | Could it pass falsely? |
|---|---|---|
| `test_wave0_modules_import_nothing_from_wave_b_modules` (AST import graph) | Z-I7 structurally | Only if a Wave-B symbol is re-exported through a Wave-0 module — so the test asserts the **module** graph, not just names |
| `test_wave0_suite_is_green_at_the_wave0_commit` | Wave 0 is acceptable on its own terms | **Yes, in one way**: it proves the suite passes, not that the wave closed what it claims. **That is why the registry check exists.** |
| `test_every_wave0_invariant_names_a_wave0_killer` (registry cross-check) | Z-I7 | Only if the registry is edited to attribute the invariant elsewhere — visible in the diff |
| `test_ladder_rows_0_3_4_5a_land_without_wave_a` | §12.2 (D-24) | No |
| **`test_wave0_prepare_refusal_leaves_state_byte_identical`** | the day-one path revision 3 would have landed `FAILED` | **No** — it is the exact first-dispatch path |
| `test_wave_acceptance_report_names_the_previous_wave_commit` | rebase discipline | No |

### 12.6 The Wave 0 residual that must not be papered over

**Directive L permits Wave B to integrate the native content primitive.** If
integration is Wave B, then between Wave 0's acceptance and Wave B's acceptance
the content path still uses the old generator. **Under this design that residual
does not arise**, because §5.4 *deletes* `git diff` in Wave 0 and §12.2 puts the
content primitive in Wave 0 — but the sentence must be checked at Wave 0
acceptance rather than assumed:

> **Wave 0's acceptance report must carry an explicit row stating whether any
> `git diff` / `git status` / `git ls-files` call site remains in `src/**`.
> Wave 0 must not state "the dispatcher's own measurement commands are no longer
> worker-influenced" until that row reads zero.** *(Escalated as Z3-AMB-1,
> §18.3.)*

---

## 13. Backward compatibility summary

| Surface | Change | Compatibility |
|---|---|---|
| MCP tool surface | **none** — still exactly four | the feasibility API is INTERNAL |
| `TaskEnvelope` / `envelope.json` | none | `SCHEMA_VERSION` stays `"1.0"` |
| `TaskRecord` / `state.json` | `+lifecycle_preflight`, `+runs_allocated` (optional) | old files load; `run_count` keeps its meaning |
| `RunRecord` / `dispatcher-result.json` | `+timeout_evidence`, `RunMetadata.+lifecycle_phase` (optional) | old files load |
| `ValidationResult` | `+phase` defaulting `"post_run"` | old files load |
| run directory | `+reservation.json`, `+expectation.json`, `+ownership.json`, `+landing.json`, `+events.jsonl`, `+git-invocations.jsonl`, `+fs-snapshot-{start,post}.json`, `+timeout.json` | additive |
| `evidence/diff.patch` | now contains untracked content **and is composed by the dispatcher** | strictly more complete. **Fable's prompt reads it in full or the review is refused (`EvidenceExceedsReviewBudget`); it is NEVER clipped.** The previous behaviour — clipping at `_MAX_PROMPT_DIFF_CHARS` and reviewing anyway — is **deleted, not preserved.** |
| `changed-paths.json` | `schema: "changed-paths/2"`, new keys, flags **produced by the generator** | additive; every v1 key keeps its meaning |
| **`changed_paths` semantics** | a worker-created file inside a base-ignored directory now **appears**; deletions and type changes now appear | **a deliberate, visible behaviour change — the G7-2 fix** |
| **task-state outcomes** | some runs that previously landed `FAILED` now land `POLICY_VIOLATION` | strictly more informative; the direction §28 requires |
| `stdout.raw` / `stderr.log` / `events.jsonl` | written by the child directly | same paths; **no redaction claim is made about them at all.** `docs/SECURITY.md` §1.5 is **rewritten** in Wave D |
| `DiffEvidence`, `DispatcherObservations`, `PrimaryTreeSnapshot` | names and field names retained; producers change | `primary_worktree_clean` becomes a genuine tri-state — **a reader that treated `None` as `True` was already wrong** |
| `check_scope` / `ScopeSpec` | operate on **`bytes`** | patterns encoded once at envelope validation; no envelope change. `docs/INTERFACES.md` §5 changes in the same wave |
| `git.py` public surface | `collect_diff_evidence`, `write_full_diff`, `primary_tree_status`, `_fold_untracked` **DELETED** | **no compatibility wrappers** — a retained wrapper is a live `git diff` call site |
| **`[lifecycle]`** | **required. Absence is a refusal. There is no production default and no in-production rollback lever.** | `config/dispatcher.example.toml` ships `true`; **a production host that upgrades without editing its config will not start**, with a typed payload naming the exact edit |
| worker deny list | `+Bash(git config:*)`, `+Bash(git update-index:*)`, `+Bash(git -C:*)` | additive; config may still only add |
| **repository administrative baseline** | **NEW: every repository needs one established once**, by `scripts/trust-repo-admin.py` | **a migration step.** The first Gate-7 dispatch against any repository refuses with `RepositoryAdministrationUnestablished` until an operator runs it. |
| **legacy tasks and runs** | **untouched — not one byte, not `mtime`, not mode.** No claim, no probe, no signal. | `get_task` gains an additive `ownership: {tracked: false}` block. **Revision 2's `COMPLETE`/`ORPHANED` rule is DELETED.** |
| `~/.codex/config.toml` | **no dispatcher change** | any Wave E harness snapshots / restores / **verifies by sha256** |

---

## 14. Documentation obligations

Three documents make claims this revision falsifies. **Each is amended in the
wave that falsifies it, not later**, and each has a named check.

| Document | Obligation | Wave | Check |
|---|---|---|---|
| `docs/SECURITY.md` §1.5 | **Rewritten, not amended in passing.** It currently states the write-time stderr-redaction property as a guarantee; after file-backing that is false. It must also carry the honest sentence in §5.16 about PREPARE, and the §4.12 qualification that the claim is *"the registered production entrypoint refuses to start inert"*, **not** *"production cannot run inert"*. | 0 (evidence), D (streams) | `test_no_document_claims_the_review_input_is_clipped` and a companion scan for the stale redaction sentence |
| `docs/INTERFACES.md` §5 | `check_scope` takes **bytes**; `collect_diff_evidence`, `write_full_diff` and `primary_tree_status` are **removed from the contract**. §4 of `CLAUDE.md` makes this the shared contract between modules written in parallel, so it changes **in the same wave** as the signature. | 0 | `test_interfaces_doc_matches_public_signatures` |
| `docs/STATE-MACHINE.md` | Gains the **run** state machine (§5.11A) beside the task state machine, and the note that `RUNNING` now requires a `WorkerHandle`. | A / B | reviewed with the wave |

**This document is itself specification** (§18.5), which is why §11.6 carries two
**documentation mutants**: two *document* defects have already shipped untested
coverage in this gate.

---

## 15. THE CANONICAL CRASH MATRIX (directive P)

### 15.1 The rule

> **There is exactly ONE crash-point table in this document. It has FIFTEEN rows,
> C1…C15. Every other section references it by row id and states no count of its
> own.**

Revision 2 had the fifteen rows and then said *"all ten points"* in §5.10 and
*"the ten injection points"* in §10.2 — **the only two numeric statements in the
document.** So amendment 7's five new points — **C9, C11, C12, C13, C14** — had
**no test plan**, including C12, which revision 2 itself called *"the
reachable-on-every-run point revision 1 missed"*, and C13, of which it said
*"idempotence that is only exercised once is an assumption"*.

### 15.2 The table

Phase is `ToolExecution.phase` at the moment of death. **Owner gate** marks rows
whose recovery is reachable only under `OWNER_GONE` (§7.7).

| # | Crash point | Phase | Durable state left | Claim | Reconciliation action | Owner gate | Named test |
|---|---|---|---|---|---|---|---|
| **C1** | after `mkdir runs/NNN`, before `reservation.json` | RESERVE | bare directory | **none** | **none** — index burnt by `mkdir(EEXIST)`; **the repository stays open** | n/a | `test_bare_run_directory_does_not_close_repository` |
| **C2** | after `reservation.json`, before `expectation.json`/spawn | RESERVE→LAUNCH | `RESERVED` | none | none at startup; `RESERVED`→`ABORTED_PRELAUNCH` on the next touch of that task | n/a | `test_reserved_run_without_claim_is_aborted_prelaunch` |
| **C3** | after spawn, before `ownership.json` | LAUNCH | `STARTING` + `expectation.json` (**no pid**) | **held** | `ORPHANED`, claim held, **candidate scan reported, never adopted** | yes | `test_crash_between_spawn_and_ownership_is_orphaned` |
| **C4** | after worker exit, before stream persistence | FINALIZE | streams already on disk (file-backed) | held | `FINALIZING` → evidence pipeline completes | yes | `test_streams_recovered_after_dispatcher_death` |
| **C5** | after streams, before evidence A | FINALIZE | `pre-validation-*` absent | held | `FINALIZATION_FAILED` | yes | `test_crash_before_evidence_a_is_finalization_failed` |
| **C6** | after evidence A, before validation | FINALIZE | evidence A preserved | held | `FINALIZATION_FAILED` | yes | `test_crash_before_validation_preserves_evidence_a` |
| **C7** | after validation, before evidence B | FINALIZE | `validation.json` preserved | held | `FINALIZATION_FAILED` | yes | `test_crash_before_evidence_b_preserves_validation` |
| **C8** | after evidence B, before `diff.patch` | FINALIZE | partial `.tmp` removed | held | `FINALIZATION_FAILED`; **no unmarked short patch** | yes | `test_no_unmarked_short_patch` |
| **C9** | after `diff.patch`, **before `changed-paths.json`** | FINALIZE | patch without its accounting | held | `FINALIZATION_FAILED`; completeness flags **never defaulted to true** | yes | `test_patch_without_changed_paths_is_finalization_failed` |
| **C10** | after `changed-paths.json`, before `dispatcher-result.json` | FINALIZE | evidence complete, unmarked | held | `FINALIZATION_FAILED`; `run_count` unmoved; `runs_allocated == N`; next resume gets N+1 | yes | `test_crash_after_patch_write_allocates_next_index` |
| **C11** | after `dispatcher-result.json`, **before `landing.json`** | FINALIZE→LAND | evidence complete; **no recorded intent**; task still `RUNNING` | held | **re-decide** the landing from the durable evidence (pure function) and apply it | yes | `test_complete_evidence_with_running_task_is_finishable_on_restart` |
| **C12** | **during `_land_state`, between two `transition()` calls** | LAND | `LAND_INCOMPLETE`; `landing.json` `applied=false` | **held** | **replay the recorded transitions idempotently** | yes | `test_crash_during_land_state_recovers` |
| **C13** | after the last transition, before `landing.json applied=true` | LAND | every target state already current | held | replay skips each, flips `applied`, reservation → `COMPLETE` | yes | `test_land_recovery_is_idempotent` (**recovery run twice**) |
| **C14** | during a claims-directory write | any | partial/unparseable claim file | **treated ACTIVE** | fail closed: `RepositoryRecoveryRequired` | classification row 12 | `test_partial_claim_file_is_active_claim` |
| **C15** | after `dispatcher-result.json`, before `run_count` save | LAND | `append_run` already atomic per file | held | `run_count` recovers as `max(run_count, highest COMPLETE index)` | yes | `test_run_count_recovers_from_highest_complete_index` |

**Injection mechanism:** a test-only fault hook keyed by row id, injected through
the store/generator seams — **never by monkeypatching `os` globally**. A **real
`os._exit` in a real subprocess** is used for **C3, C4, C10, C11, C12, C13** —
the rows where a genuine process death changes the answer — and an exception for
the rest. **C12 is run twice in the same test: kill, recover, kill *during
recovery*, recover again.**

### 15.3 Determinism and idempotence — the two obligations

**(1) The landing decision is a pure function of durable artefacts.**
`decide_landing(run_dir, evidence) -> LandingIntent` reads no clock except to
stamp `decided_at`, no live task state, and no config a later edit changed.
**PROVEN BY** `test_landing_decision_is_a_pure_function_of_durable_artefacts` —
two fresh interpreter processes, canonical JSON compared with `decided_at`
excluded, then again with `os.environ` cleared and the CWD moved. **COULD IT PASS
WHILE FALSE?** Yes, if the impurity is a read of live task state that happens to
be identical — **paired with `test_landing_decision_reads_no_task_state`
(AST: `decide_landing` and everything it calls may not reference `self.store`),
which is decidable.**

**(2) Replay is a fixed point.** `apply(apply(x)) == apply(x)` for every
reachable `x`. **PROVEN BY** three tests: `test_land_recovery_is_idempotent`
(run twice); `test_apply_landing_is_a_fixed_point` (table-driven over the cross
product of every `TaskState` and every `transitions` list any ladder branch can
emit, also asserting the third rule never forces a state); and
`test_two_dispatchers_replaying_one_landing_produce_one_landing` — **idempotence
against a *concurrent* replayer, which single-process idempotence does not
imply.**

**COULD THESE PASS WHILE FALSE?** The single-process test could, if the ladder
were re-run on replay and happened to agree — which is why the replay **asserts
the ladder function was not called**, via a seam counter rather than a mock of
the world. The concurrency test could pass by luck if the two replayers never
overlapped — which is why it asserts the **mechanism** (exactly one
`.recovering.*` marker) as well as the outcome.

**A recommendation, and a convention disclosure.** `TaskStore.transition`
(`state.py:415-463`) has **no compare-and-set**: load, check, write,
last-writer-wins. **The exclusion of concurrent writers rests entirely on the
reconciliation lock and the owner gate — a convention about where transitions are
called from, not a property of the store.** This design **recommends adding an
optional `expected_state` compare-and-set**, with mutant **P-M6** and killer
`test_transition_rejects_a_stale_expected_state`. **IF MIS-WIRED without it,** the
failure is a lost or doubled transition during a concurrent replay — **which is
precisely S-5 race 3, and the reason it should not be left to a convention.**

### 15.4 Durable writes that are NOT canonical crash points

Rather than inflate the canonical count, each is stated with why it needs no
reconciliation action and a named test.

| Section | Crash point | Why it is not a canonical row | Named test |
|---|---|---|---|
| §4.9 | feasibility computed, before `store.create()` | PREPARE: **nothing durable exists** | `test_prepare_crash_leaves_no_durable_state` |
| §4.9 | `store.create()`, before the preflight record | next touch recomputes; **never assumed feasible**. Self-healing. | `test_missing_preflight_record_is_recomputed_never_assumed` |
| §4.9 | preflight written, before reservation | `envelope_digest` + `manifest_version` invalidate a stale record | `test_stale_preflight_record_is_reproved` |
| §4.9 | resume PREPARE crash | `state.json` untouched — the same guarantee as G-I8 | `test_prepare_crash_leaves_state_byte_identical` |
| §6.10 | soft deadline fired, before hard deadline | nothing persisted beyond the child's own file — **C3/C4** | (covered) |
| §6.10 | `SIGTERM` sent, before `SIGKILL` | the child may survive — **C3/C4** plus §7.8 | (covered) |
| §6.10 | worker exit, before `timeout.json` | streams on disk; `FINALIZING`; remediation recomputed — **C4** | (covered) |
| §6.10 | post-timeout validation half-run | `validation.json` holds what completed, tagged `phase="post_timeout"` — **C7** | (covered) |
| §5.5 | after `worktree add`, before the START snapshot | the worktree exists with no START snapshot. Materialisation is re-run **only if no worker has been launched** (no `ownership.json`); otherwise `FINALIZATION_FAILED` — **a START snapshot cannot be reconstructed after a worker has run, and inventing one is the laundering this gate exists to stop.** | `test_start_snapshot_is_never_reconstructed_after_a_worker_ran` |
| §5.5 | during `start-bytes/` capture | content-addressed `.tmp` names make a partial capture harmless; an absent reconciliation re-runs materialisation | `test_partial_start_bytes_capture_is_harmless` |
| §5.5 | after the POST snapshot, before the inventory | the POST snapshot is durable; the inventory is recomputed from the two durable snapshots, deterministically. **No re-walk** — a re-walk after a crash would measure a tree that has since changed. | `test_crash_before_inventory_recovers_from_durable_snapshots` |
| §5.8 | after `git-admin-pre.json`, before launch | idempotent; recapture on restart is harmless because no worker has run | `test_admin_precapture_is_idempotent` |
| §5.8 | during `trust-repo-admin.py`'s write | atomic temp+rename; **a partial baseline is absent, and absent ⇒ refusal, never "trust everything"** | `test_partial_baseline_is_absent_not_trusted` |
| §5.8 | after the worker exits, before `git-admin-post.json` | the tamper verdict is `unknown` ⇒ **treated as tamper** ⇒ `POLICY_VIOLATION`. **Never `clean`.** | `test_admin_capture_failure_is_tamper` |
| §5.9 | during the primary POST walk | the primary invariant is `unknown`, **never `held`**; `primary_tree_unchanged` is `None`, **never `True`** | `test_primary_snapshot_failure_is_unknown_not_clean` |

### 15.5 Mutants

| Mutant | Named killer |
|---|---|
| **P-M1** skip `landing.json`; apply transitions directly | `test_crash_during_land_state_recovers` |
| **P-M2** make landing replay non-idempotent | `test_land_recovery_is_idempotent` + `test_apply_landing_is_a_fixed_point` |
| **P-M3** re-derive the landing verdict on replay | `test_landing_decision_reads_no_task_state` (AST) + the ladder-call seam counter |
| **P-M4** force a transition when it is neither current nor legal | `test_apply_landing_is_a_fixed_point` |
| **P-M5** release the claim at `LAND_INCOMPLETE` | `test_land_incomplete_holds_repository` |
| **P-M6** *(recommended addition)* drop `expected_state` from `TaskStore.transition` | `test_transition_rejects_a_stale_expected_state` |
| **P-M7** treat an unparseable claim file as absent | `test_partial_claim_file_is_active_claim` |
| **P-M8** default the completeness flags to true when `changed-paths.json` is missing | `test_patch_without_changed_paths_is_finalization_failed` |
| **P-M9** state a crash-point count anywhere outside §15 | **`test_crash_point_count_is_stated_once`** (documentation mutant) |

---

## 16. §35 gate report rows this design must produce

```
GATE 7 .............................. PASS/FAIL
  baseline SHA / final SHA · tests (passed/failed/skipped)
  mutations (x/x caught) — MODE: --full — config loaded: <path> sha256 <…>
  G7-1 lifecycle feasibility ........ 120x2 matrix, guidance cap 42,000 B, 0 infeasible
  G7-2 complete untracked evidence .. 191-line file visible to Fable
  G7-3 timeout evidence/recovery .... stream-json; absent result event = timeout
  G7-4 event-driven progress ........ CLIENT-LIMITATION (Codex 0.149.0)
  G7-5 compact profiles + bytes ..... per phase, before/after
  G7-6 zero-mutation preflight ...... state.json sha256 identical, per refusal class
  G7-6 production activation ........ PASS
      registered console script ..... sol_claude_dispatcher = server:main (1 entry)
      production entrypoint, canonical config, unmodified env, NO expectation flag:
          started ................... YES   tools/list = 4
      production entrypoint, inert config, isolated package tree:
          refused ................... YES   exit 2, stdout 0 bytes,
                                            error=ProductionActivationDisabled
      config/dispatcher.example.toml  lifecycle.enabled=true preflight_required=true
      check-production-activation.py --expect active  (CORROBORATING, not enforcing)
  G7-7 durable run reservation ...... mkdir allocator; index never reused
  G7-8 restart ownership ............ owner classified before any action
  V-1 evidence authority ............ post-worker git: cat-file + B2 rev-parse ONLY
      FINALIZE journal rows .......... {cat-file: N, rev-parse: M}; M == B2 call count
      presentation commands .......... 0
      positive control fired ........ YES  (Z-RULE-1)
  V-2 path identity ................. bytes end-to-end; hostile-name pipeline test
  V-4 index bits .................... structurally irrelevant (no index is read)
  V-5 self-hiding gitignore ......... ignore-blind snapshots; unchanged_count scalar
  crash points ...................... 15/15 injected; C12 run twice
  legacy tasks ...................... byte-identical manifest; 0 claims written
  concurrent dispatchers ............ 2 real processes, different repos, both complete
  get_task polls (0) · MCP tools (4) · B2 PASS · B3 PASS · B4 PASS
  full-voice-agent touched .......... NO   (06bfcd61, 11 dirty, verified before/after)
  ~/.claude touched ................. NO
  ~/.codex semantic changes ......... NONE — sha256 before/after recorded
  client versions ................... claude 2.1.237 · codex 0.149.0 (pin verified)
  PRODUCTION DISPATCH FREEZE MAY BE LIFTED: YES/NO
```

**`~/.codex` and the client-version rows are produced by measurement, not
assertion**, and the activation rows are produced **by the real runtime with no
operator-supplied expectation.** That is the difference between N-a's finding and
its remedy.

---

## 17. The Y-1 … Y-10 decision table, mapped to revision 3

Sol requires each of the second review's ten decisions mapped to the **exact**
revision-3 section that resolves it, **with any item the A–T directives do not
resolve named plainly rather than force-mapped.**

| # | Decision | Resolved in | Status |
|---|---|---|---|
| **Y-1** | What actually closes Tier-0 `filter.*` execution (S-1)? | **§5.4** (the whole *class* of presentation commands is deleted, not hardened), **§5.4.1** (two surfaces), **§5.4.3** (three commands measured clean on both), **§5.4.6** (**the killer test `filter.*` never had, with a mandatory positive control**), **§12.2** (the content primitive is in Wave 0) | **RESOLVED — and the finding is worse than S-1 recorded.** `git diff --name-only -z` — revision 2's own authoritative tracked-path source — **fires the filter**, measured independently by two lanes. So the vector was *inside Wave 0's own inventory*, ordered by §8 before the row that would report it. **After the worker launches the dispatcher runs exactly two git commands: `cat-file` and B2's `rev-parse --verify HEAD^{commit}` — both measured clean on all three armed surfaces, no presentation command.** Revision 3 claimed *one* and was false in its own text; the claim and its journal test are corrected in §0.2 and §5.4.5, **not** the command. The residual is named in §12.6. |
| **Y-2** | Bind `phase` to the tracker; add the loud cross-check; add mutant A-i (S-2) | **§3.1.3** (the parameter is **deleted**, not bound), **§3.1.7**, **§3.1.8**, **§4.11** | **RESOLVED, and stronger than asked.** Y-2 asked for the guard to read the tracker; revision 3 **removes the parameter entirely**, so there is no literal to get wrong. **Y-2's item 2 is refined rather than copied**, and the reason is measured: Y-2's cross-check (*"PREPARE + task state ∈ {CREATED, ROUTED, RUNNING, RESUME_REQUESTED} → loud"*) has a **real false positive**, because closing Z2-G-F2 requires a *legitimate* PREPARE refusal (`ResumeNotPermittedFromState`) precisely when the state is `RUNNING`. **A flag that fires on routine refusals is worse than no flag.** The substituted contradiction — *PREPARE while this execution already holds a reservation or a handle* — is impossible by monotonicity and has no false positive. |
| **Y-3** | Absolute suppressed set, or pre/post delta (S-3 / OQ-B6)? | **§5.6**, **§5.5.7** | **RESOLVED — and SUPERSEDED: neither.** There is **no suppressed set and no ignore query at all**. `changed_paths` is the difference between two **ignore-blind** dispatcher-owned snapshots, so `.venv` is in neither delta and collapses to `unchanged_count`, **an int that cannot become a path list**. This is strictly stronger than a delta: nothing can remove a path because nothing is consulted. **OQ-B6 is deleted.** Z3's F5 case (a new file inside an already-ignored directory) is caught trivially, and Z1's case — **a modification to an already-existing ignored file**, Sol's explicit §C requirement — is caught too, which a delta over a *path set* could not express. |
| **Y-4** | Which rule governs a pre-Gate-7 run directory (S-4)? | **§7.6** (H-I1…H-I3), **§7.6.3** (the claim-coverage theorem), **§7.14** | **RESOLVED.** A run directory with no `reservation.json` is **LEGACY** — not `ORPHANED`, no claim, **not modified, not one byte**. Reconciliation is **claim-driven** and **never walks `state/tasks/**`**. Revision 2's contradictory `COMPLETE`/`ORPHANED` sentence is **deleted**. Measured basis: all five existing tasks are populated and **none is in `RUNNING`** — revision 2 would have written five `ORPHANED` claims and **permanently closed production** the moment the freeze lifted. |
| **Y-5** | Must reconciliation prove the OWNING dispatcher is dead before acting (S-5)? | **§7.7.2** (dispatcher identity + kernel liveness lock), **§7.7.3** (twelve-row owner truth table + action table), **§7.7.4** (single-flight + `TerminationAuthority`), **§7.8** (every deadline row inside `OWNER_GONE`) | **RESOLVED.** Owner classification is **first**, uses **two independent signals**, and **disagreement is `OWNER_AMBIGUOUS`, never resolved by preferring one**. The signalling path is **reachable only while holding the dead owner's liveness flock**, which the kernel refuses while that owner lives — so it is not a policy check a future edit can forget to call. **What remains conventional is stated:** same-uid processes can always signal each other; the claim is that *the dispatcher's own code path cannot*. |
| **Y-6** | Correct the three amendment contradictions before Wave A (S-6) | **A-d → §4.11** (deleted **in the implementer's table**, with the equivalence proof, replaced by A-d′). **"clips as before" → §13 and §5.11** (both sentences deleted; replacement text in §13; `test_no_document_claims_the_review_input_is_clipped`). **"all ten points" → §3.5, §15, and mutant P-M9** (a **documentation mutant**, the only thing that can fail for a document defect). | **RESOLVED, all three limbs.** The third limb — the crash-point count — **appears in no directive** and is covered here because it would otherwise ship untested: revision 2 had fifteen rows and two "ten" statements, so **C9, C11, C12, C13 and C14 had no test plan.** |
| **Y-7** | Re-cut the waves (S-7) | **§12.1, §12.2 (D-24), §12.3, §12.4, §12.5** | **NOW RESOLVED — it was NOT resolved in revision 3 (B-4).** Taking directive L's third option was legitimate and honestly costed, but the dependency §12.2 *claimed to have broken was not broken*: three Wave-0 refusals (`RepositoryAdministrationUnestablished`/`Unreconciled`, `SnapshotBudgetExceeded`, `CheckoutTransformationBudgetExceeded`) land in §8 **row 0**, which revision 3 assigned to Wave A — so a Wave-0-only build would have reached the baseline `_record_failure` and landed the task **`FAILED` on the first dispatch against every repository**, reintroducing G7-6 through Gate 7's own first wave. Wave 0 could not have passed Z-I7's machine check either. **D-24 moves §3.1's phase mechanism and §8 row 0 into Wave 0**, which makes §12.2's sentence true rather than load-bearing and false. |
| **Y-8** | What repository-visible artefact carries the shipped default (N-a)? | **§4.12** (change 5 + the seven-conjunct proof chain), **§9.3**, **§16** | **RESOLVED AND EXCEEDED.** Y-8 asked for a tracked artefact plus a verbatim checker row. Directive N requires more: **the registered production entrypoint itself refuses to start**, with **no operator-supplied expectation flag**, proven by a **live subprocess negative control in an isolated package tree**. `check-production-activation.py` is **demoted to a corroborator**. `config/dispatcher.example.toml` is tracked and asserted in `tests/**`, which the gitignored canonical file can never be. |
| **Y-9** | Is `.gitignore`/`.gitattributes` tampering "any write", "a write that hides a path", or "a write that hides a path this run created" (N-b)? | **§5.6.6** | **MOOT, NOT ANSWERED — and this needs Sol's explicit ratification.** Under an ignore-blind measurement **no worker write suppresses anything**, so a `.gitignore` write is not an attack: it is an ordinary file change, scope-checked like any other, and lands `POLICY_VIOLATION` only by the ordinary rule. This **disposes of the cost** Z3's option (iii) carried honestly (a legitimate *"generate `dist/`, then gitignore it"* task landing `POLICY_VIOLATION`) — it does not. The tamper marker narrows to `.git/**` and `$GIT_COMMON_DIR/**` writes, which §5.8 owns. **Sol has not ruled on Y-9; §18.4 asks for it explicitly rather than inheriting it from a draft.** |
| **Y-10** | A fourth bucket for symlink/FIFO/device, treated like `untextual` (N-e)? | **§5.5.9**, **§5.11.5** | **ADOPTED — and this needs Sol's explicit ratification.** `UNREPRESENTABLE_KIND` does not block the review; `refused` is reserved for *unreadable* and *changed-during-measurement*. **Measured basis:** this repository contains **4** ignored symlinks and **production contains 1** — a number neither review recorded. Under revision 2's rule that single symlink **kills every Fable review of production, forever**, for a reason unrelated to any task. R-13's reasoning applies unchanged: **a symlink has no text representation either.** **Sol has not ruled; §18.4 asks.** |

**Summary for Sol, after the third review.** Eight of the ten are **resolved**
(Y-1 … Y-8) — but two of those changed status in revision 4:

- **Y-1** was *resolved in substance and overstated in claim*: the class deletion
  genuinely closes `filter.*` and the third review independently reproduced it,
  **but the row's own headline sentence was false** (B-1) and the two-surface
  method it rested on was incomplete (B-2). **Both corrected; the section still
  resolves the decision.**
- **Y-7 was NOT resolved in revision 3** (B-4) and is resolved here by **D-24**.
  It is the one row the third reviewer judged differently from the document, and
  the reviewer was right.

**Y-9 and Y-10 remain adopted as forced consequences of directives C, K and O
without an explicit Sol ruling.** Both change what lands `POLICY_VIOLATION` and
what blocks a review; **Y-10 is load-bearing — without it the single ignored
symlink in `/home/dev/full-voice-agent` kills every Fable review of production
forever.** They are named plainly rather than force-mapped, for the third
revision running.

---

## 18. WHAT SOL MUST RULE ON

**Clearly marked, not decided by any lane.** Ordered by how much damage a wrong
answer does.

### 18.1 From the evidence-authority lane (Z1)

**Z1-G-1 — "PREPARE is trusted" is FALSE BY MEASUREMENT, and the fix reframes a
whole section.** Directive B says to build the base and start snapshots *"while
PREPARE is still trusted"*. Measured: the dispatcher's own `git worktree add`
executes a worker-chosen **smudge filter** and a `post-checkout` hook, from a
*previous* task's poisoning of shared administrative state, and **revision 2's
hardening does not stop the smudge.** **PREPARE is not trusted by virtue of
preceding the worker; it is *made* trusted by §5.8's raw preflight running
first.** This revision resolves it by ordering (§5.8 is step 0; `worktree add` is
step 3; step 3 is gated on step 0) and specifies `dispatcher_raw` materialisation
as the structural alternative. **Sol must confirm the ordering is the intended
reading, because it changes §5.8 from a *detection* section into a *precondition*
section.**

**Z1-G-2 — directive F versus §3.4's "no excusal path and no ignore list".** A
raw traversal of the primary tree observes a **strictly larger** set than
`git status` did, including build churn the previous mechanism could not see.
Treating every such divergence as `POLICY_VIOLATION` makes the flag routine;
treating none as one **looks like** the ignore list §3.4 forbids. §5.9.4 reports
everything, keeps the previously-observable set at its previous verdict, and
**grades only the newly-observable set**, with the grading switchable and
reported. **This needs a Sol ruling, not a lane's judgement.** If Sol disagrees,
the switch defaults to `true` and the cost is false `POLICY_VIOLATION`s on any
repository with build churn. **Related and separable:** whether the production
primary tree runs with `content_hash_all` (~18 s cold × 2 per run) or
`stat_identity` (466 ms × 2) — **the numbers are in §5.9.3 and the decision is
policy, not engineering.**

**Z1-G-3 — directive A versus the retained `primary_worktree_clean` /
`porcelain_status`.** Those two fields are literally `git status` output today.
This revision keeps the field names and **re-derives their values from dispatcher
data**, which required making `primary_worktree_clean` a genuine tri-state. The
alternative — deleting them — is cleaner but touches `DispatcherObservations`,
which §2 protects. **Compatibility was chosen; Sol should say which it prefers.**

**Z1-G-4 — directive C's "only its DELTA is attributable" versus scope on a
resume.** Directive B, taken literally, would not re-scope-check a path a prior
run changed — which creates a laundering route: make the forbidden write in run
1 (lands `POLICY_VIOLATION`), resume, and run 2 reports a clean scope. §5.5.6
scopes the **union** of the run delta and the cumulative delta and labels each
entry's `origin` so attribution stays exact. **This is a widening of the literal
text and Sol should confirm it.**

**Z1-G-5 — directive E deletes a mechanism the second review called
"SUFFICIENT".** Directive E's *"make the worker-controlled index irrelevant"*
**deletes** revision 2's clean `GIT_INDEX_FILE` + `read-tree` + `ls-files -v`
layer — which Y-4's V-4 assessment called *"the correct and only measured
lever"*. **Both are right for their own pipeline:** the clean index is the
correct lever *if you are running `git diff`*, and irrelevant if you are not.
**The integrated document must not carry both**, and §5.8.5 says so. Sol should
confirm the deletion is intended.

**Z1's `REQUIRES-PROBE` list — and the honest one at the end.** Each is
**reasoned, not measured**, and must not be integrated as though it were:
**(0) RETIRED by the third review:** `worktree list --porcelain`,
`rev-parse --absolute-git-dir` and `--git-common-dir` are now **measured clean on
all three armed surfaces** with a positive control and are **permitted**
(§5.4.3); (2) `dispatcher_raw`
materialisation is untested **from the worker's side**; (3) the dispatcher-composed
unified diff has **not** been validated against `git apply` for the four §9 edge
cases — **a genuine new risk that must be retired before Wave B**;
(4) submodules; (5) reftable ref storage (git ≥ 2.45) and its refusal path;
(6) `st_ctime_ns` forgery resistance; (7) the `sys.addaudithook` mechanism
against this codebase's `asyncio.to_thread` model; (8) the HMAC-signed admin
baseline — **a proposal about filesystem containment under a same-uid threat
model, not a measurement**; (9) the base-committed ignore matcher and its
agreement corpus; (11) every measurement is **git 2.43.0 on this host**, and a
git upgrade must re-run the Z-RULE-1 tests.

> **(10) — the one Sol should weigh most, and it has now been PROVEN rather than
> feared.** Revision 3 recorded Z1's caveat: *"S-α and S-β are the two surfaces I
> know about, not the two that exist."* **The third review armed a third and it
> fired: `git worktree add` executes `$GIT_COMMON_DIR/hooks/reference-transaction`
> on a ref update, even with `--no-checkout`.** Three surfaces are armed now and
> the permitted set is clean on all three. **The caveat stands unchanged for a
> fourth**, and it is why §5.4.3's safety argument is *structural* (object-store
> reads and ref resolution touch neither the working tree, the index, nor any ref
> mutation) rather than an enumeration — and why widening the repertoire is a Sol
> decision, not a convenience.

### 18.2 From the phase-and-ownership lane (Z2)

**Z2-Q1 — a LAUNCH failure leaves the task in `ROUTED` / `RESUME_REQUESTED`.**
Directive G says a spawn failure leaves the lifecycle **unchanged**; revision 2
landed it `FAILED`. This revision implements the directive, which leaves a task
in a non-terminal, non-worker-actionable state with an `ABORTED_PRELAUNCH` run
beside it. **Recommendation:** keep the directive (the task genuinely did not
run, and `FAILED` asserts a run that never happened), and permit **one**
additional write — `last_error` via `save()`, **no transition** — so `get_task`
shows the cause without a lifecycle change. That write is not byte-identical,
which is correct: **byte-identity is a PREPARE guarantee, and by LAUNCH a run
index has already been burnt.** **Sol must confirm** whether that write is
permitted, and whether a `ROUTED` task with a failed spawn is re-dispatchable as
a new task or needs an explicit terminal path.

**Z2-Q2 — the canonical crash count.** **Fifteen** as ordered, with §4.9's four
durable-write rows routed to §15.4 with named tests; or **nineteen**, absorbing
them. **Recommendation: fifteen.** Either way **no row loses a test.**

**Z2-Q3 — Y-2's cross-check has a measured false positive.** See the Y-2 row in
§17. **Recommendation: accept the substitution.**

**Z2-Q4 — reconciliation moves out of `Dispatcher.__init__`.** Directive I gives
this as context but does not rule. **Cost, stated:** a repository nobody touches
again is never reconciled; its claim keeps it closed and `get_task` still reports
it, so the §23 residual widens from *"no dispatcher ever restarts"* to *"no
dispatcher ever touches this repository again"*. **Recommendation: move it.** A
constructor that may signal a process group and can only report failure as
`SystemExit(2)` before the transport exists is the wrong place — **and it is the
mechanism that made S-5 destructive rather than merely wrong.**

**Z2-Q5 — `RepositoryBusy` versus a distinct code for "another dispatcher owns
this".** This revision reuses `RepositoryBusy` (retryable) with the owner's
`instance_id` in `details`. **Recommendation: reuse it** — the condition genuinely
is "busy", and a not-retryable code here would recreate S-5's *"a healthy run
needs human intervention"* outcome. Sol may prefer a distinct **retryable** code
for observability.

**Z2-Q6 — a pre-Gate-7 task genuinely stuck in `RUNNING`.** None exists today.
H-I4 says such a task is `LEGACY-RUNNING` forever, with no claim and no recovery
block. **Recommendation: accept it.** It is exactly today's behaviour, and
inventing a claim for it is the S-4 bug wearing a different hat.

### 18.3 From the structure-and-policy lane (Z3)

**Z3-AMB-1 — Wave 0's residual sentence.** §12.6 requires Wave 0's acceptance
report to carry a row stating whether any `git diff` / `git status` /
`git ls-files` call site remains in `src/**`, and forbids the SECURITY.md
sentence until that row reads zero. **Sol should confirm that Wave 0 may not be
accepted with a non-zero row.**

**Z3-AMB-2 — "classification in Wave 0" vs "content in Wave B".** Directive K
puts *unsupported content classification* in Wave 0; directive M preserves
scope-before-content. This revision resolves it by ordering **inside** Wave 0
(identity → verdict → classification) with a required constructor argument.
**Sol should confirm that "classification in Wave 0" does not mean patch
generation in Wave 0** — §12.2 assumes it does not.

**Z3-AMB-3 — the production rollback lever disappears.** Directive N makes the
production entrypoint refuse to start when lifecycle is off, so after Wave A
**there is no in-production rollback**: rolling back means reverting code or
running `dev_server`. Treated as intended — it is what "enforceable" means — but
**it is a real operational change and Sol should confirm.**

**Z3-AMB-4 — the `dev_server` opt-out's shape.** An **argv flag**
(`--allow-inert-lifecycle`), never an environment variable, because an env-var
opt-out would reconstruct precisely the B4 defect. **Sol should confirm the flag
and confirm no gate script needs an inert production entrypoint.**

**Z3-AMB-5 — the mutation runner on a host with no canonical config.**
`config/dispatcher.toml` is gitignored and host-local, so on a fresh clone or in
CI it does not exist. Proposal in §11.7. **Sol should ratify or replace it.**

**Z3-AMB-6 — refusing a Fable review is not actionable after the fact.**
Directive O is correct that a clipped review is worse than no review, but
`EvidenceExceedsReviewBudget`'s remediation (*"narrow `allowed_paths`, split the
work"*) is only actionable **before** dispatch — after the run, the work exists
and is unreviewable. **Should Wave A's feasibility preflight also refuse a task
whose predicted evidence cannot fit the review budget**, making the refusal a
PREPARE-phase fact at dispatch time rather than a dead end at review time? **No
directive covers it.**

**Z3-AMB-7 — Y-9 and Y-10** — see §18.4.

**Z3-AMB-8 — the identity producer is a recommendation, not a lane's decision.**
The three-command permitted set is measured three ways (no execution on either
surface, wall-clock, exact agreement with git on the production repository), but
it changes *what produces the inventory*. **The type in §5.5.7 is unaffected by
the choice; only the producer paragraph is.**

### 18.3A Decisions arising from the third review

**T-1 — the post-worker repertoire is `{cat-file, rev-parse}`** (B-1). This
revision adopts the reviewer's recommendation: B2's post-worker check is a §2
non-regression, `rev-parse --verify HEAD^{commit}` is measured clean on all three
armed surfaces, and the correction belongs to the claim and the test rather than
to the command. **Sol should confirm**, because the alternative — a `{cat-file}`
FINALIZE set — is only reachable by deleting B2's post-worker verification, which
reopens task `49231f6e`'s defect.

**T-2 — S-γ, and whether a fourth surface must be probed before Wave 0** (B-2).
Three surfaces are now armed and the permitted set is clean on all three. **Z1's
caveat is no longer a caveat but a demonstrated fact**, so §18.5's attack item 1
is answered *yes* for the third surface. **Sol should decide whether Wave 0 may
begin on three armed surfaces plus a structural argument, or whether a systematic
sweep of git's hook and program-invocation points is a Wave-0 precondition.**

**T-3 — Z-4's status, OPEN pending Lane Z5.** `dispatcher_raw` is demoted from
*structural* to *gated*. Whether it regains structural status depends on Lane Z5's
measurement of a fire-nothing materialisation path. **Sol should also rule on
whether `-c core.hooksPath=<empty>` is acceptable in Z-4's argv** — it works
(measured) but it is exactly the flag-hardening §5.5.5 rejects on principle, and
adopting it would make Z-4 *gated by a flag* rather than *structural*.

**T-4 — B-3's line, and `scope_check_base_ignored`.** ZI-25/26/27 draw the line at
**creation is bulk, modification is not**. **Sol should confirm**, and confirm that
`scope_check_base_ignored = false` applying **only to `added` paths** is the right
default. *(If Sol instead wants any base-ignored change to clear
`patch_file_complete`, that is a one-line change to §5.5.9's table and it makes
Fable refuse after any build run — the cliff Y-10 exists to avoid, in a new
place.)*

**T-5 — D-24's wave boundary** (B-4). The PREPARE mechanism and §8 row 0 move into
Wave 0. The alternatives the reviewer listed are: move §5.8's gate and the two
budgets into Wave A; re-order so Wave A precedes Wave 0 (which directive R forbids
and which defers two live bypasses); or abandon the independence claim. **Sol
should confirm D-24 rather than let an implementer build it informally under
schedule pressure.**

**T-6 — the widened repertoire** (N-1). `config --get remote.origin.url`,
`rev-list --max-parents=0 HEAD` and `rev-parse --is-inside-work-tree` were **live
in `src/**` and unlisted** while §5.4.3 called itself exhaustive; all three are
measured clean on all three surfaces, as are the three `REQUIRES-PROBE` rows now
retired. §5.4.3 says widening is a Sol decision. **Sol must ratify the widened set
— with its measurements recorded — or order the identity producer rewritten.**
**Lane Z5 is producing a definitive git-invocation × attack-surface matrix; this
design adopts it as the repertoire's authority when it lands.**

**T-7 — promote `TaskStore.transition`'s compare-and-set from *recommended* to
*required*?** §15.3 discloses in bold that concurrent-writer exclusion *"rests
entirely on the reconciliation lock and the owner gate — a convention"*, and that
the failure *"is precisely S-5 race 3"*. The third reviewer agreed the disclosure
is honest and declined to make it blocking, because the reconciliation lock plus
single-flight rename covers the reachable path. **Sol should decide whether P-M6
is a requirement.**

### 18.4 Two decisions adopted without an explicit ruling

**Y-9 (`.gitignore` / `.gitattributes` tamper) is MOOT under §5.6** and
**Y-10 (the fourth content bucket) is ADOPTED under §5.5.9/§5.11.5.** Both change
what lands `POLICY_VIOLATION` and what blocks a review; **both are load-bearing;
both were adopted as forced consequences of directives C, K and O rather than
from a Sol ruling.** They should be **ratified explicitly rather than inherited
from a draft.**

**Directive T — CORRECTED.** Revision 3 recorded that no text for a directive T
had reached the integrator and that if one existed it was unaddressed. **That was
false about the world, though honest about revision 3's own context** — the
briefing chain referred to directives "in my previous messages" and never pasted
the block.

**Directive T exists**, headed `T. REVIEW REQUIREMENT`, and it is a **process
gate rather than a design directive**: push the revision, verify `origin/main`,
run an independent architecture review, **write no implementation source until
blocking findings = 0 and WAVE 0 APPROVED TO IMPLEMENT = YES**, and return the
SHA, the verdict, the blocking findings, the approval flag and the Y-1…Y-10 map.

**T is SATISFIED, not unaddressed.** Revision 3 was pushed and `d268f70` **is**
`origin/main`, verified; a third independent review was run and returned
**4 blocking, 7 non-blocking, WAVE 0 APPROVED: NO**; §18.5 already independently
encodes the no-code-before-zero-blockers rule; and §17 carries the map. **A
document that is the specification must not record a false fact about the
directive that governs its own approval**, which is why this paragraph replaces
revision 3's rather than being appended to it.

### 18.5 The gate on implementation

**No `src/**` or `tests/**` change may be written for Gate 7 until this revision
receives a FOURTH independent architecture review returning ZERO blocking
findings **and `WAVE 0 APPROVED TO IMPLEMENT: YES`.** The reviewer must not be
the author, must not be a prior reviewer, and must not implement the fixes. **This
is directive T.**

**What the fourth review inherits:** three prior reviews (R-1…R-14, M-1…M-10;
S-1…S-7, N-a…N-e, Y-1…Y-10; **B-1…B-4, N-1…N-7**), Lane U's capability probe,
Lane X's adjacent-mechanism probe, **Lane Z5's PREPARE probe** (§5.5.5 is OPEN
until it lands), three revision-3 drafting lanes, and this document.

**The third review's own summary of what it found, carried so the fourth does not
have to re-derive it:** *"a claim whose named killer test contradicts the pipeline
it guards; a measurement whose experiment could not have produced a positive
result; and a completeness flag that is true while the content it accounts for was
omitted."* **Assume revision 4 contains at least one more of these and go find
it.** Three reviews have each found at least one, and B-2 was one the document had
documented the failure mode of, one page earlier, about somebody else.

**What it should attack hardest — the decisions most likely to be wrong:**

1. **ANSWERED YES BY THE THIRD REVIEW, AND STILL LIVE FOR A FOURTH.** Revision 3
   asked whether a structural argument plus **two** armed surfaces was enough. It
   was not: **S-γ existed and `worktree add` fires on it.** Three are armed now,
   the permitted set is clean on all three, and the safety argument remains
   structural (object-store reads and ref *resolution* touch neither the working
   tree, the index, nor any ref *mutation*). **The honest question for the fourth
   review is the same question one surface later: is three enough, and what would
   a systematic enumeration of git's program-invocation points cost?**
2. **The `ToolExecution` mechanism removes the parameter but keeps ~12 explicit
   `enter()` calls.** The failure *direction* is safe by construction. Is the
   failure *probability* better than the class marker it replaces, or has the
   hazard merely moved?
3. **The ignore-blind snapshot model makes `content_hash_all` on the task
   worktree mandatory and non-configurable.** That is what catches a modification
   to an existing ignored file. Is the budget (§5.5.3) the right shape, and is a
   PREPARE refusal on a large repository acceptable?
4. **Z-2 (option A) makes the old side the pre-worker filesystem bytes.** If the
   checkout transform was itself hostile, the *starting state* is attacker-chosen.
   §5.8 is the only thing standing there. Is that gate sufficient, or should
   `dispatcher_raw` be the default despite being untested from the worker's side?
5. **Reconciliation-time termination** (§7.8) is the first destructive act the
   dispatcher takes against a process it did not start in this lifetime. Is the
   *"the deadline is the caller's own contract"* argument sound?
6. **Wave 0 is the largest wave and ships alone.** §12.2 argues it is
   self-sufficient; §12.5's `test_wave0_suite_is_green_at_the_wave0_commit`
   **proves the suite passes, not that the wave closed what it claims**. Is the
   registry cross-check enough?
7. **The document is the specification.** Two documentation mutants (P-M9, Z-M33)
   exist because two *document* defects shipped untested coverage. Are two
   enough?

---

## Appendix A — Measured data and its provenance

All measurements read-only, in disposable `mktemp -d` repositories, git
**2.43.0**, Linux 6.8.0-71-generic, CPython 3.12, `SC_CLK_TCK` = 100.
**`/home/dev/full-voice-agent` verified `06bfcd61` with exactly 11 dirty entries
before and after every measurement. No worker, real or fake, was run against it.**

### A.1 The two execution surfaces

```
===== poison = filter.myf.clean ONLY =====      ===== poison = core.fsmonitor ONLY =====
  FIRED   POSCTRL-plain-diff                      FIRED   POSCTRL-plain-diff
  FIRED   diff--name-only-z                       FIRED   diff--name-only-z
  clean   ls-files--others-z                      FIRED   ls-files--others-z
  clean   ls-files--others-exclstd                FIRED   ls-files--others-exclstd
  clean   ls-files-v                              FIRED   ls-files-v
  clean   ls-tree-r-z-long                        clean   ls-tree-r-z-long
  clean   cat-file-blob                           clean   cat-file-blob
  clean   rev-parse                               clean   rev-parse
```

Revision 2's **complete** hardening, with the worker using only the `Write` tool:

```
FIRED   REV2-hardened-diff    -> FIRED:REV2-hardened-diff:clean
FIRED   REV2-hardened-status  -> FIRED:REV2-hardened-status:clean
clean   ls-tree / cat-file-blob / cat-file-batch-oid / rev-parse
FIRED   cat-file-FILTERS      -> smudge
FIRED   cat-file-TEXTCONV     -> smudge
FIRED   worktree-add          -> fsmonitor
```

### A.2 The PREPARE checkout vector

```
no-checkout log:        []                      # git worktree add --no-checkout
checkout log:           [SMUDGE-FIRED POSTCHECKOUT-FIRED ]
hardened checkout log:  [SMUDGE-FIRED ]         # -c core.hooksPath=<empty>
                                                # -c core.fsmonitor=false
$ od -c < wt5/thing.dat
0000000   S   M   U   D   G   E   D   :   p   a   y   l   o   a   d  \r  \n
```

> **METHODOLOGICAL CORRECTION — this experiment armed three sentinels and drew a
> four-sentinel conclusion.** It armed **smudge**, **`post-checkout`** and
> **`core.fsmonitor`**. It did **not** arm `reference-transaction`. So
> `no-checkout log: []` established only *"no smudge, no post-checkout, no
> fsmonitor"* — and was reported, and relied upon, as *"executes nothing"*.
>
> **What it could have detected:** an attribute-selected content transform during
> checkout (S-α); a `post-checkout` hook; an index refresh (S-β).
> **What it could not have detected, and what is actually there:** any hook fired
> by a **ref update** (S-γ) — which `worktree add` performs unconditionally,
> because it creates a branch.
>
> Re-run with `reference-transaction` armed and a positive control first:
>
> ```
> POSITIVE CONTROL   git branch poscontrol              FIRED:reference-transaction
> worktree add --no-checkout -b b1 …                    FIRED:reference-transaction
> worktree add --no-checkout --detach …                 FIRED:reference-transaction
> worktree add --quiet -b b3 …   (the default argv)     FIRED:reference-transaction
>   + -c core.hooksPath=<empty>                         clean
> ls-tree -r -z --long / cat-file / rev-parse           clean
> ```
>
> **The `# executes NOTHING` annotation is deleted from §5.5.5.** The permitted
> repertoire's *conclusion* survives — all three commands are clean on S-γ — but
> this appendix's *method* did not, and the failure mode is the one §10.4 records
> one page earlier about somebody else's probe. **It is recorded here rather than
> silently fixed, because a design whose central discipline is "a negative result
> needs a positive control" must show its own violation of it.**

### A.3 Checkout transform on an ordinary repository

Committed `.gitattributes`: `* text eol=crlf` and `*.dat filter=lfsish`

```
blob bytes eol.txt      : l i n e 1 \n l i n e 2 \n
worktree bytes eol.txt  : l i n e 1 \r \n l i n e 2 \r \n
blob bytes thing.dat    : p a y l o a d \n
worktree bytes thing.dat: S M U D G E D : p a y l o a d \r \n
```

### A.4 `ls-tree -r -z --long` path encoding, and the dispatcher-side blob oid

Under `-z`, `café.txt` is raw `caf 303 251 . t x t \0`; `-c core.quotePath=false`
produced **byte-identical** output. Without `-z`: `"caf\303\251.txt"`.

```
git ls-tree -r HEAD                     python sha1(b"blob %d\0" % len(b) + b)
100644 e69de29b…  e.txt   (empty)       e.txt e69de29b…
100644 94954abd…  f.txt                 f.txt 94954abd…
120000 7f66e4fb…  l.txt   (symlink)     l.txt 7f66e4fb…   (over os.readlink bytes)
100644 2e3ff592…  n.txt   (no \n)       n.txt 2e3ff592…
```

**Four for four, exact.**

### A.5 Costs

```
/home/dev/sol-claude-dispatcher: files=6271 dirs=946 links=4 bytes=133.9MB
  lstat-walk 79 ms · read+hash cold 3.14 s / warm 0.59 s · stat-only 46 ms
blake2b 301 MB/s · sha256 200 MB/s · blake2s 217 MB/s · md5 487 MB/s

/home/dev/full-voice-agent (read-only, stat only):
  entries=46565 · regular_bytes=789.9MB · stat_walk 469/466 ms
  tracked=584 · tracked_bytes=22.6MB
  HEAD=06bfcd61… dirty=11    HEAD_after=06bfcd61… dirty_after=11

git ls-tree -r -z --long HEAD (143 entries): 10 ms
```

### A.6 Ignore-suppressed sets, and the symlink counts that decide Y-10

| | suppressed | ignored symlinks |
|---|---|---|
| `sol-claude-dispatcher` | **0 → 3,842** (`.venv` = 71 MB) | **4** |
| `/home/dev/full-voice-agent` | **9 → 927** | **1** |

### A.7 Process and lock facts

| Hypothesis | Result |
|---|---|
| kernel `E2BIG` from `create_subprocess_exec` | `OSError` **errno 7**, raised before any handle exists |
| missing binary | `FileNotFoundError` **errno 2** |
| residual child after either failure | **none** — the transient fork never execs and is reaped |
| `start_new_session=True` ⇒ `os.getpgid(pid) == pid` | **true** |
| `/proc/<pid>/stat` field 22 via `rindex(")")` | robust against a `comm` containing spaces/parens |
| `/proc/<pid>` after exit | **absent** |
| `flock(LOCK_EX\|LOCK_NB)` while a holder lives | **EAGAIN** |
| same, after the holder is `SIGKILL`ed | **acquired** — the kernel releases on death |
| `flock` fd **inherited** by a child | **lock survives the holder's death** — a false "owner alive" |
| Python `os.open` default | `get_inheritable()` is **False** (PEP 446) |
| `os.rename` raced by two processes | exactly **one winner**; loser gets **ENOENT** |

### A.8 The five existing tasks, read without modification

All five are populated, all five carry `dispatcher-result.json`, **none has a
`reservation.json` or an `ownership.json`, and none is in `RUNNING`.**
`find state -name reservation.json -o -name ownership.json` → **empty**.
`state/locks/*.claims/` **does not exist**.

### A.9 Repository and configuration facts

`config/dispatcher.toml` is **gitignored (`.gitignore:26`)**;
`config/dispatcher.example.toml` **is tracked**. `scripts/mutation/` **does not
exist**. `check-production-activation.py` **requires** `--expect` and refuses to
infer. `state/tasks/*` is gitignored. The MCP SDK's `Context.report_progress` is
documented as *"a no-op when no token was supplied"*.

### A.10 Codex trust write-back

`codex exec` auto-writes a project trust stanza into `~/.codex/config.toml`;
**`--ignore-user-config` prevents the *load*, not the *write-back*.** Restored
byte-identical, sha256 `e41ef3bd…d498e`, 1286 B.

---

## Appendix B — Requirement traceability

| Brief § | Where |
|---|---|
| §1 G7-1 / G7-5 | §4 |
| §1 G7-2 | §5.1, §5.3A, §5.4–§5.7 |
| §1 G7-3 | §6.1, §6.4–§6.6 |
| §1 G7-4 | §6.7 |
| §1 G7-6 | §3.1, §4.6, §4.12 |
| §1 G7-7 | §5.2, §5.10 |
| §1 G7-8 | §7 |
| §2 must-not-regress | §3.4, §10.1, §13 |
| §3 architecture first | this document |
| §4 / §5 lifecycle profiles, hash-pinned projections | §4.3, §4.4 |
| §6 / §25 lifecycle preflight matrix (INTERNAL) | §4.5 |
| §7 preflight must not mutate | §3.1 |
| §8 / §9 complete untracked evidence, patch requirements | §5.5.8, §5.5.9 |
| §10 one canonical patch | §5.5.8 (ZI-2) |
| §11 diff check for untracked | §5.5.8 — dispatcher-native, `git diff --check` **not consulted** |
| §12 / §13 run reservation and atomicity | §5.10, §15 |
| §14 timeout output / CLI capability | §6.0, §6.5 — **MEASURED SUPPORTED** |
| §15 soft deadline | §6.0, §6.3 — **MEASURED NOT AVAILABLE**; kept as a measurement |
| §16 factual remediation | §6.4 |
| §17 trusted validation after timeout | §6.6 |
| §18 / §19 event-driven progress and its content | §6.7 |
| §20 durable run ownership | §7.9 |
| §21 restart recovery policy | §7.5, §7.7 |
| §22 preferred durable shape | §7.4 — declined, **conditional on §7.8**; §7.5 states exit status is unrecoverable |
| §23 explicit orphan state | §7.7.6, §7.8 |
| §24 repository lock after restart | §7.7 |
| §26 size targets | §9 |
| §27 Fable evidence completeness | §5.11 |
| §28 failure ordering | §8 |
| §29 test doubles | §10 |
| §30 required adversarial cases | §5.14, §6.11, §7.12, §10.1 |
| §31 mutation suite in source control | §11 |
| §32 implementation waves | §12 |
| §33 server.py conflict control | §12.4 |
| §34 production freeze | header, §10.5, Appendix A |
| §35 final gate report rows | §16 |

---

## Appendix C — Revision 4 change log

| Section | Change | Driver |
|---|---|---|
| header | revision 4; the four blockers and their fixes; **fourth review required** | third review |
| §0.2 | *"exactly ONE git command"* → **`{cat-file, rev-parse}`**, with the three tempting exits named and refused | **B-1** |
| §2, §16, §17 Y-1 | the same correction, everywhere the claim appeared | B-1 |
| §5.4.5 | the journal assertion is written against the **true** set, with the `rev-parse` argv **pinned** and its count tied to a **seam counter** | B-1 |
| §5.4.6 | the journal test renamed and re-specified; `test_repertoire_is_clean_on_all_three_surfaces` added; the hooks test **names `reference-transaction`** | B-1, B-2 |
| §5.4.7 | **ZM-A7** (a second `rev-parse` variant) and **ZM-A8** (deleting B2's check to make the test pass) added | B-1 |
| §5.5.2 | B2's post-worker `rev-parse` stated **explicitly** as the second permitted post-worker command | B-1 |
| §5.4.1 | **S-γ (ref update)** added as a third execution surface; "measured against BOTH" → **ALL THREE** | **B-2** |
| §5.4.3 | three surfaces; three `REQUIRES-PROBE` rows **retired as clean**; three live-but-unlisted commands **added**; `read-tree` and `config --get` contradictions **resolved** | B-2, N-1, N-2 |
| §5.5.5 | `# executes NOTHING` **deleted**; Z-4 **demoted from "structural" to "gated"**; **OPEN pending Lane Z5** | B-2 |
| Appendix A.2 | **methodological correction** — what the experiment could and could not have detected, with the re-run and its positive control | B-2 |
| §5.5.9, §5.5.9A, §5.6.5, §5.11.5 | **ZI-25/26/27** — a base-ignored path that is *modified* is represented **in full**, never rolled up, and is **scope-checked**; only bulk **creation** rolls up, and **the rollup clears `patch_file_complete`** | **B-3** |
| §8, §12.1–§12.5, §17 Y-7 | **D-24** — the PREPARE mechanism and §8 row 0 **move into Wave 0** | **B-4** |
| §5.8.2 | *"no `git config`"* narrowed to *"the capture runs no git command"* | N-1 |
| §5.8.2A | **the raw gitdir resolver**, so ZI-18 is achievable | N-5 |
| §5.3 ZI-18 / ZI-20 | restated to something an implementer can satisfy | N-5 |
| §5.8.2/§5.8.3 | transport and promisor keys **printed to the operator**; promisor vector recorded as closed | N-3 |
| §11.6 | both documentation mutants **re-specified structurally** — they were red on day one | N-4 |
| §0.1, §18.4 | **directive T exists and is SATISFIED**; revision 3's statement was false about the world | N-6 |
| §10.3 | four new rows: revision 3's own proofs that could not fail | B-1, B-2, N-4 |
| §18.3A | **T-1 … T-7**, the decisions arising from the third review | — |

---

## Appendix D — Revision 3 change log (retained)

| Section | Change | Driver |
|---|---|---|
| §0 | **Z-RULE-1** and the PROVEN-BY discipline become standing rules | S-1, R-3, R-7, R-9 |
| §0.2 | the four inter-lane reconciliations, recorded rather than applied silently | Z1/Z2/Z3 |
| §0.3 | seven new defects the drafting lanes found | Z1, Z2, Z3 |
| §1 | **Shape 4** added: the measuring instrument is controlled by the thing being measured | directives A–F |
| §3.1 | `_record_failure` loses **both** its parameters; `ToolExecution` + monotone phase; `run_worker` deleted; **no fake worker run**; a spawn failure leaves the lifecycle **unchanged** | directive G, S-2, Z2-G-F1/F2 |
| §4.11 | **A-d deleted in the implementer's table** with its equivalence proof; A-d′ inserted; matrix demoted to an additional killer | Y-6, directive Q |
| §4.12 | the **registered production entrypoint refuses to start** inert; seven-conjunct proof chain; live negative control | directive N, N-a, Y-8 |
| §5.3A | identity → policy → classification, with a **required constructor argument** | directive M, Y-3 |
| §5.4 | the whole **class** of presentation commands is deleted; three-command repertoire measured on **both** surfaces; `git.py` splits; the invocation journal | directive A, S-1, Y-1 |
| §5.5 | base tree via `ls-tree` + dispatcher-side blob oid; **ignore-blind `FsSnapshot`**; base reconciliation (Z-2 option A); two deltas; the orthogonal inventory tuple | directives B, K |
| §5.6 | **no ignore query at all**; `unchanged_count` is a scalar; Y-9 becomes **moot** | directive C, S-3, Y-3, Y-9 |
| §5.7 | bytes end-to-end; **`PathIdentityUnrepresentable` moves to row 5a** | directive D, Z1-N2 |
| §5.8 | raw administrative preflight as **step 0**; the fingerprint; **layer 4 deleted** | directive E, Z1-N1 |
| §5.9 | the primary tree measured **without git**; tri-state `primary_worktree_clean` | directive F |
| §5.11 | two completeness flags; **every "clips as before" deleted**; measured argv budget | directive O, R-8, Y-6 |
| §7.3 | file-backed streams with **no redaction claim**; one accessor; decidable AST test | R-7 |
| §7.6 | **LEGACY** classification; claim-driven reconciliation; the coverage theorem | directive H, S-4, Y-4 |
| §7.7 | dispatcher identity + kernel liveness lock; owner classified **first**; `TerminationAuthority` | directive I, S-5, Y-5 |
| §7.8 | the deadline ruling preserved, **every row inside `OWNER_GONE`** | directive J |
| §8 | row 1 changed, row 5a added, row 4's source changed | directive G, Z1-N2, §5.6.6 |
| §9.2A | the matrix is parameterised by the guidance **cap** | R-9 |
| §11 | the invariant **registry**; production-active runner; `--fast`/`--full`; **documentation mutants** | directive Q, Y-6 |
| §12 | **Wave 0 self-sufficient and the largest**; D before C; `git.py` split deleted | directives L, R, S-7, Y-7 |
| §15 | **ONE canonical table, fifteen rows**, with P-M9 as its docs mutant | directive P, Y-6 |
| §17 | the Y-1…Y-10 mapping, with Y-9 and Y-10 named as unratified | Sol's requirement |
| §18 | everything no lane may decide | Z1-G, Z2-Q, Z3-AMB |
