#!/usr/bin/env bash
# Z7 PROBE 2a -- does the raw parser AGREE with git on HEALTHY repos?
# Covers: main worktree (.git dir), linked worktree (.git file), bare+worktree,
# relative gitfile, packed HEAD, detached HEAD, submodule .git file.
set -u
RA=/home/dev/sol-claude-dispatcher/probes/z7/rawadmin.py
W=$(mktemp -d /tmp/z7agree.XXXXXX); cd "$W"
pass=0; fail=0
chk() { # chk <label> <worktree> 
  local lbl=$1 wt=$2
  local g_top g_gd g_cd g_head
  g_top=$(git -C "$wt" rev-parse --show-toplevel 2>&1)
  g_gd=$(git -C "$wt" rev-parse --absolute-git-dir 2>&1)
  g_cd=$(cd "$wt" && git rev-parse --path-format=absolute --git-common-dir 2>&1)
  g_head=$(git -C "$wt" rev-parse --verify HEAD 2>&1 || echo NONE)
  local r
  r=$(python3 "$RA" "$wt" 2>&1) || { echo "  $lbl: PARSER-ERROR: $r"; fail=$((fail+1)); return; }
  local r_top r_gd r_cd r_head
  r_top=$(echo "$r" | python3 -c 'import json,sys;print(json.load(sys.stdin)["toplevel"])')
  r_gd=$(echo "$r" | python3 -c 'import json,sys;print(json.load(sys.stdin)["gitdir"])')
  r_cd=$(echo "$r" | python3 -c 'import json,sys;print(json.load(sys.stdin)["commondir"])')
  r_head=$(echo "$r" | python3 -c 'import json,sys;print(json.load(sys.stdin)["head_oid"])')
  local ok=1
  [ "$(realpath "$g_top")" = "$(realpath "$r_top")" ] || { ok=0; echo "  $lbl TOPLEVEL git=$g_top raw=$r_top"; }
  [ "$(realpath "$g_gd")"  = "$(realpath "$r_gd")"  ] || { ok=0; echo "  $lbl GITDIR   git=$g_gd raw=$r_gd"; }
  [ "$(realpath "$g_cd")"  = "$(realpath "$r_cd")"  ] || { ok=0; echo "  $lbl COMMON   git=$g_cd raw=$r_cd"; }
  [ "$g_head" = "$r_head" ] || { ok=0; echo "  $lbl HEAD     git=$g_head raw=$r_head"; }
  if [ $ok = 1 ]; then echo "  AGREE   $lbl"; pass=$((pass+1)); else echo "  DISAGREE $lbl"; fail=$((fail+1)); fi
}

# 1. plain repo, .git is a directory
git init -q main; cd main; git config user.email z@p; git config user.name z
echo a > a.txt; git add -A; git commit -qm one; echo b > b.txt; git add -A; git commit -qm two
cd "$W"; chk "main-worktree(.git dir)" "$W/main"

# 2. linked worktree, .git is a FILE with absolute gitdir
git -C main worktree add -q "$W/wt1" -b br1 >/dev/null 2>&1
chk "linked-worktree(.git file)" "$W/wt1"

# 3. detached-HEAD linked worktree
OID=$(git -C main rev-parse HEAD)
git -C main worktree add -q --detach "$W/wt2" "$OID" >/dev/null 2>&1
chk "linked-worktree(detached)" "$W/wt2"

# 4. RELATIVE gitfile (git supports it; rewrite by hand)
cp -r wt1 wt1rel
python3 - <<PY
import os,pathlib
p=pathlib.Path("$W/wt1rel/.git")
gd=p.read_text().split("gitdir: ",1)[1].strip()
rel=os.path.relpath(gd, "$W/wt1rel")
p.write_text("gitdir: %s\n"%rel)
PY
chk "linked-worktree(RELATIVE gitfile)" "$W/wt1rel"

# 5. packed refs only
git -C main pack-refs --all
chk "main-worktree(packed-refs)" "$W/main"
chk "linked-worktree(packed-refs)" "$W/wt1"

# 6. separate-gitdir main worktree (.git file at top level, NOT a linked wt)
git init -q --separate-git-dir="$W/sepgit" sep >/dev/null 2>&1
cd sep; git config user.email z@p; git config user.name z; echo x>x; git add -A; git commit -qm s; cd "$W"
chk "separate-git-dir(.git file, no commondir)" "$W/sep"

# 7. worktree of a BARE repo
git clone -q --bare main bare.git
git -C bare.git worktree add -q "$W/bwt" >/dev/null 2>&1
chk "worktree-of-bare-repo" "$W/bwt"

echo "AGREEMENT: pass=$pass fail=$fail"
echo "WORKDIR=$W"
