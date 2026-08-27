#!/bin/bash
# Z17 fixture builder. Creates a throwaway repo with 3 commits, a base ref,
# and a registered detached task worktree. Prints shell assignments on stdout.
set -euo pipefail
ROOT=$(mktemp -d)
WTBASE=$(mktemp -d)
export GIT_CONFIG_NOSYSTEM=1
cd "$ROOT"
git init -q -b main .
git config user.email z17@probe.invalid
git config user.name Z17
echo one > a.txt; mkdir -p sub; echo two > sub/b.txt
git add -A; git commit -q -m c1
echo three > c.txt; git add -A; git commit -q -m c2
echo four >> a.txt; git add -A; git commit -q -m c3
BASE=$(git rev-parse HEAD)
TRUEROOT=$(git rev-list --max-parents=0 HEAD)
# decoy orphan root, unreachable from HEAD
DECOY=$(git commit-tree -m decoy $(git rev-parse HEAD^{tree}))
git worktree add --quiet --detach "$WTBASE/task-wt" "$BASE"
echo "ROOT=$ROOT"
echo "WT=$WTBASE/task-wt"
echo "BASE=$BASE"
echo "TRUEROOT=$TRUEROOT"
echo "DECOY=$DECOY"
