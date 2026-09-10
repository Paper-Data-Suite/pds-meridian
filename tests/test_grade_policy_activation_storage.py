from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)

from meridian.grade_item_storage import write_grade_item_revision
from meridian.grade_items import GradeItemRevision
from meridian.grade_policy import (
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
)
from meridian.grade_policy_activation import (
    GRADE_POLICY_ACTIVATION_RECORD_TYPE,
    GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
    GradePolicyActivationDecision,
)
from meridian.grade_policy_activation_storage import (
    GradePolicyActivationDependencyError,
    GradePolicyActivationStorageConflictError,
    GradePolicyActivationStorageIntegrityError,
    GradePolicyActivationStorageLockError,
    GradePolicyActivationStorageTooLargeError,
    get_current_grade_policy_activation_revision,
    grade_policy_activation_current_path,
    grade_policy_activation_directory,
    grade_policy_activation_revision_digest_path,
    grade_policy_activation_revision_path,
    grade_policy_activation_revision_relative_path,
    list_grade_policy_activation_revisions,
    load_current_grade_policy_activation,
    load_grade_policy_activation_revision,
    resolve_grade_policy_activation,
    select_grade_policy_activation_revision,
    validate_grade_policy_activation_dependencies,
    write_grade_policy_activation_revision,
)
from meridian.grade_policy_storage import (
    get_current_grade_policy_revision,
    select_grade_policy_revision,
    write_grade_policy_revision,
)

CLASS_ID = "synthetic_class_2026"
PERIOD1 = AcademicPeriodRef("2026-2027", "mp1")
PERIOD2 = AcademicPeriodRef("2026-2027", "mp2")
NOW = datetime(2026, 9, 9, 22, 15, tzinfo=UTC)


def make_workspace(tmp_path: Path) -> Path:
    class_root = tmp_path / "classes" / CLASS_ID
    class_root.mkdir(parents=True)
    (class_root / "roster.csv").write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "synthetic_class_2026,s001,Synthetic,Student,1\n",
        encoding="utf-8",
    )
    write_calendar(tmp_path, 1)
    return tmp_path


def calendar(revision: int) -> AcademicPeriodCalendar:
    return AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year="2026-2027",
        calendar_revision=revision,
        created_at=NOW,
        updated_at=NOW + timedelta(hours=revision - 1),
        periods=(
            AcademicPeriod(
                period_id="mp1",
                period_type="marking_period",
                label="Marking Period 1",
                start_date=date(2026, 9, 7),
                end_date=date(2026, 11, 6),
                parent_period_id=None,
                sequence=1,
                lifecycle="active",
            ),
            AcademicPeriod(
                period_id="mp2",
                period_type="marking_period",
                label="Marking Period 2",
                start_date=date(2026, 11, 7),
                end_date=date(2027, 1, 29),
                parent_period_id=None,
                sequence=2,
                lifecycle="planned",
            ),
        ),
    )


def write_calendar(root: Path, revision: int) -> None:
    write_academic_period_calendar(
        root,
        calendar(revision),
        expected_current_revision=None if revision == 1 else revision - 1,
    )


def state_treatment() -> GradeStateTreatment:
    return GradeStateTreatment(
        missing="blocking",
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="blocking",
        unavailable="blocking",
        withdrawn="exclude",
        invalid="exclude",
        unresolved="blocking",
    )


def write_item(root: Path) -> GradePolicyItemReference:
    item = GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id=CLASS_ID,
        grade_item_id="unit1_test",
        grade_item_revision=1,
        supersedes_revision=None,
        title="Unit 1 Test",
        purpose="standards_and_conventional",
        status="active",
        weighting=None,
        created_at=NOW,
        revised_at=NOW,
    )
    stored = write_grade_item_revision(root, item).stored
    return GradePolicyItemReference(
        CLASS_ID,
        "unit1_test",
        1,
        stored.revision_sha256,
    )


def policy(
    item_reference: GradePolicyItemReference,
    *,
    revision: int = 1,
    title: str | None = None,
) -> GradePolicyRevision:
    return GradePolicyRevision(
        schema_version="1",
        record_type="meridian_grade_policy",
        class_id=CLASS_ID,
        policy_id="course_grade_policy",
        policy_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title=title or f"Course Grade Policy r{revision}",
        calculation_family="conventional",
        configuration=ConventionalGradeConfiguration(
            "total_points",
            (GradePolicyItemParticipation(item_reference, None, None),),
            (),
        ),
        state_treatment=state_treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW + timedelta(hours=revision - 1),
    )


def write_policy(root: Path, *, revisions: int = 1):
    item_reference = write_item(root)
    stored = None
    for revision in range(1, revisions + 1):
        stored = write_grade_policy_revision(
            root, policy(item_reference, revision=revision)
        ).stored
    assert stored is not None
    return stored


def activation(
    policy_reference,
    *,
    revision: int = 1,
    target_period: AcademicPeriodRef = PERIOD1,
    calendar_revision: int = 1,
    decision: str = "activate",
) -> GradePolicyActivationDecision:
    return GradePolicyActivationDecision(
        schema_version=GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
        record_type=GRADE_POLICY_ACTIVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=target_period,
        calendar_revision=calendar_revision,
        activation_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision=decision,  # type: ignore[arg-type]
        policy_reference=policy_reference if decision == "activate" else None,
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        decided_at=NOW + timedelta(hours=revision - 1),
    )


def test_write_uses_period_scoped_canonical_path_and_does_not_select(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    result = write_grade_policy_activation_revision(
        root, activation(stored_policy.reference)
    )
    assert result.disposition == "created"
    assert result.stored.relative_path == (
        "classes/synthetic_class_2026/modules/meridian/"
        "grade_policy_activations/2026-2027/mp1/revisions/1.json"
    )
    assert get_current_grade_policy_activation_revision(
        root, CLASS_ID, PERIOD1
    ) is None


def test_exact_retry_is_idempotent_and_collision_conflicts(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    value = activation(stored_policy.reference)
    first = write_grade_policy_activation_revision(root, value)
    second = write_grade_policy_activation_revision(root, value)
    assert second.disposition == "existing"
    assert first.stored.activation_sha256 == second.stored.activation_sha256

    changed = replace(value, rationale="Different")
    with pytest.raises(GradePolicyActivationStorageConflictError):
        write_grade_policy_activation_revision(root, changed)


def test_history_is_contiguous_and_preserved(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    first = write_grade_policy_activation_revision(
        root, activation(stored_policy.reference)
    ).stored.content
    write_grade_policy_activation_revision(
        root,
        activation(
            None,
            revision=2,
            decision="deactivate",
        ),
    )
    assert list_grade_policy_activation_revisions(
        root, CLASS_ID, PERIOD1
    ) == (1, 2)
    assert load_grade_policy_activation_revision(
        root, CLASS_ID, PERIOD1, 1
    ).content == first


def test_activation_requires_exact_calendar_and_period(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    with pytest.raises(GradePolicyActivationDependencyError):
        write_grade_policy_activation_revision(
            root,
            activation(stored_policy.reference, calendar_revision=2),
        )
    with pytest.raises(GradePolicyActivationDependencyError):
        write_grade_policy_activation_revision(
            root,
            activation(
                stored_policy.reference,
                target_period=AcademicPeriodRef("2026-2027", "missing"),
            ),
        )


def test_activation_requires_exact_policy_digest(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    bad = replace(
        stored_policy.reference,
        policy_sha256="0" * 64,
    )
    with pytest.raises(GradePolicyActivationDependencyError):
        write_grade_policy_activation_revision(root, activation(bad))


def test_deactivate_validates_period_without_requiring_policy(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    decision = activation(None, decision="deactivate")
    dependencies = validate_grade_policy_activation_dependencies(root, decision)
    assert dependencies.policy is None
    write_grade_policy_activation_revision(root, decision)


def test_selection_is_explicit_cas_and_can_reselect_history(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    write_grade_policy_activation_revision(
        root, activation(stored_policy.reference)
    )
    write_grade_policy_activation_revision(
        root, activation(None, revision=2, decision="deactivate")
    )

    selected2 = select_grade_policy_activation_revision(
        root,
        CLASS_ID,
        PERIOD1,
        2,
        expected_current_revision=None,
    )
    assert selected2.disposition == "created"
    assert resolve_grade_policy_activation(root, CLASS_ID, PERIOD1).status == (
        "deactivated"
    )

    selected1 = select_grade_policy_activation_revision(
        root,
        CLASS_ID,
        PERIOD1,
        1,
        expected_current_revision=2,
    )
    assert selected1.disposition == "updated"
    resolution = resolve_grade_policy_activation(root, CLASS_ID, PERIOD1)
    assert resolution.status == "activated"
    assert resolution.policy_reference == stored_policy.reference


def test_unconfigured_deactivated_and_activated_are_distinct(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)

    unconfigured = resolve_grade_policy_activation(root, CLASS_ID, PERIOD1)
    assert unconfigured.status == "unconfigured"
    assert unconfigured.activation is None

    write_grade_policy_activation_revision(
        root, activation(None, decision="deactivate")
    )
    select_grade_policy_activation_revision(
        root, CLASS_ID, PERIOD1, 1, expected_current_revision=None
    )
    assert resolve_grade_policy_activation(
        root, CLASS_ID, PERIOD1
    ).status == "deactivated"

    write_grade_policy_activation_revision(
        root, activation(stored_policy.reference, revision=2)
    )
    select_grade_policy_activation_revision(
        root, CLASS_ID, PERIOD1, 2, expected_current_revision=1
    )
    assert resolve_grade_policy_activation(
        root, CLASS_ID, PERIOD1
    ).status == "activated"


def test_policy_family_current_change_does_not_change_period_activation(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    item_reference = write_item(root)
    p1 = write_grade_policy_revision(root, policy(item_reference, revision=1)).stored
    p2 = write_grade_policy_revision(root, policy(item_reference, revision=2)).stored

    select_grade_policy_revision(
        root,
        CLASS_ID,
        "course_grade_policy",
        1,
        expected_current_revision=None,
    )
    write_grade_policy_activation_revision(root, activation(p1.reference))
    select_grade_policy_activation_revision(
        root, CLASS_ID, PERIOD1, 1, expected_current_revision=None
    )

    select_grade_policy_revision(
        root,
        CLASS_ID,
        "course_grade_policy",
        2,
        expected_current_revision=1,
    )
    assert get_current_grade_policy_revision(
        root, CLASS_ID, "course_grade_policy"
    ) == 2
    resolved = resolve_grade_policy_activation(root, CLASS_ID, PERIOD1)
    assert resolved.policy_reference == p1.reference
    assert resolved.policy_reference != p2.reference


def test_new_policy_revision_does_not_activate_automatically(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    item_reference = write_item(root)
    p1 = write_grade_policy_revision(root, policy(item_reference, revision=1)).stored
    write_grade_policy_activation_revision(root, activation(p1.reference))
    select_grade_policy_activation_revision(
        root, CLASS_ID, PERIOD1, 1, expected_current_revision=None
    )
    write_grade_policy_revision(root, policy(item_reference, revision=2))
    assert resolve_grade_policy_activation(
        root, CLASS_ID, PERIOD1
    ).policy_reference == p1.reference


def test_periods_are_independent_and_have_no_inheritance(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    write_grade_policy_activation_revision(
        root, activation(stored_policy.reference, target_period=PERIOD1)
    )
    select_grade_policy_activation_revision(
        root, CLASS_ID, PERIOD1, 1, expected_current_revision=None
    )
    assert resolve_grade_policy_activation(
        root, CLASS_ID, PERIOD1
    ).status == "activated"
    assert resolve_grade_policy_activation(
        root, CLASS_ID, PERIOD2
    ).status == "unconfigured"


def test_calendar_revision_can_change_only_through_new_activation_revision(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    write_grade_policy_activation_revision(
        root, activation(stored_policy.reference, calendar_revision=1)
    )
    select_grade_policy_activation_revision(
        root, CLASS_ID, PERIOD1, 1, expected_current_revision=None
    )
    write_calendar(root, 2)
    assert load_current_grade_policy_activation(
        root, CLASS_ID, PERIOD1
    ).decision.calendar_revision == 1

    write_grade_policy_activation_revision(
        root,
        activation(
            stored_policy.reference,
            revision=2,
            calendar_revision=2,
        ),
    )
    assert load_current_grade_policy_activation(
        root, CLASS_ID, PERIOD1
    ).decision.calendar_revision == 1


def test_selection_stale_cas_fails(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    write_grade_policy_activation_revision(
        root, activation(stored_policy.reference)
    )
    select_grade_policy_activation_revision(
        root, CLASS_ID, PERIOD1, 1, expected_current_revision=None
    )
    with pytest.raises(GradePolicyActivationStorageConflictError):
        select_grade_policy_activation_revision(
            root, CLASS_ID, PERIOD1, 1, expected_current_revision=None
        )


def test_revision_and_pointer_tampering_fail_closed(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    write_grade_policy_activation_revision(
        root, activation(stored_policy.reference)
    )
    select_grade_policy_activation_revision(
        root, CLASS_ID, PERIOD1, 1, expected_current_revision=None
    )

    current = grade_policy_activation_current_path(root, CLASS_ID, PERIOD1)
    data = json.loads(current.read_text(encoding="utf-8"))
    data["activation_sha256"] = "0" * 64
    current.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(GradePolicyActivationStorageIntegrityError):
        load_current_grade_policy_activation(root, CLASS_ID, PERIOD1)


def test_revision_digest_tampering_fails(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    write_grade_policy_activation_revision(
        root, activation(stored_policy.reference)
    )
    digest = grade_policy_activation_revision_digest_path(
        root, CLASS_ID, PERIOD1, 1
    )
    digest.write_text("0" * 64 + "\n", encoding="ascii")
    with pytest.raises(GradePolicyActivationStorageIntegrityError):
        load_grade_policy_activation_revision(root, CLASS_ID, PERIOD1, 1)


def test_noncanonical_sidecar_and_bounded_read_fail(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    created = write_grade_policy_activation_revision(
        root, activation(stored_policy.reference)
    )
    digest = grade_policy_activation_revision_digest_path(
        root, CLASS_ID, PERIOD1, 1
    )
    digest.write_bytes(
        (created.stored.activation_sha256 + "\r\n").encode("ascii")
    )
    with pytest.raises(
        GradePolicyActivationStorageIntegrityError,
        match="not canonical",
    ):
        load_grade_policy_activation_revision(root, CLASS_ID, PERIOD1, 1)

    digest.write_text(
        created.stored.activation_sha256 + "\n", encoding="ascii"
    )
    with pytest.raises(GradePolicyActivationStorageTooLargeError):
        load_grade_policy_activation_revision(
            root,
            CLASS_ID,
            PERIOD1,
            1,
            maximum_revision_bytes=8,
        )


def test_unexpected_entry_and_lock_fail_closed(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    write_grade_policy_activation_revision(
        root, activation(stored_policy.reference)
    )
    relation = grade_policy_activation_directory(root, CLASS_ID, PERIOD1)
    (relation / "notes.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(GradePolicyActivationStorageIntegrityError):
        list_grade_policy_activation_revisions(root, CLASS_ID, PERIOD1)
    (relation / "notes.txt").unlink()

    lock = relation / ".write.lock"
    lock.write_text("leftover", encoding="utf-8")
    with pytest.raises(GradePolicyActivationStorageLockError):
        write_grade_policy_activation_revision(
            root, activation(None, revision=2, decision="deactivate")
        )


def test_relative_path_is_platform_neutral(tmp_path: Path) -> None:
    make_workspace(tmp_path)
    path = grade_policy_activation_revision_relative_path(
        CLASS_ID, PERIOD1, 3
    )
    assert path == (
        "classes/synthetic_class_2026/modules/meridian/"
        "grade_policy_activations/2026-2027/mp1/revisions/3.json"
    )
    assert "\\" not in path


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_symlinked_revision_is_rejected(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    write_grade_policy_activation_revision(
        root, activation(stored_policy.reference)
    )
    path = grade_policy_activation_revision_path(
        root, CLASS_ID, PERIOD1, 1
    )
    outside = tmp_path / "outside.json"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is not permitted on this platform")
    with pytest.raises(GradePolicyActivationStorageIntegrityError):
        load_grade_policy_activation_revision(root, CLASS_ID, PERIOD1, 1)


def test_activation_does_not_mutate_policy_or_core_state(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored_policy = write_policy(root)
    policy_before = stored_policy.content
    calendar_path = (
        root
        / "settings"
        / "academic_periods"
        / "2026-2027"
        / "revisions"
        / "1.json"
    )
    calendar_before = calendar_path.read_bytes()

    write_grade_policy_activation_revision(
        root, activation(stored_policy.reference)
    )
    select_grade_policy_activation_revision(
        root, CLASS_ID, PERIOD1, 1, expected_current_revision=None
    )

    assert stored_policy.path.read_bytes() == policy_before
    assert calendar_path.read_bytes() == calendar_before
