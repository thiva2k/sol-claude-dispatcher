"""Lifecycle invariants the dispatcher must hold end to end (Lane C).

Three findings are pinned here, each against the real ``Dispatcher``, a real
git repository, a real ``TaskStore`` on disk and the fake worker binary:

* **P0/P1-4** — Fable review and worker mutation are serialised by the same
  exclusive repository lock, and the lock is released on every path.
* **P1-5** — the primary working tree, raw HEAD, and repository authority are
  captured at WORKER_START, WORKER_EXIT, and VALIDATION_EXIT. Adjacent
  terminals are compared so validation cannot erase worker interference.
* **P1-7** — evidence is collected twice, once as the worker left the worktree
  and once after the dispatcher's own validation commands have run, and the
  record distinguishes who produced which path.

Plus the two end-to-end consequences of Lane B's runner work that only exist at
this call site: a very large worker run must still yield a parsed structured
result, and its complete stream must reach the run directory.

Nothing here spawns a real ``claude`` or ``codex``. The two shims written into
``tmp_path`` below both terminate in ``tests/fixtures/claude_worktree_shim.py``,
which terminates in ``tests/fake_bin/claude``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import sol_claude_dispatcher.server as server_module
from sol_claude_dispatcher.models import TaskState

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKTREE_SHIM = PROJECT_ROOT / "tests" / "fixtures" / "claude_worktree_shim.py"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "PATH": "/usr/bin:/bin",
}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def meddling_worker(tmp_path: Path, integration_config, seeded_repo: Path, monkeypatch):
    """A worker binary that touches the **primary** tree before doing its job.

    This is the only way to exercise P1-5 honestly: the invariant is about a
    worker escaping its isolated worktree, and no existing fake mode does that.
    The shim mutates the primary repository, then hands over to the ordinary
    worktree shim with an identical argv, so everything downstream (worktree
    creation, modes, exit codes, logging) is unchanged.

    Returns a callable: ``meddling_worker("modify" | "add" | "delete" | "none")``.
    """
    script = tmp_path / "primary_tree_meddler.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "from pathlib import Path\n"
        f"repo = Path({str(seeded_repo)!r})\n"
        'action = os.environ.get("MEDDLE_ACTION", "none")\n'
        'if action == "modify":\n'
        '    (repo / "README.md").write_text("meddled by the worker\\n")\n'
        'elif action == "add":\n'
        '    (repo / "worker-was-here.txt").write_text("escaped\\n")\n'
        'elif action == "delete":\n'
        '    (repo / "README.md").unlink()\n'
        f"os.execv(sys.executable, [sys.executable, {str(WORKTREE_SHIM)!r}, *sys.argv[1:]])\n"
    )
    script.chmod(0o755)
    integration_config.claude.binary = str(script)

    def _arm(action: str) -> None:
        monkeypatch.setenv("MEDDLE_ACTION", action)

    _arm("none")
    return _arm


@pytest.fixture
def mutating_validation(tmp_path: Path):
    """Validation commands that rewrite the worktree, the way real ones do.

    Formatters, coverage runs, lockfile updaters and snapshot tests all mutate
    the tree they validate. Returns a callable producing the envelope's
    ``validation`` block for a chosen set of mutations.
    """

    def _build(*, in_scope: bool = True, out_of_scope: bool = False) -> dict:
        lines = [
            "from pathlib import Path",
            "cwd = Path.cwd()",
        ]
        if in_scope:
            lines += [
                '(cwd / "src" / "deploy").mkdir(parents=True, exist_ok=True)',
                '(cwd / "src" / "deploy" / "generated.py").write_text('
                '"# created by dispatcher validation\\n")',
                '(cwd / "src" / "deploy" / "deploy.py").write_text('
                '"def deploy():\\n    return \'validated\'\\n")',
            ]
        if out_of_scope:
            lines += [
                '(cwd / "docs").mkdir(parents=True, exist_ok=True)',
                '(cwd / "docs" / "coverage.xml").write_text("<coverage/>\\n")',
                '(cwd / ".coverage").write_text("untracked artifact\\n")',
            ]
        script = tmp_path / f"validation_meddler_{int(in_scope)}{int(out_of_scope)}.py"
        script.write_text("\n".join(lines) + "\n")
        return {"commands": [{"argv": [sys.executable, str(script)], "timeout_seconds": 60}]}

    return _build


async def _dispatch_touching(dispatcher, payload, monkeypatch, touch="src/deploy/deploy.py"):
    """Dispatch a worker that edits in-scope files and reports success."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", touch)
    return await dispatcher.dispatch_claude_task(payload)


def _evidence(dispatcher, task_id: str, name: str) -> str:
    return dispatcher.store.read_evidence(task_id, name) or ""


def _evidence_json(dispatcher, task_id: str, name: str) -> dict:
    return json.loads(_evidence(dispatcher, task_id, name))


# ---------------------------------------------------------------------------
# P0/P1-4 — Fable review and worker mutation are serialised
# ---------------------------------------------------------------------------


async def test_resume_while_a_review_holds_the_repository_is_refused(
    dispatcher, request_payload, fake_env, monkeypatch, integration_config
):
    """A resume must not mutate the worktree Fable is reading (P0/P1-4)."""
    from sol_claude_dispatcher.server import Dispatcher

    dispatched = await _dispatch_touching(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]

    # A slow reviewer, so the resume genuinely overlaps it.
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "timeout")
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "20")

    other = Dispatcher(integration_config)
    review_task = asyncio.create_task(dispatcher.review_task_with_fable(task_id))
    await asyncio.sleep(1.0)
    resume = await other.resume_claude_task(task_id, "keep going")
    review = await review_task

    assert resume["error"] == "RepositoryBusy", (resume, review)
    assert resume["retryable"] is True


async def test_a_review_while_a_worker_is_running_is_refused_by_state_preflight(
    dispatcher, request_payload, fake_env, monkeypatch, integration_config
):
    """An active worker makes review illegal before lock contention matters.

    The task is already RUNNING when this call arrives, so PREPARE can prove
    that FABLE_REVIEWED is not a legal target without touching repository
    authority. A separate Fable test holds the lock while the task remains
    AWAITING_SOL_REVIEW and pins RepositoryBusy for that opposite control.
    """
    from sol_claude_dispatcher.server import Dispatcher

    dispatched = await _dispatch_touching(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "timeout")
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "20")

    other = Dispatcher(integration_config)
    resume_task = asyncio.create_task(other.resume_claude_task(task_id, "keep going"))
    await asyncio.sleep(1.0)
    review = await dispatcher.review_task_with_fable(task_id)
    await resume_task

    assert review["error"] == "InvalidStateTransition", review
    assert review["details"]["from"] == TaskState.RUNNING.value
    assert review["details"]["to"] == TaskState.FABLE_REVIEWED.value


async def test_two_concurrent_reviews_produce_one_winner_and_one_refusal(
    dispatcher, request_payload, fake_env, monkeypatch, integration_config
):
    """Review counter contention: exactly one review is recorded, not two."""
    from sol_claude_dispatcher.server import Dispatcher

    dispatched = await _dispatch_touching(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")

    other = Dispatcher(integration_config)
    first, second = await asyncio.gather(
        dispatcher.review_task_with_fable(task_id),
        other.review_task_with_fable(task_id),
    )

    busy = [r for r in (first, second) if r.get("error") == "RepositoryBusy"]
    won = [r for r in (first, second) if r.get("status") == TaskState.FABLE_REVIEWED.value]
    assert len(busy) == 1, (first, second)
    assert len(won) == 1, (first, second)
    assert won[0]["review_number"] == 1
    assert dispatcher.store.load(task_id).fable_review_count == 1


async def test_the_lock_is_released_after_a_failed_review(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """A reviewer that exits non-zero must not wedge the repository."""
    dispatched = await _dispatch_touching(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "failure")
    failed = await dispatcher.review_task_with_fable(task_id)
    # DEFECT-L2-02: a reviewer that exits non-zero writing nothing to stdout is
    # a *process* failure and is now reported as one, with its stderr quoted.
    # It used to be reported as ClaudeStructuredOutputInvalid — the model blamed
    # for the CLI. The invariant under test is unchanged: the lock is released.
    assert failed["error"] == "ClaudeExecutionFailed"
    assert "simulated worker failure" in failed["details"]["stderr_tail"]

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    again = await dispatcher.review_task_with_fable(task_id)
    assert again["status"] == TaskState.FABLE_REVIEWED.value


async def test_the_lock_is_released_after_a_malformed_review_result(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """Unparseable review output leaves the repository usable (§25 + P0/P1-4)."""
    dispatched = await _dispatch_touching(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    monkeypatch.setenv("FAKE_CLAUDE_STDOUT", "prose, not a review")
    malformed = await dispatcher.review_task_with_fable(task_id)
    assert malformed["error"] == "ClaudeStructuredOutputInvalid"

    monkeypatch.delenv("FAKE_CLAUDE_STDOUT")
    again = await dispatcher.review_task_with_fable(task_id)
    assert again["status"] == TaskState.FABLE_REVIEWED.value
    assert again["review_number"] == 1


# ---------------------------------------------------------------------------
# P1-5 — primary-tree non-interference
# ---------------------------------------------------------------------------


async def test_an_initially_clean_primary_tree_stays_clean(
    dispatcher, request_payload, fake_env, monkeypatch, seeded_repo
):
    result = await _dispatch_touching(dispatcher, request_payload, monkeypatch)

    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert result["primary_tree"]["unchanged"] is True
    invariant = _evidence_json(dispatcher, result["task_id"], "primary-tree-invariant.json")
    assert invariant["held"] is True
    assert invariant["before"]["tree"]["entries"] == invariant["after"]["tree"]["entries"]
    assert invariant["before"]["head"]["digest"] == invariant["after"]["head"]["digest"]

    run = dispatcher.store.latest_run(result["task_id"])
    assert run is not None and run.dispatcher_observations is not None
    assert run.dispatcher_observations.primary_tree_unchanged is True
    # The untruncated diff size is recorded alongside the retained one (C-R2),
    # so a reader can tell a small diff from a capped one.
    assert run.dispatcher_observations.diff_total_bytes >= (
        run.dispatcher_observations.diff_bytes
    )
    assert run.dispatcher_observations.diff_total_bytes > 0


async def test_an_initially_dirty_primary_tree_is_accepted_when_unchanged(
    dispatcher, request_payload, fake_env, monkeypatch, seeded_repo
):
    """The invariant is ``post == pre``, **not** "the tree started clean".

    Requiring a clean tree would refuse every ordinary working repository and
    would still miss the interesting case. Pre-fix, this run was indistinguishable
    from interference: the only measurement was "is the primary tree clean now",
    which is False here.
    """
    (seeded_repo / "README.md").write_text("developer's uncommitted work\n")
    (seeded_repo / "scratch.txt").write_text("also uncommitted\n")

    result = await _dispatch_touching(dispatcher, request_payload, monkeypatch)

    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value
    assert result["primary_tree"]["unchanged"] is True
    # The raw equality measurement does not pretend to answer Git-cleanliness.
    assert result["dispatcher_observations"]["primary_worktree_clean"] is None
    invariant = _evidence_json(dispatcher, result["task_id"], "primary-tree-invariant.json")
    assert invariant["held"] is True
    assert invariant["before"]["tree"]["entries"] == invariant["after"]["tree"]["entries"]
    assert invariant["before"]["head"]["digest"] == invariant["after"]["head"]["digest"]


@pytest.mark.parametrize(
    "action,expected_marker",
    [
        ("modify", "primary_tree_changed:README.md"),
        ("add", "primary_tree_appeared:?? worker-was-here.txt"),
        ("delete", "primary_tree_disappeared:README.md"),
    ],
)
async def test_a_worker_that_touches_the_primary_tree_is_a_policy_violation(
    dispatcher,
    request_payload,
    fake_env,
    monkeypatch,
    meddling_worker,
    action,
    expected_marker,
):
    """Modify, add, delete: every one lands POLICY_VIOLATION, not review."""
    meddling_worker(action)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.POLICY_VIOLATION.value, result
    assert result["primary_tree"]["unchanged"] is False
    # The worktree itself was in scope; only the primary tree was touched, so
    # the pre-fix code would have landed AWAITING_SOL_REVIEW here.
    assert result["scope"]["valid"] is True
    assert result["last_error"]["error"] == "PolicyViolation"

    record = dispatcher.store.load(result["task_id"])
    assert record.state is TaskState.POLICY_VIOLATION
    assert expected_marker in record.policy_violations

    # The verdict is a typed observation too (C-R3), not only a string prefix
    # in policy_violations. primary_worktree_clean stays a literal measurement
    # of the tree's current dirtiness and is a different question.
    run = dispatcher.store.latest_run(result["task_id"])
    assert run is not None and run.dispatcher_observations is not None
    assert run.dispatcher_observations.primary_tree_unchanged is False

    # Both halves of the evidence survive, which is what makes the verdict
    # checkable by a human rather than merely asserted.
    task_id = result["task_id"]
    assert _evidence(dispatcher, task_id, "primary-tree-before.json")
    assert _evidence(dispatcher, task_id, "primary-tree-after.json")
    invariant = _evidence_json(dispatcher, task_id, "primary-tree-invariant.json")
    assert invariant["held"] is False
    assert any(invariant["divergence"][key] for key in ("appeared", "disappeared", "changed"))


async def test_a_commit_in_the_primary_tree_is_detected_by_the_head_fingerprint(
    dispatcher, request_payload, fake_env, monkeypatch, tmp_path, seeded_repo
):
    """``git status`` alone cannot see a commit; the HEAD half of the pair can."""
    script = tmp_path / "committing_meddler.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import os, subprocess, sys\n"
        f"repo = {str(seeded_repo)!r}\n"
        'env = dict(os.environ, GIT_AUTHOR_NAME="M", GIT_AUTHOR_EMAIL="m@x.invalid",\n'
        '           GIT_COMMITTER_NAME="M", GIT_COMMITTER_EMAIL="m@x.invalid")\n'
        'subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "sneaky"],\n'
        "               cwd=repo, env=env, check=False)\n"
        f"os.execv(sys.executable, [sys.executable, {str(WORKTREE_SHIM)!r}, *sys.argv[1:]])\n"
    )
    script.chmod(0o755)
    dispatcher.config.claude.binary = str(script)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.POLICY_VIOLATION.value, result
    assert result["primary_tree"]["divergence"]["head_changed"] is True
    assert any(
        v.startswith("primary_tree_head:")
        for v in dispatcher.store.load(result["task_id"]).policy_violations
    )


async def test_validation_cannot_restore_and_erase_worker_primary_interference(
    dispatcher,
    request_payload,
    fake_env,
    monkeypatch,
    meddling_worker,
    seeded_repo,
    tmp_path,
):
    """A WORKER_EXIT terminal makes worker interference non-erasable."""

    restore = tmp_path / "restore_primary.py"
    restore.write_text(
        "from pathlib import Path\n"
        f"Path({str(seeded_repo / 'README.md')!r}).write_text('test repo\\n')\n"
    )
    request_payload["validation"] = {
        "commands": [{"argv": [sys.executable, str(restore)]}]
    }
    meddling_worker("modify")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.POLICY_VIOLATION.value, result
    invariant = _evidence_json(
        dispatcher, result["task_id"], "primary-tree-invariant.json"
    )
    assert invariant["worker_interval"]["held"] is False
    assert invariant["worker_interval"]["divergence"]["attributed_to"] == "worker"
    assert invariant["validation_interval"]["held"] is False
    assert (
        invariant["validation_interval"]["divergence"]["attributed_to"]
        == "validation"
    )
    # The final bytes equal WORKER_START, but raw stat identity and both
    # adjacent transitions remain as non-erasable evidence.
    assert (seeded_repo / "README.md").read_text() == "test repo\n"
    assert invariant["before"]["head"]["digest"] == invariant["after"]["head"]["digest"]
    violations = dispatcher.store.load(result["task_id"]).policy_violations
    assert "worker:primary_tree_changed:README.md" in violations
    assert "validation:primary_tree_changed:README.md" in violations


async def test_validation_only_primary_interference_is_attributed_to_validation(
    dispatcher,
    request_payload,
    fake_env,
    monkeypatch,
    seeded_repo,
    tmp_path,
):
    """A validator escape is a policy violation, but never blamed on worker."""

    meddler = tmp_path / "validation_touches_primary.py"
    meddler.write_text(
        "from pathlib import Path\n"
        f"Path({str(seeded_repo / 'validation-was-here.txt')!r}).write_text('escaped\\n')\n"
    )
    request_payload["validation"] = {
        "commands": [{"argv": [sys.executable, str(meddler)]}]
    }

    result = await _dispatch_touching(dispatcher, request_payload, monkeypatch)

    assert result["status"] == TaskState.POLICY_VIOLATION.value, result
    invariant = _evidence_json(
        dispatcher, result["task_id"], "primary-tree-invariant.json"
    )
    assert invariant["worker_interval"]["held"] is True
    assert invariant["worker_interval"]["repository_authority_held"] is True
    assert invariant["validation_interval"]["held"] is False
    assert invariant["validation_interval"]["repository_authority_held"] is True
    divergence = invariant["validation_interval"]["divergence"]
    assert divergence["attributed_to"] == "validation"
    assert divergence["appeared"] == ["validation-was-here.txt"]
    error = result["last_error"]
    assert error["error"] == "PolicyViolation"
    assert error["message"].startswith("Validation changed")
    violations = dispatcher.store.load(result["task_id"]).policy_violations
    assert "validation:primary_tree_appeared:?? validation-was-here.txt" in violations
    assert "primary_tree_appeared:?? validation-was-here.txt" not in violations

    for name in (
        "primary-tree-worker-start.json",
        "primary-tree-worker-exit.json",
        "primary-tree-validation-exit.json",
    ):
        terminal = _evidence_json(dispatcher, result["task_id"], name)
        assert terminal["repository_authority"]
        assert terminal["tree"]
        assert terminal["head"]


async def test_an_unmeasurable_primary_tree_fails_closed(
    dispatcher, request_payload, fake_env, monkeypatch, seeded_repo
):
    """P0-3 at this call site: "could not look" is never "nothing changed".

    ``capture_snapshot`` raises rather than returning a partial snapshot, so a
    dispatch whose primary tree cannot be measured lands FAILED with the
    diagnostics preserved — it must never reach AWAITING_SOL_REVIEW.
    """
    from sol_claude_dispatcher import server as server_module
    from sol_claude_dispatcher.errors import FilesystemSnapshotFailed

    real = server_module.capture_snapshot

    def _fail_post(root, *, role, fidelity="content_hash_all", **kwargs):
        if role == "primary_post":
            raise FilesystemSnapshotFailed(
                "The primary tree could not be measured completely.",
                details={"role": role},
            )
        return real(root, role=role, fidelity=fidelity, **kwargs)

    monkeypatch.setattr(server_module, "capture_snapshot", _fail_post)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["error"] == "FilesystemSnapshotFailed", result
    # The refusal payload is concise by design (§29); the task is on disk.
    task_ids = dispatcher.store.list_tasks()
    assert len(task_ids) == 1
    record = dispatcher.store.load(task_ids[0])
    assert record.state is TaskState.FAILED
    assert record.state is not TaskState.AWAITING_SOL_REVIEW
    assert record.last_error["error"] == "FilesystemSnapshotFailed"


# ---------------------------------------------------------------------------
# P1-7 — two-phase evidence
# ---------------------------------------------------------------------------


async def test_validation_generated_paths_are_seen_and_attributed_to_the_dispatcher(
    dispatcher, request_payload, fake_env, monkeypatch, mutating_validation
):
    """Post-worker evidence is stale the moment a validation command writes.

    Pre-fix, ``changed-paths.json`` and the observations were measured *before*
    validation ran, so ``src/deploy/generated.py`` appeared nowhere at all.
    """
    request_payload["validation"] = mutating_validation(in_scope=True)

    result = await _dispatch_touching(dispatcher, request_payload, monkeypatch)
    task_id = result["task_id"]

    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value, result
    observations = result["dispatcher_observations"]
    # The authoritative worker delta is immutable after WORKER_EXIT.
    assert observations["changed_paths"] == ["src/deploy/deploy.py"]

    attribution = result["evidence_attribution"]
    assert attribution["worker_changed_paths"] == ["src/deploy/deploy.py"]
    assert attribution["validation_added_paths"] == ["src/deploy/generated.py"]
    assert set(attribution["final_changed_paths"]) == {
        "src/deploy/deploy.py",
        "src/deploy/generated.py",
    }

    # Both phases are on disk, distinguishable, and agree with the response.
    pre = _evidence_json(dispatcher, task_id, "pre-validation-changed-paths.json")
    post = _evidence_json(dispatcher, task_id, "changed-paths.json")
    assert pre["phase"] == "pre-validation"
    assert pre["changed_paths"] == ["src/deploy/deploy.py"]
    assert post["changed_paths"] == ["src/deploy/deploy.py"]
    phases = _evidence_json(dispatcher, task_id, "evidence-phases.json")
    assert phases["validation_added_paths"] == ["src/deploy/generated.py"]

    # Canonical evidence remains the worker's immutable delta.  Validation
    # outputs are separately attributed and named in the review prompt.
    patch = _evidence(dispatcher, task_id, "diff.patch")
    assert "touched by fake claude" in patch
    assert "validated" not in patch
    assert post["diff_patch_complete"] is True


async def test_out_of_scope_validation_output_is_attributed_not_charged_to_worker(
    dispatcher, request_payload, fake_env, monkeypatch, mutating_validation
):
    """Validation output is recorded separately from the worker scope verdict."""
    request_payload["validation"] = mutating_validation(in_scope=True, out_of_scope=True)

    result = await _dispatch_touching(dispatcher, request_payload, monkeypatch)

    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value, result
    assert result["scope"]["out_of_scope"] == []

    attribution = result["evidence_attribution"]
    assert attribution["worker_changed_paths"] == ["src/deploy/deploy.py"]
    assert set(attribution["validation_added_paths"]) == {
        ".coverage",
        "docs",
        "docs/coverage.xml",
        "src/deploy/generated.py",
    }
    # The pre-validation phase proves the worker never touched those paths.
    pre = _evidence_json(
        dispatcher, result["task_id"], "pre-validation-changed-paths.json"
    )
    assert ".coverage" not in pre["changed_paths"]
    assert "docs/coverage.xml" not in pre["changed_paths"]


async def test_the_review_prompt_names_dispatcher_generated_paths(
    dispatcher, request_payload, fake_env, monkeypatch, mutating_validation, worker_invocations
):
    """§19 fairness: the reviewer is told which paths are not the worker's."""
    request_payload["validation"] = mutating_validation(in_scope=True)
    dispatched = await _dispatch_touching(dispatcher, request_payload, monkeypatch)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    await dispatcher.review_task_with_fable(dispatched["task_id"])

    prompt = worker_invocations()[-1]["prompt"]
    assert "## SECTION 5 — VALIDATION FILESYSTEM EFFECTS" in prompt
    assert "validation_only:" in prompt
    assert "- src/deploy/generated.py" in prompt


# ---------------------------------------------------------------------------
# P1-8 wiring (Lane B R1/R2) — only observable at this call site
# ---------------------------------------------------------------------------


async def test_a_very_large_worker_run_still_yields_a_parsed_result(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """Lane B R1: the structured result sits *after* the retention cap.

    Parsing ``worker_run.stdout`` (the retained head+tail with an in-band
    truncation marker) cannot succeed here; parsing ``stdout_for_parsing`` can.
    """
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "huge-output")
    monkeypatch.setenv("FAKE_CLAUDE_NOISE_BYTES", str(3 * 1024 * 1024))

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.AWAITING_SOL_REVIEW.value, result
    assert result["worker_claims"]["status"] == "completed"
    assert result["dispatcher_observations"]["worker_result_parsed"] is True

    run = dispatcher.store.latest_run(result["task_id"])
    assert run is not None
    # The recorded size is what the worker wrote, not what was retained.
    assert run.metadata.stdout_bytes > 3 * 1024 * 1024
    # ...and the record says so, so a reader of state.json never mistakes the
    # excerpt in stdout.json for the whole stream (C-R1).
    assert run.metadata.stdout_truncated is True


async def test_the_complete_worker_stream_reaches_the_run_directory(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """Lane B R2: ``stdout.raw`` is the whole stream; ``stdout.json`` is marked."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "huge-output")
    monkeypatch.setenv("FAKE_CLAUDE_NOISE_BYTES", str(3 * 1024 * 1024))
    monkeypatch.setenv("FAKE_CLAUDE_STDERR_TEXT", "fake claude: diagnostics line\n")

    result = await dispatcher.dispatch_claude_task(request_payload)
    run_dir = Path(dispatcher.store.run_dir(result["task_id"], 1))

    raw = run_dir / "stdout.raw"
    assert raw.is_file()
    assert raw.stat().st_size > 3 * 1024 * 1024
    assert raw.read_text().rstrip().endswith("}")

    retained = (run_dir / "stdout.json").read_text()
    assert len(retained) < raw.stat().st_size
    assert "[dispatcher]" in retained  # never a silently short stream

    # stderr is spooled by the runner and must not be overwritten by the
    # retained excerpt afterwards.
    assert "fake claude: diagnostics line" in (run_dir / "stderr.log").read_text()


# ---------------------------------------------------------------------------
# Lane A R3 — evidence/diff.patch is the complete patch
# ---------------------------------------------------------------------------


async def test_validation_cannot_rewrite_the_persisted_worker_patch(
    dispatcher, request_payload, fake_env, monkeypatch, tmp_path
):
    """A huge validation rewrite cannot replace canonical worker evidence."""
    big = tmp_path / "make_a_big_tracked_change.py"
    big.write_text(
        "from pathlib import Path\n"
        'p = Path.cwd() / "src" / "deploy" / "deploy.py"\n'
        'p.write_text("".join(f"# padding line {i}\\n" for i in range(120000)))\n'
    )
    request_payload["validation"] = {
        "commands": [{"argv": [sys.executable, str(big)], "timeout_seconds": 120}]
    }

    result = await _dispatch_touching(dispatcher, request_payload, monkeypatch)
    task_id = result["task_id"]

    changed = _evidence_json(dispatcher, task_id, "changed-paths.json")
    assert changed["diff_total_bytes"] < 2_000_000, changed
    assert changed["diff_patch_complete"] is True
    assert changed["diff_bytes_retained"] == changed["diff_total_bytes"]
    patch_path = Path(dispatcher.store.task_dir(task_id)) / "evidence" / "diff.patch"
    assert patch_path.stat().st_size == changed["diff_total_bytes"]
    canonical = _evidence_json(dispatcher, task_id, "canonical-evidence.json")
    patch_data = patch_path.read_bytes()
    assert canonical["patch_bytes"] == len(patch_data)
    assert canonical["patch_sha256"] == hashlib.sha256(patch_data).hexdigest()
    assert canonical["patch_file_complete"] is True
    assert "[dispatcher] diff truncated" not in patch_path.read_text()
    assert "touched by fake claude" in patch_path.read_text()
    assert any(
        row["display"] == "src/deploy/deploy.py"
        for row in result["evidence_attribution"]["both_authors"]
    )


async def test_validation_overwrite_of_frozen_evidence_is_detected_and_attributed(
    dispatcher, request_payload, fake_env, monkeypatch, tmp_path
):
    """A live same-uid overwrite fires and lands row 4 as validation tamper."""
    overwrite = tmp_path / "overwrite_frozen_patch.py"
    overwrite.write_text(
        "from pathlib import Path\n"
        f"root = Path({str(dispatcher.store.root)!r})\n"
        "patches = list(root.glob('*/evidence/diff.patch'))\n"
        "assert len(patches) == 1, patches\n"
        "patches[0].write_bytes(b'PWNED')\n"
    )
    request_payload["validation"] = {
        "commands": [
            {"argv": [sys.executable, str(overwrite)], "timeout_seconds": 60}
        ]
    }

    result = await _dispatch_touching(dispatcher, request_payload, monkeypatch)

    assert result["validation_results"][0]["passed"] is True
    assert result["status"] == TaskState.POLICY_VIOLATION.value
    divergences = result["administrative_authority"]["divergences"]
    freeze = next(row for row in divergences if row["code"] == "EvidenceFreezeViolated")
    assert freeze["attributed_to"] == "validation"
    assert freeze["details"]["changed_files"] == ["evidence/diff.patch"]
    patch = Path(dispatcher.store.task_dir(result["task_id"])) / "evidence" / "diff.patch"
    assert patch.read_bytes() == b"PWNED"  # detection, deliberately not prevention
    freeze_record = json.loads(
        Path(dispatcher.store.run_dir(result["task_id"], 1), "evidence-freeze.json").read_text()
    )
    frozen_patch = next(
        row for row in freeze_record["entries"] if row["relpath"] == "evidence/diff.patch"
    )
    assert frozen_patch["sha256"] != hashlib.sha256(b"PWNED").hexdigest()


async def test_complete_patch_reaches_fable_without_clipping(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """The success half: every canonical patch byte reaches the reviewer."""
    dispatched = await _dispatch_touching(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    patch = dispatcher.store.read_evidence(task_id, "diff.patch")
    assert patch

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    result = await dispatcher.review_task_with_fable(task_id)
    assert "error" not in result, result

    prompt = worker_invocations()[-1]["prompt"]
    assert f"```diff\n{patch}\n```" in prompt
    assert "patch clipped" not in prompt
    patch_section = prompt[
        prompt.index("## SECTION 2"):prompt.index("## SECTION 3")
    ]
    assert "truncated" not in patch_section


async def test_incomplete_canonical_patch_refuses_before_fable_spawn(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """Representation failure is persisted and cannot reach a reviewer."""
    original = server_module.build_canonical_evidence

    def incomplete(*args, **kwargs):
        canonical = original(*args, **kwargs)
        first = canonical.per_path[0]
        return replace(
            canonical,
            per_path=(
                replace(
                    first,
                    sections=(),
                    omission_reason="binary_no_approved_representation",
                ),
                *canonical.per_path[1:],
            ),
        )

    monkeypatch.setattr(server_module, "build_canonical_evidence", incomplete)
    dispatched = await _dispatch_touching(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    metadata = _evidence_json(dispatcher, task_id, "canonical-evidence.json")
    assert metadata["patch_file_complete"] is False
    before_spawns = len(worker_invocations())

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    result = await dispatcher.review_task_with_fable(task_id)

    assert result["error"] == "EvidenceIncompleteForReview", result
    assert len(worker_invocations()) == before_spawns


async def test_a_symlinked_diff_patch_is_refused_rather_than_reviewed(
    dispatcher, request_payload, fake_env, monkeypatch, tmp_path
):
    """Tampered evidence is refused, not followed out of the state tree."""
    dispatched = await _dispatch_touching(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]

    outside = tmp_path / "elsewhere.patch"
    outside.write_text("attacker-controlled content\n")
    patch_path = Path(dispatcher.store.task_dir(task_id)) / "evidence" / "diff.patch"
    patch_path.unlink()
    patch_path.symlink_to(outside)

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    result = await dispatcher.review_task_with_fable(task_id)

    assert result["error"] == "EvidenceFreezeViolated", result


# ---------------------------------------------------------------------------
# adjacent: evidence lands before the state decision
# ---------------------------------------------------------------------------


async def test_evidence_is_on_disk_even_when_the_run_lands_a_violation(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """§13/§20: a refusal never costs the evidence that justifies it."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")  # default touch list
    result = await dispatcher.dispatch_claude_task(request_payload)
    task_id = result["task_id"]

    assert result["status"] == TaskState.POLICY_VIOLATION.value
    for name in (
        "diff.patch",
        "diff-stat.txt",
        "changed-paths.json",
        "status.txt",
        "diff-check.txt",
        "evidence-phases.json",
        "pre-validation-changed-paths.json",
        "primary-tree-before.json",
        "primary-tree-after.json",
        "primary-tree-worker-start.json",
        "primary-tree-worker-exit.json",
        "primary-tree-validation-exit.json",
        "primary-tree-invariant.json",
        "primary-tree-status.txt",
    ):
        assert dispatcher.store.read_evidence(task_id, name) is not None, name


def test_the_test_repository_is_a_real_git_top_level(seeded_repo: Path):
    """Guards the R1 fixture change: the allowlist must name a repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=seeded_repo,
        capture_output=True,
        text=True,
        env=dict(GIT_ENV, HOME=str(seeded_repo.parent)),
    )
    assert result.returncode == 0
    assert Path(result.stdout.strip()).resolve() == seeded_repo.resolve()
