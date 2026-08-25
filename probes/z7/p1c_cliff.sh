#!/usr/bin/env bash
# Z7 PROBE 1c -- where does pre-worker sealing become impractical?
# Builds throwaway repos of N files x S bytes and measures seal cost.
set -u
N=$1; S=$2
W=$(mktemp -d /tmp/z7cliff.XXXXXX)
cd "$W"
git init -q . 2>/dev/null
git config user.email z7@probe; git config user.name z7
python3 - "$N" "$S" <<'PY'
import os,sys,random
n=int(sys.argv[1]); s=int(sys.argv[2])
random.seed(1234)
for i in range(n):
    d=f"d{i//200:04d}"
    os.makedirs(d,exist_ok=True)
    # semi-compressible content, unique per file
    body=(f"file {i}\n".encode()*(max(1,s//10)))[:s]
    open(f"{d}/f{i:06d}.txt","wb").write(body)
PY
T0=$(date +%s.%N)
git add -A >/dev/null 2>&1
git commit -qm base >/dev/null 2>&1
T1=$(date +%s.%N)
echo "{\"n_files\":$N,\"file_bytes\":$S,\"t_repo_build_s\":$(echo "$T1-$T0"|bc)}"
for m in hash raw zlib; do
  python3 /home/dev/sol-claude-dispatcher/probes/z7/p1b_modes.py "$W" "$m"
done
DU_REPO=$(du -sb "$W/.git" | cut -f1)
echo "{\"git_dir_bytes\":$DU_REPO}"
rm -rf "$W"
