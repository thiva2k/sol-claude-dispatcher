"""Gate 7 operator onboarding command tests."""

from __future__ import annotations

import importlib.util
import json
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
    assert module.main([str(repo), "--state-root", str(state)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["baseline"] == str(baseline_path(state, repo))
    assert [item["key"] for item in report["trusted_exec_assignments"]] == [
        "core.repositoryformatversion"
    ]
