from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.routes import class_dir, class_metadata_path
from pds_core.routing_models import ModuleWorkRef

import meridian.grade_item_membership_storage as membership_storage
from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationInputEntry,
    AcademicPeriodProficiencyAggregationInputs,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyMembershipBasis,
    AcademicPeriodProficiencyTarget,
    calculate_academic_period_proficiency,
    create_academic_period_proficiency_result_snapshot,
)
from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodProficiencyTraceTarget,
    ExplanationTraceIntegrityError,
    ExplanationTraceNotFoundError,
    ExplanationTraceTargetError,
    academic_period_proficiency_explanation_to_json_bytes,
    explain_academic_period_proficiency,
    render_academic_period_proficiency_explanation_text,
)
from meridian.academic_period_proficiency_storage import (
    academic_period_proficiency_policy_revision_path,
    select_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_policy_revision,
    write_academic_period_proficiency_result_revision,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_storage import write_grade_item_revision
from meridian.grade_items import GradeItemRevision, GradeItemWorkReference
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.proficiency_mapping_storage import write_proficiency_scale_revision
from meridian.standards_evidence import (
    STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
    STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
    GradeItemAggregationBasis,
    StandardAggregationInputs,
)
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    StandardProficiencyActor,
    StandardProficiencyCalculationPolicy,
    calculate_standard_proficiency,
    create_standard_proficiency_result_snapshot,
    standard_proficiency_result_reference,
)
from meridian.standards_proficiency_storage import (
    select_standard_proficiency_result_revision,
    write_standard_proficiency_policy_revision,
    write_standard_proficiency_result_revision,
)

CLASS_ID = "synthetic_class_2026"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "mp1"
STUDENT_ID = "student_001"
STANDARD_ID = "urn:njsls:ela:RL.CR.11-12.1"
NOW = datetime(2026, 9, 4, 13, tzinfo=UTC)


def _scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="course_proficiency",
        scale_revision=1,
        supersedes_revision=None,
        title="Course proficiency",
        description="Criterion-referenced classroom proficiency.",
        levels=(
            ProficiencyLevel("beginning", 1, "Beginning", "Initial evidence."),
            ProficiencyLevel("developing", 2, "Developing", "Partial evidence."),
            ProficiencyLevel("proficient", 3, "Proficient", "Meets criterion."),
            ProficiencyLevel("advanced", 4, "Advanced", "Extends criterion."),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def _grade_item_policy(
    target: ProficiencyScale,
) -> StandardProficiencyCalculationPolicy:
    return StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="grade_item_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Grade Item policy",
        target_scale=proficiency_scale_reference(target),
        strategy="highest",
        minimum_performance_observations=1,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=("association_unresolved",),
        native_state_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def _period_policy(
    target: ProficiencyScale,
) -> AcademicPeriodProficiencyAggregationPolicy:
    return AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="period_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Academic Period policy",
        target_scale=proficiency_scale_reference(target),
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale="Explain exact period aggregation.",
        revised_at=NOW,
    )


def _workspace(tmp_path: Path) -> tuple[Path, ProficiencyScale]:
    root = tmp_path / "workspace"
    class_dir(root, CLASS_ID).mkdir(parents=True)
    write_class_metadata(
        class_metadata_path(root, CLASS_ID),
        ClassMetadata(
            class_id=CLASS_ID,
            school_year=SCHOOL_YEAR,
            created_at=NOW,
            updated_at=NOW,
            module_details={},
        ),
    )
    calendar = AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year=SCHOOL_YEAR,
        calendar_revision=1,
        created_at=NOW,
        updated_at=NOW,
        periods=(
            AcademicPeriod(
                period_id="mp1",
                period_type="marking_period",
                label="Marking Period 1",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 11, 8),
                parent_period_id=None,
                sequence=1,
                lifecycle="active",
            ),
            AcademicPeriod(
                period_id="mp2",
                period_type="marking_period",
                label="Marking Period 2",
                start_date=date(2026, 11, 9),
                end_date=date(2027, 1, 20),
                parent_period_id=None,
                sequence=2,
                lifecycle="planned",
            ),
        ),
    )
    write_academic_period_calendar(
        root,
        calendar,
        expected_current_revision=None,
    )
    scale = write_proficiency_scale_revision(root, _scale()).stored.scale
    write_standard_proficiency_policy_revision(
        root,
        _grade_item_policy(scale),
    )
    write_academic_period_proficiency_policy_revision(
        root,
        _period_policy(scale),
    )
    return root, scale


def _write_grade_item(root: Path, grade_item_id: str) -> GradeItemAggregationBasis:
    stored = write_grade_item_revision(
        root,
        GradeItemRevision(
            schema_version="1",
            record_type="meridian_grade_item",
            class_id=CLASS_ID,
            grade_item_id=grade_item_id,
            grade_item_revision=1,
            supersedes_revision=None,
            title=f"Assessment {grade_item_id}",
            purpose="standards_proficiency",
            status="active",
            weighting=None,
            created_at=NOW,
            revised_at=NOW,
        ),
    ).stored
    return GradeItemAggregationBasis(
        CLASS_ID,
        grade_item_id,
        1,
        stored.revision_sha256,
    )


def _write_membership(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    grade_item: GradeItemAggregationBasis,
    *,
    work_id: str,
    period_id: str,
) -> AcademicPeriodProficiencyMembershipBasis:
    work = ModuleWorkRef("scoreform", CLASS_ID, work_id)
    monkeypatch.setattr(
        membership_storage,
        "validate_grade_item_membership_dependencies",
        lambda *args, **kwargs: object(),
    )
    stored = membership_storage.write_grade_item_membership_revision(
        root,
        GradeItemMembershipDecision(
            schema_version="1",
            record_type="meridian_grade_item_membership",
            class_id=CLASS_ID,
            grade_item_id=grade_item.grade_item_id,
            grade_item_revision=grade_item.grade_item_revision,
            grade_item_revision_sha256=(
                grade_item.grade_item_revision_sha256
            ),
            work_reference=GradeItemWorkReference(
                work=work,
                registration_revision=1,
            ),
            membership_revision=1,
            supersedes_revision=None,
            decision="included",
            academic_period=GradeItemAcademicPeriodAssignment(
                period=AcademicPeriodRef(SCHOOL_YEAR, period_id),
                calendar_revision=1,
            ),
            actor_id="teacher_local",
            rationale=None,
            decided_at=NOW,
        ),
    ).stored
    return AcademicPeriodProficiencyMembershipBasis(
        grade_item_id=grade_item.grade_item_id,
        grade_item_revision=grade_item.grade_item_revision,
        grade_item_revision_sha256=grade_item.grade_item_revision_sha256,
        work_reference=stored.decision.work_reference,
        membership_revision=1,
        membership_sha256=stored.decision_sha256,
        academic_period=AcademicPeriodProficiencyTarget(
            AcademicPeriodRef(SCHOOL_YEAR, period_id),
            1,
        ),
    )


def _write_insufficient_grade_item_result(
    root: Path,
    scale: ProficiencyScale,
    grade_item: GradeItemAggregationBasis,
    *,
    revision: int,
) -> object:
    inputs = StandardAggregationInputs(
        schema_version=STANDARD_AGGREGATION_INPUTS_SCHEMA_VERSION,
        record_type=STANDARD_AGGREGATION_INPUTS_RECORD_TYPE,
        grade_item=grade_item,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(scale),
        entries=(),
    )
    policy = _grade_item_policy(scale)
    outcome = calculate_standard_proficiency(inputs, policy, scale)
    snapshot = create_standard_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=revision,
        calculated_at=NOW + timedelta(minutes=revision - 1),
    )
    return write_standard_proficiency_result_revision(root, snapshot).stored


def _write_empty_period_result(
    root: Path,
    scale: ProficiencyScale,
    *,
    revision: int = 1,
) -> None:
    target = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
        1,
    )
    inputs = AcademicPeriodProficiencyAggregationInputs(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=target,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(scale),
        period_membership_scope="direct",
        entries=(),
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        _period_policy(scale),
        scale,
    )
    snapshot = create_academic_period_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=revision,
        calculated_at=NOW + timedelta(minutes=revision - 1),
    )
    write_academic_period_proficiency_result_revision(root, snapshot)


def _target(
    *,
    selection: str = "revision",
    revision: int | None = 1,
) -> AcademicPeriodProficiencyTraceTarget:
    return AcademicPeriodProficiencyTraceTarget(
        class_id=CLASS_ID,
        school_year=SCHOOL_YEAR,
        period_id=PERIOD_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        selection=selection,  # type: ignore[arg-type]
        result_revision=revision,
    )


def test_target_rejects_current_revision_ambiguity() -> None:
    with pytest.raises(ExplanationTraceTargetError):
        _target(selection="current", revision=1)
    with pytest.raises(ExplanationTraceTargetError):
        _target(selection="revision", revision=None)


def test_current_requires_explicit_selected_result(
    tmp_path: Path,
) -> None:
    root, scale = _workspace(tmp_path)
    _write_empty_period_result(root, scale)

    with pytest.raises(ExplanationTraceNotFoundError):
        explain_academic_period_proficiency(
            root,
            _target(selection="current", revision=None),
        )


def test_historical_and_current_selection_are_never_substituted(
    tmp_path: Path,
) -> None:
    root, scale = _workspace(tmp_path)
    _write_empty_period_result(root, scale, revision=1)
    _write_empty_period_result(root, scale, revision=2)
    select_academic_period_proficiency_result_revision(
        root,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        2,
        expected_current_result_revision=None,
    )

    historical = explain_academic_period_proficiency(root, _target(revision=1))
    current = explain_academic_period_proficiency(
        root,
        _target(selection="current", revision=None),
    )

    assert historical.result_revision == 1
    assert historical.selection_state == "historical"
    assert current.result_revision == 2
    assert current.selection_state == "selected_current"


def test_empty_result_projects_exact_calendar_policy_scale_and_reason(
    tmp_path: Path,
) -> None:
    root, scale = _workspace(tmp_path)
    _write_empty_period_result(root, scale)

    explanation = explain_academic_period_proficiency(root, _target())

    assert explanation.target_period.school_year == SCHOOL_YEAR
    assert explanation.target_period.period_id == PERIOD_ID
    assert explanation.target_period.calendar_revision == 1
    assert explanation.target_period.label == "Marking Period 1"
    assert explanation.policy.policy_id == "period_policy"
    assert explanation.policy.period_membership_scope == "direct"
    assert explanation.policy.missing_result_handling == "noncontributing"
    assert explanation.scale.scale_id == "course_proficiency"
    assert explanation.grade_items == ()
    assert explanation.calculation.status == "insufficient_evidence"
    assert explanation.calculation.candidate_count == 0
    assert explanation.calculation.insufficiency_reasons[0].kind == (
        "no_calculated_results"
    )


def test_missing_exact_period_policy_is_integrity_failure(
    tmp_path: Path,
) -> None:
    root, scale = _workspace(tmp_path)
    _write_empty_period_result(root, scale)
    policy_path = academic_period_proficiency_policy_revision_path(
        root,
        CLASS_ID,
        "period_policy",
        1,
    )
    policy_path.unlink()
    Path(str(policy_path) + ".sha256").unlink()

    with pytest.raises(ExplanationTraceIntegrityError, match="#35"):
        explain_academic_period_proficiency(root, _target())


def test_grade_item_rows_distinguish_insufficient_missing_and_period_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, scale = _workspace(tmp_path)

    insufficient_item = _write_grade_item(root, "item_a")
    insufficient_membership = _write_membership(
        root,
        monkeypatch,
        insufficient_item,
        work_id="work_a",
        period_id="mp1",
    )
    child_revision_1 = _write_insufficient_grade_item_result(
        root,
        scale,
        insufficient_item,
        revision=1,
    )
    _write_insufficient_grade_item_result(
        root,
        scale,
        insufficient_item,
        revision=2,
    )
    select_standard_proficiency_result_revision(
        root,
        CLASS_ID,
        insufficient_item.grade_item_id,
        STUDENT_ID,
        STANDARD_ID,
        2,
        expected_current_result_revision=None,
    )

    missing_item = _write_grade_item(root, "item_b")
    missing_membership = _write_membership(
        root,
        monkeypatch,
        missing_item,
        work_id="work_b",
        period_id="mp1",
    )

    mismatch_item = _write_grade_item(root, "item_c")
    mismatch_membership = _write_membership(
        root,
        monkeypatch,
        mismatch_item,
        work_id="work_c",
        period_id="mp2",
    )

    child = child_revision_1.snapshot
    entries = (
        AcademicPeriodProficiencyAggregationInputEntry(
            grade_item=insufficient_item,
            memberships=(insufficient_membership,),
            status="insufficient_evidence",
            period_scope_mismatch_reason=None,
            result_reference=standard_proficiency_result_reference(child),
            result_algorithm_version=child.algorithm_version,
            result_calculation_fingerprint=child.calculation_fingerprint,
            result_status=child.outcome.status,
            proficiency_level_id=None,
            result_insufficiency_reasons=child.outcome.insufficiency_reasons,
        ),
        AcademicPeriodProficiencyAggregationInputEntry(
            grade_item=missing_item,
            memberships=(missing_membership,),
            status="missing_result",
            period_scope_mismatch_reason=None,
            result_reference=None,
            result_algorithm_version=None,
            result_calculation_fingerprint=None,
            result_status=None,
            proficiency_level_id=None,
            result_insufficiency_reasons=(),
        ),
        AcademicPeriodProficiencyAggregationInputEntry(
            grade_item=mismatch_item,
            memberships=(mismatch_membership,),
            status="period_scope_mismatch",
            period_scope_mismatch_reason="outside_target_period",
            result_reference=None,
            result_algorithm_version=None,
            result_calculation_fingerprint=None,
            result_status=None,
            proficiency_level_id=None,
            result_insufficiency_reasons=(),
        ),
    )
    target = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
        1,
    )
    inputs = AcademicPeriodProficiencyAggregationInputs(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=target,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(scale),
        period_membership_scope="direct",
        entries=entries,
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        _period_policy(scale),
        scale,
    )
    snapshot = create_academic_period_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    write_academic_period_proficiency_result_revision(root, snapshot)

    explanation = explain_academic_period_proficiency(root, _target())
    rows = {
        item.grade_item.grade_item_id: item
        for item in explanation.grade_items
    }

    assert rows["item_a"].status == "insufficient_evidence"
    assert rows["item_a"].contributed is False
    assert rows["item_a"].nested_grade_item_explanation is not None
    nested = rows["item_a"].nested_grade_item_explanation
    assert nested is not None
    assert nested.result_revision == 1
    assert nested.selection_state == "historical"

    assert rows["item_b"].status == "missing_result"
    assert rows["item_b"].result_reference is None
    assert rows["item_b"].nested_grade_item_explanation is None

    assert rows["item_c"].status == "period_scope_mismatch"
    assert rows["item_c"].period_scope_status == "period_scope_mismatch"
    assert rows["item_c"].period_scope_mismatch_reason == "outside_target_period"

    assert explanation.calculation.insufficient_result_count == 1
    assert explanation.calculation.missing_result_count == 1
    assert explanation.calculation.period_scope_mismatch_count == 1


def test_json_and_text_preserve_exact_nested_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, scale = _workspace(tmp_path)
    grade_item = _write_grade_item(root, "item_a")
    membership = _write_membership(
        root,
        monkeypatch,
        grade_item,
        work_id="work_a",
        period_id="mp1",
    )
    child_stored = _write_insufficient_grade_item_result(
        root,
        scale,
        grade_item,
        revision=1,
    )
    child = child_stored.snapshot
    target = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
        1,
    )
    entry = AcademicPeriodProficiencyAggregationInputEntry(
        grade_item=grade_item,
        memberships=(membership,),
        status="insufficient_evidence",
        period_scope_mismatch_reason=None,
        result_reference=standard_proficiency_result_reference(child),
        result_algorithm_version=child.algorithm_version,
        result_calculation_fingerprint=child.calculation_fingerprint,
        result_status=child.outcome.status,
        proficiency_level_id=None,
        result_insufficiency_reasons=child.outcome.insufficiency_reasons,
    )
    inputs = AcademicPeriodProficiencyAggregationInputs(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=target,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(scale),
        period_membership_scope="direct",
        entries=(entry,),
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        _period_policy(scale),
        scale,
    )
    write_academic_period_proficiency_result_revision(
        root,
        create_academic_period_proficiency_result_snapshot(
            inputs,
            outcome,
            result_revision=1,
            calculated_at=NOW,
        ),
    )

    explanation = explain_academic_period_proficiency(root, _target())
    payload = academic_period_proficiency_explanation_to_json_bytes(explanation)
    text = render_academic_period_proficiency_explanation_text(explanation)

    assert payload.endswith(b"\n")
    assert b'"result_revision": 1' in payload
    assert b'"nested_grade_item_explanation"' in payload
    assert b'"status": "insufficient_evidence"' in payload
    assert "exact #34 drill-down: revision=1" in text
    assert "status=insufficient_evidence" in text
