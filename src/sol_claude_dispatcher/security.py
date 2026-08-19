"""Repository allowlist and recursion detection (brief §22, §24). — Wave 2.

Fail closed, always. A path that cannot be proven safe is rejected.

Contract (authoritative, see ``docs/INTERFACES.md``)::

    def validate_task_id(value: str) -> str
    def validate_repository_root(raw_root: str, config: Config) -> Path
    def assert_no_recursion(config: Config, env: Mapping[str, str] | None = None) -> None
    def assert_dispatch_depth(depth: int, config: Config) -> None
    def worker_environment(base_env, *, task_id, dispatch_depth) -> dict[str, str]
    def redact(text: str) -> str

``validate_task_id`` is the single authoritative task-id validator: canonical
lowercase UUID form only, so a caller-supplied id can never become a path
component of the dispatcher's choosing. It is the *outer* boundary;
:class:`~sol_claude_dispatcher.state.TaskStore` independently re-verifies
containment of every path it derives, so neither layer depends on the other
having been called.

``validate_repository_root`` rejects: nonexistent paths, non-directories,
non-git directories, any path that is not itself the git top level, paths that
are not *exactly* a configured allowed root, path traversal, and symlink
escapes (checked *after* ``Path.resolve()`` and after git has named the top
level, comparing canonical paths rather than string prefixes or ancestry).

``worker_environment`` builds the child environment (§22 layer 4 and layer 7):
it sets ``SOL_WORKER=1``, ``SOL_DISPATCH_DEPTH``, ``SOL_TASK_ID``, and strips
dispatcher-specific and secret-shaped variables so no dispatcher credential is
forwarded into a worker.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Mapping
from pathlib import Path

from .config import Config
from .errors import (
    InvalidRepository,
    InvalidTaskEnvelope,
    RecursionDetected,
    RepositoryNotAllowed,
)
from .git import git_top_level

__all__ = [
    "validate_task_id",
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

#: The one shape a dispatcher task id may have: canonical, lowercase,
#: hyphenated UUID (what :func:`sol_claude_dispatcher.models.new_task_id`
#: produces). Anything else — a path fragment, a traversal sequence, an
#: uppercase or braced UUID spelling, a URN — is refused rather than
#: normalised, because "normalise then use as a path component" is exactly the
#: pattern that produces directory escapes.
_TASK_ID_RE = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)

#: Upper bound on the raw string we are willing to even inspect, so a
#: pathological input cannot turn validation into work.
_MAX_TASK_ID_LEN = 64


def validate_task_id(value: str) -> str:
    """Return ``value`` if it is a canonical dispatcher task id, else refuse.

    This is the single authoritative task-id validator (P0-1). Every MCP entry
    point that accepts a caller-supplied ``task_id`` — ``get_task``,
    ``resume_claude_task``, ``review_task_with_fable`` — must pass it through
    here *before* the id reaches any component that derives a filesystem path
    from it.

    Fail closed, and deliberately without normalisation: no stripping, no
    case-folding, no brace/URN unwrapping. A caller that sends anything other
    than the exact id the dispatcher issued gets
    :class:`~sol_claude_dispatcher.errors.InvalidTaskEnvelope`, not a repaired
    id. Rejected shapes include ``..``, ``../escape``, ``/absolute``,
    ``foo/bar``, ``foo\\bar``, ``.``, ``""``, whitespace-padded ids, embedded
    null bytes, arbitrary text, and malformed or non-canonical UUIDs.

    This is the outer boundary only. ``TaskStore`` re-verifies containment of
    every path it derives, so a call site that forgets this function still
    cannot escape the task-state root.
    """
    if not isinstance(value, str):
        raise InvalidTaskEnvelope(
            "task_id must be a string.",
            details={"type": type(value).__name__},
        )
    if len(value) > _MAX_TASK_ID_LEN:
        raise InvalidTaskEnvelope(
            "task_id is too long to be a dispatcher task id.",
            details={"length": len(value)},
        )
    if "\x00" in value:
        raise InvalidTaskEnvelope(
            "task_id contains a null byte.",
            details={"task_id": repr(value)},
        )
    if not _TASK_ID_RE.match(value):
        raise InvalidTaskEnvelope(
            "task_id is not a canonical dispatcher task id.",
            details={"task_id": repr(value)},
            remediation=(
                "Use the task_id returned by dispatch_claude_task verbatim; the "
                "dispatcher issues canonical lowercase UUIDs and accepts no "
                "other spelling."
            ),
        )
    # Belt and braces: the regex already pins the shape, but round-tripping
    # through uuid.UUID proves it is a real UUID and that the canonical
    # rendering is byte-identical to what was supplied.
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:  # pragma: no cover - unreachable given the regex
        raise InvalidTaskEnvelope(
            "task_id is not a valid UUID.", details={"task_id": repr(value)}
        ) from exc
    if str(parsed) != value:  # pragma: no cover - unreachable given the regex
        raise InvalidTaskEnvelope(
            "task_id is not in canonical UUID form.",
            details={"task_id": repr(value)},
        )
    return value


def validate_repository_root(raw_root: str, config: Config) -> Path:
    """Establish canonical repository identity and allowlist-check it (§24, P0-2).

    Order (fail closed at the first violation):

    1. reject empty / relative / null-byte-bearing input;
    2. resolve symlinks and ``..`` (``Path.resolve()``);
    3. reject nonexistent paths and non-directories;
    4. ask *git* for the repository's top level (``git rev-parse
       --show-toplevel``, argv, never a shell) and canonicalise the answer;
       a path that is not inside a work tree is rejected here;
    5. reject any request whose resolved path is not itself that top level —
       a subdirectory of an allowed repository is **not** an allowed
       repository, because accepting it would give the same repository two
       identities (two lock names, two evidence roots);
    6. require the canonical top level to be **exactly** equal to one of the
       configured allowed roots. Not a descendant of one, not a string prefix
       match — equal;
    7. return the canonical top level. This becomes ``canonical_root``, and is
       the only spelling that may be used for locking, worktree derivation and
       evidence collection.

    The historical check (``path == root or root in path.parents``) accepted
    ``/repo/src`` for an allowlist of ``/repo``. That broke canonical identity:
    the same repository reached through two spellings produced two different
    lock files and two different evidence roots, so the "one mutating worker
    per repository" invariant did not hold.
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

    # git names the repository, not the caller. Raises InvalidRepository when
    # the path is not inside a work tree or git could not be consulted.
    canonical_root = git_top_level(path)

    if path != canonical_root:
        raise InvalidRepository(
            "Repository root must be the git top-level directory, not a "
            "subdirectory of one.",
            details={"root": str(path), "git_top_level": str(canonical_root)},
            remediation=(
                "Dispatch against the repository root itself "
                f"({canonical_root}); scope a task to a subdirectory with "
                "[scope].allowed_paths instead."
            ),
        )

    allowed_roots = [Path(r).resolve() for r in config.security.allowed_repository_roots]
    if canonical_root not in allowed_roots:
        raise RepositoryNotAllowed(
            "Repository is not an allowed repository root.",
            details={
                "root": str(canonical_root),
                "allowed_roots": [str(r) for r in allowed_roots],
            },
            remediation=(
                "Add the repository's exact git top-level path to "
                "[security].allowed_repository_roots. Descendants of an allowed "
                "root are not accepted; each repository must be listed."
            ),
        )

    return canonical_root


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
#:
#: Two deliberate properties make this linear in the length of the input
#: (Lane B adjacent finding A3). ``redact()`` is applied to whole worker
#: streams, which can be multi-megabyte, so a pattern that merely "usually"
#: performs is a denial-of-service on the dispatcher's own evidence path.
#:
#: 1. The leading ``(?<![A-Za-z0-9_])`` **anchors** a candidate match to the
#:    start of an identifier run. Without it the engine retries at every offset
#:    inside a long token, and each retry rescans the rest of the token looking
#:    for an ``=`` that is not there — quadratic. Measured on this machine
#:    before the anchor: 16 KB of ``A`` took 3.7 s, and cost quadrupled per
#:    doubling, so a 4 MB stream would have taken over a day. After: 4 MB in
#:    0.24 s.
#: 2. Possessive quantifiers (``*+``) forbid backtracking that can never help:
#:    ``[A-Za-z0-9_]`` cannot match ``=``, ``[0-9]`` cannot match
#:    ``[A-Za-z_]``, and ``\S`` is the last element of the pattern, so in every
#:    case the greedy run already stops exactly where the next element must
#:    begin.
#:
#: The matched *language* is unchanged. ``[0-9]*+`` preserves the previous
#: behaviour for a key that begins mid-token after a digit (``9API_KEY=x``):
#: the old pattern started matching at the first letter, this one starts at the
#: first digit, and since key matching is a case-insensitive substring test the
#: verdict and the rendered replacement are byte-identical. Verified by
#: differential fuzzing against the previous pattern (200k random inputs,
#: zero divergences) and pinned by
#: ``tests/unit/test_security.py::TestRedactionCost``.
_ENV_PAIR_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<key>[0-9]*+[A-Za-z_][A-Za-z0-9_]*+)=(?P<val>\S*+)"
)
#: Matches ``"key": "value"`` shaped tokens (JSON-ish logging). Possessive for
#: the same reason: ``[^"]`` cannot match the ``"`` that must follow it, and
#: ``\s`` cannot match the ``:``.
_JSON_PAIR_RE = re.compile(r'"(?P<key>[^"]++)"\s*+:\s*+"(?P<val>[^"]*+)"')


def _is_secret_key(key: str) -> bool:
    upper = key.upper()
    return any(marker in upper for marker in SECRET_ENV_MARKERS)


def redact(text: str) -> str:
    """Mask secret-shaped values before logging or persisting (§28).

    Masks ``KEY=value`` and ``"key": "value"`` pairs whose key matches
    :data:`SECRET_ENV_MARKERS`, replacing the value with ``***REDACTED***``.

    Cost is linear in ``len(text)``; see :data:`_ENV_PAIR_RE`. Callers stream
    whole worker stderr through this function, so that is a requirement, not an
    optimisation.
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
