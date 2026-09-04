from __future__ import annotations

from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.academic_period_calculation_assembly_workflow as workflow
from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyAggregationPolicyReference,
)

CLASS_ID = "class_2026"
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"
POLICY_REF = AcademicPeriodProficiencyAggregationPolicyReference(
    class_id=CLASS_ID,
    policy_id="period_policy",
    policy_revision=2,
    policy_sha256="a" * 64,
)
WORK = ModuleWorkRef(
    module_id="scoreform",
    class_id=CLASS_ID,
    work_id="assessment_1",
)


def target() -> object:
    return SimpleNamespace(
        period=SimpleNamespace(
            school_year="2026-2027",
            period_id="mp1",
        ),
        calendar_revision=4,
    )


def spec(*, with_result: bool = True) -> object:
    return SimpleNamespace(
        grade_item_id="unit1",
        grade_item_revision=5,
        grade_item_revision_sha256="b" * 64,
        memberships=(
            SimpleNamespace(
                work=WORK,
                membership_revision=3,
                membership_sha256="c" * 64,
            ),
        ),
        result_revision=7 if with_result else None,
        result_sha256="d" * 64 if with_result else None,
        has_result=with_result,
    )


def install_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "AcademicPeriodProficiencyTarget",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "AcademicPeriodCalculationCandidateSpec",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "AcademicPeriodMembershipSpec",
        SimpleNamespace,
    )


def install_common(monkeypatch: pytest.MonkeyPatch) -> None:
    install_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_academic_period_proficiency_policy_revision",
        lambda *args, **kwargs: SimpleNamespace(
            policy=SimpleNamespace(
                target_scale=SimpleNamespace(),
                period_membership_scope="direct",
            ),
            policy_sha256=POLICY_REF.policy_sha256,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "load_academic_period_calendar_revision",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        workflow,
        "load_grade_item_revision",
        lambda *args, **kwargs: SimpleNamespace(
            revision=SimpleNamespace(),
            revision_sha256="b" * 64,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "load_grade_item_membership_revision",
        lambda *args, **kwargs: SimpleNamespace(
            decision=SimpleNamespace(
                grade_item_revision=5,
                grade_item_revision_sha256="b" * 64,
            ),
            decision_sha256="c" * 64,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "academic_period_proficiency_membership_basis_from_decision",
        lambda decision, digest: SimpleNamespace(
            decision=decision,
            digest=digest,
        ),
    )


def test_exact_candidate_basis_and_result_are_forwarded_to_canonical_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_common(monkeypatch)
    exact_result = SimpleNamespace(result_revision=7)
    monkeypatch.setattr(
        workflow,
        "load_standard_proficiency_result_revision",
        lambda *args, **kwargs: SimpleNamespace(
            snapshot=exact_result,
            result_sha256="d" * 64,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "GradeItemAggregationBasis",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        workflow,
        "ResolvedAcademicPeriodProficiencyCandidate",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    exact_inputs = SimpleNamespace()
    observed: dict[str, object] = {}

    def build_inputs(**kwargs: object) -> object:
        observed["inputs"] = kwargs
        return exact_inputs

    monkeypatch.setattr(
        workflow,
        "build_academic_period_proficiency_aggregation_inputs",
        build_inputs,
    )
    calculation = SimpleNamespace(
        result_write_performed=False,
        result_selection_performed=False,
    )
    monkeypatch.setattr(
        workflow,
        "build_academic_period_calculation_preview_projection",
        lambda *args, **kwargs: calculation,
    )

    result = workflow.build_bounded_academic_period_calculation_preview(
        "workspace",
        target(),
        STUDENT_ID,
        STANDARD_ID,
        (spec(),),
        POLICY_REF,
    )

    candidates = observed["inputs"]["candidates"]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.grade_item.grade_item_id == "unit1"
    assert candidate.grade_item.grade_item_revision == 5
    assert candidate.grade_item.grade_item_revision_sha256 == "b" * 64
    assert len(candidate.memberships) == 1
    assert candidate.result is exact_result
    assert result.inputs is exact_inputs
    assert result.candidate_count == 1
    assert result.grade_item_ids == ("unit1",)
    assert result.result_write_performed is False
    assert result.result_selection_performed is False


def test_missing_result_is_intentional_and_never_substituted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_common(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_standard_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail(
            "missing-result candidate must not load a current or latest #34 result"
        ),
    )
    monkeypatch.setattr(
        workflow,
        "GradeItemAggregationBasis",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        workflow,
        "ResolvedAcademicPeriodProficiencyCandidate",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    observed: list[object] = []

    def build_inputs(**kwargs: object) -> object:
        observed.extend(kwargs["candidates"])
        return SimpleNamespace()

    monkeypatch.setattr(
        workflow,
        "build_academic_period_proficiency_aggregation_inputs",
        build_inputs,
    )
    monkeypatch.setattr(
        workflow,
        "build_academic_period_calculation_preview_projection",
        lambda *args, **kwargs: SimpleNamespace(
            result_write_performed=False,
            result_selection_performed=False,
        ),
    )

    workflow.build_bounded_academic_period_calculation_preview(
        "workspace",
        target(),
        STUDENT_ID,
        STANDARD_ID,
        (spec(with_result=False),),
        POLICY_REF,
    )

    assert len(observed) == 1
    assert observed[0].result is None


def test_result_digest_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_common(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_standard_proficiency_result_revision",
        lambda *args, **kwargs: SimpleNamespace(
            snapshot=SimpleNamespace(),
            result_sha256="f" * 64,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "GradeItemAggregationBasis",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )

    with pytest.raises(
        workflow.AcademicPeriodCalculationAssemblyDependencyError,
        match="#34 result SHA-256",
    ):
        workflow.build_bounded_academic_period_calculation_preview(
            "workspace",
            target(),
            STUDENT_ID,
            STANDARD_ID,
            (spec(),),
            POLICY_REF,
        )


def test_membership_grade_item_basis_mismatch_fails_before_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_common(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_grade_item_membership_revision",
        lambda *args, **kwargs: SimpleNamespace(
            decision=SimpleNamespace(
                grade_item_revision=4,
                grade_item_revision_sha256="e" * 64,
            ),
            decision_sha256="c" * 64,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "GradeItemAggregationBasis",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        workflow,
        "build_academic_period_proficiency_aggregation_inputs",
        lambda *args, **kwargs: pytest.fail(
            "mismatched membership basis must fail before #35 builder"
        ),
    )

    with pytest.raises(
        workflow.AcademicPeriodCalculationAssemblyDependencyError,
        match="membership Grade Item basis",
    ):
        workflow.build_bounded_academic_period_calculation_preview(
            "workspace",
            target(),
            STUDENT_ID,
            STANDARD_ID,
            (spec(with_result=False),),
            POLICY_REF,
        )


def test_duplicate_grade_item_candidates_fail_before_storage_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_academic_period_proficiency_policy_revision",
        lambda *args, **kwargs: pytest.fail(
            "duplicate candidates must fail before storage access"
        ),
    )

    with pytest.raises(
        workflow.AcademicPeriodCalculationAssemblyScopeError,
        match="must not duplicate",
    ):
        workflow.build_bounded_academic_period_calculation_preview(
            "workspace",
            target(),
            STUDENT_ID,
            STANDARD_ID,
            (spec(), spec()),
            POLICY_REF,
        )


def test_result_revision_and_digest_must_be_paired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    broken = spec()
    broken.result_sha256 = None

    with pytest.raises(
        workflow.AcademicPeriodCalculationAssemblyScopeError,
        match="either both be supplied",
    ):
        workflow.build_bounded_academic_period_calculation_preview(
            "workspace",
            target(),
            STUDENT_ID,
            STANDARD_ID,
            (broken,),
            POLICY_REF,
        )
