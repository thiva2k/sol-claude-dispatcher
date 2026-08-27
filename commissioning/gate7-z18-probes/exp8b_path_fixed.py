#!/usr/bin/env python3
"""EXP 8B — REPAIR of EXP 8 (F7-3): PATH as an EXECUTION surface for G4
`worktree add`, with a POSITIVE CONTROL THAT ACTUALLY FIRES.

WHY THIS FILE EXISTS
--------------------
`commissioning/gate7-z17-probes/exp8_path.py` is a DEAD-CONTROL experiment. It
gives the child `PATH=<shimdir>` and then the shim itself calls the external
programs `touch` and `cat` -- neither of which can be resolved under that very
PATH. The shim therefore dies at its first line, the marker is never written,
and every leg prints `filter_EXECUTED=False`. The probe's own closing text says
the experiment proves nothing unless the first leg shows True. It never did.

Reproduced verbatim on this host before writing this file:

    PATH ADMITTED (contains the filter program)    rc=0 filter_EXECUTED=False f.txt='payload'
        stderr: /tmp/z17pbin.m2mq82pm/z17filter: 2: touch: not found

THE REPAIR HAS TWO PARTS
------------------------
1. The helper must not depend on commands excluded by its own PATH. Shim A uses
   ONLY shell built-ins and redirection (`: > file` for the marker, `echo` for
   the replacement content). Shim B is the alternative construction: external
   programs named by ABSOLUTE paths that this probe MEASURES at run time.
2. The positive control must change an OBSERVABLE RESULT, not merely leave a
   marker. Shim A replaces the checked-out content of `f.txt`, so the hostile
   leg is visible in the worktree even if the marker file were missed.

WHAT THIS EXPERIMENT COULD HAVE DETECTED
----------------------------------------
* that `worktree add` does NOT run smudge filters at all           (leg A/A2)
* that a bare-name smudge program is resolved by something other
  than the child's PATH                                            (leg B)
* that the final child-environment construction FAILS to suppress
  a repository-supplied filter driver                              (leg C)
* that dropping PATH is, or is not, sufficient on its own          (leg D)
* that the environment allowlist closes displaced-argv injection   (leg E)
* that `git` cannot be invoked at all without PATH                 (leg T40)

IT FAILS LOUDLY: if leg A does not fire, the probe prints CONTROL FAILURE and
exits 2. No result from this file may be cited when it exits nonzero.
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
Z17 = os.path.join(os.path.dirname(HERE), "gate7-z17-probes")
sys.path.insert(0, Z17)
from rows import pin_block, GIT as Z17_GIT  # noqa: E402  (identical pin block to Z17)

# ---------------------------------------------------------------- measurement
# T-40: the git binary is resolved to an absolute path ONCE, by measurement,
# and never by leaving PATH in the child so that git can find itself.
GIT = shutil.which("git")
assert GIT and os.path.isabs(GIT), f"git not resolvable to an absolute path: {GIT!r}"
GIT = os.path.realpath(GIT)
TOUCH = shutil.which("touch")
CAT = shutil.which("cat")
for name, p in (("touch", TOUCH), ("cat", CAT)):
    assert p and os.path.isabs(p) and os.access(p, os.X_OK), f"{name}: {p!r}"

print("=== 0. MEASURED TOOLING (nothing below is assumed) ===")
print(f"  git (shutil.which -> realpath) : {GIT}")
print(f"  rows.GIT (Z17 hard-coded)      : {Z17_GIT}   agrees={GIT == Z17_GIT}")
print(f"  touch (absolute, measured)     : {TOUCH}")
print(f"  cat   (absolute, measured)     : {CAT}")
print(f"  /bin/sh -> {os.path.realpath('/bin/sh')}")
print(f"  os.defpath                     : {os.defpath!r}")
v = subprocess.run([GIT, "--version"], capture_output=True, text=True)
print(f"  {v.stdout.strip()}")
print(f"  python                         : {sys.version.split()[0]}")

# --------------------------------------------------------------- the fixture
STATE = tempfile.mkdtemp(prefix="z18p8.")
BIN = tempfile.mkdtemp(prefix="z18bin.")
MARK = os.path.join(STATE, "FILTER_RAN")

# Shim A -- BUILT-INS ONLY. `:` is a special shell built-in and the marker is
# created by REDIRECTION; `echo` is a shell built-in. Nothing here needs PATH.
SHIM_A = os.path.join(BIN, "z18filter")
with open(SHIM_A, "w") as fh:
    fh.write(f'#!/bin/sh\n: > "{MARK}"\necho HOSTILE_SMUDGE_RAN\n')
os.chmod(SHIM_A, 0o755)

# Shim B -- external programs, but named by the ABSOLUTE paths measured above.
# Passes content through, so the marker is the only signal: this proves the
# marker detector is armed independently of the content change.
SHIM_B = os.path.join(BIN, "z18filter_abs")
with open(SHIM_B, "w") as fh:
    fh.write(f'#!/bin/sh\n{TOUCH} "{MARK}"\nexec {CAT}\n')
os.chmod(SHIM_B, 0o755)

ROOT = tempfile.mkdtemp(prefix="z18p8r.")
HOOKS = tempfile.mkdtemp(prefix="z18ph.")
ADMIN = dict(os.environ)
ADMIN["GIT_CONFIG_NOSYSTEM"] = "1"


def g(*a, cwd=ROOT, env=ADMIN):
    r = subprocess.run([GIT, *a], cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"fixture {a}: rc={r.returncode} {r.stderr}")
    return r.stdout.strip()


g("init", "-q", "-b", "main", ".")
g("config", "user.email", "z18@probe.invalid")
g("config", "user.name", "Z18")
with open(f"{ROOT}/f.txt", "w") as fh:
    fh.write("payload\n")
with open(f"{ROOT}/.gitattributes", "w") as fh:
    fh.write("f.txt filter=z18\n")
g("add", "-A")
g("commit", "-q", "-m", "c1")
BASE = g("rev-parse", "HEAD")

# The FINAL child-environment construction under test: Sol's allowlist, and
# nothing else. No PATH. No GIT_CONFIG_*. This is the exact dict the defended
# leg receives.
ALLOWLIST = {
    "GIT_NO_LAZY_FETCH": "1",
    "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
}

print("\n=== 1. FIXTURE ===")
print(f"  repo                  : {ROOT}")
print("  in-tree .gitattributes: 'f.txt filter=z18'   (committed at {})".format(BASE[:12]))
print(f"  committed f.txt       : 'payload'")
print(f"  shim dir (hostile)    : {BIN}")
print(f"  shim A (built-ins)    : {SHIM_A}")
print(f"    {open(SHIM_A).read().strip()!r}")
print(f"  shim B (measured abs) : {SHIM_B}")
print(f"    {open(SHIM_B).read().strip()!r}")
print(f"  marker path           : {MARK}")
print(f"  ALLOWLIST (final child env, verbatim) = {ALLOWLIST!r}")
print(f"  PIN BLOCK (from Z17 rows.pin_block)   = {pin_block(HOOKS)!r}")
print("  NOTE: the pin block's core.attributesFile=/dev/null neutralises the")
print("        GLOBAL attributes file. The IN-TREE .gitattributes is still")
print("        honoured -- that is why this surface exists at all.")


def set_repo_filter(smudge: str | None):
    """Repository CONFIG is worker-controlled under this threat model."""
    subprocess.run([GIT, "config", "--unset-all", "filter.z18.smudge"],
                   cwd=ROOT, env=ADMIN, capture_output=True)
    if smudge is not None:
        g("config", "filter.z18.smudge", smudge)
    g("config", "filter.z18.required", "false")


RESULTS = {}


def leg(tag, label, envd, smudge, displaced=(), expect=None):
    set_repo_filter(smudge)
    if os.path.exists(MARK):
        os.unlink(MARK)
    d = tempfile.mkdtemp(prefix="z18pw.")
    shutil.rmtree(d)
    argv = [GIT, *displaced, *pin_block(HOOKS), "worktree", "add", "--quiet",
            "--detach", d, BASE]
    r = subprocess.run(argv, cwd=ROOT, env=envd, capture_output=True,
                       text=True, timeout=180)
    ran = os.path.exists(MARK)
    fp = os.path.join(d, "f.txt")
    content = open(fp).read().strip() if os.path.exists(fp) else "(no worktree)"
    RESULTS[tag] = {"executed": ran, "content": content, "rc": r.returncode}
    print(f"\n  [{tag}] {label}")
    print(f"      child env  : {sorted(envd)}")
    print(f"      PATH       : {envd.get('PATH', '(ABSENT)')!r}")
    print(f"      repo cfg   : filter.z18.smudge = {smudge!r}")
    print(f"      displaced  : {list(displaced)!r}")
    print(f"      argv[0]    : {argv[0]!r}  (absolute={os.path.isabs(argv[0])})")
    print(f"      -> rc={r.returncode}  filter_EXECUTED={ran}  f.txt={content!r}")
    for lineno, line in enumerate(r.stderr.strip().splitlines()):
        print(f"      stderr[{lineno}]: {line}")
    if expect is not None:
        print(f"      EXPECTED filter_EXECUTED={expect}  ->  "
              f"{'AS EXPECTED' if ran == expect else '*** UNEXPECTED ***'}")
    subprocess.run([GIT, "worktree", "remove", "--force", d], cwd=ROOT,
                   env=ADMIN, capture_output=True)
    return ran, content


print("\n=== 2. THE LEGS ===")

leg("A", "POSITIVE CONTROL — hostile PATH admitted, built-ins-only shim",
    {**ALLOWLIST, "PATH": BIN}, "z18filter", expect=True)

leg("A2", "POSITIVE CONTROL 2 — hostile PATH admitted, MEASURED-ABSOLUTE shim "
          "(pass-through: marker is the only signal)",
    {**ALLOWLIST, "PATH": BIN}, "z18filter_abs", expect=True)

leg("B", "PATH admitted but ORDINARY (shim not on it) — resolution is "
         "PATH-directed",
    {**ALLOWLIST, "PATH": os.environ["PATH"]}, "z18filter", expect=False)

leg("C", "DEFENDED CONTROL — final child env (allowlist, NO PATH) + absolute "
         "git executable",
    dict(ALLOWLIST), "z18filter", expect=False)

print("\n  --- boundary legs: what dropping PATH does NOT close ---")

leg("D", "allowlist (NO PATH), but repo config names the shim by ABSOLUTE PATH",
    dict(ALLOWLIST), SHIM_A)

leg("E", "allowlist (NO PATH), repo config CLEAN, but a DISPLACED argv element "
         "injects the filter before the pin block (ZI-71 scenario)",
    dict(ALLOWLIST), None,
    displaced=("-c", f"filter.z18.smudge={SHIM_A}", "-c", "filter.z18.required=false"))

# --------------------------------------------------------------- T-40 leg
print("\n=== 3. T-40 — can `git` be invoked WITHOUT PATH, and why? ===")
nogit = tempfile.mkdtemp(prefix="z18nogit.")
saved_path = os.environ.get("PATH")
try:
    for desc, pv in (("parent PATH = a dir with NO git", nogit),
                     ("parent PATH = '' (empty string)", "")):
        os.environ["PATH"] = pv
        try:
            rr = subprocess.run(["git", "--version"], cwd=ROOT,
                                env=dict(ALLOWLIST), capture_output=True, text=True)
            res = f"rc={rr.returncode} {rr.stdout.strip()}"
        except FileNotFoundError as ex:
            res = f"FileNotFoundError({ex.strerror})"
        print(f"  bare argv[0]='git', {desc:34s} -> {res}")
finally:
    if saved_path is not None:
        os.environ["PATH"] = saved_path
rr = subprocess.run([GIT, "--version"], cwd=ROOT, env=dict(ALLOWLIST),
                    capture_output=True, text=True)
print(f"  absolute argv[0]={GIT!r}, child env has NO PATH -> rc={rr.returncode} "
      f"{rr.stdout.strip()}")
print(f"  git inside os.defpath ({os.defpath!r})? "
      f"{os.path.dirname(GIT) in os.defpath.split(os.pathsep)}")
print("  READ THIS AS: bare-`git` invocation survives an absent PATH only")
print("  because git happens to live inside os.defpath on THIS host. That is")
print("  a host property, not a guarantee -- hence T-40 (resolve the binary to")
print("  an absolute path once at start-up) rather than 'admit PATH'.")

# --------------------------------------------------------------- verdict
print("\n=== 4. VERDICT ===")
A = RESULTS["A"]
A2 = RESULTS["A2"]
C = RESULTS["C"]
pos_ok = A["executed"] and A["content"] == "HOSTILE_SMUDGE_RAN"
pos2_ok = A2["executed"] and A2["content"] == "payload"
def_ok = (not C["executed"]) and C["content"] == "payload" and C["rc"] == 0
print(f"  POSITIVE CONTROL A  : executed={A['executed']} content={A['content']!r} "
      f"-> {'FIRED' if pos_ok else '*** DID NOT FIRE ***'}")
print(f"  POSITIVE CONTROL A2 : executed={A2['executed']} content={A2['content']!r} "
      f"-> {'FIRED' if pos2_ok else '*** DID NOT FIRE ***'}")
print(f"  DEFENDED CONTROL C  : executed={C['executed']} content={C['content']!r} "
      f"rc={C['rc']} -> {'HELD' if def_ok else '*** BREACHED ***'}")
print(f"  BOUNDARY D (absolute-path smudge, no PATH) : "
      f"executed={RESULTS['D']['executed']} content={RESULTS['D']['content']!r}")
print(f"  BOUNDARY E (displaced argv, no PATH)       : "
      f"executed={RESULTS['E']['executed']} content={RESULTS['E']['content']!r}")

shutil.rmtree(ROOT, ignore_errors=True)
shutil.rmtree(BIN, ignore_errors=True)
shutil.rmtree(HOOKS, ignore_errors=True)
shutil.rmtree(nogit, ignore_errors=True)
shutil.rmtree(STATE, ignore_errors=True)

if not pos_ok:
    print("\n*** CONTROL FAILURE: the positive control did not fire. This "
          "experiment proves NOTHING about PATH and MUST NOT be cited. ***")
    sys.exit(2)
if not pos2_ok:
    print("\n*** CONTROL FAILURE: the second positive control did not fire. ***")
    sys.exit(2)
if not def_ok:
    print("\n*** DEFENDED LEG BREACHED: report as a finding, do not soften. ***")
    sys.exit(3)
print("\nBOTH LEGS DEMONSTRATED: positive control fired; defended control held.")
