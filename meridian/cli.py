"""Read-only command-line diagnostics for the Meridian foundation."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pds_core.academic_catalog import PublicationCatalogQuery
from pds_core.publication_records import PUBLICATION_CAPABILITIES

from meridian import __version__
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
from meridian.ingestion import PublicationDiscoveryRequest, PublicationIngestionError
from meridian.projection_cache import ProjectionCacheError


def _datetime_argument(value: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an ISO 8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _positive_integer(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a positive integer") from error
    if result <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return result


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
            "Meridian is the Paper Data Suite publication-ingestion, grading-policy, "
            "and reporting module. Read-only publication diagnostics are available. "
            "Proficiency, Grades, and reporting policy stages are not implemented yet."
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
    except (PublicationIngestionError, DiagnosticsError, ProjectionCacheError) as error:
        print(f"error: {error.code}", file=sys.stderr)
        return 1
    except (ValueError, TypeError) as error:
        parser.error(str(error))
        return 2  # pragma: no cover - argparse exits
