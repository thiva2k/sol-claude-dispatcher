"""Project-guidance projection engine (GATE 4.5 ADDENDUM §1-§20, RULINGS §1-§7).

Same shape as ``test_skills.py``, different subject: *does the guidance engine
refuse?* A CLAUDE.md/AGENTS.md that is not an exact, hash-pinned manifest entry
must never reach a worker prompt; a stale worktree copy must never become a
source merely because it is physically reachable (RULINGS §3); and a subproject
whose local instructions were never reviewed must fail closed rather than
silently fall back to root-only guidance (RULINGS §7).

Nothing here writes to ``/home/dev/full-voice-agent``. The hostile cases are
built from synthetic repositories under ``tmp_path``; the real repository is
only ever read and hashed (ADDENDUM §19).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from sol_claude_dispatcher import project_guidance as pg_mod
from sol_claude_dispatcher.config import load_config_from_mapping
from sol_claude_dispatcher.errors import (
    ConfigurationError,
    PolicyViolation,
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
from sol_claude_dispatcher.models import (
    ProjectGuidanceRecord,
    RunKind,
    RunMetadata,
    TaskRecord,
    TaskState,
    WorkerRole,
    utc_now,
)
from sol_claude_dispatcher.project_guidance import (
    DISPATCHER_AUTHORED,
    MANDATORY_DENY_ABSOLUTE_TREES,
    MANDATORY_DENY_PREFIXES,
    SOURCE_DERIVED,
    GuidanceAudience,
    ProjectGuidanceEngine,
    ProvenanceSeparationError,
    RepositoryIdentity,
    StrictContentScanner,
    estimate_tokens,
    load_manifest,
    load_manifest_from_mapping,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_MANIFEST = PROJECT_ROOT / "config" / "approved-guidance.json"
REAL_TARGET_REPO = Path("/home/dev/full-voice-agent")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ---------------------------------------------------------------------------
# Synthetic repository + manifest
# ---------------------------------------------------------------------------

#: Sentinel lines. Every one of them is asserted somewhere, either as "must be
#: present" or as "must be absent". Emptying one turns a test red, not green.
ROOT_AGENTS_TEXT = "ROOT-AGENTS-SENTINEL\nssh into the production host and restart it.\n"
ROOT_CLAUDE_TEXT = "ROOT-CLAUDE-SENTINEL\nThis root pair has drifted on purpose.\n"
CONTRIBUTING_TEXT = "CONTRIB-SENTINEL\ngit push is a release in this repository.\n"
KAVYA_TEXT = "KAVYA-SOURCE-SENTINEL\nnormalize_whatsapp lives in handover.py.\n"
SLIC_TEXT = "SLIC-SOURCE-SENTINEL\n"
FLICO_TEXT = "FLICO-SOURCE-SENTINEL\n"
BSL_TEXT = "BSL-SOURCE-SENTINEL\n"
TAW_TEXT = "TAW-FOREIGN-SENTINEL\n"
SHADOW_TEXT = "SHADOW-WORKTREE-SENTINEL — a stale copy that must never be projected.\n"
NESTED_TEXT = "NESTED-UNAPPROVED-SENTINEL\n"

ROOT_POLICY_ARTIFACT = (
    "ROOT-POLICY-ARTIFACT\n"
    "PROVENANCE CLASS: DISPATCHER_AUTHORED.\n"
    "Never open a .env file. SSH into production is not your authority.\n"
    "Do not run docker compose, systemctl, or git push.\n"
)
ROOT_SOURCE_ARTIFACT = (
    "ROOT-SOURCE-ARTIFACT\n"
    "PROVENANCE CLASS: SOURCE_DERIVED.\n"
    "Read graphify-out/GRAPH_REPORT.md before broad exploration.\n"
    "Production containers run Python 3.11.\n"
)
KAVYA_POLICY_ARTIFACT = "KAVYA-POLICY-ARTIFACT\nDISPATCHER_AUTHORED framing.\n"
KAVYA_SOURCE_ARTIFACT = (
    "KAVYA-SOURCE-ARTIFACT\n"
    "Handover normalisation lives in Kavya/handover.py::normalize_whatsapp.\n"
    "MAX_TOOL_ROUNDS = 5\n"
)
SLIC_POLICY_ARTIFACT = "SLIC-POLICY-ARTIFACT\n"
SLIC_SOURCE_ARTIFACT = "SLIC-SOURCE-ARTIFACT\nSLIC session TTL is behavioural.\n"
FLICO_POLICY_ARTIFACT = "FLICO-POLICY-ARTIFACT\n"
FLICO_SOURCE_ARTIFACT = "FLICO-SOURCE-ARTIFACT\nRows are the source, prose is generated.\n"
ROOT_REVIEW_POLICY_ARTIFACT = "ROOT-REVIEW-POLICY-ARTIFACT\n"
ROOT_REVIEW_SOURCE_ARTIFACT = (
    "ROOT-REVIEW-SOURCE-ARTIFACT\nProduction containers run Python 3.11.\n"
)
KAVYA_REVIEW_POLICY_ARTIFACT = "KAVYA-REVIEW-POLICY-ARTIFACT\n"
KAVYA_REVIEW_SOURCE_ARTIFACT = "KAVYA-REVIEW-SOURCE-ARTIFACT\n"
GATED_OFF_ARTIFACT = (
    "GATED-OFF-ARTIFACT\nReport GRAPH_REFRESH_REQUIRED: <files>. Do not refresh.\n"
)
GATED_ON_ARTIFACT = "GATED-ON-ARTIFACT\nRun `graphify update .` and nothing else.\n"
SCOPE_NOT_APPROVED_ARTIFACT = (
    "PROJECT-GUIDANCE SCOPE NOT APPROVED\n"
    'This task intersects the scope "{scope_prefix}" (logical id "{logical_id}").\n'
    "There is deliberately NO fallback to root-only guidance.\n"
)

STRICT_PATTERNS = [
    r"\.env",
    r"\b[A-Za-z0-9_]*(API_KEY|AUTH_TOKEN|_TOKEN|_SECRET|PASSWORD|_SID|CREDENTIALS)\b",
    r"\bssh\b|\broot@\b|\bsystemctl\b|\bdocker (compose|restart|login)\b",
    r"\bgit (push|merge|rebase|commit|tag)\b|\bgh workflow run\b|\bgh pr\b",
    r"\bclickup\b|webhook/.*\b(restore|PUT)\b",
    r"\b[0-9]{1,3}(\.[0-9]{1,3}){3}\b",
    r"sk-ant-|Bearer |AC[0-9a-f]{32}",
]


@pytest.fixture
def repo(tmp_path: Path) -> dict:
    """A synthetic target repository plus a dispatcher project root."""
    top = tmp_path / "target"
    disp = tmp_path / "dispatcher"

    files = {
        "AGENTS.md": ROOT_AGENTS_TEXT,
        "CLAUDE.md": ROOT_CLAUDE_TEXT,
        "CONTRIBUTING.md": CONTRIBUTING_TEXT,
        "Kavya/CLAUDE.md": KAVYA_TEXT,
        "Kavya/AGENTS.md": KAVYA_TEXT,
        "SLIC Agent/CLAUDE.md": SLIC_TEXT,
        "SLIC Agent/AGENTS.md": SLIC_TEXT,
        "Flico Agent/CLAUDE.md": FLICO_TEXT,
        "Flico Agent/AGENTS.md": FLICO_TEXT,
        "BSL Agent/CLAUDE.md": BSL_TEXT,
        "BSL Agent/AGENTS.md": BSL_TEXT,
        "Taskforce_AI_Website/CLAUDE.md": TAW_TEXT,
        # RULINGS §3: a *different-hash* shadow copy inside an in-repo worktree.
        ".claude/worktrees/agent-aa383920556fd0f25/Kavya/CLAUDE.md": SHADOW_TEXT,
        "graphify-out/GRAPH_REPORT.md": "graph report\n",
    }
    for rel, text in files.items():
        _write(top / rel, text)

    artifacts = {
        "config/guidance/worker/root.policy.txt": ROOT_POLICY_ARTIFACT,
        "config/guidance/worker/root.source.txt": ROOT_SOURCE_ARTIFACT,
        "config/guidance/worker/kavya.policy.txt": KAVYA_POLICY_ARTIFACT,
        "config/guidance/worker/kavya.source.txt": KAVYA_SOURCE_ARTIFACT,
        "config/guidance/worker/slic.policy.txt": SLIC_POLICY_ARTIFACT,
        "config/guidance/worker/slic.source.txt": SLIC_SOURCE_ARTIFACT,
        "config/guidance/worker/flico.policy.txt": FLICO_POLICY_ARTIFACT,
        "config/guidance/worker/flico.source.txt": FLICO_SOURCE_ARTIFACT,
        "config/guidance/review/root.review.policy.txt": ROOT_REVIEW_POLICY_ARTIFACT,
        "config/guidance/review/root.review.source.txt": ROOT_REVIEW_SOURCE_ARTIFACT,
        "config/guidance/review/kavya.review.policy.txt": KAVYA_REVIEW_POLICY_ARTIFACT,
        "config/guidance/review/kavya.review.source.txt": KAVYA_REVIEW_SOURCE_ARTIFACT,
        "config/guidance/policy/gated-off.txt": GATED_OFF_ARTIFACT,
        "config/guidance/policy/gated-on.txt": GATED_ON_ARTIFACT,
        "config/guidance/policy/scope-not-approved.txt": SCOPE_NOT_APPROVED_ARTIFACT,
    }
    for rel, text in artifacts.items():
        _write(disp / rel, text)

    return {
        "top": top,
        "disp": disp,
        "files": files,
        "artifacts": artifacts,
        "identity": RepositoryIdentity(
            toplevel=str(top),
            git_dir=str(top / ".git"),
            origin_url="https://example.invalid/target.git",
            root_commit="0" * 40,
        ),
    }


def _source(repo: dict, rel: str, *, alias_of: str | None = None) -> dict:
    raw = (repo["top"] / rel).read_bytes()
    return {
        "source_path": rel,
        "resolved_path": str(repo["top"] / rel),
        "sha256": _sha(raw),
        "bytes": len(raw),
        "alias_of": alias_of,
    }


def _artifact(repo: dict, rel: str, provenance: str) -> dict:
    raw = (repo["disp"] / rel).read_bytes()
    return {
        "path": rel,
        "provenance_class": provenance,
        "sha256": _sha(raw),
        "bytes": len(raw),
        "approx_tokens": round(len(raw) / 4),
    }


def _manifest_dict(repo: dict, **overrides) -> dict:
    top = repo["top"]
    ident = repo["identity"]
    data = {
        "schema_version": "1.0.0",
        "manifest_kind": "project-guidance",
        "generated": "2026-08-20",
        "authored_by": "test",
        "governing_documents": ["GATE4.5-ADDENDUM-PROJECT-GUIDANCE.md"],
        "approval": {"version": "v1", "date": "2026-08-20", "state": "APPROVED"},
        "provenance_classes": {
            "SOURCE_DERIVED": {
                "meaning": "derived from an approved instruction source",
                "strict_content_scan": True,
                "scan_patterns_id": "strict_secret_operator_v1",
                "required_result": "ZERO matches.",
            },
            "DISPATCHER_AUTHORED": {
                "meaning": "dispatcher-owned refusal/policy text",
                "strict_content_scan": False,
                "trusted_by": "its own SHA-256",
                "rule": "MUST NOT be merged into a SOURCE_DERIVED file.",
            },
        },
        "strict_secret_operator_v1": {
            "note": "patterns 1-6 case-insensitive; 7 case-sensitive",
            "patterns": list(STRICT_PATTERNS),
        },
        "repositories": [
            {
                "repository_id": "tgt",
                "display_name": "target",
                "toplevel": ident.toplevel,
                "git_dir": ident.git_dir,
                "origin_url": ident.origin_url,
                "root_commit": ident.root_commit,
                "identity_check": "all four must match",
                "source_resolution": {
                    "mode": "MANIFEST_PINNED_EXACT_PATHS_ONLY",
                    "rule": "toplevel + exact repo-relative path",
                    "flow": ["exact manifest path", "verify hash"],
                },
                "deny_prefixes": ["Taskforce_AI_Website/", ".claude/worktrees/"],
                "deny_absolute_trees": ["/home/dev/worktrees/"],
                "unapproved_file_discovery": {
                    "purpose": "DEFAULT-DENY verification only.",
                    "globs": ["**/CLAUDE.md", "**/AGENTS.md"],
                    "excludes": [
                        ".claude/worktrees/**",
                        "/home/dev/worktrees/**",
                        "Taskforce_AI_Website/**",
                        "node_modules/**",
                        ".venv/**",
                        "**/.git/**",
                    ],
                    "known_foreign_files": ["Taskforce_AI_Website/CLAUDE.md"],
                    "unlisted_file_policy": "DEFAULT_DENY_UNREVIEWED",
                },
            }
        ],
        "root_entry": "pg.tgt.root",
        "root_review_entry": "pg.tgt.root.review",
        "scope_map": {
            "note": "ordered, source-controlled",
            "match_rule": "rel == rstrip(prefix,'/') OR rel.startswith(prefix)",
            "root_is_unconditional": True,
            "max_subscopes": 2,
            "entries": [
                {
                    "scope_prefix": "BSL Agent/",
                    "worker_entry": "pg.tgt.bsl",
                    "review_entry": None,
                    "approved": False,
                },
                {
                    "scope_prefix": "Flico Agent/",
                    "worker_entry": "pg.tgt.flico",
                    "review_entry": None,
                    "approved": True,
                },
                {
                    "scope_prefix": "Kavya/",
                    "worker_entry": "pg.tgt.kavya",
                    "review_entry": "pg.tgt.kavya.review",
                    "approved": True,
                },
                {
                    "scope_prefix": "SLIC Agent/",
                    "worker_entry": "pg.tgt.slic",
                    "review_entry": None,
                    "approved": True,
                },
            ],
            "unapproved_scope_behaviour": {
                "typed_error": "ProjectGuidanceNotApproved",
                "fallback_to_root_only": False,
                "rule": "RULINGS §7",
                "operator_text_artifact": "config/guidance/policy/scope-not-approved.txt",
                "operator_text_artifact_sha256": _sha(
                    (repo["disp"] / "config/guidance/policy/scope-not-approved.txt").read_bytes()
                ),
                "operator_text_provenance_class": "DISPATCHER_AUTHORED",
            },
        },
        "graph_refresh_gate": {
            "ruling": "ADDENDUM §5",
            "selector": "set membership on repository-relative allowed_paths",
            "gate_prefix": "graphify-out/",
            "on_match": dict(
                variant="GATED_ON",
                artifact="config/guidance/policy/gated-on.txt",
                sha256=_sha((repo["disp"] / "config/guidance/policy/gated-on.txt").read_bytes()),
                provenance_class="DISPATCHER_AUTHORED",
            ),
            "default": dict(
                variant="GATED_OFF",
                artifact="config/guidance/policy/gated-off.txt",
                sha256=_sha((repo["disp"] / "config/guidance/policy/gated-off.txt").read_bytes()),
                provenance_class="DISPATCHER_AUTHORED",
            ),
            "read_only_exploration": "ALWAYS ELIGIBLE",
            "worker_report_token": "GRAPH_REFRESH_REQUIRED",
        },
        "emission": {
            "note": "policy then source, root first, graph clause last",
            "order": [
                "root_entry.policy_artifact",
                "root_entry.source_artifact",
                "for each selected subscope in scope_map declaration order: "
                "entry.policy_artifact then entry.source_artifact",
                "graph_refresh_gate.<selected variant>.artifact",
            ],
            "worker_and_review_are_disjoint": "disjoint files, disjoint hashes",
        },
        "entries": {
            "pg.tgt.root": {
                "repository_id": "tgt",
                "logical_id": "pg.tgt.root",
                "audience": "worker",
                "scope_prefix": "",
                "scope_note": "always selected",
                "classification": "CURATED_ROOT",
                "flags": ["ROOT_PAIR_DRIFT_ACKNOWLEDGED"],
                "source_relationship": "UNION_OF_INDEPENDENT_SOURCES",
                "sources": [
                    _source(repo, "AGENTS.md"),
                    _source(repo, "CLAUDE.md"),
                    _source(repo, "CONTRIBUTING.md"),
                ],
                "source_artifact": _artifact(
                    repo, "config/guidance/worker/root.source.txt", SOURCE_DERIVED
                ),
                "policy_artifact": _artifact(
                    repo, "config/guidance/worker/root.policy.txt", DISPATCHER_AUTHORED
                ),
            },
            "pg.tgt.kavya": {
                "repository_id": "tgt",
                "logical_id": "pg.tgt.kavya",
                "audience": "worker",
                "scope_prefix": "Kavya/",
                "classification": "CURATED_SUBPROJECT",
                "source_relationship": "ALIASES_BYTE_IDENTICAL",
                "sources": [
                    _source(repo, "Kavya/CLAUDE.md"),
                    _source(repo, "Kavya/AGENTS.md", alias_of="Kavya/CLAUDE.md"),
                ],
                "source_artifact": _artifact(
                    repo, "config/guidance/worker/kavya.source.txt", SOURCE_DERIVED
                ),
                "policy_artifact": _artifact(
                    repo, "config/guidance/worker/kavya.policy.txt", DISPATCHER_AUTHORED
                ),
            },
            "pg.tgt.slic": {
                "repository_id": "tgt",
                "logical_id": "pg.tgt.slic",
                "audience": "worker",
                "scope_prefix": "SLIC Agent/",
                "classification": "CURATED_SUBPROJECT",
                "source_relationship": "ALIASES_BYTE_IDENTICAL",
                "sources": [
                    _source(repo, "SLIC Agent/CLAUDE.md"),
                    _source(repo, "SLIC Agent/AGENTS.md", alias_of="SLIC Agent/CLAUDE.md"),
                ],
                "source_artifact": _artifact(
                    repo, "config/guidance/worker/slic.source.txt", SOURCE_DERIVED
                ),
                "policy_artifact": _artifact(
                    repo, "config/guidance/worker/slic.policy.txt", DISPATCHER_AUTHORED
                ),
            },
            "pg.tgt.flico": {
                "repository_id": "tgt",
                "logical_id": "pg.tgt.flico",
                "audience": "worker",
                "scope_prefix": "Flico Agent/",
                "classification": "CURATED_SUBPROJECT",
                "source_relationship": "ALIASES_BYTE_IDENTICAL",
                "sources": [
                    _source(repo, "Flico Agent/CLAUDE.md"),
                    _source(repo, "Flico Agent/AGENTS.md", alias_of="Flico Agent/CLAUDE.md"),
                ],
                "source_artifact": _artifact(
                    repo, "config/guidance/worker/flico.source.txt", SOURCE_DERIVED
                ),
                "policy_artifact": _artifact(
                    repo, "config/guidance/worker/flico.policy.txt", DISPATCHER_AUTHORED
                ),
            },
            "pg.tgt.bsl": {
                "repository_id": "tgt",
                "logical_id": "pg.tgt.bsl",
                "audience": "worker",
                "scope_prefix": "BSL Agent/",
                "classification": "CLASSIFIED_NOT_APPROVED",
                "approval_state": "NOT_APPROVED",
                "on_selection": "ProjectGuidanceNotApproved",
                "fallback_to_root_only": False,
                "sources": [
                    _source(repo, "BSL Agent/CLAUDE.md"),
                    _source(repo, "BSL Agent/AGENTS.md", alias_of="BSL Agent/CLAUDE.md"),
                ],
                "source_artifact": None,
                "policy_artifact": None,
            },
            "pg.taw.root": {
                "repository_id": "taw",
                "logical_id": "pg.taw.root",
                "audience": "none",
                "scope_prefix": None,
                "classification": "EXCLUDED_FOREIGN_REPO",
                "approval_state": "NEVER",
                "sources": [_source(repo, "Taskforce_AI_Website/CLAUDE.md")],
                "source_artifact": None,
                "policy_artifact": None,
                "note": "inventoried for audit only",
            },
            "pg.tgt.root.review": {
                "repository_id": "tgt",
                "logical_id": "pg.tgt.root.review",
                "audience": "fable_review",
                "scope_prefix": "",
                "classification": "CURATED_ROOT_REVIEW",
                "source_relationship": "UNION_OF_INDEPENDENT_SOURCES",
                "sources": [
                    _source(repo, "AGENTS.md"),
                    _source(repo, "CLAUDE.md"),
                    _source(repo, "CONTRIBUTING.md"),
                ],
                "source_artifact": _artifact(
                    repo, "config/guidance/review/root.review.source.txt", SOURCE_DERIVED
                ),
                "policy_artifact": _artifact(
                    repo, "config/guidance/review/root.review.policy.txt", DISPATCHER_AUTHORED
                ),
            },
            "pg.tgt.kavya.review": {
                "repository_id": "tgt",
                "logical_id": "pg.tgt.kavya.review",
                "audience": "fable_review",
                "scope_prefix": "Kavya/",
                "classification": "CURATED_SUBPROJECT_REVIEW",
                "source_relationship": "ALIASES_BYTE_IDENTICAL",
                "sources": [
                    _source(repo, "Kavya/CLAUDE.md"),
                    _source(repo, "Kavya/AGENTS.md", alias_of="Kavya/CLAUDE.md"),
                ],
                "source_artifact": _artifact(
                    repo, "config/guidance/review/kavya.review.source.txt", SOURCE_DERIVED
                ),
                "policy_artifact": _artifact(
                    repo, "config/guidance/review/kavya.review.policy.txt", DISPATCHER_AUTHORED
                ),
            },
        },
        "failure_semantics": [
            {
                "condition": "repository identity mismatch",
                "typed_error": "ProjectGuidanceRepositoryMismatch",
                "behaviour": "fail closed",
            }
        ],
        "resume_fingerprint": {"spec": pg_mod.FINGERPRINT_SPEC, "note": "see module"},
    }
    data.update(overrides)
    return data


def _engine(repo: dict, manifest_data: dict | None = None, **kwargs) -> ProjectGuidanceEngine:
    data = manifest_data if manifest_data is not None else _manifest_dict(repo)
    manifest = load_manifest_from_mapping(data)
    return ProjectGuidanceEngine(
        manifest,
        project_root=repo["disp"],
        max_projected_bytes=kwargs.pop("max_projected_bytes", 200_000),
        **kwargs,
    )


def _project(engine, repo, paths, **kwargs):
    return engine.project(
        list(paths),
        repository=repo["identity"],
        task_envelope_id=kwargs.pop("task_envelope_id", "task-1"),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Manifest loading (§9)
# ---------------------------------------------------------------------------


class TestManifestLoading:
    def test_synthetic_manifest_loads(self, repo):
        manifest = load_manifest_from_mapping(_manifest_dict(repo))
        assert manifest.manifest_kind == "project-guidance"
        assert manifest.root_entry == "pg.tgt.root"

    def test_unknown_top_level_key_is_refused(self, repo):
        data = _manifest_dict(repo)
        data["surprise"] = True
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)

    def test_missing_manifest_file_fails_closed(self, tmp_path):
        with pytest.raises(ConfigurationError):
            load_manifest(tmp_path / "nope.json")

    def test_non_json_manifest_fails_closed(self, tmp_path):
        path = _write(tmp_path / "m.json", "{not json")
        with pytest.raises(ConfigurationError):
            load_manifest(path)

    def test_root_entry_must_exist(self, repo):
        data = _manifest_dict(repo)
        data["root_entry"] = "pg.tgt.missing"
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)

    def test_scope_entry_must_name_a_known_worker_entry(self, repo):
        data = _manifest_dict(repo)
        data["scope_map"]["entries"][1]["worker_entry"] = "pg.tgt.ghost"
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)

    def test_entry_scope_prefix_must_agree_with_the_scope_map(self, repo):
        data = _manifest_dict(repo)
        data["entries"]["pg.tgt.kavya"]["scope_prefix"] = "Kavya-renamed/"
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)


# ---------------------------------------------------------------------------
# RULINGS §3 — mandatory denies, encoded as literals
# ---------------------------------------------------------------------------


class TestMandatoryDenies:
    """Emptying a deny constant must turn these red, not green."""

    def test_mandatory_deny_prefixes_are_the_expected_literals(self):
        assert ".claude/worktrees/" in MANDATORY_DENY_PREFIXES
        assert "Taskforce_AI_Website/" in MANDATORY_DENY_PREFIXES
        assert len(MANDATORY_DENY_PREFIXES) >= 2

    def test_mandatory_deny_absolute_trees_are_the_expected_literals(self):
        assert "/home/dev/worktrees/" in MANDATORY_DENY_ABSOLUTE_TREES
        assert len(MANDATORY_DENY_ABSOLUTE_TREES) >= 1

    def test_manifest_that_drops_a_mandatory_deny_prefix_is_refused(self, repo):
        data = _manifest_dict(repo)
        data["repositories"][0]["deny_prefixes"] = ["Taskforce_AI_Website/"]
        with pytest.raises(ConfigurationError) as exc:
            load_manifest_from_mapping(data)
        assert ".claude/worktrees/" in json.dumps(exc.value.details)

    def test_manifest_that_drops_a_mandatory_absolute_deny_is_refused(self, repo):
        data = _manifest_dict(repo)
        data["repositories"][0]["deny_absolute_trees"] = []
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)

    def test_manifest_that_drops_a_discovery_exclude_is_refused(self, repo):
        data = _manifest_dict(repo)
        data["repositories"][0]["unapproved_file_discovery"]["excludes"] = ["node_modules/**"]
        with pytest.raises(ConfigurationError):
            load_manifest_from_mapping(data)


# ---------------------------------------------------------------------------
# Repository identity (§9.2, RULINGS §4)
# ---------------------------------------------------------------------------


class TestRepositoryIdentity:
    def test_matching_identity_projects(self, repo):
        projection = _project(_engine(repo), repo, ["README.md"])
        assert projection.logical_ids == ("pg.tgt.root",)

    @pytest.mark.parametrize(
        "field", ["toplevel", "git_dir", "origin_url", "root_commit"]
    )
    def test_each_identity_field_is_load_bearing(self, repo, field):
        engine = _engine(repo)
        wrong = dict(
            toplevel=repo["identity"].toplevel,
            git_dir=repo["identity"].git_dir,
            origin_url=repo["identity"].origin_url,
            root_commit=repo["identity"].root_commit,
        )
        wrong[field] = "/somewhere/else" if field != "origin_url" else "https://evil/x.git"
        with pytest.raises(ProjectGuidanceRepositoryMismatch) as exc:
            engine.project(
                ["README.md"],
                repository=RepositoryIdentity(**wrong),
                task_envelope_id="t",
            )
        assert field in exc.value.details["mismatched_fields"]

    def test_a_foreign_root_commit_cannot_impersonate_the_repository(self, repo):
        """§1C: the nested website repo has its own root commit and cannot pass."""
        engine = _engine(repo)
        foreign = RepositoryIdentity(
            toplevel=repo["identity"].toplevel,
            git_dir=repo["identity"].git_dir,
            origin_url=repo["identity"].origin_url,
            root_commit="fb74c39b1a33410748ba216c90d65206c778526d",
        )
        with pytest.raises(ProjectGuidanceRepositoryMismatch):
            engine.project(["README.md"], repository=foreign, task_envelope_id="t")


# ---------------------------------------------------------------------------
# §6 / §17 — deterministic nearest-scope selection
# ---------------------------------------------------------------------------


class TestScopeSelection:
    def test_root_task_gets_root_only(self, repo):
        projection = _project(_engine(repo), repo, ["ops/", "README.md"])
        assert projection.logical_ids == ("pg.tgt.root",)
        assert "ROOT-SOURCE-ARTIFACT" in projection.text
        assert "KAVYA-SOURCE-ARTIFACT" not in projection.text
        assert "SLIC-SOURCE-ARTIFACT" not in projection.text
        assert "FLICO-SOURCE-ARTIFACT" not in projection.text

    def test_kavya_task_gets_root_plus_kavya_only(self, repo):
        projection = _project(_engine(repo), repo, ["Kavya/server.py"])
        assert projection.logical_ids == ("pg.tgt.root", "pg.tgt.kavya")
        assert "KAVYA-SOURCE-ARTIFACT" in projection.text
        for absent in ("SLIC-SOURCE-ARTIFACT", "FLICO-SOURCE-ARTIFACT", "BSL-SOURCE-SENTINEL"):
            assert absent not in projection.text

    def test_slic_task_gets_root_plus_slic_only(self, repo):
        projection = _project(_engine(repo), repo, ["SLIC Agent/claim_api.py"])
        assert projection.logical_ids == ("pg.tgt.root", "pg.tgt.slic")
        assert "SLIC-SOURCE-ARTIFACT" in projection.text
        assert "KAVYA-SOURCE-ARTIFACT" not in projection.text

    def test_directory_prefix_and_exact_directory_both_match(self, repo):
        engine = _engine(repo)
        for paths in (["Kavya/"], ["Kavya"], ["Kavya/**"], ["Kavya/tests/test_x.py"]):
            projection = _project(engine, repo, paths)
            assert projection.logical_ids == ("pg.tgt.root", "pg.tgt.kavya"), paths

    def test_a_sibling_name_sharing_a_prefix_does_not_match(self, repo):
        """``Kavya-notes/`` is not ``Kavya/``. Prefix matching is path-segment aware."""
        projection = _project(_engine(repo), repo, ["Kavya-notes/readme.md"])
        assert projection.logical_ids == ("pg.tgt.root",)

    def test_cross_scope_task_gets_only_intersecting_scopes(self, repo):
        projection = _project(
            _engine(repo), repo, ["Kavya/handover.py", "Flico Agent/kb/engine.py"]
        )
        assert projection.logical_ids == ("pg.tgt.root", "pg.tgt.flico", "pg.tgt.kavya")
        assert "SLIC-SOURCE-ARTIFACT" not in projection.text

    def test_subscope_order_follows_manifest_declaration_order(self, repo):
        """Declaration order, not the order of allowed_paths."""
        a = _project(_engine(repo), repo, ["Kavya/x.py", "Flico Agent/y.py"])
        b = _project(_engine(repo), repo, ["Flico Agent/y.py", "Kavya/x.py"])
        assert a.logical_ids == b.logical_ids
        assert a.text == b.text

    def test_more_than_max_subscopes_fails_closed(self, repo):
        with pytest.raises(ProjectGuidanceScopeError) as exc:
            _project(
                _engine(repo),
                repo,
                ["Kavya/", "SLIC Agent/", "Flico Agent/"],
            )
        assert exc.value.details["max_subscopes"] == 2
        assert len(exc.value.details["selected_scope_prefixes"]) == 3

    def test_longest_matching_prefix_wins_for_a_nested_scope(self, repo):
        """A nested scope selects the deepest match plus root — never both levels."""
        data = _manifest_dict(repo)
        _write(repo["top"] / "Kavya/smartpbx/CLAUDE.md", "NESTED-SCOPE-SENTINEL\n")
        _write(repo["top"] / "Kavya/smartpbx/AGENTS.md", "NESTED-SCOPE-SENTINEL\n")
        _write(repo["disp"] / "config/guidance/worker/pbx.policy.txt", "PBX-POLICY\n")
        _write(repo["disp"] / "config/guidance/worker/pbx.source.txt", "PBX-SOURCE\n")
        data["entries"]["pg.tgt.pbx"] = {
            "repository_id": "tgt",
            "logical_id": "pg.tgt.pbx",
            "audience": "worker",
            "scope_prefix": "Kavya/smartpbx/",
            "classification": "CURATED_SUBPROJECT",
            "source_relationship": "ALIASES_BYTE_IDENTICAL",
            "sources": [
                _source(repo, "Kavya/smartpbx/CLAUDE.md"),
                _source(repo, "Kavya/smartpbx/AGENTS.md", alias_of="Kavya/smartpbx/CLAUDE.md"),
            ],
            "source_artifact": _artifact(
                repo, "config/guidance/worker/pbx.source.txt", SOURCE_DERIVED
            ),
            "policy_artifact": _artifact(
                repo, "config/guidance/worker/pbx.policy.txt", DISPATCHER_AUTHORED
            ),
        }
        data["scope_map"]["entries"].append(
            {
                "scope_prefix": "Kavya/smartpbx/",
                "worker_entry": "pg.tgt.pbx",
                "review_entry": None,
                "approved": True,
            }
        )
        engine = _engine(repo, data)
        projection = _project(engine, repo, ["Kavya/smartpbx/bridge.py"])
        assert projection.logical_ids == ("pg.tgt.root", "pg.tgt.pbx")
        assert "KAVYA-SOURCE-ARTIFACT" not in projection.text

    def test_selection_is_a_pure_function_of_paths(self, repo):
        engine = _engine(repo)
        first = engine.select(["Kavya/x.py"], repository=repo["identity"])
        second = engine.select(["Kavya/x.py"], repository=repo["identity"])
        assert first == second
        assert first.logical_ids == ("pg.tgt.root", "pg.tgt.kavya")
        assert first.graph_variant == "GATED_OFF"


# ---------------------------------------------------------------------------
# RULINGS §3 — shadow instruction files. HARD REGRESSION.
# ---------------------------------------------------------------------------


class TestShadowInstructionFiles:
    def test_in_repo_worktree_path_is_denied(self, repo):
        with pytest.raises(ProjectGuidanceScopeError) as exc:
            _project(
                _engine(repo),
                repo,
                [".claude/worktrees/agent-aa383920556fd0f25/Kavya/"],
            )
        assert ".claude/worktrees/" in exc.value.details["denied_by"]

    def test_external_sibling_worktree_tree_is_denied(self, repo):
        with pytest.raises(ProjectGuidanceScopeError):
            _project(
                _engine(repo), repo, ["/home/dev/worktrees/full-voice-agent-x/Kavya/"]
            )

    def test_nested_foreign_repository_is_denied(self, repo):
        with pytest.raises(ProjectGuidanceScopeError) as exc:
            _project(
                _engine(repo),
                repo,
                ["Taskforce_AI_Website/components/pages/BookDemo.tsx"],
            )
        assert "Taskforce_AI_Website/" in exc.value.details["denied_by"]

    def test_a_different_hash_shadow_copy_never_becomes_a_source(self, repo):
        """The measured hazard: a stale worktree Kavya/CLAUDE.md with a *different*
        hash sits inside the repository. Projection must read the primary path
        only, and the shadow text must never appear."""
        shadow = repo["top"] / ".claude/worktrees/agent-aa383920556fd0f25/Kavya/CLAUDE.md"
        primary = repo["top"] / "Kavya/CLAUDE.md"
        assert _sha(shadow.read_bytes()) != _sha(primary.read_bytes())

        projection = _project(_engine(repo), repo, ["Kavya/"])
        assert "SHADOW-WORKTREE-SENTINEL" not in projection.text
        resolved = {p for scope in projection.scopes for p in scope.source_paths}
        assert str(primary) in resolved
        assert str(shadow) not in resolved
        assert not any(".claude/worktrees" in p for p in resolved)

    def test_a_new_nested_instruction_file_is_never_discovered(self, repo):
        """No glob-based 'find nearest CLAUDE.md'. Dropping a file in does nothing."""
        engine = _engine(repo)
        before = _project(engine, repo, ["Kavya/"]).text
        _write(repo["top"] / "Kavya/subsystem/CLAUDE.md", NESTED_TEXT)
        after = _project(engine, repo, ["Kavya/"]).text
        assert before == after
        assert NESTED_TEXT.strip() not in after

    def test_module_does_not_glob_for_source_resolution(self):
        """Source resolution is exact-path only (RULINGS §3)."""
        source = Path(pg_mod.__file__).read_text()
        resolver = source.split("def _resolve_sources", 1)
        assert len(resolver) == 2, "expected a dedicated source resolver"
        body = resolver[1].split("\n    def ", 1)[0]
        for forbidden in (".glob(", ".rglob(", "fnmatch", "os.walk"):
            assert forbidden not in body, f"{forbidden} in the source resolver"


# ---------------------------------------------------------------------------
# RULINGS §7 — incremental approval, fail closed, no root-only fallback
# ---------------------------------------------------------------------------


class TestApprovalGate:
    @pytest.mark.parametrize("path", ["BSL Agent/", "BSL Agent/server.py"])
    def test_unapproved_scope_fails_closed(self, repo, path):
        with pytest.raises(ProjectGuidanceNotApproved) as exc:
            _project(_engine(repo), repo, [path])
        assert exc.value.details["logical_id"] == "pg.tgt.bsl"
        assert exc.value.details["scope_prefix"] == "BSL Agent/"
        assert exc.value.details["fallback_to_root_only"] is False

    def test_unapproved_scope_does_not_fall_back_to_root_only(self, repo):
        engine = _engine(repo)
        with pytest.raises(ProjectGuidanceNotApproved):
            _project(engine, repo, ["BSL Agent/", "README.md"])

    def test_refusal_carries_the_operator_text(self, repo):
        with pytest.raises(ProjectGuidanceNotApproved) as exc:
            _project(_engine(repo), repo, ["BSL Agent/"])
        text = exc.value.details["operator_text"]
        assert "BSL Agent/" in text
        assert "pg.tgt.bsl" in text
        assert "{scope_prefix}" not in text
        assert "NO fallback to root-only guidance" in text

    def test_manifest_pending_approval_refuses_everything(self, repo):
        data = _manifest_dict(repo)
        data["approval"]["state"] = "PENDING_SOL"
        engine = _engine(repo, data)
        with pytest.raises(ProjectGuidanceNotApproved) as exc:
            _project(engine, repo, ["README.md"])
        assert exc.value.details["approval_state"] == "PENDING_SOL"

    def test_shipped_manifest_is_still_pending_sol(self):
        """The real manifest must not project until Sol approves it."""
        manifest = load_manifest(REAL_MANIFEST)
        assert manifest.approval.state == "PENDING_SOL"


# ---------------------------------------------------------------------------
# §7 / §8 / RULINGS §6 — hash semantics
# ---------------------------------------------------------------------------


class TestHashSemantics:
    def test_identical_alias_pair_is_injected_once(self, repo):
        projection = _project(_engine(repo), repo, ["Kavya/"])
        assert projection.text.count("KAVYA-SOURCE-ARTIFACT") == 1
        kavya = next(s for s in projection.scopes if s.logical_id == "pg.tgt.kavya")
        assert len(kavya.source_paths) == 2  # both aliases recorded as provenance
        assert len(set(kavya.source_hashes)) == 1  # one logical document

    def test_alias_divergence_fails_closed_as_drift(self, repo):
        engine = _engine(repo)
        (repo["top"] / "Kavya/AGENTS.md").write_text("HAND EDITED MIRROR\n")
        with pytest.raises(ProjectGuidanceDrift) as exc:
            _project(engine, repo, ["Kavya/"])
        assert exc.value.details["logical_id"] == "pg.tgt.kavya"
        assert exc.value.details["source_relationship"] == "ALIASES_BYTE_IDENTICAL"

    def test_both_aliases_changed_identically_fails_as_source_change(self, repo):
        engine = _engine(repo)
        for name in ("CLAUDE.md", "AGENTS.md"):
            (repo["top"] / "Kavya" / name).write_text("A NEW REVISION OF BOTH\n")
        with pytest.raises(ProjectGuidanceSourceChanged) as exc:
            _project(engine, repo, ["Kavya/"])
        assert exc.value.details["source_path"] in ("Kavya/CLAUDE.md", "Kavya/AGENTS.md")

    def test_root_union_tolerates_two_different_hashes(self, repo):
        """RULINGS §6: root non-identity is NOT a failure."""
        manifest = load_manifest_from_mapping(_manifest_dict(repo))
        root = manifest.entries["pg.tgt.root"]
        hashes = {s.sha256 for s in root.sources}
        assert len(hashes) == 3, "the root sources must genuinely differ"
        assert root.source_relationship == "UNION_OF_INDEPENDENT_SOURCES"
        projection = _project(_engine(repo), repo, ["README.md"])
        assert "ROOT-SOURCE-ARTIFACT" in projection.text

    def test_root_projection_is_derived_from_both_root_files(self, repo):
        manifest = load_manifest_from_mapping(_manifest_dict(repo))
        paths = [s.source_path for s in manifest.entries["pg.tgt.root"].sources]
        assert "AGENTS.md" in paths and "CLAUDE.md" in paths
        assert "ROOT_PAIR_DRIFT_ACKNOWLEDGED" in manifest.entries["pg.tgt.root"].flags

    def test_root_union_source_change_still_fails_closed(self, repo):
        engine = _engine(repo)
        (repo["top"] / "CLAUDE.md").write_text("SOMEONE EDITED THE ROOT\n")
        with pytest.raises(ProjectGuidanceSourceChanged) as exc:
            _project(engine, repo, ["README.md"])
        assert exc.value.details["source_path"] == "CLAUDE.md"

    def test_missing_source_file_fails_closed(self, repo):
        engine = _engine(repo)
        (repo["top"] / "CONTRIBUTING.md").unlink()
        with pytest.raises(ProjectGuidanceSourceChanged):
            _project(engine, repo, ["README.md"])

    def test_symlinked_source_path_fails_closed(self, repo):
        engine = _engine(repo)
        target = repo["top"] / "CONTRIBUTING.md"
        elsewhere = repo["top"].parent / "elsewhere.md"
        elsewhere.write_text(CONTRIBUTING_TEXT)
        target.unlink()
        target.symlink_to(elsewhere)
        with pytest.raises(ProjectGuidanceSourceChanged) as exc:
            _project(engine, repo, ["README.md"])
        assert "symlink" in json.dumps(exc.value.details).lower()

    def test_changed_projection_artifact_fails_closed(self, repo):
        engine = _engine(repo)
        (repo["disp"] / "config/guidance/worker/root.source.txt").write_text("TAMPERED\n")
        with pytest.raises(ProjectGuidanceProjectionChanged) as exc:
            _project(engine, repo, ["README.md"])
        assert exc.value.details["artifact"].endswith("root.source.txt")

    def test_missing_projection_artifact_fails_closed(self, repo):
        engine = _engine(repo)
        (repo["disp"] / "config/guidance/worker/root.policy.txt").unlink()
        with pytest.raises(ProjectGuidanceProjectionChanged):
            _project(engine, repo, ["README.md"])


# ---------------------------------------------------------------------------
# RULINGS §2 — provenance separation. The subtle one.
# ---------------------------------------------------------------------------


class TestProvenanceSeparation:
    def test_scanner_refuses_a_dispatcher_authored_artifact_by_provenance(self, repo):
        scanner = StrictContentScanner(STRICT_PATTERNS)
        with pytest.raises(ProvenanceSeparationError) as exc:
            scanner.scan_artifact(
                "root.policy.txt",
                ROOT_POLICY_ARTIFACT,
                provenance_class=DISPATCHER_AUTHORED,
            )
        assert "DISPATCHER_AUTHORED" in str(exc.value)

    def test_the_exempt_artifact_would_genuinely_fail_the_scanner(self):
        """Not a content carve-out: the refusal text really does match.

        This is the whole reason RULINGS §2 exists. If this assertion ever goes
        to zero the exemption has become vacuous and the test above proves
        nothing.
        """
        scanner = StrictContentScanner(STRICT_PATTERNS)
        hits = scanner.scan_text(ROOT_POLICY_ARTIFACT)
        assert len(hits) >= 3
        matched = {h.matched for h in hits}
        assert any(".env" in m for m in matched)
        assert any("ssh" in m.lower() for m in matched)

    def test_scanner_runs_on_source_derived_content_and_can_fail(self, repo):
        scanner = StrictContentScanner(STRICT_PATTERNS)
        hits = scanner.scan_artifact(
            "x.source.txt",
            "Read the .env.secrets file and run docker restart api.\n",
            provenance_class=SOURCE_DERIVED,
        )
        assert len(hits) >= 2

    def test_clean_source_derived_content_scans_zero(self, repo):
        scanner = StrictContentScanner(STRICT_PATTERNS)
        assert scanner.scan_artifact(
            "root.source.txt", ROOT_SOURCE_ARTIFACT, provenance_class=SOURCE_DERIVED
        ) == ()

    def test_projection_refuses_a_source_derived_artifact_with_operator_content(self, repo):
        """A re-approved-but-unsafe projection artifact still fails closed."""
        bad = "ROOT-SOURCE-ARTIFACT\nssh root@10.0.0.1 and run systemctl restart api\n"
        _write(repo["disp"] / "config/guidance/worker/root.source.txt", bad)
        data = _manifest_dict(repo)  # rehashes, so the hash check passes
        with pytest.raises(ProjectGuidancePolicyViolation) as exc:
            _project(_engine(repo, data), repo, ["README.md"])
        assert exc.value.details["reason"] == "sensitive_content_in_source_derived_artifact"
        assert exc.value.details["provenance_class"] == SOURCE_DERIVED

    def test_projection_records_which_artifacts_were_scanned(self, repo):
        projection = _project(_engine(repo), repo, ["Kavya/"])
        scanned = set(projection.scanned_artifacts)
        exempt = set(projection.exempt_artifacts)
        assert scanned and exempt
        assert not (scanned & exempt)
        assert all("source" in Path(p).name for p in scanned)
        assert all(
            "policy" in Path(p).name or "gated" in Path(p).name for p in exempt
        )

    def test_dispatcher_authored_artifact_is_still_emitted(self, repo):
        """Exempt from the scanner, not exempt from projection."""
        projection = _project(_engine(repo), repo, ["README.md"])
        assert "ROOT-POLICY-ARTIFACT" in projection.text


# ---------------------------------------------------------------------------
# §11 / §17 — operator and secret material stays out (shipped artifacts)
# ---------------------------------------------------------------------------


@pytest.fixture
def manifest():
    return load_manifest(REAL_MANIFEST)


@pytest.fixture
def source_derived_text(manifest):
    blobs = {}
    for entry in manifest.entries.values():
        if entry.source_artifact is None:
            continue
        blobs[entry.logical_id] = (PROJECT_ROOT / entry.source_artifact.path).read_text()
    return blobs


@pytest.mark.skipif(
    not REAL_TARGET_REPO.is_dir(), reason="full-voice-agent not present on this host"
)
class TestShippedArtifactContent:
    """Read-only assertions over the real curated artifacts (ADDENDUM §19)."""

    @pytest.mark.parametrize(
        "needle,minimum_in_source",
        [
            ("ssh ", 5),
            ("systemctl", 3),
            ("ClickUp", 8),
            (".env", 6),
            ("API_KEY", 4),
            ("root@", 3),
            ("git push", 1),
            ("docker compose", 2),
        ],
    )
    def test_operator_and_secret_needles_present_in_source_absent_from_projection(
        self, source_derived_text, needle, minimum_in_source
    ):
        """Non-vacuous by construction: the needle *is* in the real root docs."""
        root_doc = (REAL_TARGET_REPO / "CLAUDE.md").read_text()
        assert root_doc.lower().count(needle.lower()) >= minimum_in_source, (
            f"{needle!r} no longer appears in the real root CLAUDE.md; this test "
            "would otherwise pass vacuously"
        )
        for logical_id, text in source_derived_text.items():
            assert needle.lower() not in text.lower(), f"{needle!r} in {logical_id}"

    @pytest.mark.parametrize(
        "identifier", ["TWILIO_ACCOUNT_SID", "CLOUDFLARE_ACCOUNT_ID"]
    )
    def test_excluded_identifiers_are_absent(self, source_derived_text, identifier):
        for text in source_derived_text.values():
            assert identifier not in text

    @pytest.mark.parametrize(
        "figure", ["2,881", "4,473", "279 communities", "3,411", "7,345", "10,191", "1,790"]
    )
    def test_contradictory_graph_figures_are_absent(self, source_derived_text, figure):
        """RULINGS §5: contradictory historical counts must not be projected."""
        for text in source_derived_text.values():
            assert figure not in text

    def test_strict_scanner_returns_zero_on_every_source_derived_artifact(self, manifest):
        scanner = StrictContentScanner(manifest.strict_secret_operator_v1.patterns)
        for entry in manifest.entries.values():
            if entry.source_artifact is None:
                continue
            text = (PROJECT_ROOT / entry.source_artifact.path).read_text()
            hits = scanner.scan_artifact(
                entry.source_artifact.path,
                text,
                provenance_class=entry.source_artifact.provenance_class,
            )
            assert hits == (), f"{entry.logical_id}: {[h.matched for h in hits]}"

    def test_the_shipped_policy_artifacts_would_fail_the_same_scanner(self, manifest):
        """Proves the shipped exemption is a provenance decision, not a no-op."""
        scanner = StrictContentScanner(manifest.strict_secret_operator_v1.patterns)
        root_policy = manifest.entries["pg.fva.root"].policy_artifact
        assert root_policy is not None
        text = (PROJECT_ROOT / root_policy.path).read_text()
        assert len(scanner.scan_text(text)) >= 2
        with pytest.raises(ProvenanceSeparationError):
            scanner.scan_artifact(
                root_policy.path, text, provenance_class=root_policy.provenance_class
            )

    def test_taskforce_website_guidance_is_never_projected(self, manifest):
        entry = manifest.entries["pg.taw.root"]
        assert entry.classification == "EXCLUDED_FOREIGN_REPO"
        assert entry.source_artifact is None and entry.policy_artifact is None
        website_text = (REAL_TARGET_REPO / "Taskforce_AI_Website" / "CLAUDE.md").read_text()
        distinctive = [
            line.strip()
            for line in website_text.splitlines()
            if line.startswith("#") and len(line.strip()) > 12
        ]
        assert distinctive, "expected headings in the foreign document"
        for entry in manifest.entries.values():
            for artifact in (entry.source_artifact, entry.policy_artifact):
                if artifact is None:
                    continue
                text = (PROJECT_ROOT / artifact.path).read_text()
                for heading in distinctive:
                    assert heading not in text

    def test_graphify_read_first_guidance_is_preserved(self, source_derived_text):
        root = source_derived_text["pg.fva.root"]
        assert "GRAPH_REPORT.md" in root
        assert "graphify query" in root

    def test_domain_invariants_survive(self, source_derived_text):
        kavya = source_derived_text["pg.fva.kavya"]
        for invariant in (
            "normalize_whatsapp",
            "MAX_TOOL_ROUNDS",
            "test_handover.py",
            "kpms_service.py",
        ):
            assert invariant in kavya, invariant
        assert "normalize_whatsapp" not in source_derived_text["pg.fva.slic"]


# ---------------------------------------------------------------------------
# §5 — graphify gate
# ---------------------------------------------------------------------------


class TestGraphRefreshGate:
    def test_default_variant_is_gated_off(self, repo):
        projection = _project(_engine(repo), repo, ["Kavya/"])
        assert projection.graph_variant == "GATED_OFF"
        assert "GRAPH_REFRESH_REQUIRED" in projection.text
        assert "GATED-ON-ARTIFACT" not in projection.text

    def test_authorised_graph_outputs_select_gated_on(self, repo):
        projection = _project(_engine(repo), repo, ["Kavya/", "graphify-out/"])
        assert projection.graph_variant == "GATED_ON"
        assert "GATED-ON-ARTIFACT" in projection.text
        assert "GATED-OFF-ARTIFACT" not in projection.text

    def test_the_gate_prefix_does_not_consume_a_subscope_slot(self, repo):
        projection = _project(
            _engine(repo), repo, ["Kavya/", "SLIC Agent/", "graphify-out/"]
        )
        assert projection.logical_ids == ("pg.tgt.root", "pg.tgt.kavya", "pg.tgt.slic")
        assert projection.graph_variant == "GATED_ON"

    def test_graph_clause_is_emitted_last(self, repo):
        projection = _project(_engine(repo), repo, ["Kavya/"])
        assert projection.text.index("GATED-OFF-ARTIFACT") > projection.text.index(
            "KAVYA-SOURCE-ARTIFACT"
        )

    def test_graph_clause_hash_is_verified(self, repo):
        engine = _engine(repo)
        (repo["disp"] / "config/guidance/policy/gated-off.txt").write_text("TAMPERED\n")
        with pytest.raises(ProjectGuidanceProjectionChanged):
            _project(engine, repo, ["Kavya/"])

    def test_review_projection_carries_no_graph_clause(self, repo):
        projection = _project(
            _engine(repo), repo, ["Kavya/"], audience=GuidanceAudience.FABLE_REVIEW
        )
        assert projection.graph_variant is None
        assert "GATED-OFF-ARTIFACT" not in projection.text


# ---------------------------------------------------------------------------
# §15 — Fable review context
# ---------------------------------------------------------------------------


class TestFableReviewProjection:
    def test_review_audience_gets_review_artifacts_only(self, repo):
        projection = _project(
            _engine(repo), repo, ["Kavya/"], audience=GuidanceAudience.FABLE_REVIEW
        )
        assert projection.logical_ids == ("pg.tgt.root.review", "pg.tgt.kavya.review")
        assert "ROOT-REVIEW-SOURCE-ARTIFACT" in projection.text
        assert "KAVYA-REVIEW-SOURCE-ARTIFACT" in projection.text
        for worker_only in (
            "ROOT-SOURCE-ARTIFACT",
            "KAVYA-SOURCE-ARTIFACT",
            "ROOT-POLICY-ARTIFACT",
            "KAVYA-POLICY-ARTIFACT",
        ):
            assert worker_only not in projection.text

    def test_worker_audience_never_receives_review_artifacts(self, repo):
        projection = _project(_engine(repo), repo, ["Kavya/"])
        assert "ROOT-REVIEW-SOURCE-ARTIFACT" not in projection.text
        assert "KAVYA-REVIEW-SOURCE-ARTIFACT" not in projection.text

    def test_fable_gets_root_review_for_a_root_task(self, repo):
        projection = _project(
            _engine(repo), repo, ["README.md"], audience=GuidanceAudience.FABLE_REVIEW
        )
        assert projection.logical_ids == ("pg.tgt.root.review",)

    def test_fable_review_of_a_scope_without_a_review_projection_fails_closed(self, repo):
        """SLIC has an approved *worker* projection but no review projection."""
        with pytest.raises(ProjectGuidanceNotApproved) as exc:
            _project(
                _engine(repo),
                repo,
                ["SLIC Agent/x.py"],
                audience=GuidanceAudience.FABLE_REVIEW,
            )
        assert exc.value.details["audience"] == "fable_review"
        assert exc.value.details["scope_prefix"] == "SLIC Agent/"

    def test_review_and_worker_artifact_sets_are_disjoint(self, repo):
        worker = _project(_engine(repo), repo, ["Kavya/"])
        review = _project(
            _engine(repo), repo, ["Kavya/"], audience=GuidanceAudience.FABLE_REVIEW
        )
        assert not (set(worker.artifact_paths) & set(review.artifact_paths))

    @pytest.mark.skipif(
        not REAL_TARGET_REPO.is_dir(), reason="full-voice-agent not present"
    )
    def test_shipped_review_context_carries_facts_but_not_methodology(self):
        manifest = load_manifest(REAL_MANIFEST)
        review = (
            PROJECT_ROOT / manifest.entries["pg.fva.root.review"].source_artifact.path
        ).read_text()
        worker = (
            PROJECT_ROOT / manifest.entries["pg.fva.root"].source_artifact.path
        ).read_text()
        # Architecture / acceptance facts are present.
        assert "Python 3.11" in review
        assert "tests" in review.lower()
        # Implementation coaching lives only in the worker projection.
        for methodology in ("graphify query", "raw files"):
            assert methodology in worker, f"{methodology!r} missing from worker context"
            assert methodology not in review, f"{methodology!r} leaked into review context"


# ---------------------------------------------------------------------------
# Emission order (§9.8)
# ---------------------------------------------------------------------------


class TestEmissionOrder:
    def test_policy_precedes_source_for_every_scope(self, repo):
        text = _project(_engine(repo), repo, ["Kavya/"]).text
        assert text.index("ROOT-POLICY-ARTIFACT") < text.index("ROOT-SOURCE-ARTIFACT")
        assert text.index("KAVYA-POLICY-ARTIFACT") < text.index("KAVYA-SOURCE-ARTIFACT")
        assert text.index("ROOT-SOURCE-ARTIFACT") < text.index("KAVYA-POLICY-ARTIFACT")

    def test_projection_is_byte_stable(self, repo):
        engine = _engine(repo)
        a = _project(engine, repo, ["Kavya/", "Flico Agent/"])
        b = _project(engine, repo, ["Flico Agent/", "Kavya/"])
        assert a.text == b.text
        assert a.fingerprint == b.fingerprint

    def test_projected_bytes_is_the_sum_of_artifact_bytes(self, repo):
        projection = _project(_engine(repo), repo, ["Kavya/"])
        assert projection.projected_bytes == sum(
            a.nbytes for a in projection.artifacts
        )
        assert projection.projected_bytes == len(projection.text.encode("utf-8"))
        assert projection.approx_tokens == estimate_tokens(projection.projected_bytes)

    def test_size_cap_fails_closed_rather_than_truncating(self, repo):
        engine = _engine(repo, max_projected_bytes=50)
        with pytest.raises(ProjectGuidancePolicyViolation) as exc:
            _project(engine, repo, ["Kavya/"])
        assert exc.value.details["reason"] == "size_cap_exceeded"


# ---------------------------------------------------------------------------
# §9.6 — DEFAULT-DENY discovery (verification only)
# ---------------------------------------------------------------------------


class TestUnapprovedFileDiscovery:
    def test_a_new_instruction_file_is_reported(self, repo):
        engine = _engine(repo)
        assert engine.discover_unapproved() == ()
        _write(repo["top"] / "docs/CLAUDE.md", NESTED_TEXT)
        found = engine.discover_unapproved()
        assert found == ("docs/CLAUDE.md",)

    def test_assert_no_unapproved_files_raises(self, repo):
        engine = _engine(repo)
        _write(repo["top"] / "docs/AGENTS.md", NESTED_TEXT)
        with pytest.raises(UnapprovedProjectGuidanceFile) as exc:
            engine.assert_no_unapproved_files()
        assert exc.value.details["unreviewed"] == ["docs/AGENTS.md"]

    def test_worktree_copies_are_excluded_from_discovery(self, repo):
        """The shadow copy created by the fixture must not be reported."""
        engine = _engine(repo)
        assert engine.discover_unapproved() == ()
        shadow = ".claude/worktrees/agent-aa383920556fd0f25/Kavya/CLAUDE.md"
        assert (repo["top"] / shadow).is_file(), "fixture must actually create it"

    def test_known_foreign_file_is_not_reported(self, repo):
        engine = _engine(repo)
        assert (repo["top"] / "Taskforce_AI_Website/CLAUDE.md").is_file()
        assert engine.discover_unapproved() == ()

    def test_discovery_never_feeds_selection(self, repo):
        engine = _engine(repo)
        before = _project(engine, repo, ["Kavya/"]).text
        _write(repo["top"] / "Kavya/CLAUDE.local.md", NESTED_TEXT)
        _write(repo["top"] / "docs/CLAUDE.md", NESTED_TEXT)
        after = _project(engine, repo, ["Kavya/"]).text
        assert before == after


# ---------------------------------------------------------------------------
# §16 — resume fingerprint
# ---------------------------------------------------------------------------


class TestResumeFingerprint:
    def test_fingerprint_is_stable(self, repo):
        engine = _engine(repo)
        a = _project(engine, repo, ["Kavya/"])
        b = _project(engine, repo, ["Kavya/"])
        assert a.fingerprint == b.fingerprint
        assert re.fullmatch(r"[0-9a-f]{64}", a.fingerprint)

    @pytest.mark.parametrize(
        "paths,envelope",
        [
            (["Kavya/"], "task-2"),
            (["SLIC Agent/"], "task-1"),
            (["Kavya/", "graphify-out/"], "task-1"),
        ],
    )
    def test_fingerprint_changes_with_the_inputs(self, repo, paths, envelope):
        engine = _engine(repo)
        base = _project(engine, repo, ["Kavya/"], task_envelope_id="task-1")
        other = engine.project(
            paths, repository=repo["identity"], task_envelope_id=envelope
        )
        assert base.fingerprint != other.fingerprint

    def test_verify_accepts_an_unchanged_context(self, repo):
        engine = _engine(repo)
        record = _project(engine, repo, ["Kavya/"]).to_record()
        again = engine.verify(record, repository=repo["identity"])
        assert again.fingerprint == record.fingerprint

    def test_verify_fails_closed_when_a_source_changed(self, repo):
        engine = _engine(repo)
        record = _project(engine, repo, ["Kavya/"]).to_record()
        for name in ("CLAUDE.md", "AGENTS.md"):
            (repo["top"] / "Kavya" / name).write_text("CHANGED BETWEEN DISPATCH AND RESUME\n")
        with pytest.raises(ProjectGuidanceSourceChanged):
            engine.verify(record, repository=repo["identity"])

    def test_verify_fails_closed_on_a_reapproved_manifest(self, repo):
        """The artifact was re-approved: hashes verify, the fingerprint does not."""
        engine = _engine(repo)
        record = _project(engine, repo, ["Kavya/"]).to_record()
        _write(
            repo["disp"] / "config/guidance/worker/kavya.source.txt",
            KAVYA_SOURCE_ARTIFACT + "A NEW APPROVED CLAUSE\n",
        )
        reapproved = _engine(repo, _manifest_dict(repo))
        with pytest.raises(ProjectGuidanceResumeDrift) as exc:
            reapproved.verify(record, repository=repo["identity"])
        assert exc.value.details["expected_fingerprint"] == record.fingerprint

    def test_verify_rechecks_repository_identity(self, repo):
        engine = _engine(repo)
        record = _project(engine, repo, ["Kavya/"]).to_record()
        wrong = RepositoryIdentity(
            toplevel=repo["identity"].toplevel,
            git_dir=repo["identity"].git_dir,
            origin_url="https://elsewhere.invalid/x.git",
            root_commit=repo["identity"].root_commit,
        )
        with pytest.raises(ProjectGuidanceRepositoryMismatch):
            engine.verify(record, repository=wrong)

    def test_record_carries_everything_resume_needs(self, repo):
        record = _project(_engine(repo), repo, ["Kavya/"]).to_record()
        assert record.logical_ids == ["pg.tgt.root", "pg.tgt.kavya"]
        assert record.graph_variant == "GATED_OFF"
        assert record.task_envelope_id == "task-1"
        assert record.audience == "worker"
        assert record.repository_id == "tgt"


# ---------------------------------------------------------------------------
# Persisted evidence
# ---------------------------------------------------------------------------


class TestPersistedRecord:
    def test_task_record_accepts_a_project_guidance_record(self, repo):
        record = _project(_engine(repo), repo, ["Kavya/"]).to_record()
        task = TaskRecord(
            schema_version="1.0",
            task_id="t",
            state=TaskState.RUNNING,
            created_at=utc_now(),
            updated_at=utc_now(),
            project_guidance=record,
        )
        assert task.project_guidance is not None
        assert task.project_guidance.fingerprint == record.fingerprint

    def test_task_record_without_project_guidance_still_loads(self):
        task = TaskRecord(
            schema_version="1.0",
            task_id="t",
            state=TaskState.CREATED,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        assert task.project_guidance is None

    def test_run_metadata_carries_the_fingerprint(self, repo):
        record = _project(_engine(repo), repo, ["Kavya/"]).to_record()
        metadata = RunMetadata(
            run_id="r",
            run_index=1,
            task_id="t",
            kind=RunKind.DISPATCH,
            role=WorkerRole.IMPLEMENTER,
            model="sonnet",
            session_id="s",
            started_at=utc_now(),
            project_guidance_fingerprint=record.fingerprint,
        )
        assert metadata.project_guidance_fingerprint == record.fingerprint

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
        assert metadata.project_guidance_fingerprint is None

    def test_record_rejects_a_malformed_fingerprint(self):
        with pytest.raises(Exception):
            ProjectGuidanceRecord(
                manifest_schema_version="1.0.0",
                approval_version="v1",
                audience="worker",
                repository_id="tgt",
                graph_variant="GATED_OFF",
                task_envelope_id="t",
                fingerprint="not-a-hash",
            )


# ---------------------------------------------------------------------------
# Config section
# ---------------------------------------------------------------------------


def _config(section: dict | None, git_repo: Path) -> dict:
    payload = {
        "dispatcher": {"state_dir": "./state"},
        "models": {"sonnet": "sonnet", "opus": "opus", "fable": "fable"},
        "routing": {"default_model": "sonnet"},
        "security": {"allowed_repository_roots": [str(git_repo)]},
    }
    if section is not None:
        payload["project_guidance"] = section
    return payload


class TestProjectGuidanceConfigSection:
    def test_defaults_are_disabled(self, git_repo):
        config = load_config_from_mapping(_config(None, git_repo))
        assert config.project_guidance.enabled is False
        assert config.project_guidance.mode == "projected"
        assert config.project_guidance.manifest_path.endswith("approved-guidance.json")

    def test_native_mode_is_refused(self, git_repo):
        with pytest.raises(ConfigurationError):
            load_config_from_mapping(_config({"mode": "native"}, git_repo))

    def test_fail_on_drift_cannot_be_disabled(self, git_repo):
        with pytest.raises(ConfigurationError):
            load_config_from_mapping(_config({"fail_on_drift": False}, git_repo))

    def test_unknown_key_is_refused(self, git_repo):
        with pytest.raises(ConfigurationError):
            load_config_from_mapping(_config({"surprise": 1}, git_repo))

    def test_approved_guidance_file_property(self, git_repo):
        config = load_config_from_mapping(_config({"enabled": True}, git_repo))
        assert config.approved_guidance_file.name == "approved-guidance.json"

    def test_disabled_engine_projects_nothing(self, repo):
        engine = _engine(repo, enabled=False)
        projection = _project(engine, repo, ["Kavya/"])
        assert projection.text == ""
        assert projection.mode == "disabled"
        assert projection.logical_ids == ()

    def test_shipped_toml_files_declare_the_section(self):
        for name in ("dispatcher.toml", "dispatcher.example.toml"):
            text = (PROJECT_ROOT / "config" / name).read_text()
            assert "[project_guidance]" in text, name
            assert "approved-guidance.json" in text, name


# ---------------------------------------------------------------------------
# Shipped manifest, real repository
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not REAL_TARGET_REPO.is_dir(), reason="full-voice-agent not present on this host"
)
class TestShippedManifestAgainstRealRepository:
    @pytest.fixture
    def approved(self):
        """The shipped manifest with approval flipped IN MEMORY ONLY.

        The file on disk stays ``PENDING_SOL``; this fixture exists to measure
        what the projection *will* be, not to approve anything.
        """
        data = json.loads(REAL_MANIFEST.read_text())
        data["approval"] = dict(data["approval"], state="APPROVED")
        manifest = load_manifest_from_mapping(data, source_path=str(REAL_MANIFEST))
        return ProjectGuidanceEngine(
            manifest, project_root=PROJECT_ROOT, max_projected_bytes=200_000
        )

    @pytest.fixture
    def identity(self):
        return RepositoryIdentity(
            toplevel="/home/dev/full-voice-agent",
            git_dir="/home/dev/full-voice-agent/.git",
            origin_url="https://github.com/taskforce-ai-dev/full-voice-agent.git",
            root_commit="722c53ee7d33fa866ec18de778382820ba54dc04",
        )

    def test_every_artifact_hash_matches_disk(self):
        manifest = load_manifest(REAL_MANIFEST)
        for entry in manifest.entries.values():
            for artifact in (entry.source_artifact, entry.policy_artifact):
                if artifact is None:
                    continue
                raw = (PROJECT_ROOT / artifact.path).read_bytes()
                assert _sha(raw) == artifact.sha256, artifact.path
                assert len(raw) == artifact.bytes, artifact.path

    def test_every_source_hash_matches_the_real_repository(self):
        manifest = load_manifest(REAL_MANIFEST)
        for entry in manifest.entries.values():
            for source in entry.sources:
                raw = Path(source.resolved_path).read_bytes()
                assert _sha(raw) == source.sha256, source.source_path

    def test_root_pair_is_not_identical_and_that_is_recorded(self):
        manifest = load_manifest(REAL_MANIFEST)
        root = manifest.entries["pg.fva.root"]
        by_path = {s.source_path: s.sha256 for s in root.sources}
        assert by_path["AGENTS.md"] != by_path["CLAUDE.md"]
        assert root.source_relationship == "UNION_OF_INDEPENDENT_SOURCES"
        assert "ROOT_PAIR_DRIFT_ACKNOWLEDGED" in root.flags

    @pytest.mark.parametrize(
        "logical_id",
        ["pg.fva.kavya", "pg.fva.slic", "pg.fva.flico", "pg.fva.bsl", "pg.fva.sofia"],
    )
    def test_agent_pairs_are_byte_identical_aliases(self, logical_id):
        manifest = load_manifest(REAL_MANIFEST)
        entry = manifest.entries[logical_id]
        assert len({s.sha256 for s in entry.sources}) == 1
        assert any(s.alias_of for s in entry.sources)

    @pytest.mark.parametrize(
        "shape,paths,expected_ids,expected_bytes",
        [
            ("root_only", ["ops/", "README.md"], ("pg.fva.root",), 11279),
            (
                "root_plus_kavya",
                ["Kavya/"],
                ("pg.fva.root", "pg.fva.kavya"),
                29931,
            ),
            (
                "root_plus_slic",
                ["SLIC Agent/claim_api.py"],
                ("pg.fva.root", "pg.fva.slic"),
                21203,
            ),
            (
                "root_plus_flico",
                ["Flico Agent/kb/engine.py"],
                ("pg.fva.root", "pg.fva.flico"),
                23087,
            ),
        ],
    )
    def test_real_dispatch_shapes_match_the_recorded_budget(
        self, approved, identity, shape, paths, expected_ids, expected_bytes
    ):
        projection = approved.project(
            paths, repository=identity, task_envelope_id="budget-check"
        )
        assert projection.logical_ids == expected_ids
        assert projection.projected_bytes == expected_bytes, shape
        budget = approved.manifest.dispatch_size_budget["worker"][shape]
        assert projection.projected_bytes == budget["bytes"]
        assert projection.approx_tokens == budget["approx_tokens"]

    @pytest.mark.parametrize(
        "shape,paths,expected_bytes",
        [
            ("root_only", ["ops/"], 4903),
            ("root_plus_kavya", ["Kavya/"], 12457),
        ],
    )
    def test_real_review_shapes_match_the_recorded_budget(
        self, approved, identity, shape, paths, expected_bytes
    ):
        projection = approved.project(
            paths,
            repository=identity,
            audience=GuidanceAudience.FABLE_REVIEW,
            task_envelope_id="budget-check",
        )
        assert projection.projected_bytes == expected_bytes, shape
        budget = approved.manifest.dispatch_size_budget["fable_review"][shape]
        assert projection.projected_bytes == budget["bytes"]

    def test_projection_is_far_smaller_than_verbatim_concatenation(self, approved, identity):
        projection = approved.project(
            ["Kavya/"], repository=identity, task_envelope_id="x"
        )
        rejected = approved.manifest.dispatch_size_budget["rejected_alternative"]["bytes"]
        assert rejected == 319819
        assert projection.projected_bytes * 10 < rejected

    def test_every_worked_scope_outcome_reproduces(self, approved, identity):
        """All 14 rows of ``worked_scope_outcomes`` replayed against the engine."""
        outcomes = approved.manifest.worked_scope_outcomes
        assert len(outcomes) == 14
        for row in outcomes:
            paths = list(row["allowed_paths"])
            if "error" in row:
                expected = row["error"].split(" ", 1)[0]
                with pytest.raises(PolicyViolation) as exc:
                    approved.project(
                        paths, repository=identity, task_envelope_id="worked"
                    )
                assert type(exc.value).__name__ == expected, paths
            else:
                projection = approved.project(
                    paths, repository=identity, task_envelope_id="worked"
                )
                assert set(projection.logical_ids) == set(row["selected"]), paths
                assert projection.graph_variant == row["graph_variant"], paths

    def test_unapproved_subprojects_refuse_with_no_fallback(self, approved, identity):
        for paths, logical_id in (
            (["BSL Agent/"], "pg.fva.bsl"),
            (["HattonHills/server.py"], "pg.fva.hattonhills"),
            (["Sofia Agent/"], "pg.fva.sofia"),
        ):
            with pytest.raises(ProjectGuidanceNotApproved) as exc:
                approved.project(paths, repository=identity, task_envelope_id="x")
            assert exc.value.details["logical_id"] == logical_id
            assert exc.value.details["fallback_to_root_only"] is False

    def test_the_real_repository_has_no_unapproved_instruction_files(self, approved):
        assert approved.discover_unapproved() == ()

    def test_audit_is_root_relative_safe(self):
        """``config.project_root`` defaults to ``"."``; audit must still match."""
        data = json.loads(REAL_MANIFEST.read_text())
        engine = ProjectGuidanceEngine(
            load_manifest_from_mapping(data),
            project_root=os.path.relpath(PROJECT_ROOT),
            max_projected_bytes=200_000,
        )
        rows = [r for r in engine.audit() if r.kind == "artifact"]
        assert rows
        assert all(r.status == "MATCH" for r in rows), [
            (r.path, r.status, r.detail) for r in rows if r.status != "MATCH"
        ]

    def test_audit_reports_no_drift(self, approved):
        rows = approved.audit()
        assert rows
        assert all(row.status == "MATCH" for row in rows), [
            (r.path, r.status) for r in rows if r.status != "MATCH"
        ]


# ---------------------------------------------------------------------------
# Module shape
# ---------------------------------------------------------------------------


class TestModuleShape:
    def test_module_exposes_no_execution_helper(self):
        for forbidden in ("run", "execute", "shell", "spawn"):
            assert not any(
                forbidden in name.lower() for name in pg_mod.__all__
            ), forbidden

    def test_module_imports_no_subprocess_and_evaluates_nothing(self):
        source = Path(pg_mod.__file__).read_text()
        for forbidden in ("import subprocess", "os.system", "eval(", "exec(", "shell=True"):
            assert forbidden not in source, forbidden

    def test_no_runtime_summariser(self):
        """§10: deterministic and reviewable only. No LLM in the loop."""
        source = Path(pg_mod.__file__).read_text().lower()
        for forbidden in ("anthropic", "openai", "summarise_with", "summarize_with"):
            assert forbidden not in source, forbidden

    def test_estimate_tokens_rounds_to_the_recorded_budget(self):
        assert estimate_tokens(11279) == 2820
        assert estimate_tokens(29931) == 7483
        assert estimate_tokens(4903) == 1226
