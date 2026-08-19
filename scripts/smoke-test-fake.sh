#!/usr/bin/env bash
# smoke-test-fake.sh — run the full test suite against tests/fake_bin/claude.
#
# Safe to execute. This never spawns a real `claude` or `codex` process —
# every subprocess the suite launches is either `tests/fake_bin/claude`
# (deterministic, offline, scriptable — brief §32) or a short-lived `git`
# command against a throwaway temp repository created by the tests
# themselves. Nothing here touches an existing repository, an existing
# Claude/Codex session, or any file outside this project and pytest's own
# tmp_path fixtures.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
VENV_PY="${PROJECT_ROOT}/.venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
    echo "error: ${VENV_PY} not found." >&2
    echo "  run: python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'" >&2
    exit 1
fi

echo "sol-claude-dispatcher — fake-binary smoke test"
echo "project root: ${PROJECT_ROOT}"
echo "worker binary under test: tests/fake_bin/claude (never the real CLI)"
echo

cd "$PROJECT_ROOT"

# Belt and braces alongside the test suite's own recursion guards: refuse to
# even start if this shell is somehow already inside a worker context.
if [[ "${SOL_WORKER:-}" == "1" ]]; then
    echo "error: SOL_WORKER=1 is set in this shell; refusing to run (§22 layer 4)." >&2
    exit 1
fi

set +e
"$VENV_PY" -m pytest "$@"
STATUS=$?
set -e

echo
if [[ "$STATUS" -eq 0 ]]; then
    echo "Fake-binary smoke test passed. No real Claude or Codex process was spawned."
else
    echo "Fake-binary smoke test FAILED (pytest exit ${STATUS})."
fi
exit "$STATUS"
