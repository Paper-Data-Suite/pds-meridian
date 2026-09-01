from __future__ import annotations

from types import SimpleNamespace

import pytest

import meridian.grouping_signal_currentness as currentness
from meridian.grouping_signal_derivation import (
    GroupingSignalResolvedStudentResult,
    derive_grouping_signal_snapshot,
    grouping_signal_derivation_reference,
    grouping_signal_roster_basis,
)
from meridian.grouping_signal_derivation_storage import (
    list_grouping_signal_derivation_ids,
)
from meridian.grouping_signal_generation import (
    GroupingSignalGenerationBlocker,
    GroupingSignalGenerationCandidate,
    generate_grouping_signal_derivation,
)
from meridian.grouping_signal_policy import (
    grouping_signal_derivation_policy_reference,
)
from tests.test_grouping_signal_derivation import (
    CLASS_ID,
    derived_snapshot,
    grouping_policy,
    period_result,
    scale,
    source_policy,
)
from tests.test_grouping_signal_generation_integration import (
    _seed_current_grade_item_result,
    _seed_period_result_and_grouping_policy,
    _seed_workspace,
)


def _stored(snapshot: object) -> object:
    return SimpleNamespace(snapshot=snapshot)


def test_exact_unchanged_workspace_is_current_and_writes_nothing(
    tmp_path,
) -> None:
    workspace, exact_scale = _seed_workspace(tmp_path)
    grade_item_basis, membership, membership_sha256 = (
        _seed_current_grade_item_result(workspace, exact_scale)
    )
    policy_id = _seed_period_result_and_grouping_policy(
        workspace,
        exact_scale,
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
    reference = generated.stored.reference
    before = list_grouping_signal_derivation_ids(workspace, CLASS_ID)

    assessment = currentness.assess_grouping_signal_derivation_currentness(
        workspace,
        reference,
    )

    after = list_grouping_signal_derivation_ids(workspace, CLASS_ID)
    assert assessment.state == "current"
    assert assessment.reason_codes == ()
    assert assessment.current_derivation_reference == reference
    assert after == before


def test_changed_source_result_and_proficiency_are_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source = derived_snapshot()
    changed = derived_snapshot(
        levels={
            "student_1": "level_2",
            "student_2": "level_3",
            "student_3": "level_4",
        }
    )
    reference = grouping_signal_derivation_reference(source)
    monkeypatch.setattr(
        currentness,
        "load_grouping_signal_derivation_reference",
        lambda *args, **kwargs: _stored(source),
    )
    monkeypatch.setattr(
        currentness,
        "resolve_current_grouping_signal_derivation",
        lambda *args, **kwargs: GroupingSignalGenerationCandidate(
            "generated",
            (),
            changed,
        ),
    )

    assessment = currentness.assess_grouping_signal_derivation_currentness(
        tmp_path,
        reference,
    )

    assert assessment.state == "stale"
    assert "source_result_reference_changed" in assessment.reason_codes
    assert "source_proficiency_changed" in assessment.reason_codes
    assert assessment.current_derivation_reference == (
        grouping_signal_derivation_reference(changed)
    )


def test_roster_membership_change_is_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source = derived_snapshot()
    changed = derived_snapshot(
        student_order=("student_1", "student_2"),
        levels={
            "student_1": "level_1",
            "student_2": "level_3",
        },
    )
    reference = grouping_signal_derivation_reference(source)
    monkeypatch.setattr(
        currentness,
        "load_grouping_signal_derivation_reference",
        lambda *args, **kwargs: _stored(source),
    )
    monkeypatch.setattr(
        currentness,
        "resolve_current_grouping_signal_derivation",
        lambda *args, **kwargs: GroupingSignalGenerationCandidate(
            "generated",
            (),
            changed,
        ),
    )

    assessment = currentness.assess_grouping_signal_derivation_currentness(
        tmp_path,
        reference,
    )

    assert assessment.state == "stale"
    assert "roster_membership_changed" in assessment.reason_codes


def test_selected_policy_revision_change_is_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source = derived_snapshot()
    exact_scale = scale()
    exact_source_policy = source_policy(exact_scale)
    revised_policy = grouping_policy(
        exact_scale,
        exact_source_policy,
        revision=2,
    )
    roster = grouping_signal_roster_basis(
        CLASS_ID,
        ("student_1", "student_2", "student_3"),
    )
    resolved = tuple(
        GroupingSignalResolvedStudentResult(
            student_id,
            period_result(
                exact_scale,
                exact_source_policy,
                student_id,
                level_id,
            ),
        )
        for student_id, level_id in (
            ("student_1", "level_1"),
            ("student_2", "level_3"),
            ("student_3", "level_4"),
        )
    )
    changed = derive_grouping_signal_snapshot(
        revised_policy,
        grouping_signal_derivation_policy_reference(revised_policy),
        exact_scale,
        roster,
        resolved,
    )
    reference = grouping_signal_derivation_reference(source)
    monkeypatch.setattr(
        currentness,
        "load_grouping_signal_derivation_reference",
        lambda *args, **kwargs: _stored(source),
    )
    monkeypatch.setattr(
        currentness,
        "resolve_current_grouping_signal_derivation",
        lambda *args, **kwargs: GroupingSignalGenerationCandidate(
            "generated",
            (),
            changed,
        ),
    )

    assessment = currentness.assess_grouping_signal_derivation_currentness(
        tmp_path,
        reference,
    )

    assert assessment.state == "stale"
    assert "policy_selection_changed" in assessment.reason_codes


def test_generation_blockers_become_bounded_blocked_currentness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source = derived_snapshot()
    reference = grouping_signal_derivation_reference(source)
    monkeypatch.setattr(
        currentness,
        "load_grouping_signal_derivation_reference",
        lambda *args, **kwargs: _stored(source),
    )
    monkeypatch.setattr(
        currentness,
        "resolve_current_grouping_signal_derivation",
        lambda *args, **kwargs: GroupingSignalGenerationCandidate(
            "blocked",
            (
                GroupingSignalGenerationBlocker(
                    "no_selected_policy",
                    None,
                    None,
                ),
            ),
            None,
        ),
    )

    assessment = currentness.assess_grouping_signal_derivation_currentness(
        tmp_path,
        reference,
    )

    assert assessment.state == "blocked"
    assert assessment.reason_codes == ("no_selected_policy",)
    assert assessment.current_derivation_reference is None
