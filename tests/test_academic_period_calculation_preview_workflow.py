from __future__ import annotations

from types import SimpleNamespace

import pytest

import meridian.academic_period_calculation_preview_workflow as workflow
from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyAggregationPolicyReference,
)

POLICY_REF = AcademicPeriodProficiencyAggregationPolicyReference(
    class_id="class_2026",
    policy_id="period_policy",
    policy_revision=2,
    policy_sha256="a" * 64,
)


def inputs() -> object:
    return SimpleNamespace(
        class_id="class_2026",
        target_period=SimpleNamespace(
            period=SimpleNamespace(
                school_year="2026-2027",
                period_id="mp1",
            ),
            calendar_revision=4,
        ),
        student_id="student_001",
        standard_id="NJSLSA.R1",
        target_scale=SimpleNamespace(
            class_id="class_2026",
            scale_id="four_level",
            scale_revision=3,
            scale_sha256="b" * 64,
        ),
        period_membership_scope="direct",
        entries=(
            SimpleNamespace(status="calculated"),
            SimpleNamespace(status="missing_result"),
            SimpleNamespace(status="period_scope_mismatch"),
        ),
    )


def policy() -> object:
    return SimpleNamespace(
        title="MP proficiency",
        target_scale=inputs().target_scale,
        strategy="median",
        period_membership_scope="direct",
        minimum_calculated_results=2,
        mode_tie_rule=None,
        median_even_rule="higher",
        missing_result_handling="blocking",
        insufficient_result_handling="noncontributing",
    )


def outcome() -> object:
    return SimpleNamespace(
        status="insufficient_evidence",
        proficiency_level_id=None,
        calculation_fingerprint="c" * 64,
        candidate_count=3,
        calculated_result_count=1,
        insufficient_result_count=0,
        missing_result_count=1,
        period_scope_mismatch_count=1,
        insufficiency_reasons=(),
        tie_resolution=None,
    )


def install_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "AcademicPeriodProficiencyAggregationInputs",
        SimpleNamespace,
    )


def install_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    install_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_academic_period_proficiency_policy_revision",
        lambda *args, **kwargs: SimpleNamespace(
            policy=policy(),
            policy_sha256=POLICY_REF.policy_sha256,
            reference=POLICY_REF,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "load_proficiency_scale_revision",
        lambda *args, **kwargs: SimpleNamespace(
            scale=SimpleNamespace(),
            scale_sha256="b" * 64,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "load_academic_period_calendar_revision",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        workflow,
        "get_academic_period",
        lambda *args, **kwargs: SimpleNamespace(label="Marking Period 1"),
    )
    monkeypatch.setattr(
        workflow,
        "calculate_academic_period_proficiency",
        lambda *args, **kwargs: outcome(),
    )
    monkeypatch.setattr(
        workflow,
        "list_academic_period_proficiency_result_revisions",
        lambda *args, **kwargs: (1, 2),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: 1,
    )
    monkeypatch.setattr(
        workflow,
        "academic_period_proficiency_aggregation_inputs_sha256",
        lambda value: "d" * 64,
    )


def test_preview_projects_exact_policy_scope_counts_and_result_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_dependencies(monkeypatch)

    projection = workflow.build_academic_period_calculation_preview_projection(
        "workspace",
        inputs(),
        POLICY_REF,
    )

    assert projection.class_id == "class_2026"
    assert projection.school_year == "2026-2027"
    assert projection.period_id == "mp1"
    assert projection.calendar_revision == 4
    assert projection.target_period_title == "Marking Period 1"
    assert projection.student_id == "student_001"
    assert projection.standard_id == "NJSLSA.R1"
    assert projection.inputs_sha256 == "d" * 64
    assert projection.policy_reference == POLICY_REF
    assert projection.strategy == "median"
    assert projection.period_membership_scope == "direct"
    assert projection.minimum_calculated_results == 2
    assert projection.missing_result_handling == "blocking"
    assert projection.insufficient_result_handling == "noncontributing"
    assert projection.input_entry_count == 3
    assert projection.input_status_counts == (
        ("calculated", 1),
        ("missing_result", 1),
        ("period_scope_mismatch", 1),
    )
    assert projection.status == "insufficient_evidence"
    assert projection.proficiency_level_id is None
    assert projection.result_history == (1, 2)
    assert projection.next_result_revision == 3
    assert projection.current_result_revision == 1
    assert projection.result_write_performed is False
    assert projection.result_selection_performed is False


def test_preview_runs_pure_calculation_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_dependencies(monkeypatch)
    observed: list[tuple[object, object, object]] = []

    def calculate(
        exact_inputs: object,
        exact_policy: object,
        exact_scale: object,
    ) -> object:
        observed.append((exact_inputs, exact_policy, exact_scale))
        return outcome()

    monkeypatch.setattr(
        workflow,
        "calculate_academic_period_proficiency",
        calculate,
    )
    exact = inputs()

    projection = workflow.build_academic_period_calculation_preview_projection(
        "workspace",
        exact,
        POLICY_REF,
    )

    assert observed == [(exact, policy(), SimpleNamespace())]
    assert projection.result_write_performed is False
    assert projection.result_selection_performed is False


def test_preview_rejects_policy_digest_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_academic_period_proficiency_policy_revision",
        lambda *args, **kwargs: SimpleNamespace(
            policy=policy(),
            policy_sha256="f" * 64,
        ),
    )

    with pytest.raises(
        workflow.AcademicPeriodCalculationPreviewDependencyError,
        match="policy SHA-256",
    ):
        workflow.build_academic_period_calculation_preview_projection(
            "workspace",
            inputs(),
            POLICY_REF,
        )


def test_preview_rejects_policy_membership_scope_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    different = policy()
    different.period_membership_scope = "descendants"
    monkeypatch.setattr(
        workflow,
        "load_academic_period_proficiency_policy_revision",
        lambda *args, **kwargs: SimpleNamespace(
            policy=different,
            policy_sha256=POLICY_REF.policy_sha256,
        ),
    )

    with pytest.raises(
        workflow.AcademicPeriodCalculationPreviewDependencyError,
        match="membership scope",
    ):
        workflow.build_academic_period_calculation_preview_projection(
            "workspace",
            inputs(),
            POLICY_REF,
        )


def test_preview_rejects_scale_digest_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "load_academic_period_proficiency_policy_revision",
        lambda *args, **kwargs: SimpleNamespace(
            policy=policy(),
            policy_sha256=POLICY_REF.policy_sha256,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "load_proficiency_scale_revision",
        lambda *args, **kwargs: SimpleNamespace(
            scale=SimpleNamespace(),
            scale_sha256="f" * 64,
        ),
    )

    with pytest.raises(
        workflow.AcademicPeriodCalculationPreviewDependencyError,
        match="target-scale SHA-256",
    ):
        workflow.build_academic_period_calculation_preview_projection(
            "workspace",
            inputs(),
            POLICY_REF,
        )
