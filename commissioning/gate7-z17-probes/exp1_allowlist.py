#!/usr/bin/env python3
"""EXP 1 — construct the allowlist empirically from env -i upward."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rows import Fixture, ROWS, compare

fx = Fixture()
print(f"FIXTURE root={fx.root}\n  ext-worktree={fx.wt}\n  base={fx.base}\n"
      f"  trueroot={fx.trueroot}  decoy={fx.decoy}\n")

DISPATCHER_PINS = {
    "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
}

amb = os.environ
CANDIDATES = {
    "PATH": amb.get("PATH", "/usr/bin:/bin"),
    "HOME": amb.get("HOME", "/home/dev"),
    "LANG": amb.get("LANG", "C.UTF-8"),
    "LC_ALL": "C.UTF-8",
    "TMPDIR": "/tmp",
    "USER": amb.get("USER", "dev"),
    "LOGNAME": amb.get("LOGNAME", "dev"),
    "TZ": "UTC",
    "SHELL": amb.get("SHELL", "/bin/bash"),
    "TERM": amb.get("TERM", "xterm"),
    "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt",
    "SSL_CERT_DIR": "/etc/ssl/certs",
    "XDG_CONFIG_HOME": amb.get("XDG_CONFIG_HOME", "/home/dev/.config"),
    "XDG_RUNTIME_DIR": amb.get("XDG_RUNTIME_DIR", "/run/user/1000"),
    "PWD": fx.root,
}

def env_of(names, extra=None):
    e = {k: CANDIDATES[k] for k in names}
    e.update(DISPATCHER_PINS)
    if extra: e.update(extra)
    return e

def sweep(names, label):
    print(f"\n=== {label} ===")
    print(f"    vars: {sorted(names) or '(NONE — env -i + pins only)'}")
    e = env_of(names)
    allok = True
    for n, desc in ROWS:
        ok, detail = compare(fx, n, e)
        allok &= ok
        print(f"  {'PASS' if ok else 'FAIL'}  {n:7s} {desc:38s} {'' if ok else detail}")
    return allok

# --- STEP A: absolutely empty (env -i) + only the dispatcher-owned pins -------
sweep(set(), "STEP A — env -i + dispatcher pins ONLY (zero inherited vars)")

# --- STEP B: full candidate set (upper bound) --------------------------------
allnames = set(CANDIDATES)
full_ok = sweep(allnames, "STEP B — ALL candidates (upper bound; must be all PASS)")
if not full_ok:
    print("\n!!! CONTROL FAILURE: the upper-bound set does not pass. "
          "Every ablation below would be uninterpretable. STOPPING.")
    fx.cleanup(); sys.exit(2)

# --- STEP C: leave-one-out ablation -------------------------------------------
print("\n=== STEP C — LEAVE-ONE-OUT from the full candidate set ===")
print("   (a variable earns the allowlist ONLY if removing it breaks a row)")
necessary = {}
for cand in sorted(CANDIDATES):
    e = env_of(allnames - {cand})
    broken = []
    for n, _ in ROWS:
        ok, detail = compare(fx, n, e)
        if not ok:
            broken.append((n, detail))
    if broken:
        necessary[cand] = broken
        print(f"  NECESSARY   -{cand:16s} breaks: " +
              "; ".join(f"{n}({d})" for n, d in broken))
    else:
        print(f"  not needed  -{cand:16s} all 9 rows still identical")

print("\n--- leave-one-out verdict ---")
print(f"  necessary by single ablation: {sorted(necessary) or '(NONE)'}")

# --- STEP D: additive build-up from empty -------------------------------------
print("\n=== STEP D — ADDITIVE: does any single variable rescue a broken row? ===")
base_fail = {}
e0 = env_of(set())
for n, _ in ROWS:
    ok, d = compare(fx, n, e0)
    if not ok: base_fail[n] = d
print(f"  rows failing under env -i: {sorted(base_fail) or '(none)'}")
for cand in sorted(CANDIDATES):
    if not base_fail: break
    e = env_of({cand})
    fixed = [n for n in base_fail if compare(fx, n, e)[0]]
    if fixed:
        print(f"  +{cand:16s} rescues {fixed}")

# --- STEP E: candidate minimal sets -------------------------------------------
print("\n=== STEP E — candidate MINIMAL allowlists ===")
for trial in [set(), {"PATH"}, {"HOME"}, {"PATH","HOME"}, {"PATH","HOME","LANG"},
              {"PATH","HOME","LANG","TMPDIR"},
              {"PATH","HOME","LANG","LC_ALL","TMPDIR","USER","LOGNAME","TZ"}]:
    e = env_of(trial)
    res = [(n, compare(fx, n, e)) for n, _ in ROWS]
    bad = [f"{n}:{d}" for n, (ok, d) in res if not ok]
    print(f"  {sorted(trial) or ['(empty)']}\n      -> {'ALL 9 PASS' if not bad else 'FAIL ' + '; '.join(bad)}")

json.dump({"necessary": {k: [n for n,_ in v] for k,v in necessary.items()},
           "root": fx.root}, open("/tmp/z17_exp1.json","w"))
print(f"\n(fixture retained at {fx.root} for follow-on experiments)")
