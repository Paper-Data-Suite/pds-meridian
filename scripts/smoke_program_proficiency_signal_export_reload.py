"""Fresh-process reload verification for issue #45 installed acceptance."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, cast

import pds_core
from pds_core.grouping_signal_csv import (
    grouping_signal_csv_to_signal_set,
    parse_grouping_signal_csv,
)
from pds_core.grouping_signal_storage import (
    list_grouping_signal_ids,
    load_grouping_signal,
)
from pds_core.grouping_signals import (
    grouping_signal_set_from_json,
    grouping_signal_set_to_json_bytes,
)
from pds_core.publication_compatibility import PublicationProducerRegistry
from pds_core.publication_records import publication_record_to_dict
from pds_core.publication_storage import (
    load_publication_record,
    verify_publication_manifest,
)
from quillan.pds_publication import (
    get_publication_producer_profile as quillan_profile,
)
from scoreform.pds_publication import (
    get_publication_producer_profile as scoreform_profile,
)

import meridian
import meridian.ingestion as ingestion
from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodProficiencyTraceTarget,
    explain_academic_period_proficiency,
)
from meridian.adapters import AdapterRegistry, installed_distribution_version
from meridian.grade_item_proficiency_explanation import (
    GradeItemProficiencyTraceTarget,
    explain_grade_item_proficiency,
)
from meridian.planning_signal_export_explanation import (
    PlanningSignalExportTraceTarget,
    explain_planning_signal_export,
)
from meridian.planning_signal_preview_review_explanation import (
    PlanningSignalPreviewReviewTraceTarget,
    explain_planning_signal_preview_review,
)
from meridian.projection_cache import load_authorized_projection_snapshot
from meridian.quillan_adapter import QuillanAcademicResultAdapter
from meridian.scoreform_adapter import ScoreFormAcademicResultAdapter

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "student_synthetic_001"
NONCONTRIBUTOR_ID = "student_synthetic_002"
STANDARD_ID = "standard_ela_1"
GRADE_ITEM_ID = "issue45_installed_proficiency"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "period_q1"
SIGNAL_SET_ID = "issue45_ela_planning_001"
BASELINE_PATH = Path("issue45-reload-baseline.json")


class ReloadFailure(RuntimeError):
    """Bounded fresh-process acceptance failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReloadFailure(message)


def _require_mapping(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReloadFailure(message)
    return cast(dict[str, Any], value)


def _require_list(value: object, message: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReloadFailure(message)
    return value


def _require_text(value: object, message: str) -> str:
    if not isinstance(value, str):
        raise ReloadFailure(message)
    return value


def _module_origin(module_name: str) -> Path:
    module = importlib.import_module(module_name)
    raw = getattr(module, "__file__", None)
    if not isinstance(raw, str) or not raw:
        raise ReloadFailure(f"{module_name} has no import origin.")
    return Path(raw).resolve()


def _installed_origin(module_name: str) -> None:
    origin = _module_origin(module_name)
    prefix = Path(sys.prefix).resolve()
    _require(origin.is_relative_to(prefix), f"{module_name} is outside the venv.")
    _require(
        "site-packages" in {part.lower() for part in origin.parts},
        f"{module_name} is not installed from site-packages.",
    )


def _assert_no_concord() -> None:
    try:
        metadata.version("pds-concord")
    except metadata.PackageNotFoundError:
        pass
    else:
        raise ReloadFailure("pds-concord distribution must remain absent.")
    _require(
        importlib.util.find_spec("concord") is None,
        "concord package became importable during fresh-process reload.",
    )
    _require(
        not any(name.split(".", 1)[0] == "concord" for name in sys.modules),
        "Concord appeared in sys.modules during fresh-process reload.",
    )


def _verify_installed_composition() -> None:
    expected = {
        "pds-core": "0.6.3",
        "scoreform": "0.11.0",
        "quillan": "0.10.0",
    }
    for distribution_name, expected_version in expected.items():
        _require(
            metadata.version(distribution_name) == expected_version,
            f"{distribution_name} version mismatch during reload.",
        )
    _require(
        meridian.__version__ == metadata.version("pds-meridian"),
        "Meridian module/distribution versions disagree during reload.",
    )
    _require(
        pds_core.__version__ == metadata.version("pds-core"),
        "Core module/distribution versions disagree during reload.",
    )
    for module_name in (
        "pds_core",
        "scoreform",
        "quillan",
        "meridian",
        "meridian.scoreform_adapter",
        "meridian.quillan_adapter",
    ):
        _installed_origin(module_name)
    _assert_no_concord()


class AllowInstalledProjection:
    """Synthetic deployment authorization matching the first process exactly."""

    def authorize(
        self,
        request: ingestion.PublicationAuthorizationRequest,
    ) -> ingestion.PublicationAuthorizationDecision:
        return ingestion.PublicationAuthorizationDecision(
            True,
            "issue45_installed_acceptance",
            "1",
            (),
        )


def _load_baseline(root: Path) -> dict[str, Any]:
    _require(BASELINE_PATH.is_file(), "First-process reload baseline is missing.")
    value = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), "Reload baseline must be a JSON object.")
    _require(value.get("schema_version") == "1", "Reload baseline version mismatch.")
    _require(value.get("workspace") == "workspace", "Workspace identity mismatch.")
    _require(
        value.get("signal_set_id") == SIGNAL_SET_ID,
        "Signal identity mismatch in reload baseline.",
    )
    return cast(dict[str, Any], value)


def _verify_producers_and_caches(
    root: Path,
    workspace: Path,
    baseline: dict[str, Any],
) -> None:
    publications = _require_mapping(
        baseline.get("publications"),
        "Publication baseline is missing.",
    )
    producer_registry = PublicationProducerRegistry(
        (scoreform_profile(), quillan_profile())
    )
    adapter_registry = AdapterRegistry(
        (ScoreFormAcademicResultAdapter(), QuillanAcademicResultAdapter())
    )

    for module_id in ("scoreform", "quillan"):
        exact = _require_mapping(
            publications.get(module_id),
            f"{module_id} baseline entry is missing.",
        )
        expected_publication = _require_mapping(
            exact.get("publication"),
            f"{module_id} publication baseline is malformed.",
        )
        publication_id = _require_text(
            expected_publication.get("publication_id"),
            f"{module_id} publication ID is missing.",
        )
        loaded = load_publication_record(workspace, publication_id)
        _require(
            publication_record_to_dict(loaded) == expected_publication,
            f"{module_id} Core Publication Record changed after first process.",
        )
        verified_manifest = verify_publication_manifest(workspace, loaded)
        _require(
            hashlib.sha256(verified_manifest.read_bytes()).hexdigest()
            == loaded.manifest_digest,
            f"{module_id} manifest no longer matches its Core publication.",
        )

        cache_key = _require_text(
            exact.get("cache_key"),
            f"{module_id} projection cache key is missing.",
        )
        snapshot_digest = _require_text(
            exact.get("snapshot_digest"),
            f"{module_id} projection cache digest is missing.",
        )
        authorized = load_authorized_projection_snapshot(
            workspace,
            publication_id,
            cache_key,
            authorizer=AllowInstalledProjection(),
            authorization_purpose_id="grading_import",
            requested_student_ids=(STUDENT_ID, NONCONTRIBUTOR_ID),
            producer_registry=producer_registry,
            adapter_registry=adapter_registry,
            distribution_version_resolver=installed_distribution_version,
        )
        _require(
            authorized.stored.snapshot_digest == snapshot_digest,
            f"{module_id} projection-cache digest changed on fresh reload.",
        )
        _require(
            authorized.assessment.reuse_status == "reusable",
            f"{module_id} projection cache is not reusable after fresh reload.",
        )
        _require(
            authorized.stored.snapshot.source.publication == loaded,
            f"{module_id} projection cache no longer binds the exact publication.",
        )

        files = _require_list(
            exact.get("files"),
            f"{module_id} file baseline is malformed.",
        )
        for raw_file in files:
            file_entry = _require_mapping(
                raw_file,
                f"{module_id} producer file baseline contains invalid data.",
            )
            relative = _require_text(
                file_entry.get("path"),
                f"{module_id} producer file path is missing.",
            )
            expected_sha256 = _require_text(
                file_entry.get("sha256"),
                f"{module_id} producer file digest is missing.",
            )
            candidate = (root / Path(*relative.split("/"))).resolve()
            _require(
                candidate.is_relative_to(root),
                f"{module_id} producer file baseline escaped the smoke root.",
            )
            _require(candidate.is_file(), f"{module_id} producer file disappeared.")
            _require(
                hashlib.sha256(candidate.read_bytes()).hexdigest() == expected_sha256,
                f"{module_id} producer-owned bytes changed after full workflow.",
            )


def _verify_proficiency_history(workspace: Path) -> None:
    contributor = explain_grade_item_proficiency(
        workspace,
        GradeItemProficiencyTraceTarget(
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            "current",
        ),
    )
    noncontributor = explain_grade_item_proficiency(
        workspace,
        GradeItemProficiencyTraceTarget(
            CLASS_ID,
            GRADE_ITEM_ID,
            NONCONTRIBUTOR_ID,
            STANDARD_ID,
            "current",
        ),
    )
    _require(
        contributor.selection_state == "selected_current"
        and contributor.calculation.status == "calculated"
        and contributor.calculation.proficiency_level_id == "proficient",
        "Contributor #34 result did not survive fresh-process reload.",
    )
    _require(
        {item.source.work.module_id for item in contributor.evidence}
        == {"scoreform", "quillan"},
        "Contributor #34 trace lost one released producer source.",
    )
    _require(
        noncontributor.selection_state == "selected_current"
        and noncontributor.calculation.status == "insufficient_evidence"
        and noncontributor.calculation.proficiency_level_id is None,
        "Noncontributor #34 result was converted into a proficiency level.",
    )

    contributor_period = explain_academic_period_proficiency(
        workspace,
        AcademicPeriodProficiencyTraceTarget(
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            STUDENT_ID,
            STANDARD_ID,
            "current",
        ),
    )
    noncontributor_period = explain_academic_period_proficiency(
        workspace,
        AcademicPeriodProficiencyTraceTarget(
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            NONCONTRIBUTOR_ID,
            STANDARD_ID,
            "current",
        ),
    )
    _require(
        contributor_period.selection_state == "selected_current"
        and contributor_period.calculation.status == "calculated"
        and contributor_period.calculation.proficiency_level_id == "proficient",
        "Contributor #35 result did not survive fresh-process reload.",
    )
    _require(
        contributor_period.grade_items[0].nested_grade_item_explanation is not None,
        "Contributor #35 trace lost its exact nested #34 result.",
    )
    _require(
        noncontributor_period.selection_state == "selected_current"
        and noncontributor_period.calculation.status == "insufficient_evidence"
        and noncontributor_period.calculation.proficiency_level_id is None,
        "Noncontributor #35 result was converted into a proficiency level.",
    )


def _verify_planning_export_history(
    root: Path,
    workspace: Path,
    baseline: dict[str, Any],
) -> None:
    export_trace = explain_planning_signal_export(
        workspace,
        PlanningSignalExportTraceTarget(CLASS_ID, SIGNAL_SET_ID),
    )
    _require(
        export_trace.review_decision == "accepted_for_export",
        "Fresh export trace lost the accepted review decision.",
    )
    _require(
        len(export_trace.students) == 2,
        "Fresh export trace must cover both roster students.",
    )
    contributor = next(
        item for item in export_trace.students if item.student_id == STUDENT_ID
    )
    noncontributor = next(
        item
        for item in export_trace.students
        if item.student_id == NONCONTRIBUTOR_ID
    )
    _require(
        contributor.exported
        and contributor.core_band == 2
        and contributor.meridian_band == 2,
        "Contributor export trace no longer reconciles Core and Meridian bands.",
    )
    _require(
        not noncontributor.exported
        and noncontributor.meridian_band is None
        and noncontributor.noncontribution_reason == "insufficient_evidence",
        "Noncontributor acquired a sentinel/exported band after reload.",
    )

    preview_trace = explain_planning_signal_preview_review(
        workspace,
        PlanningSignalPreviewReviewTraceTarget(
            CLASS_ID,
            export_trace.preview_id,
            "selected",
        ),
    )
    _require(
        preview_trace.path_state == "selected_and_export_eligible"
        and preview_trace.review is not None
        and preview_trace.review.decision == "accepted_for_export",
        "Selected #39 preview/review path is not export-eligible after reload.",
    )

    _require(
        list_grouping_signal_ids(workspace, CLASS_ID) == (SIGNAL_SET_ID,),
        "Fresh reload found unexpected Core grouping-signal history.",
    )
    stored = load_grouping_signal(workspace, CLASS_ID, SIGNAL_SET_ID)
    canonical = grouping_signal_set_to_json_bytes(stored.signal)
    _require(
        grouping_signal_set_from_json(canonical) == stored.signal
        and hashlib.sha256(canonical).hexdigest() == stored.digest,
        "Fresh reload failed Core canonical JSON/digest verification.",
    )

    csv_relative = _require_text(
        baseline.get("csv_path"),
        "CSV reload path is missing.",
    )
    csv_sha256 = _require_text(
        baseline.get("csv_sha256"),
        "CSV reload digest is missing.",
    )
    csv_path = (root / Path(*csv_relative.split("/"))).resolve()
    _require(csv_path.is_relative_to(root), "CSV reload path escaped the smoke root.")
    csv_bytes = csv_path.read_bytes()
    _require(
        hashlib.sha256(csv_bytes).hexdigest() == csv_sha256,
        "Core-native CSV bytes changed between processes.",
    )
    document = parse_grouping_signal_csv(csv_bytes)
    reconstructed = grouping_signal_csv_to_signal_set(document)
    _require(
        document.representation_scope == "complete_signal"
        and reconstructed == stored.signal
        and grouping_signal_set_to_json_bytes(reconstructed) == canonical,
        "Fresh reload failed Core-native CSV reconstruction.",
    )


def main() -> None:
    _verify_installed_composition()
    root = Path(".").resolve()
    baseline = _load_baseline(root)
    workspace = root / "workspace"
    _verify_producers_and_caches(root, workspace, baseline)
    _verify_proficiency_history(workspace)
    _verify_planning_export_history(root, workspace, baseline)
    _assert_no_concord()
    print(
        "Issue #45 fresh-process persisted-history reload passed without Concord."
    )


if __name__ == "__main__":
    main()
