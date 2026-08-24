#!/usr/bin/env bash
# PROBE D: is amendment #3 (-z / NUL-delimited) implementable as written?
# Test names: cafe-with-acute, a name with a space, a name with a NEWLINE,
# a name with a double-quote, a name with a backslash, a name with a tab.
. "$(dirname "$0")/lib.sh"

mkrepo >/dev/null

CAFE=$'caf\xc3\xa9.txt'
SPACE='with space.txt'
NL=$'new\nline.txt'
QUOTE='dq".txt'
BS='back\slash.txt'
TAB=$'ta\tb.txt'
ARROW=$'arrow\xe2\x86\x92.txt'

mkdir -p "$WT/secrets"
for n in "$CAFE" "$SPACE" "$NL" "$QUOTE" "$BS" "$TAB" "$ARROW"; do
  printf 'x\n' > "$WT/secrets/$n" 2>/dev/null || echo "COULD NOT CREATE: $(printf %q "$n")"
done
# also a TRACKED file with a non-ASCII name, modified
git -C "$WT" -c core.quotePath=true add -A >/dev/null 2>&1
git -C "$WT" -c user.email=p@x -c user.name=p commit -qm names >/dev/null 2>&1
TRACKBASE="$(git -C "$WT" rev-parse HEAD)"
for n in "$CAFE" "$NL" "$SPACE"; do printf 'x\nMOD\n' > "$WT/secrets/$n"; done
printf 'untracked\n' > "$WT/secrets/$CAFE.new"

hr "D0 files actually on disk"
ls -b "$WT/secrets"

hr "D1 DEFAULT (what the dispatcher does today) — ls-files --others --exclude-standard"
git -C "$WT" ls-files --others --exclude-standard | cat -A | sed -n 1,20p

hr "D2 DEFAULT — git diff --name-only <base>"
git -C "$WT" diff --name-only "$TRACKBASE" | cat -A

hr "D3 DEFAULT — git status --porcelain"
git -C "$WT" status --porcelain | cat -A

hr "D4 -z on ls-files --others --exclude-standard  (raw bytes, NUL separated)"
git -C "$WT" ls-files --others --exclude-standard -z | od -c | head -20
sub "decoded as python list"
git -C "$WT" ls-files --others --exclude-standard -z | python3 -c "
import sys
d=sys.stdin.buffer.read()
parts=[p for p in d.split(b'\0') if p]
for p in parts: print(repr(p), '->', p.decode('utf-8','replace'))
print('COUNT', len(parts))"

hr "D5 -z on git diff --name-only"
git -C "$WT" diff --name-only -z "$TRACKBASE" | python3 -c "
import sys
d=sys.stdin.buffer.read()
parts=[p for p in d.split(b'\0') if p]
for p in parts: print(repr(p), '->', p.decode('utf-8','replace'))
print('COUNT', len(parts))"
sub "raw od"
git -C "$WT" diff --name-only -z "$TRACKBASE" | od -c | head

hr "D6 -z on git status --porcelain"
git -C "$WT" status --porcelain -z | python3 -c "
import sys
d=sys.stdin.buffer.read()
parts=[p for p in d.split(b'\0') if p]
for p in parts: print(repr(p))
print('COUNT', len(parts))"

hr "D7 -z HAZARD: renames in status --porcelain -z use TWO NUL-terminated fields (order reversed)"
git -C "$WT" mv "$WT/secrets/$SPACE" "$WT/secrets/renamed target.txt" 2>&1
sub "non -z"; git -C "$WT" status --porcelain | cat -A | grep -i renam
sub "-z"; git -C "$WT" status --porcelain -z | python3 -c "
import sys
d=sys.stdin.buffer.read()
for p in d.split(b'\0'):
    if p: print(repr(p))"
echo "NOTE: an 'R  new' entry is followed by a SEPARATE NUL-terminated field holding the OLD name,"
echo "      with NO status prefix. Naive 'split on NUL then take [3:]' yields a bogus path."

hr "D8 -z on git diff --name-only for a RENAME (-M)"
git -C "$WT" diff --name-only -z -M "$TRACKBASE" | python3 -c "
import sys
d=sys.stdin.buffer.read()
for p in d.split(b'\0'):
    if p: print(repr(p))"
sub "and with --diff-filter/raw -z (rename => two path fields)"
git -C "$WT" diff --raw -z -M "$TRACKBASE" | od -c | head -20

hr "D9 does --stat / --check / the patch itself still mangle names? (-z is NOT accepted there)"
sub "git diff --stat -z"; git -C "$WT" diff --stat -z "$TRACKBASE" 2>&1 | head -5; echo "exit=$?"
sub "git diff --check -z"; git -C "$WT" diff --check -z "$TRACKBASE" 2>&1 | head -5; echo "exit=$?"
sub "git diff --stat (default)"; git -C "$WT" diff --stat "$TRACKBASE" | cat -A | head
sub "patch headers (default)"; git -C "$WT" diff "$TRACKBASE" | grep -a '^diff --git' | cat -A

hr "D10 core.quotePath=false — the OTHER fix. Does it give raw bytes?"
sub "ls-files --others"; git -C "$WT" -c core.quotePath=false ls-files --others --exclude-standard | cat -A
sub "diff --name-only"; git -C "$WT" -c core.quotePath=false diff --name-only "$TRACKBASE" | cat -A
sub "status --porcelain"; git -C "$WT" -c core.quotePath=false status --porcelain | cat -A
echo "NOTE: quotePath=false emits RAW bytes but keeps NEWLINE separation -> newline names still split."
sub "patch headers with quotePath=false"; git -C "$WT" -c core.quotePath=false diff "$TRACKBASE" | grep -a '^diff --git' | cat -A

hr "D11 can a worker DISABLE the dispatcher's chosen quoting via shared .git/config?"
git -C "$WT" config core.quotePath false
sub "dispatcher runs plain 'git status --porcelain' -> "; git -C "$WT" status --porcelain | cat -A | head -5
echo "NOTE: if the design relies on default quoting, the worker can flip it; if it passes -c/-z explicitly, it cannot."
sub "can the worker override an explicit -c on the command line?"
git -C "$WT" -c core.quotePath=true status --porcelain | cat -A | head -3

hr "D12 -z support matrix (does the flag even exist?)"
for c in "ls-files --others --exclude-standard -z" "diff --name-only -z" "status --porcelain -z" \
         "diff --stat -z" "diff --check -z" "diff --numstat -z" "diff --raw -z" "ls-files -v -z"; do
  out=$(git -C "$WT" $c "$TRACKBASE" 2>&1 >/dev/null)
  rc=$?
  printf '%-45s rc=%s %s\n' "git $c" "$rc" "$(echo "$out" | head -1)"
done
