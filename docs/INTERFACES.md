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
FAILED              -> AWAITING_SOL_REVIEW
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
    allow_network / allow_push / allow_merge / allow_commit / allow_subagents: bool = False
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

RunMetadata:
    run_id: str; run_index: int (>=1); task_id: str
    kind: RunKind; role: WorkerRole; model: str; session_id: str
    worktree_path: str | None
    started_at: datetime; finished_at: datetime | None; duration_ms: int | None
    exit_code: int | None; timed_out: bool; killed_with_sigkill: bool
    argv_redacted: list[str]; stdout_bytes: int; stderr_bytes: int

DispatcherObservations:
    task_id, run_id, session_id, model, base_commit: str
    duration_ms: int; exit_code: int | None; timed_out: bool
    changed_paths: list[str]; diff_stat: str; diff_bytes: int
    scope_valid: bool; out_of_scope_paths: list[str]; forbidden_paths_touched: list[str]
    diff_check_passed: bool
    worker_result_parsed: bool; worker_result_error: str | None
    primary_worktree_clean: bool | None

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
`PolicyViolation`, `ValidationFailed`, `RecursionDetected`,
`ConfigurationError`, `InternalDispatcherError`.

`ERROR_CODES: frozenset[str]` must stay in sync — a test checks it. Add a new
error → add it to `ERROR_CODES`.

### `sol_claude_dispatcher.config`

```python
load_config(path, *, project_root=None) -> Config      # raises ConfigurationError
load_config_from_mapping(data, *, source_path=None, project_root=".") -> Config
```

`Config` sections: `.dispatcher`, `.models`, `.routing`, `.security`,
`.validation`, `.claude`, `.logging`, plus `.source_path`, `.project_root`.

Derived helpers you should use rather than re-deriving paths:

```python
config.state_path / tasks_path / locks_path / proposals_path   -> Path
config.worker_policy_file / fable_policy_file / empty_mcp_file -> Path
config.worker_schema_file / fable_schema_file                  -> Path
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
  runs/001/{worker-result.json,dispatcher-result.json,stdout.json,stderr.log,validation.json}
  reviews/fable-001.json
  evidence/{diff.patch,diff-stat.txt,changed-paths.json}
```

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
def lock_name_for(repository_root: Path) -> str
    # sha256(str(repository_root.resolve()).encode()).hexdigest() + ".lock"

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

Lock identity derives from the **canonical** path, so `/a/b`, `/a/b/`, and a
symlink to `/a/b` all contend for the same lock. Write the holder's pid and
task id into the lock file for debuggability (truncate first). Release is
idempotent and must run in a `finally`. Lock files are never deleted on release
— unlinking races with another acquirer.

Fable review does **not** take this lock (read-only, §25).

Required tests: two locks on the same repo — second raises `RepositoryBusy`;
different repos do not contend; path spellings/symlinks map to one lock;
release then re-acquire works; context manager releases on exception.

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
def resolve_base_commit(repo: Path, base_ref: str) -> str
def create_worktree_name(task_id: str) -> str
def worktree_path_for(repo: Path, worktree_name: str) -> Path | None
def collect_diff_evidence(worktree: Path, base_commit: str, *,
                          max_diff_bytes: int = 2_000_000) -> DiffEvidence
def check_scope(changed_paths: list[str], scope: ScopeSpec) -> ScopeCheck
def primary_tree_status(repo: Path) -> str
```

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
  `diff_text` at `max_diff_bytes` and set `truncated=True`; the full diff still
  goes to `evidence/diff.patch` (§7.3: store the diff in state rather than
  passing a huge argument on a command line).
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
def validate_repository_root(raw_root: str, config: Config) -> Path
def assert_no_recursion(config: Config, env: Mapping[str, str] | None = None) -> None
def assert_dispatch_depth(depth: int, config: Config) -> None
def worker_environment(base_env: Mapping[str, str], *, task_id: str,
                       dispatch_depth: int) -> dict[str, str]
def redact(text: str) -> str

SECRET_ENV_MARKERS: tuple[str, ...]
WORKER_ENV_MARKER = "SOL_WORKER"
```

`validate_repository_root` (§24), in order:

1. Reject empty, relative, or null-byte-bearing input → `InvalidRepository`.
2. `path = Path(raw_root).resolve()` (resolves symlinks and `..`).
3. Not exists / not a directory → `InvalidRepository`.
4. Not inside **any** configured root → `RepositoryNotAllowed`. Compare with
   resolved-ancestry (`path == root or root in path.parents`), **never** string
   `startswith` — `/srv/app-evil` must not pass for root `/srv/app`.
5. Not a git repository → `InvalidRepository` (worktree mode is the only mode).
6. Return the resolved `Path`. This value becomes `canonical_root`.

Because step 2 resolves before step 4, a symlink inside an allowed root that
points outside it is rejected. Test that explicitly.

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
anything before it reaches a log or `argv_redacted`.

Required tests (§31): valid repo; outside allowlist; symlink escape;
nonexistent; non-git; `..` traversal; `SOL_WORKER=1` rejection + override;
depth > max; worker env sets the three markers and strips secrets.

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

@dataclass
class WorkerRun:
    argv: list[str]; exit_code: int | None; stdout: str; stderr: str
    duration_ms: int; timed_out: bool = False
    killed_with_sigkill: bool = False; start_failed: bool = False

def build_argv(spec: WorkerInvocation) -> list[str]
async def run_worker(spec: WorkerInvocation) -> WorkerRun
```

### `build_argv` — pure, so tests can assert on it exactly

Emit in this order:

```
<binary>
-p
--model <model>
--output-format json
--permission-mode <permission_mode>
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
- `--append-system-prompt` takes the **policy text**, not a path. The caller
  reads `config.worker_policy_file` and passes the contents.
- `--json-schema` takes the **minified schema string**
  (`json.dumps(schema, separators=(",", ":"))`), not a path.
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
