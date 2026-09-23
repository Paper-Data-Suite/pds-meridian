"""Create and explain real installed issue #54 Grade preview state."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import sys
from datetime import timedelta
from decimal import Decimal
from importlib import metadata
from pathlib import Path

import smoke_program_conventional_grade as issue50  # type: ignore[import-not-found]
import smoke_program_hybrid_grade as issue52  # type: ignore[import-not-found]
import smoke_program_proficiency_signal_export as issue45  # type: ignore
import smoke_program_standards_grade as issue51  # type: ignore[import-not-found]

import meridian
from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.conventional_grade_explanation import (
    ConventionalGradePreviewExplanation,
    conventional_grade_observation,
)
from meridian.current_grade_preview import explain_current_grade_preview
from meridian.grade_preview_comparison import (
    compare_grade_preview_basis,
    grade_preview_comparison_to_json_bytes,
    prior_reporting_snapshot_grade_basis_from_observation,
)
from meridian.grade_preview_explanation import (
    GradePreviewTarget,
    grade_preview_observation_to_json_bytes,
)
from meridian.grade_report_preview import (
    GradeReportPreviewRequest,
    explain_grade_report_preview,
    grade_report_preview_to_json_bytes,
)
from meridian.hybrid_grade_explanation import (
    HybridGradePreviewExplanation,
    hybrid_grade_observation,
)
from meridian.standards_grade_explanation import (
    StandardsGradePreviewExplanation,
    standards_grade_observation,
)
from meridian.teacher_grade_override_lifecycle import (
    commit_teacher_grade_override_selection_preview,
    preview_teacher_grade_override_selection,
)
from meridian.teacher_grade_override_workflow import (
    commit_teacher_grade_override_authoring_preview,
    preview_teacher_grade_override_authoring,
)

BASELINE_NAME = "issue54-grade-report-preview-baseline.json"
REPLACEMENT_GRADE = Decimal("105.25")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _installed_origin(module_name: str) -> None:
    module = importlib.import_module(module_name)
    raw = getattr(module, "__file__", None)
    _require(isinstance(raw, str) and bool(raw), f"{module_name} has no origin.")
    assert isinstance(raw, str)
    origin = Path(raw).resolve()
    prefix = Path(sys.prefix).resolve()
    _require(origin.is_relative_to(prefix), f"{module_name} is outside the venv.")
    _require(
        "site-packages" in {part.lower() for part in origin.parts},
        f"{module_name} is not installed from site-packages.",
    )


def _verify_installed_composition() -> None:
    expected = {
        "pds-core": "0.6.3",
        "scoreform": "0.11.0",
        "quillan": "0.10.1",
        "pds-concord": "0.3.0",
    }
    _require(metadata.version("pds-core") == "0.6.3", "Core version mismatch.")
    _require(
        metadata.version("scoreform") == "0.11.0",
        "ScoreForm version mismatch.",
    )
    _require(metadata.version("quillan") == "0.10.1", "Quillan version mismatch.")
    _require(
        metadata.version("pds-concord") == "0.3.0",
        "Concord version mismatch.",
    )
    for distribution, version in expected.items():
        _require(
            metadata.version(distribution) == version,
            f"{distribution} version mismatch.",
        )
    _require(
        meridian.__version__ == metadata.version("pds-meridian"),
        "Meridian module/distribution versions disagree.",
    )
    for module_name in (
        "pds_core",
        "scoreform",
        "quillan",
        "concord",
        "meridian",
        "meridian.grade_preview_explanation",
        "meridian.conventional_grade_explanation",
        "meridian.standards_grade_explanation",
        "meridian.hybrid_grade_explanation",
        "meridian.current_grade_preview",
        "meridian.grade_preview_comparison",
        "meridian.grade_report_preview",
    ):
        _installed_origin(module_name)


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _encoded(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _conventional_state(
    workspace: Path,
) -> tuple[
    issue50.ProducerBaseline,
    tuple[ConventionalGradeWorkEvidenceSpec, ...],
    dict[str, object],
]:
    issue50._seed_core_context(workspace)
    producer = issue50._publish(workspace)
    projected = issue50._project(workspace, producer)
    authorized = issue50._authorized(workspace, projected)
    work_evidence = issue50._configure(workspace, projected, authorized)
    assembly = issue50.assemble_conventional_grade_calculation(
        workspace,
        issue50.CLASS_ID,
        issue50.STUDENT_ID,
        issue50.PERIOD,
        1,
        work_evidence,
    )
    snapshot = issue50.create_conventional_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=issue50.NOW,
    )
    issue50.write_conventional_grade_result_revision(
        workspace,
        snapshot,
        work_evidence=work_evidence,
    )
    issue50.select_conventional_grade_result_revision(
        workspace,
        issue50.CLASS_ID,
        issue50.STUDENT_ID,
        issue50.PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )
    authored = commit_teacher_grade_override_authoring_preview(
        workspace,
        preview_teacher_grade_override_authoring(
            workspace,
            issue50.CLASS_ID,
            issue50.STUDENT_ID,
            issue50.PERIOD,
            1,
            "conventional",
            replacement_grade=REPLACEMENT_GRADE,
            actor_id=issue50.ACTOR_ID,
            rationale="Installed issue #54 preview override.",
            decided_at=issue50.NOW + timedelta(minutes=30),
            work_evidence=work_evidence,
        ),
    )
    commit_teacher_grade_override_selection_preview(
        workspace,
        preview_teacher_grade_override_selection(
            workspace,
            authored.stored_reference,
        ),
    )
    publication = projected.cached.stored.snapshot.source.publication
    work = publication.work
    descriptor = {
        "publication_id": publication.publication_id,
        "cache_key": projected.cached.stored.cache_key,
        "module_id": work.module_id,
        "class_id": work.class_id,
        "work_id": work.work_id,
        "grade_item_id": issue50.GRADE_ITEM_ID,
        "authorization_profile": "issue50",
        "requested_student_ids": [issue50.STUDENT_ID],
    }
    return producer, work_evidence, descriptor


def _standards_state(workspace: Path) -> GradePreviewTarget:
    library = issue45._seed_core_context(workspace)
    baselines = {
        "scoreform": issue45._publish_scoreform(workspace),
        "quillan": issue45._publish_quillan(workspace),
    }
    projected = issue45._project_and_cache(workspace, baselines)
    issue45._assert_projection_semantics(projected)
    grade_item, memberships, scale = issue45._calculate_grade_item_proficiency(
        workspace,
        baselines,
        projected,
        library,
    )
    issue45._calculate_academic_period_proficiency(
        workspace,
        grade_item,
        memberships,
        scale,
    )
    issue51.select_proficiency_scale_revision(
        workspace,
        scale.reference.class_id,
        scale.reference.scale_id,
        scale.reference.scale_revision,
        expected_current_scale_revision=None,
    )

    issue51.CLASS_ID = issue45.CLASS_ID
    issue51.STUDENT_ID = issue45.STUDENT_ID
    issue51.STANDARD_ID = issue45.STANDARD_ID
    issue51.SCHOOL_YEAR = issue45.SCHOOL_YEAR
    issue51.PERIOD_ID = issue45.PERIOD_ID
    issue51.CALENDAR_REVISION = 1
    issue51.PERIOD = issue45.AcademicPeriodRef(
        issue45.SCHOOL_YEAR,
        issue45.PERIOD_ID,
    )
    issue51._install_grade_policy(workspace, scale)

    assembly = issue51.assemble_standards_grade_calculation(
        workspace,
        issue51.CLASS_ID,
        issue51.STUDENT_ID,
        issue51.PERIOD,
        issue51.CALENDAR_REVISION,
    )
    _require(
        assembly.outcome.status == "calculated",
        "Provenance-complete standards Grade did not calculate.",
    )
    _require(
        assembly.outcome.rounded_grade == Decimal("90.00"),
        "Provenance-complete standards Grade value changed.",
    )
    snapshot = issue51.create_standards_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=issue51.NOW,
    )
    written = issue51.write_standards_grade_result_revision(workspace, snapshot)
    issue51.select_standards_grade_result_revision(
        workspace,
        issue51.CLASS_ID,
        issue51.STUDENT_ID,
        issue51.PERIOD,
        issue51.CALENDAR_REVISION,
        written.stored.snapshot.result_revision,
        expected_current_result_revision=None,
    )
    return GradePreviewTarget(
        issue45.CLASS_ID,
        issue45.STUDENT_ID,
        issue45.AcademicPeriodRef(issue45.SCHOOL_YEAR, issue45.PERIOD_ID),
        1,
        "standards_based",
    )


def _align_issue45_hybrid_scope() -> None:
    issue45.CLASS_ID = issue50.CLASS_ID
    issue45.STUDENT_ID = issue50.STUDENT_ID
    issue45.NONCONTRIBUTOR_ID = "issue54_hybrid_noncontributor"
    issue45.STANDARD_ID = issue50.STANDARD_ID
    issue45.SCHOOL_YEAR = issue50.SCHOOL_YEAR
    issue45.PERIOD_ID = issue50.PERIOD_ID


def _hybrid_state(
    workspace: Path,
) -> tuple[
    issue50.ProducerBaseline,
    tuple[ConventionalGradeWorkEvidenceSpec, ...],
    dict[str, object],
]:
    _align_issue45_hybrid_scope()
    library = issue45._seed_core_context(workspace)
    baselines = {
        "scoreform": issue45._publish_scoreform(workspace),
        "quillan": issue45._publish_quillan(workspace),
    }
    projected = issue45._project_and_cache(workspace, baselines)
    issue45._assert_projection_semantics(projected)

    scoreform_projection = issue50.CachedProjection(
        projected["scoreform"].prepared,
        projected["scoreform"].inventory,
        projected["scoreform"].cached,
    )
    authorized_scoreform = issue45._authorized_projection(
        workspace,
        projected["scoreform"],
    )
    work_evidence = issue50._configure(
        workspace,
        scoreform_projection,
        authorized_scoreform,
    )

    grade_item, memberships, scale = issue45._calculate_grade_item_proficiency(
        workspace,
        baselines,
        projected,
        library,
    )
    issue45._calculate_academic_period_proficiency(
        workspace,
        grade_item,
        memberships,
        scale,
    )
    issue51.select_proficiency_scale_revision(
        workspace,
        scale.reference.class_id,
        scale.reference.scale_id,
        scale.reference.scale_revision,
        expected_current_scale_revision=None,
    )

    issue52._install_hybrid_policy(workspace, scale)
    issue52._assert_no_standalone_grade_results(workspace)
    assembly = issue52.assemble_hybrid_grade_calculation(
        workspace,
        issue52.CLASS_ID,
        issue52.STUDENT_ID,
        issue52.PERIOD,
        issue52.CALENDAR_REVISION,
        work_evidence,
    )
    _require(
        assembly.outcome.status == "calculated",
        "Provenance-complete hybrid Grade did not calculate.",
    )
    _require(
        assembly.conventional.outcome.rounded_grade == Decimal("100.00"),
        "Provenance-complete hybrid conventional component changed.",
    )
    _require(
        assembly.standards_based.outcome.rounded_grade == Decimal("90.00"),
        "Provenance-complete hybrid standards component changed.",
    )
    _require(
        assembly.outcome.rounded_grade == Decimal("96.00"),
        "Provenance-complete hybrid Grade value changed.",
    )
    snapshot = issue52.create_hybrid_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=issue52.NOW,
    )
    written = issue52.write_hybrid_grade_result_revision(
        workspace,
        snapshot,
        work_evidence=work_evidence,
    )
    issue52.select_hybrid_grade_result_revision(
        workspace,
        issue52.CLASS_ID,
        issue52.STUDENT_ID,
        issue52.PERIOD,
        issue52.CALENDAR_REVISION,
        written.stored.snapshot.result_revision,
        expected_current_result_revision=None,
    )
    issue52._assert_no_standalone_grade_results(workspace)

    scoreform = baselines["scoreform"]
    producer = issue50.ProducerBaseline(
        native_files=scoreform.native_files,
        manifest_path=scoreform.manifest_path,
        manifest_bytes=scoreform.manifest_bytes,
        publication_id=scoreform.publication.publication_id,
    )
    publication = projected["scoreform"].cached.stored.snapshot.source.publication
    work = publication.work
    descriptor: dict[str, object] = {
        "publication_id": publication.publication_id,
        "cache_key": projected["scoreform"].cached.stored.cache_key,
        "module_id": work.module_id,
        "class_id": work.class_id,
        "work_id": work.work_id,
        "grade_item_id": issue50.GRADE_ITEM_ID,
        "authorization_profile": "issue45",
        "requested_student_ids": [
            issue45.STUDENT_ID,
            issue45.NONCONTRIBUTOR_ID,
        ],
    }
    return producer, work_evidence, descriptor


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_program_grade_report_preview.py <root>")
    _verify_installed_composition()
    root = Path(sys.argv[1]).resolve()
    conventional_workspace = root / "issue54-conventional"
    standards_workspace = root / "issue54-standards"
    hybrid_workspace = root / "issue54-hybrid"

    conventional_producer, conventional_evidence, conventional_descriptor = (
        _conventional_state(conventional_workspace)
    )
    standards_target = _standards_state(standards_workspace)
    hybrid_producer, hybrid_evidence, hybrid_descriptor = _hybrid_state(
        hybrid_workspace
    )

    before = {
        "conventional": _tree_digest(conventional_workspace),
        "standards": _tree_digest(standards_workspace),
        "hybrid": _tree_digest(hybrid_workspace),
    }

    conventional_target = GradePreviewTarget(
        issue50.CLASS_ID,
        issue50.STUDENT_ID,
        issue50.PERIOD,
        1,
        "conventional",
    )
    hybrid_target = GradePreviewTarget(
        issue52.CLASS_ID,
        issue52.STUDENT_ID,
        issue52.PERIOD,
        issue52.CALENDAR_REVISION,
        "hybrid",
    )

    conventional = explain_current_grade_preview(
        conventional_workspace,
        conventional_target,
        work_evidence=conventional_evidence,
    )
    standards = explain_current_grade_preview(standards_workspace, standards_target)
    hybrid = explain_current_grade_preview(
        hybrid_workspace,
        hybrid_target,
        work_evidence=hybrid_evidence,
    )

    _require(
        isinstance(conventional, ConventionalGradePreviewExplanation),
        "Conventional current preview returned the wrong family projection.",
    )
    _require(
        isinstance(standards, StandardsGradePreviewExplanation),
        "Standards current preview returned the wrong family projection.",
    )
    _require(
        isinstance(hybrid, HybridGradePreviewExplanation),
        "Hybrid current preview returned the wrong family projection.",
    )
    assert isinstance(conventional, ConventionalGradePreviewExplanation)
    assert isinstance(standards, StandardsGradePreviewExplanation)
    assert isinstance(hybrid, HybridGradePreviewExplanation)
    conventional_observation = conventional_grade_observation(conventional)
    standards_observation = standards_grade_observation(standards)
    hybrid_observation = hybrid_grade_observation(hybrid)
    _require(
        conventional_observation.base_grade == Decimal("100.00"),
        "Installed conventional base Grade changed.",
    )
    _require(
        conventional_observation.effective_grade == REPLACEMENT_GRADE
        and conventional_observation.effective_source == "override",
        "Installed applicable override was not explained exactly.",
    )
    _require(
        standards_observation.effective_source == "base",
        "Installed standards preview did not preserve base authority.",
    )
    _require(
        hybrid_observation.effective_source == "base",
        "Installed hybrid preview did not preserve base authority.",
    )

    report = explain_grade_report_preview(
        conventional_workspace,
        (
            GradeReportPreviewRequest(
                conventional_target,
                work_evidence=conventional_evidence,
            ),
        ),
    )
    _require(
        report.summary.requested_count == 1
        and report.summary.available_count == 1
        and report.summary.effective_override_count == 1,
        "Installed report-preview summary is incorrect.",
    )
    prior = prior_reporting_snapshot_grade_basis_from_observation(
        conventional_observation
    )
    comparison = compare_grade_preview_basis(conventional_observation, prior)
    _require(
        comparison.relationship == "comparable"
        and not comparison.changed
        and comparison.reasons == (),
        "Stable installed observation did not compare as unchanged.",
    )

    after = {
        "conventional": _tree_digest(conventional_workspace),
        "standards": _tree_digest(standards_workspace),
        "hybrid": _tree_digest(hybrid_workspace),
    }
    _require(before == after, "Issue #54 preview mutated academic workspace state.")
    issue50._assert_unchanged(conventional_producer)
    issue50._assert_unchanged(hybrid_producer)

    baseline = {
        "schema_version": "1",
        "workspaces": {
            "conventional": conventional_workspace.name,
            "standards": standards_workspace.name,
            "hybrid": hybrid_workspace.name,
        },
        "workspace_digests": after,
        "conventional_evidence": conventional_descriptor,
        "hybrid_evidence": hybrid_descriptor,
        "standards_target": {
            "class_id": standards_target.class_id,
            "student_id": standards_target.student_id,
            "school_year": standards_target.target_period.school_year,
            "period_id": standards_target.target_period.period_id,
            "calendar_revision": standards_target.calendar_revision,
        },
        "observations": {
            "conventional": _encoded(
                grade_preview_observation_to_json_bytes(conventional_observation)
            ),
            "standards": _encoded(
                grade_preview_observation_to_json_bytes(standards_observation)
            ),
            "hybrid": _encoded(
                grade_preview_observation_to_json_bytes(hybrid_observation)
            ),
        },
        "report": _encoded(grade_report_preview_to_json_bytes(report)),
        "comparison": _encoded(grade_preview_comparison_to_json_bytes(comparison)),
    }
    (root / BASELINE_NAME).write_text(
        json.dumps(baseline, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("Issue #54 installed Grade/report preview acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
