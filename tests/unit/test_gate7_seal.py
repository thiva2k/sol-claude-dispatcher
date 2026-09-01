from __future__ import annotations

import os
from pathlib import Path

import pytest

from sol_claude_dispatcher.errors import (
    BaseObjectVerificationFailed,
    RepositoryIdentityUnsealed,
    SealAbsentAfterWorker,
    SealIntegrityFailed,
)
from sol_claude_dispatcher.evidence.basetree import git_blob_oid
from sol_claude_dispatcher.evidence import seal


BASE = "b" * 40


def _tree(rows: list[tuple[bytes, str, bytes]]) -> bytes:
    return b"".join(
        b"100644 blob " + oid.encode() + b"\t" + path + b"\0"
        for path, oid, _ in rows
    )


def _batch(rows: list[tuple[str, bytes]]) -> bytes:
    return b"".join(
        f"{oid} blob {len(data)}\n".encode() + data + b"\n"
        for oid, data in rows
    )


def test_route_a_union_route_b_is_total_and_cas_is_self_verifying(tmp_path: Path) -> None:
    a = b"route-a"
    b = b"route-b"
    oa, ob = git_blob_oid(a), git_blob_oid(b)
    tree = _tree([(b"a", oa, a), (b"b", ob, b)])

    loaded = seal.create_task_seal(
        tmp_path / "materialisation",
        task_id="task",
        base_commit=BASE,
        ls_tree_output=tree,
        route_a_by_path={b"a": a, b"b": b"wrong-start-version"},
        route_b_batch_output=_batch([(ob, b)]),
    )

    by_path = {entry.path: entry for entry in loaded.base_tree.entries}
    assert by_path[b"a"].content.source == "start_walk"
    assert by_path[b"b"].content.source == "cat_file_batch"
    assert loaded.base_tree.sealed_count == 2
    assert loaded.manifest_path.name == "seal-manifest.json"
    for oid, expected in ((oa, a), (ob, b)):
        cas_path = tmp_path / "materialisation" / "cas" / oid[:2] / oid[2:]
        assert cas_path.read_bytes() == expected
        assert cas_path.stat().st_nlink == 1

    # The manifest alone is not trusted: every CAS filename is re-verified.
    cas_path = tmp_path / "materialisation" / "cas" / oa[:2] / oa[2:]
    cas_path.write_bytes(b"forged!!")
    with pytest.raises(SealIntegrityFailed, match="CAS"):
        seal.load_task_seal(tmp_path / "materialisation")


def test_one_matching_route_a_path_seals_a_shared_oid_without_route_b(tmp_path: Path) -> None:
    data = b"shared"
    oid = git_blob_oid(data)
    loaded = seal.create_task_seal(
        tmp_path / "materialisation",
        task_id="task",
        base_commit=BASE,
        ls_tree_output=_tree([(b"a", oid, data), (b"b", oid, data)]),
        route_a_by_path={b"a": b"transformed", b"b": data},
        route_b_batch_output=b"",
    )
    assert loaded.base_tree.sealed_count == 2
    assert {entry.content.source for entry in loaded.base_tree.entries} == {"start_walk"}


def test_wrong_route_b_bytes_never_publish_a_manifest(tmp_path: Path) -> None:
    data = b"right"
    oid = git_blob_oid(data)
    materialisation = tmp_path / "materialisation"
    with pytest.raises(BaseObjectVerificationFailed):
        seal.create_task_seal(
            materialisation,
            task_id="task",
            base_commit=BASE,
            ls_tree_output=_tree([(b"file", oid, data)]),
            route_a_by_path={},
            route_b_batch_output=_batch([(oid, b"wrong")]),
        )
    assert not (materialisation / "seal-manifest.json").exists()


def test_manifest_is_published_last_and_existing_seal_is_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"content"
    oid = git_blob_oid(data)
    events: list[str] = []
    real = seal._atomic_write

    def observed(path: Path, payload: bytes, mode: int = 0o600) -> None:
        events.append(path.name)
        real(path, payload, mode)

    monkeypatch.setattr(seal, "_atomic_write", observed)
    args = dict(
        task_id="task",
        base_commit=BASE,
        ls_tree_output=_tree([(b"file", oid, data)]),
        route_a_by_path={b"file": data},
        route_b_batch_output=b"",
    )
    materialisation = tmp_path / "materialisation"
    seal.create_task_seal(materialisation, **args)
    assert events[-1] == "seal-manifest.json"
    before = {p.relative_to(materialisation): p.read_bytes() for p in materialisation.rglob("*") if p.is_file()}

    with pytest.raises(SealIntegrityFailed, match="already exists"):
        seal.create_task_seal(materialisation, **args)
    after = {p.relative_to(materialisation): p.read_bytes() for p in materialisation.rglob("*") if p.is_file()}
    assert before == after


def test_load_or_create_never_reconstructs_after_worker(tmp_path: Path) -> None:
    materialisation = tmp_path / "materialisation"
    called = False

    def builder() -> seal.LoadedTaskSeal:
        nonlocal called
        called = True
        raise AssertionError("must not rebuild")

    with pytest.raises(SealAbsentAfterWorker):
        seal.load_or_create_task_seal(materialisation, worker_has_run=True, builder=builder)
    assert called is False


def test_identity_is_required_by_production_consumers_not_reconstructed(
    tmp_path: Path,
) -> None:
    data = b"content"
    oid = git_blob_oid(data)
    materialisation = tmp_path / "revision-6-seal"
    seal.create_task_seal(
        materialisation,
        task_id="task",
        base_commit=BASE,
        ls_tree_output=_tree([(b"file", oid, data)]),
        route_a_by_path={b"file": data},
        route_b_batch_output=b"",
    )

    with pytest.raises(RepositoryIdentityUnsealed, match="identity record") as raised:
        seal.load_task_seal(materialisation, require_identity=True)

    assert raised.value.details["relpath"] == "identity-record.json"
