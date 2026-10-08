from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.rosters import ROSTER_REQUIRED_COLUMNS, Roster, StudentRecord
from pds_core.routing_models import ModuleWorkRef

from meridian.evidence import (
    EvidenceInventory,
    NativePointValue,
    NativeScale,
    NativeScaledValue,
    NativeScaleLevel,
    NativeStateValue,
)
from meridian.teacher_evidence_review import (
    TeacherEvidenceRosterUnavailableError,
    TeacherEvidenceStudentAmbiguityError,
    TeacherEvidenceStudentMissingError,
    build_teacher_evidence_review,
)

WORK = ModuleWorkRef("scoreform", "english_12_pd2", "memory_snapshot")
PUBLICATION_ID = "pub_11111111111111111111111111111111"


def _student(
    student_id: str,
    first_name: str,
    last_name: str,
    period: str = "2",
    *,
    preferred_name: str = "",
) -> StudentRecord:
    extras = {"preferred_name": preferred_name} if preferred_name else {}
    return StudentRecord(
        class_id=WORK.class_id,
        student_id=student_id,
        first_name=first_name,
        last_name=last_name,
        period=period,
        extra_fields=extras,
    )


def _roster(*students: StudentRecord) -> Roster:
    columns = (
        ROSTER_REQUIRED_COLUMNS
        if not any(student.extra_fields for student in students)
        else (*ROSTER_REQUIRED_COLUMNS, "preferred_name")
    )
    return Roster(
        class_id=WORK.class_id,
        students=students,
        columns=columns,
    )


def _item(
    item_id: str,
    *,
    student_id: str | None,
    target_kind: str,
    sequence: int | None,
    result_kind: str,
    value: object,
    standards: tuple[str, ...] = (),
) -> object:
    subject = (
        None
        if student_id is None
        else SimpleNamespace(student_id=student_id)
    )
    return SimpleNamespace(
        item_id=item_id,
        subject=subject,
        target=SimpleNamespace(
            target_kind=target_kind,
            sequence=sequence,
            standard_ids=standards,
        ),
        result_kind=result_kind,
        value=value,
        provenance=SimpleNamespace(
            native=SimpleNamespace(references=()),
        ),
    )


def _inventory(*items: object) -> EvidenceInventory:
    return cast(EvidenceInventory, SimpleNamespace(items=items))


def test_review_uses_roster_names_and_preserves_hidden_identity() -> None:
    inventory = _inventory(
        _item(
            "item_attempt_1",
            student_id="00001",
            target_kind="attempt",
            sequence=1,
            result_kind="submitted_result",
            value=NativePointValue(8, 10),
            standards=("RL.TS.11-12.4",),
        ),
        _item(
            "item_response_1",
            student_id="00002",
            target_kind="review_unit",
            sequence=1,
            result_kind="native_rating",
            value=NativeStateValue("reviewed", "Reviewed"),
        ),
    )
    roster = _roster(
        _student("00001", "Jane", "Smith"),
        _student("00002", "Marcus", "Lee", preferred_name="Marc"),
    )

    review = build_teacher_evidence_review(
        inventory=inventory,
        roster=roster,
        work=WORK,
        publication_id=PUBLICATION_ID,
    )

    assert review.student_count == 2
    assert review.evidence_count == 2
    assert tuple(student.display_label for student in review.students) == (
        "Jane Smith",
        "Marc Lee",
    )
    assert review.students[0].student_id == "00001"
    assert review.students[0].items[0].item_id == "item_attempt_1"
    assert review.students[0].items[0].evidence_label == "Attempt 1"
    assert review.students[0].items[0].value_label == "8 / 10"
    assert review.students[0].items[0].standard_ids == ("RL.TS.11-12.4",)


def test_native_scale_uses_teacher_facing_level_label_without_normalization() -> None:
    scale = NativeScale(
        "writing_scale",
        (
            NativeScaleLevel(1, "Developing"),
            NativeScaleLevel(2, "Meeting"),
        ),
    )
    review = build_teacher_evidence_review(
        inventory=_inventory(
            _item(
                "item_rating",
                student_id="00001",
                target_kind="review_unit",
                sequence=1,
                result_kind="native_rating",
                value=NativeScaledValue(2, scale),
            )
        ),
        roster=_roster(_student("00001", "Jane", "Smith")),
        work=WORK,
        publication_id=PUBLICATION_ID,
    )

    assert review.students[0].items[0].value_label == "Meeting"


def test_duplicate_names_use_period_when_that_safely_distinguishes() -> None:
    review = build_teacher_evidence_review(
        inventory=_inventory(
            _item(
                "item_a",
                student_id="00001",
                target_kind="response",
                sequence=1,
                result_kind="native_rating",
                value=NativeStateValue("reviewed"),
            ),
            _item(
                "item_b",
                student_id="00002",
                target_kind="response",
                sequence=1,
                result_kind="native_rating",
                value=NativeStateValue("reviewed"),
            ),
        ),
        roster=_roster(
            _student("00001", "Alex", "Rivera", "2"),
            _student("00002", "Alex", "Rivera", "5"),
        ),
        work=WORK,
        publication_id=PUBLICATION_ID,
    )

    assert tuple(student.display_label for student in review.students) == (
        "Alex Rivera · Period 2",
        "Alex Rivera · Period 5",
    )


def test_duplicate_names_and_periods_block_without_raw_id_fallback() -> None:
    with pytest.raises(TeacherEvidenceStudentAmbiguityError):
        build_teacher_evidence_review(
            inventory=_inventory(
                _item(
                    "item_a",
                    student_id="00001",
                    target_kind="response",
                    sequence=1,
                    result_kind="native_rating",
                    value=NativeStateValue("reviewed"),
                ),
                _item(
                    "item_b",
                    student_id="00002",
                    target_kind="response",
                    sequence=1,
                    result_kind="native_rating",
                    value=NativeStateValue("reviewed"),
                ),
            ),
            roster=_roster(
                _student("00001", "Alex", "Rivera", "2"),
                _student("00002", "Alex", "Rivera", "2"),
            ),
            work=WORK,
            publication_id=PUBLICATION_ID,
        )


def test_missing_roster_student_blocks_instead_of_showing_student_id() -> None:
    with pytest.raises(TeacherEvidenceStudentMissingError):
        build_teacher_evidence_review(
            inventory=_inventory(
                _item(
                    "item_missing",
                    student_id="00999",
                    target_kind="response",
                    sequence=1,
                    result_kind="native_rating",
                    value=NativeStateValue("reviewed"),
                )
            ),
            roster=_roster(_student("00001", "Jane", "Smith")),
            work=WORK,
            publication_id=PUBLICATION_ID,
        )


def test_individualized_evidence_requires_roster() -> None:
    with pytest.raises(TeacherEvidenceRosterUnavailableError):
        build_teacher_evidence_review(
            inventory=_inventory(
                _item(
                    "item_a",
                    student_id="00001",
                    target_kind="response",
                    sequence=1,
                    result_kind="native_rating",
                    value=NativeStateValue("reviewed"),
                )
            ),
            roster=None,
            work=WORK,
            publication_id=PUBLICATION_ID,
        )


def test_shared_nonstudent_evidence_does_not_require_roster() -> None:
    review = build_teacher_evidence_review(
        inventory=_inventory(
            _item(
                "shared_item",
                student_id=None,
                target_kind="group_score",
                sequence=1,
                result_kind="native_rating",
                value=NativeStateValue("meeting", "Meeting"),
            )
        ),
        roster=None,
        work=WORK,
        publication_id=PUBLICATION_ID,
    )

    assert review.student_count == 0
    assert review.shared_evidence_count == 1
    assert review.shared_items[0].student_id is None
    assert review.shared_items[0].evidence_label == "Group score 1"
    assert review.shared_items[0].value_label == "Meeting"
