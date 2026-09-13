"""Run issue #50's installed conventional-Grade acceptance with ScoreForm only."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path

PROGRAM = Path(__file__).with_name("smoke_program_conventional_grade.py")
RELOAD_PROGRAM = Path(__file__).with_name("smoke_program_conventional_grade_reload.py")


def _environment() -> dict[str, str]:
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    for variable in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "QUILLAN_WHEEL",
        "CONCORD_WHEEL",
    ):
        environment.pop(variable, None)
    return environment


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, env=_environment())


def smoke_test(
    meridian_wheel: Path,
    core_wheel: Path,
    scoreform_wheel: Path,
) -> None:
    """Install exactly Core, ScoreForm, candidate Meridian, then reload history."""

    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-conventional-grade-smoke-"
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
                str(core_wheel.resolve()),
                str(scoreform_wheel.resolve()),
                str(meridian_wheel.resolve()),
            ],
            outside,
        )
        _run([str(python), "-m", "pip", "check"], outside)
        _run([str(python), str(PROGRAM.resolve())], outside)
        _run([str(python), str(RELOAD_PROGRAM.resolve())], outside)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    parser.add_argument("scoreform_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(args.meridian_wheel, args.core_wheel, args.scoreform_wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
