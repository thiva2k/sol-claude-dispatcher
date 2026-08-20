"""Approved-skill projection (GATE 4.5 §6-§11, §15, §18).

This module turns *reviewed, hash-pinned* skill files into **inert text** that
the dispatcher appends to a worker's system prompt. It is emphatically not a
skill runtime:

* nothing here executes anything found in a skill file — ever, under any
  configuration;
* nothing here interprets ``allowed-tools``, ``disallowed-tools``, ``context``,
  ``agent``, ``background``, ``hooks``, ``!`command```, ```` ```! ```` blocks,
  plugin configuration, MCP declarations, or model/effort overrides. Those are
  *data* during inspection, and a file that carries one is refused rather than
  cleaned up;
* nothing here discovers skills. A skill is projectable if and only if it is an
  explicit entry in ``config/approved-skills.json`` whose pinned path and
  SHA-256 still match the bytes on disk. No directory is trusted, no plugin is
  trusted, no family of paths is trusted (§11).

The pipeline for every projected file is fixed (§6)::

    manifest lookup
      -> classification check           (§7: only SAFE_* project)
      -> required deny patterns present (P1/P2)
      -> canonical path validation      (load time; pure path math)
      -> resolved path validation       (realpath == pin, inside pinned install)
      -> hash verification              (SHA-256 of the exact bytes)
      -> safe content extraction        (frontmatter mechanisms refused)
      -> INERT TEXT

Anything that does not match fails closed: :class:`ApprovedSkillChanged` when
the *source* changed (hash, path, presence), :class:`SkillPolicyViolation` when
the *request* is refused (unapproved id, wrong classification, missing deny
pattern, size cap). The manifest is never rewritten — re-approval is a human
or Sol decision, not a recalculation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .config import Config
from .errors import ApprovedSkillChanged, ConfigurationError, SkillPolicyViolation
from .models import (
    Complexity,
    RiskLevel,
    RunKind,
    SkillPolicyRecord,
    TaskKind,
    WorkerRole,
)

__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "PROJECTABLE_CLASSIFICATIONS",
    "REFUSED_CLASSIFICATIONS",
    "KNOWN_CLASSIFICATIONS",
    "ALLOWED_FRONTMATTER_KEYS",
    "FRONTMATTER_MECHANISM_KEYS",
    "DYNAMIC_COMMAND_MARKERS",
    "FINGERPRINT_VERSION",
    "TOKEN_BYTES",
    "estimate_tokens",
    "PluginPin",
    "SupportingFile",
    "ApprovedSkill",
    "RejectedSkill",
    "NeverProject",
    "SelectionMap",
    "SkillManifest",
    "load_manifest",
    "load_manifest_from_mapping",
    "ProjectedFile",
    "ProjectedSkill",
    "SkillProjection",
    "SkillAuditRow",
    "SkillProjectionEngine",
    "EMPTY_PROJECTION_TEXT",
]

MANIFEST_SCHEMA_VERSION = "1.0"

#: §7. Only these two classifications may ever reach a worker prompt.
PROJECTABLE_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"SAFE_REFERENCE", "SAFE_WORKER_PROCEDURE"}
)
#: §7. These are refused. There is no sanitizer that promotes one of them:
#: rewriting an unsafe skill into a safe one is an instruction compiler, and
#: the correct move is to pick a different skill that is already safe.
REFUSED_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"MANUAL_ONLY", "UNSAFE_FOR_DISPATCHER", "UNKNOWN"}
)
KNOWN_CLASSIFICATIONS: frozenset[str] = (
    PROJECTABLE_CLASSIFICATIONS | REFUSED_CLASSIFICATIONS
)

#: The only frontmatter keys a projected file may carry. Everything else is a
#: mechanism (or an unknown), and a mechanism appearing in an approved file
#: means the file is no longer what was reviewed.
ALLOWED_FRONTMATTER_KEYS: frozenset[str] = frozenset({"name", "description"})

#: Named by §6 as things the engine must never interpret. Listed here so the
#: refusal message can say *which* mechanism was found, and so a reader can see
#: at a glance what this engine deliberately does not implement.
FRONTMATTER_MECHANISM_KEYS: frozenset[str] = frozenset(
    {
        "allowed-tools",
        "allowed_tools",
        "disallowed-tools",
        "disallowed_tools",
        "tools",
        "context",
        "agent",
        "agents",
        "background",
        "hooks",
        "mcp",
        "mcp-servers",
        "mcpServers",
        "model",
        "effort",
        "reasoning-effort",
        "plugin",
        "user-invocable",
        "userInvocable",
        "argument-hint",
        "command",
        "script",
    }
)

#: Claude Code's dynamic-content constructs. A projected file containing one is
#: refused outright: projection puts text in front of a worker, and text that
#: was written to be *expanded* is not text that was reviewed.
DYNAMIC_COMMAND_MARKERS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("!`command`", re.compile(r"!`")),
    ("```! fenced command block", re.compile(r"^[ \t]*```!", re.MULTILINE)),
)

#: Version tag hashed into every fingerprint so a change to the fingerprint
#: recipe cannot masquerade as an unchanged policy.
FINGERPRINT_VERSION = "skill-policy-fingerprint/v1"

#: Bytes per token for the §18 estimate. ASCII-dominant English markdown; the
#: measurement is explicitly approximate (±15%: code fences tokenise worse).
TOKEN_BYTES = 4

EMPTY_PROJECTION_TEXT = ""

_PLACEHOLDER_RE = re.compile(r"^\$\{([A-Za-z0-9_.-]+)\.install_path\}(?P<rest>/.*)$")
_FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:")


def estimate_tokens(n_bytes: int) -> int:
    """Approximate token count for ``n_bytes`` of markdown (§18)."""
    return n_bytes // TOKEN_BYTES


# ---------------------------------------------------------------------------
# Manifest schema (§9)
# ---------------------------------------------------------------------------


class _StrictManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PluginPin(_StrictManifestModel):
    """Pinned identity of one enabled plugin install (§9).

    ``plugin_version`` may legitimately be ``None``: ``agent-skills`` carries no
    version string in ``plugin.json``, ``installed_plugins.json`` or the
    marketplace record, and no ``gitCommitSha`` is recorded for it on this
    host. When that is the case ``plugin_version_source`` says ``"absent"`` and
    integrity rests entirely on ``install_path`` + ``plugin_install_id`` + the
    per-file SHA-256. That gap is recorded rather than papered over: the drift
    auditor cannot print a version comparison for such a plugin.
    """

    plugin_name: str = Field(min_length=1)
    marketplace: str = Field(min_length=1)
    marketplace_repo: str | None = None
    plugin_version: str | None = None
    plugin_version_source: str = Field(min_length=1)
    plugin_version_note: str | None = None
    plugin_install_id: str = Field(min_length=1)
    install_path: str = Field(min_length=1)
    git_commit_sha: str | None = None
    trusted_scope: Literal["listed_skills_only"] = "listed_skills_only"
    untrusted: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "PluginPin":
        _assert_safe_absolute_path(self.install_path, "plugins.install_path")
        if self.plugin_version is None and self.plugin_version_source != "absent":
            raise ValueError(
                "plugin_version is null but plugin_version_source does not say "
                "'absent'; record the gap explicitly rather than leaving it "
                "ambiguous"
            )
        return self

    @property
    def install_root(self) -> Path:
        return Path(self.install_path)


class SupportingFile(_StrictManifestModel):
    """One supporting file enumerated *per skill* — never a trusted directory."""

    path: str = Field(min_length=1)
    resolved_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int | None = Field(default=None, ge=0)
    executable: bool = False
    #: Whether this file is co-projected. ``False`` means the reference is left
    #: dangling on purpose and neutralised by the dispatcher's preamble.
    project: bool = False
    shared_with: tuple[str, ...] = ()
    reason: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "SupportingFile":
        _assert_safe_absolute_path(self.resolved_path, "supporting_files.resolved_path")
        if self.executable and self.project:
            raise ValueError(
                f"supporting file {self.resolved_path!r} is executable and marked "
                f"for projection; executables are never projected"
            )
        return self


class ApprovedSkill(_StrictManifestModel):
    """One explicitly approved skill. Every §9 field is required."""

    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    source_type: Literal["plugin", "personal", "project"]
    plugin: str | None = None
    #: Required for ``personal`` / ``project`` sources: the exact trusted skill
    #: directory, which must be ``…/.claude/skills/<exact-skill>``. There is no
    #: trusted *family* — this names one directory, and only one (§11).
    source_root: str | None = None
    plugin_version: str | None = None
    plugin_install_id: str | None = None
    canonical_path: str = Field(min_length=1)
    resolved_path: str = Field(min_length=1)
    resolved_equals_canonical: bool = True
    skill_md_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    skill_md_bytes: int = Field(ge=1)
    supporting_files: tuple[SupportingFile, ...] = ()
    classification: Literal[
        "SAFE_REFERENCE",
        "SAFE_WORKER_PROCEDURE",
        "MANUAL_ONLY",
        "UNSAFE_FOR_DISPATCHER",
        "UNKNOWN",
    ]
    tier: str = Field(min_length=1)
    activation: Literal["always_on", "contextual", "envelope_hint_only"]
    activation_profile: Mapping[str, Any] = Field(default_factory=dict)
    reviewer_eligible: bool = False
    requires_deny_patterns: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    selection_note: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "ApprovedSkill":
        _assert_safe_absolute_path(self.resolved_path, f"skills[{self.id}].resolved_path")
        if self.source_type == "plugin":
            if not self.plugin:
                raise ValueError(f"skill {self.id!r}: plugin source needs a plugin key")
            if self.source_root is not None:
                raise ValueError(
                    f"skill {self.id!r}: plugin sources take their root from the "
                    f"pinned plugin install, not from source_root"
                )
        else:
            if self.plugin is not None:
                raise ValueError(
                    f"skill {self.id!r}: {self.source_type} source must not name a plugin"
                )
            if not self.source_root:
                raise ValueError(
                    f"skill {self.id!r}: {self.source_type} source must pin an exact "
                    f"source_root of the form <root>/.claude/skills/<exact-skill>"
                )
            _assert_safe_absolute_path(self.source_root, f"skills[{self.id}].source_root")
            parts = Path(self.source_root).parts
            if len(parts) < 4 or parts[-2] != "skills" or parts[-3] != ".claude":
                raise ValueError(
                    f"skill {self.id!r}: source_root {self.source_root!r} is not an "
                    f"exact <root>/.claude/skills/<exact-skill> directory (§11)"
                )
        return self

    @property
    def projected_supporting_files(self) -> tuple[SupportingFile, ...]:
        return tuple(s for s in self.supporting_files if s.project)


class RejectedSkill(_StrictManifestModel):
    """A candidate that was reviewed and refused. Recorded so it stays refused."""

    id: str = Field(min_length=1)
    resolved_path: str = Field(min_length=1)
    skill_md_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    skill_md_bytes: int = Field(ge=1)
    verdict: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    reapproval_condition: str | None = None


class NeverProject(_StrictManifestModel):
    """A file that must never be projected even though it sits next to one."""

    path: str = Field(min_length=1)
    resolved_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int | None = Field(default=None, ge=0)
    executable: bool = False
    reason: str = Field(min_length=1)


class SelectionMap(_StrictManifestModel):
    """The deterministic §8 mapping. Data, reviewed with the manifest."""

    inputs: tuple[str, ...]
    combine: Literal["set_union_with_dedup"]
    by_task_kind: Mapping[str, tuple[str, ...]]
    by_complexity: Mapping[str, tuple[str, ...]]
    by_risk: Mapping[str, tuple[str, ...]]
    by_run_kind: Mapping[str, tuple[str, ...]]
    omitted_deliberately: Mapping[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _exhaustive(self) -> "SelectionMap":
        # A new TaskKind (or Complexity, or RiskLevel, or RunKind) must not
        # silently fall through to "core only". It must fail loudly until
        # somebody decides what it maps to.
        for field, enum in (
            ("by_task_kind", TaskKind),
            ("by_complexity", Complexity),
            ("by_risk", RiskLevel),
            ("by_run_kind", RunKind),
        ):
            table = getattr(self, field)
            expected = {member.value for member in enum}
            actual = set(table)
            if actual != expected:
                raise ValueError(
                    f"selection.{field} must map exactly {sorted(expected)}; "
                    f"got {sorted(actual)}"
                )
        return self


class SkillManifest(_StrictManifestModel):
    """The dispatcher-owned approval manifest (§9). Read-only, source-controlled."""

    schema_version: Literal["1.0"]
    manifest_version: str = Field(min_length=1)
    generated_at: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approval_note: str | None = None
    projection_mode: Literal["inert_text"]
    native_skill_runtime: Literal[False]
    max_projected_bytes: int = Field(ge=1)
    fail_on_drift: Literal[True]
    drift_error: Literal["ApprovedSkillChanged"] = "ApprovedSkillChanged"
    policy_error: Literal["SkillPolicyViolation"] = "SkillPolicyViolation"
    required_deny_patterns: tuple[str, ...] = ()
    envelope_precedence_preamble_required: bool = True
    plugins: Mapping[str, PluginPin]
    core_always_on: tuple[str, ...]
    selection: SelectionMap
    approved_reviewer_skills: tuple[str, ...] = ()
    skills: tuple[ApprovedSkill, ...]
    rejected: tuple[RejectedSkill, ...] = ()
    never_project: tuple[NeverProject, ...] = ()
    source_path: str | None = None

    @model_validator(mode="after")
    def _coherent(self) -> "SkillManifest":
        ids = [s.id for s in self.skills]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate skill ids in the manifest")
        by_id = {s.id: s for s in self.skills}

        rejected_ids = {r.id for r in self.rejected}
        overlap = rejected_ids & set(ids)
        if overlap:
            raise ValueError(
                f"ids appear in both skills and rejected: {sorted(overlap)}"
            )

        never = {n.resolved_path for n in self.never_project}

        for skill in self.skills:
            root = self._trusted_root(skill)
            _assert_inside(skill.resolved_path, root, f"skills[{skill.id}]")
            expanded = self._expand(skill.canonical_path, skill)
            _assert_inside(expanded, root, f"skills[{skill.id}].canonical_path")
            if skill.resolved_equals_canonical and expanded != skill.resolved_path:
                raise ValueError(
                    f"skill {skill.id!r} declares resolved_equals_canonical but the "
                    f"canonical path expands to {expanded!r}, not {skill.resolved_path!r}"
                )
            for support in skill.supporting_files:
                _assert_inside(
                    support.resolved_path, root, f"skills[{skill.id}].supporting_files"
                )
                expanded_support = self._expand(support.path, skill)
                if expanded_support != support.resolved_path:
                    raise ValueError(
                        f"skill {skill.id!r}: supporting file path {support.path!r} "
                        f"expands to {expanded_support!r}, not {support.resolved_path!r}"
                    )
                if support.project and support.resolved_path in never:
                    raise ValueError(
                        f"skill {skill.id!r} projects {support.resolved_path!r}, which "
                        f"is on the never_project list"
                    )

        for name, listed in (
            ("core_always_on", self.core_always_on),
            ("approved_reviewer_skills", self.approved_reviewer_skills),
        ):
            for skill_id in listed:
                if skill_id not in by_id:
                    raise ValueError(f"{name} names unknown skill {skill_id!r}")
                if by_id[skill_id].classification not in PROJECTABLE_CLASSIFICATIONS:
                    raise ValueError(
                        f"{name} names {skill_id!r}, whose classification "
                        f"{by_id[skill_id].classification!r} is not projectable"
                    )
        for skill_id in self.approved_reviewer_skills:
            if not by_id[skill_id].reviewer_eligible:
                raise ValueError(
                    f"approved_reviewer_skills names {skill_id!r}, which is not "
                    f"reviewer_eligible"
                )

        for table_name in ("by_task_kind", "by_complexity", "by_risk", "by_run_kind"):
            table = getattr(self.selection, table_name)
            for key, listed in table.items():
                for skill_id in listed:
                    if skill_id not in by_id:
                        raise ValueError(
                            f"selection.{table_name}[{key!r}] names unknown skill "
                            f"{skill_id!r}"
                        )
                    if by_id[skill_id].classification not in PROJECTABLE_CLASSIFICATIONS:
                        raise ValueError(
                            f"selection.{table_name}[{key!r}] names {skill_id!r}, "
                            f"whose classification is not projectable"
                        )
        if self.selection.by_run_kind.get(RunKind.REVIEW.value):
            raise ValueError(
                "selection.by_run_kind['review'] must be empty: Fable receives no "
                "implementation guidance (§14, §7.7)"
            )
        return self

    # -- helpers ---------------------------------------------------------

    def _trusted_root(self, skill: ApprovedSkill) -> str:
        if skill.source_type == "plugin":
            assert skill.plugin is not None  # guarded by ApprovedSkill._check
            pin = self.plugins.get(skill.plugin)
            if pin is None:
                raise ValueError(
                    f"skill {skill.id!r} names unknown plugin {skill.plugin!r}"
                )
            if (
                skill.plugin_install_id is not None
                and skill.plugin_install_id != pin.plugin_install_id
            ):
                raise ValueError(
                    f"skill {skill.id!r} pins install id {skill.plugin_install_id!r} "
                    f"but its plugin pins {pin.plugin_install_id!r}"
                )
            if skill.plugin_version != pin.plugin_version:
                raise ValueError(
                    f"skill {skill.id!r} pins plugin version {skill.plugin_version!r} "
                    f"but its plugin pins {pin.plugin_version!r}"
                )
            return pin.install_path
        assert skill.source_root is not None  # guarded by ApprovedSkill._check
        return skill.source_root

    def _expand(self, template: str, skill: ApprovedSkill) -> str:
        """Expand ``${<plugin-name>.install_path}/…`` against the skill's own pin."""
        if not template.startswith("${"):
            _assert_safe_absolute_path(template, f"skills[{skill.id}] path")
            return template
        match = _PLACEHOLDER_RE.match(template)
        if match is None:
            raise ValueError(
                f"skill {skill.id!r}: unsupported path placeholder in {template!r}"
            )
        name, rest = match.group(1), match.group("rest")
        if skill.source_type != "plugin":
            raise ValueError(
                f"skill {skill.id!r}: install_path placeholders are for plugin sources"
            )
        assert skill.plugin is not None
        pin = self.plugins[skill.plugin]
        if name != pin.plugin_name:
            raise ValueError(
                f"skill {skill.id!r}: placeholder names plugin {name!r} but the entry "
                f"belongs to {pin.plugin_name!r}"
            )
        expanded = pin.install_path.rstrip("/") + rest
        _assert_safe_absolute_path(expanded, f"skills[{skill.id}] path")
        return expanded

    @property
    def by_id(self) -> dict[str, ApprovedSkill]:
        return {s.id: s for s in self.skills}

    @property
    def skill_ids(self) -> tuple[str, ...]:
        return tuple(s.id for s in self.skills)

    def order_of(self, skill_id: str) -> int:
        """Manifest declaration order — the stable projection order."""
        return self.skill_ids.index(skill_id)


def _assert_safe_absolute_path(value: str, where: str) -> None:
    """Pure path math: absolute, no traversal, no ``~``. No filesystem access."""
    if not value.startswith("/"):
        raise ValueError(f"{where}: path must be absolute, got {value!r}")
    if "~" in value:
        raise ValueError(f"{where}: path must not contain '~', got {value!r}")
    parts = Path(value).parts
    if ".." in parts:
        raise ValueError(f"{where}: path must not contain '..', got {value!r}")


def _assert_inside(candidate: str, root: str, where: str) -> None:
    root_path = Path(root)
    child = Path(candidate)
    if child == root_path or root_path not in child.parents:
        raise ValueError(
            f"{where}: {candidate!r} is not inside the pinned install/source root "
            f"{root!r}; no directory family is trusted, and a same-named skill from "
            f"another plugin or another version is a different skill (§11)"
        )


def load_manifest_from_mapping(
    data: Mapping[str, Any], *, source_path: str | None = None
) -> SkillManifest:
    """Validate an already-parsed manifest mapping. Fails closed."""
    if not isinstance(data, Mapping):
        raise ConfigurationError(
            "Approved-skill manifest root must be an object.",
            details={"got": type(data).__name__},
        )
    payload = dict(data)
    payload["source_path"] = source_path
    try:
        return SkillManifest(**payload)
    except ValidationError as exc:
        raise ConfigurationError(
            "Approved-skill manifest is invalid.",
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


def load_manifest(path: str | Path) -> SkillManifest:
    """Load ``config/approved-skills.json``. Never writes, never repairs."""
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise ConfigurationError(
            "Approved-skill manifest not found.",
            details={"path": str(manifest_path)},
            remediation="Point [skills].manifest_path at the reviewed manifest, or "
            "disable [skills].enabled.",
        )
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise ConfigurationError(
            "Approved-skill manifest could not be read.",
            details={"path": str(manifest_path), "reason": exc.strerror},
        ) from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            "Approved-skill manifest is not valid UTF-8 JSON.",
            details={"path": str(manifest_path), "reason": str(exc)},
        ) from exc
    return load_manifest_from_mapping(data, source_path=str(manifest_path.resolve()))


# ---------------------------------------------------------------------------
# Projection results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectedFile:
    """One verified file's inert text."""

    resolved_path: str
    sha256: str
    nbytes: int
    text: str


@dataclass(frozen=True)
class ProjectedSkill:
    """One approved skill, verified and rendered as inert text."""

    id: str
    display_name: str
    classification: str
    tier: str
    activation: str
    resolved_path: str
    skill_md_sha256: str
    body: str
    supporting_files: tuple[ProjectedFile, ...]

    @property
    def text(self) -> str:
        blocks = [
            f"----- BEGIN APPROVED GUIDANCE: {self.display_name} [{self.id}] -----",
            self.body.strip("\n"),
        ]
        for support in self.supporting_files:
            name = Path(support.resolved_path).name
            blocks.append(
                f"----- BEGIN APPROVED SUPPORTING REFERENCE: {name} [{self.id}] -----"
            )
            blocks.append(support.text.strip("\n"))
            blocks.append(
                f"----- END APPROVED SUPPORTING REFERENCE: {name} [{self.id}] -----"
            )
        blocks.append(f"----- END APPROVED GUIDANCE: [{self.id}] -----")
        return "\n".join(blocks)


@dataclass(frozen=True)
class SkillProjection:
    """The complete, verified projection for one dispatch or resume."""

    manifest_schema_version: str
    manifest_version: str
    skill_ids: tuple[str, ...]
    skills: tuple[ProjectedSkill, ...]
    text: str
    projected_bytes: int
    approx_tokens: int
    fingerprint: str
    mode: str = "projected"

    def to_record(self) -> SkillPolicyRecord:
        """The persisted evidence the integration lane stores at dispatch (§15)."""
        return SkillPolicyRecord(
            mode="projected",
            manifest_schema_version=self.manifest_schema_version,
            manifest_version=self.manifest_version,
            fingerprint=self.fingerprint,
            skill_ids=list(self.skill_ids),
            projected_bytes=self.projected_bytes,
            approx_tokens=self.approx_tokens,
        )


@dataclass(frozen=True)
class SkillAuditRow:
    """One row of the read-only drift report (§10). Never auto-approves."""

    skill_id: str
    plugin: str
    approved_version: str | None
    approved_path: str
    approved_sha256: str
    current_sha256: str | None
    status: Literal["MATCH", "DRIFT", "MISSING"]
    detail: str = ""


# ---------------------------------------------------------------------------
# Content extraction (§6)
# ---------------------------------------------------------------------------


def _frontmatter_keys(text: str) -> tuple[frozenset[str], str]:
    """Split a leading YAML frontmatter block. Returns (top-level keys, body).

    Deliberately not a YAML parser. The engine only needs to know *which
    mechanisms are declared*; it never consumes a frontmatter value, because
    consuming one is how a document turns into a capability.
    """
    if not text.startswith("---"):
        return frozenset(), text
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return frozenset(), text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            keys = set()
            for line in lines[1:index]:
                if not line or line[0].isspace():
                    continue  # continuation / nested value, not a top-level key
                match = _FRONTMATTER_KEY_RE.match(line)
                if match:
                    keys.add(match.group(1))
            body = "\n".join(lines[index + 1 :])
            return frozenset(keys), body
    raise _content_refusal("frontmatter block is not terminated", {})


def _content_refusal(reason: str, details: dict[str, Any]) -> SkillPolicyViolation:
    payload = {"reason": reason}
    payload.update(details)
    return SkillPolicyViolation(
        "Approved skill content carries a mechanism the projection engine "
        "refuses to handle.",
        details=payload,
        remediation="The engine projects inert text only; it does not strip, "
        "rewrite or sanitize mechanisms. Re-review the skill, or choose a "
        "different approved skill providing the same methodology (§7).",
    )


def _extract_inert_text(raw: bytes, *, skill_id: str, path: str) -> str:
    """Verified bytes -> inert text. Refuses anything mechanism-shaped."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _content_refusal(
            "file is not valid UTF-8",
            {"skill_id": skill_id, "path": path, "error": str(exc)},
        ) from exc

    keys, body = _frontmatter_keys(text)
    disallowed = sorted(keys - ALLOWED_FRONTMATTER_KEYS)
    if disallowed:
        mechanisms = sorted(set(disallowed) & FRONTMATTER_MECHANISM_KEYS)
        raise _content_refusal(
            "frontmatter declares keys that are not inert metadata",
            {
                "skill_id": skill_id,
                "path": path,
                "disallowed_keys": disallowed,
                "known_mechanisms": mechanisms,
                "allowed_keys": sorted(ALLOWED_FRONTMATTER_KEYS),
            },
        )

    for label, pattern in DYNAMIC_COMMAND_MARKERS:
        if pattern.search(body):
            raise _content_refusal(
                "file contains a dynamic command construct",
                {"skill_id": skill_id, "path": path, "construct": label},
            )
    return body


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class SkillProjectionEngine:
    """Deterministic, manifest-driven projection. No discovery, no execution."""

    def __init__(
        self,
        manifest: SkillManifest,
        *,
        max_projected_bytes: int,
        denied_tools: Sequence[str] = (),
        enabled: bool = True,
    ) -> None:
        if max_projected_bytes < 1:
            raise ConfigurationError(
                "max_projected_bytes must be positive.",
                details={"max_projected_bytes": max_projected_bytes},
            )
        self.manifest = manifest
        self.enabled = enabled
        # The stricter of the two caps wins. A manifest may tighten the
        # configured budget; it may never widen it past what the operator set.
        self.max_projected_bytes = min(max_projected_bytes, manifest.max_projected_bytes)
        self.denied_tools: tuple[str, ...] = tuple(denied_tools)

    # -- construction ----------------------------------------------------

    @classmethod
    def from_config(
        cls, config: Config, *, denied_tools: Sequence[str] | None = None
    ) -> "SkillProjectionEngine":
        """Build from dispatcher config.

        ``denied_tools`` should be the *effective* deny list the worker will be
        invoked with (config plus the runner's non-configurable core set). It
        defaults to the configured list, which is the additive half.
        """
        manifest = load_manifest(config.approved_skills_file)
        return cls(
            manifest,
            max_projected_bytes=config.skills.max_projected_bytes,
            denied_tools=(
                list(denied_tools)
                if denied_tools is not None
                else list(config.claude.disallowed_tools)
            ),
            enabled=config.skills.enabled,
        )

    # -- selection (§8) --------------------------------------------------

    def select(
        self,
        *,
        task_kind: TaskKind,
        complexity: Complexity,
        risk: RiskLevel,
        run_kind: RunKind,
        role: WorkerRole = WorkerRole.IMPLEMENTER,
    ) -> tuple[str, ...]:
        """Deterministic selection from envelope facts only. No LLM, no inference.

        Inputs are exactly ``task.kind``, ``routing.complexity``,
        ``routing.risk`` and the dispatcher-owned ``RunKind``. Nothing is
        derived from task text, file paths or repository contents; where the
        mapping is not deterministic the skill is omitted rather than guessed.
        """
        if not self.enabled:
            return ()
        if role is WorkerRole.REVIEWER or run_kind is RunKind.REVIEW:
            # §7.7 / §14: Fable gets no implementation guidance. Sharing the
            # worker's rubric would make review correlated with production.
            return ()

        selection = self.manifest.selection
        chosen: set[str] = set(self.manifest.core_always_on)
        chosen.update(selection.by_task_kind[task_kind.value])
        chosen.update(selection.by_complexity[complexity.value])
        chosen.update(selection.by_risk[risk.value])
        chosen.update(selection.by_run_kind[run_kind.value])
        # Manifest declaration order: stable, order-independent of the union.
        return tuple(sorted(chosen, key=self.manifest.order_of))

    # -- projection (§6) -------------------------------------------------

    def project_for(
        self,
        *,
        task_kind: TaskKind,
        complexity: Complexity,
        risk: RiskLevel,
        run_kind: RunKind,
        role: WorkerRole = WorkerRole.IMPLEMENTER,
    ) -> SkillProjection:
        return self.project(
            self.select(
                task_kind=task_kind,
                complexity=complexity,
                risk=risk,
                run_kind=run_kind,
                role=role,
            )
        )

    def project(self, skill_ids: Sequence[str]) -> SkillProjection:
        """Verify and render the named skills. Refuses everything unapproved."""
        ordered = self._ordered(skill_ids)
        projected: list[ProjectedSkill] = []
        seen_support: set[str] = set()

        for skill in ordered:
            self._assert_projectable(skill)
            body = _extract_inert_text(
                self._verified_bytes(
                    skill.resolved_path,
                    expected_sha256=skill.skill_md_sha256,
                    expected_bytes=skill.skill_md_bytes,
                    skill=skill,
                ),
                skill_id=skill.id,
                path=skill.resolved_path,
            )
            supports: list[ProjectedFile] = []
            for support in skill.projected_supporting_files:
                raw = self._verified_bytes(
                    support.resolved_path,
                    expected_sha256=support.sha256,
                    expected_bytes=support.bytes,
                    skill=skill,
                )
                if support.resolved_path in seen_support:
                    continue  # verified every time, emitted once
                seen_support.add(support.resolved_path)
                supports.append(
                    ProjectedFile(
                        resolved_path=support.resolved_path,
                        sha256=support.sha256,
                        nbytes=len(raw),
                        text=_extract_inert_text(
                            raw, skill_id=skill.id, path=support.resolved_path
                        ),
                    )
                )
            projected.append(
                ProjectedSkill(
                    id=skill.id,
                    display_name=skill.display_name,
                    classification=skill.classification,
                    tier=skill.tier,
                    activation=skill.activation,
                    resolved_path=skill.resolved_path,
                    skill_md_sha256=skill.skill_md_sha256,
                    body=body,
                    supporting_files=tuple(supports),
                )
            )

        text = "\n\n".join(p.text for p in projected) if projected else EMPTY_PROJECTION_TEXT
        nbytes = len(text.encode("utf-8"))
        if nbytes > self.max_projected_bytes:
            raise SkillPolicyViolation(
                "Projected skill guidance exceeds the configured size cap.",
                details={
                    "projected_bytes": nbytes,
                    "max_projected_bytes": self.max_projected_bytes,
                    "skill_ids": [p.id for p in projected],
                },
                remediation="Narrow the selection or raise [skills]."
                "max_projected_bytes deliberately; the cap fails closed rather "
                "than truncating reviewed guidance mid-sentence.",
            )

        return SkillProjection(
            manifest_schema_version=self.manifest.schema_version,
            manifest_version=self.manifest.manifest_version,
            skill_ids=tuple(p.id for p in projected),
            skills=tuple(projected),
            text=text,
            projected_bytes=nbytes,
            approx_tokens=estimate_tokens(nbytes),
            fingerprint=self.fingerprint([p.id for p in projected]),
        )

    # -- fingerprint (§15) -----------------------------------------------

    def fingerprint(self, skill_ids: Iterable[str]) -> str:
        """SHA-256 over the manifest identity and every selected skill's pins.

        Persisted at dispatch and recomputed at resume. It covers the manifest
        version, the selected ids, each resolved path, each SKILL.md hash and
        every co-projected supporting file's hash — so a new plugin version, a
        re-approved hash, a changed support file or a different selection all
        produce a different value.
        """
        lines = [
            FINGERPRINT_VERSION,
            f"mode=inert_text",
            f"manifest_schema_version={self.manifest.schema_version}",
            f"manifest_version={self.manifest.manifest_version}",
        ]
        by_id = self.manifest.by_id
        for skill_id in sorted(set(skill_ids)):
            skill = by_id.get(skill_id)
            if skill is None:
                raise self._unapproved(skill_id)
            lines.append(
                f"skill={skill.id}|{skill.resolved_path}|{skill.skill_md_sha256}"
            )
            for support in sorted(
                skill.projected_supporting_files, key=lambda s: s.resolved_path
            ):
                lines.append(f"support={support.resolved_path}|{support.sha256}")
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()

    def verify(self, record: SkillPolicyRecord) -> SkillProjection:
        """Re-verify a persisted policy on resume. Drift fails closed (§15)."""
        projection = self.project(record.skill_ids)
        if projection.fingerprint != record.fingerprint:
            raise ApprovedSkillChanged(
                "The approved-skill policy changed since this task was dispatched.",
                details={
                    "expected_fingerprint": record.fingerprint,
                    "actual_fingerprint": projection.fingerprint,
                    "recorded_manifest_version": record.manifest_version,
                    "current_manifest_version": self.manifest.manifest_version,
                    "skill_ids": list(record.skill_ids),
                },
                remediation="Return the task to Sol. A resume must not silently "
                "adopt a new manifest, a new plugin version or changed guidance.",
            )
        return projection

    # -- read-only drift audit (§10) -------------------------------------

    def audit(self) -> tuple[SkillAuditRow, ...]:
        """Report approved vs current state. Never approves, never writes."""
        rows: list[SkillAuditRow] = []
        for skill in self.manifest.skills:
            path = Path(skill.resolved_path)
            real = Path(os.path.realpath(skill.resolved_path))
            if not path.is_file():
                rows.append(
                    SkillAuditRow(
                        skill_id=skill.id,
                        plugin=skill.plugin or skill.source_type,
                        approved_version=skill.plugin_version,
                        approved_path=skill.resolved_path,
                        approved_sha256=skill.skill_md_sha256,
                        current_sha256=None,
                        status="MISSING",
                        detail="approved path does not exist",
                    )
                )
                continue
            if real != path:
                rows.append(
                    SkillAuditRow(
                        skill_id=skill.id,
                        plugin=skill.plugin or skill.source_type,
                        approved_version=skill.plugin_version,
                        approved_path=skill.resolved_path,
                        approved_sha256=skill.skill_md_sha256,
                        current_sha256=None,
                        status="DRIFT",
                        detail=f"resolves to {real}",
                    )
                )
                continue
            current = hashlib.sha256(path.read_bytes()).hexdigest()
            drifted_support = [
                s.resolved_path
                for s in skill.supporting_files
                if not Path(s.resolved_path).is_file()
                or hashlib.sha256(Path(s.resolved_path).read_bytes()).hexdigest()
                != s.sha256
            ]
            status: Literal["MATCH", "DRIFT", "MISSING"] = (
                "MATCH" if current == skill.skill_md_sha256 and not drifted_support else "DRIFT"
            )
            rows.append(
                SkillAuditRow(
                    skill_id=skill.id,
                    plugin=skill.plugin or skill.source_type,
                    approved_version=skill.plugin_version,
                    approved_path=skill.resolved_path,
                    approved_sha256=skill.skill_md_sha256,
                    current_sha256=current,
                    status=status,
                    detail=(
                        ""
                        if status == "MATCH"
                        else "supporting files drifted: " + ", ".join(drifted_support)
                        if drifted_support
                        else "SKILL.md hash differs"
                    ),
                )
            )
        return tuple(rows)

    # -- internals -------------------------------------------------------

    def _ordered(self, skill_ids: Sequence[str]) -> tuple[ApprovedSkill, ...]:
        by_id = self.manifest.by_id
        resolved: list[ApprovedSkill] = []
        for skill_id in skill_ids:
            skill = by_id.get(skill_id)
            if skill is None:
                raise self._unapproved(skill_id)
            if skill not in resolved:
                resolved.append(skill)
        return tuple(sorted(resolved, key=lambda s: self.manifest.order_of(s.id)))

    def _unapproved(self, skill_id: str) -> SkillPolicyViolation:
        rejected = {r.id for r in self.manifest.rejected}
        return SkillPolicyViolation(
            "Refused a skill that is not an approved manifest entry.",
            details={
                "skill_id": skill_id,
                "previously_rejected": skill_id in rejected,
                "approved_ids": list(self.manifest.skill_ids),
            },
            remediation="Every projectable skill is an explicit, hash-pinned "
            "manifest entry. No plugin, directory or path family is trusted, and "
            "the engine never discovers skills on disk (§11).",
        )

    def _assert_projectable(self, skill: ApprovedSkill) -> None:
        if skill.classification not in PROJECTABLE_CLASSIFICATIONS:
            raise SkillPolicyViolation(
                "Refused a skill whose classification is not projectable.",
                details={
                    "skill_id": skill.id,
                    "classification": skill.classification,
                    "projectable": sorted(PROJECTABLE_CLASSIFICATIONS),
                },
                remediation="§7 forbids a generic sanitizer: pick a different "
                "approved skill that provides the same methodology safely.",
            )
        missing = [p for p in skill.requires_deny_patterns if p not in self.denied_tools]
        if missing:
            raise SkillPolicyViolation(
                "Refused a skill whose required deny patterns are not in effect.",
                details={
                    "skill_id": skill.id,
                    "missing_deny_patterns": missing,
                    "effective_deny_patterns": list(self.denied_tools),
                },
                remediation="Add the pattern to [claude].disallowed_tools (the list "
                "is additive-only) or drop the skill from the pack; the guidance "
                "names an operation that would otherwise execute.",
            )

    def _verified_bytes(
        self,
        declared: str,
        *,
        expected_sha256: str,
        expected_bytes: int | None,
        skill: ApprovedSkill,
    ) -> bytes:
        """Resolved-path validation + hash verification. Never repairs, never writes."""
        path = Path(declared)
        real = Path(os.path.realpath(declared))
        if real != path:
            # A symlink appeared, a symlinked parent appeared, or the pinned
            # path now points somewhere else. Either way this is not the file
            # that was reviewed; a broken symlink lands here too and is left
            # exactly as found.
            raise ApprovedSkillChanged(
                "An approved skill path no longer resolves to itself.",
                details={
                    "skill_id": skill.id,
                    "approved_path": declared,
                    "resolved_path": str(real),
                    "reason": "symlink or resolved-path change",
                },
                remediation="Re-review the source and re-approve it explicitly; the "
                "dispatcher never follows a moved or symlinked skill path.",
            )
        if not path.is_file():
            raise ApprovedSkillChanged(
                "An approved skill file is missing.",
                details={"skill_id": skill.id, "approved_path": declared},
                remediation="The pinned plugin install may have been updated or "
                "removed. Re-approve against the new install path and hashes.",
            )
        root = Path(os.path.realpath(self.manifest._trusted_root(skill)))
        if root not in path.parents:
            raise ApprovedSkillChanged(
                "An approved skill path no longer belongs to its pinned install.",
                details={
                    "skill_id": skill.id,
                    "approved_path": declared,
                    "pinned_root": str(root),
                },
            )
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ApprovedSkillChanged(
                "An approved skill file could not be read.",
                details={
                    "skill_id": skill.id,
                    "approved_path": declared,
                    "reason": exc.strerror,
                },
            ) from exc
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected_sha256 or (
            expected_bytes is not None and len(raw) != expected_bytes
        ):
            raise ApprovedSkillChanged(
                "An approved skill file no longer matches its pinned hash.",
                details={
                    "skill_id": skill.id,
                    "approved_path": declared,
                    "expected_sha256": expected_sha256,
                    "actual_sha256": actual,
                    "expected_bytes": expected_bytes,
                    "actual_bytes": len(raw),
                },
                remediation="Never recalculate and accept the new hash. Re-review "
                "the changed file and re-approve it in config/approved-skills.json.",
            )
        return raw
