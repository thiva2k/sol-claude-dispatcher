"""Gate 7 Subsystem A lifecycle profile and feasibility tests."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import (
    ApprovedSkillChanged,
    ConfigurationError,
    ContextTooLarge,
    SkillPolicyViolation,
)
from sol_claude_dispatcher.lifecycle import (
    LifecyclePhase,
    LifecycleProfileEngine,
    PhaseComposition,
    compose_append_system_prompt,
    evaluate_lifecycle,
    preflight_lifecycle,
    reachable_lifecycle_phases,
    select_runtime_phase,
)
from sol_claude_dispatcher.models import (
    Complexity,
    RiskLevel,
    RunKind,
    TaskKind,
    WorkerRole,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config" / "approved-lifecycle-profiles.json"
NOW = datetime(2026, 8, 29, tzinfo=timezone.utc)


def _engine(root: Path = ROOT) -> LifecycleProfileEngine:
    return LifecycleProfileEngine.from_file(
        root / "config" / "approved-lifecycle-profiles.json",
        source_root=root,
        effective_deny_patterns=(),
    )


def _contexts(*, resume_text: str = "resume-policy") -> dict[LifecyclePhase, PhaseComposition]:
    return {
        LifecyclePhase.DISPATCH_IMPLEMENTATION: PhaseComposition(
            dispatcher_authored_text="dispatch-policy",
            guidance_text="project-guidance",
            guidance_cap_bytes=42_000,
        ),
        LifecyclePhase.CORRECTION_RESUME: PhaseComposition(
            dispatcher_authored_text=resume_text,
            guidance_text="project-guidance",
            guidance_cap_bytes=42_000,
        ),
        LifecyclePhase.VALIDATION_ONLY_RESUME: PhaseComposition(
            dispatcher_authored_text="validation-policy",
            guidance_text="project-guidance",
            guidance_cap_bytes=42_000,
        ),
        LifecyclePhase.FABLE_REVIEW: PhaseComposition(
            dispatcher_authored_text="review-policy",
            guidance_text="review-guidance",
            guidance_cap_bytes=42_000,
            review_context_available=True,
        ),
    }


def _evaluate(
    engine: LifecycleProfileEngine,
    *,
    max_resume_count: int = 1,
    contexts: dict[LifecyclePhase, PhaseComposition] | None = None,
    ceiling: int = 122_880,
):
    return evaluate_lifecycle(
        engine,
        task_id="task-1",
        envelope_digest="a" * 64,
        task_kind=TaskKind.IMPLEMENTATION,
        complexity=Complexity.MEDIUM,
        risk=RiskLevel.MEDIUM,
        max_resume_count=max_resume_count,
        phase_compositions=contexts or _contexts(),
        transport_ceiling_bytes=ceiling,
        computed_at=NOW,
    )


def _copy_profile_tree(tmp_path: Path) -> Path:
    root = tmp_path / "install"
    for relative in (
        "AGENTS.md",
        "prompts/worker-policy.md",
        "docs/GATE7-DESIGN.md",
        "config/approved-lifecycle-profiles.json",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    shutil.copytree(ROOT / "config" / "lifecycle", root / "config" / "lifecycle")
    return root


def _rewrite_manifest_hash(root: Path, artifact_id: str) -> None:
    manifest_path = root / "config" / "approved-lifecycle-profiles.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact = next(a for a in document["artifacts"] if a["artifact_id"] == artifact_id)
    raw = (root / artifact["path"]).read_bytes()
    artifact["projection_sha256"] = hashlib.sha256(raw).hexdigest()
    artifact["projection_bytes"] = len(raw)
    manifest_path.write_text(
        json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def test_shipped_manifest_is_exhaustive_and_hash_verified() -> None:
    engine = _engine()
    assert set(engine.manifest.profiles) == set(LifecyclePhase)
    for phase in LifecyclePhase:
        projection = engine.project(
            phase,
            task_kind=TaskKind.IMPLEMENTATION,
            complexity=Complexity.MEDIUM,
            risk=RiskLevel.MEDIUM,
        )
        assert projection.approved_hashes_verified
        assert projection.projected_bytes == len(projection.text.encode("utf-8"))


def test_source_hash_drift_invalidates_projection(tmp_path: Path) -> None:
    root = _copy_profile_tree(tmp_path)
    engine = _engine(root)
    source = root / "prompts" / "worker-policy.md"
    source.write_bytes(source.read_bytes() + b"\nsource drift\n")

    with pytest.raises(ApprovedSkillChanged, match="source"):
        engine.project(
            LifecyclePhase.DISPATCH_IMPLEMENTATION,
            task_kind=TaskKind.IMPLEMENTATION,
            complexity=Complexity.LOW,
            risk=RiskLevel.LOW,
        )


def test_projection_hash_drift_invalidates_projection(tmp_path: Path) -> None:
    root = _copy_profile_tree(tmp_path)
    engine = _engine(root)
    artifact = root / "config" / "lifecycle" / "v1" / "implementation.md"
    artifact.write_bytes(artifact.read_bytes() + b"\nprojection drift\n")

    with pytest.raises(ApprovedSkillChanged, match="projection"):
        engine.project(
            LifecyclePhase.DISPATCH_IMPLEMENTATION,
            task_kind=TaskKind.IMPLEMENTATION,
            complexity=Complexity.LOW,
            risk=RiskLevel.LOW,
        )


def test_hash_valid_but_dynamic_projection_is_still_refused(tmp_path: Path) -> None:
    root = _copy_profile_tree(tmp_path)
    artifact = root / "config" / "lifecycle" / "v1" / "implementation.md"
    artifact.write_text("Unsafe dynamic construct: !`whoami`\n", encoding="utf-8")
    _rewrite_manifest_hash(root, "implementation")
    engine = _engine(root)

    with pytest.raises(SkillPolicyViolation, match="inert"):
        engine.project(
            LifecyclePhase.DISPATCH_IMPLEMENTATION,
            task_kind=TaskKind.IMPLEMENTATION,
            complexity=Complexity.LOW,
            risk=RiskLevel.LOW,
        )


def test_validation_profile_is_subset_of_correction_for_whole_matrix() -> None:
    engine = _engine()
    for kind in TaskKind:
        for complexity in Complexity:
            for risk in RiskLevel:
                validation = set(
                    engine.artifact_ids_for(
                        LifecyclePhase.VALIDATION_ONLY_RESUME,
                        task_kind=kind,
                        complexity=complexity,
                        risk=risk,
                    )
                )
                correction = set(
                    engine.artifact_ids_for(
                        LifecyclePhase.CORRECTION_RESUME,
                        task_kind=kind,
                        complexity=complexity,
                        risk=risk,
                    )
                )
                assert validation <= correction


def test_whole_profile_matrix_fits_with_guidance_at_configured_cap() -> None:
    """The fixture reserves the cap, not a conveniently tiny guidance file."""
    engine = _engine()
    guidance_at_cap = "G" * 42_000
    dispatcher_reserve = "D" * 8_192
    for kind in TaskKind:
        for complexity in Complexity:
            for risk in RiskLevel:
                for phase in LifecyclePhase:
                    projection = engine.project(
                        phase,
                        task_kind=kind,
                        complexity=complexity,
                        risk=risk,
                    )
                    composed = compose_append_system_prompt(
                        dispatcher_reserve, projection.text, guidance_at_cap
                    )
                    assert len(composed.encode("utf-8")) <= 122_880, (
                        kind,
                        complexity,
                        risk,
                        phase,
                    )


@pytest.mark.parametrize(
    ("run_kind", "role", "expected"),
    [
        (RunKind.DISPATCH, WorkerRole.IMPLEMENTER, LifecyclePhase.DISPATCH_IMPLEMENTATION),
        (RunKind.RESUME, WorkerRole.IMPLEMENTER, LifecyclePhase.CORRECTION_RESUME),
        (RunKind.REVIEW, WorkerRole.REVIEWER, LifecyclePhase.FABLE_REVIEW),
    ],
)
def test_validation_only_resume_is_never_selected_at_runtime(
    run_kind: RunKind, role: WorkerRole, expected: LifecyclePhase
) -> None:
    selected = select_runtime_phase(run_kind=run_kind, role=role)
    assert selected is expected
    assert selected is not LifecyclePhase.VALIDATION_ONLY_RESUME


def test_final_composed_utf8_bytes_are_measured_not_component_sum() -> None:
    engine = _engine()
    contexts = _contexts()
    contexts[LifecyclePhase.DISPATCH_IMPLEMENTATION] = PhaseComposition(
        dispatcher_authored_text="policy-λ",
        guidance_text="guidance-🧪",
        guidance_cap_bytes=42_000,
    )
    report = _evaluate(engine, contexts=contexts)
    phase = report.for_phase(LifecyclePhase.DISPATCH_IMPLEMENTATION)
    projection = engine.project(
        LifecyclePhase.DISPATCH_IMPLEMENTATION,
        task_kind=TaskKind.IMPLEMENTATION,
        complexity=Complexity.MEDIUM,
        risk=RiskLevel.MEDIUM,
    )
    final = compose_append_system_prompt("policy-λ", projection.text, "guidance-🧪")

    assert phase.composed_append_system_prompt_bytes == len(final.encode("utf-8"))
    assert phase.composed_append_system_prompt_bytes > (
        phase.dispatcher_authored_bytes + phase.projected_skill_bytes
    )


def test_oversized_future_resume_refuses_initial_dispatch() -> None:
    engine = _engine()
    contexts = _contexts(resume_text="R" * 3_000)
    dispatch_projection = engine.project(
        LifecyclePhase.DISPATCH_IMPLEMENTATION,
        task_kind=TaskKind.IMPLEMENTATION,
        complexity=Complexity.MEDIUM,
        risk=RiskLevel.MEDIUM,
    )
    dispatch_bytes = len(
        compose_append_system_prompt(
            "dispatch-policy", dispatch_projection.text, "project-guidance"
        ).encode("utf-8")
    )

    with pytest.raises(ContextTooLarge) as caught:
        preflight_lifecycle(
            engine,
            task_id="not-yet-created",
            envelope_digest="b" * 64,
            task_kind=TaskKind.IMPLEMENTATION,
            complexity=Complexity.MEDIUM,
            risk=RiskLevel.MEDIUM,
            max_resume_count=1,
            phase_compositions=contexts,
            transport_ceiling_bytes=dispatch_bytes + 1,
            computed_at=NOW,
        )

    assert caught.value.details["infeasible_phase"] == "CORRECTION_RESUME"
    assert caught.value.details["phases"]["DISPATCH_IMPLEMENTATION"] <= dispatch_bytes + 1


def test_zero_resume_limit_marks_both_resume_phases_unreachable() -> None:
    engine = _engine()
    contexts = _contexts()
    del contexts[LifecyclePhase.CORRECTION_RESUME]
    del contexts[LifecyclePhase.VALIDATION_ONLY_RESUME]
    report = _evaluate(engine, max_resume_count=0, contexts=contexts)

    assert report.unreachable_phases == (
        LifecyclePhase.CORRECTION_RESUME.value,
        LifecyclePhase.VALIDATION_ONLY_RESUME.value,
    )
    assert {phase.phase for phase in report.phases} == {
        LifecyclePhase.DISPATCH_IMPLEMENTATION,
        LifecyclePhase.FABLE_REVIEW,
    }


def test_feasibility_report_is_deterministic_for_explicit_time() -> None:
    engine = _engine()
    assert _evaluate(engine) == _evaluate(engine)


def test_missing_reachable_phase_composition_fails_closed() -> None:
    contexts = _contexts()
    del contexts[LifecyclePhase.FABLE_REVIEW]
    with pytest.raises(ConfigurationError, match="composition"):
        _evaluate(_engine(), contexts=contexts)


def test_reachable_phase_order_and_unreachable_order_are_fixed() -> None:
    reachable, unreachable = reachable_lifecycle_phases(max_resume_count=1)
    assert reachable == tuple(LifecyclePhase)
    assert unreachable == ()
    reachable, unreachable = reachable_lifecycle_phases(max_resume_count=0)
    assert reachable == (
        LifecyclePhase.DISPATCH_IMPLEMENTATION,
        LifecyclePhase.FABLE_REVIEW,
    )
    assert unreachable == (
        LifecyclePhase.CORRECTION_RESUME,
        LifecyclePhase.VALIDATION_ONLY_RESUME,
    )
