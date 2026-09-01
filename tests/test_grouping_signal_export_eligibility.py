from __future__ import annotations

from pathlib import Path

import pytest

import meridian.grouping_signal_export_eligibility as export_eligibility
from meridian.grouping_signal_derivation import GroupingSignalDerivationReference
from meridian.grouping_signal_export_eligibility import (
    GroupingSignalExportBlockedError,
    resolve_grouping_signal_export_eligibility,
    revalidate_grouping_signal_export_eligibility,
)
from meridian.grouping_signal_preview import GroupingSignalPreviewCurrentness
from meridian.grouping_signal_review_storage import (
    select_grouping_signal_review_revision,
)
from meridian.grouping_signal_review_workflow import (
    record_grouping_signal_review,
)
from tests.test_grouping_signal_review_workflow import (
    CLASS_ID,
    NOW,
    _seed,
)


def _warning_ids(stored_preview) -> tuple[str, ...]:
    return tuple(
        sorted(
            item.diagnostic_id
            for item in stored_preview.snapshot.diagnostics
            if item.severity == "warning"
        )
    )


def _seed_selected_accepted_review(tmp_path: Path):
    root, stored_preview = _seed(tmp_path)
    recorded = record_grouping_signal_review(
        root,
        stored_preview.reference,
        review_revision=1,
        supersedes_revision=None,
        decision="accepted_for_export",
        acknowledged_warning_ids=_warning_ids(stored_preview),
        actor_id="teacher_local",
        reviewed_at=NOW,
    )
    derivation_id = recorded.stored.review.derivation_reference.derivation_id
    select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        derivation_id,
        1,
        expected_current_review_revision=None,
    )
    return root, stored_preview, recorded.stored


def test_resolve_uses_exact_selected_accepted_review_and_current_derivation(
    tmp_path: Path,
) -> None:
    root, stored_preview, stored_review = _seed_selected_accepted_review(
        tmp_path
    )

    eligibility = resolve_grouping_signal_export_eligibility(
        root,
        CLASS_ID,
        stored_review.review.derivation_reference.derivation_id,
    )

    assert eligibility.review_reference == stored_review.reference
    assert (
        eligibility.derivation_reference
        == stored_review.review.derivation_reference
    )
    assert eligibility.preview_reference == stored_preview.reference
    assert eligibility.currentness.state == "current"
    assert (
        eligibility.currentness.current_derivation_reference
        == eligibility.derivation_reference
    )


def test_resolve_requires_an_explicitly_selected_review(tmp_path: Path) -> None:
    root, stored_preview = _seed(tmp_path)

    with pytest.raises(GroupingSignalExportBlockedError) as raised:
        resolve_grouping_signal_export_eligibility(
            root,
            CLASS_ID,
            stored_preview.snapshot.derivation_reference.derivation_id,
        )

    assert raised.value.code == "no_selected_review"
    assert raised.value.reason_codes == ()


def test_resolve_rejects_selected_rejection(tmp_path: Path) -> None:
    root, stored_preview = _seed(tmp_path)
    recorded = record_grouping_signal_review(
        root,
        stored_preview.reference,
        review_revision=1,
        supersedes_revision=None,
        decision="rejected",
        acknowledged_warning_ids=(),
        actor_id="teacher_local",
        reviewed_at=NOW,
    )
    derivation_id = recorded.stored.review.derivation_reference.derivation_id
    select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        derivation_id,
        1,
        expected_current_review_revision=None,
    )

    with pytest.raises(GroupingSignalExportBlockedError) as raised:
        resolve_grouping_signal_export_eligibility(
            root,
            CLASS_ID,
            derivation_id,
        )

    assert raised.value.code == "review_not_accepted"


def test_resolve_distinguishes_stale_review_from_blocked_derivation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, stored_review = _seed_selected_accepted_review(tmp_path)
    derivation_reference = stored_review.review.derivation_reference

    stale_candidate = GroupingSignalDerivationReference(
        class_id=CLASS_ID,
        derivation_id="gsd_" + ("f" * 64),
        derivation_sha256="e" * 64,
    )
    monkeypatch.setattr(
        export_eligibility,
        "assess_grouping_signal_derivation_currentness",
        lambda *args, **kwargs: GroupingSignalPreviewCurrentness(
            "stale",
            ("roster_membership_changed",),
            stale_candidate,
        ),
    )
    with pytest.raises(GroupingSignalExportBlockedError) as stale:
        resolve_grouping_signal_export_eligibility(
            root,
            CLASS_ID,
            derivation_reference.derivation_id,
        )
    assert stale.value.code == "review_stale"
    assert stale.value.reason_codes == ("roster_membership_changed",)

    monkeypatch.setattr(
        export_eligibility,
        "assess_grouping_signal_derivation_currentness",
        lambda *args, **kwargs: GroupingSignalPreviewCurrentness(
            "blocked",
            ("current_basis_unavailable",),
            None,
        ),
    )
    with pytest.raises(GroupingSignalExportBlockedError) as blocked:
        resolve_grouping_signal_export_eligibility(
            root,
            CLASS_ID,
            derivation_reference.derivation_id,
        )
    assert blocked.value.code == "derivation_not_current"
    assert blocked.value.reason_codes == ("current_basis_unavailable",)


def test_final_revalidation_detects_selected_review_change(
    tmp_path: Path,
) -> None:
    root, stored_preview, stored_review = _seed_selected_accepted_review(
        tmp_path
    )
    derivation_id = stored_review.review.derivation_reference.derivation_id
    eligibility = resolve_grouping_signal_export_eligibility(
        root,
        CLASS_ID,
        derivation_id,
    )

    rejected = record_grouping_signal_review(
        root,
        stored_preview.reference,
        review_revision=2,
        supersedes_revision=1,
        decision="rejected",
        acknowledged_warning_ids=(),
        actor_id="teacher_local",
        reviewed_at=NOW,
    )
    assert rejected.stored.review.review_revision == 2
    select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        derivation_id,
        2,
        expected_current_review_revision=1,
    )

    with pytest.raises(GroupingSignalExportBlockedError) as raised:
        revalidate_grouping_signal_export_eligibility(root, eligibility)

    assert raised.value.code == "review_selection_changed"


def test_final_revalidation_detects_live_derivation_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _, stored_review = _seed_selected_accepted_review(tmp_path)
    eligibility = resolve_grouping_signal_export_eligibility(
        root,
        CLASS_ID,
        stored_review.review.derivation_reference.derivation_id,
    )

    monkeypatch.setattr(
        export_eligibility,
        "assess_grouping_signal_derivation_currentness",
        lambda *args, **kwargs: GroupingSignalPreviewCurrentness(
            "blocked",
            ("stale_result",),
            None,
        ),
    )

    with pytest.raises(GroupingSignalExportBlockedError) as raised:
        revalidate_grouping_signal_export_eligibility(root, eligibility)

    assert raised.value.code == "derivation_not_current"
    assert raised.value.reason_codes == ("stale_result",)


def test_eligibility_resolution_and_revalidation_are_read_only(
    tmp_path: Path,
) -> None:
    root, _, stored_review = _seed_selected_accepted_review(tmp_path)

    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }

    eligibility = resolve_grouping_signal_export_eligibility(
        root,
        CLASS_ID,
        stored_review.review.derivation_reference.derivation_id,
    )
    revalidated = revalidate_grouping_signal_export_eligibility(
        root,
        eligibility,
    )

    after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert revalidated == eligibility
    assert after == before
