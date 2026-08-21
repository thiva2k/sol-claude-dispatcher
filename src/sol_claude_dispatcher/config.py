"""Configuration loading (brief §35, §10, §24).

One rule: **fail closed**. A missing section, an unknown key, a placeholder
that was never filled in, a repository root that does not exist — all of these
raise :class:`~sol_claude_dispatcher.errors.ConfigurationError` rather than
falling back to something permissive. An unconfigured dispatcher must refuse to
dispatch, not quietly accept every path on the filesystem.

Model identifiers live here and nowhere else (§10: "Do not spread model IDs
throughout source files"). Code refers to ``config.models.sonnet``, never to a
literal model string.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .errors import ConfigurationError

__all__ = [
    "DispatcherSettings",
    "ModelSettings",
    "RoutingSettings",
    "SecuritySettings",
    "ValidationSettings",
    "ClaudeSettings",
    "SkillsSettings",
    "LoggingSettings",
    "Config",
    "MEASURED_SINGLE_ARGV_LIMIT_BYTES",
    "MAX_APPEND_SYSTEM_PROMPT_BYTES",
    "DISPATCHER_AUTHORED_RESERVE_BYTES",
    "MAX_PROJECTED_CONTEXT_BYTES",
    "MAX_PROJECTED_BYTES_CEILING",
    "MAX_GUIDANCE_BYTES_CEILING",
    "ProjectGuidanceSettings",
    "load_config",
    "load_config_from_mapping",
    "DEFAULT_CONFIG_FILENAME",
    "PLACEHOLDER_ROOT",
]

DEFAULT_CONFIG_FILENAME = "dispatcher.toml"

#: The value shipped in ``config/dispatcher.example.toml``. Loading a config
#: that still contains it is an error: it means nobody chose an allowlist.
PLACEHOLDER_ROOT = "/CONFIGURE/ME"


class _StrictSection(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class DispatcherSettings(_StrictSection):
    state_dir: str = "./state"
    default_timeout_seconds: int = Field(default=1800, ge=1)
    max_timeout_seconds: int = Field(default=3600, ge=1)
    default_max_turns: int = Field(default=40, ge=1)
    default_max_resume_count: int = Field(default=4, ge=0)


class ModelSettings(_StrictSection):
    """Model aliases or full model ids (§10).

    The CLI accepts both aliases (``sonnet``) and full names
    (``claude-sonnet-4-5``), so exact ids can be pinned later without a code
    change.
    """

    sonnet: str = Field(default="sonnet", min_length=1)
    opus: str = Field(default="opus", min_length=1)
    fable: str = Field(default="fable", min_length=1)


class RoutingSettings(_StrictSection):
    default_model: str = "sonnet"

    @field_validator("default_model")
    @classmethod
    def _never_fable(cls, v: str) -> str:
        if v not in {"sonnet", "opus"}:
            raise ValueError(
                "routing.default_model must be 'sonnet' or 'opus'; Fable is a "
                "reviewer and may never be the default implementation worker"
            )
        return v


class SecuritySettings(_StrictSection):
    """Security policy.

    ``allow_push`` / ``allow_merge`` / ``allow_commit`` / ``allow_subagents``
    are **not** switches (finding P1-9). Those operations are denied by
    code-level invariants in ``runner.ALWAYS_DISALLOWED_TOOLS`` /
    ``runner.CORE_DENIED_GIT_OPERATIONS`` that this file cannot reach; the keys
    survive only so an operator's existing config still parses, and setting one
    to ``true`` is refused rather than silently ignored. ``allow_network``
    remains a genuine (POLICY-level, prompt-carried) flag.
    """

    max_dispatch_depth: int = Field(default=1, ge=0, le=1)
    allow_network: bool = False
    allow_push: bool = False
    allow_merge: bool = False
    allow_commit: bool = False
    allow_subagents: bool = False
    allowed_repository_roots: list[str] = Field(min_length=1)

    @field_validator("allow_push", "allow_merge", "allow_commit", "allow_subagents")
    @classmethod
    def _prohibited_in_v1(cls, v: bool, info: ValidationInfo) -> bool:
        if v:
            raise ValueError(
                f"security.{info.field_name} cannot be enabled: the operation it "
                "names is denied by a non-configurable code-level invariant, not "
                "by this key. Remove the key rather than setting it to true"
            )
        return v

    @field_validator("allowed_repository_roots")
    @classmethod
    def _roots_must_be_real_and_narrow(cls, roots: list[str]) -> list[str]:
        resolved: list[str] = []
        for raw in roots:
            if raw == PLACEHOLDER_ROOT:
                raise ValueError(
                    f"allowed_repository_roots still contains the placeholder "
                    f"{PLACEHOLDER_ROOT!r}; configure a real repository root "
                    f"before dispatching"
                )
            if not raw.startswith("/"):
                raise ValueError(f"repository root must be absolute: {raw!r}")
            if raw.strip() in {"/", "//"}:
                raise ValueError(
                    "'/' is not an acceptable repository root; do not seed "
                    "broad filesystem access"
                )
            path = Path(raw).resolve()
            if str(path) == "/":
                raise ValueError(f"repository root resolves to '/': {raw!r}")
            if not path.exists():
                raise ValueError(f"repository root does not exist: {path}")
            if not path.is_dir():
                raise ValueError(f"repository root is not a directory: {path}")
            resolved.append(str(path))
        return resolved


class ValidationSettings(_StrictSection):
    run_dispatcher_validation: bool = True


class ClaudeSettings(_StrictSection):
    """How the worker subprocess is invoked (§11, §22).

    Paths are relative to the project root unless absolute. Existence is
    checked by ``scripts/doctor.sh`` and by the runner at dispatch time, not at
    config-load time, so that config can be validated on a host without Claude
    installed.
    """

    binary: str = "claude"
    permission_mode: str = "auto"
    worker_policy_path: str = "./prompts/worker-policy.md"
    fable_policy_path: str = "./prompts/fable-reviewer-policy.md"
    empty_mcp_config_path: str = "./config/empty-mcp.json"
    worker_result_schema_path: str = "./schemas/worker-result.schema.json"
    fable_review_schema_path: str = "./schemas/fable-review.schema.json"

    #: Built-in tools granted to an implementation worker (§11: prefer
    #: restricting the tool list over trusting prompts). Notably absent: Agent
    #: / Task (no subagents, §22 layer 2) and WebFetch/WebSearch.
    worker_tools: list[str] = Field(
        default_factory=lambda: [
            "Bash",
            "Read",
            "Write",
            "Edit",
            "Glob",
            "Grep",
            "TodoWrite",
            "NotebookEdit",
        ]
    )
    #: Read-only tool set for Fable (§7.3). No Edit, no Write, no Bash.
    reviewer_tools: list[str] = Field(
        default_factory=lambda: ["Read", "Glob", "Grep"]
    )
    #: Deny patterns applied on top of the tool list (§11, §22 layer 3).
    #: Operator-editable, and **additive only**: the runner unions this list
    #: with the non-configurable ``runner.ALWAYS_DISALLOWED_TOOLS`` (which now
    #: includes the prohibited git operations, P1-9), so emptying this key
    #: cannot lift a single core denial. The entries below are kept as visible
    #: documentation of the core set, not as its only enforcement.
    disallowed_tools: list[str] = Field(
        default_factory=lambda: [
            "mcp__*",
            "Bash(git push:*)",
            "Bash(git merge:*)",
            "Bash(git rebase:*)",
            "Bash(git commit:*)",
            "Bash(git reset:*)",
            "Bash(git clean:*)",
            "Bash(git worktree:*)",
            "Bash(claude:*)",
            "Bash(codex:*)",
            # Gate 4.5 P1/P2. Mirrors of ``runner.CORE_DENIED_GIT_OPERATIONS``
            # and ``runner.ALWAYS_DISALLOWED_TOOLS``, kept here as visible
            # documentation *and* because ``skills.SkillProjectionEngine``
            # refuses to project guidance that instructs an operation the
            # effective deny list does not cover: ``git bisect`` (detaches HEAD,
            # runs arbitrary commands per step) and ``gh`` (authenticated
            # mutation of remote state with the operator's credentials).
            "Bash(git bisect:*)",
            "Bash(gh:*)",
        ]
    )

    @field_validator("permission_mode")
    @classmethod
    def _known_permission_mode(cls, v: str) -> str:
        allowed = {"acceptEdits", "auto", "manual", "dontAsk", "plan"}
        if v not in allowed:
            raise ValueError(
                f"claude.permission_mode must be one of {sorted(allowed)}; "
                f"'bypassPermissions' is deliberately not offered"
            )
        return v


# ---------------------------------------------------------------------------
# Transport ceiling for the composed system prompt (BLOCKER B1)
# ---------------------------------------------------------------------------
#
# ``--append-system-prompt`` is emitted INLINE, as ONE argv element (the CLI
# takes a string, not a path — ``CLI_CAPABILITIES["append_system_prompt_file"]``
# is False). Linux therefore applies ``MAX_ARG_STRLEN`` to it.
#
# Measured facts, from Lane G's live adversarial gate (``GATE-LIVE-RESULT.md``,
# claims ``I-0`` … ``I-4``) — recorded here because these numbers, not a guess,
# are why the ceiling below is what it is:
#
#   * **131,071 bytes** — the host's hard cap on a SINGLE argv element,
#     measured by bisection against ``/bin/true``. Above it ``execve`` fails
#     with ``E2BIG``, the worker never starts, and (before this fix) the
#     dispatcher surfaced a raw ``OSError`` instead of a typed error.
#   * **128,992 bytes** — launched live, answered, and came back with nothing
#     truncated. A large prompt is not silently trimmed by the CLI.
#   * **144,486 bytes** — could not launch at all.
#   * **79,406 bytes** — the intended first-task shape (curated root + Kavya
#     guidance + core skill pack + preamble + policy). PASSES, with substantial
#     headroom.
#   * **184,718 bytes** — the ceiling this config file used to *permit*
#     (skills 120,000 + guidance 60,000 + preamble 1,834 + policy 2,884). That
#     is 41% above what the OS accepts: INVALID, and refused at load from here
#     on rather than clamped, so the operator learns their requested policy
#     cannot be honoured safely.
#   * **142,006 bytes** — the measured production worst case. Under V1 inline
#     transport that composition is **not supported** and MUST be refused; it
#     is not a shape this dispatcher can carry.
MEASURED_SINGLE_ARGV_LIMIT_BYTES = 131_071

#: The V1 hard ceiling on the FINAL composed ``--append-system-prompt`` value,
#: in UTF-8 **bytes** (never Python characters). 120 KiB, ~8 KiB below the
#: measured kernel cliff — deliberate reserve, because the kernel counts the
#: whole ``argv`` + ``envp`` block and remains the authority.
MAX_APPEND_SYSTEM_PROMPT_BYTES = 122_880

#: How much of the ceiling is reserved for the dispatcher's own authored text —
#: the worker/reviewer policy file and the envelope-precedence preamble — which
#: no ``[skills]`` or ``[project_guidance]`` cap covers. Measured on the
#: production shape: preamble 1,834 + policy 2,884 = 4,718 bytes. 8 KiB leaves
#: room for those files to grow without silently eating the transport budget.
#: It is a *reserve*, not a cap: the authoritative check is the measurement of
#: the final composed payload in ``runner.build_argv``.
DISPATCHER_AUTHORED_RESERVE_BYTES = 8_192

#: What is left for projected material once the reserve is set aside. Every
#: configurable projection ceiling is bounded by this, individually and in sum.
MAX_PROJECTED_CONTEXT_BYTES = (
    MAX_APPEND_SYSTEM_PROMPT_BYTES - DISPATCHER_AUTHORED_RESERVE_BYTES
)


#: Absolute ceiling on projected skill guidance, independent of what an
#: operator writes in the config. The Gate 4.5 §18 measurement puts the
#: deterministic worst-case profile at ~105 KB including co-projected support
#: files. It used to be 200,000 bytes, which the transport cannot carry; it is
#: now the transport budget itself. A config asking for more is refused rather
#: than clamped.
MAX_PROJECTED_BYTES_CEILING = MAX_PROJECTED_CONTEXT_BYTES


class SkillsSettings(_StrictSection):
    """Approved-skill projection policy (GATE 4.5 §9).

    Three of these five keys look like switches and are not. ``mode`` accepts
    only ``"projected"``: the native Claude Skill runtime is *not* an option a
    config file can turn on (§3, §14 — "Skill" never enters ``worker_tools``,
    and no plugin runtime reaches a worker). ``fail_on_drift`` accepts only
    ``true``: §10 makes drift a fail-closed condition, so the key exists to
    document the behaviour, not to disable it. ``max_projected_bytes`` is
    bounded above by :data:`MAX_PROJECTED_BYTES_CEILING`.

    ``enabled`` defaults to ``False``. A dispatcher that was never configured
    for skill projection projects nothing — the safe direction.
    """

    enabled: bool = False
    mode: str = "projected"
    fail_on_drift: bool = True
    #: 72,000 bytes: what remains of the transport budget once the guidance
    #: default is set aside. It covers the intended first-task core pack
    #: (44,757 bytes measured) with headroom, and deliberately does NOT cover
    #: the 95,333-byte worst-case profile — that profile cannot be transported
    #: inline under V1 at all (see the B1 block above).
    max_projected_bytes: int = Field(
        default=72_000, ge=1, le=MAX_PROJECTED_BYTES_CEILING
    )
    #: The source-controlled approval manifest (§9). Never auto-rewritten.
    manifest_path: str = "./config/approved-skills.json"

    @field_validator("mode")
    @classmethod
    def _projection_only(cls, v: str) -> str:
        if v != "projected":
            raise ValueError(
                "skills.mode must be 'projected'. The native Claude Skill "
                "runtime is not offered: GATE 4.5 chose controlled projection "
                "precisely because approving a SKILL.md hash does not approve "
                "the plugin runtime, hooks, subagents or MCP servers that ship "
                "beside it"
            )
        return v

    @field_validator("fail_on_drift")
    @classmethod
    def _drift_always_fails_closed(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "skills.fail_on_drift cannot be disabled: a changed hash, a "
                "missing file or a moved path means the approved text is no "
                "longer what was reviewed, and GATE 4.5 §10 requires refusing "
                "rather than silently accepting a new hash"
            )
        return v

    @field_validator("manifest_path")
    @classmethod
    def _manifest_path_is_set(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("skills.manifest_path must not be empty")
        return v


#: Absolute ceiling on projected project guidance. The measured worst
#: legitimate cross-scope shape (curated root + the two largest approved
#: subproject projections + the graph-refresh clause) is 41,955 bytes. Bounded
#: by the same transport budget as the skill cap (B1): what an operator may ask
#: for is limited by what ``execve`` will actually carry, not by taste.
MAX_GUIDANCE_BYTES_CEILING = MAX_PROJECTED_CONTEXT_BYTES


class ProjectGuidanceSettings(_StrictSection):
    """Curated project-guidance projection policy (GATE 4.5 addendum §9).

    The same two non-switches as ``[skills]``. ``mode`` accepts only
    ``"projected"``: native ``CLAUDE.md``/``AGENTS.md`` auto-loading is not an
    option a config file can turn on (addendum §3, §14 — the worker runs under
    ``--safe-mode`` precisely so it is off). ``fail_on_drift`` accepts only
    ``true``: a changed instruction source means the curated projection derived
    from it is no longer what was reviewed, and addendum §9 requires reapproval
    rather than a silent rebuild.

    ``enabled`` defaults to ``False``. A dispatcher that was never configured
    for guidance projection projects nothing — the safe direction.
    """

    enabled: bool = False
    mode: str = "projected"
    fail_on_drift: bool = True
    #: 42,000 bytes: covers the measured production worst-case guidance shape
    #: (41,955 bytes) exactly, and no more — the rest of the transport budget
    #: belongs to the skill pack.
    max_projected_bytes: int = Field(
        default=42_000, ge=1, le=MAX_GUIDANCE_BYTES_CEILING
    )
    #: The reviewed, source-controlled approval manifest. Never auto-rewritten.
    manifest_path: str = "./config/approved-guidance.json"

    @field_validator("mode")
    @classmethod
    def _projection_only(cls, v: str) -> str:
        if v != "projected":
            raise ValueError(
                "project_guidance.mode must be 'projected'. Native CLAUDE.md / "
                "AGENTS.md loading is not offered: the root documents mix safe "
                "engineering context with production operator procedures and "
                "credential locations, and approving a repository does not "
                "approve everything its instruction files instruct"
            )
        return v

    @field_validator("fail_on_drift")
    @classmethod
    def _drift_always_fails_closed(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "project_guidance.fail_on_drift cannot be disabled: a changed "
                "CLAUDE.md/AGENTS.md hash means the curated projection derived "
                "from it is no longer what was reviewed, and the Gate 4.5 "
                "addendum §9 requires reapproval rather than a silent rebuild"
            )
        return v

    @field_validator("manifest_path")
    @classmethod
    def _manifest_path_is_set(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("project_guidance.manifest_path must not be empty")
        return v


class LoggingSettings(_StrictSection):
    """§28: logs go to stderr or files, never stdout (stdout is MCP transport)."""

    level: str = "INFO"
    log_file: str | None = None

    @field_validator("level")
    @classmethod
    def _known_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"logging.level must be one of {sorted(allowed)}")
        return v.upper()


class Config(BaseModel):
    """Fully validated dispatcher configuration."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    dispatcher: DispatcherSettings
    models: ModelSettings
    routing: RoutingSettings
    security: SecuritySettings
    validation: ValidationSettings = Field(default_factory=ValidationSettings)
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)
    skills: SkillsSettings = Field(default_factory=SkillsSettings)
    project_guidance: ProjectGuidanceSettings = Field(
        default_factory=ProjectGuidanceSettings
    )
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    #: Absolute path of the file this config was loaded from (``None`` when
    #: built from a mapping in tests).
    source_path: str | None = None
    #: Directory relative paths in this config resolve against.
    project_root: str = "."

    # -- cross-section invariants -----------------------------------------

    @model_validator(mode="after")
    def _composed_context_fits_the_transport(self) -> "Config":
        """Refuse a configuration whose composed ceiling ``execve`` cannot carry.

        BLOCKER B1. Per-section caps are checked individually above, but a sum
        of individually legal caps is not automatically legal: the two
        projections and the dispatcher's own authored text all end up in ONE
        argv element, and Linux caps that element at 131,071 bytes. The old
        defaults permitted 184,718 bytes — 41% above what the OS accepts — so
        the dispatcher would compose a payload, hand it to ``execve``, and get
        ``E2BIG`` with no worker and no typed error.

        Fail closed at load, and do NOT clamp: an operator who asked for a
        larger context must learn that their policy cannot be honoured, not
        silently receive a smaller one. The authoritative check is still the
        measurement of the final composed payload in ``runner.build_argv``;
        this one exists so an impossible policy is rejected before any task
        depends on it.

        Enforced whether or not the sections are enabled: the config states a
        policy, and a policy that cannot be transported is wrong while it is
        switched off too.
        """
        projected = (
            self.skills.max_projected_bytes
            + self.project_guidance.max_projected_bytes
        )
        composed = projected + DISPATCHER_AUTHORED_RESERVE_BYTES
        if composed > MAX_APPEND_SYSTEM_PROMPT_BYTES:
            raise ValueError(
                "the composed context ceiling this configuration requests "
                f"({composed} bytes = skills {self.skills.max_projected_bytes} "
                f"+ project_guidance {self.project_guidance.max_projected_bytes} "
                f"+ {DISPATCHER_AUTHORED_RESERVE_BYTES} reserved for the worker "
                "policy and the envelope-precedence preamble) exceeds the "
                f"{MAX_APPEND_SYSTEM_PROMPT_BYTES}-byte transport ceiling for a "
                "single --append-system-prompt argv element. The measured Linux "
                f"limit is {MEASURED_SINGLE_ARGV_LIMIT_BYTES} bytes; a payload "
                "above it cannot be launched at all. Lower "
                "skills.max_projected_bytes and/or "
                "project_guidance.max_projected_bytes so they sum to at most "
                f"{MAX_PROJECTED_CONTEXT_BYTES} bytes. This ceiling is not "
                "clamped down for you on purpose"
            )
        return self

    # -- derived paths ----------------------------------------------------

    def _resolve(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return (Path(self.project_root) / path).resolve()

    @property
    def state_path(self) -> Path:
        return self._resolve(self.dispatcher.state_dir)

    @property
    def tasks_path(self) -> Path:
        return self.state_path / "tasks"

    @property
    def locks_path(self) -> Path:
        return self.state_path / "locks"

    @property
    def proposals_path(self) -> Path:
        return self.state_path / "proposals"

    @property
    def worker_policy_file(self) -> Path:
        return self._resolve(self.claude.worker_policy_path)

    @property
    def fable_policy_file(self) -> Path:
        return self._resolve(self.claude.fable_policy_path)

    @property
    def empty_mcp_file(self) -> Path:
        return self._resolve(self.claude.empty_mcp_config_path)

    @property
    def worker_schema_file(self) -> Path:
        return self._resolve(self.claude.worker_result_schema_path)

    @property
    def fable_schema_file(self) -> Path:
        return self._resolve(self.claude.fable_review_schema_path)

    @property
    def approved_skills_file(self) -> Path:
        """The approved-skill manifest (§9). Read-only, source-controlled."""
        return self._resolve(self.skills.manifest_path)

    @property
    def approved_guidance_file(self) -> Path:
        """The project-guidance manifest (addendum §9). Read-only, reviewed."""
        return self._resolve(self.project_guidance.manifest_path)

    def model_for(self, alias: str) -> str:
        """Map ``sonnet`` / ``opus`` / ``fable`` to the configured identifier."""
        try:
            return getattr(self.models, alias)
        except AttributeError as exc:  # pragma: no cover - guarded by callers
            raise ConfigurationError(
                f"Unknown model alias {alias!r}.",
                details={"known": ["sonnet", "opus", "fable"]},
            ) from exc

    def clamp_timeout(self, requested: int) -> int:
        """Clamp a requested worker timeout to the configured maximum (§20)."""
        return min(requested, self.dispatcher.max_timeout_seconds)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_REQUIRED_SECTIONS = ("dispatcher", "models", "routing", "security")


def _format_validation_error(exc: ValidationError) -> list[dict[str, Any]]:
    """Compact, secret-free rendering of a pydantic error (§29)."""
    issues: list[dict[str, Any]] = []
    for err in exc.errors():
        issues.append(
            {
                "location": ".".join(str(p) for p in err["loc"]),
                "problem": err["msg"],
            }
        )
    return issues


def load_config_from_mapping(
    data: dict[str, Any],
    *,
    source_path: str | None = None,
    project_root: str | Path = ".",
) -> Config:
    """Validate an already-parsed TOML mapping into a :class:`Config`."""
    if not isinstance(data, dict):
        raise ConfigurationError(
            "Configuration root must be a table.",
            details={"got": type(data).__name__},
        )

    missing = [s for s in _REQUIRED_SECTIONS if s not in data]
    if missing:
        raise ConfigurationError(
            "Configuration is missing required sections.",
            details={"missing_sections": missing},
            remediation="Start from config/dispatcher.example.toml.",
        )

    payload = dict(data)
    payload["source_path"] = source_path
    payload["project_root"] = str(Path(project_root).resolve())

    try:
        return Config(**payload)
    except ValidationError as exc:
        raise ConfigurationError(
            "Configuration is invalid.",
            details={
                "source": source_path,
                "issues": _format_validation_error(exc),
            },
            remediation="Fix the listed keys; the dispatcher will not start "
            "with an invalid configuration.",
        ) from exc


def load_config(path: str | Path, *, project_root: str | Path | None = None) -> Config:
    """Load and validate a dispatcher TOML config.

    Args:
        path: Path to the TOML file.
        project_root: Directory that relative paths in the config resolve
            against. Defaults to the config file's parent's parent (i.e. the
            project root when the file lives in ``config/``), falling back to
            the file's own directory.

    Raises:
        ConfigurationError: file missing, unreadable, malformed TOML, or
            semantically invalid. Never returns a partially valid Config.
    """
    config_path = Path(path)

    if not config_path.exists():
        raise ConfigurationError(
            "Configuration file not found.",
            details={"path": str(config_path)},
            remediation="Copy config/dispatcher.example.toml and edit it.",
        )
    if not config_path.is_file():
        raise ConfigurationError(
            "Configuration path is not a file.",
            details={"path": str(config_path)},
        )

    try:
        raw = config_path.read_bytes()
    except OSError as exc:
        raise ConfigurationError(
            "Configuration file could not be read.",
            details={"path": str(config_path), "reason": exc.strerror},
        ) from exc

    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ConfigurationError(
            "Configuration file is not valid UTF-8.",
            details={"path": str(config_path)},
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(
            "Configuration file is not valid TOML.",
            details={"path": str(config_path), "reason": str(exc)},
        ) from exc

    if project_root is None:
        parent = config_path.resolve().parent
        project_root = parent.parent if parent.name == "config" else parent

    return load_config_from_mapping(
        data,
        source_path=str(config_path.resolve()),
        project_root=project_root,
    )
