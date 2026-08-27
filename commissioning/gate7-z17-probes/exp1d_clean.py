#!/usr/bin/env python3
"""EXP 1D — clean re-run of the two confounded checks from EXP 1C.

CONFOUND STATED: in EXP 1C I appended a commit to the fixture between golden
capture and the restore check, so the "restore" leg compared 619 live bytes
against a 493-byte golden and printed ok=False. That was my fixture moving, not
a stuck-FAIL harness. Re-run here with NO fixture mutation.

CONFOUND 2 STATED: `os.environ.pop("PATH")` did not break bare-`git` exec because
CPython falls back to os.confstr("CS_PATH") when PATH is unset. Re-armed with a
PATH that is SET but contains no git.
"""
import os, sys, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rows import Fixture, compare, run, GIT

fx = Fixture()
PINS = {"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1",
        "GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0","GIT_OPTIONAL_LOCKS":"0"}

print("=== A — compare(): mutate-then-restore on an UNMUTATED fixture ===")
saved = dict(fx.golden["G9"])
print(f"  clean          -> ok={compare(fx,'G9',dict(PINS))[0]}  (expect True)")
fx.golden["G9"] = {**saved, "out": saved["out"] + "MUTANT\n"}
ok, det = compare(fx, "G9", dict(PINS))
print(f"  golden mutated -> ok={ok} {det!r}  (expect False)")
fx.golden["G9"] = saved
ok2, _ = compare(fx, "G9", dict(PINS))
print(f"  golden restored-> ok={ok2}  (expect True)")
print(f"  CONTROL {'FIRED, both directions' if (not ok and ok2) else '*** DID NOT FIRE ***'}")

print("\n=== B — PATH: is the exec search real? (positive control re-armed) ===")
empty = tempfile.mkdtemp(prefix="z17nogit.")
saved_path = os.environ.get("PATH")
for desc, pv in (("parent PATH = a dir with NO git", empty),
                 ("parent PATH = ''", ""),
                 ("parent PATH restored", saved_path)):
    if pv is None: continue
    os.environ["PATH"] = pv
    try:
        rr = subprocess.run(["git","--version"], cwd=fx.root, env=dict(PINS),
                            capture_output=True, text=True)
        res = f"rc={rr.returncode} {rr.stdout.strip()}"
    except FileNotFoundError as ex:
        res = f"FileNotFoundError({ex.strerror})"
    print(f"  bare argv[0]='git', {desc:34s} -> {res}")
os.environ["PATH"] = saved_path
rr = subprocess.run([GIT,"--version"], cwd=fx.root, env=dict(PINS),
                    capture_output=True, text=True)
print(f"  absolute argv[0]='{GIT}', child env has no PATH -> rc={rr.returncode} {rr.stdout.strip()}")

print("\n=== C — GIT_EXEC_PATH: does it EXECUTE for a PERMITTED row? ===")
fakeexec = tempfile.mkdtemp(prefix="z17exec.")
marker = os.path.join(fakeexec, "Z17_EXEC_RAN")
# git-sh-setup / git-* helpers live in exec-path. Plant a shim for every helper
# a permitted row could plausibly dispatch, plus a catch-all probe.
for helper in ("git-checkout--worker","git-sh-setup","git-worktree","git-rev-list",
               "git-cat-file","git-ls-tree","git-rev-parse"):
    p = os.path.join(fakeexec, helper)
    open(p,"w").write(f"#!/bin/sh\ntouch {marker}.{helper}\nexit 0\n")
    os.chmod(p, 0o755)
import shutil
for row in ("G1","G2","G3","G4","G8","G9","G10a","G10b","RESUME"):
    for f in os.listdir(fakeexec):
        if f.startswith("Z17_EXEC_RAN"): os.unlink(os.path.join(fakeexec,f))
    e = dict(PINS); e["GIT_EXEC_PATH"] = fakeexec
    r = fx.row(row, e)
    hits = sorted(f.split(".",1)[1] for f in os.listdir(fakeexec) if f.startswith("Z17_EXEC_RAN"))
    ok, det = compare(fx, row, e)
    print(f"  {row:7s} GIT_EXEC_PATH admitted -> rc={r['rc']} identical={ok} "
          f"helpers_executed={hits or '(none)'}")
print("  CONTROL for this leg: `git z17probe` under GIT_EXEC_PATH ->", end=" ")
p = os.path.join(fakeexec,"git-z17probe")
open(p,"w").write("#!/bin/sh\necho Z17_EXECPATH_SUBCOMMAND_RAN\n"); os.chmod(p,0o755)
e = dict(PINS); e["GIT_EXEC_PATH"]=fakeexec
rr = run(["z17probe"], fx.root, e)
print(f"rc={rr.returncode} out={rr.stdout.strip()!r}")
rr2 = run(["z17probe"], fx.root, dict(PINS))
print(f"  same, GIT_EXEC_PATH DENIED -> rc={rr2.returncode} out={rr2.stdout.strip()!r}")
shutil.rmtree(fakeexec, ignore_errors=True); shutil.rmtree(empty, ignore_errors=True)
print(f"\nfixture: {fx.root}")
