"""Run, cumulative, and validation scope decisions for Gate 7."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Mapping

from .attribution import WorkerAttribution
from .inventory import (
    PathIdentitySet,
    RepoPath,
    ScopeSpecBytes,
    ScopeVerdict,
    decide_scope,
)


def _ordered_paths(*groups: tuple[RepoPath, ...]) -> tuple[RepoPath, ...]:
    return tuple(sorted(set().union(*groups), key=bytes))


def _display(paths: tuple[RepoPath, ...]) -> list[str]:
    return [os.fsdecode(bytes(path)) for path in paths]


@dataclass(frozen=True)
class ScopeVerdictSet:
    """The three non-interchangeable scope verdicts for one worker run."""

    run_identity: PathIdentitySet
    cumulative_identity: PathIdentitySet
    validation_identity: PathIdentitySet
    run_worker: ScopeVerdict
    cumulative_worker: ScopeVerdict
    validation: ScopeVerdict

    @property
    def outside_allowed(self) -> tuple[RepoPath, ...]:
        # allowed_paths constrains workers, never dispatcher-owned validation.
        return _ordered_paths(
            self.run_worker.outside_allowed,
            self.cumulative_worker.outside_allowed,
        )

    @property
    def forbidden_hits(self) -> tuple[RepoPath, ...]:
        # forbidden_paths constrains every author, including validation.
        return _ordered_paths(
            self.run_worker.forbidden_hits,
            self.cumulative_worker.forbidden_hits,
            self.validation.forbidden_hits,
        )

    @property
    def valid(self) -> bool:
        return not self.outside_allowed and not self.forbidden_hits

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "inputs": {
                "run_worker": self.run_identity.to_dict(),
                "cumulative_worker": self.cumulative_identity.to_dict(),
                "validation": self.validation_identity.to_dict(),
            },
            "run_worker": self.run_worker.to_dict(),
            "cumulative_worker": self.cumulative_worker.to_dict(),
            "validation": self.validation.to_dict(),
            "aggregate": {
                "valid": self.valid,
                "outside_allowed": _display(self.outside_allowed),
                "forbidden_hits": _display(self.forbidden_hits),
            },
            "validation_attributed_forbidden": _display(
                self.validation.forbidden_hits
            ),
        }


def decide_scope_verdicts(
    *,
    prior_cumulative_worker: PathIdentitySet | None,
    attribution: WorkerAttribution,
    scope: ScopeSpecBytes,
    base_commit: str,
) -> ScopeVerdictSet:
    """Decide current worker, cumulative worker, and validation policy.

    A resume's run delta cannot erase a prior forbidden or out-of-scope path:
    cumulative policy is updated from the persisted history of worker deltas.
    It is deliberately *not* reconstructed as initial START to the current
    worker terminal, because that interval contains outputs produced by prior
    validation runs. Validation is decided over validation-only paths and
    enforces only the caller's forbidden list; ordinary formatter/coverage
    outputs are not charged to the worker's allowed-path envelope.
    """
    run_delta = attribution.worker_delta
    if run_delta.base_commit != base_commit:
        raise ValueError("current worker delta base commit is inconsistent")
    if (
        prior_cumulative_worker is not None
        and prior_cumulative_worker.base_commit != base_commit
    ):
        raise ValueError("prior cumulative worker base commit is inconsistent")

    prior_by_path = {
        bytes(change.path): replace(change, origin="prior_run")
        for change in (
            ()
            if prior_cumulative_worker is None
            else prior_cumulative_worker.changes
        )
    }
    cumulative_by_path = dict(prior_by_path)
    for change in run_delta.changes:
        raw_path = bytes(change.path)
        cumulative_by_path[raw_path] = replace(
            change,
            origin="both" if raw_path in prior_by_path else "this_run",
        )
    cumulative_delta = PathIdentitySet.create(
        base_commit=base_commit,
        changes=cumulative_by_path.values(),
        # This is an action ledger rather than a tree comparison. Unchanged
        # paths would re-introduce prior validation filesystem state here.
        unchanged_count=0,
        cumulative_delta_count=(
            len(run_delta.changes)
            if prior_cumulative_worker is None
            else (
                prior_cumulative_worker.cumulative_delta_count
                + len(run_delta.changes)
            )
        ),
    )

    validation_changes = ()
    if attribution.validation_delta is not None:
        validation_only = set(attribution.validation_only)
        validation_changes = tuple(
            change
            for change in attribution.validation_delta.changes
            if change.path in validation_only
        )
    validation_delta = PathIdentitySet.create(
        base_commit=base_commit,
        changes=validation_changes,
        unchanged_count=0,
    )

    return ScopeVerdictSet(
        run_identity=run_delta,
        cumulative_identity=cumulative_delta,
        validation_identity=validation_delta,
        run_worker=decide_scope(run_delta, scope),
        cumulative_worker=decide_scope(cumulative_delta, scope),
        validation=decide_scope(
            validation_delta,
            scope,
            enforce_allowed=False,
        ),
    )


def load_prior_cumulative_worker(
    value: Mapping[str, object],
    *,
    scope: ScopeSpecBytes,
    base_commit: str,
) -> PathIdentitySet:
    """Load the only persisted input allowed to carry worker scope history.

    The displayed verdict is checked against the decoded identity as well as
    the identity's own digest. A forged or partial historical record therefore
    refuses resume instead of becoming an empty, permissive ledger.
    """
    expected_keys = {
        "schema_version",
        "inputs",
        "run_worker",
        "cumulative_worker",
        "validation",
        "aggregate",
        "validation_attributed_forbidden",
    }
    if set(value) != expected_keys or value.get("schema_version") != 1:
        raise ValueError("prior scope evidence schema is malformed")
    inputs = value.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != {
        "run_worker",
        "cumulative_worker",
        "validation",
    }:
        raise ValueError("prior scope evidence inputs are malformed")
    raw_identity = inputs.get("cumulative_worker")
    if not isinstance(raw_identity, Mapping):
        raise ValueError("prior cumulative worker identity is absent")
    identity = PathIdentitySet.from_dict(raw_identity)
    if identity.base_commit != base_commit:
        raise ValueError("prior cumulative worker base commit changed")
    if identity.unrepresentable:
        raise ValueError("prior cumulative worker identity is unrepresentable")

    raw_verdict = value.get("cumulative_worker")
    if not isinstance(raw_verdict, Mapping):
        raise ValueError("prior cumulative worker verdict is absent")
    expected_verdict = decide_scope(identity, scope).to_dict()
    if dict(raw_verdict) != expected_verdict:
        raise ValueError("prior cumulative worker verdict is inconsistent")
    return identity


__all__ = [
    "ScopeVerdictSet",
    "decide_scope_verdicts",
    "load_prior_cumulative_worker",
]
