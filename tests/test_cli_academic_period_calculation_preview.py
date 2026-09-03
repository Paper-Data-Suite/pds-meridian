from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "class_2026"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "mp1"
CALENDAR_REVISION = 4
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"
POLICY_ID = "period_policy"
POLICY_REVISION = 2
POLICY_SHA256 = "a" * 64
GRADE_ITEM_ID = "unit1"
GRADE_ITEM_REVISION = 5
GRADE_ITEM_SHA256 = "b" * 64
MEMBERSHIP_SHA256 = "c" * 64
RESULT_SHA256 = "d" * 64


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "academic-period-calculation-preview",
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        str(CALENDAR_REVISION),
        STUDENT_ID,
        STANDARD_ID,
        POLICY_ID,
        str(POLICY_REVISION),
        POLICY_SHA256,
        "--workspace",
        "synthetic-workspace",
        *extra,
    )


def _preview() -> object:
    target_scale = SimpleNamespace(
        scale_id="four_level",
        scale_revision=3,
        scale_sha256="e" * 64,
    )
    outcome = SimpleNamespace(
        status="insufficient_evidence",
        proficiency_level_id=None,
        calculation_fingerprint="f" * 64,
        candidate_count=1,
        calculated_result_count=0,
        insufficient_result_count=0,
        missing_result_count=1,
        period_scope_mismatch_count=0,
        insufficiency_reasons=(
            SimpleNamespace(
                kind="blocking_missing_result",
                grade_item_ids=(GRADE_ITEM_ID,),
                required_results=None,
                actual_results=None,
            ),
        ),
        tie_resolution=None,
    )
    calculation = SimpleNamespace(
        class_id=CLASS_ID,
        target_period_title="Marking Period 1",
        school_year=SCHOOL_YEAR,
        period_id=PERIOD_ID,
        calendar_revision=CALENDAR_REVISION,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        inputs_sha256="1" * 64,
        policy_reference=SimpleNamespace(
            policy_id=POLICY_ID,
            policy_revision=POLICY_REVISION,
            policy_sha256=POLICY_SHA256,
        ),
        policy_title="MP proficiency",
        strategy="median",
        period_membership_scope="direct",
        minimum_calculated_results=2,
        mode_tie_rule=None,
        median_even_rule="higher",
        missing_result_handling="blocking",
        insufficient_result_handling="noncontributing",
        input_entry_count=1,
        input_status_counts=(("missing_result", 1),),
        outcome=outcome,
        status=outcome.status,
        proficiency_level_id=None,
        calculation_fingerprint=outcome.calculation_fingerprint,
        result_history=(1, 2),
        next_result_revision=3,
        current_result_revision=1,
        result_write_performed=False,
        result_selection_performed=False,
    )
    inputs = SimpleNamespace(target_scale=target_scale)
    return SimpleNamespace(
        target_period=SimpleNamespace(),
        candidate_specs=(),
        inputs=inputs,
        calculation=calculation,
        candidate_count=1,
        grade_item_ids=(GRADE_ITEM_ID,),
        result_write_performed=False,
        result_selection_performed=False,
    )


def test_workflow_help_exposes_academic_period_calculation_preview(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "academic-period-calculation-preview" in output
    assert "Preview one bounded Academic Period proficiency calculation" in output


def test_explicit_candidate_membership_and_result_are_assembled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "AcademicPeriodMembershipSpec",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        cli,
        "AcademicPeriodCalculationCandidateSpec",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def build(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _preview()

    monkeypatch.setattr(
        cli,
        "build_bounded_academic_period_calculation_preview",
        build,
    )

    assert cli.main(
        _arguments(
            "--candidate",
            GRADE_ITEM_ID,
            str(GRADE_ITEM_REVISION),
            GRADE_ITEM_SHA256,
            "--candidate-membership",
            GRADE_ITEM_ID,
            "scoreform",
            "assessment_1",
            "3",
            MEMBERSHIP_SHA256,
            "--candidate-result",
            GRADE_ITEM_ID,
            "7",
            RESULT_SHA256,
        )
    ) == 0

    assert len(observed) == 1
    args, kwargs = observed[0]
    assert kwargs == {}
    assert args[0] == "synthetic-workspace"
    target = args[1]
    assert target.period.school_year == SCHOOL_YEAR
    assert target.period.period_id == PERIOD_ID
    assert target.calendar_revision == CALENDAR_REVISION
    assert args[2:4] == (STUDENT_ID, STANDARD_ID)
    specs = args[4]
    assert len(specs) == 1
    candidate = specs[0]
    assert candidate.grade_item_id == GRADE_ITEM_ID
    assert candidate.grade_item_revision == GRADE_ITEM_REVISION
    assert candidate.grade_item_revision_sha256 == GRADE_ITEM_SHA256
    assert candidate.result_revision == 7
    assert candidate.result_sha256 == RESULT_SHA256
    assert len(candidate.memberships) == 1
    membership = candidate.memberships[0]
    assert membership.work.module_id == "scoreform"
    assert membership.work.work_id == "assessment_1"
    assert membership.membership_revision == 3
    assert membership.membership_sha256 == MEMBERSHIP_SHA256
    policy = args[5]
    assert policy.class_id == CLASS_ID
    assert policy.policy_id == POLICY_ID
    assert policy.policy_revision == POLICY_REVISION
    assert policy.policy_sha256 == POLICY_SHA256


def test_candidate_without_result_remains_intentional_missing_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "AcademicPeriodCalculationCandidateSpec",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    observed: list[object] = []

    def build(*args: object, **kwargs: object) -> object:
        observed.extend(args[4])
        return _preview()

    monkeypatch.setattr(
        cli,
        "build_bounded_academic_period_calculation_preview",
        build,
    )

    assert cli.main(
        _arguments(
            "--candidate",
            GRADE_ITEM_ID,
            str(GRADE_ITEM_REVISION),
            GRADE_ITEM_SHA256,
        )
    ) == 0

    assert len(observed) == 1
    candidate = observed[0]
    assert candidate.memberships == ()
    assert candidate.result_revision is None
    assert candidate.result_sha256 is None


def test_orphan_result_fails_before_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "build_bounded_academic_period_calculation_preview",
        lambda *args, **kwargs: pytest.fail(
            "orphan result must fail before assembly access"
        ),
    )

    assert cli.main(
        _arguments(
            "--candidate-result",
            GRADE_ITEM_ID,
            "7",
            RESULT_SHA256,
        )
    ) == 1


def test_duplicate_candidate_fails_before_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "build_bounded_academic_period_calculation_preview",
        lambda *args, **kwargs: pytest.fail(
            "duplicate candidate must fail before assembly access"
        ),
    )

    assert cli.main(
        _arguments(
            "--candidate",
            GRADE_ITEM_ID,
            str(GRADE_ITEM_REVISION),
            GRADE_ITEM_SHA256,
            "--candidate",
            GRADE_ITEM_ID,
            str(GRADE_ITEM_REVISION),
            GRADE_ITEM_SHA256,
        )
    ) == 1


def test_json_output_preserves_read_only_period_calculation_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "build_bounded_academic_period_calculation_preview",
        lambda *args, **kwargs: _preview(),
    )

    assert cli.main(_arguments("--format", "json")) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["scope"]["school_year"] == SCHOOL_YEAR
    assert data["scope"]["period_id"] == PERIOD_ID
    assert data["scope"]["calendar_revision"] == CALENDAR_REVISION
    assert data["candidates"]["count"] == 1
    assert data["inputs"]["status_counts"] == [
        {"status": "missing_result", "count": 1}
    ]
    assert data["outcome"]["status"] == "insufficient_evidence"
    assert data["result_state"]["history"] == [1, 2]
    assert data["result_state"]["next_revision"] == 3
    assert data["result_state"]["current_revision"] == 1
    assert data["result_write_performed"] is False
    assert data["result_selection_performed"] is False
