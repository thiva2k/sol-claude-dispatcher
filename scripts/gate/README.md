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
