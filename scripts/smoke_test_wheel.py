"""Install built wheels in isolation and smoke-test outside the checkout."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _assert_empty(path: Path) -> None:
    residue = sorted(item.name for item in path.iterdir())
    if residue:
        raise RuntimeError(f"Smoke-test working directory contains residue: {residue}")


def smoke_test(meridian_wheel: Path, core_wheel: Path) -> None:
    """Install exact local wheels without indexes and exercise import and CLI."""
    with tempfile.TemporaryDirectory(prefix="pds-meridian-smoke-") as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()
        _assert_empty(outside)
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        meridian = scripts / ("meridian.exe" if os.name == "nt" else "meridian")

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
        _run(
            [
                str(python),
                "-c",
                (
                    "import importlib.metadata as m, pathlib, sys; "
                    "before=set(sys.modules); "
                    "import meridian, meridian.evidence, pds_core; "
                    "from meridian.evidence import EvidenceInventory; "
                    "assert EvidenceInventory(()).items == (); "
                    "assert meridian.__version__ == m.version('pds-meridian'); "
                    "assert m.version('pds-core') == '0.6.0'; "
                    "assert pathlib.Path(meridian.__file__).resolve().is_relative_to("
                    "pathlib.Path(sys.prefix).resolve()); "
                    "assert pathlib.Path(pds_core.__file__).resolve().is_relative_to("
                    "pathlib.Path(sys.prefix).resolve()); "
                    "assert not ({'scoreform','quillan','concord','portia','vitrine'} "
                    "& set(sys.modules))"
                ),
            ],
            outside,
        )
        for command in (
            [str(meridian)],
            [str(meridian), "--help"],
            [str(meridian), "--version"],
            [str(python), "-m", "meridian"],
            [str(python), "-m", "meridian", "--help"],
            [str(python), "-m", "meridian", "--version"],
        ):
            _run(command, outside)
        _assert_empty(outside)


def main(argv: list[str] | None = None) -> int:
    """Run an isolated smoke test for local Meridian and Core wheels."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(args.meridian_wheel, args.core_wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
