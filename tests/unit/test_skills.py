"""Approved-skill projection engine (GATE 4.5 §6-§11, §15, §16, §18).

Every test in this file is the same test wearing a different hat: *does the
projection engine refuse?* A skill that is not an exact, hash-pinned manifest
entry must never reach a worker prompt, and a skill that drifted by one byte
must fail closed rather than be silently re-approved.

Nothing here executes anything found inside a skill file, and nothing here
writes to ``~/.claude``. The hostile cases are built from synthetic plugin
trees under ``tmp_path``; the real installed skills are only ever read.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sol_claude_dispatcher import skills as skills_mod
from sol_claude_dispatcher.config import load_config_from_mapping
from sol_claude_dispatcher.errors import (
    ApprovedSkillChanged,
    ConfigurationError,
    PolicyViolation,
    SkillPolicyViolation,
)
from sol_claude_dispatcher.models import (
    Complexity,
    RiskLevel,
    RunKind,
    RunMetadata,
    SkillPolicyRecord,
    TaskKind,
    TaskRecord,
    TaskState,
    WorkerRole,
    utc_now,
)
from sol_claude_dispatcher.skills import (
    PROJECTABLE_CLASSIFICATIONS,
    REFUSED_CLASSIFICATIONS,
    SkillProjectionEngine,
    estimate_tokens,
    load_manifest,
    load_manifest_from_mapping,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_MANIFEST = PROJECT_ROOT / "config" / "approved-skills.json"

CORE_IDS = (
    "agent-skills.incremental-implementation",
    "agent-skills.debugging-and-error-recovery",
    "superpowers.test-driven-development",
    "superpowers.verification-before-completion",
)

HINT_ONLY_IDS = (
    "agent-skills.api-and-interface-design",
    "agent-skills.frontend-ui-engineering",
    "agent-skills.observability-and-instrumentation",
)

REJECTED_IDS = (
    "agent-skills.source-driven-development",
    "agent-skills.spec-driven-development",
)


# ---------------------------------------------------------------------------
# Synthetic plugin trees and manifests
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _skill_text(name: str, *, body: str | None = None, frontmatter: str = "") -> str:
    body = body or (
        f"# {name}\n\n"
        "Work in small verifiable increments.\n\n"
        "1. Write the failing test.\n"
        "2. Make it pass.\n"
    )
    return f"---\nname: {name}\ndescription: Test skill {name}.\n{frontmatter}---\n\n{body}"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def tree(tmp_path: Path) -> dict:
    """A synthetic plugin cache with the shapes the trust rules must reject."""
    cache = tmp_path / "cache"
    a1 = cache / "mk-a" / "plug-a" / "1.0.0"
    a2 = cache / "mk-a" / "plug-a" / "2.0.0"
    b1 = cache / "mk-b" / "plug-b" / "1.0.0"

    alpha = _write(a1 / "skills" / "alpha" / "SKILL.md", _skill_text("alpha"))
    # A sibling skill inside the *same* approved plugin. Never approved.
    sibling = _write(a1 / "skills" / "beta" / "SKILL.md", _skill_text("beta"))
    support = _write(
        a1 / "references" / "support.md",
        "# Supporting reference\n\nThe standing bar every increment clears.\n",
    )
    # An unreviewed sibling file in the same references/ directory.
    forbidden = _write(
        a1 / "references" / "orchestration-patterns.md",
        "# Orchestration\n\nSpawn a subagent for each persona.\n",
    )
    # A newer, unreviewed install of the same plugin.
    newer = _write(a2 / "skills" / "alpha" / "SKILL.md", _skill_text("alpha"))
    # A different plugin shipping a skill with the same name.
    impostor = _write(b1 / "skills" / "alpha" / "SKILL.md", _skill_text("alpha"))

    return {
        "cache": cache,
        "install_a": a1,
        "install_a_new": a2,
        "install_b": b1,
        "alpha": alpha,
        "sibling": sibling,
        "support": support,
        "forbidden": forbidden,
        "newer": newer,
        "impostor": impostor,
    }


def _plugin_block(key: str, name: str, marketplace: str, install: Path, version):
    return {
        key: {
            "plugin_name": name,
            "marketplace": marketplace,
            "marketplace_repo": f"example/{marketplace}",
            "plugin_version": version,
            "plugin_version_source": "plugin.json" if version else "absent",
            "plugin_install_id": version or install.name,
            "install_path": str(install),
            "git_commit_sha": None,
            "trusted_scope": "listed_skills_only",
            "untrusted": ["plugin_directory", "sibling_skills", "plugin_runtime"],
        }
    }


def _skill_entry(
    *,
    skill_id: str,
    plugin_key: str,
    plugin_name: str,
    canonical: str,
    resolved: str,
    sha: str,
    nbytes: int,
    classification: str = "SAFE_WORKER_PROCEDURE",
    tier: str = "core",
    activation: str = "always_on",
    activation_profile: dict | None = None,
    supporting_files: list | None = None,
    requires_deny_patterns: list | None = None,
    plugin_version: str | None = "1.0.0",
    install_id: str = "1.0.0",
) -> dict:
    entry = {
        "id": skill_id,
        "display_name": skill_id,
        "source_type": "plugin",
        "plugin": plugin_key,
        "plugin_version": plugin_version,
        "plugin_install_id": install_id,
        "canonical_path": canonical,
        "resolved_path": resolved,
        "resolved_equals_canonical": True,
        "skill_md_sha256": sha,
        "skill_md_bytes": nbytes,
        "supporting_files": supporting_files or [],
        "classification": classification,
        "tier": tier,
        "activation": activation,
        "reviewer_eligible": False,
        "caveats": [],
    }
    if activation_profile is not None:
        entry["activation_profile"] = activation_profile
    if requires_deny_patterns is not None:
        entry["requires_deny_patterns"] = requires_deny_patterns
    return entry


def _empty_selection(**overrides) -> dict:
    selection = {
        "inputs": ["task.kind", "routing.complexity", "routing.risk", "run_kind"],
        "combine": "set_union_with_dedup",
        "by_task_kind": {k.value: [] for k in TaskKind},
        "by_complexity": {c.value: [] for c in Complexity},
        "by_risk": {r.value: [] for r in RiskLevel},
        "by_run_kind": {r.value: [] for r in RunKind},
        "omitted_deliberately": {},
    }
    selection.update(overrides)
    return selection


def _manifest_dict(
    skill_entries: list,
    *,
    plugins: dict,
    core: list | None = None,
    selection: dict | None = None,
    **overrides,
) -> dict:
    data = {
        "schema_version": "1.0",
        "manifest_version": "test.1",
        "generated_at": "2026-08-20",
        "approved_by": "unit-test",
        "approval_note": "synthetic",
        "projection_mode": "inert_text",
        "native_skill_runtime": False,
        "max_projected_bytes": 120000,
        "fail_on_drift": True,
        "drift_error": "ApprovedSkillChanged",
        "policy_error": "SkillPolicyViolation",
        "required_deny_patterns": [],
        "envelope_precedence_preamble_required": True,
        "plugins": plugins,
        "core_always_on": core if core is not None else [e["id"] for e in skill_entries],
        "selection": selection or _empty_selection(),
        "approved_reviewer_skills": [],
        "skills": skill_entries,
        "rejected": [],
        "never_project": [],
    }
    data.update(overrides)
    return data


@pytest.fixture
def simple_manifest(tree) -> dict:
    """One approved skill (``alpha``) inside plugin A, version 1.0.0."""
    alpha = tree["alpha"]
    plugins = _plugin_block("plug-a@mk-a", "plug-a", "mk-a", tree["install_a"], "1.0.0")
    entry = _skill_entry(
        skill_id="plug-a.alpha",
        plugin_key="plug-a@mk-a",
        plugin_name="plug-a",
        canonical="${plug-a.install_path}/skills/alpha/SKILL.md",
        resolved=str(alpha),
        sha=_sha256(alpha),
        nbytes=alpha.stat().st_size,
    )
    return _manifest_dict([entry], plugins=plugins)


def _engine(manifest_data: dict, *, cap: int = 120000, denied=()) -> SkillProjectionEngine:
    manifest = load_manifest_from_mapping(manifest_data)
    return SkillProjectionEngine(manifest, max_projected_bytes=cap, denied_tools=denied)


# ---------------------------------------------------------------------------
# §11 source trust — manifest-driven, never discovered
# ---------------------------------------------------------------------------


class TestSourceTrust:
    def test_exact_approved_plugin_skill_projects(self, simple_manifest, tree):
        engine = _engine(simple_manifest)
        projection = engine.project(["plug-a.alpha"])
        assert projection.skill_ids == ("plug-a.alpha",)
        assert "Write the failing test." in projection.text
        assert projection.projected_bytes > 0

    def test_plugin_cache_root_is_not_trusted(self, simple_manifest, tree):
        """A file living under the same cache root is not thereby approved."""
        engine = _engine(simple_manifest)
        with pytest.raises(SkillPolicyViolation):
            engine.project([str(tree["cache"])])

    def test_sibling_skill_in_same_plugin_denied(self, simple_manifest, tree):
        engine = _engine(simple_manifest)
        assert tree["sibling"].is_file()  # it exists; that is not approval
        with pytest.raises(SkillPolicyViolation):
            engine.project(["plug-a.beta"])

    def test_same_skill_name_from_another_plugin_denied(self, tree):
        """Plugin B ships ``alpha`` too. The pinned entry belongs to plugin A."""
        impostor = tree["impostor"]
        plugins = _plugin_block(
            "plug-a@mk-a", "plug-a", "mk-a", tree["install_a"], "1.0.0"
        )
        entry = _skill_entry(
            skill_id="plug-a.alpha",
            plugin_key="plug-a@mk-a",
            plugin_name="plug-a",
            canonical="${plug-a.install_path}/skills/alpha/SKILL.md",
            resolved=str(impostor),
            sha=_sha256(impostor),
            nbytes=impostor.stat().st_size,
        )
        with pytest.raises(ConfigurationError) as exc:
            load_manifest_from_mapping(_manifest_dict([entry], plugins=plugins))
        assert "install" in str(exc.value.details).lower()

    def test_parent_directory_substitution_denied(self, tree):
        plugins = _plugin_block(
            "plug-a@mk-a", "plug-a", "mk-a", tree["install_a"], "1.0.0"
        )
        outside = tree["cache"] / "mk-a" / "plug-a" / "SKILL.md"
        _write(outside, _skill_text("alpha"))
        entry = _skill_entry(
            skill_id="plug-a.alpha",
            plugin_key="plug-a@mk-a",
            plugin_name="plug-a",
            canonical="${plug-a.install_path}/../SKILL.md",
            resolved=str(outside),
            sha=_sha256(outside),
            nbytes=outside.stat().st_size,
        )
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(_manifest_dict([entry], plugins=plugins))

    def test_dot_dot_traversal_in_path_denied(self, tree, simple_manifest):
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["resolved_path"] = (
            f"{tree['install_a']}/skills/../../../../etc/passwd"
        )
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)

    def test_relative_path_denied(self, simple_manifest):
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["resolved_path"] = "skills/alpha/SKILL.md"
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)

    def test_engine_never_globs_for_skills(self, simple_manifest, tree):
        """A brand-new skill dropped into an approved plugin is invisible."""
        _write(tree["install_a"] / "skills" / "gamma" / "SKILL.md", _skill_text("gamma"))
        engine = _engine(simple_manifest)
        assert engine.manifest.skill_ids == ("plug-a.alpha",)
        with pytest.raises(SkillPolicyViolation):
            engine.project(["plug-a.gamma"])

    def test_new_skill_defaults_denied_in_selection(self, simple_manifest, tree):
        _write(tree["install_a"] / "skills" / "gamma" / "SKILL.md", _skill_text("gamma"))
        engine = _engine(simple_manifest)
        selected = engine.select(
            task_kind=TaskKind.IMPLEMENTATION,
            complexity=Complexity.MEDIUM,
            risk=RiskLevel.MEDIUM,
            run_kind=RunKind.DISPATCH,
        )
        assert "plug-a.gamma" not in selected


class TestSourceFamilies:
    """§11: personal and project skills are pinned to one exact directory."""

    def _entry(self, tmp_path: Path, *, source_type: str, root: Path, skill: Path):
        return {
            "id": f"local.{skill.parent.name}",
            "display_name": "Local Skill",
            "source_type": source_type,
            "source_root": str(root),
            "canonical_path": str(skill),
            "resolved_path": str(skill),
            "resolved_equals_canonical": True,
            "skill_md_sha256": _sha256(skill),
            "skill_md_bytes": skill.stat().st_size,
            "supporting_files": [],
            "classification": "SAFE_REFERENCE",
            "tier": "contextual",
            "activation": "envelope_hint_only",
            "activation_profile": {},
            "reviewer_eligible": False,
            "caveats": [],
        }

    @pytest.mark.parametrize("source_type", ["personal", "project"])
    def test_exact_local_skill_directory_projects(self, tmp_path, source_type):
        root = tmp_path / "home" / ".claude" / "skills" / "house-style"
        skill = _write(root / "SKILL.md", _skill_text("house-style"))
        data = _manifest_dict(
            [self._entry(tmp_path, source_type=source_type, root=root, skill=skill)],
            plugins={},
        )
        engine = _engine(data)
        assert "Write the failing test." in engine.project(["local.house-style"]).text

    def test_local_root_must_be_a_dot_claude_skills_directory(self, tmp_path):
        root = tmp_path / "home" / "anywhere" / "house-style"
        skill = _write(root / "SKILL.md", _skill_text("house-style"))
        data = _manifest_dict(
            [self._entry(tmp_path, source_type="personal", root=root, skill=skill)],
            plugins={},
        )
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)

    def test_local_skill_cannot_reach_outside_its_own_directory(self, tmp_path):
        root = tmp_path / "home" / ".claude" / "skills" / "house-style"
        root.mkdir(parents=True)
        neighbour = _write(
            tmp_path / "home" / ".claude" / "skills" / "other" / "SKILL.md",
            _skill_text("other"),
        )
        entry = self._entry(
            tmp_path, source_type="personal", root=root, skill=neighbour
        )
        entry["id"] = "local.house-style"
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(_manifest_dict([entry], plugins={}))

    def test_local_entry_may_not_name_a_plugin(self, tmp_path, tree):
        root = tmp_path / "home" / ".claude" / "skills" / "house-style"
        skill = _write(root / "SKILL.md", _skill_text("house-style"))
        entry = self._entry(tmp_path, source_type="personal", root=root, skill=skill)
        entry["plugin"] = "plug-a@mk-a"
        plugins = _plugin_block(
            "plug-a@mk-a", "plug-a", "mk-a", tree["install_a"], "1.0.0"
        )
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(_manifest_dict([entry], plugins=plugins))

    def test_plugin_entry_may_not_declare_a_source_root(self, tree, simple_manifest):
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["source_root"] = str(tree["install_a"])
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)


class TestSymlinks:
    def test_symlink_escape_fails(self, tree, simple_manifest, tmp_path):
        """The pinned path resolves outside the pinned plugin install."""
        outside = _write(tmp_path / "outside" / "SKILL.md", _skill_text("evil"))
        target = tree["install_a"] / "skills" / "linked" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(outside)

        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["canonical_path"] = "${plug-a.install_path}/skills/linked/SKILL.md"
        data["skills"][0]["resolved_path"] = str(target)
        data["skills"][0]["skill_md_sha256"] = _sha256(outside)
        data["skills"][0]["skill_md_bytes"] = outside.stat().st_size

        engine = _engine(data)
        with pytest.raises(ApprovedSkillChanged) as exc:
            engine.project(["plug-a.alpha"])
        assert "resolve" in str(exc.value.details).lower() or "symlink" in str(
            exc.value.details
        ).lower()

    def test_broken_symlink_fails_and_is_not_repaired(self, tree, simple_manifest):
        target = tree["install_a"] / "skills" / "dangling" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(tree["install_a"] / "skills" / "nowhere" / "SKILL.md")

        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["canonical_path"] = (
            "${plug-a.install_path}/skills/dangling/SKILL.md"
        )
        data["skills"][0]["resolved_path"] = str(target)

        engine = _engine(data)
        with pytest.raises(ApprovedSkillChanged):
            engine.project(["plug-a.alpha"])
        # Still a broken symlink: the engine never repairs what it refuses.
        assert target.is_symlink()
        assert not target.exists()


# ---------------------------------------------------------------------------
# §10 drift control
# ---------------------------------------------------------------------------


class TestDrift:
    def test_skill_md_hash_drift_fails_closed(self, simple_manifest, tree):
        engine = _engine(simple_manifest)
        tree["alpha"].write_text(_skill_text("alpha", body="# alpha\n\nrewritten\n"))
        with pytest.raises(ApprovedSkillChanged) as exc:
            engine.project(["plug-a.alpha"])
        assert exc.value.details["skill_id"] == "plug-a.alpha"
        assert "expected_sha256" in exc.value.details

    def test_hash_drift_never_rewrites_the_manifest(self, tmp_path, simple_manifest, tree):
        path = tmp_path / "approved-skills.json"
        path.write_text(json.dumps(simple_manifest))
        before = path.read_bytes()
        manifest = load_manifest(path)
        engine = SkillProjectionEngine(manifest, max_projected_bytes=120000)
        tree["alpha"].write_text(_skill_text("alpha", body="# alpha\n\ndrifted\n"))
        with pytest.raises(ApprovedSkillChanged):
            engine.project(["plug-a.alpha"])
        assert path.read_bytes() == before

    def test_missing_file_fails_closed(self, simple_manifest, tree):
        engine = _engine(simple_manifest)
        tree["alpha"].unlink()
        with pytest.raises(ApprovedSkillChanged):
            engine.project(["plug-a.alpha"])

    def test_changed_resolved_path_fails_closed(self, simple_manifest, tree):
        """The approved file moved; the same name now lives in a newer install."""
        engine = _engine(simple_manifest)
        tree["alpha"].unlink()
        assert tree["newer"].is_file()
        with pytest.raises(ApprovedSkillChanged):
            engine.project(["plug-a.alpha"])

    def test_plugin_version_drift_fails_closed(self, tree):
        """Pin 1.0.0; the enabled install is now 2.0.0. Refuse, do not follow."""
        plugins = _plugin_block(
            "plug-a@mk-a", "plug-a", "mk-a", tree["install_a"], "1.0.0"
        )
        entry = _skill_entry(
            skill_id="plug-a.alpha",
            plugin_key="plug-a@mk-a",
            plugin_name="plug-a",
            canonical="${plug-a.install_path}/skills/alpha/SKILL.md",
            resolved=str(tree["alpha"]),
            sha=_sha256(tree["alpha"]),
            nbytes=tree["alpha"].stat().st_size,
        )
        engine = _engine(_manifest_dict([entry], plugins=plugins))
        # The whole 1.0.0 install is replaced by 2.0.0 on disk.
        import shutil

        shutil.rmtree(tree["install_a"])
        with pytest.raises(ApprovedSkillChanged):
            engine.project(["plug-a.alpha"])

    def test_supporting_file_drift_fails_closed(self, tree):
        alpha, support = tree["alpha"], tree["support"]
        plugins = _plugin_block(
            "plug-a@mk-a", "plug-a", "mk-a", tree["install_a"], "1.0.0"
        )
        entry = _skill_entry(
            skill_id="plug-a.alpha",
            plugin_key="plug-a@mk-a",
            plugin_name="plug-a",
            canonical="${plug-a.install_path}/skills/alpha/SKILL.md",
            resolved=str(alpha),
            sha=_sha256(alpha),
            nbytes=alpha.stat().st_size,
            supporting_files=[
                {
                    "path": "${plug-a.install_path}/references/support.md",
                    "resolved_path": str(support),
                    "sha256": _sha256(support),
                    "bytes": support.stat().st_size,
                    "executable": False,
                    "project": True,
                }
            ],
        )
        engine = _engine(_manifest_dict([entry], plugins=plugins))
        assert "standing bar" in engine.project(["plug-a.alpha"]).text

        support.write_text("# Supporting reference\n\ntampered\n")
        with pytest.raises(ApprovedSkillChanged) as exc:
            engine.project(["plug-a.alpha"])
        assert "support.md" in str(exc.value.details)

    def test_drift_error_is_a_dispatcher_error_with_a_stable_code(self):
        err = ApprovedSkillChanged("changed")
        assert err.code == "ApprovedSkillChanged"
        assert err.to_payload()["error"] == "ApprovedSkillChanged"

    def test_policy_violation_is_a_policy_violation_subclass(self):
        assert issubclass(SkillPolicyViolation, PolicyViolation)
        assert SkillPolicyViolation("no").code == "SkillPolicyViolation"


# ---------------------------------------------------------------------------
# §7 classification gate — no generic sanitizer
# ---------------------------------------------------------------------------


class TestClassificationGate:
    @pytest.mark.parametrize("classification", sorted(REFUSED_CLASSIFICATIONS))
    def test_refused_classifications_never_project(
        self, tree, simple_manifest, classification
    ):
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["classification"] = classification
        data["core_always_on"] = []
        engine = _engine(data)
        with pytest.raises(SkillPolicyViolation) as exc:
            engine.project(["plug-a.alpha"])
        assert classification in str(exc.value.details)

    @pytest.mark.parametrize("classification", sorted(PROJECTABLE_CLASSIFICATIONS))
    def test_projectable_classifications_project(
        self, tree, simple_manifest, classification
    ):
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["classification"] = classification
        engine = _engine(data)
        assert engine.project(["plug-a.alpha"]).skill_ids == ("plug-a.alpha",)

    def test_unknown_classification_string_refused_at_load(self, simple_manifest):
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["classification"] = "PROBABLY_FINE"
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)

    def test_refused_classification_cannot_be_core(self, simple_manifest):
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["classification"] = "MANUAL_ONLY"
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)


# ---------------------------------------------------------------------------
# §6 projection semantics — inert text, no mechanisms
# ---------------------------------------------------------------------------


class TestProjectionSemantics:
    def test_frontmatter_is_stripped_from_projected_text(self, simple_manifest):
        engine = _engine(simple_manifest)
        text = engine.project(["plug-a.alpha"]).text
        assert "description: Test skill" not in text
        assert "name: alpha" not in text
        assert "Write the failing test." in text

    @pytest.mark.parametrize(
        "key",
        [
            "allowed-tools",
            "disallowed-tools",
            "tools",
            "context",
            "agent",
            "background",
            "hooks",
            "model",
            "effort",
            "mcp",
            "user-invocable",
        ],
    )
    def test_frontmatter_mechanism_keys_are_refused(self, tree, simple_manifest, key):
        text = _skill_text("alpha", frontmatter=f"{key}: something\n")
        tree["alpha"].write_text(text)
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["skill_md_sha256"] = _sha256(tree["alpha"])
        data["skills"][0]["skill_md_bytes"] = tree["alpha"].stat().st_size
        engine = _engine(data)
        with pytest.raises(SkillPolicyViolation) as exc:
            engine.project(["plug-a.alpha"])
        assert key in str(exc.value.details)

    @pytest.mark.parametrize(
        "body",
        [
            "# alpha\n\nRun !`touch /tmp/sol-skill-gate-SHOULD-NOT-EXIST` now.\n",
            "# alpha\n\n```!\ntouch /tmp/sol-skill-gate-SHOULD-NOT-EXIST\n```\n",
        ],
    )
    def test_dynamic_command_mechanisms_are_refused(self, tree, simple_manifest, body):
        tree["alpha"].write_text(_skill_text("alpha", body=body))
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["skill_md_sha256"] = _sha256(tree["alpha"])
        data["skills"][0]["skill_md_bytes"] = tree["alpha"].stat().st_size
        engine = _engine(data)
        with pytest.raises(SkillPolicyViolation):
            engine.project(["plug-a.alpha"])
        assert not Path("/tmp/sol-skill-gate-SHOULD-NOT-EXIST").exists()

    def test_shell_examples_are_projected_as_inert_text_not_executed(
        self, tree, simple_manifest
    ):
        sentinel = Path("/tmp/sol-skill-gate-SHOULD-NOT-EXIST")
        body = "# alpha\n\n```bash\ntouch /tmp/sol-skill-gate-SHOULD-NOT-EXIST\n```\n"
        tree["alpha"].write_text(_skill_text("alpha", body=body))
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["skill_md_sha256"] = _sha256(tree["alpha"])
        data["skills"][0]["skill_md_bytes"] = tree["alpha"].stat().st_size
        engine = _engine(data)
        projection = engine.project(["plug-a.alpha"])
        assert "touch /tmp/sol-skill-gate-SHOULD-NOT-EXIST" in projection.text
        assert not sentinel.exists()

    def test_non_utf8_file_is_refused(self, tree, simple_manifest):
        tree["alpha"].write_bytes(b"---\nname: alpha\n---\n\n\xff\xfe binary\n")
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["skill_md_sha256"] = _sha256(tree["alpha"])
        data["skills"][0]["skill_md_bytes"] = tree["alpha"].stat().st_size
        engine = _engine(data)
        with pytest.raises(SkillPolicyViolation):
            engine.project(["plug-a.alpha"])

    def test_never_project_entries_cannot_be_supporting_files(self, tree):
        plugins = _plugin_block(
            "plug-a@mk-a", "plug-a", "mk-a", tree["install_a"], "1.0.0"
        )
        forbidden = tree["forbidden"]
        entry = _skill_entry(
            skill_id="plug-a.alpha",
            plugin_key="plug-a@mk-a",
            plugin_name="plug-a",
            canonical="${plug-a.install_path}/skills/alpha/SKILL.md",
            resolved=str(tree["alpha"]),
            sha=_sha256(tree["alpha"]),
            nbytes=tree["alpha"].stat().st_size,
            supporting_files=[
                {
                    "path": "${plug-a.install_path}/references/orchestration-patterns.md",
                    "resolved_path": str(forbidden),
                    "sha256": _sha256(forbidden),
                    "bytes": forbidden.stat().st_size,
                    "executable": False,
                    "project": True,
                }
            ],
        )
        data = _manifest_dict([entry], plugins=plugins)
        data["never_project"] = [
            {
                "path": "${plug-a.install_path}/references/orchestration-patterns.md",
                "resolved_path": str(forbidden),
                "sha256": _sha256(forbidden),
                "bytes": forbidden.stat().st_size,
                "reason": "subagent orchestration catalogue",
            }
        ]
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)

    def test_executable_supporting_file_refused(self, tree):
        plugins = _plugin_block(
            "plug-a@mk-a", "plug-a", "mk-a", tree["install_a"], "1.0.0"
        )
        script = _write(tree["install_a"] / "skills" / "alpha" / "run.sh", "#!/bin/sh\n")
        script.chmod(0o755)
        entry = _skill_entry(
            skill_id="plug-a.alpha",
            plugin_key="plug-a@mk-a",
            plugin_name="plug-a",
            canonical="${plug-a.install_path}/skills/alpha/SKILL.md",
            resolved=str(tree["alpha"]),
            sha=_sha256(tree["alpha"]),
            nbytes=tree["alpha"].stat().st_size,
            supporting_files=[
                {
                    "path": "${plug-a.install_path}/skills/alpha/run.sh",
                    "resolved_path": str(script),
                    "sha256": _sha256(script),
                    "bytes": script.stat().st_size,
                    "executable": True,
                    "project": True,
                }
            ],
        )
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(_manifest_dict([entry], plugins=plugins))


# ---------------------------------------------------------------------------
# Required deny patterns (proposal P1/P2)
# ---------------------------------------------------------------------------


class TestRequiredDenyPatterns:
    def _manifest(self, tree):
        plugins = _plugin_block(
            "plug-a@mk-a", "plug-a", "mk-a", tree["install_a"], "1.0.0"
        )
        entry = _skill_entry(
            skill_id="plug-a.alpha",
            plugin_key="plug-a@mk-a",
            plugin_name="plug-a",
            canonical="${plug-a.install_path}/skills/alpha/SKILL.md",
            resolved=str(tree["alpha"]),
            sha=_sha256(tree["alpha"]),
            nbytes=tree["alpha"].stat().st_size,
            requires_deny_patterns=["Bash(git bisect:*)"],
        )
        return _manifest_dict([entry], plugins=plugins)

    def test_missing_required_deny_pattern_refuses_projection(self, tree):
        engine = _engine(self._manifest(tree), denied=["mcp__*"])
        with pytest.raises(SkillPolicyViolation) as exc:
            engine.project(["plug-a.alpha"])
        assert "Bash(git bisect:*)" in str(exc.value.details)

    def test_present_required_deny_pattern_allows_projection(self, tree):
        engine = _engine(
            self._manifest(tree), denied=["mcp__*", "Bash(git bisect:*)"]
        )
        assert engine.project(["plug-a.alpha"]).skill_ids == ("plug-a.alpha",)


# ---------------------------------------------------------------------------
# §18 size accounting
# ---------------------------------------------------------------------------


class TestSizeAccounting:
    def test_reports_bytes_and_tokens(self, simple_manifest):
        engine = _engine(simple_manifest)
        projection = engine.project(["plug-a.alpha"])
        assert projection.projected_bytes == len(projection.text.encode("utf-8"))
        assert projection.approx_tokens == estimate_tokens(projection.projected_bytes)

    def test_size_cap_fails_closed(self, simple_manifest):
        engine = _engine(simple_manifest, cap=10)
        with pytest.raises(SkillPolicyViolation) as exc:
            engine.project(["plug-a.alpha"])
        assert exc.value.details["max_projected_bytes"] == 10
        assert exc.value.details["projected_bytes"] > 10

    def test_effective_cap_is_the_stricter_of_config_and_manifest(self, simple_manifest):
        data = json.loads(json.dumps(simple_manifest))
        data["max_projected_bytes"] = 10
        engine = _engine(data, cap=120000)
        assert engine.max_projected_bytes == 10
        with pytest.raises(SkillPolicyViolation):
            engine.project(["plug-a.alpha"])

    def test_empty_projection_is_zero_bytes(self, simple_manifest):
        engine = _engine(simple_manifest)
        projection = engine.project([])
        assert projection.projected_bytes == 0
        assert projection.text == ""
        assert projection.skill_ids == ()


# ---------------------------------------------------------------------------
# §8 deterministic selection
# ---------------------------------------------------------------------------


@pytest.fixture
def real_manifest():
    return load_manifest(REAL_MANIFEST)


@pytest.fixture
def real_engine(real_manifest):
    return SkillProjectionEngine(
        real_manifest,
        max_projected_bytes=120000,
        denied_tools=["Bash(git bisect:*)", "Bash(gh:*)"],
    )


def _select(engine, kind, complexity=Complexity.MEDIUM, risk=RiskLevel.MEDIUM,
            run_kind=RunKind.DISPATCH, role=WorkerRole.IMPLEMENTER):
    return engine.select(
        task_kind=kind,
        complexity=complexity,
        risk=risk,
        run_kind=run_kind,
        role=role,
    )


class TestSelection:
    def test_core_four_always_on(self, real_engine):
        selected = _select(real_engine, TaskKind.IMPLEMENTATION)
        assert set(CORE_IDS) <= set(selected)

    @pytest.mark.parametrize("model_alias", ["sonnet", "opus"])
    def test_core_guidance_reaches_both_worker_models(self, real_engine, model_alias):
        """Selection depends on envelope facts only, never on the routed model."""
        low = _select(
            real_engine, TaskKind.IMPLEMENTATION, Complexity.LOW, RiskLevel.LOW
        )
        high = _select(
            real_engine, TaskKind.IMPLEMENTATION, Complexity.HIGH, RiskLevel.CRITICAL
        )
        # Sonnet-routed (low/low) and Opus-routed (high/critical) both get CORE.
        assert set(CORE_IDS) <= set(low)
        assert set(CORE_IDS) <= set(high)
        assert model_alias in {"sonnet", "opus"}

    def test_security_sensitive_adds_hardening(self, real_engine):
        selected = _select(real_engine, TaskKind.SECURITY_SENSITIVE)
        assert "agent-skills.security-and-hardening" in selected

    def test_refactor_adds_simplification_and_review(self, real_engine):
        selected = _select(real_engine, TaskKind.REFACTOR)
        assert "agent-skills.code-simplification" in selected
        assert "agent-skills.code-review-and-quality" in selected
        assert "agent-skills.planning-and-task-breakdown" not in selected

    def test_large_refactor_adds_planning(self, real_engine):
        selected = _select(real_engine, TaskKind.LARGE_REFACTOR)
        assert "agent-skills.planning-and-task-breakdown" in selected

    def test_migration_maps_without_a_spec_substitute(self, real_engine):
        selected = _select(real_engine, TaskKind.MIGRATION)
        assert "agent-skills.deprecation-and-migration" in selected
        assert "agent-skills.planning-and-task-breakdown" in selected
        assert not any("spec-driven" in s for s in selected)

    def test_high_complexity_adds_planning(self, real_engine):
        selected = _select(real_engine, TaskKind.IMPLEMENTATION, Complexity.HIGH)
        assert "agent-skills.planning-and-task-breakdown" in selected

    @pytest.mark.parametrize("risk", [RiskLevel.HIGH, RiskLevel.CRITICAL])
    def test_high_risk_adds_code_review(self, real_engine, risk):
        selected = _select(real_engine, TaskKind.IMPLEMENTATION, risk=risk)
        assert "agent-skills.code-review-and-quality" in selected

    def test_high_risk_does_not_infer_security(self, real_engine):
        selected = _select(
            real_engine, TaskKind.IMPLEMENTATION, risk=RiskLevel.CRITICAL
        )
        assert "agent-skills.security-and-hardening" not in selected

    def test_resume_adds_receiving_code_review(self, real_engine):
        selected = _select(
            real_engine, TaskKind.IMPLEMENTATION, run_kind=RunKind.RESUME
        )
        assert "superpowers.receiving-code-review" in selected

    def test_dispatch_does_not_add_receiving_code_review(self, real_engine):
        selected = _select(real_engine, TaskKind.IMPLEMENTATION)
        assert "superpowers.receiving-code-review" not in selected

    @pytest.mark.parametrize("kind", [TaskKind.CONCURRENCY, TaskKind.DOCS])
    def test_deliberately_omitted_kinds_get_core_only(self, real_engine, kind):
        selected = _select(real_engine, kind, Complexity.LOW, RiskLevel.LOW)
        assert set(selected) == set(CORE_IDS)

    def test_irrelevant_contextual_guidance_is_absent(self, real_engine):
        selected = set(_select(real_engine, TaskKind.IMPLEMENTATION))
        for absent in (
            "agent-skills.security-and-hardening",
            "agent-skills.code-simplification",
            "agent-skills.deprecation-and-migration",
            "agent-skills.frontend-ui-engineering",
        ):
            assert absent not in selected

    def test_envelope_hint_only_skills_are_never_auto_selected(self, real_engine):
        for kind in TaskKind:
            for complexity in Complexity:
                for risk in RiskLevel:
                    for run_kind in RunKind:
                        selected = _select(
                            real_engine, kind, complexity, risk, run_kind
                        )
                        for hint_only in HINT_ONLY_IDS:
                            assert hint_only not in selected

    def test_fable_gets_no_skills(self, real_engine):
        assert _select(real_engine, TaskKind.IMPLEMENTATION, role=WorkerRole.REVIEWER) == ()
        assert _select(real_engine, TaskKind.REFACTOR, run_kind=RunKind.REVIEW) == ()

    def test_fable_projection_is_empty(self, real_engine):
        projection = real_engine.project_for(
            task_kind=TaskKind.REFACTOR,
            complexity=Complexity.HIGH,
            risk=RiskLevel.CRITICAL,
            run_kind=RunKind.REVIEW,
            role=WorkerRole.REVIEWER,
        )
        assert projection.skill_ids == ()
        assert projection.text == ""

    def test_selection_is_deterministic_and_order_independent(self, real_engine):
        first = _select(real_engine, TaskKind.LARGE_REFACTOR, Complexity.HIGH,
                        RiskLevel.CRITICAL, RunKind.RESUME)
        second = _select(real_engine, TaskKind.LARGE_REFACTOR, Complexity.HIGH,
                         RiskLevel.CRITICAL, RunKind.RESUME)
        assert first == second
        assert len(first) == len(set(first))

    def test_rejected_candidates_are_never_selected(self, real_engine):
        for kind in TaskKind:
            for run_kind in RunKind:
                selected = _select(real_engine, kind, run_kind=run_kind)
                for rejected in REJECTED_IDS:
                    assert rejected not in selected

    def test_disabled_engine_selects_nothing(self, real_manifest):
        engine = SkillProjectionEngine(
            real_manifest, max_projected_bytes=120000, enabled=False
        )
        assert _select(engine, TaskKind.IMPLEMENTATION) == ()
        assert engine.project_for(
            task_kind=TaskKind.IMPLEMENTATION,
            complexity=Complexity.MEDIUM,
            risk=RiskLevel.MEDIUM,
            run_kind=RunKind.DISPATCH,
        ).text == ""


# ---------------------------------------------------------------------------
# §15 policy fingerprint
# ---------------------------------------------------------------------------


class TestFingerprint:
    def test_fingerprint_is_stable(self, simple_manifest):
        a = _engine(simple_manifest).project(["plug-a.alpha"]).fingerprint
        b = _engine(simple_manifest).project(["plug-a.alpha"]).fingerprint
        assert a == b
        assert len(a) == 64

    def test_fingerprint_changes_with_selection(self, tree, simple_manifest):
        beta = tree["sibling"]
        data = json.loads(json.dumps(simple_manifest))
        data["skills"].append(
            _skill_entry(
                skill_id="plug-a.beta",
                plugin_key="plug-a@mk-a",
                plugin_name="plug-a",
                canonical="${plug-a.install_path}/skills/beta/SKILL.md",
                resolved=str(beta),
                sha=_sha256(beta),
                nbytes=beta.stat().st_size,
            )
        )
        engine = _engine(data)
        one = engine.project(["plug-a.alpha"]).fingerprint
        two = engine.project(["plug-a.alpha", "plug-a.beta"]).fingerprint
        assert one != two

    def test_fingerprint_changes_when_an_approved_hash_is_reapproved(
        self, tree, simple_manifest
    ):
        before = _engine(simple_manifest).project(["plug-a.alpha"]).fingerprint
        tree["alpha"].write_text(_skill_text("alpha", body="# alpha\n\nnew text\n"))
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["skill_md_sha256"] = _sha256(tree["alpha"])
        data["skills"][0]["skill_md_bytes"] = tree["alpha"].stat().st_size
        after = _engine(data).project(["plug-a.alpha"]).fingerprint
        assert before != after

    def test_fingerprint_covers_supporting_files(self, tree):
        alpha, support = tree["alpha"], tree["support"]
        plugins = _plugin_block(
            "plug-a@mk-a", "plug-a", "mk-a", tree["install_a"], "1.0.0"
        )

        def build(support_sha):
            entry = _skill_entry(
                skill_id="plug-a.alpha",
                plugin_key="plug-a@mk-a",
                plugin_name="plug-a",
                canonical="${plug-a.install_path}/skills/alpha/SKILL.md",
                resolved=str(alpha),
                sha=_sha256(alpha),
                nbytes=alpha.stat().st_size,
                supporting_files=[
                    {
                        "path": "${plug-a.install_path}/references/support.md",
                        "resolved_path": str(support),
                        "sha256": support_sha,
                        "bytes": support.stat().st_size,
                        "executable": False,
                        "project": True,
                    }
                ],
            )
            return _manifest_dict([entry], plugins=plugins)

        first = _engine(build(_sha256(support))).project(["plug-a.alpha"]).fingerprint
        support.write_text("# Supporting reference\n\nrevised text\n")
        second = _engine(build(_sha256(support))).project(["plug-a.alpha"]).fingerprint
        assert first != second

    def test_verify_accepts_the_same_policy(self, simple_manifest):
        engine = _engine(simple_manifest)
        record = engine.project(["plug-a.alpha"]).to_record()
        again = engine.verify(record)
        assert again.fingerprint == record.fingerprint

    def test_verify_refuses_drift(self, simple_manifest, tree):
        engine = _engine(simple_manifest)
        record = engine.project(["plug-a.alpha"]).to_record()
        tree["alpha"].write_text(_skill_text("alpha", body="# alpha\n\nchanged\n"))
        with pytest.raises(ApprovedSkillChanged):
            engine.verify(record)

    def test_verify_refuses_a_reapproved_manifest(self, simple_manifest, tree):
        record = _engine(simple_manifest).project(["plug-a.alpha"]).to_record()
        tree["alpha"].write_text(_skill_text("alpha", body="# alpha\n\nchanged\n"))
        data = json.loads(json.dumps(simple_manifest))
        data["skills"][0]["skill_md_sha256"] = _sha256(tree["alpha"])
        data["skills"][0]["skill_md_bytes"] = tree["alpha"].stat().st_size
        data["manifest_version"] = "test.2"
        with pytest.raises(ApprovedSkillChanged):
            _engine(data).verify(record)

    def test_record_round_trips_through_json(self, simple_manifest):
        record = _engine(simple_manifest).project(["plug-a.alpha"]).to_record()
        restored = type(record).model_validate(json.loads(record.model_dump_json()))
        assert restored == record


# ---------------------------------------------------------------------------
# The shipped manifest
# ---------------------------------------------------------------------------


class TestShippedManifest:
    def test_manifest_is_source_controlled_and_loads(self, real_manifest):
        assert REAL_MANIFEST.is_file()
        assert real_manifest.schema_version == "1.0"
        assert real_manifest.projection_mode == "inert_text"
        assert real_manifest.native_skill_runtime is False
        assert real_manifest.fail_on_drift is True

    def test_manifest_holds_the_thirteen_approved_entries(self, real_manifest):
        assert len(real_manifest.skills) == 13
        ids = set(real_manifest.skill_ids)
        assert set(CORE_IDS) <= ids
        assert set(HINT_ONLY_IDS) <= ids

    def test_rejected_candidates_are_absent_from_the_approved_set(self, real_manifest):
        ids = set(real_manifest.skill_ids)
        for rejected in REJECTED_IDS:
            assert rejected not in ids
        rejected_ids = {r.id for r in real_manifest.rejected}
        for rejected in REJECTED_IDS:
            assert rejected in rejected_ids

    def test_agent_skills_tdd_is_rejected_in_favour_of_superpowers(self, real_manifest):
        rejected_ids = {r.id for r in real_manifest.rejected}
        assert "agent-skills.test-driven-development" in rejected_ids
        assert "superpowers.test-driven-development" in real_manifest.skill_ids

    def test_no_entry_is_reviewer_eligible(self, real_manifest):
        assert real_manifest.approved_reviewer_skills == ()
        assert all(s.reviewer_eligible is False for s in real_manifest.skills)

    def test_every_entry_carries_the_section_nine_fields(self, real_manifest):
        for skill in real_manifest.skills:
            assert skill.id and skill.display_name
            assert skill.source_type == "plugin"
            assert skill.plugin in real_manifest.plugins
            assert skill.plugin_install_id
            assert skill.canonical_path.startswith("${")
            assert skill.resolved_path.startswith("/")
            assert len(skill.skill_md_sha256) == 64
            assert skill.skill_md_bytes > 0
            assert skill.classification in PROJECTABLE_CLASSIFICATIONS
            assert skill.activation in {"always_on", "contextual", "envelope_hint_only"}
            for support in skill.supporting_files:
                assert len(support.sha256) == 64

    def test_agent_skills_version_gap_is_recorded_not_invented(self, real_manifest):
        plugin = real_manifest.plugins["agent-skills@addy-agent-skills"]
        assert plugin.plugin_version is None
        assert plugin.plugin_version_source == "absent"
        assert plugin.plugin_version_note
        assert plugin.plugin_install_id == "70b7506ce90e"

    def test_required_deny_patterns_are_declared(self, real_manifest):
        assert "Bash(git bisect:*)" in real_manifest.required_deny_patterns
        assert "Bash(gh:*)" in real_manifest.required_deny_patterns

    def test_never_project_list_names_the_orchestration_catalogue(self, real_manifest):
        paths = " ".join(n.path for n in real_manifest.never_project)
        assert "orchestration-patterns.md" in paths

    @pytest.mark.skipif(
        not Path(
            "/home/dev/.claude/plugins/cache/addy-agent-skills/agent-skills/70b7506ce90e"
        ).is_dir(),
        reason="approved plugin install not present on this host",
    )
    def test_pinned_hashes_match_the_installed_files(self, real_manifest):
        for skill in real_manifest.skills:
            path = Path(skill.resolved_path)
            assert path.is_file(), skill.id
            assert _sha256(path) == skill.skill_md_sha256, skill.id
            assert path.stat().st_size == skill.skill_md_bytes, skill.id

    @pytest.mark.skipif(
        not Path(
            "/home/dev/.claude/plugins/cache/addy-agent-skills/agent-skills/70b7506ce90e"
        ).is_dir(),
        reason="approved plugin install not present on this host",
    )
    def test_core_bundle_projects_within_budget(self, real_engine):
        projection = real_engine.project_for(
            task_kind=TaskKind.IMPLEMENTATION,
            complexity=Complexity.MEDIUM,
            risk=RiskLevel.MEDIUM,
            run_kind=RunKind.DISPATCH,
        )
        assert projection.skill_ids == tuple(
            i for i in projection.skill_ids
        )  # stable order
        assert set(projection.skill_ids) == set(CORE_IDS)
        assert 0 < projection.projected_bytes < 120000
        assert projection.approx_tokens > 0

    @pytest.mark.skipif(
        not Path(
            "/home/dev/.claude/plugins/cache/addy-agent-skills/agent-skills/70b7506ce90e"
        ).is_dir(),
        reason="approved plugin install not present on this host",
    )
    def test_worst_case_profile_stays_under_the_cap(self, real_engine):
        projection = real_engine.project_for(
            task_kind=TaskKind.LARGE_REFACTOR,
            complexity=Complexity.HIGH,
            risk=RiskLevel.CRITICAL,
            run_kind=RunKind.RESUME,
        )
        assert projection.projected_bytes < 120000

    @pytest.mark.skipif(
        not Path(
            "/home/dev/.claude/plugins/cache/addy-agent-skills/agent-skills/70b7506ce90e"
        ).is_dir(),
        reason="approved plugin install not present on this host",
    )
    def test_shared_supporting_file_is_deduped(self, real_engine):
        projection = real_engine.project(
            [
                "agent-skills.incremental-implementation",
                "agent-skills.planning-and-task-breakdown",
            ]
        )
        # Emitted once even though both skills declare it. (The two skill
        # bodies each *mention* the filename; only the projected copy counts.)
        assert (
            projection.text.count(
                "BEGIN APPROVED SUPPORTING REFERENCE: definition-of-done.md"
            )
            == 1
        )
        supports = [
            s.resolved_path
            for skill in projection.skills
            for s in skill.supporting_files
        ]
        assert len(supports) == len(set(supports))

    @pytest.mark.skipif(
        not Path(
            "/home/dev/.claude/plugins/cache/addy-agent-skills/agent-skills/70b7506ce90e"
        ).is_dir(),
        reason="approved plugin install not present on this host",
    )
    def test_audit_reports_match_for_every_entry(self, real_engine):
        rows = real_engine.audit()
        assert len(rows) == 13
        assert all(row.status == "MATCH" for row in rows)
        agent_rows = [r for r in rows if r.plugin.startswith("agent-skills")]
        assert all(r.approved_version is None for r in agent_rows)


# ---------------------------------------------------------------------------
# Config surface
# ---------------------------------------------------------------------------


def _config(skills_section: dict | None, git_repo: Path):
    data = {
        "dispatcher": {"state_dir": "./state"},
        "models": {"sonnet": "sonnet", "opus": "opus", "fable": "fable"},
        "routing": {"default_model": "sonnet"},
        "security": {"allowed_repository_roots": [str(git_repo)]},
    }
    if skills_section is not None:
        data["skills"] = skills_section
    return load_config_from_mapping(data, project_root=PROJECT_ROOT)


class TestSkillsConfigSection:
    def test_absent_section_defaults_to_disabled(self, git_repo):
        config = _config(None, git_repo)
        assert config.skills.enabled is False
        assert config.skills.mode == "projected"

    def test_valid_section_loads(self, git_repo):
        config = _config(
            {
                "enabled": True,
                "mode": "projected",
                "fail_on_drift": True,
                "max_projected_bytes": 72000,
                "manifest_path": "./config/approved-skills.json",
            },
            git_repo,
        )
        assert config.skills.enabled is True
        assert config.skills.max_projected_bytes == 72000
        assert config.approved_skills_file == REAL_MANIFEST

    def test_the_old_120000_cap_is_now_refused(self, git_repo):
        """BLOCKER B1: 120,000 is above what one argv element can carry.

        It used to load. Composed with the guidance cap and the dispatcher's own
        policy text it reached 184,718 bytes, 41% above the measured 131,071-byte
        Linux limit on a single argv element, so the worker never started. See
        ``tests/unit/test_context_size_limit.py``.
        """
        with pytest.raises(ConfigurationError):
            _config({"enabled": True, "max_projected_bytes": 120000}, git_repo)

    def test_native_mode_is_refused(self, git_repo):
        with pytest.raises(ConfigurationError) as exc:
            _config({"enabled": True, "mode": "native"}, git_repo)
        assert "native" in str(exc.value.details).lower()

    def test_unknown_key_is_refused(self, git_repo):
        with pytest.raises(ConfigurationError):
            _config({"enabled": True, "allow_unapproved": True}, git_repo)

    def test_fail_on_drift_cannot_be_disabled(self, git_repo):
        with pytest.raises(ConfigurationError) as exc:
            _config({"enabled": True, "fail_on_drift": False}, git_repo)
        assert "drift" in str(exc.value.details).lower()

    def test_cap_must_be_positive(self, git_repo):
        with pytest.raises(ConfigurationError):
            _config({"enabled": True, "max_projected_bytes": 0}, git_repo)

    def test_cap_has_a_hard_ceiling(self, git_repo):
        with pytest.raises(ConfigurationError):
            _config({"enabled": True, "max_projected_bytes": 10_000_000}, git_repo)

    def test_engine_from_config(self, git_repo):
        config = _config(
            {"enabled": True, "manifest_path": "./config/approved-skills.json"},
            git_repo,
        )
        engine = SkillProjectionEngine.from_config(config)
        assert engine.enabled is True
        assert engine.max_projected_bytes <= 120000

    def test_engine_from_config_uses_configured_deny_list(self, git_repo):
        config = _config(
            {"enabled": True, "manifest_path": "./config/approved-skills.json"},
            git_repo,
        )
        engine = SkillProjectionEngine.from_config(config)
        assert "Bash(git bisect:*)" in engine.denied_tools
        assert "Bash(gh:*)" in engine.denied_tools

    def test_skill_tool_is_never_granted_to_workers(self, git_repo):
        config = _config({"enabled": True}, git_repo)
        assert "Skill" not in config.claude.worker_tools
        assert "Skill" not in config.claude.reviewer_tools

    def test_example_config_carries_the_skills_section(self):
        text = (PROJECT_ROOT / "config" / "dispatcher.example.toml").read_text()
        assert "[skills]" in text
        assert 'mode = "projected"' in text


class TestPersistedPolicy:
    """The record the integration lane stores at dispatch and checks on resume."""

    def test_task_record_accepts_a_skill_policy(self, simple_manifest):
        record = _engine(simple_manifest).project(["plug-a.alpha"]).to_record()
        task = TaskRecord(
            schema_version="1.0",
            task_id="t",
            state=TaskState.RUNNING,
            created_at=utc_now(),
            updated_at=utc_now(),
            skill_policy=record,
        )
        assert task.skill_policy is not None
        assert task.skill_policy.fingerprint == record.fingerprint

    def test_task_record_without_a_skill_policy_still_loads(self):
        """Records persisted before skill projection existed must keep loading."""
        task = TaskRecord(
            schema_version="1.0",
            task_id="t",
            state=TaskState.CREATED,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        assert task.skill_policy is None

    def test_run_metadata_carries_the_fingerprint(self, simple_manifest):
        record = _engine(simple_manifest).project(["plug-a.alpha"]).to_record()
        metadata = RunMetadata(
            run_id="r",
            run_index=1,
            task_id="t",
            kind=RunKind.DISPATCH,
            role=WorkerRole.IMPLEMENTER,
            model="sonnet",
            session_id="s",
            started_at=utc_now(),
            skill_policy_fingerprint=record.fingerprint,
        )
        assert metadata.skill_policy_fingerprint == record.fingerprint

    def test_run_metadata_without_a_fingerprint_still_loads(self):
        metadata = RunMetadata(
            run_id="r",
            run_index=1,
            task_id="t",
            kind=RunKind.DISPATCH,
            role=WorkerRole.IMPLEMENTER,
            model="sonnet",
            session_id="s",
            started_at=utc_now(),
        )
        assert metadata.skill_policy_fingerprint is None

    def test_record_rejects_a_malformed_fingerprint(self):
        with pytest.raises(Exception):
            SkillPolicyRecord(
                manifest_schema_version="1.0",
                manifest_version="x",
                fingerprint="not-a-hash",
            )


class TestModuleShape:
    def test_module_exposes_no_execution_helper(self):
        exported = set(skills_mod.__all__)
        for forbidden in ("run", "execute", "shell", "discover", "glob_skills"):
            assert not any(forbidden in name.lower() for name in exported)

    def test_native_runtime_is_not_offered(self):
        assert not hasattr(skills_mod, "enable_native_skills")
