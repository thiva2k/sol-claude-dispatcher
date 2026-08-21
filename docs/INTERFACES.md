# INTERFACES — the build contract

**Audience:** the agents implementing Waves 2, 3 and 4 in parallel.

**Status:** authoritative. Wave 1 has built and tested `models.py`, `errors.py`
and `config.py`. Everything below is the exact surface the remaining modules
must present. Code against this document, not against your own guesses, and
three people working without talking to each other will still produce modules
that fit together.

**If you believe a signature here is wrong**, implement it as written and note
the objection in your final report. Silently "improving" a shared signature
breaks someone else's module that you cannot see.

Section references (§n) point at the build brief.

---

## 0. Ground rules that apply to every module

1. **`argv` lists, never shells.** `asyncio.create_subprocess_exec` /
   `subprocess.run([...])`. No `shell=True`, no f-string commands. (§9)
2. **Never execute anything that came out of a Claude result.** The only
   commands the dispatcher runs are the ones in `envelope.validation.commands`
   and the git commands this document names. (§9, §17)
3. **Raise `DispatcherError` subclasses**, never bare exceptions, for anything
   that can reach the MCP boundary. Put diagnostics in `details`, keep
   `message` to one sentence. (§29)
4. **Nothing writes to stdout.** stdout is the MCP transport. Log to stderr or
   a file. A stray `print()` corrupts the protocol. (§28)
5. **Fail closed.** If you cannot prove something is safe, refuse.
6. **The dispatcher never decides approval.** There is no `APPROVED` state and
   you must not add one. (§26, §41)
7. **Worker claims never become dispatcher observations.** They are different
   types and they stay in different fields, forever. (§16)
8. **Do not spawn real `claude` or `codex` during the build.** Tests use
   `tests/fake_bin/claude`. (§32)

Import style: relative imports inside the package (`from .models import ...`).

---

## 1. What already exists (do not modify without saying so)

### `sol_claude_dispatcher.models`

Full field lists — this is the data contract.

#### Identity helpers

```python
SCHEMA_VERSION: str                 # "1.0"
WORKTREE_NAME_RE: re.Pattern        # ^sol-[0-9a-f]{8}$

utc_now() -> datetime               # timezone-aware UTC. Use this everywhere.
new_task_id() -> str                # uuid4 string
new_session_id() -> str             # uuid4 string; --session-id demands a UUID
new_run_id() -> str                 # 12 hex chars
short_task_id(task_id: str) -> str  # first 8 hex chars; raises ValueError on non-hex
worktree_name_for(task_id: str) -> str   # "sol-<short>"; the ONLY naming rule
```

#### Enums

| Enum | Members (values) |
|---|---|
| `TaskKind` | `implementation`, `bugfix`, `refactor`, `tests`, `docs`, `security_sensitive`, `concurrency`, `migration`, `deep_debugging`, `large_refactor` |
| `Complexity` | `low`, `medium`, `high` |
| `RiskLevel` | `low`, `medium`, `high`, `critical` |
| `RequestedModel` | `auto`, `sonnet`, `opus` — **no `fable`** |
| `WorkerRole` | `implementer`, `reviewer` |
| `RunKind` | `dispatch`, `resume`, `review` |
| `WorkerStatus` | `completed`, `blocked`, `failed` |
| `FableVerdict` | `approve`, `changes_required`, `reject` |
| `FableSeverity` | `info`, `low`, `medium`, `high`, `critical` |
| `FableCategory` | `correctness`, `architecture`, `security`, `tests`, `performance`, `maintainability`, `requirements` |
| `RecommendedNextAction` | `accept`, `resume_worker`, `escalate_to_opus`, `reject`, `human_review` |
| `TaskState` | `created`, `routed`, `running`, `implemented`, `awaiting_sol_review`, `fable_reviewed`, `resume_requested`, `review_complete`, `timed_out`, `blocked`, `failed`, `policy_violation` |

Also exported:

```python
ESCALATING_TASK_KINDS: frozenset[TaskKind]   # the five that force Opus
TERMINAL_STATES: frozenset[TaskState]        # {REVIEW_COMPLETE}
ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]]
is_transition_allowed(src: TaskState, dst: TaskState) -> bool
```

`ALLOWED_TRANSITIONS` is the state machine. `state.py` enforces it and adds
nothing to it. Full table:

```
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
FAILED              -> AWAITING_SOL_REVIEW, RESUME_REQUESTED
REVIEW_COMPLETE     -> (terminal)
```

Note the deliberate omission: **no off-ramp jumps straight back to `RUNNING`.**
A resume always passes through `RESUME_REQUESTED` so the resume cap is
consulted exactly once, in one place.

#### Caller input — `TaskRequest` (`extra="forbid"`)

```python
TaskRequest:
    repository:  RepositoryRequest
    task:        TaskSpec
    scope:       ScopeSpec        = ScopeSpec()
    validation:  ValidationSpec   = ValidationSpec()
    routing:     RoutingSpec      = RoutingSpec()
    execution:   ExecutionSpec    = ExecutionSpec()
    constraints: ConstraintsSpec  = ConstraintsSpec()
    parent_task_id: str | None    = None

RepositoryRequest:
    root: str                 # must start with "/"; NOT yet allowlist-checked
    base_ref: str = "HEAD"
    workspace_mode: Literal["worktree"] = "worktree"

TaskSpec:
    kind: TaskKind = implementation
    objective: str            # non-empty
    context: str = ""
    acceptance_criteria: list[str] = []

ScopeSpec:
    allowed_paths: list[str] = []      # repo-relative globs; no "/", "~", ".."
    forbidden_paths: list[str] = []

ValidationSpec:
    commands: list[ValidationCommand] = []

ValidationCommand:
    argv: list[str]                    # min 1; argv[0] may not be a shell
    timeout_seconds: int = 600         # 1..3600

RoutingSpec:
    requested_model: RequestedModel = auto   # accepts key "model" or "requested_model"
    complexity: Complexity = medium
    risk: RiskLevel = medium

ExecutionSpec:
    timeout_seconds: int = 1800
    max_turns: int = 40
    max_resume_count: int = 4
    max_budget_usd: float | None = None

ConstraintsSpec:
    allow_network: bool = False      # a REAL policy flag; changes the prompt
    allow_push / allow_merge / allow_commit / allow_subagents: bool = False
        # ALWAYS FALSE. Validators REFUSE `true` at the model, request and
        # config layers — these are not caller options. The operations they
        # name are prohibited by code-level invariants no flag can influence
        # (runner.CORE_DENIED_GIT_OPERATIONS, _assert_invocation_sane). The
        # fields are kept rather than deleted because TaskRequest/Config are
        # extra="forbid", so removing them would break every stored envelope
        # and shipped config that mentions them.
```

`TaskRequest` has **no** `task_id`, `run_id`, `session_id`, `worktree`,
`base_commit`, `schema_version`, `resume_count`, `dispatch_depth`, `state` or
`created_at`. Supplying any of them is a `ValidationError`, not a silent
ignore. That is the §7.1 guarantee, and it is tested.

#### Dispatcher truth — `TaskEnvelope`

```python
TaskEnvelope:
    schema_version: Literal["1.0"]   # REQUIRED, no default (unversioned = error)
    task_id: str
    created_at: datetime
    repository: RepositoryResolved   # + base_commit: str (hex, 7..64)
    task / scope / validation / routing / execution / constraints  # carried through
    lineage: LineageSpec
    worktree_name: str               # must equal worktree_name_for(task_id)

LineageSpec:
    parent_task_id: str | None
    previous_session_id: str | None
    escalation_reason: str | None
    dispatch_depth: int = 0
```

**The only construction path:**

```python
TaskEnvelope.from_request(
    request: TaskRequest,
    *,
    canonical_root: str,          # from security.validate_repository_root
    base_commit: str,             # from git.resolve_base_commit
    task_id: str | None = None,
    created_at: datetime | None = None,
    dispatch_depth: int = 0,
    previous_session_id: str | None = None,
    escalation_reason: str | None = None,
) -> TaskEnvelope
```

#### Worker claims — `WorkerResult`

```python
WorkerResult:
    status: WorkerStatus
    summary: str                                   # non-empty
    changes: list[ChangedFile] = []                # path, type, description
    acceptance_criteria: list[AcceptanceCriterionResult] = []
    tests: list[TestReport] = []                   # command, status, exit_code, summary
    risks: list[str] = []
    blockers: list[str] = []
    needs_review: bool = True
```

Field-for-field identical to `schemas/worker-result.schema.json` (a test
enforces this). If you change one, change both.

#### Reviewer output — `FableReview`

```python
FableReview:
    verdict: FableVerdict
    findings: list[FableFinding] = []      # id, severity, category, path, line,
                                           # finding, evidence, recommendation
    missing_tests: list[str] = []
    architecture_notes: list[str] = []
    recommended_next_action: RecommendedNextAction
```

Mirrors `schemas/fable-review.schema.json` (also test-enforced).

#### Dispatcher observations — never merged with claims

```python
ValidationResult:
    source: Literal["dispatcher"] = "dispatcher"   # cannot be set to anything else
    argv: list[str]
    exit_code: int | None
    passed: bool
    timed_out: bool = False
    duration_ms: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    stdout_bytes: int = 0; stderr_bytes: int = 0        # what the child wrote
    stdout_truncated: bool = False; stderr_truncated: bool = False
    # A timed-out command keeps whatever it had already produced: the tails are
    # fed by dedicated reader tasks the caller owns, not by communicate().

RunMetadata:
    run_id: str; run_index: int (>=1); task_id: str
    kind: RunKind; role: WorkerRole; model: str; session_id: str
    worktree_path: str | None
    started_at: datetime; finished_at: datetime | None; duration_ms: int | None
    exit_code: int | None; timed_out: bool; killed_with_sigkill: bool
    argv_redacted: list[str]
    stdout_bytes: int; stderr_bytes: int      # what the child WROTE, not the
                                              # size of the retained excerpt
    stdout_truncated: bool = False            # excerpt is short of the stream
    stderr_truncated: bool = False

DispatcherObservations:
    task_id, run_id, session_id, model, base_commit: str
    duration_ms: int; exit_code: int | None; timed_out: bool
    changed_paths: list[str]; diff_stat: str
    diff_bytes: int                  # retained in memory (capped)
    diff_total_bytes: int = 0        # as git produced it; > diff_bytes means
                                     # the in-memory value was capped
    scope_valid: bool; out_of_scope_paths: list[str]; forbidden_paths_touched: list[str]
    diff_check_passed: bool
    worker_result_parsed: bool; worker_result_error: str | None
    primary_worktree_clean: bool | None    # literal: no uncommitted changes NOW
    primary_tree_unchanged: bool | None    # the non-interference VERDICT
                                           # (post fingerprint == pre); None
                                           # means not compared for that run

RunRecord:
    metadata: RunMetadata
    worker_claims: WorkerResult | None            # what Claude SAID
    dispatcher_observations: DispatcherObservations | None   # what we MEASURED
    validation_results: list[ValidationResult]

TaskRecord:                                        # the mutable half, state.json
    schema_version: Literal["1.0"]
    task_id: str
    state: TaskState
    selected_model: str | None
    session_id: str | None
    worktree_path: str | None
    resume_count: int = 0
    run_count: int = 0
    created_at: datetime; updated_at: datetime
    state_history: list[dict]        # {"from","to","at","reason"}
    last_error: dict | None          # a DispatcherError.to_payload()
    policy_violations: list[str]
    fable_review_count: int = 0
```

A test asserts `WorkerResult` and `DispatcherObservations` share **zero** field
names. Keep it that way.

### `sol_claude_dispatcher.errors`

`DispatcherError(message, *, details=None, remediation=None)` with
`.code`, `.retryable`, `.to_payload() -> dict`.

Subclasses: `InvalidRepository`, `RepositoryNotAllowed`, `RepositoryBusy`
(retryable), `WorktreeCreationFailed`, `InvalidTaskEnvelope`,
`InvalidStateTransition`, `TaskNotFound`, `StateCorruption`,
`ClaudeBinaryNotFound`, `ClaudeExecutionFailed`,
`ClaudeStructuredOutputInvalid`, `ClaudeTimedOut`, `ResumeLimitReached`,
`PolicyViolation`, `ValidationFailed`, `GitEvidenceCollectionFailed`,
`RecursionDetected`, `ConfigurationError`, `InternalDispatcherError`.

Gate 4.5 added eleven more. All are in `ERROR_CODES` and serialise through
`to_payload()` unchanged.

| code | base | meaning |
|---|---|---|
| `SkillPolicyViolation` | `PolicyViolation` | an unapproved / rejected / non-projectable skill id, a skill whose `requires_deny_patterns` are not in the effective deny list, refused content (a declared mechanism, an unterminated frontmatter block), or the projected size cap exceeded |
| `ApprovedSkillChanged` | `DispatcherError` | a pinned `SKILL.md` or supporting file changed, vanished, moved, became a symlink, left its pinned plugin install, or the manifest was re-approved; also raised on resume when skill projection was switched off after dispatch (`details["reason"] == "skills_disabled_after_dispatch"`) |
| `ProjectGuidanceNotApproved` | `PolicyViolation` | manifest not approved, scope not approved, or no approved review projection for a selected scope. `details["operator_text"]` carries the canonical refusal text verbatim; there is deliberately **no** root-only fallback (RULINGS §7) |
| `ProjectGuidanceScopeError` | `PolicyViolation` | an `allowed_paths` entry outside the pinned toplevel, under a deny prefix / deny absolute tree, escaping after normalisation, or intersecting more subscopes than the policy permits |
| `ProjectGuidancePolicyViolation` | `PolicyViolation` | `details["reason"]` is `sensitive_content_in_source_derived_artifact` or `size_cap_exceeded` |
| `ProjectGuidanceRepositoryMismatch` | `DispatcherError` | one of the four identity fields (toplevel, git_dir, origin_url, root_commit) does not match the pin |
| `ProjectGuidanceSourceChanged` | `DispatcherError` | a pinned `CLAUDE.md`/`AGENTS.md` changed, moved, vanished or became a symlink |
| `ProjectGuidanceDrift` | `DispatcherError` | a pair approved as byte-identical aliases has diverged |
| `ProjectGuidanceProjectionChanged` | `DispatcherError` | a curated artifact under `config/guidance/` no longer matches its pinned hash |
| `ProjectGuidanceResumeDrift` | `DispatcherError` | every hash verifies but the manifest was re-approved with different content; also raised on resume when guidance projection was switched off after dispatch (`details["reason"] == "project_guidance_disabled_after_dispatch"`) |
| `UnapprovedProjectGuidanceFile` | `DispatcherError` | the DEFAULT-DENY verification scan found an instruction file that is neither approved nor excluded |
| `ContextTooLarge` | `DispatcherError` | the composed `--append-system-prompt` value exceeds the 122,880-byte transport ceiling (`details["source"] == "preflight"`), or the kernel refused the invocation with `E2BIG` anyway (`details["source"] == "kernel_e2big"`, `details["errno"] == 7`) |

**`ContextTooLarge` (BLOCKER B1).** `--append-system-prompt` is emitted inline
as ONE argv element, and Linux caps a single argv element at **131,071 bytes**
(`MAX_ARG_STRLEN`, measured by bisection on this host). The V1 ceiling is
**122,880 bytes (120 KiB) of UTF-8**, measured on the FINAL composed value —
never on characters, never on a sum of per-component caps. Measured shapes:
intended first task 79,406 B (fits, substantial headroom); largest that
launched live 128,992 B (nothing truncated); production worst case 142,006 B
(**refused** — an intentionally unsupported composition under V1 inline
transport); the ceiling this config file used to permit, 184,718 B (invalid,
now rejected at config load).

`details` carries bounded facts only: `actual_bytes`, `maximum_bytes`,
`excess_bytes`, `measured_argv_element_limit_bytes`, `model`, `role`,
`task_id`, `resumed`, `skill_ids` + `skill_count`, `guidance_scope_ids` +
`guidance_scope_count`, `source`, and on the kernel path `errno`, `errno_name`
and `total_argv_bytes`. It never quotes the payload, the projected guidance or
the skill text.

This is a **refusal**, not a degradation. The dispatcher does not drop a Skill,
does not drop a guidance scope, and does not truncate to squeeze underneath the
ceiling: the approved deterministic context is part of the task contract. The
selection is reported back so Sol can narrow the task or wait for a transport
upgrade. Do not "fix" this by making selection adaptive.

**Error ordering when a source is edited (Sol ruling, 2026-08-20).** Editing one
half of an approved alias pair is simultaneously an alias divergence and a hash
mismatch. The engine reports the **more precise** condition first:

```
alias pair diverged                 -> ProjectGuidanceDrift
otherwise, pinned source mismatched -> ProjectGuidanceSourceChanged
otherwise, curated artifact changed -> ProjectGuidanceProjectionChanged
otherwise, manifest re-approved     -> ProjectGuidanceResumeDrift
```

All four are fail-closed and all four return the task to Sol. Do not "fix" the
code to report the generic error first; the ordering above is the intended
behaviour and `tests/integration/test_gate45_context.py` pins it.

`ProvenanceSeparationError` is **not** a `DispatcherError` — it is a `ValueError`
raised only when the strict content classifier is pointed at
`DISPATCHER_AUTHORED` text, i.e. when the engine has been miswired across the
provenance boundary (RULINGS §2). Never catch it and convert it into a
dispatcher error, and never weaken the regex to silence it: fix the call site.

`GitEvidenceCollectionFailed` means an authoritative git command failed, timed
out, produced unusable output, or could not be run. Sol must read it as
*evidence unavailable — do not infer a clean tree*, never as "no changes".

`ERROR_CODES: frozenset[str]` must stay in sync — a test checks it. Add a new
error → add it to `ERROR_CODES`.

### `sol_claude_dispatcher.config`

```python
load_config(path, *, project_root=None) -> Config      # raises ConfigurationError
load_config_from_mapping(data, *, source_path=None, project_root=".") -> Config
```

`Config` sections: `.dispatcher`, `.models`, `.routing`, `.security`,
`.validation`, `.claude`, `.skills`, `.project_guidance`, `.logging`, plus
`.source_path`, `.project_root`.

Derived helpers you should use rather than re-deriving paths:

```python
config.state_path / tasks_path / locks_path / proposals_path   -> Path
config.worker_policy_file / fable_policy_file / empty_mcp_file -> Path
config.worker_schema_file / fable_schema_file                  -> Path
config.approved_skills_file / approved_guidance_file           -> Path
config.model_for("sonnet"|"opus"|"fable") -> str
config.clamp_timeout(requested: int) -> int
```

Key settings: `dispatcher.{state_dir, default_timeout_seconds,
max_timeout_seconds, default_max_turns, default_max_resume_count}`;
`models.{sonnet, opus, fable}`; `routing.default_model`;
`security.{max_dispatch_depth, allow_*, allowed_repository_roots}`;
`validation.run_dispatcher_validation`; `claude.{binary, permission_mode,
worker_tools, reviewer_tools, disallowed_tools, *_path}`;
`logging.{level, log_file}`.

Config already fails closed on: missing file, bad TOML, non-UTF-8, missing
section, unknown key, wrong type, `/` as a root, relative root, nonexistent
root, non-directory root, the `/CONFIGURE/ME` placeholder, `max_dispatch_depth
> 1`, `default_model = "fable"`, `permission_mode = "bypassPermissions"`.

---

## 2. Wave 2 — `router.py`

```python
def route(envelope: TaskEnvelope, config: Config) -> str
def explain_route(envelope: TaskEnvelope, config: Config) -> tuple[str, str]
```

Pure. No I/O. Deterministic. Rules **in this order**, first match wins:

| # | Condition | Result |
|---|---|---|
| 1 | `routing.requested_model is SONNET` | `config.models.sonnet` |
| 2 | `routing.requested_model is OPUS` | `config.models.opus` |
| 3 | `routing.risk in {HIGH, CRITICAL}` | `config.models.opus` |
| 4 | `routing.complexity is HIGH` | `config.models.opus` |
| 5 | `task.kind in ESCALATING_TASK_KINDS` | `config.models.opus` |
| 6 | otherwise | `config.models.sonnet` |

`explain_route` returns `(model, reason)` where reason is a short stable string
naming the rule, e.g. `"explicit_request:opus"`, `"risk:high"`,
`"complexity:high"`, `"kind:concurrency"`, `"default"`. Store it in
`TaskRecord.state_history` when transitioning to `ROUTED`.

`route` must never return `config.models.fable`. Rules 1 and 2 only fire on
enum members that exist, and `fable` is not one of them.

Required tests (§31): low risk → sonnet; medium/medium → sonnet; high
complexity → opus; high risk → opus; critical risk → opus; explicit sonnet
beats high risk; explicit opus with low risk → opus; each escalating kind →
opus; fable never returned for any input combination.

---

## 3. Wave 2 — `state.py`

```python
def atomic_write_text(path: Path, content: str, *, mode: int = 0o600) -> None
def atomic_write_json(path: Path, data: object, *, mode: int = 0o600) -> None
```

Temp file in the **same directory** → `write` → `flush` → `os.fsync` →
`os.replace`. Set the mode on the temp file *before* the replace so the final
file is never briefly world-readable. Best-effort `fsync` of the directory
afterwards. On any failure, remove the temp file and raise.

```python
class TaskStore:
    def __init__(self, root: Path) -> None
        # root == config.tasks_path. mkdir(parents=True, exist_ok=True), mode 0o700.

    def task_dir(self, task_id: str) -> Path            # root/<task_id>
    def run_dir(self, task_id: str, run_index: int) -> Path  # task_dir/runs/001

    def exists(self, task_id: str) -> bool
    def create(self, envelope: TaskEnvelope) -> TaskRecord
        # Creates the directory tree (0700), writes envelope.json,
        # writes state.json with state=CREATED, resume_count=0, run_count=0.
        # Raises InvalidTaskEnvelope if the task already exists.

    def load_envelope(self, task_id: str) -> TaskEnvelope   # TaskNotFound / StateCorruption
    def load(self, task_id: str) -> TaskRecord              # TaskNotFound / StateCorruption
    def save(self, record: TaskRecord) -> None              # sets updated_at, atomic

    def transition(self, task_id: str, target: TaskState, *,
                   reason: str | None = None, **updates) -> TaskRecord
        # 1. load current record
        # 2. is_transition_allowed(current.state, target)? else InvalidStateTransition
        #    with details {"from","to","allowed":[...]}
        # 3. apply **updates to the record's fields (selected_model, session_id,
        #    worktree_path, resume_count, ...); unknown field -> InvalidStateTransition
        # 4. append {"from","to","at","reason"} to state_history
        # 5. atomic save; return the new record

    def append_run(self, task_id: str, run: RunRecord) -> None
        # writes run_dir/dispatcher-result.json; increments run_count
    def load_runs(self, task_id: str) -> list[RunRecord]     # ordered by run_index
    def latest_run(self, task_id: str) -> RunRecord | None

    def append_review(self, task_id: str, review: FableReview) -> int
        # writes reviews/fable-NNN.json; returns the review number; bumps
        # fable_review_count
    def load_reviews(self, task_id: str) -> list[FableReview]

    def write_evidence(self, task_id: str, name: str, content: str) -> Path
        # evidence/<name>; name is validated (no "/", no "..")
    def read_evidence(self, task_id: str, name: str) -> str | None
```

On-disk layout is §27, exactly:

```
state/tasks/<task-id>/
  envelope.json  state.json  metadata.json
  runs/001/{worker-result.json,dispatcher-result.json,stdout.json,stdout.raw,
            stderr.log,validation.json,claim-verification.json}
  reviews/fable-001.json
  evidence/{diff.patch,diff-stat.txt,diff-check.txt,status.txt,
            changed-paths.json,
            pre-validation-changed-paths.json,pre-validation-status.txt,
            pre-validation-diff-stat.txt,evidence-phases.json,
            primary-tree-before.txt,primary-tree-after.txt,
            primary-tree-invariant.json,primary-tree-status.txt}
```

`stdout.json` is the *retained* stream (head+tail, in-band marker when
truncated); `stdout.raw` is every byte. The `pre-validation-*` files are
evidence phase A (the worktree as the worker left it), written before any
validation command runs; the unprefixed files are the final state on which the
scope decision is taken. `evidence-phases.json` attributes changed paths to the
worker or to the dispatcher's own validation. Files under `evidence/` are
latest-run-wins; per-run history lives in `runs/NNN/`.

`TaskStore` resolves every path it derives and refuses anything landing outside
`state/tasks/`, independently of whatever validation the caller performed
(P0-1). This includes task directories, run directories, review files and
evidence files that have since been replaced by a symlink.

Directories `0700`, files `0600`. Unparseable JSON, a missing
`schema_version`, or a `schema_version` mismatch → `StateCorruption`. Never
repair, never guess, never fall back to a default.

State must survive an MCP server restart: `TaskStore` holds no authoritative
in-memory state, and every read re-reads from disk.

Required tests: atomic write leaves no partial file when interrupted; 0600/0700
modes; every legal transition succeeds; a sample of illegal ones raise; reload
after restart; corrupt JSON → `StateCorruption`; unversioned state.json →
`StateCorruption`.

---

## 4. Wave 2 — `locks.py`

```python
def lock_identity_for(repository_root: Path) -> Path
    # the git top level, or the resolved path for a non-git directory

def lock_name_for(repository_root: Path) -> str
    # sha256(str(lock_identity_for(root)).encode()).hexdigest() + ".lock"

class RepositoryLock:
    def __init__(self, repository_root: Path, locks_dir: Path) -> None
    @property
    def lock_path(self) -> Path         # locks_dir / lock_name_for(root)
    def acquire(self, *, blocking: bool = False, timeout: float = 0.0) -> None
    def release(self) -> None
    def __enter__(self) -> "RepositoryLock"
    def __exit__(self, exc_type, exc, tb) -> None
```

`fcntl.flock(fd, LOCK_EX | LOCK_NB)`. Default **non-blocking**: a contended
repository raises `RepositoryBusy` immediately with
`details={"repository": str(root), "lock_path": str(lock_path)}` rather than
stalling until Codex's MCP tool timeout fires.

Lock identity derives from the **git top level**, so `/a/b`, `/a/b/`, a symlink
to `/a/b`, and `/a/b/src` all contend for the same lock. Deriving it from the
caller's spelling let one working tree hold two different locks, which is not
mutual exclusion at all (P0-2). `RepositoryLock` resolves identity once at
construction, so the lock file cannot move under a held lock. Write the
holder's pid and task id into the lock file for debuggability (truncate
first). Release is idempotent and must run in a `finally`. Lock files are never
deleted on release — unlinking races with another acquirer.

Fable review **does** take this lock (P0/P1-4), exclusively, for the whole
snapshot. See `docs/SECURITY.md` §1.6 for the operational consequence.

Required tests: two locks on the same repo — second raises `RepositoryBusy`;
different repos do not contend; path spellings/symlinks/subdirectories map to
one lock; release then re-acquire works; context manager releases on exception;
resume-while-review and review-while-worker are both refused.

---

## 5. Wave 2 — `git.py`

```python
@dataclass(frozen=True)
class DiffEvidence:
    base_commit: str
    changed_paths: list[str]
    diff_text: str
    diff_stat: str
    porcelain_status: str
    diff_check_passed: bool
    diff_check_output: str
    truncated: bool

@dataclass(frozen=True)
class ScopeCheck:
    valid: bool
    out_of_scope: list[str]
    forbidden: list[str]

def is_git_repository(path: Path) -> bool
def git_top_level(path: Path) -> Path              # raises InvalidRepository
def git_top_level_or_none(path: Path) -> Path | None
def resolve_base_commit(repo: Path, base_ref: str) -> str
def create_worktree_name(task_id: str) -> str
def worktree_path_for(repo: Path, worktree_name: str) -> Path | None
def collect_diff_evidence(worktree: Path, base_commit: str, *,
                          max_diff_bytes: int = 2_000_000) -> DiffEvidence
def write_full_diff(worktree: Path, base_commit: str, dest: Path) -> int
def check_scope(changed_paths: list[str], scope: ScopeSpec) -> ScopeCheck
def primary_tree_status(repo: Path) -> str         # raises, never returns ""
```

**Every authoritative command fails closed** with
`GitEvidenceCollectionFailed` on a non-permitted exit code, a timeout, an
`OSError`, or a missing `git` binary. Three failure signatures changed from
the original contract and callers must not treat the old benign defaults as
still reachable:

| Function | Was | Is |
|---|---|---|
| `worktree_path_for` | `None` if git failed **or** no worktree | `None` only when git answered and found nothing; raises if git could not be consulted |
| `primary_tree_status` | `""` (reads as "clean") if git failed | raises `GitEvidenceCollectionFailed` |
| `collect_diff_evidence` | silently degraded on any failed sub-command | raises `GitEvidenceCollectionFailed` |

`git_top_level` asks git itself (`rev-parse --show-toplevel`, argv, `cwd=path`,
never a shell) and canonicalises the answer; it is the source of repository
identity for `security.validate_repository_root` and `locks.lock_identity_for`.
`git_top_level_or_none` is the variant for callers with a legitimate non-git
fallback (the lock primitive only).

Every command in this module runs with `GIT_DIR`, `GIT_WORK_TREE`,
`GIT_COMMON_DIR`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`,
`GIT_ALTERNATE_OBJECT_DIRECTORIES`, `GIT_CEILING_DIRECTORIES` and
`GIT_NAMESPACE` stripped, plus `GIT_TERMINAL_PROMPT=0` and
`GIT_OPTIONAL_LOCKS=0` — an inherited environment must not be able to make
`--show-toplevel` answer about a different repository, and a read-only command
should neither prompt nor take the index lock.

`write_full_diff` streams the untruncated patch straight from git's stdout into
a `0600` file (temp file + `fsync` + `os.replace`; no partial file on failure)
and returns the byte count, so the dispatcher never materialises an unbounded
string to write `evidence/diff.patch`.

- `resolve_base_commit` → `git rev-parse --verify <base_ref>^{commit}`, returns
  the full 40-char SHA. Unknown ref → `InvalidRepository`.
- `create_worktree_name` → just `models.worktree_name_for(task_id)`. Never
  accepts user text. (§12)
- `worktree_path_for` → parse `git worktree list --porcelain` and match the
  final path component against `worktree_name`. Returns `None` when Claude did
  not create one; the caller raises `WorktreeCreationFailed`.
- `collect_diff_evidence` runs, in order:
  `git status --porcelain`, `git diff --name-only <base>`,
  `git diff --stat <base>`, `git diff <base>`, `git diff --check`.
  Include untracked files in `changed_paths`
  (`git ls-files --others --exclude-standard`) — a worker that adds an
  unauthorised new file must not slip past the scope check. Truncate
  `diff_text` at `max_diff_bytes`, set `truncated=True`, and record the
  untruncated size in `diff_total_bytes`; the full diff goes to
  `evidence/diff.patch` via `write_full_diff` (§7.3: store the diff in state
  rather than passing a huge argument on a command line). If the full patch
  cannot be written, the truncated text is stored **with** an explicit
  incompleteness marker naming both byte counts — never an unmarked short
  patch — and `changed-paths.json` records `diff_patch_complete: false`.
- `check_scope`: match with `fnmatch`-style globbing where `**` crosses
  directory separators and `*` does not. `forbidden_paths` wins over
  `allowed_paths`. **An empty `allowed_paths` means unrestricted**; a non-empty
  one means a path must match at least one pattern. `valid` is
  `not out_of_scope and not forbidden`.

Nothing in this module commits, merges, pushes, rebases, resets, cleans,
creates or removes worktrees, or applies changes to the primary tree. (§12)

Required tests: base commit resolution incl. bad ref; scope matching for
authorised, unauthorised, forbidden-wins, untracked-file, and empty-allowlist
cases; diff evidence against a real temp repo; truncation.

---

## 6. Wave 2 — `security.py`

```python
def validate_task_id(value: str) -> str
def validate_repository_root(raw_root: str, config: Config) -> Path
def assert_no_recursion(config: Config, env: Mapping[str, str] | None = None) -> None
def assert_dispatch_depth(depth: int, config: Config) -> None
def worker_environment(base_env: Mapping[str, str], *, task_id: str,
                       dispatch_depth: int) -> dict[str, str]
def redact(text: str) -> str

SECRET_ENV_MARKERS: tuple[str, ...]
WORKER_ENV_MARKER = "SOL_WORKER"
```

`validate_task_id` (P0-1) is the **single authoritative** task-id validator:
canonical lowercase hyphenated UUID only (regex plus a `uuid.UUID` round-trip
requiring byte-identical canonical rendering). It refuses non-strings,
over-long input, null bytes, `.`, `..`, `/`-ish and `\`-ish fragments, absolute
paths, whitespace-padded ids, arbitrary text, and non-canonical UUID spellings
(braced, URN, uppercase). It **deliberately does not normalise** — no
stripping, no case-folding, no unwrapping — because "normalise, then use as a
path component" is the defect pattern. Raises `InvalidTaskEnvelope`, which
`_guarded` already serialises. Call it at the top of `_resume`, `_review` and
`_get_task`, before the id reaches `TaskStore`, `sessions`, or anything that
derives a path. It is the *outer* boundary only: `TaskStore` independently
re-verifies containment, so neither layer depends on the other.

`validate_repository_root` (§24, P0-2), in order:

1. Reject empty, relative, or null-byte-bearing input → `InvalidRepository`.
2. `path = Path(raw_root).resolve()` (resolves symlinks and `..`).
3. Not exists / not a directory → `InvalidRepository`.
4. Ask git for the top level (`git_top_level(path)`); not inside a work tree,
   or git unusable → `InvalidRepository`.
5. `path != canonical_root` → `InvalidRepository`. A **subdirectory of an
   allowed repository is not an allowed repository**: accepting it would give
   one repository two identities (two lock names, two evidence roots).
6. `canonical_root` not **exactly equal** to one of the resolved
   `allowed_repository_roots` → `RepositoryNotAllowed`. Not a descendant of
   one, not a string prefix match — equal. `/srv/app-evil` must not pass for
   root `/srv/app`, and neither must `/srv/app/src`.
7. Return `canonical_root`. This value becomes `canonical_root` everywhere:
   lock identity, worktree lookup, evidence root, the worker's `cwd`. The
   caller's spelling is never reused after this point.

Because step 2 resolves before steps 5–6, a symlink inside an allowed root that
points outside it is rejected, and a symlink *to* an allowed repository
canonicalises to it and is accepted. Test both explicitly.

`assert_no_recursion` (§22 layer 4): if `env.get("SOL_WORKER") == "1"` raise
`RecursionDetected`, unless `env.get("SOL_DISPATCHER_TEST_OVERRIDE") == "1"`.
Defaults to `os.environ` when `env` is `None`. Call it at server startup **and**
at the top of every dispatch/resume tool.

`assert_dispatch_depth` (§22 layer 5): `depth > config.security.max_dispatch_depth`
→ `RecursionDetected` with `details={"depth", "max"}`.

`worker_environment` (§22 layers 4 and 7):

- start from `base_env`;
- **drop** every key whose name matches a `SECRET_ENV_MARKERS` substring
  (case-insensitive) and every `SOL_DISPATCHER_*` key;
- **set** `SOL_WORKER=1`, `SOL_DISPATCH_DEPTH=str(dispatch_depth + 1)`,
  `SOL_TASK_ID=task_id`;
- keep `PATH`, `HOME`, `LANG`, `TERM`, `USER`, `SHELL`, `TMPDIR`.

Anthropic credentials: do **not** synthesise or forward them. The Claude CLI
handles its own auth; the dispatcher never reads, logs, or copies a token.

`redact(text)` masks `KEY=value` / `"key": "value"` pairs whose key matches
`SECRET_ENV_MARKERS`, replacing the value with `***REDACTED***`. Apply it to
anything before it reaches a log or `argv_redacted`. Its cost is **linear** in
`len(text)` and must stay that way: callers stream whole worker stderr through
it, and the original unanchored `KEY=value` pattern backtracked quadratically
over a long `=`-free token — enough to outlive a worker's own timeout on a few
megabytes of output.

`validation.validation_environment()` (in `validation.py`, sharing
`SECRET_ENV_MARKERS` with this module) applies the same stripping policy to the
dispatcher's own validation subprocesses, and additionally drops the worker
markers. `env=None` in `run_validation_command` / `run_validations` **means**
"build a sanitized environment" — never "inherit". Do not pass `os.environ`
explicitly at a call site; that reintroduces P1-6.

Required tests (§31): valid repo; outside allowlist; symlink escape; symlink
*to* an allowed repo; subdirectory of an allowed repo refused; parent in the
allowlist does not authorise the repo; prefix lookalike refused; nonexistent;
non-git; `..` traversal; a hostile-task-id matrix against `validate_task_id`
and against `TaskStore` directly; `SOL_WORKER=1` rejection + override;
depth > max; worker env sets the three markers and strips secrets; validation
env strips secrets and does *not* set the worker markers; redaction semantics
plus a bounded-time assertion on a multi-megabyte input.

---

## 7. Wave 3 — `runner.py`

```python
CLI_CAPABILITIES: dict[str, bool]

@dataclass(frozen=True)
class WorkerInvocation:
    binary: str; model: str; session_id: str; cwd: Path; prompt: str
    timeout_seconds: int; role: str
    worktree_name: str | None = None
    resume_session_id: str | None = None
    json_schema: str | None = None
    append_system_prompt: str | None = None
    tools: list[str] = []
    disallowed_tools: list[str] = []
    mcp_config_path: Path | None = None
    permission_mode: str = "auto"
    max_budget_usd: float | None = None
    env: dict[str, str] = {}
    grace_seconds: float = 5.0
    stdout_spool_path: Path | None = None   # set by the server to run_dir/stdout.raw
    stderr_spool_path: Path | None = None   # set by the server to run_dir/stderr.log

@dataclass
class WorkerRun:
    argv: list[str]; exit_code: int | None; stdout: str; stderr: str
    duration_ms: int; timed_out: bool = False
    killed_with_sigkill: bool = False; start_failed: bool = False
    stdout_total_bytes: int = 0; stderr_total_bytes: int = 0
    stdout_truncated: bool = False; stderr_truncated: bool = False
    structured_stdout: str | None = None
    @property
    def stdout_for_parsing(self) -> str     # PARSE THIS, not .stdout

CORE_DENIED_GIT_OPERATIONS: tuple[str, ...]   # push/merge/rebase/commit/
                                              # reset/clean/worktree/bisect
ALWAYS_DISALLOWED_TOOLS: tuple[str, ...]      # mcp__*, Agent, Task,
                                              # Bash(claude:*), Bash(codex:*),
                                              # Bash(gh:*)
                                              # + CORE_DENIED_GIT_OPERATIONS

def build_argv(spec: WorkerInvocation) -> list[str]
async def run_worker(spec: WorkerInvocation) -> WorkerRun
```

Output retention (P1-8): `run_worker` keeps the first **and** last
`MAX_CAPTURED_BYTES` of each stream. A stream up to `2 × cap` is reconstructed
exactly; beyond that, `stdout`/`stderr` carry `head + "[dispatcher] N bytes
omitted … This excerpt is NOT the complete stream." + tail`, and the flags and
byte counters say so. When a spool path is supplied every byte is written to
that `0600` file (stderr redacted line-by-line on the way); an unopenable spool
raises `InternalDispatcherError` *before* the worker is launched. When stdout
was truncated, the trailing structured document is recovered by a real
`json.loads` over bounded trailing-line candidates — **never** a regex scrape —
and exposed as `structured_stdout` / `stdout_for_parsing`. Call sites must
parse `stdout_for_parsing`; it *is* `stdout` for any run inside the cap.

Captures are owned by `run_worker`, not by the pump tasks, so a cancelled or
timed-out drain keeps every byte already read instead of substituting `b""`.

`ALWAYS_DISALLOWED_TOOLS` is appended by both invocation builders regardless of
config, and `_assert_invocation_sane()` refuses to build argv for an invocation
missing any member. Operator config may **add** deny rules; it can never remove
one of these. See `docs/SECURITY.md` for what a deny pattern is and is not.

### `build_argv` — pure, so tests can assert on it exactly

Emit in this order:

```
<binary>
-p
--model <model>
--output-format json
--permission-mode <permission_mode>
--safe-mode                             always, while CLI_CAPABILITIES["safe_mode"]
--strict-mcp-config
--mcp-config <mcp_config_path>          if set
--disallowedTools <t1> <t2> ...         if any
--tools <t1> <t2> ...                   if any
--json-schema <minified schema>         if set
--append-system-prompt <policy text>    if set
--max-budget-usd <amount>               if set
--session-id <session_id>               NEW sessions only
--resume <resume_session_id>            RESUME only
--worktree <worktree_name>              NEW implementation sessions only
<prompt>                                always last, exactly one positional
```

Rules:

- `--session-id` and `--resume` are **mutually exclusive**. New session uses
  `--session-id`; resume uses `--resume` and nothing else identifying.
- `--worktree` appears **only** on the first implementation run. Never on
  resume (§18: do not create another worktree), never on review.
- **Do not emit `--max-turns`.** It does not exist on Claude Code 2.1.234
  (verified — see `docs/DISCOVERY.md`). Gate it on
  `CLI_CAPABILITIES["max_turns"]` so it can be turned on later without editing
  call sites.
- `--append-system-prompt` takes the **policy text**, not a path. By default
  `build_worker_invocation` / `build_fable_invocation` read
  `config.worker_policy_file` / `config.fable_policy_file` themselves
  (`runner.worker_policy_text()` / `runner.fable_policy_text()` expose the same
  read). Both builders also accept `append_system_prompt=<str>`, which the
  Gate 4.5 §14 composer uses to supply the whole composed context — the policy
  file is then one labelled section inside it (see §11a). Passing `None` keeps
  the pre-Gate-4.5 behaviour byte for byte.
- `--json-schema` takes the **minified schema string**
  (`json.dumps(schema, separators=(",", ":"))`), not a path. It is produced by
  `runner.schema_for_claude_cli()`, which drops **only** the canonical schema's
  top-level `"$schema"` dialect declaration: Claude Code 2.1.237 rejects
  `https://json-schema.org/draft/2020-12/schema` with *"no schema with key or
  ref"*. The files in `schemas/` stay draft 2020-12; nothing else is stripped,
  no nested `$schema` is touched, and the projection is removed once the CLI
  accepts the declaration.
- Never `--dangerously-skip-permissions`, never `--allow-dangerously-skip-permissions`.

### `run_worker` — process control

```python
proc = await asyncio.create_subprocess_exec(
    *argv, cwd=str(spec.cwd),
    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    stdin=asyncio.subprocess.DEVNULL,
    env=spec.env, start_new_session=True,
)
```

- `start_new_session=True` gives the child its own process group so the whole
  tree can be signalled.
- `await asyncio.wait_for(proc.communicate(), timeout=spec.timeout_seconds)`.
- On `TimeoutError`: `os.killpg(os.getpgid(proc.pid), SIGTERM)` → wait up to
  `grace_seconds` → if still alive `os.killpg(..., SIGKILL)` and set
  `killed_with_sigkill=True`. Then **still collect whatever stdout/stderr
  arrived** and return `WorkerRun(timed_out=True)`. Evidence must survive
  (§20). Swallow `ProcessLookupError` at every kill step.
- `FileNotFoundError` on spawn → raise `ClaudeBinaryNotFound`.
  `PermissionError` → `ClaudeBinaryNotFound`. Other `OSError` → `WorkerRun` with
  `start_failed=True`.
- **`run_worker` does not raise on a non-zero exit code.** It reports. The
  caller decides whether that is `FAILED`.
- Decode with `errors="replace"`. Cap retained stdout/stderr (~1 MB each), and
  write the full streams to the run directory.

Required tests, all against `tests/fake_bin/claude` (§32): success; non-zero
exit; sleeping worker hits the timeout and gets SIGTERM; a SIGTERM-ignoring
worker gets SIGKILL; partial output preserved on timeout; missing binary →
`ClaudeBinaryNotFound`; argv assertions for new/resume/review shapes; assert no
`--max-turns` and no `--dangerously-skip-permissions` ever appear.

---

## 8. Wave 3 — `results.py`

```python
def extract_structured_payload(stdout: str) -> dict[str, Any]
def parse_worker_result(stdout: str) -> WorkerResult
def parse_fable_review(stdout: str) -> FableReview
```

`--output-format json` wraps output in an envelope. Resolution order:

1. `json.loads(stdout)` — on failure raise `ClaudeStructuredOutputInvalid`
   with `details={"reason": "not_json", "stdout_head": stdout[:2000]}`.
2. If the object has a `structured_output` key holding an object, use it.
3. Else if it has `result` holding an object, use it.
4. Else if it has `result` holding a **string**, try `json.loads` on that
   string; if that yields an object, use it.
5. Else if the top-level object already looks like the target (has `status` and
   `summary` for a worker result; `verdict` for a review), use it directly.
6. Else raise `ClaudeStructuredOutputInvalid` with
   `details={"reason": "no_structured_payload", "top_level_keys": [...]}`.

Then `Model.model_validate(payload)`; a `ValidationError` becomes
`ClaudeStructuredOutputInvalid` with `details={"reason": "schema_mismatch",
"issues": [{"location","problem"}, ...]}` — compact, not the raw pydantic dump.

**No regex prose scraping, ever** (§15). If it will not parse, that is a
result: the run is recorded with `worker_result_parsed=False` and a populated
`worker_result_error`, and Sol is told.

Required tests: valid; invalid JSON; valid JSON wrong schema; missing required
field; extra field; `result`-as-string double-encoded; empty stdout; non-object
top level.

---

## 9. Wave 3 — `sessions.py`

```python
@dataclass(frozen=True)
class ResumePlan:
    task_id: str; session_id: str; model: str; worktree_path: str
    instruction: str; timeout_seconds: int; next_resume_count: int

def new_session(envelope: TaskEnvelope) -> str
def assert_resume_allowed(envelope: TaskEnvelope, record: TaskRecord) -> None
def resume_plan(envelope: TaskEnvelope, record: TaskRecord, instruction: str, *,
                timeout_seconds: int | None = None) -> ResumePlan
```

`assert_resume_allowed`: if `record.resume_count >= envelope.execution.max_resume_count`
raise `ResumeLimitReached` with `details={"resume_count", "max_resume_count"}`.
The MCP layer turns that into
`{"status": "requires_orchestrator_decision", "reason": "resume_limit_reached"}`
(§7.2) — note that is a *successful* tool response describing a refusal, not an
MCP protocol error.

`resume_plan` reads **only** from stored state:

- `session_id` from `record.session_id` — never from the caller (§7.2);
- `model` from `record.selected_model` — never re-routed (§18);
- `worktree_path` from `record.worktree_path` — no new worktree (§18);
- scope, constraints, acceptance criteria from the stored envelope;
- `timeout_seconds` from the caller if given, clamped by
  `config.clamp_timeout`, else `envelope.execution.timeout_seconds`.

The only thing the caller contributes is `instruction`.

Missing `session_id`, `selected_model` or `worktree_path` → `StateCorruption`.

Required tests (§31): same session id; same model; same worktree; resume_count
increments once per resume; cap enforced at the boundary (n-1 ok, n refused); a
caller-supplied session id is ignored; escalation creates a *new* task rather
than mutating the model.

---

## 10. Wave 3 — `validation.py`

```python
async def run_validation_command(cmd: ValidationCommand, cwd: Path, *,
                                 env: dict[str, str] | None = None) -> ValidationResult
async def run_validations(envelope: TaskEnvelope, cwd: Path,
                          config: Config) -> list[ValidationResult]
```

`create_subprocess_exec(*cmd.argv, cwd=cwd, start_new_session=True)`, same
timeout/SIGTERM/SIGKILL discipline as `run_worker`. `passed = exit_code == 0 and
not timed_out`. Keep the last ~8 KB of each stream in `stdout_tail` /
`stderr_tail`.

`run_validations` returns `[]` when
`config.validation.run_dispatcher_validation is False`. It runs commands from
`envelope.validation.commands` **only** — never from a worker result (§17).
Commands run to completion even if an earlier one fails; the caller decides
what a failure means.

Required tests: passing command; failing command; timing out command; disabled
by config; the list comes from the envelope even when a worker result contains
different commands.

---

## 11. Wave 4 — `server.py`

```python
SERVER_INSTRUCTIONS: str            # already written; §6 text
def build_server(config_path: str | None = None) -> MCPServer
def main() -> None
```

SDK is **mcp 2.0.0** (see `docs/DISCOVERY.md`):

```python
from mcp.server import MCPServer     # NOT mcp.server.fastmcp — it does not exist
server = MCPServer(name="sol-claude-dispatcher",
                   instructions=SERVER_INSTRUCTIONS, version=__version__)

@server.tool(name="dispatch_claude_task", description="...")
async def dispatch_claude_task(...) -> dict: ...

server.run(transport="stdio")        # or: await server.run_stdio_async()
```

`main()` must, in order: call `security.assert_no_recursion(config)`; load
config (path from `SOL_DISPATCHER_CONFIG` env var or the default
`config/dispatcher.toml`); configure logging to **stderr or a file, never
stdout**; build the server; run stdio.

### Exactly four tools

**`dispatch_claude_task`** — input is a `TaskRequest` (§7.1). Flow:
`assert_no_recursion` → validate `TaskRequest` → `validate_repository_root` →
`assert_dispatch_depth` → `RepositoryLock.acquire()` → `resolve_base_commit` →
`TaskEnvelope.from_request` → `store.create` → `route` → transition `ROUTED`
(record model + reason) → `new_session` → transition `RUNNING` →
`run_worker` → locate worktree → `collect_diff_evidence` → `check_scope` →
`parse_worker_result` → `run_validations` → build `DispatcherObservations` →
`store.append_run` → transition to `IMPLEMENTED` / `POLICY_VIOLATION` /
`TIMED_OUT` / `BLOCKED` / `FAILED` → on `IMPLEMENTED`, transition to
`AWAITING_SOL_REVIEW` → release the lock in a `finally`.

Returns:

```json
{"task_id","run_id","selected_model","session_id","worktree","status",
 "worker_claims":{...}|null,"dispatcher_observations":{...},
 "validation_results":[...],"scope":{"valid":bool,"out_of_scope":[],"forbidden":[]}}
```

**`resume_claude_task`** — input `{task_id, instruction, timeout_seconds?}`
(§7.2). `assert_resume_allowed` → transition `RESUME_REQUESTED` → `resume_plan`
→ `RUNNING` → run with `--resume`, same model, same worktree, no new worktree →
same evidence pipeline → increment `resume_count`. On the cap, return
`{"status": "requires_orchestrator_decision", "reason": "resume_limit_reached"}`.

**`review_task_with_fable`** — input `{task_id, focus: [...]}` (§7.3). Fresh
session id, `config.models.fable`, `reviewer_tools` only (Read/Glob/Grep), no
`--worktree`, no `--resume`, cwd = the task's worktree, prompt assembled from
objective + acceptance criteria + base commit + changed paths + the stored
diff + worker report + dispatcher validation + focus. Read the diff from
`evidence/diff.patch` rather than passing it as a huge argv element. Never
resumes the worker's conversation. Transition to `FABLE_REVIEWED`.

**`get_task`** — input `{task_id}` (§7.4). **Read-only**: no transition, no
subprocess, no lock. Returns envelope, status, model, worktree, session id,
resume count, run history, validation history, latest worker result, latest
Fable review, policy violations, timeout info.

Every tool wraps its body in `except DispatcherError as e: return e.to_payload()`
and `except Exception: log traceback to stderr; return
InternalDispatcherError(...).to_payload()`.

---

## 11a. Gate 4.5 — `skills.py`, `project_guidance.py`, `worker_context.py`

Three modules, one direction of dependency: `worker_context` imports the other
two; neither of them imports the other or the server. Both engines are
**manifest-driven and never discover anything on disk**; both are inert until
their feature flag is turned on, and both flags default to `false`.

### `sol_claude_dispatcher.skills`

Approved-skill projection: hash-pinned inert text, never a skill runtime.
`"Skill"` never enters `worker_tools`/`reviewer_tools`, no `--skill`-style flag
is ever emitted, and no plugin is enabled.

```python
load_manifest(path) -> SkillManifest
load_manifest_from_mapping(data, *, source_path=None) -> SkillManifest

class SkillProjectionEngine:
    @classmethod
    def from_config(cls, config, *, denied_tools=None) -> SkillProjectionEngine
    def select(self, *, task_kind, complexity, risk, run_kind,
               role=WorkerRole.IMPLEMENTER) -> tuple[str, ...]
    def project_for(self, *, task_kind, complexity, risk, run_kind,
                    role=WorkerRole.IMPLEMENTER) -> SkillProjection
    def project(self, skill_ids) -> SkillProjection
    def fingerprint(self, skill_ids) -> str
    def verify(self, record: SkillPolicyRecord) -> SkillProjection   # raises ApprovedSkillChanged
    def audit(self) -> tuple[SkillAuditRow, ...]                     # read-only, never raises
```

`denied_tools` **must** be the effective deny list the worker is actually
invoked with — `[*config.claude.disallowed_tools, *runner.ALWAYS_DISALLOWED_TOOLS]`.
Two approved skills declare `requires_deny_patterns` and the engine refuses to
project them when the pattern is absent, so passing only the configured half
silently drops reviewed guidance.

`SkillProjection` carries `.skill_ids`, `.skills` (each with `.id`, `.tier`,
`.activation` and `.text`), `.text`, `.projected_bytes`, `.approx_tokens`,
`.fingerprint`, and `.to_record() -> SkillPolicyRecord`. `.text` is `""` for the
reviewer and while the flag is off; an empty projection is not an error.
`.text` carries per-skill BEGIN/END delimiters and **no policy framing** — the
envelope-precedence preamble is dispatcher-authored and lives in
`worker_context` (RULINGS §2).

`select()` reads exactly `task.kind`, `routing.complexity`, `routing.risk`,
`RunKind` and `WorkerRole`. `RunKind.RESUME` legitimately adds
`superpowers.receiving-code-review`; **that is selection, not drift**, and
`verify()` deliberately checks the recorded id set instead.

### `sol_claude_dispatcher.project_guidance`

Curated project-guidance projection: hash-pinned, scope-aware,
manifest-driven, never a `CLAUDE.md` loader. Discovery is forbidden
(RULINGS §3); resolution is exact-path only.

```python
load_manifest(path) -> GuidanceManifest

@dataclass(frozen=True)
class RepositoryIdentity:
    toplevel: str; git_dir: str; origin_url: str; root_commit: str

class GuidanceAudience(str, Enum): WORKER = "worker"; FABLE_REVIEW = "fable_review"

class ProjectGuidanceEngine:
    @classmethod
    def from_config(cls, config) -> ProjectGuidanceEngine
    def relativise(self, allowed_paths, *, repository) -> tuple[str, ...]
    def select(self, allowed_paths, *, repository, audience=WORKER) -> GuidanceSelection
    def project(self, allowed_paths, *, repository, task_envelope_id,
                audience=WORKER) -> ProjectGuidanceProjection
    def verify(self, record: ProjectGuidanceRecord, *, repository) -> ProjectGuidanceProjection
    def audit(self) -> tuple[GuidanceAuditRow, ...]        # read-only, never raises
    def discover_unapproved(self) -> tuple[str, ...]       # verification only
    def assert_no_unapproved_files(self) -> None           # raises UnapprovedProjectGuidanceFile
```

Collect `RepositoryIdentity` with `git.collect_repository_identity(root)`
against the **canonical primary repository** named by
`envelope.repository.root`, never the dispatcher-created worktree: inside a
linked worktree `--show-toplevel` and `--absolute-git-dir` both answer about the
worktree and would fail the pin for no good reason (RULINGS §4).

`ProjectGuidanceProjection` carries `.logical_ids`, `.scopes` (root first, then
selected subscopes in manifest declaration order), `.artifacts`, `.text`,
`.graph_variant`, `.fingerprint`, `.to_record() -> ProjectGuidanceRecord`, and
the two **disjoint** provenance sets `.scanned_artifacts` (SOURCE_DERIVED) /
`.exempt_artifacts` (DISPATCHER_AUTHORED). Fable gets a *different* projection
with disjoint files and hashes and no graph-refresh clause.

`discover_unapproved()` never selects a guidance source — it exists so a new
`CLAUDE.md` defaults to DENY/UNREVIEWED and is reported. The dispatcher calls
`assert_no_unapproved_files()` at dispatch admission, not inside `project()`.

### `sol_claude_dispatcher.worker_context`

The only place the two projections meet the dispatcher's own policy text, and
the only place the combined §16 fingerprint is computed.

```python
SECTION_ORDER: tuple[str, ...]          # the ADDENDUM §14 order, literally
ENVELOPE_PRECEDENCE_PREAMBLE: str       # DISPATCHER_AUTHORED; never content-scanned
CONTEXT_FINGERPRINT_VERSION = "worker-context-fingerprint/v1"

class Provenance(str, Enum):
    DISPATCHER_AUTHORED; SOURCE_DERIVED; PRE_CLASSIFIED

@dataclass(frozen=True)
class ContextBlock: section; provenance; channel: "system"|"prompt"; text

@dataclass(frozen=True)
class WorkerContext:
    role; task_envelope_id; blocks; fingerprint
    skill_projection; guidance_projection
    .append_system_prompt -> str      # the "system"-channel blocks, in order
    .prompt -> str                    # the "prompt"-channel block
    .skill_record / .guidance_record  # what the dispatch anchor persists

def compose_worker_context(*, role, task_envelope_id, policy_text, task_prompt,
                           skill_projection=None, guidance_projection=None,
                           core_skill_ids=()) -> WorkerContext
def context_fingerprint(*, role, task_envelope_id,
                        skill_projection, guidance_projection) -> str

class WorkerContextComposer:            # held by Dispatcher as `.context`
    def __init__(self, config)
    skill_engine / guidance_engine -> engine | None      # None while the flag is off
    def repository_identity(self, canonical_root) -> RepositoryIdentity | None
    def assert_repository_reviewed(self) -> None
    def for_worker(self, envelope, *, run_kind, policy_text, task_prompt, identity)
    def for_review(self, envelope, *, policy_text, task_prompt, identity)
    def verify_dispatch_anchor(self, record: TaskRecord, *, identity) -> None
```

`SECTION_ORDER` is the ADDENDUM §14 order and emitted sections are always a
subsequence of it:

```
DISPATCHER_SYSTEM_POLICY                 system channel  (worker/fable policy file)
TASK_ENVELOPE                            prompt channel  (trailing positional)
ENVELOPE_PRECEDENCE_PREAMBLE             system channel  (only when something is projected)
CORE_APPROVED_SKILLS                     system channel
CONTEXTUAL_SKILLS                        system channel
CURATED_ROOT_GUIDANCE                    system channel
CURATED_IN_SCOPE_SUBPROJECT_GUIDANCE     system channel
GRAPH_REFRESH_CLAUSE                     system channel
```

Rules that must not move:

- The preamble is emitted **immediately before the first projected block**, and
  not at all when nothing is projected.
- No block ever mixes provenance domains. Classification has already happened
  inside both engines; a post-hoc scanner, if one is ever added, must be pointed
  at `WorkerContext.blocks`, never at `append_system_prompt` (RULINGS §2).
- With both flags off, `append_system_prompt` is the worker policy file's text
  byte for byte, and no manifest is read.

### Persistence (§15, §16)

| field | written | meaning |
|---|---|---|
| `TaskRecord.skill_policy` | once, at dispatch | the approved-skill policy the task was dispatched under |
| `TaskRecord.project_guidance` | once, at dispatch | the curated guidance context the task was dispatched under |
| `TaskRecord.context_fingerprint` | once, at dispatch | the **combined** fingerprint; the dispatch anchor |
| `RunMetadata.skill_policy_fingerprint` | every run | per-run skill profile |
| `RunMetadata.project_guidance_fingerprint` | every run | per-run guidance context |
| `RunMetadata.context_fingerprint` | every run | per-run combined value |

The anchor is **never** overwritten. A resume legitimately projects a different
skill profile, so refreshing the anchor would erase the value drift is measured
against. Resume calls `verify_dispatch_anchor()` **before** projecting anything;
every drift error propagates.

---

## 12. Cross-wave conventions

- **Time**: `models.utc_now()`. Serialise via pydantic; never `datetime.now()`.
- **IDs**: only the `models` helpers. Never build an id inline.
- **Paths**: `pathlib.Path` internally; `str` at the JSON boundary.
- **Truncation**: any field that can grow unbounded gets a documented cap, and
  the full artefact goes to the run/evidence directory.
- **Tests**: `tests/unit/test_<module>.py`, `tests/integration/test_<flow>.py`.
  Fixtures live in `tests/conftest.py`. `git_repo`, `valid_request_dict`,
  `config_text` and `config_file` already exist — reuse them.
- **Never** run real `claude` or `codex` from a test. `tests/fake_bin/claude`
  is the only worker binary any test may invoke.
