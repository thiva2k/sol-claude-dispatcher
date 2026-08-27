#!/usr/bin/env python3
"""EXP 3 — (item 2) the named class, each with a firing positive control, and
(item 4) the GIT_CONFIG_* command-line-scope precedence hazard under an allowlist.

Four legs per variable:
  BASELINE   pins only, variable absent                      -> the reference
  BYPASS     variable admitted, NO env policy (positive control; MUST differ)
  DENYLIST   revision 7's _git_env()                         -> does it survive?
  ALLOWLIST  Sol's ruling: fixed allowlist, zero ambient GIT_* -> must equal BASELINE
A row whose BYPASS leg equals BASELINE is scored NOT ATTEMPTED, never `closed`.
"""
import os, sys, subprocess, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rows import Fixture, run, pin_block, GIT
from forge import write_graph, forge

fx = Fixture(); S = tempfile.mkdtemp(prefix="z17e3.")
amb = fx.child_env(dict(os.environ))
SET = {"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1",
       "GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0","GIT_OPTIONAL_LOCKS":"0"}
DENY_STRIP=("GIT_DIR","GIT_WORK_TREE","GIT_COMMON_DIR","GIT_INDEX_FILE",
 "GIT_OBJECT_DIRECTORY","GIT_ALTERNATE_OBJECT_DIRECTORIES","GIT_CEILING_DIRECTORIES","GIT_NAMESPACE")
DENY_SCRUB=("GIT_CONFIG_COUNT","GIT_CONFIG_PARAMETERS","GIT_EXTERNAL_DIFF","GIT_SSH",
 "GIT_SSH_COMMAND","GIT_ASKPASS","GIT_PAGER","GIT_ATTR_NOSYSTEM")
DENY_PREFIX=("GIT_CONFIG_KEY_","GIT_CONFIG_VALUE_","GIT_TEST_")
ALLOW = ("PATH","HOME","LANG","TMPDIR")     # candidate allowlist under test
def deny(p):
    e=dict(p)
    for k in DENY_STRIP+DENY_SCRUB: e.pop(k,None)
    for k in list(e):
        if any(k.startswith(x) for x in DENY_PREFIX): e.pop(k,None)
    e.update(SET); return e
def allowl(p):
    e={k:p[k] for k in ALLOW if k in p}; e.update(SET); return e

# --- forged graph so the graph levers have something to bite -------------------
write_graph(fx.root, amb, [fx.base, fx.decoy])
GP = os.path.join(fx.root,".git","objects","info","commit-graph")
finfo = forge(GP, fx.base, fx.decoy)
v = subprocess.run([GIT,"commit-graph","verify"],cwd=fx.root,env=amb,capture_output=True,text=True)
assert v.returncode == 1, "forge control did not fire"
print(f"FIXTURE {fx.root}\n  forge {finfo}, commit-graph verify rc={v.returncode} (control fired)")
print(f"  TRUE root {fx.trueroot[:12]}   DECOY {fx.decoy[:12]}   BASE {fx.base[:12]}\n")

# --- payload files, all OUTSIDE the repository --------------------------------
GRAFT=os.path.join(S,"graft"); open(GRAFT,"w").write(f"{fx.base} {fx.decoy}\n")
SHALLOW=os.path.join(S,"shallow"); open(SHALLOW,"w").write(f"{fx.base}\n")
CFG=os.path.join(S,"sys.cfg"); open(CFG,"w").write("[core]\n\tcommitGraph = true\n")
ALTR=tempfile.mkdtemp(prefix="z17alt."); subprocess.run([GIT,"init","-q","."],cwd=ALTR,env=amb,capture_output=True)
ALTBLOB=subprocess.run([GIT,"hash-object","-w","--stdin"],cwd=ALTR,env=amb,
        input="Z17_ALT\n",capture_output=True,text=True).stdout.strip()
OTHER=tempfile.mkdtemp(prefix="z17oth."); subprocess.run([GIT,"init","-q","."],cwd=OTHER,env=amb,capture_output=True)
SHIM=os.path.join(S,"shim"); MARK=os.path.join(S,"MARK")
open(SHIM,"w").write(f'#!/bin/sh\ntouch "{MARK}"\nexec /bin/true "$@"\n'); os.chmod(SHIM,0o755)
TRACE=os.path.join(S,"trace.log")

ROOTCMD=["rev-list","--max-parents=0","HEAD"]
G9=["rev-list","--objects","--missing=print","HEAD"]

def leg(cmd, cwd, envd, capture_stderr=False):
    r = run(pin_block(fx.hooks)+cmd, cwd, envd)
    out = r.stdout
    if capture_stderr: out += "|STDERR:" + r.stderr
    return r.returncode, out

def case(label, var, cmd=ROOTCMD, cwd=None, extra=None, stderr=False, note=""):
    cwd = cwd or fx.root
    parent = dict(extra) if extra else {}
    parent.update(var)
    if os.path.exists(MARK): os.unlink(MARK)
    base = leg(cmd, cwd, dict(SET), stderr)
    byp  = leg(cmd, cwd, dict(parent), stderr); byp_mark = os.path.exists(MARK)
    if os.path.exists(MARK): os.unlink(MARK)
    den  = leg(cmd, cwd, deny(parent), stderr); den_mark = os.path.exists(MARK)
    if os.path.exists(MARK): os.unlink(MARK)
    alw  = leg(cmd, cwd, allowl(parent), stderr); alw_mark = os.path.exists(MARK)
    ctrl = (byp != base) or byp_mark
    dsurv = (den != base) or den_mark
    asurv = (alw != base) or alw_mark
    verdict = ("NOT ATTEMPTED (control dead)" if not ctrl else
               ("ALLOWLIST HOLDS" if not asurv else "*** ALLOWLIST DEFEATED ***"))
    print(f"  {label:44s} control={'FIRED' if ctrl else 'DEAD '} "
          f"denylist={'SURVIVES' if dsurv else 'closed  '} "
          f"allowlist={'DEFEATED' if asurv else 'closed  '}  {verdict}")
    if note: print(f"      {note}")
    if ctrl:
        def sh(t): return f"rc={t[0]} {t[1].strip()[:44]!r}"
        print(f"      baseline {sh(base)}")
        print(f"      bypass   {sh(byp)}{'  +EXEC' if byp_mark else ''}")
        if dsurv: print(f"      DENYLIST {sh(den)}{'  +EXEC' if den_mark else ''}")
    return ctrl, dsurv, asurv

print("=== ITEM 2 — THE NAMED CLASS, EACH WITH A POSITIVE CONTROL ===")
res = {}
res["GIT_GRAFT_FILE"]=case("GIT_GRAFT_FILE (out-of-repo)", {"GIT_GRAFT_FILE":GRAFT})
res["GIT_GRAFT_FILE/G9"]=case("GIT_GRAFT_FILE -> G9 enumeration", {"GIT_GRAFT_FILE":GRAFT}, cmd=G9)
res["GIT_SHALLOW_FILE"]=case("GIT_SHALLOW_FILE (out-of-repo)", {"GIT_SHALLOW_FILE":SHALLOW},
    cmd=["rev-list","HEAD"])
res["GIT_SHALLOW_FILE/G9"]=case("GIT_SHALLOW_FILE -> G9 enumeration", {"GIT_SHALLOW_FILE":SHALLOW}, cmd=G9)
res["GIT_PROXY_COMMAND"]=case("GIT_PROXY_COMMAND", {"GIT_PROXY_COMMAND":SHIM},
    cmd=["ls-remote","git://127.0.0.1:9/x"], stderr=True,
    note="git:// is the only transport that consults GIT_PROXY_COMMAND")
res["GIT_TRACE"]=case("GIT_TRACE=<file>", {"GIT_TRACE":TRACE}, stderr=True)
res["GIT_TRACE2_EVENT"]=case("GIT_TRACE2_EVENT=<file>", {"GIT_TRACE2_EVENT":TRACE+"2"}, stderr=True)
res["GIT_TEST_COMMIT_GRAPH"]=case("GIT_TEST_COMMIT_GRAPH=1", {"GIT_TEST_COMMIT_GRAPH":"1"})
res["GIT_CONFIG_PARAMETERS"]=case("GIT_CONFIG_PARAMETERS commitGraph=true",
    {"GIT_CONFIG_PARAMETERS":"'core.commitGraph=true'"})
res["GIT_CONFIG_COUNT"]=case("GIT_CONFIG_COUNT/KEY_0/VALUE_0",
    {"GIT_CONFIG_COUNT":"1","GIT_CONFIG_KEY_0":"core.commitGraph","GIT_CONFIG_VALUE_0":"true"})
res["GIT_ALTERNATE_OBJECT_DIRECTORIES"]=case("GIT_ALTERNATE_OBJECT_DIRECTORIES",
    {"GIT_ALTERNATE_OBJECT_DIRECTORIES":os.path.join(ALTR,".git","objects")},
    cmd=["cat-file","-p",ALTBLOB])
res["GIT_INDEX_FILE"]=case("GIT_INDEX_FILE", {"GIT_INDEX_FILE":os.path.join(S,"idx")},
    cmd=["rev-parse","--git-path","index"])
res["GIT_OBJECT_DIRECTORY"]=case("GIT_OBJECT_DIRECTORY",
    {"GIT_OBJECT_DIRECTORY":os.path.join(OTHER,".git","objects")}, cmd=["cat-file","-t",fx.base])
res["GIT_DIR"]=case("GIT_DIR", {"GIT_DIR":os.path.join(OTHER,".git")},
    cmd=["rev-parse","--absolute-git-dir"])
res["GIT_WORK_TREE"]=case("GIT_WORK_TREE (+GIT_DIR, the pair)", {"GIT_WORK_TREE":OTHER},
    cmd=["rev-parse","--show-toplevel"], extra={"GIT_DIR":os.path.join(fx.root,".git")})
res["GIT_COMMON_DIR"]=case("GIT_COMMON_DIR", {"GIT_COMMON_DIR":os.path.join(OTHER,".git")},
    cmd=["rev-parse","--git-common-dir"], cwd=fx.wt)
res["GIT_NAMESPACE"]=case("GIT_NAMESPACE", {"GIT_NAMESPACE":"z17ns"},
    cmd=["rev-parse","--symbolic-full-name","--all"])
res["GIT_CEILING_DIRECTORIES"]=case("GIT_CEILING_DIRECTORIES",
    {"GIT_CEILING_DIRECTORIES":fx.root}, cmd=["rev-parse","--absolute-git-dir"],
    cwd=os.path.join(fx.root,"sub"))

print("\n--- ITEM 2 SUMMARY ---")
dead=[k for k,(c,d,a) in res.items() if not c]
dsv =[k for k,(c,d,a) in res.items() if c and d]
asv =[k for k,(c,d,a) in res.items() if c and a]
print(f"  rows with a FIRING positive control : {len(res)-len(dead)}/{len(res)}")
print(f"  controls DEAD (scored NOT ATTEMPTED): {dead or 'none'}")
print(f"  SURVIVE the revision-7 DENYLIST     : {dsv or 'none'}")
print(f"  SURVIVE the ALLOWLIST               : {asv or 'NONE — class closed'}")

print("\n=== ITEM 4 — THE GIT_CONFIG_* COMMAND-LINE-SCOPE PRECEDENCE HAZARD ===")
def show(label, argv, envd):
    r = run(argv, fx.root, envd)
    tag = "DECOY" if fx.decoy[:12] in r.stdout else ("TRUE" if fx.trueroot[:12] in r.stdout else "?")
    print(f"  {label:62s} -> {r.stdout.strip()[:12]} {tag}")
PB = pin_block(fx.hooks)
NOPIN4 = [a for a in PB if a != "core.commitGraph=false"]
NOPIN4 = [x for i,x in enumerate(NOPIN4) if not (x=="-c" and i+1<len(NOPIN4) and NOPIN4[i+1].startswith("core.commitGraph"))]
print("  (a) is the env config form LIVE at all?  [pin 4a removed from argv]")
show("GIT_CONFIG_PARAMETERS='core.commitGraph=true', no argv pin",
     NOPIN4+ROOTCMD, {**SET,"GIT_CONFIG_PARAMETERS":"'core.commitGraph=true'"})
show("GIT_CONFIG_COUNT/KEY_0/VALUE_0 commitGraph=true, no argv pin",
     NOPIN4+ROOTCMD, {**SET,"GIT_CONFIG_COUNT":"1","GIT_CONFIG_KEY_0":"core.commitGraph",
                      "GIT_CONFIG_VALUE_0":"true"})
show("no env, no argv pin (baseline: graph consulted)", NOPIN4+ROOTCMD, dict(SET))
print("  (b) does the argv pin outrank the env form? [R-PIN-1]")
show("GIT_CONFIG_PARAMETERS=true  +  argv -c core.commitGraph=false", PB+ROOTCMD,
     {**SET,"GIT_CONFIG_PARAMETERS":"'core.commitGraph=true'"})
print("  (c) the ZI-71 displacement hazard: a caller -c AFTER the pin block")
show("PIN_BLOCK ... -c core.commitGraph=false  THEN caller -c ...=true",
     PB[:-1]+["-c","core.commitGraph=true","--no-pager"]+ROOTCMD, dict(SET))
print("  (d) under the ALLOWLIST, can the env form arrive at all?")
show("GIT_CONFIG_PARAMETERS set in PARENT, allowlist child", PB+ROOTCMD,
     allowl({"GIT_CONFIG_PARAMETERS":"'core.commitGraph=true'"}))
show("GIT_CONFIG_PARAMETERS set in PARENT, allowlist child, NO argv pin 4a",
     NOPIN4+ROOTCMD, allowl({"GIT_CONFIG_PARAMETERS":"'core.commitGraph=true'"}))
print("  (e) is the ARGV half of the hazard affected by the allowlist?")
show("allowlist child + caller -c AFTER the pin block",
     PB[:-1]+["-c","core.commitGraph=true","--no-pager"]+ROOTCMD, allowl({}))
print(f"\nfixture={fx.root}")
