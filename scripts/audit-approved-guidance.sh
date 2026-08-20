#!/usr/bin/env bash
# audit-approved-guidance.sh — read-only drift report for project guidance.
#
# Wraps project_guidance.ProjectGuidanceEngine.audit(): re-reads and re-hashes
# every pinned instruction source (the repository's CLAUDE.md / AGENTS.md /
# CONTRIBUTING.md files) and every curated artifact under config/guidance/, and
# reports MATCH / DRIFT / MISSING per row. It then runs the DEFAULT-DENY
# verification scan, which reports instruction files that are neither approved
# nor excluded.
#
# Sits beside audit-approved-skills.sh on purpose: an operator investigating a
# refused dispatch wants both reports in one place.
#
# What this script never does: approve anything, write anything, modify the
# manifest, regenerate a curated artifact, or touch the target repository. It is
# a probe, not a repair tool — drift is a Sol reapproval decision, never a
# recalculation.
#
# Exit status: 0 only when every pinned file is an exact MATCH and the
# DEFAULT-DENY scan is empty. 1 on ANY drift, missing file, unreviewed
# instruction file, or a config/manifest that will not load.
#
# FAILS CLOSED, in the same shape as audit-approved-skills.sh: the audit's own
# exit status is what this script exits with, and the final command is exec'd so
# there is no shell frame left that could swallow a non-zero status.

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

echo "sol-claude-dispatcher project-guidance audit — read-only, nothing is modified"
echo "config: ${CONFIG_PATH}"
echo

exec "$VENV_PY" -c "
import sys

from sol_claude_dispatcher.config import load_config
from sol_claude_dispatcher.project_guidance import ProjectGuidanceEngine

config_path = sys.argv[1]

# Any exception here (unparseable TOML, invalid config, missing or internally
# inconsistent manifest) is deliberately left to propagate: an uncaught
# exception exits python non-zero, which is exactly the fail-closed behaviour
# this script promises.
config = load_config(config_path)
engine = ProjectGuidanceEngine.from_config(config)

manifest = engine.manifest
print(f'manifest schema_version={manifest.schema_version} '
      f'approval={manifest.approval.state} version={manifest.approval.version}')
if not manifest.is_approved:
    # Reported, not treated as drift: PENDING_SOL is a deliberate state, and
    # the engine already refuses to project while it holds.
    print('NOTE    approval.state is not APPROVED — nothing will project until Sol approves.')
print(f'project_guidance.enabled={config.project_guidance.enabled}')
print()

rows = engine.audit()
if not rows:
    print('no pinned guidance files in manifest')
    sys.exit(0)

drifted = 0
for row in rows:
    current = row.current_sha256 if row.current_sha256 is not None else '-'
    print(f'{row.status:<7} {row.kind:<8} {row.logical_id}')
    print(f'        path={row.path}')
    print(f'        approved_sha256={row.approved_sha256}')
    print(f'        current_sha256={current}')
    if row.detail:
        print(f'        detail={row.detail}')
    if row.status != 'MATCH':
        drifted += 1

# DEFAULT-DENY verification scan. Never selects a guidance source — resolution
# is manifest-pinned — but a new CLAUDE.md that nobody reviewed must be visible
# here rather than discovered mid-dispatch.
unreviewed = engine.discover_unapproved()

print()
for path in unreviewed:
    print(f'UNREVIEWED       {path}')

if drifted or unreviewed:
    if drifted:
        print(f'{drifted} of {len(rows)} pinned guidance file(s) DRIFTED or MISSING.')
    if unreviewed:
        print(f'{len(unreviewed)} instruction file(s) are neither approved nor excluded.')
    sys.exit(1)
print(f'All {len(rows)} pinned guidance file(s) MATCH; DEFAULT-DENY scan is clean.')
" "$CONFIG_PATH"
