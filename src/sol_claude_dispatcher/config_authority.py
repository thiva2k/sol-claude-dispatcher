"""Which configuration the PRODUCTION MCP server is allowed to run (B4).

The problem this module closes
------------------------------

``main()`` used to resolve its config as "explicit argument, else
``SOL_DISPATCHER_CONFIG``, else the project default". Codex can give a single
MCP child a process-local environment::

    codex exec -c 'mcp_servers.sol_claude_dispatcher.env_vars=["SOL_DISPATCHER_CONFIG"]'

so the server registered as ``sol_claude_dispatcher`` could be started against
another TOML carrying a wider ``security.allowed_repository_roots``. **The
production repository authorization boundary was changeable for one process
without modifying any file on disk.** That is a legitimate way to run a
disposable live gate; it is not an acceptable way to hold production authority.

The split this module draws
---------------------------

**Production entrypoint** — :func:`sol_claude_dispatcher.server.main`, installed
as the ``sol-claude-dispatcher`` console script and registered in
``~/.codex/config.toml``. It loads :func:`canonical_production_config_path` and
nothing else. The environment is read for exactly one purpose: to **refuse**
startup when it names a different file (:func:`assert_production_config_authority`).
Widening production authorization therefore requires a deliberate, persistent,
reviewable edit to the canonical configuration.

**Test/development harness** — :mod:`sol_claude_dispatcher.dev_server`, which
takes a caller-supplied config path **on argv** and is guarded by
:func:`assert_disposable_config`. It is not a console script, it is not
registered with Codex, and it refuses any config that touches the production
boundary. Ordinary tests do not need it at all: ``load_config(path)``,
``build_dispatcher(path)`` and ``build_server(path)`` all take an explicit path.

Why refuse rather than ignore
-----------------------------

Silently ignoring the override would leave an operator — or an automated
process — believing it had selected a configuration while the server ran under
a different one. Every other unmet expectation in this codebase fails closed and
says why; this one does too.

What this is NOT
----------------

This is **not** an OS security sandbox and must never be described as one. It
is a fail-closed *configuration-authority* boundary. It prevents one specific
thing: an ambient environment variable silently redirecting the registered
production MCP server to a different policy file. It does not prevent — and
does not claim to prevent — someone who can write to ``config/dispatcher.toml``,
replace the installed package, edit ``~/.codex/config.toml``, or run a different
command entirely. Those are all deliberate persistent acts, which is exactly the
bar this module raises the environment override up to.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from .config import DEFAULT_CONFIG_FILENAME
from .errors import ConfigAuthorityViolation

__all__ = [
    "CONFIG_ENV_VAR",
    "DEFAULT_CONFIG_PATH",
    "canonical_production_config_path",
    "assert_production_config_authority",
    "production_repository_roots",
    "assert_disposable_config",
]

#: The variable Lane S used to select a throwaway config for one process. It is
#: still honoured by nothing: the production entrypoint reads it only in order
#: to refuse, and the disposable harness takes its path on argv.
CONFIG_ENV_VAR = "SOL_DISPATCHER_CONFIG"

#: The canonical config's location relative to the project root.
DEFAULT_CONFIG_PATH = Path("config") / DEFAULT_CONFIG_FILENAME


def canonical_production_config_path() -> Path:
    """The ONE configuration the registered production MCP server may load.

    Derived from the installed package's own location rather than hard-coded,
    so a clone, a recovery environment and the activated production host each
    name their own file — and none of them can be talked into naming another.

    Returned **unresolved at the leaf**: ``load_config`` derives the project
    root from ``<config>/..``, and a canonical file that happens to be a symlink
    elsewhere must still resolve its relative paths against this project. The
    equality comparison below is a different question and does resolve fully.
    """
    return Path(__file__).resolve().parents[2] / DEFAULT_CONFIG_PATH


def _real(path: str | os.PathLike[str]) -> str:
    """Full path resolution: ``..``, ``.``, and **every** symlink component.

    The comparison in :func:`assert_production_config_authority` is about file
    identity, never about how a path is spelled. Comparing before this step is
    the defect that lets ``/somewhere/alias.toml -> /tmp/wider.toml`` — or a
    path reached through a symlinked ancestor directory — masquerade as the
    production config.
    """
    return os.path.realpath(os.path.abspath(os.fspath(path)))


def assert_production_config_authority(
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return the canonical production config path, or refuse to start.

    Args:
        environ: The environment to inspect. Defaults to ``os.environ``.

    Returns:
        :func:`canonical_production_config_path`. Always. This function never
        returns a path the environment chose.

    Raises:
        ConfigAuthorityViolation: ``SOL_DISPATCHER_CONFIG`` is present and does
            not resolve to the canonical production config. Including when it
            is empty: a variable that was set means something was intended by
            it, and treating "" as absent is the silent-ignore behaviour this
            boundary exists to refuse.

    An override naming the *exact same file* — including through a symlink or a
    dotted spelling — is accepted, because accepting it changes nothing about
    what production runs. Production still does not depend on it: the path
    returned is the canonical one either way.
    """
    env = os.environ if environ is None else environ
    canonical = canonical_production_config_path()

    if CONFIG_ENV_VAR not in env:
        return canonical

    requested = env[CONFIG_ENV_VAR]

    if not requested.strip():
        raise ConfigAuthorityViolation(
            f"{CONFIG_ENV_VAR} is set but names no file, and the production "
            "dispatcher will not guess what was meant.",
            details={
                "env_var": CONFIG_ENV_VAR,
                "requested_config_path": requested,
                "canonical_config_path": str(canonical),
            },
            remediation=(
                f"Unset {CONFIG_ENV_VAR}. The registered production MCP server "
                "always loads its canonical configuration; the variable is a "
                "test/development selector for the disposable stdio harness "
                "(python -m sol_claude_dispatcher.dev_server <config>), which "
                "takes its path on argv instead."
            ),
        )

    if _real(requested) != _real(canonical):
        raise ConfigAuthorityViolation(
            "The production dispatcher refuses to start under a configuration "
            "chosen by its environment.",
            details={
                "env_var": CONFIG_ENV_VAR,
                "requested_config_path": requested,
                "requested_config_realpath": _real(requested),
                "canonical_config_path": str(canonical),
                "canonical_config_realpath": _real(canonical),
            },
            remediation=(
                "This is the production MCP entrypoint: its repository "
                "allowlist and every other policy come from the canonical "
                "configuration, and changing them requires a deliberate, "
                "persistent edit to that file — never an environment override. "
                f"Unset {CONFIG_ENV_VAR} to start production. To run against a "
                "temporary configuration, use the test/development harness "
                "(python -m sol_claude_dispatcher.dev_server <config>), which "
                "refuses any config touching the production boundary, or call "
                "load_config(path) / build_server(path) directly from a test."
            ),
        )

    return canonical


# ---------------------------------------------------------------------------
# the disposable test/development harness guard
# ---------------------------------------------------------------------------


def _declared_roots(config_path: Path) -> tuple[str, ...]:
    """``security.allowed_repository_roots`` as literally written in a TOML.

    Read with ``tomllib`` rather than through ``load_config`` on purpose: this
    guard must be able to inspect a config that would fail validation (a root
    that does not exist on this host, say) and still refuse it if it names the
    production boundary. Refusing early is the whole job.
    """
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigAuthorityViolation(
            "The disposable harness could not read the configuration it was "
            "asked to serve, so it cannot prove the configuration is safe.",
            details={"config_path": str(config_path), "reason": type(exc).__name__},
            remediation="Fix the file. The harness will not serve an unreadable config.",
        ) from exc

    section = data.get("security")
    roots = section.get("allowed_repository_roots") if isinstance(section, dict) else None
    if not isinstance(roots, list):
        return ()
    return tuple(str(r) for r in roots)


def production_repository_roots(
    canonical_path: Path | None = None,
) -> tuple[str, ...]:
    """The repository roots the CANONICAL production config authorises.

    Derived, never hard-coded, so the guard below cannot drift away from the
    boundary it is protecting.

    If the canonical config does not exist — a fresh clone, a CI checkout —
    there is no production deployment on this host and therefore no production
    boundary to protect, and this returns ``()``. That is stated plainly rather
    than hidden: on such a host the harness guard degrades to "refuse the
    canonical path", which is all there is to refuse.
    """
    path = canonical_path or canonical_production_config_path()
    if not path.is_file():
        return ()
    return _declared_roots(path)


def _touches(candidate: str, boundary: str) -> bool:
    """True when two roots are the same tree, or one contains the other.

    Both directions matter. ``/home/dev/full-voice-agent/packages/kavya`` is
    inside the production repository; ``/home/dev`` contains it. Either one
    would let a disposable harness reach production files.
    """
    a = Path(_real(candidate))
    b = Path(_real(boundary))
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def assert_disposable_config(
    config_path: str | os.PathLike[str],
    *,
    production_roots: Sequence[str] | None = None,
) -> Path:
    """Guard for the TEST/DEVELOPMENT stdio harness. Never used by production.

    Refuses, in order:

    1. the canonical production config itself — the harness exists to run
       *throwaway* configurations, and serving the production one under a
       test-only entrypoint would recreate the ambiguity B4 is closing;
    2. any config declaring a repository root that is, contains, or lies inside
       a root the production configuration authorises.

    Args:
        config_path: The disposable TOML the harness was asked to serve.
        production_roots: Override for the production allowlist. For tests
            only; production callers leave it ``None`` so the boundary is read
            from the canonical config.

    Returns:
        ``Path(config_path)``, unchanged, when the config is safely disposable.

    Raises:
        ConfigAuthorityViolation: on any of the refusals above.
    """
    path = Path(config_path)
    canonical = canonical_production_config_path()

    if _real(path) == _real(canonical):
        raise ConfigAuthorityViolation(
            "The disposable test/development harness refuses to serve the "
            "canonical production configuration.",
            details={
                "config_path": str(path),
                "canonical_config_path": str(canonical),
            },
            remediation=(
                "Production runs under the production entrypoint "
                "(sol-claude-dispatcher), not under this harness. Point the "
                "harness at a throwaway config, or start the real server."
            ),
        )

    boundary: Iterable[str] = (
        production_repository_roots() if production_roots is None else production_roots
    )
    boundary = tuple(boundary)

    declared = _declared_roots(path)
    offending = sorted(
        {
            root
            for root in declared
            for guarded in boundary
            if _touches(root, guarded)
        }
    )
    if offending:
        raise ConfigAuthorityViolation(
            "The disposable test/development harness refuses a configuration "
            "that reaches a production repository.",
            details={
                "config_path": str(path),
                "offending_repository_roots": offending,
                "production_repository_roots": list(boundary),
            },
            remediation=(
                "The harness exists so live gates can run against disposable "
                "repositories under a temporary directory. It must never be "
                "the route by which a production repository is dispatched "
                "against — that requires the production entrypoint and the "
                "canonical configuration."
            ),
        )

    return path
