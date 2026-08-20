#!/usr/bin/env python3
"""PART 4 — the disposable live adversarial gate.

Three arms, run against the same throwaway fixture:

``engine``
    No live cost. Drives the REAL projection engines through the REAL config
    loader with an ephemeral, projection-ENABLED configuration, and asserts the
    content of what they produce. Addendum §18 B/C/D/E/F and the skills-side
    §12/§16 default-deny and drift items live here.

``safe``
    Live. Replays the positive control's probes with ``--safe-mode`` added and
    nothing else changed, so any difference is attributable to the flag alone.

``dispatcher``
    Live. Invokes through the REAL ``build_worker_invocation()`` /
    ``build_argv()``, never a hand-written command line, and asserts both the
    suppression half and the composition half (§14: does the curated guidance
    and the approved skill text actually reach the worker?).

Every assertion is reported independently as PASS or FAIL with a raw-evidence
pointer, and every assertion is LITERAL: it names the exact nonce it expects to
find or not find. An emptied constant or a missing projection therefore FAILS —
the self-check in ``_assert_literal_assertions_bite`` proves that, by blanking a
projection artifact and confirming the presence assertion goes red.

**Admissibility.** A suppression assertion is only counted for a sentinel that
is listed as FIRES=YES in ``GATE-POSITIVE-CONTROL.md``. Sentinels with no
demonstrated firing baseline are reported as INADMISSIBLE and excluded, because
"it did not fire under safe mode" says nothing about a sentinel that never
fired at all.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import fixture as fixture_mod  # noqa: E402
import manifests as manifests_mod  # noqa: E402
from _common import (  # noqa: E402
    Assertion,
    CostLedger,
    cleanup,
    clean_child_env,
    eprint,
    run_cli,
    stray_sentinel_scan,
    write_evidence,
)
from probes import PROBES  # noqa: E402

from sol_claude_dispatcher.config import load_config  # noqa: E402
from sol_claude_dispatcher.errors import DispatcherError  # noqa: E402
from sol_claude_dispatcher.models import TaskEnvelope, TaskRequest  # noqa: E402
from sol_claude_dispatcher.project_guidance import (  # noqa: E402
    ProjectGuidanceEngine,
    RepositoryIdentity,
)
from sol_claude_dispatcher.runner import (  # noqa: E402
    ALWAYS_DISALLOWED_TOOLS,
    build_argv,
    build_worker_invocation,
)
from sol_claude_dispatcher.skills import SkillProjectionEngine  # noqa: E402

PROTECTED_ROOTS = (
    "/home/dev/full-voice-agent",
    "/home/dev/.claude",
    "/home/dev/.codex",
    "/home/dev/sol-claude-dispatcher",
)

#: Sentinels proven to fire without safe mode, from GATE-POSITIVE-CONTROL.md.
#: Anything not listed here is INADMISSIBLE and is excluded from scoring rather
#: than silently counted as a pass.
DEFAULT_ADMISSIBLE = (
    "ROOTCLAUDE",
    "OPERATOR",
    "SUBCLAUDE",
    "NESTEDCLAUDE",
    "HOOKSESSIONSTART",
    "HOOKUSERPROMPT",
    "PROJECTSKILL",
    "SKILLDYNSHELL",
    "CUSTOMAGENT",
    "CUSTOMCOMMAND",
    "CMDDYNSHELL",
    "MCPSTARTED",
    "MCPCALLED",
)

CLAUDE = shutil.which("claude") or "/home/dev/.local/bin/claude"


class Gate:
    def __init__(self, keep: bool) -> None:
        self.keep = keep
        self.root = Path(tempfile.mkdtemp(prefix="sol-gate-run-"))
        self.ledger = CostLedger()
        self.assertions: list[Assertion] = []
        self.fx = fixture_mod.build(self.root)
        subprocess.run(  # noqa: S603 - argv list, no shell
            ["git", "remote", "add", "origin", manifests_mod.FAKE_ORIGIN],
            cwd=str(self.fx.repo),
            check=True,
            capture_output=True,
        )
        n = self.fx.nonce
        self.proj_tokens = {
            k: f"SENT-{k}-{n}"
            for k in ("PROJROOT", "PROJSUB", "PROJOTHER", "PROJREVIEW")
        }
        self.artifact_dir = self.fx.config_path.parent / "guidance"
        manifests_mod.build_guidance_manifest(
            repo=self.fx.repo,
            out_path=self.fx.guidance_manifest_path,
            artifact_dir=self.artifact_dir,
            tokens=self.proj_tokens,
        )
        manifests_mod.build_skill_manifest(
            repo=self.fx.repo, out_path=self.fx.skills_manifest_path
        )
        self.config = load_config(self.fx.config_path)
        self.identity = RepositoryIdentity(
            toplevel=str(self.fx.repo),
            git_dir=str(self.fx.repo / ".git"),
            origin_url=manifests_mod.FAKE_ORIGIN,
            root_commit=subprocess.run(  # noqa: S603
                ["git", "rev-list", "--max-parents=0", "HEAD"],
                cwd=str(self.fx.repo),
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip(),
        )

    # -- reporting -------------------------------------------------------

    def check(
        self, ident: str, surface: str, statement: str, passed: bool, evidence: str,
        detail: str = "",
    ) -> Assertion:
        a = Assertion(ident, surface, statement, passed, evidence, detail)
        self.assertions.append(a)
        eprint(f"  [{'PASS' if passed else 'FAIL'}] {ident}: {statement}")
        return a

    def tok(self, key: str) -> str:
        return self.fx.sentinels[key].token

    # -- ARM 1: engine ---------------------------------------------------

    def arm_engine(self) -> None:
        eprint("[arm] engine (no live cost)")
        cfg = self.config
        self.check(
            "CFG-1",
            "ephemeral configuration",
            "projection is enabled by CONFIG ALONE — no code edit, no env "
            "escape hatch, no 'if testing' branch",
            cfg.skills.enabled and cfg.project_guidance.enabled,
            str(self.fx.config_path),
            f"skills.enabled={cfg.skills.enabled} "
            f"project_guidance.enabled={cfg.project_guidance.enabled}",
        )
        self.check(
            "CFG-2",
            "production inertness",
            "the PRODUCTION config and manifest are untouched by this gate",
            _production_still_inert(),
            "config/dispatcher.toml + config/approved-guidance.json",
        )

        pg = ProjectGuidanceEngine.from_config(cfg)
        sk = SkillProjectionEngine.from_config(cfg)

        projection = pg.project(
            ["SubAgent/deep/nested/widget.py"],
            repository=self.identity,
            task_envelope_id="gate-engine",
        )
        text = projection.text
        ev = write_evidence(
            self.fx.evidence_dir, "engine.guidance.txt",
            f"scopes={projection.scope_prefixes}\nids={projection.logical_ids}\n"
            f"bytes={projection.projected_bytes}\n\n{text}",
        )

        self.check(
            "A18-B", "curated root guidance",
            f"the worker's projected guidance CONTAINS the curated root token "
            f"{self.proj_tokens['PROJROOT']}",
            self.proj_tokens["PROJROOT"] in text, ev,
        )
        self.check(
            "A18-C1", "scope selection",
            f"a SubAgent/ task's guidance CONTAINS {self.proj_tokens['PROJSUB']}",
            self.proj_tokens["PROJSUB"] in text, ev,
            f"selected scopes: {projection.scope_prefixes}",
        )
        self.check(
            "A18-C2", "scope exclusion",
            f"a SubAgent/ task's guidance does NOT contain the OtherAgent token "
            f"{self.proj_tokens['PROJOTHER']}",
            self.proj_tokens["PROJOTHER"] not in text, ev,
        )
        for key, ident, why in (
            ("ROOTCLAUDE", "A18-A-eng", "raw root CLAUDE.md text"),
            ("SUBCLAUDE", "A18-C3", "raw subproject CLAUDE.md text"),
            ("NESTEDCLAUDE", "A18-D-eng", "unapproved nested CLAUDE.md text"),
            ("OPERATOR", "A18-E", "operator-only section"),
            ("OTHERSUBCLAUDE", "A18-C4", "other subproject's raw text"),
            ("UNREVIEWEDSCOPE", "A18-C5", "unreviewed scope's raw text"),
        ):
            self.check(
                ident, "projection purity",
                f"the projection does NOT contain the {why} token "
                f"({self.tok(key)})",
                self.tok(key) not in text, ev,
            )

        # §18 C / RULINGS §7 — an unapproved scope fails closed.
        try:
            pg.project(
                ["Unreviewed/thing.py"],
                repository=self.identity,
                task_envelope_id="gate-engine-unapproved",
            )
            failed_closed, detail = False, "projection SUCCEEDED — must not"
        except DispatcherError as exc:
            failed_closed = type(exc).__name__ == "ProjectGuidanceNotApproved"
            detail = f"{type(exc).__name__}: {exc}"
        self.check(
            "A18-C6", "unapproved scope",
            "a task touching an unapproved scope FAILS CLOSED with "
            "ProjectGuidanceNotApproved (never a silent root-only fallback)",
            failed_closed, ev, detail,
        )

        # §18 F — a changed instruction source blocks projection and resume.
        source = self.fx.repo / "SubAgent" / "CLAUDE.md"
        original = source.read_bytes()
        source.write_bytes(original + b"\n<!-- drifted -->\n")
        try:
            pg.project(
                ["SubAgent/deep/nested/widget.py"],
                repository=self.identity,
                task_envelope_id="gate-engine-drift",
            )
            drifted, detail = False, "projection SUCCEEDED after source change"
        except DispatcherError as exc:
            drifted = True
            detail = f"{type(exc).__name__}: {exc}"
        finally:
            source.write_bytes(original)
        self.check(
            "A18-F", "source drift",
            "changing a pinned instruction source FAILS CLOSED rather than "
            "silently reprojecting",
            drifted, ev, detail,
        )

        # Skills side: §6 default-deny and §12 native-runtime refusal.
        sp = sk.project(["gate.approved-skill"])
        sk_ev = write_evidence(self.fx.evidence_dir, "engine.skills.txt", sp.text)
        self.check(
            "SK-1", "approved skill projection",
            f"the approved skill's inert text CONTAINS {self.tok('APPROVEDSKILL')}",
            self.tok("APPROVEDSKILL") in sp.text, sk_ev,
        )
        self.check(
            "SK-2", "unapproved skill",
            f"the projection does NOT contain the unapproved neighbour's token "
            f"({self.tok('UNAPPROVEDSKILL')})",
            self.tok("UNAPPROVEDSKILL") not in sp.text, sk_ev,
        )
        for ident, skill_id, why in (
            ("SK-3", "gate.unapproved-skill", "an unapproved sibling in the same dir"),
            ("SK-4", "gate.sentinel-skill", "the unsafe native-runtime sentinel skill"),
        ):
            try:
                sk.project([skill_id])
                refused, detail = False, "projection SUCCEEDED — must not"
            except DispatcherError as exc:
                refused, detail = True, f"{type(exc).__name__}: {exc}"
            self.check(
                ident, "default deny",
                f"projecting {why} is REFUSED", refused, sk_ev, detail,
            )

        self._assert_literal_assertions_bite(cfg)

    def _assert_literal_assertions_bite(self, cfg) -> None:
        """Prove the presence assertions are not vacuous.

        Blank the curated root artifact, reproject, and confirm the engine
        either refuses outright (hash drift) or produces text WITHOUT the token
        the A18-B assertion looks for. Either outcome means A18-B could not
        have passed by accident; a green A18-B against an emptied constant
        would mean the whole gate is decorative.
        """
        artifact = self.artifact_dir / "gate-root.source.v1.txt"
        original = artifact.read_bytes()
        artifact.write_bytes(b"")
        try:
            engine = ProjectGuidanceEngine.from_config(cfg)
            text = engine.project(
                ["SubAgent/deep/nested/widget.py"],
                repository=self.identity,
                task_envelope_id="gate-mutation",
            ).text
            bites = self.proj_tokens["PROJROOT"] not in text
            detail = "projection succeeded but the token was gone"
        except DispatcherError as exc:
            bites = True
            detail = f"refused outright: {type(exc).__name__}: {exc}"
        finally:
            artifact.write_bytes(original)
        self.check(
            "MUT-1", "assertion integrity",
            "emptying the curated root artifact makes A18-B FAIL — the "
            "presence assertions are literal, not vacuous",
            bites, str(artifact), detail,
        )

    # -- argv invariants (§14) -------------------------------------------

    def worker_argv(self, prompt: str, cwd: Path) -> tuple[list[str], Any]:
        """Build a worker invocation through the REAL builder. Never by hand."""
        request = TaskRequest.model_validate(
            {
                "repository": {"root": str(self.fx.repo), "base_ref": "HEAD"},
                "task": {
                    "kind": "implementation",
                    "objective": "Report the requested project reference values.",
                    "context": "Disposable Gate 4.5 adversarial fixture.",
                    "acceptance_criteria": ["The requested values are reported."],
                },
                "scope": {"allowed_paths": ["SubAgent/**"], "forbidden_paths": []},
                "routing": {"model": "sonnet", "complexity": "low", "risk": "low"},
                "execution": {"timeout_seconds": 600, "max_turns": 8},
            }
        )
        envelope = TaskEnvelope.from_request(
            request,
            canonical_root=str(self.fx.repo),
            base_commit=self.identity.root_commit,
        )
        spec = build_worker_invocation(
            envelope,
            self.config,
            model="sonnet",
            session_id=str(uuid.uuid4()),
            prompt=prompt,
            cwd=cwd,
            # A CLI-created worktree would move the child's working directory
            # out from under the fixture's nested probe path. The builder's own
            # resume path already passes False here, so this exercises a real
            # supported branch rather than a bypass.
            include_worktree=False,
        )
        return build_argv(spec), spec

    def arm_argv_invariants(self) -> None:
        eprint("[arm] argv invariants (no live cost)")
        argv, spec = self.worker_argv("noop", self.fx.repo)
        ev = write_evidence(
            self.fx.evidence_dir, "argv.worker.json", json.dumps(argv, indent=1)
        )
        joined = " ".join(argv)
        for ident, statement, ok in (
            ("INV-1", "--safe-mode is emitted", "--safe-mode" in argv),
            ("INV-2", "--strict-mcp-config is emitted", "--strict-mcp-config" in argv),
            ("INV-3", "an empty MCP config is pinned",
             "--mcp-config" in argv and "empty-mcp.json" in joined),
            ("INV-4", "mcp__* is denied", "mcp__*" in argv),
            ("INV-5", "Agent is denied", "Agent" in argv),
            ("INV-6", "Task is denied", "Task" in argv),
            ("INV-7", "Bash(claude:*) is denied", "Bash(claude:*)" in argv),
            ("INV-8", "Bash(codex:*) is denied", "Bash(codex:*)" in argv),
            ("INV-9", "no --dangerously-skip-permissions",
             "--dangerously-skip-permissions" not in argv),
            ("INV-10", "no --bare (it leaves Skills resolvable)", "--bare" not in argv),
            ("INV-11", "Skill is NOT in the worker tool set",
             "Skill" not in list(self.config.claude.worker_tools)),
        ):
            self.check(ident, "argv invariant (§14)", statement, ok, ev)
        for op in ("push", "merge", "rebase", "commit", "reset", "clean", "worktree", "bisect"):
            self.check(
                f"INV-git-{op}", "argv invariant (§14)",
                f"Bash(git {op}:*) is denied",
                f"Bash(git {op}:*)" in argv, ev,
            )
        self.check(
            "INV-always", "argv invariant (§14)",
            "every ALWAYS_DISALLOWED_TOOLS entry is present in argv",
            all(t in argv for t in ALWAYS_DISALLOWED_TOOLS), ev,
        )

        # §14 composition — the half that depends on Lane F's wiring.
        prompt_text = spec.append_system_prompt or ""
        comp_ev = write_evidence(
            self.fx.evidence_dir, "argv.append_system_prompt.txt", prompt_text
        )
        self.check(
            "COMP-1", "§14 worker context composition (LANE F)",
            f"the worker's --append-system-prompt CONTAINS the curated root "
            f"guidance token {self.proj_tokens['PROJROOT']}",
            self.proj_tokens["PROJROOT"] in prompt_text, comp_ev,
            "FAILS until Lane F composes the guidance projection into the "
            "worker invocation. Not vacuous: the token is literal.",
        )
        self.check(
            "COMP-2", "§14 worker context composition (LANE F)",
            f"the worker's --append-system-prompt CONTAINS the approved skill "
            f"token {self.tok('APPROVEDSKILL')}",
            self.tok("APPROVEDSKILL") in prompt_text, comp_ev,
            "FAILS until Lane F composes the skill projection into the worker "
            "invocation. Not vacuous: the token is literal.",
        )
        self.check(
            "COMP-3", "§14 worker context composition",
            f"the worker's --append-system-prompt does NOT contain the raw "
            f"root CLAUDE.md token ({self.tok('ROOTCLAUDE')})",
            self.tok("ROOTCLAUDE") not in prompt_text, comp_ev,
        )

    # -- live arms -------------------------------------------------------

    def arm_live(self, arm: str, admissible: tuple[str, ...]) -> None:
        eprint(f"[arm] live/{arm}")
        for probe in PROBES:
            base = (
                self.fx.agents_only_repo if probe.repo == "agents_only" else self.fx.repo
            )
            cwd = (base / probe.cwd_rel).resolve()
            self.fx.reset_fired()
            if arm == "safe":
                argv = [
                    CLAUDE, "-p", "--model", "sonnet", "--output-format", "json",
                    "--permission-mode", "auto", "--safe-mode", probe.prompt,
                ]
                env = clean_child_env()
            else:
                argv, spec = self.worker_argv(probe.prompt, cwd)
                env = dict(spec.env)
            inv = run_cli(
                f"{arm}/{probe.ident}", argv, cwd=cwd, env=env,
                timeout_s=300, ledger=self.ledger,
            )
            fired = sorted(self.fx.fired_now())
            ev = write_evidence(
                self.fx.evidence_dir, f"{probe.ident}.{arm}.json",
                json.dumps(
                    {
                        "arm": arm, "probe": probe.ident, "cwd": str(cwd),
                        "argv": argv, "invocation": inv.to_record(),
                        "fired_files": fired, "raw_stdout": inv.stdout,
                        "raw_stderr": inv.stderr,
                    },
                    indent=2,
                ),
            )
            haystack = inv.stdout + inv.stderr

            # PRECONDITION. A probe that never ran cannot suppress anything,
            # and "the token was absent from an empty stream" is precisely the
            # vacuous pass this harness exists to prevent. So every probe must
            # first prove it engaged the CLI: a clean exit, a parseable result,
            # and either a real model turn or the CLI explicitly saying the
            # surface does not exist (which is itself the suppression evidence).
            parsed = inv.parsed or {}
            turns = parsed.get("num_turns", 0)
            explicit = any(
                marker in inv.result_text
                for marker in ("Unknown command", "UNAVAILABLE", "UNKNOWN")
            )
            ran = (
                inv.exit_code == 0
                and inv.parsed is not None
                and not parsed.get("is_error", True)
                and (turns > 0 or explicit)
            )
            self.check(
                f"{arm}/{probe.ident}/RAN", "probe liveness",
                "the probe actually engaged the CLI, so its silence is "
                "evidence rather than an empty run",
                ran, ev,
                f"exit={inv.exit_code} is_error={parsed.get('is_error')} "
                f"num_turns={turns} result={inv.result_text[:160]!r}",
            )

            for sent in self.fx.sentinels.values():
                if sent.probe != probe.ident or not sent.live_probe:
                    continue
                if sent.key not in admissible:
                    self.assertions.append(
                        Assertion(
                            f"{arm}/{sent.key}", sent.surface,
                            "suppression not scored — no firing baseline",
                            True, ev,
                            "INADMISSIBLE: this sentinel did not fire in the "
                            "positive control, so its silence here proves "
                            "nothing. Excluded, not counted as a pass.",
                        )
                    )
                    continue
                token_seen = sent.token in haystack
                file_seen = Path(sent.fired_path).name in fired
                suppressed = not token_seen and not file_seen
                self.check(
                    f"{arm}/{sent.key}", sent.surface,
                    f"SUPPRESSED under {arm}: neither the token {sent.token} nor "
                    f"the fired file appears",
                    suppressed, ev,
                    f"token_seen={token_seen} file_seen={file_seen} "
                    f"exit={inv.exit_code}",
                )
            eprint(
                f"  [{arm}/{probe.ident}] exit={inv.exit_code} "
                f"cost=${inv.cost_usd:.4f} fired={fired}"
            )

    # -- output ----------------------------------------------------------

    def render(self, stray: list[str], arms: list[str]) -> str:
        out: list[str] = []
        a = out.append
        scored = [
            x for x in self.assertions if not x.detail.startswith("INADMISSIBLE")
        ]
        excluded = len(self.assertions) - len(scored)
        passed = [x for x in scored if x.passed]
        failed = [x for x in scored if not x.passed]
        a("# GATE 4.5 — DISPOSABLE LIVE ADVERSARIAL GATE RESULT (Lane G)\n")
        a(f"- Run nonce: `{self.fx.nonce}`")
        a(f"- Arms run: {', '.join(arms)}")
        a(
            f"- Assertions: **{len(passed)} PASS / {len(failed)} FAIL**, "
            f"plus {excluded} EXCLUDED as inadmissible (no firing baseline)"
        )
        a(f"- Live cost: **${self.ledger.total_usd:.6f}** over "
          f"{len(self.ledger.invocations)} invocations")
        a("")
        a("## Assertions\n")
        a("| id | surface | statement | result | evidence | detail |")
        a("|---|---|---|---|---|---|")
        for x in self.assertions:
            # An excluded sentinel must never read as a green tick. It is
            # neither a pass nor a failure — it is evidence we do not have.
            if x.detail.startswith("INADMISSIBLE"):
                verdict = "N/A — EXCLUDED"
            else:
                verdict = f"**{'PASS' if x.passed else 'FAIL'}**"
            a(
                f"| `{x.ident}` | {x.surface} | {x.statement} | {verdict} | "
                f"`{Path(x.evidence).name}` | {x.detail} |"
            )
        a("")
        a("## Cost\n")
        a(self.ledger.table())
        a("")
        a("## Safety\n")
        a(
            f"- Stray-sentinel scan for `*{self.fx.nonce}*`: "
            + ("**NONE FOUND**" if not stray else f"**HITS** {stray}")
        )
        a("")
        return "\n".join(out)


def _production_still_inert() -> bool:
    """The gate must not have flipped a production flag (Sol ruling 2)."""
    repo = Path(__file__).resolve().parents[2]
    toml_text = (repo / "config" / "dispatcher.toml").read_text(encoding="utf-8")
    guidance = json.loads((repo / "config" / "approved-guidance.json").read_text())
    import tomllib

    data = tomllib.loads(toml_text)
    skills_off = not data.get("skills", {}).get("enabled", False)
    pg_off = not data.get("project_guidance", {}).get("enabled", False)
    pending = guidance["approval"]["state"] == "PENDING_SOL"
    return skills_off and pg_off and pending


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument(
        "--arms", default="engine,argv",
        help="comma-separated: engine, argv, safe, dispatcher",
    )
    ap.add_argument(
        "--out",
        default="/home/dev/.claude/auto-mode/commissioning/GATE-LIVE-RESULT.md",
    )
    args = ap.parse_args()
    arms = [x.strip() for x in args.arms.split(",") if x.strip()]

    gate = Gate(keep=args.keep)
    eprint(f"[fixture] {gate.fx.repo} nonce={gate.fx.nonce}")
    if "engine" in arms:
        gate.arm_engine()
    if "argv" in arms:
        gate.arm_argv_invariants()
    if "safe" in arms:
        gate.arm_live("safe", DEFAULT_ADMISSIBLE)
    if "dispatcher" in arms:
        gate.arm_live("dispatcher", DEFAULT_ADMISSIBLE)

    stray = stray_sentinel_scan(gate.fx.nonce, PROTECTED_ROOTS)
    Path(args.out).write_text(gate.render(stray, arms), encoding="utf-8")
    eprint(f"[report] {args.out}")

    keep_dir = Path("/home/dev/.claude/auto-mode/commissioning/gate-evidence")
    keep_dir.mkdir(parents=True, exist_ok=True)
    for f in gate.fx.evidence_dir.iterdir():
        shutil.copy2(f, keep_dir / f.name)

    eprint(cleanup(gate.fx.root, keep=args.keep))
    failed = [x for x in gate.assertions if not x.passed]
    eprint(
        f"[verdict] {len(gate.assertions) - len(failed)} PASS / {len(failed)} FAIL "
        f"| cost ${gate.ledger.total_usd:.6f}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
