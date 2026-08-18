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

import os
import re
from collections.abc import Mapping
from pathlib import Path

from .config import Config
from .errors import InvalidRepository, RecursionDetected, RepositoryNotAllowed
from .git import is_git_repository

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

#: Escape hatch used only by this project's own test suite, never in
#: production, to exercise dispatcher code paths from inside a test process
#: that itself happens to carry ``SOL_WORKER=1`` in ancestry.
_TEST_OVERRIDE_MARKER = "SOL_DISPATCHER_TEST_OVERRIDE"


def validate_repository_root(raw_root: str, config: Config) -> Path:
    """Canonicalise and allowlist-check a repository root (§24).

    Order (fail closed at the first violation):

    1. reject empty / relative / null-byte-bearing input;
    2. resolve symlinks and ``..`` (``Path.resolve()``);
    3. reject nonexistent paths and non-directories;
    4. reject paths outside every configured allowlist root, comparing
       *resolved* ancestry rather than string prefixes — a symlink inside an
       allowed root that points outside it was already resolved away in step
       2, so it is rejected here, not silently accepted;
    5. reject non-git directories (worktree mode requires git);
    6. return the resolved path. This becomes ``canonical_root``.
    """
    if not raw_root or not raw_root.strip():
        raise InvalidRepository(
            "Repository root must not be empty.", details={"root": raw_root}
        )
    if "\x00" in raw_root:
        raise InvalidRepository(
            "Repository root contains a null byte.", details={"root": raw_root}
        )
    if not raw_root.startswith("/"):
        raise InvalidRepository(
            "Repository root must be an absolute path.",
            details={"root": raw_root},
        )

    path = Path(raw_root).resolve()

    if not path.exists():
        raise InvalidRepository(
            "Repository root does not exist.", details={"root": str(path)}
        )
    if not path.is_dir():
        raise InvalidRepository(
            "Repository root is not a directory.", details={"root": str(path)}
        )

    allowed_roots = [Path(r).resolve() for r in config.security.allowed_repository_roots]
    if not any(path == root or root in path.parents for root in allowed_roots):
        raise RepositoryNotAllowed(
            "Repository is outside the configured allowlist.",
            details={
                "root": str(path),
                "allowed_roots": [str(r) for r in allowed_roots],
            },
            remediation="Add the path to [security].allowed_repository_roots.",
        )

    if not is_git_repository(path):
        raise InvalidRepository(
            "Repository root is not a git repository; worktree mode requires "
            "a git repository.",
            details={"root": str(path)},
        )

    return path


def assert_no_recursion(
    config: Config, env: Mapping[str, str] | None = None
) -> None:
    """Raise ``RecursionDetected`` when running inside a worker (§22 layer 4).

    Called at server startup and at the top of every dispatch/resume tool. The
    only escape hatch is ``SOL_DISPATCHER_TEST_OVERRIDE=1``, which exists
    solely for this project's own test suite.
    """
    del config  # unused: the check is unconditional, config is part of the
    # documented signature for symmetry with assert_dispatch_depth.
    e = env if env is not None else os.environ
    if e.get(WORKER_ENV_MARKER) == "1" and e.get(_TEST_OVERRIDE_MARKER) != "1":
        raise RecursionDetected(
            "Dispatcher was invoked from inside a worker context.",
            details={"marker": WORKER_ENV_MARKER},
        )


def assert_dispatch_depth(depth: int, config: Config) -> None:
    """Raise ``RecursionDetected`` when depth exceeds the max (§22 layer 5)."""
    max_depth = config.security.max_dispatch_depth
    if depth > max_depth:
        raise RecursionDetected(
            "Dispatch depth exceeds the configured maximum.",
            details={"depth": depth, "max": max_depth},
        )


def worker_environment(
    base_env: Mapping[str, str], *, task_id: str, dispatch_depth: int
) -> dict[str, str]:
    """Build the worker child environment (§22 layers 4 and 7).

    Starts from ``base_env``, drops every key whose name matches a
    :data:`SECRET_ENV_MARKERS` substring (case-insensitive) or starts with
    ``SOL_DISPATCHER_``, then sets ``SOL_WORKER``, ``SOL_DISPATCH_DEPTH`` and
    ``SOL_TASK_ID``. Anthropic credentials are never synthesised or forwarded
    here — the Claude CLI manages its own auth.
    """
    env: dict[str, str] = {}
    for key, value in base_env.items():
        upper = key.upper()
        if upper.startswith("SOL_DISPATCHER_"):
            continue
        if any(marker in upper for marker in SECRET_ENV_MARKERS):
            continue
        env[key] = value

    env["SOL_WORKER"] = "1"
    env["SOL_DISPATCH_DEPTH"] = str(dispatch_depth + 1)
    env["SOL_TASK_ID"] = task_id
    return env


#: Matches ``KEY=value`` shaped tokens (env-file / shell-export style).
_ENV_PAIR_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<val>\S*)")
#: Matches ``"key": "value"`` shaped tokens (JSON-ish logging).
_JSON_PAIR_RE = re.compile(r'"(?P<key>[^"]+)"\s*:\s*"(?P<val>[^"]*)"')


def _is_secret_key(key: str) -> bool:
    upper = key.upper()
    return any(marker in upper for marker in SECRET_ENV_MARKERS)


def redact(text: str) -> str:
    """Mask secret-shaped values before logging or persisting (§28).

    Masks ``KEY=value`` and ``"key": "value"`` pairs whose key matches
    :data:`SECRET_ENV_MARKERS`, replacing the value with ``***REDACTED***``.
    """

    def _json_sub(match: re.Match[str]) -> str:
        key = match.group("key")
        if _is_secret_key(key):
            return f'"{key}": "***REDACTED***"'
        return match.group(0)

    def _env_sub(match: re.Match[str]) -> str:
        key = match.group("key")
        if _is_secret_key(key):
            return f"{key}=***REDACTED***"
        return match.group(0)

    text = _JSON_PAIR_RE.sub(_json_sub, text)
    text = _ENV_PAIR_RE.sub(_env_sub, text)
    return text
