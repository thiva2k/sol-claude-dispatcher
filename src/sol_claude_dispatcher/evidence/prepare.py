"""Gate 7 PREPARE transaction for a new dispatch.

The function in this module owns the exact transition from raw, operator-
approved repository authority to a detached, sealed worker start tree.  It is
deliberately synchronous; the MCP server runs it in a worker thread while the
current :class:`ToolExecution` context is propagated by ``asyncio.to_thread``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from ..errors import (
    BaseObjectVerificationFailed,
    DispatcherSetupTouchedPrimaryTree,
    FilesystemSnapshotFailed,
    RefResolutionFailed,
    RepositoryIdentityUnsealed,
    RepositoryRootDrift,
    WorktreeBaseMismatch,
)
from ..git import Gate7GitExecutor, WorktreeRef
from .basetree import git_blob_oid, parse_ls_tree_z
from .fssnap import FsEntry, FsSnapshot, capture_snapshot
from .git_order import GitPath
from .gitadmin import (
    GitAdminSnapshot,
    ReconciliationResult,
    capture_repository_administration,
    load_baseline,
    reconcile_repository_administration,
)
from .identity import RepositoryAuthoritySnapshot, capture_repository_authority
from .identity_record import (
    ApprovedIdentityFacts,
    RawAdminGateResult,
    RepositoryIdentityRecord,
    build_identity_record,
)
from .seal import LoadedTaskSeal, create_task_seal, load_task_seal
from .worktreeauth import (
    WorktreeAuthorityRecord,
    capture_worktree_authority,
    encode_worktree_authority,
    decode_worktree_authority,
    verify_worktree_authority,
)

__all__ = [
    "PreparedDispatch",
    "PreparedResume",
    "PrimaryHeadSnapshot",
    "PrimaryRefLink",
    "assert_primary_snapshot_usable",
    "capture_matching_repository_authority",
    "capture_primary_head",
    "primary_snapshots_equal",
    "prepare_dispatch",
    "prepare_resume",
    "read_snapshot_entry_bytes",
]

_MAX_REF_BYTES = 4096
_MAX_PACKED_REFS_BYTES = 16 * 1024 * 1024
_MAX_SYMBOLIC_HOPS = 5
_OID_RE = re.compile(rb"[0-9a-f]{40}")
_REF_RE = re.compile(rb"refs/[A-Za-z0-9._/-]+")


@dataclass(frozen=True)
class PreparedDispatch:
    task_id: str
    base_commit: str
    worktree: WorktreeRef
    repository_authority: RepositoryAuthoritySnapshot
    admin_baseline: GitAdminSnapshot
    admin_prepare: GitAdminSnapshot
    admin_worker_start: GitAdminSnapshot
    admin_reconciliation: ReconciliationResult
    primary_prepare: FsSnapshot
    primary_worker_start: FsSnapshot
    primary_prepare_head: "PrimaryHeadSnapshot"
    primary_worker_start_head: "PrimaryHeadSnapshot"
    worktree_start: FsSnapshot
    cumulative_start: FsSnapshot
    worktree_authority: WorktreeAuthorityRecord
    seal: LoadedTaskSeal
    git_journal_path: Path
    new_loose_objects: tuple[str, ...]


@dataclass(frozen=True)
class PreparedResume:
    task_id: str
    base_commit: str
    worktree: WorktreeRef
    repository_authority: RepositoryAuthoritySnapshot
    admin_baseline: GitAdminSnapshot
    admin_prepare: GitAdminSnapshot
    admin_worker_start: GitAdminSnapshot
    admin_reconciliation: ReconciliationResult
    primary_prepare: FsSnapshot
    primary_worker_start: FsSnapshot
    primary_prepare_head: "PrimaryHeadSnapshot"
    primary_worker_start_head: "PrimaryHeadSnapshot"
    worktree_start: FsSnapshot
    cumulative_start: FsSnapshot
    worktree_authority: WorktreeAuthorityRecord
    seal: LoadedTaskSeal
    git_journal_path: Path
    new_loose_objects: tuple[str, ...]


@dataclass(frozen=True)
class PrimaryRefLink:
    """One named step in the raw primary-HEAD resolution chain."""

    ref_name: bytes
    loose_path: bytes
    loose_bytes: bytes | None
    source: Literal["loose", "packed"]

    def to_dict(self) -> dict[str, object]:
        return {
            "ref_name": os.fsdecode(self.ref_name),
            "loose_path": os.fsdecode(self.loose_path),
            "loose_hex": (
                None if self.loose_bytes is None else self.loose_bytes.hex()
            ),
            "source": self.source,
        }


@dataclass(frozen=True)
class PrimaryHeadSnapshot:
    head_path: bytes
    head_bytes: bytes
    ref_chain: tuple[PrimaryRefLink, ...]
    packed_refs_bytes: bytes | None
    head_commit: str
    digest: str

    @property
    def ref_path(self) -> bytes | None:
        """Compatibility view of the first named ref in the chain."""

        return self.ref_chain[0].loose_path if self.ref_chain else None

    @property
    def ref_bytes(self) -> bytes | None:
        """Compatibility view of the first named ref's loose bytes."""

        return self.ref_chain[0].loose_bytes if self.ref_chain else None

    def to_dict(self) -> dict[str, object]:
        return {
            "head_path": os.fsdecode(self.head_path),
            "head_hex": self.head_bytes.hex(),
            "head_commit": self.head_commit,
            "ref_chain": [link.to_dict() for link in self.ref_chain],
            "ref_path": None if self.ref_path is None else os.fsdecode(self.ref_path),
            "ref_hex": None if self.ref_bytes is None else self.ref_bytes.hex(),
            "packed_refs_hex": (
                None
                if self.packed_refs_bytes is None
                else self.packed_refs_bytes.hex()
            ),
            "digest": self.digest,
        }


def _read_regular_nofollow(
    path: bytes, *, required: bool, maximum_bytes: int
) -> bytes | None:
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        if not required:
            return None
        raise FilesystemSnapshotFailed(
            "Primary HEAD authority is absent.", details={"path": os.fsdecode(path)}
        )
    except OSError as exc:
        raise FilesystemSnapshotFailed(
            "Primary HEAD authority is unreadable.",
            details={"path": os.fsdecode(path), "reason": str(exc)},
        ) from exc
    if not stat.S_ISREG(before.st_mode):
        raise FilesystemSnapshotFailed(
            "Primary HEAD authority is not a regular file.",
            details={"path": os.fsdecode(path)},
        )
    if before.st_size > maximum_bytes:
        raise RefResolutionFailed(
            "Primary HEAD authority exceeds its raw-read budget.",
            details={
                "path": os.fsdecode(path),
                "maximum_bytes": maximum_bytes,
                "measured_bytes": before.st_size,
            },
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, min(65536, maximum_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum_bytes:
                    raise RefResolutionFailed(
                        "Primary HEAD authority exceeded its raw-read budget.",
                        details={"path": os.fsdecode(path)},
                    )
                chunks.append(chunk)
            after = os.fstat(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise FilesystemSnapshotFailed(
            "Primary HEAD authority could not be read without following links.",
            details={"path": os.fsdecode(path), "reason": str(exc)},
        ) from exc

    def identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    if (
        not stat.S_ISREG(opened.st_mode)
        or identity(before) != identity(opened)
        or identity(opened) != identity(after)
    ):
        raise FilesystemSnapshotFailed(
            "Primary HEAD authority changed during measurement.",
            details={"path": os.fsdecode(path)},
        )
    return b"".join(chunks)


def _validate_refname(ref_name: bytes) -> None:
    if (
        _REF_RE.fullmatch(ref_name) is None
        or b".." in ref_name
        or b"//" in ref_name
        or b"\\" in ref_name
        or ref_name.startswith(b"/")
        or ref_name.endswith(b"/")
        or any(component.startswith(b".") for component in ref_name.split(b"/"))
    ):
        raise RefResolutionFailed(
            "Primary HEAD contains an unsafe ref name.",
            details={"ref_hex": ref_name.hex()},
        )


def _safe_ref_path(common_dir: bytes, ref_name: bytes) -> bytes:
    """Return a ref path only after every parent is proven non-symlink."""

    _validate_refname(ref_name)
    try:
        root_stat = os.lstat(common_dir)
    except OSError as exc:
        raise RefResolutionFailed(
            "Primary ref authority root is unreadable.",
            details={"path": os.fsdecode(common_dir)},
        ) from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise RefResolutionFailed("Primary ref authority root is not a directory.")
    current = common_dir
    for component in ref_name.split(b"/")[:-1]:
        current = os.path.join(current, component)
        try:
            measured = os.lstat(current)
        except FileNotFoundError:
            # A missing parent means the loose ref is absent. The packed-refs
            # fallback remains eligible; no path is opened through the gap.
            break
        except OSError as exc:
            raise RefResolutionFailed(
                "Primary ref parent could not be classified.",
                details={"path": os.fsdecode(current)},
            ) from exc
        if not stat.S_ISDIR(measured.st_mode):
            raise RefResolutionFailed(
                "Primary ref parent is not a real directory.",
                details={"path": os.fsdecode(current)},
            )
    return os.path.join(common_dir, ref_name)


def _parse_ref_value(raw: bytes, *, label: str) -> tuple[str, bytes]:
    value = raw[:-1] if raw.endswith(b"\n") else raw
    if b"\n" in value or b"\r" in value:
        raise RefResolutionFailed(f"{label} has a non-canonical line shape.")
    if _OID_RE.fullmatch(value) is not None:
        return "oid", value
    if value.startswith(b"ref: "):
        ref_name = value[5:]
        _validate_refname(ref_name)
        return "ref", ref_name
    raise RefResolutionFailed(
        f"{label} does not resolve to exact lowercase 40-hex authority."
    )


def _packed_ref_value(packed_refs: bytes, target: bytes) -> bytes | None:
    """Parse the bounded packed-refs file and return one unambiguous target."""

    found: list[bytes] = []
    previous_entry = False
    for line_number, line in enumerate(packed_refs.splitlines(), start=1):
        if not line:
            previous_entry = False
            continue
        if line.startswith(b"#"):
            previous_entry = False
            continue
        if line.startswith(b"^"):
            if not previous_entry or _OID_RE.fullmatch(line[1:]) is None:
                raise RefResolutionFailed(
                    "packed-refs contains a malformed peeled line.",
                    details={"line": line_number},
                )
            previous_entry = False
            continue
        parts = line.split(b" ")
        if len(parts) != 2 or _OID_RE.fullmatch(parts[0]) is None:
            raise RefResolutionFailed(
                "packed-refs contains a malformed entry.",
                details={"line": line_number},
            )
        _validate_refname(parts[1])
        previous_entry = True
        if parts[1] == target:
            found.append(parts[0])
    if len(found) > 1:
        raise RefResolutionFailed("packed-refs contains duplicate target authority.")
    return found[0] if found else None


def capture_primary_head(
    authority: RepositoryAuthoritySnapshot,
) -> PrimaryHeadSnapshot:
    """Resolve primary HEAD through at most five raw, common-dir ref hops."""

    head_path = os.path.join(authority.git_dir, b"HEAD")
    head = _read_regular_nofollow(
        head_path, required=True, maximum_bytes=_MAX_REF_BYTES
    )
    assert head is not None
    chain: list[PrimaryRefLink] = []
    packed_refs: bytes | None = None
    kind, value = _parse_ref_value(head, label="Primary HEAD")
    seen: set[bytes] = set()
    hops = 0
    while kind == "ref":
        hops += 1
        if hops > _MAX_SYMBOLIC_HOPS:
            raise RefResolutionFailed(
                "Primary HEAD exceeds the symbolic-ref hop limit.",
                details={"maximum_hops": _MAX_SYMBOLIC_HOPS},
            )
        ref_name = value
        if ref_name in seen:
            raise RefResolutionFailed("Primary HEAD contains a symbolic-ref cycle.")
        seen.add(ref_name)
        ref_path = _safe_ref_path(authority.common_dir, ref_name)
        ref_bytes = _read_regular_nofollow(
            ref_path, required=False, maximum_bytes=_MAX_REF_BYTES
        )
        if ref_bytes is not None:
            chain.append(PrimaryRefLink(ref_name, ref_path, ref_bytes, "loose"))
            kind, value = _parse_ref_value(
                ref_bytes, label=f"Primary loose ref {os.fsdecode(ref_name)}"
            )
        else:
            packed_refs = _read_regular_nofollow(
                os.path.join(authority.common_dir, b"packed-refs"),
                required=False,
                maximum_bytes=_MAX_PACKED_REFS_BYTES,
            )
            if packed_refs is None:
                raise RefResolutionFailed(
                    "Primary HEAD ref has no loose or packed authority."
                )
            packed_value = _packed_ref_value(packed_refs, ref_name)
            if packed_value is None:
                raise RefResolutionFailed(
                    "Primary HEAD ref is absent from loose and packed authority."
                )
            chain.append(PrimaryRefLink(ref_name, ref_path, None, "packed"))
            kind, value = "oid", packed_value

    if kind != "oid" or _OID_RE.fullmatch(value) is None:
        raise RefResolutionFailed(
            "Primary HEAD did not terminate in exact lowercase 40-hex."
        )
    digest_parts = [b"HEAD\0", len(head).to_bytes(8, "big"), head]
    for link in chain:
        digest_parts.extend(
            (
                b"REF\0",
                len(link.ref_name).to_bytes(8, "big"),
                link.ref_name,
                len(link.loose_bytes or b"").to_bytes(8, "big"),
                link.loose_bytes or b"",
                link.source.encode("ascii"),
            )
        )
    digest_parts.extend(
        (
            b"PACKED\0",
            len(packed_refs or b"").to_bytes(8, "big"),
            packed_refs or b"",
            b"OID\0",
            value,
        )
    )
    return PrimaryHeadSnapshot(
        head_path=head_path,
        head_bytes=head,
        ref_chain=tuple(chain),
        packed_refs_bytes=packed_refs,
        head_commit=value.decode("ascii"),
        digest=hashlib.sha256(b"".join(digest_parts)).hexdigest(),
    )


def capture_matching_repository_authority(
    repository_root: Path,
    sealed: RepositoryAuthoritySnapshot,
    *,
    phase: str,
) -> RepositoryAuthoritySnapshot:
    """Recapture live repository layout and require exact sealed equality."""

    live = capture_repository_authority(
        repository_root,
        authorized_root=repository_root,
        authorized_gitdir_roots=(sealed.git_dir, sealed.common_dir),
    )
    if live != sealed:
        changed = sorted(
            field
            for field in sealed.__dataclass_fields__
            if getattr(live, field) != getattr(sealed, field)
        )
        raise RepositoryRootDrift(
            "The live repository authority differs from its pre-worker seal.",
            details={"phase": phase, "changed_fields": changed},
        )
    return live


def assert_primary_snapshot_usable(
    snapshot: FsSnapshot,
    *,
    expected_root: bytes | None = None,
    expected_fidelity: str | None = None,
    expected_entry_count: int | None = None,
) -> None:
    """Validate completeness, fidelity, root and anti-vacuity before comparison."""

    paths = [bytes(entry.path) for entry in snapshot.entries]
    counts: dict[str, int] = {}
    for entry in snapshot.entries:
        counts[entry.kind] = counts.get(entry.kind, 0) + 1
    reasons: list[str] = []
    if snapshot.schema_version != 1:
        reasons.append("schema_version")
    if snapshot.role not in {"primary_pre", "primary_post"}:
        reasons.append("role")
    if not snapshot.capture_complete:
        reasons.append("capture_incomplete")
    if snapshot.unreadable or snapshot.ambiguities or snapshot.truncated_at_entry:
        reasons.append("partial_capture")
    if not snapshot.entries:
        reasons.append("zero_entries")
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        reasons.append("path_order_or_uniqueness")
    if counts != snapshot.counts or sum(snapshot.counts.values()) != len(paths):
        reasons.append("count_mismatch")
    if tuple(bytes(path) for path in snapshot.admin_excluded) != (b".git",):
        reasons.append("admin_exclusion")
    if expected_root is not None and snapshot.root != expected_root:
        reasons.append("root")
    if expected_fidelity is not None and snapshot.fidelity != expected_fidelity:
        reasons.append("fidelity")
    if expected_entry_count is not None and len(paths) != expected_entry_count:
        reasons.append("entry_count")
    if reasons:
        raise FilesystemSnapshotFailed(
            "A primary snapshot is incomplete or incomparable.",
            details={
                "reasons": reasons,
                "entry_count": len(paths),
                "expected_entry_count": expected_entry_count,
            },
        )


def _primary_snapshot_projection(snapshot: FsSnapshot) -> tuple[object, ...]:
    return (
        snapshot.schema_version,
        snapshot.root,
        snapshot.fidelity,
        snapshot.hash_algo,
        snapshot.entries,
        tuple(sorted(snapshot.counts.items())),
        snapshot.total_regular_bytes,
        snapshot.admin_excluded,
    )


def primary_snapshots_equal(
    before: FsSnapshot,
    after: FsSnapshot,
    *,
    expected_root: bytes,
) -> bool:
    """Compare only canonical primary authority after shared usability checks."""

    assert_primary_snapshot_usable(before, expected_root=expected_root)
    assert_primary_snapshot_usable(
        after,
        expected_root=expected_root,
        expected_fidelity=before.fidelity,
    )
    return _primary_snapshot_projection(before) == _primary_snapshot_projection(after)


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def read_snapshot_entry_bytes(root: Path, entry: FsEntry) -> bytes:
    raw = os.path.join(os.fsencode(root), bytes(entry.path))
    if entry.kind == "symlink":
        target = os.fsencode(os.readlink(raw))
        if entry.link_target != target or git_blob_oid(target) != entry.content_hash:
            raise BaseObjectVerificationFailed(
                "A START symlink changed between snapshot and sealing.",
                details={"path_hex": bytes(entry.path).hex()},
            )
        return target
    if entry.kind != "regular":
        raise BaseObjectVerificationFailed(
            "A non-file START entry cannot provide base object bytes.",
            details={"path_hex": bytes(entry.path).hex(), "kind": entry.kind},
        )
    before = os.lstat(raw)
    if not stat.S_ISREG(before.st_mode):
        raise BaseObjectVerificationFailed("A START file changed type before sealing.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(raw, flags)
    try:
        opened = os.fstat(fd)
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    if (before.st_dev, before.st_ino, before.st_size) != (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
    ) or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise BaseObjectVerificationFailed("A START file changed while it was sealed.")
    data = b"".join(chunks)
    if git_blob_oid(data) != entry.content_hash:
        raise BaseObjectVerificationFailed(
            "START bytes do not match the filesystem snapshot identity.",
            details={"path_hex": bytes(entry.path).hex()},
        )
    return data


def _route_a_bytes(root: Path, snapshot: FsSnapshot) -> dict[bytes, bytes]:
    return {
        bytes(entry.path): read_snapshot_entry_bytes(root, entry)
        for entry in snapshot.entries
        if entry.kind in {"regular", "symlink"} and entry.content_hash is not None
    }


def prepare_dispatch(
    *,
    repository_root: Path,
    state_root: Path,
    worktree_path: Path,
    task_id: str,
    base_commit: str,
    empty_hooks_path: Path,
    git_executable: str | os.PathLike[str] | None = None,
    identity_preflight: Callable[
        [RepositoryAuthoritySnapshot], ApprovedIdentityFacts | None
    ]
    | None = None,
) -> PreparedDispatch:
    """Run R0–R8, the declared dispatch rows, and START sealing.

    The caller must already have validated the request, transport budget,
    repository allowlist and repository lock.  No worker process or lifecycle
    state may exist yet.  Any failure removes the dispatcher-owned worktree and
    staging seal; the operator baseline is never rewritten.
    """

    root = Path(repository_root)
    state = Path(state_root)
    staging = state / "staging" / task_id
    journal_path = state / "preflight" / task_id / "git-invocations.jsonl"
    authority = capture_repository_authority(root, authorized_root=root)
    baseline = load_baseline(state, root)
    current = capture_repository_administration(root, baseline=baseline)
    reconciliation = reconcile_repository_administration(baseline, current)
    primary_prepare_head = capture_primary_head(authority)
    primary_prepare = capture_snapshot(
        root, role="primary_pre", fidelity="stat_identity"
    )
    assert_primary_snapshot_usable(
        primary_prepare, expected_root=authority.canonical_root
    )
    approved_identity = (
        identity_preflight(authority)
        if identity_preflight is not None
        else ApprovedIdentityFacts.no_guidance()
    )
    if approved_identity is None:
        approved_identity = ApprovedIdentityFacts.no_guidance()

    executor = Gate7GitExecutor(
        repository_root=root,
        journal_path=journal_path,
        empty_hooks_path=empty_hooks_path,
        path=GitPath.DISPATCH,
        git_executable=git_executable,
    )
    executor.establish()
    created = False
    try:
        executor.verify_exact_base(base_commit)
        tree_output = executor.capture_base_tree(base_commit)
        identities = parse_ls_tree_z(tree_output)
        executor.list_worktrees()
        worktree = executor.create_detached_worktree(worktree_path, base_commit)
        created = True

        created_argv = (
            str(executor.git_executable),
            *executor.pin_block.argv,
            "worktree",
            "add",
            "--quiet",
            "--detach",
            str(worktree_path),
            base_commit,
        )
        worktree_authority = capture_worktree_authority(
            worktree_path,
            worktree_id=task_id,
            expected_base_commit=base_commit,
            created_argv=created_argv,
            dispatcher_owned_gitdir_root=os.fsdecode(authority.common_dir),
        )
        start = capture_snapshot(worktree_path, role="task_worktree_start")
        if not start.capture_complete:
            raise FilesystemSnapshotFailed(
                "The initial task-worktree snapshot is incomplete."
            )
        route_a = _route_a_bytes(worktree_path, start)
        unresolved: list[str] = []
        for identity in identities:
            if identity.kind == "gitlink":
                continue
            data = route_a.get(identity.path)
            if data is None or git_blob_oid(data) != identity.oid:
                if identity.oid not in unresolved:
                    unresolved.append(identity.oid)
        batch = executor.read_objects_batch(tuple(unresolved))
        executor.verify_promisor_completeness()

        live_worker_start_authority = capture_matching_repository_authority(
            root, authority, phase="worker_start"
        )
        primary_worker_start = capture_snapshot(
            root, role="primary_post", fidelity="stat_identity"
        )
        primary_worker_start_head = capture_primary_head(live_worker_start_authority)
        if (
            not primary_snapshots_equal(
                primary_prepare,
                primary_worker_start,
                expected_root=authority.canonical_root,
            )
            or primary_prepare_head != primary_worker_start_head
        ):
            raise DispatcherSetupTouchedPrimaryTree(
                "Dispatcher setup changed the primary worktree before worker launch.",
                details={
                    "prepare_digest": primary_prepare.digest,
                    "worker_start_digest": primary_worker_start.digest,
                },
            )

        start_content = {
            f"start-content/{git_blob_oid(data)}": data
            for data in route_a.values()
        }
        seal = create_task_seal(
            staging / "seal",
            task_id=task_id,
            base_commit=base_commit,
            ls_tree_output=tree_output,
            route_a_by_path=route_a,
            route_b_batch_output=batch,
            artefacts={
                **start_content,
                "repository-authority.json": _canonical_json(authority.to_json_dict()),
                "admin-prepare.json": _canonical_json(current.to_dict()),
                "primary-prepare.json": _canonical_json(primary_prepare.to_dict()),
                "primary-worker-start.json": _canonical_json(
                    primary_worker_start.to_dict()
                ),
                "worktree-authority.json": encode_worktree_authority(
                    worktree_authority
                ),
                "worktree-start.json": _canonical_json(start.to_dict()),
            },
            identity_factory=lambda _snapshot, base_tree_hash, sealed_at: (
                build_identity_record(
                    task_id=task_id,
                    authority=authority,
                    approved=approved_identity,
                    admin_gate=RawAdminGateResult.build(
                        baseline=baseline.to_dict(),
                        prepare_capture=current.to_dict(),
                        new_loose_objects=reconciliation.new_loose_objects,
                    ),
                    base_commit=base_commit,
                    base_tree_manifest_hash=base_tree_hash,
                    pins_applied=executor.pin_block.names,
                    sealed_at=sealed_at,
                )
            ),
        )
        # This is the attribution operand, not the earlier execution gate.  It
        # is deliberately the last PREPARE capture, after worktree creation,
        # content sealing and manifest publication have all completed.
        admin_worker_start = capture_repository_administration(
            root,
            baseline=baseline,
            selected_worktree_gitdir=worktree_authority.gitdir_realpath,
        )
        return PreparedDispatch(
            task_id=task_id,
            base_commit=base_commit,
            worktree=worktree,
            repository_authority=authority,
            admin_baseline=baseline,
            admin_prepare=current,
            admin_worker_start=admin_worker_start,
            admin_reconciliation=reconciliation,
            primary_prepare=primary_prepare,
            primary_worker_start=primary_worker_start,
            primary_prepare_head=primary_prepare_head,
            primary_worker_start_head=primary_worker_start_head,
            worktree_start=start,
            cumulative_start=start,
            worktree_authority=worktree_authority,
            seal=seal,
            git_journal_path=journal_path,
            new_loose_objects=reconciliation.new_loose_objects,
        )
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        # A failed G4 may have created a partial target.  Remove only the
        # dispatcher-derived worktree path; Git registration is intentionally
        # left for explicit operator repair because running another Git row is
        # forbidden once the declared sequence fails.
        if created and worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)
        raise


def prepare_resume(
    *,
    repository_root: Path,
    state_root: Path,
    worktree_path: Path,
    task_id: str,
    run_index: int,
    base_commit: str,
    seal_path: Path,
    empty_hooks_path: Path,
    git_executable: str | os.PathLike[str] | None = None,
    context_preflight: Callable[
        [RepositoryAuthoritySnapshot, RepositoryIdentityRecord], None
    ]
    | None = None,
) -> PreparedResume:
    """Re-establish sealed authority and execute resume's sole Git row."""

    root = Path(repository_root)
    worktree = Path(worktree_path)
    # P1/P2 consume the exact authority records first. P5 later verifies that
    # these bytes were members of the immutable seal; no Git process can occur
    # between the unverified read and that verification.
    try:
        repo_authority_bytes = (seal_path / "repository-authority.json").read_bytes()
        worktree_authority_bytes = (seal_path / "worktree-authority.json").read_bytes()
        identity_record_bytes = (seal_path / "identity-record.json").read_bytes()
        sealed_repo_authority = RepositoryAuthoritySnapshot.from_json_dict(
            json.loads(repo_authority_bytes)
        )
        worktree_authority = decode_worktree_authority(worktree_authority_bytes)
        sealed_identity = RepositoryIdentityRecord.from_json_bytes(
            identity_record_bytes
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RepositoryIdentityUnsealed(
            "The persisted resume identity or authority is absent or malformed.",
            details={"relpath": "identity-record.json"},
        ) from exc
    if sealed_identity.canonical_root != os.fsencode(root):
        raise RepositoryIdentityUnsealed(
            "The resume repository root does not equal sealed task identity.",
            details={"task_id": task_id},
        )

    try:
        live_repo_authority = capture_matching_repository_authority(
            root, sealed_repo_authority, phase="resume_prepare"
        )
    except RepositoryRootDrift as exc:
        # Preserve resume's established public refusal while retaining the
        # specific raw-authority cause and phase in the exception chain.
        raise BaseObjectVerificationFailed(
            "The primary repository authority differs from the task seal.",
            details=exc.details,
        ) from exc
    authority_verdict = verify_worktree_authority(worktree_authority)
    if authority_verdict.verdict != "base_held":
        raise WorktreeBaseMismatch(
            "The task worktree authority differs from its pre-worker seal.",
            details={
                "verdict": authority_verdict.verdict,
                "phase": "resume",
                "anchored_base_commit": worktree_authority.expected_base_commit,
                "expected_base_commit": base_commit,
                "actual_head_commit": (
                    authority_verdict.observed_head_bytes.decode(
                        "ascii", errors="replace"
                    ).strip()
                    if authority_verdict.observed_head_bytes is not None
                    else None
                ),
            },
        )

    baseline = load_baseline(state_root, root)
    current = capture_repository_administration(root, baseline=baseline)
    reconciliation = reconcile_repository_administration(baseline, current)
    primary_prepare_head = capture_primary_head(live_repo_authority)
    if context_preflight is not None:
        context_preflight(live_repo_authority, sealed_identity)

    # P5: now authenticate the authority records and every other persisted
    # artifact against the manifest before the sole resume Git row.
    seal = load_task_seal(seal_path, require_identity=True)
    if seal.manifest.task_id != task_id or seal.manifest.base_commit != base_commit:
        raise BaseObjectVerificationFailed(
            "The persisted task seal does not belong to this resume.",
            details={"task_id": task_id, "base_commit": base_commit},
        )
    if seal.identity_record != sealed_identity:
        raise RepositoryIdentityUnsealed(
            "The resume identity changed before seal verification completed.",
            details={"relpath": "identity-record.json"},
        )
    try:
        cumulative_start = FsSnapshot.from_dict(
            json.loads(seal.artefact_bytes("worktree-start.json"))
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BaseObjectVerificationFailed(
            "The sealed initial worktree snapshot is malformed."
        ) from exc
    primary_prepare = capture_snapshot(
        root, role="primary_pre", fidelity="stat_identity"
    )
    assert_primary_snapshot_usable(
        primary_prepare, expected_root=live_repo_authority.canonical_root
    )
    start = capture_snapshot(worktree, role="task_worktree_start")
    if not start.capture_complete:
        raise FilesystemSnapshotFailed(
            "The resumed task-worktree snapshot is incomplete."
        )

    journal = (
        Path(state_root)
        / "tasks"
        / task_id
        / "runs"
        / f"{run_index:04d}"
        / "git-invocations.jsonl"
    )
    executor = Gate7GitExecutor(
        repository_root=root,
        journal_path=journal,
        empty_hooks_path=empty_hooks_path,
        path=GitPath.RESUME,
        git_executable=git_executable,
    )
    executor.establish()
    listing = executor.list_worktrees(resume=True)
    if b"worktree " + os.fsencode(worktree) + b"\n" not in listing:
        raise WorktreeBaseMismatch(
            "The sealed task worktree is no longer registered."
        )
    live_worker_start_authority = capture_matching_repository_authority(
        root, live_repo_authority, phase="resume_worker_start"
    )
    primary_worker_start = capture_snapshot(
        root, role="primary_post", fidelity="stat_identity"
    )
    primary_worker_start_head = capture_primary_head(live_worker_start_authority)
    admin_worker_start = capture_repository_administration(
        root,
        baseline=baseline,
        selected_worktree_gitdir=worktree_authority.gitdir_realpath,
    )
    if (
        not primary_snapshots_equal(
            primary_prepare,
            primary_worker_start,
            expected_root=live_repo_authority.canonical_root,
        )
        or primary_prepare_head != primary_worker_start_head
    ):
        raise DispatcherSetupTouchedPrimaryTree(
            "Resume preparation changed the primary worktree."
        )
    return PreparedResume(
        task_id=task_id,
        base_commit=base_commit,
        worktree=WorktreeRef(worktree, base_commit, None),
        repository_authority=live_repo_authority,
        admin_baseline=baseline,
        admin_prepare=current,
        admin_worker_start=admin_worker_start,
        admin_reconciliation=reconciliation,
        primary_prepare=primary_prepare,
        primary_worker_start=primary_worker_start,
        primary_prepare_head=primary_prepare_head,
        primary_worker_start_head=primary_worker_start_head,
        worktree_start=start,
        cumulative_start=cumulative_start,
        worktree_authority=worktree_authority,
        seal=seal,
        git_journal_path=journal,
        new_loose_objects=reconciliation.new_loose_objects,
    )
