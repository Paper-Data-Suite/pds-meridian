"""Presentation-neutral Meridian proficiency-attention vocabulary and models.

Issue #43 derives current teacher attention from canonical Core/Meridian state.
This module intentionally owns only the stable native vocabulary, count units,
#41 task/action routing, deterministic ordering, and JSON-ready projection.
State discovery and the Core module-operations adapter are separate later slices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, TypeAlias

from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.teacher_workflows import (
    TEACHER_WORKFLOW_TASK_IDS,
    TeacherWorkflowTaskId,
)

PROFICIENCY_ATTENTION_SCHEMA_VERSION: Final = 1
MAX_MERIDIAN_ATTENTION_COUNT: Final = 1_000_000

MeridianAttentionCode: TypeAlias = Literal[
    "meridian_evidence_review_pending",
    "meridian_membership_review_pending",
    "meridian_attempt_decision_pending",
    "meridian_contract_unsupported",
    "meridian_source_withdrawn",
    "meridian_source_superseded",
    "meridian_native_value_unmapped",
    "meridian_grade_item_calculation_stale",
    "meridian_academic_period_calculation_stale",
    "meridian_planning_review_pending",
    "meridian_planning_review_selection_pending",
    "meridian_planning_review_stale",
]

MeridianAttentionCountUnit: TypeAlias = Literal[
    "work_review_scopes",
    "membership_review_scopes",
    "attempt_decision_scopes",
    "evidence_review_scopes",
    "source_review_scopes",
    "mapping_inputs",
    "grade_item_proficiency_targets",
    "academic_period_proficiency_targets",
    "planning_review_scopes",
]


class MeridianAttentionValidationError(ValueError):
    """Raised when a native Meridian attention projection is structurally invalid."""


@dataclass(frozen=True, slots=True)
class MeridianAttentionDefinition:
    """Stable meaning and navigation identity for one attention category."""

    code: MeridianAttentionCode
    label: str
    task_id: TeacherWorkflowTaskId
    action_id: str
    count_unit: MeridianAttentionCountUnit
    category_order: int

    def __post_init__(self) -> None:
        if self.task_id not in TEACHER_WORKFLOW_TASK_IDS:
            raise MeridianAttentionValidationError(
                f"Unsupported teacher workflow task: {self.task_id!r}."
            )
        _bounded_text(self.label, "label", maximum=160)
        _bounded_identifier(self.action_id, "action_id", maximum=64)
        if (
            isinstance(self.category_order, bool)
            or not isinstance(self.category_order, int)
            or self.category_order < 0
        ):
            raise MeridianAttentionValidationError(
                "category_order must be a nonnegative integer."
            )


@dataclass(frozen=True, slots=True)
class MeridianAttentionItem:
    """One aggregate, privacy-minimal Meridian-owned attention fact."""

    code: MeridianAttentionCode
    count: int
    class_id: str | None = None

    def __post_init__(self) -> None:
        attention_definition(self.code)
        if (
            isinstance(self.count, bool)
            or not isinstance(self.count, int)
            or self.count <= 0
            or self.count > MAX_MERIDIAN_ATTENTION_COUNT
        ):
            raise MeridianAttentionValidationError(
                "count must be an integer from 1 through "
                f"{MAX_MERIDIAN_ATTENTION_COUNT}."
            )
        if self.class_id is not None:
            _validated_identifier(self.class_id, "class_id")

    @property
    def definition(self) -> MeridianAttentionDefinition:
        """Return the stable category definition for this item."""

        return attention_definition(self.code)


@dataclass(frozen=True, slots=True)
class MeridianAttentionSummary:
    """Deterministically ordered native attention facts for one successful query."""

    items: tuple[MeridianAttentionItem, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        codes = tuple(item.code for item in self.items)
        if len(set(codes)) != len(codes):
            raise MeridianAttentionValidationError(
                "attention summary must not repeat a category code."
            )
        expected = tuple(sorted(self.items, key=_item_order_key))
        if self.items != expected:
            raise MeridianAttentionValidationError(
                "attention summary items must use canonical task/category order."
            )


def _bounded_text(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise MeridianAttentionValidationError(f"{field} must be a string.")
    if not value or value != value.strip():
        raise MeridianAttentionValidationError(
            f"{field} must be nonblank without surrounding whitespace."
        )
    if "\x00" in value or "\n" in value or "\r" in value:
        raise MeridianAttentionValidationError(
            f"{field} must be a control-free single-line string."
        )
    if len(value) > maximum:
        raise MeridianAttentionValidationError(
            f"{field} must be at most {maximum} characters."
        )
    return value


def _bounded_identifier(value: object, field: str, *, maximum: int) -> str:
    text = _bounded_text(value, field, maximum=maximum)
    try:
        return validate_identifier(text, field)
    except IdentifierValidationError as error:
        raise MeridianAttentionValidationError(str(error)) from error


def _validated_identifier(value: object, field: str) -> str:
    return _bounded_identifier(value, field, maximum=160)


_ACTION_BY_TASK: Final[dict[TeacherWorkflowTaskId, str]] = {
    "new-evidence": "open_new_evidence",
    "grade-items": "open_grade_items",
    "attempt-decisions": "open_attempt_decisions",
    "exclusions": "open_exclusions",
    "standards-review": "open_standards_review",
    "calculation-preview": "open_calculation_preview",
    "create-planning-signal": "open_create_planning_signal",
}

_ATTENTION_DEFINITIONS: Final[tuple[MeridianAttentionDefinition, ...]] = (
    MeridianAttentionDefinition(
        code="meridian_evidence_review_pending",
        label="Evidence review needs teacher attention",
        task_id="new-evidence",
        action_id=_ACTION_BY_TASK["new-evidence"],
        count_unit="work_review_scopes",
        category_order=0,
    ),
    MeridianAttentionDefinition(
        code="meridian_membership_review_pending",
        label="Grade Item membership needs teacher review",
        task_id="grade-items",
        action_id=_ACTION_BY_TASK["grade-items"],
        count_unit="membership_review_scopes",
        category_order=0,
    ),
    MeridianAttentionDefinition(
        code="meridian_attempt_decision_pending",
        label="Applicable attempt decisions are pending",
        task_id="attempt-decisions",
        action_id=_ACTION_BY_TASK["attempt-decisions"],
        count_unit="attempt_decision_scopes",
        category_order=0,
    ),
    MeridianAttentionDefinition(
        code="meridian_contract_unsupported",
        label="Unsupported evidence contracts need teacher review",
        task_id="exclusions",
        action_id=_ACTION_BY_TASK["exclusions"],
        count_unit="evidence_review_scopes",
        category_order=0,
    ),
    MeridianAttentionDefinition(
        code="meridian_source_withdrawn",
        label="Withdrawn evidence sources need teacher review",
        task_id="exclusions",
        action_id=_ACTION_BY_TASK["exclusions"],
        count_unit="source_review_scopes",
        category_order=1,
    ),
    MeridianAttentionDefinition(
        code="meridian_source_superseded",
        label="Superseded evidence sources need teacher review",
        task_id="exclusions",
        action_id=_ACTION_BY_TASK["exclusions"],
        count_unit="source_review_scopes",
        category_order=2,
    ),
    MeridianAttentionDefinition(
        code="meridian_native_value_unmapped",
        label="Applicable native values need mapping review",
        task_id="standards-review",
        action_id=_ACTION_BY_TASK["standards-review"],
        count_unit="mapping_inputs",
        category_order=0,
    ),
    MeridianAttentionDefinition(
        code="meridian_grade_item_calculation_stale",
        label="Grade Item proficiency calculations are stale",
        task_id="calculation-preview",
        action_id=_ACTION_BY_TASK["calculation-preview"],
        count_unit="grade_item_proficiency_targets",
        category_order=0,
    ),
    MeridianAttentionDefinition(
        code="meridian_academic_period_calculation_stale",
        label="Academic Period proficiency calculations are stale",
        task_id="calculation-preview",
        action_id=_ACTION_BY_TASK["calculation-preview"],
        count_unit="academic_period_proficiency_targets",
        category_order=1,
    ),
    MeridianAttentionDefinition(
        code="meridian_planning_review_pending",
        label="Planning previews are awaiting teacher review",
        task_id="create-planning-signal",
        action_id=_ACTION_BY_TASK["create-planning-signal"],
        count_unit="planning_review_scopes",
        category_order=0,
    ),
    MeridianAttentionDefinition(
        code="meridian_planning_review_selection_pending",
        label="Accepted planning reviews await explicit selection",
        task_id="create-planning-signal",
        action_id=_ACTION_BY_TASK["create-planning-signal"],
        count_unit="planning_review_scopes",
        category_order=1,
    ),
    MeridianAttentionDefinition(
        code="meridian_planning_review_stale",
        label="Selected planning reviews need fresh review",
        task_id="create-planning-signal",
        action_id=_ACTION_BY_TASK["create-planning-signal"],
        count_unit="planning_review_scopes",
        category_order=2,
    ),
)

_DEFINITION_BY_CODE: Final[dict[MeridianAttentionCode, MeridianAttentionDefinition]] = {
    definition.code: definition for definition in _ATTENTION_DEFINITIONS
}
_TASK_ORDER: Final[dict[TeacherWorkflowTaskId, int]] = {
    task_id: index for index, task_id in enumerate(TEACHER_WORKFLOW_TASK_IDS)
}


def meridian_attention_definitions() -> tuple[MeridianAttentionDefinition, ...]:
    """Return the complete stable issue #43 attention vocabulary in display order."""

    return _ATTENTION_DEFINITIONS


def attention_definition(code: MeridianAttentionCode) -> MeridianAttentionDefinition:
    """Resolve one stable attention category or reject an unknown runtime value."""

    definition = _DEFINITION_BY_CODE.get(code)
    if definition is None:
        raise MeridianAttentionValidationError(
            f"Unsupported Meridian attention code: {code!r}."
        )
    return definition


def build_meridian_attention_summary(
    items: tuple[MeridianAttentionItem, ...],
) -> MeridianAttentionSummary:
    """Canonicalize one already-derived set of aggregate attention facts."""

    normalized = tuple(items)
    if any(not isinstance(item, MeridianAttentionItem) for item in normalized):
        raise MeridianAttentionValidationError(
            "items must contain only MeridianAttentionItem values."
        )
    ordered = tuple(sorted(normalized, key=_item_order_key))
    return MeridianAttentionSummary(items=ordered)


def merge_meridian_attention_summaries(
    summaries: tuple[MeridianAttentionSummary, ...],
) -> MeridianAttentionSummary:
    """Merge successful scopes by stable code without inventing class context."""

    normalized = tuple(summaries)
    if any(not isinstance(summary, MeridianAttentionSummary) for summary in normalized):
        raise MeridianAttentionValidationError(
            "summaries must contain only MeridianAttentionSummary values."
        )

    totals: dict[MeridianAttentionCode, int] = {}
    class_contexts: dict[MeridianAttentionCode, set[str | None]] = {}
    for summary in normalized:
        summary.__post_init__()
        for item in summary.items:
            totals[item.code] = totals.get(item.code, 0) + item.count
            class_contexts.setdefault(item.code, set()).add(item.class_id)

    merged: list[MeridianAttentionItem] = []
    for code, count in totals.items():
        contexts = class_contexts[code]
        class_id = next(iter(contexts)) if len(contexts) == 1 else None
        merged.append(
            MeridianAttentionItem(
                code=code,
                count=count,
                class_id=class_id,
            )
        )
    return build_meridian_attention_summary(tuple(merged))


def meridian_attention_summary_to_dict(
    summary: MeridianAttentionSummary,
) -> dict[str, object]:
    """Return deterministic JSON-ready native attention without student payloads."""

    if not isinstance(summary, MeridianAttentionSummary):
        raise TypeError("summary must be a MeridianAttentionSummary.")
    summary.__post_init__()
    return {
        "schema_version": PROFICIENCY_ATTENTION_SCHEMA_VERSION,
        "items": [
            {
                "code": item.code,
                "label": item.definition.label,
                "count": item.count,
                "count_unit": item.definition.count_unit,
                "task_id": item.definition.task_id,
                "action_id": item.definition.action_id,
                "class_id": item.class_id,
            }
            for item in summary.items
        ],
    }


def _item_order_key(item: MeridianAttentionItem) -> tuple[int, int, str]:
    definition = attention_definition(item.code)
    return (
        _TASK_ORDER[definition.task_id],
        definition.category_order,
        definition.code,
    )


__all__ = [
    "MAX_MERIDIAN_ATTENTION_COUNT",
    "PROFICIENCY_ATTENTION_SCHEMA_VERSION",
    "MeridianAttentionCode",
    "MeridianAttentionCountUnit",
    "MeridianAttentionDefinition",
    "MeridianAttentionItem",
    "MeridianAttentionSummary",
    "MeridianAttentionValidationError",
    "attention_definition",
    "build_meridian_attention_summary",
    "meridian_attention_definitions",
    "meridian_attention_summary_to_dict",
    "merge_meridian_attention_summaries",
]
