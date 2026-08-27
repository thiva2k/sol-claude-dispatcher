#!/usr/bin/env python3
"""EXP 2 — sweep every GIT_* name in the 2.43 binary against the nine permitted
rows, under (A) the revision-7 DENYLIST and (B) an ALLOWLIST child environment.

For each name a value is chosen by class so the variable has a CHANCE to act:
paths point at crafted files, commands point at a marker-touching shim,
booleans are "1". A name is scored EFFECT if any row's rc or stdout differs from
golden, or if the shim marker appears.

The allowlist column is trivially all-inert BY CONSTRUCTION; it is printed to
show that the property is obtained WITHOUT NAMING ANY MEMBER. The load-bearing
column is the denylist one.
"""
import os, sys, subprocess, tempfile, shutil, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rows import Fixture, ROWS, compare, run, GIT

fx = Fixture()
SCRATCH = tempfile.mkdtemp(prefix="z17sweep.")
MARK = os.path.join(SCRATCH, "MARKER")
SHIM = os.path.join(SCRATCH, "shim.sh")
open(SHIM, "w").write(f'#!/bin/sh\ntouch "{MARK}"\nexec /bin/true "$@"\n')
os.chmod(SHIM, 0o755)

# ---- crafted payload files ---------------------------------------------------
GRAFT = os.path.join(SCRATCH, "graftfile")
open(GRAFT, "w").write(f"{fx.base} {fx.decoy}\n")
SHALLOW = os.path.join(SCRATCH, "shallowfile")
open(SHALLOW, "w").write(f"{fx.base}\n")
CFGFILE = os.path.join(SCRATCH, "poison.cfg")
open(CFGFILE, "w").write("[core]\n\tcommitGraph = true\n[z17]\n\tpoison = HIT\n")
ATTRFILE = os.path.join(SCRATCH, "poison.attr")
open(ATTRFILE, "w").write("* diff=z17\n")
ALTDIR = tempfile.mkdtemp(prefix="z17alt.")
EMPTYDIR = tempfile.mkdtemp(prefix="z17empty.")
OTHER = tempfile.mkdtemp(prefix="z17other.")
subprocess.run([GIT, "init", "-q", "-b", "main", "."], cwd=OTHER,
               env=fx.child_env(dict(os.environ)), capture_output=True)

PATHISH = {
    "GIT_GRAFT_FILE": GRAFT, "GIT_SHALLOW_FILE": SHALLOW,
    "GIT_CONFIG": CFGFILE, "GIT_CONFIG_SYSTEM": CFGFILE, "GIT_CONFIG_GLOBAL": CFGFILE,
    "GIT_ATTR_SYSTEM": ATTRFILE, "GIT_ATTR_GLOBAL": ATTRFILE,
    "GIT_DIR": os.path.join(OTHER, ".git"), "GIT_WORK_TREE": OTHER,
    "GIT_COMMON_DIR": os.path.join(OTHER, ".git"), "GIT_COMMONDIR": os.path.join(OTHER, ".git"),
    "GIT_INDEX_FILE": os.path.join(SCRATCH, "idx"),
    "GIT_OBJECT_DIRECTORY": os.path.join(OTHER, ".git", "objects"),
    "GIT_ALTERNATE_OBJECT_DIRECTORIES": os.path.join(OTHER, ".git", "objects"),
    "GIT_CEILING_DIRECTORIES": "/tmp", "GIT_TEMPLATE_DIR": EMPTYDIR,
    "GIT_EXEC_PATH": EMPTYDIR, "GIT_TEXTDOMAINDIR": EMPTYDIR,
    "GIT_QUARANTINE_PATH": EMPTYDIR, "GIT_PROJECT_ROOT": OTHER,
    "GIT_REPLACE_REF_BASE": "refs/z17replace",
}
CMDISH = ("SSH", "ASKPASS", "PAGER", "EDITOR", "PROXY_COMMAND", "EXTERNAL_DIFF",
          "DIFFTOOL", "DIFF_TOOL", "MERGETOOL", "SEQUENCE_EDITOR", "MAN_VIEWER",
          "SHELL_PATH", "SSH_COMMAND", "TRACE")

def value_for(name):
    if name in PATHISH:
        return PATHISH[name]
    if name.endswith("_") or name in ("GIT_AUTHOR_", "GIT_CONFIG_KEY_",
                                      "GIT_CONFIG_VALUE_", "GIT_PUSH_OPTION_"):
        return None                       # prefix stub, not a real variable
    if name == "GIT_CONFIG_COUNT":
        return None                       # handled as a triple below
    if name == "GIT_CONFIG_PARAMETERS":
        return "'core.commitGraph=true' 'z17.poison=HIT'"
    if name == "GIT_NAMESPACE":
        return "z17ns"
    if any(t in name for t in CMDISH):
        return SHIM
    if name.startswith("GIT_TRACE"):
        return os.path.join(SCRATCH, "trace.out")
    return "1"

DENY_STRIP = ("GIT_DIR","GIT_WORK_TREE","GIT_COMMON_DIR","GIT_INDEX_FILE",
              "GIT_OBJECT_DIRECTORY","GIT_ALTERNATE_OBJECT_DIRECTORIES",
              "GIT_CEILING_DIRECTORIES","GIT_NAMESPACE")
DENY_SCRUB = ("GIT_CONFIG_COUNT","GIT_CONFIG_PARAMETERS","GIT_EXTERNAL_DIFF",
              "GIT_SSH","GIT_SSH_COMMAND","GIT_ASKPASS","GIT_PAGER","GIT_ATTR_NOSYSTEM")
DENY_PREFIX = ("GIT_CONFIG_KEY_","GIT_CONFIG_VALUE_","GIT_TEST_")
SET = {"GIT_NO_LAZY_FETCH":"1","GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1",
       "GIT_CONFIG_GLOBAL":"/dev/null","GIT_TERMINAL_PROMPT":"0","GIT_OPTIONAL_LOCKS":"0"}

def denylisted(name):
    return (name in DENY_STRIP or name in DENY_SCRUB
            or any(name.startswith(p) for p in DENY_PREFIX))

def denylist_env(parent):
    """Revision 7's _git_env(): inherit everything, strip 8, scrub the list, set 6."""
    e = dict(parent)
    for k in DENY_STRIP: e.pop(k, None)
    for k in DENY_SCRUB: e.pop(k, None)
    for k in list(e):
        if any(k.startswith(p) for p in DENY_PREFIX): e.pop(k, None)
    e.update(SET)
    return e

def allowlist_env(parent, allow=()):
    """Sol's ruling: construct from a fixed allowlist. NO ambient GIT_* survives."""
    e = {k: parent[k] for k in allow if k in parent}
    e.update(SET)
    return e

def probe(envd):
    """Run all nine rows; return (changed_rows, marker_fired)."""
    if os.path.exists(MARK): os.unlink(MARK)
    changed = []
    for n, _ in ROWS:
        ok, det = compare(fx, n, envd)
        if not ok: changed.append(f"{n}:{det[:40]}")
    return changed, os.path.exists(MARK)

names = [l.strip() for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              "allgit.txt")) if l.strip()]
print(f"Sweeping {len(names)} GIT_* names from the 2.43 binary.\n")

# sanity: golden must be reproducible
c, _ = probe(denylist_env({}))
print(f"SANITY (no ambient vars at all): changed rows = {c or 'none'}  "
      f"{'OK' if not c else '*** HARNESS UNSTABLE ***'}\n")

results = []
for name in names:
    val = value_for(name)
    if val is None:
        results.append((name, "skip", "prefix stub / handled separately", False, False))
        continue
    parent = {name: val}
    d_changed, d_mark = probe(denylist_env(parent))
    a_changed, a_mark = probe(allowlist_env(parent, allow=("PATH","HOME","LANG","TMPDIR")))
    results.append((name, val, d_changed, d_mark, (a_changed, a_mark)))

print("=== NAMES WITH A MEASURED EFFECT UNDER THE REVISION-7 DENYLIST ===")
hits = [r for r in results if r[1] != "skip" and (r[2] or r[3])]
for name, val, d_changed, d_mark, a in hits:
    tag = "DENYLISTED" if denylisted(name) else "*** MISSED BY DENYLIST ***"
    ac, am = a
    print(f"  {name:42s} {tag}")
    print(f"      denylist child: rows_changed={d_changed or '-'} exec_marker={d_mark}")
    print(f"      allowlist child: rows_changed={ac or 'NONE'} exec_marker={am}")

print(f"\n  total names with an effect under the denylist: {len(hits)}")
missed = [h[0] for h in hits if not denylisted(h[0])]
print(f"  of those, NOT covered by the revision-7 denylist: {len(missed)}")
for m in missed: print(f"      MISSED: {m}")

print("\n=== ALLOWLIST COLUMN, WHOLE SWEEP ===")
anyeff = [r[0] for r in results if r[1] != "skip" and (r[4][0] or r[4][1])]
print(f"  names with ANY effect through the allowlist: {anyeff or 'ZERO (all 220 inert)'}")

json.dump({"hits": [(h[0], h[2], h[3], denylisted(h[0])) for h in hits],
           "missed": missed, "allow_effect": anyeff},
          open("/tmp/z17_exp2.json","w"), indent=1)
print(f"\nfixture={fx.root} scratch={SCRATCH}")
