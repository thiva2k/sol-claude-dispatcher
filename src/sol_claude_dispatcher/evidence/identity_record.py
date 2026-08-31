"""Strict, once-per-task repository identity sealed during PREPARE.

The raw repository authority is a filesystem-layout measurement.  This record
binds that measurement to the approved guidance facts, the administrative
gate, the G1-verified base and the exact Git pin set.  Resume and review load
this object from the task seal; they never reconstruct identity from the live
guidance manifest.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from ..errors import SealPinSetStale
from ..project_guidance import RepositoryIdentity
from .git_order import PIN_NAMES
from .identity import RepositoryAuthoritySnapshot

__all__ = [
    "ApprovedIdentityFacts",
    "RawAdminGateResult",
    "RepositoryIdentityRecord",
    "build_identity_record",
]

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii") + b"\n"


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: object, *, field: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field} is not canonical base64") from exc


@dataclass(frozen=True, slots=True)
class ApprovedIdentityFacts:
    """The approved, non-measured identity half supplied at initial PREPARE."""

    authority: Literal["approved_guidance", "no_guidance"]
    manifest_path: str | None
    manifest_sha256: str | None
    approval_state: str | None
    approval_version: str | None
    repository_id: str | None
    pin_toplevel: str | None
    pin_git_dir: str | None
    pin_origin_url: str | None
    pin_root_commit: str | None

    @classmethod
    def no_guidance(cls) -> "ApprovedIdentityFacts":
        return cls("no_guidance", None, None, None, None, None, None, None, None, None)

    def __post_init__(self) -> None:
        values = (
            self.manifest_path,
            self.manifest_sha256,
            self.approval_state,
            self.approval_version,
            self.repository_id,
            self.pin_toplevel,
            self.pin_git_dir,
            self.pin_origin_url,
            self.pin_root_commit,
        )
        if self.authority == "no_guidance":
            if any(value is not None for value in values):
                raise ValueError("no-guidance identity cannot carry approved pins")
            return
        if self.authority != "approved_guidance" or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise ValueError("approved-guidance identity requires every approved fact")
        assert self.manifest_sha256 is not None
        assert self.pin_root_commit is not None
        if _SHA256_RE.fullmatch(self.manifest_sha256) is None:
            raise ValueError("manifest_sha256 must be 64 lowercase hex")
        if _COMMIT_RE.fullmatch(self.pin_root_commit) is None:
            raise ValueError("approved root commit must be exact lowercase 40-hex")

    def to_repository_identity(
        self, authority: RepositoryAuthoritySnapshot
    ) -> RepositoryIdentity | None:
        if self.authority == "no_guidance":
            return None
        assert self.pin_origin_url is not None and self.pin_root_commit is not None
        return RepositoryIdentity(
            toplevel=authority.canonical_root.decode(errors="surrogateescape"),
            git_dir=authority.git_dir.decode(errors="surrogateescape"),
            origin_url=self.pin_origin_url,
            root_commit=self.pin_root_commit,
        )


@dataclass(frozen=True, slots=True)
class RawAdminGateResult:
    """Verbatim inputs and decision of the raw PREPARE administration gate."""

    decision: Literal["reconciled"]
    baseline: Mapping[str, Any]
    prepare_capture: Mapping[str, Any]
    baseline_digest: str
    capture_digest: str
    new_loose_objects: tuple[str, ...]

    @classmethod
    def build(
        cls,
        *,
        baseline: Mapping[str, Any],
        prepare_capture: Mapping[str, Any],
        new_loose_objects: tuple[str, ...],
    ) -> "RawAdminGateResult":
        return cls(
            decision="reconciled",
            baseline=dict(baseline),
            prepare_capture=dict(prepare_capture),
            baseline_digest=_sha256(baseline),
            capture_digest=_sha256(prepare_capture),
            new_loose_objects=tuple(new_loose_objects),
        )

    def __post_init__(self) -> None:
        if self.decision != "reconciled":
            raise ValueError("only a reconciled administration gate may be sealed")
        if self.baseline_digest != _sha256(self.baseline):
            raise ValueError("administration baseline digest does not verify")
        if self.capture_digest != _sha256(self.prepare_capture):
            raise ValueError("administration capture digest does not verify")

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "baseline": dict(self.baseline),
            "prepare_capture": dict(self.prepare_capture),
            "baseline_digest": self.baseline_digest,
            "capture_digest": self.capture_digest,
            "new_loose_objects": list(self.new_loose_objects),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RawAdminGateResult":
        expected = {
            "decision",
            "baseline",
            "prepare_capture",
            "baseline_digest",
            "capture_digest",
            "new_loose_objects",
        }
        if set(value) != expected:
            raise ValueError("admin_gate fields differ from the sealed schema")
        if not isinstance(value["baseline"], Mapping) or not isinstance(
            value["prepare_capture"], Mapping
        ):
            raise ValueError("admin_gate snapshots must be JSON objects")
        if value["decision"] != "reconciled" or not all(
            isinstance(value[name], str)
            for name in ("baseline_digest", "capture_digest")
        ):
            raise ValueError("admin_gate decision or digests are malformed")
        loose = value["new_loose_objects"]
        if not isinstance(loose, list) or not all(isinstance(v, str) for v in loose):
            raise ValueError("new_loose_objects must be a string list")
        return cls(
            decision=value["decision"],
            baseline=dict(value["baseline"]),
            prepare_capture=dict(value["prepare_capture"]),
            baseline_digest=value["baseline_digest"],
            capture_digest=value["capture_digest"],
            new_loose_objects=tuple(loose),
        )


@dataclass(frozen=True, slots=True)
class RepositoryIdentityRecord:
    schema_version: int
    task_id: str
    canonical_root: bytes
    canonical_root_source: Literal["r3_realpath"]
    authority: Literal["approved_guidance", "no_guidance"]
    manifest_path: str | None
    manifest_sha256: str | None
    approval_state: str | None
    approval_version: str | None
    repository_id: str | None
    pin_toplevel: str | None
    pin_git_dir: str | None
    pin_origin_url: str | None
    pin_root_commit: str | None
    root_commit_provenance: Literal["approved_onboarding_fact", "absent"]
    origin_url_provenance: Literal[
        "raw_config_bytes", "approved_onboarding_fact", "absent"
    ]
    admin_gate: RawAdminGateResult
    base_commit: str
    base_commit_verified_by: Literal["g1_byte_equality"]
    base_tree_manifest_hash: str
    git_dir: bytes
    common_dir: bytes
    layout_resolver: Literal["raw"]
    pins_applied: tuple[str, ...]
    sealed_at: str
    provenance: Literal["sealed_at_prepare"]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.canonical_root_source != "r3_realpath":
            raise ValueError("unsupported repository identity record schema")
        if self.layout_resolver != "raw" or self.provenance != "sealed_at_prepare":
            raise ValueError("repository identity record has invalid provenance")
        if self.base_commit_verified_by != "g1_byte_equality":
            raise ValueError("base commit lacks G1 byte-equality provenance")
        if _COMMIT_RE.fullmatch(self.base_commit) is None:
            raise ValueError("base commit must be exact lowercase 40-hex")
        if _SHA256_RE.fullmatch(self.base_tree_manifest_hash) is None:
            raise ValueError("base tree manifest hash must be 64 lowercase hex")
        if not self.task_id or not self.sealed_at:
            raise ValueError("identity record task_id and sealed_at are required")
        if not all(isinstance(v, bytes) and v.startswith(b"/") for v in (
            self.canonical_root,
            self.git_dir,
            self.common_dir,
        )):
            raise ValueError("identity authority paths must be absolute bytes")
        facts = ApprovedIdentityFacts(
            self.authority,
            self.manifest_path,
            self.manifest_sha256,
            self.approval_state,
            self.approval_version,
            self.repository_id,
            self.pin_toplevel,
            self.pin_git_dir,
            self.pin_origin_url,
            self.pin_root_commit,
        )
        if facts.authority == "approved_guidance":
            if self.root_commit_provenance != "approved_onboarding_fact":
                raise ValueError("approved root commit lacks onboarding provenance")
            if self.origin_url_provenance not in {
                "approved_onboarding_fact",
                "raw_config_bytes",
            }:
                raise ValueError("approved origin URL lacks permitted provenance")
        elif (
            self.root_commit_provenance != "absent"
            or self.origin_url_provenance != "absent"
        ):
            raise ValueError("no-guidance record must mark identity pins absent")
        if len(set(self.pins_applied)) != len(self.pins_applied):
            raise ValueError("identity record pin set contains duplicates")

    def to_repository_identity(self) -> RepositoryIdentity | None:
        if self.authority == "no_guidance":
            return None
        assert self.pin_origin_url is not None and self.pin_root_commit is not None
        return RepositoryIdentity(
            toplevel=self.canonical_root.decode(errors="surrogateescape"),
            git_dir=self.git_dir.decode(errors="surrogateescape"),
            origin_url=self.pin_origin_url,
            root_commit=self.pin_root_commit,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "canonical_root_b64": _b64(self.canonical_root),
            "canonical_root_source": self.canonical_root_source,
            "authority": self.authority,
            "manifest_path": self.manifest_path,
            "manifest_sha256": self.manifest_sha256,
            "approval_state": self.approval_state,
            "approval_version": self.approval_version,
            "repository_id": self.repository_id,
            "pin_toplevel": self.pin_toplevel,
            "pin_git_dir": self.pin_git_dir,
            "pin_origin_url": self.pin_origin_url,
            "pin_root_commit": self.pin_root_commit,
            "root_commit_provenance": self.root_commit_provenance,
            "origin_url_provenance": self.origin_url_provenance,
            "admin_gate": self.admin_gate.to_dict(),
            "base_commit": self.base_commit,
            "base_commit_verified_by": self.base_commit_verified_by,
            "base_tree_manifest_hash": self.base_tree_manifest_hash,
            "git_dir_b64": _b64(self.git_dir),
            "common_dir_b64": _b64(self.common_dir),
            "layout_resolver": self.layout_resolver,
            "pins_applied": list(self.pins_applied),
            "sealed_at": self.sealed_at,
            "provenance": self.provenance,
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepositoryIdentityRecord":
        expected = {
            "schema_version", "task_id", "canonical_root_b64",
            "canonical_root_source", "authority", "manifest_path",
            "manifest_sha256", "approval_state", "approval_version",
            "repository_id", "pin_toplevel", "pin_git_dir", "pin_origin_url",
            "pin_root_commit", "root_commit_provenance", "origin_url_provenance",
            "admin_gate", "base_commit", "base_commit_verified_by",
            "base_tree_manifest_hash", "git_dir_b64", "common_dir_b64",
            "layout_resolver", "pins_applied", "sealed_at", "provenance",
        }
        if set(value) != expected:
            raise ValueError("identity-record fields differ from the sealed schema")
        if (
            not isinstance(value["schema_version"], int)
            or isinstance(value["schema_version"], bool)
        ):
            raise ValueError("identity-record schema_version is malformed")
        required_text = (
            "task_id", "canonical_root_source", "authority",
            "root_commit_provenance", "origin_url_provenance", "base_commit",
            "base_commit_verified_by", "base_tree_manifest_hash",
            "layout_resolver", "sealed_at", "provenance",
        )
        if any(not isinstance(value[name], str) for name in required_text):
            raise ValueError("identity-record required text fields are malformed")
        admin = value["admin_gate"]
        pins = value["pins_applied"]
        if not isinstance(admin, Mapping) or not isinstance(pins, list) or not all(
            isinstance(pin, str) for pin in pins
        ):
            raise ValueError("identity-record nested fields are malformed")
        optional = (
            "manifest_path", "manifest_sha256", "approval_state",
            "approval_version", "repository_id", "pin_toplevel", "pin_git_dir",
            "pin_origin_url", "pin_root_commit",
        )
        if any(value[name] is not None and not isinstance(value[name], str) for name in optional):
            raise ValueError("identity-record optional facts must be strings or null")
        return cls(
            schema_version=value["schema_version"],
            task_id=value["task_id"],
            canonical_root=_unb64(value["canonical_root_b64"], field="canonical_root_b64"),
            canonical_root_source=value["canonical_root_source"],
            authority=value["authority"],
            manifest_path=value["manifest_path"],
            manifest_sha256=value["manifest_sha256"],
            approval_state=value["approval_state"],
            approval_version=value["approval_version"],
            repository_id=value["repository_id"],
            pin_toplevel=value["pin_toplevel"],
            pin_git_dir=value["pin_git_dir"],
            pin_origin_url=value["pin_origin_url"],
            pin_root_commit=value["pin_root_commit"],
            root_commit_provenance=value["root_commit_provenance"],
            origin_url_provenance=value["origin_url_provenance"],
            admin_gate=RawAdminGateResult.from_dict(admin),
            base_commit=value["base_commit"],
            base_commit_verified_by=value["base_commit_verified_by"],
            base_tree_manifest_hash=value["base_tree_manifest_hash"],
            git_dir=_unb64(value["git_dir_b64"], field="git_dir_b64"),
            common_dir=_unb64(value["common_dir_b64"], field="common_dir_b64"),
            layout_resolver=value["layout_resolver"],
            pins_applied=tuple(pins),
            sealed_at=value["sealed_at"],
            provenance=value["provenance"],
        )

    @classmethod
    def from_json_bytes(cls, data: bytes) -> "RepositoryIdentityRecord":
        try:
            value = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("identity-record is not valid JSON") from exc
        if not isinstance(value, Mapping):
            raise ValueError("identity-record root must be an object")
        return cls.from_dict(value)

    def require_current_pins(self) -> None:
        if self.pins_applied != PIN_NAMES:
            raise SealPinSetStale(
                "The sealed repository identity predates the current Git pin set.",
                details={
                    "sealed_pins": list(self.pins_applied),
                    "required_pins": list(PIN_NAMES),
                },
            )


def build_identity_record(
    *,
    task_id: str,
    authority: RepositoryAuthoritySnapshot,
    approved: ApprovedIdentityFacts,
    admin_gate: RawAdminGateResult,
    base_commit: str,
    base_tree_manifest_hash: str,
    pins_applied: tuple[str, ...],
    sealed_at: str,
) -> RepositoryIdentityRecord:
    """Build the only serialisable identity provenance used by production."""

    return RepositoryIdentityRecord(
        schema_version=1,
        task_id=task_id,
        canonical_root=authority.canonical_root,
        canonical_root_source="r3_realpath",
        authority=approved.authority,
        manifest_path=approved.manifest_path,
        manifest_sha256=approved.manifest_sha256,
        approval_state=approved.approval_state,
        approval_version=approved.approval_version,
        repository_id=approved.repository_id,
        pin_toplevel=approved.pin_toplevel,
        pin_git_dir=approved.pin_git_dir,
        pin_origin_url=approved.pin_origin_url,
        pin_root_commit=approved.pin_root_commit,
        root_commit_provenance=(
            "approved_onboarding_fact"
            if approved.authority == "approved_guidance"
            else "absent"
        ),
        origin_url_provenance=(
            "approved_onboarding_fact"
            if approved.authority == "approved_guidance"
            else "absent"
        ),
        admin_gate=admin_gate,
        base_commit=base_commit,
        base_commit_verified_by="g1_byte_equality",
        base_tree_manifest_hash=base_tree_manifest_hash,
        git_dir=authority.git_dir,
        common_dir=authority.common_dir,
        layout_resolver="raw",
        pins_applied=pins_applied,
        sealed_at=sealed_at,
        provenance="sealed_at_prepare",
    )
