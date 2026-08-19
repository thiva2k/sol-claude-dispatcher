"""Tests for independent dispatcher validation (brief §9, §17, §31)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from sol_claude_dispatcher.models import (
    TaskEnvelope,
    TaskRequest,
    TestReport,
    ValidationCommand,
    ValidationResult,
    WorkerResult,
)
from sol_claude_dispatcher.validation import (
    compare_claims_to_validation,
    run_validation_command,
    run_validations,
)
from sol_claude_dispatcher import validation as validation_module
from sol_claude_dispatcher.config import load_config_from_mapping

TRUE_BIN = shutil.which("true") or "/bin/true"
FALSE_BIN = shutil.which("false") or "/bin/false"
SLEEP_BIN = shutil.which("sleep") or "/bin/sleep"


def _config(tmp_path: Path, *, run_dispatcher_validation: bool = True):
    return load_config_from_mapping(
        {
            "dispatcher": {
                "state_dir": "./state",
                "default_timeout_seconds": 1800,
                "max_timeout_seconds": 3600,
                "default_max_turns": 40,
                "default_max_resume_count": 4,
            },
            "models": {"sonnet": "sonnet", "opus": "opus", "fable": "fable"},
            "routing": {"default_model": "sonnet"},
            "security": {
                "max_dispatch_depth": 1,
                "allowed_repository_roots": [str(tmp_path)],
            },
            "validation": {"run_dispatcher_validation": run_dispatcher_validation},
        },
        source_path=None,
        project_root=str(tmp_path),
    )


def _envelope(git_repo: Path, argv_list: list[list[str]]) -> TaskEnvelope:
    request = TaskRequest.model_validate(
        {
            "repository": {"root": str(git_repo), "base_ref": "HEAD"},
            "task": {"kind": "implementation", "objective": "Do the thing."},
            "validation": {
                "commands": [{"argv": argv, "timeout_seconds": 5} for argv in argv_list]
            },
        }
    )
    return TaskEnvelope.from_request(
        request,
        canonical_root=str(git_repo.resolve()),
        base_commit="a" * 40,
    )


# ---------------------------------------------------------------------------
# run_validation_command — real subprocess exec, argv only
# ---------------------------------------------------------------------------


async def test_passing_command(tmp_path):
    cmd = ValidationCommand(argv=[TRUE_BIN], timeout_seconds=5)
    result = await run_validation_command(cmd, tmp_path)
    assert isinstance(result, ValidationResult)
    assert result.source == "dispatcher"
    assert result.exit_code == 0
    assert result.passed is True
    assert result.timed_out is False
    assert result.argv == [TRUE_BIN]


async def test_failing_command(tmp_path):
    cmd = ValidationCommand(argv=[FALSE_BIN], timeout_seconds=5)
    result = await run_validation_command(cmd, tmp_path)
    assert result.exit_code == 1
    assert result.passed is False
    assert result.timed_out is False


async def test_timing_out_command_is_sigtermed(tmp_path):
    cmd = ValidationCommand(argv=[SLEEP_BIN, "10"], timeout_seconds=1)
    result = await run_validation_command(cmd, tmp_path)
    assert result.timed_out is True
    assert result.passed is False
    # sleep dies promptly on SIGTERM; duration should be close to the 1s
    # timeout, nowhere near the full 10s sleep or the 5s SIGKILL grace period.
    assert result.duration_ms < 4000


async def test_timing_out_command_that_ignores_sigterm_gets_sigkilled(tmp_path, monkeypatch):
    monkeypatch.setattr(validation_module, "_GRACE_SECONDS", 0.3)
    script = (
        "import signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(10)"
    )
    cmd = ValidationCommand(argv=[sys.executable, "-c", script], timeout_seconds=1)
    result = await run_validation_command(cmd, tmp_path)
    assert result.timed_out is True
    assert result.passed is False
    assert "SIGKILL" in result.stderr_tail
    # 1s timeout + two ~0.3s grace windows, well under the ignored 10s sleep.
    assert result.duration_ms < 3000


async def test_output_is_bounded_to_tail(tmp_path):
    script = "print('x' * 20000)"
    cmd = ValidationCommand(argv=[sys.executable, "-c", script], timeout_seconds=5)
    result = await run_validation_command(cmd, tmp_path)
    assert result.exit_code == 0
    assert len(result.stdout_tail) <= 8 * 1024
    assert result.stdout_tail == result.stdout_tail[-8 * 1024 :]
    assert result.stdout_tail.endswith("x")


async def test_missing_binary_reports_failure_without_raising(tmp_path):
    cmd = ValidationCommand(argv=["/no/such/binary/anywhere"], timeout_seconds=5)
    result = await run_validation_command(cmd, tmp_path)
    assert result.exit_code is None
    assert result.passed is False
    assert result.timed_out is False


async def test_shell_metacharacters_are_never_interpreted(tmp_path):
    # A single argv string containing shell metacharacters must be treated as
    # one literal program name — never handed to a shell for interpretation.
    marker = tmp_path / "pwned"
    argv = [f"true; touch {marker}"]
    cmd = ValidationCommand(argv=argv, timeout_seconds=5)
    result = await run_validation_command(cmd, tmp_path)
    assert result.exit_code is None  # no such literal binary — nothing ran
    assert not marker.exists()


async def test_worker_supplied_command_object_is_rejected(tmp_path):
    class FakeWorkerCommand:
        """Shaped like a ValidationCommand but not sourced from the envelope."""

        argv = [TRUE_BIN]
        timeout_seconds = 5

    with pytest.raises(TypeError):
        await run_validation_command(FakeWorkerCommand(), tmp_path)  # type: ignore[arg-type]


async def test_plain_dict_command_is_rejected(tmp_path):
    with pytest.raises(TypeError):
        await run_validation_command({"argv": [TRUE_BIN], "timeout_seconds": 5}, tmp_path)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# run_validations — envelope is the only source of truth
# ---------------------------------------------------------------------------


async def test_run_validations_executes_envelope_commands(git_repo, tmp_path):
    config = _config(tmp_path)
    envelope = _envelope(git_repo, [[TRUE_BIN], [FALSE_BIN]])
    results = await run_validations(envelope, git_repo, config)
    assert [r.exit_code for r in results] == [0, 1]
    assert [r.passed for r in results] == [True, False]


async def test_run_validations_disabled_by_config_returns_empty(git_repo, tmp_path):
    config = _config(tmp_path, run_dispatcher_validation=False)
    envelope = _envelope(git_repo, [[TRUE_BIN]])
    results = await run_validations(envelope, git_repo, config)
    assert results == []


async def test_run_validations_continues_after_a_failure(git_repo, tmp_path):
    config = _config(tmp_path)
    envelope = _envelope(git_repo, [[FALSE_BIN], [TRUE_BIN]])
    results = await run_validations(envelope, git_repo, config)
    # Both commands ran to completion even though the first failed.
    assert len(results) == 2
    assert results[0].passed is False
    assert results[1].passed is True


async def test_run_validations_ignores_worker_supplied_commands(git_repo, tmp_path):
    # The envelope is authored with one trusted command. A worker result
    # cannot express "commands" at all (no such field on WorkerResult), so
    # this test proves the only commands that ever run are the envelope's —
    # there is no code path by which a worker's own claimed test commands
    # could be substituted in.
    config = _config(tmp_path)
    envelope = _envelope(git_repo, [[TRUE_BIN]])
    worker_result = WorkerResult(
        status="completed",
        summary="claims to have run something else entirely",
        tests=[TestReport(command=f"{FALSE_BIN}", status="failed", exit_code=1)],
        needs_review=True,
    )
    assert not hasattr(worker_result, "commands")
    results = await run_validations(envelope, git_repo, config)
    assert len(results) == 1
    assert results[0].argv == [TRUE_BIN]


# ---------------------------------------------------------------------------
# compare_claims_to_validation — the corroborated/uncorroborated/contradicted matrix
# ---------------------------------------------------------------------------


def _worker_with_tests(*tests: TestReport) -> WorkerResult:
    return WorkerResult(
        status="completed",
        summary="did some things",
        tests=list(tests),
        needs_review=True,
    )


def test_compare_no_worker_result_returns_empty():
    assert compare_claims_to_validation(None, []) == []


def test_compare_corroborated_both_passed():
    worker_result = _worker_with_tests(
        TestReport(command="pytest -q", status="passed", exit_code=0)
    )
    validation_results = [
        ValidationResult(argv=["pytest", "-q"], exit_code=0, passed=True, duration_ms=10)
    ]
    [comparison] = compare_claims_to_validation(worker_result, validation_results)
    assert comparison["verdict"] == "corroborated"
    assert comparison["validation_found"] is True
    assert comparison["validation_passed"] is True


def test_compare_corroborated_both_failed():
    worker_result = _worker_with_tests(
        TestReport(command="pytest -q", status="failed", exit_code=1)
    )
    validation_results = [
        ValidationResult(argv=["pytest", "-q"], exit_code=1, passed=False, duration_ms=10)
    ]
    [comparison] = compare_claims_to_validation(worker_result, validation_results)
    assert comparison["verdict"] == "corroborated"
    assert comparison["validation_passed"] is False


def test_compare_contradicted_claim_passed_but_validation_failed():
    worker_result = _worker_with_tests(
        TestReport(command="pytest -q", status="passed", exit_code=0)
    )
    validation_results = [
        ValidationResult(argv=["pytest", "-q"], exit_code=1, passed=False, duration_ms=10)
    ]
    [comparison] = compare_claims_to_validation(worker_result, validation_results)
    assert comparison["verdict"] == "contradicted"


def test_compare_contradicted_claim_failed_but_validation_passed():
    worker_result = _worker_with_tests(
        TestReport(command="pytest -q", status="failed", exit_code=1)
    )
    validation_results = [
        ValidationResult(argv=["pytest", "-q"], exit_code=0, passed=True, duration_ms=10)
    ]
    [comparison] = compare_claims_to_validation(worker_result, validation_results)
    assert comparison["verdict"] == "contradicted"


def test_compare_uncorroborated_no_matching_validation_command():
    worker_result = _worker_with_tests(
        TestReport(command="pytest -q tests/other", status="passed", exit_code=0)
    )
    validation_results = [
        ValidationResult(argv=["pytest", "-q"], exit_code=0, passed=True, duration_ms=10)
    ]
    [comparison] = compare_claims_to_validation(worker_result, validation_results)
    assert comparison["verdict"] == "uncorroborated"
    assert comparison["validation_found"] is False


def test_compare_uncorroborated_when_worker_claims_skipped():
    worker_result = _worker_with_tests(
        TestReport(command="pytest -q", status="skipped")
    )
    validation_results = [
        ValidationResult(argv=["pytest", "-q"], exit_code=0, passed=True, duration_ms=10)
    ]
    [comparison] = compare_claims_to_validation(worker_result, validation_results)
    assert comparison["verdict"] == "uncorroborated"


def test_compare_uncorroborated_when_no_validation_ran_at_all():
    worker_result = _worker_with_tests(
        TestReport(command="pytest -q", status="passed", exit_code=0)
    )
    [comparison] = compare_claims_to_validation(worker_result, [])
    assert comparison["verdict"] == "uncorroborated"
    assert comparison["validation_found"] is False


def test_compare_multiple_claims_independent_verdicts():
    worker_result = _worker_with_tests(
        TestReport(command="pytest -q", status="passed", exit_code=0),
        TestReport(command="ruff check .", status="passed", exit_code=0),
    )
    validation_results = [
        ValidationResult(argv=["pytest", "-q"], exit_code=0, passed=True, duration_ms=10),
        ValidationResult(argv=["ruff", "check", "."], exit_code=1, passed=False, duration_ms=5),
    ]
    comparisons = compare_claims_to_validation(worker_result, validation_results)
    verdicts = {c["command"]: c["verdict"] for c in comparisons}
    assert verdicts["pytest -q"] == "corroborated"
    assert verdicts["ruff check ."] == "contradicted"
