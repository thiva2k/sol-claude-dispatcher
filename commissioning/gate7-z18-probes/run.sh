#!/bin/bash
# GATE 7 REVISION 9, LANE Z18 — the EXACT commands that produced every .txt
# output committed in this directory. Run from the repository root:
#
#     bash commissioning/gate7-z18-probes/run.sh
#
# Nothing here touches src/**, tests/**, docs/GATE7-DESIGN.md, or any
# repository other than a `mktemp -d` scratch directory that each probe
# creates and deletes itself.
#
# Exit status: each probe FAILS LOUDLY (nonzero) if its own positive control
# does not fire. `set -e` is deliberately NOT used, so that a control failure
# is RECORDED in the transcript rather than aborting the run silently; the
# per-probe exit codes are written to exit-codes.txt and must all be 0 before
# any result in this directory may be cited.
set -u
cd "$(dirname "$0")"

{
  echo "=== environment, measured at run time ==="
  echo "date (UTC)   : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "host kernel  : $(uname -srmo)"
  echo "distro       : $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
  echo "git path     : $(command -v git)"
  echo "git version  : $(git --version)"
  echo "python path  : $(command -v python3)"
  echo "python ver   : $(python3 --version)"
  echo "/bin/sh      : $(readlink -f /bin/sh)"
  echo "dash version : $(dpkg-query -W -f='${Version}' dash 2>/dev/null || echo 'unknown')"
  echo "repo commit  : $(git -C ../.. rev-parse HEAD)"
} > environment.txt 2>&1
cat environment.txt

: > exit-codes.txt

# ---------------------------------------------------------------------------
# The DEFECT, preserved. This is Z17's committed probe, unmodified. Its
# positive control is DEAD: the shim calls `touch` and `cat`, which cannot be
# resolved under the PATH the shim is given. Captured so that F7-3's claim
# rests on a transcript rather than on a description of one.
# ---------------------------------------------------------------------------
python3 ../gate7-z17-probes/exp8_path.py \
  > exp8_ORIGINAL_dead_control.stdout.txt \
  2> exp8_ORIGINAL_dead_control.stderr.txt
echo "exp8_path.py (Z17, UNMODIFIED, dead control) exit=$?" >> exit-codes.txt

# ---------------------------------------------------------------------------
# TASK A / F7-3 — the repaired PATH experiment, both legs.
# ---------------------------------------------------------------------------
python3 exp8b_path_fixed.py \
  > exp8b_path_fixed.stdout.txt \
  2> exp8b_path_fixed.stderr.txt
echo "exp8b_path_fixed.py exit=$?" >> exit-codes.txt

# ---------------------------------------------------------------------------
# TASK B / F7-2 — multi-pack-index location and the objects/pack/** inventory.
# ---------------------------------------------------------------------------
python3 exp9_pack_layout.py \
  > exp9_pack_layout.stdout.txt \
  2> exp9_pack_layout.stderr.txt
echo "exp9_pack_layout.py exit=$?" >> exit-codes.txt

# ---------------------------------------------------------------------------
# TASK B / F7-1 + F7-2 — loose-object path shape and the size-preserving
# alteration demonstration.
# ---------------------------------------------------------------------------
python3 exp10_loose_object.py \
  > exp10_loose_object.stdout.txt \
  2> exp10_loose_object.stderr.txt
echo "exp10_loose_object.py exit=$?" >> exit-codes.txt

echo
echo "=== exit codes (all repaired probes MUST be 0) ==="
cat exit-codes.txt
