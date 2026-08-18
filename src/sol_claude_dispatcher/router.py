"""Deterministic model routing (brief §10). — Wave 2.

Pure function, no I/O, no randomness, no LLM. Given the same envelope and the
same config it must always return the same model identifier.

Contract (authoritative, see ``docs/INTERFACES.md``)::

    def route(envelope: TaskEnvelope, config: Config) -> str
    def explain_route(envelope: TaskEnvelope, config: Config) -> tuple[str, str]

Rules, evaluated in this exact order, first match wins:

1. ``routing.requested_model == "sonnet"``  -> ``config.models.sonnet``
2. ``routing.requested_model == "opus"``    -> ``config.models.opus``
3. ``routing.risk in {high, critical}``     -> ``config.models.opus``
4. ``routing.complexity == "high"``         -> ``config.models.opus``
5. ``task.kind`` in ``ESCALATING_TASK_KINDS`` -> ``config.models.opus``
6. otherwise                                -> ``config.models.sonnet``

Model identifiers are read exclusively from ``config.models`` (§10: "Do not
spread model IDs throughout source files") — never a literal ``"sonnet"`` or
``"opus"`` string.

Fable is never returned by this function under any input. ``RequestedModel``
has no ``fable`` member, so an explicit request for it fails validation before
routing is ever reached (§10: "Never automatically route implementation to
Fable"). That is enforced by the type system; the runtime assertion below is
belt-and-braces in case a misconfigured ``[models]`` table makes ``sonnet`` or
``opus`` resolve to the same identifier as ``fable`` — in that case routing
must refuse rather than silently handing back the reviewer's model id.
"""

from __future__ import annotations

from .config import Config
from .errors import InternalDispatcherError
from .models import (
    ESCALATING_TASK_KINDS,
    Complexity,
    RequestedModel,
    RiskLevel,
    TaskEnvelope,
)

__all__ = ["route", "explain_route"]

#: Risk levels that force escalation to the stronger model (rule 3).
_ESCALATING_RISK: frozenset[RiskLevel] = frozenset({RiskLevel.HIGH, RiskLevel.CRITICAL})


def explain_route(envelope: TaskEnvelope, config: Config) -> tuple[str, str]:
    """Select a model id and name the rule that produced it.

    ``reason`` is a short, stable string suitable for storing verbatim in
    ``TaskRecord.state_history`` so a routing decision is auditable after the
    fact: ``"explicit_request:opus"``, ``"risk:high"``, ``"complexity:high"``,
    ``"kind:concurrency"``, ``"default"``.
    """
    routing = envelope.routing

    if routing.requested_model is RequestedModel.SONNET:
        model, reason = config.models.sonnet, "explicit_request:sonnet"
    elif routing.requested_model is RequestedModel.OPUS:
        model, reason = config.models.opus, "explicit_request:opus"
    elif routing.risk in _ESCALATING_RISK:
        model, reason = config.models.opus, f"risk:{routing.risk.value}"
    elif routing.complexity is Complexity.HIGH:
        model, reason = config.models.opus, "complexity:high"
    elif envelope.task.kind in ESCALATING_TASK_KINDS:
        model, reason = config.models.opus, f"kind:{envelope.task.kind.value}"
    else:
        model, reason = config.models.sonnet, "default"

    # Runtime assertion (defence in depth): RequestedModel has no FABLE
    # member, so rules 1/2 can never select Fable directly. But nothing stops
    # a misconfigured [models] table from making "sonnet" or "opus" resolve
    # to the same string as "fable". Fail closed rather than silently
    # dispatching an implementation task to the reviewer model (§10).
    fable_model = config.model_for("fable")
    if model == fable_model:
        raise InternalDispatcherError(
            "Routing selected the Fable model identifier for an "
            "implementation task; Fable may never be routed as an "
            "implementer (§10).",
            details={"reason": reason, "model": model},
            remediation="Configure distinct [models] values for sonnet, "
            "opus and fable.",
        )

    return model, reason


def route(envelope: TaskEnvelope, config: Config) -> str:
    """Select the configured model identifier for an implementation task."""
    model, _reason = explain_route(envelope, config)
    return model
