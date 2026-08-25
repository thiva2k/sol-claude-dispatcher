#!/usr/bin/env bash
# PROBE 1.3 — is there a materialisation path that fires NOTHING, and is the
# resulting worktree usable by a real worker (git status / git diff / an edit)?
set -u
. "$(dirname "$0")/lib.sh"
ROOT="$(mktemp -d)"; echo "ROOT=$ROOT"; echo "git: $(git --version)"
LOG="$ROOT/fired.log"; : > "$LOG"; SD="$ROOT/_sentinel"
R="$ROOT/primary"
git init -q -b main "$R"; git -C "$R" config user.email a@b; git -C "$R" config user.name a
mkdir -p "$R/src"
printf 'line1\nline2\n' > "$R/src/a.txt"; printf 'payload\n' > "$R/bin.dat"
ln -s src/a.txt "$R/link.txt"
printf '#!/bin/sh\necho hi\n' > "$R/run.sh"; chmod 0755 "$R/run.sh"
git -C "$R" add -A; git -C "$R" commit -qm base
BASE="$(git -C "$R" rev-parse HEAD)"
echo "BASE=$BASE"
arm_hooks "$R/.git/hooks" "$LOG"; arm_config_exec "$R" "$SD" "$LOG"
printf '* filter=zf diff=zd\n' > "$R/.git/info/attributes" 2>/dev/null || { mkdir -p "$R/.git/info"; printf '* filter=zf diff=zd\n' > "$R/.git/info/attributes"; }
run "POSITIVE CONTROL git branch (arming live)" "$LOG" git -C "$R" branch z5pc "$BASE"

WT="$ROOT/rawwt"; NAME="rawwt"
ADMIN="$R/.git/worktrees/$NAME"

echo
echo "=== A. dispatcher_raw: build the worktree administrative files with PLAIN FILE I/O ==="
: > "$LOG"
mkdir -p "$ADMIN" "$WT"
printf '%s\n' "$BASE"                    > "$ADMIN/HEAD"          # detached: no branch ref, no ref txn
printf '../..\n'                         > "$ADMIN/commondir"
printf '%s\n' "$WT/.git"                 > "$ADMIN/gitdir"
printf 'gitdir: %s\n' "$ADMIN"           > "$WT/.git"
echo "  files created: $(ls "$ADMIN" | tr '\n' ' ')"
echo "  hooks/config sentinels fired during raw construction: [$(cat "$LOG" | tr '\n' ' ')]  <-- no git process ran"

echo
echo "=== B. materialise CONTENT from raw blob bytes (dispatcher writes them) ==="
: > "$LOG"
# enumerate the tree WITHOUT git?  We use ls-tree/cat-file which are the permitted
# repertoire; both are measured clean on S-alpha/beta/gamma.
git -C "$R" ls-tree -r --long "$BASE" | while read -r mode typ oid size path; do
  case "$mode" in
    120000) tgt="$(git -C "$R" cat-file blob "$oid")"; mkdir -p "$WT/$(dirname "$path")"; ln -sfn "$tgt" "$WT/$path" ;;
    100755) mkdir -p "$WT/$(dirname "$path")"; git -C "$R" cat-file blob "$oid" > "$WT/$path"; chmod 0755 "$WT/$path" ;;
    *)      mkdir -p "$WT/$(dirname "$path")"; git -C "$R" cat-file blob "$oid" > "$WT/$path"; chmod 0644 "$WT/$path" ;;
  esac
done
echo "  fired during ls-tree + cat-file materialisation: [$(cat "$LOG" | tr '\n' ' ')]"
echo "  tree:"; (cd "$WT" && find . -not -path './.git*' | sort | sed 's/^/    /')
echo "  bytes of bin.dat (must be RAW blob, not smudged):"; od -c "$WT/bin.dat" | head -2 | sed 's/^/    /'

echo
echo "=== C. IS IT USABLE BY A WORKER?  (no index has been written) ==="
: > "$LOG"
echo "--- git status --porcelain (as a worker would run it) ---"
timeout 20 git -C "$WT" status --porcelain </dev/null 2>&1 | head -15 | sed 's/^/    /'
echo "    fired: [$(cat "$LOG" | tr '\n' ' ')]"
: > "$LOG"
echo "--- git rev-parse HEAD / --show-toplevel / --git-common-dir ---"
timeout 10 git -C "$WT" rev-parse HEAD </dev/null 2>&1 | sed 's/^/    /'
timeout 10 git -C "$WT" rev-parse --show-toplevel </dev/null 2>&1 | sed 's/^/    /'
timeout 10 git -C "$WT" rev-parse --git-common-dir </dev/null 2>&1 | sed 's/^/    /'
: > "$LOG"
echo "--- git diff (worker) ---"
timeout 20 git -C "$WT" diff </dev/null 2>&1 | head -10 | sed 's/^/    /'
echo "    fired: [$(cat "$LOG" | tr '\n' ' ')]"
echo "--- git log -1 --oneline ---"
timeout 10 git -C "$WT" log -1 --oneline </dev/null 2>&1 | sed 's/^/    /'
echo "--- worktree list --porcelain (does the primary see it?) ---"
timeout 10 git -C "$R" worktree list --porcelain </dev/null 2>&1 | sed 's/^/    /'

echo
echo "=== D. a REAL worker edit, then what the dispatcher can measure ==="
printf 'line1\nline2\nline3-ADDED\n' > "$WT/src/a.txt"
: > "$LOG"
echo "--- git status --porcelain after the edit ---"
timeout 20 git -C "$WT" status --porcelain </dev/null 2>&1 | head -15 | sed 's/^/    /'
echo "--- git diff --stat after the edit ---"
timeout 20 git -C "$WT" diff --stat </dev/null 2>&1 | head -10 | sed 's/^/    /'
echo "    fired: [$(cat "$LOG" | tr '\n' ' ')]"

echo
echo "=== E. now give it an INDEX. Which mechanisms fire? ==="
: > "$LOG"; run "read-tree BASE into the raw worktree (Z-4 step 2)"  "$LOG" git -C "$WT" read-tree "$BASE"
: > "$LOG"; run "read-tree + -c core.hooksPath=<empty>"              "$LOG" git -C "$WT" -c core.hooksPath="$ROOT/_e" read-tree "$BASE"
mkdir -p "$ROOT/_e"
: > "$LOG"; run "read-tree + -c core.hooksPath=<empty dir, exists>"  "$LOG" git -C "$WT" -c core.hooksPath="$ROOT/_e" read-tree "$BASE"
: > "$LOG"
echo "--- git status --porcelain WITH an index ---"
timeout 20 git -C "$WT" status --porcelain </dev/null 2>&1 | head -15 | sed 's/^/    /'
echo "    fired: [$(cat "$LOG" | tr '\n' ' ')]"

echo
echo "=== F. the alternative: worktree add --no-checkout with hooks made UNREACHABLE first ==="
: > "$LOG"
EMPTY="$ROOT/_empty2"; mkdir -p "$EMPTY"
run "worktree add --no-checkout -b + -c core.hooksPath=<empty>" "$LOG" git -C "$R" -c core.hooksPath="$EMPTY" worktree add --quiet --no-checkout -b z5nb "$ROOT/wt_nc" "$BASE"
run "NEG CONTROL same without the override (must FIRE)"         "$LOG" git -C "$R" worktree add --quiet --no-checkout -b z5nb2 "$ROOT/wt_nc2" "$BASE"
echo "ROOT kept at: $ROOT"
