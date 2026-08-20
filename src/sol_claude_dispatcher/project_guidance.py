"""Curated project-guidance projection (GATE 4.5 ADDENDUM §1-§20, RULINGS §1-§7).

This module turns *reviewed, hash-pinned* curated projection artifacts into the
project context a worker (or Fable) receives. It is deliberately **not** a
CLAUDE.md loader:

* nothing here reads a ``CLAUDE.md`` or ``AGENTS.md`` and puts it in front of a
  worker. Source instruction files are read for one purpose only — to verify
  that their SHA-256 still matches what was reviewed. The text a worker sees is
  a curated artifact under ``config/guidance/``, not project prose;
* nothing here discovers instruction files. A guidance source is projectable if
  and only if it is an explicit entry in ``config/approved-guidance.json`` whose
  pinned repository-relative path and SHA-256 still match the bytes on disk.
  There is no glob-based "find the nearest CLAUDE.md" walk, and a stale copy
  under ``.claude/worktrees/`` or ``/home/dev/worktrees/`` can never become a
  source merely because it is physically reachable (RULINGS §3);
* nothing here asks a model anything. Scope selection is longest-matching-prefix
  over a source-controlled table (ADDENDUM §6, §10). No runtime summariser, no
  "ask Claude which parts are safe".

The pipeline for every dispatch is fixed (§9 of the Lane B data contract)::

    approval gate                (manifest approval.state == APPROVED)
      -> repository identity     (toplevel + git dir + origin + root commit)
      -> normalise and fence     (allowed_paths -> repo-relative, deny lists)
      -> nearest-scope selection (longest matching prefix, max_subscopes)
      -> approval per scope      (no root-only fallback, RULINGS §7)
      -> source hash verify      (drift and alias divergence fail closed)
      -> artifact hash verify
      -> strict content scan     (SOURCE_DERIVED artifacts ONLY, RULINGS §2)
      -> fixed-order emission

**Provenance separation is load-bearing (RULINGS §2).** Every scope is two
artifacts: a ``DISPATCHER_AUTHORED`` policy file carrying refusal and framing
text, and a ``SOURCE_DERIVED`` file in which every statement traces to an
approved source section. The strict secret/operator classifier runs against the
second and *must never* run against the first — dispatcher refusal text says
"never open a .env file" and "SSH into production is not your authority", so it
matches by design. Running the scanner across the boundary produces pressure to
weaken the regex; :class:`ProvenanceSeparationError` makes that a loud
programming error instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .config import Config
from .errors import (
    ConfigurationError,
    ProjectGuidanceDrift,
    ProjectGuidanceNotApproved,
    ProjectGuidancePolicyViolation,
    ProjectGuidanceProjectionChanged,
    ProjectGuidanceRepositoryMismatch,
    ProjectGuidanceResumeDrift,
    ProjectGuidanceScopeError,
    ProjectGuidanceSourceChanged,
    UnapprovedProjectGuidanceFile,
)
from .models import ProjectGuidanceRecord

__all__ = [
    "MANIFEST_KIND",
    "MANIFEST_SCHEMA_VERSION",
    "APPROVED_STATE",
    "SOURCE_DERIVED",
    "DISPATCHER_AUTHORED",
    "PROJECTABLE_WORKER_CLASSIFICATIONS",
    "PROJECTABLE_REVIEW_CLASSIFICATIONS",
    "REFUSED_CLASSIFICATIONS",
    "MANDATORY_DENY_PREFIXES",
    "MANDATORY_DENY_ABSOLUTE_TREES",
    "MANDATORY_DISCOVERY_EXCLUDES",
    "FINGERPRINT_SPEC",
    "TOKEN_BYTES",
    "estimate_tokens",
    "GuidanceAudience",
    "RepositoryIdentity",
    "GuidanceSource",
    "GuidanceArtifact",
    "GuidanceEntry",
    "ScopeMapEntry",
    "ScopeMap",
    "RepositoryPin",
    "GraphRefreshGate",
    "GuidanceManifest",
    "load_manifest",
    "load_manifest_from_mapping",
    "ScanHit",
    "ProvenanceSeparationError",
    "StrictContentScanner",
    "GuidanceSelection",
    "ProjectedGuidanceArtifact",
    "ProjectedScope",
    "ProjectGuidanceProjection",
    "GuidanceAuditRow",
    "ProjectGuidanceEngine",
]

MANIFEST_KIND = "project-guidance"
MANIFEST_SCHEMA_VERSION = "1.0.0"
APPROVED_STATE = "APPROVED"

#: RULINGS §2. The two provenance domains that must never be mixed before
#: classification.
SOURCE_DERIVED = "SOURCE_DERIVED"
DISPATCHER_AUTHORED = "DISPATCHER_AUTHORED"

#: Only these reach a worker prompt.
PROJECTABLE_WORKER_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"CURATED_ROOT", "CURATED_SUBPROJECT"}
)
#: Only these reach Fable (ADDENDUM §15). Disjoint from the worker set.
PROJECTABLE_REVIEW_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"CURATED_ROOT_REVIEW", "CURATED_SUBPROJECT_REVIEW"}
)
#: Present in the manifest for audit, never projected. ``CLASSIFIED_NOT_APPROVED``
#: is a scope whose instruction files exist but were never reviewed (RULINGS §7);
#: ``EXCLUDED_FOREIGN_REPO`` is the nested Taskforce_AI_Website git repository
#: (ADDENDUM §1C), which is not part of full-voice-agent's git identity.
REFUSED_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"CLASSIFIED_NOT_APPROVED", "EXCLUDED_FOREIGN_REPO"}
)
KNOWN_CLASSIFICATIONS: frozenset[str] = (
    PROJECTABLE_WORKER_CLASSIFICATIONS
    | PROJECTABLE_REVIEW_CLASSIFICATIONS
    | REFUSED_CLASSIFICATIONS
)

#: RULINGS §3, encoded in code as well as in the manifest. A manifest that drops
#: one of these is refused at load time, so emptying the manifest list turns the
#: regression tests red instead of quietly allowing a shadow worktree tree back
#: into scope. Repository-relative.
MANDATORY_DENY_PREFIXES: tuple[str, ...] = (
    ".claude/worktrees/",
    "Taskforce_AI_Website/",
)
#: Absolute trees that may never be relativised into the pinned repository, even
#: if a symlink or a bind mount makes them look reachable.
MANDATORY_DENY_ABSOLUTE_TREES: tuple[str, ...] = ("/home/dev/worktrees/",)
#: The DEFAULT-DENY verification scan must always skip these; a stale worktree
#: copy is a *hazard*, not an unreviewed new instruction file to report.
MANDATORY_DISCOVERY_EXCLUDES: tuple[str, ...] = (
    ".claude/worktrees/**",
    "/home/dev/worktrees/**",
)

#: The fingerprint recipe, copied verbatim from the reviewed manifest. Loading a
#: manifest whose ``resume_fingerprint.spec`` differs fails closed: a changed
#: recipe must not masquerade as an unchanged context.
FINGERPRINT_SPEC = (
    "sha256( join('\\n', [ logical_id + ':' + joined_source_hashes + ':' + "
    "source_artifact_sha256 + ':' + policy_artifact_sha256 for each emitted "
    "entry, in emission order ]) + '|graph:' + graph_variant + '|envelope:' + "
    "task_envelope_id )"
)
#: Used when there is no graph clause at all (Fable review projections carry
#: none). A literal so the value is stable and reviewable.
NO_GRAPH_VARIANT = "NONE"

#: Bytes per token. ADDENDUM §20 budgets are recorded as ``round(bytes / 4)``,
#: which is *not* the floor division ``skills.estimate_tokens`` uses; the two
#: budgets were measured separately and neither is retro-fitted to the other.
TOKEN_BYTES = 4

#: Characters that make a path segment a glob rather than a literal directory.
_GLOB_CHARS = "*?["

#: RULINGS §2: patterns 1-6 of ``strict_secret_operator_v1`` are case-insensitive
#: and pattern 7 is case-sensitive (``Bearer `` in prose is not a credential).
_DEFAULT_CASE_SENSITIVE_PATTERN_INDICES: tuple[int, ...] = (6,)


def estimate_tokens(n_bytes: int) -> int:
    """Approximate token count for ``n_bytes`` of curated guidance."""
    return round(n_bytes / TOKEN_BYTES)


class GuidanceAudience(str, Enum):
    """Who the projection is for. The two artifact sets are disjoint (§15)."""

    WORKER = "worker"
    FABLE_REVIEW = "fable_review"


@dataclass(frozen=True)
class RepositoryIdentity:
    """Measured identity of the repository a task is dispatched against.

    All four fields are supplied by the caller (the dispatcher already runs git
    to collect evidence; this module runs no subprocess). ``root_commit`` is
    what makes the check resistant to a path swap: the nested
    ``Taskforce_AI_Website`` repository has its own root commit and cannot
    satisfy full-voice-agent's (ADDENDUM §1C, RULINGS §4).
    """

    toplevel: str
    git_dir: str
    origin_url: str
    root_commit: str


# ---------------------------------------------------------------------------
# Manifest schema (ADDENDUM §9)
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Lenient(BaseModel):
    """For documentation-only sub-objects whose keys vary per entry."""

    model_config = ConfigDict(extra="allow", frozen=True)


class GuidanceSource(_Strict):
    """One pinned instruction source. Read only to verify its hash."""

    source_path: str = Field(min_length=1)
    resolved_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)
    alias_of: str | None = None


class GuidanceArtifact(_Strict):
    """One curated projection artifact, pinned by hash and provenance class."""

    path: str = Field(min_length=1)
    provenance_class: Literal["SOURCE_DERIVED", "DISPATCHER_AUTHORED"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    #: ``None`` for the graph-refresh clause, which the manifest pins by hash
    #: alone. The hash is the load-bearing check; the size is a cross-check.
    bytes: int | None = Field(default=None, ge=0)
    approx_tokens: int | None = None


class GuidanceEntry(_Strict):
    """One approved logical guidance source (ADDENDUM §9)."""

    repository_id: str = Field(min_length=1)
    logical_id: str = Field(min_length=1)
    audience: Literal["worker", "fable_review", "none"]
    scope_prefix: str | None
    classification: str
    sources: tuple[GuidanceSource, ...]
    source_artifact: GuidanceArtifact | None = None
    policy_artifact: GuidanceArtifact | None = None
    source_relationship: str | None = None
    flags: tuple[str, ...] = ()
    approval_state: str | None = None
    on_selection: str | None = None
    fallback_to_root_only: bool | None = None
    # Documentation-only fields. Reviewed with the manifest, never load-bearing
    # at runtime — the engine must not start behaving differently because a
    # prose note changed.
    scope_note: str | None = None
    source_relationship_note: str | None = None
    carries_behavioural_configuration: bool | None = None
    behavioural_framing_present_in_policy_artifact: bool | None = None
    included_sections: Any = None
    excluded: Mapping[str, Any] | None = None
    review_independence: Mapping[str, Any] | None = None
    evidence: Mapping[str, Any] | None = None
    risk_note: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "GuidanceEntry":
        if self.classification not in KNOWN_CLASSIFICATIONS:
            raise ValueError(
                f"entry {self.logical_id!r}: unknown classification "
                f"{self.classification!r}; known: {sorted(KNOWN_CLASSIFICATIONS)}"
            )
        projectable = self.classification not in REFUSED_CLASSIFICATIONS
        if projectable and (self.source_artifact is None or self.policy_artifact is None):
            raise ValueError(
                f"entry {self.logical_id!r} is {self.classification} but is missing a "
                "source_artifact or policy_artifact; a projectable scope is always "
                "two files (RULINGS §2)"
            )
        if not projectable and (
            self.source_artifact is not None or self.policy_artifact is not None
        ):
            raise ValueError(
                f"entry {self.logical_id!r} is {self.classification} and must carry no "
                "projection artifact"
            )
        if self.source_artifact is not None:
            if self.source_artifact.provenance_class != SOURCE_DERIVED:
                raise ValueError(
                    f"entry {self.logical_id!r}: source_artifact must be "
                    f"{SOURCE_DERIVED}, got {self.source_artifact.provenance_class!r}"
                )
        if self.policy_artifact is not None:
            if self.policy_artifact.provenance_class != DISPATCHER_AUTHORED:
                raise ValueError(
                    f"entry {self.logical_id!r}: policy_artifact must be "
                    f"{DISPATCHER_AUTHORED}, got "
                    f"{self.policy_artifact.provenance_class!r}"
                )
        if self.source_relationship == "ALIASES_BYTE_IDENTICAL":
            if len({s.sha256 for s in self.sources}) != 1:
                raise ValueError(
                    f"entry {self.logical_id!r} declares ALIASES_BYTE_IDENTICAL but "
                    "pins more than one distinct source hash"
                )
        if not self.sources:
            raise ValueError(f"entry {self.logical_id!r} pins no source")
        return self

    @property
    def is_worker(self) -> bool:
        return self.classification in PROJECTABLE_WORKER_CLASSIFICATIONS

    @property
    def is_review(self) -> bool:
        return self.classification in PROJECTABLE_REVIEW_CLASSIFICATIONS


class ScopeMapEntry(_Strict):
    """One deterministic scope prefix (ADDENDUM §6). Ordered, source-controlled."""

    scope_prefix: str = Field(min_length=1)
    worker_entry: str = Field(min_length=1)
    review_entry: str | None = None
    approved: bool

    @model_validator(mode="after")
    def _trailing_slash(self) -> "ScopeMapEntry":
        if not self.scope_prefix.endswith("/"):
            raise ValueError(
                f"scope_prefix {self.scope_prefix!r} must end with '/' so prefix "
                "matching is path-segment aware"
            )
        return self


class UnapprovedScopeBehaviour(_Strict):
    typed_error: Literal["ProjectGuidanceNotApproved"]
    fallback_to_root_only: Literal[False]
    rule: str
    operator_text_artifact: str
    operator_text_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operator_text_provenance_class: Literal["DISPATCHER_AUTHORED"]


class ScopeMap(_Strict):
    note: str | None = None
    match_rule: str
    root_is_unconditional: Literal[True]
    max_subscopes: int = Field(ge=1)
    entries: tuple[ScopeMapEntry, ...]
    unapproved_scope_behaviour: UnapprovedScopeBehaviour

    @model_validator(mode="after")
    def _unique(self) -> "ScopeMap":
        prefixes = [e.scope_prefix for e in self.entries]
        if len(prefixes) != len(set(prefixes)):
            raise ValueError("duplicate scope_prefix in scope_map.entries")
        return self


class SourceResolution(_Strict):
    mode: Literal["MANIFEST_PINNED_EXACT_PATHS_ONLY"]
    rule: str
    flow: tuple[str, ...]


class UnapprovedFileDiscovery(_Strict):
    purpose: str
    globs: tuple[str, ...]
    excludes: tuple[str, ...]
    known_foreign_files: tuple[str, ...] = ()
    unlisted_file_policy: str


class ShadowSourceHazard(_Lenient):
    """Measured evidence that the hazard is real. Data for the regression test."""


class RepositoryPin(_Strict):
    repository_id: str = Field(min_length=1)
    display_name: str | None = None
    toplevel: str = Field(min_length=1)
    git_dir: str = Field(min_length=1)
    origin_url: str = Field(min_length=1)
    root_commit: str = Field(min_length=7)
    measured_head_at_authoring: str | None = None
    identity_check: str | None = None
    source_resolution: SourceResolution
    deny_prefixes: tuple[str, ...]
    deny_absolute_trees: tuple[str, ...]
    shadow_source_hazard: ShadowSourceHazard | None = None
    unapproved_file_discovery: UnapprovedFileDiscovery

    @model_validator(mode="after")
    def _mandatory_denies(self) -> "RepositoryPin":
        missing = [p for p in MANDATORY_DENY_PREFIXES if p not in self.deny_prefixes]
        if missing:
            raise ValueError(
                f"repository {self.repository_id!r}: deny_prefixes is missing "
                f"{missing}; RULINGS §3 makes these non-negotiable"
            )
        missing_abs = [
            p for p in MANDATORY_DENY_ABSOLUTE_TREES if p not in self.deny_absolute_trees
        ]
        if missing_abs:
            raise ValueError(
                f"repository {self.repository_id!r}: deny_absolute_trees is missing "
                f"{missing_abs}; RULINGS §3 makes these non-negotiable"
            )
        missing_ex = [
            p
            for p in MANDATORY_DISCOVERY_EXCLUDES
            if p not in self.unapproved_file_discovery.excludes
        ]
        if missing_ex:
            raise ValueError(
                f"repository {self.repository_id!r}: unapproved_file_discovery."
                f"excludes is missing {missing_ex}; RULINGS §3 makes these "
                "non-negotiable"
            )
        return self


class GraphVariant(_Strict):
    variant: Literal["GATED_ON", "GATED_OFF"]
    artifact: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance_class: Literal["DISPATCHER_AUTHORED"]


class GraphRefreshGate(_Strict):
    """ADDENDUM §5. Set membership on allowed_paths — no model decides."""

    ruling: str | None = None
    selector: str | None = None
    gate_prefix: str = Field(min_length=1)
    on_match: GraphVariant
    default: GraphVariant
    read_only_exploration: str | None = None
    worker_report_token: str | None = None

    @model_validator(mode="after")
    def _prefix(self) -> "GraphRefreshGate":
        if not self.gate_prefix.endswith("/"):
            raise ValueError("graph_refresh_gate.gate_prefix must end with '/'")
        return self


class Emission(_Strict):
    note: str | None = None
    order: tuple[str, ...]
    worker_and_review_are_disjoint: str | None = None


class Approval(_Strict):
    version: str = Field(min_length=1)
    date: str | None = None
    state: str = Field(min_length=1)
    note: str | None = None


class ProvenanceClassSpec(_Lenient):
    pass


class StrictPatternSet(_Strict):
    note: str | None = None
    patterns: tuple[str, ...]
    last_run: Mapping[str, Any] | None = None

    @model_validator(mode="after")
    def _nonempty(self) -> "StrictPatternSet":
        if not self.patterns:
            raise ValueError(
                "strict_secret_operator_v1.patterns must not be empty; RULINGS §2 "
                "forbids weakening the classifier, and an empty set is the limit "
                "case of weakening it"
            )
        return self


class ResumeFingerprintSpec(_Strict):
    spec: str
    note: str | None = None

    @model_validator(mode="after")
    def _pinned(self) -> "ResumeFingerprintSpec":
        if self.spec != FINGERPRINT_SPEC:
            raise ValueError(
                "resume_fingerprint.spec does not match the recipe this engine "
                "implements; a changed recipe must not masquerade as an unchanged "
                "context (ADDENDUM §16)"
            )
        return self


class GuidanceManifest(_Strict):
    """The dispatcher-owned project-guidance manifest. Read-only, reviewed."""

    schema_version: Literal["1.0.0"]
    manifest_kind: Literal["project-guidance"]
    generated: str | None = None
    authored_by: str | None = None
    governing_documents: tuple[str, ...] = ()
    approval: Approval
    provenance_classes: Mapping[str, ProvenanceClassSpec]
    strict_secret_operator_v1: StrictPatternSet
    behavioural_configuration_policy: Mapping[str, Any] | None = None
    repositories: tuple[RepositoryPin, ...]
    root_entry: str
    root_review_entry: str
    scope_map: ScopeMap
    graph_refresh_gate: GraphRefreshGate
    emission: Emission
    entries: Mapping[str, GuidanceEntry]
    failure_semantics: tuple[Mapping[str, Any], ...] = ()
    resume_fingerprint: ResumeFingerprintSpec
    worked_scope_outcomes: tuple[Mapping[str, Any], ...] = ()
    dispatch_size_budget: Mapping[str, Any] = Field(default_factory=dict)
    source_path: str | None = None

    @model_validator(mode="after")
    def _coherent(self) -> "GuidanceManifest":
        if not self.repositories:
            raise ValueError("manifest pins no repository")
        known_repos = {r.repository_id for r in self.repositories}

        for logical_id, entry in self.entries.items():
            if logical_id != entry.logical_id:
                raise ValueError(
                    f"entries key {logical_id!r} != logical_id {entry.logical_id!r}"
                )
            if (
                entry.repository_id not in known_repos
                and entry.classification != "EXCLUDED_FOREIGN_REPO"
            ):
                raise ValueError(
                    f"entry {logical_id!r} names unknown repository "
                    f"{entry.repository_id!r}"
                )
            if entry.repository_id in known_repos:
                pin = self.repository(entry.repository_id)
                for source in entry.sources:
                    expected = str(PurePosixPath(pin.toplevel) / source.source_path)
                    if source.resolved_path != expected:
                        raise ValueError(
                            f"entry {logical_id!r}: source {source.source_path!r} "
                            f"resolves to {source.resolved_path!r}, not {expected!r}; "
                            "sources are toplevel + exact repo-relative path only "
                            "(RULINGS §3)"
                        )

        for name, required_audience, required_classification in (
            ("root_entry", "worker", "CURATED_ROOT"),
            ("root_review_entry", "fable_review", "CURATED_ROOT_REVIEW"),
        ):
            logical_id = getattr(self, name)
            entry = self.entries.get(logical_id)
            if entry is None:
                raise ValueError(f"{name} names unknown entry {logical_id!r}")
            if entry.audience != required_audience:
                raise ValueError(
                    f"{name} {logical_id!r} has audience {entry.audience!r}, "
                    f"expected {required_audience!r}"
                )
            if entry.classification != required_classification:
                raise ValueError(
                    f"{name} {logical_id!r} has classification "
                    f"{entry.classification!r}, expected {required_classification!r}"
                )
            if entry.scope_prefix != "":
                raise ValueError(f"{name} {logical_id!r} must have an empty scope_prefix")

        for scope in self.scope_map.entries:
            worker = self.entries.get(scope.worker_entry)
            if worker is None:
                raise ValueError(
                    f"scope {scope.scope_prefix!r} names unknown worker entry "
                    f"{scope.worker_entry!r}"
                )
            if worker.scope_prefix != scope.scope_prefix:
                raise ValueError(
                    f"scope {scope.scope_prefix!r} names {scope.worker_entry!r}, whose "
                    f"scope_prefix is {worker.scope_prefix!r}"
                )
            if worker.audience != "worker":
                raise ValueError(
                    f"scope {scope.scope_prefix!r} worker entry has audience "
                    f"{worker.audience!r}"
                )
            if scope.approved != worker.is_worker:
                raise ValueError(
                    f"scope {scope.scope_prefix!r}: approved={scope.approved} "
                    f"disagrees with classification {worker.classification!r}"
                )
            if scope.review_entry is not None:
                review = self.entries.get(scope.review_entry)
                if review is None:
                    raise ValueError(
                        f"scope {scope.scope_prefix!r} names unknown review entry "
                        f"{scope.review_entry!r}"
                    )
                if review.scope_prefix != scope.scope_prefix:
                    raise ValueError(
                        f"scope {scope.scope_prefix!r} review entry has scope_prefix "
                        f"{review.scope_prefix!r}"
                    )
                if not review.is_review:
                    raise ValueError(
                        f"scope {scope.scope_prefix!r} review entry "
                        f"{scope.review_entry!r} is not a review classification"
                    )
        return self

    # -- helpers ---------------------------------------------------------

    def repository(self, repository_id: str) -> RepositoryPin:
        for pin in self.repositories:
            if pin.repository_id == repository_id:
                return pin
        raise KeyError(repository_id)

    @property
    def primary_repository(self) -> RepositoryPin:
        return self.repositories[0]

    def scope_for(self, prefix: str) -> ScopeMapEntry:
        for scope in self.scope_map.entries:
            if scope.scope_prefix == prefix:
                return scope
        raise KeyError(prefix)

    @property
    def is_approved(self) -> bool:
        return self.approval.state == APPROVED_STATE


def load_manifest_from_mapping(
    data: Mapping[str, Any], *, source_path: str | None = None
) -> GuidanceManifest:
    """Validate an already-parsed manifest mapping. Fails closed."""
    if not isinstance(data, Mapping):
        raise ConfigurationError(
            "Project-guidance manifest root must be an object.",
            details={"got": type(data).__name__},
        )
    payload = dict(data)
    payload["source_path"] = source_path
    try:
        return GuidanceManifest(**payload)
    except ValidationError as exc:
        raise ConfigurationError(
            "Project-guidance manifest is invalid.",
            details={
                "source": source_path,
                "issues": [
                    {
                        "location": ".".join(str(p) for p in err["loc"]),
                        "problem": err["msg"],
                    }
                    for err in exc.errors()
                ],
            },
            remediation="The manifest is reviewed and source-controlled; fix it by "
            "review, never by regenerating it from whatever is on disk.",
        ) from exc


def load_manifest(path: str | Path) -> GuidanceManifest:
    """Load ``config/approved-guidance.json``. Never writes, never repairs."""
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise ConfigurationError(
            "Project-guidance manifest not found.",
            details={"path": str(manifest_path)},
            remediation="Point [project_guidance].manifest_path at the reviewed "
            "manifest, or disable [project_guidance].enabled.",
        )
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise ConfigurationError(
            "Project-guidance manifest could not be read.",
            details={"path": str(manifest_path), "reason": exc.strerror},
        ) from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            "Project-guidance manifest is not valid UTF-8 JSON.",
            details={"path": str(manifest_path), "reason": str(exc)},
        ) from exc
    return load_manifest_from_mapping(data, source_path=str(manifest_path.resolve()))


# ---------------------------------------------------------------------------
# Strict content classification (RULINGS §2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScanHit:
    """One strict-classifier match."""

    pattern: str
    matched: str
    line_number: int
    line: str


class ProvenanceSeparationError(ValueError):
    """The strict classifier was pointed at DISPATCHER_AUTHORED text.

    This is a *programming* error in the engine, not a dispatcher error Sol can
    act on, so it is deliberately not a :class:`DispatcherError`. RULINGS §2:
    dispatcher refusal text ("never open a .env file", "SSH into production is
    not your authority") matches the classifier by design. Scanning it produces
    a false positive whose only available "fix" is weakening the regex — which
    is forbidden. The correct fix is to never cross the provenance boundary.
    """


class StrictContentScanner:
    """``strict_secret_operator_v1``. Applied to SOURCE_DERIVED content only."""

    def __init__(
        self,
        patterns: Sequence[str],
        *,
        case_sensitive_indices: Sequence[int] = _DEFAULT_CASE_SENSITIVE_PATTERN_INDICES,
    ) -> None:
        if not patterns:
            raise ValueError(
                "the strict classifier must carry at least one pattern; an empty "
                "pattern set is the limit case of weakening it (RULINGS §2)"
            )
        self.patterns: tuple[str, ...] = tuple(patterns)
        sensitive = set(case_sensitive_indices)
        self._compiled: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
            (pattern, re.compile(pattern, 0 if index in sensitive else re.IGNORECASE))
            for index, pattern in enumerate(self.patterns)
        )

    def scan_text(self, text: str) -> tuple[ScanHit, ...]:
        """Apply every pattern. No provenance guard — audit/diagnostic use only.

        Callers on the projection path must use :meth:`scan_artifact`, which
        refuses to cross the provenance boundary.
        """
        hits: list[ScanHit] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern, compiled in self._compiled:
                match = compiled.search(line)
                if match is not None:
                    hits.append(
                        ScanHit(
                            pattern=pattern,
                            matched=match.group(0),
                            line_number=line_number,
                            line=line.strip(),
                        )
                    )
        return tuple(hits)

    def scan_artifact(
        self, path: str, text: str, *, provenance_class: str
    ) -> tuple[ScanHit, ...]:
        """Scan a SOURCE_DERIVED artifact. Refuses any other provenance class."""
        if provenance_class != SOURCE_DERIVED:
            raise ProvenanceSeparationError(
                f"refusing to run the strict content classifier against {path!r}, "
                f"whose provenance class is {provenance_class!r}. RULINGS §2: "
                f"only {SOURCE_DERIVED} content is classified by content; "
                f"{DISPATCHER_AUTHORED} policy text is trusted by its own hash and "
                "review, and scanning it matches the refusal blocks by design."
            )
        return self.scan_text(text)


# ---------------------------------------------------------------------------
# Projection results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GuidanceSelection:
    """The deterministic outcome of scope selection. Data, not a decision."""

    relative_paths: tuple[str, ...]
    scope_prefixes: tuple[str, ...]
    logical_ids: tuple[str, ...]
    graph_variant: str | None


@dataclass(frozen=True)
class ProjectedGuidanceArtifact:
    """One verified curated artifact, in emission order."""

    logical_id: str
    path: str
    provenance_class: str
    sha256: str
    nbytes: int
    text: str


@dataclass(frozen=True)
class ProjectedScope:
    """One selected scope: its provenance and its two artifacts."""

    logical_id: str
    scope_prefix: str
    classification: str
    source_relationship: str | None
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    policy: ProjectedGuidanceArtifact
    source: ProjectedGuidanceArtifact


@dataclass(frozen=True)
class ProjectGuidanceProjection:
    """The complete, verified project context for one dispatch or resume."""

    manifest_schema_version: str
    approval_version: str
    audience: str
    repository_id: str
    logical_ids: tuple[str, ...]
    scope_prefixes: tuple[str, ...]
    scopes: tuple[ProjectedScope, ...]
    artifacts: tuple[ProjectedGuidanceArtifact, ...]
    graph_variant: str | None
    text: str
    projected_bytes: int
    approx_tokens: int
    fingerprint: str
    task_envelope_id: str
    scanned_artifacts: tuple[str, ...]
    exempt_artifacts: tuple[str, ...]
    mode: Literal["projected", "disabled"] = "projected"

    @property
    def artifact_paths(self) -> tuple[str, ...]:
        return tuple(a.path for a in self.artifacts)

    def to_record(self) -> ProjectGuidanceRecord:
        """The persisted evidence stored at dispatch (ADDENDUM §16)."""
        return ProjectGuidanceRecord(
            mode=self.mode,
            manifest_schema_version=self.manifest_schema_version,
            approval_version=self.approval_version,
            audience=self.audience,
            repository_id=self.repository_id,
            logical_ids=list(self.logical_ids),
            graph_variant=self.graph_variant or NO_GRAPH_VARIANT,
            task_envelope_id=self.task_envelope_id,
            fingerprint=self.fingerprint,
            projected_bytes=self.projected_bytes,
            approx_tokens=self.approx_tokens,
        )


@dataclass(frozen=True)
class GuidanceAuditRow:
    """One row of the read-only drift report. Never approves, never writes."""

    logical_id: str
    kind: Literal["source", "artifact"]
    path: str
    approved_sha256: str
    current_sha256: str | None
    status: Literal["MATCH", "DRIFT", "MISSING"]
    detail: str = ""


# ---------------------------------------------------------------------------
# Path fencing helpers (pure path math; no filesystem access)
# ---------------------------------------------------------------------------


def _literal_prefix(pattern: str) -> tuple[str, bool]:
    """Strip glob segments from an ``allowed_paths`` entry.

    ``"Kavya/**"`` -> ``("Kavya", True)``; ``"Kavya/server.py"`` ->
    ``("Kavya/server.py", False)``. The boolean says whether the result is a
    directory prefix (something was stripped), which decides whether a trailing
    ``/`` is appended before prefix matching. Deterministic string work: no
    filesystem, no expansion.
    """
    parts = [p for p in pattern.split("/") if p not in ("", ".")]
    literal: list[str] = []
    truncated = False
    for part in parts:
        if any(ch in part for ch in _GLOB_CHARS):
            truncated = True
            break
        literal.append(part)
    return "/".join(literal), truncated


def _normalise_relative(rel: str) -> str | None:
    """Collapse ``.`` and ``..``. Returns ``None`` if it escapes the root."""
    out: list[str] = []
    for part in rel.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not out:
                return None
            out.pop()
            continue
        out.append(part)
    return "/".join(out)


def _scope_matches(rel: str, prefix: str) -> bool:
    """``rel == rstrip(prefix,'/')`` or ``rel.startswith(prefix)`` (manifest rule).

    ``prefix`` always ends with ``/``, so ``Kavya-notes/x`` does not match
    ``Kavya/`` — segment safety comes for free.
    """
    return rel == prefix.rstrip("/") or rel.startswith(prefix)


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class ProjectGuidanceEngine:
    """Deterministic, manifest-driven project-guidance projection."""

    def __init__(
        self,
        manifest: GuidanceManifest,
        *,
        project_root: str | Path,
        max_projected_bytes: int,
        enabled: bool = True,
    ) -> None:
        if max_projected_bytes < 1:
            raise ConfigurationError(
                "max_projected_bytes must be positive.",
                details={"max_projected_bytes": max_projected_bytes},
            )
        self.manifest = manifest
        # Resolved, because ``config.project_root`` legitimately defaults to
        # ``"."``. The audit compares a path against its own realpath to detect
        # a symlinked artifact, and a relative root would make every row look
        # like drift.
        self.project_root = Path(project_root).resolve()
        self.max_projected_bytes = max_projected_bytes
        self.enabled = enabled
        self.scanner = StrictContentScanner(manifest.strict_secret_operator_v1.patterns)

    # -- construction ----------------------------------------------------

    @classmethod
    def from_config(cls, config: Config) -> "ProjectGuidanceEngine":
        """Build from dispatcher config. The manifest is never rewritten."""
        manifest = load_manifest(config.approved_guidance_file)
        return cls(
            manifest,
            project_root=config.project_root,
            max_projected_bytes=config.project_guidance.max_projected_bytes,
            enabled=config.project_guidance.enabled,
        )

    # -- scope fencing and selection (ADDENDUM §6, RULINGS §3) -----------

    def relativise(
        self, allowed_paths: Sequence[str], *, repository: RepositoryIdentity
    ) -> tuple[str, ...]:
        """``allowed_paths`` -> repository-relative literal prefixes, fenced.

        Fails closed on anything outside the pinned toplevel, anything that
        escapes after normalisation, and anything under a deny prefix or deny
        absolute tree. Pure path math — nothing on disk is consulted, because an
        ``allowed_paths`` entry legitimately names a file that does not exist
        yet.
        """
        pin = self.manifest.primary_repository
        toplevel = pin.toplevel.rstrip("/")
        deny_prefixes = tuple(pin.deny_prefixes) + MANDATORY_DENY_PREFIXES
        deny_trees = tuple(pin.deny_absolute_trees) + MANDATORY_DENY_ABSOLUTE_TREES

        out: list[str] = []
        for raw in allowed_paths:
            literal, _ = _literal_prefix(raw)
            candidate = raw.strip()

            if candidate.startswith("/"):
                for tree in deny_trees:
                    if candidate == tree.rstrip("/") or candidate.startswith(tree):
                        raise self._scope_error(
                            "An allowed path lands under a denied absolute tree.",
                            allowed_path=raw,
                            denied_by=tree,
                        )
                absolute_literal, _ = _literal_prefix(candidate)
                absolute_literal = "/" + absolute_literal
                if absolute_literal != toplevel and not absolute_literal.startswith(
                    toplevel + "/"
                ):
                    raise self._scope_error(
                        "An allowed path resolves outside the pinned repository "
                        "toplevel.",
                        allowed_path=raw,
                        denied_by="outside_pinned_toplevel",
                    )
                literal = absolute_literal[len(toplevel) :].lstrip("/")

            normalised = _normalise_relative(literal)
            if normalised is None:
                raise self._scope_error(
                    "An allowed path escapes the repository after normalisation.",
                    allowed_path=raw,
                    denied_by="path_escape",
                )
            for prefix in deny_prefixes:
                if normalised == prefix.rstrip("/") or normalised.startswith(prefix):
                    raise self._scope_error(
                        "An allowed path lands under a denied repository prefix.",
                        allowed_path=raw,
                        denied_by=prefix,
                    )
            if normalised not in out:
                out.append(normalised)
        return tuple(out)

    def select(
        self,
        allowed_paths: Sequence[str],
        *,
        repository: RepositoryIdentity,
        audience: GuidanceAudience = GuidanceAudience.WORKER,
    ) -> GuidanceSelection:
        """Nearest-scope selection. Longest matching prefix, no glob, no model."""
        self._assert_repository(repository)
        relative = self.relativise(allowed_paths, repository=repository)

        matched: list[ScopeMapEntry] = []
        for rel in relative:
            best: ScopeMapEntry | None = None
            for scope in self.manifest.scope_map.entries:
                if _scope_matches(rel, scope.scope_prefix):
                    if best is None or len(scope.scope_prefix) > len(best.scope_prefix):
                        best = scope
            if best is not None and best not in matched:
                matched.append(best)

        # Manifest declaration order, so the projection is order-independent of
        # however the envelope happened to list its paths.
        order = {s.scope_prefix: i for i, s in enumerate(self.manifest.scope_map.entries)}
        matched.sort(key=lambda s: order[s.scope_prefix])

        limit = self.manifest.scope_map.max_subscopes
        if len(matched) > limit:
            raise self._scope_error(
                "The task's allowed paths intersect more subprojects than the "
                "project-guidance policy permits.",
                allowed_path=None,
                denied_by="max_subscopes",
                extra={
                    "max_subscopes": limit,
                    "selected_scope_prefixes": [s.scope_prefix for s in matched],
                },
                remediation="Narrow the envelope. A task spanning this many "
                "subprojects carries every subproject's domain invariants into one "
                "worker prompt, which is exactly what ADDENDUM §6 refuses.",
            )

        logical_ids = [
            self.manifest.root_entry
            if audience is GuidanceAudience.WORKER
            else self.manifest.root_review_entry
        ]
        for scope in matched:
            logical_ids.append(self._entry_id_for(scope, audience))

        graph_variant: str | None = None
        if audience is GuidanceAudience.WORKER:
            gate = self.manifest.graph_refresh_gate
            authorised = any(
                _scope_matches(rel, gate.gate_prefix) for rel in relative
            )
            graph_variant = (
                gate.on_match.variant if authorised else gate.default.variant
            )

        return GuidanceSelection(
            relative_paths=relative,
            scope_prefixes=tuple(s.scope_prefix for s in matched),
            logical_ids=tuple(logical_ids),
            graph_variant=graph_variant,
        )

    # -- projection ------------------------------------------------------

    def project(
        self,
        allowed_paths: Sequence[str],
        *,
        repository: RepositoryIdentity,
        task_envelope_id: str,
        audience: GuidanceAudience = GuidanceAudience.WORKER,
    ) -> ProjectGuidanceProjection:
        """Select, verify and render the project context for one dispatch."""
        if not self.enabled:
            return self._disabled(audience, task_envelope_id)
        self._assert_approved()
        selection = self.select(
            allowed_paths, repository=repository, audience=audience
        )
        return self._project_ids(
            selection.logical_ids,
            repository=repository,
            audience=audience,
            graph_variant=selection.graph_variant,
            task_envelope_id=task_envelope_id,
            scope_prefixes=selection.scope_prefixes,
        )

    def verify(
        self, record: ProjectGuidanceRecord, *, repository: RepositoryIdentity
    ) -> ProjectGuidanceProjection:
        """Re-verify a persisted context on resume. Drift fails closed (§16)."""
        if record.mode == "disabled":
            return self._disabled(
                GuidanceAudience(record.audience), record.task_envelope_id
            )
        self._assert_approved()
        audience = GuidanceAudience(record.audience)
        graph_variant = (
            None if record.graph_variant == NO_GRAPH_VARIANT else record.graph_variant
        )
        projection = self._project_ids(
            tuple(record.logical_ids),
            repository=repository,
            audience=audience,
            graph_variant=graph_variant,
            task_envelope_id=record.task_envelope_id,
            scope_prefixes=None,
        )
        if projection.fingerprint != record.fingerprint:
            raise ProjectGuidanceResumeDrift(
                "The approved project guidance changed since this task was "
                "dispatched.",
                details={
                    "expected_fingerprint": record.fingerprint,
                    "actual_fingerprint": projection.fingerprint,
                    "recorded_approval_version": record.approval_version,
                    "current_approval_version": self.manifest.approval.version,
                    "logical_ids": list(record.logical_ids),
                },
                remediation="Return the task to Sol. A resume must not silently "
                "adopt a re-approved projection or a changed instruction source "
                "(ADDENDUM §16).",
            )
        return projection

    # -- read-only drift audit -------------------------------------------

    def audit(self) -> tuple[GuidanceAuditRow, ...]:
        """Report approved vs current state for every pinned file."""
        rows: list[GuidanceAuditRow] = []
        seen: set[tuple[str, str]] = set()
        for entry in self.manifest.entries.values():
            for source in entry.sources:
                key = ("source", source.resolved_path)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    self._audit_row(
                        entry.logical_id,
                        "source",
                        Path(source.resolved_path),
                        source.sha256,
                    )
                )
            for artifact in (entry.policy_artifact, entry.source_artifact):
                if artifact is None:
                    continue
                key = ("artifact", artifact.path)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    self._audit_row(
                        entry.logical_id,
                        "artifact",
                        self.project_root / artifact.path,
                        artifact.sha256,
                    )
                )
        gate = self.manifest.graph_refresh_gate
        for variant in (gate.default, gate.on_match):
            rows.append(
                self._audit_row(
                    f"graph:{variant.variant}",
                    "artifact",
                    self.project_root / variant.artifact,
                    variant.sha256,
                )
            )
        behaviour = self.manifest.scope_map.unapproved_scope_behaviour
        rows.append(
            self._audit_row(
                "scope-not-approved",
                "artifact",
                self.project_root / behaviour.operator_text_artifact,
                behaviour.operator_text_artifact_sha256,
            )
        )
        return tuple(rows)

    # -- DEFAULT-DENY verification scan (§9.6) ---------------------------

    def discover_unapproved(self) -> tuple[str, ...]:
        """Report instruction files that are neither approved nor excluded.

        **Verification only.** This never selects or resolves a guidance source
        — resolution is manifest-pinned (RULINGS §3). It exists so a new
        ``CLAUDE.md`` appearing in the repository defaults to DENY/UNREVIEWED
        and is reported, rather than silently becoming context.
        """
        pin = self.manifest.primary_repository
        discovery = pin.unapproved_file_discovery
        top = Path(pin.toplevel)
        if not top.is_dir():
            return ()

        wanted = {Path(g).name for g in discovery.globs}
        excludes = tuple(discovery.excludes) + MANDATORY_DISCOVERY_EXCLUDES
        known: set[str] = set(discovery.known_foreign_files)
        for entry in self.manifest.entries.values():
            for source in entry.sources:
                known.add(source.source_path)

        found = [
            rel
            for rel in self._walk_instruction_files(top, wanted, excludes)
            if rel not in known
        ]
        return tuple(sorted(found))

    def assert_no_unapproved_files(self) -> None:
        """Fail closed when the DEFAULT-DENY scan finds something unreviewed."""
        unreviewed = self.discover_unapproved()
        if unreviewed:
            raise UnapprovedProjectGuidanceFile(
                "The repository carries instruction files that were never reviewed.",
                details={
                    "repository": self.manifest.primary_repository.toplevel,
                    "unreviewed": list(unreviewed),
                },
                remediation="A new CLAUDE.md/AGENTS.md defaults to DENY. Classify it "
                "and add it to config/approved-guidance.json, or record it as a "
                "known foreign file (ADDENDUM §9).",
            )

    # -- internals -------------------------------------------------------

    def _disabled(
        self, audience: GuidanceAudience, task_envelope_id: str
    ) -> ProjectGuidanceProjection:
        return ProjectGuidanceProjection(
            manifest_schema_version=self.manifest.schema_version,
            approval_version=self.manifest.approval.version,
            audience=audience.value,
            repository_id=self.manifest.primary_repository.repository_id,
            logical_ids=(),
            scope_prefixes=(),
            scopes=(),
            artifacts=(),
            graph_variant=None,
            text="",
            projected_bytes=0,
            approx_tokens=0,
            fingerprint=hashlib.sha256(b"").hexdigest(),
            task_envelope_id=task_envelope_id,
            scanned_artifacts=(),
            exempt_artifacts=(),
            mode="disabled",
        )

    def _assert_approved(self) -> None:
        if not self.manifest.is_approved:
            raise ProjectGuidanceNotApproved(
                "The project-guidance manifest has not been approved.",
                details={
                    "approval_state": self.manifest.approval.state,
                    "approval_version": self.manifest.approval.version,
                    "manifest": self.manifest.source_path,
                },
                remediation="Nothing projects until the manifest's approval.state is "
                f"{APPROVED_STATE!r}. That is a Sol decision, not a recalculation.",
            )

    def _assert_repository(self, repository: RepositoryIdentity) -> None:
        pin = self.manifest.primary_repository
        mismatched = [
            field
            for field, expected, actual in (
                ("toplevel", pin.toplevel, repository.toplevel),
                ("git_dir", pin.git_dir, repository.git_dir),
                ("origin_url", pin.origin_url, repository.origin_url),
                ("root_commit", pin.root_commit, repository.root_commit),
            )
            if expected != actual
        ]
        if mismatched:
            raise ProjectGuidanceRepositoryMismatch(
                "The dispatch repository is not the repository this guidance was "
                "approved against.",
                details={
                    "repository_id": pin.repository_id,
                    "mismatched_fields": mismatched,
                    "expected_toplevel": pin.toplevel,
                    "actual_toplevel": repository.toplevel,
                },
                remediation="Guidance provenance resolves against the pinned "
                "canonical source set, never a transient worktree or a nested "
                "repository that happens to sit at the same path (RULINGS §4).",
            )

    def _scope_error(
        self,
        message: str,
        *,
        allowed_path: str | None,
        denied_by: str,
        extra: Mapping[str, Any] | None = None,
        remediation: str | None = None,
    ) -> ProjectGuidanceScopeError:
        details: dict[str, Any] = {
            "denied_by": denied_by,
            "repository": self.manifest.primary_repository.toplevel,
        }
        if allowed_path is not None:
            details["allowed_path"] = allowed_path
        if extra:
            details.update(extra)
        return ProjectGuidanceScopeError(
            message,
            details=details,
            remediation=remediation
            or "A stale worktree instruction file must never become a guidance "
            "source merely because it is physically reachable (RULINGS §3). "
            "Narrow the envelope to paths inside the pinned repository.",
        )

    def _entry_id_for(self, scope: ScopeMapEntry, audience: GuidanceAudience) -> str:
        worker = self.manifest.entries[scope.worker_entry]
        if audience is GuidanceAudience.WORKER:
            if not worker.is_worker:
                raise self._not_approved(scope, worker, audience)
            return scope.worker_entry
        if scope.review_entry is None:
            raise self._not_approved(scope, worker, audience)
        return scope.review_entry

    def _not_approved(
        self,
        scope: ScopeMapEntry,
        entry: GuidanceEntry,
        audience: GuidanceAudience,
    ) -> ProjectGuidanceNotApproved:
        behaviour = self.manifest.scope_map.unapproved_scope_behaviour
        operator_text = self._verified_text(
            self.project_root / behaviour.operator_text_artifact,
            expected_sha256=behaviour.operator_text_artifact_sha256,
            logical_id="scope-not-approved",
            artifact_path=behaviour.operator_text_artifact,
        )
        operator_text = operator_text.replace(
            "{scope_prefix}", scope.scope_prefix
        ).replace("{logical_id}", entry.logical_id)
        return ProjectGuidanceNotApproved(
            "The task's allowed paths intersect a repository scope with no "
            "approved project-guidance projection.",
            details={
                "scope_prefix": scope.scope_prefix,
                "logical_id": entry.logical_id,
                "classification": entry.classification,
                "audience": audience.value,
                "fallback_to_root_only": False,
                "operator_text": operator_text,
            },
            remediation="RULINGS §7: there is deliberately no root-only fallback. "
            "Approve a curated projection for this scope, or narrow the task's "
            "allowed_paths so they no longer intersect it.",
        )

    def _project_ids(
        self,
        logical_ids: Sequence[str],
        *,
        repository: RepositoryIdentity,
        audience: GuidanceAudience,
        graph_variant: str | None,
        task_envelope_id: str,
        scope_prefixes: Sequence[str] | None,
    ) -> ProjectGuidanceProjection:
        self._assert_repository(repository)
        projectable = (
            PROJECTABLE_WORKER_CLASSIFICATIONS
            if audience is GuidanceAudience.WORKER
            else PROJECTABLE_REVIEW_CLASSIFICATIONS
        )

        scopes: list[ProjectedScope] = []
        artifacts: list[ProjectedGuidanceArtifact] = []
        scanned: list[str] = []
        exempt: list[str] = []

        for logical_id in logical_ids:
            entry = self.manifest.entries.get(logical_id)
            if entry is None:
                raise ProjectGuidanceNotApproved(
                    "Refused a guidance id that is not an approved manifest entry.",
                    details={
                        "logical_id": logical_id,
                        "approved_ids": sorted(self.manifest.entries),
                    },
                    remediation="Every projectable scope is an explicit, hash-pinned "
                    "manifest entry; no directory family is trusted (RULINGS §3).",
                )
            if entry.classification not in projectable:
                scope = self._scope_of(entry)
                raise self._not_approved(scope, entry, audience)

            source_hashes = self._resolve_sources(entry)
            assert entry.policy_artifact is not None  # guarded by GuidanceEntry
            assert entry.source_artifact is not None
            policy = self._load_artifact(entry.logical_id, entry.policy_artifact)
            source = self._load_artifact(entry.logical_id, entry.source_artifact)
            exempt.append(policy.path)
            scanned.append(source.path)
            self._assert_clean(source)

            scopes.append(
                ProjectedScope(
                    logical_id=entry.logical_id,
                    scope_prefix=entry.scope_prefix or "",
                    classification=entry.classification,
                    source_relationship=entry.source_relationship,
                    source_paths=tuple(s.resolved_path for s in entry.sources),
                    source_hashes=source_hashes,
                    policy=policy,
                    source=source,
                )
            )
            artifacts.append(policy)
            artifacts.append(source)

        if graph_variant is not None:
            gate = self.manifest.graph_refresh_gate
            variant = gate.on_match if graph_variant == gate.on_match.variant else gate.default
            clause = self._load_artifact(
                f"graph:{variant.variant}",
                GuidanceArtifact(
                    path=variant.artifact,
                    provenance_class=variant.provenance_class,
                    sha256=variant.sha256,
                ),
            )
            exempt.append(clause.path)
            artifacts.append(clause)

        # Every artifact ends with a newline, so plain concatenation keeps the
        # blocks line-separated *and* keeps projected_bytes exactly equal to the
        # sum of the reviewed artifact sizes (ADDENDUM §20 budget arithmetic).
        text = "".join(a.text for a in artifacts)
        nbytes = len(text.encode("utf-8"))
        if nbytes > self.max_projected_bytes:
            raise ProjectGuidancePolicyViolation(
                "The projected project guidance exceeds the configured size cap.",
                details={
                    "reason": "size_cap_exceeded",
                    "projected_bytes": nbytes,
                    "max_projected_bytes": self.max_projected_bytes,
                    "logical_ids": list(logical_ids),
                },
                remediation="Narrow the envelope or raise [project_guidance]."
                "max_projected_bytes deliberately; the cap fails closed rather than "
                "truncating reviewed guidance mid-sentence.",
            )

        fingerprint = self._fingerprint(scopes, graph_variant, task_envelope_id)
        return ProjectGuidanceProjection(
            manifest_schema_version=self.manifest.schema_version,
            approval_version=self.manifest.approval.version,
            audience=audience.value,
            repository_id=self.manifest.primary_repository.repository_id,
            logical_ids=tuple(s.logical_id for s in scopes),
            scope_prefixes=tuple(scope_prefixes)
            if scope_prefixes is not None
            else tuple(s.scope_prefix for s in scopes if s.scope_prefix),
            scopes=tuple(scopes),
            artifacts=tuple(artifacts),
            graph_variant=graph_variant,
            text=text,
            projected_bytes=nbytes,
            approx_tokens=estimate_tokens(nbytes),
            fingerprint=fingerprint,
            task_envelope_id=task_envelope_id,
            scanned_artifacts=tuple(scanned),
            exempt_artifacts=tuple(exempt),
        )

    def _scope_of(self, entry: GuidanceEntry) -> ScopeMapEntry:
        for scope in self.manifest.scope_map.entries:
            if scope.worker_entry == entry.logical_id or (
                scope.review_entry == entry.logical_id
            ):
                return scope
        # A root entry has no scope-map row; synthesise one so the refusal text
        # can still name what was refused.
        return ScopeMapEntry(
            scope_prefix=(entry.scope_prefix or "") + "/",
            worker_entry=entry.logical_id,
            review_entry=None,
            approved=False,
        )

    def _resolve_sources(self, entry: GuidanceEntry) -> tuple[str, ...]:
        """Verify every pinned instruction source. Exact paths only.

        This is the whole of source resolution: the manifest's ``resolved_path``
        is opened, its real path must be itself, and its SHA-256 must equal the
        pin. There is no search, no fallback path, and no directory listing —
        RULINGS §3 requires that a reachable copy elsewhere in the tree can
        never become the source.
        """
        measured: list[str] = []
        for source in entry.sources:
            path = Path(source.resolved_path)
            real = Path(os.path.realpath(source.resolved_path))
            if real != path:
                raise ProjectGuidanceSourceChanged(
                    "An approved instruction source no longer resolves to itself.",
                    details={
                        "logical_id": entry.logical_id,
                        "source_path": source.source_path,
                        "approved_path": source.resolved_path,
                        "resolved_path": str(real),
                        "reason": "symlink or resolved-path change",
                    },
                    remediation="Re-review the source and re-approve it explicitly; "
                    "the dispatcher never follows a moved or symlinked instruction "
                    "path.",
                )
            if not path.is_file():
                raise ProjectGuidanceSourceChanged(
                    "An approved instruction source is missing.",
                    details={
                        "logical_id": entry.logical_id,
                        "source_path": source.source_path,
                        "approved_path": source.resolved_path,
                    },
                    remediation="Re-approve against the current repository state; a "
                    "missing reviewed source is never treated as 'no guidance'.",
                )
            try:
                raw = path.read_bytes()
            except OSError as error:
                raise ProjectGuidanceSourceChanged(
                    "An approved instruction source could not be read.",
                    details={
                        "logical_id": entry.logical_id,
                        "source_path": source.source_path,
                        "reason": error.strerror,
                    },
                ) from error
            measured.append(hashlib.sha256(raw).hexdigest())

        # Alias divergence is checked first and reported as drift, because
        # "somebody hand-edited one half of a generated mirror pair" is a more
        # actionable statement than "a hash changed" (ADDENDUM §7).
        if entry.source_relationship == "ALIASES_BYTE_IDENTICAL" and len(
            set(measured)
        ) > 1:
            raise ProjectGuidanceDrift(
                "An instruction pair that was approved as byte-identical aliases "
                "has diverged.",
                details={
                    "logical_id": entry.logical_id,
                    "source_relationship": entry.source_relationship,
                    "measured": {
                        source.source_path: digest
                        for source, digest in zip(entry.sources, measured)
                    },
                },
                remediation="ADDENDUM §7 prefers fail-closed for V1: do not silently "
                "choose one half of the pair. Re-review both and re-approve.",
            )
        for source, digest in zip(entry.sources, measured):
            if digest != source.sha256:
                raise ProjectGuidanceSourceChanged(
                    "An approved instruction source no longer matches its pinned "
                    "hash.",
                    details={
                        "logical_id": entry.logical_id,
                        "source_path": source.source_path,
                        "expected_sha256": source.sha256,
                        "actual_sha256": digest,
                    },
                    remediation="Never recalculate and accept the new hash. Re-review "
                    "the changed instruction file and re-approve it in "
                    "config/approved-guidance.json.",
                )
        return tuple(measured)

    def _load_artifact(
        self, logical_id: str, artifact: GuidanceArtifact
    ) -> ProjectedGuidanceArtifact:
        path = self.project_root / artifact.path
        text = self._verified_text(
            path,
            expected_sha256=artifact.sha256,
            logical_id=logical_id,
            artifact_path=artifact.path,
            expected_bytes=artifact.bytes,
        )
        return ProjectedGuidanceArtifact(
            logical_id=logical_id,
            path=artifact.path,
            provenance_class=artifact.provenance_class,
            sha256=artifact.sha256,
            nbytes=len(text.encode("utf-8")),
            text=text,
        )

    def _verified_text(
        self,
        path: Path,
        *,
        expected_sha256: str,
        logical_id: str,
        artifact_path: str,
        expected_bytes: int | None = None,
    ) -> str:
        if not path.is_file():
            raise ProjectGuidanceProjectionChanged(
                "An approved projection artifact is missing.",
                details={"logical_id": logical_id, "artifact": artifact_path},
                remediation="The curated artifacts are source-controlled; restore the "
                "reviewed file rather than regenerating one.",
            )
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ProjectGuidanceProjectionChanged(
                "An approved projection artifact could not be read.",
                details={
                    "logical_id": logical_id,
                    "artifact": artifact_path,
                    "reason": error.strerror,
                },
            ) from error
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected_sha256 or (
            expected_bytes is not None and len(raw) != expected_bytes
        ):
            raise ProjectGuidanceProjectionChanged(
                "An approved projection artifact no longer matches its pinned hash.",
                details={
                    "logical_id": logical_id,
                    "artifact": artifact_path,
                    "expected_sha256": expected_sha256,
                    "actual_sha256": actual,
                    "expected_bytes": expected_bytes,
                    "actual_bytes": len(raw),
                },
                remediation="Curated guidance is reviewed text. Re-review and "
                "re-approve it; never recalculate the hash to make the mismatch go "
                "away.",
            )
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProjectGuidanceProjectionChanged(
                "An approved projection artifact is not valid UTF-8.",
                details={"logical_id": logical_id, "artifact": artifact_path},
            ) from error

    def _assert_clean(self, artifact: ProjectedGuidanceArtifact) -> None:
        """RULINGS §2: strict classification, SOURCE_DERIVED domain only."""
        hits = self.scanner.scan_artifact(
            artifact.path, artifact.text, provenance_class=artifact.provenance_class
        )
        if hits:
            raise ProjectGuidancePolicyViolation(
                "A source-derived projection artifact carries operator or "
                "secret-adjacent content.",
                details={
                    "reason": "sensitive_content_in_source_derived_artifact",
                    "logical_id": artifact.logical_id,
                    "artifact": artifact.path,
                    "provenance_class": artifact.provenance_class,
                    "hits": [
                        {
                            "pattern": hit.pattern,
                            "matched": hit.matched,
                            "line_number": hit.line_number,
                        }
                        for hit in hits[:10]
                    ],
                },
                remediation="Fix the content, never the pattern set (RULINGS §2). If "
                "the text is dispatcher-authored refusal wording it belongs in the "
                "companion DISPATCHER_AUTHORED policy artifact instead.",
            )

    def _fingerprint(
        self,
        scopes: Sequence[ProjectedScope],
        graph_variant: str | None,
        task_envelope_id: str,
    ) -> str:
        """Exactly ``manifest.resume_fingerprint.spec``. No extra salt.

        The recipe is manifest data so the integration lane and any auditor can
        recompute it independently; :class:`ResumeFingerprintSpec` refuses a
        manifest whose recipe differs from this implementation.
        """
        lines = [
            ":".join(
                (
                    scope.logical_id,
                    "+".join(scope.source_hashes),
                    scope.source.sha256,
                    scope.policy.sha256,
                )
            )
            for scope in scopes
        ]
        payload = (
            "\n".join(lines)
            + "|graph:"
            + (graph_variant or NO_GRAPH_VARIANT)
            + "|envelope:"
            + task_envelope_id
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _audit_row(
        self, logical_id: str, kind: str, path: Path, approved: str
    ) -> GuidanceAuditRow:
        if not path.is_file():
            return GuidanceAuditRow(
                logical_id=logical_id,
                kind=kind,  # type: ignore[arg-type]
                path=str(path),
                approved_sha256=approved,
                current_sha256=None,
                status="MISSING",
                detail="approved path does not exist",
            )
        real = Path(os.path.realpath(path))
        if real != path:
            return GuidanceAuditRow(
                logical_id=logical_id,
                kind=kind,  # type: ignore[arg-type]
                path=str(path),
                approved_sha256=approved,
                current_sha256=None,
                status="DRIFT",
                detail=f"resolves to {real}",
            )
        current = hashlib.sha256(path.read_bytes()).hexdigest()
        return GuidanceAuditRow(
            logical_id=logical_id,
            kind=kind,  # type: ignore[arg-type]
            path=str(path),
            approved_sha256=approved,
            current_sha256=current,
            status="MATCH" if current == approved else "DRIFT",
            detail="" if current == approved else "hash differs",
        )

    def _walk_instruction_files(
        self, top: Path, wanted: set[str], excludes: Sequence[str]
    ) -> list[str]:
        """Pruned directory walk for the DEFAULT-DENY verification scan only."""
        found: list[str] = []
        stack: list[tuple[Path, str]] = [(top, "")]
        while stack:
            directory, rel = stack.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError:
                continue
            for item in entries:
                child_rel = f"{rel}/{item.name}" if rel else item.name
                if item.is_symlink():
                    continue
                if item.is_dir():
                    if item.name == ".git":
                        continue
                    if _discovery_excluded(child_rel, excludes):
                        continue
                    stack.append((Path(item.path), child_rel))
                elif item.name in wanted and not _discovery_excluded(
                    child_rel, excludes
                ):
                    found.append(child_rel)
        return found


def _discovery_excluded(rel: str, patterns: Sequence[str]) -> bool:
    """Match a repository-relative path against the manifest exclude patterns."""
    parts = rel.split("/")
    for pattern in patterns:
        if pattern.startswith("/"):
            # An absolute tree (e.g. /home/dev/worktrees/**). The walk is rooted
            # at the pinned toplevel and symlinks are skipped, so such a tree is
            # unreachable; the pattern is honoured here for completeness.
            continue
        if pattern.startswith("**/") and pattern.endswith("/**"):
            if pattern[3:-3] in parts:
                return True
            continue
        if pattern.endswith("/**"):
            base = pattern[:-3]
            if rel == base or rel.startswith(base + "/"):
                return True
            continue
        if rel == pattern:
            return True
    return False
