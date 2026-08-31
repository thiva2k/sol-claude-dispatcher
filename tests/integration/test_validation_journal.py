"""Gate 7 controls for the non-authority validation execution journal."""

from __future__ import annotations

import hashlib
import json
import shutil

import pytest

from sol_claude_dispatcher.models import ValidationCommand
from sol_claude_dispatcher.validation import run_validation_command


async def test_the_two_journals_are_disjoint(
    git_repo, tmp_path
):
    """A legal Git validation stays out of the authority-domain journal."""

    git_binary = shutil.which("git")
    if git_binary is None:
        pytest.skip("git is not installed")
    argv = [git_binary, "diff", "--exit-code"]
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    git_journal = run_dir / "git-invocations.jsonl"
    authority_hash = hashlib.sha256(b"authority-domain-control").hexdigest()
    git_journal.write_text(
        json.dumps(
            {
                "event": "git",
                "authority": True,
                "argv_sha256": authority_hash,
            }
        )
        + "\n"
    )
    authority_journal_before = git_journal.read_bytes()

    result = await run_validation_command(
        ValidationCommand(argv=argv, timeout_seconds=30),
        git_repo,
        journal_path=run_dir / "validation-invocations.jsonl",
    )

    assert result.exit_code is not None
    validation_rows = [
        json.loads(line)
        for line in (run_dir / "validation-invocations.jsonl").read_text().splitlines()
    ]
    git_rows = [
        json.loads(line)
        for line in git_journal.read_text().splitlines()
    ]

    validation_hash = hashlib.sha256(
        json.dumps(argv, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    assert validation_hash in {row["argv_sha256"] for row in validation_rows}
    assert validation_hash not in {row.get("argv_sha256") for row in git_rows}
    assert {
        row["argv_sha256"] for row in validation_rows
    }.isdisjoint({row.get("argv_sha256") for row in git_rows})
    assert all(row["authority"] is False for row in validation_rows)
    assert all(row["is_git"] is True for row in validation_rows)
    assert all(row["program"] == "git" for row in validation_rows)
    assert git_journal.read_bytes() == authority_journal_before
