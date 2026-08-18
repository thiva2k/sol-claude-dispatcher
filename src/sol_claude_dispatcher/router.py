"""Deterministic model routing (brief §10). — Wave 2.

Pure function, no I/O, no randomness, no LLM. Given the same envelope and the
same config it must always return the same model identifier.

Contract (authoritative, see ``docs/INTERFACES.md``)::

    def route(envelope: TaskEnvelope, config: Config) -> str

Rules, evaluated in this exact order:

1. ``routing.requested_model == "sonnet"``  -> ``config.models.sonnet``
2. ``routing.requested_model == "opus"``    -> ``config.models.opus``
3. ``routing.risk in {high, critical}``     -> ``config.models.opus``
4. ``routing.complexity == "high"``         -> ``config.models.opus``
5. ``task.kind`` in ``ESCALATING_TASK_KINDS`` -> ``config.models.opus``
6. otherwise                                -> ``config.models.sonnet``

Fable is never returned by this function under any input. ``RequestedModel``
has no ``fable`` member, so an explicit request for it fails validation before
routing is ever reached (§10: "Never automatically route implementation to
Fable").
"""

from __future__ import annotations

from .config import Config
from .models import TaskEnvelope

__all__ = ["route", "explain_route"]


def route(envelope: TaskEnvelope, config: Config) -> str:
    """Select the configured model identifier for an implementation task."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §router")


def explain_route(envelope: TaskEnvelope, config: Config) -> tuple[str, str]:
    """Return ``(model, reason)`` where ``reason`` names the rule that fired.

    The reason string is recorded in task state so a routing decision is
    auditable after the fact.
    """
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §router")
