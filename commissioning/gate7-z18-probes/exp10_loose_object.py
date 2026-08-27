#!/usr/bin/env python3
"""EXP 10 — F7-1/F7-2: the loose-object PATH SHAPE as git actually writes it,
and whether a SIZE-PRESERVING byte alteration of a loose object is detectable
from NAME AND SIZE ALONE.

WHY THIS FILE EXISTS
--------------------
F7-2's rule treats `objects/pack/**` as administrative and the loose fan-out as
content-addressed, and it spells the loose path as
`objects/[0-9a-f]{2}/[0-9a-f]{38}`. F7-1's premise is that a capture recording
only NAMES AND SIZES cannot see a content change inside a loose object. Both are
measurable in a disposable repository, so neither is asserted here.

WHAT THIS EXPERIMENT COULD HAVE DETECTED
----------------------------------------
* that git writes loose objects at some other shape (e.g. flat, or 3/37)
* that `{38}` is not the right tail length for the repository's hash format
  -- a sha256 repository is measured side by side for exactly this reason
* that a size-preserving alteration DOES change the name or the size, i.e.
  that name+size IS a sufficient detector after all
* that the name+size detector is simply broken -- ARMED first with a
  size-CHANGING alteration, which it must catch before its silence on the
  size-preserving one means anything

THE ARMING CONTROL IS MANDATORY. If the size-changing alteration does not trip
the name+size detector, the silence on the size-preserving one proves nothing
and this probe exits nonzero.
"""
from __future__ import annotations
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zlib

GIT = shutil.which("git")
assert GIT and os.path.isabs(GIT)
GIT = os.path.realpath(GIT)

print("=== 0. MEASURED TOOLING ===")
print(f"  git      : {GIT}")
print(f"  {subprocess.run([GIT, '--version'], capture_output=True, text=True).stdout.strip()}")
print(f"  python   : {sys.version.split()[0]}")

ROOT = tempfile.mkdtemp(prefix="z18loose.")
ENV = dict(os.environ)
ENV["GIT_CONFIG_NOSYSTEM"] = "1"
ENV["GIT_CONFIG_GLOBAL"] = "/dev/null"
ENV["GIT_AUTHOR_NAME"] = ENV["GIT_COMMITTER_NAME"] = "Z18"
ENV["GIT_AUTHOR_EMAIL"] = ENV["GIT_COMMITTER_EMAIL"] = "z18@probe.invalid"

SPEC_RE = re.compile(r"^objects/[0-9a-f]{2}/[0-9a-f]{38}$")


def run(argv, cwd, stdin=None, echo=True):
    r = subprocess.run(argv, cwd=cwd, env=ENV, input=stdin, text=True,
                       capture_output=True)
    if echo:
        print(f"    $ {' '.join(argv)}   rc={r.returncode}")
        if r.returncode and r.stderr.strip():
            print(f"      stderr: {r.stderr.strip()}")
    return r


# ================================================================ PART 1: shape
print("\n=== 1. LOOSE-OBJECT PATH SHAPE, AS GIT WRITES IT ===")
SHAPES = {}
for fmt in ("sha1", "sha256"):
    repo = os.path.join(ROOT, f"repo-{fmt}")
    os.makedirs(repo)
    r = run([GIT, "init", "-q", "-b", "main", f"--object-format={fmt}", "."], repo)
    if r.returncode:
        print(f"    {fmt}: init FAILED -- NOT OBSERVED on this build")
        continue
    fmt_out = run([GIT, "rev-parse", "--show-object-format"], repo).stdout.strip()
    oid = run([GIT, "hash-object", "-w", "--stdin"], repo,
              stdin="z18 loose object payload\n").stdout.strip()
    obj = os.path.join(repo, ".git", "objects")
    found = []
    for dirpath, _dirs, files in os.walk(obj):
        for f in files:
            rel = os.path.relpath(os.path.join(dirpath, f), os.path.join(repo, ".git"))
            found.append(rel)
    found.sort()
    rel = found[0]
    d, base = rel.split("/")[1], rel.split("/")[2]
    print(f"\n  --- object-format = {fmt} (git reports: {fmt_out}) ---")
    print(f"    $ git hash-object -w --stdin   -> {oid}")
    print(f"    files under .git/objects       : {found}")
    print(f"    fan-out dir  = {d!r}   len={len(d)}")
    print(f"    object file  = {base!r}   len={len(base)}")
    print(f"    total hex    = {len(d) + len(base)}   (oid length = {len(oid)})")
    print(f"    dir  matches ^[0-9a-f]{{2}}$   : "
          f"{bool(re.fullmatch(r'[0-9a-f]{2}', d))}")
    print(f"    file matches ^[0-9a-f]{{38}}$  : "
          f"{bool(re.fullmatch(r'[0-9a-f]{38}', base))}")
    print(f"    full path matches the SPEC regex "
          f"'objects/[0-9a-f]{{2}}/[0-9a-f]{{38}}' : {bool(SPEC_RE.match(rel))}")
    print(f"    reassembled dir+file == oid    : {d + base == oid}")
    SHAPES[fmt] = {"rel": rel, "dir": len(d), "tail": len(base),
                   "spec_match": bool(SPEC_RE.match(rel)), "oid": oid,
                   "repo": repo}

print("\n  READ THIS AS: the SPEC regex is HASH-FORMAT SPECIFIC. `{38}` is the")
print("  sha1 tail. It is measured here against a sha256 repository too so that")
print("  the design states the constraint rather than inheriting it silently.")

# ============================================ PART 2: size-preserving alteration
print("\n=== 2. IS A SIZE-PRESERVING BYTE ALTERATION VISIBLE FROM NAME+SIZE? ===")
REPO = SHAPES["sha1"]["repo"]
GITDIR = os.path.join(REPO, ".git")
OBJ = os.path.join(GITDIR, "objects")
OID = SHAPES["sha1"]["oid"]
LOOSE = os.path.join(GITDIR, SHAPES["sha1"]["rel"])
FANOUT = os.path.dirname(LOOSE)


def capture_name_size(d):
    """EXACTLY the §5.8.2 capture shape for the loose fan-out: sorted names + size.
    Nothing else. This is the detector under test."""
    return sorted((n, os.path.getsize(os.path.join(d, n))) for n in os.listdir(d))


def capture_name_size_mtime(d):
    out = []
    for n in sorted(os.listdir(d)):
        st = os.stat(os.path.join(d, n))
        out.append((n, st.st_size, st.st_mtime_ns))
    return out


def sha256_of(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


ORIG_BYTES = open(LOOSE, "rb").read()
ORIG_ST = os.stat(LOOSE)
ORIG_CAP = capture_name_size(FANOUT)
ORIG_CAPM = capture_name_size_mtime(FANOUT)
ORIG_SHA = sha256_of(LOOSE)
ORIG_CAT = run([GIT, "cat-file", "-p", OID], REPO, echo=False)

print(f"  object       : {OID}")
print(f"  path         : .git/{SHAPES['sha1']['rel']}")
print(f"  file size    : {ORIG_ST.st_size} B      mode={oct(ORIG_ST.st_mode)[-4:]}")
print(f"  sha256(file) : {ORIG_SHA}")
print(f"  zlib inflate : {zlib.decompress(ORIG_BYTES)!r}")
print(f"  git cat-file -p -> rc={ORIG_CAT.returncode} {ORIG_CAT.stdout!r}")
print(f"  NAME+SIZE capture of the fan-out dir: {ORIG_CAP}")


def restore():
    os.chmod(LOOSE, 0o644)
    with open(LOOSE, "wb") as fh:
        fh.write(ORIG_BYTES)
    os.chmod(LOOSE, ORIG_ST.st_mode & 0o7777)
    os.utime(LOOSE, ns=(ORIG_ST.st_atime_ns, ORIG_ST.st_mtime_ns))


def write_bytes(b):
    os.chmod(LOOSE, 0o644)
    with open(LOOSE, "wb") as fh:
        fh.write(b)
    os.chmod(LOOSE, ORIG_ST.st_mode & 0o7777)


# ---------------------------------------------------------------- ARMING leg
print("\n  --- ARMING LEG: a SIZE-CHANGING alteration. The name+size detector")
print("      MUST catch this, or its silence below means nothing. ---")
write_bytes(ORIG_BYTES + b"\x00")
armed_cap = capture_name_size(FANOUT)
armed_fired = armed_cap != ORIG_CAP
print(f"    appended 1 byte -> size {ORIG_ST.st_size} -> {os.path.getsize(LOOSE)}")
print(f"    NAME+SIZE capture now: {armed_cap}")
print(f"    detector differs from golden: {armed_fired}   -> "
      f"{'ARMED (control FIRED)' if armed_fired else '*** CONTROL DID NOT FIRE ***'}")
rr = run([GIT, "cat-file", "-p", OID], REPO, echo=False)
print(f"    git cat-file -p -> rc={rr.returncode} stderr={rr.stderr.strip()!r}")
restore()
print(f"    restored; sha256 back to golden: {sha256_of(LOOSE) == ORIG_SHA}")

# ------------------------------------------------- SIZE-PRESERVING alteration
print("\n  --- THE LEG UNDER TEST: a SIZE-PRESERVING byte alteration ---")
# Flip one byte in the middle of the deflate stream. Length is unchanged by
# construction: one byte out, one byte in.
idx = len(ORIG_BYTES) // 2
mutated = bytearray(ORIG_BYTES)
mutated[idx] ^= 0xFF
mutated = bytes(mutated)
assert len(mutated) == len(ORIG_BYTES)
assert mutated != ORIG_BYTES
print(f"    byte offset {idx} of {len(ORIG_BYTES)}: "
      f"0x{ORIG_BYTES[idx]:02x} -> 0x{mutated[idx]:02x}   (XOR 0xFF, length unchanged)")
write_bytes(mutated)
# A worker can also restore mtime. Do it, so the demonstration is not carried
# by a timestamp the attacker controls.
os.utime(LOOSE, ns=(ORIG_ST.st_atime_ns, ORIG_ST.st_mtime_ns))

NEW_ST = os.stat(LOOSE)
NEW_CAP = capture_name_size(FANOUT)
NEW_CAPM = capture_name_size_mtime(FANOUT)
NEW_SHA = sha256_of(LOOSE)

print(f"\n    path unchanged            : {os.path.exists(LOOSE)}  "
      f"(.git/{SHAPES['sha1']['rel']})")
print(f"    size  {ORIG_ST.st_size} -> {NEW_ST.st_size}          identical: "
      f"{ORIG_ST.st_size == NEW_ST.st_size}")
print(f"    mode  {oct(ORIG_ST.st_mode)[-4:]} -> {oct(NEW_ST.st_mode)[-4:]}      identical: "
      f"{ORIG_ST.st_mode == NEW_ST.st_mode}")
print(f"    mtime_ns identical        : {ORIG_ST.st_mtime_ns == NEW_ST.st_mtime_ns}")
print(f"    sha256 {ORIG_SHA[:16]}... -> {NEW_SHA[:16]}...   identical: "
      f"{ORIG_SHA == NEW_SHA}")

name_size_blind = NEW_CAP == ORIG_CAP
name_size_mtime_blind = NEW_CAPM == ORIG_CAPM
content_fires = NEW_SHA != ORIG_SHA
print(f"\n    NAME+SIZE capture       : {NEW_CAP}")
print(f"    NAME+SIZE detector      : "
      f"{'SILENT — the alteration is INVISIBLE to it' if name_size_blind else 'FIRED'}")
print(f"    NAME+SIZE+MTIME detector: "
      f"{'SILENT' if name_size_mtime_blind else 'FIRED'}   "
      f"(mtime was restored by the same actor that made the edit)")
print(f"    SHA256-of-bytes detector: {'FIRED' if content_fires else 'SILENT'}")

print("\n    and git's own reaction (git detects it, because a loose object's")
print("    NAME IS ITS CONTENT HASH -- that is a different mechanism from the")
print("    capture, and it is exactly why the capture must not rely on size):")
rr = run([GIT, "cat-file", "-p", OID], REPO, echo=False)
print(f"      $ git cat-file -p {OID}")
print(f"        rc={rr.returncode} stdout={rr.stdout!r}")
print(f"        stderr={rr.stderr.strip()!r}")
rr = run([GIT, "fsck", "--no-progress"], REPO, echo=False)
print(f"      $ git fsck --no-progress")
print(f"        rc={rr.returncode}")
for line in (rr.stdout + rr.stderr).strip().splitlines():
    print(f"        {line}")
try:
    zlib.decompress(mutated)
    infl = "inflated WITHOUT error (content differs)"
except zlib.error as ex:
    infl = f"zlib.error: {ex}"
print(f"      python zlib on the mutated bytes: {infl}")

restore()
rr = run([GIT, "cat-file", "-p", OID], REPO, echo=False)
print(f"\n    restored: git cat-file -p rc={rr.returncode} out={rr.stdout!r}  "
      f"sha256 back to golden: {sha256_of(LOOSE) == ORIG_SHA}")

# --------------------------------------------------------------------- verdict
print("\n=== 3. VERDICT ===")
print(f"  loose path shape (sha1)   : .git/{SHAPES['sha1']['rel']}")
print(f"  matches objects/[0-9a-f]{{2}}/[0-9a-f]{{38}} : "
      f"{SHAPES['sha1']['spec_match']}")
if "sha256" in SHAPES:
    print(f"  loose path shape (sha256) : .git/{SHAPES['sha256']['rel']}  "
          f"tail len={SHAPES['sha256']['tail']}  "
          f"matches the {{38}} regex: {SHAPES['sha256']['spec_match']}")
else:
    print("  sha256 repository         : NOT OBSERVED (init failed on this build)")
print(f"  ARMING control (size-changing edit caught by name+size) : "
      f"{'FIRED' if armed_fired else '*** DID NOT FIRE ***'}")
print(f"  size-preserving edit, name+size detector                : "
      f"{'SILENT (F7-1 premise HOLDS)' if name_size_blind else 'FIRED (F7-1 premise FALSE)'}")
print(f"  size-preserving edit, sha256 detector                   : "
      f"{'FIRED' if content_fires else 'SILENT'}")

shutil.rmtree(ROOT, ignore_errors=True)

if not armed_fired:
    print("\n*** CONTROL FAILURE: the name+size detector never fired even on a "
          "size-CHANGING edit. Its silence proves nothing. DO NOT CITE. ***")
    sys.exit(2)
if not content_fires:
    print("\n*** CONTROL FAILURE: the content detector did not fire. ***")
    sys.exit(2)
if not name_size_blind:
    print("\n*** F7-1's PREMISE IS FALSE ON THIS HOST: the name+size capture DID "
          "see a size-preserving alteration. Report as a finding. ***")
    sys.exit(3)
print("\nDEMONSTRATED: a size-preserving byte alteration of a loose object is "
      "INVISIBLE to a name+size capture and visible to a content hash.")
