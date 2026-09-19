"""Common read-only Grade preview explanation contracts for Meridian v0.3.

Issue #54 explains exact persisted Grade results and #53 effective-Grade
resolution without recalculating, selecting, or mutating academic state.  This
module owns the cross-family contracts only; family-specific item, standard, and
hybrid-component detail lives in later explanation modules.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, Literal, TypeAlias

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    academic_period_ref_to_dict,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.effective_grade import (
    EffectiveGradeOverrideApplicability,
    EffectiveGradeOverrideReason,
    EffectiveGradeResolution,
    EffectiveGradeSource,
)
from meridian.grade_policy import (
    GradeCalculationFamily,
    GradePolicyReference,
    GradePolicyRevision,
    GradePolicyValidationError,
    grade_policy_reference,
    grade_policy_reference_to_dict,
    validate_grade_policy_revision,
)
from meridian.grade_policy_activation import (
    GradePolicyActivationDecision,
    GradePolicyActivationReference,
    GradePolicyActivationValidationError,
    grade_policy_activation_reference,
    grade_policy_activation_reference_to_dict,
    validate_grade_policy_activation_decision,
)
from meridian.teacher_grade_override import (
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideDecisionKind,
    TeacherGradeOverrideReference,
    grade_override_source_result_reference_to_dict,
    teacher_grade_override_reference_to_dict,
)

GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION: Final[str] = "1"
MAXIMUM_GRADE_PREVIEW_TEXT_LENGTH: Final[int] = 2000
MAXIMUM_GRADE_PREVIEW_KEY_LENGTH: Final[int] = 512

GradePreviewBasisDimension: TypeAlias = Literal[
    "activation",
    "policy",
    "state_treatment",
    "reassessment",
    "rounding",
    "algorithm",
    "formula",
    "participation",
    "evidence",
    "weighting",
]

_BASIS_DIMENSIONS: Final[frozenset[str]] = frozenset(
    {
        "activation",
        "policy",
        "state_treatment",
        "reassessment",
        "rounding",
        "algorithm",
        "formula",
        "participation",
        "evidence",
        "weighting",
    }
)
_STATE_FIELDS: Final[tuple[str, ...]] = (
    "missing",
    "pending",
    "incomplete",
    "excused",
    "excluded",
    "not_applicable",
    "insufficient_evidence",
    "unavailable",
    "withdrawn",
    "invalid",
    "unresolved",
)
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


class GradePreviewError(RuntimeError):
    """Base error for deterministic Grade-preview explanation."""

    code = "grade_preview.error"


class GradePreviewTargetError(GradePreviewError, ValueError):
    """Raised when a Grade-preview target or pure input is invalid."""

    code = "grade_preview.target_invalid"


class GradePreviewSourceError(GradePreviewError):
    """Raised when an explicitly requested Grade source cannot be resolved."""

    code = "grade_preview.source_unavailable"


class GradePreviewTargetNotFoundError(GradePreviewSourceError):
    """Raised when an explicitly requested current Grade selection is absent."""

    code = "grade_preview.target_not_found"


class GradePreviewIntegrityError(GradePreviewError):
    """Raised when exact Grade-preview provenance cannot be trusted."""

    code = "grade_preview.integrity_failed"


class GradePreviewCurrentnessConflictError(GradePreviewError):
    """Raised when current authority changes during explanation resolution."""

    code = "grade_preview.currentness_conflict"


class GradePreviewComparisonError(GradePreviewError, ValueError):
    """Raised when a report/snapshot comparison basis is invalid."""

    code = "grade_preview.comparison_invalid"


@dataclass(frozen=True, slots=True)
class GradePreviewTarget:
    """Exact logical scope for one current Grade preview."""

    class_id: str
    student_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    calculation_family: GradeCalculationFamily

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        try:
            period = validate_academic_period_ref(self.target_period)
        except (AcademicPeriodValidationError, TypeError) as error:
            raise GradePreviewTargetError(
                f"target_period is invalid: {error}"
            ) from error
        object.__setattr__(self, "target_period", period)
        object.__setattr__(
            self,
            "calendar_revision",
            _positive_int(self.calendar_revision, "calendar_revision"),
        )
        if self.calculation_family not in {
            "conventional",
            "standards_based",
            "hybrid",
        }:
            raise GradePreviewTargetError(
                "calculation_family must be conventional, standards_based, or hybrid."
            )


@dataclass(frozen=True, slots=True)
class GradePreviewStateTreatmentRule:
    """One exact non-Grade-state consequence from Grade policy."""

    state: str
    consequence: str

    def __post_init__(self) -> None:
        if self.state not in _STATE_FIELDS:
            raise GradePreviewTargetError("unsupported Grade state treatment key.")
        if self.consequence not in {"exclude", "blocking", "zero"}:
            raise GradePreviewTargetError("unsupported Grade state consequence.")


@dataclass(frozen=True, slots=True)
class GradePreviewRoundingExplanation:
    """Exact final-Grade Decimal rounding semantics."""

    quantum: Decimal
    mode: str
    application_stage: str

    def __post_init__(self) -> None:
        _positive_decimal(self.quantum, "rounding.quantum")
        if self.mode not in {
            "half_even",
            "half_up",
            "half_down",
            "up",
            "down",
            "ceiling",
            "floor",
        }:
            raise GradePreviewTargetError("unsupported Grade rounding mode.")
        if self.application_stage != "final":
            raise GradePreviewTargetError(
                "Grade preview rounding application_stage must be final."
            )


@dataclass(frozen=True, slots=True)
class GradePreviewPolicyExplanation:
    """Exact common policy and activation basis for one persisted Grade result."""

    activation_reference: GradePolicyActivationReference
    policy_reference: GradePolicyReference
    title: str
    calculation_family: GradeCalculationFamily
    policy_actor_kind: str
    policy_actor_id: str
    policy_rationale: str | None
    policy_revised_at: datetime
    activation_actor_kind: str
    activation_actor_id: str
    activation_rationale: str | None
    activation_decided_at: datetime
    state_treatment: tuple[GradePreviewStateTreatmentRule, ...]
    reassessment_selection_authority: str
    reassessment_unresolved_handling: str
    rounding: GradePreviewRoundingExplanation

    def __post_init__(self) -> None:
        if not isinstance(self.activation_reference, GradePolicyActivationReference):
            raise GradePreviewTargetError(
                "activation_reference must be GradePolicyActivationReference."
            )
        try:
            reference = grade_policy_reference_to_dict(self.policy_reference)
        except (GradePolicyValidationError, TypeError) as error:
            raise GradePreviewTargetError(
                f"policy_reference is invalid: {error}"
            ) from error
        if reference["class_id"] != self.activation_reference.class_id:
            raise GradePreviewTargetError(
                "policy and activation references must share class_id."
            )
        _bounded_text(self.title, "title", MAXIMUM_GRADE_PREVIEW_TEXT_LENGTH)
        if self.calculation_family not in {
            "conventional",
            "standards_based",
            "hybrid",
        }:
            raise GradePreviewTargetError("unsupported Grade policy family.")
        if self.policy_actor_kind not in {"teacher", "policy"}:
            raise GradePreviewTargetError("unsupported Grade policy actor kind.")
        _bounded_text(self.policy_actor_id, "policy_actor_id", 256)
        _optional_bounded_text(self.policy_rationale, "policy_rationale")
        object.__setattr__(
            self,
            "policy_revised_at",
            _aware_utc(self.policy_revised_at, "policy_revised_at"),
        )
        if self.activation_actor_kind not in {"teacher", "policy"}:
            raise GradePreviewTargetError("unsupported activation actor kind.")
        _bounded_text(self.activation_actor_id, "activation_actor_id", 256)
        _optional_bounded_text(self.activation_rationale, "activation_rationale")
        object.__setattr__(
            self,
            "activation_decided_at",
            _aware_utc(self.activation_decided_at, "activation_decided_at"),
        )
        rules = tuple(self.state_treatment)
        if any(not isinstance(rule, GradePreviewStateTreatmentRule) for rule in rules):
            raise GradePreviewTargetError(
                "state_treatment must contain GradePreviewStateTreatmentRule values."
            )
        if tuple(rule.state for rule in rules) != _STATE_FIELDS:
            raise GradePreviewTargetError(
                "state_treatment must contain every supported state in canonical order."
            )
        object.__setattr__(self, "state_treatment", rules)
        if (
            self.reassessment_selection_authority
            != "v02_attempt_and_reassessment_state"
        ):
            raise GradePreviewTargetError(
                "unsupported reassessment selection authority."
            )
        if self.reassessment_unresolved_handling not in {"exclude", "blocking"}:
            raise GradePreviewTargetError(
                "unsupported reassessment unresolved handling."
            )
        if not isinstance(self.rounding, GradePreviewRoundingExplanation):
            raise GradePreviewTargetError(
                "rounding must be GradePreviewRoundingExplanation."
            )


@dataclass(frozen=True, slots=True)
class GradePreviewBaseResultExplanation:
    """Family-neutral exact metadata for one persisted Grade result."""

    source_result: GradeOverrideSourceResultReference
    algorithm_version: str
    calculation_fingerprint: str
    inputs_sha256: str
    calculated_at: datetime
    unrounded_grade: Decimal | None
    rounded_grade: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.source_result, GradeOverrideSourceResultReference):
            raise GradePreviewTargetError(
                "source_result must be GradeOverrideSourceResultReference."
            )
        _bounded_text(self.algorithm_version, "algorithm_version", 256)
        object.__setattr__(
            self,
            "calculation_fingerprint",
            _sha256(self.calculation_fingerprint, "calculation_fingerprint"),
        )
        object.__setattr__(
            self,
            "inputs_sha256",
            _sha256(self.inputs_sha256, "inputs_sha256"),
        )
        object.__setattr__(
            self,
            "calculated_at",
            _aware_utc(self.calculated_at, "calculated_at"),
        )
        _optional_finite_decimal(self.unrounded_grade, "unrounded_grade")
        _optional_finite_decimal(self.rounded_grade, "rounded_grade")


@dataclass(frozen=True, slots=True)
class GradePreviewOverrideExplanation:
    """Exact selected teacher-override decision and #53 applicability."""

    reference: TeacherGradeOverrideReference
    decision: TeacherGradeOverrideDecisionKind
    source_result: GradeOverrideSourceResultReference
    replacement_grade: Decimal | None
    withdrawn_override_reference: TeacherGradeOverrideReference | None
    actor_id: str
    rationale: str
    decided_at: datetime
    applicability: EffectiveGradeOverrideApplicability
    reasons: tuple[EffectiveGradeOverrideReason, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.reference, TeacherGradeOverrideReference):
            raise GradePreviewTargetError(
                "override reference must be TeacherGradeOverrideReference."
            )
        if not isinstance(self.source_result, GradeOverrideSourceResultReference):
            raise GradePreviewTargetError(
                "override source_result must be GradeOverrideSourceResultReference."
            )
        if self.decision not in {"override", "withdraw"}:
            raise GradePreviewTargetError("unsupported override decision kind.")
        _optional_finite_decimal(self.replacement_grade, "replacement_grade")
        if self.replacement_grade is not None and self.replacement_grade < 0:
            raise GradePreviewTargetError(
                "override replacement_grade must be nonnegative."
            )
        if self.decision == "override":
            if self.replacement_grade is None:
                raise GradePreviewTargetError(
                    "active override explanation requires replacement_grade."
                )
            if self.withdrawn_override_reference is not None:
                raise GradePreviewTargetError(
                    "active override explanation cannot identify withdrawal target."
                )
        else:
            if self.replacement_grade is not None:
                raise GradePreviewTargetError(
                    "withdrawal explanation cannot carry replacement_grade."
                )
            if not isinstance(
                self.withdrawn_override_reference,
                TeacherGradeOverrideReference,
            ):
                raise GradePreviewTargetError(
                    "withdrawal explanation requires withdrawn override reference."
                )
        _bounded_text(self.actor_id, "override actor_id", 256)
        _bounded_text(self.rationale, "override rationale")
        object.__setattr__(
            self,
            "decided_at",
            _aware_utc(self.decided_at, "override decided_at"),
        )
        expected: dict[
            EffectiveGradeOverrideApplicability,
            tuple[EffectiveGradeOverrideReason, ...],
        ] = {
            "no_override": ("no_selected_override",),
            "applicable": (),
            "withdrawn": ("selected_override_withdrawn",),
            "source_result_changed": ("source_result_mismatch",),
            "source_result_stale": ("source_result_stale",),
        }
        if self.applicability not in expected:
            raise GradePreviewTargetError("unsupported override applicability.")
        if self.applicability == "no_override":
            raise GradePreviewTargetError(
                "selected override explanation cannot use no_override applicability."
            )
        reasons = tuple(self.reasons)
        if reasons != expected[self.applicability]:
            raise GradePreviewTargetError(
                "override reasons do not match override applicability."
            )
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class GradePreviewBasisEntry:
    """One immutable semantic comparison dimension for later report snapshots."""

    dimension: GradePreviewBasisDimension
    key: str
    sha256: str

    def __post_init__(self) -> None:
        if self.dimension not in _BASIS_DIMENSIONS:
            raise GradePreviewComparisonError("unsupported comparison dimension.")
        object.__setattr__(
            self,
            "key",
            _bounded_text(self.key, "basis key", MAXIMUM_GRADE_PREVIEW_KEY_LENGTH),
        )
        object.__setattr__(self, "sha256", _sha256(self.sha256, "basis sha256"))


@dataclass(frozen=True, slots=True)
class GradePreviewExplanation:
    """Cross-family explanation of one exact selected Grade preview."""

    target: GradePreviewTarget
    base_result: GradePreviewBaseResultExplanation
    base_result_status: str
    base_grade: Decimal | None
    base_freshness_status: str
    base_freshness_reasons: tuple[str, ...]
    policy: GradePreviewPolicyExplanation
    selected_override: GradePreviewOverrideExplanation | None
    override_applicability: EffectiveGradeOverrideApplicability
    override_reasons: tuple[EffectiveGradeOverrideReason, ...]
    effective_grade: Decimal | None
    effective_source: EffectiveGradeSource

    def __post_init__(self) -> None:
        if not isinstance(self.target, GradePreviewTarget):
            raise GradePreviewTargetError("target must be GradePreviewTarget.")
        if not isinstance(self.base_result, GradePreviewBaseResultExplanation):
            raise GradePreviewTargetError(
                "base_result must be GradePreviewBaseResultExplanation."
            )
        _require_source_matches_target(self.base_result.source_result, self.target)
        if self.base_result_status not in {"calculated", "blocked", "insufficient"}:
            raise GradePreviewTargetError("unsupported base_result_status.")
        _optional_finite_decimal(self.base_grade, "base_grade")
        if self.base_result_status == "calculated":
            if self.base_grade is None:
                raise GradePreviewTargetError(
                    "calculated base result requires base_grade."
                )
            if self.base_result.rounded_grade != self.base_grade:
                raise GradePreviewIntegrityError(
                    "base_grade must equal exact persisted rounded Grade."
                )
        elif any(
            value is not None
            for value in (
                self.base_grade,
                self.base_result.unrounded_grade,
                self.base_result.rounded_grade,
            )
        ):
            raise GradePreviewIntegrityError(
                "blocked/insufficient base result must remain nonnumeric."
            )
        if self.base_freshness_status not in {"current", "stale"}:
            raise GradePreviewTargetError("unsupported base freshness status.")
        freshness_reasons = _reason_tuple(
            self.base_freshness_reasons,
            "base_freshness_reasons",
        )
        if self.base_freshness_status == "current" and freshness_reasons:
            raise GradePreviewTargetError(
                "current base result must not carry freshness reasons."
            )
        if self.base_freshness_status == "stale" and not freshness_reasons:
            raise GradePreviewTargetError(
                "stale base result requires freshness reasons."
            )
        object.__setattr__(self, "base_freshness_reasons", freshness_reasons)
        if not isinstance(self.policy, GradePreviewPolicyExplanation):
            raise GradePreviewTargetError(
                "policy must be GradePreviewPolicyExplanation."
            )
        _require_policy_matches_target(self.policy, self.target)
        override = self.selected_override
        if override is None:
            if self.override_applicability != "no_override":
                raise GradePreviewIntegrityError(
                    "missing selected override requires no_override applicability."
                )
        else:
            _require_override_matches_target(override, self.target)
            if override.applicability != self.override_applicability:
                raise GradePreviewIntegrityError(
                    "override explanation applicability does not match preview."
                )
        if self.override_applicability not in {
            "no_override",
            "applicable",
            "withdrawn",
            "source_result_changed",
            "source_result_stale",
        }:
            raise GradePreviewTargetError("unsupported override applicability.")
        reasons = tuple(self.override_reasons)
        expected: dict[
            EffectiveGradeOverrideApplicability,
            tuple[EffectiveGradeOverrideReason, ...],
        ] = {
            "no_override": ("no_selected_override",),
            "applicable": (),
            "withdrawn": ("selected_override_withdrawn",),
            "source_result_changed": ("source_result_mismatch",),
            "source_result_stale": ("source_result_stale",),
        }
        if reasons != expected[self.override_applicability]:
            raise GradePreviewIntegrityError(
                "override_reasons do not match override_applicability."
            )
        object.__setattr__(self, "override_reasons", reasons)
        _optional_finite_decimal(self.effective_grade, "effective_grade")
        if self.effective_source not in {"base", "override", "none"}:
            raise GradePreviewTargetError("unsupported effective_source.")
        _validate_effective_semantics(self)


@dataclass(frozen=True, slots=True)
class GradePreviewObservation:
    """Compact deterministic #54 handoff suitable for future #55 freezing."""

    schema_version: str
    target: GradePreviewTarget
    base_result_reference: GradeOverrideSourceResultReference
    base_result_status: str
    base_grade: Decimal | None
    base_freshness_status: str
    base_freshness_reasons: tuple[str, ...]
    algorithm_version: str
    calculation_fingerprint: str
    inputs_sha256: str
    activation_reference: GradePolicyActivationReference
    policy_reference: GradePolicyReference
    selected_override_reference: TeacherGradeOverrideReference | None
    override_applicability: EffectiveGradeOverrideApplicability
    override_replacement_grade: Decimal | None
    effective_grade: Decimal | None
    effective_source: EffectiveGradeSource
    basis_entries: tuple[GradePreviewBasisEntry, ...]

    def __post_init__(self) -> None:
        if self.schema_version != GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION:
            raise GradePreviewTargetError(
                'GradePreviewObservation schema_version must be "1".'
            )
        if not isinstance(self.target, GradePreviewTarget):
            raise GradePreviewTargetError("observation target is invalid.")
        _require_source_matches_target(self.base_result_reference, self.target)
        if self.base_result_status not in {"calculated", "blocked", "insufficient"}:
            raise GradePreviewTargetError("observation base status is invalid.")
        _optional_finite_decimal(self.base_grade, "observation base_grade")
        if self.base_result_status == "calculated" and self.base_grade is None:
            raise GradePreviewTargetError(
                "calculated observation requires base_grade."
            )
        if self.base_result_status != "calculated" and self.base_grade is not None:
            raise GradePreviewTargetError(
                "blocked/insufficient observation must not carry base_grade."
            )
        if self.base_freshness_status not in {"current", "stale"}:
            raise GradePreviewTargetError("observation freshness status is invalid.")
        reasons = _reason_tuple(
            self.base_freshness_reasons,
            "observation base_freshness_reasons",
        )
        if self.base_freshness_status == "current" and reasons:
            raise GradePreviewTargetError(
                "current observation must not carry freshness reasons."
            )
        if self.base_freshness_status == "stale" and not reasons:
            raise GradePreviewTargetError(
                "stale observation requires freshness reasons."
            )
        object.__setattr__(self, "base_freshness_reasons", reasons)
        _bounded_text(self.algorithm_version, "observation algorithm_version", 256)
        object.__setattr__(
            self,
            "calculation_fingerprint",
            _sha256(self.calculation_fingerprint, "calculation_fingerprint"),
        )
        object.__setattr__(
            self,
            "inputs_sha256",
            _sha256(self.inputs_sha256, "inputs_sha256"),
        )
        if not isinstance(self.activation_reference, GradePolicyActivationReference):
            raise GradePreviewTargetError(
                "observation activation reference is invalid."
            )
        if (
            self.activation_reference.class_id != self.target.class_id
            or self.activation_reference.school_year
            != self.target.target_period.school_year
            or self.activation_reference.period_id
            != self.target.target_period.period_id
        ):
            raise GradePreviewIntegrityError(
                "observation activation reference does not match target."
            )
        try:
            policy_data = grade_policy_reference_to_dict(self.policy_reference)
        except (GradePolicyValidationError, TypeError) as error:
            raise GradePreviewTargetError(
                f"observation policy reference is invalid: {error}"
            ) from error
        if policy_data["class_id"] != self.target.class_id:
            raise GradePreviewTargetError(
                "observation policy reference must match target class."
            )
        override_reference = self.selected_override_reference
        if override_reference is not None:
            _require_override_reference_matches_target(override_reference, self.target)
        if self.override_applicability not in {
            "no_override",
            "applicable",
            "withdrawn",
            "source_result_changed",
            "source_result_stale",
        }:
            raise GradePreviewTargetError("observation applicability is invalid.")
        if self.override_applicability == "no_override":
            if (
                override_reference is not None
                or self.override_replacement_grade is not None
            ):
                raise GradePreviewTargetError(
                    "no_override observation cannot carry selected override data."
                )
        elif override_reference is None:
            raise GradePreviewTargetError(
                "selected override applicability requires override reference."
            )
        _optional_finite_decimal(
            self.override_replacement_grade,
            "override_replacement_grade",
        )
        if (
            self.override_replacement_grade is not None
            and self.override_replacement_grade < 0
        ):
            raise GradePreviewTargetError(
                "override_replacement_grade must be nonnegative."
            )
        if self.override_applicability == "applicable":
            if self.override_replacement_grade is None:
                raise GradePreviewTargetError(
                    "applicable override observation requires replacement Grade."
                )
        elif self.override_replacement_grade is not None:
            raise GradePreviewTargetError(
                "non-applicable override observation cannot carry replacement Grade."
            )
        _optional_finite_decimal(self.effective_grade, "observation effective_grade")
        if self.effective_source not in {"base", "override", "none"}:
            raise GradePreviewTargetError("observation effective source is invalid.")
        if self.effective_source == "base":
            if (
                self.base_freshness_status != "current"
                or self.base_result_status != "calculated"
                or self.effective_grade != self.base_grade
                or self.override_applicability == "applicable"
            ):
                raise GradePreviewIntegrityError(
                    "observation base authority violates #53 precedence."
                )
        elif self.effective_source == "override":
            if (
                self.override_applicability != "applicable"
                or self.override_replacement_grade is None
                or self.effective_grade != self.override_replacement_grade
            ):
                raise GradePreviewIntegrityError(
                    "observation override authority violates #53 precedence."
                )
        elif self.effective_grade is not None:
            raise GradePreviewIntegrityError(
                "observation effective_source=none requires no effective Grade."
            )
        elif (
            self.base_freshness_status == "current"
            and self.base_result_status == "calculated"
            and self.override_applicability != "applicable"
        ):
            raise GradePreviewIntegrityError(
                "current calculated observation must expose base authority."
            )
        entries = tuple(self.basis_entries)
        if any(not isinstance(entry, GradePreviewBasisEntry) for entry in entries):
            raise GradePreviewComparisonError(
                "basis_entries must contain GradePreviewBasisEntry values."
            )
        keys = tuple((entry.dimension, entry.key) for entry in entries)
        if len(set(keys)) != len(keys):
            raise GradePreviewComparisonError(
                "basis_entries must not contain duplicate dimension/key pairs."
            )
        canonical = tuple(sorted(entries, key=lambda item: (item.dimension, item.key)))
        object.__setattr__(self, "basis_entries", canonical)


def explain_grade_preview_common(
    *,
    target: GradePreviewTarget,
    base_result: GradePreviewBaseResultExplanation,
    policy: GradePolicyRevision,
    activation: GradePolicyActivationDecision,
    effective: EffectiveGradeResolution,
) -> GradePreviewExplanation:
    """Build the common #54 explanation over already-resolved exact authority."""

    if not isinstance(target, GradePreviewTarget):
        raise GradePreviewTargetError("target must be GradePreviewTarget.")
    if not isinstance(base_result, GradePreviewBaseResultExplanation):
        raise GradePreviewTargetError(
            "base_result must be GradePreviewBaseResultExplanation."
        )
    if not isinstance(effective, EffectiveGradeResolution):
        raise GradePreviewTargetError("effective must be EffectiveGradeResolution.")
    try:
        exact_policy = validate_grade_policy_revision(policy)
        exact_activation = validate_grade_policy_activation_decision(activation)
    except (GradePolicyValidationError, GradePolicyActivationValidationError) as error:
        raise GradePreviewIntegrityError(
            f"Grade policy provenance is invalid: {error}"
        ) from error

    _require_source_matches_target(base_result.source_result, target)
    if effective.base_result_reference != base_result.source_result:
        raise GradePreviewIntegrityError(
            "effective Grade base reference does not match exact persisted result."
        )
    if effective.base_result_family != target.calculation_family:
        raise GradePreviewIntegrityError(
            "effective Grade family does not match preview target."
        )
    if exact_policy.class_id != target.class_id:
        raise GradePreviewIntegrityError("Grade policy class does not match target.")
    if exact_policy.calculation_family != target.calculation_family:
        raise GradePreviewIntegrityError("Grade policy family does not match target.")
    if (
        exact_activation.class_id != target.class_id
        or exact_activation.target_period != target.target_period
        or exact_activation.calendar_revision != target.calendar_revision
    ):
        raise GradePreviewIntegrityError(
            "Grade policy activation scope does not match target."
        )
    if exact_activation.decision != "activate":
        raise GradePreviewIntegrityError(
            "persisted Grade result requires an activating policy decision."
        )
    exact_policy_reference = grade_policy_reference(exact_policy)
    if exact_activation.policy_reference != exact_policy_reference:
        raise GradePreviewIntegrityError(
            "activation does not reference the exact supplied Grade policy."
        )

    policy_explanation = _policy_explanation(exact_policy, exact_activation)
    override_explanation = _override_explanation(effective)
    return GradePreviewExplanation(
        target=target,
        base_result=base_result,
        base_result_status=effective.base_result_status,
        base_grade=effective.base_grade,
        base_freshness_status=effective.base_freshness_status,
        base_freshness_reasons=effective.base_freshness_reasons,
        policy=policy_explanation,
        selected_override=override_explanation,
        override_applicability=effective.override_applicability,
        override_reasons=effective.override_reasons,
        effective_grade=effective.effective_grade,
        effective_source=effective.effective_source,
    )


def grade_preview_observation_from_explanation(
    explanation: GradePreviewExplanation,
    *,
    extra_basis_entries: tuple[GradePreviewBasisEntry, ...] = (),
) -> GradePreviewObservation:
    """Project one rich explanation into the stable #54/#55 handoff contract."""

    if not isinstance(explanation, GradePreviewExplanation):
        raise GradePreviewTargetError(
            "explanation must be GradePreviewExplanation."
        )
    if any(
        not isinstance(entry, GradePreviewBasisEntry)
        for entry in extra_basis_entries
    ):
        raise GradePreviewComparisonError(
            "extra_basis_entries must contain GradePreviewBasisEntry values."
        )
    override = explanation.selected_override
    base_entries = _common_basis_entries(explanation)
    return GradePreviewObservation(
        schema_version=GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
        target=explanation.target,
        base_result_reference=explanation.base_result.source_result,
        base_result_status=explanation.base_result_status,
        base_grade=explanation.base_grade,
        base_freshness_status=explanation.base_freshness_status,
        base_freshness_reasons=explanation.base_freshness_reasons,
        algorithm_version=explanation.base_result.algorithm_version,
        calculation_fingerprint=explanation.base_result.calculation_fingerprint,
        inputs_sha256=explanation.base_result.inputs_sha256,
        activation_reference=explanation.policy.activation_reference,
        policy_reference=explanation.policy.policy_reference,
        selected_override_reference=(
            override.reference if override is not None else None
        ),
        override_applicability=explanation.override_applicability,
        override_replacement_grade=(
            override.replacement_grade
            if override is not None and override.applicability == "applicable"
            else None
        ),
        effective_grade=explanation.effective_grade,
        effective_source=explanation.effective_source,
        basis_entries=base_entries + tuple(extra_basis_entries),
    )


def grade_preview_explanation_to_dict(
    value: GradePreviewExplanation,
) -> dict[str, object]:
    """Convert one common Grade-preview explanation to deterministic JSON data."""

    if not isinstance(value, GradePreviewExplanation):
        raise GradePreviewTargetError("value must be GradePreviewExplanation.")
    override = value.selected_override
    return {
        "target": _target_to_dict(value.target),
        "base_result": _base_result_to_dict(value.base_result),
        "base_result_status": value.base_result_status,
        "base_grade": _optional_decimal_text(value.base_grade),
        "base_freshness_status": value.base_freshness_status,
        "base_freshness_reasons": list(value.base_freshness_reasons),
        "policy": _policy_to_dict(value.policy),
        "selected_override": (
            _override_to_dict(override) if override is not None else None
        ),
        "override_applicability": value.override_applicability,
        "override_reasons": list(value.override_reasons),
        "effective_grade": _optional_decimal_text(value.effective_grade),
        "effective_source": value.effective_source,
    }


def grade_preview_observation_to_dict(
    value: GradePreviewObservation,
) -> dict[str, object]:
    """Convert one GradePreviewObservation to deterministic JSON-native data."""

    if not isinstance(value, GradePreviewObservation):
        raise GradePreviewTargetError("value must be GradePreviewObservation.")
    return {
        "schema_version": value.schema_version,
        "target": _target_to_dict(value.target),
        "base_result_reference": grade_override_source_result_reference_to_dict(
            value.base_result_reference
        ),
        "base_result_status": value.base_result_status,
        "base_grade": _optional_decimal_text(value.base_grade),
        "base_freshness_status": value.base_freshness_status,
        "base_freshness_reasons": list(value.base_freshness_reasons),
        "algorithm_version": value.algorithm_version,
        "calculation_fingerprint": value.calculation_fingerprint,
        "inputs_sha256": value.inputs_sha256,
        "activation_reference": grade_policy_activation_reference_to_dict(
            value.activation_reference
        ),
        "policy_reference": grade_policy_reference_to_dict(value.policy_reference),
        "selected_override_reference": (
            teacher_grade_override_reference_to_dict(
                value.selected_override_reference
            )
            if value.selected_override_reference is not None
            else None
        ),
        "override_applicability": value.override_applicability,
        "override_replacement_grade": _optional_decimal_text(
            value.override_replacement_grade
        ),
        "effective_grade": _optional_decimal_text(value.effective_grade),
        "effective_source": value.effective_source,
        "basis_entries": [
            {
                "dimension": entry.dimension,
                "key": entry.key,
                "sha256": entry.sha256,
            }
            for entry in value.basis_entries
        ],
    }


def grade_preview_observation_to_json_bytes(
    value: GradePreviewObservation,
) -> bytes:
    """Serialize one observation using canonical JSON bytes."""

    return _canonical_json_bytes(grade_preview_observation_to_dict(value))


def grade_preview_observation_sha256(value: GradePreviewObservation) -> str:
    """Return the canonical digest future #55 may bind when freezing previews."""

    return hashlib.sha256(grade_preview_observation_to_json_bytes(value)).hexdigest()


def _policy_explanation(
    policy: GradePolicyRevision,
    activation: GradePolicyActivationDecision,
) -> GradePreviewPolicyExplanation:
    state_treatment = tuple(
        GradePreviewStateTreatmentRule(
            state=state,
            consequence=getattr(policy.state_treatment, state),
        )
        for state in _STATE_FIELDS
    )
    return GradePreviewPolicyExplanation(
        activation_reference=grade_policy_activation_reference(activation),
        policy_reference=grade_policy_reference(policy),
        title=policy.title,
        calculation_family=policy.calculation_family,
        policy_actor_kind=policy.actor.kind,
        policy_actor_id=policy.actor.actor_id,
        policy_rationale=policy.rationale,
        policy_revised_at=policy.revised_at,
        activation_actor_kind=activation.actor.kind,
        activation_actor_id=activation.actor.actor_id,
        activation_rationale=activation.rationale,
        activation_decided_at=activation.decided_at,
        state_treatment=state_treatment,
        reassessment_selection_authority=(
            policy.reassessment_handling.selection_authority
        ),
        reassessment_unresolved_handling=(
            policy.reassessment_handling.unresolved_handling
        ),
        rounding=GradePreviewRoundingExplanation(
            quantum=policy.rounding.quantum,
            mode=policy.rounding.mode,
            application_stage=policy.rounding.application_stage,
        ),
    )


def _override_explanation(
    effective: EffectiveGradeResolution,
) -> GradePreviewOverrideExplanation | None:
    decision = effective.override_decision
    reference = effective.selected_override_reference
    if decision is None:
        if reference is not None:
            raise GradePreviewIntegrityError(
                "effective Grade carries override reference without decision."
            )
        return None
    if reference is None:
        raise GradePreviewIntegrityError(
            "effective Grade carries override decision without reference."
        )
    return GradePreviewOverrideExplanation(
        reference=reference,
        decision=decision.decision,
        source_result=decision.source_result,
        replacement_grade=decision.replacement_grade,
        withdrawn_override_reference=decision.withdrawn_override_reference,
        actor_id=decision.actor.actor_id,
        rationale=decision.rationale,
        decided_at=decision.decided_at,
        applicability=effective.override_applicability,
        reasons=effective.override_reasons,
    )


def _common_basis_entries(
    explanation: GradePreviewExplanation,
) -> tuple[GradePreviewBasisEntry, ...]:
    policy = explanation.policy
    state_treatment = {
        rule.state: rule.consequence for rule in policy.state_treatment
    }
    return (
        GradePreviewBasisEntry(
            "activation",
            "selected_activation",
            policy.activation_reference.activation_sha256,
        ),
        GradePreviewBasisEntry(
            "policy",
            "grade_policy",
            str(
                grade_policy_reference_to_dict(policy.policy_reference)[
                    "policy_sha256"
                ]
            ),
        ),
        GradePreviewBasisEntry(
            "state_treatment",
            "grade_state_treatment",
            _semantic_digest(state_treatment),
        ),
        GradePreviewBasisEntry(
            "reassessment",
            "grade_reassessment_handling",
            _semantic_digest(
                {
                    "selection_authority": (
                        policy.reassessment_selection_authority
                    ),
                    "unresolved_handling": (
                        policy.reassessment_unresolved_handling
                    ),
                }
            ),
        ),
        GradePreviewBasisEntry(
            "rounding",
            "final_grade_rounding",
            _semantic_digest(
                {
                    "quantum": _decimal_text(policy.rounding.quantum),
                    "mode": policy.rounding.mode,
                    "application_stage": policy.rounding.application_stage,
                }
            ),
        ),
        GradePreviewBasisEntry(
            "algorithm",
            explanation.target.calculation_family,
            _semantic_digest(
                {"algorithm_version": explanation.base_result.algorithm_version}
            ),
        ),
    )


def _target_to_dict(value: GradePreviewTarget) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "student_id": value.student_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "calculation_family": value.calculation_family,
    }


def _base_result_to_dict(
    value: GradePreviewBaseResultExplanation,
) -> dict[str, object]:
    return {
        "source_result": grade_override_source_result_reference_to_dict(
            value.source_result
        ),
        "algorithm_version": value.algorithm_version,
        "calculation_fingerprint": value.calculation_fingerprint,
        "inputs_sha256": value.inputs_sha256,
        "calculated_at": value.calculated_at.isoformat(),
        "unrounded_grade": _optional_decimal_text(value.unrounded_grade),
        "rounded_grade": _optional_decimal_text(value.rounded_grade),
    }


def _policy_to_dict(value: GradePreviewPolicyExplanation) -> dict[str, object]:
    return {
        "activation_reference": grade_policy_activation_reference_to_dict(
            value.activation_reference
        ),
        "policy_reference": grade_policy_reference_to_dict(value.policy_reference),
        "title": value.title,
        "calculation_family": value.calculation_family,
        "policy_actor": {
            "kind": value.policy_actor_kind,
            "actor_id": value.policy_actor_id,
        },
        "policy_rationale": value.policy_rationale,
        "policy_revised_at": value.policy_revised_at.isoformat(),
        "activation_actor": {
            "kind": value.activation_actor_kind,
            "actor_id": value.activation_actor_id,
        },
        "activation_rationale": value.activation_rationale,
        "activation_decided_at": value.activation_decided_at.isoformat(),
        "state_treatment": {
            rule.state: rule.consequence for rule in value.state_treatment
        },
        "reassessment_handling": {
            "selection_authority": value.reassessment_selection_authority,
            "unresolved_handling": value.reassessment_unresolved_handling,
        },
        "rounding": {
            "quantum": _decimal_text(value.rounding.quantum),
            "mode": value.rounding.mode,
            "application_stage": value.rounding.application_stage,
        },
    }


def _override_to_dict(
    value: GradePreviewOverrideExplanation,
) -> dict[str, object]:
    return {
        "reference": teacher_grade_override_reference_to_dict(value.reference),
        "decision": value.decision,
        "source_result": grade_override_source_result_reference_to_dict(
            value.source_result
        ),
        "replacement_grade": _optional_decimal_text(value.replacement_grade),
        "withdrawn_override_reference": (
            teacher_grade_override_reference_to_dict(
                value.withdrawn_override_reference
            )
            if value.withdrawn_override_reference is not None
            else None
        ),
        "actor_id": value.actor_id,
        "rationale": value.rationale,
        "decided_at": value.decided_at.isoformat(),
        "applicability": value.applicability,
        "reasons": list(value.reasons),
    }


def _require_source_matches_target(
    source: GradeOverrideSourceResultReference,
    target: GradePreviewTarget,
) -> None:
    if source.family != target.calculation_family:
        raise GradePreviewIntegrityError("source Grade family does not match target.")
    reference = source.reference
    if (
        reference.class_id != target.class_id
        or reference.student_id != target.student_id
        or reference.school_year != target.target_period.school_year
        or reference.period_id != target.target_period.period_id
        or reference.calendar_revision != target.calendar_revision
    ):
        raise GradePreviewIntegrityError("source Grade scope does not match target.")


def _require_policy_matches_target(
    policy: GradePreviewPolicyExplanation,
    target: GradePreviewTarget,
) -> None:
    activation = policy.activation_reference
    if (
        activation.class_id != target.class_id
        or activation.school_year != target.target_period.school_year
        or activation.period_id != target.target_period.period_id
    ):
        raise GradePreviewIntegrityError("policy activation does not match target.")
    if policy.calculation_family != target.calculation_family:
        raise GradePreviewIntegrityError("policy family does not match target.")


def _require_override_matches_target(
    override: GradePreviewOverrideExplanation,
    target: GradePreviewTarget,
) -> None:
    _require_override_reference_matches_target(override.reference, target)
    source = override.source_result.reference
    if (
        override.source_result.family != target.calculation_family
        or source.class_id != target.class_id
        or source.student_id != target.student_id
        or source.school_year != target.target_period.school_year
        or source.period_id != target.target_period.period_id
        or source.calendar_revision != target.calendar_revision
    ):
        raise GradePreviewIntegrityError("override source scope does not match target.")


def _require_override_reference_matches_target(
    reference: TeacherGradeOverrideReference,
    target: GradePreviewTarget,
) -> None:
    if (
        reference.class_id != target.class_id
        or reference.student_id != target.student_id
        or reference.school_year != target.target_period.school_year
        or reference.period_id != target.target_period.period_id
        or reference.calendar_revision != target.calendar_revision
        or reference.calculation_family != target.calculation_family
    ):
        raise GradePreviewIntegrityError(
            "selected override reference does not match preview target."
        )


def _validate_effective_semantics(value: GradePreviewExplanation) -> None:
    if value.effective_source == "base":
        if (
            value.base_freshness_status != "current"
            or value.base_result_status != "calculated"
            or value.effective_grade != value.base_grade
            or value.override_applicability == "applicable"
        ):
            raise GradePreviewIntegrityError(
                "effective base Grade is inconsistent with #53 precedence."
            )
        return
    if value.effective_source == "override":
        override = value.selected_override
        if (
            override is None
            or override.applicability != "applicable"
            or override.replacement_grade is None
            or value.effective_grade != override.replacement_grade
        ):
            raise GradePreviewIntegrityError(
                "effective override Grade is inconsistent with #53 precedence."
            )
        return
    if value.effective_grade is not None:
        raise GradePreviewIntegrityError(
            "effective_source=none requires effective_grade=None."
        )
    if (
        value.base_freshness_status == "current"
        and value.base_result_status == "calculated"
        and value.override_applicability != "applicable"
    ):
        raise GradePreviewIntegrityError(
            "current calculated base must govern without applicable override."
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GradePreviewTargetError(f"{field_name} must be a string.")
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise GradePreviewTargetError(str(error)) from error


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GradePreviewTargetError(f"{field_name} must be a positive integer.")
    return value


def _bounded_text(
    value: object,
    field_name: str,
    maximum: int = MAXIMUM_GRADE_PREVIEW_TEXT_LENGTH,
) -> str:
    if not isinstance(value, str):
        raise GradePreviewTargetError(f"{field_name} must be a string.")
    text = value.strip()
    if not text or len(text) > maximum:
        raise GradePreviewTargetError(
            f"{field_name} must be nonblank and at most {maximum} characters."
        )
    return text


def _optional_bounded_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, field_name)


def _finite_decimal(value: object, field_name: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise GradePreviewTargetError(f"{field_name} must be a finite Decimal.")
    return value


def _positive_decimal(value: object, field_name: str) -> Decimal:
    decimal = _finite_decimal(value, field_name)
    if decimal <= 0:
        raise GradePreviewTargetError(f"{field_name} must be positive.")
    return decimal


def _optional_finite_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    return _finite_decimal(value, field_name)


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise GradePreviewTargetError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _aware_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise GradePreviewTargetError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise GradePreviewTargetError(f"{field_name} must be timezone-aware.")
    utc = value.astimezone(UTC)
    if utc.utcoffset() is None:
        raise GradePreviewTargetError(f"{field_name} must resolve to UTC.")
    return utc


def _reason_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise GradePreviewTargetError(f"{field_name} must be iterable.")
    validated: list[str] = []
    for reason in value:
        if not isinstance(reason, str) or not reason:
            raise GradePreviewTargetError(
                f"{field_name} must contain nonblank strings."
            )
        validated.append(reason)
    reasons = tuple(validated)
    if len(set(reasons)) != len(reasons):
        raise GradePreviewTargetError(f"{field_name} must not contain duplicates.")
    return reasons


def _decimal_text(value: Decimal) -> str:
    decimal = _finite_decimal(value, "Decimal value")
    text = format(decimal, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"-0", ""}:
        text = "0"
    return text


def _optional_decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return _decimal_text(value)


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _semantic_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


__all__ = [
    "GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION",
    "GradePreviewBaseResultExplanation",
    "GradePreviewBasisDimension",
    "GradePreviewBasisEntry",
    "GradePreviewComparisonError",
    "GradePreviewCurrentnessConflictError",
    "GradePreviewError",
    "GradePreviewExplanation",
    "GradePreviewIntegrityError",
    "GradePreviewObservation",
    "GradePreviewOverrideExplanation",
    "GradePreviewPolicyExplanation",
    "GradePreviewRoundingExplanation",
    "GradePreviewSourceError",
    "GradePreviewStateTreatmentRule",
    "GradePreviewTarget",
    "GradePreviewTargetError",
    "GradePreviewTargetNotFoundError",
    "explain_grade_preview_common",
    "grade_preview_explanation_to_dict",
    "grade_preview_observation_from_explanation",
    "grade_preview_observation_sha256",
    "grade_preview_observation_to_dict",
    "grade_preview_observation_to_json_bytes",
]
