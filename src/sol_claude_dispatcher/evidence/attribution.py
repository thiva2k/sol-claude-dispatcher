"""Three-snapshot, identity-wise authorship attribution for Gate 7."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from ..errors import (
    AttributionClosureViolated,
    ValidationAttributionUnknown,
    WorkerAttributionAmbiguous,
)
from .fssnap import FsSnapshot
from .inventory import (
    PathIdentitySet,
    RepoPath,
    build_path_identity_set,
    path_repr,
)

AttributionAuthor = Literal["worker", "validation", "both", "ambiguous"]
AttributionVerdict = Literal[
    "attributable", "worker_ambiguous", "validation_unknown"
]


@dataclass(frozen=True)
class AttributionAmbiguity:
    path: RepoPath
    snapshot_role: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": path_repr(self.path),
            "snapshot_role": self.snapshot_role,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AttributedPath:
    path: RepoPath
    author: AttributionAuthor

    def to_dict(self) -> dict[str, object]:
        return {"path": path_repr(self.path), "author": self.author}


@dataclass(frozen=True)
class WorkerAttribution:
    schema_version: int
    start_digest: str
    worker_exit_digest: str
    post_validation_digest: str | None
    worker_delta: PathIdentitySet
    validation_delta: PathIdentitySet | None
    final_delta: PathIdentitySet | None
    worker_only: tuple[RepoPath, ...]
    validation_only: tuple[RepoPath, ...]
    both_authors: tuple[RepoPath, ...]
    validation_reverted: tuple[RepoPath, ...]
    paths: tuple[AttributedPath, ...]
    ambiguous: tuple[AttributionAmbiguity, ...]
    verdict: AttributionVerdict
    method: Literal["three_snapshot_identity_symmetric_difference"]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "start_digest": self.start_digest,
            "worker_exit_digest": self.worker_exit_digest,
            "post_validation_digest": self.post_validation_digest,
            "worker_delta": self.worker_delta.to_dict(),
            "validation_delta": (
                None if self.validation_delta is None else self.validation_delta.to_dict()
            ),
            "final_delta": (
                None if self.final_delta is None else self.final_delta.to_dict()
            ),
            "worker_only": [path_repr(path) for path in self.worker_only],
            "validation_only": [path_repr(path) for path in self.validation_only],
            "both_authors": [path_repr(path) for path in self.both_authors],
            "validation_reverted": [
                path_repr(path) for path in self.validation_reverted
            ],
            "paths": [item.to_dict() for item in self.paths],
            "ambiguous": [item.to_dict() for item in self.ambiguous],
            "verdict": self.verdict,
            "method": self.method,
        }


def _paths(identity: PathIdentitySet | None) -> set[RepoPath]:
    if identity is None:
        return set()
    return {change.path for change in identity.changes}


def _snapshot_ambiguities(snapshot: FsSnapshot) -> tuple[AttributionAmbiguity, ...]:
    by_path = {entry.path: entry for entry in snapshot.entries}
    results: list[AttributionAmbiguity] = []
    for path in snapshot.unreadable:
        entry = by_path[path]
        results.append(
            AttributionAmbiguity(
                path=path,
                snapshot_role=snapshot.role,
                reason=entry.read_error or "snapshot_incomplete",
            )
        )
    return tuple(sorted(results, key=lambda item: bytes(item.path)))


def _assert_attribution_closure(
    *,
    final_paths: set[RepoPath],
    worker_paths: set[RepoPath],
    validation_paths: set[RepoPath],
) -> None:
    """Enforce Z9-T1 loudly; never log and continue on a missing author."""
    uncovered = final_paths - (worker_paths | validation_paths)
    if uncovered:
        ordered = sorted(uncovered, key=bytes)
        raise AttributionClosureViolated(
            "Final filesystem changes escaped worker and validation attribution.",
            details={
                "unattributed_count": len(ordered),
                "unattributed_paths": [path_repr(path) for path in ordered],
            },
            remediation="Preserve and inspect all three raw snapshots; do not "
            "re-measure an earlier lifecycle moment.",
        )


def _validate_snapshots(
    start: FsSnapshot,
    worker_exit: FsSnapshot,
    post_validation: FsSnapshot | None,
) -> None:
    if start.role != "task_worktree_start":
        raise ValueError("start snapshot has the wrong role")
    if worker_exit.role != "task_worktree_worker_exit":
        raise ValueError("worker-exit snapshot has the wrong role")
    if post_validation is not None and post_validation.role != "task_worktree_post_validation":
        raise ValueError("post-validation snapshot has the wrong role")
    snapshots = (start, worker_exit) + (() if post_validation is None else (post_validation,))
    if any(snapshot.root != start.root for snapshot in snapshots):
        raise ValueError("attribution snapshots have different roots")
    if any(snapshot.fidelity != "content_hash_all" for snapshot in snapshots):
        raise ValueError("attribution requires content_hash_all snapshots")


def attribute_snapshots(
    start: FsSnapshot,
    worker_exit: FsSnapshot,
    post_validation: FsSnapshot | None,
    *,
    base_commit: str,
    tracked_paths: Iterable[RepoPath] = (),
    ignored_paths: Iterable[RepoPath] = (),
    admin_paths: Iterable[RepoPath] = (),
) -> WorkerAttribution:
    """Attribute paths from START, WORKER_EXIT and optional POST_VALIDATION.

    ``worker_delta`` is always authoritative and exists even when an incomplete
    snapshot makes the authorship verdict fail closed.  There is no fallback
    walk and no path-name-only set difference.
    """
    _validate_snapshots(start, worker_exit, post_validation)
    tracked = tuple(tracked_paths)
    ignored = tuple(ignored_paths)
    admin = tuple(admin_paths)
    worker_delta = build_path_identity_set(
        start,
        worker_exit,
        base_commit=base_commit,
        tracked_paths=tracked,
        ignored_paths=ignored,
        admin_paths=admin,
    )

    worker_ambiguities = _snapshot_ambiguities(worker_exit)
    validation_ambiguities: tuple[AttributionAmbiguity, ...] = ()
    validation_delta: PathIdentitySet | None = None
    final_delta: PathIdentitySet | None = None
    if post_validation is not None:
        validation_delta = build_path_identity_set(
            worker_exit,
            post_validation,
            base_commit=base_commit,
            tracked_paths=tracked,
            ignored_paths=ignored,
            admin_paths=admin,
        )
        final_delta = build_path_identity_set(
            start,
            post_validation,
            base_commit=base_commit,
            tracked_paths=tracked,
            ignored_paths=ignored,
            admin_paths=admin,
        )
        validation_ambiguities = _snapshot_ambiguities(post_validation)

    worker_paths = _paths(worker_delta)
    validation_paths = _paths(validation_delta)
    final_paths = _paths(final_delta) if final_delta is not None else set(worker_paths)
    _assert_attribution_closure(
        final_paths=final_paths,
        worker_paths=worker_paths,
        validation_paths=validation_paths,
    )

    worker_only = worker_paths - validation_paths
    validation_only = validation_paths - worker_paths
    both = worker_paths & validation_paths
    validation_reverted = worker_paths - final_paths
    ambiguities = tuple(
        sorted(
            (*worker_ambiguities, *validation_ambiguities),
            key=lambda item: (bytes(item.path), item.snapshot_role),
        )
    )
    ambiguous_paths = {item.path for item in ambiguities}

    all_paths = worker_paths | validation_paths | final_paths | ambiguous_paths
    attributed: list[AttributedPath] = []
    for path in sorted(all_paths, key=bytes):
        if path in ambiguous_paths:
            author: AttributionAuthor = "ambiguous"
        elif path in both:
            author = "both"
        elif path in worker_paths:
            author = "worker"
        else:
            author = "validation"
        attributed.append(AttributedPath(path=path, author=author))

    if worker_ambiguities or not worker_exit.capture_complete:
        verdict: AttributionVerdict = "worker_ambiguous"
    elif validation_ambiguities or (
        post_validation is not None and not post_validation.capture_complete
    ):
        verdict = "validation_unknown"
    else:
        verdict = "attributable"

    return WorkerAttribution(
        schema_version=1,
        start_digest=start.digest,
        worker_exit_digest=worker_exit.digest,
        post_validation_digest=(
            None if post_validation is None else post_validation.digest
        ),
        worker_delta=worker_delta,
        validation_delta=validation_delta,
        final_delta=final_delta,
        worker_only=tuple(sorted(worker_only, key=bytes)),
        validation_only=tuple(sorted(validation_only, key=bytes)),
        both_authors=tuple(sorted(both, key=bytes)),
        validation_reverted=tuple(sorted(validation_reverted, key=bytes)),
        paths=tuple(attributed),
        ambiguous=ambiguities,
        verdict=verdict,
        method="three_snapshot_identity_symmetric_difference",
    )


def require_attributable(attribution: WorkerAttribution) -> None:
    """Convert a non-attributable record into its typed fail-closed refusal."""
    if attribution.verdict == "worker_ambiguous":
        raise WorkerAttributionAmbiguous(
            "Worker filesystem attribution is ambiguous.",
            details={
                "ambiguous_count": len(attribution.ambiguous),
                "paths": [item.to_dict() for item in attribution.ambiguous],
            },
        )
    if attribution.verdict == "validation_unknown":
        raise ValidationAttributionUnknown(
            "Validation filesystem attribution is unknown.",
            details={
                "ambiguous_count": len(attribution.ambiguous),
                "paths": [item.to_dict() for item in attribution.ambiguous],
            },
        )


__all__ = [
    "AttributedPath",
    "AttributionAmbiguity",
    "WorkerAttribution",
    "attribute_snapshots",
    "require_attributable",
]
