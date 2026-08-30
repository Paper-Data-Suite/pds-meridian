from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pds_core.classes import class_roster_path, write_class_roster
from pds_core.grouping_signal_diagnostics import diagnose_grouping_signal
from pds_core.grouping_signals import (
    GROUPING_SIGNAL_RECORD_TYPE,
    GROUPING_SIGNAL_SCHEMA_VERSION,
    GroupingSignalDimension,
    GroupingSignalSet,
    GroupingSignalSource,
    GroupingSignalStudentBand,
)
from pds_core.rosters import create_roster

_SOURCE_DIGEST = "2" * 64


def _write_roster(
    workspace: Path,
    class_id: str,
    student_ids: tuple[str, ...],
) -> None:
    roster = create_roster(
        class_id,
        [
            {
                "student_id": student_id,
                "last_name": f"Last{index}",
                "first_name": f"First{index}",
                "period": "1",
            }
            for index, student_id in enumerate(student_ids, start=1)
        ],
    )
    write_class_roster(workspace, roster)


def _signal(
    *,
    class_id: str = "synthetic_class_alpha",
    entries: tuple[tuple[str, str, int], ...],
    dimensions: tuple[tuple[str, int], ...] = (
        ("analysis", 4),
        ("composition", 3),
    ),
) -> GroupingSignalSet:
    return GroupingSignalSet(
        schema_version=GROUPING_SIGNAL_SCHEMA_VERSION,
        record_type=GROUPING_SIGNAL_RECORD_TYPE,
        signal_set_id="meridian_signal_diagnostics",
        class_id=class_id,
        created_at=datetime(2026, 9, 2, 14, 0, tzinfo=UTC),
        source=GroupingSignalSource(
            kind="module_generated",
            module_id="meridian",
            snapshot_id="meridian_diagnostic_source",
            snapshot_digest_algorithm="sha256",
            snapshot_digest=_SOURCE_DIGEST,
        ),
        dimensions=tuple(
            GroupingSignalDimension(
                dimension_id=dimension_id,
                band_count=band_count,
            )
            for dimension_id, band_count in dimensions
        ),
        student_bands=tuple(
            GroupingSignalStudentBand(
                student_id=student_id,
                dimension_id=dimension_id,
                band=band,
            )
            for student_id, dimension_id, band in entries
        ),
    )


def test_core_diagnostics_clean_exact_roster_and_dimension_counts(
    tmp_path: Path,
) -> None:
    _write_roster(
        tmp_path,
        "synthetic_class_alpha",
        ("student_001", "student_002", "student_003"),
    )
    signal = _signal(
        entries=(
            ("student_001", "analysis", 1),
            ("student_002", "analysis", 2),
            ("student_003", "analysis", 4),
            ("student_001", "composition", 2),
            ("student_002", "composition", 2),
            ("student_003", "composition", 3),
        )
    )

    report = diagnose_grouping_signal(tmp_path, signal)

    assert report.is_clean
    assert not report.has_errors
    assert not report.has_warnings
    assert report.signal_set_id == signal.signal_set_id
    assert report.signal_class_id == "synthetic_class_alpha"
    assert report.target_class_id == "synthetic_class_alpha"
    assert report.roster_student_count == 3
    assert tuple(item.dimension_id for item in report.dimensions) == (
        "analysis",
        "composition",
    )

    analysis, composition = report.dimensions
    assert analysis.signal_entry_count == 3
    assert analysis.matched_student_count == 3
    assert analysis.missing_student_count == 0
    assert analysis.unknown_student_count == 0
    assert analysis.wrong_class_student_count == 0
    assert analysis.band_counts == ((1, 1), (2, 1), (3, 0), (4, 1))

    assert composition.signal_entry_count == 3
    assert composition.matched_student_count == 3
    assert composition.missing_student_count == 0
    assert composition.unknown_student_count == 0
    assert composition.wrong_class_student_count == 0
    assert composition.band_counts == ((1, 0), (2, 2), (3, 1))


def test_core_diagnostics_treat_partial_coverage_as_missing_warning(
    tmp_path: Path,
) -> None:
    _write_roster(
        tmp_path,
        "synthetic_class_alpha",
        ("student_001", "student_002", "student_003"),
    )
    signal = _signal(
        dimensions=(("analysis", 4),),
        entries=(
            ("student_001", "analysis", 1),
            ("student_002", "analysis", 4),
        ),
    )

    report = diagnose_grouping_signal(tmp_path, signal)

    assert not report.has_errors
    assert report.has_warnings
    assert not report.is_clean
    assert tuple(
        (item.code, item.severity, item.student_id, item.dimension_id)
        for item in report.findings
    ) == (
        ("missing_student_signal", "warning", "student_003", "analysis"),
    )
    dimension = report.dimensions[0]
    assert dimension.roster_student_count == 3
    assert dimension.signal_entry_count == 2
    assert dimension.matched_student_count == 2
    assert dimension.missing_student_count == 1
    assert dimension.band_counts == ((1, 1), (2, 0), (3, 0), (4, 1))


def test_core_diagnostics_distinguish_wrong_class_unknown_and_missing(
    tmp_path: Path,
) -> None:
    _write_roster(
        tmp_path,
        "synthetic_class_alpha",
        ("student_001", "student_002"),
    )
    _write_roster(
        tmp_path,
        "synthetic_class_beta",
        ("student_wrong",),
    )
    signal = _signal(
        dimensions=(("analysis", 4),),
        entries=(
            ("student_001", "analysis", 2),
            ("student_wrong", "analysis", 3),
            ("student_unknown", "analysis", 4),
        ),
    )

    report = diagnose_grouping_signal(tmp_path, signal)

    assert report.has_errors
    assert report.has_warnings
    assert tuple(item.code for item in report.findings) == (
        "wrong_class_student",
        "unknown_student",
        "missing_student_signal",
    )
    wrong, unknown, missing = report.findings
    assert wrong.student_id == "student_wrong"
    assert wrong.dimension_id == "analysis"
    assert wrong.other_class_ids == ("synthetic_class_beta",)
    assert unknown.student_id == "student_unknown"
    assert unknown.other_class_ids == ()
    assert missing.student_id == "student_002"

    dimension = report.dimensions[0]
    assert dimension.signal_entry_count == 3
    assert dimension.matched_student_count == 1
    assert dimension.missing_student_count == 1
    assert dimension.unknown_student_count == 1
    assert dimension.wrong_class_student_count == 1
    assert dimension.band_counts == ((1, 0), (2, 1), (3, 0), (4, 0))


def test_core_diagnostics_explicit_class_mismatch_is_read_only(
    tmp_path: Path,
) -> None:
    shared_ids = ("student_001", "student_002")
    _write_roster(tmp_path, "synthetic_class_alpha", shared_ids)
    _write_roster(tmp_path, "synthetic_class_beta", shared_ids)
    signal = _signal(
        dimensions=(("analysis", 4),),
        entries=(
            ("student_001", "analysis", 1),
            ("student_002", "analysis", 4),
        ),
    )
    alpha_path = class_roster_path(tmp_path, "synthetic_class_alpha")
    beta_path = class_roster_path(tmp_path, "synthetic_class_beta")
    alpha_before = alpha_path.read_bytes()
    beta_before = beta_path.read_bytes()

    report = diagnose_grouping_signal(
        tmp_path,
        signal,
        expected_class_id="synthetic_class_beta",
    )

    assert report.has_errors
    assert not report.has_warnings
    assert tuple(item.code for item in report.findings) == ("class_mismatch",)
    assert report.signal_class_id == "synthetic_class_alpha"
    assert report.target_class_id == "synthetic_class_beta"
    assert report.dimensions[0].matched_student_count == 2
    assert report.dimensions[0].missing_student_count == 0
    assert alpha_path.read_bytes() == alpha_before
    assert beta_path.read_bytes() == beta_before
