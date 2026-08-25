#!/usr/bin/env bash
# Z7 PROBE 2b -- reconstruct S-e and test detection by (i) git path identity
# commands and (ii) the raw-admin parser sealed at PREPARE.
#
# For EVERY variant we record three things:
#   EFFECT   did the permitted read actually return the ATTACKER's data?
#            (positive control: if NO, the experiment could not have detected
#             anything and the row is void, not a negative)
#   REVPARSE do the four path-identity commands still return LEGITIMATE values?
#   RAW      does the sealed raw-admin fingerprint change?
set -u
RA=/home/dev/sol-claude-dispatcher/probes/z7/rawadmin.py
V=${1:-all}
W=$(mktemp -d /tmp/z7pois.XXXXXX)

build() {  # fresh real repo + linked worktree + fake repo
  rm -rf "$W/real" "$W/fake" "$W/task"
  git init -q "$W/real"; git -C "$W/real" config user.email z@p; git -C "$W/real" config user.name z
  echo "REAL-CONTENT" > "$W/real/marker.txt"; echo "real only" > "$W/real/realonly.txt"
  git -C "$W/real" add -A; git -C "$W/real" commit -qm real
  git -C "$W/real" worktree add -q "$W/task" -b task >/dev/null 2>&1

  git init -q "$W/fake"; git -C "$W/fake" config user.email z@p; git -C "$W/fake" config user.name z
  echo "ATTACKER-CONTENT" > "$W/fake/marker.txt"; echo "planted" > "$W/fake/planted.txt"
  git -C "$W/fake" add -A; git -C "$W/fake" commit -qm fake
  REAL_OID=$(git -C "$W/real" rev-parse HEAD)
  FAKE_OID=$(git -C "$W/fake" rev-parse HEAD)
  GITDIR="$W/real/.git/worktrees/task"
  # PREPARE-time seal, taken while still trusted
  python3 "$RA" "$W/task" > "$W/seal.json"
}

report() { # report <label>
  local lbl=$1
  local head ls blob top agd gcd inside
  head=$(git -C "$W/task" rev-parse --verify 'HEAD^{commit}' 2>&1)
  ls=$(git -C "$W/task" ls-tree -r --name-only HEAD 2>&1 | tr '\n' ',')
  blob=$(git -C "$W/task" cat-file --batch <<< "$(git -C "$W/task" rev-parse 'HEAD:marker.txt' 2>/dev/null)" 2>&1 | sed -n 2p)
  top=$(git -C "$W/task" rev-parse --show-toplevel 2>&1)
  agd=$(git -C "$W/task" rev-parse --absolute-git-dir 2>&1)
  gcd=$(cd "$W/task" && git rev-parse --path-format=absolute --git-common-dir 2>&1)
  inside=$(git -C "$W/task" rev-parse --is-inside-work-tree 2>&1)

  local effect="NO"
  [ "$head" = "$FAKE_OID" ] && effect="YES(head)"
  [[ "$blob" == *ATTACKER* ]] && effect="${effect%NO}YES(blob)"
  [[ "$ls" == *planted* ]] && effect="$effect+YES(tree)"

  local rp="LEGIT"
  [ "$(realpath "$top" 2>/dev/null)" = "$(realpath "$W/task")" ] || rp="FOREIGN-toplevel:$top"
  [ "$(realpath "$agd" 2>/dev/null)" = "$(realpath "$GITDIR")" ] || rp="$rp FOREIGN-absgitdir:$agd"
  [ "$(realpath "$gcd" 2>/dev/null)" = "$(realpath "$W/real/.git")" ] || rp="$rp FOREIGN-commondir:$gcd"

  python3 - "$W/seal.json" "$W/task" <<'PY' > "$W/raw.txt" 2>&1
import json,sys,subprocess
sys.path.insert(0,"/home/dev/sol-claude-dispatcher/probes/z7")
import rawadmin
seal=json.load(open(sys.argv[1]))
try: now=rawadmin.resolve(sys.argv[2])
except Exception as e:
    print("RAW-REFUSE:%s"%e); raise SystemExit
d=[]
for k,v in seal["identity_files"].items():
    if k.startswith("_"): continue
    n=now["identity_files"].get(k,"GONE")
    if n!=v: d.append(f"{k}:{v[:8]}->{str(n)[:8]}")
for f in ("gitdir","commondir","head_oid","dotgit_kind","gitfile_raw","commondir_raw"):
    if seal.get(f)!=now.get(f): d.append(f"{f}:{seal.get(f)}->{now.get(f)}")
sp=[s["path"] for s in seal["object_stores"]]; np_=[s["path"] for s in now["object_stores"]]
if sp!=np_: d.append("object_stores:%d->%d %s"%(len(sp),len(np_),[x for x in np_ if x not in sp]))
print(("RAW-DETECT: "+" | ".join(d)) if d else "RAW-CLEAN")
PY
  printf '%-26s EFFECT=%-22s REVPARSE=%s\n' "$lbl" "$effect" "$rp"
  printf '%-26s %s\n' "" "$(cat "$W/raw.txt")"
  echo
}

# ---------------- BASELINE (no poison) -- proves EFFECT can read NO ----------
build; report "0-BASELINE(no poison)"

# ---------------- Variant A: gitfile redirection ----------------------------
build
printf 'gitdir: %s/.git\n' "$W/fake" > "$W/task/.git"
report "A-gitfile->fake"

# ---------------- Variant B: commondir redirection --------------------------
build
printf '%s/.git\n' "$W/fake" > "$GITDIR/commondir"
printf '%s\n' "$FAKE_OID" > "$GITDIR/HEAD"
report "B-commondir->fake"

# ---------------- Variant C: alternates + worktree HEAD (stealth) -----------
build
mkdir -p "$W/real/.git/objects/info"
printf '%s/.git/objects\n' "$W/fake" > "$W/real/.git/objects/info/alternates"
printf '%s\n' "$FAKE_OID" > "$GITDIR/HEAD"
report "C-alternates+HEAD"

# ---------------- Variant C2: alternates only, HEAD untouched ---------------
build
mkdir -p "$W/real/.git/objects/info"
printf '%s/.git/objects\n' "$W/fake" > "$W/real/.git/objects/info/alternates"
report "C2-alternates-only"

# ---------------- Variant D: refs/replace object substitution ---------------
build
FAKE_TREE=$(git -C "$W/fake" rev-parse 'HEAD^{tree}')
# make the fake objects reachable from the real store first
printf '%s/.git/objects\n' "$W/fake" > "$W/real/.git/objects/info/alternates" 2>/dev/null || \
  { mkdir -p "$W/real/.git/objects/info"; printf '%s/.git/objects\n' "$W/fake" > "$W/real/.git/objects/info/alternates"; }
mkdir -p "$W/real/.git/refs/replace"
printf '%s\n' "$FAKE_OID" > "$W/real/.git/refs/replace/$REAL_OID"
report "D-refs/replace"

# ---------------- Variant E: info/grafts ------------------------------------
build
mkdir -p "$W/real/.git/info"
printf '%s %s\n' "$REAL_OID" "$FAKE_OID" > "$W/real/.git/info/grafts"
report "E-info/grafts"

# ---------------- Variant F: http-alternates --------------------------------
build
mkdir -p "$W/real/.git/objects/info"
printf '%s/.git/objects\n' "$W/fake" > "$W/real/.git/objects/info/http-alternates"
printf '%s\n' "$FAKE_OID" > "$GITDIR/HEAD"
report "F-http-alternates"

# ---------------- Variant G: core.worktree in config.worktree ---------------
build
git -C "$W/real" config extensions.worktreeConfig true
printf '[core]\n\tworktree = %s\n' "$W/fake" > "$GITDIR/config.worktree"
report "G-core.worktree"

echo "WORKDIR=$W"
