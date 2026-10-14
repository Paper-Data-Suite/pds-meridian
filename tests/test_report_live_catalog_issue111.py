"""Slice 12.2: canonical read-only report discovery with injected source readers."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.class_metadata import ClassMetadata
from pds_core.classes import ClassFolder, class_folder
from pds_core.rosters import Roster

from meridian.external_gradebook_mapping import (
    ExternalGradebookMappingEntry,
    compose_external_gradebook_mapping_revision,
    external_gradebook_mapping_to_json_bytes,
)
from meridian.grade_items_workflow import GradeItemsReview
from meridian.proficiency_mapping import proficiency_scale_reference
from meridian.report_guided_selection import ReportSelectionUnavailable
from meridian.report_live_catalog import (
    LiveReportChoiceCatalog,
    ReportLiveCatalogDependencies,
)
from meridian.reporting_snapshot_storage import StoredReportingSnapshot
from tests.test_external_gradebook_mapping_issue111 import scale


def make_catalog(
    *,
    roots: tuple[Path, ...] | None = None,
    years: tuple[str, ...] = ("2026-2027",),
) -> LiveReportChoiceCatalog:
    workspace = Path("C:/synthetic")
    files = iter(roots) if roots is not None else None

    def resolve() -> Path:
        return next(files) if files is not None else workspace

    def classes(root: Path) -> tuple[ClassFolder, ...]:
        assert root == workspace
        folder = class_folder(workspace, "english12_p4")
        metadata = cast(
            ClassMetadata,
            SimpleNamespace(class_id="english12_p4", school_year=years[0]),
        )
        return (replace(folder, metadata=metadata),)

    def period_list(root: Path, year: str):
        assert year == years[0]
        return (
            SimpleNamespace(
                school_year=year,
                period_id="mp1",
                label="Marking Period 1",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 11, 5),
                calendar_revision=2,
                lifecycle="active",
            ),
            SimpleNamespace(
                school_year=year,
                period_id="cancelled",
                label="Cancelled period",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 11, 5),
                calendar_revision=2,
                lifecycle="cancelled",
            ),
        )

    def roster(root: Path, class_id: str) -> Roster:
        assert class_id == "english12_p4"
        return cast(Roster, SimpleNamespace(students=(
            SimpleNamespace(student_id="s01", first_name="Alex", last_name="Chen"),
            SimpleNamespace(student_id="s02", first_name="Alex", last_name="Chen"),
            SimpleNamespace(student_id="s03", first_name="Sam", last_name="Rivera"),
        )))

    def items(root: Path, class_id: str) -> GradeItemsReview:
        return cast(GradeItemsReview, SimpleNamespace(items=(
            SimpleNamespace(
                grade_item_id="gi1", title="Comparative Essay",
                selected_revision=2, status="active"
            ),
            SimpleNamespace(
                grade_item_id="gi2", title=None,
                selected_revision=None, status=None
            ),
        )))

    def snaps(root: Path, class_id: str) -> tuple[str, ...]:
        return ("snapshot_mp1", "snapshot_other")

    def load_snap(root: Path, class_id: str, snapshot_id: str):
        target_id = "mp1" if snapshot_id == "snapshot_mp1" else "mp2"
        snapshot = SimpleNamespace(
            target_period=SimpleNamespace(school_year=years[0], period_id=target_id),
            calendar_revision=2,
            created_at=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
        )
        return cast(StoredReportingSnapshot, SimpleNamespace(snapshot=snapshot))

    return LiveReportChoiceCatalog(
        ReportLiveCatalogDependencies(
            workspace_resolver=resolve,
            class_lister=classes,
            period_lister=period_list,
            class_metadata_loader=lambda _root, _class: cast(
                ClassMetadata,
                SimpleNamespace(school_year=years[0]),
            ),
            roster_loader=roster,
            grade_item_reviewer=items,
            snapshot_id_lister=snaps,
            snapshot_loader=load_snap,
        )
    )


# The root is created explicitly because the provider requires an existing,
# resolved workspace. No tests write files inside the workspace during discovery.
@pytest.fixture
def catalog(tmp_path: Path) -> LiveReportChoiceCatalog:
    live = make_catalog()
    # Make the synthetic resolver point at a real canonical path.
    deps = live.dependencies
    return LiveReportChoiceCatalog(
        replace(
            deps,
            workspace_resolver=lambda: tmp_path,
            class_lister=lambda _root: (
                replace(
                    class_folder(tmp_path, "english12_p4"),
                    metadata=cast(
                        ClassMetadata,
                        SimpleNamespace(school_year="2026-2027"),
                    ),
                ),
            ),
        )
    )


def test_classes_use_canonical_metadata_and_are_sis_neutral(
    catalog: LiveReportChoiceCatalog,
) -> None:
    choices = catalog.options(
        report_kind="sis_gradebook_reconciliation", scope="class", selected={}
    )
    assert len(choices) == 1
    assert choices[0].value == "english12_p4"
    assert "2026-2027" in choices[0].display
    assert "Genesis" not in choices[0].display


def test_marking_periods_are_current_and_not_cancelled(
    catalog: LiveReportChoiceCatalog,
) -> None:
    choices = catalog.options(
        report_kind="marking_period_readiness",
        scope="period",
        selected={"class": "english12_p4"},
    )
    assert [item.value for item in choices] == ["mp1"]
    assert "Marking Period 1" in choices[0].display


def test_duplicate_student_names_are_disambiguated(
    catalog: LiveReportChoiceCatalog,
) -> None:
    choices = catalog.options(
        report_kind="student_current_grade_justification",
        scope="student",
        selected={"class": "english12_p4", "period": "mp1"},
    )
    assert len(choices) == 3
    assert choices[0].display == "Alex Chen - Record s01"
    assert choices[1].display == "Alex Chen - Record s02"
    assert choices[2].display == "Sam Rivera"


def test_grade_items_are_exact_selected_class_records(
    catalog: LiveReportChoiceCatalog,
) -> None:
    choices = catalog.options(
        report_kind="assessment_impact",
        scope="grade_item",
        selected={"class": "english12_p4", "period": "mp1"},
    )
    assert len(choices) == 1
    assert choices[0].value == "gi1"
    assert "Comparative Essay" in choices[0].display


def test_checkpoints_require_matching_exact_period_and_calendar(
    catalog: LiveReportChoiceCatalog,
) -> None:
    choices = catalog.options(
        report_kind="grade_checkpoint_comparison",
        scope="checkpoint",
        selected={"class": "english12_p4", "period": "mp1"},
    )
    assert len(choices) == 1
    assert choices[0].value == "snapshot_mp1"
    assert "2026-10-13" in choices[0].label


def test_mapping_never_guessed_from_files(catalog: LiveReportChoiceCatalog) -> None:
    assert catalog.options(
        report_kind="sis_gradebook_reconciliation",
        scope="mapping",
        selected={"class": "english12_p4", "period": "mp1"},
    ) == ()


def test_teacher_named_mapping_file_is_validated_and_rechecked(
    catalog: LiveReportChoiceCatalog,
    tmp_path: Path,
) -> None:
    target_scale = replace(scale(), class_id="english12_p4")
    profile = compose_external_gradebook_mapping_revision(
        class_id="english12_p4",
        profile_id="district_gradebook",
        profile_revision=2,
        title="School gradebook scale",
        system_label="Any district gradebook",
        target_period=AcademicPeriodRef("2026-2027", "mp1"),
        target_scale=proficiency_scale_reference(target_scale),
        entries=tuple(
            ExternalGradebookMappingEntry(item.level_id, str(index + 1))
            for index, item in enumerate(target_scale.levels)
        ),
        actor_id="teacher_local",
        revised_at=datetime(2026, 10, 13, 12, 0, tzinfo=UTC),
    )
    path = tmp_path / "mapping.json"
    path.write_bytes(external_gradebook_mapping_to_json_bytes(profile))
    selected = {"class": "english12_p4", "period": "mp1"}

    option = catalog.choose_mapping_file(
        report_kind="sis_gradebook_reconciliation",
        path_text=str(path),
        selected=selected,
    )

    assert "Any district gradebook" in option.display
    assert catalog.options(
        report_kind="sis_gradebook_reconciliation",
        scope="mapping",
        selected=selected,
    ) == (option,)


def test_invalid_previous_class_rejected(catalog: LiveReportChoiceCatalog) -> None:
    with pytest.raises(ReportSelectionUnavailable):
        catalog.options(
            report_kind="assessment_impact",
            scope="grade_item",
            selected={"class": "invalid", "period": "mp1"},
        )


def test_invalid_previous_period_rejected(catalog: LiveReportChoiceCatalog) -> None:
    with pytest.raises(ReportSelectionUnavailable):
        catalog.options(
            report_kind="assessment_impact",
            scope="grade_item",
            selected={"class": "english12_p4", "period": "cancelled"},
        )


def test_unknown_report_fails_closed(catalog: LiveReportChoiceCatalog) -> None:
    with pytest.raises(ReportSelectionUnavailable):
        catalog.options(report_kind="bogus", scope="class", selected={})


def test_workspace_move_fails_closed(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    choices = iter((tmp_path, other))
    live = LiveReportChoiceCatalog(
        ReportLiveCatalogDependencies(workspace_resolver=lambda: next(choices))
    )
    # Initial scan sees no classes, but pins the resolved workspace.
    assert live.options(
        report_kind="marking_period_readiness", scope="class", selected={}
    ) == ()
    with pytest.raises(ReportSelectionUnavailable):
        live.options(report_kind="marking_period_readiness", scope="class", selected={})
