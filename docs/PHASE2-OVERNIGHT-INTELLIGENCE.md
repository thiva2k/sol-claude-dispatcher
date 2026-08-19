# PHASE 2 — OVERNIGHT INTELLIGENCE (design only, not built)

**Status: not implemented in V1.** No scheduler, no collector, no analysis
pass exists in this codebase. What exists today is the design and the
schema this future capability will need (§36) — written now so the
approval boundary is fixed in writing before there is any temptation to
blur it during implementation.

---

## 1. Why this document exists before the code

§36 of the build brief is explicit: *"Do not implement the scheduler yet.
DO implement the design and schemas necessary for it."* The risk this
guards against is not technical difficulty — it's scope creep on the single
most safety-critical property a background analysis system can have:
**it must never be able to act.** Writing the boundary down now, and
building `schemas/improvement-proposal.schema.json` and
`prompts/future-sol-observer.md` as inert artifacts today, means a future
implementation has no ambiguity to "interpret" later.

---

## 2. Future architecture

```text
LOG COLLECTORS
      │            (application logs, service errors, failed test runs,
      │             resource usage trends, recurring warnings, repository
      │             health signals, operational incidents — read-only
      │             inputs, never a live repository write)
      ▼
EvidenceBundle
      │            (not yet a schema; would carry raw observed signals,
      │             grouped, before Sol turns any of them into a proposal)
      ▼
SOL
      │            (Sol reads evidence, synthesizes proposals — this is
      │             where judgement lives, same as everywhere else in this
      │             system)
      ▼
ImprovementProposal
      │            (schemas/improvement-proposal.schema.json — built and
      │             validated today, §3 below)
      ▼
state/proposals/
      │            (filesystem JSON, same discipline as state/tasks/ —
      │             atomic writes, 0700/0600, fail-closed on corruption)
      ▼
MORNING SUMMARY
      │            ($ sol-morning — §5 below)
      ▼
USER APPROVAL
      │            (the only step that can turn a proposal into work —
      │             explicit, human, and never inferred)
      ▼
TaskEnvelope
      │            (built the same way any other dispatch is: through
      │             TaskEnvelope.from_request, after human approval)
      ▼
Claude implementation
      (dispatch_claude_task, exactly as documented in
       docs/ARCHITECTURE.md §3 — no different code path for
       proposal-originated work)
```

The load-bearing property of this diagram: **every arrow above
`USER APPROVAL` is read-only or advisory.** Nothing before that box can
write to a repository, and nothing after it happens without a human having
crossed that box first.

---

## 3. The read-only-overnight law (§36)

> **Overnight analysis is read-only.**

No overnight proposal may automatically invoke:

- `dispatch_claude_task`
- `resume_claude_task`
- a git edit of any kind
- a merge
- a push
- a deployment

This is enforced in the design in three independent ways, so that no single
mistake breaks it:

1. **No code path exists.** There is no scheduler in V1, so there is
   nothing to invoke `dispatch_claude_task` overnight even in error — the
   only caller of that tool is the MCP server responding to Sol.
2. **The schema has no such field.** `improvement-proposal.schema.json` has
   no property that names a task id, a dispatch action, or an execution
   trigger except `task_id` (nullable, and per its own description: *"Dispatcher
   task created from this proposal, once approved and dispatched"* —
   written by the dispatcher after human approval, never by the analysis
   pass) and `implementation_started` (boolean, description: *"Set by the
   dispatcher when a task is created from this proposal, after approval.
   Never set by the analysis pass."*).
3. **The prompt says so explicitly.** `prompts/future-sol-observer.md` — a
   stub today, loaded by nothing — lists under "Absolute constraints":
   modify no file, run no writing/deleting/installing/restarting command,
   create no branch/commit/worktree/tag/stash, never push/merge/deploy,
   never call `dispatch_claude_task`/`resume_claude_task`, never act on a
   proposal it produced itself, never wake or notify anyone automatically.

Per `CLAUDE.md`'s own standard ("prompts are not sandboxing"), (3) alone
would not be a sufficient guarantee — which is exactly why (1) and (2) exist
independently of it. When Phase 2 is eventually built, whatever process runs
the observer must still be denied `dispatch_claude_task`/`resume_claude_task`
by construction (no MCP access, same as a worker — see `docs/SECURITY.md`
§2 layer 1), not merely instructed not to use them.

---

## 4. `ImprovementProposal` schema (§37)

Defined today at `schemas/improvement-proposal.schema.json`, `additionalProperties: false`,
`schema_version` pinned to `"1.0"`. Required fields: `schema_version`,
`proposal_id` (pattern `^P-[0-9]{3,}$`), `created_at`, `repository`, `title`,
`summary`, `evidence` (min 1 item — *"A proposal without evidence is
speculation and must not be raised"*), `impact` (`low`/`medium`/`high`),
`confidence` (0.0–1.0), `risk` (`low`/`medium`/`high`/`critical`),
`proposed_plan` (min 1 item), `status`, `implementation_started`.

Each `evidence[]` entry requires `source` and `observation`, with optional
`reference` (a pointer to the specific occurrence — line range, timestamp,
test id) and `occurrences` (integer count). This is the same discipline as
`worker_claims` vs `dispatcher_observations` elsewhere in this system: a
proposal that cannot cite a concrete source and observation must not be
raised at all, mirroring "claims are not evidence" from `CLAUDE.md`.

`status` enumerates the full proposal lifecycle:

```text
pending_user_review   — the only state a newly created proposal may start in
approved              — set only by an explicit human decision
rejected              — set only by an explicit human decision
superseded            — a newer proposal (superseded_by) replaces this one
implemented           — a task was dispatched from this proposal and finished
```

The schema's own description is explicit about the one rule that matters
most: *"Only an explicit human decision may move it to approved or
rejected."* **Approval must never be inferred from Sol merely creating a
proposal** — creating `P-106` with `status: "pending_user_review"` is Sol
doing its job (synthesizing evidence into something reviewable); it is not,
and must never be treated as, the human having agreed to anything.

---

## 5. Morning experience — design target (§38)

```text
$ sol-morning

Overnight Engineering Review
────────────────────────────

4 potential improvements found.

P-104  HIGH confidence / MEDIUM impact
Repeated connection retry storm detected
Evidence: 37 occurrences across 6 hours

P-105  MEDIUM confidence / LOW impact
Redundant API query observed

P-106  HIGH confidence / HIGH impact
Test suite reveals rollback gap

P-107  LOW confidence / MEDIUM impact
Potential cache inefficiency

No code was modified overnight.
```

The closing line — *"No code was modified overnight"* — is not decoration;
it is the one sentence the whole feature exists to be able to say honestly
every single morning, and every design decision in this document is in
service of it remaining true.

From there, the interaction is conversational and still entirely read-only
until the human explicitly crosses the approval boundary:

```text
> Show me P-106.

Sol explains:
  evidence
  reasoning
  proposed architecture
  risk
  implementation plan

> Implement P-106.

Only now does Sol build a TaskEnvelope and call dispatch_claude_task.
```

`sol-morning` itself does not exist as code in V1 — no CLI entry point, no
`state/proposals/` reader is implemented. This section documents the
target shape so that when it is built, "show me P-106" and "implement
P-106" remain two conversational turns with a real human decision between
them, not one command that happens to print a confirmation first.

---

## 6. Extension points that exist today

Nothing above is theoretical scaffolding-only — three concrete artifacts
are already built and ready for a future scheduler to use without needing
to be redesigned:

| Artifact | Status today | Role in Phase 2 |
|---|---|---|
| `schemas/improvement-proposal.schema.json` | Complete, `additionalProperties: false`, validated JSON Schema draft 2020-12 | The wire format every `ImprovementProposal` must satisfy before it is written to `state/proposals/` |
| `state/proposals/` | Directory exists (`state/proposals/.gitkeep`), no writer yet | Where proposals will live, following the same atomic-write/fail-closed discipline as `state/tasks/` (`state.py`'s `atomic_write_json` is already general-purpose and reusable here without modification) |
| `prompts/future-sol-observer.md` | Written, explicitly marked "not implemented," loaded by nothing in V1 | The intended system-prompt policy for whatever process eventually performs the read-only analysis pass — already states the absolute constraints from §3 above |

A future implementation's job is to build the collector(s), the
`EvidenceBundle` intermediate representation (not yet schematized — that is
genuinely open design work, unlike the proposal schema which is fixed), the
`sol-morning` reader/CLI, and the scheduler that runs the observer — all
without touching the approval boundary this document and the three
artifacts above already fix in place.
