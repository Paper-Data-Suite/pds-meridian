"""#125-H3B2: installed-wheel canonical writes and collateral-write isolation.

Synthetic classes, teacher actors and producer records only. Requires the
explicit isolated official-wheel + candidate-wheel acceptance environment.
File inventory is confined to the synthetic workspace; it does not claim to
observe unrelated host filesystem activity or a full 174-action execution.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_issue124_slicee2g3k_composite_canonical import CLASS, _all_bytes
from test_issue125_sliceg2a_canonical_batch_acceptance import (
    _build_plan,
    _ready_native,
)

from meridian.assessment_eligibility_plan import (
    BatchEligibilitySelection,
    build_batch_eligibility_plan,
    capture_batch_pointer_witnesses,
)
from meridian.assessment_eligibility_progress import (
    execute_batch_with_sealed_progress,
)
from meridian.assessment_eligibility_review import (
    project_assessment_eligibility_review,
)
from meridian.evidence_eligibility_storage import (
    load_current_evidence_eligibility_decision,
)
from meridian.teacher_action_receipts import TeacherActionReceiptStore

_NATIVE = os.environ.get("PDS_ISSUE125_H3B2_NATIVE_TEST") == "1"
pytestmark = pytest.mark.skipif(
    not _NATIVE,
    reason="Requires isolated installed official and Meridian candidate wheels",
)


def _eligible_rows(review: object, producer: str) -> tuple[object, ...]:
    rows = tuple(
        sorted(
            (
                row
                for student in review.students
                for row in student.items
                if row.candidate_for_explicit_review
            ),
            key=lambda row: row.source.item_id,
        )
    )
    if producer == "scoreform":
        rows = tuple(row for row in rows if row.result_kind == "question_correctness")
        assert len(rows) == 174
    assert rows
    return rows


def _write_inventory(before: dict[str, bytes], after: dict[str, bytes]) -> set[str]:
    """Permit only the three established Meridian-owned eligibility paths."""
    prefix = f"classes/{CLASS}/modules/meridian/"
    allowed = (
        prefix + "elig/",
        prefix + "teacher_action_receipts/",
        prefix + "assessment_eligibility_progress/",
    )
    changes = {
        key for key in before.keys() | after.keys() if before.get(key) != after.get(key)
    }
    assert changes, "Canonical action produced no observable workspace changes"
    assert not (before.keys() - after.keys()), "Pre-existing academic file was removed"
    unexpected = sorted(key for key in changes if not key.startswith(allowed))
    assert not unexpected, f"Collateral workspace changes: {unexpected[:8]}"
    assert any(key.startswith(allowed[0]) for key in changes)
    assert any(key.startswith(allowed[1]) for key in changes)
    assert any(key.startswith(allowed[2]) for key in changes)
    return changes


@pytest.mark.parametrize(
    ("producer", "limit"), (("scoreform", 2), ("quillan", 1), ("concord", 1))
)
def test_installed_canonical_writes_touch_only_eligibility_journal_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, producer: str, limit: int
) -> None:
    root, grade_id, prepared, review, deps, grade_item, _, actor = _ready_native(
        tmp_path, monkeypatch, producer
    )
    selected_rows = _eligible_rows(review, producer)[:limit]
    selected = tuple(row.source.item_id for row in selected_rows)
    plan = _build_plan(root, prepared, review, deps, actor, selected)
    assert plan.action_count == limit
    before = _all_bytes(root)
    outcome = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert not outcome.stopped, (outcome.stop_reason, outcome.counts)
    assert outcome.verified_current_count == limit
    changes = _write_inventory(before, _all_bytes(root))
    assert len({item.action_id for item in outcome.items}) == limit
    for item in plan.items:
        current = load_current_evidence_eligibility_decision(
            root, CLASS, grade_id, item.source
        )
        assert current is not None
        assert current.decision.disposition == "included"
        assert current.decision.eligibility_revision == 1
    print(
        f"H3B2_NATIVE_ISOLATION producer={producer} "
        f"actions={limit} changed_paths={len(changes)}"
    )


@pytest.mark.parametrize("disposition", ("excluded", "pending", "unsupported"))
def test_installed_noninclude_action_preserves_reason_and_other_domains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, disposition: str
) -> None:
    root, grade_id, prepared, review, deps, grade_item, _, actor = _ready_native(
        tmp_path, monkeypatch, "scoreform"
    )
    row = _eligible_rows(review, "scoreform")[0]
    selected = (row.source.item_id,)
    selection = BatchEligibilitySelection(
        selected_item_ids=selected,
        disposition=disposition,
        reason_codes=("eligibility.manual",),
        rationale="Synthetic teacher review",
    )
    plan = build_batch_eligibility_plan(
        review,
        selection,
        actor=actor,
        policy=deps.policies[0],
        witnesses=capture_batch_pointer_witnesses(
            root, review, prepared.authorized, selected
        ),
        qualified_policies=deps.policies,
    )
    assert plan.action_count == 1
    before = _all_bytes(root)
    outcome = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert not outcome.stopped, (outcome.stop_reason, outcome.counts)
    assert outcome.verified_current_count == 1
    _write_inventory(before, _all_bytes(root))
    current = load_current_evidence_eligibility_decision(
        root, CLASS, grade_id, row.source
    )
    assert current is not None
    assert current.decision.disposition == disposition
    assert current.decision.reason_codes == ("eligibility.manual",)
    assert current.decision.rationale == "Synthetic teacher review"


def test_installed_repeat_equivalent_review_is_zero_write_and_zero_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, grade_id, prepared, review, deps, grade_item, _, actor = _ready_native(
        tmp_path, monkeypatch, "scoreform"
    )
    rows = _eligible_rows(review, "scoreform")[:3]
    selected = tuple(row.source.item_id for row in rows)
    plan = _build_plan(root, prepared, review, deps, actor, selected)
    first = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert not first.stopped and first.verified_current_count == 3
    receipts = TeacherActionReceiptStore(root, CLASS)
    before_receipts = {receipt.action_id for receipt in receipts.list_receipts()}
    before = _all_bytes(root)

    # An old reviewed pointer witness is stale: repeat Apply must not write.
    stale = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert stale.stopped and stale.verified_current_count == 0
    assert _all_bytes(root) == before

    # A fresh equivalent review recognizes already-current choices as no-ops.
    updated = project_assessment_eligibility_review(
        root, grade_item_id=grade_id, prepared=prepared
    )
    refreshed = _build_plan(root, prepared, updated, deps, actor, selected)
    assert refreshed.action_count == 0
    assert all(item.status == "unchanged" for item in refreshed.items)
    no_op = execute_batch_with_sealed_progress(
        root,
        refreshed,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert not no_op.stopped, (no_op.stop_reason, no_op.counts)
    assert no_op.counts == (("unchanged", 3),)
    assert _all_bytes(root) == before
    assert {
        receipt.action_id for receipt in receipts.list_receipts()
    } == before_receipts
    for row in rows:
        current = load_current_evidence_eligibility_decision(
            root, CLASS, grade_id, row.source
        )
        assert current is not None
        assert current.decision.eligibility_revision == 1
    print("H3B2_NATIVE_REPEAT first=3 stale_replay=0 fresh_equivalent_writes=0")
