#!/usr/bin/env python3
"""EXP 1B — CONTROLS for EXP 1's empty-allowlist result.

EXP 1 returned "no inherited variable is necessary". That is a negative. This
file proves the same harness CAN report FAIL, for each failure mode it claims to
have looked for: (a) nonzero rc, (b) byte-different stdout, (c) a variable that
genuinely does reach git. If any control here does not fire, EXP 1's result is
NOT ATTEMPTED, not clean.
"""
import os, sys, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rows import Fixture, ROWS, compare, run, pin_block, GIT

fx = Fixture()
PINS = {"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1",
        "GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0","GIT_OPTIONAL_LOCKS":"0"}
fired = {}

def report(name, ok, detail):
    fired[name] = ok
    print(f"  {'CONTROL FIRED   ' if ok else 'CONTROL DID NOT FIRE':22s} {name}: {detail}")

print("=== CONTROL 1 — the harness detects a NONZERO rc ===")
e = dict(PINS)
r = run(pin_block(fx.hooks) + ["rev-parse","--verify","--end-of-options",
        "0000000000000000000000000000000000000000^{commit}"], fx.root, e)
report("rc-detection", r.returncode != 0, f"absent object -> rc={r.returncode}")

print("\n=== CONTROL 2 — the harness detects a BYTE-DIFFERENT stdout ===")
# same row, one pin flipped: quotePath. Add a non-ASCII path to the fixture.
sub = os.path.join(fx.root, "näme.txt")
open(sub,"w").write("x\n")
amb = fx.child_env(dict(os.environ))
subprocess.run([GIT,"add","-A"],cwd=fx.root,env=amb,capture_output=True)
subprocess.run([GIT,"-c","user.email=z@z","-c","user.name=z","commit","-q","-m","nonascii"],
               cwd=fx.root,env=amb,capture_output=True)
h = subprocess.run([GIT,"rev-parse","HEAD"],cwd=fx.root,env=amb,capture_output=True,text=True).stdout.strip()
a = run(["-c","core.quotePath=false","ls-tree","-r","-z",h], fx.root, e).stdout
b = run(["-c","core.quotePath=true","ls-tree","-r","-z",h], fx.root, e).stdout
report("stdout-diff-detection", a != b,
       f"quotePath false/true ls-tree differ: {a!=b} ({len(a)} vs {len(b)} bytes)")

print("\n=== CONTROL 3 — an inherited variable DOES reach git in this harness ===")
# GIT_DIR is the textbook case; it must redirect when admitted.
other = tempfile.mkdtemp(prefix="z17other.")
subprocess.run([GIT,"init","-q","-b","main","."],cwd=other,env=amb,capture_output=True)
e_git = dict(PINS); e_git["GIT_DIR"] = os.path.join(other,".git")
r_admit = run(pin_block(fx.hooks)+["rev-parse","--absolute-git-dir"], fx.root, e_git)
r_deny  = run(pin_block(fx.hooks)+["rev-parse","--absolute-git-dir"], fx.root, dict(PINS))
report("env-reaches-child", r_admit.stdout.strip() != r_deny.stdout.strip(),
       f"admitted GIT_DIR -> {r_admit.stdout.strip()} | denied -> {r_deny.stdout.strip()}")

print("\n=== CONTROL 4 — HOME/XDG_CONFIG_HOME are genuinely CONSULTED without the pin ===")
fakehome = tempfile.mkdtemp(prefix="z17home.")
os.makedirs(os.path.join(fakehome,".config","git"), exist_ok=True)
open(os.path.join(fakehome,".gitconfig"),"w").write("[core]\n\tquotePath = true\n[z17]\n\tmark = HOMEHIT\n")
open(os.path.join(fakehome,".config","git","config"),"w").write("[z17]\n\txdg = XDGHIT\n")
# WITHOUT GIT_CONFIG_GLOBAL pin, HOME admitted:
e_nopin = {k:v for k,v in PINS.items() if k != "GIT_CONFIG_GLOBAL"}
e_nopin["HOME"] = fakehome
v1 = run(["config","--get","z17.mark"], fx.root, e_nopin)
e_nopin2 = dict(e_nopin); e_nopin2.pop("HOME"); e_nopin2["XDG_CONFIG_HOME"]=os.path.join(fakehome,".config")
v2 = run(["config","--get","z17.xdg"], fx.root, e_nopin2)
report("HOME-consulted-unpinned", v1.stdout.strip()=="HOMEHIT",
       f"HOME + no GIT_CONFIG_GLOBAL -> z17.mark={v1.stdout.strip()!r}")
report("XDG-consulted-unpinned", v2.stdout.strip()=="XDGHIT",
       f"XDG_CONFIG_HOME + no GIT_CONFIG_GLOBAL -> z17.xdg={v2.stdout.strip()!r}")
# WITH the pin, both inert:
e_pin = dict(PINS); e_pin["HOME"]=fakehome; e_pin["XDG_CONFIG_HOME"]=os.path.join(fakehome,".config")
w1 = run(["config","--get","z17.mark"], fx.root, e_pin)
w2 = run(["config","--get","z17.xdg"], fx.root, e_pin)
print(f"  WITH GIT_CONFIG_GLOBAL=/dev/null: z17.mark rc={w1.returncode} out={w1.stdout.strip()!r} ; "
      f"z17.xdg rc={w2.returncode} out={w2.stdout.strip()!r}")

print("\n=== CONTROL 5 — does PATH matter to the PARENT's exec of 'git'? ===")
# _git_env() passes env= to subprocess; execvp searches the CHILD env's PATH.
for label, envd in (("PATH admitted", {**PINS, "PATH": os.environ["PATH"]}),
                    ("PATH ABSENT",   dict(PINS))):
    try:
        rr = subprocess.run(["git","rev-parse","--absolute-git-dir"], cwd=fx.root,
                            env=envd, capture_output=True, text=True)
        res = f"rc={rr.returncode} out={rr.stdout.strip()[:60]}"
    except FileNotFoundError as ex:
        res = f"FileNotFoundError: {ex}"
    print(f"  bare argv[0]='git', {label:14s} -> {res}")
for label, envd in (("PATH ABSENT", dict(PINS)),):
    rr = subprocess.run([GIT,"rev-parse","--absolute-git-dir"], cwd=fx.root,
                        env=envd, capture_output=True, text=True)
    print(f"  absolute argv[0]='{GIT}', {label} -> rc={rr.returncode} out={rr.stdout.strip()[:60]}")

print("\n=== CONTROL 6 — does LANG/LC_ALL change anything the dispatcher records? ===")
locs = subprocess.run(["locale","-a"],capture_output=True,text=True).stdout.split()
print(f"  locales available: {[l for l in locs if not l.startswith('C') and l!='POSIX'][:8]}")
for lc in ["C", "C.UTF-8"] + [l for l in locs if l.lower().startswith(("fr_","de_","ja_"))][:1]:
    ee = dict(PINS); ee["LC_ALL"]=lc; ee["LANG"]=lc
    rr = run(pin_block(fx.hooks)+["rev-parse","--verify","--end-of-options",
             "0000000000000000000000000000000000000000^{commit}"], fx.root, ee)
    print(f"  LC_ALL={lc:12s} stderr={rr.stderr.strip()[:90]!r}")
ee = dict(PINS)
rr = run(pin_block(fx.hooks)+["rev-parse","--verify","--end-of-options",
         "0000000000000000000000000000000000000000^{commit}"], fx.root, ee)
print(f"  LC_ALL absent      stderr={rr.stderr.strip()[:90]!r}")

print("\n=== CONTROL 7 — TMPDIR: is it used by any permitted row? ===")
td = tempfile.mkdtemp(prefix="z17tmp.")
before = set(os.listdir(td))
ee = dict(PINS); ee["TMPDIR"]=td
d = tempfile.mkdtemp(prefix="z17wt2."); import shutil; shutil.rmtree(d)
run(pin_block(fx.hooks)+["worktree","add","--quiet","--detach",d,fx.base], fx.root, ee, timeout=300)
after = set(os.listdir(td))
print(f"  TMPDIR contents created by 'worktree add': {sorted(after-before) or '(none)'}")
subprocess.run([GIT,"worktree","remove","--force",d],cwd=fx.root,env=amb,capture_output=True)

print("\n--- CONTROL SUMMARY ---")
for k,v in fired.items():
    print(f"  {k:26s} {'FIRED' if v else '*** DID NOT FIRE ***'}")
print(f"\nfixture: {fx.root}")
