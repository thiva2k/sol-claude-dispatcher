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
    "ClaudeProviderLimit",
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
    "ValidationBudgetExceeded",
    "WorktreeCreationFailed",
    "WorktreeBaseMismatch",
    "GitEvidenceCollectionFailed",
    "RecursionDetected",
    "ConfigurationError",
    "ConfigAuthorityViolation",
    "StateCorruption",
    "AdminAllowlistPresent",
    "AmbiguousRepositoryHistory",
    "AttributionClosureViolated",
    "BaseBlobUnreadable",
    "BaseCommitAbsent",
    "BaseObjectVerificationFailed",
    "BaseRefNotACommitObject",
    "BaseTreeSnapshotFailed",
    "CheckoutTransformationBudgetExceeded",
    "DispatcherSetupTouchedPrimaryTree",
    "EvidenceFreezeViolated",
    "EvidenceIncompleteForReview",
    "EvidenceExceedsReviewBudget",
    "FilesystemSnapshotFailed",
    "ForbiddenGitInvocation",
    "GitAdministrativeCaptureFailed",
    "GitArgvPinDisplaced",
    "GitBeforeEstablishment",
    "GitIdentityDerivationAttempted",
    "HistoryIdentityDerivationDisagreement",
    "InventoryFilesystemUnsupported",
    "PathIdentityUnrepresentable",
    "PhaseRegression",
    "ProductionBaseRefNotExact",
    "RefResolutionFailed",
    "RepositoryAdministrationUnestablished",
    "RepositoryAdministrationUnreconciled",
    "RepositoryAdministrationUnsupported",
    "RepositoryAuthorityCaptureFailed",
    "RepositoryIdentityUnsealed",
    "RepositoryLayoutUnreadable",
    "RepositoryObjectStoreEntryUnsupported",
    "RepositoryObjectStoreMalformed",
    "RepositoryRootDrift",
    "RunFinalizationFailed",
    "SealAbsentAfterWorker",
    "SealBudgetExceeded",
    "SealIntegrityFailed",
    "SealPinSetStale",
    "SealProvenanceInvalid",
    "SnapshotBudgetExceeded",
    "DiffBudgetExceeded",
    "StoreRoutingUnreadable",
    "UnsupportedObjectFormat",
    "UnsupportedRefStorage",
    "ValidationAttributionUnknown",
    "ValidationTouchedAdministrativeState",
    "ValidationTouchedPrimaryTree",
    "WorkerAttributionAmbiguous",
    "WorkerExitSnapshotMissing",
    "WorktreeGitdirNotDispatcherOwned",
    "WorktreeGitfileMalformed",
    "WorktreeGitfileNotRegular",
    "WorktreeHeadNotRegular",
    "WorktreeIndirectionChanged",
    "WorktreeSealSchemaUnsupported",
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


class WorktreeBaseMismatch(DispatcherError):
    """The isolated worktree is not on the commit the task recorded as its base (B2).

    Every measurement the dispatcher makes about a run — changed paths, the
    scope decision, ``evidence/diff.patch``, the review prompt, the validation
    it re-runs — is taken as a diff against the recorded base commit. If the
    worktree is on a different commit, all of it describes a tree that never
    existed: the base divergence is attributed to the worker, and — worse — a
    worker change that happens to restore a file to its recorded-base content
    disappears **entirely**, because the two components of
    ``(W - B) u worker-changes`` cancel. A genuinely forbidden change can be
    recorded ``scope_valid: true`` that way.

    There is no partial-credit reading of this, so it fails closed rather than
    warning, and the recorded base is never rewritten to match what was found:
    Sol named a base, and the dispatcher's job is to report that it could not
    honour it, not to silently redefine the task.
    """

    code = "WorktreeBaseMismatch"
    retryable = False


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

    This is a statement about **model output**, and it must stay that narrow. A
    run the provider refused (:class:`ClaudeProviderLimit`), a CLI that never
    produced anything (:class:`ClaudeExecutionFailed`) and a run the dispatcher
    killed (:class:`ClaudeTimedOut`) all also arrive with nothing parseable, and
    reporting any of them here sends the operator to the wrong layer.
    """

    code = "ClaudeStructuredOutputInvalid"


class ClaudeProviderLimit(DispatcherError):
    """The provider refused the run with a usage or rate limit (B3).

    Production task ``c5e385c9`` died on an HTTP 429 weekly account limit. The
    CLI wrapped the provider's prose in its ordinary ``--output-format json``
    envelope, **exited 0**, and stated the cause in three machine-readable
    envelope fields — ``is_error: true``, ``terminal_reason: "api_error"``,
    ``api_error_status: 429``. Nothing read them, so the empty structured
    payload was reported as ``ClaudeStructuredOutputInvalid``: a verdict that is
    literally true and diagnostically wrong. It says "the model emitted a bad
    schema" about an account that had run out of quota, and an operator acting
    on it goes looking at prompts and schemas instead of at billing or the
    clock.

    So this is its own branch of the taxonomy. It is decided **only** from
    trusted CLI-envelope and process evidence (``runner.envelope_facts``); text
    the model wrote — its summary, its prose result, its structured payload —
    can never reach this classification, however many times it says "429".

    ``retryable`` is True in the precise sense §29 gives the word: the identical
    request may succeed later, unchanged, once the limit window resets. It is
    *not* a licence to retry automatically — the dispatcher never does — and the
    task still lands in a failure state with its session, worktree and evidence
    preserved so Sol can decide when to resume.

    ``details`` carries bounded facts only: the trusted envelope signals, the
    exit status, the token counts that expose a zero-work run, and a short
    redacted excerpt of the provider's own message (which usually names the
    reset time). Never the prompt, never argv, never the raw envelope.
    """

    code = "ClaudeProviderLimit"
    retryable = True


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
    """The complete worker invocation cannot be transported to the CLI (B1).

    ``--append-system-prompt`` is emitted inline as ONE argv element, and Linux
    caps a single argv element at 131,071 bytes (measured). The dispatcher's V1
    ceiling is 122,880 bytes of UTF-8, checked against the FINAL composed value
    before ``execve``.  The runner also measures every final argv element,
    every encoded ``KEY=value`` envp element, all NUL terminators and the two
    pointer tables against ``SC_ARG_MAX`` with an explicit reserve.  Kernel
    ``E2BIG`` remains a defence-in-depth typed refusal.

    This is a **refusal**, not a degradation. The approved deterministic context
    is part of the task contract, so the dispatcher never drops a Skill, never
    drops a guidance scope, and never truncates to squeeze underneath. The
    selected profile is reported instead, so Sol can narrow the task or wait for
    a transport that carries more.

    ``details`` carries bounded facts only — sizes, indices, ids, the model and
    the role — never argv text, environment names or values, projected
    guidance, or anything secret-adjacent.
    """

    code = "ContextTooLarge"


class ValidationFailed(DispatcherError):
    """A trusted dispatcher validation command failed (§17)."""

    code = "ValidationFailed"


class ValidationBudgetExceeded(DispatcherError):
    """The envelope declares more work than one MCP tool call can carry.

    GATE 6, closing Lane K's FINDING K-1. ``models.ValidationSpec`` permits 32
    commands of up to 3,600 s each, so an envelope may legally declare over
    115,000 s of validation. Since Gate 6 the dispatch/resume/review tool call
    stays pending for the whole run, and no ``tool_timeout_sec`` can cover that.

    Raised **before any worker starts**, on every path that starts one. This is
    a refusal, not a degradation: the dispatcher never truncates a declared
    timeout, never drops a validation command to fit, and never clamps the
    configured budget down. The caller is told exactly how much it asked for,
    how much is available, and which validation commands make up the total, so
    it can shrink the envelope deliberately.

    Exceeding the budget is not the same as exceeding the tool timeout. The tool
    timeout remains a *latency* bound — ``waiting.py`` has no timeout of its own
    and a cancelled waiter never kills a worker. This error exists so an
    envelope that would predictably outrun the transport is refused up front
    rather than discovered halfway through validation.

    ``details`` carries bounded facts only: the declared total, the budget, the
    excess, and one entry per validation command giving its index, the basename
    of its program and its declared timeout. Never argv arguments, never the
    objective, never repository contents.
    """

    code = "ValidationBudgetExceeded"


class RecursionDetected(DispatcherError):
    """A dispatch was attempted from inside a worker context (§22)."""

    code = "RecursionDetected"


# --------------------------------------------------------------------------
# Configuration / internal
# --------------------------------------------------------------------------


class ConfigurationError(DispatcherError):
    """Configuration is missing, malformed, or semantically invalid (§35)."""

    code = "ConfigurationError"


class ConfigAuthorityViolation(ConfigurationError):
    """Something tried to choose the config the PRODUCTION server runs (B4).

    The registered production MCP server loads the canonical
    ``config/dispatcher.toml`` and nothing else. A ``SOL_DISPATCHER_CONFIG``
    naming any other file is **refused at startup**, not ignored: an operator
    or a process that believes it selected another configuration must not
    receive a server quietly running under different assumptions — in
    particular, a different ``security.allowed_repository_roots``.

    Also raised by the test/development stdio harness when the disposable
    config it was handed touches the production boundary at all.

    A subclass of :class:`ConfigurationError` so every existing fail-closed
    handler already covers it, with its own code so the refusal is
    machine-distinguishable from an ordinary malformed-config error.
    """

    code = "ConfigAuthorityViolation"


class InternalDispatcherError(DispatcherError):
    """Unexpected internal fault. Traceback goes to logs, never to Sol."""

    code = "InternalDispatcherError"


# --------------------------------------------------------------------------
# Gate 7 Wave-0 authority, evidence and refusal taxonomy
# --------------------------------------------------------------------------


class RepositoryAdministrationUnestablished(DispatcherError):
    """No operator-approved administrative baseline exists for the repository."""

    code = "RepositoryAdministrationUnestablished"


class RepositoryAdministrationUnreconciled(DispatcherError):
    """Current administrative authority diverges from its approved baseline."""

    code = "RepositoryAdministrationUnreconciled"


class RepositoryAdministrationUnsupported(DispatcherError):
    """Repository administration has a shape Wave 0 cannot safely interpret."""

    code = "RepositoryAdministrationUnsupported"


class RepositoryLayoutUnreadable(DispatcherError):
    """The raw repository-layout resolver could not establish authority."""

    code = "RepositoryLayoutUnreadable"


class RepositoryObjectStoreMalformed(DispatcherError):
    """A loose object is not canonical for its content-addressed path."""

    code = "RepositoryObjectStoreMalformed"


class RepositoryObjectStoreEntryUnsupported(DispatcherError):
    """An object-store entry has a prohibited name or filesystem type."""

    code = "RepositoryObjectStoreEntryUnsupported"


class UnsupportedObjectFormat(DispatcherError):
    """The repository object format is outside Wave 0's supported set."""

    code = "UnsupportedObjectFormat"


class ProductionBaseRefNotExact(DispatcherError):
    """A production dispatch supplied a symbolic rather than exact base."""

    code = "ProductionBaseRefNotExact"


class BaseRefNotACommitObject(DispatcherError):
    """The exact base object exists but is not a commit."""

    code = "BaseRefNotACommitObject"


class BaseCommitAbsent(DispatcherError):
    """The exact base commit is not locally present."""

    code = "BaseCommitAbsent"


class BaseTreeSnapshotFailed(GitEvidenceCollectionFailed):
    """A complete base-tree identity snapshot could not be constructed."""

    code = "BaseTreeSnapshotFailed"


class BaseBlobUnreadable(GitEvidenceCollectionFailed):
    """A base blob could not be materialised during PREPARE."""

    code = "BaseBlobUnreadable"


class BaseObjectVerificationFailed(GitEvidenceCollectionFailed):
    """Materialised bytes did not hash to the requested Git object id."""

    code = "BaseObjectVerificationFailed"


class SealBudgetExceeded(DispatcherError):
    """A pre-worker seal exceeded a configured fail-closed budget."""

    code = "SealBudgetExceeded"


class SealIntegrityFailed(DispatcherError):
    """A persisted seal or one of its covered artefacts failed verification."""

    code = "SealIntegrityFailed"


class SealAbsentAfterWorker(DispatcherError):
    """A pre-worker seal is absent after durable worker ownership existed."""

    code = "SealAbsentAfterWorker"


class SealProvenanceInvalid(InternalDispatcherError):
    """A seal claims provenance inconsistent with durable worker ownership."""

    code = "SealProvenanceInvalid"


class WorktreeIndirectionChanged(DispatcherError):
    """The sealed linked-worktree indirection changed after worker start."""

    code = "WorktreeIndirectionChanged"


class StoreRoutingUnreadable(DispatcherError):
    """Object-store routing authority could not be read safely."""

    code = "StoreRoutingUnreadable"


class RepositoryAuthorityCaptureFailed(DispatcherError):
    """A raw repository-authority capture could not be completed."""

    code = "RepositoryAuthorityCaptureFailed"


class AdminAllowlistPresent(InternalDispatcherError):
    """Administrative capture attempted to exempt a path by name or prefix."""

    code = "AdminAllowlistPresent"


class GitBeforeEstablishment(InternalDispatcherError):
    """A dispatcher Git invocation preceded its administrative gate."""

    code = "GitBeforeEstablishment"


class WorkerAttributionAmbiguous(DispatcherError):
    """Worker-attributable filesystem change could not be determined exactly."""

    code = "WorkerAttributionAmbiguous"


class ValidationAttributionUnknown(DispatcherError):
    """Validation-attributable filesystem change could not be determined."""

    code = "ValidationAttributionUnknown"


class WorkerExitSnapshotMissing(DispatcherError):
    """The durable worker-exit snapshot needed for attribution is absent."""

    code = "WorkerExitSnapshotMissing"


class AttributionClosureViolated(InternalDispatcherError):
    """The final delta is not contained in worker union validation deltas."""

    code = "AttributionClosureViolated"


class EvidenceFreezeViolated(DispatcherError):
    """A validation command changed already-frozen worker evidence."""

    code = "EvidenceFreezeViolated"


class EvidenceIncompleteForReview(DispatcherError):
    """The canonical worker patch omits at least one changed path."""

    code = "EvidenceIncompleteForReview"


class EvidenceExceedsReviewBudget(DispatcherError):
    """The complete canonical worker patch cannot fit the review input budget."""

    code = "EvidenceExceedsReviewBudget"


class ValidationTouchedAdministrativeState(DispatcherError):
    """Validation changed protected repository administrative authority."""

    code = "ValidationTouchedAdministrativeState"


class ValidationTouchedPrimaryTree(DispatcherError):
    """Validation changed the primary working tree."""

    code = "ValidationTouchedPrimaryTree"


class PathIdentityUnrepresentable(DispatcherError):
    """A changed raw path cannot be represented at the public boundary."""

    code = "PathIdentityUnrepresentable"


class InventoryFilesystemUnsupported(GitEvidenceCollectionFailed):
    """The filesystem cannot supply the identity guarantees inventory needs."""

    code = "InventoryFilesystemUnsupported"


class FilesystemSnapshotFailed(DispatcherError):
    """A complete raw filesystem snapshot could not be constructed."""

    code = "FilesystemSnapshotFailed"


class SnapshotBudgetExceeded(DispatcherError):
    """A raw filesystem snapshot exceeded a configured bound."""

    code = "SnapshotBudgetExceeded"


class DiffBudgetExceeded(DispatcherError):
    """Native diff production exceeded its deterministic-work budget."""

    code = "DiffBudgetExceeded"


class CheckoutTransformationBudgetExceeded(DispatcherError):
    """Base-to-worktree reconciliation exceeded its configured budget."""

    code = "CheckoutTransformationBudgetExceeded"


class WorktreeGitfileNotRegular(DispatcherError):
    """A linked-worktree .git authority entry is not a regular file."""

    code = "WorktreeGitfileNotRegular"


class WorktreeGitfileMalformed(DispatcherError):
    """A linked-worktree .git file does not have the exact required shape."""

    code = "WorktreeGitfileMalformed"


class WorktreeGitdirNotDispatcherOwned(DispatcherError):
    """A linked worktree points outside the dispatcher's sealed authority."""

    code = "WorktreeGitdirNotDispatcherOwned"


class WorktreeHeadNotRegular(DispatcherError):
    """The linked-worktree HEAD authority entry is not a regular file."""

    code = "WorktreeHeadNotRegular"


class WorktreeSealSchemaUnsupported(DispatcherError):
    """A persisted worktree authority seal uses an unsupported schema."""

    code = "WorktreeSealSchemaUnsupported"


class RepositoryIdentityUnsealed(DispatcherError):
    """A production path attempted to consume unsealed repository identity."""

    code = "RepositoryIdentityUnsealed"


class SealPinSetStale(DispatcherError):
    """A seal was produced under a Git pin set different from the current set."""

    code = "SealPinSetStale"


class RepositoryRootDrift(DispatcherError):
    """The live repository root no longer matches sealed authority."""

    code = "RepositoryRootDrift"


class GitIdentityDerivationAttempted(InternalDispatcherError):
    """A production Git path attempted a forbidden identity derivation."""

    code = "GitIdentityDerivationAttempted"


class GitArgvPinDisplaced(InternalDispatcherError):
    """A call site displaced the fixed Git pin block from its required position."""

    code = "GitArgvPinDisplaced"


class DispatcherSetupTouchedPrimaryTree(DispatcherError):
    """Dispatcher-owned PREPARE work changed the primary working tree."""

    code = "DispatcherSetupTouchedPrimaryTree"


class HistoryIdentityDerivationDisagreement(DispatcherError):
    """Pinned and unpinned onboarding history walks disagreed."""

    code = "HistoryIdentityDerivationDisagreement"


class AmbiguousRepositoryHistory(DispatcherError):
    """Onboarding found no single repository history identity to approve."""

    code = "AmbiguousRepositoryHistory"


class GitAdministrativeCaptureFailed(DispatcherError):
    """A raw administrative capture was incomplete or unreadable."""

    code = "GitAdministrativeCaptureFailed"


class RefResolutionFailed(DispatcherError):
    """A raw primary-tree ref chain could not be resolved safely."""

    code = "RefResolutionFailed"


class UnsupportedRefStorage(DispatcherError):
    """The repository ref-storage format is unsupported by Wave 0."""

    code = "UnsupportedRefStorage"


class ForbiddenGitInvocation(InternalDispatcherError):
    """Dispatcher code attempted a Git invocation outside the declared order."""

    code = "ForbiddenGitInvocation"


class RunFinalizationFailed(DispatcherError):
    """A worker existed but its run could not be finalized safely."""

    code = "RunFinalizationFailed"


class PhaseRegression(InternalDispatcherError):
    """A ToolExecution attempted to move to an earlier execution phase."""

    code = "PhaseRegression"


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
        "ClaudeProviderLimit",
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
        "ValidationBudgetExceeded",
        "WorktreeCreationFailed",
        "WorktreeBaseMismatch",
        "GitEvidenceCollectionFailed",
        "RecursionDetected",
        "ConfigurationError",
        "ConfigAuthorityViolation",
        "AdminAllowlistPresent",
        "AmbiguousRepositoryHistory",
        "AttributionClosureViolated",
        "BaseBlobUnreadable",
        "BaseCommitAbsent",
        "BaseObjectVerificationFailed",
        "BaseRefNotACommitObject",
        "BaseTreeSnapshotFailed",
        "CheckoutTransformationBudgetExceeded",
        "DispatcherSetupTouchedPrimaryTree",
        "EvidenceFreezeViolated",
        "EvidenceIncompleteForReview",
        "EvidenceExceedsReviewBudget",
        "FilesystemSnapshotFailed",
        "ForbiddenGitInvocation",
        "GitAdministrativeCaptureFailed",
        "GitArgvPinDisplaced",
        "GitBeforeEstablishment",
        "GitIdentityDerivationAttempted",
        "HistoryIdentityDerivationDisagreement",
        "InventoryFilesystemUnsupported",
        "PathIdentityUnrepresentable",
        "PhaseRegression",
        "ProductionBaseRefNotExact",
        "RefResolutionFailed",
        "RepositoryAdministrationUnestablished",
        "RepositoryAdministrationUnreconciled",
        "RepositoryAdministrationUnsupported",
        "RepositoryAuthorityCaptureFailed",
        "RepositoryIdentityUnsealed",
        "RepositoryLayoutUnreadable",
        "RepositoryObjectStoreEntryUnsupported",
        "RepositoryObjectStoreMalformed",
        "RepositoryRootDrift",
        "RunFinalizationFailed",
        "SealAbsentAfterWorker",
        "SealBudgetExceeded",
        "SealIntegrityFailed",
        "SealPinSetStale",
        "SealProvenanceInvalid",
        "SnapshotBudgetExceeded",
        "DiffBudgetExceeded",
        "StoreRoutingUnreadable",
        "UnsupportedObjectFormat",
        "UnsupportedRefStorage",
        "ValidationAttributionUnknown",
        "ValidationTouchedAdministrativeState",
        "ValidationTouchedPrimaryTree",
        "WorkerAttributionAmbiguous",
        "WorkerExitSnapshotMissing",
        "WorktreeGitdirNotDispatcherOwned",
        "WorktreeGitfileMalformed",
        "WorktreeGitfileNotRegular",
        "WorktreeHeadNotRegular",
        "WorktreeIndirectionChanged",
        "WorktreeSealSchemaUnsupported",
    }
)
