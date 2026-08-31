"""Live Gate 7 closure controls over complete dispatcher tool paths.

These tests deliberately observe below the dispatcher's own journal.  The
spawn test watches CPython's process audit events, while the review test watches
file-open audit events.  Each observer is armed with a positive control in the
same test so an accidentally dead observer cannot prove an empty set.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

import pytest

import sol_claude_dispatcher.server as server_module
from sol_claude_dispatcher.evidence.worktreeauth import (
    authority_file_paths,
    decode_worktree_authority,
)
from sol_claude_dispatcher.git import resolve_git_executable
from tests.support.spawn_journal import SpawnEvent, capture_spawns


PROJECT_ROOT = Path(server_module.__file__).resolve().parents[2]


_ACTIVE_OPENS: ContextVar[list[str] | None] = ContextVar(
    "gate7_test_open_journal", default=None
)
_OPEN_HOOK_LOCK = threading.Lock()
_OPEN_HOOK_INSTALLED = False


def _open_audit_hook(name: str, args: tuple[object, ...]) -> None:
    if name != "open":
        return
    active = _ACTIVE_OPENS.get()
    if active is None or not args or not isinstance(args[0], (str, bytes)):
        return
    active.append(os.path.abspath(os.fsdecode(args[0])))


def _install_open_audit_hook() -> None:
    global _OPEN_HOOK_INSTALLED
    with _OPEN_HOOK_LOCK:
        if not _OPEN_HOOK_INSTALLED:
            sys.addaudithook(_open_audit_hook)
            _OPEN_HOOK_INSTALLED = True


@contextmanager
def _capture_opens() -> Iterator[list[str]]:
    _install_open_audit_hook()
    if _ACTIVE_OPENS.get() is not None:
        raise RuntimeError("open journals may not be nested")
    observed: list[str] = []
    token = _ACTIVE_OPENS.set(observed)
    real_os_open = os.open
    descriptor_paths: dict[int, str] = {}

    def capture_descriptor_open(
        path: str | bytes,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        raw = os.fsdecode(path)
        if dir_fd is None:
            resolved = os.path.abspath(raw)
            fd = real_os_open(path, flags, mode)
        else:
            parent = descriptor_paths.get(dir_fd)
            resolved = (
                os.path.abspath(os.path.join(parent, raw))
                if parent
                else os.path.abspath(raw)
            )
            fd = real_os_open(path, flags, mode, dir_fd=dir_fd)
        observed.append(resolved)
        descriptor_paths[fd] = resolved
        return fd

    os.open = capture_descriptor_open
    try:
        yield observed
    finally:
        os.open = real_os_open
        _ACTIVE_OPENS.reset(token)


def _real_paths_under(paths: list[str], root: Path) -> set[Path]:
    canonical_root = Path(os.path.realpath(root))
    observed: set[Path] = set()
    for raw in paths:
        candidate = Path(os.path.realpath(raw))
        try:
            candidate.relative_to(canonical_root)
        except ValueError:
            continue
        observed.add(candidate)
    return observed


def _assert_exact_review_authority_opens(
    observed: list[str],
    *,
    repository_root: Path,
    worktree_root: Path,
    expected: tuple[bytes, ...],
) -> None:
    expected_paths = {Path(os.path.realpath(os.fsdecode(path))) for path in expected}
    expected_repository = {
        path
        for path in expected_paths
        if path == Path(os.path.realpath(repository_root))
        or Path(os.path.realpath(repository_root)) in path.parents
    }
    expected_worktree = {
        path
        for path in expected_paths
        if path == Path(os.path.realpath(worktree_root))
        or Path(os.path.realpath(worktree_root)) in path.parents
    }
    assert _real_paths_under(observed, repository_root) == expected_repository
    assert _real_paths_under(observed, worktree_root) == expected_worktree


def _git_events(events: list[SpawnEvent]) -> list[tuple[int, SpawnEvent]]:
    return [
        (index, event)
        for index, event in enumerate(events)
        if event.executable is not None
        and Path(event.executable).name == "git"
    ]


def _git_suffixes(events: list[SpawnEvent]) -> list[tuple[str, ...]]:
    suffixes: list[tuple[str, ...]] = []
    hooks = PROJECT_ROOT / "config" / "empty-hooks"
    # PinBlock is intentionally not imported here: the test observes the exact
    # production argv rather than asking the argv-producing module to describe
    # its own output.
    pins = (
        "-c",
        f"core.hooksPath={hooks}",
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
    for _, event in _git_events(events):
        assert event.executable is not None
        assert os.path.isabs(event.executable)
        assert event.argv[0] == event.executable
        assert event.argv[1 : 1 + len(pins)] == pins
        suffixes.append(event.argv[1 + len(pins) :])
    return suffixes


def _assert_no_git_after_first_non_git_process(events: list[SpawnEvent]) -> None:
    git_indexes = {index for index, _ in _git_events(events)}
    process_indexes = [
        index
        for index, event in enumerate(events)
        if event.name == "subprocess.Popen"
    ]
    non_git = [index for index in process_indexes if index not in git_indexes]
    assert non_git, events
    assert all(index < non_git[0] for index in git_indexes), events


async def test_runtime_git_spawn_sets_and_post_worker_closure(
    dispatcher, request_payload, fake_env, monkeypatch
) -> None:
    """Dispatch is G1/G2/G3/G4/G8/G9, resume is G1', review is empty."""

    git = resolve_git_executable()
    with capture_spawns() as control:
        subprocess.run(
            [git, "--version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    assert [(event.executable, event.argv) for _, event in _git_events(control)] == [
        (str(git), (str(git), "--version"))
    ]

    with capture_spawns() as dispatch_spawns:
        dispatched = await dispatcher.dispatch_claude_task(request_payload)
    assert "error" not in dispatched, dispatched
    base = request_payload["repository"]["base_ref"]
    assert _git_suffixes(dispatch_spawns) == [
        ("rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}"),
        ("ls-tree", "-r", "-z", base),
        ("worktree", "list", "--porcelain"),
        ("worktree", "add", "--quiet", "--detach", dispatched["worktree"], base),
        ("cat-file", "--batch"),
        ("rev-list", "--objects", "--missing=print", "HEAD"),
    ]
    _assert_no_git_after_first_non_git_process(dispatch_spawns)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    with capture_spawns() as resume_spawns:
        resumed = await dispatcher.resume_claude_task(
            dispatched["task_id"], "Re-check the implementation without broadening scope."
        )
    assert "error" not in resumed, resumed
    assert _git_suffixes(resume_spawns) == [("worktree", "list", "--porcelain")]
    _assert_no_git_after_first_non_git_process(resume_spawns)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    with capture_spawns() as review_spawns:
        reviewed = await dispatcher.review_task_with_fable(resumed["task_id"])
    assert "error" not in reviewed, reviewed
    assert _git_suffixes(review_spawns) == []
    _assert_no_git_after_first_non_git_process(review_spawns)


async def test_fable_opens_exactly_the_sealed_authority_paths(
    dispatcher, request_payload, fake_env, monkeypatch
) -> None:
    """V6 exact-set equality, armed canary, and one-extra-read control."""

    dispatched = await dispatcher.dispatch_claude_task(request_payload)
    assert "error" not in dispatched, dispatched
    task_id = dispatched["task_id"]
    repository_root = Path(request_payload["repository"]["root"])
    worktree_root = Path(dispatched["worktree"])
    authority_path = (
        dispatcher.store.task_dir(task_id)
        / "evidence"
        / "preworker-seal"
        / "worktree-authority.json"
    )
    authority = decode_worktree_authority(authority_path.read_bytes())
    expected = authority_file_paths(authority) + (authority.gitdir_realpath,)

    canary = repository_root / "README.md"
    with _capture_opens() as canary_opens:
        canary.read_bytes()
    assert Path(os.path.realpath(canary)) in _real_paths_under(
        canary_opens, repository_root
    )

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    with _capture_opens() as observed:
        reviewed = await dispatcher.review_task_with_fable(task_id)
    assert "error" not in reviewed, reviewed
    _assert_exact_review_authority_opens(
        observed,
        repository_root=repository_root,
        worktree_root=worktree_root,
        expected=expected,
    )


async def test_fable_exact_open_set_rejects_one_extra_read(
    dispatcher, request_payload, fake_env, monkeypatch
) -> None:
    """The exact-set assertion must fire when V6 reads one unsealed file."""

    dispatched = await dispatcher.dispatch_claude_task(request_payload)
    assert "error" not in dispatched, dispatched
    task_id = dispatched["task_id"]
    repository_root = Path(request_payload["repository"]["root"])
    worktree_root = Path(dispatched["worktree"])
    authority_path = (
        dispatcher.store.task_dir(task_id)
        / "evidence"
        / "preworker-seal"
        / "worktree-authority.json"
    )
    authority = decode_worktree_authority(authority_path.read_bytes())
    expected = authority_file_paths(authority) + (authority.gitdir_realpath,)

    original_verify = server_module.verify_worktree_authority
    extra = Path(os.fsdecode(authority.gitdir_realpath)) / "index"
    assert extra.is_file()

    def verify_with_extra_read(record):
        extra.read_bytes()
        return original_verify(record)

    monkeypatch.setattr(
        server_module, "verify_worktree_authority", verify_with_extra_read
    )
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    with _capture_opens() as forged_observed:
        second = await dispatcher.review_task_with_fable(task_id)
    assert "error" not in second, second
    assert Path(os.path.realpath(extra)) in _real_paths_under(
        forged_observed, repository_root
    )
    with pytest.raises(AssertionError):
        _assert_exact_review_authority_opens(
            forged_observed,
            repository_root=repository_root,
            worktree_root=worktree_root,
            expected=expected,
        )
