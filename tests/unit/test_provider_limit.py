"""B3 — provider usage-limit / 429 classification.

Production task ``c5e385c9-7c71-458c-81d6-a809371d1437`` died of an HTTP 429
weekly account usage limit. The Claude CLI wrapped the provider's prose in its
normal ``--output-format json`` envelope, exited **0**, and set three trusted
envelope fields::

    is_error: true    terminal_reason: "api_error"    api_error_status: 429

The dispatcher never looked at any of them. ``extract_structured_payload`` found
no structured payload, raised ``ClaudeStructuredOutputInvalid``, and the task
landed ``FAILED / unparseable_worker_result`` — a verdict that is literally true
and diagnostically wrong: it blames the model's output schema for an upstream
quota exhaustion the dispatcher had been told about in a machine-readable field.

The taxonomy these tests pin has five distinct outcomes:

===========================  ==========================================
outcome                      trusted evidence it is decided from
===========================  ==========================================
valid structured response    a parseable, schema-valid payload
schema / output failure      ``ClaudeStructuredOutputInvalid``
execution / process failure  exit status + empty stdout (``cli_failure``)
timeout                      ``WorkerRun.timed_out`` (process control)
provider usage / rate limit  ``api_error_status`` / ``terminal_reason``
                             read from the CLI's own result envelope
===========================  ==========================================

**The classification never reads model-generated text.** A worker that writes
"429" or "rate limit" into its summary, its prose result, or its structured
payload must not be able to make the dispatcher report a provider limit — there
are direct tests for every one of those spoofs below.

Fixture provenance
------------------

``tests/fixtures/claude_429_usage_limit_envelope.json`` is the **real**
``runs/001/stdout.json`` from task ``c5e385c9``, read-only, byte-faithful apart
from two opaque identifiers: ``session_id`` and ``uuid`` were replaced with
synthetic UUIDs. Nothing else was altered, nothing was removed, and the file
carries no credential, no path, no prompt and no repository content — the
provider's own message ("You've hit your weekly limit ...") is preserved
verbatim because it is exactly what an operator needs to see.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import (
    ERROR_CODES,
    ClaudeExecutionFailed,
    ClaudeProviderLimit,
    ClaudeStructuredOutputInvalid,
)
from sol_claude_dispatcher.results import parse_worker_result
from sol_claude_dispatcher.runner import (
    PROVIDER_MESSAGE_CHARS,
    WorkerRun,
    cli_failure,
    envelope_facts,
    provider_failure,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REAL_429_ENVELOPE = FIXTURES / "claude_429_usage_limit_envelope.json"
GATE_DIR = Path(__file__).resolve().parents[2] / "scripts" / "gate"


def _run(**overrides) -> WorkerRun:
    fields = {
        "argv": ["claude", "-p", "--model", "sonnet"],
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "duration_ms": 553899,
    }
    fields.update(overrides)
    return WorkerRun(**fields)  # type: ignore[arg-type]


def _envelope(**overrides) -> str:
    """A well-formed CLI result envelope carrying a valid worker payload."""
    payload = {
        "status": "completed",
        "summary": "Implemented the thing.",
        "changes": [],
        "acceptance_criteria": [],
        "tests": [],
        "risks": [],
        "blockers": [],
        "needs_review": True,
    }
    envelope = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 12,
        "num_turns": 3,
        "session_id": "00000000-0000-4000-8000-000000000000",
        "total_cost_usd": 0.5,
        "result": "run complete",
        "structured_output": payload,
    }
    envelope.update(overrides)
    return json.dumps(envelope)


def _limit_envelope(**overrides) -> str:
    envelope = json.loads(REAL_429_ENVELOPE.read_text())
    envelope.update(overrides)
    return json.dumps(envelope)


# ---------------------------------------------------------------------------
# 1. The real c5e385c9 shape
# ---------------------------------------------------------------------------


def test_real_429_envelope_classifies_as_a_provider_limit():
    run = _run(exit_code=0, stdout=REAL_429_ENVELOPE.read_text())

    error = provider_failure(run, binary="/usr/bin/claude", role="implementer")

    assert error is not None
    assert isinstance(error, ClaudeProviderLimit)
    assert error.code == "ClaudeProviderLimit"
    assert error.details["api_error_status"] == 429
    assert error.details["terminal_reason"] == "api_error"


def test_the_real_shape_is_never_a_structured_output_defect():
    """The exact regression: a provider limit must not be a schema verdict."""
    run = _run(exit_code=0, stdout=REAL_429_ENVELOPE.read_text())

    error = provider_failure(run, binary="/usr/bin/claude", role="implementer")

    assert not isinstance(error, ClaudeStructuredOutputInvalid)
    assert error.code != "ClaudeStructuredOutputInvalid"
    # And the old path really would have said exactly that, which is why the
    # classifier has to run first.
    with pytest.raises(ClaudeStructuredOutputInvalid):
        parse_worker_result(REAL_429_ENVELOPE.read_text())


def test_exit_zero_with_an_api_error_is_still_classified():
    """``cli_failure`` returns None here — exit 0 — so nothing else catches it."""
    run = _run(exit_code=0, stdout=REAL_429_ENVELOPE.read_text())

    assert cli_failure(run, binary="/usr/bin/claude", role="implementer") is None
    error = provider_failure(run, binary="/usr/bin/claude", role="implementer")
    assert error is not None
    assert error.details["exit_code"] == 0


def test_provider_limit_is_retryable_and_in_the_taxonomy():
    assert "ClaudeProviderLimit" in ERROR_CODES
    assert ClaudeProviderLimit.retryable is True
    error = ClaudeProviderLimit("limit", details={"api_error_status": 429})
    assert error.to_payload()["retryable"] is True
    assert error.to_payload()["error"] == "ClaudeProviderLimit"


def test_the_zero_token_signature_is_preserved_for_the_operator():
    """Gate 4.5's trap keys off a well-formed envelope with no real work."""
    run = _run(exit_code=0, stdout=REAL_429_ENVELOPE.read_text())

    error = provider_failure(run, binary="/usr/bin/claude", role="implementer")

    assert error.details["is_error"] is True
    assert error.details["num_turns"] == 53
    assert error.details["usage"]["output_tokens"] == 14545
    assert "resets" in error.details["provider_message"]


# ---------------------------------------------------------------------------
# 2. Never from model-generated text
# ---------------------------------------------------------------------------


def test_a_model_writing_429_in_its_summary_does_not_trigger_the_classification():
    payload = {
        "status": "completed",
        "summary": "Handled HTTP 429 rate limit retries in the client.",
        "changes": [],
        "acceptance_criteria": [],
        "tests": [],
        "risks": ["api_error_status 429 may still leak through"],
        "blockers": [],
        "needs_review": True,
    }
    stdout = _envelope(
        structured_output=payload,
        result="I hit a 429 rate limit while testing; terminal_reason api_error.",
    )
    run = _run(exit_code=0, stdout=stdout)

    assert provider_failure(run, binary="/usr/bin/claude", role="implementer") is None
    # It is a perfectly good run and still parses as one.
    assert parse_worker_result(stdout).status.value == "completed"


def test_a_model_payload_spoofing_envelope_fields_does_not_trigger():
    """The payload is model output even when it apes the envelope's shape."""
    spoof = {
        "status": "completed",
        "summary": "done",
        "changes": [],
        "acceptance_criteria": [],
        "tests": [],
        "risks": [],
        "blockers": [],
        "needs_review": True,
        "api_error_status": 429,
        "terminal_reason": "api_error",
        "is_error": True,
        "type": "result",
    }
    run = _run(exit_code=0, stdout=json.dumps(spoof))

    assert provider_failure(run, binary="/usr/bin/claude", role="implementer") is None


def test_a_nested_structured_output_claiming_429_does_not_trigger():
    stdout = _envelope(
        structured_output={
            "status": "completed",
            "summary": "s",
            "changes": [],
            "acceptance_criteria": [],
            "tests": [],
            "risks": [],
            "blockers": [],
            "needs_review": True,
            "api_error_status": 429,
            "terminal_reason": "api_error",
        }
    )
    run = _run(exit_code=0, stdout=stdout)

    assert provider_failure(run, binary="/usr/bin/claude", role="implementer") is None


def test_prose_stdout_naming_429_does_not_trigger():
    run = _run(exit_code=0, stdout="I give up: the API returned 429 rate limit.\n")

    assert provider_failure(run, binary="/usr/bin/claude", role="implementer") is None
    assert envelope_facts(run) is None


def test_a_bare_json_object_the_model_printed_is_not_an_envelope():
    """The payload veto is not the only door: an arbitrary JSON object that is
    neither a worker result nor a review must not be read as a CLI envelope
    either. ``--output-format json`` always wraps, so anything that does not
    identify itself as the CLI's own result object is model output.
    """
    printed = {
        "api_error_status": 429,
        "terminal_reason": "api_error",
        "is_error": True,
        "note": "the model printed this JSON as its answer",
    }
    run = _run(exit_code=0, stdout=json.dumps(printed))

    assert envelope_facts(run) is None
    assert provider_failure(run, binary="/usr/bin/claude", role="implementer") is None


def test_one_envelope_marker_alone_does_not_make_an_envelope():
    """A single coincidental key is not identification. Two are required, and
    the real CLI supplies ``type: "result"`` plus nine of them."""
    one_marker = {"api_error_status": 429, "terminal_reason": "api_error", "num_turns": 4}
    run = _run(exit_code=0, stdout=json.dumps(one_marker))

    assert envelope_facts(run) is None
    assert provider_failure(run, binary="/usr/bin/claude", role="implementer") is None

    # Positive control: the gate opens for a genuine unlabelled envelope, so
    # the classifier does not depend on ``type`` being present.
    two_markers = dict(one_marker, session_id="s", total_cost_usd=0.2)
    run = _run(exit_code=0, stdout=json.dumps(two_markers))

    assert envelope_facts(run) is not None
    assert isinstance(
        provider_failure(run, binary="/usr/bin/claude", role="implementer"),
        ClaudeProviderLimit,
    )


def test_a_string_shaped_status_from_the_model_is_not_an_envelope():
    """A bare JSON string or list is not an envelope, whatever it says."""
    for stdout in ('"api_error_status 429"', '[{"api_error_status": 429}]', "429"):
        run = _run(exit_code=0, stdout=stdout)
        assert envelope_facts(run) is None
        assert provider_failure(run, binary="/usr/bin/claude", role="x") is None


# ---------------------------------------------------------------------------
# 3. The other four outcomes stay distinct
# ---------------------------------------------------------------------------


def test_a_valid_response_is_not_a_provider_limit():
    stdout = _envelope()
    run = _run(exit_code=0, stdout=stdout)

    assert provider_failure(run, binary="/usr/bin/claude", role="implementer") is None
    assert cli_failure(run, binary="/usr/bin/claude", role="implementer") is None
    assert parse_worker_result(stdout).status.value == "completed"


def test_a_schema_failure_is_still_a_structured_output_defect():
    stdout = _envelope(structured_output={"status": "completed"})  # no summary
    run = _run(exit_code=0, stdout=stdout)

    assert provider_failure(run, binary="/usr/bin/claude", role="implementer") is None
    with pytest.raises(ClaudeStructuredOutputInvalid) as excinfo:
        parse_worker_result(stdout)
    assert excinfo.value.details["reason"] == "schema_mismatch"


def test_a_process_failure_is_still_an_execution_failure():
    run = _run(exit_code=2, stdout="", stderr="claude native binary not installed\n")

    assert provider_failure(run, binary="/usr/bin/claude", role="implementer") is None
    error = cli_failure(run, binary="/usr/bin/claude", role="implementer")
    assert error is not None
    assert error.code == "ClaudeExecutionFailed"


def test_a_timeout_is_never_a_provider_limit():
    """Even holding a complete 429 envelope: a killed run is a timeout."""
    run = _run(
        exit_code=None,
        timed_out=True,
        killed_with_sigkill=True,
        stdout=REAL_429_ENVELOPE.read_text(),
    )

    assert provider_failure(run, binary="/usr/bin/claude", role="implementer") is None
    assert envelope_facts(run) is None


def test_a_run_that_never_started_is_never_a_provider_limit():
    run = _run(exit_code=None, start_failed=True, stdout=REAL_429_ENVELOPE.read_text())

    assert provider_failure(run, binary="/usr/bin/claude", role="implementer") is None


def test_a_non_limit_api_error_is_an_execution_failure_not_a_limit():
    """A 500 is a provider fault, but it is not a usage limit — and it is
    still not a model-output defect."""
    run = _run(exit_code=0, stdout=_limit_envelope(api_error_status=500))

    error = provider_failure(run, binary="/usr/bin/claude", role="implementer")

    assert error is not None
    assert not isinstance(error, ClaudeProviderLimit)
    assert isinstance(error, ClaudeExecutionFailed)
    assert error.details["reason"] == "provider_api_error"
    assert error.details["api_error_status"] == 500


def test_an_explicit_usage_limit_terminal_reason_is_a_limit_without_a_status():
    run = _run(
        exit_code=0,
        stdout=_limit_envelope(api_error_status=None, terminal_reason="usage_limit"),
    )

    error = provider_failure(run, binary="/usr/bin/claude", role="implementer")

    assert isinstance(error, ClaudeProviderLimit)


def test_a_completed_terminal_reason_is_not_an_api_error():
    run = _run(exit_code=0, stdout=_envelope(terminal_reason="completed"))

    assert provider_failure(run, binary="/usr/bin/claude", role="implementer") is None


# ---------------------------------------------------------------------------
# 4. Bounded, redacted diagnostics
# ---------------------------------------------------------------------------


SECRET = "ANTHROPIC_API_KEY=sk-ant-supersecret-value-0123456789"
PROMPT = "TASK OBJECTIVE: rewrite the billing ledger. " * 200


def test_the_provider_message_is_bounded_and_redacted():
    run = _run(
        exit_code=0,
        stdout=_limit_envelope(result=f"You've hit your weekly limit. {SECRET} " + "x" * 5000),
        argv=["claude", "-p", "--append-system-prompt", PROMPT, SECRET, PROMPT],
        stderr=SECRET,
    )

    error = provider_failure(run, binary="/usr/bin/claude", role="implementer")

    message = error.details["provider_message"]
    assert len(message) <= PROVIDER_MESSAGE_CHARS
    assert "sk-ant-supersecret-value" not in message
    assert "***REDACTED***" in message


def test_details_never_carry_the_prompt_the_argv_or_a_secret():
    run = _run(
        exit_code=0,
        stdout=_limit_envelope(result=f"weekly limit reached {SECRET}"),
        argv=["claude", "-p", "--append-system-prompt", PROMPT, SECRET],
        stderr=f"{SECRET}\n{PROMPT}",
    )

    error = provider_failure(run, binary="/usr/bin/claude", role="implementer")
    blob = json.dumps(error.to_payload(), default=str)

    assert "sk-ant-supersecret-value" not in blob
    assert "rewrite the billing ledger" not in blob
    assert "--append-system-prompt" not in blob


def test_the_whole_payload_stays_small_whatever_the_envelope_carried():
    """§29: an error crossing the MCP boundary is short. Never a raw dump."""
    noisy = _limit_envelope(
        result="R" * 100_000,
        stop_reason="S" * 50_000,
        modelUsage={f"model-{i}": {"inputTokens": i} for i in range(500)},
        terminal_reason="api_error" + "!" * 10_000,
    )
    run = _run(exit_code=0, stdout=noisy)

    error = provider_failure(run, binary="/usr/bin/claude", role="implementer")
    blob = json.dumps(error.to_payload(), default=str)

    assert len(blob) < 4000
    assert "R" * 1000 not in blob
    assert len(error.details["terminal_reason"]) <= 64


def test_details_hold_only_the_whitelisted_diagnostic_keys():
    run = _run(exit_code=0, stdout=REAL_429_ENVELOPE.read_text())

    error = provider_failure(run, binary="/usr/bin/claude", role="implementer")

    assert set(error.details) == {
        "binary",
        "role",
        "reason",
        "exit_code",
        "is_error",
        "api_error_status",
        "terminal_reason",
        "subtype",
        "num_turns",
        "total_cost_usd",
        "usage",
        "provider_message",
    }
    assert set(error.details["usage"]) == {
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    }


def test_envelope_facts_exposes_only_trusted_scalars():
    run = _run(exit_code=0, stdout=REAL_429_ENVELOPE.read_text())

    facts = envelope_facts(run)

    assert facts["api_error_status"] == 429
    assert facts["terminal_reason"] == "api_error"
    assert facts["is_error"] is True
    # The model's own payload is never surfaced through this door.
    assert "structured_output" not in facts
    assert "modelUsage" not in facts


# ---------------------------------------------------------------------------
# 5. The Gate 4.5 live-harness rule still stands (read-only assertion)
# ---------------------------------------------------------------------------


def test_the_gate_harness_still_refuses_to_score_a_429_run():
    """A usage-limit response must never be a PASS or suppression evidence.

    Owned by the gate lane; asserted here only so B3 cannot be read as licence
    to soften it. Deliberately tolerant of wording and of which gate module
    holds the trap.
    """
    sources = [p.read_text(encoding="utf-8") for p in sorted(GATE_DIR.glob("*.py"))]
    assert sources, "scripts/gate carries no python modules"
    trapped = [
        text
        for text in sources
        if "api_error_status" in text and "not_testable" in text
    ]
    assert trapped, "no gate module still treats an api_error_status run as NOT-TESTABLE"
