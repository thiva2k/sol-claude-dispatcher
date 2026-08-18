"""Git evidence collection and scope enforcement (brief §12, §13). — Wave 2.

Every function here shells out with ``subprocess`` / ``asyncio`` using **argv
lists**, never ``shell=True``, and never interpolates user text into a command.

This module reads and reports. It does not commit, merge, push, rebase, reset,
or delete worktrees, and it never applies a worktree's changes to the primary
tree (§12). Evidence is preserved for Sol, including after a failure.

Contract (authoritative, see ``docs/INTERFACES.md``)::

    def resolve_base_commit(repo: Path, base_ref: str) -> str
    def create_worktree_name(task_id: str) -> str
    def worktree_path_for(repo: Path, worktree_name: str) -> Path | None
    def collect_diff_evidence(worktree: Path, base_commit: str) -> DiffEvidence
    def check_scope(changed_paths, scope) -> ScopeCheck
    def is_git_repository(path: Path) -> bool
    def primary_tree_status(repo: Path) -> str
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .models import ScopeSpec

__all__ = [
    "DiffEvidence",
    "ScopeCheck",
    "is_git_repository",
    "resolve_base_commit",
    "create_worktree_name",
    "worktree_path_for",
    "collect_diff_evidence",
    "check_scope",
    "primary_tree_status",
]


@dataclass(frozen=True)
class DiffEvidence:
    """Everything the dispatcher observed about a worktree's changes (§12)."""

    base_commit: str
    changed_paths: list[str] = field(default_factory=list)
    diff_text: str = ""
    diff_stat: str = ""
    porcelain_status: str = ""
    diff_check_passed: bool = True
    diff_check_output: str = ""
    truncated: bool = False


@dataclass(frozen=True)
class ScopeCheck:
    """Result of comparing changed paths against the declared scope (§13)."""

    valid: bool
    out_of_scope: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)


def is_git_repository(path: Path) -> bool:
    """True when ``path`` is inside a git work tree."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §git")


def resolve_base_commit(repo: Path, base_ref: str) -> str:
    """Resolve ``base_ref`` to a full 40-character commit SHA."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §git")


def create_worktree_name(task_id: str) -> str:
    """Deterministic ``sol-<short-task-id>``; validated, never user text (§12)."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §git")


def worktree_path_for(repo: Path, worktree_name: str) -> Path | None:
    """Locate the worktree Claude created, via ``git worktree list --porcelain``."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §git")


def collect_diff_evidence(
    worktree: Path, base_commit: str, *, max_diff_bytes: int = 2_000_000
) -> DiffEvidence:
    """Gather status/diff/stat/check evidence from a worktree (§12)."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §git")


def check_scope(changed_paths: list[str], scope: ScopeSpec) -> ScopeCheck:
    """Compare changed paths against allowed/forbidden patterns (§13)."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §git")


def primary_tree_status(repo: Path) -> str:
    """``git status --porcelain`` of the primary tree, to prove non-interference."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §git")
