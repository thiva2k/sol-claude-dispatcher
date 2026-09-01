#!/usr/bin/env python3
"""Establish a reviewed repository-administration baseline for Gate 7.

This is an operator command, never a dispatch-path helper.  It performs raw
filesystem parsing only and intentionally spawns no Git process.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

try:
    from sol_claude_dispatcher.errors import DispatcherError
    from sol_claude_dispatcher.evidence.gitadmin import (
        baseline_path,
        capture_repository_administration,
        read_repository_object_format,
        write_baseline,
    )
except ModuleNotFoundError:  # direct execution from a source checkout
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "src"))
    from sol_claude_dispatcher.errors import DispatcherError
    from sol_claude_dispatcher.evidence.gitadmin import (
        baseline_path,
        capture_repository_administration,
        read_repository_object_format,
        write_baseline,
    )


def preview_repository(
    repository: str | Path,
    state_root: str | Path,
) -> tuple[dict[str, Any], Any]:
    """Capture what trusting this repository *would* mean. Writes nothing.

    Phase one of onboarding. The operator cannot review
    ``trusted_exec_assignments`` before the decision is committed unless the
    capture and the write are separable, so they are.
    """

    # Load-bearing order: format refusal precedes the object walk and baseline
    # writer.  A SHA-256 repository therefore gets its actual cause once rather
    # than a misleading 2/38 loose-path error.
    object_format = read_repository_object_format(repository)
    snapshot = capture_repository_administration(repository, validate_all_loose=True)
    target = baseline_path(state_root, snapshot.canonical_root)
    report = {
        "repository": snapshot.canonical_root,
        "repository_key": snapshot.repository_key,
        "object_format": object_format,
        "baseline": str(target),
        "baseline_established": False,
        "baseline_path_exists": os.path.lexists(target),
        "loose_objects_validated": len(snapshot.validated_loose_paths),
        "trusted_exec_assignments": [item.to_dict() for item in snapshot.exec_assignments],
        "note": (
            "NOTHING HAS BEEN WRITTEN YET. Every execution and transport "
            "assignment listed above becomes permanently trusted in this "
            "repository once you confirm."
        ),
    }
    return report, snapshot


def establish_baseline(
    state_root: str | Path,
    snapshot: Any,
    *,
    replace: bool = False,
) -> Path:
    """Phase two: commit the reviewed capture. Only reached after confirmation."""

    return write_baseline(state_root, snapshot, replace=replace)


def trust_repository(
    repository: str | Path,
    state_root: str | Path,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    """Capture and establish in one call, with no confirmation step.

    For programmatic callers that are themselves asserting the review happened.
    The CLI deliberately does not use this: an operator gets
    :func:`preview_repository`, a confirmation, and only then
    :func:`establish_baseline`.
    """

    report, snapshot = preview_repository(repository, state_root)
    baseline = establish_baseline(state_root, snapshot, replace=replace)
    report["baseline"] = str(baseline)
    report["baseline_established"] = True
    # preview-only: beside baseline_established=True it reads as a
    # contradiction in the operator's record.
    report.pop("baseline_path_exists", None)
    report["note"] = (
        "This operator baseline is not updated by dispatch or reconciliation. "
        "Review every trusted execution/transport assignment printed above."
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Establish the Gate 7 raw Git-administration baseline."
    )
    parser.add_argument("repository", help="absolute repository working-tree root")
    parser.add_argument(
        "--state-root",
        required=True,
        help="dispatcher state root containing the repos/ directory",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="explicitly replace an existing baseline after operator review",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "establish the baseline without an interactive prompt, asserting "
            "that the trusted execution assignments have already been reviewed"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Preview, confirm, then establish -- in that order, or not at all.

    Trusting a repository's administrative state is the one decision this tool
    makes, and it used to be committed to disk before the operator could see
    what they were trusting. Now nothing is written until the assignments have
    been shown and the decision has been taken explicitly. Every path that does
    not reach that confirmation leaves no baseline behind.
    """

    args = _parser().parse_args(argv)
    try:
        report, snapshot = preview_repository(args.repository, args.state_root)
    except DispatcherError as exc:
        sys.stderr.write(json.dumps(exc.to_payload(), sort_keys=True) + "\n")
        return 2

    if not args.confirm:
        # The preview goes to stderr so that stdout carries exactly one
        # document -- the established baseline -- or nothing at all.
        sys.stderr.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        if not sys.stdin.isatty():
            sys.stderr.write(
                "Refusing to establish a baseline without confirmation. Review "
                "the trusted execution and transport assignments above, then "
                "re-run with --confirm. Nothing was written.\n"
            )
            return 3
        try:
            reply = input("Type 'trust' to establish this baseline: ")
        except (EOFError, KeyboardInterrupt):
            sys.stderr.write("\nAborted. Nothing was written.\n")
            return 1
        if reply.strip() != "trust":
            sys.stderr.write("Aborted. Nothing was written.\n")
            return 1

    try:
        baseline = establish_baseline(args.state_root, snapshot, replace=args.replace)
    except DispatcherError as exc:
        sys.stderr.write(json.dumps(exc.to_payload(), sort_keys=True) + "\n")
        return 2

    report["baseline"] = str(baseline)
    report["baseline_established"] = True
    # preview-only: beside baseline_established=True it reads as a
    # contradiction in the operator's record.
    report.pop("baseline_path_exists", None)
    report["note"] = (
        "This operator baseline is not updated by dispatch or reconciliation. "
        "Any commit, fetch or git gc in this repository will require a "
        "reviewed --replace before the next dispatch."
    )
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
