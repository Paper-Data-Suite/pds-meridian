"""Run #123 Slice 11K joined teacher journey in an isolated five-wheel venv."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from scripts.installed_qualification_harness import (
    InstalledWheelSet,
    PreparedInstalledEnvironment,
)
from scripts.installed_qualification_matrix import DependencyMatrixId, matrix_for
from scripts.smoke_test_issue123_populated_domain_wheel import isolated_environment

PROGRAM = Path(__file__).with_name("smoke_program_issue123_joined_journey.py")
SUCCESS = "Meridian #123 11K joined installed teacher journey passed."


def run_prepared_smoke(python: Path, outside: Path, root: Path) -> None:
    if not outside.is_dir() or root.exists():
        raise RuntimeError("11K requires a new synthetic root outside source checkout.")
    result = subprocess.run(
        [str(python), str(PROGRAM.resolve()), str(root)],
        cwd=outside,
        env=isolated_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode or "Traceback" in result.stdout + result.stderr:
        raise RuntimeError(
            "Installed 11K joined journey failed: "
            + result.stdout[-3500:]
            + result.stderr[-3500:]
        )
    if SUCCESS not in result.stdout:
        raise RuntimeError("11K did not prove the installed joined journey.")
    if tuple(outside.iterdir()):
        raise RuntimeError("11K created files outside its synthetic root.")
    print(result.stdout, end="", flush=True)


def smoke_test(wheels: InstalledWheelSet) -> None:
    with PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.ALL_ADAPTERS), wheels
    ) as prepared:
        working = prepared.fresh_working_directory("issue123-11k-joined")
        outside = working / "outside"
        outside.mkdir()
        run_prepared_smoke(prepared.python, outside, working / "synthetic-root")
        prepared.assert_package_set_immutable("issue123-11k-joined")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    parser.add_argument("scoreform_wheel", type=Path)
    parser.add_argument("quillan_wheel", type=Path)
    parser.add_argument("concord_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(
        InstalledWheelSet(
            meridian=args.meridian_wheel,
            core=args.core_wheel,
            scoreform=args.scoreform_wheel,
            quillan=args.quillan_wheel,
            concord=args.concord_wheel,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
