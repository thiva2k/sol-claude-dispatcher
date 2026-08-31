"""The fail-closed aggregate run budget (GATE 6, Lane L — closes FINDING K-1).

Lane K measured that ``models.ValidationSpec`` permits 32 commands of up to
3,600 s each, so an envelope may legally declare ``32 x 3610 = 115,520 s`` of
validation. No MCP tool timeout can cover that: the applied
``tool_timeout_sec`` is 10,800 s. Before this module existed, nothing in the
code refused such an envelope — the dispatcher would start a worker, run
validation, and have its waiter cancelled part-way through, leaving Sol to
recover the state with ``get_task``.

The fix is a *refusal*, not a repair. These tests pin that distinction hard:
the dispatcher must never truncate a validation command's timeout, never drop a
command to fit, and never clamp an over-large config down to something legal.
An operator (or Sol) who declares more work than the transport can carry must
learn that, not silently receive a smaller run.

The budget is bounded, not the wait. ``waiting.py`` still has no timeout of its
own — asserted here — so the MCP tool timeout stays a LATENCY bound rather than
a correctness bound (Lane J §7, Lane K §2.6).
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from sol_claude_dispatcher import git, runner, validation as validation_module, waiting
from sol_claude_dispatcher.config import (
    DEFAULT_TOTAL_RUN_BUDGET_SECONDS,
    EVIDENCE_GIT_BUDGET_SECONDS,
    MAX_TOTAL_RUN_BUDGET_CEILING,
    MAX_VALIDATION_COMMANDS,
    MCP_TRANSPORT_BUDGET_SECONDS,
    TRANSPORT_TOOL_TIMEOUT_SECONDS,
    VALIDATION_COMMAND_TAIL_SECONDS,
    WORKER_TERMINATION_TAIL_SECONDS,
    load_config,
    load_config_from_mapping,
    required_tool_timeout_seconds,
)
from sol_claude_dispatcher.errors import (
    ERROR_CODES,
    ConfigurationError,
    DispatcherError,
    ValidationBudgetExceeded,
)
from sol_claude_dispatcher.models import (
    ExecutionSpec,
    TaskEnvelope,
    TaskRequest,
    ValidationCommand,
    ValidationSpec,
)
from sol_claude_dispatcher.validation import (
    assert_validation_budget,
    validation_budget_facts,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _commands(*timeouts: int, program: str = "pytest") -> list[ValidationCommand]:
    return [
        ValidationCommand(argv=[program, "-q", f"tests/test_{i}.py"], timeout_seconds=t)
        for i, t in enumerate(timeouts)
    ]


def _request(git_repo: Path, *, execution: int, validation: list[ValidationCommand]):
    return TaskRequest(
        repository={"root": str(git_repo), "base_ref": "a" * 40},
        task={"objective": "Do the thing."},
        execution=ExecutionSpec(timeout_seconds=execution),
        validation=ValidationSpec(commands=validation),
    )


@pytest.fixture
def config(config_file: Path):
    return load_config(config_file)


# ---------------------------------------------------------------------------
# 1. The constants are derived, not recalled
# ---------------------------------------------------------------------------


def test_worker_termination_tail_matches_the_runner_it_describes():
    """5 s SIGTERM grace + 10 s SIGKILL reap + 10 s pipe drain."""
    assert runner.DEFAULT_GRACE_SECONDS == 5.0
    assert WORKER_TERMINATION_TAIL_SECONDS == int(runner.DEFAULT_GRACE_SECONDS) + 10 + 10
    assert WORKER_TERMINATION_TAIL_SECONDS == 25


def test_validation_command_tail_matches_validation_py():
    """5 s SIGTERM grace + 5 s stream drain, per command."""
    assert validation_module._GRACE_SECONDS == 5.0
    assert VALIDATION_COMMAND_TAIL_SECONDS == int(validation_module._GRACE_SECONDS) * 2
    assert VALIDATION_COMMAND_TAIL_SECONDS == 10


def test_max_validation_commands_matches_the_model_that_enforces_it():
    field = ValidationSpec.model_fields["commands"]
    limits = [m for m in field.metadata if getattr(m, "max_length", None) is not None]
    assert limits, "ValidationSpec.commands must carry a max_length"
    assert limits[0].max_length == MAX_VALIDATION_COMMANDS == 32


def test_evidence_git_budget_is_24_git_calls_at_the_real_git_timeout():
    assert git._GIT_TIMEOUT_SECONDS == 60
    assert EVIDENCE_GIT_BUDGET_SECONDS == 24 * git._GIT_TIMEOUT_SECONDS == 1_440


def test_the_applied_transport_timeout_is_lane_ks_10800():
    assert TRANSPORT_TOOL_TIMEOUT_SECONDS == 10_800


def test_default_budget_is_the_governed_worker_plus_validation_shape():
    """Sol-approved production policy (Lane N, 2026-08-23):

        3,600  maximum worker execution
      + 3,600  maximum declared validation
      = 7,200  declared run budget          <- validation.max_total_seconds

    This supersedes Lane L's conservative 7,115 s default, which refused
    Lane K's own governed sizing shape (a full-length worker plus a
    full-length aggregate validation phase) by 85 s.
    """
    assert DEFAULT_TOTAL_RUN_BUDGET_SECONDS == 7_200
    assert DEFAULT_TOTAL_RUN_BUDGET_SECONDS == 3_600 + 3_600


def test_the_ceiling_is_exactly_what_the_transport_can_honour():
    """Everything the tool timeout must also pay for, subtracted once.

    Unaffected by the 7,115 -> 7,200 default change: the overhead terms are
    all fixed costs independent of the declared budget, so the ceiling is
    recomputed from them and lands on the same 8,955 s as before.
    """
    overhead = (
        WORKER_TERMINATION_TAIL_SECONDS
        + MAX_VALIDATION_COMMANDS * VALIDATION_COMMAND_TAIL_SECONDS
        + EVIDENCE_GIT_BUDGET_SECONDS
        + MCP_TRANSPORT_BUDGET_SECONDS
    )
    assert overhead == 1_845
    assert MAX_TOTAL_RUN_BUDGET_CEILING == TRANSPORT_TOOL_TIMEOUT_SECONDS - overhead
    assert MAX_TOTAL_RUN_BUDGET_CEILING == 8_955


def test_the_default_budget_is_below_the_ceiling_it_is_checked_against():
    assert DEFAULT_TOTAL_RUN_BUDGET_SECONDS < MAX_TOTAL_RUN_BUDGET_CEILING
    assert MAX_TOTAL_RUN_BUDGET_CEILING - DEFAULT_TOTAL_RUN_BUDGET_SECONDS == 1_755


def test_required_tool_timeout_fits_under_the_applied_transport_timeout(config):
    """7,200 + 1,845 = 9,045 s required against a 10,800 s applied ceiling."""
    required = required_tool_timeout_seconds(config)
    assert required == DEFAULT_TOTAL_RUN_BUDGET_SECONDS + 1_845 == 9_045
    assert required <= TRANSPORT_TOOL_TIMEOUT_SECONDS
    assert TRANSPORT_TOOL_TIMEOUT_SECONDS - required == 1_755


def test_required_tool_timeout_is_never_the_stale_plus_300_shape(config):
    """3,900 s covered the worker phase and 275 s of nothing else (Lane K §2.5)."""
    stale = config.dispatcher.max_timeout_seconds + 300
    assert stale == 3_900
    assert required_tool_timeout_seconds(config) != stale
    assert required_tool_timeout_seconds(config) > stale


# ---------------------------------------------------------------------------
# 2. Config above transport capacity is REFUSED at load, never clamped
# ---------------------------------------------------------------------------


def _config_mapping(git_repo: Path, **validation_keys) -> dict:
    return {
        "dispatcher": {"state_dir": "./state", "max_timeout_seconds": 3600},
        "models": {"sonnet": "sonnet", "opus": "opus", "fable": "fable"},
        "routing": {"default_model": "sonnet"},
        "security": {"allowed_repository_roots": [str(git_repo)]},
        "validation": {"run_dispatcher_validation": True, **validation_keys},
    }


def test_a_budget_above_transport_capacity_is_refused_at_load(git_repo: Path):
    with pytest.raises(ConfigurationError) as exc:
        load_config_from_mapping(
            _config_mapping(git_repo, max_total_seconds=MAX_TOTAL_RUN_BUDGET_CEILING + 1)
        )
    rendered = json.dumps(exc.value.to_payload())
    assert str(MAX_TOTAL_RUN_BUDGET_CEILING) in rendered
    assert str(TRANSPORT_TOOL_TIMEOUT_SECONDS) in rendered


def test_a_budget_above_transport_capacity_is_not_clamped_down(git_repo: Path):
    """The B1 discipline: the operator learns, they do not get a smaller run."""
    with pytest.raises(ConfigurationError):
        load_config_from_mapping(_config_mapping(git_repo, max_total_seconds=100_000))


def test_a_budget_exactly_at_the_ceiling_loads(git_repo: Path):
    cfg = load_config_from_mapping(
        _config_mapping(git_repo, max_total_seconds=MAX_TOTAL_RUN_BUDGET_CEILING)
    )
    assert cfg.validation.max_total_seconds == MAX_TOTAL_RUN_BUDGET_CEILING
    assert required_tool_timeout_seconds(cfg) == TRANSPORT_TOOL_TIMEOUT_SECONDS


def test_a_smaller_budget_is_preserved_verbatim(git_repo: Path):
    cfg = load_config_from_mapping(_config_mapping(git_repo, max_total_seconds=3_700))
    assert cfg.validation.max_total_seconds == 3_700


def test_a_budget_that_cannot_even_seat_one_full_length_worker_is_refused(
    git_repo: Path,
):
    """900 s of budget under a 3,600 s worker ceiling accepts no envelope."""
    with pytest.raises(ConfigurationError):
        load_config_from_mapping(_config_mapping(git_repo, max_total_seconds=900))


def test_a_zero_or_negative_budget_is_refused(git_repo: Path):
    for bad in (0, -1):
        with pytest.raises(ConfigurationError):
            load_config_from_mapping(_config_mapping(git_repo, max_total_seconds=bad))


def test_the_shipped_example_config_documents_the_budget(project_root: Path):
    text = (project_root / "config" / "dispatcher.example.toml").read_text()
    assert "max_total_seconds" in text


# ---------------------------------------------------------------------------
# 3. The boundary: at budget accepted, one second over refused
# ---------------------------------------------------------------------------


def test_an_envelope_exactly_at_budget_is_accepted(config, git_repo: Path):
    budget = config.validation.max_total_seconds
    request = _request(git_repo, execution=3_600, validation=_commands(budget - 3_600))
    assert_validation_budget(request, config, phase="dispatch")


def test_one_second_over_budget_is_refused(config, git_repo: Path):
    """``ValidationCommand.timeout_seconds`` itself caps at 3,600 s per command,

    so the one-second excess is split across two commands rather than declared
    on a single one.
    """
    budget = config.validation.max_total_seconds
    excess_total = budget - 3_600 + 1
    request = _request(
        git_repo, execution=3_600, validation=_commands(3_600, excess_total - 3_600)
    )
    with pytest.raises(ValidationBudgetExceeded) as exc:
        assert_validation_budget(request, config, phase="dispatch")
    assert exc.value.details["excess_seconds"] == 1
    assert exc.value.details["budget_seconds"] == budget
    assert exc.value.details["declared_total_seconds"] == budget + 1


def test_exactly_7200_seconds_declared_is_accepted(config, git_repo: Path):
    """Pins the shipped default itself, independent of ``config.validation``."""
    assert config.validation.max_total_seconds == 7_200
    request = _request(git_repo, execution=3_600, validation=_commands(3_600))
    assert_validation_budget(request, config, phase="dispatch")


def test_exactly_7201_seconds_declared_is_refused(config, git_repo: Path):
    """3,600 (worker) + 3,600 + 1 (validation, split across two commands)."""
    request = _request(git_repo, execution=3_600, validation=_commands(3_600, 1))
    with pytest.raises(ValidationBudgetExceeded) as exc:
        assert_validation_budget(request, config, phase="dispatch")
    assert exc.value.details["excess_seconds"] == 1
    assert exc.value.details["declared_total_seconds"] == 7_201


def test_the_governed_3600_worker_plus_3600_validation_shape_is_accepted(
    config, git_repo: Path
):
    """The specific case that motivated the 7,115 -> 7,200 correction.

    Lane K's governed sizing shape: a full-length (3,600 s) worker followed
    by a full-length (3,600 s) aggregate validation phase. Under the old
    7,115 s default this was refused by 85 s; it is Sol-approved production
    policy and must be accepted now.
    """
    request = _request(git_repo, execution=3_600, validation=_commands(3_600))
    assert_validation_budget(request, config, phase="dispatch")


def test_the_structural_worst_case_lane_k_found_is_refused(config, git_repo: Path):
    """32 commands x 3,600 s — the 115,520 s path FINDING K-1 named."""
    request = _request(git_repo, execution=3_600, validation=_commands(*([3_600] * 32)))
    with pytest.raises(ValidationBudgetExceeded):
        assert_validation_budget(request, config, phase="dispatch")


def test_an_envelope_with_no_validation_commands_is_accepted(config, git_repo: Path):
    request = _request(git_repo, execution=3_600, validation=[])
    assert_validation_budget(request, config, phase="dispatch")


def test_execution_alone_can_never_exceed_the_budget_at_the_shipped_maximum(config):
    assert config.dispatcher.max_timeout_seconds <= config.validation.max_total_seconds


# ---------------------------------------------------------------------------
# 4. The refusal is a refusal: nothing truncated, nothing dropped
# ---------------------------------------------------------------------------


def test_a_refusal_does_not_truncate_any_validation_timeout(config, git_repo: Path):
    commands = _commands(3_600, 3_600, 3_600)
    before = [c.timeout_seconds for c in commands]
    request = _request(git_repo, execution=3_600, validation=commands)
    with pytest.raises(ValidationBudgetExceeded):
        assert_validation_budget(request, config, phase="dispatch")
    assert [c.timeout_seconds for c in request.validation.commands] == before
    assert request.execution.timeout_seconds == 3_600


def test_a_refusal_does_not_drop_a_validation_command(config, git_repo: Path):
    request = _request(git_repo, execution=3_600, validation=_commands(*([3_600] * 8)))
    with pytest.raises(ValidationBudgetExceeded):
        assert_validation_budget(request, config, phase="dispatch")
    assert len(request.validation.commands) == 8


def test_an_accepted_envelope_is_returned_untouched(config, git_repo: Path):
    request = _request(git_repo, execution=1_800, validation=_commands(600, 600))
    assert_validation_budget(request, config, phase="dispatch")
    assert [c.timeout_seconds for c in request.validation.commands] == [600, 600]
    assert request.execution.timeout_seconds == 1_800


# ---------------------------------------------------------------------------
# 5. The typed error carries bounded facts and leaks nothing
# ---------------------------------------------------------------------------


def test_the_error_is_a_registered_dispatcher_error():
    assert issubclass(ValidationBudgetExceeded, DispatcherError)
    assert ValidationBudgetExceeded.code == "ValidationBudgetExceeded"
    assert "ValidationBudgetExceeded" in ERROR_CODES


def test_the_refusal_names_the_contributing_commands(config, git_repo: Path):
    commands = [
        ValidationCommand(argv=["pytest", "-q"], timeout_seconds=3_600),
        ValidationCommand(argv=["/usr/bin/npm", "test"], timeout_seconds=3_000),
        ValidationCommand(argv=["ruff", "check", "."], timeout_seconds=60),
    ]
    request = _request(git_repo, execution=3_600, validation=commands)
    with pytest.raises(ValidationBudgetExceeded) as exc:
        assert_validation_budget(request, config, phase="dispatch")

    contributing = exc.value.details["contributing_commands"]
    assert [c["program"] for c in contributing] == ["pytest", "npm", "ruff"]
    assert [c["timeout_seconds"] for c in contributing] == [3_600, 3_000, 60]
    assert [c["index"] for c in contributing] == [0, 1, 2]
    assert exc.value.details["validation_command_count"] == 3
    assert exc.value.details["validation_total_seconds"] == 6_660


def test_the_refusal_leaks_no_envelope_contents(config, git_repo: Path):
    secret = "ghp_THISMUSTNEVERAPPEARINANERROR"
    commands = [
        ValidationCommand(
            argv=["pytest", "--token", secret, "--url", "https://internal.example"],
            timeout_seconds=3_600,
        ),
        ValidationCommand(argv=["make", "check"], timeout_seconds=3_600),
    ]
    request = TaskRequest(
        repository={"root": str(git_repo), "base_ref": "a" * 40},
        task={
            "objective": f"Rotate the credential {secret}",
            "context": f"the old value was {secret}",
            "acceptance_criteria": [f"no {secret} remains"],
        },
        execution=ExecutionSpec(timeout_seconds=3_600),
        validation=ValidationSpec(commands=commands),
    )
    with pytest.raises(ValidationBudgetExceeded) as exc:
        assert_validation_budget(request, config, phase="dispatch")

    rendered = json.dumps(exc.value.to_payload())
    assert secret not in rendered
    assert "Rotate the credential" not in rendered
    assert "internal.example" not in rendered
    assert "--token" not in rendered
    # The program name is the only thing taken from argv, and only its basename.
    assert '"program": "pytest"' in rendered


def test_the_refusal_facts_are_bounded(config, git_repo: Path):
    request = _request(
        git_repo,
        execution=3_600,
        validation=_commands(*([3_600] * 32), program="a" * 300),
    )
    with pytest.raises(ValidationBudgetExceeded) as exc:
        assert_validation_budget(request, config, phase="dispatch")
    contributing = exc.value.details["contributing_commands"]
    assert len(contributing) <= MAX_VALIDATION_COMMANDS
    assert all(len(c["program"]) <= 64 for c in contributing)
    assert len(json.dumps(exc.value.to_payload())) < 8_192


def test_the_refusal_states_the_phase_it_refused_in(config, git_repo: Path):
    request = _request(git_repo, execution=3_600, validation=_commands(*([3_600] * 4)))
    with pytest.raises(ValidationBudgetExceeded) as exc:
        assert_validation_budget(request, config, phase="resume")
    assert exc.value.details["phase"] == "resume"


def test_the_refusal_offers_remediation_that_does_not_suggest_shrinking_silently(
    config, git_repo: Path
):
    request = _request(git_repo, execution=3_600, validation=_commands(*([3_600] * 4)))
    with pytest.raises(ValidationBudgetExceeded) as exc:
        assert_validation_budget(request, config, phase="dispatch")
    assert exc.value.remediation
    assert not exc.value.retryable


# ---------------------------------------------------------------------------
# 6. The clamped execution timeout is the one that counts
# ---------------------------------------------------------------------------


def test_the_budget_counts_the_clamped_execution_timeout_not_the_requested_one(
    config, git_repo: Path
):
    """A caller may ask for 86,400 s; ``clamp_timeout`` makes it 3,600 s."""
    request = _request(git_repo, execution=86_400, validation=_commands(600))
    facts = validation_budget_facts(request, config, phase="dispatch")
    assert facts["execution_timeout_seconds"] == config.dispatcher.max_timeout_seconds
    assert facts["declared_total_seconds"] == 3_600 + 600
    assert_validation_budget(request, config, phase="dispatch")


def test_an_explicit_effective_timeout_overrides_the_envelope_value(
    config, git_repo: Path
):
    """The resume path supplies ``ResumePlan.timeout_seconds``, already clamped."""
    request = _request(git_repo, execution=60, validation=_commands(600))
    facts = validation_budget_facts(
        request, config, phase="resume", execution_timeout_seconds=3_600
    )
    assert facts["execution_timeout_seconds"] == 3_600
    assert facts["declared_total_seconds"] == 4_200


def test_an_envelope_is_checked_the_same_way_a_request_is(config, git_repo: Path):
    request = _request(git_repo, execution=3_600, validation=_commands(600))
    envelope = TaskEnvelope.from_request(
        request, canonical_root=str(git_repo), base_commit="0" * 40
    )
    assert validation_budget_facts(envelope, config, phase="dispatch") == (
        validation_budget_facts(request, config, phase="dispatch")
    )


# ---------------------------------------------------------------------------
# 7. The wait invariant Lane J established is preserved
# ---------------------------------------------------------------------------


def test_waiting_still_has_no_timeout_of_its_own():
    """The budget bounds declared WORK, never the wait (Lane J §7, Lane K §2.6).

    A waiter-side deadline would turn the MCP tool timeout into a correctness
    bound; the whole point of ``RunRegistry`` is that it is only a latency one.
    """
    source = inspect.getsource(waiting)
    body = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    # ``drain`` takes a caller-supplied timeout for tests and shutdown; the
    # request path must not.
    assert "asyncio.wait_for" not in body.split("async def drain")[0]
    assert "asyncio.shield(task)" in body
    run_source = inspect.getsource(waiting.RunRegistry.run)
    assert "timeout" not in run_source


def test_the_budget_never_reaches_the_registry():
    """``RunRegistry`` knows nothing about budgets: they are refused earlier."""
    source = inspect.getsource(waiting)
    assert "max_total_seconds" not in source
    assert "ValidationBudgetExceeded" not in source
