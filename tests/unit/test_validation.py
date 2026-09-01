"""Tests for independent dispatcher validation (brief §9, §17, §31)."""

from __future__ import annotations

import hashlib
import json
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
from sol_claude_dispatcher.runner import measure_execve_transport
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
            "repository": {"root": str(git_repo), "base_ref": "a" * 40},
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
    journal = tmp_path / "validation-invocations.jsonl"
    result = await run_validation_command(cmd, tmp_path, journal_path=journal)
    assert result.timed_out is True
    assert result.passed is False
    assert "SIGKILL" in result.stderr_tail
    # 1s timeout + two ~0.3s grace windows, well under the ignored 10s sleep.
    assert result.duration_ms < 3000
    completion = json.loads(journal.read_text().splitlines()[-1])
    assert completion["sigkill"] is True
    assert completion["timed_out"] is True
    assert completion["pgid"] == completion["pid"]


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
    journal = tmp_path / "validation-invocations.jsonl"
    result = await run_validation_command(cmd, tmp_path, journal_path=journal)
    assert result.exit_code is None
    assert result.passed is False
    assert result.timed_out is False
    attempt, completion = [
        json.loads(line) for line in journal.read_text().splitlines()
    ]
    assert "returncode" not in attempt
    assert completion["returncode"] is None
    assert completion["pid"] is None
    assert completion["pgid"] is None
    assert completion["sigkill"] is False


async def test_validation_envp_exact_element_boundary_spawns_once(
    tmp_path, monkeypatch
):
    """131,071 encoded KEY=value bytes are legal and reach execve once."""

    original_spawn = validation_module.asyncio.create_subprocess_exec
    spawn_count = 0

    async def counted_spawn(*args, **kwargs):
        nonlocal spawn_count
        spawn_count += 1
        return await original_spawn(*args, **kwargs)

    monkeypatch.setattr(
        validation_module.asyncio, "create_subprocess_exec", counted_spawn
    )
    key = "BOUNDARY"
    value = "v" * (131_071 - len(key) - 1)
    result = await run_validation_command(
        ValidationCommand(argv=[TRUE_BIN], timeout_seconds=5),
        tmp_path,
        env={key: value},
    )

    assert result.passed is True
    assert spawn_count == 1


async def test_validation_envp_one_byte_over_element_boundary_is_refused_without_spawn(
    tmp_path, monkeypatch
):
    """131,072 encoded KEY=value bytes refuse before the subprocess call."""

    original_spawn = validation_module.asyncio.create_subprocess_exec
    spawn_count = 0

    async def counted_spawn(*args, **kwargs):
        nonlocal spawn_count
        spawn_count += 1
        return await original_spawn(*args, **kwargs)

    monkeypatch.setattr(
        validation_module.asyncio, "create_subprocess_exec", counted_spawn
    )
    key = "ENV_SECRET_SENTINEL"
    value = "s" * (131_072 - len(key) - 1)
    journal = tmp_path / "validation-invocations.jsonl"
    result = await run_validation_command(
        ValidationCommand(argv=[TRUE_BIN], timeout_seconds=5),
        tmp_path,
        env={key: value},
        journal_path=journal,
    )

    assert result.exit_code is None
    assert result.passed is False
    assert result.timed_out is False
    assert "refused before spawn" in result.stderr_tail
    assert spawn_count == 0
    raw_journal = journal.read_text()
    assert key not in raw_journal
    assert value[:64] not in raw_journal
    row = json.loads(raw_journal)
    assert row["event"] == "spawn_refused"
    assert row["refusal_code"] == "ContextTooLarge"
    assert row["refusal_source"] == "execve_preflight"
    assert row["binding_constraint"] == "envp_element"
    assert row["largest_envp_element_bytes"] == 131_072
    assert row["oversized_envp_element_count"] == 1
    assert row["pid"] is None
    assert row["pgid"] is None


async def test_validation_aggregate_boundary_and_plus_one_audit_spawn_count(
    tmp_path, monkeypatch
):
    """The NUL-and-pointer aggregate accepts equality and refuses +1."""

    original_spawn = validation_module.asyncio.create_subprocess_exec
    spawn_count = 0

    async def counted_spawn(*args, **kwargs):
        nonlocal spawn_count
        spawn_count += 1
        return await original_spawn(*args, **kwargs)

    monkeypatch.setattr(
        validation_module.asyncio, "create_subprocess_exec", counted_spawn
    )
    arg_max = 10_000

    def constrained_measure(argv, env):
        return measure_execve_transport(argv, env, arg_max_bytes=arg_max)

    monkeypatch.setattr(
        validation_module, "measure_execve_transport", constrained_measure
    )
    argv = [TRUE_BIN]
    empty_value = measure_execve_transport(
        argv, {"X": ""}, arg_max_bytes=arg_max
    )
    exact_value_size = empty_value.aggregate_limit_bytes - empty_value.total_bytes
    assert exact_value_size > 0

    exact_journal = tmp_path / "exact.jsonl"
    exact_result = await run_validation_command(
        ValidationCommand(argv=argv, timeout_seconds=5),
        tmp_path,
        env={"X": "x" * exact_value_size},
        journal_path=exact_journal,
    )
    refused_journal = tmp_path / "refused.jsonl"
    refused_result = await run_validation_command(
        ValidationCommand(argv=argv, timeout_seconds=5),
        tmp_path,
        env={"X": "x" * (exact_value_size + 1)},
        journal_path=refused_journal,
    )

    assert exact_result.passed is True
    assert refused_result.passed is False
    assert refused_result.exit_code is None
    assert spawn_count == 1
    exact_rows = [json.loads(line) for line in exact_journal.read_text().splitlines()]
    assert [row["event"] for row in exact_rows] == ["spawn_attempt", "completion"]
    refused_row = json.loads(refused_journal.read_text())
    assert refused_row["event"] == "spawn_refused"
    assert refused_row["binding_constraint"] == "aggregate"
    assert refused_row["total_bytes"] == refused_row["aggregate_limit_bytes"] + 1


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


async def test_validation_journal_is_non_authority_and_records_every_attempt(
    git_repo, tmp_path
):
    config = _config(tmp_path)
    envelope = _envelope(git_repo, [[TRUE_BIN], [FALSE_BIN]])
    journal = tmp_path / "run" / "validation-invocations.jsonl"

    results = await run_validations(
        envelope, git_repo, config, journal_path=journal
    )

    assert [result.exit_code for result in results] == [0, 1]
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    assert [(row["sequence"], row["event"]) for row in rows] == [
        (1, "spawn_attempt"),
        (1, "completion"),
        (2, "spawn_attempt"),
        (2, "completion"),
    ]
    assert all(row["domain"] == "trusted_validation" for row in rows)
    assert all(row["authority"] is False for row in rows)
    assert all(row["phase"] == "POST_WORKER" for row in rows)
    assert all(row["cwd_role"] == "task_worktree" for row in rows)
    assert all(row["env_policy"] == "validation_environment/1" for row in rows)
    assert all(row["pins_applied"] == [] for row in rows)
    assert all(row["start_new_session"] is True for row in rows)
    assert all(row["descendants_observed"] is None for row in rows)
    assert [row["program"] for row in rows] == ["true", "true", "false", "false"]
    assert all(row["argv_len"] == 1 for row in rows)
    assert all(row["is_git"] is False for row in rows)
    expected = hashlib.sha256(
        json.dumps([TRUE_BIN], separators=(",", ":")).encode("ascii")
    ).hexdigest()
    assert rows[0]["argv_sha256"] == expected
    assert rows[0]["index"] == 0
    assert rows[0]["pid"] is None
    assert rows[0]["pgid"] is None
    assert rows[0]["sigkill"] is False
    assert "returncode" not in rows[0]
    assert rows[1]["returncode"] == 0
    assert isinstance(rows[1]["pid"], int)
    assert rows[1]["pgid"] == rows[1]["pid"]
    assert rows[1]["sigkill"] is False


def test_git_validation_command_is_accepted_by_the_envelope_validator(git_repo):
    envelope = _envelope(git_repo, [["git", "diff", "--exit-code"]])
    assert envelope.validation.commands[0].argv == ["git", "diff", "--exit-code"]


@pytest.mark.parametrize("absolute", [False, True])
async def test_git_is_a_legal_validation_command_and_is_journalled_without_authority(
    git_repo, tmp_path, absolute
):
    git_binary = shutil.which("git")
    if git_binary is None:
        pytest.skip("git is not installed")
    argv = [git_binary if absolute else "git", "diff", "--exit-code"]
    journal = tmp_path / "run" / "validation-invocations.jsonl"

    result = await run_validation_command(
        ValidationCommand(argv=argv, timeout_seconds=5),
        git_repo,
        journal_path=journal,
    )

    assert result.exit_code is not None
    rows = [json.loads(line) for line in journal.read_text().splitlines()]
    independently_computed_hash = hashlib.sha256(
        json.dumps(argv, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    assert {row["argv_sha256"] for row in rows} == {independently_computed_hash}
    assert all(row["program"] == "git" for row in rows)
    assert all(row["is_git"] is True for row in rows)
    assert all(row["authority"] is False for row in rows)
    assert all(row["pins_applied"] == [] for row in rows)


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
