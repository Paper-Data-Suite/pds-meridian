"""Installed-wheel, source-isolated teacher navigation smoke for Meridian #123.

This smoke is run by the existing all-adapters prepared-wheel matrix. It makes
no academic writes, uses no source checkout imports, and needs no workspace.
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


def _environment() -> dict[str, str]:
    result = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PDS_CORE_WHEEL",
        "SCOREFORM_WHEEL",
        "QUILLAN_WHEEL",
        "CONCORD_WHEEL",
    ):
        result.pop(key, None)
    return result


def _run(
    command: list[str], *, cwd: Path, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=_environment(),
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def _tree(root: Path) -> tuple[str, ...]:
    return tuple(sorted(p.relative_to(root).as_posix() for p in root.rglob("*")))


def _menu_cases() -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Eight teacher domains, nested Planning Signal, and guided Reports."""
    return (
        (
            "grade-items",
            "2\nb\nq\n",
            ("Manage Grade Items", "Review Grade Items by name", "Advanced:"),
        ),
        (
            "proficiency",
            "3\nb\nq\n",
            (
                "Review Proficiency",
                "Review current Grade Item proficiency by name",
                "Advanced:",
            ),
        ),
        (
            "grades",
            "4\nb\nq\n",
            ("Preview Grades", "Review a current Grade by student", "Advanced:"),
        ),
        (
            "overrides",
            "5\nb\nq\n",
            ("Overrides", "Review current override by student", "Advanced:"),
        ),
        (
            "snapshots",
            "6\nb\nq\n",
            ("Snapshots", "Browse frozen reporting checkpoints by name", "Advanced:"),
        ),
        (
            "export",
            "7\nb\nq\n",
            ("Export", "Browse Export Profiles by name", "Advanced:"),
        ),
        (
            "explain",
            "8\nb\nq\n",
            ("Explain", "Explain a current Grade by name", "Advanced:"),
        ),
        (
            "reports",
            "9\nb\nq\n",
            ("Reports", "What would you like to find out?", "Guided choices"),
        ),
        (
            "nested-planning",
            "3\n10\nb\nb\nq\n",
            (
                "Review Proficiency",
                "Create Planning Signal",
                "Review Planning Signal readiness by policy name",
                "Export accepted Planning Signal to Core by name",
                "Advanced:",
            ),
        ),
    )


def _require_pass(
    name: str,
    result: subprocess.CompletedProcess[str],
    required: tuple[str, ...],
) -> None:
    if result.returncode:
        raise RuntimeError(
            f"Installed teacher navigation {name} exited {result.returncode}."
        )
    if "Traceback" in result.stdout + result.stderr:
        raise RuntimeError(f"Installed teacher navigation {name} raised traceback.")
    for text in required:
        if text not in result.stdout:
            raise RuntimeError(f"Installed teacher navigation {name} missing {text!r}.")
    for technical in (
        "Class ID: ",
        "Grade Item ID: ",
        "Preview sha256: ",
        "Projection cache key: ",
    ):
        if technical in result.stdout:
            raise RuntimeError(
                f"Installed teacher navigation {name} requested raw technical input."
            )


def run_prepared_smoke(python: Path, meridian: Path, outside: Path) -> None:
    """Prove the actual installed wheel exposes named/Advanced routes, safely."""
    if not outside.is_dir():
        raise RuntimeError("Installed smoke needs an existing outside directory.")
    origin = _run(
        [
            str(python),
            "-c",
            (
                "from pathlib import Path; import sys, meridian, pds_core; "
                "import meridian.menu, meridian.menu_planning_signal; "
                "import meridian.menu_teacher_named_planning_export; "
                "root=Path(sys.prefix).resolve(); "
                "mods=(meridian,pds_core,meridian.menu,"
                "meridian.menu_planning_signal,"
                "meridian.menu_teacher_named_planning_export); "
                "assert all(Path(m.__file__).resolve().is_relative_to(root) "
                "for m in mods)"
            ),
        ],
        cwd=outside,
    )
    _require_pass("installed imports", origin, ())
    before = _tree(outside)
    for name, answers, required in _menu_cases():
        run = _run([str(meridian), "menu"], cwd=outside, stdin=answers)
        _require_pass(name, run, required)
        if "1. Review New Evidence" not in run.stdout:
            raise RuntimeError(f"Installed {name} did not return to main menu.")
        if _tree(outside) != before:
            raise RuntimeError(f"Installed {name} created workspace state.")
    main = _run([str(meridian), "menu"], cwd=outside, stdin="8\nm\nq\n")
    _require_pass("main navigation", main, ("Explain", "1. Review New Evidence"))
    if main.stdout.count("1. Review New Evidence") < 2:
        raise RuntimeError("M failed to return to installed main menu.")
    quit_screen = _run([str(meridian), "menu"], cwd=outside, stdin="2\nq\n")
    _require_pass("nested quit", quit_screen, ("Manage Grade Items",))
    if _tree(outside) != before:
        raise RuntimeError("Installed navigation changed the outside directory.")
    print("Meridian #123 installed teacher-navigation smoke passed.", flush=True)


def smoke_test(wheels: InstalledWheelSet) -> None:
    """Prepare exactly the existing all-adapters matrix and run its smoke."""
    with PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.ALL_ADAPTERS), wheels
    ) as prepared:
        root = prepared.fresh_working_directory("issue123-navigation")
        outside = root / "outside"
        outside.mkdir()
        run_prepared_smoke(prepared.python, prepared.meridian, outside)
        prepared.assert_package_set_immutable("issue123-navigation")


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


__all__ = ("run_prepared_smoke", "smoke_test", "main")


if __name__ == "__main__":
    raise SystemExit(main())
