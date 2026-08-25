"""Smoke-test Grade Item modules from an isolated installed Meridian wheel."""

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
    """Install only Core and Meridian, then exercise the Grade Item surface."""
    with tempfile.TemporaryDirectory(
        prefix="pds-meridian-grade-item-smoke-"
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
                "--no-index",
                "--no-deps",
                str(core_wheel.resolve()),
                str(meridian_wheel.resolve()),
            ],
            outside,
        )
        _run([str(python), "-m", "pip", "check"], outside)
        code = (
            "from datetime import UTC, datetime; "
            "from decimal import Decimal; "
            "import pathlib, sys; "
            "from meridian.grade_items import "
            "GRADE_ITEM_RECORD_TYPE, GRADE_ITEM_SCHEMA_VERSION, "
            "GradeItemRevision, GradeItemWeightingMetadata, "
            "grade_item_revision_from_json_bytes, "
            "grade_item_revision_to_json_bytes; "
            "import meridian.grade_item_storage as storage; "
            "item=GradeItemRevision("
            "schema_version=GRADE_ITEM_SCHEMA_VERSION, "
            "record_type=GRADE_ITEM_RECORD_TYPE, class_id='synthetic_class', "
            "grade_item_id='essay_1', grade_item_revision=1, "
            "supersedes_revision=None, title='Synthetic Essay', "
            "purpose='standards_proficiency', status='active', "
            "weighting=GradeItemWeightingMetadata("
            "relative_weight=Decimal('1.5')), "
            "created_at=datetime(2026,8,25,tzinfo=UTC), "
            "revised_at=datetime(2026,8,25,tzinfo=UTC)); "
            "data=grade_item_revision_to_json_bytes(item); "
            "assert grade_item_revision_from_json_bytes(data)==item; "
            "assert storage.GRADE_ITEM_CURRENT_RECORD_TYPE == "
            "'meridian_grade_item_current'; "
            "import meridian, pds_core; root=pathlib.Path(sys.prefix).resolve(); "
            "assert pathlib.Path(meridian.__file__).resolve().is_relative_to(root); "
            "assert pathlib.Path(pds_core.__file__).resolve().is_relative_to(root); "
            "assert not ({'scoreform','quillan','concord','portia','vitrine'} "
            "& set(sys.modules))"
        )
        _run([str(python), "-c", code], outside)
        if list(outside.iterdir()):
            raise RuntimeError("Grade Item smoke test left working-directory residue.")


def main(argv: list[str] | None = None) -> int:
    """Parse wheel paths and run the installed Grade Item smoke test."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    args = parser.parse_args(argv)
    smoke_test(args.meridian_wheel, args.core_wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
