#!/usr/bin/env bash
# PROBE B: can a worker suppress a modification to a TRACKED file?
. "$(dirname "$0")/lib.sh"

hr "B0 BASELINE: modify tracked src/tracked.txt, no suppression"
mkrepo >/dev/null
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
evidence "$WT" "$BASE"

hr "B1 git update-index --assume-unchanged  (NOT in the deny set)"
mkrepo >/dev/null
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
git -C "$WT" update-index --assume-unchanged src/tracked.txt; echo "update-index exit=$?"
evidence "$WT" "$BASE"
sub "changed_paths"; changed_paths "$WT" "$BASE"
sub "actual file content on disk"; cat "$WT/src/tracked.txt"
sub "git ls-files -v (lowercase flag = suppressed)"; git -C "$WT" ls-files -v src/
sub "does it survive to the PRIMARY tree? (index is PER-WORKTREE)"
ls -l "$PRIMARY/.git/index" "$PRIMARY/.git/worktrees/task/index" 2>&1
printf 'alpha\nEVIL-P\n' > "$PRIMARY/src/tracked.txt"
echo "primary status:"; git -C "$PRIMARY" status --porcelain

hr "B2 git update-index --skip-worktree"
mkrepo >/dev/null
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
git -C "$WT" update-index --skip-worktree src/tracked.txt; echo "exit=$?"
evidence "$WT" "$BASE"
sub "ls-files -v"; git -C "$WT" ls-files -v src/

hr "B3 assume-unchanged on a file the worker then DELETES"
mkrepo >/dev/null
git -C "$WT" update-index --assume-unchanged src/tracked.txt
rm "$WT/src/tracked.txt"
evidence "$WT" "$BASE"
sub "file gone?"; ls "$WT/src/"

hr "B4 assume-unchanged applied to EVERY tracked file at once"
mkrepo >/dev/null
git -C "$WT" ls-files -z | xargs -0 git -C "$WT" update-index --assume-unchanged
printf 'PWNED\n' > "$WT/src/tracked.txt"
printf 'PWNED\n' > "$WT/README.md"
evidence "$WT" "$BASE"

hr "B5 core.fileMode / index refresh: does 'git add' undo assume-unchanged? (worker can re-set)"
mkrepo >/dev/null
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
git -C "$WT" add src/tracked.txt 2>&1; echo "add exit=$?"
git -C "$WT" update-index --assume-unchanged src/tracked.txt; echo "assume exit=$?"
sub "STAGED change + assume-unchanged"
evidence "$WT" "$BASE"

hr "B6 write a whole fake index via update-index --index-info (content substitution)"
mkrepo >/dev/null
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
# stage a blob whose content is the ORIGINAL, while disk holds EVIL, then assume-unchanged
BLOB=$(printf 'alpha\n' | git -C "$WT" hash-object -w --stdin)
echo "100644 $BLOB	src/tracked.txt" | git -C "$WT" update-index --index-info
git -C "$WT" update-index --assume-unchanged src/tracked.txt
evidence "$WT" "$BASE"
sub "disk content"; cat "$WT/src/tracked.txt"

hr "B7 .gitattributes -diff on a tracked file (recap; contrast with assume-unchanged)"
mkrepo >/dev/null
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
printf 'src/tracked.txt -diff\n' > "$WT/.gitattributes"
evidence "$WT" "$BASE"

hr "B8 \$GIT_COMMON_DIR/info/attributes -diff (invisible + reaches PRIMARY)"
mkrepo >/dev/null
COMMON="$(git -C "$WT" rev-parse --git-common-dir)"
mkdir -p "$COMMON/info"
printf 'src/tracked.txt -diff\n' > "$COMMON/info/attributes"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
evidence "$WT" "$BASE"
sub "PRIMARY tree: modify same file, then primary_tree_status()/diff"
printf 'alpha\nEVIL-P\n' > "$PRIMARY/src/tracked.txt"
git -C "$PRIMARY" status --porcelain
git -C "$PRIMARY" diff --stat
git -C "$PRIMARY" diff | wc -c
