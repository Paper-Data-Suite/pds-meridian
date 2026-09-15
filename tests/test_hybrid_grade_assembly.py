from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.routing_models import ModuleWorkRef

import meridian.conventional_grade_assembly as conventional_assembly
import meridian.hybrid_grade_assembly as hybrid_assembly
import meridian.standards_grade_assembly as standards_assembly
from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
)
from meridian.conventional_grade import (
    ConventionalGradeCalculationInput,
    ConventionalGradeItemInput,
    calculate_conventional_grade,
)
from meridian.conventional_grade_assembly import (
    ConventionalGradeComponentAssembly,
    ConventionalGradeWorkEvidenceSpec,
    assemble_conventional_grade_component,
)
from meridian.grade_policy import (
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
    HybridGradeConfiguration,
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
from meridian.hybrid_grade_assembly import (
    HybridGradeAssemblyAuthorityError,
    assemble_hybrid_grade_calculation,
)
from meridian.proficiency_mapping import (
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_to_json_bytes,
)
from meridian.proficiency_mapping_storage import StoredProficiencyScale
from meridian.standards_grade import (
    StandardsGradeCalculationInput,
    StandardsGradeStandardInput,
    calculate_standards_grade,
)
from meridian.standards_grade_assembly import (
    StandardsGradeComponentAssembly,
    assemble_standards_grade_component,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "student_001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 15, 1, 30, tzinfo=UTC)
GRADE_ITEM_SHA = "a" * 64
RESULT_SHA = "b" * 64
RESULT_FINGERPRINT = "c" * 64


def _treatment(*, insufficient: str = "exclude") -> GradeStateTreatment:
    return GradeStateTreatment(
        missing="blocking",
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence=insufficient,  # type: ignore[arg-type]
        unavailable="blocking",
        withdrawn="exclude",
        invalid="blocking",
        unresolved="blocking",
    )


def _stored_basis(
    tmp_path: Path,
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
        description="Synthetic hybrid scale.",
        levels=(
            ProficiencyLevel("developing", 1, "Developing", "Developing."),
            ProficiencyLevel("proficient", 2, "Proficient", "Proficient."),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )
    scale_content = proficiency_scale_to_json_bytes(scale)
    stored_scale = StoredProficiencyScale(
        scale=scale,
        scale_sha256=hashlib.sha256(scale_content).hexdigest(),
        path=tmp_path / "scale" / "1.json",
        relative_path=(
            "classes/synthetic_class_2026/modules/meridian/"
            "proficiency_scales/course_scale/revisions/1.json"
        ),
        content=scale_content,
    )

    item = GradePolicyItemParticipation(
        grade_item=GradePolicyItemReference(
            CLASS_ID,
            "quiz_001",
            1,
            GRADE_ITEM_SHA,
        ),
        category_id=None,
        weight=None,
        possible_points=Decimal("100"),
    )
    conventional = ConventionalGradeConfiguration("total_points", (item,), ())
    standards = StandardsBasedGradeConfiguration(
        target_scale=stored_scale.reference,
        standards=(StandardGradeParticipation("STD.A", Decimal("1")),),
        conversions=(
            ProficiencyGradeConversion("developing", Decimal("80")),
            ProficiencyGradeConversion("proficient", Decimal("90")),
        ),
        aggregation_strategy="weighted_mean",
        minimum_calculated_results=1,
    )
    configuration = HybridGradeConfiguration(
        conventional=conventional,
        standards_based=standards,
        conventional_weight=Decimal("0.7"),
        standards_weight=Decimal("0.3"),
    )
    policy = GradePolicyRevision(
        schema_version="1",
        record_type="meridian_grade_policy",
        class_id=CLASS_ID,
        policy_id="hybrid_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Hybrid Policy",
        calculation_family="hybrid",
        configuration=configuration,
        state_treatment=_treatment(),
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
    stored_policy = StoredGradePolicyRevision(
        policy=policy,
        policy_sha256=hashlib.sha256(policy_content).hexdigest(),
        path=tmp_path / "policy" / "1.json",
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
    stored_activation = StoredGradePolicyActivationDecision(
        decision=activation,
        activation_sha256=hashlib.sha256(activation_content).hexdigest(),
        path=tmp_path / "activation" / "1.json",
        relative_path=grade_policy_activation_revision_relative_path(
            CLASS_ID,
            PERIOD,
            1,
        ),
        content=activation_content,
    )
    return stored_policy, stored_activation, stored_scale


def _conventional_input(
    stored_policy: StoredGradePolicyRevision,
    stored_activation: StoredGradePolicyActivationDecision,
    earned: str = "90",
) -> ConventionalGradeCalculationInput:
    config = stored_policy.policy.configuration
    assert isinstance(config, HybridGradeConfiguration)
    participation = config.conventional.items[0]
    item = ConventionalGradeItemInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status="points",
        earned=Decimal(earned),
        possible=Decimal("100"),
    )
    return ConventionalGradeCalculationInput(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_reference=stored_activation.reference,
        policy_reference=stored_policy.reference,
        configuration=config.conventional,
        state_treatment=stored_policy.policy.state_treatment,
        rounding=stored_policy.policy.rounding,
        items=(item,),
    )


def _standards_input(
    stored_policy: StoredGradePolicyRevision,
    stored_activation: StoredGradePolicyActivationDecision,
    level: str = "developing",
) -> StandardsGradeCalculationInput:
    config = stored_policy.policy.configuration
    assert isinstance(config, HybridGradeConfiguration)
    participation = config.standards_based.standards[0]
    selected = StandardsGradeStandardInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status="calculated",
        result_reference=AcademicPeriodProficiencyResultReference(
            CLASS_ID,
            PERIOD.school_year,
            PERIOD.period_id,
            STUDENT_ID,
            participation.standard_id,
            1,
            RESULT_SHA,
        ),
        result_calculation_fingerprint=RESULT_FINGERPRINT,
        result_algorithm_version="1",
        proficiency_level_id=level,
        target_scale=config.standards_based.target_scale,
        freshness_status="current",
    )
    return StandardsGradeCalculationInput(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_reference=stored_activation.reference,
        policy_reference=stored_policy.reference,
        configuration=config.standards_based,
        state_treatment=stored_policy.policy.state_treatment,
        rounding=stored_policy.policy.rounding,
        standards=(selected,),
    )


def test_conventional_component_accepts_exact_embedded_hybrid_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, activation, _scale = _stored_basis(tmp_path)
    config = policy.policy.configuration
    assert isinstance(config, HybridGradeConfiguration)
    participation = config.conventional.items[0]
    work = ModuleWorkRef(
        module_id="scoreform",
        class_id=CLASS_ID,
        work_id="work_001",
    )
    spec = ConventionalGradeWorkEvidenceSpec("quiz_001", work, "missing")

    monkeypatch.setattr(
        conventional_assembly,
        "_verify_policy_grade_item",
        lambda *_: None,
    )
    monkeypatch.setattr(
        conventional_assembly,
        "_assemble_policy_item",
        lambda **_: ConventionalGradeItemInput(
            participation=participation,
            student_id=STUDENT_ID,
            target_period=PERIOD,
            calendar_revision=1,
            status="points",
            earned=Decimal("90"),
            possible=Decimal("100"),
        ),
    )

    component = assemble_conventional_grade_component(
        tmp_path,
        activation=activation,
        policy=policy,
        configuration=config.conventional,
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        work_evidence=(spec,),
    )
    assert component.outcome.status == "calculated"
    assert component.outcome.unrounded_grade == Decimal("90")
    assert component.inputs.policy_reference == policy.reference
    assert component.inputs.activation_reference == activation.reference


def test_standards_component_accepts_exact_embedded_hybrid_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, activation, scale = _stored_basis(tmp_path)
    config = policy.policy.configuration
    assert isinstance(config, HybridGradeConfiguration)
    participation = config.standards_based.standards[0]

    monkeypatch.setattr(
        standards_assembly,
        "validate_grade_policy_dependencies",
        lambda *_: GradePolicyDependencies(
            grade_items=(),
            target_scale=scale,
            standards=(),
        ),
    )
    monkeypatch.setattr(
        standards_assembly,
        "_assemble_standard_input",
        lambda *_: _standards_input(policy, activation).standards[0],
    )

    component = assemble_standards_grade_component(
        tmp_path,
        activation=activation,
        policy=policy,
        configuration=config.standards_based,
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
    )
    assert component.outcome.status == "calculated"
    assert component.outcome.unrounded_grade == Decimal("80")
    assert component.standards[0].participation == participation
    assert component.target_scale.reference == config.standards_based.target_scale


def test_hybrid_assembly_resolves_one_authority_and_composes_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, activation, scale = _stored_basis(tmp_path)
    conventional_input = _conventional_input(policy, activation, "90")
    standards_input = _standards_input(policy, activation, "developing")
    conventional = ConventionalGradeComponentAssembly(
        work_evidence=(),
        inputs=conventional_input,
        outcome=calculate_conventional_grade(conventional_input),
    )
    standards = StandardsGradeComponentAssembly(
        target_scale=scale,
        standards=standards_input.standards,
        inputs=standards_input,
        outcome=calculate_standards_grade(standards_input),
    )
    calls = {"activation": 0, "policy": 0}

    def resolve(*_args: object) -> GradePolicyActivationResolution:
        calls["activation"] += 1
        return GradePolicyActivationResolution(
            "activated",
            activation,
            policy.reference,
        )

    def load(*_args: object) -> StoredGradePolicyRevision:
        calls["policy"] += 1
        return policy

    monkeypatch.setattr(hybrid_assembly, "resolve_grade_policy_activation", resolve)
    monkeypatch.setattr(hybrid_assembly, "load_grade_policy_revision", load)
    monkeypatch.setattr(
        hybrid_assembly,
        "assemble_conventional_grade_component",
        lambda *_args, **_kwargs: conventional,
    )
    monkeypatch.setattr(
        hybrid_assembly,
        "assemble_standards_grade_component",
        lambda *_args, **_kwargs: standards,
    )

    assembled = assemble_hybrid_grade_calculation(
        tmp_path,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        (),
    )
    assert calls == {"activation": 1, "policy": 1}
    assert assembled.outcome.status == "calculated"
    assert assembled.outcome.weighted_numerator == Decimal("87.0")
    assert assembled.outcome.unrounded_grade == Decimal("87")
    assert assembled.outcome.rounded_grade == Decimal("87.00")
    assert assembled.inputs.conventional == conventional_input
    assert assembled.inputs.standards_based == standards_input


def test_hybrid_assembly_rejects_nonhybrid_activated_policy_before_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hybrid_policy, _hybrid_activation, _scale = _stored_basis(tmp_path)
    config = hybrid_policy.policy.configuration
    assert isinstance(config, HybridGradeConfiguration)
    conventional_policy = GradePolicyRevision(
        schema_version="1",
        record_type="meridian_grade_policy",
        class_id=CLASS_ID,
        policy_id="conventional_only",
        policy_revision=1,
        supersedes_revision=None,
        title="Conventional",
        calculation_family="conventional",
        configuration=config.conventional,
        state_treatment=hybrid_policy.policy.state_treatment,
        reassessment_handling=hybrid_policy.policy.reassessment_handling,
        rounding=hybrid_policy.policy.rounding,
        actor=hybrid_policy.policy.actor,
        rationale=None,
        revised_at=NOW,
    )
    content = grade_policy_revision_to_json_bytes(conventional_policy)
    stored_policy = StoredGradePolicyRevision(
        policy=conventional_policy,
        policy_sha256=hashlib.sha256(content).hexdigest(),
        path=tmp_path / "conventional" / "1.json",
        relative_path=grade_policy_revision_relative_path(
            CLASS_ID,
            conventional_policy.policy_id,
            1,
        ),
        content=content,
    )
    decision = GradePolicyActivationDecision(
        schema_version="1",
        record_type="meridian_grade_policy_activation",
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=stored_policy.reference,
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        decided_at=NOW,
    )
    activation_content = grade_policy_activation_decision_to_json_bytes(decision)
    stored_activation = StoredGradePolicyActivationDecision(
        decision=decision,
        activation_sha256=hashlib.sha256(activation_content).hexdigest(),
        path=tmp_path / "activation2" / "1.json",
        relative_path=grade_policy_activation_revision_relative_path(
            CLASS_ID,
            PERIOD,
            1,
        ),
        content=activation_content,
    )
    monkeypatch.setattr(
        hybrid_assembly,
        "resolve_grade_policy_activation",
        lambda *_: GradePolicyActivationResolution(
            "activated",
            stored_activation,
            stored_policy.reference,
        ),
    )
    monkeypatch.setattr(
        hybrid_assembly,
        "load_grade_policy_revision",
        lambda *_: stored_policy,
    )

    with pytest.raises(HybridGradeAssemblyAuthorityError):
        assemble_hybrid_grade_calculation(
            tmp_path,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            (),
        )
