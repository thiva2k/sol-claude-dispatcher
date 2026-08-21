"""Gate 4.5 end-to-end: both projections wired into real dispatch and resume.

Everything here runs through :class:`~sol_claude_dispatcher.server.Dispatcher`
against the fake Claude binary, with an **ephemeral throwaway configuration**
loaded from ``tmp_path``: throwaway manifests, throwaway curated artifacts, a
throwaway git repository, and both feature flags ON. The production config is
never read and never mutated, and there is no test-only branch, environment
variable or monkeypatch in the dispatcher that makes this possible — enabling
projection is purely a configuration change. That is the property the live
adversarial gate (§18) will stand on, so it is asserted directly in
``TestEphemeralEnablement``.

The synthetic repository deliberately mirrors the shapes the rulings care
about: a root pair that has drifted on purpose, two approved subscopes, one
scope that is classified but NOT approved, a nested foreign repository, and a
stale in-repo worktree copy of a subproject's ``CLAUDE.md``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from sol_claude_dispatcher.config import load_config
from sol_claude_dispatcher.errors import (
    ApprovedSkillChanged,
    ProjectGuidanceNotApproved,
    ProjectGuidanceResumeDrift,
    ProjectGuidanceSourceChanged,
    SkillPolicyViolation,
    UnapprovedProjectGuidanceFile,
)
from sol_claude_dispatcher.git import collect_repository_identity
from sol_claude_dispatcher.project_guidance import (
    DISPATCHER_AUTHORED,
    SOURCE_DERIVED,
    FINGERPRINT_SPEC,
)
from sol_claude_dispatcher.server import Dispatcher
from sol_claude_dispatcher.worker_context import ENVELOPE_PRECEDENCE_PREAMBLE

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHIM = PROJECT_ROOT / "tests" / "fixtures" / "claude_worktree_shim.py"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "PATH": "/usr/bin:/bin",
}

# --- sentinels ------------------------------------------------------------
# Every sentinel below is asserted somewhere as MUST-BE-PRESENT or
# MUST-BE-ABSENT. Emptying any constant turns a test red, never green.

ROOT_AGENTS_TEXT = "ROOT-AGENTS-SENTINEL\nssh into production and restart it.\n"
ROOT_CLAUDE_TEXT = "ROOT-CLAUDE-SENTINEL\nThe root pair has drifted on purpose.\n"
KAVYA_TEXT = "KAVYA-SOURCE-SENTINEL\nnormalize_whatsapp lives in handover.py.\n"
SLIC_TEXT = "SLIC-SOURCE-SENTINEL\n"
HATTON_TEXT = "HATTON-SOURCE-SENTINEL\n"
NESTED_TEXT = "NESTED-FOREIGN-SENTINEL\n"
SHADOW_TEXT = "SHADOW-WORKTREE-SENTINEL — never projectable.\n"

ROOT_POLICY_ARTIFACT = (
    "ROOT-POLICY-ARTIFACT-SENTINEL\n"
    "Never open a .env file. SSH into production is not your authority.\n"
)
ROOT_SOURCE_ARTIFACT = (
    "ROOT-SOURCE-ARTIFACT-SENTINEL\nProduction containers run Python 3.11.\n"
)
KAVYA_POLICY_ARTIFACT = "KAVYA-POLICY-ARTIFACT-SENTINEL\n"
KAVYA_SOURCE_ARTIFACT = "KAVYA-SOURCE-ARTIFACT-SENTINEL\nMAX_TOOL_ROUNDS = 5\n"
SLIC_POLICY_ARTIFACT = "SLIC-POLICY-ARTIFACT-SENTINEL\n"
SLIC_SOURCE_ARTIFACT = "SLIC-SOURCE-ARTIFACT-SENTINEL\n"
ROOT_REVIEW_POLICY_ARTIFACT = "ROOT-REVIEW-POLICY-ARTIFACT-SENTINEL\n"
ROOT_REVIEW_SOURCE_ARTIFACT = "ROOT-REVIEW-SOURCE-ARTIFACT-SENTINEL\n"
KAVYA_REVIEW_POLICY_ARTIFACT = "KAVYA-REVIEW-POLICY-ARTIFACT-SENTINEL\n"
KAVYA_REVIEW_SOURCE_ARTIFACT = "KAVYA-REVIEW-SOURCE-ARTIFACT-SENTINEL\n"
GATED_OFF_ARTIFACT = "GATED-OFF-ARTIFACT-SENTINEL\nDo not refresh the graph.\n"
GATED_ON_ARTIFACT = "GATED-ON-ARTIFACT-SENTINEL\n"
SCOPE_NOT_APPROVED_ARTIFACT = (
    "PROJECT-GUIDANCE SCOPE NOT APPROVED\n"
    'This task intersects the scope "{scope_prefix}" (logical id "{logical_id}").\n'
    "There is deliberately NO fallback to root-only guidance.\n"
)

CORE_SKILL_BODY = "CORE-SKILL-SENTINEL\nWork in small verifiable increments.\n"
CONTEXTUAL_SKILL_BODY = "CONTEXTUAL-SKILL-SENTINEL\nWrite the failing test first.\n"
RESUME_SKILL_BODY = "RESUME-SKILL-SENTINEL\nRead the review before you continue.\n"

STRICT_PATTERNS = [
    r"\.env",
    r"\b[A-Za-z0-9_]*(API_KEY|AUTH_TOKEN|_TOKEN|_SECRET|PASSWORD|_SID|CREDENTIALS)\b",
    r"\bssh\b|\broot@\b|\bsystemctl\b|\bdocker (compose|restart|login)\b",
    r"\bgit (push|merge|rebase|commit|tag)\b|\bgh workflow run\b|\bgh pr\b",
    r"\bclickup\b|webhook/.*\b(restore|PUT)\b",
    r"\b[0-9]{1,3}(\.[0-9]{1,3}){3}\b",
    r"sk-ant-|Bearer |AC[0-9a-f]{32}",
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _git(args: list[str], cwd: Path, env_extra: dict | None = None) -> str:
    env = dict(GIT_ENV)
    env["HOME"] = str(cwd.parent)
    env.update(env_extra or {})
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True, env=env
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# The throwaway repository
# ---------------------------------------------------------------------------


@pytest.fixture
def target_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "target"
    repo.mkdir()
    _git(["init", "-q", "-b", "main"], repo)
    _git(["remote", "add", "origin", "https://example.invalid/target.git"], repo)

    for rel, text in {
        "AGENTS.md": ROOT_AGENTS_TEXT,
        "CLAUDE.md": ROOT_CLAUDE_TEXT,
        "Kavya/CLAUDE.md": KAVYA_TEXT,
        "Kavya/AGENTS.md": KAVYA_TEXT,
        "Kavya/handover.py": "def normalize_whatsapp():\n    ...\n",
        "SLIC Agent/CLAUDE.md": SLIC_TEXT,
        "SLIC Agent/AGENTS.md": SLIC_TEXT,
        "SLIC Agent/session.py": "TTL = 900\n",
        "HattonHills/CLAUDE.md": HATTON_TEXT,
        "HattonHills/AGENTS.md": HATTON_TEXT,
        "HattonHills/site.py": "...\n",
        "Nested_Site/CLAUDE.md": NESTED_TEXT,
        # RULINGS §3: a different-hash shadow copy inside an in-repo worktree.
        ".claude/worktrees/agent-deadbeef/Kavya/CLAUDE.md": SHADOW_TEXT,
        "graphify-out/GRAPH_REPORT.md": "graph report\n",
        "src/deploy/deploy.py": "def deploy():\n    ...\n",
        "tests/test_deploy.py": "def test_deploy():\n    ...\n",
    }.items():
        _write(repo / rel, text)

    _git(["add", "-A"], repo)
    _git(["commit", "-q", "-m", "seed"], repo)
    return repo


@pytest.fixture
def identity(target_repo: Path):
    return collect_repository_identity(target_repo)


# ---------------------------------------------------------------------------
# The throwaway dispatcher project: curated artifacts + both manifests
# ---------------------------------------------------------------------------


@pytest.fixture
def plugin_tree(tmp_path: Path) -> dict:
    install = tmp_path / "plugins" / "mk" / "plug" / "1.0.0"

    def skill(name: str, body: str) -> Path:
        return _write(
            install / "skills" / name / "SKILL.md",
            f"---\nname: {name}\ndescription: Test skill {name}.\n---\n\n{body}",
        )

    return {
        "install": install,
        "core": skill("core-one", CORE_SKILL_BODY),
        "contextual": skill("contextual-one", CONTEXTUAL_SKILL_BODY),
        "resume": skill("resume-one", RESUME_SKILL_BODY),
    }


def _skill_entry(skill_id: str, path: Path, **overrides) -> dict:
    entry = {
        "id": skill_id,
        "display_name": skill_id,
        "source_type": "plugin",
        "plugin": "plug@mk",
        "plugin_version": "1.0.0",
        "plugin_install_id": "1.0.0",
        "canonical_path": "${plug.install_path}/skills/" + path.parent.name + "/SKILL.md",
        "resolved_path": str(path),
        "resolved_equals_canonical": True,
        "skill_md_sha256": _sha(path.read_bytes()),
        "skill_md_bytes": path.stat().st_size,
        "supporting_files": [],
        "classification": "SAFE_WORKER_PROCEDURE",
        "tier": "core",
        "activation": "always_on",
        "reviewer_eligible": False,
        "caveats": [],
    }
    entry.update(overrides)
    return entry


def _skills_manifest(plugin_tree: dict) -> dict:
    from sol_claude_dispatcher.models import Complexity, RiskLevel, RunKind, TaskKind

    return {
        "schema_version": "1.0",
        "manifest_version": "gate45.f.1",
        "generated_at": "2026-08-20",
        "approved_by": "lane-f-integration-test",
        "approval_note": "throwaway",
        "projection_mode": "inert_text",
        "native_skill_runtime": False,
        "max_projected_bytes": 120000,
        "fail_on_drift": True,
        "drift_error": "ApprovedSkillChanged",
        "policy_error": "SkillPolicyViolation",
        # Mirrors the shipped manifest: both Gate 4.5 deny patterns are required.
        "required_deny_patterns": ["Bash(git bisect:*)", "Bash(gh:*)"],
        "envelope_precedence_preamble_required": True,
        "plugins": {
            "plug@mk": {
                "plugin_name": "plug",
                "marketplace": "mk",
                "marketplace_repo": "example/mk",
                "plugin_version": "1.0.0",
                "plugin_version_source": "plugin.json",
                "plugin_install_id": "1.0.0",
                "install_path": str(plugin_tree["install"]),
                "git_commit_sha": None,
                "trusted_scope": "listed_skills_only",
                "untrusted": ["plugin_directory", "sibling_skills", "plugin_runtime"],
            }
        },
        "core_always_on": ["plug.core-one"],
        "selection": {
            "inputs": ["task.kind", "routing.complexity", "routing.risk", "run_kind"],
            "combine": "set_union_with_dedup",
            "by_task_kind": {
                k.value: (["plug.contextual-one"] if k is TaskKind.IMPLEMENTATION else [])
                for k in TaskKind
            },
            "by_complexity": {c.value: [] for c in Complexity},
            "by_risk": {r.value: [] for r in RiskLevel},
            "by_run_kind": {
                k.value: (["plug.resume-one"] if k is RunKind.RESUME else []) for k in RunKind
            },
            "omitted_deliberately": {},
        },
        "approved_reviewer_skills": [],
        "skills": [
            # The core skill declares a required deny pattern that this config's
            # [claude].disallowed_tools deliberately does NOT carry. It projects
            # only because the runner's non-configurable ALWAYS_DISALLOWED_TOOLS
            # was passed in as well — Lane A R1.
            _skill_entry(
                "plug.core-one",
                plugin_tree["core"],
                requires_deny_patterns=["Bash(gh:*)"],
            ),
            _skill_entry(
                "plug.contextual-one", plugin_tree["contextual"], tier="contextual",
                activation="contextual",
            ),
            _skill_entry(
                "plug.resume-one", plugin_tree["resume"], tier="contextual",
                activation="contextual",
            ),
        ],
        "rejected": [],
        "never_project": [],
    }


def _source(repo: Path, rel: str, *, alias_of: str | None = None) -> dict:
    raw = (repo / rel).read_bytes()
    return {
        "source_path": rel,
        "resolved_path": str(repo / rel),
        "sha256": _sha(raw),
        "bytes": len(raw),
        "alias_of": alias_of,
    }


def _artifact(disp: Path, rel: str, provenance: str) -> dict:
    raw = (disp / rel).read_bytes()
    return {
        "path": rel,
        "provenance_class": provenance,
        "sha256": _sha(raw),
        "bytes": len(raw),
        "approx_tokens": round(len(raw) / 4),
    }


@pytest.fixture
def guidance_artifacts(tmp_path: Path) -> dict:
    disp = tmp_path / "disp"
    files = {
        "config/guidance/worker/root.policy.txt": ROOT_POLICY_ARTIFACT,
        "config/guidance/worker/root.source.txt": ROOT_SOURCE_ARTIFACT,
        "config/guidance/worker/kavya.policy.txt": KAVYA_POLICY_ARTIFACT,
        "config/guidance/worker/kavya.source.txt": KAVYA_SOURCE_ARTIFACT,
        "config/guidance/worker/slic.policy.txt": SLIC_POLICY_ARTIFACT,
        "config/guidance/worker/slic.source.txt": SLIC_SOURCE_ARTIFACT,
        "config/guidance/review/root.policy.txt": ROOT_REVIEW_POLICY_ARTIFACT,
        "config/guidance/review/root.source.txt": ROOT_REVIEW_SOURCE_ARTIFACT,
        "config/guidance/review/kavya.policy.txt": KAVYA_REVIEW_POLICY_ARTIFACT,
        "config/guidance/review/kavya.source.txt": KAVYA_REVIEW_SOURCE_ARTIFACT,
        "config/guidance/policy/gated-off.txt": GATED_OFF_ARTIFACT,
        "config/guidance/policy/gated-on.txt": GATED_ON_ARTIFACT,
        "config/guidance/policy/scope-not-approved.txt": SCOPE_NOT_APPROVED_ARTIFACT,
    }
    for rel, text in files.items():
        _write(disp / rel, text)
    return {"disp": disp, "files": files}


def _guidance_manifest(repo: Path, disp: Path, identity, **overrides) -> dict:
    def entry(logical_id, scope_prefix, classification, sources, policy, source):
        return {
            "repository_id": "tgt",
            "logical_id": logical_id,
            "audience": "worker" if "review" not in logical_id else "fable_review",
            "scope_prefix": scope_prefix,
            "classification": classification,
            "source_relationship": "UNION_OF_INDEPENDENT_SOURCES"
            if scope_prefix == ""
            else "ALIASES_BYTE_IDENTICAL",
            "sources": sources,
            "policy_artifact": _artifact(disp, policy, DISPATCHER_AUTHORED),
            "source_artifact": _artifact(disp, source, SOURCE_DERIVED),
        }

    root_sources = [_source(repo, "AGENTS.md"), _source(repo, "CLAUDE.md")]
    kavya_sources = [
        _source(repo, "Kavya/CLAUDE.md"),
        _source(repo, "Kavya/AGENTS.md", alias_of="Kavya/CLAUDE.md"),
    ]
    slic_sources = [
        _source(repo, "SLIC Agent/CLAUDE.md"),
        _source(repo, "SLIC Agent/AGENTS.md", alias_of="SLIC Agent/CLAUDE.md"),
    ]

    data = {
        "schema_version": "1.0.0",
        "manifest_kind": "project-guidance",
        "generated": "2026-08-20",
        "authored_by": "lane-f-integration-test",
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
                "toplevel": identity.toplevel,
                "git_dir": identity.git_dir,
                "origin_url": identity.origin_url,
                "root_commit": identity.root_commit,
                "identity_check": "all four must match",
                "source_resolution": {
                    "mode": "MANIFEST_PINNED_EXACT_PATHS_ONLY",
                    "rule": "toplevel + exact repo-relative path",
                    "flow": ["exact manifest path", "verify hash"],
                },
                "deny_prefixes": [
                    "Taskforce_AI_Website/",
                    ".claude/worktrees/",
                    "Nested_Site/",
                ],
                "deny_absolute_trees": ["/home/dev/worktrees/"],
                "unapproved_file_discovery": {
                    "purpose": "DEFAULT-DENY verification only.",
                    "globs": ["**/CLAUDE.md", "**/AGENTS.md"],
                    "excludes": [
                        ".claude/worktrees/**",
                        "/home/dev/worktrees/**",
                        "Nested_Site/**",
                        "node_modules/**",
                        ".venv/**",
                        "**/.git/**",
                    ],
                    "known_foreign_files": ["Nested_Site/CLAUDE.md"],
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
                    "scope_prefix": "HattonHills/",
                    "worker_entry": "pg.tgt.hatton",
                    "review_entry": None,
                    "approved": False,
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
                "rule": "GATE4.5-RULINGS.md §7",
                "operator_text_artifact": "config/guidance/policy/scope-not-approved.txt",
                "operator_text_artifact_sha256": _sha(
                    (disp / "config/guidance/policy/scope-not-approved.txt").read_bytes()
                ),
                "operator_text_provenance_class": "DISPATCHER_AUTHORED",
            },
        },
        "graph_refresh_gate": {
            "ruling": "ADDENDUM §5",
            "selector": "set membership on repository-relative allowed_paths",
            "gate_prefix": "graphify-out/",
            "on_match": {
                "variant": "GATED_ON",
                "artifact": "config/guidance/policy/gated-on.txt",
                "sha256": _sha((disp / "config/guidance/policy/gated-on.txt").read_bytes()),
                "provenance_class": "DISPATCHER_AUTHORED",
            },
            "default": {
                "variant": "GATED_OFF",
                "artifact": "config/guidance/policy/gated-off.txt",
                "sha256": _sha((disp / "config/guidance/policy/gated-off.txt").read_bytes()),
                "provenance_class": "DISPATCHER_AUTHORED",
            },
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
            "pg.tgt.root": entry(
                "pg.tgt.root",
                "",
                "CURATED_ROOT",
                root_sources,
                "config/guidance/worker/root.policy.txt",
                "config/guidance/worker/root.source.txt",
            ),
            "pg.tgt.kavya": entry(
                "pg.tgt.kavya",
                "Kavya/",
                "CURATED_SUBPROJECT",
                kavya_sources,
                "config/guidance/worker/kavya.policy.txt",
                "config/guidance/worker/kavya.source.txt",
            ),
            "pg.tgt.slic": entry(
                "pg.tgt.slic",
                "SLIC Agent/",
                "CURATED_SUBPROJECT",
                slic_sources,
                "config/guidance/worker/slic.policy.txt",
                "config/guidance/worker/slic.source.txt",
            ),
            "pg.tgt.hatton": {
                "repository_id": "tgt",
                "logical_id": "pg.tgt.hatton",
                "audience": "worker",
                "scope_prefix": "HattonHills/",
                "classification": "CLASSIFIED_NOT_APPROVED",
                "approval_state": "NOT_APPROVED",
                "on_selection": "ProjectGuidanceNotApproved",
                "fallback_to_root_only": False,
                "sources": [
                    _source(repo, "HattonHills/CLAUDE.md"),
                    _source(repo, "HattonHills/AGENTS.md", alias_of="HattonHills/CLAUDE.md"),
                ],
                "source_artifact": None,
                "policy_artifact": None,
            },
            "pg.tgt.root.review": entry(
                "pg.tgt.root.review",
                "",
                "CURATED_ROOT_REVIEW",
                root_sources,
                "config/guidance/review/root.policy.txt",
                "config/guidance/review/root.source.txt",
            ),
            "pg.tgt.kavya.review": entry(
                "pg.tgt.kavya.review",
                "Kavya/",
                "CURATED_SUBPROJECT_REVIEW",
                kavya_sources,
                "config/guidance/review/kavya.policy.txt",
                "config/guidance/review/kavya.source.txt",
            ),
        },
        "failure_semantics": [
            {
                "condition": "repository identity mismatch",
                "typed_error": "ProjectGuidanceRepositoryMismatch",
                "behaviour": "fail closed",
            }
        ],
        "resume_fingerprint": {"spec": FINGERPRINT_SPEC, "note": "see module"},
    }
    data.update(overrides)
    return data


def _config_text(
    repo: Path, *, skills: bool, guidance: bool, policy_path: Path | None = None
) -> str:
    worker_policy = policy_path or (PROJECT_ROOT / "prompts" / "worker-policy.md")
    return f"""
[dispatcher]
state_dir = "./state"
default_timeout_seconds = 60
max_timeout_seconds = 120
default_max_turns = 40
default_max_resume_count = 4

[models]
sonnet = "sonnet"
opus = "opus"
fable = "fable"

[routing]
default_model = "sonnet"

[security]
max_dispatch_depth = 1
allowed_repository_roots = ["{repo}"]

[validation]
run_dispatcher_validation = true

[claude]
binary = "{SHIM}"
permission_mode = "auto"
worker_policy_path = "{worker_policy}"
fable_policy_path = "{PROJECT_ROOT}/prompts/fable-reviewer-policy.md"
empty_mcp_config_path = "{PROJECT_ROOT}/config/empty-mcp.json"
worker_result_schema_path = "{PROJECT_ROOT}/schemas/worker-result.schema.json"
fable_review_schema_path = "{PROJECT_ROOT}/schemas/fable-review.schema.json"
# Deliberately EMPTY. The two Gate 4.5 deny patterns therefore reach the skill
# engine only through runner.ALWAYS_DISALLOWED_TOOLS (Lane A R1); a stubbed
# deny list here would make the core skill refuse to project.
disallowed_tools = []

[skills]
enabled = {str(skills).lower()}
manifest_path = "./config/approved-skills.json"

[project_guidance]
enabled = {str(guidance).lower()}
manifest_path = "./config/approved-guidance.json"

[logging]
level = "WARNING"
"""


@pytest.fixture
def gate45(
    tmp_path: Path,
    target_repo: Path,
    identity,
    plugin_tree: dict,
    guidance_artifacts: dict,
):
    """An ephemeral project root with both manifests and both flags ON."""
    disp = guidance_artifacts["disp"]

    def build(
        *,
        skills: bool = True,
        guidance: bool = True,
        guidance_overrides=None,
        policy_path: Path | None = None,
    ):
        (disp / "config" / "approved-skills.json").write_text(
            json.dumps(_skills_manifest(plugin_tree), indent=1)
        )
        (disp / "config" / "approved-guidance.json").write_text(
            json.dumps(
                _guidance_manifest(
                    target_repo, disp, identity, **(guidance_overrides or {})
                ),
                indent=1,
            )
        )
        config_path = disp / "config" / "dispatcher.toml"
        config_path.write_text(
            _config_text(
                target_repo, skills=skills, guidance=guidance, policy_path=policy_path
            )
        )
        return Dispatcher(load_config(config_path))

    build.disp = disp  # type: ignore[attr-defined]
    build.repo = target_repo  # type: ignore[attr-defined]
    return build


@pytest.fixture
def payload(target_repo: Path) -> dict:
    return {
        "repository": {"root": str(target_repo), "base_ref": "HEAD"},
        "task": {
            "kind": "implementation",
            "objective": "Normalise the handover payload.",
            "acceptance_criteria": ["Handover is normalised."],
        },
        "scope": {"allowed_paths": ["Kavya/**"], "forbidden_paths": [".github/**"]},
        "routing": {"model": "auto", "complexity": "medium", "risk": "medium"},
        "execution": {"timeout_seconds": 60, "max_turns": 40, "max_resume_count": 4},
    }


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    log = tmp_path / "fake-claude.log.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")
    monkeypatch.setenv("FAKE_CLAUDE_WORKTREE_ROOT", str(tmp_path / "worktrees"))
    monkeypatch.delenv("SOL_WORKER", raising=False)
    monkeypatch.delenv("SOL_DISPATCH_DEPTH", raising=False)
    return log


def _invocations(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _system_prompt(record: dict) -> str:
    argv = record["argv"]
    return argv[argv.index("--append-system-prompt") + 1]


def _assert_ok(result: dict) -> dict:
    assert "error" not in result, result
    return result


# ---------------------------------------------------------------------------
# Ephemeral enablement — the property the live gate (§18) stands on
# ---------------------------------------------------------------------------


class TestEphemeralEnablement:
    async def test_projection_runs_end_to_end_from_a_temp_config_alone(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        assert dispatcher.config.skills.enabled is True
        assert dispatcher.config.project_guidance.enabled is True
        result = _assert_ok(await dispatcher.dispatch_claude_task(payload))
        prompt = _system_prompt(_invocations(fake_env)[0])
        assert "CORE-SKILL-SENTINEL" in prompt
        assert "ROOT-SOURCE-ARTIFACT-SENTINEL" in prompt
        assert "KAVYA-SOURCE-ARTIFACT-SENTINEL" in prompt
        assert result["state"] == "awaiting_sol_review"

    def test_production_config_stays_inert(self):
        """The shipped production config must not enable either projection."""
        production = load_config(PROJECT_ROOT / "config" / "dispatcher.toml")
        assert production.skills.enabled is False
        assert production.project_guidance.enabled is False
        assert production.security.allowed_repository_roots == ["/home/dev/full-voice-agent"]

    def test_example_config_stays_inert(self):
        # The example carries the /CONFIGURE/ME placeholder root on purpose, so
        # it cannot be loaded; its flags are read from the TOML directly.
        import tomllib

        example = tomllib.loads(
            (PROJECT_ROOT / "config" / "dispatcher.example.toml").read_text()
        )
        assert example["skills"]["enabled"] is False
        assert example["project_guidance"]["enabled"] is False

    def test_no_environment_variable_can_enable_projection(
        self, gate45, monkeypatch: pytest.MonkeyPatch
    ):
        # There is no escape hatch: every plausible one is set and the disabled
        # dispatcher still projects nothing.
        for name in (
            "SOL_SKILLS_ENABLED",
            "SOL_PROJECT_GUIDANCE_ENABLED",
            "SKILLS_ENABLED",
            "PROJECT_GUIDANCE_ENABLED",
            "SOL_DISPATCHER_SKILLS",
        ):
            monkeypatch.setenv(name, "1")
        dispatcher = gate45(skills=False, guidance=False)
        assert dispatcher.context.skill_engine is None
        assert dispatcher.context.guidance_engine is None


# ---------------------------------------------------------------------------
# Flags off — byte-identical to the pre-Gate-4.5 behaviour
# ---------------------------------------------------------------------------


class TestFlagsDisabled:
    async def test_disabled_dispatch_sends_exactly_the_policy_file(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45(skills=False, guidance=False)
        _assert_ok(await dispatcher.dispatch_claude_task(payload))
        prompt = _system_prompt(_invocations(fake_env)[0])
        assert prompt == (PROJECT_ROOT / "prompts" / "worker-policy.md").read_text()
        assert ENVELOPE_PRECEDENCE_PREAMBLE not in prompt

    async def test_disabled_dispatch_records_no_context_evidence(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45(skills=False, guidance=False)
        result = _assert_ok(await dispatcher.dispatch_claude_task(payload))
        record = dispatcher.store.load(result["task_id"])
        assert record.skill_policy is None
        assert record.project_guidance is None
        # The anchor is still written: "nothing was projected" is a fact worth
        # persisting, and a later run that *does* project is visibly different.
        assert record.context_fingerprint is not None
        runs = dispatcher.store.load_runs(result["task_id"])
        assert runs[0].metadata.skill_policy_fingerprint is None
        assert runs[0].metadata.project_guidance_fingerprint is None

    async def test_disabled_dispatch_reads_no_manifest(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45(skills=False, guidance=False)
        # Deleting both manifests proves the disabled path never touches them.
        (gate45.disp / "config" / "approved-skills.json").unlink()
        (gate45.disp / "config" / "approved-guidance.json").unlink()
        _assert_ok(await dispatcher.dispatch_claude_task(payload))

    async def test_disabled_review_sends_exactly_the_reviewer_policy(
        self, gate45, payload, fake_env, monkeypatch: pytest.MonkeyPatch
    ):
        dispatcher = gate45(skills=False, guidance=False)
        result = _assert_ok(await dispatcher.dispatch_claude_task(payload))
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
        _assert_ok(await dispatcher.review_task_with_fable(result["task_id"]))
        prompt = _system_prompt(_invocations(fake_env)[-1])
        assert prompt == (PROJECT_ROOT / "prompts" / "fable-reviewer-policy.md").read_text()


# ---------------------------------------------------------------------------
# ADDENDUM §14 — the composed worker context on the real dispatch path
# ---------------------------------------------------------------------------


class TestDispatchComposition:
    async def test_sections_arrive_in_the_addendum_14_order(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        _assert_ok(await dispatcher.dispatch_claude_task(payload))
        prompt = _system_prompt(_invocations(fake_env)[0])
        offsets = [
            prompt.index("orchestration law"),  # worker-policy.md, §1 heading text
            prompt.index("ENVELOPE PRECEDENCE"),
            prompt.index("CORE-SKILL-SENTINEL"),
            prompt.index("CONTEXTUAL-SKILL-SENTINEL"),
            prompt.index("ROOT-POLICY-ARTIFACT-SENTINEL"),
            prompt.index("ROOT-SOURCE-ARTIFACT-SENTINEL"),
            prompt.index("KAVYA-POLICY-ARTIFACT-SENTINEL"),
            prompt.index("KAVYA-SOURCE-ARTIFACT-SENTINEL"),
            prompt.index("GATED-OFF-ARTIFACT-SENTINEL"),
        ]
        assert offsets == sorted(offsets)

    async def test_only_the_intersecting_scope_is_projected(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        _assert_ok(await dispatcher.dispatch_claude_task(payload))
        prompt = _system_prompt(_invocations(fake_env)[0])
        assert "KAVYA-SOURCE-ARTIFACT-SENTINEL" in prompt
        assert "SLIC-SOURCE-ARTIFACT-SENTINEL" not in prompt
        assert "HATTON-SOURCE-SENTINEL" not in prompt

    async def test_raw_instruction_sources_are_never_projected_verbatim(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        _assert_ok(await dispatcher.dispatch_claude_task(payload))
        prompt = _system_prompt(_invocations(fake_env)[0])
        # Only the curated artifacts reach the worker; the sources are hashed.
        assert "ROOT-AGENTS-SENTINEL" not in prompt
        assert "ROOT-CLAUDE-SENTINEL" not in prompt
        assert "KAVYA-SOURCE-SENTINEL" not in prompt
        assert "SHADOW-WORKTREE-SENTINEL" not in prompt
        assert "NESTED-FOREIGN-SENTINEL" not in prompt

    async def test_the_worker_still_receives_safe_mode_and_the_core_deny_set(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        _assert_ok(await dispatcher.dispatch_claude_task(payload))
        argv = _invocations(fake_env)[0]["argv"]
        assert "--safe-mode" in argv
        assert "Bash(gh:*)" in argv
        assert "Bash(git bisect:*)" in argv
        assert "Skill" not in argv

    async def test_required_deny_pattern_coupling_is_preserved(
        self, gate45, payload, fake_env
    ):
        """Lane A R1, proven non-vacuously.

        ``[claude].disallowed_tools`` is empty in this config, so the core
        skill's ``requires_deny_patterns`` is satisfied only by the runner's
        non-configurable set. Building the engine with the configured half alone
        must refuse the same skill.
        """
        from sol_claude_dispatcher.skills import SkillProjectionEngine

        dispatcher = gate45()
        assert dispatcher.config.claude.disallowed_tools == []
        stubbed = SkillProjectionEngine.from_config(dispatcher.config)
        with pytest.raises(SkillPolicyViolation) as exc:
            stubbed.project(["plug.core-one"])
        assert exc.value.details["missing_deny_patterns"] == ["Bash(gh:*)"]
        # And the wired engine, built with the effective list, projects it.
        assert "CORE-SKILL-SENTINEL" in dispatcher.context.skill_engine.project(
            ["plug.core-one"]
        ).text


# ---------------------------------------------------------------------------
# ADDENDUM §16 — the dispatch anchor
# ---------------------------------------------------------------------------


class TestDispatchAnchor:
    async def test_anchor_records_both_policies_and_the_combined_fingerprint(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        result = _assert_ok(await dispatcher.dispatch_claude_task(payload))
        record = dispatcher.store.load(result["task_id"])

        assert record.skill_policy is not None
        assert record.skill_policy.skill_ids == ["plug.core-one", "plug.contextual-one"]
        assert record.skill_policy.manifest_version == "gate45.f.1"

        assert record.project_guidance is not None
        assert record.project_guidance.logical_ids == ["pg.tgt.root", "pg.tgt.kavya"]
        assert record.project_guidance.audience == "worker"
        assert record.project_guidance.graph_variant == "GATED_OFF"

        assert record.context_fingerprint is not None
        assert len(record.context_fingerprint) == 64

        run = dispatcher.store.load_runs(result["task_id"])[0]
        assert run.metadata.skill_policy_fingerprint == record.skill_policy.fingerprint
        assert (
            run.metadata.project_guidance_fingerprint == record.project_guidance.fingerprint
        )
        assert run.metadata.context_fingerprint == record.context_fingerprint

    async def test_anchor_is_stable_across_two_identical_dispatches(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        first = _assert_ok(await dispatcher.dispatch_claude_task(payload))
        second = _assert_ok(await dispatcher.dispatch_claude_task(payload))
        a = dispatcher.store.load(first["task_id"])
        b = dispatcher.store.load(second["task_id"])
        # The guidance fingerprint binds the envelope id, so the *combined*
        # value differs per task while both engine profiles match exactly.
        assert a.skill_policy.fingerprint == b.skill_policy.fingerprint
        assert a.project_guidance.logical_ids == b.project_guidance.logical_ids
        assert a.context_fingerprint != b.context_fingerprint

    async def test_anchor_refuses_to_be_rewritten(self, gate45, payload, fake_env):
        """The write-once guard, exercised directly.

        Today no code path calls ``_anchor_dispatch_context`` twice — dispatch
        calls it once and resume never calls it at all — so the structural
        property is proven by ``TestResume`` instead. This test makes the guard
        itself load-bearing: a future edit that re-anchors on resume (the
        obvious "keep the record fresh" mistake) would erase the value drift is
        measured against, and must be stopped here rather than reviewed for.
        """
        from sol_claude_dispatcher.models import RunKind
        from sol_claude_dispatcher.runner import worker_policy_text

        dispatcher = gate45()
        result = _assert_ok(await dispatcher.dispatch_claude_task(payload))
        task_id = result["task_id"]
        original = dispatcher.store.load(task_id)
        assert original.context_fingerprint is not None

        envelope = dispatcher.store.load_envelope(task_id)
        identity = dispatcher.context.repository_identity(gate45.repo)
        resume_context = dispatcher.context.for_worker(
            envelope,
            run_kind=RunKind.RESUME,
            policy_text=worker_policy_text(dispatcher.config),
            task_prompt="resume",
            identity=identity,
        )
        # A genuinely different context: the resume profile adds a skill.
        assert resume_context.fingerprint != original.context_fingerprint
        assert resume_context.skill_record.skill_ids != original.skill_policy.skill_ids

        dispatcher._anchor_dispatch_context(task_id, resume_context)

        after = dispatcher.store.load(task_id)
        assert after.context_fingerprint == original.context_fingerprint
        assert after.skill_policy.skill_ids == original.skill_policy.skill_ids
        assert after.project_guidance.fingerprint == original.project_guidance.fingerprint

    async def test_anchor_is_written_before_the_worker_runs(
        self, gate45, payload, fake_env, monkeypatch: pytest.MonkeyPatch
    ):
        dispatcher = gate45()
        seen: dict = {}

        import sol_claude_dispatcher.server as server_mod

        real = server_mod.run_worker

        async def spy(invocation):
            # The anchor must already be on disk by the time the child starts.
            for task_dir in (dispatcher.store.root).iterdir():
                state = json.loads((task_dir / "state.json").read_text())
                seen["fingerprint"] = state.get("context_fingerprint")
            return await real(invocation)

        monkeypatch.setattr(server_mod, "run_worker", spy)
        _assert_ok(await dispatcher.dispatch_claude_task(payload))
        assert seen["fingerprint"] is not None


# ---------------------------------------------------------------------------
# ADDENDUM §16 — resume
# ---------------------------------------------------------------------------


class TestResume:
    async def _dispatch(self, dispatcher, payload):
        return _assert_ok(await dispatcher.dispatch_claude_task(payload))["task_id"]

    async def test_resume_adds_the_resume_skill_and_that_is_not_drift(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        task_id = await self._dispatch(dispatcher, payload)
        anchor = dispatcher.store.load(task_id)

        _assert_ok(await dispatcher.resume_claude_task(task_id, "keep going"))

        prompt = _system_prompt(_invocations(fake_env)[-1])
        assert "RESUME-SKILL-SENTINEL" in prompt
        assert "CORE-SKILL-SENTINEL" in prompt

        after = dispatcher.store.load(task_id)
        # The dispatch anchor did not move.
        assert after.skill_policy.skill_ids == anchor.skill_policy.skill_ids
        assert after.skill_policy.fingerprint == anchor.skill_policy.fingerprint
        assert after.context_fingerprint == anchor.context_fingerprint
        # The per-run values did.
        runs = dispatcher.store.load_runs(task_id)
        assert runs[1].metadata.skill_policy_fingerprint != (
            runs[0].metadata.skill_policy_fingerprint
        )
        assert runs[1].metadata.context_fingerprint != runs[0].metadata.context_fingerprint
        # Guidance selection is unchanged by a resume, so its fingerprint is not.
        assert runs[1].metadata.project_guidance_fingerprint == (
            runs[0].metadata.project_guidance_fingerprint
        )

    async def test_resume_fails_closed_on_a_changed_instruction_source(
        self, gate45, payload, fake_env
    ):
        """A pinned source that is not half of an alias pair -> SourceChanged.

        Root ``AGENTS.md`` is one of two *independent* root sources
        (``UNION_OF_INDEPENDENT_SOURCES``), so editing it is a plain hash
        mismatch and nothing more precise is available.
        """
        dispatcher = gate45()
        task_id = await self._dispatch(dispatcher, payload)
        before = len(_invocations(fake_env))

        (gate45.repo / "AGENTS.md").write_text(
            ROOT_AGENTS_TEXT + "someone edited the source after dispatch\n"
        )

        result = await dispatcher.resume_claude_task(task_id, "keep going")
        assert result["error"] == ProjectGuidanceSourceChanged.__name__
        # No worker was launched under the changed guidance.
        assert len(_invocations(fake_env)) == before
        assert dispatcher.store.load(task_id).last_error["error"] == (
            ProjectGuidanceSourceChanged.__name__
        )

    async def test_diverged_alias_pair_reports_drift_not_source_changed(
        self, gate45, payload, fake_env
    ):
        """Sol ruling (2026-08-20): the more precise error wins, by design.

        ``Kavya/CLAUDE.md`` and ``Kavya/AGENTS.md`` are approved as byte-
        identical aliases. Editing one is *both* a hash mismatch and an alias
        divergence; ``ProjectGuidanceDrift`` fires first because "these approved
        aliases no longer agree" is the operationally useful statement. Both are
        fail-closed. This test pins the intended ordering so a future reader
        cannot "fix" the code to match older prose.
        """
        dispatcher = gate45()
        task_id = await self._dispatch(dispatcher, payload)
        before = len(_invocations(fake_env))

        (gate45.repo / "Kavya" / "CLAUDE.md").write_text(
            KAVYA_TEXT + "a hand edit to one half of a generated mirror\n"
        )

        result = await dispatcher.resume_claude_task(task_id, "keep going")
        assert result["error"] == "ProjectGuidanceDrift"
        assert len(_invocations(fake_env)) == before

    async def test_resume_fails_closed_on_a_changed_curated_artifact(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        task_id = await self._dispatch(dispatcher, payload)
        before = len(_invocations(fake_env))
        (gate45.disp / "config/guidance/worker/kavya.source.txt").write_text(
            KAVYA_SOURCE_ARTIFACT + "edited\n"
        )
        result = await dispatcher.resume_claude_task(task_id, "keep going")
        assert result["error"] == "ProjectGuidanceProjectionChanged"
        assert len(_invocations(fake_env)) == before

    async def test_resume_fails_closed_on_a_changed_skill_hash(
        self, gate45, payload, fake_env, plugin_tree
    ):
        dispatcher = gate45()
        task_id = await self._dispatch(dispatcher, payload)
        before = len(_invocations(fake_env))
        plugin_tree["core"].write_text(
            plugin_tree["core"].read_text() + "\nan unreviewed edit\n"
        )
        result = await dispatcher.resume_claude_task(task_id, "keep going")
        assert result["error"] == ApprovedSkillChanged.__name__
        assert len(_invocations(fake_env)) == before

    async def test_resume_fails_closed_when_skill_projection_is_switched_off(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        task_id = await self._dispatch(dispatcher, payload)
        switched_off = gate45(skills=False, guidance=True)
        result = await switched_off.resume_claude_task(task_id, "keep going")
        assert result["error"] == ApprovedSkillChanged.__name__
        assert result["details"]["reason"] == "skills_disabled_after_dispatch"

    async def test_resume_fails_closed_when_guidance_is_switched_off(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        task_id = await self._dispatch(dispatcher, payload)
        switched_off = gate45(skills=True, guidance=False)
        result = await switched_off.resume_claude_task(task_id, "keep going")
        assert result["error"] == ProjectGuidanceResumeDrift.__name__
        assert result["details"]["reason"] == (
            "project_guidance_disabled_after_dispatch"
        )

    async def test_a_clean_resume_keeps_the_same_guidance_text(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        task_id = await self._dispatch(dispatcher, payload)
        dispatch_prompt = _system_prompt(_invocations(fake_env)[0])
        _assert_ok(await dispatcher.resume_claude_task(task_id, "keep going"))
        resume_prompt = _system_prompt(_invocations(fake_env)[-1])
        for sentinel in (
            "ROOT-POLICY-ARTIFACT-SENTINEL",
            "ROOT-SOURCE-ARTIFACT-SENTINEL",
            "KAVYA-SOURCE-ARTIFACT-SENTINEL",
        ):
            assert sentinel in dispatch_prompt
            assert sentinel in resume_prompt


# ---------------------------------------------------------------------------
# RULINGS §7 — unapproved scope fails closed, never degrades to root-only
# ---------------------------------------------------------------------------


class TestUnapprovedScope:
    async def test_dispatch_into_an_unapproved_scope_fails_closed(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        payload["scope"]["allowed_paths"] = ["HattonHills/**"]
        result = await dispatcher.dispatch_claude_task(payload)
        assert result["error"] == ProjectGuidanceNotApproved.__name__
        # No worker ran, and there is no root-only fallback anywhere in the run.
        assert _invocations(fake_env) == []
        assert "NO fallback to root-only guidance" in (
            result["details"]["operator_text"]
        )

    async def test_the_refused_task_lands_in_failed_with_last_error(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        payload["scope"]["allowed_paths"] = ["HattonHills/**"]
        result = await dispatcher.dispatch_claude_task(payload)
        task_id = result["details"].get("task_id")
        # The refusal happens after the envelope is persisted, so the task is
        # inspectable; whichever id it got, exactly one task must be FAILED.
        states = [
            json.loads((d / "state.json").read_text())
            for d in dispatcher.store.root.iterdir()
        ]
        assert [s["state"] for s in states] == ["failed"]
        assert states[0]["last_error"]["error"] == ProjectGuidanceNotApproved.__name__
        assert task_id is None or task_id == states[0]["task_id"]

    async def test_an_unreviewed_instruction_file_blocks_the_dispatch(
        self, gate45, payload, fake_env
    ):
        dispatcher = gate45()
        _write(gate45.repo / "Kavya" / "sub" / "CLAUDE.md", "brand new, unreviewed\n")
        result = await dispatcher.dispatch_claude_task(payload)
        assert result["error"] == UnapprovedProjectGuidanceFile.__name__
        assert "Kavya/sub/CLAUDE.md" in result["details"]["unreviewed"]
        assert _invocations(fake_env) == []

    async def test_a_shadow_worktree_copy_is_not_reported_and_not_projected(
        self, gate45, payload, fake_env
    ):
        # The stale .claude/worktrees copy exists in the fixture repo and is a
        # *hazard*, not an unreviewed new file: the dispatch succeeds.
        dispatcher = gate45()
        assert (
            gate45.repo / ".claude/worktrees/agent-deadbeef/Kavya/CLAUDE.md"
        ).is_file()
        _assert_ok(await dispatcher.dispatch_claude_task(payload))
        assert "SHADOW-WORKTREE-SENTINEL" not in _system_prompt(_invocations(fake_env)[0])


# ---------------------------------------------------------------------------
# ADDENDUM §15 — Fable
# ---------------------------------------------------------------------------


class TestFableReview:
    async def test_fable_gets_review_guidance_and_zero_skills(
        self, gate45, payload, fake_env, monkeypatch: pytest.MonkeyPatch
    ):
        dispatcher = gate45()
        result = _assert_ok(await dispatcher.dispatch_claude_task(payload))
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
        _assert_ok(await dispatcher.review_task_with_fable(result["task_id"]))
        prompt = _system_prompt(_invocations(fake_env)[-1])

        assert "ROOT-REVIEW-SOURCE-ARTIFACT-SENTINEL" in prompt
        assert "KAVYA-REVIEW-SOURCE-ARTIFACT-SENTINEL" in prompt
        # Zero skills, and none of the worker's own guidance artifacts.
        assert "CORE-SKILL-SENTINEL" not in prompt
        assert "CONTEXTUAL-SKILL-SENTINEL" not in prompt
        assert "RESUME-SKILL-SENTINEL" not in prompt
        assert "ROOT-SOURCE-ARTIFACT-SENTINEL" not in prompt
        assert "KAVYA-SOURCE-ARTIFACT-SENTINEL" not in prompt
        # A review projection carries no graph-refresh clause.
        assert "GATED-OFF-ARTIFACT-SENTINEL" not in prompt

    async def test_fable_run_records_guidance_but_no_skill_fingerprint(
        self, gate45, payload, fake_env, monkeypatch: pytest.MonkeyPatch
    ):
        dispatcher = gate45()
        result = _assert_ok(await dispatcher.dispatch_claude_task(payload))
        monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
        _assert_ok(await dispatcher.review_task_with_fable(result["task_id"]))
        runs = dispatcher.store.load_runs(result["task_id"])
        review = runs[-1]
        assert review.metadata.role.value == "reviewer"
        assert review.metadata.skill_policy_fingerprint is None
        assert review.metadata.project_guidance_fingerprint is not None
        assert review.metadata.context_fingerprint is not None
        # The dispatch anchor is untouched by a review.
        record = dispatcher.store.load(result["task_id"])
        assert record.project_guidance.audience == "worker"

    async def test_scoped_review_without_an_approved_review_entry_fails_closed(
        self, gate45, payload, fake_env
    ):
        """RULINGS §7 as re-confirmed by Sol: no root-only review fallback.

        ``SLIC Agent/`` has an approved *worker* projection and
        ``review_entry: null``. Fable must refuse rather than review a SLIC task
        with root-only context.
        """
        dispatcher = gate45()
        payload["scope"]["allowed_paths"] = ["SLIC Agent/**"]
        result = _assert_ok(await dispatcher.dispatch_claude_task(payload))
        review = await dispatcher.review_task_with_fable(result["task_id"])
        assert review["error"] == ProjectGuidanceNotApproved.__name__
        assert review["details"]["audience"] == "fable_review"
        # And the worker dispatch itself was fine: SLIC has a worker projection.
        assert "SLIC-SOURCE-ARTIFACT-SENTINEL" in _system_prompt(
            _invocations(fake_env)[0]
        )


# ---------------------------------------------------------------------------
# RULINGS §2 — provenance domains stay separate on the wired path
# ---------------------------------------------------------------------------


class TestProvenanceSeparationWired:
    async def test_scanned_and_exempt_artifacts_are_disjoint_for_a_real_dispatch(
        self, gate45, payload, fake_env, identity
    ):
        dispatcher = gate45()
        _assert_ok(await dispatcher.dispatch_claude_task(payload))
        engine = dispatcher.context.guidance_engine
        projection = engine.project(
            ["Kavya/**"],
            repository=identity,
            task_envelope_id="probe",
        )
        assert projection.scanned_artifacts
        assert projection.exempt_artifacts
        assert set(projection.scanned_artifacts) & set(projection.exempt_artifacts) == set()

    async def test_the_dispatcher_authored_preamble_is_never_inside_a_source_block(
        self, gate45, payload, fake_env, identity
    ):
        dispatcher = gate45()
        from sol_claude_dispatcher.models import RunKind
        from sol_claude_dispatcher.runner import worker_policy_text

        envelope_dict = _assert_ok(await dispatcher.dispatch_claude_task(payload))
        envelope = dispatcher.store.load_envelope(envelope_dict["task_id"])
        context = dispatcher.context.for_worker(
            envelope,
            run_kind=RunKind.DISPATCH,
            policy_text=worker_policy_text(dispatcher.config),
            task_prompt="probe",
            identity=identity,
        )
        for block in context.blocks:
            if block.section in ("CORE_APPROVED_SKILLS", "CONTEXTUAL_SKILLS"):
                assert "ENVELOPE PRECEDENCE" not in block.text
                assert "ROOT-POLICY-ARTIFACT-SENTINEL" not in block.text


# ---------------------------------------------------------------------------
# BLOCKER B1 — the composed context must fit in one argv element
# ---------------------------------------------------------------------------


class TestTransportCeiling:
    """The composed ``--append-system-prompt`` is ONE argv element (§14).

    Linux caps a single argv element at 131,071 bytes (measured live, Lane G
    claim ``I-0``); the dispatcher's V1 ceiling is 122,880 bytes of UTF-8. When
    the composed context does not fit, the task is REFUSED — no Skill is
    dropped, no guidance scope is dropped, nothing is truncated, and no worker
    process is started.

    The oversized component here is the dispatcher's own worker policy file,
    which is operator-configurable and covered by neither projection cap. That
    is exactly why the check measures the FINAL composed payload rather than
    trusting a sum of per-component caps.
    """

    def _oversized_policy(self, tmp_path: Path) -> Path:
        policy = tmp_path / "oversized-worker-policy.md"
        body = "This throwaway policy line exists only to exceed the cap.\n"
        policy.write_text("# Oversized throwaway worker policy\n" + body * 2400)
        assert len(policy.read_bytes()) > 122_880
        return policy

    async def test_oversized_context_is_refused_with_a_typed_error(
        self, gate45, payload, fake_env, tmp_path: Path
    ):
        dispatcher = gate45(policy_path=self._oversized_policy(tmp_path))
        result = await dispatcher.dispatch_claude_task(payload)

        assert result["error"] == "ContextTooLarge"
        details = result["details"]
        assert details["maximum_bytes"] == 122_880
        assert details["actual_bytes"] > details["maximum_bytes"]
        assert details["excess_bytes"] == (
            details["actual_bytes"] - details["maximum_bytes"]
        )
        assert details["source"] == "preflight"
        assert details["role"] == "implementer"

    async def test_no_worker_process_is_started(
        self, gate45, payload, fake_env, tmp_path: Path
    ):
        dispatcher = gate45(policy_path=self._oversized_policy(tmp_path))
        await dispatcher.dispatch_claude_task(payload)
        assert _invocations(fake_env) == []

    async def test_the_full_selection_is_reported_not_narrowed(
        self, gate45, payload, fake_env, tmp_path: Path
    ):
        """Refuse and hand back the selection, so Sol can narrow the task."""
        dispatcher = gate45(policy_path=self._oversized_policy(tmp_path))
        result = await dispatcher.dispatch_claude_task(payload)
        details = result["details"]

        # Every selected skill and every selected guidance scope is named.
        assert details["skill_count"] == len(details["skill_ids"])
        assert details["skill_count"] >= 1
        assert details["guidance_scope_count"] == len(details["guidance_scope_ids"])
        assert details["guidance_scope_count"] >= 1
        assert "pg.root" in details["guidance_scope_ids"] or any(
            sid.startswith("pg.") for sid in details["guidance_scope_ids"]
        )

    async def test_the_refusal_quotes_no_projected_content(
        self, gate45, payload, fake_env, tmp_path: Path
    ):
        dispatcher = gate45(policy_path=self._oversized_policy(tmp_path))
        result = await dispatcher.dispatch_claude_task(payload)
        rendered = json.dumps(result)
        for sentinel in (
            "CORE-SKILL-SENTINEL",
            "ROOT-SOURCE-ARTIFACT-SENTINEL",
            "KAVYA-SOURCE-ARTIFACT-SENTINEL",
            "ROOT-POLICY-ARTIFACT-SENTINEL",
        ):
            assert sentinel not in rendered

    async def test_the_task_fails_closed_with_the_error_recorded(
        self, gate45, payload, fake_env, tmp_path: Path
    ):
        dispatcher = gate45(policy_path=self._oversized_policy(tmp_path))
        result = await dispatcher.dispatch_claude_task(payload)
        assert "task_id" in result["details"]
        record = dispatcher.store.load(result["details"]["task_id"])
        assert record.state.value == "failed"
        assert record.last_error["error"] == "ContextTooLarge"
