#!/usr/bin/env bash
# PROBE 1c — the dispatcher's ACTUAL env (_git_env: GIT_OPTIONAL_LOCKS=0,
# GIT_TERMINAL_PROMPT=0, 8 GIT_* redirects popped) vs default env.
set -u
. "$(dirname "$0")/lib.sh"
ROOT="$(mktemp -d)"; echo "ROOT=$ROOT"
LOG="$ROOT/fired.log"; : > "$LOG"; SD="$ROOT/_sentinel"; R="$ROOT/primary"
git init -q -b main "$R"; git -C "$R" config user.email z5@probe; git -C "$R" config user.name z5
printf 'line1\nline2\n' > "$R/a.txt"; git -C "$R" add -A; git -C "$R" commit -qm base
BASE="$(git -C "$R" rev-parse HEAD)"
arm_hooks "$R/.git/hooks" "$LOG"; arm_config_exec "$R" "$SD" "$LOG"
printf '* filter=zf diff=zd\n' > "$R/.gitattributes"
mkdir -p "$R/.git/info"; printf '* filter=zf diff=zd\n' > "$R/.git/info/attributes"
EMPTY="$ROOT/_emptyhooks"; mkdir -p "$EMPTY"
E="GIT_OPTIONAL_LOCKS=0"; E2="GIT_TERMINAL_PROMPT=0"
N=0; n() { N=$((N+1)); }

run "PC branch (arming live)" "$LOG" git -C "$R" branch z5pc "$BASE"
echo
echo "=== dispatcher env (GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0) ==="
n; run "OPTLOCKS=0 worktree add --quiet -b B$N"            "$LOG" env $E $E2 git -C "$R" worktree add --quiet -b "B$N" "$ROOT/w$N" "$BASE"
n; run "OPTLOCKS=0 worktree add --quiet --no-checkout -b B$N" "$LOG" env $E $E2 git -C "$R" worktree add --quiet --no-checkout -b "B$N" "$ROOT/w$N" "$BASE"
run "OPTLOCKS=0 status --porcelain"                        "$LOG" env $E $E2 git -C "$R" status --porcelain
run "OPTLOCKS unset status --porcelain"                    "$LOG" git -C "$R" status --porcelain
run "OPTLOCKS=0 read-tree BASE"                            "$LOG" env $E $E2 git -C "$R" read-tree "$BASE"
run "OPTLOCKS unset read-tree BASE"                        "$LOG" git -C "$R" read-tree "$BASE"
run "OPTLOCKS=0 diff BASE"                                 "$LOG" env $E $E2 git -C "$R" diff "$BASE"
run "OPTLOCKS=0 ls-files --others --exclude-standard"      "$LOG" env $E $E2 git -C "$R" ls-files --others --exclude-standard
run "OPTLOCKS=0 rev-parse --verify HEAD^{commit}"          "$LOG" env $E $E2 git -C "$R" rev-parse --verify 'HEAD^{commit}'
run "OPTLOCKS=0 config --get remote.origin.url"            "$LOG" env $E $E2 git -C "$R" config --get user.email
run "OPTLOCKS=0 rev-list --max-parents=0 HEAD"             "$LOG" env $E $E2 git -C "$R" rev-list --max-parents=0 HEAD
run "OPTLOCKS=0 rev-parse --is-inside-work-tree"           "$LOG" env $E $E2 git -C "$R" rev-parse --is-inside-work-tree
run "OPTLOCKS=0 worktree list --porcelain"                 "$LOG" env $E $E2 git -C "$R" worktree list --porcelain
run "OPTLOCKS=0 rev-parse --absolute-git-dir"              "$LOG" env $E $E2 git -C "$R" rev-parse --absolute-git-dir
run "OPTLOCKS=0 rev-parse --git-common-dir"                "$LOG" env $E $E2 git -C "$R" rev-parse --git-common-dir
run "OPTLOCKS=0 ls-tree -r -z --long BASE"                 "$LOG" env $E $E2 git -C "$R" ls-tree -r -z --long "$BASE"
run "OPTLOCKS=0 cat-file -p BASE"                          "$LOG" env $E $E2 git -C "$R" cat-file -p "$BASE"

echo
echo "=== GIT_CONFIG_* as an alternative hooksPath lever (why did it rc=128?) ==="
n; echo "--- verbose:"; env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY0=core.hooksPath GIT_CONFIG_VALUE0="$EMPTY" git -C "$R" worktree add --quiet -b "B$N" "$ROOT/w$N" "$BASE"; echo "rc=$?"
n; run "GIT_CONFIG_COUNT=1 core.hooksPath=<EMPTY>"         "$LOG" env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY0=core.hooksPath GIT_CONFIG_VALUE0="$EMPTY" git -C "$R" worktree add --quiet -b "B$N" "$ROOT/w$N" "$BASE"
echo
echo "=== GIT_CONFIG_* is NOT scrubbed by _git_env: can an INHERITED value ARM a surface? ==="
POISON="$ROOT/_poison"; printf '#!/bin/sh\nprintf "ENVCFG:core.fsmonitor\\n" >> "%s"\nexit 1\n' "$LOG" > "$POISON"; chmod 0755 "$POISON"
CLEANR="$ROOT/clean"; git init -q -b main "$CLEANR"; git -C "$CLEANR" config user.email a@b; git -C "$CLEANR" config user.name a
printf 'x\n' > "$CLEANR/f.txt"; git -C "$CLEANR" add -A; git -C "$CLEANR" commit -qm c
run "UNPOISONED repo + inherited GIT_CONFIG_COUNT core.fsmonitor" "$LOG" env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY0=core.fsmonitor GIT_CONFIG_VALUE0="$POISON" git -C "$CLEANR" status --porcelain
run "UNPOISONED repo + inherited GIT_EXTERNAL_DIFF"        "$LOG" env GIT_EXTERNAL_DIFF="$POISON" git -C "$CLEANR" diff HEAD
echo "ROOT kept at: $ROOT"
