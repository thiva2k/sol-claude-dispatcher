#!/usr/bin/env bash
# audit-approved-skills.sh — read-only drift report for approved skills (§10).
#
# Wraps skills.SkillProjectionEngine.audit(): re-reads and re-hashes every
# approved-skill file on disk (SKILL.md plus supporting files) and reports
# MATCH / DRIFT / MISSING per manifest entry, against the *effective* deny
# list the worker is actually invoked with (config plus the runner's
# non-configurable core deny set — see runner.ALWAYS_DISALLOWED_TOOLS).
#
# What this script never does: approve anything, write anything, modify the
# manifest, or touch a skill file. It is a probe, not a repair tool.
#
# Exit status: 0 only when every approved skill is an exact MATCH. 1 on ANY
# DRIFT or MISSING row, and 1 if the config or manifest fails to load at all.
#
# FAILS CLOSED (see scripts/doctor.sh's check_binary_version for the defect
# this deliberately avoids): the audit's own exit status is what this script
# exits with. The final command is `exec`'d, so nothing here can wrap it in
# `|| true` or an `if` that discards a non-zero status — there is no shell
# frame left to swallow it. A config that will not parse, a manifest that
# will not load, or a drifted/missing skill are all reported as a failure,
# never silently accepted as a pass.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
VENV_PY="${PROJECT_ROOT}/.venv/bin/python"
CONFIG_PATH="${1:-${PROJECT_ROOT}/config/dispatcher.toml}"

if [[ ! -x "$VENV_PY" ]]; then
    echo "FAIL  venv python not found at ${VENV_PY} — run: python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'" >&2
    exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "FAIL  config not found: ${CONFIG_PATH}" >&2
    exit 1
fi

echo "sol-claude-dispatcher approved-skills audit — read-only, nothing is modified"
echo "config: ${CONFIG_PATH}"
echo

exec "$VENV_PY" -c "
import sys

from sol_claude_dispatcher.config import load_config
from sol_claude_dispatcher.runner import ALWAYS_DISALLOWED_TOOLS
from sol_claude_dispatcher.skills import SkillProjectionEngine

config_path = sys.argv[1]

# Any exception here (unparseable TOML, invalid config, missing or invalid
# manifest) is deliberately left to propagate: an uncaught exception exits
# python non-zero, which is exactly the fail-closed behaviour this script
# promises. No try/except here that would turn a broken config into a PASS.
config = load_config(config_path)

# The *effective* deny list, per LANE-A-INTEGRATION-REQUESTS.md R1: config
# plus the runner's non-configurable core set. Two approved skills declare
# requires_deny_patterns and the engine refuses to project them if the
# pattern is absent — auditing against config alone would miss that a
# required pattern is only present because of the non-configurable core set.
engine = SkillProjectionEngine.from_config(
    config,
    denied_tools=[*config.claude.disallowed_tools, *ALWAYS_DISALLOWED_TOOLS],
)

rows = engine.audit()
if not rows:
    print('no approved skills in manifest')
    sys.exit(0)

drifted = 0
for row in rows:
    # approved_version is None for every agent-skills entry — that plugin
    # publishes no version string anywhere upstream (§10 note). Print that
    # honestly rather than inventing a version.
    version = row.approved_version if row.approved_version is not None else 'n/a (absent upstream)'
    current = row.current_sha256 if row.current_sha256 is not None else '-'
    print(f'{row.status:<7} {row.skill_id:<48} plugin={row.plugin} version={version}')
    print(f'        approved_path={row.approved_path}')
    print(f'        approved_sha256={row.approved_sha256}')
    print(f'        current_sha256={current}')
    if row.detail:
        print(f'        detail={row.detail}')
    if row.status != 'MATCH':
        drifted += 1

print()
if drifted:
    print(f'{drifted} of {len(rows)} approved skill(s) DRIFTED or MISSING.')
    sys.exit(1)
print(f'All {len(rows)} approved skill(s) MATCH.')
" "$CONFIG_PATH"
