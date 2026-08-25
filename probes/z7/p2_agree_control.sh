#!/usr/bin/env bash
# Z7 PROBE 2a-CONTROL -- can the agreement harness DISAGREE?
# Installs a deliberately-broken parser (ignores commondir indirection, the
# exact bug the real parser must not have) and reruns one linked-worktree case.
set -u
W=$(mktemp -d /tmp/z7ctl.XXXXXX); cd "$W"
git init -q main; cd main; git config user.email z@p; git config user.name z
echo a>a; git add -A; git commit -qm one; cd "$W"
git -C main worktree add -q "$W/wt1" -b br1 >/dev/null 2>&1

cat > broken.py <<'PY'
import sys,json,os,pathlib
wt=pathlib.Path(sys.argv[1]).resolve()
raw=(wt/".git").read_text()
gd=pathlib.Path(raw.split("gitdir: ",1)[1].strip())
# BUG under test: commondir indirection ignored
print(json.dumps({"toplevel":str(wt),"gitdir":str(gd),"commondir":str(gd),
                  "head_oid":(gd/"HEAD").read_text().strip()}))
PY
for P in /home/dev/sol-claude-dispatcher/probes/z7/rawadmin.py "$W/broken.py"; do
  echo "--- parser: $(basename $P)"
  g_cd=$(cd "$W/wt1" && git rev-parse --path-format=absolute --git-common-dir)
  g_head=$(git -C "$W/wt1" rev-parse --verify HEAD)
  r=$(python3 "$P" "$W/wt1")
  r_cd=$(echo "$r"|python3 -c 'import json,sys;print(json.load(sys.stdin)["commondir"])')
  r_head=$(echo "$r"|python3 -c 'import json,sys;print(json.load(sys.stdin)["head_oid"])')
  [ "$(realpath "$g_cd")" = "$(realpath "$r_cd")" ] && echo "  COMMON agree" || echo "  COMMON DISAGREE git=$g_cd raw=$r_cd"
  [ "$g_head" = "$r_head" ] && echo "  HEAD   agree" || echo "  HEAD   DISAGREE git=$g_head raw=$r_head"
done
rm -rf "$W"
