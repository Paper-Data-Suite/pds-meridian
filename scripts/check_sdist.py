"""Validate the Meridian source distribution metadata and content boundary."""

from __future__ import annotations

import argparse
import tarfile
from email.message import Message
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

EXPECTED_DISTRIBUTION = "pds-meridian"
EXPECTED_VERSION = "0.1.1"
EXPECTED_SUMMARY = (
    "Publication ingestion and typed evidence diagnostics for Paper Data Suite"
)
EXPECTED_SDIST_FILENAME = f"pds_meridian-{EXPECTED_VERSION}.tar.gz"
EXPECTED_ROOT = f"pds_meridian-{EXPECTED_VERSION}"

REQUIRED_MEMBERS = frozenset(
    {
        "CHANGELOG.md",
        "LICENSE",
        "MANIFEST.in",
        "README",
        "Security.md",
        "pyproject.toml",
        "docs/README.md",
        "docs/architecture/attempt-selection-policy-and-decisions.md",
        "docs/architecture/evidence-eligibility-decisions.md",
        "docs/architecture/grade-item-membership-and-academic-period-assignment.md",
        "docs/architecture/grade-items-and-canonical-storage.md",
        "docs/architecture/reassessment-and-replacement-relationships.md",
        "docs/architecture/proficiency-scales-and-native-value-mapping-profiles.md",
        "docs/architecture/standards-evidence-association-and-aggregation-inputs.md",
        "docs/architecture/standards-proficiency-calculation.md",
        "docs/architecture/academic-period-proficiency-aggregation.md",
        "docs/architecture/core-grouping-signal-interchange.md",
        "docs/architecture/grouping-signal-derivation-policy.md",
        "docs/architecture/grouping-signal-generation.md",
        "docs/architecture/grouping-signal-preview-diagnostics.md",
        "docs/architecture/grouping-signal-core-export.md",
        "meridian/__init__.py",
        "meridian/academic_period_proficiency.py",
        "meridian/academic_period_calculation_preview_workflow.py",
        "meridian/academic_period_result_persistence_workflow.py",
        "meridian/academic_period_result_selection_workflow.py",
        "meridian/planning_signal_workflow.py",
        "meridian/planning_signal_derivation_persistence_workflow.py",
        "meridian/planning_signal_preview_generation_workflow.py",
        "meridian/planning_signal_preview_write_workflow.py",
        "meridian/academic_period_calculation_assembly_workflow.py",
        "meridian/academic_period_proficiency_storage.py",
        "meridian/attempt_selection.py",
        "meridian/attempt_selection_storage.py",
        "meridian/attempt_decisions_workflow.py",
        "meridian/exclusions_workflow.py",
        "meridian/exclusions_eligibility_authoring_workflow.py",
        "meridian/exclusions_eligibility_selection_workflow.py",
        "meridian/attempt_decision_authoring_workflow.py",
        "meridian/calculation_preview_workflow.py",
        "meridian/calculation_result_persistence_workflow.py",
        "meridian/calculation_result_selection_workflow.py",
        "meridian/calculation_preview_assembly_workflow.py",
        "meridian/attempt_decision_selection_workflow.py",
        "meridian/attempt_policy_authoring_workflow.py",
        "meridian/attempt_policy_selection_workflow.py",
        "meridian/_version.py",
        "meridian/evidence_eligibility.py",
        "meridian/evidence_eligibility_storage.py",
        "meridian/grade_item_membership_storage.py",
        "meridian/grade_item_memberships.py",
        "meridian/grade_item_storage.py",
        "meridian/grade_items.py",
        "meridian/grouping_signal_policy.py",
        "meridian/grouping_signal_policy_storage.py",
        "meridian/grouping_signal_derivation.py",
        "meridian/grouping_signal_derivation_storage.py",
        "meridian/grouping_signal_generation.py",
        "meridian/grouping_signal_generation_basis.py",
        "meridian/grouping_signal_currentness.py",
        "meridian/grouping_signal_preview.py",
        "meridian/grouping_signal_preview_storage.py",
        "meridian/grouping_signal_preview_generation.py",
        "meridian/grouping_signal_preview_projection.py",
        "meridian/grouping_signal_review.py",
        "meridian/grouping_signal_review_storage.py",
        "meridian/grouping_signal_review_workflow.py",
        "meridian/grouping_signal_export.py",
        "meridian/grouping_signal_export_eligibility.py",
        "meridian/grouping_signal_export_workflow.py",
        "meridian/grouping_signal_export_receipt.py",
        "meridian/grouping_signal_export_storage.py",
        "meridian/grouping_signal_export_receipt_workflow.py",
        "meridian/grouping_signal_csv_export.py",
        "meridian/teacher_workflows.py",
        "meridian/standards_review_workflow.py",
        "meridian/standards_association_authoring_workflow.py",
        "meridian/standards_association_selection_workflow.py",
        "meridian/new_evidence_workflow.py",
        "meridian/new_evidence_eligibility_workflow.py",
        "meridian/new_evidence_eligibility_selection_workflow.py",
        "meridian/grade_items_workflow.py",
        "meridian/grade_item_authoring_workflow.py",
        "meridian/grade_item_selection_workflow.py",
        "meridian/grade_item_membership_authoring_workflow.py",
        "meridian/grade_item_membership_selection_workflow.py",
        "meridian/py.typed",
        "meridian/proficiency_mapping.py",
        "meridian/proficiency_mapping_storage.py",
        "meridian/reassessment.py",
        "meridian/reassessment_storage.py",
        "meridian/standards_evidence.py",
        "meridian/standards_evidence_storage.py",
        "meridian/standards_proficiency.py",
        "meridian/standards_proficiency_storage.py",
        "scripts/smoke_test_academic_period_proficiency_wheel.py",
        "scripts/smoke_test_grade_items_wheel.py",
        "scripts/smoke_test_grouping_signal_contract_wheel.py",
        "scripts/smoke_test_grouping_signal_policy_wheel.py",
        "scripts/smoke_test_grouping_signal_generation_wheel.py",
        "scripts/smoke_program_grouping_signal_generation.py",
        "scripts/smoke_test_grouping_signal_preview_review_wheel.py",
        "scripts/smoke_program_grouping_signal_preview_review.py",
        "scripts/smoke_test_grouping_signal_export_wheel.py",
        "scripts/smoke_program_grouping_signal_export.py",
        "scripts/validate_repository.py",
        "tests/test_academic_period_proficiency.py",
        "tests/test_academic_period_calculation_preview_workflow.py",
        "tests/test_academic_period_result_persistence_workflow.py",
        "tests/test_academic_period_result_selection_workflow.py",
        "tests/test_planning_signal_workflow.py",
        "tests/test_planning_signal_derivation_persistence_workflow.py",
        "tests/test_planning_signal_preview_generation_workflow.py",
        "tests/test_planning_signal_preview_write_workflow.py",
        "tests/test_academic_period_calculation_assembly_workflow.py",
        "tests/test_academic_period_proficiency_integration.py",
        "tests/test_academic_period_proficiency_storage.py",
        "tests/test_attempt_selection.py",
        "tests/test_attempt_selection_storage.py",
        "tests/test_attempt_decisions_workflow.py",
        "tests/test_exclusions_workflow.py",
        "tests/test_exclusions_eligibility_authoring_workflow.py",
        "tests/test_exclusions_eligibility_selection_workflow.py",
        "tests/test_attempt_decision_authoring_workflow.py",
        "tests/test_calculation_preview_workflow.py",
        "tests/test_calculation_result_persistence_workflow.py",
        "tests/test_calculation_result_selection_workflow.py",
        "tests/test_calculation_preview_assembly_workflow.py",
        "tests/test_cli_calculation_preview.py",
        "tests/test_cli_calculation_result_persistence.py",
        "tests/test_cli_calculation_result_selection.py",
        "tests/test_cli_academic_period_calculation_preview.py",
        "tests/test_cli_academic_period_result_persistence.py",
        "tests/test_cli_academic_period_result_selection.py",
        "tests/test_cli_planning_signal_workflow.py",
        "tests/test_cli_planning_signal_derivation_persistence.py",
        "tests/test_cli_planning_signal_preview_write.py",
        "tests/test_attempt_decision_selection_workflow.py",
        "tests/test_attempt_policy_authoring_workflow.py",
        "tests/test_attempt_policy_selection_workflow.py",
        "tests/test_cli_attempt_decisions_workflow.py",
        "tests/test_cli_attempt_policy_authoring.py",
        "tests/test_cli_attempt_policy_selection.py",
        "tests/test_cli_attempt_decision_authoring.py",
        "tests/test_cli_attempt_decision_selection.py",
        "tests/test_cli_exclusions_workflow.py",
        "tests/test_cli_exclusions_eligibility_authoring.py",
        "tests/test_cli_exclusions_eligibility_selection.py",
        "tests/test_attempt_selection_integration.py",
        "tests/test_attempt_selection_package_boundaries.py",
        "tests/test_evidence_eligibility.py",
        "tests/test_evidence_eligibility_storage.py",
        "tests/test_evidence_eligibility_package_boundaries.py",
        "tests/test_grade_item_membership_storage.py",
        "tests/test_grade_item_memberships.py",
        "tests/test_grade_item_storage.py",
        "tests/test_grade_items.py",
        "tests/test_grouping_signal_contract.py",
        "tests/test_grouping_signal_diagnostics_contract.py",
        "tests/test_grouping_signal_storage_contract.py",
        "tests/test_grouping_signal_policy.py",
        "tests/test_grouping_signal_policy_storage.py",
        "tests/test_grouping_signal_policy_integration.py",
        "tests/test_grouping_signal_policy_storage_hardening.py",
        "tests/test_grouping_signal_policy_package_boundaries.py",
        "tests/test_grouping_signal_derivation.py",
        "tests/test_grouping_signal_derivation_storage.py",
        "tests/test_grouping_signal_derivation_storage_hardening.py",
        "tests/test_grouping_signal_generation.py",
        "tests/test_grouping_signal_generation_basis.py",
        "tests/test_grouping_signal_generation_integration.py",
        "tests/test_grouping_signal_derivation_package_boundaries.py",
        "tests/test_grouping_signal_currentness.py",
        "tests/test_grouping_signal_preview.py",
        "tests/test_grouping_signal_preview_storage.py",
        "tests/test_grouping_signal_preview_generation.py",
        "tests/test_grouping_signal_preview_projection.py",
        "tests/test_grouping_signal_review.py",
        "tests/test_grouping_signal_review_storage.py",
        "tests/test_grouping_signal_review_workflow.py",
        "tests/test_grouping_signal_preview_package_boundaries.py",
        "tests/test_grouping_signal_export.py",
        "tests/test_grouping_signal_export_eligibility.py",
        "tests/test_grouping_signal_export_workflow.py",
        "tests/test_grouping_signal_export_receipt_workflow.py",
        "tests/test_grouping_signal_csv_export.py",
        "tests/test_grouping_signal_export_package_boundaries.py",
        "tests/test_reassessment.py",
        "tests/test_reassessment_storage.py",
        "tests/test_reassessment_integration.py",
        "tests/test_reassessment_package_boundaries.py",
        "tests/test_proficiency_mapping.py",
        "tests/test_proficiency_mapping_storage.py",
        "tests/test_proficiency_mapping_integration.py",
        "tests/test_proficiency_mapping_package_boundaries.py",
        "tests/test_standards_evidence.py",
        "tests/test_standards_evidence_storage.py",
        "tests/test_standards_evidence_integration.py",
        "tests/test_standards_evidence_package_boundaries.py",
        "tests/test_standards_proficiency.py",
        "tests/test_standards_proficiency_storage.py",
        "tests/test_standards_proficiency_results.py",
        "tests/test_standards_proficiency_result_storage.py",
        "tests/test_standards_proficiency_freshness.py",
        "tests/test_standards_proficiency_integration.py",
        "tests/test_standards_proficiency_package_boundaries.py",
        "tests/test_validation_scripts.py",
        "tests/test_teacher_workflows.py",
        "tests/test_standards_review_workflow.py",
        "tests/test_standards_association_authoring_workflow.py",
        "tests/test_standards_association_selection_workflow.py",
        "tests/test_cli_standards_review_workflow.py",
        "tests/test_cli_standards_association_authoring.py",
        "tests/test_cli_standards_association_selection.py",
        "tests/test_cli_teacher_workflows.py",
        "tests/test_cli_new_evidence_workflow.py",
        "tests/test_cli_new_evidence_eligibility_authoring.py",
        "tests/test_cli_new_evidence_eligibility_selection.py",
        "tests/test_grade_items_workflow.py",
        "tests/test_grade_item_authoring_workflow.py",
        "tests/test_grade_item_selection_workflow.py",
        "tests/test_grade_item_membership_authoring_workflow.py",
        "tests/test_grade_item_membership_selection_workflow.py",
        "tests/test_cli_grade_items_workflow.py",
        "tests/test_cli_grade_item_authoring.py",
        "tests/test_cli_grade_item_selection.py",
        "tests/test_cli_grade_item_membership_authoring.py",
        "tests/test_cli_grade_item_membership_selection.py",
        "tests/test_new_evidence_workflow.py",
        "tests/test_new_evidence_eligibility_workflow.py",
        "tests/test_new_evidence_eligibility_selection_workflow.py",
    }
)
FORBIDDEN_PREFIXES = (
    ".git/",
    ".venv/",
    "venv/",
    "build/",
    "dist/",
    "pds_core/",
    "scoreform/",
    "quillan/",
    "concord/",
    "portia/",
    "vitrine/",
    "classes/",
    "registry/",
    "settings/",
)
FORBIDDEN_COMPONENTS = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".coverage",
        "htmlcov",
    }
)


class SdistValidationError(ValueError):
    """Raised when a source distribution violates the release boundary."""


def _relative_member(name: str) -> PurePosixPath | None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise SdistValidationError(f"Source distribution has unsafe path: {name}")
    if not path.parts or path.parts[0] != EXPECTED_ROOT:
        raise SdistValidationError(
            f"Source distribution member is outside {EXPECTED_ROOT!r}: {name}"
        )
    if len(path.parts) == 1:
        return None
    return PurePosixPath(*path.parts[1:])


def _pkg_info(archive: tarfile.TarFile) -> Message:
    target = f"{EXPECTED_ROOT}/PKG-INFO"
    matches = [member for member in archive.getmembers() if member.name == target]
    if len(matches) != 1 or not matches[0].isfile():
        raise SdistValidationError(
            "Source distribution must contain exactly one top-level PKG-INFO."
        )
    source = archive.extractfile(matches[0])
    if source is None:
        raise SdistValidationError("Source distribution PKG-INFO is unreadable.")
    return BytesParser().parsebytes(source.read())


def validate_sdist(path: str | Path) -> None:
    """Validate one built Meridian sdist without extracting it."""
    sdist = Path(path)
    if sdist.name != EXPECTED_SDIST_FILENAME:
        raise SdistValidationError(
            f"Expected {EXPECTED_SDIST_FILENAME!r}, got {sdist.name!r}."
        )
    if not sdist.is_file():
        raise SdistValidationError(f"Source distribution does not exist: {sdist}")

    try:
        with tarfile.open(sdist, mode="r:gz") as archive:
            metadata = _pkg_info(archive)
            relative_files: set[str] = set()
            for member in archive.getmembers():
                relative = _relative_member(member.name)
                if member.issym() or member.islnk():
                    raise SdistValidationError(
                        f"Source distribution contains a link: {member.name}"
                    )
                if not (member.isfile() or member.isdir()):
                    raise SdistValidationError(
                        "Source distribution contains an unsupported tar member: "
                        f"{member.name}"
                    )
                if relative is None or member.isdir():
                    continue
                normalized = relative.as_posix()
                lowered = normalized.lower()
                components = {part.lower() for part in relative.parts}
                if lowered.startswith(FORBIDDEN_PREFIXES):
                    raise SdistValidationError(
                        f"Source distribution contains forbidden content: {normalized}"
                    )
                if components.intersection(FORBIDDEN_COMPONENTS) or any(
                    "credential" in part for part in components
                ):
                    raise SdistValidationError(
                        f"Source distribution contains forbidden content: {normalized}"
                    )
                relative_files.add(normalized)
    except (tarfile.TarError, OSError) as error:
        raise SdistValidationError(
            "Source distribution is not a readable gzip tar archive."
        ) from error

    if metadata["Name"] != EXPECTED_DISTRIBUTION:
        raise SdistValidationError("Source distribution name must be pds-meridian.")
    if metadata["Version"] != EXPECTED_VERSION:
        raise SdistValidationError(
            f"Source distribution version must be {EXPECTED_VERSION}."
        )
    if metadata["Summary"] != EXPECTED_SUMMARY:
        raise SdistValidationError(
            "Source distribution summary must describe only the implemented "
            "release surface."
        )

    missing = sorted(REQUIRED_MEMBERS - relative_files)
    if missing:
        raise SdistValidationError(
            f"Source distribution is missing required source members: {missing!r}."
        )


def main(argv: list[str] | None = None) -> int:
    """Validate one built Meridian source distribution."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdist", type=Path)
    args = parser.parse_args(argv)
    validate_sdist(args.sdist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
