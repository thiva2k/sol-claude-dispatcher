from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from sol_claude_dispatcher.evidence.content import ContentInput, classify_change, git_blob_oid
from sol_claude_dispatcher.evidence.patch import (
    DiffBudgetExceeded,
    build_canonical_evidence,
    c_quote_path,
    render_change,
)


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    env = {"PATH": os.environ["PATH"], "HOME": str(repo / "home"), "GIT_CONFIG_NOSYSTEM": "1"}
    (repo / "home").mkdir(exist_ok=True)
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, input=input_bytes, capture_output=True, check=False
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "-q").returncode == 0
    assert _git(repo, "config", "user.email", "test@example.invalid").returncode == 0
    assert _git(repo, "config", "user.name", "Test").returncode == 0
    return repo


def _apply_and_read(tmp_path: Path, change, expected_path: bytes) -> Path:
    repo = _repo(tmp_path)
    patch = render_change(change).patch_bytes
    checked = _git(repo, "apply", "--check", input_bytes=patch)
    assert checked.returncode == 0, checked.stderr.decode(errors="replace")
    applied = _git(repo, "apply", input_bytes=patch)
    assert applied.returncode == 0, applied.stderr.decode(errors="replace")
    return Path(os.fsdecode(os.fsencode(repo) + b"/" + expected_path))


def test_empty_new_file_has_mode_and_no_hunk_and_applies(tmp_path: Path) -> None:
    change = classify_change(b"empty", ContentInput.absent(), ContentInput.regular(b""))
    rendered = render_change(change)
    assert b"new file mode 100644\n" in rendered.patch_bytes
    assert b"@@" not in rendered.patch_bytes
    result = _apply_and_read(tmp_path, change, b"empty")
    assert result.read_bytes() == b""


@pytest.mark.parametrize("path", [b"space name.txt", b"new\nline.txt"])
def test_hostile_path_headers_wrap_prefix_and_apply(tmp_path: Path, path: bytes) -> None:
    change = classify_change(path, ContentInput.absent(), ContentInput.regular(b"payload\n"))
    rendered = render_change(change)
    if b"\n" in path:
        assert b'"a/new\\nline.txt"' in rendered.patch_bytes
        assert b'a/"new\\nline.txt"' not in rendered.patch_bytes
    else:
        assert b"+++ b/space name.txt\n" in rendered.patch_bytes
    result = _apply_and_read(tmp_path, change, path)
    assert result.read_bytes() == b"payload\n"


def test_dangling_symlink_patch_is_exact_and_uses_independent_oids(tmp_path: Path) -> None:
    target = b"../missing\nsecond"
    change = classify_change(b"link", ContentInput.absent(), ContentInput.symlink(target))
    rendered = render_change(change)
    assert b"new file mode 120000" in rendered.patch_bytes
    assert git_blob_oid(target).encode() in rendered.patch_bytes
    result = _apply_and_read(tmp_path, change, b"link")
    assert result.is_symlink()
    assert os.readlink(os.fsencode(result)) == target


def test_symlink_to_regular_kind_change_is_two_sections() -> None:
    change = classify_change(
        b"same", ContentInput.symlink(b"target"), ContentInput.regular(b"body\n")
    )
    rendered = render_change(change)
    assert len(rendered.sections) == 2
    assert b"deleted file mode 120000" in rendered.sections[0]
    assert b"new file mode 100644" in rendered.sections[1]


def test_modified_file_uses_native_myers_script_and_applies(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "x.txt").write_bytes(b"one\ntwo\nthree\n")
    change = classify_change(
        b"x.txt",
        ContentInput.regular(b"one\ntwo\nthree\n"),
        ContentInput.regular(b"one\nchanged\nthree\nfour\n"),
    )
    rendered = render_change(change)
    assert rendered.additions == 2
    assert rendered.deletions == 1
    result = _git(repo, "apply", "--check", input_bytes=rendered.patch_bytes)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    result = _git(repo, "apply", input_bytes=rendered.patch_bytes)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert (repo / "x.txt").read_bytes() == b"one\nchanged\nthree\nfour\n"


def test_binary_and_unreadable_paths_are_accounted_but_make_patch_incomplete(tmp_path: Path) -> None:
    changes = (
        classify_change(b"binary", ContentInput.absent(), ContentInput.regular(b"a\0b")),
        classify_change(
            b"unreadable",
            ContentInput.absent(),
            ContentInput(kind="regular", data=None, mode=0o100644, read_error="EACCES"),
        ),
    )
    evidence = build_canonical_evidence(changes, base_commit="a" * 40, patch_path=tmp_path / "diff.patch")
    assert len(evidence.per_path) == 2
    assert evidence.patch_file_complete is False
    assert {row.omission_reason for row in evidence.per_path} == {
        "binary_no_approved_representation",
        "unreadable",
    }
    assert (tmp_path / "diff.patch").read_bytes() == b""


def test_diff_check_scans_added_lines_without_git(tmp_path: Path) -> None:
    body = b"ok\ntrailing \nspace \tbad\n<<<<<<< ours\n======= \n>>>>>>> theirs\n"
    change = classify_change(b"bad.txt", ContentInput.absent(), ContentInput.regular(body))
    evidence = build_canonical_evidence((change,), base_commit="b" * 40, patch_path=tmp_path / "diff.patch")
    kinds = [finding.kind for finding in evidence.check_findings]
    assert kinds.count("trailing_whitespace") >= 2
    assert "space_before_tab" in kinds
    assert kinds.count("conflict_marker") == 3
    assert evidence.diff_check_passed is False


def test_native_diff_refuses_before_pathological_work() -> None:
    change = classify_change(
        b"large", ContentInput.regular(b"a\n" * 100), ContentInput.regular(b"b\n" * 100)
    )
    with pytest.raises(DiffBudgetExceeded) as caught:
        render_change(change, maximum_input_bytes=10)
    assert caught.value.details["maximum_input_bytes"] == 10


def test_compatibility_diff_evidence_has_existing_shape_and_dispatcher_status(tmp_path: Path) -> None:
    change = classify_change(b"x", ContentInput.absent(), ContentInput.regular(b"x\n"))
    canonical = build_canonical_evidence((change,), base_commit="c" * 40, patch_path=tmp_path / "p")
    compat = canonical.to_diff_evidence()
    assert compat.base_commit == "c" * 40
    assert compat.changed_paths == ["x"]
    assert compat.porcelain_status == "?? x\n"
    assert compat.diff_total_bytes == len(canonical.patch_data)
    assert compat.truncated is False


def test_c_quote_path_is_ascii_stable_for_non_utf8_bytes() -> None:
    assert c_quote_path(b"a/nonutf8-\xff") == b'"a/nonutf8-\\377"'
