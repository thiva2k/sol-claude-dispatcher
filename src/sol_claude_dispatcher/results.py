"""Structured result parsing (brief §15, §16, §19). — Wave 3.

The dispatcher parses **real JSON**. §15 is explicit: "Do not scrape prose using
regex." If the output is not parseable and schema-valid, that is a
:class:`~sol_claude_dispatcher.errors.ClaudeStructuredOutputInvalid` failure —
not an invitation to guess.

Claude Code's ``--output-format json`` wraps the model's structured output in an
envelope. :func:`extract_structured_payload` locates the structured payload
inside that wrapper using the six-step resolution order below (authoritative,
``docs/INTERFACES.md`` §8), then :func:`parse_worker_result` /
:func:`parse_fable_review` validate it against the matching pydantic model —
the same contract as ``schemas/worker-result.schema.json`` /
``schemas/fable-review.schema.json``.

Resolution order for ``extract_structured_payload``:

1. ``json.loads(stdout)``. Failure (including empty stdout) →
   ``ClaudeStructuredOutputInvalid(details={"reason": "not_json", ...})``.
2. If the top-level value is not a JSON object →
   ``ClaudeStructuredOutputInvalid(details={"reason": "top_level_not_object", ...})``.
3. If it has a ``structured_output`` key holding an object, use it.
4. Else if it has a ``result`` key holding an object, use it.
5. Else if it has a ``result`` key holding a *string*, try ``json.loads`` on
   that string; if that yields an object, use it.
6. Else if the top-level object already looks like the target (has ``status``
   and ``summary`` for a worker result, or ``verdict`` for a review), use it
   directly.
7. Else → ``ClaudeStructuredOutputInvalid(details={"reason": "no_structured_payload", ...})``.

§16: the parsed worker result is a **claim**, never dispatcher evidence.
:func:`build_dispatcher_observations` assembles the *measured* half from git
evidence, scope checks and process facts — never from parsed worker output —
and the two are kept in permanently separate fields (``worker_claims`` /
``dispatcher_observations``) with zero shared field names (enforced by
``models.py`` and a test).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from .errors import ClaudeStructuredOutputInvalid
from .models import DispatcherObservations, FableReview, WorkerResult

if TYPE_CHECKING:
    from .git import DiffEvidence, ScopeCheck

__all__ = [
    "extract_structured_payload",
    "parse_worker_result",
    "parse_fable_review",
    "build_dispatcher_observations",
]

#: How much of the raw stdout is kept as diagnostic context on a parse
#: failure. Bounded so a runaway worker cannot balloon an error payload.
_STDOUT_HEAD_CHARS = 2000


def _validation_issues(exc: ValidationError) -> list[dict[str, str]]:
    """Compact issue list for a failed payload — never the raw pydantic dump."""
    issues = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"]) or "<root>"
        issues.append({"location": location, "problem": err["msg"]})
    return issues


def extract_structured_payload(stdout: str) -> dict[str, Any]:
    """Pull the structured object out of Claude's ``--output-format json`` wrapper.

    Raises ``ClaudeStructuredOutputInvalid`` on non-JSON (including empty
    stdout), on a non-object top-level payload, or when no structured payload
    can be located inside the envelope.
    """
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeStructuredOutputInvalid(
            "Claude's stdout was not valid JSON.",
            details={"reason": "not_json", "stdout_head": stdout[:_STDOUT_HEAD_CHARS]},
        ) from exc

    if not isinstance(parsed, dict):
        raise ClaudeStructuredOutputInvalid(
            "Claude's stdout parsed to JSON, but the top-level value is not an object.",
            details={
                "reason": "top_level_not_object",
                "top_level_type": type(parsed).__name__,
            },
        )

    structured_output = parsed.get("structured_output")
    if isinstance(structured_output, dict):
        return structured_output

    result = parsed.get("result")
    if isinstance(result, dict):
        return result

    if isinstance(result, str):
        try:
            inner = json.loads(result)
        except json.JSONDecodeError:
            inner = None
        if isinstance(inner, dict):
            return inner

    if ("status" in parsed and "summary" in parsed) or "verdict" in parsed:
        return parsed

    raise ClaudeStructuredOutputInvalid(
        "No structured payload found inside Claude's --output-format json envelope.",
        details={
            "reason": "no_structured_payload",
            "top_level_keys": sorted(parsed.keys()),
        },
    )


def parse_worker_result(stdout: str) -> WorkerResult:
    """Parse and validate a worker's structured result (§15).

    The returned object holds **claims**. Callers must store it under
    ``worker_claims`` and never merge it into dispatcher observations (§16).
    """
    payload = extract_structured_payload(stdout)
    try:
        return WorkerResult.model_validate(payload)
    except ValidationError as exc:
        raise ClaudeStructuredOutputInvalid(
            "Structured payload did not match the WorkerResult schema.",
            details={"reason": "schema_mismatch", "issues": _validation_issues(exc)},
        ) from exc


def parse_fable_review(stdout: str) -> FableReview:
    """Parse and validate an independent review result (§19). Advisory only."""
    payload = extract_structured_payload(stdout)
    try:
        return FableReview.model_validate(payload)
    except ValidationError as exc:
        raise ClaudeStructuredOutputInvalid(
            "Structured payload did not match the FableReview schema.",
            details={"reason": "schema_mismatch", "issues": _validation_issues(exc)},
        ) from exc


def build_dispatcher_observations(
    *,
    task_id: str,
    run_id: str,
    session_id: str,
    model: str,
    base_commit: str,
    duration_ms: int,
    exit_code: int | None,
    timed_out: bool,
    diff_evidence: "DiffEvidence",
    scope_check: "ScopeCheck",
    worker_result: WorkerResult | None,
    worker_result_error: str | None = None,
    primary_worktree_clean: bool | None = None,
) -> DispatcherObservations:
    """Assemble the dispatcher's *measured* evidence for one run (§16).

    Every field here comes from process control (``duration_ms``,
    ``exit_code``, ``timed_out``), git inspection (``diff_evidence``) or scope
    checking (``scope_check``) — never from parsed worker output.
    ``worker_result`` is consulted only to record whether parsing succeeded
    (``worker_result_parsed``); none of its fields are copied onto the
    returned object, so ``worker_claims`` and ``dispatcher_observations``
    never share data, matching the zero-shared-field-names guarantee §16
    requires of the two types.
    """
    diff_bytes = len(diff_evidence.diff_text.encode("utf-8", errors="replace"))
    return DispatcherObservations(
        task_id=task_id,
        run_id=run_id,
        session_id=session_id,
        model=model,
        base_commit=base_commit,
        duration_ms=duration_ms,
        exit_code=exit_code,
        timed_out=timed_out,
        changed_paths=list(diff_evidence.changed_paths),
        diff_stat=diff_evidence.diff_stat,
        diff_bytes=diff_bytes,
        scope_valid=scope_check.valid,
        out_of_scope_paths=list(scope_check.out_of_scope),
        forbidden_paths_touched=list(scope_check.forbidden),
        diff_check_passed=diff_evidence.diff_check_passed,
        worker_result_parsed=worker_result is not None,
        worker_result_error=worker_result_error,
        primary_worktree_clean=primary_worktree_clean,
    )
