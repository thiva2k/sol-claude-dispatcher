from __future__ import annotations

import os
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import (
    WorktreeGitfileNotRegular,
    WorktreeHeadNotRegular,
)
from sol_claude_dispatcher.evidence.worktreeauth import (
    authority_file_paths,
    capture_worktree_authority,
    verify_worktree_authority,
)


BASE = "c" * 40


def _linked(tmp_path: Path) -> tuple[Path, Path, Path]:
    common = tmp_path / "primary" / ".git"
    gitdir = common / "worktrees" / "task"
    worktree = tmp_path / "task"
    gitdir.mkdir(parents=True)
    worktree.mkdir()
    (worktree / ".git").write_bytes(b"gitdir: " + os.fsencode(gitdir) + b"\n")
    (gitdir / "commondir").write_bytes(b"../..\n")
    (gitdir / "gitdir").write_bytes(os.fsencode(worktree / ".git") + b"\n")
    (gitdir / "HEAD").write_bytes(BASE.encode() + b"\n")
    return worktree, gitdir, common


def test_raw_authority_seals_four_files_and_all_eight_comparisons(tmp_path: Path) -> None:
    worktree, gitdir, common = _linked(tmp_path)
    record = capture_worktree_authority(
        worktree,
        worktree_id="task",
        expected_base_commit=BASE,
        created_argv=("git", "worktree", "add", "--detach", str(worktree), BASE),
        dispatcher_owned_gitdir_root=common,
    )
    assert authority_file_paths(record) == (
        os.fsencode(worktree / ".git"),
        os.fsencode(gitdir / "commondir"),
        os.fsencode(gitdir / "gitdir"),
        os.fsencode(gitdir / "HEAD"),
    )
    verdict = verify_worktree_authority(record)
    assert verdict.verdict == "base_held"
    assert verdict.differences == ()
    assert verdict.checks_passed == (1, 2, 3, 4, 5, 6, 7, 8)


@pytest.mark.parametrize("authority_name", [".git", "commondir", "gitdir", "HEAD"])
def test_authority_read_refuses_a_symlink_swapped_after_lstat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, authority_name: str
) -> None:
    """The old lstat/Path.read_bytes sequence followed each forged link."""

    worktree, gitdir, common = _linked(tmp_path)
    record = capture_worktree_authority(
        worktree,
        worktree_id="task",
        expected_base_commit=BASE,
        created_argv=("git", "worktree", "add", "--detach", str(worktree), BASE),
        dispatcher_owned_gitdir_root=common,
    )
    selected = worktree / ".git" if authority_name == ".git" else gitdir / authority_name
    original_bytes = selected.read_bytes()
    decoy = tmp_path / f"decoy-{authority_name.replace('.', 'dot')}"
    decoy.write_bytes(original_bytes)
    backup = selected.with_name(selected.name + ".sealed")
    raw_selected = os.fsencode(selected)
    real_open = os.open
    swapped = False

    def swap_then_open(
        path: str | bytes,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        absolute_match = dir_fd is None and os.fsencode(path) == raw_selected
        anchored_child_match = (
            authority_name != ".git"
            and dir_fd is not None
            and os.fsencode(path) == os.fsencode(authority_name)
        )
        if not swapped and (absolute_match or anchored_child_match):
            selected.rename(backup)
            selected.symlink_to(decoy)
            swapped = True
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_then_open)
    try:
        verdict = verify_worktree_authority(record)
        assert swapped, "the deterministic replacement control did not fire"
        assert selected.is_symlink()
        assert selected.read_bytes() == original_bytes, "the forged link is an armed decoy"
        assert verdict.verdict != "base_held"
    finally:
        if selected.is_symlink():
            selected.unlink()
        if backup.exists():
            backup.rename(selected)


@pytest.mark.parametrize("swap_after", ["gitdir", "commondir", "HEAD"])
def test_matching_whole_gitdir_replacement_cannot_pass_anchored_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap_after: str
) -> None:
    """A matching decoy cannot exploit path-based reads after check 3."""

    worktree, gitdir, common = _linked(tmp_path)
    record = capture_worktree_authority(
        worktree,
        worktree_id="task",
        expected_base_commit=BASE,
        created_argv=("git", "worktree", "add", "--detach", str(worktree), BASE),
        dispatcher_owned_gitdir_root=common,
    )
    original_identity = (record.gitdir_dev, record.gitdir_ino)
    decoy = tmp_path / "matching-gitdir-decoy"
    decoy.mkdir()
    for name in ("commondir", "gitdir", "HEAD"):
        (decoy / name).write_bytes((gitdir / name).read_bytes())
    backup = gitdir.with_name("task-sealed-original")
    real_open = os.open
    swapped = False

    def swap_after_open(
        path: str | bytes,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if dir_fd is None:
            fd = real_open(path, flags, mode)
        else:
            fd = real_open(path, flags, mode, dir_fd=dir_fd)
        directory_boundary = (
            swap_after == "gitdir"
            and dir_fd is None
            and os.fsencode(path) == os.fsencode(gitdir)
        )
        child_boundary = (
            swap_after != "gitdir"
            and dir_fd is not None
            and os.fsencode(path) == os.fsencode(swap_after)
        )
        if not swapped and (directory_boundary or child_boundary):
            gitdir.rename(backup)
            decoy.rename(gitdir)
            swapped = True
        return fd

    monkeypatch.setattr(os, "open", swap_after_open)
    verdict = verify_worktree_authority(record)

    assert swapped, f"the {swap_after} replacement control did not fire"
    assert (gitdir.stat().st_dev, gitdir.stat().st_ino) != original_identity
    assert {
        name: (gitdir / name).read_bytes() for name in ("commondir", "gitdir", "HEAD")
    } == {
        "commondir": record.commondir_bytes,
        "gitdir": record.gitdir_backptr_bytes,
        "HEAD": record.head_bytes,
    }, "the replacement was not an armed matching-byte decoy"
    assert verdict.verdict == "indirection_changed"
    assert verdict.differences[-1].comparison == 3


def test_matching_gitfile_replacement_after_open_cannot_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worktree .git descriptor remains anchored through child reads."""

    worktree, gitdir, common = _linked(tmp_path)
    record = capture_worktree_authority(
        worktree,
        worktree_id="task",
        expected_base_commit=BASE,
        created_argv=("git", "worktree", "add", "--detach", str(worktree), BASE),
        dispatcher_owned_gitdir_root=common,
    )
    gitfile = worktree / ".git"
    original_identity = (gitfile.stat().st_dev, gitfile.stat().st_ino)
    backup = worktree / ".git.sealed-original"
    decoy = worktree / ".git.matching-decoy"
    decoy.write_bytes(record.gitfile_bytes)
    real_open = os.open
    swapped = False

    def replace_after_open(
        path: str | bytes,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if dir_fd is None:
            fd = real_open(path, flags, mode)
        else:
            fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if not swapped and dir_fd is None and os.fsencode(path) == os.fsencode(gitdir):
            gitfile.rename(backup)
            decoy.rename(gitfile)
            swapped = True
        return fd

    monkeypatch.setattr(os, "open", replace_after_open)
    verdict = verify_worktree_authority(record)

    assert swapped, "the matching gitfile replacement control did not fire"
    assert gitfile.read_bytes() == record.gitfile_bytes
    assert (gitfile.stat().st_dev, gitfile.stat().st_ino) != original_identity
    assert verdict.verdict == "indirection_changed"
    assert verdict.differences[-1].field == "gitfile_identity"


def test_live_gitfile_cannot_redirect_verification_to_attacker_gitdir(tmp_path: Path) -> None:
    worktree, _, common = _linked(tmp_path)
    record = capture_worktree_authority(
        worktree,
        worktree_id="task",
        expected_base_commit=BASE,
        created_argv=("git", "worktree", "add", "--detach", str(worktree), BASE),
        dispatcher_owned_gitdir_root=common,
    )
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    (attacker / "HEAD").write_bytes(BASE.encode() + b"\n")
    (worktree / ".git").write_bytes(b"gitdir: " + os.fsencode(attacker) + b"\n")

    verdict = verify_worktree_authority(record)
    assert verdict.verdict == "indirection_changed"
    assert verdict.differences[0].comparison == 2


@pytest.mark.parametrize(
    "head",
    [
        BASE.encode(),
        BASE.upper().encode() + b"\n",
        BASE.encode() + b"\r\n",
        BASE.encode() + b"\n\n",
        b"ref: refs/heads/main\n",
        (BASE[:-1] + "d").encode() + b"\n",
    ],
)
def test_head_is_post_worker_whole_file_byte_equality(tmp_path: Path, head: bytes) -> None:
    worktree, gitdir, common = _linked(tmp_path)
    record = capture_worktree_authority(
        worktree,
        worktree_id="task",
        expected_base_commit=BASE,
        created_argv=("git", "worktree", "add", "--detach", str(worktree), BASE),
        dispatcher_owned_gitdir_root=common,
    )
    (gitdir / "HEAD").write_bytes(head)
    verdict = verify_worktree_authority(record)
    assert verdict.verdict == "base_mismatch"
    assert verdict.observed_head_bytes == head
    assert verdict.differences[-1].comparison == 8


def test_missing_head_is_unknown_and_symlinked_head_refuses(tmp_path: Path) -> None:
    worktree, gitdir, common = _linked(tmp_path)
    record = capture_worktree_authority(
        worktree,
        worktree_id="task",
        expected_base_commit=BASE,
        created_argv=("git", "worktree", "add", "--detach", str(worktree), BASE),
        dispatcher_owned_gitdir_root=common,
    )
    (gitdir / "HEAD").unlink()
    assert verify_worktree_authority(record).verdict == "unknown"
    (gitdir / "HEAD").symlink_to("elsewhere")
    assert verify_worktree_authority(record).verdict == "base_mismatch"


def test_capture_refuses_nonregular_authority_files(tmp_path: Path) -> None:
    worktree, gitdir, common = _linked(tmp_path)
    (worktree / ".git").unlink()
    (worktree / ".git").symlink_to("elsewhere")
    with pytest.raises(WorktreeGitfileNotRegular):
        capture_worktree_authority(
            worktree,
            worktree_id="task",
            expected_base_commit=BASE,
            created_argv=(BASE,),
            dispatcher_owned_gitdir_root=common,
        )
    (worktree / ".git").unlink()
    (worktree / ".git").write_bytes(b"gitdir: " + os.fsencode(gitdir) + b"\n")
    (gitdir / "HEAD").unlink()
    (gitdir / "HEAD").symlink_to("missing")
    with pytest.raises(WorktreeHeadNotRegular):
        capture_worktree_authority(
            worktree,
            worktree_id="task",
            expected_base_commit=BASE,
            created_argv=(BASE,),
            dispatcher_owned_gitdir_root=common,
        )
