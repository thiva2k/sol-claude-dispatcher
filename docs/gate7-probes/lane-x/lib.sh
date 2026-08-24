#!/usr/bin/env bash
# Shared harness for GATE7 Lane X adversarial probes. Throwaway repos only.
# Reproduces the dispatcher's evidence surface EXACTLY as src/sol_claude_dispatcher/git.py does.

set -u

export GIT_TERMINAL_PROMPT=0
export GIT_OPTIONAL_LOCKS=0
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_CEILING_DIRECTORIES GIT_NAMESPACE 2>/dev/null

hr() { printf '\n===== %s =====\n' "$*"; }
sub() { printf -- '--- %s\n' "$*"; }

# Build a primary repo + a linked worktree, exactly like the dispatcher does
# (git worktree add -b <branch> <path> <start_commit>).
# Sets: PRIMARY, WT, BASE
mkrepo() {
  ROOT="$(mktemp -d)"
  PRIMARY="$ROOT/primary"
  mkdir -p "$PRIMARY"
  git -C "$PRIMARY" init -q -b main
  git -C "$PRIMARY" config user.email probe@example.invalid
  git -C "$PRIMARY" config user.name Probe
  mkdir -p "$PRIMARY/src" "$PRIMARY/secrets"
  printf 'alpha\n' > "$PRIMARY/src/tracked.txt"
  printf 'beta\n'  > "$PRIMARY/src/other.txt"
  printf 'top\n'   > "$PRIMARY/README.md"
  printf 'keep\n'  > "$PRIMARY/secrets/.keep"
  git -C "$PRIMARY" add -A
  git -C "$PRIMARY" commit -q -m init
  BASE="$(git -C "$PRIMARY" rev-parse HEAD)"
  WT="$ROOT/wt"
  git -C "$PRIMARY" worktree add --quiet -b task "$WT" "$BASE"
  echo "ROOT=$ROOT"
}

# The five commands collect_diff_evidence() runs, in order, verbatim.
evidence() {
  local wt="$1" base="$2"
  sub "git status --porcelain"
  git -C "$wt" status --porcelain
  sub "git diff --name-only $base  (-> tracked_changed)"
  git -C "$wt" diff --name-only "$base"
  sub "git ls-files --others --exclude-standard  (-> untracked)"
  git -C "$wt" ls-files --others --exclude-standard
  sub "git diff --stat $base"
  git -C "$wt" diff --stat "$base"
  sub "git diff $base  (byte count of patch)"
  git -C "$wt" diff "$base" | wc -c
  sub "git diff --check $base ; exit code"
  git -C "$wt" diff --check "$base"; echo "exit=$?"
}

# changed_paths as the dispatcher computes it: name-only ++ ls-files --others
changed_paths() {
  local wt="$1" base="$2"
  { git -C "$wt" diff --name-only "$base"; git -C "$wt" ls-files --others --exclude-standard; } \
    | awk 'NF' | awk '!seen[$0]++'
}
