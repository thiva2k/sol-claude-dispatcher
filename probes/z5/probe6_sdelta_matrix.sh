#!/usr/bin/env bash
# PROBE 6 — the S-delta column, measured for EVERY command in src/** today,
# plus the full permitted repertoire. Arming: extensions.partialClone + promisor
# remote over ssh:// + core.sshCommand sentinel, and ONE base blob deleted with rm.
set -u
. "$(dirname "$0")/lib.sh"
ROOT="$(mktemp -d)"; echo "ROOT=$ROOT"; echo "git: $(git --version)"
LOG="$ROOT/fired.log"; : > "$LOG"
SSHP="$ROOT/sshprog"; printf '#!/bin/sh\nprintf "EXEC:core.sshCommand\\n" >> "%s"\nexit 1\n' "$LOG" > "$SSHP"; chmod 0755 "$SSHP"
R="$ROOT/r"
mkrepo() {
  rm -rf "$R"; git init -q -b main "$R"; git -C "$R" config user.email a@b; git -C "$R" config user.name a
  mkdir -p "$R/d"; printf 'VICTIMPAYLOAD\n' > "$R/d/big.txt"; printf 'other\n' > "$R/o.txt"
  git -C "$R" add -A; git -C "$R" commit -qm one
  BASE="$(git -C "$R" rev-parse HEAD)"; O="$(git -C "$R" rev-parse HEAD:d/big.txt)"
  arm_hooks "$R/.git/hooks" "$LOG"
  cat >> "$R/.git/config" <<CFG
[extensions]
	partialClone = evil
[remote "evil"]
	url = ssh://nosuchhost.invalid/repo.git
	promisor = true
	fetch = +refs/heads/*:refs/remotes/evil/*
[core]
	sshCommand = $SSHP
CFG
  rm -f "$R/.git/objects/${O:0:2}/${O:2}"     # worker deletes ONE base blob with plain rm
}
m() { mkrepo; run "$1" "$LOG" "${@:2}"; }

echo
echo "=== POSITIVE CONTROL: the arming is live (cat-file on the absent blob MUST fire) ==="
mkrepo; run "PC cat-file blob <ABSENT base blob>" "$LOG" git -C "$R" cat-file blob "$O"
mkrepo; run "PC branch (S-gamma still armed too)" "$LOG" git -C "$R" branch z5pc "$BASE"
echo
echo "=== S-delta column for the PERMITTED repertoire ==="
m "ls-tree -r -z --long <base>   [design argv]" git -C "$R" ls-tree -r -z --long "$BASE"
m "ls-tree -r -z <base>          [NO --long]"   git -C "$R" ls-tree -r -z "$BASE"
m "ls-tree -r <base>             [NO --long]"   git -C "$R" ls-tree -r "$BASE"
m "cat-file blob <ABSENT oid>"                  git -C "$R" cat-file blob "$O"
m "cat-file -p <base commit>"                   git -C "$R" cat-file -p "$BASE"
m "rev-parse --verify HEAD^{commit}"            git -C "$R" rev-parse --verify 'HEAD^{commit}'
m "rev-parse --show-toplevel"                   git -C "$R" rev-parse --show-toplevel
m "rev-parse --absolute-git-dir"                git -C "$R" rev-parse --absolute-git-dir
m "rev-parse --git-common-dir"                  git -C "$R" rev-parse --git-common-dir
m "rev-parse --is-inside-work-tree"             git -C "$R" rev-parse --is-inside-work-tree
m "worktree list --porcelain"                   git -C "$R" worktree list --porcelain
m "config --get remote.origin.url"              git -C "$R" config --get remote.origin.url
m "rev-list --max-parents=0 HEAD"               git -C "$R" rev-list --max-parents=0 HEAD
mkrepo; run "worktree add --quiet -b B P BASE   [git.py:609]" "$LOG" git -C "$R" worktree add --quiet -b z5b "$ROOT/wa1" "$BASE"
mkrepo; run "worktree add --no-checkout -b B P BASE [Z-4]"    "$LOG" git -C "$R" worktree add --quiet --no-checkout -b z5b "$ROOT/wa2" "$BASE"
echo
echo "=== S-delta column for the PROHIBITED set still in src/** today ==="
m "status --porcelain"                          git -C "$R" status --porcelain
m "diff <base>"                                 git -C "$R" diff "$BASE"
m "diff --name-only <base>"                     git -C "$R" diff --name-only "$BASE"
m "diff --stat <base>"                          git -C "$R" diff --stat "$BASE"
m "diff --check <base>"                         git -C "$R" diff --check "$BASE"
m "ls-files --others --exclude-standard"        git -C "$R" ls-files --others --exclude-standard
echo
echo "=== does GIT_NO_LAZY_FETCH=1 close the whole column? ==="
mkrepo; run "GIT_NO_LAZY_FETCH=1 ls-tree -r -z --long" "$LOG" env GIT_NO_LAZY_FETCH=1 git -C "$R" ls-tree -r -z --long "$BASE"
mkrepo; run "GIT_NO_LAZY_FETCH=1 cat-file blob <ABSENT>" "$LOG" env GIT_NO_LAZY_FETCH=1 git -C "$R" cat-file blob "$O"
mkrepo; run "GIT_NO_LAZY_FETCH=1 diff <base>"          "$LOG" env GIT_NO_LAZY_FETCH=1 git -C "$R" diff "$BASE"
mkrepo; run "GIT_NO_LAZY_FETCH=1 status --porcelain"   "$LOG" env GIT_NO_LAZY_FETCH=1 git -C "$R" status --porcelain
mkrepo; run "NEG CONTROL: same ls-tree WITHOUT the env (must FIRE)" "$LOG" git -C "$R" ls-tree -r -z --long "$BASE"
echo "ROOT kept at: $ROOT"
