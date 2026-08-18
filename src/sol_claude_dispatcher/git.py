"""Git evidence collection and scope enforcement (brief §12, §13). — Wave 2.

Every function here shells out with ``subprocess`` using **argv lists**, never
``shell=True``, and never interpolates user text into a command.

This module reads and reports. It does not commit, merge, push, rebase, reset,
or delete worktrees, and it never applies a worktree's changes to the primary
tree (§12). Evidence is preserved for Sol, including after a failure.

Note on concurrency: every public function here has a **synchronous**
signature per ``docs/INTERFACES.md`` §5 (none of them are ``async def``), so
subprocesses are launched with ``subprocess.run([...])`` — an argv list, never
a shell string — which satisfies ground rule 0.1 just as
``asyncio.create_subprocess_exec`` would. Callers that need this off the event
loop should run it in a thread.

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

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .errors import InvalidRepository
from .models import ScopeSpec, worktree_name_for

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

#: Per-invocation timeout for the small, bounded git commands this module
#: runs. Generous enough for a real repository, short enough that a hung git
#: process cannot wedge a dispatch indefinitely.
_GIT_TIMEOUT_SECONDS = 60


def _run_git(
    args: list[str], *, cwd: Path, timeout: int = _GIT_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` in ``cwd`` as an argv list. Never raises on nonzero exit."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


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
    try:
        result = _run_git(
            ["rev-parse", "--is-inside-work-tree"], cwd=path, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def resolve_base_commit(repo: Path, base_ref: str) -> str:
    """Resolve ``base_ref`` to a full 40-character commit SHA."""
    try:
        result = _run_git(
            ["rev-parse", "--verify", f"{base_ref}^{{commit}}"], cwd=repo
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InvalidRepository(
            "Could not resolve base_ref: git could not be run.",
            details={"repo": str(repo), "base_ref": base_ref, "reason": str(exc)},
        ) from exc

    if result.returncode != 0:
        raise InvalidRepository(
            "base_ref does not resolve to a commit in this repository.",
            details={
                "repo": str(repo),
                "base_ref": base_ref,
                "stderr": result.stderr.strip(),
            },
        )
    sha = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise InvalidRepository(
            "git rev-parse did not return a full commit SHA.",
            details={"repo": str(repo), "base_ref": base_ref, "got": sha},
        )
    return sha


def create_worktree_name(task_id: str) -> str:
    """Deterministic ``sol-<short-task-id>``; validated, never user text (§12).

    Delegates to :func:`sol_claude_dispatcher.models.worktree_name_for`, the
    single naming rule in this codebase. Never accepts or derives a name from
    raw caller-supplied text.
    """
    return worktree_name_for(task_id)


def worktree_path_for(repo: Path, worktree_name: str) -> Path | None:
    """Locate the worktree Claude created, via ``git worktree list --porcelain``."""
    try:
        result = _run_git(["worktree", "list", "--porcelain"], cwd=repo)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        candidate = Path(line[len("worktree ") :].strip())
        if candidate.name == worktree_name:
            return candidate
    return None


def _fold_untracked(worktree: Path) -> list[str]:
    """Untracked files, so an unauthorised new file cannot slip past scope."""
    try:
        result = _run_git(
            ["ls-files", "--others", "--exclude-standard"], cwd=worktree
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def collect_diff_evidence(
    worktree: Path, base_commit: str, *, max_diff_bytes: int = 2_000_000
) -> DiffEvidence:
    """Gather status/diff/stat/check evidence from a worktree (§12).

    Runs, in order: ``git status --porcelain``, ``git diff --name-only``,
    ``git diff --stat``, ``git diff``, ``git diff --check``, plus
    ``git ls-files --others --exclude-standard`` to fold untracked files into
    ``changed_paths``. The full diff is truncated at ``max_diff_bytes``; the
    caller is responsible for persisting the untruncated text to
    ``evidence/diff.patch`` before this value would otherwise be lost.
    """
    status_result = _run_git(["status", "--porcelain"], cwd=worktree)
    porcelain_status = status_result.stdout

    name_only_result = _run_git(["diff", "--name-only", base_commit], cwd=worktree)
    tracked_changed = [
        line for line in name_only_result.stdout.splitlines() if line
    ]

    untracked = _fold_untracked(worktree)

    changed_paths: list[str] = []
    for path in [*tracked_changed, *untracked]:
        if path not in changed_paths:
            changed_paths.append(path)

    stat_result = _run_git(["diff", "--stat", base_commit], cwd=worktree)
    diff_stat = stat_result.stdout

    diff_result = _run_git(["diff", base_commit], cwd=worktree)
    diff_text_raw = diff_result.stdout

    diff_bytes = diff_text_raw.encode("utf-8", errors="replace")
    truncated = len(diff_bytes) > max_diff_bytes
    if truncated:
        diff_text = diff_bytes[:max_diff_bytes].decode("utf-8", errors="ignore")
    else:
        diff_text = diff_text_raw

    check_result = _run_git(["diff", "--check", base_commit], cwd=worktree)
    diff_check_passed = check_result.returncode == 0
    diff_check_output = check_result.stdout + check_result.stderr

    return DiffEvidence(
        base_commit=base_commit,
        changed_paths=changed_paths,
        diff_text=diff_text,
        diff_stat=diff_stat,
        porcelain_status=porcelain_status,
        diff_check_passed=diff_check_passed,
        diff_check_output=diff_check_output,
        truncated=truncated,
    )


def _translate_glob(pattern: str) -> re.Pattern[str]:
    """Compile a scope glob pattern to a regex.

    ``**`` matches any sequence of characters, including ``/``. ``*`` matches
    any run of characters *excluding* ``/``. ``?`` matches exactly one
    non-separator character. Everything else is a literal.
    """
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(_translate_glob(p).match(path) for p in patterns)


def check_scope(changed_paths: list[str], scope: ScopeSpec) -> ScopeCheck:
    """Compare changed paths against allowed/forbidden patterns (§13).

    ``forbidden_paths`` wins over ``allowed_paths``. An empty ``allowed_paths``
    means unrestricted; a non-empty one means a path must match at least one
    pattern. ``valid`` is ``not out_of_scope and not forbidden``.
    """
    out_of_scope: list[str] = []
    forbidden: list[str] = []

    for path in changed_paths:
        if scope.forbidden_paths and _matches_any(path, scope.forbidden_paths):
            forbidden.append(path)
            continue
        if scope.allowed_paths and not _matches_any(path, scope.allowed_paths):
            out_of_scope.append(path)

    return ScopeCheck(
        valid=not out_of_scope and not forbidden,
        out_of_scope=out_of_scope,
        forbidden=forbidden,
    )


def primary_tree_status(repo: Path) -> str:
    """``git status --porcelain`` of the primary tree, to prove non-interference."""
    result = _run_git(["status", "--porcelain"], cwd=repo)
    return result.stdout
