#!/usr/bin/env python3
"""EXP 1C — re-arming CONTROL 2 after it did not fire, and dissecting CONTROL 5.

CONTROL 2 FAILURE, stated: I chose `ls-tree -r -z` to demonstrate that the
harness detects a byte-different stdout by flipping core.quotePath. `-z` emits
NUL-terminated raw paths and DISABLES quoting entirely, so quotePath cannot
change that row's output. The control could not have produced a positive. The
defect was in my choice of lever, not in compare(). Re-armed below two ways.
"""
import os, sys, subprocess, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rows import Fixture, ROWS, compare, run, pin_block, GIT

fx = Fixture()
PINS = {"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1",
        "GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0","GIT_OPTIONAL_LOCKS":"0"}
amb = fx.child_env(dict(os.environ))

print("=== CONTROL 2 RE-ARM (a) — quotePath DOES move ls-tree WITHOUT -z ===")
open(os.path.join(fx.root,"näme.txt"),"w").write("x\n")
subprocess.run([GIT,"add","-A"],cwd=fx.root,env=amb,capture_output=True)
subprocess.run([GIT,"-c","user.email=z@z","-c","user.name=z","commit","-q","-m","na"],
               cwd=fx.root,env=amb,capture_output=True)
h = subprocess.run([GIT,"rev-parse","HEAD"],cwd=fx.root,env=amb,
                   capture_output=True,text=True).stdout.strip()
a = run(["-c","core.quotePath=false","ls-tree","-r",h], fx.root, dict(PINS)).stdout
b = run(["-c","core.quotePath=true", "ls-tree","-r",h], fx.root, dict(PINS)).stdout
print(f"  quotePath=false tail: {a.strip().splitlines()[-1][-30:]!r}")
print(f"  quotePath=true  tail: {b.strip().splitlines()[-1][-30:]!r}")
print(f"  CONTROL {'FIRED' if a!=b else '*** DID NOT FIRE ***'}: outputs differ = {a!=b}")
print(f"  (and this is WHY `-z` is in the pinned G2 argv: it makes G2 immune to the key)")

print("\n=== CONTROL 2 RE-ARM (b) — compare() itself flags a byte difference ===")
saved = fx.golden["G9"]["out"]
fx.golden["G9"] = {"out": saved + "MUTANT\n", "rc": 0, "err": ""}
ok, det = compare(fx, "G9", dict(PINS))
print(f"  golden mutated by 7 bytes -> compare() says ok={ok} detail={det!r}")
print(f"  CONTROL {'FIRED' if not ok else '*** DID NOT FIRE ***'}")
fx.golden["G9"] = {"out": saved, "rc": 0, "err": ""}
ok2, det2 = compare(fx, "G9", dict(PINS))
print(f"  golden restored -> ok={ok2} (must be True, else the harness is stuck-FAIL)")

print("\n=== CONTROL 5 DISSECTION — why does argv[0]='git' resolve with no PATH in env? ===")
print("  CPython subprocess resolves the executable with execvp-family semantics")
print("  against the CALLING process's PATH, not against the env= it hands the child.")
parent_path = os.environ.get("PATH")
for desc, mutate in (("parent PATH intact", None), ("parent PATH removed", "del")):
    if mutate == "del":
        os.environ.pop("PATH", None)
    try:
        rr = subprocess.run(["git","rev-parse","--absolute-git-dir"], cwd=fx.root,
                            env=dict(PINS), capture_output=True, text=True)
        res = f"rc={rr.returncode}"
    except FileNotFoundError as ex:
        res = f"FileNotFoundError({ex.strerror})"
    print(f"  bare argv[0]='git', child env has NO PATH, {desc:20s} -> {res}")
    if mutate == "del" and parent_path:
        os.environ["PATH"] = parent_path
print("  => PATH's necessity is a property of the PARENT process, not of the")
print("     allowlist. An allowlist that drops PATH does NOT break exec.")
print("     But the dispatcher's `[\"git\", *args]` then depends on an inherited")
print("     PATH it did not admit -- a hidden dependency. See finding.")

print("\n=== EXTRA — is PATH reachable by git ITSELF for any permitted row? ===")
# git dispatches aliases and non-builtin subcommands via PATH/exec-path.
bindir = tempfile.mkdtemp(prefix="z17bin.")
shim = os.path.join(bindir, "git-z17probe")
open(shim,"w").write("#!/bin/sh\necho Z17_PATH_SUBCOMMAND_RAN\n")
os.chmod(shim, 0o755)
for desc, envd in (("PATH ADMITTED (= shim dir)", {**PINS, "PATH": bindir}),
                   ("PATH DENIED",                dict(PINS))):
    rr = run(["z17probe"], fx.root, envd)
    print(f"  git z17probe, {desc:26s} -> rc={rr.returncode} out={rr.stdout.strip()!r}")
print("  => a PATH admitted into the child IS an execution surface for git itself.")

print("\n=== EXTRA — GIT_EXEC_PATH / GIT_TEMPLATE_DIR reachability ===")
for var, val in (("GIT_EXEC_PATH", bindir), ("GIT_TEMPLATE_DIR", bindir)):
    e = dict(PINS); e[var] = val
    rr = run(["--exec-path"], fx.root, e)
    print(f"  {var}={bindir} -> git --exec-path = {rr.stdout.strip()}")
shutil.rmtree(bindir, ignore_errors=True)
print(f"\nfixture: {fx.root}")
