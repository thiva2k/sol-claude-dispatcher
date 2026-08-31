"""Raw repository-layout authority for Gate 7.

This module intentionally does not import :mod:`sol_claude_dispatcher.git` and
never starts a subprocess.  It answers the smaller question that must be
settled before Git is allowed to run: which on-disk administration directories
does an already-authorised worktree name?

Paths are carried as filesystem bytes.  Decoding a non-UTF-8 path merely so it
can be sealed would turn identity into presentation, so the JSON form uses
base64 for every byte field.
"""

from __future__ import annotations

import base64
import hashlib
import os
import stat
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Literal, Mapping, TypeAlias

from ..errors import (
    RepositoryAdministrationUnsupported,
    RepositoryLayoutUnreadable,
)

Pathish: TypeAlias = str | bytes | os.PathLike[str] | os.PathLike[bytes]

__all__ = [
    "DotGitClassification",
    "DotGitShape",
    "RepositoryAuthoritySnapshot",
    "capture_repository_authority",
    "classify_dot_git",
    "raw_realpath",
]

_MAX_INDIRECTION_BYTES = 4096
_B64_FIELDS = (
    "canonical_root",
    "dot_git_path",
    "gitfile_bytes",
    "git_dir",
    "commondir_path",
    "commondir_bytes",
    "common_dir",
)


class DotGitShape(str, Enum):
    """The exhaustive policy classification of one ``.git`` entry."""

    DIRECTORY = "directory"
    GITFILE = "gitfile"
    SYMLINK = "symlink"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class DotGitClassification:
    """An ``lstat``-derived classification; links are never followed."""

    path: bytes
    shape: DotGitShape
    mode: int
    dev: int
    ino: int
    link_target: bytes | None = None


@dataclass(frozen=True, slots=True)
class RepositoryAuthoritySnapshot:
    """Immutable raw authority sufficient for later administrative seals.

    The inode identities detect replacement of the entry or either resolved
    administration directory.  The exact gitfile and ``commondir`` bytes let a
    later seal compare indirection without re-resolving it.  Hashes are stored
    alongside those bytes for manifest integration, but never replace the byte
    equality requirement.
    """

    schema_version: int
    canonical_root: bytes
    canonical_root_source: Literal["raw_realpath"]
    canonical_root_mode: int
    canonical_root_dev: int
    canonical_root_ino: int
    dot_git_path: bytes
    dot_git_shape: DotGitShape
    dot_git_mode: int
    dot_git_dev: int
    dot_git_ino: int
    gitfile_bytes: bytes | None
    gitfile_sha256: str | None
    git_dir: bytes
    git_dir_mode: int
    git_dir_dev: int
    git_dir_ino: int
    commondir_path: bytes | None
    commondir_mode: int | None
    commondir_dev: int | None
    commondir_ino: int | None
    commondir_bytes: bytes | None
    commondir_sha256: str | None
    common_dir: bytes
    common_dir_mode: int
    common_dir_dev: int
    common_dir_ino: int
    resolver: Literal["raw"]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported RepositoryAuthoritySnapshot schema")
        if self.canonical_root_source != "raw_realpath" or self.resolver != "raw":
            raise ValueError("repository authority must record raw provenance")
        for name in ("canonical_root", "dot_git_path", "git_dir", "common_dir"):
            value = getattr(self, name)
            if not isinstance(value, bytes) or not os.path.isabs(value):
                raise ValueError(f"{name} must be an absolute byte path")
        if self.dot_git_path != os.path.join(self.canonical_root, b".git"):
            raise ValueError("dot_git_path does not belong to canonical_root")
        if not stat.S_ISDIR(self.canonical_root_mode):
            raise ValueError("canonical_root_mode must describe a directory")
        if not stat.S_ISDIR(self.git_dir_mode):
            raise ValueError("git_dir_mode must describe a directory")
        if not stat.S_ISDIR(self.common_dir_mode):
            raise ValueError("common_dir_mode must describe a directory")
        for name in (
            "canonical_root_mode",
            "canonical_root_dev",
            "canonical_root_ino",
            "dot_git_mode",
            "dot_git_dev",
            "dot_git_ino",
            "git_dir_mode",
            "git_dir_dev",
            "git_dir_ino",
            "common_dir_mode",
            "common_dir_dev",
            "common_dir_ino",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.dot_git_shape is DotGitShape.DIRECTORY:
            if not stat.S_ISDIR(self.dot_git_mode):
                raise ValueError("directory shape disagrees with dot_git_mode")
            if self.gitfile_bytes is not None or self.gitfile_sha256 is not None:
                raise ValueError("a directory .git entry cannot carry gitfile bytes")
        elif self.dot_git_shape is DotGitShape.GITFILE:
            if not stat.S_ISREG(self.dot_git_mode):
                raise ValueError("gitfile shape disagrees with dot_git_mode")
            _validate_bytes_digest(
                self.gitfile_bytes, self.gitfile_sha256, label="gitfile"
            )
        else:
            raise ValueError("unsupported .git shape cannot enter an authority seal")
        if self.commondir_path is None:
            if any(
                item is not None
                for item in (
                    self.commondir_mode,
                    self.commondir_dev,
                    self.commondir_ino,
                    self.commondir_bytes,
                    self.commondir_sha256,
                )
            ):
                raise ValueError("commondir authority requires a commondir path")
            if self.common_dir != self.git_dir:
                raise ValueError("absent commondir must use git_dir as common_dir")
            if (
                self.common_dir_mode,
                self.common_dir_dev,
                self.common_dir_ino,
            ) != (self.git_dir_mode, self.git_dir_dev, self.git_dir_ino):
                raise ValueError("absent commondir must reuse git_dir identity")
        else:
            if not os.path.isabs(self.commondir_path):
                raise ValueError("commondir_path must be absolute")
            if self.commondir_path != os.path.join(self.git_dir, b"commondir"):
                raise ValueError("commondir_path does not belong to git_dir")
            for name in ("commondir_mode", "commondir_dev", "commondir_ino"):
                value = getattr(self, name)
                if not isinstance(value, int) or value < 0:
                    raise ValueError(f"{name} must be a non-negative integer")
            assert self.commondir_mode is not None
            if not stat.S_ISREG(self.commondir_mode):
                raise ValueError("commondir_mode must describe a regular file")
            _validate_bytes_digest(
                self.commondir_bytes, self.commondir_sha256, label="commondir"
            )

    def to_json_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-compatible representation."""

        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "canonical_root_source": self.canonical_root_source,
            "canonical_root_mode": self.canonical_root_mode,
            "canonical_root_dev": self.canonical_root_dev,
            "canonical_root_ino": self.canonical_root_ino,
            "dot_git_shape": self.dot_git_shape.value,
            "dot_git_mode": self.dot_git_mode,
            "dot_git_dev": self.dot_git_dev,
            "dot_git_ino": self.dot_git_ino,
            "gitfile_sha256": self.gitfile_sha256,
            "git_dir_mode": self.git_dir_mode,
            "git_dir_dev": self.git_dir_dev,
            "git_dir_ino": self.git_dir_ino,
            "commondir_mode": self.commondir_mode,
            "commondir_dev": self.commondir_dev,
            "commondir_ino": self.commondir_ino,
            "commondir_sha256": self.commondir_sha256,
            "common_dir_mode": self.common_dir_mode,
            "common_dir_dev": self.common_dir_dev,
            "common_dir_ino": self.common_dir_ino,
            "resolver": self.resolver,
        }
        for name in _B64_FIELDS:
            value = getattr(self, name)
            result[f"{name}_b64"] = _b64(value) if value is not None else None
        return result

    @classmethod
    def from_json_dict(cls, value: Mapping[str, Any]) -> "RepositoryAuthoritySnapshot":
        """Load the exact schema emitted by :meth:`to_json_dict`.

        Unknown and absent fields refuse.  A seal loader must not silently
        upgrade or partially adopt repository authority.
        """

        expected = {
            "schema_version",
            "canonical_root_source",
            "canonical_root_mode",
            "canonical_root_dev",
            "canonical_root_ino",
            "dot_git_shape",
            "dot_git_mode",
            "dot_git_dev",
            "dot_git_ino",
            "gitfile_sha256",
            "git_dir_mode",
            "git_dir_dev",
            "git_dir_ino",
            "commondir_mode",
            "commondir_dev",
            "commondir_ino",
            "commondir_sha256",
            "common_dir_mode",
            "common_dir_dev",
            "common_dir_ino",
            "resolver",
            *(f"{name}_b64" for name in _B64_FIELDS),
        }
        actual = set(value)
        if actual != expected:
            raise ValueError(
                "repository authority JSON fields differ from schema: "
                f"missing={sorted(expected - actual)!r}, extra={sorted(actual - expected)!r}"
            )
        decoded: dict[str, bytes | None] = {}
        for name in _B64_FIELDS:
            encoded = value[f"{name}_b64"]
            decoded[name] = None if encoded is None else _unb64(encoded, name=name)
        return cls(
            schema_version=_integer(value["schema_version"], "schema_version"),
            canonical_root=_required_bytes(decoded["canonical_root"], "canonical_root"),
            canonical_root_source=value["canonical_root_source"],
            canonical_root_mode=_integer(value["canonical_root_mode"], "canonical_root_mode"),
            canonical_root_dev=_integer(value["canonical_root_dev"], "canonical_root_dev"),
            canonical_root_ino=_integer(value["canonical_root_ino"], "canonical_root_ino"),
            dot_git_path=_required_bytes(decoded["dot_git_path"], "dot_git_path"),
            dot_git_shape=DotGitShape(value["dot_git_shape"]),
            dot_git_mode=_integer(value["dot_git_mode"], "dot_git_mode"),
            dot_git_dev=_integer(value["dot_git_dev"], "dot_git_dev"),
            dot_git_ino=_integer(value["dot_git_ino"], "dot_git_ino"),
            gitfile_bytes=decoded["gitfile_bytes"],
            gitfile_sha256=_optional_string(value["gitfile_sha256"], "gitfile_sha256"),
            git_dir=_required_bytes(decoded["git_dir"], "git_dir"),
            git_dir_mode=_integer(value["git_dir_mode"], "git_dir_mode"),
            git_dir_dev=_integer(value["git_dir_dev"], "git_dir_dev"),
            git_dir_ino=_integer(value["git_dir_ino"], "git_dir_ino"),
            commondir_path=decoded["commondir_path"],
            commondir_mode=_optional_integer(value["commondir_mode"], "commondir_mode"),
            commondir_dev=_optional_integer(value["commondir_dev"], "commondir_dev"),
            commondir_ino=_optional_integer(value["commondir_ino"], "commondir_ino"),
            commondir_bytes=decoded["commondir_bytes"],
            commondir_sha256=_optional_string(
                value["commondir_sha256"], "commondir_sha256"
            ),
            common_dir=_required_bytes(decoded["common_dir"], "common_dir"),
            common_dir_mode=_integer(value["common_dir_mode"], "common_dir_mode"),
            common_dir_dev=_integer(value["common_dir_dev"], "common_dir_dev"),
            common_dir_ino=_integer(value["common_dir_ino"], "common_dir_ino"),
            resolver=value["resolver"],
        )


def raw_realpath(path: Pathish) -> bytes:
    """Canonicalise a filesystem path without decoding its byte identity."""

    try:
        raw = os.fsencode(os.fspath(path))
    except (TypeError, UnicodeEncodeError) as exc:
        raise RepositoryLayoutUnreadable(
            "Repository path cannot be represented as filesystem bytes."
        ) from exc
    if b"\0" in raw:
        raise RepositoryLayoutUnreadable("Repository path contains a null byte.")
    try:
        return os.path.realpath(os.path.abspath(raw))
    except OSError as exc:
        raise RepositoryLayoutUnreadable(
            "Repository path realpath could not be resolved.",
            details={"errno": exc.errno},
        ) from exc


def classify_dot_git(root: Pathish) -> DotGitClassification:
    """Classify ``root/.git`` by ``lstat`` before any other entry operation."""

    canonical_root = raw_realpath(root)
    path = os.path.join(canonical_root, b".git")
    entry = _lstat(path, label=".git")
    mode = entry.st_mode
    target: bytes | None = None
    if stat.S_ISDIR(mode):
        shape = DotGitShape.DIRECTORY
    elif stat.S_ISREG(mode):
        shape = DotGitShape.GITFILE
    elif stat.S_ISLNK(mode):
        shape = DotGitShape.SYMLINK
        # Evidence only.  The shape decision above is already final, and
        # readlink cannot follow even a live target.
        try:
            target = os.fsencode(os.readlink(path))
        except OSError:
            target = None
    else:
        shape = DotGitShape.OTHER
    return DotGitClassification(
        path=path,
        shape=shape,
        mode=mode,
        dev=entry.st_dev,
        ino=entry.st_ino,
        link_target=target,
    )


def capture_repository_authority(
    root: Pathish,
    *,
    authorized_root: Pathish | None = None,
    authorized_gitdir_roots: Iterable[Pathish] = (),
) -> RepositoryAuthoritySnapshot:
    """Resolve and seal a normal repository or an authorised linked worktree.

    A normal ``.git`` directory is self-authorising once ``root`` has passed
    the caller's repository allowlist.  A gitfile is different: its bytes name
    another directory, so the caller must provide the already-onboarded
    administration root(s) in ``authorized_gitdir_roots``.  Containment uses
    canonical byte paths and path-component semantics, never string prefixes.
    """

    canonical_root = raw_realpath(root)
    root_stat = _lstat(canonical_root, label="canonical repository root")
    if not stat.S_ISDIR(root_stat.st_mode):
        raise RepositoryLayoutUnreadable(
            "The canonical repository root is not a directory.",
            details={"root": _display(canonical_root)},
        )
    authorized = raw_realpath(authorized_root) if authorized_root is not None else None
    if authorized is not None and canonical_root != authorized:
        raise RepositoryLayoutUnreadable(
            "Repository realpath does not equal the authorized root.",
            details={
                "root": _display(canonical_root),
                "authorized_root": _display(authorized),
            },
        )
    classification = classify_dot_git(canonical_root)
    allowed = _authorised_directories(authorized_gitdir_roots)

    gitfile_bytes: bytes | None = None
    if classification.shape is DotGitShape.DIRECTORY:
        git_dir = classification.path
        git_dir_stat = _require_same_directory(
            git_dir, classification, label=".git directory"
        )
        allowed = tuple(dict.fromkeys((*allowed, git_dir)))
    elif classification.shape is DotGitShape.GITFILE:
        if not allowed:
            raise RepositoryAdministrationUnsupported(
                "A primary gitfile requires an onboarded administration root.",
                details={"root": _display(canonical_root), "shape": "gitfile"},
            )
        gitfile_bytes = _read_regular(
            classification.path,
            label=".git gitfile",
            expected_dev=classification.dev,
            expected_ino=classification.ino,
        )
        target = _parse_gitfile(gitfile_bytes)
        git_dir, git_dir_stat = _resolve_directory_target(
            target,
            relative_to=canonical_root,
            allowed_roots=allowed,
            label="gitfile target",
        )
    else:
        details: dict[str, Any] = {
            "root": _display(canonical_root),
            "shape": classification.shape.value,
        }
        if classification.link_target is not None:
            details["target"] = _display(classification.link_target)
        raise RepositoryAdministrationUnsupported(
            "The repository .git entry has an unsupported filesystem type.",
            details=details,
        )

    commondir_path = os.path.join(git_dir, b"commondir")
    try:
        commondir_stat = os.lstat(commondir_path)
    except FileNotFoundError:
        commondir_path_or_none = None
        commondir_mode = None
        commondir_dev = None
        commondir_ino = None
        commondir_bytes = None
        common_dir = git_dir
        common_dir_stat = git_dir_stat
    except OSError as exc:
        raise RepositoryLayoutUnreadable(
            "The commondir entry could not be classified.",
            details={"path": _display(commondir_path), "errno": exc.errno},
        ) from exc
    else:
        if not stat.S_ISREG(commondir_stat.st_mode):
            raise RepositoryLayoutUnreadable(
                "The commondir entry is not a regular file.",
                details={"path": _display(commondir_path)},
            )
        commondir_bytes = _read_regular(
            commondir_path,
            label="commondir file",
            expected_dev=commondir_stat.st_dev,
            expected_ino=commondir_stat.st_ino,
        )
        commondir_mode = commondir_stat.st_mode
        commondir_dev = commondir_stat.st_dev
        commondir_ino = commondir_stat.st_ino
        target = _parse_path_record(commondir_bytes, label="commondir")
        common_dir, common_dir_stat = _resolve_directory_target(
            target,
            relative_to=git_dir,
            allowed_roots=allowed,
            label="commondir target",
        )
        commondir_path_or_none = commondir_path

    final_root_stat = _lstat(canonical_root, label="canonical repository root")
    if not stat.S_ISDIR(final_root_stat.st_mode) or (
        final_root_stat.st_dev,
        final_root_stat.st_ino,
    ) != (root_stat.st_dev, root_stat.st_ino):
        raise RepositoryLayoutUnreadable(
            "The canonical repository root was replaced during capture.",
            details={"root": _display(canonical_root)},
        )

    return RepositoryAuthoritySnapshot(
        schema_version=1,
        canonical_root=canonical_root,
        canonical_root_source="raw_realpath",
        canonical_root_mode=root_stat.st_mode,
        canonical_root_dev=root_stat.st_dev,
        canonical_root_ino=root_stat.st_ino,
        dot_git_path=classification.path,
        dot_git_shape=classification.shape,
        dot_git_mode=classification.mode,
        dot_git_dev=classification.dev,
        dot_git_ino=classification.ino,
        gitfile_bytes=gitfile_bytes,
        gitfile_sha256=_sha256(gitfile_bytes),
        git_dir=git_dir,
        git_dir_mode=git_dir_stat.st_mode,
        git_dir_dev=git_dir_stat.st_dev,
        git_dir_ino=git_dir_stat.st_ino,
        commondir_path=commondir_path_or_none,
        commondir_mode=commondir_mode,
        commondir_dev=commondir_dev,
        commondir_ino=commondir_ino,
        commondir_bytes=commondir_bytes,
        commondir_sha256=_sha256(commondir_bytes),
        common_dir=common_dir,
        common_dir_mode=common_dir_stat.st_mode,
        common_dir_dev=common_dir_stat.st_dev,
        common_dir_ino=common_dir_stat.st_ino,
        resolver="raw",
    )


def _lstat(path: bytes, *, label: str) -> os.stat_result:
    try:
        return os.lstat(path)
    except OSError as exc:
        raise RepositoryLayoutUnreadable(
            f"The {label} entry could not be classified.",
            details={"path": _display(path), "errno": exc.errno},
        ) from exc


def _require_same_directory(
    path: bytes, classification: DotGitClassification, *, label: str
) -> os.stat_result:
    current = _lstat(path, label=label)
    if not stat.S_ISDIR(current.st_mode):
        raise RepositoryLayoutUnreadable(
            f"The {label} changed type during capture.",
            details={"path": _display(path)},
        )
    if (current.st_dev, current.st_ino) != (classification.dev, classification.ino):
        raise RepositoryLayoutUnreadable(
            f"The {label} was replaced during capture.",
            details={"path": _display(path)},
        )
    return current


def _read_regular(
    path: bytes, *, label: str, expected_dev: int, expected_ino: int
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RepositoryLayoutUnreadable(
            f"The {label} could not be opened without following links.",
            details={"path": _display(path), "errno": exc.errno},
        ) from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise RepositoryLayoutUnreadable(
                f"The {label} is not a regular file.",
                details={"path": _display(path)},
            )
        if (opened.st_dev, opened.st_ino) != (expected_dev, expected_ino):
            raise RepositoryLayoutUnreadable(
                f"The {label} was replaced during capture.",
                details={"path": _display(path)},
            )
        chunks: list[bytes] = []
        remaining = _MAX_INDIRECTION_BYTES + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > _MAX_INDIRECTION_BYTES:
            raise RepositoryLayoutUnreadable(
                f"The {label} exceeds the bounded raw parser size.",
                details={"path": _display(path), "max_bytes": _MAX_INDIRECTION_BYTES},
            )
        return data
    finally:
        os.close(fd)


def _parse_gitfile(data: bytes) -> bytes:
    prefix = b"gitdir: "
    if not data.startswith(prefix):
        raise RepositoryLayoutUnreadable("The .git gitfile has a malformed prefix.")
    return _parse_path_record(data[len(prefix) :], label="gitfile")


def _parse_path_record(data: bytes, *, label: str) -> bytes:
    if b"\0" in data:
        raise RepositoryLayoutUnreadable(f"The {label} contains a null byte.")
    if data.endswith(b"\n"):
        data = data[:-1]
    if not data or b"\n" in data or b"\r" in data:
        raise RepositoryLayoutUnreadable(
            f"The {label} must contain exactly one non-empty path record."
        )
    return data


def _resolve_directory_target(
    target: bytes,
    *,
    relative_to: bytes,
    allowed_roots: tuple[bytes, ...],
    label: str,
) -> tuple[bytes, os.stat_result]:
    candidate = target if os.path.isabs(target) else os.path.join(relative_to, target)
    candidate = os.path.normpath(candidate)
    candidate_stat = _lstat(candidate, label=label)
    if stat.S_ISLNK(candidate_stat.st_mode):
        raise RepositoryLayoutUnreadable(
            f"The {label} is a symlink and cannot carry authority.",
            details={"path": _display(candidate)},
        )
    if not stat.S_ISDIR(candidate_stat.st_mode):
        raise RepositoryLayoutUnreadable(
            f"The {label} is not a directory.",
            details={"path": _display(candidate)},
        )
    resolved = raw_realpath(candidate)
    if not any(_is_within(resolved, boundary) for boundary in allowed_roots):
        raise RepositoryLayoutUnreadable(
            f"The {label} escapes every authorized administration root.",
            details={
                "path": _display(resolved),
                "authorized_roots": [_display(item) for item in allowed_roots],
            },
        )
    resolved_stat = _lstat(resolved, label=label)
    if not stat.S_ISDIR(resolved_stat.st_mode):
        raise RepositoryLayoutUnreadable(
            f"The resolved {label} is not a directory.",
            details={"path": _display(resolved)},
        )
    if (candidate_stat.st_dev, candidate_stat.st_ino) != (
        resolved_stat.st_dev,
        resolved_stat.st_ino,
    ):
        raise RepositoryLayoutUnreadable(
            f"The {label} was replaced during capture.",
            details={"path": _display(candidate)},
        )
    return resolved, resolved_stat


def _is_within(path: bytes, boundary: bytes) -> bool:
    try:
        return os.path.commonpath((path, boundary)) == boundary
    except ValueError:
        return False


def _authorised_directories(values: Iterable[Pathish]) -> tuple[bytes, ...]:
    result: list[bytes] = []
    for value in values:
        path = raw_realpath(value)
        entry = _lstat(path, label="authorized administration root")
        if not stat.S_ISDIR(entry.st_mode):
            raise RepositoryLayoutUnreadable(
                "An authorized administration root is not a directory.",
                details={"path": _display(path)},
            )
        if path not in result:
            result.append(path)
    return tuple(result)


def _validate_bytes_digest(
    data: bytes | None, digest: str | None, *, label: str
) -> None:
    if data is None or digest is None or _sha256(data) != digest:
        raise ValueError(f"{label} bytes and digest are inconsistent")


def _sha256(data: bytes | None) -> str | None:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(value: Any, *, name: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{name}_b64 must be a string or null")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError(f"{name}_b64 is not canonical base64") from exc
    if _b64(decoded) != value:
        raise ValueError(f"{name}_b64 is not canonical base64")
    return decoded


def _required_bytes(value: bytes | None, name: str) -> bytes:
    if value is None:
        raise ValueError(f"{name} must not be null")
    return value


def _integer(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value


def _optional_integer(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _integer(value, name)


def _optional_string(value: Any, name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be a string or null")
    return value


def _display(path: bytes) -> str:
    return os.fsdecode(path)
