"""Issue #117: Report 9 works from authorized current publications, not snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.routing_models import ModuleWorkRef

import meridian.benchmark_current_analysis as current
import meridian.report_menu_execution as executor_module
from meridian.benchmark_current_analysis import (
    CurrentBenchmarkUnavailableError,
    build_current_benchmark_analysis,
)
from meridian.diagnostics import DiagnosticsDependencies
from meridian.report_menu_execution import LiveReportMenuExecutor
from meridian.teacher_report import TeacherReportPreview

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)
PERIOD = AcademicPeriodRef("2026-2027", "mp1")


def _context(
    monkeypatch: pytest.MonkeyPatch, producer: str
) -> tuple[DiagnosticsDependencies, list[object]]:
    work = ModuleWorkRef(producer, "class_1", "assessment_1")
    membership = SimpleNamespace(
        decision=SimpleNamespace(
            academic_period=SimpleNamespace(period=PERIOD, calendar_revision=1),
            work_reference=SimpleNamespace(work=work, registration_revision=1),
            membership_revision=1,
        ),
        decision_sha256="b" * 64,
    )
    grade_item = SimpleNamespace(
        revision=SimpleNamespace(
            grade_item_revision=1, title="Current assessment", status="active"
        ),
        revision_sha256="a" * 64,
    )
    scale = SimpleNamespace(
        scale=SimpleNamespace(
            scale_id="scale_1", scale_revision=1,
            levels=(SimpleNamespace(level_id="meeting"),)
        ),
        scale_sha256="c" * 64,
    )
    roster = SimpleNamespace(
        students=(SimpleNamespace(
            student_id="student_1", first_name="Ada", last_name="One"
        ),)
    )
    candidate = SimpleNamespace(
        publication_id="pub_11111111111111111111111111111111",
        catalog_publication=SimpleNamespace(work=work),
    )
    prepared = SimpleNamespace(
        canonical_context=SimpleNamespace(
            referenced_registration=SimpleNamespace(registration_revision=1),
            publication=SimpleNamespace(
                publication_id=candidate.publication_id, manifest_digest="d" * 64
            ),
        ),
        projection_request=object(), producer_profile=object(),
    )
    calls: list[object] = []

    monkeypatch.setattr(
        current, "load_current_grade_item_revision", lambda *_: grade_item
    )
    monkeypatch.setattr(
        current, "list_selected_included_grade_item_memberships",
        lambda *_: (membership,),
    )
    monkeypatch.setattr(current, "load_class_roster", lambda *_: roster)
    monkeypatch.setattr(current, "list_proficiency_scale_ids", lambda *_: ("scale_1",))
    monkeypatch.setattr(current, "load_current_proficiency_scale", lambda *_: scale)
    monkeypatch.setattr(
        current, "load_current_standard_proficiency_result", lambda *_: None
    )
    def discovery(_root: Path, request: object) -> object:
        calls.append(("discover", request))
        return SimpleNamespace(candidates=(candidate,))
    monkeypatch.setattr(current, "discover_publication_candidates", discovery)
    def prepare(_root: Path, _candidate: object, **kwargs: object) -> object:
        calls.append(("prepare", kwargs))
        return prepared
    monkeypatch.setattr(current, "prepare_publication_invocation", prepare)
    dependencies = cast(
        DiagnosticsDependencies,
        SimpleNamespace(
            authorizer=object(),
            producer_registry=object(),
            producer_registry_state="available",
            adapter_registry=SimpleNamespace(
                invoke=lambda *_args, **_kw: SimpleNamespace(items=())
            ),
            distribution_version_resolver=lambda _: "1.0.0",
        ),
    )
    return dependencies, calls


@pytest.mark.parametrize("producer", ("scoreform", "quillan", "concord"))
def test_current_report_without_checkpoint_uses_all_producer_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, producer: str,
) -> None:
    dependencies, calls = _context(monkeypatch, producer)
    result = build_current_benchmark_analysis(
        tmp_path,
        class_id="class_1",
        grade_item_id="grade_1",
        target_period=PERIOD,
        calendar_revision=1,
        generated_at=NOW,
        diagnostics=cast(DiagnosticsDependencies, dependencies),
        item_observer=lambda _items: (),
    )
    assert result.report_kind == "benchmark_analysis_instructional_response"
    assert result.title == "Benchmark Analysis & Instructional Response Planner"
    assert "not assessed" in " ".join(
        (part or "") for row in result.rows for part in row.values
    ).casefold()
    assert any(entry[0] == "discover" for entry in calls)
    preparations = [entry for entry in calls if entry[0] == "prepare"]
    assert len(preparations) == 1
    kwargs = preparations[0][1]
    assert kwargs["authorization_purpose_id"] == "teacher_reporting"
    assert kwargs["requested_student_ids"] == ()
    assert any(
        source.source_kind == "publication" for source in result.source_references
    )
    assert not any(
        source.source_kind == "reporting_snapshot"
        for source in result.source_references
    )


def test_without_reporting_permission_fails_before_manifest_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _context(monkeypatch, "scoreform")
    with pytest.raises(CurrentBenchmarkUnavailableError, match="evidence access"):
        build_current_benchmark_analysis(
            tmp_path, class_id="class_1", grade_item_id="grade_1",
            target_period=PERIOD, calendar_revision=1,
            generated_at=NOW, diagnostics=None, item_observer=lambda _: (),
        )


def test_normal_report_executor_uses_current_path_not_legacy_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    preview = cast(TeacherReportPreview, object())
    def current_builder(*_args: object, **kwargs: object) -> TeacherReportPreview:
        calls.append(kwargs)
        return preview
    monkeypatch.setattr(
        executor_module, "build_current_benchmark_analysis", current_builder
    )
    executor = LiveReportMenuExecutor()
    context = SimpleNamespace(
        root=Path("workspace"), class_id="class_1",
        period=SimpleNamespace(
            school_year="2026-2027", period_id="mp1", calendar_revision=1
        ),
        identifiers={"grade_item": "grade_1"},
    )
    assert executor._build(
        cast(object, context), "benchmark_analysis_instructional_response", NOW
    ) is preview
    assert len(calls) == 1
    assert calls[0]["grade_item_id"] == "grade_1"
