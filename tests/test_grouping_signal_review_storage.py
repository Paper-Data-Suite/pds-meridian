from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from meridian.grouping_signal_derivation_storage import (
    write_grouping_signal_derivation,
)
from meridian.grouping_signal_preview import grouping_signal_preview_reference
from meridian.grouping_signal_preview_storage import (
    write_grouping_signal_preview,
)
from meridian.grouping_signal_review import (
    create_grouping_signal_review_decision,
)
from meridian.grouping_signal_review_storage import (
    GroupingSignalReviewDependencyError,
    GroupingSignalReviewStorageConflictError,
    get_current_grouping_signal_review_revision,
    grouping_signal_review_current_path,
    grouping_signal_review_revision_path,
    list_grouping_signal_review_revisions,
    load_current_grouping_signal_review,
    load_grouping_signal_review_revision,
    select_grouping_signal_review_revision,
    write_grouping_signal_review_revision,
)
from tests.test_grouping_signal_derivation import derived_snapshot
from tests.test_grouping_signal_preview import _preview

CLASS_ID = "synthetic_class_2026"
NOW = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)


def _seed_exact_artifacts(
    tmp_path: Path,
    *,
    levels: dict[str, str | None] | None = None,
):
    root = tmp_path / "workspace"
    root.mkdir()
    derivation = derived_snapshot(levels=levels)
    preview = _preview(levels=levels)
    stored_derivation = write_grouping_signal_derivation(
        root,
        derivation,
    ).stored
    stored_preview = write_grouping_signal_preview(root, preview).stored
    assert stored_preview.snapshot.derivation_reference == (
        stored_derivation.reference
    )
    return root, stored_derivation, stored_preview


def _review(
    preview,
    revision: int,
    *,
    decision: str = "accepted_for_export",
    reviewed_at: datetime = NOW,
):
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
        reviewed_at=reviewed_at,
    )


def test_review_write_does_not_auto_select_and_uses_padded_revision_path(
    tmp_path: Path,
) -> None:
    root, _, stored_preview = _seed_exact_artifacts(tmp_path)
    review = _review(stored_preview.snapshot, 1)

    written = write_grouping_signal_review_revision(root, review)

    assert written.disposition == "created"
    assert list_grouping_signal_review_revisions(
        root,
        CLASS_ID,
        review.derivation_reference.derivation_id,
    ) == (1,)
    assert get_current_grouping_signal_review_revision(
        root,
        CLASS_ID,
        review.derivation_reference.derivation_id,
    ) is None
    assert not grouping_signal_review_current_path(
        root,
        CLASS_ID,
        review.derivation_reference.derivation_id,
    ).exists()
    assert written.stored.path == grouping_signal_review_revision_path(
        root,
        CLASS_ID,
        review.derivation_reference.derivation_id,
        1,
    )
    assert written.stored.path.name == "000001.json"


def test_review_selection_is_explicit_cas_and_new_write_does_not_supersede(
    tmp_path: Path,
) -> None:
    root, _, stored_preview = _seed_exact_artifacts(tmp_path)
    first = _review(stored_preview.snapshot, 1)
    write_grouping_signal_review_revision(root, first)

    selected_first = select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        first.derivation_reference.derivation_id,
        1,
        expected_current_review_revision=None,
    )
    assert selected_first.disposition == "created"
    current_first = load_current_grouping_signal_review(
        root,
        CLASS_ID,
        first.derivation_reference.derivation_id,
    )
    assert current_first is not None
    assert current_first.review == first

    second = _review(
        stored_preview.snapshot,
        2,
        decision="rejected",
        reviewed_at=NOW + timedelta(seconds=1),
    )
    write_grouping_signal_review_revision(root, second)

    assert get_current_grouping_signal_review_revision(
        root,
        CLASS_ID,
        first.derivation_reference.derivation_id,
    ) == 1

    with pytest.raises(GroupingSignalReviewStorageConflictError, match="Expected"):
        select_grouping_signal_review_revision(
            root,
            CLASS_ID,
            first.derivation_reference.derivation_id,
            2,
            expected_current_review_revision=None,
        )

    selected_second = select_grouping_signal_review_revision(
        root,
        CLASS_ID,
        first.derivation_reference.derivation_id,
        2,
        expected_current_review_revision=1,
    )
    assert selected_second.disposition == "updated"
    current_second = load_current_grouping_signal_review(
        root,
        CLASS_ID,
        first.derivation_reference.derivation_id,
    )
    assert current_second is not None
    assert current_second.review == second


def test_review_storage_is_idempotent_and_contiguous(
    tmp_path: Path,
) -> None:
    root, _, stored_preview = _seed_exact_artifacts(tmp_path)
    first = _review(stored_preview.snapshot, 1)
    assert write_grouping_signal_review_revision(root, first).disposition == (
        "created"
    )
    assert write_grouping_signal_review_revision(root, first).disposition == (
        "existing"
    )

    third = replace(
        first,
        review_revision=3,
        supersedes_revision=2,
        reviewed_at=NOW + timedelta(seconds=2),
    )
    with pytest.raises(
        GroupingSignalReviewStorageConflictError,
        match="contiguous",
    ):
        write_grouping_signal_review_revision(root, third)


def test_review_storage_revalidates_exact_preview_dependency(
    tmp_path: Path,
) -> None:
    root, _, stored_preview = _seed_exact_artifacts(tmp_path)
    review = _review(stored_preview.snapshot, 1)
    forged = replace(
        review,
        preview_reference=replace(
            review.preview_reference,
            preview_sha256="0" * 64,
        ),
    )

    with pytest.raises(GroupingSignalReviewDependencyError):
        write_grouping_signal_review_revision(root, forged)


def test_review_revision_round_trip_preserves_exact_bytes(
    tmp_path: Path,
) -> None:
    root, _, stored_preview = _seed_exact_artifacts(tmp_path)
    review = _review(stored_preview.snapshot, 1)
    written = write_grouping_signal_review_revision(root, review).stored

    loaded = load_grouping_signal_review_revision(
        root,
        CLASS_ID,
        review.derivation_reference.derivation_id,
        1,
    )
    assert loaded.review == review
    assert loaded.reference == written.reference
    assert loaded.content == written.content
