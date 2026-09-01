from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from meridian.grouping_signal_derivation import grouping_signal_derivation_reference
from meridian.grouping_signal_preview import (
    GROUPING_SIGNAL_PREVIEW_ALGORITHM_VERSION,
    GROUPING_SIGNAL_PREVIEW_ID_PREFIX,
    GROUPING_SIGNAL_PREVIEW_RECORD_TYPE,
    GROUPING_SIGNAL_PREVIEW_SCHEMA_VERSION,
    GroupingSignalPreviewCurrentness,
    GroupingSignalPreviewSerializationError,
    GroupingSignalPreviewValidationError,
    build_grouping_signal_preview_snapshot,
    grouping_signal_preview_diagnostic_id,
    grouping_signal_preview_reference,
    grouping_signal_preview_reference_from_dict,
    grouping_signal_preview_reference_to_dict,
    grouping_signal_preview_snapshot_from_json_bytes,
    grouping_signal_preview_snapshot_to_dict,
    grouping_signal_preview_snapshot_to_json_bytes,
)
from tests.test_grouping_signal_derivation import (
    derived_snapshot,
    grouping_policy,
    scale,
    source_policy,
)


def _preview(levels: dict[str, str | None] | None = None):
    exact_scale = scale()
    source = source_policy(exact_scale)
    policy = grouping_policy(exact_scale, source)
    derivation = derived_snapshot(levels=levels)
    reference = grouping_signal_derivation_reference(derivation)
    return build_grouping_signal_preview_snapshot(
        derivation,
        policy,
        exact_scale,
        GroupingSignalPreviewCurrentness("current", (), reference),
    )


def test_preview_is_frozen_content_addressed_and_bound_to_derivation() -> None:
    preview = _preview()
    assert preview.schema_version == GROUPING_SIGNAL_PREVIEW_SCHEMA_VERSION
    assert preview.record_type == GROUPING_SIGNAL_PREVIEW_RECORD_TYPE
    assert preview.preview_algorithm_version == (
        GROUPING_SIGNAL_PREVIEW_ALGORITHM_VERSION
    )
    assert preview.preview_id == GROUPING_SIGNAL_PREVIEW_ID_PREFIX + (
        preview.preview_fingerprint
    )
    assert preview.derivation_reference == grouping_signal_derivation_reference(
        derived_snapshot()
    )
    assert not hasattr(preview, "__dict__")
    with pytest.raises(FrozenInstanceError):
        preview.dimension_id = "changed"  # type: ignore[misc]


def test_preview_exposes_exact_policy_basis_and_band_definitions() -> None:
    preview = _preview()
    assert preview.academic_basis.basis_kind == "academic_period_proficiency"
    assert preview.academic_basis.standard_id == "njsls-ela:RL.CR.9-10.1"
    assert preview.dimension_id == "reading_planning"
    assert preview.band_count == 3
    assert [
        (item.band, item.minimum_scale_position, item.maximum_scale_position)
        for item in preview.band_definitions
    ] == [(1, 1, 1), (2, 2, 3), (3, 4, 4)]
    assert preview.tie_handling == "same_level_same_band"
    assert preview.roster_basis.student_ids == (
        "student_1",
        "student_2",
        "student_3",
    )


def test_student_rows_and_distribution_are_deterministic() -> None:
    preview = _preview()
    assert [row.student_id for row in preview.student_rows] == [
        "student_1",
        "student_2",
        "student_3",
    ]
    assert [row.band for row in preview.student_rows] == [1, 2, 3]
    assert preview.coverage.roster_student_count == 3
    assert preview.coverage.contributing_student_count == 3
    assert preview.coverage.noncontributing_student_count == 0
    assert preview.coverage.occupied_band_count == 3
    assert preview.coverage.empty_band_count == 0
    assert [item.student_count for item in preview.band_summaries] == [1, 1, 1]
    assert preview.band_summaries[1].proficiency_level_ids == (
        "level_2",
        "level_3",
    )
    assert preview.diagnostics == ()


def test_same_level_ties_are_visible_and_never_split() -> None:
    preview = _preview(
        {
            "student_1": "level_3",
            "student_2": "level_3",
            "student_3": "level_4",
        }
    )
    assert len(preview.tie_groups) == 1
    tie = preview.tie_groups[0]
    assert (tie.proficiency_level_id, tie.scale_position, tie.band) == (
        "level_3",
        3,
        2,
    )
    assert tie.student_ids == ("student_1", "student_2")
    assert {
        row.band
        for row in preview.student_rows
        if row.student_id in tie.student_ids
    } == {2}


def test_missing_and_insufficient_stay_noncontributing_without_band() -> None:
    preview = _preview({"student_2": None, "student_3": "level_4"})
    rows = {row.student_id: row for row in preview.student_rows}
    assert (rows["student_1"].source_state, rows["student_1"].band) == (
        "missing",
        None,
    )
    assert (rows["student_2"].source_state, rows["student_2"].band) == (
        "insufficient_evidence",
        None,
    )
    assert rows["student_3"].band == 3
    assert preview.coverage.contributing_student_count == 1
    assert preview.coverage.missing_noncontributor_count == 1
    assert preview.coverage.insufficient_noncontributor_count == 1
    assert preview.coverage.empty_band_count == 2
    assert {item.code for item in preview.diagnostics} == {
        "missing_noncontributors",
        "insufficient_noncontributors",
        "partial_coverage",
        "empty_bands",
        "single_occupied_band",
    }
    assert all(item.severity == "warning" for item in preview.diagnostics)


def test_zero_contributors_is_blocking_without_fabricated_band() -> None:
    preview = _preview({"student_1": None, "student_2": None})
    assert preview.coverage.contributing_student_count == 0
    assert all(row.band is None for row in preview.student_rows)
    diagnostics = {item.code: item for item in preview.diagnostics}
    assert diagnostics["zero_contributors"].severity == "blocking"
    assert diagnostics["zero_contributors"].student_ids == (
        "student_1",
        "student_2",
        "student_3",
    )
    assert diagnostics["empty_bands"].bands == (1, 2, 3)


def test_stale_currentness_adds_blocking_diagnostic() -> None:
    exact_scale = scale()
    source = source_policy(exact_scale)
    policy = grouping_policy(exact_scale, source)
    old = derived_snapshot()
    current = derived_snapshot(
        levels={
            "student_1": "level_2",
            "student_2": "level_3",
            "student_3": "level_4",
        }
    )
    preview = build_grouping_signal_preview_snapshot(
        old,
        policy,
        exact_scale,
        GroupingSignalPreviewCurrentness(
            "stale",
            ("source_proficiency_changed",),
            grouping_signal_derivation_reference(current),
        ),
    )
    diagnostic = next(
        item for item in preview.diagnostics if item.code == "derivation_not_current"
    )
    assert diagnostic.severity == "blocking"
    assert diagnostic.details == ("source_proficiency_changed",)


def test_blocked_currentness_preserves_source_blocker() -> None:
    exact_scale = scale()
    source = source_policy(exact_scale)
    policy = grouping_policy(exact_scale, source)
    derivation = derived_snapshot()
    preview = build_grouping_signal_preview_snapshot(
        derivation,
        policy,
        exact_scale,
        GroupingSignalPreviewCurrentness(
            "blocked", ("current_basis_unavailable",), None
        ),
    )
    diagnostic = next(
        item
        for item in preview.diagnostics
        if item.code == "current_generation_blocked"
    )
    assert diagnostic.severity == "blocking"
    assert diagnostic.details == ("current_basis_unavailable",)


def test_diagnostic_identity_binds_structured_subject() -> None:
    first = grouping_signal_preview_diagnostic_id(
        "missing_noncontributors", "warning", ("student_1",)
    )
    replay = grouping_signal_preview_diagnostic_id(
        "missing_noncontributors", "warning", ("student_1",)
    )
    changed = grouping_signal_preview_diagnostic_id(
        "missing_noncontributors", "warning", ("student_2",)
    )
    assert first == replay
    assert first != changed


def test_preview_replay_is_byte_identical_and_reference_exact() -> None:
    first = _preview()
    second = _preview()
    first_bytes = grouping_signal_preview_snapshot_to_json_bytes(first)
    assert first == second
    assert first_bytes == grouping_signal_preview_snapshot_to_json_bytes(second)
    assert grouping_signal_preview_snapshot_from_json_bytes(first_bytes) == first
    reference = grouping_signal_preview_reference(first)
    assert reference.preview_id == first.preview_id
    assert len(reference.preview_sha256) == 64
    assert grouping_signal_preview_reference_from_dict(
        grouping_signal_preview_reference_to_dict(reference)
    ) == reference


def test_material_currentness_change_changes_preview_identity() -> None:
    exact_scale = scale()
    source = source_policy(exact_scale)
    policy = grouping_policy(exact_scale, source)
    derivation = derived_snapshot()
    reference = grouping_signal_derivation_reference(derivation)
    current = build_grouping_signal_preview_snapshot(
        derivation,
        policy,
        exact_scale,
        GroupingSignalPreviewCurrentness("current", (), reference),
    )
    blocked = build_grouping_signal_preview_snapshot(
        derivation,
        policy,
        exact_scale,
        GroupingSignalPreviewCurrentness(
            "blocked", ("current_basis_unavailable",), None
        ),
    )
    assert current.preview_id != blocked.preview_id
    assert current.preview_fingerprint != blocked.preview_fingerprint


def test_current_state_requires_exact_previewed_derivation() -> None:
    exact_scale = scale()
    source = source_policy(exact_scale)
    policy = grouping_policy(exact_scale, source)
    old = derived_snapshot()
    changed = derived_snapshot(
        levels={
            "student_1": "level_2",
            "student_2": "level_3",
            "student_3": "level_4",
        }
    )
    with pytest.raises(GroupingSignalPreviewValidationError, match="exact"):
        build_grouping_signal_preview_snapshot(
            old,
            policy,
            exact_scale,
            GroupingSignalPreviewCurrentness(
                "current", (), grouping_signal_derivation_reference(changed)
            ),
        )


def test_preview_rejects_policy_not_bound_by_derivation() -> None:
    exact_scale = scale()
    source = source_policy(exact_scale)
    derivation = derived_snapshot()
    changed_policy = grouping_policy(exact_scale, source, revision=2)
    with pytest.raises(GroupingSignalPreviewValidationError, match="exact policy"):
        build_grouping_signal_preview_snapshot(
            derivation,
            changed_policy,
            exact_scale,
            GroupingSignalPreviewCurrentness(
                "current", (), grouping_signal_derivation_reference(derivation)
            ),
        )


def test_canonical_loader_rejects_duplicate_unknown_and_crlf_json() -> None:
    preview = _preview()
    canonical = grouping_signal_preview_snapshot_to_json_bytes(preview)
    duplicate = canonical.replace(
        b'{\n  "academic_basis":',
        b'{\n  "academic_basis": {},\n  "academic_basis":',
        1,
    )
    with pytest.raises(GroupingSignalPreviewSerializationError, match="duplicate"):
        grouping_signal_preview_snapshot_from_json_bytes(duplicate)

    mapping = grouping_signal_preview_snapshot_to_dict(preview)
    mapping["unexpected"] = True
    noncontract = (json.dumps(mapping, sort_keys=True, indent=2) + "\n").encode()
    with pytest.raises(GroupingSignalPreviewSerializationError, match="keys"):
        grouping_signal_preview_snapshot_from_json_bytes(noncontract)

    with pytest.raises(GroupingSignalPreviewSerializationError, match="canonical"):
        grouping_signal_preview_snapshot_from_json_bytes(
            canonical.replace(b"\n", b"\r\n")
        )


def test_preview_has_no_display_names_contacts_or_concord_planning_state() -> None:
    payload = grouping_signal_preview_snapshot_to_json_bytes(_preview()).decode()
    forbidden = (
        "first_name",
        "last_name",
        "email",
        "guardian",
        "contact",
        "generated_at",
        "created_at",
        "group_strategy",
        "group_membership",
        "target_group_size",
    )
    assert all(token not in payload for token in forbidden)
