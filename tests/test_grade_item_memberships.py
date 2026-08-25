from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_item_memberships import (
    GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
    GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
    MAXIMUM_MEMBERSHIP_ACTOR_ID_LENGTH,
    MAXIMUM_MEMBERSHIP_RATIONALE_LENGTH,
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
    GradeItemMembershipSerializationError,
    GradeItemMembershipValidationError,
    grade_item_membership_decision_from_dict,
    grade_item_membership_decision_from_json_bytes,
    grade_item_membership_decision_to_dict,
    grade_item_membership_decision_to_json_bytes,
    validate_grade_item_membership_transition,
)
from meridian.grade_items import GradeItemWorkReference

CLASS_ID = "synthetic_class_2026"
ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")
OTHER_WORK = ModuleWorkRef(
    module_id="quillan", class_id=CLASS_ID, work_id="essay_1"
)
DIGEST = "a" * 64
DECIDED = datetime(2026, 8, 25, 12, tzinfo=UTC)
ASSIGNMENT = GradeItemAcademicPeriodAssignment(
    period=AcademicPeriodRef(school_year="2026-2027", period_id="mp1"),
    calendar_revision=1,
)


def decision(
    revision: int = 1,
    *,
    disposition: str = "included",
    work: ModuleWorkRef = WORK,
    registration_revision: int = 1,
    grade_item_revision: int = 1,
    grade_item_digest: str = DIGEST,
    academic_period: GradeItemAcademicPeriodAssignment | None = ASSIGNMENT,
    actor_id: str = "teacher_local",
    rationale: str | None = None,
    decided_at: datetime | None = None,
) -> GradeItemMembershipDecision:
    return GradeItemMembershipDecision(
        schema_version=GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
        record_type=GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=ITEM_ID,
        grade_item_revision=grade_item_revision,
        grade_item_revision_sha256=grade_item_digest,
        work_reference=GradeItemWorkReference(
            work=work,
            registration_revision=registration_revision,
        ),
        membership_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision=disposition,  # type: ignore[arg-type]
        academic_period=academic_period,
        actor_id=actor_id,
        rationale=rationale,
        decided_at=decided_at or (DECIDED + timedelta(hours=revision - 1)),
    )


def test_included_and_excluded_decisions_are_explicit() -> None:
    included = decision()
    excluded = decision(disposition="excluded", academic_period=None)
    assert included.decision == "included"
    assert included.academic_period == ASSIGNMENT
    assert excluded.decision == "excluded"
    assert excluded.academic_period is None


def test_included_requires_period_and_excluded_forbids_period() -> None:
    with pytest.raises(GradeItemMembershipValidationError, match="requires"):
        decision(academic_period=None)
    with pytest.raises(GradeItemMembershipValidationError, match="excluded"):
        decision(disposition="excluded", academic_period=ASSIGNMENT)


def test_membership_model_is_frozen_and_slotted() -> None:
    value = decision()
    with pytest.raises((FrozenInstanceError, AttributeError)):
        value.actor_id = "other"  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        value.extra = True  # type: ignore[attr-defined]


def test_class_must_match_work_reference() -> None:
    cross_class = ModuleWorkRef(
        module_id="scoreform", class_id="other_class", work_id="test_1"
    )
    with pytest.raises(GradeItemMembershipValidationError, match="class_id"):
        decision(work=cross_class)


@pytest.mark.parametrize("value", [0, -1, True])
def test_membership_revision_must_be_positive_integer(value: object) -> None:
    data = grade_item_membership_decision_to_dict(decision())
    data["membership_revision"] = value
    with pytest.raises(GradeItemMembershipValidationError):
        grade_item_membership_decision_from_dict(data)


def test_revision_one_and_later_supersession_are_strict() -> None:
    data = grade_item_membership_decision_to_dict(decision())
    data["supersedes_revision"] = 1
    with pytest.raises(GradeItemMembershipValidationError, match="revision 1"):
        grade_item_membership_decision_from_dict(data)

    data = grade_item_membership_decision_to_dict(decision(2))
    data["supersedes_revision"] = 7
    with pytest.raises(GradeItemMembershipValidationError, match="supersedes"):
        grade_item_membership_decision_from_dict(data)


def test_actor_and_rationale_are_bounded_clean_text() -> None:
    assert decision(actor_id="teacher:local", rationale="Teacher review").rationale
    for actor in ("", " teacher", "teacher ", "teacher\nname"):
        with pytest.raises(GradeItemMembershipValidationError):
            decision(actor_id=actor)
    with pytest.raises(GradeItemMembershipValidationError):
        decision(actor_id="x" * (MAXIMUM_MEMBERSHIP_ACTOR_ID_LENGTH + 1))
    for rationale in ("", " note", "note ", "student\nname"):
        with pytest.raises(GradeItemMembershipValidationError):
            decision(rationale=rationale)
    with pytest.raises(GradeItemMembershipValidationError):
        decision(rationale="x" * (MAXIMUM_MEMBERSHIP_RATIONALE_LENGTH + 1))


def test_decided_at_is_timezone_aware_and_canonicalized_to_utc() -> None:
    with pytest.raises(GradeItemMembershipValidationError, match="timezone-aware"):
        decision(decided_at=datetime(2026, 8, 25, 12))
    eastern = timezone(timedelta(hours=-4))
    value = decision(decided_at=datetime(2026, 8, 25, 8, tzinfo=eastern))
    assert value.decided_at == DECIDED
    assert value.decided_at.tzinfo == UTC


def test_transition_preserves_logical_identity_but_allows_exact_basis_changes() -> None:
    first = decision()
    second = decision(
        2,
        disposition="excluded",
        registration_revision=2,
        grade_item_revision=2,
        grade_item_digest="b" * 64,
        academic_period=None,
        actor_id="teacher_local_2",
        rationale="Reviewed against revision 2",
    )
    assert validate_grade_item_membership_transition(first, second) == second


def test_transition_rejects_different_grade_item_or_work() -> None:
    first = decision()
    data = grade_item_membership_decision_to_dict(decision(2))
    data["grade_item_id"] = "other_item"
    with pytest.raises(GradeItemMembershipValidationError, match="grade_item_id"):
        validate_grade_item_membership_transition(
            first, grade_item_membership_decision_from_dict(data)
        )
    with pytest.raises(GradeItemMembershipValidationError, match="logical work"):
        validate_grade_item_membership_transition(first, decision(2, work=OTHER_WORK))


def test_transition_rejects_skipped_revision_and_time_reversal() -> None:
    first = decision()
    with pytest.raises(GradeItemMembershipValidationError, match="exactly one"):
        validate_grade_item_membership_transition(first, decision(3))
    with pytest.raises(GradeItemMembershipValidationError, match="decided_at"):
        validate_grade_item_membership_transition(
            first,
            decision(2, decided_at=DECIDED - timedelta(seconds=1)),
        )


def test_exact_dict_and_json_round_trip() -> None:
    value = decision(rationale="Explicit review")
    mapping = grade_item_membership_decision_to_dict(value)
    assert grade_item_membership_decision_from_dict(mapping) == value
    data = grade_item_membership_decision_to_json_bytes(value)
    assert grade_item_membership_decision_from_json_bytes(data) == value
    assert data.endswith(b"\n")
    assert data == grade_item_membership_decision_to_json_bytes(value)


def test_json_schema_rejects_missing_unknown_duplicate_and_noncanonical_bytes() -> None:
    value = decision()
    mapping = grade_item_membership_decision_to_dict(value)
    missing = dict(mapping)
    missing.pop("actor_id")
    with pytest.raises(GradeItemMembershipValidationError, match="missing"):
        grade_item_membership_decision_from_dict(missing)
    unknown = dict(mapping)
    unknown["publication_id"] = "pub_fake"
    with pytest.raises(GradeItemMembershipValidationError, match="unknown"):
        grade_item_membership_decision_from_dict(unknown)

    canonical = grade_item_membership_decision_to_json_bytes(value)
    duplicate = canonical.decode("utf-8").replace(
        '  "actor_id": "teacher_local",',
        '  "actor_id": "teacher_local",\n  "actor_id": "teacher_local",',
    ).encode("utf-8")
    with pytest.raises(GradeItemMembershipSerializationError, match="duplicate"):
        grade_item_membership_decision_from_json_bytes(duplicate)

    compact = json.dumps(mapping, sort_keys=True).encode("utf-8")
    with pytest.raises(GradeItemMembershipSerializationError, match="canonical"):
        grade_item_membership_decision_from_json_bytes(compact)


def test_grade_item_digest_and_assignment_revision_are_exact() -> None:
    with pytest.raises(GradeItemMembershipValidationError, match="SHA-256"):
        decision(grade_item_digest="ABC")
    with pytest.raises(GradeItemMembershipValidationError, match="positive integer"):
        GradeItemAcademicPeriodAssignment(
            period=AcademicPeriodRef(
                school_year="2026-2027", period_id="mp1"
            ),
            calendar_revision=0,
        )
