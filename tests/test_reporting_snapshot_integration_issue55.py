from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import (
    ACADEMIC_PERIOD_CALENDAR_RECORD_TYPE,
    ACADEMIC_PERIOD_CALENDAR_SCHEMA_VERSION,
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
)

import meridian.reporting_snapshot_freeze as freeze_module
from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.conventional_grade_explanation import (
    ConventionalGradeFormulaExplanation,
    ConventionalGradePreviewExplanation,
    conventional_grade_observation,
)
from meridian.grade_policy import GradePolicyReference
from meridian.grade_policy_activation import GradePolicyActivationReference
from meridian.grade_preview_explanation import (
    GradePreviewBaseResultExplanation,
    GradePreviewBasisEntry,
    GradePreviewExplanation,
    GradePreviewObservation,
    GradePreviewPolicyExplanation,
    GradePreviewRoundingExplanation,
    GradePreviewStateTreatmentRule,
    GradePreviewTarget,
    grade_preview_observation_to_json_bytes,
)
from meridian.grade_report_preview import (
    GradeReportPreview,
    GradeReportPreviewRequest,
    GradeReportPreviewRow,
    grade_report_preview_to_json_bytes,
)
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionRevision,
)
from meridian.reporting_snapshot_comparison import (
    compare_reporting_snapshot_to_current_observations,
    load_reporting_snapshot_for_comparison,
    reporting_snapshot_prior_grade_basis,
)
from meridian.reporting_snapshot_preview import (
    frozen_grade_report_preview_from_json_bytes,
)
from meridian.reporting_snapshot_record import (
    reporting_snapshot_build_request_from_preview_requests,
)
from meridian.reporting_snapshot_selection import select_reporting_snapshot
from meridian.reporting_snapshot_storage import write_reporting_definition_revision
from meridian.teacher_grade_override import (
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideReference,
)

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 9, 20, 20, 30, tzinfo=UTC)
SNAPSHOT_ID = "snapshot_integration_001"
DEFINITION_ID = "quarter_grade_report"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64

_STATE_RULES = (
    ("missing", "blocking"),
    ("pending", "blocking"),
    ("incomplete", "blocking"),
    ("excused", "exclude"),
    ("excluded", "exclude"),
    ("not_applicable", "exclude"),
    ("insufficient_evidence", "blocking"),
    ("unavailable", "blocking"),
    ("withdrawn", "exclude"),
    ("invalid", "blocking"),
    ("unresolved", "blocking"),
)


def _calendar() -> AcademicPeriodCalendar:
    return AcademicPeriodCalendar(
        schema_version=ACADEMIC_PERIOD_CALENDAR_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_CALENDAR_RECORD_TYPE,
        school_year=PERIOD.school_year,
        calendar_revision=1,
        created_at=NOW - timedelta(days=10),
        updated_at=NOW - timedelta(days=10),
        periods=(
            AcademicPeriod(
                period_id=PERIOD.period_id,
                period_type="quarter",
                label="Quarter 1",
                start_date=date(2026, 9, 7),
                end_date=date(2026, 11, 6),
                parent_period_id=None,
                sequence=1,
                lifecycle="active",
            ),
        ),
    )


def _definition() -> ReportingDefinitionRevision:
    return ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=CLASS_ID,
        definition_id=DEFINITION_ID,
        definition_revision=1,
        supersedes_revision=None,
        report_kind="grade_report",
        purpose="quarter_grade_review",
        title="Quarter Grade Report",
        target_period=PERIOD,
        intended_audience="teacher",
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW - timedelta(minutes=10),
    )


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "classes" / CLASS_ID).mkdir(parents=True)
    write_academic_period_calendar(
        root,
        _calendar(),
        expected_current_revision=None,
    )
    return root


def _target(student_id: str = "student_001") -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=student_id,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="conventional",
    )


def _source_result(student_id: str) -> GradeOverrideSourceResultReference:
    return GradeOverrideSourceResultReference(
        "conventional",
        ConventionalGradeResultReference(
            class_id=CLASS_ID,
            student_id=student_id,
            school_year=PERIOD.school_year,
            period_id=PERIOD.period_id,
            calendar_revision=1,
            result_revision=1,
            result_sha256=SHA_A,
        ),
    )


def _policy_explanation() -> GradePreviewPolicyExplanation:
    return GradePreviewPolicyExplanation(
        activation_reference=GradePolicyActivationReference(
            CLASS_ID,
            PERIOD.school_year,
            PERIOD.period_id,
            1,
            SHA_D,
        ),
        policy_reference=GradePolicyReference(
            CLASS_ID,
            "course_grade",
            1,
            SHA_E,
        ),
        title="Course Grade",
        calculation_family="conventional",
        policy_actor_kind="teacher",
        policy_actor_id="teacher_local",
        policy_rationale=None,
        policy_revised_at=NOW - timedelta(minutes=30),
        activation_actor_kind="teacher",
        activation_actor_id="teacher_local",
        activation_rationale=None,
        activation_decided_at=NOW - timedelta(minutes=20),
        state_treatment=tuple(
            GradePreviewStateTreatmentRule(state, consequence)
            for state, consequence in _STATE_RULES
        ),
        reassessment_selection_authority="v02_attempt_and_reassessment_state",
        reassessment_unresolved_handling="blocking",
        rounding=GradePreviewRoundingExplanation(
            quantum=Decimal("0.01"),
            mode="half_up",
            application_stage="final",
        ),
    )


def _report(
    student_id: str = "student_001",
) -> tuple[GradeReportPreview, GradePreviewObservation]:
    target = _target(student_id)
    source = _source_result(student_id)
    common = GradePreviewExplanation(
        target=target,
        base_result=GradePreviewBaseResultExplanation(
            source_result=source,
            algorithm_version="1",
            calculation_fingerprint=SHA_B,
            inputs_sha256=SHA_C,
            calculated_at=NOW - timedelta(minutes=5),
            unrounded_grade=Decimal("90"),
            rounded_grade=Decimal("90"),
        ),
        base_result_status="calculated",
        base_grade=Decimal("90"),
        base_freshness_status="current",
        base_freshness_reasons=(),
        policy=_policy_explanation(),
        selected_override=None,
        override_applicability="no_override",
        override_reasons=("no_selected_override",),
        effective_grade=Decimal("90"),
        effective_source="base",
    )
    explanation = ConventionalGradePreviewExplanation(
        common=common,
        mode="total_points",
        items=(),
        categories=(),
        formula=ConventionalGradeFormulaExplanation(
            mode="total_points",
            total_earned=Decimal("90"),
            total_possible=Decimal("100"),
            final_fraction=Decimal("0.9"),
            unrounded_grade=Decimal("90"),
            rounded_grade=Decimal("90"),
        ),
        reasons=(),
    )
    observation = conventional_grade_observation(explanation)
    report = GradeReportPreview(
        (
            GradeReportPreviewRow(
                target=target,
                status="available",
                explanation=explanation,
                observation=observation,
                unavailable_reason=None,
            ),
        )
    )
    return report, observation


def _prepared(root: Path):
    stored_definition = write_reporting_definition_revision(root, _definition()).stored
    report, observation = _report()
    request = GradeReportPreviewRequest(_target(), work_evidence=())
    build = reporting_snapshot_build_request_from_preview_requests(
        definition_reference=stored_definition.reference,
        requests=(request,),
        actor=ReportingActor("teacher", "teacher_local"),
        requested_at=NOW,
        rationale="Freeze reviewed report.",
    )
    strict = frozen_grade_report_preview_from_json_bytes(
        grade_report_preview_to_json_bytes(report)
    )
    assert strict.rows[0].observation == observation
    return stored_definition, report, observation, request, build


def _freeze(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    definition, report, observation, request, build = _prepared(root)
    monkeypatch.setattr(
        freeze_module,
        "explain_grade_report_preview",
        lambda *args, **kwargs: report,
    )
    stored = freeze_module.freeze_reporting_snapshot(
        root,
        snapshot_id=SNAPSHOT_ID,
        build_request=build,
        preview_requests=(request,),
        created_at=NOW + timedelta(minutes=1),
    )
    return definition, stored, observation


def _replace_basis(
    observation: GradePreviewObservation,
    dimension: str,
    digest: str,
) -> GradePreviewObservation:
    changed = False
    entries: list[GradePreviewBasisEntry] = []
    for entry in observation.basis_entries:
        if entry.dimension == dimension:
            entries.append(replace(entry, sha256=digest))
            changed = True
        else:
            entries.append(entry)
    assert changed, dimension
    return replace(
        observation,
        basis_entries=tuple(entries),
        inputs_sha256="6" * 64,
        calculation_fingerprint="7" * 64,
    )


def _policy_changed(observation: GradePreviewObservation) -> GradePreviewObservation:
    entries = tuple(
        replace(entry, sha256=("8" if entry.dimension == "activation" else "9") * 64)
        if entry.dimension in {"activation", "policy"}
        else entry
        for entry in observation.basis_entries
    )
    return replace(
        observation,
        activation_reference=GradePolicyActivationReference(
            CLASS_ID,
            PERIOD.school_year,
            PERIOD.period_id,
            2,
            "8" * 64,
        ),
        policy_reference=GradePolicyReference(
            CLASS_ID,
            "course_grade",
            2,
            "9" * 64,
        ),
        basis_entries=entries,
        inputs_sha256="6" * 64,
        calculation_fingerprint="7" * 64,
    )


def _override_changed(
    observation: GradePreviewObservation,
) -> GradePreviewObservation:
    reference = TeacherGradeOverrideReference(
        class_id=CLASS_ID,
        student_id=observation.target.student_id,
        school_year=PERIOD.school_year,
        period_id=PERIOD.period_id,
        calendar_revision=1,
        calculation_family="conventional",
        override_revision=1,
        override_sha256="9" * 64,
    )
    return replace(
        observation,
        selected_override_reference=reference,
        override_applicability="applicable",
        override_replacement_grade=Decimal("95"),
        effective_grade=Decimal("95"),
        effective_source="override",
    )


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _install_audit_sentinels(root: Path) -> dict[str, str]:
    members = {
        "core": root / "settings" / "audit" / "core_state.json",
        "producer": (
            root
            / "classes"
            / CLASS_ID
            / "modules"
            / "scoreform"
            / "audit"
            / "producer_state.json"
        ),
        "grade_items": (
            root
            / "classes"
            / CLASS_ID
            / "modules"
            / "meridian"
            / "grade_items"
            / "audit.json"
        ),
        "decision_state": (
            root
            / "classes"
            / CLASS_ID
            / "modules"
            / "meridian"
            / "evidence_eligibility"
            / "audit.json"
        ),
        "proficiency_state": (
            root
            / "classes"
            / CLASS_ID
            / "modules"
            / "meridian"
            / "academic_period_proficiency"
            / "audit.json"
        ),
        "grade_policy": (
            root
            / "classes"
            / CLASS_ID
            / "modules"
            / "meridian"
            / "grade_policies"
            / "audit.json"
        ),
        "grade_result": (
            root
            / "classes"
            / CLASS_ID
            / "modules"
            / "meridian"
            / "conventional_grade_results"
            / "audit.json"
        ),
        "override_state": (
            root
            / "classes"
            / CLASS_ID
            / "modules"
            / "meridian"
            / "teacher_grade_overrides"
            / "audit.json"
        ),
    }
    for label, path in members.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"audit": label}, sort_keys=True) + "\n"
        path.write_text(payload, encoding="utf-8")
    return {
        label: hashlib.sha256(path.read_bytes()).hexdigest()
        for label, path in members.items()
    }


def test_real_snapshot_reload_adapts_through_existing_comparison_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    _, stored, observation = _freeze(root, monkeypatch)

    loaded = load_reporting_snapshot_for_comparison(root, stored.reference)
    assert loaded.content == stored.content
    prior = reporting_snapshot_prior_grade_basis(loaded.snapshot, observation.target)
    assert prior is not None
    assert prior.observation == observation

    unchanged = compare_reporting_snapshot_to_current_observations(
        loaded.snapshot,
        (observation,),
    )
    assert len(unchanged) == 1
    assert unchanged[0].relationship == "comparable"
    assert unchanged[0].changed is False
    assert unchanged[0].reasons == ()
    assert unchanged[0].effective_grade_delta == Decimal("0")

    effective_changed = replace(
        observation,
        base_grade=Decimal("91"),
        effective_grade=Decimal("91"),
    )
    policy_changed = _policy_changed(observation)
    weighting_changed = _replace_basis(observation, "weighting", "1" * 64)
    evidence_changed = _replace_basis(observation, "evidence", "2" * 64)
    override_changed = _override_changed(observation)
    freshness_changed = replace(
        observation,
        base_freshness_status="stale",
        base_freshness_reasons=("inputs_changed",),
        effective_grade=None,
        effective_source="none",
    )

    cases = (
        (effective_changed, "effective_grade_changed"),
        (policy_changed, "policy_changed"),
        (weighting_changed, "weighting_changed"),
        (evidence_changed, "evidence_or_proficiency_basis_changed"),
        (override_changed, "override_changed"),
        (freshness_changed, "freshness_changed"),
    )
    for current, expected_reason in cases:
        comparison = compare_reporting_snapshot_to_current_observations(
            loaded.snapshot,
            (current,),
        )
        assert len(comparison) == 1
        assert comparison[0].relationship == "comparable"
        assert comparison[0].changed is True
        assert expected_reason in comparison[0].reasons

    _, second_observation = _report("student_002")
    membership = compare_reporting_snapshot_to_current_observations(
        loaded.snapshot,
        (second_observation,),
    )
    assert {(item.relationship, item.changed) for item in membership} == {
        ("new", True),
        ("removed", True),
    }


def test_freeze_mutates_only_reporting_snapshot_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    _, report, _, request, build = _prepared(root)
    sentinel_hashes = _install_audit_sentinels(root)
    before = _file_hashes(root)

    monkeypatch.setattr(
        freeze_module,
        "explain_grade_report_preview",
        lambda *args, **kwargs: report,
    )
    stored = freeze_module.freeze_reporting_snapshot(
        root,
        snapshot_id=SNAPSHOT_ID,
        build_request=build,
        preview_requests=(request,),
        created_at=NOW + timedelta(minutes=1),
    )

    after = _file_hashes(root)
    for relative, digest in before.items():
        assert after[relative] == digest, relative

    new_files = set(after) - set(before)
    expected_json = stored.relative_path
    assert new_files == {expected_json, f"{expected_json}.sha256"}

    observed_sentinels = {
        "core": "settings/audit/core_state.json",
        "producer": f"classes/{CLASS_ID}/modules/scoreform/audit/producer_state.json",
        "grade_items": f"classes/{CLASS_ID}/modules/meridian/grade_items/audit.json",
        "decision_state": (
            f"classes/{CLASS_ID}/modules/meridian/evidence_eligibility/audit.json"
        ),
        "proficiency_state": (
            f"classes/{CLASS_ID}/modules/meridian/"
            "academic_period_proficiency/audit.json"
        ),
        "grade_policy": (
            f"classes/{CLASS_ID}/modules/meridian/grade_policies/audit.json"
        ),
        "grade_result": (
            f"classes/{CLASS_ID}/modules/meridian/conventional_grade_results/audit.json"
        ),
        "override_state": (
            f"classes/{CLASS_ID}/modules/meridian/teacher_grade_overrides/audit.json"
        ),
    }
    for label, relative in observed_sentinels.items():
        assert after[relative] == sentinel_hashes[label]


def test_fresh_process_reloads_definition_snapshot_observation_comparison_and_selector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    definition, stored, observation = _freeze(root, monkeypatch)
    selection = select_reporting_snapshot(
        root,
        stored.reference,
        actor=ReportingActor("teacher", "teacher_local"),
        rationale="Use reviewed snapshot.",
        decided_at=NOW + timedelta(minutes=2),
        expected_current=None,
    )
    assert selection.selection.selection.snapshot_reference == stored.reference

    observation_path = tmp_path / "current_observation.json"
    observation_path.write_bytes(grade_preview_observation_to_json_bytes(observation))

    program = r'''
import json
import sys
from pathlib import Path
from pds_core.academic_periods import AcademicPeriodRef
from meridian.grade_preview_explanation import grade_preview_observation_sha256
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_comparison import (
    compare_reporting_snapshot_reference_to_current_observations,
    load_reporting_snapshot_for_comparison,
    reporting_snapshot_prior_grade_bases,
)
from meridian.reporting_snapshot_preview import (
    grade_preview_observation_from_json_bytes,
)
from meridian.reporting_snapshot_selection import (
    load_current_reporting_snapshot_selection,
)
from meridian.reporting_snapshot_storage import load_reporting_definition_revision

root = Path(sys.argv[1])
class_id = sys.argv[2]
snapshot_id = sys.argv[3]
snapshot_sha256 = sys.argv[4]
definition_id = sys.argv[5]
definition_revision = int(sys.argv[6])
school_year = sys.argv[7]
period_id = sys.argv[8]
calendar_revision = int(sys.argv[9])
observation_path = Path(sys.argv[10])
reference = ReportingSnapshotReference(class_id, snapshot_id, snapshot_sha256)
definition = load_reporting_definition_revision(
    root, class_id, definition_id, definition_revision
)
stored = load_reporting_snapshot_for_comparison(root, reference)
bases = reporting_snapshot_prior_grade_bases(stored.snapshot)
current = grade_preview_observation_from_json_bytes(observation_path.read_bytes())
comparisons = compare_reporting_snapshot_reference_to_current_observations(
    root, reference, (current,)
)
selection = load_current_reporting_snapshot_selection(
    root,
    class_id,
    definition_id,
    AcademicPeriodRef(school_year, period_id),
    calendar_revision,
)
assert selection is not None
print(json.dumps({
    "definition_sha256": definition.reference.definition_sha256,
    "snapshot_sha256": stored.snapshot_sha256,
    "row_status": stored.snapshot.report_preview.rows[0].status,
    "prior_observation_sha256": grade_preview_observation_sha256(bases[0].observation),
    "comparison_relationship": comparisons[0].relationship,
    "comparison_changed": comparisons[0].changed,
    "selected_snapshot_id": selection.selection.snapshot_reference.snapshot_id,
}, sort_keys=True))
'''
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(root),
            CLASS_ID,
            stored.snapshot.snapshot_id,
            stored.snapshot_sha256,
            DEFINITION_ID,
            "1",
            PERIOD.school_year,
            PERIOD.period_id,
            "1",
            str(observation_path),
        ],
        cwd=Path.cwd(),
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {
        "comparison_changed": False,
        "comparison_relationship": "comparable",
        "definition_sha256": definition.reference.definition_sha256,
        "prior_observation_sha256": hashlib.sha256(
            grade_preview_observation_to_json_bytes(observation)
        ).hexdigest(),
        "row_status": "available",
        "selected_snapshot_id": SNAPSHOT_ID,
        "snapshot_sha256": stored.snapshot_sha256,
    }
