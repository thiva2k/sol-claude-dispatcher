"""Immutable, per-task pre-worker evidence seal.

The Git layer supplies raw row outputs.  This module verifies them, publishes a
content-addressed store and writes ``seal-manifest.json`` atomically *last*.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from ..errors import (
    BaseObjectVerificationFailed,
    RepositoryIdentityUnsealed,
    SealAbsentAfterWorker,
    SealIntegrityFailed,
)
from ..models import utc_now
from .basetree import (
    BaseTreeSnapshot,
    build_base_tree_snapshot,
    git_blob_oid,
    parse_cat_file_batch,
    parse_ls_tree_z,
)
from .identity import RepositoryAuthoritySnapshot
from .identity_record import RepositoryIdentityRecord


@dataclass(frozen=True)
class SealedArtefact:
    relpath: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, object]:
        return {"relpath": self.relpath, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True)
class SealManifest:
    schema_version: int
    task_id: str
    base_commit: str
    sealed_at: str
    sealed_before_pid: int | None
    artefacts: tuple[SealedArtefact, ...]
    cas_root_hash: str
    manifest_hash: str

    def unsigned_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "base_commit": self.base_commit,
            "sealed_at": self.sealed_at,
            "sealed_before_pid": self.sealed_before_pid,
            "artefacts": [item.to_dict() for item in self.artefacts],
            "cas_root_hash": self.cas_root_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.unsigned_dict(), "manifest_hash": self.manifest_hash}


@dataclass(frozen=True)
class LoadedTaskSeal:
    materialisation: Path
    manifest_path: Path
    manifest: SealManifest
    base_tree: BaseTreeSnapshot
    identity_record: RepositoryIdentityRecord | None = None
    artefact_payloads: tuple[tuple[str, bytes], ...] = ()

    def artefact_bytes(self, relpath: str) -> bytes:
        """Return bytes authenticated during this exact seal load."""
        for candidate, payload in self.artefact_payloads:
            if candidate == relpath:
                return payload
        raise SealIntegrityFailed(
            "A required sealed artefact is absent.", details={"relpath": relpath}
        )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii") + b"\n"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: Path, payload: bytes, mode: int = 0o600) -> None:
    """Publish a new regular file in its destination directory."""

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_st = os.lstat(path.parent)
    if not stat.S_ISDIR(parent_st.st_mode):
        raise SealIntegrityFailed(
            "A seal destination parent is not a real directory.",
            details={"path": str(path.parent)},
        )
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink():
            raise SealIntegrityFailed(
                "An immutable seal file already exists.",
                details={"path": str(path)},
            )
        os.replace(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _cas_root_hash(pairs: Mapping[str, int]) -> str:
    digest = hashlib.sha256()
    for oid, size in sorted(pairs.items()):
        digest.update(oid.encode("ascii"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _enumerate_cas(cas_root: Path) -> dict[str, Path]:
    """Return the exact canonical CAS name set and refuse every other shape."""

    result: dict[str, Path] = {}
    if not cas_root.exists():
        return result
    root_st = os.lstat(cas_root)
    if not stat.S_ISDIR(root_st.st_mode):
        raise SealIntegrityFailed("The CAS root is not a real directory.")
    for fanout in os.scandir(cas_root):
        if (
            len(fanout.name) != 2
            or any(ch not in "0123456789abcdef" for ch in fanout.name)
            or not fanout.is_dir(follow_symlinks=False)
        ):
            raise SealIntegrityFailed(
                "The CAS contains a non-canonical fanout entry.",
                details={"entry": fanout.name},
            )
        for entry in os.scandir(fanout.path):
            oid = fanout.name + entry.name
            if (
                len(entry.name) != 38
                or any(ch not in "0123456789abcdef" for ch in entry.name)
                or not entry.is_file(follow_symlinks=False)
                or oid in result
            ):
                raise SealIntegrityFailed(
                    "The CAS contains a non-canonical object entry.",
                    details={"entry": oid},
                )
            result[oid] = Path(entry.path)
    return result


def _write_cas_blob(materialisation: Path, oid: str, data: bytes) -> None:
    if git_blob_oid(data) != oid:
        raise BaseObjectVerificationFailed(
            "CAS bytes do not match their filename object id.", details={"oid": oid}
        )
    destination = materialisation / "cas" / oid[:2] / oid[2:]
    if destination.exists() or destination.is_symlink():
        try:
            current = destination.read_bytes()
            st = os.lstat(destination)
        except OSError as exc:
            raise SealIntegrityFailed(
                "An existing CAS entry is unreadable.", details={"oid": oid}
            ) from exc
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or current != data:
            raise SealIntegrityFailed(
                "An existing CAS entry does not match its object id.",
                details={"oid": oid},
            )
        return
    _atomic_write(destination, data)
    st = os.lstat(destination)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise SealIntegrityFailed(
            "A published CAS entry is not a private regular file.",
            details={"oid": oid},
        )


def _discard_incomplete_outputs(root: Path, artefact_names: Mapping[str, bytes]) -> None:
    """Remove only files this builder owns when no manifest was ever published."""

    owned = {"base-tree.json", *artefact_names.keys()}
    for relpath in owned:
        _validate_artefact_relpath(relpath)
        path = root.joinpath(*relpath.split("/"))
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink()
    cas = root / "cas"
    try:
        cas_st = os.lstat(cas)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(cas_st.st_mode) and not stat.S_ISLNK(cas_st.st_mode):
        shutil.rmtree(cas)
    else:
        cas.unlink()


def create_task_seal(
    materialisation: str | os.PathLike[str],
    *,
    task_id: str,
    base_commit: str,
    ls_tree_output: bytes,
    route_a_by_path: Mapping[bytes, bytes],
    route_b_batch_output: bytes,
    artefacts: Mapping[str, bytes] | None = None,
    identity_factory: Callable[[BaseTreeSnapshot, str, str], RepositoryIdentityRecord]
    | None = None,
) -> LoadedTaskSeal:
    """Create a total seal from injected G2/G8 outputs.

    Route A is accepted only when independently hashed start bytes equal the
    tree oid.  All other non-gitlink entries must appear, in oid order, in the
    injected Route-B batch response.
    """

    root = Path(materialisation)
    manifest_path = root / "seal-manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise SealIntegrityFailed(
            "A task seal already exists and is immutable.",
            details={"path": str(manifest_path)},
        )
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root_st = os.lstat(root)
    if not stat.S_ISDIR(root_st.st_mode):
        raise SealIntegrityFailed("The materialisation root is not a real directory.")
    try:
        os.chmod(root, 0o700)
    except OSError as exc:
        raise SealIntegrityFailed("The materialisation directory is not private.") from exc

    additional = artefacts or {}
    _discard_incomplete_outputs(root, additional)
    identities = parse_ls_tree_z(ls_tree_output)
    content: dict[str, bytes] = {}
    sources: dict[str, str] = {}
    for entry in identities:
        if entry.kind == "gitlink":
            continue
        start = route_a_by_path.get(entry.path)
        if start is not None and git_blob_oid(start) == entry.oid:
            content[entry.oid] = start
            sources[entry.oid] = "start_walk"
    unresolved: list[str] = []
    for entry in identities:
        if (
            entry.kind != "gitlink"
            and entry.oid not in content
            and entry.oid not in unresolved
        ):
            unresolved.append(entry.oid)
    route_b = parse_cat_file_batch(unresolved, route_b_batch_output)
    for oid, data in route_b.items():
        content[oid] = data
        sources[oid] = "cat_file_batch"

    # build_base_tree_snapshot is the A-union-B totality assertion.
    snapshot = build_base_tree_snapshot(
        base_commit, identities, content, source_by_oid=sources  # type: ignore[arg-type]
    )
    for oid, data in sorted(content.items()):
        _write_cas_blob(root, oid, data)

    base_tree_bytes = _canonical_json(snapshot.to_dict())
    base_tree_hash = _sha256(base_tree_bytes)
    sealed_at = utc_now().isoformat().replace("+00:00", "Z")
    payloads = {"base-tree.json": base_tree_bytes}
    for relpath, payload in additional.items():
        _validate_artefact_relpath(relpath)
        if relpath in payloads or relpath == "seal-manifest.json" or relpath.startswith("cas/"):
            raise ValueError(f"reserved sealed artefact path: {relpath}")
        payloads[relpath] = bytes(payload)
    if identity_factory is not None:
        if "identity-record.json" in payloads:
            raise ValueError("identity-record.json is owned by identity_factory")
        identity = identity_factory(snapshot, base_tree_hash, sealed_at)
        payloads["identity-record.json"] = identity.to_json_bytes()

    sealed_artefacts: list[SealedArtefact] = []
    for relpath, payload in sorted(payloads.items()):
        destination = root.joinpath(*relpath.split("/"))
        _atomic_write(destination, payload)
        sealed_artefacts.append(
            SealedArtefact(relpath=relpath, sha256=_sha256(payload), size=len(payload))
        )

    cas_sizes = {oid: len(data) for oid, data in content.items()}
    unsigned = {
        "schema_version": 1,
        "task_id": task_id,
        "base_commit": base_commit,
        "sealed_at": sealed_at,
        "sealed_before_pid": None,
        "artefacts": [item.to_dict() for item in sealed_artefacts],
        "cas_root_hash": _cas_root_hash(cas_sizes),
    }
    manifest = SealManifest(
        schema_version=1,
        task_id=task_id,
        base_commit=base_commit,
        sealed_at=sealed_at,
        sealed_before_pid=None,
        artefacts=tuple(sealed_artefacts),
        cas_root_hash=str(unsigned["cas_root_hash"]),
        manifest_hash=_sha256(_canonical_json(unsigned)),
    )
    # Loaders define existence by this file.  It is intentionally the final
    # publication operation in the successful path.
    _atomic_write(manifest_path, _canonical_json(manifest.to_dict()))
    return load_task_seal(root, require_identity=identity_factory is not None)


def _validate_artefact_relpath(relpath: str) -> None:
    if not relpath or relpath.startswith("/") or "\\" in relpath:
        raise ValueError("sealed artefact path must be POSIX-relative")
    parts = relpath.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("sealed artefact path contains an unsafe component")


def _parse_manifest(data: bytes) -> SealManifest:
    try:
        value = json.loads(data)
        if value.get("schema_version") != 1:
            raise ValueError("unsupported schema")
        raw_artefacts = value["artefacts"]
        artefacts = tuple(
            SealedArtefact(
                relpath=str(item["relpath"]),
                sha256=str(item["sha256"]),
                size=int(item["size"]),
            )
            for item in raw_artefacts
        )
        manifest = SealManifest(
            schema_version=1,
            task_id=str(value["task_id"]),
            base_commit=str(value["base_commit"]),
            sealed_at=str(value["sealed_at"]),
            sealed_before_pid=(
                None
                if value.get("sealed_before_pid") is None
                else int(value["sealed_before_pid"])
            ),
            artefacts=artefacts,
            cas_root_hash=str(value["cas_root_hash"]),
            manifest_hash=str(value["manifest_hash"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SealIntegrityFailed("The seal manifest is malformed.") from exc
    expected_hash = _sha256(_canonical_json(manifest.unsigned_dict()))
    if manifest.manifest_hash != expected_hash:
        raise SealIntegrityFailed("The seal manifest hash does not verify.")
    relpaths = tuple(item.relpath for item in manifest.artefacts)
    if relpaths != tuple(sorted(relpaths)) or len(relpaths) != len(set(relpaths)):
        raise SealIntegrityFailed("The seal manifest artefact set is not canonical.")
    return manifest


def load_task_seal(
    materialisation: str | os.PathLike[str], *, require_identity: bool = False
) -> LoadedTaskSeal:
    """Load and verify an existing seal without trusting manifest assertions."""

    root = Path(materialisation)
    manifest_path = root / "seal-manifest.json"
    try:
        manifest_st = os.lstat(manifest_path)
        if not stat.S_ISREG(manifest_st.st_mode):
            raise SealIntegrityFailed("The seal manifest is not a regular file.")
        manifest = _parse_manifest(manifest_path.read_bytes())
    except FileNotFoundError as exc:
        raise SealIntegrityFailed("The task seal is absent.") from exc

    artefact_payloads: dict[str, bytes] = {}
    for artefact in manifest.artefacts:
        try:
            _validate_artefact_relpath(artefact.relpath)
            path = root.joinpath(*artefact.relpath.split("/"))
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode):
                raise OSError("not regular")
            payload = path.read_bytes()
        except (OSError, ValueError) as exc:
            raise SealIntegrityFailed(
                "A sealed artefact is missing or unsupported.",
                details={"relpath": artefact.relpath},
            ) from exc
        if len(payload) != artefact.size or _sha256(payload) != artefact.sha256:
            raise SealIntegrityFailed(
                "A sealed artefact digest does not verify.",
                details={"relpath": artefact.relpath},
            )
        artefact_payloads[artefact.relpath] = payload

    try:
        base_value = json.loads(artefact_payloads["base-tree.json"])
        base_tree = BaseTreeSnapshot.from_dict(base_value)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SealIntegrityFailed("The sealed base-tree snapshot is malformed.") from exc
    if base_tree.base_commit != manifest.base_commit:
        raise SealIntegrityFailed("The seal and base-tree commits disagree.")

    identity: RepositoryIdentityRecord | None = None
    identity_payload = artefact_payloads.get("identity-record.json")
    if identity_payload is None:
        if require_identity:
            raise RepositoryIdentityUnsealed(
                "The task seal has no repository identity record.",
                details={"relpath": "identity-record.json"},
            )
    else:
        try:
            identity = RepositoryIdentityRecord.from_json_bytes(identity_payload)
        except ValueError as exc:
            raise RepositoryIdentityUnsealed(
                "The sealed repository identity record is malformed.",
                details={"relpath": "identity-record.json"},
            ) from exc
        base_tree_artefact = next(
            item for item in manifest.artefacts if item.relpath == "base-tree.json"
        )
        if (
            identity.task_id != manifest.task_id
            or identity.base_commit != manifest.base_commit
            or identity.base_tree_manifest_hash != base_tree_artefact.sha256
            or identity.sealed_at != manifest.sealed_at
        ):
            raise RepositoryIdentityUnsealed(
                "The sealed repository identity does not match its seal manifest.",
                details={"relpath": "identity-record.json"},
            )
        authority_payload = artefact_payloads.get("repository-authority.json")
        if authority_payload is None:
            raise RepositoryIdentityUnsealed(
                "The sealed repository identity has no repository authority operand.",
                details={"relpath": "repository-authority.json"},
            )
        try:
            authority_value = json.loads(authority_payload)
            if not isinstance(authority_value, Mapping):
                raise ValueError("authority root is not an object")
            repository_authority = RepositoryAuthoritySnapshot.from_json_dict(
                authority_value
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RepositoryIdentityUnsealed(
                "The repository authority bound to sealed identity is malformed.",
                details={"relpath": "repository-authority.json"},
            ) from exc
        if (
            identity.canonical_root != repository_authority.canonical_root
            or identity.git_dir != repository_authority.git_dir
            or identity.common_dir != repository_authority.common_dir
        ):
            raise RepositoryIdentityUnsealed(
                "The sealed identity and repository authority disagree.",
                details={"relpath": "identity-record.json"},
            )
        identity.require_current_pins()

    expected_oids = {
        entry.oid: entry.content.size
        for entry in base_tree.entries
        if entry.content is not None
    }
    actual_oids: dict[str, int] = {}
    cas_root = root / "cas"
    actual_paths = _enumerate_cas(cas_root)
    if set(actual_paths) != set(expected_oids):
        raise SealIntegrityFailed(
            "The CAS object set does not equal the sealed base-tree object set.",
            details={
                "missing": sorted(set(expected_oids) - set(actual_paths)),
                "extra": sorted(set(actual_paths) - set(expected_oids)),
            },
        )
    for oid, size in expected_oids.items():
        path = actual_paths[oid]
        try:
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise OSError("not a private regular file")
            data = path.read_bytes()
        except OSError as exc:
            raise SealIntegrityFailed(
                "A required CAS entry is missing or unsupported.", details={"oid": oid}
            ) from exc
        if len(data) != size or git_blob_oid(data) != oid:
            raise SealIntegrityFailed(
                "A CAS entry does not self-verify.", details={"oid": oid}
            )
        actual_oids[oid] = len(data)
    if _cas_root_hash(actual_oids) != manifest.cas_root_hash:
        raise SealIntegrityFailed("The CAS root hash does not verify.")
    return LoadedTaskSeal(
        materialisation=root,
        manifest_path=manifest_path,
        manifest=manifest,
        base_tree=base_tree,
        identity_record=identity,
        artefact_payloads=tuple(sorted(artefact_payloads.items())),
    )


def load_or_create_task_seal(
    materialisation: str | os.PathLike[str],
    *,
    worker_has_run: bool,
    builder: Callable[[], LoadedTaskSeal],
) -> LoadedTaskSeal:
    """Per-task entry point: verify existing, create once, never reconstruct."""

    manifest = Path(materialisation) / "seal-manifest.json"
    if manifest.exists() or manifest.is_symlink():
        return load_task_seal(materialisation)
    if worker_has_run:
        raise SealAbsentAfterWorker(
            "The pre-worker seal is absent after a worker ran and cannot be rebuilt.",
            details={"materialisation": str(materialisation)},
        )
    return builder()
