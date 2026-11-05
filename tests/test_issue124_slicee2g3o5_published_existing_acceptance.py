"""#124 E2G3O5: synthetic canonical publication and existing Grade Item journey.

Exercise the real Core publication/registration/catalog and Meridian #122/E2C
academic stores with no producer data or personal teacher profile. Only the
saved actor lookup is replaced, using the E2G3O4 isolated test harness.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

import pytest
from pds_core.academic_catalog import rebuild_academic_catalog
from pds_core.publication_records import PublicationRecord, PublicationWithdrawal
from pds_core.publication_storage import (
    get_current_publication_record,
    write_publication_record,
    write_publication_withdrawal,
)
from test_issue124_slicee2g3k_composite_canonical import (
    ACTOR,
    CLASS,
    GRADE,
    STAMP,
    WORK,
    _all_bytes,
    _grade_written,
    _workspace,
)
from test_issue124_slicee2g3o4_canonical_teacher_acceptance import (
    _correlation,
    _first_setup_answers,
    _journey,
)

from meridian.assessment_setup_choices import load_named_assessment_choices
from meridian.assessment_setup_correlation_storage import (
    AssessmentSetupCorrelationStore,
)
from meridian.assessment_setup_preview import (
    AssessmentSetupPreviewError,
    load_assessment_setup_preview,
)
from meridian.grade_item_membership_storage import (
    list_grade_item_membership_revisions,
    load_current_grade_item_membership_decision,
)
from meridian.grade_item_storage import (
    get_current_grade_item_revision,
    list_grade_item_revisions,
    select_grade_item_revision,
)
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.teacher_action_receipts import TeacherActionReceiptStore

PUBLICATION_ID = "pub_" + "c" * 32
RECORD_SET = "scene_results"


def _publish(root: Path) -> PublicationRecord:
    """Publish only synthetic provenance; no actual score/student manifest."""
    manifest = (
        root
        / "classes"
        / CLASS
        / "modules"
        / WORK.module_id
        / "work"
        / WORK.work_id
        / "publication"
        / "synthetic.json"
    )
    manifest.parent.mkdir(parents=True, exist_ok=True)
    content = b'{"fixture":"publication metadata only; no students"}\n'
    manifest.write_bytes(content)
    record = PublicationRecord(
        schema_version="1",
        record_type="publication_record",
        publication_id=PUBLICATION_ID,
        work=WORK,
        source_record=None,
        publication_kind="academic_result_set",
        capabilities=("points",),
        record_set_id=RECORD_SET,
        record_set_revision=1,
        manifest_contract_version="v1",
        manifest_path=manifest.relative_to(root).as_posix(),
        manifest_digest_algorithm="sha256",
        manifest_digest=hashlib.sha256(content).hexdigest(),
        published_at=STAMP + timedelta(hours=2),
        academic_work_registration_revision=1,
        supersedes_publication_id=None,
    )
    write_publication_record(root, record)
    rebuild_academic_catalog(root)
    return record


def _existing(root: Path) -> None:
    digest = _grade_written(root)
    assert len(digest) == 64
    select_grade_item_revision(root, CLASS, GRADE, 1, expected_current_revision=None)
    assert get_current_grade_item_revision(root, CLASS, GRADE) == 1


def _existing_answers(confirmation: str = "APPLY") -> tuple[str, ...]:
    return (
        "1",  # Marking period
        "1",  # Exact named registered work
        "S",  # Setup
        "1",  # Exact existing Grade Item, no raw canonical ID
        "",  # Rationale
        ACTOR.actor_id,  # Saved teacher attribution
        confirmation,
        "",  # Read reviewed disposition
    )


def test_published_discovery_is_exact_and_does_not_grant_evidence(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    publication = _publish(root)
    before = _all_bytes(root)
    choices = load_named_assessment_choices(
        root, class_id=CLASS, school_year="2026-2027", period_id="mp1"
    )
    assert len(choices.items) == 1
    selected = choices.items[0]
    assert selected.candidate.work == WORK
    assert selected.publication_state == "current_results_verified"
    assert selected.candidate.publication_id == publication.publication_id
    assert selected.candidate.setup_state == "needs_create"
    assert publication.publication_id not in selected.choice.label
    assert _all_bytes(root) == before
    assert AssessmentSetupCorrelationStore(root, CLASS).list_records() == ()
    assert TeacherActionReceiptStore(root, CLASS).list_receipts() == ()


def test_published_assessment_one_confirmation_retains_exact_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    publication = _publish(root)
    journey = _journey(root, monkeypatch, _first_setup_answers())
    assert "Assessment relationship verified current." in journey.output
    assert journey.prompts.count("Confirmation: ") == 1
    assert journey.reviews[0].publication_id == publication.publication_id
    assert journey.reviews[0].kind == "create_and_link"
    assert journey.session.active_work == WORK
    assert journey.session.active_grade_item_id == GRADE
    assert journey.session.active_publication_id == publication.publication_id
    assert get_current_grade_item_revision(root, CLASS, GRADE) == 1
    linked = load_current_grade_item_membership_decision(root, CLASS, GRADE, WORK)
    assert linked is not None and linked.decision.decision == "included"
    assert _correlation(root).stage == "membership_bound"
    assert (
        get_current_publication_record(root, WORK, "academic_result_set", RECORD_SET)
        == publication
    )


def test_published_ready_reopen_preserves_publication_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    publication = _publish(root)
    _journey(root, monkeypatch, _first_setup_answers())
    before = _all_bytes(root)
    again = _journey(root, monkeypatch, ("1", "1", "S", ""))
    assert "Assessment relationship verified current." in again.output
    assert again.prompts.count("Confirmation: ") == 0
    assert again.reviews[0].kind == "already_ready"
    assert again.session.active_work == WORK
    assert again.session.active_publication_id == publication.publication_id
    assert again.session.active_grade_item_id == GRADE
    assert _all_bytes(root) == before


def test_existing_grade_item_links_exactly_once_with_one_teacher_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _existing(root)
    before_grade_history = list_grade_item_revisions(root, CLASS, GRADE)
    journey = _journey(root, monkeypatch, _existing_answers())
    assert "Assessment relationship verified current." in journey.output
    assert journey.prompts.count("Confirmation: ") == 1
    assert journey.reviews[0].kind == "use_existing"
    assert journey.reviews[0].grade_item_id == GRADE
    assert journey.session.active_work == WORK
    assert journey.session.active_grade_item_id == GRADE
    assert list_grade_item_revisions(root, CLASS, GRADE) == before_grade_history
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == (1,)
    linked = load_current_grade_item_membership_decision(root, CLASS, GRADE, WORK)
    assert linked is not None and linked.decision.decision == "included"
    assert linked.decision.academic_period is not None
    assert linked.decision.academic_period.period.period_id == "mp1"
    record = _correlation(root)
    assert record.kind == "use_existing"
    assert record.grade_action_id is None
    assert record.membership_action_id is not None
    action_ids = {
        entry.preview.action_id
        for entry in TeacherActionReceiptStore(root, CLASS).list_receipts()
    }
    assert action_ids == {record.membership_action_id}


def test_published_assessment_links_existing_item_and_preserves_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    published = _publish(root)
    _existing(root)
    journey = _journey(root, monkeypatch, _existing_answers())
    assert "Assessment relationship verified current." in journey.output
    assert journey.prompts.count("Confirmation: ") == 1
    assert journey.reviews[0].kind == "use_existing"
    assert journey.reviews[0].publication_id == published.publication_id
    assert journey.session.active_publication_id == published.publication_id
    assert journey.session.active_grade_item_id == GRADE
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == (1,)
    assert _correlation(root).grade_action_id is None


def test_existing_relation_reopens_zero_write_without_duplicate_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _existing(root)
    _journey(root, monkeypatch, _existing_answers())
    before = _all_bytes(root)
    again = _journey(root, monkeypatch, ("1", "1", "S", ""))
    assert "Assessment relationship verified current." in again.output
    assert "Confirmation: " not in again.prompts
    assert again.reviews[0].kind == "already_ready"
    assert again.session.active_grade_item_id == GRADE
    assert _all_bytes(root) == before
    assert list_grade_item_revisions(root, CLASS, GRADE) == (1,)
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == (1,)


def test_cancel_existing_link_has_no_membership_or_receipt_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _existing(root)
    before = _all_bytes(root)
    answers = (*_existing_answers("B")[:-1], "B", "B")
    journey = _journey(root, monkeypatch, answers)
    assert "Cancelled. No setup action requested." in journey.output
    assert journey.prompts.count("Confirmation: ") == 1
    assert journey.session.active_work is None
    assert _all_bytes(root) == before
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, WORK) == ()
    assert AssessmentSetupCorrelationStore(root, CLASS).list_records() == ()
    assert TeacherActionReceiptStore(root, CLASS).list_receipts() == ()


def test_withdrawn_publication_requires_review_before_new_setup(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    publication = _publish(root)
    write_publication_withdrawal(
        root,
        PublicationWithdrawal(
            schema_version="1",
            record_type="publication_withdrawal",
            publication_id=publication.publication_id,
            withdrawn_at=STAMP + timedelta(days=1),
            reason="synthetic source withdrawn",
        ),
    )
    rebuild_academic_catalog(root)
    choices = load_named_assessment_choices(
        root, class_id=CLASS, school_year="2026-2027", period_id="mp1"
    )
    assert len(choices.items) == 1
    assert choices.items[0].publication_state == "withdrawn_results"
    before = _all_bytes(root)
    with pytest.raises(AssessmentSetupPreviewError, match="history needs review"):
        load_assessment_setup_preview(
            root,
            class_id=CLASS,
            school_year="2026-2027",
            period_id="mp1",
            work=WORK,
            dependencies=GuidedGradeItemBridgeDependencies(),
            purpose="standards_proficiency",
            new_title="Scene",
            actor_attribution=ACTOR.actor_id,
        )
    assert _all_bytes(root) == before
    assert AssessmentSetupCorrelationStore(root, CLASS).list_records() == ()
    assert TeacherActionReceiptStore(root, CLASS).list_receipts() == ()
