"""Interpreter-level, test-only spawn observation for Gate 7 closure tests.

The audit hook cannot be removed once installed, so it remains dormant unless
``capture_spawns`` installs a context-local collector.  No environment mapping
or file content is retained.
"""

from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

EVENTS: tuple[str, ...] = (
    "subprocess.Popen",
    "os.posix_spawn",
    "os.posix_spawnp",
    "os.exec",
    "os.spawn",
    "os.fork",
    "os.forkpty",
)


@dataclass(frozen=True, slots=True)
class SpawnEvent:
    name: str
    executable: str | None
    argv: tuple[str, ...]


_ACTIVE: ContextVar[list[SpawnEvent] | None] = ContextVar(
    "gate7_test_spawn_journal", default=None
)
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode(errors="surrogateescape")
    if isinstance(value, os.PathLike):
        return os.fsdecode(value)
    return None


def _argv(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    converted = tuple(_string(item) for item in value)
    return tuple(item for item in converted if item is not None)


def _extract(name: str, args: tuple[object, ...]) -> SpawnEvent:
    executable: str | None = None
    argv: tuple[str, ...] = ()
    if name == "subprocess.Popen":
        if args:
            executable = _string(args[0])
        if len(args) > 1:
            argv = _argv(args[1])
    elif name in {"os.posix_spawn", "os.posix_spawnp", "os.exec"}:
        if args:
            executable = _string(args[0])
        if len(args) > 1:
            argv = _argv(args[1])
    elif name == "os.spawn":
        if len(args) > 1:
            executable = _string(args[1])
        if len(args) > 2:
            argv = _argv(args[2])
    return SpawnEvent(name=name, executable=executable, argv=argv)


def _hook(name: str, args: tuple[object, ...]) -> None:
    if name not in EVENTS:
        return
    active = _ACTIVE.get()
    if active is not None:
        active.append(_extract(name, args))


def install_spawn_journal() -> None:
    """Install the process-wide hook once; subsequent calls are idempotent."""
    global _INSTALLED
    with _INSTALL_LOCK:
        if not _INSTALLED:
            sys.addaudithook(_hook)
            _INSTALLED = True


@contextmanager
def capture_spawns() -> Iterator[list[SpawnEvent]]:
    """Collect interpreter spawn events in the current context only."""
    install_spawn_journal()
    if _ACTIVE.get() is not None:
        raise RuntimeError("spawn journals may not be nested")
    observed: list[SpawnEvent] = []
    token = _ACTIVE.set(observed)
    try:
        yield observed
    finally:
        _ACTIVE.reset(token)
