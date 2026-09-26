"""Run issue #55's installed ReportingSnapshot acceptance."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path

PROGRAM = Path(__file__).with_name("smoke_program_reporting_snapshot.py")
RELOAD_PROGRAM = Path(__file__).with_name(
    "smoke_program_reporting_snapshot_reload.py"
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
        "PDS_CORE_WHEEL",
        "SCOREFORM_WHEEL",
        "QUILLAN_WHEEL",
        "CONCORD_WHEEL",
    ):
        environment.pop(variable, None)
    return environment


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, env=_environment())


def run_prepared_smoke(python: Path, outside: Path) -> None:
    """Run ReportingSnapshot acceptance in a prepared environment."""
    _run([str(python), str(PROGRAM.resolve()), str(outside)], outside)
    _run([str(python), str(RELOAD_PROGRAM.resolve()), str(outside)], outside)


def smoke_test(
    meridian_wheel: Path,
    core_wheel: Path,
    scoreform_wheel: Path,
    quillan_wheel: Path,
    concord_wheel: Path,
) -> None:
    """Install exact released dependencies plus the candidate Meridian wheel."""

    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-reporting-snapshot-smoke-"
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
                str(quillan_wheel.resolve()),
                str(concord_wheel.resolve()),
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
    parser.add_argument("quillan_wheel", type=Path)
    parser.add_argument("concord_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(
        args.meridian_wheel,
        args.core_wheel,
        args.scoreform_wheel,
        args.quillan_wheel,
        args.concord_wheel,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
