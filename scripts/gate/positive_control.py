#!/usr/bin/env python3
"""PART 3 — the positive control. Prove every sentinel FIRES without safe mode.

Run this BEFORE any suppression claim is made. A sentinel that never fired in
the first place proves nothing when it fails to fire under ``--safe-mode``: the
suppression test would pass vacuously and the gate would ship a false GREEN.

Usage::

    scripts/gate/positive_control.py [--keep] [--probes P1_root,P4_skill]

Every invocation is the REAL Claude CLI, so this costs real money (~$0.06 per
probe at the time of writing). The cost is measured, not estimated, and printed
at the end.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture as fixture_mod  # noqa: E402
from _common import (  # noqa: E402
    CostLedger,
    cleanup,
    clean_child_env,
    eprint,
    run_cli,
    stray_sentinel_scan,
    write_evidence,
)
from probes import BY_ID, PROBES  # noqa: E402

CLAUDE = shutil.which("claude") or "/home/dev/.local/bin/claude"

#: Trees a stray sentinel must never appear in. Checked after every run.
PROTECTED_ROOTS = (
    "/home/dev/full-voice-agent",
    "/home/dev/.claude",
    "/home/dev/.codex",
    "/home/dev/sol-claude-dispatcher",
    "/tmp/sol-gate-should-not-exist",
)


def plain_argv(prompt: str) -> list[str]:
    """A NORMAL invocation: no ``--safe-mode``, no dispatcher isolation flags.

    ``--permission-mode auto`` matches what the dispatcher emits, so the only
    difference between this baseline and the suppression arms is the isolation
    itself and not whether a sentinel's ``touch`` was permitted to run.
    """
    return [
        CLAUDE,
        "-p",
        "--model",
        "sonnet",
        "--output-format",
        "json",
        "--permission-mode",
        "auto",
        prompt,
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="do not delete the temp tree")
    ap.add_argument("--probes", default="", help="comma-separated probe ids to run")
    ap.add_argument(
        "--out",
        default="/home/dev/.claude/auto-mode/commissioning/GATE-POSITIVE-CONTROL.md",
        help="where to write the positive-control table",
    )
    args = ap.parse_args()

    selected = (
        [BY_ID[p] for p in args.probes.split(",") if p]
        if args.probes
        else [p for p in PROBES if "positive" in p.arms]
    )

    root = Path(tempfile.mkdtemp(prefix="sol-gate-poscontrol-"))
    ledger = CostLedger()
    fx = fixture_mod.build(root)
    eprint(f"[fixture] {fx.repo}  nonce={fx.nonce}")

    results: dict[str, dict] = {}
    for probe in selected:
        base = fx.agents_only_repo if probe.repo == "agents_only" else fx.repo
        cwd = (base / probe.cwd_rel).resolve()
        # Cleared before EVERY probe, not once per run: a file planted by an
        # earlier probe would otherwise never look "new" again and its own
        # probe would score a false NO.
        fx.reset_fired()
        before = fx.fired_now()
        inv = run_cli(
            f"positive-control/{probe.ident}",
            plain_argv(probe.prompt),
            cwd=cwd,
            env=clean_child_env(),
            timeout_s=300,
            ledger=ledger,
        )
        after = fx.fired_now()
        new_files = sorted(after - before)
        raw = write_evidence(
            fx.evidence_dir,
            f"{probe.ident}.plain.json",
            json.dumps(
                {
                    "probe": probe.ident,
                    "cwd": str(cwd),
                    "invocation": inv.to_record(),
                    "fired_files_new": new_files,
                    "raw_stdout": inv.stdout,
                    "raw_stderr": inv.stderr,
                },
                indent=2,
            ),
        )
        results[probe.ident] = {
            "new_files": new_files,
            "result_text": inv.result_text,
            "stdout": inv.stdout,
            "evidence": raw,
            "exit_code": inv.exit_code,
        }
        eprint(
            f"[{probe.ident}] exit={inv.exit_code} cost=${inv.cost_usd:.4f} "
            f"new_fired={new_files}"
        )

    _REPLIES.update({k: v["result_text"] for k, v in results.items()})
    rows = _score(fx, results, selected)
    stray = stray_sentinel_scan(fx.nonce, PROTECTED_ROOTS)

    report = _render(fx, rows, ledger, stray, selected, args.keep)
    Path(args.out).write_text(report, encoding="utf-8")
    eprint(f"[report] {args.out}")

    # Evidence is inside the temp tree, so copy it out before cleanup.
    if not args.keep:
        keep_dir = Path("/home/dev/.claude/auto-mode/commissioning/gate-evidence")
        keep_dir.mkdir(parents=True, exist_ok=True)
        for f in fx.evidence_dir.iterdir():
            shutil.copy2(f, keep_dir / f.name)
        eprint(f"[evidence] copied to {keep_dir}")

    eprint(cleanup(fx.root, keep=args.keep))
    eprint(f"[cost] total ${ledger.total_usd:.6f} over {len(ledger.invocations)} invocations")

    admissible = sum(1 for r in rows if r["fires"])
    eprint(f"[verdict] {admissible}/{len(rows)} sentinels admissible")
    return 0


def _score(fx, results, selected) -> list[dict]:
    """Decide, per sentinel, whether it demonstrably fired."""
    selected_ids = {p.ident for p in selected}
    rows: list[dict] = []
    for sent in fx.sentinels.values():
        if not sent.live_probe:
            # These exist only to be asserted ABSENT from a projection. They
            # are never expected to fire live, so scoring them here would
            # manufacture failures that mean nothing.
            continue
        if sent.probe not in selected_ids:
            rows.append(
                {
                    "sentinel": sent,
                    "fires": False,
                    "token_seen": False,
                    "file_seen": False,
                    "evidence": "<probe not run>",
                    "detail": "probe not selected for this run",
                }
            )
            continue
        res = results[sent.probe]
        token_seen = sent.token in res["result_text"] or sent.token in res["stdout"]
        file_seen = Path(sent.fired_path).name in res["new_files"]
        if sent.channel == "token":
            fires = token_seen
        elif sent.channel == "file":
            fires = file_seen
        else:
            fires = token_seen or file_seen
        rows.append(
            {
                "sentinel": sent,
                "fires": fires,
                "token_seen": token_seen,
                "file_seen": file_seen,
                "evidence": res["evidence"],
                "detail": f"exit={res['exit_code']}",
            }
        )
    return rows


#: Filled in by :func:`main` so the rendered report can quote the model
#: verbatim. Raw replies are the evidence; a summary of them is not.
_REPLIES: dict[str, str] = {}


def _render(fx, rows, ledger, stray, selected, keep) -> str:
    out: list[str] = []
    a = out.append
    a("# GATE 4.5 — POSITIVE CONTROL (Lane G)\n")
    a(
        "Every sentinel below was planted in a throwaway git repository under a "
        "fresh `mktemp -d` and then probed with the **real Claude CLI 2.1.237, "
        "WITHOUT `--safe-mode`** and without any dispatcher isolation flag.\n"
    )
    a(
        "**Why this document exists.** A suppression proof is worthless without "
        "a positive control. If a sentinel never fired in the first place, "
        '"safe mode suppressed it" proves nothing — the test passes vacuously '
        "and we would be shipping a false GREEN. Only a sentinel with a "
        "demonstrated firing baseline in the FIRES column below is admissible "
        "evidence in the suppression half of the gate.\n"
    )
    a(f"- Run nonce: `{fx.nonce}`")
    a(f"- Throwaway root: `{fx.root}`")
    a(f"- Probes run: {', '.join(p.ident for p in selected)}")
    a("")
    a("## Positive-control table\n")
    a(
        "| sentinel | surface | §18/§12 | probe | channel | token seen | file seen "
        "| FIRES WITHOUT SAFE MODE | raw evidence |"
    )
    a("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        s = r["sentinel"]
        a(
            f"| `{s.key}` | {s.surface} | {s.assertion} | {s.probe} | {s.channel} | "
            f"{'YES' if r['token_seen'] else 'no'} | "
            f"{'YES' if r['file_seen'] else 'no'} | "
            f"**{'YES' if r['fires'] else 'NO'}** | `{Path(r['evidence']).name}` |"
        )
    a("")
    a("## What each probe actually asked\n")
    for probe in selected:
        a(f"- **{probe.ident}** (cwd `{probe.cwd_rel}` in the {probe.repo} repo) — {probe.intent}")
        a(f"  - prompt: `{probe.prompt[:400]}`")
    a("")
    a("## Model replies, verbatim\n")
    for probe in selected:
        a(f"### {probe.ident}\n")
        a("```")
        a(_REPLIES.get(probe.ident, "<not captured>").strip())
        a("```")
        a("")
    inadmissible = [r for r in rows if not r["fires"]]
    a("## Inadmissible sentinels (NOT live-testable as planted)\n")
    if not inadmissible:
        a("None — every planted sentinel fired.\n")
    else:
        for r in inadmissible:
            s = r["sentinel"]
            a(
                f"- **`{s.key}`** ({s.surface}) — did not fire under a normal "
                f"invocation. {r['detail']}. It MUST NOT be counted as a passed "
                f"suppression test; see the report for the reason and whether a "
                f"redesign is possible."
            )
        a("")
    a("## Cost envelope\n")
    a(ledger.table())
    a("")
    a("## Safety\n")
    a(
        f"- Stray-sentinel scan for `*{fx.nonce}*` across "
        f"{', '.join(PROTECTED_ROOTS)}: "
        + ("**NONE FOUND**" if not stray else f"**{len(stray)} HITS** — {stray}")
    )
    a(f"- Temp tree: {'KEPT by operator request' if keep else 'removed'}")
    a("")
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
