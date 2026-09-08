"""Run issue #45's installed ScoreForm/Quillan composition without Concord."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path

PROGRAM = Path(__file__).with_name("smoke_program_proficiency_signal_export.py")
RELOAD_PROGRAM = Path(__file__).with_name(
    "smoke_program_proficiency_signal_export_reload.py"
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
        "CONCORD_WHEEL",
    ):
        environment.pop(variable, None)
    return environment


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env=_environment(),
    )


def smoke_test(
    meridian_wheel: Path,
    core_wheel: Path,
    scoreform_wheel: Path,
    quillan_wheel: Path,
) -> None:
    """Install the four PDS candidates plus their ordinary runtime dependencies."""

    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-proficiency-signal-export-smoke-"
    ) as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()

        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")

        # The four explicit PDS candidates are local wheel paths. Dependency
        # resolution remains enabled because the released ScoreForm and Quillan
        # wheels declare ordinary third-party runtime dependencies (for example,
        # OpenCV). The installed smoke program separately proves that Concord is
        # neither installed nor importable.
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                str(core_wheel.resolve()),
                str(scoreform_wheel.resolve()),
                str(quillan_wheel.resolve()),
                str(meridian_wheel.resolve()),
            ],
            outside,
        )
        _run([str(python), "-m", "pip", "check"], outside)
        _run([str(python), str(PROGRAM.resolve())], outside)
        _run([str(python), str(RELOAD_PROGRAM.resolve())], outside)


def main(argv: list[str] | None = None) -> int:
    """Parse wheel paths and run issue #45's isolated installed acceptance."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    parser.add_argument("scoreform_wheel", type=Path)
    parser.add_argument("quillan_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(
        args.meridian_wheel,
        args.core_wheel,
        args.scoreform_wheel,
        args.quillan_wheel,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
