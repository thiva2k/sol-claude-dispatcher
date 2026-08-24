#!/usr/bin/env bash
# PROBE C: which git config keys / hooks cause the DISPATCHER's own git commands
# to execute a worker-chosen program? Runs under the dispatcher's exact env
# (GIT_TERMINAL_PROMPT=0, GIT_OPTIONAL_LOCKS=0, redirect vars stripped).
. "$(dirname "$0")/lib.sh"

MARKDIR=""
payload() { # $1 = tag ; writes an executable that stamps a marker
  cat > "$ROOT/pay-$1.sh" <<EOF
#!/bin/sh
echo "EXECUTED tag=$1 pid=\$\$ argv=\$*" >> "$MARKDIR/fired"
# textconv/external-diff must still produce something usable
exit 0
EOF
  chmod +x "$ROOT/pay-$1.sh"
  echo "$ROOT/pay-$1.sh"
}

fresh() { mkrepo >/dev/null; MARKDIR="$ROOT/marks"; mkdir -p "$MARKDIR"; : > "$MARKDIR/fired"; }
verdict() {
  if [ -s "$MARKDIR/fired" ]; then echo "*** OBSERVED: dispatcher executed worker program"; cat "$MARKDIR/fired"
  else echo "not observed (no execution)"; fi
}
# The dispatcher's five evidence commands (output discarded; we only care about exec)
dispatch_evidence() {
  git -C "$WT" status --porcelain          >/dev/null 2>&1
  git -C "$WT" diff --name-only "$BASE"    >/dev/null 2>&1
  git -C "$WT" ls-files --others --exclude-standard >/dev/null 2>&1
  git -C "$WT" diff --stat "$BASE"         >/dev/null 2>&1
  git -C "$WT" diff "$BASE"                >/dev/null 2>&1
  git -C "$WT" diff --check "$BASE"        >/dev/null 2>&1
  git -C "$WT" rev-parse HEAD              >/dev/null 2>&1
  git -C "$WT" worktree list --porcelain   >/dev/null 2>&1
}

hr "C1 core.fsmonitor"
fresh; P=$(payload fsmonitor)
git -C "$WT" config core.fsmonitor "$P"
sub "config landed in:"; grep -rn fsmonitor "$PRIMARY/.git/config"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
dispatch_evidence
verdict
sub "does it also fire for the PRIMARY tree? (shared .git/config)"
: > "$MARKDIR/fired"; git -C "$PRIMARY" status --porcelain >/dev/null 2>&1; verdict

hr "C2 diff.<driver>.textconv via in-tree .gitattributes"
fresh; P=$(payload textconv)
git -C "$WT" config diff.evil.textconv "$P"
printf 'src/tracked.txt diff=evil\n' > "$WT/.gitattributes"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
dispatch_evidence; verdict

hr "C3 diff.<driver>.command  (external diff driver)"
fresh; P=$(payload diffcommand)
git -C "$WT" config diff.evil.command "$P"
printf 'src/tracked.txt diff=evil\n' > "$WT/.gitattributes"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
dispatch_evidence; verdict

hr "C4 diff.external  (global external diff, NO .gitattributes needed)"
fresh; P=$(payload diffexternal)
git -C "$WT" config diff.external "$P"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
dispatch_evidence; verdict

hr "C5 filter.<f>.clean via .gitattributes"
fresh; P=$(payload filterclean)
git -C "$WT" config filter.evil.clean "$P"
printf 'src/tracked.txt filter=evil\n' > "$WT/.gitattributes"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
dispatch_evidence; verdict

hr "C5b filter.<f>.smudge (fires on checkout => 'git worktree add' of the NEXT task)"
fresh; P=$(payload filtersmudge)
git -C "$PRIMARY" config filter.evil.smudge "$P"
printf 'src/tracked.txt filter=evil\n' > "$PRIMARY/.git/info/attributes"
git -C "$PRIMARY" worktree add --quiet -b task9 "$ROOT/wt9" "$BASE" >/dev/null 2>&1
verdict

hr "C5c filter.<f>.process (long-running filter protocol)"
fresh; P=$(payload filterprocess)
git -C "$WT" config filter.evil.process "$P"
printf 'src/tracked.txt filter=evil\n' > "$WT/.gitattributes"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
dispatch_evidence; verdict

hr "C6 core.attributesFile (points attributes at an arbitrary worker file; shared config)"
fresh; P=$(payload attrfile)
printf 'src/tracked.txt diff=evil\n' > "$ROOT/hidden-attrs"
git -C "$WT" config core.attributesFile "$ROOT/hidden-attrs"
git -C "$WT" config diff.evil.textconv "$P"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
dispatch_evidence; verdict
sub "visible anywhere?"; git -C "$WT" status --porcelain; git -C "$WT" ls-files --others --exclude-standard
echo "(empty => invisible)"

hr "C7 .git/hooks/post-checkout  fired by the dispatcher's 'git worktree add'"
fresh; P=$(payload postcheckout)
cp "$P" "$PRIMARY/.git/hooks/post-checkout"; chmod +x "$PRIMARY/.git/hooks/post-checkout"
git -C "$PRIMARY" worktree add --quiet -b task3 "$ROOT/wt3" "$BASE" >/dev/null 2>&1
verdict

hr "C7b .git/hooks/reference-transaction fired by 'git worktree add -b' (creates a ref)"
fresh; P=$(payload reftxn)
cp "$P" "$PRIMARY/.git/hooks/reference-transaction"; chmod +x "$PRIMARY/.git/hooks/reference-transaction"
git -C "$PRIMARY" worktree add --quiet -b task4 "$ROOT/wt4" "$BASE" >/dev/null 2>&1
verdict

hr "C7c .git/hooks/post-index-change fired by dispatcher status/diff"
fresh; P=$(payload postindexchange)
cp "$P" "$PRIMARY/.git/hooks/post-index-change"; chmod +x "$PRIMARY/.git/hooks/post-index-change"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
dispatch_evidence; verdict
sub "again WITHOUT GIT_OPTIONAL_LOCKS=0"
: > "$MARKDIR/fired"
env -u GIT_OPTIONAL_LOCKS git -C "$WT" status --porcelain >/dev/null 2>&1; verdict

hr "C7d core.hooksPath -> worker-controlled directory"
fresh; P=$(payload hookspath)
mkdir -p "$ROOT/evilhooks"; cp "$P" "$ROOT/evilhooks/post-checkout"; chmod +x "$ROOT/evilhooks/post-checkout"
git -C "$WT" config core.hooksPath "$ROOT/evilhooks"
git -C "$PRIMARY" worktree add --quiet -b task5 "$ROOT/wt5" "$BASE" >/dev/null 2>&1
verdict

hr "C8 core.pager / pager.<cmd>"
fresh; P=$(payload pager)
git -C "$WT" config core.pager "$P"
git -C "$WT" config pager.diff "$P"
git -C "$WT" config pager.status "$P"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
dispatch_evidence; verdict
sub "with a TTY? (script -qec, simulates an interactive dispatcher)"
: > "$MARKDIR/fired"
script -qec "git -C '$WT' diff $BASE" /dev/null >/dev/null 2>&1; verdict

hr "C9 core.editor / sequence.editor"
fresh; P=$(payload editor)
git -C "$WT" config core.editor "$P"; git -C "$WT" config sequence.editor "$P"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
dispatch_evidence; verdict

hr "C10 credential.helper"
fresh; P=$(payload credhelper)
git -C "$WT" config credential.helper "!$P"
dispatch_evidence; verdict

hr "C11 core.gitProxy / core.sshCommand"
fresh; P=$(payload proxy)
git -C "$WT" config core.gitProxy "$P"; git -C "$WT" config core.sshCommand "$P"
dispatch_evidence; verdict

hr "C12 uploadpack.packObjectsHook"
fresh; P=$(payload packobjects)
git -C "$WT" config uploadpack.packObjectsHook "$P"
dispatch_evidence; verdict

hr "C13 core.alternateRefsCommand"
fresh; P=$(payload altrefs)
git -C "$WT" config core.alternateRefsCommand "$P"
dispatch_evidence; verdict

hr "C14 gpg.program (would need --show-signature; dispatcher does not use it)"
fresh; P=$(payload gpg)
git -C "$WT" config gpg.program "$P"
dispatch_evidence; verdict

hr "C15 alias overriding a builtin the dispatcher runs"
fresh; P=$(payload alias)
git -C "$WT" config alias.status "!$P"
git -C "$WT" config alias.diff "!$P"
dispatch_evidence; verdict
sub "what does 'git status' actually print now?"; git -C "$WT" status --porcelain; echo "exit=$?"

hr "C16 include.path -> worker file that carries the payload config"
fresh; P=$(payload includepath)
cat > "$ROOT/evil.gitconfig" <<EOF
[core]
	fsmonitor = $P
EOF
git -C "$WT" config include.path "$ROOT/evil.gitconfig"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
dispatch_evidence; verdict

hr "C17 merge.<d>.driver / trailer.<t>.command / rebase.instructionFormat"
fresh; P=$(payload merge)
git -C "$WT" config merge.evil.driver "$P %O %A %B"
git -C "$WT" config trailer.evil.command "$P"
printf 'src/tracked.txt merge=evil\n' > "$WT/.gitattributes"
printf 'alpha\nEVIL\n' > "$WT/src/tracked.txt"
dispatch_evidence; verdict
