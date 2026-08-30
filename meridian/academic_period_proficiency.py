"Pure domain contract for Academic Period proficiency aggregation policy."

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypeAlias, cast

from pds_core.academic_periods import (
    AcademicPeriod,
    AcademicPeriodCalendar,
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    academic_period_ref_from_dict,
    academic_period_ref_to_dict,
    validate_academic_period_calendar,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.grade_item_memberships import (
    GradeItemMembershipDecision,
    GradeItemMembershipValidationError,
    grade_item_membership_decision_to_json_bytes,
    validate_grade_item_membership_decision,
)
from meridian.grade_items import (
    GradeItemValidationError,
    GradeItemWorkReference,
    grade_item_work_reference_from_dict,
    grade_item_work_reference_to_dict,
)
from meridian.proficiency_mapping import (
    ProficiencyScale,
    ProficiencyScaleReference,
    proficiency_scale_reference,
    validate_proficiency_scale,
)
from meridian.standards_evidence import (
    GradeItemAggregationBasis,
    StandardsEvidenceValidationError,
    normalize_standard_id,
)
from meridian.standards_proficiency import (
    MedianEvenRule,
    ModeTieRule,
    StandardProficiencyActor,
    StandardProficiencyCalculationStatus,
    StandardProficiencyInsufficiencyKind,
    StandardProficiencyInsufficiencyReason,
    StandardProficiencyLevelCount,
    StandardProficiencyResultReference,
    StandardProficiencyResultSnapshot,
    StandardProficiencyStrategy,
    StandardProficiencyTieResolution,
    standard_proficiency_result_reference,
    standard_proficiency_result_reference_from_dict,
    standard_proficiency_result_reference_to_dict,
)

ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION: Final[str] = "1"
ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE: Final[str] = (
    "meridian_academic_period_proficiency_aggregation_policy"
)

MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_TITLE_LENGTH: Final[int] = 256
MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_TEXT_LENGTH: Final[int] = 2000
MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_RESULTS: Final[int] = 1000
MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_POLICY_BYTES: Final[int] = 256 * 1024
ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION: Final[str] = "1"
ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE: Final[str] = (
    "meridian_academic_period_proficiency_aggregation_inputs"
)
MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_CANDIDATES: Final[int] = 1000
MAXIMUM_ACADEMIC_PERIOD_MEMBERSHIPS_PER_GRADE_ITEM: Final[int] = 1000
MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_INPUT_BYTES: Final[int] = 4 * 1024 * 1024
ACADEMIC_PERIOD_PROFICIENCY_ALGORITHM_VERSION: Final[str] = "1"
MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_OUTCOME_BYTES: Final[int] = 4 * 1024 * 1024

ACADEMIC_PERIOD_PROFICIENCY_RESULT_SCHEMA_VERSION: Final[str] = "1"
ACADEMIC_PERIOD_PROFICIENCY_RESULT_RECORD_TYPE: Final[str] = (
    "meridian_academic_period_proficiency_result"
)
MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_RESULT_BYTES: Final[int] = 8 * 1024 * 1024

AcademicPeriodMembershipScope: TypeAlias = Literal["direct", "descendants"]
PeriodResultHandling: TypeAlias = Literal["noncontributing", "blocking"]
AcademicPeriodProficiencyAggregationStrategy: TypeAlias = StandardProficiencyStrategy
AcademicPeriodProficiencyInputStatus: TypeAlias = Literal[
    "calculated",
    "insufficient_evidence",
    "missing_result",
    "period_scope_mismatch",
]
AcademicPeriodScopeMismatchReason: TypeAlias = Literal[
    "mixed_sibling_periods",
    "outside_target_period",
    "calendar_revision_mismatch",
    "school_year_mismatch",
]
AcademicPeriodScopeResolutionStatus: TypeAlias = Literal[
    "eligible",
    "period_scope_mismatch",
]
AcademicPeriodProficiencyCalculationStatus: TypeAlias = Literal[
    "calculated",
    "insufficient_evidence",
]
AcademicPeriodProficiencyInsufficiencyKind: TypeAlias = Literal[
    "period_scope_mismatch",
    "blocking_missing_result",
    "blocking_insufficient_result",
    "no_calculated_results",
    "below_minimum_calculated_results",
    "unresolved_mode_tie",
    "unresolved_even_median",
]
AcademicPeriodProficiencyFreshnessStatus: TypeAlias = Literal["current", "stale"]
AcademicPeriodProficiencyStalenessReason: TypeAlias = Literal[
    "inputs_changed",
    "policy_changed",
    "scale_changed",
    "calendar_changed",
    "algorithm_changed",
]

_ACADEMIC_PERIOD_MEMBERSHIP_SCOPES: Final[
    tuple[AcademicPeriodMembershipScope, ...]
] = (
    "direct",
    "descendants",
)
_PERIOD_RESULT_HANDLINGS: Final[tuple[PeriodResultHandling, ...]] = (
    "noncontributing",
    "blocking",
)
_STRATEGIES: Final[tuple[StandardProficiencyStrategy, ...]] = (
    "highest",
    "lowest",
    "median",
    "mode",
)
_TIE_RULES: Final[tuple[Literal["lower", "higher", "insufficient"], ...]] = (
    "lower",
    "higher",
    "insufficient",
)
_CALCULATION_STATUSES: Final[tuple[AcademicPeriodProficiencyCalculationStatus, ...]] = (
    "calculated",
    "insufficient_evidence",
)
_ACADEMIC_PERIOD_INSUFFICIENCY_KINDS: Final[
    tuple[AcademicPeriodProficiencyInsufficiencyKind, ...]
] = (
    "period_scope_mismatch",
    "blocking_missing_result",
    "blocking_insufficient_result",
    "no_calculated_results",
    "below_minimum_calculated_results",
    "unresolved_mode_tie",
    "unresolved_even_median",
)
_ACADEMIC_PERIOD_STALENESS_REASON_ORDER: Final[
    tuple[AcademicPeriodProficiencyStalenessReason, ...]
] = (
    "inputs_changed",
    "policy_changed",
    "scale_changed",
    "calendar_changed",
    "algorithm_changed",
)
_ACADEMIC_PERIOD_STALENESS_REASON_SET: Final[frozenset[str]] = frozenset(
    _ACADEMIC_PERIOD_STALENESS_REASON_ORDER
)
_TIE_KINDS: Final[tuple[Literal["mode_tie", "median_even"], ...]] = (
    "mode_tie",
    "median_even",
)
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_INPUT_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "calculated",
        "insufficient_evidence",
        "missing_result",
        "period_scope_mismatch",
    }
)
_SCOPE_MISMATCH_REASONS: Final[frozenset[str]] = frozenset(
    {
        "mixed_sibling_periods",
        "outside_target_period",
        "calendar_revision_mismatch",
        "school_year_mismatch",
    }
)

_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "policy_id",
        "policy_revision",
        "supersedes_revision",
        "title",
        "target_scale",
        "strategy",
        "period_membership_scope",
        "minimum_calculated_results",
        "mode_tie_rule",
        "median_even_rule",
        "missing_result_handling",
        "insufficient_result_handling",
        "actor",
        "rationale",
        "revised_at",
    }
)
_POLICY_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "policy_id", "policy_revision", "policy_sha256"}
)
_SCALE_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "scale_id", "scale_revision", "scale_sha256"}
)
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})

_TARGET_PERIOD_KEYS: Final[frozenset[str]] = frozenset(
    {"period", "calendar_revision"}
)
_GRADE_ITEM_BASIS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "grade_item_id",
        "grade_item_revision",
        "grade_item_revision_sha256",
    }
)
_MEMBERSHIP_BASIS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "grade_item_id",
        "grade_item_revision",
        "grade_item_revision_sha256",
        "work_reference",
        "membership_revision",
        "membership_sha256",
        "academic_period",
    }
)
_INPUT_ENTRY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "grade_item",
        "memberships",
        "status",
        "period_scope_mismatch_reason",
        "result_reference",
        "result_algorithm_version",
        "result_calculation_fingerprint",
        "result_status",
        "proficiency_level_id",
        "result_insufficiency_reasons",
    }
)
_INPUTS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "target_period",
        "student_id",
        "standard_id",
        "target_scale",
        "period_membership_scope",
        "entries",
    }
)
_INSUFFICIENCY_REASON_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "source_keys", "required_observations", "actual_observations"}
)
_ACADEMIC_PERIOD_INSUFFICIENCY_REASON_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "grade_item_ids", "required_results", "actual_results"}
)
_ACADEMIC_PERIOD_EXPLANATION_ENTRY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "grade_item_id",
        "status",
        "contributed",
        "result_reference",
        "proficiency_level_id",
        "period_scope_mismatch_reason",
    }
)
_ACADEMIC_PERIOD_LEVEL_COUNT_KEYS: Final[frozenset[str]] = frozenset(
    {"proficiency_level_id", "count"}
)
_ACADEMIC_PERIOD_TIE_RESOLUTION_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "rule", "candidate_level_ids", "selected_level_id"}
)
_ACADEMIC_PERIOD_OUTCOME_KEYS: Final[frozenset[str]] = frozenset(
    {
        "algorithm_version",
        "status",
        "proficiency_level_id",
        "aggregation_inputs_sha256",
        "calculation_fingerprint",
        "policy_reference",
        "target_period",
        "target_scale",
        "candidate_count",
        "calculated_result_count",
        "insufficient_result_count",
        "missing_result_count",
        "period_scope_mismatch_count",
        "level_counts",
        "insufficiency_reasons",
        "tie_resolution",
        "explanation_entries",
    }
)

_ACADEMIC_PERIOD_RESULT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "target_period",
        "student_id",
        "standard_id",
        "result_revision",
        "supersedes_revision",
        "algorithm_version",
        "calculation_fingerprint",
        "inputs",
        "inputs_sha256",
        "policy_reference",
        "target_scale",
        "outcome",
        "calculated_at",
    }
)
_ACADEMIC_PERIOD_RESULT_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "school_year",
        "period_id",
        "student_id",
        "standard_id",
        "result_revision",
        "result_sha256",
    }
)


class AcademicPeriodProficiencyError(ValueError):
    "Base error for Academic Period proficiency domain contracts."


class AcademicPeriodProficiencyValidationError(AcademicPeriodProficiencyError):
    "Raised when Academic Period proficiency data violates its contract."


class AcademicPeriodProficiencySerializationError(AcademicPeriodProficiencyError):
    "Raised when Academic Period proficiency JSON is invalid or noncanonical."


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyAggregationPolicy:
    "One immutable policy revision for Academic Period proficiency aggregation."

    schema_version: str
    record_type: str
    class_id: str
    policy_id: str
    policy_revision: int
    supersedes_revision: int | None
    title: str
    target_scale: ProficiencyScaleReference
    strategy: AcademicPeriodProficiencyAggregationStrategy
    period_membership_scope: AcademicPeriodMembershipScope
    minimum_calculated_results: int
    mode_tie_rule: ModeTieRule | None
    median_even_rule: MedianEvenRule | None
    missing_result_handling: PeriodResultHandling
    insufficient_result_handling: PeriodResultHandling
    actor: StandardProficiencyActor
    rationale: str | None
    revised_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != ACADEMIC_PERIOD_PROFICIENCY_POLICY_SCHEMA_VERSION:
            raise AcademicPeriodProficiencyValidationError(
                "unsupported Academic Period proficiency policy schema_version."
            )
        if self.record_type != ACADEMIC_PERIOD_PROFICIENCY_POLICY_RECORD_TYPE:
            raise AcademicPeriodProficiencyValidationError(
                "record_type must identify an Academic Period proficiency policy."
            )

        class_id = _identifier(self.class_id, "class_id")
        policy_id = _identifier(self.policy_id, "policy_id")
        revision = _positive_int(self.policy_revision, "policy_revision")
        supersedes = _optional_positive_int(
            self.supersedes_revision,
            "supersedes_revision",
        )
        _validate_revision_pair(revision, supersedes)

        title = _bounded_text(
            self.title,
            "title",
            MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_TITLE_LENGTH,
        )

        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise AcademicPeriodProficiencyValidationError(
                "target_scale must be a ProficiencyScaleReference."
            )
        if self.target_scale.class_id != class_id:
            raise AcademicPeriodProficiencyValidationError(
                "target_scale class_id must match the policy class_id."
            )

        strategy = _strategy(self.strategy)
        scope = _period_membership_scope(self.period_membership_scope)
        minimum = _positive_int(
            self.minimum_calculated_results,
            "minimum_calculated_results",
        )
        if minimum > MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_RESULTS:
            raise AcademicPeriodProficiencyValidationError(
                "minimum_calculated_results exceeds the bounded maximum of "
                f"{MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_RESULTS}."
            )

        mode_rule = _optional_tie_rule(self.mode_tie_rule, "mode_tie_rule")
        median_rule = _optional_tie_rule(
            self.median_even_rule,
            "median_even_rule",
        )
        if strategy == "mode":
            if mode_rule is None:
                raise AcademicPeriodProficiencyValidationError(
                    "mode strategy requires mode_tie_rule."
                )
            if median_rule is not None:
                raise AcademicPeriodProficiencyValidationError(
                    "mode strategy must not define median_even_rule."
                )
        elif strategy == "median":
            if median_rule is None:
                raise AcademicPeriodProficiencyValidationError(
                    "median strategy requires median_even_rule."
                )
            if mode_rule is not None:
                raise AcademicPeriodProficiencyValidationError(
                    "median strategy must not define mode_tie_rule."
                )
        elif mode_rule is not None or median_rule is not None:
            raise AcademicPeriodProficiencyValidationError(
                "highest/lowest strategies must not define tie rules."
            )

        missing = _period_result_handling(
            self.missing_result_handling,
            "missing_result_handling",
        )
        insufficient = _period_result_handling(
            self.insufficient_result_handling,
            "insufficient_result_handling",
        )

        if not isinstance(self.actor, StandardProficiencyActor):
            raise AcademicPeriodProficiencyValidationError(
                "actor must be a StandardProficiencyActor."
            )
        actor = StandardProficiencyActor(self.actor.kind, self.actor.actor_id)
        rationale = _optional_bounded_text(
            self.rationale,
            "rationale",
            MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_TEXT_LENGTH,
        )
        revised_at = _aware_utc_datetime(self.revised_at, "revised_at")

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "policy_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(self, "period_membership_scope", scope)
        object.__setattr__(self, "minimum_calculated_results", minimum)
        object.__setattr__(self, "mode_tie_rule", mode_rule)
        object.__setattr__(self, "median_even_rule", median_rule)
        object.__setattr__(self, "missing_result_handling", missing)
        object.__setattr__(self, "insufficient_result_handling", insufficient)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "revised_at", revised_at)


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyAggregationPolicyReference:
    "Exact immutable Academic Period proficiency policy revision and digest."

    class_id: str
    policy_id: str
    policy_revision: int
    policy_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "class_id",
            _identifier(self.class_id, "class_id"),
        )
        object.__setattr__(
            self,
            "policy_id",
            _identifier(self.policy_id, "policy_id"),
        )
        object.__setattr__(
            self,
            "policy_revision",
            _positive_int(self.policy_revision, "policy_revision"),
        )
        object.__setattr__(
            self,
            "policy_sha256",
            _sha256(self.policy_sha256, "policy_sha256"),
        )



@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyTarget:
    "Exact Core Academic Period Calendar revision and period target."

    period: AcademicPeriodRef
    calendar_revision: int

    def __post_init__(self) -> None:
        if not isinstance(self.period, AcademicPeriodRef):
            raise AcademicPeriodProficiencyValidationError(
                "period must be an AcademicPeriodRef."
            )
        try:
            period = validate_academic_period_ref(self.period)
        except AcademicPeriodValidationError as error:
            raise AcademicPeriodProficiencyValidationError(
                f"period is invalid: {error}"
            ) from error
        object.__setattr__(self, "period", period)
        object.__setattr__(
            self,
            "calendar_revision",
            _positive_int(self.calendar_revision, "calendar_revision"),
        )


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyScopeResolution:
    "Pure deterministic period-scope classification for one Grade Item basis."

    status: AcademicPeriodScopeResolutionStatus
    mismatch_reason: AcademicPeriodScopeMismatchReason | None

    def __post_init__(self) -> None:
        if self.status not in {"eligible", "period_scope_mismatch"}:
            raise AcademicPeriodProficiencyValidationError(
                "unsupported Academic Period scope-resolution status."
            )
        reason = self.mismatch_reason
        if reason is not None and reason not in _SCOPE_MISMATCH_REASONS:
            raise AcademicPeriodProficiencyValidationError(
                "unsupported period scope mismatch reason."
            )
        if self.status == "eligible" and reason is not None:
            raise AcademicPeriodProficiencyValidationError(
                "eligible scope resolution must not carry a mismatch reason."
            )
        if self.status == "period_scope_mismatch" and reason is None:
            raise AcademicPeriodProficiencyValidationError(
                "period_scope_mismatch requires an explicit mismatch reason."
            )


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyMembershipBasis:
    "Minimal exact snapshot of one selected included #28 membership decision."

    grade_item_id: str
    grade_item_revision: int
    grade_item_revision_sha256: str
    work_reference: GradeItemWorkReference
    membership_revision: int
    membership_sha256: str
    academic_period: AcademicPeriodProficiencyTarget

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        object.__setattr__(
            self,
            "grade_item_revision",
            _positive_int(self.grade_item_revision, "grade_item_revision"),
        )
        object.__setattr__(
            self,
            "grade_item_revision_sha256",
            _sha256(
                self.grade_item_revision_sha256,
                "grade_item_revision_sha256",
            ),
        )
        if not isinstance(self.work_reference, GradeItemWorkReference):
            raise AcademicPeriodProficiencyValidationError(
                "work_reference must be a GradeItemWorkReference."
            )
        try:
            work_reference = GradeItemWorkReference(
                work=self.work_reference.work,
                registration_revision=self.work_reference.registration_revision,
            )
        except GradeItemValidationError as error:
            raise AcademicPeriodProficiencyValidationError(
                f"work_reference is invalid: {error}"
            ) from error
        object.__setattr__(self, "work_reference", work_reference)
        object.__setattr__(
            self,
            "membership_revision",
            _positive_int(self.membership_revision, "membership_revision"),
        )
        object.__setattr__(
            self,
            "membership_sha256",
            _sha256(self.membership_sha256, "membership_sha256"),
        )
        if not isinstance(self.academic_period, AcademicPeriodProficiencyTarget):
            raise AcademicPeriodProficiencyValidationError(
                "academic_period must be an AcademicPeriodProficiencyTarget."
            )
        object.__setattr__(
            self,
            "academic_period",
            AcademicPeriodProficiencyTarget(
                self.academic_period.period,
                self.academic_period.calendar_revision,
            ),
        )


@dataclass(frozen=True, slots=True)
class ResolvedAcademicPeriodProficiencyCandidate:
    """One exact Grade Item membership basis plus optional exact #34 result."""

    grade_item: GradeItemAggregationBasis
    memberships: tuple[AcademicPeriodProficiencyMembershipBasis, ...]
    result: StandardProficiencyResultSnapshot | None

    def __post_init__(self) -> None:
        if not isinstance(self.grade_item, GradeItemAggregationBasis):
            raise AcademicPeriodProficiencyValidationError(
                "grade_item must be a GradeItemAggregationBasis."
            )
        memberships = _validated_memberships_for_grade_item(
            self.memberships,
            self.grade_item,
        )
        object.__setattr__(self, "memberships", memberships)

        result = self.result
        if result is not None:
            if not isinstance(result, StandardProficiencyResultSnapshot):
                raise AcademicPeriodProficiencyValidationError(
                    "result must be a StandardProficiencyResultSnapshot or None."
                )
            try:
                reference = standard_proficiency_result_reference(result)
            except ValueError as error:
                raise AcademicPeriodProficiencyValidationError(
                    f"#34 result snapshot is invalid: {error}"
                ) from error
            if (
                reference.class_id != self.grade_item.class_id
                or reference.grade_item_id != self.grade_item.grade_item_id
                or result.inputs.grade_item != self.grade_item
            ):
                raise AcademicPeriodProficiencyValidationError(
                    "#34 result must bind the exact candidate Grade Item basis."
                )
            _validate_result_membership_provenance(memberships, result)




@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyAggregationInputEntry:
    "One exact Grade Item candidate normalized for later pure #35 calculation."

    grade_item: GradeItemAggregationBasis
    memberships: tuple[AcademicPeriodProficiencyMembershipBasis, ...]
    status: AcademicPeriodProficiencyInputStatus
    period_scope_mismatch_reason: AcademicPeriodScopeMismatchReason | None
    result_reference: StandardProficiencyResultReference | None
    result_algorithm_version: str | None
    result_calculation_fingerprint: str | None
    result_status: StandardProficiencyCalculationStatus | None
    proficiency_level_id: str | None
    result_insufficiency_reasons: tuple[StandardProficiencyInsufficiencyReason, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.grade_item, GradeItemAggregationBasis):
            raise AcademicPeriodProficiencyValidationError(
                "grade_item must be a GradeItemAggregationBasis."
            )
        memberships = _validated_memberships_for_grade_item(
            self.memberships,
            self.grade_item,
        )
        object.__setattr__(self, "memberships", memberships)

        if self.status not in _INPUT_STATUSES:
            raise AcademicPeriodProficiencyValidationError(
                "unsupported Academic Period proficiency input status."
            )
        mismatch_reason = self.period_scope_mismatch_reason
        if (
            mismatch_reason is not None
            and mismatch_reason not in _SCOPE_MISMATCH_REASONS
        ):
            raise AcademicPeriodProficiencyValidationError(
                "unsupported period scope mismatch reason."
            )

        result_reference = self.result_reference
        if result_reference is not None and not isinstance(
            result_reference,
            StandardProficiencyResultReference,
        ):
            raise AcademicPeriodProficiencyValidationError(
                "result_reference must be a StandardProficiencyResultReference "
                "or None."
            )
        has_result = result_reference is not None
        algorithm_version = self.result_algorithm_version
        fingerprint = self.result_calculation_fingerprint
        result_status = self.result_status
        level_id = self.proficiency_level_id
        reasons = tuple(self.result_insufficiency_reasons)
        if any(
            not isinstance(reason, StandardProficiencyInsufficiencyReason)
            for reason in reasons
        ):
            raise AcademicPeriodProficiencyValidationError(
                "result_insufficiency_reasons contains an invalid reason."
            )

        if result_reference is not None:
            if (
                algorithm_version is None
                or fingerprint is None
                or result_status is None
            ):
                raise AcademicPeriodProficiencyValidationError(
                    "an exact #34 result requires algorithm, fingerprint, and status."
                )
            algorithm_version = _bounded_text(
                algorithm_version,
                "result_algorithm_version",
                128,
            )
            fingerprint = _sha256(
                fingerprint,
                "result_calculation_fingerprint",
            )
            if result_status not in {"calculated", "insufficient_evidence"}:
                raise AcademicPeriodProficiencyValidationError(
                    "unsupported #34 result status."
                )
            if result_status == "calculated":
                if level_id is None or reasons:
                    raise AcademicPeriodProficiencyValidationError(
                        "calculated #34 result requires one level and no "
                        "insufficiency reasons."
                    )
                level_id = _identifier(level_id, "proficiency_level_id")
            elif level_id is not None or not reasons:
                raise AcademicPeriodProficiencyValidationError(
                    "insufficient #34 result requires no level and at least one "
                    "insufficiency reason."
                )
            if (
                result_reference.class_id != self.grade_item.class_id
                or result_reference.grade_item_id
                != self.grade_item.grade_item_id
            ):
                raise AcademicPeriodProficiencyValidationError(
                    "result_reference must match the exact Grade Item basis scope."
                )
        elif (
            algorithm_version is not None
            or fingerprint is not None
            or result_status is not None
            or level_id is not None
            or reasons
        ):
            raise AcademicPeriodProficiencyValidationError(
                "missing #34 result must not carry normalized result fields."
            )

        if self.status == "calculated":
            if (
                not has_result
                or result_status != "calculated"
                or mismatch_reason is not None
            ):
                raise AcademicPeriodProficiencyValidationError(
                    "calculated input requires one calculated #34 result and no "
                    "period mismatch."
                )
        elif self.status == "insufficient_evidence":
            if (
                not has_result
                or result_status != "insufficient_evidence"
                or mismatch_reason is not None
            ):
                raise AcademicPeriodProficiencyValidationError(
                    "insufficient input requires one insufficient #34 result and "
                    "no period mismatch."
                )
        elif self.status == "missing_result":
            if has_result or mismatch_reason is not None:
                raise AcademicPeriodProficiencyValidationError(
                    "missing_result requires no #34 result and no period mismatch."
                )
        elif mismatch_reason is None:
            raise AcademicPeriodProficiencyValidationError(
                "period_scope_mismatch requires an explicit mismatch reason."
            )

        object.__setattr__(self, "period_scope_mismatch_reason", mismatch_reason)
        object.__setattr__(self, "result_algorithm_version", algorithm_version)
        object.__setattr__(self, "result_calculation_fingerprint", fingerprint)
        object.__setattr__(self, "proficiency_level_id", level_id)
        object.__setattr__(self, "result_insufficiency_reasons", reasons)


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyAggregationInputs:
    "Deterministic bounded Grade Item inputs for one later #35 calculation."

    schema_version: str
    record_type: str
    class_id: str
    target_period: AcademicPeriodProficiencyTarget
    student_id: str
    standard_id: str
    target_scale: ProficiencyScaleReference
    period_membership_scope: AcademicPeriodMembershipScope
    entries: tuple[AcademicPeriodProficiencyAggregationInputEntry, ...]

    def __post_init__(self) -> None:
        if self.schema_version != ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION:
            raise AcademicPeriodProficiencyValidationError(
                "unsupported Academic Period proficiency inputs schema_version."
            )
        if self.record_type != ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE:
            raise AcademicPeriodProficiencyValidationError(
                "record_type must identify Academic Period proficiency inputs."
            )
        class_id = _identifier(self.class_id, "class_id")
        object.__setattr__(self, "class_id", class_id)
        if not isinstance(self.target_period, AcademicPeriodProficiencyTarget):
            raise AcademicPeriodProficiencyValidationError(
                "target_period must be an AcademicPeriodProficiencyTarget."
            )
        object.__setattr__(
            self,
            "target_period",
            AcademicPeriodProficiencyTarget(
                self.target_period.period,
                self.target_period.calendar_revision,
            ),
        )
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        object.__setattr__(self, "standard_id", _standard_id(self.standard_id))
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise AcademicPeriodProficiencyValidationError(
                "target_scale must be a ProficiencyScaleReference."
            )
        if self.target_scale.class_id != class_id:
            raise AcademicPeriodProficiencyValidationError(
                "target_scale class_id must match the input class_id."
            )
        scope = _period_membership_scope(self.period_membership_scope)
        object.__setattr__(self, "period_membership_scope", scope)
        entries = tuple(self.entries)
        if len(entries) > MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_CANDIDATES:
            raise AcademicPeriodProficiencyValidationError(
                "Academic Period proficiency candidate count exceeds the finite "
                "maximum."
            )
        if any(
            not isinstance(item, AcademicPeriodProficiencyAggregationInputEntry)
            for item in entries
        ):
            raise AcademicPeriodProficiencyValidationError(
                "entries contains an invalid Academic Period proficiency input."
            )
        grade_item_ids = tuple(item.grade_item.grade_item_id for item in entries)
        if len(set(grade_item_ids)) != len(grade_item_ids):
            raise AcademicPeriodProficiencyValidationError(
                "entries must not duplicate a logical Grade Item candidate."
            )
        if grade_item_ids != tuple(sorted(grade_item_ids)):
            raise AcademicPeriodProficiencyValidationError(
                "entries must use deterministic Grade Item ID ordering."
            )
        for entry in entries:
            if entry.grade_item.class_id != class_id:
                raise AcademicPeriodProficiencyValidationError(
                    "entry Grade Item class must match the input class_id."
                )
            reference = entry.result_reference
            if reference is not None and (
                reference.class_id != class_id
                or reference.student_id != self.student_id
                or reference.standard_id != self.standard_id
            ):
                raise AcademicPeriodProficiencyValidationError(
                    "#34 result reference must match class/student/standard scope."
                )
        object.__setattr__(self, "entries", entries)

    @property
    def sha256(self) -> str:
        "Stable digest for exact #35 result provenance."
        return academic_period_proficiency_aggregation_inputs_sha256(self)



@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyInsufficiencyReason:
    "Structured reason why one exact #35 calculation cannot yield proficiency."

    kind: AcademicPeriodProficiencyInsufficiencyKind
    grade_item_ids: tuple[str, ...] = ()
    required_results: int | None = None
    actual_results: int | None = None

    def __post_init__(self) -> None:
        allowed = {
            "period_scope_mismatch",
            "blocking_missing_result",
            "blocking_insufficient_result",
            "no_calculated_results",
            "below_minimum_calculated_results",
            "unresolved_mode_tie",
            "unresolved_even_median",
        }
        if self.kind not in allowed:
            raise AcademicPeriodProficiencyValidationError(
                "unsupported Academic Period proficiency insufficiency reason."
            )
        ids = tuple(self.grade_item_ids)
        if any(not isinstance(item, str) for item in ids):
            raise AcademicPeriodProficiencyValidationError(
                "grade_item_ids must contain strings."
            )
        ids = tuple(_identifier(item, "grade_item_id") for item in ids)
        if len(set(ids)) != len(ids):
            raise AcademicPeriodProficiencyValidationError(
                "grade_item_ids must not contain duplicates."
            )
        if ids != tuple(sorted(ids)):
            raise AcademicPeriodProficiencyValidationError(
                "grade_item_ids must use deterministic ordering."
            )
        required = _optional_positive_int(self.required_results, "required_results")
        actual = _optional_nonnegative_int(self.actual_results, "actual_results")

        if self.kind in {
            "period_scope_mismatch",
            "blocking_missing_result",
            "blocking_insufficient_result",
        }:
            if not ids or required is not None or actual is not None:
                raise AcademicPeriodProficiencyValidationError(
                    "blocking insufficiency requires only exact Grade Item IDs."
                )
        elif self.kind == "no_calculated_results":
            if ids or required is not None or actual != 0:
                raise AcademicPeriodProficiencyValidationError(
                    "no_calculated_results requires only actual_results=0."
                )
        elif self.kind == "below_minimum_calculated_results":
            if ids or required is None or actual is None or actual >= required:
                raise AcademicPeriodProficiencyValidationError(
                    "below-minimum result insufficiency requires exact "
                    "required/actual counts."
                )
        elif ids or required is not None or actual is not None:
            raise AcademicPeriodProficiencyValidationError(
                "tie insufficiency must not carry Grade Item or count fields."
            )

        object.__setattr__(self, "grade_item_ids", ids)
        object.__setattr__(self, "required_results", required)
        object.__setattr__(self, "actual_results", actual)


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyEntryExplanation:
    "Privacy-minimal deterministic explanation for one Grade Item candidate."

    grade_item_id: str
    status: AcademicPeriodProficiencyInputStatus
    contributed: bool
    result_reference: StandardProficiencyResultReference | None
    proficiency_level_id: str | None
    period_scope_mismatch_reason: AcademicPeriodScopeMismatchReason | None

    def __post_init__(self) -> None:
        grade_item_id = _identifier(self.grade_item_id, "grade_item_id")
        status = _input_status(self.status)
        if type(self.contributed) is not bool:
            raise AcademicPeriodProficiencyValidationError(
                "contributed must be a boolean."
            )
        reference = self.result_reference
        if reference is not None and not isinstance(
            reference,
            StandardProficiencyResultReference,
        ):
            raise AcademicPeriodProficiencyValidationError(
                "result_reference must be an exact #34 result reference or None."
            )
        if reference is not None and reference.grade_item_id != grade_item_id:
            raise AcademicPeriodProficiencyValidationError(
                "result_reference Grade Item must match the explanation Grade Item."
            )
        level_id = self.proficiency_level_id
        if level_id is not None:
            level_id = _identifier(level_id, "proficiency_level_id")
        mismatch = _optional_scope_mismatch_reason(
            self.period_scope_mismatch_reason
        )

        if status == "calculated":
            if reference is None or level_id is None or mismatch is not None:
                raise AcademicPeriodProficiencyValidationError(
                    "calculated explanation requires result provenance and one level."
                )
            if not self.contributed:
                raise AcademicPeriodProficiencyValidationError(
                    "calculated explanation must be contributing."
                )
        elif status == "insufficient_evidence":
            if reference is None or level_id is not None or mismatch is not None:
                raise AcademicPeriodProficiencyValidationError(
                    "insufficient explanation requires only exact result provenance."
                )
            if self.contributed:
                raise AcademicPeriodProficiencyValidationError(
                    "insufficient explanation must be noncontributing."
                )
        elif status == "missing_result":
            if reference is not None or level_id is not None or mismatch is not None:
                raise AcademicPeriodProficiencyValidationError(
                    "missing explanation must not carry result or mismatch data."
                )
            if self.contributed:
                raise AcademicPeriodProficiencyValidationError(
                    "missing explanation must be noncontributing."
                )
        else:
            if level_id is not None or mismatch is None:
                raise AcademicPeriodProficiencyValidationError(
                    "scope-mismatch explanation requires only its mismatch reason."
                )
            if self.contributed:
                raise AcademicPeriodProficiencyValidationError(
                    "scope-mismatch explanation must be noncontributing."
                )

        object.__setattr__(self, "grade_item_id", grade_item_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "proficiency_level_id", level_id)
        object.__setattr__(self, "period_scope_mismatch_reason", mismatch)


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyCalculationOutcome:
    "Pure deterministic Academic Period proficiency calculation outcome."

    algorithm_version: str
    status: AcademicPeriodProficiencyCalculationStatus
    proficiency_level_id: str | None
    aggregation_inputs_sha256: str
    calculation_fingerprint: str
    policy_reference: AcademicPeriodProficiencyAggregationPolicyReference
    target_period: AcademicPeriodProficiencyTarget
    target_scale: ProficiencyScaleReference
    candidate_count: int
    calculated_result_count: int
    insufficient_result_count: int
    missing_result_count: int
    period_scope_mismatch_count: int
    level_counts: tuple[StandardProficiencyLevelCount, ...]
    insufficiency_reasons: tuple[AcademicPeriodProficiencyInsufficiencyReason, ...]
    tie_resolution: StandardProficiencyTieResolution | None
    explanation_entries: tuple[AcademicPeriodProficiencyEntryExplanation, ...]

    def __post_init__(self) -> None:
        if self.algorithm_version != ACADEMIC_PERIOD_PROFICIENCY_ALGORITHM_VERSION:
            raise AcademicPeriodProficiencyValidationError(
                "unsupported Academic Period proficiency algorithm_version."
            )
        if self.status not in {"calculated", "insufficient_evidence"}:
            raise AcademicPeriodProficiencyValidationError(
                "unsupported Academic Period proficiency calculation status."
            )
        level_id = self.proficiency_level_id
        if level_id is not None:
            level_id = _identifier(level_id, "proficiency_level_id")
        inputs_sha256 = _sha256(
            self.aggregation_inputs_sha256,
            "aggregation_inputs_sha256",
        )
        fingerprint = _sha256(
            self.calculation_fingerprint,
            "calculation_fingerprint",
        )
        if not isinstance(
            self.policy_reference,
            AcademicPeriodProficiencyAggregationPolicyReference,
        ):
            raise AcademicPeriodProficiencyValidationError(
                "policy_reference must be exact #35 policy provenance."
            )
        if not isinstance(self.target_period, AcademicPeriodProficiencyTarget):
            raise AcademicPeriodProficiencyValidationError(
                "target_period must be an exact Academic Period target."
            )
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise AcademicPeriodProficiencyValidationError(
                "target_scale must be an exact proficiency scale reference."
            )
        if self.policy_reference.class_id != self.target_scale.class_id:
            raise AcademicPeriodProficiencyValidationError(
                "policy and target scale must use one class scope."
            )

        candidate_count = _nonnegative_int(self.candidate_count, "candidate_count")
        if candidate_count > MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_CANDIDATES:
            raise AcademicPeriodProficiencyValidationError(
                "outcome candidate_count exceeds the finite maximum."
            )
        calculated_count = _nonnegative_int(
            self.calculated_result_count,
            "calculated_result_count",
        )
        insufficient_count = _nonnegative_int(
            self.insufficient_result_count,
            "insufficient_result_count",
        )
        missing_count = _nonnegative_int(
            self.missing_result_count,
            "missing_result_count",
        )
        mismatch_count = _nonnegative_int(
            self.period_scope_mismatch_count,
            "period_scope_mismatch_count",
        )
        if (
            calculated_count
            + insufficient_count
            + missing_count
            + mismatch_count
            != candidate_count
        ):
            raise AcademicPeriodProficiencyValidationError(
                "outcome counts must cover every candidate exactly once."
            )

        level_counts = tuple(self.level_counts)
        if any(
            not isinstance(item, StandardProficiencyLevelCount)
            for item in level_counts
        ):
            raise AcademicPeriodProficiencyValidationError(
                "level_counts contains an invalid level count."
            )
        if len({item.proficiency_level_id for item in level_counts}) != len(
            level_counts
        ):
            raise AcademicPeriodProficiencyValidationError(
                "level_counts must not duplicate proficiency levels."
            )
        if sum(item.count for item in level_counts) != calculated_count:
            raise AcademicPeriodProficiencyValidationError(
                "level_counts must sum to calculated_result_count."
            )

        reasons = tuple(self.insufficiency_reasons)
        if any(
            not isinstance(item, AcademicPeriodProficiencyInsufficiencyReason)
            for item in reasons
        ):
            raise AcademicPeriodProficiencyValidationError(
                "insufficiency_reasons contains an invalid reason."
            )
        explanations = tuple(self.explanation_entries)
        if any(
            not isinstance(item, AcademicPeriodProficiencyEntryExplanation)
            for item in explanations
        ):
            raise AcademicPeriodProficiencyValidationError(
                "explanation_entries contains an invalid explanation."
            )
        if len(explanations) != candidate_count:
            raise AcademicPeriodProficiencyValidationError(
                "explanation_entries must cover every candidate exactly once."
            )
        explanation_ids = tuple(item.grade_item_id for item in explanations)
        if len(set(explanation_ids)) != len(explanation_ids):
            raise AcademicPeriodProficiencyValidationError(
                "explanation_entries must not duplicate Grade Item IDs."
            )
        if explanation_ids != tuple(sorted(explanation_ids)):
            raise AcademicPeriodProficiencyValidationError(
                "explanation_entries must use deterministic Grade Item ordering."
            )
        explanation_status_counts = Counter(
            item.status for item in explanations
        )
        if (
            explanation_status_counts.get("calculated", 0) != calculated_count
            or explanation_status_counts.get("insufficient_evidence", 0)
            != insufficient_count
            or explanation_status_counts.get("missing_result", 0) != missing_count
            or explanation_status_counts.get("period_scope_mismatch", 0)
            != mismatch_count
        ):
            raise AcademicPeriodProficiencyValidationError(
                "explanation statuses must match the declared outcome counts."
            )
        explanation_level_counts = Counter(
            item.proficiency_level_id
            for item in explanations
            if item.status == "calculated"
        )
        declared_level_counts = {
            item.proficiency_level_id: item.count
            for item in level_counts
            if item.count > 0
        }
        if dict(explanation_level_counts) != declared_level_counts:
            raise AcademicPeriodProficiencyValidationError(
                "level_counts must match contributing explanation levels."
            )
        for explanation in explanations:
            reference = explanation.result_reference
            if reference is not None and (
                reference.class_id != self.policy_reference.class_id
                or reference.grade_item_id != explanation.grade_item_id
            ):
                raise AcademicPeriodProficiencyValidationError(
                    "explanation result provenance must match outcome class and "
                    "Grade Item scope."
                )
        if self.tie_resolution is not None and not isinstance(
            self.tie_resolution,
            StandardProficiencyTieResolution,
        ):
            raise AcademicPeriodProficiencyValidationError(
                "tie_resolution has an invalid type."
            )
        if self.tie_resolution is not None:
            selected = self.tie_resolution.selected_level_id
            if selected is not None and selected != level_id:
                raise AcademicPeriodProficiencyValidationError(
                    "resolved tie must select the outcome proficiency level."
                )
            if selected is None and self.status != "insufficient_evidence":
                raise AcademicPeriodProficiencyValidationError(
                    "unresolved tie requires an insufficient outcome."
                )

        if self.status == "calculated":
            if level_id is None or reasons:
                raise AcademicPeriodProficiencyValidationError(
                    "calculated outcome requires one level and no "
                    "insufficiency reasons."
                )
        elif level_id is not None or not reasons:
            raise AcademicPeriodProficiencyValidationError(
                "insufficient outcome requires no level and at least one reason."
            )

        object.__setattr__(self, "proficiency_level_id", level_id)
        object.__setattr__(self, "aggregation_inputs_sha256", inputs_sha256)
        object.__setattr__(self, "calculation_fingerprint", fingerprint)
        object.__setattr__(self, "candidate_count", candidate_count)
        object.__setattr__(self, "calculated_result_count", calculated_count)
        object.__setattr__(self, "insufficient_result_count", insufficient_count)
        object.__setattr__(self, "missing_result_count", missing_count)
        object.__setattr__(self, "period_scope_mismatch_count", mismatch_count)
        object.__setattr__(self, "level_counts", level_counts)
        object.__setattr__(self, "insufficiency_reasons", reasons)
        object.__setattr__(self, "explanation_entries", explanations)


def is_academic_period_membership_scope(value: object) -> bool:
    "Return whether *value* is one exact #35 period-membership scope."
    return (
        isinstance(value, str)
        and value in _ACADEMIC_PERIOD_MEMBERSHIP_SCOPES
    )


def is_period_result_handling(value: object) -> bool:
    "Return whether *value* is one exact #35 missing/insufficient handling mode."
    return isinstance(value, str) and value in _PERIOD_RESULT_HANDLINGS


def validate_academic_period_proficiency_aggregation_policy(
    value: AcademicPeriodProficiencyAggregationPolicy,
) -> AcademicPeriodProficiencyAggregationPolicy:
    "Fully revalidate one immutable #35 aggregation-policy revision."
    if not isinstance(value, AcademicPeriodProficiencyAggregationPolicy):
        raise AcademicPeriodProficiencyValidationError(
            "value must be an AcademicPeriodProficiencyAggregationPolicy."
        )
    value.__post_init__()
    return value


def validate_academic_period_proficiency_aggregation_policy_transition(
    previous: AcademicPeriodProficiencyAggregationPolicy,
    current: AcademicPeriodProficiencyAggregationPolicy,
) -> AcademicPeriodProficiencyAggregationPolicy:
    "Validate one contiguous immutable policy-family transition."
    old = validate_academic_period_proficiency_aggregation_policy(previous)
    new = validate_academic_period_proficiency_aggregation_policy(current)

    if (old.class_id, old.policy_id) != (new.class_id, new.policy_id):
        raise AcademicPeriodProficiencyValidationError(
            "policy logical identity cannot change across revisions."
        )
    if new.policy_revision != old.policy_revision + 1:
        raise AcademicPeriodProficiencyValidationError(
            "policy revisions must be contiguous."
        )
    if new.supersedes_revision != old.policy_revision:
        raise AcademicPeriodProficiencyValidationError(
            "supersedes_revision must identify the prior policy revision."
        )
    if new.revised_at < old.revised_at:
        raise AcademicPeriodProficiencyValidationError(
            "revised_at must be nondecreasing across policy revisions."
        )
    return new


def academic_period_proficiency_aggregation_policy_reference(
    policy: AcademicPeriodProficiencyAggregationPolicy,
) -> AcademicPeriodProficiencyAggregationPolicyReference:
    "Return exact SHA-bound provenance for one immutable policy revision."
    value = validate_academic_period_proficiency_aggregation_policy(policy)
    return AcademicPeriodProficiencyAggregationPolicyReference(
        class_id=value.class_id,
        policy_id=value.policy_id,
        policy_revision=value.policy_revision,
        policy_sha256=academic_period_proficiency_aggregation_policy_sha256(
            value
        ),
    )


def academic_period_proficiency_aggregation_policy_to_dict(
    value: AcademicPeriodProficiencyAggregationPolicy,
) -> dict[str, object]:
    "Convert one policy revision to its exact JSON-native mapping."
    policy = validate_academic_period_proficiency_aggregation_policy(value)
    return {
        "schema_version": policy.schema_version,
        "record_type": policy.record_type,
        "class_id": policy.class_id,
        "policy_id": policy.policy_id,
        "policy_revision": policy.policy_revision,
        "supersedes_revision": policy.supersedes_revision,
        "title": policy.title,
        "target_scale": _scale_reference_to_dict(policy.target_scale),
        "strategy": policy.strategy,
        "period_membership_scope": policy.period_membership_scope,
        "minimum_calculated_results": policy.minimum_calculated_results,
        "mode_tie_rule": policy.mode_tie_rule,
        "median_even_rule": policy.median_even_rule,
        "missing_result_handling": policy.missing_result_handling,
        "insufficient_result_handling": policy.insufficient_result_handling,
        "actor": _actor_to_dict(policy.actor),
        "rationale": policy.rationale,
        "revised_at": policy.revised_at.isoformat(),
    }


def academic_period_proficiency_aggregation_policy_from_dict(
    data: object,
) -> AcademicPeriodProficiencyAggregationPolicy:
    "Parse one exact policy mapping."
    mapping = _exact_mapping(
        data,
        _POLICY_KEYS,
        "Academic Period proficiency aggregation policy",
    )
    supersedes = mapping["supersedes_revision"]
    if supersedes is not None and (
        isinstance(supersedes, bool) or not isinstance(supersedes, int)
    ):
        raise AcademicPeriodProficiencyValidationError(
            "supersedes_revision must be an integer or null."
        )

    return AcademicPeriodProficiencyAggregationPolicy(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_revision=_require_int(
            mapping["policy_revision"],
            "policy_revision",
        ),
        supersedes_revision=supersedes,
        title=_require_str(mapping["title"], "title"),
        target_scale=_scale_reference_from_dict(mapping["target_scale"]),
        strategy=_strategy(mapping["strategy"]),
        period_membership_scope=_period_membership_scope(
            mapping["period_membership_scope"]
        ),
        minimum_calculated_results=_require_int(
            mapping["minimum_calculated_results"],
            "minimum_calculated_results",
        ),
        mode_tie_rule=_optional_tie_rule(
            mapping["mode_tie_rule"],
            "mode_tie_rule",
        ),
        median_even_rule=_optional_tie_rule(
            mapping["median_even_rule"],
            "median_even_rule",
        ),
        missing_result_handling=_period_result_handling(
            mapping["missing_result_handling"],
            "missing_result_handling",
        ),
        insufficient_result_handling=_period_result_handling(
            mapping["insufficient_result_handling"],
            "insufficient_result_handling",
        ),
        actor=_actor_from_dict(mapping["actor"]),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        revised_at=_datetime_from_text(mapping["revised_at"], "revised_at"),
    )


def academic_period_proficiency_aggregation_policy_to_json_bytes(
    value: AcademicPeriodProficiencyAggregationPolicy,
) -> bytes:
    "Serialize one policy revision to stable canonical UTF-8 JSON bytes."
    return _canonical_json_bytes(
        academic_period_proficiency_aggregation_policy_to_dict(value)
    )


def academic_period_proficiency_aggregation_policy_from_json_bytes(
    payload: bytes,
) -> AcademicPeriodProficiencyAggregationPolicy:
    "Strictly parse one canonical policy JSON payload."
    parsed = _strict_json_object(
        payload,
        "Academic Period proficiency aggregation policy",
        MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_POLICY_BYTES,
    )
    value = academic_period_proficiency_aggregation_policy_from_dict(parsed)
    if academic_period_proficiency_aggregation_policy_to_json_bytes(value) != payload:
        raise AcademicPeriodProficiencySerializationError(
            "Academic Period proficiency aggregation policy is not canonical JSON."
        )
    return value


def academic_period_proficiency_aggregation_policy_sha256(
    value: AcademicPeriodProficiencyAggregationPolicy,
) -> str:
    "Return SHA-256 over the exact canonical policy JSON bytes."
    return hashlib.sha256(
        academic_period_proficiency_aggregation_policy_to_json_bytes(value)
    ).hexdigest()


def academic_period_proficiency_aggregation_policy_reference_to_dict(
    value: AcademicPeriodProficiencyAggregationPolicyReference,
) -> dict[str, object]:
    "Convert one exact policy reference to JSON-native data."
    if not isinstance(
        value,
        AcademicPeriodProficiencyAggregationPolicyReference,
    ):
        raise AcademicPeriodProficiencyValidationError(
            "value must be an AcademicPeriodProficiencyAggregationPolicyReference."
        )
    return {
        "class_id": value.class_id,
        "policy_id": value.policy_id,
        "policy_revision": value.policy_revision,
        "policy_sha256": value.policy_sha256,
    }


def academic_period_proficiency_aggregation_policy_reference_from_dict(
    data: object,
) -> AcademicPeriodProficiencyAggregationPolicyReference:
    "Parse one exact policy reference mapping."
    mapping = _exact_mapping(
        data,
        _POLICY_REFERENCE_KEYS,
        "Academic Period proficiency aggregation policy reference",
    )
    return AcademicPeriodProficiencyAggregationPolicyReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_revision=_require_int(
            mapping["policy_revision"],
            "policy_revision",
        ),
        policy_sha256=_require_str(mapping["policy_sha256"], "policy_sha256"),
    )




def academic_period_proficiency_membership_basis_from_decision(
    decision: GradeItemMembershipDecision,
    decision_sha256: str,
) -> AcademicPeriodProficiencyMembershipBasis:
    """Normalize one exact selected included #28 decision for pure #35 use."""

    if not isinstance(decision, GradeItemMembershipDecision):
        raise AcademicPeriodProficiencyValidationError(
            "decision must be a GradeItemMembershipDecision."
        )
    try:
        exact = validate_grade_item_membership_decision(decision)
    except GradeItemMembershipValidationError as error:
        raise AcademicPeriodProficiencyValidationError(
            f"membership decision is invalid: {error}"
        ) from error

    digest = _sha256(decision_sha256, "decision_sha256")
    exact_digest = hashlib.sha256(
        grade_item_membership_decision_to_json_bytes(exact)
    ).hexdigest()
    if digest != exact_digest:
        raise AcademicPeriodProficiencyValidationError(
            "decision_sha256 must match the exact canonical membership decision."
        )
    if exact.decision != "included" or exact.academic_period is None:
        raise AcademicPeriodProficiencyValidationError(
            "only an exact included #28 membership can form a #35 membership basis."
        )

    return AcademicPeriodProficiencyMembershipBasis(
        grade_item_id=exact.grade_item_id,
        grade_item_revision=exact.grade_item_revision,
        grade_item_revision_sha256=exact.grade_item_revision_sha256,
        work_reference=exact.work_reference,
        membership_revision=exact.membership_revision,
        membership_sha256=digest,
        academic_period=AcademicPeriodProficiencyTarget(
            exact.academic_period.period,
            exact.academic_period.calendar_revision,
        ),
    )


def build_academic_period_proficiency_aggregation_inputs(
    *,
    target_period: AcademicPeriodProficiencyTarget,
    calendar: AcademicPeriodCalendar,
    student_id: str,
    standard_id: str,
    target_scale: ProficiencyScaleReference,
    period_membership_scope: AcademicPeriodMembershipScope,
    candidates: Iterable[ResolvedAcademicPeriodProficiencyCandidate],
) -> AcademicPeriodProficiencyAggregationInputs:
    """Build exact bounded #35 inputs from membership bases and #34 snapshots."""

    if not isinstance(target_period, AcademicPeriodProficiencyTarget):
        raise AcademicPeriodProficiencyValidationError(
            "target_period must be an AcademicPeriodProficiencyTarget."
        )
    target = AcademicPeriodProficiencyTarget(
        target_period.period,
        target_period.calendar_revision,
    )
    if not isinstance(calendar, AcademicPeriodCalendar):
        raise AcademicPeriodProficiencyValidationError(
            "calendar must be an AcademicPeriodCalendar."
        )
    try:
        exact_calendar = validate_academic_period_calendar(calendar)
    except AcademicPeriodValidationError as error:
        raise AcademicPeriodProficiencyValidationError(
            f"calendar is invalid: {error}"
        ) from error

    validated_student_id = _identifier(student_id, "student_id")
    validated_standard_id = _standard_id(standard_id)
    if not isinstance(target_scale, ProficiencyScaleReference):
        raise AcademicPeriodProficiencyValidationError(
            "target_scale must be a ProficiencyScaleReference."
        )
    scope = _period_membership_scope(period_membership_scope)
    class_id = target_scale.class_id

    if exact_calendar.school_year != target.period.school_year:
        raise AcademicPeriodProficiencyValidationError(
            "target period school year must match the exact calendar revision."
        )
    if exact_calendar.calendar_revision != target.calendar_revision:
        raise AcademicPeriodProficiencyValidationError(
            "target calendar_revision must match the exact calendar revision."
        )

    if isinstance(candidates, (str, bytes)):
        raise AcademicPeriodProficiencyValidationError(
            "candidates must be an iterable of resolved Grade Item candidates."
        )
    try:
        raw_candidates = tuple(candidates)
    except TypeError as error:
        raise AcademicPeriodProficiencyValidationError(
            "candidates must be an iterable of resolved Grade Item candidates."
        ) from error
    if len(raw_candidates) > MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_CANDIDATES:
        raise AcademicPeriodProficiencyValidationError(
            "Academic Period proficiency candidate count exceeds the finite maximum."
        )
    if any(
        not isinstance(item, ResolvedAcademicPeriodProficiencyCandidate)
        for item in raw_candidates
    ):
        raise AcademicPeriodProficiencyValidationError(
            "candidates contains an invalid resolved Grade Item candidate."
        )

    grade_item_ids = tuple(
        candidate.grade_item.grade_item_id for candidate in raw_candidates
    )
    if len(set(grade_item_ids)) != len(grade_item_ids):
        raise AcademicPeriodProficiencyValidationError(
            "candidates must not duplicate a logical Grade Item."
        )

    entries: list[AcademicPeriodProficiencyAggregationInputEntry] = []
    for candidate in sorted(
        raw_candidates,
        key=lambda item: item.grade_item.grade_item_id,
    ):
        if candidate.grade_item.class_id != class_id:
            raise AcademicPeriodProficiencyValidationError(
                "candidate Grade Item class must match target_scale class_id."
            )

        result = candidate.result
        result_reference: StandardProficiencyResultReference | None = None
        result_algorithm_version: str | None = None
        result_calculation_fingerprint: str | None = None
        result_status: StandardProficiencyCalculationStatus | None = None
        proficiency_level_id: str | None = None
        result_insufficiency_reasons: tuple[
            StandardProficiencyInsufficiencyReason, ...
        ] = ()

        if result is not None:
            try:
                result_reference = standard_proficiency_result_reference(result)
            except ValueError as error:
                raise AcademicPeriodProficiencyValidationError(
                    f"#34 result snapshot is invalid: {error}"
                ) from error
            if (
                result.class_id != class_id
                or result.grade_item_id != candidate.grade_item.grade_item_id
                or result.inputs.grade_item != candidate.grade_item
            ):
                raise AcademicPeriodProficiencyValidationError(
                    "#34 result must match the exact candidate Grade Item basis."
                )
            if result.student_id != validated_student_id:
                raise AcademicPeriodProficiencyValidationError(
                    "#34 result student_id must match the target student."
                )
            if result.standard_id != validated_standard_id:
                raise AcademicPeriodProficiencyValidationError(
                    "#34 result standard_id must match the target standard."
                )
            if result.target_scale != target_scale:
                raise AcademicPeriodProficiencyValidationError(
                    "#34 result target_scale must match the exact #35 target scale."
                )

            result_algorithm_version = result.algorithm_version
            result_calculation_fingerprint = result.calculation_fingerprint
            result_status = result.outcome.status
            proficiency_level_id = result.outcome.proficiency_level_id
            result_insufficiency_reasons = result.outcome.insufficiency_reasons

        resolution = resolve_academic_period_proficiency_scope(
            target,
            exact_calendar,
            candidate.memberships,
            scope,
        )
        if resolution.status == "period_scope_mismatch":
            status: AcademicPeriodProficiencyInputStatus = "period_scope_mismatch"
            mismatch_reason = resolution.mismatch_reason
        elif result is None:
            status = "missing_result"
            mismatch_reason = None
        elif result.outcome.status == "calculated":
            status = "calculated"
            mismatch_reason = None
        else:
            status = "insufficient_evidence"
            mismatch_reason = None

        entries.append(
            AcademicPeriodProficiencyAggregationInputEntry(
                grade_item=candidate.grade_item,
                memberships=candidate.memberships,
                status=status,
                period_scope_mismatch_reason=mismatch_reason,
                result_reference=result_reference,
                result_algorithm_version=result_algorithm_version,
                result_calculation_fingerprint=result_calculation_fingerprint,
                result_status=result_status,
                proficiency_level_id=proficiency_level_id,
                result_insufficiency_reasons=result_insufficiency_reasons,
            )
        )

    return AcademicPeriodProficiencyAggregationInputs(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_INPUTS_RECORD_TYPE,
        class_id=class_id,
        target_period=target,
        student_id=validated_student_id,
        standard_id=validated_standard_id,
        target_scale=target_scale,
        period_membership_scope=scope,
        entries=tuple(entries),
    )



def resolve_academic_period_proficiency_scope(
    target_period: AcademicPeriodProficiencyTarget,
    calendar: AcademicPeriodCalendar,
    memberships: Iterable[AcademicPeriodProficiencyMembershipBasis],
    period_membership_scope: AcademicPeriodMembershipScope,
) -> AcademicPeriodProficiencyScopeResolution:
    "Purely classify one exact Grade Item membership basis for one period scope."

    if not isinstance(target_period, AcademicPeriodProficiencyTarget):
        raise AcademicPeriodProficiencyValidationError(
            "target_period must be an AcademicPeriodProficiencyTarget."
        )
    target = AcademicPeriodProficiencyTarget(
        target_period.period,
        target_period.calendar_revision,
    )
    if not isinstance(calendar, AcademicPeriodCalendar):
        raise AcademicPeriodProficiencyValidationError(
            "calendar must be an AcademicPeriodCalendar."
        )
    try:
        exact_calendar = validate_academic_period_calendar(calendar)
    except AcademicPeriodValidationError as error:
        raise AcademicPeriodProficiencyValidationError(
            f"calendar is invalid: {error}"
        ) from error
    scope = _period_membership_scope(period_membership_scope)

    if exact_calendar.school_year != target.period.school_year:
        raise AcademicPeriodProficiencyValidationError(
            "target period school year must match the exact calendar revision."
        )
    if exact_calendar.calendar_revision != target.calendar_revision:
        raise AcademicPeriodProficiencyValidationError(
            "target calendar_revision must match the exact calendar revision."
        )

    by_id = {period.period_id: period for period in exact_calendar.periods}
    if target.period.period_id not in by_id:
        raise AcademicPeriodProficiencyValidationError(
            "target period must exist in the exact calendar revision."
        )

    try:
        membership_values = tuple(memberships)
    except TypeError as error:
        raise AcademicPeriodProficiencyValidationError(
            "memberships must be an iterable of membership basis values."
        ) from error
    if not membership_values:
        raise AcademicPeriodProficiencyValidationError(
            "scope resolution requires at least one included membership basis."
        )
    if len(membership_values) > MAXIMUM_ACADEMIC_PERIOD_MEMBERSHIPS_PER_GRADE_ITEM:
        raise AcademicPeriodProficiencyValidationError(
            "membership basis count exceeds the finite maximum."
        )
    if any(
        not isinstance(item, AcademicPeriodProficiencyMembershipBasis)
        for item in membership_values
    ):
        raise AcademicPeriodProficiencyValidationError(
            "memberships contains an invalid membership basis."
        )

    if any(
        membership.academic_period.period.school_year
        != target.period.school_year
        for membership in membership_values
    ):
        return AcademicPeriodProficiencyScopeResolution(
            "period_scope_mismatch",
            "school_year_mismatch",
        )

    if any(
        membership.academic_period.calendar_revision
        != target.calendar_revision
        for membership in membership_values
    ):
        return AcademicPeriodProficiencyScopeResolution(
            "period_scope_mismatch",
            "calendar_revision_mismatch",
        )

    membership_period_ids = tuple(
        membership.academic_period.period.period_id
        for membership in membership_values
    )
    missing_period_ids = sorted(
        {period_id for period_id in membership_period_ids if period_id not in by_id}
    )
    if missing_period_ids:
        raise AcademicPeriodProficiencyValidationError(
            "membership basis references a period missing from the exact "
            "calendar revision: "
            + ", ".join(missing_period_ids)
            + "."
        )

    target_period_id = target.period.period_id
    if scope == "direct":
        eligible = all(
            period_id == target_period_id
            for period_id in membership_period_ids
        )
    else:
        eligible = all(
            _period_is_target_or_descendant(
                period_id,
                target_period_id,
                by_id,
            )
            for period_id in membership_period_ids
        )

    if eligible:
        return AcademicPeriodProficiencyScopeResolution("eligible", None)

    return AcademicPeriodProficiencyScopeResolution(
        "period_scope_mismatch",
        _period_scope_mismatch_reason(membership_period_ids, by_id),
    )


def _period_is_target_or_descendant(
    period_id: str,
    target_period_id: str,
    by_id: Mapping[str, AcademicPeriod],
) -> bool:
    current_id: str | None = period_id
    while current_id is not None:
        if current_id == target_period_id:
            return True
        current_id = by_id[current_id].parent_period_id
    return False


def _period_scope_mismatch_reason(
    period_ids: Iterable[str],
    by_id: Mapping[str, AcademicPeriod],
) -> AcademicPeriodScopeMismatchReason:
    distinct = tuple(sorted(set(period_ids)))
    if len(distinct) >= 2:
        parent_ids = {by_id[period_id].parent_period_id for period_id in distinct}
        if len(parent_ids) == 1:
            return "mixed_sibling_periods"
    return "outside_target_period"


def academic_period_proficiency_target_to_dict(
    value: AcademicPeriodProficiencyTarget,
) -> dict[str, object]:
    if not isinstance(value, AcademicPeriodProficiencyTarget):
        raise AcademicPeriodProficiencyValidationError(
            "value must be an AcademicPeriodProficiencyTarget."
        )
    return {
        "period": academic_period_ref_to_dict(value.period),
        "calendar_revision": value.calendar_revision,
    }


def academic_period_proficiency_target_from_dict(
    data: object,
) -> AcademicPeriodProficiencyTarget:
    mapping = _exact_mapping(
        data,
        _TARGET_PERIOD_KEYS,
        "Academic Period proficiency target",
    )
    try:
        period = academic_period_ref_from_dict(mapping["period"])
    except AcademicPeriodValidationError as error:
        raise AcademicPeriodProficiencyValidationError(
            f"target period is invalid: {error}"
        ) from error
    return AcademicPeriodProficiencyTarget(
        period=period,
        calendar_revision=_require_int(
            mapping["calendar_revision"],
            "calendar_revision",
        ),
    )


def academic_period_proficiency_membership_basis_to_dict(
    value: AcademicPeriodProficiencyMembershipBasis,
) -> dict[str, object]:
    if not isinstance(value, AcademicPeriodProficiencyMembershipBasis):
        raise AcademicPeriodProficiencyValidationError(
            "value must be an AcademicPeriodProficiencyMembershipBasis."
        )
    return {
        "grade_item_id": value.grade_item_id,
        "grade_item_revision": value.grade_item_revision,
        "grade_item_revision_sha256": value.grade_item_revision_sha256,
        "work_reference": grade_item_work_reference_to_dict(
            value.work_reference
        ),
        "membership_revision": value.membership_revision,
        "membership_sha256": value.membership_sha256,
        "academic_period": academic_period_proficiency_target_to_dict(
            value.academic_period
        ),
    }


def academic_period_proficiency_membership_basis_from_dict(
    data: object,
) -> AcademicPeriodProficiencyMembershipBasis:
    mapping = _exact_mapping(
        data,
        _MEMBERSHIP_BASIS_KEYS,
        "Academic Period proficiency membership basis",
    )
    try:
        work_reference = grade_item_work_reference_from_dict(
            mapping["work_reference"]
        )
    except GradeItemValidationError as error:
        raise AcademicPeriodProficiencyValidationError(
            f"membership work_reference is invalid: {error}"
        ) from error
    return AcademicPeriodProficiencyMembershipBasis(
        grade_item_id=_require_str(mapping["grade_item_id"], "grade_item_id"),
        grade_item_revision=_require_int(
            mapping["grade_item_revision"],
            "grade_item_revision",
        ),
        grade_item_revision_sha256=_require_str(
            mapping["grade_item_revision_sha256"],
            "grade_item_revision_sha256",
        ),
        work_reference=work_reference,
        membership_revision=_require_int(
            mapping["membership_revision"],
            "membership_revision",
        ),
        membership_sha256=_require_str(
            mapping["membership_sha256"],
            "membership_sha256",
        ),
        academic_period=academic_period_proficiency_target_from_dict(
            mapping["academic_period"]
        ),
    )


def academic_period_proficiency_aggregation_input_entry_to_dict(
    value: AcademicPeriodProficiencyAggregationInputEntry,
) -> dict[str, object]:
    if not isinstance(value, AcademicPeriodProficiencyAggregationInputEntry):
        raise AcademicPeriodProficiencyValidationError(
            "value must be an AcademicPeriodProficiencyAggregationInputEntry."
        )
    return {
        "grade_item": _grade_item_basis_to_dict(value.grade_item),
        "memberships": [
            academic_period_proficiency_membership_basis_to_dict(item)
            for item in value.memberships
        ],
        "status": value.status,
        "period_scope_mismatch_reason": value.period_scope_mismatch_reason,
        "result_reference": (
            standard_proficiency_result_reference_to_dict(value.result_reference)
            if value.result_reference is not None
            else None
        ),
        "result_algorithm_version": value.result_algorithm_version,
        "result_calculation_fingerprint": value.result_calculation_fingerprint,
        "result_status": value.result_status,
        "proficiency_level_id": value.proficiency_level_id,
        "result_insufficiency_reasons": [
            _insufficiency_reason_to_dict(item)
            for item in value.result_insufficiency_reasons
        ],
    }


def academic_period_proficiency_aggregation_input_entry_from_dict(
    data: object,
) -> AcademicPeriodProficiencyAggregationInputEntry:
    mapping = _exact_mapping(
        data,
        _INPUT_ENTRY_KEYS,
        "Academic Period proficiency input entry",
    )
    memberships_data = _require_list(mapping["memberships"], "memberships")
    reasons_data = _require_list(
        mapping["result_insufficiency_reasons"],
        "result_insufficiency_reasons",
    )
    reference_data = mapping["result_reference"]
    reference = (
        standard_proficiency_result_reference_from_dict(reference_data)
        if reference_data is not None
        else None
    )
    return AcademicPeriodProficiencyAggregationInputEntry(
        grade_item=_grade_item_basis_from_dict(mapping["grade_item"]),
        memberships=tuple(
            academic_period_proficiency_membership_basis_from_dict(item)
            for item in memberships_data
        ),
        status=_input_status(mapping["status"]),
        period_scope_mismatch_reason=_optional_scope_mismatch_reason(
            mapping["period_scope_mismatch_reason"]
        ),
        result_reference=reference,
        result_algorithm_version=_optional_str(
            mapping["result_algorithm_version"],
            "result_algorithm_version",
        ),
        result_calculation_fingerprint=_optional_str(
            mapping["result_calculation_fingerprint"],
            "result_calculation_fingerprint",
        ),
        result_status=_optional_result_status(mapping["result_status"]),
        proficiency_level_id=_optional_str(
            mapping["proficiency_level_id"],
            "proficiency_level_id",
        ),
        result_insufficiency_reasons=tuple(
            _insufficiency_reason_from_dict(item) for item in reasons_data
        ),
    )


def academic_period_proficiency_aggregation_inputs_to_dict(
    value: AcademicPeriodProficiencyAggregationInputs,
) -> dict[str, object]:
    if not isinstance(value, AcademicPeriodProficiencyAggregationInputs):
        raise AcademicPeriodProficiencyValidationError(
            "value must be an AcademicPeriodProficiencyAggregationInputs."
        )
    value.__post_init__()
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "class_id": value.class_id,
        "target_period": academic_period_proficiency_target_to_dict(
            value.target_period
        ),
        "student_id": value.student_id,
        "standard_id": value.standard_id,
        "target_scale": _scale_reference_to_dict(value.target_scale),
        "period_membership_scope": value.period_membership_scope,
        "entries": [
            academic_period_proficiency_aggregation_input_entry_to_dict(item)
            for item in value.entries
        ],
    }


def academic_period_proficiency_aggregation_inputs_from_dict(
    data: object,
) -> AcademicPeriodProficiencyAggregationInputs:
    mapping = _exact_mapping(
        data,
        _INPUTS_KEYS,
        "Academic Period proficiency aggregation inputs",
    )
    entries_data = _require_list(mapping["entries"], "entries")
    return AcademicPeriodProficiencyAggregationInputs(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        target_period=academic_period_proficiency_target_from_dict(
            mapping["target_period"]
        ),
        student_id=_require_str(mapping["student_id"], "student_id"),
        standard_id=_require_str(mapping["standard_id"], "standard_id"),
        target_scale=_scale_reference_from_dict(mapping["target_scale"]),
        period_membership_scope=_period_membership_scope(
            mapping["period_membership_scope"]
        ),
        entries=tuple(
            academic_period_proficiency_aggregation_input_entry_from_dict(item)
            for item in entries_data
        ),
    )


def academic_period_proficiency_aggregation_inputs_to_json_bytes(
    value: AcademicPeriodProficiencyAggregationInputs,
) -> bytes:
    return _canonical_json_bytes(
        academic_period_proficiency_aggregation_inputs_to_dict(value)
    )


def academic_period_proficiency_aggregation_inputs_from_json_bytes(
    payload: bytes,
) -> AcademicPeriodProficiencyAggregationInputs:
    parsed = _strict_json_object(
        payload,
        "Academic Period proficiency aggregation inputs",
        MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_INPUT_BYTES,
    )
    value = academic_period_proficiency_aggregation_inputs_from_dict(parsed)
    if academic_period_proficiency_aggregation_inputs_to_json_bytes(value) != payload:
        raise AcademicPeriodProficiencySerializationError(
            "Academic Period proficiency aggregation inputs are not canonical JSON."
        )
    return value


def academic_period_proficiency_aggregation_inputs_sha256(
    value: AcademicPeriodProficiencyAggregationInputs,
) -> str:
    return hashlib.sha256(
        academic_period_proficiency_aggregation_inputs_to_json_bytes(value)
    ).hexdigest()




@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyResultSnapshot:
    """Immutable persisted wrapper for one exact pure #35 calculation."""

    schema_version: str
    record_type: str
    class_id: str
    target_period: AcademicPeriodProficiencyTarget
    student_id: str
    standard_id: str
    result_revision: int
    supersedes_revision: int | None
    algorithm_version: str
    calculation_fingerprint: str
    inputs: AcademicPeriodProficiencyAggregationInputs
    inputs_sha256: str
    policy_reference: AcademicPeriodProficiencyAggregationPolicyReference
    target_scale: ProficiencyScaleReference
    outcome: AcademicPeriodProficiencyCalculationOutcome
    calculated_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != ACADEMIC_PERIOD_PROFICIENCY_RESULT_SCHEMA_VERSION:
            raise AcademicPeriodProficiencyValidationError(
                "unsupported Academic Period proficiency result schema_version."
            )
        if self.record_type != ACADEMIC_PERIOD_PROFICIENCY_RESULT_RECORD_TYPE:
            raise AcademicPeriodProficiencyValidationError(
                "record_type must identify an Academic Period proficiency result."
            )

        class_id = _identifier(self.class_id, "class_id")
        if not isinstance(self.target_period, AcademicPeriodProficiencyTarget):
            raise AcademicPeriodProficiencyValidationError(
                "target_period must be an AcademicPeriodProficiencyTarget."
            )
        target_period = AcademicPeriodProficiencyTarget(
            self.target_period.period,
            self.target_period.calendar_revision,
        )
        student_id = _identifier(self.student_id, "student_id")
        standard_id = _standard_id(self.standard_id)
        revision = _positive_int(self.result_revision, "result_revision")
        supersedes = _optional_positive_int(
            self.supersedes_revision,
            "supersedes_revision",
        )
        if revision == 1 and supersedes is not None:
            raise AcademicPeriodProficiencyValidationError(
                "result revision 1 must not supersede a prior revision."
            )
        if revision > 1 and supersedes != revision - 1:
            raise AcademicPeriodProficiencyValidationError(
                "result supersedes_revision must identify the immediately "
                "prior revision."
            )
        if self.algorithm_version != ACADEMIC_PERIOD_PROFICIENCY_ALGORITHM_VERSION:
            raise AcademicPeriodProficiencyValidationError(
                "unsupported Academic Period proficiency result algorithm_version."
            )
        fingerprint = _sha256(
            self.calculation_fingerprint,
            "calculation_fingerprint",
        )

        if not isinstance(self.inputs, AcademicPeriodProficiencyAggregationInputs):
            raise AcademicPeriodProficiencyValidationError(
                "inputs must be AcademicPeriodProficiencyAggregationInputs."
            )
        self.inputs.__post_init__()
        inputs_sha256 = _sha256(self.inputs_sha256, "inputs_sha256")
        exact_inputs_sha256 = academic_period_proficiency_aggregation_inputs_sha256(
            self.inputs
        )
        if inputs_sha256 != exact_inputs_sha256:
            raise AcademicPeriodProficiencyValidationError(
                "inputs_sha256 must match the exact embedded #35 aggregation inputs."
            )
        if (
            self.inputs.class_id != class_id
            or self.inputs.target_period != target_period
            or self.inputs.student_id != student_id
            or self.inputs.standard_id != standard_id
        ):
            raise AcademicPeriodProficiencyValidationError(
                "result scope must match the exact embedded #35 aggregation inputs."
            )

        if not isinstance(
            self.policy_reference,
            AcademicPeriodProficiencyAggregationPolicyReference,
        ):
            raise AcademicPeriodProficiencyValidationError(
                "policy_reference must be exact #35 policy provenance."
            )
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise AcademicPeriodProficiencyValidationError(
                "target_scale must be an exact proficiency-scale reference."
            )
        if self.target_scale != self.inputs.target_scale:
            raise AcademicPeriodProficiencyValidationError(
                "result target_scale must match the embedded #35 inputs."
            )
        if self.policy_reference.class_id != class_id:
            raise AcademicPeriodProficiencyValidationError(
                "result policy_reference must match the result class scope."
            )
        if not isinstance(self.outcome, AcademicPeriodProficiencyCalculationOutcome):
            raise AcademicPeriodProficiencyValidationError(
                "outcome must be an AcademicPeriodProficiencyCalculationOutcome."
            )
        if (
            self.outcome.algorithm_version != self.algorithm_version
            or self.outcome.calculation_fingerprint != fingerprint
            or self.outcome.aggregation_inputs_sha256 != inputs_sha256
            or self.outcome.policy_reference != self.policy_reference
            or self.outcome.target_period != target_period
            or self.outcome.target_scale != self.target_scale
        ):
            raise AcademicPeriodProficiencyValidationError(
                "result metadata must match the exact pure #35 calculation outcome."
            )

        calculated_at = _aware_utc_datetime(
            self.calculated_at,
            "calculated_at",
        )
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "target_period", target_period)
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "standard_id", standard_id)
        object.__setattr__(self, "result_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "calculation_fingerprint", fingerprint)
        object.__setattr__(self, "inputs_sha256", inputs_sha256)
        object.__setattr__(self, "calculated_at", calculated_at)


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyResultReference:
    """Exact immutable #35 result revision and digest."""

    class_id: str
    school_year: str
    period_id: str
    student_id: str
    standard_id: str
    result_revision: int
    result_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "class_id",
            _identifier(self.class_id, "class_id"),
        )
        if not isinstance(self.school_year, str) or not isinstance(
            self.period_id,
            str,
        ):
            raise AcademicPeriodProficiencyValidationError(
                "school_year and period_id must be strings."
            )
        try:
            period = validate_academic_period_ref(
                AcademicPeriodRef(self.school_year, self.period_id)
            )
        except AcademicPeriodValidationError as error:
            raise AcademicPeriodProficiencyValidationError(
                f"result reference Academic Period is invalid: {error}"
            ) from error
        object.__setattr__(self, "school_year", period.school_year)
        object.__setattr__(self, "period_id", period.period_id)
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        object.__setattr__(self, "standard_id", _standard_id(self.standard_id))
        object.__setattr__(
            self,
            "result_revision",
            _positive_int(self.result_revision, "result_revision"),
        )
        object.__setattr__(
            self,
            "result_sha256",
            _sha256(self.result_sha256, "result_sha256"),
        )


@dataclass(frozen=True, slots=True)
class AcademicPeriodProficiencyResultFreshness:
    """Pure diagnostic comparison of one persisted #35 result to current basis."""

    status: AcademicPeriodProficiencyFreshnessStatus
    reasons: tuple[AcademicPeriodProficiencyStalenessReason, ...]

    def __post_init__(self) -> None:
        if self.status not in {"current", "stale"}:
            raise AcademicPeriodProficiencyValidationError(
                "unsupported Academic Period proficiency freshness status."
            )
        reasons = _academic_period_staleness_reasons(self.reasons)
        if self.status == "current" and reasons:
            raise AcademicPeriodProficiencyValidationError(
                "current freshness status requires no staleness reasons."
            )
        if self.status == "stale" and not reasons:
            raise AcademicPeriodProficiencyValidationError(
                "stale freshness status requires at least one reason."
            )
        object.__setattr__(self, "reasons", reasons)


def academic_period_proficiency_calculation_fingerprint(
    inputs: AcademicPeriodProficiencyAggregationInputs,
    policy: AcademicPeriodProficiencyAggregationPolicy,
    scale: ProficiencyScale,
) -> str:
    "Return a stable digest over the exact pure #35 calculation basis."

    scale_reference, policy_reference = _validate_academic_period_calculation_basis(
        inputs,
        policy,
        scale,
    )
    return _academic_period_calculation_fingerprint_from_references(
        inputs.sha256,
        policy_reference,
        inputs.target_period,
        scale_reference,
    )


def calculate_academic_period_proficiency(
    inputs: AcademicPeriodProficiencyAggregationInputs,
    policy: AcademicPeriodProficiencyAggregationPolicy,
    scale: ProficiencyScale,
) -> AcademicPeriodProficiencyCalculationOutcome:
    "Purely calculate one class/period/student/standard proficiency outcome."

    scale_reference, policy_reference = _validate_academic_period_calculation_basis(
        inputs,
        policy,
        scale,
    )
    positions = {level.level_id: level.position for level in scale.levels}
    ordered_level_ids = tuple(level.level_id for level in scale.levels)

    calculated_level_ids: list[str] = []
    explanation_entries: list[AcademicPeriodProficiencyEntryExplanation] = []
    mismatch_ids: list[str] = []
    blocking_missing_ids: list[str] = []
    blocking_insufficient_ids: list[str] = []
    insufficient_count = 0
    missing_count = 0
    mismatch_count = 0

    for entry in inputs.entries:
        grade_item_id = entry.grade_item.grade_item_id
        if entry.status == "calculated":
            level_id = entry.proficiency_level_id
            if level_id is None or level_id not in positions:
                raise AcademicPeriodProficiencyValidationError(
                    "calculated #34 result references a level outside the exact "
                    "target scale."
                )
            calculated_level_ids.append(level_id)
            explanation_entries.append(
                AcademicPeriodProficiencyEntryExplanation(
                    grade_item_id,
                    "calculated",
                    True,
                    entry.result_reference,
                    level_id,
                    None,
                )
            )
        elif entry.status == "insufficient_evidence":
            insufficient_count += 1
            explanation_entries.append(
                AcademicPeriodProficiencyEntryExplanation(
                    grade_item_id,
                    "insufficient_evidence",
                    False,
                    entry.result_reference,
                    None,
                    None,
                )
            )
            if policy.insufficient_result_handling == "blocking":
                blocking_insufficient_ids.append(grade_item_id)
        elif entry.status == "missing_result":
            missing_count += 1
            explanation_entries.append(
                AcademicPeriodProficiencyEntryExplanation(
                    grade_item_id,
                    "missing_result",
                    False,
                    None,
                    None,
                    None,
                )
            )
            if policy.missing_result_handling == "blocking":
                blocking_missing_ids.append(grade_item_id)
        else:
            mismatch_count += 1
            mismatch = entry.period_scope_mismatch_reason
            if mismatch is None:
                raise AcademicPeriodProficiencyValidationError(
                    "period_scope_mismatch input is missing its exact reason."
                )
            mismatch_ids.append(grade_item_id)
            explanation_entries.append(
                AcademicPeriodProficiencyEntryExplanation(
                    grade_item_id,
                    "period_scope_mismatch",
                    False,
                    entry.result_reference,
                    None,
                    mismatch,
                )
            )

    calculated_count = len(calculated_level_ids)
    counts = Counter(calculated_level_ids)
    level_counts = tuple(
        StandardProficiencyLevelCount(level_id, counts.get(level_id, 0))
        for level_id in ordered_level_ids
    )

    reasons: list[AcademicPeriodProficiencyInsufficiencyReason] = []
    if mismatch_ids:
        reasons.append(
            AcademicPeriodProficiencyInsufficiencyReason(
                "period_scope_mismatch",
                tuple(mismatch_ids),
            )
        )
    if blocking_missing_ids:
        reasons.append(
            AcademicPeriodProficiencyInsufficiencyReason(
                "blocking_missing_result",
                tuple(blocking_missing_ids),
            )
        )
    if blocking_insufficient_ids:
        reasons.append(
            AcademicPeriodProficiencyInsufficiencyReason(
                "blocking_insufficient_result",
                tuple(blocking_insufficient_ids),
            )
        )
    if calculated_count == 0:
        reasons.append(
            AcademicPeriodProficiencyInsufficiencyReason(
                "no_calculated_results",
                actual_results=0,
            )
        )
    elif calculated_count < policy.minimum_calculated_results:
        reasons.append(
            AcademicPeriodProficiencyInsufficiencyReason(
                "below_minimum_calculated_results",
                required_results=policy.minimum_calculated_results,
                actual_results=calculated_count,
            )
        )

    fingerprint = _academic_period_calculation_fingerprint_from_references(
        inputs.sha256,
        policy_reference,
        inputs.target_period,
        scale_reference,
    )
    selected_level_id: str | None = None
    tie_resolution: StandardProficiencyTieResolution | None = None

    if not reasons:
        (
            selected_level_id,
            tie_resolution,
            strategy_reason,
        ) = _apply_academic_period_proficiency_strategy(
            calculated_level_ids,
            positions,
            policy,
        )
        if strategy_reason is not None:
            reasons.append(strategy_reason)

    status: AcademicPeriodProficiencyCalculationStatus
    if reasons:
        status = "insufficient_evidence"
        selected_level_id = None
    else:
        status = "calculated"

    return AcademicPeriodProficiencyCalculationOutcome(
        algorithm_version=ACADEMIC_PERIOD_PROFICIENCY_ALGORITHM_VERSION,
        status=status,
        proficiency_level_id=selected_level_id,
        aggregation_inputs_sha256=inputs.sha256,
        calculation_fingerprint=fingerprint,
        policy_reference=policy_reference,
        target_period=inputs.target_period,
        target_scale=scale_reference,
        candidate_count=len(inputs.entries),
        calculated_result_count=calculated_count,
        insufficient_result_count=insufficient_count,
        missing_result_count=missing_count,
        period_scope_mismatch_count=mismatch_count,
        level_counts=level_counts,
        insufficiency_reasons=tuple(reasons),
        tie_resolution=tie_resolution,
        explanation_entries=tuple(explanation_entries),
    )



def create_academic_period_proficiency_result_snapshot(
    inputs: AcademicPeriodProficiencyAggregationInputs,
    outcome: AcademicPeriodProficiencyCalculationOutcome,
    *,
    result_revision: int,
    calculated_at: datetime,
) -> AcademicPeriodProficiencyResultSnapshot:
    """Wrap one already-pure #35 outcome in immutable result metadata."""

    if not isinstance(inputs, AcademicPeriodProficiencyAggregationInputs):
        raise AcademicPeriodProficiencyValidationError(
            "inputs must be AcademicPeriodProficiencyAggregationInputs."
        )
    if not isinstance(outcome, AcademicPeriodProficiencyCalculationOutcome):
        raise AcademicPeriodProficiencyValidationError(
            "outcome must be an AcademicPeriodProficiencyCalculationOutcome."
        )
    revision = _positive_int(result_revision, "result_revision")
    return AcademicPeriodProficiencyResultSnapshot(
        schema_version=ACADEMIC_PERIOD_PROFICIENCY_RESULT_SCHEMA_VERSION,
        record_type=ACADEMIC_PERIOD_PROFICIENCY_RESULT_RECORD_TYPE,
        class_id=inputs.class_id,
        target_period=inputs.target_period,
        student_id=inputs.student_id,
        standard_id=inputs.standard_id,
        result_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        algorithm_version=outcome.algorithm_version,
        calculation_fingerprint=outcome.calculation_fingerprint,
        inputs=inputs,
        inputs_sha256=academic_period_proficiency_aggregation_inputs_sha256(inputs),
        policy_reference=outcome.policy_reference,
        target_scale=outcome.target_scale,
        outcome=outcome,
        calculated_at=calculated_at,
    )


def validate_academic_period_proficiency_result_transition(
    previous: AcademicPeriodProficiencyResultSnapshot,
    current: AcademicPeriodProficiencyResultSnapshot,
) -> AcademicPeriodProficiencyResultSnapshot:
    """Validate one contiguous revision transition in a durable period family."""

    if not isinstance(previous, AcademicPeriodProficiencyResultSnapshot):
        raise AcademicPeriodProficiencyValidationError(
            "previous must be an AcademicPeriodProficiencyResultSnapshot."
        )
    if not isinstance(current, AcademicPeriodProficiencyResultSnapshot):
        raise AcademicPeriodProficiencyValidationError(
            "current must be an AcademicPeriodProficiencyResultSnapshot."
        )
    previous.__post_init__()
    current.__post_init__()
    previous_scope = (
        previous.class_id,
        previous.target_period.period.school_year,
        previous.target_period.period.period_id,
        previous.student_id,
        previous.standard_id,
    )
    current_scope = (
        current.class_id,
        current.target_period.period.school_year,
        current.target_period.period.period_id,
        current.student_id,
        current.standard_id,
    )
    if current_scope != previous_scope:
        raise AcademicPeriodProficiencyValidationError(
            "Academic Period proficiency result logical identity cannot change "
            "across revisions."
        )
    if current.result_revision != previous.result_revision + 1:
        raise AcademicPeriodProficiencyValidationError(
            "Academic Period proficiency result revisions must be contiguous."
        )
    if current.supersedes_revision != previous.result_revision:
        raise AcademicPeriodProficiencyValidationError(
            "result supersedes_revision must identify the prior revision."
        )
    return current


def academic_period_proficiency_result_snapshot_to_dict(
    value: AcademicPeriodProficiencyResultSnapshot,
) -> dict[str, object]:
    if not isinstance(value, AcademicPeriodProficiencyResultSnapshot):
        raise AcademicPeriodProficiencyValidationError(
            "value must be an AcademicPeriodProficiencyResultSnapshot."
        )
    value.__post_init__()
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "class_id": value.class_id,
        "target_period": academic_period_proficiency_target_to_dict(
            value.target_period
        ),
        "student_id": value.student_id,
        "standard_id": value.standard_id,
        "result_revision": value.result_revision,
        "supersedes_revision": value.supersedes_revision,
        "algorithm_version": value.algorithm_version,
        "calculation_fingerprint": value.calculation_fingerprint,
        "inputs": academic_period_proficiency_aggregation_inputs_to_dict(
            value.inputs
        ),
        "inputs_sha256": value.inputs_sha256,
        "policy_reference": (
            academic_period_proficiency_aggregation_policy_reference_to_dict(
                value.policy_reference
            )
        ),
        "target_scale": _scale_reference_to_dict(value.target_scale),
        "outcome": academic_period_proficiency_calculation_outcome_to_dict(
            value.outcome
        ),
        "calculated_at": value.calculated_at.isoformat(),
    }


def academic_period_proficiency_result_snapshot_from_dict(
    data: object,
) -> AcademicPeriodProficiencyResultSnapshot:
    mapping = _exact_mapping(
        data,
        _ACADEMIC_PERIOD_RESULT_KEYS,
        "Academic Period proficiency result snapshot",
    )
    return AcademicPeriodProficiencyResultSnapshot(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        target_period=academic_period_proficiency_target_from_dict(
            mapping["target_period"]
        ),
        student_id=_require_str(mapping["student_id"], "student_id"),
        standard_id=_require_str(mapping["standard_id"], "standard_id"),
        result_revision=_require_int(
            mapping["result_revision"],
            "result_revision",
        ),
        supersedes_revision=_optional_int(
            mapping["supersedes_revision"],
            "supersedes_revision",
        ),
        algorithm_version=_require_str(
            mapping["algorithm_version"],
            "algorithm_version",
        ),
        calculation_fingerprint=_require_str(
            mapping["calculation_fingerprint"],
            "calculation_fingerprint",
        ),
        inputs=academic_period_proficiency_aggregation_inputs_from_dict(
            mapping["inputs"]
        ),
        inputs_sha256=_require_str(mapping["inputs_sha256"], "inputs_sha256"),
        policy_reference=(
            academic_period_proficiency_aggregation_policy_reference_from_dict(
                mapping["policy_reference"]
            )
        ),
        target_scale=_scale_reference_from_dict(mapping["target_scale"]),
        outcome=academic_period_proficiency_calculation_outcome_from_dict(
            mapping["outcome"]
        ),
        calculated_at=_datetime_from_text(
            mapping["calculated_at"],
            "calculated_at",
        ),
    )


def academic_period_proficiency_result_snapshot_to_json_bytes(
    value: AcademicPeriodProficiencyResultSnapshot,
) -> bytes:
    return _canonical_json_bytes(
        academic_period_proficiency_result_snapshot_to_dict(value)
    )


def academic_period_proficiency_result_snapshot_from_json_bytes(
    payload: bytes,
) -> AcademicPeriodProficiencyResultSnapshot:
    parsed = _strict_json_object(
        payload,
        "Academic Period proficiency result snapshot",
        MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_RESULT_BYTES,
    )
    value = academic_period_proficiency_result_snapshot_from_dict(parsed)
    if academic_period_proficiency_result_snapshot_to_json_bytes(value) != payload:
        raise AcademicPeriodProficiencySerializationError(
            "Academic Period proficiency result snapshot is not canonical JSON."
        )
    return value


def academic_period_proficiency_result_reference(
    value: AcademicPeriodProficiencyResultSnapshot,
) -> AcademicPeriodProficiencyResultReference:
    if not isinstance(value, AcademicPeriodProficiencyResultSnapshot):
        raise AcademicPeriodProficiencyValidationError(
            "value must be an AcademicPeriodProficiencyResultSnapshot."
        )
    content = academic_period_proficiency_result_snapshot_to_json_bytes(value)
    return AcademicPeriodProficiencyResultReference(
        class_id=value.class_id,
        school_year=value.target_period.period.school_year,
        period_id=value.target_period.period.period_id,
        student_id=value.student_id,
        standard_id=value.standard_id,
        result_revision=value.result_revision,
        result_sha256=hashlib.sha256(content).hexdigest(),
    )


def academic_period_proficiency_result_reference_to_dict(
    value: AcademicPeriodProficiencyResultReference,
) -> dict[str, object]:
    if not isinstance(value, AcademicPeriodProficiencyResultReference):
        raise AcademicPeriodProficiencyValidationError(
            "value must be an AcademicPeriodProficiencyResultReference."
        )
    return {
        "class_id": value.class_id,
        "school_year": value.school_year,
        "period_id": value.period_id,
        "student_id": value.student_id,
        "standard_id": value.standard_id,
        "result_revision": value.result_revision,
        "result_sha256": value.result_sha256,
    }


def academic_period_proficiency_result_reference_from_dict(
    data: object,
) -> AcademicPeriodProficiencyResultReference:
    mapping = _exact_mapping(
        data,
        _ACADEMIC_PERIOD_RESULT_REFERENCE_KEYS,
        "Academic Period proficiency result reference",
    )
    return AcademicPeriodProficiencyResultReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        school_year=_require_str(mapping["school_year"], "school_year"),
        period_id=_require_str(mapping["period_id"], "period_id"),
        student_id=_require_str(mapping["student_id"], "student_id"),
        standard_id=_require_str(mapping["standard_id"], "standard_id"),
        result_revision=_require_int(
            mapping["result_revision"],
            "result_revision",
        ),
        result_sha256=_require_str(mapping["result_sha256"], "result_sha256"),
    )


def assess_academic_period_proficiency_result_freshness(
    result: AcademicPeriodProficiencyResultSnapshot,
    current_inputs: AcademicPeriodProficiencyAggregationInputs,
    current_policy_reference: AcademicPeriodProficiencyAggregationPolicyReference,
    current_scale_reference: ProficiencyScaleReference,
    current_calendar_revision: int,
    algorithm_version: str,
) -> AcademicPeriodProficiencyResultFreshness:
    """Compare one immutable #35 result against explicit current dependencies."""

    if not isinstance(result, AcademicPeriodProficiencyResultSnapshot):
        raise AcademicPeriodProficiencyValidationError(
            "result must be an AcademicPeriodProficiencyResultSnapshot."
        )
    result.__post_init__()
    if not isinstance(current_inputs, AcademicPeriodProficiencyAggregationInputs):
        raise AcademicPeriodProficiencyValidationError(
            "current_inputs must be AcademicPeriodProficiencyAggregationInputs."
        )
    current_inputs.__post_init__()
    if not isinstance(
        current_policy_reference,
        AcademicPeriodProficiencyAggregationPolicyReference,
    ):
        raise AcademicPeriodProficiencyValidationError(
            "current_policy_reference must be an exact #35 policy reference."
        )
    if not isinstance(current_scale_reference, ProficiencyScaleReference):
        raise AcademicPeriodProficiencyValidationError(
            "current_scale_reference must be an exact proficiency-scale reference."
        )
    calendar_revision = _positive_int(
        current_calendar_revision,
        "current_calendar_revision",
    )
    current_algorithm = _bounded_text(
        algorithm_version,
        "algorithm_version",
        256,
    )

    current_scope = (
        current_inputs.class_id,
        current_inputs.target_period.period.school_year,
        current_inputs.target_period.period.period_id,
        current_inputs.student_id,
        current_inputs.standard_id,
    )
    result_scope = (
        result.class_id,
        result.target_period.period.school_year,
        result.target_period.period.period_id,
        result.student_id,
        result.standard_id,
    )
    if current_scope != result_scope:
        raise AcademicPeriodProficiencyValidationError(
            "freshness comparison must preserve the result logical identity."
        )
    if current_policy_reference.class_id != result.class_id:
        raise AcademicPeriodProficiencyValidationError(
            "current policy reference must match the result class."
        )
    if current_scale_reference.class_id != result.class_id:
        raise AcademicPeriodProficiencyValidationError(
            "current scale reference must match the result class."
        )

    reasons: list[AcademicPeriodProficiencyStalenessReason] = []
    if current_inputs.sha256 != result.inputs_sha256:
        reasons.append("inputs_changed")
    if current_policy_reference != result.policy_reference:
        reasons.append("policy_changed")
    if current_scale_reference != result.target_scale:
        reasons.append("scale_changed")
    if calendar_revision != result.target_period.calendar_revision:
        reasons.append("calendar_changed")
    if current_algorithm != result.algorithm_version:
        reasons.append("algorithm_changed")

    return AcademicPeriodProficiencyResultFreshness(
        status="current" if not reasons else "stale",
        reasons=tuple(reasons),
    )


def academic_period_proficiency_calculation_outcome_to_dict(
    value: AcademicPeriodProficiencyCalculationOutcome,
) -> dict[str, object]:
    if not isinstance(value, AcademicPeriodProficiencyCalculationOutcome):
        raise AcademicPeriodProficiencyValidationError(
            "value must be an AcademicPeriodProficiencyCalculationOutcome."
        )
    value.__post_init__()
    return {
        "algorithm_version": value.algorithm_version,
        "status": value.status,
        "proficiency_level_id": value.proficiency_level_id,
        "aggregation_inputs_sha256": value.aggregation_inputs_sha256,
        "calculation_fingerprint": value.calculation_fingerprint,
        "policy_reference": (
            academic_period_proficiency_aggregation_policy_reference_to_dict(
                value.policy_reference
            )
        ),
        "target_period": academic_period_proficiency_target_to_dict(
            value.target_period
        ),
        "target_scale": _scale_reference_to_dict(value.target_scale),
        "candidate_count": value.candidate_count,
        "calculated_result_count": value.calculated_result_count,
        "insufficient_result_count": value.insufficient_result_count,
        "missing_result_count": value.missing_result_count,
        "period_scope_mismatch_count": value.period_scope_mismatch_count,
        "level_counts": [
            {
                "proficiency_level_id": item.proficiency_level_id,
                "count": item.count,
            }
            for item in value.level_counts
        ],
        "insufficiency_reasons": [
            _academic_period_insufficiency_reason_to_dict(item)
            for item in value.insufficiency_reasons
        ],
        "tie_resolution": (
            None
            if value.tie_resolution is None
            else {
                "kind": value.tie_resolution.kind,
                "rule": value.tie_resolution.rule,
                "candidate_level_ids": list(
                    value.tie_resolution.candidate_level_ids
                ),
                "selected_level_id": value.tie_resolution.selected_level_id,
            }
        ),
        "explanation_entries": [
            _academic_period_explanation_entry_to_dict(item)
            for item in value.explanation_entries
        ],
    }


def academic_period_proficiency_calculation_outcome_from_dict(
    data: object,
) -> AcademicPeriodProficiencyCalculationOutcome:
    mapping = _exact_mapping(
        data,
        _ACADEMIC_PERIOD_OUTCOME_KEYS,
        "Academic Period proficiency calculation outcome",
    )
    tie_data = mapping["tie_resolution"]
    tie_resolution: StandardProficiencyTieResolution | None = None
    if tie_data is not None:
        tie = _exact_mapping(
            tie_data,
            _ACADEMIC_PERIOD_TIE_RESOLUTION_KEYS,
            "Academic Period proficiency tie resolution",
        )
        tie_resolution = StandardProficiencyTieResolution(
            _tie_kind(tie["kind"]),
            _tie_rule(tie["rule"]),
            tuple(
                _require_str(item, "candidate_level_id")
                for item in _require_list(
                    tie["candidate_level_ids"],
                    "candidate_level_ids",
                )
            ),
            _optional_str(tie["selected_level_id"], "selected_level_id"),
        )

    return AcademicPeriodProficiencyCalculationOutcome(
        algorithm_version=_require_str(
            mapping["algorithm_version"],
            "algorithm_version",
        ),
        status=_academic_period_calculation_status(mapping["status"]),
        proficiency_level_id=_optional_str(
            mapping["proficiency_level_id"],
            "proficiency_level_id",
        ),
        aggregation_inputs_sha256=_require_str(
            mapping["aggregation_inputs_sha256"],
            "aggregation_inputs_sha256",
        ),
        calculation_fingerprint=_require_str(
            mapping["calculation_fingerprint"],
            "calculation_fingerprint",
        ),
        policy_reference=(
            academic_period_proficiency_aggregation_policy_reference_from_dict(
                mapping["policy_reference"]
            )
        ),
        target_period=academic_period_proficiency_target_from_dict(
            mapping["target_period"]
        ),
        target_scale=_scale_reference_from_dict(mapping["target_scale"]),
        candidate_count=_require_int(mapping["candidate_count"], "candidate_count"),
        calculated_result_count=_require_int(
            mapping["calculated_result_count"],
            "calculated_result_count",
        ),
        insufficient_result_count=_require_int(
            mapping["insufficient_result_count"],
            "insufficient_result_count",
        ),
        missing_result_count=_require_int(
            mapping["missing_result_count"],
            "missing_result_count",
        ),
        period_scope_mismatch_count=_require_int(
            mapping["period_scope_mismatch_count"],
            "period_scope_mismatch_count",
        ),
        level_counts=tuple(
            _academic_period_level_count_from_dict(item)
            for item in _require_list(mapping["level_counts"], "level_counts")
        ),
        insufficiency_reasons=tuple(
            _academic_period_insufficiency_reason_from_dict(item)
            for item in _require_list(
                mapping["insufficiency_reasons"],
                "insufficiency_reasons",
            )
        ),
        tie_resolution=tie_resolution,
        explanation_entries=tuple(
            _academic_period_explanation_entry_from_dict(item)
            for item in _require_list(
                mapping["explanation_entries"],
                "explanation_entries",
            )
        ),
    )


def academic_period_proficiency_calculation_outcome_to_json_bytes(
    value: AcademicPeriodProficiencyCalculationOutcome,
) -> bytes:
    return _canonical_json_bytes(
        academic_period_proficiency_calculation_outcome_to_dict(value)
    )


def academic_period_proficiency_calculation_outcome_from_json_bytes(
    payload: bytes,
) -> AcademicPeriodProficiencyCalculationOutcome:
    parsed = _strict_json_object(
        payload,
        "Academic Period proficiency calculation outcome",
        MAXIMUM_ACADEMIC_PERIOD_PROFICIENCY_OUTCOME_BYTES,
    )
    value = academic_period_proficiency_calculation_outcome_from_dict(parsed)
    if academic_period_proficiency_calculation_outcome_to_json_bytes(value) != payload:
        raise AcademicPeriodProficiencySerializationError(
            "Academic Period proficiency calculation outcome is not canonical JSON."
        )
    return value


def _validate_academic_period_calculation_basis(
    inputs: AcademicPeriodProficiencyAggregationInputs,
    policy: AcademicPeriodProficiencyAggregationPolicy,
    scale: ProficiencyScale,
) -> tuple[
    ProficiencyScaleReference,
    AcademicPeriodProficiencyAggregationPolicyReference,
]:
    if not isinstance(inputs, AcademicPeriodProficiencyAggregationInputs):
        raise AcademicPeriodProficiencyValidationError(
            "inputs must be AcademicPeriodProficiencyAggregationInputs."
        )
    inputs.__post_init__()
    validate_academic_period_proficiency_aggregation_policy(policy)
    validate_proficiency_scale(scale)

    scale_reference = proficiency_scale_reference(scale)
    if inputs.target_scale != scale_reference:
        raise AcademicPeriodProficiencyValidationError(
            "aggregation inputs do not bind this exact proficiency-scale revision."
        )
    if policy.target_scale != scale_reference:
        raise AcademicPeriodProficiencyValidationError(
            "aggregation policy does not bind this exact proficiency-scale revision."
        )
    if policy.class_id != inputs.class_id:
        raise AcademicPeriodProficiencyValidationError(
            "aggregation policy class must match the input class scope."
        )
    if policy.period_membership_scope != inputs.period_membership_scope:
        raise AcademicPeriodProficiencyValidationError(
            "aggregation policy period_membership_scope must match the exact "
            "scope used to build the aggregation inputs."
        )
    return (
        scale_reference,
        academic_period_proficiency_aggregation_policy_reference(policy),
    )


def _academic_period_calculation_fingerprint_from_references(
    aggregation_inputs_sha256: str,
    policy_reference: AcademicPeriodProficiencyAggregationPolicyReference,
    target_period: AcademicPeriodProficiencyTarget,
    scale_reference: ProficiencyScaleReference,
) -> str:
    payload = {
        "algorithm_version": ACADEMIC_PERIOD_PROFICIENCY_ALGORITHM_VERSION,
        "aggregation_inputs_sha256": _sha256(
            aggregation_inputs_sha256,
            "aggregation_inputs_sha256",
        ),
        "policy_reference": (
            academic_period_proficiency_aggregation_policy_reference_to_dict(
                policy_reference
            )
        ),
        "target_period": academic_period_proficiency_target_to_dict(target_period),
        "target_scale": _scale_reference_to_dict(scale_reference),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _apply_academic_period_proficiency_strategy(
    calculated_level_ids: list[str],
    positions: dict[str, int],
    policy: AcademicPeriodProficiencyAggregationPolicy,
) -> tuple[
    str | None,
    StandardProficiencyTieResolution | None,
    AcademicPeriodProficiencyInsufficiencyReason | None,
]:
    if not calculated_level_ids:
        raise AcademicPeriodProficiencyValidationError(
            "strategy execution requires calculated Grade Item results."
        )
    ordered = sorted(calculated_level_ids, key=positions.__getitem__)
    if policy.strategy == "highest":
        return ordered[-1], None, None
    if policy.strategy == "lowest":
        return ordered[0], None, None
    if policy.strategy == "median":
        return _apply_academic_period_median_strategy(ordered, policy)
    return _apply_academic_period_mode_strategy(calculated_level_ids, positions, policy)


def _apply_academic_period_median_strategy(
    ordered: list[str],
    policy: AcademicPeriodProficiencyAggregationPolicy,
) -> tuple[
    str | None,
    StandardProficiencyTieResolution | None,
    AcademicPeriodProficiencyInsufficiencyReason | None,
]:
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle], None, None

    lower = ordered[middle - 1]
    higher = ordered[middle]
    rule = policy.median_even_rule
    if rule is None:
        raise AcademicPeriodProficiencyValidationError(
            "median strategy is missing median_even_rule."
        )
    candidates = (lower, higher)
    if rule == "lower":
        selected = lower
        reason = None
    elif rule == "higher":
        selected = higher
        reason = None
    else:
        selected = None
        reason = AcademicPeriodProficiencyInsufficiencyReason(
            "unresolved_even_median"
        )
    return (
        selected,
        StandardProficiencyTieResolution(
            "median_even",
            rule,
            candidates,
            selected,
        ),
        reason,
    )


def _apply_academic_period_mode_strategy(
    calculated_level_ids: list[str],
    positions: dict[str, int],
    policy: AcademicPeriodProficiencyAggregationPolicy,
) -> tuple[
    str | None,
    StandardProficiencyTieResolution | None,
    AcademicPeriodProficiencyInsufficiencyReason | None,
]:
    counts = Counter(calculated_level_ids)
    maximum = max(counts.values())
    candidates = tuple(
        sorted(
            (
                level_id
                for level_id, count in counts.items()
                if count == maximum
            ),
            key=positions.__getitem__,
        )
    )
    if len(candidates) == 1:
        return candidates[0], None, None

    rule = policy.mode_tie_rule
    if rule is None:
        raise AcademicPeriodProficiencyValidationError(
            "mode strategy is missing mode_tie_rule."
        )
    if rule == "lower":
        selected = candidates[0]
        reason = None
    elif rule == "higher":
        selected = candidates[-1]
        reason = None
    else:
        selected = None
        reason = AcademicPeriodProficiencyInsufficiencyReason(
            "unresolved_mode_tie"
        )
    return (
        selected,
        StandardProficiencyTieResolution(
            "mode_tie",
            rule,
            candidates,
            selected,
        ),
        reason,
    )


def _academic_period_insufficiency_reason_to_dict(
    value: AcademicPeriodProficiencyInsufficiencyReason,
) -> dict[str, object]:
    return {
        "kind": value.kind,
        "grade_item_ids": list(value.grade_item_ids),
        "required_results": value.required_results,
        "actual_results": value.actual_results,
    }


def _academic_period_insufficiency_reason_from_dict(
    data: object,
) -> AcademicPeriodProficiencyInsufficiencyReason:
    mapping = _exact_mapping(
        data,
        _ACADEMIC_PERIOD_INSUFFICIENCY_REASON_KEYS,
        "Academic Period proficiency insufficiency reason",
    )
    return AcademicPeriodProficiencyInsufficiencyReason(
        kind=_academic_period_insufficiency_kind(mapping["kind"]),
        grade_item_ids=tuple(
            _require_str(item, "grade_item_id")
            for item in _require_list(mapping["grade_item_ids"], "grade_item_ids")
        ),
        required_results=_optional_int(
            mapping["required_results"],
            "required_results",
        ),
        actual_results=_optional_int(
            mapping["actual_results"],
            "actual_results",
        ),
    )


def _academic_period_explanation_entry_to_dict(
    value: AcademicPeriodProficiencyEntryExplanation,
) -> dict[str, object]:
    return {
        "grade_item_id": value.grade_item_id,
        "status": value.status,
        "contributed": value.contributed,
        "result_reference": (
            None
            if value.result_reference is None
            else standard_proficiency_result_reference_to_dict(
                value.result_reference
            )
        ),
        "proficiency_level_id": value.proficiency_level_id,
        "period_scope_mismatch_reason": value.period_scope_mismatch_reason,
    }


def _academic_period_explanation_entry_from_dict(
    data: object,
) -> AcademicPeriodProficiencyEntryExplanation:
    mapping = _exact_mapping(
        data,
        _ACADEMIC_PERIOD_EXPLANATION_ENTRY_KEYS,
        "Academic Period proficiency explanation entry",
    )
    reference_data = mapping["result_reference"]
    reference = (
        None
        if reference_data is None
        else standard_proficiency_result_reference_from_dict(reference_data)
    )
    return AcademicPeriodProficiencyEntryExplanation(
        grade_item_id=_require_str(mapping["grade_item_id"], "grade_item_id"),
        status=_input_status(mapping["status"]),
        contributed=_require_bool(mapping["contributed"], "contributed"),
        result_reference=reference,
        proficiency_level_id=_optional_str(
            mapping["proficiency_level_id"],
            "proficiency_level_id",
        ),
        period_scope_mismatch_reason=_optional_scope_mismatch_reason(
            mapping["period_scope_mismatch_reason"]
        ),
    )


def _academic_period_level_count_from_dict(
    data: object,
) -> StandardProficiencyLevelCount:
    mapping = _exact_mapping(
        data,
        _ACADEMIC_PERIOD_LEVEL_COUNT_KEYS,
        "Academic Period proficiency level count",
    )
    return StandardProficiencyLevelCount(
        _require_str(mapping["proficiency_level_id"], "proficiency_level_id"),
        _require_int(mapping["count"], "count"),
    )


def _grade_item_basis_to_dict(
    value: GradeItemAggregationBasis,
) -> dict[str, object]:
    if not isinstance(value, GradeItemAggregationBasis):
        raise AcademicPeriodProficiencyValidationError(
            "grade_item must be a GradeItemAggregationBasis."
        )
    return {
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "grade_item_revision": value.grade_item_revision,
        "grade_item_revision_sha256": value.grade_item_revision_sha256,
    }


def _grade_item_basis_from_dict(data: object) -> GradeItemAggregationBasis:
    mapping = _exact_mapping(data, _GRADE_ITEM_BASIS_KEYS, "Grade Item basis")
    try:
        return GradeItemAggregationBasis(
            class_id=_require_str(mapping["class_id"], "grade_item.class_id"),
            grade_item_id=_require_str(
                mapping["grade_item_id"],
                "grade_item.grade_item_id",
            ),
            grade_item_revision=_require_int(
                mapping["grade_item_revision"],
                "grade_item.grade_item_revision",
            ),
            grade_item_revision_sha256=_require_str(
                mapping["grade_item_revision_sha256"],
                "grade_item.grade_item_revision_sha256",
            ),
        )
    except StandardsEvidenceValidationError as error:
        raise AcademicPeriodProficiencyValidationError(
            f"Grade Item basis is invalid: {error}"
        ) from error


def _insufficiency_reason_to_dict(
    value: StandardProficiencyInsufficiencyReason,
) -> dict[str, object]:
    if not isinstance(value, StandardProficiencyInsufficiencyReason):
        raise AcademicPeriodProficiencyValidationError(
            "invalid #34 insufficiency reason."
        )
    return {
        "kind": value.kind,
        "source_keys": list(value.source_keys),
        "required_observations": value.required_observations,
        "actual_observations": value.actual_observations,
    }


def _insufficiency_reason_from_dict(
    data: object,
) -> StandardProficiencyInsufficiencyReason:
    mapping = _exact_mapping(
        data,
        _INSUFFICIENCY_REASON_KEYS,
        "#34 insufficiency reason",
    )
    return StandardProficiencyInsufficiencyReason(
        kind=cast(
            StandardProficiencyInsufficiencyKind,
            _require_str(mapping["kind"], "result_insufficiency_reason.kind"),
        ),
        source_keys=tuple(
            _require_str(item, "source_key")
            for item in _require_list(mapping["source_keys"], "source_keys")
        ),
        required_observations=_optional_int(
            mapping["required_observations"],
            "required_observations",
        ),
        actual_observations=_optional_int(
            mapping["actual_observations"],
            "actual_observations",
        ),
    )


def _input_status(value: object) -> AcademicPeriodProficiencyInputStatus:
    if not isinstance(value, str) or value not in _INPUT_STATUSES:
        raise AcademicPeriodProficiencyValidationError(
            "unsupported Academic Period proficiency input status."
        )
    return cast(AcademicPeriodProficiencyInputStatus, value)


def _optional_scope_mismatch_reason(
    value: object,
) -> AcademicPeriodScopeMismatchReason | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in _SCOPE_MISMATCH_REASONS:
        raise AcademicPeriodProficiencyValidationError(
            "unsupported period scope mismatch reason."
        )
    return cast(AcademicPeriodScopeMismatchReason, value)


def _optional_result_status(
    value: object,
) -> StandardProficiencyCalculationStatus | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in {
        "calculated",
        "insufficient_evidence",
    }:
        raise AcademicPeriodProficiencyValidationError(
            "unsupported #34 result status."
        )
    return cast(StandardProficiencyCalculationStatus, value)



def _academic_period_calculation_status(
    value: object,
) -> AcademicPeriodProficiencyCalculationStatus:
    if not isinstance(value, str) or value not in _CALCULATION_STATUSES:
        raise AcademicPeriodProficiencyValidationError(
            "unsupported Academic Period proficiency calculation status."
        )
    return value


def _academic_period_insufficiency_kind(
    value: object,
) -> AcademicPeriodProficiencyInsufficiencyKind:
    if (
        not isinstance(value, str)
        or value not in _ACADEMIC_PERIOD_INSUFFICIENCY_KINDS
    ):
        raise AcademicPeriodProficiencyValidationError(
            "unsupported Academic Period proficiency insufficiency reason."
        )
    return value


def _tie_kind(value: object) -> Literal["mode_tie", "median_even"]:
    if not isinstance(value, str) or value not in _TIE_KINDS:
        raise AcademicPeriodProficiencyValidationError(
            "unsupported Academic Period proficiency tie kind."
        )
    return value


def _tie_rule(value: object) -> Literal["lower", "higher", "insufficient"]:
    if not isinstance(value, str) or value not in _TIE_RULES:
        raise AcademicPeriodProficiencyValidationError(
            "unsupported Academic Period proficiency tie rule."
        )
    return value



def _validate_result_membership_provenance(
    memberships: tuple[AcademicPeriodProficiencyMembershipBasis, ...],
    result: StandardProficiencyResultSnapshot,
) -> None:
    """Reject #34 membership references that disagree with the #35 basis."""

    by_work = {
        (
            membership.work_reference.work.module_id,
            membership.work_reference.work.work_id,
        ): membership
        for membership in memberships
    }
    for entry in result.inputs.entries:
        reference = entry.membership_reference
        if reference is None:
            continue
        key = (entry.source.work.module_id, entry.source.work.work_id)
        membership = by_work.get(key)
        if membership is None:
            raise AcademicPeriodProficiencyValidationError(
                "#34 result membership provenance references work absent from "
                "the exact #35 membership basis."
            )
        if (
            reference.revision != membership.membership_revision
            or reference.decision_sha256 != membership.membership_sha256
        ):
            raise AcademicPeriodProficiencyValidationError(
                "#34 result membership provenance must match the exact #35 "
                "membership revision and digest."
            )


def _validated_memberships_for_grade_item(
    values: object,
    grade_item: GradeItemAggregationBasis,
) -> tuple[AcademicPeriodProficiencyMembershipBasis, ...]:
    if isinstance(values, (str, bytes)):
        raise AcademicPeriodProficiencyValidationError(
            "memberships must be an iterable of membership bases."
        )
    try:
        memberships = tuple(cast(Iterable[object], values))
    except TypeError as error:
        raise AcademicPeriodProficiencyValidationError(
            "memberships must be an iterable of membership bases."
        ) from error
    if not memberships:
        raise AcademicPeriodProficiencyValidationError(
            "each Academic Period candidate requires at least one included "
            "membership basis."
        )
    if len(memberships) > MAXIMUM_ACADEMIC_PERIOD_MEMBERSHIPS_PER_GRADE_ITEM:
        raise AcademicPeriodProficiencyValidationError(
            "membership basis count exceeds the finite maximum."
        )
    if any(
        not isinstance(item, AcademicPeriodProficiencyMembershipBasis)
        for item in memberships
    ):
        raise AcademicPeriodProficiencyValidationError(
            "memberships contains an invalid membership basis."
        )
    typed = cast(tuple[AcademicPeriodProficiencyMembershipBasis, ...], memberships)
    membership_keys = tuple(
        (
            item.work_reference.work.module_id,
            item.work_reference.work.work_id,
        )
        for item in typed
    )
    if len(set(membership_keys)) != len(membership_keys):
        raise AcademicPeriodProficiencyValidationError(
            "memberships must not duplicate a logical work relationship."
        )
    if membership_keys != tuple(sorted(membership_keys)):
        raise AcademicPeriodProficiencyValidationError(
            "memberships must use deterministic module/work ordering."
        )
    for membership in typed:
        if (
            membership.work_reference.work.class_id != grade_item.class_id
            or membership.grade_item_id != grade_item.grade_item_id
            or membership.grade_item_revision != grade_item.grade_item_revision
            or membership.grade_item_revision_sha256
            != grade_item.grade_item_revision_sha256
        ):
            raise AcademicPeriodProficiencyValidationError(
                "membership basis must match the exact Grade Item basis."
            )
    return typed



def _strategy(value: object) -> StandardProficiencyStrategy:
    if not isinstance(value, str) or value not in _STRATEGIES:
        raise AcademicPeriodProficiencyValidationError(
            "strategy must be one of: highest, lowest, median, mode."
        )
    return value


def _period_membership_scope(value: object) -> AcademicPeriodMembershipScope:
    if not is_academic_period_membership_scope(value):
        raise AcademicPeriodProficiencyValidationError(
            "period_membership_scope must be one of: descendants, direct."
        )
    return cast(AcademicPeriodMembershipScope, value)


def _period_result_handling(
    value: object,
    field_name: str,
) -> PeriodResultHandling:
    if not is_period_result_handling(value):
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be one of: blocking, noncontributing."
        )
    return cast(PeriodResultHandling, value)


def _optional_tie_rule(
    value: object,
    field_name: str,
) -> Literal["lower", "higher", "insufficient"] | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in _TIE_RULES:
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be lower, higher, insufficient, or null."
        )
    return value


def _validate_revision_pair(
    revision: int,
    supersedes_revision: int | None,
) -> None:
    if revision == 1 and supersedes_revision is not None:
        raise AcademicPeriodProficiencyValidationError(
            "policy revision 1 must not supersede a prior revision."
        )
    if revision > 1 and supersedes_revision != revision - 1:
        raise AcademicPeriodProficiencyValidationError(
            "supersedes_revision must identify the immediately prior revision."
        )


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise AcademicPeriodProficiencyValidationError(str(error)) from error



def _standard_id(value: object) -> str:
    try:
        return normalize_standard_id(value)
    except StandardsEvidenceValidationError as error:
        raise AcademicPeriodProficiencyValidationError(str(error)) from error


def _nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be a nonnegative integer."
        )
    return value


def _optional_nonnegative_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _nonnegative_int(value, field_name)


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _optional_positive_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be a string."
        )
    if not value or value != value.strip():
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be nonblank with no surrounding whitespace."
        )
    if len(value) > maximum:
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} exceeds the maximum length of {maximum}."
        )
    if any(
        character in "\r\n\0"
        or unicodedata.category(character) == "Cc"
        for character in value
    ):
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be single-line text without control characters."
        )
    return value


def _optional_bounded_text(
    value: object,
    field_name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    return _bounded_text(value, field_name, maximum)


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be a datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _academic_period_staleness_reasons(
    values: object,
) -> tuple[AcademicPeriodProficiencyStalenessReason, ...]:
    if isinstance(values, (str, bytes)):
        raise AcademicPeriodProficiencyValidationError(
            "freshness reasons must be an iterable."
        )
    try:
        raw = tuple(cast(Iterable[object], values))
    except TypeError as error:
        raise AcademicPeriodProficiencyValidationError(
            "freshness reasons must be an iterable."
        ) from error
    if any(not isinstance(value, str) for value in raw):
        raise AcademicPeriodProficiencyValidationError(
            "freshness reasons must contain strings."
        )
    if len(set(raw)) != len(raw):
        raise AcademicPeriodProficiencyValidationError(
            "freshness reasons must not contain duplicates."
        )
    invalid = sorted(
        set(cast(tuple[str, ...], raw))
        - _ACADEMIC_PERIOD_STALENESS_REASON_SET
    )
    if invalid:
        raise AcademicPeriodProficiencyValidationError(
            f"unsupported freshness reasons: {invalid!r}."
        )
    selected = set(cast(tuple[str, ...], raw))
    return tuple(
        reason
        for reason in _ACADEMIC_PERIOD_STALENESS_REASON_ORDER
        if reason in selected
    )



def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _scale_reference_to_dict(
    value: ProficiencyScaleReference,
) -> dict[str, object]:
    if not isinstance(value, ProficiencyScaleReference):
        raise AcademicPeriodProficiencyValidationError(
            "target_scale must be a ProficiencyScaleReference."
        )
    return {
        "class_id": value.class_id,
        "scale_id": value.scale_id,
        "scale_revision": value.scale_revision,
        "scale_sha256": value.scale_sha256,
    }


def _scale_reference_from_dict(data: object) -> ProficiencyScaleReference:
    mapping = _exact_mapping(
        data,
        _SCALE_REFERENCE_KEYS,
        "proficiency scale reference",
    )
    return ProficiencyScaleReference(
        class_id=_require_str(mapping["class_id"], "target_scale.class_id"),
        scale_id=_require_str(mapping["scale_id"], "target_scale.scale_id"),
        scale_revision=_require_int(
            mapping["scale_revision"],
            "target_scale.scale_revision",
        ),
        scale_sha256=_require_str(
            mapping["scale_sha256"],
            "target_scale.scale_sha256",
        ),
    )


def _actor_to_dict(value: StandardProficiencyActor) -> dict[str, object]:
    if not isinstance(value, StandardProficiencyActor):
        raise AcademicPeriodProficiencyValidationError(
            "actor must be a StandardProficiencyActor."
        )
    return {"kind": value.kind, "actor_id": value.actor_id}


def _actor_from_dict(data: object) -> StandardProficiencyActor:
    mapping = _exact_mapping(data, _ACTOR_KEYS, "actor")
    kind = _require_str(mapping["kind"], "actor.kind")
    if kind not in {"teacher", "policy"}:
        raise AcademicPeriodProficiencyValidationError(
            "actor.kind must be one of: policy, teacher."
        )
    return StandardProficiencyActor(
        cast(Literal["teacher", "policy"], kind),
        _require_str(mapping["actor_id"], "actor.actor_id"),
    )


def _exact_mapping(
    data: object,
    expected_keys: frozenset[str],
    label: str,
) -> Mapping[str, object]:
    if not isinstance(data, Mapping):
        raise AcademicPeriodProficiencyValidationError(
            f"{label} must be an object."
        )
    if any(not isinstance(key, str) for key in data):
        raise AcademicPeriodProficiencyValidationError(
            f"{label} keys must be strings."
        )
    actual = frozenset(cast(str, key) for key in data)
    if actual != expected_keys:
        missing = sorted(expected_keys - actual)
        unknown = sorted(actual - expected_keys)
        details: list[str] = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise AcademicPeriodProficiencyValidationError(
            f"{label} has an invalid shape ({'; '.join(details)})."
        )
    return cast(Mapping[str, object], data)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be a string."
        )
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be a boolean."
        )
    return value


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be an integer."
        )
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be a list."
        )
    return value


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise AcademicPeriodProficiencyValidationError(
            f"{field_name} must be an ISO 8601 datetime."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _canonical_json_bytes(data: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _strict_json_object(
    payload: bytes,
    label: str,
    maximum_bytes: int,
) -> Mapping[str, object]:
    if not isinstance(payload, bytes):
        raise AcademicPeriodProficiencySerializationError(
            f"{label} payload must be bytes."
        )
    if len(payload) > maximum_bytes:
        raise AcademicPeriodProficiencySerializationError(
            f"{label} payload exceeds the maximum size."
        )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AcademicPeriodProficiencySerializationError(
            f"{label} payload must be UTF-8."
        ) from error

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_pairs,
            parse_constant=_reject_json_constant,
        )
    except (
        json.JSONDecodeError,
        AcademicPeriodProficiencySerializationError,
    ) as error:
        if isinstance(error, AcademicPeriodProficiencySerializationError):
            raise
        raise AcademicPeriodProficiencySerializationError(
            f"{label} payload is invalid JSON."
        ) from error

    if not isinstance(parsed, Mapping):
        raise AcademicPeriodProficiencySerializationError(
            f"{label} payload must contain a JSON object."
        )
    return cast(Mapping[str, object], parsed)


def _reject_duplicate_object_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AcademicPeriodProficiencySerializationError(
                f"duplicate JSON object key: {key!r}."
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise AcademicPeriodProficiencySerializationError(
        f"non-standard JSON numeric constant is not permitted: {value}."
    )
