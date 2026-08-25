from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)
from pds_core.academic_work_registration_storage import (
    write_academic_work_registration,
)
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.routes import class_metadata_path, module_work_dir
from pds_core.routing_models import ModuleWorkRef

from meridian.grade_item_membership_storage import (
    GRADE_ITEM_MEMBERSHIP_CURRENT_RECORD_TYPE,
    GradeItemMembershipDependencyError,
    GradeItemMembershipStorageConflictError,
    GradeItemMembershipStorageIntegrityError,
    GradeItemMembershipStorageLockError,
    GradeItemMembershipStorageTooLargeError,
    get_current_grade_item_membership_revision,
    grade_item_membership_current_path,
    grade_item_membership_directory,
    grade_item_membership_revision_digest_path,
    grade_item_membership_revision_path,
    grade_item_membership_revision_relative_path,
    list_grade_item_membership_revisions,
    list_grade_item_membership_work_refs,
    list_selected_included_grade_item_memberships,
    load_current_grade_item_membership_decision,
    load_grade_item_membership_revision,
    select_grade_item_membership_revision,
    validate_grade_item_membership_dependencies,
    write_grade_item_membership_revision,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_storage import (
    list_grade_item_revisions,
    select_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import GradeItemRevision, GradeItemWorkReference

CLASS_ID = "synthetic_class_2026"
SCHOOL_YEAR = "2026-2027"
ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")
OTHER_WORK = ModuleWorkRef(
    module_id="quillan", class_id=CLASS_ID, work_id="essay_1"
)
CREATED = datetime(2026, 8, 25, 12, tzinfo=UTC)


def make_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    metadata = ClassMetadata(
        class_id=CLASS_ID,
        school_year=SCHOOL_YEAR,
        created_at=CREATED,
        updated_at=CREATED,
        module_details={},
    )
    write_class_metadata(class_metadata_path(root, CLASS_ID), metadata)

    calendar = AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year=SCHOOL_YEAR,
        calendar_revision=1,
        created_at=CREATED,
        updated_at=CREATED,
        periods=(
            AcademicPeriod(
                period_id="mp1",
                period_type="marking_period",
                label="Marking Period 1",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 11, 8),
                parent_period_id=None,
                sequence=1,
                lifecycle="active",
            ),
            AcademicPeriod(
                period_id="mp2",
                period_type="marking_period",
                label="Marking Period 2",
                start_date=date(2026, 11, 9),
                end_date=date(2027, 1, 20),
                parent_period_id=None,
                sequence=2,
                lifecycle="planned",
            ),
            AcademicPeriod(
                period_id="closed_window",
                period_type="progress_window",
                label="Closed Window",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 9, 15),
                parent_period_id=None,
                sequence=3,
                lifecycle="closed",
            ),
            AcademicPeriod(
                period_id="cancelled_window",
                period_type="custom",
                label="Cancelled Window",
                start_date=date(2026, 10, 1),
                end_date=date(2026, 10, 2),
                parent_period_id=None,
                sequence=4,
                lifecycle="cancelled",
            ),
        ),
    )
    write_academic_period_calendar(root, calendar, expected_current_revision=None)
    write_registration(root, WORK)
    write_registration(root, OTHER_WORK)
    return root


def write_registration(
    root: Path,
    work: ModuleWorkRef,
    *,
    revision: int = 1,
    lifecycle: str = "active",
    expected_current_revision: int | None = None,
) -> None:
    work_root = module_work_dir(root, work)
    work_root.mkdir(parents=True, exist_ok=True)
    registration = AcademicWorkRegistration(
        schema_version="1",
        record_type="academic_work_registration",
        work=work,
        registration_revision=revision,
        producer_contract_version="v1",
        title=f"Synthetic {work.work_id}",
        work_kind="assessment",
        academic_intent="summative",
        lifecycle=lifecycle,  # type: ignore[arg-type]
        created_at=CREATED,
        updated_at=CREATED + timedelta(minutes=revision - 1),
        source_records=(),
    )
    write_academic_work_registration(
        root,
        registration,
        expected_current_revision=expected_current_revision,
    )


def write_grade_item(
    root: Path,
    *,
    grade_item_id: str = ITEM_ID,
    status: str = "active",
) -> str:
    grade_item = GradeItemRevision(
        schema_version="1",
        record_type="meridian_grade_item",
        class_id=CLASS_ID,
        grade_item_id=grade_item_id,
        grade_item_revision=1,
        supersedes_revision=None,
        title="Unit 1 Assessment",
        purpose="standards_proficiency",
        status=status,  # type: ignore[arg-type]
        weighting=None,
        created_at=CREATED,
        revised_at=CREATED,
    )
    stored = write_grade_item_revision(root, grade_item).stored
    return stored.revision_sha256


def membership(
    digest: str,
    *,
    revision: int = 1,
    work: ModuleWorkRef = WORK,
    registration_revision: int = 1,
    grade_item_id: str = ITEM_ID,
    grade_item_revision: int = 1,
    disposition: str = "included",
    period_id: str = "mp1",
    school_year: str = SCHOOL_YEAR,
    calendar_revision: int = 1,
) -> GradeItemMembershipDecision:
    assignment = (
        GradeItemAcademicPeriodAssignment(
            period=AcademicPeriodRef(
                school_year=school_year,
                period_id=period_id,
            ),
            calendar_revision=calendar_revision,
        )
        if disposition == "included"
        else None
    )
    return GradeItemMembershipDecision(
        schema_version="1",
        record_type="meridian_grade_item_membership",
        class_id=CLASS_ID,
        grade_item_id=grade_item_id,
        grade_item_revision=grade_item_revision,
        grade_item_revision_sha256=digest,
        work_reference=GradeItemWorkReference(
            work=work,
            registration_revision=registration_revision,
        ),
        membership_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision=disposition,  # type: ignore[arg-type]
        academic_period=assignment,
        actor_id="teacher_local",
        rationale=None,
        decided_at=CREATED + timedelta(hours=revision),
    )


def prepared(tmp_path: Path) -> tuple[Path, str]:
    root = make_workspace(tmp_path)
    return root, write_grade_item(root)


def test_dependency_validation_resolves_exact_authorities(tmp_path: Path) -> None:
    root, digest = prepared(tmp_path)
    resolved = validate_grade_item_membership_dependencies(root, membership(digest))
    assert resolved.grade_item.revision_sha256 == digest
    assert resolved.registration.work == WORK
    assert resolved.registration.registration_revision == 1
    assert resolved.class_metadata.school_year == SCHOOL_YEAR
    assert resolved.calendar is not None
    assert resolved.calendar.calendar_revision == 1
    assert resolved.period is not None
    assert resolved.period.period_id == "mp1"


def test_missing_or_wrong_grade_item_basis_fails(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    with pytest.raises(GradeItemMembershipDependencyError, match="Grade Item"):
        validate_grade_item_membership_dependencies(root, membership("a" * 64))
    digest = write_grade_item(root)
    with pytest.raises(GradeItemMembershipDependencyError, match="SHA-256"):
        validate_grade_item_membership_dependencies(root, membership("b" * 64))
    assert digest != "b" * 64


def test_included_archived_grade_item_is_rejected(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    digest = write_grade_item(root, status="archived")
    with pytest.raises(GradeItemMembershipDependencyError, match="archived"):
        write_grade_item_membership_revision(root, membership(digest))


def test_missing_registration_and_cancelled_registration_are_rejected(
    tmp_path: Path,
) -> None:
    root, digest = prepared(tmp_path)
    with pytest.raises(GradeItemMembershipDependencyError, match="Registration"):
        write_grade_item_membership_revision(
            root, membership(digest, registration_revision=2)
        )

    cancelled = ModuleWorkRef(
        module_id="scoreform", class_id=CLASS_ID, work_id="cancelled_test"
    )
    write_registration(root, cancelled, lifecycle="cancelled")
    with pytest.raises(GradeItemMembershipDependencyError, match="cancelled"):
        write_grade_item_membership_revision(
            root, membership(digest, work=cancelled)
        )


def test_period_school_year_missing_period_and_cancelled_period_are_rejected(
    tmp_path: Path,
) -> None:
    root, digest = prepared(tmp_path)
    with pytest.raises(GradeItemMembershipDependencyError, match="school_year"):
        write_grade_item_membership_revision(
            root, membership(digest, school_year="2025-2026")
        )
    with pytest.raises(GradeItemMembershipDependencyError, match="does not exist"):
        write_grade_item_membership_revision(
            root, membership(digest, period_id="missing")
        )
    with pytest.raises(GradeItemMembershipDependencyError, match="cancelled"):
        write_grade_item_membership_revision(
            root, membership(digest, period_id="cancelled_window")
        )


def test_closed_period_is_a_valid_explicit_target(tmp_path: Path) -> None:
    root, digest = prepared(tmp_path)
    result = write_grade_item_membership_revision(
        root, membership(digest, period_id="closed_window")
    )
    assert result.disposition == "created"


def test_excluded_decision_needs_no_period_but_still_validates_registration(
    tmp_path: Path,
) -> None:
    root, digest = prepared(tmp_path)
    excluded = membership(digest, disposition="excluded")
    result = write_grade_item_membership_revision(root, excluded)
    assert result.stored.decision.academic_period is None


def test_canonical_path_and_relative_path(tmp_path: Path) -> None:
    root, digest = prepared(tmp_path)
    stored = write_grade_item_membership_revision(root, membership(digest)).stored
    assert stored.relative_path == (
        "classes/synthetic_class_2026/modules/meridian/grade_items/"
        "unit1_assessment/memberships/scoreform/test_1/revisions/1.json"
    )
    assert stored.path == grade_item_membership_revision_path(
        root, CLASS_ID, ITEM_ID, WORK, 1
    )
    assert grade_item_membership_revision_relative_path(
        CLASS_ID, ITEM_ID, WORK, 1
    ) == stored.relative_path


def test_revision_write_is_immutable_and_exact_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    root, digest = prepared(tmp_path)
    first = write_grade_item_membership_revision(root, membership(digest))
    retry = write_grade_item_membership_revision(root, membership(digest))
    assert first.disposition == "created"
    assert retry.disposition == "existing"
    assert retry.stored.content == first.stored.content

    data = json.loads(first.stored.content)
    data["actor_id"] = "another_teacher"
    path = grade_item_membership_revision_path(root, CLASS_ID, ITEM_ID, WORK, 1)
    original = path.read_bytes()
    path.write_bytes((json.dumps(data, indent=2, sort_keys=True) + "\n").encode())
    with pytest.raises(GradeItemMembershipStorageIntegrityError):
        load_grade_item_membership_revision(root, CLASS_ID, ITEM_ID, WORK, 1)
    path.write_bytes(original)


def test_same_revision_identity_with_different_content_conflicts(
    tmp_path: Path,
) -> None:
    root, digest = prepared(tmp_path)
    write_grade_item_membership_revision(root, membership(digest))
    original = membership(digest)
    changed = GradeItemMembershipDecision(
        schema_version=original.schema_version,
        record_type=original.record_type,
        class_id=original.class_id,
        grade_item_id=original.grade_item_id,
        grade_item_revision=original.grade_item_revision,
        grade_item_revision_sha256=original.grade_item_revision_sha256,
        work_reference=original.work_reference,
        membership_revision=original.membership_revision,
        supersedes_revision=original.supersedes_revision,
        decision=original.decision,
        academic_period=original.academic_period,
        actor_id="other",
        rationale=original.rationale,
        decided_at=original.decided_at,
    )
    with pytest.raises(GradeItemMembershipStorageConflictError):
        write_grade_item_membership_revision(root, changed)


def test_membership_history_is_contiguous_and_can_change_basis(tmp_path: Path) -> None:
    root, digest = prepared(tmp_path)
    write_grade_item_membership_revision(root, membership(digest))
    write_registration(
        root,
        WORK,
        revision=2,
        lifecycle="active",
        expected_current_revision=1,
    )
    second = membership(
        digest,
        revision=2,
        registration_revision=2,
        disposition="excluded",
    )
    write_grade_item_membership_revision(root, second)
    assert list_grade_item_membership_revisions(root, CLASS_ID, ITEM_ID, WORK) == (
        1,
        2,
    )

    skipped = GradeItemMembershipDecision(
        schema_version="1",
        record_type="meridian_grade_item_membership",
        class_id=CLASS_ID,
        grade_item_id=ITEM_ID,
        grade_item_revision=1,
        grade_item_revision_sha256=digest,
        work_reference=GradeItemWorkReference(work=WORK, registration_revision=2),
        membership_revision=4,
        supersedes_revision=3,
        decision="excluded",
        academic_period=None,
        actor_id="teacher_local",
        rationale=None,
        decided_at=CREATED + timedelta(hours=4),
    )
    with pytest.raises(GradeItemMembershipStorageConflictError):
        write_grade_item_membership_revision(root, skipped)


def test_current_selection_is_explicit_and_historical_reselection_is_allowed(
    tmp_path: Path,
) -> None:
    root, digest = prepared(tmp_path)
    write_grade_item_membership_revision(root, membership(digest))
    write_grade_item_membership_revision(
        root, membership(digest, revision=2, disposition="excluded")
    )
    assert get_current_grade_item_membership_revision(
        root, CLASS_ID, ITEM_ID, WORK
    ) is None
    assert load_current_grade_item_membership_decision(
        root, CLASS_ID, ITEM_ID, WORK
    ) is None

    selected2 = select_grade_item_membership_revision(
        root,
        CLASS_ID,
        ITEM_ID,
        WORK,
        2,
        expected_current_membership_revision=None,
    )
    assert selected2.disposition == "created"
    assert selected2.stored.decision.decision == "excluded"

    selected1 = select_grade_item_membership_revision(
        root,
        CLASS_ID,
        ITEM_ID,
        WORK,
        1,
        expected_current_membership_revision=2,
    )
    assert selected1.disposition == "updated"
    assert selected1.stored.decision.decision == "included"


def test_selection_retry_and_stale_compare_and_swap(tmp_path: Path) -> None:
    root, digest = prepared(tmp_path)
    write_grade_item_membership_revision(root, membership(digest))
    first = select_grade_item_membership_revision(
        root,
        CLASS_ID,
        ITEM_ID,
        WORK,
        1,
        expected_current_membership_revision=None,
    )
    retry = select_grade_item_membership_revision(
        root,
        CLASS_ID,
        ITEM_ID,
        WORK,
        1,
        expected_current_membership_revision=1,
    )
    assert first.disposition == "created"
    assert retry.disposition == "existing"
    with pytest.raises(GradeItemMembershipStorageConflictError):
        select_grade_item_membership_revision(
            root,
            CLASS_ID,
            ITEM_ID,
            WORK,
            1,
            expected_current_membership_revision=None,
        )


def test_digest_and_pointer_tampering_fail_closed(tmp_path: Path) -> None:
    root, digest = prepared(tmp_path)
    stored = write_grade_item_membership_revision(root, membership(digest)).stored
    assert stored.decision_sha256 == hashlib.sha256(stored.content).hexdigest()

    sidecar = grade_item_membership_revision_digest_path(
        root, CLASS_ID, ITEM_ID, WORK, 1
    )
    sidecar.write_bytes(("0" * 64 + "\n").encode("ascii"))
    with pytest.raises(GradeItemMembershipStorageIntegrityError):
        load_grade_item_membership_revision(root, CLASS_ID, ITEM_ID, WORK, 1)


def test_digest_sidecar_rejects_crlf(tmp_path: Path) -> None:
    root, digest = prepared(tmp_path)
    stored = write_grade_item_membership_revision(root, membership(digest)).stored
    sidecar = grade_item_membership_revision_digest_path(
        root, CLASS_ID, ITEM_ID, WORK, 1
    )
    sidecar.write_bytes((stored.decision_sha256 + "\r\n").encode("ascii"))
    with pytest.raises(GradeItemMembershipStorageIntegrityError, match="canonical"):
        load_grade_item_membership_revision(root, CLASS_ID, ITEM_ID, WORK, 1)


def test_current_pointer_digest_is_verified(tmp_path: Path) -> None:
    root, digest = prepared(tmp_path)
    write_grade_item_membership_revision(root, membership(digest))
    select_grade_item_membership_revision(
        root,
        CLASS_ID,
        ITEM_ID,
        WORK,
        1,
        expected_current_membership_revision=None,
    )
    pointer = grade_item_membership_current_path(root, CLASS_ID, ITEM_ID, WORK)
    data = json.loads(pointer.read_text(encoding="utf-8"))
    data["decision_sha256"] = "0" * 64
    pointer.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(GradeItemMembershipStorageIntegrityError):
        load_current_grade_item_membership_decision(root, CLASS_ID, ITEM_ID, WORK)


def test_work_relationship_listing_and_selected_included_query_are_deterministic(
    tmp_path: Path,
) -> None:
    root, digest = prepared(tmp_path)
    write_grade_item_membership_revision(root, membership(digest, work=WORK))
    write_grade_item_membership_revision(
        root, membership(digest, work=OTHER_WORK, disposition="excluded")
    )
    select_grade_item_membership_revision(
        root,
        CLASS_ID,
        ITEM_ID,
        WORK,
        1,
        expected_current_membership_revision=None,
    )
    select_grade_item_membership_revision(
        root,
        CLASS_ID,
        ITEM_ID,
        OTHER_WORK,
        1,
        expected_current_membership_revision=None,
    )
    assert list_grade_item_membership_work_refs(root, CLASS_ID, ITEM_ID) == (
        OTHER_WORK,
        WORK,
    )
    included = list_selected_included_grade_item_memberships(root, CLASS_ID, ITEM_ID)
    assert tuple(item.decision.work_reference.work for item in included) == (WORK,)


def test_no_decision_is_distinct_from_explicit_excluded(tmp_path: Path) -> None:
    root, digest = prepared(tmp_path)
    assert load_current_grade_item_membership_decision(
        root, CLASS_ID, ITEM_ID, WORK
    ) is None
    write_grade_item_membership_revision(
        root, membership(digest, disposition="excluded")
    )
    assert load_current_grade_item_membership_decision(
        root, CLASS_ID, ITEM_ID, WORK
    ) is None
    select_grade_item_membership_revision(
        root,
        CLASS_ID,
        ITEM_ID,
        WORK,
        1,
        expected_current_membership_revision=None,
    )
    current = load_current_grade_item_membership_decision(
        root, CLASS_ID, ITEM_ID, WORK
    )
    assert current is not None
    assert current.decision.decision == "excluded"


def test_same_work_can_participate_in_different_grade_items(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    digest1 = write_grade_item(root)
    digest2 = write_grade_item(root, grade_item_id="other_item")
    write_grade_item_membership_revision(root, membership(digest1))
    write_grade_item_membership_revision(
        root, membership(digest2, grade_item_id="other_item")
    )
    assert list_grade_item_membership_work_refs(root, CLASS_ID, ITEM_ID) == (WORK,)
    assert list_grade_item_membership_work_refs(
        root, CLASS_ID, "other_item"
    ) == (WORK,)


def test_membership_subtree_does_not_break_grade_item_history_or_selection(
    tmp_path: Path,
) -> None:
    root, digest = prepared(tmp_path)
    write_grade_item_membership_revision(root, membership(digest))
    assert list_grade_item_revisions(root, CLASS_ID, ITEM_ID) == (1,)
    selected = select_grade_item_revision(
        root,
        CLASS_ID,
        ITEM_ID,
        1,
        expected_current_revision=None,
    )
    assert selected.stored.revision.grade_item_id == ITEM_ID


def test_unexpected_visible_entry_and_lock_conflict_fail_closed(tmp_path: Path) -> None:
    root, digest = prepared(tmp_path)
    write_grade_item_membership_revision(root, membership(digest))
    relation = grade_item_membership_directory(root, CLASS_ID, ITEM_ID, WORK)
    extra = relation / "latest.json"
    extra.write_text("{}\n", encoding="utf-8")
    with pytest.raises(GradeItemMembershipStorageIntegrityError, match="unexpected"):
        list_grade_item_membership_revisions(root, CLASS_ID, ITEM_ID, WORK)
    extra.unlink()

    lock = relation / ".write.lock"
    lock.write_bytes(b"held\n")
    with pytest.raises(GradeItemMembershipStorageLockError):
        write_grade_item_membership_revision(
            root, membership(digest, revision=2, disposition="excluded")
        )


def test_oversized_revision_read_is_rejected(tmp_path: Path) -> None:
    root, digest = prepared(tmp_path)
    write_grade_item_membership_revision(root, membership(digest))
    with pytest.raises(GradeItemMembershipStorageTooLargeError):
        load_grade_item_membership_revision(
            root,
            CLASS_ID,
            ITEM_ID,
            WORK,
            1,
            maximum_revision_bytes=1,
        )


def test_symlinked_membership_component_is_rejected_when_supported(
    tmp_path: Path,
) -> None:
    root, digest = prepared(tmp_path)
    write_grade_item_membership_revision(root, membership(digest))
    relation = grade_item_membership_directory(root, CLASS_ID, ITEM_ID, WORK)
    revisions = relation / "revisions"
    moved = relation / "real_revisions"
    revisions.rename(moved)
    try:
        os.symlink(moved, revisions, target_is_directory=True)
    except (OSError, NotImplementedError):
        moved.rename(revisions)
        pytest.skip("symlink creation is not permitted on this platform")
    with pytest.raises(GradeItemMembershipStorageIntegrityError):
        list_grade_item_membership_revisions(root, CLASS_ID, ITEM_ID, WORK)


def test_membership_pointer_record_type_is_stable() -> None:
    assert GRADE_ITEM_MEMBERSHIP_CURRENT_RECORD_TYPE == (
        "meridian_grade_item_membership_current"
    )
