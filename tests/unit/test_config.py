"""Configuration loading (brief §35, §10, §24).

Every test here is really the same test: *does it fail closed?* A dispatcher
that starts with a half-valid config is more dangerous than one that refuses to
start at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sol_claude_dispatcher.config import (
    PLACEHOLDER_ROOT,
    Config,
    load_config,
    load_config_from_mapping,
)
from sol_claude_dispatcher.errors import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "dispatcher.example.toml"


class TestExampleConfig:
    def test_example_file_exists(self):
        assert EXAMPLE_CONFIG.is_file()

    def test_example_refuses_to_load_until_configured(self):
        """The shipped example carries a placeholder root. That must be fatal."""
        with pytest.raises(ConfigurationError) as exc:
            load_config(EXAMPLE_CONFIG)
        assert "invalid" in exc.value.message.lower()
        rendered = str(exc.value.details)
        assert "CONFIGURE" in rendered or "placeholder" in rendered

    def test_example_is_otherwise_structurally_complete(self, tmp_path):
        """Swap only the placeholder root; everything else must validate."""
        text = EXAMPLE_CONFIG.read_text().replace(PLACEHOLDER_ROOT, str(tmp_path))
        path = tmp_path / "dispatcher.toml"
        path.write_text(text)
        config = load_config(path)
        assert config.dispatcher.default_timeout_seconds == 1800
        assert config.models.sonnet == "sonnet"
        assert config.models.opus == "opus"
        assert config.models.fable == "fable"
        assert config.routing.default_model == "sonnet"
        assert config.security.max_dispatch_depth == 1
        assert config.validation.run_dispatcher_validation is True
        assert config.security.allowed_repository_roots == [str(tmp_path.resolve())]

    def test_example_grants_no_write_tools_to_the_reviewer(self, tmp_path):
        text = EXAMPLE_CONFIG.read_text().replace(PLACEHOLDER_ROOT, str(tmp_path))
        path = tmp_path / "dispatcher.toml"
        path.write_text(text)
        config = load_config(path)
        assert set(config.claude.reviewer_tools) == {"Read", "Glob", "Grep"}
        assert "Edit" not in config.claude.reviewer_tools
        assert "Write" not in config.claude.reviewer_tools
        assert "Bash" not in config.claude.reviewer_tools

    def test_example_denies_mcp_and_dangerous_git_to_workers(self, tmp_path):
        text = EXAMPLE_CONFIG.read_text().replace(PLACEHOLDER_ROOT, str(tmp_path))
        path = tmp_path / "dispatcher.toml"
        path.write_text(text)
        config = load_config(path)
        denied = " ".join(config.claude.disallowed_tools)
        assert "mcp__*" in config.claude.disallowed_tools
        for forbidden in ("git push", "git merge", "git rebase", "git commit"):
            assert forbidden in denied
        assert "claude" in denied and "codex" in denied
        # No subagent tool is granted at all.
        assert "Agent" not in config.claude.worker_tools
        assert "Task" not in config.claude.worker_tools


class TestLoadingValidConfig:
    def test_loads_and_exposes_sections(self, config_file, git_repo):
        config = load_config(config_file)
        assert isinstance(config, Config)
        assert config.source_path == str(config_file.resolve())
        # The shared fixture allowlists the repository's own git top level, not
        # its parent — exact-equality allowlisting (P0-2) accepts nothing else.
        assert config.security.allowed_repository_roots == [str(git_repo.resolve())]

    def test_optional_sections_get_safe_defaults(self, config_file):
        config = load_config(config_file)
        assert config.claude.binary == "claude"
        assert config.claude.permission_mode == "auto"
        assert config.logging.level == "INFO"
        assert config.logging.log_file is None

    def test_derived_paths_resolve_against_project_root(self, config_file, tmp_path):
        config = load_config(config_file, project_root=tmp_path)
        assert config.state_path == (tmp_path / "state").resolve()
        assert config.tasks_path.name == "tasks"
        assert config.locks_path.name == "locks"
        assert config.proposals_path.name == "proposals"
        assert config.worker_policy_file.name == "worker-policy.md"
        assert config.empty_mcp_file.name == "empty-mcp.json"

    def test_project_root_is_inferred_from_a_config_subdirectory(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "dispatcher.toml").write_text(
            f"""
[dispatcher]
[models]
[routing]
[security]
allowed_repository_roots = ["{tmp_path}"]
"""
        )
        config = load_config(cfg_dir / "dispatcher.toml")
        assert config.project_root == str(tmp_path.resolve())

    def test_model_lookup_is_the_only_source_of_model_ids(self, config_file):
        config = load_config(config_file)
        assert config.model_for("sonnet") == "sonnet"
        assert config.model_for("opus") == "opus"
        assert config.model_for("fable") == "fable"
        with pytest.raises(ConfigurationError):
            config.model_for("gpt")

    def test_pinned_model_ids_need_no_code_change(self, tmp_path):
        (tmp_path / "c.toml").write_text(
            f"""
[dispatcher]
[models]
sonnet = "claude-sonnet-4-5-20250929"
opus = "claude-opus-4-1"
[routing]
[security]
allowed_repository_roots = ["{tmp_path}"]
"""
        )
        config = load_config(tmp_path / "c.toml")
        assert config.model_for("sonnet") == "claude-sonnet-4-5-20250929"
        assert config.model_for("fable") == "fable"  # default retained

    def test_clamp_timeout_respects_the_maximum(self, config_file):
        config = load_config(config_file)
        assert config.clamp_timeout(600) == 600
        assert config.clamp_timeout(99_999) == 3600


class TestFailsClosed:
    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigurationError, match="not found"):
            load_config(tmp_path / "nope.toml")

    def test_directory_instead_of_file(self, tmp_path):
        with pytest.raises(ConfigurationError):
            load_config(tmp_path)

    def test_malformed_toml(self, tmp_path):
        path = tmp_path / "bad.toml"
        path.write_text("[dispatcher\nstate_dir = ")
        with pytest.raises(ConfigurationError, match="not valid TOML"):
            load_config(path)

    def test_non_utf8_file(self, tmp_path):
        path = tmp_path / "bad.toml"
        path.write_bytes(b"\xff\xfe[dispatcher]\n")
        with pytest.raises(ConfigurationError, match="UTF-8"):
            load_config(path)

    @pytest.mark.parametrize(
        "section", ["dispatcher", "models", "routing", "security"]
    )
    def test_missing_required_section(self, tmp_path, config_text, section):
        text = "\n".join(
            line for line in config_text.splitlines() if line.strip() != f"[{section}]"
        )
        path = tmp_path / "c.toml"
        path.write_text(text)
        with pytest.raises(ConfigurationError) as exc:
            load_config(path)
        assert section in str(exc.value.details)

    def test_unknown_top_level_section(self, tmp_path, config_text):
        path = tmp_path / "c.toml"
        path.write_text(config_text + '\n[experimental]\nyolo = true\n')
        with pytest.raises(ConfigurationError, match="invalid"):
            load_config(path)

    def test_unknown_key_inside_a_section(self, tmp_path, config_text):
        path = tmp_path / "c.toml"
        path.write_text(config_text + '\n[dispatcher]\nallow_everything = true\n')
        with pytest.raises(ConfigurationError):
            load_config(path)

    def test_wrong_type(self, tmp_path, config_text):
        path = tmp_path / "c.toml"
        path.write_text(config_text.replace("default_timeout_seconds = 1800",
                                           'default_timeout_seconds = "soon"'))
        with pytest.raises(ConfigurationError) as exc:
            load_config(path)
        assert "default_timeout_seconds" in str(exc.value.details)

    def test_error_payload_stays_short_and_actionable(self, tmp_path, config_text):
        path = tmp_path / "c.toml"
        path.write_text(config_text.replace("default_timeout_seconds = 1800",
                                           "default_timeout_seconds = 0"))
        with pytest.raises(ConfigurationError) as exc:
            load_config(path)
        payload = exc.value.to_payload()
        assert payload["error"] == "ConfigurationError"
        assert "Traceback" not in str(payload)
        assert len(str(payload)) < 2000


class TestRepositoryAllowlist:
    """§24: do not accept arbitrary filesystem paths."""

    def _write(self, tmp_path, roots: str) -> Path:
        path = tmp_path / "c.toml"
        path.write_text(
            f"""
[dispatcher]
[models]
[routing]
[security]
allowed_repository_roots = {roots}
"""
        )
        return path

    def test_placeholder_is_rejected(self, tmp_path):
        path = self._write(tmp_path, f'["{PLACEHOLDER_ROOT}"]')
        with pytest.raises(ConfigurationError) as exc:
            load_config(path)
        assert "CONFIGURE" in str(exc.value.details)

    def test_empty_allowlist_is_rejected(self, tmp_path):
        path = self._write(tmp_path, "[]")
        with pytest.raises(ConfigurationError):
            load_config(path)

    def test_root_slash_is_rejected(self, tmp_path):
        path = self._write(tmp_path, '["/"]')
        with pytest.raises(ConfigurationError) as exc:
            load_config(path)
        assert "broad" in str(exc.value.details) or "/" in str(exc.value.details)

    def test_relative_root_is_rejected(self, tmp_path):
        path = self._write(tmp_path, '["some/relative"]')
        with pytest.raises(ConfigurationError, match="invalid"):
            load_config(path)

    def test_nonexistent_root_is_rejected(self, tmp_path):
        path = self._write(tmp_path, f'["{tmp_path}/does-not-exist"]')
        with pytest.raises(ConfigurationError) as exc:
            load_config(path)
        assert "does not exist" in str(exc.value.details)

    def test_file_instead_of_directory_is_rejected(self, tmp_path):
        target = tmp_path / "afile"
        target.write_text("x")
        path = self._write(tmp_path, f'["{target}"]')
        with pytest.raises(ConfigurationError) as exc:
            load_config(path)
        assert "not a directory" in str(exc.value.details)

    def test_roots_are_canonicalised_on_load(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        messy = f"{tmp_path}/real/./"
        path = self._write(tmp_path, f'["{messy}"]')
        config = load_config(path)
        assert config.security.allowed_repository_roots == [str(real.resolve())]

    def test_symlinked_root_resolves_to_its_target(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        path = self._write(tmp_path, f'["{link}"]')
        config = load_config(path)
        assert config.security.allowed_repository_roots == [str(real.resolve())]


class TestSecurityDefaultsAreRestrictive:
    def test_all_permissions_default_to_false(self, config_file):
        s = load_config(config_file).security
        assert s.allow_network is False
        assert s.allow_push is False
        assert s.allow_merge is False
        assert s.allow_commit is False
        assert s.allow_subagents is False

    def test_dispatch_depth_cannot_exceed_one(self, tmp_path, config_text):
        path = tmp_path / "c.toml"
        path.write_text(config_text.replace("max_dispatch_depth = 1",
                                           "max_dispatch_depth = 5"))
        with pytest.raises(ConfigurationError) as exc:
            load_config(path)
        assert "max_dispatch_depth" in str(exc.value.details)

    def test_fable_cannot_be_the_default_implementation_model(self, tmp_path, config_text):
        path = tmp_path / "c.toml"
        path.write_text(config_text.replace('default_model = "sonnet"',
                                           'default_model = "fable"'))
        with pytest.raises(ConfigurationError) as exc:
            load_config(path)
        assert "default_model" in str(exc.value.details)

    def test_bypass_permissions_mode_is_not_offered(self, tmp_path, config_text):
        path = tmp_path / "c.toml"
        path.write_text(
            config_text + '\n[claude]\npermission_mode = "bypassPermissions"\n'
        )
        with pytest.raises(ConfigurationError) as exc:
            load_config(path)
        assert "permission_mode" in str(exc.value.details)

    def test_unknown_logging_level_is_rejected(self, tmp_path, config_text):
        path = tmp_path / "c.toml"
        path.write_text(config_text + '\n[logging]\nlevel = "CHATTY"\n')
        with pytest.raises(ConfigurationError):
            load_config(path)


class TestLoadFromMapping:
    def test_accepts_a_valid_mapping(self, tmp_path):
        config = load_config_from_mapping(
            {
                "dispatcher": {},
                "models": {},
                "routing": {},
                "security": {"allowed_repository_roots": [str(tmp_path)]},
            },
            project_root=tmp_path,
        )
        assert config.source_path is None
        assert config.project_root == str(tmp_path.resolve())

    def test_rejects_a_non_mapping(self):
        with pytest.raises(ConfigurationError):
            load_config_from_mapping(["not", "a", "table"])  # type: ignore[arg-type]

    def test_reports_every_missing_section_at_once(self):
        with pytest.raises(ConfigurationError) as exc:
            load_config_from_mapping({"dispatcher": {}})
        missing = exc.value.details["missing_sections"]
        assert set(missing) == {"models", "routing", "security"}
