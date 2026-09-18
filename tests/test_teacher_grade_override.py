from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.grade_policy import GradePolicyActor
from meridian.hybrid_grade_result import HybridGradeResultReference
from meridian.standards_grade_result import StandardsGradeResultReference
from meridian.teacher_grade_override import (
    MAXIMUM_TEACHER_GRADE_OVERRIDE_TEXT_LENGTH,
    TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
    TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideDecision,
    TeacherGradeOverrideSerializationError,
    TeacherGradeOverrideValidationError,
    grade_override_source_result_reference_from_dict,
    grade_override_source_result_reference_to_dict,
    teacher_grade_override_decision_from_dict,
    teacher_grade_override_decision_from_json_bytes,
    teacher_grade_override_decision_to_dict,
    teacher_grade_override_decision_to_json_bytes,
    teacher_grade_override_reference,
    teacher_grade_override_reference_from_dict,
    teacher_grade_override_reference_to_dict,
    validate_teacher_grade_override_transition,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "student_001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 16, 22, 0, tzinfo=UTC)


def source_reference(
    family: str = "conventional",
    *,
    result_revision: int = 1,
    digest: str = "a" * 64,
    class_id: str = CLASS_ID,
    student_id: str = STUDENT_ID,
    period: AcademicPeriodRef = PERIOD,
    calendar_revision: int = 1,
) -> GradeOverrideSourceResultReference:
    kwargs = {
        "class_id": class_id,
        "student_id": student_id,
        "school_year": period.school_year,
        "period_id": period.period_id,
        "calendar_revision": calendar_revision,
        "result_revision": result_revision,
        "result_sha256": digest,
    }
    if family == "conventional":
        reference = ConventionalGradeResultReference(**kwargs)
    elif family == "standards_based":
        reference = StandardsGradeResultReference(**kwargs)
    elif family == "hybrid":
        reference = HybridGradeResultReference(**kwargs)
    else:
        raise AssertionError("unsupported test family")
    return GradeOverrideSourceResultReference(
        family,  # type: ignore[arg-type]
        reference,
    )


def override_decision(
    revision: int = 1,
    *,
    family: str = "conventional",
    source: GradeOverrideSourceResultReference | None = None,
    replacement: Decimal | None = Decimal("87.5"),
    actor: GradePolicyActor | None = None,
    rationale: str = "Teacher review of the final Academic Period Grade.",
    decided_at: datetime | None = None,
    calendar_revision: int = 1,
) -> TeacherGradeOverrideDecision:
    if source is None:
        source = source_reference(
            family,
            calendar_revision=calendar_revision,
        )
    if actor is None:
        actor = GradePolicyActor("teacher", "teacher_local")
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=calendar_revision,
        calculation_family=family,  # type: ignore[arg-type]
        override_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision="override",
        source_result=source,
        replacement_grade=replacement,
        withdrawn_override_reference=None,
        actor=actor,
        rationale=rationale,
        decided_at=decided_at or NOW + timedelta(minutes=revision - 1),
    )


def withdrawal(
    active: TeacherGradeOverrideDecision,
    *,
    revision: int = 2,
    rationale: str = "Teacher withdrew the prior final Grade override.",
    decided_at: datetime | None = None,
) -> TeacherGradeOverrideDecision:
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=active.class_id,
        student_id=active.student_id,
        target_period=active.target_period,
        calendar_revision=active.calendar_revision,
        calculation_family=active.calculation_family,
        override_revision=revision,
        supersedes_revision=revision - 1,
        decision="withdraw",
        source_result=active.source_result,
        replacement_grade=None,
        withdrawn_override_reference=teacher_grade_override_reference(active),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=rationale,
        decided_at=decided_at or active.decided_at + timedelta(minutes=1),
    )


@pytest.mark.parametrize("family", ["conventional", "standards_based", "hybrid"])
def test_source_reference_round_trip_is_explicitly_family_tagged(family: str) -> None:
    source = source_reference(family)
    data = grade_override_source_result_reference_to_dict(source)

    assert data["family"] == family
    assert grade_override_source_result_reference_from_dict(data) == source


def test_source_family_must_match_concrete_reference_type() -> None:
    conventional = source_reference("conventional")
    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="hybrid source family requires",
    ):
        GradeOverrideSourceResultReference(
            "hybrid",
            conventional.reference,
        )


def test_override_is_frozen_and_slotted() -> None:
    value = override_decision()
    with pytest.raises(FrozenInstanceError):
        value.replacement_grade = Decimal("90")  # type: ignore[misc]
    assert not hasattr(value, "__dict__")


@pytest.mark.parametrize("family", ["conventional", "standards_based", "hybrid"])
def test_override_accepts_each_final_grade_result_family(family: str) -> None:
    value = override_decision(family=family)
    assert value.calculation_family == family
    assert value.source_result.family == family


def test_source_scope_must_match_exact_override_scope() -> None:
    source = source_reference(student_id="student_002")
    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="exact override scope",
    ):
        override_decision(source=source)


def test_calculation_family_must_match_source_family() -> None:
    source = source_reference("conventional")
    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="family must match",
    ):
        override_decision(family="hybrid", source=source)


@pytest.mark.parametrize(
    "replacement",
    [
        Decimal("-0.01"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        90,
        90.0,
        "90",
        True,
    ],
)
def test_override_rejects_nonexact_or_invalid_replacement(
    replacement: object,
) -> None:
    with pytest.raises(TeacherGradeOverrideValidationError):
        override_decision(replacement=replacement)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "replacement",
    [Decimal("0"), Decimal("87.125"), Decimal("105"), Decimal("250.75")],
)
def test_override_accepts_nonnegative_decimal_without_100_clamp(
    replacement: Decimal,
) -> None:
    value = override_decision(replacement=replacement)
    assert value.replacement_grade == replacement


def test_replacement_decimal_is_canonicalized_as_text() -> None:
    value = override_decision(replacement=Decimal("120.5000"))
    data = teacher_grade_override_decision_to_dict(value)

    assert data["replacement_grade"] == "120.5"
    assert value.replacement_grade == Decimal("120.5")


def test_override_requires_replacement_and_forbids_withdrawal_reference() -> None:
    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="requires replacement_grade",
    ):
        override_decision(replacement=None)

    active = override_decision()
    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="withdrawn_override_reference=null",
    ):
        replace(
            active,
            withdrawn_override_reference=teacher_grade_override_reference(active),
        )


def test_withdrawal_is_explicit_immutable_decision() -> None:
    active = override_decision()
    value = withdrawal(active)

    assert value.decision == "withdraw"
    assert value.replacement_grade is None
    assert value.withdrawn_override_reference == teacher_grade_override_reference(
        active
    )
    assert validate_teacher_grade_override_transition(active, value) == value


def test_withdrawal_requires_prior_same_family_reference() -> None:
    active = override_decision()
    bad_reference = replace(
        teacher_grade_override_reference(active),
        calculation_family="hybrid",
    )
    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="exact override family",
    ):
        replace(
            withdrawal(active),
            withdrawn_override_reference=bad_reference,
        )

    future_reference = replace(
        teacher_grade_override_reference(active),
        override_revision=2,
    )
    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="must precede",
    ):
        replace(
            withdrawal(active),
            withdrawn_override_reference=future_reference,
        )


def test_withdrawal_forbids_replacement_grade() -> None:
    value = withdrawal(override_decision())
    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="replacement_grade=null",
    ):
        replace(value, replacement_grade=Decimal("80"))


def test_actor_must_be_teacher() -> None:
    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="actor kind must be teacher",
    ):
        override_decision(actor=GradePolicyActor("policy", "automatic"))


@pytest.mark.parametrize(
    "rationale",
    ["", " ", " leading", "trailing ", "line\nbreak"],
)
def test_rationale_is_required_bounded_clean_text(rationale: str) -> None:
    with pytest.raises(TeacherGradeOverrideValidationError):
        override_decision(rationale=rationale)

    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="exceeds maximum length",
    ):
        override_decision(
            rationale="x" * (MAXIMUM_TEACHER_GRADE_OVERRIDE_TEXT_LENGTH + 1)
        )


def test_naive_decision_time_is_rejected() -> None:
    with pytest.raises(TeacherGradeOverrideValidationError):
        override_decision(decided_at=datetime(2026, 9, 16, 22, 0))


def test_revision_lineage_is_contiguous_and_scope_bound() -> None:
    first = override_decision()
    second = override_decision(2)
    assert validate_teacher_grade_override_transition(first, second) == second

    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="contiguous",
    ):
        validate_teacher_grade_override_transition(
            first,
            override_decision(3),
        )

    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="logical identity",
    ):
        validate_teacher_grade_override_transition(
            first,
            override_decision(2, calendar_revision=2),
        )


def test_transition_rejects_time_regression() -> None:
    first = override_decision()
    second = override_decision(
        2,
        decided_at=NOW - timedelta(seconds=1),
    )
    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="nondecreasing",
    ):
        validate_teacher_grade_override_transition(first, second)


def test_transition_may_deliberately_rebind_new_source_result() -> None:
    first = override_decision()
    new_source = source_reference(
        "conventional",
        result_revision=2,
        digest="b" * 64,
    )
    second = override_decision(2, source=new_source, replacement=Decimal("91"))

    assert validate_teacher_grade_override_transition(first, second) == second
    assert second.source_result != first.source_result


def test_canonical_round_trip_and_reference_digest() -> None:
    value = override_decision()
    content = teacher_grade_override_decision_to_json_bytes(value)

    assert content.endswith(b"\n")
    assert teacher_grade_override_decision_from_json_bytes(content) == value

    reference = teacher_grade_override_reference(value)
    assert reference.override_sha256 == hashlib.sha256(content).hexdigest()
    assert teacher_grade_override_reference_from_dict(
        teacher_grade_override_reference_to_dict(reference)
    ) == reference


def test_withdrawal_round_trip_is_canonical() -> None:
    value = withdrawal(override_decision())
    content = teacher_grade_override_decision_to_json_bytes(value)

    assert teacher_grade_override_decision_from_json_bytes(content) == value
    assert teacher_grade_override_decision_to_json_bytes(
        teacher_grade_override_decision_from_json_bytes(content)
    ) == content


def test_duplicate_unknown_missing_and_noncanonical_json_fail() -> None:
    value = override_decision()
    canonical = teacher_grade_override_decision_to_json_bytes(value).decode(
        "utf-8"
    )
    duplicate = canonical.replace(
        '  "class_id": "synthetic_class_2026",',
        '  "class_id": "synthetic_class_2026",\n'
        '  "class_id": "synthetic_class_2026",',
        1,
    ).encode("utf-8")
    with pytest.raises(
        TeacherGradeOverrideSerializationError,
        match="duplicate JSON object key",
    ):
        teacher_grade_override_decision_from_json_bytes(duplicate)

    data = teacher_grade_override_decision_to_dict(value)
    with pytest.raises(TeacherGradeOverrideValidationError):
        teacher_grade_override_decision_from_dict({**data, "extra": True})

    missing = dict(data)
    del missing["source_result"]
    with pytest.raises(TeacherGradeOverrideValidationError):
        teacher_grade_override_decision_from_dict(missing)

    compact = json.dumps(data).encode("utf-8")
    with pytest.raises(
        TeacherGradeOverrideSerializationError,
        match="canonical encoding",
    ):
        teacher_grade_override_decision_from_json_bytes(compact)


def test_dict_parser_rejects_numeric_replacement_instead_of_decimal_text() -> None:
    data = teacher_grade_override_decision_to_dict(override_decision())
    data["replacement_grade"] = 90

    with pytest.raises(
        TeacherGradeOverrideValidationError,
        match="decimal text",
    ):
        teacher_grade_override_decision_from_dict(data)


def test_reference_rejects_bad_digest_and_family() -> None:
    reference = teacher_grade_override_reference(override_decision())

    with pytest.raises(TeacherGradeOverrideValidationError):
        teacher_grade_override_reference_from_dict(
            {
                **teacher_grade_override_reference_to_dict(reference),
                "override_sha256": "ABC",
            }
        )

    with pytest.raises(TeacherGradeOverrideValidationError):
        teacher_grade_override_reference_from_dict(
            {
                **teacher_grade_override_reference_to_dict(reference),
                "calculation_family": "other",
            }
        )
