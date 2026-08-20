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
    def git_top_level(path: Path) -> Path
    def git_top_level_or_none(path: Path) -> Path | None
    def write_full_diff(worktree: Path, base_commit: str, dest: Path) -> int
    def primary_tree_status(repo: Path) -> str

Fail-closed rule for evidence (§12, remediation P0-3): every git command whose
output the dispatcher *reasons about* is checked for success. A command that
could not be run, timed out, or exited non-zero raises
:class:`~sol_claude_dispatcher.errors.GitEvidenceCollectionFailed` — it never
degrades into an empty result, because "git could not tell us what changed" and
"nothing changed" must never produce the same observation.
"""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import GitEvidenceCollectionFailed, InvalidRepository
from .models import ScopeSpec, worktree_name_for

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .project_guidance import RepositoryIdentity

__all__ = [
    "DiffEvidence",
    "ScopeCheck",
    "is_git_repository",
    "git_top_level",
    "git_top_level_or_none",
    "collect_repository_identity",
    "resolve_base_commit",
    "create_worktree_name",
    "worktree_path_for",
    "collect_diff_evidence",
    "write_full_diff",
    "check_scope",
    "primary_tree_status",
]

#: Per-invocation timeout for the small, bounded git commands this module
#: runs. Generous enough for a real repository, short enough that a hung git
#: process cannot wedge a dispatch indefinitely.
_GIT_TIMEOUT_SECONDS = 60

#: Environment variables that would silently redirect a git command away from
#: the working tree named by ``cwd``. The dispatcher derives repository
#: *identity* from ``git rev-parse --show-toplevel``, so an inherited
#: ``GIT_DIR``/``GIT_WORK_TREE`` in the dispatcher's own environment could
#: otherwise make every command in this module answer about a different
#: repository than the one the caller asked about. Stripped unconditionally:
#: this module always addresses a repository by ``cwd``, never by env.
_GIT_ENV_REDIRECTS: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES",
    "GIT_NAMESPACE",
)

#: Longest stderr excerpt copied into an error payload (§29: no dumps).
_STDERR_EXCERPT = 400


def _git_env() -> dict[str, str]:
    """Environment for every git command this module runs."""
    env = dict(os.environ)
    for key in _GIT_ENV_REDIRECTS:
        env.pop(key, None)
    # Never block waiting for a credential prompt: this module only reads local
    # state, and a prompt would turn a bounded command into a hang.
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Read-only commands must not take (or wait for) the index lock.
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


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
        env=_git_env(),
    )


def _git_checked(
    args: list[str],
    *,
    cwd: Path,
    what: str,
    ok_returncodes: tuple[int, ...] = (0,),
    timeout: int = _GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>``, failing closed on anything that is not a clean result.

    Raises :class:`GitEvidenceCollectionFailed` when git could not be started,
    timed out, or exited with a code outside ``ok_returncodes``. The caller
    therefore never has to decide what an empty stdout "probably" meant.
    """
    try:
        result = _run_git(args, cwd=cwd, timeout=timeout)
    except FileNotFoundError as exc:
        raise GitEvidenceCollectionFailed(
            "git evidence could not be collected: the git executable was not found.",
            details={"what": what, "command": ["git", *args], "cwd": str(cwd)},
            remediation="Install git, or make it reachable on the dispatcher's PATH.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitEvidenceCollectionFailed(
            "git evidence could not be collected: the git command timed out.",
            details={
                "what": what,
                "command": ["git", *args],
                "cwd": str(cwd),
                "timeout_seconds": timeout,
            },
        ) from exc
    except OSError as exc:
        raise GitEvidenceCollectionFailed(
            "git evidence could not be collected: the git command could not be started.",
            details={
                "what": what,
                "command": ["git", *args],
                "cwd": str(cwd),
                "reason": str(exc)[:_STDERR_EXCERPT],
            },
        ) from exc

    if result.returncode not in ok_returncodes:
        raise GitEvidenceCollectionFailed(
            "git evidence could not be collected: the git command failed.",
            details={
                "what": what,
                "command": ["git", *args],
                "cwd": str(cwd),
                "returncode": result.returncode,
                "stderr": result.stderr.strip()[:_STDERR_EXCERPT],
            },
        )
    return result


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
    #: Size of the *untruncated* patch in bytes. Non-zero even when
    #: ``truncated`` is true, so a reader can always tell how much of the
    #: patch ``diff_text`` actually represents rather than having to trust
    #: that "no marker" means "complete".
    diff_total_bytes: int = 0


@dataclass(frozen=True)
class ScopeCheck:
    """Result of comparing changed paths against the declared scope (§13)."""

    valid: bool
    out_of_scope: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)


def is_git_repository(path: Path) -> bool:
    """True when ``path`` is inside a git work tree.

    Fail-closed by construction: any failure to *prove* the path is inside a
    work tree answers ``False``. Note that this proves membership only — it
    says nothing about whether ``path`` is the repository's top level. Use
    :func:`git_top_level` when repository *identity* is the question.
    """
    try:
        result = _run_git(
            ["rev-parse", "--is-inside-work-tree"], cwd=path, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_top_level(path: Path) -> Path:
    """Canonical git top-level directory containing ``path`` (P0-2).

    This is *the* repository identity primitive. It asks git itself — via
    ``git rev-parse --show-toplevel``, run as an argv list with ``cwd=path``,
    never through a shell and never with an inherited ``GIT_DIR`` — and then
    canonicalises the answer with ``Path.resolve()`` so symlinked spellings
    collapse to one identity.

    Fails closed with :class:`InvalidRepository` when ``path`` is not inside a
    work tree, when git could not be run, or when the answer is not a usable
    absolute directory. It never guesses at a top level from the caller's own
    spelling of the path.
    """
    candidate = Path(path)
    try:
        result = _run_git(["rev-parse", "--show-toplevel"], cwd=candidate, timeout=10)
    except FileNotFoundError as exc:
        raise InvalidRepository(
            "Repository identity could not be established: git was not found.",
            details={"path": str(candidate)},
            remediation="Install git, or make it reachable on the dispatcher's PATH.",
        ) from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InvalidRepository(
            "Repository identity could not be established: git could not be run.",
            details={"path": str(candidate), "reason": str(exc)[:_STDERR_EXCERPT]},
        ) from exc

    if result.returncode != 0:
        raise InvalidRepository(
            "Repository identity could not be established: path is not inside a "
            "git work tree.",
            details={
                "path": str(candidate),
                "returncode": result.returncode,
                "stderr": result.stderr.strip()[:_STDERR_EXCERPT],
            },
        )

    raw = result.stdout.strip()
    if not raw or not raw.startswith("/"):
        raise InvalidRepository(
            "Repository identity could not be established: git returned an "
            "unusable top-level path.",
            details={"path": str(candidate), "got": raw[:_STDERR_EXCERPT]},
        )

    top_level = Path(raw).resolve()
    if not top_level.is_dir():
        raise InvalidRepository(
            "Repository identity could not be established: the reported git "
            "top level is not a directory.",
            details={"path": str(candidate), "top_level": str(top_level)},
        )
    return top_level


def git_top_level_or_none(path: Path) -> Path | None:
    """:func:`git_top_level`, or ``None`` when identity cannot be established.

    For callers (such as lock identity) that have a meaningful non-git
    fallback. Security decisions must use :func:`git_top_level` instead, so
    that "could not determine" is an explicit refusal rather than a ``None``
    that a caller might read as "fine".
    """
    try:
        return git_top_level(path)
    except InvalidRepository:
        return None


def collect_repository_identity(repo: Path) -> "RepositoryIdentity":
    """Measure the four identity facts project guidance pins (Gate 4.5 §16).

    Run this against the **canonical primary repository** named by
    ``envelope.repository.root``, never against a dispatcher-created worktree.
    Inside a linked worktree ``--show-toplevel`` answers with the worktree path
    and ``--absolute-git-dir`` with ``<primary>/.git/worktrees/<name>``; both
    would mismatch the manifest pin and refuse a legitimate dispatch
    (RULINGS §4, Lane D R2).

    Three traps this function closes, none of which the guidance engine can see:

    * ``git rev-parse --git-dir`` returns the literal string ``.git`` at the top
      level, so ``--absolute-git-dir`` is used instead;
    * a repository with **more than one root commit** is a fail-closed
      condition, not a "pick the first" — the caller must never guess which
      history the pin meant;
    * a repository with no ``origin`` remote yields ``""`` rather than an error,
      because "no origin" is a perfectly measurable fact and the engine's
      four-field comparison is where it becomes a refusal.
    """
    from .project_guidance import RepositoryIdentity

    toplevel = _git_checked(
        ["rev-parse", "--show-toplevel"], cwd=repo, what="repository toplevel"
    ).stdout.strip()
    git_dir = _git_checked(
        ["rev-parse", "--absolute-git-dir"], cwd=repo, what="repository git dir"
    ).stdout.strip()

    # `git config --get` exits 1 when the key is simply absent. That is not a
    # failure to measure; it is the measurement.
    origin = _run_git(["config", "--get", "remote.origin.url"], cwd=repo)
    origin_url = origin.stdout.strip() if origin.returncode == 0 else ""

    roots = _git_checked(
        ["rev-list", "--max-parents=0", "HEAD"], cwd=repo, what="repository root commit"
    ).stdout.split()
    if len(roots) != 1:
        raise GitEvidenceCollectionFailed(
            "The repository does not have exactly one root commit, so its "
            "identity cannot be pinned.",
            details={"repo": str(repo), "root_commits": roots[:8], "count": len(roots)},
            remediation="A guidance manifest pins one root commit. Do not pick "
            "one of several; decide which history is canonical and record it.",
        )

    return RepositoryIdentity(
        toplevel=toplevel,
        git_dir=git_dir,
        origin_url=origin_url,
        root_commit=roots[0],
    )


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
    """Locate the worktree Claude created, via ``git worktree list --porcelain``.

    ``None`` means git answered successfully and no worktree with that name
    exists. If git itself could not be consulted, this raises
    :class:`GitEvidenceCollectionFailed` rather than returning ``None`` — the
    two are different facts and the caller must not conflate "the worker did
    not create a worktree" with "we could not look".
    """
    result = _git_checked(
        ["worktree", "list", "--porcelain"], cwd=repo, what="git worktree list"
    )

    for line in result.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        candidate = Path(line[len("worktree ") :].strip())
        if candidate.name == worktree_name:
            return candidate
    return None


def _fold_untracked(worktree: Path) -> list[str]:
    """Untracked files, so an unauthorised new file cannot slip past scope.

    Fails closed: previously a failed ``ls-files`` returned ``[]``, which is
    indistinguishable from "no untracked files" and would have let an
    unauthorised new file pass the scope check unseen.
    """
    result = _git_checked(
        ["ls-files", "--others", "--exclude-standard"],
        cwd=worktree,
        what="git ls-files --others --exclude-standard",
    )
    return [line for line in result.stdout.splitlines() if line]


def collect_diff_evidence(
    worktree: Path, base_commit: str, *, max_diff_bytes: int = 2_000_000
) -> DiffEvidence:
    """Gather status/diff/stat/check evidence from a worktree (§12).

    Runs, in order: ``git status --porcelain``, ``git diff --name-only``,
    ``git diff --stat``, ``git diff``, ``git diff --check``, plus
    ``git ls-files --others --exclude-standard`` to fold untracked files into
    ``changed_paths``. The full diff is truncated at ``max_diff_bytes`` for the
    in-memory value; ``diff_total_bytes`` always records the untruncated size,
    and :func:`write_full_diff` streams the complete patch to
    ``evidence/diff.patch`` without holding it in memory.

    Every command above is checked. If any of them cannot be run, times out, or
    exits non-zero, this raises :class:`GitEvidenceCollectionFailed` — it never
    returns a partially-observed ``DiffEvidence``, because a caller cannot tell
    "clean" from "unmeasured" once the evidence object exists.
    """
    status_result = _git_checked(
        ["status", "--porcelain"], cwd=worktree, what="git status --porcelain"
    )
    porcelain_status = status_result.stdout

    name_only_result = _git_checked(
        ["diff", "--name-only", base_commit],
        cwd=worktree,
        what="git diff --name-only",
    )
    tracked_changed = [
        line for line in name_only_result.stdout.splitlines() if line
    ]

    untracked = _fold_untracked(worktree)

    changed_paths: list[str] = []
    for path in [*tracked_changed, *untracked]:
        if path not in changed_paths:
            changed_paths.append(path)

    stat_result = _git_checked(
        ["diff", "--stat", base_commit], cwd=worktree, what="git diff --stat"
    )
    diff_stat = stat_result.stdout

    diff_result = _git_checked(
        ["diff", base_commit], cwd=worktree, what="git diff"
    )
    diff_text_raw = diff_result.stdout

    diff_bytes = diff_text_raw.encode("utf-8", errors="replace")
    diff_total_bytes = len(diff_bytes)
    truncated = diff_total_bytes > max_diff_bytes
    if truncated:
        diff_text = diff_bytes[:max_diff_bytes].decode("utf-8", errors="ignore")
    else:
        diff_text = diff_text_raw

    # `git diff --check` exits 0 when clean and non-zero (1 or 2, depending on
    # the git version and the class of problem) when it *found* whitespace or
    # conflict-marker problems. Those are legitimate findings, not collection
    # failures. Anything outside that set — 128 for a bad revision, say — means
    # the check did not run, and must not be reported as "passed".
    check_result = _git_checked(
        ["diff", "--check", base_commit],
        cwd=worktree,
        what="git diff --check",
        ok_returncodes=(0, 1, 2),
    )
    if check_result.stderr.strip().startswith("fatal:"):
        raise GitEvidenceCollectionFailed(
            "git evidence could not be collected: git diff --check reported a "
            "fatal error.",
            details={
                "what": "git diff --check",
                "cwd": str(worktree),
                "returncode": check_result.returncode,
                "stderr": check_result.stderr.strip()[:_STDERR_EXCERPT],
            },
        )
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
        diff_total_bytes=diff_total_bytes,
    )


def write_full_diff(worktree: Path, base_commit: str, dest: Path) -> int:
    """Stream the *complete* patch to ``dest`` (0600) and return its byte size.

    ``collect_diff_evidence`` caps the diff it holds in memory, so persisting
    ``DiffEvidence.diff_text`` produces a silently-shortened
    ``evidence/diff.patch``. This writes the untruncated patch straight from
    git's stdout to a file, so evidence is complete without the dispatcher ever
    materialising an unbounded string.

    Fails closed with :class:`GitEvidenceCollectionFailed`; on failure no
    partial file is left behind at ``dest``.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp_path = dest.parent / f".{dest.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"

    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.chmod(tmp_path, 0o600)
        try:
            with os.fdopen(fd, "wb") as out:
                completed = subprocess.run(
                    ["git", "diff", base_commit],
                    cwd=str(worktree),
                    stdout=out,
                    stderr=subprocess.PIPE,
                    timeout=_GIT_TIMEOUT_SECONDS,
                    env=_git_env(),
                )
                out.flush()
                os.fsync(out.fileno())
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitEvidenceCollectionFailed(
                "git evidence could not be collected: the full diff could not "
                "be written.",
                details={
                    "what": "git diff (full patch)",
                    "cwd": str(worktree),
                    "dest": str(dest),
                    "reason": str(exc)[:_STDERR_EXCERPT],
                },
            ) from exc

        if completed.returncode != 0:
            raise GitEvidenceCollectionFailed(
                "git evidence could not be collected: the full diff could not "
                "be written.",
                details={
                    "what": "git diff (full patch)",
                    "cwd": str(worktree),
                    "returncode": completed.returncode,
                    "stderr": completed.stderr.decode("utf-8", errors="replace")
                    .strip()[:_STDERR_EXCERPT],
                },
            )

        size = tmp_path.stat().st_size
        os.replace(tmp_path, dest)
        return size
    except GitEvidenceCollectionFailed:
        # Never leave a half-written patch where a reader would take it for
        # complete evidence.
        _unlink_quietly(tmp_path)
        raise
    except OSError as exc:
        _unlink_quietly(tmp_path)
        raise GitEvidenceCollectionFailed(
            "git evidence could not be collected: the full diff could not be "
            "written.",
            details={
                "what": "git diff (full patch)",
                "cwd": str(worktree),
                "dest": str(dest),
                "reason": str(exc)[:_STDERR_EXCERPT],
            },
        ) from exc
    except BaseException:
        _unlink_quietly(tmp_path)
        raise


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


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
    """``git status --porcelain`` of the primary tree, to prove non-interference.

    Fails closed: this value is read as "the primary tree is clean" when it is
    empty, so a failed ``git status`` must never be allowed to produce ``""``.
    """
    result = _git_checked(
        ["status", "--porcelain"], cwd=repo, what="git status --porcelain (primary tree)"
    )
    return result.stdout
