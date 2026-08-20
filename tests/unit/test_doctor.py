"""Regression tests for ``scripts/doctor.sh`` (DEFECT-L2-01).

The doctor is a *gate*. A gate that reports PASS for a binary which exists but
cannot run is worse than no gate at all: commissioning goes green while the
dispatcher is physically incapable of launching a worker. That is exactly what
happened on the commissioning box — an unattended CLI auto-update left the
platform-native binary undownloaded, so ``claude --version`` exited 1 printing
"Error: claude native binary not installed." and the doctor printed::

    PASS  claude binary   /…/bin/claude (Error: claude native binary not installed.)

These tests exercise ``check_binary_version`` (which backs both the ``claude
binary`` and the ``codex binary`` checks) against stub binaries only. Nothing
here probes the machine's real toolchain, and nothing here runs the doctor's
other checks: ``doctor.sh`` is sourced, and sourcing it defines the functions
without executing a single probe.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

DOCTOR = Path(__file__).resolve().parents[2] / "scripts" / "doctor.sh"


def _stub(directory: Path, name: str, body: str) -> Path:
    """Write an executable stub binary and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body)
    path.chmod(0o755)
    return path


def _run_snippet(snippet: str, path_dir: Path) -> subprocess.CompletedProcess[str]:
    """Source doctor.sh in a fresh bash and run ``snippet`` against ``path_dir``."""
    return subprocess.run(
        ["bash", "-c", f'source "$1"\n{snippet}', "_", str(DOCTOR)],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{path_dir}:/usr/bin:/bin",
            "HOME": str(path_dir),
            # Guard against a hostile-looking inherited environment leaking in.
            "LC_ALL": "C",
        },
    )


@pytest.fixture
def stub_dir(tmp_path: Path) -> Path:
    return tmp_path / "bin"


def test_sourcing_doctor_runs_no_checks(stub_dir: Path) -> None:
    """The script must be inert when sourced — no probes, no output, no exit 1."""
    stub_dir.mkdir(parents=True)
    result = _run_snippet("true", stub_dir)

    assert result.returncode == 0
    assert result.stdout == ""


def test_broken_binary_that_exits_nonzero_fails_closed(stub_dir: Path) -> None:
    """The live failure: present, executable, and completely non-functional."""
    _stub(
        stub_dir,
        "clauded",
        "#!/bin/sh\n"
        "echo 'Error: claude native binary not installed.' >&2\n"
        "exit 1\n",
    )

    result = _run_snippet("check_binary_version clauded", stub_dir)

    assert result.returncode != 0, "a CLI that cannot report its version must FAIL"
    assert "--version failed (exit 1)" in result.stdout
    assert "claude native binary not installed" in result.stdout


def test_binary_printing_prose_with_exit_zero_fails_closed(stub_dir: Path) -> None:
    """Exit 0 is not enough: the output must actually look like a version."""
    _stub(stub_dir, "prosed", "#!/bin/sh\necho 'installed, probably'\nexit 0\n")

    result = _run_snippet("check_binary_version prosed", stub_dir)

    assert result.returncode != 0
    assert "no recognisable version" in result.stdout


def test_binary_producing_no_output_fails_closed(stub_dir: Path) -> None:
    """Silence is not a version either."""
    _stub(stub_dir, "muted", "#!/bin/sh\nexit 0\n")

    result = _run_snippet("check_binary_version muted", stub_dir)

    assert result.returncode != 0
    assert "no output" in result.stdout


def test_missing_binary_still_fails(stub_dir: Path) -> None:
    stub_dir.mkdir(parents=True)

    result = _run_snippet("check_binary_version definitely-not-installed", stub_dir)

    assert result.returncode != 0
    assert "not found on PATH" in result.stdout


def test_working_binary_passes_and_reports_the_actual_version(stub_dir: Path) -> None:
    """A healthy CLI passes, and the line carries the version that really ran.

    NOTE-L2-A: ``runner.CLI_CAPABILITIES`` is pinned to one CLI release while
    the machine can auto-update unattended. Printing the actual installed
    version is what makes that drift visible at the gate.
    """
    binary = _stub(
        stub_dir,
        "healthy",
        "#!/bin/sh\necho '2.1.237 (Claude Code)'\nexit 0\n",
    )

    result = _run_snippet("check_binary_version healthy", stub_dir)

    assert result.returncode == 0
    assert str(binary) in result.stdout
    assert "2.1.237" in result.stdout


def test_run_check_prints_FAIL_and_counts_a_broken_binary(stub_dir: Path) -> None:
    """End of the chain: a broken binary produces a FAIL line and a failure count.

    ``run_check`` decides PASS/FAIL purely from the check function's exit
    status, and the doctor exits non-zero when ``FAILURES`` is non-zero — so
    this is the whole gate semantics, minus the machine's real toolchain.
    """
    _stub(stub_dir, "clauded", "#!/bin/sh\necho 'Error: broken' >&2\nexit 1\n")

    result = _run_snippet(
        'run_check "claude binary" check_binary_version clauded\n'
        'printf "FAILURES=%s\\n" "$FAILURES"\n'
        '[[ "$FAILURES" -eq 0 ]] && exit 0 || exit 1\n',
        stub_dir,
    )

    assert result.stdout.startswith("FAIL  claude binary")
    assert "FAILURES=1" in result.stdout
    assert result.returncode == 1


def test_run_check_prints_PASS_for_a_healthy_binary(stub_dir: Path) -> None:
    """The PASS line format is unchanged for a CLI that really works."""
    _stub(stub_dir, "healthy", "#!/bin/sh\necho '2.1.237 (Claude Code)'\n")

    result = _run_snippet(
        'run_check "claude binary" check_binary_version healthy\n'
        'printf "FAILURES=%s\\n" "$FAILURES"\n',
        stub_dir,
    )

    assert result.stdout.startswith("PASS  claude binary")
    assert "2.1.237" in result.stdout
    assert "FAILURES=0" in result.stdout


def test_doctor_never_writes_to_the_repository(stub_dir: Path) -> None:
    """Read-only discipline: sourcing and probing must not create anything."""
    stub_dir.mkdir(parents=True)
    before = sorted(os.listdir(DOCTOR.parent))

    _run_snippet("check_binary_version definitely-not-installed", stub_dir)

    assert sorted(os.listdir(DOCTOR.parent)) == before
