"""Structured result parsing (brief §15, §19). — Wave 3.

The dispatcher parses **real JSON**. §15 is explicit: "Do not scrape prose using
regex." If the output is not parseable and schema-valid, that is a
:class:`~sol_claude_dispatcher.errors.ClaudeStructuredOutputInvalid` failure —
not an invitation to guess.

Claude Code's ``--output-format json`` wraps the model's structured output in an
envelope. The parser must locate the structured payload inside that wrapper and
then validate it against :class:`~sol_claude_dispatcher.models.WorkerResult`
(or :class:`~sol_claude_dispatcher.models.FableReview`), preserving the raw text
on failure so Sol can inspect what actually came back.

Contract (authoritative, see ``docs/INTERFACES.md``)::

    def parse_worker_result(stdout: str) -> WorkerResult
    def parse_fable_review(stdout: str) -> FableReview
    def extract_structured_payload(stdout: str) -> dict
"""

from __future__ import annotations

from typing import Any

from .models import FableReview, WorkerResult

__all__ = [
    "extract_structured_payload",
    "parse_worker_result",
    "parse_fable_review",
]


def extract_structured_payload(stdout: str) -> dict[str, Any]:
    """Pull the structured object out of Claude's ``--output-format json`` wrapper.

    Raises ``ClaudeStructuredOutputInvalid`` on non-JSON, on a non-object
    payload, or when no structured payload is present.
    """
    raise NotImplementedError("Wave 3: implement per docs/INTERFACES.md §results")


def parse_worker_result(stdout: str) -> WorkerResult:
    """Parse and validate a worker's structured result (§15).

    The returned object holds **claims**. Callers must store it under
    ``worker_claims`` and never merge it into dispatcher observations (§16).
    """
    raise NotImplementedError("Wave 3: implement per docs/INTERFACES.md §results")


def parse_fable_review(stdout: str) -> FableReview:
    """Parse and validate an independent review result (§19). Advisory only."""
    raise NotImplementedError("Wave 3: implement per docs/INTERFACES.md §results")
