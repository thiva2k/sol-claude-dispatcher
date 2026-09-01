"""Dispatcher-native unified patch, stat and diff-check production.

No function in this module spawns Git or consults repository state.  Tests may
feed the produced bytes to ``git apply`` in disposable repositories solely to
validate the format.  Inputs are bounded before the deterministic Myers line
differ runs, preventing adversarial files from turning evidence generation
into unbounded work.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Sequence

from ..errors import DiffBudgetExceeded
from .content import AuthoritativeContent, ContentClass, ContentSide, git_blob_oid

__all__ = [
    "DiffBudgetExceeded",
    "DiffCheckFinding",
    "PathRepresentation",
    "RenderedChange",
    "CanonicalEvidence",
    "c_quote_path",
    "render_change",
    "build_canonical_evidence",
]


@dataclass(frozen=True)
class DiffCheckFinding:
    path: bytes
    line_number: int
    kind: Literal["trailing_whitespace", "space_before_tab", "conflict_marker"]
    line_excerpt: str


@dataclass(frozen=True)
class PathRepresentation:
    path: bytes
    content_class: ContentClass
    sections: tuple[bytes, ...]
    omission_reason: str | None
    inventory_complete: bool
    additions: int
    deletions: int


@dataclass(frozen=True)
class RenderedChange:
    path: bytes
    sections: tuple[bytes, ...]
    omission_reason: str | None
    inventory_complete: bool
    content_class: ContentClass
    additions: int
    deletions: int
    added_lines: tuple[tuple[int, bytes], ...]

    @property
    def patch_bytes(self) -> bytes:
        return b"".join(self.sections)


@dataclass(frozen=True)
class CanonicalEvidence:
    """One complete accounting over the authoritative worker delta."""

    changes: tuple[AuthoritativeContent, ...]
    inventory: object | None
    base_commit: str
    patch_path: Path
    patch_data: bytes
    patch_bytes: int
    patch_sha256: str
    per_path: tuple[PathRepresentation, ...]
    diff_stat: str
    check_findings: tuple[DiffCheckFinding, ...]

    @property
    def patch_file_complete(self) -> bool:
        expected = (
            len(getattr(self.inventory.identity, "changes"))
            if self.inventory is not None
            else len(self.changes)
        )
        return (
            len(self.per_path) == expected
            and all(row.sections for row in self.per_path)
            and all(row.omission_reason is None for row in self.per_path)
        )

    @property
    def review_input_complete(self) -> bool:
        return self.patch_file_complete

    @property
    def diff_check_passed(self) -> bool:
        return not self.check_findings

    @property
    def diff_check_output(self) -> str:
        rows = []
        for finding in self.check_findings:
            name = _public_path(finding.path)
            rows.append(
                f"{name}:{finding.line_number}: {finding.kind}: {finding.line_excerpt}"
            )
        return "\n".join(rows) + ("\n" if rows else "")

    def to_diff_evidence(self):
        """Project into the pre-Gate-7 compatibility shape without Git."""
        # Local import avoids making the native evidence modules depend on the
        # legacy producer during concurrent Wave-0 construction.
        from ..git import DiffEvidence

        status = "".join(_status_line(change) for change in self.changes)
        return DiffEvidence(
            base_commit=self.base_commit,
            changed_paths=[_public_path(change.path) for change in self.changes],
            diff_text=self.patch_data.decode("utf-8", errors="replace"),
            diff_stat=self.diff_stat,
            porcelain_status=status,
            diff_check_passed=self.diff_check_passed,
            diff_check_output=self.diff_check_output,
            truncated=False,
            diff_total_bytes=self.patch_bytes,
        )


def _public_path(path: bytes) -> str:
    return path.decode("utf-8", errors="backslashreplace")


def _status_line(change: AuthoritativeContent) -> str:
    path = _public_path(change.path)
    if change.change == "added":
        return f"?? {path}\n"
    if change.change == "removed":
        return f" D {path}\n"
    return f" M {path}\n"


def c_quote_path(path: bytes) -> bytes:
    """Render a whole prefixed path using Git-compatible C quoting."""
    raw = bytes(path)
    needs_quotes = any(
        byte < 0x20 or byte >= 0x7F or byte in (ord('"'), ord("\\")) for byte in raw
    )
    if not needs_quotes:
        return raw
    escaped = bytearray(b'"')
    named = {
        0x09: b"\\t",
        0x0A: b"\\n",
        0x0D: b"\\r",
        0x22: b'\\"',
        0x5C: b"\\\\",
    }
    for byte in raw:
        replacement = named.get(byte)
        if replacement is not None:
            escaped.extend(replacement)
        elif 0x20 <= byte < 0x7F:
            escaped.append(byte)
        else:
            escaped.extend(f"\\{byte:03o}".encode("ascii"))
    escaped.extend(b'"')
    return bytes(escaped)


def _split_lines(data: bytes) -> tuple[bytes, ...]:
    if not data:
        return ()
    return tuple(data.splitlines(keepends=True))


Edit = tuple[Literal["equal", "delete", "insert"], bytes]


def _myers_edits(
    old: Sequence[bytes], new: Sequence[bytes], *, maximum_work: int
) -> tuple[Edit, ...]:
    """Return a deterministic shortest edit script with an explicit work cap."""
    n, m = len(old), len(new)
    if n == 0:
        return tuple(("insert", line) for line in new)
    if m == 0:
        return tuple(("delete", line) for line in old)
    work = 0
    frontier: dict[int, int] = {1: 0}
    trace: list[dict[int, int]] = []
    end_distance: int | None = None
    for distance in range(n + m + 1):
        trace.append(frontier.copy())
        for diagonal in range(-distance, distance + 1, 2):
            work += 1
            if work > maximum_work:
                raise DiffBudgetExceeded(
                    "Native diff exceeded its deterministic work budget.",
                    details={"maximum_work": maximum_work, "old_lines": n, "new_lines": m},
                )
            if diagonal == -distance or (
                diagonal != distance
                and frontier.get(diagonal - 1, -1) < frontier.get(diagonal + 1, -1)
            ):
                x = frontier.get(diagonal + 1, 0)
            else:
                x = frontier.get(diagonal - 1, 0) + 1
            y = x - diagonal
            while x < n and y < m and old[x] == new[y]:
                x += 1
                y += 1
                work += 1
                if work > maximum_work:
                    raise DiffBudgetExceeded(
                        "Native diff exceeded its deterministic work budget.",
                        details={"maximum_work": maximum_work, "old_lines": n, "new_lines": m},
                    )
            frontier[diagonal] = x
            if x >= n and y >= m:
                end_distance = distance
                break
        if end_distance is not None:
            break
    if end_distance is None:  # pragma: no cover - mathematical invariant
        raise RuntimeError("Myers differ did not reach the end")

    x, y = n, m
    reverse: list[Edit] = []
    for distance in range(end_distance, -1, -1):
        prior = trace[distance]
        diagonal = x - y
        if diagonal == -distance or (
            diagonal != distance
            and prior.get(diagonal - 1, -1) < prior.get(diagonal + 1, -1)
        ):
            previous_diagonal = diagonal + 1
        else:
            previous_diagonal = diagonal - 1
        previous_x = prior.get(previous_diagonal, 0)
        previous_y = previous_x - previous_diagonal
        while x > previous_x and y > previous_y:
            reverse.append(("equal", old[x - 1]))
            x -= 1
            y -= 1
        if distance == 0:
            break
        if x == previous_x:
            reverse.append(("insert", new[y - 1]))
            y -= 1
        else:
            reverse.append(("delete", old[x - 1]))
            x -= 1
    reverse.reverse()
    return tuple(reverse)


def _range(start: int, count: int) -> bytes:
    return str(start).encode("ascii") if count == 1 else f"{start},{count}".encode("ascii")


def _emit_prefixed_line(prefix: bytes, line: bytes) -> bytes:
    if line.endswith(b"\n"):
        return prefix + line
    return prefix + line + b"\n\\ No newline at end of file\n"


def _body(
    old: bytes,
    new: bytes,
    *,
    maximum_work: int,
) -> tuple[bytes, int, int, tuple[tuple[int, bytes], ...]]:
    old_lines, new_lines = _split_lines(old), _split_lines(new)
    edits = _myers_edits(old_lines, new_lines, maximum_work=maximum_work)
    if all(operation == "equal" for operation, _ in edits):
        return b"", 0, 0, ()
    old_count, new_count = len(old_lines), len(new_lines)
    old_start = 1 if old_count else 0
    new_start = 1 if new_count else 0
    out = bytearray(
        b"@@ -" + _range(old_start, old_count) + b" +" + _range(new_start, new_count) + b" @@\n"
    )
    additions = deletions = 0
    new_line_number = 0
    added_lines: list[tuple[int, bytes]] = []
    for operation, line in edits:
        if operation == "equal":
            new_line_number += 1
            out.extend(_emit_prefixed_line(b" ", line))
        elif operation == "delete":
            deletions += 1
            out.extend(_emit_prefixed_line(b"-", line))
        else:
            additions += 1
            new_line_number += 1
            added_lines.append((new_line_number, line.rstrip(b"\n")))
            out.extend(_emit_prefixed_line(b"+", line))
    return bytes(out), additions, deletions, tuple(added_lines)


def _mode(side: ContentSide) -> int:
    if side.mode is not None:
        return side.mode
    return 0o120000 if side.kind == "symlink" else 0o100644


def _one_section(
    path: bytes,
    old: ContentSide,
    new: ContentSide,
    *,
    maximum_work: int,
) -> tuple[bytes, int, int, tuple[tuple[int, bytes], ...]]:
    a_path = c_quote_path(b"a/" + path)
    b_path = c_quote_path(b"b/" + path)
    old_absent = old.kind == "absent"
    new_absent = new.kind == "absent"
    old_data = old.data or b""
    new_data = new.data or b""
    out = bytearray(b"diff --git " + a_path + b" " + b_path + b"\n")
    if old_absent:
        out.extend(f"new file mode {_mode(new):06o}\n".encode("ascii"))
    elif new_absent:
        out.extend(f"deleted file mode {_mode(old):06o}\n".encode("ascii"))
    elif _mode(old) != _mode(new):
        out.extend(f"old mode {_mode(old):06o}\nnew mode {_mode(new):06o}\n".encode("ascii"))

    # Empty add/delete is represented solely by its file-mode line. This is
    # the one valid zero-hunk shape accepted by git apply.
    if not old_data and not new_data:
        return bytes(out), 0, 0, ()

    old_oid = old.oid or ("0" * 40)
    new_oid = new.oid or ("0" * 40)
    mode_suffix = f" {_mode(new):06o}" if not old_absent and not new_absent else ""
    out.extend(f"index {old_oid}..{new_oid}{mode_suffix}\n".encode("ascii"))
    out.extend(b"--- " + (b"/dev/null" if old_absent else a_path) + b"\n")
    out.extend(b"+++ " + (b"/dev/null" if new_absent else b_path) + b"\n")
    body, additions, deletions, added_lines = _body(
        old_data, new_data, maximum_work=maximum_work
    )
    out.extend(body)
    return bytes(out), additions, deletions, added_lines


def _omission(change: AuthoritativeContent) -> tuple[str | None, ContentClass, bool]:
    sides = (change.old, change.new)
    relevant = [side for side in sides if side.kind != "absent"]
    inventory_complete = all(side.inventory_complete for side in relevant)
    classes = {side.content_class for side in relevant}
    if ContentClass.CHANGED_DURING_MEASUREMENT in classes:
        return "changed_during_measurement", ContentClass.CHANGED_DURING_MEASUREMENT, False
    if ContentClass.UNREADABLE in classes:
        return "unreadable", ContentClass.UNREADABLE, False
    if ContentClass.OVERSIZED in classes:
        return "oversized", ContentClass.OVERSIZED, False
    if ContentClass.UNREPRESENTABLE_KIND in classes:
        return "unsupported_special_file", ContentClass.UNREPRESENTABLE_KIND, inventory_complete
    if ContentClass.UNTEXTUAL in classes:
        return "binary_no_approved_representation", ContentClass.UNTEXTUAL, inventory_complete
    return None, ContentClass.TEXT_CANDIDATE, inventory_complete


def render_change(
    change: AuthoritativeContent,
    *,
    maximum_input_bytes: int = 8_000_000,
    maximum_work: int = 2_000_000,
) -> RenderedChange:
    """Render one authoritative change, or account for why it is omitted."""
    measured = sum(side.size or 0 for side in (change.old, change.new))
    if measured > maximum_input_bytes:
        raise DiffBudgetExceeded(
            "Native diff input exceeded its byte budget.",
            details={
                "path": _public_path(change.path),
                "measured_input_bytes": measured,
                "maximum_input_bytes": maximum_input_bytes,
            },
        )
    omission, classification, complete = _omission(change)
    if omission is not None:
        return RenderedChange(change.path, (), omission, complete, classification, 0, 0, ())

    if change.change == "unchanged":
        # The authoritative inventory should not contain unchanged paths. Keep
        # the accounting honest if a caller violates that precondition.
        return RenderedChange(
            change.path, (), "unchanged_not_in_delta", complete, classification, 0, 0, ()
        )

    if change.old.kind != "absent" and change.new.kind != "absent" and change.old.kind != change.new.kind:
        absent = ContentSide(
            kind="absent",
            data=None,
            mode=None,
            size=None,
            sha256_digest=None,
            oid=None,
            content_class=ContentClass.ABSENT,
            inventory_complete=True,
            read_error=None,
        )
        deleted = _one_section(
            change.path, change.old, absent, maximum_work=maximum_work
        )
        added = _one_section(
            change.path, absent, change.new, maximum_work=maximum_work
        )
        return RenderedChange(
            change.path,
            (deleted[0], added[0]),
            None,
            complete,
            classification,
            deleted[1] + added[1],
            deleted[2] + added[2],
            deleted[3] + added[3],
        )

    section, additions, deletions, added_lines = _one_section(
        change.path, change.old, change.new, maximum_work=maximum_work
    )
    return RenderedChange(
        change.path,
        (section,),
        None,
        complete,
        classification,
        additions,
        deletions,
        added_lines,
    )


def _scan_added(path: bytes, rows: Iterable[tuple[int, bytes]]) -> tuple[DiffCheckFinding, ...]:
    findings: list[DiffCheckFinding] = []
    for line_number, line in rows:
        excerpt = line.decode("utf-8", errors="replace")[:160]
        if line.endswith((b" ", b"\t")):
            findings.append(DiffCheckFinding(path, line_number, "trailing_whitespace", excerpt))
        if b" \t" in line:
            findings.append(DiffCheckFinding(path, line_number, "space_before_tab", excerpt))
        if line.startswith((b"<<<<<<< ", b"=======", b">>>>>>> ")):
            findings.append(DiffCheckFinding(path, line_number, "conflict_marker", excerpt))
    return tuple(findings)


def _render_stat(rows: Sequence[PathRepresentation]) -> str:
    if not rows:
        return ""
    lines: list[str] = []
    total_add = total_delete = 0
    for row in rows:
        total_add += row.additions
        total_delete += row.deletions
        graph = "+" * min(row.additions, 40) + "-" * min(row.deletions, 40)
        lines.append(f" {_public_path(row.path)} | {row.additions + row.deletions} {graph}".rstrip())
    files = len(rows)
    lines.append(
        f" {files} file{'s' if files != 1 else ''} changed, "
        f"{total_add} insertion{'s' if total_add != 1 else ''}(+), "
        f"{total_delete} deletion{'s' if total_delete != 1 else ''}(-)"
    )
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_canonical_evidence(
    changes: Iterable[AuthoritativeContent] | object,
    *,
    base_commit: str,
    patch_path: Path,
    maximum_input_bytes_per_path: int = 8_000_000,
    maximum_work_per_path: int = 2_000_000,
) -> CanonicalEvidence:
    """Render and persist one canonical worker patch from authoritative bytes."""
    # A ClassifiedInventory from the concurrent inventory/content lanes is
    # accepted without importing its concrete class. This preserves the stage
    # boundary while keeping construction useful during parallel integration.
    inventory = changes if hasattr(changes, "classes") and hasattr(changes, "identity") else None
    source = (
        (row.content for row in getattr(changes, "classes"))
        if inventory is not None
        else changes
    )
    ordered = tuple(sorted(source, key=lambda item: item.path))  # type: ignore[arg-type, union-attr]
    if len({change.path for change in ordered}) != len(ordered):
        raise ValueError("canonical evidence requires exactly one row per path")
    rendered = tuple(
        render_change(
            change,
            maximum_input_bytes=maximum_input_bytes_per_path,
            maximum_work=maximum_work_per_path,
        )
        for change in ordered
    )
    patch_data = b"".join(row.patch_bytes for row in rendered)
    _atomic_write(Path(patch_path), patch_data)
    per_path = tuple(
        PathRepresentation(
            row.path,
            row.content_class,
            row.sections,
            row.omission_reason,
            row.inventory_complete,
            row.additions,
            row.deletions,
        )
        for row in rendered
    )
    findings = tuple(
        finding
        for row in rendered
        for finding in _scan_added(row.path, row.added_lines)
    )
    return CanonicalEvidence(
        changes=ordered,
        inventory=inventory,
        base_commit=base_commit,
        patch_path=Path(patch_path),
        patch_data=patch_data,
        patch_bytes=len(patch_data),
        patch_sha256=hashlib.sha256(patch_data).hexdigest(),
        per_path=per_path,
        diff_stat=_render_stat(per_path),
        check_findings=findings,
    )
