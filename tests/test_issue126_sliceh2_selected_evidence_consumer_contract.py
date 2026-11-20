"""#126 H2: selected evidence consumer boundaries; synthetic data only.

An explicit item choice is not, by itself, a canonical #30/#31 selection.
This suite documents the separation without modifying proficiency or reports.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from typing import cast

import pytest
from test_issue126_slicef3b1_verified_standards_recovery_check import (
    _fixture,
    _prepared,
)

from meridian import guided_proficiency
from meridian.evidence import EvidenceItem
from meridian.guided_proficiency import (
    GuidedProficiencyContext,
    GuidedProficiencyDependencies,
    GuidedProficiencyScopeError,
    _selected_evidence_item,
    build_guided_proficiency_preview,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.menu_teacher_verified_continuation import (
    VerifiedContinuationError,
    _review_evidence,
    verify_student_current_use,
)
from meridian.teacher_evidence_review import (
    TeacherEvidenceReviewItem,
    TeacherEvidenceStudent,
)

STUDENT = "synthetic_student_01"


def _native_item(name: str, student: str | None = STUDENT) -> EvidenceItem:
    subject = None if student is None else NS(student_id=student)
    return cast(EvidenceItem, NS(item_id=name, subject=subject))


def _authorized(*items: EvidenceItem) -> GuidedProjectionResult:
    return cast(
        GuidedProjectionResult,
        NS(authorized=NS(stored=NS(snapshot=NS(inventory=NS(items=items))))),
    )


def _row(name: str, student: str | None = STUDENT) -> TeacherEvidenceReviewItem:
    return TeacherEvidenceReviewItem(
        item_id=name,
        student_id=student,
        evidence_label="Synthetic source item",
        value_label="6 / 6",
        result_kind_label="Attempt points",
        standard_ids=("RL.TS.11-12.4",),
    )


def test_guided_item_lookup_preserves_exact_selected_item_identity() -> None:
    earlier = _native_item("synthetic_original")
    chosen = _native_item("synthetic_corrected")
    prepared = _authorized(earlier, chosen)
    assert _selected_evidence_item(prepared, _row("synthetic_corrected")) is chosen
    assert _selected_evidence_item(prepared, _row("synthetic_original")) is earlier
    # Both are exact item lookups. Neither call is a #30 current-use resolver.


def test_guided_item_lookup_refuses_missing_source_item() -> None:
    with pytest.raises(GuidedProficiencyScopeError, match="resolves exactly"):
        _selected_evidence_item(
            _authorized(_native_item("synthetic_original")),
            _row("synthetic_missing"),
        )


def test_guided_item_lookup_refuses_duplicate_source_item_ids() -> None:
    with pytest.raises(GuidedProficiencyScopeError, match="resolves exactly"):
        _selected_evidence_item(
            _authorized(
                _native_item("synthetic_duplicated"),
                _native_item("synthetic_duplicated"),
            ),
            _row("synthetic_duplicated"),
        )


@pytest.mark.parametrize("native_student", [None, "synthetic_other_student"])
def test_guided_item_lookup_refuses_shared_or_foreign_student(
    native_student: str | None,
) -> None:
    with pytest.raises(GuidedProficiencyScopeError, match="student"):
        _selected_evidence_item(
            _authorized(_native_item("synthetic_evidence", native_student)),
            _row("synthetic_evidence"),
        )


def test_guided_item_lookup_refuses_shared_teacher_row() -> None:
    with pytest.raises(GuidedProficiencyScopeError, match="student-specific"):
        _selected_evidence_item(
            _authorized(_native_item("synthetic_evidence")),
            _row("synthetic_evidence", None),
        )


def test_standards_handoff_excludes_historical_item_despite_display_visibility(
    tmp_path: Path,
) -> None:
    inventory, row, _, ports, _, _ = _fixture()
    state = verify_student_current_use(
        tmp_path, _prepared(), inventory, row, ports=ports
    )
    original = ports.evidence(tmp_path, state.prepared)
    person = original.students[0]
    historical = replace(person.items[0], item_id="synthetic_historical_attempt")
    altered = replace(
        original,
        students=(replace(person, items=(*person.items, historical)),),
    )
    choices = _review_evidence(
        tmp_path, state, replace(ports, evidence=lambda *args: altered)
    )
    assert [item.item_id for item in choices] == [person.items[0].item_id]
    assert historical.item_id not in state.included_item_ids


def test_standards_handoff_does_not_include_other_student_with_same_item_id(
    tmp_path: Path,
) -> None:
    inventory, row, _, ports, _, _ = _fixture()
    state = verify_student_current_use(
        tmp_path, _prepared(), inventory, row, ports=ports
    )
    original = ports.evidence(tmp_path, state.prepared)
    same_id = original.students[0].items[0].item_id
    foreign = TeacherEvidenceStudent(
        student_id="synthetic_student_outside_scope",
        display_label="Synthetic outside scope",
        period="2",
        items=(_row(same_id, "synthetic_student_outside_scope"),),
    )
    altered = replace(original, students=(*original.students, foreign))
    choices = _review_evidence(
        tmp_path, state, replace(ports, evidence=lambda *args: altered)
    )
    assert len(choices) == 1
    assert choices[0].student_id == row.student_id


def test_standards_handoff_rejects_duplicate_selected_item_choices(
    tmp_path: Path,
) -> None:
    inventory, row, _, ports, _, _ = _fixture()
    state = verify_student_current_use(
        tmp_path, _prepared(), inventory, row, ports=ports
    )
    original = ports.evidence(tmp_path, state.prepared)
    person = original.students[0]
    duplicate = replace(person, items=(*person.items, person.items[0]))
    altered = replace(original, students=(duplicate,))
    with pytest.raises(VerifiedContinuationError, match="No unique included"):
        _review_evidence(
            tmp_path, state, replace(ports, evidence=lambda *args: altered)
        )


def test_standards_handoff_rejects_wrong_source_publication(
    tmp_path: Path,
) -> None:
    inventory, row, _, ports, _, _ = _fixture()
    state = verify_student_current_use(
        tmp_path, _prepared(), inventory, row, ports=ports
    )
    original = ports.evidence(tmp_path, state.prepared)
    changed = replace(original, publication_id="synthetic_other_publication")
    with pytest.raises(VerifiedContinuationError, match="fresh source"):
        _review_evidence(
            tmp_path, state, replace(ports, evidence=lambda *args: changed)
        )


def test_standards_handoff_rejects_no_exact_included_choice(
    tmp_path: Path,
) -> None:
    inventory, row, _, ports, _, _ = _fixture()
    state = verify_student_current_use(
        tmp_path, _prepared(), inventory, row, ports=ports
    )
    empty = replace(state, included_item_ids=frozenset())
    with pytest.raises(VerifiedContinuationError, match="No unique included"):
        _review_evidence(tmp_path, empty, ports)


def test_guided_proficiency_preview_receives_one_explicit_item_binding_not_30(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record the existing #110/#34 call without invoking a calculation writer.

    A binding with attempt=None is not evidence of resolved multi-attempt use.
    """
    observed: dict[str, object] = {}
    binding_token = object()
    result_token = object()

    def binding_factory(**kwargs: object) -> object:
        observed.update(kwargs)
        return binding_token

    def preview_builder(*args: object) -> object:
        observed["arguments"] = args
        return result_token

    monkeypatch.setattr(
        guided_proficiency, "StandardAggregationCandidateBinding", binding_factory
    )
    prepared = cast(GuidedProjectionResult, NS(authorized="authorized_snapshot"))
    context = cast(
        GuidedProficiencyContext,
        NS(source="exact_item_source", scale=NS(reference="scale_reference")),
    )
    preview = build_guided_proficiency_preview(
        tmp_path,
        prepared,
        context,
        grade_item_id="synthetic_grade_item",
        student_id=STUDENT,
        standard=NS(standard_id="RL.TS.11-12.4"),
        policy=NS(reference="policy_reference"),
        mapping=NS(reference="mapping_reference"),
        dependencies=GuidedProficiencyDependencies(preview_builder=preview_builder),
    )
    assert preview is result_token
    assert observed["source"] == "exact_item_source"
    assert observed["authorized_snapshot"] == "authorized_snapshot"
    assert observed["mapping_profile"] == "mapping_reference"
    assert observed["attempt"] is None
    args = cast(tuple[object, ...], observed["arguments"])
    assert args[1:5] == (
        "synthetic_grade_item",
        STUDENT,
        "RL.TS.11-12.4",
        "scale_reference",
    )
    assert args[5] == (binding_token,)
    assert args[6] == "policy_reference"
    # This is a bounded call witness, not a full #34 calculation qualification.
