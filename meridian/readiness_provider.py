"""Read-only Meridian readiness provider for Core module-operations v1."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Final, Literal

from pds_core.class_metadata import (
    ClassMetadataReadError,
    ClassMetadataValidationError,
    load_class_metadata_for_class,
)
from pds_core.classes import class_folder, load_class_roster
from pds_core.identifiers import IdentifierValidationError
from pds_core.module_operations import (
    ModuleOperationsNotice,
    ModuleOperationsRequest,
    ModuleReadinessReport,
    validate_module_operations_request,
    validate_module_readiness_report,
)
from pds_core.rosters import RosterReadError, RosterValidationError
from pds_core.routes import classes_dir
from pds_core.workspace import WorkspaceRootError, inspect_workspace_root

from meridian.pds_operations import MERIDIAN_MODULE_ID

READINESS_UNAVAILABLE_CODE: Final[str] = "meridian_readiness_unavailable"
WORKSPACE_NOT_READY_CODE: Final[str] = "meridian_workspace_not_ready"
CLASS_NOT_READY_CODE: Final[str] = "meridian_class_not_ready"

READINESS_UNAVAILABLE_SUMMARY: Final[str] = (
    "Meridian readiness could not be evaluated for the supplied workspace context."
)
WORKSPACE_NOT_READY_SUMMARY: Final[str] = (
    "The supplied workspace is not currently structurally usable for Meridian."
)
CLASS_NOT_READY_SUMMARY: Final[str] = (
    "The requested Meridian class is missing or structurally invalid."
)

_PathState = Literal["present", "missing", "wrong_type", "unsafe"]


def _notice(code: str, summary: str) -> ModuleOperationsNotice:
    return ModuleOperationsNotice(code=code, summary=summary)


def _report(
    *,
    evaluation: Literal["evaluated", "unavailable"],
    ready: bool | None,
    notice: ModuleOperationsNotice | None = None,
) -> ModuleReadinessReport:
    return validate_module_readiness_report(
        ModuleReadinessReport(
            evaluation=evaluation,
            ready=ready,
            notices=() if notice is None else (notice,),
        ),
        expected_module_id=MERIDIAN_MODULE_ID,
    )


def _unavailable() -> ModuleReadinessReport:
    return _report(
        evaluation="unavailable",
        ready=None,
        notice=_notice(
            READINESS_UNAVAILABLE_CODE,
            READINESS_UNAVAILABLE_SUMMARY,
        ),
    )


def _workspace_not_ready() -> ModuleReadinessReport:
    return _report(
        evaluation="evaluated",
        ready=False,
        notice=_notice(
            WORKSPACE_NOT_READY_CODE,
            WORKSPACE_NOT_READY_SUMMARY,
        ),
    )


def _class_not_ready() -> ModuleReadinessReport:
    return _report(
        evaluation="evaluated",
        ready=False,
        notice=_notice(CLASS_NOT_READY_CODE, CLASS_NOT_READY_SUMMARY),
    )


def _ready() -> ModuleReadinessReport:
    return _report(evaluation="evaluated", ready=True)


def _inspect_path(
    path: Path,
    *,
    expected_kind: Literal["directory", "file"],
) -> _PathState:
    """Classify one canonical Core path without following unsafe links."""

    try:
        if path.is_symlink():
            return "unsafe"
        if not path.exists():
            return "missing"
        if expected_kind == "directory":
            return "present" if path.is_dir() else "wrong_type"
        return "present" if path.is_file() else "wrong_type"
    except OSError:
        return "unsafe"


def _class_metadata_state(
    root: Path,
    class_id: str,
) -> ModuleReadinessReport | None:
    try:
        load_class_metadata_for_class(root, class_id)
    except ClassMetadataValidationError:
        return _class_not_ready()
    except ClassMetadataReadError as error:
        cause = error.__cause__
        if isinstance(cause, (json.JSONDecodeError, UnicodeError)):
            return _class_not_ready()
        return _unavailable()
    return None


def _class_roster_state(
    root: Path,
    class_id: str,
) -> ModuleReadinessReport | None:
    try:
        load_class_roster(root, class_id)
    except RosterValidationError:
        return _class_not_ready()
    except RosterReadError as error:
        cause = error.__cause__
        if isinstance(cause, (UnicodeError, csv.Error)):
            return _class_not_ready()
        return _unavailable()
    return None


def _evaluate_class_readiness(
    root: Path,
    class_id: str,
) -> ModuleReadinessReport:
    """Inspect the exact existing Core class baseline without mutation."""

    try:
        folder = class_folder(root, class_id)
    except IdentifierValidationError:
        return _unavailable()

    classes_state = _inspect_path(classes_dir(root), expected_kind="directory")
    if classes_state == "unsafe":
        return _unavailable()
    if classes_state != "present":
        return _class_not_ready()

    class_state = _inspect_path(folder.class_dir, expected_kind="directory")
    if class_state == "unsafe":
        return _unavailable()
    if class_state != "present":
        return _class_not_ready()

    metadata_state = _inspect_path(folder.metadata_path, expected_kind="file")
    if metadata_state == "unsafe":
        return _unavailable()
    if metadata_state != "present":
        return _class_not_ready()

    roster_state = _inspect_path(folder.roster_path, expected_kind="file")
    if roster_state == "unsafe":
        return _unavailable()
    if roster_state != "present":
        return _class_not_ready()

    metadata_result = _class_metadata_state(root, class_id)
    if metadata_result is not None:
        return metadata_result

    roster_result = _class_roster_state(root, class_id)
    if roster_result is not None:
        return roster_result

    # A valid Core class is sufficient. Meridian Grade/report state, policies,
    # evidence, snapshots, exports, and attention are not readiness prerequisites.
    return _ready()


def evaluate_meridian_readiness(
    request: ModuleOperationsRequest,
    /,
) -> ModuleReadinessReport:
    """Evaluate structural Meridian readiness for the exact supplied context."""

    request = validate_module_operations_request(request)
    if request.workspace_root is None:
        return _unavailable()

    raw_root = Path(request.workspace_root)
    try:
        if raw_root.is_symlink():
            return _unavailable()
        status = inspect_workspace_root(request.workspace_root)
    except (OSError, RuntimeError, WorkspaceRootError):
        return _unavailable()

    if not status.exists:
        return _unavailable()
    if not status.is_dir:
        return _workspace_not_ready()
    if status.root.is_symlink():
        return _unavailable()
    if not status.is_writable:
        return _workspace_not_ready()

    if request.class_id is None:
        return _ready()
    return _evaluate_class_readiness(status.root, request.class_id)


__all__ = [
    "CLASS_NOT_READY_CODE",
    "CLASS_NOT_READY_SUMMARY",
    "READINESS_UNAVAILABLE_CODE",
    "READINESS_UNAVAILABLE_SUMMARY",
    "WORKSPACE_NOT_READY_CODE",
    "WORKSPACE_NOT_READY_SUMMARY",
    "evaluate_meridian_readiness",
]
