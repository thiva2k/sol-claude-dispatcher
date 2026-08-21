"""B1 — the argv single-element size cliff (Gate 4.5, Lane H).

Measured facts this file is built on (Lane G's live gate, ``GATE-LIVE-RESULT.md``
claims ``I-0`` … ``I-4``):

* Linux caps a **single argv element** at **131,071 bytes** (``MAX_ARG_STRLEN``),
  measured by bisection on this host. Exceed it and ``execve`` fails with
  ``E2BIG``: the worker never starts and the dispatcher used to surface a raw
  ``OSError``.
* 128,992 bytes launched and answered with **nothing truncated** (``I-3``/``I-4``).
* 144,486 bytes could not launch at all (``I-1``).
* The intended first-task shape is **79,406 bytes** — inside the ceiling with
  substantial headroom.
* The previously configured ceiling was **184,718 bytes**, 41% above what the OS
  accepts. It is INVALID and is refused at config load from this commit on.
* The measured production worst case composes to **142,006 bytes**. That shape
  is **not supported** under V1 inline transport and must be REFUSED.

Sol's V1 ceiling is 122,880 bytes (120 KiB), measured in UTF-8 **bytes**, applied
to the FINAL EXACT VALUE handed to ``--append-system-prompt``. Nothing here may
drop a Skill, drop a guidance scope, or truncate: an over-large task is refused.

Every process in this file is either never launched or is a throwaway shell
script in ``tmp_path``. Nothing spawns the real Claude CLI (§32).
"""

from __future__ import annotations

import asyncio
import errno
import os
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from sol_claude_dispatcher.config import (
    DISPATCHER_AUTHORED_RESERVE_BYTES,
    MAX_APPEND_SYSTEM_PROMPT_BYTES,
    MAX_GUIDANCE_BYTES_CEILING,
    MAX_PROJECTED_BYTES_CEILING,
    MAX_PROJECTED_CONTEXT_BYTES,
    MEASURED_SINGLE_ARGV_LIMIT_BYTES,
    ProjectGuidanceSettings,
    SkillsSettings,
    load_config,
    load_config_from_mapping,
)
from sol_claude_dispatcher.errors import ConfigurationError, ContextTooLarge
from sol_claude_dispatcher.models import TaskEnvelope, TaskRequest
from sol_claude_dispatcher.runner import (
    WorkerInvocation,
    build_argv,
    build_fable_invocation,
    build_worker_invocation,
    run_worker,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAKE_CLAUDE = PROJECT_ROOT / "tests" / "fake_bin" / "claude"
BASE_COMMIT = "a" * 40

#: The measured shapes from the live gate, reused as literal test data.
INTENDED_FIRST_TASK_BYTES = 79_406
PRODUCTION_WORST_CASE_BYTES = 142_006
PREVIOUSLY_CONFIGURED_CEILING_BYTES = 184_718
LARGEST_COMPOSED_THAT_STARTED_BYTES = 128_992


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def dispatcher_config(tmp_path: Path):
    return load_config_from_mapping(
        {
            "dispatcher": {"state_dir": str(tmp_path / "state")},
            "models": {"sonnet": "sonnet", "opus": "opus", "fable": "fable"},
            "routing": {"default_model": "sonnet"},
            "security": {
                "max_dispatch_depth": 1,
                "allowed_repository_roots": [str(tmp_path)],
            },
            "claude": {"binary": str(FAKE_CLAUDE)},
        },
        project_root=PROJECT_ROOT,
    )


@pytest.fixture
def envelope(valid_request_dict: dict, git_repo: Path) -> TaskEnvelope:
    request = TaskRequest.model_validate(valid_request_dict)
    return TaskEnvelope.from_request(
        request, canonical_root=str(git_repo), base_commit=BASE_COMMIT
    )


@pytest.fixture
def fake_env(tmp_path: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "LANG": "C.UTF-8",
        "FAKE_CLAUDE_MODE": "success",
        "FAKE_CLAUDE_LOG": str(tmp_path / "fake-claude.log"),
    }


def payload_of(nbytes: int, *, filler: str = "x") -> str:
    """A UTF-8 payload of exactly ``nbytes`` bytes built from ``filler``."""
    unit = len(filler.encode("utf-8"))
    assert nbytes % unit == 0, "pick a filler whose width divides the target"
    text = filler * (nbytes // unit)
    assert len(text.encode("utf-8")) == nbytes
    return text


def spec_with(prompt_text: str, **overrides) -> WorkerInvocation:
    kwargs = dict(
        binary=str(FAKE_CLAUDE),
        model="sonnet",
        session_id="11111111-1111-4111-8111-111111111111",
        cwd=Path("/tmp"),
        prompt="Implement the objective.",
        timeout_seconds=10,
        role="implementer",
        append_system_prompt=prompt_text,
        disallowed_tools=list(_always_disallowed()),
    )
    kwargs.update(overrides)
    return WorkerInvocation(**kwargs)  # type: ignore[arg-type]


def _always_disallowed() -> tuple[str, ...]:
    from sol_claude_dispatcher.runner import ALWAYS_DISALLOWED_TOOLS

    return ALWAYS_DISALLOWED_TOOLS


def sentinel_binary(tmp_path: Path) -> tuple[Path, Path]:
    """A throwaway 'CLI' that records the fact it was executed, and its marker."""
    marker = tmp_path / "LAUNCHED"
    binary = tmp_path / "never-run-me"
    binary.write_text(f'#!/bin/sh\n: > "{marker}"\necho "{{}}"\n')
    binary.chmod(0o755)
    return binary, marker


# ---------------------------------------------------------------------------
# 1. the ceiling itself, and the facts it was chosen from
# ---------------------------------------------------------------------------


class TestCeilingConstants:
    def test_ceiling_is_120_kib_in_bytes(self):
        assert MAX_APPEND_SYSTEM_PROMPT_BYTES == 122_880
        assert MAX_APPEND_SYSTEM_PROMPT_BYTES == 120 * 1024

    def test_ceiling_sits_below_the_measured_linux_cliff(self):
        assert MEASURED_SINGLE_ARGV_LIMIT_BYTES == 131_071
        assert MAX_APPEND_SYSTEM_PROMPT_BYTES < MEASURED_SINGLE_ARGV_LIMIT_BYTES
        # ~8 KiB of deliberate reserve below the kernel's own limit.
        headroom = MEASURED_SINGLE_ARGV_LIMIT_BYTES - MAX_APPEND_SYSTEM_PROMPT_BYTES
        assert headroom >= 8_000

    def test_the_intended_first_task_shape_fits(self):
        assert INTENDED_FIRST_TASK_BYTES < MAX_APPEND_SYSTEM_PROMPT_BYTES

    def test_the_production_worst_case_is_refused(self):
        """142,006 bytes is an intentionally UNSUPPORTED composition under V1."""
        assert PRODUCTION_WORST_CASE_BYTES > MAX_APPEND_SYSTEM_PROMPT_BYTES

    def test_the_previously_configured_ceiling_is_invalid(self):
        assert PREVIOUSLY_CONFIGURED_CEILING_BYTES > MEASURED_SINGLE_ARGV_LIMIT_BYTES


# ---------------------------------------------------------------------------
# 2. the preflight boundary
# ---------------------------------------------------------------------------


class TestPreflightBoundary:
    def test_payload_at_the_exact_ceiling_is_accepted(self):
        text = payload_of(MAX_APPEND_SYSTEM_PROMPT_BYTES)
        argv = build_argv(spec_with(text))
        emitted = argv[argv.index("--append-system-prompt") + 1]
        # Accepted AND byte-identical: nothing is trimmed to make it fit.
        assert emitted == text
        assert len(emitted.encode("utf-8")) == MAX_APPEND_SYSTEM_PROMPT_BYTES

    def test_one_byte_over_the_ceiling_is_refused(self):
        text = payload_of(MAX_APPEND_SYSTEM_PROMPT_BYTES + 1)
        with pytest.raises(ContextTooLarge) as exc:
            build_argv(spec_with(text))
        details = exc.value.details
        assert details["actual_bytes"] == MAX_APPEND_SYSTEM_PROMPT_BYTES + 1
        assert details["maximum_bytes"] == MAX_APPEND_SYSTEM_PROMPT_BYTES
        assert details["excess_bytes"] == 1
        assert details["model"] == "sonnet"

    def test_the_production_worst_case_shape_is_refused(self):
        with pytest.raises(ContextTooLarge) as exc:
            build_argv(spec_with(payload_of(PRODUCTION_WORST_CASE_BYTES)))
        assert exc.value.details["excess_bytes"] == (
            PRODUCTION_WORST_CASE_BYTES - MAX_APPEND_SYSTEM_PROMPT_BYTES
        )

    def test_a_shape_the_kernel_accepted_but_policy_does_not(self):
        """128,992 bytes launched live — under V1 policy it is still refused."""
        with pytest.raises(ContextTooLarge):
            build_argv(spec_with(payload_of(LARGEST_COMPOSED_THAT_STARTED_BYTES)))

    def test_the_intended_first_task_shape_launches(self, tmp_path: Path):
        argv = build_argv(spec_with(payload_of(INTENDED_FIRST_TASK_BYTES)))
        assert "--append-system-prompt" in argv


class TestBytesNotCharacters:
    def test_character_count_under_the_limit_can_still_be_refused(self):
        """A 61,441-character payload is 122,882 BYTES. Bytes decide."""
        text = payload_of((MAX_APPEND_SYSTEM_PROMPT_BYTES + 2), filler="é")
        assert len(text) < MAX_APPEND_SYSTEM_PROMPT_BYTES          # characters
        assert len(text.encode("utf-8")) > MAX_APPEND_SYSTEM_PROMPT_BYTES
        with pytest.raises(ContextTooLarge) as exc:
            build_argv(spec_with(text))
        assert exc.value.details["actual_bytes"] == len(text.encode("utf-8"))

    def test_a_full_ceiling_of_two_byte_characters_is_accepted(self):
        text = payload_of(MAX_APPEND_SYSTEM_PROMPT_BYTES, filler="é")
        assert len(text) == MAX_APPEND_SYSTEM_PROMPT_BYTES // 2
        argv = build_argv(spec_with(text))
        assert argv[argv.index("--append-system-prompt") + 1] == text

    def test_multibyte_boundary_straddle(self):
        """A 4-byte emoji that ends exactly on the ceiling passes; one past fails."""
        emoji = "\N{ROCKET}"                       # 4 UTF-8 bytes
        assert len(emoji.encode("utf-8")) == 4
        head = payload_of(MAX_APPEND_SYSTEM_PROMPT_BYTES - 4)
        exact = head + emoji
        assert len(exact.encode("utf-8")) == MAX_APPEND_SYSTEM_PROMPT_BYTES
        build_argv(spec_with(exact))               # accepted

        over = head + emoji + "x"
        with pytest.raises(ContextTooLarge) as exc:
            build_argv(spec_with(over))
        assert exc.value.details["excess_bytes"] == 1

    def test_a_single_multibyte_character_can_cross_the_boundary(self):
        head = payload_of(MAX_APPEND_SYSTEM_PROMPT_BYTES - 2)
        with pytest.raises(ContextTooLarge) as exc:
            build_argv(spec_with(head + "\N{ROCKET}"))
        # 4-byte character, 2 bytes of room: over by exactly 2.
        assert exc.value.details["excess_bytes"] == 2


# ---------------------------------------------------------------------------
# 3. refuse — never truncate, never drop
# ---------------------------------------------------------------------------


class TestNothingIsSilentlyRemoved:
    def _composed(self) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        skills = tuple(f"skill.pack-{i}" for i in range(6))
        scopes = ("pg.fva.root", "pg.fva.kavya", "pg.fva.flico")
        blocks = [f"----- SKILL {sid} -----\n" + payload_of(20_000) for sid in skills]
        blocks += [f"----- SCOPE {cid} -----\n" + payload_of(8_000) for cid in scopes]
        return "\n\n".join(blocks), skills, scopes

    def test_oversized_context_is_refused_not_truncated(self):
        text, skills, scopes = self._composed()
        spec = spec_with(text, skill_ids=skills, guidance_scope_ids=scopes)
        with pytest.raises(ContextTooLarge):
            build_argv(spec)
        # The invocation is untouched: every projected block is still there.
        for sid in skills:
            assert f"----- SKILL {sid} -----" in spec.append_system_prompt
        for cid in scopes:
            assert f"----- SCOPE {cid} -----" in spec.append_system_prompt
        assert len(spec.append_system_prompt.encode("utf-8")) == len(
            text.encode("utf-8")
        )

    def test_no_skill_is_dropped_to_fit(self):
        text, skills, scopes = self._composed()
        with pytest.raises(ContextTooLarge) as exc:
            build_argv(spec_with(text, skill_ids=skills, guidance_scope_ids=scopes))
        # Every selected skill is reported, so Sol can narrow the task herself.
        assert exc.value.details["skill_ids"] == list(skills)

    def test_no_project_guidance_scope_is_dropped_to_fit(self):
        text, skills, scopes = self._composed()
        with pytest.raises(ContextTooLarge) as exc:
            build_argv(spec_with(text, skill_ids=skills, guidance_scope_ids=scopes))
        assert exc.value.details["guidance_scope_ids"] == list(scopes)

    def test_a_second_identical_attempt_is_refused_identically(self):
        """No adaptive shrinking on retry: the refusal is deterministic."""
        text, skills, scopes = self._composed()
        first = None
        for _ in range(2):
            with pytest.raises(ContextTooLarge) as exc:
                build_argv(spec_with(text, skill_ids=skills, guidance_scope_ids=scopes))
            if first is None:
                first = exc.value.details
            else:
                assert exc.value.details == first

    def test_the_error_never_quotes_the_payload(self):
        secret = "SENT-PROJECT-GUIDANCE-BODY"
        text = secret + payload_of(MAX_APPEND_SYSTEM_PROMPT_BYTES)
        with pytest.raises(ContextTooLarge) as exc:
            build_argv(spec_with(text, skill_ids=("s.one",)))
        rendered = f"{exc.value.message} {exc.value.details} {exc.value.remediation}"
        assert secret not in rendered
        assert len(rendered) < 2_000


# ---------------------------------------------------------------------------
# 4. every transport path
# ---------------------------------------------------------------------------


class TestEveryInvocationPath:
    def test_worker_dispatch_path_refuses(
        self, dispatcher_config, envelope, git_repo, fake_env
    ):
        spec = build_worker_invocation(
            envelope,
            dispatcher_config,
            model="sonnet",
            session_id=str(uuid.uuid4()),
            prompt="p",
            cwd=git_repo,
            base_env=fake_env,
            append_system_prompt=payload_of(MAX_APPEND_SYSTEM_PROMPT_BYTES + 1),
        )
        with pytest.raises(ContextTooLarge) as exc:
            build_argv(spec)
        assert exc.value.details["task_id"] == envelope.task_id
        assert exc.value.details["role"] == "implementer"

    def test_resume_path_cannot_bypass_the_limit(
        self, dispatcher_config, envelope, git_repo, fake_env
    ):
        spec = build_worker_invocation(
            envelope,
            dispatcher_config,
            model="sonnet",
            session_id="ignored-on-resume",
            resume_session_id="22222222-2222-4222-8222-222222222222",
            prompt="Keep going.",
            cwd=git_repo,
            base_env=fake_env,
            append_system_prompt=payload_of(MAX_APPEND_SYSTEM_PROMPT_BYTES + 1),
        )
        with pytest.raises(ContextTooLarge):
            build_argv(spec)

    def test_fable_review_path_refuses(
        self, dispatcher_config, envelope, git_repo, fake_env
    ):
        spec = build_fable_invocation(
            envelope,
            dispatcher_config,
            session_id=str(uuid.uuid4()),
            prompt="Review the diff.",
            cwd=git_repo,
            base_env=fake_env,
            append_system_prompt=payload_of(MAX_APPEND_SYSTEM_PROMPT_BYTES + 1),
        )
        with pytest.raises(ContextTooLarge) as exc:
            build_argv(spec)
        assert exc.value.details["role"] == "reviewer"
        assert exc.value.details["model"] == "fable"

    async def test_no_process_is_launched_on_a_preflight_refusal(self, tmp_path: Path):
        binary, marker = sentinel_binary(tmp_path)
        spec = spec_with(
            payload_of(MAX_APPEND_SYSTEM_PROMPT_BYTES + 1),
            binary=str(binary),
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
        )
        with pytest.raises(ContextTooLarge):
            await run_worker(spec)
        assert not marker.exists(), "a worker was launched despite the refusal"

    async def test_an_accepted_payload_still_launches(self, tmp_path: Path):
        binary, marker = sentinel_binary(tmp_path)
        spec = spec_with(
            payload_of(1_024),
            binary=str(binary),
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
        )
        run = await run_worker(spec)
        assert marker.exists()
        assert run.start_failed is False


# ---------------------------------------------------------------------------
# 5. defence in depth — the kernel stays authoritative
# ---------------------------------------------------------------------------


class TestKernelE2BIG:
    async def _run_with_spawn_error(self, tmp_path: Path, exc: OSError):
        async def boom(*args, **kwargs):
            raise exc

        spec = spec_with(
            payload_of(1_024),
            binary=str(FAKE_CLAUDE),
            cwd=tmp_path,
            env={"PATH": "/usr/bin:/bin"},
        )
        original = asyncio.create_subprocess_exec
        asyncio.create_subprocess_exec = boom  # type: ignore[assignment]
        try:
            return await run_worker(spec)
        finally:
            asyncio.create_subprocess_exec = original  # type: ignore[assignment]

    async def test_e2big_is_translated_to_the_typed_error(self, tmp_path: Path):
        with pytest.raises(ContextTooLarge) as exc:
            await self._run_with_spawn_error(
                tmp_path, OSError(errno.E2BIG, "Argument list too long")
            )
        details = exc.value.details
        assert details["errno"] == errno.E2BIG
        assert details["source"] == "kernel_e2big"
        assert details["maximum_bytes"] == MAX_APPEND_SYSTEM_PROMPT_BYTES
        # The original errno survives for diagnostics.
        assert isinstance(exc.value.__cause__, OSError)
        assert exc.value.__cause__.errno == errno.E2BIG

    async def test_an_unrelated_oserror_is_not_mislabelled(self, tmp_path: Path):
        run = await self._run_with_spawn_error(
            tmp_path, OSError(errno.ENOMEM, "Cannot allocate memory")
        )
        assert run.start_failed is True
        assert run.exit_code is None
        assert "Cannot allocate memory" in run.stderr

    async def test_a_missing_binary_is_still_reported_as_such(self, tmp_path: Path):
        from sol_claude_dispatcher.errors import ClaudeBinaryNotFound

        with pytest.raises(ClaudeBinaryNotFound):
            await self._run_with_spawn_error(
                tmp_path, FileNotFoundError(errno.ENOENT, "No such file")
            )


# ---------------------------------------------------------------------------
# 6. configuration cannot request more than the transport can carry
# ---------------------------------------------------------------------------


def _config(tmp_path: Path, **sections):
    data = {
        "dispatcher": {"state_dir": str(tmp_path / "state")},
        "models": {"sonnet": "sonnet", "opus": "opus", "fable": "fable"},
        "routing": {"default_model": "sonnet"},
        "security": {"allowed_repository_roots": [str(tmp_path)]},
    }
    data.update(sections)
    return load_config_from_mapping(data, project_root=PROJECT_ROOT)


class TestConfigCeiling:
    def test_the_previously_configured_ceiling_is_rejected(self, tmp_path: Path):
        """skills 120,000 + guidance 60,000 + overhead = 184,718. REFUSED."""
        with pytest.raises(ConfigurationError) as exc:
            _config(
                tmp_path,
                skills={"enabled": True, "max_projected_bytes": 120_000},
                project_guidance={"enabled": True, "max_projected_bytes": 60_000},
            )
        rendered = str(exc.value.details).replace(",", "").replace("_", "")
        # Named against one of the two transport numbers, never a vague refusal.
        assert str(MAX_APPEND_SYSTEM_PROMPT_BYTES) in rendered or (
            str(MAX_PROJECTED_CONTEXT_BYTES) in rendered
        )

    def test_a_single_field_above_the_budget_is_rejected(self, tmp_path: Path):
        with pytest.raises(ConfigurationError):
            _config(
                tmp_path,
                skills={
                    "enabled": True,
                    "max_projected_bytes": MAX_PROJECTED_CONTEXT_BYTES + 1,
                },
            )

    def test_an_invented_ceiling_key_is_rejected(self, tmp_path: Path):
        """`max_projected_context_bytes = 184718` must not be honoured."""
        with pytest.raises(ConfigurationError):
            _config(
                tmp_path,
                skills={
                    "enabled": True,
                    "max_projected_context_bytes": PREVIOUSLY_CONFIGURED_CEILING_BYTES,
                },
            )

    def test_two_individually_legal_caps_can_still_be_refused_together(
        self, tmp_path: Path
    ):
        """Fail closed. The operator must learn the policy cannot be honoured.

        100,000 and 60,000 are each below the per-field ceiling; their SUM is
        not. A sum of legal caps is not automatically legal — they share one
        argv element.
        """
        with pytest.raises(ConfigurationError) as exc:
            _config(
                tmp_path,
                skills={"enabled": True, "max_projected_bytes": 100_000},
                project_guidance={"enabled": True, "max_projected_bytes": 60_000},
            )
        rendered = str(exc.value.details).replace(",", "").replace("_", "")
        assert str(MAX_APPEND_SYSTEM_PROMPT_BYTES) in rendered
        # Explicitly refused, not normalised down to something that fits.
        assert "not clamped" in rendered

    def test_a_disabled_section_cannot_hide_an_over_budget_policy(self, tmp_path: Path):
        with pytest.raises(ConfigurationError):
            _config(
                tmp_path,
                skills={"enabled": False, "max_projected_bytes": 120_000},
                project_guidance={"enabled": False, "max_projected_bytes": 60_000},
            )

    def test_a_within_budget_config_loads(self, tmp_path: Path):
        config = _config(
            tmp_path,
            skills={"enabled": True, "max_projected_bytes": 72_000},
            project_guidance={"enabled": True, "max_projected_bytes": 42_000},
        )
        assert config.skills.max_projected_bytes == 72_000
        assert config.project_guidance.max_projected_bytes == 42_000

    def test_defaults_are_within_the_budget(self, tmp_path: Path):
        config = _config(tmp_path)
        composed = (
            config.skills.max_projected_bytes
            + config.project_guidance.max_projected_bytes
            + DISPATCHER_AUTHORED_RESERVE_BYTES
        )
        assert composed <= MAX_APPEND_SYSTEM_PROMPT_BYTES

    def test_the_shipped_production_config_is_within_the_budget(self):
        config = load_config(PROJECT_ROOT / "config" / "dispatcher.toml")
        composed = (
            config.skills.max_projected_bytes
            + config.project_guidance.max_projected_bytes
            + DISPATCHER_AUTHORED_RESERVE_BYTES
        )
        assert composed <= MAX_APPEND_SYSTEM_PROMPT_BYTES
        # Untouched by this fix: both projections stay inert.
        assert config.skills.enabled is False
        assert config.project_guidance.enabled is False

    def test_the_shipped_example_config_is_within_the_budget(self):
        import tomllib

        example = tomllib.loads(
            (PROJECT_ROOT / "config" / "dispatcher.example.toml").read_text()
        )
        composed = (
            example["skills"]["max_projected_bytes"]
            + example["project_guidance"]["max_projected_bytes"]
            + DISPATCHER_AUTHORED_RESERVE_BYTES
        )
        assert composed <= MAX_APPEND_SYSTEM_PROMPT_BYTES

    def test_the_budget_is_derived_from_the_transport_ceiling(self):
        assert (
            MAX_PROJECTED_CONTEXT_BYTES
            == MAX_APPEND_SYSTEM_PROMPT_BYTES - DISPATCHER_AUTHORED_RESERVE_BYTES
        )

    def test_each_field_ceiling_is_the_transport_budget(self):
        """Pinned per-section, not only in sum.

        The cross-field check would mask a raised per-field ceiling in almost
        every combination, so the sections are asserted directly: neither may
        individually promise more than one argv element can carry.
        """
        assert MAX_PROJECTED_BYTES_CEILING == MAX_PROJECTED_CONTEXT_BYTES
        assert MAX_GUIDANCE_BYTES_CEILING == MAX_PROJECTED_CONTEXT_BYTES

    @pytest.mark.parametrize("section", [SkillsSettings, ProjectGuidanceSettings])
    def test_a_section_refuses_a_cap_above_the_budget(self, section):
        section(max_projected_bytes=MAX_PROJECTED_CONTEXT_BYTES)  # accepted
        with pytest.raises(PydanticValidationError):
            section(max_projected_bytes=MAX_PROJECTED_CONTEXT_BYTES + 1)
