#!/usr/bin/env python3
"""EXP 9 — F7-2: WHERE does git 2.43 actually put the multi-pack-index, and
what else actually appears under `objects/pack/`?

WHY THIS FILE EXISTS
--------------------
The specification places the multi-pack-index under `objects/info/`. That is
where the SPLIT COMMIT-GRAPH lives (`objects/info/commit-graphs/`), and the
single-file commit-graph (`objects/info/commit-graph`), so the mistake is easy
to make and easy to keep. This probe does not argue about it: it builds a
disposable repository under `mktemp -d`, runs `git multi-pack-index write`, and
reports the path git actually created.

F7-2's rule turns on `objects/pack/**` being ADMINISTRATIVE rather than
content-addressed, so every file type that shows up there in practice is
enumerated here together with THE COMMAND THAT PRODUCED IT. A file type that
could not be produced on this host is reported as NOT OBSERVED with the command
that was attempted and its exit status -- never as an assumption.

WHAT THIS EXPERIMENT COULD HAVE DETECTED
----------------------------------------
* that `multi-pack-index` really is at `objects/info/multi-pack-index`
  (the specification's claim) -- BOTH candidate paths are probed every time
* that the MIDX is at neither path, i.e. that the write silently no-ops
* that a given pack-directory file type does not exist on git 2.43

CONTROL: `_exists()` is armed by probing a path that must NOT exist. If that
probe ever returns True the detector is broken and the run aborts.
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import sys
import tempfile

GIT = shutil.which("git")
assert GIT and os.path.isabs(GIT)
GIT = os.path.realpath(GIT)

print("=== 0. MEASURED TOOLING ===")
print(f"  git      : {GIT}")
print(f"  {subprocess.run([GIT, '--version'], capture_output=True, text=True).stdout.strip()}")
print(f"  python   : {sys.version.split()[0]}")
print(f"  platform : {' '.join(os.uname())}")

ROOT = tempfile.mkdtemp(prefix="z18pack.")
REPO = os.path.join(ROOT, "repo")
os.mkdir(REPO)
ENV = dict(os.environ)
ENV["GIT_CONFIG_NOSYSTEM"] = "1"
ENV["GIT_CONFIG_GLOBAL"] = "/dev/null"
ENV["GIT_AUTHOR_NAME"] = ENV["GIT_COMMITTER_NAME"] = "Z18"
ENV["GIT_AUTHOR_EMAIL"] = ENV["GIT_COMMITTER_EMAIL"] = "z18@probe.invalid"

print(f"\n  disposable repository (mktemp -d): {REPO}")


def run(argv, cwd=REPO, stdin=None, check=True, binary=False):
    """Every command in this probe goes through here so the transcript is exact."""
    kw = dict(cwd=cwd, env=ENV, capture_output=True)
    if binary:
        r = subprocess.run(argv, input=stdin, **kw)
    else:
        r = subprocess.run(argv, input=stdin, text=True, **kw)
    shown = " ".join(argv[1:]) if argv and argv[0] == GIT else " ".join(map(str, argv))
    print(f"    $ git {shown}" if argv[0] == GIT else f"    $ {shown}")
    print(f"      rc={r.returncode}")
    if check and r.returncode != 0:
        err = r.stderr if not binary else r.stderr.decode("utf-8", "replace")
        print(f"      stderr: {err.strip()}")
    return r


GITDIR = os.path.join(REPO, ".git")
OBJ = os.path.join(GITDIR, "objects")
PACKDIR = os.path.join(OBJ, "pack")
INFODIR = os.path.join(OBJ, "info")

_CONTROL_ARMED = False


def _exists(rel):
    global _CONTROL_ARMED
    if not _CONTROL_ARMED:
        bogus = os.path.join(OBJ, "pack", "Z18-THIS-MUST-NOT-EXIST")
        if os.path.exists(bogus):
            print("*** DETECTOR CONTROL FAILED: bogus path reported present ***")
            sys.exit(2)
        _CONTROL_ARMED = True
    return os.path.exists(os.path.join(OBJ, rel))


# CUMULATIVE, not final-state. A later `git repack` DELETES files an earlier
# command created (the cruft repack removes the pack bitmap), so a roll-up taken
# only from the final listing UNDER-REPORTS what git actually produces. This
# probe's first draft did exactly that and reported `*.bitmap NOT OBSERVED`
# while step 5's own listing showed one. Recorded here so the trap is visible.
OBSERVED: dict[str, str] = {}


def classify(name):
    if name == "multi-pack-index":
        return "multi-pack-index"
    if name.startswith("multi-pack-index-") and name.endswith(".bitmap"):
        return "multi-pack-index-*.bitmap"
    if "." in name:
        return "*." + name.rsplit(".", 1)[1]
    return name


def listing(d, label, note=None):
    print(f"    {label}:")
    if not os.path.isdir(d):
        print("      (directory does not exist)")
        return []
    names = sorted(os.listdir(d))
    if not names:
        print("      (empty)")
    for n in names:
        p = os.path.join(d, n)
        st = os.stat(p)
        print(f"      {oct(st.st_mode)[-4:]}  {st.st_size:9d}  {n}")
        if note:
            OBSERVED.setdefault(classify(n), note)
    return names


# ------------------------------------------------------------------ content
print("\n=== 1. BUILD CONTENT (loose objects first) ===")
run([GIT, "init", "-q", "-b", "main", "."])
for i in range(4):
    with open(os.path.join(REPO, f"f{i}.txt"), "w") as fh:
        fh.write(f"content-{i}\n" * (20 * (i + 1)))
    run([GIT, "add", "-A"])
    run([GIT, "commit", "-q", "-m", f"c{i}"])

print("\n  objects/ BEFORE any repack (loose fan-out is what exists):")
loose = sorted(n for n in os.listdir(OBJ) if re.fullmatch(r"[0-9a-f]{2}", n))
print(f"    loose fan-out directories: {loose}")
listing(PACKDIR, "objects/pack/")
listing(INFODIR, "objects/info/")

# ------------------------------------------------------------------ .pack/.idx
print("\n=== 2. *.pack and *.idx ===")
print("  COMMAND: git repack -a -d")
run([GIT, "repack", "-a", "-d"])
names = listing(PACKDIR, "objects/pack/", note="git repack -a -d")
listing(INFODIR, "objects/info/  (attribution: was empty before the repack)")
print(f"    -> *.pack present: {any(n.endswith('.pack') for n in names)}")
print(f"    -> *.idx  present: {any(n.endswith('.idx') for n in names)}")
print(f"    -> *.rev  present after a plain repack: "
      f"{any(n.endswith('.rev') for n in names)}")

# ------------------------------------------------------------------ THE ROW
print("\n=== 3. THE F7-2 ROW — multi-pack-index LOCATION ===")
print("  COMMAND: git multi-pack-index write")
r = run([GIT, "multi-pack-index", "write"])
cand_info = "info/multi-pack-index"
cand_pack = "pack/multi-pack-index"
at_info = _exists(cand_info)
at_pack = _exists(cand_pack)
print(f"    objects/{cand_info:26s} exists = {at_info}   <- the SPECIFICATION's claim")
print(f"    objects/{cand_pack:26s} exists = {at_pack}   <- MEASURED")
listing(INFODIR, "objects/info/  (after multi-pack-index write)")
listing(PACKDIR, "objects/pack/  (after multi-pack-index write)",
        note="git multi-pack-index write")
if at_pack:
    st = os.stat(os.path.join(OBJ, cand_pack))
    print(f"    MEASURED LOCATION: objects/pack/multi-pack-index  "
          f"mode={oct(st.st_mode)[-4:]} size={st.st_size} B")
print("  CROSS-CHECK, git's own answer (git rev-parse --git-path):")
rr = run([GIT, "rev-parse", "--git-path", "objects/pack/multi-pack-index"])
print(f"      {rr.stdout.strip()}")
print("  CROSS-CHECK, the file's own magic header:")
with open(os.path.join(OBJ, cand_pack), "rb") as fh:
    magic = fh.read(12)
print(f"      first 12 bytes = {magic!r}   (MIDX signature is b'MIDX')")
print("  CROSS-CHECK, git reads it back:")
rr = run([GIT, "multi-pack-index", "verify"])
print(f"      verify rc={rr.returncode} out={rr.stdout.strip()!r}")

MIDX_VERDICT = ("objects/pack/multi-pack-index" if at_pack and not at_info else
                "objects/info/multi-pack-index" if at_info and not at_pack else
                "AMBIGUOUS / NEITHER")

# --------------------------------------------------------- midx bitmap + .rev
print("\n=== 4. multi-pack-index-<hash>.bitmap and *.rev ===")
print("  COMMAND: git multi-pack-index write --bitmap")
run([GIT, "multi-pack-index", "write", "--bitmap"], check=False)
names = listing(PACKDIR, "objects/pack/", note="git multi-pack-index write --bitmap")
midx_bitmaps = [n for n in names if n.startswith("multi-pack-index-") and n.endswith(".bitmap")]
print(f"    -> multi-pack-index-*.bitmap : {midx_bitmaps or 'NOT OBSERVED'}")
print(f"    -> *.rev                     : "
      f"{[n for n in names if n.endswith('.rev')] or 'NOT OBSERVED'}")

print("\n  COMMAND: git -c pack.writeReverseIndex=true repack -a -d")
run([GIT, "-c", "pack.writeReverseIndex=true", "repack", "-a", "-d"])
names = listing(PACKDIR, "objects/pack/",
                note="git -c pack.writeReverseIndex=true repack -a -d")
print(f"    -> *.rev : {[n for n in names if n.endswith('.rev')] or 'NOT OBSERVED'}")

# ------------------------------------------------------------------ .bitmap
print("\n=== 5. *.bitmap (pack bitmap) ===")
print("  COMMAND: git repack -a -d -b")
run([GIT, "repack", "-a", "-d", "-b"], check=False)
names = listing(PACKDIR, "objects/pack/", note="git repack -a -d -b")
pack_bitmaps = [n for n in names if n.endswith(".bitmap") and not n.startswith("multi-pack-index")]
print(f"    -> pack-*.bitmap : {pack_bitmaps or 'NOT OBSERVED'}")

# ------------------------------------------------------------------ .mtimes
print("\n=== 6. *.mtimes (cruft pack) ===")
print("  set-up: create an UNREACHABLE object so a cruft pack has something to hold")
rr = run([GIT, "hash-object", "-w", "--stdin"], stdin="z18-unreachable-blob\n")
print(f"      unreachable blob = {rr.stdout.strip()}")
tree = run([GIT, "rev-parse", "HEAD^{tree}"]).stdout.strip()
rr = run([GIT, "commit-tree", "-m", "z18-orphan", tree])
print(f"      unreachable commit = {rr.stdout.strip()}")
print("  COMMAND: git repack --cruft --cruft-expiration=never -a -d")
run([GIT, "repack", "--cruft", "--cruft-expiration=never", "-a", "-d"], check=False)
names = listing(PACKDIR, "objects/pack/",
                note="git repack --cruft --cruft-expiration=never -a -d")
mtimes = [n for n in names if n.endswith(".mtimes")]
print(f"    -> *.mtimes : {mtimes or 'NOT OBSERVED'}")

# ------------------------------------------------------------------ .keep
print("\n=== 7. *.keep ===")
print("  COMMAND (produce a pack on stdout): "
      "git pack-objects --revs --stdout  <<< HEAD")
rr = subprocess.run([GIT, "pack-objects", "--revs", "--stdout"], cwd=REPO, env=ENV,
                    input=b"HEAD\n", capture_output=True)
print(f"    $ git pack-objects --revs --stdout   rc={rr.returncode} "
      f"({len(rr.stdout)} pack bytes)")
print("  COMMAND (index it INTO objects/pack with a keep marker): "
      "git index-pack --stdin --keep=<reason> --fix-thin")
rr2 = subprocess.run([GIT, "index-pack", "--stdin", "--keep=z18 probe keep reason",
                      "--fix-thin"], cwd=REPO, env=ENV, input=rr.stdout,
                     capture_output=True)
print(f"    $ git index-pack --stdin --keep='z18 probe keep reason' --fix-thin  "
      f"rc={rr2.returncode}")
if rr2.returncode:
    print(f"      stderr: {rr2.stderr.decode('utf-8', 'replace').strip()}")
names = listing(PACKDIR, "objects/pack/",
                note="git index-pack --stdin --keep=<reason> --fix-thin")
keeps = [n for n in names if n.endswith(".keep")]
print(f"    -> *.keep : {keeps or 'NOT OBSERVED'}")
for k in keeps:
    print(f"       contents of {k}: {open(os.path.join(PACKDIR, k)).read()!r}")

# ------------------------------------------------------------------ .promisor
print("\n=== 8. *.promisor (partial clone) ===")
SRC = REPO
DST = os.path.join(ROOT, "partial")
print("  COMMAND: git -C <src> config uploadpack.allowFilter true")
run([GIT, "config", "uploadpack.allowFilter", "true"])
print("  COMMAND: git clone --no-local --filter=blob:none "
      "file://<src> <dst>")
rr = subprocess.run([GIT, "clone", "--no-local", "--filter=blob:none",
                     "file://" + SRC, DST], cwd=ROOT, env=ENV,
                    capture_output=True, text=True)
print(f"    $ git clone --no-local --filter=blob:none file://{SRC} {DST}   "
      f"rc={rr.returncode}")
if rr.returncode:
    print(f"      stderr: {rr.stderr.strip()}")
DST_PACK = os.path.join(DST, ".git", "objects", "pack")
promisors = []
if os.path.isdir(DST_PACK):
    dnames = listing(DST_PACK, "<partial clone>/.git/objects/pack/",
                     note="git clone --no-local --filter=blob:none file://<src> <dst>")
    promisors = [n for n in dnames if n.endswith(".promisor")]
print(f"    -> *.promisor : {promisors or 'NOT OBSERVED'}")
if promisors:
    p = os.path.join(DST_PACK, promisors[0])
    print(f"       size of {promisors[0]} = {os.path.getsize(p)} B "
          f"(promisor markers are typically empty)")
    print("       the partial clone's ENTIRE local config "
          "(git config --list --local), so that promisor/partialClone keys are")
    print("       read off a transcript rather than asserted:")
    rr = subprocess.run([GIT, "config", "--list", "--local"], cwd=DST, env=ENV,
                        capture_output=True, text=True)
    print(f"       $ git config --list --local   rc={rr.returncode}")
    for line in rr.stdout.strip().splitlines():
        print(f"         {line}")
    # INCIDENTAL BUT LOAD-BEARING: the design elsewhere names
    # `extensions.partialClone` as a partial-clone signal. On this host it is
    # NOT written by a `--filter` clone over file://; the signals that ARE
    # written are core.repositoryformatversion=1, remote.<name>.promisor and
    # remote.<name>.partialclonefilter, plus objects/pack/*.promisor.
    for key in ("extensions.partialClone", "remote.origin.promisor",
                "remote.origin.partialclonefilter",
                "core.repositoryformatversion"):
        rr = subprocess.run([GIT, "config", "--get", key], cwd=DST, env=ENV,
                            capture_output=True, text=True)
        print(f"       $ git config --get {key:34s} rc={rr.returncode} "
              f"out={rr.stdout.strip()!r}"
              f"{'   <- NOT SET' if rr.returncode else ''}")

# ------------------------------------------------------------------ inventory
print("\n=== 9. FINAL INVENTORY ===")
print("  COMMAND: find <gitdir>/objects -type f | sort   (primary repo)")
rr = subprocess.run(["find", OBJ, "-type", "f"], capture_output=True, text=True)
for line in sorted(rr.stdout.strip().splitlines()):
    print(f"      {os.path.relpath(line, GITDIR)}   ({os.path.getsize(line)} B)")
print("\n  objects/info/ final listing (primary repo):")
listing(INFODIR, "objects/info/")

WANTED = ["*.pack", "*.idx", "*.promisor", "*.keep", "*.bitmap", "*.rev",
          "*.mtimes", "multi-pack-index", "multi-pack-index-*.bitmap"]
print("\n  F7-2 ROLL-UP — CUMULATIVE across every step of this probe, with the")
print("  command that FIRST produced each class. This is deliberately NOT the")
print("  final-state listing: `git repack --cruft -a -d` deletes the pack")
print("  bitmap an earlier `git repack -a -d -b` created, so a final-state")
print("  roll-up reports `*.bitmap NOT OBSERVED` and is WRONG.")
missing = []
for w in WANTED:
    cmd = OBSERVED.get(w)
    if cmd:
        print(f"      {w:28s} MEASURED — OBSERVED   <- {cmd}")
    else:
        missing.append(w)
        print(f"      {w:28s} NOT OBSERVED")
print(f"\n  classes seen but not on the F7-2 wanted list: "
      f"{sorted(set(OBSERVED) - set(WANTED)) or '(none)'}")

print("\n=== 10. VERDICT ===")
print(f"  multi-pack-index MEASURED LOCATION : {MIDX_VERDICT}")
print(f"  present at objects/info/           : {at_info}")
print(f"  present at objects/pack/           : {at_pack}")
print(f"  objects/info/ final listing        : "
      f"{sorted(os.listdir(INFODIR)) if os.path.isdir(INFODIR) else '(absent)'}")
print(f"  repo (left for inspection during the run): {REPO}")

shutil.rmtree(ROOT, ignore_errors=True)

if MIDX_VERDICT == "AMBIGUOUS / NEITHER":
    print("\n*** THE LOCATION MEASUREMENT DID NOT RESOLVE — do not cite. ***")
    sys.exit(2)
