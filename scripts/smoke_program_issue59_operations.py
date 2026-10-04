"""Installed Issue #59 Core-matrix acceptance for operations and launcher boundaries."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from pds_core.class_metadata import (
    create_class_metadata,
    write_class_metadata_for_class,
)
from pds_core.classes import class_folder, write_class_roster
from pds_core.module_operations import (
    ModuleAttentionReport,
    ModuleOperationsInvocationResult,
    ModuleOperationsProfile,
    ModuleOperationsRequest,
    ModuleReadinessReport,
    invoke_module_attention,
    invoke_module_operations,
    invoke_module_readiness,
)
from pds_core.provider_diagnostics import (
    diagnose_core_providers,
    inspect_core_provider_entry_points,
)
from pds_core.rosters import create_roster
from pds_core.workspace import ensure_workspace_root

from meridian.grouping_signal_derivation_storage import (
    list_grouping_signal_derivation_ids,
)
from meridian.grouping_signal_review_storage import (
    grouping_signal_review_current_path,
)
from meridian.owner_actions import (
    MERIDIAN_OWNER_ACTION_IDS,
    MERIDIAN_OWNER_MODULE_ID,
    owner_action_for_action_id,
)

CLASS_ID = "synthetic_class_2026"
SCHOOL_YEAR = "2026-2027"

ABSENT_MODULES = (
    "scoreform",
    "quillan",
    "concord",
    "portia",
    "vitrine",
    "paper_data_suite",
)
ABSENT_DISTRIBUTIONS = (
    "scoreform",
    "quillan",
    "pds-concord",
    "pds-portia",
    "pds-vitrine",
    "paper-data-suite",
)


def _tree_state(root: Path) -> tuple[tuple[str, str, str], ...]:
    values: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            values.append(("link", relative, ""))
        elif path.is_dir():
            values.append(("dir", relative, ""))
        elif path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            values.append(("file", relative, digest))
    return tuple(values)


def _distribution_absent(distribution: str) -> bool:
    try:
        metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return True
    return False


def _assert_isolated_install() -> str:
    if metadata.version("pds-core") != "0.6.4":
        raise RuntimeError("Issue #59 installed acceptance requires exact Core 0.6.4.")

    meridian_version = metadata.version("pds-meridian")
    if not meridian_version:
        raise RuntimeError("Installed Meridian distribution version is unavailable.")

    for module_name in ABSENT_MODULES:
        if importlib.util.find_spec(module_name) is not None:
            raise RuntimeError(
                f"Issue #59 Core matrix unexpectedly found module {module_name!r}."
            )
    for distribution_name in ABSENT_DISTRIBUTIONS:
        if not _distribution_absent(distribution_name):
            raise RuntimeError(
                "Issue #59 Core matrix unexpectedly found distribution "
                f"{distribution_name!r}."
            )

    source_text = os.environ.get("PDS_MERIDIAN_SMOKE_SOURCE_ROOT")
    if not source_text:
        raise RuntimeError("Issue #59 source-root isolation marker is missing.")
    source_root = Path(source_text).resolve()
    if Path.cwd().resolve().is_relative_to(source_root):
        raise RuntimeError("Issue #59 acceptance must run outside the source checkout.")

    import pds_core

    import meridian

    prefix = Path(sys.prefix).resolve()
    for package_name, package_file in (
        ("meridian", meridian.__file__),
        ("pds_core", pds_core.__file__),
    ):
        if package_file is None:
            raise RuntimeError(
                f"Installed {package_name} package origin is unavailable."
            )
        if not Path(package_file).resolve().is_relative_to(prefix):
            raise RuntimeError(
                f"Installed {package_name} resolved outside the isolated environment."
            )

    return meridian_version


def _installed_profile() -> ModuleOperationsProfile:
    rows = inspect_core_provider_entry_points(provider_kind="module_operations")
    if len(rows) != 1:
        raise RuntimeError(
            "Issue #59 expected exactly one installed module-operations entry point."
        )
    row = rows[0]
    if (
        row.entry_point_group != "paper_data_suite.module_operations"
        or row.entry_point_name != "meridian"
        or row.entry_point_target
        != "meridian.pds_operations:get_module_operations_profile"
    ):
        raise RuntimeError(
            "Installed Meridian operations entry-point metadata is wrong."
        )

    diagnostics = diagnose_core_providers(provider_kind="module_operations")
    if len(diagnostics) != 1:
        raise RuntimeError(
            "Issue #59 expected exactly one installed operations diagnostic."
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
        raise RuntimeError("Core did not return a ModuleOperationsProfile.")
    if profile.module_id != MERIDIAN_OWNER_MODULE_ID:
        raise RuntimeError("Installed operations profile has the wrong module_id.")
    if profile.supported_core_operations_contract_versions != frozenset({"1"}):
        raise RuntimeError("Installed operations profile must expose Core v1 exactly.")
    if profile.readiness_provider is None:
        raise RuntimeError("Installed operations profile lacks readiness.")
    if profile.attention_provider is None:
        raise RuntimeError("Installed operations profile lacks attention.")
    return profile


def _readiness_report(
    result: ModuleOperationsInvocationResult,
    *,
    expected_code: str,
    expected_evaluation: str,
    expected_ready: bool | None,
) -> ModuleReadinessReport:
    if (
        result.code != expected_code
        or not result.provider_call_attempted
        or not result.provider_call_succeeded
        or result.result_validation != "passed"
        or not isinstance(result.report, ModuleReadinessReport)
    ):
        raise RuntimeError("Core did not return a validated readiness result.")
    report = result.report
    if report.evaluation != expected_evaluation or report.ready is not expected_ready:
        raise RuntimeError(
            "Installed Meridian readiness returned the wrong evaluation state."
        )
    return report


def _attention_report(
    result: ModuleOperationsInvocationResult,
) -> ModuleAttentionReport:
    if (
        result.code != "module_operations.evaluated"
        or not result.provider_call_attempted
        or not result.provider_call_succeeded
        or result.result_validation != "passed"
        or not isinstance(result.report, ModuleAttentionReport)
    ):
        raise RuntimeError("Core did not return a validated attention result.")
    return result.report


def _make_ready_class(root: Path, class_id: str = CLASS_ID) -> None:
    ensure_workspace_root(root)
    created_at = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    write_class_metadata_for_class(
        root,
        create_class_metadata(
            class_id,
            SCHOOL_YEAR,
            created_at=created_at,
        ),
    )
    write_class_roster(
        root,
        create_roster(
            class_id,
            (
                {
                    "student_id": "student_1",
                    "last_name": "Example",
                    "first_name": "Student",
                    "period": "1",
                },
            ),
        ),
    )


def _assert_readiness_cases(profile: ModuleOperationsProfile) -> None:
    contexts = Path("issue59-readiness-contexts").resolve()
    contexts.mkdir()

    no_workspace = invoke_module_readiness(profile, ModuleOperationsRequest())
    _readiness_report(
        no_workspace,
        expected_code="module_operations.evaluation_unavailable",
        expected_evaluation="unavailable",
        expected_ready=None,
    )

    missing = contexts / "missing-workspace"
    missing_result = invoke_module_readiness(
        profile,
        ModuleOperationsRequest(workspace_root=missing),
    )
    _readiness_report(
        missing_result,
        expected_code="module_operations.evaluation_unavailable",
        expected_evaluation="unavailable",
        expected_ready=None,
    )
    if missing.exists():
        raise RuntimeError("Readiness created a missing workspace.")

    empty = contexts / "empty-workspace"
    empty.mkdir()
    before_empty = _tree_state(empty)
    empty_result = invoke_module_readiness(
        profile,
        ModuleOperationsRequest(workspace_root=empty),
    )
    _readiness_report(
        empty_result,
        expected_code="module_operations.evaluated",
        expected_evaluation="evaluated",
        expected_ready=True,
    )
    if before_empty != _tree_state(empty):
        raise RuntimeError("Readiness mutated an empty workspace.")

    valid = contexts / "valid-workspace"
    _make_ready_class(valid)
    before_valid = _tree_state(valid)
    valid_result = invoke_module_readiness(
        profile,
        ModuleOperationsRequest(
            workspace_root=valid,
            class_id=CLASS_ID,
            active_school_year="2025-2026",
        ),
    )
    _readiness_report(
        valid_result,
        expected_code="module_operations.evaluated",
        expected_evaluation="evaluated",
        expected_ready=True,
    )
    if before_valid != _tree_state(valid):
        raise RuntimeError("Readiness mutated a valid class workspace.")

    missing_class = invoke_module_readiness(
        profile,
        ModuleOperationsRequest(
            workspace_root=valid,
            class_id="missing_class",
        ),
    )
    _readiness_report(
        missing_class,
        expected_code="module_operations.evaluated",
        expected_evaluation="evaluated",
        expected_ready=False,
    )
    if before_valid != _tree_state(valid):
        raise RuntimeError("Missing-class readiness mutated the valid workspace.")

    invalid = contexts / "invalid-class-workspace"
    _make_ready_class(invalid)
    class_folder(invalid, CLASS_ID).metadata_path.write_text(
        "{not-json",
        encoding="utf-8",
    )
    before_invalid = _tree_state(invalid)
    invalid_result = invoke_module_readiness(
        profile,
        ModuleOperationsRequest(
            workspace_root=invalid,
            class_id=CLASS_ID,
        ),
    )
    _readiness_report(
        invalid_result,
        expected_code="module_operations.evaluated",
        expected_evaluation="evaluated",
        expected_ready=False,
    )
    if before_invalid != _tree_state(invalid):
        raise RuntimeError("Invalid-class readiness mutated the workspace.")

    target = contexts / "linked-target"
    target.mkdir()
    link = contexts / "linked-workspace"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError):
        pass
    else:
        linked_result = invoke_module_readiness(
            profile,
            ModuleOperationsRequest(workspace_root=link),
        )
        _readiness_report(
            linked_result,
            expected_code="module_operations.evaluation_unavailable",
            expected_evaluation="unavailable",
            expected_ready=None,
        )


def _assert_ready_with_attention(profile: ModuleOperationsProfile) -> None:
    workspace = Path("workspace").resolve()
    if not workspace.is_dir():
        raise RuntimeError("Issue #59 representative seeded workspace is missing.")

    derivation_ids = list_grouping_signal_derivation_ids(workspace, CLASS_ID)
    if len(derivation_ids) != 1:
        raise RuntimeError(
            "Issue #59 planning fixture has unexpected derivation state."
        )
    pointer = grouping_signal_review_current_path(
        workspace,
        CLASS_ID,
        derivation_ids[0],
    )
    pointer.unlink(missing_ok=True)

    before = _tree_state(workspace)
    request = ModuleOperationsRequest(
        workspace_root=workspace,
        active_school_year=SCHOOL_YEAR,
        class_id=CLASS_ID,
    )

    first_attention = _attention_report(invoke_module_attention(profile, request))
    readiness = _readiness_report(
        invoke_module_readiness(profile, request),
        expected_code="module_operations.evaluated",
        expected_evaluation="evaluated",
        expected_ready=True,
    )
    second_attention = _attention_report(invoke_module_attention(profile, request))

    if first_attention != second_attention:
        raise RuntimeError("Readiness invocation changed Meridian attention results.")
    if readiness.ready is not True:
        raise RuntimeError("Representative attention context must remain ready.")

    matches = tuple(
        summary
        for summary in second_attention.summaries
        if summary.code == "meridian_planning_review_selection_pending"
    )
    if len(matches) != 1:
        raise RuntimeError(
            "Issue #59 representative ready context lacks expected attention."
        )

    for summary in second_attention.summaries:
        action = summary.action
        if action is None:
            continue
        if action.module_id != MERIDIAN_OWNER_MODULE_ID:
            raise RuntimeError("Core-facing attention action has the wrong owner.")
        if action.action_id not in MERIDIAN_OWNER_ACTION_IDS:
            raise RuntimeError("Core-facing attention action is outside the catalog.")
        owner_action_for_action_id(action.action_id)

    both_readiness, both_attention = invoke_module_operations(profile, request)
    _readiness_report(
        both_readiness,
        expected_code="module_operations.evaluated",
        expected_evaluation="evaluated",
        expected_ready=True,
    )
    _attention_report(both_attention)

    after = _tree_state(workspace)
    if before != after:
        raise RuntimeError("Issue #59 operations invocation mutated canonical state.")


def _run_launcher(command: list[str]) -> subprocess.CompletedProcess[str]:
    child_environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    for variable in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        child_environment.pop(variable, None)
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=child_environment,
    )


def _assert_launcher(meridian_version: str) -> None:
    distribution = metadata.distribution("pds-meridian")
    entry_points = tuple(
        entry_point
        for entry_point in distribution.entry_points
        if entry_point.group == "console_scripts" and entry_point.name == "meridian"
    )
    if len(entry_points) != 1 or entry_points[0].value != "meridian.cli:main":
        raise RuntimeError(
            "Installed Meridian console metadata is not exactly meridian.cli:main."
        )

    scripts = Path(sys.executable).resolve().parent
    launcher = scripts / ("meridian.exe" if os.name == "nt" else "meridian")
    if not launcher.is_file():
        raise RuntimeError("Installed Meridian console launcher is missing.")
    if not launcher.resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError(
            "Installed Meridian launcher escaped the active environment."
        )

    first_version = _run_launcher([str(launcher), "--version"])
    second_version = _run_launcher([str(launcher), "--version"])
    expected_version = f"meridian {meridian_version}\n"
    if (
        first_version.returncode != 0
        or second_version.returncode != 0
        or first_version.stderr
        or second_version.stderr
        or first_version.stdout != expected_version
        or second_version.stdout != expected_version
    ):
        raise RuntimeError("Installed `meridian --version` boundary is invalid.")

    first_help = _run_launcher([str(launcher), "--help"])
    second_help = _run_launcher([str(launcher), "--help"])
    if (
        first_help.returncode != 0
        or second_help.returncode != 0
        or first_help.stderr
        or second_help.stderr
        or first_help.stdout != second_help.stdout
        or "usage: meridian" not in first_help.stdout
    ):
        raise RuntimeError("Installed `meridian --help` boundary is invalid.")


def main() -> None:
    """Exercise exact installed readiness, attention, and console boundaries."""

    meridian_version = _assert_isolated_install()
    profile = _installed_profile()
    _assert_readiness_cases(profile)
    _assert_ready_with_attention(profile)
    _assert_launcher(meridian_version)
    print("Installed Meridian Issue #59 operations/launcher smoke passed.")


if __name__ == "__main__":
    main()
