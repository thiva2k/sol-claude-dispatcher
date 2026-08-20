"""Gate 4.5 §14/§16 — final worker-context composition and the combined fingerprint.

Lane F (integration). These tests are about *composition*, not about either
projection engine: the engines are exercised exhaustively by
``tests/unit/test_skills.py`` and ``tests/unit/test_project_guidance.py``.
What is proven here is that the integration layer

* emits the six §14 sections in the §14 order and nothing else;
* never concatenates a DISPATCHER_AUTHORED block with a SOURCE_DERIVED block
  before classification has run (RULINGS §2);
* emits the dispatcher-authored envelope-precedence preamble immediately before
  the first projected block, and never when nothing is projected;
* gives Fable project guidance but zero skills (§15);
* is byte-identical to the pre-Gate-4.5 behaviour when both flags are off;
* produces one combined context fingerprint covering skill policy, the root
  guidance projection, every scoped guidance projection and envelope identity.

Every assertion below is against a LITERAL expected value. Emptying a constant
in ``worker_context.py`` turns these red rather than vacuously green.
"""

from __future__ import annotations

import hashlib

import pytest

from sol_claude_dispatcher.models import WorkerRole
from sol_claude_dispatcher.project_guidance import (
    DISPATCHER_AUTHORED,
    SOURCE_DERIVED,
    ProjectedGuidanceArtifact,
    ProjectedScope,
    ProjectGuidanceProjection,
    ProvenanceSeparationError,
    StrictContentScanner,
)
from sol_claude_dispatcher.skills import (
    ProjectedSkill,
    SkillProjection,
)
from sol_claude_dispatcher.worker_context import (
    CONTEXT_FINGERPRINT_VERSION,
    ENVELOPE_PRECEDENCE_PREAMBLE,
    SECTION_ORDER,
    ContextBlock,
    Provenance,
    WorkerContext,
    compose_worker_context,
    context_fingerprint,
)

POLICY_TEXT = "# Worker policy\n\nDispatcher-authored orchestration law.\n"
TASK_PROMPT = "# Implementation task\n\nDo the thing.\n"


# ---------------------------------------------------------------------------
# Synthetic projections. Frozen dataclasses, so no manifest is needed here.
# ---------------------------------------------------------------------------


def _skill(skill_id: str, body: str) -> ProjectedSkill:
    return ProjectedSkill(
        id=skill_id,
        display_name=skill_id,
        classification="SAFE_WORKER_PROCEDURE",
        tier="core",
        activation="always_on",
        resolved_path=f"/plugins/{skill_id}/SKILL.md",
        skill_md_sha256="a" * 64,
        body=body,
        supporting_files=(),
    )


def _skill_projection(*skills: ProjectedSkill, fingerprint: str = "1" * 64) -> SkillProjection:
    text = "\n\n".join(s.text for s in skills)
    return SkillProjection(
        manifest_schema_version="1.0",
        manifest_version="test.1",
        skill_ids=tuple(s.id for s in skills),
        skills=tuple(skills),
        text=text,
        projected_bytes=len(text.encode("utf-8")),
        approx_tokens=len(text) // 4,
        fingerprint=fingerprint,
    )


def _artifact(path: str, provenance: str, text: str) -> ProjectedGuidanceArtifact:
    return ProjectedGuidanceArtifact(
        logical_id=path,
        path=path,
        provenance_class=provenance,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        nbytes=len(text.encode()),
        text=text,
    )


def _scope(logical_id: str, prefix: str, policy_text: str, source_text: str) -> ProjectedScope:
    return ProjectedScope(
        logical_id=logical_id,
        scope_prefix=prefix,
        classification="CURATED_ROOT" if not prefix else "CURATED_SUBPROJECT",
        source_relationship="UNION_OF_INDEPENDENT_SOURCES",
        source_paths=(f"/target/{prefix}CLAUDE.md",),
        source_hashes=(hashlib.sha256(source_text.encode()).hexdigest(),),
        policy=_artifact(f"{logical_id}.policy.txt", DISPATCHER_AUTHORED, policy_text),
        source=_artifact(f"{logical_id}.source.txt", SOURCE_DERIVED, source_text),
    )


def _guidance_projection(
    *scopes: ProjectedScope,
    audience: str = "worker",
    graph_variant: str | None = "GATED_OFF",
    task_envelope_id: str = "task-1",
    approval_version: str = "v1",
) -> ProjectGuidanceProjection:
    artifacts: list[ProjectedGuidanceArtifact] = []
    for scope in scopes:
        artifacts.append(scope.policy)
        artifacts.append(scope.source)
    if graph_variant is not None:
        artifacts.append(
            _artifact("graph.clause.txt", DISPATCHER_AUTHORED, "GRAPH-CLAUSE\n")
        )
    text = "".join(a.text for a in artifacts)
    return ProjectGuidanceProjection(
        manifest_schema_version="1.0.0",
        approval_version=approval_version,
        audience=audience,
        repository_id="tgt",
        logical_ids=tuple(s.logical_id for s in scopes),
        scope_prefixes=tuple(s.scope_prefix for s in scopes if s.scope_prefix),
        scopes=tuple(scopes),
        artifacts=tuple(artifacts),
        graph_variant=graph_variant,
        text=text,
        projected_bytes=len(text.encode()),
        approx_tokens=len(text) // 4,
        fingerprint=hashlib.sha256(text.encode()).hexdigest(),
        task_envelope_id=task_envelope_id,
        scanned_artifacts=tuple(s.source.path for s in scopes),
        exempt_artifacts=tuple(s.policy.path for s in scopes),
    )


CORE_SKILL = _skill("plug.core-one", "CORE-SKILL-BODY-SENTINEL\n")
CONTEXTUAL_SKILL = _skill("plug.contextual-one", "CONTEXTUAL-SKILL-BODY-SENTINEL\n")
ROOT_SCOPE = _scope("pg.tgt.root", "", "ROOT-POLICY-SENTINEL\n", "ROOT-SOURCE-SENTINEL\n")
KAVYA_SCOPE = _scope(
    "pg.tgt.kavya", "Kavya/", "KAVYA-POLICY-SENTINEL\n", "KAVYA-SOURCE-SENTINEL\n"
)


def _compose(**overrides) -> WorkerContext:
    kwargs = dict(
        role=WorkerRole.IMPLEMENTER,
        task_envelope_id="task-1",
        policy_text=POLICY_TEXT,
        task_prompt=TASK_PROMPT,
        skill_projection=None,
        guidance_projection=None,
        core_skill_ids=("plug.core-one",),
    )
    kwargs.update(overrides)
    return compose_worker_context(**kwargs)


# ---------------------------------------------------------------------------
# ADDENDUM §14 — the composition order
# ---------------------------------------------------------------------------


class TestSectionOrder:
    def test_section_order_constant_is_the_addendum_14_order(self):
        # Literal, in order. §14: DISPATCHER SYSTEM POLICY + TASK ENVELOPE +
        # CORE APPROVED ENGINEERING SKILLS + DETERMINISTIC CONTEXTUAL SKILLS +
        # CURATED ROOT PROJECT GUIDANCE + CURATED IN-SCOPE SUBPROJECT GUIDANCE.
        # The preamble is the dispatcher-authored hinge required by Lane A R2
        # and the graph-refresh clause is the guidance engine's own trailer.
        assert SECTION_ORDER == (
            "DISPATCHER_SYSTEM_POLICY",
            "TASK_ENVELOPE",
            "ENVELOPE_PRECEDENCE_PREAMBLE",
            "CORE_APPROVED_SKILLS",
            "CONTEXTUAL_SKILLS",
            "CURATED_ROOT_GUIDANCE",
            "CURATED_IN_SCOPE_SUBPROJECT_GUIDANCE",
            "GRAPH_REFRESH_CLAUSE",
        )

    def test_full_context_emits_every_section_in_order(self):
        context = _compose(
            skill_projection=_skill_projection(CORE_SKILL, CONTEXTUAL_SKILL),
            guidance_projection=_guidance_projection(ROOT_SCOPE, KAVYA_SCOPE),
        )
        assert [b.section for b in context.blocks] == [
            "DISPATCHER_SYSTEM_POLICY",
            "TASK_ENVELOPE",
            "ENVELOPE_PRECEDENCE_PREAMBLE",
            "CORE_APPROVED_SKILLS",
            "CONTEXTUAL_SKILLS",
            "CURATED_ROOT_GUIDANCE",
            "CURATED_IN_SCOPE_SUBPROJECT_GUIDANCE",
            "GRAPH_REFRESH_CLAUSE",
        ]

    def test_emitted_sections_are_a_subsequence_of_the_canonical_order(self):
        context = _compose(
            skill_projection=_skill_projection(CORE_SKILL),
            guidance_projection=_guidance_projection(ROOT_SCOPE, graph_variant=None),
        )
        positions = [SECTION_ORDER.index(b.section) for b in context.blocks]
        assert positions == sorted(positions)
        assert "CONTEXTUAL_SKILLS" not in [b.section for b in context.blocks]
        assert "GRAPH_REFRESH_CLAUSE" not in [b.section for b in context.blocks]

    def test_system_prompt_orders_the_sentinels_exactly_as_section_order(self):
        context = _compose(
            skill_projection=_skill_projection(CORE_SKILL, CONTEXTUAL_SKILL),
            guidance_projection=_guidance_projection(ROOT_SCOPE, KAVYA_SCOPE),
        )
        text = context.append_system_prompt
        offsets = [
            text.index("Dispatcher-authored orchestration law."),
            text.index("ENVELOPE PRECEDENCE"),
            text.index("CORE-SKILL-BODY-SENTINEL"),
            text.index("CONTEXTUAL-SKILL-BODY-SENTINEL"),
            text.index("ROOT-POLICY-SENTINEL"),
            text.index("ROOT-SOURCE-SENTINEL"),
            text.index("KAVYA-POLICY-SENTINEL"),
            text.index("KAVYA-SOURCE-SENTINEL"),
            text.index("GRAPH-CLAUSE"),
        ]
        assert offsets == sorted(offsets)

    def test_task_envelope_travels_on_the_prompt_channel_not_the_system_prompt(self):
        context = _compose(
            skill_projection=_skill_projection(CORE_SKILL),
            guidance_projection=_guidance_projection(ROOT_SCOPE),
        )
        assert context.prompt == TASK_PROMPT
        assert TASK_PROMPT not in context.append_system_prompt
        envelope_block = next(b for b in context.blocks if b.section == "TASK_ENVELOPE")
        assert envelope_block.channel == "prompt"
        assert all(
            b.channel == "system" for b in context.blocks if b.section != "TASK_ENVELOPE"
        )


# ---------------------------------------------------------------------------
# Lane A R2 / RULINGS §2 — the preamble and provenance separation
# ---------------------------------------------------------------------------


class TestPreamble:
    def test_preamble_carries_the_load_bearing_clauses_verbatim(self):
        # Literal phrases: emptying the constant fails this test.
        for phrase in (
            "ENVELOPE PRECEDENCE",
            "DISPATCHER-AUTHORED POLICY",
            "REFERENCE MATERIAL",
            "the envelope wins",
            "A dangling reference is intentional.",
            "git bisect",
            "gh",
            "not authorisation",
            "cannot enlarge your tool authority",
        ):
            assert phrase in ENVELOPE_PRECEDENCE_PREAMBLE, phrase

    def test_preamble_immediately_precedes_the_first_projected_block(self):
        context = _compose(
            skill_projection=_skill_projection(CORE_SKILL),
            guidance_projection=_guidance_projection(ROOT_SCOPE),
        )
        sections = [b.section for b in context.blocks]
        assert sections[sections.index("ENVELOPE_PRECEDENCE_PREAMBLE") + 1] == (
            "CORE_APPROVED_SKILLS"
        )

    def test_preamble_precedes_guidance_when_only_guidance_is_projected(self):
        context = _compose(guidance_projection=_guidance_projection(ROOT_SCOPE))
        sections = [b.section for b in context.blocks]
        assert sections[sections.index("ENVELOPE_PRECEDENCE_PREAMBLE") + 1] == (
            "CURATED_ROOT_GUIDANCE"
        )

    def test_no_preamble_when_nothing_is_projected(self):
        context = _compose()
        assert "ENVELOPE_PRECEDENCE_PREAMBLE" not in [b.section for b in context.blocks]
        assert ENVELOPE_PRECEDENCE_PREAMBLE not in context.append_system_prompt

    def test_preamble_is_dispatcher_authored_and_must_never_be_content_scanned(self):
        # RULINGS §2: the preamble names `git push`, `gh` and `.env` on purpose.
        # Pointing the strict classifier at it is a miswiring, not a finding.
        scanner = StrictContentScanner([r"\bgit (push|commit|bisect)\b", r"\.env"])
        assert scanner.scan_text(ENVELOPE_PRECEDENCE_PREAMBLE)  # it *would* match
        with pytest.raises(ProvenanceSeparationError):
            scanner.scan_artifact(
                "preamble",
                ENVELOPE_PRECEDENCE_PREAMBLE,
                provenance_class=DISPATCHER_AUTHORED,
            )


class TestProvenanceDomains:
    def test_every_block_carries_a_provenance_domain(self):
        context = _compose(
            skill_projection=_skill_projection(CORE_SKILL, CONTEXTUAL_SKILL),
            guidance_projection=_guidance_projection(ROOT_SCOPE, KAVYA_SCOPE),
        )
        assert all(isinstance(b.provenance, Provenance) for b in context.blocks)
        by_section = {b.section: b.provenance for b in context.blocks}
        assert by_section["DISPATCHER_SYSTEM_POLICY"] is Provenance.DISPATCHER_AUTHORED
        assert by_section["TASK_ENVELOPE"] is Provenance.DISPATCHER_AUTHORED
        assert by_section["ENVELOPE_PRECEDENCE_PREAMBLE"] is Provenance.DISPATCHER_AUTHORED
        assert by_section["CORE_APPROVED_SKILLS"] is Provenance.SOURCE_DERIVED
        assert by_section["CONTEXTUAL_SKILLS"] is Provenance.SOURCE_DERIVED
        assert by_section["CURATED_ROOT_GUIDANCE"] is Provenance.PRE_CLASSIFIED
        assert by_section["CURATED_IN_SCOPE_SUBPROJECT_GUIDANCE"] is Provenance.PRE_CLASSIFIED
        assert by_section["GRAPH_REFRESH_CLAUSE"] is Provenance.DISPATCHER_AUTHORED

    def test_a_dispatcher_authored_block_is_never_fused_with_a_source_derived_one(self):
        context = _compose(
            skill_projection=_skill_projection(CORE_SKILL),
            guidance_projection=_guidance_projection(ROOT_SCOPE),
        )
        # No block mixes domains: a DISPATCHER_AUTHORED block never contains a
        # sentinel that only exists inside SOURCE_DERIVED material, and vice
        # versa. That is the mechanical form of "never mix before classification".
        dispatcher_blocks = [
            b for b in context.blocks if b.provenance is Provenance.DISPATCHER_AUTHORED
        ]
        source_blocks = [
            b for b in context.blocks if b.provenance is Provenance.SOURCE_DERIVED
        ]
        assert dispatcher_blocks and source_blocks
        for block in dispatcher_blocks:
            assert "CORE-SKILL-BODY-SENTINEL" not in block.text
            assert "ROOT-SOURCE-SENTINEL" not in block.text
        for block in source_blocks:
            assert "Dispatcher-authored orchestration law." not in block.text
            assert "ENVELOPE PRECEDENCE" not in block.text

    def test_scanned_and_exempt_artifact_sets_stay_disjoint_and_are_carried_through(self):
        projection = _guidance_projection(ROOT_SCOPE, KAVYA_SCOPE)
        context = _compose(guidance_projection=projection)
        assert set(projection.scanned_artifacts) & set(projection.exempt_artifacts) == set()
        assert context.scanned_artifacts == projection.scanned_artifacts
        assert context.exempt_artifacts == projection.exempt_artifacts

    def test_guidance_blocks_reassemble_the_engine_text_byte_for_byte(self):
        projection = _guidance_projection(ROOT_SCOPE, KAVYA_SCOPE)
        context = _compose(guidance_projection=projection)
        guidance = [
            b.text
            for b in context.blocks
            if b.section
            in (
                "CURATED_ROOT_GUIDANCE",
                "CURATED_IN_SCOPE_SUBPROJECT_GUIDANCE",
                "GRAPH_REFRESH_CLAUSE",
            )
        ]
        assert "".join(guidance) == projection.text

    def test_skill_blocks_carry_every_projected_skill_unmodified(self):
        projection = _skill_projection(CORE_SKILL, CONTEXTUAL_SKILL)
        context = _compose(skill_projection=projection)
        core = next(b for b in context.blocks if b.section == "CORE_APPROVED_SKILLS")
        contextual = next(b for b in context.blocks if b.section == "CONTEXTUAL_SKILLS")
        assert core.text == CORE_SKILL.text
        assert contextual.text == CONTEXTUAL_SKILL.text
        assert "----- BEGIN APPROVED GUIDANCE" in core.text
        assert "----- END APPROVED GUIDANCE" in contextual.text


# ---------------------------------------------------------------------------
# §15 — Fable
# ---------------------------------------------------------------------------


class TestFable:
    def test_reviewer_gets_guidance_and_zero_skills(self):
        context = _compose(
            role=WorkerRole.REVIEWER,
            skill_projection=None,
            guidance_projection=_guidance_projection(
                ROOT_SCOPE, KAVYA_SCOPE, audience="fable_review", graph_variant=None
            ),
        )
        sections = [b.section for b in context.blocks]
        assert "CORE_APPROVED_SKILLS" not in sections
        assert "CONTEXTUAL_SKILLS" not in sections
        assert "CURATED_ROOT_GUIDANCE" in sections
        assert "CURATED_IN_SCOPE_SUBPROJECT_GUIDANCE" in sections
        assert "ROOT-SOURCE-SENTINEL" in context.append_system_prompt

    def test_reviewer_with_a_skill_projection_is_a_programming_error(self):
        # Belt and braces for R5: the reviewer argv must carry no skill block.
        with pytest.raises(ValueError, match="reviewer"):
            _compose(
                role=WorkerRole.REVIEWER,
                skill_projection=_skill_projection(CORE_SKILL),
            )

    def test_reviewer_with_an_empty_skill_projection_is_accepted_and_emits_nothing(self):
        context = _compose(
            role=WorkerRole.REVIEWER,
            skill_projection=_skill_projection(),
            guidance_projection=_guidance_projection(ROOT_SCOPE, graph_variant=None),
        )
        assert "CORE_APPROVED_SKILLS" not in [b.section for b in context.blocks]


# ---------------------------------------------------------------------------
# Feature flags off — byte-identical to the pre-Gate-4.5 behaviour
# ---------------------------------------------------------------------------


class TestFlagsDisabled:
    def test_disabled_context_is_exactly_the_policy_file(self):
        context = _compose()
        assert context.append_system_prompt == POLICY_TEXT
        assert context.prompt == TASK_PROMPT
        assert [b.section for b in context.blocks] == [
            "DISPATCHER_SYSTEM_POLICY",
            "TASK_ENVELOPE",
        ]

    def test_disabled_context_has_no_fingerprint_material(self):
        context = _compose()
        assert context.skill_projection is None
        assert context.guidance_projection is None
        assert context.skill_record is None
        assert context.guidance_record is None

    def test_disabled_context_still_has_a_fingerprint_bound_to_the_envelope(self):
        # Not None: §16 wants the anchor recorded even when nothing is projected,
        # so a later run that *does* project is visibly a different context.
        first = _compose().fingerprint
        second = _compose().fingerprint
        assert first == second
        assert first != _compose(task_envelope_id="task-2").fingerprint


# ---------------------------------------------------------------------------
# §16 — combined context fingerprint
# ---------------------------------------------------------------------------


class TestCombinedFingerprint:
    def _fp(self, **overrides) -> str:
        kwargs = dict(
            role=WorkerRole.IMPLEMENTER,
            task_envelope_id="task-1",
            skill_projection=_skill_projection(CORE_SKILL),
            guidance_projection=_guidance_projection(ROOT_SCOPE, KAVYA_SCOPE),
        )
        kwargs.update(overrides)
        return context_fingerprint(**kwargs)

    def test_version_string_is_pinned(self):
        assert CONTEXT_FINGERPRINT_VERSION == "worker-context-fingerprint/v1"

    def test_fingerprint_is_a_sha256_hex_digest(self):
        value = self._fp()
        assert len(value) == 64
        assert all(c in "0123456789abcdef" for c in value)

    def test_fingerprint_is_stable_for_identical_inputs(self):
        assert self._fp() == self._fp()

    def test_changing_the_skill_policy_fingerprint_changes_it(self):
        other = _skill_projection(CORE_SKILL, fingerprint="2" * 64)
        assert self._fp(skill_projection=other) != self._fp()

    def test_changing_the_root_guidance_projection_changes_it(self):
        other_root = _scope(
            "pg.tgt.root", "", "ROOT-POLICY-SENTINEL\n", "ROOT-SOURCE-CHANGED\n"
        )
        assert (
            self._fp(guidance_projection=_guidance_projection(other_root, KAVYA_SCOPE))
            != self._fp()
        )

    def test_changing_a_scoped_guidance_projection_changes_it(self):
        other_kavya = _scope(
            "pg.tgt.kavya", "Kavya/", "KAVYA-POLICY-SENTINEL\n", "KAVYA-SOURCE-CHANGED\n"
        )
        assert (
            self._fp(guidance_projection=_guidance_projection(ROOT_SCOPE, other_kavya))
            != self._fp()
        )

    def test_changing_the_guidance_approval_version_changes_it(self):
        assert (
            self._fp(
                guidance_projection=_guidance_projection(
                    ROOT_SCOPE, KAVYA_SCOPE, approval_version="v2"
                )
            )
            != self._fp()
        )

    def test_changing_the_task_envelope_identity_changes_it(self):
        assert self._fp(task_envelope_id="task-2") != self._fp()

    def test_changing_the_role_changes_it(self):
        assert self._fp(role=WorkerRole.REVIEWER, skill_projection=None) != self._fp()

    def test_dropping_the_guidance_projection_changes_it(self):
        assert self._fp(guidance_projection=None) != self._fp()

    def test_dropping_the_skill_projection_changes_it(self):
        assert self._fp(skill_projection=None) != self._fp()

    def test_composed_context_exposes_the_same_fingerprint(self):
        context = _compose(
            skill_projection=_skill_projection(CORE_SKILL),
            guidance_projection=_guidance_projection(ROOT_SCOPE, KAVYA_SCOPE),
        )
        assert context.fingerprint == self._fp()

    def test_records_round_trip_from_the_projections(self):
        context = _compose(
            skill_projection=_skill_projection(CORE_SKILL),
            guidance_projection=_guidance_projection(ROOT_SCOPE, KAVYA_SCOPE),
        )
        assert context.skill_record is not None
        assert context.skill_record.skill_ids == ["plug.core-one"]
        assert context.guidance_record is not None
        assert context.guidance_record.logical_ids == ["pg.tgt.root", "pg.tgt.kavya"]
        assert context.guidance_record.graph_variant == "GATED_OFF"


class TestContextBlockShape:
    def test_block_is_frozen(self):
        block = ContextBlock(
            section="TASK_ENVELOPE",
            provenance=Provenance.DISPATCHER_AUTHORED,
            channel="prompt",
            text="x",
        )
        with pytest.raises(Exception):
            block.text = "y"  # type: ignore[misc]

    def test_unknown_section_is_refused(self):
        with pytest.raises(ValueError, match="section"):
            ContextBlock(
                section="NOT_A_SECTION",
                provenance=Provenance.DISPATCHER_AUTHORED,
                channel="system",
                text="x",
            )
