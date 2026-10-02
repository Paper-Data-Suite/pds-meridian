"""Exercise installed Issue #58 Grade/report attention boundaries."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import cast

import pds_core
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.module_operations import (
    ModuleAttentionReport,
    ModuleOperationsProfile,
    ModuleOperationsRequest,
    invoke_module_operations,
)
from pds_core.provider_diagnostics import (
    diagnose_core_providers,
    inspect_core_provider_entry_points,
)
from pds_core.routes import class_dir

import meridian
from meridian.attention_provider import project_meridian_attention_to_core
from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.pds_operations import get_module_operations_profile
from meridian.proficiency_attention import (
    MERIDIAN_ATTENTION_SCHEMA_VERSION,
    MeridianAttentionCode,
    MeridianAttentionItem,
    MeridianAttentionSummary,
    attention_definition,
    build_meridian_attention_summary,
    meridian_attention_summary_to_dict,
)
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionReference,
    ReportingDefinitionRevision,
    ReportingSnapshotPredecessor,
)
from meridian.reporting_snapshot_preview import (
    FrozenGradeReportPreview,
    frozen_grade_report_preview_from_json_bytes,
)
from meridian.reporting_snapshot_record import (
    REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
    ReportingSnapshot,
    ReportingSnapshotBuildRequest,
    ReportingSnapshotGradeRequest,
    compose_reporting_snapshot,
    reporting_snapshot_provenance_binding,
)
from meridian.reporting_snapshot_selection import select_reporting_snapshot
from meridian.reporting_snapshot_storage import (
    write_reporting_definition_revision,
    write_reporting_snapshot,
)

CLASS_ID = "issue58_reporting_class"
EMPTY_CLASS_ID = "issue58_empty_class"
MISSING_CLASS_ID = "issue58_missing_class"
SCHOOL_YEAR = "2026-2027"
PERIOD = AcademicPeriodRef(SCHOOL_YEAR, "q1")
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

SIBLING_MODULES = (
    "scoreform",
    "quillan",
    "concord",
    "portia",
    "vitrine",
    "paper_data_suite",
)
SIBLING_DISTRIBUTIONS = (
    "scoreform",
    "quillan",
    "pds-concord",
    "pds-portia",
    "pds-vitrine",
    "paper-data-suite",
)

EXPECTED: dict[MeridianAttentionCode, tuple[str, str, str]] = {
    "meridian_grade_result_stale": (
        "grade_result_targets",
        "preview-grades",
        "open_preview_grades",
    ),
    "meridian_reporting_publication_changed": (
        "reporting_snapshot_scopes",
        "snapshots",
        "open_snapshots",
    ),
    "meridian_reporting_snapshot_refresh_needed": (
        "reporting_snapshot_scopes",
        "snapshots",
        "open_snapshots",
    ),
    "meridian_reporting_snapshot_selection_pending": (
        "reporting_snapshot_scopes",
        "snapshots",
        "open_snapshots",
    ),
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _tree_state(root: Path) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        if path.is_file():
            rows.append(
                (
                    path.relative_to(root).as_posix(),
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
    return tuple(sorted(rows))


def _assert_installed_boundary() -> None:
    _require(
        metadata.version("pds-core") == "0.6.3",
        "Issue #58 installed smoke requires exact Core 0.6.3.",
    )
    _require(
        metadata.version("pds-meridian") == "0.2.0",
        "Issue #58 installed smoke requires candidate Meridian 0.2.0.",
    )
    for name in SIBLING_MODULES:
        _require(
            importlib.util.find_spec(name) is None,
            f"Issue #58 Core-only matrix unexpectedly found module {name!r}.",
        )
    for name in SIBLING_DISTRIBUTIONS:
        try:
            metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
        raise RuntimeError(
            f"Issue #58 Core-only matrix found distribution {name!r}."
        )

    prefix = Path(sys.prefix).resolve()
    for module in (pds_core, meridian):
        raw = module.__file__
        _require(isinstance(raw, str) and bool(raw), "Installed origin is missing.")
        assert isinstance(raw, str)
        _require(
            Path(raw).resolve().is_relative_to(prefix),
            "Installed module escaped the prepared virtual environment.",
        )


def _assert_provider_discovery() -> None:
    metadata_rows = inspect_core_provider_entry_points(
        provider_kind="module_operations"
    )
    metadata_matches = tuple(
        row for row in metadata_rows if row.entry_point_name == "meridian"
    )
    _require(
        len(metadata_matches) == 1,
        "Core did not discover exactly one Meridian provider.",
    )
    row = metadata_matches[0]
    _require(
        row.entry_point_target
        == "meridian.pds_operations:get_module_operations_profile",
        "Installed Meridian module-operations entry point is incorrect.",
    )

    diagnostics = diagnose_core_providers(provider_kind="module_operations")
    diagnostic_matches = tuple(
        item
        for item in diagnostics
        if item.metadata.entry_point_name == "meridian"
    )
    _require(
        len(diagnostic_matches) == 1,
        "Core did not diagnose exactly one Meridian provider.",
    )
    diagnostic = diagnostic_matches[0]
    _require(
        diagnostic.code == "provider.valid"
        and diagnostic.profile_validation == "passed"
        and diagnostic.core_compatibility == "passed"
        and not diagnostic.registry_conflict,
        "Core rejected the installed Meridian operations provider.",
    )


def _assert_native_contracts() -> None:
    _require(
        MERIDIAN_ATTENTION_SCHEMA_VERSION == 2,
        "Issue #58 native attention schema must remain version 2.",
    )
    for code, expected in EXPECTED.items():
        definition = attention_definition(code)
        actual = (
            definition.count_unit,
            definition.destination_id,
            definition.action_id,
        )
        _require(actual == expected, f"Installed routing changed for {code}.")
        _require(
            definition.task_id is None,
            f"Issue #58 category {code} fabricated a legacy task.",
        )


def _representative_native_summary() -> MeridianAttentionSummary:
    return build_meridian_attention_summary(
        tuple(
            MeridianAttentionItem(
                code=code,
                count=index,
                class_id=CLASS_ID,
            )
            for index, code in enumerate(EXPECTED, start=1)
        )
    )


def _assert_all_new_core_routes(workspace: Path) -> None:
    request = ModuleOperationsRequest(
        workspace_root=workspace,
        active_school_year=SCHOOL_YEAR,
        class_id=CLASS_ID,
    )
    native = _representative_native_summary()
    report = project_meridian_attention_to_core(native, request)
    _require(report.evaluation == "evaluated", "Core projection was not evaluated.")
    _require(len(report.summaries) == 4, "Core projection lost Issue #58 categories.")

    observed = {
        item.code: (
            item.count,
            item.action.action_id if item.action is not None else None,
        )
        for item in report.summaries
    }
    for index, (code, expected) in enumerate(EXPECTED.items(), start=1):
        _require(
            observed[code] == (index, expected[2]),
            f"Core projection changed Issue #58 route for {code}.",
        )

    native_payload = meridian_attention_summary_to_dict(native)
    _require(
        native_payload["schema_version"] == 2,
        "Native Issue #58 JSON schema changed.",
    )
    native_items = cast(list[dict[str, object]], native_payload["items"])
    for item in native_items:
        _require(
            item["destination_id"] in {"preview-grades", "snapshots"}
            and item["task_id"] is None,
            "Native Issue #58 JSON routing is not presentation-neutral.",
        )


def _definition() -> ReportingDefinitionRevision:
    return ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=CLASS_ID,
        definition_id="quarter_grade_report",
        definition_revision=1,
        supersedes_revision=None,
        report_kind="grade_report",
        purpose="quarter_grade_review",
        title="Quarter Grade Report",
        target_period=PERIOD,
        intended_audience="teacher",
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def _target() -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id="student_001",
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="standards_based",
    )


def _preview(target: GradePreviewTarget) -> FrozenGradeReportPreview:
    data: dict[str, object] = {
        "summary": {
            "requested_count": 1,
            "available_count": 0,
            "unavailable_count": 1,
            "base_calculated_count": 0,
            "base_blocked_count": 0,
            "base_insufficient_count": 0,
            "current_count": 0,
            "stale_count": 0,
            "effective_numeric_count": 0,
            "effective_nonnumeric_count": 0,
            "effective_base_count": 0,
            "effective_override_count": 0,
            "effective_none_count": 0,
        },
        "rows": [
            {
                "target": {
                    "class_id": target.class_id,
                    "student_id": target.student_id,
                    "target_period": {
                        "school_year": target.target_period.school_year,
                        "period_id": target.target_period.period_id,
                    },
                    "calendar_revision": target.calendar_revision,
                    "calculation_family": target.calculation_family,
                },
                "status": "unavailable",
                "unavailable_reason": "no_selected_grade",
                "explanation": None,
                "observation": None,
            }
        ],
    }
    encoded = (
        json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return frozen_grade_report_preview_from_json_bytes(encoded)


def _snapshot(
    definition: ReportingDefinitionReference,
    *,
    snapshot_id: str,
    minute: int,
    predecessor: ReportingSnapshotPredecessor | None = None,
) -> ReportingSnapshot:
    target = _target()
    request = ReportingSnapshotBuildRequest(
        schema_version=REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
        definition_reference=definition,
        grade_requests=(
            ReportingSnapshotGradeRequest(target=target, work_evidence=None),
        ),
        actor=ReportingActor("teacher", "teacher_local"),
        rationale="Freeze reviewed report.",
        requested_at=NOW,
        predecessor=predecessor,
    )
    return compose_reporting_snapshot(
        snapshot_id=snapshot_id,
        build_request=request,
        report_preview=_preview(target),
        provenance_bindings=(
            reporting_snapshot_provenance_binding(
                authority_kind="academic_period_calendar",
                reference_kind="academic_period_calendar_reference",
                reference={
                    "school_year": SCHOOL_YEAR,
                    "calendar_revision": 1,
                },
            ),
        ),
        created_at=NOW + timedelta(minutes=minute),
    )


def _seed_real_replacement_pending(workspace: Path) -> None:
    definition = write_reporting_definition_revision(
        workspace,
        _definition(),
    ).stored
    first = write_reporting_snapshot(
        workspace,
        _snapshot(
            definition.reference,
            snapshot_id="snapshot_a",
            minute=0,
        ),
    ).stored
    predecessor = ReportingSnapshotPredecessor(
        relationship="replaces_for_current_use",
        snapshot_reference=first.reference,
    )
    write_reporting_snapshot(
        workspace,
        _snapshot(
            definition.reference,
            snapshot_id="snapshot_b",
            minute=5,
            predecessor=predecessor,
        ),
    )
    select_reporting_snapshot(
        workspace,
        first.reference,
        actor=ReportingActor("teacher", "teacher_local"),
        rationale="Keep predecessor current until replacement review.",
        decided_at=NOW + timedelta(minutes=10),
        expected_current=None,
    )


def _invoke(
    profile: ModuleOperationsProfile,
    request: ModuleOperationsRequest,
) -> ModuleAttentionReport:
    readiness, attention = invoke_module_operations(profile, request)
    if readiness.code != "module_operations.capability_absent":
        raise RuntimeError("Meridian readiness must remain absent under Issue #58.")
    if not isinstance(attention.report, ModuleAttentionReport):
        raise RuntimeError("Core did not return a ModuleAttentionReport.")
    return attention.report


def _assert_real_provider_attention(
    profile: ModuleOperationsProfile,
    workspace: Path,
) -> None:
    report = _invoke(
        profile,
        ModuleOperationsRequest(
            workspace_root=workspace,
            active_school_year=SCHOOL_YEAR,
            class_id=CLASS_ID,
        ),
    )
    _require(report.evaluation == "evaluated", "Real #58 state was unavailable.")
    matches = tuple(
        item
        for item in report.summaries
        if item.code == "meridian_reporting_snapshot_selection_pending"
    )
    _require(len(matches) == 1, "Real #58 category was not emitted exactly once.")
    item = matches[0]
    _require(
        item.count == 1
        and item.class_id == CLASS_ID
        and item.action is not None
        and item.action.module_id == "meridian"
        and item.action.action_id == "open_snapshots",
        "Real #58 Core attention has the wrong safe route/count.",
    )
    rendered = json.dumps(asdict(report), sort_keys=True, default=str)
    for token in (
        "student_001",
        "score",
        "percentage",
        "proficiency_level",
        "snapshot_sha256",
        "rationale",
    ):
        _require(token not in rendered, f"Core attention leaked {token!r}.")


def _assert_empty_and_unavailable(
    profile: ModuleOperationsProfile,
    workspace: Path,
) -> None:
    empty = _invoke(
        profile,
        ModuleOperationsRequest(
            workspace_root=workspace,
            active_school_year=SCHOOL_YEAR,
            class_id=EMPTY_CLASS_ID,
        ),
    )
    _require(
        empty.evaluation == "evaluated" and empty.summaries == (),
        "Real empty class did not return successful-empty attention.",
    )

    _, missing = invoke_module_operations(
        profile,
        ModuleOperationsRequest(
            workspace_root=workspace,
            active_school_year=SCHOOL_YEAR,
            class_id=MISSING_CLASS_ID,
        ),
    )
    if (
        missing.code != "module_operations.evaluation_unavailable"
        or not isinstance(missing.report, ModuleAttentionReport)
    ):
        raise RuntimeError("Missing exact class did not remain unavailable.")
    _require(
        missing.report.evaluation == "unavailable"
        and missing.report.summaries == (),
        "Missing exact class did not remain unavailable.",
    )


def _assert_workspace_partial(
    profile: ModuleOperationsProfile,
    workspace: Path,
) -> None:
    report = _invoke(
        profile,
        ModuleOperationsRequest(
            workspace_root=workspace,
            active_school_year=SCHOOL_YEAR,
        ),
    )
    _require(report.evaluation == "evaluated", "Workspace attention failed.")
    _require(
        any(
            item.code == "meridian_reporting_snapshot_selection_pending"
            for item in report.summaries
        ),
        "Workspace aggregation lost the real Issue #58 category.",
    )
    _require(
        any(
            notice.code == "meridian_attention_partial"
            for notice in report.notices
        ),
        "Workspace discovery failure did not remain a bounded partial result.",
    )


def _run_cli(
    meridian_executable: Path,
    workspace: Path,
    class_id: str,
) -> dict[str, object]:
    command = [
        str(meridian_executable),
        "attention",
        "--workspace",
        str(workspace),
        "--school-year",
        SCHOOL_YEAR,
        "--class-id",
        class_id,
        "--format",
        "json",
    ]
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    first = subprocess.run(
        command,
        check=False,
        cwd=workspace.parent,
        env=env,
        text=True,
        capture_output=True,
    )
    second = subprocess.run(
        command,
        check=False,
        cwd=workspace.parent,
        env=env,
        text=True,
        capture_output=True,
    )
    _require(
        first.returncode == 0
        and second.returncode == 0
        and not first.stderr
        and not second.stderr
        and first.stdout == second.stdout,
        "Installed Issue #58 JSON CLI is not deterministic.",
    )
    decoded = json.loads(first.stdout)
    _require(isinstance(decoded, dict), "Installed CLI JSON is not an object.")
    return cast(dict[str, object], decoded)


def _assert_cli(
    meridian_executable: Path,
    workspace: Path,
) -> None:
    active = _run_cli(meridian_executable, workspace, CLASS_ID)
    items = cast(list[dict[str, object]], active["items"])
    matches = tuple(
        item
        for item in items
        if item["code"] == "meridian_reporting_snapshot_selection_pending"
    )
    _require(
        active["evaluation"] == "evaluated"
        and len(matches) == 1
        and matches[0]["count"] == 1,
        "Installed CLI did not expose the real Issue #58 category.",
    )

    empty = _run_cli(meridian_executable, workspace, EMPTY_CLASS_ID)
    _require(
        empty["evaluation"] == "evaluated" and empty["items"] == [],
        "Installed CLI confused successful-empty with unavailable.",
    )

    rendered = json.dumps(active, sort_keys=True)
    for token in (
        "student_001",
        "meridian_export_pending",
        "meridian_export_ready",
    ):
        _require(token not in rendered, f"Installed CLI exposed {token!r}.")


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: smoke_program_grade_report_attention.py <root> <meridian>"
        )

    _assert_installed_boundary()
    _assert_provider_discovery()
    _assert_native_contracts()

    root = Path(sys.argv[1]).resolve()
    meridian_executable = Path(sys.argv[2]).resolve()
    workspace = root / "workspace"
    class_dir(workspace, CLASS_ID).mkdir(parents=True)
    class_dir(workspace, EMPTY_CLASS_ID).mkdir(parents=True)
    _seed_real_replacement_pending(workspace)
    (workspace / "classes" / "invalid-entry.txt").write_text(
        "synthetic discovery failure\n",
        encoding="utf-8",
        newline="\n",
    )

    before = _tree_state(workspace)
    _assert_all_new_core_routes(workspace)

    profile = get_module_operations_profile()
    _assert_real_provider_attention(profile, workspace)
    _assert_empty_and_unavailable(profile, workspace)
    _assert_workspace_partial(profile, workspace)
    _assert_cli(meridian_executable, workspace)

    _require(
        _tree_state(workspace) == before,
        "Issue #58 installed provider/CLI mutated the workspace.",
    )

    print("Issue #58 installed Grade/report attention acceptance passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
