from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.standards_grade_storage as storage
from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
)
from meridian.grade_policy import (
    GradePolicyActor,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    ProficiencyGradeConversion,
    StandardGradeParticipation,
    StandardsBasedGradeConfiguration,
    grade_policy_reference,
)
from meridian.grade_policy_activation import GradePolicyActivationDecision
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_grade import (
    StandardsGradeStandardInput,
    calculate_standards_grade,
    create_standards_grade_calculation_input,
)
from meridian.standards_grade_result import create_standards_grade_result_snapshot
from meridian.standards_grade_storage import (
    StandardsGradeStorageConflictError,
    StandardsGradeStorageIntegrityError,
    get_current_standards_grade_result_revision,
    list_standards_grade_result_revisions,
    load_current_standards_grade_result,
    load_standards_grade_result_revision,
    select_standards_grade_result_revision,
    standards_grade_result_current_path,
    write_standards_grade_result_revision,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "s001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 13, 19, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SCALE = ProficiencyScaleReference(CLASS_ID, "course_scale", 1, SHA_A)


def _basis():
    config = StandardsBasedGradeConfiguration(
        target_scale=SCALE,
        standards=(StandardGradeParticipation("std.a", Decimal("1")),),
        conversions=(ProficiencyGradeConversion("proficient", Decimal("88")),),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=1,
    )
    policy = GradePolicyRevision(
        schema_version="1",
        record_type="meridian_grade_policy",
        class_id=CLASS_ID,
        policy_id="standards_grade_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Standards Grade Policy",
        calculation_family="standards_based",
        configuration=config,
        state_treatment=GradeStateTreatment(
            missing="blocking",
            pending="blocking",
            incomplete="blocking",
            excused="exclude",
            excluded="exclude",
            not_applicable="exclude",
            insufficient_evidence="blocking",
            unavailable="blocking",
            withdrawn="exclude",
            invalid="blocking",
            unresolved="blocking",
        ),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )
    activation = GradePolicyActivationDecision(
        schema_version="1",
        record_type="meridian_grade_policy_activation",
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=grade_policy_reference(policy),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        decided_at=NOW,
    )
    standard = StandardsGradeStandardInput(
        participation=config.standards[0],
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status="calculated",
        result_reference=AcademicPeriodProficiencyResultReference(
            CLASS_ID,
            PERIOD.school_year,
            PERIOD.period_id,
            STUDENT_ID,
            "std.a",
            1,
            SHA_B,
        ),
        result_calculation_fingerprint=SHA_C,
        result_algorithm_version="1",
        proficiency_level_id="proficient",
        target_scale=SCALE,
        freshness_status="current",
    )
    inputs = create_standards_grade_calculation_input(
        policy=policy,
        activation=activation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        standards=(standard,),
    )
    return inputs, calculate_standards_grade(inputs)


def _workspace(tmp_path):
    (tmp_path / "classes" / CLASS_ID).mkdir(parents=True)
    return tmp_path


def _snapshot(revision: int = 1, *, calculated_at: datetime = NOW):
    inputs, outcome = _basis()
    return create_standards_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=revision,
        calculated_at=calculated_at,
    )


def _accept_current_basis(monkeypatch, snapshot):
    monkeypatch.setattr(
        storage,
        "assemble_standards_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(
            inputs=snapshot.inputs,
            outcome=snapshot.outcome,
        ),
    )


def test_write_is_immutable_and_does_not_select(tmp_path, monkeypatch) -> None:
    root = _workspace(tmp_path)
    snapshot = _snapshot()
    _accept_current_basis(monkeypatch, snapshot)

    written = write_standards_grade_result_revision(root, snapshot)
    assert written.disposition == "created"
    assert written.stored.snapshot == snapshot
    assert list_standards_grade_result_revisions(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1
    ) == (1,)
    assert get_current_standards_grade_result_revision(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1
    ) is None
    assert load_current_standards_grade_result(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1
    ) is None


def test_exact_write_retry_is_existing_but_changed_bytes_conflict(
    tmp_path, monkeypatch
) -> None:
    root = _workspace(tmp_path)
    snapshot = _snapshot()
    _accept_current_basis(monkeypatch, snapshot)
    first = write_standards_grade_result_revision(root, snapshot)
    second = write_standards_grade_result_revision(root, snapshot)
    assert first.disposition == "created"
    assert second.disposition == "existing"

    changed = replace(snapshot, calculated_at=NOW + timedelta(seconds=1))
    with pytest.raises(StandardsGradeStorageConflictError, match="different content"):
        write_standards_grade_result_revision(root, changed)


def test_explicit_selection_uses_cas_and_allows_historical_reselection(
    tmp_path, monkeypatch
) -> None:
    root = _workspace(tmp_path)
    first = _snapshot()
    _accept_current_basis(monkeypatch, first)
    write_standards_grade_result_revision(root, first)

    second = _snapshot(2, calculated_at=NOW + timedelta(seconds=1))
    _accept_current_basis(monkeypatch, second)
    write_standards_grade_result_revision(root, second)

    monkeypatch.setattr(
        storage,
        "_validate_historical_dependencies",
        lambda *args: None,
    )
    selected1 = select_standards_grade_result_revision(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )
    assert selected1.disposition == "created"
    assert get_current_standards_grade_result_revision(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1
    ) == 1

    with pytest.raises(StandardsGradeStorageConflictError, match="Expected current"):
        select_standards_grade_result_revision(
            root,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            2,
            expected_current_result_revision=None,
        )

    selected2 = select_standards_grade_result_revision(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        2,
        expected_current_result_revision=1,
    )
    assert selected2.disposition == "updated"
    reselected = select_standards_grade_result_revision(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        1,
        expected_current_result_revision=2,
    )
    assert reselected.disposition == "updated"
    assert load_current_standards_grade_result(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1
    ).snapshot.result_revision == 1


def test_source_basis_change_before_commit_fails_closed(tmp_path, monkeypatch) -> None:
    root = _workspace(tmp_path)
    snapshot = _snapshot()
    changed_input = replace(
        snapshot.inputs,
        standards=(
            replace(
                snapshot.inputs.standards[0],
                result_reference=replace(
                    snapshot.inputs.standards[0].result_reference,
                    result_revision=2,
                    result_sha256="d" * 64,
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        storage,
        "assemble_standards_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(
            inputs=changed_input,
            outcome=calculate_standards_grade(changed_input),
        ),
    )
    with pytest.raises(StandardsGradeStorageConflictError, match="inputs changed"):
        write_standards_grade_result_revision(root, snapshot)


def test_corrupt_digest_is_rejected(tmp_path, monkeypatch) -> None:
    root = _workspace(tmp_path)
    snapshot = _snapshot()
    _accept_current_basis(monkeypatch, snapshot)
    written = write_standards_grade_result_revision(root, snapshot)
    digest_path = written.stored.path.with_suffix(".json.sha256")
    digest_path.write_text("0" * 64 + "\n", encoding="ascii")
    with pytest.raises(StandardsGradeStorageIntegrityError, match="digest"):
        load_standards_grade_result_revision(
            root, CLASS_ID, STUDENT_ID, PERIOD, 1, 1
        )


def test_corrupt_current_pointer_digest_is_rejected(tmp_path, monkeypatch) -> None:
    root = _workspace(tmp_path)
    snapshot = _snapshot()
    _accept_current_basis(monkeypatch, snapshot)
    write_standards_grade_result_revision(root, snapshot)
    monkeypatch.setattr(
        storage,
        "_validate_historical_dependencies",
        lambda *args: None,
    )
    select_standards_grade_result_revision(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )
    pointer = standards_grade_result_current_path(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1
    )
    text = pointer.read_text(encoding="utf-8").replace(
        '"result_sha256": "',
        '"result_sha256": "f',
        1,
    )
    pointer.write_text(text, encoding="utf-8")
    with pytest.raises(StandardsGradeStorageIntegrityError):
        load_current_standards_grade_result(root, CLASS_ID, STUDENT_ID, PERIOD, 1)
