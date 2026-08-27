#!/usr/bin/env python3
"""EXP 2C — re-arming the nine controls that DID NOT FIRE in EXP 2B.

EXP 2B honestly reported 9/14 controls dead. Each is re-armed here with a
fixture that gives the variable something to bite, or is recorded NOT ATTEMPTED
with the reason. Only after a control fires in the RAW column may the DENYLIST
and ALLOWLIST cells for that name be read as measurements.
"""
import os, sys, subprocess, tempfile, shutil, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rows import Fixture, ROWS, compare, run, pin_block, GIT
from forge import write_graph, forge

fx = Fixture()
S = tempfile.mkdtemp(prefix="z17r.")
amb = fx.child_env(dict(os.environ))
SET = {"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1",
       "GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0","GIT_OPTIONAL_LOCKS":"0"}
DENY_STRIP=("GIT_DIR","GIT_WORK_TREE","GIT_COMMON_DIR","GIT_INDEX_FILE",
  "GIT_OBJECT_DIRECTORY","GIT_ALTERNATE_OBJECT_DIRECTORIES","GIT_CEILING_DIRECTORIES","GIT_NAMESPACE")
DENY_SCRUB=("GIT_CONFIG_COUNT","GIT_CONFIG_PARAMETERS","GIT_EXTERNAL_DIFF","GIT_SSH",
  "GIT_SSH_COMMAND","GIT_ASKPASS","GIT_PAGER","GIT_ATTR_NOSYSTEM")
DENY_PREFIX=("GIT_CONFIG_KEY_","GIT_CONFIG_VALUE_","GIT_TEST_")
def deny(p):
    e=dict(p)
    for k in DENY_STRIP+DENY_SCRUB: e.pop(k,None)
    for k in list(e):
        if any(k.startswith(x) for x in DENY_PREFIX): e.pop(k,None)
    e.update(SET); return e
def allow(p, a=("PATH","HOME","LANG","TMPDIR")):
    e={k:p[k] for k in a if k in p}; e.update(SET); return e

def probe(cmd, cwd, envd):
    return run(pin_block(fx.hooks)+cmd, cwd, envd)

def row(label, cmd, cwd, parent, note=""):
    r_raw  = probe(cmd, cwd, dict(parent))
    r_den  = probe(cmd, cwd, deny(parent))
    r_all  = probe(cmd, cwd, allow(parent))
    r_none = probe(cmd, cwd, dict(SET))
    fired  = (r_raw.returncode, r_raw.stdout) != (r_none.returncode, r_none.stdout)
    def s(r): return f"rc={r.returncode} {r.stdout.strip()[:34] or r.stderr.strip()[:34]!r}"
    print(f"\n  {label}   {note}")
    print(f"     no var (baseline) : {s(r_none)}")
    print(f"     RAW   (no policy) : {s(r_raw)}   CONTROL {'FIRED' if fired else '*** DID NOT FIRE ***'}")
    print(f"     DENYLIST (rev 7)  : {s(r_den)}   {'DEFEATED' if (r_den.returncode,r_den.stdout)!=(r_none.returncode,r_none.stdout) else 'held'}")
    print(f"     ALLOWLIST (Sol)   : {s(r_all)}   {'DEFEATED' if (r_all.returncode,r_all.stdout)!=(r_none.returncode,r_none.stdout) else 'HELD'}")
    return fired

fired = {}
print("=== RE-ARM 1 — GIT_TEST_COMMIT_GRAPH / GIT_CONFIG_PARAMETERS need a FORGED GRAPH ===")
info = None
try:
    write_graph(fx.root, amb, [fx.base, fx.decoy])
    p = os.path.join(fx.root,".git","objects","info","commit-graph")
    info = forge(p, fx.base, fx.decoy)
    print(f"  forge asserted: {info}")
    v = subprocess.run([GIT,"commit-graph","verify"],cwd=fx.root,env=amb,
                       capture_output=True,text=True)
    print(f"  INDEPENDENT CONTROL `git commit-graph verify` -> rc={v.returncode} "
          f"{'(rc=1 = the forge genuinely took)' if v.returncode else '*** rc=0: FORGE DID NOT TAKE ***'}")
    print(f"     {v.stdout.strip().splitlines()[0][:100] if v.stdout.strip() else v.stderr.strip().splitlines()[0][:100]}")
except AssertionError as e:
    print(f"  *** FORGE FAILED: {e} — rows below are NOT ATTEMPTED ***")

RL = ["rev-list","--max-parents=0","HEAD"]
print(f"\n  TRUE root={fx.trueroot[:12]}  DECOY={fx.decoy[:12]}")
if info:
    fired["GIT_TEST_COMMIT_GRAPH"] = row("GIT_TEST_COMMIT_GRAPH=1", RL, fx.root,
        {"GIT_TEST_COMMIT_GRAPH":"1"}, "(pin -c core.commitGraph=false is IN the argv)")
    fired["GIT_CONFIG_PARAMETERS"] = row("GIT_CONFIG_PARAMETERS core.commitGraph=true",
        RL, fx.root, {"GIT_CONFIG_PARAMETERS":"'core.commitGraph=true'"})
    fired["GIT_CONFIG_COUNT"] = row("GIT_CONFIG_COUNT/KEY_0/VALUE_0", RL, fx.root,
        {"GIT_CONFIG_COUNT":"1","GIT_CONFIG_KEY_0":"core.commitGraph","GIT_CONFIG_VALUE_0":"true"})
    fired["GIT_COMMIT_GRAPH_PARANOIA"] = row("GIT_COMMIT_GRAPH_PARANOIA=false", RL, fx.root,
        {"GIT_COMMIT_GRAPH_PARANOIA":"false"}, "(NOT in any rev-7 list)")

print("\n=== RE-ARM 2 — GIT_CEILING_DIRECTORIES needs cwd BELOW the repo root ===")
sub = os.path.join(fx.root,"sub")
fired["GIT_CEILING_DIRECTORIES"] = row("GIT_CEILING_DIRECTORIES=<root>",
    ["rev-parse","--absolute-git-dir"], sub, {"GIT_CEILING_DIRECTORIES": fx.root},
    f"(cwd={sub})")

print("\n=== RE-ARM 3 — GIT_ALTERNATE_OBJECT_DIRECTORIES needs an alt store WITH an object ===")
altrepo = tempfile.mkdtemp(prefix="z17altr.")
subprocess.run([GIT,"init","-q","-b","main","."],cwd=altrepo,env=amb,capture_output=True)
blobid = subprocess.run([GIT,"hash-object","-w","--stdin"],cwd=altrepo,env=amb,
        input="Z17_ALTERNATE_ONLY_OBJECT\n",capture_output=True,text=True).stdout.strip()
altobj = os.path.join(altrepo,".git","objects")
print(f"  object {blobid[:12]} exists ONLY in the alternate store")
fired["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = row("GIT_ALTERNATE_OBJECT_DIRECTORIES=<alt>",
    ["cat-file","-p",blobid], fx.root, {"GIT_ALTERNATE_OBJECT_DIRECTORIES": altobj})

print("\n=== RE-ARM 4 — GIT_WORK_TREE / GIT_INDEX_FILE / GIT_NAMESPACE ===")
OTHER = tempfile.mkdtemp(prefix="z17oth.")
subprocess.run([GIT,"init","-q","-b","main","."],cwd=OTHER,env=amb,capture_output=True)
fired["GIT_WORK_TREE"] = row("GIT_DIR + GIT_WORK_TREE (the documented pair)",
    ["rev-parse","--show-toplevel"], fx.root,
    {"GIT_DIR": os.path.join(fx.root,".git"), "GIT_WORK_TREE": OTHER},
    "(GIT_WORK_TREE is inert ALONE; it is a pair variable)")
idx = os.path.join(S,"planted.idx")
fired["GIT_INDEX_FILE"] = row("GIT_INDEX_FILE=<planted>", ["rev-parse","--git-path","index"],
    fx.root, {"GIT_INDEX_FILE": idx})
fired["GIT_NAMESPACE"] = row("GIT_NAMESPACE=z17ns", ["rev-parse","--namespace-path","HEAD"]
    if False else ["rev-parse","--symbolic-full-name","HEAD"], fx.root,
    {"GIT_NAMESPACE":"z17ns"}, "(HEAD is not namespaced; see note)")

print("\n=== RE-ARM 5 — GIT_ATTR_NOSYSTEM ===")
sysattr = "/etc/gitattributes"
print(f"  {sysattr} exists: {os.path.exists(sysattr)}")
print(f"  writing it requires root, which this lane does not have and must not take.")
print(f"  VERDICT: NOT ATTEMPTED. The rev-7 direction defect (scrubbing")
print(f"  GIT_ATTR_NOSYSTEM makes git CONSULT /etc/gitattributes) is a STATIC")
print(f"  reading of git's semantics, unchanged by this lane, and is moot under an")
print(f"  allowlist since neither the variable nor its absence is inherited.")

print("\n--- RE-ARM CONTROL VERDICT ---")
for k,v in fired.items():
    print(f"  {k:36s} {'FIRED' if v else '*** STILL DID NOT FIRE ***'}")
print(f"\nfixture={fx.root}")
