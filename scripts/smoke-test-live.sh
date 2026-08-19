#!/usr/bin/env bash
# smoke-test-live.sh — end-to-end smoke test against the REAL Claude CLI
# (brief §33; expanded per remediation finding P1-10).
#
# ============================================================================
#                       *** THIS SCRIPT USES REAL CLAUDE USAGE ***
#
#  It launches the actual `claude` binary against a throwaway temporary git
#  repository and consumes real API usage/credits on whatever account the
#  Claude CLI is authenticated as. It runs TWO full dispatch/resume/review
#  cycles (one in-process, one over the real MCP stdio transport), i.e. four
#  real dispatch/resume invocations plus two real Fable reviews — six live
#  `claude` process launches in total. It is NOT part of the build/test suite
#  and was intentionally never executed by the agent that wrote/expanded it.
#
#  Do not run this from an automated pipeline. Run it yourself, once, when
#  you are ready to confirm the dispatcher works end-to-end against the real
#  worker binary and the real MCP transport.
# ============================================================================
#
# Coverage (see LANE-D-REPORT.md for the full checklist and what is
# deliberately out of scope):
#
#   1. REAL WORKER    — claude launches; Sonnet resolves; an isolated
#                        worktree is created; structured output parses;
#                        resume reuses the same session id, model, worktree.
#   2. REAL FABLE      — Fable launches in a fresh session (never the
#                        worker's); read-only tool set; structured review
#                        parses; the worktree diff is byte-identical before
#                        and after the review (no file changes during it).
#   3. MCP PHASE       — a second, independent cycle driven over the real
#                        MCP stdio transport (a live `sol_claude_dispatcher`
#                        server subprocess), using the project's own `mcp`
#                        SDK from .venv: initialize, tools/list,
#                        dispatch_claude_task, get_task, resume_claude_task,
#                        review_task_with_fable.
#   4. REPOSITORY GUARD — the configured repo is accepted; a subdirectory of
#                        it is rejected (P0-2: exact git top-level only, no
#                        descendants); this project's own repository is
#                        rejected; a repo outside every allowlisted root
#                        (standing in for /tmp/other-repo) is rejected.
#   5. RECURSION       — the argv the dispatcher actually recorded for each
#                        live run still carries every recursion protection
#                        (mcp stripped, Agent/Task denied, claude/codex
#                        denied, no --dangerously-skip-permissions), and
#                        security.worker_environment() still sets the
#                        SOL_WORKER marker and strips secret-shaped vars.
#
# Everything this script creates lives under a fresh `mktemp -d` directory
# removed on exit (see the `cleanup` trap below), with one narrow exception:
# the repository-guard phase needs a real git repository that is NOT this
# project and NOT the temp repo, standing in for the brief's literal
# "/tmp/other-repo" case. If /tmp/other-repo does not already exist, this
# script creates one and removes it again on exit; if it already exists (e.g.
# a real directory of the user's), it is used read-only and never modified
# or deleted — see the OTHER_REPO block below.
#
# This project's own repository is used ONLY as the target of a rejection
# check (a pure, read-only `git rev-parse` under the hood) and ONLY as the
# cwd for the MCP server subprocess launched with an EPHEMERAL config
# (SOL_DISPATCHER_CONFIG env var, never the project's config/dispatcher.toml
# default). The production config file is never read, written, or pointed at
# by anything in this script — see the REAL_CONFIG guard below.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
VENV_PY="${PROJECT_ROOT}/.venv/bin/python"

cat <<'BANNER'
================================================================================
  sol-claude-dispatcher LIVE smoke test (expanded: worker + Fable + MCP +
  repository guard + recursion protections)
  ------------------------------------------------------------------
  This will invoke the REAL `claude` CLI six times (two dispatches, two
  resumes, two Fable reviews) and consume real usage on your authenticated
  account. It also starts a real MCP server subprocess over stdio. Throwaway
  git repos are created under temp directories and removed afterwards.
  Nothing in this project's own repository, and no existing Codex/Claude
  config or session, is touched. The production dispatcher config
  (config/dispatcher.toml) is never read or written by this script.
================================================================================
BANNER

if [[ "${FORCE:-0}" != "1" ]]; then
    if [[ ! -t 0 ]]; then
        echo "error: no TTY attached and FORCE=1 not set; refusing to run non-interactively." >&2
        echo "       (this is deliberate — see brief §33: warn before consuming Claude usage)" >&2
        exit 1
    fi
    read -r -p "Type 'yes' to proceed and consume real Claude usage (6 live launches): " reply
    if [[ "$reply" != "yes" ]]; then
        echo "Aborted. Nothing was run."
        exit 0
    fi
fi

if [[ ! -x "$VENV_PY" ]]; then
    echo "error: ${VENV_PY} not found. Run: python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'" >&2
    exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
    echo "error: 'claude' not found on PATH. Install the Claude Code CLI first." >&2
    exit 1
fi

if [[ "${SOL_WORKER:-}" == "1" ]]; then
    echo "error: SOL_WORKER=1 is set in this shell; refusing to run (§22 layer 4)." >&2
    exit 1
fi

WORKDIR="$(mktemp -d -t sol-claude-live-smoke.XXXXXX)"

# Repository-guard fixture standing in for the brief's literal
# "/tmp/other-repo": a real git repository that is neither the configured
# temp repo nor this project. Reused as-is (never modified/removed) if it
# already exists; created and cleaned up here otherwise.
OTHER_REPO="/tmp/other-repo"
OTHER_REPO_CREATED=0

cleanup() {
    rm -rf -- "$WORKDIR"
    if [[ "$OTHER_REPO_CREATED" == "1" ]]; then
        rm -rf -- "$OTHER_REPO"
    fi
}
trap cleanup EXIT

REPO="${WORKDIR}/throwaway-repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.email "smoke-test@example.invalid"
git -C "$REPO" config user.name "smoke test"
echo "# throwaway repo for sol-claude-dispatcher live smoke test" > "$REPO/README.md"
git -C "$REPO" add README.md
git -C "$REPO" commit -q -m "initial commit"

# A plain subdirectory (not its own git repo): its git top-level resolves to
# $REPO, not to itself, which is exactly the P0-2 case the repository guard
# must reject (see AUDIT/REMEDIATION-BRIEF finding P0-2 — "reject subdirectory
# requests" even when they resolve to an otherwise-allowed top-level).
mkdir -p "${REPO}/subdir"

if [[ -e "$OTHER_REPO" ]]; then
    echo "note: ${OTHER_REPO} already exists; using it read-only for the"
    echo "      repository-guard 'outside every allowlisted root' case. It is"
    echo "      not modified or deleted by this script."
else
    mkdir -p "$OTHER_REPO"
    git -C "$OTHER_REPO" init -q
    git -C "$OTHER_REPO" config user.email "smoke-test@example.invalid"
    git -C "$OTHER_REPO" config user.name "smoke test"
    echo "# a repository that is never in the dispatcher's allowlist" > "$OTHER_REPO/README.md"
    git -C "$OTHER_REPO" add README.md
    git -C "$OTHER_REPO" commit -q -m "initial commit"
    OTHER_REPO_CREATED=1
fi

STATE_DIR="${WORKDIR}/state"
CONFIG_FILE="${WORKDIR}/dispatcher.toml"

# Defense in depth: the ephemeral config path must never collide with the
# project's real config. (Belt-and-braces — CONFIG_FILE is always under
# $WORKDIR, which can never equal $PROJECT_ROOT/config/dispatcher.toml, but
# assert it explicitly so a future edit to this script cannot silently widen
# the blast radius onto the production config.)
REAL_CONFIG="${PROJECT_ROOT}/config/dispatcher.toml"
if [[ "$CONFIG_FILE" == "$REAL_CONFIG" ]]; then
    echo "internal error: ephemeral config path collided with the production config path; aborting." >&2
    exit 1
fi

cat > "$CONFIG_FILE" <<EOF
[dispatcher]
state_dir = "${STATE_DIR}"
default_timeout_seconds = 300
max_timeout_seconds = 600
default_max_turns = 10
default_max_resume_count = 4

[models]
sonnet = "sonnet"
opus = "opus"
fable = "fable"

[routing]
default_model = "sonnet"

[security]
max_dispatch_depth = 1
allow_network = false
allow_push = false
allow_merge = false
allow_commit = false
allow_subagents = false
allowed_repository_roots = ["${REPO}"]

[validation]
run_dispatcher_validation = false

[claude]
binary = "claude"
permission_mode = "auto"
worker_policy_path = "${PROJECT_ROOT}/prompts/worker-policy.md"
fable_policy_path = "${PROJECT_ROOT}/prompts/fable-reviewer-policy.md"
empty_mcp_config_path = "${PROJECT_ROOT}/config/empty-mcp.json"
worker_result_schema_path = "${PROJECT_ROOT}/schemas/worker-result.schema.json"
fable_review_schema_path = "${PROJECT_ROOT}/schemas/fable-review.schema.json"
EOF

echo
echo "Temp repo:        ${REPO}"
echo "Temp state:        ${STATE_DIR}"
echo "Temp config:       ${CONFIG_FILE}"
echo "Other-repo fixture: ${OTHER_REPO} (created=${OTHER_REPO_CREATED})"
echo "Production config (never touched): ${REAL_CONFIG}"
echo

# The embedded harness below exercises two independent code paths so both
# are proven live:
#
#  * the `Dispatcher` class in server.py directly (the same object every MCP
#    tool adapter calls — see server.py's own "Layering note"), which is the
#    fastest way to get detailed, typed assertions on session/model/worktree
#    identity and on the argv the dispatcher actually recorded; and
#
#  * the real MCP stdio transport, spawning `python -m
#    sol_claude_dispatcher.server` (via `main()`) as a subprocess and
#    speaking JSON-RPC to it with this project's own `mcp` SDK client
#    (mirrors tests/integration/test_server_surface.py's
#    test_stdio_handshake_lists_the_four_tools, extended through all four
#    tools instead of stopping at the handshake).
#
# NOTE ON THE POST-REMEDIATION CONTRACT: this harness calls
# `security.validate_repository_root` directly for the repository-guard
# phase, and reads `RunMetadata.argv_redacted` back out of `get_task()` for
# the recursion-protection phase, rather than re-implementing either check
# here. That is deliberate: those are the exact functions/fields the
# remediation pass (P0-2 exact-git-top-level, P1-9 code-level invariant
# denies) is changing, so this script must observe their real, live
# behaviour rather than assert its own copy of the old contract.
set +e
"$VENV_PY" - "$CONFIG_FILE" "$REPO" "$PROJECT_ROOT" "$OTHER_REPO" <<'PYEOF'
import asyncio
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

from sol_claude_dispatcher import security
from sol_claude_dispatcher.config import load_config
from sol_claude_dispatcher.errors import DispatcherError
from sol_claude_dispatcher.runner import (
    ALWAYS_DISALLOWED_TOOLS,
    FORBIDDEN_FLAGS,
    MUTATING_TOOL_NAMES,
)
from sol_claude_dispatcher.server import Dispatcher, SERVER_INSTRUCTIONS, TOOL_NAMES

CONFIG_PATH, REPO, PROJECT_ROOT, OTHER_REPO = sys.argv[1:5]

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def section(title: str) -> None:
    print()
    print(f"--- {title} " + "-" * max(0, 76 - len(title)))


def git(cwd: Path, args: list[str]) -> str:
    """Read-only git call used only to snapshot worktree state for
    before/after comparisons around the Fable review. Never mutates."""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=30
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} failed in {cwd}: {proc.stderr}")
    return proc.stdout


# --- setup: same startup guard the real MCP server runs (§22 layer 4) ------
config = load_config(CONFIG_PATH)
security.assert_no_recursion(config)

check(
    "ephemeral config allowlist is exactly the temp repo — production "
    "config is never touched",
    config.security.allowed_repository_roots == [REPO],
    str(config.security.allowed_repository_roots),
)
check(
    "Fable's configured reviewer_tools contain no mutating tool",
    all(t not in MUTATING_TOOL_NAMES for t in config.claude.reviewer_tools),
    str(config.claude.reviewer_tools),
)


def assert_argv_recursion_safe(label: str, argv_redacted: list[str]) -> None:
    """§22: every recorded worker/Fable argv must still carry the recursion
    protections, read back from what the dispatcher actually recorded for a
    real run — not re-derived from this script's own idea of the policy."""
    check(f"{label}: mcp__* is denied (mcp stripped)", "mcp__*" in argv_redacted, "")
    check(f"{label}: Agent is denied", "Agent" in argv_redacted, "")
    check(f"{label}: Task is denied", "Task" in argv_redacted, "")
    check(f"{label}: claude sub-invocation is denied", "Bash(claude:*)" in argv_redacted, "")
    check(f"{label}: codex sub-invocation is denied", "Bash(codex:*)" in argv_redacted, "")
    for name in ALWAYS_DISALLOWED_TOOLS:
        check(f"{label}: ALWAYS_DISALLOWED_TOOLS entry {name!r} present in argv", name in argv_redacted, "")
    forbidden_present = FORBIDDEN_FLAGS.intersection(argv_redacted)
    check(
        f"{label}: no --dangerously-skip-permissions / --allow-dangerously-skip-permissions",
        not forbidden_present,
        str(sorted(forbidden_present)),
    )


# ===========================================================================
# PHASE 0 — repository guard (P0-2: exact git top-level required, no
# descendants). Pure and local: spends no Claude usage, so it runs first.
# ===========================================================================
section("repository guard (P0-2 — exact git top-level, no descendants)")


def repo_guard(label: str, raw_root: str, expect_ok: bool) -> None:
    try:
        resolved = security.validate_repository_root(raw_root, config)
    except DispatcherError as exc:
        if expect_ok:
            check(f"repo guard: {label} should be accepted", False, f"{type(exc).__name__}: {exc.message}")
        else:
            check(f"repo guard: {label} is rejected", True, type(exc).__name__)
        return
    if expect_ok:
        check(f"repo guard: {label} is accepted", True, str(resolved))
    else:
        check(f"repo guard: {label} should be rejected", False, f"unexpectedly resolved to {resolved!r}")


repo_guard("the configured repo itself", REPO, True)
repo_guard("a subdirectory of the configured repo", str(Path(REPO) / "subdir"), False)
repo_guard("this project's own repository", PROJECT_ROOT, False)
repo_guard("a repo outside every allowlisted root (/tmp/other-repo)", OTHER_REPO, False)


# ===========================================================================
# PHASE 1 — recursion protections, static half. security.worker_environment
# is a pure function; exercising it here spends no Claude usage. The
# argv-level half runs after each real dispatch/review below, against argv
# the dispatcher actually recorded.
# ===========================================================================
section("recursion protections — worker_environment() (static, no live call)")

sample_env = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/home/nobody",
    "HARMLESS_SETTING": "keep-me",
    "DEPLOY_API_KEY": "should-be-stripped",
    "AUTH_TOKEN": "should-be-stripped",
    "SOL_DISPATCHER_SECRET": "should-be-stripped",
}
built_env = security.worker_environment(sample_env, task_id="smoke-static-check", dispatch_depth=0)
check("worker_environment sets SOL_WORKER=1", built_env.get("SOL_WORKER") == "1", str(built_env.get("SOL_WORKER")))
check("worker_environment sets SOL_DISPATCH_DEPTH", built_env.get("SOL_DISPATCH_DEPTH") is not None, str(built_env.get("SOL_DISPATCH_DEPTH")))
check("worker_environment sets SOL_TASK_ID", built_env.get("SOL_TASK_ID") == "smoke-static-check", str(built_env.get("SOL_TASK_ID")))
check("worker_environment strips secret-shaped keys", "DEPLOY_API_KEY" not in built_env and "AUTH_TOKEN" not in built_env, str(sorted(built_env)))
check("worker_environment strips SOL_DISPATCHER_* keys", "SOL_DISPATCHER_SECRET" not in built_env, str(sorted(built_env)))
check("worker_environment preserves harmless keys", built_env.get("HARMLESS_SETTING") == "keep-me", str(built_env.get("HARMLESS_SETTING")))


# ===========================================================================
# PHASE 2 — real worker + real Fable, driven through the actual Dispatcher
# class (the exact object every MCP tool adapter in server.py calls).
# ===========================================================================
async def dispatch_resume_review_cycle(
    dispatcher: Dispatcher, label: str, filename1: str, filename2: str
) -> None:
    section(f"{label}: real worker (dispatch_claude_task)")
    request = {
        "repository": {"root": REPO, "base_ref": "HEAD"},
        "task": {
            "kind": "implementation",
            "objective": (
                f"Create a new file named {filename1} in the repository root "
                "containing exactly one line: 'hello from claude'. Do not "
                "modify or delete any other file."
            ),
            "acceptance_criteria": [f"{filename1} exists and contains 'hello from claude'"],
        },
        "scope": {"allowed_paths": [filename1, filename2], "forbidden_paths": []},
        "routing": {"model": "auto", "complexity": "low", "risk": "low"},
        "execution": {"timeout_seconds": 240, "max_turns": 10, "max_resume_count": 4},
    }
    result = await dispatcher.dispatch_claude_task(request)
    check(f"{label}: dispatch returned no tool-level error", "error" not in result, str(result.get("error")))
    if "error" in result:
        return

    task_id = result["task_id"]
    session_id = result["session_id"]
    model = result["selected_model"]
    worktree = result["worktree"]

    check(f"{label}: Sonnet resolved as the model", model == dispatcher.config.models.sonnet, model)
    check(f"{label}: an isolated worktree was created", bool(worktree) and worktree != REPO, str(worktree))
    check(
        f"{label}: worker result parsed as schema-valid WorkerResult",
        result.get("worker_claims") is not None and result.get("worker_result_error") is None,
        str(result.get("worker_result_error")),
    )

    task_view = await dispatcher.get_task(task_id)
    assert_argv_recursion_safe(f"{label} dispatch run", task_view["runs"][-1]["metadata"]["argv_redacted"])

    section(f"{label}: resume (same session id / model / worktree)")
    resume_result = await dispatcher.resume_claude_task(
        task_id,
        f"Also create a second file named {filename2} containing exactly one "
        f"line: 'hello again'. Do not modify {filename1}.",
    )
    check(f"{label}: resume returned no tool-level error", "error" not in resume_result, str(resume_result.get("error")))
    resume_session_id = session_id
    if "error" not in resume_result:
        resume_session_id = resume_result["session_id"]
        check(f"{label}: resume reused the same session id", resume_result["session_id"] == session_id, resume_result["session_id"])
        check(f"{label}: resume reused the same model", resume_result["selected_model"] == model, resume_result["selected_model"])
        check(f"{label}: resume reused the same worktree", resume_result["worktree"] == worktree, resume_result["worktree"])
        check(
            f"{label}: resume's worker result parsed as schema-valid WorkerResult",
            resume_result.get("worker_claims") is not None and resume_result.get("worker_result_error") is None,
            str(resume_result.get("worker_result_error")),
        )

    section(f"{label}: real Fable review (fresh session, read-only, no file changes)")
    worktree_path = Path(worktree)
    before = (
        git(worktree_path, ["status", "--porcelain"]),
        git(worktree_path, ["diff", "HEAD"]),
        git(worktree_path, ["rev-parse", "HEAD"]),
    )

    review_result = await dispatcher.review_task_with_fable(task_id)
    check(f"{label}: review returned no tool-level error", "error" not in review_result, str(review_result.get("error")))
    if "error" in review_result:
        return

    check(
        f"{label}: Fable used a fresh session (never the worker's)",
        review_result["session_id"] not in (session_id, resume_session_id),
        review_result["session_id"],
    )
    check(f"{label}: Fable ran the configured fable model", review_result["model"] == dispatcher.config.models.fable, review_result["model"])
    review_payload = review_result.get("review") or {}
    check(
        f"{label}: Fable review parsed as schema-valid FableReview",
        bool(review_payload) and "verdict" in review_payload,
        str(review_payload)[:200],
    )
    check(f"{label}: Fable's verdict is advisory only, never an approval", review_result.get("advisory") is True, str(review_result.get("advisory")))

    after = (
        git(worktree_path, ["status", "--porcelain"]),
        git(worktree_path, ["diff", "HEAD"]),
        git(worktree_path, ["rev-parse", "HEAD"]),
    )
    check(
        f"{label}: worktree diff is byte-identical before vs. after the Fable review",
        before == after,
        "status/diff/HEAD compared" if before == after else "MISMATCH — Fable appears to have changed the worktree",
    )

    task_view_after_review = await dispatcher.get_task(task_id)
    assert_argv_recursion_safe(f"{label} Fable review run", task_view_after_review["runs"][-1]["metadata"]["argv_redacted"])


# ===========================================================================
# PHASE 3 — the same four tools, but over the REAL MCP stdio transport: a
# live `sol_claude_dispatcher` server subprocess, spoken to with this
# project's own `mcp` SDK client (mirrors
# tests/integration/test_server_surface.py's stdio handshake test, extended
# through dispatch/get/resume/review instead of stopping at tools/list).
# ===========================================================================
async def mcp_phase() -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    section("MCP phase: real stdio server process, all four tools")

    env = dict(os.environ)
    env["SOL_DISPATCHER_CONFIG"] = CONFIG_PATH
    env.pop("SOL_WORKER", None)
    env.pop("SOL_DISPATCH_DEPTH", None)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from sol_claude_dispatcher.server import main; main()"],
        env=env,
        cwd=PROJECT_ROOT,
    )

    def unwrap(call_result) -> dict:
        if call_result.structured_content is not None:
            return call_result.structured_content
        text = "".join(getattr(block, "text", "") for block in call_result.content)
        return json.loads(text)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await asyncio.wait_for(session.initialize(), timeout=30)
            check("MCP initialize: reports the dispatcher server identity", init.server_info.name == "sol-claude-dispatcher", init.server_info.name)
            check("MCP initialize: returns the §6 instructions verbatim", init.instructions == SERVER_INSTRUCTIONS, "")

            listed = await asyncio.wait_for(session.list_tools(), timeout=30)
            names = sorted(t.name for t in listed.tools)
            check("MCP tools/list: exactly the four registered tools", names == sorted(TOOL_NAMES), str(names))

            request = {
                "repository": {"root": REPO, "base_ref": "HEAD"},
                "task": {
                    "kind": "implementation",
                    "objective": (
                        "Create a new file named hello-mcp.txt in the "
                        "repository root containing exactly one line: 'hello "
                        "over mcp'. Do not modify or delete any other file."
                    ),
                    "acceptance_criteria": ["hello-mcp.txt exists and contains 'hello over mcp'"],
                },
                "scope": {"allowed_paths": ["hello-mcp.txt", "hello-mcp-2.txt"], "forbidden_paths": []},
                "routing": {"model": "auto", "complexity": "low", "risk": "low"},
                "execution": {"timeout_seconds": 240, "max_turns": 10, "max_resume_count": 4},
            }
            dispatch_res = unwrap(await session.call_tool("dispatch_claude_task", {"request": request}, read_timeout_seconds=300))
            check("MCP dispatch_claude_task: no tool-level error", "error" not in dispatch_res, str(dispatch_res.get("error")))
            if "error" in dispatch_res:
                return

            task_id = dispatch_res["task_id"]
            session_id = dispatch_res["session_id"]
            model = dispatch_res["selected_model"]
            worktree = dispatch_res["worktree"]
            check("MCP dispatch_claude_task: Sonnet resolved as the model", model == config.models.sonnet, model)
            check("MCP dispatch_claude_task: an isolated worktree was created", bool(worktree) and worktree != REPO, str(worktree))
            check(
                "MCP dispatch_claude_task: structured worker result parsed",
                dispatch_res.get("worker_claims") is not None and dispatch_res.get("worker_result_error") is None,
                str(dispatch_res.get("worker_result_error")),
            )

            get_res = unwrap(await session.call_tool("get_task", {"task_id": task_id}))
            check(
                "MCP get_task: reports the same session id / model / worktree as dispatch",
                get_res.get("session_id") == session_id
                and get_res.get("model") == model
                and get_res.get("worktree") == worktree,
                str({k: get_res.get(k) for k in ("session_id", "model", "worktree")}),
            )
            assert_argv_recursion_safe("MCP dispatch run", get_res["runs"][-1]["metadata"]["argv_redacted"])

            resume_res = unwrap(
                await session.call_tool(
                    "resume_claude_task",
                    {
                        "task_id": task_id,
                        "instruction": (
                            "Also create a second file named hello-mcp-2.txt "
                            "containing exactly one line: 'hello again over "
                            "mcp'. Do not modify hello-mcp.txt."
                        ),
                    },
                    read_timeout_seconds=300,
                )
            )
            check("MCP resume_claude_task: no tool-level error", "error" not in resume_res, str(resume_res.get("error")))
            resume_session_id = session_id
            if "error" not in resume_res:
                resume_session_id = resume_res["session_id"]
                check("MCP resume_claude_task: same session id as dispatch", resume_res["session_id"] == session_id, resume_res["session_id"])
                check("MCP resume_claude_task: same model as dispatch", resume_res["selected_model"] == model, resume_res["selected_model"])
                check("MCP resume_claude_task: same worktree as dispatch", resume_res["worktree"] == worktree, resume_res["worktree"])

            worktree_path = Path(worktree)
            before = (
                git(worktree_path, ["status", "--porcelain"]),
                git(worktree_path, ["diff", "HEAD"]),
                git(worktree_path, ["rev-parse", "HEAD"]),
            )
            review_res = unwrap(await session.call_tool("review_task_with_fable", {"task_id": task_id}, read_timeout_seconds=300))
            check("MCP review_task_with_fable: no tool-level error", "error" not in review_res, str(review_res.get("error")))
            if "error" in review_res:
                return
            check(
                "MCP review_task_with_fable: fresh session (never the worker's)",
                review_res["session_id"] not in (session_id, resume_session_id),
                review_res["session_id"],
            )
            check("MCP review_task_with_fable: advisory only", review_res.get("advisory") is True, str(review_res.get("advisory")))
            after = (
                git(worktree_path, ["status", "--porcelain"]),
                git(worktree_path, ["diff", "HEAD"]),
                git(worktree_path, ["rev-parse", "HEAD"]),
            )
            check(
                "MCP review_task_with_fable: worktree diff unchanged across the review",
                before == after,
                "status/diff/HEAD compared" if before == after else "MISMATCH — Fable appears to have changed the worktree",
            )

            get_res_after_review = unwrap(await session.call_tool("get_task", {"task_id": task_id}))
            assert_argv_recursion_safe("MCP Fable review run", get_res_after_review["runs"][-1]["metadata"]["argv_redacted"])


async def main() -> None:
    dispatcher = Dispatcher(config)
    await dispatch_resume_review_cycle(dispatcher, "in-process Dispatcher path", "hello.txt", "hello2.txt")
    await mcp_phase()


try:
    asyncio.run(main())
except Exception:
    check("live smoke harness completed without an unhandled exception", False, "see traceback below")
    traceback.print_exc()

print()
failed = [name for name, ok, _ in checks if not ok]
if failed:
    print(f"LIVE SMOKE TEST FAILED — {len(failed)} of {len(checks)} check(s) did not pass:")
    for name in failed:
        print(f"  - {name}")
    sys.exit(1)
print(f"LIVE SMOKE TEST PASSED — {len(checks)} check(s) all green.")
PYEOF
STATUS=$?
set -e

echo
if [[ "$STATUS" -eq 0 ]]; then
    echo "Live smoke test completed successfully."
else
    echo "Live smoke test FAILED (exit ${STATUS}). Temp repo and state have been removed;"
    echo "re-run with the trap disabled (comment out 'trap cleanup EXIT' above) if you need"
    echo "to inspect ${WORKDIR} after a failure."
fi
exit "$STATUS"
