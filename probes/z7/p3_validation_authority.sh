#!/usr/bin/env bash
# Z7 PROBE 3b -- can a VALIDATION command (or a descendant) contribute
# authority?  Reproduces server.py's real ordering:
#   2005 B2 rev-parse -> 2040 evidence A -> 2103 validation -> 2116 evidence B
#   -> 2123 check_scope (uses evidence B)  -> 2453 write_full_diff
set -u
W=$(mktemp -d /tmp/z7val.XXXXXX); cd "$W"
git init -q repo; cd repo; git config user.email z@p; git config user.name z
echo BASE > src.txt; git add -A; git commit -qm base
BASE=$(git rev-parse HEAD)
git worktree add -q "$W/task" -b task >/dev/null 2>&1
cd "$W/task"
echo "base_commit = $BASE"; echo

echo "--- worker runs and edits one in-scope file ---"
echo "WORKER-EDIT" >> src.txt
echo "  [2040] evidence A  diff --name-only : $(git diff --name-only $BASE | tr '\n' ' ')"
echo "  [2040] evidence A  status           : $(git status --porcelain | tr '\n' ' ')"
echo

echo "=== V1. validation command writes a file -> does it reach the AUTHORITATIVE decision? ==="
# this is an ordinary ValidationCommand: models.py rejects only sh/bash/zsh/dash/ksh/fish
python3 -c "open('OUT-OF-SCOPE.txt','w').write('written by the validation command')"
echo "  [2116] evidence B  diff --name-only : $(git diff --name-only $BASE | tr '\n' ' ')"
echo "  [2116] evidence B  status           : $(git status --porcelain | tr '\n' ' ')"
echo "  [2123] check_scope sees the file the VALIDATION command wrote, not the worker"
echo

echo "=== V2. validation command plants refs/replace -> does evidence B serve forged content? ==="
rm -f OUT-OF-SCOPE.txt
# a legal ValidationCommand argv[0]='git' (models.py permits it)
git -c user.email=v@v -c user.name=v stash -q 2>/dev/null || true
git checkout -q -- . 2>/dev/null || true
echo FORGED > src.txt; git add -A; git -c user.email=v@v -c user.name=v commit -qm forged >/dev/null
FORGED_TREE=$(git rev-parse 'HEAD^{tree}')
git reset -q --hard "$BASE"
echo "WORKER-EDIT" >> src.txt
BASE_TREE=$(git rev-parse "$BASE^{tree}")
mkdir -p "$W/repo/.git/refs/replace"
printf '%s\n' "$FORGED_TREE" > "$W/repo/.git/refs/replace/$BASE_TREE"
echo "  planted: refs/replace/$BASE_TREE -> $FORGED_TREE  (a plain file write)"
echo "  [2005] B2  rev-parse --verify HEAD^{commit} : $(git rev-parse --verify 'HEAD^{commit}')"
echo "         expected base_commit                : $BASE"
echo "  [2116] evidence B diff --name-only $BASE   : $(git diff --name-only $BASE | tr '\n' ' ')"
echo "  [2116] evidence B diff --stat              : $(git diff --stat $BASE | tail -1)"
echo "  [2453] write_full_diff  git diff $BASE     :"
git diff "$BASE" | sed 's/^/           /'
echo "  ^ the OLD side of the patch is the forged tree; the commit oid is correct"
echo
echo "=== V3. is the forgery visible to the raw-admin sealed fingerprint? ==="
python3 /home/dev/sol-claude-dispatcher/probes/z7/rawadmin.py "$W/task" 2>/dev/null \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("   replace refs:",d["identity_files"]["_replace_refs"]); print("   digest      :",d["identity_files"]["common/refs/replace/**"])'
echo
echo "=== V4. does the validation spawn appear in a git journal written by _run_git? ==="
echo "   validation.py:228 uses asyncio.create_subprocess_exec directly."
echo "   git.py's journal is written by _run_git (git.py:139-150). Disjoint."
echo "   -> a git validation command produces ZERO journal rows.  (static fact)"
rm -rf "$W"
