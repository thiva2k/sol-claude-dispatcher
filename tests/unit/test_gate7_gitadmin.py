"""Gate 7 repository-administration capture and reconciliation tests."""

from __future__ import annotations

import hashlib
import os
import zlib
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import (
    GitAdministrativeCaptureFailed,
    RepositoryAdministrationUnestablished,
    RepositoryAdministrationUnreconciled,
    RepositoryObjectStoreEntryUnsupported,
    RepositoryObjectStoreMalformed,
)
from sol_claude_dispatcher.evidence.gitadmin import (
    ObjectEntry,
    baseline_path,
    capture_repository_administration,
    load_baseline,
    reconcile_repository_administration,
    repository_identity_key,
    validate_loose_object_sha1,
    write_baseline,
)


def _init_raw_repo(root: Path, config: bytes = b"[core]\n\trepositoryformatversion = 0\n") -> Path:
    gitdir = root / ".git"
    (gitdir / "objects" / "info").mkdir(parents=True)
    (gitdir / "objects" / "pack").mkdir()
    (gitdir / "refs" / "heads").mkdir(parents=True)
    (gitdir / "config").write_bytes(config)
    (gitdir / "HEAD").write_bytes(b"ref: refs/heads/main\n")
    return gitdir


def _write_loose(gitdir: Path, kind: str, payload: bytes) -> tuple[str, Path]:
    canonical = f"{kind} {len(payload)}\0".encode() + payload
    oid = hashlib.sha1(canonical).hexdigest()
    path = gitdir / "objects" / oid[:2] / oid[2:]
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(zlib.compress(canonical))
    return oid, path


def test_repository_identity_key_is_sha256_of_canonical_realpath(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(repo, target_is_directory=True)
    expected = hashlib.sha256(os.fsencode(os.path.realpath(repo))).hexdigest()
    assert repository_identity_key(alias) == expected


def test_raw_config_includes_are_captured_without_git(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    gitdir = _init_raw_repo(
        repo,
        b"[include]\n\tpath = included.conf\n[filter \"hostile\"]\n\tsmudge = bare-helper\n",
    )
    included = gitdir / "included.conf"
    included.write_bytes(b"[diff \"x\"]\n\ttextconv = /bin/false\n")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("repository capture must not spawn a process")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    snapshot = capture_repository_administration(repo)

    labels = {entry.relative_path for entry in snapshot.exact_entries}
    keys = {assignment.key for assignment in snapshot.exec_assignments}
    assert "config" in labels
    assert "included.conf" in labels
    assert "filter.hostile.smudge" in keys
    assert "diff.x.textconv" in keys


def test_malformed_include_fails_closed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_raw_repo(repo, b"[include]\n\tpath = missing.conf\n")
    with pytest.raises(GitAdministrativeCaptureFailed):
        capture_repository_administration(repo)


def test_object_entry_is_regular_only_and_digest_never_null(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    gitdir = _init_raw_repo(repo)
    _, path = _write_loose(gitdir, "blob", b"payload")
    snapshot = capture_repository_administration(repo)
    entry = next(item for item in snapshot.loose_objects if item.relative_path.endswith(path.name))
    assert entry.entry_type == "regular"
    assert len(entry.sha256_digest) == 64
    assert ObjectEntry.from_dict(entry.to_dict()) == entry


def test_same_length_loose_symlink_target_change_never_enters_value_domain(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    gitdir = _init_raw_repo(repo)
    oid, valid = _write_loose(gitdir, "blob", b"payload")
    data = valid.read_bytes()
    valid.unlink()
    outside = tmp_path / "aa"
    outside.write_bytes(data)
    valid.symlink_to(outside)
    with pytest.raises(RepositoryObjectStoreEntryUnsupported):
        capture_repository_administration(repo)
    valid.unlink()
    outside2 = tmp_path / "bb"
    outside2.write_bytes(data)
    valid.symlink_to(outside2)
    assert len(os.readlink(valid)) == len(str(outside2))
    with pytest.raises(RepositoryObjectStoreEntryUnsupported):
        capture_repository_administration(repo)
    assert valid.name == oid[2:]


def test_canonical_sha1_validator_rejects_corrupt_bytes_at_valid_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    gitdir = _init_raw_repo(repo)
    oid, path = _write_loose(gitdir, "blob", b"payload")
    assert validate_loose_object_sha1(path, expected_oid=oid).oid == oid
    path.write_bytes(b"not-zlib")
    with pytest.raises(RepositoryObjectStoreMalformed):
        validate_loose_object_sha1(path, expected_oid=oid)


def test_reconcile_allows_only_new_canonical_loose_objects(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    gitdir = _init_raw_repo(repo)
    _write_loose(gitdir, "blob", b"baseline")
    baseline = capture_repository_administration(repo)
    oid, _ = _write_loose(gitdir, "blob", b"later")
    current = capture_repository_administration(repo, baseline=baseline)
    result = reconcile_repository_administration(baseline, current)
    assert result.reconciled is True
    assert result.new_loose_objects == (f"objects/{oid[:2]}/{oid[2:]}",)
    assert baseline != current


@pytest.mark.parametrize(
    "mutation",
    [
        "remove_loose",
        "alter_loose_same_size",
        "new_pack",
        "new_pack_directory",
        "new_info",
        "new_ref",
    ],
)
def test_exact_and_baseline_relations_refuse_divergence(tmp_path: Path, mutation: str) -> None:
    repo = tmp_path / mutation
    repo.mkdir()
    gitdir = _init_raw_repo(repo)
    _, loose = _write_loose(gitdir, "blob", b"baseline")
    baseline = capture_repository_administration(repo)

    if mutation == "remove_loose":
        loose.unlink()
    elif mutation == "alter_loose_same_size":
        raw = bytearray(loose.read_bytes())
        raw[-1] ^= 0xFF
        loose.write_bytes(raw)
    elif mutation == "new_pack":
        (gitdir / "objects" / "pack" / "new.promisor").write_bytes(b"marker")
    elif mutation == "new_pack_directory":
        (gitdir / "objects" / "pack" / "nested").mkdir()
    elif mutation == "new_info":
        (gitdir / "objects" / "info" / "alternates").write_bytes(b"/tmp/objects\n")
    else:
        (gitdir / "refs" / "heads" / "other").write_bytes(b"0" * 40 + b"\n")

    # Existing corrupt entries remain capturable for a precise equality verdict;
    # canonical validation is the admission predicate for baseline creation and
    # later appends.
    current = capture_repository_administration(repo, baseline=baseline)
    with pytest.raises(RepositoryAdministrationUnreconciled):
        reconcile_repository_administration(baseline, current)


def test_baseline_write_load_is_atomic_private_and_never_automatic(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_raw_repo(repo)
    snapshot = capture_repository_administration(repo)
    state_root = tmp_path / "state"
    path = write_baseline(state_root, snapshot)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert load_baseline(state_root, repo) == snapshot
    before = path.read_bytes()
    # Reconciliation is a pure comparison and cannot launder current state into
    # the operator baseline.
    assert reconcile_repository_administration(snapshot, snapshot).reconciled
    assert path.read_bytes() == before


def test_selected_worktree_registration_is_captured_by_sealed_provenance_only(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    gitdir = _init_raw_repo(repo)
    selected = gitdir / "worktrees" / "arbitrary-git-id"
    unaccounted = gitdir / "worktrees" / "sol-looking-but-unaccounted"
    for registration in (selected, unaccounted):
        (registration / "logs").mkdir(parents=True)
        (registration / "HEAD").write_bytes(b"1" * 40 + b"\n")
        (registration / "ORIG_HEAD").write_bytes(b"1" * 40 + b"\n")
        (registration / "commondir").write_bytes(b"../..\n")
        (registration / "gitdir").write_bytes(b"/task/.git\n")
        (registration / "index").write_bytes(b"index")
        (registration / "logs" / "HEAD").write_bytes(b"reflog")

    snapshot = capture_repository_administration(
        repo, selected_worktree_gitdir=selected
    )

    captured = {
        entry.relative_path
        for entry in (
            snapshot.registration_exact_entries
            + snapshot.registration_report_entries
        )
    }
    assert captured == {
        "worktree-registration/arbitrary-git-id/HEAD",
        "worktree-registration/arbitrary-git-id/ORIG_HEAD",
        "worktree-registration/arbitrary-git-id/commondir",
        "worktree-registration/arbitrary-git-id/gitdir",
        "worktree-registration/arbitrary-git-id/index",
        "worktree-registration/arbitrary-git-id/logs/HEAD",
    }
    assert not any("sol-looking" in path for path in captured)
    assert {
        entry.relative_path for entry in snapshot.registration_report_entries
    } == {
        "worktree-registration/arbitrary-git-id/index",
        "worktree-registration/arbitrary-git-id/logs/HEAD",
    }


def test_selected_registration_exact_changes_refuse_but_report_only_changes_do_not(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    gitdir = _init_raw_repo(repo)
    registration = gitdir / "worktrees" / "opaque-id"
    (registration / "logs").mkdir(parents=True)
    (registration / "HEAD").write_bytes(b"1" * 40 + b"\n")
    (registration / "commondir").write_bytes(b"../..\n")
    (registration / "gitdir").write_bytes(b"/task/.git\n")
    (registration / "index").write_bytes(b"before")
    (registration / "logs" / "HEAD").write_bytes(b"before")
    baseline = capture_repository_administration(
        repo, selected_worktree_gitdir=registration
    )

    (registration / "index").write_bytes(b"after")
    (registration / "logs" / "HEAD").write_bytes(b"after")
    report_only = capture_repository_administration(
        repo,
        baseline=baseline,
        selected_worktree_gitdir=registration,
    )
    assert reconcile_repository_administration(baseline, report_only).reconciled

    (registration / "HEAD").write_bytes(b"2" * 40 + b"\n")
    changed = capture_repository_administration(
        repo,
        baseline=report_only,
        selected_worktree_gitdir=registration,
    )
    with pytest.raises(RepositoryAdministrationUnreconciled) as raised:
        reconcile_repository_administration(report_only, changed)
    assert raised.value.details["changed_registration"] == [
        "worktree-registration/opaque-id/HEAD"
    ]


def test_absent_baseline_is_unestablished_not_a_capture_failure(tmp_path: Path) -> None:
    """A repository nobody has onboarded is a distinct condition from a broken one.

    Both refuse, but only this one is remediable by running trust-repo-admin.py,
    and the operator cannot tell which situation they are in from the refusal
    alone unless the taxonomy separates them (GATE7-DESIGN.md ORDER 1, R6).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_raw_repo(repo)

    with pytest.raises(RepositoryAdministrationUnestablished) as excinfo:
        load_baseline(tmp_path / "state", repo)

    assert "trust-repo-admin.py" in (excinfo.value.remediation or "")


def test_unreadable_baseline_is_still_a_capture_failure(tmp_path: Path) -> None:
    """An established-but-unreadable baseline must NOT be reported as absent.

    Onboarding it again would silently replace a baseline a human approved, so
    this case keeps the capture-failure taxonomy and its own remediation.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_raw_repo(repo)
    state = tmp_path / "state"
    path = write_baseline(state, capture_repository_administration(repo))
    path.chmod(0o000)
    try:
        if os.access(path, os.R_OK):  # running as root: the mode cannot deny us
            pytest.skip("filesystem permissions are not enforced for this user")
        with pytest.raises(GitAdministrativeCaptureFailed):
            load_baseline(state, repo)
    finally:
        path.chmod(0o600)


def _baseline_at(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A captured repo plus the state root and baseline path for it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_raw_repo(repo)
    state = tmp_path / "state"
    path = baseline_path(state, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    return repo, state, path


def test_a_symlinked_baseline_is_never_followed(tmp_path: Path) -> None:
    """The baseline is the trust anchor; its bytes must come from the state dir.

    Following a symlink would let approved administrative state live anywhere on
    the filesystem, outside the 0700 directory the dispatcher owns, where a
    process that cannot write the state dir could still choose what the
    dispatcher trusts.
    """
    repo, state, path = _baseline_at(tmp_path)
    elsewhere = tmp_path / "elsewhere.json"
    real = write_baseline(state, capture_repository_administration(repo))
    elsewhere.write_bytes(real.read_bytes())
    real.unlink()
    path.symlink_to(elsewhere)

    with pytest.raises(GitAdministrativeCaptureFailed):
        load_baseline(state, repo)


def test_a_dangling_baseline_symlink_is_refused_not_reported_absent(
    tmp_path: Path,
) -> None:
    """"Absent" invites onboarding; a planted symlink must not earn that answer.

    Reporting Unestablished here would tell the operator to run
    trust-repo-admin.py, and onboarding would then replace whatever the link
    points at -- turning a suspicious artefact into an approved baseline.
    """
    _repo, state, path = _baseline_at(tmp_path)
    path.symlink_to(tmp_path / "nowhere.json")

    with pytest.raises(GitAdministrativeCaptureFailed):
        load_baseline(state, _repo)


def test_write_refuses_a_dangling_symlink_without_replace(tmp_path: Path) -> None:
    """`exists()` is False for a dangling link, so the guard must use lexists."""
    repo, state, path = _baseline_at(tmp_path)
    path.symlink_to(tmp_path / "nowhere.json")

    with pytest.raises((RepositoryAdministrationUnreconciled, GitAdministrativeCaptureFailed)):
        write_baseline(state, capture_repository_administration(repo))


def test_write_refuses_a_non_regular_entry_even_with_replace(tmp_path: Path) -> None:
    """--replace is for reviewed divergence, not for clearing planted artefacts."""
    repo, state, path = _baseline_at(tmp_path)
    path.symlink_to(tmp_path / "nowhere.json")

    with pytest.raises(GitAdministrativeCaptureFailed):
        write_baseline(state, capture_repository_administration(repo), replace=True)
