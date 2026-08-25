# GATE 7 — ARCHITECTURE

**Lifecycle, evidence and recovery integrity.**

Status: **DESIGN — REVISION 6. NOT APPROVED FOR IMPLEMENTATION.**

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

Revision 4 (`165aa93`) left **one** question OPEN by construction: §5.5.5 and
DECISION Z-4, held pending Lane Z5's PREPARE probe. **Z5 is published
(`2569f31`), and it answers both halves negatively while discovering a FOURTH
execution surface.** Revision 5 integrates it.

> ### The honest framing this document now owes its fourth reviewer
>
> **Three revisions ago the claim was that the PREPARE execution vector is
> "closed structurally."** It is now: **closed by an ENUMERATED, argv- and
> env-pinned defence on FOUR MEASURED SURFACES, with no proof that four is
> all of them.**
>
> The surface count has been wrong **twice** — revision 3 said two, revision 4
> said three, Z5 measured four — and each correction came from a probe, never
> from reasoning. Nothing in this document should be read as asserting that the
> enumeration is complete.

> **NO SOURCE CODE MAY BE WRITTEN until a FIFTH independent review returns ZERO
> blocking findings and WAVE 0 APPROVED TO IMPLEMENT: YES.** That is directive T,
> its mandate is **§19**, and it is not discretionary. The production freeze
> remains absolute until then.

Revision 5 (`d197bf08`, pushed and verified as `origin/main`) received a
**fourth** independent review: **F-1 … F-7**. Sol accepted it and issued
**twenty-one directives, §1 … §21**, which do not patch revision 5 — they
**replace its central claim**. Revision 6 integrates them, together with four
lanes: **Z7** (the sealing/parsing/elimination/promisor probe, `e0b1670`),
**Z8** (sealing), **Z9** (attribution), **Z10** (policy).

> # THE CENTRAL INVARIANT
>
> ## After successful Claude process creation, the count of git commands the dispatcher executes in order to decide anything is **ZERO**.
>
> Not *"`cat-file` only"*. Not *"two"*. **Zero.**
> **Everything git-derived that must be trusted is sealed before Claude exists.**

**Why the count was never the point.** Five revisions defended a *permitted set*.
Every defence in §5.4.3A — `GIT_NO_LAZY_FETCH`, `-c core.hooksPath`,
`-c core.fsmonitor=false`, `--no-pager`, the redirect-var stripping — answers one
question: *is a program running?* **None of them constrains what a read resolves
against.** The fourth review's **F-5** and Lane Z7 then demonstrated the
consequence: a worker writing **one plain file** — no git command at all — makes
`rev-parse --verify HEAD^{commit}` return **the expected SHA at `rc=0`** while
`ls-tree` and `cat-file` serve the attacker's tree and blobs, with all four
identity commands reporting legitimate values. **A four-surface-clean, pinned,
argv-verified repertoire of size two is defeated without adding a third command.**

**So revision 6 stops defending the set and empties it.** §1 is not another
member of the enumeration family and does not compete with it:

> **A command that is never executed cannot be redirected, cannot be filtered,
> cannot be textconv'd, cannot fire a hook, cannot lazily fetch, cannot resolve
> through a substituted store, and cannot consult a configuration file.**

That closes, in one clause and without enumeration: `filter.*`, `diff.*.textconv`,
`diff.*.command`, `diff.external`, `core.fsmonitor`, the entire 28-hook
namespace, `core.attributesFile` and in-tree `.gitattributes`, `alternates` and
`http-alternates`, `refs/replace/**`, `info/grafts`, `extensions.partialClone`
and promisors, the index in every form, every key in `$GIT_COMMON_DIR/config` and
every `include.path` it reaches — **and every future git redirection nobody has
named.** The last clause is the only clause in this document that is not bounded
by what someone thought to arm.

**What it is NOT, stated first rather than last.** This is **not an OS sandbox**.
The worker runs as the same uid as the dispatcher and can read, write and delete
every dispatcher artefact including the seal. **No dispatcher-side artefact is
tamper-proof under this threat model** (§5.8.4). What §1 changes is the *shape of
the dispatcher's dependence*: under revision 5 the worker attacked a **live
resolution** and the dispatcher walked into it; under §1 the worker can only
attack a **frozen artefact**, and a frozen artefact that is deleted, truncated or
hash-mismatched is detectable against its own manifest and lands `FAILED` or
`POLICY_VIOLATION`, **never a plausible wrong answer**. The residual is named in
§2A.6: a worker that modifies the seal **and** its manifest coherently produces a
consistent lie. **Sealing converts a silent substitution into a forgery that must
be self-consistent. It does not make it impossible.**

### What revision 6 changes

| # | Sol's directive | What this revision does |
|---|---|---|
| **§1** | zero authoritative git after spawn | **§2A** — the central invariant, its proof obligations, and the honest statement of what it is not |
| **§2** | seal before launch | **§5.5.2/§5.5.2A** — `BaseTreeSnapshot` carries **exact content bytes** in a dispatcher-owned CAS keyed by git-blob-sha1, plus a `seal-manifest.json` written **last**; the lazy FINALIZE `cat-file` is **deleted** |
| **§3** | promisor / partial clone | **§5.5.2B** — every base object is materialised and oid-verified **before launch**, under **PIN 1**; `rev-list --objects --missing=print` is the only verifier that reports absence instead of dying of it (Z7 §5.3) |
| **§4** | S-ε store redirection | **§5.4.1A / §5.8.2** — the closure is that the store is **never consulted after launch**; capture-and-report is evidence, not the defence. **Alternates is an availability primitive, not a forgery primitive** (Z7): the authority-bearing file is `worktrees/<id>/HEAD` |
| **§5** | B2 raw | **§5.5.2C** — the whole **HEAD resolution chain** is sealed and re-verified by raw file reads. **Sol's literal form is falsified and corrected** (Z8 M6): `<gitdir>/HEAD` is `ref: refs/heads/sol-<id>`, never 40-hex, and is byte-identical after a worker commit |
| **§6** | production `base_ref` is an exact SHA | **§4.14** — `^[0-9a-f]{40}$` at the production entrypoint, with a **byte-equality post-condition** (an annotated tag peels to a *different* commit); the default `"HEAD"` is deleted; the measured drift is **154** commits, not 139 |
| **§7** | remove `rev-parse --show-toplevel` | **§5.8.2B** — authorization is `realpath` equality; the command is **deleted from `src/**`**, not measured. It is a **precondition** for §19's ordering, because `lock_identity_for` calls it |
| **§8** | worker attribution | **§5.5.6** — **three** raw filesystem states (START · WORKER_EXIT · POST_VALIDATION), identity-wise deltas, and the closure theorem `final_delta ⊆ worker_delta ∪ validation_delta` |
| **§9** | validation output is not worker output | **§5.5.9/§5.11** — the third column is **deleted**; `BULK_CREATED_IGNORED` goes with it; volume routes to `review_input_complete` |
| **§10** | validation is an execution domain | **§5.17** — it **may** run `git`; the invariant is **authority, not containment**; two journals, two post-worker admin captures, and an **evidence freeze** |
| **§11** | one completeness definition, one producer | **§5.5.8/§5.5.9** — `patch_file_complete` becomes a **read-only property**, an IFF over `worker_delta`; **symlinks are SUPPORTED** |
| **§12** | Fable | **§5.11** — six labelled sections, refusal on either flag, `both_authors` mandatory sentence |
| **§13** | F-3 `BaseBlobUnreadable` | **§5.12** — it exists **only in PREPARE**; every FINALIZE precedence row is deleted, so the laundering route does not exist |
| **§14** | raw git administration, no exemptions | **§5.8** — §5.8.3's *"NOT protected, deliberately"* allowlist is **DELETED in its entirety** |
| **§15** | primary tree | **§5.9** — raw equality, **no `git status` in any form**, symmetric fidelity, and a machine-checked write prohibition |
| **§16** | the pre-worker git surface | **§5.4.3** — ten enumerated PREPARE rows, three deletions, three pins |
| **§17** | post-worker repertoire = `{}` | **§5.4.5** — literally empty, by two named mechanisms, with the **one surviving post-worker spawn** named in the same breath |
| **§18** | retire the stale promisor experiment | **§5.8.3** — recorded as an **INVALID EXPERIMENT**, not as a measurement with a different conclusion |
| **§19** | the pre-worker command order | **§5.4.3B** — declared as **data**, enforced by a runtime interlock, corroborated by the journal; **A.2B is generated from it** |
| **§20** | Wave 0 independence | **§12.2A** — `owns ≡ creates`, split from `lands_in` and `modifies`; `creates(baseline, 5)` |
| **§21** | the fifth-review mandate | **§19** — sixteen attack vectors and the twelve-item return format, **verbatim** |

### What revision 5 changed

| # | Z5 finding | What this revision does |
|---|---|---|
| **1** | **The ordering fix does not work.** A worker-set `core.hooksPath` — directly, or reached through `include.path` — **survives the dispatcher deleting `$GIT_COMMON_DIR/hooks` outright**, and there is **no per-worktree hooks namespace** to isolate into | §5.5.5(a): filesystem quarantine is **not** a defence. Only **PIN 2** (`-c core.hooksPath=<empty dir>` on the argv) is. Written plainly, not softened. |
| **2** | **S-δ — a FOURTH execution surface.** `cat-file --batch` (rc=0, **silent**) and `ls-tree -r -z --long` (rc=0, **silent**) run the worker's `core.sshCommand` / `core.gitProxy` / `ext::` program via **promisor lazy fetch**. These are *the design's own permitted post-worker commands* | §5.4.1 gains **S-δ**; §5.4.3's repertoire is re-measured on **four** columns; **`--long` is REMOVED** from `BaseTreeSnapshot`'s argv (it is what arms it); **PIN 1** `GIT_NO_LAZY_FETCH=1` closes the column and enters §5.4.3A's global env policy; Lane X's TIER-0 table is **corrected** — `core.sshCommand` and `core.gitProxy` are **executed**, not inert |
| **3** | **DECISION Z-4 is retired, not rescued.** A fire-nothing raw materialisation exists but is **unusable** (no index ⇒ every file reports `D` *and* `??`; a real edit produced no diff), and **every** measured way to give it an index fires `post-index-change` — including an external `GIT_INDEX_FILE` | §5.5.5(c): *fire-nothing only when unusable, usable only when it fires.* The "structural rather than gated" claim is **withdrawn**. The untested raw-DIRC path is escalated as **T-8**, claiming nothing. |
| **4** | **`git.py:776` bypasses the chokepoint** — `write_full_diff` calls `subprocess.run(["git","diff",…])` directly, outside `_run_git`. A live ZM-A5 in the current tree | §5.4.5 records that the journal is **blind** to it; §5.4.6 specifies **`test_no_direct_git_subprocess_in_src`** (AST, whole tree) and states that it **fails against `HEAD`**, with this call site as the **day-one killer** |
| **5** | **The patch format is real.** All §9 edge cases pass `git apply --check` **and apply byte-exactly** | §5.5.8: the `REQUIRES-PROBE` is **retired** and **three** measured format constraints become load-bearing renderer rules |
| **6** | Z5's **NOT TESTED / NOT OBSERVED** discipline | Mirrored: `GIT_CONFIG_KEY0` precedence, the raw-DIRC index, and the per-worktree hooks path are each labelled with what was and was not attempted |

### What revision 4 changed

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
| Revision 3 | `d268f70` — **pushed, `origin/main` verified**; reviewed a third time |
| Revision 4 | `165aa93` — closed B-1…B-4 and N-1…N-7 |
| Revision 5 | `d197bf08` — **pushed, `origin/main` verified**; reviewed a fourth time; **the artefact this revision replaces** |
| Author | Lane V (integrator). **This lane wrote no `src/**`, no `tests/**`.** |
| Drafting lanes | **Z1** (evidence authority, §A–F) · **Z2** (phase & ownership, §G–J, §P) · **Z3** (structure & policy, §K–S, Y-mapping) |
| Probes | `GATE7-CAPABILITY-PROBE.md` (U) · `GATE7-V1-ADJACENT-PROBE.md` (X) · `GATE7-Z5-PREPARE-PROBE.md` (Z5, `2569f31`) · **`GATE7-Z7-SEALING-PROBE.md` (Z7, `e0b1670`)** |
| Reviews | `GATE7-DESIGN-REVIEW.md` (W) · `-2.md` (Y) · `-3.md` (Z4) · **`-4.md` (Z6) — F-1 … F-7** |
| Drafting lanes (rev 6) | **Z8** sealing (§1–§5, §13, §14, §16–§18) · **Z9** attribution (§8–§12) · **Z10** policy (§6, §7, §15, §19–§21, Y-map) |
| Pending probe | **none.** Z5 and Z7 are published and cited. **Where Z7 and a draft disagree, Z7's measurement governs and the disagreement is recorded, not smoothed.** |
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

> ### Z-RULE-1B — INTEGRITY CONTROLS (new in revision 6)
>
> **Where the attack substitutes *what a read resolves against* rather than
> *running a program*, there is no sentinel to fire, and Z-RULE-1's usual form
> does not apply.** The positive control is instead:
>
> **(b) run the UN-HARDENED invocation and assert it returns the DECOY's
> answer** — proving the decoy is genuinely consulted — (c) clear, (d) run the
> production path and assert it returns the real answer or refuses.
>
> **A test that only asserts "the real answer came back" passes against a build
> where the decoy was never wired up.** That is B-2's failure mode in a new form.
> Six of §19's sixteen attack vectors execute nothing, so six of them can only be
> controlled this way.

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
must rule on. Appendix A is measured data; Appendix C is the change log.

**`REQUIRES-PROBE`** marks a statement that is reasoned but **not measured**. It
must not be read as a measurement, and Wave acceptance may not depend on one
without discharging it first.

### The eight labels this document uses, and what each one licenses

| Label | Means | Licenses |
|---|---|---|
| **MEASURED** | an experiment was run in this gate, with a control where a control is meaningful, and the lane names itself | a claim of fact, bounded by what that experiment could detect |
| **MEASURED (inherited)** | measured by a named earlier probe or review, cited by section, **not re-derived** | the same, with the citation carrying the provenance |
| **REASONED** | an argument, with the step that could be wrong named | nothing about the world; it is a hypothesis with a falsifier attached |
| **UNMEASURED** | a gap, with the lane that must close it named | nothing |
| **`REQUIRES-PROBE`** | reasoned but not measured, and Wave acceptance may not depend on it | nothing until discharged |
| **`NOT TESTED`** | **no experiment was run.** Claims nothing in either direction | nothing |
| **`NOT OBSERVED`** | an experiment ran, **a positive control fired**, and the effect did not appear | evidence, bounded by that experiment's detection power |
| **`VOID`** | an experiment ran and **could not have produced a positive result** | nothing. **A VOID row is not a negative result and must never be recorded as `clean`** |

**`VOID` is new in revision 6 and it exists because it happened three times.**
Review 3's N-3 promisor result, review 4's own first attempt at reproducing it,
and **Lane Z7's own first run** all used a `file://` clone whose `--filter` git
silently ignored, so every object was present and no fetch could occur. Z7
reported its own row **VOID** and re-armed with `uploadpack.allowFilter` plus a
`missing > 0` precondition assertion. **That a probe caught its own invalid
experiment is the standard every claim carried forward is held to here.**

**`NOT TESTED` / `NOT OBSERVED`** are Lane Z5's discipline, adopted here.
`NOT TESTED` means *no experiment was run* — the statement claims nothing in
either direction. `NOT OBSERVED` means *an experiment ran, a positive control
fired, and the effect did not appear* — which is evidence, bounded by what that
experiment could have detected. Revision 4's Appendix A.2 correction exists
because a `NOT OBSERVED` was recorded where the control had never been armed;
that distinction is now marked wherever it applies.

---

## 0.1 Sol's twenty-one revision-6 directives, and where each lands

The twenty directives A–T of revision 3 are retained below as history. **Sol's
revision-6 directives are numbered §1 … §21 and are a different, superseding
set.** Where a revision-6 directive contradicts an A–T directive, the revision-6
directive governs and §18 records the supersession.

| Sol's § | Directive | Lands in |
|---|---|---|
| **§1** | zero authoritative git after spawn | **§2A** (new), §5.4.5, §5.4.6, §16 |
| **§2** | seal before launch — identity **and content** | §5.5.1, §5.5.2, **§5.5.2A** (new), §5.5.4 |
| **§3** | promisor / partial clone materialised pre-launch | **§5.5.2B** (new), §5.8.3 |
| **§4** | S-ε store redirection | **§5.4.1A** (new), §5.8.2 |
| **§5** | B2 by raw HEAD-chain reads | **§5.5.2C** (new), §5.4.5, §8 row 2 |
| **§6** | production `base_ref` is an exact SHA | **§4.14** (new), §12.2A |
| **§7** | remove `rev-parse --show-toplevel` | **§5.8.2B** (new), §5.4.3, §5.4.3B |
| **§8** | worker attribution — three raw states | §5.5.6, **§5.5.6A** (new), §8 |
| **§9** | validation output is not worker output | §5.5.9, §5.5.9A, §5.11 |
| **§10** | validation is an explicit execution domain | **§5.17** (new), §6.6 |
| **§11** | one completeness definition, one producer | §5.5.8, §5.5.9, §5.11.5 |
| **§12** | Fable consumes `worker_delta` only | §5.11 |
| **§13** | `BaseBlobUnreadable` exists only in PREPARE | §5.12, §8 row 3 |
| **§14** | raw git administration, **no deliberate exemption** | §5.8.2, §5.8.3 |
| **§15** | primary tree, raw, equality not cleanliness | §5.9 |
| **§16** | the pre-worker git surface, enumerated | §5.4.3 |
| **§17** | post-worker repertoire = `{}` | §5.4.5, §5.4.6 |
| **§18** | retire the stale promisor experiment | §5.8.3, §10.3 |
| **§19** | the pre-worker command order | **§5.4.3B** (new) |
| **§20** | Wave 0 independence, `owns` defined | **§12.2A** (new) |
| **§21** | the fifth-review mandate | **§19** (new) |

## 0.1A Sol's twenty directives of revision 3 (retained)

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

**RESOLVED: adopt Z1's permitted set** *(and revision 5 removes `--long` from it —
§5.4.1)*. Only `ls-tree -r -z`, `cat-file`
(bare) and `rev-parse` are measured clean on **both** surfaces. `ls-files` in
every form is prohibited. **Z3's dispatcher-side git-blob-sha1 is kept** — Z1
verified it independently, byte-exact on a normal file, an **empty** file, a file
with **no trailing newline** and a **symlink** — which lets `cat-file` come off
the PREPARE hot path entirely and be invoked lazily, for changed paths only.

> **Consequence AS STATED IN REVISION 3, AND SUPERSEDED IN REVISION 6:** *"after
> the worker is launched, the dispatcher runs exactly TWO git commands —
> `cat-file` … and `rev-parse --verify HEAD^{commit}` … NO PRESENTATION COMMAND
> RUNS."*
>
> **The claim was corrected twice — from ONE to TWO, then re-argued — and was
> wrong both times for the same reason: the count was never the defect. The
> inventory METHOD was.** Measured, sixteen authoritative invocations from ten
> call sites are reachable after the spawn seam, plus one spawn that is not a git
> call site at all. **Revision 6 does not correct the number. It empties the
> set** (§2A), **and the two commands named above are deleted by §5.5.2A and
> §5.5.2C rather than defended.** The reconciliation's *narrowing* — `ls-files`
> in every form is prohibited, and `ls-tree -r -z` / bare `cat-file` /
> `rev-parse` are the only clean readers — **stands, and now applies to the
> PREPARE window only.**

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

> **AND THE THREE REFUSED EXITS ABOVE WERE ALL REFUSED FOR THE RIGHT REASON AND
> ARE ALL NOW MOOT.** Revision 6 takes a fourth route none of them named:
> **replace the command with a mechanism that answers the same question without
> a git process** (§5.5.2C's raw HEAD chain). **B2's invariant is not deleted, not
> weakened, and not moved off the chokepoint — it is computed from sealed bytes,
> and the measured result is that the raw form is strictly better than the
> `rev-parse` form, because under S-ε the `rev-parse` form returns a
> worker-chosen answer at `rc=0` while all three of revision 4's new conditions
> pass.**

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
measures a repository state the design never produces.** *Z5 measured the
converse and it is worse than this note assumed: the `read-tree` that makes the
state real is itself an execution surface —* `post-index-change` *fires on it,
including with an external* `GIT_INDEX_FILE` *(§5.5.5(c)).* This is Z-RULE-1's
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
  PRE-GIT     │ R2 base_ref exactness · R3 realpath AUTHORIZATION ·      │
  (mutates    │ R4 raw layout · R5 lock · R6 §5.8 RAW ADMIN ESTABLISHMENT │
   nothing)   │ R7 PRIMARY_START — all plain file I/O                     │
              │        NO GIT PROCESS HAS BEEN CREATED YET                │
              └───────────────────────┬───────────────────────────────────┘
                                      │ establishment marker written
  PREPARE     ┌───────────────────────▼───────────────────────────────────┐
              │ G1…G10  the TEN enumerated git commands (§5.4.3)          │
              │ then    SEAL: base identity + EXACT CONTENT BYTES + the   │
              │         HEAD chain + the manifest, written LAST (§5.5.2A) │
              └───────────────────────┬───────────────────────────────────┘
                                      │ the seal exists
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
              │     THREE dispatcher-owned filesystem snapshots →         │
              │     worker_delta → SCOPE → content FROM THE SEAL →        │
              │     one representation → FREEZE → validation → attribute  │
              │     POST-WORKER AUTHORITATIVE GIT: {}  (§2A)              │
              │     post-worker SPAWNS: exactly one, run_validation_command│
              └───────────────────────┬───────────────────────────────────┘
  LAND        ┌───────────────────────▼───────────────────────────────────┐
              │ LandingIntent — recorded, then applied idempotently       │
              └───────────────────────────────────────────────────────────┘
```

Seams, stated so a reviewer can attack them:

- **R6 → every git process.** The administrative establishment runs with **plain
  file I/O** and **nothing in PREPARE may run a git command until it passes** —
  enforced by a **runtime interlock in `_run_git`**, not by ordering alone
  (§5.4.3B). `git worktree add` itself executes repository-configured programs.
  **This ordering is only possible because §5.8.2B removed the git command from
  authorization and from the lock digest** — while `lock_identity_for` calls
  `git_top_level_or_none`, no ordering can put the lock before the first git
  process.
- **SEAL → the worker.** Nothing may launch a worker until the seal's manifest
  exists. **Everything git-derived that must be trusted is on the far side of
  that line, and nothing after it asks git anything** (§2A).
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

## 2A. THE CENTRAL INVARIANT (Sol §1)

### 2A.1 Current failure

Revision 5's central claim is a **count**: *"after the worker launches the
dispatcher runs exactly two git commands."* The fourth review's verdict is that
**the count was never the defect — the inventory method was**, and it
demonstrated that twice in one review:

- **F-4.** `validation.py:228` is `await asyncio.create_subprocess_exec(*argv)`
  where `argv[0]` is an **envelope field**. `models.py:355-366` rejects exactly
  `{sh, bash, zsh, dash, ksh, fish}` and a NUL byte. **`["git","diff","--exit-code"]`
  is a legal, ordinary declared validation**, it runs post-worker between the two
  evidence collections, none of §5.4.3A's pins apply to it, and
  `test_no_direct_git_subprocess_in_src`'s predicate — *"the first argv element
  is the literal `"git"`"* — **is green while the path is live**. An inventory
  built by scanning `src/**` for a literal string cannot enumerate a path whose
  argv comes from data.
- **F-5 / S-ε.** A worker writing plain files defeats **both** permitted
  commands **without adding a third**.

Lane Z7 then made the count itself measurable and it is **not two**:

> **16 authoritative git invocations on the success path (18 with the failure
> path), from 10 distinct call sites in `git.py` — `531, 904, 385, 652, 678, 683,
> 699, 704, 722, 776` — all reachable after the spawn seam** (`runner.py:1428`),
> one of which (`776`) bypasses the `_run_git` chokepoint, **plus
> `validation.py:228`, which is not a git call site at all and therefore appears
> in no inventory.** *(Z7 §4.1, static, with `file:line` for every row.)*

### 2A.2 The new invariant

> ### INVARIANT ZI-51 — ZERO AUTHORITATIVE GIT AFTER SPAWN
>
> From the instant `create_subprocess_exec` returns a handle for the Claude
> worker, until the run's evidence, verdict and review are final, **the count of
> git commands the dispatcher executes in order to decide anything is ZERO.**
>
> No git command executed after worker launch may serve, in whole or in part:
> repository identity · the B2 base check · base resolution · the changed-path
> inventory · the scope verdict · content evidence · diff generation · diff stat
> · diff check · Fable evidence · the primary-tree invariant · completeness
> determination · attribution.
>
> **Everything git-derived that must be trusted is sealed before Claude exists.**

**`{}` is literal, not definitional.** No command was reclassified as
"non-authoritative" to get it out of the set. **Two commands were deleted, each
by a named mechanism a fifth reviewer can check:**

| Revision 5's post-worker command | What it served | What replaces it | Result |
|---|---|---|---|
| `rev-parse --verify HEAD^{commit}`, `cwd=task_worktree` (`git.py:531` ← `server.py:2005`) | **B2** | **§5.5.2C.** The `.git` indirection, `commondir`, the gitdir back-pointer and the **whole HEAD resolution chain** become protected immutable dispatcher authority, sealed as raw bytes before launch and verified after the worker by **raw filesystem reads only**. `resolve_head_raw` computes the same 40-hex answer with no git process | command eliminated; **the invariant is strictly stronger** — MEASURED: the `rev-parse` form returns a worker-chosen answer under S-ε, the raw form does not, because it reads the sealed chain rather than resolving through a substituted store |
| `cat-file --batch`, lazily at FINALIZE, for the old side | the **old side** of every changed path | **§5.5.2A.** `BaseTreeSnapshot` holds each base path's **exact content bytes** in a dispatcher-owned CAS, sealed before launch. `old_side(p)` has two branches and **both are CAS reads** | command eliminated; **there is no post-worker object read to serve** |

> **If either mechanism is removed, the command comes back and the set is not
> empty.** That is what makes this checkable rather than asserted, and it is why
> §17 must never be integrated as a bare *"the post-worker repertoire is empty"*
> line: the claim is checkable only with its mechanism table attached.

### 2A.3 The one post-worker spawn that survives, named in the same breath

> **The post-worker AUTHORITY repertoire is empty. The post-worker SPAWN set has
> exactly one member: `run_validation_command` (`validation.py:228`).**

It is not eliminated **and it must not be**: it is Sol's §10 execution domain.
§5.17 classifies and journals it as **trusted validation, never authority**.
Anyone reading `{}` must read §5.17 in the same breath — this sentence exists so
that the empty set is not quoted without its exception.

### 2A.4 How ZI-51 is PROVEN, and whether the proof could pass while false

| Obligation | Mechanism | **Could it pass while the property is false?** |
|---|---|---|
| No git subprocess after spawn, from any dispatcher code path | §5.4.6's **two-half killer**: a whole-tree AST test **over the callee, not the argv**, plus an **fd-backed** runtime audit hook over a complete real run | **NO for any in-interpreter spawn** — MEASURED (Z8 M1/M2/M3) across eleven spawn forms including `os.fork()`+`os.execv`. **YES** for a C extension that calls `fork`/`execve` without raising CPython audit events (**UNMEASURED**, and no such dependency exists in `src/**` today), and **YES** for a git process started by a *different* process the dispatcher launched — which is out of scope by construction and is §5.17's subject |
| No git-**derived value** is consumed after spawn | `test_finalize_consumes_only_sealed_authority`: every FINALIZE consumer takes its base facts from a handle whose provenance field is `sealed_at_prepare`, asserted at the seam | **YES if the seal itself were produced post-spawn.** Closed by `test_seal_written_after_spawn_is_rejected`: the check is the **existence of `runs/NNN/ownership.json`**, a file written only from a `WorkerHandle`, **not a clock comparison** — a mutant that forges `sealed_at` still fails |
| The invariant is not silently narrowed by a later edit | `test_central_invariant_states_zero` — a P-M9-family documentation mutant: the phrase *"after worker launch"* must never appear in the same paragraph as a permitted git subcommand name | **YES to a paraphrase.** It is a **tripwire**, labelled as one, exactly as §11.6 already labels its two documentation mutants |

**A killer that cannot fail against its own mechanism is the defect the fourth
review found in B-3.** So §5.4.6's tests ship with mutants that **must** make
them red — including **`Z8-M30`** (`shutil.which("git")` as argv[0], to which a
literal-`"git"` predicate is **blind** — MEASURED), **`Z8-M31`** (variable
argv[0], the `validation.py:228` shape), **`Z8-M32`** (`stdout=<fd>`, the
`git.py:776` shape) and **`Z8-M33`** (a git call in a helper module outside the
AST root set, **killed only by the runtime half — which is stated rather than
discovered later**).

### 2A.5 What this closes, and the exact class it closes

ZI-51 is **a closure for a class of question, and it is exact about which class**.
It says nothing about anything else. In particular it does **not** close:

- **the PREPARE window.** Ten enumerated git commands run there (§5.4.3), gated
  by §5.8's raw establishment and pinned by three argv/env pins. That window is
  defended by **enumeration**, and the enumeration has been wrong twice.
- **the worker's own capability.** The worker has Bash and its own git and can do
  anything a same-uid process can do, including to the seal.
- **validation and its descendants** (§5.17), which are an execution domain by
  design.

### 2A.6 The residual, stated plainly

> **A worker that modifies the seal AND its manifest coherently produces a
> consistent lie.** That requires forging a manifest hash chain over content the
> dispatcher wrote, which is the same capability class as §5.8.4's baseline
> forgery, mitigated by the same optional out-of-repository HMAC and no more.
>
> **A PREPARE-window compromise** — a repository whose administrative state was
> already hostile when the operator established the baseline, or a git defect
> reachable from §5.4.3's ten rows — produces a **sealed lie**. §5.8's gate and
> the operator's trust step are the only things standing there.
>
> **Sealing does not improve either residual. It confines both to one window,
> before any untrusted process exists.**

### 2A.7 Cost

ZI-51 has no runtime cost of its own. It **removes** work from FINALIZE (the lazy
`cat-file` pass, the B2 `rev-parse`) and **moves** it to PREPARE. The trade is
§5.5.3A's budget and the refusal it implies, and the numbers are measured there.
**Net wall-clock is not asserted**: the two windows are not symmetric and no
end-to-end measurement was made.

### 2A.8 Backward compatibility

`DiffEvidence`, `DispatcherObservations` and every field name §2 of the brief
protects are unchanged — they are **produced from sealed material instead of from
git output**. `worktree-base.json` keeps its name and gains fields.
`git-invocations.jsonl` keeps its schema; **its FINALIZE window becomes empty**,
which is a strictly stronger post-condition than revision 5's two-row rule and
needs no argv pin and no seam counter to stay closed. **An empty set is the only
set that cannot be widened by accident.**

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
| **B2 exact-full-SHA `worktree HEAD == base_commit`** | **already defeatable at the baseline by ONE plain file write, with no git command** — S-ε: `rev-parse --verify HEAD^{commit}` returns the **expected SHA at `rc=0`** while the tree and blobs are the attacker's. **Every mitigation revision 4 added passes while it does, because none of them pins the repository** | §5.5.2C, §5.4.1A |
| **"untracked PATH detection" and the whole evidence path** | **the artefact Fable reads is composed AFTER validation** (`server.py:2454`), and **scope is decided over the validation-inclusive set** (`server.py:2123`). *"Silently rewrite the worker patch and call the result Claude's work"* is **already shipped**, with no flag recording it | §5.5.6, §5.17 |

These are the honest state of the baseline. **Wave 0 exists because of them.**

> **`base_ref` is not on the §2 list and must not be added to it as a
> non-regression.** §4.14 **narrows** production admission: `base_ref: "HEAD"`
> stops being accepted. That is a deliberate behaviour change with an operator
> cost, and it is escalated (T-24) rather than smuggled in under
> *"no regression"*.

### 3.5 One canonical crash matrix

> **There is exactly ONE crash-point table in this document. It has FIFTEEN rows,
> C1…C20, in §15. Every other section references it by row id and states no count
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

### 4.14 Production `base_ref` is an EXACT object name (Sol §6)

#### 4.14.1 Current failure — one line

```python
# models.py:398
class RepositoryRequest(StrictModel):
    root: NonEmptyStr
    base_ref: NonEmptyStr = "HEAD"          # <- the defect, in one line
```

`server.py:918` → `git.py:382` `resolve_base_commit(repo, base_ref)` →
`rev-parse --verify <ref>^{commit}` in the **primary** repository. Three
consequences, all live:

1. **The default is symbolic and silent.** A caller who omits `base_ref` gets
   whatever the primary repository's local `HEAD` happens to be. On
   `/home/dev/full-voice-agent` that is `06bfcd61…` — **measured today, 154
   commits behind `origin/main` (`5eca2113…`).** Sol's brief recorded 139+; **the
   gap has grown by fifteen commits while the envelope text `base_ref: "HEAD"`
   did not change by one byte. That drift is the directive's own best argument:
   the recorded intent is stable and its meaning is not.**
2. **The post-condition is the wrong assertion.** `git.py:405` asserts only that
   the answer matches `^[0-9a-f]{40}$`. **It never asserts that the answer is
   what was asked for.** With a symbolic input that assertion cannot be written;
   with an exact input it is one comparison, **and it is the whole of the
   difference between *resolving* and *verifying*.**
3. **It is a TOCTOU by construction.** Between Sol deciding what to dispatch and
   the dispatcher resolving `HEAD`, any process on the host can move the ref, and
   nothing in the envelope records that it moved.

**The design already knows this in its own error text.** `server.py:423`, the
`WorktreeBaseMismatch` remediation, tells the operator: *"Re-dispatch with
`repository.base_ref` **naming the commit you intend**."* And `sessions.py:314`
already passes a resolved 40-hex SHA as the child's `base_ref` on the
child-session path. **The exact-SHA discipline exists in this codebase on the
paths that were written after somebody got burned. §6 applies it to the path that
was written first.**

#### 4.14.2 The invariant

> ### INVARIANT ZI-61 — PRODUCTION BASE REF IS AN EXACT OBJECT NAME
>
> For any dispatch admitted through the **registered production MCP entrypoint**
> (the entrypoint §4.12 gates), `repository.base_ref` **MUST** match
> `^[0-9a-f]{40}$` and **MUST** verify, in the canonical allowed root, to a
> commit whose own object id is **byte-identical to that string**.
>
> Refused by name: `HEAD`, `@`, `main`, `origin/main`, `refs/heads/main`, any
> tag, any short SHA, **any uppercase SHA**, `<sha>^`, `<sha>~1`,
> `<sha>^{commit}` written by the caller, `@{upstream}`, `@{-1}`, `:/text`, and
> anything beginning `-`.
>
> **Sol resolves and fetches the desired revision before dispatch. The dispatcher
> verifies and never chooses. A base commit absent from the object store is a
> refusal, never a fetch.**
>
> Dev and test APIs may retain broader ref support. **Production authority is
> exact SHA.**

#### 4.14.3 Mechanism

**(a) Shape — pure string work, no git process, at R2 of §5.4.3B's order.** The
default is **deleted**: `base_ref: NonEmptyStr` with **no default**, so omission
is a refusal for every caller, dev included. Keeping the field `str` is what
preserves dev flexibility. The exactness rule is a **production policy
predicate** evaluated from the activation state §4.12 already computes:

```
if production_entrypoint and not re.fullmatch(r"[0-9a-f]{40}", base_ref):
    raise ProductionBaseRefNotExact(...)        # PREPARE refusal, §8 row 0
```

**Lowercase-only is load-bearing and is MEASURED, not assumed.** git accepts an
uppercase SHA and **normalises it to lowercase on output**:

```
$ git rev-parse --verify --end-of-options 5192A5A1…DDE22^{commit}
5192a5a10faeb7e00cdbad3c40c35fb5533dde22        rc=0
```

**Without the lowercase-only shape rule the byte-equality post-condition below
would fire on a legitimate uppercase input, and the implementer would "fix" it by
weakening the comparison. The shape rule is what makes the equality
well-defined.**

**(b) Verification — the first git process of the dispatch, at G1.**
`resolve_base_commit` is renamed **`verify_base_commit`** — *resolve* is what a
symbolic ref needs; *verify* is what an exact one needs:

```
verify_base_commit(repo, base_ref) -> str
  argv:  rev-parse --verify --end-of-options <base_ref>^{commit}
  cwd:   canonical_root (primary)
  post:  rc == 0
         stdout.strip() == base_ref        <-- NEW, and it is the point
         else: BaseRefNotACommitObject | BaseCommitAbsent
```

**Four measured rows justify each element (git 2.43.0, throwaway repo):**

| Input | Result | Why it matters |
|---|---|---|
| `<commit sha>^{commit}` | `rc=0`, echoes the same sha | the normal path; equality holds |
| **`<annotated tag object sha>^{commit}`** | `rc=0`, returns a **DIFFERENT** sha (`a6d2ba69…` in → `5192a5a1…` out) | **the equality check catches a caller naming a tag object; a 40-hex-only check would silently adopt the peeled commit** |
| `--not-a-ref` with `--end-of-options` | `rc=128`, *"Needed a single revision"* — **not parsed as an option** | argv-injection hygiene, free, and it protects the dev path where symbolic refs remain legal. **`--end-of-options` is supported by `rev-parse` on 2.43.0 — MEASURED, not inferred from documentation** |
| absent-but-well-formed sha | `rc=128` | `BaseCommitAbsent`; and `rev-parse --verify` is **measured clean on S-δ — it does not fetch** |

**(c) The boundary with §5.8.2B, stated so the two directives do not look
contradictory.** §7 removes a git command because it asks git *which repository
is authorized*. §6 keeps a git command that asks git *whether a named commit
exists in a repository that has already been authorized, locked and
administratively established*. **The first is a question about authority and git
must not answer it. The second is a question about content and only git can
answer it.** §5.4.3B's ordering is what makes the distinction real rather than
rhetorical: **G1 runs after R3–R7.**

#### 4.14.4 The operational consequence, written down

- **Today**, `base_ref: "HEAD"` against `/home/dev/full-voice-agent` means
  `06bfcd61…`, **154 commits behind `origin/main`**, and nothing in the envelope,
  the task record, the run record or the gate report says so.
  `RepositoryRecord.base_ref` stores the *string* `"HEAD"` — **so the ambiguity is
  recorded, and it is recorded as the word `HEAD`, which is not information.**
- **After ZI-61**, that dispatch is refused at R2, **before the lock, before any
  git process**, with `state.json` byte-identical.
- **The dispatcher must NEVER fetch to make a dispatch possible.**
  `BaseCommitAbsent` is terminal for that request. **This is not a convenience
  decision: a dispatcher that fetches is a dispatcher that runs a transport
  program the repository names — which is S-δ, on the earliest path of every
  dispatch.** PIN 1 makes the failure loud; **ZI-61 makes the *intent* to fetch
  inexpressible.**

**Migration, and it is deliberately inert:**

| Surface | Treatment |
|---|---|
| The five historical forensic tasks | **Not read, not rewritten, not touched.** |
| Any stored envelope with `base_ref: "HEAD"` | `base_commit` remains authoritative for B2 and resume. **No stored record is rewritten.** ZI-61 is a *dispatch-time admission rule*, not a re-interpretation of history — **rewriting stored `base_ref` would be the silent repair `CLAUDE.md` §2 forbids** |
| Resume | Unchanged. `sessions.py:314` already carries an exact SHA. **§6 makes the dispatch path match the resume path, not the other way round** |
| Dev / test callers | Broader refs still legal; **the only break is that `base_ref` becomes required.** *(Escalated as **T-24**: the alternative — a dev-only `"HEAD"` default — reintroduces a silent default on a code path that shares a model with production)* |

#### 4.14.5 Tests

| Test | Proves | Could it pass while false? |
|---|---|---|
| `test_production_rejects_symbolic_base_ref` — parameterised over `HEAD`, `@`, `main`, `origin/main`, `refs/heads/main`, a tag name, a 7-char SHA, an **uppercase** 40-char SHA, `<sha>^`, `HEAD~1`, `@{upstream}`, `:/fix`, `-x` | each is a PREPARE refusal at row 0, `state.json` byte-identical, no task id, no run index, no worktree, **zero git processes** | **YES if written as a unit test of the validator** — a validator can be correct while the production entrypoint never calls it. **The test must dispatch through the registered production entrypoint.** That is the assertion a mis-wiring breaks |
| `test_production_accepts_only_the_exact_recorded_sha` — repo with commits A (older) and B (= local HEAD); dispatch naming **A** | `base_commit == A`, worktree HEAD is A, B2 passes; **and the same dispatch with `"HEAD"` is refused, not silently pinned to B** | **No** for the pinning claim. **The `"HEAD"`-refused half is the control that proves the fixture could have gone wrong** |
| `test_base_ref_verification_compares_answer_to_input` — `base_ref` = an **annotated tag object id** | refusal `BaseRefNotACommitObject`, **not silent adoption of the peeled commit** | **No** — the oids differ by construction (MEASURED). **This is the killer for the "40-hex is enough" mutant** |
| `test_base_commit_absent_refuses_and_fetches_nothing` — well-formed absent sha, in a **partial clone** with `core.sshCommand` / `core.gitProxy` / `ext::` armed | PREPARE refusal; no fetch; the transport sentinel does **not** fire | **YES without step (b).** Z-RULE-1 is mandatory here: run the same read **without** PIN 1 against an absent *object* and assert the sentinel **FIRES** first. **A version asserting only `rc != 0` passes against a build that fetched successfully** |
| `test_no_default_base_ref_exists` (AST + model introspection) | no default, and no `src/**` expression supplies `"HEAD"` as a fallback (`or "HEAD"`, `get(…, "HEAD")`, `setdefault`) | **YES** for a default constructed from a variable. Paired with the integration test, which is the real killer |
| `test_dev_entrypoint_still_accepts_symbolic_ref` | the production/dev split is wired **the right way round** | **No** — and it exists precisely because the inversion mutant is an *inversion*, which a one-sided test cannot see. **This is the B2-double lesson: doubles can encode the inverse of production** |

#### 4.14.6 Named mutants

| Mutant | Named killer |
|---|---|
| **ZM-P1** restore `base_ref: NonEmptyStr = "HEAD"` | `test_no_default_base_ref_exists` + `test_production_rejects_symbolic_base_ref` |
| **ZM-P2** drop the `stdout == base_ref` post-condition, keep the 40-hex check | `test_base_ref_verification_compares_answer_to_input` |
| **ZM-P3** widen the pattern to `^[0-9a-fA-F]{7,40}$` | `test_production_rejects_symbolic_base_ref` (short + uppercase rows) |
| **ZM-P4** fetch on `BaseCommitAbsent` "to be helpful" | `test_base_commit_absent_refuses_and_fetches_nothing` — **and the killer must be the SENTINEL, not a string assertion, because this mutant IS S-δ's precondition** |
| **ZM-P5** apply the exactness rule to the dev entrypoint and not production | **two sides required**: `test_production_rejects_symbolic_base_ref` **and** `test_dev_entrypoint_still_accepts_symbolic_ref` — an inversion passes any single-sided test |
| **ZM-P6** rewrite stored `base_ref` to `base_commit` during migration | `test_legacy_envelope_base_ref_text_is_not_rewritten` — byte-compare envelope JSON before/after a migration pass, **on copies in a temp dir; the five forensic tasks are never opened for writing** |
| **ZM-P7b** accept `<sha>^{commit}` typed by the caller (looks exact, is a revision expression) | `test_production_rejects_symbolic_base_ref` — **the pattern contains no `^` and no `{`** |

#### 4.14.7 Backward compatibility

No MCP tool signature changes; **still four tools, forever.**
`RepositoryRecord.base_ref` keeps its type and `max_length=256`. No state-file
migration. **The single behavioural break is production admission, and it is a
refusal at row 0 with no lifecycle mutation** — the shape brief §7 exists to
require.

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
  all four armed surfaces (§5.4.3), and the capture prefers a raw resolver over
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

#### 5.4.1 FOUR independent execution surfaces — and the count has now been wrong twice

| Surface | Selected by | Triggered by |
|---|---|---|
| **S-α — attribute-selected content transform** | an *attribute* (`filter=`, `diff=`, `-diff`, `working-tree-encoding`) from `.gitattributes`, `info/attributes` or `core.attributesFile`, plus a config-defined driver | any command that **reads working-tree content through git's content pipeline** |
| **S-β — index refresh** | `core.fsmonitor` **alone; no attribute needed** | any command that **refreshes the index** |
| **S-γ — ref update** *(found by the third review)* | the hook `$GIT_COMMON_DIR/hooks/reference-transaction`, and via `core.hooksPath` the **entire 28-hook namespace** | any command that **creates, moves or deletes a ref** — including `worktree add --no-checkout`, `--detach`, `pack-refs` and `gc` |
| **S-δ — promisor lazy fetch** *(found by Lane Z5; **the most severe**)* | `extensions.partialClone` + `remote.<n>.promisor` + a transport program: `core.sshCommand`, `core.gitProxy`, or `ext::` once the worker sets `protocol.ext.allow=always` | any command that **reads an object that is not present locally** — because *an object-store read of an absent object is not a read, it is a FETCH* |

**S-δ lands on the two commands this design treated as unconditionally safe.**
Measured, with a positive control in the same repository:

```
cat-file blob <ABSENT>        [PERMITTED]   rc=128  EXEC:sshcommand-prog
cat-file --batch <ABSENT>     [PERMITTED]   rc=0    EXEC:sshcommand-prog   <-- SILENT
ls-tree -r -z --long <base>   [PERMITTED]   rc=0    EXEC:sshcommand-prog   <-- SILENT
ls-tree -r -z <base>          [no --long]   rc=0    clean
rev-parse --verify HEAD^{commit}            rc=0    clean
```

**`cat-file --batch` and `ls-tree --long` execute the worker's program and return
`rc=0`.** The dispatcher sees a successful command; `git-invocations.jsonl` would
record `"returncode": 0`. Confirmed a second time through `core.gitProxy`, and a
third through `ext::`.

**Both preconditions are plain file operations with no git command at all**:
append to `.git/config` (which `Write` reaches), and `rm` **one loose base blob** —
*chosen deliberately, because it is a blob §5.4.3's lazy FINALIZE `cat-file` is
guaranteed to read.* **The attack is aimed precisely at the design's own
laziness.**

**And `--long` is what arms it.** `--long` prints the blob **size**, which
requires the blob; `ls-tree -r -z` without it is clean. §5.4.3 and §5.5.2
specified `--long` **by name**.

> ##### The paragraph this falsifies, quoted so it cannot be re-derived
>
> Revision 3 §5.4.3: *"`ls-tree` and bare `cat-file` read the **object database**
> and never touch the working tree or the index … That is a **structural**
> property of object-store reads rather than a per-key enumeration, which is why
> it is expected to survive a git upgrade."*
>
> **Measured false.** The paragraph is the exact form of reasoning this gate
> exists to distrust: a structural argument extended one category past its
> evidence. It is deleted, not softened.

> ##### The count has been wrong twice, and that is the finding
>
> Revision 3 said two surfaces and asserted *"a fourth surface may exist. The
> design does not claim otherwise."* **S-γ existed. Then S-δ existed.** Z1's
> caveat — *"S-α and S-β are the two surfaces I know about, not the two that
> exist"* — has now been **demonstrated true twice**, once by each of the last two
> reviews.
>
> **So the honest framing, and it replaces every "structural" claim in §5.4:**
> the post-worker path is **closed by an enumerated, argv- and env-pinned defence
> on FOUR measured surfaces, with no proof that four is all of them.** Not
> structurally. Not by a property that survives a git upgrade unexamined. **By a
> defence whose completeness is bounded by the number of surfaces someone has
> thought to arm**, which is four, and which was two a fortnight ago.

**What the four measurements could and could not have detected.** Each was run
with a positive control armed for that surface in the same repository in the same
run; a `clean` row with a dead control is reported **NOT TESTABLE**, never
`clean`. What none of them could detect is **a fifth mechanism nobody
enumerated** — and the fourth review found one. **It is not an execution surface
at all.**

#### 5.4.1A S-ε — STORE AND REFERENCE REDIRECTION. It executes nothing, and that is why the surface model could not see it (Sol §4)

**Every surface above answers one question: *is a program running?* S-ε answers a
different one: *what does a read resolve against?* No pin in §5.4.3A constrains
it, because none of them is about resolution.** That sentence is the fourth
review's and it is the finding.

**MEASURED — Lane Z7's thirteen-variant matrix, each row reporting EFFECT (did a
permitted read return the attacker's data?) separately from REVPARSE (do the
identity commands still look legitimate?) and RAW (does a sealed raw fingerprint
change?). Row 0 is the un-poisoned negative control and reads clean on all
three.**

| # | Variant | Files the worker writes — **no git command** | EFFECT | REVPARSE | RAW |
|---|---|---|---|---|---|
| 0 | **baseline, no poison** | — | **NONE** | LEGIT | **CLEAN** |
| A | gitfile → fake | `<wt>/.git` | head+blob+tree | **foreign** `--absolute-git-dir` **and** `--git-common-dir` | DETECT (13 fields) |
| B | `commondir` → fake | `worktrees/<id>/commondir`, `HEAD` | head+blob+tree | **foreign** `--git-common-dir` only | DETECT |
| C | alternates + worktree `HEAD` | `objects/info/alternates`, `worktrees/<id>/HEAD` | head+blob+tree | **ALL LEGIT** | DETECT |
| **C2** | **alternates ONLY, `HEAD` untouched** | `objects/info/alternates` | **NONE** | ALL LEGIT | DETECT |
| **D** | **`refs/replace/<oid>`** | one file | **blob+tree, head = EXPECTED SHA** | **ALL LEGIT** | DETECT |
| **D3** | **`refs/replace/<tree-oid>`** | one file | **blob+tree, the COMMIT OID IS UNTOUCHED** | ALL LEGIT | DETECT |
| **E3** | replace-reparent | one file | **ROOT COMMIT forged** | ALL LEGIT | DETECT |
| **E2** | **`info/grafts`** | one file | **ROOT COMMIT forged, `rc=0`** | ALL LEGIT | DETECT |
| F | `http-alternates` | two files | **NONE** | ALL LEGIT | DETECT |
| G | `core.worktree` | `config`, `config.worktree` | NONE | **foreign `--show-toplevel`** | DETECT |
| **H** | **object transplant + `HEAD`, NO alternates file** | `worktrees/<id>/HEAD` + objects into the real store | **head+ROOT+blob+tree** | **ALL LEGIT** | DETECT |
| **H2** | **H with `alternates` explicitly DELETED** | as H | **head+ROOT+blob+tree** | ALL LEGIT | DETECT |

**Five findings, and four of them change what this document said.**

**(i) `refs/replace/**` is the variant nobody named, and it is *exactly* the
brief's signature.** Verbatim (Z7 §3.4):

```
  plain                   : FAKEBLOB
  --no-replace            : REAL
  GIT_NO_REPLACE_OBJECTS  : REAL
  cat-file batch plain    : FAKEBLOB
  ls-tree plain           : m.txt
  rev-parse HEAD^{commit} : e14cade2…  (expected e14cade2…)
```

**One plain file write. `rev-parse --verify HEAD^{commit}` returns the expected
SHA at `rc=0` while `cat-file --batch` and `ls-tree` serve the attacker's
content, and all four identity commands are legitimate.** It can also forge the
**root commit** (E3) and replace **the tree alone, leaving the commit oid
untouched** (D3). It was in no table in revision 5, and **none of the four
mitigations review 4 proposed for S-ε touches it** — they name the gitfile,
`commondir`, `worktrees/<id>/HEAD` and `objects/info/alternates`.

> ### PIN 3 — `GIT_NO_REPLACE_OBJECTS=1` in `_git_env`, unconditionally.
>
> **MEASURED to neutralise it** (`--no-replace-objects` on the argv does the same
> and is redundant with the env form). **MEASURED absent: `GIT_NO_REPLACE` and
> `no-replace-objects` have ZERO hits in `src/**`**, so every one of the sixteen
> live authoritative invocations is currently exposed to it.

**(ii) `info/grafts` is LIVE on git 2.43.0, and Z7's first measurement of it was
a false negative.** Re-armed: `rc=0`, correct-looking output, the deprecation
hint on **stderr only**, and the **root commit forged** — which is
`collect_repository_identity`'s repository fingerprint (`git.py:362`,
`rev-list --max-parents=0 HEAD`). *Z7 recorded its own confounded first attempt
rather than filing the negative. That is the standard, and it is why this row
exists in this table at all.*

**(iii) Deleting `objects/info/alternates` DOES NOT close variant C.** Rows **H**
and **H2** are byte-identical in outcome with **no alternates file present at
all**. **The worker does not need an alternate; it needs the objects to exist,
and it has Bash and its own git.** Review 4's mitigation #4 is **measurably
insufficient** and is not adopted.

**(iv) `objects/info/alternates` alone is an AVAILABILITY primitive, not a
FORGERY primitive.** Row C2: the alternate is armed, `HEAD` is untouched,
`EFFECT=NONE`. **Objects are content-addressed, so an alternate can only supply
an object by its true oid** — it can make an absent object present; it cannot
substitute different content for the same oid. **The authority-bearing file in
variant C is `worktrees/<id>/HEAD`.** Capturing `alternates` is right (it is a
store-identity change and must be TAMPER) and **capturing it does not close C.**

**(v) `objects/info/http-alternates` is NOT honoured for local object lookup on
2.43.0** — row F, `EFFECT=NONE`, armed identically to C which fired. **`NOT
OBSERVED`, not `clean`.** It is still sealed (§5.8.2), because it is cheap and it
is load-bearing for other transports.

#### 5.4.1B How S-ε is closed — and it is not by a longer denylist

> **INVARIANT ZI-52 — THE DISPATCHER DOES NOT CONSULT THE STORE AFTER LAUNCH.**
>
> **A redirection of a store that is never consulted redirects nothing.** That is
> the closure, and it is §1 (§2A) applied to this family.
>
> **In addition, and independently**, the store-routing and administrative state
> is snapshotted **pre and post by raw filesystem means** (§5.8.2). A START→POST
> change is **`POLICY_VIOLATION`, §8 row 4**, with each changed file named and
> its before/after sha256.
>
> **The evidence stays trustworthy because it is computed from the sealed
> pre-worker snapshot, not from the changed store. The post-worker comparison
> REPORTS the attack; it is not what protects the evidence from it.**

That ordering is the whole point and it must survive integration: §5.8.1's own
complaint about revision 2 was *"detection after execution is not containment."*
Here, detection is after the change and **containment does not depend on it**.

**Should the alternates file be REMOVED before evidence? NO — capture and report.**
Review 4 asked. Three reasons, with the counter-argument stated fairly:

- under ZI-51 the store is never consulted post-worker, so deletion buys nothing
  for evidence integrity — it would defend a mechanism that no longer exists;
- **deletion is a WRITE into the target repository by the dispatcher**, and
  §5.9.2's *"the dispatcher does not clean, reset, stash or checkout"* discipline
  holds for the object store too. A legitimate `alternates` — which
  `git clone --shared` creates — would be **destroyed**, and the failure would be
  attributed to the dispatcher, correctly;
- **and it does not work anyway**: rows H and H2 are the measurement.
- **Counter-argument:** deletion is the only measure that still works if ZI-51 is
  ever weakened. **That is an argument for making ZI-51 hard to weaken (§5.4.6's
  runtime killer), not for taking a destructive action now.** *(Escalated as
  **T-11**.)* If Sol rules for deletion it must be a copy-aside-and-restore with
  the original bytes in the seal, gated on the file not being in the trusted
  baseline, and **a named, journaled, reversible act — never a quiet `unlink`.**

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

#### 5.4.3 The repertoire — TEN PREPARE rows, and `{}` after the spawn (Sol §16, §17)

> **The post-worker set is EMPTY** (§2A). The table below is therefore the
> **PREPARE** repertoire and nothing else. It is enumerated, and the enumeration
> is now the *only* thing defending that window — there is no structural
> fallback, and the surface count has been wrong twice.

**The ten rows, in the order §5.4.3B declares them:**

| # | Command (exact argv) | `cwd_role` | Purpose | Sealed into |
|---|---|---|---|---|
| G1 | `rev-parse --verify --end-of-options <base_commit>^{commit}` | primary | §4.14 verification. **Post-condition: `stdout == base_ref`, byte for byte** | `base_commit` |
| G2 | `ls-tree -r -z <base_commit>` **(no `--long`)** | primary | base tree **identity** | `base-tree.json` |
| G3 | `worktree list --porcelain` | primary | is the task worktree registered? | `repo-authority.json` |
| G4 | `worktree add --quiet -b <branch> <path> <base_commit>` | primary | **the ONE PREPARE execution-capable operation.** Gated by §5.8 **and** argv-pinned; neither alone (§5.5.5) | — |
| G5 | `rev-parse --verify HEAD^{commit}` | task_worktree | **pre-launch** confirmation that the checkout landed on the base | `worktree-base.json.pre` |
| G6 | `rev-list --max-parents=0 HEAD` | primary | identity: root commit | identity record |
| G7 | `config --get remote.origin.url` | primary | identity: origin. **`rc=1` is a measurement, not a failure** | identity record |
| G8 | `cat-file --batch` fed **object ids** | primary | **Route B sealing** (§5.5.2A) | `cas/` |
| G9 | `rev-list --objects --missing=print HEAD` | primary | **the promisor verifier** (§5.5.2B) | `repo-authority.json` |
| G10 | `rev-parse --absolute-git-dir` / `--git-common-dir` | primary | §5.8.2A **fallback only**, and **never on the authorization path** (§5.8.2B) | `repo_authority.resolver` |

**THREE ROWS ARE DELETED FROM THE PERMITTED SET, and deletion is the disposition
rather than measurement:**

| Deleted row | Why |
|---|---|
| ~~`rev-parse --show-toplevel`~~ | **Sol §7.** It asks git *which repository is authorized* — a question git must not answer — and F-7 found it is **the earliest git command of every dispatch and absent from A.2B entirely**. Authorization becomes `realpath` equality (§5.8.2B). **Deleted from `src/**`, not measured.** |
| ~~`read-tree <base>` with an external `GIT_INDEX_FILE`~~ | Z-4 is retired (§5.5.5(c)), so `dispatcher_raw` buys nothing on execution safety and this row **has no call site**. Z7 independently measured that `read-tree` **fires `post-index-change` even with an external `GIT_INDEX_FILE`**. **All three revision-6 lanes independently recommended deletion.** A permitted row with no caller is a standing invitation to acquire one. Killer `ZM-E7` is retained — it already catches its return |
| ~~`rev-parse --is-inside-work-tree`~~ | **no call site in `src/**`** (measured, revision 5). Same argument. `is_git_repository` (`git.py:238`) is **deleted, not deprecated** — no compatibility wrapper |

**The FINALIZE row set:**

| Command | Verdict |
|---|---|
| *(none)* | **`{}`.** §2A's table names the two mechanisms that emptied it. **The pinned `argv_sha256` and the `_verify_worktree_base` seam counter are deleted with it** — they existed only to keep a two-member set from growing, and deleting them removes two things a mutant could edit in a diff |

**Every surviving row re-measured on all FOUR surfaces** (Lane Z5, positive
control per surface per run; Z7 re-armed G8 and G9 with a genuinely absent
object):

| Command (exact argv) | Phase | S-α | S-β | S-γ | **S-δ** | verdict |
|---|---|---|---|---|---|---|
| `rev-parse --verify <ref>^{commit}` | **PREPARE ONLY** (G1, G5) | clean | clean | clean | **clean** | clean on all four |
| ~~`rev-parse --show-toplevel`~~ | — | clean | clean | clean | **NOT IN A.2B** | **DELETED (Sol §7).** Its S-δ column in revision 5 **came from nowhere** — F-7 |
| `rev-parse --absolute-git-dir` / `--git-common-dir` | PREPARE (G10, fallback) | clean | clean | clean | **clean** | **retires `REQUIRES-PROBE`** |
| `rev-list --max-parents=0 HEAD` | PREPARE (`git.py:362`) | clean | clean | clean | **clean** | clean on all four |
| `config --get remote.origin.url` | PREPARE (`git.py:359`) | clean | clean | clean | **clean** | clean on all four |
| `worktree list --porcelain` | PREPARE | clean | clean | clean | **clean** | **retires `REQUIRES-PROBE`** |
| **`ls-tree -r -z <base>`** *(NO `--long`)* | PREPARE | clean | clean | clean | **clean** | **clean on all four — this is the argv the design now uses** |
| ~~`ls-tree -r -z --long <base>`~~ | — | clean | clean | clean | **FIRES, silently, `rc=0`** | **REMOVED — `--long` is what arms S-δ** |
| `cat-file --batch` fed object ids | **PREPARE ONLY** (G8, Route B) | clean | clean | clean | **FIRES, silently, `rc=0`** — re-confirmed by Z7 with a genuinely absent object: `rc=0`, correct content, **missing count 3→2** | **permitted ONLY under PIN 1** |
| `cat-file blob <oid>` | PREPARE | clean | clean | clean | **FIRES (`rc=128`)** | **permitted ONLY under PIN 1** |
| **`rev-list --objects --missing=print HEAD`** *(new — G9)* | PREPARE | clean | clean | clean | **clean under PIN 1: `rc=0`, lists absent oids prefixed `?`** | **the only command that REPORTS absence instead of dying of it** (Z7 §5.3) |
| ~~`read-tree <base>` with an external `GIT_INDEX_FILE`~~ | — | clean | clean | **FIRES `post-index-change`** † | clean | **DELETED from the permitted set.** No call site; Z7 confirms an external index does not avoid the hook |
| `worktree add` (any form) | PREPARE, only after §5.8 passes | **FIRES** smudge (checkout forms) | **FIRES** (checkout forms) | **FIRES `reference-transaction` in EVERY form, `--no-checkout` and `--detach` included** | FIRES (checkout form) | **gated + argv-pinned** |
| ~~`rev-parse --is-inside-work-tree`~~ | — | clean | clean | clean | **clean** | **DELETED.** No call site in `src/**`; `is_git_repository` is removed from `git.py` |

**Two rows measured by Z7 that must be read next to this table, because they are
the fail-closed behaviour PREPARE depends on:**

```
promisor remote unreachable, GIT_NO_LAZY_FETCH=1:
  git fetch                        rc=128     <- materialisation failed, loudly
  rev-list --objects --missing=print rc=0     <- the verifier still ANSWERS
  cat-file --batch                 rc=128
  ls-tree -r -l                    rc=128     <- the -l size column needs the blob
  ls-tree -r        (no -l)        rc=0
  rev-parse --verify HEAD          rc=0       <- !!!
```

> **`rev-parse --verify HEAD` returns `rc=0` in a repository whose blobs cannot
> be read.** A PREPARE that checked only HEAD would proceed into an unreadable
> repository. **This is why G9 exists and why §5.5.2B's step 4 re-verification is
> not optional and is not implied by step 3** — a fetch can partially succeed.
> The `-l` row independently confirms Z5's finding that **the size column is what
> arms the fetch**.

##### The THREE argv/env pins this table depends on — and none of them is in the tree

> **PIN 1 — `GIT_NO_LAZY_FETCH=1` in `_git_env`, unconditionally.** Measured to
> close **the entire S-δ column** in one line, with a negative control confirming
> the same command fires without it. It is **not** set today. **Blanking
> `extensions.partialClone`, `remote.<n>.promisor` or
> `fetch.negotiationAlgorithm` on the argv was measured INEFFECTIVE — all three
> still fired.** A defence that disarms the promisor *configuration* rather than
> the *fetch* does not work; only refusing to fetch does.
>
> **PIN 2 — `-c core.hooksPath=<empty dir>` on every invocation.** Measured to
> neutralise **every one of the 28 hooks**, with a negative control. `/dev/null`
> and a nonexistent path behave identically; **the directory need not exist.** It
> does **not** touch `core.fsmonitor` or `filter.*.smudge` — only `--no-checkout`
> removes those.

† **`post-index-change` is not a ref transaction**, so it is not S-γ's trigger —
but it is a hook in the **same 28-hook namespace S-γ exposes**, reached by an
**index write** rather than a ref update, and it is neutralised by the **same**
pin. It is recorded in S-γ's column because that is the column PIN 2 governs, and
the alternative — a fifth column for one row — would overstate what was measured.
**An external `GIT_INDEX_FILE` does NOT avoid it: the hook fires on the index
write, whichever file is written.**

> **PIN 3 — `GIT_NO_REPLACE_OBJECTS=1` in `_git_env`, unconditionally.**
> Measured (Z7) to neutralise `refs/replace/**` — the S-ε variant that reproduces
> the brief's signature exactly. `--no-replace-objects` on the argv is
> equivalent and redundant with the env form. **It does not touch `info/grafts`**,
> which is closed only by §5.8.2's capture plus ZI-51.

> ### MEASURED ABSENT — the pins are documentation, not code, today.
>
> **`GIT_NO_LAZY_FETCH`, `GIT_NO_REPLACE_OBJECTS`, `core.hooksPath` and
> `attr-source` have ZERO hits in `src/**`** (Z7 §4.2a, grep). `_git_env()`
> (`git.py:126-136`) strips eight `GIT_*` redirect variables and sets exactly
> `GIT_TERMINAL_PROMPT=0` and `GIT_OPTIONAL_LOCKS=0`. **There are zero
> `-c key=value` occurrences in `src/**`.** And
> **`test_no_direct_git_subprocess_in_src` does not exist in `tests/`** — no file
> matches that name or `addaudithook`.
>
> **Every acceptance row that depends on a pin is therefore UNMEASURABLE, not
> green**, and §12.6 says so as a Wave-0 obligation rather than leaving it to be
> discovered. All three pins are Wave 0 work.

**All three pins are ENUMERATED defences and this document does not pretend
otherwise.** Pin 2's necessity is proven by §5.5.5: a worker-set `core.hooksPath`
**survives the dispatcher deleting `$GIT_COMMON_DIR/hooks` outright**, so
filesystem quarantine is not a defence and argv pinning is the only measured one.

**A missing base object becomes a LOUD FAILURE instead of silent execution.**
Under PIN 1, `cat-file` on an absent object **fails** rather than fetching. That
turns Z5's attack precondition — a worker deleting one loose base blob with plain
`rm` — into `BaseBlobUnreadable` at §8 **row 3**, `FAILED`, with the object id
named. **The fail-closed direction is what makes the pin safe to depend on**, and
`test_deleted_base_blob_fails_closed_and_executes_nothing` is its killer, with a
positive control that fires the transport program without the pin.

**`--long` is dropped as a second, independent reduction.** `BaseTreeSnapshot`
does not need blob sizes for its primary purpose: Z-5 makes the `ls-tree` **oid**
the content hash, so no size is read on the hot path. Where a base blob size is
genuinely required — `total_blob_bytes`, and the primary-tree `stat_identity`
size comparison of §5.9.5 — it is obtained **deliberately, for named oids, under
PIN 1**, and a missing object there is the same loud failure. **`TreeEntry.blob_size`
becomes `int | None`**, `None` meaning *not requested*, and a test asserts the
snapshot's default argv contains no `--long`.

**Four rows changed status.** `--absolute-git-dir`, `--git-common-dir` and
`worktree list --porcelain` move from `REQUIRES-PROBE` to **permitted**. Three
rows were **live in `src/**` while the repertoire called itself exhaustive** —
`rev-list --max-parents=0 HEAD`, `config --get remote.origin.url` and
`rev-parse --is-inside-work-tree`; **the exact argv is recorded, not the generic
subcommand**, and the third has **no call site**, so its repertoire status is
moot at runtime although it remains exported public API.

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
> **external `GIT_INDEX_FILE`** touches no worktree index and appears only in
> `dispatcher_raw` materialisation. B-I5 is unaffected: the *task worktree's*
> index is still never written, and the temporary index is a dispatcher-owned
> file. **A `read-tree` without an external `GIT_INDEX_FILE` remains
> prohibited**, and `ZM-E7`'s killer catches its return.
>
> **CORRECTED BY Z5 — `read-tree` is NOT clean.** It fires `post-index-change`
> on S-γ's hook surface, **and an external `GIT_INDEX_FILE` does not avoid it**:
> the hook fires on the index *write*, whichever file is written. It is clean
> only under **PIN 2**. This is one of the measurements that retired Z-4
> (§5.5.5(c)), and the narrowing above stands only because PIN 2 is now global
> policy — **not** because the command is inert.

**Everything else is removed from the dispatcher.** `git status`, `git diff` in
all forms, `git ls-files` in all forms, `git diff --check`, `git diff --stat`
disappear from `src/**`. **This is a deletion, not a hardening.**

##### Why the permitted set is exec-safe — and it is NOT a structural argument

Revision 3 said the permitted set was safe because *object-store reads touch
neither the working tree nor the index* — a **structural** property *"expected to
survive a git upgrade"*. **That paragraph is deleted. It was measured false**: an
object-store read of an **absent** object is a *fetch*, and a fetch runs a
transport program the worker names (S-δ).

The honest statement, and it is weaker on purpose:

> **The PREPARE set is exec-safe because each command was measured against four
> armed surfaces with a positive control, and because three enumerated pins —
> `GIT_NO_LAZY_FETCH=1`, `-c core.hooksPath=<empty>` and
> `GIT_NO_REPLACE_OBJECTS=1` — close the surfaces on which members of the set
> fire. There is no proof that four surfaces are all of them, the count has been
> wrong twice, and the fourth review found a fifth mechanism that is not an
> execution surface at all (S-ε, §5.4.1A).**
>
> **The FINALIZE set needs no such argument, because it is empty.** That
> asymmetry is the whole of revision 6: the window that must be defended by
> enumeration is now the window in which no untrusted process has ever run.

Three consequences follow, and each is a rule rather than a hope:

1. **A git upgrade invalidates this table**, exactly as a Codex upgrade
   invalidates §6.0. `scripts/gate/git_version.py` records `git --version` at gate
   time and compares against a pinned value; **a mismatch is a gate failure whose
   named remediation is to re-run the four-surface probe**, not to re-assert the
   table.
2. **Widening the repertoire is a Sol decision**, and the widening must carry its
   own four-surface measurement with a control.
3. **`test_repertoire_is_clean_on_all_four_surfaces`** runs the full set under
   each surface armed separately, **each pass carrying its own positive control
   that must fire**. **COULD IT PASS WHILE FALSE?** For the four armed surfaces,
   no. **For a fifth nobody has armed, yes — and that is stated rather than
   hidden.**

##### 5.4.3A The global git invocation policy, stated as one block

Every git call in `src/**` goes through `_run_git`, which applies this
unconditionally. **Every line is an enumerated defence and is labelled as one.**

```
env:   GIT_NO_LAZY_FETCH=1        # PIN 1 — closes the whole S-δ column (measured)
       GIT_NO_REPLACE_OBJECTS=1   # PIN 3 — closes refs/replace/** (measured, Z7)
       GIT_CONFIG_NOSYSTEM=1      # ignore /etc/gitconfig
       GIT_CONFIG_GLOBAL=/dev/null# ignore ~/.gitconfig
       GIT_TERMINAL_PROMPT=0      # existing
       GIT_OPTIONAL_LOCKS=0       # existing — suppresses post-index-change for
                                  #   `status` ONLY; measured NOT to for read-tree
       + existing redirect-var stripping (GIT_DIR, GIT_WORK_TREE, GIT_COMMON_DIR,
         GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY, GIT_ALTERNATE_OBJECT_DIRECTORIES,
         GIT_CEILING_DIRECTORIES, GIT_NAMESPACE)
       + NEW scrubbing (hygiene, not a worker path under this threat model):
         GIT_CONFIG_COUNT, GIT_CONFIG_KEY_*, GIT_CONFIG_VALUE_*, GIT_EXTERNAL_DIFF,
         GIT_SSH, GIT_SSH_COMMAND, GIT_ASKPASS, GIT_PAGER, GIT_ATTR_NOSYSTEM

argv:  git -c core.hooksPath=<empty dir>   # PIN 2 — neutralises all 28 hooks
           -c core.fsmonitor=false
           -c core.attributesFile=/dev/null   # partial — see the caveat
           -c core.quotePath=false
           --no-pager  <subcommand> …
```

> **The `--attr-source=<base_commit>` line of revision 5 is DELETED** (F-7's
> third instance). §5.4.4 deletes every diff-producing subcommand from `src/**`;
> **a policy line specifying flags for a class of command that cannot exist is an
> invitation to conclude that a hardened `git diff` is permitted after all.**

**Measured caveats that must travel with this block, not be inferred from it:**

- `-c core.attributesFile=/dev/null` does **not** disable in-tree
  `.gitattributes` or `info/attributes` — reproduced twice. **The "hardened
  checkout" combination is genuinely incomplete**, which is why `worktree add` is
  gated by §5.8 rather than trusted.
- `GIT_OPTIONAL_LOCKS=0` suppresses `post-index-change` for **`status` only**,
  and **not** for `read-tree`. Lane X's C7c note is correct for `status` and
  **does not generalise**.
- **Zero `-c key=value` occurrences exist in `src/**` today**, so none of these
  pins is implemented; all are Wave 0 work.
- `GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_n` is a viable *alternative* lever for
  pinning `core.hooksPath` without touching argv. **Recorded, not adopted** — argv
  is simpler to assert in the journal. (Z5's first attempt used `GIT_CONFIG_KEY0`
  without the underscore and git refused with `rc=128`; **that row is reported
  NOT TESTABLE as run, never `clean`** — a reading from a command that never
  executed proves nothing.)

##### Lane X's TIER-0 table is corrected

Lane X listed `core.sshCommand` and `core.gitProxy` under *"NOT executed in the
dispatcher's context"*, with the correct caveat that the list was *"safe only
because the dispatcher's command repertoire is …"*. **The repertoire it named did
not include a lazy-fetch trigger. It does now — `cat-file` and `ls-tree` are the
whole post-worker repertoire — and both keys are measured EXECUTING via S-δ.**
Both move to **executed**. `credential.helper` and `core.alternateRefsCommand`
remain **NOT OBSERVED** from the repertoire, each from an experiment whose control
fired.

##### 5.4.3B The pre-worker command ORDER, declared as data (Sol §19, closes F-7)

**F-7's defect is not that two rows were missing from a matrix. It is that the
matrix was ordered by how interesting a command looked, not by when it ran** — so
the enumeration omitted the earliest command of every dispatch, the one that
decides whether the repository is even allowed. **An enumeration ordered by
interest will always omit its own plumbing, and plumbing runs first.**

**Measured order in the tree at `d197bf0`, dispatch path — nine git processes,
three of them `--show-toplevel`, one of them `git status`, and the first three
run before anything has established that this repository is safe to run git in:**

| # | `server.py` | Command | Runs before |
|---|---|---|---|
| 1 | `904` → `security.py:217` → `git.py:271` | `rev-parse --show-toplevel` | **the lock, the authorization decision it feeds, and any establishment** |
| 2 | `909` → `locks.py:72` → `git.py:271` | `rev-parse --show-toplevel` again | the lock it is naming |
| 3 | `918` → `git.py:386` | `rev-parse --verify HEAD^{commit}` | materialisation |
| 4 | `954` → `git.py:608` | `worktree add …` | — |
| 5 | `977` → `git.py:531` | `rev-parse --verify HEAD^{commit}` (B2) | — |
| 6 | `1002` → `git.py:350,353,359,362` | `--show-toplevel`, `--absolute-git-dir`, `config --get`, `rev-list --max-parents=0` | — |
| 7 | `1037` → `git.py:904` + `:386` | **`git status --porcelain`** + `rev-parse HEAD` | the spawn, by ~5 lines |

**There is no administrative establishment step in the tree at all**; §5.8.3's
step 0 is design, not code.

> ### INVARIANT ZI-53 — NO GIT PROCESS PRECEDES THE RAW ESTABLISHMENT THAT MAKES IT ACCEPTABLE
>
> The pre-worker git sequence is **declared as data, in execution order, in one
> place, per dispatch path**. **Step R6 — raw administrative establishment —
> runs before the first git process of the dispatch and runs no git process
> itself.**
>
> `_run_git` **refuses to execute** (`GitBeforeEstablishment`,
> `InternalDispatcherError`) when the current `ToolExecution` carries no
> establishment marker.

**DISPATCH. Everything above the line is raw: no subprocess of any kind.**

```
── PRE-GIT. RAW ONLY. ZERO GIT PROCESSES. ──────────────────────────────────────
 R0  request shape / transport validation            pure Python
 R1  validation-budget assertion (Gate 6, K-1)       pure Python
 R2  production base_ref exactness      (§4.14)      pure string   -> row 0
 R3  repository AUTHORIZATION           (§5.8.2B)    realpath == allowlist -> row 0
 R4  raw git layout resolution          (§5.8.2A)    open()/stat() -> row 0
 R5  repository lock acquisition                     flock on the realpath digest
 R6  RAW ADMINISTRATIVE ESTABLISHMENT   (§5.8.3)     open(path,"rb") ONLY
       capture(role="pre_run"); no baseline -> Unestablished (row 0)
       != baseline -> Unreconciled (row 0, NOT retryable)
       writes the ESTABLISHMENT MARKER row into git-invocations.jsonl
 R7  PRIMARY_START raw snapshot         (§5.9)       raw HEAD + FsSnapshot + admin
── THE FIRST GIT PROCESS OF THE DISPATCH IS HERE, AND NOT BEFORE ───────────────
 G1 … G10   exactly §5.4.3's ten rows, in that order
── SEAL (§5.5.2A) — manifest written LAST, atomically ──────────────────────────
── worker spawns ───────────────────────────────────────────────────────────────
```

**RESUME declares its own order, and a second table is not optional** — F-7's
shape is *an enumeration that forgot a path*, and declaring only the dispatch
order repeats it:

```
 R0–R7 identical, except R2 is N/A: the base is the stored, already-exact base_commit.
 G1'  worktree list --porcelain                 cwd=primary
        A MISSING REGISTRATION IS A PREPARE REFUSAL, NEVER A RE-MATERIALISATION.
        Re-materialising would run `worktree add` — the exec vector — after a
        previous worker has already written to this repository.
 G2'  (no B2 git command: §5.5.2C's raw chain verification)
 G3'  ls-tree / cat-file  ONLY IF the task has no persisted seal — and a seal
        that is absent while any run has ownership.json is SealAbsentAfterWorker,
        never a rebuild (§5.5.2A).
 G4'  rev-list --max-parents=0 HEAD             cwd=primary
 G5'  config --get remote.origin.url            cwd=primary
```

**FABLE REVIEW: the review path runs ZERO git commands before the reviewer
starts.** It reads persisted evidence. **Status: `REQUIRES-VERIFICATION` against
`server.py:1328-1500` by the implementer.** The requirement and its test are
declared here; **no lane read the whole review path, and stating it as measured
would be the F-7 error in a new place.**

**Why the order stops being prose — three mechanisms, and both of the last two
are required:**

1. **The order is data.** A Wave-0 module `git_order.py` declares, per path
   (`dispatch` | `resume` | `review`), an ordered list of
   `(position, subcommand, argv_shape_sha256, cwd_role, permitted_by_row, requires, conditional)`,
   where `requires` names the raw step that must precede it — `R6` for every git
   row, plus `R3`/`R4` for anything that opens a file inside the repository.
2. **The runtime interlock is the property.** `_run_git` reads the current
   `ToolExecution` (§3.1's contextvar-carried identity, Wave 0's by D-24) and
   raises `GitBeforeEstablishment` if no establishment marker has been recorded
   for this execution. **This is a refusal at the chokepoint, not a post-hoc
   assertion.**
3. **The journal is the audit.** `git-invocations.jsonl` gains a monotone `seq`
   per run, and R6 writes one non-git row:

```json
{"seq": 7, "phase": "PREPARE", "subcommand": "(raw-admin-establishment)",
 "argv_sha256": null, "cwd_role": "primary", "permitted_by": "§5.8.3",
 "returncode": null}
```

   `test_prepare_journal_matches_the_declared_order` asserts the PREPARE rows are
   a **prefix-preserving subsequence** of the declared order for that path —
   subsequence because G3/G8/G9 are conditional, but **no reordering and no
   unlisted row** — and that **every git row's `seq` exceeds the marker's**.

> **Why both (2) and (3).** With only the journal check, a mutant that moves
> *both* the marker and the command keeps their order and passes — **the marker
> is written by the same code the mutant is editing.** With the interlock,
> `_run_git` itself fails closed from state the mutant would also have to forge.
> **The interlock is the property; the journal is the audit.** This is the same
> shape as §5.4.5's *"the journal is only as good as the chokepoint"* box, and
> the same answer.
>
> **And the interlock is blind to `validation.py:228`**, which does not go through
> `_run_git` at all. That is not a gap in the interlock; it is §5.17's subject,
> and §19's vectors 7 and 8 exist to attack it.

**A.2B IS GENERATED, NOT MAINTAINED — and this is F-7's structural fix.**

> The four-surface matrix's row set is **generated** from the declared pre-worker
> order (all three paths) plus the FINALIZE set. **The acceptance report fails if
> any declared row has no measured row.** `test_declared_order_is_the_matrix_row_set`
> — **RED today**, because `--show-toplevel` is declared in revision 5's §5.4.3
> and absent from A.2B.
>
> **A hand-maintained matrix will drift again; a derived one cannot.** F-7 is
> discharged by *deleting* both of its missing rows rather than by measuring
> either, and the derivation rule prevents the class from recurring.

**`test_worktree_add_is_the_only_mutating_pre_worker_command`** replays the whole
declared order against a **read-only bind mount** of a throwaway repository and
asserts every declared pre-worker row except G4 is read-only. **COULD IT PASS
WHILE FALSE?** Yes if the mount is not actually read-only — so the test first
attempts a control write that **must** fail. **No existing test asserts this.**

#### 5.4.4 `git.py` splits

```
git.py            ONLY the permitted invocations, each a named function.
                  `_run_git` keeps the single-chokepoint role and gains the
                  argv/env policy. collect_diff_evidence, write_full_diff,
                  primary_tree_status and _fold_untracked are DELETED —
                  not wrapped, not deprecated. DELETED.
evidence/
  basetree.py     BaseTreeSnapshot          (ls-tree identity + SEALED bytes)
  seal.py         SealManifest, the CAS, Route A/Route B    [WAVE 0]
  headchain.py    resolve_head_raw — B2 with no git process [WAVE 0]
  attribution.py  the three deltas and the closure theorem  [WAVE 0]
  freeze.py       EvidenceFreeze                            [WAVE 0]
  git_order.py    the declared pre-worker order + interlock [WAVE 0]
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
state/tasks/<id>/runs/NNN/git-invocations.jsonl        append-only, monotone seq
  {"ts":…, "seq":11, "phase":"PREPARE", "subcommand":"ls-tree",
   "argv_sha256":"…", "cwd_role":"primary"|"task_worktree",
   "permitted_by":"G2", "returncode":0, "duration_ms":12}

state/tasks/<id>/runs/NNN/validation-invocations.jsonl  NEW, append-only
  one row per SPAWN ATTEMPT of a validation command  (§5.17)
```

Every call through `_run_git` appends one record to the **first** file. **The two
journals are disjoint by construction** — one is written by `_run_git`, the other
by `run_validation_command` — and `test_the_two_journals_are_disjoint` asserts no
`argv_sha256` appears in both.

> ### THE FINALIZE WINDOW OF `git-invocations.jsonl` IS EMPTY.
>
> **Zero rows.** Not "only `cat-file` and `rev-parse`". Zero.
>
> **PROVEN BY `test_finalize_journal_is_empty`.** **COULD IT PASS WHILE FALSE?**
> **No** for anything through `_run_git`; still yes for a bypass, which is what
> §5.4.6's runtime killer is for. **This test replaces
> `test_finalize_journal_is_catfile_and_b2_revparse_only`, and the replacement is
> strictly stronger: an empty set needs no argv pin and no seam counter to stay
> closed.** Both are deleted with it.

**Revision 5 called B2's post-worker `rev-parse` load-bearing and said it must
not be deleted to make a journal assertion pass — and that objection was
correct.** It is answered with a **mechanism, not a redefinition**: §5.5.2C
computes the same 40-hex answer from the sealed HEAD chain by raw file reads, and
**MEASURED, the raw form is not merely equivalent but strictly better** — under
S-ε variant C the `rev-parse` form returns a worker-chosen commit at `rc=0` with
every identity command legitimate, and revision 5's three B-1 conditions all pass
while it does, **because none of them pins the repository**.

**`ZM-A8` — *"delete B2's post-worker verification to make the journal test
pass"* — is RETIRED, and what replaces it is named.** There is no journal row to
make pass and no command to delete. The invariant B2 protects is unchanged and is
now guarded by **four** mutants instead of one: `Z8-M14` (compare `<gitdir>/HEAD`
bytes only — **MEASURED to be the passable-while-false version**), `Z8-M15`
(treat an absent loose ref as *skip*), `Z8-M16` (restore the post-worker
`rev-parse` fallback), `Z8-M18` (adopt the observed HEAD). **`ZM-A8`'s own killer
`test_worktree_head_moved_during_run_is_refused` is retained verbatim and merely
re-parameterised over both worktree forms**, so nothing it proved is lost.

> **THE JOURNAL IS ONLY AS GOOD AS THE CHOKEPOINT, AND THE CHOKEPOINT IS BROKEN
> TODAY — IN TWO PLACES, NOT ONE.**
>
> **(1) `validation.py:228`** is `await asyncio.create_subprocess_exec(*argv)`
> with a caller-supplied `argv[0]`. **It is not a git call site at all**, which is
> why it appears in no inventory, and it is the one that matters: a scan of
> `src/**` for the literal `"git"` **cannot enumerate a path whose argv comes from
> data.** See §5.17.
>
> **(2)** `git.py:776` — `write_full_diff` — calls
> `subprocess.run(["git", "diff", base_commit], stdout=<fd>, …)` **directly,
> outside `_run_git`**, because it streams to a file descriptor while `_run_git`
> uses `capture_output=True`. It uses `_git_env()` but not `_git_checked`'s
> taxonomy, and **any journal built from `_run_git` alone is blind to it.** This
> is a **live instance of mutant ZM-A5 already in the tree**, and §5.4.6's AST
> tests *as revision 4 specified them* would not have caught it: they scanned for
> git **subcommand strings** and for argv construction inside `_run_git`, not for
> a `subprocess` call whose first argv element is `"git"`.
>
> §5.4.4 already deletes `write_full_diff`. **The AST check is strengthened
> regardless**, because deletion removes today's instance and not tomorrow's
> (§5.4.6).

**The complete post-worker inventory at `d197bf0`, checked row by row against
what revision 6 does with it** (Z7 §4.1 supplies the `file:line`; the third
column is this design's answer):

| Site | argv | Eliminated by |
|---|---|---|
| `git.py:531` `worktree_head` (B2) | `rev-parse --verify HEAD^{commit}` | **§5.5.2C** — the raw HEAD chain |
| `git.py:385` `resolve_base_commit` (both paths) | `rev-parse --verify HEAD^{commit}` | **§5.5.2A** — `base_commit` is sealed at PREPARE and read from the manifest |
| `git.py:904` `primary_tree_status` ×2 | `status --porcelain` | **§5.9** — raw `FsSnapshot` equality |
| `git.py:652` `_fold_untracked` | `ls-files --others --exclude-standard` | **§5.6** — dispatcher-owned ignore evaluation |
| `git.py:678, 683, 699, 704, 722` `collect_diff_evidence` ×2 phases | `status`, `diff --name-only`, `diff --stat`, `diff`, `diff --check` | **§5.4.4, retained from revision 5** — DELETED from `src/**`, not wrapped |
| **`git.py:776`** `write_full_diff` | `["git","diff",base]` via **bare `subprocess.run`** | **§5.4.4** deletes it — **and §5.4.6's AST check is strengthened regardless, because deletion removes today's instance and not tomorrow's** |
| **`validation.py:228`** `run_validation_command` | **`*argv`, `argv[0]` caller-supplied** | **NOT ELIMINATED, AND IT MUST NOT BE.** §5.17 classifies and journals it as trusted validation, never authority |
| `runner.py:1428` | the `claude` spawn | it *is* the seam |

**Sixteen invocations on the success path, eighteen with the failure path, from
ten distinct `git.py` call sites. §16's `V-1` row and §17's Y-1 headline said
two, for the third revision running.** They are corrected in §16 and §17, in this
revision, **not deferred**.

> **"Post-worker" is the wrong boundary; "post-ANY-worker" is the right one.**
> `collect_repository_identity`, `validate_repository_root` and
> `lock_identity_for` are all nominally *pre*-worker — but **resume and review run
> in a repository a previous worker already owned.** F-5 makes this point about
> PREPARE step 0 on a resume; **it generalises to every "pre-worker" command on
> the resume and review paths**, and it is why §5.8.2B's deletion of
> `rev-parse --show-toplevel` matters even though that command is nominally
> pre-worker. Variant G is the live mechanism: `core.worktree` moves
> `--show-toplevel`, which decides **repository authorization** and the **lock
> digest**.

#### 5.4.6 Tests — and whether each could pass while the property is false

| Test | Proves | Could it pass while false? |
|---|---|---|
| `test_git_repertoire_is_exactly_the_permitted_set` (AST) | the source names no other subcommand | **YES** — a subcommand built from a variable defeats it. **Not sufficient alone.** |
| ~~`test_no_direct_git_subprocess_in_src`~~ — **REPLACED, because its predicate was over the ARGV** | revision 5 specified *"whose first argv element is the literal `"git"`"* | **IT IS GREEN WHILE `validation.py:228` IS LIVE** (F-4), and MEASURED (Z8 M2) **blind to five of six evasions**: `/usr/bin/git`, `["env","git",…]`, `["/bin/sh","-c","git …"]`, `shell=True`, `os.system`, `os.posix_spawn`. **A predicate over the argument cannot be the killer.** It is also, MEASURED (Z7 §4.2c), **not written**: no file under `tests/` matches that name |
| **(a) `test_no_spawn_in_finalization_call_graph`** (AST) — **the STATIC half, over the CALLEE** | builds the call graph of `src/**` rooted at every finalization entry point (evidence, B2, inventory, scope, primary-tree, patch/stat/check, review builder, landing transaction) and flags **every** call to `subprocess.run` / `Popen` / `check_output` / `check_call` / `os.system` / `os.popen` / `os.exec*` / `os.spawn*` / `os.posix_spawn` / `asyncio.create_subprocess_exec` / `asyncio.create_subprocess_shell` / `loop.subprocess_exec`. **A flagged call is a failure regardless of argv. No string matching on `"git"` anywhere in this test.** The only exception is a call inside a function decorated `@trusted_validation` (§5.17) | **NO** for a spawn reachable from a registered root, **whatever argv[0] is** — which is why it catches `validation.py:228` **and** `git.py:776`'s `stdout=<fd>` form. **YES in three named ways**, each of which is why the runtime half exists: a spawn reached through dynamic dispatch the AST cannot follow; a spawn in a module the root set does not reach because a new entry point was added and not registered; a spawn in a dependency rather than in `src/**`. **`test_finalization_entry_points_are_registered` guards the root set — and could itself pass while false if a stage is neither annotated nor reachable, which is exactly what the runtime half measures instead of asserting** |
| **(b) `test_post_worker_spawn_log_is_empty`** — **the RUNTIME half, fd-backed** | `sys.addaudithook` writing to an **inherited file descriptor** (`os.write`), installed before the run; asserts **ZERO** spawn events between the write of `runs/NNN/ownership.json` and the write of `runs/NNN/dispatcher-result.json`, other than those inside an explicitly bracketed `@trusted_validation` window | **NO for any in-interpreter spawn — MEASURED (Z8 M1/M2/M3) across eleven forms**, including `subprocess.run(stdout=<fd>)`, a **variable** `argv[0]`, `create_subprocess_exec`, **inside `asyncio.to_thread`** (thread `asyncio_0` — the `_verify_worktree_base` shape), `shutil.which("git")`, `["env","git",…]`, `shell=True`, `os.system`, `os.posix_spawn`, and **`os.fork()` + `os.execv`, which lands in the same log under a different pid with an fd sink and IS LOST with an in-memory list.** **This retires revision 5's `REQUIRES-PROBE`** on the audit hook, which was *"not verified against this codebase's `asyncio.to_thread` execution model"* — it is now verified for `to_thread` **and** `create_subprocess_exec`, the two forms the codebase actually uses. **YES in exactly three ways, stated rather than argued away:** a C extension that forks without raising audit events (**UNMEASURED**; no such dependency in `src/**`); a git process started by a *different* process the dispatcher launched (out of scope by construction, §5.17); and **a run whose finalization never reaches the code path under test** — closed by the same run asserting `dispatcher-result.json` exists and `changed-paths.json` carries a non-empty inventory, i.e. **the run really did finalize** |
| `test_all_git_argv_constructed_in_run_git` (AST) | no second construction site | **YES** for an indirection. Not sufficient alone; paired with the row above and the audit hook. |
| **`test_finalize_journal_is_empty`** *(replaces `test_finalize_journal_is_catfile_and_b2_revparse_only`, which was written against a set that is now empty)* | `git-invocations.jsonl` has **zero** FINALIZE rows after a complete run | **NO** for anything through `_run_git`. Still yes for a bypass — rows (a) and (b). **An empty set needs no argv pin and no seam counter, so there are two fewer things a mutant can edit** |
| **`test_the_two_journals_are_disjoint`** | for a run with a `git` validation command, no `argv_sha256` appears in both `git-invocations.jsonl` and `validation-invocations.jsonl` | **NO** for this shape. It is also the killer for a mutant that "hardens" validation by routing it through `_run_git` — **that the safety-*improving* mutant is killed too is deliberate: the change is a Sol decision (T-13), not a keyboard decision** |
| **`test_git_before_establishment_raises`** | with R6 stubbed to a no-op, every `_run_git` call raises `GitBeforeEstablishment`; with R6 present the same calls succeed | **NO** for anything through `_run_git`; **YES** for a bypass — which is F-4's hole, and why it is paired with row (b). **Do not merge this with rows (a)/(b): different window, different assertion, different mutants** |
| **`test_v1_filter_program_not_executed`** — **Z-RULE-1 positive control mandatory** | arms `$GIT_COMMON_DIR/info/attributes` + `.git/config` with a sentinel `filter.myf.clean`; **(b) runs the revision-2 hardened diff and asserts the sentinel FIRED**; (c) clears; (d) runs the production finalisation and asserts it did **not** | **NO.** Step (b) is what forecloses a mis-armed sentinel. **This is the test whose absence made S-1 shippable.** |
| `test_v1_fsmonitor_program_not_executed` | same shape, `core.fsmonitor` | as above |
| `test_v1_textconv_and_external_diff_not_executed` | same shape | as above |
| `test_v1_hooks_not_executed_during_finalisation` | same shape, arming **`reference-transaction`, `post-checkout`, `post-index-change`, `pre-auto-gc`** and `core.hooksPath` **by name** | as above. **`reference-transaction` is named because revision 3 omitted it and that omission produced B-2.** |
| **`test_repertoire_is_clean_on_all_four_surfaces`** | the **§5.4.3 PREPARE set**, re-run over the **generated** row set (§5.4.3B(d)), under each of S-α…S-δ armed separately, each pass carrying its own positive control that fires, under all three pins | **NO** for the four surfaces armed. **YES for a fifth surface nobody has armed** — revision 4 wrote that sentence about a fourth and a probe found one, then the fourth review found **S-ε, which is not an execution surface at all.** The safety argument for PREPARE is **enumerative with no structural fallback**; the residue is stated in §19 rather than argued away |
| **`test_alternates_written_mid_run_does_not_change_the_evidence`** — **Z-RULE-1B** | (a) **integrity control:** with the seal disabled, planting S-ε variant C mid-run **changes** the produced patch and the B2 answer, proving the decoy is genuinely consulted; (b) clear; (c) with the seal on, the same plant produces **byte-identical evidence** and lands `POLICY_VIOLATION` for the routing change | **NO — and step (a) is the reason.** Z-RULE-1's usual form does not apply because **nothing executes**. **A test asserting only "the real answer came back" would pass against a build where the decoy was never wired up** — the B-2 failure mode in a new form |
| **`test_refs_replace_is_neutralised_and_detected`** — **Z-RULE-1B** | (a) plant `refs/replace/<oid>` and run the read **without PIN 3**; assert it returns **FAKEBLOB** and that `rev-parse --verify HEAD^{commit}` returns the **expected SHA at `rc=0`**; (b) clear; (c) production: assert the sealed bytes are served, the run lands row 4, and `refs/replace/**` is named in the divergence | **NO.** Step (a) is what makes (c) mean anything, and asserting the *expected SHA at rc=0* in step (a) is what demonstrates the signature rather than merely a wrong answer |
| **`test_absent_base_object_executes_nothing`** *(new — the S-δ sentinel)* | deletes a base blob, arms `core.sshCommand` / `core.gitProxy` / an `ext::` remote; **(b) runs `cat-file --batch` WITHOUT `GIT_NO_LAZY_FETCH` and asserts the program FIRED and `rc == 0`**; (c) clears; (d) runs the production invocation under PIN 1 and asserts the program did **not** fire and the read **failed closed** | **NO.** Step (b) is load-bearing twice over: it forecloses a mis-armed sentinel **and** it demonstrates the silent `rc=0`. A version asserting only `rc != 0` at step (d) would pass against a build that fetched successfully. |
| **`test_base_tree_argv_has_no_long_flag`** *(new)* | AST + runtime assertion that `BaseTreeSnapshot`'s argv contains no `--long` | **NO** for the literal flag. **YES** if a size is obtained by some other absent-object read — which is why PIN 1 is global rather than local to this call site. |
| ~~`test_subprocess_audit_hook_accounts_for_every_git_child`~~ | superseded by row (b), which is fd-backed and fork-safe | its `REQUIRES-PROBE` is **RETIRED by measurement** (Z8 M1–M3) |

**The positive-control mutants for rows (a) and (b) are REQUIRED and are ordinary
rows in the mutation suite, not a prose promise.** Sol's directive names the
control explicitly: *adding `cat-file` or `rev-parse` to finalization must make
the killer fail.*

| Mutant | What it does | Which half must go red |
|---|---|---|
| **Z8-M28** `subprocess.run(["git","cat-file","-e",oid])` in the patch composer | literal-argv git spawn in finalization | static **and** runtime |
| **Z8-M29** `subprocess.run(["git","rev-parse","HEAD"], cwd=wt)` in the landing transaction | the classic B2 relapse | static **and** runtime |
| **Z8-M30** `subprocess.run([shutil.which("git"), …])` | **absolute-path argv[0]** — a literal-`"git"` predicate is **blind** (MEASURED) | static (callee-based) **and** runtime |
| **Z8-M31** `subprocess.run(prog + ["rev-parse"])`, `prog` a module variable | **variable argv[0]** — the `validation.py:228` shape | static (callee-based) **and** runtime |
| **Z8-M32** `subprocess.run(["git","diff",base], stdout=fh)` in evidence | **the `git.py:776` shape** | static **and** runtime |
| **Z8-M33** move a git call into a helper module **not in the AST root set** | reachable but unregistered | **runtime ONLY — and that is the point.** If this mutant is killed only by the runtime half, **the static half is not sufficient alone, which is stated here rather than discovered later** |
| **Z8-M34** delete the `@trusted_validation` bracket markers | breaks the subtraction | runtime (the log has unbracketed events) |
| **Z8-M35** annotate an evidence function `@trusted_validation` to silence the static half | **laundering authority as validation** | `test_trusted_validation_annotations_are_exactly_the_validation_module` (AST, pinned list of qualified names) **and** `test_validation_output_never_reaches_evidence` (seam) |

> **Do not merge the static and runtime halves into one test.** Z8-M33 is killed
> only by the runtime half; a merged test would hide which half is doing the work
> and the design would lose the ability to say so.

#### 5.4.7 Named mutants (directive A)

| Mutant | Named killer |
|---|---|
| **ZM-A1** re-introduce `git diff <base>` as the content source | `test_v1_filter_program_not_executed` (sentinel fires at step (d)) |
| **ZM-A2** re-introduce `git status --porcelain -z` for the inventory | `test_finalize_journal_is_empty` + `test_v1_filter_program_not_executed` |
| **ZM-A3** re-introduce `git diff --check` as a corroborating source | `test_check_findings_have_single_source` (asserts every finding's provenance is `dispatcher` **and** no `diff` row exists in the journal) |
| **ZM-A4** use `cat-file --filters` for the old side | `test_old_side_bytes_are_raw_blob` (clean/smudge rewrite content; the old side must equal the raw blob **and** the sentinel must not fire) |
| **ZM-A5** call `subprocess.run(["git", …])` outside `_run_git` — **live in the tree at `git.py:776`** | `test_no_spawn_in_finalization_call_graph` (AST, callee-based) **and** `test_post_worker_spawn_log_is_empty` (fd-backed). **Both are specified to be RED against `HEAD`** |
| **ZM-A6** move the §5.8 preflight to after `worktree add` | `test_unreconciled_admin_state_refuses_before_worktree_add` |
| **ZM-A7** run a second `rev-parse` variant post-worker | `test_finalize_journal_is_empty` + the runtime half |
| ~~**ZM-A8**~~ delete B2's post-worker verification to make the journal test pass | **RETIRED — the mechanism it guarded no longer exists** (§5.4.5). Replaced by `Z8-M14…Z8-M18`; its killer `test_worktree_head_moved_during_run_is_refused` is **retained verbatim and re-parameterised over both worktree forms** |
| **ZM-A12** *(new)* re-introduce `rev-parse --show-toplevel` in `validate_repository_root` | `test_no_show_toplevel_in_src` (AST) + `test_authorization_decides_before_any_git_process` (§5.8.2B) |
| **ZM-A13** *(new)* keep `realpath` **and** consult git, preferring git's answer on disagreement | `test_worker_written_gitfile_cannot_change_authorization` under **Z-RULE-1B** — **under the mutant the decoy wins, which is the only outcome that distinguishes it from the correct build** |
| **ZM-A11b** replace the identity producer with `diff --name-only -z` | `test_inventory_never_executes_a_worker_filter` — **measured to fire, so this mutant is killable, which it was not in revision 2** |

### 5.5 Directive B — the authority pipeline

#### 5.5.1 Shape, and the order is load-bearing

**Revision 5's pipeline had ten steps, no validation step in it at all, and
deferred the base content read past the worker on purpose.** That single
deferral was three blockers at once: it is what S-δ was aimed at (*"a blob the
lazy FINALIZE `cat-file` is guaranteed to read"*), what S-ε poisons (under
variant C the lazy `cat-file` returns the fake store's bytes **and the `ls-tree`
oid the design compares them against comes from the same poisoned store, so the
comparison agrees with itself**), and what F-3's laundering route depends on.
**The seal removes the deferral, and the ordering below is the whole of §8's and
§9's fix.**

```
── PREPARE ─────────────────────────────────────────────────────────────
 0. RAW ADMINISTRATIVE PREFLIGHT  (§5.8)     NO git process has run yet  [R6]
 1. verify the immutable base SHA            rev-parse         [G1, §4.14]
 2. BaseTreeSnapshot IDENTITY                ls-tree -r -z     [G2, no --long]
 3. materialise the task worktree            worktree add      [G4] ← the ONE
                                                                PREPARE exec vector
 4. RepositoryAuthoritySnapshot(role=pre_run) RAW FILE READS ONLY  (§5.5.2C)
 5. START FsSnapshot                         dispatcher-owned lstat/readlink/hash
 6. BaseReconciliation(2 vs 5)               dispatcher-owned; DECIDES the old side
 7. SEAL THE CONTENT                         Route A (free) + Route B [G8]
 8. seal-manifest.json written LAST, ATOMICALLY   ← the seal exists iff this does
── only now may a worker be launched ───────────────────────────────────
── worker runs ─────────────────────────────────────────────────────────
 9. worker reaped
10. RAW admin re-capture #1 + RAW B2 over the sealed HEAD chain  (§5.5.2C)
11. WORKER_EXIT = FsSnapshot                 ← state 2. NO git status.
12. worker_delta = delta(START, WORKER_EXIT) → PathIdentitySet
13. SCOPE + primary-tree policy                        (§8 rows 4, 5)
14. classification (lstat) → content from SEALED BYTES. NO git anything.
15. the WORKER canonical patch composed, hashed, WRITTEN, FSYNCED
16. evidence-freeze.json: sha256 of every evidence artefact   (§5.17)
── TRUSTED VALIDATION — THE EXECUTION DOMAIN (§5.17) ───────────────────
17. run_validations(envelope, worktree, config)
── after validation ────────────────────────────────────────────────────
18. POST_VALIDATION = FsSnapshot              ← state 3
19. RAW admin re-capture #2; evidence-freeze re-hash
20. validation_delta, final_delta, attribution.json
```

**Steps 2, 6, 7 and 8 happen ONCE PER TASK** and are **never re-created** — a
missing seal with any run's `ownership.json` present is `SealAbsentAfterWorker`,
**`FINALIZATION_FAILED`, never a rebuild** (§5.5.2A). Steps 5 and 9–20 happen
once per run.

> **Step 15 moving above step 17 is the whole of F-1's fix on the attribution
> side, and it is the one reordering that cannot be done later: once a validation
> command has run, the worker's bytes are gone.**
>
> **Steps 10 and 19 are TWO post-worker administrative captures, not one.**
> Revision 5 has one. With one capture you cannot tell whether the worker or a
> validation command planted the hook, and `attributed_to` is undecidable.

#### 5.5.2 Step 1–2 — the base tree, and the content hash IS the git blob oid

`resolve_base_commit` is **renamed `verify_base_commit`** — the name is part of
the fix, because *resolve* is what a symbolic ref needs and *verify* is what an
exact one needs (§4.14). Exact full-SHA equality, ancestry and merge-base
refused, unchanged.

> **`assert_worktree_base` no longer runs a git command.** Revision 5 ran it
> POST-WORKER at §8 row 2 (`server.py:2005` → `git.py:531` →
> `rev-parse --verify HEAD^{commit}` inside the task worktree) and called it the
> second of two post-worker git commands. **§5.5.2C replaces the command, not the
> check**: the invariant is unchanged, it still runs at row 2 before any evidence
> is collected, and it is computed from the sealed HEAD chain by raw file reads.
>
> **`git.py:520`'s docstring — *"`rev-parse` executed inside the worktree cannot
> be stale with respect to a HEAD that moved during a run"* — is DELETED as
> MEASURED FALSE**, and quoted in §10.3 so it cannot be re-derived. It was a
> claim about **staleness**, and S-ε is not a staleness attack; it is a
> **substitution** attack. **The claim was true about the failure mode it named
> and silent about the one that exists.**

```python
@dataclass(frozen=True)
class ContentRef:
    oid: str                       # 40-hex git-blob-sha1; IS the CAS filename
    size: int                      # measured from the SEALED BYTES, never asked of git
    source: Literal["start_walk", "cat_file_batch"]     # which route sealed it

@dataclass(frozen=True)
class SealedTreeEntry:             # replaces TreeEntry
    path: bytes                    # repo-relative, RAW bytes
    mode: int                      # 0o100644 | 0o100755 | 0o120000 | 0o160000
    kind: Literal["blob", "symlink", "gitlink"]
    oid: str                       # from ls-tree — provenance identity
    content: ContentRef | None     # None IF AND ONLY IF kind == "gitlink"

@dataclass(frozen=True)
class BaseTreeSnapshot:            # SAME NAME
    schema_version: int
    base_commit: str
    entries: tuple[SealedTreeEntry, ...]   # sorted by RAW path bytes ascending
    total_content_bytes: int
    sealed_count: int
    gitlink_count: int
    complete: Literal[True]        # THERE IS NO PARTIAL BaseTreeSnapshot
    captured_at: str; duration_ms: int
```

**`blob_size` is DELETED rather than kept as `int | None`.** Revision 5
introduced `int | None` to carry `--long`'s removal; with the seal, size is
measured from the sealed bytes and is never absent. Any consumer reading
`blob_size` reads `ContentRef.size`. **`test_base_tree_argv_has_no_long_flag` is
retained** — it still guards the argv, and `--long` is still what arms S-δ.

**`complete: Literal[True]` is deliberate and load-bearing:** the type system
carries the *"no partial snapshot"* rule that revision 5 stated in prose. **A
partial seal cannot be represented; it can only be absent.**

**DECISION Z-5 — the content hash is the git blob object id.**

```python
def git_blob_oid(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
```

Verified byte-exact against `git ls-tree` for a normal file, an **empty** file, a
file with **no trailing newline**, and a **symlink** (where the blob is the raw
target bytes, so `os.readlink` in bytes mode feeds the same function). Four
cases, four exact. Adopted from Z3 and independently verified by Z1.

Consequences: base-vs-filesystem comparison is a **string compare of two object
ids**, and one hash serves both the base-comparison axis and the START↔POST axis.

> **DECISION Z-5's laziness is REVERSED.** Revision 5 concluded that because the
> `ls-tree` oid *is* the hash, `cat-file --batch` could come off the PREPARE hot
> path and be *"invoked lazily at FINALIZE, for the old side of changed paths
> only"*, removing a 22.6 MB read from every dispatch. **That was the design's
> own performance win and it was also the target of two attacks and the enabler
> of a third.** §5.5.2A reads the bytes at PREPARE instead. **The identity
> argument survives intact and is what makes Route A free; only the deferral is
> withdrawn.**

sha1 runs at 200 MB/s here against blake2b's 301: on the production task worktree
(22.6 MB) that is 113 ms vs 75 ms — **38 ms for removing an entire read pass and
for direct interoperability with git's own identity. Worth it.** sha1 is used as
a *content identity function interoperable with the object store*, never as a
security primitive; a collision attack would have to produce a file whose git oid
matches the base blob, which is the assumption git already makes about the
repository. **Recorded, not hidden.**

**Parsing `ls-tree -r -z`, precisely.** Records are NUL-terminated. Within a
record, split on the **first** `0x09`: head is `<mode> SP <type> SP <oid>` —
**and `SP <space-padded-size>` only when `--long` was deliberately requested**,
which the default argv does not do — tail is the **raw path**.
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

#### 5.5.2A The seal — identity AND exact content bytes, before the worker exists (Sol §2)

> ### INVARIANT ZI-54 — THE SEAL IS COMPLETE BEFORE THE WORKER EXISTS
>
> During trusted PREPARE, before any Claude process is created, the dispatcher
> creates and persists four artefacts **under dispatcher-owned state outside the
> target repository**, each covered by a persisted manifest hash:
>
> | Artefact | What it freezes |
> |---|---|
> | `RepositoryAuthoritySnapshot` | which repository, gitdir, common dir, store and HEAD chain this task is about (§5.5.2C, §5.8) |
> | `BaseTreeSnapshot` | every base path's identity **and its exact content bytes** |
> | `StartFilesystemSnapshot` | the task worktree as it was handed to the worker |
> | `PrimaryStartSnapshot` | the primary tree and its own base identity, pre-worker (§5.9) |
>
> **`BaseTreeSnapshot` must contain enough to generate every later piece of
> evidence without querying git again. No later requirement to call `cat-file`
> for the old side is left standing.**
>
> **If complete base material cannot be obtained during PREPARE: REFUSE BEFORE
> THE WORKER.** No run index consumed, `state.json` byte-identical,
> `refusals.jsonl` row written — §8 row 0.

**Layout.** The seal lives in the existing once-per-task, immutable
`materialisation/` directory (§5.11B), which already holds `base-tree.json`,
`base-reconciliation.json` and a content-addressed `start-bytes/`. **The seal
generalises `start-bytes/` into one store and adds the manifest.**

```
state/tasks/<task-id>/materialisation/       0700, once per task, IMMUTABLE
  seal-manifest.json          NEW    the root of trust for everything below
  repo-authority.json         NEW    RepositoryAuthoritySnapshot
  base-tree.json              EXT    BaseTreeSnapshot + content_ref per entry
  base-reconciliation.json    =      BaseReconciliation (unchanged shape)
  primary-start.json          NEW    PrimaryStartSnapshot
  fs-snapshot-start.json      MOVED  from runs/NNN/ — it is per-TASK, not per-run
  cas/<oid[:2]>/<oid[2:]>     EXT    was start-bytes/<hash>.bin; ONE store now,
                                     keyed by git-blob-sha1, 0600 inside 0700
```

**Two routes, and the cheap one is the common one.**

**Route A — from the START walk, no git at all.** Step 5 already opens and
`git-blob-sha1`-hashes every regular file and every symlink target in the task
worktree. For every path where the START hash **equals** the `ls-tree` oid from
step 2, **the bytes on disk ARE the base blob** — that is precisely what DECISION
Z-5's identity means. Those bytes are written into `cas/` from the same read. **No
`cat-file`. No second read.**

**Route B — one bulk `cat-file --batch`, pre-worker, for the remainder.** Every
path where START ≠ base oid (`BaseReconciliation.diverged`), every path absent
from the working tree, and every path Route A could not read, is fetched by
**one** `cat-file --batch` process fed the oid list on stdin, under **PIN 1** and
**PIN 3**, at `cwd_role="primary"` (row G8).

> **MEASURED — the writer must run on its own thread.** A single-threaded
> write-then-read against `cat-file --batch` **deadlocks on the pipe buffer** for
> any non-trivial tree. Both probes that implemented Route B hit this. It is
> recorded here because it is an implementation trap that looks like a hang, not
> a bug.

**Both routes verify.** Every blob written to `cas/` is verified
`sha1(b"blob %d\0" % len(data) + data).hexdigest() == oid` **before** the CAS
entry is published. A mismatch is `BaseObjectVerificationFailed`; an absence is
`BaseBlobUnreadable`; **both are PREPARE refusals and they are different codes on
purpose — "the bytes were wrong" and "the bytes were absent" must not be
collapsed.** The CAS is self-describing: **the file's name is its own hash, so a
later reader re-verifies without trusting the manifest alone.**

**Hardlinks and reflinks are PROHIBITED.** A hardlink from `cas/` into the
worktree would let the worker mutate the sealed bytes through the worktree path.
**This is the obvious optimisation to reach for**, so it is stated as a
prohibition with a named killer: `test_cas_entries_are_not_hardlinked_to_the_worktree`
asserts `st_nlink == 1` and `st_ino` inequality for every CAS entry. **COULD IT
PASS WHILE FALSE?** No for hardlinks; **yes for a reflink on a CoW filesystem**,
where `st_ino` differs and `st_nlink == 1` and the blocks are still shared —
**but a reflink is copy-on-write, so a worker write to the worktree file does not
alter the CAS entry.** Recorded because the test's *reason* would otherwise be
misread. Reflink is **UNMEASURED on this host's filesystem** and is not adopted.

**The manifest.**

```python
@dataclass(frozen=True)
class SealManifest:
    schema_version: int
    task_id: str
    base_commit: str
    sealed_at: str                    # ISO-8601, dispatcher clock
    sealed_before_pid: int | None
    artefacts: tuple[SealedArtefact, ...]     # (relpath, sha256, size) per file
    cas_root_hash: str                # sha256 over sorted (oid, size) pairs
    manifest_hash: str                # sha256 over the canonical encoding above
```

`cas_root_hash` covers the store **by identity, not by re-reading 24 MB** — each
CAS entry is separately self-verifying by filename, so a full re-hash is a
**diagnostic** (`scripts/verify-seal.py`), not a hot path.

**The manifest is written LAST and atomically, so the seal exists if and only if
the manifest exists.** `test_manifest_is_written_last` is an AST guard over the
seal module's statement order; `test_partial_seal_without_manifest_is_absent`
kills during CAS population and asserts the next PREPARE treats the seal as
absent and rebuilds.

#### 5.5.2A(i) The seal is PER-TASK and is NEVER recreated

This is the clause that closes F-5's resume hole — *"PREPARE step 0 on a fresh
dispatch is safe … on a resume it is not: run 1's worktree already exists, and
run 2's step-0 capture resolves through whatever run 1's worker left in that
worktree's `.git`."*

> **On run 2 and every later run the dispatcher does NOT re-seal. It LOADS the
> existing seal and verifies it against `seal-manifest.json`.**
>
> A missing seal while any run has `ownership.json` is **`SealAbsentAfterWorker`
> → `FINALIZATION_FAILED`, never re-created.** Reconstructing a pre-worker seal
> after a worker has run is the same laundering §15.4 already forbids for the
> START snapshot, and it is forbidden here for the same reason and by name.
>
> A seal whose manifest does not verify is **`SealIntegrityFailed`**: a
> **PREPARE refusal** when no worker ever ran for this task, and
> **`POLICY_VIOLATION` at §8 row 4** when one has — worker-attributable damage to
> evidence authority. The two cases are distinguished by the existence of any
> `runs/*/ownership.json`, which is durable and is written only from a
> `WorkerHandle`.

`fs-snapshot-start.json` **moves from `runs/NNN/` to `materialisation/`** to make
this structural rather than conventional: there is one START snapshot per task, in
the immutable directory, and **no per-run location for a second one to appear in.**

#### 5.5.2A(ii) The primary side is IDENTITY-ONLY, and that is a costed decision

`PrimaryStartSnapshot` seals the primary `FsSnapshot(role="primary_pre")`, the
primary `GitAdminSnapshot`, the primary's **raw** HEAD chain, and the primary's
own base tree **identity only** — `(path, mode, kind, oid)` per entry, **no
content bytes**.

**Why identity is sufficient there.** §5.9.2's primary invariant compares
`primary_pre` against `primary_post` — snapshot against snapshot, needing no base
content at all. The primary base tree is needed only for the `ignored_by_base`
classification, which is a **path-set** question, and for §5.9.5's re-derived
`porcelain_status`, which compares an `FsSnapshot` content hash against an
`ls-tree` oid — **two identities, no bytes.**

**Cost avoided, with the numbers.** The primary tree is 46,565 entries / 789.9 MB
on the filesystem; its **tracked** set is 584 entries / 22.6 MB. Sealing primary
identity is one `ls-tree`. Sealing primary **content** would be a second 24 MB
copy for no consumer. **If a future section acquires a consumer for primary base
bytes it must SEAL them; it may not reach for `cat-file` at FINALIZE.** That rule
is stated now so the next revision has a marker.

#### 5.5.2A(iii) `old_side(p)` — the lazy branch is deleted

```
revision 5:
old_side(p) = start-bytes[p]        if p in reconciliation.diverged
              raw blob(base_oid[p]) elif p in base_tree   ← LAZY cat-file, FINALIZE
              /dev/null             otherwise

revision 6:
old_side(p) = cas[reconciliation.captured_ref[p]]  if p in reconciliation.diverged
              cas[base_oid[p]]                     elif p in base_tree
              /dev/null                            otherwise
```

**Both branches are CAS reads. Neither is a git command.**
`test_resume_old_side_is_base_not_run1` is retained verbatim and still passes;
**`ZM-B3`** (*"capture `start-bytes` lazily at FINALIZE"*) **widens to cover base
bytes too.**

#### 5.5.3A The fail-closed PREPARE budget — and the cliff is NOT where the design would look for it

**Sealing is cheap and linear. MEASURED (Z7 §2.2, `full-voice-agent`, 584
entries / 22.6 MB, three runs each):**

| strategy | stores | `t_seal` | on-disk |
|---|---|---|---|
| `hash` | identity only, **no content** | 0.287–0.377 s | 0 |
| **`raw`** | **content bytes in a CAS keyed by blob oid** | **0.732–1.075 s** | **23 220 224 B** |
| `zlib` | zlib-6 in the same CAS | 0.726–1.967 s | 4 317 184 B |
| ~~`packfile`~~ | `pack-objects --revs --stdout` | 4.65–5.05 s | ~4.3 MB |

`t_ls_tree` is 0.018–0.079 s in every run and **is never the cost**. A
task-scoped subtree (`Kavya/`, 170 entries, 4.4 MB) is **75 ms**. Scaling:
**40 000 entries / 163 MB → 5.06 s**, fitting
`t_seal ≈ N × 100 µs + B / 140 MB/s`.

> **`git pack-objects` is RULED OUT as an immutable content object.** Three
> identical runs of the identical command on the identical tree produced **three
> different byte counts** (4 385 122 / 4 376 047 / 4 325 452). **A packfile is not
> byte-reproducible, so it cannot carry a stable identity.** It is also the
> slowest option by 5×. Content bytes or an oid-keyed CAS only.
>
> **`zlib` buys 5.4× disk for no reliable time saving** and is strictly worse at
> scale (788 MB: 5.68 s raw vs **9.97 s** zlib). **This is a policy choice, not a
> correctness one**; both satisfy Sol §2. *(Escalated as **T-12**.)*
>
> **The fitted model UNDER-PREDICTS `full-voice-agent` by 3×** (0.22 s predicted,
> 0.73 s measured) because the synthetic repositories are all **loose** objects
> while production has 1311 objects in 6 packs and `cat-file` must reconstruct
> deltas. **Seal cost depends on the pack/delta state of the store, not only on
> tree size, so a budget keyed purely on bytes will be optimistic on a
> well-packed repository.**

> ### THE CLIFF IS IN REGENERATION, AND NO DRAFT BUDGETED FOR IT
>
> Sol §2 requires the snapshot to contain enough to generate **all** later
> evidence without querying git again. Regenerating it in pure Python is where
> the design falls over, and **the key is LINES PER CHANGED BLOB — not bytes, not
> entry count, not tree size.**
>
> | changed file | base bytes | base lines | `git diff` | `difflib.unified_diff` |
> |---|---|---|---|---|
> | `graphify-out/GRAPH_REPORT.md` | 192 904 | 2 687 | 0.016 s | 0.140 s |
> | `graphify-out/manifest.json` | 89 882 | 2 382 | 0.015 s | 0.479 s |
> | **`graphify-out/graph.html`** | **6 393 727** | **305** | 0.145 s | **0.012 s** |
> | **`graphify-out/graph.json`** | **6 445 536** | **187 085** | **1.696 s** | **>100 s ABORTED** |
>
> **`graph.html` is the control that makes this a finding rather than a size
> effect: it is the SAME 6.4 MB and it diffs in 12 ms, because it has 305 lines.**
>
> **And it cannot be tuned away.** Three mitigations, measured on the same file:
> interning lines to integers → **>90 s aborted**; `autojunk=True` → **>90 s
> aborted**; common prefix/suffix trimming → **>90 s aborted**, because the common
> prefix is **3 lines**. `difflib` is Ratcliff/Obershelp; git uses Myers over
> hashed lines. **The cliff is inherent to the algorithm, not to its input
> representation.**
>
> ### **A dispatcher-owned Myers or histogram differ is REQUIRED, not preferable.**
> Tuning `difflib` is not an option. *(Escalated as **T-14**.)*

**A second, independent cliff, measured accidentally and worth keeping.** The
first regeneration run walked the working tree with `os.walk` and blew a
two-minute budget on `full-voice-agent`, because the untracked `.venv` is in the
tree. **The filesystem side of the comparison must be bounded by the sealed path
set plus an explicitly evaluated ignore set, never by a naive walk.** Today that
bound comes from `git ls-files --others --exclude-standard` (`git.py:652`), which
this design **deletes** — so **the dispatcher must own ignore-rule evaluation**
(§5.6.4), and that obligation is a *consequence of the deletion*, not an
independent nicety.

```toml
[evidence]
seal_max_entries              = 250_000     # aligns with snapshot_max_entries
seal_max_content_bytes        = 2_000_000_000
seal_max_duration_ms          = 30_000      # ~30x the 5.06s worst measured point
seal_free_space_headroom      = 4.0         # required free bytes / seal bytes
regen_max_lines_per_blob      = 50_000      # B-REGEN-1 — THE ONE THAT FAILS FIRST
```

**Three budgets, checked at three different moments:**

| # | Budget | Keyed on | When it is checkable |
|---|---|---|---|
| B-SEAL-1 | seal wall time | `N × 100 µs + bytes / 140 MB/s`, ×3 for packed stores | after `ls-tree`, **before any `cat-file`** — both inputs are in the `ls-tree` output |
| B-SEAL-2 | seal disk | `Σ size`, against free space (**3.0 GB free on this host**) | the same moment |
| **B-REGEN-1** | **max lines in any single sealed blob that may later be diffed** | line count per blob | **during the seal — the bytes are in hand and counting `\n` is free** |

> **B-REGEN-1 is the budget the design did not have and the one that fails
> first.** A tree can be small in every other dimension and still contain one
> minified 187 000-line JSON artefact. **Z8's draft carried
> `seal_max_duration_ms = 120_000` and labelled it PROVISIONAL at ~600× the
> measured production cost — safe, but not designed. It is replaced above by
> Z7's measured model, and this paragraph records that it was a placeholder so
> that "it was always 30 s" is not inferred later.**

Exceeding any bound raises **`SealBudgetExceeded`** — a **PREPARE refusal**: no
worker launched, no run index consumed, `state.json` byte-identical, with the
measured counts and the bound in `refusals.jsonl`. **The operator learns the
repository is too large before spending a worker.** A blob over
`regen_max_lines_per_blob` whose path is inside the task scope is the same
refusal; outside the scope it is sealed and marked `regeneration_capped`, and any
later attempt to diff it is `patch_file_complete = False` with
`omission_reason="regeneration_capped"` — **fail-closed and honest, never a
silent truncation.**

**The disk cost is real and must be in the gate report.** The seal is a full
second copy of the base tree per task: **22.6 MB per task** on production; ten
tasks is 226 MB under `state/`. `seal_free_space_headroom` makes running out of
disk a PREPARE refusal rather than a truncated seal.

#### 5.5.2B Promisor / partial clone — materialised before launch (Sol §3)

> ### INVARIANT ZI-55 — EVERY BASE OBJECT IS MATERIALISED LOCALLY BEFORE LAUNCH
>
> Every object the base tree names is present in the local object store and has
> been read into the seal **before** the worker is created. **There is no lazy
> object retrieval after launch, because there is no object retrieval after
> launch at all.**
>
> If PREPARE cannot fully materialise and verify the base set, **the dispatch is
> refused with a typed PRELAUNCH refusal. No worker is created.**

**The sequence, from Z7's measurement, and step 4 is not optional:**

```
1. RAW precondition check, NO git process:
     extensions.partialClone / remote.*.promisor in config, any objects/pack/*.promisor,
     and remote.*.url  — all four readable by open() + glob.
     The remote URL is in the same read, and it is the thing that becomes an
     `ext::` execution vector, so it must be SEEN before anything can fetch.
2. ENUMERATE   GIT_NO_LAZY_FETCH=1 git rev-list --objects --missing=print HEAD   [G9]
3. MATERIALISE explicit `git fetch --no-tags --no-write-fetch-head origin <oids>`
4. RE-VERIFY   step 2 again. ONLY `missing == 0` may proceed.
5. SEAL        §5.5.2A. After the seal the promisor state is irrelevant.
```

**Step 4 is not implied by step 3: a fetch can partially succeed.** Measured
materialisation strategies: `rev-list --missing=print` → explicit fetch (0.148 s,
missing→0) · `git checkout` (0.121 s, missing→0) ·
`-c remote.origin.partialclonefilter= git fetch --refetch` (0.107 s, missing→0) ·
`git fetch --refetch --filter=` **fails**, `fatal: invalid filter-spec ''`.

**Fail-closed is available and cheap**, and this is the row that matters:
`git fetch` returns **128** while the verifier still returns **0** with a
non-empty missing list, **so PREPARE can distinguish "materialisation failed"
from "the verifier failed" — a distinction a bare `cat-file` rc=128 cannot
make.**

**Detection of partial-clone configuration is additional, not primary.**
`repo-authority.json` records `extensions.partialClone`, `remote.*.promisor`,
`remote.*.partialclonefilter` and `remote.*.url` from the **raw** config text and
prints them to the operator at trust time. **Their presence alone is NOT a
refusal** — a fully hydrated partial clone seals fine, and refusing on
configuration rather than on the measured outcome is exactly the *"disarm the
configuration rather than the fetch"* mistake PIN 1's own measurement already
falsified.

> **The closure is the seal, not the detection.** Stated that way round on
> purpose: **a future revision that adds a promisor key to a denylist and deletes
> the seal has removed the mechanism and kept the decoration.**
>
> **`git gc --prune=now` after materialisation left `missing=0`** — the objects
> are reachable so gc keeps them — while `remote.origin.promisor` remained
> `true`, so the *capability* to re-absent an object survives. **Under ZI-51 that
> is moot: once PREPARE has sealed the content bytes, no later read consults the
> store. This is the clearest case in the document for Sol's structural answer
> over an enumerated one — the promisor surface is not mitigated, it is made
> unreachable.**

**PIN 1 is still REQUIRED and is not part of this closure.** It guards row G8,
which is a **live `cat-file --batch` over every base oid** — the single largest
object-store read the dispatcher performs, **moved earlier rather than removed**.
Without PIN 1, Route B on an absent object fetches and executes a worker-named
transport program. **Sealing moved the invocation; it did not make it safe.**
Mutant **Z8-M10** (*"drop PIN 1 because the seal makes it unnecessary"*) and
**Z8-M27** (the same for PIN 2) exist because that is a genuinely tempting
simplification and nothing else in this document forbids it.

#### 5.5.2C B2 without a git command — the sealed HEAD chain (Sol §5)

> ### INVARIANT ZI-56 — THE WORKTREE HEAD CHAIN AND THE `.git` INDIRECTION ARE PROTECTED, IMMUTABLE DISPATCHER AUTHORITY
>
> **§5.8.3's exceptions for `worktrees/sol-<id>/{HEAD, gitdir, commondir}` are
> DELETED.** There is no allowlist (§5.8).
>
> Before launch the dispatcher records — **raw** — the worktree `.git` bytes, the
> resolved gitdir, the `commondir` bytes **and** its resolution, the gitdir
> back-pointer, **every file on the HEAD resolution chain**, and the expected
> exact 40-hex base SHA. After the worker it verifies those exact bytes and
> identities **using raw filesystem reads only. No `rev-parse`. No git process of
> any kind.**
>
> **The dispatcher NEVER adopts observed state.** The expected value is the one
> recorded at `worktree add`. There is no path on which a mismatch is resolved by
> believing the file.

##### Sol's directive is FALSIFIED as literally written, and is corrected rather than silently satisfied

Sol §5 directs recording *"gitdir `HEAD` bytes · expected exact 40-char SHA"* and
verifying *"those exact bytes."* **MEASURED, with the dispatcher's actual argv
(`git.py:608`, `worktree add --quiet -b <branch> <path> <sha>`):**

```
after worktree add:
  <gitdir>/HEAD        = "ref: refs/heads/sol-abc\n"   ← NOT 40-hex, ever
  refs/heads/sol-abc   = "<base sha>\n"                ← the value lives HERE

--- worker runs `git commit` inside the worktree ---
  <gitdir>/HEAD        = "ref: refs/heads/sol-abc\n"   ← BYTE-IDENTICAL
  refs/heads/sol-abc   = "<worker sha>\n"              ← MOVED
```

> **A B2 that compares only `<gitdir>/HEAD` bytes against an expected 40-hex
> would pass while HEAD had moved to the worker's own commit — the exact defect
> B2 exists to catch. Sol's §5 as literally written contains that trap.**
> Independently confirmed by Z7, which observed the *form* change (sealed symref
> → attacker's detached oid) **before any value comparison**.

**And a second measurement makes the naive fix wrong too.** A worker running
`git pack-refs --all` — its own git, in its own worktree, and **not in
`CORE_DENIED_GIT_OPERATIONS`** — **deletes the loose ref file** while the value is
unchanged and now lives in `packed-refs`. **A raw byte comparison of the sealed
loose ref sees ABSENT** and would either report a violation that did not happen
or, if implemented as *"absent ⇒ skip"*, silently drop the check.

**So the sealed object is the CHAIN and the invariant is over the RESOLVED VALUE.**

```python
@dataclass(frozen=True)
class HeadChainLink:
    kind: Literal["head_file", "loose_ref", "packed_refs", "terminal_sha"]
    path: bytes                  # absolute, RAW
    present: bool
    raw_bytes: bytes | None      # None iff not present
    sha256: str | None

@dataclass(frozen=True)
class HeadChain:
    links: tuple[HeadChainLink, ...]   # resolution order, <= 5 symbolic hops
    refname: bytes | None              # b"refs/heads/sol-abc"; None if detached
    resolved: str                      # 40-hex, ^[0-9a-f]{40}$
    resolution: Literal["detached", "loose", "packed"]
```

**`resolve_head_raw(gitdir, common_dir) -> HeadChain`** — plain `open()`/`stat()`,
no git process, the same reader §5.9.2 specifies for the primary, generalised to
a linked worktree and made to record its chain:

```
1. h = read(gitdir/"HEAD")                             link kind="head_file"
2. exactly 40 hex + optional LF        -> resolution="detached", done
3. starts b"ref: ":
     refname = h[5:].strip()
     REFUSE unless refname matches ^refs/[A-Za-z0-9._/-]+$
       and contains no b"..", no b"//", no b"\\", no leading/trailing b"/",
       and no component beginning b"."
       -- MEASURED: git itself refuses `ref: refs/heads/../../../tmp/evil`
          with `fatal: ambiguous argument 'HEAD'`, rc=128. The raw resolver
          REFUSES THE SAME SHAPES rather than following them.
     look in gitdir/refname   (per-worktree: refs/bisect, refs/worktree, refs/rewritten)
       then common_dir/refname                          kind="loose_ref"
     if neither exists: scan common_dir/"packed-refs"   kind="packed_refs"
       (hash the WHOLE file as the link; parse only the matching line;
        an unparseable line is fail-closed)
     the value may itself be b"ref: " -> hop, max 5 hops
4. terminal must match ^[0-9a-f]{40}$ else RefResolutionFailed (fail closed)
5. record EVERY file consulted, present or absent, as a link.
```

**The post-worker comparison, raw:**

| Check | Rule |
|---|---|
| `worktree_gitfile.raw_bytes` | must equal the sealed bytes exactly. Change ⇒ `WorktreeIndirectionChanged` |
| `commondir_file.raw_bytes` **and** the resolved `common_dir` | **both.** MEASURED: `commondir` is **relative** (`../..\n`), so comparing only the resolved path misses a rewrite that resolves to the same place by a different route, and comparing only the bytes misses a change of the anchor |
| `gitdir_file.raw_bytes` (`<gitdir>/gitdir`) | must equal the sealed bytes — the back-pointer git uses to prune |
| `head_chain.resolved` | must equal the sealed `resolved`, which must equal the base SHA `worktree add` was given |
| `head_chain.refname` | must equal the sealed refname (or both `None`) |
| every `HeadChainLink` | compared as `(present, sha256)`. A link whose `present` or `sha256` changed **while `resolved` is unchanged** is **`head_chain_restructured`** — reported and enumerated, and row 4 **only if it is attributable to a worker-written protected file** |

**`head_chain_restructured` is the one place this section chooses report over
refuse, and the reason is measured, not assumed:** `pack-refs` shows a
value-preserving restructure is reachable by an ordinary git command in the
worker's own worktree, and landing `POLICY_VIOLATION` on it would make the flag
routine — the failure §5.9.4 names.

**`ZM-A9`'s tempting single-sided test is named:** `Z8-M15` (*treat an absent
loose ref as "unchanged, skip"*) is killed by
`test_pack_refs_does_not_produce_a_false_violation` **and** a companion in which
the packed value **differs**, `test_pack_refs_with_a_moved_value_is_a_mismatch`.
**One without the other is not a killer: the first alone is passed by an
implementation that skips the check.**

**The `rev-parse` fallback is DELETED for the post-worker path.** §5.8.2A permits
a fallback to `rev-parse --absolute-git-dir` / `--git-common-dir` where the raw
resolver cannot decide, recording `resolver="rev-parse-fallback"`.

- **PREPARE: RETAINED** (row G10) — it runs before any worker exists, after
  §5.8's gate, and is measured clean on four surfaces.
- **POST-WORKER: DELETED.** `RepositoryAuthoritySnapshot.resolver` is typed
  `Literal["raw"]` for `role="post_run"` — **the fallback cannot be
  represented.** A layout the raw resolver cannot decide post-worker is
  `RepositoryLayoutUnreadable` ⇒ verdict `unknown` ⇒ **treated as mismatch, never
  as held.**
- **Consequence, stated:** a repository layout that needs the fallback can be
  dispatched but its run lands `FAILED` at finalisation. **That is a real
  usability cost and it is the correct direction** — the alternative is a
  post-worker `rev-parse` whose answer S-ε chooses.

**`worktree-base.json` keeps its name and its `expected_base_commit` field** and
becomes:

```python
@dataclass(frozen=True)
class WorktreeBaseRecord:
    schema_version: int
    expected_base_commit: str            # from `worktree add`, NEVER re-derived
    created_argv_sha256: str
    pre:  RepositoryAuthoritySnapshot    # role="pre_run"  — sealed
    post: RepositoryAuthoritySnapshot | None   # None ⇒ NOT MEASURED
    verdict: Literal["base_held","base_mismatch","indirection_changed","unknown"]
    head_chain_restructured: bool
    differences: tuple[AuthorityDifference, ...]   # field, before_sha256, after_sha256
```

**`verdict="unknown"` is treated as mismatch, never as held** — the same rule
§5.12 applies to `GitAdministrativeCaptureFailed`.

**Row ordering, because it looks wrong until it is explained.**
`WorktreeIndirectionChanged` lands at **row 4** and `WorktreeBaseMismatch` at
**row 2**, so an indirection change is evaluated *after* a base mismatch. That is
correct: if the base moved, **no evidence is collected at all**, so there is
nothing to protect; if the indirection changed but the sealed chain still resolves
to the base, the run **does** produce evidence — from the seal — that evidence is
sound, and the run must reach row 4 to be judged. **Neither verdict is laundered
into the other.**

**Tests, and the parameterisation that is load-bearing:**

| Test | Proves | Could it pass while false? |
|---|---|---|
| `test_worktree_head_moved_during_run_is_refused` *(ZM-A8's killer, retained verbatim)* | a fake worker checks out another commit inside its worktree; the run lands `FAILED` with `WorktreeBaseMismatch` **before any evidence exists** | **YES as revision 5 specified it.** It **must** be parameterised over **both** worktree forms — `--detach` (HEAD is 40-hex) and **`-b` (HEAD is symbolic and the value is in the ref)** — **and the `-b` case must be the one that fires.** Without that parameterisation it cannot distinguish a correct chain resolver from one that compares HEAD bytes |
| **`test_worker_commit_moves_the_ref_and_is_caught`** | the `-b` case explicitly: a worker `git commit` leaves `<gitdir>/HEAD` byte-identical and moves `refs/heads/sol-<id>`; B2 must fire | **NO.** This is the measurement turned into a test, and it is the one a HEAD-bytes-only implementation fails |
| `test_b2_runs_no_git_command` | the fd-backed spawn log is empty across the B2 window | **NO** for in-interpreter spawns |
| `test_gitfile_repointed_mid_run_is_policy_violation` | S-ε variant A: evidence is still produced from the seal and is **byte-identical**; verdict `POLICY_VIOLATION` | **YES if the fixture's fake repository happens to produce the same evidence anyway.** The fake repo **must** differ in content, and the test asserts the produced patch equals the **real** repository's patch, not merely that a patch exists |
| `test_head_chain_traversal_is_refused` | `ref: refs/heads/../../../tmp/evil` and siblings are refused, fail-closed | **NO** for the enumerated shapes; **YES** for a shape not in the fixture — so the refusal is an **allowlist regex**, not a denylist of bad substrings, and the test asserts the regex **rejects by default** |
| `test_dispatcher_never_adopts_observed_head` (AST) | no assignment writes an observed HEAD value into `expected_base_commit` anywhere in `src/**` | **YES** for an indirection the AST cannot follow. Paired with `test_worker_commit_moves_the_ref_and_is_caught`, which fails outright if adoption happens |

**Cost.** ≤ 5 small file reads plus, in the packed case, one `packed-refs` read.
`packed-refs` is a few KB here and **UNMEASURED on a repository with very many
refs**, where it could be megabytes — recorded as a gap, with the note that it is
read **once per snapshot, twice per run**, and that only the matching line is
parsed while the whole file is hashed.

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
    role: Literal["task_worktree_start","task_worktree_worker_exit",
                  "task_worktree_post_validation","primary_pre","primary_post"]
                  # "task_worktree_post" is DELETED, not aliased (§5.5.6)
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

Diverged START bytes are captured **content-addressed** into the **same CAS the
seal uses** — `materialisation/cas/<oid[:2]>/<oid[2:]>` (0600 inside 0700), keyed
by git-blob-sha1 — so N identical CRLF files cost one copy, **and a diverged
path's captured bytes and a base blob's sealed bytes are the same kind of object
in the same store.** Bounded by
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
    cas[reconciliation.captured_ref[p]]  if p in reconciliation.diverged  (Z-2 A)
    cas[base_oid[p]]                     elif p in base_tree
    /dev/null                            otherwise (created after materialisation)
```

**Both branches are CAS reads. Neither is a git command** (§5.5.2A(iii)). Pinned
by `test_resume_old_side_is_base_not_run1`, retained verbatim.

**Submodules (`gitlink`)** are recorded, never descended, never content-diffed.
**`REQUIRES-PROBE`:** no repository with a real submodule was exercised; the
production repository has none.

#### 5.5.5 Step 3 — materialisation. The PREPARE vector is closed by an ENUMERATED defence, or not at all

**Lane Z5 measured both halves of this section's open question and both answers
are negative.** `GATE7-Z5-PREPARE-PROBE.md` is published; §5.5.5 is no longer
OPEN, and what it now says is weaker than what revision 4 hoped for.

> **AND IN REVISION 6 THIS SECTION IS NO LONGER LOAD-BEARING FOR THE RUN'S
> EVIDENCE.** `worktree add` is still the one PREPARE execution-capable operation
> and it is still gated **and** pinned — but it now runs **inside the window in
> which no untrusted process has ever existed**, and **everything it produces is
> sealed before the worker starts** (§5.5.2A). A hook that fires here corrupts
> the *starting tree*, which §5.8's baseline gate and §5.5.4's reconciliation
> both measure; **it cannot corrupt an answer the dispatcher asks later, because
> the dispatcher asks nothing later.** *(The residual is unchanged and is stated
> in §2A.6: a PREPARE-window compromise produces a SEALED LIE, and §5.8's gate
> plus the operator's trust step are the only things standing there.)*

##### (a) The ordering fix does not work — filesystem quarantine is not a defence

The §5.8-as-precondition argument was: establish or quarantine the administrative
state before any ref-mutating operation, so a planted hook cannot exist when
`worktree add` runs. **Measured, it does not hold**, because *the hook does not
have to be in `$GIT_COMMON_DIR/hooks` at all*:

```
-- dispatcher DELETES the common hooks dir outright --
hooks dir present? no
PC branch (worker core.hooksPath)                rc=0  WORKERHOOK:reference-transaction
worktree add -b (worker core.hooksPath)          rc=0  WORKERHOOK:post-checkout
                                                       WORKERHOOK:post-index-change
                                                       WORKERHOOK:reference-transaction
-- same, reached through include.path indirection --
worktree add -b                                  rc=0  INCHOOK:reference-transaction …
-- and with the dispatcher PINNING -c core.hooksPath=<empty> on the argv --
worktree add -b + pin                            rc=0  clean
```

A previous task's poisoning persists as a **config key**, not only as a file, and
`include.path` means a `.git/config` grep is not a defence either. There is also
**no per-worktree hook namespace to isolate into**: a hook planted at
`$GIT_DIR/worktrees/<n>/hooks/reference-transaction` was **never consulted**
(control fired; **NOT OBSERVED**).

> **Stated plainly, because softening it would be the fourth instance of this
> gate's own failure mode: the PREPARE execution vector can be closed only by an
> ENUMERATED, ARGV-PINNED defence — `-c core.hooksPath=<empty dir>` — and not
> structurally. §5.8's baseline gate remains correct and valuable, but *refusing*
> is a gate, not a structural closure.**

##### (b) DECISION Z-3 (revised) — materialisation is gated AND argv-pinned

`git worktree add` remains the default mechanism. It runs **only after §5.8's raw
administrative preflight passes** *and* with **PIN 2** on its argv. Neither alone
is sufficient: the gate cannot see a key reached through `include.path` after the
baseline was trusted, and the pin does not stop a worker planting the key.

##### (c) DECISION Z-4 — RETIRED. `dispatcher_raw` is not structural

Revision 4 demoted Z-4 from *structural* to *gated* pending measurement. **The
measurement retires it rather than rescuing it.**

A fire-nothing materialisation path **does exist** — raw administrative files
written with plain file I/O, content written from `ls-tree` + `cat-file` bytes,
**zero sentinels fired with all 28 hooks and 11 exec keys armed**, and the bytes
are the **raw blob, not the smudged form**, which is exactly the property Z-4
exists for.

**It is not worker-usable.** With no index, a real `git status` inside it reports
**every tracked file simultaneously `D` (staged deletion) and `??` (untracked)**,
and after a real edit `git status` was **unchanged** and `git diff` **empty**. *A
real Claude worker in that tree would be told its own change did not happen.*

**And every measured way to give it an index fires:**

```
read-tree BASE (in-place index)                       rc=0  HOOK:post-index-change
GIT_INDEX_FILE=<tmp> read-tree BASE                   rc=0  HOOK:post-index-change
update-index --index-info (stdin)                     rc=0  HOOK:post-index-change
GIT_INDEX_FILE=<tmp> read-tree + hooksPath=<empty>    rc=0  clean
```

**An external `GIT_INDEX_FILE` does NOT avoid the hook** — it fires on the index
*write*, whichever file is written. (It is also useless to the worker: the
variable is per-process, so the worker's own `git status` would not read it.)

> **Z-4 is fire-nothing only in the state that is unusable, and usable only in
> the state that fires.** Its claim to close the PREPARE vector *structurally
> rather than by gating* is **unsupported by any configuration that was
> measured**, and it is **retired, not rescued**. `worktree_materialisation =
> "dispatcher_raw"` survives as a configuration value with the same gate and the
> same pin as the default — it buys the raw-blob starting tree (which makes
> `BaseReconciliation` a verification rather than a measurement), and it buys
> **nothing** on execution safety.

**The one untested path that could make it structural**, named so nobody
rediscovers it as an idea: the dispatcher writing the git **index file itself in
raw DIRC format**, with no git process. **NOT TESTED. Unspecified, unimplemented,
unmeasured**, and a substantial piece of new dispatcher-owned binary-format code.
**This design makes no claim about its feasibility** — only that no *git*
mechanism achieves it. It is escalated as **T-8** (§18.3A), not adopted.

##### (d) What the default path therefore is, exactly

```
git -c core.hooksPath=<empty dir>        # PIN 2 — the enumerated defence
    -c core.fsmonitor=false
    … the rest of §5.4.3A …
    worktree add --quiet -b <branch> <path> <base_commit>
```

preceded by §5.8's gate, which refuses on any administrative divergence **before
this command is constructed**. The residual, stated: **a worker that plants
`core.hooksPath` and a hook in the same run is caught by §5.8's fingerprint on
the *next* dispatch and by `POLICY_VIOLATION` on *this* one — and PIN 2 is what
stops the hook running in between.**

#### 5.5.6 THREE raw filesystem states, and attribution as a theorem (Sol §8)

##### The four defects this replaces, all measured in the tree at `d197bf0`

**(a) There are only two states, and neither of them is START.**
`server.py:2038` collects `worker_evidence` after the worker exits;
`server.py:2117` collects `final_evidence` after validation. **The pre-worker
state is never measured** — `base_commit` stands in for it — and under DECISION
Z-2 the base tree and the starting filesystem are *routinely* not byte-identical
(`.gitattributes` `eol=crlf`, `git-lfs`). So today's "worker changes" conflate
**checkout transform + prior run + worker** into one set.

**(b) Attribution is a set difference over path NAMES, and the source says so:**

```python
# server.py:558-589 — attribute_changed_paths
worker_set = set(worker_paths); final_set = set(final_paths)
"validation_added_paths": sorted(final_set - worker_set),
"attribution_method": "set_difference",
"attribution_caveat": (
    "A path changed by the worker and then rewritten by a validation "
    "command appears only under worker_changed_paths; set difference "
    "cannot separate authorship of a single path."),
```

**A set difference over path names structurally cannot express *modification*:**
a path present in both snapshots is in neither difference, whatever happened to
its bytes. **The caveat is an accurate description of a defect, shipped in
production as documentation.**

**(c) Scope is decided over the validation-inclusive set** —
`server.py:2123`: `check_scope(final_evidence.changed_paths, envelope.scope)`. A
validation command writing `coverage/lcov.info` outside `allowed_paths` lands the
**task** in `POLICY_VIOLATION` for something the dispatcher did.

**(d) The canonical patch is composed AFTER validation and labelled as the
worker's change.** `server.py:2451-2457` calls `write_full_diff(...)` at the end
of `_persist_evidence`, i.e. after `run_validations` returned. **`evidence/diff.patch`
is therefore `git diff <base>` of the POST-VALIDATION tree — and that is the
artefact Fable reads. This is "silently rewrite the worker patch and call the
result Claude's work", already shipped, with no flag recording it.**

**(e) Revision 5's own pipeline has no validation step in it.** It listed steps
0–10 with `── worker runs ──` between 5 and 6 and nothing between 6 and 10, while
§6.6 and `server.py:2103` place `run_validations` exactly there. §5.5.1 now has
it.

##### The invariants

- **ZI-28 (THREE STATES).** Every run measures exactly three raw filesystem
  states of the task worktree: **`START`** (PREPARE, before the spawn),
  **`WORKER_EXIT`** (after the worker is reaped and after the raw B2/admin check,
  **before the first validation spawn**), and **`POST_VALIDATION`** (after the
  last validation command is reaped). Each is an `FsSnapshot` at
  `fidelity="content_hash_all"`. **No fourth state, and no state is re-measured.**
- **ZI-29 (DELTA IS IDENTITY-WISE, NOT NAME-WISE).**

  ```
  identity(S, p) = ABSENT   if p not in S
                 = (kind, mode_significant_bits, content_hash, link_target)
  delta(A, B)    = { p : identity(A, p) != identity(B, p) }
  ```

  **`set(A) ^ set(B)` is forbidden by name** and an AST test asserts the
  expression does not occur on the attribution path.
- **ZI-30 (THE THREE DELTAS).** `worker_delta = delta(START, WORKER_EXIT)` ·
  `validation_delta = delta(WORKER_EXIT, POST_VALIDATION)` ·
  `final_delta = delta(START, POST_VALIDATION)`.
- **ZI-31 (`worker_delta` IS AUTHORITATIVE FOR AUTHORSHIP).** It is the sole
  input to the worker `PathIdentitySet`, the worker scope verdict, the worker
  canonical patch, `patch_file_complete`, and the Fable implementation review.
  **No path enters any of them because it is in `validation_delta` or
  `final_delta`.**
- **ZI-32 (THE PATCH IS FROZEN BEFORE VALIDATION).** The worker canonical patch,
  its sha256 and `patch_file_complete` are produced, written, fsynced and
  recorded **before the first validation command is spawned.** Nothing composed
  after a validation spawn may be labelled as the worker's work.
- **ZI-33 (NO SILENT ATTRIBUTION).** Every path in
  `final_delta ∪ worker_delta ∪ validation_delta` carries exactly one
  `author ∈ {worker, validation, both, ambiguous}` in `attribution.json`.
  **`both` is reported explicitly and is never collapsed to either side.**
- **ZI-34 (A MOMENT CANNOT BE RE-ENTERED).** A missing or partial snapshot is
  **not re-measured on recovery.** The run lands `FINALIZATION_FAILED` or fails
  closed. **There is no fallback measurement of a later tree standing in for an
  earlier one.**

##### The closure theorem

> **THEOREM Z9-T1.** `final_delta ⊆ worker_delta ∪ validation_delta`.
>
> *Proof.* Let `p ∈ final_delta`, so `identity(START,p) ≠
> identity(POST_VALIDATION,p)`. Identity equality is transitive, so it cannot be
> that `identity(START,p) = identity(WORKER_EXIT,p)` **and**
> `identity(WORKER_EXIT,p) = identity(POST_VALIDATION,p)`. Hence
> `p ∈ worker_delta` or `p ∈ validation_delta`. ∎

**This is what makes *"no changed path escapes attribution"* provable rather than
asserted.** Five cases follow and none of them is expressible today:

| Case | Membership | Handling |
|---|---|---|
| `worker_only` | `worker_delta \ validation_delta` | worker patch, worker scope |
| `validation_only` | `validation_delta \ worker_delta` | `validation_delta`, **never the worker patch** |
| **`both_authors`** | `worker_delta ∩ validation_delta` | **§5.11's explicit report, mandatory sentence** |
| `validation_reverted` | `worker_delta \ final_delta` | reported; the worker patch still shows it |
| — | `final_delta \ (worker ∪ validation)` | **impossible by Z9-T1.** Non-empty ⇒ `AttributionClosureViolated`, an `InternalDispatcherError`, **raised, never logged-and-continued** |

**`both_authors` being non-empty is NOT ambiguity.** `worker_delta` measures a
closed interval that contains no validation command, and under ZI-32 the worker's
new-side bytes are read and frozen inside that interval. **A `both_authors` path
is fully attributed on both sides; it is merely reportable.**

**Ambiguity is exactly three conditions**, each of which makes `worker_delta` not
a measurement of a closed interval: `changed_during_measurement` inside the
WORKER_EXIT walk (§5.5.3 item 4 already re-verifies each file's hash against the
bytes actually read; **a worker descendant that outlived the worker is the live
cause, and nothing prevents that** — §5.17); the WORKER_EXIT snapshot could not
be completed; the POST_VALIDATION snapshot could not be completed.

**Fail-closed placement, and why it is not F-3's shape.** Attribution ambiguity
must **never** preempt §8 rows 4 and 5. **Scope is decided over
`worker_delta ∪ validation_delta`, which exists even when the attribution between
them is ambiguous — so the tamper verdict and the scope verdict are ALWAYS
decidable.** Attribution failures therefore land at **row 5a**, which §8 already
defines as *"ONLY IF rows 4 AND 5 did not fire"*. *(A new row 5b was considered
and rejected: it would change §8's row count, which §12 and §16 assert, for no
behavioural difference. Recorded, not adopted.)*

##### Why the BYTES must be read in the interval, not the hashes

`FsSnapshot` records `content_hash`, not content, and a patch needs bytes. Two
options:

- **(a) compose the patch inside the interval — ADOPTED.** It is Sol's own
  ordering, costs one pass over `worker_delta` paths only, and needs no new
  storage.
- **(b) capture WORKER_EXIT bytes content-addressed and compose later —
  RECORDED, NOT ADOPTED.** It doubles the storage of every run's changed set and
  buys only the freedom to reorder, which nothing needs. **It remains the
  fallback if a later revision requires deferred composition, and it is the one
  thing that would rescue crash point C16.**

**`mode_significant_bits`.** Git records only `100644 | 100755 | 120000 |
160000`, so the identity tuple uses the executable bit for regular files and
nothing else for other kinds: **a `chmod g+w` is not a spurious delta while a
`chmod +x` is a real one.**

##### Three scope verdicts, because one reopens the resume hole

Sol §8 makes `worker_delta` *"the authoritative input to worker scope"*. **Read
literally and alone, that reopens the resume laundering hole §5.5.6 exists to
close**: a forbidden write made in run 1 and untouched in run 2 is not in run 2's
`worker_delta`, so run 2 would report a clean scope.

| Verdict | Decided over | Lands |
|---|---|---|
| `run_scope_verdict` | `worker_delta` | row 5. **This is the worker's verdict — the one attributed to Claude** |
| `cumulative_scope_verdict` | `cumulative_delta` (base representation vs WORKER_EXIT) | row 5. **Preserves the resume property** |
| `validation_scope_verdict` | `validation_delta \ worker_delta` | row 5 **for `forbidden_paths` only**; row 4 for `admin_significant`. **`allowed_paths` never fires for validation output** |

**`allowed_paths` bounds *what the worker was asked to change*, so a `dist/`
written by the dispatcher's own validation command is not out of scope — it is
not in scope at all. `forbidden_paths` bounds *what anything may touch*, so it
fires regardless of author.** Failing open on `forbidden_paths` for validation
would be a laundering channel: a caller-declared
`["cp","secrets/x","forbidden/y"]` would write a forbidden path with no policy
consequence. *(Escalated as **T-15** — the sharpest of the revision-6
escalations.)*

A path the worker changed **and reverted within one run** is still in
`worker_delta` and **must still be reported**: touching a forbidden path and
putting it back is still touching it.

##### Persistent data

```
state/tasks/<task-id>/runs/NNN/
  fs-snapshot-worker-exit.json      NEW  role="task_worktree_worker_exit"
  fs-snapshot-post-validation.json  NEW  role="task_worktree_post_validation"
  attribution.json                  NEW  WorkerAttribution
  evidence-freeze.json              NEW  §5.17
  evidence-freeze-post.json         NEW  §5.17
  validation-invocations.jsonl      NEW  §5.17
  git-admin-post.json               EXISTING — becomes capture #1 (step 10)
  git-admin-post-validation.json    NEW     — capture #2 (step 19)
state/tasks/<task-id>/evidence/
  path-inventory.json               PathIdentitySet over WORKER_DELTA
  path-inventory-validation.json    NEW  PathIdentitySet over VALIDATION_DELTA
  diff.patch                        the WORKER canonical patch      (T-16)
  cumulative.patch                  NEW  the cumulative patch       (T-16)
  changed-paths.json                schema "changed-paths/3"
  evidence-phases.json              schema "evidence-phases/2"
```

`FsSnapshot.role`'s literal becomes `"task_worktree_start" |
"task_worktree_worker_exit" | "task_worktree_post_validation" | "primary_pre" |
"primary_post"`. **`"task_worktree_post"` is DELETED, not aliased** — it named a
state whose position relative to validation was undefined, which is defect (e).

```python
@dataclass(frozen=True)
class WorkerAttribution:
    schema_version: int
    start_digest: str; worker_exit_digest: str
    post_validation_digest: str | None      # None iff no validation command ran
    worker_delta: PathIdentitySet           # AUTHORITATIVE
    validation_delta: PathIdentitySet | None
    final_delta: PathIdentitySet | None
    worker_only: tuple[RepoPath, ...]
    validation_only: tuple[RepoPath, ...]
    both_authors: tuple[RepoPath, ...]      # sorted by raw bytes
    validation_reverted: tuple[RepoPath, ...]
    ambiguous: tuple[AttributionAmbiguity, ...]
    verdict: Literal["attributable","worker_ambiguous","validation_unknown"]
    method: Literal["three_snapshot_identity_symmetric_difference"]
```

**`method` is a pinned literal precisely so that reverting to a set difference
must edit a string a test compares, and the edit is visible in the diff.**
`evidence-phases.json` keeps its four array names, **their values change** — they
were wrong for the intersection case — and **loses `attribution_caveat`
entirely**, with a test asserting the caveat string occurs nowhere in `src/**`:
*the sentence described a defect and the defect is gone.*

##### Tests, and the two that cannot pass while false

> **`test_worker_patch_is_frozen_before_validation_runs` — the strongest test in
> this section.** Worker writes `src/a.py` = `b"worker\n"`; validation runs
> `python3 -c "open('src/a.py','w').write('validation\n')"`. Assert `diff.patch`
> contains `+worker` and **not** `+validation`; `b"src/a.py" ∈ both_authors`;
> `verdict == "attributable"`; **and the on-disk `src/a.py` after the run is
> `b"validation\n"`.**
> **COULD IT PASS WHILE FALSE? No.** The pair *(patch says `worker`, disk says
> `validation`)* is unsatisfiable by any build that composes the patch from the
> tree after validation, **and** unsatisfiable by any build where validation did
> not run. The last assertion is what proves the arming command genuinely reached
> that path.

> **`test_worker_exit_snapshot_precedes_the_first_validation_spawn` —
> order-of-effects, not clocks.** The worker creates `tmp/scratch.txt`; the
> validation command **deletes** it. If WORKER_EXIT was taken first the path is in
> `worker_delta` **and** in `validation_delta`; if it was taken after validation
> it is in neither. Assert **both** memberships.
> **A wall-clock comparison between `captured_at` and the spawn time is a flake
> on a fast tree and proves nothing about causality. The clock form is explicitly
> rejected.**

> **`test_modified_path_is_in_the_delta_not_only_added_and_removed`.** Worker
> modifies an existing tracked file; nothing is added or removed.
> **COULD IT PASS WHILE FALSE?** **Yes**, if the implementation quietly falls back
> to `git diff --name-only` — which finds it, and fires a worker filter. Closed by
> additionally asserting the FINALIZE journal is **empty** and
> `PathIdentitySet.fidelity == "content_hash_all"`.

> **`test_size_and_mtime_preserving_edit_is_in_the_worker_delta`.** The worker
> rewrites a file to the same byte length and restores `st_mtime_ns` with
> `os.utime`. **Only `content_hash_all` catches it** — this is the killer for a
> mutant that makes `snapshot_fidelity_task_worktree` configurable downward,
> which §5.5.3 forbids in prose and nothing tested.

> **`test_final_delta_is_contained_in_the_union`.** Z9-T1 over a fixture
> engineered to make **every** case non-empty. **COULD IT PASS WHILE FALSE?**
> **Yes — vacuously, if all deltas are empty.** The four non-emptiness assertions
> are what close it, and they are why the fixture is built the way it is.

> **`test_attribution_ambiguity_fails_closed_below_rows_4_and_5`.** (i) ambiguity
> **plus** an out-of-scope write ⇒ `POLICY_VIOLATION` (row 5), **not** `FAILED`;
> (ii) ambiguity alone ⇒ `FAILED` with `WorkerAttributionAmbiguous`.
> **COULD IT PASS WHILE FALSE? Yes, and this is the trap.** If the ambiguity is
> injected by **racing** a background writer against the WORKER_EXIT walk, the
> test can pass by *not racing* — a green run that proved nothing, which is B-2's
> failure mode. **The ambiguity is therefore injected through a production seam,
> not a race:** §5.5.3 item 4's hash re-verification is production code, and the
> fixture makes one entry's re-read differ via a `SIGSTOP`-released helper
> synchronised on a FIFO, or by parameterising the walk's re-read hook. **The
> dynamic race version is recorded as NOT A TEST.**

> **`test_missing_worker_exit_snapshot_is_finalization_failed_not_remeasured`.**
> Delete `fs-snapshot-worker-exit.json` and drive recovery. Assert
> `FINALIZATION_FAILED`, **assert no new snapshot file appears**, assert the index
> is not reused. **The "no new file" assertion is what distinguishes refusal from
> silent re-measurement.**

##### Backward compatibility

**`DispatcherObservations.changed_paths` changes meaning** from the
post-validation set to `worker_delta` and gains `validation_changed_paths`.
Readers — `server.py:1350-1365` (`get_task`), `server.py:701-732` (the review
prompt), `results.py:197` — are **each a behaviour change and each must be
updated in the same wave.** `changed-paths.json` → schema 3;
`evidence-phases.json` → schema 2. **No existing production task is affected:**
Gate 7 has not shipped, the five forensic tasks are read-only, and
`fs-snapshot-*.json` exists nowhere on disk.

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
**`REQUIRES-PROBE` RETIRED — measured (Z5).** Every §9 edge case was
hand-composed by the probe in the shape this design specifies, and every one
passed `git apply --check` **and applied byte-exactly** into a disposable
repository:

```
empty new file                 --check ok   apply ok   bytes match
new file with content          --check ok   apply ok   bytes match
path with spaces               --check ok   apply ok   bytes match
path with newline (C-quoted)   --check ok   apply ok   bytes match
delete to empty                --check ok   apply ok   bytes match
```

**Three format constraints are now load-bearing and MUST be encoded in the
renderer**, because each has a plausible wrong form that `--check` rejects:

1. **An empty new file is `diff --git` + `new file mode 100644` and NO `@@` line
   at all.** Emitting `@@ -0,0 +0,0 @@` produces `corrupt patch`, and omitting
   `new file mode` produces no valid patch either. The zero-hunk file section is
   the *only* accepted shape. `test_empty_new_file_patch_has_no_hunk_header`.
2. **Paths containing spaces:** git itself appends a **trailing TAB** after
   `+++ b/<path>` (and after `--- a/<path>`). The **tab-less form is also
   accepted** by `git apply`. The renderer emits the tab-less form; the test
   asserts *acceptance*, not byte-equality with git's own output, because the
   two differ and only one of them is this design's product.
   `test_spaced_path_patch_applies_without_trailing_tab`.
3. **C-quoting is optional, but when used the quote must wrap the whole
   prefixed path** — `"a/new\nline.txt"`, not `a/"new\nline.txt"`. The wrong
   nesting is accepted by nothing. `test_c_quoted_path_quote_wraps_prefix`.

> **PROVEN BY:** each test composes the patch with the production renderer and
> runs `git apply --check` plus a real `git apply` in a `tmp_path` repository,
> then compares the resulting file bytes to the intended bytes.
> **COULD IT PASS WHILE FALSE?** Yes, if it only ran `--check`: `--check`
> accepted shapes that this probe also had to *apply* to distinguish. Hence
> apply-and-compare-bytes, not `--check` alone. **IF MIS-WIRED** — the renderer
> falls back to git for these shapes — §5.4.6's static half fails, and **the
> permitted post-worker list is empty**, so `git apply` appears there only inside
> these disposable-repo tests.

#### 5.5.9 ONE completeness definition, ONE producer, and NO THIRD COLUMN (Sol §11, closes F-1 and F-2)

##### The structural cause, in one sentence

**The design had THREE columns — *omits content?*, *clears the flag?*, *blocks
the review?* — and a guard that reads only the second.** Any class whose three
columns are not `(yes, yes, yes)` or `(no, no, no)` is a latent F-1, and revision
5 had three such classes. **Revision 5 also gave two tables opposite answers to
one question:**

| | revision 5 §5.5.9 *clears the flag?* | revision 5 §5.11.5 *blocks the flag?* |
|---|---|---|
| binary / `UNTEXTUAL` | **no** | **yes** |
| symlink, FIFO, socket, device, gitlink | **no** | **yes** |

Read §5.11.5 as authoritative and **one symlink kills every review of
production**. Read §5.5.9 as authoritative and **the flag is `true` while content
was omitted, for two whole classes** — which brief §9 forbids by name, and which
means **directive C's named attack survives B-3's fix in binary form**: ZI-25
promises a modified base-ignored path *"in the canonical patch in full"*, which is
not achievable for a modified `.venv/bin/python`.

**And in the tree, `diff_patch_complete` means "git exited 0"** —
`server.py:2451-2457` sets it `True` unless `write_full_diff` raised. **A binary
change, a symlink, an unreadable file and a 3 GB file all leave it `True`.** It is
not a completeness flag.

##### The invariants

- **ZI-44 (ONE DEFINITION).**

  > **`patch_file_complete == True` IF AND ONLY IF every path in `worker_delta`
  > has an exact canonical review representation in the worker canonical patch.**
  >
  > **No exception for ignored, base-ignored, generated-before-worker, binary,
  > symlink, or any other class.** Unchanged baseline paths are simply **absent
  > from `worker_delta`** and the IFF does not range over them.

- **ZI-45 (ONE PRODUCER, STRUCTURALLY).** `patch_file_complete` is **not a
  field.** It is a read-only property of `CanonicalEvidence` computed from the
  per-path accounting the same object carries. **There is no constructor argument
  to pass, no serializer field to forget, and no caller expression that can set
  it.**
- **ZI-46 (TWO AXES, NOT ONE).** *Content inventory completeness* and *review
  representation completeness* are different questions with different answers.
  **A binary file's inventory (path, mode, size, sha256) is COMPLETE; its text
  review representation DOES NOT EXIST.** Both facts are recorded, on separate
  fields, and the two tables merge into one with two columns.
- **ZI-37 (NO THIRD COLUMN).** For every content class, *clears
  `patch_file_complete`* and *blocks the review* are **the same column**. **There
  is no class that omits content and does not block the review**, and an
  enumeration test asserts it over `ContentClass.__members__`. **This is F-1
  closed at the source rather than at the guard.**

##### The seven rules, exactly

| Input | `representation` | `inventory_complete` | Contributes `patch_file_complete` |
|---|---|---|---|
| supported regular UTF-8 text | **exact canonical patch section** | true | **true** |
| **empty** regular file | **exact** — `new file mode 100644` and **no `@@` line at all** (§5.5.8 rule 1) | true | **true** |
| regular file with **no final newline** | **exact** — `\ No newline at end of file` on the affected side | true | **true** |
| **symlink** | **exact** — `lstat(follow_symlinks=False)` + `os.readlink` in **bytes**; mode `120000`; body = raw target bytes. **Never followed, never opened, never `realpath`ed** | true | **true** |
| **binary** (NUL in the first 8 KiB of either side, or either side not valid UTF-8) | **None** — `omission_reason="binary_no_approved_representation"` | **true** — path, mode, size, sha256 of both sides | **false** |
| unsupported special file — FIFO, socket, block/char device | **None** — `omission_reason="unsupported_special_file"` | true — kind, `st_mode` | **false** |
| unrepresentable path (a non-UTF-8 name the envelope path model cannot carry) | **None** — `omission_reason="unrepresentable_path"` | true — `raw_b64` | **false** |
| unreadable · `changed_during_measurement` · oversized · `regeneration_capped` | **None** | partial, recorded as partial | **false** |
| **gitlink (submodule)** | **None** — `REQUIRES-PROBE` | true — mode `160000`, old/new oid | **false** |

**`content_omitted_bulk_created` and `BULK_CREATED_IGNORED` are DELETED as a
class.** Under the IFF there is no class that omits content while the flag stays
true, and under ZI-37 there is no class that clears the flag without blocking the
review. **`ZI-26`'s rollup was both of those things at once, so it cannot
exist.** Consequently `[evidence].bulk_created_ignored_budget` is **removed as a
config key** (a config carrying it is a **refusal**, not a warning), the
`prefix / count / total_bytes` rollup row is **deleted from `diff_stat`**, and
§5.11.5's `BULK_CREATED_IGNORED` row is **deleted, not amended** — §5.8.5's own
rule for mutually exclusive designs.

**B-3 is not reopened**, because B-3's finding was *content omitted under a true
flag* and **there is now no class at all that omits content under a true flag.**
ZI-25 and ZI-27 stand unchanged and are **strengthened**: `added` base-ignored
paths are now also in the patch **in full, with no escape hatch.**

**What is honestly lost, and it is one step less than "cliff".** A task whose
**worker** ran a large build loses its **automated** review — the patch is
honestly complete, and it may then be too large to travel in the reviewer's argv,
which is `EvidenceExceedsReviewBudget` and `review_input_complete = False`
(§5.11.4). **It does not lose its task state:** both review refusals are §8
**row 0** PREPARE refusals on the *review* path with `state.json` byte-identical;
the task still lands `IMPLEMENTED → AWAITING_SOL_REVIEW` and Sol reviews by hand.
**"Every review after a build run refuses" is accurate; "cliff" overstates it by
one step, because no task state changes.** Recording that distinction is the
difference between a lever Sol can price and a defect.

##### The symlink rule — MEASURED, and it is what makes Y-10 ratifiable

1. **A symlink's git object is the raw target bytes.** `ls-tree` reports
   `120000 blob 7f66e4fb…  link`, and `printf 'f.txt' | git hash-object --stdin`
   returns **the same oid**. **DECISION Z-5's `git_blob_oid` already covers
   symlinks**; `os.readlink` in bytes mode feeds the same function.
2. git's own representation is a normal hunk at mode `120000` with
   `\ No newline at end of file` on both sides.
3. **A hand-composed section — no `git diff` involved — applies byte-exactly and
   recreates a SYMLINK**, not a regular file: `--check` OK, `apply` OK,
   `os.path.islink` true, `os.readlink` byte-equal.
4. **A dangling symlink is fully representable** — `dangle -> /nonexistent/x`
   commits, hashes and diffs normally, because git never resolves it. **This is
   the fixture assertion a follow-the-link implementation cannot satisfy.**
5. **A symlink whose target contains `LF` is legal and representable**:
   `os.symlink("a\nb", …)` succeeds, git renders `@@ -1,2 +1,2 @@` with two `-`
   and two `+` lines, and a hand-composed version applies and reconstructs
   `b"c\nd"` **as a symlink**.
6. **An empty symlink target cannot exist** — `os.symlink("", …)` fails
   `ENOENT`. **There is no zero-byte-target hole to specify.**
7. **A `symlink ↔ regular` kind change is TWO patch sections** — `deleted file
   mode 120000` **plus** `new file mode 100644` for the same path. **A single
   section is not a valid representation**, and revision 5 does not say this
   anywhere.
8. **`git apply` DOES NOT VALIDATE `index` LINES.** A section carrying a
   malformed **39-character** oid was accepted and applied. **Any test that
   proves the renderer by applying the patch can pass while the index line is
   garbage** — so the oids must be asserted independently against
   `git_blob_oid`.

**Rendering, precisely, so two implementers produce the same bytes:**

```
diff --git a/<disp> b/<disp>
index <git_blob_oid(old_target)>..<git_blob_oid(new_target)> 120000
--- a/<disp>
+++ b/<disp>
@@ -1,<n_old> +1,<n_new> @@
-<old target bytes, split on LF>
\ No newline at end of file
+<new target bytes, split on LF>
\ No newline at end of file
```

with `n = target.count(b"\n") + 1`, the `@@ -1 +1 @@` short form when both are 1,
`new file mode 120000` / `deleted file mode 120000` for add/remove, `<disp>` the
C-quoted display form per ZI-7 (**never read back**), and **two sections for
`kind_changed`**.

**`UNREPRESENTABLE_KIND` survives, narrowed to FIFO, socket, block device, char
device and gitlink**, and its two columns are unambiguously `(false, blocks)`.
**Measured population: this repository has 4 ignored symlinks and production has
1, and ZERO FIFOs, sockets or devices in either — so the narrowed class is empty
in practice on both hosts.**

**Binary — the escape hatch, costed by measurement.** An exact binary
representation **is** implementable: `GIT binary patch` / `literal <size>` /
zlib-deflate / git's base85 with the length-prefix byte. **MEASURED:** a
dispatcher-composed section of that form passes `--check`, applies byte-exactly,
and reverse-applies. **MEASURED TRAP: Python's `base64.b85encode` produces
`error: corrupt binary patch`** — the alphabet matches (RFC 1924); **the padding
does not**, because git emits full five-character groups for a short final chunk
and Python truncates. **An implementer who reaches for the stdlib gets a
silent-looking failure at apply time, which is why this is a Sol decision
(T-17) and not a keyboard one.** Until it is taken: `sections=()`, flag false,
fail closed, **and the cost is that any task changing a binary loses its
automated Fable review** — with the inventory still carrying path, mode, size and
both sha256s, so nothing is hidden.

**Gitlink: `REQUIRES-PROBE`.** `-Subproject commit <oid>` is a *plausible* exact
representation and is **not adopted**, because no repository with a real
submodule has been exercised and production has none.

##### The type, and why the property is the mechanism

```python
# evidence/patch.py — the ONLY module permitted to construct CanonicalEvidence.
# An AST test asserts "CanonicalEvidence(" occurs in exactly one module and that
# "patch_file_complete=" occurs NOWHERE as a keyword argument in src/**.

@dataclass(frozen=True)
class CanonicalEvidence:
    inventory: ClassifiedInventory        # over worker_delta
    patch_path: Path
    patch_bytes: int
    patch_sha256: str
    per_path: tuple[PathRepresentation, ...]   # one per inventory entry, same order

    @property
    def patch_file_complete(self) -> bool:
        return (
            len(self.per_path) == len(self.inventory.identity.changes)
            and all(r.sections for r in self.per_path)
            and all(r.omission_reason is None for r in self.per_path)
        )
```

**The first conjunct is load-bearing and is the B-3/F-2 shape closed
structurally:** a path silently dropped from the accounting no longer leaves the
flag true — **it makes the lengths differ.** A rollup, an exemption, a filtered
comprehension, or a `continue` in the classification loop all fail it.

**The `@property` is what makes ZI-45 structural: there is no assignment
expression that can produce a wrong value.** A mutant must edit the returned
expression, which is three lines, visible in the diff.

##### The killer that closes both findings

> **`test_no_class_is_exempt_from_the_completeness_iff`** — parameterised over
> `ContentClass.__members__`, **generated at collection time**. For each class,
> build a `worker_delta` containing exactly one path of that class and assert
> `patch_file_complete == (per_path[0].sections != ())` **and**
> `blocks_the_review == (not patch_file_complete)` — i.e. **the two columns are
> one column.**
>
> **COULD IT PASS WHILE FALSE? Yes, if a class had no fixture.** Closed by
> asserting the generated parameter-id set **equals** `set(ContentClass.__members__)`
> — **a new class added without a fixture FAILS COLLECTION, it does not silently
> pass.**
>
> **IF MIS-WIRED as revision 5:** `UNTEXTUAL` and `UNREPRESENTABLE_KIND` fail
> under §5.5.9's values and `BULK_CREATED_IGNORED` fails under either table's.
> **A build carrying two tables cannot pass this test.**

**Companion tests, each with the assertion that closes it:**

| Test | The assertion that makes it non-vacuous |
|---|---|
| `test_patch_file_complete_is_a_property_not_a_field` | reflection **plus** the paired AST test — a second construction path is the only way it could pass while false |
| `test_symlink_is_supported_and_the_patch_recreates_a_symlink` | the fixture contains a **dangling** symlink, which `realpath`/`open` cannot resolve, **so a follow-the-link build fails on that entry**; and the `index` oids are asserted **independently** against `git_blob_oid`, because `git apply` ignores them |
| `test_symlink_to_regular_kind_change_is_two_sections` | `len(sections) == 2` — a single-section renderer produces 1, and `git apply` rejects a mode-changing single section |
| `test_a_single_unchanged_symlink_blocks_nothing` | **a walk that skips symlinks entirely would pass it** — closed by asserting the START **and** WORKER_EXIT snapshots each contain the symlink with a `content_hash` and a `link_target` |
| `test_binary_change_clears_the_flag_and_keeps_the_inventory` | asserts the dispatcher's **own** classifier assigned `UNTEXTUAL` from the bytes, and that **no `diff` row exists in the journal** — git's `Binary files … differ` must never be the source |
| `test_bulk_created_rollup_does_not_exist` | the grep is the cheap half; **the enumeration is the half that cannot be renamed around** |
| `test_ignored_and_base_ignored_paths_are_not_exempt` | the fixture **commits the file to the base first, then modifies it**, so the case cannot silently be an `added` path; and 20 `added` base-ignored files must appear **in full** |

##### What disappeared, and why `refused` is now worth reading

`refused: directory` (a directory is a `kind`, not a file to read),
`refused: path_escapes_worktree` (nothing resolves a symlink) and
`refused: symlink` (**symlinks are SUPPORTED**) are all gone. **`refused` now
means only "we could not see it" or "it moved while we looked."**

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

> **REVISION 6 GIVES THIS MODULE A SECOND, LOAD-BEARING CONSUMER, and it is a
> consequence of a deletion rather than a new feature.** §5.4.5 deletes
> `git ls-files --others --exclude-standard` (`git.py:652`) from `src/**`. That
> command is what **bounds the filesystem side of the comparison** today — and a
> regeneration run that replaced it with a naive `os.walk` **blew a two-minute
> budget on the production repository, because the untracked `.venv` is in the
> tree** (§5.5.3A). **So the walk must be bounded by the sealed path set plus an
> explicitly evaluated ignore set, and the dispatcher must own that evaluation.**
>
> **The fail-open direction is now doubly load-bearing**: a discarded rule means
> *more* paths are walked and reported, which is safe for correctness and
> **costly for the budget**. `unsupported_ignore_rules` is therefore an input to
> the §5.5.3A budget report, not only to the evidence record. **`REQUIRES-PROBE`:
> the agreement corpus for this matcher still does not exist**, and it is now
> guarding a performance boundary as well as a classification.

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
(`os.scandir` on a `bytes` root) and `ls-tree -r -z`. Lane X measured why
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
| **transport and promisor keys** | any config reached above | `remote.*.url`, `url.*.insteadOf`, `extensions.partialClone`, `remote.*.promisor`, `remote.*.partialclonefilter`, `core.alternateRefsCommand`, `credential.helper` — **recorded and PRINTED VERBATIM to the operator** (see below) |
| **worktree `.git` indirection** | `<worktree>/.git` | present · **raw bytes** · sha256 · is-file-or-dir. **NEW — and §5.8.2A only *read* it before, to find the gitdir it was about to capture, so a redirected gitfile made the CAPTURE ITSELF describe the repository the worker chose** |
| **worktree gitdir `HEAD`** | `<gitdir>/HEAD` | raw bytes · sha256. **NEW — was allowlisted** |
| **the whole HEAD chain** | every file `resolve_head_raw` consults (§5.5.2C) | per-link present · sha256. **NEW** |
| **`commondir`** | `<gitdir>/commondir` | **raw bytes** (MEASURED: relative, `../..\n`) · resolved path · sha256. **NEW — was allowlisted** |
| **gitdir back-pointer** | `<gitdir>/gitdir` | raw bytes · sha256. **NEW — was allowlisted** |
| **`objects/info/alternates`** | every one reachable from `$GIT_COMMON_DIR` and each worktree admin dir, **transitively, depth ≤ 8** | raw bytes · sha256 · resolved targets · `transitive_depth_reached`. **NEW** |
| **`objects/info/http-alternates`** | same | same. **NEW.** `NOT OBSERVED` as a local vector on 2.43.0 (§5.4.1A row F) — captured anyway, because captured is cheaper than reasoned about |
| **`objects/info/` DIRECTORY LISTING** | `$GIT_COMMON_DIR/objects/info/` and each gitdir's | sorted raw names. **NEW — the only row here that is not an enumeration**, included precisely because every other row is. It does not prove completeness; **it makes an unnamed routing file VISIBLE**, which is a strictly weaker and honestly stated property |
| **`refs/replace/**`** and packed `refs/replace/` lines | `$GIT_COMMON_DIR/refs/replace/**`, `packed-refs` | names + per-file sha256. **NEW — MEASURED to substitute any object for any other, `rc=0`, with the expected SHA returned** |
| **`info/grafts`** | `$GIT_COMMON_DIR/info/grafts` | raw bytes + sha256. **NEW — MEASURED live on 2.43.0, forges the root commit** |
| **`packed-refs`** | `$GIT_COMMON_DIR/packed-refs` | full bytes + hash. **NEW** — a worker `pack-refs --all` moves the chain without moving a value |
| **`refs/` listing** | `$GIT_COMMON_DIR/refs/**` and `<gitdir>/refs/**` | names + per-file sha256. **NEW** |
| **object presence** | `$GIT_COMMON_DIR/objects/pack/` listing (names + sizes) and the 256 loose-object fan-out directory listings | sorted raw names + per-file size. **NEW — this is what makes a deleted base blob DETECTABLE rather than INFERRED** (§5.12) |
| `shallow`, `objects/info/commit-graph`, `objects/info/commit-graphs/**`, `objects/info/multi-pack-index` | as named | hash + listing. **`commit-graph` and `multi-pack-index` are `NOT TESTABLE` as forgery vectors — inventoried, never measured.** Given that `refs/replace` and `info/grafts` both fired, **an un-probed cached-parentage file is not a safe assumption** |
| `modules/**` (submodule admin) | `$GIT_COMMON_DIR/modules/**` | **NOT TESTABLE — not inventoried by any probe.** Escalated as **T-18** |
| `logs/**` (reflogs) | `<gitdir>/logs/**`, `$GIT_COMMON_DIR/logs/**` | listing + hash, **REPORT ONLY** — see §5.8.3 |

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

> **The fallback is UNAVAILABLE on the authorization path and on the post-worker
> path.** At R3/R4 an undecidable layout is `RepositoryLayoutUnreadable`, a
> refusal **before any git process** — otherwise §5.8.2B is defeated by its own
> escape hatch on exactly the inputs an attacker would construct. Post-worker it
> is deleted outright (§5.5.2C). **It survives only for the capture of an
> already-authorized, already-established repository, at row G10.** *(This is a
> conflict with §5.8.2A as revision 5 wrote it, resolved in §5.8.2B's favour for
> the authorization step; escalated as **T-20**.)*
>
> **The test-oracle carve-out, stated so an implementer does not "fix" it
> wrongly:** `test_gitdir_resolver_matches_rev_parse_on_every_layout` compares the
> raw resolver against the command §5.8.2B removes. **That is legitimate and is
> explicitly permitted** — the prohibition is over `src/**`, and `tests/**` may
> run the oracle **in throwaway repositories**. Without this sentence, an
> implementer meeting a red AST test inside `tests/` deletes the oracle, and the
> raw parser ships with no independent check.

**The raw parser is MEASURED, with a control that could report failure.** Lane Z7
compared it against git on **8/8 healthy layouts** — main worktree (`.git`
directory), linked worktree (`.git` file), detached, **relative gitfile**, main
and linked with `packed-refs`, **`--separate-git-dir` with no `commondir` file**,
and a worktree of a bare repository — on `toplevel`, `gitdir`, `commondir` and
`head_oid`. **The positive control fired:** a deliberately broken parser that
ignores `commondir` reported **DISAGREE** on both fields through the same
harness. **The 8/8 is a result, not an artefact.**

**The one place the parser deliberately DISAGREES with git, and it is the
argument for §5.8.2B:**

```
  git --show-toplevel : /tmp/z7p2c.Y7eZfG/altwt
  raw   toplevel      : /tmp/z7p2c.Y7eZfG/task
```

`core.worktree` — in `config`, or in `config.worktree` under
`extensions.worktreeConfig` — **redirects `rev-parse --show-toplevel`**, and
`config` is worker-writable. **The raw parser refuses to let configuration
redirect identity at all.** The consequence must be stated: **a repository that
*legitimately* sets `core.worktree` cannot be served by a parser that ignores
it**, so the fail-closed answer is to **refuse** a repository whose
`config`/`config.worktree` sets `core.worktree`, and to seal both files so the
setting cannot appear later.

**One `REQUIRES-PROBE` this section owes:** `Path.is_dir()` **follows symlinks**,
so a `<root>/.git` that is a **symlink to a directory** reads as a directory and
works, **while the link itself is never captured** — an uncaptured redirection
pointer of exactly S-ε's family. **Not measured by any lane. `REQUIRES-PROBE`,
and §5.8.2's gitfile row must be extended to cover it.**

#### 5.8.2B Repository authorization is a filesystem identity, never a git answer (Sol §7)

##### The categorical defect

`git.py:255-271` — `git_top_level(path)`, whose own docstring calls it *"**the**
repository identity primitive"* and says in as many words that **it asks git
itself** — runs `_run_git(["rev-parse", "--show-toplevel"], cwd=candidate)`.
Three call sites, and one of them is the authorization decision:

| Call site | What it decides | When |
|---|---|---|
| `security.py:217` (`validate_repository_root`) | **whether this repository may be dispatched into at all** | `server.py:904` — **the first git process of any dispatch** |
| `locks.py:72` (`lock_identity_for` → `git_top_level_or_none`) | which lock file *"one mutating worker per repository"* uses | `server.py:909`, immediately after |
| `git.py:350` (`collect_repository_identity`) | the guidance manifest's `toplevel` field | pre-worker, after materialisation |

> **The dispatcher asks the repository which repository it is, and then uses the
> answer to decide whether that repository is authorized.**
> `rev-parse --show-toplevel` resolves through git's discovery walk — the `.git`
> gitfile, `commondir`, `core.worktree`, `GIT_CEILING_DIRECTORIES`,
> `safe.directory` — and **in a tree a previous run's worker owned, every one of
> those is a worker-writable plain file.** MEASURED: S-ε variant A makes it report
> a **foreign** path; variant C makes it report the **legitimate** path while the
> object store underneath is substituted. **So the command is neither necessary
> nor sufficient for the question it is being asked.**

**And it is F-7's first missing row:** revision 5's §5.4.3 asserted it clean on
all four surfaces while **A.2B does not contain the row at all. Its S-δ column
came from nowhere.**

> ### INVARIANT ZI-58 — AUTHORIZATION IS `realpath` EQUALITY
>
> Authorization is `realpath(requested_root) == realpath(allowed_root)` — byte
> equality of two `realpath` results, against `[security].allowed_repository_roots`
> realpath'd **once at config load**. **No git process participates in the
> authorization decision, and no git process runs before it.**
>
> Git administrative layout is obtained by **raw filesystem parsing** (§5.8.2A).
> **`rev-parse --show-toplevel` has no call site in `src/**`.**
>
> **The layout parse may only NARROW authorization.** An unparseable layout is
> `RepositoryLayoutUnreadable`, a PREPARE refusal, and **never an acceptance of a
> different root.**

**The order inside `validate_repository_root` is itself load-bearing:**

```
1. shape:      non-empty, no NUL, absolute            (pure string — unchanged)
2. canon:      path = realpath(raw_root)              (ONE resolution, ONE value)
3. exists:     is a directory                         (stat only)
4. ALLOWLIST:  path in {realpath(r) for r in config.security.allowed_repository_roots}
               else RepositoryNotAllowed
   ---- only now may anything INSIDE the repository be opened ----
5. LAYOUT:     resolve_gitdir(path) must succeed  else RepositoryLayoutUnreadable
6. return path                                        (the canonical_root, threaded on)
```

**Step 4 before step 5 is the point.** Reading `<root>/.git` is reading a
worker-writable file; it must happen only after we know we are permitted to be in
that directory, **and its result must never widen the decision.**

**What is preserved for free.** Today's *"root must be the git top level, not a
subdirectory"* refusal survives without a git command: `/repo/src` is not in the
allowlist and has no `.git`. **Same outcome, different reason — and "same
outcome" is exactly the claim a reviewer should test**, which is why
`test_authorization_is_realpath_equality` carries the subdirectory row
explicitly.

**`lock_identity_for` drops `git_top_level_or_none`.** Lock identity becomes the
canonical root `validate_repository_root` already returned — `realpath()` and
nothing else. The function becomes **total**, so its unit tests over plain
non-git directories keep working, and `locks.py`'s own docstring — *"Security
decisions never come through here"* — becomes **structurally true rather than
conventionally true**.

> **This is a PRECONDITION for §5.4.3B's ordering, not merely a neighbour of it.**
> While `lock_identity_for` calls `git_top_level_or_none`, **the lock itself runs
> a git process, and no ordering can put the lock — or §5.8.3's gate — before the
> first git process of the dispatch.**

**`collect_repository_identity` loses two rows.** `toplevel` becomes the
`canonical_root` the caller already holds (`worker_context.py:581` passes it in)
— **a parameter, not a measurement**; `--absolute-git-dir` becomes
`resolve_gitdir`'s answer. What remains is `config --get remote.origin.url` and
`rev-list --max-parents=0 HEAD` — **genuine questions about repository CONTENT**,
both in A.2B, both measured clean on four surfaces, at G6/G7.

**`is_git_repository` (`git.py:238`, `rev-parse --is-inside-work-tree`) is
deleted.** It has no call site. **A permitted row with no call site is a future
call site — the same argument that deletes `write_full_diff`. No compatibility
wrapper.**

##### Tests

| Test | Proves | Could it pass while false? |
|---|---|---|
| **`test_no_show_toplevel_in_src`** (AST) — **RED against `d197bf0` today** (`git.py:271`, `security.py:217`, `locks.py:72`, `git.py:350`) | the literal `"--show-toplevel"` and the symbols `git_top_level` / `git_top_level_or_none` / `is_git_repository` appear nowhere in `src/**` | **YES** for an argv assembled from a variable — the standing weakness of every AST test here. Paired with the journal and the audit hook. **It is specified RED on purpose**, in the same posture as §5.4.6's static half |
| **`test_authorization_decides_before_any_git_process`** — dispatch against a **non-allowed** root under a live spawn audit hook | `RepositoryNotAllowed` **and zero git children** | **YES IF THE HOOK IS NOT PROVEN LIVE.** The test must fire a deliberate `git --version` first and assert the hook **observed it**. Without that control this is the B-2 failure mode exactly |
| **`test_worker_written_gitfile_cannot_change_authorization`** — S-ε variant A | the dispatch refuses and **nothing reports the FAKE path** | **YES WITHOUT THE INTEGRITY CONTROL.** Per **Z-RULE-1B**: first run the **removed** `rev-parse --show-toplevel` in the same fixture and assert it returns the **FAKE** path — proving the decoy is genuinely consulted — then run the production path |
| `test_authorization_is_realpath_equality` | accept `/repo`, `/repo/`, `/repo/./`, a symlink to `/repo`; refuse `/repo/src`, `/repo/../repo2`, a symlink inside `/repo` pointing out | **YES if it only checks the return value** — a build that calls `realpath` twice passes. **The test must assert the value is THREADED**: construct the lock from the returned root and assert `lock_path` equals the digest of that exact string |
| `test_unreadable_layout_refuses_and_runs_no_git` | refusal, zero git children, **no `rev-parse` fallback** | **NO** — the fallback's absence is observable as the absence of a journal row |

##### Backward compatibility

`git_top_level`, `git_top_level_or_none` and `is_git_repository` are **deleted,
not deprecated.** They are in `git.py:__all__`; the break is internal to this
package — no MCP surface, no envelope field, no state-file change. Operators
listing an allowed root by a non-realpath spelling keep working, because the
allowlist is realpath'd at config load. **One genuine regression, named rather
than discovered:** a repository whose `.git` is a **symlink to a directory** —
accepted today by `rev-parse`, accepted by the raw resolver via `is_dir()`
symlink-following, **and the link itself uncaptured.** `REQUIRES-PROBE`.

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
       and the human trust step must see it. The PRINTED list is what a
       human actually reads; §5.8.2 hashes the whole config file.
if current != baseline:
    -> RepositoryAdministrationUnreconciled           (PREPARE refusal, NOT retryable)
```

**No git command that could execute a repository-supplied program runs before
this gate passes** — only the identity resolution of §5.8.2A, whose fallback
`rev-parse` variants are measured clean on all four armed surfaces. That is
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

##### THE ALLOWLIST IS DELETED IN ITS ENTIRETY (Sol §14)

> ### INVARIANT ZI-57 — THE PROTECTED ADMINISTRATIVE SNAPSHOT HAS NO DELIBERATE EXEMPTIONS
>
> Revision 5's *"What is NOT protected, deliberately"* paragraph put
> `$GIT_COMMON_DIR/worktrees/sol-<id>/{gitdir,commondir,HEAD,index,logs}` on an
> explicit allowlist keyed by the `sol-` prefix. **`commondir` says where the
> object store and the refs live. `HEAD` is what B2 measures. The design
> allowlisted the redirection pointers by name, and S-ε walked through exactly
> that hole.**
>
> **The paragraph is DELETED. Not narrowed. Deleted.** An exemption keyed on a
> filename prefix the dispatcher controls **is not a security property — it is a
> naming convention.**
>
> Any START→POST change to protected administrative state attributable to the
> worker's run window is **`POLICY_VIOLATION`, §8 row 4.** **The snapshot is a
> RAW FILESYSTEM MEASUREMENT: no git command performs the comparison, and no git
> command produces either side of it.**
>
> A code path that skips a protected path by name or prefix raises
> **`AdminAllowlistPresent`**, an `InternalDispatcherError` — **raised, never
> logged-and-continued.**

**Revision 5's second excuse is deleted with it.** *"Objects are immutable and
content-addressed; a new object cannot change an existing one"* is **true, and it
is not the question. Alternates does not change an object; it changes which store
is consulted.** A documentation mutant `Z8-M13` guards its return: the string
*"immutable and content-addressed"* must not appear in the same section as the
object-store capture rationale.

##### What is protected is decided by DEPENDENCE, not by convenience

Sol §14 requires the determination to come from **actual dispatcher dependence**:

| Class | Does the dispatcher DEPEND on it? | Protected? |
|---|---|---|
| worktree `.git`, `commondir`, `gitdir` | **YES** — every path the raw resolver produces flows from them | **YES** |
| worktree `HEAD` + chain incl. `packed-refs` and `refs/**` | **YES** — B2's entire verdict | **YES** |
| `objects/info/alternates`, `http-alternates`, `objects/info/` listing | **YES at PREPARE** — Route B's `cat-file` resolves through them, and the seal's contents are decided by them | **YES** |
| `refs/replace/**`, `info/grafts` | **YES at PREPARE** — they change what every G-row read resolves to | **YES** |
| `objects/pack/` and loose-object listings | **NO for correctness** (nothing is read post-seal) — **YES for attribution**: it is what turns a deleted base blob from an unexplained failure into a named worker act | **YES, as evidence, not as a dependency** |
| `<gitdir>/index` | **NO** — ZI-19 deleted every index dependence; no index is read | **REPORT ONLY** |
| `<gitdir>/logs/**` (reflogs) | **NO** — nothing reads a reflog, and reflogs move as an ordinary consequence of the worker's own legitimate commits | **LISTING + hash only; a change is REPORTED, not a violation** |
| hooks | **YES at PREPARE** — `worktree add` is the one exec vector and the hook survives directory quarantine | **YES** |

> **`index` and `logs/**` are the two classes this design deliberately treats as
> report-only, and both are justified by MEASURED NON-DEPENDENCE, not by
> convenience. That distinction is the whole content of Sol's directive, and it
> is the line the fifth reviewer should attack — it is the same shape of
> judgement that produced the allowlist this section just deleted.**
>
> **The tripwire:** `test_report_only_admin_classes_have_no_reader` (AST) asserts
> no `src/**` code path opens `<gitdir>/index` or `logs/` for anything but the
> capture itself. **If any future section reads an index or a reflog, it must
> move these rows to protected in the same commit.** *(Escalated as **T-19**:
> Sol should rule explicitly rather than let it pass as integrated.)*
>
> **And the false-positive direction needs a killer too**, or the flag becomes
> routine — which is §5.9.4's named failure. `Z8-M25` (*promote `logs/**` changes
> to `POLICY_VIOLATION`*) is killed by
> `test_reflog_movement_is_reported_not_a_violation`.

##### Tests

| Test | Proves | Could it pass while false? |
|---|---|---|
| **`test_no_admin_allowlist_exists`** (AST + runtime) | no `src/**` path filters an administrative path by a `sol-` prefix or any name pattern; and at runtime the pre/post capture path **sets are identical** and contain every §5.8.2 row | **YES** if the filter is expressed as data loaded from config rather than as source. Closed by the runtime half: the captured path set is compared against a **generated expectation derived from the live repository layout**, not from a literal list in the test |
| `test_admin_capture_runs_no_git_command` | retained, now under the **fd-backed fork-safe** hook rather than an in-memory one | **NO** for in-interpreter spawns **including a forked child** — strictly stronger than revision 5's version |
| **`test_every_protected_class_has_a_divergence_test`** | one parameterised case per §5.8.2 row: mutate that file mid-run, assert row 4 (or *reported* for the two report-only classes) | **YES for a class not in the table** — which is what the `objects/info/` and `refs/**` **listing** rows exist to make visible. Stated, not claimed away |
| **`test_gitfile_redirect_makes_the_capture_describe_the_wrong_repo`** | **the §5.8.2A hole as a test**: on a build without the gitfile row, a redirected gitfile makes the capture read the FAKE repo's config and **the poisoned config is NOT SEEN**; with the row, it is `POLICY_VIOLATION` | **NO** — and note the control shape: the assertion on the unhardened build is *"the planted poison was NOT seen"*, which is a **positive demonstration that the capture was genuinely redirected** |

##### Cost

Raw reads of a few dozen small files plus directory listings; sub-millisecond,
twice per run. **The object-presence rows are the only ones with scale — 256
loose fan-out listings plus the pack directory — and are UNMEASURED at production
scale.** A bounded fallback (fan-out **counts and mtimes** rather than full name
lists) is available, is weaker, and is **not adopted without that measurement.**

##### Backward compatibility

**An existing baseline established under revision 5 does not contain the new
classes and therefore cannot reconcile**: it lands
`RepositoryAdministrationUnreconciled`, a PREPARE refusal, whose remediation is
the operator re-running `scripts/trust-repo-admin.py`. **That is correct and must
not be softened into "treat missing classes as matching"** — mutant `Z8-M26`,
killed by `test_baseline_missing_a_class_is_unreconciled_not_matching`.

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
the failure path — at `server.py:1037` (pre-worker), **`2127` (POST-WORKER)** and
`2410`. It is simultaneously **the most attractive S-α / S-β target in the
system**, a **live directive-A violation** (a `git status` in the post-worker
window), **blindable** three separate ways, and **structurally blind to
`.git/**`**, so a worker poisoning `$GIT_COMMON_DIR/info/attributes` permanently
is invisible to it. It also carries a **second** `resolve_base_commit(repo,
"HEAD")` — a symbolic resolution of exactly the kind §4.14 removes from the
dispatch path.

> ### INVARIANT ZI-59 — THE PRIMARY-TREE INVARIANT IS RAW, AND IT IS AN EQUALITY, NOT A CLEANLINESS
>
> **`PRIMARY_POST == PRIMARY_START`**, where both are built with **no git
> process**: a raw HEAD read, a dispatcher-owned `FsSnapshot`, and a §5.8
> `GitAdminSnapshot`.
>
> **No `git status` in any form, at any phase.** The dispatcher never runs
> `clean`, `reset`, `checkout`, `restore`, `stash`, `gc`, `prune` or
> `update-index`, and **writes no path under the primary work tree, ever, on any
> path including the failure path and the timeout path.**

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

**The eleven, recorded — and one precision that must not be lost.** Measured
today, read-only, `--no-optional-locks`, no index write, on
`/home/dev/full-voice-agent` at `06bfcd61`:

```
 M graphify-out/.graphify_labels.json      ?? .claude/worktrees/
 M graphify-out/GRAPH_REPORT.md            ?? .venv
 M graphify-out/graph.html                 ?? SECURITY_AUDIT_PROD_2026-07-24.md
 M graphify-out/graph.json                 ?? docs/superpowers/plans/2026-07-03-…md
 M graphify-out/manifest.json              ?? docs/superpowers/plans/2026-07-27-…md
                                           ?? graphify-out/.graphify_analysis.json
```

Five modified, six untracked.

> **"Eleven dirty entries" is a `git status` metric that does not exist in the
> model this section mandates.** It is `git status`'s count of a tree the raw
> model describes as **46,565 entries / 789.9 MB**, and **two of the eleven are
> DIRECTORIES** — `git status` collapses an untracked directory to one line while
> the `FsSnapshot` enumerates everything beneath `.venv/` and
> `.claude/worktrees/`.
>
> **The directive's intent — change nothing — is preserved and strengthened. Its
> metric must not be transliterated. No implementer may write
> `assert len(dirty) == 11` against a raw snapshot**; there is no `dirty` in a raw
> snapshot, and forcing one back would re-derive a `git status`-shaped view, which
> is the thing being deleted. **The raw obligation is: for each of those eleven
> paths, and every path beneath the two directories, the identity tuple is
> byte-identical across the run.** That is strictly stronger and differently
> shaped. *(Recorded as a directive/metric conflict; escalated as **T-21**.)*

**The invariant holds trivially over them and no cleanliness is required.**

**Two additions that revision 5 did not have and that are one-line mutants
without them:**

- **Symmetric fidelity.** `PRIMARY_START` and `PRIMARY_POST` must be captured at
  the **same** fidelity, and the fidelity is recorded in both. **Comparing a
  `stat_identity` START against a `content_hash_all` POST yields `None` on one
  side of every `content_hash` and reads as *unchanged* for any same-size
  modification.** The design does not currently forbid this.
  `test_primary_fidelity_is_symmetric`.
- **The write prohibition is machine-checked, not merely stated.** An integration
  test with a filesystem-write audit asserts **zero writes under the primary
  root** across a complete dispatch, a failing dispatch **and a timing-out
  dispatch**. **No existing test states this, and "no clean/reset/stash" is
  unenforceable without it — `git stash` is only the most obvious way to write
  there.** `test_dispatcher_writes_nothing_under_the_primary_root`. **COULD IT
  PASS WHILE FALSE? Yes if the write audit is not proven live** — it carries a
  deliberate write that must be observed.

**And the test that looks safest is the one that needs the most help.**
`test_primary_start_equals_post_on_an_untouched_dirty_tree` builds a throwaway
repository to production's *shape* — 5 modified tracked files, 6 untracked
entries **of which 2 are directories with many files beneath**, and at least one
ignored symlink. **COULD IT PASS WHILE FALSE? YES — two empty measurements
agree.** It must (i) assert the enumerated **entry count** equals the fixture's
known count, and (ii) carry its control **inside**: mutate one byte of one
modified file after START → assert `POLICY_VIOLATION`; restore; re-run → assert
clean. **Without (i) and (ii) a snapshot that silently failed to enumerate
passes.** The eleven-path shape fixture is **never run against
`/home/dev/full-voice-agent`** — the production repository is READ-ONLY.

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
ev  = load_canonical_evidence(task_id, run_index)   # worker_delta ONLY
att = load_attribution(task_id, run_index)

# ZI-16, strengthened: the bytes measured ARE the bytes on disk.
patch_bytes = ev.patch_path.stat().st_size
if patch_bytes != ev.patch_bytes or sha256_file(ev.patch_path) != ev.patch_sha256:
    raise EvidenceFreezeViolated(artefact="evidence/diff.patch")

budget = measured_review_input_budget(argv_block_without_patch)

review_input_complete = (
    patch_bytes <= budget
    and att.verdict == "attributable"
    and att.validation_delta is not None
)

if not ev.patch_file_complete:            # a PROPERTY, not a field (ZI-45)
    raise EvidenceIncompleteForReview(
        omitted=[(r.path, r.omission_reason)
                 for r in ev.per_path if r.omission_reason is not None])
if not review_input_complete:
    raise (EvidenceExceedsReviewBudget(...) if patch_bytes > budget
           else ReviewInputIncomplete(verdict=att.verdict))
# else: the ENTIRE file is read and passed. No slice exists on this path.
```

- **ZI-47 (FABLE CONSUMES `worker_delta` ONLY).** The patch section, path
  inventory and change counts derive from `worker_delta` and from the **frozen**
  worker canonical patch. **No byte of `validation_delta` enters a patch
  section.**
- **ZI-48 (REFUSE ON EITHER FLAG).** `patch_file_complete == False` **OR**
  `review_input_complete == False` ⇒ **REFUSE.**
- **ZI-49 (VALIDATION IS A SEPARATE SECTION)**, labelled *dispatcher-executed*,
  never merged into the patch or the inventory.
- **ZI-50 (THE PROMPT NAMES THE AUTHOR OF EVERY PATH IT SHOWS).** A non-empty
  `both_authors` carries a **mandatory sentence**; an empty `validation_only`
  section is rendered as an explicit *"none"*, **never omitted** — **an absent
  section reads as "nothing happened", which is this design's own Shape 2.**

**Why F-1 cannot recur here.** The guard still reads `patch_file_complete` — but
under **ZI-37** there is no longer any class for which *"clears the flag"* and
*"blocks the review"* differ, **so a flag-predicate and a class-predicate are the
same predicate.** The fourth review offered two repairs — restate the guard over
classes, or split the flag — and **both are taken**: the guard reads both flags
(B-I7, finally used), **and the classes were made consistent with the flag rather
than the guard being weakened to fit them. The third column is deleted; that is
what makes the guard safe, rather than the guard being made cleverer.**

**Prompt structure:**

```
SECTION 1  TASK                      envelope text
SECTION 2  WORKER CHANGES            the complete canonical patch over
                                     worker_delta — inline, whole, unclipped
SECTION 3  WORKER CHANGE INVENTORY   every worker_delta path: display form,
                                     change, mode, size, sha256
SECTION 4  DISPATCHER VALIDATION     argv, exit code, timed_out, bounded tails.
                                     Header: "executed by the dispatcher after
                                     the worker exited. NOT Claude's work."
SECTION 5  VALIDATION FILESYSTEM     validation_only paths; both_authors with the
           EFFECTS                   mandatory sentence; validation_reverted.
                                     Rendered as "none" when empty (ZI-50).
SECTION 6  COMPLETENESS              "Every changed path is represented above."
                                     A tautology under ZI-44 — if it were false
                                     the review already refused.
```

The mandatory sentence for a non-empty `both_authors`:

> *N path(s) shown above were modified by dispatcher validation after the worker
> exited. The patch above is the worktree as the worker left it, not as it is
> now: `<paths>`.*

Both refusals are **PREPARE-phase, §8 row 0**: no reviewer tokens spent, no run
index consumed, `state.json` byte-identical.

**Tests whose non-vacuity is the whole point:**

| Test | The assertion that closes it |
|---|---|
| `test_fable_is_not_blocked_by_validation_created_artifacts` — **the direct replacement for B-3's killer, the one the fourth review found could not pass.** Worker changes one text file; validation creates **200** files under `dist/` | assert `validation.json[0].exit_code == 0` **and** `len(validation_delta) == 200` (**not `>= 0`**) — otherwise it passes because validation never ran. **Checked against the mechanism: `dist/**` ∈ `validation_delta` ⇒ ∉ `worker_delta` ⇒ the IFF ranges over a set that does not contain them ⇒ flag `True` ⇒ the guard does not raise. This test CAN pass against the mechanism specified here. It could not pass against revision 5's.** |
| `test_worker_run_build_is_complete_and_refuses_only_on_the_budget` — **paired, same fixture, two budgets** | (i) large budget: flag `True`, review proceeds, **all 200 appear as full patch sections**; (ii) budget parameterised small: flag **still `True`**, `review_input_complete` `False`, the exception is `EvidenceExceedsReviewBudget` **and not** `EvidenceIncompleteForReview`. **A build that always refuses fails (i); a build that never refuses fails (ii). Neither direction alone is a test.** |
| `test_fable_refuses_when_a_worker_binary_change_has_no_representation` | assert the exception **type**, because it could otherwise pass for the wrong reason if the run also exceeded the budget |
| `test_review_refusal_leaves_state_json_byte_identical` | **and** assert `refusals.jsonl` grew by one row — **that second assertion is what distinguishes "refused and recorded" from "nothing happened"** |
| `test_review_prompt_bytes_are_the_patch_bytes` | **three-way**: argv element ≡ `ev.patch_sha256` ≡ sha256 of the file on disk. **A two-way version passes if both sides read the same wrong file** |
| `test_both_authors_sentence_is_in_the_prompt` | **paired negative**: a run with empty `both_authors` must **not** contain it and must contain section 5 rendered as *"none"* — otherwise an unconditional sentence passes |

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
| **`SYMLINK`** — **SUPPORTED, new in revision 6** | **no** | **no** | **the content: mode `120000`, body = raw `readlink` bytes** |
| `UNREPRESENTABLE_KIND` — **narrowed to FIFO / socket / block device / char device / gitlink** | yes | **yes** | path, `st_mode`, type name |
| ~~`BULK_CREATED_IGNORED`~~ | — | — | **DELETED as a class** (§5.5.9). The rollup omitted content while the third column said *"does not block"*, which is F-1 |
| `OVERSIZED` | yes | **yes** | refusal |
| `UNREADABLE` / `CHANGED_DURING_MEASUREMENT` | yes | **yes** | refusal |

> **THE THIRD COLUMN IS GONE, AND WITH IT F-1.** In revision 5 the second and
> third columns disagreed for three classes, and §5.11.3's guard read only the
> second. **They are now the same column, enumerated over `ContentClass.__members__`
> by `test_no_class_is_exempt_from_the_completeness_iff`.** `UNTEXTUAL` moves to
> `(yes, yes)` — revision 5's §5.5.9 said `(yes, no)` and its §5.11.5 said
> `(yes, yes)`, and **a build carrying two tables cannot pass the enumeration.**
>
> **`IGNORED_BY_BASE` is gone** (B-3, revision 4). **`BULK_CREATED_IGNORED` is
> gone** (F-1, revision 6). **Neither is amended; both are deleted** — §5.8.5's
> own rule for mutually exclusive designs.

**Why symlinks are SUPPORTED rather than exempted, and why that is what makes
Y-10 ratifiable.** Revision 5 exempted `UNREPRESENTABLE_KIND` from blocking
because **this repository contains 4 ignored symlinks and production contains 1**,
so under revision 2's rule every Fable review of either repository was dead for a
reason unrelated to the task. **That exemption was the right instinct and the
wrong mechanism: it created the third column.** Sol's §11 rule removes **both**
horns of Y-10 at once:

- the horn where §5.11.5 is authoritative — *one symlink kills every production
  review* — is gone, because a symlink is **SUPPORTED** and never clears the flag;
- **and independently**, the production symlink is **unchanged**, so under ZI-44
  it is **absent from `worker_delta`** and the IFF never ranges over it;
- the horn where §5.5.9 is authoritative — *content omitted under a true flag* —
  is gone, because a symlink's content is now **in** the patch.

**Two independent reasons, and `test_a_single_unchanged_symlink_blocks_nothing`
asserts the second one directly.** *Y-10 is now ratifiable for the symlink half;
what remains outstanding is named in §17 rather than force-mapped.*

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
    seal-manifest.json             NEW  the root of trust; written LAST, atomically
    repo-authority.json            NEW  RepositoryAuthoritySnapshot  (§5.5.2C)
    base-tree.json                       BaseTreeSnapshot + content_ref per entry
    base-reconciliation.json             BaseReconciliation
    primary-start.json             NEW  PrimaryStartSnapshot (identity only)
    fs-snapshot-start.json         MOVED from runs/NNN/ — it is per-TASK
    cas/<oid[:2]>/<oid[2:]>              SEALED base bytes + captured START bytes,
                                         keyed by git-blob-sha1, self-verifying
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
| `BaseTreeSnapshotFailed` | `GitEvidenceCollectionFailed` | PREPARE | refusal, no run consumed |
| **`BaseBlobUnreadable`** | `GitEvidenceCollectionFailed` | **PREPARE ONLY** | refusal, no run consumed. `details` name the **oid**, the **path**, the **route** (`start_walk` / `cat_file_batch`), the **rc**, and whether `extensions.partialClone` was present. **See ZI-60 below** |
| **`BaseObjectVerificationFailed`** | `GitEvidenceCollectionFailed` | **PREPARE ONLY** | refusal. The bytes returned did not hash to the requested oid — **a genuinely different failure from "absent", and the two must not be collapsed into one code** |
| **`SealBudgetExceeded`** | `DispatcherError` | **PREPARE ONLY** | refusal, no run consumed, `state.json` sha256 identical |
| **`SealIntegrityFailed`** | `DispatcherError` | PREPARE / FINALIZE | PREPARE (**no worker ever ran for this task**) → refusal · **any run has `ownership.json`** → **`POLICY_VIOLATION`, §8 row 4** |
| **`SealAbsentAfterWorker`** | `DispatcherError` | FINALIZE | `FINALIZATION_FAILED`. **The seal is NEVER reconstructed** |
| **`SealProvenanceInvalid`** | `InternalDispatcherError` | any | a dispatcher defect: a seal whose `sealed_at` postdates `ownership.json`. Raised, never logged-and-continued |
| **`WorktreeIndirectionChanged`** | `DispatcherError` | FINALIZE | **`POLICY_VIOLATION`, §8 row 4.** It is a worker write to protected administrative state and, unlike a moved HEAD, **it is never innocent** |
| **`StoreRoutingUnreadable`** | `DispatcherError` | PREPARE | refusal |
| **`RepositoryAuthorityCaptureFailed`** | `DispatcherError` | PREPARE / FINALIZE | PREPARE → refusal · **FINALIZE → verdict `unknown`, treated as TAMPER, never as clean** |
| **`AdminAllowlistPresent`** | `InternalDispatcherError` | any | a code path that skips a protected path by name or prefix. **Raised, never logged-and-continued** |
| **`GitBeforeEstablishment`** | `InternalDispatcherError` | PREPARE | a git invocation with no establishment marker on the current `ToolExecution` (§5.4.3B) |
| **`WorkerAttributionAmbiguous`** | `DispatcherError` | FINALIZE | `FAILED` at **row 5a, only if rows 4 and 5 did not fire.** Sets `patch_file_complete = False` |
| **`ValidationAttributionUnknown`** | `DispatcherError` | FINALIZE | `FAILED` at **row 5a**, same condition. Sets `review_input_complete = False`; **`patch_file_complete` is left as produced, because the worker patch is honestly complete** |
| **`WorkerExitSnapshotMissing`** | `DispatcherError` | FINALIZE / recovery | `FINALIZATION_FAILED`. Streams and evidence preserved, index never reused, **never re-measured** (ZI-34) |
| **`AttributionClosureViolated`** | `InternalDispatcherError` | FINALIZE | `final_delta \ (worker ∪ validation)` non-empty contradicts Z9-T1 |
| **`EvidenceFreezeViolated`** | `DispatcherError` | FINALIZE | **row 4**, `attributed_to="validation"`, naming every artefact whose sha256 changed |
| **`ValidationTouchedAdministrativeState`** | `DispatcherError` | FINALIZE | row 4, `attributed_to="validation"`, decided from capture #1 vs capture #2 |
| **`ValidationTouchedPrimaryTree`** | `DispatcherError` | FINALIZE | row 5, `attributed_to="validation"` |
| **`ProductionBaseRefNotExact`** / **`BaseRefNotACommitObject`** / **`BaseCommitAbsent`** | `DispatcherError` | PREPARE | refusal, row 0 (§4.14) |
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

> ### INVARIANT ZI-60 — `BaseBlobUnreadable` EXISTS ONLY DURING PREPARE (Sol §13, closes F-3)
>
> Revision 5 specified this class **three ways and no two agreed**: §5.4.3
> implied FINALIZE (the lazy read) landing `§8 row 3` `FAILED`; §5.12 said PREPARE
> refusal; and **§8 row 3's own enumeration did not contain it at all.** §5.12's
> row was **unreachable by construction**, because DECISION Z-5 moved `cat-file`
> to FINALIZE.
>
> **And §5.4.3's row was a laundering route.** Row 3 is **above** rows 4 and 5,
> and §8's own comment marks the boundary — *"from here the inventory EXISTS, so
> policy is ALWAYS decided."* **A worker that makes a forbidden write and then
> `rm`s one loose base blob lands `FAILED` at row 3, and the scope violation and
> the tamper verdict are never decided.**
>
> **Because the whole `BaseTreeSnapshot` — identity AND content — is sealed
> before the worker exists, there is no post-worker base read. There is therefore
> no post-worker `BaseBlobUnreadable`, and ALL post-worker precedence rows for it
> are DELETED. The route does not exist because the read does not exist.**
>
> §5.12's row becomes **reachable and correct for the first time.** §8 row 3's
> enumeration is left alone, because `BaseBlobUnreadable` never belonged there.

**And F-3's distinguishability problem is answered differently, not argued
away.** F-3 notes that `rc=128` on an absent object is byte-identical to genuine
corruption and *"nothing distinguishes 'the worker removed this' from 'this was
never there'."* **Under the seal the dispatcher knows which**: the object was read
and verified into `cas/` **before the worker existed**, so its later absence from
the repository is a **change**, measured by §5.8.2's object-presence listing
comparison, attributable to the run window, landing **`POLICY_VIOLATION` at row
4 on its own evidence** — not an inventory failure, and **not something the
dispatcher only learns by trying to read it and failing. The ambiguity was a
consequence of reading late.**

**The conflict-set test must still be extended, and it is the more valuable
half.** `test_deliberately_conflicting_run_lands_policy_violation`'s set grows
from *timeout + out-of-scope + 429 + symlink + FIFO + oversized + non-UTF-8 name*
to additionally include **a deleted loose base blob**, **a planted
`objects/info/alternates`**, and **a rewritten `<worktree>/.git` gitfile.**

> **COULD IT PASS WHILE FALSE? YES, in a way that must be guarded.** If the seal
> makes the deleted blob a non-event, this test passes for a reason unrelated to
> the deletion — **it would pass even against a build that laundered the deletion
> into `FAILED`, because some other conflict in the set already lands
> `POLICY_VIOLATION`.** So the deletion needs its **own single-cause test**:
> **`test_deleted_base_blob_alone_lands_policy_violation`**, whose only conflict
> is the deleted blob and whose assertion is row 4, plus
> **`test_deleted_base_blob_after_launch_does_not_change_the_verdict`** — a
> Z-RULE-1B integrity control: with the seal **disabled** (a build flag the test
> flips), deleting a loose base blob mid-run **changes** the run's landing; with
> the seal on, the same deletion changes **nothing** — same patch bytes, same
> verdict. **Without the disabled-seal arm, this test would pass against a build
> where the base blob was never consulted for an unrelated reason.**

### 5.13 Crash points

Subsystem B's rows are **C1–C13, C15 and C16–C20 of the canonical matrix
(§15)**. This
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
| **ZM-D6** split `ls-tree -z` on the last TAB | `test_base_tree_snapshot_matches_ls_tree_for_hostile_names` |
| **ZM-D7** *(new)* restore `--long` to the default `ls-tree` argv | `test_base_tree_argv_has_no_long_flag` **and** `test_absent_base_object_executes_nothing` (the S-δ sentinel, with its positive control) |
| **ZM-D8** *(new)* drop `GIT_NO_LAZY_FETCH=1` from `_git_env` | `test_absent_base_object_executes_nothing` |
| **ZM-D9** *(new)* drop `-c core.hooksPath=<empty>` from the argv policy | `test_worktree_add_executes_no_planted_hook` (positive control: the same argv without the pin **must** fire) |
| **ZM-D10** *(new)* disarm S-δ by blanking `extensions.partialClone` / `remote.*.promisor` instead of `GIT_NO_LAZY_FETCH` | `test_absent_base_object_executes_nothing` — **measured: both still fire** |
| **ZM-E1** run the admin capture after `worktree add` | `test_unreconciled_admin_state_refuses_before_worktree_add` |
| **ZM-E2** capture with `git config --list` | `test_admin_capture_runs_no_git_command` |
| **ZM-E3** treat a missing baseline as "trust current" | `test_missing_baseline_refuses` |
| **ZM-E4** treat a FINALIZE capture failure as clean | `test_admin_capture_failure_is_tamper` |
| **ZM-E5** re-establish the baseline automatically after divergence | `test_divergence_persists_across_dispatches` |
| **ZM-E6** stop following `include.path` | `test_include_path_indirection_is_followed` |
| **ZM-E7** re-introduce the clean `GIT_INDEX_FILE` + `ls-files -v` audit | `test_finalize_journal_is_empty` — **and it now also catches `read-tree`'s return, since that row is deleted from the permitted set entirely** |
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

### 5.17 Trusted validation is an EXECUTION DOMAIN, not an authority domain (Sol §10, closes F-4)

#### 5.17.1 Current failure — measured, not inferred

```python
# src/sol_claude_dispatcher/validation.py:223-236
argv = list(cmd.argv)                              # <- from the ENVELOPE
child_env = validation_environment() if env is None else dict(env)
proc = await asyncio.create_subprocess_exec(
    *argv,                                         # <- argv[0] is CALLER DATA
    cwd=str(cwd),                                  # <- the TASK WORKTREE
    env=child_env,                                 # <- NOT _git_env()
    start_new_session=True,
)
```

**Every claim below reproduces against the tree at `d197bf0`.**

1. **`argv[0]` may be `"git"`.** `models.py:355-366` rejects exactly
   `{sh, bash, zsh, dash, ksh, fish}` and a NUL byte in `argv[0]`.
   `["git","diff","--exit-code"]`, `["git","status","--porcelain"]` and
   `["git","diff","--stat"]` are all legal `ValidationCommand`s. ***"Prove the
   tree is clean"* is an entirely ordinary declared validation.**
2. **It runs post-worker, between the two evidence collections** —
   `server.py:2004` B2 → `2038` evidence A → `2103` `run_validations` → `2117`
   evidence B → `2454` `write_full_diff`.
3. **§6.6 makes it run MORE often, not less**: post-timeout trusted validation is
   a brief §17 requirement and this design keeps it.
4. **None of §5.4.3A's policy applies.** `validation_environment()`
   (`validation.py:92-120`) is a **denylist**: it drops `SOL_DISPATCHER_*`, three
   worker markers, and any key whose upper-case name contains a
   `SECRET_ENV_MARKERS` substring. **It does not strip the eight `GIT_*` redirect
   variables `_git_env()` strips, does not set `GIT_TERMINAL_PROMPT` or
   `GIT_OPTIONAL_LOCKS`, and sets none of PIN 1 / PIN 2 / PIN 3.** Both pin
   families are absent on this path **by construction**.
5. **Neither test can see it.** `git-invocations.jsonl` is written by `_run_git`;
   this is not `_run_git`. And revision 5's AST predicate is *"the first argv
   element is the literal `"git"`"* — **here `argv[0]` is `cmd.argv[0]`, an
   envelope field. The AST test is green while the path is live.**

**And Z7 measured that it contributes authority TODAY.** `server.py:1962-1972`
states outright that *"the authoritative scope and policy decision uses the
**final** state"*:

```
  [2040] evidence A  status :  M src.txt
  [2116] evidence B  status :  M src.txt ?? OUT-OF-SCOPE.txt
  [2123] check_scope sees the file the VALIDATION command wrote, not the worker
```

**And it is worse than a file.** A validation command that plants
`refs/replace` — a plain file write, no git needed:

```
  [2005] B2  rev-parse --verify HEAD^{commit} : a592e5d4…   (expected a592e5d4…)
  [2453] write_full_diff  git diff <base>     :
           --- a/src.txt
           +++ b/src.txt
           @@ -1 +1,2 @@
           -FORGED
           +BASE
           +WORKER-EDIT
```

> **The old side of the reviewed patch is fabricated while the commit oid
> verifies.** `diff.patch` is the artefact Fable reads.

#### 5.17.2 The invariant — authority, not containment

- **ZI-40 (VALIDATION IS AN EXECUTION DOMAIN).** *Trusted validation **may**
  execute worker-controlled project code, including `git`, including a program
  the worker wrote, including anything that program spawns. The design does not
  pretend otherwise.* The invariant is **narrow and total**:

  > **No validation command, and no descendant of one, contributes repository
  > identity, the B2 base verification, the trusted administrative baseline,
  > scope, `patch_file_complete`, `review_input_complete`, the canonical patch,
  > any `PathIdentitySet`, the primary-tree verdict, or any row of
  > `git-invocations.jsonl`.**

- **ZI-41 (NO OS CONTAINMENT IS CLAIMED).** `start_new_session=True` creates a
  new session and process group. **It is not a sandbox.** Same uid, same
  filesystem, same network, no namespace, no seccomp, no rlimit beyond
  `cmd.timeout_seconds`. `_terminate` signals **one process group**; **a
  descendant that calls `setsid(2)` leaves that group and survives.** *(Stated
  from the mechanism; `os.killpg` signals one pgid by definition.
  **`REQUIRES-PROBE` if Sol wants it asserted rather than assumed — and note that
  assuming the SAFE direction here means assuming the escape WORKS, which is the
  fail-closed assumption.**)* **No sentence in `docs/**` or `src/**` may describe
  validation as sandboxed, isolated, contained, confined or jailed**, and a
  documentation test asserts it.
- **ZI-42 (SEPARATE JOURNAL).** Every validation spawn attempt appends one row to
  `runs/NNN/validation-invocations.jsonl`. **It is a different file from
  `git-invocations.jsonl` and the two are disjoint by construction**, because one
  is written by `_run_git` and the other by `run_validation_command`.
- **ZI-43 (VALIDATION SPAWNS ARE NOT AUTHORITY).** A validation command whose
  `argv[0]` basename is `git` is recorded `is_git: true, authority: false` and
  **must not appear in `git-invocations.jsonl`.** §5.4.5's *"the FINALIZE window
  is empty"* remains exact **only because the two journals are disjoint**, which
  `test_the_two_journals_are_disjoint` asserts directly.

#### 5.17.3 The ordering, and what each seam buys

| # | Step | Why here and not elsewhere |
|---|---|---|
| 10 | **raw B2 / admin capture #1** | before any measurement is trusted. If HEAD moved during the run, every measurement below describes a tree that never existed |
| 11 | **WORKER_EXIT snapshot** | **the last moment at which the tree is the worker's and nothing else's** |
| 12–15 | **worker scope / evidence complete** | everything attributed to Claude is produced **before the dispatcher executes any worker-controlled program.** This is the ordering that makes ZI-40 achievable **without containment** |
| 16 | **evidence freeze** | the detection baseline for step 19 |
| 17 | **trusted validation** | the execution domain |
| 18 | **POST_VALIDATION snapshot** | attribution input |
| 19 | **admin capture #2 + freeze re-hash** | **two post-worker admin captures, not one.** With one capture you cannot tell whether the worker or a validation command planted the hook |

**Ordering and a separate journal are NECESSARY AND NOT SUFFICIENT.** They do not
help against a validation-planted `refs/replace`, because it survives the command
and poisons everything downstream. **The only measured answer is §2A's zero —
plus re-verifying the sealed administrative fingerprint AFTER validation and
treating any change as TAMPER.** That is step 19, and it is why it exists.

#### 5.17.4 The evidence freeze — the mechanism that makes ZI-40 true rather than asserted

```python
# freeze.py — WAVE 0. Plain file I/O. No git process.
@dataclass(frozen=True)
class EvidenceFreeze:
    schema_version: int
    taken_at: str
    entries: tuple[tuple[bytes, str, int], ...]   # (relpath, sha256, size), sorted
    root_digest: str                              # sha256 over the ordered records
```

Written at step 16 over `evidence/**` and
`runs/NNN/{fs-snapshot-start.json, fs-snapshot-worker-exit.json,
path-inventory.json}`; recomputed at step 19 and compared **record-wise**.

**What it does and does not do, stated honestly:**

- **It DETECTS. It does not PREVENT.** A validation command runs as the same uid
  and can open `evidence/diff.patch` by absolute path. **Prevention is not
  available under `docs/SECURITY.md`'s same-user threat model** — moving the
  evidence elsewhere, `chmod`, or a different `cwd` all fail to the same absolute
  path. **Detection is the whole of what is on offer and the design must say so.**
- On mismatch **the artefact is already overwritten**; the run lands row 4 with
  `EvidenceFreezeViolated` naming each changed file. **The correct claim is
  "detected and failed closed", never "the worker patch was protected."**

#### 5.17.5 Environment and secrets — Sol's ruling, and the one gap inside it

Per Sol: **run validations with the existing sanitized environment and no
dispatcher secrets.** `validation_environment()` is therefore **not** replaced by
`_git_env()`, **no pins are applied**, and `git` remains a legal `argv[0]`. That
ruling is implemented as given.

**The gap inside the ruling, named rather than silently kept.**
`validation_environment()` does not strip `GIT_DIR`, `GIT_WORK_TREE`,
`GIT_COMMON_DIR`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`,
`GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_CEILING_DIRECTORIES` or `GIT_NAMESPACE`.
**If the operator's own shell exports any of them, a `git` validation command
inherits a DISPATCHER-SIDE redirect.** That is not "hardening the git call" — it
is **dispatcher leakage**, squarely inside *"no dispatcher secrets, sanitized
environment"*. *(Escalated as **T-22**. Recommendation: strip them — one loop, no
pins, no `-c`, no behaviour change for any non-git command. It is the cheapest
decidable improvement in this section and it does not touch the ruling.)*

**The prohibition Sol did not take, recorded so it is not re-derived.** The
fourth review's option 1 was *"prohibit `git` as `ValidationCommand.argv[0]`"* —
one `field_validator` line, decidable, and **the only answer that makes §16's
`V-1` row provable rather than merely restated.** Sol's directive keeps `git`
legal. **The cost of that choice, stated: `V-1` and `Y-1` must be RESTATED, and
the four armed surfaces S-α…S-δ are REACHABLE on the validation path with no
pins. This is a residual, not a closed item.** A mutant that *adds* the
prohibition is **ZM-V6**, and it has a killer
(`test_git_validation_command_is_accepted_by_the_envelope_validator`) **precisely
so the prohibition cannot be acquired by accident either** — a lane that "fixes"
F-4 by prohibiting `git` silently breaks every caller that declared one, and the
prohibition must be Sol's, taken deliberately, with `V-1` rewritten to match.

*(If Sol does take it: the check must be on the **basename of the resolved
executable**, not the raw string — `/usr/bin/git` and `["env","git",…]` are
MEASURED to defeat a raw-string check — and **it is a cost-raiser, not a
closure**, because a validation command can reach git through a script one level
down. **The closure is that nothing it produces is authority.**)*

#### 5.17.6 Journal row shape

```json
{"ts":"…","index":0,"phase":"POST_WORKER",
 "program":"git","argv_sha256":"…","argv_len":3,
 "cwd_role":"task_worktree","authority":false,"is_git":true,
 "env_policy":"validation_environment/1","pins_applied":[],
 "pid":41231,"pgid":41231,"start_new_session":true,
 "returncode":0,"timed_out":false,"sigkill":false,"duration_ms":94,
 "descendants_observed":null}
```

`"program"` is the **basename only**, bounded at 64 characters — **arguments are
where credentials, hostnames and repository paths live and none of them belongs
in a journal**; `argv_sha256` covers the whole argv so the row is still pinnable.
**`"descendants_observed": null` is deliberate: the dispatcher does not track
descendants and must not imply that it does** (ZI-41). **`"pins_applied": []` is
a literal empty list, not an omitted key — the absence of pins is a recorded
fact.**

#### 5.17.7 The acceptance table Sol's directive requires

`patch_file_complete` and the worker patch are **never** affected by any row.

| Validation did this | Worker patch | `patch_file_complete` | Fable | Task ladder |
|---|---|---|---|---|
| created a path not in `worker_delta` (`dist/`, `coverage/`, caches) | unaffected | unaffected | **proceeds**; the path is in prompt section 5, never section 2 | none |
| modified a path **in** `worker_delta` | frozen at WORKER_EXIT | unaffected | **proceeds**; the `both_authors` sentence is **mandatory** | none |
| deleted a path in `worker_delta` | frozen; the addition still shows | unaffected | proceeds; `validation_reverted` reported | none |
| wrote a `forbidden_paths` path | unaffected | unaffected | proceeds | **row 5 `POLICY_VIOLATION`, `attributed_to="validation"`** |
| wrote a path outside `allowed_paths` | unaffected | unaffected | proceeds | **none** — `allowed_paths` bounds the worker |
| wrote under `.git/` or `$GIT_COMMON_DIR/` | unaffected | unaffected | **REFUSE** | **row 4 TAMPER, `attributed_to="validation"`** |
| changed a file in `evidence/` | **already overwritten on disk** | unaffected *as produced*; the artefact is corrupt | **REFUSE** | **row 4, `EvidenceFreezeViolated` naming the file** |
| moved HEAD in the task worktree | unaffected — **B2 already ran, raw, at step 10** | unaffected | REFUSE | row 4 |
| touched the primary tree | unaffected | unaffected | REFUSE | **row 5, `attributed_to="validation"`** |
| POST_VALIDATION snapshot unmeasurable | frozen, stands | **left as produced** | **REFUSE** | `ValidationAttributionUnknown` → row 5a, only if 4 and 5 did not fire |

**In every one of the last three rows the TASK verdict is decided before the
attribution failure is consulted, so no attribution failure ever launders a
policy violation into `FAILED`** — F-3's shape, avoided by construction rather
than by care.

> **A validation-caused `POLICY_VIOLATION` punishes the task for something the
> dispatcher did.** That is real and it is kept, with `attributed_to` and a
> remediation string naming the envelope's `[validation]` block as the defect.
> **Failing open would be a laundering channel** — a caller-declared
> `["cp","secrets/x","forbidden/y"]` would write a forbidden path with no policy
> consequence — and inventing a distinct terminal state changes §8's row set and
> every state consumer. *(Escalated as **T-23**.)*

#### 5.17.8 Crash points

| Row | Crash between | Recovery rule |
|---|---|---|
| **C19** | `evidence-freeze.json` fsync and the first validation spawn | freeze present, no invocation rows → validation is **unknown**, **never "none ran"**; `ValidationAttributionUnknown` |
| **C20** | a validation spawn and its reap | **the child outlives the dispatcher**: `start_new_session=True` means the dispatcher's death does not signal it. The row has no `returncode`; the run is `FINALIZATION_FAILED`; **the recovering dispatcher must not adopt, signal, or wait on it** — it holds no `WorkerHandle` for it, and §7.5's rule that an exit status is not recoverable after dispatcher death applies identically |

**C20 is a genuinely new hazard revision 5 does not name:** a validation command
can outlive the dispatcher and keep writing to the task worktree *after* recovery
has read it. **The honest consequence is that a recovered run's attribution is
`unknown` and Fable refuses; claiming otherwise would be a containment claim.**

#### 5.17.9 Tests

| Test | The assertion that makes it non-vacuous |
|---|---|
| `test_git_is_a_legal_validation_command_and_is_journalled_without_authority` — envelope declares `["git","diff","--exit-code"]` | assert `validation.json[0].exit_code is not None` (otherwise it passes with validation disabled), **and compute the argv hash independently in the test** so a helper writing the row cannot satisfy it |
| **`test_validation_cannot_silently_change_the_frozen_evidence`** — **Z-RULE-1B** | (a) arm a validation command that opens `evidence/diff.patch` by absolute path and writes `PWNED`; **(b) positive control: run the same fixture under a build with the revision-5 ordering and assert the stored patch IS `PWNED`, proving the arming command genuinely reaches the file**; (c) clear; (d) production: row 4, `EvidenceFreezeViolated`, `attributed_to == "validation"`. **Note what (d) does NOT assert: it does not assert the patch content survived. It did not. A test asserting survival would be asserting a property the mechanism does not have** |
| **`test_validation_touching_git_admin_is_row_4_attributed_to_validation`** | **the landing is identical under a single-capture build and only the attribution differs** — so `attributed_to == "validation"` **is the whole test**, and it is unsatisfiable without capture #1 **and** capture #2. **This is why step 19 exists** |
| `test_validation_environment_carries_no_dispatcher_secret` | **the test must INJECT `SOL_DISPATCHER_TOKEN` and `MY_API_SECRET` into `os.environ` for the duration** and assert both are absent from the child's view — otherwise it is green because the host happened to have no such key. **A negative assertion needs a planted positive** |
| `test_no_document_or_docstring_claims_validation_is_contained` | greps `docs/**` and `src/**` for `sandbox`, `isolated`, `jail`, `contained`, `confined` near `validation`. **A cheap corroborator, not a proof — yes to a paraphrase, recorded as such** |
| `test_validation_created_out_of_scope_file_is_not_a_policy_violation` **paired with** `test_worker_out_of_scope_write_is_a_policy_violation_even_when_validation_reverts_it` | **the second is the direction a naive fix breaks** |

#### 5.17.10 Named mutants

| Mutant | Named killer |
|---|---|
| **ZM-V1** route validation git through `_run_git` "to harden it" | `test_the_two_journals_are_disjoint` |
| **ZM-V2** run validation before the WORKER_EXIT snapshot | `test_worker_exit_snapshot_precedes_the_first_validation_spawn` |
| **ZM-V3** compose the patch after validation *(this is the tree today)* | `test_worker_patch_is_frozen_before_validation_runs` |
| **ZM-V4** collapse the two post-worker admin captures into one | `test_validation_touching_git_admin_is_row_4_attributed_to_validation` |
| **ZM-V5** drop `validation-invocations.jsonl` | `test_git_is_a_legal_validation_command_and_is_journalled_without_authority` |
| **ZM-V6** prohibit `git` as `argv[0]` **without a Sol ruling** | `test_git_validation_command_is_accepted_by_the_envelope_validator` |
| **ZM-V7** claim containment in a docstring or a design sentence | `test_no_document_or_docstring_claims_validation_is_contained` |
| **ZM-V10** apply `allowed_paths` to `validation_delta` | `test_validation_created_out_of_scope_file_is_not_a_policy_violation` |
| **ZM-V11** exempt `validation_delta` from `forbidden_paths` "because the dispatcher wrote it" | `test_validation_command_writing_a_forbidden_path_is_a_policy_violation_attributed_to_validation` |
| **ZM-V13** kill the process group and record `descendants_observed: 0` | `test_no_document_or_docstring_claims_validation_is_contained` — **it is a containment claim in data** |

#### 5.17.11 Backward compatibility

`ValidationCommand`, `run_validation_command`, `run_validations` and
`validation.json` are **unchanged in shape**; no envelope breaks.
`validation_environment()` is unchanged unless Sol takes T-22. The two-journal
split is additive and nothing reads `validation-invocations.jsonl` today.
**§16's `V-1` row and §17's `Y-1` headline change text — a documentation break
§16's own gate-report checker asserts, and the third revision in which those two
sentences have been false. They are corrected in this revision, not deferred.**

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
                                    CheckoutTransformationBudgetExceeded,
                                    ProductionBaseRefNotExact,
                                    BaseRefNotACommitObject, BaseCommitAbsent,
                                    RepositoryNotAllowed,
                                    RepositoryLayoutUnreadable,
                                    GitBeforeEstablishment,
                                    BaseBlobUnreadable,
                                    BaseObjectVerificationFailed,
                                    SealBudgetExceeded,
                                    SealIntegrityFailed (no worker ever ran))

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
                                   NEW in revision 6: store-routing divergence
                                   (alternates, refs/replace/**, info/grafts,
                                   objects/info listing), WorktreeIndirection-
                                   Changed, SealIntegrityFailed once any run has
                                   ownership.json, EvidenceFreezeViolated, and
                                   ValidationTouchedAdministrativeState — the
                                   last two carrying attributed_to="validation".
                                   A DELETED BASE BLOB lands HERE, on the
                                   object-presence listing's own evidence, not
                                   at row 3 (§5.12, ZI-60).

 5. scope violation /           -> POLICY_VIOLATION. Outranks worker success, and
    primary-tree interference      outranks EVERY content-level refusal.
                                   A symlink, FIFO, oversized, unreadable or
                                   non-UTF-8-named path that is OUT OF SCOPE
                                   lands HERE on its authoritative path.
                                   It is NOT laundered into FAILED.

 5a. path identity              -> FAILED, ONLY IF rows 4 AND 5 did not fire.
     unrepresentable, OR              PathIdentityUnrepresentable /
     attribution ambiguous            WorkerAttributionAmbiguous /
                                      ValidationAttributionUnknown.
                                   Scope is decided over
                                   worker_delta u validation_delta, which
                                   EXISTS under ambiguity — so rows 4 and 5 are
                                   always reachable and an attribution failure
                                   can never launder a policy violation into
                                   FAILED. A new row 5b was considered and
                                   REJECTED: it would change the row count that
                                   §12 and §16 assert, for no behavioural
                                   difference. Recorded, not adopted.

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
| **revision 4's own "structural property of object-store reads"** | the paragraph reasoned from *category* — object reads are local, therefore inert — with **no experiment behind it at all**, and it was **false**: `cat-file --batch` and `ls-tree --long` execute the worker's transport program via promisor lazy fetch (S-δ). It was written **in the same revision** that added S-γ after the identical mistake | §5.4.1 — the paragraph is **quoted and deleted**; the repertoire is measured on four surfaces; PIN 1 added. **Fourth occurrence of the shape, and the second inside this document.** |
| **revision 4's "Z-4 closes PREPARE structurally, pending measurement"** | *"structural"* was asserted of a mechanism **nobody had run**; when it was run, the fire-nothing state proved **unusable** and every usable state **fired** | §5.5.5(c) — **retired, not rescued** |
| **`git.py:520`'s docstring: *"`rev-parse` executed inside the worktree CANNOT BE STALE with respect to a HEAD that moved during a run"*** — carried into §5.5.2 as *"B2 stands exactly as it is"* | **it is a claim about STALENESS, and S-ε is not a staleness attack — it is a SUBSTITUTION attack.** The claim was true about the failure mode it named and **silent about the one that exists**. MEASURED: under variant C the same command returns a worker-chosen commit at `rc=0`, and **all three of revision 4's new B-1 conditions pass while it does, because none of them pins the repository** | §5.5.2C — the command is deleted and the chain is read raw |
| **revision 5's `test_no_direct_git_subprocess_in_src`**, specified as the *"day-one killer"* | its predicate was **over the ARGV** — *"the first argv element is the literal `"git"`"*. **It is GREEN while `validation.py:228` is live**, because `argv[0]` there is an envelope field, and MEASURED blind to five of six evasions (`/usr/bin/git`, `env git`, `sh -c`, `shell=True`, `os.system`, `os.posix_spawn`). **A design that names a killer test and gets the predicate wrong has an unkillable mutant and a green suite.** It was also, measured, **never written** | §5.4.6 — **the predicate moves to the CALLEE**, and the runtime half is fd-backed |
| **revision 5's *"after the worker launches the dispatcher runs exactly two git commands"*** | **it is a COUNT, and the count was never the defect — the inventory METHOD was.** Measured: **16 invocations on the success path from 10 call sites**, one bypassing the chokepoint, plus one spawn that is not a git call site at all. **A scan of `src/**` for the literal `"git"` cannot enumerate a path whose argv comes from data.** *(Third revision running for this sentence.)* | §2A — the set is emptied rather than counted |
| **revision 5's `content_omitted_bulk_created` row: *"clears the flag — but does not block Fable"*** | **the guard reads the flag.** `if not evidence.patch_file_complete: raise EvidenceIncompleteForReview` is unconditional, so the third column was **unreachable prose**, and B-3's own named killer asserted *"Fable not blocked"* and **could not pass against the mechanism it guarded** | §5.5.9 — **the third column is deleted**, and the enumeration test ranges over `ContentClass.__members__` |
| **revision 5's two tables giving opposite `patch_file_complete` values for `UNTEXTUAL` and `UNREPRESENTABLE_KIND`** | **there was no fact of the matter.** §5.5.9 said *no*, §5.11.5 said *yes*, and **whichever a reader took as authoritative produced a defect** — a dead review, or content omitted under a true flag | §5.5.9 / §5.11.5 — **one table, two columns, one deleted not amended** |
| **revision 5's `BaseBlobUnreadable`, specified in three places with three different phases and rows** | §5.12's row was **unreachable by construction** and §5.4.3's was a **laundering route above rows 4 and 5**. **A machine check across the error taxonomy and the ladder registry would have caught it as a build failure** | §5.12 ZI-60, and §12.2A's `test_registry_lands_in_matches_the_error_taxonomy` |
| **`server.py:576`'s `attribution_caveat`** | it is **an accurate description of a defect, shipped in production as documentation**: *"set difference cannot separate authorship of a single path."* **The sentence was true and the code stayed** | §5.5.6 — identity-wise deltas; the caveat string is asserted absent from `src/**` |

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
creates        = "0"          # was `owning_wave`; see §12.2A — owns == creates
lands_in       = ["5"]        # zero or more ladder rows
modifies       = []
design_section = "5.6"
mutants        = ["ZM-C1", "ZM-C2", "ZM-C6"]
killers        = ["tests/integration/test_inventory.py::test_baseline_venv_does_not_enter_changed_paths"]
```

**`owning_wave` becomes three columns in revision 6** (§12.2A). **The runner and
the registry are Wave 0 deliverables**, because Wave 0's acceptance is defined in
terms of them — *a wave whose acceptance criterion is produced by a later wave is
not independently shippable, and that is the same defect B-4 was.* The port of
the 38 Gate-6-era mutants stays Wave A.

Before applying a single mutant the runner asserts: (1)
`production_activation_defects(loaded_config) == ()`; (2) every row has ≥1 mutant
and ≥1 killer; (2a) **every ladder row has exactly one `creates` value in
`{0, A, B, C, D, E, baseline}`, and for EVERY error class in §5.12 and §8 the
registry's `lands_in` equals the taxonomy's row** — **this is the check that
would have caught F-3, where one class was specified in three places with three
different phases and rows: it turns "three mutually exclusive specifications"
into a build failure**; (3) **no killer list consists solely of matrix node ids**;
(4)
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
> | `test_crash_point_count_is_stated_once` | §15's table has **exactly twenty** `C`-prefixed rows; **no other `##`/`###` section in `docs/**` contains a markdown table whose first column matches `^\*\*C[0-9]+\*\*$`** | the banned strings do not appear **outside a blockquote, a fenced block or a table cell** |
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
WAVE 0   AUTHORITY FOUNDATION — and in revision 6 it is where the CENTRAL
         INVARIANT is built, so nothing in it may be deferred
         §5.4 deletions + the TEN-row PREPARE repertoire + the THREE pins ·
         §5.4.3B the declared order, git_order.py and the _run_git INTERLOCK ·
         §5.4.6 the two-half killer (callee-based AST + fd-backed runtime hook) ·
         §5.5 base/fs snapshots + reconciliation + the inventory type ·
         §5.5.2A THE SEAL (seal.py, the CAS, the manifest written LAST) ·
         §5.5.2B promisor materialisation · §5.5.2C the raw HEAD chain
         (headchain.py) · §5.5.6 three-state attribution (attribution.py) ·
         §5.17 the evidence freeze (freeze.py) and the validation journal ·
         §5.6 ignore-blind measurement + DISPATCHER-OWNED IGNORE EVALUATION ·
         §5.7 byte path model · §5.8 administrative preflight + fingerprint +
         deny list, WITH NO ALLOWLIST · §5.8.2B realpath authorization ·
         §5.9 primary tree, raw · §4.14 base_ref exactness ·
         the native content primitive AND the Myers/histogram differ (T-14) ·
         §3.1's EXECUTION PHASE mechanism (phase.py, _record_failure,
         refusals.jsonl)  [D-24] · §8 row 0 · §8 rows 3, 4, 5a ·
         the mutation runner and the invariant registry [§12.2A] ·
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

**And in revision 6 the list of live holes is longer, not shorter.** Measured at
`d197bf0`: **B2 is defeatable by one plain file write**; the artefact Fable reads
is **composed after validation**; scope is decided over the **validation-inclusive
set**; `git status` runs against the **primary repository after the worker
exits**; `rev-parse --show-toplevel` decides **repository authorization** and runs
**before the lock**; `git.py:776` **bypasses the chokepoint**; and **none of the
three pins, and none of the four named AST tests, exists in the tree.** **Wave 0
is where all of that closes, and it is why Wave 0 grew rather than shrank.**

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

### 12.2A "Owns a ladder row" — the operational definition (Sol §20)

**Z-I7 is described as *machine-checked*, and a machine check needs a predicate.
B-4 is exactly what happens when that predicate is left to prose.** The single
word *owns* was doing three jobs. It is split into three registry columns:

> For a ladder row `r` and a wave `w`:
>
> - **`creates(w, r)`** — `w` is the wave in which row `r` first exists as a
>   **decidable branch in the ladder implementation**. **Exactly one wave creates
>   each row**, or the creator is the literal value **`baseline`**, meaning the
>   row exists and is exercised in the tree at the Gate-7 baseline commit and no
>   wave creates it.
> - **`lands_in(w, r)`** — some invariant attributed to `w` names an error class
>   or verdict whose landing row is `r`. **Zero or more** waves land in a row.
> - **`modifies(w, r)`** — `w` changes row `r`'s **text, its precedence, or the
>   set of classes that land there**, without creating it.
>
> ### **`owns(w, r) ≡ creates(w, r)`. Ownership is creation, and nothing else.**
>
> **Z-I7, restated so the machine check has a predicate:** a wave-acceptance
> report for `w` is **refused** if any invariant attributed to `w` has
> `lands_in(w, r)` for a row `r` where `creates(w', r)` holds for a wave `w'`
> scheduled **after** `w`.
>
> Landing in a row created by an **earlier** wave or by **`baseline`** is legal
> and is the normal case. `modifies(w, r)` requires
> `creates(w, r) ∨ creates(baseline, r)`: **a wave may not modify a row a later
> wave has not yet created.**

**Applying it, and N-3's residue closes by definition:**

- Rows **0, 3, 4, 5a**: `creates(Wave 0, ·)`.
- Row **1**: `creates(Wave A, ·)`. Wave 0 has no `lands_in` on it — it touches
  neither `start_worker` nor `WorkerHandle`. **D-24 is exactly this predicate
  applied by hand; the definition makes it checkable.**
- Row **5**: **`creates(baseline, 5)`.** Row 5 exists and is exercised in the
  tree today — `check_scope` (`git.py:874`) and `compare_primary_tree`
  (`server.py:335`) both land `POLICY_VIOLATION` at the baseline. Wave 0 has
  `lands_in(Wave 0, 5)` **and** `modifies(Wave 0, 5)`, **and both are legal
  because `creates(baseline, 5)`.**

> **N-3 is closed by a definition, not by moving a wave.** The reading review 4
> called *"defensible … but not written"* is now written, **and it is written as
> a predicate a runner can evaluate rather than as a sentence a reader can agree
> with.**

**§12.3's count stays 4, because the count is a count of `creates`, not of
`lands_in`** — and the table must name **both**, because the mismatch between the
two columns is precisely what N-3 noticed. **Naming both makes it visible instead
of contradictory, and both must be DERIVED from the registry, not asserted beside
it.**

| Wave | **Ladder rows created** | **Ladder rows landed in** |
|---|---|---|
| **0** | **4** — {0, 3, 4, 5a} | **5** — {0, 3, 4, **5**, 5a} |
| A | 1 — {1} | {0, 1} |
| B | 0 | {0} |
| D / C / E | 0 | {0} |

**The second half of the residue — the mutation runner's wave.** §11.7 ports the
38 Gate-6-era mutants *"as part of Wave A"*; §12.4 lists `scripts/mutation/**` as
parallelisable; §12.3's Wave-0 module column did not name it — **yet Wave 0's
acceptance turns on the registry cross-check the runner performs.**

> **The mutation runner and the invariant registry are Wave 0 deliverables** —
> `creates(Wave 0, registry)` and `creates(Wave 0, runner)` — **because Wave 0's
> acceptance is defined in terms of them. The port of the 38 Gate-6-era mutants
> remains Wave A.**
>
> **A wave whose acceptance criterion is produced by a later wave is not
> independently shippable, and that is the same defect B-4 was.**

**Revision 6 adds refusals, and not one of them lands in row 1:**

| Refusal | Phase | Row | Created by |
|---|---|---|---|
| `ProductionBaseRefNotExact`, `BaseRefNotACommitObject`, `BaseCommitAbsent` | PREPARE | 0 | Wave 0 |
| `RepositoryNotAllowed`, `RepositoryLayoutUnreadable` | PREPARE | 0 | Wave 0 |
| `GitBeforeEstablishment` | PREPARE | 0 | Wave 0 |
| `BaseBlobUnreadable`, `BaseObjectVerificationFailed`, `SealBudgetExceeded` | PREPARE | 0 | Wave 0 |
| `SealIntegrityFailed` (no worker ever ran) | PREPARE | 0 | Wave 0 |
| `SealIntegrityFailed` (a worker ran), `WorktreeIndirectionChanged`, store-routing divergence, `EvidenceFreezeViolated`, `ValidationTouchedAdministrativeState` | FINALIZE | 4 | Wave 0 |
| `WorkerAttributionAmbiguous`, `ValidationAttributionUnknown` | FINALIZE | 5a | Wave 0 |
| `SealAbsentAfterWorker`, `WorkerExitSnapshotMissing` | FINALIZE | `FINALIZATION_FAILED` | Wave 0 |

**Every PREPARE refusal above requires §3.1's phase mechanism — i.e. requires
D-24. Wave 0 remains self-sufficient and B-4 stays closed.** *(Any lane proposing
to move D-24's boundary must first show it does not reopen B-4. Recorded here
because B-4 was reopened once already by a fix to something else.)*

**Tests, from two directions, because that is the answer to B-4's shape:**

| Test | Could it pass while false? |
|---|---|
| `test_owning_wave_predicate_is_total` — every ladder row has **exactly one** `creates` value; every invariant has ≥1 `lands_in` | **Yes if the registry is simply wrong** — which is why the next row exists |
| **`test_registry_lands_in_matches_the_error_taxonomy`** — for **every** error class in §5.12 and §8, the registry's `lands_in` equals the taxonomy's row | **No** for a disagreement between the two. **This is the check that would have caught F-3**, where `BaseBlobUnreadable` was specified in three places with three different phases and rows: **a machine check across the taxonomy turns "three mutually exclusive specifications" into a build failure** |
| `test_ladder_row_counts_derive_from_the_registry` | **No** |
| **`test_wave0_ships_without_row_1`** — a Wave-0-only build exercising **every** refusal in the table above | **Yes if a refusal is missing from the table** — caught from the other side by the taxonomy cross-check. **Two checks from opposite directions is the answer to "undefined predicates are how B-4 happened"** |
| `test_wave0_acceptance_inputs_are_wave0_artifacts` | **No** |

### 12.3 The honest resize — Wave 0 is the largest wave

The honest measure available before implementation is the count of named
artefacts each wave must deliver:

| Wave | New/moved modules | Invariants closed | Named tests | Named mutants | Ladder rows |
|---|---|---|---|---|---|
| **0** | `inventory.py`, `basetree.py`, `fssnap.py`, `reconcile.py`, `ignore.py`, `gitadmin.py`, `content.py`, `git.py` policy, **`phase.py`**, **`seal.py`**, **`headchain.py`**, **`attribution.py`**, **`freeze.py`**, **`git_order.py`**, **the mutation runner and the invariant registry** | **~34** | **~90** | **~85** | **4 created** (0, 3, 4, 5a); **5 landed in** (adds row 5) |
| A | `lifecycle.py`, compact artifacts, `config_authority` activation | 9 | ~28 | ~15 | **1** (row 1) |
| B | `evidence.py`, `runs.py` | 8 | ~24 | ~17 | 0 |
| D | `ownership.py`, `streams.py` | 12 | ~24 | ~28 | 0 |
| C | timeout / stream-json / post-timeout validation | 7 | ~16 | ~16 | 0 |
| E | progress | 3 | ~8 | 4 | 0 |

**Wave 0 is the largest wave in the plan by every column except ladder rows** —
roughly Wave A and Wave B's mutant counts combined. Revision 1 called it *"the
cheapest wave"*; revision 2 said it was *"no longer small"* **without resizing
anything**; **revision 3 states the size and accepts it.**

**Revision 6 makes Wave 0 larger again, and the reason is the central
invariant.** Sealing, the raw HEAD chain, three-state attribution, the evidence
freeze, the declared order and its interlock are all **preconditions for the
post-worker set being empty**, so none of them can be deferred behind a wave that
ships after the thing they make true. **A wave whose central claim is produced by
a later wave is not independently shippable — which is exactly what B-4 was.**

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

**Three additions to that row, from Lane Z5, each of which would otherwise let
Wave 0 declare a closure it has not built:**

1. **The row must be produced by §5.4.6's two-half killer — a CALLEE-based AST
   check plus the fd-backed runtime hook — not by a subcommand-string grep and
   not by an ARGV-based predicate.** `git.py:776` is a `subprocess.run(["git","diff",…])`
   outside `_run_git` that a subcommand scan over `_run_git`'s call sites cannot
   see (§5.4.5). **The test is red against `HEAD` today**; the row cannot read
   zero until it is green.
2. **PIN 1 and PIN 2 are Wave 0 deliverables, not documentation.** **Zero
   `-c key=value` occurrences exist in `src/**` today** and `GIT_NO_LAZY_FETCH`
   is not set anywhere. **Until both ship, the post-worker `cat-file` is a live
   S-δ execution vector**, and Wave 0 must not claim the repertoire is safe on
   the strength of §5.4.3's table alone — that table was measured *with* the pins.
3. **The acceptance report must name the surface count it was measured against —
   four — and must not describe the closure as structural.** The word has been
   used twice for claims that were later falsified (§10.3), and an acceptance
   report is exactly where it would be inherited without re-derivation.
4. **The report must print `V-1a` and `V-1b` separately** (§16). A single
   `V-1` row is what made a live `git` validation command invisible for three
   revisions.
5. **The pre-worker order row must be GENERATED from `git_order.py`**, and the
   report **fails if any declared row has no measured row in A.2B.** A
   hand-maintained matrix drifted into F-7; a derived one cannot.
6. **`test_no_show_toplevel_in_src`, `test_declared_order_is_the_matrix_row_set`
   and `test_no_status_clean_reset_stash_in_src` are all specified RED against
   `HEAD`**, alongside §5.4.6's static half. **Wave 0 begins with four
   known-red tests naming four known-live defects, and that is deliberate: a test
   that is green on a tree containing the defect it names is not a test.**

---

## 13. Backward compatibility summary

| Surface | Change | Compatibility |
|---|---|---|
| MCP tool surface | **none** — still exactly four | the feasibility API is INTERNAL |
| `TaskEnvelope` / `envelope.json` | none | `SCHEMA_VERSION` stays `"1.0"` |
| `TaskRecord` / `state.json` | `+lifecycle_preflight`, `+runs_allocated` (optional) | old files load; `run_count` keeps its meaning |
| `RunRecord` / `dispatcher-result.json` | `+timeout_evidence`, `RunMetadata.+lifecycle_phase` (optional) | old files load |
| `ValidationResult` | `+phase` defaulting `"post_run"` | old files load |
| run directory | `+reservation.json`, `+expectation.json`, `+ownership.json`, `+landing.json`, `+events.jsonl`, `+git-invocations.jsonl`, `+timeout.json`, **`+fs-snapshot-{worker-exit,post-validation}.json`**, **`+attribution.json`**, **`+evidence-freeze{,-post}.json`**, **`+validation-invocations.jsonl`**, **`+git-admin-post-validation.json`** | additive. **`fs-snapshot-start.json` MOVES to `materialisation/`** — it is per-TASK, and the move is what makes "one START snapshot, never re-measured" structural rather than conventional |
| **`materialisation/`** | **`+seal-manifest.json`, `+repo-authority.json`, `+primary-start.json`, and `start-bytes/<hash>.bin` → `cas/<oid[:2]>/<oid[2:]>`** | **no migration required**: every existing task predates `materialisation/` entirely. **A task with a `start-bytes/` directory and no `seal-manifest.json` is a pre-revision-6 task and is NOT resumable** — it lands `ResumeNotPermittedFromState`, a row-0 refusal, **not a silent re-seal** |
| `evidence/diff.patch` | now contains untracked content **and is composed by the dispatcher** | strictly more complete. **Fable's prompt reads it in full or the review is refused (`EvidenceExceedsReviewBudget`); it is NEVER clipped.** The previous behaviour — clipping at `_MAX_PROMPT_DIFF_CHARS` and reviewing anyway — is **deleted, not preserved.** |
| `changed-paths.json` | `schema: "changed-paths/3"`, new keys, `diff_patch_complete` → **`patch_file_complete`** | **the SEMANTICS change even where a key name is kept** — from *"git exited 0"* to §5.5.9's IFF. **A value comparison across the change is meaningless** and every consumer must be updated |
| **`evidence/diff.patch`** | **means the WORKER patch** (frozen at WORKER_EXIT), with `cumulative.patch` alongside | **this breaks every existing reader** and is escalated as **T-16** rather than taken silently |
| `evidence-phases.json` | schema 2; the four arrays keep their names and **change their values** — they were wrong for the intersection case — and **`attribution_caveat` is removed** | a test asserts the caveat string occurs nowhere in `src/**`: **the sentence described a defect and the defect is gone** |
| **`DispatcherObservations.changed_paths`** | **means `worker_delta`**, not the post-validation set; `+validation_changed_paths` | **a behaviour change for `get_task`, the review prompt and `results.py`, and each must be updated in the same wave** |
| **`repository.base_ref`** | **no default; production requires `^[0-9a-f]{40}$`** | **the one production-admission break.** No stored record is rewritten (T-24) |
| **`ContentClass`** | loses `BULK_CREATED_IGNORED` (never shipped); `UNREPRESENTABLE_KIND` narrows to FIFO/socket/device/gitlink; **symlink becomes SUPPORTED** | **measured production impact: 1 ignored symlink, unchanged, therefore absent from `worker_delta` — no production review is blocked, by two independent reasons.** New behaviour: **a task that changes a binary loses its automated review** until T-17 |
| `[evidence].bulk_created_ignored_budget` | **removed** | a config carrying it is a **refusal**, not a warning, per the fail-closed convention for unknown keys |
| **`changed_paths` semantics** | a worker-created file inside a base-ignored directory now **appears**; deletions and type changes now appear | **a deliberate, visible behaviour change — the G7-2 fix** |
| **task-state outcomes** | some runs that previously landed `FAILED` now land `POLICY_VIOLATION` | strictly more informative; the direction §28 requires |
| `stdout.raw` / `stderr.log` / `events.jsonl` | written by the child directly | same paths; **no redaction claim is made about them at all.** `docs/SECURITY.md` §1.5 is **rewritten** in Wave D |
| `DiffEvidence`, `DispatcherObservations`, `PrimaryTreeSnapshot` | names and field names retained; producers change | `primary_worktree_clean` becomes a genuine tri-state — **a reader that treated `None` as `True` was already wrong** |
| `check_scope` / `ScopeSpec` | operate on **`bytes`** | patterns encoded once at envelope validation; no envelope change. `docs/INTERFACES.md` §5 changes in the same wave |
| `git.py` public surface | `collect_diff_evidence`, `write_full_diff`, `primary_tree_status`, `_fold_untracked` **DELETED**; **and now `git_top_level`, `git_top_level_or_none`, `is_git_repository`, `worktree_head`** | **no compatibility wrappers** — a retained wrapper is a live call site, and **a permitted row with no caller is a future caller** |
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
| `docs/INTERFACES.md` §5 | `check_scope` takes **bytes**; `collect_diff_evidence`, `write_full_diff`, `primary_tree_status`, **`git_top_level`, `git_top_level_or_none`, `is_git_repository` and `worktree_head`** are **removed from the contract**. §4 of `CLAUDE.md` makes this the shared contract between modules written in parallel, so it changes **in the same wave** as the signature. | 0 | `test_interfaces_doc_matches_public_signatures` |
| `docs/STATE-MACHINE.md` | Gains the **run** state machine (§5.11A) beside the task state machine, and the note that `RUNNING` now requires a `WorkerHandle`. | A / B | reviewed with the wave |

| **Fable's own instructions** | the review prompt gains sections 3, 5 and 6 and **section 2 changes source**. A prompt that says *"review the change below"* while a **dispatcher-executed** section 5 exists is a documentation defect | B | reviewed with the wave |
| `docs/SECURITY.md` — validation | must state that **trusted validation is an execution domain with no OS containment**, and must not use the words *sandboxed*, *isolated*, *contained*, *confined* or *jailed* about it | 0 | `test_no_document_or_docstring_claims_validation_is_contained` |

**This document is itself specification** (§18.5), which is why §11.6 carries two
**documentation mutants**: two *document* defects have already shipped untested
coverage in this gate. **Revision 6 adds a third class of documentation
obligation and it is the one most likely to be skipped: §16's gate report must
print `UNMEASURABLE` — not `PASS`, not a blank — for every row whose mechanism is
measured absent from the tree.**

---

## 15. THE CANONICAL CRASH MATRIX (directive P)

### 15.1 The rule

> **There is exactly ONE crash-point table in this document. It has TWENTY rows,
> C1…C20. Every other section references it by row id and states no count of its
> own.**

**Revision 6 adds C16…C20** — three from the three-state attribution model
(§5.5.6) and two from the validation execution domain (§5.17). **The count moved
and it moves in exactly one place**, which is the whole content of the rule; the
documentation mutant `P-M9` and its killer are updated in the same edit, because
**a count assertion that is not updated with the count is the defect the rule
exists to prevent.**

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
| **C16** | between the WORKER_EXIT snapshot and the frozen worker patch | FINALIZE | `fs-snapshot-worker-exit.json` exists, `diff.patch` does not | held | **`FINALIZATION_FAILED`.** Recomposing needs the WORKER_EXIT **bytes**, and they are gone — the snapshot holds hashes, not content. **This is the one place §5.5.6's rejected option (b) would buy something, and it is the stated cost of not adopting it** | yes | `test_crash_between_worker_exit_snapshot_and_patch_is_finalization_failed` |
| **C17** | between the frozen patch and `evidence-freeze.json` | FINALIZE | patch present, no freeze | held | **`FINALIZATION_FAILED`.** Re-hashing on recovery is **not equivalent**, because validation may already have run — **acquiring a baseline from a tree that has moved on is exactly the laundering ZI-34 forbids** | yes | `test_missing_evidence_freeze_is_finalization_failed_not_rebaselined` |
| **C18** | between the first validation spawn and the POST_VALIDATION snapshot | FINALIZE | `validation-invocations.jsonl` has a row with **no `returncode`** | held | `ValidationAttributionUnknown` → row 5a. **NEVER "no validation ran"** | yes | `test_validation_row_without_returncode_is_unknown_not_none` |
| **C19** | between `evidence-freeze.json` fsync and the first validation spawn | FINALIZE | freeze present, **zero** invocation rows | held | validation is **unknown**, not "none ran" | yes | `test_freeze_without_invocations_is_unknown` |
| **C20** | between a validation spawn and its reap | FINALIZE | the child **outlives the dispatcher** — `start_new_session=True` means the dispatcher's death does not signal it | held | `FINALIZATION_FAILED`. **The recovering dispatcher must not adopt, signal, or wait on it**: it holds no `WorkerHandle` for it, and §7.5's rule that an exit status is not recoverable after dispatcher death applies identically. **A validation command can therefore keep writing to the task worktree AFTER recovery has read it, and the honest consequence is that the run's attribution is `unknown` and Fable refuses** | yes | `test_orphaned_validation_child_is_not_adopted` |

> **The seal itself introduces NO canonical crash row.** It belongs in **§15.4**
> (durable writes that are not canonical crash points), because a crash during
> CAS population is a PREPARE event with **no lifecycle mutation**: CAS entries
> are content-addressed and written temp-then-rename, so a partial store is a
> **subset, never a corruption**, and the manifest is written **last and
> atomically**, so *the seal exists iff the manifest exists*.

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
| §5.5 | during CAS population (base bytes or captured START bytes) | content-addressed temp-then-rename makes a partial store a **subset, never a corruption**; **the manifest is written LAST, so the seal exists iff the manifest exists** | `test_partial_seal_without_manifest_is_absent` + `test_manifest_is_written_last` (AST) |
| §5.5 | after `seal-manifest.json`, before spawn | the seal is complete and immutable; re-entering PREPARE **loads and verifies** it rather than rebuilding | `test_seal_is_loaded_not_rebuilt_on_reentry` |
| §5.5 | seal absent, a worker has run | **never reconstructed** — `SealAbsentAfterWorker` → `FINALIZATION_FAILED` | `test_seal_is_never_reconstructed_after_a_worker_ran` |
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
  V-1a evidence authority ........... post-worker AUTHORITATIVE git: NONE (empty set)
      FINALIZE journal rows .......... 0
      post-worker spawn events ....... 0   (fd-backed audit hook, fork-safe)
      positive control fired ......... YES (Z-RULE-1)
      integrity control fired ........ YES (Z-RULE-1B: the decoy answered)
  V-1b validation spawns ............ n=<N>, authority=false, is_git=<K>
      -- a live `git` validation command INCREMENTS A PRINTED NUMBER
         instead of being invisible. K>0 is not a failure; K unrecorded is.
  pre-worker git order .............. GENERATED from git_order.py, not typed
      declared rows / measured rows .. must be EQUAL, all three paths
      establishment before git ....... YES (interlock; 0 journal rows precede it)
  seal .............................. N blobs / X MB / Y ms · manifest sha256 <…>
      route A / route B split ........ <a>/<b>
      max lines in any sealed blob ... <n>  (budget <regen_max_lines_per_blob>)
      base objects missing after step 4  0
  store routing ..................... alternates 0 · http-alternates 0 ·
                                      refs/replace 0 · info/grafts absent · unchanged
  head chain ........................ resolved == base · links N · restructured NO
  pins in the tree .................. PIN 1 <yes/no> · PIN 2 <yes/no> · PIN 3 <yes/no>
      -- ANY "no" makes every row above that depends on it UNMEASURABLE,
         and the report must print UNMEASURABLE, never PASS.
  attribution ....................... three states captured · closure theorem held
      final_delta \ (worker u validation)  MUST BE EMPTY
  V-2 path identity ................. bytes end-to-end; hostile-name pipeline test
  V-4 index bits .................... structurally irrelevant (no index is read)
  V-5 self-hiding gitignore ......... ignore-blind snapshots; unchanged_count scalar
  crash points ...................... 20/20 injected; C12 run twice
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

> **Revision 5's `V-1` row said *"post-worker git: cat-file + B2 rev-parse
> ONLY"*. It was false for the third revision running** — not because the count
> was two rather than sixteen, but because **the inventory method could not see a
> spawn whose argv came from data.** It is replaced above by two rows, `V-1a`
> and `V-1b`, so that **the thing the old row could not express now has a
> printed number of its own.**
>
> **And the pin rows are new because the pins are not in the tree.** `PIN 1`,
> `PIN 2`, `PIN 3`, `core.hooksPath` and `attr-source` have **zero hits in
> `src/**`**, and `test_no_direct_git_subprocess_in_src` **does not exist**.
> **Every acceptance row that depends on one of them is UNMEASURABLE, not green**,
> and the report must say so in that word. A gate report that prints PASS for a
> row whose mechanism is not implemented is the defect this gate exists to
> catch.**

---

## 17. The Y-1 … Y-10 decision table, carried into revision 6

Sol requires each of the second review's ten decisions mapped to the **exact**
section that resolves it, **with any item the directives do not resolve named
plainly rather than force-mapped.** Revision 6's status is the right-hand column;
the revision-3 mapping is retained beneath it.

| # | Revision-6 status |
|---|---|
| **Y-1** | **RESOLVED IN SUBSTANCE; THE HEADLINE WAS OVERSTATED FOR THREE REVISIONS AND IS NOW REPLACED RATHER THAN CORRECTED.** The class deletion genuinely closes `filter.*` and review 3 independently reproduced it. **What kept failing was the other half: the inventory METHOD.** Revision 3 said *one* command and was false in its own text (B-1); revisions 4 and 5 said *two* and were false because a scan for the literal `"git"` cannot enumerate `validation.py:228` (F-4), and because **16 authoritative invocations from 10 call sites are reachable after the spawn seam.** **Revision 6 does not restate the count. It empties the set** (§2A), deletes `rev-parse --show-toplevel` (§5.8.2B), replaces the enumeration with a **declared, interlocked, generated** order (§5.4.3B), and gives validation **its own printed number** (`V-1b`). **The claim is now checkable by mechanism rather than by counting**, and §16 no longer contains a sentence of the form *"exactly N git commands"*. |
| **Y-2** | **RESOLVED, stronger than asked.** Unchanged. **New dependency recorded:** §5.4.3B's `GitBeforeEstablishment` interlock reads `ToolExecution`, so **Y-2's mechanism is now load-bearing for ZI-53 as well.** |
| **Y-3** | **RESOLVED — superseded.** Unchanged at the inventory layer. Its content-layer residue was F-1/F-2 and is closed in §5.5.9. |
| **Y-4** | **RESOLVED.** Unchanged. *(Verified against the host by review 4; no revision-6 lane re-verified it and none opened the five forensic tasks.)* |
| **Y-5** | **RESOLVED.** Unchanged. |
| **Y-6** | **RESOLVED, all three limbs.** Unchanged. |
| **Y-7** | **RESOLVED — AND ITS RESIDUE IS NOW CLOSED.** D-24's cut is preserved untouched. N-3's residue — row 5, and *"owns a ladder row"* having no operational definition — is closed by **§12.2A's `creates` / `lands_in` / `modifies`**, with `owns ≡ creates` and `creates(baseline, 5)`. The mutation runner's wave is settled in the same section. |
| **Y-8** | **RESOLVED AND EXCEEDED — and now LOAD-BEARING for §4.14.** ZI-61's production/dev split is gated by §4.12's activation predicate. **If that predicate is wrong, §4.14 is wrong**, which is ZM-P5. **Recorded as a coupling, not a defect.** |
| **Y-9** | **NOT RESOLVED. MOOT, SOUND, AND UNRATIFIED FOR THE FOURTH REVISION RUNNING — and it becomes the fifth if revision 6 ships without a ruling.** Named plainly, not force-mapped. The moot-ing argument is sound: under an ignore-blind measurement no worker write suppresses anything. **The soundness of the argument is not the ruling.** An unruled adoption that changes what lands `POLICY_VIOLATION` is precisely the shape of thing that becomes load-bearing and false. **Recommendation: Sol ratifies it in revision 6, in one sentence.** |
| **Y-10** | **UPGRADED from `CANNOT BE RATIFIED AS WRITTEN` to RATIFIABLE FOR THE SYMLINK HALF; the remainder is named rather than force-mapped.** Revision 5 was unratifiable because §5.5.9 and §5.11.5 gave **opposite** `patch_file_complete` values for `UNTEXTUAL` and `UNREPRESENTABLE_KIND` (F-2) — **Sol was being asked to ratify a decision the document specified two ways.** Sol's §11 rule removes the symlink half entirely: a symlink is **SUPPORTED**, never followed, `lstat` + `readlink` at mode `120000`, **so it is a represented kind, not an unrepresentable one, and the bucket contradiction cannot arise for it** — MEASURED, including a **dangling** symlink and a symlink whose target contains `LF`, both of which round-trip through a hand-composed patch. **And independently**, the production symlink is unchanged and therefore absent from `worker_delta`. **What §11 does NOT resolve, stated rather than mapped away:** (a) `UNREPRESENTABLE_KIND` still covers **FIFO, socket, block device, char device and gitlink**, all now `(clears, blocks)` and all **empty in practice on both hosts**; (b) **binary is untouched** — an exact `GIT binary patch` representation is MEASURED to work and is **not adopted for Wave 0** (T-17), **so any task that changes a binary loses its automated Fable review.** **Y-10 is ratifiable once Sol takes T-17 or accepts that cost explicitly.** |

**Summary entering the fifth review.** **Eight of ten resolved.** **Y-1 is
resolved in substance; its headline is no longer restated at all, because
restating it is what failed three times.** **Y-9 is moot, sound, and unratified
for the fourth revision running: it is NOT resolved, and this table says so
rather than mapping it to a section that agrees with it.** **Y-10 moves from
unratifiable to ratifiable for its symlink half, with its binary half named as
outstanding. No row is force-mapped.**

### 17.1 The revision-3 mapping, retained

| # | Decision | Resolved in | Status as of revision 3 |
|---|---|---|---|
| **Y-1** *(revision-3 text, **SUPERSEDED** — its headline sentence is false and §17's revision-6 row replaces it)* | What actually closes Tier-0 `filter.*` execution (S-1)? | **§5.4**, **§5.4.1**, **§5.4.3**, **§5.4.6**, **§12.2** | **RESOLVED — and the finding is worse than S-1 recorded.** `git diff --name-only -z` — revision 2's own authoritative tracked-path source — **fires the filter**, measured independently by two lanes. So the vector was *inside Wave 0's own inventory*, ordered by §8 before the row that would report it. **After the worker launches the dispatcher runs exactly two git commands: `cat-file` and B2's `rev-parse --verify HEAD^{commit}` — both measured clean on all four armed surfaces, `cat-file` only because PIN 1 closes S-δ, no presentation command.** Revision 3 claimed *one* and was false in its own text; the claim and its journal test are corrected in §0.2 and §5.4.5, **not** the command. The residual is named in §12.6. |
| **Y-2** | Bind `phase` to the tracker; add the loud cross-check; add mutant A-i (S-2) | **§3.1.3** (the parameter is **deleted**, not bound), **§3.1.7**, **§3.1.8**, **§4.11** | **RESOLVED, and stronger than asked.** Y-2 asked for the guard to read the tracker; revision 3 **removes the parameter entirely**, so there is no literal to get wrong. **Y-2's item 2 is refined rather than copied**, and the reason is measured: Y-2's cross-check (*"PREPARE + task state ∈ {CREATED, ROUTED, RUNNING, RESUME_REQUESTED} → loud"*) has a **real false positive**, because closing Z2-G-F2 requires a *legitimate* PREPARE refusal (`ResumeNotPermittedFromState`) precisely when the state is `RUNNING`. **A flag that fires on routine refusals is worse than no flag.** The substituted contradiction — *PREPARE while this execution already holds a reservation or a handle* — is impossible by monotonicity and has no false positive. |
| **Y-3** | Absolute suppressed set, or pre/post delta (S-3 / OQ-B6)? | **§5.6**, **§5.5.7** | **RESOLVED — and SUPERSEDED: neither.** There is **no suppressed set and no ignore query at all**. `changed_paths` is the difference between two **ignore-blind** dispatcher-owned snapshots, so `.venv` is in neither delta and collapses to `unchanged_count`, **an int that cannot become a path list**. This is strictly stronger than a delta: nothing can remove a path because nothing is consulted. **OQ-B6 is deleted.** Z3's F5 case (a new file inside an already-ignored directory) is caught trivially, and Z1's case — **a modification to an already-existing ignored file**, Sol's explicit §C requirement — is caught too, which a delta over a *path set* could not express. |
| **Y-4** | Which rule governs a pre-Gate-7 run directory (S-4)? | **§7.6** (H-I1…H-I3), **§7.6.3** (the claim-coverage theorem), **§7.14** | **RESOLVED.** A run directory with no `reservation.json` is **LEGACY** — not `ORPHANED`, no claim, **not modified, not one byte**. Reconciliation is **claim-driven** and **never walks `state/tasks/**`**. Revision 2's contradictory `COMPLETE`/`ORPHANED` sentence is **deleted**. Measured basis: all five existing tasks are populated and **none is in `RUNNING`** — revision 2 would have written five `ORPHANED` claims and **permanently closed production** the moment the freeze lifted. |
| **Y-5** | Must reconciliation prove the OWNING dispatcher is dead before acting (S-5)? | **§7.7.2** (dispatcher identity + kernel liveness lock), **§7.7.3** (twelve-row owner truth table + action table), **§7.7.4** (single-flight + `TerminationAuthority`), **§7.8** (every deadline row inside `OWNER_GONE`) | **RESOLVED.** Owner classification is **first**, uses **two independent signals**, and **disagreement is `OWNER_AMBIGUOUS`, never resolved by preferring one**. The signalling path is **reachable only while holding the dead owner's liveness flock**, which the kernel refuses while that owner lives — so it is not a policy check a future edit can forget to call. **What remains conventional is stated:** same-uid processes can always signal each other; the claim is that *the dispatcher's own code path cannot*. |
| **Y-6** | Correct the three amendment contradictions before Wave A (S-6) | **A-d → §4.11** (deleted **in the implementer's table**, with the equivalence proof, replaced by A-d′). **"clips as before" → §13 and §5.11** (both sentences deleted; replacement text in §13; `test_no_document_claims_the_review_input_is_clipped`). **"all ten points" → §3.5, §15, and mutant P-M9** (a **documentation mutant**, the only thing that can fail for a document defect). | **RESOLVED, all three limbs.** The third limb — the crash-point count — **appears in no directive** and is covered here because it would otherwise ship untested: revision 2 had fifteen rows and two "ten" statements, so **C9, C11, C12, C13 and C14 had no test plan.** |
| **Y-7** | Re-cut the waves (S-7) | **§12.1, §12.2 (D-24), §12.3, §12.4, §12.5** | **NOW RESOLVED — it was NOT resolved in revision 3 (B-4).** Taking directive L's third option was legitimate and honestly costed, but the dependency §12.2 *claimed to have broken was not broken*: three Wave-0 refusals (`RepositoryAdministrationUnestablished`/`Unreconciled`, `SnapshotBudgetExceeded`, `CheckoutTransformationBudgetExceeded`) land in §8 **row 0**, which revision 3 assigned to Wave A — so a Wave-0-only build would have reached the baseline `_record_failure` and landed the task **`FAILED` on the first dispatch against every repository**, reintroducing G7-6 through Gate 7's own first wave. Wave 0 could not have passed Z-I7's machine check either. **D-24 moves §3.1's phase mechanism and §8 row 0 into Wave 0**, which makes §12.2's sentence true rather than load-bearing and false. |
| **Y-8** | What repository-visible artefact carries the shipped default (N-a)? | **§4.12** (change 5 + the seven-conjunct proof chain), **§9.3**, **§16** | **RESOLVED AND EXCEEDED.** Y-8 asked for a tracked artefact plus a verbatim checker row. Directive N requires more: **the registered production entrypoint itself refuses to start**, with **no operator-supplied expectation flag**, proven by a **live subprocess negative control in an isolated package tree**. `check-production-activation.py` is **demoted to a corroborator**. `config/dispatcher.example.toml` is tracked and asserted in `tests/**`, which the gitignored canonical file can never be. |
| **Y-9** | Is `.gitignore`/`.gitattributes` tampering "any write", "a write that hides a path", or "a write that hides a path this run created" (N-b)? | **§5.6.6** | **MOOT, NOT ANSWERED — and this needs Sol's explicit ratification.** Under an ignore-blind measurement **no worker write suppresses anything**, so a `.gitignore` write is not an attack: it is an ordinary file change, scope-checked like any other, and lands `POLICY_VIOLATION` only by the ordinary rule. This **disposes of the cost** Z3's option (iii) carried honestly (a legitimate *"generate `dist/`, then gitignore it"* task landing `POLICY_VIOLATION`) — it does not. The tamper marker narrows to `.git/**` and `$GIT_COMMON_DIR/**` writes, which §5.8 owns. **Sol has not ruled on Y-9; §18.4 asks for it explicitly rather than inheriting it from a draft.** |
| **Y-10** | A fourth bucket for symlink/FIFO/device, treated like `untextual` (N-e)? | **§5.5.9**, **§5.11.5** | **ADOPTED — and this needs Sol's explicit ratification.** `UNREPRESENTABLE_KIND` does not block the review; `refused` is reserved for *unreadable* and *changed-during-measurement*. **Measured basis:** this repository contains **4** ignored symlinks and **production contains 1** — a number neither review recorded. Under revision 2's rule that single symlink **kills every Fable review of production, forever**, for a reason unrelated to any task. R-13's reasoning applies unchanged: **a symlink has no text representation either.** **Sol has not ruled; §18.4 asks.** |

**Summary as of revision 4, retained for provenance.** Eight of the ten are
**resolved** (Y-1 … Y-8) — but two of those changed status in revision 4:

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
step 3; step 3 is gated on step 0) **and by PIN 2 on the argv**. Revision 3 and 4
also offered `dispatcher_raw` materialisation as a *structural* alternative;
**Z5 retired that claim (§5.5.5(c)), and ordering alone is now known to be
insufficient — a worker-set `core.hooksPath` survives the dispatcher deleting the
hooks directory (§5.5.5(a)).** **Sol must confirm the ordering is the intended
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
`rev-parse --absolute-git-dir` and `--git-common-dir` are **measured clean on all
four armed surfaces** with a positive control and are **permitted** (§5.4.3);
**(2) RETIRED by Z5 — negatively:** `dispatcher_raw` materialisation was untested
from the worker's side; it has now been tested from the worker's side and **it
does not work** (§5.5.5(c)); **(3) RETIRED by Z5 — positively:** the
dispatcher-composed unified diff **is** accepted by `git apply --check` and
applies byte-exactly for every §9 edge case, subject to three measured format
constraints (§5.5.8); (4) submodules; (5) reftable ref storage (git ≥ 2.45) and its refusal path;
(6) `st_ctime_ns` forgery resistance; (7) the `sys.addaudithook` mechanism
against this codebase's `asyncio.to_thread` model; (8) the HMAC-signed admin
baseline — **a proposal about filesystem containment under a same-uid threat
model, not a measurement**; (9) the base-committed ignore matcher and its
agreement corpus; (11) every measurement is **git 2.43.0 on this host**, and a
git upgrade must re-run the Z-RULE-1 tests.

> **(10) — the one Sol should weigh most. It has now been PROVEN TWICE.**
> Revision 3 recorded Z1's caveat: *"S-α and S-β are the two surfaces I know
> about, not the two that exist."* The third review armed a third and it fired
> (**S-γ**: `worktree add` runs `reference-transaction` even with
> `--no-checkout`). Revision 4 wrote that three were armed and appealed to a
> *structural* argument for the rest. **Lane Z5 armed a fourth and it fired
> (S-δ), and the structural argument it appealed to was the thing that turned
> out to be false.**
>
> Four surfaces are armed and the permitted set is clean on all four **under two
> enumerated pins**. **The caveat stands unchanged for a fifth**, and §5.4.3's
> safety argument is now **an enumeration and nothing else** — there is no
> structural claim left to hide behind, which is precisely why widening the
> repertoire must remain a Sol decision rather than a convenience.

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

**Z2-Q2 — the canonical crash count.** **Twenty** as of revision 6 (fifteen as
ordered, plus C16…C20), with §4.9's four durable-write rows and the seal's three
routed to §15.4 with named tests; or **twenty-seven**, absorbing them.
**Recommendation: twenty.** Either way **no row loses a test.**

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

**T-1 — SUPERSEDED BY SOL §17: the post-worker repertoire is `{}`** (§2A, §5.4.5).
*The revision-4 text is retained below for provenance.* **T-1 (superseded).** This
revision adopts the reviewer's recommendation: B2's post-worker check is a §2
non-regression, `rev-parse --verify HEAD^{commit}` is measured clean on all
**four** armed surfaces (S-δ added by Z5), and the correction belongs to the claim and the test rather than
to the command. **Sol should confirm**, because the alternative — a `{cat-file}`
FINALIZE set — is only reachable by deleting B2's post-worker verification, which
reopens task `49231f6e`'s defect.

**T-2 — SUPERSEDED BY MEASUREMENT. The fourth surface exists.** (B-2, then Z5.)
Revision 4 asked Sol whether Wave 0 could begin on **three** armed surfaces plus
a structural argument. **Lane Z5 answered the empirical half before Sol answered
the policy half: S-δ exists, and it fires on `cat-file --batch` and
`ls-tree --long` — two commands the design had already permitted.** The
"structural argument" that made three feel sufficient is the paragraph §5.4.1
now quotes and deletes.

**What Sol must rule on is therefore narrower and sharper: Wave 0 may not begin
on a structural argument at all, because the structural argument has now been
falsified twice.** The remaining choice is between:
(a) **four armed surfaces plus two enumerated pins (PIN 1, PIN 2), accepting that
completeness is unproven**, or (b) **a systematic sweep of git's program- and
hook-invocation points as a Wave-0 precondition.** This design implements (a)
and states its residue in §5.4.1. **Sol should choose knowingly.**

**T-2A — ratify PIN 1 and PIN 2 as global, non-optional invocation policy**
(§5.4.3A). `GIT_NO_LAZY_FETCH=1` on **every** dispatcher git invocation, and
`-c core.hooksPath=<empty dir>` on every **mutating** one. Both are exactly the
flag-hardening §5.5.5 hoped to avoid; **both are now the only measured defence
for their surface**, so the principle loses to the measurement. **Sol should
ratify them explicitly**, because they are enumerated defences and the document
must not present them as anything else.

**T-2B — remove `--long` from the `ls-tree` argv** (§5.5.2). It is what arms
S-δ. The cost is that `TreeEntry.blob_size` becomes `int | None`, and any size
the design needs is fetched deliberately, per oid, under PIN 1. **Sol should
confirm that no consumer requires a size for every entry**; §5.9.5 is the only
site that reads one.

**T-3 — CLOSED NEGATIVELY. Z-4 is RETIRED, not rescued.** Revision 4 demoted
`dispatcher_raw` from *structural* to *gated* pending Z5. Z5 measured it: the
fire-nothing state is **unusable by a real worker**, and **every** measured way
to make it usable **fires** (§5.5.5(c)). **Its claim to close PREPARE
structurally is withdrawn.** `dispatcher_raw` survives only as a configuration
value that buys the raw-blob starting tree, with the same gate and the same pin
as the default, and **no execution-safety benefit whatsoever**. **Sol needs only
to ratify the retirement** — there is no longer a decision about whether
`-c core.hooksPath=<empty>` makes it "gated rather than structural", because
nothing about it is structural.

**T-8 — commission the raw-DIRC index work, or close it permanently.** The one
path that could make a fire-nothing materialisation *usable* is the dispatcher
writing git's **index file itself in raw DIRC binary format**, with no git
process. It is **NOT TESTED**: unspecified, unimplemented, unmeasured, and a
substantial piece of new dispatcher-owned binary-format code that would have to
track git's index versions. **This design claims nothing about its feasibility
and does not adopt it.** **Sol should either commission a probe or close the
idea**, so that a later lane does not rediscover it as an insight and build it
under schedule pressure. *(Recommendation, non-binding: close it. PIN 2 already
covers the surface, and a hand-written index is a new correctness liability in
exchange for removing one enumerated flag.)*

**T-9 — `git.py:776` is a live chokepoint bypass in the current tree.**
`write_full_diff` calls `subprocess.run(["git", "diff", …])` **directly, outside
`_run_git`**, so the §5.4.5 journal cannot see it and none of §5.4.3A's pins
apply to it. It is a live instance of mutant **ZM-A5** sitting in `HEAD`.
**Sol should confirm that fixing it is Wave-0 work**, because
`test_no_direct_git_subprocess_in_src` (§5.4.6) is specified to **fail against
the current tree** and this call site is its day-one killer. **Fixing it is not
a refactor of convenience: until it routes through `_run_git`, the design's
central claim about the post-worker repertoire is unenforceable by the mechanism
the design names.**

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
measured clean on all **four** surfaces, as are the three `REQUIRES-PROBE` rows
now retired. §5.4.3 says widening is a Sol decision. **Sol must ratify the widened
set — with its measurements recorded — or order the identity producer rewritten.**
**Lane Z5's matrix has landed and §5.4.3 adopts it as the repertoire's
authority.** N-1's argv are corrected there to the forms Z5 actually measured
(`rev-list --max-parents=0 HEAD`, `config --get remote.origin.url`); Z5 also
found **no call site in `src/**` for `rev-parse --is-inside-work-tree`, so it is
dropped from the widening request rather than ratified.**

**T-7 — promote `TaskStore.transition`'s compare-and-set from *recommended* to
*required*?** §15.3 discloses in bold that concurrent-writer exclusion *"rests
entirely on the reconciliation lock and the owner gate — a convention"*, and that
the failure *"is precisely S-5 race 3"*. The third reviewer agreed the disclosure
is honest and declined to make it blocking, because the reconciliation lock plus
single-flight rename covers the reachable path. **Sol should decide whether P-M6
is a requirement.**

### 18.3B Decisions arising from the fourth review and Sol's twenty-one directives

**Sol's revision-6 directives supersede parts of A–T, and the supersessions are
recorded rather than left to inference.** Specifically: **T-1** (the post-worker
set is `{cat-file, rev-parse}`) is **superseded by §17 — the set is `{}`**;
**T-2/T-2A/T-2B** are **subordinated**: PIN 1 and PIN 2 remain required and gain
**PIN 3**, but they now defend only the PREPARE window, and the question *"is
four surfaces enough"* is no longer the question the design's safety rests on;
**T-6**'s widened repertoire is **narrowed by three deletions**. **T-3** (Z-4
retired), **T-4**, **T-5**, **T-7**, **T-8** and **T-9** stand as written — and
**T-9 is now discharged by mechanism**: `git.py:776` is deleted by §5.4.4 and
caught by §5.4.6's callee-based static half, which is **specified RED against
`HEAD`**.

**T-11 — delete the alternates file before evidence, or capture and report?**
Review 4's decision item 4. **Recommendation: capture and report** (§5.4.1B).
Deletion buys nothing under ZI-51, **is a dispatcher WRITE into the target
repository** that would destroy a legitimate `git clone --shared`, **and does not
work anyway** — rows H and H2 defeat B2 with **no alternates file present at
all**. *The counter-argument, stated fairly: deletion is the only measure that
still works if ZI-51 is ever weakened. That is an argument for making ZI-51 hard
to weaken, not for taking a destructive action now.*

**T-12 — `raw` or `zlib` for the CAS?** `raw` is **23.2 MB / 0.73 s** on
production; `zlib` is **4.3 MB** for no reliable time saving and is **strictly
worse at scale** (788 MB: 5.68 s raw vs 9.97 s zlib). On a host with **3.0 GB
free**, the 5.4× disk saving is not nothing. **This is a policy choice, not a
correctness one; both satisfy Sol §2.** *(Recommendation: `raw`, with
`seal_free_space_headroom` making exhaustion a refusal.)*

**T-13 — `git` as `ValidationCommand.argv[0]`.** Sol ruled it stays legal. **The
cost is that §16's `V-1` row cannot be made *provable*, only restated, and that
all four armed surfaces are reachable on the validation path with no pins.**
**Recorded as a residual, not a closed item** (§5.17.5), and pinned by
`test_git_validation_command_is_accepted_by_the_envelope_validator` **so the
prohibition cannot be acquired by accident either.**

**T-14 — commission the dispatcher-owned Myers/histogram differ.** **MEASURED as
REQUIRED, not preferable:** `difflib.unified_diff` on one real 6.4 MB /
**187,085-line** file **exceeded 100 s and was aborted** where `git diff` took
**1.696 s**, and **all three tuning mitigations aborted >90 s**. The control that
makes this a finding rather than a size effect is `graph.html`: **the same
6.4 MB, 305 lines, 12 ms.** **Sol must commission it or ratify
`regen_max_lines_per_blob` as a refusal boundary** — §5.5.3A specifies both, and
**the seal is worth nothing if the evidence cannot be regenerated from it.**

**T-15 — three scope verdicts, or accept that a literal single-verdict reading of
§8 reopens the resume laundering hole.** *(Recommendation: three verdicts. The
cost is one extra field in `ScopeVerdict`; the alternative costs a closed
defect.)* **The sharpest of the revision-6 escalations.**

**T-16 — what `evidence/diff.patch` MEANS.** Sol §8 makes the **worker** patch
authoritative; §5.5.6 says the **cumulative** patch *"is what `diff.patch` has
always meant and must keep meaning."* **Both cannot own the filename.** Resolved
here as `diff.patch` = the worker patch (Fable's input) and `cumulative.patch` =
the cumulative patch, both dispatcher-composed, both subject to ZI-44. **This
breaks every existing reader of `diff.patch` and Sol must take it deliberately.**

**T-17 — commission the exact binary representation, or leave binary
not-review-complete.** MEASURED to work; MEASURED trap: **Python's
`base64.b85encode` yields `corrupt binary patch`** because git pads the final
group and Python truncates. *(Recommendation: leave it for Wave 0. It is new
dispatcher-owned binary-format code with a silent failure mode — the T-8
raw-DIRC shape — and nothing is hidden meanwhile. **The cost, stated plainly: any
task that changes a binary loses its automated Fable review**, and the remedy is
available and named.)*

**T-18 — commission the two NOT TESTABLE administrative classes.**
`objects/info/commit-graph` / `multi-pack-index` and submodule `modules/**` are
**inventoried and unmeasured**. **Given that `refs/replace` and `info/grafts`
both fired, an un-probed cached-parentage file is not a safe assumption — that is
the exact shape of reasoning §10.3 exists to catalogue.**

**T-19 — `<gitdir>/index` and `<gitdir>/logs/**` as REPORT-ONLY.** Justified by
**measured non-dependence**, not convenience — **and it is the same shape of
judgement that produced the allowlist §5.8.3 just deleted.** The tripwire is
`test_report_only_admin_classes_have_no_reader`. **Sol should rule explicitly
rather than let it pass as integrated.**

**T-20 — the `rev-parse` fallback's scope.** Unavailable at R3/R4 and
post-worker; retained at G10 for the capture of an already-authorized,
already-established repository. **This is a conflict with §5.8.2A as revision 5
wrote it, resolved in §5.8.2B's favour for the authorization step only. Sol must
confirm.** *(The alternative — delete the fallback entirely — is cleaner and
costs the unusual-layout case.)*

**T-21 — §15's "eleven dirty entries" metric.** It is a **`git status` count of a
tree the raw model describes as 46,565 entries, and two of the eleven are
directories.** The intent is preserved and strengthened; **the metric must not be
transliterated, and no implementer may write `assert len(dirty) == 11` against a
raw snapshot.**

**T-22 — strip the eight `GIT_*` redirect variables in
`validation_environment()`.** *(Recommendation: strip. It is **leakage removal,
not hardening**, it does not touch Sol's ruling, and without it a dispatcher-side
`GIT_DIR` reaches a `git` validation command.)*

**T-23 — a validation-caused `POLICY_VIOLATION` punishes the task for the
dispatcher's act.** *(Recommendation: keep the landing, record `attributed_to`,
and name the envelope's `[validation]` block in the remediation. Failing open is
a laundering channel; a distinct terminal state changes §8's row set and every
state consumer.)*

**T-24 — `base_ref` becomes REQUIRED for dev callers too.** *(Recommendation:
yes. A dev-only `"HEAD"` default reintroduces a silent default on a code path
that shares a model with production — ZM-P5's territory.)*

**T-25 — the correction to the brief's own figure.** Sol's tasking records
`/home/dev/full-voice-agent` as *"139+ commits behind `origin/main`"*. **Measured
today: 154** (`06bfcd61…` vs `5eca2113…`). Not a conflict — an update, **and it
is §6's own best argument: the number moved by fifteen while the envelope text
`base_ref: "HEAD"` did not change by one byte.**

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
receives a FIFTH independent architecture review returning ZERO blocking findings
**and `WAVE 0 APPROVED TO IMPLEMENT: YES`.** The reviewer must not be the author,
must not be a prior reviewer, and must not implement the fixes. **This is
directive T, and §19 is its mandate — sixteen attack vectors and a twelve-item
return format, written verbatim.**

**What it should attack hardest — the decisions most likely to be wrong:**

1. **THE SURFACE QUESTION HAS BEEN ANSWERED "NO" THREE TIMES, AND REVISION 6
   STOPS ASKING IT.** Revision 3 asked whether a structural argument plus **two**
   armed surfaces was enough: **S-γ existed.** Revision 4 asked about **three**
   and offered a structural argument — *"object-store reads and ref resolution
   touch neither the working tree, the index, nor any ref mutation"* — **and that
   argument was measured false: S-δ makes an object-store read execute a
   worker-named transport program.** Revision 5 asked about **four**, with no
   structural fallback. **The fourth review then found S-ε, which is not an
   execution surface at all — it does not run a program, it changes what a read
   RESOLVES AGAINST, and no pin in §5.4.3A constrains it.**
   **So the enumeration was never going to converge, and revision 6 subordinates
   it: the enumeration now defends only the PREPARE window, and the post-worker
   window is empty.** **The question for the fifth review is therefore NOT "is
   four enough" — it is: *is the PREPARE window actually the only window, and is
   the seal actually complete?*** Vectors 5 and 16 of §19 are that question in
   executable form. *(A reviewer who still wants to hunt a sixth surface should
   start with the seven un-probed candidates: `core.pager` / `GIT_PAGER`,
   `credential.helper`, `diff.*.textconv` and `diff.*.command`, `core.editor`,
   `uploadpack.packObjectsHook`, `safe.directory`, and `protocol.*.allow` with
   `ext::` — **but a sixth surface no longer changes the post-worker answer, and
   that is the point of §1.**)*
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
   §5.8 is the only thing standing there. **The escape hatch revision 4 offered
   here is now closed:** `dispatcher_raw` cannot be the default, because Z5
   measured it from the worker's side and it does not work (§5.5.5(c)). **So the
   question has no alternative answer left — is §5.8's gate sufficient, and if
   it is not, what is?**
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

## 19. THE FIFTH INDEPENDENT ARCHITECTURE REVIEW — REQUIRED ATTACK LIST (Sol §21)

> No `src/**` or `tests/**` change may be written for Gate 7 until revision 6
> receives a **FIFTH** independent architecture review returning **ZERO blocking
> findings** and **`WAVE 0 APPROVED TO IMPLEMENT: YES`**. The reviewer must not
> be the author, must not be a prior reviewer, and must not implement the fixes.
> **This is directive T.**
>
> **The reviewer MUST attack each of the following sixteen vectors, and MUST
> report each one as `MEASURED` · `NOT TESTABLE` · `NOT ATTEMPTED`. A `clean`
> verdict whose positive control did not fire is reported `NOT TESTABLE`, never
> `clean`.**
>
> 1. **alternates / http-alternates after worker**
> 2. **worktree HEAD rewrite**
> 3. **object store replacement / redirection**
> 4. **partial clone / promisor missing base object**
> 5. **post-worker `cat-file` reintroduction**
> 6. **`rev-parse --show-toplevel`**
> 7. **validation `argv[0] = git`**
> 8. **validation child invoking git**
> 9. **validation-created `dist/`**
> 10. **validation modifying a worker-authored file**
> 11. **changed ignored binary**
> 12. **changed symlink**
> 13. **unchanged ignored symlink**
> 14. **forbidden write + attempted base-store corruption**
> 15. **`PRIMARY_START` / `POST` fidelity**
> 16. **the zero-authoritative-git-after-spawn claim**
>
> ### REQUIRED RETURN FORMAT — all twelve items, in this order
>
> 1. **REVISION 6 SHA**
> 2. **REVIEW VERDICT**
> 3. **BLOCKING FINDINGS**
> 4. **CENTRAL CLAIM VERIFIED: YES / NO**
> 5. **WAVE 0 APPROVED TO IMPLEMENT: YES / NO**
> 6. **pre-worker exact git commands**
> 7. **post-worker authoritative git commands (expected `{}`)**
> 8. **validation execution classification**
> 9. **repository authority snapshot fields**
> 10. **base snapshot completeness proof**
> 11. **`worker_delta` completeness proof**
> 12. **Y-1 … Y-10 mapping**

### 19.1 What each vector attacks, and what a mis-armed control looks like

Written so the mandate is auditable rather than decorative.

| # | Vector | Attacks | The control that makes a negative result meaningful |
|---|---|---|---|
| 1 | alternates / http-alternates after worker | S-ε variant C; revision 5's capture table had **no objects row at all** | **Z-RULE-1B:** delete the alternates file and assert the same blob reads `missing` — **proving the alternate was genuinely the source** |
| 2 | worktree HEAD rewrite | `worktrees/sol-<id>/HEAD` was on §5.8.3's *"NOT protected, deliberately"* allowlist **and** is what B2 reads | write the expected base SHA into it **while the real HEAD has moved**; assert B2 does **not** return `rc=0` with the expected SHA. **Must be run in the `-b` form, where `<gitdir>/HEAD` stays byte-identical** |
| 3 | object store replacement / redirection | `commondir` / gitfile redirection, and **`refs/replace/**` and `info/grafts`, which no revision before this one named** | **the unpinned command must return the DECOY's answer.** For `refs/replace`, assert step (a) returns the **expected SHA at `rc=0`** — that is the signature, not merely a wrong answer |
| 4 | partial clone / promisor missing base object | PIN 1; **F-3's laundering of a policy violation into `FAILED` above rows 4 and 5** | arm `core.sshCommand` / `gitProxy` / `ext::`, **delete a loose base blob**, assert the sentinel **fires without PIN 1**. **And assert the clone is genuinely partial before scoring any row** — `uploadpack.allowFilter` on the source, `missing > 0` as a precondition. **Three separate parties have filed a VOID row here** |
| 5 | post-worker `cat-file` reintroduction | §2A's empty set | add `subprocess.run(["git","cat-file","-e",oid])` to the patch composer and assert **both** halves of §5.4.6 go red. **If only the runtime half fires, the static half is insufficient — report which** |
| 6 | `rev-parse --show-toplevel` | §5.8.2B — F-7's first missing row, **discharged by deletion, not by measurement** | run the **removed** command in the same fixture and assert it returns the **FAKE** path |
| 7 | validation `argv[0] = git` | F-4 — caller argv, no pins, no journal row, **and an AST predicate that is green while the path is live** | declare `["git","diff","--exit-code"]`; assert it appears in `validation-invocations.jsonl` with `authority=false`, in `git-invocations.jsonl` **not at all**, and that `V-1b` **increments a printed number** |
| 8 | validation child invoking git | the same hole one level down: a legal validation binary that *spawns* git | audit hook over the whole process tree, **with a control spawn**. **Note what the design claims here: nothing. §5.17 claims no containment** |
| 9 | validation-created `dist/` | validation runs **between** evidence A and B and its writes are attributed to the worker | assert the path is in `validation_delta`, **not** in `worker_delta`, **and** assert `validation.json[0].exit_code == 0` and `len(validation_delta) == 200` — **not `>= 0`** |
| 10 | validation modifying a worker-authored file | the same seam, worse: **it corrupts the old side** | assert *(patch says `worker`, disk says `validation`)* — **the pair is unsatisfiable by any build that composes the patch after validation, and by any build where validation did not run** |
| 11 | changed ignored binary | F-2 — ZI-25 promises *"the bytes, in full"*, **unachievable for a binary**; directive C's own named attack in binary form | replace an ignored ELF / wheel / `.so`; assert `patch_file_complete` is **not** `true` while the content is omitted, **and** that the classifier assigned `UNTEXTUAL` from the **bytes** |
| 12 | changed symlink | Sol §11: SUPPORTED, never followed, `lstat` + `readlink`, mode `120000` | the fixture **must** contain a **dangling** symlink — `realpath`/`open` cannot resolve it, **so a follow-the-link build fails on that entry** — and the `index` oids must be asserted **independently**, because `git apply` **does not validate them** |
| 13 | unchanged ignored symlink | the Y-10 cliff itself — production contains **1**, this repository **4** | assert a Fable review of an untouched tree containing it is **not** refused. **A walk that skips symlinks entirely passes this** — so assert the symlink is **present in both snapshots with a `content_hash` and a `link_target`** |
| 14 | forbidden write + attempted base-store corruption | F-3's laundering | **the deleted blob needs its own SINGLE-CAUSE test.** In a mixed conflict set this passes because some *other* conflict already lands `POLICY_VIOLATION` — **it would pass even against a build that laundered the deletion into `FAILED`** |
| 15 | `PRIMARY_START` / `POST` fidelity | asymmetric fidelity reads as *unchanged* for any same-size change | mutate one byte between START and POST and assert `POLICY_VIOLATION`; **then restore and assert clean.** And assert the **entry count** — **two empty measurements agree** |
| 16 | the zero-authoritative-git-after-spawn claim | **the claim Y-1 overstated for three revisions** | enumerate every post-spawn git child under an **fd-backed** audit hook **with a live control**, and compare against the declared FINALIZE set **and** against `validation.py:228`. **An in-memory hook loses a `fork`+`exec` child — MEASURED** |

### 19.2 The mandate is auditable, and how

- The acceptance report carries a **sixteen-row table**, one row per vector, each
  `MEASURED` / `NOT TESTABLE` / `NOT ATTEMPTED`, **with the control's outcome
  recorded next to it.**
- **Return item 6 must be GENERATED from `git_order.py`** (§5.4.3B), not typed —
  **otherwise the fifth review re-does F-7 by hand.**
- **Return item 7 is expected to be `{}` and the reviewer should not accept the
  word "authoritative" as doing the work.** §2A's table names the two mechanisms
  that emptied the set; **if either mechanism is absent, the answer is not `{}`
  and the reviewer should say so.** *(Revision 5's `{cat-file, rev-parse}` is
  reconcilable with `{}` only under a definitional reading, and this design does
  not take that route: it deletes the commands.)*
- **Return item 12 must name anything unresolved plainly rather than
  force-mapping it** — the discipline §17 has held for four revisions, and the
  only reason **Y-9 and Y-10 are visible at all.**

### 19.3 What the fifth review inherits, and the one instruction that matters

**Four prior reviews** (R-1…R-14, M-1…M-10 · S-1…S-7, N-a…N-e, Y-1…Y-10 ·
B-1…B-4, N-1…N-7 · **F-1…F-7**), **four probes** (U, X, Z5, **Z7**), **six
drafting lanes** (Z1/Z2/Z3, **Z8/Z9/Z10**), and this document.

**Each of the four reviews found at least one claim whose named proof could not
observe the property.** §10.3 is the catalogue and it now has **fifteen rows.**
Three of them are defects this document introduced **in the same revision that
fixed the identical shape elsewhere.**

> ### **Assume revision 6 contains at least one more, and go find it.**
>
> **The two places this revision is most likely to be wrong, named by the author
> rather than left to be discovered:**
>
> **(1) Route A's coverage (§5.5.2A).** The claim that where the START walk's
> `git-blob-sha1` equals the `ls-tree` oid the bytes on disk **are** the base
> blob is **REASONED from DECISION Z-5's identity, not measured end-to-end.** The
> step that could be wrong is a path where the hashes coincide for a reason other
> than the bytes being the blob — which for sha1 means a collision. **The
> negative was not constructed.** Route B exists so that Route A's failure is a
> **cost, not a correctness bug**, and **the design is correct without Route A at
> the price of one 193 ms pass.**
>
> **(2) The `head_chain_restructured` non-violation (§5.5.2C).** *Report* was
> chosen over *refuse* for a value-preserving ref restructure, on the strength of
> one measurement. The step that could be wrong is whether a restructure can be
> made to **hide** a movement. **The argument is that the resolver recomputes
> `resolved` from the post-state chain and compares it to the sealed `resolved`,
> so a changed value is caught regardless of route — and that is an argument.**
> Falsified by any chain rewrite that yields the sealed `resolved` while the
> worktree's actual HEAD differs.

**And three claims in this document rest on measurements no lane could complete:**
the **NOT TESTABLE** rows for `objects/info/commit-graph`, `multi-pack-index` and
submodule `modules/**` (T-18); the **UNMEASURED** object-presence listing cost at
production scale; and the **UNMEASURED** `packed-refs` read on a repository with
very many refs. **None of them is recorded as clean.**

---

## Appendix A — Measured data and its provenance

All measurements read-only, in disposable `mktemp -d` repositories, git
**2.43.0**, Linux 6.8.0-71-generic, CPython 3.12, `SC_CLK_TCK` = 100.
**`/home/dev/full-voice-agent` verified `06bfcd61` with exactly 11 dirty entries
before and after every measurement. No worker, real or fake, was run against it.**

### A.1 The first two execution surfaces (S-α, S-β)

> **The heading is kept as it was written, because the count in it was wrong.**
> Revision 3 measured two, revision 4 added **S-γ** (A.2), and Lane Z5 added
> **S-δ** (A.2A). This section measures the first two only.

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

### A.2A S-δ — promisor lazy fetch, the fourth surface (Lane Z5)

Repository armed with `core.sshCommand`, `core.gitProxy` and an `ext::` remote,
plus a **deleted base blob** so the object is genuinely absent:

```
POSITIVE CONTROL  fetch                         rc=128  EXEC:sshcommand-prog
cat-file blob <missing>                         rc=128  EXEC:sshcommand-prog
cat-file --batch  <missing>                     rc=0    EXEC:sshcommand-prog   <-- SILENT
ls-tree -r -z --long <base>                     rc=0    EXEC:sshcommand-prog   <-- SILENT
ls-tree -r -z <base>          [no --long]       rc=0    clean
rev-parse --verify HEAD^{commit}                rc=0    clean

--- attempted mitigations ---
blank extensions.partialClone                   rc=0    EXEC  (still fires)
blank remote.origin.promisor                    rc=0    EXEC  (still fires)
blank fetch.negotiationAlgorithm                rc=0    EXEC  (still fires)
GIT_NO_LAZY_FETCH=1                             rc=128  clean (whole column closed)
```

**Two of these commands — `cat-file --batch` and `ls-tree --long` — were on this
design's permitted post-worker list, and two of them return `rc=0` while
executing a worker-named program.** A caller checking only the return code sees
success. `--long` is what arms `ls-tree`: it prints the blob **size**, which
requires the **object**, which triggers the fetch. `ls-tree -r -z` without it
reads only the tree.

**PIN 1 = `GIT_NO_LAZY_FETCH=1`** on every dispatcher git invocation (§5.4.3A).
Note the return code: the pin does not make the read succeed, it makes it
**fail closed**. Config-blanking does not work and must not be substituted.

### A.2B The four-surface repertoire matrix

Every command in §5.4.3's permitted set, against all four surfaces armed
simultaneously, each with its own positive control:

| Command | S-α smudge | S-β fsmonitor | S-γ ref-txn | S-δ promisor |
|---|---|---|---|---|
| `ls-tree -r -z <commit>` *(no `--long`)* | clean | clean | clean | **clean** |
| ~~`ls-tree -r -z --long`~~ | clean | clean | clean | **FIRES, silent, rc=0** |
| `cat-file blob <oid>` | clean | clean | clean | **FIRES, rc=128** — permitted only under PIN 1 |
| `cat-file --batch` | clean | clean | clean | **FIRES, silent, rc=0** — permitted only under PIN 1 |
| `rev-parse --verify <rev>^{commit}` | clean | clean | clean | **clean** |
| `rev-parse --absolute-git-dir` / `--git-common-dir` | clean | clean | clean | **clean** |
| `worktree list --porcelain` | clean | clean | clean | **clean** |
| `rev-list --max-parents=0 HEAD` | clean | clean | clean | **clean** |
| `config --get remote.origin.url` | clean | clean | clean | **clean** |
| `worktree add …` *(mutating; PREPARE only)* | clean w/ `-c core.fsmonitor=false` | clean w/ same | **FIRES** unless PIN 2 | clean |
| **positive control** (`diff`, `fetch`, `git branch`) | **FIRED** | **FIRED** | **FIRED** | **FIRED** |

**Every row's clean verdict is bounded by four armed surfaces. It is not a claim
about a fifth.**

### A.2C The fire-nothing materialisation, and why it is unusable

```
raw admin files + ls-tree/cat-file bytes, 28 hooks + 11 exec keys armed
                                                        ZERO sentinels fired
  worker view: git status  -> every tracked file listed  D  and  ??
  worker edits a file, then git status                   UNCHANGED
                          git diff                       EMPTY

giving it an index:
  read-tree BASE                                  rc=0  HOOK:post-index-change
  GIT_INDEX_FILE=<tmp> read-tree BASE             rc=0  HOOK:post-index-change
  update-index --index-info < stdin               rc=0  HOOK:post-index-change
  GIT_INDEX_FILE=<tmp> read-tree + PIN 2          rc=0  clean

per-worktree hook namespace:
  $GIT_DIR/worktrees/<n>/hooks/reference-transaction   NOT OBSERVED (control fired)

worker core.hooksPath survives dispatcher hook-dir deletion:
  hooks dir deleted, worker core.hooksPath set    rc=0  WORKERHOOK:reference-transaction
  same, via include.path indirection              rc=0  INCHOOK:reference-transaction
  same, + PIN 2 on the argv                       rc=0  clean
```

**Raw-DIRC index written by the dispatcher: NOT TESTED** — see T-8.

### A.2D `git apply` against dispatcher-composed patches

```
empty new file                 --check ok   apply ok   bytes match
new file with content          --check ok   apply ok   bytes match
path with spaces               --check ok   apply ok   bytes match
path with newline (C-quoted)   --check ok   apply ok   bytes match
delete to empty                --check ok   apply ok   bytes match

rejected shapes (so the renderer never emits them):
empty new file with @@ -0,0 +0,0 @@            corrupt patch
empty new file without `new file mode`         no valid patch
a/"new\nline.txt"  (quote inside the prefix)   rejected
```

git's own output for a spaced path appends a **trailing TAB** after
`+++ b/<path>`; the **tab-less form applies identically**, and the renderer emits
the tab-less form (§5.5.8).

### A.2E S-ε — store and reference redirection (Lane Z7, thirteen variants)

The full matrix is in §5.4.1A. The rows that changed this document:

```
B2 DEFEAT, verbatim — probes/z7/p2_b2defeat.sh
  recorded base_commit = 3aafab3fc72ca732c766cfc8c00aad8f9bc9d5bb

  1. worker moves HEAD (ordinary commit), B2 with NO poison
       rev-parse --verify HEAD^{commit} -> rc=0 f1c3d24b…
       B2 VERDICT: FAIL            <-- the control: B2 works when un-poisoned
  2. same, + worker writes the expected base oid into worktrees/task/HEAD
       rev-parse --verify HEAD^{commit} -> rc=0 3aafab3f…
       B2 VERDICT: PASS            <-- DEFEATED, expected SHA, rc=0
       refs/heads/task still at    f1c3d24b…
       --absolute-git-dir / --git-common-dir / --show-toplevel : ALL LEGITIMATE
       alternates file             : ABSENT
  3. what RAW parsing sees and rev-parse cannot
       sealed HEAD would have been : ref: refs/heads/task -> 3aafab3f…
       raw HEAD now                : 3aafab3f…        <-- SYMREF became DETACHED
       raw refs/heads/task now     : f1c3d24b…        <-- the value MOVED

refs/replace/<oid>
  plain                   : FAKEBLOB
  --no-replace            : REAL
  GIT_NO_REPLACE_OBJECTS  : REAL
  cat-file batch plain    : FAKEBLOB
  ls-tree plain           : m.txt
  rev-parse HEAD^{commit} : e14cade2…  (expected e14cade2…)

info/grafts  (first measurement CONFOUNDED and re-armed)
  hint: Support for <GIT_DIR>/info/grafts is deprecated      [stderr only]
  f354f6b5…   rc=0
  true root = a0e21804…  ;  HEAD = f354f6b5…               <-- ROOT COMMIT FORGED
```

**The step-3 observation is what `rev-parse` structurally cannot express: its
entire answer is forty hex characters, so neither the change of FORM (symref →
detached) nor the movement of the underlying ref is representable in it.**

### A.2F The raw administrative parser vs git — 8/8, with a control that failed

```
  AGREE   main-worktree(.git dir)          AGREE   main-worktree(packed-refs)
  AGREE   linked-worktree(.git file)       AGREE   linked-worktree(packed-refs)
  AGREE   linked-worktree(detached)        AGREE   separate-git-dir(no commondir)
  AGREE   linked-worktree(RELATIVE gitfile) AGREE  worktree-of-bare-repo
AGREEMENT: pass=8 fail=0

positive control — a parser deliberately ignoring `commondir`:
  COMMON DISAGREE git=/tmp/z7ctl…/main/.git   raw=…/worktrees/wt1
  HEAD   DISAGREE git=05e860c1…               raw=ref: refs/heads/br1
```

**The harness can fail. The 8/8 is a result, not an artefact.**

The one deliberate disagreement — `core.worktree` redirecting
`--show-toplevel` — is §5.8.2B's argument and is recorded there.

### A.2G Sealing cost, the regeneration cliff, and what is ruled out

```
full-voice-agent — 584 entries / 22 598 354 declared bytes / 540 distinct blobs
                   1311 objects in 6 packs; 2 files > 1 MB = 57% of the base
  hash      0.287–0.377 s        0 bytes
  raw       0.732–1.075 s        23 220 224 bytes on disk
  zlib      0.726–1.967 s         4 317 184 bytes on disk
  packfile  4.65–5.05 s          4 385 122 / 4 376 047 / 4 325 452   <-- 3 RUNS,
                                                                        3 SIZES
  t_ls_tree 0.018–0.079 s in every run — never the cost
  Kavya/ subtree: 170 entries / 4.4 MB -> 75 ms
scaling (synthetic, all LOOSE objects):
     500 /   1.8 MB   t_raw 0.197 s        200 x 256 KB /  44 MB   0.760 s
   2 000 /   7.7 MB   t_raw 0.685 s        200 x   2 MB / 354 MB   2.354 s
  10 000 /  40 MB     t_raw 1.564 s         60 x  16 MB / 788 MB   5.679 s
  40 000 / 163 MB     t_raw 5.059 s                       (zlib:   9.973 s)
  fit: t_seal ~ N x 100 us + B / 140 MB/s
  the fit UNDER-PREDICTS full-voice-agent by 3x (0.22 s vs 0.73 s) because the
  synthetic repos are loose and production is packed -> delta reconstruction
```

**Regeneration, in pure Python, from the seal:**

```
changed file                          base bytes  base lines  git diff  difflib
graphify-out/.graphify_labels.json        14 564           1   0.006 s  0.000 s
graphify-out/GRAPH_REPORT.md             192 904       2 687   0.016 s  0.140 s
graphify-out/manifest.json                89 882       2 382   0.015 s  0.479 s
graphify-out/graph.html                6 393 727         305   0.145 s  0.012 s
graphify-out/graph.json                6 445 536     187 085   1.696 s  >100 s ABORT

mitigations, same file (187 085 -> 254 622 lines):
  SequenceMatcher(interned, autojunk=False)        >90 s ABORT
  SequenceMatcher(interned, autojunk=True)         >90 s ABORT
  common prefix = 3 lines, suffix = 1 line
  trim + SequenceMatcher(interned, autojunk=False) >90 s ABORT
```

**`graph.html` is the control: the same 6.4 MB, 305 lines, 12 ms. The cliff is
LINES, and it is inherent to `difflib`'s algorithm rather than to its input.**

**A second cliff, measured accidentally:** the first regeneration run used
`os.walk` over the working tree and blew a two-minute budget, **because the
untracked `.venv` is in the tree.**

### A.2H Promisor, re-armed — and the VOID row

```
v1  git clone --filter=blob:none over file://  WITHOUT uploadpack.allowFilter
      warning: filtering not recognized by server, ignoring
      missing objects reachable from HEAD : 0
    ==> EVERY ROW MEASURED AGAINST THIS CLONE IS **VOID**, NOT NEGATIVE.

v2  uploadpack.allowFilter on the origin, and `missing > 0` asserted BEFORE
    any row is scored:
      extensions.partialClone : (none)      remote.origin.promisor : true
      objects/pack/*.promisor : 1           missing reachable from HEAD : 3
      cat-file -e $BIG under GIT_NO_LAZY_FETCH=1 : ABSENT

  B. UNPINNED cat-file --batch on an absent object
      before: missing=3   $BIG present? NO
      cat-file --batch (NO pin)  rc=0  header=[16d5001d… blob 270177]
      after : missing=2   $BIG present? YES
      --> a network fetch ran inside a command the design calls read-only

  detection under GIT_NO_LAZY_FETCH=1, on an absent object:
      rev-list --objects --missing=print HEAD   rc=0    LISTS THEM, prefixed '?'
      cat-file --batch-check                    rc=128  fatal
      cat-file --batch                          rc=128  fatal
      ls-tree -r -l HEAD                        rc=128  fatal (the -l size column)
      ls-tree -r HEAD  (no -l)                  rc=0
      rev-parse --verify HEAD^{commit}          rc=0

  materialisation:
      rev-list --missing=print -> fetch <oids>          0.148 s   missing -> 0
      git checkout                                      0.121 s   missing -> 0
      -c remote.origin.partialclonefilter= fetch --refetch  0.107 s  missing -> 0
      git fetch --refetch --filter=                     FAILS: invalid filter-spec

  promisor remote unreachable:
      git fetch                     rc=128
      rev-list --missing=print      rc=0     missing=2
      cat-file --batch (pinned)     rc=128
      rev-parse --verify HEAD       rc=0     <-- a HEAD-only PREPARE would proceed
```

**Three separate parties walked into the same invalid experiment: review 3's N-3,
review 4's first attempt, and Lane Z7's own first run. Z7 reported its own row
VOID rather than filing the negative.**

### A.2I The audit hook's coverage — eleven spawn forms

```
subprocess.run(["git", …])                                 SEEN
subprocess.run(["git", …], stdout=<fd>)   git.py:776 shape SEEN
subprocess.run(argv) with argv[0] a VARIABLE  validation shape  SEEN
asyncio.create_subprocess_exec("git", …)                   SEEN
any of the above inside asyncio.to_thread   _verify_worktree_base shape
                                                           SEEN (thread asyncio_0)
subprocess.run(["/usr/bin/git", …])                        SEEN   literal-"git" BLIND
subprocess.run(["env", "git", …])                          SEEN   literal-"git" BLIND
subprocess.run(["/bin/sh","-c","git …"]) / shell=True      SEEN   literal-"git" BLIND
os.system("git …")                                         SEEN   literal-"git" BLIND
os.posix_spawn(git, …)                                     SEEN   literal-"git" BLIND
os.fork() + os.execv(git, …)          fd sink              SEEN
                                      in-memory list       **LOST**
```

**A predicate matching only the literal string `"git"` at `argv[0]` is blind to
five of six evasions, and an in-memory sink loses the forked child.** This
retires revision 5's `REQUIRES-PROBE` on the audit-hook row.

### A.2J Symlink, kind-change and binary representation

```
symlink object identity
  git ls-tree -r HEAD          120000 blob 7f66e4fb…  link      (link -> f.txt)
  printf 'f.txt' | git hash-object --stdin
                               7f66e4fb…                        IDENTICAL

hand-composed symlink patch (no git diff involved)
  CHECK OK / APPLY OK ; link -> other.txt ; newlink -> /etc/passwd ; islink true
  and the newlink section carried a MALFORMED 39-CHARACTER index oid, and
  `git apply --check` and `git apply` BOTH ACCEPTED IT.

os.symlink('a\nb', 'lf')            OK, readlink == b'a\nb'
os.symlink('', 'empty')             OSError ENOENT  -- cannot exist
os.symlink('/nonexistent/x','dangle') OK, commits and hashes normally
  retarget lf -> b'c\nd' : @@ -1,2 +1,2 @@ with both \ No newline markers;
  hand-composed version applies and reconstructs b'c\nd' AS A SYMLINK

symlink -> regular is TWO sections
  deleted file mode 120000 ... @@ -1 +0,0 @@ -target
  new file mode 100644     ... @@ -0,0 +1 @@ +now a regular file

binary
  default:  "Binary files a/b.bin and b/b.bin differ"   -- not a representation
  composed with git's base85 (4-byte zero padding, full five-char groups):
      BINARY CHECK OK / BINARY APPLY OK / byte-exact / REVERSE OK
  the identical code using Python base64.b85encode:
      error: corrupt binary patch at line 8 ; error: No valid patches in input
```

**`git apply` does not validate index lines, so a renderer test that proves
itself by applying can pass while the index line is garbage.** The alphabet of
Python's b85 matches RFC 1924; **the padding does not.**

### A.2K Production repository facts, read-only

```
HEAD                                   06bfcd619a71272a9ce477484f54566a1e8ae849
origin/main                            5eca21131d767a5c00fbf917e3f4192050de2002
rev-list --count HEAD..origin/main     154        (Sol's brief recorded "139+")
status --porcelain | wc -l             11         (5 modified, 6 untracked,
                                                   TWO OF THEM DIRECTORIES)
raw model of the same tree             46 565 entries / 789.9 MB
tracked set                            584 entries / 22.6 MB
ignored symlinks                       1   (this repository: 4)
FIFOs / sockets / devices              0   (both hosts)
uppercase SHA input to rev-parse       normalised to lowercase on output, rc=0
annotated tag oid ^{commit}            returns a DIFFERENT oid   a6d2ba69 -> 5192a5a1
--end-of-options on rev-parse          supported on 2.43.0
```

**Every command above was read-only, under `--no-optional-locks`, with no index
write. Nothing was written to that repository by any lane.**

### A.3 Checkout transform on an ordinary repository

Committed `.gitattributes`: `* text eol=crlf` and `*.dat filter=lfsish`

```
blob bytes eol.txt      : l i n e 1 \n l i n e 2 \n
worktree bytes eol.txt  : l i n e 1 \r \n l i n e 2 \r \n
blob bytes thing.dat    : p a y l o a d \n
worktree bytes thing.dat: S M U D G E D : p a y l o a d \r \n
```

### A.4 `ls-tree -r -z` path encoding, and the dispatcher-side blob oid

*(measured with `--long`, before Z5 established that `--long` arms S-δ; the path
encoding is unaffected by the flag — `--long` adds a size field to the head, not
to the path)*

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

## Appendix C — Revision 6 change log

| Section | Change | Driver |
|---|---|---|
| header | revision 6; **the central invariant stated first**; the twenty-one-directive map; the reason the count was never the point | Sol §1 |
| §0 | **Z-RULE-1B** (integrity controls) — six of §19's sixteen vectors execute nothing, so six can only be controlled that way; the **eight-label** vocabulary, with **`VOID`** added because three separate parties filed the same invalid promisor experiment | F-5, Z7 |
| §0.1 | Sol's **§1 … §21** mapped; the A–T set retained as history with supersessions recorded in §18.3B | Sol |
| **§2A** *(new)* | **ZERO AUTHORITATIVE GIT AFTER SPAWN.** The mechanism table that empties the set, the one surviving post-worker spawn named in the same breath, the proof obligations, and **what this is not — it is not an OS sandbox** | **Sol §1** |
| §4.14 *(new)* | production `base_ref` is `^[0-9a-f]{40}$` with a **byte-equality post-condition**; the default deleted; **154 commits, not 139**; the dispatcher never fetches | Sol §6 |
| §5.4.1A/B *(new)* | **S-ε** — thirteen measured variants; `refs/replace/**` reproduces the brief's signature exactly; `info/grafts` is live; **alternates is an availability primitive, not a forgery primitive**; deleting it does **not** close variant C | Sol §4, F-5, Z7 |
| §5.4.3 | the repertoire becomes **ten PREPARE rows and `{}` after the spawn**; **three deletions** (`--show-toplevel`, `read-tree`, `--is-inside-work-tree`); `rev-list --objects --missing=print` added; **PIN 3** | Sol §16, §17, F-7 |
| §5.4.3A | **PIN 3** `GIT_NO_REPLACE_OBJECTS=1`; `--attr-source` **deleted**; **the measured statement that none of the pins is in the tree**, so dependent acceptance rows are **UNMEASURABLE, not green** | Z7 |
| §5.4.3B *(new)* | the pre-worker order **declared as data**, per path, with a `_run_git` **interlock** and a journal **corroborator**; **A.2B is GENERATED from it** | Sol §19, F-7 |
| §5.4.5 | the FINALIZE journal window is **empty**; the argv pin and the seam counter are **deleted with it**; the full sixteen-invocation inventory with its replacements; **`validation.py:228` named as the chokepoint hole that matters** | Sol §17, F-4, Z7 |
| §5.4.6 | the killer is **two halves, both required**, and its predicate moves **from the argv to the callee**; the fd-backed runtime hook retires the audit-hook `REQUIRES-PROBE`; **eight positive-control mutants**, one of them killed **only** by the runtime half | Sol §17, F-4 |
| §5.5.1 | the pipeline gains the **seal**, the **three states** and the **validation step it never had** | Sol §2, §8 |
| §5.5.2 / §5.5.2A | `BaseTreeSnapshot` carries **exact content bytes** in an oid-keyed CAS; `blob_size` deleted; `complete: Literal[True]`; the manifest written **last**; **the seal is per-task and is NEVER recreated**; `old_side`'s lazy branch deleted | Sol §2 |
| §5.5.2B *(new)* | promisor materialisation as a **five-step sequence with a re-verification that is not implied by the fetch**; `rev-parse --verify HEAD` returns `rc=0` in an unreadable repository | Sol §3, Z7 |
| §5.5.2C *(new)* | **B2 with no git command.** Sol's literal form is **falsified and corrected**: `<gitdir>/HEAD` is a symref and is byte-identical after a worker commit; `pack-refs` deletes the sealed loose ref without moving a value | Sol §5, Z8 |
| §5.5.3A *(new)* | the seal budget from **measured** data, and **B-REGEN-1 — max lines per blob — the budget that fails first and that no draft had**; `pack-objects` **ruled out**; a Myers/histogram differ is **REQUIRED** | Z7 |
| §5.5.6 | **three raw filesystem states**, identity-wise deltas, the **closure theorem**, three scope verdicts, and the reason the patch must be frozen **before** validation | Sol §8, F-1 |
| §5.5.9 | **one IFF, one producer, NO THIRD COLUMN**; `BULK_CREATED_IGNORED` **deleted**; **symlinks SUPPORTED**; the binary escape hatch costed | Sol §9, §11, F-1, F-2 |
| §5.8.2 | the capture table gains **fifteen rows**, including `refs/replace/**`, `info/grafts`, the HEAD chain, `packed-refs`, the `objects/info/` **listing** and object presence | Sol §14, Z7 |
| §5.8.2B *(new)* | **authorization is `realpath` equality**; `git_top_level` / `git_top_level_or_none` / `is_git_repository` **deleted**; **the precondition that makes §5.4.3B's order possible** | Sol §7, F-7 |
| §5.8.3 | **the allowlist is DELETED in its entirety**; *"objects are immutable"* deleted; **dependence, not convenience**, with the two report-only classes escalated | Sol §14 |
| §5.9 | the primary tree is **raw equality, no `git status` in any form**; **symmetric fidelity**; a machine-checked **write prohibition**; **"eleven dirty entries" is a metric that does not exist in the model** | Sol §15 |
| §5.11 | Fable's guard reads **both** flags; six labelled prompt sections; the `both_authors` mandatory sentence; the paired tests that make each non-vacuous | Sol §12 |
| §5.12 | ~25 new codes; **`BaseBlobUnreadable` exists ONLY in PREPARE**, so F-3's laundering route does not exist; the single-cause deleted-blob test | Sol §13, F-3 |
| §5.17 *(new)* | **validation is an execution domain**: it may run `git`; the invariant is **authority, not containment**; two journals, **two** post-worker admin captures, and the **evidence freeze** that detects but does not prevent | Sol §10, F-4 |
| §8 | row 0 and row 4 gain their new classes; **row 5a is renamed** to carry attribution ambiguity; a new row 5b was **considered and rejected** | Sol §8, §13 |
| §10.3 | **eight new rows** — including three defects this document introduced in the same revision that fixed the identical shape elsewhere | F-1…F-7 |
| §12.2A *(new)* | **`owns ≡ creates`**, split from `lands_in` and `modifies`; `creates(baseline, 5)`; **the mutation runner and the registry are Wave 0** | Sol §20 |
| §12.3 | Wave 0 grows again, and the reason is that **every new mechanism is a precondition for the post-worker set being empty** | Sol §20 |
| §15.2 | **C16 … C20**, including a validation child that **outlives the dispatcher** | Sol §8, §10 |
| §16 | `V-1` becomes **`V-1a` + `V-1b`** so a live `git` validation command increments a printed number; **pin rows that print UNMEASURABLE** | F-4, Z7 |
| §17 | the Y-map carried into revision 6; **Y-1's headline is replaced rather than restated**; **Y-9 unratified for the fourth revision running**; **Y-10 ratifiable for its symlink half** | Sol |
| §18.3B *(new)* | **T-11 … T-25**, and the supersessions of T-1/T-2/T-6 | Sol |
| **§19** *(new)* | **the fifth-review mandate — sixteen vectors and the twelve-item return format, verbatim** — plus what a mis-armed control looks like for each, and **the two places the author judges this revision most likely to be wrong** | **Sol §21** |
| Appendix A | **A.2E–A.2K** — S-ε, the parser's 8/8 with its failing control, sealing cost and the regeneration cliff, the re-armed promisor with its VOID row, the audit hook's eleven forms, symlink/binary rendering, and the production facts | Z7, Z8, Z9, Z10 |

---

## Appendix C1 — Revision 5 change log (retained)

| Section | Change | Driver |
|---|---|---|
| header | revision 5; the **honest framing** the fourth reviewer is owed — *"closed structurally"* → *"closed by an enumerated, argv- and env-pinned defence on four measured surfaces, with no proof that four is all of them"*; the surface count has been wrong **twice** | Z5 |
| §0 | **`NOT TESTED` / `NOT OBSERVED`** adopted as marked vocabulary, distinct from `REQUIRES-PROBE` | Z5 item 6 |
| §5.4.1 | **S-δ — a fourth execution surface.** Revision 4's *"structural property of object-store reads"* paragraph is **quoted and deleted**; the count is corrected from three to four | Z5 item 2 |
| §5.4.3 | repertoire matrix re-measured on **four** columns; `ls-tree --long` **struck**; `cat-file` rows permitted **only under PIN 1**; Lane X's TIER-0 table **corrected** — `core.sshCommand` / `core.gitProxy` are executed, not inert | Z5 item 2 |
| §5.4.3A *(new)* | the **global git invocation policy** in one block: **PIN 1** `GIT_NO_LAZY_FETCH=1` on every invocation, **PIN 2** `-c core.hooksPath=<empty dir>` on every mutating one, with the measured caveats and the `GIT_CONFIG_KEY0` **NOT TESTABLE** note | Z5 items 1–2 |
| §5.4.5 | the invocation journal is **blind** to `git.py:776` — a live `subprocess.run(["git","diff",…])` outside `_run_git` | Z5 item 3 |
| §5.4.6 | **`test_no_direct_git_subprocess_in_src`** specified (AST over the whole tree), and stated to **fail against `HEAD`**, with `git.py:776` as the **day-one killer** | Z5 item 3 |
| §5.5.2 | **`--long` removed** from `BaseTreeSnapshot`'s argv; `blob_size: int \| None`; the `ls-tree` parser no longer assumes a size field; **ZM-D7…ZM-D10** added | Z5 item 2 |
| §5.5.5 | **rewritten.** (a) the ordering fix **does not work** — worker `core.hooksPath`, direct or via `include.path`, survives deleting `$GIT_COMMON_DIR/hooks`, and there is no per-worktree hooks namespace; **filesystem quarantine is not a defence, only argv pinning is**; (b) Z-3 revised to gate **and** pin; (c) **Z-4 RETIRED, not rescued** — fire-nothing only when unusable, usable only when it fires; (d) the exact default argv | Z5 item 1 |
| §5.5.8 | the `git apply --check` **`REQUIRES-PROBE` is RETIRED** — every §9 edge case applies byte-exactly — and **three measured format constraints** become renderer rules | Z5 items 4–5 |
| §10.3 | two new rows: revision 4's **own** falsified "structural property" paragraph, and its unmeasured "structural" claim for Z-4 | Z5 items 1–2 |
| §10.4 | the `read-tree` probe hazard is worse than recorded — the `read-tree` itself fires | Z5 item 1 |
| §18.1 | Z1's list: item (2) retired **negatively**, item (3) retired **positively**; caveat (10) *"proven twice"* | Z5 |
| §18.3A | **T-2 superseded** (the fourth surface arrived before Sol's ruling); **T-2A** ratify PIN 1/PIN 2; **T-2B** remove `--long`; **T-3 closed negatively**; **T-6** corrected argv and `--is-inside-work-tree` dropped; **T-8** raw-DIRC index — commission or close; **T-9** `git.py:776` as Wave-0 work | Z5 items 1–3 |
| §18.5 | attack item 1 rewritten: *answered NO twice*; **no structural argument remains**; seven un-probed candidate fifth surfaces named for the reviewer | Z5 |
| Appendix A | **A.1** retitled (its count was wrong); **A.2A** S-δ measurements; **A.2B** the four-surface matrix; **A.2C** the fire-nothing/index dichotomy and the hooks-survival result; **A.2D** `git apply` results and the rejected shapes; **A.4** retitled | Z5 |

---

## Appendix C2 — Revision 4 change log (retained)

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
| §5.5.5 | `# executes NOTHING` **deleted**; Z-4 **demoted from "structural" to "gated"**; **OPEN pending Lane Z5** *(closed negatively in revision 5)* | B-2 |
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
