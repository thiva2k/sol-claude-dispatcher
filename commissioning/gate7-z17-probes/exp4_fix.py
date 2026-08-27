#!/usr/bin/env python3
"""EXP 4 — repairs for the five dead controls in EXP 3, and a correct item-4 leg.

EXP 3 DEFECT STATED: my "pin 4a removed" argv was built by a filter that deleted
the value but left the bare `-c`, producing a malformed argv. Those legs printed
`?` and are void. Rebuilt explicitly below.
"""
import os, sys, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rows import Fixture, run, GIT
from forge import write_graph, forge

fx = Fixture(); S = tempfile.mkdtemp(prefix="z17e4.")
amb = fx.child_env(dict(os.environ))
SET = {"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1",
       "GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0","GIT_OPTIONAL_LOCKS":"0"}
ALLOW = ("PATH","HOME","LANG","TMPDIR")
def allowl(p):
    e={k:p[k] for k in ALLOW if k in p}; e.update(SET); return e

write_graph(fx.root, amb, [fx.base, fx.decoy])
GP=os.path.join(fx.root,".git","objects","info","commit-graph")
finfo=forge(GP, fx.base, fx.decoy)
v=subprocess.run([GIT,"commit-graph","verify"],cwd=fx.root,env=amb,capture_output=True,text=True)
assert v.returncode==1, "forge control dead"
print(f"forge {finfo}; verify rc=1 (control fired)")
print(f"TRUE={fx.trueroot[:12]} DECOY={fx.decoy[:12]}\n")

# EXPLICIT argv blocks — no filtering
FULL = ["-c",f"core.hooksPath={fx.hooks}", "-c","core.commitGraph=false",
        "-c","core.multiPackIndex=false","-c","core.fsmonitor=false",
        "-c","core.attributesFile=/dev/null","-c","core.quotePath=false","--no-pager"]
NO4A = ["-c",f"core.hooksPath={fx.hooks}",
        "-c","core.multiPackIndex=false","-c","core.fsmonitor=false",
        "-c","core.attributesFile=/dev/null","-c","core.quotePath=false","--no-pager"]
DISPLACED = FULL[:-1] + ["-c","core.commitGraph=true","--no-pager"]
RL=["rev-list","--max-parents=0","HEAD"]

def show(label, argv, envd):
    r=run(argv+RL, fx.root, envd); o=r.stdout.strip()
    tag = "DECOY" if o.startswith(fx.decoy[:12]) else ("TRUE" if o.startswith(fx.trueroot[:12]) else f"?? rc={r.returncode} {r.stderr.strip()[:40]}")
    print(f"  {label:64s} -> {o[:12] or '-'} {tag}")
    return tag

print("=== ITEM 4, REBUILT — GIT_CONFIG_* precedence, correct argv ===")
print("(a) is the env config form genuinely LIVE?  [PIN 4a absent from argv]")
show("baseline: no env, no pin 4a (graph IS consulted)", NO4A, dict(SET))
show("GIT_CONFIG_PARAMETERS='core.commitGraph=false', no pin 4a", NO4A,
     {**SET,"GIT_CONFIG_PARAMETERS":"'core.commitGraph=false'"})
show("GIT_CONFIG_COUNT/KEY_0/VALUE_0 commitGraph=false, no pin 4a", NO4A,
     {**SET,"GIT_CONFIG_COUNT":"1","GIT_CONFIG_KEY_0":"core.commitGraph","GIT_CONFIG_VALUE_0":"false"})
print("(b) R-PIN-1: does a LATER argv -c outrank the env command-line scope?")
show("GIT_CONFIG_PARAMETERS='core.commitGraph=true' + argv -c ...=false", FULL,
     {**SET,"GIT_CONFIG_PARAMETERS":"'core.commitGraph=true'"})
show("GIT_CONFIG_COUNT ...=true + argv -c ...=false", FULL,
     {**SET,"GIT_CONFIG_COUNT":"1","GIT_CONFIG_KEY_0":"core.commitGraph","GIT_CONFIG_VALUE_0":"true"})
print("(c) ZI-71 displacement: a caller -c AFTER the pin block")
show("PIN_BLOCK(false) then caller -c core.commitGraph=true", DISPLACED, dict(SET))
print("(d) ALLOWLIST: can the env form arrive at all?")
show("GIT_CONFIG_PARAMETERS in PARENT, allowlist child, PIN 4a present", FULL,
     allowl({"GIT_CONFIG_PARAMETERS":"'core.commitGraph=true'"}))
show("GIT_CONFIG_PARAMETERS in PARENT, allowlist child, PIN 4a ABSENT", NO4A,
     allowl({"GIT_CONFIG_PARAMETERS":"'core.commitGraph=true'"}))
show("GIT_CONFIG_COUNT in PARENT, allowlist child, PIN 4a ABSENT", NO4A,
     allowl({"GIT_CONFIG_COUNT":"1","GIT_CONFIG_KEY_0":"core.commitGraph","GIT_CONFIG_VALUE_0":"true"}))
print("(e) the ARGV half is NOT an environment problem:")
show("allowlist child + displaced caller -c", DISPLACED, allowl({}))

print("\n=== DEAD CONTROL REPAIR — GIT_TRACE / GIT_TRACE2_EVENT ===")
print("  (they write to a FILE; stdout/stderr do not move, so EXP 3 could not see them)")
for var in ("GIT_TRACE","GIT_TRACE2_EVENT","GIT_TRACE2_PERF","GIT_TRACE_PACKET",
            "GIT_TRACE_SETUP","GIT_TRACE_PERFORMANCE","GIT_TRACE_REFS"):
    for mode, envd in (("BYPASS", {**SET, var: os.path.join(S, var+".log")}),
                       ("ALLOWLIST", allowl({var: os.path.join(S, var+".log")}))):
        p = os.path.join(S, var+".log")
        if os.path.exists(p): os.unlink(p)
        run(FULL+RL, fx.root, envd)
        sz = os.path.getsize(p) if os.path.exists(p) else None
        if mode=="BYPASS":
            b = sz
        else:
            print(f"  {var:24s} bypass_file={b if b is not None else 'ABSENT':>8} bytes | "
                  f"allowlist_file={sz if sz is not None else 'ABSENT':>8}   "
                  f"control={'FIRED' if b else 'DEAD'}  "
                  f"allowlist={'DEFEATED' if sz else 'closed'}")

print("\n=== DEAD CONTROL REPAIR — GIT_NAMESPACE ===")
subprocess.run([GIT,"update-ref","refs/namespaces/z17ns/refs/heads/planted",fx.decoy],
               cwd=fx.root, env=amb, capture_output=True)
for label, envd in (("BYPASS (GIT_NAMESPACE=z17ns)", {**SET,"GIT_NAMESPACE":"z17ns"}),
                    ("baseline (no var)", dict(SET)),
                    ("ALLOWLIST", allowl({"GIT_NAMESPACE":"z17ns"}))):
    r = run(FULL+["for-each-ref","--format=%(refname) %(objectname)"], fx.root, envd)
    print(f"  {label:32s} -> {r.stdout.strip().replace(chr(10),' | ')[:96]}")
print("  NOTE: `for-each-ref` is NOT a permitted row. GIT_NAMESPACE has no measured")
print("  effect on any of the nine permitted rows; this leg only proves the harness")
print("  can see namespacing at all.")

print("\n=== GIT_PROXY_COMMAND — does it EXECUTE, and is the exec real? ===")
MARK=os.path.join(S,"PROXY_RAN"); SHIM=os.path.join(S,"proxy")
open(SHIM,"w").write(f'#!/bin/sh\ntouch "{MARK}"\nexit 1\n'); os.chmod(SHIM,0o755)
DENY_SCRUB=("GIT_CONFIG_COUNT","GIT_CONFIG_PARAMETERS","GIT_EXTERNAL_DIFF","GIT_SSH",
 "GIT_SSH_COMMAND","GIT_ASKPASS","GIT_PAGER","GIT_ATTR_NOSYSTEM")
def deny(p):
    e=dict(p)
    for k in DENY_SCRUB: e.pop(k,None)
    e.update(SET); return e
for label, envd in (("baseline (no var)", dict(SET)),
                    ("BYPASS", {**SET,"GIT_PROXY_COMMAND":SHIM}),
                    ("revision-7 DENYLIST", deny({"GIT_PROXY_COMMAND":SHIM})),
                    ("ALLOWLIST", allowl({"GIT_PROXY_COMMAND":SHIM}))):
    if os.path.exists(MARK): os.unlink(MARK)
    r = run(FULL+["ls-remote","git://127.0.0.1:9/x"], fx.root, envd)
    print(f"  {label:22s} rc={r.returncode} proxy_EXECUTED={os.path.exists(MARK)}  "
          f"{r.stderr.strip().splitlines()[0][:52] if r.stderr.strip() else ''}")
print(f"\nfixture={fx.root}")
