"""Gate 7 operator onboarding command tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import UnsupportedObjectFormat
from sol_claude_dispatcher.evidence.gitadmin import baseline_path, load_baseline


SCRIPT = Path(__file__).parents[2] / "scripts" / "trust-repo-admin.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("trust_repo_admin", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw_repo(root: Path, object_format: str | None) -> None:
    gitdir = root / ".git"
    (gitdir / "objects" / "info").mkdir(parents=True)
    (gitdir / "objects" / "pack").mkdir()
    (gitdir / "refs").mkdir()
    extension = (
        b""
        if object_format is None
        else f"[extensions]\n\tobjectFormat = {object_format}\n".encode()
    )
    (gitdir / "config").write_bytes(
        b"[core]\n\trepositoryformatversion = 0\n" + extension
    )


@pytest.mark.parametrize("object_format", ["sha256", "future-format"])
def test_unsupported_format_refuses_before_baseline_or_git(
    tmp_path: Path, monkeypatch, object_format: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _raw_repo(repo, object_format)
    state = tmp_path / "state"
    module = _load_script()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("onboarding must not spawn git or another process")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    with pytest.raises(UnsupportedObjectFormat) as exc_info:
        module.trust_repository(repo, state)
    assert exc_info.value.details["object_format"] == object_format
    assert not baseline_path(state, repo).exists()


@pytest.mark.parametrize("object_format", [None, "sha1"])
def test_sha1_or_absent_format_writes_loadable_baseline(
    tmp_path: Path, object_format: str | None
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _raw_repo(repo, object_format)
    state = tmp_path / "state"
    report = _load_script().trust_repository(repo, state)
    assert report["object_format"] == "sha1"
    assert report["baseline"] == str(baseline_path(state, repo))
    assert load_baseline(state, repo).repository_key == report["repository_key"]


def test_cli_is_importable_and_prints_operator_report(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _raw_repo(repo, None)
    state = tmp_path / "state"
    module = _load_script()
    assert module.main([str(repo), "--state-root", str(state), "--confirm"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["baseline"] == str(baseline_path(state, repo))
    assert report["baseline_established"] is True
    assert [item["key"] for item in report["trusted_exec_assignments"]] == [
        "core.repositoryformatversion"
    ]


def _repo_and_state(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _raw_repo(repo, None)
    return repo, tmp_path / "state"


def test_cli_writes_nothing_without_confirmation(tmp_path: Path, capsys) -> None:
    """The decision must be reviewable before it is committed.

    Onboarding used to write the baseline and *then* print the assignments the
    operator was told to review, so the trust decision was already on disk by
    the time it could be questioned.
    """
    repo, state = _repo_and_state(tmp_path)
    module = _load_script()

    assert module.main([str(repo), "--state-root", str(state)]) == 3

    captured = capsys.readouterr()
    assert captured.out == ""
    preview = json.loads(captured.err[: captured.err.rindex("}") + 1])
    assert preview["baseline_established"] is False
    assert preview["trusted_exec_assignments"]
    assert not os.path.lexists(baseline_path(state, repo))


def test_cli_aborts_when_the_operator_declines(tmp_path: Path, monkeypatch) -> None:
    repo, state = _repo_and_state(tmp_path)
    module = _load_script()
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "no")

    assert module.main([str(repo), "--state-root", str(state)]) == 1
    assert not os.path.lexists(baseline_path(state, repo))


def test_cli_establishes_after_an_explicit_yes(tmp_path: Path, monkeypatch) -> None:
    repo, state = _repo_and_state(tmp_path)
    module = _load_script()
    monkeypatch.setattr(module.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "trust")

    assert module.main([str(repo), "--state-root", str(state)]) == 0
    assert load_baseline(state, repo).repository_key


def test_replace_is_gated_by_the_same_confirmation(tmp_path: Path) -> None:
    """--replace discards a baseline a human approved; it earns no shortcut."""
    repo, state = _repo_and_state(tmp_path)
    module = _load_script()
    assert module.main([str(repo), "--state-root", str(state), "--confirm"]) == 0
    before = baseline_path(state, repo).read_bytes()

    assert module.main([str(repo), "--state-root", str(state), "--replace"]) == 3

    assert baseline_path(state, repo).read_bytes() == before


_ROOT = Path(__file__).parents[2]


def test_the_documented_onboarding_command_actually_runs(tmp_path: Path) -> None:
    """The form printed in the docs must be executable as written.

    The script is committed non-executable, so any documented invocation that
    omits an interpreter dies with exit 126 in a clean checkout -- and the first
    thing an operator does with a new deployment is copy that line.
    """
    repo, state = _repo_and_state(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(repo), "--state-root", str(state), "--confirm"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["baseline_established"] is True


def test_no_document_invokes_the_script_without_an_interpreter() -> None:
    """Guards the exit-126 defect at its source rather than one line at a time."""
    sources = [
        _ROOT / "README.md",
        _ROOT / "docs" / "OPERATIONS.md",
        _ROOT / "scripts" / "gate" / "README.md",
        _ROOT / "src" / "sol_claude_dispatcher" / "evidence" / "gitadmin.py",
    ]
    offenders: list[str] = []
    for source in sources:
        if not source.exists():
            continue
        for number, line in enumerate(source.read_text().splitlines(), start=1):
            if "trust-repo-admin.py" not in line:
                continue
            before = line.split("trust-repo-admin.py")[0]
            if "python" not in before and "scripts/trust-repo-admin.py" in line:
                # a bare path invocation, not prose referring to the file
                if before.strip().endswith(("$", "#", "`", "")) and (
                    before.lstrip().startswith(("scripts/", "./scripts/", "`scripts/"))
                ):
                    offenders.append(f"{source.relative_to(_ROOT)}:{number}: {line.strip()}")
    assert offenders == [], "documented invocations missing an interpreter:\n" + "\n".join(offenders)
