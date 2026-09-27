"""Issue #96 installed-qualification dependency matrix inventory.

This module describes the dependency-isolation boundaries that the repository
validator must preserve while installed-wheel qualification is consolidated.
It deliberately does not create environments or execute smoke programs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DependencyMatrixId(str, Enum):
    """Stable identifiers for installed dependency-isolation boundaries."""

    CORE = "core"
    SCOREFORM = "scoreform"
    QUILLAN = "quillan"
    CONCORD = "concord"
    SCOREFORM_QUILLAN = "scoreform-quillan"
    ALL_ADAPTERS = "all-adapters"


@dataclass(frozen=True)
class DependencyMatrix:
    """One immutable installed package-presence/absence boundary."""

    matrix_id: DependencyMatrixId
    producers: tuple[str, ...]

    @property
    def excluded_producers(self) -> tuple[str, ...]:
        """Return supported producer packages intentionally absent."""
        return tuple(
            producer
            for producer in SUPPORTED_PRODUCERS
            if producer not in self.producers
        )


@dataclass(frozen=True)
class SmokeAssignment:
    """One historical installed-environment setup and its required matrix."""

    name: str
    matrix_id: DependencyMatrixId
    source_wrapper: str


SUPPORTED_PRODUCERS = ("scoreform", "quillan", "concord")

DEPENDENCY_MATRICES: tuple[DependencyMatrix, ...] = (
    DependencyMatrix(DependencyMatrixId.CORE, ()),
    DependencyMatrix(DependencyMatrixId.SCOREFORM, ("scoreform",)),
    DependencyMatrix(DependencyMatrixId.QUILLAN, ("quillan",)),
    DependencyMatrix(DependencyMatrixId.CONCORD, ("concord",)),
    DependencyMatrix(
        DependencyMatrixId.SCOREFORM_QUILLAN,
        ("scoreform", "quillan"),
    ),
    DependencyMatrix(
        DependencyMatrixId.ALL_ADAPTERS,
        ("scoreform", "quillan", "concord"),
    ),
)

MATRIX_BY_ID = {matrix.matrix_id: matrix for matrix in DEPENDENCY_MATRICES}

# Pre-#96, smoke_test_wheel.py creates five venvs internally and the repository
# validator invokes nineteen additional one-venv wrappers. These 24 assignments
# capture those environment setups before consolidation. The names are logical
# qualification units rather than necessarily standalone script filenames.
SMOKE_ASSIGNMENTS: tuple[SmokeAssignment, ...] = (
    SmokeAssignment(
        "wheel-foundation",
        DependencyMatrixId.CORE,
        "scripts/smoke_test_wheel.py",
    ),
    SmokeAssignment(
        "scoreform-adapter",
        DependencyMatrixId.SCOREFORM,
        "scripts/smoke_test_wheel.py",
    ),
    SmokeAssignment(
        "quillan-adapter",
        DependencyMatrixId.QUILLAN,
        "scripts/smoke_test_wheel.py",
    ),
    SmokeAssignment(
        "concord-adapter",
        DependencyMatrixId.CONCORD,
        "scripts/smoke_test_wheel.py",
    ),
    SmokeAssignment(
        "all-adapters-composition",
        DependencyMatrixId.ALL_ADAPTERS,
        "scripts/smoke_test_wheel.py",
    ),
    SmokeAssignment(
        "grade-items",
        DependencyMatrixId.CORE,
        "scripts/smoke_test_grade_items_wheel.py",
    ),
    SmokeAssignment(
        "academic-period-proficiency",
        DependencyMatrixId.CORE,
        "scripts/smoke_test_academic_period_proficiency_wheel.py",
    ),
    SmokeAssignment(
        "grouping-signal-contract",
        DependencyMatrixId.CORE,
        "scripts/smoke_test_grouping_signal_contract_wheel.py",
    ),
    SmokeAssignment(
        "grouping-signal-policy",
        DependencyMatrixId.CORE,
        "scripts/smoke_test_grouping_signal_policy_wheel.py",
    ),
    SmokeAssignment(
        "grouping-signal-generation",
        DependencyMatrixId.CORE,
        "scripts/smoke_test_grouping_signal_generation_wheel.py",
    ),
    SmokeAssignment(
        "grouping-signal-preview-review",
        DependencyMatrixId.CORE,
        "scripts/smoke_test_grouping_signal_preview_review_wheel.py",
    ),
    SmokeAssignment(
        "grouping-signal-export",
        DependencyMatrixId.CORE,
        "scripts/smoke_test_grouping_signal_export_wheel.py",
    ),
    SmokeAssignment(
        "explanation-traces",
        DependencyMatrixId.CORE,
        "scripts/smoke_test_explanation_traces_wheel.py",
    ),
    SmokeAssignment(
        "teacher-workflows",
        DependencyMatrixId.CORE,
        "scripts/smoke_test_teacher_workflows_wheel.py",
    ),
    SmokeAssignment(
        "attention",
        DependencyMatrixId.CORE,
        "scripts/smoke_test_attention_wheel.py",
    ),
    SmokeAssignment(
        "proficiency-signal-export",
        DependencyMatrixId.SCOREFORM_QUILLAN,
        "scripts/smoke_test_proficiency_signal_export_wheel.py",
    ),
    SmokeAssignment(
        "conventional-grade",
        DependencyMatrixId.SCOREFORM,
        "scripts/smoke_test_conventional_grade_wheel.py",
    ),
    SmokeAssignment(
        "standards-grade",
        DependencyMatrixId.SCOREFORM_QUILLAN,
        "scripts/smoke_test_standards_grade_wheel.py",
    ),
    SmokeAssignment(
        "hybrid-grade",
        DependencyMatrixId.SCOREFORM_QUILLAN,
        "scripts/smoke_test_hybrid_grade_wheel.py",
    ),
    SmokeAssignment(
        "teacher-grade-override",
        DependencyMatrixId.SCOREFORM,
        "scripts/smoke_test_teacher_grade_override_wheel.py",
    ),
    SmokeAssignment(
        "grade-report-preview",
        DependencyMatrixId.ALL_ADAPTERS,
        "scripts/smoke_test_grade_report_preview_wheel.py",
    ),
    SmokeAssignment(
        "reporting-snapshot",
        DependencyMatrixId.ALL_ADAPTERS,
        "scripts/smoke_test_reporting_snapshot_wheel.py",
    ),
    SmokeAssignment(
        "report-exports",
        DependencyMatrixId.ALL_ADAPTERS,
        "scripts/smoke_test_report_exports_wheel.py",
    ),
    SmokeAssignment(
        "teacher-menu",
        DependencyMatrixId.ALL_ADAPTERS,
        "scripts/smoke_test_teacher_menu_wheel.py",
    ),
)

PRE_ISSUE96_ENVIRONMENT_SETUP_COUNT = len(SMOKE_ASSIGNMENTS)
TARGET_SHARED_ENVIRONMENT_COUNT = len(DEPENDENCY_MATRICES)


def matrix_for(matrix_id: DependencyMatrixId | str) -> DependencyMatrix:
    """Resolve one matrix identifier, failing closed for unknown values."""
    try:
        normalized = DependencyMatrixId(matrix_id)
    except ValueError as exc:
        raise KeyError(
            f"Unknown installed qualification matrix: {matrix_id!r}"
        ) from exc
    return MATRIX_BY_ID[normalized]


def assignments_for(
    matrix_id: DependencyMatrixId | str,
) -> tuple[SmokeAssignment, ...]:
    """Return deterministic smoke assignments for one dependency matrix."""
    matrix = matrix_for(matrix_id)
    return tuple(
        assignment
        for assignment in SMOKE_ASSIGNMENTS
        if assignment.matrix_id is matrix.matrix_id
    )


def validate_matrix_inventory() -> None:
    """Reject duplicate, unknown, or structurally inconsistent inventory."""
    matrix_ids = tuple(matrix.matrix_id for matrix in DEPENDENCY_MATRICES)
    if len(matrix_ids) != len(set(matrix_ids)):
        raise ValueError("Installed qualification matrix identifiers must be unique.")

    assignment_names = tuple(assignment.name for assignment in SMOKE_ASSIGNMENTS)
    if len(assignment_names) != len(set(assignment_names)):
        raise ValueError("Installed qualification smoke names must be unique.")

    known = set(matrix_ids)
    unknown = {
        assignment.matrix_id
        for assignment in SMOKE_ASSIGNMENTS
        if assignment.matrix_id not in known
    }
    if unknown:
        raise ValueError(
            "Installed qualification smoke assignments reference unknown matrices: "
            f"{sorted(item.value for item in unknown)!r}"
        )

    for matrix in DEPENDENCY_MATRICES:
        if tuple(dict.fromkeys(matrix.producers)) != matrix.producers:
            raise ValueError(
                f"Matrix {matrix.matrix_id.value!r} contains duplicate producers."
            )
        unsupported = set(matrix.producers) - set(SUPPORTED_PRODUCERS)
        if unsupported:
            raise ValueError(
                f"Matrix {matrix.matrix_id.value!r} contains unsupported producers: "
                f"{sorted(unsupported)!r}"
            )
