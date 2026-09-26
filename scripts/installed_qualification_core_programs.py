"""Run program-backed Core-only installed smokes in one prepared matrix."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.installed_qualification_harness import (
    InstalledWheelSet,
    PreparedInstalledEnvironment,
)
from scripts.installed_qualification_matrix import DependencyMatrixId, matrix_for

SCRIPT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = SCRIPT_ROOT.parent

GENERATION_PROGRAM = SCRIPT_ROOT / "smoke_program_grouping_signal_generation.py"
PREVIEW_REVIEW_PROGRAM = (
    SCRIPT_ROOT / "smoke_program_grouping_signal_preview_review.py"
)
EXPORT_PROGRAM = SCRIPT_ROOT / "smoke_program_grouping_signal_export.py"
TEACHER_WORKFLOWS_PROGRAM = SCRIPT_ROOT / "smoke_program_teacher_workflows.py"
ATTENTION_PROGRAM = SCRIPT_ROOT / "smoke_program_attention.py"


def run_core_program_smokes(prepared: PreparedInstalledEnvironment) -> None:
    """Run the first migrated Core-only smoke batch in one prepared venv."""
    if prepared.matrix.matrix_id is not DependencyMatrixId.CORE:
        raise ValueError(
            "Program-backed Core smoke batch requires the core dependency matrix."
        )

    prepared.run_smoke(
        "grouping-signal-generation",
        [str(prepared.python), str(GENERATION_PROGRAM)],
    )
    prepared.run_smoke(
        "grouping-signal-preview-review",
        [str(prepared.python), str(PREVIEW_REVIEW_PROGRAM)],
    )
    prepared.run_smoke(
        "grouping-signal-export",
        [str(prepared.python), str(EXPORT_PROGRAM)],
    )

    teacher_workspace = prepared.fresh_working_directory("teacher-workflows")
    prepared.run_smoke(
        "teacher-workflows-seed",
        [str(prepared.python), str(EXPORT_PROGRAM)],
        cwd=teacher_workspace,
    )
    prepared.run_smoke(
        "teacher-workflows",
        [str(prepared.python), str(TEACHER_WORKFLOWS_PROGRAM)],
        cwd=teacher_workspace,
    )

    attention_workspace = prepared.fresh_working_directory("attention")
    attention_environment = {
        "PDS_MERIDIAN_SMOKE_SOURCE_ROOT": str(SOURCE_ROOT),
    }
    prepared.run_smoke(
        "attention-seed",
        [str(prepared.python), str(PREVIEW_REVIEW_PROGRAM)],
        cwd=attention_workspace,
        env=attention_environment,
    )
    prepared.run_smoke(
        "attention",
        [str(prepared.python), str(ATTENTION_PROGRAM)],
        cwd=attention_workspace,
        env=attention_environment,
    )


def main(argv: list[str] | None = None) -> int:
    """Prepare one Core matrix and run the migrated program-backed smokes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    parser.add_argument("scoreform_wheel", type=Path)
    parser.add_argument("quillan_wheel", type=Path)
    parser.add_argument("concord_wheel", type=Path)
    parser.add_argument("--temp-parent", type=Path)
    args = parser.parse_args(argv)

    wheels = InstalledWheelSet(
        meridian=args.meridian_wheel,
        core=args.core_wheel,
        scoreform=args.scoreform_wheel,
        quillan=args.quillan_wheel,
        concord=args.concord_wheel,
    )
    with PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.CORE),
        wheels,
        temp_parent=args.temp_parent,
    ) as prepared:
        run_core_program_smokes(prepared)

    print(
        "Issue #96 prepared Core matrix program-backed qualification passed.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
