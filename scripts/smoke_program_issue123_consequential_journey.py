"""#123 11M: configured Grade through frozen ReportingSnapshot and local export.

Installed, synthetic, source-side acceptance: real domain services, named Grade,
snapshot and export controllers, explicit confirmation, fail-closed negatives.
All synthetic writes live in a newly created temporary workspace.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from pds_core.academic_periods import AcademicPeriod, AcademicPeriodRef

import meridian.report_export_commit as commit_service
from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.export_profile import ExportProfileActor
from meridian.export_profile_storage import (
    load_export_profile_revision,
    select_export_profile,
)
from meridian.grade_policy import GradeCalculationFamily
from meridian.menu_export import default_export_menu_dependencies
from meridian.menu_grades import default_grade_menu_dependencies
from meridian.menu_snapshots import default_snapshot_menu_dependencies
from meridian.menu_teacher_named_export_delivery import run_named_report_export_delivery
from meridian.menu_teacher_named_export_receipts import (
    NamedExportReceiptCatalog,
    run_named_export_receipt_browse,
)
from meridian.menu_teacher_named_grades import run_named_current_grade_review
from meridian.menu_teacher_named_snapshots import run_named_snapshot_browse
from meridian.report_export_commit import (
    ReportExportCurrentnessConflictError,
    commit_report_export,
    file_export_destination,
)
from meridian.report_export_preview import build_export_preview
from meridian.report_export_receipt import ReportExportActor, load_export_receipt
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_storage import load_reporting_snapshot
from meridian.teacher_navigation_choices import load_teacher_choices
from meridian.teacher_navigation_context import (
    TeacherNavigationContext,
    TeacherNavigationReaders,
)
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_navigation_period import PeriodProficiencyChoiceCatalog
from meridian.teacher_session import TeacherSessionContext

if TYPE_CHECKING:
    from scripts import smoke_program_grade_report_preview as issue54
    from scripts import smoke_program_hybrid_grade as issue52
    from scripts import smoke_program_proficiency_signal_export as issue45
    from scripts import smoke_program_report_exports as issue56
    from scripts import smoke_program_reporting_snapshot as issue55
else:
    import smoke_program_grade_report_preview as issue54
    import smoke_program_hybrid_grade as issue52
    import smoke_program_proficiency_signal_export as issue45
    import smoke_program_report_exports as issue56
    import smoke_program_reporting_snapshot as issue55

SUCCESS = "Meridian #123 11M installed consequential teacher journey passed."
APPROVED_ID = "export-" + "b" * 32
STALE_ID = "issue123_11m_stale_rejected"


@dataclass
class Script:
    answers: list[str]
    prompts: list[str] = field(default_factory=list)

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        if not self.answers:
            raise AssertionError("Unexpected teacher prompt: " + prompt)
        return self.answers.pop(0)


def exercise(action: Any, answers: Script, **kwargs: Any) -> str:
    output = StringIO()
    action(input_fn=answers, output=output, clear_fn=lambda: None, **kwargs)
    if answers.answers:
        raise AssertionError("Unused teacher responses after action.")
    return output.getvalue()


def no_raw(answers: Script) -> None:
    for prompt in answers.prompts:
        if any(
            word in prompt.casefold()
            for word in (
                "class id:",
                "student id:",
                "snapshot id:",
                "profile id:",
                "sha256:",
                "cache key:",
            )
        ):
            raise AssertionError("Ordinary path prompted for technical identity.")


def tree(root: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (
                file.relative_to(root).as_posix(),
                hashlib.sha256(file.read_bytes()).hexdigest(),
            )
            for file in root.rglob("*")
            if file.is_file()
        )
    )


def run_fixture(main: Any, root: Path) -> None:
    original = sys.argv
    try:
        sys.argv = ["installed-acceptance", str(root)]
        if main() != 0:
            raise AssertionError("Installed domain fixture returned failure.")
    finally:
        sys.argv = original


def position(choices: tuple[Any, ...], identity: str) -> str:
    matches = [i for i, item in enumerate(choices, 1) if item.identity == (identity,)]
    if len(matches) != 1:
        raise AssertionError("Named catalog did not uniquely identify selected record.")
    return str(matches[0])


def journey(root: Path) -> None:
    # Source fixture itself checks provenance-complete 96.00 hybrid Grade and
    # authorized ScoreForm/Quillan-backed calculations before freezing.
    captured: list[tuple[ConventionalGradeWorkEvidenceSpec, ...]] = []
    seed = issue54._hybrid_state

    def record_hybrid(workspace: Path) -> Any:
        result = seed(workspace)
        captured.append(result[1])
        return result

    # The older #45/54 hybrid fixture uses Core period_type="quarter".
    # Teacher-first navigation intentionally lists marking_period only.
    # Convert the single synthetic seed before all records are written;
    # never modify the real period selector or any committed state.
    original_period = AcademicPeriod

    def marked_period(*args: Any, **kwargs: Any) -> Any:
        value = original_period(*args, **kwargs)
        if value.period_id != issue52.PERIOD_ID or value.period_type != "quarter":
            raise AssertionError("Unexpected synthetic Core period seed.")
        return replace(value, period_type="marking_period")

    with (
        patch.object(issue45, "AcademicPeriod", new=marked_period),
        patch.object(issue54, "_hybrid_state", side_effect=record_hybrid),
    ):
        run_fixture(issue55.main, root)
    if len(captured) != 1:
        raise AssertionError("Configured hybrid Grade evidence was not captured.")

    baseline = json.loads((root / issue55.BASELINE_NAME).read_text(encoding="utf-8"))
    workspace = root / baseline["workspace"]
    class_id: str = baseline["class_id"]
    snapshot_ref = ReportingSnapshotReference(
        class_id=class_id,
        snapshot_id=baseline["snapshot_id"],
        snapshot_sha256=baseline["snapshot_sha256"],
    )
    frozen = load_reporting_snapshot(workspace, class_id, snapshot_ref.snapshot_id)
    assert frozen.reference == snapshot_ref
    assert len(frozen.snapshot.report_preview.rows) == 1
    assert frozen.snapshot.report_preview.rows[0].observation is not None

    nav = TeacherNavigationContext(
        session=TeacherSessionContext(),
        readers=TeacherNavigationReaders(
            workspace_resolver=lambda: workspace,
            active_year_loader=lambda _: issue52.PERIOD.school_year,
        ),
    )
    classes = TeacherAcademicChoiceCatalog(nav)
    class_number = position(load_teacher_choices(classes, scope="class"), class_id)
    nav.choose_class(class_id)
    periods = PeriodProficiencyChoiceCatalog(nav)
    period_number = position(
        load_teacher_choices(periods, scope="period", selected={"class": class_id}),
        issue52.PERIOD.period_id,
    )
    students = load_teacher_choices(
        classes, scope="student", selected={"class": class_id}
    )
    student_number = position(students, issue52.STUDENT_ID)
    nav.session.clear()

    def authorized_evidence(
        target_root: Path,
        target_class: str,
        target_student: str,
        period: AcademicPeriodRef,
        revision: int,
        family: GradeCalculationFamily,
    ) -> tuple[ConventionalGradeWorkEvidenceSpec, ...]:
        assert (target_root, target_class, target_student) == (
            workspace,
            class_id,
            issue52.STUDENT_ID,
        )
        assert period == issue52.PERIOD
        assert revision == issue52.CALENDAR_REVISION and family == "hybrid"
        return captured[0]

    grade_loader = default_grade_menu_dependencies(
        work_evidence_provider=authorized_evidence
    ).current_grade_loader
    before = tree(workspace)
    grade_script = Script([class_number, period_number, student_number, "3", ""])
    grade = exercise(
        run_named_current_grade_review,
        grade_script,
        navigation=nav,
        current_grade_loader=grade_loader,
        class_catalog=classes,
        period_catalog=periods,
    )
    assert "Current Grade Review" in grade, grade[-1000:]
    assert "Base Grade: 96.00" in grade and "Effective Grade: 96.00" in grade, grade[
        -1000:
    ]
    no_raw(grade_script)
    assert nav.session.active_class_id == class_id
    assert nav.session.active_student_id == issue52.STUDENT_ID
    assert nav.current_period() is not None
    assert tree(workspace) == before

    # The existing installed #56 fixture deliberately commits exact snapshot-
    # and roster-backed local exports, then reloads immutable receipts.
    run_fixture(issue56.main, root)
    export_baseline = json.loads(
        (root / issue56.BASELINE_NAME).read_text(encoding="utf-8")
    )
    assert export_baseline["snapshot_sha256"] == snapshot_ref.snapshot_sha256
    source_snapshot = load_reporting_snapshot(
        workspace, class_id, snapshot_ref.snapshot_id
    )
    assert source_snapshot.reference == snapshot_ref
    assert (root / export_baseline["file_name"]).is_file()
    assert (
        hashlib.sha256((root / export_baseline["file_name"]).read_bytes()).hexdigest()
        == export_baseline["file_sha256"]
    )
    assert (
        load_export_receipt(workspace, class_id, issue56.FILE_EXPORT_ID).receipt_sha256
        == export_baseline["file_receipt_sha256"]
    )

    snapshot_deps = default_snapshot_menu_dependencies()
    export_deps = default_export_menu_dependencies()
    after_exports = tree(workspace)
    snapshot_script = Script(["1", ""])
    snapshot_display = exercise(
        run_named_snapshot_browse,
        snapshot_script,
        navigation=nav,
        lister=snapshot_deps.lister,
        inspector=snapshot_deps.inspector,
        class_catalog=classes,
    )
    assert "Frozen Reporting Checkpoint" in snapshot_display, snapshot_display[-1000:]
    no_raw(snapshot_script)
    assert tree(workspace) == after_exports

    receipt_catalog = NamedExportReceiptCatalog(
        navigation=nav,
        lister=export_deps.receipt_lister,
        loader=export_deps.receipt_loader,
    )
    receipts = load_teacher_choices(
        receipt_catalog, scope="export_receipt", selected={"class": class_id}
    )
    receipt_script = Script([position(receipts, issue56.FILE_EXPORT_ID), ""])
    receipt_display = exercise(
        run_named_export_receipt_browse,
        receipt_script,
        navigation=nav,
        receipt_lister=export_deps.receipt_lister,
        receipt_loader=export_deps.receipt_loader,
        class_catalog=classes,
        receipt_catalog=receipt_catalog,
    )
    assert "Saved Local Export Receipt" in receipt_display, receipt_display[-1000:]
    assert "not" in receipt_display.lower() and "district" in receipt_display.lower()
    no_raw(receipt_script)
    assert tree(workspace) == after_exports

    # Profile revision was deliberately authored by #56; selection for the
    # ordinary named workflow remains a separate explicit fixture action.
    selected_profile = load_export_profile_revision(
        workspace, class_id, issue56.SNAPSHOT_PROFILE_ID, 1
    )
    select_export_profile(
        workspace,
        selected_profile.reference,
        actor=ExportProfileActor("teacher", issue56.ACTOR_ID),
        rationale="Select exact synthetic profile for named teacher acceptance.",
        decided_at=datetime(2026, 9, 22, 9, tzinfo=UTC),
        expected_current=None,
    )
    before_named_write = tree(workspace)

    def do_delivery(answers: Script, *, receipt_id: str) -> str:
        return exercise(
            run_named_report_export_delivery,
            answers,
            navigation=nav,
            snapshot_lister=snapshot_deps.lister,
            profile_lister=export_deps.profile_lister,
            profile_loader=export_deps.profile_loader,
            preview_builder=export_deps.preview_builder,
            export_committer=export_deps.export_committer,
            receipt_loader=export_deps.receipt_loader,
            clock=lambda: datetime(2026, 9, 22, 10, tzinfo=UTC),
            export_id_factory=lambda: receipt_id,
            class_catalog=classes,
            period_catalog=periods,
        )

    # Cancel after successful real named preview, without authorizing EXPORT.
    cancelled = Script(["1", "1", "2", issue56.ACTOR_ID, "", "", ""])
    canceled_view = do_delivery(cancelled, receipt_id="export-" + "a" * 32)
    assert "Canceled. No export was attempted." in canceled_view, canceled_view[-1000:]
    no_raw(cancelled)
    assert tree(workspace) == before_named_write

    # Explicit typed confirmation uses the true production named controller.
    destination = root / "issue123-11m-confirmed-local-export.csv"
    approved = Script(
        [
            "1",
            "1",
            "1",
            str(destination),
            issue56.ACTOR_ID,
            "Synthetic teacher acceptance",
            "EXPORT",
            "",
        ]
    )
    accepted_view = do_delivery(approved, receipt_id=APPROVED_ID)
    assert "Local Report Export Recorded" in accepted_view, accepted_view[-1400:]
    assert "Exact local ExportReceipt verified." in accepted_view
    no_raw(approved)
    approved_receipt = load_export_receipt(workspace, class_id, APPROVED_ID)
    assert approved_receipt.receipt.destination.basename == destination.name
    assert approved_receipt.receipt.destination.kind == "file"
    assert destination.is_file()
    assert str(destination).encode("utf-8") not in approved_receipt.content
    assert (
        load_reporting_snapshot(workspace, class_id, snapshot_ref.snapshot_id).reference
        == snapshot_ref
    )

    # Inject a different *real built* preview during commit: the service must
    # reject a changed exact source before writing any artifact or receipt.
    other_profile = load_export_profile_revision(
        workspace, class_id, issue56.ROSTER_PROFILE_ID, 1
    )
    selected_preview = build_export_preview(
        workspace, snapshot_ref, selected_profile.reference
    )
    conflicting_preview = build_export_preview(
        workspace, snapshot_ref, other_profile.reference
    )
    assert selected_preview.preview != conflicting_preview.preview
    conflict_destination = root / "issue123-11m-stale-must-not-exist.csv"
    before_rejection = tree(workspace)
    with patch.object(
        commit_service, "build_export_preview", return_value=conflicting_preview
    ):
        try:
            commit_report_export(
                workspace,
                export_id=STALE_ID,
                approved_preview=selected_preview.preview,
                destination=file_export_destination(conflict_destination),
                actor=ReportExportActor("teacher", issue56.ACTOR_ID),
                rationale="Reject synthetic changed-currentness preview.",
                exported_at=datetime(2026, 9, 22, 11, tzinfo=UTC),
            )
        except ReportExportCurrentnessConflictError:
            pass
        else:
            raise AssertionError("Changed exact export preview was not rejected.")
    assert not conflict_destination.exists()
    assert tree(workspace) == before_rejection

    # Denial cannot disclose the private token or create/readjust a Grade.
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError("synthetic-private-evidence-token")

    denied_script = Script([student_number, "3", ""])
    denied_view = exercise(
        run_named_current_grade_review,
        denied_script,
        navigation=nav,
        current_grade_loader=denied,
        class_catalog=classes,
        period_catalog=periods,
    )
    assert "cannot be verified or is not configured" in denied_view
    assert "synthetic-private-evidence-token" not in denied_view
    no_raw(denied_script)
    assert tree(workspace) == before_rejection
    print(SUCCESS, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    issue56._verify_installed_composition()
    for distribution, version in (
        ("pds-meridian", "0.4.2"),
        ("pds-core", "0.6.6"),
        ("scoreform", "0.13.0"),
        ("quillan", "0.10.6"),
        ("pds-concord", "0.3.2"),
    ):
        assert importlib.metadata.version(distribution) == version
    if args.root.exists():
        raise RuntimeError("11M requires a new absent synthetic workspace root.")
    args.root.mkdir(parents=True)
    journey(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
