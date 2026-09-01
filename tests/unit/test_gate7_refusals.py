from __future__ import annotations

import json
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import InvalidTaskEnvelope, StateCorruption
from sol_claude_dispatcher.models import TaskEnvelope, TaskRequest
from sol_claude_dispatcher.state import TaskStore


def _record(index: int = 1) -> dict[str, object]:
    return {
        "at": f"2026-08-29T00:00:0{index}+00:00",
        "tool": "dispatch_claude_task",
        "phase": "PREPARE",
        "code": "RepositoryAdministrationUnestablished",
        "message": "Repository administration is not established.",
        "details": {"index": index},
        "remediation": "Run trust-repo-admin.py.",
    }


def test_pretask_refusal_creates_no_task_directory(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks")
    key = "a" * 64

    path = store.append_refusal(_record(), repository_key=key)

    assert path == tmp_path / "tasks" / "_refusals" / "repositories" / f"{key}.jsonl"
    assert store.list_tasks() == []
    assert store.load_refusals(repository_key=key) == [_record()]


def test_task_refusal_does_not_mutate_state_json(
    valid_request_dict: dict, tmp_path: Path
) -> None:
    envelope = TaskEnvelope.from_request(
        TaskRequest(**valid_request_dict),
        canonical_root="/tmp/canonical/repo",
        base_commit="a" * 40,
    )
    store = TaskStore(tmp_path / "tasks")
    store.create(envelope)
    state_path = store.task_dir(envelope.task_id) / "state.json"
    before = state_path.read_bytes()

    store.append_refusal(_record(), task_id=envelope.task_id)

    assert state_path.read_bytes() == before
    assert store.load_refusals(task_id=envelope.task_id) == [_record()]


def test_refusal_journal_is_append_only_and_bounded(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks")
    key = "b" * 64
    for index in range(1, 4):
        store.append_refusal(_record(index), repository_key=key)

    assert [r["details"] for r in store.load_refusals(repository_key=key, limit=2)] == [
        {"index": 2},
        {"index": 3},
    ]


def test_refusal_target_is_unambiguous(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks")
    with pytest.raises(InvalidTaskEnvelope):
        store.append_refusal(_record())
    with pytest.raises(InvalidTaskEnvelope):
        store.append_refusal(_record(), task_id="task", repository_key="c" * 64)


def test_corrupt_refusal_journal_fails_closed(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks")
    key = "d" * 64
    path = store.append_refusal(_record(), repository_key=key)
    path.write_text(json.dumps(_record()) + "\nnot-json\n")

    with pytest.raises(StateCorruption):
        store.load_refusals(repository_key=key)


def test_refusal_journal_symlink_is_not_followed(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks")
    key = "e" * 64
    path = store._refusal_path(task_id=None, repository_key=key)
    path.parent.mkdir(parents=True)
    target = tmp_path / "outside"
    target.write_text("untouched")
    path.symlink_to(target)

    with pytest.raises((StateCorruption, InvalidTaskEnvelope)):
        store.append_refusal(_record(), repository_key=key)
    assert target.read_text() == "untouched"
