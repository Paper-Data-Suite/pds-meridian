"Pure domain contracts for standards-proficiency calculation policy."

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypeAlias, TypeVar, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.evidence_eligibility import evidence_source_key
from meridian.proficiency_mapping import (
    ProficiencyScale,
    ProficiencyScaleReference,
    proficiency_scale_reference,
    validate_proficiency_scale,
)
from meridian.standards_evidence import (
    StandardAggregationExclusionReason,
    StandardAggregationInputs,
    standard_aggregation_inputs_from_dict,
    standard_aggregation_inputs_sha256,
    standard_aggregation_inputs_to_dict,
)

STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION: Final[str] = "1"
STANDARD_PROFICIENCY_POLICY_RECORD_TYPE: Final[str] = (
    "meridian_standard_proficiency_calculation_policy"
)
STANDARD_PROFICIENCY_ALGORITHM_VERSION: Final[str] = "1"
STANDARD_PROFICIENCY_RESULT_SCHEMA_VERSION: Final[str] = "1"
STANDARD_PROFICIENCY_RESULT_RECORD_TYPE: Final[str] = (
    "meridian_standard_proficiency_result"
)

MAXIMUM_STANDARD_PROFICIENCY_TITLE_LENGTH: Final[int] = 256
MAXIMUM_STANDARD_PROFICIENCY_TEXT_LENGTH: Final[int] = 2000
MAXIMUM_STANDARD_PROFICIENCY_ACTOR_ID_LENGTH: Final[int] = 256
MAXIMUM_STANDARD_PROFICIENCY_OBSERVATIONS: Final[int] = 1000

StandardProficiencyStrategy: TypeAlias = Literal[
    "highest",
    "lowest",
    "median",
    "mode",
]
ModeTieRule: TypeAlias = Literal["lower", "higher", "insufficient"]
MedianEvenRule: TypeAlias = Literal["lower", "higher", "insufficient"]
NativeStateHandling: TypeAlias = Literal["noncontributing", "blocking"]
StandardProficiencyActorKind: TypeAlias = Literal["teacher", "policy"]
StandardProficiencyBlockingExclusionReason: TypeAlias = Literal[
    "association_unresolved",
    "eligibility_unresolved",
    "attempt_selection_unresolved",
    "reassessment_unresolved",
    "mapping_not_supplied",
    "mapping_unmapped",
    "mapping_unsupported",
    "scale_mismatch",
    "source_unverifiable",
    "standard_unresolved",
]

StandardProficiencyCalculationStatus: TypeAlias = Literal[
    "calculated",
    "insufficient_evidence",
]
StandardProficiencyInsufficiencyKind: TypeAlias = Literal[
    "no_performance_evidence",
    "below_minimum_performance_observations",
    "blocking_exclusion",
    "blocking_native_state",
    "unresolved_mode_tie",
    "unresolved_even_median",
]
StandardProficiencyExplanationStatus: TypeAlias = Literal[
    "performance",
    "native_state",
    "excluded",
]
StandardProficiencyTieKind: TypeAlias = Literal["mode_tie", "median_even"]

StandardProficiencyFreshnessStatus: TypeAlias = Literal["current", "stale"]
StandardProficiencyStalenessReason: TypeAlias = Literal[
    "inputs_changed",
    "policy_changed",
    "scale_changed",
    "algorithm_changed",
]

_STRATEGIES: Final[tuple[StandardProficiencyStrategy, ...]] = (
    "highest",
    "lowest",
    "median",
    "mode",
)
_TIE_RULES: Final[tuple[ModeTieRule, ...]] = (
    "lower",
    "higher",
    "insufficient",
)
_BLOCKING_EXCLUSION_REASONS: Final[
    tuple[StandardProficiencyBlockingExclusionReason, ...]
] = (
    "association_unresolved",
    "eligibility_unresolved",
    "attempt_selection_unresolved",
    "reassessment_unresolved",
    "mapping_not_supplied",
    "mapping_unmapped",
    "mapping_unsupported",
    "scale_mismatch",
    "source_unverifiable",
    "standard_unresolved",
)
_BLOCKING_EXCLUSION_SET: Final[frozenset[str]] = frozenset(
    _BLOCKING_EXCLUSION_REASONS
)
_STALENESS_REASON_ORDER: Final[
    tuple[StandardProficiencyStalenessReason, ...]
] = (
    "inputs_changed",
    "policy_changed",
    "scale_changed",
    "algorithm_changed",
)
_STALENESS_REASON_SET: Final[frozenset[str]] = frozenset(
    _STALENESS_REASON_ORDER
)
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")

_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})
_SCALE_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "scale_id", "scale_revision", "scale_sha256"}
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
        "minimum_performance_observations",
        "mode_tie_rule",
        "median_even_rule",
        "blocking_exclusion_reasons",
        "native_state_handling",
        "actor",
        "rationale",
        "revised_at",
    }
)
_POLICY_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {"class_id", "policy_id", "policy_revision", "policy_sha256"}
)
_LEVEL_COUNT_KEYS: Final[frozenset[str]] = frozenset(
    {"proficiency_level_id", "count"}
)
_INSUFFICIENCY_REASON_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "source_keys", "required_observations", "actual_observations"}
)
_TIE_RESOLUTION_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "rule", "candidate_level_ids", "selected_level_id"}
)
_EXPLANATION_ENTRY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "source_key",
        "status",
        "proficiency_level_id",
        "native_state_code",
        "exclusion_reason",
    }
)
_OUTCOME_KEYS: Final[frozenset[str]] = frozenset(
    {
        "algorithm_version",
        "status",
        "proficiency_level_id",
        "aggregation_inputs_sha256",
        "calculation_fingerprint",
        "policy_reference",
        "target_scale",
        "performance_observation_count",
        "native_state_count",
        "excluded_count",
        "level_counts",
        "insufficiency_reasons",
        "tie_resolution",
        "explanation_entries",
    }
)
_RESULT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "grade_item_id",
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
_RESULT_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "grade_item_id",
        "student_id",
        "standard_id",
        "result_revision",
        "result_sha256",
    }
)

_T = TypeVar("_T")


class StandardProficiencyError(ValueError):
    "Base error for standards-proficiency domain contracts."


class StandardProficiencyValidationError(StandardProficiencyError):
    "Raised when standards-proficiency data violates its domain contract."


class StandardProficiencySerializationError(StandardProficiencyError):
    "Raised when standards-proficiency JSON is invalid or noncanonical."


@dataclass(frozen=True, slots=True)
class StandardProficiencyActor:
    "Explicit authorship for a calculation-policy revision."

    kind: StandardProficiencyActorKind
    actor_id: str

    def __post_init__(self) -> None:
        if self.kind not in {"teacher", "policy"}:
            raise StandardProficiencyValidationError(
                "actor kind must be one of: policy, teacher."
            )
        object.__setattr__(
            self,
            "actor_id",
            _bounded_text(
                self.actor_id,
                "actor_id",
                MAXIMUM_STANDARD_PROFICIENCY_ACTOR_ID_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class StandardProficiencyCalculationPolicy:
    "One immutable policy revision governing one target proficiency scale."

    schema_version: str
    record_type: str
    class_id: str
    policy_id: str
    policy_revision: int
    supersedes_revision: int | None
    title: str
    target_scale: ProficiencyScaleReference
    strategy: StandardProficiencyStrategy
    minimum_performance_observations: int
    mode_tie_rule: ModeTieRule | None
    median_even_rule: MedianEvenRule | None
    blocking_exclusion_reasons: tuple[
        StandardProficiencyBlockingExclusionReason, ...
    ]
    native_state_handling: NativeStateHandling
    actor: StandardProficiencyActor
    rationale: str | None
    revised_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != STANDARD_PROFICIENCY_POLICY_SCHEMA_VERSION:
            raise StandardProficiencyValidationError(
                "unsupported calculation-policy schema_version."
            )
        if self.record_type != STANDARD_PROFICIENCY_POLICY_RECORD_TYPE:
            raise StandardProficiencyValidationError(
                "record_type must identify a standards-proficiency calculation policy."
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
            MAXIMUM_STANDARD_PROFICIENCY_TITLE_LENGTH,
        )
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise StandardProficiencyValidationError(
                "target_scale must be a ProficiencyScaleReference."
            )
        if self.target_scale.class_id != class_id:
            raise StandardProficiencyValidationError(
                "target_scale class_id must match the calculation policy class_id."
            )

        strategy = _strategy(self.strategy)
        minimum = _positive_int(
            self.minimum_performance_observations,
            "minimum_performance_observations",
        )
        if minimum > MAXIMUM_STANDARD_PROFICIENCY_OBSERVATIONS:
            raise StandardProficiencyValidationError(
                "minimum_performance_observations exceeds the bounded "
                f"maximum of {MAXIMUM_STANDARD_PROFICIENCY_OBSERVATIONS}."
            )

        mode_rule = _optional_tie_rule(self.mode_tie_rule, "mode_tie_rule")
        median_rule = _optional_tie_rule(
            self.median_even_rule,
            "median_even_rule",
        )
        if strategy == "mode":
            if mode_rule is None:
                raise StandardProficiencyValidationError(
                    "mode strategy requires mode_tie_rule."
                )
            if median_rule is not None:
                raise StandardProficiencyValidationError(
                    "mode strategy must not define median_even_rule."
                )
        elif strategy == "median":
            if median_rule is None:
                raise StandardProficiencyValidationError(
                    "median strategy requires median_even_rule."
                )
            if mode_rule is not None:
                raise StandardProficiencyValidationError(
                    "median strategy must not define mode_tie_rule."
                )
        elif mode_rule is not None or median_rule is not None:
            raise StandardProficiencyValidationError(
                "highest/lowest strategies must not define tie rules."
            )

        blocking = _blocking_exclusion_reasons(
            self.blocking_exclusion_reasons
        )
        native_state_handling = _native_state_handling(
            self.native_state_handling
        )
        if not isinstance(self.actor, StandardProficiencyActor):
            raise StandardProficiencyValidationError(
                "actor must be a StandardProficiencyActor."
            )
        rationale = _optional_bounded_text(
            self.rationale,
            "rationale",
            MAXIMUM_STANDARD_PROFICIENCY_TEXT_LENGTH,
        )
        revised_at = _aware_utc_datetime(self.revised_at, "revised_at")

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "policy_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "strategy", strategy)
        object.__setattr__(
            self,
            "minimum_performance_observations",
            minimum,
        )
        object.__setattr__(self, "mode_tie_rule", mode_rule)
        object.__setattr__(self, "median_even_rule", median_rule)
        object.__setattr__(
            self,
            "blocking_exclusion_reasons",
            blocking,
        )
        object.__setattr__(
            self,
            "native_state_handling",
            native_state_handling,
        )
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "revised_at", revised_at)


@dataclass(frozen=True, slots=True)
class StandardProficiencyCalculationPolicyReference:
    "Exact immutable calculation-policy revision and digest."

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
class StandardProficiencyLevelCount:
    "Count of contributing observations at one exact target-scale level."

    proficiency_level_id: str
    count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proficiency_level_id",
            _identifier(self.proficiency_level_id, "proficiency_level_id"),
        )
        object.__setattr__(
            self,
            "count",
            _nonnegative_int(self.count, "count"),
        )


@dataclass(frozen=True, slots=True)
class StandardProficiencyInsufficiencyReason:
    "Structured reason why the exact calculation basis cannot yield proficiency."

    kind: StandardProficiencyInsufficiencyKind
    source_keys: tuple[str, ...] = ()
    required_observations: int | None = None
    actual_observations: int | None = None

    def __post_init__(self) -> None:
        allowed = {
            "no_performance_evidence",
            "below_minimum_performance_observations",
            "blocking_exclusion",
            "blocking_native_state",
            "unresolved_mode_tie",
            "unresolved_even_median",
        }
        if self.kind not in allowed:
            raise StandardProficiencyValidationError(
                "unsupported insufficiency reason kind."
            )
        source_keys = _sha256_tuple(self.source_keys, "source_keys")
        required = _optional_positive_int(
            self.required_observations,
            "required_observations",
        )
        actual = _optional_nonnegative_int(
            self.actual_observations,
            "actual_observations",
        )
        if self.kind == "no_performance_evidence":
            if source_keys or required is not None or actual != 0:
                raise StandardProficiencyValidationError(
                    "no_performance_evidence requires only actual_observations=0."
                )
        elif self.kind == "below_minimum_performance_observations":
            if (
                source_keys
                or required is None
                or actual is None
                or actual >= required
            ):
                raise StandardProficiencyValidationError(
                    "below-minimum evidence requires exact required/actual counts."
                )
        elif self.kind in {"blocking_exclusion", "blocking_native_state"}:
            if not source_keys or required is not None or actual is not None:
                raise StandardProficiencyValidationError(
                    "blocking insufficiency requires only exact source keys."
                )
        elif source_keys or required is not None or actual is not None:
            raise StandardProficiencyValidationError(
                "tie insufficiency must not carry source/count fields."
            )
        object.__setattr__(self, "source_keys", source_keys)
        object.__setattr__(self, "required_observations", required)
        object.__setattr__(self, "actual_observations", actual)


@dataclass(frozen=True, slots=True)
class StandardProficiencyTieResolution:
    "Deterministic resolution metadata for mode or even-median ambiguity."

    kind: StandardProficiencyTieKind
    rule: Literal["lower", "higher", "insufficient"]
    candidate_level_ids: tuple[str, ...]
    selected_level_id: str | None

    def __post_init__(self) -> None:
        if self.kind not in {"mode_tie", "median_even"}:
            raise StandardProficiencyValidationError(
                "unsupported tie-resolution kind."
            )
        if self.rule not in {"lower", "higher", "insufficient"}:
            raise StandardProficiencyValidationError(
                "unsupported tie-resolution rule."
            )
        candidates = _identifier_tuple(
            self.candidate_level_ids,
            "candidate_level_ids",
        )
        if len(candidates) < 2:
            raise StandardProficiencyValidationError(
                "tie resolution requires at least two candidate observations."
            )
        selected = self.selected_level_id
        if selected is not None:
            selected = _identifier(selected, "selected_level_id")
        if self.rule == "insufficient":
            if selected is not None:
                raise StandardProficiencyValidationError(
                    "insufficient tie resolution must not select a level."
                )
        elif selected is None or selected not in candidates:
            raise StandardProficiencyValidationError(
                "resolved tie must select one candidate level."
            )
        object.__setattr__(self, "candidate_level_ids", candidates)
        object.__setattr__(self, "selected_level_id", selected)


@dataclass(frozen=True, slots=True)
class StandardProficiencyEntryExplanation:
    "Deterministic privacy-minimal explanation for one #33 input entry."

    source_key: str
    status: StandardProficiencyExplanationStatus
    proficiency_level_id: str | None
    native_state_code: str | None
    exclusion_reason: StandardAggregationExclusionReason | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_key",
            _sha256(self.source_key, "source_key"),
        )
        if self.status not in {"performance", "native_state", "excluded"}:
            raise StandardProficiencyValidationError(
                "unsupported explanation-entry status."
            )
        level_id = self.proficiency_level_id
        if level_id is not None:
            level_id = _identifier(level_id, "proficiency_level_id")
        native_code = self.native_state_code
        if native_code is not None:
            native_code = _bounded_text(
                native_code,
                "native_state_code",
                MAXIMUM_STANDARD_PROFICIENCY_TITLE_LENGTH,
            )
        if self.status == "performance":
            if (
                level_id is None
                or native_code is not None
                or self.exclusion_reason is not None
            ):
                raise StandardProficiencyValidationError(
                    "performance explanation requires only a proficiency level."
                )
        elif self.status == "native_state":
            if (
                native_code is None
                or level_id is not None
                or self.exclusion_reason is not None
            ):
                raise StandardProficiencyValidationError(
                    "native-state explanation requires only its native state code."
                )
        elif (
            self.exclusion_reason is None
            or level_id is not None
            or native_code is not None
        ):
            raise StandardProficiencyValidationError(
                "excluded explanation requires only an exclusion reason."
            )
        object.__setattr__(self, "proficiency_level_id", level_id)
        object.__setattr__(self, "native_state_code", native_code)


@dataclass(frozen=True, slots=True)
class StandardProficiencyCalculationOutcome:
    "Pure deterministic calculation outcome over one exact #33 input snapshot."

    algorithm_version: str
    status: StandardProficiencyCalculationStatus
    proficiency_level_id: str | None
    aggregation_inputs_sha256: str
    calculation_fingerprint: str
    policy_reference: StandardProficiencyCalculationPolicyReference
    target_scale: ProficiencyScaleReference
    performance_observation_count: int
    native_state_count: int
    excluded_count: int
    level_counts: tuple[StandardProficiencyLevelCount, ...]
    insufficiency_reasons: tuple[StandardProficiencyInsufficiencyReason, ...]
    tie_resolution: StandardProficiencyTieResolution | None
    explanation_entries: tuple[StandardProficiencyEntryExplanation, ...]

    def __post_init__(self) -> None:
        if self.algorithm_version != STANDARD_PROFICIENCY_ALGORITHM_VERSION:
            raise StandardProficiencyValidationError(
                "unsupported standards-proficiency algorithm_version."
            )
        if self.status not in {"calculated", "insufficient_evidence"}:
            raise StandardProficiencyValidationError(
                "unsupported calculation outcome status."
            )
        level_id = self.proficiency_level_id
        if level_id is not None:
            level_id = _identifier(level_id, "proficiency_level_id")
        object.__setattr__(
            self,
            "aggregation_inputs_sha256",
            _sha256(
                self.aggregation_inputs_sha256,
                "aggregation_inputs_sha256",
            ),
        )
        object.__setattr__(
            self,
            "calculation_fingerprint",
            _sha256(
                self.calculation_fingerprint,
                "calculation_fingerprint",
            ),
        )
        if not isinstance(
            self.policy_reference,
            StandardProficiencyCalculationPolicyReference,
        ):
            raise StandardProficiencyValidationError(
                "policy_reference must be exact calculation-policy provenance."
            )
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise StandardProficiencyValidationError(
                "target_scale must be a ProficiencyScaleReference."
            )
        performance_count = _nonnegative_int(
            self.performance_observation_count,
            "performance_observation_count",
        )
        native_count = _nonnegative_int(
            self.native_state_count,
            "native_state_count",
        )
        excluded_count = _nonnegative_int(
            self.excluded_count,
            "excluded_count",
        )
        level_counts = _typed_tuple(
            self.level_counts,
            StandardProficiencyLevelCount,
            "level_counts",
        )
        if len({item.proficiency_level_id for item in level_counts}) != len(
            level_counts
        ):
            raise StandardProficiencyValidationError(
                "level_counts must not duplicate proficiency levels."
            )
        if sum(item.count for item in level_counts) != performance_count:
            raise StandardProficiencyValidationError(
                "level_counts must sum to performance_observation_count."
            )
        reasons = _typed_tuple(
            self.insufficiency_reasons,
            StandardProficiencyInsufficiencyReason,
            "insufficiency_reasons",
        )
        explanations = _typed_tuple(
            self.explanation_entries,
            StandardProficiencyEntryExplanation,
            "explanation_entries",
        )
        if len({item.source_key for item in explanations}) != len(explanations):
            raise StandardProficiencyValidationError(
                "explanation_entries must not duplicate source keys."
            )
        if performance_count + native_count + excluded_count != len(explanations):
            raise StandardProficiencyValidationError(
                "outcome counts must cover every explanation entry exactly once."
            )
        if self.tie_resolution is not None and not isinstance(
            self.tie_resolution,
            StandardProficiencyTieResolution,
        ):
            raise StandardProficiencyValidationError(
                "tie_resolution has an invalid type."
            )
        if self.status == "calculated":
            if level_id is None or reasons:
                raise StandardProficiencyValidationError(
                    "calculated outcomes require a level and no insufficiency reasons."
                )
        elif level_id is not None or not reasons:
            raise StandardProficiencyValidationError(
                "insufficient outcomes require no level and at least one reason."
            )
        object.__setattr__(self, "proficiency_level_id", level_id)
        object.__setattr__(
            self,
            "performance_observation_count",
            performance_count,
        )
        object.__setattr__(self, "native_state_count", native_count)
        object.__setattr__(self, "excluded_count", excluded_count)
        object.__setattr__(self, "level_counts", level_counts)
        object.__setattr__(self, "insufficiency_reasons", reasons)
        object.__setattr__(self, "explanation_entries", explanations)



@dataclass(frozen=True, slots=True)
class StandardProficiencyResultSnapshot:
    """Immutable persisted calculation wrapper over one exact #33 input body."""

    schema_version: str
    record_type: str
    class_id: str
    grade_item_id: str
    student_id: str
    standard_id: str
    result_revision: int
    supersedes_revision: int | None
    algorithm_version: str
    calculation_fingerprint: str
    inputs: StandardAggregationInputs
    inputs_sha256: str
    policy_reference: StandardProficiencyCalculationPolicyReference
    target_scale: ProficiencyScaleReference
    outcome: StandardProficiencyCalculationOutcome
    calculated_at: datetime

    def __post_init__(self) -> None:
        if self.schema_version != STANDARD_PROFICIENCY_RESULT_SCHEMA_VERSION:
            raise StandardProficiencyValidationError(
                "unsupported standards-proficiency result schema_version."
            )
        if self.record_type != STANDARD_PROFICIENCY_RESULT_RECORD_TYPE:
            raise StandardProficiencyValidationError(
                "record_type must identify a standards-proficiency result."
            )
        class_id = _identifier(self.class_id, "class_id")
        grade_item_id = _identifier(self.grade_item_id, "grade_item_id")
        student_id = _identifier(self.student_id, "student_id")
        standard_id = _standard_id(self.standard_id)
        revision = _positive_int(self.result_revision, "result_revision")
        supersedes = _optional_positive_int(
            self.supersedes_revision,
            "supersedes_revision",
        )
        if revision == 1 and supersedes is not None:
            raise StandardProficiencyValidationError(
                "result revision 1 must not supersede a prior revision."
            )
        if revision > 1 and supersedes != revision - 1:
            raise StandardProficiencyValidationError(
                "result supersedes_revision must identify the immediately "
                "prior revision."
            )
        if self.algorithm_version != STANDARD_PROFICIENCY_ALGORITHM_VERSION:
            raise StandardProficiencyValidationError(
                "unsupported standards-proficiency result algorithm_version."
            )
        fingerprint = _sha256(
            self.calculation_fingerprint,
            "calculation_fingerprint",
        )
        if not isinstance(self.inputs, StandardAggregationInputs):
            raise StandardProficiencyValidationError(
                "inputs must be StandardAggregationInputs."
            )
        inputs_sha256 = _sha256(self.inputs_sha256, "inputs_sha256")
        exact_inputs_sha256 = standard_aggregation_inputs_sha256(self.inputs)
        if inputs_sha256 != exact_inputs_sha256:
            raise StandardProficiencyValidationError(
                "inputs_sha256 must match the exact embedded aggregation inputs."
            )
        if (
            self.inputs.grade_item.class_id != class_id
            or self.inputs.grade_item.grade_item_id != grade_item_id
            or self.inputs.student_id != student_id
            or self.inputs.standard_id != standard_id
        ):
            raise StandardProficiencyValidationError(
                "result scope must match the exact embedded aggregation inputs."
            )
        if not isinstance(
            self.policy_reference,
            StandardProficiencyCalculationPolicyReference,
        ):
            raise StandardProficiencyValidationError(
                "policy_reference must be exact calculation-policy provenance."
            )
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise StandardProficiencyValidationError(
                "target_scale must be a ProficiencyScaleReference."
            )
        if self.target_scale != self.inputs.target_scale:
            raise StandardProficiencyValidationError(
                "result target_scale must match embedded aggregation inputs."
            )
        if self.policy_reference.class_id != class_id:
            raise StandardProficiencyValidationError(
                "result policy_reference must match result class scope."
            )
        if not isinstance(self.outcome, StandardProficiencyCalculationOutcome):
            raise StandardProficiencyValidationError(
                "outcome must be a StandardProficiencyCalculationOutcome."
            )
        if (
            self.outcome.algorithm_version != self.algorithm_version
            or self.outcome.calculation_fingerprint != fingerprint
            or self.outcome.aggregation_inputs_sha256 != inputs_sha256
            or self.outcome.policy_reference != self.policy_reference
            or self.outcome.target_scale != self.target_scale
        ):
            raise StandardProficiencyValidationError(
                "result metadata must match the exact pure calculation outcome."
            )
        calculated_at = _aware_utc_datetime(
            self.calculated_at,
            "calculated_at",
        )
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "grade_item_id", grade_item_id)
        object.__setattr__(self, "student_id", student_id)
        object.__setattr__(self, "standard_id", standard_id)
        object.__setattr__(self, "result_revision", revision)
        object.__setattr__(self, "supersedes_revision", supersedes)
        object.__setattr__(self, "calculation_fingerprint", fingerprint)
        object.__setattr__(self, "inputs_sha256", inputs_sha256)
        object.__setattr__(self, "calculated_at", calculated_at)


@dataclass(frozen=True, slots=True)
class StandardProficiencyResultReference:
    """Exact immutable standards-proficiency result revision and digest."""

    class_id: str
    grade_item_id: str
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
        object.__setattr__(
            self,
            "grade_item_id",
            _identifier(self.grade_item_id, "grade_item_id"),
        )
        object.__setattr__(
            self,
            "student_id",
            _identifier(self.student_id, "student_id"),
        )
        object.__setattr__(
            self,
            "standard_id",
            _standard_id(self.standard_id),
        )
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
class StandardProficiencyResultFreshness:
    """Pure diagnostic comparison of one persisted result to a supplied basis."""

    status: StandardProficiencyFreshnessStatus
    reasons: tuple[StandardProficiencyStalenessReason, ...]

    def __post_init__(self) -> None:
        if self.status not in {"current", "stale"}:
            raise StandardProficiencyValidationError(
                "unsupported standards-proficiency freshness status."
            )
        reasons = _staleness_reasons(self.reasons)
        if self.status == "current" and reasons:
            raise StandardProficiencyValidationError(
                "current freshness status requires no staleness reasons."
            )
        if self.status == "stale" and not reasons:
            raise StandardProficiencyValidationError(
                "stale freshness status requires at least one reason."
            )
        object.__setattr__(self, "reasons", reasons)


def validate_standard_proficiency_calculation_policy(
    value: StandardProficiencyCalculationPolicy,
) -> StandardProficiencyCalculationPolicy:
    if not isinstance(value, StandardProficiencyCalculationPolicy):
        raise StandardProficiencyValidationError(
            "value must be a StandardProficiencyCalculationPolicy."
        )
    value.__post_init__()
    return value


def validate_standard_proficiency_calculation_policy_transition(
    previous: StandardProficiencyCalculationPolicy,
    current: StandardProficiencyCalculationPolicy,
) -> StandardProficiencyCalculationPolicy:
    validate_standard_proficiency_calculation_policy(previous)
    validate_standard_proficiency_calculation_policy(current)
    if (previous.class_id, previous.policy_id) != (
        current.class_id,
        current.policy_id,
    ):
        raise StandardProficiencyValidationError(
            "calculation-policy logical identity cannot change across revisions."
        )
    if current.policy_revision != previous.policy_revision + 1:
        raise StandardProficiencyValidationError(
            "calculation-policy revisions must be contiguous."
        )
    if current.supersedes_revision != previous.policy_revision:
        raise StandardProficiencyValidationError(
            "calculation-policy supersedes_revision must identify the prior revision."
        )
    if current.revised_at < previous.revised_at:
        raise StandardProficiencyValidationError(
            "calculation-policy revised_at must be nondecreasing."
        )
    return current


def standard_proficiency_calculation_policy_reference(
    policy: StandardProficiencyCalculationPolicy,
) -> StandardProficiencyCalculationPolicyReference:
    validate_standard_proficiency_calculation_policy(policy)
    return StandardProficiencyCalculationPolicyReference(
        class_id=policy.class_id,
        policy_id=policy.policy_id,
        policy_revision=policy.policy_revision,
        policy_sha256=hashlib.sha256(
            standard_proficiency_calculation_policy_to_json_bytes(policy)
        ).hexdigest(),
    )


def standard_proficiency_calculation_policy_to_dict(
    value: StandardProficiencyCalculationPolicy,
) -> dict[str, object]:
    validate_standard_proficiency_calculation_policy(value)
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "class_id": value.class_id,
        "policy_id": value.policy_id,
        "policy_revision": value.policy_revision,
        "supersedes_revision": value.supersedes_revision,
        "title": value.title,
        "target_scale": _scale_reference_to_dict(value.target_scale),
        "strategy": value.strategy,
        "minimum_performance_observations": (
            value.minimum_performance_observations
        ),
        "mode_tie_rule": value.mode_tie_rule,
        "median_even_rule": value.median_even_rule,
        "blocking_exclusion_reasons": list(
            value.blocking_exclusion_reasons
        ),
        "native_state_handling": value.native_state_handling,
        "actor": _actor_to_dict(value.actor),
        "rationale": value.rationale,
        "revised_at": _datetime_to_text(value.revised_at),
    }


def standard_proficiency_calculation_policy_from_dict(
    data: object,
) -> StandardProficiencyCalculationPolicy:
    mapping = _exact_mapping(
        data,
        _POLICY_KEYS,
        "standards-proficiency calculation policy",
    )
    blocking = tuple(
        _require_str(item, "blocking_exclusion_reason")
        for item in _require_list(
            mapping["blocking_exclusion_reasons"],
            "blocking_exclusion_reasons",
        )
    )
    return StandardProficiencyCalculationPolicy(
        schema_version=_require_str(
            mapping["schema_version"],
            "schema_version",
        ),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_revision=_require_int(
            mapping["policy_revision"],
            "policy_revision",
        ),
        supersedes_revision=_optional_int(
            mapping["supersedes_revision"],
            "supersedes_revision",
        ),
        title=_require_str(mapping["title"], "title"),
        target_scale=_scale_reference_from_dict(mapping["target_scale"]),
        strategy=_strategy(mapping["strategy"]),
        minimum_performance_observations=_require_int(
            mapping["minimum_performance_observations"],
            "minimum_performance_observations",
        ),
        mode_tie_rule=_optional_tie_rule(
            mapping["mode_tie_rule"],
            "mode_tie_rule",
        ),
        median_even_rule=_optional_tie_rule(
            mapping["median_even_rule"],
            "median_even_rule",
        ),
        blocking_exclusion_reasons=cast(
            tuple[StandardProficiencyBlockingExclusionReason, ...],
            blocking,
        ),
        native_state_handling=_native_state_handling(
            mapping["native_state_handling"]
        ),
        actor=_actor_from_dict(mapping["actor"]),
        rationale=_optional_str(mapping["rationale"], "rationale"),
        revised_at=_datetime_from_text(
            mapping["revised_at"],
            "revised_at",
        ),
    )


def standard_proficiency_calculation_policy_to_json_bytes(
    value: StandardProficiencyCalculationPolicy,
) -> bytes:
    return _canonical_json_bytes(
        standard_proficiency_calculation_policy_to_dict(value)
    )


def standard_proficiency_calculation_policy_from_json_bytes(
    data: bytes,
) -> StandardProficiencyCalculationPolicy:
    decoded = _decode_json(
        data,
        "standards-proficiency calculation policy",
    )
    value = standard_proficiency_calculation_policy_from_dict(decoded)
    canonical = standard_proficiency_calculation_policy_to_json_bytes(value)
    if canonical != data:
        raise StandardProficiencySerializationError(
            "standards-proficiency calculation policy is not canonical JSON."
        )
    return value


def standard_proficiency_calculation_policy_reference_to_dict(
    value: StandardProficiencyCalculationPolicyReference,
) -> dict[str, object]:
    if not isinstance(value, StandardProficiencyCalculationPolicyReference):
        raise StandardProficiencyValidationError(
            "value must be a StandardProficiencyCalculationPolicyReference."
        )
    return {
        "class_id": value.class_id,
        "policy_id": value.policy_id,
        "policy_revision": value.policy_revision,
        "policy_sha256": value.policy_sha256,
    }


def standard_proficiency_calculation_policy_reference_from_dict(
    data: object,
) -> StandardProficiencyCalculationPolicyReference:
    mapping = _exact_mapping(
        data,
        _POLICY_REFERENCE_KEYS,
        "standards-proficiency calculation policy reference",
    )
    return StandardProficiencyCalculationPolicyReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        policy_id=_require_str(mapping["policy_id"], "policy_id"),
        policy_revision=_require_int(
            mapping["policy_revision"],
            "policy_revision",
        ),
        policy_sha256=_require_str(
            mapping["policy_sha256"],
            "policy_sha256",
        ),
    )



def standard_proficiency_calculation_fingerprint(
    inputs: StandardAggregationInputs,
    policy: StandardProficiencyCalculationPolicy,
    scale: ProficiencyScale,
) -> str:
    "Return a stable digest over the exact pure academic calculation basis."

    scale_reference, policy_reference = _validate_calculation_basis(
        inputs,
        policy,
        scale,
    )
    payload = {
        "algorithm_version": STANDARD_PROFICIENCY_ALGORITHM_VERSION,
        "aggregation_inputs_sha256": inputs.sha256,
        "policy_reference": (
            standard_proficiency_calculation_policy_reference_to_dict(
                policy_reference
            )
        ),
        "target_scale": _scale_reference_to_dict(scale_reference),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def calculate_standard_proficiency(
    inputs: StandardAggregationInputs,
    policy: StandardProficiencyCalculationPolicy,
    scale: ProficiencyScale,
) -> StandardProficiencyCalculationOutcome:
    "Purely calculate one Grade Item/student/standard proficiency outcome."

    scale_reference, policy_reference = _validate_calculation_basis(
        inputs,
        policy,
        scale,
    )
    positions = {level.level_id: level.position for level in scale.levels}
    ordered_level_ids = tuple(level.level_id for level in scale.levels)

    performance_level_ids: list[str] = []
    explanation_entries: list[StandardProficiencyEntryExplanation] = []
    blocking_exclusion_keys: list[str] = []
    blocking_native_keys: list[str] = []
    native_state_count = 0
    excluded_count = 0

    for entry in inputs.entries:
        source_key = evidence_source_key(entry.source)
        if entry.status == "performance":
            level_id = entry.proficiency_level_id
            if level_id is None or level_id not in positions:
                raise StandardProficiencyValidationError(
                    "performance entry references a level outside the exact "
                    "target scale."
                )
            performance_level_ids.append(level_id)
            explanation_entries.append(
                StandardProficiencyEntryExplanation(
                    source_key,
                    "performance",
                    level_id,
                    None,
                    None,
                )
            )
        elif entry.status == "native_state":
            native_state = entry.native_state
            if native_state is None:
                raise StandardProficiencyValidationError(
                    "native-state entry is missing its exact native state."
                )
            native_state_count += 1
            explanation_entries.append(
                StandardProficiencyEntryExplanation(
                    source_key,
                    "native_state",
                    None,
                    native_state.code,
                    None,
                )
            )
            if policy.native_state_handling == "blocking":
                blocking_native_keys.append(source_key)
        else:
            reason = entry.exclusion_reason
            if reason is None:
                raise StandardProficiencyValidationError(
                    "excluded entry is missing its exact exclusion reason."
                )
            excluded_count += 1
            explanation_entries.append(
                StandardProficiencyEntryExplanation(
                    source_key,
                    "excluded",
                    None,
                    None,
                    reason,
                )
            )
            if reason in policy.blocking_exclusion_reasons:
                blocking_exclusion_keys.append(source_key)

    performance_count = len(performance_level_ids)
    counts = Counter(performance_level_ids)
    level_counts = tuple(
        StandardProficiencyLevelCount(
            level_id,
            counts.get(level_id, 0),
        )
        for level_id in ordered_level_ids
    )

    reasons: list[StandardProficiencyInsufficiencyReason] = []
    if blocking_exclusion_keys:
        reasons.append(
            StandardProficiencyInsufficiencyReason(
                "blocking_exclusion",
                tuple(blocking_exclusion_keys),
            )
        )
    if blocking_native_keys:
        reasons.append(
            StandardProficiencyInsufficiencyReason(
                "blocking_native_state",
                tuple(blocking_native_keys),
            )
        )
    if performance_count == 0:
        reasons.append(
            StandardProficiencyInsufficiencyReason(
                "no_performance_evidence",
                actual_observations=0,
            )
        )
    elif performance_count < policy.minimum_performance_observations:
        reasons.append(
            StandardProficiencyInsufficiencyReason(
                "below_minimum_performance_observations",
                required_observations=policy.minimum_performance_observations,
                actual_observations=performance_count,
            )
        )

    fingerprint = _calculation_fingerprint_from_references(
        inputs.sha256,
        policy_reference,
        scale_reference,
    )
    tie_resolution: StandardProficiencyTieResolution | None = None
    selected_level_id: str | None = None

    if not reasons:
        (
            selected_level_id,
            tie_resolution,
            strategy_reason,
        ) = _apply_standard_proficiency_strategy(
            performance_level_ids,
            positions,
            policy,
        )
        if strategy_reason is not None:
            reasons.append(strategy_reason)

    status: StandardProficiencyCalculationStatus
    if reasons:
        status = "insufficient_evidence"
        selected_level_id = None
    else:
        status = "calculated"

    return StandardProficiencyCalculationOutcome(
        algorithm_version=STANDARD_PROFICIENCY_ALGORITHM_VERSION,
        status=status,
        proficiency_level_id=selected_level_id,
        aggregation_inputs_sha256=inputs.sha256,
        calculation_fingerprint=fingerprint,
        policy_reference=policy_reference,
        target_scale=scale_reference,
        performance_observation_count=performance_count,
        native_state_count=native_state_count,
        excluded_count=excluded_count,
        level_counts=level_counts,
        insufficiency_reasons=tuple(reasons),
        tie_resolution=tie_resolution,
        explanation_entries=tuple(explanation_entries),
    )



def create_standard_proficiency_result_snapshot(
    inputs: StandardAggregationInputs,
    outcome: StandardProficiencyCalculationOutcome,
    *,
    result_revision: int,
    calculated_at: datetime,
) -> StandardProficiencyResultSnapshot:
    """Wrap one already-pure outcome in explicit immutable persistence metadata."""

    if not isinstance(inputs, StandardAggregationInputs):
        raise StandardProficiencyValidationError(
            "inputs must be StandardAggregationInputs."
        )
    if not isinstance(outcome, StandardProficiencyCalculationOutcome):
        raise StandardProficiencyValidationError(
            "outcome must be a StandardProficiencyCalculationOutcome."
        )
    revision = _positive_int(result_revision, "result_revision")
    return StandardProficiencyResultSnapshot(
        schema_version=STANDARD_PROFICIENCY_RESULT_SCHEMA_VERSION,
        record_type=STANDARD_PROFICIENCY_RESULT_RECORD_TYPE,
        class_id=inputs.grade_item.class_id,
        grade_item_id=inputs.grade_item.grade_item_id,
        student_id=inputs.student_id,
        standard_id=inputs.standard_id,
        result_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        algorithm_version=outcome.algorithm_version,
        calculation_fingerprint=outcome.calculation_fingerprint,
        inputs=inputs,
        inputs_sha256=standard_aggregation_inputs_sha256(inputs),
        policy_reference=outcome.policy_reference,
        target_scale=outcome.target_scale,
        outcome=outcome,
        calculated_at=calculated_at,
    )


def validate_standard_proficiency_result_transition(
    previous: StandardProficiencyResultSnapshot,
    current: StandardProficiencyResultSnapshot,
) -> StandardProficiencyResultSnapshot:
    if not isinstance(previous, StandardProficiencyResultSnapshot):
        raise StandardProficiencyValidationError(
            "previous must be a StandardProficiencyResultSnapshot."
        )
    if not isinstance(current, StandardProficiencyResultSnapshot):
        raise StandardProficiencyValidationError(
            "current must be a StandardProficiencyResultSnapshot."
        )
    previous.__post_init__()
    current.__post_init__()
    previous_scope = (
        previous.class_id,
        previous.grade_item_id,
        previous.student_id,
        previous.standard_id,
    )
    current_scope = (
        current.class_id,
        current.grade_item_id,
        current.student_id,
        current.standard_id,
    )
    if current_scope != previous_scope:
        raise StandardProficiencyValidationError(
            "standards-proficiency result logical identity cannot change "
            "across revisions."
        )
    if current.result_revision != previous.result_revision + 1:
        raise StandardProficiencyValidationError(
            "standards-proficiency result revisions must be contiguous."
        )
    if current.supersedes_revision != previous.result_revision:
        raise StandardProficiencyValidationError(
            "result supersedes_revision must identify the prior revision."
        )
    return current


def standard_proficiency_calculation_outcome_to_dict(
    value: StandardProficiencyCalculationOutcome,
) -> dict[str, object]:
    if not isinstance(value, StandardProficiencyCalculationOutcome):
        raise StandardProficiencyValidationError(
            "value must be a StandardProficiencyCalculationOutcome."
        )
    return {
        "algorithm_version": value.algorithm_version,
        "status": value.status,
        "proficiency_level_id": value.proficiency_level_id,
        "aggregation_inputs_sha256": value.aggregation_inputs_sha256,
        "calculation_fingerprint": value.calculation_fingerprint,
        "policy_reference": (
            standard_proficiency_calculation_policy_reference_to_dict(
                value.policy_reference
            )
        ),
        "target_scale": _scale_reference_to_dict(value.target_scale),
        "performance_observation_count": value.performance_observation_count,
        "native_state_count": value.native_state_count,
        "excluded_count": value.excluded_count,
        "level_counts": [
            {
                "proficiency_level_id": item.proficiency_level_id,
                "count": item.count,
            }
            for item in value.level_counts
        ],
        "insufficiency_reasons": [
            {
                "kind": item.kind,
                "source_keys": list(item.source_keys),
                "required_observations": item.required_observations,
                "actual_observations": item.actual_observations,
            }
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
            {
                "source_key": item.source_key,
                "status": item.status,
                "proficiency_level_id": item.proficiency_level_id,
                "native_state_code": item.native_state_code,
                "exclusion_reason": item.exclusion_reason,
            }
            for item in value.explanation_entries
        ],
    }


def standard_proficiency_calculation_outcome_from_dict(
    data: object,
) -> StandardProficiencyCalculationOutcome:
    mapping = _exact_mapping(data, _OUTCOME_KEYS, "calculation outcome")
    level_counts_data = _require_list(mapping["level_counts"], "level_counts")
    reason_data = _require_list(
        mapping["insufficiency_reasons"],
        "insufficiency_reasons",
    )
    explanation_data = _require_list(
        mapping["explanation_entries"],
        "explanation_entries",
    )
    tie_data = mapping["tie_resolution"]
    tie_resolution: StandardProficiencyTieResolution | None = None
    if tie_data is not None:
        tie = _exact_mapping(
            tie_data,
            _TIE_RESOLUTION_KEYS,
            "tie resolution",
        )
        tie_resolution = StandardProficiencyTieResolution(
            kind=cast(
                StandardProficiencyTieKind,
                _require_str(tie["kind"], "tie_resolution.kind"),
            ),
            rule=cast(
                Literal["lower", "higher", "insufficient"],
                _require_str(tie["rule"], "tie_resolution.rule"),
            ),
            candidate_level_ids=tuple(
                _require_str(item, "candidate_level_id")
                for item in _require_list(
                    tie["candidate_level_ids"],
                    "tie_resolution.candidate_level_ids",
                )
            ),
            selected_level_id=_optional_str(
                tie["selected_level_id"],
                "tie_resolution.selected_level_id",
            ),
        )

    return StandardProficiencyCalculationOutcome(
        algorithm_version=_require_str(
            mapping["algorithm_version"],
            "algorithm_version",
        ),
        status=cast(
            StandardProficiencyCalculationStatus,
            _require_str(mapping["status"], "status"),
        ),
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
            standard_proficiency_calculation_policy_reference_from_dict(
                mapping["policy_reference"]
            )
        ),
        target_scale=_scale_reference_from_dict(mapping["target_scale"]),
        performance_observation_count=_require_int(
            mapping["performance_observation_count"],
            "performance_observation_count",
        ),
        native_state_count=_require_int(
            mapping["native_state_count"],
            "native_state_count",
        ),
        excluded_count=_require_int(
            mapping["excluded_count"],
            "excluded_count",
        ),
        level_counts=tuple(
            _level_count_from_dict(item) for item in level_counts_data
        ),
        insufficiency_reasons=tuple(
            _insufficiency_reason_from_dict(item) for item in reason_data
        ),
        tie_resolution=tie_resolution,
        explanation_entries=tuple(
            _explanation_entry_from_dict(item) for item in explanation_data
        ),
    )


def standard_proficiency_result_snapshot_to_dict(
    value: StandardProficiencyResultSnapshot,
) -> dict[str, object]:
    if not isinstance(value, StandardProficiencyResultSnapshot):
        raise StandardProficiencyValidationError(
            "value must be a StandardProficiencyResultSnapshot."
        )
    value.__post_init__()
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "student_id": value.student_id,
        "standard_id": value.standard_id,
        "result_revision": value.result_revision,
        "supersedes_revision": value.supersedes_revision,
        "algorithm_version": value.algorithm_version,
        "calculation_fingerprint": value.calculation_fingerprint,
        "inputs": standard_aggregation_inputs_to_dict(value.inputs),
        "inputs_sha256": value.inputs_sha256,
        "policy_reference": (
            standard_proficiency_calculation_policy_reference_to_dict(
                value.policy_reference
            )
        ),
        "target_scale": _scale_reference_to_dict(value.target_scale),
        "outcome": standard_proficiency_calculation_outcome_to_dict(
            value.outcome
        ),
        "calculated_at": _datetime_to_text(value.calculated_at),
    }


def standard_proficiency_result_snapshot_from_dict(
    data: object,
) -> StandardProficiencyResultSnapshot:
    mapping = _exact_mapping(
        data,
        _RESULT_KEYS,
        "standards-proficiency result snapshot",
    )
    return StandardProficiencyResultSnapshot(
        schema_version=_require_str(
            mapping["schema_version"],
            "schema_version",
        ),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        grade_item_id=_require_str(
            mapping["grade_item_id"],
            "grade_item_id",
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
        inputs=standard_aggregation_inputs_from_dict(mapping["inputs"]),
        inputs_sha256=_require_str(
            mapping["inputs_sha256"],
            "inputs_sha256",
        ),
        policy_reference=(
            standard_proficiency_calculation_policy_reference_from_dict(
                mapping["policy_reference"]
            )
        ),
        target_scale=_scale_reference_from_dict(mapping["target_scale"]),
        outcome=standard_proficiency_calculation_outcome_from_dict(
            mapping["outcome"]
        ),
        calculated_at=_datetime_from_text(
            mapping["calculated_at"],
            "calculated_at",
        ),
    )


def standard_proficiency_result_snapshot_to_json_bytes(
    value: StandardProficiencyResultSnapshot,
) -> bytes:
    return _canonical_json_bytes(
        standard_proficiency_result_snapshot_to_dict(value)
    )


def standard_proficiency_result_snapshot_from_json_bytes(
    data: bytes,
) -> StandardProficiencyResultSnapshot:
    decoded = _decode_json(data, "standards-proficiency result snapshot")
    result = standard_proficiency_result_snapshot_from_dict(decoded)
    if standard_proficiency_result_snapshot_to_json_bytes(result) != data:
        raise StandardProficiencySerializationError(
            "standards-proficiency result snapshot is not canonical JSON."
        )
    return result


def standard_proficiency_result_reference(
    value: StandardProficiencyResultSnapshot,
) -> StandardProficiencyResultReference:
    if not isinstance(value, StandardProficiencyResultSnapshot):
        raise StandardProficiencyValidationError(
            "value must be a StandardProficiencyResultSnapshot."
        )
    content = standard_proficiency_result_snapshot_to_json_bytes(value)
    return StandardProficiencyResultReference(
        class_id=value.class_id,
        grade_item_id=value.grade_item_id,
        student_id=value.student_id,
        standard_id=value.standard_id,
        result_revision=value.result_revision,
        result_sha256=hashlib.sha256(content).hexdigest(),
    )


def standard_proficiency_result_reference_to_dict(
    value: StandardProficiencyResultReference,
) -> dict[str, object]:
    if not isinstance(value, StandardProficiencyResultReference):
        raise StandardProficiencyValidationError(
            "value must be a StandardProficiencyResultReference."
        )
    return {
        "class_id": value.class_id,
        "grade_item_id": value.grade_item_id,
        "student_id": value.student_id,
        "standard_id": value.standard_id,
        "result_revision": value.result_revision,
        "result_sha256": value.result_sha256,
    }


def standard_proficiency_result_reference_from_dict(
    data: object,
) -> StandardProficiencyResultReference:
    mapping = _exact_mapping(
        data,
        _RESULT_REFERENCE_KEYS,
        "standards-proficiency result reference",
    )
    return StandardProficiencyResultReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        grade_item_id=_require_str(
            mapping["grade_item_id"],
            "grade_item_id",
        ),
        student_id=_require_str(mapping["student_id"], "student_id"),
        standard_id=_require_str(mapping["standard_id"], "standard_id"),
        result_revision=_require_int(
            mapping["result_revision"],
            "result_revision",
        ),
        result_sha256=_require_str(
            mapping["result_sha256"],
            "result_sha256",
        ),
    )


def assess_standard_proficiency_result_freshness(
    result: StandardProficiencyResultSnapshot,
    current_inputs: StandardAggregationInputs,
    current_policy_reference: StandardProficiencyCalculationPolicyReference,
    current_scale_reference: ProficiencyScaleReference,
    algorithm_version: str,
) -> StandardProficiencyResultFreshness:
    """Purely compare one immutable result against explicit current dependencies."""

    if not isinstance(result, StandardProficiencyResultSnapshot):
        raise StandardProficiencyValidationError(
            "result must be a StandardProficiencyResultSnapshot."
        )
    result.__post_init__()
    if not isinstance(current_inputs, StandardAggregationInputs):
        raise StandardProficiencyValidationError(
            "current_inputs must be StandardAggregationInputs."
        )
    current_inputs.__post_init__()
    if not isinstance(
        current_policy_reference,
        StandardProficiencyCalculationPolicyReference,
    ):
        raise StandardProficiencyValidationError(
            "current_policy_reference must be an exact calculation-policy reference."
        )
    if not isinstance(current_scale_reference, ProficiencyScaleReference):
        raise StandardProficiencyValidationError(
            "current_scale_reference must be an exact proficiency-scale reference."
        )
    current_algorithm = _bounded_text(
        algorithm_version,
        "algorithm_version",
        256,
    )

    current_scope = (
        current_inputs.grade_item.class_id,
        current_inputs.grade_item.grade_item_id,
        current_inputs.student_id,
        current_inputs.standard_id,
    )
    result_scope = (
        result.class_id,
        result.grade_item_id,
        result.student_id,
        result.standard_id,
    )
    if current_scope != result_scope:
        raise StandardProficiencyValidationError(
            "freshness comparison must preserve the result logical identity."
        )
    if current_policy_reference.class_id != result.class_id:
        raise StandardProficiencyValidationError(
            "current policy reference must match the result class."
        )
    if current_scale_reference.class_id != result.class_id:
        raise StandardProficiencyValidationError(
            "current scale reference must match the result class."
        )

    reasons: list[StandardProficiencyStalenessReason] = []
    if standard_aggregation_inputs_sha256(current_inputs) != result.inputs_sha256:
        reasons.append("inputs_changed")
    if current_policy_reference != result.policy_reference:
        reasons.append("policy_changed")
    if current_scale_reference != result.target_scale:
        reasons.append("scale_changed")
    if current_algorithm != result.algorithm_version:
        reasons.append("algorithm_changed")

    return StandardProficiencyResultFreshness(
        status="current" if not reasons else "stale",
        reasons=tuple(reasons),
    )


def _level_count_from_dict(data: object) -> StandardProficiencyLevelCount:
    mapping = _exact_mapping(data, _LEVEL_COUNT_KEYS, "level count")
    return StandardProficiencyLevelCount(
        proficiency_level_id=_require_str(
            mapping["proficiency_level_id"],
            "proficiency_level_id",
        ),
        count=_require_int(mapping["count"], "count"),
    )


def _insufficiency_reason_from_dict(
    data: object,
) -> StandardProficiencyInsufficiencyReason:
    mapping = _exact_mapping(
        data,
        _INSUFFICIENCY_REASON_KEYS,
        "insufficiency reason",
    )
    return StandardProficiencyInsufficiencyReason(
        kind=cast(
            StandardProficiencyInsufficiencyKind,
            _require_str(mapping["kind"], "kind"),
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


def _explanation_entry_from_dict(
    data: object,
) -> StandardProficiencyEntryExplanation:
    mapping = _exact_mapping(
        data,
        _EXPLANATION_ENTRY_KEYS,
        "explanation entry",
    )
    exclusion = _optional_str(
        mapping["exclusion_reason"],
        "exclusion_reason",
    )
    return StandardProficiencyEntryExplanation(
        source_key=_require_str(mapping["source_key"], "source_key"),
        status=cast(
            StandardProficiencyExplanationStatus,
            _require_str(mapping["status"], "status"),
        ),
        proficiency_level_id=_optional_str(
            mapping["proficiency_level_id"],
            "proficiency_level_id",
        ),
        native_state_code=_optional_str(
            mapping["native_state_code"],
            "native_state_code",
        ),
        exclusion_reason=cast(
            StandardAggregationExclusionReason | None,
            exclusion,
        ),
    )


def _validate_calculation_basis(
    inputs: StandardAggregationInputs,
    policy: StandardProficiencyCalculationPolicy,
    scale: ProficiencyScale,
) -> tuple[
    ProficiencyScaleReference,
    StandardProficiencyCalculationPolicyReference,
]:
    if not isinstance(inputs, StandardAggregationInputs):
        raise StandardProficiencyValidationError(
            "inputs must be StandardAggregationInputs."
        )
    inputs.__post_init__()
    validate_standard_proficiency_calculation_policy(policy)
    validate_proficiency_scale(scale)

    scale_reference = proficiency_scale_reference(scale)
    if inputs.target_scale != scale_reference:
        raise StandardProficiencyValidationError(
            "aggregation inputs do not bind this exact proficiency-scale revision."
        )
    if policy.target_scale != scale_reference:
        raise StandardProficiencyValidationError(
            "calculation policy does not bind this exact proficiency-scale revision."
        )
    if policy.class_id != inputs.grade_item.class_id:
        raise StandardProficiencyValidationError(
            "calculation policy class must match aggregation-input Grade Item class."
        )
    return (
        scale_reference,
        standard_proficiency_calculation_policy_reference(policy),
    )


def _calculation_fingerprint_from_references(
    aggregation_inputs_sha256: str,
    policy_reference: StandardProficiencyCalculationPolicyReference,
    scale_reference: ProficiencyScaleReference,
) -> str:
    payload = {
        "algorithm_version": STANDARD_PROFICIENCY_ALGORITHM_VERSION,
        "aggregation_inputs_sha256": _sha256(
            aggregation_inputs_sha256,
            "aggregation_inputs_sha256",
        ),
        "policy_reference": (
            standard_proficiency_calculation_policy_reference_to_dict(
                policy_reference
            )
        ),
        "target_scale": _scale_reference_to_dict(scale_reference),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _apply_standard_proficiency_strategy(
    performance_level_ids: list[str],
    positions: dict[str, int],
    policy: StandardProficiencyCalculationPolicy,
) -> tuple[
    str | None,
    StandardProficiencyTieResolution | None,
    StandardProficiencyInsufficiencyReason | None,
]:
    if not performance_level_ids:
        raise StandardProficiencyValidationError(
            "strategy execution requires performance observations."
        )
    ordered = sorted(
        performance_level_ids,
        key=positions.__getitem__,
    )
    if policy.strategy == "highest":
        return ordered[-1], None, None
    if policy.strategy == "lowest":
        return ordered[0], None, None
    if policy.strategy == "median":
        return _apply_median_strategy(ordered, policy)
    return _apply_mode_strategy(performance_level_ids, positions, policy)


def _apply_median_strategy(
    ordered: list[str],
    policy: StandardProficiencyCalculationPolicy,
) -> tuple[
    str | None,
    StandardProficiencyTieResolution | None,
    StandardProficiencyInsufficiencyReason | None,
]:
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle], None, None

    lower = ordered[middle - 1]
    higher = ordered[middle]
    rule = policy.median_even_rule
    if rule is None:
        raise StandardProficiencyValidationError(
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
        reason = StandardProficiencyInsufficiencyReason(
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


def _apply_mode_strategy(
    performance_level_ids: list[str],
    positions: dict[str, int],
    policy: StandardProficiencyCalculationPolicy,
) -> tuple[
    str | None,
    StandardProficiencyTieResolution | None,
    StandardProficiencyInsufficiencyReason | None,
]:
    counts = Counter(performance_level_ids)
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
        raise StandardProficiencyValidationError(
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
        reason = StandardProficiencyInsufficiencyReason(
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


def _actor_to_dict(value: StandardProficiencyActor) -> dict[str, object]:
    return {"kind": value.kind, "actor_id": value.actor_id}


def _actor_from_dict(data: object) -> StandardProficiencyActor:
    mapping = _exact_mapping(data, _ACTOR_KEYS, "actor")
    kind = mapping["kind"]
    if kind not in {"teacher", "policy"}:
        raise StandardProficiencyValidationError(
            "unsupported calculation-policy actor kind."
        )
    return StandardProficiencyActor(
        kind,
        _require_str(mapping["actor_id"], "actor_id"),
    )


def _scale_reference_to_dict(
    value: ProficiencyScaleReference,
) -> dict[str, object]:
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
        "proficiency-scale reference",
    )
    return ProficiencyScaleReference(
        class_id=_require_str(mapping["class_id"], "scale class_id"),
        scale_id=_require_str(mapping["scale_id"], "scale_id"),
        scale_revision=_require_int(
            mapping["scale_revision"],
            "scale_revision",
        ),
        scale_sha256=_require_str(
            mapping["scale_sha256"],
            "scale_sha256",
        ),
    )


def _staleness_reasons(
    values: object,
) -> tuple[StandardProficiencyStalenessReason, ...]:
    if isinstance(values, (str, bytes)):
        raise StandardProficiencyValidationError(
            "freshness reasons must be an iterable."
        )
    try:
        raw = tuple(cast(Iterable[object], values))
    except TypeError as error:
        raise StandardProficiencyValidationError(
            "freshness reasons must be an iterable."
        ) from error
    if any(not isinstance(value, str) for value in raw):
        raise StandardProficiencyValidationError(
            "freshness reasons must contain strings."
        )
    if len(set(raw)) != len(raw):
        raise StandardProficiencyValidationError(
            "freshness reasons must not contain duplicates."
        )
    invalid = sorted(set(cast(tuple[str, ...], raw)) - _STALENESS_REASON_SET)
    if invalid:
        raise StandardProficiencyValidationError(
            f"unsupported freshness reasons: {invalid!r}."
        )
    selected = set(cast(tuple[str, ...], raw))
    return tuple(
        reason
        for reason in _STALENESS_REASON_ORDER
        if reason in selected
    )


def _strategy(value: object) -> StandardProficiencyStrategy:
    if value not in set(_STRATEGIES):
        raise StandardProficiencyValidationError(
            "strategy must be one of: highest, lowest, median, mode."
        )
    return value


def _optional_tie_rule(
    value: object,
    field_name: str,
) -> ModeTieRule | None:
    if value is None:
        return None
    if value not in set(_TIE_RULES):
        raise StandardProficiencyValidationError(
            f"{field_name} must be lower, higher, insufficient, or null."
        )
    return value


def _blocking_exclusion_reasons(
    values: object,
) -> tuple[StandardProficiencyBlockingExclusionReason, ...]:
    if isinstance(values, (str, bytes)):
        raise StandardProficiencyValidationError(
            "blocking_exclusion_reasons must be an iterable."
        )
    try:
        raw = tuple(cast(Iterable[object], values))
    except TypeError as error:
        raise StandardProficiencyValidationError(
            "blocking_exclusion_reasons must be an iterable."
        ) from error
    if any(not isinstance(value, str) for value in raw):
        raise StandardProficiencyValidationError(
            "blocking_exclusion_reasons must contain strings."
        )
    if len(set(raw)) != len(raw):
        raise StandardProficiencyValidationError(
            "blocking_exclusion_reasons must not contain duplicates."
        )
    invalid = sorted(set(cast(tuple[str, ...], raw)) - _BLOCKING_EXCLUSION_SET)
    if invalid:
        raise StandardProficiencyValidationError(
            "blocking_exclusion_reasons contains nonblocking or unsupported "
            f"#33 exclusion reasons: {invalid!r}."
        )
    selected = set(cast(tuple[str, ...], raw))
    return tuple(
        reason
        for reason in _BLOCKING_EXCLUSION_REASONS
        if reason in selected
    )


def _native_state_handling(value: object) -> NativeStateHandling:
    if value not in {"noncontributing", "blocking"}:
        raise StandardProficiencyValidationError(
            "native_state_handling must be noncontributing or blocking."
        )
    return value



def _standard_id(value: object) -> str:
    if not isinstance(value, str):
        raise StandardProficiencyValidationError(
            "standard_id must be a string."
        )
    result = value.strip()
    if not result:
        raise StandardProficiencyValidationError(
            "standard_id must not be blank."
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in result):
        raise StandardProficiencyValidationError(
            "standard_id must not contain control characters."
        )
    return result


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise StandardProficiencyValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise StandardProficiencyValidationError(str(error)) from error




def _typed_tuple(
    values: object,
    item_type: type[_T],
    field_name: str,
) -> tuple[_T, ...]:
    if isinstance(values, (str, bytes)):
        raise StandardProficiencyValidationError(
            f"{field_name} must be an iterable."
        )
    try:
        result = tuple(cast(Iterable[object], values))
    except TypeError as error:
        raise StandardProficiencyValidationError(
            f"{field_name} must be an iterable."
        ) from error
    if any(not isinstance(value, item_type) for value in result):
        raise StandardProficiencyValidationError(
            f"{field_name} contains an invalid item type."
        )
    return cast(tuple[_T, ...], result)


def _nonnegative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StandardProficiencyValidationError(
            f"{field_name} must be a nonnegative integer."
        )
    return value


def _optional_nonnegative_int(
    value: object,
    field_name: str,
) -> int | None:
    if value is None:
        return None
    return _nonnegative_int(value, field_name)


def _identifier_tuple(
    values: object,
    field_name: str,
) -> tuple[str, ...]:
    raw = _typed_tuple(values, str, field_name)
    return tuple(
        _identifier(value, f"{field_name} item")
        for value in raw
    )


def _sha256_tuple(
    values: object,
    field_name: str,
) -> tuple[str, ...]:
    raw = _typed_tuple(values, str, field_name)
    if len(set(raw)) != len(raw):
        raise StandardProficiencyValidationError(
            f"{field_name} must not contain duplicates."
        )
    return tuple(
        _sha256(value, f"{field_name} item")
        for value in raw
    )


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StandardProficiencyValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _optional_positive_int(
    value: object,
    field_name: str,
) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _validate_revision_pair(
    revision: int,
    supersedes: int | None,
) -> None:
    if revision == 1 and supersedes is not None:
        raise StandardProficiencyValidationError(
            "calculation-policy revision 1 must not supersede a prior revision."
        )
    if revision > 1 and supersedes != revision - 1:
        raise StandardProficiencyValidationError(
            "calculation-policy supersedes_revision must identify the "
            "immediately prior revision."
        )


def _bounded_text(
    value: object,
    field_name: str,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise StandardProficiencyValidationError(
            f"{field_name} must be a string."
        )
    if value != value.strip() or not value:
        raise StandardProficiencyValidationError(
            f"{field_name} must be nonempty without surrounding whitespace."
        )
    if len(value) > maximum:
        raise StandardProficiencyValidationError(
            f"{field_name} exceeds the maximum length of {maximum}."
        )
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise StandardProficiencyValidationError(
            f"{field_name} must not contain control characters."
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
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise StandardProficiencyValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_to_text(value: datetime) -> str:
    canonical = _aware_utc_datetime(value, "timestamp")
    return canonical.isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    if not text.endswith("Z"):
        raise StandardProficiencyValidationError(
            f"{field_name} must use canonical UTC Z."
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise StandardProficiencyValidationError(
            f"{field_name} is invalid."
        ) from error
    if _datetime_to_text(parsed) != text:
        raise StandardProficiencyValidationError(
            f"{field_name} must use canonical microsecond UTC encoding."
        )
    return parsed.astimezone(UTC)


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StandardProficiencyValidationError(
            f"{field_name} must be 64 lowercase hexadecimal characters."
        )
    return value


def _exact_mapping(
    value: object,
    keys: frozenset[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise StandardProficiencySerializationError(
            f"{label} must be a JSON object."
        )
    actual = frozenset(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise StandardProficiencySerializationError(
            f"{label} does not use exact schema "
            f"(missing={missing}, unknown={unknown})."
        )
    return cast(dict[str, object], value)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise StandardProficiencyValidationError(
            f"{field_name} must be a string."
        )
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StandardProficiencyValidationError(
            f"{field_name} must be an integer."
        )
    return value


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise StandardProficiencySerializationError(
            f"{field_name} must be a JSON array."
        )
    return cast(list[object], value)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise StandardProficiencySerializationError(
            "standards-proficiency state cannot be canonically serialized."
        ) from error
    return (text + "\n").encode("utf-8")


def _unique_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise StandardProficiencySerializationError(
                f"duplicate JSON key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise StandardProficiencySerializationError(
        f"non-finite JSON value is invalid: {value}"
    )


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise StandardProficiencySerializationError(
            f"{label} input must be bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StandardProficiencySerializationError(
            f"{label} must be UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except StandardProficiencySerializationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise StandardProficiencySerializationError(
            f"{label} JSON is invalid."
        ) from error


def is_blockable_standard_aggregation_exclusion_reason(
    value: StandardAggregationExclusionReason,
) -> bool:
    "Return whether a #33 exclusion reason may block a #34 calculation policy."

    return value in _BLOCKING_EXCLUSION_SET
