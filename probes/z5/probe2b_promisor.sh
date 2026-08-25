#!/usr/bin/env bash
# PROBE — promisor lazy-fetch as a candidate FOURTH surface, with a VALID
# partial clone (uploadpack.allowFilter) and a proven-absent object.
set -u
. "$(dirname "$0")/lib.sh"
ROOT="$(mktemp -d)"; echo "ROOT=$ROOT"; echo "git: $(git --version)"
LOG="$ROOT/fired.log"; : > "$LOG"
HELPER="$ROOT/transport-helper"
printf '#!/bin/sh\nprintf "EXEC:ext-transport-helper argv=%%s\\n" "$*" >> "%s"\nexit 1\n' "$LOG" > "$HELPER"; chmod 0755 "$HELPER"

SRC="$ROOT/src"; git init -q -b main "$SRC"
git -C "$SRC" config user.email a@b; git -C "$SRC" config user.name a
git -C "$SRC" config uploadpack.allowFilter true
git -C "$SRC" config uploadpack.allowAnySHA1InWant true
mkdir -p "$SRC/d"; printf 'AAAAAAAAAAAAAAAA\n' > "$SRC/d/big.txt"; printf 'bbb\n' > "$SRC/small.txt"
git -C "$SRC" add -A; git -C "$SRC" commit -qm one
CL="$ROOT/partial"
git clone -q --filter=blob:none --no-checkout "file://$SRC" "$CL" 2>&1 | head -3
BASE="$(git -C "$CL" rev-parse HEAD)"
MISS="$(git -C "$CL" ls-tree -r "$BASE" | awk '/big.txt/{print $3}')"
echo "BASE=$BASE  target-blob=$MISS"
echo "-- PROOF the blob is genuinely absent locally (this is the control that makes the test valid) --"
git -C "$CL" cat-file -e "$MISS" 2>&1; echo "  cat-file -e rc=$?  (rc!=0 => absent, test is valid)"
echo "-- promisor config as cloned --"
git -C "$CL" config --local --list | grep -E 'partialclone|promisor|partialclonefilter|remote.origin.url'

echo
echo "-- BASELINE (control): fetch works and prints the blob before poisoning --"
timeout 20 git -C "$CL" cat-file blob "$MISS" </dev/null; echo "  rc=$?"
echo "-- re-create a fresh partial clone so the blob is absent again --"
rm -rf "$CL"; git clone -q --filter=blob:none --no-checkout "file://$SRC" "$CL" 2>&1 | head -2
git -C "$CL" cat-file -e "$MISS" 2>/dev/null; echo "  absent again? rc=$? (nonzero=absent)"
arm_hooks "$CL/.git/hooks" "$LOG"

echo
echo "-- POISON: worker rewrites remote.origin.url to an ext:: transport naming its own program --"
git -C "$CL" config remote.origin.url "ext::$HELPER %S"
git -C "$CL" config --local --get remote.origin.url
run "POSITIVE CONTROL: git branch (ref update)"      "$LOG" git -C "$CL" branch z5pc "$BASE"
run "cat-file blob <ABSENT oid>   [PERMITTED CMD]"   "$LOG" git -C "$CL" cat-file blob "$MISS"
run "cat-file -p <ABSENT oid>"                       "$LOG" git -C "$CL" cat-file -p "$MISS"
run "cat-file --batch <<ABSENT    [PERMITTED CMD]"   "$LOG" sh -c "printf '%s\n' $MISS | timeout 15 git -C '$CL' cat-file --batch"
run "ls-tree -r -z --long BASE    [PERMITTED CMD]"   "$LOG" git -C "$CL" ls-tree -r -z --long "$BASE"
run "rev-parse --verify BASE^{commit}"               "$LOG" git -C "$CL" rev-parse --verify "$BASE^{commit}"
run "rev-list --max-parents=0 HEAD"                  "$LOG" git -C "$CL" rev-list --max-parents=0 HEAD
run "config --get remote.origin.url"                 "$LOG" git -C "$CL" config --get remote.origin.url
run "worktree add --no-checkout -b B P BASE  [Z-4]"  "$LOG" git -C "$CL" worktree add --quiet --no-checkout -b pz1 "$ROOT/pw1" "$BASE"
run "worktree add -b B P BASE (checkout)"            "$LOG" git -C "$CL" worktree add --quiet -b pz2 "$ROOT/pw2" "$BASE"
echo
echo "-- what did cat-file actually print/say? (verbose) --"
: > "$LOG"; timeout 20 git -C "$CL" cat-file blob "$MISS" </dev/null; echo "  rc=$?"; echo "  fired: $(cat "$LOG")"
echo "ROOT kept at: $ROOT"
