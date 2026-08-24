#!/usr/bin/env bash
# PROBE C-extras: confirm the negatives properly, and sweep remaining exec-capable keys.
. "$(dirname "$0")/lib.sh"
MARKDIR=""
payload() { cat > "$ROOT/pay-$1.sh" <<EOF
#!/bin/sh
echo "EXECUTED tag=$1 argv=\$*" >> "$MARKDIR/fired"
exit 0
EOF
chmod +x "$ROOT/pay-$1.sh"; echo "$ROOT/pay-$1.sh"; }
fresh() { mkrepo >/dev/null; MARKDIR="$ROOT/marks"; mkdir -p "$MARKDIR"; : > "$MARKDIR/fired"; }
verdict() { if [ -s "$MARKDIR/fired" ]; then echo "*** OBSERVED"; cat "$MARKDIR/fired"; else echo "not observed"; fi; }

hr "C15-recheck alias.status with a REAL modification present"
fresh; P=$(payload alias)
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
git -C "$WT" config alias.status "!$P"
sub "git status --porcelain output + exit"
git -C "$WT" status --porcelain; echo "exit=$?"
verdict
sub "does the alias work for a NON-builtin name?"
git -C "$WT" config alias.evilcmd "!$P"
git -C "$WT" evilcmd >/dev/null 2>&1; verdict

hr "C18 .git/hooks/pre-auto-gc  (git status can trigger auto-gc)"
fresh; P=$(payload preautogc)
cp "$P" "$PRIMARY/.git/hooks/pre-auto-gc"
git -C "$WT" status --porcelain >/dev/null 2>&1
git -C "$WT" gc --auto >/dev/null 2>&1
verdict

hr "C19 hooks placed in the WORKTREE's private hooks dir vs \$GIT_COMMON_DIR/hooks"
fresh; P=$(payload wthook)
echo "worktree git-dir     : $(git -C "$WT" rev-parse --git-dir)"
echo "worktree common-dir  : $(git -C "$WT" rev-parse --git-common-dir)"
mkdir -p "$(git -C "$WT" rev-parse --git-dir)/hooks"
cp "$P" "$(git -C "$WT" rev-parse --git-dir)/hooks/post-checkout" 2>/dev/null
echo "hooks are resolved from: $(git -C "$WT" rev-parse --git-path hooks)"

hr "C20 diff.<d>.cachetextconv, core.fsmonitorHookVersion, core.untrackedCache (exec?)"
fresh; P=$(payload misc)
git -C "$WT" config diff.evil.textconv "$P"
git -C "$WT" config diff.evil.cachetextconv true
git -C "$WT" config core.untrackedCache true
printf 'src/tracked.txt diff=evil\n' > "$WT/.gitattributes"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
git -C "$WT" diff "$BASE" >/dev/null 2>&1
verdict
sub "cachetextconv writes attacker output into the git object/notes store?"
git -C "$WT" notes --ref=textconv list 2>&1 | head -3

hr "C21 core.hooksPath set on the PRIMARY from the worktree, then dispatcher 'git worktree add'"
fresh; P=$(payload hp2)
mkdir -p "$ROOT/eh"; cp "$P" "$ROOT/eh/post-checkout"
git -C "$WT" config core.hooksPath "$ROOT/eh"
sub "which config file holds it?"; git -C "$WT" config --show-origin core.hooksPath
git -C "$PRIMARY" worktree add --quiet -b tz "$ROOT/wtz" "$BASE" >/dev/null 2>&1
verdict

hr "C22 does 'git config' from a linked worktree write to SHARED or worktree-local config?"
fresh
git -C "$WT" config probe.key fromworktree
sub "git config --show-origin"; git -C "$WT" config --show-origin probe.key
sub "does the PRIMARY see it?"; git -C "$PRIMARY" config probe.key
sub "extensions.worktreeConfig present?"; git -C "$PRIMARY" config extensions.worktreeConfig; echo "exit=$?"
sub "worker enables worktree-scoped config and hides a key there:"
git -C "$WT" config extensions.worktreeConfig true
git -C "$WT" config --worktree probe.hidden yes
git -C "$WT" config --show-origin probe.hidden
echo "primary sees probe.hidden? -> $(git -C "$PRIMARY" config probe.hidden; echo exit=$?)"

hr "C23 GIT_CONFIG_COUNT/GIT_CONFIG_KEY env — does the dispatcher strip them? (it strips only GIT_DIR-class)"
fresh; P=$(payload envcfg)
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.fsmonitor GIT_CONFIG_VALUE_0="$P" \
  git -C "$WT" status --porcelain >/dev/null 2>&1
verdict
echo "NOTE: relevant only if a worker can influence the dispatcher's own environment."
