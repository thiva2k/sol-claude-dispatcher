#!/usr/bin/env bash
# PROBE — hunting a FOURTH execution surface beyond S-alpha (attributes/filters),
# S-beta (fsmonitor/index refresh) and S-gamma (ref update / reference-transaction).
set -u
. "$(dirname "$0")/lib.sh"
ROOT="$(mktemp -d)"; echo "ROOT=$ROOT"; echo "git: $(git --version)"
LOG="$ROOT/fired.log"; : > "$LOG"
P="$ROOT/prog"; printf '#!/bin/sh\nprintf "EXEC:%%s\\n" "$(basename "$0")" >> "%s"\nexit 1\n' "$LOG" > "$P"; chmod 0755 "$P"
mk() { local n="$1"; cp "$P" "$ROOT/$n"; chmod 0755 "$ROOT/$n"; echo "$ROOT/$n"; }

echo
echo "########## 1. PARTIAL CLONE / PROMISOR: does cat-file or ls-tree lazy-fetch? ##########"
SRC="$ROOT/src"; git init -q -b main "$SRC"; git -C "$SRC" config user.email a@b; git -C "$SRC" config user.name a
mkdir -p "$SRC/d"; printf 'AAAA\n' > "$SRC/d/big.txt"; printf 'bbb\n' > "$SRC/small.txt"
git -C "$SRC" add -A; git -C "$SRC" commit -qm one
SRCBASE="$(git -C "$SRC" rev-parse HEAD)"
CL="$ROOT/partial"
git clone -q --filter=blob:none --no-checkout "file://$SRC" "$CL" 2>&1 | head -2
echo "-- partial clone config --"; git -C "$CL" config --local --list | grep -E 'partialclone|promisor|filter' 
BASE="$(git -C "$CL" rev-parse HEAD)"
MISSING="$(git -C "$CL" ls-tree -r "$BASE" | awk '/big.txt/{print $3}')"
echo "BASE=$BASE  missing-blob-oid=$MISSING"
echo "-- is it really absent locally? --"; git -C "$CL" cat-file -e "$MISSING" 2>&1; echo "cat-file -e rc=$?"
POISON="$(mk transport-helper)"
echo "-- POISON: repoint the promisor remote at an ext:: transport naming a worker program --"
git -C "$CL" config remote.origin.url "ext::$POISON %S"
git -C "$CL" config --local --list | grep -E 'remote.origin.url|promisor|partialclone'
arm_hooks "$CL/.git/hooks" "$LOG"
run "POSITIVE CONTROL: git branch (ref update)"    "$LOG" git -C "$CL" branch z5pc "$BASE"
run "cat-file blob <MISSING oid>"                  "$LOG" git -C "$CL" cat-file blob "$MISSING"
run "cat-file -p <MISSING oid>"                    "$LOG" git -C "$CL" cat-file -p "$MISSING"
run "cat-file --batch <<MISSING"                   "$LOG" sh -c "echo $MISSING | git -C '$CL' cat-file --batch"
run "ls-tree -r -z --long <BASE>"                  "$LOG" git -C "$CL" ls-tree -r -z --long "$BASE"
run "rev-parse --verify BASE^{commit}"             "$LOG" git -C "$CL" rev-parse --verify "$BASE^{commit}"
run "rev-list --max-parents=0 HEAD"                "$LOG" git -C "$CL" rev-list --max-parents=0 HEAD
run "worktree add --no-checkout -b z5 P BASE"      "$LOG" git -C "$CL" worktree add --quiet --no-checkout -b z5wt "$ROOT/pw1" "$BASE"
run "worktree add -b z5 P BASE (with checkout)"    "$LOG" git -C "$CL" worktree add --quiet -b z5wt2 "$ROOT/pw2" "$BASE"

echo
echo "########## 1b. SAME, but the promisor config PLANTED into a FULL repo by a worker ##########"
FULL="$ROOT/full"; git init -q -b main "$FULL"; git -C "$FULL" config user.email a@b; git -C "$FULL" config user.name a
printf 'zz\n' > "$FULL/z.txt"; git -C "$FULL" add -A; git -C "$FULL" commit -qm one
FBASE="$(git -C "$FULL" rev-parse HEAD)"; FOID="$(git -C "$FULL" rev-parse HEAD:z.txt)"
arm_hooks "$FULL/.git/hooks" "$LOG"
P2="$(mk planted-helper)"
git -C "$FULL" config extensions.partialClone z5remote
git -C "$FULL" config remote.z5remote.url "ext::$P2 %S"
git -C "$FULL" config remote.z5remote.promisor true
git -C "$FULL" config remote.z5remote.fetch "+refs/heads/*:refs/remotes/z5remote/*"
FAKE="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
run "PC branch"                                    "$LOG" git -C "$FULL" branch z5pc2 "$FBASE"
run "cat-file blob <PRESENT oid>"                  "$LOG" git -C "$FULL" cat-file blob "$FOID"
run "cat-file blob <ABSENT oid> (lazy fetch?)"     "$LOG" git -C "$FULL" cat-file blob "$FAKE"
run "cat-file --batch <<ABSENT"                    "$LOG" sh -c "echo $FAKE | git -C '$FULL' cat-file --batch"
run "rev-parse --verify <ABSENT>^{commit}"         "$LOG" git -C "$FULL" rev-parse --verify "$FAKE^{commit}"

echo
echo "########## 2. objects/info/alternates + core.alternateRefsCommand ##########"
A="$ROOT/altrepo"; git init -q -b main "$A"; git -C "$A" config user.email a@b; git -C "$A" config user.name a
printf 'q\n' > "$A/q.txt"; git -C "$A" add -A; git -C "$A" commit -qm one
ABASE="$(git -C "$A" rev-parse HEAD)"; AOID="$(git -C "$A" rev-parse HEAD:q.txt)"
arm_hooks "$A/.git/hooks" "$LOG"
P3="$(mk altrefs-helper)"
git -C "$A" config core.alternateRefsCommand "$P3"
mkdir -p "$A/.git/objects/info"; printf '%s\n' "$SRC/.git/objects" > "$A/.git/objects/info/alternates"
run "PC branch"                                    "$LOG" git -C "$A" branch z5pc3 "$ABASE"
run "cat-file blob <oid> (alternates armed)"       "$LOG" git -C "$A" cat-file blob "$AOID"
run "ls-tree -r -z --long BASE"                    "$LOG" git -C "$A" ls-tree -r -z --long "$ABASE"
run "rev-parse --verify HEAD^{commit}"             "$LOG" git -C "$A" rev-parse --verify 'HEAD^{commit}'
run "worktree add --no-checkout -b w P BASE"       "$LOG" git -C "$A" worktree add --quiet --no-checkout -b altw "$ROOT/aw1" "$ABASE"

echo
echo "########## 3. gc.auto -> pre-auto-gc, reachable from the repertoire? ##########"
G="$ROOT/gcrepo"; git init -q -b main "$G"; git -C "$G" config user.email a@b; git -C "$G" config user.name a
printf 'g\n' > "$G/g.txt"; git -C "$G" add -A; git -C "$G" commit -qm one
GBASE="$(git -C "$G" rev-parse HEAD)"
arm_hooks "$G/.git/hooks" "$LOG"
git -C "$G" config gc.auto 1
git -C "$G" config gc.autoDetach false
for k in $(seq 1 40); do printf 'x%s\n' "$k" | git -C "$G" hash-object -w --stdin >/dev/null; done
run "PC git gc --auto (must fire pre-auto-gc)"     "$LOG" git -C "$G" gc --auto
for k in $(seq 41 90); do printf 'y%s\n' "$k" | git -C "$G" hash-object -w --stdin >/dev/null; done
run "worktree add -b (gc.auto=1, 90 loose objects)" "$LOG" git -C "$G" worktree add --quiet -b gcw "$ROOT/gw1" "$GBASE"
run "worktree add --no-checkout -b"                "$LOG" git -C "$G" worktree add --quiet --no-checkout -b gcw2 "$ROOT/gw2" "$GBASE"
run "status --porcelain"                           "$LOG" git -C "$G" status --porcelain
run "rev-parse --verify HEAD^{commit}"             "$LOG" git -C "$G" rev-parse --verify 'HEAD^{commit}'

echo
echo "########## 4. worker-set core.hooksPath: does it re-arm after the dispatcher quarantines hooks/? ##########"
H="$ROOT/hprepo"; git init -q -b main "$H"; git -C "$H" config user.email a@b; git -C "$H" config user.name a
printf 'h\n' > "$H/h.txt"; git -C "$H" add -A; git -C "$H" commit -qm one
HBASE="$(git -C "$H" rev-parse HEAD)"
WORKERHOOKS="$ROOT/worker_hooks"; arm_hooks "$WORKERHOOKS" "$LOG"
sed -i 's/HOOK:/WORKERHOOK:/' "$WORKERHOOKS"/* 2>/dev/null
git -C "$H" config core.hooksPath "$WORKERHOOKS"
echo "-- dispatcher 'quarantines' the common hooks dir by renaming it --"
mv "$H/.git/hooks" "$H/.git/hooks.quarantined" 2>/dev/null; echo "hooks dir present? $([ -d "$H/.git/hooks" ] && echo yes || echo no)"
run "PC branch (worker hooksPath, common hooks GONE)" "$LOG" git -C "$H" branch z5pc4 "$HBASE"
run "worktree add -b (worker hooksPath)"           "$LOG" git -C "$H" worktree add --quiet -b hw "$ROOT/hw1" "$HBASE"
echo "-- and with the dispatcher pinning -c core.hooksPath=<empty> on the argv --"
EMPTY2="$ROOT/_e2"; mkdir -p "$EMPTY2"
run "worktree add -b + -c core.hooksPath=<EMPTY>"  "$LOG" git -C "$H" -c core.hooksPath="$EMPTY2" worktree add --quiet -b hw2 "$ROOT/hw2" "$HBASE"

echo
echo "########## 5. include.path indirection reaching core.hooksPath ##########"
I="$ROOT/increpo"; git init -q -b main "$I"; git -C "$I" config user.email a@b; git -C "$I" config user.name a
printf 'i\n' > "$I/i.txt"; git -C "$I" add -A; git -C "$I" commit -qm one
IBASE="$(git -C "$I" rev-parse HEAD)"
IH="$ROOT/inc_hooks"; arm_hooks "$IH" "$LOG"; sed -i 's/HOOK:/INCHOOK:/' "$IH"/* 2>/dev/null
printf '[core]\n\thooksPath = %s\n' "$IH" > "$ROOT/side.cfg"
printf '\n[include]\n\tpath = %s\n' "$ROOT/side.cfg" >> "$I/.git/config"
rm -rf "$I/.git/hooks"
run "PC/worktree add -b (hooksPath via include.path)" "$LOG" git -C "$I" worktree add --quiet -b iw "$ROOT/iw1" "$IBASE"
run "branch (hooksPath via include.path)"          "$LOG" git -C "$I" branch z5pc5 "$IBASE"

echo
echo "########## 6. extensions.worktreeConfig / config.worktree ##########"
echo "(measured on repo H's linked worktree)"
run "worktree add -b in H w/ worktreeConfig"       "$LOG" git -C "$H" worktree add --quiet -b hw3 "$ROOT/hw3" "$HBASE"

echo "ROOT kept at: $ROOT"
