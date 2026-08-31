"""Gate 7's declared Git order, pins, establishment interlock and journal."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import (
    ForbiddenGitInvocation,
    GitArgvPinDisplaced,
    GitBeforeEstablishment,
    InternalDispatcherError,
)
from sol_claude_dispatcher.evidence.git_order import (
    DECLARED_GIT_ORDER,
    DISPATCHER_GIT_ENV,
    EMPTY_BY_DECLARATION,
    GIT_ENV_ALLOWLIST,
    PIN_NAMES,
    CwdRole,
    GitInvocationJournal,
    GitPath,
    PinBlock,
    execute_declared_git,
    prepare_git_invocation,
    validate_row_args,
)
from sol_claude_dispatcher.phase import ExecutionPhase, begin_tool_execution
from tests.support.spawn_journal import capture_spawns


EXPECTED_ENV = {
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
}


def test_git_child_environment_is_exact_and_immutable() -> None:
    assert GIT_ENV_ALLOWLIST == ()
    assert dict(DISPATCHER_GIT_ENV) == EXPECTED_ENV
    assert set(DISPATCHER_GIT_ENV) == set(EXPECTED_ENV)
    with pytest.raises(TypeError):
        DISPATCHER_GIT_ENV["GIT_GRAFT_FILE"] = "/tmp/decoy"  # type: ignore[index]


def test_pin_block_is_frozen_ordered_and_injects_the_sealed_hooks_path() -> None:
    pins = PinBlock("/dispatcher/sealed/empty-hooks")
    assert pins.argv == (
        "-c",
        "core.hooksPath=/dispatcher/sealed/empty-hooks",
        "-c",
        "core.commitGraph=false",
        "-c",
        "core.multiPackIndex=false",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "core.quotePath=false",
        "--no-pager",
    )
    assert pins.names == PIN_NAMES
    with pytest.raises(dataclasses.FrozenInstanceError):
        pins.empty_hooks_path = "/tmp/other"  # type: ignore[misc]
    with pytest.raises(ValueError):
        PinBlock("relative/hooks")


def test_declared_orders_are_frozen_data_and_review_is_explicitly_empty() -> None:
    dispatch = DECLARED_GIT_ORDER[GitPath.DISPATCH]
    resume = DECLARED_GIT_ORDER[GitPath.RESUME]

    assert tuple(row.row_id for row in dispatch) == (
        "G1",
        "G2",
        "G3",
        "G4",
        "G8",
        "G9",
    )
    assert tuple(row.row_id for row in resume) == ("G1_PRIME",)
    assert DECLARED_GIT_ORDER[GitPath.REVIEW] is EMPTY_BY_DECLARATION
    assert EMPTY_BY_DECLARATION != ()
    with pytest.raises(TypeError):
        DECLARED_GIT_ORDER[GitPath.REVIEW] = ()  # type: ignore[index]


@pytest.mark.parametrize(
    "row_args",
    [
        ("-c", "core.commitGraph=true"),
        ("-ccore.commitGraph=true",),
        ("--config-env=x=y",),
        ("-C/tmp/repo",),
        ("--git-dir=/tmp/repo",),
        ("--work-tree", "/tmp/repo"),
        ("--namespace=decoy",),
        ("--exec-path=/tmp",),
        ("--no-pager",),
    ],
)
def test_caller_cannot_displace_the_terminal_pin_prefix(
    row_args: tuple[str, ...],
) -> None:
    with pytest.raises(GitArgvPinDisplaced):
        validate_row_args("rev-parse", row_args)


def test_prepared_argv_has_absolute_git_then_pins_then_declared_subcommand(
    tmp_path: Path,
) -> None:
    journal = GitInvocationJournal(tmp_path / "git-invocations.jsonl")
    pins = PinBlock("/dispatcher/sealed/empty-hooks")
    with begin_tool_execution("dispatch"):
        journal.establish(GitPath.DISPATCH)
        prepared = prepare_git_invocation(
            journal=journal,
            path=GitPath.DISPATCH,
            row_id="G1",
            git_executable="/opt/git/bin/git",
            pin_block=pins,
            cwd_role=CwdRole.PRIMARY,
            values={"base_commit": "a" * 40},
        )

    assert prepared.argv == (
        "/opt/git/bin/git",
        *pins.argv,
        "rev-parse",
        "--verify",
        "--end-of-options",
        f"{'a' * 40}^{{commit}}",
    )
    assert dict(prepared.env) == EXPECTED_ENV


def test_git_is_refused_before_establishment_and_outside_prepare(tmp_path: Path) -> None:
    journal = GitInvocationJournal(tmp_path / "git-invocations.jsonl")
    kwargs = {
        "journal": journal,
        "path": GitPath.DISPATCH,
        "row_id": "G1",
        "git_executable": "/usr/bin/git",
        "pin_block": PinBlock("/sealed/hooks"),
        "cwd_role": CwdRole.PRIMARY,
        "values": {"base_commit": "b" * 40},
    }

    with begin_tool_execution("dispatch") as execution:
        with pytest.raises(GitBeforeEstablishment):
            prepare_git_invocation(**kwargs)
        journal.establish(GitPath.DISPATCH)
        execution.enter(ExecutionPhase.RESERVE)
        with pytest.raises(GitBeforeEstablishment):
            prepare_git_invocation(**kwargs)


def test_establishment_does_not_transfer_to_another_tool_execution(tmp_path: Path) -> None:
    journal = GitInvocationJournal(tmp_path / "git-invocations.jsonl")
    with begin_tool_execution("dispatch"):
        journal.establish(GitPath.DISPATCH)

    with begin_tool_execution("dispatch"):
        with pytest.raises(GitBeforeEstablishment):
            prepare_git_invocation(
                journal=journal,
                path=GitPath.DISPATCH,
                row_id="G1",
                git_executable="/usr/bin/git",
                pin_block=PinBlock("/sealed/hooks"),
                cwd_role=CwdRole.PRIMARY,
                values={"base_commit": "c" * 40},
            )


def test_review_cannot_establish_or_prepare_a_git_invocation(tmp_path: Path) -> None:
    journal = GitInvocationJournal(tmp_path / "git-invocations.jsonl")
    with begin_tool_execution("review"):
        with pytest.raises(ForbiddenGitInvocation):
            journal.establish(GitPath.REVIEW)
        with pytest.raises(ForbiddenGitInvocation):
            prepare_git_invocation(
                journal=journal,
                path=GitPath.REVIEW,
                row_id="anything",
                git_executable="/usr/bin/git",
                pin_block=PinBlock("/sealed/hooks"),
                cwd_role=CwdRole.PRIMARY,
            )


def test_fake_runner_records_append_only_monotone_rows(tmp_path: Path) -> None:
    path = tmp_path / "git-invocations.jsonl"
    journal = GitInvocationJournal(path)
    calls: list[tuple[tuple[str, ...], str, dict[str, str]]] = []

    class Result:
        returncode = 0

    def fake_runner(argv, *, cwd, env):
        calls.append((tuple(argv), str(cwd), dict(env)))
        return Result()

    common = {
        "journal": journal,
        "path": GitPath.DISPATCH,
        "git_executable": "/usr/bin/git",
        "pin_block": PinBlock("/sealed/hooks"),
        "cwd": tmp_path,
        "cwd_role": CwdRole.PRIMARY,
        "runner": fake_runner,
    }
    with begin_tool_execution("dispatch"):
        marker = journal.establish(GitPath.DISPATCH)
        first = execute_declared_git(
            **common, row_id="G1", values={"base_commit": "d" * 40}
        )
        before = path.read_bytes()
        second = execute_declared_git(
            **common, row_id="G2", values={"base_commit": "d" * 40}
        )

    records = GitInvocationJournal(path).records()
    assert [record.seq for record in records] == [1, 2, 3]
    assert [record.event for record in records] == ["establishment", "git", "git"]
    assert [record.permitted_by for record in records] == [
        "PREPARE_ADMIN_GATE",
        "G1",
        "G2",
    ]
    assert marker.seq < first.journal_record.seq < second.journal_record.seq
    assert path.read_bytes().startswith(before)
    assert len(calls) == 2
    assert calls[0][2] == EXPECTED_ENV


def test_declared_runtime_order_cannot_regress_or_repeat(tmp_path: Path) -> None:
    journal = GitInvocationJournal(tmp_path / "git-invocations.jsonl")

    class Result:
        returncode = 0

    def fake_runner(argv, *, cwd, env):
        return Result()

    common = {
        "journal": journal,
        "path": GitPath.DISPATCH,
        "git_executable": "/usr/bin/git",
        "pin_block": PinBlock("/sealed/hooks"),
        "cwd": tmp_path,
        "cwd_role": CwdRole.PRIMARY,
        "runner": fake_runner,
    }
    with begin_tool_execution("dispatch"):
        journal.establish(GitPath.DISPATCH)
        execute_declared_git(
            **common, row_id="G2", values={"base_commit": "e" * 40}
        )
        with pytest.raises(ForbiddenGitInvocation):
            execute_declared_git(
                **common, row_id="G1", values={"base_commit": "e" * 40}
            )
        with pytest.raises(ForbiddenGitInvocation):
            execute_declared_git(
                **common, row_id="G2", values={"base_commit": "e" * 40}
            )


def test_runner_protocol_failure_is_still_journaled(tmp_path: Path) -> None:
    journal = GitInvocationJournal(tmp_path / "git-invocations.jsonl")

    def malformed_runner(argv, *, cwd, env):
        return object()

    with begin_tool_execution("resume"):
        journal.establish(GitPath.RESUME)
        with pytest.raises(InternalDispatcherError, match="integer return code"):
            execute_declared_git(
                journal=journal,
                path=GitPath.RESUME,
                row_id="G1_PRIME",
                git_executable="/usr/bin/git",
                pin_block=PinBlock("/sealed/hooks"),
                cwd=tmp_path,
                cwd_role=CwdRole.PRIMARY,
                runner=malformed_runner,
            )

    records = journal.records()
    assert [record.event for record in records] == ["establishment", "git"]
    assert records[-1].returncode is None
    assert records[-1].permitted_by == "G1_PRIME"


def test_spawn_support_observes_the_whole_event_family_without_real_spawn() -> None:
    with capture_spawns() as observed:
        sys.audit(
            "subprocess.Popen",
            "/sealed/git",
            ("/sealed/git", "--version"),
            None,
            {},
        )
        sys.audit(
            "os.posix_spawn",
            "/sealed/git",
            ("/sealed/git", "--version"),
            {},
        )

    assert {event.name for event in observed} == {
        "subprocess.Popen",
        "os.posix_spawn",
    }
    assert all(event.argv == ("/sealed/git", "--version") for event in observed)


def test_journal_lines_are_canonical_json_without_full_argv(tmp_path: Path) -> None:
    journal = GitInvocationJournal(tmp_path / "git-invocations.jsonl")
    with begin_tool_execution("resume"):
        journal.establish(GitPath.RESUME)
    rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
    assert rows[0]["seq"] == 1
    assert "argv" not in rows[0]
