"""Run Issue #57's installed teacher-main-menu acceptance."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path


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


def _run(
    command: list[str],
    *,
    cwd: Path,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        env=_environment(),
        input=stdin,
        text=True,
        capture_output=True,
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _assert_menu_exit(
    command: list[str],
    *,
    cwd: Path,
    stdin: str,
    required_text: tuple[str, ...],
) -> str:
    result = _run(command, cwd=cwd, stdin=stdin)
    _require(
        result.returncode == 0,
        f"Installed menu command failed ({result.returncode}): {result.stderr}",
    )
    output = result.stdout
    for token in required_text:
        _require(token in output, f"Installed menu output is missing {token!r}.")
    _require(
        "Traceback" not in output + result.stderr,
        "Installed menu emitted traceback.",
    )
    return output


def _tree(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
        )
    )


def run_prepared_smoke(
    python: Path,
    meridian: Path,
    outside: Path,
) -> None:
    """Run teacher-menu acceptance in a prepared environment."""
    origin = _run(
        [
            str(python),
            "-c",
            (
                "from pathlib import Path; import meridian, pds_core; "
                "import meridian.menu, meridian.menu_planning_signal; "
                "root=Path(__import__('sys').prefix).resolve(); "
                "mods=(meridian,pds_core,meridian.menu,"
                "meridian.menu_planning_signal); "
                "assert all("
                "Path(m.__file__).resolve().is_relative_to(root) "
                "for m in mods)"
            ),
        ],
        cwd=outside,
    )
    _require(origin.returncode == 0, origin.stdout + origin.stderr)

    before = _tree(outside)
    menu_text = (
        "Review New Evidence",
        "Manage Grade Items",
        "Review Proficiency",
        "Preview Grades",
        "Overrides",
        "Snapshots",
        "Export",
        "Explain",
    )
    _assert_menu_exit(
        [str(meridian)],
        cwd=outside,
        stdin="q\n",
        required_text=menu_text,
    )
    _assert_menu_exit(
        [str(meridian), "menu"],
        cwd=outside,
        stdin="q\n",
        required_text=menu_text,
    )
    _assert_menu_exit(
        [str(python), "-m", "meridian"],
        cwd=outside,
        stdin="q\n",
        required_text=menu_text,
    )
    _assert_menu_exit(
        [str(python), "-m", "meridian", "menu"],
        cwd=outside,
        stdin="q\n",
        required_text=menu_text,
    )
    after = _tree(outside)
    _require(
        after == before,
        "Launching/quitting the installed menu created workspace state.",
    )

    navigation = _assert_menu_exit(
        [str(meridian)],
        cwd=outside,
        stdin="3\n10\nb\nm\nq\n",
        required_text=("Review Proficiency", "Create Planning Signal", "Meridian"),
    )
    _require(
        navigation.count("Review Proficiency") >= 2,
        "B did not return to Review Proficiency.",
    )
    _require(
        navigation.count("1. Review New Evidence") >= 2,
        "M did not return to the main menu.",
    )
    _require(
        _tree(outside) == before,
        "Installed navigation created workspace state.",
    )

    for command in (
        [str(meridian), "--help"],
        [str(meridian), "--version"],
        [str(meridian), "reporting", "--help"],
    ):
        result = _run(command, cwd=outside)
        _require(result.returncode == 0, result.stdout + result.stderr)
        _require(
            "Choice:" not in result.stdout,
            "Direct CLI command became interactive.",
        )
        _require(
            "Press Enter to continue" not in result.stdout,
            "Direct CLI command paused.",
        )

    _require(
        _tree(outside) == before,
        "Direct CLI help/version created workspace state.",
    )
    print("Issue #57 installed teacher-menu acceptance passed.")


def smoke_test(
    meridian_wheel: Path,
    core_wheel: Path,
    scoreform_wheel: Path,
    quillan_wheel: Path,
    concord_wheel: Path,
) -> None:
    """Install exact released dependencies plus candidate Meridian and exercise UI."""
    with tempfile.TemporaryDirectory(prefix="pds-meridian-menu-smoke-") as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        meridian = scripts / ("meridian.exe" if os.name == "nt" else "meridian")

        install = _run(
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
            cwd=outside,
        )
        _require(install.returncode == 0, install.stderr)
        check = _run([str(python), "-m", "pip", "check"], cwd=outside)
        _require(check.returncode == 0, check.stdout + check.stderr)

        run_prepared_smoke(python, meridian, outside)


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
