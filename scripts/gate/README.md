# `scripts/gate/` — the disposable live adversarial gate (Gate 4.5, Lane G)

This directory spawns the **real** Claude CLI. It is deliberately **not** under
`tests/`, because the repository rule is "never spawn a real `claude` or `codex`
child process from a test" and pytest must never collect any of it. Run it by
hand, on purpose, with the cost in front of you.

Nothing here is imported by `src/sol_claude_dispatcher`. Deleting this whole
directory would not change a single production code path.

## The idea

`claude --safe-mode` claims to disable every customization surface. Emitting the
flag is not proof that it does. Neither is the help text. The only thing that
proves suppression is planting a real sentinel on each surface, in a throwaway
repository, and watching it not fire.

And a suppression proof is worthless without a **positive control**. If a
sentinel never fired in the first place, "safe mode suppressed it" proves
nothing — the test passes vacuously and we ship a false GREEN. So every sentinel
must first be shown to fire under a normal invocation. Only then is its silence
under safe mode evidence of anything.

## Running it

```bash
# Part 3 — establish the firing baseline. Do this first, and after any
# sentinel redesign. ~7 live invocations.
.venv/bin/python scripts/gate/positive_control.py

# Part 4 — free arms only: the projection engines and the argv invariants.
.venv/bin/python scripts/gate/run_gate.py --arms engine,argv

# Part 4 — everything, including both live suppression arms.
.venv/bin/python scripts/gate/run_gate.py --arms engine,argv,safe,dispatcher
```

`--keep` leaves the temp tree in place for inspection. Without it the tree is
removed and the raw evidence is copied to
`~/.claude/auto-mode/commissioning/gate-evidence/`.

## Layout

| file | what it is |
|---|---|
| `_common.py` | Invocation, cost ledger, assertion record, write-target safety, stray-sentinel scan. |
| `fixture.py` | Builds the throwaway repo, plants every sentinel, writes the ephemeral projection-ENABLED config. |
| `manifests.py` | Generates the throwaway skill and project-guidance manifests, pinned to the fixture. |
| `probes.py` | The probe matrix — one prompt/cwd definition shared by every arm, so arms stay comparable. |
| `positive_control.py` | Part 3. Proves each sentinel fires **without** `--safe-mode`. |
| `run_gate.py` | Part 4. Engine, argv, and the two live suppression arms. |

## Rules this harness holds itself to

- **Enabling projection is a pure config change.** The ephemeral TOML sets
  `[skills].enabled` and `[project_guidance].enabled` to `true` and points at
  throwaway manifests. There is no environment escape hatch and no "if testing"
  branch anywhere in `src/**`. If enabling ever requires a code edit, that is a
  DEFECT to report — not something to work around here.
- **Production stays inert.** `CFG-2` asserts, every run, that
  `config/dispatcher.toml` still has both flags off and that
  `config/approved-guidance.json` is still `PENDING_SOL`.
- **Assertions are literal.** Every one names the exact nonce it expects to find
  or not find, and `MUT-1` proves it by blanking a projection artifact and
  confirming the presence assertion goes red.
- **Nothing global is touched.** Every sentinel is project-scoped inside the
  throwaway tree. `assert_write_target_safe()` refuses to arm any write outside
  `/tmp`, and refuses `/home/dev/full-voice-agent`, `~/.claude`, `~/.codex` and
  this repository by name.
- **Every temp tree is removed**, and a stray-sentinel scan by run nonce over
  the protected roots is printed with the result.

## Known staleness against the Gate 7 Wave 0 contract (unfixed)

These harnesses predate the sealed lifecycle and **will refuse before reaching
their first live invocation**. This is recorded rather than repaired because
verifying a fix costs real Claude usage, and an unverified edit to a live-cost
harness is worth less than an accurate warning. `scripts/smoke-test-live.sh` hit
both of these and has been fixed; use it as the reference for what a correct
call site now looks like.

1. **`"base_ref": "HEAD"` is refused.** `repository.base_ref` must be an exact
   40-character lowercase commit object name — symbolic refs are forbidden
   (`models.py`, `RepositoryRequest._base_ref_is_an_exact_object_name`).
   Resolve it first: `git -C <repo> rev-parse HEAD`. Affects
   `blocking_live.py:466`, `mcp_stdio.py:206,351`, `run_gate.py:452`,
   `b2_live.py:470,1500`.
2. **No operator administrative baseline is established.** Every dispatch and
   resume loads one first and refuses `RepositoryAdministrationUnestablished`
   when it is absent. After building the throwaway fixture — and after the *last*
   mutation of its administrative state, since refs and config are compared for
   exact equality — each harness must run:
   ```bash
   .venv/bin/python scripts/trust-repo-admin.py <fixture-repo> --state-root <its-state-dir>
   ```
   The state root must be the one that harness writes into its ephemeral config.

Repository-guard fixtures are the exception: rejections are decided before the
baseline is consulted, so `/tmp/other-repo`, subdirectories and this repository
must stay un-onboarded or the rejections stop proving anything.
