from __future__ import annotations

from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.new_evidence_eligibility_selection_workflow as workflow
from meridian.evidence_eligibility import (
    EvidenceSourceReference,
    EvidenceSourceStateObservation,
)
from meridian.new_evidence_workflow import (
    NewEvidenceReview,
    NewEvidenceRow,
    NewEvidenceStatusSummary,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
ITEM_ID = "scoreform_item_1"
PUBLICATION_ID = "pub_" + "1" * 32
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
MEMBERSHIP_DIGEST = "4" * 64
TARGET_DIGEST = "5" * 64
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")


def _source() -> EvidenceSourceReference:
    return EvidenceSourceReference(
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        item_id=ITEM_ID,
    )


def _source_state() -> EvidenceSourceStateObservation:
    return EvidenceSourceStateObservation(
        state="current",
        head_publication_id=PUBLICATION_ID,
        successor_publication_id=None,
        withdrawn_at=None,
    )


def _row(*, selected_revision: int | None = 2) -> NewEvidenceRow:
    return NewEvidenceRow(
        source=_source(),
        student_id="student_1",
        target_kind="question",
        target_id="q1",
        standard_ids=("RL.CR.9-10.1",),
        result_kind="question_score",
        membership_state="included",
        eligibility_status=(
            "excluded" if selected_revision is not None else "no_decision"
        ),
        selected_eligibility_revision=selected_revision,
        selected_eligibility_disposition=(
            "excluded" if selected_revision is not None else None
        ),
        eligibility_source_state="current" if selected_revision is not None else None,
        operative_included=False,
        attention_required=selected_revision is None,
        recommended_task=None if selected_revision is not None else "exclusions",
    )


def _review(*, selected_revision: int | None = 2) -> NewEvidenceReview:
    return NewEvidenceReview(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        projection_source_status="current",
        membership_state="included",
        membership_revision=3,
        academic_period_id="mp1",
        academic_period_calendar_revision=4,
        rows=(_row(selected_revision=selected_revision),),
        status_summary=(
            NewEvidenceStatusSummary(
                status=(
                    "eligibility_excluded"
                    if selected_revision is not None
                    else "eligibility_no_decision"
                ),
                count=1,
            ),
        ),
        attention_count=0 if selected_revision is not None else 1,
    )


def _authorized() -> object:
    return SimpleNamespace(
        stored=SimpleNamespace(
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
            snapshot=SimpleNamespace(
                source=SimpleNamespace(
                    publication=SimpleNamespace(
                        work=WORK,
                        publication_id=PUBLICATION_ID,
                    )
                )
            ),
        )
    )


def _target(revision: int = 1) -> object:
    return SimpleNamespace(
        decision=SimpleNamespace(
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            source=_source(),
            membership_revision=3,
            eligibility_revision=revision,
            disposition="included",
        ),
        decision_sha256=TARGET_DIGEST,
    )


def _membership() -> object:
    return SimpleNamespace(
        decision=SimpleNamespace(
            decision="included",
            membership_revision=3,
        ),
        decision_sha256=MEMBERSHIP_DIGEST,
    )


def _install_preview_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_revision: int = 1,
    selected_revision: int | None = 2,
) -> tuple[object, object]:
    monkeypatch.setattr(workflow, "AuthorizedProjectionSnapshot", SimpleNamespace)
    authorized = _authorized()
    target = _target(target_revision)
    membership = _membership()
    monkeypatch.setattr(
        workflow,
        "project_new_evidence_review",
        lambda *args: _review(selected_revision=selected_revision),
    )
    monkeypatch.setattr(
        workflow,
        "load_evidence_eligibility_revision",
        lambda *args: target,
    )
    monkeypatch.setattr(
        workflow,
        "validate_evidence_eligibility_dependencies",
        lambda *args, **kwargs: SimpleNamespace(
            membership=membership,
            current_source_state=_source_state(),
        ),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_evidence_eligibility_revision",
        lambda *args: selected_revision,
    )
    return authorized, target


def test_preview_exact_persisted_revision_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorized, target = _install_preview_dependencies(monkeypatch)
    observed: dict[str, object] = {}

    def unexpected(*args: object, **kwargs: object) -> object:
        raise AssertionError("selection preview must not mutate current selection")

    monkeypatch.setattr(workflow, "select_evidence_eligibility_revision", unexpected)

    preview = workflow.preview_new_evidence_eligibility_selection(
        "workspace",
        _review(),
        authorized,  # type: ignore[arg-type]
        item_id=ITEM_ID,
        eligibility_revision=1,
    )

    assert preview.target is target
    assert preview.target_revision == 1
    assert preview.target_disposition == "included"
    assert preview.expected_current_revision == 2
    assert preview.membership_revision == 3
    assert preview.membership_revision_sha256 == MEMBERSHIP_DIGEST
    assert preview.source_state == _source_state()
    assert observed == {}


def test_commit_selects_exact_preview_with_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorized, target = _install_preview_dependencies(monkeypatch)
    preview = workflow.preview_new_evidence_eligibility_selection(
        "workspace",
        _review(),
        authorized,  # type: ignore[arg-type]
        item_id=ITEM_ID,
        eligibility_revision=1,
    )

    monkeypatch.setattr(
        workflow,
        "load_evidence_eligibility_revision",
        lambda *args: target,
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args: _membership(),
    )
    monkeypatch.setattr(
        workflow,
        "observe_evidence_source_state",
        lambda *args: _source_state(),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_evidence_eligibility_revision",
        lambda *args: 2,
    )
    observed: dict[str, object] = {}
    canonical_result = SimpleNamespace(
        disposition="updated",
        selection=SimpleNamespace(eligibility_revision=1),
        stored=SimpleNamespace(decision=SimpleNamespace(disposition="included")),
    )

    def fake_select(*args: object, **kwargs: object) -> object:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return canonical_result

    monkeypatch.setattr(workflow, "select_evidence_eligibility_revision", fake_select)

    result = workflow.commit_new_evidence_eligibility_selection_preview(
        "workspace",
        preview,
        authorized,  # type: ignore[arg-type]
    )

    assert observed["args"] == (
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        _source(),
        1,
    )
    assert observed["kwargs"] == {
        "authorized_snapshot": authorized,
        "expected_current_eligibility_revision": 2,
    }
    assert result.previous_current_revision == 2
    assert result.selected_revision == 1
    assert result.selected_disposition == "included"
    assert result.selection_disposition == "updated"


def test_commit_fails_if_current_selection_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorized, target = _install_preview_dependencies(monkeypatch)
    preview = workflow.preview_new_evidence_eligibility_selection(
        "workspace",
        _review(),
        authorized,  # type: ignore[arg-type]
        item_id=ITEM_ID,
        eligibility_revision=1,
    )
    monkeypatch.setattr(
        workflow,
        "load_evidence_eligibility_revision",
        lambda *args: target,
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args: _membership(),
    )
    monkeypatch.setattr(
        workflow,
        "observe_evidence_source_state",
        lambda *args: _source_state(),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_evidence_eligibility_revision",
        lambda *args: 3,
    )
    monkeypatch.setattr(
        workflow,
        "select_evidence_eligibility_revision",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("stale preview must fail before selection")
        ),
    )

    with pytest.raises(
        workflow.NewEvidenceEligibilitySelectionStaleError,
        match="Current eligibility selection changed",
    ):
        workflow.commit_new_evidence_eligibility_selection_preview(
            "workspace",
            preview,
            authorized,  # type: ignore[arg-type]
        )


def test_commit_fails_if_membership_or_source_lifecycle_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorized, target = _install_preview_dependencies(monkeypatch)
    preview = workflow.preview_new_evidence_eligibility_selection(
        "workspace",
        _review(),
        authorized,  # type: ignore[arg-type]
        item_id=ITEM_ID,
        eligibility_revision=1,
    )
    monkeypatch.setattr(
        workflow,
        "load_evidence_eligibility_revision",
        lambda *args: target,
    )
    changed_membership = SimpleNamespace(
        decision=SimpleNamespace(decision="included", membership_revision=4),
        decision_sha256="9" * 64,
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args: changed_membership,
    )
    with pytest.raises(
        workflow.NewEvidenceEligibilitySelectionStaleError,
        match="Grade Item membership changed",
    ):
        workflow.commit_new_evidence_eligibility_selection_preview(
            "workspace",
            preview,
            authorized,  # type: ignore[arg-type]
        )

    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_membership_decision",
        lambda *args: _membership(),
    )
    changed_state = EvidenceSourceStateObservation(
        state="superseded",
        head_publication_id="pub_" + "8" * 32,
        successor_publication_id="pub_" + "8" * 32,
        withdrawn_at=None,
    )
    monkeypatch.setattr(
        workflow,
        "observe_evidence_source_state",
        lambda *args: changed_state,
    )
    with pytest.raises(
        workflow.NewEvidenceEligibilitySelectionStaleError,
        match="source lifecycle changed",
    ):
        workflow.commit_new_evidence_eligibility_selection_preview(
            "workspace",
            preview,
            authorized,  # type: ignore[arg-type]
        )


def test_historical_revision_can_be_explicit_target_and_invalid_scope_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorized, _ = _install_preview_dependencies(
        monkeypatch,
        target_revision=1,
        selected_revision=2,
    )
    preview = workflow.preview_new_evidence_eligibility_selection(
        "workspace",
        _review(),
        authorized,  # type: ignore[arg-type]
        item_id=ITEM_ID,
        eligibility_revision=1,
    )
    assert preview.target_revision == 1
    assert preview.expected_current_revision == 2

    with pytest.raises(workflow.NewEvidenceEligibilitySelectionScopeError):
        workflow.preview_new_evidence_eligibility_selection(
            "workspace",
            _review(),
            authorized,  # type: ignore[arg-type]
            item_id=ITEM_ID,
            eligibility_revision=0,
        )
