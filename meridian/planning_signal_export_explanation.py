"""Read-only explanation for one exact Meridian-generated Core grouping signal.

The projection starts from an explicit ``class_id`` / ``signal_set_id`` target,
verifies the Core signal and Meridian #40 export receipt, walks the exact
receipt-bound #39/#38 provenance, and reconciles every exported or omitted
student band against the deterministic #38 -> Core projection.

Historical export explanation never substitutes a currently selected review or
a newer derivation.  No state is written, selected, regenerated, or exported.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pds_core.grouping_signal_storage import (
    GroupingSignalNotFoundError,
    GroupingSignalStorageError,
    StoredGroupingSignal,
    load_grouping_signal,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.academic_period_proficiency import (
    AcademicPeriodProficiencyResultReference,
    academic_period_proficiency_result_reference_to_dict,
)
from meridian.grade_item_proficiency_explanation import (
    ExplanationTraceIntegrityError,
    ExplanationTraceNotFoundError,
    ExplanationTraceTargetError,
)
from meridian.grouping_signal_derivation_storage import (
    GroupingSignalDerivationStorageError,
    StoredGroupingSignalDerivation,
    load_grouping_signal_derivation_reference,
)
from meridian.grouping_signal_export import (
    GroupingSignalExportProjectionError,
    build_grouping_signal_export_candidate,
)
from meridian.grouping_signal_export_receipt import (
    GROUPING_SIGNAL_EXPORT_RECEIPT_DIGEST_ALGORITHM,
)
from meridian.grouping_signal_export_storage import (
    GroupingSignalExportReceiptStorageError,
    GroupingSignalExportReceiptStorageNotFoundError,
    StoredGroupingSignalExportReceipt,
    load_grouping_signal_export_receipt,
)
from meridian.grouping_signal_policy_storage import (
    GroupingSignalPolicyStorageError,
    load_grouping_signal_policy_revision,
)
from meridian.grouping_signal_preview import (
    GroupingSignalPreviewValidationError,
    build_grouping_signal_preview_snapshot,
)
from meridian.grouping_signal_preview_storage import (
    GroupingSignalPreviewStorageError,
    StoredGroupingSignalPreview,
    load_grouping_signal_preview_reference,
)
from meridian.grouping_signal_review import (
    GroupingSignalReviewValidationError,
    validate_grouping_signal_review_against_preview,
)
from meridian.grouping_signal_review_storage import (
    GroupingSignalReviewStorageError,
    StoredGroupingSignalReview,
    load_grouping_signal_review_revision,
)
from meridian.planning_signal_derivation_explanation import (
    PlanningSignalBandDefinitionExplanation,
    PlanningSignalDerivationExplanation,
    PlanningSignalDerivationTraceTarget,
    PlanningSignalStudentDerivationExplanation,
    explain_planning_signal_derivation,
    planning_signal_derivation_explanation_to_dict,
    render_planning_signal_derivation_explanation_text,
)
from meridian.proficiency_mapping_storage import (
    ProficiencyMappingStorageError,
    load_proficiency_scale_revision,
)


@dataclass(frozen=True, slots=True)
class PlanningSignalExportTraceTarget:
    """One exact Core grouping-signal identity; there is no latest target."""

    class_id: str
    signal_set_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "signal_set_id",
            _identifier(self.signal_set_id, "signal_set_id"),
        )


@dataclass(frozen=True, slots=True)
class PlanningSignalExportStudentExplanation:
    """Exact Core export disposition for one #38 roster student."""

    student_id: str
    source_state: str
    disposition: str
    exported: bool
    core_band: int | None
    meridian_band: int | None
    source_result: AcademicPeriodProficiencyResultReference | None
    proficiency_level_id: str | None
    scale_position: int | None
    matching_band_definition: PlanningSignalBandDefinitionExplanation | None
    noncontribution_reason: str | None
    policy_handling: str | None


@dataclass(frozen=True, slots=True)
class PlanningSignalExportExplanation:
    """Deterministic read-only trace for one exact exported Core signal."""

    class_id: str
    signal_set_id: str
    core_contract: str
    created_at: datetime
    core_digest_algorithm: str
    core_signal_digest: str
    receipt_sha256: str
    derivation_id: str
    derivation_sha256: str
    preview_id: str
    preview_sha256: str
    preview_currentness_state: str
    preview_currentness_reason_codes: tuple[str, ...]
    preview_diagnostic_codes: tuple[str, ...]
    review_revision: int
    review_sha256: str
    review_decision: str
    review_actor_kind: str
    review_actor_id: str
    review_reviewed_at: datetime
    acknowledged_warning_ids: tuple[str, ...]
    dimension_id: str
    band_count: int
    students: tuple[PlanningSignalExportStudentExplanation, ...]
    nested_derivation_explanation: PlanningSignalDerivationExplanation


def explain_planning_signal_export(
    workspace_root: str | Path,
    target: PlanningSignalExportTraceTarget,
) -> PlanningSignalExportExplanation:
    """Explain one exact Core export and verify every provenance/band edge."""

    if not isinstance(target, PlanningSignalExportTraceTarget):
        raise ExplanationTraceTargetError(
            "target must be a PlanningSignalExportTraceTarget."
        )

    core, stored_receipt = _resolve_export_target(workspace_root, target)
    receipt = stored_receipt.receipt
    derivation, preview, review = _resolve_exact_dependencies(
        workspace_root,
        stored_receipt,
    )
    _verify_preview_against_exact_derivation(
        workspace_root,
        derivation,
        preview,
    )
    _verify_exact_review(review, preview, stored_receipt)

    nested = explain_planning_signal_derivation(
        workspace_root,
        PlanningSignalDerivationTraceTarget(
            class_id=target.class_id,
            derivation_id=receipt.derivation_reference.derivation_id,
        ),
    )
    if (
        nested.derivation_id != receipt.derivation_reference.derivation_id
        or nested.derivation_sha256 != receipt.derivation_reference.derivation_sha256
    ):
        raise ExplanationTraceIntegrityError(
            "Nested #38 explanation does not match export-receipt provenance."
        )

    students = _reconcile_students(core, nested)
    _verify_core_semantics(core, stored_receipt, derivation)
    _verify_stable_target(workspace_root, target, core, stored_receipt)

    signal = core.signal
    exact_review = review.review
    exact_preview = preview.snapshot
    return PlanningSignalExportExplanation(
        class_id=signal.class_id,
        signal_set_id=signal.signal_set_id,
        core_contract=receipt.core_contract,
        created_at=signal.created_at,
        core_digest_algorithm=core.digest_algorithm,
        core_signal_digest=core.digest,
        receipt_sha256=stored_receipt.receipt_sha256,
        derivation_id=receipt.derivation_reference.derivation_id,
        derivation_sha256=receipt.derivation_reference.derivation_sha256,
        preview_id=receipt.preview_reference.preview_id,
        preview_sha256=receipt.preview_reference.preview_sha256,
        preview_currentness_state=exact_preview.currentness.state,
        preview_currentness_reason_codes=exact_preview.currentness.reason_codes,
        preview_diagnostic_codes=tuple(item.code for item in exact_preview.diagnostics),
        review_revision=exact_review.review_revision,
        review_sha256=stored_receipt.receipt.review_reference.review_sha256,
        review_decision=exact_review.decision,
        review_actor_kind=exact_review.actor.kind,
        review_actor_id=exact_review.actor.actor_id,
        review_reviewed_at=exact_review.reviewed_at,
        acknowledged_warning_ids=exact_review.acknowledged_warning_ids,
        dimension_id=nested.dimension_id,
        band_count=nested.band_count,
        students=students,
        nested_derivation_explanation=nested,
    )


def planning_signal_export_explanation_to_dict(
    value: PlanningSignalExportExplanation,
) -> dict[str, object]:
    """Return deterministic JSON-native data for one exact export trace."""

    if not isinstance(value, PlanningSignalExportExplanation):
        raise ExplanationTraceTargetError(
            "value must be a PlanningSignalExportExplanation."
        )
    return {
        "target": {
            "class_id": value.class_id,
            "signal_set_id": value.signal_set_id,
        },
        "core_signal": {
            "contract": value.core_contract,
            "created_at": value.created_at.isoformat(),
            "digest_algorithm": value.core_digest_algorithm,
            "signal_digest": value.core_signal_digest,
            "dimension_id": value.dimension_id,
            "band_count": value.band_count,
        },
        "export_receipt": {
            "receipt_sha256": value.receipt_sha256,
            "derivation": {
                "derivation_id": value.derivation_id,
                "derivation_sha256": value.derivation_sha256,
            },
            "preview": {
                "preview_id": value.preview_id,
                "preview_sha256": value.preview_sha256,
                "snapshot_currentness": {
                    "state": value.preview_currentness_state,
                    "reason_codes": list(value.preview_currentness_reason_codes),
                },
                "diagnostic_codes": list(value.preview_diagnostic_codes),
            },
            "review": {
                "derivation_id": value.derivation_id,
                "review_revision": value.review_revision,
                "review_sha256": value.review_sha256,
                "decision": value.review_decision,
                "actor": {
                    "kind": value.review_actor_kind,
                    "actor_id": value.review_actor_id,
                },
                "reviewed_at": value.review_reviewed_at.isoformat(),
                "acknowledged_warning_ids": list(value.acknowledged_warning_ids),
            },
        },
        "students": [_student_to_dict(item) for item in value.students],
        "derivation_explanation": planning_signal_derivation_explanation_to_dict(
            value.nested_derivation_explanation
        ),
    }


def planning_signal_export_explanation_to_json_bytes(
    value: PlanningSignalExportExplanation,
) -> bytes:
    """Serialize one export explanation as deterministic readable JSON."""

    return (
        json.dumps(
            planning_signal_export_explanation_to_dict(value),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def render_planning_signal_export_explanation_text(
    value: PlanningSignalExportExplanation,
) -> str:
    """Render exact Core/receipt lineage and per-student export reconciliation."""

    if not isinstance(value, PlanningSignalExportExplanation):
        raise ExplanationTraceTargetError(
            "value must be a PlanningSignalExportExplanation."
        )

    lines = [
        "Planning signal export trace",
        f"Class: {value.class_id}",
        f"Signal set: {value.signal_set_id}",
        (
            "Core: "
            f"contract={value.core_contract} "
            f"created_at={value.created_at.isoformat()} "
            f"{value.core_digest_algorithm}={value.core_signal_digest}"
        ),
        f"Receipt SHA-256: {value.receipt_sha256}",
        (
            "Derivation: "
            f"{value.derivation_id} sha256={value.derivation_sha256}"
        ),
        (
            "Preview: "
            f"{value.preview_id} sha256={value.preview_sha256} "
            f"snapshot_currentness={value.preview_currentness_state}"
        ),
        (
            "Review: "
            f"revision={value.review_revision} sha256={value.review_sha256} "
            f"decision={value.review_decision} "
            f"actor={value.review_actor_kind}:{value.review_actor_id}"
        ),
        f"Planning dimension: {value.dimension_id} bands={value.band_count}",
        "Students:",
    ]
    for student in value.students:
        lines.extend(_student_text(student))

    lines.extend(
        [
            "",
            "Nested exact #38 derivation trace:",
            render_planning_signal_derivation_explanation_text(
                value.nested_derivation_explanation
            ).rstrip(),
        ]
    )
    return "\n".join(lines) + "\n"


def _resolve_export_target(
    workspace_root: str | Path,
    target: PlanningSignalExportTraceTarget,
) -> tuple[StoredGroupingSignal, StoredGroupingSignalExportReceipt]:
    try:
        core = load_grouping_signal(
            workspace_root,
            target.class_id,
            target.signal_set_id,
        )
    except GroupingSignalNotFoundError as core_error:
        try:
            load_grouping_signal_export_receipt(
                workspace_root,
                target.class_id,
                target.signal_set_id,
            )
        except GroupingSignalExportReceiptStorageNotFoundError:
            raise ExplanationTraceNotFoundError(
                "Exact Core grouping signal/export receipt target does not exist."
            ) from core_error
        except GroupingSignalExportReceiptStorageError as receipt_error:
            raise ExplanationTraceIntegrityError(
                "Meridian export receipt exists but its exact Core signal is "
                "missing or invalid."
            ) from receipt_error
        raise ExplanationTraceIntegrityError(
            "Meridian export receipt exists without its exact Core signal."
        ) from core_error
    except GroupingSignalStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact Core grouping signal is unreadable or fails integrity checks."
        ) from error

    try:
        receipt = load_grouping_signal_export_receipt(
            workspace_root,
            target.class_id,
            target.signal_set_id,
        )
    except GroupingSignalExportReceiptStorageNotFoundError as error:
        raise ExplanationTraceIntegrityError(
            "Core grouping signal exists without its Meridian export receipt."
        ) from error
    except GroupingSignalExportReceiptStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Meridian export receipt or one exact receipt dependency fails "
            "integrity checks."
        ) from error
    return core, receipt


def _resolve_exact_dependencies(
    workspace_root: str | Path,
    stored_receipt: StoredGroupingSignalExportReceipt,
) -> tuple[
    StoredGroupingSignalDerivation,
    StoredGroupingSignalPreview,
    StoredGroupingSignalReview,
]:
    receipt = stored_receipt.receipt
    try:
        derivation = load_grouping_signal_derivation_reference(
            workspace_root,
            receipt.derivation_reference,
        )
        preview = load_grouping_signal_preview_reference(
            workspace_root,
            receipt.preview_reference,
        )
        review = load_grouping_signal_review_revision(
            workspace_root,
            receipt.review_reference.class_id,
            receipt.review_reference.derivation_id,
            receipt.review_reference.review_revision,
        )
    except (
        GroupingSignalDerivationStorageError,
        GroupingSignalPreviewStorageError,
        GroupingSignalReviewStorageError,
    ) as error:
        raise ExplanationTraceIntegrityError(
            "Exact export receipt #38/#39 provenance is unavailable or invalid."
        ) from error

    if review.reference != receipt.review_reference:
        raise ExplanationTraceIntegrityError(
            "Exact #39 review digest does not match export-receipt provenance."
        )
    if preview.reference != receipt.preview_reference:
        raise ExplanationTraceIntegrityError(
            "Exact #39 preview digest does not match export-receipt provenance."
        )
    if derivation.reference != receipt.derivation_reference:
        raise ExplanationTraceIntegrityError(
            "Exact #38 derivation digest does not match export-receipt provenance."
        )
    return derivation, preview, review


def _verify_preview_against_exact_derivation(
    workspace_root: str | Path,
    derivation: StoredGroupingSignalDerivation,
    preview: StoredGroupingSignalPreview,
) -> None:
    snapshot = preview.snapshot
    if snapshot.derivation_reference != derivation.reference:
        raise ExplanationTraceIntegrityError(
            "Receipt-bound #39 preview does not bind the exact #38 derivation."
        )

    policy_ref = snapshot.policy_reference
    try:
        policy = load_grouping_signal_policy_revision(
            workspace_root,
            policy_ref.class_id,
            policy_ref.policy_id,
            policy_ref.policy_revision,
        )
    except GroupingSignalPolicyStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #37 policy required to verify the export preview is unavailable."
        ) from error
    if policy.policy_sha256 != policy_ref.policy_sha256:
        raise ExplanationTraceIntegrityError(
            "Exact #37 policy digest does not match the #39 preview."
        )

    scale_ref = policy.policy.academic_basis.target_scale
    try:
        scale = load_proficiency_scale_revision(
            workspace_root,
            scale_ref.class_id,
            scale_ref.scale_id,
            scale_ref.scale_revision,
        )
    except ProficiencyMappingStorageError as error:
        raise ExplanationTraceIntegrityError(
            "Exact proficiency scale required to verify the export preview is "
            "unavailable."
        ) from error
    if scale.scale_sha256 != scale_ref.scale_sha256:
        raise ExplanationTraceIntegrityError(
            "Exact proficiency-scale digest does not match #39 provenance."
        )

    try:
        replay = build_grouping_signal_preview_snapshot(
            derivation.snapshot,
            policy.policy,
            scale.scale,
            snapshot.currentness,
        )
    except GroupingSignalPreviewValidationError as error:
        raise ExplanationTraceIntegrityError(
            "Receipt-bound #39 preview cannot be replayed from exact provenance."
        ) from error
    if replay != snapshot:
        raise ExplanationTraceIntegrityError(
            "Receipt-bound #39 preview differs from deterministic exact replay."
        )


def _verify_exact_review(
    review: StoredGroupingSignalReview,
    preview: StoredGroupingSignalPreview,
    stored_receipt: StoredGroupingSignalExportReceipt,
) -> None:
    receipt = stored_receipt.receipt
    exact_review = review.review
    if (
        exact_review.derivation_reference != receipt.derivation_reference
        or exact_review.preview_reference != receipt.preview_reference
    ):
        raise ExplanationTraceIntegrityError(
            "Receipt-bound #39 review does not bind the exact derivation/preview."
        )
    try:
        validate_grouping_signal_review_against_preview(
            exact_review,
            preview.snapshot,
        )
    except GroupingSignalReviewValidationError as error:
        raise ExplanationTraceIntegrityError(
            "Receipt-bound #39 review is invalid against the exact preview."
        ) from error
    if exact_review.decision != "accepted_for_export":
        raise ExplanationTraceIntegrityError(
            "A Meridian export receipt must bind an accepted_for_export review."
        )


def _verify_core_semantics(
    core: StoredGroupingSignal,
    stored_receipt: StoredGroupingSignalExportReceipt,
    derivation: StoredGroupingSignalDerivation,
) -> None:
    receipt = stored_receipt.receipt
    if receipt.core_digest_algorithm != GROUPING_SIGNAL_EXPORT_RECEIPT_DIGEST_ALGORITHM:
        raise ExplanationTraceIntegrityError(
            "Export receipt uses an unsupported Core digest algorithm."
        )
    if (
        core.digest_algorithm != receipt.core_digest_algorithm
        or core.digest != receipt.core_signal_digest
    ):
        raise ExplanationTraceIntegrityError(
            "Core grouping-signal digest does not match the exact export receipt."
        )

    try:
        expected = build_grouping_signal_export_candidate(
            derivation.snapshot,
            signal_set_id=receipt.signal_set_id,
            created_at=receipt.created_at,
        )
    except GroupingSignalExportProjectionError as error:
        raise ExplanationTraceIntegrityError(
            "Exact #38 derivation cannot reproduce the exported Core signal."
        ) from error
    if expected != core.signal:
        raise ExplanationTraceIntegrityError(
            "Stored Core grouping signal differs from the deterministic exact "
            "#38 export projection."
        )


def _reconcile_students(
    core: StoredGroupingSignal,
    nested: PlanningSignalDerivationExplanation,
) -> tuple[PlanningSignalExportStudentExplanation, ...]:
    signal = core.signal
    if len(signal.dimensions) != 1:
        raise ExplanationTraceIntegrityError(
            "Meridian export must contain exactly one Core planning dimension."
        )
    dimension = signal.dimensions[0]
    if (
        dimension.dimension_id != nested.dimension_id
        or dimension.band_count != nested.band_count
    ):
        raise ExplanationTraceIntegrityError(
            "Core planning dimension does not match exact #38 derivation."
        )

    by_student: dict[str, int] = {}
    for entry in signal.student_bands:
        if entry.dimension_id != nested.dimension_id:
            raise ExplanationTraceIntegrityError(
                "Core student band references an unexpected planning dimension."
            )
        if entry.student_id in by_student:
            raise ExplanationTraceIntegrityError(
                "Core grouping signal contains duplicate student-band identity."
            )
        by_student[entry.student_id] = entry.band

    rows: list[PlanningSignalExportStudentExplanation] = []
    derivation_ids = {item.student_id for item in nested.students}
    unexpected = sorted(set(by_student) - derivation_ids)
    if unexpected:
        raise ExplanationTraceIntegrityError(
            "Core grouping signal contains student band(s) with no exact #38 "
            "student derivation."
        )

    for item in nested.students:
        rows.append(_reconcile_student(item, by_student.get(item.student_id)))
    return tuple(rows)


def _reconcile_student(
    item: PlanningSignalStudentDerivationExplanation,
    core_band: int | None,
) -> PlanningSignalExportStudentExplanation:
    if item.disposition == "contributing":
        if core_band is None:
            raise ExplanationTraceIntegrityError(
                "A contributing #38 student is absent from the Core export."
            )
        if item.band is None or core_band != item.band:
            raise ExplanationTraceIntegrityError(
                "Core exported band disagrees with exact #38 derived band."
            )
        exported = True
    else:
        if core_band is not None:
            raise ExplanationTraceIntegrityError(
                "Core exports a band for a noncontributing #38 student."
            )
        exported = False

    return PlanningSignalExportStudentExplanation(
        student_id=item.student_id,
        source_state=item.source_state,
        disposition=item.disposition,
        exported=exported,
        core_band=core_band,
        meridian_band=item.band,
        source_result=item.source_result,
        proficiency_level_id=item.proficiency_level_id,
        scale_position=item.scale_position,
        matching_band_definition=item.matching_band_definition,
        noncontribution_reason=item.noncontribution_reason,
        policy_handling=item.policy_handling,
    )


def _verify_stable_target(
    workspace_root: str | Path,
    target: PlanningSignalExportTraceTarget,
    core: StoredGroupingSignal,
    receipt: StoredGroupingSignalExportReceipt,
) -> None:
    try:
        current_core = load_grouping_signal(
            workspace_root,
            target.class_id,
            target.signal_set_id,
        )
        current_receipt = load_grouping_signal_export_receipt(
            workspace_root,
            target.class_id,
            target.signal_set_id,
        )
    except (
        GroupingSignalStorageError,
        GroupingSignalExportReceiptStorageError,
    ) as error:
        raise ExplanationTraceIntegrityError(
            "Exact export target changed or became unreadable during explanation."
        ) from error
    if current_core != core or current_receipt != receipt:
        raise ExplanationTraceIntegrityError(
            "Exact export target changed while the explanation was being resolved."
        )


def _student_to_dict(
    value: PlanningSignalExportStudentExplanation,
) -> dict[str, object]:
    return {
        "student_id": value.student_id,
        "source_state": value.source_state,
        "disposition": value.disposition,
        "exported": value.exported,
        "core_band": value.core_band,
        "meridian_band": value.meridian_band,
        "source_result": (
            academic_period_proficiency_result_reference_to_dict(value.source_result)
            if value.source_result is not None
            else None
        ),
        "proficiency_level_id": value.proficiency_level_id,
        "scale_position": value.scale_position,
        "matching_band_definition": (
            _band_to_dict(value.matching_band_definition)
            if value.matching_band_definition is not None
            else None
        ),
        "noncontribution_reason": value.noncontribution_reason,
        "policy_handling": value.policy_handling,
    }


def _band_to_dict(
    value: PlanningSignalBandDefinitionExplanation,
) -> dict[str, int]:
    return {
        "band": value.band,
        "minimum_scale_position": value.minimum_scale_position,
        "maximum_scale_position": value.maximum_scale_position,
    }


def _student_text(value: PlanningSignalExportStudentExplanation) -> list[str]:
    exported = "yes" if value.exported else "no"
    lines = [
        (
            f"  - {value.student_id}: source_state={value.source_state} "
            f"disposition={value.disposition} exported={exported} "
            f"core_band={_optional(value.core_band)} "
            f"meridian_band={_optional(value.meridian_band)}"
        )
    ]
    if value.source_result is not None:
        lines.append(
            "    #35 source: "
            f"revision={value.source_result.result_revision} "
            f"sha256={value.source_result.result_sha256}"
        )
    if value.exported:
        band = value.matching_band_definition
        if band is None:
            raise ExplanationTraceIntegrityError(
                "Exported student is missing the matching #37 band definition."
            )
        lines.append(
            "    mapping: "
            f"level={value.proficiency_level_id} -> "
            f"scale_position={value.scale_position} -> "
            f"range={band.minimum_scale_position}-{band.maximum_scale_position} "
            f"-> band={value.meridian_band}"
        )
    else:
        lines.append(
            "    no exported band: "
            f"reason={value.noncontribution_reason} "
            f"policy_handling={value.policy_handling}"
        )
    return lines


def _optional(value: object | None) -> str:
    return "none" if value is None else str(value)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ExplanationTraceTargetError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ExplanationTraceTargetError(str(error)) from error
