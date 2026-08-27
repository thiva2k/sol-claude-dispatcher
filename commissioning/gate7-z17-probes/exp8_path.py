#!/usr/bin/env python3
"""EXP 8 — is PATH itself an execution surface for G4 `worktree add`?

PIN 2 (core.hooksPath) neutralises hooks. It does NOT neutralise .gitattributes
filter drivers, which run during checkout and are resolved through the SHELL,
hence through PATH. If a repository-supplied filter can be made to run, then
admitting PATH into the child is admitting an execution surface -- which is a
direct argument about the CONTENTS of Sol's allowlist, not just its existence.
"""
import os, subprocess, tempfile, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rows import GIT, pin_block

S = tempfile.mkdtemp(prefix="z17p8.")
BIN = tempfile.mkdtemp(prefix="z17pbin.")
MARK = os.path.join(S,"FILTER_RAN")
shim = os.path.join(BIN,"z17filter")
open(shim,"w").write(f'#!/bin/sh\ntouch "{MARK}"\ncat\n'); os.chmod(shim,0o755)

root = tempfile.mkdtemp(prefix="z17p8r.")
e = dict(os.environ); e["GIT_CONFIG_NOSYSTEM"]="1"
def g(*a, cwd=root):
    r = subprocess.run([GIT,*a],cwd=cwd,env=e,capture_output=True,text=True)
    if r.returncode: raise RuntimeError(f"{a}: {r.stderr}")
    return r.stdout.strip()
g("init","-q","-b","main","."); g("config","user.email","z@z"); g("config","user.name","z")
# repository-supplied: .gitattributes IN THE TREE + a filter driver in .git/config
open(f"{root}/f.txt","w").write("payload\n")
open(f"{root}/.gitattributes","w").write("f.txt filter=z17\n")
g("add","-A"); g("commit","-q","-m","c1")
base = g("rev-parse","HEAD")
# the worker controls repository CONFIG under this threat model
g("config","filter.z17.smudge","z17filter")
g("config","filter.z17.required","false")

hooks = tempfile.mkdtemp(prefix="z17ph.")
SET = {"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1",
       "GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0","GIT_OPTIONAL_LOCKS":"0"}

print("fixture: .gitattributes 'f.txt filter=z17' committed; filter.z17.smudge=z17filter")
print("         the smudge program lives ONLY in", BIN, "\n")
for label, envd in (
    ("PATH ADMITTED (contains the filter program)", {**SET, "PATH": BIN}),
    ("PATH ADMITTED (normal system PATH)",          {**SET, "PATH": os.environ["PATH"]}),
    ("PATH DENIED   (Sol's allowlist without PATH)", dict(SET)),
):
    if os.path.exists(MARK): os.unlink(MARK)
    d = tempfile.mkdtemp(prefix="z17pw."); shutil.rmtree(d)
    r = subprocess.run([GIT,*pin_block(hooks),"worktree","add","--quiet","--detach",d,base],
                       cwd=root, env=envd, capture_output=True, text=True, timeout=120)
    ran = os.path.exists(MARK)
    content = open(os.path.join(d,"f.txt")).read().strip() if os.path.isdir(d) else "(no worktree)"
    print(f"  {label:46s} rc={r.returncode} filter_EXECUTED={str(ran):5s} f.txt={content!r}")
    if r.stderr.strip():
        print(f"      stderr: {r.stderr.strip().splitlines()[0][:70]}")
    subprocess.run([GIT,"worktree","remove","--force",d],cwd=root,env=e,capture_output=True)

print("\n  CONTROL: the first leg MUST show filter_EXECUTED=True, or this experiment")
print("  proves nothing about PATH.")
print("\n=== and the same question for core.gitProxy / core.sshCommand (S-delta) ===")
print("  those are resolved as SHELL command strings too; a bare program name in")
print("  them is found via PATH. Not re-measured here -- Z16 measured S-delta and")
print("  PIN 1 closes it. Recorded as INHERITED, not re-run.")
shutil.rmtree(root, ignore_errors=True); shutil.rmtree(BIN, ignore_errors=True)
