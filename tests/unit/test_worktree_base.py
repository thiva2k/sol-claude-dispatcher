"""B2 — worktree base identity: measurement, creation, and the invariant.

Every test here uses a **real** git repository and **real** ``git worktree``
commands in ``tmp_path``. Nothing is mocked except two deliberately-malformed
``git worktree list --porcelain`` outputs, which exist to prove the record
parser fails closed on shapes git will not produce on a healthy repository.

The repositories are deliberately built so that ``local HEAD != origin/main``
and so that historical commits are neither tip, because that is the production
shape B2 was found in (`B2-DIAGNOSIS.md` §1.5): the primary tree sat at
``06bfcd61`` while every dispatcher worktree was created at ``6bf20ef``
(``origin/main``), 120 commits ahead.

The invariant under test (§4 of the B2 directive)::

    actual initial worktree HEAD == envelope.repository.base_commit

EXACT full-40-character equality. Not ancestry, not merge-base, not a prefix,
and never "adopt what we observed".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sol_claude_dispatcher import git as git_mod
from sol_claude_dispatcher.errors import (
    GitEvidenceCollectionFailed,
    PolicyViolation,
    WorktreeBaseMismatch,
    WorktreeCreationFailed,
)
from sol_claude_dispatcher.server import assert_worktree_base

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "PATH": "/usr/bin:/bin",
}


def _git(repo: Path, *args: str) -> str:
    env = dict(GIT_ENV, HOME=str(repo.parent))
    result = subprocess.run(
        ["git", *args], cwd=str(repo), env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout.strip()


def _commit(repo: Path, name: str, body: str = "x\n") -> str:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def diverged_repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A repo whose local ``main`` is deliberately BEHIND ``origin/main``.

    Commits ``A -> B -> C``. ``refs/remotes/origin/main`` (and
    ``origin/HEAD``) point at ``C``; the checked-out local ``main`` is reset
    back to ``A``. So:

    * local HEAD (``A``) is an **ancestor** of ``origin/main`` (``C``) — the
      exact shape of task ``49231f6e``, whose recorded base was an ancestor of
      the worktree it was measured against;
    * ``B`` is a historical commit that is neither tip.
    """
    repo = tmp_path / "diverged"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    a = _commit(repo, "a.txt", "A\n")
    b = _commit(repo, "b.txt", "B\n")
    c = _commit(repo, "c.txt", "C\n")
    _git(repo, "update-ref", "refs/remotes/origin/main", c)
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    _git(repo, "reset", "--hard", "-q", a)
    assert _git(repo, "rev-parse", "HEAD") == a
    assert _git(repo, "rev-parse", "origin/main") == c
    return repo, {"A": a, "B": b, "C": c}


# ---------------------------------------------------------------------------
# §5 — the porcelain HEAD line must never be discarded again
# ---------------------------------------------------------------------------


def test_resolve_worktree_reports_actual_head(diverged_repo, tmp_path):
    """The unit-level shape of the whole defect (case I).

    The repository is at ``A``; the worktree is created at ``C``.
    ``git worktree list --porcelain`` prints the true head one line below the
    path the old implementation matched on, and discarded.
    """
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-11111111"
    _git(repo, "worktree", "add", "-q", "--detach", str(target), sha["C"])

    ref = git_mod.resolve_worktree(repo, "sol-11111111")

    assert ref is not None
    assert ref.head_commit == sha["C"]
    assert ref.head_commit != _git(repo, "rev-parse", "HEAD")
    assert ref.path == target


def test_resolve_worktree_returns_none_when_absent(diverged_repo):
    repo, _ = diverged_repo
    assert git_mod.resolve_worktree(repo, "sol-doesnotexist") is None


def test_resolve_worktree_raises_when_git_cannot_be_consulted(tmp_path):
    """"No such worktree" and "we could not look" are different facts."""
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    with pytest.raises(GitEvidenceCollectionFailed):
        git_mod.resolve_worktree(not_a_repo, "sol-11111111")


def test_resolve_worktree_raises_on_record_without_head(diverged_repo, monkeypatch):
    """A matched record with no ``HEAD`` line is unmeasured, not measured-empty."""
    repo, _ = diverged_repo
    porcelain = (
        f"worktree {repo}\n"
        "HEAD " + "a" * 40 + "\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /tmp/wt/sol-11111111\n"
        "branch refs/heads/worktree-sol-11111111\n"
        "\n"
    )
    monkeypatch.setattr(
        git_mod,
        "_run_git",
        lambda *a, **k: subprocess.CompletedProcess(
            args=["git"], returncode=0, stdout=porcelain, stderr=""
        ),
    )
    with pytest.raises(GitEvidenceCollectionFailed):
        git_mod.resolve_worktree(repo, "sol-11111111")


def test_resolve_worktree_rejects_a_non_sha_head(diverged_repo, monkeypatch):
    repo, _ = diverged_repo
    porcelain = (
        "worktree /tmp/wt/sol-11111111\n"
        "HEAD not-a-sha\n"
        "branch refs/heads/worktree-sol-11111111\n"
        "\n"
    )
    monkeypatch.setattr(
        git_mod,
        "_run_git",
        lambda *a, **k: subprocess.CompletedProcess(
            args=["git"], returncode=0, stdout=porcelain, stderr=""
        ),
    )
    with pytest.raises(GitEvidenceCollectionFailed):
        git_mod.resolve_worktree(repo, "sol-11111111")


def test_resolve_worktree_parses_records_not_lines(diverged_repo, tmp_path):
    """Two worktrees: worktree 2 must report worktree 2's head, not the first one's."""
    repo, sha = diverged_repo
    first = tmp_path / "wt" / "sol-aaaaaaaa"
    second = tmp_path / "wt" / "sol-bbbbbbbb"
    _git(repo, "worktree", "add", "-q", "--detach", str(first), sha["B"])
    _git(repo, "worktree", "add", "-q", "--detach", str(second), sha["C"])

    assert git_mod.resolve_worktree(repo, "sol-aaaaaaaa").head_commit == sha["B"]
    assert git_mod.resolve_worktree(repo, "sol-bbbbbbbb").head_commit == sha["C"]


def test_resolve_worktree_handles_detached_head(diverged_repo, tmp_path):
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-cccccccc"
    _git(repo, "worktree", "add", "-q", "--detach", str(target), sha["B"])

    ref = git_mod.resolve_worktree(repo, "sol-cccccccc")
    assert ref.branch is None
    assert ref.head_commit == sha["B"]


def test_resolve_worktree_reports_the_branch_when_attached(diverged_repo, tmp_path):
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-dddddddd"
    _git(repo, "worktree", "add", "-q", "-b", "wtbranch", str(target), sha["B"])

    ref = git_mod.resolve_worktree(repo, "sol-dddddddd")
    assert ref.branch == "refs/heads/wtbranch"
    assert ref.head_commit == sha["B"]


def test_worktree_path_for_still_returns_the_path(diverged_repo, tmp_path):
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-eeeeeeee"
    _git(repo, "worktree", "add", "-q", "--detach", str(target), sha["C"])

    assert git_mod.worktree_path_for(repo, "sol-eeeeeeee") == target
    assert git_mod.worktree_path_for(repo, "sol-nope") is None


def test_worktree_head_matches_rev_parse_inside_the_worktree(diverged_repo, tmp_path):
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-ffffffff"
    _git(repo, "worktree", "add", "-q", "--detach", str(target), sha["B"])

    assert git_mod.worktree_head(target) == _git(target, "rev-parse", "HEAD")
    assert git_mod.worktree_head(target) == sha["B"]
    # M11: measuring in the primary instead of the worktree answers ``A`` here.
    assert git_mod.worktree_head(target) != _git(repo, "rev-parse", "HEAD")


def test_worktree_head_fails_closed_on_non_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(GitEvidenceCollectionFailed):
        git_mod.worktree_head(plain)


# ---------------------------------------------------------------------------
# §4 — the dispatcher owns worktree creation, at an EXACT commit
# ---------------------------------------------------------------------------


def test_create_worktree_uses_the_exact_local_head(diverged_repo, tmp_path):
    """Case A: local HEAD != origin/main, base = local HEAD."""
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-00000001"

    ref = git_mod.create_worktree(
        repo, worktree_name="sol-00000001", path=target, start_commit=sha["A"]
    )

    assert ref.head_commit == sha["A"]
    assert git_mod.worktree_head(target) == sha["A"]
    assert _git(target, "rev-parse", "HEAD") == sha["A"]


def test_create_worktree_uses_origin_main_when_that_is_the_base(diverged_repo, tmp_path):
    """Case B: base = origin/main resolves to C, and the worktree lands on C."""
    repo, sha = diverged_repo
    resolved = git_mod.resolve_base_commit(repo, "origin/main")
    assert resolved == sha["C"]
    target = tmp_path / "wt" / "sol-00000002"

    ref = git_mod.create_worktree(
        repo, worktree_name="sol-00000002", path=target, start_commit=resolved
    )
    assert ref.head_commit == sha["C"]


def test_create_worktree_uses_a_historical_sha(diverged_repo, tmp_path):
    """Case C: a commit that is neither local HEAD nor any remote tip."""
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-00000003"

    ref = git_mod.create_worktree(
        repo, worktree_name="sol-00000003", path=target, start_commit=sha["B"]
    )
    assert ref.head_commit == sha["B"]
    assert sha["B"] not in (_git(repo, "rev-parse", "HEAD"), _git(repo, "rev-parse", "origin/main"))


def test_created_worktree_ignores_a_later_origin_advance(diverged_repo, tmp_path):
    """Case D: origin/main moves AFTER the base was pinned; the tree still starts pinned."""
    repo, sha = diverged_repo
    pinned = git_mod.resolve_base_commit(repo, "HEAD")
    assert pinned == sha["A"]

    # origin/main advances to a brand-new commit after resolution.
    _git(repo, "update-ref", "refs/remotes/origin/main", sha["C"])
    moved = _commit(repo, "late.txt", "LATE\n")
    _git(repo, "update-ref", "refs/remotes/origin/main", moved)
    _git(repo, "reset", "--hard", "-q", sha["A"])

    target = tmp_path / "wt" / "sol-00000004"
    ref = git_mod.create_worktree(
        repo, worktree_name="sol-00000004", path=target, start_commit=pinned
    )
    assert ref.head_commit == pinned
    assert ref.head_commit != moved


def test_create_worktree_refuses_a_start_point_that_is_not_a_full_sha(
    diverged_repo, tmp_path
):
    """A ref, a short sha or a branch name is never an acceptable start-point."""
    repo, sha = diverged_repo
    for bad in ("HEAD", "origin/main", sha["A"][:7], "main"):
        with pytest.raises(WorktreeCreationFailed):
            git_mod.create_worktree(
                repo,
                worktree_name="sol-00000005",
                path=tmp_path / "wt" / "sol-00000005",
                start_commit=bad,
            )
    assert not (tmp_path / "wt" / "sol-00000005").exists()


def test_create_worktree_refuses_an_existing_path(diverged_repo, tmp_path):
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-00000006"
    target.mkdir(parents=True)
    with pytest.raises(WorktreeCreationFailed):
        git_mod.create_worktree(
            repo, worktree_name="sol-00000006", path=target, start_commit=sha["A"]
        )


def test_create_worktree_refuses_an_unknown_commit(diverged_repo, tmp_path):
    repo, _ = diverged_repo
    with pytest.raises(WorktreeCreationFailed):
        git_mod.create_worktree(
            repo,
            worktree_name="sol-00000007",
            path=tmp_path / "wt" / "sol-00000007",
            start_commit="0" * 40,
        )


def test_create_worktree_leaves_the_primary_tree_unchanged(diverged_repo, tmp_path):
    """Case L: the dispatcher's own worktree creation must not move the primary."""
    repo, sha = diverged_repo
    before_head = _git(repo, "rev-parse", "HEAD")
    before_status = git_mod.primary_tree_status(repo)

    git_mod.create_worktree(
        repo,
        worktree_name="sol-00000008",
        path=tmp_path / "wt" / "sol-00000008",
        start_commit=sha["C"],
    )

    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert git_mod.primary_tree_status(repo) == before_status


def test_create_worktree_outside_the_repository_adds_no_untracked_entry(
    diverged_repo, tmp_path
):
    """K-2, structurally: a container outside the repo cannot dirty the primary tree.

    The production defect was the CLI placing ``.claude/worktrees/`` INSIDE the
    repository, where it appears as a new untracked entry and trips the
    primary-tree non-interference invariant on the first dispatch into any
    newly-authorised repository.
    """
    repo, sha = diverged_repo
    target = tmp_path / "outside" / "sol-00000009"

    git_mod.create_worktree(
        repo, worktree_name="sol-00000009", path=target, start_commit=sha["A"]
    )

    assert not target.is_relative_to(repo)
    assert git_mod.primary_tree_status(repo) == ""
    assert not (repo / ".claude").exists()


# ---------------------------------------------------------------------------
# §4 — the invariant itself
# ---------------------------------------------------------------------------


def _assert(worktree: Path, expected: str):
    return assert_worktree_base(
        worktree,
        expected_base_commit=expected,
        task_id="11111111-1111-4111-8111-111111111111",
        worktree_name="sol-11111111",
        base_ref="HEAD",
        phase="dispatch",
    )


def test_assert_worktree_base_accepts_exact_match(diverged_repo, tmp_path):
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-11111111"
    git_mod.create_worktree(
        repo, worktree_name="sol-11111111", path=target, start_commit=sha["A"]
    )
    assert _assert(target, sha["A"]) == sha["A"]


def test_assert_worktree_base_refuses_mismatch(diverged_repo, tmp_path):
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-11111111"
    git_mod.create_worktree(
        repo, worktree_name="sol-11111111", path=target, start_commit=sha["C"]
    )
    with pytest.raises(WorktreeBaseMismatch):
        _assert(target, sha["A"])


def test_mismatch_payload_names_both_commits(diverged_repo, tmp_path):
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-11111111"
    git_mod.create_worktree(
        repo, worktree_name="sol-11111111", path=target, start_commit=sha["C"]
    )
    with pytest.raises(WorktreeBaseMismatch) as excinfo:
        _assert(target, sha["A"])

    payload = excinfo.value.to_payload()
    details = payload["details"]
    assert details["expected_base_commit"] == sha["A"]
    assert details["actual_head_commit"] == sha["C"]
    assert details["base_ref"] == "HEAD"
    assert details["worktree_name"] == "sol-11111111"
    assert details["worktree_path"] == str(target)
    assert details["task_id"] == "11111111-1111-4111-8111-111111111111"
    assert details["phase"] == "dispatch"
    # Sol needs the observed SHA to re-dispatch successfully.
    assert sha["C"] in payload["remediation"]
    assert payload["retryable"] is False


def test_ancestor_is_still_a_mismatch(diverged_repo, tmp_path):
    """Case E — the shape of task ``49231f6e``.

    The recorded base (``A``) is a genuine ANCESTOR of the worktree's head
    (``C``). An ancestry- or merge-base-tolerant check would have waved through
    the worst of the three preserved production failures, where 120 commits of
    other people's work were attributed to the worker.
    """
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-11111111"
    git_mod.create_worktree(
        repo, worktree_name="sol-11111111", path=target, start_commit=sha["C"]
    )
    assert (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha["A"], sha["C"]],
            cwd=str(repo),
            env=dict(GIT_ENV, HOME=str(repo.parent)),
        ).returncode
        == 0
    ), "fixture precondition: the recorded base must be an ancestor"

    with pytest.raises(WorktreeBaseMismatch):
        _assert(target, sha["A"])


def test_descendant_is_still_a_mismatch(diverged_repo, tmp_path):
    """The mirror of case E: the worktree sits at an ancestor of the recorded base."""
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-11111111"
    git_mod.create_worktree(
        repo, worktree_name="sol-11111111", path=target, start_commit=sha["A"]
    )
    with pytest.raises(WorktreeBaseMismatch):
        _assert(target, sha["C"])


def test_one_commit_of_difference_is_still_a_mismatch(diverged_repo, tmp_path):
    """Case F: exactly one commit apart is still a refusal."""
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-11111111"
    git_mod.create_worktree(
        repo, worktree_name="sol-11111111", path=target, start_commit=sha["B"]
    )
    assert _git(repo, "rev-list", "--count", f"{sha['A']}..{sha['B']}") == "1"
    with pytest.raises(WorktreeBaseMismatch):
        _assert(target, sha["A"])


def test_short_sha_prefix_is_not_accepted(diverged_repo, tmp_path):
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-11111111"
    git_mod.create_worktree(
        repo, worktree_name="sol-11111111", path=target, start_commit=sha["A"]
    )
    with pytest.raises(WorktreeBaseMismatch):
        _assert(target, sha["A"][:7])


def test_mismatch_is_not_a_policy_violation(diverged_repo, tmp_path):
    """The worker did nothing wrong; the dispatcher could not establish its ground."""
    repo, sha = diverged_repo
    target = tmp_path / "wt" / "sol-11111111"
    git_mod.create_worktree(
        repo, worktree_name="sol-11111111", path=target, start_commit=sha["C"]
    )
    with pytest.raises(WorktreeBaseMismatch) as excinfo:
        _assert(target, sha["A"])
    assert not isinstance(excinfo.value, PolicyViolation)
    assert excinfo.value.retryable is False


def test_assert_worktree_base_fails_closed_when_it_cannot_measure(tmp_path):
    """An unmeasurable worktree is never "probably fine"."""
    plain = tmp_path / "gone"
    plain.mkdir()
    with pytest.raises(GitEvidenceCollectionFailed):
        _assert(plain, "a" * 40)


# ---------------------------------------------------------------------------
# §5 — evidence integrity: the false-negative the invariant protects against
# ---------------------------------------------------------------------------


def test_a_forbidden_change_that_matches_the_recorded_base_is_invisible(
    diverged_repo, tmp_path
):
    """Case G at the measurement level (`B2-DIAGNOSIS.md` §5.1).

    Evidence is ``git diff <recorded-base>`` taken INSIDE the worktree, so it
    reports ``(W-B) u worker-changes`` — and those two components CANCEL. A
    worker that edits a forbidden tracked file to content identical to the
    recorded base produces no diff line at all: the path never enters
    ``changed_paths``, never reaches ``check_scope``, and never appears in
    ``diff.patch``.

    This test documents the hazard as executable fact. The dispatcher's answer
    is not to detect the cancellation — it cannot — but to refuse to collect
    evidence at all when the worktree is not on the recorded base.
    """
    repo, _ = diverged_repo
    (repo / "forbidden").mkdir()
    (repo / "forbidden" / "f.py").write_text("BASE CONTENT\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "forbidden at base")
    base = _git(repo, "rev-parse", "HEAD")

    (repo / "forbidden" / "f.py").write_text("DRIFTED CONTENT\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "forbidden drifted")
    drifted = _git(repo, "rev-parse", "HEAD")

    # The worktree is on the WRONG commit, exactly as the CLI left it in
    # production.
    target = tmp_path / "wt" / "sol-11111111"
    git_mod.create_worktree(
        repo, worktree_name="sol-11111111", path=target, start_commit=drifted
    )
    # A worker reverts a forbidden file to the recorded base's content.
    (target / "forbidden" / "f.py").write_text("BASE CONTENT\n")

    evidence = git_mod.collect_diff_evidence(target, base)
    scope = git_mod.check_scope(
        evidence.changed_paths,
        __import__(
            "sol_claude_dispatcher.models", fromlist=["ScopeSpec"]
        ).ScopeSpec(allowed_paths=["src/**"], forbidden_paths=["forbidden/**"]),
    )

    # The false negative, proven: a genuine forbidden-path change is recorded
    # as a clean, in-scope run.
    assert "forbidden/f.py" not in evidence.changed_paths
    assert scope.valid is True
    assert scope.forbidden == []

    # And the invariant refuses this run before any of that can be believed.
    with pytest.raises(WorktreeBaseMismatch):
        _assert(target, base)


# ---------------------------------------------------------------------------
# §6 — the resume policy anchor binds the IMMUTABLE base identity
# ---------------------------------------------------------------------------


def _fingerprint(**overrides) -> str:
    from sol_claude_dispatcher.models import WorkerRole
    from sol_claude_dispatcher.worker_context import context_fingerprint

    kwargs = dict(
        role=WorkerRole.IMPLEMENTER,
        task_envelope_id="task-1",
        base_commit="a" * 40,
        worktree_name="sol-11111111",
        skill_projection=None,
        guidance_projection=None,
    )
    kwargs.update(overrides)
    return context_fingerprint(**kwargs)


def test_context_fingerprint_binds_the_base_commit():
    """Lane M found the recipe covered neither the base nor the worktree head.

    The drift detector a resume runs through was therefore structurally blind
    to a base mismatch. The base is immutable for a task, so binding it costs
    nothing on a legitimate resume and makes a silently-redefined base
    impossible to hide inside the anchor.
    """
    assert _fingerprint(base_commit="b" * 40) != _fingerprint()


def test_context_fingerprint_binds_the_worktree_identity():
    assert _fingerprint(worktree_name="sol-22222222") != _fingerprint()


def test_context_fingerprint_is_stable_for_the_same_base():
    assert _fingerprint() == _fingerprint()


def test_context_fingerprint_version_records_the_recipe_change():
    from sol_claude_dispatcher.worker_context import CONTEXT_FINGERPRINT_VERSION

    assert CONTEXT_FINGERPRINT_VERSION == "worker-context-fingerprint/v2"


def test_context_fingerprint_requires_the_base_commit():
    """A recipe that can be called without the base is a recipe that will be."""
    from sol_claude_dispatcher.models import WorkerRole
    from sol_claude_dispatcher.worker_context import context_fingerprint

    with pytest.raises(TypeError):
        context_fingerprint(
            role=WorkerRole.IMPLEMENTER,
            task_envelope_id="task-1",
            skill_projection=None,
            guidance_projection=None,
        )
