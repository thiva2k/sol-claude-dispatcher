"""Gate 7 raw repository-layout identity.

These tests deliberately construct Git layouts without invoking Git.  The
identity layer is the pre-subprocess authority boundary: if a layout cannot be
proved from raw filesystem facts, it must refuse instead of asking Git to
interpret attacker-controlled administration.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import (
    RepositoryAdministrationUnsupported,
    RepositoryLayoutUnreadable,
)
from sol_claude_dispatcher.evidence.identity import (
    DotGitShape,
    RepositoryAuthoritySnapshot,
    capture_repository_authority,
    classify_dot_git,
    raw_realpath,
)


def _normal_repository(root: Path) -> Path:
    git_dir = root / ".git"
    (git_dir / "objects").mkdir(parents=True)
    (git_dir / "HEAD").write_bytes(b"ref: refs/heads/main\n")
    return git_dir


def _linked_worktree(tmp_path: Path, *, target_line: bytes | None = None):
    primary = tmp_path / "primary"
    common = _normal_repository(primary)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    git_dir = common / "worktrees" / "task"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_bytes(b"0123456789abcdef\n")
    (git_dir / "commondir").write_bytes(b"../..\n")
    (git_dir / "gitdir").write_bytes(os.fsencode(worktree / ".git") + b"\n")
    line = target_line or b"gitdir: " + os.fsencode(git_dir) + b"\n"
    (worktree / ".git").write_bytes(line)
    return primary, common, worktree, git_dir


class TestClassification:
    @pytest.mark.parametrize(
        ("maker", "expected"),
        [
            (lambda p: p.mkdir(), DotGitShape.DIRECTORY),
            (lambda p: p.write_bytes(b"gitdir: /tmp/example\n"), DotGitShape.GITFILE),
            (lambda p: p.symlink_to("missing"), DotGitShape.SYMLINK),
            (lambda p: os.mkfifo(p), DotGitShape.OTHER),
        ],
    )
    def test_dot_git_shape_is_four_valued(self, tmp_path, maker, expected):
        root = tmp_path / "repo"
        root.mkdir()
        maker(root / ".git")
        assert classify_dot_git(root).shape is expected

    def test_lstat_precedes_readlink_and_open(self, tmp_path, monkeypatch):
        root = tmp_path / "repo"
        root.mkdir()
        (root / ".git").symlink_to("missing")
        events: list[str] = []
        real_lstat = os.lstat
        real_readlink = os.readlink

        def observed_lstat(path):
            if os.fspath(path).endswith(b"/.git"):
                events.append("lstat")
            return real_lstat(path)

        def observed_readlink(path):
            events.append("readlink")
            return real_readlink(path)

        monkeypatch.setattr(os, "lstat", observed_lstat)
        monkeypatch.setattr(os, "readlink", observed_readlink)
        result = classify_dot_git(root)

        assert result.shape is DotGitShape.SYMLINK
        assert events == ["lstat", "readlink"]

    def test_lstat_precedes_gitfile_open(self, tmp_path, monkeypatch):
        _, common, worktree, _ = _linked_worktree(tmp_path)
        events: list[tuple[str, bytes]] = []
        real_lstat = os.lstat
        real_open = os.open

        def observed_lstat(path):
            if os.fspath(path).endswith(b"/.git"):
                events.append(("lstat", os.fsencode(path)))
            return real_lstat(path)

        def observed_open(path, flags, *args):
            if os.fspath(path).endswith(b"/.git"):
                events.append(("open", os.fsencode(path)))
            return real_open(path, flags, *args)

        monkeypatch.setattr(os, "lstat", observed_lstat)
        monkeypatch.setattr(os, "open", observed_open)
        capture_repository_authority(worktree, authorized_gitdir_roots=(common,))
        worktree_git = os.fsencode(worktree / ".git")
        worktree_events = [operation for operation, path in events if path == worktree_git]
        assert worktree_events == ["lstat", "open"]


class TestRawResolution:
    def test_normal_repository_is_captured_without_git(self, tmp_path, monkeypatch):
        root = tmp_path / "repo"
        git_dir = _normal_repository(root)

        def subprocess_is_a_bug(*args, **kwargs):  # pragma: no cover - fires on defect
            raise AssertionError("raw identity must not spawn a subprocess")

        monkeypatch.setattr("subprocess.run", subprocess_is_a_bug)
        snapshot = capture_repository_authority(root)

        assert snapshot.canonical_root == os.fsencode(root)
        assert snapshot.dot_git_shape is DotGitShape.DIRECTORY
        assert snapshot.git_dir == os.fsencode(git_dir)
        assert snapshot.common_dir == os.fsencode(git_dir)
        assert snapshot.gitfile_bytes is None
        assert snapshot.commondir_bytes is None
        assert snapshot.resolver == "raw"

    def test_authorized_root_uses_raw_realpath_byte_equality(self, tmp_path):
        root = tmp_path / "repo"
        _normal_repository(root)
        alias = tmp_path / "alias"
        alias.symlink_to(root)

        snapshot = capture_repository_authority(
            alias, authorized_root=raw_realpath(root)
        )
        assert snapshot.canonical_root == raw_realpath(root)

        other = tmp_path / "other"
        other.mkdir()
        with pytest.raises(RepositoryLayoutUnreadable, match="authorized root"):
            capture_repository_authority(root, authorized_root=raw_realpath(other))

    def test_linked_worktree_requires_and_uses_authorized_gitdir_root(self, tmp_path):
        _, common, worktree, git_dir = _linked_worktree(tmp_path)

        with pytest.raises(RepositoryAdministrationUnsupported, match="onboarded"):
            capture_repository_authority(worktree)

        snapshot = capture_repository_authority(
            worktree,
            authorized_gitdir_roots=(common,),
        )
        assert snapshot.dot_git_shape is DotGitShape.GITFILE
        assert snapshot.gitfile_bytes == (
            b"gitdir: " + os.fsencode(git_dir) + b"\n"
        )
        assert snapshot.git_dir == os.fsencode(git_dir)
        assert snapshot.common_dir == os.fsencode(common)
        assert snapshot.commondir_bytes == b"../..\n"

    def test_relative_gitfile_target_resolves_from_worktree_root(self, tmp_path):
        _, common, worktree, git_dir = _linked_worktree(tmp_path)
        relative = os.path.relpath(git_dir, worktree)
        (worktree / ".git").write_bytes(b"gitdir: " + os.fsencode(relative) + b"\n")

        snapshot = capture_repository_authority(
            worktree, authorized_gitdir_roots=(common,)
        )
        assert snapshot.git_dir == os.fsencode(git_dir)

    @pytest.mark.parametrize(
        "body",
        [
            b"",
            b"gitdir:",
            b"gitdir: /tmp/x",
            b" gitdir: /tmp/x\n",
            b"gitdir: /tmp/x\nextra\n",
            b"gitdir: \n",
            b"GITDIR: /tmp/x\n",
            b"gitdir: /tmp/nu\x00ll\n",
        ],
    )
    def test_malformed_gitfile_refuses(self, tmp_path, body):
        root = tmp_path / "worktree"
        root.mkdir()
        (root / ".git").write_bytes(body)
        with pytest.raises(RepositoryLayoutUnreadable, match="gitfile"):
            capture_repository_authority(
                root, authorized_gitdir_roots=(tmp_path,)
            )

    def test_gitfile_target_cannot_escape_authorized_admin_root(self, tmp_path):
        _, common, worktree, _ = _linked_worktree(tmp_path)
        decoy = tmp_path / "decoy"
        decoy.mkdir()
        (worktree / ".git").write_bytes(
            b"gitdir: " + os.fsencode(decoy) + b"\n"
        )

        with pytest.raises(RepositoryLayoutUnreadable, match="escapes"):
            capture_repository_authority(
                worktree, authorized_gitdir_roots=(common,)
            )

    def test_authorized_root_containment_is_component_aware(self, tmp_path):
        _, common, worktree, _ = _linked_worktree(tmp_path)
        decoy = common.with_name(common.name + "-decoy")
        decoy.mkdir()
        (worktree / ".git").write_bytes(
            b"gitdir: " + os.fsencode(decoy) + b"\n"
        )

        with pytest.raises(RepositoryLayoutUnreadable, match="escapes"):
            capture_repository_authority(
                worktree, authorized_gitdir_roots=(common,)
            )

    def test_commondir_target_cannot_escape_authorized_admin_root(self, tmp_path):
        _, common, worktree, git_dir = _linked_worktree(tmp_path)
        (git_dir / "commondir").write_bytes(b"../../../decoy\n")
        (tmp_path / "primary" / "decoy").mkdir()

        with pytest.raises(RepositoryLayoutUnreadable, match="commondir.*escapes"):
            capture_repository_authority(
                worktree, authorized_gitdir_roots=(common,)
            )

    @pytest.mark.parametrize("shape", ["symlink", "fifo"])
    def test_symlink_and_nonregular_dot_git_refuse(self, tmp_path, shape):
        root = tmp_path / "repo"
        root.mkdir()
        dot_git = root / ".git"
        if shape == "symlink":
            dot_git.symlink_to("missing")
        else:
            os.mkfifo(dot_git)

        with pytest.raises(RepositoryAdministrationUnsupported) as excinfo:
            capture_repository_authority(root)
        assert excinfo.value.details["shape"] == (
            "symlink" if shape == "symlink" else "other"
        )

    def test_symlinked_gitdir_target_refuses_before_following(self, tmp_path):
        _, common, worktree, git_dir = _linked_worktree(tmp_path)
        real = git_dir.with_name("real-task")
        git_dir.rename(real)
        git_dir.symlink_to(real)

        with pytest.raises(RepositoryLayoutUnreadable, match="symlink"):
            capture_repository_authority(
                worktree, authorized_gitdir_roots=(common,)
            )

    def test_symlinked_commondir_file_refuses(self, tmp_path):
        _, common, worktree, git_dir = _linked_worktree(tmp_path)
        (git_dir / "commondir").unlink()
        (git_dir / "commondir").symlink_to("../..")

        with pytest.raises(RepositoryLayoutUnreadable, match="commondir"):
            capture_repository_authority(
                worktree, authorized_gitdir_roots=(common,)
            )


class TestSnapshot:
    def test_snapshot_is_frozen_and_json_round_trips(self, tmp_path):
        _, common, worktree, _ = _linked_worktree(tmp_path)
        snapshot = capture_repository_authority(
            worktree, authorized_gitdir_roots=(common,)
        )

        with pytest.raises(AttributeError):
            snapshot.git_dir = b"/forged"  # type: ignore[misc]

        wire = snapshot.to_json_dict()
        encoded = json.dumps(wire, sort_keys=True)
        restored = RepositoryAuthoritySnapshot.from_json_dict(json.loads(encoded))
        assert restored == snapshot

    def test_snapshot_contains_inode_and_content_authority(self, tmp_path):
        _, common, worktree, _ = _linked_worktree(tmp_path)
        snapshot = capture_repository_authority(
            worktree, authorized_gitdir_roots=(common,)
        )

        assert snapshot.dot_git_mode & stat.S_IFMT(snapshot.dot_git_mode)
        assert snapshot.dot_git_dev >= 0
        assert snapshot.dot_git_ino > 0
        assert snapshot.git_dir_dev >= 0
        assert snapshot.git_dir_ino > 0
        assert snapshot.common_dir_dev >= 0
        assert snapshot.common_dir_ino > 0
        assert len(snapshot.gitfile_sha256 or "") == 64
        assert len(snapshot.commondir_sha256 or "") == 64

    def test_non_utf8_path_round_trips_without_decoding(self, tmp_path):
        raw_parent = os.fsencode(tmp_path)
        raw_root = os.path.join(raw_parent, b"repo-\xff")
        os.mkdir(raw_root)
        os.mkdir(os.path.join(raw_root, b".git"))

        snapshot = capture_repository_authority(raw_root)
        restored = RepositoryAuthoritySnapshot.from_json_dict(snapshot.to_json_dict())
        assert restored.canonical_root == raw_root
        assert restored == snapshot

    def test_json_refuses_unknown_fields_and_noncanonical_base64(self, tmp_path):
        root = tmp_path / "repo"
        _normal_repository(root)
        snapshot = capture_repository_authority(root)

        with_extra = snapshot.to_json_dict()
        with_extra["future_authority"] = "silently accepting this would be adoption"
        with pytest.raises(ValueError, match="fields differ"):
            RepositoryAuthoritySnapshot.from_json_dict(with_extra)

        invalid = snapshot.to_json_dict()
        invalid["canonical_root_b64"] = invalid["canonical_root_b64"] + "="
        with pytest.raises(ValueError, match="canonical base64"):
            RepositoryAuthoritySnapshot.from_json_dict(invalid)
