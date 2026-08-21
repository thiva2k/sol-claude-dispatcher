"""``scripts/check-production-activation.py`` — the operational activation check.

Background. Until the commissioning -> production transition (2026-08-21) three
ordinary tests asserted the *inert* state of ``config/dispatcher.toml``. That
file is gitignored and host-local, so those assertions made repository
correctness depend on whether the machine running the suite happened to be
activated — wrong for a repository test, and guaranteed to break the moment Sol
activated production.

The tripwire was not deleted; it moved here and became explicit. The checker
takes the expected state as a REQUIRED argument, so it can still catch a host
that is not in the state the operator believes it is in, while the test suite
stays green in either legitimate deployment state.

Nothing in this file launches a real process or touches the real host config.
Every configuration and manifest is a throwaway under ``tmp_path``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = PROJECT_ROOT / "scripts" / "check-production-activation.py"
REAL_GUIDANCE_MANIFEST = PROJECT_ROOT / "config" / "approved-guidance.json"


def _load_checker():
    """Import the script by path — it is a tool, not an installed module."""
    spec = importlib.util.spec_from_file_location("check_production_activation", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


# ---------------------------------------------------------------------------
# Fixtures: throwaway configs and manifests
# ---------------------------------------------------------------------------


def _write_manifest(tmp_path: Path, state: str) -> Path:
    """A copy of the real manifest with only ``approval.state`` rewritten."""
    data = json.loads(REAL_GUIDANCE_MANIFEST.read_text())
    data["approval"] = dict(data["approval"], state=state)
    path = tmp_path / "guidance.json"
    path.write_text(json.dumps(data))
    return path


def _write_config(
    tmp_path: Path,
    *,
    skills_enabled: bool,
    guidance_enabled: bool,
    manifest_path: Path,
    skills_cap: int = 72_000,
    guidance_cap: int = 42_000,
    skills_mode: str = "projected",
    guidance_fail_on_drift: bool = True,
    root: Path | None = None,
) -> Path:
    """Write a minimal but genuinely loadable dispatcher config."""
    repo_root = root if root is not None else tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)

    def b(value: bool) -> str:
        return "true" if value else "false"

    path = tmp_path / "config" / "dispatcher.toml"
    path.write_text(
        f"""
[dispatcher]
state_dir = "{tmp_path / "state"}"

[models]
sonnet = "sonnet"
opus = "opus"
fable = "fable"

[routing]
default_model = "sonnet"

[security]
allowed_repository_roots = ["{repo_root}"]

[skills]
enabled = {b(skills_enabled)}
mode = "{skills_mode}"
fail_on_drift = true
max_projected_bytes = {skills_cap}
manifest_path = "{PROJECT_ROOT / "config" / "approved-skills.json"}"

[project_guidance]
enabled = {b(guidance_enabled)}
mode = "projected"
fail_on_drift = {b(guidance_fail_on_drift)}
max_projected_bytes = {guidance_cap}
manifest_path = "{manifest_path}"
"""
    )
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run(config: Path, expect: str, repo: Path, *extra: str) -> int:
    return checker.main(
        ["--expect", expect, "--config", str(config), "--expect-root", str(repo), *extra]
    )


# ---------------------------------------------------------------------------
# The two states the checker recognises
# ---------------------------------------------------------------------------


class TestExpectedStateMatches:
    def test_inert_config_passes_expect_inert(self, tmp_path: Path, repo: Path):
        config = _write_config(
            tmp_path,
            skills_enabled=False,
            guidance_enabled=False,
            manifest_path=_write_manifest(tmp_path, "PENDING_SOL"),
            root=repo,
        )
        assert _run(config, "inert", repo) == 0

    def test_active_config_with_approved_manifest_passes_expect_active(
        self, tmp_path: Path, repo: Path
    ):
        config = _write_config(
            tmp_path,
            skills_enabled=True,
            guidance_enabled=True,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            root=repo,
        )
        assert _run(config, "active", repo) == 0

    def test_an_inert_host_is_not_reported_as_active(self, tmp_path: Path, repo: Path):
        """The states are not interchangeable in either direction."""
        config = _write_config(
            tmp_path,
            skills_enabled=False,
            guidance_enabled=False,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            root=repo,
        )
        assert _run(config, "inert", repo) == 0
        assert _run(config, "active", repo) == 1


# ---------------------------------------------------------------------------
# Mismatches must exit non-zero — this is the tripwire's whole purpose
# ---------------------------------------------------------------------------


class TestExpectedStateMismatch:
    @pytest.mark.parametrize(
        ("skills_enabled", "guidance_enabled"),
        [(True, False), (False, True)],
        ids=["guidance-off", "skills-off"],
    )
    def test_active_with_one_flag_false_fails(
        self, tmp_path: Path, repo: Path, skills_enabled: bool, guidance_enabled: bool
    ):
        """Half-activation is the dangerous shape, so it must not pass."""
        config = _write_config(
            tmp_path,
            skills_enabled=skills_enabled,
            guidance_enabled=guidance_enabled,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            root=repo,
        )
        assert _run(config, "active", repo) == 1

    def test_active_with_pending_sol_guidance_fails(self, tmp_path: Path, repo: Path):
        """Flags on but the manifest unapproved: enabled, yet refuses every task."""
        config = _write_config(
            tmp_path,
            skills_enabled=True,
            guidance_enabled=True,
            manifest_path=_write_manifest(tmp_path, "PENDING_SOL"),
            root=repo,
        )
        assert _run(config, "active", repo) == 1

    @pytest.mark.parametrize(
        ("skills_enabled", "guidance_enabled"),
        [(True, False), (False, True), (True, True)],
        ids=["skills-on", "guidance-on", "both-on"],
    )
    def test_inert_with_either_flag_true_fails(
        self, tmp_path: Path, repo: Path, skills_enabled: bool, guidance_enabled: bool
    ):
        config = _write_config(
            tmp_path,
            skills_enabled=skills_enabled,
            guidance_enabled=guidance_enabled,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            root=repo,
        )
        assert _run(config, "inert", repo) == 1

    def test_a_different_repository_root_fails_in_both_states(
        self, tmp_path: Path, repo: Path
    ):
        """Activation must not become approval of some other repository."""
        other = tmp_path / "other-repo"
        other.mkdir()
        config = _write_config(
            tmp_path,
            skills_enabled=True,
            guidance_enabled=True,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            root=other,
        )
        # The config is internally consistent; it just is not the approved root.
        assert _run(config, "active", repo) == 1
        config_inert = _write_config(
            tmp_path,
            skills_enabled=False,
            guidance_enabled=False,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            root=other,
        )
        assert _run(config_inert, "inert", repo) == 1

    def test_a_relaxed_invariant_fails_even_in_the_inert_state(
        self, tmp_path: Path, repo: Path
    ):
        """fail_on_drift is not a deployment-state property; it must always hold.

        ``fail_on_drift = false`` is refused by the loader itself, so this is a
        load failure (exit 2), not a check failure — which is the correct
        distinction: a config that cannot load is neither active nor inert.
        """
        config = _write_config(
            tmp_path,
            skills_enabled=False,
            guidance_enabled=False,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            guidance_fail_on_drift=False,
            root=repo,
        )
        assert _run(config, "inert", repo) == 2


# ---------------------------------------------------------------------------
# Broken configuration is a third outcome, not a silent pass
# ---------------------------------------------------------------------------


class TestUnloadableConfiguration:
    def test_invalid_b1_caps_fail_through_normal_config_loading(
        self, tmp_path: Path, repo: Path
    ):
        """The checker does not re-implement B1; it lets the loader refuse.

        skills 120,000 + guidance 60,000 + 8,192 reserve = 188,192 bytes, far
        above the 122,880-byte transport ceiling.
        """
        config = _write_config(
            tmp_path,
            skills_enabled=True,
            guidance_enabled=True,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            skills_cap=120_000,
            guidance_cap=60_000,
            root=repo,
        )
        assert _run(config, "active", repo) == 2
        assert _run(config, "inert", repo) == 2

    def test_native_skill_mode_fails_to_load(self, tmp_path: Path, repo: Path):
        config = _write_config(
            tmp_path,
            skills_enabled=True,
            guidance_enabled=True,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            skills_mode="native",
            root=repo,
        )
        assert _run(config, "active", repo) == 2

    def test_a_missing_config_fails_rather_than_passing(self, tmp_path: Path, repo: Path):
        assert _run(tmp_path / "nope.toml", "inert", repo) == 2

    def test_a_missing_guidance_manifest_fails_expect_active(
        self, tmp_path: Path, repo: Path
    ):
        config = _write_config(
            tmp_path,
            skills_enabled=True,
            guidance_enabled=True,
            manifest_path=tmp_path / "absent.json",
            root=repo,
        )
        assert _run(config, "active", repo) == 1


# ---------------------------------------------------------------------------
# The checker is READ-ONLY
# ---------------------------------------------------------------------------


class TestTheCheckerWritesNothing:
    @staticmethod
    def _snapshot(root: Path) -> dict[str, str]:
        snap: dict[str, str] = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                snap[str(path.relative_to(root))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
        return snap

    @pytest.mark.parametrize("expect", ["active", "inert"])
    def test_no_file_is_created_modified_or_removed(
        self, tmp_path: Path, repo: Path, expect: str
    ):
        _write_config(
            tmp_path,
            skills_enabled=True,
            guidance_enabled=True,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            root=repo,
        )
        config = tmp_path / "config" / "dispatcher.toml"

        before = self._snapshot(tmp_path)
        _run(config, expect, repo)
        after = self._snapshot(tmp_path)

        assert after == before

    def test_it_does_not_create_the_state_directory(self, tmp_path: Path, repo: Path):
        """Merely loading a config must not provision anything on disk."""
        config = _write_config(
            tmp_path,
            skills_enabled=False,
            guidance_enabled=False,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            root=repo,
        )
        _run(config, "inert", repo)
        assert not (tmp_path / "state").exists()

    def test_it_never_rewrites_an_unapproved_manifest(self, tmp_path: Path, repo: Path):
        """A checker that could 'fix' PENDING_SOL would defeat its own purpose."""
        manifest = _write_manifest(tmp_path, "PENDING_SOL")
        digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
        config = _write_config(
            tmp_path,
            skills_enabled=True,
            guidance_enabled=True,
            manifest_path=manifest,
            root=repo,
        )
        assert _run(config, "active", repo) == 1
        assert hashlib.sha256(manifest.read_bytes()).hexdigest() == digest
        assert json.loads(manifest.read_text())["approval"]["state"] == "PENDING_SOL"


# ---------------------------------------------------------------------------
# The expected state is stated, never inferred
# ---------------------------------------------------------------------------


class TestTheExpectationIsExplicit:
    def test_expect_is_required(self):
        with pytest.raises(SystemExit) as exc:
            checker.build_parser().parse_args([])
        assert exc.value.code == 2

    def test_only_the_two_known_states_are_accepted(self):
        with pytest.raises(SystemExit):
            checker.build_parser().parse_args(["--expect", "probably-fine"])

    def test_no_environment_variable_selects_the_expected_state(
        self, tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Every plausible env hatch is set; the stated expectation still wins."""
        config = _write_config(
            tmp_path,
            skills_enabled=False,
            guidance_enabled=False,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            root=repo,
        )
        for name in (
            "SOL_EXPECT",
            "SOL_ACTIVATION_STATE",
            "EXPECT",
            "SOL_DISPATCHER_EXPECT",
            "SOL_DISPATCHER_ACTIVATION",
            "PRODUCTION_ACTIVATION",
        ):
            monkeypatch.setenv(name, "active")
        # Still judged against the argument that was passed, so an inert host
        # asked about 'active' still fails.
        assert _run(config, "active", repo) == 1
        assert _run(config, "inert", repo) == 0

    def test_json_report_is_machine_readable(self, tmp_path: Path, repo: Path, capsys):
        config = _write_config(
            tmp_path,
            skills_enabled=True,
            guidance_enabled=True,
            manifest_path=_write_manifest(tmp_path, "APPROVED"),
            root=repo,
        )
        assert _run(config, "active", repo, "--json") == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["expected_state"] == "active"
        assert payload["ok"] is True
        assert all(check["ok"] for check in payload["checks"])
