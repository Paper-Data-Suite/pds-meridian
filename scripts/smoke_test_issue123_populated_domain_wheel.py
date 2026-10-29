"""Execute #123 11G populated-domain acceptance using a prepared installed wheel.

This is an additive, explicitly invoked qualification. It does not modify the
frozen Issue #96 runner or the existing Issue #123 11D menu-only smoke.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from scripts.installed_qualification_harness import (
    InstalledWheelSet,
    PreparedInstalledEnvironment,
)
from scripts.installed_qualification_matrix import DependencyMatrixId, matrix_for

PROGRAM = Path(__file__).with_name("smoke_program_issue123_populated_domain.py")


def isolated_environment() -> dict[str, str]:
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


def run_prepared_smoke(python: Path, outside: Path, root: Path) -> None:
    if not outside.is_dir() or root.exists():
        raise RuntimeError(
            "11G requires a new synthetic workspace beside an outside directory."
        )
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
            "Installed 11G populated-domain acceptance failed: "
            + result.stdout[-2400:]
            + result.stderr[-2400:]
        )
    if (
        "Meridian #123 11G populated installed domain acceptance passed."
        not in result.stdout
    ):
        raise RuntimeError("Installed 11G program did not report qualification.")
    if tuple(outside.iterdir()):
        raise RuntimeError("11G created files outside its synthetic workspace.")
    print(result.stdout, end="", flush=True)


def smoke_test(wheels: InstalledWheelSet) -> None:
    with PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.ALL_ADAPTERS), wheels
    ) as prepared:
        working = prepared.fresh_working_directory("issue123-11g-populated")
        outside = working / "outside"
        outside.mkdir()
        run_prepared_smoke(prepared.python, outside, working / "synthetic-root")
        prepared.assert_package_set_immutable("issue123-11g-populated")


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
