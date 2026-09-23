from __future__ import annotations

import hashlib
import json
import os
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from meridian.export_profile import (
    EXPORT_PROFILE_RECORD_TYPE,
    EXPORT_PROFILE_SCHEMA_VERSION,
    EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
    ExportColumn,
    ExportProfileActor,
    ExportProfileReference,
    ExportProfileRevision,
    ExportRepresentation,
)
from meridian.export_profile_storage import (
    EXPORT_PROFILE_SELECTION_RECORD_TYPE,
    EXPORT_PROFILE_SELECTION_SCHEMA_VERSION,
    ExportProfileCurrentSelection,
    ExportProfileSelectionConflictError,
    ExportProfileSelectionReference,
    ExportProfileStorageConflictError,
    ExportProfileStorageIntegrityError,
    ExportProfileStorageNotFoundError,
    ExportProfileStorageTooLargeError,
    ExportProfileStorageValidationError,
    export_profile_current_path,
    export_profile_revision_relative_path,
    export_profile_selection_from_json_bytes,
    export_profile_selection_relative_path,
    export_profile_selection_sha256,
    export_profile_selection_to_json_bytes,
    get_current_export_profile_selection_reference,
    list_export_profile_ids,
    list_export_profile_revisions,
    load_current_export_profile,
    load_current_export_profile_selection,
    load_export_profile_reference,
    load_export_profile_revision,
    select_export_profile,
    write_export_profile_revision,
)

CLASS_ID = "english_12"
NOW = datetime(2026, 9, 21, 22, 0, tzinfo=UTC)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "classes" / CLASS_ID).mkdir(parents=True)
    return root


def _columns(revision: int = 1) -> tuple[ExportColumn, ...]:
    base = (
        ExportColumn("target.student_id", "Student ID"),
        ExportColumn("grade.effective_grade", "Grade"),
    )
    if revision == 1:
        return base
    return (
        ExportColumn("target.student_id", "Student ID"),
        ExportColumn("roster.last_name", "Last Name"),
        ExportColumn("roster.first_name", "First Name"),
        ExportColumn("grade.effective_grade", "Grade"),
    )


def _profile(
    revision: int = 1,
    *,
    profile_id: str = "district_gradebook",
) -> ExportProfileRevision:
    return ExportProfileRevision(
        schema_version=EXPORT_PROFILE_SCHEMA_VERSION,
        record_type=EXPORT_PROFILE_RECORD_TYPE,
        source_registry_version=EXPORT_SOURCE_FIELD_REGISTRY_VERSION,
        class_id=CLASS_ID,
        profile_id=profile_id,
        profile_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        title=f"District Gradebook {revision}",
        purpose="Teacher-controlled Grade transfer",
        columns=_columns(revision),
        representation=ExportRepresentation("csv", True, "crlf", True),
        actor=ExportProfileActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW + timedelta(minutes=revision - 1),
    )


def _write_two(root: Path):
    first = write_export_profile_revision(root, _profile()).stored
    second = write_export_profile_revision(root, _profile(2)).stored
    return first, second


def _select(root: Path, stored, expected, minute: int):
    return select_export_profile(
        root,
        stored.reference,
        actor=ExportProfileActor("teacher", "teacher_local"),
        rationale="Use this import layout.",
        decided_at=NOW + timedelta(minutes=minute),
        expected_current=expected,
    )


def test_write_first_revision_is_create_only_and_does_not_select(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    result = write_export_profile_revision(root, _profile())

    assert result.disposition == "created"
    assert result.stored.profile == _profile()
    assert result.stored.reference.profile_sha256 == hashlib.sha256(
        result.stored.content
    ).hexdigest()
    assert get_current_export_profile_selection_reference(
        root, CLASS_ID, "district_gradebook"
    ) is None
    assert not export_profile_current_path(
        root, CLASS_ID, "district_gradebook"
    ).exists()


def test_write_exact_replay_is_idempotent(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    first = write_export_profile_revision(root, _profile())
    second = write_export_profile_revision(root, _profile())

    assert second.disposition == "existing"
    assert second.stored == first.stored


def test_same_immutable_identity_with_different_content_conflicts(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    write_export_profile_revision(root, _profile())

    with pytest.raises(ExportProfileStorageConflictError, match="different content"):
        write_export_profile_revision(
            root,
            replace(_profile(), title="Different bytes"),
        )


def test_successor_requires_exact_previous_revision(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    with pytest.raises(ExportProfileStorageConflictError, match="Previous"):
        write_export_profile_revision(root, _profile(2))


def test_linear_successor_persists_and_lists_in_numeric_order(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    first, second = _write_two(root)

    assert first.profile.profile_revision == 1
    assert second.profile.profile_revision == 2
    assert list_export_profile_revisions(
        root, CLASS_ID, "district_gradebook"
    ) == (1, 2)


def test_revision_path_is_class_local_and_privacy_safe(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored

    assert stored.relative_path == (
        "classes/english_12/modules/meridian/export_profiles/"
        "district_gradebook/revisions/1.json"
    )
    assert stored.relative_path == export_profile_revision_relative_path(
        CLASS_ID, "district_gradebook", 1
    )
    assert "student" not in stored.relative_path.lower()


def test_load_reference_requires_exact_digest(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored

    assert load_export_profile_reference(root, stored.reference) == stored
    bad = ExportProfileReference(
        CLASS_ID,
        "district_gradebook",
        1,
        "f" * 64,
    )
    with pytest.raises(ExportProfileStorageIntegrityError, match="digest"):
        load_export_profile_reference(root, bad)


def test_missing_core_class_blocks_profile_creation(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(ExportProfileStorageNotFoundError, match="Core class"):
        write_export_profile_revision(root, _profile())


def test_corrupt_revision_digest_sidecar_fails_closed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored
    digest_path = Path(str(stored.path) + ".sha256")
    digest_path.write_bytes(("f" * 64 + "\n").encode("ascii"))

    with pytest.raises(ExportProfileStorageIntegrityError, match="digest"):
        load_export_profile_revision(root, CLASS_ID, "district_gradebook", 1)


def test_noncanonical_revision_bytes_fail_closed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored
    data = json.loads(stored.content)
    alternate = json.dumps(data, sort_keys=True).encode("utf-8")
    stored.path.write_bytes(alternate)
    Path(str(stored.path) + ".sha256").write_bytes(
        (hashlib.sha256(alternate).hexdigest() + "\n").encode("ascii")
    )

    with pytest.raises(ExportProfileStorageIntegrityError, match="invalid"):
        load_export_profile_revision(root, CLASS_ID, "district_gradebook", 1)


def test_oversized_revision_read_is_rejected(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    write_export_profile_revision(root, _profile())

    with pytest.raises(ExportProfileStorageTooLargeError):
        load_export_profile_revision(
            root,
            CLASS_ID,
            "district_gradebook",
            1,
            maximum_bytes=8,
        )


def test_unexpected_family_entry_fails_closed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored
    (stored.path.parent.parent / "surprise.txt").write_text("x", encoding="utf-8")

    with pytest.raises(ExportProfileStorageIntegrityError, match="unexpected entry"):
        load_export_profile_revision(root, CLASS_ID, "district_gradebook", 1)


def test_revision_symlink_is_rejected_when_supported(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored
    outside = tmp_path / "outside.json"
    outside.write_bytes(stored.content)
    stored.path.unlink()
    try:
        os.symlink(outside, stored.path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")

    with pytest.raises(ExportProfileStorageIntegrityError, match="symlink"):
        load_export_profile_revision(root, CLASS_ID, "district_gradebook", 1)


def test_no_current_profile_before_explicit_selection(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    write_export_profile_revision(root, _profile())

    assert load_current_export_profile_selection(
        root, CLASS_ID, "district_gradebook"
    ) is None
    assert load_current_export_profile(root, CLASS_ID, "district_gradebook") is None


def test_first_selection_is_digest_bound_and_canonical(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored
    result = _select(root, stored, None, 5)

    assert result.disposition == "created"
    assert result.selection.selection.selection_revision == 1
    assert result.selection.selection.previous_selection is None
    assert result.selection.selection.profile_reference == stored.reference
    assert result.selection.reference.selection_sha256 == (
        export_profile_selection_sha256(result.selection.selection)
    )
    assert export_profile_selection_from_json_bytes(result.selection.content) == (
        result.selection.selection
    )


def test_selector_is_frozen_and_uses_expected_record_identity(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored
    result = _select(root, stored, None, 5)
    selection = result.selection.selection

    assert selection.schema_version == EXPORT_PROFILE_SELECTION_SCHEMA_VERSION
    assert selection.record_type == EXPORT_PROFILE_SELECTION_RECORD_TYPE
    with pytest.raises(FrozenInstanceError):
        selection.profile_id = "changed"  # type: ignore[misc]


def test_selector_path_is_family_local_and_contains_no_student_identity(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored
    result = _select(root, stored, None, 5)

    assert result.selection.relative_path == (
        "classes/english_12/modules/meridian/export_profiles/"
        "district_gradebook/current.json"
    )
    assert result.selection.relative_path == export_profile_selection_relative_path(
        CLASS_ID, "district_gradebook"
    )


def test_select_new_revision_updates_selector_and_binds_prior_state(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    first_profile, second_profile = _write_two(root)
    first = _select(root, first_profile, None, 5)
    second = _select(root, second_profile, first.selection.reference, 10)

    assert second.disposition == "updated"
    assert second.selection.selection.selection_revision == 2
    assert second.selection.selection.previous_selection == first.selection.reference
    assert second.selection.selection.profile_reference == second_profile.reference


def test_reselect_older_historical_revision_is_intentional_and_supported(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    first_profile, second_profile = _write_two(root)
    first = _select(root, first_profile, None, 5)
    second = _select(root, second_profile, first.selection.reference, 10)
    third = _select(root, first_profile, second.selection.reference, 15)

    assert third.disposition == "updated"
    assert third.selection.selection.selection_revision == 3
    assert third.selection.selection.profile_reference == first_profile.reference


def test_reselect_same_exact_revision_is_idempotent(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored
    first = _select(root, stored, None, 5)
    second = _select(root, stored, first.selection.reference, 10)

    assert second.disposition == "existing"
    assert second.selection == first.selection
    assert second.selection.selection.selection_revision == 1


def test_stale_expected_selector_fails_compare_and_swap(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    first_profile, second_profile = _write_two(root)
    first = _select(root, first_profile, None, 5)
    _select(root, second_profile, first.selection.reference, 10)

    with pytest.raises(ExportProfileSelectionConflictError, match="changed"):
        _select(root, first_profile, first.selection.reference, 15)


def test_expected_none_fails_after_selector_exists(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    first_profile, second_profile = _write_two(root)
    _select(root, first_profile, None, 5)

    with pytest.raises(ExportProfileSelectionConflictError):
        _select(root, second_profile, None, 10)


def test_selection_cannot_predate_selected_profile_revision(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored

    with pytest.raises(ExportProfileStorageValidationError, match="earlier"):
        select_export_profile(
            root,
            stored.reference,
            actor=ExportProfileActor("teacher", "teacher_local"),
            rationale=None,
            decided_at=NOW - timedelta(seconds=1),
            expected_current=None,
        )


def test_current_loader_returns_exact_selected_profile(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    first_profile, second_profile = _write_two(root)
    first = _select(root, first_profile, None, 5)
    _select(root, second_profile, first.selection.reference, 10)

    current = load_current_export_profile(root, CLASS_ID, "district_gradebook")
    assert current is not None
    assert current.reference == second_profile.reference


def test_selector_digest_changes_for_material_selection_change(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    first_profile, second_profile = _write_two(root)
    first = _select(root, first_profile, None, 5)
    second = _select(root, second_profile, first.selection.reference, 10)

    assert first.selection.selection_sha256 != second.selection.selection_sha256
    assert first.selection.reference != second.selection.reference


def test_selector_model_rejects_broken_prior_chain(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored
    first = _select(root, stored, None, 5)

    with pytest.raises(ExportProfileStorageValidationError, match="immediately"):
        ExportProfileCurrentSelection(
            schema_version=EXPORT_PROFILE_SELECTION_SCHEMA_VERSION,
            record_type=EXPORT_PROFILE_SELECTION_RECORD_TYPE,
            class_id=CLASS_ID,
            profile_id="district_gradebook",
            selection_revision=3,
            profile_reference=stored.reference,
            actor=ExportProfileActor("teacher", "teacher_local"),
            rationale=None,
            decided_at=NOW + timedelta(minutes=10),
            previous_selection=first.selection.reference,
        )


def test_selector_json_rejects_unknown_duplicate_and_noncanonical_bytes(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored
    result = _select(root, stored, None, 5)
    path = result.selection.path
    data = json.loads(result.selection.content)

    unknown = dict(data)
    unknown["is_current"] = True
    unknown_bytes = (
        json.dumps(
            unknown,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(unknown_bytes)
    with pytest.raises(ExportProfileStorageValidationError, match="exact schema"):
        load_current_export_profile_selection(root, CLASS_ID, "district_gradebook")

    path.write_bytes(result.selection.content)
    noncanonical = json.dumps(data, sort_keys=True).encode("utf-8")
    path.write_bytes(noncanonical)
    with pytest.raises(ExportProfileStorageIntegrityError, match="canonical"):
        load_current_export_profile_selection(root, CLASS_ID, "district_gradebook")

    duplicate = result.selection.content.decode("utf-8").replace(
        '  "class_id": "english_12",',
        '  "class_id": "english_12",\n  "class_id": "english_12",',
        1,
    ).encode("utf-8")
    path.write_bytes(duplicate)
    with pytest.raises(ExportProfileStorageIntegrityError, match="duplicate"):
        load_current_export_profile_selection(root, CLASS_ID, "district_gradebook")


def test_tampered_selected_profile_digest_fails_closed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored
    result = _select(root, stored, None, 5)
    path = result.selection.path
    data = json.loads(result.selection.content)
    data["profile_reference"]["profile_sha256"] = "f" * 64
    tampered = (
        json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(tampered)

    with pytest.raises(ExportProfileStorageIntegrityError, match="Selected"):
        load_current_export_profile_selection(root, CLASS_ID, "district_gradebook")


def test_selector_symlink_is_rejected_when_supported(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    stored = write_export_profile_revision(root, _profile()).stored
    result = _select(root, stored, None, 5)
    outside = tmp_path / "outside-current.json"
    outside.write_bytes(result.selection.content)
    result.selection.path.unlink()
    try:
        os.symlink(outside, result.selection.path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")

    with pytest.raises(ExportProfileStorageIntegrityError, match="regular file"):
        load_current_export_profile_selection(root, CLASS_ID, "district_gradebook")


def test_selection_reference_requires_exact_digest_and_safe_family_identity() -> None:
    ref = ExportProfileSelectionReference(
        CLASS_ID,
        "district_gradebook",
        1,
        "a" * 64,
    )
    assert ref.selection_revision == 1

    with pytest.raises(ExportProfileStorageValidationError):
        replace(ref, selection_sha256="A" * 64)
    with pytest.raises(ExportProfileStorageValidationError):
        replace(ref, profile_id="../escape")


def test_write_and_selection_change_only_export_profile_owned_state(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    marker = root / "classes" / CLASS_ID / "upstream-marker.bin"
    marker.write_bytes(b"unchanged")

    first, second = _write_two(root)
    selected = _select(root, first, None, 5)
    _select(root, second, selected.selection.reference, 10)

    assert marker.read_bytes() == b"unchanged"
    assert export_profile_selection_to_json_bytes(
        load_current_export_profile_selection(
            root, CLASS_ID, "district_gradebook"
        ).selection  # type: ignore[union-attr]
    )

def test_list_profile_ids_is_sorted_and_verifies_each_family(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    write_export_profile_revision(root, _profile(profile_id="zeta_profile"))
    write_export_profile_revision(root, _profile(profile_id="alpha_profile"))

    assert list_export_profile_ids(root, CLASS_ID) == (
        "alpha_profile",
        "zeta_profile",
    )


def test_list_profile_ids_fails_closed_on_unexpected_collection_entry(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    write_export_profile_revision(root, _profile())
    collection = (
        root / "classes" / CLASS_ID / "modules" / "meridian" / "export_profiles"
    )
    (collection / "unexpected.txt").write_text("bad", encoding="utf-8")

    with pytest.raises(
        ExportProfileStorageIntegrityError,
        match="non-directory",
    ):
        list_export_profile_ids(root, CLASS_ID)
