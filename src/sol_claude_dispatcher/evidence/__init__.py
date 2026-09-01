"""Gate 7 dispatcher-owned evidence primitives."""

from .identity import (
    DotGitClassification,
    DotGitShape,
    RepositoryAuthoritySnapshot,
    capture_repository_authority,
    classify_dot_git,
    raw_realpath,
)

__all__ = [
    "DotGitClassification",
    "DotGitShape",
    "RepositoryAuthoritySnapshot",
    "capture_repository_authority",
    "classify_dot_git",
    "raw_realpath",
]
