from __future__ import annotations

import hashlib

from sol_claude_dispatcher.evidence.content import (
    ContentClass,
    ContentInput,
    classify_change,
    classify_inventory,
    classify_input,
    git_blob_oid,
)
from sol_claude_dispatcher.evidence.fssnap import FsEntry, FsSnapshot
from sol_claude_dispatcher.evidence.inventory import RepoPath, ScopeSpecBytes, build_path_identity_set, decide_scope


def test_text_binary_absent_unreadable_oversized_and_changed_are_distinct() -> None:
    assert classify_input(ContentInput.regular(b"hello\n")).content_class is ContentClass.TEXT_CANDIDATE
    binary = classify_input(ContentInput.regular(b"hello\0world"))
    assert binary.content_class is ContentClass.UNTEXTUAL
    assert binary.inventory_complete is True
    assert binary.data == b"hello\0world"
    assert classify_input(ContentInput.absent()).content_class is ContentClass.ABSENT
    unreadable = classify_input(ContentInput(kind="regular", data=None, mode=0o100644, read_error="EACCES"))
    assert unreadable.content_class is ContentClass.UNREADABLE
    assert unreadable.inventory_complete is False
    moved = classify_input(ContentInput(kind="regular", data=None, mode=0o100644, read_error="changed_during_measurement"))
    assert moved.content_class is ContentClass.CHANGED_DURING_MEASUREMENT
    assert classify_input(ContentInput.regular(b"12345"), maximum_bytes=4).content_class is ContentClass.OVERSIZED


def test_invalid_utf8_regular_file_is_binary_but_symlink_target_is_exact_bytes() -> None:
    regular = classify_input(ContentInput.regular(b"\xfftarget"))
    symlink = classify_input(ContentInput.symlink(b"\xfftarget"))
    assert regular.content_class is ContentClass.UNTEXTUAL
    assert symlink.content_class is ContentClass.TEXT_CANDIDATE
    assert symlink.data == b"\xfftarget"
    assert symlink.oid == git_blob_oid(b"\xfftarget")


def test_special_files_and_gitlinks_are_inventory_complete_but_unrepresentable() -> None:
    for kind in ("fifo", "socket", "block", "char", "gitlink", "directory"):
        side = classify_input(ContentInput(kind=kind, data=None, mode=None))
        assert side.content_class is ContentClass.UNREPRESENTABLE_KIND
        assert side.inventory_complete is True


def test_git_blob_oid_is_byte_exact_and_change_keeps_both_authorities() -> None:
    data = b"no trailing newline"
    expected = hashlib.sha1(b"blob 19\0" + data).hexdigest()
    assert git_blob_oid(data) == expected
    change = classify_change(
        b"hostile\nname",
        ContentInput.regular(b"old"),
        ContentInput.symlink(b"../dangling"),
    )
    assert change.path == b"hostile\nname"
    assert change.old.data == b"old"
    assert change.new.data == b"../dangling"
    assert change.change == "kind_changed"


def test_classification_requires_the_exact_prior_scope_verdict() -> None:
    def entry(value: bytes) -> FsEntry:
        return FsEntry(
            path=RepoPath(b"x"), kind="regular", perm=0o644, size=len(value),
            mtime_ns=1, ctime_ns=1, ino=1, dev=1, nlink=1,
            content_hash=git_blob_oid(value), link_target=None, read_error=None,
        )

    start = FsSnapshot.from_entries(root=b"/repo", role="task_worktree_start", entries=(entry(b"a"),), fidelity="content_hash_all")
    post = FsSnapshot.from_entries(root=b"/repo", role="task_worktree_worker_exit", entries=(entry(b"b"),), fidelity="content_hash_all")
    identity = build_path_identity_set(start, post, base_commit="a" * 40)
    verdict = decide_scope(identity, ScopeSpecBytes())
    inventory = classify_inventory(
        identity,
        verdict,
        {b"x": (ContentInput.regular(b"a"), ContentInput.regular(b"b"))},
    )
    assert inventory.verdict is verdict
    assert inventory.classes[0].content.new.data == b"b"
