"""Smoke-test #43 attention from an isolated installed Meridian wheel."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path

PROGRAM = Path(__file__).with_name("smoke_program_attention.py")
SEED_PROGRAM = Path(__file__).with_name(
    "smoke_program_grouping_signal_preview_review.py"
)
SOURCE_ROOT = Path(__file__).resolve().parents[1]


def _environment() -> dict[str, str]:
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PDS_MERIDIAN_SMOKE_SOURCE_ROOT": str(SOURCE_ROOT),
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
    """Install exact Core + Meridian and exercise installed #43 attention."""

    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-attention-smoke-"
    ) as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()

        if outside.resolve().is_relative_to(SOURCE_ROOT):
            raise RuntimeError(
                "Installed #43 smoke must execute outside the source checkout."
            )

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

        _run([str(python), str(SEED_PROGRAM.resolve())], outside)
        _run([str(python), str(PROGRAM.resolve())], outside)


def main(argv: list[str] | None = None) -> int:
    """Parse wheel paths and run the isolated #43 installed-wheel smoke."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(args.meridian_wheel, args.core_wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
