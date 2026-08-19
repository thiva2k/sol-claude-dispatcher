"""Adversarial boundary tests: task ids, repository identity, git evidence.

These are the regression tests for the three P0 boundary findings. Each one is
written to fail against the pre-fix implementation:

* **P0-1** — a caller-supplied ``task_id`` reached ``TaskStore.task_dir()`` and
  was joined straight onto ``state/tasks/``. There was no authoritative
  validator and no containment check, so ``../..``-shaped ids escaped the
  task-state root.
* **P0-2** — the repository allowlist accepted ``path == root or root in
  path.parents``, so a *subdirectory* of an allowed repository passed, and
  ``is_git_repository`` only proved "somewhere inside a work tree". One
  repository could therefore have several identities (several lock names,
  several evidence roots).
* **P0-3** — git evidence collection swallowed failures: a failed
  ``ls-files``/``status`` produced an empty result, which is indistinguishable
  from "nothing changed" and would let an unmeasured run land as
  ``changed_paths=[] / scope_valid=true``.

Nothing here spawns ``claude`` or ``codex``; the only subprocess is ``git``
against repositories created under ``tmp_path``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sol_claude_dispatcher import git as git_mod
from sol_claude_dispatcher import locks, security
from sol_claude_dispatcher.config import load_config_from_mapping
from sol_claude_dispatcher.errors import (
    GitEvidenceCollectionFailed,
    InvalidRepository,
    InvalidTaskEnvelope,
    RepositoryNotAllowed,
)
from sol_claude_dispatcher.models import TaskEnvelope, TaskRequest, new_task_id
from sol_claude_dispatcher.state import TaskStore

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


#: Every hostile ``task_id`` shape named in the remediation brief, plus the
#: near-miss UUID spellings that a "normalise it for them" implementation would
#: have quietly accepted.
HOSTILE_TASK_IDS: list[str] = [
    "../escape",
    "../../escape",
    "../../../etc",
    "/foo",
    "//foo",
    "foo/bar",
    "foo\\bar",
    ".",
    "..",
    "",
    " ",
    "\t",
    "\n",
    " 5f9c1f2e-0d3a-4b6f-8a1c-2b3d4e5f6a7b ",
    "5f9c1f2e-0d3a-4b6f-8a1c-2b3d4e5f6a7b\x00",
    "\x00",
    "some random text",
    "not-a-uuid",
    "5f9c1f2e-0d3a-4b6f-8a1c",  # truncated UUID
    "5f9c1f2e0d3a4b6f8a1c2b3d4e5f6a7b",  # unhyphenated
    "5F9C1F2E-0D3A-4B6F-8A1C-2B3D4E5F6A7B",  # uppercase, not canonical
    "{5f9c1f2e-0d3a-4b6f-8a1c-2b3d4e5f6a7b}",  # braced
    "urn:uuid:5f9c1f2e-0d3a-4b6f-8a1c-2b3d4e5f6a7b",
    "g5f9c1f2e-0d3a-4b6f-8a1c-2b3d4e5f6a7",  # non-hex character
    "../" * 40 + "etc",
    "a" * 200,
]

#: The subset that must additionally be refused by ``TaskStore`` itself, i.e.
#: without any help from the MCP-layer validator. (``TaskStore`` deliberately
#: still accepts non-UUID *safe* component names such as ``does-not-exist``,
#: because the store is also used with dispatcher-internal identifiers; what it
#: must never accept is anything that can leave ``state/tasks/``.)
ESCAPING_TASK_IDS: list[str] = [
    "../escape",
    "../../escape",
    "../../../etc",
    "/foo",
    "//foo",
    "foo/bar",
    "foo\\bar",
    ".",
    "..",
    "",
    " ",
    "\t",
    " 5f9c1f2e-0d3a-4b6f-8a1c-2b3d4e5f6a7b ",
    "5f9c1f2e-0d3a-4b6f-8a1c-2b3d4e5f6a7b\x00",
    "\x00",
    "../" * 40 + "etc",
    "a" * 200,
]


def _make_config(project_root: Path, allowed_roots: list[Path]):
    return load_config_from_mapping(
        {
            "dispatcher": {},
            "models": {},
            "routing": {},
            "security": {
                "allowed_repository_roots": [str(r) for r in allowed_roots]
            },
        },
        project_root=str(project_root),
    )


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "main"], path)
    (path / "README.md").write_text("x\n")
    _git(["add", "README.md"], path)
    _git(
        [
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            "init",
        ],
        path,
    )
    return path


def _outside_tree(tmp_path: Path) -> tuple[Path, Path]:
    """A directory outside the state root, with one sentinel file in it."""
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("ORIGINAL")
    return outside, sentinel


def _snapshot(tree: Path) -> dict[str, str]:
    return {
        str(p.relative_to(tree)): p.read_text()
        for p in sorted(tree.rglob("*"))
        if p.is_file()
    }


# ===========================================================================
# P0-1 — task id is an authoritative, fail-closed validator
# ===========================================================================


class TestValidateTaskId:
    @pytest.mark.parametrize("hostile", HOSTILE_TASK_IDS)
    def test_hostile_task_ids_are_refused(self, hostile: str) -> None:
        with pytest.raises(InvalidTaskEnvelope):
            security.validate_task_id(hostile)

    def test_a_dispatcher_issued_task_id_is_accepted_verbatim(self) -> None:
        task_id = new_task_id()
        assert security.validate_task_id(task_id) == task_id

    def test_two_hundred_generated_ids_all_validate(self) -> None:
        for _ in range(200):
            task_id = new_task_id()
            assert security.validate_task_id(task_id) is task_id

    def test_non_string_input_is_refused(self) -> None:
        for value in (None, 12, b"5f9c1f2e-0d3a-4b6f-8a1c-2b3d4e5f6a7b", ["x"]):
            with pytest.raises(InvalidTaskEnvelope):
                security.validate_task_id(value)  # type: ignore[arg-type]

    def test_refusal_does_not_normalise_the_id(self) -> None:
        """A near-miss must be refused, never silently repaired into a valid id."""
        padded = " 5f9c1f2e-0d3a-4b6f-8a1c-2b3d4e5f6a7b "
        with pytest.raises(InvalidTaskEnvelope):
            security.validate_task_id(padded)
        with pytest.raises(InvalidTaskEnvelope):
            security.validate_task_id(padded.strip().upper())


# ===========================================================================
# P0-1 — TaskStore is independently safe (defense in depth)
# ===========================================================================


@pytest.fixture
def store(tmp_path: Path) -> TaskStore:
    return TaskStore(tmp_path / "state" / "tasks")


@pytest.fixture
def real_task(store: TaskStore, valid_request_dict: dict):
    envelope = TaskEnvelope.from_request(
        TaskRequest(**valid_request_dict),
        canonical_root="/tmp/canonical/repo",
        base_commit="a" * 40,
    )
    store.create(envelope)
    return envelope


class TestTaskStoreContainment:
    @pytest.mark.parametrize("hostile", ESCAPING_TASK_IDS)
    def test_task_dir_refuses_escaping_ids(
        self, store: TaskStore, hostile: str
    ) -> None:
        with pytest.raises(InvalidTaskEnvelope):
            store.task_dir(hostile)

    @pytest.mark.parametrize("hostile", ESCAPING_TASK_IDS)
    def test_every_public_reader_refuses_escaping_ids(
        self, store: TaskStore, hostile: str
    ) -> None:
        for call in (
            lambda: store.exists(hostile),
            lambda: store.load(hostile),
            lambda: store.load_envelope(hostile),
            lambda: store.run_dir(hostile, 1),
            lambda: store.load_runs(hostile),
            lambda: store.latest_run(hostile),
            lambda: store.load_reviews(hostile),
            lambda: store.read_evidence(hostile, "diff.patch"),
            lambda: store.write_evidence(hostile, "diff.patch", "x"),
        ):
            with pytest.raises(InvalidTaskEnvelope):
                call()

    def test_traversal_never_reads_a_file_outside_the_state_root(
        self, store: TaskStore, tmp_path: Path
    ) -> None:
        outside, sentinel = _outside_tree(tmp_path)
        before = _snapshot(outside)

        # state/tasks/ is tmp_path/state/tasks, so this is the exact number of
        # hops needed to land on tmp_path/outside/sentinel.txt.
        with pytest.raises(InvalidTaskEnvelope):
            store.read_evidence("../../../outside", "sentinel.txt")
        with pytest.raises(InvalidTaskEnvelope):
            store.write_evidence("../../../outside", "sentinel.txt", "OVERWRITTEN")

        assert _snapshot(outside) == before
        assert sentinel.read_text() == "ORIGINAL"

    def test_traversal_never_creates_a_file_outside_the_state_root(
        self, store: TaskStore, tmp_path: Path
    ) -> None:
        outside, _ = _outside_tree(tmp_path)
        with pytest.raises(InvalidTaskEnvelope):
            store.write_evidence("../../../outside", "planted.txt", "x")
        assert not (outside / "planted.txt").exists()

    def test_evidence_name_may_not_escape_the_task_directory(
        self, store: TaskStore, real_task, tmp_path: Path
    ) -> None:
        outside, sentinel = _outside_tree(tmp_path)
        for name in ("../../../outside/sentinel.txt", "/etc/passwd", "a/b", "..", ""):
            with pytest.raises(InvalidTaskEnvelope):
                store.write_evidence(real_task.task_id, name, "OVERWRITTEN")
        assert sentinel.read_text() == "ORIGINAL"

    def test_symlinked_task_directory_is_refused(
        self, store: TaskStore, tmp_path: Path
    ) -> None:
        """A task dir replaced by a symlink must not redirect reads or writes."""
        outside, sentinel = _outside_tree(tmp_path)
        task_id = new_task_id()
        (store.root / task_id).symlink_to(outside, target_is_directory=True)

        with pytest.raises(InvalidTaskEnvelope):
            store.task_dir(task_id)
        with pytest.raises(InvalidTaskEnvelope):
            store.write_evidence(task_id, "sentinel.txt", "OVERWRITTEN")
        assert sentinel.read_text() == "ORIGINAL"

    def test_negative_and_non_integer_run_index_are_refused(
        self, store: TaskStore, real_task
    ) -> None:
        with pytest.raises(InvalidTaskEnvelope):
            store.run_dir(real_task.task_id, -1)
        with pytest.raises(InvalidTaskEnvelope):
            store.run_dir(real_task.task_id, "1")  # type: ignore[arg-type]

    def test_a_real_task_still_works_end_to_end(
        self, store: TaskStore, real_task
    ) -> None:
        """The containment check must not be a general obstruction."""
        store.write_evidence(real_task.task_id, "diff.patch", "PATCH")
        assert store.read_evidence(real_task.task_id, "diff.patch") == "PATCH"
        assert store.task_dir(real_task.task_id).is_dir()
        assert store.run_dir(real_task.task_id, 1).name == "001"
        assert store.list_tasks() == [real_task.task_id]

    def test_list_tasks_skips_a_symlinked_entry(
        self, store: TaskStore, real_task, tmp_path: Path
    ) -> None:
        outside, _ = _outside_tree(tmp_path)
        (outside / "envelope.json").write_text("{}")
        (store.root / "aaaaaaaa-0000-4000-8000-000000000000").symlink_to(
            outside, target_is_directory=True
        )
        assert store.list_tasks() == [real_task.task_id]


# ===========================================================================
# P0-2 — repository identity is the exact git top level
# ===========================================================================


class TestRepositoryIdentity:
    def test_exact_repository_root_is_accepted(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path / "example-repo")
        config = _make_config(tmp_path, [repo])
        assert security.validate_repository_root(str(repo), config) == repo.resolve()

    def test_subdirectory_of_an_allowed_repository_is_rejected(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path / "example-repo")
        (repo / "src").mkdir()
        config = _make_config(tmp_path, [repo])
        with pytest.raises((InvalidRepository, RepositoryNotAllowed)):
            security.validate_repository_root(str(repo / "src"), config)

    def test_nested_subdirectory_is_rejected(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path / "example-repo")
        (repo / "src" / "foo").mkdir(parents=True)
        config = _make_config(tmp_path, [repo])
        with pytest.raises((InvalidRepository, RepositoryNotAllowed)):
            security.validate_repository_root(str(repo / "src" / "foo"), config)

    def test_parent_of_a_repository_does_not_authorise_the_repository(
        self, tmp_path: Path
    ) -> None:
        """Allowlisting ``/parent`` must not implicitly allow ``/parent/repo``."""
        repo = _init_repo(tmp_path / "example-repo")
        config = _make_config(tmp_path, [tmp_path])
        with pytest.raises((InvalidRepository, RepositoryNotAllowed)):
            security.validate_repository_root(str(repo), config)

    def test_symlink_to_the_repository_resolves_to_the_exact_root(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path / "example-repo")
        alias = tmp_path / "alias"
        alias.symlink_to(repo, target_is_directory=True)
        config = _make_config(tmp_path, [repo])
        assert security.validate_repository_root(str(alias), config) == repo.resolve()

    def test_symlink_to_a_subdirectory_is_still_rejected(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path / "example-repo")
        (repo / "src").mkdir()
        alias = tmp_path / "alias-src"
        alias.symlink_to(repo / "src", target_is_directory=True)
        config = _make_config(tmp_path, [repo])
        with pytest.raises((InvalidRepository, RepositoryNotAllowed)):
            security.validate_repository_root(str(alias), config)

    def test_prefix_lookalike_repository_is_rejected(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path / "example-repo")
        evil = _init_repo(tmp_path / "example-repo-evil")
        config = _make_config(tmp_path, [repo])
        with pytest.raises(RepositoryNotAllowed):
            security.validate_repository_root(str(evil), config)

    def test_repository_outside_the_allowlist_is_rejected(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path / "example-repo")
        other = _init_repo(tmp_path / "other-repo")
        config = _make_config(tmp_path, [repo])
        with pytest.raises(RepositoryNotAllowed):
            security.validate_repository_root(str(other), config)

    def test_trailing_slash_and_dot_segments_canonicalise_to_the_same_root(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path / "example-repo")
        config = _make_config(tmp_path, [repo])
        for spelling in (f"{repo}/", f"{repo}/.", f"{repo}/src/.."):
            (repo / "src").mkdir(exist_ok=True)
            assert (
                security.validate_repository_root(spelling, config) == repo.resolve()
            )

    def test_a_linked_worktree_is_not_the_configured_repository(
        self, tmp_path: Path
    ) -> None:
        """A worktree has its own top level, so it needs its own allowlist entry."""
        repo = _init_repo(tmp_path / "example-repo")
        wt = tmp_path / "wt"
        _git(["worktree", "add", "-q", "-b", "wt", str(wt), "HEAD"], repo)
        config = _make_config(tmp_path, [repo])
        with pytest.raises(RepositoryNotAllowed):
            security.validate_repository_root(str(wt), config)

    def test_git_top_level_reports_the_repository_root_from_a_subdirectory(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path / "example-repo")
        (repo / "src" / "deep").mkdir(parents=True)
        assert git_mod.git_top_level(repo / "src" / "deep") == repo.resolve()

    def test_git_top_level_fails_closed_outside_a_work_tree(
        self, tmp_path: Path
    ) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(InvalidRepository):
            git_mod.git_top_level(plain)
        assert git_mod.git_top_level_or_none(plain) is None

    def test_git_top_level_ignores_an_inherited_git_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An inherited GIT_DIR/GIT_WORK_TREE must not redefine identity."""
        repo = _init_repo(tmp_path / "example-repo")
        decoy = _init_repo(tmp_path / "decoy-repo")
        monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
        monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
        assert git_mod.git_top_level(repo) == repo.resolve()


class TestLockIdentity:
    def test_repository_and_its_subdirectory_share_one_lock(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path / "example-repo")
        (repo / "src").mkdir()
        assert locks.lock_name_for(repo) == locks.lock_name_for(repo / "src")

    def test_a_subdirectory_contends_with_the_repository_lock(
        self, tmp_path: Path
    ) -> None:
        repo = _init_repo(tmp_path / "example-repo")
        (repo / "src").mkdir()
        locks_dir = tmp_path / "locks"

        held = locks.RepositoryLock(repo, locks_dir)
        held.acquire()
        try:
            from sol_claude_dispatcher.errors import RepositoryBusy

            with pytest.raises(RepositoryBusy):
                locks.RepositoryLock(repo / "src", locks_dir).acquire()
        finally:
            held.release()

    def test_two_distinct_repositories_still_do_not_contend(
        self, tmp_path: Path
    ) -> None:
        repo_a = _init_repo(tmp_path / "a")
        repo_b = _init_repo(tmp_path / "b")
        locks_dir = tmp_path / "locks"
        assert locks.lock_name_for(repo_a) != locks.lock_name_for(repo_b)
        lock_a = locks.RepositoryLock(repo_a, locks_dir)
        lock_b = locks.RepositoryLock(repo_b, locks_dir)
        lock_a.acquire()
        try:
            lock_b.acquire()
            lock_b.release()
        finally:
            lock_a.release()


# ===========================================================================
# P0-3 — git evidence fails closed
# ===========================================================================


def _fail_git_matching(monkeypatch: pytest.MonkeyPatch, needle: str, exc) -> None:
    """Make only the git command containing ``needle`` fail with ``exc``."""
    real_run = subprocess.run

    def fake_run(argv, *args, **kwargs):
        if isinstance(argv, list) and needle in argv:
            raise exc
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(git_mod.subprocess, "run", fake_run)


def _nonzero_git_matching(monkeypatch: pytest.MonkeyPatch, needle: str) -> None:
    """Make only the git command containing ``needle`` exit non-zero."""
    real_run = subprocess.run

    def fake_run(argv, *args, **kwargs):
        if isinstance(argv, list) and needle in argv:
            return subprocess.CompletedProcess(
                argv, 128, stdout="", stderr="fatal: injected failure\n"
            )
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(git_mod.subprocess, "run", fake_run)


#: Every authoritative command ``collect_diff_evidence`` depends on.
EVIDENCE_COMMANDS = ["status", "--name-only", "ls-files", "--stat", "--check"]


class TestGitEvidenceFailsClosed:
    @pytest.mark.parametrize("needle", EVIDENCE_COMMANDS)
    def test_a_failing_command_is_never_read_as_no_changes(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch, needle: str
    ) -> None:
        base = git_mod.resolve_base_commit(git_repo, "HEAD")
        _nonzero_git_matching(monkeypatch, needle)
        with pytest.raises(GitEvidenceCollectionFailed):
            git_mod.collect_diff_evidence(git_repo, base)

    @pytest.mark.parametrize("needle", EVIDENCE_COMMANDS + ["diff"])
    def test_a_timing_out_command_fails_closed(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch, needle: str
    ) -> None:
        base = git_mod.resolve_base_commit(git_repo, "HEAD")
        _fail_git_matching(
            monkeypatch, needle, subprocess.TimeoutExpired(cmd="git", timeout=60)
        )
        with pytest.raises(GitEvidenceCollectionFailed):
            git_mod.collect_diff_evidence(git_repo, base)

    def test_missing_git_executable_fails_closed(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base = git_mod.resolve_base_commit(git_repo, "HEAD")
        _fail_git_matching(
            monkeypatch, "status", FileNotFoundError(2, "No such file", "git")
        )
        with pytest.raises(GitEvidenceCollectionFailed):
            git_mod.collect_diff_evidence(git_repo, base)

    def test_untracked_listing_failure_cannot_hide_an_unauthorised_new_file(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The exact fail-open shape: ``ls-files`` failing used to return ``[]``."""
        base = git_mod.resolve_base_commit(git_repo, "HEAD")
        (git_repo / "unauthorised.py").write_text("print('hi')\n")
        _nonzero_git_matching(monkeypatch, "ls-files")
        with pytest.raises(GitEvidenceCollectionFailed) as excinfo:
            git_mod.collect_diff_evidence(git_repo, base)
        assert "ls-files" in str(excinfo.value.details)

    def test_unresolvable_base_commit_fails_closed(self, git_repo: Path) -> None:
        with pytest.raises(GitEvidenceCollectionFailed):
            git_mod.collect_diff_evidence(git_repo, "0" * 40)

    def test_collecting_outside_a_repository_fails_closed(
        self, tmp_path: Path
    ) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(GitEvidenceCollectionFailed):
            git_mod.collect_diff_evidence(plain, "HEAD")

    def test_primary_tree_status_failure_is_never_reported_as_clean(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _nonzero_git_matching(monkeypatch, "status")
        with pytest.raises(GitEvidenceCollectionFailed):
            git_mod.primary_tree_status(git_repo)

    def test_primary_tree_status_outside_a_repository_fails_closed(
        self, tmp_path: Path
    ) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        with pytest.raises(GitEvidenceCollectionFailed):
            git_mod.primary_tree_status(plain)

    def test_worktree_lookup_failure_is_never_reported_as_absent(
        self, git_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``None`` means "git looked and found nothing", not "we could not look"."""
        _nonzero_git_matching(monkeypatch, "worktree")
        with pytest.raises(GitEvidenceCollectionFailed):
            git_mod.worktree_path_for(git_repo, "sol-deadbeef")

    def test_diff_check_whitespace_findings_are_not_collection_failures(
        self, git_repo: Path
    ) -> None:
        base = git_mod.resolve_base_commit(git_repo, "HEAD")
        (git_repo / "trailing.py").write_text("value = 1   \n")
        _git(["add", "trailing.py"], git_repo)
        evidence = git_mod.collect_diff_evidence(git_repo, base)
        assert evidence.diff_check_passed is False
        assert "trailing.py" in evidence.changed_paths


class TestFullDiffPreservation:
    def test_full_patch_is_written_untruncated(self, git_repo: Path) -> None:
        base = git_mod.resolve_base_commit(git_repo, "HEAD")
        (git_repo / "big.py").write_text("x = 1\n" * 100_000)
        _git(["add", "big.py"], git_repo)

        evidence = git_mod.collect_diff_evidence(git_repo, base, max_diff_bytes=1000)
        assert evidence.truncated is True
        assert evidence.diff_total_bytes > 1000

        dest = git_repo.parent / "evidence" / "diff.patch"
        written = git_mod.write_full_diff(git_repo, base, dest)
        assert written == evidence.diff_total_bytes
        assert dest.stat().st_size == evidence.diff_total_bytes
        assert dest.read_text().count("x = 1") >= 100_000

    def test_full_patch_file_is_owner_only(self, git_repo: Path) -> None:
        import stat as stat_mod

        base = git_mod.resolve_base_commit(git_repo, "HEAD")
        (git_repo / "a.py").write_text("a\n")
        _git(["add", "a.py"], git_repo)
        dest = git_repo.parent / "evidence" / "diff.patch"
        git_mod.write_full_diff(git_repo, base, dest)
        assert stat_mod.S_IMODE(dest.stat().st_mode) == 0o600

    def test_full_patch_failure_leaves_no_partial_file(self, git_repo: Path) -> None:
        dest = git_repo.parent / "evidence" / "diff.patch"
        with pytest.raises(GitEvidenceCollectionFailed):
            git_mod.write_full_diff(git_repo, "0" * 40, dest)
        assert not dest.exists()
        assert list(dest.parent.iterdir()) == []
