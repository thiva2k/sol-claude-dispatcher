#!/usr/bin/env bash
# Z7 PROBE 2c -- the rows PROBE 2b could not have detected, plus the two
# questions Sol's mitigation list depends on.
set -u
RA=/home/dev/sol-claude-dispatcher/probes/z7/rawadmin.py
W=$(mktemp -d /tmp/z7p2c.XXXXXX)

build() {
  rm -rf "$W/real" "$W/fake" "$W/task"
  git init -q "$W/real"; git -C "$W/real" config user.email z@p; git -C "$W/real" config user.name z
  echo REAL-CONTENT > "$W/real/marker.txt"; git -C "$W/real" add -A; git -C "$W/real" commit -qm r1
  echo more >> "$W/real/marker.txt"; git -C "$W/real" add -A; git -C "$W/real" commit -qm r2
  git -C "$W/real" worktree add -q "$W/task" -b task >/dev/null 2>&1
  git init -q "$W/fake"; git -C "$W/fake" config user.email z@p; git -C "$W/fake" config user.name z
  echo ATTACKER-CONTENT > "$W/fake/marker.txt"; echo planted > "$W/fake/planted.txt"
  git -C "$W/fake" add -A; git -C "$W/fake" commit -qm f1
  REAL_OID=$(git -C "$W/real" rev-parse HEAD); FAKE_OID=$(git -C "$W/fake" rev-parse HEAD)
  REAL_ROOT=$(git -C "$W/real" rev-list --max-parents=0 HEAD)
  FAKE_ROOT=$(git -C "$W/fake" rev-list --max-parents=0 HEAD)
  GITDIR="$W/real/.git/worktrees/task"
  python3 "$RA" "$W/task" > "$W/seal.json"
}
# copy fake objects INTO the real store -- no alternates involved
transplant() {
  git -C "$W/fake" rev-list --objects --all | awk '{print $1}' | \
    git -C "$W/fake" pack-objects --stdout -q > "$W/t.pack" 2>/dev/null
  git -C "$W/real" unpack-objects -q < "$W/t.pack" 2>/dev/null || \
    git -C "$W/real" index-pack --stdin < "$W/t.pack" >/dev/null 2>&1
}
row() { # row <label>
  local lbl=$1 head ls blob root top agd gcd
  head=$(git -C "$W/task" rev-parse --verify 'HEAD^{commit}' 2>&1)
  root=$(git -C "$W/task" rev-list --max-parents=0 HEAD 2>&1 | tr '\n' ' ')
  ls=$(git -C "$W/task" ls-tree -r --name-only HEAD 2>&1 | tr '\n' ',')
  blob=$(git -C "$W/task" show 'HEAD:marker.txt' 2>&1 | head -1)
  top=$(git -C "$W/task" rev-parse --show-toplevel 2>&1)
  agd=$(git -C "$W/task" rev-parse --absolute-git-dir 2>&1)
  gcd=$(cd "$W/task" && git rev-parse --path-format=absolute --git-common-dir 2>&1)
  local eff=""
  [ "$head" = "$FAKE_OID" ] && eff="$eff head"
  [ "${root% }" = "$FAKE_ROOT" ] && eff="$eff ROOT"
  [[ "$blob" == *ATTACKER* ]] && eff="$eff blob"
  [[ "$ls" == *planted* ]] && eff="$eff tree"
  [ -z "$eff" ] && eff=" NONE"
  local rp="LEGIT"
  [ "$(realpath "$top" 2>/dev/null)" = "$(realpath "$W/task")" ] || rp="top=$top"
  [ "$(realpath "$agd" 2>/dev/null)" = "$(realpath "$GITDIR")" ] || rp="$rp agd=$agd"
  [ "$(realpath "$gcd" 2>/dev/null)" = "$(realpath "$W/real/.git")" ] || rp="$rp gcd=$gcd"
  python3 - "$W/seal.json" "$W/task" <<'PY' > "$W/raw.txt" 2>&1
import json,sys
sys.path.insert(0,"/home/dev/sol-claude-dispatcher/probes/z7"); import rawadmin
seal=json.load(open(sys.argv[1]))
try: now=rawadmin.resolve(sys.argv[2])
except Exception as e: print("RAW-REFUSE:%s"%e); raise SystemExit
d=[k for k,v in seal["identity_files"].items()
   if not k.startswith("_") and now["identity_files"].get(k,"GONE")!=v]
for f in ("gitdir","commondir","head_oid"):
    if seal.get(f)!=now.get(f): d.append(f)
if [s["path"] for s in seal["object_stores"]]!=[s["path"] for s in now["object_stores"]]:
    d.append("object_stores")
print(("RAW-DETECT["+",".join(d)+"]") if d else "RAW-CLEAN")
PY
  printf '%-34s EFFECT=%-24s REVPARSE=%-10s %s\n' "$lbl" "$eff" "$rp" "$(cat "$W/raw.txt")"
  printf '%-34s   head=%s root=%s blob=%s\n\n' "" "${head:0:12}" "${root:0:12}" "${blob:0:20}"
}

build; row "0-BASELINE"

# H: does deleting alternates close it?  Objects transplanted into REAL store.
build; transplant; printf '%s\n' "$FAKE_OID" > "$GITDIR/HEAD"
row "H-transplant+HEAD (NO alternates)"

# H2: same, but ALSO delete any alternates file (Sol/F-5 mitigation #4)
rm -f "$W/real/.git/objects/info/alternates"
row "H2-H + alternates DELETED"

# D': refs/replace with objects already in the real store
build; transplant
mkdir -p "$W/real/.git/refs/replace"; printf '%s\n' "$FAKE_OID" > "$W/real/.git/refs/replace/$REAL_OID"
row "D2-refs/replace (NO alternates)"

# D3: replace the TREE only -- HEAD commit oid stays byte-identical
build; transplant
FAKE_TREE=$(git -C "$W/fake" rev-parse 'HEAD^{tree}'); REAL_TREE=$(git -C "$W/real" rev-parse 'HEAD^{tree}')
mkdir -p "$W/real/.git/refs/replace"; printf '%s\n' "$FAKE_TREE" > "$W/real/.git/refs/replace/$REAL_TREE"
row "D3-refs/replace TREE only"

# E': grafts, with the ROOT-COMMIT detector armed
build; transplant
mkdir -p "$W/real/.git/info"; printf '%s %s\n' "$REAL_OID" "$FAKE_OID" > "$W/real/.git/info/grafts"
row "E2-info/grafts (root armed)"

# E3: refs/replace used to change PARENTAGE -> root commit identity
build; transplant
NEWC=$(git -C "$W/real" commit-tree "$(git -C "$W/real" rev-parse 'HEAD^{tree}')" -p "$FAKE_OID" -m x 2>/dev/null)
mkdir -p "$W/real/.git/refs/replace"; printf '%s\n' "$NEWC" > "$W/real/.git/refs/replace/$REAL_OID"
row "E3-replace reparent (root armed)"

# I: is a LEGITIMATE core.worktree a false positive for the raw parser?
build
git -C "$W/real" config extensions.worktreeConfig true
mkdir -p "$W/altwt"; cp "$W/task/marker.txt" "$W/altwt/" 2>/dev/null
printf '[core]\n\tworktree = %s\n' "$W/altwt" > "$GITDIR/config.worktree"
echo "  git --show-toplevel : $(git -C "$W/task" rev-parse --show-toplevel 2>&1)"
echo "  raw   toplevel      : $(python3 $RA "$W/task" 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin)["toplevel"])')"
echo
echo "WORKDIR=$W"
