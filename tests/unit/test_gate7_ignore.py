from __future__ import annotations

from sol_claude_dispatcher.evidence.basetree import (
    build_base_tree_snapshot,
    git_blob_oid,
    parse_ls_tree_z,
)
from sol_claude_dispatcher.evidence.ignore import build_base_ignore_matcher, classify_paths


BASE = "a" * 40


def _snapshot(sources: dict[bytes, bytes]):
    records = []
    blobs: dict[str, bytes] = {}
    for path, data in sorted(sources.items()):
        oid = git_blob_oid(data)
        blobs[oid] = data
        records.append(b"100644 blob " + oid.encode() + b"\t" + path + b"\0")
    identities = parse_ls_tree_z(b"".join(records))
    return build_base_tree_snapshot(BASE, identities, blobs), blobs


def test_base_ignore_matching_is_raw_byte_last_match_wins_and_deeper_wins() -> None:
    snapshot, blobs = _snapshot(
        {
            b".gitignore": b"*.log\n/cache/\n!keep.log\nnonutf8-?\n",
            b"sub/.gitignore": b"!local.log\n[[:digit:]].tmp\n",
        }
    )
    matcher = build_base_ignore_matcher(snapshot, blobs)

    assert matcher.is_ignored(b"error.log") is True
    assert matcher.is_ignored(b"keep.log") is False
    assert matcher.is_ignored(b"sub/local.log") is False
    assert matcher.is_ignored(b"sub/other.log") is True
    assert matcher.is_ignored(b"cache/child.bin") is True
    assert matcher.is_ignored(b"nested/cache/child.bin") is False
    assert matcher.is_ignored(b"sub/7.tmp") is True
    assert matcher.is_ignored(b"nonutf8-\xff") is True


def test_info_exclude_is_lower_precedence_and_live_sources_are_never_read() -> None:
    snapshot, blobs = _snapshot({b".gitignore": b"!generated.bin\n"})
    matcher = build_base_ignore_matcher(
        snapshot,
        blobs,
        info_exclude=b"generated.bin\nadmin-only\n",
        info_exclude_oid="baseline:sha256:1234",
    )

    assert matcher.is_ignored(b"generated.bin") is False
    classification = matcher.classify(b"admin-only")
    assert classification.ignored is True
    assert classification.matched_rule is not None
    assert classification.matched_rule.source_oid == "baseline:sha256:1234"


def test_double_star_matches_raw_newlines_only_in_supported_positions() -> None:
    snapshot, blobs = _snapshot({b".gitignore": b"tree/**/last\n**/cache\n"})
    matcher = build_base_ignore_matcher(snapshot, blobs)

    assert matcher.is_ignored(b"tree/one\ntwo/last") is True
    assert matcher.is_ignored(b"deep/cache/file") is True


def test_unsupported_rules_fail_open_toward_reporting_with_exact_provenance() -> None:
    source = b"escaped\\ pattern\n[[:emoji:]]\nunterminated[\n[z-a]\nfoo**bar\n***\n"
    snapshot, blobs = _snapshot({b".gitignore": source})
    matcher = build_base_ignore_matcher(snapshot, blobs)

    assert matcher.is_ignored(b"escaped pattern") is False
    assert matcher.is_ignored(b"x") is False
    assert [(item.line_number, item.raw) for item in matcher.unsupported_ignore_rules] == [
        (1, b"escaped\\ pattern"),
        (2, b"[[:emoji:]]"),
        (3, b"unterminated["),
        (4, b"[z-a]"),
        (5, b"foo**bar"),
        (6, b"***"),
    ]
    assert all(item.source_oid == git_blob_oid(source) for item in matcher.unsupported_ignore_rules)


def test_missing_sealed_ignore_blob_is_unsupported_not_an_empty_rule_set() -> None:
    snapshot, _ = _snapshot({b".gitignore": b"secret\n"})
    matcher = build_base_ignore_matcher(snapshot, {})

    assert matcher.is_ignored(b"secret") is False
    assert len(matcher.unsupported_ignore_rules) == 1
    assert matcher.unsupported_ignore_rules[0].line_number == 0
    assert matcher.unsupported_ignore_rules[0].reason == "sealed source bytes are absent"


def test_ignore_classification_consumes_only_an_explicit_inventory() -> None:
    snapshot, blobs = _snapshot({b".gitignore": b"*.tmp\n"})
    matcher = build_base_ignore_matcher(snapshot, blobs)

    assert classify_paths(
        matcher,
        ((b"visible", False), (b"hidden.tmp", False), (b"dir.tmp", True)),
    ) == {b"visible": False, b"hidden.tmp": True, b"dir.tmp": True}

    try:
        classify_paths(matcher, ((b"same", False), (b"same", True)))
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("a duplicate inventory path was accepted")


def test_invalid_inventory_paths_are_refused_instead_of_normalized() -> None:
    snapshot, blobs = _snapshot({})
    matcher = build_base_ignore_matcher(snapshot, blobs)

    for path in (b"", b"/absolute", b"../escape", b"a//b", b"a/./b", b"nul\0x"):
        try:
            matcher.is_ignored(path)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid path was accepted: {path!r}")
