from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

import meridian.grouping_signal_export_eligibility as export_eligibility
import meridian.planning_signal_preview_review_explanation as under_test
from meridian.grade_item_proficiency_explanation import (
    ExplanationTraceIntegrityError,
    ExplanationTraceNotFoundError,
    ExplanationTraceTargetError,
)
from meridian.grouping_signal_derivation import GroupingSignalDerivationReference
from meridian.grouping_signal_preview import (
    GroupingSignalPreviewCurrentness,
    build_grouping_signal_preview_snapshot,
    grouping_signal_preview_reference,
)
from meridian.grouping_signal_preview_storage import write_grouping_signal_preview
from meridian.grouping_signal_review import create_grouping_signal_review_decision
from meridian.grouping_signal_review_storage import (
    select_grouping_signal_review_revision,
    write_grouping_signal_review_revision,
)
from meridian.planning_signal_preview_review_explanation import (
    PlanningSignalPreviewReviewTraceTarget,
    explain_planning_signal_preview_review,
    planning_signal_preview_review_explanation_to_json_bytes,
    render_planning_signal_preview_review_explanation_text,
)
from tests.test_planning_signal_derivation_explanation import (
    CLASS_ID,
    NOW,
    PERIOD_ID,
    SCHOOL_YEAR,
    STANDARD_ID,
    _grouping_policy,
    _period_policy,
    _prepared,
    _scale,
)


def _target(
    preview_id: str,
    *,
    selection: str = "selected",
    revision: int | None = None,
) -> PlanningSignalPreviewReviewTraceTarget:
    return PlanningSignalPreviewReviewTraceTarget(
        class_id=CLASS_ID,
        preview_id=preview_id,
        review_selection=selection,  # type: ignore[arg-type]
        review_revision=revision,
    )


def _stored_preview(root: Path, derivation):
    scale = _scale()
    policy = _grouping_policy(scale, _period_policy(scale))
    snapshot = build_grouping_signal_preview_snapshot(
        derivation.snapshot,
        policy,
        scale,
        GroupingSignalPreviewCurrentness(
            "current",
            (),
            derivation.reference,
        ),
    )
    return write_grouping_signal_preview(root, snapshot).stored


def _review(stored_preview, revision: int, *, decision: str = "accepted_for_export"):
    preview = stored_preview.snapshot
    warning_ids = tuple(
        sorted(
            item.diagnostic_id
            for item in preview.diagnostics
            if item.severity == "warning"
        )
    )
    return create_grouping_signal_review_decision(
        preview,
        grouping_signal_preview_reference(preview),
        review_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision=decision,  # type: ignore[arg-type]
        acknowledged_warning_ids=(
            warning_ids if decision == "accepted_for_export" else ()
        ),
        actor_id="teacher_local",
        reviewed_at=NOW + timedelta(minutes=revision),
    )


def _patch_live_currentness(
    monkeypatch: pytest.MonkeyPatch,
    value: GroupingSignalPreviewCurrentness,
) -> None:
    monkeypatch.setattr(
        under_test,
        "assess_grouping_signal_derivation_currentness",
        lambda *args, **kwargs: value,
    )
    monkeypatch.setattr(
        export_eligibility,
        "assess_grouping_signal_derivation_currentness",
        lambda *args, **kwargs: value,
    )


def _currentness(derivation) -> GroupingSignalPreviewCurrentness:
    return GroupingSignalPreviewCurrentness(
        "current",
        (),
        derivation.reference,
    )


def _stale_currentness() -> GroupingSignalPreviewCurrentness:
    changed = GroupingSignalDerivationReference(
        CLASS_ID,
        "gsd_" + "a" * 64,
        "b" * 64,
    )
    return GroupingSignalPreviewCurrentness(
        "stale",
        ("source_proficiency_changed",),
        changed,
    )


def test_target_requires_exact_preview_and_explicit_review_semantics() -> None:
    with pytest.raises(ExplanationTraceTargetError):
        _target("latest")
    with pytest.raises(ExplanationTraceTargetError):
        _target("gsp_" + "A" * 64)
    with pytest.raises(ExplanationTraceTargetError):
        _target("gsp_" + "0" * 64, selection="selected", revision=1)
    with pytest.raises(ExplanationTraceTargetError):
        _target("gsp_" + "0" * 64, selection="revision")


def test_missing_exact_preview_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(ExplanationTraceNotFoundError):
        explain_planning_signal_preview_review(
            tmp_path,
            _target("gsp_" + "0" * 64),
        )


def test_selected_mode_without_review_is_ready_for_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    preview = _stored_preview(root, derivation)
    _patch_live_currentness(monkeypatch, _currentness(derivation))

    explained = explain_planning_signal_preview_review(
        root,
        _target(preview.snapshot.preview_id),
    )

    assert explained.path_state == "ready_for_review"
    assert explained.review is None
    assert explained.export_eligibility.eligible is False
    assert explained.export_eligibility.block_code == "no_selected_review"
    assert explained.snapshot_currentness.state == "current"
    assert explained.live_currentness.state == "current"
    assert explained.warning_diagnostic_ids
    assert not explained.blocking_diagnostic_ids
    assert explained.nested_derivation_explanation.derivation_id == (
        derivation.snapshot.derivation_id
    )


def test_exact_accepted_review_can_be_explained_without_being_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    preview = _stored_preview(root, derivation)
    review = _review(preview, 1)
    write_grouping_signal_review_revision(root, review)
    _patch_live_currentness(monkeypatch, _currentness(derivation))

    explained = explain_planning_signal_preview_review(
        root,
        _target(
            preview.snapshot.preview_id,
            selection="revision",
            revision=1,
        ),
    )

    assert explained.path_state == "accepted_but_not_selected"
    assert explained.review is not None
    assert explained.review.selection_state == "not_selected"
    assert explained.review.decision == "accepted_for_export"
    assert explained.review.acknowledged_warning_ids == (
        explained.warning_diagnostic_ids
    )
    assert explained.review.rationale is None
    assert explained.review.rationale_status == (
        "not_represented_by_grouping_signal_review_v1"
    )
    assert explained.export_eligibility.block_code == "no_selected_review"


def test_selected_accepted_review_is_export_eligible_when_derivation_is_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    preview = _stored_preview(root, derivation)
    review = _review(preview, 1)
    write_grouping_signal_review_revision(root, review)
    select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        derivation.snapshot.derivation_id,
        1,
        expected_current_review_revision=None,
    )
    _patch_live_currentness(monkeypatch, _currentness(derivation))

    explained = explain_planning_signal_preview_review(
        root,
        _target(preview.snapshot.preview_id),
    )

    assert explained.path_state == "selected_and_export_eligible"
    assert explained.review is not None
    assert explained.review.selection_state == "selected"
    assert explained.review.applicability_status == "current"
    assert explained.export_eligibility.eligible is True
    assert explained.export_eligibility.target_preview_is_authorized_path is True


def test_selected_accepted_review_reports_live_staleness_without_rewriting_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    preview = _stored_preview(root, derivation)
    review = _review(preview, 1)
    write_grouping_signal_review_revision(root, review)
    select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        derivation.snapshot.derivation_id,
        1,
        expected_current_review_revision=None,
    )
    stale = _stale_currentness()
    _patch_live_currentness(monkeypatch, stale)

    explained = explain_planning_signal_preview_review(
        root,
        _target(preview.snapshot.preview_id),
    )

    assert explained.snapshot_currentness.state == "current"
    assert explained.live_currentness.state == "stale"
    assert explained.path_state == "selected_but_stale"
    assert explained.review is not None
    assert explained.review.applicability_status == "stale"
    assert explained.export_eligibility.block_code == "review_stale"
    assert explained.export_eligibility.reason_codes == (
        "source_proficiency_changed",
    )


def test_selected_rejected_review_is_not_export_eligible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    preview = _stored_preview(root, derivation)
    review = _review(preview, 1, decision="rejected")
    write_grouping_signal_review_revision(root, review)
    select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        derivation.snapshot.derivation_id,
        1,
        expected_current_review_revision=None,
    )
    _patch_live_currentness(monkeypatch, _currentness(derivation))

    explained = explain_planning_signal_preview_review(
        root,
        _target(preview.snapshot.preview_id),
    )

    assert explained.path_state == "not_export_eligible"
    assert explained.review is not None
    assert explained.review.decision == "rejected"
    assert explained.review.applicability_status == "not_accepted"
    assert explained.export_eligibility.block_code == "review_not_accepted"


def test_missing_exact_derivation_under_preview_is_integrity_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    preview = _stored_preview(root, derivation)
    derivation.path.unlink()
    Path(str(derivation.path) + ".sha256").unlink()

    with pytest.raises(ExplanationTraceIntegrityError):
        explain_planning_signal_preview_review(
            root,
            _target(preview.snapshot.preview_id),
        )


def test_json_and_text_preserve_review_diagnostics_and_path_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, derivation = _prepared(tmp_path, monkeypatch)
    preview = _stored_preview(root, derivation)
    review = _review(preview, 1)
    write_grouping_signal_review_revision(root, review)
    _patch_live_currentness(monkeypatch, _currentness(derivation))

    explained = explain_planning_signal_preview_review(
        root,
        _target(
            preview.snapshot.preview_id,
            selection="revision",
            revision=1,
        ),
    )
    payload = planning_signal_preview_review_explanation_to_json_bytes(
        explained
    ).decode("utf-8")
    text = render_planning_signal_preview_review_explanation_text(explained)

    assert '"path_state": "accepted_but_not_selected"' in payload
    assert '"rationale_status":' in payload
    assert '"warning_diagnostic_ids":' in payload
    assert "path_state: accepted_but_not_selected" in text
    assert "review_rationale: not represented" in text
    assert "warning_acknowledgments:" in text


# Keep imported exact target constants exercised in this integration fixture.
def test_fixture_scope_is_exact() -> None:
    assert SCHOOL_YEAR == "2026-2027"
    assert PERIOD_ID == "mp1"
    assert STANDARD_ID.startswith("urn:")
