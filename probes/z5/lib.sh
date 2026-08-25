#!/usr/bin/env bash
# Z5 probe harness — shared library.
# READ-ONLY MEASUREMENT. Throwaway repos only. No production repo is touched.
set -u

# The full hook name set enumerated from `man githooks` on this host (git 2.43.0).
HOOKS="applypatch-msg commit-msg fsmonitor-watchman p4-changelist p4-post-changelist \
p4-pre-submit p4-prepare-changelist post-applypatch post-checkout post-commit \
post-index-change post-merge post-receive post-rewrite post-update pre-applypatch \
pre-auto-gc pre-commit pre-merge-commit pre-push pre-rebase pre-receive \
prepare-commit-msg proc-receive push-to-checkout reference-transaction \
sendemail-validate update"

# Config keys that name a program git may execute.
EXEC_KEYS="core.fsmonitor core.pager core.editor sequence.editor core.gitProxy \
core.sshCommand credential.helper gpg.program core.alternateRefsCommand \
uploadpack.packObjectsHook diff.external"

sentinel_dir() { echo "$1/_sentinel"; }

# arm_hooks <hooks_dir> <logfile>
arm_hooks() {
  local hd="$1" log="$2" h
  mkdir -p "$hd"
  for h in $HOOKS; do
    printf '#!/bin/sh\nprintf "HOOK:%%s\\n" "%s" >> "%s"\nexit 0\n' "$h" "$log" > "$hd/$h"
    chmod 0755 "$hd/$h"
  done
}

# arm_config_exec <repo_dir> <sentinel_dir> <logfile>
arm_config_exec() {
  local repo="$1" sd="$2" log="$3" k
  mkdir -p "$sd"
  # pass-through program: logs then copies stdin->stdout (safe for filters)
  for k in $EXEC_KEYS; do
    printf '#!/bin/sh\nprintf "CFG:%%s\\n" "%s" >> "%s"\nexit 0\n' "$k" "$log" > "$sd/k-$k"
    chmod 0755 "$sd/k-$k"
    git -C "$repo" config "$k" "$sd/k-$k" 2>/dev/null
  done
  # attribute-selected drivers
  printf '#!/bin/sh\nprintf "CFG:filter.zf.clean\\n" >> "%s"\ncat\n'  "$log" > "$sd/f-clean";  chmod 0755 "$sd/f-clean"
  printf '#!/bin/sh\nprintf "CFG:filter.zf.smudge\\n" >> "%s"\ncat\n' "$log" > "$sd/f-smudge"; chmod 0755 "$sd/f-smudge"
  printf '#!/bin/sh\nprintf "CFG:diff.zd.textconv\\n" >> "%s"\ncat "$1"\n' "$log" > "$sd/d-textconv"; chmod 0755 "$sd/d-textconv"
  printf '#!/bin/sh\nprintf "CFG:diff.zd.command\\n" >> "%s"\nexit 0\n'    "$log" > "$sd/d-command";  chmod 0755 "$sd/d-command"
  git -C "$repo" config filter.zf.clean    "$sd/f-clean"
  git -C "$repo" config filter.zf.smudge   "$sd/f-smudge"
  git -C "$repo" config diff.zd.textconv   "$sd/d-textconv"
  git -C "$repo" config diff.zd.command    "$sd/d-command"
}

# reset the log
clr() { : > "$1"; }

# run <label> <logfile> <cmd...>   -> prints "label | rc | FIRED:<sorted uniq> or clean"
run() {
  local label="$1" log="$2"; shift 2
  clr "$log"
  local out rc
  out="$(timeout -k 2 15 "$@" 2>&1 </dev/null)"; rc=$?
  local fired
  fired="$(sort -u < "$log" | tr '\n' ' ')"
  if [ -z "$fired" ]; then fired="clean"; fi
  printf '%-56s rc=%-3s %s\n' "$label" "$rc" "$fired"
  if [ -n "${Z5_VERBOSE:-}" ]; then printf '    out: %s\n' "$(echo "$out" | head -3 | tr '\n' '|')"; fi
}
