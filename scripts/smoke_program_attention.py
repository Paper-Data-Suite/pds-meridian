"""Exercise installed Meridian attention through Core and the native CLI."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import asdict
from importlib import metadata
from pathlib import Path

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

from meridian.grouping_signal_derivation_storage import (
    list_grouping_signal_derivation_ids,
)
from meridian.grouping_signal_review_storage import (
    get_current_grouping_signal_review_revision,
    grouping_signal_review_current_path,
)

CLASS_ID = "synthetic_class_2026"
OTHER_CLASS_ID = "synthetic_class_other"
MISSING_CLASS_ID = "synthetic_class_missing"
SCHOOL_YEAR = "2026-2027"
STUDENT_ID = "student_001"
STANDARD_ID = "urn:njsls:ela:RL.CR.9-10.1"

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


def _tree_state(root: Path) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        values.append((relative, digest))
    return tuple(sorted(values))


def _assert_isolated_install() -> None:
    if metadata.version("pds-core") != "0.6.3":
        raise RuntimeError("Installed #43 smoke requires exact pds-core 0.6.3.")
    if metadata.version("pds-meridian") != "0.2.0":
        raise RuntimeError(
            "Installed #43 smoke requires the candidate Meridian 0.2.0 wheel."
        )

    for module_name in SIBLING_MODULES:
        if importlib.util.find_spec(module_name) is not None:
            raise RuntimeError(
                f"Installed #43 smoke unexpectedly found {module_name!r}."
            )

    for distribution_name in SIBLING_DISTRIBUTIONS:
        try:
            metadata.version(distribution_name)
        except metadata.PackageNotFoundError:
            continue
        raise RuntimeError(
            "Installed #43 smoke unexpectedly found distribution "
            f"{distribution_name!r}."
        )

    source_root = Path(os.environ["PDS_MERIDIAN_SMOKE_SOURCE_ROOT"]).resolve()
    if Path.cwd().resolve().is_relative_to(source_root):
        raise RuntimeError(
            "Installed #43 smoke is running inside the source checkout."
        )

    import pds_core

    import meridian

    prefix = Path(sys.prefix).resolve()
    meridian_file = meridian.__file__
    core_file = pds_core.__file__
    if meridian_file is None or core_file is None:
        raise RuntimeError("Installed package file metadata is unavailable.")
    if not Path(meridian_file).resolve().is_relative_to(prefix):
        raise RuntimeError("Meridian was not imported from the isolated venv.")
    if not Path(core_file).resolve().is_relative_to(prefix):
        raise RuntimeError("Core was not imported from the isolated venv.")


def _installed_profile() -> ModuleOperationsProfile:
    metadata_rows = inspect_core_provider_entry_points(
        provider_kind="module_operations"
    )
    if len(metadata_rows) != 1:
        raise RuntimeError(
            "Installed #43 smoke expected exactly one operations entry point."
        )
    row = metadata_rows[0]
    if (
        row.entry_point_group != "paper_data_suite.module_operations"
        or row.entry_point_name != "meridian"
        or row.entry_point_target
        != "meridian.pds_operations:get_module_operations_profile"
    ):
        raise RuntimeError(
            "Installed Meridian operations entry-point metadata is incorrect."
        )

    diagnostics = diagnose_core_providers(provider_kind="module_operations")
    if len(diagnostics) != 1:
        raise RuntimeError(
            "Installed #43 smoke expected one operations diagnostic."
        )
    diagnostic = diagnostics[0]
    if (
        diagnostic.code != "provider.valid"
        or diagnostic.profile_validation != "passed"
        or diagnostic.core_compatibility != "passed"
        or diagnostic.registry_conflict
    ):
        raise RuntimeError(
            "Core did not validate the installed Meridian operations provider."
        )

    profile = diagnostic.validated_profile
    if not isinstance(profile, ModuleOperationsProfile):
        raise RuntimeError(
            "Core did not return a validated ModuleOperationsProfile."
        )
    if profile.module_id != "meridian":
        raise RuntimeError("Installed operations profile has wrong module_id.")
    if profile.supported_core_operations_contract_versions != frozenset({"1"}):
        raise RuntimeError(
            "Installed operations profile does not expose contract v1 exactly."
        )
    if profile.attention_provider is None:
        raise RuntimeError("Installed operations profile lacks attention.")
    if profile.readiness_provider is not None:
        raise RuntimeError("Issue #43 must not invent Meridian readiness.")
    return profile


def _assert_attention_report(
    report: ModuleAttentionReport,
    *,
    expected_code: str | None,
    expected_class_id: str | None,
) -> None:
    if report.evaluation != "evaluated":
        raise RuntimeError("Expected an evaluated Meridian attention report.")

    if expected_code is None:
        if report.summaries:
            raise RuntimeError(
                "Expected successful empty Meridian attention summaries."
            )
        return

    matches = tuple(
        summary
        for summary in report.summaries
        if summary.code == expected_code
    )
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one representative planning-attention summary."
        )
    summary = matches[0]
    if (
        summary.count != 1
        or summary.class_id != expected_class_id
        or summary.work_ref is not None
        or summary.action is None
        or summary.action.module_id != "meridian"
        or summary.action.action_id != "open_create_planning_signal"
    ):
        raise RuntimeError(
            "Installed planning-attention summary has the wrong safe shape."
        )

    if any(
        item.class_id != expected_class_id
        for item in report.summaries
        if item.class_id is not None
    ):
        raise RuntimeError(
            "Installed attention report crossed the requested class scope."
        )

    serialized = json.dumps(asdict(report), sort_keys=True, default=str)
    forbidden_tokens = (
        "student_id",
        "student_name",
        "score",
        "percentage",
        "proficiency_level",
        "grouping_band",
        "grouping_dimension",
        "digest",
        "rationale",
        STUDENT_ID,
        STANDARD_ID,
        "Synthetic Student",
        '"proficient"',
    )
    for token in forbidden_tokens:
        if token in serialized:
            raise RuntimeError(
                "Installed Core attention report leaked protected detail."
            )


def _invoke_attention(
    profile: ModuleOperationsProfile,
    request: ModuleOperationsRequest,
) -> ModuleAttentionReport:
    readiness, attention = invoke_module_operations(profile, request)
    if readiness.code != "module_operations.capability_absent":
        raise RuntimeError("Meridian readiness must remain absent in #43.")
    if attention.code != "module_operations.evaluated":
        raise RuntimeError(
            "Core did not classify Meridian attention as evaluated."
        )
    if not isinstance(attention.report, ModuleAttentionReport):
        raise RuntimeError("Core did not return a ModuleAttentionReport.")
    return attention.report


def _run_cli(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        },
    )


def _assert_cli(workspace: Path, *, expected_code: str) -> None:
    scripts = Path(sys.executable).resolve().parent
    meridian = scripts / ("meridian.exe" if os.name == "nt" else "meridian")
    common = [
        str(meridian),
        "attention",
        "--workspace",
        str(workspace),
        "--school-year",
        SCHOOL_YEAR,
        "--class-id",
        CLASS_ID,
    ]

    first_json = _run_cli([*common, "--format", "json"])
    second_json = _run_cli([*common, "--format", "json"])
    if (
        first_json.returncode != 0
        or second_json.returncode != 0
        or first_json.stderr
        or second_json.stderr
        or first_json.stdout != second_json.stdout
    ):
        raise RuntimeError(
            "Installed Meridian attention JSON CLI is not deterministic."
        )
    payload = json.loads(first_json.stdout)
    items = payload["items"]
    matches = tuple(
        item for item in items if item["code"] == expected_code
    )
    if (
        payload["evaluation"] != "evaluated"
        or payload["scope"]["class_id"] != CLASS_ID
        or len(matches) != 1
        or matches[0]["count"] != 1
        or any(
            item["class_id"] not in {None, CLASS_ID}
            for item in items
        )
    ):
        raise RuntimeError(
            "Installed Meridian attention JSON CLI returned wrong state."
        )

    first_text = _run_cli([*common, "--format", "text"])
    second_text = _run_cli([*common, "--format", "text"])
    if (
        first_text.returncode != 0
        or second_text.returncode != 0
        or first_text.stderr
        or second_text.stderr
        or first_text.stdout != second_text.stdout
        or expected_code not in first_text.stdout
    ):
        raise RuntimeError(
            "Installed Meridian attention text CLI is not deterministic."
        )

    combined = first_json.stdout + first_text.stdout
    for token in (STUDENT_ID, STANDARD_ID, "Synthetic Student", "Band 2"):
        if token in combined:
            raise RuntimeError(
                "Installed Meridian attention CLI leaked protected detail."
            )

    empty = _run_cli(
        [
            str(meridian),
            "attention",
            "--workspace",
            str(workspace),
            "--class-id",
            OTHER_CLASS_ID,
            "--format",
            "json",
        ]
    )
    if empty.returncode != 0 or empty.stderr:
        raise RuntimeError(
            "Installed Meridian attention CLI failed an empty class scope."
        )
    empty_payload = json.loads(empty.stdout)
    if empty_payload["evaluation"] != "evaluated" or empty_payload["items"] != []:
        raise RuntimeError(
            "Installed CLI confused successful empty with unavailable."
        )

    missing_workspace = workspace.parent / "missing-workspace"
    unavailable = _run_cli(
        [
            str(meridian),
            "attention",
            "--workspace",
            str(missing_workspace),
            "--format",
            "json",
        ]
    )
    if (
        unavailable.returncode != 2
        or unavailable.stdout
        or unavailable.stderr
        != "Meridian attention scope could not be inspected safely.\n"
    ):
        raise RuntimeError(
            "Installed CLI did not fail closed for a missing workspace."
        )


def main() -> None:
    """Exercise provider discovery, invocation, filtering, and native CLI."""

    _assert_isolated_install()

    workspace = Path("workspace").resolve()
    if not workspace.is_dir():
        raise RuntimeError(
            "Representative #39 smoke workspace was not created first."
        )

    derivation_ids = list_grouping_signal_derivation_ids(workspace, CLASS_ID)
    if len(derivation_ids) != 1:
        raise RuntimeError(
            "Representative planning fixture has unexpected derivation state."
        )
    derivation_id = derivation_ids[0]
    if (
        get_current_grouping_signal_review_revision(
            workspace,
            CLASS_ID,
            derivation_id,
        )
        != 1
    ):
        raise RuntimeError(
            "Representative planning fixture lacks selected review revision 1."
        )

    pointer = grouping_signal_review_current_path(
        workspace,
        CLASS_ID,
        derivation_id,
    )
    pointer.unlink()
    if (
        get_current_grouping_signal_review_revision(
            workspace,
            CLASS_ID,
            derivation_id,
        )
        is not None
    ):
        raise RuntimeError(
            "Representative planning fixture did not enter selection-pending."
        )

    class_dir(workspace, OTHER_CLASS_ID).mkdir(parents=True)
    before = _tree_state(workspace)

    profile = _installed_profile()
    expected_code = "meridian_planning_review_selection_pending"

    exact = _invoke_attention(
        profile,
        ModuleOperationsRequest(
            workspace_root=workspace,
            active_school_year=SCHOOL_YEAR,
            class_id=CLASS_ID,
        ),
    )
    _assert_attention_report(
        exact,
        expected_code=expected_code,
        expected_class_id=CLASS_ID,
    )

    other = _invoke_attention(
        profile,
        ModuleOperationsRequest(
            workspace_root=workspace,
            active_school_year=SCHOOL_YEAR,
            class_id=OTHER_CLASS_ID,
        ),
    )
    _assert_attention_report(
        other,
        expected_code=None,
        expected_class_id=None,
    )

    workspace_report = _invoke_attention(
        profile,
        ModuleOperationsRequest(
            workspace_root=workspace,
            active_school_year=SCHOOL_YEAR,
        ),
    )
    _assert_attention_report(
        workspace_report,
        expected_code=expected_code,
        expected_class_id=CLASS_ID,
    )

    missing_class = invoke_module_operations(
        profile,
        ModuleOperationsRequest(
            workspace_root=workspace,
            active_school_year=SCHOOL_YEAR,
            class_id=MISSING_CLASS_ID,
        ),
    )[1]
    if (
        missing_class.code != "module_operations.evaluation_unavailable"
        or not isinstance(missing_class.report, ModuleAttentionReport)
        or missing_class.report.evaluation != "unavailable"
        or missing_class.report.summaries
    ):
        raise RuntimeError(
            "Installed provider did not fail closed for an unknown class."
        )

    missing_workspace = invoke_module_operations(
        profile,
        ModuleOperationsRequest(
            workspace_root=(workspace.parent / "absent-workspace").resolve(),
        ),
    )[1]
    if (
        missing_workspace.code != "module_operations.evaluation_unavailable"
        or not isinstance(missing_workspace.report, ModuleAttentionReport)
        or missing_workspace.report.evaluation != "unavailable"
        or missing_workspace.report.summaries
    ):
        raise RuntimeError(
            "Installed provider did not fail closed for missing workspace."
        )

    after_provider = _tree_state(workspace)
    if before != after_provider:
        raise RuntimeError(
            "Installed Core attention invocation mutated the workspace."
        )

    _assert_cli(workspace, expected_code=expected_code)

    after_cli = _tree_state(workspace)
    if before != after_cli:
        raise RuntimeError(
            "Installed Meridian attention CLI mutated the workspace."
        )

    print("Installed Meridian attention smoke passed.")


if __name__ == "__main__":
    main()
