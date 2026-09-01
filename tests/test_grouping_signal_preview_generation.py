from __future__ import annotations

from pathlib import Path

from pds_core.grouping_signal_storage import list_grouping_signal_ids

from meridian.grouping_signal_derivation_storage import (
    list_grouping_signal_derivation_ids,
)
from meridian.grouping_signal_generation import generate_grouping_signal_derivation
from meridian.grouping_signal_preview_generation import (
    generate_grouping_signal_preview,
)
from meridian.grouping_signal_preview_storage import (
    list_grouping_signal_preview_ids,
)
from tests.test_grouping_signal_generation_integration import (
    CLASS_ID,
    _seed_current_grade_item_result,
    _seed_period_result_and_grouping_policy,
    _seed_workspace,
)


def test_workspace_preview_generation_persists_only_preview(
    tmp_path: Path,
) -> None:
    workspace, scale = _seed_workspace(tmp_path)
    grade_item_basis, membership, membership_sha256 = (
        _seed_current_grade_item_result(workspace, scale)
    )
    policy_id = _seed_period_result_and_grouping_policy(
        workspace,
        scale,
        grade_item_basis,
        membership,
        membership_sha256,
    )
    generated = generate_grouping_signal_derivation(
        workspace,
        CLASS_ID,
        policy_id,
    )
    assert generated.status == "generated"
    assert generated.stored is not None
    derivation_reference = generated.stored.reference

    derivations_before = list_grouping_signal_derivation_ids(
        workspace,
        CLASS_ID,
    )
    core_signals_before = list_grouping_signal_ids(workspace, CLASS_ID)

    preview_result = generate_grouping_signal_preview(
        workspace,
        derivation_reference,
    )

    derivations_after = list_grouping_signal_derivation_ids(
        workspace,
        CLASS_ID,
    )
    core_signals_after = list_grouping_signal_ids(workspace, CLASS_ID)

    assert preview_result.write_disposition == "created"
    preview = preview_result.stored.snapshot
    assert preview.derivation_reference == derivation_reference
    assert preview.currentness.state == "current"
    assert preview.currentness.current_derivation_reference == derivation_reference
    assert preview.policy_reference == generated.stored.snapshot.policy_reference
    assert preview.coverage.roster_student_count == 1
    assert preview.coverage.contributing_student_count == 1
    assert preview.student_rows[0].student_id == (
        generated.stored.snapshot.student_derivations[0].student_id
    )
    assert preview.student_rows[0].band == 2
    assert derivations_after == derivations_before
    assert core_signals_after == core_signals_before == ()
    assert list_grouping_signal_preview_ids(workspace, CLASS_ID) == (
        preview.preview_id,
    )

    replay = generate_grouping_signal_preview(
        workspace,
        derivation_reference,
    )
    assert replay.write_disposition == "existing"
    assert replay.stored.reference == preview_result.stored.reference
    assert replay.stored.content == preview_result.stored.content
