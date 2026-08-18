"""Repository allowlist and recursion detection (brief §22, §24). — Wave 2.

Fail closed, always. A path that cannot be proven safe is rejected.

Contract (authoritative, see ``docs/INTERFACES.md``)::

    def validate_repository_root(raw_root: str, config: Config) -> Path
    def assert_no_recursion(config: Config, env: Mapping[str, str] | None = None) -> None
    def assert_dispatch_depth(depth: int, config: Config) -> None
    def worker_environment(base_env, *, task_id, dispatch_depth) -> dict[str, str]
    def redact(text: str) -> str

``validate_repository_root`` rejects: nonexistent paths, non-directories,
non-git directories, paths outside every configured root, path traversal, and
symlink escapes (checked *after* ``Path.resolve()``, comparing resolved
ancestry rather than string prefixes).

``worker_environment`` builds the child environment (§22 layer 4 and layer 7):
it sets ``SOL_WORKER=1``, ``SOL_DISPATCH_DEPTH``, ``SOL_TASK_ID``, and strips
dispatcher-specific and secret-shaped variables so no dispatcher credential is
forwarded into a worker.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .config import Config

__all__ = [
    "validate_repository_root",
    "assert_no_recursion",
    "assert_dispatch_depth",
    "worker_environment",
    "redact",
    "SECRET_ENV_MARKERS",
    "WORKER_ENV_MARKER",
]

#: Substrings that mark an environment variable or log line as secret-bearing
#: (§28). Matching is case-insensitive.
SECRET_ENV_MARKERS: tuple[str, ...] = (
    "TOKEN",
    "API_KEY",
    "APIKEY",
    "AUTHORIZATION",
    "COOKIE",
    "SECRET",
    "PASSWORD",
    "PRIVATE_KEY",
    "CREDENTIAL",
)

#: Presence of this variable in the dispatcher's own environment means the
#: dispatcher is running inside a worker and must refuse to start (§22 layer 4).
WORKER_ENV_MARKER = "SOL_WORKER"


def validate_repository_root(raw_root: str, config: Config) -> Path:
    """Canonicalise and allowlist-check a repository root (§24)."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §security")


def assert_no_recursion(
    config: Config, env: Mapping[str, str] | None = None
) -> None:
    """Raise ``RecursionDetected`` when running inside a worker (§22 layer 4)."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §security")


def assert_dispatch_depth(depth: int, config: Config) -> None:
    """Raise ``RecursionDetected`` when depth exceeds the max (§22 layer 5)."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §security")


def worker_environment(
    base_env: Mapping[str, str], *, task_id: str, dispatch_depth: int
) -> dict[str, str]:
    """Build the worker child environment (§22 layers 4 and 7)."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §security")


def redact(text: str) -> str:
    """Mask secret-shaped values before logging or persisting (§28)."""
    raise NotImplementedError("Wave 2: implement per docs/INTERFACES.md §security")
