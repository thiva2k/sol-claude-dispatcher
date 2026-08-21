"""Typed error taxonomy for the dispatcher (brief §29).

Every failure that crosses the MCP boundary must be one of these. The rule from
§29 is blunt: *never* return a 4,000-line Python traceback to Sol. Diagnostics
belong in state and log files; what Sol receives is a short, structured,
actionable payload.

Usage contract for every module in this package:

    raise RepositoryNotAllowed(
        "Repository is outside the configured allowlist.",
        details={"root": str(root), "allowed_roots": [...]},
        remediation="Add the path to [security].allowed_repository_roots.",
    )

The MCP layer catches :class:`DispatcherError` and serialises it with
:meth:`DispatcherError.to_payload`. Anything that is *not* a DispatcherError
escaping into the MCP layer is a bug; the MCP layer wraps it as
:class:`InternalDispatcherError` and logs the traceback to stderr only.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "DispatcherError",
    "InternalDispatcherError",
    "InvalidRepository",
    "RepositoryNotAllowed",
    "RepositoryBusy",
    "InvalidTaskEnvelope",
    "InvalidStateTransition",
    "TaskNotFound",
    "ClaudeBinaryNotFound",
    "ClaudeExecutionFailed",
    "ClaudeStructuredOutputInvalid",
    "ClaudeTimedOut",
    "ResumeLimitReached",
    "PolicyViolation",
    "SkillPolicyViolation",
    "ApprovedSkillChanged",
    "ProjectGuidanceNotApproved",
    "ProjectGuidanceScopeError",
    "ProjectGuidancePolicyViolation",
    "ProjectGuidanceRepositoryMismatch",
    "ProjectGuidanceSourceChanged",
    "ProjectGuidanceProjectionChanged",
    "ProjectGuidanceDrift",
    "ProjectGuidanceResumeDrift",
    "UnapprovedProjectGuidanceFile",
    "ContextTooLarge",
    "ValidationFailed",
    "WorktreeCreationFailed",
    "GitEvidenceCollectionFailed",
    "RecursionDetected",
    "ConfigurationError",
    "StateCorruption",
    "ERROR_CODES",
]


class DispatcherError(Exception):
    """Base class for every error the dispatcher reports to Sol.

    Attributes:
        code: Stable machine-readable identifier (the class name). Sol may
            branch on this; it must not change casually.
        message: One-sentence human-readable explanation. No tracebacks.
        details: JSON-serialisable structured context. Must never contain
            secrets, environment dumps, or full file contents.
        remediation: Optional hint describing what a human or Sol can do next.
        retryable: Whether retrying the identical request could plausibly
            succeed without any change (e.g. RepositoryBusy).
    """

    code: str = "DispatcherError"
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        remediation: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        self.remediation = remediation

    def to_payload(self) -> dict[str, Any]:
        """Serialise for an MCP tool response. Concise by construction."""
        payload: dict[str, Any] = {
            "error": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            payload["details"] = self.details
        if self.remediation:
            payload["remediation"] = self.remediation
        return payload

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.code}({self.message!r}, details={self.details!r})"


# --------------------------------------------------------------------------
# Repository / workspace
# --------------------------------------------------------------------------


class InvalidRepository(DispatcherError):
    """Path is missing, is not a directory, or is not a git repository."""

    code = "InvalidRepository"


class RepositoryNotAllowed(DispatcherError):
    """Canonical path falls outside ``[security].allowed_repository_roots``."""

    code = "RepositoryNotAllowed"


class RepositoryBusy(DispatcherError):
    """Another mutating worker already holds this repository's lock (§25)."""

    code = "RepositoryBusy"
    retryable = True


class WorktreeCreationFailed(DispatcherError):
    """Could not create or locate the isolated worktree for a task (§12)."""

    code = "WorktreeCreationFailed"


class GitEvidenceCollectionFailed(DispatcherError):
    """An authoritative git command failed, timed out, or produced unusable output.

    The dispatcher's scope and non-interference decisions are only as good as
    the evidence they are made from. "git could not tell us" is *not* "nothing
    changed": conflating the two would let a run whose changes could not be
    measured land as ``changed_paths=[] / scope_valid=true``. So evidence
    collection fails closed with this error and the task lands in an explicit
    failure state with the diagnostics preserved, rather than in a state that
    implies a clean, in-scope result nobody actually observed.
    """

    code = "GitEvidenceCollectionFailed"


# --------------------------------------------------------------------------
# Envelope / state
# --------------------------------------------------------------------------


class InvalidTaskEnvelope(DispatcherError):
    """Caller input or a persisted envelope failed model validation."""

    code = "InvalidTaskEnvelope"


class InvalidStateTransition(DispatcherError):
    """Refused a transition not permitted by the state machine (§26)."""

    code = "InvalidStateTransition"


class TaskNotFound(DispatcherError):
    """No persisted task exists for the supplied ``task_id``."""

    code = "TaskNotFound"


class StateCorruption(DispatcherError):
    """Persisted state is unreadable or internally inconsistent.

    §27: state corruption fails closed. Never repair silently.
    """

    code = "StateCorruption"


# --------------------------------------------------------------------------
# Claude subprocess
# --------------------------------------------------------------------------


class ClaudeBinaryNotFound(DispatcherError):
    """Configured Claude executable is absent or not executable."""

    code = "ClaudeBinaryNotFound"


class ClaudeExecutionFailed(DispatcherError):
    """Claude exited non-zero, or could not be started at all."""

    code = "ClaudeExecutionFailed"


class ClaudeStructuredOutputInvalid(DispatcherError):
    """Claude's stdout was not valid JSON, or did not match the worker schema.

    §15: parse the real JSON result. Never regex-scrape prose to recover.
    """

    code = "ClaudeStructuredOutputInvalid"


class ClaudeTimedOut(DispatcherError):
    """The worker exceeded its dispatcher timeout and was terminated (§20).

    A timeout is *not* evidence that the implementation is wrong. Evidence
    (session id, worktree, partial output, diff) must survive this error.
    """

    code = "ClaudeTimedOut"


# --------------------------------------------------------------------------
# Policy / limits
# --------------------------------------------------------------------------


class ResumeLimitReached(DispatcherError):
    """``resume_count`` has reached ``max_resume_count`` (§7.2, §22 layer 6)."""

    code = "ResumeLimitReached"


class PolicyViolation(DispatcherError):
    """The run touched paths outside its declared scope (§13).

    Evidence is preserved. Sol decides whether to reject or correct.
    """

    code = "PolicyViolation"


class SkillPolicyViolation(PolicyViolation):
    """An unapproved or ineligible skill reached the projection engine.

    Gate 4.5 §9/§11. Raised when a skill id is not an explicit manifest entry,
    when its classification is not projectable (§7: MANUAL_ONLY /
    UNSAFE_FOR_DISPATCHER / UNKNOWN never project), when a required deny
    pattern is absent from the effective tool policy, when a skill file carries
    a frontmatter mechanism or a dynamic-command construct, or when the
    projected payload exceeds the configured byte cap (§18).

    This is *policy*, not drift: nothing on disk changed, the request itself is
    refused.
    """

    code = "SkillPolicyViolation"


class ApprovedSkillChanged(DispatcherError):
    """A pinned skill source no longer matches what was approved (§10, §15).

    Hash mismatch, a missing file, a resolved path that moved, or a path that
    no longer belongs to the expected pinned plugin install. The dispatcher
    never recalculates and accepts a new hash: re-approval is a human/Sol
    decision recorded in ``config/approved-skills.json``.
    """

    code = "ApprovedSkillChanged"


# --------------------------------------------------------------------------
# Project-guidance projection (Gate 4.5 addendum §1-§20, rulings §1-§7)
# --------------------------------------------------------------------------


class ProjectGuidanceNotApproved(PolicyViolation):
    """A scope with no approved curated projection was selected.

    Raised when the manifest itself is not approved, when a selected scope is
    ``CLASSIFIED_NOT_APPROVED`` (its CLAUDE.md/AGENTS.md exist but were never
    reviewed), or when Fable review is requested for a scope that has no
    approved review projection.

    Rulings §7 is explicit that there is **no root-only fallback**: root
    guidance does not carry a subproject's domain invariants, so dispatching
    without them would silently authorise work against guidance nobody reviewed
    for that subproject.
    """

    code = "ProjectGuidanceNotApproved"


class ProjectGuidanceScopeError(PolicyViolation):
    """An ``allowed_paths`` entry is outside the pinned repository, or too broad.

    Covers a path that escapes the toplevel after normalisation, a path under a
    denied prefix (``.claude/worktrees/``, ``Taskforce_AI_Website/``) or denied
    absolute tree (``/home/dev/worktrees/``), and an envelope intersecting more
    subprojects than ``scope_map.max_subscopes`` permits.
    """

    code = "ProjectGuidanceScopeError"


class ProjectGuidancePolicyViolation(PolicyViolation):
    """A projection artifact was refused on content or size grounds.

    ``details["reason"]`` distinguishes
    ``sensitive_content_in_source_derived_artifact`` (the strict classifier
    matched a ``SOURCE_DERIVED`` artifact — fix the content, never the pattern
    set) from ``size_cap_exceeded``.
    """

    code = "ProjectGuidancePolicyViolation"


class ProjectGuidanceRepositoryMismatch(DispatcherError):
    """The dispatch repository is not the one the guidance was approved against.

    All four of toplevel, git dir, origin url and root commit must match the
    manifest pin. ``root_commit`` is what makes this resistant to a path swap:
    a nested repository sitting inside the working tree has its own root commit
    and cannot satisfy the parent's (rulings §4).
    """

    code = "ProjectGuidanceRepositoryMismatch"


class ProjectGuidanceSourceChanged(DispatcherError):
    """A pinned CLAUDE.md/AGENTS.md no longer matches its approved hash.

    The dispatcher never recalculates and accepts the new hash: reapproval is a
    human/Sol decision recorded in ``config/approved-guidance.json``.
    """

    code = "ProjectGuidanceSourceChanged"


class ProjectGuidanceProjectionChanged(DispatcherError):
    """A curated projection artifact no longer matches its approved hash."""

    code = "ProjectGuidanceProjectionChanged"


class ProjectGuidanceDrift(DispatcherError):
    """An instruction pair approved as byte-identical aliases has diverged.

    Addendum §7 prefers fail-closed for V1: do not silently pick one half of a
    generated-mirror pair once the halves disagree.
    """

    code = "ProjectGuidanceDrift"


class ProjectGuidanceResumeDrift(DispatcherError):
    """The project-guidance context changed between dispatch and resume (§16)."""

    code = "ProjectGuidanceResumeDrift"


class UnapprovedProjectGuidanceFile(DispatcherError):
    """The DEFAULT-DENY verification scan found an unreviewed instruction file.

    Discovery is verification only — it never selects a guidance source
    (rulings §3). A new nested ``CLAUDE.md`` defaults to DENY/UNREVIEWED.
    """

    code = "UnapprovedProjectGuidanceFile"


class ContextTooLarge(DispatcherError):
    """The composed worker context cannot be transported to the CLI (B1).

    ``--append-system-prompt`` is emitted inline as ONE argv element, and Linux
    caps a single argv element at 131,071 bytes (measured). The dispatcher's V1
    ceiling is 122,880 bytes of UTF-8, checked against the FINAL composed value
    before ``execve`` — and again, defensively, if the kernel returns ``E2BIG``
    anyway.

    This is a **refusal**, not a degradation. The approved deterministic context
    is part of the task contract, so the dispatcher never drops a Skill, never
    drops a guidance scope, and never truncates to squeeze underneath. The
    selected profile is reported instead, so Sol can narrow the task or wait for
    a transport that carries more.

    ``details`` carries bounded facts only — sizes, ids, the model, the role —
    never the payload, never projected guidance, never anything secret-adjacent.
    """

    code = "ContextTooLarge"


class ValidationFailed(DispatcherError):
    """A trusted dispatcher validation command failed (§17)."""

    code = "ValidationFailed"


class RecursionDetected(DispatcherError):
    """A dispatch was attempted from inside a worker context (§22)."""

    code = "RecursionDetected"


# --------------------------------------------------------------------------
# Configuration / internal
# --------------------------------------------------------------------------


class ConfigurationError(DispatcherError):
    """Configuration is missing, malformed, or semantically invalid (§35)."""

    code = "ConfigurationError"


class InternalDispatcherError(DispatcherError):
    """Unexpected internal fault. Traceback goes to logs, never to Sol."""

    code = "InternalDispatcherError"


#: Every error code the dispatcher may emit. Used by tests and by the docs to
#: guarantee the taxonomy stays complete and in sync with §29.
ERROR_CODES: frozenset[str] = frozenset(
    {
        "DispatcherError",
        "InternalDispatcherError",
        "InvalidRepository",
        "RepositoryNotAllowed",
        "RepositoryBusy",
        "InvalidTaskEnvelope",
        "InvalidStateTransition",
        "TaskNotFound",
        "StateCorruption",
        "ClaudeBinaryNotFound",
        "ClaudeExecutionFailed",
        "ClaudeStructuredOutputInvalid",
        "ClaudeTimedOut",
        "ResumeLimitReached",
        "PolicyViolation",
        "SkillPolicyViolation",
        "ApprovedSkillChanged",
        "ProjectGuidanceNotApproved",
        "ProjectGuidanceScopeError",
        "ProjectGuidancePolicyViolation",
        "ProjectGuidanceRepositoryMismatch",
        "ProjectGuidanceSourceChanged",
        "ProjectGuidanceProjectionChanged",
        "ProjectGuidanceDrift",
        "ProjectGuidanceResumeDrift",
        "UnapprovedProjectGuidanceFile",
        "ContextTooLarge",
        "ValidationFailed",
        "WorktreeCreationFailed",
        "GitEvidenceCollectionFailed",
        "RecursionDetected",
        "ConfigurationError",
    }
)
