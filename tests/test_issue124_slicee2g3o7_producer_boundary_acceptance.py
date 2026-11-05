"""#124 E2G3O7: producer-distinct canonical provenance and adversarial setup.

All workspace data are synthetic. Publication manifests are SHA-256-bound
placeholders, NOT producer-generated result manifests. The tested authority is
Core registration/publication + Meridian Grade Item setup, not result grading.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from pds_core.academic_catalog import rebuild_academic_catalog
from pds_core.academic_period_storage import (
    load_current_academic_period_calendar,
    write_academic_period_calendar,
)
from pds_core.academic_work_registration_storage import write_academic_work_registration
from pds_core.publication_records import PublicationRecord, PublicationWithdrawal
from pds_core.publication_storage import (
    write_publication_record,
    write_publication_withdrawal,
)
from pds_core.routes import module_work_dir
from pds_core.routing_models import ModuleWorkRef
from test_issue124_slicee2g3k_composite_canonical import (
    ACTOR,
    CLASS,
    GRADE,
    STAMP,
    YEAR,
    _all_bytes,
    _registration,
    _workspace,
)
from test_issue124_slicee2g3o4_canonical_teacher_acceptance import (
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
from meridian.grade_item_storage import get_current_grade_item_revision
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.teacher_action_receipts import TeacherActionReceiptStore


def _register(
    root: Path,
    module: str,
    *,
    title: str,
    intent: str = "summative",
) -> ModuleWorkRef:
    """Add one canonical synthetic producer registration to the Core workspace."""
    work = ModuleWorkRef(module, CLASS, "scene")
    module_work_dir(root, work).mkdir(parents=True, exist_ok=True)
    registered = replace(
        _registration(), work=work, title=title, academic_intent=intent
    )
    write_academic_work_registration(root, registered, expected_current_revision=None)
    rebuild_academic_catalog(root)
    return work


def _publish_provenance(
    root: Path, work: ModuleWorkRef, *, capability: str
) -> PublicationRecord:
    """Write Core provenance only, never a native producer results manifest."""
    relative = (
        Path("classes")
        / CLASS
        / "modules"
        / work.module_id
        / "work"
        / work.work_id
        / "exports"
        / "manifests"
        / "academic_results"
        / "synthetic.json"
    )
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = b'{"synthetic":"provenance only - no student results"}\n'
    target.write_bytes(raw)
    record = PublicationRecord(
        schema_version="1",
        record_type="publication_record",
        publication_id="pub_" + ("d" if work.module_id == "quillan" else "e") * 32,
        work=work,
        source_record=None,
        publication_kind="academic_result_set",
        capabilities=(capability,),
        record_set_id="assessment_results",
        record_set_revision=1,
        manifest_contract_version="v1",
        manifest_path=relative.as_posix(),
        manifest_digest_algorithm="sha256",
        manifest_digest=hashlib.sha256(raw).hexdigest(),
        published_at=STAMP + timedelta(hours=2),
        academic_work_registration_revision=1,
        supersedes_publication_id=None,
    )
    write_publication_record(root, record)
    rebuild_academic_catalog(root)
    return record


def _named(root: Path, work: ModuleWorkRef) -> object:
    named = load_named_assessment_choices(
        root, class_id=CLASS, school_year=YEAR, period_id="mp1"
    )
    result = [entry for entry in named.items if entry.candidate.work == work]
    assert len(result) == 1
    return result[0]


def test_quillan_standards_ratings_publication_has_correct_provenance(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    work = _register(
        root, "quillan", title="A Quillan Standards Check", intent="formative"
    )
    published = _publish_provenance(root, work, capability="standards_ratings")
    before = _all_bytes(root)
    entry = _named(root, work)
    assert entry.candidate.publication_id == published.publication_id
    assert entry.publication_state == "current_results_verified"
    assert entry.candidate.setup_state == "needs_create"
    assert entry.choice.source == "Quillan"
    assert "published" in entry.choice.display.casefold()
    assert _all_bytes(root) == before
    assert TeacherActionReceiptStore(root, CLASS).list_receipts() == ()


def test_quillan_formative_work_requires_explicit_purpose_and_one_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    work = _register(
        root, "quillan", title="A Quillan Standards Check", intent="formative"
    )
    published = _publish_provenance(root, work, capability="standards_ratings")
    journey = _journey(root, monkeypatch, _first_setup_answers())
    assert "Assessment relationship verified current." in journey.output
    assert journey.prompts.count("Confirmation: ") == 1
    assert journey.reviews[0].grade_item_purpose == "standards_proficiency"
    assert journey.session.active_work == work
    assert journey.session.active_publication_id == published.publication_id
    assert get_current_grade_item_revision(root, CLASS, GRADE) == 1
    selected = load_current_grade_item_membership_decision(root, CLASS, GRADE, work)
    assert selected is not None and selected.decision.decision == "included"
    assert selected.decision.academic_period is not None
    assert selected.decision.academic_period.period.period_id == "mp1"
    assert list_grade_item_membership_revisions(root, CLASS, GRADE, work) == (1,)


def test_quillan_published_ready_reopen_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    work = _register(root, "quillan", title="A Quillan Standards Check")
    publication = _publish_provenance(root, work, capability="standards_ratings")
    _journey(root, monkeypatch, _first_setup_answers())
    before = _all_bytes(root)
    reopened = _journey(root, monkeypatch, ("1", "1", "S", ""))
    assert reopened.reviews[0].kind == "already_ready"
    assert reopened.prompts.count("Confirmation: ") == 0
    assert reopened.session.active_work == work
    assert reopened.session.active_publication_id == publication.publication_id
    assert _all_bytes(root) == before


def test_concord_scored_core_publication_preserves_exact_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    work = _register(root, "concord", title="A Concord Scored Activity")
    publication = _publish_provenance(root, work, capability="criterion_scores")
    entry = _named(root, work)
    assert entry.publication_state == "current_results_verified"
    assert entry.choice.source == "Concord"
    journey = _journey(root, monkeypatch, _first_setup_answers())
    assert "Assessment relationship verified current." in journey.output
    assert journey.prompts.count("Confirmation: ") == 1
    assert journey.session.active_work == work
    assert journey.session.active_publication_id == publication.publication_id
    linked = load_current_grade_item_membership_decision(root, CLASS, GRADE, work)
    assert linked is not None and linked.decision.decision == "included"
    assert linked.decision.academic_period is not None
    assert linked.decision.academic_period.period.period_id == "mp1"
    assert get_current_grade_item_revision(root, CLASS, GRADE) == 1
    # Core's generic capability field does not establish Concord target
    # attribution or certify this placeholder as a producer-native manifest.


def test_concord_registration_without_scored_publication_blocks_setup(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    work = _register(root, "concord", title="A Concord Evidence-Only Activity")
    entry = _named(root, work)
    assert entry.publication_state == "no_results_indexed"
    before = _all_bytes(root)
    with pytest.raises(AssessmentSetupPreviewError, match="Unpublished Concord"):
        load_assessment_setup_preview(
            root,
            class_id=CLASS,
            school_year=YEAR,
            period_id="mp1",
            work=work,
            dependencies=GuidedGradeItemBridgeDependencies(),
            purpose="reporting_only",
            new_title="Scene",
            actor_attribution=ACTOR.actor_id,
        )
    assert _all_bytes(root) == before
    assert AssessmentSetupCorrelationStore(root, CLASS).list_records() == ()
    assert TeacherActionReceiptStore(root, CLASS).list_receipts() == ()


def test_two_producers_with_same_title_are_visibly_disambiguated(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    work = _register(root, "quillan", title="Synthetic Scene Study")
    before = _all_bytes(root)
    named = load_named_assessment_choices(
        root, class_id=CLASS, school_year=YEAR, period_id="mp1"
    )
    assert len(named.items) == 2
    display = [entry.choice.display for entry in named.items]
    assert len(set(display)) == 2
    assert any("Quillan" in label for label in display)
    assert any("ScoreForm" in label for label in display)
    assert {_entry.candidate.work.module_id for _entry in named.items} == {
        work.module_id,
        "scoreform",
    }
    assert _all_bytes(root) == before


def test_published_quillan_withdrawn_at_apply_fails_before_new_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    work = _register(root, "quillan", title="A Quillan Standards Check")
    publication = _publish_provenance(root, work, capability="standards_ratings")

    def withdraw() -> None:
        write_publication_withdrawal(
            root,
            PublicationWithdrawal(
                schema_version="1",
                record_type="publication_withdrawal",
                publication_id=publication.publication_id,
                withdrawn_at=STAMP + timedelta(days=1),
                reason="synthetic withdrawal during confirmation",
            ),
        )
        rebuild_academic_catalog(root)

    journey = _journey(
        root, monkeypatch, _first_setup_answers(), on_confirmation=withdraw
    )
    assert "Assessment setup is not verified ready." in journey.output
    assert journey.prompts.count("Confirmation: ") == 1
    assert journey.session.active_work is None
    assert get_current_grade_item_revision(root, CLASS, GRADE) is None
    assert TeacherActionReceiptStore(root, CLASS).list_receipts() == ()
    assert AssessmentSetupCorrelationStore(root, CLASS).list_records() == ()


def test_marking_period_revision_drift_at_apply_fails_without_grade_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)

    def update_calendar() -> None:
        current = load_current_academic_period_calendar(root, YEAR)
        assert current is not None
        amended = replace(
            current,
            calendar_revision=current.calendar_revision + 1,
            updated_at=STAMP + timedelta(days=1),
        )
        write_academic_period_calendar(
            root, amended, expected_current_revision=current.calendar_revision
        )
        rebuild_academic_catalog(root)

    journey = _journey(
        root, monkeypatch, _first_setup_answers(), on_confirmation=update_calendar
    )
    assert "Assessment setup is not verified ready." in journey.output
    assert journey.prompts.count("Confirmation: ") == 1
    assert journey.session.active_work is None
    assert get_current_grade_item_revision(root, CLASS, GRADE) is None
    assert TeacherActionReceiptStore(root, CLASS).list_receipts() == ()
    assert AssessmentSetupCorrelationStore(root, CLASS).list_records() == ()
