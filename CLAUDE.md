# CLAUDE.md — engineering rules for this repository

These rules apply to any agent or human working **on the dispatcher itself**.
`AGENTS.md` carries the same core rules; if you change one, change both. They
are kept aligned deliberately (§34 of the build brief).

Do not confuse these with `prompts/worker-policy.md`. That file is orchestration
law for a *dispatched worker* operating on some other repository. This file is
engineering law for people building this codebase.

---

## 1. What this project is

A deterministic MCP control layer. It routes, executes, records, and enforces.
It does not reason.

If you are about to add something that makes a judgement call — inferring what
the user "really meant", deciding whether an implementation is good enough,
choosing to retry because it seems sensible — stop. That belongs to Sol. The
dispatcher's job is to make Sol's decisions executable and auditable, not to
make them.

## 2. The rules that are not negotiable

**Claims are not evidence.** `WorkerResult` is what Claude said.
`DispatcherObservations` is what we measured. They are separate types with zero
overlapping field names, and a test enforces that. Never populate an
observation field from parsed worker output.

**The dispatcher never approves.** There is no `APPROVED` state and you must
not add one. "Implementation complete", "review complete" and "user approved"
are three different things.

**Fail closed.** Unknown config key, unparseable state, unresolvable path,
malformed output — refuse, and say precisely why. Never guess, never repair
silently, never fall back to something permissive.

**argv, never shells.** `create_subprocess_exec` with a list. No `shell=True`,
no interpolated command strings. And never execute anything that appeared
inside a Claude result — trusted commands come from the task envelope only.

**stdout belongs to MCP.** A `print()` in the server process corrupts the
JSON-RPC transport. Log to stderr or a file.

**Prompts are not sandboxing.** When you document a protection, say honestly
whether it is hard-enforced or advisory. `docs/SECURITY.md` keeps that split
explicit and must stay accurate.

## 3. Safety rules for the build environment

This VPS has live Codex and Claude sessions on it. While working here:

- never modify `~/.codex/config.toml`, Claude settings, or any MCP server
  configuration;
- never delete or inspect Codex/Claude session state;
- never spawn a real `claude` or `codex` child process from a test or a build
  step — `tests/fake_bin/claude` exists for exactly this reason;
- never touch a repository outside this project;
- never push, merge, or deploy.

## 4. How to add code

Read `docs/INTERFACES.md` first. It is the contract between modules that were
written in parallel by people who could not talk to each other. If a signature
there looks wrong, implement it as written and raise the objection separately —
changing a shared signature unilaterally breaks a module you cannot see.

Test-first for anything in the safety path: routing, state transitions,
recursion prevention, path validation, scope checks, locking, timeouts, result
parsing. §31 of the brief lists the required cases; treat it as a checklist.

Do not write `"should work"` where a deterministic test can prove it.

## 5. Style

Prefer simple, deterministic, auditable, recoverable, testable, fail-closed
over clever, magical, or agentic-for-its-own-sake. This is production
infrastructure that will run unattended against real repositories; boring is
the goal.

Comments explain *why*, especially why something is refused. A reader six
months from now needs to know which constraints are load-bearing before they
relax one.

Type-annotate public functions. Keep module boundaries strict: MCP layer,
routing, subprocess execution, state, git, validation, security, schemas.

## 6. Before you say you are done

```bash
.venv/bin/python -m pytest
.venv/bin/python -m compileall -q src
git diff --check
```

Then state what you changed, what you tested, and what you did *not* verify.
An honest gap is useful. An unsupported claim of completeness is not.
