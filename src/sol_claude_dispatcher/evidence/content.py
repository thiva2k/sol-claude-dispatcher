"""Authoritative byte classification for dispatcher-native evidence.

This module receives bytes from the pre-worker seal and the verified
post-worker filesystem reader.  It never opens a repository path itself and
never invokes Git; provenance remains with those two producers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Mapping

__all__ = [
    "ContentClass",
    "ContentInput",
    "ContentSide",
    "AuthoritativeContent",
    "PathClass",
    "ClassifiedInventory",
    "classify_input",
    "classify_change",
    "classify_inventory",
    "git_blob_oid",
]


class ContentClass(str, Enum):
    TEXT_CANDIDATE = "text_candidate"
    UNTEXTUAL = "untextual"
    UNREPRESENTABLE_KIND = "unrepresentable_kind"
    OVERSIZED = "oversized"
    UNREADABLE = "unreadable"
    CHANGED_DURING_MEASUREMENT = "changed_during_measurement"
    ABSENT = "absent"


ContentKind = Literal[
    "regular", "symlink", "gitlink", "directory", "fifo", "socket", "block", "char", "absent"
]


def git_blob_oid(data: bytes) -> str:
    """Return Git's SHA-1 blob identity for exact bytes."""
    header = b"blob " + str(len(data)).encode("ascii") + b"\0"
    return hashlib.sha1(header + data).hexdigest()


@dataclass(frozen=True)
class ContentInput:
    """One authoritative side before content classification."""

    kind: ContentKind
    data: bytes | None
    mode: int | None
    read_error: str | None = None

    @classmethod
    def regular(cls, data: bytes, *, executable: bool = False) -> "ContentInput":
        return cls("regular", bytes(data), 0o100755 if executable else 0o100644)

    @classmethod
    def symlink(cls, target: bytes) -> "ContentInput":
        return cls("symlink", bytes(target), 0o120000)

    @classmethod
    def absent(cls) -> "ContentInput":
        return cls("absent", None, None)


@dataclass(frozen=True)
class ContentSide:
    """A classified side; inventory truth and reviewability stay separate."""

    kind: ContentKind
    data: bytes | None
    mode: int | None
    size: int | None
    sha256_digest: str | None
    oid: str | None
    content_class: ContentClass
    inventory_complete: bool
    read_error: str | None

    @property
    def representable(self) -> bool:
        return self.content_class in {ContentClass.TEXT_CANDIDATE, ContentClass.ABSENT}


@dataclass(frozen=True)
class AuthoritativeContent:
    """Both sealed sides of one raw repository-relative path."""

    path: bytes
    old: ContentSide
    new: ContentSide
    change: Literal[
        "added", "removed", "modified", "kind_changed", "mode_changed", "link_target_changed", "unchanged"
    ]


@dataclass(frozen=True)
class PathClass:
    """Stage-3 content classification for one already-decided identity row."""

    path: bytes
    content: AuthoritativeContent
    content_class: ContentClass
    ignored_by_base: bool
    inventory_complete: bool


@dataclass(frozen=True)
class ClassifiedInventory:
    """Classification cannot exist without the preceding scope verdict."""

    identity: Any
    verdict: Any
    classes: tuple[PathClass, ...]


def classify_input(
    source: ContentInput, *, maximum_bytes: int = 8_000_000
) -> ContentSide:
    """Classify one authoritative side without reading or following anything."""
    if maximum_bytes < 0:
        raise ValueError("maximum_bytes must be non-negative")

    if source.kind == "absent":
        return ContentSide(
            kind="absent",
            data=None,
            mode=None,
            size=None,
            sha256_digest=None,
            oid=None,
            content_class=ContentClass.ABSENT,
            inventory_complete=True,
            read_error=None,
        )

    if source.read_error is not None:
        changed = source.read_error == "changed_during_measurement"
        return ContentSide(
            kind=source.kind,
            data=None,
            mode=source.mode,
            size=None,
            sha256_digest=None,
            oid=None,
            content_class=(
                ContentClass.CHANGED_DURING_MEASUREMENT
                if changed
                else ContentClass.UNREADABLE
            ),
            inventory_complete=False,
            read_error=source.read_error,
        )

    if source.kind not in {"regular", "symlink"}:
        return ContentSide(
            kind=source.kind,
            data=None,
            mode=source.mode,
            size=None,
            sha256_digest=None,
            oid=None,
            content_class=ContentClass.UNREPRESENTABLE_KIND,
            inventory_complete=True,
            read_error=None,
        )

    if source.data is None:
        return ContentSide(
            kind=source.kind,
            data=None,
            mode=source.mode,
            size=None,
            sha256_digest=None,
            oid=None,
            content_class=ContentClass.UNREADABLE,
            inventory_complete=False,
            read_error="authoritative_bytes_absent",
        )

    data = bytes(source.data)
    digest = hashlib.sha256(data).hexdigest()
    oid = git_blob_oid(data)
    if len(data) > maximum_bytes:
        return ContentSide(
            kind=source.kind,
            data=None,
            mode=source.mode,
            size=len(data),
            sha256_digest=digest,
            oid=oid,
            content_class=ContentClass.OVERSIZED,
            inventory_complete=False,
            read_error="maximum_bytes_exceeded",
        )

    # A symlink's Git object is its raw target bytes. It remains exactly
    # representable even when those bytes are not UTF-8; following or decoding
    # the target would destroy the authority this type carries.
    if source.kind == "symlink":
        classification = ContentClass.TEXT_CANDIDATE
    else:
        try:
            data.decode("utf-8")
            text = True
        except UnicodeDecodeError:
            text = False
        classification = (
            ContentClass.TEXT_CANDIDATE
            if text and b"\0" not in data[:8192]
            else ContentClass.UNTEXTUAL
        )
    return ContentSide(
        kind=source.kind,
        data=data,
        mode=source.mode,
        size=len(data),
        sha256_digest=digest,
        oid=oid,
        content_class=classification,
        inventory_complete=True,
        read_error=None,
    )


def classify_change(
    path: bytes,
    old: ContentInput,
    new: ContentInput,
    *,
    maximum_bytes: int = 8_000_000,
) -> AuthoritativeContent:
    """Classify both sides and derive the orthogonal identity change."""
    raw_path = bytes(path)
    if not raw_path or raw_path.startswith(b"/") or b"\0" in raw_path:
        raise ValueError("path must be non-empty repository-relative raw bytes")
    old_side = classify_input(old, maximum_bytes=maximum_bytes)
    new_side = classify_input(new, maximum_bytes=maximum_bytes)

    if old_side.kind == "absent" and new_side.kind != "absent":
        change = "added"
    elif old_side.kind != "absent" and new_side.kind == "absent":
        change = "removed"
    elif old_side.kind != new_side.kind:
        change = "kind_changed"
    elif old_side.mode != new_side.mode:
        change = "mode_changed"
    elif old_side.data != new_side.data:
        change = "link_target_changed" if old_side.kind == "symlink" else "modified"
    else:
        change = "unchanged"

    return AuthoritativeContent(raw_path, old_side, new_side, change)


def classify_inventory(
    identity: Any,
    verdict: Any,
    authoritative_by_path: Mapping[bytes, tuple[ContentInput, ContentInput]],
    *,
    maximum_bytes: int = 8_000_000,
) -> ClassifiedInventory:
    """Classify every identity row only after its scope verdict exists.

    ``identity`` and ``verdict`` are duck-typed deliberately: those concurrent
    Wave-0 modules remain dependency-light, while the digest equality and exact
    path coverage are still enforced here at runtime.
    """
    digest = getattr(identity, "digest", None)
    if getattr(verdict, "decided_over_digest", None) != digest:
        raise ValueError("scope verdict was not decided over this identity set")
    identity_changes = tuple(getattr(identity, "changes"))
    expected = {bytes(row.path) for row in identity_changes}
    supplied = {bytes(path) for path in authoritative_by_path}
    if expected != supplied:
        raise ValueError("authoritative content coverage must equal the identity path set")
    classes: list[PathClass] = []
    for row in identity_changes:
        path = bytes(row.path)
        old, new = authoritative_by_path[path]
        content = classify_change(path, old, new, maximum_bytes=maximum_bytes)
        relevant = [side for side in (content.old, content.new) if side.kind != "absent"]
        classification = next(
            (
                side.content_class
                for side in relevant
                if side.content_class is not ContentClass.TEXT_CANDIDATE
            ),
            ContentClass.TEXT_CANDIDATE,
        )
        classes.append(
            PathClass(
                path=path,
                content=content,
                content_class=classification,
                ignored_by_base=bool(getattr(row, "ignored_by_base", False)),
                inventory_complete=all(side.inventory_complete for side in relevant),
            )
        )
    return ClassifiedInventory(identity=identity, verdict=verdict, classes=tuple(classes))
