"""Run issue #53's installed teacher Grade override lifecycle acceptance."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path

PROGRAM = Path(__file__).with_name("smoke_program_teacher_grade_override.py")
ACTIVE_RELOAD = Path(__file__).with_name(
    "smoke_program_teacher_grade_override_reload_active.py"
)
WITHDRAWN_RELOAD = Path(__file__).with_name(
    "smoke_program_teacher_grade_override_reload_withdrawn.py"
)


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


def run_prepared_smoke(python: Path, outside: Path) -> None:
    """Run teacher Grade override acceptance in a prepared ScoreForm environment."""
    _run([str(python), str(PROGRAM.resolve())], outside)
    _run([str(python), str(ACTIVE_RELOAD.resolve())], outside)
    _run([str(python), str(WITHDRAWN_RELOAD.resolve())], outside)


def smoke_test(
    meridian_wheel: Path,
    core_wheel: Path,
    scoreform_wheel: Path,
) -> None:
    """Install exact released dependencies plus the candidate Meridian wheel."""

    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-teacher-grade-override-smoke-"
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
        run_prepared_smoke(python, outside)


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
