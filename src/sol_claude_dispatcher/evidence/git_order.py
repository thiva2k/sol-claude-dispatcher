"""Gate 7's closed Git environment, declared order and establishment journal.

This module contains policy data and a small enforcement seam.  It does not
spawn Git itself.  Production ``git.py`` supplies the resolved executable and
runner; tests can therefore exercise the entire policy with a fake runner.

The important distinction is deliberate:

* the establishment interlock is the enforcement mechanism;
* the append-only journal is corroborating evidence.

A journal row can never grant authority to run Git.  Authority comes only from
the current :class:`~sol_claude_dispatcher.phase.ToolExecution`, while it is in
PREPARE, after that same execution durably wrote its establishment marker.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import string
import time
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, TypeVar

from ..errors import (
    ForbiddenGitInvocation,
    GitArgvPinDisplaced,
    GitBeforeEstablishment,
    InternalDispatcherError,
)
from ..models import utc_now
from ..phase import ExecutionPhase, ToolExecution, require_current_execution

__all__ = [
    "CwdRole",
    "DECLARED_GIT_ORDER",
    "DISPATCHER_GIT_ENV",
    "DISPATCHER_GIT_ENV_ITEMS",
    "DeclaredGitRow",
    "EMPTY_BY_DECLARATION",
    "EmptyByDeclaration",
    "ExecutedGitInvocation",
    "GIT_ENV_ALLOWLIST",
    "GitInvocationJournal",
    "GitJournalRecord",
    "GitPath",
    "PIN_NAMES",
    "PinBlock",
    "PreparedGitInvocation",
    "execute_declared_git",
    "prepare_git_invocation",
    "validate_row_args",
]


# ZI-85.  The allowlist was measured empty.  The child receives these six
# dispatcher-owned values and nothing inherited from the dispatcher process.
GIT_ENV_ALLOWLIST: tuple[str, ...] = ()
DISPATCHER_GIT_ENV_ITEMS: tuple[tuple[str, str], ...] = (
    ("GIT_NO_LAZY_FETCH", "1"),
    ("GIT_NO_REPLACE_OBJECTS", "1"),
    ("GIT_CONFIG_NOSYSTEM", "1"),
    ("GIT_CONFIG_GLOBAL", "/dev/null"),
    ("GIT_TERMINAL_PROMPT", "0"),
    ("GIT_OPTIONAL_LOCKS", "0"),
)
DISPATCHER_GIT_ENV: Mapping[str, str] = MappingProxyType(
    dict(DISPATCHER_GIT_ENV_ITEMS)
)

if GIT_ENV_ALLOWLIST or any(key.startswith("GIT_") for key in GIT_ENV_ALLOWLIST):
    # The first predicate is intentionally stronger than the second: Revision 10
    # measured no inherited variable necessary.  A future widening is an
    # architecture change, not a local convenience.
    raise InternalDispatcherError(
        "The dispatcher Git environment allowlist must remain empty."
    )


PIN_NAMES: tuple[str, ...] = ("PIN1", "PIN2", "PIN3", "PIN4")


@dataclass(frozen=True, slots=True)
class PinBlock:
    """The frozen, ordered, terminal argv pin prefix.

    ``empty_hooks_path`` is injected from the sealed dispatcher authority.  It
    must already be absolute; this class never resolves or guesses a path.
    """

    empty_hooks_path: str
    argv: tuple[str, ...] = field(init=False)
    names: tuple[str, ...] = field(default=PIN_NAMES, init=False)

    def __post_init__(self) -> None:
        path = self.empty_hooks_path
        if not isinstance(path, str) or not path or "\x00" in path:
            raise ValueError("The sealed empty-hooks path must be a non-empty path.")
        if not Path(path).is_absolute():
            raise ValueError("The sealed empty-hooks path must be absolute.")
        object.__setattr__(
            self,
            "argv",
            (
                "-c",
                f"core.hooksPath={path}",
                "-c",
                "core.commitGraph=false",
                "-c",
                "core.multiPackIndex=false",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.attributesFile=/dev/null",
                "-c",
                "core.quotePath=false",
                "--no-pager",
            ),
        )


class GitPath(str, Enum):
    DISPATCH = "dispatch"
    RESUME = "resume"
    REVIEW = "review"


class CwdRole(str, Enum):
    PRIMARY = "primary"
    TASK_WORKTREE = "task_worktree"


@dataclass(frozen=True, slots=True)
class EmptyByDeclaration:
    """Explicit declaration that a path has no authority-domain Git rows."""

    reason: str = "EMPTY_BY_DECLARATION"


EMPTY_BY_DECLARATION = EmptyByDeclaration()


@dataclass(frozen=True, slots=True)
class DeclaredGitRow:
    """One normative row, including any explicitly-declared argv variants."""

    row_id: str
    path: GitPath
    purpose: str
    argv_templates: tuple[tuple[str, ...], ...]
    cwd_role: CwdRole
    pins: tuple[str, ...] = PIN_NAMES

    @property
    def subcommands(self) -> tuple[str, ...]:
        return tuple(template[0] for template in self.argv_templates)

    def render(
        self, values: Mapping[str, str] | None = None, *, variant: int = 0
    ) -> tuple[str, ...]:
        supplied = dict(values or {})
        try:
            template = self.argv_templates[variant]
        except IndexError as exc:
            raise ForbiddenGitInvocation(
                "The requested Git argv variant is not declared.",
                details={"row": self.row_id, "variant": variant},
            ) from exc

        formatter = string.Formatter()
        required = {
            name
            for token in template
            for _, name, _, _ in formatter.parse(token)
            if name is not None
        }
        if set(supplied) != required:
            raise ForbiddenGitInvocation(
                "The Git row values do not exactly match its declaration.",
                details={
                    "row": self.row_id,
                    "required": sorted(required),
                    "supplied": sorted(supplied),
                },
            )
        for name, value in supplied.items():
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ForbiddenGitInvocation(
                    "A declared Git row value is empty or unrepresentable.",
                    details={"row": self.row_id, "field": name},
                )
        rendered = tuple(token.format_map(supplied) for token in template)
        validate_row_args(rendered[0], rendered[1:])
        return rendered


_DISPATCH_ROWS: tuple[DeclaredGitRow, ...] = (
    DeclaredGitRow(
        "G1",
        GitPath.DISPATCH,
        "verify the exact base commit",
        (("rev-parse", "--verify", "--end-of-options", "{base_commit}^{{commit}}"),),
        CwdRole.PRIMARY,
    ),
    DeclaredGitRow(
        "G2",
        GitPath.DISPATCH,
        "capture base-tree identity",
        (("ls-tree", "-r", "-z", "{base_commit}"),),
        CwdRole.PRIMARY,
    ),
    DeclaredGitRow(
        "G3",
        GitPath.DISPATCH,
        "list registered worktrees",
        (("worktree", "list", "--porcelain"),),
        CwdRole.PRIMARY,
    ),
    DeclaredGitRow(
        "G4",
        GitPath.DISPATCH,
        "create the detached task worktree",
        (
            (
                "worktree",
                "add",
                "--quiet",
                "--detach",
                "{worktree_path}",
                "{base_commit}",
            ),
        ),
        CwdRole.PRIMARY,
    ),
    DeclaredGitRow(
        "G8",
        GitPath.DISPATCH,
        "seal remaining base objects in one batch",
        (("cat-file", "--batch"),),
        CwdRole.PRIMARY,
    ),
    DeclaredGitRow(
        "G9",
        GitPath.DISPATCH,
        "verify promisor completeness",
        (("rev-list", "--objects", "--missing=print", "HEAD"),),
        CwdRole.PRIMARY,
    ),
)

_RESUME_ROWS: tuple[DeclaredGitRow, ...] = (
    DeclaredGitRow(
        "G1_PRIME",
        GitPath.RESUME,
        "confirm the sealed task worktree remains registered",
        (("worktree", "list", "--porcelain"),),
        CwdRole.PRIMARY,
    ),
)

DECLARED_GIT_ORDER: Mapping[
    GitPath, tuple[DeclaredGitRow, ...] | EmptyByDeclaration
] = MappingProxyType(
    {
        GitPath.DISPATCH: _DISPATCH_ROWS,
        GitPath.RESUME: _RESUME_ROWS,
        GitPath.REVIEW: EMPTY_BY_DECLARATION,
    }
)


_DISPLACED_EXACT = frozenset(
    {
        "-c",
        "--config-env",
        "-C",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--exec-path",
        "--no-pager",
    }
)
_DISPLACED_PREFIXES: tuple[str, ...] = (
    "-c",
    "-C",
    "--config-env=",
    "--git-dir=",
    "--work-tree=",
    "--namespace=",
    "--exec-path=",
)


def validate_row_args(subcommand: str, row_args: tuple[str, ...]) -> None:
    """Reject any caller token that could precede or displace the pin policy."""
    if not isinstance(subcommand, str) or not subcommand or subcommand.startswith("-"):
        raise GitArgvPinDisplaced(
            "A Git invocation must begin with a declared subcommand token."
        )
    for token in row_args:
        if not isinstance(token, str) or "\x00" in token:
            raise GitArgvPinDisplaced(
                "A caller-supplied Git argv token is unrepresentable."
            )
        if token in _DISPLACED_EXACT or any(
            token.startswith(prefix) for prefix in _DISPLACED_PREFIXES
        ):
            raise GitArgvPinDisplaced(
                "A caller-supplied Git option would displace the terminal pin prefix.",
                details={"option": token.split("=", 1)[0]},
            )


@dataclass(frozen=True, slots=True)
class GitJournalRecord:
    ts: str
    seq: int
    event: str
    path: str
    phase: str
    subcommand: str | None
    argv_sha256: str | None
    cwd_role: str | None
    permitted_by: str
    returncode: int | None
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class _Establishment:
    execution: ToolExecution
    journal_path: Path
    path: GitPath
    marker_seq: int


_ESTABLISHMENT: ContextVar[_Establishment | None] = ContextVar(
    "gate7_git_establishment", default=None
)


def _coerce_path(path: GitPath | str) -> GitPath:
    try:
        return path if isinstance(path, GitPath) else GitPath(path)
    except ValueError as exc:
        raise ForbiddenGitInvocation(
            "The requested Git authority path is not declared.",
            details={"path": str(path)},
        ) from exc


def _declared_rows(path: GitPath) -> tuple[DeclaredGitRow, ...]:
    declaration = DECLARED_GIT_ORDER[path]
    if declaration is EMPTY_BY_DECLARATION:
        raise ForbiddenGitInvocation(
            "This dispatcher path declares no authority-domain Git invocations.",
            details={"path": path.value, "declaration": "EMPTY_BY_DECLARATION"},
        )
    return declaration


def _row(path: GitPath, row_id: str) -> DeclaredGitRow:
    matches = [row for row in _declared_rows(path) if row.row_id == row_id]
    if len(matches) != 1:
        raise ForbiddenGitInvocation(
            "The requested Git row is absent or ambiguous in the declaration.",
            details={"path": path.value, "row": row_id, "matches": len(matches)},
        )
    return matches[0]


def _utc_now() -> str:
    return utc_now().isoformat()


def _argv_sha256(argv: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for token in argv:
        encoded = os.fsencode(token)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


class GitInvocationJournal:
    """Append-only JSONL with a file-locked, strictly increasing sequence."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _open(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise InternalDispatcherError(
                "The Git invocation journal could not be opened.",
                details={"path": str(self.path), "reason": type(exc).__name__},
            ) from exc
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise InternalDispatcherError(
                "The Git invocation journal is not a regular file.",
                details={"path": str(self.path)},
            )
        os.fchmod(fd, 0o600)
        return fd

    @staticmethod
    def _decode_lines(raw: bytes) -> list[GitJournalRecord]:
        records: list[GitJournalRecord] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            if not line:
                continue
            try:
                payload = json.loads(line)
                record = GitJournalRecord(**payload)
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
                raise InternalDispatcherError(
                    "The Git invocation journal is malformed.",
                    details={"line": number},
                ) from exc
            if record.seq != len(records) + 1:
                raise InternalDispatcherError(
                    "The Git invocation journal sequence is not monotone.",
                    details={"line": number, "seq": record.seq},
                )
            records.append(record)
        return records

    def records(self) -> tuple[GitJournalRecord, ...]:
        if not self.path.exists():
            return ()
        fd = self._open()
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            os.lseek(fd, 0, os.SEEK_SET)
            raw = b""
            while chunk := os.read(fd, 1024 * 1024):
                raw += chunk
            return tuple(self._decode_lines(raw))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _append(self, **values: Any) -> GitJournalRecord:
        fd = self._open()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.lseek(fd, 0, os.SEEK_SET)
            raw = b""
            while chunk := os.read(fd, 1024 * 1024):
                raw += chunk
            existing = self._decode_lines(raw)
            record = GitJournalRecord(
                ts=_utc_now(), seq=len(existing) + 1, **values
            )
            encoded = (
                json.dumps(asdict(record), sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("utf-8")
            os.write(fd, encoded)
            os.fsync(fd)
            return record
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def establish(self, path: GitPath | str) -> GitJournalRecord:
        declared_path = _coerce_path(path)
        if DECLARED_GIT_ORDER[declared_path] is EMPTY_BY_DECLARATION:
            raise ForbiddenGitInvocation(
                "An empty-by-declaration path cannot establish Git authority.",
                details={"path": declared_path.value},
            )
        execution = require_current_execution()
        if (
            execution.phase is not ExecutionPhase.PREPARE
            or execution.tool != declared_path.value
        ):
            raise GitBeforeEstablishment(
                "Git establishment requires the matching current tool in PREPARE.",
                details={
                    "tool": execution.tool,
                    "phase": execution.phase.name,
                    "path": declared_path.value,
                },
            )
        existing = _ESTABLISHMENT.get()
        if existing is not None and existing.execution is execution:
            raise InternalDispatcherError(
                "This tool execution already carries a Git establishment marker.",
                details={"tool": execution.tool},
            )
        marker = self._append(
            event="establishment",
            path=declared_path.value,
            phase=ExecutionPhase.PREPARE.name,
            subcommand=None,
            argv_sha256=None,
            cwd_role=None,
            permitted_by="PREPARE_ADMIN_GATE",
            returncode=None,
            duration_ms=None,
        )
        _ESTABLISHMENT.set(
            _Establishment(execution, self.path.resolve(), declared_path, marker.seq)
        )
        return marker

    def assert_row_may_follow(self, row: DeclaredGitRow) -> None:
        rows = _declared_rows(row.path)
        row_indexes = {declared.row_id: index for index, declared in enumerate(rows)}
        prior = [
            record
            for record in self.records()
            if record.event == "git" and record.path == row.path.value
        ]
        if prior:
            previous_id = prior[-1].permitted_by
            if previous_id not in row_indexes or row_indexes[row.row_id] <= row_indexes[previous_id]:
                raise ForbiddenGitInvocation(
                    "The Git invocation would regress or repeat the declared order.",
                    details={
                        "path": row.path.value,
                        "previous": previous_id,
                        "requested": row.row_id,
                    },
                )

    def record_git(
        self,
        prepared: "PreparedGitInvocation",
        *,
        returncode: int | None,
        duration_ms: int,
    ) -> GitJournalRecord:
        _assert_established(self, prepared.row.path)
        return self._append(
            event="git",
            path=prepared.row.path.value,
            phase=ExecutionPhase.PREPARE.name,
            subcommand=prepared.subcommand,
            argv_sha256=prepared.argv_sha256,
            cwd_role=prepared.cwd_role.value,
            permitted_by=prepared.row.row_id,
            returncode=returncode,
            duration_ms=duration_ms,
        )


def _assert_established(journal: GitInvocationJournal, path: GitPath) -> ToolExecution:
    execution = require_current_execution()
    marker = _ESTABLISHMENT.get()
    if (
        execution.phase is not ExecutionPhase.PREPARE
        or marker is None
        or marker.execution is not execution
        or marker.journal_path != journal.path.resolve()
        or marker.path is not path
    ):
        raise GitBeforeEstablishment(
            "No Git process may run before this PREPARE execution establishes raw authority.",
            details={
                "tool": execution.tool,
                "phase": execution.phase.name,
                "path": path.value,
            },
        )
    return execution


@dataclass(frozen=True, slots=True)
class PreparedGitInvocation:
    row: DeclaredGitRow
    argv: tuple[str, ...]
    env: Mapping[str, str]
    cwd_role: CwdRole
    argv_sha256: str

    @property
    def subcommand(self) -> str:
        return self.row.subcommands[
            next(
                index
                for index, template in enumerate(self.row.argv_templates)
                if template[0] in self.argv
            )
        ]


def prepare_git_invocation(
    *,
    journal: GitInvocationJournal,
    path: GitPath | str,
    row_id: str,
    git_executable: str,
    pin_block: PinBlock,
    cwd_role: CwdRole,
    values: Mapping[str, str] | None = None,
    variant: int = 0,
) -> PreparedGitInvocation:
    declared_path = _coerce_path(path)
    row = _row(declared_path, row_id)
    _assert_established(journal, declared_path)
    if cwd_role is not row.cwd_role:
        raise ForbiddenGitInvocation(
            "The Git invocation cwd role differs from its declaration.",
            details={
                "row": row.row_id,
                "declared": row.cwd_role.value,
                "requested": cwd_role.value,
            },
        )
    if not isinstance(git_executable, str) or "\x00" in git_executable:
        raise ForbiddenGitInvocation("The sealed Git executable is unrepresentable.")
    if not Path(git_executable).is_absolute():
        raise ForbiddenGitInvocation(
            "The sealed Git executable must be an absolute path.",
            details={"row": row.row_id},
        )
    rendered = row.render(values, variant=variant)
    journal.assert_row_may_follow(row)
    argv = (git_executable, *pin_block.argv, *rendered)
    return PreparedGitInvocation(
        row=row,
        argv=argv,
        env=DISPATCHER_GIT_ENV,
        cwd_role=cwd_role,
        argv_sha256=_argv_sha256(argv),
    )


T = TypeVar("T")
GitRunner = Callable[..., T]


@dataclass(frozen=True, slots=True)
class ExecutedGitInvocation:
    result: Any
    prepared: PreparedGitInvocation
    journal_record: GitJournalRecord


def execute_declared_git(
    *,
    journal: GitInvocationJournal,
    path: GitPath | str,
    row_id: str,
    git_executable: str,
    pin_block: PinBlock,
    cwd: Path,
    cwd_role: CwdRole,
    runner: GitRunner[T],
    values: Mapping[str, str] | None = None,
    variant: int = 0,
) -> ExecutedGitInvocation:
    """Execute one prepared row through an injected runner and always journal it."""
    prepared = prepare_git_invocation(
        journal=journal,
        path=path,
        row_id=row_id,
        git_executable=git_executable,
        pin_block=pin_block,
        cwd_role=cwd_role,
        values=values,
        variant=variant,
    )
    started = time.monotonic()
    try:
        result = runner(prepared.argv, cwd=Path(cwd), env=dict(prepared.env))
    except BaseException:
        duration_ms = int((time.monotonic() - started) * 1000)
        journal.record_git(prepared, returncode=None, duration_ms=duration_ms)
        raise
    returncode = getattr(result, "returncode", None)
    if not isinstance(returncode, int):
        journal.record_git(
            prepared,
            returncode=None,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        raise InternalDispatcherError(
            "The Git runner returned no integer return code.",
            details={"row": prepared.row.row_id},
        )
    record = journal.record_git(
        prepared,
        returncode=returncode,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return ExecutedGitInvocation(result, prepared, record)
