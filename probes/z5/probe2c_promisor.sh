#!/usr/bin/env bash
# PROBE (3rd attempt) — absence proven WITHOUT touching the object (batch-all-objects
# enumerates only LOCAL objects and performs no lazy fetch). Poison applied BEFORE
# any command that could materialise the blob.
set -u
. "$(dirname "$0")/lib.sh"
ROOT="$(mktemp -d)"; echo "ROOT=$ROOT"; echo "git: $(git --version)"
LOG="$ROOT/fired.log"; : > "$LOG"
HELPER="$ROOT/transport-helper"
printf '#!/bin/sh\nprintf "EXEC:ext-transport-helper argv=[%%s]\\n" "$*" >> "%s"\nexit 1\n' "$LOG" > "$HELPER"; chmod 0755 "$HELPER"

SRC="$ROOT/src"; git init -q -b main "$SRC"
git -C "$SRC" config user.email a@b; git -C "$SRC" config user.name a
git -C "$SRC" config uploadpack.allowFilter true
mkdir -p "$SRC/d"; printf 'AAAAAAAAAAAAAAAA\n' > "$SRC/d/big.txt"
git -C "$SRC" add -A; git -C "$SRC" commit -qm one
SRCOID="$(git -C "$SRC" rev-parse HEAD:d/big.txt)"
CL="$ROOT/partial"
git clone -q --filter=blob:none --no-checkout "file://$SRC" "$CL" 2>&1 | head -3
BASE="$(git -C "$CL" rev-parse HEAD)"
echo "BASE=$BASE  target-blob=$SRCOID"

echo "-- POISON FIRST (before anything can materialise the blob) --"
git -C "$CL" config remote.origin.url "ext::$HELPER %S"
arm_hooks "$CL/.git/hooks" "$LOG"

echo "-- NON-FETCHING absence proof: enumerate LOCAL objects only --"
LOCAL="$(git -C "$CL" cat-file --batch-all-objects --batch-check='%(objectname)' 2>/dev/null)"
echo "  local object count: $(echo "$LOCAL" | wc -l)"
if echo "$LOCAL" | grep -qx "$SRCOID"; then echo "  *** BLOB IS PRESENT LOCALLY -> test would be INVALID"; else echo "  BLOB ABSENT LOCALLY -> test is VALID"; fi
echo "  fired during the absence proof: [$(cat "$LOG" | tr '\n' ' ')]"

echo
run "POSITIVE CONTROL: git branch (ref update)"      "$LOG" git -C "$CL" branch z5pc "$BASE"
run "cat-file blob <ABSENT oid>   [PERMITTED CMD]"   "$LOG" git -C "$CL" cat-file blob "$SRCOID"
echo "  -- verbose rerun --"
: > "$LOG"; timeout 25 git -C "$CL" cat-file blob "$SRCOID" </dev/null 2>&1 | head -5; echo "  rc=${PIPESTATUS[0]}  fired=[$(cat "$LOG"|tr '\n' ' ')]"
# re-clone to restore absence for each subsequent measurement
recl() { rm -rf "$CL"; git clone -q --filter=blob:none --no-checkout "file://$SRC" "$CL" 2>/dev/null; git -C "$CL" config remote.origin.url "ext::$HELPER %S"; arm_hooks "$CL/.git/hooks" "$LOG"; }
recl; run "cat-file --batch <<ABSENT [PERMITTED CMD]" "$LOG" sh -c "printf '%s\n' $SRCOID | timeout 20 git -C '$CL' cat-file --batch"
recl; run "cat-file -p <ABSENT oid>"                 "$LOG" git -C "$CL" cat-file -p "$SRCOID"
recl; run "ls-tree -r -z --long BASE [PERMITTED]"    "$LOG" git -C "$CL" ls-tree -r -z --long "$BASE"
recl; run "rev-parse --verify BASE^{commit}"         "$LOG" git -C "$CL" rev-parse --verify "$BASE^{commit}"
recl; run "worktree add --no-checkout -b [Z-4]"      "$LOG" git -C "$CL" worktree add --quiet --no-checkout -b pz1 "$ROOT/pw1" "$BASE"
recl; run "worktree add -b (WITH checkout)"          "$LOG" git -C "$CL" worktree add --quiet -b pz2 "$ROOT/pw2" "$BASE"
echo "ROOT kept at: $ROOT"
