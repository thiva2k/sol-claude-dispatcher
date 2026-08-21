#!/usr/bin/env python3
"""Read-only activation-state check for a deployed dispatcher.

This is the operational replacement for the commissioning tripwires that used
to live in the ordinary test suite. Those tests asserted
``skills.enabled is False`` against ``config/dispatcher.toml`` — a gitignored,
host-local file — which made repository correctness depend on whether the
machine running the suite happened to be activated. A clone, a recovery
environment, a dev host and the activated production host are all legitimate,
and they do not agree on that flag.

So the check moved here, where it belongs, and it became explicit:

    scripts/check-production-activation.py --expect inert
    scripts/check-production-activation.py --expect active

``--expect`` is REQUIRED and has no default. This tool never infers what the
state ought to be, and it deliberately offers no environment variable for
choosing the expectation: an operator states the state they believe the host is
in, and the checker either confirms it or exits non-zero. Guessing the
expectation would make the check unfalsifiable.

It is strictly READ-ONLY. It opens files for reading, loads them through the
real dispatcher loaders, and writes nothing anywhere — no manifest repair, no
config rewrite, no state directory, no log file. A checker that could "fix"
drift would defeat its own purpose.

Exit codes:
    0  every check passed; the host is in the expected state
    1  at least one check failed (state mismatch, or a broken invariant)
    2  the configuration or manifest could not be loaded at all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from sol_claude_dispatcher.config import (  # noqa: E402
    DISPATCHER_AUTHORED_RESERVE_BYTES,
    MAX_APPEND_SYSTEM_PROMPT_BYTES,
    Config,
    load_config,
)
from sol_claude_dispatcher.errors import DispatcherError  # noqa: E402
from sol_claude_dispatcher.project_guidance import (  # noqa: E402
    APPROVED_STATE,
    load_manifest,
)
from sol_claude_dispatcher.server import resolve_config_path  # noqa: E402

#: The one repository this production deployment is authorised for. Kept as a
#: default rather than a hard constant so the checker's own tests can point it
#: at a temporary repository; it is still stated explicitly on the command
#: line, never inferred from whatever the config happens to contain.
DEFAULT_EXPECTED_ROOT = "/home/dev/full-voice-agent"

ACTIVE = "active"
INERT = "inert"


class Check:
    """One named invariant and its outcome."""

    __slots__ = ("name", "ok", "detail")

    def __init__(self, name: str, ok: bool, detail: str) -> None:
        self.name = name
        self.ok = bool(ok)
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def _shared_invariants(config: Config, expected_root: str) -> list[Check]:
    """Invariants that must hold whether the host is active or inert.

    None of these describe deployment state. They describe the policy the
    deployment is running under, which activation does not change.
    """
    checks: list[Check] = []

    roots = list(config.security.allowed_repository_roots)
    checks.append(
        Check(
            "allowed repository root",
            roots == [expected_root],
            f"expected exactly [{expected_root!r}], got {roots!r}",
        )
    )

    checks.append(
        Check(
            "skills.mode is projected",
            config.skills.mode == "projected",
            f"skills.mode={config.skills.mode!r}",
        )
    )
    checks.append(
        Check(
            "project_guidance.mode is projected",
            config.project_guidance.mode == "projected",
            f"project_guidance.mode={config.project_guidance.mode!r}",
        )
    )

    checks.append(
        Check(
            "skills.fail_on_drift",
            config.skills.fail_on_drift is True,
            f"skills.fail_on_drift={config.skills.fail_on_drift!r}",
        )
    )
    checks.append(
        Check(
            "project_guidance.fail_on_drift",
            config.project_guidance.fail_on_drift is True,
            f"project_guidance.fail_on_drift={config.project_guidance.fail_on_drift!r}",
        )
    )

    composed = (
        config.skills.max_projected_bytes
        + config.project_guidance.max_projected_bytes
        + DISPATCHER_AUTHORED_RESERVE_BYTES
    )
    checks.append(
        Check(
            "B1 composed ceiling",
            composed <= MAX_APPEND_SYSTEM_PROMPT_BYTES,
            f"{composed} <= {MAX_APPEND_SYSTEM_PROMPT_BYTES} "
            f"(skills {config.skills.max_projected_bytes} + guidance "
            f"{config.project_guidance.max_projected_bytes} + reserve "
            f"{DISPATCHER_AUTHORED_RESERVE_BYTES})",
        )
    )

    return checks


def _active_invariants(config: Config) -> list[Check]:
    """What must be true for this host to be genuinely, safely activated."""
    checks = [
        Check(
            "skills.enabled",
            config.skills.enabled is True,
            f"skills.enabled={config.skills.enabled!r}, expected True",
        ),
        Check(
            "project_guidance.enabled",
            config.project_guidance.enabled is True,
            f"project_guidance.enabled={config.project_guidance.enabled!r}, expected True",
        ),
    ]

    # An activated host whose guidance manifest is not approved would enable a
    # projection path that then refuses every task. Catch it here, not at
    # dispatch time.
    manifest_path = config.approved_guidance_file
    try:
        manifest = load_manifest(manifest_path)
    except DispatcherError as exc:
        checks.append(
            Check(
                "guidance manifest loads",
                False,
                f"{manifest_path}: {exc}",
            )
        )
        return checks

    checks.append(
        Check(
            "guidance manifest approval.state",
            manifest.approval.state == APPROVED_STATE,
            f"approval.state={manifest.approval.state!r}, expected {APPROVED_STATE!r} "
            f"({manifest_path})",
        )
    )
    return checks


def _inert_invariants(config: Config) -> list[Check]:
    """What must be true for this host to be genuinely switched off."""
    return [
        Check(
            "skills.enabled",
            config.skills.enabled is False,
            f"skills.enabled={config.skills.enabled!r}, expected False",
        ),
        Check(
            "project_guidance.enabled",
            config.project_guidance.enabled is False,
            f"project_guidance.enabled={config.project_guidance.enabled!r}, expected False",
        ),
    ]


_STATE_INVARIANTS: dict[str, Callable[[Config], list[Check]]] = {
    ACTIVE: _active_invariants,
    INERT: _inert_invariants,
}


def run_checks(config: Config, expect: str, expected_root: str) -> list[Check]:
    """Evaluate every invariant for ``expect``. Pure; touches no filesystem
    except reading the guidance manifest the config points at."""
    if expect not in _STATE_INVARIANTS:
        raise ValueError(f"unknown expected state {expect!r}")
    return _shared_invariants(config, expected_root) + _STATE_INVARIANTS[expect](config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check-production-activation.py",
        description=(
            "Verify a deployed dispatcher is in an explicitly stated activation "
            "state. Read-only: nothing is modified."
        ),
    )
    parser.add_argument(
        "--expect",
        required=True,
        choices=(ACTIVE, INERT),
        help=(
            "The state you assert this host is in. REQUIRED and never inferred: "
            "'active' means both projections on and the guidance manifest "
            "APPROVED; 'inert' means both projections off."
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Dispatcher config to check. Defaults to the same path the running "
            "dispatcher resolves."
        ),
    )
    parser.add_argument(
        "--expect-root",
        default=DEFAULT_EXPECTED_ROOT,
        help=f"The single authorised repository root (default: {DEFAULT_EXPECTED_ROOT}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Emit a machine-readable report instead of the text table.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    config_path = Path(args.config) if args.config else resolve_config_path()

    try:
        config = load_config(config_path)
    except DispatcherError as exc:
        # A config that cannot load is not "inert" and not "active" — it is
        # broken, and that is a distinct exit code. Invalid B1 caps land here,
        # refused by the normal loader rather than by a duplicate check.
        payload = {
            "expected_state": args.expect,
            "config": str(config_path),
            "loaded": False,
            "error": str(exc),
            "details": getattr(exc, "details", None),
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(f"config:   {config_path}")
            print(f"expected: {args.expect}")
            print()
            print(f"FAIL  configuration did not load: {exc}")
            details = getattr(exc, "details", None)
            if details:
                print(f"      {details}")
        return 2

    checks = run_checks(config, args.expect, args.expect_root)
    failed = [c for c in checks if not c.ok]

    if args.as_json:
        print(
            json.dumps(
                {
                    "expected_state": args.expect,
                    "config": str(config_path),
                    "loaded": True,
                    "ok": not failed,
                    "checks": [c.as_dict() for c in checks],
                },
                indent=2,
                default=str,
            )
        )
    else:
        print(f"config:   {config_path}")
        print(f"expected: {args.expect}")
        print()
        for check in checks:
            print(f"{'PASS' if check.ok else 'FAIL'}  {check.name:<38} {check.detail}")
        print()
        if failed:
            print(
                f"{len(failed)} of {len(checks)} check(s) FAILED — this host is not "
                f"in the '{args.expect}' state."
            )
        else:
            print(f"All {len(checks)} check(s) passed — host is '{args.expect}'.")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
