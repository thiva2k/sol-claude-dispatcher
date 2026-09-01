"""Base-authority ignore matching used only to classify inventory paths.

The matcher never reads a live ignore source.  Callers provide blobs from the
sealed base tree and the trusted administrative baseline.  Unsupported rules
are discarded, which deliberately biases the result toward reporting a path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from .basetree import BaseTreeSnapshot


_POSIX_CLASSES: dict[bytes, bytes] = {
    b"alnum": b"A-Za-z0-9",
    b"alpha": b"A-Za-z",
    b"blank": b" \\t",
    b"cntrl": b"\\x00-\\x1f\\x7f",
    b"digit": b"0-9",
    b"graph": b"!-~",
    b"lower": b"a-z",
    b"print": b" -~",
    b"punct": b"\\x21-\\x2f\\x3a-\\x40\\x5b-\\x60\\x7b-\\x7e",
    b"space": b" \\t\\r\\n\\v\\f",
    b"upper": b"A-Z",
    b"xdigit": b"A-Fa-f0-9",
}


@dataclass(frozen=True, slots=True)
class UnsupportedIgnoreRule:
    """A base-authority rule that was not used for classification."""

    source_oid: str
    source_path: bytes
    line_number: int
    raw: bytes
    reason: str


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    source_oid: str
    source_path: bytes
    source_directory: bytes
    line_number: int
    raw: bytes
    negated: bool
    anchored: bool
    directory_only: bool
    contains_slash: bool
    expression: re.Pattern[bytes]


@dataclass(frozen=True, slots=True)
class IgnoreClassification:
    ignored: bool
    matched_rule: IgnoreRule | None


@dataclass(frozen=True, slots=True)
class BaseIgnoreMatcher:
    """Immutable last-match-wins matcher over sealed ignore sources."""

    rules: tuple[IgnoreRule, ...]
    unsupported_ignore_rules: tuple[UnsupportedIgnoreRule, ...]

    def classify(self, path: bytes, *, is_directory: bool = False) -> IgnoreClassification:
        _validate_relative_path(path)
        ignored = False
        matched: IgnoreRule | None = None
        for rule in self.rules:
            relative = _under_source(path, rule.source_directory)
            if relative is None or not _rule_matches(rule, relative, is_directory=is_directory):
                continue
            ignored = not rule.negated
            matched = rule
        return IgnoreClassification(ignored=ignored, matched_rule=matched)

    def is_ignored(self, path: bytes, *, is_directory: bool = False) -> bool:
        return self.classify(path, is_directory=is_directory).ignored


def build_base_ignore_matcher(
    snapshot: BaseTreeSnapshot,
    blob_bytes_by_oid: Mapping[str, bytes],
    *,
    info_exclude: bytes | None = None,
    info_exclude_oid: str | None = None,
) -> BaseIgnoreMatcher:
    """Build a matcher without consulting the worktree or process environment.

    ``blob_bytes_by_oid`` must contain the verified bytes for every committed
    ``.gitignore`` entry.  A missing blob is recorded as unsupported rather
    than guessed.  ``info_exclude`` must be the copy held by the trusted admin
    baseline; the live ``$GIT_COMMON_DIR/info/exclude`` is never opened here.
    """

    sources: list[tuple[int, bytes, bytes, str, bytes | None]] = []
    for entry in snapshot.entries:
        if entry.kind != "blob" or not _is_gitignore_path(entry.path):
            continue
        source_directory = entry.path.rpartition(b"/")[0]
        sources.append(
            (
                _depth(source_directory),
                entry.path,
                source_directory,
                entry.oid,
                blob_bytes_by_oid.get(entry.oid),
            )
        )
    # info/exclude has Git's lowest repository-local precedence.  Give it a
    # synthetic depth before root .gitignore while preserving deterministic
    # raw-byte ordering among committed sources.
    if info_exclude is not None:
        sources.append((-1, b"$GIT_COMMON_DIR/info/exclude", b"", info_exclude_oid or "", info_exclude))

    rules: list[IgnoreRule] = []
    unsupported: list[UnsupportedIgnoreRule] = []
    for _, source_path, source_directory, source_oid, content in sorted(
        sources, key=lambda item: (item[0], item[1])
    ):
        if content is None:
            unsupported.append(
                UnsupportedIgnoreRule(
                    source_oid=source_oid,
                    source_path=source_path,
                    line_number=0,
                    raw=b"",
                    reason="sealed source bytes are absent",
                )
            )
            continue
        parsed, rejected = _parse_source(
            source_oid=source_oid,
            source_path=source_path,
            source_directory=source_directory,
            content=content,
        )
        rules.extend(parsed)
        unsupported.extend(rejected)
    return BaseIgnoreMatcher(tuple(rules), tuple(unsupported))


def _parse_source(
    *, source_oid: str, source_path: bytes, source_directory: bytes, content: bytes
) -> tuple[list[IgnoreRule], list[UnsupportedIgnoreRule]]:
    rules: list[IgnoreRule] = []
    unsupported: list[UnsupportedIgnoreRule] = []
    for line_number, original in enumerate(content.split(b"\n"), 1):
        raw = original[:-1] if original.endswith(b"\r") else original
        if not raw or raw.startswith(b"#"):
            continue
        try:
            rule = _parse_rule(
                source_oid=source_oid,
                source_path=source_path,
                source_directory=source_directory,
                line_number=line_number,
                raw=raw,
            )
        except ValueError as exc:
            unsupported.append(
                UnsupportedIgnoreRule(
                    source_oid=source_oid,
                    source_path=source_path,
                    line_number=line_number,
                    raw=raw,
                    reason=str(exc),
                )
            )
        else:
            rules.append(rule)
    return rules, unsupported


def _parse_rule(
    *,
    source_oid: str,
    source_path: bytes,
    source_directory: bytes,
    line_number: int,
    raw: bytes,
) -> IgnoreRule:
    # Git's escaping and trailing-space rules are deliberately not approximated.
    # Discarding them makes affected paths visible rather than hidden.
    if b"\\" in raw:
        raise ValueError("backslash escaping is outside the supported subset")
    if raw.endswith(b" "):
        raise ValueError("trailing-space escaping is outside the supported subset")
    negated = raw.startswith(b"!")
    pattern = raw[1:] if negated else raw
    if not pattern:
        raise ValueError("empty negation pattern")
    anchored = pattern.startswith(b"/")
    if anchored:
        pattern = pattern[1:]
    directory_only = pattern.endswith(b"/")
    if directory_only:
        pattern = pattern[:-1]
    if not pattern or b"\0" in pattern or b"//" in pattern:
        raise ValueError("empty, NUL, or repeated-separator pattern")
    if any(component in (b".", b"..") for component in pattern.split(b"/")):
        raise ValueError("dot traversal component")
    try:
        expression = re.compile(rb"\A" + _translate_glob(pattern) + rb"\Z")
    except re.error as exc:
        raise ValueError("unsupported or malformed character class") from exc
    return IgnoreRule(
        source_oid=source_oid,
        source_path=source_path,
        source_directory=source_directory,
        line_number=line_number,
        raw=raw,
        negated=negated,
        anchored=anchored,
        directory_only=directory_only,
        contains_slash=b"/" in pattern,
        expression=expression,
    )


def _translate_glob(pattern: bytes) -> bytes:
    out = bytearray()
    cursor = 0
    while cursor < len(pattern):
        byte = pattern[cursor]
        if byte == ord("*"):
            run_end = cursor + 1
            while run_end < len(pattern) and pattern[run_end] == ord("*"):
                run_end += 1
            run_length = run_end - cursor
            if run_length > 2:
                raise ValueError("more than two consecutive asterisks")
            if run_length == 2:
                before_slash = cursor == 0 or pattern[cursor - 1] == ord("/")
                after_slash = run_end == len(pattern) or pattern[run_end] == ord("/")
                if not (before_slash and after_slash):
                    raise ValueError("double-star is outside a supported path position")
                if run_end < len(pattern):
                    out.extend(b"(?:[\\x00-\\xff]*/)?")
                    cursor = run_end
                else:
                    out.extend(b"[\\x00-\\xff]*")
                    cursor = run_end - 1
            else:
                out.extend(b"[^/]*")
        elif byte == ord("?"):
            out.extend(b"[^/]")
        elif byte == ord("["):
            rendered, cursor = _translate_class(pattern, cursor)
            out.extend(rendered)
        else:
            out.extend(re.escape(bytes((byte,))))
        cursor += 1
    return bytes(out)


def _translate_class(pattern: bytes, start: int) -> tuple[bytes, int]:
    end = pattern.find(b"]", start + 1)
    if pattern[start + 1 : start + 3] == b"[:":
        posix_end = pattern.find(b":]]", start + 3)
        if posix_end < 0:
            raise ValueError("unterminated POSIX character class")
        name = pattern[start + 3 : posix_end]
        translated = _POSIX_CLASSES.get(name)
        if translated is None:
            raise ValueError("unsupported POSIX character class")
        return b"[" + translated + b"]", posix_end + 2
    if end < 0:
        raise ValueError("unterminated character class")
    body = pattern[start + 1 : end]
    if not body or b"/" in body or b"[" in body:
        raise ValueError("unsupported character class")
    if body.startswith(b"!"):
        body = b"^" + body[1:]
    elif body.startswith(b"^"):
        body = b"\\^" + body[1:]
    return b"[" + body + b"]", end


def _rule_matches(rule: IgnoreRule, relative: bytes, *, is_directory: bool) -> bool:
    components = relative.split(b"/")
    last_directory = len(components) if is_directory else len(components) - 1
    if rule.contains_slash or rule.anchored:
        candidates = [b"/".join(components[:index]) for index in range(1, len(components) + 1)]
        if rule.directory_only:
            candidates = candidates[:last_directory]
        return any(rule.expression.fullmatch(candidate) is not None for candidate in candidates)

    candidates = components[:last_directory] if rule.directory_only else components
    return any(rule.expression.fullmatch(component) is not None for component in candidates)


def _under_source(path: bytes, source_directory: bytes) -> bytes | None:
    if not source_directory:
        return path
    prefix = source_directory + b"/"
    return path[len(prefix) :] if path.startswith(prefix) else None


def _is_gitignore_path(path: bytes) -> bool:
    return path == b".gitignore" or path.endswith(b"/.gitignore")


def _depth(path: bytes) -> int:
    return 0 if not path else path.count(b"/") + 1


def _validate_relative_path(path: bytes) -> None:
    if not isinstance(path, bytes) or not path or path.startswith(b"/") or b"\0" in path:
        raise ValueError("ignore classification requires a non-empty relative byte path")
    if any(component in (b"", b".", b"..") for component in path.split(b"/")):
        raise ValueError("ignore classification path contains an invalid component")


def classify_paths(
    matcher: BaseIgnoreMatcher,
    paths: Iterable[tuple[bytes, bool]],
) -> dict[bytes, bool]:
    """Classify an explicit inventory path set; never discover paths itself."""

    declared = tuple(paths)
    if len({path for path, _ in declared}) != len(declared):
        raise ValueError("explicit ignore-classification inventory contains a duplicate path")
    return {
        path: matcher.is_ignored(path, is_directory=is_dir)
        for path, is_dir in declared
    }
