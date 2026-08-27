#!/usr/bin/env python3
"""GATE 7 LANE V — revision 9 probe.

Measures the facts F7-1 and F7-2 require, each with a positive control that
must FIRE or the row is reported as dead rather than as a pass.

  A. Where does git 2.43 place the multi-pack-index?          (F7-2)
  B. Which sidecars appear in objects/pack/, and what shape?  (F7-2)
  C. Can a size-preserving byte alteration of a loose object
     evade a name+size capture, and does sha256 catch it?     (F7-1)
  D. What is the literal loose-object path shape?             (F7-2)
  E. Does ordinary maintenance REMOVE baseline loose objects?  (cost of clause 1)

READ-ONLY with respect to every repository on this host: every fixture is
created fresh under mktemp. No production path is opened.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

GIT = shutil.which("git") or "/usr/bin/git"


def run(args, cwd, check=True):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"FIXTURE FAILED: {args}\n{p.stdout}\n{p.stderr}")
    return p


def newrepo(tag):
    d = tempfile.mkdtemp(prefix=f"v9-{tag}-")
    run([GIT, "init", "-q", "--initial-branch=main", "."], d)
    run([GIT, "config", "user.email", "probe@example.invalid"], d)
    run([GIT, "config", "user.name", "probe"], d)
    return d


def commits(d, n, size=64):
    for i in range(n):
        with open(os.path.join(d, f"f{i}.txt"), "w") as fh:
            fh.write(("%d-" % i) * size)
        run([GIT, "add", "-A"], d)
        run([GIT, "commit", "-q", "-m", f"c{i}"], d)


def tree(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for f in sorted(filenames):
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, root)
            st = os.lstat(p)
            out.append((rel, st.st_size, oct(st.st_mode)))
    return out


def loose(objdir):
    r = []
    for dirpath, dirnames, filenames in os.walk(objdir):
        dirnames.sort()
        for f in sorted(filenames):
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, objdir).replace(os.sep, "/")
            if rel.startswith(("pack/", "info/")):
                continue
            r.append(rel)
    return sorted(r)


def sha256(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


print("=" * 78)
v = run([GIT, "--version"], "/").stdout.strip()
print(f"git binary  : {GIT}")
print(f"git version : {v}")
print(f"python      : {sys.version.split()[0]}")
print(f"uid         : {os.getuid()}")
print("=" * 78)

# ---------------------------------------------------------------- A
print("\n### A. WHERE DOES GIT PLACE THE MULTI-PACK-INDEX?")
print("    The design (revision 8) says objects/info/multi-pack-index.")
print("    Positive control: the file must EXIST somewhere after the write,")
print("    or the experiment measured nothing and is reported DEAD.\n")
for label, cmd in (
    ("git multi-pack-index write", [GIT, "multi-pack-index", "write"]),
    ("git repack -a -d --write-midx", [GIT, "repack", "-a", "-d", "--write-midx"]),
):
    d = newrepo("midx")
    commits(d, 3)
    run([GIT, "repack", "-a", "-d", "-q"], d)
    before = {r for r, _, _ in tree(os.path.join(d, ".git", "objects"))}
    p = run(cmd, d, check=False)
    after = tree(os.path.join(d, ".git", "objects"))
    names = {r for r, _, _ in after}
    new = sorted(names - before)
    hits = [r for r in names if "multi-pack-index" in r]
    print(f"  {label}")
    print(f"    rc={p.returncode}")
    print(f"    new entries under objects/ : {new}")
    print(f"    multi-pack-index found at  : {hits or 'NOWHERE'}")
    print(f"    CONTROL FIRED (file exists): {bool(hits)}")
    for r in hits:
        print(f"      under objects/info/ ? {r.startswith('info/')}")
        print(f"      under objects/pack/ ? {r.startswith('pack/')}")
    shutil.rmtree(d, ignore_errors=True)

# ---------------------------------------------------------------- B
print("\n### B. WHAT ELSE LIVES IN objects/pack/ ?")
print("    Each sidecar is created by a real git command or a real file write.")
print("    Positive control: the entry must APPEAR, or the row is DEAD.\n")
d = newrepo("side")
commits(d, 4)
run([GIT, "repack", "-a", "-d", "-q", "--write-bitmap-index"], d)
packdir = os.path.join(d, ".git", "objects", "pack")
base = None
for f in sorted(os.listdir(packdir)):
    if f.endswith(".pack"):
        base = f[:-5]
print(f"  after repack --write-bitmap-index : {sorted(os.listdir(packdir))}")
run([GIT, "multi-pack-index", "write"], d, check=False)
print(f"  after multi-pack-index write      : {sorted(os.listdir(packdir))}")
# .keep and .promisor are plain file writes -- this is exactly how a worker
# would create one, and it is why they are NOT content-addressed.
for ext in (".keep", ".promisor", ".mtimes"):
    with open(os.path.join(packdir, base + ext), "w") as fh:
        fh.write("planted by a plain file write, no git process\n")
final = sorted(os.listdir(packdir))
print(f"  after PLAIN FILE WRITES           : {final}")
print(f"  CONTROL FIRED (sidecars present)  : "
      f"{all(any(x.endswith(e) for x in final) for e in ('.keep', '.promisor', '.mtimes'))}")
print("  classification of every entry seen:")
LOOSE_RE = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{38}$")
for f in final:
    print(f"    pack/{f:<52} matches loose-object shape? {bool(LOOSE_RE.match('pack/'+f))}")
shutil.rmtree(d, ignore_errors=True)

# ---------------------------------------------------------------- C
print("\n### C. SIZE-PRESERVING ALTERATION OF A BASELINE LOOSE OBJECT")
print("    This is F7-1. A name+size capture must MISS it; sha256 must CATCH it.\n")
d = newrepo("alter")
commits(d, 2)
objdir = os.path.join(d, ".git", "objects")
names = loose(objdir)
target = os.path.join(objdir, names[0])
st_before = os.lstat(target)
digest_before = sha256(target)
with open(target, "rb") as fh:
    raw = bytearray(fh.read())
# flip exactly one bit in the last byte -- length is unchanged by construction
raw[-1] ^= 0x01
os.chmod(target, 0o644)
with open(target, "wb") as fh:
    fh.write(bytes(raw))
os.chmod(target, st_before.st_mode & 0o777)
st_after = os.lstat(target)
digest_after = sha256(target)
print(f"  object                      : {names[0]}")
print(f"  size before / after         : {st_before.st_size} / {st_after.st_size}")
print(f"  SIZE IS UNCHANGED           : {st_before.st_size == st_after.st_size}")
print(f"  sha256 before               : {digest_before}")
print(f"  sha256 after                : {digest_after}")
print(f"  DIGEST CHANGED              : {digest_before != digest_after}")
print(f"  name set unchanged          : {loose(objdir) == names}")
print("  => a capture of (sorted names + per-file size) is BYTE-FOR-BYTE")
print("     IDENTICAL before and after. It CANNOT detect this mutation.")
oid = names[0].replace("/", "")
p = run([GIT, "cat-file", "-p", oid], d, check=False)
print(f"  git cat-file -p <oid>       : rc={p.returncode}  {p.stderr.strip()[:70]}")
print(f"  CONTROL FIRED (git agrees the object is now broken): {p.returncode != 0}")
shutil.rmtree(d, ignore_errors=True)

# ---------------------------------------------------------------- D
print("\n### D. THE LITERAL LOOSE-OBJECT PATH SHAPE")
d = newrepo("shape")
commits(d, 3)
objdir = os.path.join(d, ".git", "objects")
names = loose(objdir)
print(f"  loose object count          : {len(names)}")
allm = all(LOOSE_RE.match(n) for n in names)
print(f"  ALL match ^[0-9a-f]{{2}}/[0-9a-f]{{38}}$ : {allm}")
print(f"  sample                      : {names[:3]}")
fmt = run([GIT, "rev-parse", "--show-object-format"], d).stdout.strip()
print(f"  object format on this host  : {fmt}  (sha1 => 38 hex tail)")
print("  NOTE: a sha256 repository would give a 62-hex tail. The regex below is")
print("        therefore FAIL-CLOSED for sha256 repositories, which is stated")
print("        in the design rather than silently widened.")
# negative controls for the regex
for bad in ("ab/NOTHEX0000000000000000000000000000000000",
            "abc/0000000000000000000000000000000000000",
            "ab/0123456789abcdef0123456789abcdef012345678"):
    print(f"  regex rejects {bad!r:>48} : {not bool(LOOSE_RE.match(bad))}")
shutil.rmtree(d, ignore_errors=True)

# ---------------------------------------------------------------- E
print("\n### E. DOES ORDINARY MAINTENANCE REMOVE BASELINE LOOSE OBJECTS?")
print("    This prices clause 1: 'removal is divergence'.\n")
d = newrepo("gc")
commits(d, 3)
objdir = os.path.join(d, ".git", "objects")
before = loose(objdir)
run([GIT, "repack", "-a", "-d", "-q"], d)
after = loose(objdir)
print(f"  loose before repack -a -d   : {len(before)}")
print(f"  loose after  repack -a -d   : {len(after)}")
print(f"  REMOVED                     : {len(set(before) - set(after))}")
print(f"  CONTROL FIRED (repack really removed loose objects): "
      f"{len(set(before) - set(after)) > 0}")
print("  => `git gc` / `git repack -d` in the PRIMARY repository is a")
print("     DIVERGENCE under clause 1. That is a real operational cost and")
print("     the design must state it, not discover it in production.")
shutil.rmtree(d, ignore_errors=True)

print("\n" + "=" * 78)
print("END OF PROBE")
print("=" * 78)
