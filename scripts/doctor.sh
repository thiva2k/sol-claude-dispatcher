#!/usr/bin/env bash
# doctor.sh — read-only diagnostic for the sol-claude-dispatcher install (brief §30).
#
# What this script does: inspects the toolchain, the venv, the config, the
# prompts, and the schemas, and prints one PASS/FAIL line per check.
#
# What this script never does: install or upgrade anything, modify a user
# config (Codex, Claude, or this project's own config/dispatcher.toml),
# spawn a Claude or Codex worker, or kill a process. Every command below is
# either a filesystem read, a `--version` probe, or an in-process Python
# import — nothing that could touch a live session.
#
# Exit status: 0 when every check passes, 1 when any check fails.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
VENV_PY="${PROJECT_ROOT}/.venv/bin/python"

FAILURES=0

# run_check NAME CMD [ARGS...]
#
# Runs CMD, prints "PASS  NAME  <first line of output>" or
# "FAIL  NAME  <first line of output>", and tracks failures. Never lets a
# failing check abort the script (that would defeat a diagnostic tool) and
# never lets `set -e` propagate out of a failing probe.
run_check() {
    local name="$1"
    shift
    local out status
    if out="$("$@" 2>&1)"; then
        status=0
    else
        status=$?
    fi
    out="$(printf '%s' "$out" | head -n1)"
    if [[ "$status" -eq 0 ]]; then
        printf 'PASS  %-32s %s\n' "$name" "$out"
    else
        printf 'FAIL  %-32s %s\n' "$name" "$out"
        FAILURES=$((FAILURES + 1))
    fi
}

# --- individual checks ------------------------------------------------------

check_venv_python() {
    if [[ ! -x "$VENV_PY" ]]; then
        echo "not found at ${VENV_PY} — run: python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'"
        return 1
    fi
    "$VENV_PY" --version
}

check_pkg_version() {
    local pkg="$1"
    "$VENV_PY" -c "
import sys
from importlib.metadata import PackageNotFoundError, version
try:
    print(version(sys.argv[1]))
except PackageNotFoundError:
    print(sys.argv[1] + ' not installed in .venv')
    sys.exit(1)
" "$pkg"
}

check_git() {
    if ! command -v git >/dev/null 2>&1; then
        echo "git not found on PATH"
        return 1
    fi
    git --version
}

# Locates a worker CLI on PATH and probes only --version. Never invokes it
# with -p / --print, never spawns a worker.
check_binary_version() {
    local binary_name="$1"
    local resolved
    if ! resolved="$(command -v "$binary_name" 2>/dev/null)"; then
        echo "${binary_name} not found on PATH"
        return 1
    fi
    local ver
    ver="$("$resolved" --version 2>&1 || true)"
    ver="$(printf '%s' "$ver" | head -n1)"
    echo "${resolved} (${ver:-version unknown})"
}

check_state_perms() {
    local dir="${PROJECT_ROOT}/state"
    if [[ ! -d "$dir" ]]; then
        echo "missing: ${dir}"
        return 1
    fi
    local mode
    mode="$(stat -c '%a' "$dir")"
    if [[ "$mode" != "700" ]]; then
        echo "${dir} is mode ${mode}, expected 700"
        return 1
    fi
    echo "${dir} mode 700"
}

check_config_parses() {
    local cfg="${PROJECT_ROOT}/config/dispatcher.toml"
    if [[ ! -f "$cfg" ]]; then
        echo "missing: ${cfg} — copy config/dispatcher.example.toml and set [security].allowed_repository_roots"
        return 1
    fi
    "$VENV_PY" -c "
from sol_claude_dispatcher.config import load_config
load_config('${cfg}')
print('parses OK, fails closed on invalid input')
"
}

check_prompts_present() {
    local f missing=0
    for f in worker-policy.md fable-reviewer-policy.md future-sol-observer.md; do
        if [[ ! -f "${PROJECT_ROOT}/prompts/${f}" ]]; then
            echo "missing prompts/${f}"
            missing=1
        fi
    done
    [[ "$missing" -eq 0 ]] || return 1
    echo "3 prompt files present"
}

check_schemas_valid_json() {
    local f count=0
    shopt -s nullglob
    local files=("${PROJECT_ROOT}"/schemas/*.schema.json)
    shopt -u nullglob
    if [[ "${#files[@]}" -eq 0 ]]; then
        echo "no schemas/*.schema.json files found"
        return 1
    fi
    for f in "${files[@]}"; do
        if ! "$VENV_PY" -c "import json, sys; json.load(open(sys.argv[1]))" "$f" >/dev/null 2>&1; then
            echo "invalid JSON: ${f}"
            return 1
        fi
        count=$((count + 1))
    done
    echo "${count} schema file(s) valid JSON"
}

check_empty_mcp_config() {
    local f="${PROJECT_ROOT}/config/empty-mcp.json"
    if [[ ! -f "$f" ]]; then
        echo "missing: ${f}"
        return 1
    fi
    "$VENV_PY" -c "
import json, sys
data = json.load(open(sys.argv[1]))
if data != {'mcpServers': {}}:
    print('unexpected content, expected {\"mcpServers\": {}}:', data)
    sys.exit(1)
print('{\"mcpServers\": {}} exactly')
" "$f"
}

check_fake_claude_present() {
    local f="${PROJECT_ROOT}/tests/fake_bin/claude"
    if [[ ! -x "$f" ]]; then
        echo "missing or not executable: ${f}"
        return 1
    fi
    echo "${f}"
}

# --- run everything ----------------------------------------------------------

echo "sol-claude-dispatcher doctor — read-only diagnostic, nothing is modified"
echo "project root: ${PROJECT_ROOT}"
echo

run_check "python (venv)"          check_venv_python
run_check "mcp package"            check_pkg_version mcp
run_check "pydantic package"       check_pkg_version pydantic
run_check "pytest package"         check_pkg_version pytest
run_check "git"                    check_git
run_check "claude binary"          check_binary_version claude
run_check "codex binary"           check_binary_version codex
run_check "state dir permissions"  check_state_perms
run_check "config parses"          check_config_parses
run_check "worker prompt files"    check_prompts_present
run_check "JSON schemas"           check_schemas_valid_json
run_check "empty MCP config"       check_empty_mcp_config
run_check "fake claude (tests)"    check_fake_claude_present

echo
if [[ "$FAILURES" -eq 0 ]]; then
    echo "All checks passed."
    exit 0
else
    echo "${FAILURES} check(s) failed. Nothing was modified; fix the items above and re-run."
    exit 1
fi
