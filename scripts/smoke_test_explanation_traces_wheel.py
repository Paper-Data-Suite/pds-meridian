"""Smoke-test #42 explanation traces from an isolated installed wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path
from typing import cast

PROGRAM = Path(__file__).with_name("smoke_program_explanation_traces.py")
TARGETS_FILE = "issue42_trace_targets.json"


def _environment() -> dict[str, str]:
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
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


def _run_capture(command: list[str], cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env=_environment(),
        capture_output=True,
        text=True,
    )
    return result.stdout


def _tree_state(root: Path) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        values.append((relative, digest))
    return tuple(sorted(values))


def _target_values(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Installed #42 smoke targets must be a JSON object.")
    values = cast(dict[object, object], payload)
    required = {
        "class_id",
        "grade_item_id",
        "school_year",
        "period_id",
        "standard_id",
        "student_id",
        "derivation_id",
        "signal_set_id",
    }
    if set(values) != required or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in values.items()
    ):
        raise RuntimeError("Installed #42 smoke targets are invalid.")
    return cast(dict[str, str], values)


def _assert_deterministic_json(command: list[str], cwd: Path) -> dict[str, object]:
    first = _run_capture(command, cwd)
    second = _run_capture(command, cwd)
    if first != second:
        raise RuntimeError("Installed #42 trace CLI output is not deterministic.")
    payload = json.loads(first)
    if not isinstance(payload, dict):
        raise RuntimeError("Installed #42 trace CLI did not emit a JSON object.")
    return cast(dict[str, object], payload)


def smoke_test(meridian_wheel: Path, core_wheel: Path) -> None:
    """Install exact Core + Meridian and exercise packaged #42 traces."""

    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-explanation-trace-smoke-"
    ) as raw_temp:
        root = Path(raw_temp)
        environment = root / "venv"
        outside = root / "outside"
        outside.mkdir()
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
        _run([str(python), str(PROGRAM.resolve())], outside)

        targets = _target_values(outside / TARGETS_FILE)
        workspace = outside / "workspace"
        before_cli = _tree_state(workspace)
        common = ["--workspace", str(workspace), "--format", "json"]

        grade = _assert_deterministic_json(
            [
                str(meridian),
                "trace",
                "grade-item-proficiency",
                targets["class_id"],
                targets["grade_item_id"],
                targets["student_id"],
                targets["standard_id"],
                *common,
                "--result-revision",
                "1",
            ],
            outside,
        )
        academic_period = _assert_deterministic_json(
            [
                str(meridian),
                "trace",
                "academic-period-proficiency",
                targets["class_id"],
                targets["school_year"],
                targets["period_id"],
                targets["student_id"],
                targets["standard_id"],
                *common,
                "--result-revision",
                "1",
            ],
            outside,
        )
        derivation = _assert_deterministic_json(
            [
                str(meridian),
                "trace",
                "planning-derivation",
                targets["class_id"],
                targets["derivation_id"],
                *common,
            ],
            outside,
        )
        exported = _assert_deterministic_json(
            [
                str(meridian),
                "trace",
                "planning-export",
                targets["class_id"],
                targets["signal_set_id"],
                *common,
            ],
            outside,
        )

        grade_target = cast(dict[str, object], grade["target"])
        if grade_target["result_revision"] != 1:
            raise RuntimeError("Installed Grade Item trace used the wrong revision.")
        if grade_target["selection_state"] != "historical":
            raise RuntimeError("Installed Grade Item trace lost historical state.")
        if cast(dict[str, object], academic_period["target"])[
            "selection_state"
        ] != "historical":
            raise RuntimeError("Installed Academic Period trace lost history.")
        if cast(dict[str, object], derivation["target"])["derivation_id"] != targets[
            "derivation_id"
        ]:
            raise RuntimeError("Installed planning trace used the wrong derivation.")
        if cast(dict[str, object], exported["target"])["signal_set_id"] != targets[
            "signal_set_id"
        ]:
            raise RuntimeError("Installed export trace used the wrong Core signal.")

        after_cli = _tree_state(workspace)
        if before_cli != after_cli:
            raise RuntimeError("Installed #42 CLI traces mutated the workspace.")


def main(argv: list[str] | None = None) -> int:
    """Parse wheel paths and run the isolated #42 installed-wheel smoke."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(args.meridian_wheel, args.core_wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
