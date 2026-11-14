"""#125-H3C3A: explicit target-scope execution without skipping canonical checks.

The target-only view is not the teacher's complete 406-row inventory. The
selected source and membership are re-resolved; full preview remains available.
Installed native qualification is opt-in and uses synthetic ScoreForm fixtures.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_issue124_slicee2g3k_composite_canonical import CLASS
from test_issue125_h3b2_native_write_isolation import _eligible_rows
from test_issue125_sliceg2a_canonical_batch_acceptance import _build_plan, _ready_native

from meridian.assessment_eligibility_progress import execute_batch_with_sealed_progress
from meridian.guided_eligibility import load_guided_eligibility_context
from meridian.new_evidence_workflow import (
    NewEvidenceWorkflowScopeError,
    project_new_evidence_review,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("PDS_ISSUE125_H3C3A_NATIVE_TEST") != "1",
    reason="Requires the explicit installed native candidate matrix",
)


def test_target_scope_requires_exact_authorized_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, grade_id, prepared, review, deps, grade_item, _, _ = _ready_native(
        tmp_path, monkeypatch, "scoreform"
    )
    selected = _eligible_rows(review, "scoreform")
    assert len(selected) == 174
    item_id = selected[0].source.item_id
    complete = project_new_evidence_review(root, CLASS, grade_id, prepared.authorized)
    narrowed = project_new_evidence_review(
        root, CLASS, grade_id, prepared.authorized, target_item_id=item_id
    )
    assert len(complete.rows) == 406
    assert len(narrowed.rows) == 1
    assert narrowed.rows[0] == next(
        row for row in complete.rows if row.source.item_id == item_id
    )
    complete_context = load_guided_eligibility_context(
        root, prepared, grade_item, item_id=item_id, dependencies=deps
    )
    narrow_context = load_guided_eligibility_context(
        root,
        prepared,
        grade_item,
        item_id=item_id,
        dependencies=deps,
        exact_item_only=True,
    )
    assert len(complete_context.review.rows) == 406
    assert narrow_context.review.rows == narrowed.rows
    with pytest.raises(NewEvidenceWorkflowScopeError):
        project_new_evidence_review(
            root,
            CLASS,
            grade_id,
            prepared.authorized,
            target_item_id="nonexistent-native-evidence-id",
        )


def test_nine_canonical_actions_do_not_reproject_unrelated_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import meridian.new_evidence_workflow as workflow

    root, _, prepared, review, deps, grade_item, _, actor = _ready_native(
        tmp_path, monkeypatch, "scoreform"
    )
    selected = tuple(
        row.source.item_id for row in _eligible_rows(review, "scoreform")[:9]
    )
    plan = _build_plan(root, prepared, review, deps, actor, selected)
    assert plan.action_count == 9
    projected_rows = 0
    original = workflow._project_row

    def counted(*args: object, **kwargs: object) -> object:
        nonlocal projected_rows
        projected_rows += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow, "_project_row", counted)
    result = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert not result.stopped, (result.stop_reason, result.counts)
    assert result.verified_current_count == 9
    assert result.counts == (("applied", 9),)
    # One mandatory complete preflight + up to three exact refreshes per action.
    assert projected_rows <= 406 + (9 * 3), projected_rows
