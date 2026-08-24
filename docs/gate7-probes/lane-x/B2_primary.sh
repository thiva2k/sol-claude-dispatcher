#!/usr/bin/env bash
# PROBE B-primary: is the assume-unchanged bit per-worktree, and can the worker reach the primary index?
. "$(dirname "$0")/lib.sh"

mkrepo >/dev/null
sub "index files that exist"
find "$PRIMARY/.git" -name index

hr "B1p assume-unchanged set from the worktree — does the PRIMARY index get it?"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
git -C "$WT" update-index --assume-unchanged src/tracked.txt
sub "worktree ls-files -v"; git -C "$WT" ls-files -v src/tracked.txt
sub "primary  ls-files -v"; git -C "$PRIMARY" ls-files -v src/tracked.txt
sub "primary sees its own modification?"
printf 'alpha\nEVIL-P\n' > "$PRIMARY/src/tracked.txt"
git -C "$PRIMARY" status --porcelain

hr "B2p worker runs update-index against the PRIMARY tree directly (git -C is not denied)"
git -C "$PRIMARY" update-index --assume-unchanged src/tracked.txt; echo "exit=$?"
sub "primary ls-files -v"; git -C "$PRIMARY" ls-files -v src/tracked.txt
sub "primary_tree_status() now:"; git -C "$PRIMARY" status --porcelain
echo "(empty == compare_primary_tree() blinded on the PRIMARY tree)"
sub "primary file on disk"; cat "$PRIMARY/src/tracked.txt"

hr "B3p same via the deny-set-evading form: cd into primary, plain 'git update-index'"
mkrepo >/dev/null
printf 'alpha\nEVIL-P\n' > "$PRIMARY/src/tracked.txt"
( cd "$PRIMARY" && git update-index --assume-unchanged src/tracked.txt && echo "exit=$?" )
git -C "$PRIMARY" status --porcelain; echo "(empty == blinded)"

hr "B4p does 'git worktree add' for the NEXT task inherit the poisoned bit? (index is fresh)"
WT2="$ROOT/wt2"
git -C "$PRIMARY" worktree add --quiet -b task2 "$WT2" "$BASE" 2>&1
git -C "$WT2" ls-files -v src/tracked.txt
