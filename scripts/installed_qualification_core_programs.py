"""Run program-backed Core-only installed smokes in one prepared matrix."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.installed_qualification_harness import (
    InstalledWheelSet,
    PreparedInstalledEnvironment,
)
from scripts.installed_qualification_matrix import DependencyMatrixId, matrix_for
from scripts.smoke_test_academic_period_proficiency_wheel import (
    run_prepared_smoke as run_academic_period_prepared,
)
from scripts.smoke_test_explanation_traces_wheel import (
    run_prepared_smoke as run_explanation_traces_prepared,
)
from scripts.smoke_test_grade_items_wheel import (
    run_prepared_smoke as run_grade_items_prepared,
)
from scripts.smoke_test_grouping_signal_contract_wheel import (
    run_prepared_smoke as run_grouping_contract_prepared,
)
from scripts.smoke_test_grouping_signal_policy_wheel import (
    run_prepared_smoke as run_grouping_policy_prepared,
)

SCRIPT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = SCRIPT_ROOT.parent

GENERATION_PROGRAM = SCRIPT_ROOT / "smoke_program_grouping_signal_generation.py"
PREVIEW_REVIEW_PROGRAM = (
    SCRIPT_ROOT / "smoke_program_grouping_signal_preview_review.py"
)
EXPORT_PROGRAM = SCRIPT_ROOT / "smoke_program_grouping_signal_export.py"
TEACHER_WORKFLOWS_PROGRAM = SCRIPT_ROOT / "smoke_program_teacher_workflows.py"
ATTENTION_PROGRAM = SCRIPT_ROOT / "smoke_program_attention.py"



def _prepared_layout(
    prepared: PreparedInstalledEnvironment,
    smoke_name: str,
) -> tuple[Path, Path]:
    root = prepared.fresh_working_directory(smoke_name)
    outside = root / "outside"
    outside.mkdir()
    return root, outside


def _finish_inline_smoke(
    prepared: PreparedInstalledEnvironment,
    smoke_name: str,
) -> None:
    prepared.assert_package_set_immutable(smoke_name)


def run_core_inline_smokes(prepared: PreparedInstalledEnvironment) -> None:
    """Run migrated inline Core smoke logic inside the prepared environment."""
    if prepared.matrix.matrix_id is not DependencyMatrixId.CORE:
        raise ValueError(
            "Inline Core smoke batch requires the core dependency matrix."
        )

    root, outside = _prepared_layout(prepared, "grade-items")
    run_grade_items_prepared(prepared.python, root, outside)
    _finish_inline_smoke(prepared, "grade-items")

    root, outside = _prepared_layout(prepared, "academic-period-proficiency")
    run_academic_period_prepared(prepared.python, root, outside)
    _finish_inline_smoke(prepared, "academic-period-proficiency")

    root, outside = _prepared_layout(prepared, "grouping-signal-contract")
    run_grouping_contract_prepared(prepared.python, root, outside)
    _finish_inline_smoke(prepared, "grouping-signal-contract")

    root, outside = _prepared_layout(prepared, "grouping-signal-policy")
    run_grouping_policy_prepared(prepared.python, root, outside)
    _finish_inline_smoke(prepared, "grouping-signal-policy")

    root, outside = _prepared_layout(prepared, "explanation-traces")
    run_explanation_traces_prepared(
        prepared.python,
        prepared.meridian,
        root,
        outside,
    )
    _finish_inline_smoke(prepared, "explanation-traces")

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
        run_core_inline_smokes(prepared)
        run_core_program_smokes(prepared)

    print(
        "Issue #96 prepared Core matrix program-backed qualification passed.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
