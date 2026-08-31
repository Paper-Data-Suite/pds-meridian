from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.grouping_signal_generation_basis as basis_module
from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyAggregationPolicyReference,
    AcademicPeriodProficiencyTarget,
    AcademicPeriodProficiencyValidationError,
)
from meridian.grouping_signal_generation_basis import (
    CurrentGroupingSignalAcademicBasis,
    GroupingSignalCurrentBasisReadError,
    GroupingSignalCurrentBasisValidationError,
    build_current_academic_period_proficiency_inputs,
    build_current_grouping_signal_inputs_by_student,
    resolve_current_grouping_signal_academic_basis,
)
from meridian.grouping_signal_policy import (
    GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
    GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
    GroupingSignalAcademicBasis,
    GroupingSignalBandDefinition,
    GroupingSignalDerivationPolicy,
    GroupingSignalPolicyActor,
)
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_evidence import GradeItemAggregationBasis

CLASS_ID = "synthetic_class_2026"
POLICY_ID = "reading_planning_signal"
STANDARD_ID = "urn:standard:reading"


def policy() -> GroupingSignalDerivationPolicy:
    return GroupingSignalDerivationPolicy(
        schema_version=GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Reading planning signal",
        academic_basis=GroupingSignalAcademicBasis(
            basis_kind="academic_period_proficiency",
            target_period=AcademicPeriodProficiencyTarget(
                AcademicPeriodRef("2026-2027", "mp1"),
                2,
            ),
            standard_id=STANDARD_ID,
            source_policy=AcademicPeriodProficiencyAggregationPolicyReference(
                CLASS_ID,
                "mp1_proficiency",
                1,
                "b" * 64,
            ),
            target_scale=ProficiencyScaleReference(
                CLASS_ID,
                "teacher_scale",
                1,
                "a" * 64,
            ),
        ),
        dimension_id="reading_planning",
        band_count=2,
        band_definitions=(
            GroupingSignalBandDefinition(1, 1, 2),
            GroupingSignalBandDefinition(2, 3, 4),
        ),
        tie_handling="same_level_same_band",
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=GroupingSignalPolicyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=datetime(2026, 8, 30, 20, tzinfo=UTC),
    )


def dependencies(scope: str = "direct") -> object:
    return SimpleNamespace(
        source_policy=SimpleNamespace(
            policy=SimpleNamespace(period_membership_scope=scope)
        )
    )


def test_resolve_current_basis_uses_exact_policy_dependencies_and_calendar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    exact_policy = policy()
    deps = dependencies("descendants")
    calendar = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        basis_module,
        "validate_grouping_signal_policy_dependencies",
        lambda root, candidate: deps,
    )
    monkeypatch.setattr(
        basis_module,
        "load_academic_period_calendar_revision",
        lambda root, school_year, revision: calendar,
    )

    def fake_candidates(
        root: object,
        candidate: object,
        exact_calendar: object,
        scope: object,
    ) -> tuple[object, ...]:
        captured["policy"] = candidate
        captured["calendar"] = exact_calendar
        captured["scope"] = scope
        return ()

    monkeypatch.setattr(basis_module, "_current_candidate_bases", fake_candidates)

    value = resolve_current_grouping_signal_academic_basis(
        tmp_path,  # type: ignore[arg-type]
        exact_policy,
    )

    assert value.policy == exact_policy
    assert value.dependencies is deps
    assert value.calendar is calendar
    assert captured == {
        "policy": exact_policy,
        "calendar": calendar,
        "scope": "descendants",
    }


def test_current_candidate_discovery_filters_and_orders_current_grade_items(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    exact_policy = policy()
    monkeypatch.setattr(
        basis_module,
        "list_grade_item_ids",
        lambda root, class_id: ("item_z", "item_a", "item_archived", "item_grade"),
    )

    def stored(item_id: str) -> object:
        status = "archived" if item_id == "item_archived" else "active"
        purpose = (
            "conventional_grade"
            if item_id == "item_grade"
            else "standards_proficiency"
        )
        return SimpleNamespace(
            revision=SimpleNamespace(
                class_id=CLASS_ID,
                grade_item_id=item_id,
                grade_item_revision=1,
                status=status,
                purpose=purpose,
            ),
            revision_sha256="a" * 64,
        )

    monkeypatch.setattr(
        basis_module,
        "_load_current_grade_item",
        lambda root, class_id, grade_item_id: stored(grade_item_id),
    )
    monkeypatch.setattr(
        basis_module,
        "_current_membership_bases",
        lambda root, item: (SimpleNamespace(tag=item.revision.grade_item_id),),
    )
    monkeypatch.setattr(
        basis_module,
        "_membership_is_relevant",
        lambda policy_value, calendar, membership, scope: True,
    )

    candidates = basis_module._current_candidate_bases(
        basis_module._root(tmp_path),  # type: ignore[arg-type]
        exact_policy,
        object(),  # type: ignore[arg-type]
        "direct",
    )

    assert tuple(item[0].grade_item_id for item in candidates) == (
        "item_a",
        "item_z",
    )


def test_current_candidate_discovery_requires_at_least_one_relevant_membership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    exact_policy = policy()
    stored = SimpleNamespace(
        revision=SimpleNamespace(
            class_id=CLASS_ID,
            grade_item_id="item_a",
            grade_item_revision=1,
            status="active",
            purpose="standards_proficiency",
        ),
        revision_sha256="a" * 64,
    )
    monkeypatch.setattr(basis_module, "list_grade_item_ids", lambda *args: ("item_a",))
    monkeypatch.setattr(basis_module, "_load_current_grade_item", lambda *args: stored)
    monkeypatch.setattr(
        basis_module,
        "_current_membership_bases",
        lambda *args: (SimpleNamespace(tag="outside"),),
    )
    monkeypatch.setattr(
        basis_module,
        "_membership_is_relevant",
        lambda *args: False,
    )

    assert basis_module._current_candidate_bases(
        basis_module._root(tmp_path),  # type: ignore[arg-type]
        exact_policy,
        object(),  # type: ignore[arg-type]
        "direct",
    ) == ()


def test_stale_membership_selection_is_not_current_grade_item_basis() -> None:
    stored_item = SimpleNamespace(
        revision=SimpleNamespace(
            class_id=CLASS_ID,
            grade_item_id="item_a",
            grade_item_revision=2,
        ),
        revision_sha256="a" * 64,
    )
    stored_membership = SimpleNamespace(
        decision=SimpleNamespace(
            class_id=CLASS_ID,
            grade_item_id="item_a",
            grade_item_revision=1,
            grade_item_revision_sha256="b" * 64,
        )
    )
    assert not basis_module._membership_matches_current_grade_item(
        stored_membership,  # type: ignore[arg-type]
        stored_item,  # type: ignore[arg-type]
    )


def current_basis() -> CurrentGroupingSignalAcademicBasis:
    exact_policy = policy()
    grade_item = GradeItemAggregationBasis(CLASS_ID, "item_a", 1, "d" * 64)
    memberships = (SimpleNamespace(tag="membership"),)
    return CurrentGroupingSignalAcademicBasis(
        policy=exact_policy,
        dependencies=dependencies("direct"),  # type: ignore[arg-type]
        calendar=object(),  # type: ignore[arg-type]
        candidates=((grade_item, memberships),),  # type: ignore[arg-type]
    )


def test_build_current_student_inputs_uses_selected_current_grade_item_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    selected_snapshot = object()
    selected = SimpleNamespace(snapshot=selected_snapshot)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        basis_module,
        "_load_current_grade_item_result",
        lambda *args: selected,
    )
    monkeypatch.setattr(
        basis_module,
        "ResolvedAcademicPeriodProficiencyCandidate",
        lambda grade_item, memberships, result: SimpleNamespace(
            grade_item=grade_item,
            memberships=memberships,
            result=result,
        ),
    )

    def fake_build(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(student_id=kwargs["student_id"])

    monkeypatch.setattr(
        basis_module,
        "build_academic_period_proficiency_aggregation_inputs",
        fake_build,
    )

    result = build_current_academic_period_proficiency_inputs(
        tmp_path,  # type: ignore[arg-type]
        current_basis(),
        "student_1",
    )

    assert result.student_id == "student_1"  # type: ignore[attr-defined]
    candidate = captured["candidates"][0]  # type: ignore[index]
    assert candidate.result is selected_snapshot
    assert captured["standard_id"] == STANDARD_ID
    assert captured["period_membership_scope"] == "direct"


def test_incompatible_selected_grade_item_result_rebuilds_as_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    selected_snapshot = object()
    selected = SimpleNamespace(snapshot=selected_snapshot)
    seen: list[object | None] = []

    monkeypatch.setattr(
        basis_module,
        "_load_current_grade_item_result",
        lambda *args: selected,
    )

    def candidate(grade_item: object, memberships: object, result: object) -> object:
        seen.append(result)
        if result is not None:
            raise AcademicPeriodProficiencyValidationError("stale #34 basis")
        return SimpleNamespace(result=None)

    monkeypatch.setattr(
        basis_module,
        "ResolvedAcademicPeriodProficiencyCandidate",
        candidate,
    )
    monkeypatch.setattr(
        basis_module,
        "build_academic_period_proficiency_aggregation_inputs",
        lambda **kwargs: SimpleNamespace(student_id=kwargs["student_id"]),
    )

    build_current_academic_period_proficiency_inputs(
        tmp_path,  # type: ignore[arg-type]
        current_basis(),
        "student_1",
    )
    assert seen == [selected_snapshot, None]


def test_student_input_map_is_deterministically_ordered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    exact_policy = policy()
    shared = object()
    monkeypatch.setattr(
        basis_module,
        "resolve_current_grouping_signal_academic_basis",
        lambda *args: shared,
    )
    monkeypatch.setattr(
        basis_module,
        "build_current_academic_period_proficiency_inputs",
        lambda root, basis, student_id: SimpleNamespace(student_id=student_id),
    )

    result = build_current_grouping_signal_inputs_by_student(
        tmp_path,  # type: ignore[arg-type]
        exact_policy,
        ("student_2", "student_1"),
    )
    assert tuple(result) == ("student_1", "student_2")

    with pytest.raises(GroupingSignalCurrentBasisValidationError, match="duplicates"):
        build_current_grouping_signal_inputs_by_student(
            tmp_path,  # type: ignore[arg-type]
            exact_policy,
            ("student_1", "student_1"),
        )


def test_grade_item_storage_failure_is_wrapped_as_current_basis_read_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    from meridian.grade_item_storage import GradeItemStorageReadError

    monkeypatch.setattr(
        basis_module,
        "list_grade_item_ids",
        lambda *args: (_ for _ in ()).throw(GradeItemStorageReadError("boom")),
    )
    with pytest.raises(GroupingSignalCurrentBasisReadError, match="enumerate"):
        basis_module._current_candidate_bases(
            basis_module._root(tmp_path),  # type: ignore[arg-type]
            policy(),
            object(),  # type: ignore[arg-type]
            "direct",
        )
