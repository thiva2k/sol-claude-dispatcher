from __future__ import annotations

import hashlib

import pytest

from sol_claude_dispatcher.errors import BaseObjectVerificationFailed, BaseTreeSnapshotFailed
from sol_claude_dispatcher.evidence.basetree import (
    build_base_tree_snapshot,
    git_blob_oid,
    parse_cat_file_batch,
    parse_ls_tree_z,
)
from sol_claude_dispatcher.evidence.reconcile import StartTreeEntry, reconcile_base_to_start


BASE = "a" * 40


def _record(mode: bytes, kind: bytes, oid: str, path: bytes) -> bytes:
    return mode + b" " + kind + b" " + oid.encode("ascii") + b"\t" + path + b"\0"


def test_ls_tree_parser_preserves_raw_paths_and_has_no_long_shape() -> None:
    one = git_blob_oid(b"one")
    two = git_blob_oid(b"two")
    raw = _record(b"100644", b"blob", one, b"new\nline\tname") + _record(
        b"120000", b"blob", two, b"nonutf8-\xff"
    )

    entries = parse_ls_tree_z(raw)

    assert tuple(entry.path for entry in entries) == (b"new\nline\tname", b"nonutf8-\xff")
    assert entries[0].kind == "blob"
    assert entries[1].kind == "symlink"


def test_recursive_git_tree_order_is_canonicalised_not_rejected() -> None:
    oid = git_blob_oid(b"x")
    # A recursive traversal can emit a/file before root-level a.txt even though
    # the flattened raw paths have the opposite lexicographic ordering.
    raw = _record(b"100644", b"blob", oid, b"a/file") + _record(
        b"100644", b"blob", oid, b"a.txt"
    )
    assert tuple(entry.path for entry in parse_ls_tree_z(raw)) == (b"a.txt", b"a/file")


@pytest.mark.parametrize(
    "raw",
    [
        b"100644 blob " + b"a" * 40 + b" 12\tfile\0",  # --long output
        b"100644 blob " + b"a" * 40 + b"\tfile",  # no NUL terminator
        b"100644 blob " + b"A" * 40 + b"\tfile\0",  # non-canonical oid
        b"040000 tree " + b"a" * 40 + b"\tdir\0",  # -r must not emit trees
        b"100644 blob " + b"a" * 40 + b"\t\0",  # empty path
    ],
)
def test_ls_tree_parser_refuses_every_malformed_or_long_record(raw: bytes) -> None:
    with pytest.raises(BaseTreeSnapshotFailed):
        parse_ls_tree_z(raw)


def test_cat_file_batch_is_length_delimited_and_self_verifying() -> None:
    first = b"with\nembedded\nnewlines"
    second = b""
    oid1 = git_blob_oid(first)
    oid2 = git_blob_oid(second)
    raw = (
        f"{oid1} blob {len(first)}\n".encode()
        + first
        + b"\n"
        + f"{oid2} blob 0\n".encode()
        + b"\n"
    )

    assert parse_cat_file_batch((oid1, oid2), raw) == {oid1: first, oid2: second}

    corrupt = raw.replace(first, first[:-1] + b"X", 1)
    with pytest.raises(BaseObjectVerificationFailed, match="object id"):
        parse_cat_file_batch((oid1, oid2), corrupt)


def test_complete_snapshot_cannot_be_built_with_one_blob_missing() -> None:
    data = b"payload"
    oid = git_blob_oid(data)
    identities = parse_ls_tree_z(_record(b"100644", b"blob", oid, b"file"))

    with pytest.raises(BaseTreeSnapshotFailed, match="complete"):
        build_base_tree_snapshot(BASE, identities, {})

    snapshot = build_base_tree_snapshot(BASE, identities, {oid: data})
    assert snapshot.complete is True
    assert snapshot.sealed_count == 1
    assert snapshot.total_content_bytes == len(data)
    assert snapshot.entries[0].content is not None
    assert snapshot.entries[0].content.oid == oid
    assert hashlib.sha1(b"blob 7\0payload").hexdigest() == oid


def test_base_start_reconciliation_is_total_and_keeps_transformed_old_side() -> None:
    base_data = b"line1\nline2\n"
    transformed = b"line1\r\nline2\r\n"
    oid = git_blob_oid(base_data)
    transformed_oid = git_blob_oid(transformed)
    identities = parse_ls_tree_z(_record(b"100644", b"blob", oid, b"file"))
    base = build_base_tree_snapshot(BASE, identities, {oid: base_data})

    result = reconcile_base_to_start(
        base,
        (
            StartTreeEntry(
                path=b"file",
                kind="regular",
                content_hash=transformed_oid,
                size=len(transformed),
            ),
            StartTreeEntry(path=b"extra", kind="regular", content_hash="d" * 40, size=1),
        ),
    )

    assert result.verdict == "transformed"
    assert result.diverged[0].captured_ref == transformed_oid
    assert result.captured_bytes == len(transformed)
    assert result.extra_on_fs == (b"extra",)
