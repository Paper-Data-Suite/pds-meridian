"""Run the principal local checks mirrored by continuous integration."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
) -> None:
    print("+", subprocess.list2cmdline(command), flush=True)
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env=env or {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def _clean_source_copy(destination: Path) -> None:
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "venv",
            "build",
            "dist",
            "*.egg-info",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".coverage",
            "htmlcov",
        ),
    )


def _require_clean_repository() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
        raise RuntimeError("Repository validation found working-tree residue.")


def validate(
    core_wheel: Path,
    scoreform_wheel: Path,
    quillan_wheel: Path,
    concord_wheel: Path,
    *,
    allow_dirty: bool,
) -> None:
    """Run tests, static checks, builds, package checks, and smoke validation."""
    wheel = core_wheel.resolve()
    scoreform = scoreform_wheel.resolve()
    quillan = quillan_wheel.resolve()
    concord = concord_wheel.resolve()
    python = sys.executable
    _run([python, "scripts/verify_core_wheel.py", str(wheel), "--installed"])
    _run(
        [
            python,
            "scripts/verify_scoreform_wheel.py",
            str(scoreform),
            "--installed",
        ]
    )
    _run(
        [
            python,
            "scripts/verify_quillan_wheel.py",
            str(quillan),
            "--installed",
        ]
    )
    _run(
        [
            python,
            "scripts/verify_concord_wheel.py",
            str(concord),
            "--installed",
        ]
    )
    _run(
        [
            python,
            "scripts/verify_dependency_direction.py",
            str(wheel),
            str(scoreform),
            str(quillan),
            str(concord),
        ]
    )
    _run([python, "-m", "pip", "check"])

    with tempfile.TemporaryDirectory(prefix="pds-meridian-validation-") as raw_temp:
        temp = Path(raw_temp)
        env = {
            **os.environ,
            "TMP": str(temp),
            "TEMP": str(temp),
            "TMPDIR": str(temp),
            "PDS_CORE_WHEEL": str(wheel),
            "SCOREFORM_WHEEL": str(scoreform),
            "QUILLAN_WHEEL": str(quillan),
            "CONCORD_WHEEL": str(concord),
            "PYTHONDONTWRITEBYTECODE": "1",
            "RUFF_CACHE_DIR": str(temp / "ruff-cache"),
            "MYPY_CACHE_DIR": str(temp / "mypy-cache"),
        }
        commands = (
            [
                python,
                "-m",
                "pytest",
                "--basetemp",
                str(temp / "pytest"),
                "-o",
                f"cache_dir={temp / 'pytest-cache'}",
            ],
            [python, "-m", "ruff", "check", "."],
            [python, "-m", "mypy", "--cache-dir", str(temp / "mypy-cache")],
            [python, "scripts/check_documentation.py"],
        )
        for command in commands:
            _run(command, env=env)

        source = temp / "source"
        dist = temp / "dist"
        _clean_source_copy(source)
        _run([python, "-m", "build", "--outdir", str(dist)], cwd=source, env=env)
        artifacts = sorted(dist.iterdir())
        if not artifacts:
            raise RuntimeError("Package build produced no distribution artifacts.")
        _run([python, "-m", "twine", "check", *map(str, artifacts)], env=env)
        wheels = list(dist.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("Expected exactly one built Meridian wheel.")
        sdists = list(dist.glob("*.tar.gz"))
        if len(sdists) != 1:
            raise RuntimeError(
                "Expected exactly one built Meridian source distribution."
            )
        _run([python, "scripts/check_package.py", str(wheels[0])], env=env)
        _run([python, "scripts/check_sdist.py", str(sdists[0])], env=env)
        _run(
            [
                python,
                "scripts/smoke_test_wheel.py",
                str(wheels[0]),
                str(wheel),
                str(scoreform),
                str(quillan),
                str(concord),
            ],
            env=env,
        )
        _run(
            [
                python,
                "scripts/smoke_test_grade_items_wheel.py",
                str(wheels[0]),
                str(wheel),
            ],
            env=env,
        )
        _run(
            [
                python,
                "scripts/smoke_test_academic_period_proficiency_wheel.py",
                str(wheels[0]),
                str(wheel),
            ],
            env=env,
        )

    _run(["git", "diff", "--check"])
    if not allow_dirty:
        _require_clean_repository()


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and validate the repository."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-wheel", required=True, type=Path)
    parser.add_argument("--scoreform-wheel", required=True, type=Path)
    parser.add_argument("--quillan-wheel", required=True, type=Path)
    parser.add_argument("--concord-wheel", required=True, type=Path)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    validate(
        args.core_wheel,
        args.scoreform_wheel,
        args.quillan_wheel,
        args.concord_wheel,
        allow_dirty=args.allow_dirty,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
