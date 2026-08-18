"""Tests for deterministic model routing (brief §10, §31).

Written before ``router.py`` is implemented (TDD). These tests are the §31
routing matrix plus the extra guarantees the interface contract calls out:
model ids must come from config (never hardcoded), rule order must be exactly
the one documented in ``docs/INTERFACES.md``, and Fable must be unroutable for
implementation even if a config is somehow written to make that possible.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from sol_claude_dispatcher.config import Config, load_config_from_mapping
from sol_claude_dispatcher.errors import InternalDispatcherError
from sol_claude_dispatcher.models import (
    ESCALATING_TASK_KINDS,
    Complexity,
    RequestedModel,
    RiskLevel,
    TaskEnvelope,
    TaskKind,
    TaskRequest,
)
from sol_claude_dispatcher.router import explain_route, route

BASE_COMMIT = "a" * 40


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def router_config(tmp_path) -> Config:
    """A config with deliberately distinct, non-alias model ids.

    If ``router.py`` ever hardcodes "sonnet" / "opus" instead of reading
    ``config.models.*``, these tests fail loudly because the returned string
    would not match.
    """
    return load_config_from_mapping(
        {
            "dispatcher": {"state_dir": "./state"},
            "models": {
                "sonnet": "acme-sonnet-v9",
                "opus": "acme-opus-v9",
                "fable": "acme-fable-v9",
            },
            "routing": {"default_model": "sonnet"},
            "security": {
                "max_dispatch_depth": 1,
                "allowed_repository_roots": [str(tmp_path)],
            },
        },
        project_root=tmp_path,
    )


@pytest.fixture
def collided_fable_config(tmp_path) -> Config:
    """A pathological config where an implementer alias collides with Fable.

    Exists solely to exercise the runtime assertion in ``router.py``: even
    though the type system already prevents ``RequestedModel.FABLE`` from
    existing, a misconfigured ``[models]`` table could still make ``sonnet``
    or ``opus`` resolve to the same identifier as ``fable``. Routing must
    refuse rather than silently hand back the reviewer's model id.
    """
    return load_config_from_mapping(
        {
            "dispatcher": {"state_dir": "./state"},
            "models": {
                "sonnet": "shared-collided-id",
                "opus": "acme-opus-v9",
                "fable": "shared-collided-id",
            },
            "routing": {"default_model": "sonnet"},
            "security": {
                "max_dispatch_depth": 1,
                "allowed_repository_roots": [str(tmp_path)],
            },
        },
        project_root=tmp_path,
    )


def _envelope(
    valid_request_dict: dict,
    git_repo,
    *,
    routing: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
) -> TaskEnvelope:
    payload = copy.deepcopy(valid_request_dict)
    if routing:
        payload["routing"] = {**payload.get("routing", {}), **routing}
    if task:
        payload["task"] = {**payload["task"], **task}
    request = TaskRequest(**payload)
    return TaskEnvelope.from_request(
        request, canonical_root=str(git_repo), base_commit=BASE_COMMIT
    )


# ---------------------------------------------------------------------------
# §31 routing matrix
# ---------------------------------------------------------------------------


def test_low_risk_medium_complexity_routes_sonnet(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "medium", "risk": "low"},
        task={"kind": "implementation"},
    )
    assert route(env, router_config) == router_config.models.sonnet


def test_medium_risk_medium_complexity_routes_sonnet(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "medium", "risk": "medium"},
        task={"kind": "implementation"},
    )
    assert route(env, router_config) == router_config.models.sonnet


def test_high_complexity_routes_opus(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "high", "risk": "low"},
        task={"kind": "implementation"},
    )
    assert route(env, router_config) == router_config.models.opus


def test_high_risk_routes_opus(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "medium", "risk": "high"},
        task={"kind": "implementation"},
    )
    assert route(env, router_config) == router_config.models.opus


def test_critical_risk_routes_opus(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "medium", "risk": "critical"},
        task={"kind": "implementation"},
    )
    assert route(env, router_config) == router_config.models.opus


def test_explicit_sonnet_beats_high_risk(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "sonnet", "complexity": "high", "risk": "critical"},
        task={"kind": "security_sensitive"},
    )
    assert route(env, router_config) == router_config.models.sonnet


def test_explicit_opus_with_low_risk_routes_opus(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "opus", "complexity": "low", "risk": "low"},
        task={"kind": "docs"},
    )
    assert route(env, router_config) == router_config.models.opus


@pytest.mark.parametrize("kind", sorted(ESCALATING_TASK_KINDS, key=lambda k: k.value))
def test_each_escalating_kind_routes_opus(valid_request_dict, git_repo, router_config, kind):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "low", "risk": "low"},
        task={"kind": kind.value},
    )
    assert route(env, router_config) == router_config.models.opus


def test_non_escalating_kind_with_low_risk_and_complexity_routes_sonnet(
    valid_request_dict, git_repo, router_config
):
    for kind in (
        TaskKind.IMPLEMENTATION,
        TaskKind.BUGFIX,
        TaskKind.REFACTOR,
        TaskKind.TESTS,
        TaskKind.DOCS,
    ):
        env = _envelope(
            valid_request_dict,
            git_repo,
            routing={"model": "auto", "complexity": "low", "risk": "low"},
            task={"kind": kind.value},
        )
        assert route(env, router_config) == router_config.models.sonnet, kind


def test_fable_never_returned_for_any_input_combination(valid_request_dict, git_repo, router_config):
    for requested in RequestedModel:
        for complexity in Complexity:
            for risk in RiskLevel:
                for kind in TaskKind:
                    env = _envelope(
                        valid_request_dict,
                        git_repo,
                        routing={
                            "model": requested.value,
                            "complexity": complexity.value,
                            "risk": risk.value,
                        },
                        task={"kind": kind.value},
                    )
                    model = route(env, router_config)
                    assert model != router_config.models.fable
                    assert model in {router_config.models.sonnet, router_config.models.opus}


def test_requested_model_enum_has_no_fable_member():
    # Belt-and-braces: the type system already makes RequestedModel.FABLE
    # inexpressible. This just documents and pins that fact.
    assert "fable" not in {m.value for m in RequestedModel}
    assert not hasattr(RequestedModel, "FABLE")


# ---------------------------------------------------------------------------
# Rule ordering / precedence
# ---------------------------------------------------------------------------


def test_explicit_request_beats_escalating_kind(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "sonnet", "complexity": "high", "risk": "critical"},
        task={"kind": "concurrency"},
    )
    assert route(env, router_config) == router_config.models.sonnet


def test_risk_beats_complexity_and_kind_when_both_would_pick_opus_anyway(
    valid_request_dict, git_repo, router_config
):
    # Risk fires before complexity/kind are even inspected; since all three
    # point at opus here the observable result can't distinguish them, but
    # explain_route's reason string proves risk fired first (see below).
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "high", "risk": "high"},
        task={"kind": "migration"},
    )
    model, reason = explain_route(env, router_config)
    assert model == router_config.models.opus
    assert reason == "risk:high"


def test_complexity_beats_kind_when_risk_is_low(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "high", "risk": "low"},
        task={"kind": "migration"},
    )
    model, reason = explain_route(env, router_config)
    assert model == router_config.models.opus
    assert reason == "complexity:high"


# ---------------------------------------------------------------------------
# explain_route reason strings
# ---------------------------------------------------------------------------


def test_explain_route_reason_explicit_sonnet(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "sonnet", "complexity": "low", "risk": "low"},
        task={"kind": "implementation"},
    )
    model, reason = explain_route(env, router_config)
    assert model == router_config.models.sonnet
    assert reason == "explicit_request:sonnet"


def test_explain_route_reason_explicit_opus(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "opus", "complexity": "low", "risk": "low"},
        task={"kind": "implementation"},
    )
    model, reason = explain_route(env, router_config)
    assert model == router_config.models.opus
    assert reason == "explicit_request:opus"


def test_explain_route_reason_risk_critical(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "low", "risk": "critical"},
        task={"kind": "implementation"},
    )
    model, reason = explain_route(env, router_config)
    assert model == router_config.models.opus
    assert reason == "risk:critical"


def test_explain_route_reason_kind(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "low", "risk": "low"},
        task={"kind": "deep_debugging"},
    )
    model, reason = explain_route(env, router_config)
    assert model == router_config.models.opus
    assert reason == "kind:deep_debugging"


def test_explain_route_reason_default(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "medium", "risk": "medium"},
        task={"kind": "implementation"},
    )
    model, reason = explain_route(env, router_config)
    assert model == router_config.models.sonnet
    assert reason == "default"


def test_route_and_explain_route_agree_on_model(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "high", "risk": "high"},
        task={"kind": "implementation"},
    )
    assert route(env, router_config) == explain_route(env, router_config)[0]


# ---------------------------------------------------------------------------
# Model ids come from config, never hardcoded
# ---------------------------------------------------------------------------


def test_model_ids_come_from_config_not_hardcoded(valid_request_dict, git_repo, router_config):
    """router_config uses non-standard model ids; a hardcoded "sonnet"/"opus"
    string anywhere in router.py would make these assertions fail."""
    sonnet_env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "sonnet", "complexity": "low", "risk": "low"},
        task={"kind": "implementation"},
    )
    opus_env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "opus", "complexity": "low", "risk": "low"},
        task={"kind": "implementation"},
    )
    assert route(sonnet_env, router_config) == "acme-sonnet-v9"
    assert route(opus_env, router_config) == "acme-opus-v9"
    assert route(sonnet_env, router_config) != "sonnet"
    assert route(opus_env, router_config) != "opus"


# ---------------------------------------------------------------------------
# Runtime assertion: Fable must be unroutable even under a colliding config
# ---------------------------------------------------------------------------


def test_route_refuses_when_selected_model_collides_with_fable(
    valid_request_dict, git_repo, collided_fable_config
):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "medium", "risk": "medium"},
        task={"kind": "implementation"},
    )
    # default -> sonnet -> which in this config equals fable's id.
    with pytest.raises(InternalDispatcherError):
        route(env, collided_fable_config)


def test_explain_route_refuses_when_explicit_sonnet_collides_with_fable(
    valid_request_dict, git_repo, collided_fable_config
):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "sonnet", "complexity": "low", "risk": "low"},
        task={"kind": "implementation"},
    )
    with pytest.raises(InternalDispatcherError):
        explain_route(env, collided_fable_config)


def test_route_still_works_for_the_non_colliding_model(
    valid_request_dict, git_repo, collided_fable_config
):
    # opus does not collide with fable in this config, so it must still route.
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "opus", "complexity": "low", "risk": "low"},
        task={"kind": "implementation"},
    )
    assert route(env, collided_fable_config) == "acme-opus-v9"


# ---------------------------------------------------------------------------
# Purity: no I/O, deterministic, no envelope/config mutation
# ---------------------------------------------------------------------------


def test_route_is_pure_and_deterministic(valid_request_dict, git_repo, router_config):
    env = _envelope(
        valid_request_dict,
        git_repo,
        routing={"model": "auto", "complexity": "high", "risk": "high"},
        task={"kind": "implementation"},
    )
    before = env.model_dump()
    results = {route(env, router_config) for _ in range(10)}
    assert results == {router_config.models.opus}
    assert env.model_dump() == before
