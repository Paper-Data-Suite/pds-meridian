from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.standards_association_selection_workflow as workflow
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.projection_cache import AuthorizedProjectionSnapshot
from meridian.standards_review_workflow import StandardsReviewProjection

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STANDARD_ID = "NJSLSA.R1"
STUDENT_ID = "student_001"
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
WORK = ModuleWorkRef(
    module_id="scoreform",
    class_id=CLASS_ID,
    work_id="test_1",
)
SOURCE = EvidenceSourceReference(
    work=WORK,
    publication_id=PUBLICATION_ID,
    cache_key=CACHE_KEY,
    snapshot_digest=SNAPSHOT_DIGEST,
    item_id="scoreform_item_1",
)
SCALE = ProficiencyScaleReference(
    class_id=CLASS_ID,
    scale_id="four_level",
    scale_revision=2,
    scale_sha256="a" * 64,
)


def authorized() -> AuthorizedProjectionSnapshot:
    publication = SimpleNamespace(
        work=WORK,
        publication_id=PUBLICATION_ID,
    )
    return cast(
        AuthorizedProjectionSnapshot,
        SimpleNamespace(
            stored=SimpleNamespace(
                cache_key=CACHE_KEY,
                snapshot_digest=SNAPSHOT_DIGEST,
                snapshot=SimpleNamespace(
                    source=SimpleNamespace(publication=publication),
                ),
            )
        ),
    )


def projection() -> StandardsReviewProjection:
    return cast(
        StandardsReviewProjection,
        SimpleNamespace(
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            student_id=STUDENT_ID,
            standard_id=STANDARD_ID,
            item_id=SOURCE.item_id,
            source=SOURCE,
            target_scale=SCALE,
            mapping_profile=None,
        ),
    )


def target(
    revision: int = 1,
    *,
    disposition: str = "not_associated",
    basis: str = "explicit",
) -> object:
    decision = SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        source=SOURCE,
        standard_id=STANDARD_ID,
        association_revision=revision,
        disposition=disposition,
        basis=basis,
    )
    content = f"revision-{revision}".encode()
    return SimpleNamespace(
        decision=decision,
        decision_sha256=("b" if revision == 1 else "c") * 64,
        content=content,
    )


def install_runtime_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "AuthorizedProjectionSnapshot",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "StandardsReviewProjection",
        SimpleNamespace,
    )


def install_preview_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    selected_revision: int | None = 2,
) -> tuple[
    StandardsReviewProjection,
    AuthorizedProjectionSnapshot,
    object,
]:
    install_runtime_types(monkeypatch)
    reviewed = projection()
    auth = authorized()
    stored = target()
    monkeypatch.setattr(
        workflow,
        "build_standards_review_projection",
        lambda *args, **kwargs: reviewed,
    )
    monkeypatch.setattr(
        workflow,
        "list_standard_evidence_association_revisions",
        lambda *args, **kwargs: (1, 2),
    )
    monkeypatch.setattr(
        workflow,
        "load_standard_evidence_association_revision",
        lambda *args, **kwargs: stored,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_standard_evidence_association_revision",
        lambda *args, **kwargs: selected_revision,
    )
    return reviewed, auth, stored


def test_preview_exact_historical_revision_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, stored = install_preview_state(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "select_standard_evidence_association_revision",
        lambda *args, **kwargs: pytest.fail("preview must not select"),
    )

    preview = workflow.preview_standards_association_selection(
        "workspace",
        reviewed,
        authorized_snapshot=auth,
        association_revision=1,
    )

    assert preview.target is stored
    assert preview.target_revision == 1
    assert preview.target_disposition == "not_associated"
    assert preview.target_basis == "explicit"
    assert preview.history == (1, 2)
    assert preview.expected_current_association_revision == 2
    assert preview.authoring_action == "not_performed"


def test_preview_rejects_revision_outside_exact_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, _ = install_preview_state(monkeypatch)

    with pytest.raises(
        workflow.StandardsAssociationSelectionScopeError,
        match="exact persisted revision",
    ):
        workflow.preview_standards_association_selection(
            "workspace",
            reviewed,
            authorized_snapshot=auth,
            association_revision=3,
        )


def test_commit_selects_exact_target_with_revision_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, stored = install_preview_state(monkeypatch)
    preview = workflow.preview_standards_association_selection(
        "workspace",
        reviewed,
        authorized_snapshot=auth,
        association_revision=1,
    )
    monkeypatch.setattr(
        workflow,
        "load_standard_evidence_association_revision",
        lambda *args, **kwargs: stored,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_standard_evidence_association_revision",
        lambda *args, **kwargs: 2,
    )
    observed: dict[str, object] = {}

    def select(*args: object, **kwargs: object) -> object:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return SimpleNamespace(
            disposition="updated",
            selection=SimpleNamespace(association_revision=1),
            stored=stored,
        )

    monkeypatch.setattr(
        workflow,
        "select_standard_evidence_association_revision",
        select,
    )

    result = workflow.commit_standards_association_selection_preview(
        "workspace",
        preview,
        authorized_snapshot=auth,
    )

    assert observed["args"] == (
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        SOURCE,
        STANDARD_ID,
        1,
    )
    assert observed["kwargs"] == {
        "expected_current_association_revision": 2,
    }
    assert result.previous_current_revision == 2
    assert result.selected_revision == 1
    assert result.selected_disposition == "not_associated"
    assert result.selected_basis == "explicit"
    assert result.selection_disposition == "updated"
    assert result.authoring_action == "not_performed"


def test_commit_rejects_review_projection_drift_before_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, _ = install_preview_state(monkeypatch)
    preview = workflow.preview_standards_association_selection(
        "workspace",
        reviewed,
        authorized_snapshot=auth,
        association_revision=1,
    )
    changed = projection()
    changed.standard_id = "NJSLSA.R2"
    monkeypatch.setattr(
        workflow,
        "build_standards_review_projection",
        lambda *args, **kwargs: changed,
    )
    monkeypatch.setattr(
        workflow,
        "select_standard_evidence_association_revision",
        lambda *args, **kwargs: pytest.fail("stale review must not select"),
    )

    with pytest.raises(
        workflow.StandardsAssociationSelectionStaleError,
        match="projection changed",
    ):
        workflow.commit_standards_association_selection_preview(
            "workspace",
            preview,
            authorized_snapshot=auth,
        )


def test_commit_rejects_history_change_before_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, _ = install_preview_state(monkeypatch)
    preview = workflow.preview_standards_association_selection(
        "workspace",
        reviewed,
        authorized_snapshot=auth,
        association_revision=1,
    )
    monkeypatch.setattr(
        workflow,
        "list_standard_evidence_association_revisions",
        lambda *args, **kwargs: (1, 2, 3),
    )
    monkeypatch.setattr(
        workflow,
        "select_standard_evidence_association_revision",
        lambda *args, **kwargs: pytest.fail("stale history must not select"),
    )

    with pytest.raises(
        workflow.StandardsAssociationSelectionStaleError,
        match="history changed",
    ):
        workflow.commit_standards_association_selection_preview(
            "workspace",
            preview,
            authorized_snapshot=auth,
        )


def test_commit_rejects_target_bytes_change_before_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, _ = install_preview_state(monkeypatch)
    preview = workflow.preview_standards_association_selection(
        "workspace",
        reviewed,
        authorized_snapshot=auth,
        association_revision=1,
    )
    changed = target(disposition="associated")
    monkeypatch.setattr(
        workflow,
        "load_standard_evidence_association_revision",
        lambda *args, **kwargs: changed,
    )
    monkeypatch.setattr(
        workflow,
        "select_standard_evidence_association_revision",
        lambda *args, **kwargs: pytest.fail("changed target must not select"),
    )

    with pytest.raises(
        workflow.StandardsAssociationSelectionStaleError,
        match="Target association revision changed",
    ):
        workflow.commit_standards_association_selection_preview(
            "workspace",
            preview,
            authorized_snapshot=auth,
        )


def test_commit_rejects_current_selector_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed, auth, stored = install_preview_state(monkeypatch)
    preview = workflow.preview_standards_association_selection(
        "workspace",
        reviewed,
        authorized_snapshot=auth,
        association_revision=1,
    )
    monkeypatch.setattr(
        workflow,
        "load_standard_evidence_association_revision",
        lambda *args, **kwargs: stored,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_standard_evidence_association_revision",
        lambda *args, **kwargs: 3,
    )
    monkeypatch.setattr(
        workflow,
        "select_standard_evidence_association_revision",
        lambda *args, **kwargs: pytest.fail("stale selector must not select"),
    )

    with pytest.raises(
        workflow.StandardsAssociationSelectionStaleError,
        match="Current association selection changed",
    ):
        workflow.commit_standards_association_selection_preview(
            "workspace",
            preview,
            authorized_snapshot=auth,
        )
