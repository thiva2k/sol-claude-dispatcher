"""Lifecycle invariants the dispatcher must hold end to end (Lane C).

Three findings are pinned here, each against the real ``Dispatcher``, a real
git repository, a real ``TaskStore`` on disk and the fake worker binary:

* **P0/P1-4** — Fable review and worker mutation are serialised by the same
  exclusive repository lock, and the lock is released on every path.
* **P1-5** — the primary working tree is fingerprinted *before* the worker runs
  and compared afterwards. The invariant is ``post_state == pre_state``, not
  "the primary tree is clean".
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
import json
import subprocess
import sys
from pathlib import Path

import pytest

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


async def test_a_review_while_a_worker_holds_the_repository_is_refused(
    dispatcher, request_payload, fake_env, monkeypatch, integration_config
):
    """The mirror image: Fable refuses rather than reading a moving tree."""
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

    assert review["error"] == "RepositoryBusy", review
    assert "lock_path" in review["details"]


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
    assert failed["error"] == "ClaudeStructuredOutputInvalid"

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
    assert invariant["before"]["porcelain_status"] == ""
    assert invariant["after"]["porcelain_status"] == ""
    assert invariant["before"]["head_commit"] == invariant["after"]["head_commit"]


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
    # The raw measurement is honest about the tree being dirty; the invariant
    # verdict is the separate, correct question.
    assert result["dispatcher_observations"]["primary_worktree_clean"] is False
    invariant = _evidence_json(dispatcher, result["task_id"], "primary-tree-invariant.json")
    assert invariant["held"] is True
    assert " M README.md" in invariant["before"]["status_lines"]
    assert invariant["before"]["status_lines"] == invariant["after"]["status_lines"]


@pytest.mark.parametrize(
    "action,expected_marker",
    [
        ("modify", "primary_tree_appeared: M README.md"),
        ("add", "primary_tree_appeared:?? worker-was-here.txt"),
        ("delete", "primary_tree_appeared: D README.md"),
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

    # Both halves of the evidence survive, which is what makes the verdict
    # checkable by a human rather than merely asserted.
    task_id = result["task_id"]
    assert _evidence(dispatcher, task_id, "primary-tree-before.txt")
    assert _evidence(dispatcher, task_id, "primary-tree-after.txt")
    invariant = _evidence_json(dispatcher, task_id, "primary-tree-invariant.json")
    assert invariant["held"] is False
    assert invariant["divergence"]["status_entries_appeared"]


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


async def test_an_unmeasurable_primary_tree_fails_closed(
    dispatcher, request_payload, fake_env, monkeypatch, seeded_repo
):
    """P0-3 at this call site: "could not look" is never "nothing changed".

    ``primary_tree_status`` raises rather than returning ``""`` now, so a
    dispatch whose primary tree cannot be fingerprinted lands FAILED with the
    diagnostics preserved — it must never reach AWAITING_SOL_REVIEW.
    """
    from sol_claude_dispatcher import server as server_module
    from sol_claude_dispatcher.errors import GitEvidenceCollectionFailed

    calls = {"n": 0}
    real = server_module.primary_tree_status

    def _fail_after_the_baseline(repo):
        calls["n"] += 1
        if calls["n"] > 1:
            raise GitEvidenceCollectionFailed(
                "git evidence could not be collected: the git command failed.",
                details={"what": "git status --porcelain (primary tree)"},
            )
        return real(repo)

    monkeypatch.setattr(server_module, "primary_tree_status", _fail_after_the_baseline)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["error"] == "GitEvidenceCollectionFailed", result
    # The refusal payload is concise by design (§29); the task is on disk.
    task_ids = dispatcher.store.list_tasks()
    assert len(task_ids) == 1
    record = dispatcher.store.load(task_ids[0])
    assert record.state is TaskState.FAILED
    assert record.state is not TaskState.AWAITING_SOL_REVIEW
    assert record.last_error["error"] == "GitEvidenceCollectionFailed"


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
    # The final state is what is on disk, and it is what gets policed.
    assert "src/deploy/generated.py" in observations["changed_paths"]

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
    assert "src/deploy/generated.py" in post["changed_paths"]
    phases = _evidence_json(dispatcher, task_id, "evidence-phases.json")
    assert phases["validation_added_paths"] == ["src/deploy/generated.py"]

    # The reviewed patch is the final one, so Fable is not reviewing a fiction:
    # validation rewrote deploy.py after the worker did, and that is what the
    # patch shows. (An untracked file never appears in `git diff`; that is what
    # changed-paths.json is for.)
    patch = _evidence(dispatcher, task_id, "diff.patch")
    assert "validated" in patch
    assert "touched by fake claude" not in patch
    assert post["diff_patch_complete"] is True


async def test_out_of_scope_validation_output_is_refused_but_attributed(
    dispatcher, request_payload, fake_env, monkeypatch, mutating_validation
):
    """Safe first, fair second: refuse on the final state, record who did it.

    An out-of-scope file is a policy violation whoever created it — the
    dispatcher will not decide that its own artefact is acceptable. What it
    *does* guarantee is that the record says the dispatcher created it, so Sol
    never charges it to Claude.
    """
    request_payload["validation"] = mutating_validation(in_scope=True, out_of_scope=True)

    result = await _dispatch_touching(dispatcher, request_payload, monkeypatch)

    assert result["status"] == TaskState.POLICY_VIOLATION.value, result
    assert sorted(result["scope"]["out_of_scope"]) == [".coverage", "docs/coverage.xml"]

    attribution = result["evidence_attribution"]
    assert attribution["worker_changed_paths"] == ["src/deploy/deploy.py"]
    assert set(attribution["validation_added_paths"]) == {
        ".coverage",
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
    assert "Paths produced by the dispatcher's own validation" in prompt
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


async def test_the_persisted_patch_is_untruncated_even_past_the_memory_cap(
    dispatcher, request_payload, fake_env, monkeypatch, tmp_path
):
    """Fable reviews ``evidence/diff.patch``; a shortened one reviews a fiction.

    ``collect_diff_evidence`` still caps the diff it holds *in memory* at 2 MB.
    Pre-fix that capped string was what got written to disk, so a large change
    was reviewed as a fragment. ``write_full_diff`` streams the real patch.
    """
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
    assert changed["diff_total_bytes"] > 2_000_000, changed
    assert changed["diff_patch_complete"] is True
    # The retained in-memory value is capped; the file on disk is not.
    assert changed["diff_bytes_retained"] <= 2_000_000
    patch_path = Path(dispatcher.store.task_dir(task_id)) / "evidence" / "diff.patch"
    assert patch_path.stat().st_size == changed["diff_total_bytes"]
    assert "[dispatcher] diff truncated" not in patch_path.read_text()


async def test_an_enormous_patch_is_clipped_when_read_into_a_review_prompt(
    dispatcher, request_payload, fake_env, monkeypatch, worker_invocations
):
    """The complete patch is unbounded; reading it into a prompt must not be.

    Adjacent to Lane A R3: making ``diff.patch`` complete removed the only
    bound on that read, and the reader is a prompt that clips at 120k
    characters anyway.
    """
    dispatched = await _dispatch_touching(dispatcher, request_payload, monkeypatch)
    task_id = dispatched["task_id"]
    dispatcher.store.write_evidence(task_id, "diff.patch", "d" * 9_000_000)

    # The read itself is bounded and says so; the prompt then clips further.
    read_back = dispatcher._prompt_diff_text(task_id)
    assert len(read_back) < 300_000
    assert "[dispatcher] patch clipped at" in read_back
    assert "9000000-byte patch is evidence/diff.patch" in read_back

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fable-review")
    await dispatcher.review_task_with_fable(task_id)

    prompt = worker_invocations()[-1]["prompt"]
    assert len(prompt) < 400_000
    assert "truncated at 120000 characters by the dispatcher" in prompt
    # The complete patch is untouched on disk.
    patch_path = Path(dispatcher.store.task_dir(task_id)) / "evidence" / "diff.patch"
    assert patch_path.stat().st_size == 9_000_000


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

    assert result["error"] == "StateCorruption", result


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
        "primary-tree-before.txt",
        "primary-tree-after.txt",
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
