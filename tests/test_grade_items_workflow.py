from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.grade_items_workflow as workflow

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
OTHER_GRADE_ITEM_ID = "essay_revision"
WORK = ModuleWorkRef(
    module_id="scoreform",
    class_id=CLASS_ID,
    work_id="test_1",
)
OTHER_WORK = ModuleWorkRef(
    module_id="quillan",
    class_id=CLASS_ID,
    work_id="essay_1",
)
DECIDED_AT = datetime(2026, 9, 1, 20, tzinfo=UTC)


def _stored_grade_item(
    *,
    revision: int = 1,
    digest: str = "a" * 64,
    title: str = "Unit 1 Assessment",
    purpose: str = "standards_proficiency",
    status: str = "active",
    weighting: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        revision=SimpleNamespace(
            grade_item_revision=revision,
            title=title,
            purpose=purpose,
            status=status,
            weighting=weighting,
            created_at=DECIDED_AT,
            revised_at=DECIDED_AT,
        ),
        revision_sha256=digest,
    )


def _stored_membership(
    *,
    work: ModuleWorkRef = WORK,
    membership_revision: int = 1,
    decision: str = "included",
    grade_item_revision: int = 1,
    grade_item_digest: str = "a" * 64,
    decision_digest: str = "b" * 64,
    period_id: str = "q1",
) -> SimpleNamespace:
    assignment = None
    if decision == "included":
        assignment = SimpleNamespace(
            period=SimpleNamespace(
                school_year="2026-2027",
                period_id=period_id,
            ),
            calendar_revision=3,
        )
    return SimpleNamespace(
        decision=SimpleNamespace(
            membership_revision=membership_revision,
            decision=decision,
            grade_item_revision=grade_item_revision,
            grade_item_revision_sha256=grade_item_digest,
            work_reference=SimpleNamespace(
                work=work,
                registration_revision=7,
            ),
            academic_period=assignment,
            actor_id="teacher_local",
            decided_at=DECIDED_AT,
        ),
        decision_sha256=decision_digest,
    )


def test_review_preserves_explicit_historical_grade_item_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "list_grade_item_ids", lambda *args: (GRADE_ITEM_ID,))
    monkeypatch.setattr(workflow, "list_grade_item_revisions", lambda *args: (1, 2))
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_revision",
        lambda *args: _stored_grade_item(revision=1),
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_work_refs",
        lambda *args: (),
    )

    review = workflow.project_grade_items_review("workspace", CLASS_ID)

    assert len(review.items) == 1
    row = review.items[0]
    assert row.latest_persisted_revision == 2
    assert row.selected_revision == 1
    assert row.selection_state == "selected_historical"
    assert row.title == "Unit 1 Assessment"
    assert review.active_count == 1
    assert review.unselected_count == 0


def test_review_does_not_treat_latest_revision_as_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "list_grade_item_ids", lambda *args: (GRADE_ITEM_ID,))
    monkeypatch.setattr(workflow, "list_grade_item_revisions", lambda *args: (1, 2))
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_revision",
        lambda *args: None,
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_work_refs",
        lambda *args: (),
    )

    row = workflow.project_grade_items_review("workspace", CLASS_ID).items[0]

    assert row.latest_persisted_revision == 2
    assert row.selected_revision is None
    assert row.selection_state == "no_selection"
    assert row.title is None
    assert row.status is None


def test_membership_review_preserves_explicit_period_and_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "list_grade_item_ids", lambda *args: (GRADE_ITEM_ID,))
    monkeypatch.setattr(workflow, "list_grade_item_revisions", lambda *args: (1, 2))
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_revision",
        lambda *args: _stored_grade_item(revision=2, digest="c" * 64),
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_work_refs",
        lambda *args: (WORK,),
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_revisions",
        lambda *args: (1, 2, 3),
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args: _stored_membership(
            membership_revision=2,
            grade_item_revision=1,
            grade_item_digest="a" * 64,
        ),
    )

    membership = workflow.project_grade_items_review(
        "workspace", CLASS_ID
    ).items[0].memberships[0]

    assert membership.latest_persisted_revision == 3
    assert membership.selected_revision == 2
    assert membership.selection_state == "selected_historical"
    assert membership.decision == "included"
    assert membership.grade_item_basis_state == "historical_grade_item_basis"
    assert membership.registration_revision == 7
    assert membership.academic_period_school_year == "2026-2027"
    assert membership.academic_period_id == "q1"
    assert membership.academic_period_calendar_revision == 3


def test_membership_history_without_selector_is_not_a_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow, "list_grade_item_ids", lambda *args: (GRADE_ITEM_ID,))
    monkeypatch.setattr(workflow, "list_grade_item_revisions", lambda *args: (1,))
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_revision",
        lambda *args: _stored_grade_item(),
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_work_refs",
        lambda *args: (WORK,),
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_revisions",
        lambda *args: (1, 2),
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args: None,
    )

    membership = workflow.project_grade_items_review(
        "workspace", CLASS_ID
    ).items[0].memberships[0]

    assert membership.latest_persisted_revision == 2
    assert membership.selected_revision is None
    assert membership.selection_state == "no_selection"
    assert membership.decision is None
    assert membership.grade_item_basis_state == "not_selected"
    assert membership.academic_period_id is None


def test_review_is_deterministic_and_weighting_is_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "list_grade_item_ids",
        lambda *args: (GRADE_ITEM_ID, OTHER_GRADE_ITEM_ID),
    )

    def grade_item_history(*args: object) -> tuple[int, ...]:
        return (1,)

    def current_grade_item(
        _root: object, _class_id: object, grade_item_id: str
    ) -> SimpleNamespace:
        if grade_item_id == GRADE_ITEM_ID:
            return _stored_grade_item(
                weighting=SimpleNamespace(
                    category_id="summative",
                    relative_weight=Decimal("2.50"),
                )
            )
        return _stored_grade_item(
            title="Essay Revision",
            status="archived",
            digest="d" * 64,
        )

    def work_refs(
        _root: object, _class_id: object, grade_item_id: str
    ) -> tuple[ModuleWorkRef, ...]:
        return (WORK,) if grade_item_id == GRADE_ITEM_ID else (OTHER_WORK,)

    monkeypatch.setattr(workflow, "list_grade_item_revisions", grade_item_history)
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_revision",
        current_grade_item,
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_work_refs",
        work_refs,
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_revisions",
        lambda *args: (1,),
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda _root, _class_id, grade_item_id, work: _stored_membership(
            work=work,
            decision="included" if grade_item_id == GRADE_ITEM_ID else "excluded",
            grade_item_digest="a" * 64 if grade_item_id == GRADE_ITEM_ID else "d" * 64,
            decision_digest="e" * 64,
        ),
    )

    review = workflow.project_grade_items_review("workspace", CLASS_ID)
    payload = workflow.grade_items_review_to_dict(review)

    assert tuple(row.grade_item_id for row in review.items) == (
        OTHER_GRADE_ITEM_ID,
        GRADE_ITEM_ID,
    )
    assert review.active_count == 1
    assert review.archived_count == 1
    assert review.membership_included_count == 1
    assert review.membership_excluded_count == 1
    item_payloads = {
        item["grade_item_id"]: item for item in payload["items"]  # type: ignore[index]
    }
    assert item_payloads[GRADE_ITEM_ID]["weighting"] == {
        "category_id": "summative",
        "relative_weight": "2.50",
    }
    rendered = repr(payload).lower()
    assert "calculated_grade" not in rendered
    assert "weighted_score" not in rendered
    assert "groupplan" not in rendered


def test_projection_rejects_inconsistent_summary_instead_of_normalizing() -> None:
    with pytest.raises(
        workflow.GradeItemsWorkflowProjectionError,
        match="summary counts",
    ):
        workflow.GradeItemsReview(
            schema_version=1,
            class_id=CLASS_ID,
            items=(),
            active_count=1,
            archived_count=0,
            unselected_count=0,
            membership_relationship_count=0,
            membership_included_count=0,
            membership_excluded_count=0,
            membership_unselected_count=0,
        )
