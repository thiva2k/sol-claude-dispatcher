from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.mutation.run_mutations import (
    Invariant,
    Mutation,
    RegistryError,
    load_registry,
    validate_registry,
)


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/mutation/run_mutations.py"


def test_source_controlled_registry_is_total_unique_and_resolvable() -> None:
    registry = load_registry(ROOT)

    assert registry.schema_version == 1
    assert len(registry.implemented_wave0) == 24
    assert {item.id for item in registry.invariants} == set(registry.implemented_wave0)
    assert len({mutant for item in registry.invariants for mutant in item.mutants}) == 24
    assert all(item.mutants and item.killers for item in registry.invariants)


def test_registry_refuses_missing_duplicate_and_unknown_invariant_mappings() -> None:
    registry = load_registry(ROOT)

    with pytest.raises(RegistryError, match="missing=.*ZI-86"):
        validate_registry(ROOT, replace(registry, invariants=registry.invariants[:-1]))

    with pytest.raises(RegistryError, match="duplicate implemented Wave 0 invariant"):
        validate_registry(
            ROOT,
            replace(
                registry,
                implemented_wave0=registry.implemented_wave0 + (registry.implemented_wave0[0],),
            ),
        )

    unknown = replace(registry.invariants[0], id="ZI-999")
    with pytest.raises(RegistryError, match="unknown=.*ZI-999"):
        validate_registry(ROOT, replace(registry, invariants=(unknown, *registry.invariants[1:])))


def test_registry_refuses_missing_duplicate_unknown_and_unowned_mutants() -> None:
    registry = load_registry(ROOT)
    first, second, *tail = registry.invariants

    with pytest.raises(RegistryError, match="has no named mutant"):
        validate_registry(ROOT, replace(registry, invariants=(replace(first, mutants=()), second, *tail)))

    with pytest.raises(RegistryError, match="unknown mutants"):
        validate_registry(
            ROOT,
            replace(registry, invariants=(replace(first, mutants=("W0-M999",)), second, *tail)),
        )

    with pytest.raises(RegistryError, match="duplicate invariant-to-mutant mapping"):
        validate_registry(
            ROOT,
            replace(
                registry,
                invariants=(first, replace(second, mutants=first.mutants), *tail),
            ),
        )

    extra = Mutation("W0-M999", first.mutants[0], "x", "y")
    with pytest.raises(RegistryError, match="unmapped"):
        validate_registry(ROOT, replace(registry, mutations=(*registry.mutations, extra)))


def test_registry_refuses_missing_or_matrix_only_killers() -> None:
    registry = load_registry(ROOT)
    first, *tail = registry.invariants

    with pytest.raises(RegistryError, match="has no named killer"):
        validate_registry(ROOT, replace(registry, invariants=(replace(first, killers=()), *tail)))

    with pytest.raises(RegistryError, match="only matrix killer"):
        validate_registry(
            ROOT,
            replace(
                registry,
                invariants=(
                    replace(first, killers=("tests/unit/test_gate7_matrix.py::test_120x2_matrix",)),
                    *tail,
                ),
            ),
        )

    with pytest.raises(RegistryError, match="does not exist"):
        validate_registry(
            ROOT,
            replace(
                registry,
                invariants=(
                    replace(first, killers=("tests/unit/test_gate7_ignore.py::test_absent",)),
                    *tail,
                ),
            ),
        )


def test_registry_refuses_unsafe_targets_stale_anchors_and_noop_replacements() -> None:
    registry = load_registry(ROOT)
    first_mutation, *tail = registry.mutations

    with pytest.raises(RegistryError, match="outside declared"):
        validate_registry(
            ROOT,
            replace(
                registry,
                mutations=(replace(first_mutation, target="docs/GATE7-DESIGN.md"), *tail),
            ),
        )

    with pytest.raises(RegistryError, match="anchor occurs 0 times"):
        validate_registry(
            ROOT,
            replace(
                registry,
                mutations=(replace(first_mutation, anchor="definitely absent anchor"), *tail),
            ),
        )

    with pytest.raises(RegistryError, match="byte-identical"):
        validate_registry(
            ROOT,
            replace(
                registry,
                mutations=(replace(first_mutation, replacement=first_mutation.anchor), *tail),
            ),
        )


def test_default_runner_is_read_only_and_gate_report_requires_full_execution(tmp_path: Path) -> None:
    protected = [
        ROOT / "scripts/mutation/invariants.toml",
        ROOT / "scripts/mutation/mutants/gate7/wave0.json",
        ROOT / "src/sol_claude_dispatcher/evidence/ignore.py",
    ]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    report_path = tmp_path / "check.json"

    completed = subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(RUNNER), "--report", str(report_path)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["mode"] == "check"
    assert json.loads(report_path.read_text())["mode"] == "check"
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}

    rejected = subprocess.run(
        [str(ROOT / ".venv/bin/python"), str(RUNNER), "--gate-report"],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert rejected.returncode != 0
    assert "requires --execute --full" in rejected.stderr
