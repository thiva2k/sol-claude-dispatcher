#!/usr/bin/env bash
# PROBE 1 — which surfaces fire, for which commands. Throwaway repo.
set -u
. "$(dirname "$0")/lib.sh"

ROOT="$(mktemp -d)"; echo "ROOT=$ROOT"; echo "git: $(git --version)"
LOG="$ROOT/fired.log"; : > "$LOG"
SD="$ROOT/_sentinel"; mkdir -p "$SD"
R="$ROOT/primary"

git init -q -b main "$R"
git -C "$R" config user.email z5@probe && git -C "$R" config user.name z5
mkdir -p "$R/sub"
printf 'line1\nline2\n' > "$R/a.txt"
printf 'payload\n'       > "$R/thing.dat"
printf 'deep\n'          > "$R/sub/deep.txt"
git -C "$R" add -A && git -C "$R" commit -qm base
BASE="$(git -C "$R" rev-parse HEAD)"
OID="$(git -C "$R" rev-parse HEAD:a.txt)"
echo "BASE=$BASE OID=$OID"

echo
echo "=== ARMING (every hook + every exec config key + attributes, both sources) ==="
arm_hooks "$R/.git/hooks" "$LOG"
arm_config_exec "$R" "$SD" "$LOG"
# attribute sources: in-tree (worker-written, uncommitted) AND common-dir info/attributes
printf '* filter=zf diff=zd\n' > "$R/.gitattributes"
mkdir -p "$R/.git/info"
printf '* filter=zf diff=zd\n' > "$R/.git/info/attributes"
ls "$R/.git/hooks" | tr '\n' ' '; echo
echo "armed exec keys:"; git -C "$R" config --local --list | grep -E 'fsmonitor|pager|editor|Proxy|sshCommand|credential|gpg|alternateRefs|packObjectsHook|external|filter\.|diff\.zd' | sed 's/=.*/=<sentinel>/' | tr '\n' ' '; echo

echo
echo "=== POSITIVE CONTROLS (each must fire the surface it targets) ==="
run "PC ref-update: git branch pc1"             "$LOG" git -C "$R" branch pc1
run "PC index-refresh+content: git status"      "$LOG" git -C "$R" status --porcelain
run "PC content-transform: cat-file --filters"  "$LOG" git -C "$R" cat-file --filters HEAD:a.txt
run "PC checkout: worktree add (WITH checkout)" "$LOG" git -C "$R" worktree add -q "$ROOT/wt_pc" -b pcwt "$BASE"

echo
echo "=== PROBE 1.1 — ref-mutating operations: which fire reference-transaction ==="
run "branch <new>"                    "$LOG" git -C "$R" branch rb1 "$BASE"
run "branch -D <b>"                   "$LOG" git -C "$R" branch -D rb1
run "tag t1"                          "$LOG" git -C "$R" tag t1 "$BASE"
run "update-ref refs/z5/x <sha>"      "$LOG" git -C "$R" update-ref refs/z5/x "$BASE"
run "symbolic-ref refs/z5/s refs/heads/main" "$LOG" git -C "$R" symbolic-ref refs/z5/s refs/heads/main
run "gc --quiet"                      "$LOG" git -C "$R" gc --quiet
run "pack-refs --all"                 "$LOG" git -C "$R" pack-refs --all
run "reflog expire --all"             "$LOG" git -C "$R" reflog expire --all
run "read-tree <base> (bare index)"   "$LOG" git -C "$R" read-tree "$BASE"
run "checkout -b cb1 <base>"          "$LOG" git -C "$R" checkout -q -b cb1 "$BASE"
run "checkout main"                   "$LOG" git -C "$R" checkout -q main
run "stash list"                      "$LOG" git -C "$R" stash list

echo
echo "=== PROBE 1.1b — worktree add, ALL forms (the PREPARE vector) ==="
i=0
wt() { i=$((i+1)); echo "$ROOT/w$i"; }
P=$(wt); run "worktree add --quiet -b b$i <p> <base>   [git.py:609 default]" "$LOG" git -C "$R" worktree add --quiet -b "b$i" "$P" "$BASE"
P=$(wt); run "worktree add --quiet --no-checkout -b b$i <p> <base>  [Z-4]"   "$LOG" git -C "$R" worktree add --quiet --no-checkout -b "b$i" "$P" "$BASE"
P=$(wt); run "worktree add --quiet --no-checkout --detach <p> <base>"        "$LOG" git -C "$R" worktree add --quiet --no-checkout --detach "$P" "$BASE"
P=$(wt); run "worktree add --quiet --detach <p> <base>"                      "$LOG" git -C "$R" worktree add --quiet --detach "$P" "$BASE"
run "worktree list --porcelain"                                              "$LOG" git -C "$R" worktree list --porcelain
run "worktree prune"                                                         "$LOG" git -C "$R" worktree prune

echo
echo "=== PROBE 1.2 — does -c core.hooksPath neutralise it? ==="
EMPTY="$ROOT/_emptyhooks"; mkdir -p "$EMPTY"
P=$(wt); run "worktree add -b + -c core.hooksPath=<empty dir>"   "$LOG" git -C "$R" -c core.hooksPath="$EMPTY" worktree add --quiet -b "h$i" "$P" "$BASE"
P=$(wt); run "worktree add -b + -c core.hooksPath=/dev/null"     "$LOG" git -C "$R" -c core.hooksPath=/dev/null   worktree add --quiet -b "h$i" "$P" "$BASE"
P=$(wt); run "worktree add -b + -c core.hooksPath=<nonexistent>" "$LOG" git -C "$R" -c core.hooksPath="$ROOT/_nope" worktree add --quiet -b "h$i" "$P" "$BASE"
P=$(wt); run "worktree add -b + GIT_CONFIG_{COUNT,KEY0,VALUE0} hooksPath" "$LOG" env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY0=core.hooksPath GIT_CONFIG_VALUE0="$EMPTY" git -C "$R" worktree add --quiet -b "e$i" "$P" "$BASE"
P=$(wt); run "worktree add -b + --no-checkout + hooksPath=<empty>" "$LOG" git -C "$R" -c core.hooksPath="$EMPTY" worktree add --quiet --no-checkout -b "n$i" "$P" "$BASE"

echo
echo "=== PROBE 3 — the permitted repertoire + the three unlisted commands ==="
run "rev-parse --verify HEAD^{commit}"        "$LOG" git -C "$R" rev-parse --verify 'HEAD^{commit}'
run "rev-parse --show-toplevel"               "$LOG" git -C "$R" rev-parse --show-toplevel
run "rev-parse --absolute-git-dir"            "$LOG" git -C "$R" rev-parse --absolute-git-dir
run "rev-parse --git-common-dir"              "$LOG" git -C "$R" rev-parse --git-common-dir
run "rev-parse --is-inside-work-tree   [N-1]" "$LOG" git -C "$R" rev-parse --is-inside-work-tree
run "ls-tree -r -z --long <base>"             "$LOG" git -C "$R" ls-tree -r -z --long "$BASE"
run "cat-file blob <oid>"                     "$LOG" git -C "$R" cat-file blob "$OID"
run "cat-file -p <base>"                      "$LOG" git -C "$R" cat-file -p "$BASE"
run "config --get user.email          [N-1]"  "$LOG" git -C "$R" config --get user.email
run "config --get remote.origin.url   [N-1]"  "$LOG" git -C "$R" config --get remote.origin.url
run "rev-list --max-parents=0 HEAD     [N-1,actual]" "$LOG" git -C "$R" rev-list --max-parents=0 HEAD
run "rev-list --count HEAD"                    "$LOG" git -C "$R" rev-list --count HEAD
echo "-- prohibited set, for contrast --"
run "status --porcelain -z"                   "$LOG" git -C "$R" status --porcelain -z
run "diff <base>"                             "$LOG" git -C "$R" diff "$BASE"
run "diff --name-only -z <base>"              "$LOG" git -C "$R" diff --name-only -z "$BASE"
run "diff --stat"                             "$LOG" git -C "$R" diff --stat
run "diff --check"                            "$LOG" git -C "$R" diff --check
run "ls-files --others -z --exclude-standard" "$LOG" git -C "$R" ls-files --others -z --exclude-standard
run "ls-files -v"                             "$LOG" git -C "$R" ls-files -v
run "check-attr -a a.txt"                     "$LOG" git -C "$R" check-attr -a a.txt
run "check-ignore -q a.txt"                   "$LOG" git -C "$R" check-ignore -q a.txt
run "branch --list"                           "$LOG" git -C "$R" branch --list
run "cat-file --batch (fed oid)"              "$LOG" sh -c "echo $OID | git -C '$R' cat-file --batch"

echo
echo "=== cat-file --batch fed via stdin, and the --textconv form ==="
run "cat-file --textconv HEAD:a.txt"          "$LOG" git -C "$R" cat-file --textconv "HEAD:a.txt"

echo
echo "ROOT kept at: $ROOT"
