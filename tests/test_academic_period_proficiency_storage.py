from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.routes import class_dir, class_metadata_path
from pds_core.routing_models import ModuleWorkRef

from meridian.academic_period_proficiency import (
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
    ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
    AcademicPeriodProficiencyAggregationInputEntry,
    AcademicPeriodProficiencyAggregationInputs,
    AcademicPeriodProficiencyAggregationPolicy,
    AcademicPeriodProficiencyMembershipBasis,
    AcademicPeriodProficiencyResultSnapshot,
    AcademicPeriodProficiencyTarget,
    academic_period_proficiency_result_snapshot_to_json_bytes,
    calculate_academic_period_proficiency,
    create_academic_period_proficiency_result_snapshot,
)
from meridian.academic_period_proficiency_storage import (
    AcademicPeriodProficiencyPolicyDependencyError,
    AcademicPeriodProficiencyResultDependencyError,
    AcademicPeriodProficiencyStorageConflictError,
    AcademicPeriodProficiencyStorageIntegrityError,
    academic_period_proficiency_policy_current_path,
    academic_period_proficiency_policy_revision_relative_path,
    academic_period_proficiency_result_current_path,
    academic_period_proficiency_result_family_directory,
    academic_period_proficiency_result_revision_path,
    academic_period_proficiency_result_revision_relative_path,
    academic_period_proficiency_standard_key,
    get_current_academic_period_proficiency_policy_revision,
    get_current_academic_period_proficiency_result_revision,
    list_academic_period_proficiency_policy_ids,
    list_academic_period_proficiency_policy_revisions,
    list_academic_period_proficiency_result_revisions,
    load_academic_period_proficiency_policy_revision,
    load_academic_period_proficiency_result_revision,
    load_current_academic_period_proficiency_policy,
    load_current_academic_period_proficiency_result,
    select_academic_period_proficiency_policy_revision,
    select_academic_period_proficiency_result_revision,
    write_academic_period_proficiency_policy_revision,
    write_academic_period_proficiency_result_revision,
)
from meridian.grade_items import GradeItemWorkReference
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
from meridian.standards_evidence import GradeItemAggregationBasis
from meridian.standards_proficiency import StandardProficiencyActor

CLASS_ID = "synthetic_class_2026"
NOW = datetime(2026, 8, 27, 23, tzinfo=UTC)
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "mp1"
STUDENT_ID = "student_1"
STANDARD_ID = "urn:njsls:ela:RL.CR.11-12.1"


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
) -> AcademicPeriodProficiencyAggregationPolicy:
    return AcademicPeriodProficiencyAggregationPolicy(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=policy_id,
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title="Course Academic Period proficiency policy",
        target_scale=proficiency_scale_reference(target),
        strategy="highest",
        period_membership_scope="direct",
        minimum_calculated_results=1,
        mode_tie_rule=None,
        median_even_rule=None,
        missing_result_handling="noncontributing",
        insufficient_result_handling="blocking",
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
    assert academic_period_proficiency_policy_revision_relative_path(
        CLASS_ID,
        "course_policy",
        1,
    ) == (
        "classes/synthetic_class_2026/modules/meridian/"
        "academic_period_proficiency/policies/course_policy/revisions/1.json"
    )


def test_policy_requires_exact_persisted_target_scale(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    with pytest.raises(AcademicPeriodProficiencyPolicyDependencyError):
        write_academic_period_proficiency_policy_revision(
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
        AcademicPeriodProficiencyPolicyDependencyError,
        match="digest",
    ):
        write_academic_period_proficiency_policy_revision(
            workspace,
            wrong_digest,
        )


def test_policy_write_is_immutable_and_does_not_auto_select(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)
    first = policy(target)

    written = write_academic_period_proficiency_policy_revision(
        workspace,
        first,
    )
    assert written.disposition == "created"
    assert (
        write_academic_period_proficiency_policy_revision(
            workspace,
            first,
        ).disposition
        == "existing"
    )
    assert (
        get_current_academic_period_proficiency_policy_revision(
            workspace,
            CLASS_ID,
            first.policy_id,
        )
        is None
    )

    with pytest.raises(AcademicPeriodProficiencyStorageConflictError):
        write_academic_period_proficiency_policy_revision(
            workspace,
            replace(first, title="Changed in place"),
        )


def test_policy_history_is_contiguous_and_verified(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)
    first = policy(target)
    second = policy(target, revision=2)

    write_academic_period_proficiency_policy_revision(workspace, first)
    write_academic_period_proficiency_policy_revision(workspace, second)

    assert list_academic_period_proficiency_policy_revisions(
        workspace,
        CLASS_ID,
        first.policy_id,
    ) == (1, 2)
    assert (
        load_academic_period_proficiency_policy_revision(
            workspace,
            CLASS_ID,
            first.policy_id,
            1,
        ).policy
        == first
    )

    with pytest.raises(
        AcademicPeriodProficiencyStorageConflictError,
        match="contiguous",
    ):
        write_academic_period_proficiency_policy_revision(
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
    write_academic_period_proficiency_policy_revision(workspace, first)
    write_academic_period_proficiency_policy_revision(workspace, second)

    created = select_academic_period_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        first.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    assert created.disposition == "created"
    current = load_current_academic_period_proficiency_policy(
        workspace,
        CLASS_ID,
        first.policy_id,
    )
    assert current is not None
    assert current.policy == first

    with pytest.raises(
        AcademicPeriodProficiencyStorageConflictError,
        match="Expected",
    ):
        select_academic_period_proficiency_policy_revision(
            workspace,
            CLASS_ID,
            first.policy_id,
            2,
            expected_current_policy_revision=None,
        )

    updated = select_academic_period_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        first.policy_id,
        2,
        expected_current_policy_revision=1,
    )
    assert updated.disposition == "updated"

    historical = select_academic_period_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        first.policy_id,
        1,
        expected_current_policy_revision=2,
    )
    assert historical.disposition == "updated"
    assert (
        get_current_academic_period_proficiency_policy_revision(
            workspace,
            CLASS_ID,
            first.policy_id,
        )
        == 1
    )

    existing = select_academic_period_proficiency_policy_revision(
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

    write_academic_period_proficiency_policy_revision(
        workspace,
        policy(target, policy_id="z_policy"),
    )
    write_academic_period_proficiency_policy_revision(
        workspace,
        policy(target, policy_id="a_policy"),
    )

    assert list_academic_period_proficiency_policy_ids(
        workspace,
        CLASS_ID,
    ) == ("a_policy", "z_policy")


def test_policy_pointer_tamper_fails_closed(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)
    value = policy(target)
    write_academic_period_proficiency_policy_revision(workspace, value)
    select_academic_period_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        value.policy_id,
        1,
        expected_current_policy_revision=None,
    )

    pointer = academic_period_proficiency_policy_current_path(
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
        AcademicPeriodProficiencyStorageIntegrityError,
        match="digest",
    ):
        load_current_academic_period_proficiency_policy(
            workspace,
            CLASS_ID,
            value.policy_id,
        )


def test_policy_revision_digest_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)
    stored = write_academic_period_proficiency_policy_revision(
        workspace,
        policy(target),
    ).stored

    stored.path.write_bytes(stored.content + b" ")
    with pytest.raises(
        AcademicPeriodProficiencyStorageIntegrityError,
        match="digest",
    ):
        load_academic_period_proficiency_policy_revision(
            workspace,
            CLASS_ID,
            stored.policy.policy_id,
            1,
        )


def test_unexpected_policy_entry_fails_closed(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    target = persisted_scale(workspace)
    stored = write_academic_period_proficiency_policy_revision(
        workspace,
        policy(target),
    ).stored

    (stored.path.parent.parent / "latest.json").write_text(
        "{}",
        encoding="utf-8",
    )
    with pytest.raises(
        AcademicPeriodProficiencyStorageIntegrityError,
        match="unexpected",
    ):
        load_academic_period_proficiency_policy_revision(
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
    stored = write_academic_period_proficiency_policy_revision(
        workspace,
        value,
    ).stored

    select_academic_period_proficiency_policy_revision(
        workspace,
        CLASS_ID,
        value.policy_id,
        1,
        expected_current_policy_revision=None,
    )
    current = load_current_academic_period_proficiency_policy(
        workspace,
        CLASS_ID,
        value.policy_id,
    )
    assert current is not None
    assert current.reference == stored.reference
    assert current.policy_sha256 == stored.policy_sha256



def period_result_snapshot(
    *,
    revision: int = 1,
    period_id: str = PERIOD_ID,
    standard_id: str = STANDARD_ID,
) -> AcademicPeriodProficiencyResultSnapshot:
    target_scale = scale()
    target = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, period_id),
        1,
    )
    inputs = AcademicPeriodProficiencyAggregationInputs(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=target,
        student_id=STUDENT_ID,
        standard_id=standard_id,
        target_scale=proficiency_scale_reference(target_scale),
        period_membership_scope="direct",
        entries=(),
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        policy(target_scale),
        target_scale,
    )
    return create_academic_period_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=revision,
        calculated_at=NOW + timedelta(minutes=revision - 1),
    )


def seed_result_revision(
    workspace: Path,
    snapshot: AcademicPeriodProficiencyResultSnapshot,
    *,
    path_period_id: str | None = None,
) -> Path:
    period = snapshot.target_period.period
    path = academic_period_proficiency_result_revision_path(
        workspace,
        snapshot.class_id,
        period.school_year,
        path_period_id or period.period_id,
        snapshot.student_id,
        snapshot.standard_id,
        snapshot.result_revision,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    content = academic_period_proficiency_result_snapshot_to_json_bytes(snapshot)
    path.write_bytes(content)
    Path(str(path) + ".sha256").write_text(
        hashlib.sha256(content).hexdigest() + "\n",
        encoding="ascii",
        newline="\n",
    )
    return path


def test_result_family_path_uses_durable_period_and_hashed_standard() -> None:
    standard_key = academic_period_proficiency_standard_key(STANDARD_ID)
    assert len(standard_key) == 64
    assert standard_key == academic_period_proficiency_standard_key(STANDARD_ID)
    assert academic_period_proficiency_result_revision_relative_path(
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
    ) == (
        "classes/synthetic_class_2026/modules/meridian/"
        "academic_period_proficiency/results/school_years/2026-2027/"
        "periods/mp1/students/student_1/standards/"
        f"{standard_key}/revisions/1.json"
    )


def test_result_revision_load_verifies_exact_bytes_and_reference(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    snapshot = period_result_snapshot()
    path = seed_result_revision(workspace, snapshot)

    stored = load_academic_period_proficiency_result_revision(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
    )
    assert stored.snapshot == snapshot
    assert stored.path == path
    assert stored.content == path.read_bytes()
    assert stored.reference.class_id == CLASS_ID
    assert stored.reference.period_id == PERIOD_ID
    assert stored.reference.result_sha256 == hashlib.sha256(
        stored.content
    ).hexdigest()


def test_result_history_is_contiguous_and_transition_validated(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    seed_result_revision(workspace, period_result_snapshot(revision=1))
    seed_result_revision(workspace, period_result_snapshot(revision=2))

    assert list_academic_period_proficiency_result_revisions(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
    ) == (1, 2)


def test_result_revision_digest_tamper_fails_closed(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    path = seed_result_revision(workspace, period_result_snapshot())
    path.write_bytes(path.read_bytes() + b" ")

    with pytest.raises(
        AcademicPeriodProficiencyStorageIntegrityError,
        match="digest",
    ):
        load_academic_period_proficiency_result_revision(
            workspace,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            STUDENT_ID,
            STANDARD_ID,
            1,
        )


def test_result_path_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    snapshot = period_result_snapshot(period_id="mp2")
    seed_result_revision(
        workspace,
        snapshot,
        path_period_id=PERIOD_ID,
    )

    with pytest.raises(
        AcademicPeriodProficiencyStorageIntegrityError,
        match="identity",
    ):
        load_academic_period_proficiency_result_revision(
            workspace,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            STUDENT_ID,
            STANDARD_ID,
            1,
        )


def test_result_history_requires_complete_json_digest_pairs(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    path = seed_result_revision(workspace, period_result_snapshot())
    Path(str(path) + ".sha256").unlink()

    with pytest.raises(
        AcademicPeriodProficiencyStorageIntegrityError,
        match="incomplete",
    ):
        list_academic_period_proficiency_result_revisions(
            workspace,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            STUDENT_ID,
            STANDARD_ID,
        )


def test_result_history_rejects_noncontiguous_revision_numbers(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    seed_result_revision(workspace, period_result_snapshot(revision=1))
    seed_result_revision(workspace, period_result_snapshot(revision=3))

    with pytest.raises(
        AcademicPeriodProficiencyStorageIntegrityError,
        match="contiguous",
    ):
        list_academic_period_proficiency_result_revisions(
            workspace,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            STUDENT_ID,
            STANDARD_ID,
        )


def test_result_family_rejects_unexpected_entries(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    snapshot = period_result_snapshot()
    seed_result_revision(workspace, snapshot)
    family = academic_period_proficiency_result_family_directory(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
    )
    (family / "latest.json").write_text("{}", encoding="utf-8")

    with pytest.raises(
        AcademicPeriodProficiencyStorageIntegrityError,
        match="unexpected",
    ):
        load_academic_period_proficiency_result_revision(
            workspace,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            STUDENT_ID,
            STANDARD_ID,
            1,
        )

def persist_result_top_level_dependencies(
    workspace: Path,
    *,
    include_metadata: bool = True,
    include_calendar: bool = True,
    include_policy: bool = True,
) -> None:
    if include_metadata:
        metadata = ClassMetadata(
            class_id=CLASS_ID,
            school_year=SCHOOL_YEAR,
            created_at=NOW,
            updated_at=NOW,
            module_details={},
        )
        write_class_metadata(class_metadata_path(workspace, CLASS_ID), metadata)

    target_scale = persisted_scale(workspace)
    if include_policy:
        write_academic_period_proficiency_policy_revision(
            workspace,
            policy(target_scale),
        )

    if include_calendar:
        calendar = AcademicPeriodCalendar(
            schema_version="1",
            record_type="academic_period_calendar",
            school_year=SCHOOL_YEAR,
            calendar_revision=1,
            created_at=NOW,
            updated_at=NOW,
            periods=(
                AcademicPeriod(
                    period_id=PERIOD_ID,
                    period_type="marking_period",
                    label="Marking Period 1",
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 11, 8),
                    parent_period_id=None,
                    sequence=1,
                    lifecycle="active",
                ),
            ),
        )
        write_academic_period_calendar(
            workspace,
            calendar,
            expected_current_revision=None,
        )


def period_result_with_missing_grade_item() -> AcademicPeriodProficiencyResultSnapshot:
    target_scale = scale()
    target = AcademicPeriodProficiencyTarget(
        AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID),
        1,
    )
    grade_item = GradeItemAggregationBasis(
        class_id=CLASS_ID,
        grade_item_id="missing_item",
        grade_item_revision=1,
        grade_item_revision_sha256="a" * 64,
    )
    membership = AcademicPeriodProficiencyMembershipBasis(
        grade_item_id="missing_item",
        grade_item_revision=1,
        grade_item_revision_sha256="a" * 64,
        work_reference=GradeItemWorkReference(
            work=ModuleWorkRef(
                module_id="scoreform",
                class_id=CLASS_ID,
                work_id="missing_work",
            ),
            registration_revision=1,
        ),
        membership_revision=1,
        membership_sha256="b" * 64,
        academic_period=target,
    )
    entry = AcademicPeriodProficiencyAggregationInputEntry(
        grade_item=grade_item,
        memberships=(membership,),
        status="missing_result",
        period_scope_mismatch_reason=None,
        result_reference=None,
        result_algorithm_version=None,
        result_calculation_fingerprint=None,
        result_status=None,
        proficiency_level_id=None,
        result_insufficiency_reasons=(),
    )
    inputs = AcademicPeriodProficiencyAggregationInputs(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=target,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=proficiency_scale_reference(target_scale),
        period_membership_scope="direct",
        entries=(entry,),
    )
    outcome = calculate_academic_period_proficiency(
        inputs,
        policy(target_scale),
        target_scale,
    )
    return create_academic_period_proficiency_result_snapshot(
        inputs,
        outcome,
        result_revision=1,
        calculated_at=NOW,
    )


def test_result_write_is_immutable_and_exact_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    persist_result_top_level_dependencies(workspace)
    snapshot = period_result_snapshot()

    first = write_academic_period_proficiency_result_revision(
        workspace,
        snapshot,
    )
    retry = write_academic_period_proficiency_result_revision(
        workspace,
        snapshot,
    )

    assert first.disposition == "created"
    assert retry.disposition == "existing"
    assert retry.stored.reference == first.stored.reference
    assert first.stored.content == (
        academic_period_proficiency_result_snapshot_to_json_bytes(snapshot)
    )


def test_result_write_requires_contiguous_history(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    persist_result_top_level_dependencies(workspace)

    with pytest.raises(
        AcademicPeriodProficiencyStorageConflictError,
        match="Initial",
    ):
        write_academic_period_proficiency_result_revision(
            workspace,
            period_result_snapshot(revision=2),
        )

    write_academic_period_proficiency_result_revision(
        workspace,
        period_result_snapshot(revision=1),
    )
    second = write_academic_period_proficiency_result_revision(
        workspace,
        period_result_snapshot(revision=2),
    )
    assert second.disposition == "created"
    assert list_academic_period_proficiency_result_revisions(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
    ) == (1, 2)


def test_result_write_same_revision_different_content_conflicts(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    persist_result_top_level_dependencies(workspace)
    snapshot = period_result_snapshot()
    write_academic_period_proficiency_result_revision(workspace, snapshot)

    changed = replace(
        snapshot,
        calculated_at=snapshot.calculated_at + timedelta(minutes=10),
    )
    with pytest.raises(
        AcademicPeriodProficiencyStorageConflictError,
        match="different content",
    ):
        write_academic_period_proficiency_result_revision(workspace, changed)


@pytest.mark.parametrize(
    ("metadata", "calendar", "policy_present", "message"),
    [
        (False, True, True, "class metadata"),
        (True, False, True, "Calendar"),
        (True, True, False, "aggregation-policy"),
    ],
)
def test_result_write_requires_exact_top_level_dependencies(
    tmp_path: Path,
    metadata: bool,
    calendar: bool,
    policy_present: bool,
    message: str,
) -> None:
    workspace = root(tmp_path)
    persist_result_top_level_dependencies(
        workspace,
        include_metadata=metadata,
        include_calendar=calendar,
        include_policy=policy_present,
    )

    with pytest.raises(
        AcademicPeriodProficiencyResultDependencyError,
        match=message,
    ):
        write_academic_period_proficiency_result_revision(
            workspace,
            period_result_snapshot(),
        )


def test_result_write_walks_bounded_input_grade_item_dependencies(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    persist_result_top_level_dependencies(workspace)

    with pytest.raises(
        AcademicPeriodProficiencyResultDependencyError,
        match="Grade Item",
    ):
        write_academic_period_proficiency_result_revision(
            workspace,
            period_result_with_missing_grade_item(),
        )


def test_result_write_does_not_auto_select_current(tmp_path: Path) -> None:
    workspace = root(tmp_path)
    persist_result_top_level_dependencies(workspace)
    write_academic_period_proficiency_result_revision(
        workspace,
        period_result_snapshot(),
    )

    assert get_current_academic_period_proficiency_result_revision(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
    ) is None
    assert load_current_academic_period_proficiency_result(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
    ) is None


def test_result_current_selection_is_explicit_and_sha_bound(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    persist_result_top_level_dependencies(workspace)
    stored = write_academic_period_proficiency_result_revision(
        workspace,
        period_result_snapshot(),
    ).stored

    selected = select_academic_period_proficiency_result_revision(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    assert selected.disposition == "created"
    current = load_current_academic_period_proficiency_result(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
    )
    assert current is not None
    assert current.reference == stored.reference
    assert get_current_academic_period_proficiency_result_revision(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
    ) == 1


def test_result_selection_supports_cas_and_historical_reselection(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    persist_result_top_level_dependencies(workspace)
    write_academic_period_proficiency_result_revision(
        workspace,
        period_result_snapshot(revision=1),
    )
    write_academic_period_proficiency_result_revision(
        workspace,
        period_result_snapshot(revision=2),
    )
    select_academic_period_proficiency_result_revision(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )

    with pytest.raises(
        AcademicPeriodProficiencyStorageConflictError,
        match="Expected current",
    ):
        select_academic_period_proficiency_result_revision(
            workspace,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            STUDENT_ID,
            STANDARD_ID,
            2,
            expected_current_result_revision=None,
        )

    updated = select_academic_period_proficiency_result_revision(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        2,
        expected_current_result_revision=1,
    )
    assert updated.disposition == "updated"
    historical = select_academic_period_proficiency_result_revision(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=2,
    )
    assert historical.disposition == "updated"
    existing = select_academic_period_proficiency_result_revision(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=1,
    )
    assert existing.disposition == "existing"


def test_result_current_pointer_digest_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    workspace = root(tmp_path)
    persist_result_top_level_dependencies(workspace)
    write_academic_period_proficiency_result_revision(
        workspace,
        period_result_snapshot(),
    )
    select_academic_period_proficiency_result_revision(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        1,
        expected_current_result_revision=None,
    )
    pointer = academic_period_proficiency_result_current_path(
        workspace,
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
    )
    data = json.loads(pointer.read_text(encoding="utf-8"))
    data["result_sha256"] = "0" * 64
    pointer.write_bytes(
        (json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )

    with pytest.raises(
        AcademicPeriodProficiencyStorageIntegrityError,
        match="digest",
    ):
        load_current_academic_period_proficiency_result(
            workspace,
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            STUDENT_ID,
            STANDARD_ID,
        )

