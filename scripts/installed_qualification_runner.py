"""Central prepared installed-qualification orchestration for Issue #96."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable
from pathlib import Path

from scripts.installed_qualification_core_programs import (
    run_core_inline_smokes,
    run_core_program_smokes,
)
from scripts.installed_qualification_harness import (
    InstalledWheelSet,
    PreparedEnvironmentError,
    PreparedInstalledEnvironment,
)
from scripts.installed_qualification_matrix import DependencyMatrixId, matrix_for
from scripts.smoke_test_conventional_grade_wheel import (
    run_prepared_smoke as run_conventional_grade_prepared_smoke,
)
from scripts.smoke_test_teacher_grade_override_wheel import (
    run_prepared_smoke as run_teacher_grade_override_prepared_smoke,
)
from scripts.smoke_test_wheel import (
    run_all_adapters_prepared_smoke,
    run_concord_adapter_prepared_smoke,
    run_core_foundation_prepared_smoke,
    run_quillan_adapter_prepared_smoke,
    run_scoreform_adapter_prepared_smoke,
)


def _working_layout(
    prepared: PreparedInstalledEnvironment,
    smoke_name: str,
) -> tuple[Path, Path]:
    root = prepared.fresh_working_directory(smoke_name)
    outside = root / "outside"
    outside.mkdir()
    return root, outside


def _run_acceptance(
    prepared: PreparedInstalledEnvironment,
    smoke_name: str,
    action: Callable[[], None],
) -> None:
    try:
        action()
    except subprocess.CalledProcessError as exc:
        command = subprocess.list2cmdline([str(item) for item in exc.cmd])
        raise PreparedEnvironmentError(
            f"Matrix {prepared.matrix.matrix_id.value!r} smoke "
            f"{smoke_name!r} failed: {command}"
        ) from exc
    prepared.assert_package_set_immutable(smoke_name)


def run_migrated_matrices(
    wheels: InstalledWheelSet,
    *,
    temp_parent: Path | None = None,
) -> None:
    """Run currently migrated acceptance in its exact prepared matrices."""
    with PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.CORE),
        wheels,
        temp_parent=temp_parent,
    ) as prepared:
        root, outside = _working_layout(prepared, "wheel-foundation")
        _run_acceptance(
            prepared,
            "wheel-foundation",
            lambda: run_core_foundation_prepared_smoke(
                prepared.python,
                prepared.meridian,
                root,
                outside,
            ),
        )
        run_core_inline_smokes(prepared)
        run_core_program_smokes(prepared)

    with PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.SCOREFORM),
        wheels,
        temp_parent=temp_parent,
    ) as prepared:
        _, outside = _working_layout(prepared, "scoreform-adapter")
        _run_acceptance(
            prepared,
            "scoreform-adapter",
            lambda: run_scoreform_adapter_prepared_smoke(
                prepared.python,
                outside,
            ),
        )

        _, outside = _working_layout(prepared, "conventional-grade")
        _run_acceptance(
            prepared,
            "conventional-grade",
            lambda: run_conventional_grade_prepared_smoke(
                prepared.python,
                outside,
            ),
        )

        _, outside = _working_layout(prepared, "teacher-grade-override")
        _run_acceptance(
            prepared,
            "teacher-grade-override",
            lambda: run_teacher_grade_override_prepared_smoke(
                prepared.python,
                outside,
            ),
        )

    with PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.QUILLAN),
        wheels,
        temp_parent=temp_parent,
    ) as prepared:
        _, outside = _working_layout(prepared, "quillan-adapter")
        _run_acceptance(
            prepared,
            "quillan-adapter",
            lambda: run_quillan_adapter_prepared_smoke(
                prepared.python,
                outside,
            ),
        )

    with PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.CONCORD),
        wheels,
        temp_parent=temp_parent,
    ) as prepared:
        _, outside = _working_layout(prepared, "concord-adapter")
        _run_acceptance(
            prepared,
            "concord-adapter",
            lambda: run_concord_adapter_prepared_smoke(
                prepared.python,
                outside,
            ),
        )

    with PreparedInstalledEnvironment(
        matrix_for(DependencyMatrixId.ALL_ADAPTERS),
        wheels,
        temp_parent=temp_parent,
    ) as prepared:
        _, outside = _working_layout(prepared, "all-adapters-composition")
        _run_acceptance(
            prepared,
            "all-adapters-composition",
            lambda: run_all_adapters_prepared_smoke(
                prepared.python,
                outside,
            ),
        )


def main(argv: list[str] | None = None) -> int:
    """Run the currently migrated prepared installed-qualification matrices."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meridian_wheel", type=Path)
    parser.add_argument("core_wheel", type=Path)
    parser.add_argument("scoreform_wheel", type=Path)
    parser.add_argument("quillan_wheel", type=Path)
    parser.add_argument("concord_wheel", type=Path)
    parser.add_argument("--temp-parent", type=Path)
    args = parser.parse_args(argv)

    run_migrated_matrices(
        InstalledWheelSet(
            meridian=args.meridian_wheel,
            core=args.core_wheel,
            scoreform=args.scoreform_wheel,
            quillan=args.quillan_wheel,
            concord=args.concord_wheel,
        ),
        temp_parent=args.temp_parent,
    )
    print("Issue #96 prepared installed qualification passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
