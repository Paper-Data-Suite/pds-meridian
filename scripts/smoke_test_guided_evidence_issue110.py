"""Prepared-matrix wrapper for Issue #110 guided evidence acceptance."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal, TypeAlias

Producer: TypeAlias = Literal["scoreform", "quillan"]
PROGRAM = Path(__file__).with_name("smoke_program_guided_evidence_issue110.py")


def _isolated_environment() -> dict[str, str]:
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    for variable in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        environment.pop(variable, None)
    return environment


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env=_isolated_environment(),
    )


def run_prepared_smoke(
    python: Path,
    outside: Path,
    workspace: Path,
    producer: Producer,
) -> None:
    """Run one installed producer-specific guided evidence journey."""
    _run(
        [
            str(python),
            str(PROGRAM.resolve()),
            producer,
            str(workspace),
        ],
        outside,
    )


__all__ = ("Producer", "run_prepared_smoke")
