from __future__ import annotations

from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.grouping_signal_generation as generation
from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationInputs,
    AcademicPeriodProficiencyResultFreshness,
    AcademicPeriodProficiencyResultReference,
    AcademicPeriodProficiencyTarget,
)
from meridian.grouping_signal_generation import (
    GroupingSignalGenerationReadError,
    GroupingSignalGenerationValidationError,
    generate_grouping_signal_derivation,
    generate_grouping_signal_derivation_from_current_inputs,
)
from meridian.proficiency_mapping import ProficiencyScaleReference

CLASS_ID = "synthetic_class_2026"
STANDARD_ID = "urn:standard:reading"
POLICY_ID = "reading_signal"
SCALE_REF = ProficiencyScaleReference(CLASS_ID, "teacher_scale", 1, "a" * 64)
TARGET = AcademicPeriodProficiencyTarget(
    AcademicPeriodRef("2026-2027", "mp1"),
    2,
)
SOURCE_POLICY_REF = SimpleNamespace(
    class_id=CLASS_ID,
    policy_id="period_policy",
    policy_revision=1,
    policy_sha256="b" * 64,
)


def current_inputs(student_id: str) -> AcademicPeriodProficiencyAggregationInputs:
    return AcademicPeriodProficiencyAggregationInputs(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=TARGET,
        student_id=student_id,
        standard_id=STANDARD_ID,
        target_scale=SCALE_REF,
        period_membership_scope="direct",
        entries=(),
    )


def policy(
    *,
    missing: str = "noncontributing",
    insufficient: str = "noncontributing",
) -> object:
    basis = SimpleNamespace(
        target_period=TARGET,
        standard_id=STANDARD_ID,
        source_policy=SOURCE_POLICY_REF,
        target_scale=SCALE_REF,
    )
    return SimpleNamespace(
        class_id=CLASS_ID,
        academic_basis=basis,
        missing_result_handling=missing,
        insufficient_result_handling=insufficient,
    )


def selected_policy(exact_policy: object) -> object:
    return SimpleNamespace(
        policy=exact_policy,
        reference=SimpleNamespace(class_id=CLASS_ID),
    )


def result_reference(student_id: str) -> AcademicPeriodProficiencyResultReference:
    return AcademicPeriodProficiencyResultReference(
        class_id=CLASS_ID,
        school_year="2026-2027",
        period_id="mp1",
        student_id=student_id,
        standard_id=STANDARD_ID,
        result_revision=1,
        result_sha256=("c" if student_id == "student_1" else "d") * 64,
    )


def stored_result(student_id: str, *, status: str = "calculated") -> object:
    snapshot = SimpleNamespace(
        class_id=CLASS_ID,
        target_period=TARGET,
        student_id=student_id,
        standard_id=STANDARD_ID,
        policy_reference=SOURCE_POLICY_REF,
        target_scale=SCALE_REF,
        outcome=SimpleNamespace(status=status),
    )
    return SimpleNamespace(snapshot=snapshot, reference=result_reference(student_id))


def configure_common(
    monkeypatch: pytest.MonkeyPatch,
    *,
    exact_policy: object | None = None,
    students: tuple[str, ...] = ("student_1", "student_2"),
) -> object:
    selected = selected_policy(exact_policy or policy())
    monkeypatch.setattr(
        generation,
        "load_current_grouping_signal_policy",
        lambda *args, **kwargs: selected,
    )
    monkeypatch.setattr(
        generation,
        "GroupingSignalResolvedStudentResult",
        lambda student_id, result: SimpleNamespace(
            student_id=student_id,
            result=result,
        ),
    )
    monkeypatch.setattr(
        generation,
        "validate_grouping_signal_policy_dependencies",
        lambda *args, **kwargs: SimpleNamespace(
            target_scale=SimpleNamespace(scale=object())
        ),
    )
    monkeypatch.setattr(
        generation,
        "load_roster",
        lambda path: SimpleNamespace(
            class_id=CLASS_ID,
            students=tuple(SimpleNamespace(student_id=item) for item in students),
        ),
    )
    return selected


def test_no_selected_policy_is_structured_class_level_blocker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    monkeypatch.setattr(
        generation,
        "load_current_grouping_signal_policy",
        lambda *args, **kwargs: None,
    )
    result = generate_grouping_signal_derivation_from_current_inputs(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        POLICY_ID,
        {},
    )
    assert result.status == "blocked"
    assert result.blockers[0].code == "no_selected_policy"
    assert result.blockers[0].student_id is None


def test_exact_current_calculated_results_generate_and_persist_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    configure_common(monkeypatch)
    selected_by_student = {
        "student_1": stored_result("student_1"),
        "student_2": stored_result("student_2"),
    }
    monkeypatch.setattr(
        generation,
        "load_current_academic_period_proficiency_result",
        lambda root, class_id, school_year, period_id, student_id, standard_id: (
            selected_by_student[student_id]
        ),
    )
    monkeypatch.setattr(
        generation,
        "assess_academic_period_proficiency_result_freshness",
        lambda *args, **kwargs: AcademicPeriodProficiencyResultFreshness(
            "current",
            (),
        ),
    )
    captured: dict[str, object] = {}

    def fake_derive(*args: object) -> object:
        captured["resolved"] = args[-1]
        captured["roster"] = args[-2]
        return object()

    monkeypatch.setattr(generation, "derive_grouping_signal_snapshot", fake_derive)
    stored = object()
    monkeypatch.setattr(
        generation,
        "write_grouping_signal_derivation",
        lambda root, snapshot: SimpleNamespace(
            disposition="created",
            stored=stored,
        ),
    )

    result = generate_grouping_signal_derivation_from_current_inputs(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        POLICY_ID,
        {
            "student_2": current_inputs("student_2"),
            "student_1": current_inputs("student_1"),
        },
    )
    assert result.status == "generated"
    assert result.write_disposition == "created"
    assert result.stored is stored
    assert tuple(item.student_id for item in captured["resolved"]) == (
        "student_1",
        "student_2",
    )
    assert captured["roster"].student_ids == ("student_1", "student_2")


def test_missing_noncontributing_reaches_pure_derivation_as_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    configure_common(monkeypatch, exact_policy=policy(missing="noncontributing"))
    monkeypatch.setattr(
        generation,
        "load_current_academic_period_proficiency_result",
        lambda *args, **kwargs: None,
    )
    captured: dict[str, object] = {}

    def fake_derive(*args: object) -> object:
        captured["resolved"] = args[-1]
        return object()

    monkeypatch.setattr(generation, "derive_grouping_signal_snapshot", fake_derive)
    monkeypatch.setattr(
        generation,
        "write_grouping_signal_derivation",
        lambda *args, **kwargs: SimpleNamespace(
            disposition="created",
            stored=object(),
        ),
    )
    result = generate_grouping_signal_derivation_from_current_inputs(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        POLICY_ID,
        {},
    )
    assert result.status == "generated"
    assert all(item.result is None for item in captured["resolved"])


def test_missing_blocking_prevents_derivation_and_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    configure_common(monkeypatch, exact_policy=policy(missing="blocking"))
    monkeypatch.setattr(
        generation,
        "load_current_academic_period_proficiency_result",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        generation,
        "derive_grouping_signal_snapshot",
        lambda *args, **kwargs: pytest.fail("derive must not run"),
    )
    monkeypatch.setattr(
        generation,
        "write_grouping_signal_derivation",
        lambda *args, **kwargs: pytest.fail("write must not run"),
    )
    result = generate_grouping_signal_derivation_from_current_inputs(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        POLICY_ID,
        {},
    )
    assert result.status == "blocked"
    assert tuple((item.student_id, item.code) for item in result.blockers) == (
        ("student_1", "missing_result"),
        ("student_2", "missing_result"),
    )


def test_insufficient_blocking_is_structured_and_preserves_reference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    configure_common(
        monkeypatch,
        exact_policy=policy(insufficient="blocking"),
        students=("student_1",),
    )
    selected = stored_result("student_1", status="insufficient_evidence")
    monkeypatch.setattr(
        generation,
        "load_current_academic_period_proficiency_result",
        lambda *args, **kwargs: selected,
    )
    monkeypatch.setattr(
        generation,
        "assess_academic_period_proficiency_result_freshness",
        lambda *args, **kwargs: AcademicPeriodProficiencyResultFreshness(
            "current",
            (),
        ),
    )
    result = generate_grouping_signal_derivation_from_current_inputs(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        POLICY_ID,
        {"student_1": current_inputs("student_1")},
    )
    assert result.status == "blocked"
    blocker = result.blockers[0]
    assert blocker.code == "insufficient_evidence"
    assert blocker.source_result == selected.reference


def test_stale_result_blocks_with_exact_freshness_reasons(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    configure_common(monkeypatch, students=("student_1",))
    selected = stored_result("student_1")
    monkeypatch.setattr(
        generation,
        "load_current_academic_period_proficiency_result",
        lambda *args, **kwargs: selected,
    )
    monkeypatch.setattr(
        generation,
        "assess_academic_period_proficiency_result_freshness",
        lambda *args, **kwargs: AcademicPeriodProficiencyResultFreshness(
            "stale",
            ("inputs_changed", "calendar_changed"),
        ),
    )
    result = generate_grouping_signal_derivation_from_current_inputs(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        POLICY_ID,
        {"student_1": current_inputs("student_1")},
    )
    blocker = result.blockers[0]
    assert blocker.code == "stale_result"
    assert blocker.source_result == selected.reference
    assert blocker.freshness_reasons == (
        "inputs_changed",
        "calendar_changed",
    )


def test_selected_result_policy_mismatch_blocks_without_history_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    configure_common(monkeypatch, students=("student_1",))
    selected = stored_result("student_1")
    selected.snapshot.target_scale = ProficiencyScaleReference(
        CLASS_ID,
        "other_scale",
        1,
        "e" * 64,
    )
    monkeypatch.setattr(
        generation,
        "load_current_academic_period_proficiency_result",
        lambda *args, **kwargs: selected,
    )
    result = generate_grouping_signal_derivation_from_current_inputs(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        POLICY_ID,
        {"student_1": current_inputs("student_1")},
    )
    assert result.blockers[0].code == "selected_result_mismatch"
    assert result.blockers[0].source_result == selected.reference


def test_selected_result_without_explicit_current_basis_blocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    configure_common(monkeypatch, students=("student_1",))
    selected = stored_result("student_1")
    monkeypatch.setattr(
        generation,
        "load_current_academic_period_proficiency_result",
        lambda *args, **kwargs: selected,
    )
    result = generate_grouping_signal_derivation_from_current_inputs(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        POLICY_ID,
        {},
    )
    assert result.blockers[0].code == "current_basis_unavailable"
    assert result.blockers[0].source_result == selected.reference


def test_out_of_roster_current_inputs_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    configure_common(monkeypatch, students=("student_1",))
    with pytest.raises(
        GroupingSignalGenerationValidationError,
        match="out-of-roster",
    ):
        generate_grouping_signal_derivation_from_current_inputs(
            tmp_path,  # type: ignore[arg-type]
            CLASS_ID,
            POLICY_ID,
            {"student_2": current_inputs("student_2")},
        )


def test_current_inputs_mapping_key_must_match_input_student(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    configure_common(monkeypatch, students=("student_1",))
    with pytest.raises(
        GroupingSignalGenerationValidationError,
        match="student_id must match mapping key",
    ):
        generate_grouping_signal_derivation_from_current_inputs(
            tmp_path,  # type: ignore[arg-type]
            CLASS_ID,
            POLICY_ID,
            {"student_1": current_inputs("student_2")},
        )


def test_policy_storage_failure_is_wrapped_as_generation_read_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    from meridian.grouping_signal_policy_storage import (
        GroupingSignalPolicyStorageReadError,
    )

    monkeypatch.setattr(
        generation,
        "load_current_grouping_signal_policy",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            GroupingSignalPolicyStorageReadError("broken")
        ),
    )
    with pytest.raises(GroupingSignalGenerationReadError, match="selected #37"):
        generate_grouping_signal_derivation_from_current_inputs(
            tmp_path,  # type: ignore[arg-type]
            CLASS_ID,
            POLICY_ID,
            {},
        )


def test_workspace_wrapper_rebuilds_current_inputs_for_exact_roster(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    selected = configure_common(
        monkeypatch,
        students=("student_2", "student_1"),
    )
    captured: dict[str, object] = {}

    def fake_build(
        root: object,
        exact_policy: object,
        student_ids: object,
    ) -> dict[str, AcademicPeriodProficiencyAggregationInputs]:
        captured["policy"] = exact_policy
        captured["students"] = student_ids
        return {
            "student_1": current_inputs("student_1"),
            "student_2": current_inputs("student_2"),
        }

    sentinel = object()
    monkeypatch.setattr(
        generation,
        "build_current_grouping_signal_inputs_by_student",
        fake_build,
    )
    monkeypatch.setattr(
        generation,
        "_generate_grouping_signal_derivation_from_resolved_state",
        lambda *args, **kwargs: sentinel,
    )

    result = generate_grouping_signal_derivation(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        POLICY_ID,
    )
    assert result is sentinel
    assert captured["policy"] is selected.policy
    assert captured["students"] == ("student_1", "student_2")


def test_workspace_wrapper_wraps_current_basis_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    configure_common(monkeypatch, students=("student_1",))
    monkeypatch.setattr(
        generation,
        "build_current_grouping_signal_inputs_by_student",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            generation.GroupingSignalCurrentBasisError("broken")
        ),
    )
    with pytest.raises(
        GroupingSignalGenerationReadError,
        match="current #35 aggregation-input basis",
    ):
        generate_grouping_signal_derivation(
            tmp_path,  # type: ignore[arg-type]
            CLASS_ID,
            POLICY_ID,
        )
