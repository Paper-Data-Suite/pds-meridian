from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.effective_grade as effective
from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.grade_policy import GradePolicyActor
from meridian.hybrid_grade_result import HybridGradeResultReference
from meridian.standards_grade_result import StandardsGradeResultReference
from meridian.teacher_grade_override import (
    TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
    TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideDecision,
    TeacherGradeOverrideReference,
    teacher_grade_override_decision_to_json_bytes,
    teacher_grade_override_reference,
)
from meridian.teacher_grade_override_storage import (
    TeacherGradeOverrideStorageIntegrityError,
)
from meridian.teacher_grade_override_workflow import (
    TeacherGradeOverrideSelectedSource,
    TeacherGradeOverrideSourceCurrentnessError,
    TeacherGradeOverrideSourceIntegrityError,
    TeacherGradeOverrideSourceResult,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "s001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 17, 20, 0, tzinfo=UTC)


def source_reference(
    family: str = "conventional",
    *,
    revision: int = 1,
    digest: str = "a" * 64,
) -> GradeOverrideSourceResultReference:
    kwargs = {
        "class_id": CLASS_ID,
        "student_id": STUDENT_ID,
        "school_year": PERIOD.school_year,
        "period_id": PERIOD.period_id,
        "calendar_revision": 1,
        "result_revision": revision,
        "result_sha256": digest,
    }
    if family == "conventional":
        reference = ConventionalGradeResultReference(**kwargs)
    elif family == "standards_based":
        reference = StandardsGradeResultReference(**kwargs)
    elif family == "hybrid":
        reference = HybridGradeResultReference(**kwargs)
    else:
        raise AssertionError(f"unsupported test family: {family}")
    return GradeOverrideSourceResultReference(
        family,  # type: ignore[arg-type]
        reference,
    )


def selected_source(
    family: str = "conventional",
    *,
    revision: int = 1,
    digest: str = "a" * 64,
    status: str = "calculated",
    grade: Decimal | None = Decimal("88.25"),
    freshness: str = "current",
    reasons: tuple[str, ...] = (),
) -> TeacherGradeOverrideSelectedSource:
    return TeacherGradeOverrideSelectedSource(
        source=TeacherGradeOverrideSourceResult(
            source_result=source_reference(
                family,
                revision=revision,
                digest=digest,
            ),
            source_status=status,  # type: ignore[arg-type]
            base_grade=grade,
        ),
        freshness_status=freshness,  # type: ignore[arg-type]
        freshness_reasons=reasons,
    )


def active_override(
    source: GradeOverrideSourceResultReference,
    *,
    replacement: Decimal = Decimal("91.5"),
    revision: int = 1,
) -> TeacherGradeOverrideDecision:
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family=source.family,
        override_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision="override",
        source_result=source,
        replacement_grade=replacement,
        withdrawn_override_reference=None,
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Documented teacher decision.",
        decided_at=NOW,
    )


def withdrawal(
    prior: TeacherGradeOverrideDecision,
) -> TeacherGradeOverrideDecision:
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family=prior.calculation_family,
        override_revision=prior.override_revision + 1,
        supersedes_revision=prior.override_revision,
        decision="withdraw",
        source_result=prior.source_result,
        replacement_grade=None,
        withdrawn_override_reference=teacher_grade_override_reference(prior),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Teacher withdrew the prior override.",
        decided_at=NOW,
    )


def stored_override(decision: TeacherGradeOverrideDecision) -> SimpleNamespace:
    return SimpleNamespace(
        reference=teacher_grade_override_reference(decision),
        decision=decision,
    )


@pytest.mark.parametrize("family", ["conventional", "standards_based", "hybrid"])
def test_current_calculated_without_override_uses_exact_base(family: str) -> None:
    source = selected_source(family)

    result = effective.resolve_effective_grade(source)

    assert result.base_result_family == family
    assert result.base_result_reference == source.source_result
    assert result.base_result_status == "calculated"
    assert result.base_grade == Decimal("88.25")
    assert result.base_freshness_status == "current"
    assert result.selected_override_reference is None
    assert result.override_decision is None
    assert result.override_applicability == "no_override"
    assert result.override_reasons == ("no_selected_override",)
    assert result.effective_grade == Decimal("88.25")
    assert result.effective_source == "base"


def test_current_calculated_with_applicable_override_uses_replacement() -> None:
    source = selected_source()
    decision = active_override(source.source_result, replacement=Decimal("105.25"))

    result = effective.resolve_effective_grade(
        source,
        selected_override_reference=teacher_grade_override_reference(decision),
        selected_override=decision,
    )

    assert result.override_applicability == "applicable"
    assert result.override_reasons == ()
    assert result.base_grade == Decimal("88.25")
    assert result.effective_grade == Decimal("105.25")
    assert result.effective_source == "override"


@pytest.mark.parametrize("status", ["blocked", "insufficient"])
def test_current_nonnumeric_base_without_override_has_no_effective_grade(
    status: str,
) -> None:
    source = selected_source(status=status, grade=None)

    result = effective.resolve_effective_grade(source)

    assert result.base_result_status == status
    assert result.effective_grade is None
    assert result.effective_source == "none"


@pytest.mark.parametrize("status", ["blocked", "insufficient"])
def test_current_nonnumeric_base_accepts_exact_applicable_override(status: str) -> None:
    source = selected_source(status=status, grade=None)
    decision = active_override(source.source_result, replacement=Decimal("79.75"))

    result = effective.resolve_effective_grade(
        source,
        selected_override_reference=teacher_grade_override_reference(decision),
        selected_override=decision,
    )

    assert result.base_grade is None
    assert result.override_applicability == "applicable"
    assert result.effective_grade == Decimal("79.75")
    assert result.effective_source == "override"


def test_selected_withdrawal_returns_precedence_to_current_base() -> None:
    source = selected_source()
    prior = active_override(source.source_result)
    decision = withdrawal(prior)

    result = effective.resolve_effective_grade(
        source,
        selected_override_reference=teacher_grade_override_reference(decision),
        selected_override=decision,
    )

    assert result.override_applicability == "withdrawn"
    assert result.override_reasons == ("selected_override_withdrawn",)
    assert result.effective_grade == Decimal("88.25")
    assert result.effective_source == "base"


def test_selected_withdrawal_does_not_make_blocked_base_numeric() -> None:
    source = selected_source(status="blocked", grade=None)
    prior = active_override(source.source_result)
    decision = withdrawal(prior)

    result = effective.resolve_effective_grade(
        source,
        selected_override_reference=teacher_grade_override_reference(decision),
        selected_override=decision,
    )

    assert result.override_applicability == "withdrawn"
    assert result.effective_grade is None
    assert result.effective_source == "none"


def test_old_source_override_is_nonfloating_and_current_base_governs() -> None:
    current = selected_source(revision=2, digest="b" * 64)
    old = active_override(source_reference(revision=1, digest="a" * 64))

    result = effective.resolve_effective_grade(
        current,
        selected_override_reference=teacher_grade_override_reference(old),
        selected_override=old,
    )

    assert result.override_applicability == "source_result_changed"
    assert result.override_reasons == ("source_result_mismatch",)
    assert result.effective_grade == Decimal("88.25")
    assert result.effective_source == "base"


def test_same_grade_value_does_not_make_old_source_override_applicable() -> None:
    first = selected_source(revision=1, digest="a" * 64, grade=Decimal("88.25"))
    decision = active_override(first.source_result, replacement=Decimal("95"))
    second = selected_source(revision=2, digest="b" * 64, grade=Decimal("88.25"))

    result = effective.resolve_effective_grade(
        second,
        selected_override_reference=teacher_grade_override_reference(decision),
        selected_override=decision,
    )

    assert result.base_grade == Decimal("88.25")
    assert result.override_applicability == "source_result_changed"
    assert result.effective_grade == Decimal("88.25")
    assert result.effective_source == "base"


def test_deliberate_rebind_to_new_source_makes_new_override_effective() -> None:
    second = selected_source(revision=2, digest="b" * 64)
    decision = active_override(
        second.source_result,
        replacement=Decimal("96.5"),
        revision=2,
    )

    result = effective.resolve_effective_grade(
        second,
        selected_override_reference=teacher_grade_override_reference(decision),
        selected_override=decision,
    )

    assert result.override_applicability == "applicable"
    assert result.effective_grade == Decimal("96.5")
    assert result.effective_source == "override"


def test_matching_override_cannot_make_stale_source_current() -> None:
    source = selected_source(
        freshness="stale",
        reasons=("policy_changed",),
    )
    decision = active_override(source.source_result)

    result = effective.resolve_effective_grade(
        source,
        selected_override_reference=teacher_grade_override_reference(decision),
        selected_override=decision,
    )

    assert result.base_freshness_status == "stale"
    assert result.base_freshness_reasons == ("policy_changed",)
    assert result.override_applicability == "source_result_stale"
    assert result.override_reasons == ("source_result_stale",)
    assert result.effective_grade is None
    assert result.effective_source == "none"


def test_stale_base_without_override_has_no_current_effective_authority() -> None:
    source = selected_source(
        freshness="stale",
        reasons=("inputs_changed",),
    )

    result = effective.resolve_effective_grade(source)

    assert result.override_applicability == "no_override"
    assert result.base_freshness_reasons == ("inputs_changed",)
    assert result.effective_grade is None
    assert result.effective_source == "none"


def test_withdrawal_does_not_rescue_stale_base() -> None:
    source = selected_source(
        freshness="stale",
        reasons=("algorithm_changed",),
    )
    prior = active_override(source.source_result)
    decision = withdrawal(prior)

    result = effective.resolve_effective_grade(
        source,
        selected_override_reference=teacher_grade_override_reference(decision),
        selected_override=decision,
    )

    assert result.override_applicability == "withdrawn"
    assert result.effective_grade is None
    assert result.effective_source == "none"


def test_resolution_is_read_only_for_source_and_override() -> None:
    source = selected_source()
    decision = active_override(source.source_result)
    source_before = source
    decision_before = teacher_grade_override_decision_to_json_bytes(decision)

    effective.resolve_effective_grade(
        source,
        selected_override_reference=teacher_grade_override_reference(decision),
        selected_override=decision,
    )

    assert source == source_before
    assert teacher_grade_override_decision_to_json_bytes(decision) == decision_before


def test_reference_and_decision_must_be_supplied_together() -> None:
    source = selected_source()
    decision = active_override(source.source_result)

    with pytest.raises(effective.EffectiveGradeScopeError):
        effective.resolve_effective_grade(
            source,
            selected_override=decision,
        )


def test_reference_must_bind_exact_selected_decision() -> None:
    source = selected_source()
    decision = active_override(source.source_result)
    wrong = TeacherGradeOverrideReference(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        school_year=PERIOD.school_year,
        period_id=PERIOD.period_id,
        calendar_revision=1,
        calculation_family="conventional",
        override_revision=1,
        override_sha256="f" * 64,
    )

    with pytest.raises(effective.EffectiveGradeScopeError):
        effective.resolve_effective_grade(
            source,
            selected_override_reference=wrong,
            selected_override=decision,
        )


def test_selected_override_scope_mismatch_is_not_ordinary_nonapplicability() -> None:
    source = selected_source()
    decision = TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id="other_class",
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="conventional",
        override_revision=1,
        supersedes_revision=None,
        decision="override",
        source_result=GradeOverrideSourceResultReference(
            "conventional",
            ConventionalGradeResultReference(
                class_id="other_class",
                student_id=STUDENT_ID,
                school_year=PERIOD.school_year,
                period_id=PERIOD.period_id,
                calendar_revision=1,
                result_revision=1,
                result_sha256="a" * 64,
            ),
        ),
        replacement_grade=Decimal("90"),
        withdrawn_override_reference=None,
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Different logical family.",
        decided_at=NOW,
    )

    with pytest.raises(effective.EffectiveGradeScopeError):
        effective.resolve_effective_grade(
            source,
            selected_override_reference=teacher_grade_override_reference(decision),
            selected_override=decision,
        )


@pytest.mark.parametrize("family", ["conventional", "standards_based", "hybrid"])
def test_current_service_preserves_family_and_no_override(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
) -> None:
    source = selected_source(family)
    historical_calls: list[int] = []
    monkeypatch.setattr(
        effective,
        "resolve_selected_teacher_grade_override_source",
        lambda *args, **kwargs: source,
    )
    monkeypatch.setattr(
        effective,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: None,
    )

    def historical(*args: object, **kwargs: object) -> None:
        historical_calls.append(1)

    monkeypatch.setattr(
        effective,
        "load_teacher_grade_override_source_result",
        historical,
    )

    result = effective.resolve_current_effective_grade(
        Path("."),
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        family,  # type: ignore[arg-type]
        work_evidence=() if family != "standards_based" else None,
    )

    assert result.base_result_family == family
    assert result.effective_source == "base"
    assert historical_calls == []


def test_current_service_verifies_selected_override_historical_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = selected_source(revision=2, digest="b" * 64)
    decision = active_override(source_reference(revision=1, digest="a" * 64))
    selected = stored_override(decision)
    verified: list[GradeOverrideSourceResultReference] = []
    monkeypatch.setattr(
        effective,
        "resolve_selected_teacher_grade_override_source",
        lambda *args, **kwargs: source,
    )
    monkeypatch.setattr(
        effective,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: selected,
    )

    def verify(
        root: object,
        reference: GradeOverrideSourceResultReference,
    ) -> TeacherGradeOverrideSourceResult:
        verified.append(reference)
        return TeacherGradeOverrideSourceResult(
            source_result=reference,
            source_status="calculated",
            base_grade=Decimal("87"),
        )

    monkeypatch.setattr(
        effective,
        "load_teacher_grade_override_source_result",
        verify,
    )

    result = effective.resolve_current_effective_grade(
        Path("."),
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        "conventional",
        work_evidence=(),
    )

    assert verified == [decision.source_result]
    assert result.override_applicability == "source_result_changed"
    assert result.effective_source == "base"


def test_corrupt_override_selector_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        effective,
        "resolve_selected_teacher_grade_override_source",
        lambda *args, **kwargs: selected_source(),
    )

    def corrupt(*args: object, **kwargs: object) -> None:
        raise TeacherGradeOverrideStorageIntegrityError("corrupt current.json")

    monkeypatch.setattr(
        effective,
        "load_current_teacher_grade_override",
        corrupt,
    )

    with pytest.raises(effective.EffectiveGradeIntegrityError):
        effective.resolve_current_effective_grade(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            "conventional",
            work_evidence=(),
        )


def test_corrupt_historical_override_source_fails_closed_instead_of_base_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = selected_source(revision=2, digest="b" * 64)
    decision = active_override(source_reference(revision=1, digest="a" * 64))
    monkeypatch.setattr(
        effective,
        "resolve_selected_teacher_grade_override_source",
        lambda *args, **kwargs: current,
    )
    monkeypatch.setattr(
        effective,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: stored_override(decision),
    )

    def corrupt(*args: object, **kwargs: object) -> None:
        raise TeacherGradeOverrideSourceIntegrityError("historical source missing")

    monkeypatch.setattr(
        effective,
        "load_teacher_grade_override_source_result",
        corrupt,
    )

    with pytest.raises(effective.EffectiveGradeIntegrityError):
        effective.resolve_current_effective_grade(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            "conventional",
            work_evidence=(),
        )


def test_unresolvable_base_freshness_is_source_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        raise TeacherGradeOverrideSourceCurrentnessError("basis unavailable")

    monkeypatch.setattr(
        effective,
        "resolve_selected_teacher_grade_override_source",
        unavailable,
    )

    with pytest.raises(effective.EffectiveGradeSourceError):
        effective.resolve_current_effective_grade(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            "conventional",
            work_evidence=(),
        )
