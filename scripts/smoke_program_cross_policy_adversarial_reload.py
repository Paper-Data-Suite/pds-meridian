"""Fresh-process reload for Issue #60 installed cross-policy acceptance."""

from __future__ import annotations

import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import smoke_program_cross_policy_adversarial as issue60  # type: ignore
import smoke_program_grade_report_preview as issue54  # type: ignore[import-not-found]
import smoke_program_grade_report_preview_reload as issue54_reload  # type: ignore
from concord.pds_publication import (
    get_publication_producer_profile as concord_profile,
)
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.publication_compatibility import PublicationProducerRegistry

from meridian.adapters import AdapterRegistry
from meridian.concord_adapter import ConcordAcademicResultAdapter
from meridian.conventional_grade import calculate_conventional_grade
from meridian.conventional_grade_storage import (
    load_current_conventional_grade_result,
)
from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.grade_report_preview import GradeReportPreviewRequest
from meridian.hybrid_grade import calculate_hybrid_grade
from meridian.hybrid_grade_storage import load_current_hybrid_grade_result
from meridian.projection_cache import load_authorized_projection_snapshot
from meridian.reporting_snapshot_storage import load_reporting_snapshot
from meridian.standards_grade import calculate_standards_grade
from meridian.standards_grade_storage import load_current_standards_grade_result
from meridian.teacher_grade_override_storage import (
    list_teacher_grade_override_revisions,
    load_current_teacher_grade_override,
    load_teacher_grade_override_revision,
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


def _period(data: dict[str, Any]) -> AcademicPeriodRef:
    return AcademicPeriodRef(
        _text(data.get("school_year"), "school_year missing"),
        _text(data.get("period_id"), "period_id missing"),
    )


def _verify_result(stored: Any, expected: dict[str, Any]) -> None:
    _require(stored is not None, "Selected Grade result did not reload.")
    result = _mapping(expected.get("result"), "result baseline missing")
    _require(
        stored.snapshot.result_revision
        == _integer(result.get("revision"), "result revision missing"),
        "Selected result revision changed on fresh reload.",
    )
    _require(
        stored.reference.result_sha256
        == _text(result.get("sha256"), "result digest missing"),
        "Selected result digest changed on fresh reload.",
    )
    _require(
        stored.snapshot.calculation_fingerprint
        == _text(result.get("fingerprint"), "result fingerprint missing"),
        "Selected result fingerprint changed on fresh reload.",
    )
    _require(
        str(stored.snapshot.outcome.rounded_grade)
        == _text(result.get("rounded_grade"), "rounded Grade missing"),
        "Selected result Grade changed on fresh reload.",
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: smoke_program_cross_policy_adversarial_reload.py <root>"
        )
    issue60._verify_installed()
    root = Path(sys.argv[1]).resolve()
    baseline = _mapping(
        json.loads((root / issue60.BASELINE_NAME).read_text(encoding="utf-8")),
        "Issue #60 baseline must be an object.",
    )

    workspaces = tuple(
        root
        / _text(
            _mapping(baseline.get(key), f"{key} missing").get("workspace"),
            "workspace missing",
        )
        for key in ("conventional", "weighted", "profile", "hybrid", "concord")
    )
    before = {path.name: issue54._tree_digest(path) for path in workspaces}

    conventional = _mapping(
        baseline.get("conventional"),
        "conventional missing",
    )
    conventional_workspace = root / _text(
        conventional.get("workspace"),
        "conventional workspace missing",
    )
    conventional_period = _period(conventional)
    conventional_current = load_current_conventional_grade_result(
        conventional_workspace,
        _text(conventional.get("class_id"), "conventional class missing"),
        _text(conventional.get("student_id"), "conventional student missing"),
        conventional_period,
        _integer(conventional.get("calendar_revision"), "calendar missing"),
    )
    _verify_result(conventional_current, conventional)
    assert conventional_current is not None
    _require(
        calculate_conventional_grade(conventional_current.snapshot.inputs)
        == conventional_current.snapshot.outcome,
        "Fresh-process conventional Grade does not reproduce.",
    )

    override_data = _mapping(
        conventional.get("override"),
        "override baseline missing",
    )
    selected_override = load_current_teacher_grade_override(
        conventional_workspace,
        conventional_current.snapshot.class_id,
        conventional_current.snapshot.student_id,
        conventional_period,
        conventional_current.snapshot.calendar_revision,
        "conventional",
    )
    _require(selected_override is not None, "Selected withdrawal did not reload.")
    assert selected_override is not None
    _require(
        selected_override.decision.decision == "withdraw",
        "Fresh-process override state is not selected withdrawal.",
    )
    _require(
        selected_override.reference.override_revision
        == _integer(
            override_data.get("withdrawal_revision"),
            "withdrawal revision missing",
        ),
        "Selected withdrawal revision changed.",
    )
    _require(
        selected_override.reference.override_sha256
        == _text(
            override_data.get("withdrawal_sha256"),
            "withdrawal digest missing",
        ),
        "Selected withdrawal digest changed.",
    )
    revisions = list_teacher_grade_override_revisions(
        conventional_workspace,
        conventional_current.snapshot.class_id,
        conventional_current.snapshot.student_id,
        conventional_period,
        conventional_current.snapshot.calendar_revision,
        "conventional",
    )
    _require(revisions == (1, 2), "Override lifecycle history changed.")
    active = load_teacher_grade_override_revision(
        conventional_workspace,
        conventional_current.snapshot.class_id,
        conventional_current.snapshot.student_id,
        conventional_period,
        conventional_current.snapshot.calendar_revision,
        "conventional",
        _integer(
            override_data.get("active_revision"),
            "active revision missing",
        ),
    )
    _require(
        active.override_sha256
        == _text(override_data.get("active_sha256"), "active digest missing"),
        "Historical active override changed after withdrawal.",
    )
    conventional_evidence = issue54_reload._authorized_evidence(
        conventional_workspace,
        _mapping(
            conventional.get("evidence"),
            "conventional evidence missing",
        ),
    )
    preview = issue54.explain_current_grade_preview(
        conventional_workspace,
        GradePreviewTarget(
            conventional_current.snapshot.class_id,
            conventional_current.snapshot.student_id,
            conventional_period,
            conventional_current.snapshot.calendar_revision,
            "conventional",
        ),
        work_evidence=conventional_evidence,
    )
    observation = issue54.conventional_grade_observation(preview)
    _require(
        observation.effective_source == "base"
        and observation.effective_grade == observation.base_grade,
        "Fresh-process selected withdrawal did not preserve base precedence.",
    )

    weighted = _mapping(baseline.get("weighted"), "weighted missing")
    weighted_workspace = root / _text(
        weighted.get("workspace"),
        "weighted workspace missing",
    )
    weighted_period = _period(weighted)
    weighted_current = load_current_standards_grade_result(
        weighted_workspace,
        _text(weighted.get("class_id"), "weighted class missing"),
        _text(weighted.get("student_id"), "weighted student missing"),
        weighted_period,
        _integer(weighted.get("calendar_revision"), "weighted calendar missing"),
    )
    _verify_result(weighted_current, weighted)
    assert weighted_current is not None
    _require(
        weighted_current.snapshot.inputs.configuration.aggregation_strategy
        == "weighted_mean",
        "Fresh-process weighted standards strategy changed.",
    )
    _require(
        calculate_standards_grade(weighted_current.snapshot.inputs)
        == weighted_current.snapshot.outcome,
        "Fresh-process weighted standards Grade does not reproduce.",
    )

    profile = _mapping(baseline.get("profile"), "profile missing")
    profile_workspace = root / _text(
        profile.get("workspace"),
        "profile workspace missing",
    )
    profile_period = _period(profile)
    profile_current = load_current_standards_grade_result(
        profile_workspace,
        _text(profile.get("class_id"), "profile class missing"),
        _text(profile.get("student_id"), "profile student missing"),
        profile_period,
        _integer(profile.get("calendar_revision"), "profile calendar missing"),
    )
    _verify_result(profile_current, profile)
    assert profile_current is not None
    profile_outcome = profile_current.snapshot.outcome
    _require(
        profile_current.snapshot.inputs.configuration.aggregation_strategy
        == "profile_constrained_mean",
        "Fresh-process profile strategy changed.",
    )
    _require(
        profile_outcome.base_unrounded_grade == Decimal("90")
        and profile_outcome.selected_profile_band_id == "high"
        and profile_outcome.profile_adjustment == "floor"
        and profile_outcome.unrounded_grade == Decimal("95")
        and profile_outcome.rounded_grade == Decimal("95.00"),
        "Fresh-process profile evidence changed.",
    )
    _require(
        profile_current.snapshot.inputs.target_scale_definition is not None,
        "Fresh-process profile exact scale authority was lost.",
    )
    _require(
        calculate_standards_grade(profile_current.snapshot.inputs)
        == profile_outcome,
        "Fresh-process profile Grade does not reproduce.",
    )

    hybrid = _mapping(baseline.get("hybrid"), "hybrid missing")
    hybrid_workspace = root / _text(
        hybrid.get("workspace"),
        "hybrid workspace missing",
    )
    hybrid_period = _period(hybrid)
    hybrid_current = load_current_hybrid_grade_result(
        hybrid_workspace,
        _text(hybrid.get("class_id"), "hybrid class missing"),
        _text(hybrid.get("student_id"), "hybrid student missing"),
        hybrid_period,
        _integer(hybrid.get("calendar_revision"), "hybrid calendar missing"),
    )
    _verify_result(hybrid_current, hybrid)
    assert hybrid_current is not None
    _require(
        calculate_hybrid_grade(hybrid_current.snapshot.inputs)
        == hybrid_current.snapshot.outcome,
        "Fresh-process hybrid Grade does not reproduce.",
    )

    snapshot_data = _mapping(
        hybrid.get("snapshot"),
        "snapshot baseline missing",
    )
    snapshot = load_reporting_snapshot(
        hybrid_workspace,
        hybrid_current.snapshot.class_id,
        _text(snapshot_data.get("snapshot_id"), "snapshot id missing"),
    )
    _require(
        snapshot.snapshot_sha256
        == _text(snapshot_data.get("snapshot_sha256"), "snapshot digest missing"),
        "Fresh-process ReportingSnapshot digest changed.",
    )
    _require(
        hashlib.sha256(snapshot.content).hexdigest() == snapshot.snapshot_sha256,
        "Fresh-process ReportingSnapshot bytes fail digest verification.",
    )
    _require(
        snapshot.snapshot.payload_sha256
        == _text(snapshot_data.get("payload_sha256"), "payload digest missing"),
        "Fresh-process ReportingSnapshot payload digest changed.",
    )
    _require(
        snapshot.snapshot.report_preview_sha256
        == _text(
            snapshot_data.get("report_preview_sha256"),
            "report preview digest missing",
        ),
        "Fresh-process ReportingSnapshot preview digest changed.",
    )

    hybrid_evidence = issue54_reload._authorized_evidence(
        hybrid_workspace,
        _mapping(hybrid.get("evidence"), "hybrid evidence missing"),
    )
    current_report = issue54.explain_grade_report_preview(
        hybrid_workspace,
        (
            GradeReportPreviewRequest(
                GradePreviewTarget(
                    hybrid_current.snapshot.class_id,
                    hybrid_current.snapshot.student_id,
                    hybrid_period,
                    hybrid_current.snapshot.calendar_revision,
                    "hybrid",
                ),
                work_evidence=hybrid_evidence,
            ),
        ),
    )
    _require(
        current_report.summary.available_count == 1,
        "Fresh-process hybrid report preview became unavailable.",
    )

    concord = _mapping(baseline.get("concord"), "concord missing")
    concord_workspace = root / _text(
        concord.get("workspace"),
        "concord workspace missing",
    )
    manifest_path = concord_workspace.joinpath(
        *_text(
            concord.get("manifest_path"),
            "Concord manifest path missing",
        ).split("/")
    )
    _require(
        hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        == _text(
            concord.get("manifest_sha256"),
            "Concord manifest digest missing",
        ),
        "Fresh-process Concord source manifest changed.",
    )
    authorized = load_authorized_projection_snapshot(
        concord_workspace,
        _text(concord.get("publication_id"), "Concord publication missing"),
        _text(concord.get("cache_key"), "Concord cache key missing"),
        authorizer=issue54.issue45.AllowInstalledProjection(),
        authorization_purpose_id="grading_import",
        requested_student_ids=(
            _text(concord.get("student_id"), "Concord student missing"),
        ),
        producer_registry=PublicationProducerRegistry((concord_profile(),)),
        adapter_registry=AdapterRegistry((ConcordAcademicResultAdapter(),)),
        distribution_version_resolver=(
            issue54.issue45.installed_distribution_version
        ),
    )
    _require(
        authorized.stored.snapshot_digest
        == _text(
            concord.get("snapshot_digest"),
            "Concord snapshot digest missing",
        ),
        "Fresh-process Concord projection digest changed.",
    )
    cached_items = authorized.stored.snapshot.inventory.items
    group_item_id = _text(
        concord.get("group_item_id"),
        "Concord group item missing",
    )
    _require(
        all(item.target.target_kind != "concord_group" for item in cached_items),
        "Student-scoped Concord cache retained nonstudent group evidence.",
    )
    _require(
        all(item.item_id != group_item_id for item in cached_items),
        "Known Concord group item leaked into student-scoped cache.",
    )
    _require(
        all(
            item.subject is not None
            and item.subject.student_id
            == _text(concord.get("student_id"), "Concord student missing")
            for item in cached_items
        ),
        "Student-scoped Concord cache contains evidence outside its subject scope.",
    )

    after = {path.name: issue54._tree_digest(path) for path in workspaces}
    _require(
        after == before,
        "Issue #60 fresh-process reload mutated workspace state.",
    )
    print("Issue #60 fresh-process installed cross-policy reload passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
