"""Killers for raw primary HEAD, authority, and snapshot invariants."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import (
    FilesystemSnapshotFailed,
    RefResolutionFailed,
    RepositoryRootDrift,
)
from sol_claude_dispatcher.evidence.fssnap import FsEntry, FsSnapshot
from sol_claude_dispatcher.evidence.identity import capture_repository_authority
from sol_claude_dispatcher.evidence.inventory import RepoPath
from sol_claude_dispatcher.evidence.prepare import (
    assert_primary_snapshot_usable,
    capture_matching_repository_authority,
    capture_primary_head,
    primary_snapshots_equal,
)


def _authority(repo: Path):
    return capture_repository_authority(repo, authorized_root=repo)


def _oid(character: bytes) -> bytes:
    return character * 40 + b"\n"


def test_raw_primary_head_resolves_and_seals_every_loose_hop(
    git_repo: Path,
) -> None:
    authority = _authority(git_repo)
    git_dir = Path(os.fsdecode(authority.common_dir))
    (git_dir / "HEAD").write_bytes(b"ref: refs/heads/one\n")
    (git_dir / "refs/heads/one").write_bytes(b"ref: refs/heads/two\n")
    (git_dir / "refs/heads/two").write_bytes(_oid(b"a"))

    before = capture_primary_head(authority)
    assert [link.ref_name for link in before.ref_chain] == [
        b"refs/heads/one",
        b"refs/heads/two",
    ]
    assert before.head_commit == "a" * 40

    (git_dir / "refs/heads/two").write_bytes(_oid(b"b"))
    after = capture_primary_head(authority)
    assert after.head_commit == "b" * 40
    assert after.digest != before.digest


@pytest.mark.parametrize(
    "head",
    [
        b"NOT-A-COMMIT\n",
        b"A" * 40 + b"\n",
        b"a" * 39 + b"\n",
        b"a" * 40 + b"\nextra\n",
        b"ref: refs/heads/../../../tmp/evil\n",
        b"ref: refs/heads/.hidden\n",
        b"ref: refs/heads/main\\evil\n",
    ],
)
def test_raw_primary_head_rejects_noncanonical_terminal_or_ref(
    git_repo: Path, head: bytes
) -> None:
    authority = _authority(git_repo)
    Path(os.fsdecode(authority.git_dir), "HEAD").write_bytes(head)

    with pytest.raises(RefResolutionFailed):
        capture_primary_head(authority)


def test_raw_primary_head_enforces_five_symbolic_hops(git_repo: Path) -> None:
    authority = _authority(git_repo)
    git_dir = Path(os.fsdecode(authority.common_dir))
    (git_dir / "HEAD").write_bytes(b"ref: refs/heads/a\n")
    for left, right in zip("abcde", "bcdef", strict=True):
        (git_dir / f"refs/heads/{left}").write_bytes(
            f"ref: refs/heads/{right}\n".encode("ascii")
        )
    (git_dir / "refs/heads/f").write_bytes(_oid(b"a"))

    with pytest.raises(RefResolutionFailed, match="hop limit"):
        capture_primary_head(authority)


def test_raw_primary_head_resolves_exact_packed_ref(git_repo: Path) -> None:
    authority = _authority(git_repo)
    common = Path(os.fsdecode(authority.common_dir))
    head = common / "refs/heads/main"
    head.unlink()
    (common / "packed-refs").write_bytes(
        b"# pack-refs with: peeled fully-peeled sorted\n"
        + _oid(b"c").rstrip(b"\n")
        + b" refs/heads/main\n"
    )

    snapshot = capture_primary_head(authority)

    assert snapshot.head_commit == "c" * 40
    assert snapshot.ref_chain[-1].source == "packed"
    assert snapshot.packed_refs_bytes is not None


def test_live_authority_replacement_with_identical_bytes_refuses(
    git_repo: Path,
) -> None:
    sealed = _authority(git_repo)
    original = git_repo / ".git"
    displaced = git_repo / ".git-old"
    original.rename(displaced)
    shutil.copytree(displaced, original, symlinks=True)

    with pytest.raises(RepositoryRootDrift) as raised:
        capture_matching_repository_authority(
            git_repo, sealed, phase="worker_exit"
        )

    assert raised.value.details["phase"] == "worker_exit"
    assert "git_dir_ino" in raised.value.details["changed_fields"]


def _entry(path: bytes = b"README.md") -> FsEntry:
    return FsEntry(
        path=RepoPath(path),
        kind="regular",
        perm=0o644,
        size=1,
        mtime_ns=1,
        ctime_ns=1,
        ino=1,
        dev=1,
        nlink=1,
        content_hash=None,
        link_target=None,
        read_error=None,
    )


def _primary(
    *, root: bytes = b"/repo", role: str = "primary_pre", entries=(_entry(),)
) -> FsSnapshot:
    return FsSnapshot.from_entries(
        root=root,
        role=role,  # type: ignore[arg-type]
        fidelity="stat_identity",
        entries=entries,
        admin_excluded=(RepoPath(b".git"),),
    )


def test_primary_comparison_refuses_two_empty_captures() -> None:
    empty = _primary(entries=())

    with pytest.raises(FilesystemSnapshotFailed) as raised:
        primary_snapshots_equal(empty, empty, expected_root=b"/repo")

    assert "zero_entries" in raised.value.details["reasons"]


def test_primary_comparison_requires_same_root_fidelity_and_canonical_entries() -> None:
    before = _primary()
    after = _primary(role="primary_post")
    assert primary_snapshots_equal(before, after, expected_root=b"/repo") is True

    wrong_root = _primary(root=b"/other", role="primary_post")
    with pytest.raises(FilesystemSnapshotFailed) as raised:
        primary_snapshots_equal(before, wrong_root, expected_root=b"/repo")
    assert "root" in raised.value.details["reasons"]

    changed = _primary(role="primary_post", entries=(_entry(b"other"),))
    assert primary_snapshots_equal(before, changed, expected_root=b"/repo") is False


def test_primary_snapshot_requires_exact_admin_exclusion() -> None:
    snapshot = FsSnapshot.from_entries(
        root=b"/repo",
        role="primary_pre",
        fidelity="stat_identity",
        entries=(_entry(),),
    )
    with pytest.raises(FilesystemSnapshotFailed) as raised:
        assert_primary_snapshot_usable(snapshot, expected_root=b"/repo")
    assert "admin_exclusion" in raised.value.details["reasons"]
