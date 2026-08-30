from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian import grouping_signal_policy_storage as storage
from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyTarget,
    academic_period_proficiency_aggregation_policy_reference,
)
from meridian.grouping_signal_policy import (
    GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
    GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
    GroupingSignalAcademicBasis,
    GroupingSignalBandDefinition,
    GroupingSignalDerivationPolicy,
    GroupingSignalPolicyActor,
)
from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.standards_proficiency import StandardProficiencyActor

CLASS_ID = "synthetic_class_2026"
STANDARD_ID = "njsls-ela:RL.CR.9-10.1"
NOW = datetime(2026, 8, 30, 20, tzinfo=UTC)


def scale() -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="teacher_scale",
        scale_revision=1,
        supersedes_revision=None,
        title="Teacher proficiency scale",
        description="Criterion-referenced scale.",
        levels=(
            ProficiencyLevel("level_1", 1, "Beginning", "Beginning evidence."),
            ProficiencyLevel("level_2", 2, "Developing", "Developing evidence."),
            ProficiencyLevel("level_3", 3, "Proficient", "Proficient evidence."),
            ProficiencyLevel("level_4", 4, "Extending", "Extending evidence."),
        ),
        proficiency_threshold_level_id="level_3",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def source_policy() -> AcademicPeriodProficiencyAggregationPolicy:
    exact_scale = scale()
    return AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id="period_proficiency_policy",
        policy_revision=1,
        supersedes_revision=None,
        title="Academic Period proficiency",
        target_scale=proficiency_scale_reference(exact_scale),
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def policy(
    *,
    revision: int = 1,
    policy_id: str = "reading_planning_signal",
) -> GroupingSignalDerivationPolicy:
    exact_scale = scale()
    exact_source = source_policy()
    return GroupingSignalDerivationPolicy(
        schema_version=GROUPING_SIGNAL_DERIVATION_POLICY_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_DERIVATION_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=policy_id,
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Reading planning signal",
        academic_basis=GroupingSignalAcademicBasis(
            basis_kind="academic_period_proficiency",
            target_period=AcademicPeriodProficiencyTarget(
                AcademicPeriodRef("2026-2027", "mp1"),
                2,
            ),
            standard_id=STANDARD_ID,
            source_policy=(
                academic_period_proficiency_aggregation_policy_reference(
                    exact_source
                )
            ),
            target_scale=proficiency_scale_reference(exact_scale),
        ),
        dimension_id="reading_planning",
        band_count=3,
        band_definitions=(
            GroupingSignalBandDefinition(1, 1, 1),
            GroupingSignalBandDefinition(2, 2, 3),
            GroupingSignalBandDefinition(3, 4, 4),
        ),
        tie_handling="same_level_same_band",
        missing_result_handling="noncontributing",
        insufficient_result_handling="blocking",
        actor=GroupingSignalPolicyActor("teacher", "teacher_local"),
        rationale="Temporary contextual planning support.",
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def allow_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        storage,
        "validate_grouping_signal_policy_dependencies",
        lambda *args, **kwargs: object(),
    )


def test_canonical_policy_path_is_meridian_owned_and_class_local(
    tmp_path: Path,
) -> None:
    assert storage.grouping_signal_policy_revision_relative_path(
        CLASS_ID,
        "reading_planning_signal",
        1,
    ) == (
        "classes/synthetic_class_2026/modules/meridian/"
        "grouping_signal_policies/reading_planning_signal/revisions/1.json"
    )
    path = storage.grouping_signal_policy_revision_path(
        tmp_path,
        CLASS_ID,
        "reading_planning_signal",
        1,
    )
    assert "grouping_signals" not in path.parts
    assert "grouping_signal_policies" in path.parts


def test_write_is_immutable_digest_bound_and_does_not_auto_select(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    value = policy()
    created = storage.write_grouping_signal_policy_revision(tmp_path, value)
    assert created.disposition == "created"
    assert created.stored.policy == value
    assert created.stored.path.with_suffix(".json.sha256").is_file()
    assert created.stored.reference.policy_sha256 == created.stored.policy_sha256
    assert (
        storage.get_current_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            value.policy_id,
        )
        is None
    )
    replay = storage.write_grouping_signal_policy_revision(tmp_path, value)
    assert replay.disposition == "existing"
    assert replay.stored.content == created.stored.content


def test_same_revision_different_content_conflicts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    value = policy()
    storage.write_grouping_signal_policy_revision(tmp_path, value)
    with pytest.raises(storage.GroupingSignalPolicyStorageConflictError):
        storage.write_grouping_signal_policy_revision(
            tmp_path,
            replace(value, rationale="Different immutable bytes."),
        )


def test_history_is_contiguous_and_transition_validated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    first = policy()
    second = policy(revision=2)
    storage.write_grouping_signal_policy_revision(tmp_path, first)
    storage.write_grouping_signal_policy_revision(tmp_path, second)
    assert storage.list_grouping_signal_policy_revisions(
        tmp_path,
        CLASS_ID,
        first.policy_id,
    ) == (1, 2)
    with pytest.raises(
        storage.GroupingSignalPolicyStorageConflictError,
        match="contiguous",
    ):
        storage.write_grouping_signal_policy_revision(
            tmp_path,
            policy(revision=4),
        )


def test_newer_revision_does_not_change_explicit_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    first = policy()
    storage.write_grouping_signal_policy_revision(tmp_path, first)
    storage.select_grouping_signal_policy_revision(
        tmp_path,
        CLASS_ID,
        first.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    storage.write_grouping_signal_policy_revision(tmp_path, policy(revision=2))
    assert storage.get_current_grouping_signal_policy_revision(
        tmp_path,
        CLASS_ID,
        first.policy_id,
    ) == 1


def test_explicit_selection_is_cas_protected_and_historical(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    first = policy()
    second = policy(revision=2)
    for value in (first, second):
        storage.write_grouping_signal_policy_revision(tmp_path, value)

    created = storage.select_grouping_signal_policy_revision(
        tmp_path,
        CLASS_ID,
        first.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    assert created.disposition == "created"

    with pytest.raises(
        storage.GroupingSignalPolicyStorageConflictError,
        match="Expected current",
    ):
        storage.select_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            first.policy_id,
            2,
            expected_current_policy_revision=None,
        )

    updated = storage.select_grouping_signal_policy_revision(
        tmp_path,
        CLASS_ID,
        first.policy_id,
        2,
        expected_current_policy_revision=1,
    )
    assert updated.disposition == "updated"
    historical = storage.select_grouping_signal_policy_revision(
        tmp_path,
        CLASS_ID,
        first.policy_id,
        1,
        expected_current_policy_revision=2,
    )
    assert historical.disposition == "updated"
    assert historical.stored.policy.policy_revision == 1

    existing = storage.select_grouping_signal_policy_revision(
        tmp_path,
        CLASS_ID,
        first.policy_id,
        1,
        expected_current_policy_revision=1,
    )
    assert existing.disposition == "existing"


def test_selection_revalidates_exact_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    value = policy()
    storage.write_grouping_signal_policy_revision(tmp_path, value)

    def reject(*args: object, **kwargs: object) -> object:
        raise storage.GroupingSignalPolicyDependencyError("dependency changed")

    monkeypatch.setattr(
        storage,
        "validate_grouping_signal_policy_dependencies",
        reject,
    )
    with pytest.raises(
        storage.GroupingSignalPolicyDependencyError,
        match="dependency changed",
    ):
        storage.select_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            value.policy_id,
            1,
            expected_current_policy_revision=None,
        )


def test_current_pointer_is_minimal_and_sha_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    value = policy()
    stored = storage.write_grouping_signal_policy_revision(
        tmp_path,
        value,
    ).stored
    storage.select_grouping_signal_policy_revision(
        tmp_path,
        CLASS_ID,
        value.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    pointer = storage.grouping_signal_policy_current_path(
        tmp_path,
        CLASS_ID,
        value.policy_id,
    )
    data = json.loads(pointer.read_text(encoding="utf-8"))
    assert set(data) == {
        "schema_version",
        "record_type",
        "class_id",
        "policy_id",
        "policy_revision",
        "policy_sha256",
    }
    assert data["policy_sha256"] == stored.policy_sha256
    current = storage.load_current_grouping_signal_policy(
        tmp_path,
        CLASS_ID,
        value.policy_id,
    )
    assert current is not None
    assert current.reference == stored.reference


def test_pointer_digest_tamper_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    value = policy()
    storage.write_grouping_signal_policy_revision(tmp_path, value)
    storage.select_grouping_signal_policy_revision(
        tmp_path,
        CLASS_ID,
        value.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    pointer = storage.grouping_signal_policy_current_path(
        tmp_path,
        CLASS_ID,
        value.policy_id,
    )
    data = json.loads(pointer.read_text(encoding="utf-8"))
    data["policy_sha256"] = "0" * 64
    pointer.write_text(
        json.dumps(data, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(
        storage.GroupingSignalPolicyStorageIntegrityError,
        match="digest",
    ):
        storage.load_current_grouping_signal_policy(
            tmp_path,
            CLASS_ID,
            value.policy_id,
        )


def test_revision_digest_tamper_and_bounded_read_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    stored = storage.write_grouping_signal_policy_revision(
        tmp_path,
        policy(),
    ).stored
    with pytest.raises(storage.GroupingSignalPolicyStorageTooLargeError):
        storage.load_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            stored.policy.policy_id,
            1,
            maximum_revision_bytes=8,
        )

    stored.path.write_bytes(stored.content + b" ")
    with pytest.raises(
        storage.GroupingSignalPolicyStorageIntegrityError,
        match="digest",
    ):
        storage.load_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            stored.policy.policy_id,
            1,
        )


def test_policy_ids_are_deterministic_and_do_not_imply_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    storage.write_grouping_signal_policy_revision(
        tmp_path,
        policy(policy_id="z_policy"),
    )
    storage.write_grouping_signal_policy_revision(
        tmp_path,
        policy(policy_id="a_policy"),
    )
    assert storage.list_grouping_signal_policy_ids(
        tmp_path,
        CLASS_ID,
    ) == ("a_policy", "z_policy")
    assert storage.get_current_grouping_signal_policy_revision(
        tmp_path,
        CLASS_ID,
        "a_policy",
    ) is None


def test_unexpected_visible_policy_entry_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    stored = storage.write_grouping_signal_policy_revision(
        tmp_path,
        policy(),
    ).stored
    (stored.path.parent.parent / "latest.json").write_text(
        "{}",
        encoding="utf-8",
    )
    with pytest.raises(
        storage.GroupingSignalPolicyStorageIntegrityError,
        match="unexpected",
    ):
        storage.load_grouping_signal_policy_revision(
            tmp_path,
            CLASS_ID,
            stored.policy.policy_id,
            1,
        )


def test_existing_write_lock_fails_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    allow_dependencies(monkeypatch)
    value = policy()
    revisions = storage.grouping_signal_policy_revisions_directory(
        tmp_path,
        CLASS_ID,
        value.policy_id,
    )
    revisions.mkdir(parents=True)
    lock = revisions.parent / ".write.lock"
    lock.write_text("held\n", encoding="ascii")
    with pytest.raises(storage.GroupingSignalPolicyStorageLockError):
        storage.write_grouping_signal_policy_revision(tmp_path, value)
    assert not storage.grouping_signal_policy_revision_path(
        tmp_path,
        CLASS_ID,
        value.policy_id,
        1,
    ).exists()


def test_dependency_validation_binds_exact_academic_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    value = policy()
    exact_scale = scale()
    exact_source = source_policy()
    basis = value.academic_basis

    monkeypatch.setattr(
        storage,
        "load_class_metadata",
        lambda *args: SimpleNamespace(
            class_id=CLASS_ID,
            school_year="2026-2027",
        ),
    )
    monkeypatch.setattr(
        storage,
        "load_academic_period_calendar_revision",
        lambda *args: object(),
    )
    monkeypatch.setattr(
        storage,
        "get_academic_period",
        lambda *args: SimpleNamespace(period_id="mp1"),
    )
    monkeypatch.setattr(
        storage,
        "load_workspace_standards_library",
        lambda *args: object(),
    )
    monkeypatch.setattr(
        storage,
        "find_standard_definition",
        lambda *args: SimpleNamespace(standard_id=STANDARD_ID),
    )
    monkeypatch.setattr(
        storage,
        "load_academic_period_proficiency_policy_revision",
        lambda *args: SimpleNamespace(
            policy=exact_source,
            policy_sha256=basis.source_policy.policy_sha256,
        ),
    )
    monkeypatch.setattr(
        storage,
        "load_proficiency_scale_revision",
        lambda *args: SimpleNamespace(
            scale=exact_scale,
            scale_sha256=basis.target_scale.scale_sha256,
        ),
    )

    dependencies = storage.validate_grouping_signal_policy_dependencies(
        tmp_path,
        value,
    )
    assert dependencies.class_metadata.class_id == CLASS_ID
    assert dependencies.target_period.period_id == "mp1"
    assert dependencies.standard.standard_id == STANDARD_ID
    assert dependencies.source_policy.policy == exact_source
    assert dependencies.target_scale.scale == exact_scale
