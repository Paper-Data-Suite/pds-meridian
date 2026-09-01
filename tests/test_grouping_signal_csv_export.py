from __future__ import annotations

from pathlib import Path

import pytest
from pds_core.grouping_signal_csv import (
    grouping_signal_csv_to_signal_set,
    parse_grouping_signal_csv,
)
from pds_core.grouping_signal_storage import load_grouping_signal
from pds_core.grouping_signals import grouping_signal_set_to_json_bytes

import meridian.grouping_signal_csv_export as csv_export
from meridian.grouping_signal_csv_export import (
    GroupingSignalCsvExportConflictError,
    GroupingSignalCsvExportWriteError,
    export_grouping_signal_csv,
)
from meridian.grouping_signal_export_receipt_workflow import (
    export_grouping_signal,
)
from tests.test_grouping_signal_export_eligibility import (
    CLASS_ID,
    NOW,
    _seed_selected_accepted_review,
)


def _seed_export(tmp_path: Path):
    root, _, stored_review = _seed_selected_accepted_review(tmp_path)
    derivation_id = stored_review.review.derivation_reference.derivation_id
    signal_set_id = "reading_mp1_csv_export"
    exported = export_grouping_signal(
        root,
        CLASS_ID,
        derivation_id,
        signal_set_id=signal_set_id,
        created_at=NOW,
    )
    return root, signal_set_id, exported


def test_csv_export_uses_exact_stored_core_complete_signal_round_trip(
    tmp_path: Path,
) -> None:
    root, signal_set_id, exported = _seed_export(tmp_path)
    destination = tmp_path / "planning-signal.csv"

    result = export_grouping_signal_csv(
        root,
        CLASS_ID,
        signal_set_id,
        destination,
    )

    assert result.disposition == "created"
    assert result.destination == destination.resolve()
    csv_bytes = destination.read_bytes()
    assert result.byte_length == len(csv_bytes)
    assert result.csv_sha256
    document = parse_grouping_signal_csv(csv_bytes)
    assert document.csv_contract == "grouping_signal_csv_v1"
    assert document.representation_scope == "complete_signal"
    assert document.signal_set_id == signal_set_id
    assert document.class_id == CLASS_ID
    assert document.source.module_id == "meridian"

    reconstructed = grouping_signal_csv_to_signal_set(document)
    stored = load_grouping_signal(root, CLASS_ID, signal_set_id)
    assert reconstructed == stored.signal
    assert (
        grouping_signal_set_to_json_bytes(reconstructed)
        == grouping_signal_set_to_json_bytes(stored.signal)
    )
    assert stored == exported.core.write_result.stored


def test_csv_contains_only_core_metadata_and_student_id_band_rows(
    tmp_path: Path,
) -> None:
    root, signal_set_id, _ = _seed_export(tmp_path)
    destination = tmp_path / "privacy.csv"

    export_grouping_signal_csv(
        root,
        CLASS_ID,
        signal_set_id,
        destination,
    )
    text = destination.read_text(encoding="utf-8")

    assert "student_id,band" in text
    for forbidden in (
        "display_name",
        "student_name",
        "proficiency_level_id",
        "scale_position",
        "standard_id",
        "percentage",
        "raw_score",
        "review_reference",
        "preview_reference",
    ):
        assert forbidden not in text


def test_exact_csv_retry_is_existing_and_different_destination_bytes_conflict(
    tmp_path: Path,
) -> None:
    root, signal_set_id, _ = _seed_export(tmp_path)
    destination = tmp_path / "retry.csv"

    first = export_grouping_signal_csv(
        root,
        CLASS_ID,
        signal_set_id,
        destination,
    )
    second = export_grouping_signal_csv(
        root,
        CLASS_ID,
        signal_set_id,
        destination,
    )

    assert first.disposition == "created"
    assert second.disposition == "existing"
    assert first.csv_sha256 == second.csv_sha256

    destination.write_text("teacher edited\n", encoding="utf-8")
    with pytest.raises(GroupingSignalCsvExportConflictError) as raised:
        export_grouping_signal_csv(
            root,
            CLASS_ID,
            signal_set_id,
            destination,
        )
    assert raised.value.code == "csv_destination_conflict"
    assert destination.read_text(encoding="utf-8") == "teacher edited\n"


def test_csv_export_rejects_directory_and_symlink_destination(
    tmp_path: Path,
) -> None:
    root, signal_set_id, _ = _seed_export(tmp_path)

    directory = tmp_path / "not-a-file"
    directory.mkdir()
    with pytest.raises(GroupingSignalCsvExportConflictError):
        export_grouping_signal_csv(
            root,
            CLASS_ID,
            signal_set_id,
            directory,
        )

    target = tmp_path / "target.csv"
    target.write_text("existing\n", encoding="utf-8")
    symlink = tmp_path / "link.csv"
    try:
        symlink.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation is unavailable on this platform.")

    with pytest.raises(GroupingSignalCsvExportConflictError):
        export_grouping_signal_csv(
            root,
            CLASS_ID,
            signal_set_id,
            symlink,
        )
    assert target.read_text(encoding="utf-8") == "existing\n"


def test_csv_write_failure_does_not_mutate_core_or_receipt_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, signal_set_id, exported = _seed_export(tmp_path)
    destination = tmp_path / "failure.csv"

    before_core = load_grouping_signal(root, CLASS_ID, signal_set_id)

    def fail_write(path: Path, content: bytes) -> None:
        raise OSError("synthetic CSV write failure")

    monkeypatch.setattr(csv_export, "_write_new_file", fail_write)

    with pytest.raises(GroupingSignalCsvExportWriteError) as raised:
        export_grouping_signal_csv(
            root,
            CLASS_ID,
            signal_set_id,
            destination,
        )

    assert raised.value.code == "csv_write_failed"
    assert not destination.exists()
    after_core = load_grouping_signal(root, CLASS_ID, signal_set_id)
    assert after_core == before_core == exported.core.write_result.stored
    assert exported.receipt.stored.path.exists()
