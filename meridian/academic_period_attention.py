"""Read-only current attention for selected Academic Period proficiency results.

Issue #43 treats staleness as a property of an explicitly selected #35 result,
not of missing calculations or historical result revisions.  This module
compares each selected result only with canonical current selectors for the
same bounded calculation basis.  It never opens protected producer evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from pds_core.academic_period_storage import (
    AcademicPeriodCalendarStorageError,
    get_current_academic_period_calendar_revision,
)

from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_ALGORITHM_VERSION,
    AcademicPeriodProficiencyResultFreshness,
    AcademicPeriodProficiencyResultSnapshot,
    AcademicPeriodProficiencyStalenessReason,
)
from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyStorageError,
    StoredAcademicPeriodProficiencyResult,
    academic_period_proficiency_result_current_path,
    academic_period_proficiency_results_directory,
    load_current_academic_period_proficiency_policy,
    load_current_academic_period_proficiency_result,
)
from meridian.grade_item_membership_storage import (
    GradeItemMembershipStorageError,
    load_current_grade_item_membership_decision,
)
from meridian.grade_item_storage import (
    GradeItemStorageError,
    load_current_grade_item_revision,
)
from meridian.proficiency_attention import (
    MeridianAttentionItem,
    MeridianAttentionSummary,
    build_meridian_attention_summary,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    load_current_proficiency_scale,
)
from meridian.standards_proficiency_storage import (
    StandardProficiencyStorageError,
    load_current_standard_proficiency_result,
)

_MAXIMUM_CURRENT_RESULT_POINTER_BYTES: Final[int] = 16 * 1024
_MAXIMUM_CURRENT_RESULT_TARGETS: Final[int] = 100_000
_CURRENT_POINTER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "school_year",
        "period_id",
        "student_id",
        "standard_id",
        "standard_key",
        "result_revision",
        "result_sha256",
    }
)


class AcademicPeriodAttentionReadError(RuntimeError):
    """Raised when current #35 attention state cannot be inspected safely."""

    code = "attention.academic_period.read_failed"


def inspect_academic_period_attention_for_class(
    workspace_root: str | Path,
    class_id: str,
    *,
    active_school_year: str | None = None,
) -> MeridianAttentionSummary:
    """Return aggregate stale selected #35 targets for one exact class.

    Missing result families and unselected historical revisions are not
    attention.  Each stale selected logical #35 target contributes exactly one
    ``academic_period_proficiency_targets`` count unit.
    """

    try:
        selected = _discover_current_results(
            workspace_root,
            class_id,
            active_school_year=active_school_year,
        )
        stale_count = sum(
            1
            for stored in selected
            if _current_result_is_stale(workspace_root, stored)
        )
    except (
        AcademicPeriodProficiencyStorageError,
        AcademicPeriodCalendarStorageError,
        GradeItemStorageError,
        GradeItemMembershipStorageError,
        ProficiencyMappingStorageError,
        StandardProficiencyStorageError,
        OSError,
        ValueError,
    ) as error:
        raise AcademicPeriodAttentionReadError(
            "Current Academic Period proficiency attention could not be "
            "inspected safely."
        ) from error

    items: tuple[MeridianAttentionItem, ...] = ()
    if stale_count:
        items = (
            MeridianAttentionItem(
                code="meridian_academic_period_calculation_stale",
                count=stale_count,
                class_id=class_id,
            ),
        )
    return build_meridian_attention_summary(items)


def _discover_current_results(
    workspace_root: str | Path,
    class_id: str,
    *,
    active_school_year: str | None,
) -> tuple[StoredAcademicPeriodProficiencyResult, ...]:
    root = Path(workspace_root).resolve()
    collection = academic_period_proficiency_results_directory(root, class_id)
    if not collection.exists():
        return ()
    if collection.is_symlink() or not collection.is_dir():
        raise AcademicPeriodAttentionReadError(
            "Academic Period proficiency result collection is not a regular directory."
        )

    pointers = tuple(
        sorted(
            collection.rglob("current.json"),
            key=lambda path: path.as_posix(),
        )
    )
    if len(pointers) > _MAXIMUM_CURRENT_RESULT_TARGETS:
        raise AcademicPeriodAttentionReadError(
            "Academic Period proficiency current-result target count exceeds the "
            "bounded attention maximum."
        )

    selected: list[StoredAcademicPeriodProficiencyResult] = []
    for pointer in pointers:
        _require_regular_path_below(collection, pointer)
        data = _read_pointer(pointer)
        school_year = _required_text(data, "school_year")
        if active_school_year is not None and school_year != active_school_year:
            continue
        pointer_class = _required_text(data, "class_id")
        if pointer_class != class_id:
            raise AcademicPeriodAttentionReadError(
                "Academic Period proficiency current pointer crosses class scope."
            )
        period_id = _required_text(data, "period_id")
        student_id = _required_text(data, "student_id")
        standard_id = _required_text(data, "standard_id")
        expected = academic_period_proficiency_result_current_path(
            root,
            class_id,
            school_year,
            period_id,
            student_id,
            standard_id,
        )
        if pointer != expected:
            raise AcademicPeriodAttentionReadError(
                "Academic Period proficiency current pointer is not at "
                "its canonical path."
            )
        stored = load_current_academic_period_proficiency_result(
            root,
            class_id,
            school_year,
            period_id,
            student_id,
            standard_id,
        )
        if stored is None:
            raise AcademicPeriodAttentionReadError(
                "Discovered Academic Period proficiency current pointer "
                "did not resolve."
            )
        selected.append(stored)
    return tuple(selected)


def assess_selected_academic_period_proficiency_result_freshness(
    workspace_root: str | Path,
    stored: StoredAcademicPeriodProficiencyResult,
) -> AcademicPeriodProficiencyResultFreshness:
    """Assess whether one exact selected #35 result still matches current basis.

    The caller supplies the exact persisted result it observed. This helper first
    proves that the same revision/digest is still the explicit current selection,
    then applies the same canonical dependency checks used by Academic Period
    attention. It never recalculates proficiency or opens producer evidence.
    """

    snapshot = stored.snapshot
    if not isinstance(snapshot, AcademicPeriodProficiencyResultSnapshot):
        raise AcademicPeriodAttentionReadError(
            "Selected Academic Period proficiency result has an invalid snapshot."
        )

    inputs_changed = False
    policy_changed = False
    scale_changed = False
    calendar_changed = False
    algorithm_changed = (
        snapshot.algorithm_version != ACADEMIC_PERIOD_PROFICIENCY_ALGORITHM_VERSION
    )

    try:
        period = snapshot.target_period.period
        selected = load_current_academic_period_proficiency_result(
            workspace_root,
            snapshot.class_id,
            period.school_year,
            period.period_id,
            snapshot.student_id,
            snapshot.standard_id,
        )
        if (
            selected is None
            or selected.result_sha256 != stored.result_sha256
            or selected.snapshot != snapshot
        ):
            inputs_changed = True

        current_calendar = get_current_academic_period_calendar_revision(
            workspace_root,
            period.school_year,
        )
        calendar_changed = (
            current_calendar != snapshot.target_period.calendar_revision
        )

        policy_ref = snapshot.policy_reference
        current_policy = load_current_academic_period_proficiency_policy(
            workspace_root,
            snapshot.class_id,
            policy_ref.policy_id,
        )
        policy_changed = (
            current_policy is None or current_policy.reference != policy_ref
        )

        scale_ref = snapshot.target_scale
        current_scale = load_current_proficiency_scale(
            workspace_root,
            snapshot.class_id,
            scale_ref.scale_id,
        )
        scale_changed = (
            current_scale is None or current_scale.reference != scale_ref
        )

        for entry in snapshot.inputs.entries:
            current_grade_item = load_current_grade_item_revision(
                workspace_root,
                snapshot.class_id,
                entry.grade_item.grade_item_id,
            )
            if current_grade_item is None:
                inputs_changed = True
            else:
                revision = current_grade_item.revision
                if (
                    revision.grade_item_revision
                    != entry.grade_item.grade_item_revision
                    or current_grade_item.revision_sha256
                    != entry.grade_item.grade_item_revision_sha256
                ):
                    inputs_changed = True

            for basis in entry.memberships:
                current_membership = load_current_grade_item_membership_decision(
                    workspace_root,
                    snapshot.class_id,
                    entry.grade_item.grade_item_id,
                    basis.work_reference.work,
                )
                if current_membership is None:
                    inputs_changed = True
                    continue
                decision = current_membership.decision
                assignment = decision.academic_period
                if (
                    decision.decision != "included"
                    or decision.grade_item_revision != basis.grade_item_revision
                    or decision.grade_item_revision_sha256
                    != basis.grade_item_revision_sha256
                    or decision.work_reference != basis.work_reference
                    or decision.membership_revision != basis.membership_revision
                    or current_membership.decision_sha256
                    != basis.membership_sha256
                    or assignment is None
                    or assignment.period != basis.academic_period.period
                    or assignment.calendar_revision
                    != basis.academic_period.calendar_revision
                ):
                    inputs_changed = True

            current_grade_item_result = load_current_standard_proficiency_result(
                workspace_root,
                snapshot.class_id,
                entry.grade_item.grade_item_id,
                snapshot.student_id,
                snapshot.standard_id,
            )
            current_reference = (
                None
                if current_grade_item_result is None
                else current_grade_item_result.reference
            )
            if current_reference != entry.result_reference:
                inputs_changed = True
    except (
        AcademicPeriodProficiencyStorageError,
        AcademicPeriodCalendarStorageError,
        GradeItemStorageError,
        GradeItemMembershipStorageError,
        ProficiencyMappingStorageError,
        StandardProficiencyStorageError,
        OSError,
        ValueError,
    ) as error:
        raise AcademicPeriodAttentionReadError(
            "Selected Academic Period proficiency result freshness could not be "
            "assessed safely."
        ) from error

    reasons: list[AcademicPeriodProficiencyStalenessReason] = []
    if inputs_changed:
        reasons.append("inputs_changed")
    if policy_changed:
        reasons.append("policy_changed")
    if scale_changed:
        reasons.append("scale_changed")
    if calendar_changed:
        reasons.append("calendar_changed")
    if algorithm_changed:
        reasons.append("algorithm_changed")
    return AcademicPeriodProficiencyResultFreshness(
        status="current" if not reasons else "stale",
        reasons=tuple(reasons),
    )


def _current_result_is_stale(
    workspace_root: str | Path,
    stored: StoredAcademicPeriodProficiencyResult,
) -> bool:
    return (
        assess_selected_academic_period_proficiency_result_freshness(
            workspace_root,
            stored,
        ).status
        == "stale"
    )

def _read_pointer(path: Path) -> dict[str, object]:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise AcademicPeriodAttentionReadError(
            "Could not inspect an Academic Period proficiency current pointer."
        ) from error
    if size <= 0 or size > _MAXIMUM_CURRENT_RESULT_POINTER_BYTES:
        raise AcademicPeriodAttentionReadError(
            "Academic Period proficiency current pointer has invalid size."
        )
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AcademicPeriodAttentionReadError(
            "Academic Period proficiency current pointer is unreadable."
        ) from error
    if not isinstance(data, dict) or frozenset(data) != _CURRENT_POINTER_KEYS:
        raise AcademicPeriodAttentionReadError(
            "Academic Period proficiency current pointer shape is invalid."
        )
    return data


def _required_text(data: dict[str, object], field: str) -> str:
    value = data[field]
    if not isinstance(value, str) or not value:
        raise AcademicPeriodAttentionReadError(
            f"Academic Period proficiency current pointer {field} is invalid."
        )
    return value


def _require_regular_path_below(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise AcademicPeriodAttentionReadError(
            "Academic Period proficiency pointer escaped its collection."
        ) from error
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise AcademicPeriodAttentionReadError(
                "Academic Period proficiency attention refuses symlinked state."
            )
    if not path.is_file():
        raise AcademicPeriodAttentionReadError(
            "Academic Period proficiency current pointer is not a regular file."
        )


__all__ = [
    "AcademicPeriodAttentionReadError",
    "assess_selected_academic_period_proficiency_result_freshness",
    "inspect_academic_period_attention_for_class",
]
