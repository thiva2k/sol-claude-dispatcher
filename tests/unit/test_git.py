"""Tests for ``sol_claude_dispatcher.git`` (§12, §13, §31)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sol_claude_dispatcher import git as git_mod
from sol_claude_dispatcher.errors import InvalidRepository
from sol_claude_dispatcher.models import ScopeSpec

def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# is_git_repository
# ---------------------------------------------------------------------------


def test_is_git_repository_true_for_real_repo(git_repo: Path) -> None:
    assert git_mod.is_git_repository(git_repo) is True


def test_is_git_repository_false_for_plain_directory(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert git_mod.is_git_repository(plain) is False


# ---------------------------------------------------------------------------
# resolve_base_commit
# ---------------------------------------------------------------------------


def test_resolve_base_commit_head(git_repo: Path) -> None:
    sha = git_mod.resolve_base_commit(git_repo, "HEAD")
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_resolve_base_commit_branch_name(git_repo: Path) -> None:
    sha = git_mod.resolve_base_commit(git_repo, "main")
    head_sha = git_mod.resolve_base_commit(git_repo, "HEAD")
    assert sha == head_sha


def test_resolve_base_commit_bad_ref_raises(git_repo: Path) -> None:
    with pytest.raises(InvalidRepository):
        git_mod.resolve_base_commit(git_repo, "this-ref-does-not-exist")


# ---------------------------------------------------------------------------
# create_worktree_name / worktree_path_for
# ---------------------------------------------------------------------------


def test_create_worktree_name_matches_pattern() -> None:
    task_id = "0123456789abcdef0123456789abcdef"
    name = git_mod.create_worktree_name(task_id)
    assert name == "sol-01234567"


def test_worktree_path_for_returns_none_when_absent(git_repo: Path) -> None:
    assert git_mod.worktree_path_for(git_repo, "sol-deadbeef") is None


def test_worktree_path_for_finds_created_worktree(git_repo: Path, tmp_path: Path) -> None:
    wt_path = tmp_path / "sol-abc12345"
    _git(["worktree", "add", "-b", "wt-branch", str(wt_path), "HEAD"], git_repo)
    found = git_mod.worktree_path_for(git_repo, "sol-abc12345")
    assert found is not None
    assert found.resolve() == wt_path.resolve()


# ---------------------------------------------------------------------------
# collect_diff_evidence
# ---------------------------------------------------------------------------


def test_collect_diff_evidence_includes_tracked_and_untracked_changes(
    git_repo: Path,
) -> None:
    base = git_mod.resolve_base_commit(git_repo, "HEAD")

    (git_repo / "README.md").write_text("test repo\nmodified\n")
    _git(["add", "README.md"], git_repo)

    (git_repo / "new_untracked.py").write_text("print('hi')\n")

    evidence = git_mod.collect_diff_evidence(git_repo, base)

    assert evidence.base_commit == base
    assert "README.md" in evidence.changed_paths
    assert "new_untracked.py" in evidence.changed_paths
    assert not evidence.truncated
    assert "README.md" in evidence.diff_stat
    assert evidence.porcelain_status


def test_collect_diff_evidence_truncates_large_diffs(git_repo: Path) -> None:
    base = git_mod.resolve_base_commit(git_repo, "HEAD")
    big_content = "x = 1\n" * 200_000
    (git_repo / "big.py").write_text(big_content)
    _git(["add", "big.py"], git_repo)

    evidence = git_mod.collect_diff_evidence(git_repo, base, max_diff_bytes=1000)

    assert evidence.truncated is True
    assert len(evidence.diff_text.encode("utf-8")) <= 1000


def test_collect_diff_evidence_no_changes_is_clean(git_repo: Path) -> None:
    base = git_mod.resolve_base_commit(git_repo, "HEAD")
    evidence = git_mod.collect_diff_evidence(git_repo, base)
    assert evidence.changed_paths == []
    assert evidence.porcelain_status == ""
    assert evidence.diff_check_passed is True


def test_collect_diff_evidence_diff_check_flags_whitespace_errors(
    git_repo: Path,
) -> None:
    base = git_mod.resolve_base_commit(git_repo, "HEAD")
    (git_repo / "trailing.py").write_text("value = 1   \n")
    _git(["add", "trailing.py"], git_repo)

    evidence = git_mod.collect_diff_evidence(git_repo, base)

    assert evidence.diff_check_passed is False
    assert evidence.diff_check_output


# ---------------------------------------------------------------------------
# check_scope
# ---------------------------------------------------------------------------


def test_check_scope_authorized_changes() -> None:
    scope = ScopeSpec(allowed_paths=["src/**"], forbidden_paths=[])
    result = git_mod.check_scope(["src/foo.py", "src/pkg/bar.py"], scope)
    assert result.valid
    assert result.out_of_scope == []
    assert result.forbidden == []


def test_check_scope_unauthorized_change_is_out_of_scope() -> None:
    scope = ScopeSpec(allowed_paths=["src/**"], forbidden_paths=[])
    result = git_mod.check_scope(["docs/readme.md"], scope)
    assert not result.valid
    assert result.out_of_scope == ["docs/readme.md"]
    assert result.forbidden == []


def test_check_scope_forbidden_wins_over_allowed() -> None:
    scope = ScopeSpec(allowed_paths=["**"], forbidden_paths=["secrets/**"])
    result = git_mod.check_scope(["secrets/key.pem"], scope)
    assert not result.valid
    assert result.forbidden == ["secrets/key.pem"]
    assert result.out_of_scope == []


def test_check_scope_untracked_file_is_flagged() -> None:
    scope = ScopeSpec(allowed_paths=["src/**"], forbidden_paths=[])
    result = git_mod.check_scope(["src/foo.py", "unexpected_new_file.txt"], scope)
    assert not result.valid
    assert "unexpected_new_file.txt" in result.out_of_scope
    assert "src/foo.py" not in result.out_of_scope


def test_check_scope_empty_allowlist_is_unrestricted() -> None:
    scope = ScopeSpec(allowed_paths=[], forbidden_paths=[])
    result = git_mod.check_scope(["anything/anywhere.py"], scope)
    assert result.valid
    assert result.out_of_scope == []


def test_check_scope_empty_allowlist_still_honours_forbidden() -> None:
    scope = ScopeSpec(allowed_paths=[], forbidden_paths=["secrets/**"])
    result = git_mod.check_scope(["ok.py", "secrets/key.pem"], scope)
    assert not result.valid
    assert result.forbidden == ["secrets/key.pem"]
    assert result.out_of_scope == []


def test_check_scope_single_star_does_not_cross_directories() -> None:
    scope = ScopeSpec(allowed_paths=["src/*.py"], forbidden_paths=[])
    result = git_mod.check_scope(["src/foo.py", "src/pkg/bar.py"], scope)
    assert not result.valid
    assert result.out_of_scope == ["src/pkg/bar.py"]


# ---------------------------------------------------------------------------
# primary_tree_status
# ---------------------------------------------------------------------------


def test_primary_tree_status_clean(git_repo: Path) -> None:
    assert git_mod.primary_tree_status(git_repo) == ""


def test_primary_tree_status_reports_untracked_file(git_repo: Path) -> None:
    (git_repo / "untracked.txt").write_text("x")
    status = git_mod.primary_tree_status(git_repo)
    assert "untracked.txt" in status
