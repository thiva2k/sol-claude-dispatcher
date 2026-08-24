#!/usr/bin/env bash
# PROBE E: which dispatcher-side levers actually neutralise the worker's config?
# Command-line -c beats repository config (proved in D11). How far does that go?
. "$(dirname "$0")/lib.sh"
MARKDIR=""
payload() { cat > "$ROOT/pay-$1.sh" <<EOF
#!/bin/sh
echo "EXECUTED tag=$1" >> "$MARKDIR/fired"
exit 0
EOF
chmod +x "$ROOT/pay-$1.sh"; echo "$ROOT/pay-$1.sh"; }
fresh() { mkrepo >/dev/null; MARKDIR="$ROOT/marks"; mkdir -p "$MARKDIR"; : > "$MARKDIR/fired"; }
verdict() { if [ -s "$MARKDIR/fired" ]; then echo "*** STILL EXECUTED (lever FAILED)"; cat "$MARKDIR/fired"; else echo "neutralised (no execution)"; fi; }

hr "E1 -c core.fsmonitor= (empty) on the dispatcher's argv"
fresh; P=$(payload fsm); git -C "$WT" config core.fsmonitor "$P"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
sub "without the lever"; git -C "$WT" status --porcelain >/dev/null 2>&1; verdict
: > "$MARKDIR/fired"
sub "with -c core.fsmonitor="; git -C "$WT" -c core.fsmonitor= status --porcelain >/dev/null 2>&1; verdict
: > "$MARKDIR/fired"
sub "with -c core.fsmonitor=false"; git -C "$WT" -c core.fsmonitor=false status --porcelain >/dev/null 2>&1; verdict

hr "E2 --no-textconv / --no-ext-diff against textconv + external diff"
fresh; P=$(payload tc); git -C "$WT" config diff.evil.textconv "$P"; git -C "$WT" config diff.external "$P"
printf 'src/tracked.txt diff=evil\n' > "$WT/.gitattributes"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
sub "plain git diff"; git -C "$WT" diff "$BASE" >/dev/null 2>&1; verdict
: > "$MARKDIR/fired"
sub "git diff --no-textconv --no-ext-diff"; git -C "$WT" diff --no-textconv --no-ext-diff "$BASE" >/dev/null 2>&1; verdict
: > "$MARKDIR/fired"
sub "git diff --stat  (does --stat run textconv?)"; git -C "$WT" diff --stat "$BASE" >/dev/null 2>&1; verdict
: > "$MARKDIR/fired"
sub "git diff --stat --no-textconv --no-ext-diff"; git -C "$WT" diff --stat --no-textconv --no-ext-diff "$BASE" >/dev/null 2>&1; verdict
: > "$MARKDIR/fired"
sub "git status --porcelain (unaffected by --no-textconv; does status exec?)"; git -C "$WT" status --porcelain >/dev/null 2>&1; verdict

hr "E3 filter.clean: is there ANY flag that stops git diff/status running it?"
fresh; P=$(payload fc); git -C "$WT" config filter.evil.clean "$P"
printf 'src/tracked.txt filter=evil\n' > "$WT/.gitattributes"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
for lever in "" "--no-textconv --no-ext-diff"; do
  : > "$MARKDIR/fired"
  sub "git diff $lever"; git -C "$WT" diff $lever "$BASE" >/dev/null 2>&1; verdict
done
: > "$MARKDIR/fired"
sub "-c filter.evil.clean= (blank out the driver)"; git -C "$WT" -c filter.evil.clean= diff "$BASE" >/dev/null 2>&1; verdict
: > "$MARKDIR/fired"
sub "-c core.attributesFile=/dev/null (does NOT disable in-tree .gitattributes)"
git -C "$WT" -c core.attributesFile=/dev/null diff "$BASE" >/dev/null 2>&1; verdict

hr "E4 can in-tree .gitattributes be ignored at all? (--attr-source, GIT_ATTR_NOSYSTEM)"
fresh
printf 'src/tracked.txt -diff\n' > "$WT/.gitattributes"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
sub "plain diff --stat"; git -C "$WT" diff --stat "$BASE"
sub "GIT_ATTR_NOSYSTEM=1"; GIT_ATTR_NOSYSTEM=1 git -C "$WT" diff --stat "$BASE"
sub "--attr-source=$BASE  (read attributes from the BASE COMMIT, not the worktree)"
git -C "$WT" --attr-source="$BASE" diff --stat "$BASE" 2>&1
sub "same, with the diff itself"
git -C "$WT" --attr-source="$BASE" diff "$BASE" 2>&1 | head -8
sub "--attr-source against \$GIT_COMMON_DIR/info/attributes"
COMMON="$(git -C "$WT" rev-parse --git-common-dir)"; mkdir -p "$COMMON/info"
printf 'src/tracked.txt -diff\n' > "$COMMON/info/attributes"
rm "$WT/.gitattributes"
echo "plain:"; git -C "$WT" diff --stat "$BASE"
echo "--attr-source=$BASE:"; git -C "$WT" --attr-source="$BASE" diff --stat "$BASE"

hr "E5 assume-unchanged / skip-worktree: what dispatcher-side lever exposes them?"
fresh
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
git -C "$WT" update-index --assume-unchanged src/tracked.txt
sub "plain status"; git -C "$WT" status --porcelain; echo "(empty)"
sub "git ls-files -v -z  (bits: h=assume-unchanged, S=skip-worktree)"; git -C "$WT" ls-files -v | grep -v '^H '
sub "git diff --no-optional-locks? irrelevant. Try 'git status --ignore-submodules --no-renames'"; git -C "$WT" status --porcelain --untracked-files=all
sub "does 'git update-index --really-refresh' clear it?"; git -C "$WT" update-index --really-refresh 2>&1; git -C "$WT" status --porcelain; echo "(still empty?)"
sub "does 'git diff --no-index BASE-tree vs worktree' bypass the index? use git stash? no."
sub "AUTHORITATIVE lever: re-read the worktree ignoring the index bits"
git -C "$WT" ls-files -v | awk '$1 ~ /^[a-z]$/ || $1=="S" {print}'
sub "diff against a FRESH temporary index (GIT_INDEX_FILE)"
TMPIDX="$ROOT/tmp.index"
GIT_INDEX_FILE="$TMPIDX" git -C "$WT" read-tree "$BASE"
GIT_INDEX_FILE="$TMPIDX" git -C "$WT" diff --stat "$BASE"
GIT_INDEX_FILE="$TMPIDX" git -C "$WT" status --porcelain

hr "E6 .gitignore / info/exclude: dispatcher lever = drop --exclude-standard, or --no-exclude-standard?"
fresh
printf 'stolen\n' > "$WT/secrets/exfil.txt"
printf '*\n' > "$WT/.gitignore"
COMMON="$(git -C "$WT" rev-parse --git-common-dir)"
printf 'secrets/exfil.txt\n' >> "$COMMON/info/exclude"
sub "current dispatcher call: ls-files --others --exclude-standard"
git -C "$WT" ls-files --others --exclude-standard; echo "(empty)"
sub "ls-files --others  (NO --exclude-standard)"
git -C "$WT" ls-files --others
sub "ls-files --others --exclude-standard --ignored (what was suppressed)"
git -C "$WT" ls-files --others --exclude-standard --ignored --directory
sub "status --porcelain --ignored"
git -C "$WT" status --porcelain --ignored
sub "-c core.excludesFile=/dev/null + ls-files --others (does it re-expose?)"
git -C "$WT" -c core.excludesFile=/dev/null ls-files --others --exclude-standard

hr "E7 is 'git config' the ONLY write path to .git/config, or does Write reach it directly?"
fresh; P=$(payload direct)
cat >> "$PRIMARY/.git/config" <<EOF
[core]
	fsmonitor = $P
EOF
git -C "$WT" status --porcelain >/dev/null 2>&1; verdict
echo "=> denying Bash(git config:*) alone is INSUFFICIENT; Write reaches .git/config as a plain file."

hr "E8 does the worktree-scoped config.worktree hide an fsmonitor from a .git/config audit?"
fresh; P=$(payload wtcfg)
git -C "$WT" config extensions.worktreeConfig true
git -C "$WT" config --worktree core.fsmonitor "$P"
sub "grep .git/config"; grep -n fsmonitor "$PRIMARY/.git/config" || echo "NOT IN .git/config"
sub "grep worktrees/*/config.worktree"; grep -rn fsmonitor "$PRIMARY/.git/worktrees/" || echo "not found"
git -C "$WT" status --porcelain >/dev/null 2>&1; verdict
sub "primary tree affected?"; : > "$MARKDIR/fired"; git -C "$PRIMARY" status --porcelain >/dev/null 2>&1; verdict
