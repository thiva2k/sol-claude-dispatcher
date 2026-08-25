#!/usr/bin/env bash
# ADDENDA — (a) a WORKING pre-auto-gc positive control, (b) index-population
# mechanisms that do/don't fire post-index-change, (c) core.gitProxy over git://,
# (d) can the worker make an object absent WITHOUT any git command?
set -u
. "$(dirname "$0")/lib.sh"
ROOT="$(mktemp -d)"; echo "ROOT=$ROOT"; echo "git: $(git --version)"
LOG="$ROOT/fired.log"; : > "$LOG"
mkprog() { printf '#!/bin/sh\nprintf "EXEC:%%s argv=[%%s]\\n" "%s" "$*" >> "%s"\nexit 1\n' "$1" "$LOG" > "$ROOT/$1"; chmod 0755 "$ROOT/$1"; echo "$ROOT/$1"; }

echo "########## (a) pre-auto-gc: a WORKING positive control first ##########"
G="$ROOT/g"; git init -q -b main "$G"; git -C "$G" config user.email a@b; git -C "$G" config user.name a
printf 'g\n' > "$G/g.txt"; git -C "$G" add -A; git -C "$G" commit -qm one
GBASE="$(git -C "$G" rev-parse HEAD)"
arm_hooks "$G/.git/hooks" "$LOG"
git -C "$G" config gc.auto 1; git -C "$G" config gc.autoDetach false
for k in $(seq 1 300); do printf 'x%s\n' "$k" | git -C "$G" hash-object -w --stdin >/dev/null; done
echo "  loose object count: $(find "$G/.git/objects" -type f -not -path '*info*' -not -path '*pack*' | wc -l)"
run "PC1 git gc --auto (gc.auto=1, 300 loose)" "$LOG" git -C "$G" gc --auto
run "PC2 git commit --allow-empty (calls gc --auto)" "$LOG" git -C "$G" commit -q --allow-empty -m e
run "PC3 git gc --auto again"                  "$LOG" git -C "$G" gc --auto
echo "  -- if none of PC1..PC3 fired, section (a) is NOT TESTABLE by this harness --"
run "worktree add -b (gc.auto=1)"              "$LOG" git -C "$G" worktree add --quiet -b gw "$ROOT/gw" "$GBASE"
run "cat-file -p BASE"                         "$LOG" git -C "$G" cat-file -p "$GBASE"

echo
echo "########## (b) index population: which mechanism avoids post-index-change? ##########"
I="$ROOT/i"; git init -q -b main "$I"; git -C "$I" config user.email a@b; git -C "$I" config user.name a
printf 'a\n' > "$I/a.txt"; git -C "$I" add -A; git -C "$I" commit -qm one
IB="$(git -C "$I" rev-parse HEAD)"
arm_hooks "$I/.git/hooks" "$LOG"
run "PC branch"                                "$LOG" git -C "$I" branch z5pc "$IB"
run "read-tree BASE (in-place index)"          "$LOG" git -C "$I" read-tree "$IB"
run "GIT_INDEX_FILE=<tmp> read-tree BASE"      "$LOG" env GIT_INDEX_FILE="$ROOT/idx.tmp" git -C "$I" read-tree "$IB"
run "GIT_INDEX_FILE=<tmp> read-tree + hooksPath=<empty>" "$LOG" env GIT_INDEX_FILE="$ROOT/idx2.tmp" git -C "$I" -c core.hooksPath="$ROOT/_e" read-tree "$IB"
mkdir -p "$ROOT/_e"
run "GIT_INDEX_FILE=<tmp> read-tree + hooksPath=<empty,exists>" "$LOG" env GIT_INDEX_FILE="$ROOT/idx3.tmp" git -C "$I" -c core.hooksPath="$ROOT/_e" read-tree "$IB"
run "update-index --index-info (stdin)"        "$LOG" sh -c "git -C '$I' ls-tree -r '$IB' | git -C '$I' update-index --index-info"
echo "  NOTE: does an EXTERNAL GIT_INDEX_FILE even serve a worker's in-worktree git?  (it does not: env is per-process)"

echo
echo "########## (c) core.gitProxy over git:// via promisor lazy fetch ##########"
PXY="$(mkprog gitproxy-prog)"
R="$ROOT/px"; git init -q -b main "$R"; git -C "$R" config user.email a@b; git -C "$R" config user.name a
mkdir -p "$R/d"; printf 'PAYLOAD\n' > "$R/d/big.txt"; git -C "$R" add -A; git -C "$R" commit -qm one
O="$(git -C "$R" rev-parse HEAD:d/big.txt)"
arm_hooks "$R/.git/hooks" "$LOG"
cat >> "$R/.git/config" <<CFG
[extensions]
	partialClone = evil
[remote "evil"]
	url = git://nosuchhost.invalid/repo.git
	promisor = true
[core]
	gitProxy = $PXY
CFG
rm -f "$R/.git/objects/${O:0:2}/${O:2}"
run "cat-file blob <ABSENT> + core.gitProxy (git://)" "$LOG" git -C "$R" cat-file blob "$O"
echo "  verbose: $(timeout 25 git -C "$R" cat-file blob "$O" 2>&1 </dev/null | head -2 | tr '\n' '|')"

echo
echo "########## (d) can the worker make an object absent with NO git command? ##########"
W="$ROOT/w"; git init -q -b main "$W"; git -C "$W" config user.email a@b; git -C "$W" config user.name a
printf 'VICTIM\n' > "$W/v.txt"; git -C "$W" add -A; git -C "$W" commit -qm one
WB="$(git -C "$W" rev-parse HEAD)"; WO="$(git -C "$W" rev-parse HEAD:v.txt)"
git -C "$W" worktree add --quiet -b wk "$ROOT/wk" "$WB"
echo "  worker cwd = $ROOT/wk ; its .git file: $(cat "$ROOT/wk/.git")"
LOOSE="$W/.git/objects/${WO:0:2}/${WO:2}"
echo "  base blob loose path: $LOOSE"
echo "  writable by the worker uid? $([ -w "$W/.git/objects/${WO:0:2}" ] && echo yes || echo no)"
rm -f "$LOOSE"; echo "  removed with plain rm (no git command). present? $([ -f "$LOOSE" ] && echo yes || echo no)"
echo "  dispatcher cat-file of that base blob now:"
timeout 15 git -C "$W" cat-file blob "$WO" </dev/null 2>&1 | head -2 | sed 's/^/    /'
echo "  rc=$?"
echo "ROOT kept at: $ROOT"
