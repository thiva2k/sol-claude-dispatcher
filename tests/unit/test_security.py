"""Tests for ``sol_claude_dispatcher.security`` (§24, §22, §28, §31)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from sol_claude_dispatcher import security
from sol_claude_dispatcher.config import load_config_from_mapping
from sol_claude_dispatcher.errors import (
    InvalidRepository,
    InvalidTaskEnvelope,
    RecursionDetected,
    RepositoryNotAllowed,
)
from sol_claude_dispatcher.models import new_task_id


def _make_config(tmp_path: Path, allowed_roots: list[Path], **security_overrides):
    sec = {"allowed_repository_roots": [str(r) for r in allowed_roots]}
    sec.update(security_overrides)
    data = {
        "dispatcher": {},
        "models": {},
        "routing": {},
        "security": sec,
    }
    return load_config_from_mapping(data, project_root=str(tmp_path))


# ---------------------------------------------------------------------------
# validate_repository_root
# ---------------------------------------------------------------------------


def test_valid_repository_root_is_accepted(git_repo: Path) -> None:
    config = _make_config(git_repo.parent, [git_repo])
    result = security.validate_repository_root(str(git_repo), config)
    assert result == git_repo.resolve()
    assert isinstance(result, Path)


def test_repository_outside_allowlist_is_rejected(tmp_path: Path, git_repo: Path) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    config = _make_config(tmp_path, [other])
    with pytest.raises(RepositoryNotAllowed):
        security.validate_repository_root(str(git_repo), config)


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    """A symlink inside an allowed root pointing outside it must not pass.

    ``/srv/app-evil`` must not match an allowlist entry of ``/srv/app``, and
    neither may a symlink that resolves out of the allowed root.
    """
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    evil = tmp_path / "evil"
    evil.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=evil, check=True)

    escape_link = allowed / "escape"
    escape_link.symlink_to(evil, target_is_directory=True)

    config = _make_config(tmp_path, [allowed])
    with pytest.raises(RepositoryNotAllowed):
        security.validate_repository_root(str(escape_link), config)


def test_string_prefix_lookalike_is_rejected(tmp_path: Path) -> None:
    """``/srv/app-evil`` must not pass an allowlist of ``/srv/app`` by prefix."""
    app = tmp_path / "app"
    app.mkdir()
    app_evil = tmp_path / "app-evil"
    app_evil.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=app_evil, check=True)

    config = _make_config(tmp_path, [app])
    with pytest.raises(RepositoryNotAllowed):
        security.validate_repository_root(str(app_evil), config)


def test_nonexistent_repository_is_rejected(tmp_path: Path) -> None:
    config = _make_config(tmp_path, [tmp_path])
    missing = tmp_path / "does-not-exist"
    with pytest.raises(InvalidRepository):
        security.validate_repository_root(str(missing), config)


def test_non_git_directory_is_rejected(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    config = _make_config(tmp_path, [tmp_path])
    with pytest.raises(InvalidRepository):
        security.validate_repository_root(str(plain), config)


def test_path_traversal_is_resolved_before_the_allowlist_check(
    tmp_path: Path, git_repo: Path
) -> None:
    """A ``..``-bearing path must be canonicalised, not string-matched."""
    config = _make_config(tmp_path, [git_repo])
    escape = str(git_repo / ".." / "escaped-target")
    with pytest.raises((InvalidRepository, RepositoryNotAllowed)):
        security.validate_repository_root(escape, config)


def test_relative_root_is_rejected(tmp_path: Path) -> None:
    config = _make_config(tmp_path, [tmp_path])
    with pytest.raises(InvalidRepository):
        security.validate_repository_root("relative/path", config)


def test_empty_root_is_rejected(tmp_path: Path) -> None:
    config = _make_config(tmp_path, [tmp_path])
    with pytest.raises(InvalidRepository):
        security.validate_repository_root("", config)


def test_null_byte_in_root_is_rejected(tmp_path: Path) -> None:
    config = _make_config(tmp_path, [tmp_path])
    with pytest.raises(InvalidRepository):
        security.validate_repository_root(f"{tmp_path}/foo\x00bar", config)


def test_subdirectory_of_an_allowed_repository_is_rejected(git_repo: Path) -> None:
    """P0-2: repository identity is the git top level, not "somewhere inside it".

    The previous rule (``path == root or root in path.parents``) accepted a
    subdirectory, which gave one repository two identities — two lock names and
    two evidence roots.
    """
    sub = git_repo / "src"
    sub.mkdir()
    config = _make_config(git_repo.parent, [git_repo])
    with pytest.raises((InvalidRepository, RepositoryNotAllowed)):
        security.validate_repository_root(str(sub), config)


def test_allowlisting_a_parent_directory_does_not_allow_the_repository(
    git_repo: Path,
) -> None:
    """Allowlist matching is exact equality, not ancestry."""
    config = _make_config(git_repo.parent, [git_repo.parent])
    with pytest.raises((InvalidRepository, RepositoryNotAllowed)):
        security.validate_repository_root(str(git_repo), config)


def test_accepted_root_is_the_canonical_git_top_level(git_repo: Path) -> None:
    """Every downstream decision uses git's answer, not the caller's spelling."""
    config = _make_config(git_repo.parent, [git_repo])
    result = security.validate_repository_root(f"{git_repo}/", config)
    assert result == git_repo.resolve()


# ---------------------------------------------------------------------------
# validate_task_id
# ---------------------------------------------------------------------------


def test_validate_task_id_accepts_a_dispatcher_issued_id() -> None:
    task_id = new_task_id()
    assert security.validate_task_id(task_id) == task_id


@pytest.mark.parametrize(
    "hostile",
    ["../escape", "../../escape", "/foo", "foo/bar", "foo\\bar", ".", "..", "",
     "   ", "\x00", "not-a-uuid", "5F9C1F2E-0D3A-4B6F-8A1C-2B3D4E5F6A7B"],
)
def test_validate_task_id_refuses_hostile_input(hostile: str) -> None:
    with pytest.raises(InvalidTaskEnvelope):
        security.validate_task_id(hostile)


# ---------------------------------------------------------------------------
# assert_no_recursion
# ---------------------------------------------------------------------------


def test_recursion_detected_when_worker_marker_present(tmp_path: Path) -> None:
    config = _make_config(tmp_path, [tmp_path])
    with pytest.raises(RecursionDetected):
        security.assert_no_recursion(config, env={"SOL_WORKER": "1"})


def test_recursion_override_permits_the_marker(tmp_path: Path) -> None:
    config = _make_config(tmp_path, [tmp_path])
    security.assert_no_recursion(
        config,
        env={"SOL_WORKER": "1", "SOL_DISPATCHER_TEST_OVERRIDE": "1"},
    )  # must not raise


def test_no_recursion_without_marker(tmp_path: Path) -> None:
    config = _make_config(tmp_path, [tmp_path])
    security.assert_no_recursion(config, env={})  # must not raise


# ---------------------------------------------------------------------------
# assert_dispatch_depth
# ---------------------------------------------------------------------------


def test_dispatch_depth_exceeding_max_is_rejected(tmp_path: Path) -> None:
    config = _make_config(tmp_path, [tmp_path], max_dispatch_depth=1)
    with pytest.raises(RecursionDetected):
        security.assert_dispatch_depth(2, config)


def test_dispatch_depth_within_max_is_accepted(tmp_path: Path) -> None:
    config = _make_config(tmp_path, [tmp_path], max_dispatch_depth=1)
    security.assert_dispatch_depth(1, config)  # must not raise
    security.assert_dispatch_depth(0, config)  # must not raise


# ---------------------------------------------------------------------------
# worker_environment
# ---------------------------------------------------------------------------


def test_worker_environment_sets_the_three_markers() -> None:
    base_env = {"PATH": "/usr/bin", "HOME": "/home/x"}
    env = security.worker_environment(base_env, task_id="task-123", dispatch_depth=0)
    assert env["SOL_WORKER"] == "1"
    assert env["SOL_DISPATCH_DEPTH"] == "1"
    assert env["SOL_TASK_ID"] == "task-123"


def test_worker_environment_increments_dispatch_depth() -> None:
    env = security.worker_environment({}, task_id="t", dispatch_depth=3)
    assert env["SOL_DISPATCH_DEPTH"] == "4"


def test_worker_environment_strips_secret_shaped_keys() -> None:
    base_env = {
        "PATH": "/usr/bin",
        "API_KEY": "should-not-survive",
        "AWS_SECRET_ACCESS_KEY": "should-not-survive",
        "AUTH_TOKEN": "should-not-survive",
        "COOKIE": "should-not-survive",
        "DB_PASSWORD": "should-not-survive",
    }
    env = security.worker_environment(base_env, task_id="t", dispatch_depth=0)
    for key in (
        "API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AUTH_TOKEN",
        "COOKIE",
        "DB_PASSWORD",
    ):
        assert key not in env


def test_worker_environment_strips_dispatcher_internal_keys() -> None:
    base_env = {"SOL_DISPATCHER_CONFIG": "/x/config.toml", "PATH": "/usr/bin"}
    env = security.worker_environment(base_env, task_id="t", dispatch_depth=0)
    assert "SOL_DISPATCHER_CONFIG" not in env
    assert env["PATH"] == "/usr/bin"


def test_worker_environment_keeps_ordinary_keys() -> None:
    base_env = {
        "PATH": "/usr/bin",
        "HOME": "/home/x",
        "LANG": "en_US.UTF-8",
        "TERM": "xterm",
        "USER": "worker",
        "SHELL": "/bin/bash",
        "TMPDIR": "/tmp",
    }
    env = security.worker_environment(base_env, task_id="t", dispatch_depth=0)
    for key, value in base_env.items():
        assert env[key] == value


# ---------------------------------------------------------------------------
# redact
# ---------------------------------------------------------------------------


def test_redact_masks_env_style_pairs() -> None:
    text = "API_KEY=super-secret-value other=fine"
    redacted = security.redact(text)
    assert "super-secret-value" not in redacted
    assert "API_KEY=***REDACTED***" in redacted
    assert "other=fine" in redacted


def test_redact_masks_json_style_pairs() -> None:
    text = '{"token": "abc123", "name": "ok"}'
    redacted = security.redact(text)
    assert "abc123" not in redacted
    assert '"token": "***REDACTED***"' in redacted
    assert '"name": "ok"' in redacted


def test_redact_is_case_insensitive() -> None:
    text = "authorization=Bearer-xyz123"
    redacted = security.redact(text)
    assert "Bearer-xyz123" not in redacted
    assert "authorization=***REDACTED***" in redacted


# ---------------------------------------------------------------------------
# redact — cost (Lane B adjacent finding A3)
#
# ``redact()`` is applied to whole worker streams, which are bounded at
# 2 x 1 MB per stream in memory and are unbounded on the spool path. The
# original ``[A-Za-z_][A-Za-z0-9_]*=\S*`` pattern retried at every offset
# inside a long ``=``-free token, so cost grew quadratically: Lane B observed a
# 3 MB stderr redaction outliving the worker's own 60 s timeout. The fix must
# not change what gets masked.
# ---------------------------------------------------------------------------


#: Cases chosen to pin the exact shapes the pre-fix pattern handled, including
#: the awkward ones (a key that begins after a digit, a value containing a
#: second ``=``, an empty value, a key immediately after punctuation).
REDACTION_CASES = [
    ("API_KEY=super-secret-value other=fine", "API_KEY=***REDACTED***"),
    ("export AUTH_TOKEN=abc123", "AUTH_TOKEN=***REDACTED***"),
    ("MY_PASSWORD=", "MY_PASSWORD=***REDACTED***"),
    ("A=b=c TOKEN=x", "TOKEN=***REDACTED***"),
    # A key reached mid-token after a digit: the old pattern began matching at
    # the first letter, the anchored one begins at the digit, and both render
    # the same text because key matching is a substring test.
    ("9API_KEY=x", "9API_KEY=***REDACTED***"),
    # An empty key can never start a pair; the pair after it still must.
    ("=TOKEN=s", "=TOKEN=***REDACTED***"),
    # Digits-only key is not a key: the following pair is still found.
    ("12=TOKEN=s", "12=TOKEN=***REDACTED***"),
    ('{"token": "abc123", "name": "ok"}', '"token": "***REDACTED***"'),
    ("PATH=/usr/bin", "PATH=/usr/bin"),
]


@pytest.mark.parametrize(("text", "expected_fragment"), REDACTION_CASES)
def test_redaction_semantics_survive_the_anchored_pattern(
    text: str, expected_fragment: str
) -> None:
    assert expected_fragment in security.redact(text)


@pytest.mark.parametrize(
    "text",
    [
        "API_KEY=super-secret-value other=fine",
        "export AUTH_TOKEN=abc123",
        "9API_KEY=x",
        "=TOKEN=s",
        "12=TOKEN=s",
        "PATH=/usr/bin HOME=/home/dev",
        "a" * 200,
        "".join("k%d=v%d " % (i, i) for i in range(50)),
    ],
)
def test_no_env_pair_match_starts_inside_an_identifier_run(text: str) -> None:
    """The structural property that makes the pattern linear.

    A match may only begin where an identifier run begins. This is what stops
    the engine restarting — and rescanning — at every offset of a long token,
    and it is checkable without measuring anything.
    """
    for match in security._ENV_PAIR_RE.finditer(text):
        start = match.start()
        if start == 0:
            continue
        preceding = text[start - 1]
        assert not (preceding.isalnum() or preceding == "_"), (
            f"match at offset {start} starts inside an identifier run: "
            f"{text[max(0, start - 5):start + 10]!r}"
        )


#: Wall time the child is allowed for a 4 MB redaction. This is a *bound*, not
#: a measurement: the linear implementation does it in well under a second on
#: this machine, while the quadratic one extrapolates to over a day (measured:
#: 3.7 s for 16 KB, cost x4 per doubling, 4 MB is 8 further doublings). Any
#: value between "a second" and "a day" makes the test decide the same way, so
#: there is no threshold to tune and nothing for machine load to flip.
_REDACTION_BUDGET_SECONDS = 20.0

_BULK_REDACTION_CHILD = r"""
import sys
from sol_claude_dispatcher.security import redact

# 4 MB of one unbroken =-free identifier run: the exact shape that made the
# unanchored pattern restart at every offset.
blob = "A" * (4 * 1024 * 1024)
text = "\n".join([
    "GITHUB_TOKEN=ghp_realsecret",
    blob,
    '{"api_key": "leaked"}',
    "HARMLESS=keepme",
])
out = redact(text)
assert "ghp_realsecret" not in out, "env-style secret survived"
assert "leaked" not in out, "json-style secret survived"
assert "GITHUB_TOKEN=***REDACTED***" in out
assert '"api_key": "***REDACTED***"' in out
assert "HARMLESS=keepme" in out
assert blob in out, "bulk text was corrupted"
sys.stdout.write("OK")
"""


def test_bulk_redaction_completes_within_a_bounded_time(project_root: Path) -> None:
    """A multi-megabyte stream must redact in bounded time, correctly.

    Run in a child process so that a regression cannot hang the test session:
    Python's ``re`` does not release the GIL, so a quadratic match in a thread
    would freeze every other test rather than fail this one.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(project_root / "src"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", _BULK_REDACTION_CHILD],
            capture_output=True,
            text=True,
            timeout=_REDACTION_BUDGET_SECONDS,
            env=env,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            "redact() did not finish 4 MB of input within "
            f"{_REDACTION_BUDGET_SECONDS:.0f}s — the pattern has regressed to "
            "superlinear backtracking (Lane B adjacent finding A3)."
        )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "OK"
