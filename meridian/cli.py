"""Command-line diagnostics and teacher workflows for Meridian."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from pds_core.academic_catalog import PublicationCatalogQuery
from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
)
from pds_core.publication_records import PUBLICATION_CAPABILITIES
from pds_core.routing_models import ModuleWorkRef, RoutingModelError

from meridian import __version__
from meridian.academic_period_calculation_assembly_workflow import (
    AcademicPeriodCalculationAssemblyError,
    AcademicPeriodCalculationAssemblyScopeError,
    AcademicPeriodCalculationCandidateSpec,
    AcademicPeriodMembershipSpec,
    BoundedAcademicPeriodCalculationPreview,
    build_bounded_academic_period_calculation_preview,
)
from meridian.academic_period_calculation_preview_workflow import (
    AcademicPeriodCalculationPreviewWorkflowError,
)
from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyAggregationPolicyReference,
    AcademicPeriodProficiencyTarget,
)
from meridian.academic_period_result_persistence_workflow import (
    AcademicPeriodResultPersistenceError,
    AcademicPeriodResultPersistencePreview,
    AcademicPeriodResultPersistenceWorkflowResult,
    commit_academic_period_result_persistence_preview,
    preview_academic_period_result_persistence,
)
from meridian.academic_period_result_selection_workflow import (
    AcademicPeriodResultSelectionError,
    AcademicPeriodResultSelectionPreview,
    AcademicPeriodResultSelectionWorkflowResult,
    commit_academic_period_result_selection_preview,
    preview_academic_period_result_selection,
)
from meridian.attempt_decision_authoring_workflow import (
    AttemptDecisionAuthoringPreview,
    AttemptDecisionAuthoringResult,
    AttemptDecisionAuthoringScopeError,
    AttemptDecisionAuthoringWorkflowError,
    commit_attempt_decision_authoring_preview,
    preview_attempt_decision_authoring,
)
from meridian.attempt_decision_selection_workflow import (
    AttemptDecisionSelectionPreview,
    AttemptDecisionSelectionWorkflowError,
    AttemptDecisionSelectionWorkflowResult,
    commit_attempt_decision_selection_preview,
    preview_attempt_decision_selection,
)
from meridian.attempt_decisions_workflow import (
    AttemptDecisionWorkflowError,
    AttemptDecisionWorkflowProjection,
    project_attempt_decisions,
)
from meridian.attempt_policy_authoring_workflow import (
    AttemptPolicyAuthoringPreview,
    AttemptPolicyAuthoringResult,
    AttemptPolicyAuthoringScopeError,
    AttemptPolicyAuthoringWorkflowError,
    commit_attempt_policy_authoring_preview,
    preview_attempt_policy_authoring,
)
from meridian.attempt_policy_selection_workflow import (
    AttemptPolicySelectionPreview,
    AttemptPolicySelectionScopeError,
    AttemptPolicySelectionWorkflowError,
    AttemptPolicySelectionWorkflowResult,
    commit_attempt_policy_selection_preview,
    preview_attempt_policy_selection,
)
from meridian.attempt_selection import AttemptObservationReference
from meridian.attempt_selection_storage import (
    AttemptSelectionStorageError,
    derive_attempt_candidates,
)
from meridian.calculation_preview_assembly_workflow import (
    BoundedCalculationPreview,
    CalculationPreviewAssemblyDependencyError,
    CalculationPreviewAssemblyError,
    CalculationPreviewAssemblyScopeError,
    build_bounded_calculation_preview,
)
from meridian.calculation_preview_workflow import (
    CalculationPreviewWorkflowError,
)
from meridian.calculation_result_persistence_workflow import (
    CalculationResultPersistenceError,
    CalculationResultPersistencePreview,
    CalculationResultPersistenceWorkflowResult,
    commit_calculation_result_persistence_preview,
    preview_calculation_result_persistence,
)
from meridian.calculation_result_selection_workflow import (
    CalculationResultSelectionError,
    CalculationResultSelectionPreview,
    CalculationResultSelectionWorkflowResult,
    commit_calculation_result_selection_preview,
    preview_calculation_result_selection,
)
from meridian.diagnostics import (
    DiagnosticsDependencies,
    DiagnosticsError,
    EvidenceExplanationDiagnostic,
    EvidenceFilters,
    EvidenceInspectionDiagnostic,
    PublicationListDiagnostic,
    PublicationVerificationDiagnostic,
    default_diagnostics_dependencies,
    evidence_explanation_to_dict,
    evidence_inspection_to_dict,
    explain_evidence_diagnostic,
    inspect_evidence_diagnostic,
    list_publication_diagnostics,
    publication_list_to_dict,
    publication_verification_to_dict,
    verify_publication_diagnostic,
)
from meridian.evidence import (
    EvidenceItem,
    NativePointValue,
    NativeScalarValue,
    NativeScaledValue,
    NativeStateValue,
)
from meridian.evidence_eligibility import EvidenceSourceReference
from meridian.evidence_eligibility_storage import EvidenceEligibilityStorageError
from meridian.exclusions_eligibility_authoring_workflow import (
    ExclusionAcademicDisposition,
    ExclusionEligibilityAuthoringError,
    ExclusionEligibilityAuthoringPreview,
    ExclusionEligibilityAuthoringResult,
    commit_exclusion_eligibility_authoring_preview,
    preview_exclusion_eligibility_authoring,
)
from meridian.exclusions_eligibility_selection_workflow import (
    ExclusionEligibilitySelectionError,
    ExclusionEligibilitySelectionPreview,
    ExclusionEligibilitySelectionWorkflowResult,
    commit_exclusion_eligibility_selection_preview,
    preview_exclusion_eligibility_selection,
)
from meridian.exclusions_workflow import (
    ExclusionsProjection,
    ExclusionsWorkflowError,
    build_exclusions_projection,
)
from meridian.grade_item_authoring_workflow import (
    GradeItemAuthoringPreview,
    GradeItemAuthoringResult,
    GradeItemAuthoringScopeError,
    GradeItemAuthoringWorkflowError,
    GradeItemWeightingAction,
    commit_grade_item_authoring_preview,
    preview_grade_item_authoring,
)
from meridian.grade_item_membership_authoring_workflow import (
    GradeItemMembershipAuthoringError,
    GradeItemMembershipAuthoringPreview,
    GradeItemMembershipAuthoringResult,
    GradeItemMembershipAuthoringScopeError,
    commit_grade_item_membership_authoring_preview,
    preview_grade_item_membership_authoring,
)
from meridian.grade_item_membership_selection_workflow import (
    GradeItemMembershipSelectionPreview,
    GradeItemMembershipSelectionScopeError,
    GradeItemMembershipSelectionWorkflowError,
    GradeItemMembershipSelectionWorkflowResult,
    commit_grade_item_membership_selection_preview,
    preview_grade_item_membership_selection,
)
from meridian.grade_item_membership_storage import GradeItemMembershipStorageError
from meridian.grade_item_memberships import (
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipValidationError,
)
from meridian.grade_item_selection_workflow import (
    GradeItemSelectionPreview,
    GradeItemSelectionWorkflowError,
    GradeItemSelectionWorkflowResult,
    commit_grade_item_selection_preview,
    preview_grade_item_selection,
)
from meridian.grade_item_storage import GradeItemStorageError
from meridian.grade_items import (
    GradeItemValidationError,
    GradeItemWeightingMetadata,
    grade_item_revision_to_dict,
)
from meridian.grade_items_workflow import (
    GradeItemsReview,
    GradeItemsWorkflowError,
    grade_items_review_to_dict,
    project_grade_items_review,
)
from meridian.ingestion import PublicationDiscoveryRequest, PublicationIngestionError
from meridian.new_evidence_eligibility_selection_workflow import (
    NewEvidenceEligibilitySelectionError,
    NewEvidenceEligibilitySelectionPreview,
    NewEvidenceEligibilitySelectionWorkflowResult,
    commit_new_evidence_eligibility_selection_preview,
    preview_new_evidence_eligibility_selection,
)
from meridian.new_evidence_eligibility_workflow import (
    NewEvidenceEligibilityAuthoringError,
    NewEvidenceEligibilityAuthoringPreview,
    NewEvidenceEligibilityAuthoringResult,
    commit_new_evidence_eligibility_preview,
    preview_new_evidence_eligibility_revision,
)
from meridian.new_evidence_workflow import (
    NewEvidenceReview,
    NewEvidenceWorkflowError,
    new_evidence_review_to_dict,
    project_new_evidence_review,
)
from meridian.planning_signal_derivation_persistence_workflow import (
    PlanningSignalDerivationPersistenceError,
    PlanningSignalDerivationPersistencePreview,
    PlanningSignalDerivationPersistenceResult,
    commit_planning_signal_derivation_persistence_preview,
    preview_planning_signal_derivation_persistence,
)
from meridian.planning_signal_preview_write_workflow import (
    PlanningSignalPreviewWriteError,
    PlanningSignalPreviewWritePreview,
    PlanningSignalPreviewWriteResult,
    PlanningSignalPreviewWriteScopeError,
    commit_planning_signal_preview_write,
    preview_planning_signal_preview_write,
)
from meridian.planning_signal_workflow import (
    PlanningSignalReadinessProjection,
    PlanningSignalWorkflowError,
    project_planning_signal_readiness,
)
from meridian.proficiency_mapping import (
    NativeValueMappingProfileReference,
    ProficiencyScaleReference,
)
from meridian.projection_cache import ProjectionCacheError
from meridian.standards_association_authoring_workflow import (
    StandardsAssociationAuthoringError,
    StandardsAssociationAuthoringPreview,
    StandardsAssociationAuthoringResult,
    commit_standards_association_authoring_preview,
    preview_standards_association_authoring,
)
from meridian.standards_association_selection_workflow import (
    StandardsAssociationSelectionError,
    StandardsAssociationSelectionPreview,
    StandardsAssociationSelectionWorkflowResult,
    commit_standards_association_selection_preview,
    preview_standards_association_selection,
)
from meridian.standards_evidence_storage import (
    StandardAggregationCandidateBinding,
)
from meridian.standards_proficiency import (
    StandardProficiencyCalculationPolicyReference,
)
from meridian.standards_review_workflow import (
    StandardsReviewProjection,
    StandardsReviewWorkflowError,
    StandardsReviewWorkflowScopeError,
    build_standards_review_projection,
)
from meridian.teacher_workflows import (
    TeacherWorkflowCatalog,
    teacher_workflow_catalog,
    teacher_workflow_catalog_to_dict,
)


def _datetime_argument(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an ISO 8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _decimal_argument(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError(
            "expected decimal text"
        ) from error


def _positive_integer(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a positive integer") from error
    if result <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return result


def _sha256_argument(value: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise argparse.ArgumentTypeError(
            "expected a lowercase 64-character SHA-256 digest"
        )
    return value


def _nonnegative_integer(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a nonnegative integer") from error
    if result < 0:
        raise argparse.ArgumentTypeError("expected a nonnegative integer")
    return result


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser without touching workspace or producer state."""
    parser = argparse.ArgumentParser(
        prog="meridian",
        description=(
            "Meridian is the Paper Data Suite "
            "publication-ingestion and typed-evidence diagnostics foundation. "
            "Grade Item-level and Academic Period standards-proficiency "
            "calculations are implemented as library APIs; Grade calculation "
            "and reporting stages are not implemented yet."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    groups = parser.add_subparsers(dest="command_group")

    publications = groups.add_parser(
        "publications",
        help="List Core publication candidates or verify one canonical publication.",
    )
    publication_commands = publications.add_subparsers(dest="publication_command")

    list_parser = publication_commands.add_parser(
        "list",
        help="List bounded catalog candidates and reconcile them with canonical state.",
    )
    _add_workspace_argument(list_parser)
    list_parser.add_argument("--school-year")
    list_parser.add_argument("--class-id")
    list_parser.add_argument("--module-id")
    list_parser.add_argument("--work-id")
    list_parser.add_argument(
        "--publication-kind",
        choices=("academic_result_set", "intervention_record_set"),
    )
    list_parser.add_argument(
        "--capability",
        action="append",
        choices=tuple(sorted(PUBLICATION_CAPABILITIES)),
        default=[],
        help="Require one Core publication capability; repeat for AND semantics.",
    )
    list_parser.add_argument("--producer-contract-version")
    list_parser.add_argument("--manifest-contract-version")
    list_parser.add_argument("--source-contract-version")
    list_parser.add_argument("--referenced-registration-lifecycle")
    list_parser.add_argument("--current-registration-lifecycle")
    list_parser.add_argument("--record-set-id")
    list_parser.add_argument("--minimum-record-set-revision", type=_positive_integer)
    list_parser.add_argument("--published-at-or-after", type=_datetime_argument)
    list_parser.add_argument("--published-before", type=_datetime_argument)
    list_parser.add_argument(
        "--state",
        choices=("current", "series_heads", "historical", "withdrawn", "all"),
        default="current",
    )
    list_parser.add_argument("--limit", type=_positive_integer, default=50)
    list_parser.add_argument("--offset", type=_nonnegative_integer, default=0)
    _add_format_argument(list_parser)
    list_parser.set_defaults(handler=_handle_publication_list)

    verify_parser = publication_commands.add_parser(
        "verify",
        help=(
            "Verify canonical contract support/readiness without reading "
            "manifest bytes."
        ),
    )
    verify_parser.add_argument("publication_id")
    _add_workspace_argument(verify_parser)
    _add_format_argument(verify_parser)
    verify_parser.set_defaults(handler=_handle_publication_verify)

    evidence = groups.add_parser(
        "evidence",
        help="Inspect and explain authorized persisted evidence.",
    )
    evidence_commands = evidence.add_subparsers(dest="evidence_command")

    inspect_parser = evidence_commands.add_parser(
        "inspect",
        help="Inspect one exact authorized persisted EvidenceInventory.",
    )
    inspect_parser.add_argument("publication_id")
    inspect_parser.add_argument("cache_key")
    _add_workspace_argument(inspect_parser)
    _add_evidence_authorization_arguments(inspect_parser)
    inspect_parser.add_argument("--item-id", action="append", default=[])
    inspect_parser.add_argument("--student-id", action="append", default=[])
    inspect_parser.add_argument("--target-kind", action="append", default=[])
    inspect_parser.add_argument("--standard-id", action="append", default=[])
    inspect_parser.add_argument("--result-kind", action="append", default=[])
    inspect_parser.add_argument(
        "--eligibility",
        action="append",
        choices=("unevaluated", "eligible", "ineligible"),
        default=[],
    )
    _add_format_argument(inspect_parser)
    inspect_parser.set_defaults(
        handler=_handle_evidence_inspect, show_group_help=None
    )

    explain_parser = evidence_commands.add_parser(
        "explain",
        help="Explain current-use/cache state and existing evidence eligibility.",
    )
    explain_parser.add_argument("publication_id")
    explain_parser.add_argument("cache_key")
    _add_workspace_argument(explain_parser)
    _add_evidence_authorization_arguments(explain_parser)
    _add_format_argument(explain_parser)
    explain_parser.set_defaults(
        handler=_handle_evidence_explain, show_group_help=None
    )

    evidence.set_defaults(show_group_help=evidence)

    workflow = groups.add_parser(
        "workflow",
        help="Enter the task-oriented teacher workflow surface.",
        description="Enter the task-oriented teacher workflow surface for issue #41.",
    )
    workflow_commands = workflow.add_subparsers(dest="workflow_command")
    workflow_list_parser = workflow_commands.add_parser(
        "list",
        help="List the seven canonical issue #41 teacher workflow tasks.",
    )
    _add_format_argument(workflow_list_parser)
    workflow_list_parser.set_defaults(
        handler=_handle_teacher_workflow_list, show_group_help=None
    )
    new_evidence_parser = workflow_commands.add_parser(
        "new-evidence",
        help="Review one authorized evidence projection for a Grade Item.",
        description=(
            "Review one already-authorized exact evidence projection against "
            "selected Grade Item membership and eligibility state. This command "
            "is read-only."
        ),
    )
    new_evidence_parser.add_argument("publication_id")
    new_evidence_parser.add_argument("cache_key")
    new_evidence_parser.add_argument("grade_item_id")
    _add_workspace_argument(new_evidence_parser)
    _add_evidence_authorization_arguments(new_evidence_parser)
    _add_format_argument(new_evidence_parser)
    new_evidence_parser.set_defaults(
        handler=_handle_new_evidence_review, show_group_help=None
    )
    new_evidence_author_parser = workflow_commands.add_parser(
        "new-evidence-author",
        help="Preview or write one teacher eligibility revision.",
        description=(
            "Preview one exact teacher-authored eligibility revision. "
            "No state is written unless --confirm-write is supplied; "
            "writing never selects the revision as current."
        ),
    )
    new_evidence_author_parser.add_argument("publication_id")
    new_evidence_author_parser.add_argument("cache_key")
    new_evidence_author_parser.add_argument("grade_item_id")
    new_evidence_author_parser.add_argument("item_id")
    _add_workspace_argument(new_evidence_author_parser)
    _add_evidence_authorization_arguments(new_evidence_author_parser)
    new_evidence_author_parser.add_argument(
        "--disposition",
        required=True,
        choices=("included", "excluded", "pending", "unsupported"),
    )
    new_evidence_author_parser.add_argument("--actor-id", required=True)
    new_evidence_author_parser.add_argument("--policy-id", required=True)
    new_evidence_author_parser.add_argument("--policy-version", required=True)
    new_evidence_author_parser.add_argument(
        "--reason-code", action="append", default=[]
    )
    new_evidence_author_parser.add_argument("--rationale")
    new_evidence_author_parser.add_argument(
        "--confirm-write",
        action="store_true",
        help=(
            "Write the exact preview after live revalidation. Omit to "
            "preview/cancel with no state change."
        ),
    )
    _add_format_argument(new_evidence_author_parser)
    new_evidence_author_parser.set_defaults(
        handler=_handle_new_evidence_eligibility_authoring,
        show_group_help=None,
    )
    new_evidence_select_parser = workflow_commands.add_parser(
        "new-evidence-select",
        help="Preview or select one persisted eligibility revision.",
        description=(
            "Preview one exact persisted eligibility revision and, only "
            "with --confirm-select, select it as current after live CAS "
            "revalidation. This command does not author eligibility records."
        ),
    )
    new_evidence_select_parser.add_argument("publication_id")
    new_evidence_select_parser.add_argument("cache_key")
    new_evidence_select_parser.add_argument("grade_item_id")
    new_evidence_select_parser.add_argument("item_id")
    new_evidence_select_parser.add_argument(
        "eligibility_revision", type=_positive_integer
    )
    _add_workspace_argument(new_evidence_select_parser)
    _add_evidence_authorization_arguments(new_evidence_select_parser)
    new_evidence_select_parser.add_argument(
        "--confirm-select",
        action="store_true",
        help=(
            "Select the exact previewed revision after live CAS "
            "revalidation. Omit to preview/cancel with no selector change."
        ),
    )
    _add_format_argument(new_evidence_select_parser)
    new_evidence_select_parser.set_defaults(
        handler=_handle_new_evidence_eligibility_selection,
        show_group_help=None,
    )
    grade_items_parser = workflow_commands.add_parser(
        "grade-items",
        help="Review explicit Grade Item and membership selector state.",
        description=(
            "Review canonical Grade Item histories, explicit current "
            "Grade Item selectors, and explicit per-work membership "
            "selectors. This command is read-only and performs no "
            "Grade calculation."
        ),
    )
    grade_items_parser.add_argument("class_id")
    _add_workspace_argument(grade_items_parser)
    _add_format_argument(grade_items_parser)
    grade_items_parser.set_defaults(
        handler=_handle_grade_items_review,
        show_group_help=None,
    )
    grade_items_author_parser = workflow_commands.add_parser(
        "grade-items-author",
        help="Preview or write one immutable Grade Item revision.",
        description=(
            "Preview an exact Grade Item create/revise/archive/reactivate "
            "revision and, only with --confirm-write, persist that immutable "
            "revision after live history revalidation. Writing does not "
            "select the revision as current."
        ),
    )
    grade_items_author_parser.add_argument("class_id")
    grade_items_author_parser.add_argument("grade_item_id")
    _add_workspace_argument(grade_items_author_parser)
    grade_items_author_parser.add_argument(
        "--operation",
        required=True,
        choices=("create", "revise", "archive", "reactivate"),
    )
    grade_items_author_parser.add_argument("--actor-id", required=True)
    grade_items_author_parser.add_argument(
        "--revised-at", required=True, type=_datetime_argument
    )
    grade_items_author_parser.add_argument("--title")
    grade_items_author_parser.add_argument(
        "--purpose",
        choices=(
            "standards_proficiency",
            "conventional_grade",
            "standards_and_conventional",
            "reporting_only",
        ),
    )
    grade_items_author_parser.add_argument("--weighting-category-id")
    grade_items_author_parser.add_argument(
        "--relative-weight", type=_decimal_argument
    )
    grade_items_author_parser.add_argument(
        "--clear-weighting",
        action="store_true",
        help=(
            "Explicitly clear weighting metadata on revise. Cannot be "
            "combined with weighting replacement fields."
        ),
    )
    grade_items_author_parser.add_argument(
        "--confirm-write",
        action="store_true",
        help=(
            "Write the exact previewed immutable revision after live "
            "history revalidation. Omit to preview/cancel with no write."
        ),
    )
    _add_format_argument(grade_items_author_parser)
    grade_items_author_parser.set_defaults(
        handler=_handle_grade_item_authoring,
        show_group_help=None,
    )
    grade_items_select_parser = workflow_commands.add_parser(
        "grade-items-select",
        help="Preview or select one persisted Grade Item revision.",
        description=(
            "Preview one exact persisted Grade Item revision and, only "
            "with --confirm-select, select it as current after live CAS "
            "revalidation. This command does not author Grade Item revisions."
        ),
    )
    grade_items_select_parser.add_argument("class_id")
    grade_items_select_parser.add_argument("grade_item_id")
    grade_items_select_parser.add_argument(
        "grade_item_revision", type=_positive_integer
    )
    _add_workspace_argument(grade_items_select_parser)
    grade_items_select_parser.add_argument(
        "--confirm-select",
        action="store_true",
        help=(
            "Select the exact previewed revision after live CAS "
            "revalidation. Omit to preview/cancel with no selector change."
        ),
    )
    _add_format_argument(grade_items_select_parser)
    grade_items_select_parser.set_defaults(
        handler=_handle_grade_item_selection,
        show_group_help=None,
    )
    membership_author_parser = workflow_commands.add_parser(
        "grade-items-membership-author",
        help="Preview or write one Grade Item membership revision.",
        description=(
            "Preview one explicit Grade Item/work membership decision and, "
            "only with --confirm-write, persist its immutable revision. "
            "Writing never selects the new membership revision."
        ),
    )
    membership_author_parser.add_argument("class_id")
    membership_author_parser.add_argument("grade_item_id")
    membership_author_parser.add_argument("module_id")
    membership_author_parser.add_argument("work_id")
    _add_workspace_argument(membership_author_parser)
    membership_author_parser.add_argument(
        "--operation", choices=("create", "revise"), required=True
    )
    membership_author_parser.add_argument(
        "--grade-item-revision", type=_positive_integer, required=True
    )
    membership_author_parser.add_argument(
        "--registration-revision", type=_positive_integer, required=True
    )
    membership_author_parser.add_argument(
        "--decision", choices=("included", "excluded"), required=True
    )
    membership_author_parser.add_argument("--actor-id", required=True)
    membership_author_parser.add_argument(
        "--decided-at", type=_datetime_argument, required=True
    )
    membership_author_parser.add_argument("--school-year")
    membership_author_parser.add_argument("--period-id")
    membership_author_parser.add_argument(
        "--calendar-revision", type=_positive_integer
    )
    membership_author_parser.add_argument("--rationale")
    membership_author_parser.add_argument(
        "--confirm-write",
        action="store_true",
        help=(
            "Write the exact previewed immutable membership revision after "
            "live revalidation. Omit for a read-only preview."
        ),
    )
    _add_format_argument(membership_author_parser)
    membership_author_parser.set_defaults(
        handler=_handle_grade_item_membership_authoring,
        show_group_help=None,
    )
    membership_select_parser = workflow_commands.add_parser(
        "grade-items-membership-select",
        help="Preview or select one Grade Item membership revision.",
        description=(
            "Preview one exact persisted membership decision and, only "
            "with --confirm-select, select it as operative after live CAS "
            "revalidation. Selection does not author membership history."
        ),
    )
    membership_select_parser.add_argument("class_id")
    membership_select_parser.add_argument("grade_item_id")
    membership_select_parser.add_argument("module_id")
    membership_select_parser.add_argument("work_id")
    membership_select_parser.add_argument(
        "membership_revision", type=_positive_integer
    )
    _add_workspace_argument(membership_select_parser)
    membership_select_parser.add_argument(
        "--confirm-select",
        action="store_true",
        help=(
            "Select the exact previewed membership revision after live "
            "CAS revalidation. Omit for a read-only preview."
        ),
    )
    _add_format_argument(membership_select_parser)
    membership_select_parser.set_defaults(
        handler=_handle_grade_item_membership_selection,
        show_group_help=None,
    )
    attempt_decisions_parser = workflow_commands.add_parser(
        "attempt-decisions",
        help="Review explicit attempt candidates and current selection.",
        description=(
            "Review the exact #30 attempt candidate and current-selection "
            "state for one student in one authorized projection. This "
            "command is read-only and applies no ranking heuristic."
        ),
    )
    attempt_decisions_parser.add_argument("publication_id")
    attempt_decisions_parser.add_argument("cache_key")
    attempt_decisions_parser.add_argument("grade_item_id")
    attempt_decisions_parser.add_argument("student_id")
    _add_workspace_argument(attempt_decisions_parser)
    _add_evidence_authorization_arguments(attempt_decisions_parser)
    _add_format_argument(attempt_decisions_parser)
    attempt_decisions_parser.set_defaults(
        handler=_handle_attempt_decisions_review,
        show_group_help=None,
    )
    attempt_policy_author_parser = workflow_commands.add_parser(
        "attempt-policy-author",
        help="Preview or write an explicit attempt-selection policy.",
        description=(
            "Preview one immutable explicit-selection policy revision and, "
            "only with --confirm-write, persist it. Writing never selects "
            "the policy as current."
        ),
    )
    attempt_policy_author_parser.add_argument("class_id")
    attempt_policy_author_parser.add_argument("grade_item_id")
    attempt_policy_author_parser.add_argument("module_id")
    attempt_policy_author_parser.add_argument("work_id")
    attempt_policy_author_parser.add_argument("policy_id")
    _add_workspace_argument(attempt_policy_author_parser)
    attempt_policy_author_parser.add_argument(
        "--operation", choices=("create", "revise"), required=True
    )
    attempt_policy_author_parser.add_argument(
        "--minimum-selected", type=_nonnegative_integer, required=True
    )
    attempt_policy_author_parser.add_argument(
        "--maximum-selected", type=_nonnegative_integer
    )
    attempt_policy_author_parser.add_argument("--actor-id", required=True)
    attempt_policy_author_parser.add_argument(
        "--revised-at", type=_datetime_argument, required=True
    )
    attempt_policy_author_parser.add_argument("--rationale")
    attempt_policy_author_parser.add_argument(
        "--confirm-write",
        action="store_true",
        help=(
            "Persist the exact previewed policy revision after live "
            "history revalidation. Omit for a read-only preview."
        ),
    )
    _add_format_argument(attempt_policy_author_parser)
    attempt_policy_author_parser.set_defaults(
        handler=_handle_attempt_policy_authoring,
        show_group_help=None,
    )
    attempt_policy_select_parser = workflow_commands.add_parser(
        "attempt-policy-select",
        help=(
            "Preview or select one persisted attempt-selection policy."
        ),
        description=(
            "Preview one exact persisted attempt-selection policy revision "
            "and, only with --confirm-select, select it as current after "
            "live CAS revalidation. Historical revisions are valid explicit "
            "targets. This command does not author policy history."
        ),
    )
    attempt_policy_select_parser.add_argument("class_id")
    attempt_policy_select_parser.add_argument("grade_item_id")
    attempt_policy_select_parser.add_argument("module_id")
    attempt_policy_select_parser.add_argument("work_id")
    attempt_policy_select_parser.add_argument("policy_id")
    attempt_policy_select_parser.add_argument(
        "policy_revision", type=_positive_integer
    )
    _add_workspace_argument(attempt_policy_select_parser)
    attempt_policy_select_parser.add_argument(
        "--confirm-select",
        action="store_true",
        help=(
            "Select the exact previewed policy revision after live CAS "
            "revalidation. Omit for a read-only preview."
        ),
    )
    _add_format_argument(attempt_policy_select_parser)
    attempt_policy_select_parser.set_defaults(
        handler=_handle_attempt_policy_selection,
        show_group_help=None,
    )
    attempt_decision_author_parser = workflow_commands.add_parser(
        "attempt-decision-author",
        help="Preview or write one explicit student attempt decision.",
        description=(
            "Resolve explicit native attempt identities against the exact "
            "current authorized candidate set, preview one immutable student "
            "decision revision, and write it only with --confirm-write. "
            "Writing does not select the decision as current."
        ),
    )
    attempt_decision_author_parser.add_argument("publication_id")
    attempt_decision_author_parser.add_argument("cache_key")
    attempt_decision_author_parser.add_argument("grade_item_id")
    attempt_decision_author_parser.add_argument("student_id")
    attempt_decision_author_parser.add_argument("policy_id")
    _add_workspace_argument(attempt_decision_author_parser)
    _add_evidence_authorization_arguments(attempt_decision_author_parser)
    attempt_decision_author_parser.add_argument(
        "--select-sequence",
        action="append",
        type=_positive_integer,
        default=[],
        help="Select one exact native attempt sequence; repeat as needed.",
    )
    attempt_decision_author_parser.add_argument(
        "--select-identifier",
        action="append",
        default=[],
        help="Select one exact native attempt identifier; repeat as needed.",
    )
    attempt_decision_author_parser.add_argument("--actor-id", required=True)
    attempt_decision_author_parser.add_argument(
        "--decided-at", type=_datetime_argument, required=True
    )
    attempt_decision_author_parser.add_argument("--rationale")
    attempt_decision_author_parser.add_argument(
        "--confirm-write", action="store_true",
        help=(
            "Write the exact previewed immutable decision revision after "
            "live dependency revalidation. Omit for a read-only preview."
        ),
    )
    _add_format_argument(attempt_decision_author_parser)
    attempt_decision_author_parser.set_defaults(
        handler=_handle_attempt_decision_authoring,
        show_group_help=None,
    )
    attempt_decision_select_parser = workflow_commands.add_parser(
        "attempt-decision-select",
        help=(
            "Preview or select one persisted student attempt decision."
        ),
        description=(
            "Preview one exact persisted student attempt-decision revision "
            "against the current authorized evidence, membership, policy, "
            "candidate, and eligibility state. Only --confirm-select mutates "
            "the current decision pointer; decision history is unchanged."
        ),
    )
    attempt_decision_select_parser.add_argument("publication_id")
    attempt_decision_select_parser.add_argument("cache_key")
    attempt_decision_select_parser.add_argument("grade_item_id")
    attempt_decision_select_parser.add_argument("student_id")
    attempt_decision_select_parser.add_argument(
        "decision_revision", type=_positive_integer
    )
    _add_workspace_argument(attempt_decision_select_parser)
    _add_evidence_authorization_arguments(attempt_decision_select_parser)
    attempt_decision_select_parser.add_argument(
        "--confirm-select",
        action="store_true",
        help=(
            "Select the exact previewed decision revision after live "
            "dependency and current-pointer revalidation."
        ),
    )
    _add_format_argument(attempt_decision_select_parser)
    attempt_decision_select_parser.set_defaults(
        handler=_handle_attempt_decision_selection,
        show_group_help=None,
    )
    exclusions_parser = workflow_commands.add_parser(
        "exclusions",
        help=(
            "Review academic eligibility separately from source lifecycle."
        ),
        description=(
            "Read one exact authorized projection and show selected #29 "
            "academic eligibility beside current Core source lifecycle. "
            "This command is read-only and never writes or selects "
            "eligibility decisions."
        ),
    )
    exclusions_parser.add_argument("publication_id")
    exclusions_parser.add_argument("cache_key")
    exclusions_parser.add_argument("grade_item_id")
    _add_workspace_argument(exclusions_parser)
    _add_evidence_authorization_arguments(exclusions_parser)
    _add_format_argument(exclusions_parser)
    exclusions_parser.set_defaults(
        handler=_handle_exclusions_workflow,
        show_group_help=None,
    )
    exclusions_author_parser = workflow_commands.add_parser(
        "exclusions-author",
        help=(
            "Preview or write one teacher academic eligibility revision."
        ),
        description=(
            "Create one immutable #29 teacher academic "
            "eligibility revision "
            "from an exact Exclusions review. Preview is read-only. "
            "--confirm-write writes the exact previewed "
            "revision but never "
            "selects it as current."
        ),
    )
    exclusions_author_parser.add_argument("publication_id")
    exclusions_author_parser.add_argument("cache_key")
    exclusions_author_parser.add_argument("grade_item_id")
    exclusions_author_parser.add_argument("item_id")
    _add_workspace_argument(exclusions_author_parser)
    _add_evidence_authorization_arguments(exclusions_author_parser)
    exclusions_author_parser.add_argument(
        "--disposition",
        required=True,
        choices=("included", "excluded", "pending", "unsupported"),
    )
    exclusions_author_parser.add_argument("--actor-id", required=True)
    exclusions_author_parser.add_argument("--policy-id", required=True)
    exclusions_author_parser.add_argument(
        "--policy-version", required=True
    )
    exclusions_author_parser.add_argument(
        "--reason-code",
        action="append",
        default=[],
        help=(
            "Canonical academic eligibility reason code; "
            "repeat as needed."
        ),
    )
    exclusions_author_parser.add_argument("--rationale")
    exclusions_author_parser.add_argument(
        "--decided-at",
        required=True,
        type=_datetime_argument,
    )
    exclusions_author_parser.add_argument(
        "--confirm-write",
        action="store_true",
        help=(
            "Write the exact previewed immutable eligibility revision. "
            "This never changes the current eligibility selector."
        ),
    )
    _add_format_argument(exclusions_author_parser)
    exclusions_author_parser.set_defaults(
        handler=_handle_exclusions_eligibility_authoring,
        show_group_help=None,
    )
    exclusions_select_parser = workflow_commands.add_parser(
        "exclusions-select",
        help=(
            "Preview or select one persisted eligibility revision."
        ),
        description=(
            "Preview one exact persisted #29 eligibility revision "
            "against current authorized evidence, membership, source "
            "lifecycle, and selector state. Only --confirm-select "
            "mutates the current eligibility pointer; no decision "
            "revision is authored."
        ),
    )
    exclusions_select_parser.add_argument("publication_id")
    exclusions_select_parser.add_argument("cache_key")
    exclusions_select_parser.add_argument("grade_item_id")
    exclusions_select_parser.add_argument("item_id")
    exclusions_select_parser.add_argument(
        "eligibility_revision",
        type=_positive_integer,
    )
    _add_workspace_argument(exclusions_select_parser)
    _add_evidence_authorization_arguments(exclusions_select_parser)
    exclusions_select_parser.add_argument(
        "--confirm-select",
        action="store_true",
        help=(
            "Select the exact previewed eligibility revision after "
            "live dependency and current-pointer revalidation."
        ),
    )
    _add_format_argument(exclusions_select_parser)
    exclusions_select_parser.set_defaults(
        handler=_handle_exclusions_eligibility_selection,
        show_group_help=None,
    )
    standards_review_parser = workflow_commands.add_parser(
        "standards-review",
        help=(
            "Review one exact evidence-to-standard interpretation path."
        ),
        description=(
            "Read one authorized evidence item through current Standard "
            "resolution, selected #33 association, explicit mapping context, "
            "and bounded aggregation state. This command never calculates "
            "or persists standards proficiency."
        ),
    )
    standards_review_parser.add_argument("publication_id")
    standards_review_parser.add_argument("cache_key")
    standards_review_parser.add_argument("grade_item_id")
    standards_review_parser.add_argument("student_id")
    standards_review_parser.add_argument("standard_id")
    standards_review_parser.add_argument("item_id")
    standards_review_parser.add_argument("scale_id")
    standards_review_parser.add_argument(
        "scale_revision",
        type=_positive_integer,
    )
    standards_review_parser.add_argument(
        "scale_sha256",
        type=_sha256_argument,
    )
    _add_workspace_argument(standards_review_parser)
    _add_evidence_authorization_arguments(standards_review_parser)
    standards_review_parser.add_argument("--mapping-profile-scale-id")
    standards_review_parser.add_argument("--mapping-profile-id")
    standards_review_parser.add_argument(
        "--mapping-profile-revision",
        type=_positive_integer,
    )
    standards_review_parser.add_argument(
        "--mapping-profile-sha256",
        type=_sha256_argument,
    )
    _add_format_argument(standards_review_parser)
    standards_review_parser.set_defaults(
        handler=_handle_standards_review,
        show_group_help=None,
    )
    standards_author_parser = workflow_commands.add_parser(
        "standards-association-author",
        help=(
            "Preview or write one standards-evidence association revision."
        ),
        description=(
            "Review one exact authorized evidence-to-Standard path, then "
            "preview an immutable #33 association create/revise operation. "
            "Only --confirm-write writes the exact previewed revision, and "
            "writing never selects it as current."
        ),
    )
    standards_author_parser.add_argument("publication_id")
    standards_author_parser.add_argument("cache_key")
    standards_author_parser.add_argument("grade_item_id")
    standards_author_parser.add_argument("student_id")
    standards_author_parser.add_argument("standard_id")
    standards_author_parser.add_argument("item_id")
    standards_author_parser.add_argument("scale_id")
    standards_author_parser.add_argument(
        "scale_revision",
        type=_positive_integer,
    )
    standards_author_parser.add_argument(
        "scale_sha256",
        type=_sha256_argument,
    )
    _add_workspace_argument(standards_author_parser)
    _add_evidence_authorization_arguments(standards_author_parser)
    standards_author_parser.add_argument("--mapping-profile-scale-id")
    standards_author_parser.add_argument("--mapping-profile-id")
    standards_author_parser.add_argument(
        "--mapping-profile-revision",
        type=_positive_integer,
    )
    standards_author_parser.add_argument(
        "--mapping-profile-sha256",
        type=_sha256_argument,
    )
    standards_author_parser.add_argument(
        "--operation",
        required=True,
        choices=("create", "revise"),
    )
    standards_author_parser.add_argument(
        "--disposition",
        required=True,
        choices=("associated", "not_associated"),
    )
    standards_author_parser.add_argument(
        "--basis",
        required=True,
        choices=("producer_declared", "explicit"),
    )
    standards_author_parser.add_argument("--actor-id", required=True)
    standards_author_parser.add_argument("--rationale")
    standards_author_parser.add_argument(
        "--decided-at",
        required=True,
        type=_datetime_argument,
    )
    standards_author_parser.add_argument(
        "--confirm-write",
        action="store_true",
        help=(
            "Write the exact previewed immutable association revision. "
            "This never changes the current association selector."
        ),
    )
    _add_format_argument(standards_author_parser)
    standards_author_parser.set_defaults(
        handler=_handle_standards_association_authoring,
        show_group_help=None,
    )
    standards_select_parser = workflow_commands.add_parser(
        "standards-association-select",
        help=(
            "Preview or select one persisted standards association revision."
        ),
        description=(
            "Review one exact authorized evidence-to-Standard path, then "
            "preview selection of one exact persisted #33 association "
            "revision. Only --confirm-select mutates the current pointer; "
            "selection never authors an association revision."
        ),
    )
    standards_select_parser.add_argument("publication_id")
    standards_select_parser.add_argument("cache_key")
    standards_select_parser.add_argument("grade_item_id")
    standards_select_parser.add_argument("student_id")
    standards_select_parser.add_argument("standard_id")
    standards_select_parser.add_argument("item_id")
    standards_select_parser.add_argument("scale_id")
    standards_select_parser.add_argument(
        "scale_revision",
        type=_positive_integer,
    )
    standards_select_parser.add_argument(
        "scale_sha256",
        type=_sha256_argument,
    )
    standards_select_parser.add_argument(
        "association_revision",
        type=_positive_integer,
    )
    _add_workspace_argument(standards_select_parser)
    _add_evidence_authorization_arguments(standards_select_parser)
    standards_select_parser.add_argument("--mapping-profile-scale-id")
    standards_select_parser.add_argument("--mapping-profile-id")
    standards_select_parser.add_argument(
        "--mapping-profile-revision",
        type=_positive_integer,
    )
    standards_select_parser.add_argument(
        "--mapping-profile-sha256",
        type=_sha256_argument,
    )
    standards_select_parser.add_argument(
        "--confirm-select",
        action="store_true",
        help=(
            "Select the exact previewed persisted association revision "
            "after live review/history/target/current-pointer checks."
        ),
    )
    _add_format_argument(standards_select_parser)
    standards_select_parser.set_defaults(
        handler=_handle_standards_association_selection,
        show_group_help=None,
    )
    calculation_preview_parser = workflow_commands.add_parser(
        "calculation-preview",
        help=(
            "Preview one bounded Grade Item standards-proficiency calculation."
        ),
        description=(
            "Resolve only explicitly supplied evidence bindings into one "
            "exact #33 aggregation input snapshot, then run the pure #34 "
            "calculation. This command never writes or selects a result."
        ),
    )
    calculation_preview_parser.add_argument("class_id")
    calculation_preview_parser.add_argument("grade_item_id")
    calculation_preview_parser.add_argument("student_id")
    calculation_preview_parser.add_argument("standard_id")
    calculation_preview_parser.add_argument("scale_id")
    calculation_preview_parser.add_argument(
        "scale_revision", type=_positive_integer
    )
    calculation_preview_parser.add_argument(
        "scale_sha256", type=_sha256_argument
    )
    calculation_preview_parser.add_argument("policy_id")
    calculation_preview_parser.add_argument(
        "policy_revision", type=_positive_integer
    )
    calculation_preview_parser.add_argument(
        "policy_sha256", type=_sha256_argument
    )
    _add_workspace_argument(calculation_preview_parser)
    _add_evidence_authorization_arguments(calculation_preview_parser)
    calculation_preview_parser.add_argument(
        "--binding",
        nargs=3,
        action="append",
        default=[],
        metavar=("PUBLICATION_ID", "CACHE_KEY", "ITEM_ID"),
        help=(
            "Explicit evidence candidate; repeat as needed. An empty "
            "binding set is allowed and is never populated implicitly."
        ),
    )
    calculation_preview_parser.add_argument(
        "--binding-profile",
        nargs=7,
        action="append",
        default=[],
        metavar=(
            "PUBLICATION_ID",
            "CACHE_KEY",
            "ITEM_ID",
            "SCALE_ID",
            "PROFILE_ID",
            "PROFILE_REVISION",
            "PROFILE_SHA256",
        ),
        help=(
            "Attach one exact #32 mapping profile to one explicitly "
            "named --binding. Repeat for bindings that need profiles."
        ),
    )
    _add_format_argument(calculation_preview_parser)
    calculation_preview_parser.set_defaults(
        handler=_handle_calculation_preview,
        show_group_help=None,
    )
    calculation_write_parser = workflow_commands.add_parser(
        "calculation-result-write",
        help=(
            "Preview or write one immutable Grade Item proficiency result."
        ),
        description=(
            "Rebuild one exact bounded Calculation Preview, freeze the "
            "next immutable #34 result revision, and only with "
            "--confirm-write persist it after live revalidation. Writing "
            "never changes the current result selection."
        ),
    )
    calculation_write_parser.add_argument("class_id")
    calculation_write_parser.add_argument("grade_item_id")
    calculation_write_parser.add_argument("student_id")
    calculation_write_parser.add_argument("standard_id")
    calculation_write_parser.add_argument("scale_id")
    calculation_write_parser.add_argument(
        "scale_revision", type=_positive_integer
    )
    calculation_write_parser.add_argument(
        "scale_sha256", type=_sha256_argument
    )
    calculation_write_parser.add_argument("policy_id")
    calculation_write_parser.add_argument(
        "policy_revision", type=_positive_integer
    )
    calculation_write_parser.add_argument(
        "policy_sha256", type=_sha256_argument
    )
    _add_workspace_argument(calculation_write_parser)
    _add_evidence_authorization_arguments(calculation_write_parser)
    calculation_write_parser.add_argument(
        "--binding",
        nargs=3,
        action="append",
        default=[],
        metavar=("PUBLICATION_ID", "CACHE_KEY", "ITEM_ID"),
    )
    calculation_write_parser.add_argument(
        "--binding-profile",
        nargs=7,
        action="append",
        default=[],
        metavar=(
            "PUBLICATION_ID",
            "CACHE_KEY",
            "ITEM_ID",
            "SCALE_ID",
            "PROFILE_ID",
            "PROFILE_REVISION",
            "PROFILE_SHA256",
        ),
    )
    calculation_write_parser.add_argument("--actor-id", required=True)
    calculation_write_parser.add_argument(
        "--calculated-at",
        required=True,
        type=_datetime_argument,
    )
    calculation_write_parser.add_argument(
        "--confirm-write",
        action="store_true",
        help=(
            "Write the exact previewed immutable result after live "
            "calculation/history revalidation."
        ),
    )
    _add_format_argument(calculation_write_parser)
    calculation_write_parser.set_defaults(
        handler=_handle_calculation_result_persistence,
        show_group_help=None,
    )
    calculation_select_parser = workflow_commands.add_parser(
        "calculation-result-select",
        help=(
            "Preview or select one persisted Grade Item proficiency result."
        ),
        description=(
            "Preview one exact persisted #34 Grade Item proficiency result "
            "revision. Only --confirm-select mutates the current-result "
            "pointer with CAS. No result is authored or recalculated."
        ),
    )
    calculation_select_parser.add_argument("class_id")
    calculation_select_parser.add_argument("grade_item_id")
    calculation_select_parser.add_argument("student_id")
    calculation_select_parser.add_argument("standard_id")
    calculation_select_parser.add_argument(
        "result_revision", type=_positive_integer
    )
    _add_workspace_argument(calculation_select_parser)
    calculation_select_parser.add_argument(
        "--confirm-select",
        action="store_true",
        help=(
            "Select the exact previewed persisted result revision "
            "after history/target/current-pointer revalidation."
        ),
    )
    _add_format_argument(calculation_select_parser)
    calculation_select_parser.set_defaults(
        handler=_handle_calculation_result_selection,
        show_group_help=None,
    )
    period_preview_parser = workflow_commands.add_parser(
        "academic-period-calculation-preview",
        help=(
            "Preview one bounded Academic Period proficiency calculation."
        ),
        description=(
            "Assemble only explicitly named Grade Item, membership, and "
            "optional #34 result revisions into exact #35 inputs, then "
            "run the pure Academic Period proficiency calculation. No "
            "result is written or selected."
        ),
    )
    period_preview_parser.add_argument("class_id")
    period_preview_parser.add_argument("school_year")
    period_preview_parser.add_argument("period_id")
    period_preview_parser.add_argument(
        "calendar_revision", type=_positive_integer
    )
    period_preview_parser.add_argument("student_id")
    period_preview_parser.add_argument("standard_id")
    period_preview_parser.add_argument("policy_id")
    period_preview_parser.add_argument(
        "policy_revision", type=_positive_integer
    )
    period_preview_parser.add_argument(
        "policy_sha256", type=_sha256_argument
    )
    _add_workspace_argument(period_preview_parser)
    period_preview_parser.add_argument(
        "--candidate",
        nargs=3,
        action="append",
        default=[],
        metavar=(
            "GRADE_ITEM_ID",
            "GRADE_ITEM_REVISION",
            "GRADE_ITEM_SHA256",
        ),
    )
    period_preview_parser.add_argument(
        "--candidate-membership",
        nargs=5,
        action="append",
        default=[],
        metavar=(
            "GRADE_ITEM_ID",
            "MODULE_ID",
            "WORK_ID",
            "MEMBERSHIP_REVISION",
            "MEMBERSHIP_SHA256",
        ),
    )
    period_preview_parser.add_argument(
        "--candidate-result",
        nargs=3,
        action="append",
        default=[],
        metavar=(
            "GRADE_ITEM_ID",
            "RESULT_REVISION",
            "RESULT_SHA256",
        ),
    )
    _add_format_argument(period_preview_parser)
    period_preview_parser.set_defaults(
        handler=_handle_academic_period_calculation_preview,
        show_group_help=None,
    )
    period_write_parser = workflow_commands.add_parser(
        "academic-period-result-write",
        help=(
            "Preview or write one immutable Academic Period "
            "proficiency result."
        ),
        description=(
            "Rebuild one exact bounded Academic Period Calculation "
            "Preview, freeze the next immutable #35 result revision, "
            "and only with --confirm-write persist it after live "
            "revalidation. Writing never changes the current "
            "Academic Period result selection."
        ),
    )
    period_write_parser.add_argument("class_id")
    period_write_parser.add_argument("school_year")
    period_write_parser.add_argument("period_id")
    period_write_parser.add_argument(
        "calendar_revision", type=_positive_integer
    )
    period_write_parser.add_argument("student_id")
    period_write_parser.add_argument("standard_id")
    period_write_parser.add_argument("policy_id")
    period_write_parser.add_argument(
        "policy_revision", type=_positive_integer
    )
    period_write_parser.add_argument(
        "policy_sha256", type=_sha256_argument
    )
    _add_workspace_argument(period_write_parser)
    period_write_parser.add_argument(
        "--candidate",
        nargs=3,
        action="append",
        default=[],
        metavar=(
            "GRADE_ITEM_ID",
            "GRADE_ITEM_REVISION",
            "GRADE_ITEM_SHA256",
        ),
    )
    period_write_parser.add_argument(
        "--candidate-membership",
        nargs=5,
        action="append",
        default=[],
        metavar=(
            "GRADE_ITEM_ID",
            "MODULE_ID",
            "WORK_ID",
            "MEMBERSHIP_REVISION",
            "MEMBERSHIP_SHA256",
        ),
    )
    period_write_parser.add_argument(
        "--candidate-result",
        nargs=3,
        action="append",
        default=[],
        metavar=(
            "GRADE_ITEM_ID",
            "RESULT_REVISION",
            "RESULT_SHA256",
        ),
    )
    period_write_parser.add_argument("--actor-id", required=True)
    period_write_parser.add_argument(
        "--calculated-at",
        required=True,
        type=_datetime_argument,
    )
    period_write_parser.add_argument(
        "--confirm-write",
        action="store_true",
        help=(
            "Write the exact previewed immutable Academic Period "
            "result after live calculation/history revalidation."
        ),
    )
    _add_format_argument(period_write_parser)
    period_write_parser.set_defaults(
        handler=_handle_academic_period_result_persistence,
        show_group_help=None,
    )
    period_select_parser = workflow_commands.add_parser(
        "academic-period-result-select",
        help=(
            "Preview or select one persisted Academic Period "
            "proficiency result."
        ),
        description=(
            "Preview one exact persisted #35 Academic Period "
            "proficiency result revision. Only --confirm-select "
            "mutates the current-result pointer with CAS. No result "
            "is authored or recalculated."
        ),
    )
    period_select_parser.add_argument("class_id")
    period_select_parser.add_argument("school_year")
    period_select_parser.add_argument("period_id")
    period_select_parser.add_argument("student_id")
    period_select_parser.add_argument("standard_id")
    period_select_parser.add_argument(
        "result_revision", type=_positive_integer
    )
    _add_workspace_argument(period_select_parser)
    period_select_parser.add_argument(
        "--confirm-select",
        action="store_true",
        help=(
            "Select the exact previewed persisted Academic Period "
            "result after history/target/current-pointer CAS "
            "revalidation."
        ),
    )
    _add_format_argument(period_select_parser)
    period_select_parser.set_defaults(
        handler=_handle_academic_period_result_selection,
        show_group_help=None,
    )
    planning_signal_parser = workflow_commands.add_parser(
        "create-planning-signal",
        help=(
            "Review planning-signal readiness from selected Academic "
            "Period proficiency."
        ),
        description=(
            "Inspect the explicitly selected #37 policy and resolve "
            "the current read-only #38 derivation candidate from exact "
            "selected/current #35 Academic Period proficiency. This "
            "entry step writes or exports nothing."
        ),
    )
    planning_signal_parser.add_argument("class_id")
    planning_signal_parser.add_argument("policy_id")
    _add_workspace_argument(planning_signal_parser)
    planning_signal_parser.add_argument(
        "--confirm-derivation-write",
        action="store_true",
        help=(
            "Persist the exact reviewed #38 derivation after live "
            "readiness revalidation; stop before #39 preview/review."
        ),
    )
    planning_signal_parser.add_argument(
        "--preview-derivation-id",
        help="Exact persisted #38 derivation to use as the #39 source.",
    )
    planning_signal_parser.add_argument(
        "--preview-derivation-sha256",
        help="Exact SHA-256 for --preview-derivation-id.",
    )
    planning_signal_parser.add_argument(
        "--confirm-preview-write",
        action="store_true",
        help=(
            "Persist the canonical #39 preview for the exact supplied "
            "#38 source; stop before teacher review."
        ),
    )
    _add_format_argument(planning_signal_parser)
    planning_signal_parser.set_defaults(
        handler=_handle_planning_signal_readiness,
        show_group_help=None,
    )
    workflow.set_defaults(show_group_help=workflow)

    return parser


def _add_workspace_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        required=True,
        type=Path,
        help="Paper Data Suite workspace root.",
    )


def _add_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
    )


def _add_evidence_authorization_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--purpose-id",
        required=True,
        help="Exact deployment authorization purpose used by the cached projection.",
    )
    parser.add_argument(
        "--scope-student-id",
        action="append",
        default=[],
        help=(
            "Exact student scope used by the cached projection; repeat as needed. "
            "Omit only for a projection originally authorized with an empty scope."
        ),
    )


def _list_request(args: argparse.Namespace) -> PublicationDiscoveryRequest:
    query = PublicationCatalogQuery(
        school_year=args.school_year,
        class_id=args.class_id,
        module_id=args.module_id,
        work_id=args.work_id,
        publication_kind=args.publication_kind,
        required_capabilities=tuple(args.capability),
        producer_contract_version=args.producer_contract_version,
        manifest_contract_version=args.manifest_contract_version,
        source_contract_version=args.source_contract_version,
        referenced_registration_lifecycle=args.referenced_registration_lifecycle,
        current_registration_lifecycle=args.current_registration_lifecycle,
        record_set_id=args.record_set_id,
        minimum_record_set_revision=args.minimum_record_set_revision,
        published_at_or_after=args.published_at_or_after,
        published_before=args.published_before,
        state=args.state,
        limit=args.limit,
        offset=args.offset,
    )
    return PublicationDiscoveryRequest(query)


def _dependencies(
    supplied: DiagnosticsDependencies | None,
) -> DiagnosticsDependencies:
    return supplied if supplied is not None else default_diagnostics_dependencies()


def _handle_publication_list(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    result = list_publication_diagnostics(
        str(args.workspace),
        _list_request(args),
        _dependencies(dependencies),
    )
    _render_publication_list(result, args.format)
    return 0


def _handle_publication_verify(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    result = verify_publication_diagnostic(
        str(args.workspace),
        args.publication_id,
        _dependencies(dependencies),
    )
    _render_publication_verification(result, args.format)
    return 0


def _handle_evidence_inspect(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    filters = EvidenceFilters(
        item_ids=tuple(args.item_id),
        student_ids=tuple(args.student_id),
        target_kinds=tuple(args.target_kind),
        standard_ids=tuple(args.standard_id),
        result_kinds=tuple(args.result_kind),
        eligibility_statuses=tuple(args.eligibility),
    )
    result = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=tuple(args.scope_student_id),
        filters=filters,
        dependencies=_dependencies(dependencies),
    )
    _render_evidence_inspection(result, args.format)
    return 0



def _handle_evidence_explain(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    result = explain_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=tuple(args.scope_student_id),
        dependencies=_dependencies(dependencies),
    )
    _render_evidence_explanation(result, args.format)
    return 0


def _handle_teacher_workflow_list(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    _ = dependencies
    catalog = teacher_workflow_catalog()
    _render_teacher_workflow_catalog(catalog, args.format)
    return 0


def _handle_new_evidence_review(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    inspection = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=tuple(args.scope_student_id),
        filters=EvidenceFilters(),
        dependencies=_dependencies(dependencies),
    )
    authorized = inspection.authorized
    class_id = authorized.stored.snapshot.source.publication.work.class_id
    review = project_new_evidence_review(
        str(args.workspace),
        class_id,
        args.grade_item_id,
        authorized,
    )
    _render_new_evidence_review(review, args.format)
    return 0


def _calculation_binding_profile_specs(
    args: argparse.Namespace,
) -> dict[tuple[str, str, str], tuple[str, str, int, str]]:
    binding_keys = tuple(tuple(values) for values in args.binding)
    if len(set(binding_keys)) != len(binding_keys):
        raise CalculationPreviewAssemblyScopeError(
            "Calculation Preview --binding values must not duplicate "
            "the same publication/cache/item triple."
        )
    profiles: dict[tuple[str, str, str], tuple[str, str, int, str]] = {}
    binding_key_set = set(binding_keys)
    for raw in args.binding_profile:
        (
            publication_id,
            cache_key,
            item_id,
            scale_id,
            profile_id,
            revision,
            sha256,
        ) = raw
        key = (publication_id, cache_key, item_id)
        if key not in binding_key_set:
            raise CalculationPreviewAssemblyScopeError(
                "Every --binding-profile must identify an explicit --binding."
            )
        if key in profiles:
            raise CalculationPreviewAssemblyScopeError(
                "A Calculation Preview binding may have at most one mapping profile."
            )
        try:
            profile_revision = _positive_integer(revision)
            profile_sha256 = _sha256_argument(sha256)
        except argparse.ArgumentTypeError as error:
            raise CalculationPreviewAssemblyScopeError(str(error)) from error
        profiles[key] = (
            scale_id,
            profile_id,
            profile_revision,
            profile_sha256,
        )
    return profiles


def _build_calculation_result_review_from_args(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> BoundedCalculationPreview:
    profile_specs = _calculation_binding_profile_specs(args)
    target_scale = ProficiencyScaleReference(
        class_id=args.class_id,
        scale_id=args.scale_id,
        scale_revision=args.scale_revision,
        scale_sha256=args.scale_sha256,
    )
    policy_reference = StandardProficiencyCalculationPolicyReference(
        class_id=args.class_id,
        policy_id=args.policy_id,
        policy_revision=args.policy_revision,
        policy_sha256=args.policy_sha256,
    )
    bindings: list[StandardAggregationCandidateBinding] = []
    for publication_id, cache_key, item_id in args.binding:
        inspection = inspect_evidence_diagnostic(
            str(args.workspace),
            publication_id,
            cache_key,
            authorization_purpose_id=args.purpose_id,
            requested_student_ids=tuple(args.scope_student_id),
            filters=EvidenceFilters(item_ids=(item_id,)),
            dependencies=_dependencies(dependencies),
        )
        if len(inspection.items) != 1 or inspection.items[0].item_id != item_id:
            raise CalculationPreviewAssemblyDependencyError(
                "Explicit Calculation Preview binding must resolve to exactly "
                "one authorized evidence item."
            )
        authorized = inspection.authorized
        stored = authorized.stored
        publication = stored.snapshot.source.publication
        if publication.work.class_id != args.class_id:
            raise CalculationPreviewAssemblyScopeError(
                "Every authorized binding must belong to the requested class."
            )
        source = EvidenceSourceReference(
            work=publication.work,
            publication_id=publication.publication_id,
            cache_key=stored.cache_key,
            snapshot_digest=stored.snapshot_digest,
            item_id=item_id,
        )
        profile_spec = profile_specs.get(
            (publication_id, cache_key, item_id)
        )
        mapping_profile = None
        if profile_spec is not None:
            (
                scale_id,
                profile_id,
                profile_revision,
                profile_sha256,
            ) = profile_spec
            mapping_profile = NativeValueMappingProfileReference(
                class_id=args.class_id,
                scale_id=scale_id,
                profile_id=profile_id,
                profile_revision=profile_revision,
                profile_sha256=profile_sha256,
            )
        bindings.append(
            StandardAggregationCandidateBinding(
                source=source,
                authorized_snapshot=authorized,
                mapping_profile=mapping_profile,
                attempt=None,
            )
        )
    return build_bounded_calculation_preview(
        str(args.workspace),
        args.grade_item_id,
        args.student_id,
        args.standard_id,
        target_scale,
        tuple(bindings),
        policy_reference,
    )


def _academic_period_candidate_specs(
    args: argparse.Namespace,
) -> tuple[AcademicPeriodCalculationCandidateSpec, ...]:
    declared: dict[str, tuple[int, str]] = {}
    for grade_item_id, raw_revision, raw_sha256 in args.candidate:
        if grade_item_id in declared:
            raise AcademicPeriodCalculationAssemblyScopeError(
                "Academic Period --candidate must not duplicate a Grade Item."
            )
        try:
            revision = _positive_integer(raw_revision)
            sha256 = _sha256_argument(raw_sha256)
        except argparse.ArgumentTypeError as error:
            raise AcademicPeriodCalculationAssemblyScopeError(
                str(error)
            ) from error
        declared[grade_item_id] = (revision, sha256)

    memberships: dict[str, list[AcademicPeriodMembershipSpec]] = {
        grade_item_id: [] for grade_item_id in declared
    }
    membership_keys: set[tuple[str, str, str]] = set()
    for raw in args.candidate_membership:
        (
            grade_item_id,
            module_id,
            work_id,
            raw_revision,
            raw_sha256,
        ) = raw
        if grade_item_id not in declared:
            raise AcademicPeriodCalculationAssemblyScopeError(
                "Every --candidate-membership must identify a declared "
                "--candidate."
            )
        key = (grade_item_id, module_id, work_id)
        if key in membership_keys:
            raise AcademicPeriodCalculationAssemblyScopeError(
                "A candidate membership work relationship must not duplicate."
            )
        membership_keys.add(key)
        try:
            revision = _positive_integer(raw_revision)
            sha256 = _sha256_argument(raw_sha256)
            work = ModuleWorkRef(
                module_id=module_id,
                class_id=args.class_id,
                work_id=work_id,
            )
        except (argparse.ArgumentTypeError, RoutingModelError) as error:
            raise AcademicPeriodCalculationAssemblyScopeError(
                str(error)
            ) from error
        memberships[grade_item_id].append(
            AcademicPeriodMembershipSpec(
                work=work,
                membership_revision=revision,
                membership_sha256=sha256,
            )
        )

    results: dict[str, tuple[int, str]] = {}
    for grade_item_id, raw_revision, raw_sha256 in args.candidate_result:
        if grade_item_id not in declared:
            raise AcademicPeriodCalculationAssemblyScopeError(
                "Every --candidate-result must identify a declared --candidate."
            )
        if grade_item_id in results:
            raise AcademicPeriodCalculationAssemblyScopeError(
                "A Grade Item candidate may have at most one exact #34 result."
            )
        try:
            revision = _positive_integer(raw_revision)
            sha256 = _sha256_argument(raw_sha256)
        except argparse.ArgumentTypeError as error:
            raise AcademicPeriodCalculationAssemblyScopeError(
                str(error)
            ) from error
        results[grade_item_id] = (revision, sha256)

    specs: list[AcademicPeriodCalculationCandidateSpec] = []
    for grade_item_id in sorted(declared):
        grade_item_revision, grade_item_sha256 = declared[grade_item_id]
        result = results.get(grade_item_id)
        specs.append(
            AcademicPeriodCalculationCandidateSpec(
                grade_item_id=grade_item_id,
                grade_item_revision=grade_item_revision,
                grade_item_revision_sha256=grade_item_sha256,
                memberships=tuple(
                    sorted(
                        memberships[grade_item_id],
                        key=lambda value: (
                            value.work.module_id,
                            value.work.work_id,
                        ),
                    )
                ),
                result_revision=None if result is None else result[0],
                result_sha256=None if result is None else result[1],
            )
        )
    return tuple(specs)


def _handle_academic_period_calculation_preview(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    try:
        target = AcademicPeriodProficiencyTarget(
            period=AcademicPeriodRef(
                school_year=args.school_year,
                period_id=args.period_id,
            ),
            calendar_revision=args.calendar_revision,
        )
        policy_reference = AcademicPeriodProficiencyAggregationPolicyReference(
            class_id=args.class_id,
            policy_id=args.policy_id,
            policy_revision=args.policy_revision,
            policy_sha256=args.policy_sha256,
        )
    except (AcademicPeriodValidationError, ValueError) as error:
        raise AcademicPeriodCalculationAssemblyScopeError(str(error)) from error

    preview = build_bounded_academic_period_calculation_preview(
        str(args.workspace),
        target,
        args.student_id,
        args.standard_id,
        _academic_period_candidate_specs(args),
        policy_reference,
    )
    _render_academic_period_calculation_preview(preview, args.format)
    return 0


def _handle_academic_period_result_persistence(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    try:
        target = AcademicPeriodProficiencyTarget(
            period=AcademicPeriodRef(
                school_year=args.school_year,
                period_id=args.period_id,
            ),
            calendar_revision=args.calendar_revision,
        )
        policy_reference = AcademicPeriodProficiencyAggregationPolicyReference(
            class_id=args.class_id,
            policy_id=args.policy_id,
            policy_revision=args.policy_revision,
            policy_sha256=args.policy_sha256,
        )
    except (AcademicPeriodValidationError, ValueError) as error:
        raise AcademicPeriodCalculationAssemblyScopeError(str(error)) from error

    reviewed = build_bounded_academic_period_calculation_preview(
        str(args.workspace),
        target,
        args.student_id,
        args.standard_id,
        _academic_period_candidate_specs(args),
        policy_reference,
    )
    preview = preview_academic_period_result_persistence(
        str(args.workspace),
        reviewed,
        actor_id=args.actor_id,
        calculated_at=args.calculated_at,
    )
    if not args.confirm_write:
        _render_academic_period_result_persistence_preview(
            preview,
            args.format,
            confirmation_supplied=False,
        )
        return 0
    if args.format == "text":
        _render_academic_period_result_persistence_preview(
            preview,
            args.format,
            confirmation_supplied=True,
        )
        sys.stdout.flush()
    result = commit_academic_period_result_persistence_preview(
        str(args.workspace),
        preview,
    )
    _render_academic_period_result_persistence_result(
        preview,
        result,
        args.format,
    )
    return 0


def _handle_planning_signal_readiness(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies

    has_preview_derivation_id = args.preview_derivation_id is not None
    has_preview_derivation_sha256 = (
        args.preview_derivation_sha256 is not None
    )
    if has_preview_derivation_id != has_preview_derivation_sha256:
        raise PlanningSignalPreviewWriteScopeError(
            "#39 preview source requires both --preview-derivation-id and "
            "--preview-derivation-sha256."
        )
    preview_source_supplied = (
        has_preview_derivation_id and has_preview_derivation_sha256
    )
    if args.confirm_preview_write and not preview_source_supplied:
        raise PlanningSignalPreviewWriteScopeError(
            "--confirm-preview-write requires an exact persisted #38 source."
        )
    if preview_source_supplied and args.confirm_derivation_write:
        raise PlanningSignalPreviewWriteScopeError(
            "#38 derivation write and #39 preview write stages cannot be combined."
        )

    if preview_source_supplied:
        preview_write = preview_planning_signal_preview_write(
            str(args.workspace),
            args.class_id,
            args.policy_id,
            args.preview_derivation_id,
            args.preview_derivation_sha256,
        )
        if not args.confirm_preview_write:
            _render_planning_signal_preview_write_preview(
                preview_write,
                args.format,
            )
            return 0
        if args.format == "text":
            _render_planning_signal_preview_write_confirmation(preview_write)
            sys.stdout.flush()
        preview_result = commit_planning_signal_preview_write(
            str(args.workspace),
            preview_write,
        )
        _render_planning_signal_preview_write_result(
            preview_write,
            preview_result,
            args.format,
        )
        return 0

    projection = project_planning_signal_readiness(
        str(args.workspace),
        args.class_id,
        args.policy_id,
    )
    if not projection.ready_for_derivation_persistence:
        if args.confirm_derivation_write:
            preview_planning_signal_derivation_persistence(projection)
        _render_planning_signal_readiness(projection, args.format)
        return 0

    preview = preview_planning_signal_derivation_persistence(projection)
    if not args.confirm_derivation_write:
        _render_planning_signal_derivation_persistence_preview(
            projection,
            preview,
            args.format,
        )
        return 0

    if args.format == "text":
        _render_planning_signal_derivation_write_confirmation(preview)
        sys.stdout.flush()
    result = commit_planning_signal_derivation_persistence_preview(
        str(args.workspace),
        preview,
    )
    _render_planning_signal_derivation_persistence_result(
        projection,
        result,
        args.format,
    )
    return 0


def _handle_academic_period_result_selection(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    preview = preview_academic_period_result_selection(
        str(args.workspace),
        args.class_id,
        args.school_year,
        args.period_id,
        args.student_id,
        args.standard_id,
        args.result_revision,
    )
    if not args.confirm_select:
        _render_academic_period_result_selection_preview(
            preview,
            args.format,
            confirmation_supplied=False,
        )
        return 0
    if args.format == "text":
        _render_academic_period_result_selection_preview(
            preview,
            args.format,
            confirmation_supplied=True,
        )
        sys.stdout.flush()
    result = commit_academic_period_result_selection_preview(
        str(args.workspace),
        preview,
    )
    _render_academic_period_result_selection_result(
        preview,
        result,
        args.format,
    )
    return 0


def _handle_calculation_result_selection(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    preview = preview_calculation_result_selection(
        str(args.workspace),
        args.class_id,
        args.grade_item_id,
        args.student_id,
        args.standard_id,
        args.result_revision,
    )
    if not args.confirm_select:
        _render_calculation_result_selection_preview(
            preview,
            args.format,
            confirmation_supplied=False,
        )
        return 0
    if args.format == "text":
        _render_calculation_result_selection_preview(
            preview,
            args.format,
            confirmation_supplied=True,
        )
        sys.stdout.flush()
    result = commit_calculation_result_selection_preview(
        str(args.workspace),
        preview,
    )
    _render_calculation_result_selection_result(
        preview,
        result,
        args.format,
    )
    return 0


def _handle_calculation_result_persistence(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    reviewed = _build_calculation_result_review_from_args(
        args,
        dependencies,
    )
    preview = preview_calculation_result_persistence(
        str(args.workspace),
        reviewed,
        actor_id=args.actor_id,
        calculated_at=args.calculated_at,
    )
    if not args.confirm_write:
        _render_calculation_result_persistence_preview(
            preview,
            args.format,
            confirmation_supplied=False,
        )
        return 0
    if args.format == "text":
        _render_calculation_result_persistence_preview(
            preview,
            args.format,
            confirmation_supplied=True,
        )
        sys.stdout.flush()
    result = commit_calculation_result_persistence_preview(
        str(args.workspace),
        preview,
    )
    _render_calculation_result_persistence_result(
        preview,
        result,
        args.format,
    )
    return 0


def _handle_calculation_preview(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    profile_specs = _calculation_binding_profile_specs(args)
    target_scale = ProficiencyScaleReference(
        class_id=args.class_id,
        scale_id=args.scale_id,
        scale_revision=args.scale_revision,
        scale_sha256=args.scale_sha256,
    )
    policy_reference = StandardProficiencyCalculationPolicyReference(
        class_id=args.class_id,
        policy_id=args.policy_id,
        policy_revision=args.policy_revision,
        policy_sha256=args.policy_sha256,
    )

    bindings: list[StandardAggregationCandidateBinding] = []
    for publication_id, cache_key, item_id in args.binding:
        inspection = inspect_evidence_diagnostic(
            str(args.workspace),
            publication_id,
            cache_key,
            authorization_purpose_id=args.purpose_id,
            requested_student_ids=tuple(args.scope_student_id),
            filters=EvidenceFilters(item_ids=(item_id,)),
            dependencies=_dependencies(dependencies),
        )
        if len(inspection.items) != 1 or inspection.items[0].item_id != item_id:
            raise CalculationPreviewAssemblyDependencyError(
                "Explicit Calculation Preview binding must resolve to exactly "
                "one authorized evidence item."
            )
        authorized = inspection.authorized
        stored = authorized.stored
        publication = stored.snapshot.source.publication
        if publication.work.class_id != args.class_id:
            raise CalculationPreviewAssemblyScopeError(
                "Every authorized binding must belong to the requested class."
            )
        source = EvidenceSourceReference(
            work=publication.work,
            publication_id=publication.publication_id,
            cache_key=stored.cache_key,
            snapshot_digest=stored.snapshot_digest,
            item_id=item_id,
        )
        profile_spec = profile_specs.get(
            (publication_id, cache_key, item_id)
        )
        mapping_profile = None
        if profile_spec is not None:
            (
                scale_id,
                profile_id,
                profile_revision,
                profile_sha256,
            ) = profile_spec
            mapping_profile = NativeValueMappingProfileReference(
                class_id=args.class_id,
                scale_id=scale_id,
                profile_id=profile_id,
                profile_revision=profile_revision,
                profile_sha256=profile_sha256,
            )
        bindings.append(
            StandardAggregationCandidateBinding(
                source=source,
                authorized_snapshot=authorized,
                mapping_profile=mapping_profile,
                attempt=None,
            )
        )

    preview = build_bounded_calculation_preview(
        str(args.workspace),
        args.grade_item_id,
        args.student_id,
        args.standard_id,
        target_scale,
        tuple(bindings),
        policy_reference,
    )
    _render_calculation_preview(preview, args.format)
    return 0


def _handle_standards_association_selection(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    profile_values = (
        args.mapping_profile_scale_id,
        args.mapping_profile_id,
        args.mapping_profile_revision,
        args.mapping_profile_sha256,
    )
    if any(value is not None for value in profile_values) and not all(
        value is not None for value in profile_values
    ):
        raise StandardsReviewWorkflowScopeError(
            "mapping profile selection requires scale ID, profile ID, "
            "revision, and SHA-256 together."
        )
    inspection = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=tuple(args.scope_student_id),
        filters=EvidenceFilters(),
        dependencies=_dependencies(dependencies),
    )
    authorized = inspection.authorized
    class_id = authorized.stored.snapshot.source.publication.work.class_id
    target_scale = ProficiencyScaleReference(
        class_id=class_id,
        scale_id=args.scale_id,
        scale_revision=args.scale_revision,
        scale_sha256=args.scale_sha256,
    )
    mapping_profile = None
    if all(value is not None for value in profile_values):
        mapping_profile = NativeValueMappingProfileReference(
            class_id=class_id,
            scale_id=cast(str, args.mapping_profile_scale_id),
            profile_id=cast(str, args.mapping_profile_id),
            profile_revision=cast(int, args.mapping_profile_revision),
            profile_sha256=cast(str, args.mapping_profile_sha256),
        )
    review = build_standards_review_projection(
        str(args.workspace),
        args.grade_item_id,
        args.student_id,
        args.standard_id,
        args.item_id,
        target_scale,
        authorized_snapshot=authorized,
        mapping_profile=mapping_profile,
        attempt=None,
    )
    preview = preview_standards_association_selection(
        str(args.workspace),
        review,
        authorized_snapshot=authorized,
        association_revision=args.association_revision,
        attempt=None,
    )
    if not args.confirm_select:
        _render_standards_association_selection_preview(
            preview,
            args.format,
            confirmation_supplied=False,
        )
        return 0
    if args.format == "text":
        _render_standards_association_selection_preview(
            preview,
            args.format,
            confirmation_supplied=True,
        )
        sys.stdout.flush()
    result = commit_standards_association_selection_preview(
        str(args.workspace),
        preview,
        authorized_snapshot=authorized,
    )
    _render_standards_association_selection_result(
        preview,
        result,
        args.format,
    )
    return 0


def _handle_standards_association_authoring(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    profile_values = (
        args.mapping_profile_scale_id,
        args.mapping_profile_id,
        args.mapping_profile_revision,
        args.mapping_profile_sha256,
    )
    if any(value is not None for value in profile_values) and not all(
        value is not None for value in profile_values
    ):
        raise StandardsReviewWorkflowScopeError(
            "mapping profile selection requires scale ID, profile ID, "
            "revision, and SHA-256 together."
        )
    inspection = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=tuple(args.scope_student_id),
        filters=EvidenceFilters(),
        dependencies=_dependencies(dependencies),
    )
    authorized = inspection.authorized
    class_id = authorized.stored.snapshot.source.publication.work.class_id
    target_scale = ProficiencyScaleReference(
        class_id=class_id,
        scale_id=args.scale_id,
        scale_revision=args.scale_revision,
        scale_sha256=args.scale_sha256,
    )
    mapping_profile = None
    if all(value is not None for value in profile_values):
        mapping_profile = NativeValueMappingProfileReference(
            class_id=class_id,
            scale_id=cast(str, args.mapping_profile_scale_id),
            profile_id=cast(str, args.mapping_profile_id),
            profile_revision=cast(int, args.mapping_profile_revision),
            profile_sha256=cast(str, args.mapping_profile_sha256),
        )
    review = build_standards_review_projection(
        str(args.workspace),
        args.grade_item_id,
        args.student_id,
        args.standard_id,
        args.item_id,
        target_scale,
        authorized_snapshot=authorized,
        mapping_profile=mapping_profile,
        attempt=None,
    )
    preview = preview_standards_association_authoring(
        str(args.workspace),
        review,
        authorized_snapshot=authorized,
        operation=args.operation,
        disposition=args.disposition,
        basis=args.basis,
        actor_id=args.actor_id,
        rationale=args.rationale,
        decided_at=args.decided_at,
    )
    if not args.confirm_write:
        _render_standards_association_authoring_preview(
            preview,
            args.format,
            confirmation_supplied=False,
        )
        return 0
    if args.format == "text":
        _render_standards_association_authoring_preview(
            preview,
            args.format,
            confirmation_supplied=True,
        )
        sys.stdout.flush()
    result = commit_standards_association_authoring_preview(
        str(args.workspace),
        preview,
        authorized_snapshot=authorized,
    )
    _render_standards_association_authoring_result(
        preview,
        result,
        args.format,
    )
    return 0


def _handle_standards_review(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    profile_values = (
        args.mapping_profile_scale_id,
        args.mapping_profile_id,
        args.mapping_profile_revision,
        args.mapping_profile_sha256,
    )
    if any(value is not None for value in profile_values) and not all(
        value is not None for value in profile_values
    ):
        raise StandardsReviewWorkflowScopeError(
            "mapping profile selection requires scale ID, profile ID, "
            "revision, and SHA-256 together."
        )
    inspection = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=tuple(args.scope_student_id),
        filters=EvidenceFilters(),
        dependencies=_dependencies(dependencies),
    )
    authorized = inspection.authorized
    class_id = authorized.stored.snapshot.source.publication.work.class_id
    target_scale = ProficiencyScaleReference(
        class_id=class_id,
        scale_id=args.scale_id,
        scale_revision=args.scale_revision,
        scale_sha256=args.scale_sha256,
    )
    mapping_profile = None
    if all(value is not None for value in profile_values):
        mapping_profile = NativeValueMappingProfileReference(
            class_id=class_id,
            scale_id=cast(str, args.mapping_profile_scale_id),
            profile_id=cast(str, args.mapping_profile_id),
            profile_revision=cast(int, args.mapping_profile_revision),
            profile_sha256=cast(str, args.mapping_profile_sha256),
        )
    projection = build_standards_review_projection(
        str(args.workspace),
        args.grade_item_id,
        args.student_id,
        args.standard_id,
        args.item_id,
        target_scale,
        authorized_snapshot=authorized,
        mapping_profile=mapping_profile,
        attempt=None,
    )
    _render_standards_review(projection, args.format)
    return 0


def _handle_exclusions_eligibility_selection(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    inspection = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=tuple(args.scope_student_id),
        filters=EvidenceFilters(),
        dependencies=_dependencies(dependencies),
    )
    authorized = inspection.authorized
    projection = build_exclusions_projection(
        str(args.workspace),
        args.grade_item_id,
        authorized_snapshot=authorized,
    )
    preview = preview_exclusion_eligibility_selection(
        str(args.workspace),
        projection,
        authorized_snapshot=authorized,
        item_id=args.item_id,
        eligibility_revision=args.eligibility_revision,
    )
    if not args.confirm_select:
        _render_exclusions_eligibility_selection_preview(
            preview,
            args.format,
            confirmation_supplied=False,
        )
        return 0
    if args.format == "text":
        _render_exclusions_eligibility_selection_preview(
            preview,
            args.format,
            confirmation_supplied=True,
        )
        sys.stdout.flush()
    result = commit_exclusion_eligibility_selection_preview(
        str(args.workspace),
        preview,
        authorized_snapshot=authorized,
    )
    _render_exclusions_eligibility_selection_result(
        preview,
        result,
        args.format,
    )
    return 0


def _handle_exclusions_eligibility_authoring(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    inspection = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=tuple(args.scope_student_id),
        filters=EvidenceFilters(),
        dependencies=_dependencies(dependencies),
    )
    authorized = inspection.authorized
    projection = build_exclusions_projection(
        str(args.workspace),
        args.grade_item_id,
        authorized_snapshot=authorized,
    )
    preview = preview_exclusion_eligibility_authoring(
        str(args.workspace),
        projection,
        authorized_snapshot=authorized,
        item_id=args.item_id,
        disposition=cast(ExclusionAcademicDisposition, args.disposition),
        actor_id=args.actor_id,
        policy_id=args.policy_id,
        policy_version=args.policy_version,
        reason_codes=tuple(args.reason_code),
        rationale=args.rationale,
        decided_at=args.decided_at,
    )
    if not args.confirm_write:
        _render_exclusions_eligibility_authoring_preview(
            preview,
            args.format,
            confirmation_supplied=False,
        )
        return 0
    if args.format == "text":
        _render_exclusions_eligibility_authoring_preview(
            preview,
            args.format,
            confirmation_supplied=True,
        )
        sys.stdout.flush()
    result = commit_exclusion_eligibility_authoring_preview(
        str(args.workspace),
        preview,
        authorized_snapshot=authorized,
    )
    _render_exclusions_eligibility_authoring_result(
        preview,
        result,
        args.format,
    )
    return 0


def _handle_exclusions_workflow(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    inspection = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=tuple(args.scope_student_id),
        filters=EvidenceFilters(),
        dependencies=_dependencies(dependencies),
    )
    projection = build_exclusions_projection(
        str(args.workspace),
        args.grade_item_id,
        authorized_snapshot=inspection.authorized,
    )
    _render_exclusions_projection(projection, args.format)
    return 0


def _handle_attempt_decision_selection(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    inspection = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=(args.student_id,),
        filters=EvidenceFilters(),
        dependencies=_dependencies(dependencies),
    )
    authorized = inspection.authorized
    work = authorized.stored.snapshot.source.publication.work
    preview = preview_attempt_decision_selection(
        str(args.workspace),
        work.class_id,
        args.grade_item_id,
        work,
        args.student_id,
        args.decision_revision,
        authorized_snapshot=authorized,
    )
    if not args.confirm_select:
        _render_attempt_decision_selection_preview(
            preview, args.format, confirmation_supplied=False
        )
        return 0
    if args.format == "text":
        _render_attempt_decision_selection_preview(
            preview, args.format, confirmation_supplied=True
        )
        sys.stdout.flush()
    result = commit_attempt_decision_selection_preview(
        str(args.workspace),
        preview,
        authorized_snapshot=authorized,
    )
    _render_attempt_decision_selection_result(preview, result, args.format)
    return 0


def _resolve_attempt_decision_cli_selection(
    derivation: object,
    sequences: list[int],
    identifiers: list[str],
) -> tuple[AttemptObservationReference, ...]:
    status = getattr(derivation, "status", None)
    if status != "applicable":
        raise AttemptDecisionAuthoringScopeError(
            "Explicit attempt selection requires applicable current "
            f"candidates; derivation status is {status!r}."
        )
    candidates = tuple(getattr(derivation, "candidates", ()))
    selected: list[AttemptObservationReference] = []
    for field_name, values in (
        ("sequence", sequences),
        ("identifier", identifiers),
    ):
        for value in values:
            matches = tuple(
                candidate.attempt
                for candidate in candidates
                if getattr(candidate.attempt.native, field_name) == value
            )
            if len(matches) != 1:
                raise AttemptDecisionAuthoringScopeError(
                    f"Native attempt {field_name} {value!r} must match "
                    "exactly one current candidate."
                )
            if matches[0] in selected:
                raise AttemptDecisionAuthoringScopeError(
                    "Multiple selectors resolved to the same candidate."
                )
            selected.append(matches[0])
    return tuple(
        candidate.attempt
        for candidate in candidates
        if candidate.attempt in selected
    )


def _handle_attempt_decision_authoring(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    inspection = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=(args.student_id,),
        filters=EvidenceFilters(),
        dependencies=_dependencies(dependencies),
    )
    authorized = inspection.authorized
    work = authorized.stored.snapshot.source.publication.work
    derivation = derive_attempt_candidates(
        str(args.workspace),
        work.class_id,
        args.grade_item_id,
        args.student_id,
        authorized,
    )
    selected = _resolve_attempt_decision_cli_selection(
        derivation,
        args.select_sequence,
        args.select_identifier,
    )
    preview = preview_attempt_decision_authoring(
        str(args.workspace),
        work.class_id,
        args.grade_item_id,
        work,
        args.student_id,
        args.policy_id,
        authorized_snapshot=authorized,
        selected_attempts=selected,
        actor_id=args.actor_id,
        decided_at=args.decided_at,
        rationale=args.rationale,
    )
    if not args.confirm_write:
        _render_attempt_decision_authoring_preview(
            preview, args.format, confirmation_supplied=False
        )
        return 0
    if args.format == "text":
        _render_attempt_decision_authoring_preview(
            preview, args.format, confirmation_supplied=True
        )
        sys.stdout.flush()
    result = commit_attempt_decision_authoring_preview(
        str(args.workspace),
        preview,
        authorized_snapshot=authorized,
    )
    _render_attempt_decision_authoring_result(preview, result, args.format)
    return 0


def _handle_attempt_policy_selection(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    try:
        work = ModuleWorkRef(
            module_id=args.module_id,
            class_id=args.class_id,
            work_id=args.work_id,
        )
    except RoutingModelError as error:
        raise AttemptPolicySelectionScopeError(str(error)) from error
    preview = preview_attempt_policy_selection(
        str(args.workspace),
        args.class_id,
        args.grade_item_id,
        work,
        args.policy_id,
        args.policy_revision,
    )
    if not args.confirm_select:
        _render_attempt_policy_selection_preview(
            preview, args.format, confirmation_supplied=False
        )
        return 0
    if args.format == "text":
        _render_attempt_policy_selection_preview(
            preview, args.format, confirmation_supplied=True
        )
        sys.stdout.flush()
    result = commit_attempt_policy_selection_preview(
        str(args.workspace), preview
    )
    _render_attempt_policy_selection_result(preview, result, args.format)
    return 0


def _handle_attempt_policy_authoring(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    try:
        work = ModuleWorkRef(
            module_id=args.module_id,
            class_id=args.class_id,
            work_id=args.work_id,
        )
    except RoutingModelError as error:
        raise AttemptPolicyAuthoringScopeError(str(error)) from error
    preview = preview_attempt_policy_authoring(
        str(args.workspace),
        args.class_id,
        args.grade_item_id,
        work,
        args.policy_id,
        operation=args.operation,
        minimum_selected=args.minimum_selected,
        maximum_selected=args.maximum_selected,
        actor_id=args.actor_id,
        revised_at=args.revised_at,
        rationale=args.rationale,
    )
    if not args.confirm_write:
        _render_attempt_policy_authoring_preview(
            preview, args.format, confirmation_supplied=False
        )
        return 0
    if args.format == "text":
        _render_attempt_policy_authoring_preview(
            preview, args.format, confirmation_supplied=True
        )
        sys.stdout.flush()
    result = commit_attempt_policy_authoring_preview(
        str(args.workspace), preview
    )
    _render_attempt_policy_authoring_result(preview, result, args.format)
    return 0


def _handle_attempt_decisions_review(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    inspection = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=(args.student_id,),
        filters=EvidenceFilters(),
        dependencies=_dependencies(dependencies),
    )
    authorized = inspection.authorized
    work = authorized.stored.snapshot.source.publication.work
    review = project_attempt_decisions(
        str(args.workspace),
        work.class_id,
        args.grade_item_id,
        work,
        args.student_id,
        authorized_snapshot=authorized,
    )
    _render_attempt_decisions_review(review, args.format)
    return 0


def _handle_grade_item_membership_selection(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    try:
        work = ModuleWorkRef(
            module_id=args.module_id,
            class_id=args.class_id,
            work_id=args.work_id,
        )
    except RoutingModelError as error:
        raise GradeItemMembershipSelectionScopeError(str(error)) from error
    preview = preview_grade_item_membership_selection(
        str(args.workspace),
        args.class_id,
        args.grade_item_id,
        work,
        args.membership_revision,
    )
    if not args.confirm_select:
        _render_grade_item_membership_selection_preview(
            preview, args.format, confirmation_supplied=False
        )
        return 0
    if args.format == "text":
        _render_grade_item_membership_selection_preview(
            preview, args.format, confirmation_supplied=True
        )
        sys.stdout.flush()
    result = commit_grade_item_membership_selection_preview(
        str(args.workspace), preview
    )
    _render_grade_item_membership_selection_result(
        preview, result, args.format
    )
    return 0


def _handle_grade_item_membership_authoring(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    try:
        work = ModuleWorkRef(
            module_id=args.module_id,
            class_id=args.class_id,
            work_id=args.work_id,
        )
        period_parts = (
            args.school_year,
            args.period_id,
            args.calendar_revision,
        )
        academic_period: GradeItemAcademicPeriodAssignment | None = None
        if args.decision == "included":
            if any(value is None for value in period_parts):
                raise GradeItemMembershipAuthoringScopeError(
                    "included membership requires --school-year, "
                    "--period-id, and --calendar-revision."
                )
            academic_period = GradeItemAcademicPeriodAssignment(
                period=AcademicPeriodRef(
                    school_year=args.school_year,
                    period_id=args.period_id,
                ),
                calendar_revision=args.calendar_revision,
            )
        elif any(value is not None for value in period_parts):
            raise GradeItemMembershipAuthoringScopeError(
                "excluded membership must not include Academic Period "
                "coordinates."
            )
        preview = preview_grade_item_membership_authoring(
            str(args.workspace),
            args.class_id,
            args.grade_item_id,
            work,
            operation=args.operation,
            grade_item_revision=args.grade_item_revision,
            registration_revision=args.registration_revision,
            decision=args.decision,
            actor_id=args.actor_id,
            decided_at=args.decided_at,
            academic_period=academic_period,
            rationale=args.rationale,
        )
    except (
        AcademicPeriodValidationError,
        GradeItemMembershipValidationError,
        RoutingModelError,
    ) as error:
        raise GradeItemMembershipAuthoringScopeError(str(error)) from error
    if not args.confirm_write:
        _render_grade_item_membership_authoring_preview(
            preview, args.format, confirmation_supplied=False
        )
        return 0
    if args.format == "text":
        _render_grade_item_membership_authoring_preview(
            preview, args.format, confirmation_supplied=True
        )
        sys.stdout.flush()
    result = commit_grade_item_membership_authoring_preview(
        str(args.workspace), preview
    )
    _render_grade_item_membership_authoring_result(
        preview, result, args.format
    )
    return 0


def _handle_grade_item_selection(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    preview = preview_grade_item_selection(
        str(args.workspace),
        args.class_id,
        args.grade_item_id,
        args.grade_item_revision,
    )
    if not args.confirm_select:
        _render_grade_item_selection_preview(
            preview, args.format, confirmation_supplied=False
        )
        return 0
    if args.format == "text":
        _render_grade_item_selection_preview(
            preview, args.format, confirmation_supplied=True
        )
        sys.stdout.flush()
    result = commit_grade_item_selection_preview(
        str(args.workspace), preview
    )
    _render_grade_item_selection_result(preview, result, args.format)
    return 0


def _handle_grade_item_authoring(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    try:
        has_weighting_replacement = (
            args.weighting_category_id is not None
            or args.relative_weight is not None
        )
        if args.clear_weighting and has_weighting_replacement:
            raise GradeItemAuthoringScopeError(
                "--clear-weighting cannot be combined with weighting replacement "
                "fields."
            )
        weighting = None
        weighting_action: GradeItemWeightingAction = "preserve"
        if args.clear_weighting:
            weighting_action = "clear"
        elif has_weighting_replacement:
            weighting_action = "replace"
            weighting = GradeItemWeightingMetadata(
                category_id=args.weighting_category_id,
                relative_weight=args.relative_weight,
            )
        preview = preview_grade_item_authoring(
            str(args.workspace),
            args.class_id,
            args.grade_item_id,
            operation=args.operation,
            actor_id=args.actor_id,
            revised_at=args.revised_at,
            title=args.title,
            purpose=args.purpose,
            weighting=weighting,
            weighting_action=weighting_action,
        )
        if not args.confirm_write:
            _render_grade_item_authoring_preview(
                preview, args.format, confirmation_supplied=False
            )
            return 0
        if args.format == "text":
            _render_grade_item_authoring_preview(
                preview, args.format, confirmation_supplied=True
            )
            sys.stdout.flush()
        result = commit_grade_item_authoring_preview(
            str(args.workspace), preview
        )
    except GradeItemValidationError as error:
        raise GradeItemAuthoringScopeError(str(error)) from error
    _render_grade_item_authoring_result(preview, result, args.format)
    return 0


def _handle_grade_items_review(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    del dependencies
    review = project_grade_items_review(
        str(args.workspace),
        args.class_id,
    )
    _render_grade_items_review(review, args.format)
    return 0


def _handle_new_evidence_eligibility_authoring(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    inspection = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=tuple(args.scope_student_id),
        filters=EvidenceFilters(),
        dependencies=_dependencies(dependencies),
    )
    authorized = inspection.authorized
    class_id = authorized.stored.snapshot.source.publication.work.class_id
    review = project_new_evidence_review(
        str(args.workspace),
        class_id,
        args.grade_item_id,
        authorized,
    )
    preview = preview_new_evidence_eligibility_revision(
        str(args.workspace),
        review,
        authorized,
        item_id=args.item_id,
        disposition=args.disposition,
        actor_id=args.actor_id,
        policy_id=args.policy_id,
        policy_version=args.policy_version,
        reason_codes=tuple(args.reason_code),
        rationale=args.rationale,
        decided_at=datetime.now(UTC),
    )
    if not args.confirm_write:
        _render_new_evidence_eligibility_preview(
            preview, args.format, confirmation_supplied=False
        )
        return 0
    if args.format == "text":
        _render_new_evidence_eligibility_preview(
            preview, args.format, confirmation_supplied=True
        )
        sys.stdout.flush()
    result = commit_new_evidence_eligibility_preview(
        str(args.workspace),
        preview,
        authorized,
    )
    _render_new_evidence_eligibility_authoring_result(
        preview, result, args.format
    )
    return 0


def _handle_new_evidence_eligibility_selection(
    args: argparse.Namespace,
    dependencies: DiagnosticsDependencies | None,
) -> int:
    inspection = inspect_evidence_diagnostic(
        str(args.workspace),
        args.publication_id,
        args.cache_key,
        authorization_purpose_id=args.purpose_id,
        requested_student_ids=tuple(args.scope_student_id),
        filters=EvidenceFilters(),
        dependencies=_dependencies(dependencies),
    )
    authorized = inspection.authorized
    class_id = authorized.stored.snapshot.source.publication.work.class_id
    review = project_new_evidence_review(
        str(args.workspace),
        class_id,
        args.grade_item_id,
        authorized,
    )
    preview = preview_new_evidence_eligibility_selection(
        str(args.workspace),
        review,
        authorized,
        item_id=args.item_id,
        eligibility_revision=args.eligibility_revision,
    )
    if not args.confirm_select:
        _render_new_evidence_eligibility_selection_preview(
            preview, args.format, confirmation_supplied=False
        )
        return 0
    if args.format == "text":
        _render_new_evidence_eligibility_selection_preview(
            preview, args.format, confirmation_supplied=True
        )
        sys.stdout.flush()
    result = commit_new_evidence_eligibility_selection_preview(
        str(args.workspace),
        preview,
        authorized,
    )
    _render_new_evidence_eligibility_selection_result(
        preview, result, args.format
    )
    return 0


def _print_json(value: object) -> None:
    sys.stdout.write(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )


def _new_evidence_eligibility_preview_to_dict(
    preview: NewEvidenceEligibilityAuthoringPreview,
) -> dict[str, object]:
    decision = preview.decision
    policy = decision.policy
    return {
        "class_id": decision.class_id,
        "grade_item_id": decision.grade_item_id,
        "item_id": decision.source.item_id,
        "publication_id": decision.source.publication_id,
        "cache_key": decision.source.cache_key,
        "snapshot_digest": decision.source.snapshot_digest,
        "membership_revision": decision.membership_revision,
        "eligibility_revision": decision.eligibility_revision,
        "supersedes_revision": decision.supersedes_revision,
        "disposition": decision.disposition,
        "actor": {
            "kind": decision.actor.kind,
            "actor_id": decision.actor.actor_id,
        },
        "policy": (
            None
            if policy is None
            else {
                "policy_id": policy.policy_id,
                "policy_version": policy.policy_version,
            }
        ),
        "reason_codes": list(decision.reason_codes),
        "rationale": decision.rationale,
        "source_state": decision.source_state.state,
        "decided_at": decision.decided_at.isoformat().replace(
            "+00:00", "Z"
        ),
        "selected_revision": preview.selected_revision,
    }


def _render_new_evidence_eligibility_preview(
    preview: NewEvidenceEligibilityAuthoringPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "write_confirmed": confirmation_supplied,
                "preview": _new_evidence_eligibility_preview_to_dict(
                    preview
                ),
                "selection_action": "not_performed",
            }
        )
        return
    decision = preview.decision
    print("Eligibility revision preview")
    print(f"Grade Item: {decision.grade_item_id}")
    print(f"item: {decision.source.item_id}")
    print(f"revision: {decision.eligibility_revision}")
    supersedes = decision.supersedes_revision
    print(f"supersedes: {supersedes if supersedes is not None else 'none'}")
    print(f"disposition: {decision.disposition}")
    print(f"teacher actor: {decision.actor.actor_id}")
    if decision.policy is not None:
        print(
            "policy: "
            f"{decision.policy.policy_id}@{decision.policy.policy_version}"
        )
    print(
        "reason codes: " + (", ".join(decision.reason_codes) or "none")
    )
    selected = preview.selected_revision
    print(f"currently selected revision: {selected if selected else 'none'}")
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("committing this exact preview after live revalidation")
    else:
        print("confirmation supplied: no")
        print("NO WRITE PERFORMED; current selection is unchanged")
        print("rerun with --confirm-write to authorize a fresh commit")


def _render_new_evidence_eligibility_authoring_result(
    preview: NewEvidenceEligibilityAuthoringPreview,
    result: NewEvidenceEligibilityAuthoringResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "written",
                "write_confirmed": True,
                "preview": _new_evidence_eligibility_preview_to_dict(
                    preview
                ),
                "result": {
                    "write_disposition": result.write_result.disposition,
                    "written_revision": result.written_revision,
                    "written_disposition": result.written_disposition,
                    "selected_revision_before_write": (
                        result.selected_revision_before_write
                    ),
                    "selected_revision_after_write": (
                        result.selected_revision_after_write
                    ),
                    "selection_changed_during_write": (
                        result.selection_changed_during_write
                    ),
                    "selection_action": "not_performed",
                },
            }
        )
        return
    print(
        "Write committed: eligibility revision "
        f"{result.written_revision} ({result.write_result.disposition})"
    )
    before = result.selected_revision_before_write
    after = result.selected_revision_after_write
    if result.selection_changed_during_write:
        print(
            "WARNING: current eligibility selection changed concurrently: "
            f"{before if before is not None else 'none'} -> "
            f"{after if after is not None else 'none'}"
        )
    else:
        print(
            "selected eligibility revision remains: "
            f"{after if after is not None else 'none'}"
        )
    print("selection action: not performed")


def _new_evidence_eligibility_selection_preview_to_dict(
    preview: NewEvidenceEligibilitySelectionPreview,
) -> dict[str, object]:
    decision = preview.target.decision
    return {
        "class_id": decision.class_id,
        "grade_item_id": decision.grade_item_id,
        "item_id": decision.source.item_id,
        "publication_id": decision.source.publication_id,
        "cache_key": decision.source.cache_key,
        "snapshot_digest": decision.source.snapshot_digest,
        "target_revision": preview.target_revision,
        "target_disposition": preview.target_disposition,
        "target_revision_sha256": preview.target.decision_sha256,
        "expected_current_revision": preview.expected_current_revision,
        "membership_revision": preview.membership_revision,
        "membership_revision_sha256": (
            preview.membership_revision_sha256
        ),
        "source_state": preview.source_state.state,
    }


def _render_new_evidence_eligibility_selection_preview(
    preview: NewEvidenceEligibilitySelectionPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "selection_confirmed": confirmation_supplied,
                "preview": (
                    _new_evidence_eligibility_selection_preview_to_dict(
                        preview
                    )
                ),
                "authoring_action": "not_performed",
            }
        )
        return
    decision = preview.target.decision
    print("Eligibility current-selection preview")
    print(f"Grade Item: {decision.grade_item_id}")
    print(f"item: {decision.source.item_id}")
    print(f"target revision: {preview.target_revision}")
    print(f"target disposition: {preview.target_disposition}")
    print(f"target revision digest: {preview.target.decision_sha256}")
    current = preview.expected_current_revision
    print(
        "currently selected revision: "
        f"{current if current is not None else 'none'}"
    )
    print(f"membership revision: {preview.membership_revision}")
    print(f"source state: {preview.source_state.state}")
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("selecting this exact revision after live CAS revalidation")
    else:
        print("confirmation supplied: no")
        print(
            "NO SELECTION PERFORMED; eligibility history and current "
            "selection are unchanged"
        )
        print("rerun with --confirm-select to authorize a fresh selection")


def _render_new_evidence_eligibility_selection_result(
    preview: NewEvidenceEligibilitySelectionPreview,
    result: NewEvidenceEligibilitySelectionWorkflowResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "selected",
                "selection_confirmed": True,
                "preview": (
                    _new_evidence_eligibility_selection_preview_to_dict(
                        preview
                    )
                ),
                "result": {
                    "selection_disposition": result.selection_disposition,
                    "previous_current_revision": (
                        result.previous_current_revision
                    ),
                    "selected_revision": result.selected_revision,
                    "selected_disposition": result.selected_disposition,
                    "authoring_action": "not_performed",
                },
            }
        )
        return
    print(
        "Selection committed: eligibility revision "
        f"{result.selected_revision} ({result.selection_disposition})"
    )
    previous = result.previous_current_revision
    print(
        "previous current revision: "
        f"{previous if previous is not None else 'none'}"
    )
    print(f"selected disposition: {result.selected_disposition}")
    print("authoring action: not performed")


def _academic_period_calculation_preview_to_dict(
    preview: BoundedAcademicPeriodCalculationPreview,
) -> dict[str, object]:
    calculation = preview.calculation
    outcome = calculation.outcome
    tie = outcome.tie_resolution
    return {
        "scope": {
            "class_id": calculation.class_id,
            "school_year": calculation.school_year,
            "period_id": calculation.period_id,
            "calendar_revision": calculation.calendar_revision,
            "period_label": calculation.target_period_title,
            "student_id": calculation.student_id,
            "standard_id": calculation.standard_id,
        },
        "candidates": {
            "count": preview.candidate_count,
            "grade_item_ids": list(preview.grade_item_ids),
        },
        "inputs": {
            "sha256": calculation.inputs_sha256,
            "entry_count": calculation.input_entry_count,
            "target_scale": {
                "scale_id": preview.inputs.target_scale.scale_id,
                "scale_revision": preview.inputs.target_scale.scale_revision,
                "scale_sha256": preview.inputs.target_scale.scale_sha256,
            },
            "status_counts": [
                {"status": status, "count": count}
                for status, count in calculation.input_status_counts
            ],
        },
        "policy": {
            "policy_id": calculation.policy_reference.policy_id,
            "policy_revision": calculation.policy_reference.policy_revision,
            "policy_sha256": calculation.policy_reference.policy_sha256,
            "title": calculation.policy_title,
            "strategy": calculation.strategy,
            "period_membership_scope": calculation.period_membership_scope,
            "minimum_calculated_results": (
                calculation.minimum_calculated_results
            ),
            "mode_tie_rule": calculation.mode_tie_rule,
            "median_even_rule": calculation.median_even_rule,
            "missing_result_handling": calculation.missing_result_handling,
            "insufficient_result_handling": (
                calculation.insufficient_result_handling
            ),
        },
        "outcome": {
            "status": outcome.status,
            "proficiency_level_id": outcome.proficiency_level_id,
            "calculation_fingerprint": outcome.calculation_fingerprint,
            "candidate_count": outcome.candidate_count,
            "calculated_result_count": outcome.calculated_result_count,
            "insufficient_result_count": outcome.insufficient_result_count,
            "missing_result_count": outcome.missing_result_count,
            "period_scope_mismatch_count": (
                outcome.period_scope_mismatch_count
            ),
            "insufficiency_reasons": [
                {
                    "kind": reason.kind,
                    "grade_item_ids": list(reason.grade_item_ids),
                    "required_results": reason.required_results,
                    "actual_results": reason.actual_results,
                }
                for reason in outcome.insufficiency_reasons
            ],
            "tie_resolution": (
                None
                if tie is None
                else {
                    "kind": tie.kind,
                    "rule": tie.rule,
                    "candidate_level_ids": list(tie.candidate_level_ids),
                    "selected_level_id": tie.selected_level_id,
                }
            ),
        },
        "result_state": {
            "history": list(calculation.result_history),
            "next_revision": calculation.next_result_revision,
            "current_revision": calculation.current_result_revision,
        },
        "result_write_performed": preview.result_write_performed,
        "result_selection_performed": preview.result_selection_performed,
    }


def _render_academic_period_calculation_preview(
    preview: BoundedAcademicPeriodCalculationPreview,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(_academic_period_calculation_preview_to_dict(preview))
        return
    calculation = preview.calculation
    outcome = calculation.outcome
    print("Academic Period Calculation Preview")
    print(f"class: {calculation.class_id}")
    print(
        "Academic Period: "
        f"{calculation.target_period_title} | "
        f"{calculation.school_year}/{calculation.period_id} | "
        f"calendar revision {calculation.calendar_revision}"
    )
    print(f"student: {calculation.student_id}")
    print(f"Standard: {calculation.standard_id}")
    print(f"candidate count: {preview.candidate_count}")
    print(
        "candidate Grade Items: "
        + (", ".join(preview.grade_item_ids) or "none")
    )
    print(f"aggregation inputs SHA-256: {calculation.inputs_sha256}")
    print(
        "target scale: "
        f"{preview.inputs.target_scale.scale_id}@"
        f"{preview.inputs.target_scale.scale_revision}"
    )
    print(
        "period policy: "
        f"{calculation.policy_reference.policy_id}@"
        f"{calculation.policy_reference.policy_revision} | "
        f"{calculation.policy_title}"
    )
    print(f"strategy: {calculation.strategy}")
    print(
        "period membership scope: "
        f"{calculation.period_membership_scope}"
    )
    print(
        "minimum calculated results: "
        f"{calculation.minimum_calculated_results}"
    )
    print(
        "missing-result handling: "
        f"{calculation.missing_result_handling}"
    )
    print(
        "insufficient-result handling: "
        f"{calculation.insufficient_result_handling}"
    )
    if calculation.input_status_counts:
        print("input status counts:")
        for input_status, count in calculation.input_status_counts:
            print(f"  {input_status}: {count}")
    print(f"calculation status: {outcome.status}")
    print(
        "proficiency level: "
        f"{outcome.proficiency_level_id or 'none'}"
    )
    print(
        "result counts: "
        f"calculated={outcome.calculated_result_count} | "
        f"insufficient={outcome.insufficient_result_count} | "
        f"missing={outcome.missing_result_count} | "
        f"period_scope_mismatch={outcome.period_scope_mismatch_count}"
    )
    if outcome.insufficiency_reasons:
        print("insufficiency reasons:")
        for insufficiency_reason in outcome.insufficiency_reasons:
            detail: str = insufficiency_reason.kind
            if insufficiency_reason.grade_item_ids:
                detail += (
                    " | Grade Items="
                    + ",".join(insufficiency_reason.grade_item_ids)
                )
            if insufficiency_reason.required_results is not None:
                detail += (
                    f" | required={insufficiency_reason.required_results}"
                )
            if insufficiency_reason.actual_results is not None:
                detail += (
                    f" | actual={insufficiency_reason.actual_results}"
                )
            print(f"  {detail}")
    tie = outcome.tie_resolution
    if tie is not None:
        print(
            "tie resolution: "
            f"{tie.kind} | rule={tie.rule} | "
            f"selected={tie.selected_level_id or 'none'}"
        )
    print(f"calculation fingerprint: {outcome.calculation_fingerprint}")
    history = ", ".join(str(value) for value in calculation.result_history)
    print(f"persisted period-result history: {history or 'none'}")
    print(
        "next period-result revision if confirmed later: "
        f"{calculation.next_result_revision}"
    )
    current = calculation.current_result_revision
    print(
        "currently selected period-result revision: "
        f"{current if current is not None else 'none'}"
    )
    print("NO ACADEMIC PERIOD PROFICIENCY RESULT WRITTEN")
    print("NO CURRENT ACADEMIC PERIOD RESULT SELECTION CHANGED")


def _academic_period_result_persistence_preview_to_dict(
    preview: AcademicPeriodResultPersistencePreview,
) -> dict[str, object]:
    candidate = preview.candidate
    period = candidate.target_period.period
    return {
        "actor_id": preview.actor_id,
        "class_id": candidate.class_id,
        "school_year": period.school_year,
        "period_id": period.period_id,
        "calendar_revision": candidate.target_period.calendar_revision,
        "student_id": candidate.student_id,
        "standard_id": candidate.standard_id,
        "candidate_revision": preview.candidate_revision,
        "candidate_status": preview.candidate_status,
        "candidate_proficiency_level_id": (
            preview.candidate_proficiency_level_id
        ),
        "candidate_calculation_fingerprint": (
            preview.candidate_calculation_fingerprint
        ),
        "calculated_at": candidate.calculated_at.isoformat(),
        "history_before": list(preview.history_before),
        "latest_result_sha256_before": preview.latest_result_sha256_before,
        "selected_revision_before": preview.selected_revision_before,
        "selection_action": preview.selection_action,
    }


def _render_academic_period_result_persistence_preview(
    preview: AcademicPeriodResultPersistencePreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "write_confirmed": confirmation_supplied,
                "preview": (
                    _academic_period_result_persistence_preview_to_dict(
                        preview
                    )
                ),
            }
        )
        return
    candidate = preview.candidate
    period = candidate.target_period.period
    print("Academic Period result write preview")
    print(f"teacher actor context: {preview.actor_id}")
    print(
        "Academic Period: "
        f"{period.school_year}/{period.period_id} @ calendar revision "
        f"{candidate.target_period.calendar_revision}"
    )
    print(f"student: {candidate.student_id}")
    print(f"Standard: {candidate.standard_id}")
    print(f"candidate period-result revision: {preview.candidate_revision}")
    print(f"calculation status: {preview.candidate_status}")
    print(
        "proficiency level: "
        f"{preview.candidate_proficiency_level_id or 'none'}"
    )
    print(
        "calculation fingerprint: "
        f"{preview.candidate_calculation_fingerprint}"
    )
    print(f"calculated at: {candidate.calculated_at.isoformat()}")
    current = preview.selected_revision_before
    print(
        "currently selected Academic Period result revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print(
            "writing this exact immutable Academic Period result after "
            "live revalidation"
        )
    else:
        print("confirmation supplied: no")
        print("NO ACADEMIC PERIOD PROFICIENCY RESULT WRITTEN")
        print(
            "rerun with --confirm-write to authorize immutable "
            "Academic Period result write"
        )
    print("NO CURRENT ACADEMIC PERIOD RESULT SELECTION CHANGED")


def _render_academic_period_result_persistence_result(
    preview: AcademicPeriodResultPersistencePreview,
    result: AcademicPeriodResultPersistenceWorkflowResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "written",
                "write_confirmed": True,
                "preview": (
                    _academic_period_result_persistence_preview_to_dict(
                        preview
                    )
                ),
                "result": {
                    "write_disposition": result.write_result.disposition,
                    "written_revision": result.written_revision,
                    "written_result_sha256": result.written_result_sha256,
                    "written_status": result.written_status,
                    "written_proficiency_level_id": (
                        result.written_proficiency_level_id
                    ),
                    "selected_revision_after_write": (
                        result.selected_revision_after_write
                    ),
                    "selection_changed_during_write": (
                        result.selection_changed_during_write
                    ),
                    "selection_action": result.selection_action,
                },
            }
        )
        return
    print(
        "Academic Period proficiency result revision "
        f"{result.written_revision} written "
        f"({result.write_result.disposition})"
    )
    print(f"result SHA-256: {result.written_result_sha256}")
    before = preview.selected_revision_before
    after = result.selected_revision_after_write
    if result.selection_changed_during_write:
        print(
            "WARNING: current Academic Period result selection changed "
            "concurrently: "
            f"{before if before is not None else 'none'} -> "
            f"{after if after is not None else 'none'}"
        )
    else:
        print(
            "current Academic Period result selection after write: "
            f"{after if after is not None else 'none'}"
        )
    print(
        "Academic Period result selection action: "
        f"{result.selection_action.replace('_', ' ')}"
    )


def _planning_signal_source_result_to_dict(
    source_result: object | None,
) -> dict[str, object] | None:
    if source_result is None:
        return None
    return {
        "class_id": getattr(source_result, "class_id"),
        "school_year": getattr(source_result, "school_year"),
        "period_id": getattr(source_result, "period_id"),
        "student_id": getattr(source_result, "student_id"),
        "standard_id": getattr(source_result, "standard_id"),
        "result_revision": getattr(source_result, "result_revision"),
        "result_sha256": getattr(source_result, "result_sha256"),
    }


def _planning_signal_readiness_to_dict(
    projection: PlanningSignalReadinessProjection,
) -> dict[str, object]:
    policy = projection.policy
    policy_data: dict[str, object] | None = None
    academic_basis: dict[str, object] | None = None
    if policy is not None:
        reference = policy.reference
        period = policy.target_period.period
        source_policy = policy.source_policy_reference
        scale = policy.target_scale_reference
        policy_data = {
            "policy_id": reference.policy_id,
            "policy_revision": reference.policy_revision,
            "policy_sha256": reference.policy_sha256,
            "title": policy.title,
            "dimension_id": policy.dimension_id,
            "band_count": policy.band_count,
            "band_definitions": [
                {
                    "band": band.band,
                    "minimum_scale_position": band.minimum_scale_position,
                    "maximum_scale_position": band.maximum_scale_position,
                }
                for band in policy.band_definitions
            ],
            "tie_handling": policy.tie_handling,
            "missing_result_handling": policy.missing_result_handling,
            "insufficient_result_handling": (
                policy.insufficient_result_handling
            ),
            "actor": {
                "kind": policy.actor_kind,
                "actor_id": policy.actor_id,
            },
            "rationale": policy.rationale,
            "revised_at": policy.revised_at.isoformat(),
        }
        academic_basis = {
            "school_year": period.school_year,
            "period_id": period.period_id,
            "calendar_revision": policy.target_period.calendar_revision,
            "standard_id": policy.standard_id,
            "source_policy": {
                "policy_id": source_policy.policy_id,
                "policy_revision": source_policy.policy_revision,
                "policy_sha256": source_policy.policy_sha256,
            },
            "target_scale": {
                "scale_id": scale.scale_id,
                "scale_revision": scale.scale_revision,
                "scale_sha256": scale.scale_sha256,
            },
        }

    return {
        "task": "create-planning-signal",
        "class_id": projection.class_id,
        "requested_policy_id": projection.policy_id,
        "policy": policy_data,
        "academic_basis": academic_basis,
        "generation": {
            "status": projection.generation_status,
            "ready_for_derivation_persistence": (
                projection.ready_for_derivation_persistence
            ),
            "blockers": [
                {
                    "code": blocker.code,
                    "student_id": blocker.student_id,
                    "source_result": _planning_signal_source_result_to_dict(
                        blocker.source_result
                    ),
                    "freshness_reasons": list(blocker.freshness_reasons),
                }
                for blocker in projection.generation.blockers
            ],
            "candidate_derivation_id": projection.candidate_derivation_id,
            "candidate_calculation_fingerprint": (
                projection.candidate_calculation_fingerprint
            ),
            "roster_student_count": projection.roster_student_count,
            "contributing_student_count": (
                projection.contributing_student_count
            ),
            "noncontributing_student_count": (
                projection.noncontributing_student_count
            ),
        },
        "actions": {
            "derivation_write": projection.derivation_write_action,
            "preview_write": projection.preview_write_action,
            "review_write": projection.review_write_action,
            "review_selection": projection.review_selection_action,
            "core_export": projection.core_export_action,
            "csv_export": projection.csv_export_action,
        },
        "concord_action": "not_performed",
    }


def _render_planning_signal_readiness(
    projection: PlanningSignalReadinessProjection,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(_planning_signal_readiness_to_dict(projection))
        return

    print("Create Planning Signal — readiness")
    print(f"class: {projection.class_id}")
    policy = projection.policy
    if policy is None:
        print("selected #37 policy: none")
    else:
        reference = policy.reference
        period = policy.target_period.period
        source_policy = policy.source_policy_reference
        scale = policy.target_scale_reference
        print(
            "selected #37 policy: "
            f"{reference.policy_id}@{reference.policy_revision}"
        )
        print(f"policy SHA-256: {reference.policy_sha256}")
        print(f"policy title: {policy.title}")
        print(
            "Academic Period: "
            f"{period.school_year}/{period.period_id} @ calendar revision "
            f"{policy.target_period.calendar_revision}"
        )
        print(f"Standard: {policy.standard_id}")
        print(
            "#35 source policy: "
            f"{source_policy.policy_id}@{source_policy.policy_revision}"
        )
        print(
            "target proficiency scale: "
            f"{scale.scale_id}@{scale.scale_revision}"
        )
        print(f"grouping dimension: {policy.dimension_id}")
        print(f"band count: {policy.band_count}")
        print("band boundaries:")
        for band in policy.band_definitions:
            print(
                f"  band {band.band}: scale positions "
                f"{band.minimum_scale_position}-"
                f"{band.maximum_scale_position}"
            )
        print(f"tie handling: {policy.tie_handling}")
        print(
            "missing-result handling: "
            f"{policy.missing_result_handling}"
        )
        print(
            "insufficient-result handling: "
            f"{policy.insufficient_result_handling}"
        )

    if projection.ready_for_derivation_persistence:
        print("generation readiness: ready")
        print(
            "candidate derivation ID: "
            f"{projection.candidate_derivation_id}"
        )
        print(
            "candidate calculation fingerprint: "
            f"{projection.candidate_calculation_fingerprint}"
        )
        print(f"roster students: {projection.roster_student_count}")
        print(
            "contributing students: "
            f"{projection.contributing_student_count}"
        )
        print(
            "noncontributing students: "
            f"{projection.noncontributing_student_count}"
        )
    else:
        print("generation readiness: blocked")
        print("blockers:")
        for blocker in projection.generation.blockers:
            detail: str = blocker.code
            if blocker.student_id is not None:
                detail += f" | student={blocker.student_id}"
            if blocker.source_result is not None:
                source = blocker.source_result
                detail += (
                    f" | result={source.result_revision}@"
                    f"{source.result_sha256}"
                )
            if blocker.freshness_reasons:
                detail += (
                    " | freshness="
                    + ",".join(blocker.freshness_reasons)
                )
            print(f"  {detail}")

    print("NO #38 DERIVATION PERSISTED")
    print("NO #39 PREVIEW OR REVIEW WRITTEN")
    print("NO REVIEW SELECTION CHANGED")
    print("NO CORE GROUPING SIGNAL OR CSV EXPORTED")
    print("NO CONCORD GROUP OR GROUPPLAN CREATED")


def _planning_signal_preview_write_source_to_dict(
    preview: PlanningSignalPreviewWritePreview,
) -> dict[str, object]:
    policy = preview.policy_reference
    return {
        "class_id": preview.class_id,
        "policy_id": preview.policy_id,
        "bound_policy_revision": policy.policy_revision,
        "bound_policy_sha256": policy.policy_sha256,
        "derivation_id": preview.derivation_id,
        "derivation_sha256": preview.derivation_sha256,
        "calculation_fingerprint": preview.calculation_fingerprint,
        "roster_student_count": preview.roster_student_count,
        "contributing_student_count": preview.contributing_student_count,
        "noncontributing_student_count": preview.noncontributing_student_count,
    }


def _render_planning_signal_preview_write_preview(
    preview: PlanningSignalPreviewWritePreview,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "task": "create-planning-signal",
                "mode": "preview_write_intent",
                "preview_write_confirmed": False,
                "source_derivation": (
                    _planning_signal_preview_write_source_to_dict(preview)
                ),
                "actions": {
                    "derivation_write": "not_performed",
                    "preview_write": preview.preview_write_action,
                    "review_write": preview.review_write_action,
                    "review_selection": preview.review_selection_action,
                    "core_export": preview.core_export_action,
                    "csv_export": preview.csv_export_action,
                },
                "concord_action": "not_performed",
            }
        )
        return

    policy = preview.policy_reference
    print("Create Planning Signal — #39 preview write")
    print(f"class: {preview.class_id}")
    print(
        "bound #37 policy: "
        f"{policy.policy_id}@{policy.policy_revision}"
    )
    print(f"exact #38 derivation: {preview.derivation_id}")
    print(f"derivation SHA-256: {preview.derivation_sha256}")
    print(
        "derivation calculation fingerprint: "
        f"{preview.calculation_fingerprint}"
    )
    print(f"roster students: {preview.roster_student_count}")
    print(
        "contributing students: "
        f"{preview.contributing_student_count}"
    )
    print(
        "noncontributing students: "
        f"{preview.noncontributing_student_count}"
    )
    print("preview write confirmation supplied: no")
    print("NO #39 PREVIEW WRITTEN")
    print("NO TEACHER REVIEW WRITTEN")
    print("NO REVIEW SELECTION CHANGED")
    print("NO CORE GROUPING SIGNAL OR CSV EXPORTED")
    print("NO CONCORD GROUP OR GROUPPLAN CREATED")


def _render_planning_signal_preview_write_confirmation(
    preview: PlanningSignalPreviewWritePreview,
) -> None:
    print("Create Planning Signal — #39 preview write")
    print(f"exact #38 derivation: {preview.derivation_id}")
    print(f"derivation SHA-256: {preview.derivation_sha256}")
    print("preview write confirmation supplied: yes")
    print(
        "generating and persisting the canonical immutable #39 preview "
        "from this exact #38 source"
    )
    print("NO TEACHER REVIEW OR EXPORT WILL OCCUR")


def _render_planning_signal_preview_write_result(
    preview: PlanningSignalPreviewWritePreview,
    result: PlanningSignalPreviewWriteResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "task": "create-planning-signal",
                "mode": "preview_written",
                "preview_write_confirmed": True,
                "source_derivation": (
                    _planning_signal_preview_write_source_to_dict(preview)
                ),
                "preview": {
                    "preview_id": result.preview_id,
                    "preview_sha256": result.preview_sha256,
                    "preview_fingerprint": result.preview_fingerprint,
                    "write_disposition": result.write_disposition,
                    "currentness_state": result.currentness_state,
                    "currentness_reason_codes": list(
                        result.currentness_reason_codes
                    ),
                    "diagnostic_count": result.diagnostic_count,
                    "warning_diagnostic_ids": list(
                        result.warning_diagnostic_ids
                    ),
                    "blocking_diagnostic_ids": list(
                        result.blocking_diagnostic_ids
                    ),
                    "roster_student_count": result.roster_student_count,
                    "contributing_student_count": (
                        result.contributing_student_count
                    ),
                    "noncontributing_student_count": (
                        result.noncontributing_student_count
                    ),
                },
                "actions": {
                    "derivation_write": "not_performed",
                    "preview_write": "performed",
                    "review_write": result.review_write_action,
                    "review_selection": result.review_selection_action,
                    "core_export": result.core_export_action,
                    "csv_export": result.csv_export_action,
                },
                "concord_action": "not_performed",
            }
        )
        return

    print(f"#39 preview persisted: {result.preview_id}")
    print(f"preview SHA-256: {result.preview_sha256}")
    print(f"preview fingerprint: {result.preview_fingerprint}")
    print(f"write disposition: {result.write_disposition}")
    print(f"preview currentness: {result.currentness_state}")
    print(
        "currentness reasons: "
        + (
            ", ".join(result.currentness_reason_codes)
            if result.currentness_reason_codes
            else "none"
        )
    )
    print(f"diagnostics: {result.diagnostic_count}")
    print(
        "warning diagnostic IDs: "
        + (
            ", ".join(result.warning_diagnostic_ids)
            if result.warning_diagnostic_ids
            else "none"
        )
    )
    print(
        "blocking diagnostic IDs: "
        + (
            ", ".join(result.blocking_diagnostic_ids)
            if result.blocking_diagnostic_ids
            else "none"
        )
    )
    print("NO TEACHER REVIEW WRITTEN")
    print("NO REVIEW SELECTION CHANGED")
    print("NO CORE GROUPING SIGNAL OR CSV EXPORTED")
    print("NO CONCORD GROUP OR GROUPPLAN CREATED")


def _planning_signal_derivation_preview_to_dict(
    preview: PlanningSignalDerivationPersistencePreview,
) -> dict[str, object]:
    return {
        "derivation_id": preview.derivation_id,
        "calculation_fingerprint": preview.calculation_fingerprint,
        "roster_student_count": preview.roster_student_count,
        "contributing_student_count": preview.contributing_student_count,
        "noncontributing_student_count": preview.noncontributing_student_count,
    }


def _render_planning_signal_derivation_persistence_preview(
    projection: PlanningSignalReadinessProjection,
    preview: PlanningSignalDerivationPersistencePreview,
    output_format: str,
) -> None:
    if output_format == "json":
        data = _planning_signal_readiness_to_dict(projection)
        data["mode"] = "derivation_write_preview"
        data["derivation_write_confirmed"] = False
        data["derivation"] = _planning_signal_derivation_preview_to_dict(
            preview
        )
        _print_json(data)
        return

    _render_planning_signal_readiness(projection, "text")
    print(f"derivation write candidate: {preview.derivation_id}")
    print(
        "derivation candidate fingerprint: "
        f"{preview.calculation_fingerprint}"
    )
    print("derivation write confirmation supplied: no")
    print(
        "rerun with --confirm-derivation-write to persist this exact "
        "#38 candidate after live revalidation"
    )


def _render_planning_signal_derivation_write_confirmation(
    preview: PlanningSignalDerivationPersistencePreview,
) -> None:
    print("Create Planning Signal — #38 derivation write")
    print(f"derivation write candidate: {preview.derivation_id}")
    print(
        "derivation candidate fingerprint: "
        f"{preview.calculation_fingerprint}"
    )
    print(f"roster students: {preview.roster_student_count}")
    print(
        "contributing students: "
        f"{preview.contributing_student_count}"
    )
    print(
        "noncontributing students: "
        f"{preview.noncontributing_student_count}"
    )
    print("derivation write confirmation supplied: yes")
    print(
        "persisting this exact immutable #38 candidate after live "
        "readiness revalidation"
    )


def _render_planning_signal_derivation_persistence_result(
    projection: PlanningSignalReadinessProjection,
    result: PlanningSignalDerivationPersistenceResult,
    output_format: str,
) -> None:
    if output_format == "json":
        data = _planning_signal_readiness_to_dict(projection)
        data["mode"] = "derivation_written"
        data["derivation_write_confirmed"] = True
        data["derivation"] = {
            "derivation_id": result.derivation_id,
            "derivation_sha256": result.derivation_sha256,
            "calculation_fingerprint": result.calculation_fingerprint,
            "write_disposition": result.write_disposition,
        }
        data["actions"] = {
            "derivation_write": "performed",
            "preview_write": result.preview_write_action,
            "review_write": result.review_write_action,
            "review_selection": result.review_selection_action,
            "core_export": result.core_export_action,
            "csv_export": result.csv_export_action,
        }
        _print_json(data)
        return

    print(f"#38 derivation persisted: {result.derivation_id}")
    print(f"derivation SHA-256: {result.derivation_sha256}")
    print(f"write disposition: {result.write_disposition}")
    print(
        "calculation fingerprint: "
        f"{result.calculation_fingerprint}"
    )
    print("NO #39 PREVIEW OR REVIEW WRITTEN")
    print("NO REVIEW SELECTION CHANGED")
    print("NO CORE GROUPING SIGNAL OR CSV EXPORTED")
    print("NO CONCORD GROUP OR GROUPPLAN CREATED")


def _academic_period_result_selection_preview_to_dict(
    preview: AcademicPeriodResultSelectionPreview,
) -> dict[str, object]:
    return {
        "class_id": preview.class_id,
        "school_year": preview.school_year,
        "period_id": preview.period_id,
        "calendar_revision": preview.calendar_revision,
        "student_id": preview.student_id,
        "standard_id": preview.standard_id,
        "target_revision": preview.target_revision,
        "target_result_sha256": preview.target_result_sha256,
        "target_status": preview.target_status,
        "target_proficiency_level_id": (
            preview.target_proficiency_level_id
        ),
        "target_calculation_fingerprint": (
            preview.target_calculation_fingerprint
        ),
        "history": list(preview.history),
        "target_is_latest": preview.target_is_latest,
        "expected_current_result_revision": (
            preview.expected_current_result_revision
        ),
        "authoring_action": preview.authoring_action,
    }


def _render_academic_period_result_selection_preview(
    preview: AcademicPeriodResultSelectionPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "selection_confirmed": confirmation_supplied,
                "preview": (
                    _academic_period_result_selection_preview_to_dict(
                        preview
                    )
                ),
            }
        )
        return
    print("Academic Period result selection preview")
    print(
        "Academic Period: "
        f"{preview.school_year}/{preview.period_id} @ calendar revision "
        f"{preview.calendar_revision}"
    )
    print(f"student: {preview.student_id}")
    print(f"Standard: {preview.standard_id}")
    print(f"target result revision: {preview.target_revision}")
    print(f"target result SHA-256: {preview.target_result_sha256}")
    print(f"target calculation status: {preview.target_status}")
    print(
        "target proficiency level: "
        f"{preview.target_proficiency_level_id or 'none'}"
    )
    print(
        "target calculation fingerprint: "
        f"{preview.target_calculation_fingerprint}"
    )
    print(
        "persisted Academic Period result history: "
        + (", ".join(str(value) for value in preview.history) or "none")
    )
    print(
        "target is latest: "
        f"{'yes' if preview.target_is_latest else 'no'}"
    )
    current = preview.expected_current_result_revision
    print(
        "currently selected Academic Period result revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print(
            "selecting this exact persisted Academic Period result "
            "after live CAS revalidation"
        )
    else:
        print("confirmation supplied: no")
        print("NO CURRENT ACADEMIC PERIOD RESULT SELECTION CHANGED")
        print(
            "rerun with --confirm-select to authorize Academic Period "
            "pointer mutation"
        )
    print("NO ACADEMIC PERIOD PROFICIENCY RESULT AUTHORED OR RECALCULATED")


def _render_academic_period_result_selection_result(
    preview: AcademicPeriodResultSelectionPreview,
    result: AcademicPeriodResultSelectionWorkflowResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "selected",
                "selection_confirmed": True,
                "preview": (
                    _academic_period_result_selection_preview_to_dict(
                        preview
                    )
                ),
                "result": {
                    "selection_disposition": result.selection_disposition,
                    "previous_current_result_revision": (
                        result.previous_current_result_revision
                    ),
                    "selected_revision": result.selected_revision,
                    "selected_result_sha256": result.selected_result_sha256,
                    "selected_status": result.selected_status,
                    "selected_proficiency_level_id": (
                        result.selected_proficiency_level_id
                    ),
                    "authoring_action": result.authoring_action,
                },
            }
        )
        return
    print(
        "Academic Period result selection committed: revision "
        f"{result.selected_revision} ({result.selection_disposition})"
    )
    previous = result.previous_current_result_revision
    print(
        "previous current Academic Period result revision: "
        f"{previous if previous is not None else 'none'}"
    )
    print(f"selected result SHA-256: {result.selected_result_sha256}")
    print(f"selected calculation status: {result.selected_status}")
    print(
        "selected proficiency level: "
        f"{result.selected_proficiency_level_id or 'none'}"
    )
    print(
        "authoring action: "
        f"{result.authoring_action.replace('_', ' ')}"
    )


def _calculation_result_selection_preview_to_dict(
    preview: CalculationResultSelectionPreview,
) -> dict[str, object]:
    return {
        "class_id": preview.class_id,
        "grade_item_id": preview.grade_item_id,
        "student_id": preview.student_id,
        "standard_id": preview.standard_id,
        "target_revision": preview.target_revision,
        "target_result_sha256": preview.target_result_sha256,
        "target_status": preview.target_status,
        "target_proficiency_level_id": (
            preview.target_proficiency_level_id
        ),
        "target_calculation_fingerprint": (
            preview.target_calculation_fingerprint
        ),
        "history": list(preview.history),
        "target_is_latest": preview.target_is_latest,
        "expected_current_result_revision": (
            preview.expected_current_result_revision
        ),
        "authoring_action": preview.authoring_action,
    }


def _render_calculation_result_selection_preview(
    preview: CalculationResultSelectionPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "selection_confirmed": confirmation_supplied,
                "preview": _calculation_result_selection_preview_to_dict(
                    preview
                ),
            }
        )
        return
    print("Calculation result selection preview")
    print(f"Grade Item: {preview.grade_item_id}")
    print(f"student: {preview.student_id}")
    print(f"Standard: {preview.standard_id}")
    print(f"target result revision: {preview.target_revision}")
    print(f"target result SHA-256: {preview.target_result_sha256}")
    print(f"target calculation status: {preview.target_status}")
    print(
        "target proficiency level: "
        f"{preview.target_proficiency_level_id or 'none'}"
    )
    print(
        "target calculation fingerprint: "
        f"{preview.target_calculation_fingerprint}"
    )
    print(
        "persisted result history: "
        + (", ".join(str(value) for value in preview.history) or "none")
    )
    print(
        "target is latest: "
        f"{'yes' if preview.target_is_latest else 'no'}"
    )
    current = preview.expected_current_result_revision
    print(
        "currently selected result revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("selecting this exact persisted result after live CAS revalidation")
    else:
        print("confirmation supplied: no")
        print("NO CURRENT RESULT SELECTION CHANGED")
        print("rerun with --confirm-select to authorize pointer mutation")
    print("NO PROFICIENCY RESULT AUTHORED OR RECALCULATED")


def _render_calculation_result_selection_result(
    preview: CalculationResultSelectionPreview,
    result: CalculationResultSelectionWorkflowResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "selected",
                "selection_confirmed": True,
                "preview": _calculation_result_selection_preview_to_dict(
                    preview
                ),
                "result": {
                    "selection_disposition": result.selection_disposition,
                    "previous_current_result_revision": (
                        result.previous_current_result_revision
                    ),
                    "selected_revision": result.selected_revision,
                    "selected_result_sha256": result.selected_result_sha256,
                    "selected_status": result.selected_status,
                    "selected_proficiency_level_id": (
                        result.selected_proficiency_level_id
                    ),
                    "authoring_action": result.authoring_action,
                },
            }
        )
        return
    print(
        "Result selection committed: revision "
        f"{result.selected_revision} ({result.selection_disposition})"
    )
    previous = result.previous_current_result_revision
    print(
        "previous current result revision: "
        f"{previous if previous is not None else 'none'}"
    )
    print(f"selected result SHA-256: {result.selected_result_sha256}")
    print(f"selected calculation status: {result.selected_status}")
    print(
        "selected proficiency level: "
        f"{result.selected_proficiency_level_id or 'none'}"
    )
    print(
        "authoring action: "
        f"{result.authoring_action.replace('_', ' ')}"
    )


def _calculation_result_persistence_preview_to_dict(
    preview: CalculationResultPersistencePreview,
) -> dict[str, object]:
    candidate = preview.candidate
    return {
        "actor_id": preview.actor_id,
        "class_id": candidate.class_id,
        "grade_item_id": candidate.grade_item_id,
        "student_id": candidate.student_id,
        "standard_id": candidate.standard_id,
        "candidate_revision": preview.candidate_revision,
        "candidate_status": preview.candidate_status,
        "candidate_proficiency_level_id": (
            preview.candidate_proficiency_level_id
        ),
        "candidate_calculation_fingerprint": (
            preview.candidate_calculation_fingerprint
        ),
        "calculated_at": candidate.calculated_at.isoformat(),
        "history_before": list(preview.history_before),
        "latest_result_sha256_before": preview.latest_result_sha256_before,
        "selected_revision_before": preview.selected_revision_before,
        "selection_action": preview.selection_action,
    }


def _render_calculation_result_persistence_preview(
    preview: CalculationResultPersistencePreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "write_confirmed": confirmation_supplied,
                "preview": (
                    _calculation_result_persistence_preview_to_dict(preview)
                ),
            }
        )
        return
    print("Calculation result write preview")
    print(f"teacher actor context: {preview.actor_id}")
    print(f"Grade Item: {preview.candidate.grade_item_id}")
    print(f"student: {preview.candidate.student_id}")
    print(f"Standard: {preview.candidate.standard_id}")
    print(f"candidate result revision: {preview.candidate_revision}")
    print(f"calculation status: {preview.candidate_status}")
    print(
        "proficiency level: "
        f"{preview.candidate_proficiency_level_id or 'none'}"
    )
    print(
        "calculation fingerprint: "
        f"{preview.candidate_calculation_fingerprint}"
    )
    print(f"calculated at: {preview.candidate.calculated_at.isoformat()}")
    current = preview.selected_revision_before
    print(
        "currently selected result revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("writing this exact immutable result after live revalidation")
    else:
        print("confirmation supplied: no")
        print("NO PROFICIENCY RESULT WRITTEN")
        print("rerun with --confirm-write to authorize immutable result write")
    print("NO CURRENT RESULT SELECTION CHANGED")


def _render_calculation_result_persistence_result(
    preview: CalculationResultPersistencePreview,
    result: CalculationResultPersistenceWorkflowResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "written",
                "write_confirmed": True,
                "preview": (
                    _calculation_result_persistence_preview_to_dict(preview)
                ),
                "result": {
                    "write_disposition": result.write_result.disposition,
                    "written_revision": result.written_revision,
                    "written_result_sha256": result.written_result_sha256,
                    "written_status": result.written_status,
                    "written_proficiency_level_id": (
                        result.written_proficiency_level_id
                    ),
                    "selected_revision_after_write": (
                        result.selected_revision_after_write
                    ),
                    "selection_changed_during_write": (
                        result.selection_changed_during_write
                    ),
                    "selection_action": result.selection_action,
                },
            }
        )
        return
    print(
        f"Proficiency result revision {result.written_revision} written "
        f"({result.write_result.disposition})"
    )
    print(f"result SHA-256: {result.written_result_sha256}")
    before = preview.selected_revision_before
    after = result.selected_revision_after_write
    if result.selection_changed_during_write:
        print(
            "WARNING: current result selection changed concurrently: "
            f"{before if before is not None else 'none'} -> "
            f"{after if after is not None else 'none'}"
        )
    else:
        print(
            "current result selection after write: "
            f"{after if after is not None else 'none'}"
        )
    print(
        "result selection action: "
        f"{result.selection_action.replace('_', ' ')}"
    )


def _calculation_preview_to_dict(
    preview: BoundedCalculationPreview,
) -> dict[str, object]:
    calculation = preview.calculation
    outcome = calculation.outcome
    tie = outcome.tie_resolution
    return {
        "scope": {
            "class_id": preview.class_id,
            "grade_item_id": preview.grade_item_id,
            "grade_item_revision": preview.grade_item_basis.grade_item_revision,
            "grade_item_revision_sha256": (
                preview.grade_item_basis.grade_item_revision_sha256
            ),
            "student_id": preview.student_id,
            "standard_id": preview.standard_id,
        },
        "bindings": {
            "count": preview.binding_count,
            "source_keys": list(preview.source_keys),
        },
        "inputs": {
            "sha256": preview.inputs.sha256,
            "entry_count": calculation.input_entry_count,
            "target_scale": {
                "scale_id": preview.inputs.target_scale.scale_id,
                "scale_revision": preview.inputs.target_scale.scale_revision,
                "scale_sha256": preview.inputs.target_scale.scale_sha256,
            },
            "exclusion_reason_counts": [
                {"reason": reason, "count": count}
                for reason, count in calculation.exclusion_reason_counts
            ],
        },
        "policy": {
            "policy_id": calculation.policy_reference.policy_id,
            "policy_revision": calculation.policy_reference.policy_revision,
            "policy_sha256": calculation.policy_reference.policy_sha256,
            "title": calculation.policy_title,
            "strategy": calculation.strategy,
            "minimum_performance_observations": (
                calculation.minimum_performance_observations
            ),
            "mode_tie_rule": calculation.mode_tie_rule,
            "median_even_rule": calculation.median_even_rule,
            "blocking_exclusion_reasons": list(
                calculation.blocking_exclusion_reasons
            ),
            "native_state_handling": calculation.native_state_handling,
        },
        "outcome": {
            "status": outcome.status,
            "proficiency_level_id": outcome.proficiency_level_id,
            "calculation_fingerprint": outcome.calculation_fingerprint,
            "performance_observation_count": (
                outcome.performance_observation_count
            ),
            "native_state_count": outcome.native_state_count,
            "excluded_count": outcome.excluded_count,
            "insufficiency_reasons": [
                {
                    "kind": reason.kind,
                    "source_keys": list(reason.source_keys),
                    "required_observations": reason.required_observations,
                    "actual_observations": reason.actual_observations,
                }
                for reason in outcome.insufficiency_reasons
            ],
            "tie_resolution": (
                None
                if tie is None
                else {
                    "kind": tie.kind,
                    "rule": tie.rule,
                    "candidate_level_ids": list(tie.candidate_level_ids),
                    "selected_level_id": tie.selected_level_id,
                }
            ),
        },
        "result_state": {
            "history": list(calculation.result_history),
            "next_revision": calculation.next_result_revision,
            "current_revision": calculation.current_result_revision,
        },
        "result_write_performed": preview.result_write_performed,
        "result_selection_performed": preview.result_selection_performed,
    }


def _render_calculation_preview(
    preview: BoundedCalculationPreview,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(_calculation_preview_to_dict(preview))
        return
    calculation = preview.calculation
    outcome = calculation.outcome
    print("Calculation Preview")
    print(f"class: {preview.class_id}")
    print(f"Grade Item: {preview.grade_item_id}")
    print(
        "Grade Item basis: revision "
        f"{preview.grade_item_basis.grade_item_revision} | "
        f"{preview.grade_item_basis.grade_item_revision_sha256}"
    )
    print(f"student: {preview.student_id}")
    print(f"Standard: {preview.standard_id}")
    print(f"binding count: {preview.binding_count}")
    print(f"aggregation inputs SHA-256: {preview.inputs.sha256}")
    print(
        "target scale: "
        f"{preview.inputs.target_scale.scale_id}@"
        f"{preview.inputs.target_scale.scale_revision}"
    )
    print(
        "calculation policy: "
        f"{calculation.policy_reference.policy_id}@"
        f"{calculation.policy_reference.policy_revision} | "
        f"{calculation.policy_title}"
    )
    print(f"strategy: {calculation.strategy}")
    print(
        "minimum performance observations: "
        f"{calculation.minimum_performance_observations}"
    )
    print(
        "input counts: "
        f"performance={outcome.performance_observation_count} | "
        f"native_state={outcome.native_state_count} | "
        f"excluded={outcome.excluded_count}"
    )
    if calculation.exclusion_reason_counts:
        print("exclusion reason counts:")
        for exclusion_reason, count in calculation.exclusion_reason_counts:
            print(f"  {exclusion_reason}: {count}")
    print(f"calculation status: {outcome.status}")
    print(
        "proficiency level: "
        f"{outcome.proficiency_level_id or 'none'}"
    )
    if outcome.insufficiency_reasons:
        print("insufficiency reasons:")
        for insufficiency_reason in outcome.insufficiency_reasons:
            detail: str = insufficiency_reason.kind
            if insufficiency_reason.required_observations is not None:
                detail += (
                    f" | required={insufficiency_reason.required_observations}"
                )
            if insufficiency_reason.actual_observations is not None:
                detail += (
                    f" | actual={insufficiency_reason.actual_observations}"
                )
            if insufficiency_reason.source_keys:
                detail += (
                    f" | sources={','.join(insufficiency_reason.source_keys)}"
                )
            print(f"  {detail}")
    tie = outcome.tie_resolution
    if tie is not None:
        print(
            "tie resolution: "
            f"{tie.kind} | rule={tie.rule} | "
            f"selected={tie.selected_level_id or 'none'}"
        )
    print(f"calculation fingerprint: {outcome.calculation_fingerprint}")
    history = ", ".join(str(value) for value in calculation.result_history)
    print(f"persisted result history: {history or 'none'}")
    print(
        "next result revision if confirmed later: "
        f"{calculation.next_result_revision}"
    )
    current = calculation.current_result_revision
    print(
        "currently selected result revision: "
        f"{current if current is not None else 'none'}"
    )
    print("NO PROFICIENCY RESULT WRITTEN")
    print("NO CURRENT RESULT SELECTION CHANGED")


def _standards_association_selection_preview_to_dict(
    preview: StandardsAssociationSelectionPreview,
) -> dict[str, object]:
    decision = preview.target.decision
    return {
        "class_id": decision.class_id,
        "grade_item_id": decision.grade_item_id,
        "standard_id": decision.standard_id,
        "item_id": decision.source.item_id,
        "target_revision": preview.target_revision,
        "target_disposition": preview.target_disposition,
        "target_basis": preview.target_basis,
        "target_decision_sha256": preview.target_sha256,
        "history": list(preview.history),
        "expected_current_association_revision": (
            preview.expected_current_association_revision
        ),
        "actor_kind": decision.actor.kind,
        "actor_id": decision.actor.actor_id,
        "rationale": decision.rationale,
        "authoring_action": preview.authoring_action,
    }


def _render_standards_association_selection_preview(
    preview: StandardsAssociationSelectionPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "selection_confirmed": confirmation_supplied,
                "preview": (
                    _standards_association_selection_preview_to_dict(
                        preview
                    )
                ),
            }
        )
        return
    decision = preview.target.decision
    print("Standards association selection preview")
    print(f"Standard: {decision.standard_id}")
    print(f"evidence item: {decision.source.item_id}")
    print(f"target revision: {preview.target_revision}")
    print(f"target association: {preview.target_disposition}")
    print(f"target basis: {preview.target_basis}")
    current = preview.expected_current_association_revision
    print(
        "currently selected association revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("selecting this exact persisted association revision")
    else:
        print("confirmation supplied: no")
        print("NO CURRENT ASSOCIATION SELECTION CHANGED")
        print("rerun with --confirm-select to authorize pointer mutation")
    print("NO ASSOCIATION REVISION AUTHORED")


def _render_standards_association_selection_result(
    preview: StandardsAssociationSelectionPreview,
    result: StandardsAssociationSelectionWorkflowResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "selected",
                "selection_confirmed": True,
                "preview": (
                    _standards_association_selection_preview_to_dict(
                        preview
                    )
                ),
                "result": {
                    "selected_revision": result.selected_revision,
                    "selected_disposition": result.selected_disposition,
                    "selected_basis": result.selected_basis,
                    "selected_decision_sha256": (
                        result.selected_decision_sha256
                    ),
                    "selection_disposition": (
                        result.selection_disposition
                    ),
                    "previous_current_revision": (
                        result.previous_current_revision
                    ),
                    "authoring_action": result.authoring_action,
                },
            }
        )
        return
    print(
        "Association selection committed: revision "
        f"{result.selected_revision} ({result.selection_disposition})"
    )
    previous = result.previous_current_revision
    print(
        "previous current association revision: "
        f"{previous if previous is not None else 'none'}"
    )
    print(
        "association authoring: "
        f"{result.authoring_action.replace('_', ' ')}"
    )


def _standards_association_authoring_preview_to_dict(
    preview: StandardsAssociationAuthoringPreview,
) -> dict[str, object]:
    candidate = preview.candidate
    return {
        "operation": preview.operation,
        "class_id": candidate.class_id,
        "grade_item_id": candidate.grade_item_id,
        "standard_id": candidate.standard_id,
        "item_id": candidate.source.item_id,
        "candidate_revision": preview.candidate_revision,
        "supersedes_revision": candidate.supersedes_revision,
        "disposition": preview.candidate_disposition,
        "basis": preview.candidate_basis,
        "history": list(preview.history),
        "latest_revision_sha256": preview.latest_revision_sha256,
        "expected_current_association_revision": (
            preview.expected_current_association_revision
        ),
        "grade_item_revision": preview.grade_item_revision,
        "membership_revision": preview.membership_revision,
        "standard_resolved": preview.standard_resolved,
        "standard_active": preview.standard_active,
        "actor_kind": candidate.actor.kind,
        "actor_id": candidate.actor.actor_id,
        "rationale": candidate.rationale,
        "decided_at": candidate.decided_at.isoformat(),
        "selection_action": preview.selection_action,
    }


def _render_standards_association_authoring_preview(
    preview: StandardsAssociationAuthoringPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "write_confirmed": confirmation_supplied,
                "preview": (
                    _standards_association_authoring_preview_to_dict(
                        preview
                    )
                ),
            }
        )
        return
    candidate = preview.candidate
    print("Standards association authoring preview")
    print(f"operation: {preview.operation}")
    print(f"Standard: {candidate.standard_id}")
    print(f"evidence item: {candidate.source.item_id}")
    print(f"candidate revision: {preview.candidate_revision}")
    print(f"association: {preview.candidate_disposition}")
    print(f"basis: {preview.candidate_basis}")
    print(f"teacher actor: {candidate.actor.actor_id}")
    current = preview.expected_current_association_revision
    print(
        "currently selected association revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("writing this exact immutable association revision")
    else:
        print("confirmation supplied: no")
        print("NO ASSOCIATION REVISION WRITTEN")
        print("rerun with --confirm-write to authorize immutable write")
    print("NO CURRENT ASSOCIATION SELECTION CHANGED")


def _render_standards_association_authoring_result(
    preview: StandardsAssociationAuthoringPreview,
    result: StandardsAssociationAuthoringResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "written",
                "write_confirmed": True,
                "preview": (
                    _standards_association_authoring_preview_to_dict(
                        preview
                    )
                ),
                "result": {
                    "written_revision": result.written_revision,
                    "written_disposition": result.written_disposition,
                    "written_basis": result.written_basis,
                    "write_disposition": (
                        result.write_result.disposition
                    ),
                    "selected_revision_before_write": (
                        result.selected_revision_before_write
                    ),
                    "selected_revision_after_write": (
                        result.selected_revision_after_write
                    ),
                    "selection_changed_during_write": (
                        result.selection_changed_during_write
                    ),
                    "selection_action": result.selection_action,
                },
            }
        )
        return
    print(
        "Association revision written: "
        f"{result.written_revision} ({result.write_result.disposition})"
    )
    before = result.selected_revision_before_write
    after = result.selected_revision_after_write
    print(
        "current selection before write: "
        f"{before if before is not None else 'none'}"
    )
    print(
        "current selection after write: "
        f"{after if after is not None else 'none'}"
    )
    print(
        "selection action: "
        f"{result.selection_action.replace('_', ' ')}"
    )


def _standards_review_to_dict(
    projection: StandardsReviewProjection,
) -> dict[str, object]:
    standard_resolution = projection.standard_resolution
    profile = projection.mapping_profile
    native_state = projection.native_state
    return {
        "class_id": projection.class_id,
        "grade_item_id": projection.grade_item_id,
        "student_id": projection.student_id,
        "standard_id": projection.standard_id,
        "item_id": projection.item_id,
        "producer_alignment": {
            "standard_ids": list(
                projection.producer_declared_standard_ids
            ),
            "declares_requested_standard": (
                projection.producer_declares_standard
            ),
        },
        "core_standard": {
            "resolved": standard_resolution.resolved,
            "active": standard_resolution.active,
        },
        "association": {
            "status": projection.association_status,
            "revision": projection.association_revision,
            "decision_sha256": projection.association_sha256,
            "disposition": projection.association_disposition,
            "basis": projection.association_basis,
            "actor_kind": projection.association_actor_kind,
            "actor_id": projection.association_actor_id,
            "rationale": projection.association_rationale,
            "operative": projection.operative_associated,
        },
        "target_scale": {
            "scale_id": projection.target_scale.scale_id,
            "scale_revision": projection.target_scale.scale_revision,
            "scale_sha256": projection.target_scale.scale_sha256,
        },
        "mapping": {
            "profile": (
                None
                if profile is None
                else {
                    "scale_id": profile.scale_id,
                    "profile_id": profile.profile_id,
                    "profile_revision": profile.profile_revision,
                    "profile_sha256": profile.profile_sha256,
                }
            ),
            "status": projection.mapping_status,
            "proficiency_level_id": (
                projection.mapped_proficiency_level_id
            ),
            "native_state": (
                None
                if native_state is None
                else {
                    "code": native_state.code,
                    "label": native_state.label,
                    "description": native_state.description,
                }
            ),
            "unsupported_reason": (
                projection.mapping_unsupported_reason
            ),
        },
        "evidence_context": {
            "result_kind": projection.result_kind,
            "target_kind": projection.target_kind,
            "subject_kind": projection.subject_kind,
            "subject_student_id": projection.subject_student_id,
        },
        "upstream": {
            "eligibility_state": projection.eligibility_state,
            "attempt_state": projection.attempt_state,
            "reassessment_state": projection.reassessment_state,
            "membership_revision": projection.membership_revision,
            "eligibility_revision": projection.eligibility_revision,
            "attempt_selection_revision": (
                projection.attempt_selection_revision
            ),
            "reassessment_revision": projection.reassessment_revision,
        },
        "aggregation": {
            "status": projection.aggregation_status,
            "exclusion_reason": projection.aggregation_exclusion_reason,
        },
        "calculation_performed": projection.calculation_performed,
    }


def _render_standards_review(
    projection: StandardsReviewProjection,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(_standards_review_to_dict(projection))
        return
    print("Standards Review")
    print(f"class: {projection.class_id}")
    print(f"Grade Item: {projection.grade_item_id}")
    print(f"student: {projection.student_id}")
    print(f"evidence item: {projection.item_id}")
    print(f"requested Standard: {projection.standard_id}")
    producer_ids = ", ".join(
        projection.producer_declared_standard_ids
    ) or "none"
    print(f"producer-declared Standards: {producer_ids}")
    print(
        "producer declares requested standard: "
        f"{'yes' if projection.producer_declares_standard else 'no'}"
    )
    resolution = projection.standard_resolution
    print(
        "Core Standard: "
        f"{'resolved' if resolution.resolved else 'unresolved'}; "
        f"active={resolution.active if resolution.active is not None else '-'}"
    )
    association = projection.association_status
    if projection.association_revision is not None:
        association += f" rev {projection.association_revision}"
    if projection.association_basis is not None:
        association += f" basis={projection.association_basis}"
    print(f"association: {association}")
    print(
        "association operative: "
        f"{'yes' if projection.operative_associated else 'no'}"
    )
    print(
        "target scale: "
        f"{projection.target_scale.scale_id}@"
        f"{projection.target_scale.scale_revision} "
        f"sha256={projection.target_scale.scale_sha256}"
    )
    if projection.mapping_profile is None:
        print("mapping profile: none supplied")
    else:
        profile = projection.mapping_profile
        print(
            "mapping profile: "
            f"{profile.scale_id}/{profile.profile_id}@"
            f"{profile.profile_revision} sha256={profile.profile_sha256}"
        )
    print(f"mapping status: {projection.mapping_status or 'not supplied'}")
    if projection.mapped_proficiency_level_id is not None:
        print(
            "mapped proficiency level: "
            f"{projection.mapped_proficiency_level_id}"
        )
    if projection.native_state is not None:
        print(f"native state: {projection.native_state.code}")
    if projection.mapping_unsupported_reason is not None:
        print(
            "mapping unsupported reason: "
            f"{projection.mapping_unsupported_reason}"
        )
    print(
        "upstream: "
        f"eligibility={projection.eligibility_state}; "
        f"attempt={projection.attempt_state}; "
        f"reassessment={projection.reassessment_state}"
    )
    aggregation = projection.aggregation_status
    if projection.aggregation_exclusion_reason is not None:
        aggregation += f" ({projection.aggregation_exclusion_reason})"
    print(f"aggregation: {aggregation}")
    print(
        "proficiency calculation performed: "
        f"{'yes' if projection.calculation_performed else 'no'}"
    )


def _exclusions_eligibility_selection_preview_to_dict(
    preview: ExclusionEligibilitySelectionPreview,
) -> dict[str, object]:
    decision = preview.target.decision
    policy = decision.policy
    return {
        "class_id": decision.class_id,
        "grade_item_id": decision.grade_item_id,
        "item_id": preview.item_id,
        "target_revision": preview.target_revision,
        "target_disposition": preview.target_disposition,
        "target_decision_sha256": preview.target_sha256,
        "expected_current_revision": preview.expected_current_revision,
        "membership_revision": preview.membership_revision,
        "authored_source_state": decision.source_state.state,
        "current_source_state": preview.source_state.state,
        "actor_kind": decision.actor.kind,
        "actor_id": decision.actor.actor_id,
        "policy_id": None if policy is None else policy.policy_id,
        "policy_version": (
            None if policy is None else policy.policy_version
        ),
        "reason_codes": list(decision.reason_codes),
        "rationale": decision.rationale,
        "authoring_action": preview.authoring_action,
    }


def _render_exclusions_eligibility_selection_preview(
    preview: ExclusionEligibilitySelectionPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "selection_confirmed": confirmation_supplied,
                "preview": (
                    _exclusions_eligibility_selection_preview_to_dict(
                        preview
                    )
                ),
            }
        )
        return
    decision = preview.target.decision
    print("Exclusions eligibility selection preview")
    print(f"item: {preview.item_id}")
    print(f"target revision: {preview.target_revision}")
    print(f"target disposition: {preview.target_disposition}")
    print(f"authored source state: {decision.source_state.state}")
    print(f"current source state: {preview.source_state.state}")
    print(f"membership revision: {preview.membership_revision}")
    current = preview.expected_current_revision
    print(
        "currently selected eligibility revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("selecting this exact persisted eligibility revision")
    else:
        print("confirmation supplied: no")
        print("NO CURRENT ELIGIBILITY SELECTION CHANGED")
        print("rerun with --confirm-select to authorize pointer mutation")
    print("NO ELIGIBILITY REVISION AUTHORED")


def _render_exclusions_eligibility_selection_result(
    preview: ExclusionEligibilitySelectionPreview,
    result: ExclusionEligibilitySelectionWorkflowResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "selected",
                "selection_confirmed": True,
                "preview": (
                    _exclusions_eligibility_selection_preview_to_dict(
                        preview
                    )
                ),
                "result": {
                    "selected_revision": result.selected_revision,
                    "selected_disposition": result.selected_disposition,
                    "selected_decision_sha256": (
                        result.selected_decision_sha256
                    ),
                    "selection_disposition": (
                        result.selection_disposition
                    ),
                    "previous_current_revision": (
                        result.previous_current_revision
                    ),
                    "authoring_action": result.authoring_action,
                },
            }
        )
        return
    print(
        "Eligibility selection committed: revision "
        f"{result.selected_revision} ({result.selection_disposition})"
    )
    previous = result.previous_current_revision
    print(
        "previous current eligibility revision: "
        f"{previous if previous is not None else 'none'}"
    )
    print(
        "eligibility authoring: "
        f"{result.authoring_action.replace('_', ' ')}"
    )


def _exclusions_eligibility_authoring_preview_to_dict(
    preview: ExclusionEligibilityAuthoringPreview,
) -> dict[str, object]:
    candidate = preview.candidate
    policy = candidate.policy
    return {
        "class_id": candidate.class_id,
        "grade_item_id": candidate.grade_item_id,
        "item_id": preview.item_id,
        "candidate_revision": preview.candidate_revision,
        "disposition": preview.candidate_disposition,
        "history": list(preview.history),
        "expected_current_eligibility_revision": (
            preview.expected_current_eligibility_revision
        ),
        "membership_revision": preview.membership_revision,
        "source_state": preview.source_state,
        "actor_kind": candidate.actor.kind,
        "actor_id": candidate.actor.actor_id,
        "policy_id": None if policy is None else policy.policy_id,
        "policy_version": (
            None if policy is None else policy.policy_version
        ),
        "reason_codes": list(candidate.reason_codes),
        "rationale": candidate.rationale,
        "decided_at": candidate.decided_at.isoformat(),
        "selection_action": preview.selection_action,
    }


def _render_exclusions_eligibility_authoring_preview(
    preview: ExclusionEligibilityAuthoringPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "write_confirmed": confirmation_supplied,
                "preview": (
                    _exclusions_eligibility_authoring_preview_to_dict(
                        preview
                    )
                ),
            }
        )
        return
    candidate = preview.candidate
    print("Exclusions eligibility authoring preview")
    print(f"item: {preview.item_id}")
    print(f"candidate revision: {preview.candidate_revision}")
    print(f"academic disposition: {preview.candidate_disposition}")
    print(f"membership revision: {preview.membership_revision}")
    print(f"source state: {preview.source_state}")
    print(f"teacher actor: {candidate.actor.actor_id}")
    if candidate.policy is not None:
        print(
            "policy: "
            f"{candidate.policy.policy_id}@"
            f"{candidate.policy.policy_version}"
        )
    print(
        "reason codes: "
        f"{', '.join(candidate.reason_codes) or 'none'}"
    )
    print(f"rationale: {candidate.rationale or 'none'}")
    current = preview.expected_current_eligibility_revision
    print(
        "currently selected eligibility revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("writing this exact immutable eligibility revision")
    else:
        print("confirmation supplied: no")
        print("NO ELIGIBILITY REVISION WRITTEN")
        print("rerun with --confirm-write to authorize immutable write")
    print("NO CURRENT SELECTION CHANGED")


def _render_exclusions_eligibility_authoring_result(
    preview: ExclusionEligibilityAuthoringPreview,
    result: ExclusionEligibilityAuthoringResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "written",
                "write_confirmed": True,
                "preview": (
                    _exclusions_eligibility_authoring_preview_to_dict(
                        preview
                    )
                ),
                "result": {
                    "written_revision": result.written_revision,
                    "written_disposition": result.written_disposition,
                    "write_disposition": (
                        result.write_result.disposition
                    ),
                    "selected_revision_before_write": (
                        result.selected_revision_before_write
                    ),
                    "selected_revision_after_write": (
                        result.selected_revision_after_write
                    ),
                    "selection_changed_during_write": (
                        result.selection_changed_during_write
                    ),
                    "selection_action": result.selection_action,
                },
            }
        )
        return
    print(
        "Eligibility revision written: "
        f"{result.written_revision} ({result.write_result.disposition})"
    )
    before = result.selected_revision_before_write
    after = result.selected_revision_after_write
    print(
        "current selection before write: "
        f"{before if before is not None else 'none'}"
    )
    print(
        "current selection after write: "
        f"{after if after is not None else 'none'}"
    )
    print(
        "selection action: "
        f"{result.selection_action.replace('_', ' ')}"
    )


def _exclusions_projection_to_dict(
    projection: ExclusionsProjection,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for row in projection.rows:
        rows.append(
            {
                "item_id": row.item_id,
                "student_id": row.student_id,
                "academic_disposition": row.selected_disposition,
                "eligibility_revision": (
                    row.selected_eligibility_revision
                ),
                "eligibility_decision_sha256": (
                    row.selected_decision_sha256
                ),
                "reviewed_membership_revision": (
                    row.reviewed_membership_revision
                ),
                "current_membership_revision": (
                    row.current_membership_revision
                ),
                "reason_codes": list(row.reason_codes),
                "rationale": row.rationale,
                "actor_kind": row.actor_kind,
                "actor_id": row.actor_id,
                "policy_id": row.policy_id,
                "policy_version": row.policy_version,
                "reviewed_source_state": row.reviewed_source_state,
                "review_state": row.review_state,
                "source_state": row.source_state,
                "operative_included": row.operative_included,
                "successor_publication_id": (
                    row.successor_publication_id
                ),
                "head_publication_id": row.head_publication_id,
            }
        )
    return {
        "class_id": projection.class_id,
        "grade_item_id": projection.grade_item_id,
        "counts": projection.counts,
        "rows": rows,
    }


def _render_exclusions_projection(
    projection: ExclusionsProjection,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(_exclusions_projection_to_dict(projection))
        return
    print("Exclusions review")
    print(f"class: {projection.class_id}")
    print(f"grade item: {projection.grade_item_id}")
    counts = projection.counts
    print(
        "counts: "
        + ", ".join(
            f"{key}={counts[key]}"
            for key in (
                "included",
                "excluded",
                "pending",
                "unsupported",
                "superseded",
                "withdrawn",
                "no_decision",
                "stale",
                "source_blocked",
                "source_unverifiable",
            )
        )
    )
    if not projection.rows:
        print("No evidence items are present in the authorized projection.")
        return
    print(
        "item | student | academic_disposition | review_state | "
        "source_state | operative | reviewed_membership | current_membership | "
        "reason_codes | rationale"
    )
    for row in projection.rows:
        disposition = row.selected_disposition or "none"
        source_state = row.source_state or "unverifiable"
        print(
            f"{row.item_id} | {row.student_id or '-'} | "
            f"{disposition} | {row.review_state} | {source_state} | "
            f"{'yes' if row.operative_included else 'no'} | "
            f"{row.reviewed_membership_revision or '-'} | "
            f"{row.current_membership_revision or '-'} | "
            f"{','.join(row.reason_codes) or '-'} | "
            f"{row.rationale or '-'}"
        )
    print(
        "Academic disposition is distinct from Core publication lifecycle."
    )
    print("NO ELIGIBILITY WRITE OR SELECTION PERFORMED")


def _attempt_decision_selection_preview_to_dict(
    preview: AttemptDecisionSelectionPreview,
) -> dict[str, object]:
    decision = preview.target.decision
    selected = decision.selected_attempts
    candidates: list[dict[str, object]] = []
    for candidate in decision.candidates:
        attempt = candidate.attempt
        candidates.append(
            {
                "native": {
                    "identifier": attempt.native.identifier,
                    "sequence": attempt.native.sequence,
                },
                "target_id": attempt.target.target_id,
                "eligible_evidence_count": len(candidate.eligible_evidence),
                "selected": attempt in selected,
            }
        )
    return {
        "class_id": decision.class_id,
        "grade_item_id": decision.grade_item_id,
        "student_id": decision.student_id,
        "target_revision": preview.target_revision,
        "target_decision_sha256": preview.target_sha256,
        "latest_revision": preview.latest_revision,
        "target_is_latest": preview.target_is_latest,
        "expected_current_decision_revision": (
            preview.expected_current_decision_revision
        ),
        "policy_id": decision.policy.policy_id,
        "policy_revision": decision.policy.policy_revision,
        "membership_revision": decision.membership_revision,
        "candidate_count": len(decision.candidates),
        "selected_count": len(decision.selected_attempts),
        "candidates": candidates,
        "history": list(preview.history),
    }


def _render_attempt_decision_selection_preview(
    preview: AttemptDecisionSelectionPreview,
    output_format: str,
    *, confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "selection_confirmed": confirmation_supplied,
                "preview": _attempt_decision_selection_preview_to_dict(
                    preview
                ),
                "authoring_action": "not_performed",
            }
        )
        return
    decision = preview.target.decision
    print("Attempt-decision selection preview")
    print(f"student: {decision.student_id}")
    print(f"target decision revision: {preview.target_revision}")
    print(f"latest persisted decision revision: {preview.latest_revision}")
    print(
        "target is latest: "
        f"{'yes' if preview.target_is_latest else 'no'}"
    )
    current = preview.expected_current_decision_revision
    print(
        "currently selected decision revision: "
        f"{current if current is not None else 'none'}"
    )
    print(
        f"policy: {decision.policy.policy_id}@{decision.policy.policy_revision}"
    )
    print(f"candidate attempts: {len(decision.candidates)}")
    print(f"selected attempts: {len(decision.selected_attempts)}")
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("selecting this exact persisted decision revision")
    else:
        print("confirmation supplied: no")
        print("NO DECISION SELECTION PERFORMED")
        print("rerun with --confirm-select to authorize pointer mutation")
    print("decision authoring remains a separate action")


def _render_attempt_decision_selection_result(
    preview: AttemptDecisionSelectionPreview,
    result: AttemptDecisionSelectionWorkflowResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "selected",
                "selection_confirmed": True,
                "preview": _attempt_decision_selection_preview_to_dict(
                    preview
                ),
                "result": {
                    "selected_revision": result.selected_revision,
                    "selected_decision_sha256": (
                        result.selected_decision_sha256
                    ),
                    "selection_disposition": (
                        result.selection_disposition
                    ),
                    "previous_current_decision_revision": (
                        result.previous_current_decision_revision
                    ),
                    "authoring_action": result.authoring_action,
                },
            }
        )
        return
    print(
        "Decision selection committed: revision "
        f"{result.selected_revision} ({result.selection_disposition})"
    )
    print(
        "previous current decision revision: "
        f"{result.previous_current_decision_revision}"
    )
    print(
        "decision authoring: "
        f"{result.authoring_action.replace('_', ' ')}"
    )


def _attempt_decision_authoring_preview_to_dict(
    preview: AttemptDecisionAuthoringPreview,
) -> dict[str, object]:
    decision = preview.candidate
    selected = decision.selected_attempts
    candidates: list[dict[str, object]] = []
    for candidate in decision.candidates:
        attempt = candidate.attempt
        candidates.append(
            {
                "native": {
                    "identifier": attempt.native.identifier,
                    "sequence": attempt.native.sequence,
                },
                "target_id": attempt.target.target_id,
                "eligible_evidence_count": len(candidate.eligible_evidence),
                "selected": attempt in selected,
            }
        )
    return {
        "class_id": decision.class_id,
        "grade_item_id": decision.grade_item_id,
        "student_id": decision.student_id,
        "policy_id": decision.policy.policy_id,
        "policy_revision": decision.policy.policy_revision,
        "policy_sha256": decision.policy.policy_revision_sha256,
        "membership_revision": decision.membership_revision,
        "membership_sha256": decision.membership_revision_sha256,
        "decision_revision": decision.decision_revision,
        "supersedes_revision": decision.supersedes_revision,
        "candidate_count": preview.candidate_count,
        "selected_count": preview.selected_count,
        "candidates": candidates,
        "actor": {
            "kind": decision.actor.kind,
            "actor_id": decision.actor.actor_id,
        },
        "rationale": decision.rationale,
        "decided_at": decision.decided_at.isoformat(),
        "history": list(preview.history),
        "reviewed_current_decision_revision": (
            preview.reviewed_current_decision_revision
        ),
    }


def _render_attempt_decision_authoring_preview(
    preview: AttemptDecisionAuthoringPreview,
    output_format: str,
    *, confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "write_confirmed": confirmation_supplied,
                "preview": _attempt_decision_authoring_preview_to_dict(
                    preview
                ),
                "selection_action": "not_performed",
            }
        )
        return
    decision = preview.candidate
    print("Attempt-decision authoring preview")
    print(f"student: {decision.student_id}")
    print(f"decision revision: {decision.decision_revision}")
    print(
        f"policy: {decision.policy.policy_id}@{decision.policy.policy_revision}"
    )
    print(f"candidate attempts: {preview.candidate_count}")
    print(f"selected attempts: {preview.selected_count}")
    if decision.candidates:
        print("sequence | identifier | target | selected")
        chosen = decision.selected_attempts
        for candidate in decision.candidates:
            attempt = candidate.attempt
            print(
                f"{attempt.native.sequence or '-'} | "
                f"{attempt.native.identifier or '-'} | "
                f"{attempt.target.target_id or '-'} | "
                f"{'yes' if attempt in chosen else 'no'}"
            )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("writing this exact immutable decision revision")
    else:
        print("confirmation supplied: no")
        print("NO DECISION WRITE PERFORMED")
        print("rerun with --confirm-write to authorize the write")
    print("current-decision selection remains a separate action")


def _render_attempt_decision_authoring_result(
    preview: AttemptDecisionAuthoringPreview,
    result: AttemptDecisionAuthoringResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "written",
                "write_confirmed": True,
                "preview": _attempt_decision_authoring_preview_to_dict(
                    preview
                ),
                "result": {
                    "written_revision": result.written_revision,
                    "write_disposition": result.write_disposition,
                    "selection_action": result.selection_action,
                },
            }
        )
        return
    print(
        "Decision write committed: revision "
        f"{result.written_revision} ({result.write_disposition})"
    )
    print(
        "current-decision selection: "
        f"{result.selection_action.replace('_', ' ')}"
    )


def _attempt_policy_selection_preview_to_dict(
    preview: AttemptPolicySelectionPreview,
) -> dict[str, object]:
    policy = preview.target.policy
    return {
        "class_id": preview.class_id,
        "grade_item_id": preview.grade_item_id,
        "work": {
            "module_id": preview.work.module_id,
            "class_id": preview.work.class_id,
            "work_id": preview.work.work_id,
        },
        "policy_id": preview.policy_id,
        "target_revision": preview.target_revision,
        "target_policy_sha256": preview.target_sha256,
        "selection_basis": policy.selection_basis,
        "minimum_selected": policy.minimum_selected,
        "maximum_selected": policy.maximum_selected,
        "actor": {
            "kind": policy.actor.kind,
            "actor_id": policy.actor.actor_id,
        },
        "history": list(preview.history),
        "latest_revision": preview.latest_revision,
        "target_is_latest": preview.target_is_latest,
        "expected_current_policy_revision": (
            preview.expected_current_policy_revision
        ),
    }


def _render_attempt_policy_selection_preview(
    preview: AttemptPolicySelectionPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "selection_confirmed": confirmation_supplied,
                "preview": _attempt_policy_selection_preview_to_dict(
                    preview
                ),
                "authoring_action": "not_performed",
            }
        )
        return
    policy = preview.target.policy
    maximum = (
        "unbounded"
        if policy.maximum_selected is None
        else str(policy.maximum_selected)
    )
    print("Attempt-selection policy selection preview")
    print(f"target policy: {preview.policy_id}@{preview.target_revision}")
    print(f"selection basis: {policy.selection_basis}")
    print(f"cardinality: {policy.minimum_selected}..{maximum}")
    print(f"latest persisted policy revision: {preview.latest_revision}")
    print(
        "target is latest: "
        f"{'yes' if preview.target_is_latest else 'no'}"
    )
    current = preview.expected_current_policy_revision
    print(
        "currently selected policy revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("selecting this exact persisted policy revision")
    else:
        print("confirmation supplied: no")
        print("NO POLICY SELECTION PERFORMED")
        print("rerun with --confirm-select to authorize pointer mutation")
    print("policy authoring remains a separate action")


def _render_attempt_policy_selection_result(
    preview: AttemptPolicySelectionPreview,
    result: AttemptPolicySelectionWorkflowResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "selected",
                "selection_confirmed": True,
                "preview": _attempt_policy_selection_preview_to_dict(
                    preview
                ),
                "result": {
                    "selected_revision": result.selected_revision,
                    "selected_policy_sha256": (
                        result.selected_policy_sha256
                    ),
                    "selection_disposition": (
                        result.selection_disposition
                    ),
                    "previous_current_policy_revision": (
                        result.previous_current_policy_revision
                    ),
                    "authoring_action": result.authoring_action,
                },
            }
        )
        return
    print(
        "Policy selection committed: revision "
        f"{result.selected_revision} ({result.selection_disposition})"
    )
    print(
        "previous current policy revision: "
        f"{result.previous_current_policy_revision}"
    )
    print(
        "policy authoring: "
        f"{result.authoring_action.replace('_', ' ')}"
    )


def _attempt_policy_authoring_preview_to_dict(
    preview: AttemptPolicyAuthoringPreview,
) -> dict[str, object]:
    policy = preview.candidate
    return {
        "operation": preview.operation,
        "class_id": policy.class_id,
        "grade_item_id": policy.grade_item_id,
        "work": {
            "module_id": policy.work.module_id,
            "class_id": policy.work.class_id,
            "work_id": policy.work.work_id,
        },
        "policy_id": policy.policy_id,
        "policy_revision": policy.policy_revision,
        "supersedes_revision": policy.supersedes_revision,
        "selection_basis": policy.selection_basis,
        "minimum_selected": policy.minimum_selected,
        "maximum_selected": policy.maximum_selected,
        "actor": {
            "kind": policy.actor.kind,
            "actor_id": policy.actor.actor_id,
        },
        "rationale": policy.rationale,
        "revised_at": policy.revised_at.isoformat(),
        "history": list(preview.history),
        "latest_persisted_policy_sha256": (
            preview.latest_persisted_policy_sha256
        ),
        "reviewed_current_policy_revision": (
            preview.reviewed_current_policy_revision
        ),
    }


def _render_attempt_policy_authoring_preview(
    preview: AttemptPolicyAuthoringPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "write_confirmed": confirmation_supplied,
                "preview": _attempt_policy_authoring_preview_to_dict(
                    preview
                ),
                "selection_action": "not_performed",
            }
        )
        return
    policy = preview.candidate
    maximum = (
        "unbounded"
        if policy.maximum_selected is None
        else str(policy.maximum_selected)
    )
    print("Attempt-selection policy authoring preview")
    print(f"operation: {preview.operation}")
    print(f"policy: {policy.policy_id}@{policy.policy_revision}")
    print(f"selection basis: {policy.selection_basis}")
    print(f"cardinality: {policy.minimum_selected}..{maximum}")
    print(f"actor: {policy.actor.kind}/{policy.actor.actor_id}")
    current = preview.reviewed_current_policy_revision
    print(
        "currently selected policy revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("writing this exact immutable policy revision")
    else:
        print("confirmation supplied: no")
        print("NO POLICY WRITE PERFORMED")
        print("rerun with --confirm-write to authorize the write")
    print("current-policy selection remains a separate action")


def _render_attempt_policy_authoring_result(
    preview: AttemptPolicyAuthoringPreview,
    result: AttemptPolicyAuthoringResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "written",
                "write_confirmed": True,
                "preview": _attempt_policy_authoring_preview_to_dict(
                    preview
                ),
                "result": {
                    "written_revision": result.written_revision,
                    "write_disposition": result.write_disposition,
                    "selection_action": result.selection_action,
                },
            }
        )
        return
    print(
        "Policy write committed: revision "
        f"{result.written_revision} ({result.write_disposition})"
    )
    print(
        "current-policy selection: "
        f"{result.selection_action.replace('_', ' ')}"
    )


def _attempt_decisions_review_to_dict(
    review: AttemptDecisionWorkflowProjection,
) -> dict[str, object]:
    policy: dict[str, object] | None = None
    if review.current_policy_id is not None:
        policy = {
            "policy_id": review.current_policy_id,
            "policy_revision": review.current_policy_revision,
            "policy_sha256": review.current_policy_sha256,
            "minimum_selected": review.minimum_selected,
            "maximum_selected": review.maximum_selected,
        }
    candidates: list[dict[str, object]] = []
    for row in review.candidates:
        candidates.append(
            {
                "target": {
                    "target_kind": row.attempt.target.target_kind,
                    "target_id": row.attempt.target.target_id,
                    "owning_system": row.attempt.target.owning_system,
                    "contract_version": row.attempt.target.contract_version,
                },
                "native": {
                    "identifier": row.native_identifier,
                    "sequence": row.native_sequence,
                },
                "eligible_evidence_count": row.eligible_evidence_count,
                "selected_in_reviewed_decision": (
                    row.selected_in_reviewed_decision
                ),
            }
        )
    source = review.source_snapshot
    return {
        "status": review.status,
        "resolution_status": review.resolution_status,
        "stale_reason": review.stale_reason,
        "class_id": review.class_id,
        "grade_item_id": review.grade_item_id,
        "work": {
            "module_id": review.work.module_id,
            "class_id": review.work.class_id,
            "work_id": review.work.work_id,
        },
        "student_id": review.student_id,
        "source_snapshot": {
            "publication_id": source.publication_id,
            "cache_key": source.cache_key,
            "snapshot_digest": source.snapshot_digest,
        },
        "candidate_count": review.candidate_count,
        "reviewed_selected_count": review.reviewed_selected_count,
        "selected_decision_revision": review.selected_decision_revision,
        "selected_decision_sha256": review.selected_decision_sha256,
        "operative_selection": review.operative_selection,
        "policy": policy,
        "candidates": candidates,
        "read_only": True,
    }


def _render_attempt_decisions_review(
    review: AttemptDecisionWorkflowProjection,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(_attempt_decisions_review_to_dict(review))
        return
    print("Attempt Decisions review")
    print(f"Grade Item: {review.grade_item_id}")
    print(f"student: {review.student_id}")
    print(
        "work: "
        f"{review.work.module_id}/{review.work.class_id}/{review.work.work_id}"
    )
    print(f"status: {review.status}")
    print(f"resolution status: {review.resolution_status}")
    if review.stale_reason is not None:
        print(f"stale reason: {review.stale_reason}")
    print(
        "operative selection: "
        f"{'yes' if review.operative_selection else 'no'}"
    )
    print(f"candidate count: {review.candidate_count}")
    print(f"reviewed selected count: {review.reviewed_selected_count}")
    if review.selected_decision_revision is not None:
        print(
            "selected decision revision: "
            f"{review.selected_decision_revision}"
        )
    if review.current_policy_id is not None:
        maximum = (
            "unbounded"
            if review.maximum_selected is None
            else str(review.maximum_selected)
        )
        print(
            "current policy: "
            f"{review.current_policy_id}@{review.current_policy_revision} "
            f"cardinality={review.minimum_selected}..{maximum}"
        )
    if review.candidates:
        print(
            "native_sequence | target | eligible_sources | reviewed_selected"
        )
        for row in review.candidates:
            native = (
                str(row.native_sequence)
                if row.native_sequence is not None
                else row.native_identifier or "opaque"
            )
            target = row.target_id or "none"
            selected = "yes" if row.selected_in_reviewed_decision else "no"
            print(
                f"{native} | {target} | {row.eligible_evidence_count} | "
                f"{selected}"
            )
    else:
        print("No current attempt candidates are available.")
    print("read-only; no attempt-selection state was written")


def _grade_item_membership_selection_preview_to_dict(
    preview: GradeItemMembershipSelectionPreview,
) -> dict[str, object]:
    decision = preview.target.decision
    assignment = decision.academic_period
    academic_period: dict[str, object] | None = None
    if assignment is not None:
        academic_period = {
            "school_year": assignment.period.school_year,
            "period_id": assignment.period.period_id,
            "calendar_revision": assignment.calendar_revision,
        }
    return {
        "class_id": preview.class_id,
        "grade_item_id": preview.grade_item_id,
        "work": {
            "module_id": preview.work.module_id,
            "class_id": preview.work.class_id,
            "work_id": preview.work.work_id,
        },
        "target_revision": preview.target_revision,
        "target_decision_sha256": preview.target.decision_sha256,
        "target_decision": preview.target_decision,
        "target_grade_item_revision": (
            preview.target_grade_item_revision
        ),
        "target_grade_item_revision_sha256": (
            decision.grade_item_revision_sha256
        ),
        "target_registration_revision": (
            preview.target_registration_revision
        ),
        "academic_period": academic_period,
        "history": list(preview.history),
        "latest_revision": preview.latest_revision,
        "target_is_latest": preview.target_is_latest,
        "expected_current_membership_revision": (
            preview.expected_current_membership_revision
        ),
    }


def _render_grade_item_membership_selection_preview(
    preview: GradeItemMembershipSelectionPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "selection_confirmed": confirmation_supplied,
                "preview": (
                    _grade_item_membership_selection_preview_to_dict(
                        preview
                    )
                ),
                "authoring_action": "not_performed",
            }
        )
        return
    decision = preview.target.decision
    print("Grade Item membership current-selection preview")
    print(f"Grade Item: {preview.grade_item_id}")
    print(f"work: {preview.work.module_id}/{preview.work.work_id}")
    print(f"target membership revision: {preview.target_revision}")
    print(f"target decision: {preview.target_decision}")
    print(
        "target decision digest: "
        f"{preview.target.decision_sha256}"
    )
    print(
        "target Grade Item revision: "
        f"{preview.target_grade_item_revision}"
    )
    print(
        "target registration revision: "
        f"{preview.target_registration_revision}"
    )
    assignment = decision.academic_period
    if assignment is None:
        print("target academic period: none")
    else:
        print(
            "target academic period: "
            f"{assignment.period.school_year}/"
            f"{assignment.period.period_id} @ calendar revision "
            f"{assignment.calendar_revision}"
        )
    print(f"latest persisted membership revision: {preview.latest_revision}")
    print(
        "target is latest: "
        f"{'yes' if preview.target_is_latest else 'no'}"
    )
    current = preview.expected_current_membership_revision
    print(
        "currently selected membership revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("selecting this exact revision after live CAS revalidation")
    else:
        print("confirmation supplied: no")
        print(
            "NO MEMBERSHIP SELECTION PERFORMED; immutable history is "
            "unchanged"
        )
        print("rerun with --confirm-select to authorize fresh selection")


def _render_grade_item_membership_selection_result(
    preview: GradeItemMembershipSelectionPreview,
    result: GradeItemMembershipSelectionWorkflowResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "selected",
                "selection_confirmed": True,
                "preview": (
                    _grade_item_membership_selection_preview_to_dict(
                        preview
                    )
                ),
                "result": {
                    "selection_disposition": (
                        result.selection_disposition
                    ),
                    "previous_current_membership_revision": (
                        result.previous_current_membership_revision
                    ),
                    "selected_revision": result.selected_revision,
                    "selected_decision": result.selected_decision,
                    "authoring_action": result.authoring_action,
                },
            }
        )
        return
    print(
        "Membership selection committed: revision "
        f"{result.selected_revision} ({result.selection_disposition})"
    )
    previous = result.previous_current_membership_revision
    print(
        "previous current membership revision: "
        f"{previous if previous is not None else 'none'}"
    )
    print(f"selected decision: {result.selected_decision}")
    print(
        "membership authoring action: "
        f"{result.authoring_action.replace('_', ' ')}"
    )


def _grade_item_membership_assignment_to_dict(
    assignment: GradeItemAcademicPeriodAssignment | None,
) -> dict[str, object] | None:
    if assignment is None:
        return None
    return {
        "school_year": assignment.period.school_year,
        "period_id": assignment.period.period_id,
        "calendar_revision": assignment.calendar_revision,
    }


def _grade_item_membership_authoring_preview_to_dict(
    preview: GradeItemMembershipAuthoringPreview,
) -> dict[str, object]:
    candidate = preview.candidate
    work = candidate.work_reference.work
    return {
        "operation": preview.operation,
        "class_id": candidate.class_id,
        "grade_item_id": candidate.grade_item_id,
        "grade_item_revision": candidate.grade_item_revision,
        "grade_item_revision_sha256": (
            candidate.grade_item_revision_sha256
        ),
        "work": {
            "module_id": work.module_id,
            "class_id": work.class_id,
            "work_id": work.work_id,
        },
        "registration_revision": (
            candidate.work_reference.registration_revision
        ),
        "membership_revision": candidate.membership_revision,
        "supersedes_revision": candidate.supersedes_revision,
        "decision": candidate.decision,
        "academic_period": _grade_item_membership_assignment_to_dict(
            candidate.academic_period
        ),
        "actor_id": candidate.actor_id,
        "rationale": candidate.rationale,
        "decided_at": candidate.decided_at.isoformat(),
        "history": list(preview.history),
        "latest_persisted_decision_sha256": (
            preview.latest_persisted_decision_sha256
        ),
        "expected_current_grade_item_revision": (
            preview.expected_current_grade_item_revision
        ),
        "expected_current_membership_revision": (
            preview.expected_current_membership_revision
        ),
    }


def _render_grade_item_membership_authoring_preview(
    preview: GradeItemMembershipAuthoringPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "write_confirmed": confirmation_supplied,
                "preview": (
                    _grade_item_membership_authoring_preview_to_dict(
                        preview
                    )
                ),
                "selection_action": "not_performed",
            }
        )
        return
    candidate = preview.candidate
    work = candidate.work_reference.work
    print("Grade Item membership authoring preview")
    print(f"operation: {preview.operation}")
    print(f"Grade Item: {candidate.grade_item_id}")
    print(f"Grade Item revision: {candidate.grade_item_revision}")
    print(
        "Grade Item revision digest: "
        f"{candidate.grade_item_revision_sha256}"
    )
    print(f"work: {work.module_id}/{work.work_id}")
    print(
        "registration revision: "
        f"{candidate.work_reference.registration_revision}"
    )
    print(f"membership revision: {candidate.membership_revision}")
    print(f"decision: {candidate.decision}")
    assignment = candidate.academic_period
    if assignment is None:
        print("academic period: none")
    else:
        print(
            "academic period: "
            f"{assignment.period.school_year}/"
            f"{assignment.period.period_id} @ calendar revision "
            f"{assignment.calendar_revision}"
        )
    print(f"actor: {candidate.actor_id}")
    print(f"rationale: {candidate.rationale or 'none'}")
    current = preview.expected_current_membership_revision
    print(
        "currently selected membership revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("writing this exact revision after live revalidation")
    else:
        print("confirmation supplied: no")
        print(
            "NO MEMBERSHIP WRITE PERFORMED; current membership selection "
            "is unchanged"
        )
        print("rerun with --confirm-write to authorize a fresh write")


def _render_grade_item_membership_authoring_result(
    preview: GradeItemMembershipAuthoringPreview,
    result: GradeItemMembershipAuthoringResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "written",
                "write_confirmed": True,
                "preview": (
                    _grade_item_membership_authoring_preview_to_dict(
                        preview
                    )
                ),
                "result": {
                    "write_disposition": result.write_disposition,
                    "written_revision": result.written_revision,
                    "written_decision": result.written_decision,
                    "previous_current_membership_revision": (
                        result.previous_current_membership_revision
                    ),
                    "selection_action": result.selection_action,
                },
            }
        )
        return
    print(
        f"Membership revision {result.written_revision} written "
        f"({result.write_disposition})"
    )
    previous = result.previous_current_membership_revision
    print(
        "previous current membership revision: "
        f"{previous if previous is not None else 'none'}"
    )
    print(
        "membership selection action: "
        f"{result.selection_action.replace('_', ' ')}"
    )


def _grade_item_selection_preview_to_dict(
    preview: GradeItemSelectionPreview,
) -> dict[str, object]:
    return {
        "class_id": preview.class_id,
        "grade_item_id": preview.grade_item_id,
        "target_revision": preview.target_revision,
        "target_revision_sha256": preview.target.revision_sha256,
        "target_status": preview.target_status,
        "history": list(preview.history),
        "latest_revision": preview.latest_revision,
        "target_is_latest": preview.target_is_latest,
        "expected_current_revision": preview.expected_current_revision,
    }


def _render_grade_item_selection_preview(
    preview: GradeItemSelectionPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "selection_confirmed": confirmation_supplied,
                "preview": _grade_item_selection_preview_to_dict(preview),
                "authoring_action": "not_performed",
            }
        )
        return
    print("Grade Item current-selection preview")
    print(f"Grade Item: {preview.grade_item_id}")
    print(f"target revision: {preview.target_revision}")
    print(f"target status: {preview.target_status}")
    print(f"target revision digest: {preview.target.revision_sha256}")
    print(f"latest persisted revision: {preview.latest_revision}")
    print(
        "target is latest: "
        f"{'yes' if preview.target_is_latest else 'no'}"
    )
    current = preview.expected_current_revision
    print(
        "currently selected revision: "
        f"{current if current is not None else 'none'}"
    )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("selecting this exact revision after live CAS revalidation")
    else:
        print("confirmation supplied: no")
        print("NO SELECTION PERFORMED; Grade Item history is unchanged")
        print("rerun with --confirm-select to authorize a fresh selection")


def _render_grade_item_selection_result(
    preview: GradeItemSelectionPreview,
    result: GradeItemSelectionWorkflowResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "selected",
                "selection_confirmed": True,
                "preview": _grade_item_selection_preview_to_dict(preview),
                "result": {
                    "selection_disposition": result.selection_disposition,
                    "previous_current_revision": (
                        result.previous_current_revision
                    ),
                    "selected_revision": result.selected_revision,
                    "selected_status": result.selected_status,
                    "authoring_action": "not_performed",
                },
            }
        )
        return
    print(
        "Selection committed: Grade Item revision "
        f"{result.selected_revision} ({result.selection_disposition})"
    )
    previous = result.previous_current_revision
    print(
        "previous current revision: "
        f"{previous if previous is not None else 'none'}"
    )
    print(f"selected status: {result.selected_status}")
    print("authoring action: not performed")


def _grade_item_authoring_preview_to_dict(
    preview: GradeItemAuthoringPreview,
) -> dict[str, object]:
    return {
        "actor_id": preview.actor_id,
        "operation": preview.operation,
        "history_before": list(preview.history_before),
        "latest_revision_sha256_before": (
            preview.latest_revision_sha256_before
        ),
        "candidate_sha256": preview.candidate_sha256,
        "candidate": grade_item_revision_to_dict(preview.candidate),
    }


def _render_grade_item_authoring_preview(
    preview: GradeItemAuthoringPreview,
    output_format: str,
    *,
    confirmation_supplied: bool,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "preview",
                "write_confirmed": confirmation_supplied,
                "preview": _grade_item_authoring_preview_to_dict(preview),
                "selection_action": "not_performed",
            }
        )
        return
    candidate = preview.candidate
    print("Grade Item revision preview")
    print(f"Grade Item: {candidate.grade_item_id}")
    print(f"operation: {preview.operation}")
    print(f"candidate revision: {candidate.grade_item_revision}")
    print(f"status: {candidate.status}")
    print(f"title: {candidate.title}")
    print(f"purpose: {candidate.purpose}")
    print(f"teacher actor context: {preview.actor_id}")
    if candidate.weighting is not None:
        category = candidate.weighting.category_id or "none"
        relative = (
            str(candidate.weighting.relative_weight)
            if candidate.weighting.relative_weight is not None
            else "none"
        )
        print(
            "weighting metadata only: "
            f"category={category} | relative_weight={relative}"
        )
    if confirmation_supplied:
        print("confirmation supplied: yes")
        print("committing this exact preview after live revalidation")
    else:
        print("confirmation supplied: no")
        print("NO WRITE PERFORMED; current selection is unchanged")
        print("rerun with --confirm-write to authorize a fresh commit")


def _render_grade_item_authoring_result(
    preview: GradeItemAuthoringPreview,
    result: GradeItemAuthoringResult,
    output_format: str,
) -> None:
    if output_format == "json":
        _print_json(
            {
                "mode": "written",
                "write_confirmed": True,
                "preview": _grade_item_authoring_preview_to_dict(preview),
                "result": {
                    "write_disposition": result.write_disposition,
                    "written_revision": (
                        result.preview.candidate.grade_item_revision
                    ),
                    "stored_revision_sha256": (
                        result.stored_revision_sha256
                    ),
                    "selected_revision_after": (
                        result.selected_revision_after
                    ),
                    "selection_action": "not_performed",
                },
            }
        )
        return
    revision = result.preview.candidate.grade_item_revision
    print(
        f"Write committed: Grade Item revision {revision} "
        f"({result.write_disposition})"
    )
    selected = result.selected_revision_after
    print(
        "selected Grade Item revision remains: "
        f"{selected if selected is not None else 'none'}"
    )
    print("selection action: not performed")


def _render_grade_items_review(
    review: GradeItemsReview, output_format: str
) -> None:
    if output_format == "json":
        _print_json(grade_items_review_to_dict(review))
        return
    print(
        f"Grade Items review: {review.class_id} | "
        f"active={review.active_count} | archived={review.archived_count} | "
        f"unselected={review.unselected_count}"
    )
    if not review.items:
        print("No canonical Grade Items exist for this class.")
        print("No Grade Item was inferred from publications or dates.")
        return
    for row in review.items:
        selected = (
            str(row.selected_revision)
            if row.selected_revision is not None
            else "none"
        )
        title = row.title or "(no selected revision)"
        status = row.status or "unselected"
        purpose = row.purpose or "none"
        print(
            f"{row.grade_item_id} | {row.selection_state} | "
            f"selected={selected} | latest={row.latest_persisted_revision} | "
            f"{status} | {title} | purpose={purpose}"
        )
        if row.weighting is not None:
            category = row.weighting.category_id or "none"
            relative = row.weighting.relative_weight or "none"
            print(
                "  weighting metadata only: "
                f"category={category} | relative_weight={relative}"
            )
        for membership in row.memberships:
            membership_selected = (
                str(membership.selected_revision)
                if membership.selected_revision is not None
                else "none"
            )
            decision = membership.decision or "none"
            registration = (
                str(membership.registration_revision)
                if membership.registration_revision is not None
                else "none"
            )
            if membership.academic_period_id is None:
                period = "none"
            else:
                period = (
                    f"{membership.academic_period_school_year}/"
                    f"{membership.academic_period_id}"
                    f"@calendar-{membership.academic_period_calendar_revision}"
                )
            print(
                f"  {membership.work.module_id}/{membership.work.work_id} | "
                f"{membership.selection_state} | "
                f"selected={membership_selected} | "
                f"latest={membership.latest_persisted_revision} | "
                f"decision={decision} | "
                f"grade_item_basis={membership.grade_item_basis_state} | "
                f"registration={registration} | period={period}"
            )
    print("read-only review; no Grade Item or membership state changed")


def _render_new_evidence_review(
    review: NewEvidenceReview, output_format: str
) -> None:
    if output_format == "json":
        _print_json(new_evidence_review_to_dict(review))
        return
    print(f"New Evidence review | Grade Item: {review.grade_item_id}")
    print(
        "work: "
        f"{review.work.module_id}/{review.work.class_id}/{review.work.work_id}"
    )
    print(f"publication: {review.publication_id}")
    print(f"projection source: {review.projection_source_status}")
    membership: str = review.membership_state
    if review.membership_revision is not None:
        membership += f"@{review.membership_revision}"
    print(f"membership: {membership}")
    if review.academic_period_id is not None:
        print(
            "academic period: "
            f"{review.academic_period_id}@calendar-"
            f"{review.academic_period_calendar_revision}"
        )
    print(f"attention: {review.attention_count}/{len(review.rows)} evidence rows")
    if review.status_summary:
        print("status summary:")
        for item in review.status_summary:
            print(f"  {item.status}: {item.count}")
    if not review.rows:
        print("No evidence rows are present in this authorized projection.")
    else:
        print(
            "item | student | target | result_kind | membership | eligibility | "
            "source_state | attention | next"
        )
        for row in review.rows:
            student = row.student_id or "none"
            target = f"{row.target_kind}/{row.target_id or 'none'}"
            eligibility = row.eligibility_status or "not_evaluated"
            source_state = row.eligibility_source_state or "not_evaluated"
            attention = "yes" if row.attention_required else "no"
            next_task = row.recommended_task or "none"
            print(
                f"{row.source.item_id} | {student} | {target} | "
                f"{row.result_kind} | {row.membership_state} | {eligibility} | "
                f"{source_state} | {attention} | {next_task}"
            )
    print("read-only; no Meridian or Core state was written")


def _render_teacher_workflow_catalog(
    catalog: TeacherWorkflowCatalog, output_format: str
) -> None:
    if output_format == "json":
        _print_json(teacher_workflow_catalog_to_dict(catalog))
        return
    print("Issue #41 teacher workflows:")
    for index, task in enumerate(catalog.tasks, start=1):
        print(f"{index}. {task.task_id} | {task.title}")
        print(f"   {task.summary}")
        print(f"   write boundary: {task.write_boundary}")
    print("catalog only; this command performs no workflow write")


def _render_publication_list(
    result: PublicationListDiagnostic, output_format: str
) -> None:
    if output_format == "json":
        _print_json(publication_list_to_dict(result))
        return
    if not result.observations:
        print("No publication candidates matched the bounded catalog query.")
        return
    print(
        "publication | producer | class | work | kind | record_set/revision | "
        "canonical_state | contract_support | adapter | reader"
    )
    for observation in result.observations:
        row = observation.candidate.catalog_publication
        if observation.canonical_context is None:
            print(
                f"{observation.publication_id} | {row.work.module_id} | "
                f"{row.work.class_id} | {row.work.work_id} | {row.publication_kind} | "
                f"{row.record_set_id}/{row.record_set_revision} | unavailable | "
                f"{observation.canonical_error_code} | not_evaluated | not_evaluated"
            )
            continue
        context = observation.canonical_context
        support = observation.support
        if support is None:  # defensive: model validation forbids this
            raise RuntimeError("support diagnostic unexpectedly missing")
        canonical_state_text: str = context.canonical_state
        if observation.drift_fields:
            canonical_state_text += "+candidate_drift"
        print(
            f"{context.publication.publication_id} | "
            f"{context.publication.work.module_id} | "
            f"{context.publication.work.class_id} | "
            f"{context.publication.work.work_id} | "
            f"{context.publication.publication_kind} | "
            f"{context.publication.record_set_id}/"
            f"{context.publication.record_set_revision} | "
            f"{canonical_state_text} | {support.compatibility_state} | "
            f"{support.adapter_state} | {support.reader_state}"
        )


def _compact_value(item: EvidenceItem) -> str:
    value = item.value
    if isinstance(value, NativeScalarValue):
        return f"scalar:{value.value!r}"
    if isinstance(value, NativePointValue):
        return f"points:{value.earned!r}/{value.possible!r}"
    if isinstance(value, NativeScaledValue):
        return f"scaled:{value.value!r}@{value.scale.scale_id}"
    if isinstance(value, NativeStateValue):
        return f"state:{value.code}"
    return "unknown"


def _render_evidence_inspection(
    result: EvidenceInspectionDiagnostic, output_format: str
) -> None:
    if output_format == "json":
        _print_json(evidence_inspection_to_dict(result))
        return
    assessment = result.authorized.assessment
    print(
        f"source: {assessment.source_status}; reuse: {assessment.reuse_status}; "
        f"reasons: {', '.join(assessment.reason_codes) or 'none'}"
    )
    if not result.items:
        print("No evidence items matched the exact filters.")
        return
    print(
        "item | student | target | standards | result_kind | typed_value | "
        "eligibility"
    )
    for item in result.items:
        subject_id = (
            item.subject.student_id if item.subject is not None else "none"
        )
        target_id = item.target.target_id or "none"
        target_text = f"{item.target.target_kind}/{target_id}"
        if item.target.owning_system is not None:
            target_text = f"{item.target.owning_system}:{target_text}"
        if item.target.contract_version is not None:
            target_text += f"@{item.target.contract_version}"
        standards = ",".join(item.target.standard_ids) or "none"
        print(
            f"{item.item_id} | {subject_id} | "
            f"{target_text} | {standards} | "
            f"{item.result_kind} | {_compact_value(item)} | "
            f"{item.eligibility.status}"
        )


def _render_evidence_explanation(
    result: EvidenceExplanationDiagnostic, output_format: str
) -> None:
    if output_format == "json":
        _print_json(evidence_explanation_to_dict(result))
        return
    assessment = result.authorized.assessment
    print(f"source status: {assessment.source_status}")
    print(f"reuse status: {assessment.reuse_status}")
    print(f"reason codes: {', '.join(assessment.reason_codes) or 'none'}")
    print(f"observed canonical state: {assessment.observed_canonical_state}")
    current_state = assessment.current_canonical_state or "unavailable"
    print(f"current canonical state: {current_state}")
    print(f"observed series head: {assessment.observed_head_publication_id}")
    current_head = assessment.current_head_publication_id or "unavailable"
    print(f"current series head: {current_head}")
    observed_revision = assessment.observed_current_registration_revision
    current_revision = assessment.current_registration_revision
    print(
        "observed current registration revision: "
        + (str(observed_revision) if observed_revision is not None else "none")
    )
    print(
        "current registration revision: "
        + (str(current_revision) if current_revision is not None else "none")
    )
    items = result.authorized.stored.snapshot.inventory.items
    if not items:
        print("evidence eligibility: no persisted items")
        return
    print("evidence eligibility:")
    for item in items:
        eligibility = item.eligibility
        if eligibility.status == "unevaluated":
            detail = "no Meridian evidence-eligibility policy has evaluated this item"
        elif eligibility.status == "eligible":
            detail = f"policy={eligibility.policy_id}@{eligibility.policy_version}"
        else:
            reasons = ",".join(eligibility.reason_codes)
            detail = (
                f"policy={eligibility.policy_id}@{eligibility.policy_version}; "
                f"reasons={reasons}"
            )
        print(f"  {item.item_id}: {eligibility.status}; {detail}")


def _render_publication_verification(
    result: PublicationVerificationDiagnostic, output_format: str
) -> None:
    if output_format == "json":
        _print_json(publication_verification_to_dict(result))
        return
    context = result.context
    publication = context.publication
    support = result.support
    source = publication.source_record
    source_text = (
        "absent"
        if source is None
        else (
            f"{source.module_id}/{source.record_kind}/{source.record_id}"
            f"@{source.contract_version or 'unversioned'}"
        )
    )
    referenced = context.referenced_registration
    current = context.current_registration
    print(f"publication: {publication.publication_id}")
    print(
        "work: "
        f"{publication.work.module_id}/{publication.work.class_id}/"
        f"{publication.work.work_id}"
    )
    print(f"source record: {source_text}")
    print(f"publication kind: {publication.publication_kind}")
    print(f"capabilities: {', '.join(publication.capabilities) or 'none'}")
    print(f"record set: {publication.record_set_id}/{publication.record_set_revision}")
    print(f"manifest contract: {publication.manifest_contract_version}")
    print("manifest access: not requested")
    print("manifest bytes: not checked")
    print(
        "referenced registration revision: "
        + (str(referenced.registration_revision) if referenced is not None else "none")
    )
    print(
        "current registration revision: "
        + (str(current.registration_revision) if current is not None else "none")
    )
    print(f"canonical state: {context.canonical_state}")
    print(f"series head: {context.series.head_publication_id}")
    print(f"successor: {context.series.successor_publication_id or 'none'}")
    print(f"withdrawn: {'yes' if context.withdrawal is not None else 'no'}")
    print(f"producer profile: {support.profile_state}")
    print(f"contract compatibility: {support.compatibility_state}")
    if support.compatibility_codes:
        print(f"compatibility codes: {', '.join(support.compatibility_codes)}")
    print(f"adapter: {support.adapter_state}")
    if support.adapter_id is not None:
        print(f"adapter id: {support.adapter_id}")
    print(f"reader: {support.reader_state}")
    if support.reader_distribution is not None:
        print(f"reader distribution: {support.reader_distribution}")
    if support.installed_reader_version is not None:
        print(f"installed reader version: {support.installed_reader_version}")
    if support.supported_reader_versions:
        versions = ", ".join(support.supported_reader_versions)
        print(f"supported reader versions: {versions}")
    print(f"support status: {support.overall_state}")
    if support.reason_codes:
        print(f"reason codes: {', '.join(support.reason_codes)}")


def main(
    argv: Sequence[str] | None = None,
    *,
    dependencies: DiagnosticsDependencies | None = None,
) -> int:
    """Parse CLI arguments and return a stable process exit status."""
    effective_argv = tuple(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not effective_argv:
        parser.print_help()
        return 0
    args = parser.parse_args(effective_argv)
    group_help = getattr(args, "show_group_help", None)
    if group_help is not None:
        cast(argparse.ArgumentParser, group_help).print_help()
        return 0
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    try:
        return int(handler(args, dependencies))
    except PlanningSignalPreviewWriteScopeError as error:
        print(f"error: {error.code}: {error}", file=sys.stderr)
        return 1
    except (
        PublicationIngestionError,
        DiagnosticsError,
        ProjectionCacheError,
        NewEvidenceEligibilityAuthoringError,
        NewEvidenceEligibilitySelectionError,
        NewEvidenceWorkflowError,
        EvidenceEligibilityStorageError,
        AttemptDecisionAuthoringWorkflowError,
        AttemptDecisionSelectionWorkflowError,
        ExclusionsWorkflowError,
        ExclusionEligibilityAuthoringError,
        ExclusionEligibilitySelectionError,
        StandardsReviewWorkflowError,
        StandardsAssociationAuthoringError,
        StandardsAssociationSelectionError,
        CalculationPreviewAssemblyError,
        CalculationPreviewWorkflowError,
        CalculationResultPersistenceError,
        CalculationResultSelectionError,
        AcademicPeriodCalculationAssemblyError,
        AcademicPeriodCalculationPreviewWorkflowError,
        AcademicPeriodResultPersistenceError,
        AcademicPeriodResultSelectionError,
        PlanningSignalWorkflowError,
        PlanningSignalDerivationPersistenceError,
        PlanningSignalPreviewWriteError,
        AttemptDecisionWorkflowError,
        AttemptPolicyAuthoringWorkflowError,
        AttemptPolicySelectionWorkflowError,
        AttemptSelectionStorageError,
        GradeItemAuthoringWorkflowError,
        GradeItemMembershipStorageError,
        GradeItemMembershipAuthoringError,
        GradeItemMembershipSelectionWorkflowError,
        GradeItemSelectionWorkflowError,
        GradeItemStorageError,
        GradeItemsWorkflowError,
    ) as error:
        print(f"error: {error.code}", file=sys.stderr)
        return 1
    except (ValueError, TypeError) as error:
        parser.error(str(error))
        return 2  # pragma: no cover - argparse exits
