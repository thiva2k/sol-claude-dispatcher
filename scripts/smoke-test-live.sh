#!/usr/bin/env bash
# smoke-test-live.sh — end-to-end smoke test against the REAL Claude CLI (brief §33).
#
# ============================================================================
#                       *** THIS SCRIPT USES REAL CLAUDE USAGE ***
#
#  It launches the actual `claude` binary against a throwaway temporary git
#  repository and consumes real API usage/credits on whatever account the
#  Claude CLI is authenticated as. It is NOT part of the build/test suite and
#  was intentionally never executed by the agent that wrote it.
#
#  Do not run this from an automated pipeline. Run it yourself, once, when
#  you are ready to confirm the dispatcher works end-to-end against the real
#  worker binary.
# ============================================================================
#
# What it does, end to end, driving this project's own dispatch/session
# modules directly (the same code path the MCP tools in server.py call —
# this harness does not go through the MCP/stdio transport, so it also works
# before the snippet from generate-codex-config.sh has been applied
# anywhere):
#
#   1. creates a brand-new temporary git repository (nothing you own)
#   2. dispatches one tiny, harmless Sonnet task: "create hello.txt"
#   3. checks the result is a schema-valid structured WorkerResult
#   4. checks the change landed in an isolated git worktree, not in the
#      temporary repo's primary working tree
#   5. checks the primary working tree of the temp repo is still clean
#   6. resumes the same session with a second tiny instruction and checks
#      the session id, model, and worktree all stayed the same
#
# It never touches this project's own repository, ~/.codex/config.toml,
# Claude/Codex settings, or any existing session. Everything it creates lives
# under a fresh `mktemp -d` directory that is removed on exit.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
VENV_PY="${PROJECT_ROOT}/.venv/bin/python"

cat <<'BANNER'
================================================================================
  sol-claude-dispatcher LIVE smoke test
  ------------------------------------------------------------------
  This will invoke the REAL `claude` CLI and consume real usage on your
  authenticated account. A throwaway git repo will be created under a temp
  directory and removed afterwards. Nothing in this project's own
  repository, and no existing Codex/Claude config or session, is touched.
================================================================================
BANNER

if [[ "${FORCE:-0}" != "1" ]]; then
    if [[ ! -t 0 ]]; then
        echo "error: no TTY attached and FORCE=1 not set; refusing to run non-interactively." >&2
        echo "       (this is deliberate — see brief §33: warn before consuming Claude usage)" >&2
        exit 1
    fi
    read -r -p "Type 'yes' to proceed and consume real Claude usage: " reply
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
cleanup() {
    rm -rf -- "$WORKDIR"
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

STATE_DIR="${WORKDIR}/state"
CONFIG_FILE="${WORKDIR}/dispatcher.toml"
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
echo "Temp repo:   ${REPO}"
echo "Temp state:  ${STATE_DIR}"
echo "Temp config: ${CONFIG_FILE}"
echo

# This harness drives the dispatcher's own Python modules directly (the same
# security/router/state/git/runner/sessions code the MCP tools in server.py
# call), rather than going through the MCP/stdio transport. That lets it run
# standalone before any MCP client has the server configured, and it fails
# loudly on assert rather than degrading into a soft warning.
set +e
"$VENV_PY" - "$CONFIG_FILE" "$REPO" <<'PYEOF'
import asyncio
import json
import sys
from pathlib import Path

from sol_claude_dispatcher import git, router, security, sessions, validation
from sol_claude_dispatcher.config import load_config
from sol_claude_dispatcher.errors import ClaudeStructuredOutputInvalid, DispatcherError
from sol_claude_dispatcher.locks import RepositoryLock
from sol_claude_dispatcher.models import (
    DispatcherObservations,
    RepositoryRequest,
    RunKind,
    RunMetadata,
    RunRecord,
    ScopeSpec,
    TaskEnvelope,
    TaskRequest,
    TaskSpec,
    TaskState,
    WorkerRole,
    utc_now,
)
from sol_claude_dispatcher.results import parse_worker_result
from sol_claude_dispatcher.runner import build_worker_invocation, run_worker
from sol_claude_dispatcher.state import TaskStore

config_path, repo = sys.argv[1], sys.argv[2]
checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


# --- setup: same startup guard the real MCP server runs (§22 layer 4) ------
config = load_config(config_path)
security.assert_no_recursion(config)

request = TaskRequest(
    repository=RepositoryRequest(root=repo, base_ref="HEAD"),
    task=TaskSpec(
        objective=(
            "Create a new file named hello.txt in the repository root "
            "containing exactly one line: 'hello from claude'. Do not modify "
            "or delete any other file."
        ),
        acceptance_criteria=["hello.txt exists and contains 'hello from claude'"],
    ),
    scope=ScopeSpec(),  # unrestricted: this is a throwaway repo
)

canonical_root = security.validate_repository_root(request.repository.root, config)
security.assert_dispatch_depth(0, config)

lock = RepositoryLock(canonical_root, config.locks_path)
lock.acquire()
try:
    base_commit = git.resolve_base_commit(canonical_root, request.repository.base_ref)
    envelope = TaskEnvelope.from_request(
        request, canonical_root=str(canonical_root), base_commit=base_commit
    )
    store = TaskStore(config.tasks_path)
    store.create(envelope)

    envelope_model, reason = router.explain_route(envelope, config)
    check("router selected a real model (not fable)", envelope_model != config.models.fable, envelope_model)
    store.transition(envelope.task_id, TaskState.ROUTED, reason=reason, selected_model=envelope_model)

    session_id = sessions.new_session(envelope)
    store.transition(envelope.task_id, TaskState.RUNNING, reason="dispatch", session_id=session_id)

    prompt = (
        f"Objective: {request.task.objective}\n\n"
        f"Acceptance criteria:\n- " + "\n- ".join(request.task.acceptance_criteria)
    )
    invocation = build_worker_invocation(
        envelope, config,
        model=envelope_model, session_id=session_id, prompt=prompt, cwd=canonical_root,
    )
    run1 = asyncio.run(run_worker(invocation))
    check("first run did not time out", not run1.timed_out, f"exit={run1.exit_code}")

    worktree = git.worktree_path_for(canonical_root, envelope.worktree_name)
    check("worktree was created", worktree is not None, str(worktree))
    check(
        "worktree is isolated from the primary tree",
        worktree is not None and worktree != canonical_root,
        str(worktree),
    )

    diff = git.collect_diff_evidence(worktree, base_commit) if worktree else None
    scope_check = git.check_scope(diff.changed_paths, envelope.scope) if diff else None
    if diff is not None:
        store.write_evidence(envelope.task_id, "diff.patch", diff.diff_text)
        store.write_evidence(envelope.task_id, "diff-stat.txt", diff.diff_stat)
        store.write_evidence(
            envelope.task_id, "changed-paths.json", json.dumps(diff.changed_paths)
        )

    worker_result = None
    parsed_ok = False
    parse_error = None
    try:
        worker_result = parse_worker_result(run1.stdout)
        parsed_ok = True
    except ClaudeStructuredOutputInvalid as exc:
        parse_error = exc.message
    check("worker result parsed as schema-valid WorkerResult", parsed_ok, parse_error or "")

    primary_status = git.primary_tree_status(canonical_root)
    check("primary tree of the temp repo is still clean", primary_status.strip() == "", repr(primary_status))

    validation_results = (
        asyncio.run(validation.run_validations(envelope, worktree, config))
        if config.validation.run_dispatcher_validation and worktree
        else []
    )

    observations = DispatcherObservations(
        task_id=envelope.task_id,
        run_id="live-smoke-run-1",
        session_id=session_id,
        model=envelope_model,
        base_commit=base_commit,
        duration_ms=run1.duration_ms,
        exit_code=run1.exit_code,
        timed_out=run1.timed_out,
        changed_paths=diff.changed_paths if diff else [],
        diff_stat=diff.diff_stat if diff else "",
        diff_bytes=len((diff.diff_text if diff else "").encode("utf-8")),
        scope_valid=scope_check.valid if scope_check else False,
        out_of_scope_paths=scope_check.out_of_scope if scope_check else [],
        forbidden_paths_touched=scope_check.forbidden if scope_check else [],
        diff_check_passed=diff.diff_check_passed if diff else False,
        worker_result_parsed=parsed_ok,
        worker_result_error=parse_error,
        primary_worktree_clean=primary_status.strip() == "",
    )
    metadata = RunMetadata(
        run_id="live-smoke-run-1",
        run_index=1,
        task_id=envelope.task_id,
        kind=RunKind.DISPATCH,
        role=WorkerRole.IMPLEMENTER,
        model=envelope_model,
        session_id=session_id,
        worktree_path=str(worktree) if worktree else None,
        started_at=utc_now(),
        finished_at=utc_now(),
        duration_ms=run1.duration_ms,
        exit_code=run1.exit_code,
        timed_out=run1.timed_out,
        killed_with_sigkill=run1.killed_with_sigkill,
        argv_redacted=[security.redact(a) for a in run1.argv],
        stdout_bytes=len(run1.stdout.encode("utf-8")),
        stderr_bytes=len(run1.stderr.encode("utf-8")),
    )
    store.append_run(
        envelope.task_id,
        RunRecord(
            metadata=metadata,
            worker_claims=worker_result,
            dispatcher_observations=observations,
            validation_results=validation_results,
        ),
    )

    if run1.timed_out:
        final_state = TaskState.TIMED_OUT
    elif scope_check is not None and not scope_check.valid:
        final_state = TaskState.POLICY_VIOLATION
    elif not parsed_ok or run1.exit_code != 0:
        final_state = TaskState.FAILED
    elif worker_result is not None and worker_result.status.value == "blocked":
        final_state = TaskState.BLOCKED
    else:
        final_state = TaskState.IMPLEMENTED

    store.transition(
        envelope.task_id, final_state, reason="live-smoke first run",
        worktree_path=str(worktree) if worktree else None,
    )
    if final_state == TaskState.IMPLEMENTED:
        store.transition(envelope.task_id, TaskState.AWAITING_SOL_REVIEW, reason="live-smoke")

    # --- resume: same session id, same model, same worktree ---------------
    if final_state == TaskState.IMPLEMENTED:
        record = store.load(envelope.task_id)
        plan = sessions.resume_plan(
            envelope, record,
            "Also create a second file named hello2.txt containing exactly one "
            "line: 'hello again'. Do not modify hello.txt.",
            config=config,
        )
        check("resume reused the same session id", plan.session_id == session_id)
        check("resume reused the same model", plan.model == envelope_model)
        check("resume reused the same worktree", plan.worktree_path == str(worktree))

        store.transition(envelope.task_id, TaskState.RESUME_REQUESTED, reason="live-smoke resume")
        store.transition(
            envelope.task_id, TaskState.RUNNING, reason="live-smoke resume",
            resume_count=plan.next_resume_count,
        )
        resume_invocation = build_worker_invocation(
            envelope, config,
            model=plan.model, session_id=plan.session_id, prompt=plan.instruction,
            cwd=Path(plan.worktree_path), resume_session_id=plan.session_id,
            include_worktree=False, timeout_seconds=plan.timeout_seconds,
        )
        run2 = asyncio.run(run_worker(resume_invocation))
        check("resume run did not time out", not run2.timed_out, f"exit={run2.exit_code}")
        store.transition(
            envelope.task_id, TaskState.IMPLEMENTED, reason="live-smoke resume finished",
            worktree_path=plan.worktree_path,
        )
        store.transition(envelope.task_id, TaskState.AWAITING_SOL_REVIEW, reason="live-smoke resume")
    else:
        check("resume phase skipped", False, f"first run ended in {final_state.value}, not IMPLEMENTED")

finally:
    lock.release()

print()
failed = [name for name, ok, _ in checks if not ok]
if failed:
    print(f"LIVE SMOKE TEST FAILED — {len(failed)} check(s) did not pass: {', '.join(failed)}")
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
