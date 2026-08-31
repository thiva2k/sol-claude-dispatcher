"""Pure base-tree to pre-worker filesystem reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Protocol

from ..errors import CheckoutTransformationBudgetExceeded
from .basetree import BaseTreeSnapshot


class StartEntryLike(Protocol):
    path: bytes
    kind: str
    content_hash: str | None
    size: int


@dataclass(frozen=True)
class StartTreeEntry:
    path: bytes
    kind: str
    content_hash: str | None
    size: int


@dataclass(frozen=True)
class DivergedPath:
    path: bytes
    base_oid: str
    start_hash: str
    start_size: int
    captured_ref: str


@dataclass(frozen=True)
class KindMismatch:
    path: bytes
    base_kind: str
    start_kind: str


@dataclass(frozen=True)
class BaseReconciliation:
    base_commit: str
    identical_count: int
    diverged: tuple[DivergedPath, ...]
    missing_from_fs: tuple[bytes, ...]
    extra_on_fs: tuple[bytes, ...]
    kind_mismatch: tuple[KindMismatch, ...]
    gitlinks: tuple[bytes, ...]
    captured_bytes: int
    verdict: Literal["identical", "transformed"]


def _normalise_start_kind(kind: str) -> str:
    if kind in ("file", "regular", "blob"):
        return "blob"
    if kind in ("link", "symlink"):
        return "symlink"
    return kind


def reconcile_base_to_start(
    base: BaseTreeSnapshot,
    start_entries: Iterable[StartEntryLike],
    *,
    reconciliation_max_captured_bytes: int = 200_000_000,
    reconciliation_max_diverged_paths: int = 20_000,
) -> BaseReconciliation:
    """Compare sealed Git identities with an injected START snapshot.

    This function captures no files and invokes no subprocess.  A caller stores
    each diverged entry's already-measured START bytes in the shared CAS under
    ``captured_ref`` before the worker can start.
    """

    start: dict[bytes, StartEntryLike] = {}
    for entry in start_entries:
        if entry.path in start:
            raise ValueError("START snapshot contains a duplicate path")
        start[entry.path] = entry

    base_by_path = {entry.path: entry for entry in base.entries}
    identical = 0
    diverged: list[DivergedPath] = []
    missing: list[bytes] = []
    mismatches: list[KindMismatch] = []
    gitlinks: list[bytes] = []
    captured_bytes = 0

    for path, base_entry in base_by_path.items():
        if base_entry.kind == "gitlink":
            gitlinks.append(path)
            continue
        current = start.get(path)
        if current is None:
            missing.append(path)
            continue
        start_kind = _normalise_start_kind(current.kind)
        if start_kind != base_entry.kind:
            mismatches.append(
                KindMismatch(path=path, base_kind=base_entry.kind, start_kind=start_kind)
            )
            continue
        if current.content_hash is None:
            mismatches.append(
                KindMismatch(
                    path=path,
                    base_kind=base_entry.kind,
                    start_kind=f"{start_kind}:unmeasurable",
                )
            )
            continue
        if current.content_hash == base_entry.oid:
            identical += 1
            continue
        if current.size < 0:
            raise ValueError("START snapshot contains a negative size")
        captured_bytes += current.size
        diverged.append(
            DivergedPath(
                path=path,
                base_oid=base_entry.oid,
                start_hash=current.content_hash,
                start_size=current.size,
                captured_ref=current.content_hash,
            )
        )
        if len(diverged) > reconciliation_max_diverged_paths:
            raise CheckoutTransformationBudgetExceeded(
                "Base-to-START reconciliation exceeded its path budget.",
                details={
                    "maximum_diverged_paths": reconciliation_max_diverged_paths,
                    "measured_diverged_paths": len(diverged),
                },
            )
        if captured_bytes > reconciliation_max_captured_bytes:
            raise CheckoutTransformationBudgetExceeded(
                "Base-to-START reconciliation exceeded its byte budget.",
                details={
                    "maximum_captured_bytes": reconciliation_max_captured_bytes,
                    "measured_captured_bytes": captured_bytes,
                },
            )

    extras = sorted(
        path
        for path, entry in start.items()
        if path not in base_by_path and _normalise_start_kind(entry.kind) != "directory"
    )
    transformed = bool(diverged or missing or extras or mismatches)
    return BaseReconciliation(
        base_commit=base.base_commit,
        identical_count=identical,
        diverged=tuple(sorted(diverged, key=lambda item: item.path)),
        missing_from_fs=tuple(sorted(missing)),
        extra_on_fs=tuple(extras),
        kind_mismatch=tuple(sorted(mismatches, key=lambda item: item.path)),
        gitlinks=tuple(sorted(gitlinks)),
        captured_bytes=captured_bytes,
        verdict="transformed" if transformed else "identical",
    )
