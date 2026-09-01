"""B4 — PRODUCTION CONFIG AUTHORITY.

The dispatcher used to accept ``SOL_DISPATCHER_CONFIG`` as *the* config-path
selector for its console-script entrypoint. Codex can hand a single MCP child a
process-local environment::

    codex exec -c 'mcp_servers.sol_claude_dispatcher.env_vars=["SOL_DISPATCHER_CONFIG"]'

so the registered production server could be pointed at another TOML carrying a
**wider ``allowed_repository_roots``** — changing the production repository
authorization boundary for one process, with no change to any file on disk.
Lane S found this while making its live test safe; it is pre-existing
behaviour, not a regression.

That is a fine TEST/DEVELOPMENT mechanism and an unacceptable PRODUCTION
authority mechanism. This module pins the split:

* **production entrypoint** — :func:`sol_claude_dispatcher.server.main`, the
  ``sol-claude-dispatcher`` console script registered in ``~/.codex/config.toml``.
  Always loads the canonical ``config/dispatcher.toml``. A
  ``SOL_DISPATCHER_CONFIG`` naming anything else **refuses startup** with a
  typed error, before the MCP server exists.
* **test/development harness** — ``sol_claude_dispatcher.dev_server``, which
  takes a caller-supplied config path **on argv** and refuses anything that
  touches the production boundary. It is not installed as a console script and
  is not registered with Codex.

This is a fail-closed *configuration-authority* boundary. It is **not** an OS
security sandbox: it constrains which configuration the registered production
server will run under, and nothing more. Anyone who can write to
``config/dispatcher.toml``, replace the installed package, or run a different
command has not been stopped by it — those are deliberate, persistent,
reviewable acts, which is exactly the bar this boundary is raising the
environment override to.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from sol_claude_dispatcher import config_authority as authority
from sol_claude_dispatcher.config import load_config
from sol_claude_dispatcher.errors import ConfigAuthorityViolation, ConfigurationError
from sol_claude_dispatcher.server import (
    CONFIG_ENV_VAR,
    TOOL_NAMES,
    build_dispatcher,
    build_server,
    resolve_config_path,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = PROJECT_ROOT / "config" / "dispatcher.toml"

#: The one repository the production deployment is authorised for. Stated
#: literally because requirement 6 is stated literally: a temporary config
#: naming it must be refused by the disposable harness.
PRODUCTION_ROOT = "/home/dev/full-voice-agent"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """A clean child environment: no SOL_WORKER, no inherited config selector."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "PYTHONPATH": str(PROJECT_ROOT / "src"),
        "PYTHONUNBUFFERED": "1",
    }
    env.update(extra or {})
    return env


def _wider_config(tmp_path: Path, git_repo: Path, *, roots: list[str]) -> Path:
    """A config whose allowlist is WIDER than production's, written to tmp."""
    state = tmp_path / "wider-state"
    listed = ", ".join(json.dumps(r) for r in roots)
    body = f"""
[dispatcher]
state_dir = "{state}"

[models]
sonnet = "sonnet"
opus = "opus"
fable = "fable"

[routing]
default_model = "sonnet"

[security]
max_dispatch_depth = 1
allowed_repository_roots = [{listed}]

[validation]
run_dispatcher_validation = true
"""
    path = tmp_path / "wider.toml"
    path.write_text(body, encoding="utf-8")
    return path


class _Stdio:
    """The smallest MCP stdio client that can prove a tool surface."""

    def __init__(self, argv: list[str], env: dict[str, str], cwd: Path) -> None:
        self.proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
            argv,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._id = 0
        self._err: list[str] = []
        threading.Thread(target=self._drain, daemon=True).start()

    def _drain(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self._err.append(line)

    @property
    def stderr(self) -> str:
        return "".join(self._err)

    def request(self, method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self._id += 1
        rid = self._id
        self.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
            + "\n"
        )
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"server closed stdout; stderr: {self.stderr[-2000:]}")
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == rid:
                return msg
        raise TimeoutError(f"no response to {method}")

    def notify(self, method: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def initialize(self) -> dict:
        resp = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "b4-probe", "version": "1.0.0"},
            },
        )
        self.notify("notifications/initialized")
        return resp

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=20)
        except Exception:  # pragma: no cover - teardown
            self.proc.kill()


# ---------------------------------------------------------------------------
# 1. production entrypoint + no override -> canonical production config
# ---------------------------------------------------------------------------


class TestCanonicalPath:
    def test_canonical_path_is_the_projects_own_dispatcher_toml(self):
        assert authority.canonical_production_config_path() == CANONICAL

    def test_no_override_resolves_to_the_canonical_config(self):
        assert authority.assert_production_config_authority({}) == CANONICAL

    def test_resolve_config_path_no_longer_consults_the_environment(self, monkeypatch):
        """The env var must not *select* a config on any library path either.

        Defence in depth against the "relocate the defect" failure mode: even a
        caller that bypasses :func:`assert_production_config_authority` and asks
        the resolver for a default gets the canonical file, never the override.
        """
        monkeypatch.setenv(CONFIG_ENV_VAR, "/tmp/wider.toml")
        assert resolve_config_path() == CANONICAL

    def test_explicit_argument_still_wins_for_tests(self, config_file):
        assert resolve_config_path(config_file) == Path(config_file)


# ---------------------------------------------------------------------------
# 2. production entrypoint + SOL_DISPATCHER_CONFIG=/tmp/wider.toml -> REFUSED
# ---------------------------------------------------------------------------


class TestProductionRefusesRedirection:
    def test_foreign_path_is_refused(self, tmp_path):
        foreign = tmp_path / "wider.toml"
        foreign.write_text("# not the canonical config\n", encoding="utf-8")
        with pytest.raises(ConfigAuthorityViolation) as excinfo:
            authority.assert_production_config_authority({CONFIG_ENV_VAR: str(foreign)})
        payload = excinfo.value.to_payload()
        assert payload["error"] == "ConfigAuthorityViolation"
        assert payload["details"]["canonical_config_path"] == str(CANONICAL)
        assert payload["details"]["requested_config_path"] == str(foreign)

    def test_the_refusal_is_a_configuration_error(self, tmp_path):
        """Typed, and catchable by every existing ``ConfigurationError`` handler."""
        assert issubclass(ConfigAuthorityViolation, ConfigurationError)

    def test_a_nonexistent_override_is_refused_too(self):
        with pytest.raises(ConfigAuthorityViolation):
            authority.assert_production_config_authority(
                {CONFIG_ENV_VAR: "/nowhere/at/all/dispatcher.toml"}
            )

    def test_an_empty_override_is_refused_rather_than_ignored(self):
        """An operator who set the variable meant something by it.

        Treating "" as absent would be the silent-ignore behaviour this whole
        boundary exists to refuse.
        """
        with pytest.raises(ConfigAuthorityViolation):
            authority.assert_production_config_authority({CONFIG_ENV_VAR: ""})

    def test_another_config_inside_the_repository_is_refused(self):
        """MUTANT: "accept any path under the repo".

        ``dispatcher.example.toml`` lives beside the canonical file and is a
        perfectly valid dispatcher config. Proximity is not authority.
        """
        sibling = PROJECT_ROOT / "config" / "dispatcher.example.toml"
        assert sibling.exists()
        with pytest.raises(ConfigAuthorityViolation):
            authority.assert_production_config_authority({CONFIG_ENV_VAR: str(sibling)})

    def test_the_exact_canonical_path_is_accepted(self):
        """Harmless: it names the same file production would have loaded."""
        assert (
            authority.assert_production_config_authority({CONFIG_ENV_VAR: str(CANONICAL)})
            == CANONICAL
        )

    def test_a_dotted_spelling_of_the_canonical_path_is_accepted(self):
        """MUTANT: comparing raw strings instead of resolved paths."""
        dotted = PROJECT_ROOT / "config" / ".." / "config" / "dispatcher.toml"
        assert (
            authority.assert_production_config_authority({CONFIG_ENV_VAR: str(dotted)})
            == CANONICAL
        )


# ---------------------------------------------------------------------------
# 3. symlinks — canonicalize before comparing, in BOTH directions
# ---------------------------------------------------------------------------


class TestSymlinkCanonicalization:
    def test_a_symlink_to_the_canonical_file_is_accepted(self, tmp_path):
        """MUTANT: compare paths before canonicalization.

        A symlink whose realpath is the canonical config names the same inode
        and therefore the same bytes: accepting it changes nothing about what
        production runs. Pinned explicitly so nobody has to guess.
        """
        if not CANONICAL.exists():
            pytest.skip("no canonical production config on this host")
        alias = tmp_path / "alias.toml"
        alias.symlink_to(CANONICAL)
        assert (
            authority.assert_production_config_authority({CONFIG_ENV_VAR: str(alias)})
            == CANONICAL
        )

    def test_a_symlink_named_like_the_config_but_pointing_elsewhere_is_refused(
        self, tmp_path, git_repo
    ):
        """No symlink alias may let another file masquerade as production config.

        The dangerous shape: a path that *looks* canonical, or is reached
        through a symlinked ancestor, but whose realpath is a foreign file with
        a wider allowlist.
        """
        wider = _wider_config(tmp_path, git_repo, roots=[str(git_repo), "/tmp"])
        fake_dir = tmp_path / "config"
        fake_dir.mkdir()
        masquerade = fake_dir / "dispatcher.toml"
        masquerade.symlink_to(wider)
        with pytest.raises(ConfigAuthorityViolation):
            authority.assert_production_config_authority({CONFIG_ENV_VAR: str(masquerade)})

    def test_a_symlinked_ancestor_directory_does_not_alias_a_foreign_file(
        self, tmp_path, git_repo
    ):
        wider = _wider_config(tmp_path, git_repo, roots=[str(git_repo)])
        link_dir = tmp_path / "link"
        link_dir.symlink_to(tmp_path, target_is_directory=True)
        through_link = link_dir / "wider.toml"
        assert through_link.exists()
        with pytest.raises(ConfigAuthorityViolation):
            authority.assert_production_config_authority({CONFIG_ENV_VAR: str(through_link)})
        # ...and the same repository reached through a symlinked ancestor DOES
        # resolve to the canonical file, which is the accept side of the rule.
        assert authority._real(through_link) == str(wider.resolve())


# ---------------------------------------------------------------------------
# 4. test/build_server APIs can still use a temporary config
# ---------------------------------------------------------------------------


class TestTestabilityPreserved:
    def test_build_dispatcher_accepts_an_explicit_temp_config(self, config_file, git_repo):
        dispatcher = build_dispatcher(config_file)
        assert dispatcher.config.security.allowed_repository_roots == [str(git_repo)]

    def test_build_server_accepts_an_explicit_temp_config(self, config_file):
        server = build_server(config_file)
        assert server is not None

    def test_load_config_is_still_directly_callable(self, config_file, git_repo):
        config = load_config(config_file)
        assert config.security.allowed_repository_roots == [str(git_repo)]

    def test_an_explicit_temp_config_wins_over_a_hostile_environment(
        self, config_file, git_repo, monkeypatch
    ):
        monkeypatch.setenv(CONFIG_ENV_VAR, "/tmp/wider.toml")
        dispatcher = build_dispatcher(config_file)
        assert dispatcher.config.security.allowed_repository_roots == [str(git_repo)]


# ---------------------------------------------------------------------------
# 6. the disposable harness refuses the production boundary
# ---------------------------------------------------------------------------


class TestDisposableHarnessGuard:
    def test_a_temp_config_is_accepted(self, config_file):
        assert authority.assert_disposable_config(config_file) == Path(config_file)

    def test_the_canonical_production_config_is_refused(self):
        if not CANONICAL.exists():
            pytest.skip("no canonical production config on this host")
        with pytest.raises(ConfigAuthorityViolation):
            authority.assert_disposable_config(CANONICAL)

    def test_a_temp_config_naming_the_production_root_is_refused(self, tmp_path, git_repo):
        """MUTANT: let the disposable harness accept the production root."""
        wider = _wider_config(tmp_path, git_repo, roots=[str(git_repo), PRODUCTION_ROOT])
        with pytest.raises(ConfigAuthorityViolation) as excinfo:
            authority.assert_disposable_config(
                wider, production_roots=(PRODUCTION_ROOT,)
            )
        assert PRODUCTION_ROOT in json.dumps(excinfo.value.to_payload())

    def test_a_path_inside_the_production_root_is_refused(self, tmp_path, git_repo):
        wider = _wider_config(
            tmp_path, git_repo, roots=[PRODUCTION_ROOT + "/packages/kavya"]
        )
        with pytest.raises(ConfigAuthorityViolation):
            authority.assert_disposable_config(wider, production_roots=(PRODUCTION_ROOT,))

    def test_a_path_containing_the_production_root_is_refused(self, tmp_path, git_repo):
        wider = _wider_config(tmp_path, git_repo, roots=["/home/dev"])
        with pytest.raises(ConfigAuthorityViolation):
            authority.assert_disposable_config(wider, production_roots=(PRODUCTION_ROOT,))

    def test_the_live_production_roots_are_read_from_the_canonical_config(self):
        if not CANONICAL.exists():
            pytest.skip("no canonical production config on this host")
        roots = authority.production_repository_roots()
        assert roots == (PRODUCTION_ROOT,)

    def test_the_harness_refuses_the_real_production_root_by_default(
        self, tmp_path, git_repo
    ):
        """Requirement 6, against the host's ACTUAL production allowlist."""
        if not CANONICAL.exists():
            pytest.skip("no canonical production config on this host")
        wider = _wider_config(tmp_path, git_repo, roots=[PRODUCTION_ROOT])
        with pytest.raises(ConfigAuthorityViolation):
            authority.assert_disposable_config(wider)


# ---------------------------------------------------------------------------
# 7. the allowlist cannot be widened through the production environment
# ---------------------------------------------------------------------------


class TestNoEnvironmentAuthority:
    ALTERNATIVE_NAMES = (
        "SOL_DISPATCHER_CONFIG_PATH",
        "SOL_DISPATCHER_CONFIG_FILE",
        "SOL_CONFIG",
        "DISPATCHER_CONFIG",
        "CONFIG_PATH",
        "SOL_CLAUDE_DISPATCHER_CONFIG",
    )

    def test_no_other_environment_variable_selects_a_config(self, monkeypatch, tmp_path):
        """MUTANT: reintroduce env-based authority under a different name."""
        foreign = tmp_path / "wider.toml"
        foreign.write_text("# wider\n", encoding="utf-8")
        for name in self.ALTERNATIVE_NAMES:
            monkeypatch.setenv(name, str(foreign))
        assert resolve_config_path() == CANONICAL
        assert authority.assert_production_config_authority(dict(os.environ)) == CANONICAL

    @staticmethod
    def _env_reads(func) -> list[str]:
        """Names of environment lookups in ``func``'s executable body (AST).

        Docstrings and comments are excluded on purpose: this guard is about
        what the code *does*, and the code is allowed to explain itself.
        """
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
        found: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
                found.append(node.attr)
            if isinstance(node, ast.Name) and node.id in {"environ", "getenv"}:
                found.append(node.id)
        return found

    def test_the_resolver_reads_no_environment_at_all(self):
        """Source-level guard: the resolver must not grow an env branch back."""
        assert self._env_reads(resolve_config_path) == []

    def test_the_production_entrypoint_reads_no_environment_directly(self):
        """``main`` delegates to the one audited check; it does not peek itself."""
        from sol_claude_dispatcher.server import main

        assert self._env_reads(main) == []

    def test_the_disposable_harness_reads_no_environment_at_all(self):
        from sol_claude_dispatcher.dev_server import main as dev_main

        assert self._env_reads(dev_main) == []

    def test_the_authority_check_reads_exactly_one_variable(self):
        """Every environment read in the whole module is gated on ONE name."""
        import ast

        source = Path(authority.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        reads = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}
        ]
        # os.environ as the default for the injectable `environ` argument, and
        # os.path.realpath's own module access is not one of these.
        assert len(reads) == 1, f"unexpected environment reads: {len(reads)}"
        # Every lookup into the environment mapping names the one variable.
        keys = {
            node.slice.id if isinstance(node.slice, ast.Name) else "<literal>"
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "env"
        }
        assert keys == {"CONFIG_ENV_VAR"}


# ---------------------------------------------------------------------------
# live subprocess proofs: 2, 5, 8
# ---------------------------------------------------------------------------


class TestLiveEntrypoints:
    """Real processes, real stdio. Nothing is stubbed.

    No worker is ever dispatched here: the servers are started, interrogated
    and closed. The production repository is never named by any config these
    tests write.
    """

    def test_production_entrypoint_refuses_before_the_server_starts(
        self, tmp_path, git_repo
    ):
        wider = _wider_config(tmp_path, git_repo, roots=[str(git_repo)])
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            [sys.executable, "-m", "sol_claude_dispatcher.server"],
            cwd=str(PROJECT_ROOT),
            env=_child_env({CONFIG_ENV_VAR: str(wider)}),
            input="",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode != 0, "the production entrypoint must refuse to start"
        assert proc.stdout == "", "nothing may reach the MCP transport on refusal"
        payload = json.loads(proc.stderr.strip().splitlines()[-1])
        assert payload["error"] == "ConfigAuthorityViolation"
        assert payload["details"]["requested_config_path"] == str(wider)

    def test_production_entrypoint_starts_clean_with_no_override(self):
        """9. The normal production startup path stays green."""
        if not CANONICAL.exists():
            pytest.skip("no canonical production config on this host")
        client = _Stdio(
            [sys.executable, "-m", "sol_claude_dispatcher.server"],
            _child_env(),
            PROJECT_ROOT,
        )
        try:
            init = client.initialize()
            assert (init["result"]["serverInfo"]["name"]) == "sol-claude-dispatcher"
            listed = client.request("tools/list")
            names = sorted(t["name"] for t in listed["result"]["tools"])
            assert names == sorted(TOOL_NAMES)
        finally:
            client.close()

    def test_disposable_harness_serves_a_temp_config_with_four_tools(
        self, config_file, git_repo
    ):
        """5 and 8: the harness still works, and the surface is still four."""
        client = _Stdio(
            [sys.executable, "-m", "sol_claude_dispatcher.dev_server", str(config_file)],
            _child_env(),
            PROJECT_ROOT,
        )
        try:
            init = client.initialize()
            assert init["result"]["serverInfo"]["name"] == "sol-claude-dispatcher"
            listed = client.request("tools/list")
            names = sorted(t["name"] for t in listed["result"]["tools"])
            assert names == sorted(TOOL_NAMES)
        finally:
            client.close()

    def test_disposable_harness_ignores_the_environment_selector(
        self, config_file, tmp_path, git_repo
    ):
        """The harness takes its config on ARGV. Env is not an input anywhere."""
        wider = _wider_config(tmp_path, git_repo, roots=[str(git_repo), "/tmp"])
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            [sys.executable, "-m", "sol_claude_dispatcher.dev_server"],
            cwd=str(PROJECT_ROOT),
            env=_child_env({CONFIG_ENV_VAR: str(wider)}),
            input="",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode != 0
        assert "usage" in (proc.stderr + proc.stdout).lower()

    def test_disposable_harness_refuses_the_production_root_live(
        self, tmp_path, git_repo
    ):
        """6, through the real harness process."""
        if not CANONICAL.exists():
            pytest.skip("host-local production config is not installed")
        wider = _wider_config(tmp_path, git_repo, roots=[PRODUCTION_ROOT])
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            [sys.executable, "-m", "sol_claude_dispatcher.dev_server", str(wider)],
            cwd=str(PROJECT_ROOT),
            env=_child_env(),
            input="",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode != 0
        assert proc.stdout == ""
        payload = json.loads(proc.stderr.strip().splitlines()[-1])
        assert payload["error"] == "ConfigAuthorityViolation"

    def test_disposable_harness_refuses_the_canonical_config_live(self):
        if not CANONICAL.exists():
            pytest.skip("no canonical production config on this host")
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            [sys.executable, "-m", "sol_claude_dispatcher.dev_server", str(CANONICAL)],
            cwd=str(PROJECT_ROOT),
            env=_child_env(),
            input="",
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode != 0
        payload = json.loads(proc.stderr.strip().splitlines()[-1])
        assert payload["error"] == "ConfigAuthorityViolation"


# ---------------------------------------------------------------------------
# registration surface
# ---------------------------------------------------------------------------


class TestRegistrationSurface:
    def test_only_one_console_script_is_installed(self):
        text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        block = text.split("[project.scripts]", 1)[1].split("[", 1)[0]
        entries = [line for line in block.splitlines() if "=" in line]
        assert len(entries) == 1
        assert "server:main" in entries[0]
        assert "dev_server" not in text

    def test_the_generated_codex_snippet_sets_no_config_environment(self):
        script = (PROJECT_ROOT / "scripts" / "generate-codex-config.sh").read_text(
            encoding="utf-8"
        )
        snippet = script.split("[mcp_servers.sol_claude_dispatcher]", 1)[1]
        assert CONFIG_ENV_VAR not in snippet
        assert "env_vars" not in snippet
