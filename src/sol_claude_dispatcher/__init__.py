"""sol-claude-dispatcher.

A deterministic MCP control layer that lets Sol (running on Codex) delegate
implementation work to controlled Claude Code workers, and independent review
to Fable, without ever surrendering orchestration or approval authority.

The package contains no LLM intelligence. It is execution plumbing: routing,
subprocess control, state, git evidence, and policy enforcement. Every
judgement call belongs to Sol; every final approval belongs to the human.

Module map (see ``docs/INTERFACES.md`` for the full contract):

===============  ==========================================================
``models``       Pydantic v2 core types. Caller input vs dispatcher truth;
                 worker claims vs dispatcher observations.
``errors``       Typed error taxonomy returned across the MCP boundary.
``config``       Fail-closed TOML configuration. Model ids live here only.
``router``       Deterministic model selection.
``state``        Atomic task persistence and state-machine transitions.
``locks``        One mutating worker per repository.
``git``          Base commits, worktree naming, diff evidence, scope checks.
``security``     Repository allowlist, recursion detection.
``runner``       Async subprocess execution with process-group timeouts.
``sessions``     Session identity, resume rules and caps.
``results``      Parsing and validating structured worker/reviewer output.
``validation``   Independent re-execution of trusted validation commands.
``skills``       Approved-skill projection: hash-pinned inert guidance,
                 manifest-driven, never a skill runtime.
``project_guidance``  Curated project-guidance projection: hash-pinned,
                 scope-aware, manifest-driven, never a CLAUDE.md loader.
``worker_context``  Final worker-context composition (ADDENDUM §14) and the
                 combined context fingerprint (§16). The only place the two
                 projections meet dispatcher-authored policy text.
``server``       The stdio MCP server exposing exactly four tools.
===============  ==========================================================
"""

from __future__ import annotations

__version__ = "0.1.0"

#: The MCP server name Codex will reference (§6).
SERVER_NAME = "sol-claude-dispatcher"

__all__ = ["__version__", "SERVER_NAME"]
