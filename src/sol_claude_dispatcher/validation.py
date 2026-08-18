"""Independent dispatcher validation (brief §9, §17). — Wave 3.

The dispatcher re-runs the *trusted* validation commands from the task envelope
after the worker exits, and stores the outcome next to — never merged with —
the worker's own test claims.

Two prohibitions, both absolute:

* Commands are structured argv executed via ``asyncio.create_subprocess_exec``.
  Never ``shell=True`` (§9).
* Commands that appear inside a Claude result are **never** executed, and the
  worker result may never redefine which commands run (§9, §17). The only
  source of truth is ``envelope.validation.commands``.

Contract (authoritative, see ``docs/INTERFACES.md``)::

    async def run_validation_command(cmd: ValidationCommand, cwd: Path) -> ValidationResult
    async def run_validations(envelope: TaskEnvelope, cwd: Path, config: Config) -> list[ValidationResult]
"""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .models import TaskEnvelope, ValidationCommand, ValidationResult

__all__ = ["run_validation_command", "run_validations"]


async def run_validation_command(
    cmd: ValidationCommand, cwd: Path, *, env: dict[str, str] | None = None
) -> ValidationResult:
    """Execute one trusted argv command and capture its outcome (§9)."""
    raise NotImplementedError("Wave 3: implement per docs/INTERFACES.md §validation")


async def run_validations(
    envelope: TaskEnvelope, cwd: Path, config: Config
) -> list[ValidationResult]:
    """Run every envelope validation command when enabled by config (§17)."""
    raise NotImplementedError("Wave 3: implement per docs/INTERFACES.md §validation")
