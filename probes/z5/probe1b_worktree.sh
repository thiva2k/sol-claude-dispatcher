#!/usr/bin/env bash
# PROBE 1b — worktree add in every form, with UNIQUE branch/path per run so no
# invocation can fail for a name collision. rc is printed; a non-zero rc
# invalidates the "clean" reading and is reported as NOT TESTABLE.
set -u
. "$(dirname "$0")/lib.sh"

ROOT="$(mktemp -d)"; echo "ROOT=$ROOT"; echo "git: $(git --version)"
LOG="$ROOT/fired.log"; : > "$LOG"; SD="$ROOT/_sentinel"
R="$ROOT/primary"
git init -q -b main "$R"; git -C "$R" config user.email z5@probe; git -C "$R" config user.name z5
printf 'line1\nline2\n' > "$R/a.txt"; printf 'payload\n' > "$R/thing.dat"
git -C "$R" add -A; git -C "$R" commit -qm base
BASE="$(git -C "$R" rev-parse HEAD)"
arm_hooks "$R/.git/hooks" "$LOG"; arm_config_exec "$R" "$SD" "$LOG"
printf '* filter=zf diff=zd\n' > "$R/.gitattributes"
mkdir -p "$R/.git/info"; printf '* filter=zf diff=zd\n' > "$R/.git/info/attributes"
EMPTY="$ROOT/_emptyhooks"; mkdir -p "$EMPTY"
N=0
wt_next() { N=$((N+1)); }

echo
echo "=== POSITIVE CONTROL (must fire; proves the arming is live in THIS repo) ==="
run "PC git branch z5pc"  "$LOG" git -C "$R" branch z5pc "$BASE"

echo
echo "=== A. worktree add forms, DEFAULT env (no GIT_OPTIONAL_LOCKS) ==="
wt_next; run "add --quiet -b B$N P$N BASE        [git.py:609 default]" "$LOG" git -C "$R" worktree add --quiet -b "B$N" "$ROOT/w$N" "$BASE"
wt_next; run "add --quiet --no-checkout -b B$N P$N BASE   [Z-4 argv]"  "$LOG" git -C "$R" worktree add --quiet --no-checkout -b "B$N" "$ROOT/w$N" "$BASE"
wt_next; run "add --no-checkout --detach P$N BASE"                     "$LOG" git -C "$R" worktree add --quiet --no-checkout --detach "$ROOT/w$N" "$BASE"
wt_next; run "add --detach P$N BASE"                                   "$LOG" git -C "$R" worktree add --quiet --detach "$ROOT/w$N" "$BASE"
wt_next; run "add --no-checkout -b B$N P$N BASE (no --quiet)"          "$LOG" git -C "$R" worktree add --no-checkout -b "B$N" "$ROOT/w$N" "$BASE"

echo
echo "=== B. same, under the DISPATCHER'S env (GIT_OPTIONAL_LOCKS=0, GIT_TERMINAL_PROMPT=0) ==="
G() { env GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0 git "$@"; }
wt_next; run "OPTLOCKS=0 add --quiet -b B$N P$N BASE"                  "$LOG" G -C "$R" worktree add --quiet -b "B$N" "$ROOT/w$N" "$BASE"
wt_next; run "OPTLOCKS=0 add --quiet --no-checkout -b B$N P$N BASE"    "$LOG" G -C "$R" worktree add --quiet --no-checkout -b "B$N" "$ROOT/w$N" "$BASE"
run "OPTLOCKS=0 status --porcelain"                                    "$LOG" G -C "$R" status --porcelain
run "OPTLOCKS=0 read-tree BASE"                                        "$LOG" G -C "$R" read-tree "$BASE"
run "OPTLOCKS=1(unset) read-tree BASE"                                 "$LOG" git -C "$R" read-tree "$BASE"

echo
echo "=== C. does -c core.hooksPath neutralise it? (unique names, rc must be 0) ==="
wt_next; run "add -b + -c core.hooksPath=<EMPTY DIR>"                  "$LOG" git -C "$R" -c core.hooksPath="$EMPTY" worktree add --quiet -b "B$N" "$ROOT/w$N" "$BASE"
wt_next; run "add -b + -c core.hooksPath=/dev/null"                    "$LOG" git -C "$R" -c core.hooksPath=/dev/null worktree add --quiet -b "B$N" "$ROOT/w$N" "$BASE"
wt_next; run "add -b + -c core.hooksPath=<NONEXISTENT>"                "$LOG" git -C "$R" -c core.hooksPath="$ROOT/_nope" worktree add --quiet -b "B$N" "$ROOT/w$N" "$BASE"
wt_next; run "add -b + GIT_CONFIG_COUNT=1 core.hooksPath=<EMPTY>"      "$LOG" env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY0=core.hooksPath GIT_CONFIG_VALUE0="$EMPTY" git -C "$R" worktree add --quiet -b "B$N" "$ROOT/w$N" "$BASE"
wt_next; run "add --no-checkout -b + hooksPath=<EMPTY>"                "$LOG" git -C "$R" -c core.hooksPath="$EMPTY" worktree add --quiet --no-checkout -b "B$N" "$ROOT/w$N" "$BASE"
wt_next; run "add -b + hooksPath=<EMPTY> + fsmonitor=false + attributesFile=/dev/null" "$LOG" git -C "$R" -c core.hooksPath="$EMPTY" -c core.fsmonitor=false -c core.attributesFile=/dev/null worktree add --quiet -b "B$N" "$ROOT/w$N" "$BASE"

echo
echo "=== C2. NEGATIVE CONTROL for C: same argv WITHOUT the hooksPath override ==="
wt_next; run "add -b (no override) — must FIRE, else C proves nothing"  "$LOG" git -C "$R" worktree add --quiet -b "B$N" "$ROOT/w$N" "$BASE"

echo
echo "=== D. is the hooks dir per-worktree or common only? ==="
WT="$ROOT/w1"
echo "-- git -C <worktree> rev-parse --git-dir / --git-common-dir --"
git -C "$WT" rev-parse --git-dir; git -C "$WT" rev-parse --git-common-dir
mkdir -p "$WT/.git-nonsense" 2>/dev/null
PERWT="$R/.git/worktrees/w1/hooks"; mkdir -p "$PERWT"
printf '#!/bin/sh\nprintf "PERWT-HOOK:reference-transaction\\n" >> "%s"\nexit 0\n' "$LOG" > "$PERWT/reference-transaction"; chmod 0755 "$PERWT/reference-transaction"
run "branch inside worktree (per-wt hooks dir planted)"                "$LOG" git -C "$WT" branch z5perwt "$BASE"

echo
echo "ROOT kept at: $ROOT"
