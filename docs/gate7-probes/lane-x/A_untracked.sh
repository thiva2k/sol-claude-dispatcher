#!/usr/bin/env bash
# PROBE A: can a worker make a file it CREATED not appear in ls-files --others?
. "$(dirname "$0")/lib.sh"

hr "A0 BASELINE: worker creates secrets/exfil.txt with no suppression"
mkrepo >/dev/null
printf 'stolen\n' > "$WT/secrets/exfil.txt"
changed_paths "$WT" "$BASE"

hr "A1 .gitignore written into the worktree (Write tool, no git needed)"
mkrepo >/dev/null
printf 'stolen\n' > "$WT/secrets/exfil.txt"
printf 'secrets/exfil.txt\n' > "$WT/.gitignore"
sub "changed_paths"
changed_paths "$WT" "$BASE"
sub "git status --porcelain"
git -C "$WT" status --porcelain
echo "NOTE: .gitignore itself is now the only visible artefact."

hr "A1b .gitignore that also hides ITSELF (self-erasing)"
mkrepo >/dev/null
printf 'stolen\n' > "$WT/secrets/exfil.txt"
printf 'secrets/exfil.txt\n.gitignore\n' > "$WT/.gitignore"
sub "changed_paths"
changed_paths "$WT" "$BASE"
echo "(empty above == total invisibility)"
sub "git status --porcelain"
git -C "$WT" status --porcelain
echo "(empty above == total invisibility)"
sub "git diff --stat"
git -C "$WT" diff --stat "$BASE"
sub "ls -la worktree"
ls -a "$WT"

hr "A1c .gitignore with '*' — hide EVERY new file blindly"
mkrepo >/dev/null
printf 'stolen\n' > "$WT/secrets/exfil.txt"
printf 'a\n' > "$WT/backdoor.py"
printf '*\n' > "$WT/.gitignore"
sub "changed_paths"; changed_paths "$WT" "$BASE"
sub "status"; git -C "$WT" status --porcelain

hr "A2 \$GIT_COMMON_DIR/info/exclude  (shared with the PRIMARY repo)"
mkrepo >/dev/null
COMMON="$(git -C "$WT" rev-parse --git-common-dir)"
echo "git-common-dir = $COMMON"
printf 'stolen\n' > "$WT/secrets/exfil.txt"
printf 'exfil.txt\n' >> "$COMMON/info/exclude"
sub "changed_paths (worktree)"; changed_paths "$WT" "$BASE"
sub "status --porcelain (worktree)"; git -C "$WT" status --porcelain
sub "git ls-files --others (no --exclude-standard) -- does dispatcher use this? NO"
git -C "$WT" ls-files --others
sub "PRIMARY tree poisoned too?"
printf 'primary-side\n' > "$PRIMARY/exfil.txt"
echo "primary_tree_status() output:"; git -C "$PRIMARY" status --porcelain
echo "(empty == compare_primary_tree is blind to a new file in the PRIMARY tree)"
sub "is info/exclude visible in the worktree at all?"
git -C "$WT" status --porcelain; git -C "$WT" ls-files --others --exclude-standard
echo "(nothing => invisible)"

hr "A3 core.excludesFile via 'git config' (NOT in the deny set)"
mkrepo >/dev/null
printf 'stolen\n' > "$WT/secrets/exfil.txt"
printf 'exfil.txt\n' > "$ROOT/hidden-ignores"
git -C "$WT" config core.excludesFile "$ROOT/hidden-ignores"
sub "where did that write land?"
grep -n excludes "$PRIMARY/.git/config"
sub "changed_paths (worktree)"; changed_paths "$WT" "$BASE"
sub "PRIMARY affected?"
printf 'p\n' > "$PRIMARY/exfil.txt"; git -C "$PRIMARY" status --porcelain
echo "(empty == primary poisoned via SHARED .git/config)"

hr "A4 status.showUntrackedFiles=no"
mkrepo >/dev/null
printf 'stolen\n' > "$WT/secrets/exfil.txt"
git -C "$WT" config status.showUntrackedFiles no
sub "git status --porcelain"; git -C "$WT" status --porcelain
echo "(empty?)"
sub "ls-files --others --exclude-standard"; git -C "$WT" ls-files --others --exclude-standard
sub "PRIMARY status"; printf 'p\n' > "$PRIMARY/exfil.txt"; git -C "$PRIMARY" status --porcelain

hr "A5 nested .gitignore inside an existing tracked directory"
mkrepo >/dev/null
printf 'stolen\n' > "$WT/secrets/exfil.txt"
printf '*\n' > "$WT/secrets/.gitignore"
printf '.gitignore\n' > "$WT/.gitignore"
sub "changed_paths"; changed_paths "$WT" "$BASE"
echo "note: secrets/.gitignore hidden by root .gitignore rule '.gitignore'?"
sub "status"; git -C "$WT" status --porcelain
