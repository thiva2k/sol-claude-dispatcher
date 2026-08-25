#!/usr/bin/env bash
# Z7 PROBE 2d -- the exact F-5 B2 scenario, verbatim, plus the confounded rows.
set -u
W=$(mktemp -d /tmp/z7b2.XXXXXX)
git init -q "$W/real"; cd "$W/real"; git config user.email z@p; git config user.name z
echo BASE > f.txt; git add -A; git commit -qm base
BASE=$(git rev-parse HEAD)
git worktree add -q "$W/task" -b task >/dev/null 2>&1
GD="$W/real/.git/worktrees/task"
echo "recorded base_commit = $BASE"
echo
echo "=== 1. worker moves HEAD (an ordinary commit), B2 with NO poison ==="
cd "$W/task"; echo WORKER >> f.txt; git add -A; git -c user.email=w@w -c user.name=w commit -qm worker >/dev/null
OUT=$(git rev-parse --verify 'HEAD^{commit}' 2>&1); RC=$?
echo "  rev-parse --verify HEAD^{commit} -> rc=$RC out=$OUT"
[ "$OUT" = "$BASE" ] && echo "  B2 VERDICT: PASS (wrong!)" || echo "  B2 VERDICT: FAIL  <-- B2 works when un-poisoned"
echo
echo "=== 2. same, + worker writes expected base oid into worktrees/task/HEAD ==="
printf '%s\n' "$BASE" > "$GD/HEAD"
OUT=$(git -C "$W/task" rev-parse --verify 'HEAD^{commit}' 2>&1); RC=$?
echo "  rev-parse --verify HEAD^{commit} -> rc=$RC out=$OUT"
[ "$OUT" = "$BASE" ] && echo "  B2 VERDICT: PASS  <-- B2 DEFEATED, expected SHA, rc=0" || echo "  B2 VERDICT: FAIL"
echo "  branch refs/heads/task still at: $(git -C "$W/real" rev-parse refs/heads/task)"
echo "  worker's commit is still reachable and its tree is still on disk"
echo "  --absolute-git-dir : $(git -C "$W/task" rev-parse --absolute-git-dir)"
echo "  --git-common-dir   : $(cd "$W/task" && git rev-parse --path-format=absolute --git-common-dir)"
echo "  --show-toplevel    : $(git -C "$W/task" rev-parse --show-toplevel)"
echo "  no alternates file : $([ -e "$W/real/.git/objects/info/alternates" ] && echo PRESENT || echo ABSENT)"
echo
echo "=== 3. RAW reader of worktrees/task/HEAD, sealed at PREPARE ==="
echo "  sealed value would have been: ref: refs/heads/task -> $BASE"
echo "  raw HEAD now                : $(cat "$GD/HEAD")"
echo "  raw refs/heads/task now     : $(cat "$W/real/.git/refs/heads/task" 2>/dev/null || git -C "$W/real" rev-parse refs/heads/task)"
echo
echo "=== 4. info/grafts -- exact rc and stderr (row E2 was confounded) ==="
W2=$(mktemp -d /tmp/z7gr.XXXXXX); git init -q "$W2/r"; cd "$W2/r"
git config user.email z@p; git config user.name z
echo a>a; git add -A; git commit -qm one; A=$(git rev-parse HEAD)
echo b>b; git add -A; git commit -qm two; B=$(git rev-parse HEAD)
mkdir -p .git/info; printf '%s\n' "$B" > .git/info/grafts   # make B a root
echo "  --- rev-list --max-parents=0 HEAD with grafts:"
git rev-list --max-parents=0 HEAD; echo "  rc=$?"
echo "  --- stderr:"; git rev-list --max-parents=0 HEAD 2>&1 1>/dev/null | sed 's/^/    /'
echo "  true root = $A ; HEAD = $B"
echo
echo "=== 5. does --no-replace-objects / GIT_NO_REPLACE_OBJECTS neutralise D? ==="
W3=$(mktemp -d /tmp/z7rp.XXXXXX); git init -q "$W3/r"; cd "$W3/r"
git config user.email z@p; git config user.name z
echo REAL>m.txt; git add -A; git commit -qm r; R=$(git rev-parse HEAD)
echo FAKEBLOB>m.txt; git add -A; git -c user.email=z@p -c user.name=z commit -qm f; F=$(git rev-parse HEAD)
git reset -q --hard "$R"
mkdir -p .git/refs/replace; printf '%s\n' "$F" > ".git/refs/replace/$R"
echo "  plain          : $(git show HEAD:m.txt 2>&1)"
echo "  --no-replace   : $(git --no-replace-objects show HEAD:m.txt 2>&1)"
echo "  GIT_NO_REPLACE : $(GIT_NO_REPLACE_OBJECTS=1 git show HEAD:m.txt 2>&1)"
echo "  cat-file batch plain    : $(git rev-parse HEAD:m.txt | git cat-file --batch | sed -n 2p)"
echo "  ls-tree plain           : $(git ls-tree -r --name-only HEAD | tr '\n' ' ')"
echo "  rev-parse HEAD^{commit} : $(git rev-parse --verify 'HEAD^{commit}')  (expected $R)"
rm -rf "$W" "$W2" "$W3"
