#!/usr/bin/env python3
"""Establish a reviewed repository-administration baseline for Gate 7.

This is an operator command, never a dispatch-path helper.  It performs raw
filesystem parsing only and intentionally spawns no Git process.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

try:
    from sol_claude_dispatcher.errors import DispatcherError
    from sol_claude_dispatcher.evidence.gitadmin import (
        capture_repository_administration,
        read_repository_object_format,
        write_baseline,
    )
except ModuleNotFoundError:  # direct execution from a source checkout
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "src"))
    from sol_claude_dispatcher.errors import DispatcherError
    from sol_claude_dispatcher.evidence.gitadmin import (
        capture_repository_administration,
        read_repository_object_format,
        write_baseline,
    )


def trust_repository(
    repository: str | Path,
    state_root: str | Path,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    """Validate and atomically establish one operator baseline."""

    # Load-bearing order: format refusal precedes the object walk and baseline
    # writer.  A SHA-256 repository therefore gets its actual cause once rather
    # than a misleading 2/38 loose-path error.
    object_format = read_repository_object_format(repository)
    snapshot = capture_repository_administration(repository, validate_all_loose=True)
    baseline = write_baseline(state_root, snapshot, replace=replace)
    return {
        "repository": snapshot.canonical_root,
        "repository_key": snapshot.repository_key,
        "object_format": object_format,
        "baseline": str(baseline),
        "loose_objects_validated": len(snapshot.validated_loose_paths),
        "trusted_exec_assignments": [item.to_dict() for item in snapshot.exec_assignments],
        "note": (
            "This operator baseline is not updated by dispatch or reconciliation. "
            "Review every trusted execution/transport assignment printed above."
        ),
    }


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = trust_repository(args.repository, args.state_root, replace=args.replace)
    except DispatcherError as exc:
        sys.stderr.write(json.dumps(exc.to_payload(), sort_keys=True) + "\n")
        return 2
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
