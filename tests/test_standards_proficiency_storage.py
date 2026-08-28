from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pds_core.routes import class_dir

from meridian.proficiency_mapping import (
    PROFICIENCY_SCALE_RECORD_TYPE,
    PROFICIENCY_SCALE_SCHEMA_VERSION,
    MappingActor,
    ProficiencyLevel,
    ProficiencyScale,
    proficiency_scale_reference,
)
from meridian.proficiency_mapping_storage import (
    write_proficiency_scale_revision,
)
from meridian.standards_proficiency import (
    STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
    STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    StandardProficiencyActor,
    StandardProficiencyCalculationPolicy,
)
from meridian.standards_proficiency_storage import (
    StandardProficiencyPolicyDependencyError,
    StandardProficiencyStorageConflictError,
    StandardProficiencyStorageIntegrityError,
    get_current_standard_proficiency_policy_revision,
    list_standard_proficiency_policy_ids,
    list_standard_proficiency_policy_revisions,
    load_current_standard_proficiency_policy,
    load_standard_proficiency_policy_revision,
    select_standard_proficiency_policy_revision,
    standard_proficiency_policy_current_path,
    standard_proficiency_policy_revision_relative_path,
    write_standard_proficiency_policy_revision,
)

CLASS_ID = "synthetic_class_2026"
NOW = datetime(2026, 8, 27, 23, tzinfo=UTC)


def root(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    class_dir(workspace, CLASS_ID).mkdir(parents=True)
    return workspace


def scale(*, revision: int = 1) -> ProficiencyScale:
    return ProficiencyScale(
        schema_version=PROFICIENCY_SCALE_SCHEMA_VERSION,
        record_type=PROFICIENCY_SCALE_RECORD_TYPE,
        class_id=CLASS_ID,
        scale_id="course_proficiency",
        scale_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Course proficiency",
        description="Criterion-referenced classroom proficiency.",
        levels=(
            ProficiencyLevel(
                "beginning",
                1,
                "Beginning",
                "Initial evidence.",
            ),
            ProficiencyLevel(
                "developing",
                2,
                "Developing",
                "Partial evidence.",
            ),
            ProficiencyLevel(
                "proficient",
                3,
                "Proficient",
                "Meets criterion.",
            ),
            ProficiencyLevel(
                "advanced",
                4,
                "Advanced",
                "Extends criterion.",
            ),
        ),
        proficiency_threshold_level_id="proficient",
        actor=MappingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def policy(
    target: ProficiencyScale,
    *,
    policy_id: str = "course_policy",
    revision: int = 1,
) -> StandardProficiencyCalculationPolicy:
    return StandardProficiencyCalculationPolicy(
        schema_version=STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=policy_id,
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Course proficiency policy",
        target_scale=proficiency_scale_reference(target),
        strategy="highest",
        minimum_performance_observations=1,
        mode_tie_rule=None,
        median_even_rule=None,
        blocking_exclusion_reasons=(
            "association_unresolved",
            "mapping_not_supplied",
        ),
        native_state_handling="noncontributing",
        actor=StandardProficiencyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def persisted_scale(workspace: Path) -> ProficiencyScale:
    return write_proficiency_scale_revision(
        workspace,
        scale(),
    ).stored.scale


def test_policy_relative_path_is_class_local_and_scale_independent() -> None:
    assert standard_proficiency_policy_revision_relative_path(
        CLASS_ID,
        "course_policy",
        1,
    ) == (
        "classes/synthetic_class_2026/modules/meridian/"
        "standards_proficiency/policies/course_policy/revisions/1.json"
    )


def test_policy_requires_exact_persisted_target_scale(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    with pytest.raises(StandardProficiencyPolicyDependencyError):
        write_standard_proficiency_policy_revision(
            workspace,
            policy(scale()),
        )

    target = persisted_scale(workspace)
    wrong_digest = replace(
        policy(target),
        target_scale=replace(
            proficiency_scale_reference(target),
            scale_sha256="0" * 64,
        ),
    )
    with pytest.raises(
        StandardProficiencyPolicyDependencyError,
        match="digest",
    ):
        write_standard_proficiency_policy_revision(
            workspace,
            wrong_digest,
        )


def test_policy_write_is_immutable_and_does_not_auto_select(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)
    first = policy(target)

    written = write_standard_proficiency_policy_revision(
        workspace,
        first,
    )
    assert written.disposition == "created"
    assert (
        write_standard_proficiency_policy_revision(
            workspace,
            first,
        ).disposition
        == "existing"
    )
    assert (
        get_current_standard_proficiency_policy_revision(
            workspace,
            CLASS_ID,
            first.policy_id,
        )
        is None
    )

    with pytest.raises(StandardProficiencyStorageConflictError):
        write_standard_proficiency_policy_revision(
            workspace,
            replace(first, title="Changed in place"),
        )


def test_policy_history_is_contiguous_and_verified(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)
    first = policy(target)
    second = policy(target, revision=2)

    write_standard_proficiency_policy_revision(workspace, first)
    write_standard_proficiency_policy_revision(workspace, second)

    assert list_standard_proficiency_policy_revisions(
        workspace,
        CLASS_ID,
        first.policy_id,
    ) == (1, 2)
    assert (
        load_standard_proficiency_policy_revision(
            workspace,
            CLASS_ID,
            first.policy_id,
            1,
        ).policy
        == first
    )

    with pytest.raises(
        StandardProficiencyStorageConflictError,
        match="contiguous",
    ):
        write_standard_proficiency_policy_revision(
            workspace,
            policy(target, revision=4),
        )


def test_policy_selection_is_explicit_cas_and_historical(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)
    first = policy(target)
    second = policy(target, revision=2)
    write_standard_proficiency_policy_revision(workspace, first)
    write_standard_proficiency_policy_revision(workspace, second)

    created = select_standard_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        first.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    assert created.disposition == "created"
    current = load_current_standard_proficiency_policy(
        workspace,
        CLASS_ID,
        first.policy_id,
    )
    assert current is not None
    assert current.policy == first

    with pytest.raises(
        StandardProficiencyStorageConflictError,
        match="Expected",
    ):
        select_standard_proficiency_policy_revision(
            workspace,
            CLASS_ID,
            first.policy_id,
            2,
            expected_current_policy_revision=None,
        )

    updated = select_standard_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        first.policy_id,
        2,
        expected_current_policy_revision=1,
    )
    assert updated.disposition == "updated"

    historical = select_standard_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        first.policy_id,
        1,
        expected_current_policy_revision=2,
    )
    assert historical.disposition == "updated"
    assert (
        get_current_standard_proficiency_policy_revision(
            workspace,
            CLASS_ID,
            first.policy_id,
        )
        == 1
    )

    existing = select_standard_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        first.policy_id,
        1,
        expected_current_policy_revision=1,
    )
    assert existing.disposition == "existing"


def test_policy_ids_are_sorted_and_do_not_imply_selection(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)

    write_standard_proficiency_policy_revision(
        workspace,
        policy(target, policy_id="z_policy"),
    )
    write_standard_proficiency_policy_revision(
        workspace,
        policy(target, policy_id="a_policy"),
    )

    assert list_standard_proficiency_policy_ids(
        workspace,
        CLASS_ID,
    ) == ("a_policy", "z_policy")


def test_policy_pointer_tamper_fails_closed(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)
    value = policy(target)
    write_standard_proficiency_policy_revision(workspace, value)
    select_standard_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        value.policy_id,
        1,
        expected_current_policy_revision=None,
    )

    pointer = standard_proficiency_policy_current_path(
        workspace,
        CLASS_ID,
        value.policy_id,
    )
    data = json.loads(pointer.read_text(encoding="utf-8"))
    data["policy_sha256"] = "0" * 64
    pointer.write_bytes(
        (
            json.dumps(data, sort_keys=True, indent=2)
            + "\n"
        ).encode("utf-8")
    )

    with pytest.raises(
        StandardProficiencyStorageIntegrityError,
        match="digest",
    ):
        load_current_standard_proficiency_policy(
            workspace,
            CLASS_ID,
            value.policy_id,
        )


def test_policy_revision_digest_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)
    stored = write_standard_proficiency_policy_revision(
        workspace,
        policy(target),
    ).stored

    stored.path.write_bytes(stored.content + b" ")
    with pytest.raises(
        StandardProficiencyStorageIntegrityError,
        match="digest",
    ):
        load_standard_proficiency_policy_revision(
            workspace,
            CLASS_ID,
            stored.policy.policy_id,
            1,
        )


def test_unexpected_policy_entry_fails_closed(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)
    stored = write_standard_proficiency_policy_revision(
        workspace,
        policy(target),
    ).stored

    (stored.path.parent.parent / "latest.json").write_text(
        "{}",
        encoding="utf-8",
    )
    with pytest.raises(
        StandardProficiencyStorageIntegrityError,
        match="unexpected",
    ):
        load_standard_proficiency_policy_revision(
            workspace,
            CLASS_ID,
            stored.policy.policy_id,
            1,
        )


def test_policy_pointer_is_sha_bound_to_selected_revision(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)
    value = policy(target)
    stored = write_standard_proficiency_policy_revision(
        workspace,
        value,
    ).stored

    select_standard_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        value.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    current = load_current_standard_proficiency_policy(
        workspace,
        CLASS_ID,
        value.policy_id,
    )
    assert current is not None
    assert current.reference == stored.reference
    assert current.policy_sha256 == stored.policy_sha256
