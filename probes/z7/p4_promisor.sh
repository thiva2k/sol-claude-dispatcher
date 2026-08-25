#!/usr/bin/env bash
# Z7 PROBE 4 -- partial clone / promisor with a GENUINELY ABSENT object.
# v2: origin must set uploadpack.allowFilter, otherwise file:// silently
# ignores --filter and the clone is NOT partial (v1 fell into exactly the
# trap it was written to avoid; that run is reported as VOID).
set -u
W=$(mktemp -d /tmp/z7prom.XXXXXX); cd "$W"
git init -q origin; cd origin; git config user.email z@p; git config user.name z
git config uploadpack.allowFilter true
git config uploadpack.allowAnySHA1InWant true
echo SMALL > small.txt; head -c 200000 /dev/urandom | base64 > big.txt; echo OTHER > other.txt
git add -A; git commit -qm base
BASE=$(git rev-parse HEAD); BIG=$(git rev-parse HEAD:big.txt)
cd "$W"

mkpc() { rm -rf "$1"; git clone -q --filter=blob:none --no-checkout "file://$W/origin" "$1" 2>&1 | sed 's/^/    /'; }
nmiss() { GIT_NO_LAZY_FETCH=1 git -C "$1" rev-list --objects --missing=print HEAD 2>/dev/null | grep -c '^?'; }

echo "=== PRECONDITION: is the clone GENUINELY partial? ==="
mkpc pc
echo "  extensions.partialClone      : $(git -C pc config --get extensions.partialClone || echo '(none)')"
echo "  remote.origin.promisor       : $(git -C pc config --get remote.origin.promisor || echo '(none)')"
echo "  objects/pack/*.promisor      : $(ls pc/.git/objects/pack/*.promisor 2>/dev/null | wc -l)"
echo "  missing objects reachable from HEAD : $(nmiss pc)"
echo "  cat-file -e \$BIG under GIT_NO_LAZY_FETCH=1 : $(GIT_NO_LAZY_FETCH=1 git -C pc cat-file -e "$BIG" 2>&1 && echo PRESENT || echo ABSENT)"
if [ "$(nmiss pc)" = "0" ]; then echo "  *** STILL NOT PARTIAL -- every row below is VOID ***"; fi
echo

echo "=== A. detection of absence WITHOUT permitting a fetch ==="
echo "  batch-check (pinned):"; echo "$BIG" | GIT_NO_LAZY_FETCH=1 git -C pc cat-file --batch-check 2>&1 | sed 's/^/    /'
echo "  batch       (pinned):"; echo "$BIG" | GIT_NO_LAZY_FETCH=1 git -C pc cat-file --batch 2>&1 | head -2 | cut -c1-80 | sed 's/^/    /'
echo "    rc=${PIPESTATUS[1]}"
echo "  ls-tree -r -l HEAD (pinned) -- is the SIZE column still right?"
GIT_NO_LAZY_FETCH=1 git -C pc ls-tree -r -l HEAD 2>&1 | sed 's/^/    /'
echo "  rev-list --missing=print (pinned):"
GIT_NO_LAZY_FETCH=1 git -C pc rev-list --objects --missing=print HEAD 2>/dev/null | grep '^?' | sed 's/^/    /'
echo

echo "=== B. UNPINNED cat-file --batch on an absent object: does it fetch? ==="
mkpc pcb >/dev/null
echo "  before: missing=$(nmiss pcb)  \$BIG present? $(GIT_NO_LAZY_FETCH=1 git -C pcb cat-file -e "$BIG" 2>/dev/null && echo YES || echo NO)"
OUT=$(echo "$BIG" | git -C pcb cat-file --batch 2>&1 | head -1 | cut -c1-70); RC=$?
echo "  cat-file --batch (NO pin) rc=$RC header=[$OUT]"
echo "  after : missing=$(nmiss pcb)  \$BIG present? $(GIT_NO_LAZY_FETCH=1 git -C pcb cat-file -e "$BIG" 2>/dev/null && echo YES || echo NO)"
echo "  --> a network fetch ran inside a command the design calls read-only"
echo

echo "=== C. MATERIALISATION strategies during PREPARE ==="
for M in fetch-listed checkout refetch-nofilter blob-limit-none; do
  mkpc m >/dev/null
  T0=$(date +%s.%N); ERR=""
  case $M in
    fetch-listed)
      MISS=$(GIT_NO_LAZY_FETCH=1 git -C m rev-list --objects --missing=print HEAD 2>/dev/null | sed -n 's/^?//p')
      ERR=$(git -C m fetch -q --no-tags --no-write-fetch-head origin $MISS 2>&1 | head -1) ;;
    checkout)  ERR=$(git -C m checkout -q 2>&1 | head -1) ;;
    refetch-nofilter) ERR=$(git -C m fetch -q --refetch --filter= origin 2>&1 | head -1) ;;
    blob-limit-none)  ERR=$(git -C m -c remote.origin.partialclonefilter= fetch -q --refetch origin 2>&1 | head -1) ;;
  esac
  T1=$(date +%s.%N)
  printf '  %-18s t=%6.3fs missing_after=%-3s %s\n' "$M" "$(echo "$T1-$T0"|bc)" "$(nmiss m)" "$ERR"
done
echo

echo "=== D. does materialisation SURVIVE?  can the worker re-absent an object? ==="
mkpc d >/dev/null
MISS=$(GIT_NO_LAZY_FETCH=1 git -C d rev-list --objects --missing=print HEAD 2>/dev/null | sed -n 's/^?//p')
git -C d fetch -q --no-tags --no-write-fetch-head origin $MISS 2>/dev/null
echo "  after PREPARE materialisation: missing=$(nmiss d)"
echo "  worker runs: git -C d gc --prune=now  (or deletes a loose object)"
git -C d gc -q --prune=now 2>/dev/null
echo "  after worker gc              : missing=$(nmiss d)"
echo "  still a promisor remote?     : $(git -C d config --get remote.origin.promisor || echo '(none)')"
echo "  --> if the promisor remote survives, absence is re-creatable AFTER sealing"
echo

echo "=== E. PREPARE CANNOT materialise: promisor remote unreachable ==="
mkpc e >/dev/null
git -C e remote set-url origin "file://$W/GONE"
MISS=$(GIT_NO_LAZY_FETCH=1 git -C e rev-list --objects --missing=print HEAD 2>/dev/null | sed -n 's/^?//p')
echo "  fetch: $(git -C e fetch -q --no-tags origin $MISS 2>&1 | head -2 | tr '\n' ' ')"
echo "  rc=$?  missing_after=$(nmiss e)"
echo "  UNPINNED cat-file --batch against the dead promisor (i.e. NOT failing closed):"
echo "$BIG" | timeout 30 git -C e cat-file --batch 2>&1 | head -2 | cut -c1-90 | sed 's/^/    /'
echo "    rc=$?"
echo

echo "=== F. POSITIVE CONTROL: full clone ==="
rm -rf full; git clone -q "file://$W/origin" full 2>/dev/null
echo "  missing=$(nmiss full)  promisor packs=$(ls full/.git/objects/pack/*.promisor 2>/dev/null|wc -l)  remote.origin.promisor=$(git -C full config --get remote.origin.promisor || echo '(none)')"
echo "WORKDIR=$W"
