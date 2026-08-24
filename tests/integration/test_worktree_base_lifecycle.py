"""B2 end-to-end: the dispatcher owns the worktree, and proves what it measured.

Every test drives ``Dispatcher`` against a real git repository, real
``git worktree`` commands and the fake worker binary. No real ``claude`` process
is ever started, and nothing outside ``tmp_path`` is touched.

The repositories here are built so the recorded base is **not** the repository's
current ``HEAD``, because that is the production shape B2 was found in: the
dispatcher recorded one commit and the tree was on another, and every diff,
every scope decision and ``evidence/diff.patch`` described a tree that never
existed.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sol_claude_dispatcher import server as server_mod
from sol_claude_dispatcher.models import TaskState

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "PATH": "/usr/bin:/bin",
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        env=dict(GIT_ENV, HOME=str(repo.parent)),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout.strip()


@pytest.fixture
def diverged_repo(seeded_repo: Path) -> dict[str, str]:
    """``seeded_repo`` at commit ``A``, then advanced to ``B`` — the divergence.

    ``B`` adds twenty files under ``vendor/`` that the task never allows. This
    is the ``Hutch Agent/**`` analogue from task ``3dbd78d6``, whose 22
    "out-of-scope" paths were, every one of them, base divergence rather than
    anything the worker did.
    """
    base = _git(seeded_repo, "rev-parse", "HEAD")
    vendor = seeded_repo / "vendor"
    vendor.mkdir()
    for i in range(20):
        (vendor / f"lib{i}.py").write_text(f"# vendored module {i}\n")
    _git(seeded_repo, "add", "-A")
    _git(seeded_repo, "commit", "-q", "-m", "vendor drop (the divergence)")
    drifted = _git(seeded_repo, "rev-parse", "HEAD")
    assert base != drifted
    return {"repo": str(seeded_repo), "base": base, "drifted": drifted}


def _evidence(dispatcher, task_id: str) -> Path:
    return Path(dispatcher.store.task_dir(task_id)) / "evidence"


# ---------------------------------------------------------------------------
# §4 — the dispatcher creates the worktree, at the exact recorded base
# ---------------------------------------------------------------------------


async def test_worktree_is_created_at_the_recorded_base_not_at_repo_head(
    dispatcher, request_payload, fake_env, diverged_repo, monkeypatch
):
    """Cases A and C: the base is pinned, and the tree starts exactly there.

    ``base_ref`` names commit ``A`` while the repository's ``HEAD`` is ``B``.
    Under the old design the CLI chose the start-point and landed on ``B``, so
    the twenty ``vendor/`` files were attributed to the worker and the run was
    refused as a scope violation. The dispatcher now creates the worktree
    itself, at ``A``, and the evidence is exactly the worker's footprint.
    """
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", "src/deploy/deploy.py")
    request_payload["repository"]["base_ref"] = diverged_repo["base"]

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert "error" not in result, result
    envelope = json.loads(
        (Path(dispatcher.store.task_dir(result["task_id"])) / "envelope.json").read_text()
    )
    assert envelope["repository"]["base_commit"] == diverged_repo["base"]

    worktree = Path(result["worktree"])
    assert _git(worktree, "rev-parse", "HEAD") == diverged_repo["base"]
    assert _git(worktree, "rev-parse", "HEAD") != diverged_repo["drifted"]

    # The 20 divergence files are NOT the worker's changes and must not appear.
    observations = result["dispatcher_observations"]
    assert observations["changed_paths"] == ["src/deploy/deploy.py"]
    assert observations["worktree_head_commit"] == diverged_repo["base"]
    assert observations["scope_valid"] is True
    assert result["scope"]["out_of_scope"] == []
    assert result["status"] != TaskState.POLICY_VIOLATION.value
    assert dispatcher.store.load(result["task_id"]).policy_violations == []

    # And the evidence file records the verified invariant.
    verdict = json.loads((_evidence(dispatcher, result["task_id"]) / "worktree-base.json").read_text())
    assert verdict["held"] is True
    assert verdict["expected_base_commit"] == diverged_repo["base"]
    assert verdict["actual_head_commit"] == diverged_repo["base"]


async def test_base_ref_HEAD_lands_on_local_head_and_nowhere_else(
    dispatcher, request_payload, fake_env, diverged_repo, monkeypatch
):
    """``base_ref: "HEAD"`` was not a safe default: task ``49231f6e`` used it.

    The recorded base tracked the local checkout while the CLI tracked the
    remote default branch, 120 commits ahead. Here ``origin/main`` is set to a
    different commit than ``HEAD``, and the worktree must still start on the
    resolved local ``HEAD``.
    """
    repo = Path(diverged_repo["repo"])
    _git(repo, "update-ref", "refs/remotes/origin/main", diverged_repo["base"])
    _git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    head = _git(repo, "rev-parse", "HEAD")
    assert head != _git(repo, "rev-parse", "origin/main")

    request_payload["repository"]["base_ref"] = "HEAD"
    result = await dispatcher.dispatch_claude_task(request_payload)

    assert "error" not in result, result
    assert _git(Path(result["worktree"]), "rev-parse", "HEAD") == head
    assert result["dispatcher_observations"]["worktree_head_commit"] == head


async def test_dispatch_never_asks_claude_to_create_a_worktree(
    dispatcher, request_payload, fake_env, worker_invocations
):
    """Case K: no ``--worktree`` flag on the dispatcher-owned-worktree path.

    ``--worktree`` has no start-point parameter (`CLI-HELP-RAW.txt:216-217`),
    so emitting it hands the choice of base to the CLI. The dispatcher creates
    the tree first and launches the worker with ``cwd`` already inside it.
    """
    result = await dispatcher.dispatch_claude_task(request_payload)

    call = worker_invocations()[0]
    assert "--worktree" not in call["argv"]
    assert "-w" not in call["argv"]
    assert call["has_worktree"] is False
    assert call["worktree"] is None
    # The worker started *inside* the worktree the dispatcher had already made.
    assert call["cwd"] == result["worktree"]


async def test_the_worktree_exists_and_is_verified_before_the_worker_starts(
    dispatcher, request_payload, fake_env, diverged_repo, monkeypatch, worker_invocations
):
    """The tree is measured before a single token is spent."""
    request_payload["repository"]["base_ref"] = diverged_repo["base"]
    seen: list[str] = []
    real_run = server_mod.run_worker

    async def observing(invocation):
        # By the time the worker is launched the worktree exists and is on the
        # recorded base.
        seen.append(_git(Path(invocation.cwd), "rev-parse", "HEAD"))
        return await real_run(invocation)

    monkeypatch.setattr(server_mod, "run_worker", observing)
    result = await dispatcher.dispatch_claude_task(request_payload)

    assert "error" not in result, result
    assert seen == [diverged_repo["base"]]


# ---------------------------------------------------------------------------
# §4 — fail closed, before the worker, when the tree is not on the base
# ---------------------------------------------------------------------------


async def test_worktree_base_mismatch_refuses_before_any_worker_starts(
    dispatcher, request_payload, fake_env, diverged_repo, monkeypatch, worker_invocations
):
    """Cases E and F: creation lands on the wrong commit -> refuse, spend nothing.

    The sabotage stands in for anything that chooses a start-point other than
    the recorded base — which is precisely what the Claude CLI did to all three
    production dispatches.
    """
    request_payload["repository"]["base_ref"] = diverged_repo["base"]
    real_create = server_mod.create_worktree

    def sabotage(repo, *, worktree_name, path, start_commit):
        return real_create(
            repo,
            worktree_name=worktree_name,
            path=path,
            start_commit=diverged_repo["drifted"],
        )

    monkeypatch.setattr(server_mod, "create_worktree", sabotage)
    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["error"] == "WorktreeBaseMismatch"
    assert result["details"]["expected_base_commit"] == diverged_repo["base"]
    assert result["details"]["actual_head_commit"] == diverged_repo["drifted"]
    assert result["retryable"] is False
    assert diverged_repo["drifted"] in result["remediation"]

    task_id = result["details"]["task_id"]
    record = dispatcher.store.load(task_id)
    assert record.state is TaskState.FAILED
    assert record.state is not TaskState.POLICY_VIOLATION
    assert record.policy_violations == []
    assert record.state_history[-1]["reason"] == "worktree_base_mismatch"

    # No worker ran: the check is pre-launch on a fresh dispatch.
    assert worker_invocations() == []
    assert record.run_count == 0

    # No evidence that would describe a tree that never existed.
    evidence = _evidence(dispatcher, task_id)
    assert not (evidence / "diff.patch").exists()
    assert not (evidence / "changed-paths.json").exists()
    verdict = json.loads((evidence / "worktree-base.json").read_text())
    assert verdict["held"] is False
    assert verdict["expected_base_commit"] == diverged_repo["base"]
    assert verdict["actual_head_commit"] == diverged_repo["drifted"]


async def test_the_recorded_base_is_never_rewritten_to_match_reality(
    dispatcher, request_payload, fake_env, diverged_repo, monkeypatch
):
    """Sol named a base. A refusal is honest; adopting the observed head is not."""
    request_payload["repository"]["base_ref"] = diverged_repo["base"]
    real_create = server_mod.create_worktree
    monkeypatch.setattr(
        server_mod,
        "create_worktree",
        lambda repo, *, worktree_name, path, start_commit: real_create(
            repo, worktree_name=worktree_name, path=path,
            start_commit=diverged_repo["drifted"],
        ),
    )

    result = await dispatcher.dispatch_claude_task(request_payload)
    task_id = result["details"]["task_id"]

    envelope = json.loads(
        (Path(dispatcher.store.task_dir(task_id)) / "envelope.json").read_text()
    )
    assert envelope["repository"]["base_commit"] == diverged_repo["base"]
    assert envelope["repository"]["base_commit"] != diverged_repo["drifted"]


async def test_head_moved_during_the_run_is_refused_before_evidence(
    dispatcher, request_payload, fake_env, diverged_repo, monkeypatch, worker_invocations
):
    """The post-run choke point: a worker that moves HEAD inside its worktree.

    The worker has ``Bash``. Nothing stops it running ``git checkout`` in its
    own worktree, and if it does, every subsequent measurement is taken against
    a tree the dispatcher never authorised. Evidence is written first (the run
    streams), then the refusal — never a diff against a base the tree is not on.
    """
    request_payload["repository"]["base_ref"] = diverged_repo["base"]
    real_run = server_mod.run_worker

    async def drifting(invocation):
        _git(Path(invocation.cwd), "checkout", "--detach", "-q", diverged_repo["drifted"])
        return await real_run(invocation)

    monkeypatch.setattr(server_mod, "run_worker", drifting)
    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["error"] == "WorktreeBaseMismatch"
    task_id = result["details"]["task_id"]
    record = dispatcher.store.load(task_id)
    assert record.state is TaskState.FAILED
    assert record.policy_violations == []
    assert record.state_history[-1]["reason"] == "worktree_base_mismatch"

    # Evidence first, refusal second: the run itself is on disk...
    assert len(worker_invocations()) == 1
    assert record.run_count == 1
    run_dir = Path(dispatcher.store.task_dir(task_id)) / "runs" / "001"
    assert (run_dir / "stdout.json").exists()

    # ...but no diff evidence, because it would be a lie.
    evidence = _evidence(dispatcher, task_id)
    assert not (evidence / "diff.patch").exists()
    assert not (evidence / "changed-paths.json").exists()
    assert json.loads((evidence / "worktree-base.json").read_text())["held"] is False


async def test_false_negative_is_refused_before_it_can_hide_a_change(
    dispatcher, request_payload, fake_env, seeded_repo, monkeypatch, worker_invocations
):
    """Case G — the blast radius (`B2-DIAGNOSIS.md` §5.1), end to end.

    ``.github/deploy.yml`` is forbidden. It holds content ``X`` at the recorded
    base and content ``Y`` one commit later. The worktree drifts to ``Y`` and
    the worker rewrites the file back to ``X`` — a genuine, explicitly
    prohibited change that produces **no diff line at all** against the recorded
    base. The second half of this test proves that: with the invariant disabled
    the pipeline records ``scope_valid: true`` and an empty
    ``forbidden_paths_touched``.
    """
    forbidden_dir = seeded_repo / ".github"
    forbidden_dir.mkdir(exist_ok=True)
    # The exact bytes the fake worker writes, so the "revert" is byte-identical.
    base_content = "touched by fake claude outside the allowed paths\n"
    (forbidden_dir / "deploy.yml").write_text(base_content)
    _git(seeded_repo, "add", "-A")
    _git(seeded_repo, "commit", "-q", "-m", "forbidden file at base")
    base = _git(seeded_repo, "rev-parse", "HEAD")

    (forbidden_dir / "deploy.yml").write_text("PRODUCTION DEPLOY CONFIG\n")
    _git(seeded_repo, "add", "-A")
    _git(seeded_repo, "commit", "-q", "-m", "forbidden file drifted")
    drifted = _git(seeded_repo, "rev-parse", "HEAD")

    request_payload["repository"]["base_ref"] = base
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", ".github/deploy.yml")

    real_run = server_mod.run_worker

    async def drifting(invocation):
        _git(Path(invocation.cwd), "checkout", "--detach", "-q", drifted)
        return await real_run(invocation)

    monkeypatch.setattr(server_mod, "run_worker", drifting)

    refused = await dispatcher.dispatch_claude_task(request_payload)
    assert refused["error"] == "WorktreeBaseMismatch"
    refused_id = refused["details"]["task_id"]
    assert dispatcher.store.load(refused_id).policy_violations == []

    # Now disable the invariant and watch the forbidden change vanish. This is
    # what the refusal above is protecting against, stated as an executable
    # fact rather than a warning in a document.
    monkeypatch.setattr(
        server_mod, "assert_worktree_base", lambda path, **kwargs: kwargs["expected_base_commit"]
    )
    blind = await dispatcher.dispatch_claude_task(request_payload)

    assert "error" not in blind, blind
    observations = blind["dispatcher_observations"]
    assert observations["scope_valid"] is True
    assert observations["forbidden_paths_touched"] == []
    assert ".github/deploy.yml" not in observations["changed_paths"]
    assert blind["status"] != TaskState.POLICY_VIOLATION.value
    # The file on disk really was rewritten to the forbidden content.
    assert (Path(blind["worktree"]) / ".github" / "deploy.yml").read_text() == base_content


async def test_out_of_scope_change_is_still_a_policy_violation(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """Case H: with a correctly based worktree the scope check does its job."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", "src/unrelated/leak.py")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.POLICY_VIOLATION.value
    assert result["scope"]["out_of_scope"] == ["src/unrelated/leak.py"]
    assert result["dispatcher_observations"]["worktree_head_commit"] == (
        result["dispatcher_observations"]["base_commit"]
    )


async def test_forbidden_path_change_is_still_a_policy_violation(
    dispatcher, request_payload, fake_env, monkeypatch
):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", ".github/workflows/pwn.yml")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.POLICY_VIOLATION.value
    assert result["scope"]["forbidden"] == [".github/workflows/pwn.yml"]


# ---------------------------------------------------------------------------
# K-2 — the primary tree, and where the container lives
# ---------------------------------------------------------------------------


async def test_first_dispatch_into_a_fresh_repository_leaves_the_primary_tree_alone(
    dispatcher, request_payload, fake_env, seeded_repo, monkeypatch
):
    """K-2: the container is outside the repository, so nothing appears in it.

    The production defect was the CLI creating ``.claude/worktrees/`` INSIDE
    the primary work tree: a brand-new untracked entry that trips the
    primary-tree non-interference invariant, so the first dispatch into any
    newly-authorised repository lands in ``POLICY_VIOLATION``. The dispatcher
    now creates the worktree itself, under its own state directory. Nothing is
    excused and no check is relaxed — the entry simply never exists.
    """
    assert not (seeded_repo / ".claude").exists()
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", "src/deploy/deploy.py")
    head_before = _git(seeded_repo, "rev-parse", "HEAD")
    status_before = _git(seeded_repo, "status", "--porcelain")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert "error" not in result, result
    assert result["status"] != TaskState.POLICY_VIOLATION.value
    assert result["primary_tree"]["unchanged"] is True
    assert result["primary_tree"]["divergence"] is None
    assert _git(seeded_repo, "rev-parse", "HEAD") == head_before
    assert _git(seeded_repo, "status", "--porcelain") == status_before
    assert not (seeded_repo / ".claude").exists()

    worktree = Path(result["worktree"])
    assert not worktree.is_relative_to(seeded_repo)
    assert worktree.is_relative_to(Path(dispatcher.config.state_path))


async def test_a_worker_touching_the_primary_tree_is_still_a_violation(
    dispatcher, request_payload, fake_env, seeded_repo, monkeypatch
):
    """The anti-weakening proof: nothing about K-2's fix excuses anything.

    The primary-tree invariant is still ``post_state == pre_state`` over HEAD
    plus the whole porcelain status, with no ignore list and no excusal path.
    """
    real_run = server_mod.run_worker

    async def leaking(invocation):
        (seeded_repo / "leaked.txt").write_text("written into the primary tree\n")
        return await real_run(invocation)

    monkeypatch.setattr(server_mod, "run_worker", leaking)
    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.POLICY_VIOLATION.value
    assert result["primary_tree"]["unchanged"] is False
    record = dispatcher.store.load(result["task_id"])
    assert "primary_tree_appeared:?? leaked.txt" in record.policy_violations


async def test_a_worker_writing_dot_claude_in_the_primary_tree_is_still_a_violation(
    dispatcher, request_payload, fake_env, seeded_repo, monkeypatch
):
    """``.claude/`` is not a magic word. Nothing about that path is excused."""
    real_run = server_mod.run_worker

    async def leaking(invocation):
        (seeded_repo / ".claude").mkdir(exist_ok=True)
        (seeded_repo / ".claude" / "settings.json").write_text("{}\n")
        return await real_run(invocation)

    monkeypatch.setattr(server_mod, "run_worker", leaking)
    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.POLICY_VIOLATION.value
    assert result["primary_tree"]["unchanged"] is False


# ---------------------------------------------------------------------------
# §6 — resume keeps the ORIGINAL baseline identity
# ---------------------------------------------------------------------------


async def test_resume_reuses_the_exact_worktree_and_its_original_base(
    dispatcher, request_payload, fake_env, diverged_repo, monkeypatch, worker_invocations
):
    """Case J."""
    request_payload["repository"]["base_ref"] = diverged_repo["base"]
    first = await dispatcher.dispatch_claude_task(request_payload)
    assert "error" not in first, first

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    resumed = await dispatcher.resume_claude_task(first["task_id"], "Continue.")

    assert "error" not in resumed, resumed
    assert resumed["worktree"] == first["worktree"]
    assert worker_invocations()[-1]["cwd"] == first["worktree"]
    assert worker_invocations()[-1]["has_worktree"] is False
    assert resumed["dispatcher_observations"]["base_commit"] == diverged_repo["base"]
    assert resumed["dispatcher_observations"]["worktree_head_commit"] == diverged_repo["base"]


async def test_resume_into_a_drifted_worktree_is_refused_before_launch(
    dispatcher, request_payload, fake_env, diverged_repo, monkeypatch, worker_invocations
):
    """A mismatched task must not be re-dispatched into the same corrupt ground.

    ``POLICY_VIOLATION -> RESUME_REQUESTED`` is a legal transition, so "issue a
    corrective resume" is Sol's natural next move. It must not spend another
    worker on a tree that cannot produce valid evidence.
    """
    request_payload["repository"]["base_ref"] = diverged_repo["base"]
    first = await dispatcher.dispatch_claude_task(request_payload)
    task_id = first["task_id"]
    before = dispatcher.store.load(task_id)
    calls_before = len(worker_invocations())

    # Out of band, exactly as a stray checkout or a resumed CLI session would.
    _git(Path(first["worktree"]), "checkout", "--detach", "-q", diverged_repo["drifted"])

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    refused = await dispatcher.resume_claude_task(task_id, "Continue.")

    assert refused["error"] == "WorktreeBaseMismatch"
    assert refused["details"]["expected_base_commit"] == diverged_repo["base"]
    assert refused["details"]["actual_head_commit"] == diverged_repo["drifted"]
    assert refused["details"]["phase"] == "resume"

    assert len(worker_invocations()) == calls_before  # no worker launched
    after = dispatcher.store.load(task_id)
    assert after.run_count == before.run_count
    assert after.resume_count == before.resume_count
    # Refused before any transition: a resume that never happened must not
    # rewrite the state the previous run legitimately landed in. The refusal is
    # recorded as the task's last error instead.
    assert after.state is before.state
    assert after.last_error["error"] == "WorktreeBaseMismatch"


async def test_resume_does_not_adopt_or_normalise_the_worktree_base(
    dispatcher, request_payload, fake_env, diverged_repo, monkeypatch
):
    """§6: a resume may not redefine the task to match what it found."""
    request_payload["repository"]["base_ref"] = diverged_repo["base"]
    first = await dispatcher.dispatch_claude_task(request_payload)
    task_id = first["task_id"]
    _git(Path(first["worktree"]), "checkout", "--detach", "-q", diverged_repo["drifted"])

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    await dispatcher.resume_claude_task(task_id, "Continue.")

    envelope = json.loads(
        (Path(dispatcher.store.task_dir(task_id)) / "envelope.json").read_text()
    )
    assert envelope["repository"]["base_commit"] == diverged_repo["base"]
    record = dispatcher.store.load(task_id)
    assert record.worktree_base_anchor.base_commit == diverged_repo["base"]
    assert record.worktree_path == first["worktree"]


async def test_resume_refuses_when_the_envelope_base_no_longer_matches_the_anchor(
    dispatcher, request_payload, fake_env, diverged_repo, monkeypatch, worker_invocations
):
    """The anchor binds the base, so "normalising" the envelope cannot work.

    Both the envelope's recorded base **and** the worktree's HEAD are moved to
    the drifted commit, so a check that only measured the tree would happily
    accept it. The dispatch anchor is what refuses: the baseline identity a
    resume runs under must still be the one the task was approved with.
    """
    request_payload["repository"]["base_ref"] = diverged_repo["base"]
    first = await dispatcher.dispatch_claude_task(request_payload)
    task_id = first["task_id"]
    calls_before = len(worker_invocations())

    envelope_path = Path(dispatcher.store.task_dir(task_id)) / "envelope.json"
    envelope = json.loads(envelope_path.read_text())
    envelope["repository"]["base_commit"] = diverged_repo["drifted"]
    envelope_path.write_text(json.dumps(envelope, indent=2))
    _git(Path(first["worktree"]), "checkout", "--detach", "-q", diverged_repo["drifted"])

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    refused = await dispatcher.resume_claude_task(task_id, "Continue.")

    assert refused["error"] == "WorktreeBaseMismatch"
    assert refused["details"]["anchored_base_commit"] == diverged_repo["base"]
    assert refused["details"]["expected_base_commit"] == diverged_repo["drifted"]
    assert len(worker_invocations()) == calls_before


async def test_the_resume_side_anchor_check_refuses_on_its_own(
    dispatcher, request_payload, fake_env, diverged_repo, monkeypatch, worker_invocations
):
    """The pre-launch anchor check must refuse without help from the other layer.

    Two independent guards cover a normalised base: this one, before any state
    is mutated, and ``WorkerContextComposer.verify_dispatch_anchor``, which the
    resume runs later. Redundancy is deliberate — but a redundant guard that no
    test can distinguish from a no-op is a guard that will be deleted by
    somebody one day as dead code. So the other layer is disabled here and this
    one is required to refuse on its own, before a worker starts.
    """
    request_payload["repository"]["base_ref"] = diverged_repo["base"]
    first = await dispatcher.dispatch_claude_task(request_payload)
    task_id = first["task_id"]
    calls_before = len(worker_invocations())

    envelope_path = Path(dispatcher.store.task_dir(task_id)) / "envelope.json"
    envelope = json.loads(envelope_path.read_text())
    envelope["repository"]["base_commit"] = diverged_repo["drifted"]
    envelope_path.write_text(json.dumps(envelope, indent=2))
    _git(Path(first["worktree"]), "checkout", "--detach", "-q", diverged_repo["drifted"])

    monkeypatch.setattr(
        type(dispatcher.context),
        "verify_dispatch_anchor",
        lambda self, record, *, identity, envelope=None: None,
    )
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    refused = await dispatcher.resume_claude_task(task_id, "Continue.")

    assert refused["error"] == "WorktreeBaseMismatch"
    assert refused["details"]["anchored_base_commit"] == diverged_repo["base"]
    assert len(worker_invocations()) == calls_before
    # And nothing normalised: the anchor still names the approved base.
    assert (
        dispatcher.store.load(task_id).worktree_base_anchor.base_commit
        == diverged_repo["base"]
    )


async def test_resume_refuses_when_the_recorded_worktree_is_no_longer_registered(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """Worktree identity, not just the path: git must still know this tree."""
    first = await dispatcher.dispatch_claude_task(request_payload)
    task_id = first["task_id"]
    calls_before = len(worker_invocations())

    record = dispatcher.store.load(task_id)
    stray = Path(first["worktree"]).parent / "stray-copy"
    stray.mkdir(parents=True)
    record.worktree_path = str(stray)
    dispatcher.store.save(record)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    refused = await dispatcher.resume_claude_task(task_id, "Continue.")

    assert refused["error"] in ("WorktreeBaseMismatch", "StateCorruption")
    assert len(worker_invocations()) == calls_before
