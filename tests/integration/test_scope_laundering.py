"""End-to-end controls for Gate 7 scope laundering across lifecycle phases."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sol_claude_dispatcher.models import TaskState


def _scope_evidence(dispatcher, task_id: str) -> dict:
    raw = dispatcher.store.read_evidence(task_id, "scope-verdicts.json")
    assert raw is not None
    return json.loads(raw)


async def test_prior_forbidden_worker_path_cannot_vanish_on_clean_resume(
    dispatcher, request_payload, fake_env, monkeypatch
):
    """Run 2's empty delta cannot launder run 1's surviving policy breach."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", ".github/workflows/pwn.yml")
    first = await dispatcher.dispatch_claude_task(request_payload)

    assert first["status"] == TaskState.POLICY_VIOLATION.value
    assert first["scope"]["verdicts"]["run_worker"]["valid"] is False

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    resumed = await dispatcher.resume_claude_task(
        first["task_id"], "Report without changing any files."
    )

    assert resumed["status"] == TaskState.POLICY_VIOLATION.value, resumed
    verdicts = resumed["scope"]["verdicts"]
    assert verdicts["run_worker"]["valid"] is True
    assert verdicts["run_worker"]["forbidden_hits"] == []
    assert verdicts["inputs"]["run_worker"]["changes"] == []
    assert verdicts["cumulative_worker"]["valid"] is False
    assert [
        item["display"]
        for item in verdicts["cumulative_worker"]["forbidden_hits"]
    ] == [".github/workflows/pwn.yml"]
    assert [
        item["path"]["display"]
        for item in verdicts["inputs"]["cumulative_worker"]["changes"]
        if item["new_kind"] != "directory"
    ] == [".github/workflows/pwn.yml"]
    assert resumed["scope"]["forbidden"] == [".github/workflows/pwn.yml"]

    persisted = _scope_evidence(dispatcher, first["task_id"])
    assert persisted == verdicts
    run_evidence = json.loads(
        (
            Path(dispatcher.store.run_dir(first["task_id"], 2))
            / "scope-verdicts.json"
        ).read_text()
    )
    assert run_evidence == verdicts


async def test_validation_forbidden_path_blocks_without_worker_scope_laundering(
    dispatcher, request_payload, fake_env, monkeypatch, tmp_path
):
    """Allowed validator output is neutral; its forbidden output still blocks."""
    validator = tmp_path / "validator_writes_outputs.py"
    validator.write_text(
        "from pathlib import Path\n"
        "cwd = Path.cwd()\n"
        '(cwd / "docs").mkdir(exist_ok=True)\n'
        '(cwd / "docs" / "coverage.xml").write_text("<coverage/>\\n")\n'
        '(cwd / ".github" / "workflows").mkdir(parents=True, exist_ok=True)\n'
        '(cwd / ".github" / "workflows" / "pwn.yml").write_text("forbidden\\n")\n'
    )
    request_payload["validation"] = {
        "commands": [{"argv": [sys.executable, str(validator)]}]
    }
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", "src/deploy/deploy.py")

    result = await dispatcher.dispatch_claude_task(request_payload)

    assert result["status"] == TaskState.POLICY_VIOLATION.value, result
    verdicts = result["scope"]["verdicts"]
    assert verdicts["run_worker"]["valid"] is True
    assert verdicts["cumulative_worker"]["valid"] is True
    assert verdicts["validation"]["outside_allowed"] == []
    assert [
        item["display"] for item in verdicts["validation"]["forbidden_hits"]
    ] == [".github/workflows/pwn.yml"]
    assert verdicts["validation_attributed_forbidden"] == [
        ".github/workflows/pwn.yml"
    ]
    assert result["scope"]["out_of_scope"] == []
    run_inputs = {
        item["path"]["display"]
        for item in verdicts["inputs"]["run_worker"]["changes"]
    }
    validation_inputs = {
        item["path"]["display"]
        for item in verdicts["inputs"]["validation"]["changes"]
    }
    assert run_inputs == {"src/deploy/deploy.py"}
    assert {"docs/coverage.xml", ".github/workflows/pwn.yml"} <= validation_inputs

    attribution = result["evidence_attribution"]
    assert attribution["worker_changed_paths"] == ["src/deploy/deploy.py"]
    assert "docs/coverage.xml" in attribution["validation_added_paths"]
    assert ".github/workflows/pwn.yml" in attribution["validation_added_paths"]
    assert result["last_error"]["details"]["scope_verdicts"] == verdicts
    assert "Validation changed caller-forbidden paths" in result["last_error"]["message"]
    violations = dispatcher.store.load(result["task_id"]).policy_violations
    assert "forbidden_validation:.github/workflows/pwn.yml" in violations
    assert "out_of_scope:docs/coverage.xml" not in violations


async def test_prior_validation_output_is_not_laundered_into_worker_scope_on_resume(
    dispatcher, request_payload, fake_env, monkeypatch, tmp_path
):
    """A validator-owned file remains validator-owned across a no-op resume."""
    validator = tmp_path / "validator_writes_coverage.py"
    validator.write_text(
        "from pathlib import Path\n"
        "target = Path.cwd() / 'docs' / 'coverage.xml'\n"
        "target.parent.mkdir(exist_ok=True)\n"
        "target.write_text('<coverage/>\\n')\n"
    )
    request_payload["validation"] = {
        "commands": [{"argv": [sys.executable, str(validator)]}]
    }
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")

    first = await dispatcher.dispatch_claude_task(request_payload)

    assert first["status"] == TaskState.AWAITING_SOL_REVIEW.value, first
    first_verdicts = first["scope"]["verdicts"]
    assert first_verdicts["run_worker"]["valid"] is True
    assert first_verdicts["inputs"]["run_worker"]["changes"] == []
    assert first_verdicts["cumulative_worker"]["valid"] is True
    assert first_verdicts["inputs"]["cumulative_worker"]["changes"] == []
    assert {
        item["path"]["display"]
        for item in first_verdicts["inputs"]["validation"]["changes"]
    } == {"docs", "docs/coverage.xml"}

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    resumed = await dispatcher.resume_claude_task(
        first["task_id"], "Report without changing any files."
    )

    assert resumed["status"] == TaskState.AWAITING_SOL_REVIEW.value, resumed
    verdicts = resumed["scope"]["verdicts"]
    assert verdicts["run_worker"]["valid"] is True
    assert verdicts["inputs"]["run_worker"]["changes"] == []
    assert verdicts["cumulative_worker"]["valid"] is True
    assert verdicts["cumulative_worker"]["outside_allowed"] == []
    assert verdicts["cumulative_worker"]["forbidden_hits"] == []
    assert verdicts["inputs"]["cumulative_worker"]["changes"] == []
    assert resumed["scope"]["out_of_scope"] == []
    assert resumed["scope"]["forbidden"] == []
    assert dispatcher.store.load(first["task_id"]).policy_violations == []


async def test_malformed_prior_cumulative_scope_history_refuses_resume(
    dispatcher, request_payload, fake_env, monkeypatch
):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")
    first = await dispatcher.dispatch_claude_task(request_payload)
    assert first["status"] == TaskState.AWAITING_SOL_REVIEW.value, first

    evidence = _scope_evidence(dispatcher, first["task_id"])
    evidence["inputs"]["cumulative_worker"]["digest"] = "0" * 64
    dispatcher.store.write_evidence(
        first["task_id"], "scope-verdicts.json", json.dumps(evidence)
    )

    monkeypatch.setenv("FAKE_CLAUDE_MODE", "resume")
    refused = await dispatcher.resume_claude_task(
        first["task_id"], "Report without changing any files."
    )

    assert refused["error"] == "StateCorruption"
    assert refused["message"] == (
        "The prior cumulative worker scope history is malformed."
    )
