"""``scripts/generate-codex-config.sh`` must never regenerate 3,900 s (GATE 6).

The script used to print ``max_timeout_seconds + 300``. On a 3,600 s ceiling
that is 3,900 s, which was the value actually installed in
``~/.codex/config.toml`` before Lane K corrected it. Lane K's measurement of
what one blocking dispatch call really costs:

    3,625 s worker (3,600 clamp + 5 SIGTERM + 10 SIGKILL reap + 10 pipe drain)
  + 3,920 s validation (governed aggregate + 32 per-command tails)
  + 1,440 s evidence (23 git calls at 60 s, budgeted 24)
  +    60 s MCP transport
  = 9,045 s required

3,900 s covered the worker phase and 275 s of *nothing else*: a max-length
worker followed by any real validation would have had its MCP waiter cancelled
mid-validation. The margin was not small — it was the wrong shape.

These tests exist so that a future edit which reintroduces the ``+300`` shape
FAILS here rather than silently regenerating a dangerous config.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from sol_claude_dispatcher.config import (
    TRANSPORT_TOOL_TIMEOUT_SECONDS,
    load_config,
    required_tool_timeout_seconds,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "scripts" / "generate-codex-config.sh"
VENV_PY = PROJECT_ROOT / ".venv" / "bin" / "python"


def _run(config_path: Path | None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if config_path is not None:
        env["SOL_DISPATCHER_CONFIG"] = str(config_path)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


@pytest.fixture
def generated(config_file: Path) -> str:
    result = _run(config_file)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _emitted_timeout(text: str) -> int:
    match = re.search(r"^tool_timeout_sec\s*=\s*([0-9]+)", text, re.MULTILINE)
    assert match, f"no tool_timeout_sec in:\n{text}"
    return int(match.group(1))


# ---------------------------------------------------------------------------
# The stale formula must be gone from the script and from its output
# ---------------------------------------------------------------------------


def _executable_lines(source: str) -> str:
    """The script with its comments stripped.

    The banner deliberately *quotes* the old formula to explain why it is gone;
    what must never come back is the arithmetic itself.
    """
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )


def test_the_script_no_longer_contains_the_plus_300_margin():
    code = _executable_lines(SCRIPT.read_text())
    assert "MARGIN_SECONDS" not in code
    assert not re.search(r"\+\s*300\b", code)
    assert not re.search(r"MAX_TIMEOUT\w*\s*\+", code)
    assert not re.search(r"max_timeout_seconds\s*\+", code)


def test_the_script_never_emits_the_stale_3900(generated: str, config_file: Path):
    cfg = load_config(config_file)
    stale = cfg.dispatcher.max_timeout_seconds + 300
    assert stale == 3_900
    assert _emitted_timeout(generated) != stale
    assert "3900" not in generated


def test_the_emitted_timeout_is_the_applied_transport_timeout(generated: str):
    assert _emitted_timeout(generated) == TRANSPORT_TOOL_TIMEOUT_SECONDS == 10_800


def test_the_emitted_timeout_covers_the_derived_requirement(
    generated: str, config_file: Path
):
    required = required_tool_timeout_seconds(load_config(config_file))
    assert _emitted_timeout(generated) >= required


def test_the_output_shows_the_arithmetic_that_produced_the_number(generated: str):
    """A reader must be able to check the number without reading the script."""
    for component in ("worker", "validation", "evidence", "transport"):
        assert component in generated.lower()
    # every component of the derivation is stated as a number
    for number in ("25", "1440", "60", "10800"):
        assert number in generated


def test_the_output_names_the_config_it_derived_from(generated: str, config_file: Path):
    assert str(config_file) in generated


# ---------------------------------------------------------------------------
# It fails closed rather than guessing
# ---------------------------------------------------------------------------


def test_it_refuses_rather_than_guessing_when_the_config_is_missing(tmp_path: Path):
    result = _run(tmp_path / "does-not-exist.toml")
    assert result.returncode != 0
    assert "tool_timeout_sec" not in result.stdout
    assert "mcp_servers" not in result.stdout


def test_it_refuses_rather_than_guessing_when_the_config_is_invalid(tmp_path: Path):
    bad = tmp_path / "bad.toml"
    bad.write_text("[dispatcher]\nmax_timeout_seconds = 3600\n")
    result = _run(bad)
    assert result.returncode != 0
    assert "tool_timeout_sec" not in result.stdout


def test_a_config_whose_budget_exceeds_the_transport_cannot_be_generated(
    tmp_path: Path, git_repo: Path
):
    """The load-time ceiling is what stops it — the script does not clamp."""
    over = tmp_path / "over.toml"
    over.write_text(
        f"""
[dispatcher]
state_dir = "./state"
max_timeout_seconds = 3600

[models]
sonnet = "sonnet"
opus = "opus"
fable = "fable"

[routing]
default_model = "sonnet"

[security]
allowed_repository_roots = ["{git_repo}"]

[validation]
run_dispatcher_validation = true
max_total_seconds = 100000
"""
    )
    result = _run(over)
    assert result.returncode != 0
    assert "tool_timeout_sec" not in result.stdout


# ---------------------------------------------------------------------------
# Everything else about the snippet is unchanged
# ---------------------------------------------------------------------------


def test_the_snippet_still_declares_exactly_the_four_tools(generated: str):
    for tool in (
        "dispatch_claude_task",
        "resume_claude_task",
        "review_task_with_fable",
        "get_task",
    ):
        assert f'"{tool}"' in generated
    assert generated.count('"') >= 8
    for absent in ("watch_task", "wait_for_task", "subscribe"):
        assert absent not in generated


def test_the_script_is_still_print_only():
    source = SCRIPT.read_text()
    assert "DO NOT APPLY AUTOMATICALLY" in source
    # No copy/move/delete, and no redirection into a file anywhere in the body.
    assert not re.search(r"^\s*(cp|mv|rm|install|tee)\s", source, re.MULTILINE)
    assert not re.search(r">>?\s*[\"']?(~|\$HOME)", source)
