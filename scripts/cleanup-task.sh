#!/usr/bin/env bash
# cleanup-task.sh — safely remove one task's state directory (brief §27/§30 area).
#
# Removes ONLY state/tasks/<task-id>/ after an interactive confirmation (or
# -y / FORCE=1 for non-interactive use). It never touches a worktree inside
# any target repository: if the task recorded a worktree path, this script
# prints the exact `git worktree remove` command for the user to run
# themselves against that repository. Deciding to actually delete a
# worktree — and confirming nothing uncommitted is being lost — is a human
# decision, not this script's.
#
# Usage:
#   scripts/cleanup-task.sh <task-id>
#   scripts/cleanup-task.sh <task-id> -y      # skip confirmation
#   FORCE=1 scripts/cleanup-task.sh <task-id> # same, for CI/non-interactive use

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

usage() {
    echo "usage: $(basename "$0") <task-id> [-y]" >&2
    exit 2
}

[[ $# -ge 1 ]] || usage
TASK_ID="$1"
shift || true
AUTO_YES="${FORCE:-0}"
if [[ "${1:-}" == "-y" ]]; then
    AUTO_YES=1
fi

# Task ids are uuid4 strings (models.new_task_id). Reject anything that is
# not a bare identifier — this also blocks path traversal through the id.
if [[ ! "$TASK_ID" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "error: task id '${TASK_ID}' contains characters outside [A-Za-z0-9_-]; refusing." >&2
    exit 1
fi

TASK_DIR="${PROJECT_ROOT}/state/tasks/${TASK_ID}"

if [[ ! -e "$TASK_DIR" ]]; then
    echo "error: no state directory for task '${TASK_ID}' at ${TASK_DIR}" >&2
    exit 1
fi

# Belt and braces: TASK_DIR must resolve to somewhere inside
# state/tasks/, never outside it (defends against a crafted id even though
# the regex above already blocks '/' and '..').
TASKS_ROOT_REAL="$(cd -- "${PROJECT_ROOT}/state/tasks" && pwd)"
TASK_DIR_REAL="$(cd -- "$TASK_DIR" && pwd)"
if [[ "$TASK_DIR_REAL" != "$TASKS_ROOT_REAL"/* ]]; then
    echo "error: resolved path ${TASK_DIR_REAL} is not inside ${TASKS_ROOT_REAL}; refusing." >&2
    exit 1
fi

echo "Task:      ${TASK_ID}"
echo "State dir: ${TASK_DIR_REAL}"

# Best-effort: read worktree_path out of state.json so we can print (never
# run) the removal command for the human to use in the target repository.
WORKTREE_PATH=""
REPO_ROOT=""
STATE_JSON="${TASK_DIR}/state.json"
ENVELOPE_JSON="${TASK_DIR}/envelope.json"
VENV_PY="${PROJECT_ROOT}/.venv/bin/python"
if [[ -x "$VENV_PY" && -f "$STATE_JSON" ]]; then
    WORKTREE_PATH="$("$VENV_PY" -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    print(data.get('worktree_path') or '')
except Exception:
    print('')
" "$STATE_JSON" 2>/dev/null || true)"
fi
if [[ -x "$VENV_PY" && -f "$ENVELOPE_JSON" ]]; then
    REPO_ROOT="$("$VENV_PY" -c "
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    print((data.get('repository') or {}).get('root') or '')
except Exception:
    print('')
" "$ENVELOPE_JSON" 2>/dev/null || true)"
fi

du_size() {
    du -sh "$TASK_DIR" 2>/dev/null | cut -f1 || echo "unknown"
}

echo "Size:      $(du_size)"
if [[ -n "$WORKTREE_PATH" ]]; then
    echo
    echo "This task recorded a worktree. This script will NOT touch it. If you"
    echo "are done with it, remove it yourself from inside the target repository:"
    echo
    if [[ -n "$REPO_ROOT" ]]; then
        echo "  cd '${REPO_ROOT}' && git worktree remove '${WORKTREE_PATH}'"
        echo "  # or, if it still has uncommitted changes you want to discard:"
        echo "  cd '${REPO_ROOT}' && git worktree remove --force '${WORKTREE_PATH}'"
    else
        echo "  git -C <repository-root> worktree remove '${WORKTREE_PATH}'"
    fi
fi

echo
if [[ "$AUTO_YES" != "1" ]]; then
    if [[ ! -t 0 ]]; then
        echo "error: no TTY and no -y/FORCE=1 given; refusing to delete non-interactively." >&2
        exit 1
    fi
    read -r -p "Delete this task's state directory? Evidence, diffs, and reviews will be lost. [y/N] " reply
    case "$reply" in
        y|Y|yes|YES) ;;
        *) echo "Aborted. Nothing was deleted."; exit 0 ;;
    esac
fi

rm -rf -- "$TASK_DIR"
echo "Removed ${TASK_DIR}"
