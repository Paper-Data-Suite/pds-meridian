"""Stable inert Meridian owner-action and destination catalog.

Issue #59 makes attention owner actions explicit module-owned identities rather
than accidental strings embedded in the attention vocabulary.  These records
are presentation-neutral and deliberately contain no executable routing data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, TypeAlias

from pds_core.identifiers import IdentifierValidationError, validate_identifier

MERIDIAN_OWNER_MODULE_ID: Final[str] = "meridian"

MeridianOwnerDestinationId: TypeAlias = Literal[
    "new-evidence",
    "grade-items",
    "attempt-decisions",
    "exclusions",
    "standards-review",
    "calculation-preview",
    "preview-grades",
    "snapshots",
    "create-planning-signal",
]

MeridianOwnerActionId: TypeAlias = Literal[
    "open_new_evidence",
    "open_grade_items",
    "open_attempt_decisions",
    "open_exclusions",
    "open_standards_review",
    "open_calculation_preview",
    "open_preview_grades",
    "open_snapshots",
    "open_create_planning_signal",
]

MERIDIAN_OWNER_DESTINATION_IDS: Final[tuple[MeridianOwnerDestinationId, ...]] = (
    "new-evidence",
    "grade-items",
    "attempt-decisions",
    "exclusions",
    "standards-review",
    "calculation-preview",
    "preview-grades",
    "snapshots",
    "create-planning-signal",
)

MERIDIAN_OWNER_ACTION_IDS: Final[tuple[MeridianOwnerActionId, ...]] = (
    "open_new_evidence",
    "open_grade_items",
    "open_attempt_decisions",
    "open_exclusions",
    "open_standards_review",
    "open_calculation_preview",
    "open_preview_grades",
    "open_snapshots",
    "open_create_planning_signal",
)


class MeridianOwnerActionValidationError(ValueError):
    """Raised when an owner-action identity is outside Meridian's catalog."""


def _bounded_text(value: object, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise MeridianOwnerActionValidationError(f"{field} must be a string.")
    if not value or value != value.strip():
        raise MeridianOwnerActionValidationError(
            f"{field} must be nonblank without surrounding whitespace."
        )
    if "\x00" in value or "\n" in value or "\r" in value:
        raise MeridianOwnerActionValidationError(
            f"{field} must be a control-free single-line string."
        )
    if len(value) > maximum:
        raise MeridianOwnerActionValidationError(
            f"{field} must be at most {maximum} characters."
        )
    return value


def _bounded_identifier(value: object, field: str, *, maximum: int) -> str:
    text = _bounded_text(value, field, maximum=maximum)
    try:
        return validate_identifier(text, field)
    except IdentifierValidationError as error:
        raise MeridianOwnerActionValidationError(str(error)) from error


@dataclass(frozen=True, slots=True)
class MeridianOwnerActionDefinition:
    """One stable action identity routed back to a Meridian-owned destination."""

    destination_id: MeridianOwnerDestinationId
    action_id: MeridianOwnerActionId
    label: str
    order: int

    def __post_init__(self) -> None:
        if self.destination_id not in MERIDIAN_OWNER_DESTINATION_IDS:
            raise MeridianOwnerActionValidationError(
                "Unsupported Meridian owner destination."
            )
        if self.action_id not in MERIDIAN_OWNER_ACTION_IDS:
            raise MeridianOwnerActionValidationError(
                "Unsupported Meridian owner action ID."
            )
        _bounded_identifier(self.destination_id, "destination_id", maximum=64)
        _bounded_identifier(self.action_id, "action_id", maximum=64)
        _bounded_text(self.label, "label", maximum=80)
        if (
            isinstance(self.order, bool)
            or not isinstance(self.order, int)
            or self.order < 0
        ):
            raise MeridianOwnerActionValidationError(
                "order must be a nonnegative integer."
            )

    @property
    def module_id(self) -> str:
        """Return the owning Core module identity without executable metadata."""

        return MERIDIAN_OWNER_MODULE_ID


_OWNER_ACTIONS: Final[tuple[MeridianOwnerActionDefinition, ...]] = (
    MeridianOwnerActionDefinition(
        "new-evidence",
        "open_new_evidence",
        "New Evidence",
        0,
    ),
    MeridianOwnerActionDefinition(
        "grade-items",
        "open_grade_items",
        "Grade Items",
        1,
    ),
    MeridianOwnerActionDefinition(
        "attempt-decisions",
        "open_attempt_decisions",
        "Attempt Decisions",
        2,
    ),
    MeridianOwnerActionDefinition(
        "exclusions",
        "open_exclusions",
        "Exclusions",
        3,
    ),
    MeridianOwnerActionDefinition(
        "standards-review",
        "open_standards_review",
        "Standards Review",
        4,
    ),
    MeridianOwnerActionDefinition(
        "calculation-preview",
        "open_calculation_preview",
        "Calculation Preview",
        5,
    ),
    MeridianOwnerActionDefinition(
        "preview-grades",
        "open_preview_grades",
        "Preview Grades",
        6,
    ),
    MeridianOwnerActionDefinition(
        "snapshots",
        "open_snapshots",
        "Snapshots",
        7,
    ),
    MeridianOwnerActionDefinition(
        "create-planning-signal",
        "open_create_planning_signal",
        "Create Planning Signal",
        8,
    ),
)


def _validate_catalog() -> None:
    destinations = tuple(item.destination_id for item in _OWNER_ACTIONS)
    actions = tuple(item.action_id for item in _OWNER_ACTIONS)
    orders = tuple(item.order for item in _OWNER_ACTIONS)
    if destinations != MERIDIAN_OWNER_DESTINATION_IDS:
        raise MeridianOwnerActionValidationError(
            "Owner-action destinations must match canonical destination order."
        )
    if actions != MERIDIAN_OWNER_ACTION_IDS:
        raise MeridianOwnerActionValidationError(
            "Owner-action IDs must match canonical action order."
        )
    if len(set(destinations)) != len(destinations):
        raise MeridianOwnerActionValidationError(
            "Owner-action destinations must be unique."
        )
    if len(set(actions)) != len(actions):
        raise MeridianOwnerActionValidationError("Owner-action IDs must be unique.")
    if orders != tuple(range(len(_OWNER_ACTIONS))):
        raise MeridianOwnerActionValidationError(
            "Owner-action order must be contiguous and deterministic."
        )


_validate_catalog()

_ACTION_BY_DESTINATION: Final = {
    item.destination_id: item for item in _OWNER_ACTIONS
}
_ACTION_BY_ID: Final = {item.action_id: item for item in _OWNER_ACTIONS}


def meridian_owner_action_definitions() -> tuple[MeridianOwnerActionDefinition, ...]:
    """Return the complete immutable owner-action catalog in stable order."""

    return _OWNER_ACTIONS


def owner_action_for_destination(
    destination_id: object,
) -> MeridianOwnerActionDefinition:
    """Resolve one declared destination without fallback or executable inference."""

    try:
        return _ACTION_BY_DESTINATION[destination_id]  # type: ignore[index]
    except (KeyError, TypeError) as error:
        raise MeridianOwnerActionValidationError(
            "Unsupported Meridian owner destination."
        ) from error


def owner_action_for_action_id(action_id: object) -> MeridianOwnerActionDefinition:
    """Resolve one declared action ID or fail closed for unknown identities."""

    try:
        return _ACTION_BY_ID[action_id]  # type: ignore[index]
    except (KeyError, TypeError) as error:
        raise MeridianOwnerActionValidationError(
            "Unsupported Meridian owner action ID."
        ) from error


__all__ = [
    "MERIDIAN_OWNER_ACTION_IDS",
    "MERIDIAN_OWNER_DESTINATION_IDS",
    "MERIDIAN_OWNER_MODULE_ID",
    "MeridianOwnerActionDefinition",
    "MeridianOwnerActionId",
    "MeridianOwnerActionValidationError",
    "MeridianOwnerDestinationId",
    "meridian_owner_action_definitions",
    "owner_action_for_action_id",
    "owner_action_for_destination",
]
