#!/usr/bin/env python3
"""EXP 7 — which variables must the dispatcher INSERT explicitly, given that the
allowlist admits nothing? Each is kept only if removing it is MEASURED to change
behaviour.
"""
import os, sys, subprocess, tempfile, shutil, pwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rows import Fixture, ROWS, compare, run, pin_block, GIT

fx = Fixture()
S = tempfile.mkdtemp(prefix="z17e7.")
SET = {"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1",
       "GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0","GIT_OPTIONAL_LOCKS":"0"}

print("=== A — LEAVE-ONE-OUT over the six dispatcher-owned insertions ===")
print("    (does removing the insertion change any of the nine permitted rows?)")
for k in SET:
    e = {x:v for x,v in SET.items() if x != k}
    bad = [n for n,_ in ROWS if not compare(fx,n,e)[0]]
    print(f"  -{k:24s} rows changed: {bad or 'none'}")

print("\n=== B — is GIT_CONFIG_GLOBAL still load-bearing when HOME is NOT admitted? ===")
print("    git falls back to getpwuid() for the home directory when HOME is unset.")
real_home = pwd.getpwuid(os.getuid()).pw_dir
print(f"    getpwuid(uid).pw_dir = {real_home}")
fake = tempfile.mkdtemp(prefix="z17home.")
open(os.path.join(fake,".gitconfig"),"w").write("[z17]\n\tglobalhit = YES\n")
for label, e in (
    ("HOME admitted, GIT_CONFIG_GLOBAL=/dev/null", {**SET, "HOME": fake}),
    ("HOME admitted, NO GIT_CONFIG_GLOBAL",
        {**{k:v for k,v in SET.items() if k!='GIT_CONFIG_GLOBAL'}, "HOME": fake}),
    ("HOME DENIED,   NO GIT_CONFIG_GLOBAL",
        {k:v for k,v in SET.items() if k!='GIT_CONFIG_GLOBAL'}),
    ("HOME DENIED,   GIT_CONFIG_GLOBAL=/dev/null", dict(SET)),
):
    r = run(["config","--get","z17.globalhit"], fx.root, e)
    r2 = run(["config","--show-origin","--get-all","user.email"], fx.root, e)
    print(f"  {label:44s} z17.globalhit rc={r.returncode} {r.stdout.strip()!r}"
          f"   origins={r2.stdout.strip()[:46]!r}")
print("  CONTROL: the 'HOME admitted, NO GIT_CONFIG_GLOBAL' leg MUST return YES,")
print("  or this whole block proves nothing.")

print("\n  Does git read the REAL home's ~/.gitconfig when HOME is denied?")
real_cfg = os.path.join(real_home, ".gitconfig")
print(f"    {real_cfg} exists: {os.path.exists(real_cfg)}")
if os.path.exists(real_cfg):
    keys = subprocess.run([GIT,"config","-f",real_cfg,"--list"],capture_output=True,
                          text=True).stdout.strip().splitlines()
    probe_key = keys[0].split("=")[0] if keys else None
    print(f"    a key that exists ONLY there: {probe_key}")
    if probe_key:
        for label, e in (("HOME denied, NO GIT_CONFIG_GLOBAL",
                          {k:v for k,v in SET.items() if k!='GIT_CONFIG_GLOBAL'}),
                         ("HOME denied, GIT_CONFIG_GLOBAL=/dev/null", dict(SET))):
            r = run(["config","--get",probe_key], fx.root, e)
            print(f"    {label:42s} rc={r.returncode} {r.stdout.strip()[:40]!r}")

print("\n=== C — GIT_CONFIG_NOSYSTEM vs an /etc/gitconfig that does not exist here ===")
print(f"  /etc/gitconfig exists: {os.path.exists('/etc/gitconfig')}")
sysfile = os.path.join(S,"sys.cfg"); open(sysfile,"w").write("[z17]\n\tsyshit = YES\n")
for label, e in (("GIT_CONFIG_SYSTEM=<file>, NOSYSTEM unset",
                  {**{k:v for k,v in SET.items() if k!='GIT_CONFIG_NOSYSTEM'},
                   "GIT_CONFIG_SYSTEM": sysfile}),
                 ("GIT_CONFIG_SYSTEM=<file> + GIT_CONFIG_NOSYSTEM=1",
                  {**SET, "GIT_CONFIG_SYSTEM": sysfile}),
                 ("allowlist child (GIT_CONFIG_SYSTEM cannot arrive)", dict(SET))):
    r = run(["config","--get","z17.syshit"], fx.root, e)
    print(f"  {label:52s} rc={r.returncode} {r.stdout.strip()!r}")

print("\n=== D — GIT_TERMINAL_PROMPT / GIT_OPTIONAL_LOCKS: measured necessity ===")
print("  GIT_TERMINAL_PROMPT=0 guards a HANG, not an output change, so a row-diff")
print("  cannot see it. Measured by whether a credential prompt is attempted:")
askpass = os.path.join(S,"ask"); MARK=os.path.join(S,"ASKED")
open(askpass,"w").write(f'#!/bin/sh\ntouch "{MARK}"\necho x\n'); os.chmod(askpass,0o755)
for label, e in (("GIT_TERMINAL_PROMPT unset", {k:v for k,v in SET.items()
                                                if k!='GIT_TERMINAL_PROMPT'}),
                 ("GIT_TERMINAL_PROMPT=0", dict(SET))):
    if os.path.exists(MARK): os.unlink(MARK)
    r = subprocess.run([GIT,"ls-remote","https://127.0.0.1:1/x"],cwd=fx.root,
        env={**e,"GIT_ASKPASS":askpass},capture_output=True,text=True,timeout=30)
    print(f"  {label:30s} rc={r.returncode} askpass_invoked={os.path.exists(MARK)} "
          f"{r.stderr.strip().splitlines()[-1][:40] if r.stderr.strip() else ''}")
print("  NOTE: no permitted row contacts a remote. GIT_TERMINAL_PROMPT=0 is a")
print("  BELT-AND-BRACES insertion against a row that should never occur; it")
print("  earns its place as a hang-guard, NOT as a measured behaviour change on")
print("  the nine rows. Reported as such rather than as a measured necessity.")

print("\n=== E — the ownership / safe.directory consequence of the pins ===")
print("  GIT_CONFIG_NOSYSTEM=1 + GIT_CONFIG_GLOBAL=/dev/null means NO safe.directory")
print("  entry can be read. If the target repository is owned by a DIFFERENT uid,")
print("  every permitted row refuses. Measured on a repo this lane owns:")
st = os.stat(os.path.join(fx.root,".git"))
print(f"    fixture .git owner uid={st.st_uid}, process uid={os.getuid()}  -> same")
r = run(pin_block(fx.hooks)+["rev-parse","--absolute-git-dir"], fx.root, dict(SET))
print(f"    rc={r.returncode} (same-owner case passes)")
print("    DIFFERENT-owner case: NOT ATTEMPTED — it needs a second uid, which")
print("    requires root on this host. Recorded as an OWED measurement, not as a")
print("    clean row. It is a property of the PINS, not of the allowlist, and it")
print("    is unchanged by Sol's ruling.")
print(f"\nfixture={fx.root}")
