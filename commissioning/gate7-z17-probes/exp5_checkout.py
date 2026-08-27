#!/usr/bin/env python3
"""EXP 5 — which worker actions move <gitdir>/HEAD off the literal SHA in a
DETACHED task worktree (B2/ZI-77's invariant), and what a deny pattern costs.

Two questions, kept separate:
  (1) DETECTION  — does the action make raw <gitdir>/HEAD stop being 40hex+LF?
                   (that is exactly what ZI-77 comparison 8 tests)
  (2) COLLATERAL — would `Bash(git checkout:*)` / `Bash(git switch:*)` also deny
                   a LEGITIMATE worker action? Every denied-but-legitimate row is
                   a cost that must be reported, not hidden.
Each action runs in a FRESH worktree so rows cannot contaminate each other.
"""
import os, sys, re, subprocess, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rows import GIT

SHA = re.compile(rb"^[0-9a-f]{40}\n$")

def newrepo():
    root = tempfile.mkdtemp(prefix="z17co.")
    e = dict(os.environ); e["GIT_CONFIG_NOSYSTEM"]="1"
    def g(*a, cwd=root, ok=True):
        r = subprocess.run([GIT,*a],cwd=cwd,env=e,capture_output=True,text=True)
        if ok and r.returncode: raise RuntimeError(f"{a}: {r.stderr}")
        return r
    g("init","-q","-b","main",".")
    g("config","user.email","z@z"); g("config","user.name","z")
    open(f"{root}/f.txt","w").write("one\n")
    g("add","-A"); g("commit","-q","-m","c1")
    open(f"{root}/f.txt","a").write("two\n")
    g("add","-A"); g("commit","-q","-m","c2")
    base = g("rev-parse","HEAD").stdout.strip()
    prev = g("rev-parse","HEAD~1").stdout.strip()
    g("branch","other",prev)
    return root, base, prev, e, g

def trial(action, mutate=None):
    root, base, prev, e, g = newrepo()
    ext = tempfile.mkdtemp(prefix="z17wt.")
    wt = f"{ext}/task-wt"
    g("worktree","add","--quiet","--detach",wt,base)
    gitdir = subprocess.run([GIT,"rev-parse","--absolute-git-dir"],cwd=wt,env=e,
                            capture_output=True,text=True).stdout.strip()
    headp = os.path.join(gitdir,"HEAD")
    sealed = open(headp,"rb").read()
    assert SHA.match(sealed), f"seal precondition broken: {sealed!r}"
    if mutate: mutate(wt)
    argv = [x.replace("<BASE>",base).replace("<PREV>",prev) for x in action]
    r = subprocess.run([GIT,*argv],cwd=wt,env=e,capture_output=True,text=True)
    after = open(headp,"rb").read()
    resolved = subprocess.run([GIT,"rev-parse","HEAD"],cwd=wt,env=e,
                              capture_output=True,text=True).stdout.strip()
    out = {
        "rc": r.returncode,
        "head_is_literal_sha": bool(SHA.match(after)),
        "head_changed": after != sealed,
        "head_after": after.decode(errors="replace").strip()[:44],
        "base_moved": resolved != base,
        "zi77_verdict": "base_held" if after == sealed else "base_MISMATCH",
        "err": r.stderr.strip().splitlines()[0][:56] if r.stderr.strip() else "",
    }
    shutil.rmtree(root, ignore_errors=True); shutil.rmtree(ext, ignore_errors=True)
    return out

def dirty(wt):
    open(os.path.join(wt,"f.txt"),"a").write("worker edit\n")

ACTIONS = [
 # (label, argv, mutate, would `Bash(git checkout:*)`+`Bash(git switch:*)` deny it?, legitimate?)
 ("git checkout -b feature",          ["checkout","-b","feature"],        None, True,  True),
 ("git checkout -B feature",          ["checkout","-B","feature"],        None, True,  True),
 ("git switch -c feature",            ["switch","-c","feature"],          None, True,  True),
 ("git switch -C feature",            ["switch","-C","feature"],          None, True,  True),
 ("git checkout --orphan orph",       ["checkout","--orphan","orph"],     None, True,  True),
 ("git checkout other (branch)",      ["checkout","other"],               None, True,  True),
 ("git switch other",                 ["switch","other"],                 None, True,  True),
 ("git switch --detach <PREV>",       ["switch","--detach","<PREV>"],     None, True,  True),
 ("git checkout --detach <PREV>",     ["checkout","--detach","<PREV>"],   None, True,  True),
 ("git checkout <PREV>",              ["checkout","<PREV>"],              None, True,  True),
 ("git checkout -b f <PREV>",         ["checkout","-b","f2","<PREV>"],    None, True,  True),
 # --- actions a task worker legitimately performs -----------------------------
 ("git checkout -- f.txt  (restore)", ["checkout","--","f.txt"],          dirty, True, True),
 ("git checkout <BASE> -- f.txt",     ["checkout","<BASE>","--","f.txt"], dirty, True, True),
 ("git checkout . ",                  ["checkout","."],                   dirty, True, True),
 ("git restore f.txt  (modern form)", ["restore","f.txt"],                dirty, False, True),
 ("git restore --source <BASE> f.txt",["restore","--source","<BASE>","f.txt"], dirty, False, True),
 # --- non-checkout ways to move HEAD ------------------------------------------
 ("git branch feature (no HEAD move)",["branch","feature2"],              None, False, True),
 ("git symbolic-ref HEAD refs/heads/main", ["symbolic-ref","HEAD","refs/heads/main"], None, False, False),
 ("git update-ref --no-deref HEAD <PREV>", ["update-ref","--no-deref","HEAD","<PREV>"], None, False, False),
 ("git stash (dirty tree)",           ["stash"],                          dirty, False, True),
 ("git cherry-pick <PREV>",           ["cherry-pick","<PREV>"],           None, False, True),
 ("git revert --no-edit <BASE>",      ["revert","--no-edit","<BASE>"],    None, False, True),
 ("git am (empty stdin)",             ["am"],                             None, False, True),
 ("git notes add -m x",               ["notes","add","-m","x"],           None, False, True),
 ("git tag t1",                       ["tag","t1"],                       None, False, True),
]

print(f"{'action':38s} {'rc':>3s} {'HEAD literal':>12s} {'HEAD moved':>10s} "
      f"{'base moved':>10s} {'ZI-77':>13s}")
print("-"*96)
rows = []
for label, argv, mut, denied, legit in ACTIONS:
    o = trial(argv, mut)
    rows.append((label, o, denied, legit))
    print(f"{label:38s} {o['rc']:3d} {str(o['head_is_literal_sha']):>12s} "
          f"{str(o['head_changed']):>10s} {str(o['base_moved']):>10s} {o['zi77_verdict']:>13s}"
          f"{'' if not o['err'] else '  '+o['err'][:30]}")

print("\n=== (1) DETECTION — actions that break the detached-HEAD literal-SHA invariant ===")
brk = [(l,o) for l,o,d,g in rows if not o["head_is_literal_sha"]]
for l,o in brk:
    print(f"  {l:40s} HEAD -> {o['head_after']!r}   base_actually_moved={o['base_moved']}")
print(f"  count: {len(brk)}")

print("\n=== (2) FALSE POSITIVES — HEAD off the SHA but the BASE never moved ===")
fp = [(l,o) for l,o,d,g in rows if not o["head_is_literal_sha"] and not o["base_moved"]]
for l,o in fp: print(f"  {l:40s} ZI-77 says {o['zi77_verdict']}, base is UNCHANGED")
print(f"  count: {len(fp)}   <-- each is a FAILED run with zero evidence collected")

print("\n=== (3) COLLATERAL — legitimate actions a checkout/switch deny would BLOCK ===")
col = [l for l,o,d,g in rows if d and g]
for l in col: print(f"  DENIED and legitimate: {l}")
print(f"  count: {len(col)}")

print("\n=== (4) NOT COVERED — actions that break the invariant but survive the deny ===")
esc = [(l,o) for l,o,d,g in rows if not o["head_is_literal_sha"] and not d]
for l,o in esc: print(f"  ESCAPES the deny: {l:36s} HEAD -> {o['head_after']!r}")
print(f"  count: {len(esc)}")
