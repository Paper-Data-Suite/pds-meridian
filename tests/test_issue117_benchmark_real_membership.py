"""Issue #117: a real selected membership reaches Report 9 without a snapshot.

Core class, calendar, registration and Meridian Grade Item/membership storage are
real and digest-verified. The publication adapter boundary alone is synthetic;
installed producer-wheel qualification remains a separate release requirement.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

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

import meridian.benchmark_current_analysis as current
from meridian.benchmark_current_analysis import (
    CurrentBenchmarkUnavailableError,
    build_current_benchmark_analysis,
)
from meridian.diagnostics import DiagnosticsDependencies
from meridian.grade_item_membership_storage import (
    GradeItemMembershipStorageIntegrityError,
    load_current_grade_item_membership_decision,
    select_grade_item_membership_revision,
    write_grade_item_membership_revision,
)
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_storage import (
    load_current_grade_item_revision,
    select_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import GradeItemRevision, GradeItemWorkReference

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)
YEAR = "2026-2027"
CLASS = "synthetic_class_2026"
GRADE_ITEM = "unit1_assessment"
PERIOD = AcademicPeriodRef(YEAR, "mp1")


def _workspace(tmp_path: Path, producer: str) -> tuple[Path, ModuleWorkRef]:
    """Author actual immutable records with their selected current pointers."""
    root = tmp_path / "workspace"
    root.mkdir()
    write_class_metadata(
        class_metadata_path(root, CLASS),
        ClassMetadata(
            class_id=CLASS,
            school_year=YEAR,
            created_at=NOW,
            updated_at=NOW,
            module_details={},
        ),
    )
    roster_path = root / "classes" / CLASS / "roster.csv"
    roster_path.write_text(
        "class_id,student_id,last_name,first_name,period\n"
        f"{CLASS},student_1,Synthetic,Ada,1\n",
        encoding="utf-8",
    )
    write_academic_period_calendar(
        root,
        AcademicPeriodCalendar(
            schema_version="1",
            record_type="academic_period_calendar",
            school_year=YEAR,
            calendar_revision=1,
            created_at=NOW,
            updated_at=NOW,
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
            ),
        ),
        expected_current_revision=None,
    )
    work = ModuleWorkRef(producer, CLASS, "assessment_1")
    module_work_dir(root, work).mkdir(parents=True, exist_ok=True)
    write_academic_work_registration(
        root,
        AcademicWorkRegistration(
            schema_version="1",
            record_type="academic_work_registration",
            work=work,
            registration_revision=1,
            producer_contract_version="v1",
            title="Synthetic Assessment",
            work_kind="assessment",
            academic_intent="summative",
            lifecycle="active",
            created_at=NOW,
            updated_at=NOW,
            source_records=(),
        ),
        expected_current_revision=None,
    )
    stored_grade = write_grade_item_revision(
        root,
        GradeItemRevision(
            schema_version="1",
            record_type="meridian_grade_item",
            class_id=CLASS,
            grade_item_id=GRADE_ITEM,
            grade_item_revision=1,
            supersedes_revision=None,
            title="Unit 1 Benchmark",
            purpose="standards_proficiency",
            status="active",
            weighting=None,
            created_at=NOW,
            revised_at=NOW,
        ),
    ).stored
    select_grade_item_revision(
        root, CLASS, GRADE_ITEM, 1, expected_current_revision=None
    )
    stored_membership = write_grade_item_membership_revision(
        root,
        GradeItemMembershipDecision(
            schema_version="1",
            record_type="meridian_grade_item_membership",
            class_id=CLASS,
            grade_item_id=GRADE_ITEM,
            grade_item_revision=1,
            grade_item_revision_sha256=stored_grade.revision_sha256,
            work_reference=GradeItemWorkReference(
                work=work, registration_revision=1
            ),
            membership_revision=1,
            supersedes_revision=None,
            decision="included",
            academic_period=GradeItemAcademicPeriodAssignment(
                period=PERIOD, calendar_revision=1
            ),
            actor_id="synthetic_teacher",
            rationale="Benchmark analysis",
            decided_at=NOW,
        ),
    ).stored
    select_grade_item_membership_revision(
        root,
        CLASS,
        GRADE_ITEM,
        work,
        1,
        expected_current_membership_revision=None,
    )
    # These are genuine SHA-verified storage wrappers, not SimpleNamespace stand-ins.
    assert load_current_grade_item_revision(root, CLASS, GRADE_ITEM) is not None
    loaded = load_current_grade_item_membership_decision(
        root, CLASS, GRADE_ITEM, work
    )
    assert loaded is not None
    assert loaded.decision_sha256 == stored_membership.decision_sha256
    return root, work


def _publication_stub(
    monkeypatch: pytest.MonkeyPatch,
    work: ModuleWorkRef,
) -> tuple[DiagnosticsDependencies, list[tuple[str, object]]]:
    """Stub only the external publication and installed adapter boundary."""
    publication_id = "pub_11111111111111111111111111111111"
    candidate = SimpleNamespace(
        publication_id=publication_id,
        catalog_publication=SimpleNamespace(work=work),
    )
    prepared = SimpleNamespace(
        canonical_context=SimpleNamespace(
            referenced_registration=SimpleNamespace(registration_revision=1),
            publication=SimpleNamespace(
                publication_id=publication_id, manifest_digest="d" * 64
            ),
        ),
        projection_request=object(),
        producer_profile=object(),
    )
    calls: list[tuple[str, object]] = []

    def discover(_root: Path, request: object) -> object:
        calls.append(("discover", request))
        return SimpleNamespace(candidates=(candidate,))

    def prepare(_root: Path, _candidate: object, **kw: object) -> object:
        calls.append(("authorize", kw))
        return prepared

    monkeypatch.setattr(current, "discover_publication_candidates", discover)
    monkeypatch.setattr(current, "prepare_publication_invocation", prepare)
    monkeypatch.setattr(current, "list_proficiency_scale_ids", lambda *_: ("scale_1",))
    monkeypatch.setattr(
        current,
        "load_current_proficiency_scale",
        lambda *_: SimpleNamespace(
            scale=SimpleNamespace(
                scale_id="scale_1",
                scale_revision=1,
                levels=(SimpleNamespace(level_id="meeting"),),
            ),
            scale_sha256="c" * 64,
        ),
    )
    deps = cast(
        DiagnosticsDependencies,
        SimpleNamespace(
            authorizer=object(),
            producer_registry=object(),
            producer_registry_state="available",
            adapter_registry=SimpleNamespace(
                invoke=lambda *_a, **_kw: SimpleNamespace(items=())
            ),
            distribution_version_resolver=lambda _: "1.0.0",
        ),
    )
    return deps, calls


@pytest.mark.parametrize("producer", ("scoreform", "quillan", "concord"))
def test_real_storage_report9_no_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, producer: str
) -> None:
    root, work = _workspace(tmp_path, producer)
    deps, calls = _publication_stub(monkeypatch, work)
    preview = build_current_benchmark_analysis(
        root,
        class_id=CLASS,
        grade_item_id=GRADE_ITEM,
        target_period=PERIOD,
        calendar_revision=1,
        generated_at=NOW,
        diagnostics=deps,
        item_observer=lambda _: (),
    )
    grade = load_current_grade_item_revision(root, CLASS, GRADE_ITEM)
    membership = load_current_grade_item_membership_decision(
        root, CLASS, GRADE_ITEM, work
    )
    assert grade is not None and membership is not None
    assert preview.report_kind == "benchmark_analysis_instructional_response"
    assert preview.class_id == CLASS
    assert preview.source_references
    assert any(
        ref.source_kind == "grade_item_revision"
        and ref.source_sha256 == grade.revision_sha256
        for ref in preview.source_references
    )
    assert any(
        ref.source_kind == "grade_item_membership"
        and ref.source_sha256 == membership.decision_sha256
        for ref in preview.source_references
    )
    assert all(
        ref.source_kind != "reporting_snapshot" for ref in preview.source_references
    )
    authorizations = [data for name, data in calls if name == "authorize"]
    assert len(authorizations) == 1
    assert isinstance(authorizations[0], dict)
    assert authorizations[0]["authorization_purpose_id"] == "teacher_reporting"
    assert authorizations[0]["requested_student_ids"] == ()
    snapshot_dir = root / "classes" / CLASS / "modules" / "meridian"
    assert not (snapshot_dir / "reporting_snapshots").exists()


def test_corrupted_real_membership_blocks_before_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, work = _workspace(tmp_path, "scoreform")
    deps, calls = _publication_stub(monkeypatch, work)
    membership = load_current_grade_item_membership_decision(
        root, CLASS, GRADE_ITEM, work
    )
    assert membership is not None
    membership.path.write_bytes(membership.content + b"\n")
    with pytest.raises(GradeItemMembershipStorageIntegrityError):
        build_current_benchmark_analysis(
            root,
            class_id=CLASS,
            grade_item_id=GRADE_ITEM,
            target_period=PERIOD,
            calendar_revision=1,
            generated_at=NOW,
            diagnostics=deps,
            item_observer=lambda _: (),
        )
    assert not any(name == "authorize" for name, _ in calls)


def test_no_authorization_blocks_before_reading_real_storage(
    tmp_path: Path,
) -> None:
    root, _work = _workspace(tmp_path, "quillan")
    with pytest.raises(CurrentBenchmarkUnavailableError, match="evidence access"):
        build_current_benchmark_analysis(
            root,
            class_id=CLASS,
            grade_item_id=GRADE_ITEM,
            target_period=PERIOD,
            calendar_revision=1,
            generated_at=NOW,
            diagnostics=None,
            item_observer=lambda _: (),
        )
