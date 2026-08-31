#!/usr/bin/env python3
"""Gate 7 revision 10 — object-admission boundary probes.

Every fixture is created in a TemporaryDirectory.  The probe never opens or
modifies a pre-existing repository.

It measures four facts used by revision 10:

1. A regular file with a loose-object-shaped name is not necessarily the
   content-addressed object named by that path, and such a file changes G9.
2. An ordinary commit can create new two-hex fan-out directories as well as
   new loose-object files.
3. ``(entry_type, size, sha256_digest=None)`` cannot identify a symlink: a
   same-length target change is invisible to that tuple.
4. A SHA-256 repository declares its object format in the raw local config and
   writes 62-hex loose-object tails.

Every negative leg has an armed positive/control leg.  Any failed control makes
the program exit non-zero.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import zlib


GIT = shutil.which("git")
if not GIT:
    raise SystemExit("CONTROL FAILURE: git is not resolvable")
GIT = os.path.realpath(GIT)

CHILD_ENV = {
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
}

FIXTURE_ENV = dict(os.environ)
FIXTURE_ENV.update(
    {
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
    }
)


def run(
    args: list[str],
    cwd: Path,
    *,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        input=input_bytes,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"fixture command failed: {args!r}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
    return result


def git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = run([GIT, *args], cwd, env=FIXTURE_ENV if env is None else env)
    return result.stdout.decode("utf-8", "replace").strip()


def init_repo(root: Path, *, object_format: str = "sha1") -> None:
    git(root, "init", "-q", "-b", "main", f"--object-format={object_format}", ".")
    git(root, "config", "user.email", "gate7-v10@example.invalid")
    git(root, "config", "user.name", "Gate 7 revision 10")


def pin_block(hooks: Path) -> list[str]:
    return [
        "-c",
        f"core.hooksPath={hooks}",
        "-c",
        "core.commitGraph=false",
        "-c",
        "core.multiPackIndex=false",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "core.quotePath=false",
        "--no-pager",
    ]


def g9(root: Path, hooks: Path) -> list[str]:
    result = run(
        [GIT, *pin_block(hooks), "rev-list", "--objects", "--missing=print", "HEAD"],
        root,
        env=dict(CHILD_ENV),
    )
    return result.stdout.decode("utf-8", "replace").splitlines()


def loose_path(root: Path, oid: str) -> Path:
    return root / ".git" / "objects" / oid[:2] / oid[2:]


def validate_sha1_loose_object(path: Path, oid: str) -> tuple[bool, str]:
    """Small reference validator for the probe, not production code.

    Revision 10 specifies a bounded streaming implementation.  This fixture is
    intentionally tiny, so the probe uses ``zlib.decompress`` to demonstrate
    the semantic check: canonical bytes, declared size, and SHA-1 pathname.
    """

    try:
        canonical = zlib.decompress(path.read_bytes())
    except (OSError, zlib.error) as exc:
        return False, f"inflate failed: {type(exc).__name__}"
    header, separator, content = canonical.partition(b"\0")
    if separator != b"\0":
        return False, "missing NUL header separator"
    fields = header.split(b" ", 1)
    if len(fields) != 2 or fields[0] not in {b"blob", b"tree", b"commit", b"tag"}:
        return False, "invalid object type/header"
    try:
        declared = int(fields[1])
    except ValueError:
        return False, "invalid declared size"
    if declared != len(content):
        return False, "declared size mismatch"
    actual_oid = hashlib.sha1(canonical, usedforsecurity=False).hexdigest()
    if actual_oid != oid:
        return False, f"oid mismatch: {actual_oid}"
    return True, "canonical object digest matches pathname"


def object_entries(root: Path) -> set[tuple[str, str]]:
    objects = root / ".git" / "objects"
    result: set[tuple[str, str]] = set()
    for dirpath, dirnames, filenames in os.walk(objects):
        dirnames.sort()
        filenames.sort()
        current = Path(dirpath)
        for name in dirnames:
            relative = (current / name).relative_to(objects).as_posix()
            result.add((relative, "directory"))
        for name in filenames:
            relative = (current / name).relative_to(objects).as_posix()
            result.add((relative, "regular"))
    return result


def symlink_tuple(path: Path) -> tuple[str, int, None]:
    metadata = os.lstat(path)
    if not stat.S_ISLNK(metadata.st_mode):
        raise AssertionError("control fixture stopped being a symlink")
    return ("symlink", metadata.st_size, None)


print("=" * 78)
print(f"git binary : {GIT}")
print(f"git version: {git(Path('/'), '--version')}")
print(f"python     : {sys.version.split()[0]}")
print(f"uid        : {os.getuid()}")
print("=" * 78)


print("\n### A. OBJECT-SHAPED CORRUPT BYTES CHANGE THE PINNED G9 ROW")
with tempfile.TemporaryDirectory(prefix="gate7-v10-g9-") as temporary:
    root = Path(temporary)
    hooks = root / "empty-hooks"
    hooks.mkdir()
    init_repo(root)
    (root / "f").write_text("payload\n")
    git(root, "add", "f")
    git(root, "commit", "-q", "-m", "base")
    oid = git(root, "rev-parse", "HEAD:f")
    object_path = loose_path(root, oid)
    valid, valid_reason = validate_sha1_loose_object(object_path, oid)
    print(f"  blob oid                         : {oid}")
    print(f"  path shape                       : objects/{oid[:2]}/{oid[2:]}")
    print(f"  VALID OBJECT CONTROL             : {valid} ({valid_reason})")
    if not valid:
        raise SystemExit("CONTROL FAILURE: git-written object did not validate")

    saved = root / "saved-object"
    object_path.rename(saved)
    missing = g9(root, hooks)
    missing_row = f"?{oid}"
    missing_fired = missing_row in missing
    print(f"  missing-object G9 row            : {missing_row!r}")
    print(f"  MISSING CONTROL FIRED            : {missing_fired}")
    if not missing_fired:
        raise SystemExit("CONTROL FAILURE: G9 did not report the absent blob")

    object_path.write_bytes(b"corrupt object-shaped bytes")
    corrupt_valid, corrupt_reason = validate_sha1_loose_object(object_path, oid)
    present = g9(root, hooks)
    present_rows = [row for row in present if row.startswith(oid)]
    output_changed = missing != present and missing_row not in present and bool(present_rows)
    print(f"  corrupt file entry_type          : regular")
    print(f"  corrupt path matches 2/38 shape  : True")
    print(f"  canonical validator accepts      : {corrupt_valid} ({corrupt_reason})")
    print(f"  pinned G9 rows for oid afterward : {present_rows}")
    print(f"  G9 OUTPUT CHANGED                : {output_changed}")
    if corrupt_valid or not output_changed:
        raise SystemExit("CONTROL FAILURE: corrupt-path boundary did not fire")


print("\n### B. A NORMAL COMMIT CREATES FAN-OUT DIRECTORIES")
with tempfile.TemporaryDirectory(prefix="gate7-v10-fanout-") as temporary:
    root = Path(temporary)
    init_repo(root)
    (root / "f").write_text("base\n")
    git(root, "add", "f")
    git(root, "commit", "-q", "-m", "base")
    baseline = object_entries(root)
    discovered_dirs: list[str] = []
    discovered_files: list[str] = []
    commits_needed = 0
    for index in range(1, 65):
        (root / "f").write_text(f"change {index}\n")
        git(root, "add", "f")
        git(root, "commit", "-q", "-m", f"change-{index}")
        added = object_entries(root) - baseline
        discovered_dirs = sorted(
            path
            for path, kind in added
            if kind == "directory"
            and len(path) == 2
            and all(char in "0123456789abcdef" for char in path)
        )
        discovered_files = sorted(
            path
            for path, kind in added
            if kind == "regular"
            and len(path) == 41
            and path[2] == "/"
        )
        if discovered_dirs:
            commits_needed = index
            break
    print(f"  commits needed for a new fan-out : {commits_needed}")
    print(f"  new fan-out directories          : {discovered_dirs}")
    print(f"  new loose files (sample)         : {discovered_files[:8]}")
    paired = bool(discovered_dirs) and all(
        any(path.startswith(directory + "/") for path in discovered_files)
        for directory in discovered_dirs
    )
    print(f"  DIRECTORY/OBJECT CONTROL FIRED   : {paired}")
    if not paired:
        raise SystemExit("CONTROL FAILURE: no new fan-out directory was measured")


print("\n### C. NONE==NONE IS BLIND TO A SAME-LENGTH SYMLINK TARGET CHANGE")
with tempfile.TemporaryDirectory(prefix="gate7-v10-link-") as temporary:
    root = Path(temporary)
    link = root / "object-shaped-entry"
    link.symlink_to("aa")
    baseline_tuple = symlink_tuple(link)
    baseline_target = os.readlink(link)

    link.unlink()
    link.symlink_to("longer")
    armed_tuple = symlink_tuple(link)
    arming_fired = armed_tuple != baseline_tuple
    print(f"  baseline tuple                   : {baseline_tuple}")
    print(f"  size-changing target tuple       : {armed_tuple}")
    print(f"  TUPLE DETECTOR ARMED             : {arming_fired}")
    if not arming_fired:
        raise SystemExit("CONTROL FAILURE: symlink tuple detector did not arm")

    link.unlink()
    link.symlink_to("bb")
    current_tuple = symlink_tuple(link)
    current_target = os.readlink(link)
    hidden = baseline_tuple == current_tuple and baseline_target != current_target
    print(f"  same-length current tuple        : {current_tuple}")
    print(f"  targets                          : {baseline_target!r} -> {current_target!r}")
    print(f"  NONE==NONE HIDES TARGET CHANGE   : {hidden}")
    if not hidden:
        raise SystemExit("CONTROL FAILURE: same-length symlink case did not reproduce")


print("\n### D. SHA-256 IS DECLARED IN RAW CONFIG AND USES A 62-HEX TAIL")
with tempfile.TemporaryDirectory(prefix="gate7-v10-sha256-") as temporary:
    root = Path(temporary)
    init_repo(root, object_format="sha256")
    oid = run(
        [GIT, "hash-object", "-w", "--stdin"],
        root,
        input_bytes=b"sha256 object\n",
    ).stdout.decode().strip()
    config_bytes = (root / ".git" / "config").read_bytes()
    config_has_format = b"objectformat = sha256" in config_bytes.lower()
    tail_length = len(oid[2:])
    print(f"  oid                              : {oid}")
    print(f"  loose tail length                : {tail_length}")
    print(f"  raw config declares sha256       : {config_has_format}")
    print(f"  SHA256 CONTROL FIRED             : {tail_length == 62 and config_has_format}")
    if tail_length != 62 or not config_has_format:
        raise SystemExit("CONTROL FAILURE: SHA-256 fixture did not declare its format")


print("\n" + "=" * 78)
print("ALL FOUR CONTROLS FIRED")
print("=" * 78)
