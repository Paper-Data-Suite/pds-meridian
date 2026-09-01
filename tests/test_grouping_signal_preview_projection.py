from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pds_core.grouping_signal_storage import list_grouping_signal_ids
from pds_core.rosters import (
    StudentRecord,
    load_roster,
    replace_student_record,
    write_roster,
)
from pds_core.routes import class_roster_path

from meridian.grouping_signal_derivation_storage import (
    list_grouping_signal_derivation_ids,
)
from meridian.grouping_signal_generation import generate_grouping_signal_derivation
from meridian.grouping_signal_preview_generation import (
    generate_grouping_signal_preview,
)
from meridian.grouping_signal_preview_projection import (
    ACCEPTANCE_DOES_NOT_EXPORT_NOTICE,
    EXPORT_ONLY_IN_ISSUE_40_NOTICE,
    PREVIEW_DOES_NOT_EXPORT_NOTICE,
    build_grouping_signal_teacher_projection,
    format_grouping_signal_teacher_projection,
)
from meridian.grouping_signal_preview_storage import (
    list_grouping_signal_preview_ids,
)
from meridian.grouping_signal_review_storage import (
    list_grouping_signal_review_revisions,
    select_grouping_signal_review_revision,
)
from meridian.grouping_signal_review_workflow import record_grouping_signal_review
from tests.test_grouping_signal_generation_integration import (
    CLASS_ID,
    _seed_current_grade_item_result,
    _seed_period_result_and_grouping_policy,
    _seed_workspace,
)

NOW = datetime(2026, 8, 31, 18, 30, tzinfo=UTC)


def _seed(tmp_path: Path):
    workspace, scale = _seed_workspace(tmp_path)
    grade_item_basis, membership, membership_sha256 = (
        _seed_current_grade_item_result(workspace, scale)
    )
    policy_id = _seed_period_result_and_grouping_policy(
        workspace,
        scale,
        grade_item_basis,
        membership,
        membership_sha256,
    )
    generated = generate_grouping_signal_derivation(
        workspace,
        CLASS_ID,
        policy_id,
    )
    assert generated.status == "generated"
    assert generated.stored is not None
    preview_result = generate_grouping_signal_preview(
        workspace,
        generated.stored.reference,
    )
    return workspace, generated.stored, preview_result.stored


def test_teacher_projection_exposes_required_sections_and_neutral_bands(
    tmp_path: Path,
) -> None:
    workspace, derivation, preview = _seed(tmp_path)

    projection = build_grouping_signal_teacher_projection(
        workspace,
        preview.reference,
    )
    rendered = format_grouping_signal_teacher_projection(projection)

    assert projection.class_id == CLASS_ID
    assert projection.school_year == "2026-2027"
    assert projection.period_id == "mp1"
    assert projection.standard_id == "urn:njsls:ela:RL.CR.9-10.1"
    assert projection.derivation_reference == derivation.reference
    assert projection.live_currentness.state == "current"
    assert projection.policy_title == "Reading planning signal"
    assert projection.dimension_id == "reading_planning"
    assert projection.band_count == 2
    assert projection.band_summaries[0].label == "Band 1"
    assert projection.band_summaries[1].label == "Band 2"
    assert projection.student_assignments[0].display_name == "Synthetic Student"
    assert projection.student_assignments[0].band == 2
    assert projection.review_status.selected_review_reference is None
    assert projection.notices == (
        PREVIEW_DOES_NOT_EXPORT_NOTICE,
        ACCEPTANCE_DOES_NOT_EXPORT_NOTICE,
        EXPORT_ONLY_IN_ISSUE_40_NOTICE,
    )

    for section in (
        "Class",
        "Academic Basis",
        "Derivation Identity",
        "Policy",
        "Band Definitions",
        "Coverage",
        "Band Distribution",
        "Student Assignments",
        "Ties",
        "Noncontributing Students",
        "Diagnostics / Limitations",
        "Review Status",
        "Export Boundary",
    ):
        assert section in rendered
    assert "Band 1" in rendered
    assert "Band 2" in rendered
    assert "Previewing does not export." in rendered
    assert "Accepting does not export." in rendered
    assert "Export happens only in #40." in rendered
    assert "low band" not in rendered.lower()
    assert "high band" not in rendered.lower()
    assert "ability" not in rendered.lower()
    assert "readiness" not in rendered.lower()


def test_projection_display_name_join_is_transient_and_identity_neutral(
    tmp_path: Path,
) -> None:
    workspace, derivation, preview = _seed(tmp_path)
    before_reference = preview.reference
    before_derivations = list_grouping_signal_derivation_ids(
        workspace,
        CLASS_ID,
    )
    before_previews = list_grouping_signal_preview_ids(workspace, CLASS_ID)

    roster_path = class_roster_path(workspace, CLASS_ID)
    roster = load_roster(roster_path)
    original = roster.students[0]
    renamed = StudentRecord(
        class_id=original.class_id,
        student_id=original.student_id,
        last_name="Renamed",
        first_name="Display",
        period=original.period,
        extra_fields=original.extra_fields,
    )
    write_roster(
        roster_path,
        replace_student_record(roster, renamed),
        overwrite=True,
    )

    projection = build_grouping_signal_teacher_projection(
        workspace,
        preview.reference,
    )

    assert projection.student_assignments[0].display_name == "Display Renamed"
    assert projection.preview_reference == before_reference
    assert projection.derivation_reference == derivation.reference
    assert projection.live_currentness.state == "current"
    assert list_grouping_signal_derivation_ids(
        workspace,
        CLASS_ID,
    ) == before_derivations
    assert list_grouping_signal_preview_ids(
        workspace,
        CLASS_ID,
    ) == before_previews


def test_projection_surfaces_selected_review_and_live_applicability(
    tmp_path: Path,
) -> None:
    workspace, _, preview = _seed(tmp_path)
    warning_ids = tuple(
        sorted(
            item.diagnostic_id
            for item in preview.snapshot.diagnostics
            if item.severity == "warning"
        )
    )
    recorded = record_grouping_signal_review(
        workspace,
        preview.reference,
        review_revision=1,
        supersedes_revision=None,
        decision="accepted_for_export",
        acknowledged_warning_ids=warning_ids,
        actor_id="teacher_local",
        reviewed_at=NOW,
    )
    derivation_id = recorded.stored.review.derivation_reference.derivation_id
    select_grouping_signal_review_revision(
        workspace,
        CLASS_ID,
        derivation_id,
        1,
        expected_current_review_revision=None,
    )

    projection = build_grouping_signal_teacher_projection(
        workspace,
        preview.reference,
    )
    review = projection.review_status

    assert review.selected_review_reference == recorded.stored.reference
    assert review.decision == "accepted_for_export"
    assert review.acknowledged_warning_ids == warning_ids
    assert review.actor_id == "teacher_local"
    assert review.reviewed_at == NOW
    assert review.applicability is not None
    assert review.applicability.status == "current"


def test_projection_is_read_only_across_meridian_and_core_signal_storage(
    tmp_path: Path,
) -> None:
    workspace, _, preview = _seed(tmp_path)
    derivation_id = preview.snapshot.derivation_reference.derivation_id
    before = (
        list_grouping_signal_derivation_ids(workspace, CLASS_ID),
        list_grouping_signal_preview_ids(workspace, CLASS_ID),
        list_grouping_signal_review_revisions(
            workspace,
            CLASS_ID,
            derivation_id,
        ),
        list_grouping_signal_ids(workspace, CLASS_ID),
    )

    projection = build_grouping_signal_teacher_projection(
        workspace,
        preview.reference,
    )
    assert projection.preview_reference == preview.reference

    after = (
        list_grouping_signal_derivation_ids(workspace, CLASS_ID),
        list_grouping_signal_preview_ids(workspace, CLASS_ID),
        list_grouping_signal_review_revisions(
            workspace,
            CLASS_ID,
            derivation_id,
        ),
        list_grouping_signal_ids(workspace, CLASS_ID),
    )
    assert after == before
