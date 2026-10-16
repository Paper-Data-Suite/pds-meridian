"""One installed Concord Report 9 journey using the existing Concord matrix."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROGRAM = Path(__file__).with_name("smoke_program_concord_benchmark_issue117.py")


def run_prepared_smoke(python: Path, outside: Path, workspace: Path) -> None:
    """Run in one isolated process; package installation is matrix-owned."""
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        environment.pop(name, None)
    subprocess.run(
        [str(python), str(PROGRAM.resolve()), str(workspace)],
        cwd=outside,
        env=environment,
        check=True,
    )


__all__ = ("run_prepared_smoke",)
