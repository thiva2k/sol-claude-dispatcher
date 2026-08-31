# Gate 7 mutation runner

`invariants.toml` is the source-controlled map from implemented Wave 0
invariants to named mutants and pytest killer node ids. The registry checker
refuses missing rows, unknown rows, duplicate ids, unknown or multiply-owned
mutants, missing killer nodes, matrix-only killers, unsafe targets, and stale
anchors.

The default command is read-only:

```bash
.venv/bin/python scripts/mutation/run_mutations.py
```

Mutation requires the explicit `--execute` switch. Every mutant runs in its own
temporary copy; the working repository is never rewritten. `--full` additionally
runs the complete suite per mutant. A gate-signing report requires both
`--execute --full`; a fast report cannot sign a gate.

```bash
.venv/bin/python scripts/mutation/run_mutations.py --execute
.venv/bin/python scripts/mutation/run_mutations.py --execute --full --gate-report \
  --report mutations.json
```

Mutation declarations are inert JSON. Targets are limited to regular,
non-symlink files below `src/sol_claude_dispatcher/**` or `tests/**`; anchors
must occur exactly once. No declaration is imported or executed.

## Equivalent mutant A-d

The deleted Gate 6 mutant A-d compared per-component prompt-budget sums with a
composed-payload measurement. It was equivalent under the shipped constraints:
`skills_cap + guidance_cap + 8192 <= prompt_cap`, so no permitted component
shape could make every component fit while the composition exceeded the cap.
The killable replacement A-d' grows dispatcher-authored text beyond its fixed
reserve while the component bounds still hold. The Gate 6 port remains a Wave A
deliverable; it is not falsely listed as implemented by this Wave 0 registry.
