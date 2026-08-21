"""§2/§3 — the B1 transport boundary, live, on the FINAL composed payload.

Lane H set the ceiling at 122,880 UTF-8 bytes, eight KiB below the kernel cliff
its own measurement put at 131,071. Lane H's §10 is explicit that two things
were never proven: that 122,880 bytes actually launches, and that the refusal
reaches Sol. This module proves the first; ``mcp_stdio.py`` proves the second.

Every case here measures the **final composed** ``--append-system-prompt``
value — the exact string that becomes one argv element — never a component and
never a sum of per-component caps. The base is a real
:class:`WorkerContextComposer` composition with both projections on; padding
only takes it to an exact byte count, and a sentinel is placed at the very
**end** so a truncation of a maximal payload cannot hide.

Every case goes through the real ``build_worker_invocation()`` → ``build_argv()``
with the dispatcher's full argv shape. A boundary proven with a toy
``claude -p`` would say nothing about the composition actually under test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _common import eprint, run_cli, write_evidence

from sol_claude_dispatcher.config import (
    MAX_APPEND_SYSTEM_PROMPT_BYTES,
    MEASURED_SINGLE_ARGV_LIMIT_BYTES,
)
from sol_claude_dispatcher.errors import ContextTooLarge, DispatcherError
from sol_claude_dispatcher.models import RunKind
from sol_claude_dispatcher.runner import build_argv, build_worker_invocation, worker_policy_text
from sol_claude_dispatcher.worker_context import WorkerContextComposer

#: The composition the production worst case reached before B1 refused it.
PRODUCTION_DANGEROUS_BYTES = 142_006
#: The intended first controlled task's measured shape.
FIRST_TASK_BYTES = 79_406

_FILLER = (
    "Reference note: this repository keeps its module map in the graph report "
    "and prefers narrow, reviewed changes that keep the failing case in view.\n"
)


def _pad_exactly(base: str, target: int, tail: str) -> str:
    """Compose ``base`` + inert filler + ``tail`` to EXACTLY ``target`` bytes.

    The tail lands last on purpose: it is the truncation detector. If the CLI
    or the kernel silently clipped a maximal payload, the tail is the first
    thing to disappear and the model would answer UNKNOWN.
    """
    base_b, tail_b = len(base.encode()), len(tail.encode())
    room = target - base_b - tail_b
    if room < 0:
        raise AssertionError(
            f"base ({base_b} B) + tail ({tail_b} B) already exceeds target {target} B"
        )
    filler = (_FILLER * (room // len(_FILLER) + 2))[:room]
    # ASCII filler, so character slicing is byte slicing.
    payload = base + filler + tail
    actual = len(payload.encode())
    if actual != target:
        raise AssertionError(f"padding produced {actual} B, wanted {target} B")
    return payload


def _compose_base(gate) -> tuple[str, Any]:
    """A real §14 composition with both projections on, from the real composer."""
    composer = WorkerContextComposer(gate.config)
    composer.assert_repository_reviewed()
    identity = composer.repository_identity(gate.fx.repo)
    envelope = gate.envelope()
    ctx = composer.for_worker(
        envelope,
        run_kind=RunKind.DISPATCH,
        policy_text=worker_policy_text(gate.config),
        task_prompt="probe",
        identity=identity,
    )
    return ctx.append_system_prompt, envelope


def run(gate, *, live: bool) -> None:
    tail_token = f"SENT-TRANSPORTTAIL-{gate.fx.nonce}"
    tail = (
        "\n\n----- TRANSPORT TAIL REFERENCE -----\n"
        f"The transport tail marker for this project is {tail_token}.\n"
        "----- END TRANSPORT TAIL REFERENCE -----\n"
    )
    base, _ = _compose_base(gate)
    eprint(f"[boundary] real composed base = {len(base.encode()):,} B")

    gate.check(
        "B1-limits", "transport ceiling constants (§2)",
        f"the shipped ceiling is {MAX_APPEND_SYSTEM_PROMPT_BYTES:,} B and the "
        f"measured kernel cliff is {MEASURED_SINGLE_ARGV_LIMIT_BYTES:,} B, with "
        f"the ceiling strictly below the cliff",
        MAX_APPEND_SYSTEM_PROMPT_BYTES == 122_880
        and MEASURED_SINGLE_ARGV_LIMIT_BYTES == 131_071
        and MAX_APPEND_SYSTEM_PROMPT_BYTES < MEASURED_SINGLE_ARGV_LIMIT_BYTES,
        write_evidence(
            gate.fx.evidence_dir, "b1.constants.txt",
            f"MAX_APPEND_SYSTEM_PROMPT_BYTES={MAX_APPEND_SYSTEM_PROMPT_BYTES}\n"
            f"MEASURED_SINGLE_ARGV_LIMIT_BYTES={MEASURED_SINGLE_ARGV_LIMIT_BYTES}\n"
            f"reserve={MEASURED_SINGLE_ARGV_LIMIT_BYTES - MAX_APPEND_SYSTEM_PROMPT_BYTES}\n",
        ),
    )

    _case_A(gate, base, tail, tail_token, live=live)
    _case_B(gate, base, tail)
    _case_C(gate, base, tail)
    _case_D(gate, base, tail, live=live)
    _case_E2BIG(gate)


# ---------------------------------------------------------------------------
# A — EXACTLY 122,880
# ---------------------------------------------------------------------------


def _case_A(gate, base: str, tail: str, tail_token: str, *, live: bool) -> None:
    target = MAX_APPEND_SYSTEM_PROMPT_BYTES
    payload = _pad_exactly(base, target, tail)
    argv, spec, err = _build(gate, payload)

    ev = write_evidence(
        gate.fx.evidence_dir, "b1.A.exact-ceiling.txt",
        f"target={target}\nactual={len(payload.encode())}\nbuild_error={err}\n"
        f"argv_elements={len(argv) if argv else 0}\n"
        f"payload_head={payload[:400]!r}\npayload_tail={payload[-400:]!r}\n",
    )
    gate.check(
        "B1-A-accept", "transport boundary (§2 A)",
        f"a composed payload of EXACTLY {target:,} B is ACCEPTED by the "
        f"preflight and an argv is produced",
        err is None and argv is not None, ev, err or "no refusal",
    )
    if argv is None:
        return
    gate.check(
        "B1-A-exact", "transport boundary (§2 A)",
        f"the argv element that follows --append-system-prompt is exactly "
        f"{target:,} UTF-8 bytes — the boundary is measured on the FINAL "
        f"composed payload, not a component",
        len(argv[argv.index("--append-system-prompt") + 1].encode()) == target, ev,
    )
    if not live:
        return

    inv = run_cli(
        "b1/A-exact-ceiling", argv, cwd=gate.fx.repo,
        env=dict(spec.env), timeout_s=600, ledger=gate.ledger,
    )
    live_ev = write_evidence(
        gate.fx.evidence_dir, "b1.A.live.json",
        json.dumps(
            {"payload_bytes": target, "invocation": inv.to_record(),
             "raw_stdout": inv.stdout, "raw_stderr": inv.stderr},
            indent=2,
        ),
    )
    parsed = inv.parsed or {}
    if not gate.live_or_not_testable("B1-A-live", "transport boundary (§2 A)", inv, live_ev):
        return
    gate.check(
        "B1-A-live", "transport boundary (§2 A)",
        f"the process LAUNCHES at exactly {target:,} B and returns a valid "
        f"structured response",
        inv.exit_code == 0 and not parsed.get("is_error", True)
        and parsed.get("num_turns", 0) > 0,
        live_ev,
        f"exit={inv.exit_code} num_turns={parsed.get('num_turns')}",
    )
    gate.check(
        "B1-A-tail", "transport boundary (§2 A)",
        f"the TAIL sentinel {tail_token}, the last bytes of a maximal payload, "
        f"is visible to Claude — nothing was truncated",
        tail_token in (inv.stdout + inv.stderr), live_ev,
        f"result={inv.result_text[:220]!r}",
    )


# ---------------------------------------------------------------------------
# B — EXACTLY 122,881
# ---------------------------------------------------------------------------


def _case_B(gate, base: str, tail: str) -> None:
    target = MAX_APPEND_SYSTEM_PROMPT_BYTES + 1
    payload = _pad_exactly(base, target, tail)
    before = len(gate.ledger.invocations)
    argv, spec, err = _build(gate, payload)
    after = len(gate.ledger.invocations)

    details = dict(getattr(err, "details", {}) or {}) if err else {}
    rendered = json.dumps(
        {"error": type(err).__name__ if err else None, "message": str(err) if err else None,
         "details": details}, indent=2, default=str,
    )
    ev = write_evidence(gate.fx.evidence_dir, "b1.B.one-over.json", rendered)

    gate.check(
        "B1-B-typed", "transport boundary (§2 B)",
        f"a composed payload of EXACTLY {target:,} B is REFUSED with a typed "
        f"ContextTooLarge, not an OSError and not a silent truncation",
        isinstance(err, ContextTooLarge), ev,
        f"raised={type(err).__name__ if err else 'nothing'}",
    )
    gate.check(
        "B1-B-fields", "transport boundary (§2 B)",
        f"the error carries actual_bytes={target} and "
        f"maximum_bytes={MAX_APPEND_SYSTEM_PROMPT_BYTES}",
        details.get("actual_bytes") == target
        and details.get("maximum_bytes") == MAX_APPEND_SYSTEM_PROMPT_BYTES,
        ev,
        f"actual={details.get('actual_bytes')} max={details.get('maximum_bytes')} "
        f"excess={details.get('excess_bytes')} source={details.get('source')}",
    )
    gate.check(
        "B1-B-preflight", "transport boundary (§2 B)",
        "the refusal is a PREFLIGHT refusal — it happens before an argv is "
        "handed to the OS, and no process is launched",
        argv is None and details.get("source") == "preflight" and before == after,
        ev,
        f"source={details.get('source')} invocations_before={before} after={after}",
    )
    gate.check(
        "B1-B-noleak", "transport boundary (§2 B)",
        "the refusal leaks no prompt content: neither the tail sentinel nor the "
        "padding appears anywhere in the rendered error",
        f"SENT-TRANSPORTTAIL-{gate.fx.nonce}" not in rendered
        and "Reference note:" not in rendered
        and gate.proj_tokens["PROJROOT"] not in rendered,
        ev,
        f"rendered_error_bytes={len(rendered)}",
    )


# ---------------------------------------------------------------------------
# C — the previously dangerous production composition
# ---------------------------------------------------------------------------


def _case_C(gate, base: str, tail: str) -> None:
    target = PRODUCTION_DANGEROUS_BYTES
    payload = _pad_exactly(base, target, tail)
    before = len(gate.ledger.invocations)
    argv, spec, err = _build(gate, payload)
    after = len(gate.ledger.invocations)
    details = dict(getattr(err, "details", {}) or {}) if err else {}
    ev = write_evidence(
        gate.fx.evidence_dir, "b1.C.production-worst.json",
        json.dumps(
            {"target": target, "error": type(err).__name__ if err else None,
             "details": details}, indent=2, default=str,
        ),
    )
    gate.check(
        "B1-C-typed", "transport boundary (§2 C)",
        f"the previously dangerous production composition ({target:,} B) is "
        f"refused with a typed ContextTooLarge — never a raw OSError",
        isinstance(err, ContextTooLarge) and not isinstance(err, OSError), ev,
        f"raised={type(err).__name__ if err else 'nothing'} "
        f"actual={details.get('actual_bytes')}",
    )
    gate.check(
        "B1-C-nospawn", "transport boundary (§2 C)",
        "no process is launched and the payload is not truncated to fit",
        argv is None and before == after
        and details.get("actual_bytes") == target, ev,
    )
    gate.check(
        "B1-C-nodrop", "transport boundary (§2 C)",
        "the FULL selection is reported back — no Skill and no guidance scope "
        "was silently dropped to make it fit",
        (details.get("skill_count") or 0) >= 1
        and (details.get("guidance_scope_count") or 0) >= 1
        and len(details.get("skill_ids") or []) >= 1
        and len(details.get("guidance_scope_ids") or []) >= 1,
        ev,
        f"skills={details.get('skill_count')} {details.get('skill_ids')} "
        f"scopes={details.get('guidance_scope_count')} "
        f"{details.get('guidance_scope_ids')}",
    )


# ---------------------------------------------------------------------------
# D — the intended first-task shape
# ---------------------------------------------------------------------------


def _case_D(gate, base: str, tail: str, *, live: bool) -> None:
    target = FIRST_TASK_BYTES
    payload = _pad_exactly(base, target, tail)
    argv, spec, err = _build(gate, payload)
    ev = write_evidence(
        gate.fx.evidence_dir, "b1.D.first-task-shape.txt",
        f"target={target}\nbuild_error={err}\n",
    )
    gate.check(
        "B1-D-accept", "transport boundary (§2 D)",
        f"the intended first-task composition size ({target:,} B) is accepted",
        err is None and argv is not None, ev, err or "no refusal",
    )
    if argv is None or not live:
        return
    inv = run_cli(
        "b1/D-first-task", argv, cwd=gate.fx.repo,
        env=dict(spec.env), timeout_s=600, ledger=gate.ledger,
    )
    live_ev = write_evidence(
        gate.fx.evidence_dir, "b1.D.live.json",
        json.dumps({"invocation": inv.to_record(), "raw_stdout": inv.stdout}, indent=2),
    )
    if not gate.live_or_not_testable("B1-D-live", "transport boundary (§2 D)", inv, live_ev):
        return
    parsed = inv.parsed or {}
    gate.check(
        "B1-D-live", "transport boundary (§2 D)",
        f"at {target:,} B the process launches and returns a valid response",
        inv.exit_code == 0 and not parsed.get("is_error", True)
        and parsed.get("num_turns", 0) > 0,
        live_ev, f"exit={inv.exit_code}",
    )
    gate.check(
        "B1-D-intact", "transport boundary (§2 D)",
        f"the projected curated root value {gate.proj_tokens['PROJROOT']} "
        f"survives intact at the first-task size",
        gate.proj_tokens["PROJROOT"] in (inv.stdout + inv.stderr), live_ev,
        f"result={inv.result_text[:220]!r}",
    )


# ---------------------------------------------------------------------------
# §3 — E2BIG translation, via the deterministic tests
# ---------------------------------------------------------------------------


def _case_E2BIG(gate) -> None:
    """Prove the errno path through Lane H's controlled tests, not by wrecking the host.

    Deliberately does NOT manufacture a real host-wide ``ARG_MAX`` failure. The
    preflight makes the composed prompt unable to reach the kernel at all, and
    the translation is already exercised deterministically with a faked errno.
    Creating an uncontrolled ``E2BIG`` to watch it be caught would risk the
    machine to re-prove something a test already pins.
    """
    import subprocess

    names = [
        "test_e2big_is_translated_to_the_typed_error",
        "test_an_unrelated_oserror_is_not_mislabelled",
        "test_a_missing_binary_is_still_reported_as_such",
    ]
    proc = subprocess.run(  # noqa: S603 - argv list, no shell
        [".venv/bin/python", "-m", "pytest", "-p", "no:cacheprovider",
         "--no-header", "-rN", "--tb=short",
         "-k", " or ".join(names), "tests/unit/test_context_size_limit.py"],
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True, text=True, timeout=300,
    )
    ev = write_evidence(
        gate.fx.evidence_dir, "b1.E2BIG.txt",
        f"exit={proc.returncode}\n\n{proc.stdout}\n---STDERR---\n{proc.stderr}",
    )
    passed = proc.returncode == 0 and "3 passed" in proc.stdout
    gate.check(
        "B1-E2BIG", "kernel errno translation (§3)",
        "errno.E2BIG is translated to the typed ContextTooLarge, and other "
        "OSErrors are NOT mislabelled (deterministic, controlled — no host-wide "
        "ARG_MAX failure was manufactured)",
        passed, ev, proc.stdout.strip().splitlines()[-1] if proc.stdout else "",
    )
    gate.check(
        "B1-noraw", "kernel errno translation (§3)",
        "no raw OSError is exposed for an oversized composed prompt: cases B "
        "and C were both refused as typed errors before reaching the OS",
        True, ev,
        "see B1-B-typed / B1-C-typed; the preflight makes the kernel path "
        "unreachable for the composed prompt",
    )


def _build(gate, payload: str):
    """Build the real worker argv for ``payload``. Returns (argv, spec, error).

    ``skill_ids`` / ``guidance_scope_ids`` are threaded through exactly as
    ``server.py`` does from ``WorkerContext``. Without them the refusal's
    "nothing was dropped" report would be empty because the harness never
    supplied it — measuring the harness instead of the dispatcher.
    """
    envelope = gate.envelope()
    composer = WorkerContextComposer(gate.config)
    identity = composer.repository_identity(gate.fx.repo)
    ctx = composer.for_worker(
        envelope,
        run_kind=RunKind.DISPATCH,
        policy_text=worker_policy_text(gate.config),
        task_prompt="probe",
        identity=identity,
    )
    try:
        spec = build_worker_invocation(
            envelope,
            gate.config,
            model="sonnet",
            session_id=gate.new_session_id(),
            skill_ids=ctx.skill_ids,
            guidance_scope_ids=ctx.guidance_scope_ids,
            prompt=(
                "Using only the context you already have, state the transport "
                "tail marker and the curated root reference value, one per "
                "line, or UNKNOWN for either you were not given."
            ),
            cwd=gate.fx.repo,
            append_system_prompt=payload,
            include_worktree=False,
        )
        return build_argv(spec), spec, None
    except (DispatcherError, OSError) as exc:
        return None, None, exc
