#!/usr/bin/env python3
"""Validate and, only when explicitly requested, run declared mutations.

The default operation is read-only.  ``--execute`` creates a disposable copy
of the repository for each mutant, so an interrupted run cannot leave source
files modified.  Declarative mutation files are JSON and are never imported or
executed as Python.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


REGISTRY_RELATIVE = Path("scripts/mutation/invariants.toml")
MUTANTS_RELATIVE = Path("scripts/mutation/mutants/gate7")
_ALLOWED_TARGET_PREFIXES = ("src/sol_claude_dispatcher/", "tests/")


class RegistryError(ValueError):
    """The source-controlled mutation declaration is inconsistent."""


@dataclass(frozen=True, slots=True)
class Invariant:
    id: str
    statement: str
    creates: str
    lands_in: tuple[str, ...]
    modifies: tuple[str, ...]
    design_section: str
    mutants: tuple[str, ...]
    killers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Mutation:
    id: str
    target: str
    anchor: str
    replacement: str


@dataclass(frozen=True, slots=True)
class Registry:
    schema_version: int
    implemented_wave0: tuple[str, ...]
    invariants: tuple[Invariant, ...]
    mutations: tuple[Mutation, ...]


def repository_root(start: Path | None = None) -> Path:
    cursor = (start or Path(__file__)).resolve()
    if cursor.is_file():
        cursor = cursor.parent
    for candidate in (cursor, *cursor.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / REGISTRY_RELATIVE).is_file():
            return candidate
    raise RegistryError("repository root containing the mutation registry was not found")


def load_registry(root: Path) -> Registry:
    values, rows = _parse_registry(root / REGISTRY_RELATIVE)
    try:
        schema_version = int(values["schema_version"])
        implemented = _string_tuple(values["implemented_wave0"], "implemented_wave0")
    except KeyError as exc:
        raise RegistryError(f"registry is missing top-level field {exc.args[0]!r}") from exc
    invariants = tuple(_invariant_from_row(row) for row in rows)
    mutations = _load_mutations(root / MUTANTS_RELATIVE)
    registry = Registry(schema_version, implemented, invariants, mutations)
    validate_registry(root, registry)
    return registry


def validate_registry(root: Path, registry: Registry) -> None:
    if registry.schema_version != 1:
        raise RegistryError("unsupported registry schema version")
    _require_unique(registry.implemented_wave0, "implemented Wave 0 invariant")
    invariant_ids = tuple(item.id for item in registry.invariants)
    _require_unique(invariant_ids, "invariant row")
    expected = set(registry.implemented_wave0)
    actual = set(invariant_ids)
    if expected != actual:
        raise RegistryError(
            "implemented invariant mapping is not total: "
            f"missing={sorted(expected - actual)!r}, unknown={sorted(actual - expected)!r}"
        )

    mutation_ids = tuple(item.id for item in registry.mutations)
    _require_unique(mutation_ids, "mutation declaration")
    known_mutations = set(mutation_ids)
    mapped_mutations: list[str] = []
    known_killers: set[str] = set()
    for invariant in registry.invariants:
        if not invariant.mutants:
            raise RegistryError(f"{invariant.id} has no named mutant")
        if not invariant.killers:
            raise RegistryError(f"{invariant.id} has no named killer")
        if set(invariant.mutants) - known_mutations:
            raise RegistryError(
                f"{invariant.id} names unknown mutants "
                f"{sorted(set(invariant.mutants) - known_mutations)!r}"
            )
        if all(_is_matrix_node(node) for node in invariant.killers):
            raise RegistryError(f"{invariant.id} names only matrix killer nodes")
        mapped_mutations.extend(invariant.mutants)
        for node in invariant.killers:
            _validate_killer_node(root, node)
            known_killers.add(node)
    _require_unique(tuple(mapped_mutations), "invariant-to-mutant mapping")
    unmapped = known_mutations - set(mapped_mutations)
    if unmapped:
        raise RegistryError(f"mutation declarations are unmapped: {sorted(unmapped)!r}")

    for mutation in registry.mutations:
        target = _safe_target(root, mutation.target)
        text = target.read_text(encoding="utf-8")
        count = text.count(mutation.anchor)
        if count != 1:
            raise RegistryError(
                f"{mutation.id} anchor occurs {count} times in {mutation.target}; expected exactly one"
            )
        if mutation.anchor == mutation.replacement:
            raise RegistryError(f"{mutation.id} replacement is byte-identical to its anchor")


def execute_mutations(
    root: Path,
    registry: Registry,
    *,
    full: bool,
) -> dict[str, object]:
    """Run mutations in disposable repository copies; never edit ``root``."""

    invariant_by_mutant = {
        mutant: invariant
        for invariant in registry.invariants
        for mutant in invariant.mutants
    }
    results: list[dict[str, object]] = []
    for mutation in sorted(registry.mutations, key=lambda item: item.id):
        invariant = invariant_by_mutant[mutation.id]
        with tempfile.TemporaryDirectory(prefix="sol-gate7-mutant-") as temp:
            clone = Path(temp) / "repo"
            _copy_repository(root, clone)
            target = _safe_target(clone, mutation.target)
            original = target.read_bytes()
            original_sha = hashlib.sha256(original).hexdigest()
            text = original.decode("utf-8")
            target.write_text(text.replace(mutation.anchor, mutation.replacement, 1), encoding="utf-8")
            argv = [sys.executable, "-m", "pytest", "-q", *invariant.killers]
            targeted = subprocess.run(
                argv,
                cwd=clone,
                env=_test_environment(clone),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            full_run: subprocess.CompletedProcess[str] | None = None
            if full:
                full_run = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q"],
                    cwd=clone,
                    env=_test_environment(clone),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
            # The authoritative tree was never touched.  The copied original is
            # nevertheless verified so a malformed copy cannot produce a report.
            if hashlib.sha256(original).hexdigest() != original_sha:
                raise RegistryError(f"{mutation.id} disposable baseline changed unexpectedly")
            caught = targeted.returncode != 0
            results.append(
                {
                    "id": mutation.id,
                    "invariant": invariant.id,
                    "status": "caught" if caught else "survived",
                    "targeted_returncode": targeted.returncode,
                    "full_returncode": None if full_run is None else full_run.returncode,
                    "first_killer": invariant.killers[0] if caught else None,
                    "output_sha256": hashlib.sha256(targeted.stdout.encode()).hexdigest(),
                }
            )
    return {
        "schema_version": 1,
        "mode": "full" if full else "fast",
        "execution": "disposable_copy",
        "registry_sha256": hashlib.sha256((root / REGISTRY_RELATIVE).read_bytes()).hexdigest(),
        "results": results,
    }


def _parse_registry(path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    top: dict[str, object] = {}
    rows: list[dict[str, object]] = []
    current = top
    for line_number, source_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[[invariant]]":
            current = {}
            rows.append(current)
            continue
        if "=" not in line:
            raise RegistryError(f"invalid registry syntax at line {line_number}")
        key, raw_value = (part.strip() for part in line.split("=", 1))
        if not key or key in current:
            raise RegistryError(f"duplicate or empty registry key at line {line_number}")
        try:
            current[key] = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise RegistryError(f"unsupported registry value at line {line_number}") from exc
    return top, rows


def _invariant_from_row(row: dict[str, object]) -> Invariant:
    expected = {
        "id", "statement", "creates", "lands_in", "modifies",
        "design_section", "mutants", "killers",
    }
    if set(row) != expected:
        raise RegistryError(
            "invariant fields differ from schema: "
            f"missing={sorted(expected - set(row))!r}, unknown={sorted(set(row) - expected)!r}"
        )
    return Invariant(
        id=_string(row["id"], "id"),
        statement=_string(row["statement"], "statement"),
        creates=_string(row["creates"], "creates"),
        lands_in=_string_tuple(row["lands_in"], "lands_in"),
        modifies=_string_tuple(row["modifies"], "modifies"),
        design_section=_string(row["design_section"], "design_section"),
        mutants=_string_tuple(row["mutants"], "mutants"),
        killers=_string_tuple(row["killers"], "killers"),
    )


def _load_mutations(directory: Path) -> tuple[Mutation, ...]:
    rows: list[Mutation] = []
    files = sorted(directory.glob("*.json"))
    if not files:
        raise RegistryError("no source-controlled mutation declarations were found")
    for path in files:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise RegistryError(f"{path} must contain a JSON list")
        for raw in value:
            if not isinstance(raw, dict) or set(raw) != {"id", "target", "anchor", "replacement"}:
                raise RegistryError(f"{path} contains a malformed mutation declaration")
            rows.append(
                Mutation(
                    id=_string(raw["id"], "mutation.id"),
                    target=_string(raw["target"], "mutation.target"),
                    anchor=_string(raw["anchor"], "mutation.anchor"),
                    replacement=_string(raw["replacement"], "mutation.replacement"),
                )
            )
    return tuple(rows)


def _safe_target(root: Path, relative: str) -> Path:
    if not relative.startswith(_ALLOWED_TARGET_PREFIXES) or "\\" in relative:
        raise RegistryError(f"mutation target is outside declared source/test roots: {relative!r}")
    rel = Path(relative)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise RegistryError(f"mutation target is not a canonical relative path: {relative!r}")
    target = root / rel
    if target.is_symlink() or not target.is_file():
        raise RegistryError(f"mutation target is absent, non-regular, or a symlink: {relative!r}")
    if root.resolve() not in target.resolve().parents:
        raise RegistryError(f"mutation target escapes repository root: {relative!r}")
    return target


def _validate_killer_node(root: Path, node: str) -> None:
    if not node.startswith("tests/") or "::" not in node or any(ch in node for ch in "\0\r\n"):
        raise RegistryError(f"killer is not a canonical pytest node id: {node!r}")
    components = node.split("::")
    if len(components) not in (2, 3):
        raise RegistryError(f"killer names an unsupported pytest node shape: {node!r}")
    path_text, test_name = components[0], components[-1]
    path = _safe_target(root, path_text)
    if not test_name.startswith("test_"):
        raise RegistryError(f"killer names an unsupported pytest node shape: {node!r}")
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise RegistryError(f"killer module does not parse: {path_text!r}") from exc
    scope: Sequence[ast.stmt] = tree.body
    if len(components) == 3:
        class_name = components[1]
        classes = [
            item for item in tree.body
            if isinstance(item, ast.ClassDef) and item.name == class_name
        ]
        if len(classes) != 1:
            raise RegistryError(f"killer class does not exist exactly once: {node!r}")
        scope = classes[0].body
    matches = [
        item for item in scope
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == test_name
    ]
    if len(matches) != 1:
        raise RegistryError(f"killer node does not exist: {node!r}")


def _copy_repository(source: Path, destination: Path) -> None:
    ignored_names = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache"}

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in ignored_names or name.endswith(".pyc")}

    shutil.copytree(source, destination, symlinks=True, ignore=ignore)


def _test_environment(root: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env["PYTHONPATH"] = str(root / "src")
    return env


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RegistryError(f"{field} must be a non-empty string")
    return value


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise RegistryError(f"{field} must be an array of non-empty strings")
    return tuple(value)


def _require_unique(values: Sequence[str], label: str) -> None:
    duplicates = sorted({item for item in values if values.count(item) > 1})
    if duplicates:
        raise RegistryError(f"duplicate {label}s: {duplicates!r}")


def _is_matrix_node(node: str) -> bool:
    lowered = node.lower()
    return "matrix" in lowered or "120x2" in lowered or "120_x_2" in lowered


def _write_report(path: Path, report: dict[str, object]) -> None:
    encoded = (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(encoded)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="run mutants in disposable copies")
    parser.add_argument("--full", action="store_true", help="also run the full suite for every mutant")
    parser.add_argument("--gate-report", action="store_true", help="mark output as gate-signing evidence")
    parser.add_argument("--report", type=Path, help="write canonical JSON report")
    args = parser.parse_args(tuple(argv) if argv is not None else None)
    if args.full and not args.execute:
        parser.error("--full requires --execute")
    if args.gate_report and not (args.execute and args.full):
        parser.error("a gate report requires --execute --full")
    try:
        root = repository_root()
        registry = load_registry(root)
        if not args.execute:
            report: dict[str, object] = {
                "schema_version": 1,
                "mode": "check",
                "invariant_count": len(registry.invariants),
                "mutation_count": len(registry.mutations),
            }
        else:
            report = execute_mutations(root, registry, full=args.full)
            report["gate_signing"] = bool(args.gate_report)
        if args.report is not None:
            _write_report(args.report, report)
        sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
        if args.execute and any(
            item.get("status") != "caught" for item in report.get("results", [])
        ):
            return 1
        return 0
    except (OSError, RegistryError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"mutation registry refused: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
