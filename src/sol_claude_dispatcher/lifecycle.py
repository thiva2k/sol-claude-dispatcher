"""Deterministic Gate 7 lifecycle profile projection and preflight.

This module is internal orchestration support.  It does not register MCP tools,
does not mutate task state, and does not discover source material.  Every byte
it projects is named in ``approved-lifecycle-profiles.json`` and is checked
against both its own SHA-256 and the SHA-256 of each enumerated, source-
controlled input from which it was reviewed.

The runtime operation is intentionally small: select a profile from stored
envelope facts, verify immutable inputs, compose the exact final
``--append-system-prompt`` string, and measure its UTF-8 bytes.  No summarising,
truncating, inference, filesystem scanning, or profile selection from caller
text occurs here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .errors import (
    ApprovedSkillChanged,
    ConfigurationError,
    ContextTooLarge,
    SkillPolicyViolation,
)
from .models import Complexity, RiskLevel, RunKind, TaskKind, WorkerRole
from .skills import (
    ALLOWED_FRONTMATTER_KEYS,
    DYNAMIC_COMMAND_MARKERS,
    FRONTMATTER_MECHANISM_KEYS,
)

__all__ = [
    "LIFECYCLE_MANIFEST_SCHEMA_VERSION",
    "LifecyclePhase",
    "DerivedSource",
    "LifecycleArtifact",
    "LifecycleProfile",
    "LifecycleManifest",
    "LifecycleProjection",
    "PhaseComposition",
    "PhaseFeasibility",
    "LifecycleFeasibilityReport",
    "LifecycleProfileEngine",
    "load_lifecycle_manifest",
    "compose_append_system_prompt",
    "reachable_lifecycle_phases",
    "select_runtime_phase",
    "evaluate_lifecycle",
    "preflight_lifecycle",
]


LIFECYCLE_MANIFEST_SCHEMA_VERSION = "1.0"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:")


class LifecyclePhase(str, Enum):
    """Dispatcher-owned lifecycle phases, distinct from :class:`RunKind`."""

    DISPATCH_IMPLEMENTATION = "DISPATCH_IMPLEMENTATION"
    CORRECTION_RESUME = "CORRECTION_RESUME"
    VALIDATION_ONLY_RESUME = "VALIDATION_ONLY_RESUME"
    FABLE_REVIEW = "FABLE_REVIEW"


@dataclass(frozen=True, slots=True)
class DerivedSource:
    """One exact source-controlled provenance edge for an artifact."""

    source_id: str
    source_kind: str
    source_path: str
    source_sha256: str
    source_sections: tuple[str, ...]
    concepts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LifecycleArtifact:
    artifact_id: str
    path: str
    projection_sha256: str
    projection_bytes: int
    projection_version: str
    required_deny_patterns: tuple[str, ...]
    derived_from: tuple[DerivedSource, ...]


@dataclass(frozen=True, slots=True)
class LifecycleProfile:
    profile_id: str
    profile_version: str
    fixed: tuple[str, ...]
    by_task_kind: Mapping[str, tuple[str, ...]]
    by_complexity: Mapping[str, tuple[str, ...]]
    by_risk: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class LifecycleManifest:
    schema_version: str
    manifest_version: str
    provenance_policy: str
    review_status: str
    artifacts: tuple[LifecycleArtifact, ...]
    profiles: Mapping[LifecyclePhase, LifecycleProfile]

    @property
    def artifact_by_id(self) -> Mapping[str, LifecycleArtifact]:
        return {artifact.artifact_id: artifact for artifact in self.artifacts}


@dataclass(frozen=True, slots=True)
class LifecycleProjection:
    phase: LifecyclePhase
    profile_id: str
    profile_version: str
    artifact_ids: tuple[str, ...]
    skill_source_ids: tuple[str, ...]
    text: str
    projected_bytes: int
    approved_hashes_verified: bool
    required_deny_patterns_present: bool
    supporting_files_verified: bool


@dataclass(frozen=True, slots=True)
class PhaseComposition:
    """Already-authorised non-lifecycle blocks for one future phase.

    The strings are the exact blocks that will reach the transport.  They are
    passed explicitly so runtime preflight measures actual bytes while matrix
    tests may pass a guidance string at the configured cap.  This object does
    not select or inspect either string.
    """

    dispatcher_authored_text: str
    guidance_text: str = ""
    guidance_cap_bytes: int = 0
    review_context_available: bool = True

    def __post_init__(self) -> None:
        if self.guidance_cap_bytes < 0:
            raise ValueError("guidance_cap_bytes must be non-negative")


@dataclass(frozen=True, slots=True)
class PhaseFeasibility:
    phase: LifecyclePhase
    profile_id: str
    profile_version: str
    artifact_ids: tuple[str, ...]
    skill_source_ids: tuple[str, ...]
    projected_skill_bytes: int
    guidance_cap_bytes: int
    dispatcher_authored_bytes: int
    composed_append_system_prompt_bytes: int
    transport_ceiling_bytes: int
    approved_hashes_verified: bool
    required_deny_patterns_present: bool
    supporting_files_verified: bool
    review_context_available: bool
    feasible: bool
    refusal_code: str | None
    refusal_detail: str | None


@dataclass(frozen=True, slots=True)
class LifecycleFeasibilityReport:
    schema_version: str
    task_id: str
    envelope_digest: str
    manifest_version: str
    computed_at: datetime
    phases: tuple[PhaseFeasibility, ...]
    unreachable_phases: tuple[str, ...]
    feasible: bool

    def for_phase(self, phase: LifecyclePhase) -> PhaseFeasibility:
        for row in self.phases:
            if row.phase is phase:
                return row
        raise KeyError(f"phase {phase.value} is unreachable in this report")

    def to_dict(self) -> dict[str, Any]:
        """Return a bounded JSON-compatible representation for persistence."""
        payload = asdict(self)
        payload["computed_at"] = self.computed_at.isoformat()
        for row in payload["phases"]:
            row["phase"] = row["phase"].value
        return payload


def _configuration_error(message: str, **details: Any) -> ConfigurationError:
    return ConfigurationError(message, details=details)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _configuration_error(
            "Lifecycle profile manifest has an invalid object field.", field=field
        )
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise _configuration_error(
            "Lifecycle profile manifest has an invalid string field.", field=field
        )
    return value


def _string_tuple(value: Any, field: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise _configuration_error(
            "Lifecycle profile manifest has an invalid string-list field.", field=field
        )
    if not allow_empty and not value:
        raise _configuration_error(
            "Lifecycle profile manifest requires a non-empty list.", field=field
        )
    if len(value) != len(set(value)):
        raise _configuration_error(
            "Lifecycle profile manifest contains duplicate list entries.", field=field
        )
    return tuple(value)


def _strict_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    actual = set(value)
    if actual != expected:
        raise _configuration_error(
            "Lifecycle profile manifest fields are not exact.",
            field=field,
            missing=sorted(expected - actual),
            unknown=sorted(actual - expected),
        )


def _safe_relative_path(value: Any, field: str) -> str:
    path = _string(value, field)
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or path != pure.as_posix():
        raise _configuration_error(
            "Lifecycle profile manifest path is not a safe relative POSIX path.",
            field=field,
            path=path,
        )
    return path


def _sha256(value: Any, field: str) -> str:
    digest = _string(value, field)
    if not _HASH_RE.fullmatch(digest):
        raise _configuration_error(
            "Lifecycle profile manifest has an invalid SHA-256.", field=field
        )
    return digest


def _selection_map(
    value: Any,
    field: str,
    *,
    allowed_keys: set[str],
) -> Mapping[str, tuple[str, ...]]:
    source = _mapping(value, field)
    unknown = set(source) - allowed_keys
    if unknown:
        raise _configuration_error(
            "Lifecycle profile selector names an unknown envelope value.",
            field=field,
            unknown=sorted(unknown),
        )
    return {
        key: _string_tuple(items, f"{field}.{key}") for key, items in source.items()
    }


def load_lifecycle_manifest(path: Path | str) -> LifecycleManifest:
    """Parse the strict manifest schema without reading projected files."""
    manifest_path = Path(path)
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _configuration_error(
            "Lifecycle profile manifest could not be read.",
            path=str(manifest_path),
            reason=str(exc),
        ) from exc
    root = _mapping(document, "manifest")
    _strict_keys(
        root,
        {
            "schema_version",
            "manifest_version",
            "provenance_policy",
            "review_status",
            "artifacts",
            "profiles",
        },
        "manifest",
    )
    schema_version = _string(root["schema_version"], "schema_version")
    if schema_version != LIFECYCLE_MANIFEST_SCHEMA_VERSION:
        raise _configuration_error(
            "Lifecycle profile manifest schema is unsupported.",
            expected=LIFECYCLE_MANIFEST_SCHEMA_VERSION,
            actual=schema_version,
        )

    raw_artifacts = root["artifacts"]
    if not isinstance(raw_artifacts, list):
        raise _configuration_error(
            "Lifecycle profile manifest artifacts must be a list.", field="artifacts"
        )
    artifacts: list[LifecycleArtifact] = []
    for index, item in enumerate(raw_artifacts):
        field = f"artifacts[{index}]"
        entry = _mapping(item, field)
        _strict_keys(
            entry,
            {
                "artifact_id",
                "path",
                "projection_sha256",
                "projection_bytes",
                "projection_version",
                "required_deny_patterns",
                "derived_from",
            },
            field,
        )
        raw_sources = entry["derived_from"]
        if not isinstance(raw_sources, list) or not raw_sources:
            raise _configuration_error(
                "Every lifecycle artifact requires provenance.", field=f"{field}.derived_from"
            )
        sources: list[DerivedSource] = []
        for source_index, raw_source in enumerate(raw_sources):
            source_field = f"{field}.derived_from[{source_index}]"
            source = _mapping(raw_source, source_field)
            _strict_keys(
                source,
                {
                    "source_id",
                    "source_kind",
                    "source_path",
                    "source_sha256",
                    "source_sections",
                    "concepts",
                },
                source_field,
            )
            sources.append(
                DerivedSource(
                    source_id=_string(source["source_id"], f"{source_field}.source_id"),
                    source_kind=_string(
                        source["source_kind"], f"{source_field}.source_kind"
                    ),
                    source_path=_safe_relative_path(
                        source["source_path"], f"{source_field}.source_path"
                    ),
                    source_sha256=_sha256(
                        source["source_sha256"], f"{source_field}.source_sha256"
                    ),
                    source_sections=_string_tuple(
                        source["source_sections"],
                        f"{source_field}.source_sections",
                        allow_empty=False,
                    ),
                    concepts=_string_tuple(
                        source["concepts"],
                        f"{source_field}.concepts",
                        allow_empty=False,
                    ),
                )
            )
        projection_bytes = entry["projection_bytes"]
        if not isinstance(projection_bytes, int) or isinstance(projection_bytes, bool) or projection_bytes < 0:
            raise _configuration_error(
                "Lifecycle artifact projection_bytes is invalid.",
                field=f"{field}.projection_bytes",
            )
        artifacts.append(
            LifecycleArtifact(
                artifact_id=_string(entry["artifact_id"], f"{field}.artifact_id"),
                path=_safe_relative_path(entry["path"], f"{field}.path"),
                projection_sha256=_sha256(
                    entry["projection_sha256"], f"{field}.projection_sha256"
                ),
                projection_bytes=projection_bytes,
                projection_version=_string(
                    entry["projection_version"], f"{field}.projection_version"
                ),
                required_deny_patterns=_string_tuple(
                    entry["required_deny_patterns"], f"{field}.required_deny_patterns"
                ),
                derived_from=tuple(sources),
            )
        )
    artifact_ids = [artifact.artifact_id for artifact in artifacts]
    if len(artifact_ids) != len(set(artifact_ids)):
        raise _configuration_error(
            "Lifecycle artifact ids must be unique.", artifact_ids=artifact_ids
        )

    raw_profiles = _mapping(root["profiles"], "profiles")
    expected_phases = {phase.value for phase in LifecyclePhase}
    if set(raw_profiles) != expected_phases:
        raise _configuration_error(
            "Lifecycle profile manifest must be exhaustive over LifecyclePhase.",
            missing=sorted(expected_phases - set(raw_profiles)),
            unknown=sorted(set(raw_profiles) - expected_phases),
        )
    profiles: dict[LifecyclePhase, LifecycleProfile] = {}
    for phase in LifecyclePhase:
        field = f"profiles.{phase.value}"
        entry = _mapping(raw_profiles[phase.value], field)
        _strict_keys(
            entry,
            {
                "profile_id",
                "profile_version",
                "fixed",
                "by_task_kind",
                "by_complexity",
                "by_risk",
            },
            field,
        )
        profiles[phase] = LifecycleProfile(
            profile_id=_string(entry["profile_id"], f"{field}.profile_id"),
            profile_version=_string(
                entry["profile_version"], f"{field}.profile_version"
            ),
            fixed=_string_tuple(entry["fixed"], f"{field}.fixed"),
            by_task_kind=_selection_map(
                entry["by_task_kind"],
                f"{field}.by_task_kind",
                allowed_keys={item.value for item in TaskKind},
            ),
            by_complexity=_selection_map(
                entry["by_complexity"],
                f"{field}.by_complexity",
                allowed_keys={item.value for item in Complexity},
            ),
            by_risk=_selection_map(
                entry["by_risk"],
                f"{field}.by_risk",
                allowed_keys={item.value for item in RiskLevel},
            ),
        )

    manifest = LifecycleManifest(
        schema_version=schema_version,
        manifest_version=_string(root["manifest_version"], "manifest_version"),
        provenance_policy=_string(root["provenance_policy"], "provenance_policy"),
        review_status=_string(root["review_status"], "review_status"),
        artifacts=tuple(artifacts),
        profiles=profiles,
    )
    _validate_manifest_references_and_lattice(manifest)
    return manifest


def _selected_artifact_ids(
    manifest: LifecycleManifest,
    phase: LifecyclePhase,
    *,
    task_kind: TaskKind,
    complexity: Complexity,
    risk: RiskLevel,
) -> tuple[str, ...]:
    profile = manifest.profiles[phase]
    selected = set(profile.fixed)
    selected.update(profile.by_task_kind.get(task_kind.value, ()))
    selected.update(profile.by_complexity.get(complexity.value, ()))
    selected.update(profile.by_risk.get(risk.value, ()))
    return tuple(
        artifact.artifact_id
        for artifact in manifest.artifacts
        if artifact.artifact_id in selected
    )


def _validate_manifest_references_and_lattice(manifest: LifecycleManifest) -> None:
    known = {artifact.artifact_id for artifact in manifest.artifacts}
    profile_ids = [profile.profile_id for profile in manifest.profiles.values()]
    if len(profile_ids) != len(set(profile_ids)):
        raise _configuration_error(
            "Lifecycle profile ids must be unique.", profile_ids=profile_ids
        )
    for phase, profile in manifest.profiles.items():
        referenced = set(profile.fixed)
        for mapping in (profile.by_task_kind, profile.by_complexity, profile.by_risk):
            for artifacts in mapping.values():
                referenced.update(artifacts)
        if not referenced <= known:
            raise _configuration_error(
                "Lifecycle profile names an unknown artifact.",
                phase=phase.value,
                unknown=sorted(referenced - known),
            )

    for task_kind in TaskKind:
        for complexity in Complexity:
            for risk in RiskLevel:
                validation = set(
                    _selected_artifact_ids(
                        manifest,
                        LifecyclePhase.VALIDATION_ONLY_RESUME,
                        task_kind=task_kind,
                        complexity=complexity,
                        risk=risk,
                    )
                )
                correction = set(
                    _selected_artifact_ids(
                        manifest,
                        LifecyclePhase.CORRECTION_RESUME,
                        task_kind=task_kind,
                        complexity=complexity,
                        risk=risk,
                    )
                )
                if not validation <= correction:
                    raise _configuration_error(
                        "Lifecycle resume profiles violate the monotone lattice.",
                        task_kind=task_kind.value,
                        complexity=complexity.value,
                        risk=risk.value,
                        validation_only=sorted(validation),
                        correction=sorted(correction),
                    )
                fable = _selected_artifact_ids(
                    manifest,
                    LifecyclePhase.FABLE_REVIEW,
                    task_kind=task_kind,
                    complexity=complexity,
                    risk=risk,
                )
                if fable:
                    raise _configuration_error(
                        "Fable review must carry zero implementation methodology.",
                        artifact_ids=list(fable),
                    )


def _read_regular_file(root: Path, relative: str, *, purpose: str) -> bytes:
    lexical = root / relative
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise ApprovedSkillChanged(
            f"A lifecycle {purpose} file is missing or unreadable.",
            details={"path": relative, "reason": str(exc)},
        ) from exc
    if resolved != lexical:
        raise ApprovedSkillChanged(
            f"A lifecycle {purpose} path no longer resolves to itself.",
            details={"path": relative, "resolved_path": str(resolved)},
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lexical, flags)
    except OSError as exc:
        raise ApprovedSkillChanged(
            f"A lifecycle {purpose} file could not be opened.",
            details={"path": relative, "reason": str(exc)},
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ApprovedSkillChanged(
                f"A lifecycle {purpose} path is not a regular file.",
                details={"path": relative},
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _extract_inert_projection(raw: bytes, *, artifact_id: str, path: str) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillPolicyViolation(
            "Lifecycle projection is not valid UTF-8 inert text.",
            details={"artifact_id": artifact_id, "path": path},
        ) from exc

    body = text
    if text.startswith("---\n") or text.startswith("---\r\n"):
        lines = text.splitlines()
        end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
        if end is None:
            raise SkillPolicyViolation(
                "Lifecycle projection is not inert text: frontmatter is unterminated.",
                details={"artifact_id": artifact_id, "path": path},
            )
        keys = {
            match.group(1)
            for line in lines[1:end]
            if (match := _FRONTMATTER_KEY_RE.match(line)) is not None
        }
        disallowed = sorted(keys - ALLOWED_FRONTMATTER_KEYS)
        if disallowed:
            raise SkillPolicyViolation(
                "Lifecycle projection is not inert text: frontmatter declares mechanisms.",
                details={
                    "artifact_id": artifact_id,
                    "path": path,
                    "disallowed_keys": disallowed,
                    "known_mechanisms": sorted(
                        set(disallowed) & FRONTMATTER_MECHANISM_KEYS
                    ),
                },
            )
        body = "\n".join(lines[end + 1 :])
    for label, pattern in DYNAMIC_COMMAND_MARKERS:
        if pattern.search(body):
            raise SkillPolicyViolation(
                "Lifecycle projection is not inert text: dynamic command construct found.",
                details={"artifact_id": artifact_id, "path": path, "construct": label},
            )
    return body


class LifecycleProfileEngine:
    """Hash-pinned, deterministic lifecycle projection engine."""

    def __init__(
        self,
        manifest: LifecycleManifest,
        *,
        source_root: Path | str,
        effective_deny_patterns: Sequence[str] = (),
    ) -> None:
        self.manifest = manifest
        self.source_root = Path(source_root).resolve(strict=True)
        if not self.source_root.is_dir():
            raise ConfigurationError(
                "Lifecycle source root is not a directory.",
                details={"source_root": str(self.source_root)},
            )
        self.effective_deny_patterns = tuple(effective_deny_patterns)

    @classmethod
    def from_file(
        cls,
        manifest_path: Path | str,
        *,
        source_root: Path | str,
        effective_deny_patterns: Sequence[str] = (),
    ) -> "LifecycleProfileEngine":
        return cls(
            load_lifecycle_manifest(manifest_path),
            source_root=source_root,
            effective_deny_patterns=effective_deny_patterns,
        )

    def artifact_ids_for(
        self,
        phase: LifecyclePhase,
        *,
        task_kind: TaskKind,
        complexity: Complexity,
        risk: RiskLevel,
    ) -> tuple[str, ...]:
        return _selected_artifact_ids(
            self.manifest,
            phase,
            task_kind=task_kind,
            complexity=complexity,
            risk=risk,
        )

    def project(
        self,
        phase: LifecyclePhase,
        *,
        task_kind: TaskKind,
        complexity: Complexity,
        risk: RiskLevel,
    ) -> LifecycleProjection:
        artifact_ids = self.artifact_ids_for(
            phase,
            task_kind=task_kind,
            complexity=complexity,
            risk=risk,
        )
        artifacts = self.manifest.artifact_by_id
        texts: list[str] = []
        source_ids: list[str] = []
        verified_sources: set[tuple[str, str]] = set()
        for artifact_id in artifact_ids:
            artifact = artifacts[artifact_id]
            for source in artifact.derived_from:
                identity = (source.source_path, source.source_sha256)
                if identity not in verified_sources:
                    raw_source = _read_regular_file(
                        self.source_root, source.source_path, purpose="source"
                    )
                    actual_source_hash = hashlib.sha256(raw_source).hexdigest()
                    if actual_source_hash != source.source_sha256:
                        raise ApprovedSkillChanged(
                            "A lifecycle source hash no longer matches its reviewed provenance.",
                            details={
                                "source_id": source.source_id,
                                "source_path": source.source_path,
                                "expected_sha256": source.source_sha256,
                                "actual_sha256": actual_source_hash,
                            },
                            remediation="Re-review the compact projection against the changed source; hashes are never refreshed automatically.",
                        )
                    verified_sources.add(identity)
                if source.source_id not in source_ids:
                    source_ids.append(source.source_id)

            raw_projection = _read_regular_file(
                self.source_root, artifact.path, purpose="projection"
            )
            actual_projection_hash = hashlib.sha256(raw_projection).hexdigest()
            if (
                actual_projection_hash != artifact.projection_sha256
                or len(raw_projection) != artifact.projection_bytes
            ):
                raise ApprovedSkillChanged(
                    "A lifecycle projection no longer matches its reviewed hash and size.",
                    details={
                        "artifact_id": artifact.artifact_id,
                        "path": artifact.path,
                        "expected_sha256": artifact.projection_sha256,
                        "actual_sha256": actual_projection_hash,
                        "expected_bytes": artifact.projection_bytes,
                        "actual_bytes": len(raw_projection),
                    },
                    remediation="Restore the reviewed projection or explicitly re-review and update its manifest entry.",
                )
            missing_denies = sorted(
                set(artifact.required_deny_patterns) - set(self.effective_deny_patterns)
            )
            if missing_denies:
                raise SkillPolicyViolation(
                    "Lifecycle projection requires deny patterns that are not in effect.",
                    details={
                        "artifact_id": artifact.artifact_id,
                        "missing_deny_patterns": missing_denies,
                    },
                )
            texts.append(
                _extract_inert_projection(
                    raw_projection, artifact_id=artifact.artifact_id, path=artifact.path
                )
            )

        text = "\n\n".join(texts)
        profile = self.manifest.profiles[phase]
        return LifecycleProjection(
            phase=phase,
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            artifact_ids=artifact_ids,
            skill_source_ids=tuple(source_ids),
            text=text,
            projected_bytes=len(text.encode("utf-8")),
            approved_hashes_verified=True,
            required_deny_patterns_present=True,
            supporting_files_verified=True,
        )


def compose_append_system_prompt(*blocks: str) -> str:
    """Compose the exact inline transport string; no normalisation or truncation."""
    if any(not isinstance(block, str) for block in blocks):
        raise TypeError("append-system-prompt blocks must be strings")
    return "\n\n".join(block for block in blocks if block != "")


def reachable_lifecycle_phases(
    *, max_resume_count: int
) -> tuple[tuple[LifecyclePhase, ...], tuple[LifecyclePhase, ...]]:
    if (
        not isinstance(max_resume_count, int)
        or isinstance(max_resume_count, bool)
        or max_resume_count < 0
    ):
        raise ValueError("max_resume_count must be a non-negative integer")
    if max_resume_count > 0:
        return tuple(LifecyclePhase), ()
    return (
        (
            LifecyclePhase.DISPATCH_IMPLEMENTATION,
            LifecyclePhase.FABLE_REVIEW,
        ),
        (
            LifecyclePhase.CORRECTION_RESUME,
            LifecyclePhase.VALIDATION_ONLY_RESUME,
        ),
    )


def select_runtime_phase(*, run_kind: RunKind, role: WorkerRole) -> LifecyclePhase:
    """Pure runtime selector.  V1 deliberately never returns validation-only."""
    if role is WorkerRole.REVIEWER or run_kind is RunKind.REVIEW:
        return LifecyclePhase.FABLE_REVIEW
    if run_kind is RunKind.DISPATCH:
        return LifecyclePhase.DISPATCH_IMPLEMENTATION
    if run_kind is RunKind.RESUME:
        return LifecyclePhase.CORRECTION_RESUME
    raise ConfigurationError(
        "No lifecycle profile exists for the runtime invocation.",
        details={"run_kind": str(run_kind), "role": str(role)},
    )


def evaluate_lifecycle(
    engine: LifecycleProfileEngine,
    *,
    task_id: str,
    envelope_digest: str,
    task_kind: TaskKind,
    complexity: Complexity,
    risk: RiskLevel,
    max_resume_count: int,
    phase_compositions: Mapping[LifecyclePhase, PhaseComposition],
    transport_ceiling_bytes: int,
    computed_at: datetime,
) -> LifecycleFeasibilityReport:
    """Prove every automatically reachable phase without mutating task state."""
    if not task_id:
        raise ValueError("task_id must be non-empty")
    if not _HASH_RE.fullmatch(envelope_digest):
        raise ValueError("envelope_digest must be a lowercase SHA-256")
    if isinstance(transport_ceiling_bytes, bool) or transport_ceiling_bytes < 1:
        raise ValueError("transport_ceiling_bytes must be positive")
    if computed_at.tzinfo is None or computed_at.utcoffset() is None:
        raise ValueError("computed_at must be timezone-aware")

    reachable, unreachable = reachable_lifecycle_phases(
        max_resume_count=max_resume_count
    )
    missing = [phase.value for phase in reachable if phase not in phase_compositions]
    unknown = [
        str(phase)
        for phase in phase_compositions
        if not isinstance(phase, LifecyclePhase)
    ]
    if missing or unknown:
        raise ConfigurationError(
            "Lifecycle composition inputs do not cover every reachable phase.",
            details={"missing": missing, "unknown": unknown},
        )

    rows: list[PhaseFeasibility] = []
    for phase in reachable:
        projection = engine.project(
            phase,
            task_kind=task_kind,
            complexity=complexity,
            risk=risk,
        )
        composition = phase_compositions[phase]
        final_prompt = compose_append_system_prompt(
            composition.dispatcher_authored_text,
            projection.text,
            composition.guidance_text,
        )
        composed_bytes = len(final_prompt.encode("utf-8"))
        guidance_bytes = len(composition.guidance_text.encode("utf-8"))
        review_available = (
            composition.review_context_available
            if phase is LifecyclePhase.FABLE_REVIEW
            else True
        )
        refusal_code: str | None = None
        refusal_detail: str | None = None
        if guidance_bytes > composition.guidance_cap_bytes:
            refusal_code = "ProjectGuidanceNotApproved"
            refusal_detail = (
                f"guidance bytes {guidance_bytes} exceed cap "
                f"{composition.guidance_cap_bytes}"
            )
        elif not review_available:
            refusal_code = "ProjectGuidanceNotApproved"
            refusal_detail = "review context is unavailable"
        elif composed_bytes > transport_ceiling_bytes:
            refusal_code = "ContextTooLarge"
            refusal_detail = (
                f"composed bytes {composed_bytes} exceed transport ceiling "
                f"{transport_ceiling_bytes}"
            )
        rows.append(
            PhaseFeasibility(
                phase=phase,
                profile_id=projection.profile_id,
                profile_version=projection.profile_version,
                artifact_ids=projection.artifact_ids,
                skill_source_ids=projection.skill_source_ids,
                projected_skill_bytes=projection.projected_bytes,
                guidance_cap_bytes=composition.guidance_cap_bytes,
                dispatcher_authored_bytes=len(
                    composition.dispatcher_authored_text.encode("utf-8")
                ),
                composed_append_system_prompt_bytes=composed_bytes,
                transport_ceiling_bytes=transport_ceiling_bytes,
                approved_hashes_verified=projection.approved_hashes_verified,
                required_deny_patterns_present=projection.required_deny_patterns_present,
                supporting_files_verified=projection.supporting_files_verified,
                review_context_available=review_available,
                feasible=refusal_code is None,
                refusal_code=refusal_code,
                refusal_detail=refusal_detail,
            )
        )
    return LifecycleFeasibilityReport(
        schema_version="1.0",
        task_id=task_id,
        envelope_digest=envelope_digest,
        manifest_version=engine.manifest.manifest_version,
        computed_at=computed_at,
        phases=tuple(rows),
        unreachable_phases=tuple(phase.value for phase in unreachable),
        feasible=all(row.feasible for row in rows),
    )


def preflight_lifecycle(
    engine: LifecycleProfileEngine,
    **kwargs: Any,
) -> LifecycleFeasibilityReport:
    """Evaluate the full future horizon and refuse before lifecycle mutation."""
    report = evaluate_lifecycle(engine, **kwargs)
    if report.feasible:
        return report
    failed = next(row for row in report.phases if not row.feasible)
    details = {
        "infeasible_phase": failed.phase.value,
        "profile_id": failed.profile_id,
        "profile_version": failed.profile_version,
        "artifact_ids": list(failed.artifact_ids),
        "composed_bytes": failed.composed_append_system_prompt_bytes,
        "transport_ceiling_bytes": failed.transport_ceiling_bytes,
        "phases": {
            row.phase.value: row.composed_append_system_prompt_bytes
            for row in report.phases
        },
        "reason": failed.refusal_detail,
    }
    if failed.refusal_code == "ContextTooLarge":
        raise ContextTooLarge(
            "An automatically reachable lifecycle phase exceeds the transport ceiling.",
            details=details,
            remediation="Narrow the task or install an explicitly reviewed smaller lifecycle projection; the dispatcher never truncates one.",
        )
    raise ConfigurationError(
        "An automatically reachable lifecycle phase cannot be composed safely.",
        details=details,
    )
