#!/usr/bin/env bash
# generate-codex-config.sh — print the Codex MCP server snippet (brief §21).
#
# This script only PRINTS. It never writes to ~/.codex/config.toml or any
# other file outside its own stdout. Applying the snippet is a manual step
# for the user (or Sol) — see the loud comment at the bottom of the output.
#
# ---------------------------------------------------------------------------
# WHY tool_timeout_sec IS NOT "max_timeout_seconds + a margin"  (GATE 6)
# ---------------------------------------------------------------------------
#
# It used to be. This script printed `max_timeout_seconds + 300`, which on the
# shipped 3,600 s ceiling is 3,900 s — and 3,900 s is what was actually
# installed in ~/.codex/config.toml until Lane K corrected it.
#
# That formula was sized when a dispatch tool call returned quickly. Since
# GATE 6 the call BLOCKS for the whole run (src/sol_claude_dispatcher/waiting.py),
# so one tool timeout has to cover the worker, its termination tail, every
# validation command the envelope declares, evidence collection and the stdio
# round trip. Against that, 3,900 s covers the worker phase (3,600 clamp + 25 s
# termination = 3,625 s) plus 275 s of *nothing else* — it pays for neither the
# validation phase nor evidence collection at all. A full-length worker
# followed by any real validation would have had its MCP waiter cancelled
# mid-validation. The margin was not too small; it was the wrong shape.
#
# The number below is therefore DERIVED, from the dispatcher's own constants:
#
#   config.validation.max_total_seconds        the whole declared run
#                                              (execution + all validation),
#                                              itself capped so it cannot exceed
#                                              what the transport can honour
# + WORKER_TERMINATION_TAIL_SECONDS       25   SIGTERM 5 + SIGKILL reap 10
#                                              + pipe drain 10 (runner.py)
# + MAX_VALIDATION_COMMANDS
#     x VALIDATION_COMMAND_TAIL_SECONDS  320   32 x (SIGTERM 5 + drain 5)
#                                              (models.py, validation.py)
# + EVIDENCE_GIT_BUDGET_SECONDS        1,440   24 git calls at 60 s (git.py)
# + MCP_TRANSPORT_BUDGET_SECONDS          60   marshalling + local stdio pipe
#   -----------------------------------------
#   REQUIRED                             = config.required_tool_timeout_seconds()
#   APPLIED   TRANSPORT_TOOL_TIMEOUT_SECONDS   the commissioned ceiling
#
# There is no arithmetic on `max_timeout_seconds` in this file any more, and
# tests/unit/test_codex_config_script.py fails if any is reintroduced.
#
# If the derivation cannot be performed — no virtualenv, no config, an invalid
# config — this script REFUSES to print a snippet rather than guessing a
# number. A wrong tool_timeout_sec is the defect this rewrite exists to
# prevent; a fallback constant would be the same bug wearing a different value.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
VENV_PY="${PROJECT_ROOT}/.venv/bin/python"
ENTRYPOINT="${PROJECT_ROOT}/.venv/bin/sol-claude-dispatcher"

CONFIG_PATH="${SOL_DISPATCHER_CONFIG:-${PROJECT_ROOT}/config/dispatcher.toml}"

refuse() {
    echo "generate-codex-config.sh: $1" >&2
    echo "generate-codex-config.sh: refusing to print a Codex snippet with an" >&2
    echo "  underived tool_timeout_sec. Fix the above and re-run." >&2
    exit 2
}

[[ -x "$VENV_PY" ]] || refuse "no interpreter at ${VENV_PY} (run scripts/setup.sh)"
[[ -f "$CONFIG_PATH" ]] || refuse "no dispatcher config at ${CONFIG_PATH}"

# One python invocation, one line of output: every field the snippet needs,
# read through the real loader so an invalid config fails here rather than
# producing a plausible-looking but unenforced number.
DERIVED="$(
    SOL_DISPATCHER_CONFIG="$CONFIG_PATH" "$VENV_PY" - "$CONFIG_PATH" <<'PY' || refuse "could not derive the timeout from ${CONFIG_PATH}"
import sys

from sol_claude_dispatcher.config import (
    EVIDENCE_GIT_BUDGET_SECONDS,
    MAX_VALIDATION_COMMANDS,
    MCP_TRANSPORT_BUDGET_SECONDS,
    TRANSPORT_TOOL_TIMEOUT_SECONDS,
    UNDECLARED_RUN_OVERHEAD_SECONDS,
    VALIDATION_COMMAND_TAIL_SECONDS,
    WORKER_TERMINATION_TAIL_SECONDS,
    load_config,
    required_tool_timeout_seconds,
)

config = load_config(sys.argv[1])
required = required_tool_timeout_seconds(config)
applied = TRANSPORT_TOOL_TIMEOUT_SECONDS

# The load-time ceiling on validation.max_total_seconds already guarantees
# this. Asserting it here as well means a future edit to either side cannot
# print a snippet that promises more than the transport was commissioned for.
if applied < required:
    raise SystemExit(
        f"derived requirement {required}s exceeds the commissioned "
        f"tool timeout {applied}s"
    )

print(
    " ".join(
        str(value)
        for value in (
            applied,
            required,
            config.validation.max_total_seconds,
            config.dispatcher.max_timeout_seconds,
            WORKER_TERMINATION_TAIL_SECONDS,
            MAX_VALIDATION_COMMANDS * VALIDATION_COMMAND_TAIL_SECONDS,
            EVIDENCE_GIT_BUDGET_SECONDS,
            MCP_TRANSPORT_BUDGET_SECONDS,
            UNDECLARED_RUN_OVERHEAD_SECONDS,
        )
    )
)
PY
)"

read -r TOOL_TIMEOUT_SEC REQUIRED_SEC RUN_BUDGET_SEC MAX_WORKER_SEC \
    WORKER_TAIL_SEC VALIDATION_TAIL_SEC EVIDENCE_SEC TRANSPORT_SEC OVERHEAD_SEC \
    <<<"$DERIVED"

[[ -n "${TOOL_TIMEOUT_SEC:-}" ]] || refuse "the derivation produced no value"

cat <<EOF
# ============================================================================
# Generated by scripts/generate-codex-config.sh — DO NOT APPLY AUTOMATICALLY.
#
# This is a PRINT-ONLY script. Nothing on this host was modified by running
# it. To activate the dispatcher inside Codex, a human (or Sol, with the
# human's knowledge) must:
#
#   1. open ~/.codex/config.toml
#   2. back it up first (this script does not do that for you)
#   3. paste the [mcp_servers.sol_claude_dispatcher] block below into it,
#      preserving every other [mcp_servers.*] entry already present
#   4. save, and restart Codex — the file is read at startup and there is no
#      reload; a running session keeps the old value in memory
#
# ----------------------------------------------------------------------------
# tool_timeout_sec = ${TOOL_TIMEOUT_SEC}s, and here is the whole derivation.
#
# Since GATE 6 a dispatch/resume/review call stays PENDING for the entire run,
# so this one timeout pays for all of the following (values read from
# ${CONFIG_PATH}):
#
#   declared run budget (worker + all validation)   ${RUN_BUDGET_SEC}s
#     of which one worker may take at most          ${MAX_WORKER_SEC}s
#   worker termination tail                         ${WORKER_TAIL_SEC}s
#   validation termination tails (32 commands)      ${VALIDATION_TAIL_SEC}s
#   evidence collection (24 git calls at 60s)       ${EVIDENCE_SEC}s
#   MCP marshalling + local stdio transport         ${TRANSPORT_SEC}s
#   --------------------------------------------------------
#   REQUIRED                                        ${REQUIRED_SEC}s
#   APPLIED                                         ${TOOL_TIMEOUT_SEC}s
#
# It is deliberately NOT "max_timeout_seconds + a margin". That formula
# produced 3,900s, which covered the worker phase and 275s of nothing else,
# and would have cancelled the MCP waiter mid-validation.
#
# The budget is enforced in the dispatcher, not just described here: an
# envelope declaring more than ${RUN_BUDGET_SEC}s is refused with
# ValidationBudgetExceeded before any worker starts. Nothing is truncated or
# dropped to make a task fit.
#
# Exceeding tool_timeout_sec is still not a correctness failure: the waiter is
# cancelled, the worker keeps running, and get_task recovers the authoritative
# state. This ceiling buys autonomy, not safety.
# ============================================================================

[mcp_servers.sol_claude_dispatcher]
command = "${ENTRYPOINT}"
args = []
cwd = "${PROJECT_ROOT}"

startup_timeout_sec = 10
tool_timeout_sec = ${TOOL_TIMEOUT_SEC}
required = false

enabled_tools = [
  "dispatch_claude_task",
  "resume_claude_task",
  "review_task_with_fable",
  "get_task"
]

# ============================================================================
# Reminder: this snippet was PRINTED, not installed. ~/.codex/config.toml has
# not been touched. Apply it yourself when you are ready (step 5 of
# README.md's activation steps is intentionally manual).
# ============================================================================
EOF
