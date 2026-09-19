"""Fresh-process issue #54 Grade/report preview reproduction."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, cast

import smoke_program_conventional_grade as issue50  # type: ignore[import-not-found]
import smoke_program_grade_report_preview as issue54  # type: ignore[import-not-found]
import smoke_program_hybrid_grade as issue52  # type: ignore[import-not-found]
import smoke_program_proficiency_signal_export as issue45  # type: ignore
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.routing_models import ModuleWorkRef

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


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _mapping(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(message)
    return cast(dict[str, Any], value)


def _text(value: object, message: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(message)
    return value


def _integer(value: object, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(message)
    return value


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


def _authorized_evidence(
    workspace: Path,
    descriptor: dict[str, Any],
) -> tuple[ConventionalGradeWorkEvidenceSpec, ...]:
    publication_id = _text(descriptor.get("publication_id"), "publication_id missing")
    cache_key = _text(descriptor.get("cache_key"), "cache_key missing")
    module_id = _text(descriptor.get("module_id"), "module_id missing")
    class_id = _text(descriptor.get("class_id"), "class_id missing")
    work_id = _text(descriptor.get("work_id"), "work_id missing")
    grade_item_id = _text(descriptor.get("grade_item_id"), "grade_item_id missing")
    authorization_profile = _text(
        descriptor.get("authorization_profile"),
        "authorization_profile missing",
    )
    raw_student_ids = descriptor.get("requested_student_ids")
    if not isinstance(raw_student_ids, list) or not raw_student_ids:
        raise RuntimeError("requested_student_ids missing")
    requested_student_ids = tuple(
        _text(value, "requested_student_ids contains a non-string")
        for value in raw_student_ids
    )

    if authorization_profile == "issue50":
        authorizer = issue50.AllowProjection()
        producer_registry = issue50.PublicationProducerRegistry(
            (issue50.get_publication_producer_profile(),)
        )
        adapter_registry = issue50.AdapterRegistry(
            (issue50.ScoreFormAcademicResultAdapter(),)
        )
    elif authorization_profile == "issue45":
        authorizer = issue45.AllowInstalledProjection()
        producer_registry = issue45._producer_registry()
        adapter_registry = issue45._adapter_registry()
    else:
        raise RuntimeError("unsupported authorization_profile")

    authorized = issue50.load_authorized_projection_snapshot(
        workspace,
        publication_id,
        cache_key,
        authorizer=authorizer,
        authorization_purpose_id="grading_import",
        requested_student_ids=requested_student_ids,
        producer_registry=producer_registry,
        adapter_registry=adapter_registry,
        distribution_version_resolver=issue50.installed_distribution_version,
    )
    return (
        ConventionalGradeWorkEvidenceSpec(
            grade_item_id=grade_item_id,
            work=ModuleWorkRef(module_id, class_id, work_id),
            status="available",
            authorized_snapshots=(authorized,),
        ),
    )


def _encoded(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_program_grade_report_preview_reload.py <root>")
    issue54._verify_installed_composition()
    _require(metadata.version("pds-concord") == "0.3.0", "Concord version changed.")
    root = Path(sys.argv[1]).resolve()
    baseline = _mapping(
        json.loads((root / issue54.BASELINE_NAME).read_text(encoding="utf-8")),
        "Issue #54 baseline must be an object.",
    )
    workspaces = _mapping(baseline.get("workspaces"), "workspace map missing")
    expected_digests = _mapping(
        baseline.get("workspace_digests"),
        "workspace digests missing",
    )
    observations = _mapping(baseline.get("observations"), "observations missing")
    conventional_workspace = root / _text(
        workspaces.get("conventional"),
        "conventional workspace missing",
    )
    standards_workspace = root / _text(
        workspaces.get("standards"),
        "standards workspace missing",
    )
    hybrid_workspace = root / _text(
        workspaces.get("hybrid"),
        "hybrid workspace missing",
    )

    before = {
        "conventional": _tree_digest(conventional_workspace),
        "standards": _tree_digest(standards_workspace),
        "hybrid": _tree_digest(hybrid_workspace),
    }
    _require(before == expected_digests, "Workspace changed before fresh reload.")

    conventional_evidence = _authorized_evidence(
        conventional_workspace,
        _mapping(baseline.get("conventional_evidence"), "evidence missing"),
    )
    hybrid_evidence = _authorized_evidence(
        hybrid_workspace,
        _mapping(baseline.get("hybrid_evidence"), "hybrid evidence missing"),
    )

    conventional_target = GradePreviewTarget(
        issue50.CLASS_ID,
        issue50.STUDENT_ID,
        issue50.PERIOD,
        1,
        "conventional",
    )
    standards_target_data = _mapping(
        baseline.get("standards_target"),
        "standards target missing",
    )
    standards_target = GradePreviewTarget(
        _text(standards_target_data.get("class_id"), "standards class missing"),
        _text(
            standards_target_data.get("student_id"),
            "standards student missing",
        ),
        AcademicPeriodRef(
            _text(
                standards_target_data.get("school_year"),
                "standards school year missing",
            ),
            _text(
                standards_target_data.get("period_id"),
                "standards period missing",
            ),
        ),
        _integer(
            standards_target_data.get("calendar_revision"),
            "standards calendar revision missing",
        ),
        "standards_based",
    )
    hybrid_target = GradePreviewTarget(
        issue52.CLASS_ID,
        issue52.STUDENT_ID,
        issue52.PERIOD,
        issue52.CALENDAR_REVISION,
        "hybrid",
    )

    conventional_explanation = explain_current_grade_preview(
        conventional_workspace,
        conventional_target,
        work_evidence=conventional_evidence,
    )
    standards_explanation = explain_current_grade_preview(
        standards_workspace,
        standards_target,
    )
    hybrid_explanation = explain_current_grade_preview(
        hybrid_workspace,
        hybrid_target,
        work_evidence=hybrid_evidence,
    )
    _require(
        isinstance(conventional_explanation, ConventionalGradePreviewExplanation),
        "Fresh conventional preview returned the wrong family projection.",
    )
    _require(
        isinstance(standards_explanation, StandardsGradePreviewExplanation),
        "Fresh standards preview returned the wrong family projection.",
    )
    _require(
        isinstance(hybrid_explanation, HybridGradePreviewExplanation),
        "Fresh hybrid preview returned the wrong family projection.",
    )
    assert isinstance(conventional_explanation, ConventionalGradePreviewExplanation)
    assert isinstance(standards_explanation, StandardsGradePreviewExplanation)
    assert isinstance(hybrid_explanation, HybridGradePreviewExplanation)
    conventional = conventional_grade_observation(conventional_explanation)
    standards = standards_grade_observation(standards_explanation)
    hybrid = hybrid_grade_observation(hybrid_explanation)
    actual_observations = {
        "conventional": _encoded(grade_preview_observation_to_json_bytes(conventional)),
        "standards": _encoded(grade_preview_observation_to_json_bytes(standards)),
        "hybrid": _encoded(grade_preview_observation_to_json_bytes(hybrid)),
    }
    _require(
        actual_observations == observations,
        "Fresh-process GradePreviewObservation changed.",
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
        _encoded(grade_report_preview_to_json_bytes(report))
        == _text(baseline.get("report"), "report baseline missing"),
        "Fresh-process report preview changed.",
    )
    comparison = compare_grade_preview_basis(
        conventional,
        prior_reporting_snapshot_grade_basis_from_observation(conventional),
    )
    _require(
        _encoded(grade_preview_comparison_to_json_bytes(comparison))
        == _text(baseline.get("comparison"), "comparison baseline missing"),
        "Fresh-process comparison changed.",
    )

    after = {
        "conventional": _tree_digest(conventional_workspace),
        "standards": _tree_digest(standards_workspace),
        "hybrid": _tree_digest(hybrid_workspace),
    }
    _require(after == before, "Fresh-process issue #54 preview wrote workspace state.")
    print("Issue #54 fresh-process Grade/report preview acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
