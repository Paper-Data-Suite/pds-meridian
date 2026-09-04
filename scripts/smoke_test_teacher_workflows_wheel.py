"""Smoke-test issue #41 workflows from an isolated installed Meridian wheel."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path

BASELINE_PROGRAM = Path(__file__).with_name(
    "smoke_program_grouping_signal_export.py"
)
WORKFLOW_PROGRAM = Path(__file__).with_name(
    "smoke_program_teacher_workflows.py"
)


def _environment() -> dict[str, str]:
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
        env=_environment(),
    )


def smoke_test(meridian_wheel: Path, core_wheel: Path) -> None:
    """Install exact Core + Meridian and exercise packaged #41 workflows."""

    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-teacher-workflow-smoke-"
    ) as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")

        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(core_wheel.resolve()),
                str(meridian_wheel.resolve()),
            ],
            outside,
        )
        _run([str(python), "-m", "pip", "check"], outside)

        # Seed a complete exact #27-#40 synthetic state through the existing
        #40 installed acceptance harness, then exercise #41 over those durable
        #canonical records from the same outside directory.
        _run([str(python), str(BASELINE_PROGRAM.resolve())], outside)
        _run([str(python), str(WORKFLOW_PROGRAM.resolve())], outside)


def main(argv: list[str] | None = None) -> int:
    """Parse wheel paths and run the isolated issue #41 workflow smoke."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(args.meridian_wheel, args.core_wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
