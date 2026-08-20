"""The probe matrix: which prompt, from which directory, exercises which surface.

One definition shared by every arm of the gate. The positive-control arm and
the suppression arms MUST run the same prompts from the same directories,
otherwise "it did not fire under safe mode" could just mean "we asked it
something else."
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Probe:
    ident: str
    #: Repository-relative working directory the CLI is launched from.
    cwd_rel: str
    prompt: str
    intent: str
    #: Which throwaway repo to launch in: the main fixture, or the separate
    #: CLAUDE.md-free repo used to isolate the AGENTS.md question.
    repo: str = "main"


PROBES: tuple[Probe, ...] = (
    Probe(
        ident="P1_root",
        cwd_rel=".",
        prompt=(
            "Using only the project context you already have — do not read, "
            "search or open any file — list these values, one per line, in the "
            "form 'label: value'. Write UNKNOWN as the value for anything you "
            "were not given.\n"
            "1. internal build identifier\n"
            "2. agent handbook code\n"
            "3. release marker\n"
            "4. session bootstrap code\n"
            "5. per-turn code"
        ),
        intent=(
            "Asks for five random nonces the model can only know if the root "
            "CLAUDE.md, root AGENTS.md, the operator-only section, and the two "
            "hooks reached its context. 'Do not read any file' is essential: it "
            "forces the answer to come from auto-loaded context, not from the "
            "worker deciding to open CLAUDE.md itself."
        ),
    ),
    Probe(
        ident="P2_nested",
        cwd_rel="SubAgent/deep/nested",
        prompt=(
            "Using only the project context you already have — do not read, "
            "search or open any file — list these values, one per line, in the "
            "form 'label: value'. Write UNKNOWN as the value for anything you "
            "were not given.\n"
            "1. subproject module code\n"
            "2. subproject agent code\n"
            "3. widget calibration code"
        ),
        intent=(
            "Launched from the deepest directory, the most favourable possible "
            "condition for nested instruction discovery."
        ),
    ),
    Probe(
        ident="P3_command",
        cwd_rel=".",
        prompt="/gate-sentinel-command",
        intent="Invokes the project's custom slash command by name.",
    ),
    Probe(
        ident="P4_skill",
        cwd_rel=".",
        prompt=(
            "Use the gate sentinel skill and tell me the sentinel skill code it "
            "carries. If no such skill is available to you, reply UNAVAILABLE."
        ),
        intent="Asks for the project skill by name.",
    ),
    Probe(
        ident="P5_agent",
        cwd_rel=".",
        prompt=(
            "Launch the subagent whose type is gate-sentinel-agent and ask it to "
            "report. Repeat its reply verbatim in your final answer. If no such "
            "subagent type is available to you, reply UNAVAILABLE."
        ),
        intent="Asks for the project's custom agent by name.",
    ),
    Probe(
        ident="P6_mcp",
        cwd_rel=".",
        prompt=(
            "Call the gate_sentinel_ping tool and repeat its output verbatim in "
            "your final answer. If no such tool is available to you, reply "
            "UNAVAILABLE."
        ),
        intent="Asks for the project-scoped MCP server's tool by name.",
    ),
    Probe(
        ident="P7_agents_only",
        cwd_rel=".",
        repo="agents_only",
        prompt=(
            "Using only the project context you already have — do not read, "
            "search or open any file — state the standalone handbook code for "
            "this repository, or UNKNOWN if you were not given it."
        ),
        intent=(
            "Isolating control. Runs in a throwaway repo that contains AGENTS.md "
            "and no CLAUDE.md anywhere, so a UNKNOWN here means AGENTS.md is not "
            "auto-loaded at all rather than merely losing to CLAUDE.md."
        ),
    ),
)

BY_ID = {p.ident: p for p in PROBES}
