from __future__ import annotations

import os
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import EvidenceFreezeViolated
from sol_claude_dispatcher.evidence.freeze import capture_evidence_freeze, verify_evidence_freeze


def test_freeze_verifies_every_file_record_and_detects_same_size_change(tmp_path: Path) -> None:
    root = tmp_path / "task"
    (root / "evidence").mkdir(parents=True)
    (root / "runs" / "001").mkdir(parents=True)
    (root / "evidence" / "diff.patch").write_bytes(b"AAAA")
    (root / "runs" / "001" / "path-inventory.json").write_bytes(b"{}")
    frozen = capture_evidence_freeze(
        root,
        (b"evidence/diff.patch", b"runs/001/path-inventory.json"),
    )
    assert tuple(entry.relpath for entry in frozen.entries) == (
        b"evidence/diff.patch",
        b"runs/001/path-inventory.json",
    )
    verify_evidence_freeze(root, frozen)

    (root / "evidence" / "diff.patch").write_bytes(b"BBBB")
    with pytest.raises(EvidenceFreezeViolated) as caught:
        verify_evidence_freeze(root, frozen)
    assert caught.value.details["changed_files"] == ["evidence/diff.patch"]


def test_freeze_refuses_missing_extra_and_symlink_substitution(tmp_path: Path) -> None:
    root = tmp_path / "task"
    root.mkdir()
    target = root / "a"
    target.write_bytes(b"a")
    frozen = capture_evidence_freeze(root, (b"a",))
    target.unlink()
    with pytest.raises(EvidenceFreezeViolated):
        verify_evidence_freeze(root, frozen)
    target.symlink_to("outside")
    with pytest.raises(EvidenceFreezeViolated):
        verify_evidence_freeze(root, frozen)


def test_freeze_paths_are_relative_and_cannot_escape_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="relative"):
        capture_evidence_freeze(tmp_path, (os.fsencode(tmp_path / "x"),))
    with pytest.raises(ValueError, match="parent"):
        capture_evidence_freeze(tmp_path, (b"../x",))
