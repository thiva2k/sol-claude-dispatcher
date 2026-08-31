from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from sol_claude_dispatcher.evidence.fssnap import FsEntry, FsSnapshot
from sol_claude_dispatcher.evidence.inventory import (
    PathIdentitySet,
    RepoPath,
    ScopeSpecBytes,
    build_path_identity_set,
    decide_scope,
    path_repr,
    repo_path_from_repr,
)


def _entry(
    path: bytes,
    *,
    kind: str = "regular",
    content_hash: str | None = "a" * 40,
    perm: int = 0o644,
    size: int = 1,
    link_target: bytes | None = None,
) -> FsEntry:
    return FsEntry(
        path=RepoPath(path),
        kind=kind,
        perm=perm,
        size=size,
        mtime_ns=1,
        ctime_ns=1,
        ino=1,
        dev=1,
        nlink=1,
        content_hash=content_hash,
        link_target=link_target,
        read_error=None,
    )


def _snapshot(entries: tuple[FsEntry, ...], role: str) -> FsSnapshot:
    return FsSnapshot.from_entries(
        root=b"/tmp/repo",
        role=role,
        entries=entries,
        fidelity="content_hash_all",
    )


def test_modified_path_is_in_the_delta_not_only_added_and_removed() -> None:
    before = _snapshot(
        (
            _entry(b"modified", content_hash="a" * 40),
            _entry(b"removed"),
            _entry(b"kind"),
            _entry(b"mode", perm=0o644),
            _entry(b"link", kind="symlink", content_hash="1" * 40, link_target=b"a"),
            _entry(b"same"),
        ),
        "task_worktree_start",
    )
    after = _snapshot(
        (
            _entry(b"added"),
            _entry(b"modified", content_hash="b" * 40),
            _entry(b"kind", kind="symlink", content_hash="2" * 40, link_target=b"x"),
            _entry(b"mode", perm=0o755),
            _entry(b"link", kind="symlink", content_hash="3" * 40, link_target=b"b"),
            _entry(b"same"),
        ),
        "task_worktree_worker_exit",
    )

    identity = build_path_identity_set(before, after, base_commit="f" * 40)

    assert [(bytes(c.path), c.change) for c in identity.changes] == [
        (b"added", "added"),
        (b"kind", "kind_changed"),
        (b"link", "link_target_changed"),
        (b"mode", "mode_changed"),
        (b"modified", "modified"),
        (b"removed", "removed"),
    ]
    assert identity.unchanged_count == 1
    assert identity.fidelity == "content_hash_all"


def test_digest_is_stable_over_raw_bytes_and_load_bearing() -> None:
    before = _snapshot((), "task_worktree_start")
    after = _snapshot((_entry(b"bad-\xff\nname"),), "task_worktree_worker_exit")
    one = build_path_identity_set(before, after, base_commit="a" * 40)
    two = build_path_identity_set(before, after, base_commit="a" * 40)
    assert one.digest == two.digest
    changed = replace(one.changes[0], path=RepoPath(b"bad-\xfe\nname"))
    forged = PathIdentitySet.create(
        base_commit=one.base_commit,
        changes=(changed,),
        unchanged_count=one.unchanged_count,
        fidelity=one.fidelity,
    )
    assert forged.digest != one.digest


def test_raw_byte_scope_matching_preserves_hostile_names_and_forbidden_wins() -> None:
    before = _snapshot((), "task_worktree_start")
    after = _snapshot(
        (
            _entry(b"allowed/new\nline.txt"),
            _entry(b"allowed/forbidden/secret"),
            _entry(b"outside/\xff"),
        ),
        "task_worktree_worker_exit",
    )
    identity = build_path_identity_set(before, after, base_commit="a" * 40)
    scope = ScopeSpecBytes.from_strings(
        allowed_paths=["allowed/**"], forbidden_paths=["allowed/forbidden/**"]
    )

    verdict = decide_scope(identity, scope)

    assert verdict.decided_over_digest == identity.digest
    assert verdict.valid is False
    assert tuple(map(bytes, verdict.forbidden_hits)) == (b"allowed/forbidden/secret",)
    assert tuple(map(bytes, verdict.outside_allowed)) == (b"outside/\xff",)


def test_empty_allowed_paths_is_unrestricted_but_forbidden_still_applies() -> None:
    identity = build_path_identity_set(
        _snapshot((), "task_worktree_start"),
        _snapshot((_entry(b"anything"),), "task_worktree_worker_exit"),
        base_commit="a" * 40,
    )
    assert decide_scope(identity, ScopeSpecBytes()).valid is True
    verdict = decide_scope(
        identity, ScopeSpecBytes.from_strings(forbidden_paths=["anything"])
    )
    assert verdict.valid is False
    assert tuple(map(bytes, verdict.forbidden_hits)) == (b"anything",)


def test_no_lstat_before_the_scope_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = build_path_identity_set(
        _snapshot((), "task_worktree_start"),
        _snapshot((_entry(b"src/x"),), "task_worktree_worker_exit"),
        base_commit="a" * 40,
    )

    def forbidden_lstat(*args, **kwargs):
        raise AssertionError("policy must not classify filesystem content")

    monkeypatch.setattr(os, "lstat", forbidden_lstat)
    verdict = decide_scope(
        identity, ScopeSpecBytes.from_strings(allowed_paths=["src/**"])
    )
    assert verdict.valid is True


def test_scope_verdict_digest_matches_identity_digest() -> None:
    identity = build_path_identity_set(
        _snapshot((), "task_worktree_start"),
        _snapshot((_entry(b"src/x"),), "task_worktree_worker_exit"),
        base_commit="a" * 40,
    )
    verdict = decide_scope(identity, ScopeSpecBytes())
    assert verdict.decided_over_digest == identity.digest


def test_path_repr_round_trips_non_utf8_bytes_without_using_display() -> None:
    raw = RepoPath(b"dir/nonutf8-\xff\n")
    rendered = path_repr(raw)
    assert rendered["utf8"] is False
    assert "\ufffd" in rendered["display"]
    assert repo_path_from_repr(rendered) == raw
