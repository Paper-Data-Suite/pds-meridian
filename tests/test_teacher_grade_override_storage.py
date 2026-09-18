from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.grade_policy import GradePolicyActor
from meridian.hybrid_grade_result import HybridGradeResultReference
from meridian.standards_grade_result import StandardsGradeResultReference
from meridian.teacher_grade_override import (
    TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
    TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideDecision,
    TeacherGradeOverrideReference,
    teacher_grade_override_decision_to_json_bytes,
    teacher_grade_override_reference,
)
from meridian.teacher_grade_override_storage import (
    TeacherGradeOverrideStorageConflictError,
    TeacherGradeOverrideStorageIntegrityError,
    TeacherGradeOverrideStorageLockError,
    get_current_teacher_grade_override_reference,
    list_teacher_grade_override_revisions,
    load_current_teacher_grade_override,
    load_teacher_grade_override_revision,
    select_teacher_grade_override_revision,
    teacher_grade_override_current_path,
    teacher_grade_override_family_directory,
    teacher_grade_override_revision_digest_path,
    teacher_grade_override_revision_path,
    teacher_grade_override_revision_relative_path,
    teacher_grade_override_subject_key,
    write_teacher_grade_override_revision,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "student_001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 17, 21, 0, tzinfo=UTC)


def make_workspace(tmp_path: Path) -> Path:
    class_root = tmp_path / "classes" / CLASS_ID
    class_root.mkdir(parents=True)
    (class_root / "roster.csv").write_text(
        "class_id,student_id,last_name,first_name,period\n"
        "synthetic_class_2026,student_001,Synthetic,Student,1\n",
        encoding="utf-8",
    )
    return tmp_path


def source_reference(
    family: str = "conventional",
    *,
    result_revision: int = 1,
    digest: str = "a" * 64,
    calendar_revision: int = 1,
) -> GradeOverrideSourceResultReference:
    kwargs = {
        "class_id": CLASS_ID,
        "student_id": STUDENT_ID,
        "school_year": PERIOD.school_year,
        "period_id": PERIOD.period_id,
        "calendar_revision": calendar_revision,
        "result_revision": result_revision,
        "result_sha256": digest,
    }
    if family == "conventional":
        reference = ConventionalGradeResultReference(**kwargs)
    elif family == "standards_based":
        reference = StandardsGradeResultReference(**kwargs)
    elif family == "hybrid":
        reference = HybridGradeResultReference(**kwargs)
    else:
        raise AssertionError("unsupported test family")
    return GradeOverrideSourceResultReference(
        family,  # type: ignore[arg-type]
        reference,
    )


def override_decision(
    revision: int = 1,
    *,
    family: str = "conventional",
    source: GradeOverrideSourceResultReference | None = None,
    replacement: Decimal = Decimal("87.5"),
    calendar_revision: int = 1,
    rationale: str | None = None,
) -> TeacherGradeOverrideDecision:
    if source is None:
        source = source_reference(
            family,
            calendar_revision=calendar_revision,
        )
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=calendar_revision,
        calculation_family=family,  # type: ignore[arg-type]
        override_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision="override",
        source_result=source,
        replacement_grade=replacement,
        withdrawn_override_reference=None,
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=rationale or f"Teacher final Grade decision r{revision}.",
        decided_at=NOW + timedelta(minutes=revision - 1),
    )


def withdrawal(
    active: TeacherGradeOverrideDecision,
    *,
    revision: int = 2,
    source: GradeOverrideSourceResultReference | None = None,
    withdrawn_reference: TeacherGradeOverrideReference | None = None,
) -> TeacherGradeOverrideDecision:
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=active.class_id,
        student_id=active.student_id,
        target_period=active.target_period,
        calendar_revision=active.calendar_revision,
        calculation_family=active.calculation_family,
        override_revision=revision,
        supersedes_revision=revision - 1,
        decision="withdraw",
        source_result=source or active.source_result,
        replacement_grade=None,
        withdrawn_override_reference=(
            withdrawn_reference or teacher_grade_override_reference(active)
        ),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=f"Teacher withdrawal r{revision}.",
        decided_at=NOW + timedelta(minutes=revision - 1),
    )


def _canonical_json(data: object) -> bytes:
    return (
        json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")


@pytest.mark.parametrize("family", ["conventional", "standards_based", "hybrid"])
def test_write_uses_privacy_minimized_family_scoped_path(
    tmp_path: Path,
    family: str,
) -> None:
    root = make_workspace(tmp_path)
    value = override_decision(family=family)
    result = write_teacher_grade_override_revision(root, value)
    subject_key = teacher_grade_override_subject_key(
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        value.calculation_family,
    )

    assert result.disposition == "created"
    assert result.stored.relative_path == (
        "classes/synthetic_class_2026/modules/meridian/grade_overrides/"
        f"periods/2026-2027/mp1/students/{subject_key}/{family}/"
        "revisions/1.json"
    )
    assert STUDENT_ID not in result.stored.relative_path
    assert get_current_teacher_grade_override_reference(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, value.calculation_family
    ) is None


def test_subject_key_covers_calendar_and_calculation_family() -> None:
    conventional = teacher_grade_override_subject_key(
        CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
    )
    later_calendar = teacher_grade_override_subject_key(
        CLASS_ID, STUDENT_ID, PERIOD, 2, "conventional"
    )
    hybrid = teacher_grade_override_subject_key(
        CLASS_ID, STUDENT_ID, PERIOD, 1, "hybrid"
    )

    assert conventional != later_calendar
    assert conventional != hybrid
    assert len(conventional) == 64


def test_exact_retry_is_idempotent_and_collision_conflicts(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    value = override_decision()
    first = write_teacher_grade_override_revision(root, value)
    second = write_teacher_grade_override_revision(root, value)

    assert second.disposition == "existing"
    assert first.stored.override_sha256 == second.stored.override_sha256

    changed = replace(value, rationale="Different teacher rationale.")
    with pytest.raises(TeacherGradeOverrideStorageConflictError):
        write_teacher_grade_override_revision(root, changed)


def test_history_is_contiguous_and_immutable(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    first = override_decision()
    first_content = write_teacher_grade_override_revision(root, first).stored.content
    second = override_decision(2, replacement=Decimal("91"))
    write_teacher_grade_override_revision(root, second)

    assert list_teacher_grade_override_revisions(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
    ) == (1, 2)
    assert load_teacher_grade_override_revision(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional", 1
    ).content == first_content

    with pytest.raises(TeacherGradeOverrideStorageConflictError):
        write_teacher_grade_override_revision(root, override_decision(4))


def test_write_never_changes_current_selection(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    first = write_teacher_grade_override_revision(root, override_decision()).stored
    select_teacher_grade_override_revision(
        root, first.reference, expected_current=None
    )
    write_teacher_grade_override_revision(
        root, override_decision(2, replacement=Decimal("90"))
    )

    assert get_current_teacher_grade_override_reference(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
    ) == first.reference


def test_selection_is_digest_bound_cas_and_exact_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    first = write_teacher_grade_override_revision(root, override_decision()).stored
    second = write_teacher_grade_override_revision(
        root, override_decision(2, replacement=Decimal("90"))
    ).stored

    selected1 = select_teacher_grade_override_revision(
        root, first.reference, expected_current=None
    )
    assert selected1.disposition == "created"

    selected2 = select_teacher_grade_override_revision(
        root, second.reference, expected_current=first.reference
    )
    assert selected2.disposition == "updated"
    assert load_current_teacher_grade_override(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
    ) == second

    retry = select_teacher_grade_override_revision(
        root, second.reference, expected_current=None
    )
    assert retry.disposition == "existing"

    with pytest.raises(TeacherGradeOverrideStorageConflictError):
        select_teacher_grade_override_revision(
            root, first.reference, expected_current=None
        )


def test_low_level_selection_can_reselect_exact_history_with_valid_cas(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    first = write_teacher_grade_override_revision(root, override_decision()).stored
    second = write_teacher_grade_override_revision(
        root, override_decision(2, replacement=Decimal("90"))
    ).stored
    select_teacher_grade_override_revision(root, first.reference, expected_current=None)
    select_teacher_grade_override_revision(
        root, second.reference, expected_current=first.reference
    )

    back = select_teacher_grade_override_revision(
        root, first.reference, expected_current=second.reference
    )
    assert back.disposition == "updated"
    assert get_current_teacher_grade_override_reference(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
    ) == first.reference


def test_selection_rejects_wrong_digest_even_when_revision_exists(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    stored = write_teacher_grade_override_revision(root, override_decision()).stored
    bad = replace(stored.reference, override_sha256="0" * 64)

    with pytest.raises(TeacherGradeOverrideStorageConflictError):
        select_teacher_grade_override_revision(root, bad, expected_current=None)


def test_expected_current_must_be_same_logical_family(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored = write_teacher_grade_override_revision(root, override_decision()).stored
    other = replace(stored.reference, calculation_family="hybrid")

    with pytest.raises(ValueError, match="same override family"):
        select_teacher_grade_override_revision(
            root, stored.reference, expected_current=other
        )


def test_withdrawal_requires_exact_stored_override_reference(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    active = override_decision()
    stored = write_teacher_grade_override_revision(root, active).stored
    value = withdrawal(active, withdrawn_reference=stored.reference)

    result = write_teacher_grade_override_revision(root, value)
    assert result.stored.decision.decision == "withdraw"
    assert result.stored.decision.withdrawn_override_reference == stored.reference


def test_withdrawal_rejects_wrong_digest_or_source(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    active = override_decision()
    stored = write_teacher_grade_override_revision(root, active).stored

    wrong_digest = replace(stored.reference, override_sha256="b" * 64)
    with pytest.raises(TeacherGradeOverrideStorageConflictError):
        write_teacher_grade_override_revision(
            root, withdrawal(active, withdrawn_reference=wrong_digest)
        )

    changed_source = source_reference(digest="c" * 64)
    with pytest.raises(TeacherGradeOverrideStorageConflictError):
        write_teacher_grade_override_revision(
            root,
            withdrawal(
                active,
                source=changed_source,
                withdrawn_reference=stored.reference,
            ),
        )


def test_withdrawal_cannot_reference_another_withdrawal(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    active = override_decision()
    first = write_teacher_grade_override_revision(root, active).stored
    withdrawn = withdrawal(active, withdrawn_reference=first.reference)
    second = write_teacher_grade_override_revision(root, withdrawn).stored

    third = withdrawal(
        withdrawn,
        revision=3,
        withdrawn_reference=second.reference,
    )
    with pytest.raises(
        TeacherGradeOverrideStorageConflictError,
        match="not another withdrawal",
    ):
        write_teacher_grade_override_revision(root, third)


def test_digest_sidecar_and_canonical_bytes_are_exact(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    value = override_decision()
    stored = write_teacher_grade_override_revision(root, value).stored
    path = teacher_grade_override_revision_path(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional", 1
    )
    digest_path = teacher_grade_override_revision_digest_path(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional", 1
    )

    assert path.read_bytes() == teacher_grade_override_decision_to_json_bytes(value)
    assert digest_path.read_text(encoding="ascii") == stored.override_sha256 + "\n"


def test_missing_digest_sidecar_fails_closed(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_teacher_grade_override_revision(root, override_decision())
    digest = teacher_grade_override_revision_digest_path(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional", 1
    )
    digest.unlink()

    with pytest.raises(TeacherGradeOverrideStorageIntegrityError, match="incomplete"):
        load_teacher_grade_override_revision(
            root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional", 1
        )


def test_tampered_revision_content_fails_closed(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_teacher_grade_override_revision(root, override_decision())
    path = teacher_grade_override_revision_path(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional", 1
    )
    path.write_bytes(path.read_bytes().replace(b"87.5", b"99.5", 1))

    with pytest.raises(TeacherGradeOverrideStorageIntegrityError, match="digest"):
        load_teacher_grade_override_revision(
            root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional", 1
        )


def test_tampered_current_pointer_digest_fails_closed(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored = write_teacher_grade_override_revision(root, override_decision()).stored
    select_teacher_grade_override_revision(
        root, stored.reference, expected_current=None
    )
    pointer = teacher_grade_override_current_path(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
    )
    data = json.loads(pointer.read_text(encoding="utf-8"))
    data["override_sha256"] = "0" * 64
    pointer.write_bytes(_canonical_json(data))

    with pytest.raises(TeacherGradeOverrideStorageIntegrityError, match="digest"):
        load_current_teacher_grade_override(
            root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
        )


def test_current_pointer_unknown_field_fails_closed(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    stored = write_teacher_grade_override_revision(root, override_decision()).stored
    select_teacher_grade_override_revision(
        root, stored.reference, expected_current=None
    )
    pointer = teacher_grade_override_current_path(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
    )
    data = json.loads(pointer.read_text(encoding="utf-8"))
    data["unexpected"] = True
    pointer.write_bytes(_canonical_json(data))

    with pytest.raises(TeacherGradeOverrideStorageIntegrityError, match="exact schema"):
        get_current_teacher_grade_override_reference(
            root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
        )


def test_unexpected_revision_entry_fails_closed(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_teacher_grade_override_revision(root, override_decision())
    family = teacher_grade_override_family_directory(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
    )
    (family / "revisions" / "notes.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(TeacherGradeOverrideStorageIntegrityError, match="Unexpected"):
        list_teacher_grade_override_revisions(
            root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
        )


def test_existing_lock_blocks_writer(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    family = teacher_grade_override_family_directory(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
    )
    (family / "revisions").mkdir(parents=True)
    (family / ".write.lock").write_text("held\n", encoding="ascii")

    with pytest.raises(TeacherGradeOverrideStorageLockError):
        write_teacher_grade_override_revision(root, override_decision())


def test_restart_reload_preserves_history_and_selection(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    first = write_teacher_grade_override_revision(root, override_decision()).stored
    second = write_teacher_grade_override_revision(
        root, override_decision(2, replacement=Decimal("92"))
    ).stored
    select_teacher_grade_override_revision(root, first.reference, expected_current=None)
    select_teacher_grade_override_revision(
        root, second.reference, expected_current=first.reference
    )

    assert list_teacher_grade_override_revisions(
        Path(str(root)), CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
    ) == (1, 2)
    reloaded = load_current_teacher_grade_override(
        Path(str(root)), CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
    )
    assert reloaded is not None
    assert reloaded.reference == second.reference
    assert reloaded.content == second.content


def test_family_histories_are_independent(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    conventional = write_teacher_grade_override_revision(
        root, override_decision(family="conventional")
    ).stored
    hybrid = write_teacher_grade_override_revision(
        root, override_decision(family="hybrid")
    ).stored

    assert conventional.path != hybrid.path
    assert list_teacher_grade_override_revisions(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional"
    ) == (1,)
    assert list_teacher_grade_override_revisions(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "hybrid"
    ) == (1,)


def test_relative_path_never_contains_raw_student_identifier() -> None:
    value = teacher_grade_override_revision_relative_path(
        CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional", 1
    )
    assert STUDENT_ID not in value
    assert "/students/" in value


def test_symlinked_revision_is_rejected_when_supported(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    write_teacher_grade_override_revision(root, override_decision())
    path = teacher_grade_override_revision_path(
        root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional", 1
    )
    original = path.with_name("original.json")
    path.rename(original)
    try:
        os.symlink(original.name, path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable in this environment")

    with pytest.raises(TeacherGradeOverrideStorageIntegrityError, match="Symbolic"):
        load_teacher_grade_override_revision(
            root, CLASS_ID, STUDENT_ID, PERIOD, 1, "conventional", 1
        )
