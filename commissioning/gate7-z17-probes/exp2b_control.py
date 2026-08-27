#!/usr/bin/env python3
"""EXP 2B — POSITIVE CONTROL for the EXP 2 sweep.

EXP 2 reported that no DENYLISTED name had an effect. That is exactly what a
sweep which cannot detect anything would also report. This re-runs the identical
sweep with NO policy at all (raw inherited env, no strip, no scrub, no set) and
requires the denylisted names to LIGHT UP. If they do not, EXP 2's denylist
column is NOT ATTEMPTED, not clean.

Three columns per name:  RAW (no policy) | DENYLIST (rev 7) | ALLOWLIST (Sol).
"""
import os, sys, json, importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "sw", os.path.join(os.path.dirname(os.path.abspath(__file__)), "exp2_sweep.py"))
# re-implement rather than import (exp2_sweep runs on import); duplicate the setup
import subprocess, tempfile, shutil
from rows import Fixture, ROWS, compare, run, GIT

fx = Fixture()
SCRATCH = tempfile.mkdtemp(prefix="z17c.")
MARK = os.path.join(SCRATCH, "MARKER")
SHIM = os.path.join(SCRATCH, "shim.sh")
open(SHIM,"w").write(f'#!/bin/sh\ntouch "{MARK}"\nexec /bin/true "$@"\n'); os.chmod(SHIM,0o755)
OTHER = tempfile.mkdtemp(prefix="z17o.")
subprocess.run([GIT,"init","-q","-b","main","."],cwd=OTHER,
               env=fx.child_env(dict(os.environ)),capture_output=True)
CFG = os.path.join(SCRATCH,"poison.cfg")
open(CFG,"w").write("[core]\n\tquotePath = true\n[z17]\n\tpoison = HIT\n")

SET = {"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1",
       "GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0","GIT_OPTIONAL_LOCKS":"0"}
DENY_STRIP = ("GIT_DIR","GIT_WORK_TREE","GIT_COMMON_DIR","GIT_INDEX_FILE",
              "GIT_OBJECT_DIRECTORY","GIT_ALTERNATE_OBJECT_DIRECTORIES",
              "GIT_CEILING_DIRECTORIES","GIT_NAMESPACE")
DENY_SCRUB = ("GIT_CONFIG_COUNT","GIT_CONFIG_PARAMETERS","GIT_EXTERNAL_DIFF",
              "GIT_SSH","GIT_SSH_COMMAND","GIT_ASKPASS","GIT_PAGER","GIT_ATTR_NOSYSTEM")
DENY_PREFIX = ("GIT_CONFIG_KEY_","GIT_CONFIG_VALUE_","GIT_TEST_")

def raw_env(parent):        # no policy whatsoever
    return dict(parent)
def deny_env(parent):
    e = dict(parent)
    for k in DENY_STRIP: e.pop(k,None)
    for k in DENY_SCRUB: e.pop(k,None)
    for k in list(e):
        if any(k.startswith(p) for p in DENY_PREFIX): e.pop(k,None)
    e.update(SET); return e
def allow_env(parent, allow=("PATH","HOME","LANG","TMPDIR")):
    e = {k:parent[k] for k in allow if k in parent}
    e.update(SET); return e

def probe(envd):
    if os.path.exists(MARK): os.unlink(MARK)
    changed=[]
    for n,_ in ROWS:
        ok,det = compare(fx,n,envd)
        if not ok: changed.append(n)
    return changed, os.path.exists(MARK)

# The names the DENYLIST claims to cover. Each gets a value that MUST bite.
CASES = {
  "GIT_DIR": os.path.join(OTHER,".git"),
  "GIT_WORK_TREE": OTHER,
  "GIT_COMMON_DIR": os.path.join(OTHER,".git"),
  "GIT_INDEX_FILE": os.path.join(SCRATCH,"idx"),
  "GIT_OBJECT_DIRECTORY": os.path.join(OTHER,".git","objects"),
  "GIT_ALTERNATE_OBJECT_DIRECTORIES": os.path.join(OTHER,".git","objects"),
  "GIT_CEILING_DIRECTORIES": "/tmp",
  "GIT_NAMESPACE": "z17ns",
  "GIT_CONFIG_PARAMETERS": "'core.commitGraph=true' 'z17.poison=HIT'",
  "GIT_TEST_COMMIT_GRAPH": "1",
  "GIT_ATTR_NOSYSTEM": "1",
  "GIT_GRAFT_FILE": None,   # filled below
  "GIT_SHALLOW_FILE": None,
}
g = os.path.join(SCRATCH,"graft"); open(g,"w").write(f"{fx.base} {fx.decoy}\n")
s = os.path.join(SCRATCH,"shallow"); open(s,"w").write(f"{fx.base}\n")
CASES["GIT_GRAFT_FILE"]=g; CASES["GIT_SHALLOW_FILE"]=s
# GIT_CONFIG_COUNT is a triple
TRIPLE = {"GIT_CONFIG_COUNT":"1","GIT_CONFIG_KEY_0":"core.commitGraph",
          "GIT_CONFIG_VALUE_0":"true"}

print(f"{'name':38s} {'RAW':>12s} {'DENYLIST':>12s} {'ALLOWLIST':>12s}")
print("-"*78)
def fmt(c,m): return ("EFFECT" if (c or m) else "inert") + (f"({len(c)})" if c else "")
control_fired = []
for name, val in CASES.items():
    p = {name: val}
    r,_ = probe(raw_env(p)); d,_ = probe(deny_env(p)); a,_ = probe(allow_env(p))
    fired = bool(r)
    control_fired.append((name, fired))
    print(f"{name:38s} {fmt(r,0):>12s} {fmt(d,0):>12s} {fmt(a,0):>12s}"
          f"{'' if fired else '   <-- CONTROL DID NOT FIRE'}")
r,_ = probe(raw_env(TRIPLE)); d,_ = probe(deny_env(TRIPLE)); a,_ = probe(allow_env(TRIPLE))
print(f"{'GIT_CONFIG_COUNT/KEY_0/VALUE_0':38s} {fmt(r,0):>12s} {fmt(d,0):>12s} {fmt(a,0):>12s}")
control_fired.append(("GIT_CONFIG_COUNT-triple", bool(r)))

print("\n--- CONTROL VERDICT ---")
dead = [n for n,f in control_fired if not f]
print(f"  controls that fired: {sum(1 for _,f in control_fired if f)}/{len(control_fired)}")
if dead:
    print(f"  *** DID NOT FIRE: {dead}")
    print("  For those names the DENYLIST 'inert' cell is NOT ATTEMPTED, not clean.")
else:
    print("  every denylisted name demonstrably bites when policy is removed;")
    print("  the sweep's 'inert' cells are armed negatives.")
print(f"\nfixture={fx.root}")
