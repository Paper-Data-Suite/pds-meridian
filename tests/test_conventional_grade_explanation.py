from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.conventional_grade_explanation as explanation
from meridian.conventional_grade import (
    ConventionalGradeItemInput,
    ConventionalGradeProvenanceReference,
    calculate_conventional_grade,
    conventional_grade_result_reference,
    create_conventional_grade_calculation_input,
    create_conventional_grade_result_snapshot,
)
from meridian.effective_grade import EffectiveGradeResolution
from meridian.grade_item_storage import GradeItemStorageIntegrityError
from meridian.grade_items import (
    GRADE_ITEM_RECORD_TYPE,
    GRADE_ITEM_SCHEMA_VERSION,
    GradeItemRevision,
)
from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyCategory,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    grade_policy_reference,
)
from meridian.grade_policy_activation import (
    GRADE_POLICY_ACTIVATION_RECORD_TYPE,
    GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
    GradePolicyActivationDecision,
)
from meridian.grade_preview_explanation import GradePreviewIntegrityError
from meridian.teacher_grade_override import GradeOverrideSourceResultReference

CLASS_ID = "english_12"
STUDENT_ID = "student_001"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 9, 18, 20, 0, tzinfo=UTC)


def _item_ref(item_id: str, digit: str) -> GradePolicyItemReference:
    return GradePolicyItemReference(
        class_id=CLASS_ID,
        grade_item_id=item_id,
        grade_item_revision=1,
        grade_item_revision_sha256=digit * 64,
    )


def _treatment(*, missing: str = "exclude") -> GradeStateTreatment:
    return GradeStateTreatment(
        missing=missing,  # type: ignore[arg-type]
        pending="exclude",
        incomplete="exclude",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="exclude",
        unavailable="exclude",
        withdrawn="exclude",
        invalid="exclude",
        unresolved="exclude",
    )


def _policy(
    configuration: ConventionalGradeConfiguration,
    *,
    missing: str = "exclude",
) -> GradePolicyRevision:
    return GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="course_grade",
        policy_revision=1,
        supersedes_revision=None,
        title="Quarter 1 conventional Grade",
        calculation_family="conventional",
        configuration=configuration,
        state_treatment=_treatment(missing=missing),
        reassessment_handling=GradeReassessmentHandling(
            selection_authority="v02_attempt_and_reassessment_state",
            unresolved_handling="exclude",
        ),
        rounding=GradeRoundingPolicy(
            quantum=Decimal("0.01"),
            mode="half_up",
            application_stage="final",
        ),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Quarter policy.",
        revised_at=NOW,
    )


def _activation(policy: GradePolicyRevision) -> GradePolicyActivationDecision:
    return GradePolicyActivationDecision(
        schema_version=GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
        record_type=GRADE_POLICY_ACTIVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=grade_policy_reference(policy),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Use this policy for Q1.",
        decided_at=NOW,
    )


def _input(
    participation: GradePolicyItemParticipation,
    *,
    state: str = "points",
    earned: str | None = None,
    possible: str | None = None,
    provenance: tuple[ConventionalGradeProvenanceReference, ...] = (),
) -> ConventionalGradeItemInput:
    return ConventionalGradeItemInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status=state,  # type: ignore[arg-type]
        earned=Decimal(earned) if earned is not None else None,
        possible=Decimal(possible) if possible is not None else None,
        reason_codes=("source_marked_missing",) if state == "missing" else (),
        provenance=provenance,
    )


def _snapshot(
    policy: GradePolicyRevision,
    *items: ConventionalGradeItemInput,
):
    activation = _activation(policy)
    basis = create_conventional_grade_calculation_input(
        policy=policy,
        activation=activation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        items=tuple(items),
    )
    outcome = calculate_conventional_grade(basis)
    snapshot = create_conventional_grade_result_snapshot(
        basis,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )
    return snapshot, activation


def _effective(snapshot) -> EffectiveGradeResolution:
    reference = GradeOverrideSourceResultReference(
        "conventional",
        conventional_grade_result_reference(snapshot),
    )
    calculated = snapshot.outcome.status == "calculated"
    return EffectiveGradeResolution(
        base_result_family="conventional",
        base_result_reference=reference,
        base_result_status=snapshot.outcome.status,
        base_grade=snapshot.outcome.rounded_grade,
        base_freshness_status="current",
        base_freshness_reasons=(),
        selected_override_reference=None,
        override_decision=None,
        override_applicability="no_override",
        override_reasons=("no_selected_override",),
        effective_grade=snapshot.outcome.rounded_grade if calculated else None,
        effective_source="base" if calculated else "none",
    )


def _grade_item_revision(reference: GradePolicyItemReference) -> GradeItemRevision:
    return GradeItemRevision(
        schema_version=GRADE_ITEM_SCHEMA_VERSION,
        record_type=GRADE_ITEM_RECORD_TYPE,
        class_id=reference.class_id,
        grade_item_id=reference.grade_item_id,
        grade_item_revision=reference.grade_item_revision,
        supersedes_revision=None,
        title=f"Title for {reference.grade_item_id}",
        purpose="conventional_grade",
        status="active",
        weighting=None,
        created_at=NOW,
        revised_at=NOW,
    )


def _install_grade_item_loader(
    monkeypatch: pytest.MonkeyPatch,
    *references: GradePolicyItemReference,
) -> None:
    by_id = {reference.grade_item_id: reference for reference in references}

    def load(
        workspace_root: object,
        class_id: str,
        grade_item_id: str,
        grade_item_revision: int,
    ) -> SimpleNamespace:
        del workspace_root
        reference = by_id[grade_item_id]
        assert class_id == reference.class_id
        assert grade_item_revision == reference.grade_item_revision
        return SimpleNamespace(
            revision=_grade_item_revision(reference),
            revision_sha256=reference.grade_item_revision_sha256,
        )

    monkeypatch.setattr(explanation, "load_grade_item_revision", load)


def test_total_points_explains_items_formula_and_recorded_provenance(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    essay_ref = _item_ref("essay", "1")
    quiz_ref = _item_ref("quiz", "2")
    essay = GradePolicyItemParticipation(
        essay_ref,
        None,
        None,
        Decimal("10"),
    )
    quiz = GradePolicyItemParticipation(
        quiz_ref,
        None,
        None,
        Decimal("20"),
    )
    policy = _policy(
        ConventionalGradeConfiguration("total_points", (essay, quiz), ())
    )
    source = ConventionalGradeProvenanceReference(
        "source",
        "opaque:publication:cache:item",
        "a" * 64,
    )
    membership = ConventionalGradeProvenanceReference(
        "membership",
        "opaque:membership:key",
        "b" * 64,
    )
    snapshot, activation = _snapshot(
        policy,
        _input(
            essay,
            earned="8",
            possible="10",
            provenance=(source, membership),
        ),
        _input(quiz, earned="15", possible="20"),
    )
    _install_grade_item_loader(monkeypatch, essay_ref, quiz_ref)

    result = explanation.explain_conventional_grade_preview(
        tmp_path,
        snapshot,
        policy=policy,
        activation=activation,
        effective=_effective(snapshot),
    )

    assert result.mode == "total_points"
    assert result.formula.total_earned == Decimal("23")
    assert result.formula.total_possible == Decimal("30")
    assert result.formula.unrounded_grade == Decimal("23") / Decimal("30") * 100
    assert result.formula.rounded_grade == Decimal("76.67")
    assert [item.grade_item.title for item in result.items] == [
        "Title for essay",
        "Title for quiz",
    ]
    assert result.items[0].source_state == "points"
    assert result.items[0].action == "contribute"
    assert result.items[0].earned == Decimal("8")
    assert result.items[0].possible == Decimal("10")
    assert result.items[0].percentage == Decimal("80")
    assert result.items[0].provenance[0].reference_key == (
        "opaque:membership:key"
    )
    assert {item.kind for item in result.items[0].provenance} == {
        "source",
        "membership",
    }


def test_weighted_items_explains_policy_zero_as_zero_not_missing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    essay_ref = _item_ref("essay", "1")
    quiz_ref = _item_ref("quiz", "2")
    essay = GradePolicyItemParticipation(
        essay_ref,
        None,
        Decimal("0.75"),
        None,
    )
    quiz = GradePolicyItemParticipation(
        quiz_ref,
        None,
        Decimal("0.25"),
        None,
    )
    policy = _policy(
        ConventionalGradeConfiguration("weighted_items", (essay, quiz), ()),
        missing="zero",
    )
    snapshot, activation = _snapshot(
        policy,
        _input(essay, earned="9", possible="10"),
        _input(quiz, state="missing"),
    )
    _install_grade_item_loader(monkeypatch, essay_ref, quiz_ref)

    result = explanation.explain_conventional_grade_preview(
        tmp_path,
        snapshot,
        policy=policy,
        activation=activation,
        effective=_effective(snapshot),
    )

    by_id = {
        item.grade_item.reference.grade_item_id: item for item in result.items
    }
    assert by_id["quiz"].source_state == "missing"
    assert by_id["quiz"].action == "zero"
    assert by_id["quiz"].percentage == Decimal("0")
    assert by_id["quiz"].contribution == Decimal("0")
    assert by_id["quiz"].reason_codes == ("source_marked_missing",)
    assert result.formula.rounded_grade == Decimal("67.50")


def test_weighted_categories_explains_category_titles_weights_and_contributions(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    practice_ref = _item_ref("practice", "1")
    exam_ref = _item_ref("exam", "2")
    practice = GradePolicyItemParticipation(
        practice_ref,
        "practice",
        None,
        Decimal("10"),
    )
    exam = GradePolicyItemParticipation(
        exam_ref,
        "assessment",
        None,
        Decimal("100"),
    )
    policy = _policy(
        ConventionalGradeConfiguration(
            "weighted_categories",
            (practice, exam),
            (
                GradePolicyCategory("practice", "Practice", Decimal("0.4")),
                GradePolicyCategory(
                    "assessment",
                    "Assessments",
                    Decimal("0.6"),
                ),
            ),
        )
    )
    snapshot, activation = _snapshot(
        policy,
        _input(practice, earned="8", possible="10"),
        _input(exam, earned="90", possible="100"),
    )
    _install_grade_item_loader(monkeypatch, practice_ref, exam_ref)

    result = explanation.explain_conventional_grade_preview(
        tmp_path,
        snapshot,
        policy=policy,
        activation=activation,
        effective=_effective(snapshot),
    )

    categories = {item.category_id: item for item in result.categories}
    assert categories["practice"].title == "Practice"
    assert categories["practice"].weight == Decimal("0.4")
    assert categories["practice"].fraction == Decimal("0.8")
    assert categories["practice"].contribution == Decimal("0.32")
    assert categories["assessment"].title == "Assessments"
    assert categories["assessment"].contribution == Decimal("0.54")
    assert result.formula.rounded_grade == Decimal("86.00")


def test_blocking_missing_state_remains_nonnumeric_and_explainable(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_ref = _item_ref("essay", "1")
    item = GradePolicyItemParticipation(
        item_ref,
        None,
        None,
        Decimal("10"),
    )
    policy = _policy(
        ConventionalGradeConfiguration("total_points", (item,), ()),
        missing="blocking",
    )
    snapshot, activation = _snapshot(policy, _input(item, state="missing"))
    _install_grade_item_loader(monkeypatch, item_ref)

    result = explanation.explain_conventional_grade_preview(
        tmp_path,
        snapshot,
        policy=policy,
        activation=activation,
        effective=_effective(snapshot),
    )

    assert result.common.base_result_status == "blocked"
    assert result.common.base_grade is None
    assert result.common.effective_grade is None
    assert result.items[0].source_state == "missing"
    assert result.items[0].action == "blocking"
    assert result.formula.unrounded_grade is None
    assert result.formula.rounded_grade is None
    assert result.reasons[0].code == "blocking_item"


def test_exact_grade_item_digest_mismatch_fails_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_ref = _item_ref("essay", "1")
    item = GradePolicyItemParticipation(
        item_ref,
        None,
        None,
        Decimal("10"),
    )
    policy = _policy(ConventionalGradeConfiguration("total_points", (item,), ()))
    snapshot, activation = _snapshot(
        policy,
        _input(item, earned="8", possible="10"),
    )

    monkeypatch.setattr(
        explanation,
        "load_grade_item_revision",
        lambda *args, **kwargs: SimpleNamespace(
            revision=_grade_item_revision(item_ref),
            revision_sha256="f" * 64,
        ),
    )

    with pytest.raises(GradePreviewIntegrityError, match="digest"):
        explanation.explain_conventional_grade_preview(
            tmp_path,
            snapshot,
            policy=policy,
            activation=activation,
            effective=_effective(snapshot),
        )


def test_grade_item_storage_corruption_fails_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_ref = _item_ref("essay", "1")
    item = GradePolicyItemParticipation(
        item_ref,
        None,
        None,
        Decimal("10"),
    )
    policy = _policy(ConventionalGradeConfiguration("total_points", (item,), ()))
    snapshot, activation = _snapshot(
        policy,
        _input(item, earned="8", possible="10"),
    )

    def corrupt(*args: object, **kwargs: object) -> None:
        raise GradeItemStorageIntegrityError("corrupt exact Grade Item")

    monkeypatch.setattr(explanation, "load_grade_item_revision", corrupt)

    with pytest.raises(GradePreviewIntegrityError, match="could not be verified"):
        explanation.explain_conventional_grade_preview(
            tmp_path,
            snapshot,
            policy=policy,
            activation=activation,
            effective=_effective(snapshot),
        )


def test_conventional_observation_adds_deterministic_privacy_minimized_basis(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_ref = _item_ref("essay", "1")
    item = GradePolicyItemParticipation(
        item_ref,
        None,
        None,
        Decimal("10"),
    )
    policy = _policy(ConventionalGradeConfiguration("total_points", (item,), ()))
    snapshot, activation = _snapshot(
        policy,
        _input(
            item,
            earned="8",
            possible="10",
            provenance=(
                ConventionalGradeProvenanceReference(
                    "source",
                    "sensitive:opaque:source:key",
                    "a" * 64,
                ),
            ),
        ),
    )
    _install_grade_item_loader(monkeypatch, item_ref)
    result = explanation.explain_conventional_grade_preview(
        tmp_path,
        snapshot,
        policy=policy,
        activation=activation,
        effective=_effective(snapshot),
    )

    first = explanation.conventional_grade_observation(result)
    second = explanation.conventional_grade_observation(result)
    entries = {(entry.dimension, entry.key): entry for entry in first.basis_entries}

    assert first == second
    assert ("formula", "conventional_formula") in entries
    assert ("participation", "conventional_participation") in entries
    assert ("evidence", "conventional_evidence_basis") in entries
    assert ("weighting", "conventional_weighting") in entries
    assert all(len(entry.sha256) == 64 for entry in first.basis_entries)
    serialized = str(first)
    assert "sensitive:opaque:source:key" not in serialized


def test_conventional_serialization_preserves_decimal_text_and_exact_item_reference(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_ref = _item_ref("essay", "1")
    item = GradePolicyItemParticipation(
        item_ref,
        None,
        None,
        Decimal("3"),
    )
    policy = _policy(ConventionalGradeConfiguration("total_points", (item,), ()))
    snapshot, activation = _snapshot(
        policy,
        _input(item, earned="2", possible="3"),
    )
    _install_grade_item_loader(monkeypatch, item_ref)
    result = explanation.explain_conventional_grade_preview(
        tmp_path,
        snapshot,
        policy=policy,
        activation=activation,
        effective=_effective(snapshot),
    )

    data = explanation.conventional_grade_preview_explanation_to_dict(result)
    item_data = data["items"][0]  # type: ignore[index]
    formula = data["formula"]  # type: ignore[assignment]

    assert item_data["grade_item"]["reference"]["grade_item_id"] == "essay"
    assert item_data["earned"] == "2"
    assert item_data["possible"] == "3"
    assert formula["rounded_grade"] == "66.67"
