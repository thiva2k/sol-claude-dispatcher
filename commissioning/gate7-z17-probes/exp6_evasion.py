#!/usr/bin/env python3
"""EXP 6 — the EVASION space for a `Bash(git checkout:*)` prefix deny.

CORE_DENIED_GIT_OPERATIONS entries are Bash *prefix* patterns handed to the
Claude CLI's --disallowedTools. This lane cannot spawn a worker (production
freeze), so the CLI's matcher is NOT exercised here; what IS measured is the set
of argv shapes that produce the SAME effect on <gitdir>/HEAD while not beginning
with the literal token sequence `git checkout` / `git switch`. Every such shape
is a hole in any prefix-shaped deny, independent of the matcher's details.
"""
import os, re, subprocess, tempfile, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rows import GIT
SHA = re.compile(rb"^[0-9a-f]{40}\n$")

def fresh():
    root = tempfile.mkdtemp(prefix="z17ev.")
    e = dict(os.environ); e["GIT_CONFIG_NOSYSTEM"]="1"
    def g(*a, cwd=root):
        r = subprocess.run([GIT,*a],cwd=cwd,env=e,capture_output=True,text=True)
        if r.returncode: raise RuntimeError(f"{a}: {r.stderr}")
        return r.stdout.strip()
    g("init","-q","-b","main","."); g("config","user.email","z@z"); g("config","user.name","z")
    open(f"{root}/f.txt","w").write("one\n"); g("add","-A"); g("commit","-q","-m","c1")
    base = g("rev-parse","HEAD")
    ext = tempfile.mkdtemp(prefix="z17evw."); wt = f"{ext}/task-wt"
    g("worktree","add","--quiet","--detach",wt,base)
    gd = subprocess.run([GIT,"rev-parse","--absolute-git-dir"],cwd=wt,env=e,
                        capture_output=True,text=True).stdout.strip()
    return root, ext, wt, gd, base, e

CASES = [
 ("git checkout -b x",                 lambda wt,gd,b: ([GIT,"checkout","-b","x"], wt), True),
 ("git switch -c x",                   lambda wt,gd,b: ([GIT,"switch","-c","x"], wt), True),
 ("git -C <wt> checkout -b x",         lambda wt,gd,b: ([GIT,"-C",wt,"checkout","-b","x"], "/tmp"), False),
 ("git --git-dir=<gd> --work-tree=<wt> checkout -b x",
      lambda wt,gd,b: ([GIT,f"--git-dir={gd}",f"--work-tree={wt}","checkout","-b","x"], "/tmp"), False),
 ("/usr/bin/git checkout -b x  (absolute argv[0])",
      lambda wt,gd,b: (["/usr/bin/git","checkout","-b","x"], wt), False),
 ("git symbolic-ref HEAD refs/heads/x",
      lambda wt,gd,b: ([GIT,"symbolic-ref","HEAD","refs/heads/x"], wt), False),
 ("git update-ref --no-deref HEAD <b> (stays literal)",
      lambda wt,gd,b: ([GIT,"update-ref","--no-deref","HEAD",b], wt), False),
 ("git branch x && git symbolic-ref HEAD refs/heads/x",
      lambda wt,gd,b: None, False),   # handled specially
 ("git checkout$'\\x20'-b  (argv is identical; only the SHELL text differs)",
      lambda wt,gd,b: ([GIT,"checkout","-b","x"], wt), False),
 ("printf > <gitdir>/HEAD   (no git process at all)",
      lambda wt,gd,b: None, False),   # handled specially
]

print(f"{'shape':56s} {'rc':>3s} {'HEAD after':>26s} {'invariant':>10s}")
print("-"*102)
for label, mk, is_literal_prefix in CASES:
    root, ext, wt, gd, base, e = fresh()
    headp = os.path.join(gd,"HEAD")
    sealed = open(headp,"rb").read()
    assert SHA.match(sealed)
    if label.startswith("git branch x &&"):
        subprocess.run([GIT,"branch","x"],cwd=wt,env=e,capture_output=True)
        r = subprocess.run([GIT,"symbolic-ref","HEAD","refs/heads/x"],cwd=wt,env=e,
                           capture_output=True,text=True)
    elif label.startswith("printf"):
        open(headp,"wb").write(b"ref: refs/heads/x\n")
        class R: returncode = 0
        r = R()
    else:
        argv, cwd = mk(wt,gd,base)
        r = subprocess.run(argv,cwd=cwd,env=e,capture_output=True,text=True)
    after = open(headp,"rb").read()
    ok = bool(SHA.match(after))
    print(f"{label:56s} {r.returncode:3d} {after.decode(errors='replace').strip()[:26]:>26s} "
          f"{'HELD' if after==sealed else 'BROKEN':>10s}"
          f"{'' if is_literal_prefix else '   <-- NOT matched by `git checkout`/`git switch` prefix'}")
    shutil.rmtree(root, ignore_errors=True); shutil.rmtree(ext, ignore_errors=True)

print("\nNOTE: the last row uses NO git process. No Bash deny pattern of any shape")
print("reaches it; only ZI-77's raw byte comparison does. That is the argument for")
print("keeping the byte rule REGARDLESS of what the deny list says.")
