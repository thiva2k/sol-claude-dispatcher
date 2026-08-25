#!/usr/bin/env bash
# Z7 PROBE 4b -- exact return codes when PREPARE cannot materialise.
set -u
W=$(mktemp -d /tmp/z7fc.XXXXXX); cd "$W"
git init -q origin; cd origin; git config user.email z@p; git config user.name z
git config uploadpack.allowFilter true; git config uploadpack.allowAnySHA1InWant true
echo S>small.txt; head -c 200000 /dev/urandom|base64>big.txt; git add -A; git commit -qm b
BIG=$(git rev-parse HEAD:big.txt); cd "$W"
git clone -q --filter=blob:none --no-checkout "file://$W/origin" e 2>/dev/null
cd e; git remote set-url origin "file://$W/GONE"
MISS=$(GIT_NO_LAZY_FETCH=1 git rev-list --objects --missing=print HEAD 2>/dev/null | sed -n 's/^?//p' | tr '\n' ' ')
echo "missing before: $(echo $MISS | wc -w)"

git fetch -q --no-tags origin $MISS >/dev/null 2>&1; echo "git fetch rc                    = $?"
GIT_NO_LAZY_FETCH=1 git rev-list --objects --missing=print HEAD >/dev/null 2>&1; echo "rev-list --missing=print rc     = $?"
echo "missing after failed fetch      = $(GIT_NO_LAZY_FETCH=1 git rev-list --objects --missing=print HEAD 2>/dev/null | grep -c '^?')"
echo "$BIG" | GIT_NO_LAZY_FETCH=1 git cat-file --batch >/dev/null 2>&1; echo "cat-file --batch PINNED rc      = $?"
echo "$BIG" | timeout 30 git cat-file --batch >/dev/null 2>&1; echo "cat-file --batch UNPINNED rc    = $?"
GIT_NO_LAZY_FETCH=1 git ls-tree -r -l HEAD >/dev/null 2>&1; echo "ls-tree -r -l PINNED rc         = $?"
GIT_NO_LAZY_FETCH=1 git ls-tree -r HEAD >/dev/null 2>&1; echo "ls-tree -r (no -l) PINNED rc    = $?"
git rev-parse --verify 'HEAD^{commit}' >/dev/null 2>&1; echo "rev-parse --verify HEAD rc      = $?"
echo
echo "--- raw-file detection of the promisor precondition (no git process) ---"
python3 - "$PWD" <<'PY'
import pathlib,sys,re
g=pathlib.Path(sys.argv[1])/".git"
cfg=(g/"config").read_text()
print("  extensions.partialClone in config :", bool(re.search(r'partialclone',cfg,re.I)))
print("  promisor = true in config         :", bool(re.search(r'promisor\s*=\s*true',cfg,re.I)))
print("  *.promisor pack marker files      :", len(list((g/'objects'/'pack').glob('*.promisor'))))
print("  remote urls in config             :", re.findall(r'url\s*=\s*(.+)', cfg))
PY
rm -rf "$W"
