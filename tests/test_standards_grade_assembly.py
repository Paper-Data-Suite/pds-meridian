from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.standards_grade_assembly as assembly_module
from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultFreshness,
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
    grade_policy_revision_to_json_bytes,
)
from meridian.grade_policy_activation import (
    GradePolicyActivationDecision,
    grade_policy_activation_decision_to_json_bytes,
)
from meridian.grade_policy_activation_storage import (
    GradePolicyActivationResolution,
    StoredGradePolicyActivationDecision,
    grade_policy_activation_revision_relative_path,
)
from meridian.grade_policy_storage import (
    GradePolicyDependencies,
    StoredGradePolicyRevision,
    grade_policy_revision_relative_path,
)
from meridian.proficiency_mapping import (
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_to_json_bytes,
)
from meridian.proficiency_mapping_storage import StoredProficiencyScale
from meridian.standards_grade_assembly import (
    StandardsGradeAssemblyAuthorityError,
    assemble_standards_grade_calculation,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "s001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 13, 18, 0, tzinfo=UTC)


def state_treatment(*, missing: str = "blocking") -> GradeStateTreatment:
    return GradeStateTreatment(
        missing=missing,  # type: ignore[arg-type]
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
    )


def stored_basis(
    tmp_path: Path,
    *,
    minimum: int = 1,
    missing: str = "blocking",
) -> tuple[
    StoredGradePolicyRevision,
    StoredGradePolicyActivationDecision,
    StoredProficiencyScale,
]:
    scale = ProficiencyScale(
        schema_version="1",
        record_type="meridian_proficiency_scale",
        class_id=CLASS_ID,
        scale_id="course_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Course Scale",
        description="Synthetic course proficiency scale.",
        levels=(
            ProficiencyLevel("developing", 1, "Developing", "Developing."),
            ProficiencyLevel("proficient", 2, "Proficient", "Proficient."),
            ProficiencyLevel("advanced", 3, "Advanced", "Advanced."),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )
    scale_content = proficiency_scale_to_json_bytes(scale)
    scale_sha = hashlib.sha256(scale_content).hexdigest()
    stored_scale = StoredProficiencyScale(
        scale=scale,
        scale_sha256=scale_sha,
        path=tmp_path / "scale" / "1.json",
        relative_path=(
            "classes/synthetic_class_2026/modules/meridian/"
            "proficiency_scales/course_scale/revisions/1.json"
        ),
        content=scale_content,
    )

    configuration = StandardsBasedGradeConfiguration(
        target_scale=stored_scale.reference,
        standards=(
            StandardGradeParticipation("STD.A", Decimal("0.5")),
            StandardGradeParticipation("STD.B", Decimal("0.5")),
        ),
        conversions=(
            ProficiencyGradeConversion("developing", Decimal("70")),
            ProficiencyGradeConversion("proficient", Decimal("90")),
            ProficiencyGradeConversion("advanced", Decimal("110")),
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=minimum,
    )
    policy = GradePolicyRevision(
        schema_version="1",
        record_type="meridian_grade_policy",
        class_id=CLASS_ID,
        policy_id="course_grade_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Course Grade Policy",
        calculation_family="standards_based",
        configuration=configuration,
        state_treatment=state_treatment(missing=missing),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )
    policy_content = grade_policy_revision_to_json_bytes(policy)
    policy_sha = hashlib.sha256(policy_content).hexdigest()
    policy_path = tmp_path / "policy" / "1.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    stored_policy = StoredGradePolicyRevision(
        policy=policy,
        policy_sha256=policy_sha,
        path=policy_path,
        relative_path=grade_policy_revision_relative_path(
            CLASS_ID,
            policy.policy_id,
            1,
        ),
        content=policy_content,
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
    activation_content = grade_policy_activation_decision_to_json_bytes(activation)
    activation_sha = hashlib.sha256(activation_content).hexdigest()
    activation_path = tmp_path / "activation" / "1.json"
    activation_path.parent.mkdir(parents=True, exist_ok=True)
    stored_activation = StoredGradePolicyActivationDecision(
        decision=activation,
        activation_sha256=activation_sha,
        path=activation_path,
        relative_path=grade_policy_activation_revision_relative_path(
            CLASS_ID,
            PERIOD,
            1,
        ),
        content=activation_content,
    )
    return stored_policy, stored_activation, stored_scale


def selected_result(
    standard_id: str,
    scale_ref: object,
    *,
    level_id: str | None = "proficient",
    status: str = "calculated",
    calendar_revision: int = 1,
) -> SimpleNamespace:
    reference = AcademicPeriodProficiencyResultReference(
        class_id=CLASS_ID,
        school_year=PERIOD.school_year,
        period_id=PERIOD.period_id,
        student_id=STUDENT_ID,
        standard_id=standard_id,
        result_revision=1,
        result_sha256=("a" if standard_id.endswith("A") else "b") * 64,
    )
    snapshot = SimpleNamespace(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        standard_id=standard_id,
        target_period=SimpleNamespace(
            period=PERIOD,
            calendar_revision=calendar_revision,
        ),
        target_scale=scale_ref,
        calculation_fingerprint=("c" if standard_id.endswith("A") else "d") * 64,
        algorithm_version="1",
        outcome=SimpleNamespace(
            status=status,
            proficiency_level_id=level_id,
        ),
    )
    return SimpleNamespace(snapshot=snapshot, reference=reference)


def install_basis(
    monkeypatch: pytest.MonkeyPatch,
    stored_policy: StoredGradePolicyRevision,
    stored_activation: StoredGradePolicyActivationDecision,
    stored_scale: StoredProficiencyScale,
    results: dict[str, object | None],
    *,
    freshness: AcademicPeriodProficiencyResultFreshness | None = None,
) -> None:
    resolution = GradePolicyActivationResolution(
        "activated",
        stored_activation,
        stored_policy.reference,
    )
    monkeypatch.setattr(
        assembly_module,
        "resolve_grade_policy_activation",
        lambda *_args: resolution,
    )
    monkeypatch.setattr(
        assembly_module,
        "load_grade_policy_revision",
        lambda *_args: stored_policy,
    )
    monkeypatch.setattr(
        assembly_module,
        "validate_grade_policy_dependencies",
        lambda *_args: GradePolicyDependencies((), stored_scale, ()),
    )
    monkeypatch.setattr(
        assembly_module,
        "load_current_academic_period_proficiency_result",
        lambda *_args: results.get(_args[-1]),
    )
    resolved_freshness = freshness or AcademicPeriodProficiencyResultFreshness(
        "current",
        (),
    )
    monkeypatch.setattr(
        assembly_module,
        "assess_selected_academic_period_proficiency_result_freshness",
        lambda *_args: resolved_freshness,
    )


def test_assembly_consumes_selected_current_proficiency_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, activation, scale = stored_basis(tmp_path)
    install_basis(
        monkeypatch,
        policy,
        activation,
        scale,
        {
            "STD.A": selected_result("STD.A", scale.reference, level_id="proficient"),
            "STD.B": selected_result("STD.B", scale.reference, level_id="advanced"),
        },
    )

    assembled = assemble_standards_grade_calculation(
        tmp_path,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    )

    assert assembled.outcome.status == "calculated"
    assert assembled.outcome.unrounded_grade == Decimal("100")
    assert assembled.outcome.rounded_grade == Decimal("100.00")
    assert assembled.outcome.actual_calculated_result_count == 2
    assert tuple(item.status for item in assembled.standards) == (
        "calculated",
        "calculated",
    )


def test_missing_selected_result_is_explicit_policy_zero_but_not_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, activation, scale = stored_basis(tmp_path, minimum=1, missing="zero")
    install_basis(
        monkeypatch,
        policy,
        activation,
        scale,
        {
            "STD.A": selected_result("STD.A", scale.reference, level_id="proficient"),
            "STD.B": None,
        },
    )

    assembled = assemble_standards_grade_calculation(
        tmp_path,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    )

    assert assembled.outcome.status == "calculated"
    assert assembled.outcome.actual_calculated_result_count == 1
    assert assembled.outcome.rounded_grade == Decimal("45.00")
    by_standard = {
        item.standard_id: item for item in assembled.outcome.standard_results
    }
    assert by_standard["STD.B"].source_state == "missing"
    assert by_standard["STD.B"].action == "zero"


def test_stale_selected_result_fails_closed_as_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, activation, scale = stored_basis(tmp_path)
    install_basis(
        monkeypatch,
        policy,
        activation,
        scale,
        {
            "STD.A": selected_result("STD.A", scale.reference),
            "STD.B": selected_result("STD.B", scale.reference),
        },
        freshness=AcademicPeriodProficiencyResultFreshness(
            "stale",
            ("inputs_changed",),
        ),
    )

    assembled = assemble_standards_grade_calculation(
        tmp_path,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    )

    assert assembled.outcome.status == "blocked"
    assert all(item.status == "unresolved" for item in assembled.standards)
    assert all(
        "upstream_inputs_changed" in item.reason_codes
        for item in assembled.standards
    )


def test_scale_mismatch_is_unresolved_not_converted_by_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, activation, scale = stored_basis(tmp_path)
    wrong_scale = type(scale.reference)(
        CLASS_ID,
        "other_scale",
        1,
        "e" * 64,
    )
    install_basis(
        monkeypatch,
        policy,
        activation,
        scale,
        {
            "STD.A": selected_result("STD.A", wrong_scale),
            "STD.B": selected_result("STD.B", scale.reference),
        },
    )

    assembled = assemble_standards_grade_calculation(
        tmp_path,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    )

    assert assembled.outcome.status == "blocked"
    first = next(
        item
        for item in assembled.standards
        if item.participation.standard_id == "STD.A"
    )
    assert first.status == "unresolved"
    assert first.reason_codes == ("proficiency_scale_mismatch",)


def test_calendar_scope_mismatch_is_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, activation, scale = stored_basis(tmp_path)
    install_basis(
        monkeypatch,
        policy,
        activation,
        scale,
        {
            "STD.A": selected_result(
                "STD.A",
                scale.reference,
                calendar_revision=2,
            ),
            "STD.B": selected_result("STD.B", scale.reference),
        },
    )

    assembled = assemble_standards_grade_calculation(
        tmp_path,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    )

    assert assembled.outcome.status == "blocked"
    first = next(
        item
        for item in assembled.standards
        if item.participation.standard_id == "STD.A"
    )
    assert first.status == "unresolved"
    assert first.reason_codes == ("calendar_scope_mismatch",)


def test_upstream_insufficient_evidence_remains_nonnumeric(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, activation, scale = stored_basis(tmp_path)
    install_basis(
        monkeypatch,
        policy,
        activation,
        scale,
        {
            "STD.A": selected_result(
                "STD.A",
                scale.reference,
                level_id=None,
                status="insufficient_evidence",
            ),
            "STD.B": selected_result("STD.B", scale.reference),
        },
    )

    assembled = assemble_standards_grade_calculation(
        tmp_path,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    )

    assert assembled.outcome.status == "blocked"
    first = next(
        item
        for item in assembled.standards
        if item.participation.standard_id == "STD.A"
    )
    assert first.status == "insufficient_evidence"
    assert first.proficiency_level_id is None


def test_unconfigured_activation_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        assembly_module,
        "resolve_grade_policy_activation",
        lambda *_args: GradePolicyActivationResolution("unconfigured", None, None),
    )

    with pytest.raises(StandardsGradeAssemblyAuthorityError):
        assemble_standards_grade_calculation(
            tmp_path,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
        )
