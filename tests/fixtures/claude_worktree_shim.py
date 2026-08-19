#!/usr/bin/env python3
"""Worktree-creating shim in front of ``tests/fake_bin/claude`` (brief §32).

The real Claude CLI creates the isolated worktree itself when it is given
``--worktree <name>`` and then does its work inside it. ``tests/fake_bin/claude``
deliberately knows nothing about git, so the integration suite needs something
that reproduces *that one CLI behaviour* without going anywhere near a real
agent.

This shim does exactly two things and then gets out of the way:

1. if ``--worktree <name>`` is present, run
   ``git worktree add -b <name> <worktrees-root>/<name>`` from the current
   directory (which the dispatcher sets to the repository root on a first
   dispatch), and ``chdir`` into the new worktree;
2. ``exec`` ``tests/fake_bin/claude`` with the identical argv.

Everything else — modes, exit codes, logging, sleeping, malformed output — stays
in the fake binary, which remains the only worker binary any test executes. This
file never launches a real ``claude`` or ``codex`` process, never touches the
network, and only ever writes inside the temporary repository it is pointed at.

The worktrees root defaults to ``<repo-parent>/.sol-test-worktrees``, i.e.
outside the repository, so the primary tree stays clean. Override it with
``FAKE_CLAUDE_WORKTREE_ROOT``. Resolution back to a path is by final path
component (``git.worktree_path_for``), so the location is irrelevant to the
dispatcher.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

FAKE_CLAUDE = Path(__file__).resolve().parents[1] / "fake_bin" / "claude"


def _worktree_name(argv: list[str]) -> str | None:
    for i, token in enumerate(argv):
        if token in ("--worktree", "-w") and i + 1 < len(argv):
            return argv[i + 1]
    return None


def main(argv: list[str]) -> int:
    name = _worktree_name(argv)
    if name:
        repo = Path.cwd()
        root = Path(
            os.environ.get(
                "FAKE_CLAUDE_WORKTREE_ROOT", str(repo.parent / ".sol-test-worktrees")
            )
        )
        root.mkdir(parents=True, exist_ok=True)
        target = root / name
        if not target.exists():
            result = subprocess.run(
                ["git", "worktree", "add", "-b", name, str(target)],
                cwd=str(repo),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                sys.stderr.write(
                    "claude_worktree_shim: git worktree add failed: "
                    f"{result.stderr.strip()}\n"
                )
                return 70
        os.chdir(target)

    # Hand over to the fake binary with the identical argv. execv replaces this
    # process, so signal handling (SIGTERM/SIGKILL escalation) applies directly
    # to the fake, exactly as it would to a real CLI.
    os.execv(sys.executable, [sys.executable, str(FAKE_CLAUDE), *argv])
    return 0  # pragma: no cover - execv does not return


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
