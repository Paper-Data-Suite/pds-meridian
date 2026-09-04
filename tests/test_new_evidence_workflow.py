from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.new_evidence_workflow as workflow
from meridian.evidence_eligibility import EvidenceSourceStateObservation
from meridian.evidence_eligibility_storage import EvidenceEligibilityResolution
from meridian.projection_cache import AuthorizedProjectionSnapshot

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")
PUBLICATION_ID = "pub_" + "1" * 32
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64


def fake_item(
    item_id: str,
    *,
    student_id: str | None = "student_1",
) -> SimpleNamespace:
    subject = None if student_id is None else SimpleNamespace(student_id=student_id)
    return SimpleNamespace(
        item_id=item_id,
        subject=subject,
        target=SimpleNamespace(
            target_kind="question",
            target_id="q1",
            standard_ids=("RL.CR.9-10.1",),
        ),
        result_kind="question_score",
    )


def fake_authorized(
    *items: object, source_status: str = "current"
) -> AuthorizedProjectionSnapshot:
    publication = SimpleNamespace(work=WORK, publication_id=PUBLICATION_ID)
    snapshot = SimpleNamespace(
        source=SimpleNamespace(publication=publication),
        inventory=SimpleNamespace(items=tuple(items)),
    )
    stored = SimpleNamespace(
        snapshot=snapshot,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
    )
    return cast(
        AuthorizedProjectionSnapshot,
        SimpleNamespace(
            stored=stored,
            assessment=SimpleNamespace(source_status=source_status),
        ),
    )


def fake_membership(decision: str) -> SimpleNamespace:
    assignment = (
        SimpleNamespace(
            period=SimpleNamespace(period_id="mp1"),
            calendar_revision=3,
        )
        if decision == "included"
        else None
    )
    return SimpleNamespace(
        decision=SimpleNamespace(
            decision=decision,
            membership_revision=2,
            academic_period=assignment,
        )
    )


def source_state(state: str = "current") -> EvidenceSourceStateObservation:
    if state == "current":
        return EvidenceSourceStateObservation(
            state="current",
            head_publication_id=PUBLICATION_ID,
            successor_publication_id=None,
            withdrawn_at=None,
        )
    raise AssertionError("test helper only needs current state")


def resolution(
    status: str, *, operative: bool = False
) -> EvidenceEligibilityResolution:
    return EvidenceEligibilityResolution(
        status=status,  # type: ignore[arg-type]
        selected=None,
        current_source_state=source_state(),
        current_membership_revision=2,
        operative_included=operative,
    )


def permit_fake_authorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "AuthorizedProjectionSnapshot",
        SimpleNamespace,
    )


def permit_fake_items(monkeypatch: pytest.MonkeyPatch) -> None:
    import meridian.evidence as evidence

    monkeypatch.setattr(evidence, "EvidenceItem", SimpleNamespace)


def test_no_membership_routes_every_row_to_grade_items_without_eligibility_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit_fake_authorized(monkeypatch)
    permit_fake_items(monkeypatch)
    authorized = fake_authorized(
        fake_item("item_b", student_id="student_2"),
        fake_item("item_a", student_id="student_1"),
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args, **kwargs: None,
    )

    def unexpected_resolution(*args: object, **kwargs: object) -> object:
        raise AssertionError("eligibility must not resolve before included membership")

    monkeypatch.setattr(
        workflow,
        "resolve_current_evidence_eligibility",
        unexpected_resolution,
    )

    review = workflow.project_new_evidence_review(
        "workspace", CLASS_ID, GRADE_ITEM_ID, authorized
    )

    assert review.membership_state == "no_decision"
    assert [row.source.item_id for row in review.rows] == ["item_a", "item_b"]
    assert review.attention_count == 2
    assert all(row.recommended_task == "grade-items" for row in review.rows)
    assert review.status_summary == (
        workflow.NewEvidenceStatusSummary(status="membership_no_decision", count=2),
    )


def test_excluded_membership_is_resolved_without_fabricating_eligibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit_fake_authorized(monkeypatch)
    permit_fake_items(monkeypatch)
    authorized = fake_authorized(fake_item("item_a"), source_status="withdrawn")
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args, **kwargs: fake_membership("excluded"),
    )

    def unexpected_resolution(*args: object, **kwargs: object) -> object:
        raise AssertionError("excluded membership must not resolve eligibility")

    monkeypatch.setattr(
        workflow,
        "resolve_current_evidence_eligibility",
        unexpected_resolution,
    )

    review = workflow.project_new_evidence_review(
        "workspace", CLASS_ID, GRADE_ITEM_ID, authorized
    )

    assert review.membership_state == "excluded"
    assert review.membership_revision == 2
    assert review.projection_source_status == "withdrawn"
    assert review.attention_count == 0
    assert review.rows[0].eligibility_status is None
    assert review.rows[0].recommended_task is None


def test_included_membership_preserves_eligibility_distinctions_and_routes_attention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit_fake_authorized(monkeypatch)
    permit_fake_items(monkeypatch)
    authorized = fake_authorized(
        fake_item("included", student_id="student_1"),
        fake_item("pending", student_id="student_2"),
        fake_item("stale", student_id="student_3"),
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args, **kwargs: fake_membership("included"),
    )

    statuses = {
        "included": resolution("included", operative=True),
        "pending": resolution("pending"),
        "stale": resolution("membership_stale"),
    }

    def resolve(
        workspace_root: object,
        class_id: object,
        grade_item_id: object,
        source: object,
        *,
        authorized_snapshot: object,
    ) -> EvidenceEligibilityResolution:
        del workspace_root, class_id, grade_item_id, authorized_snapshot
        return statuses[getattr(source, "item_id")]

    monkeypatch.setattr(workflow, "resolve_current_evidence_eligibility", resolve)

    review = workflow.project_new_evidence_review(
        "workspace", CLASS_ID, GRADE_ITEM_ID, authorized
    )
    rows = {row.source.item_id: row for row in review.rows}

    assert review.membership_state == "included"
    assert review.membership_revision == 2
    assert review.academic_period_id == "mp1"
    assert review.academic_period_calendar_revision == 3
    assert review.attention_count == 2
    assert rows["included"].operative_included is True
    assert rows["included"].attention_required is False
    assert rows["pending"].recommended_task == "exclusions"
    assert rows["stale"].recommended_task == "grade-items"


def test_json_projection_is_provenance_safe_and_does_not_copy_native_value() -> None:
    row = workflow.NewEvidenceRow(
        source=workflow.EvidenceSourceReference(
            work=WORK,
            publication_id=PUBLICATION_ID,
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
            item_id="item_a",
        ),
        student_id="student_1",
        target_kind="question",
        target_id="q1",
        standard_ids=("RL.CR.9-10.1",),
        result_kind="question_score",
        membership_state="no_decision",
        eligibility_status=None,
        selected_eligibility_revision=None,
        selected_eligibility_disposition=None,
        eligibility_source_state=None,
        operative_included=False,
        attention_required=True,
        recommended_task="grade-items",
    )
    review = workflow.NewEvidenceReview(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        projection_source_status="current",
        membership_state="no_decision",
        membership_revision=None,
        academic_period_id=None,
        academic_period_calendar_revision=None,
        rows=(row,),
        status_summary=(
            workflow.NewEvidenceStatusSummary(
                status="membership_no_decision",
                count=1,
            ),
        ),
        attention_count=1,
    )

    payload = workflow.new_evidence_review_to_dict(review)
    text = repr(payload)

    assert payload["attention_count"] == 1
    assert "value" not in text
    assert "earned" not in text
    assert "possible" not in text
    assert "answer" not in text


def test_requested_class_must_match_authorized_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    permit_fake_authorized(monkeypatch)
    permit_fake_items(monkeypatch)
    authorized = fake_authorized(fake_item("item_a"))

    with pytest.raises(workflow.NewEvidenceWorkflowScopeError, match="class_id"):
        workflow.project_new_evidence_review(
            "workspace", "different_class", GRADE_ITEM_ID, authorized
        )
