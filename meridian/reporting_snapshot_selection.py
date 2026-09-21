"""Explicit digest-bound current-use selection for ReportingSnapshots.

Selection is separate mutable reporting authority.  Freezing or storing a
ReportingSnapshot never selects it.  One selector is scoped to a class,
reporting-definition family, Academic Period, and exact calendar revision.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, TypeAlias, cast

from pds_core.academic_periods import (
    AcademicPeriodRef,
    AcademicPeriodValidationError,
    academic_period_ref_from_dict,
    academic_period_ref_to_dict,
    validate_academic_period_ref,
)
from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_dir, class_module_dir

from meridian.reporting_snapshot import (
    ReportingActor,
    ReportingDefinitionReference,
    ReportingSnapshotReference,
    ReportingSnapshotValidationError,
    reporting_definition_reference_from_dict,
    reporting_definition_reference_to_dict,
    reporting_snapshot_reference_from_dict,
    reporting_snapshot_reference_to_dict,
)
from meridian.reporting_snapshot_storage import (
    ReportingSnapshotStorageError,
    StoredReportingSnapshot,
    load_reporting_snapshot,
)

REPORTING_SNAPSHOT_SELECTION_SCHEMA_VERSION: Final[str] = "1"
REPORTING_SNAPSHOT_SELECTION_RECORD_TYPE: Final[str] = (
    "meridian_reporting_snapshot_current_selection"
)
DEFAULT_MAXIMUM_REPORTING_SNAPSHOT_SELECTION_BYTES: Final[int] = 64 * 1024
MAXIMUM_REPORTING_SNAPSHOT_SELECTION_RATIONALE_LENGTH: Final[int] = 2000

ReportingSnapshotSelectionDisposition: TypeAlias = Literal[
    "created", "updated", "existing"
]

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_SELECTION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "record_type",
        "class_id",
        "definition_id",
        "target_period",
        "calendar_revision",
        "selection_revision",
        "snapshot_reference",
        "definition_reference",
        "actor",
        "rationale",
        "decided_at",
        "previous_selection",
    }
)
_REFERENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "class_id",
        "definition_id",
        "target_period",
        "calendar_revision",
        "selection_revision",
        "selection_sha256",
    }
)
_ACTOR_KEYS: Final[frozenset[str]] = frozenset({"kind", "actor_id"})


class ReportingSnapshotSelectionError(RuntimeError):
    """Base error for current-use ReportingSnapshot selection."""

    code: str = "reporting_snapshot.selection_error"


class ReportingSnapshotSelectionValidationError(
    ReportingSnapshotSelectionError, ValueError
):
    """Raised for invalid selector API arguments or model values."""

    code = "reporting_snapshot.selection_invalid"


class ReportingSnapshotSelectionReadError(ReportingSnapshotSelectionError):
    """Raised when current-use selection cannot be read safely."""

    code = "reporting_snapshot.selection_read_failed"


class ReportingSnapshotSelectionWriteError(ReportingSnapshotSelectionError):
    """Raised when current-use selection cannot be persisted safely."""

    code = "reporting_snapshot.selection_write_failed"


class ReportingSnapshotSelectionConflictError(ReportingSnapshotSelectionError):
    """Raised when digest-bound compare-and-swap state is stale."""

    code = "reporting_snapshot.selection_conflict"


class ReportingSnapshotSelectionLockError(
    ReportingSnapshotSelectionConflictError
):
    """Raised when another selector writer owns the exact scope."""

    code = "reporting_snapshot.selection_locked"


class ReportingSnapshotSelectionIntegrityError(ReportingSnapshotSelectionError):
    """Raised when persisted selector state fails closed validation."""

    code = "reporting_snapshot.selection_integrity_failed"


class ReportingSnapshotSelectionTooLargeError(
    ReportingSnapshotSelectionReadError
):
    """Raised when current selector bytes exceed the configured bound."""

    code = "reporting_snapshot.selection_too_large"


@dataclass(frozen=True, slots=True)
class ReportingSnapshotSelectionReference:
    """Exact digest-bound identity for one observed selector state."""

    class_id: str
    definition_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    selection_revision: int
    selection_sha256: str

    def __post_init__(self) -> None:
        class_id = _identifier(self.class_id, "class_id")
        definition_id = _identifier(self.definition_id, "definition_id")
        period = _period(self.target_period)
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        selection_revision = _positive_int(
            self.selection_revision,
            "selection_revision",
        )
        selection_sha256 = _sha256(
            self.selection_sha256,
            "selection_sha256",
        )
        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "definition_id", definition_id)
        object.__setattr__(self, "target_period", period)
        object.__setattr__(self, "calendar_revision", calendar_revision)
        object.__setattr__(self, "selection_revision", selection_revision)
        object.__setattr__(self, "selection_sha256", selection_sha256)


@dataclass(frozen=True, slots=True)
class ReportingSnapshotCurrentSelection:
    """One canonical current-use selector decision for an exact report scope."""

    schema_version: str
    record_type: str
    class_id: str
    definition_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    selection_revision: int
    snapshot_reference: ReportingSnapshotReference
    definition_reference: ReportingDefinitionReference
    actor: ReportingActor
    rationale: str | None
    decided_at: datetime
    previous_selection: ReportingSnapshotSelectionReference | None

    def __post_init__(self) -> None:
        if self.schema_version != REPORTING_SNAPSHOT_SELECTION_SCHEMA_VERSION:
            raise ReportingSnapshotSelectionValidationError(
                'selection schema_version must be "1".'
            )
        if self.record_type != REPORTING_SNAPSHOT_SELECTION_RECORD_TYPE:
            raise ReportingSnapshotSelectionValidationError(
                "selection record_type must be "
                '"meridian_reporting_snapshot_current_selection".'
            )
        class_id = _identifier(self.class_id, "class_id")
        definition_id = _identifier(self.definition_id, "definition_id")
        period = _period(self.target_period)
        calendar_revision = _positive_int(
            self.calendar_revision,
            "calendar_revision",
        )
        selection_revision = _positive_int(
            self.selection_revision,
            "selection_revision",
        )
        if not isinstance(self.snapshot_reference, ReportingSnapshotReference):
            raise ReportingSnapshotSelectionValidationError(
                "snapshot_reference must be ReportingSnapshotReference."
            )
        snapshot_reference = ReportingSnapshotReference(
            class_id=self.snapshot_reference.class_id,
            snapshot_id=self.snapshot_reference.snapshot_id,
            snapshot_sha256=self.snapshot_reference.snapshot_sha256,
        )
        if snapshot_reference.class_id != class_id:
            raise ReportingSnapshotSelectionValidationError(
                "selected snapshot class must match selector class."
            )
        if not isinstance(
            self.definition_reference,
            ReportingDefinitionReference,
        ):
            raise ReportingSnapshotSelectionValidationError(
                "definition_reference must be ReportingDefinitionReference."
            )
        definition_reference = ReportingDefinitionReference(
            class_id=self.definition_reference.class_id,
            definition_id=self.definition_reference.definition_id,
            definition_revision=self.definition_reference.definition_revision,
            definition_sha256=self.definition_reference.definition_sha256,
        )
        if (
            definition_reference.class_id != class_id
            or definition_reference.definition_id != definition_id
        ):
            raise ReportingSnapshotSelectionValidationError(
                "selected definition must match selector scope."
            )
        if not isinstance(self.actor, ReportingActor):
            raise ReportingSnapshotSelectionValidationError(
                "actor must be ReportingActor."
            )
        actor = ReportingActor(self.actor.kind, self.actor.actor_id)
        rationale = _optional_bounded_text(
            self.rationale,
            "rationale",
            MAXIMUM_REPORTING_SNAPSHOT_SELECTION_RATIONALE_LENGTH,
        )
        decided_at = _aware_utc_datetime(self.decided_at, "decided_at")
        previous = self.previous_selection
        if selection_revision == 1:
            if previous is not None:
                raise ReportingSnapshotSelectionValidationError(
                    "initial selector revision must not identify prior state."
                )
        else:
            if not isinstance(previous, ReportingSnapshotSelectionReference):
                raise ReportingSnapshotSelectionValidationError(
                    "later selector revision requires exact prior selection."
                )
            previous = ReportingSnapshotSelectionReference(
                class_id=previous.class_id,
                definition_id=previous.definition_id,
                target_period=previous.target_period,
                calendar_revision=previous.calendar_revision,
                selection_revision=previous.selection_revision,
                selection_sha256=previous.selection_sha256,
            )
            if _selection_scope(previous) != (
                class_id,
                definition_id,
                period.school_year,
                period.period_id,
                calendar_revision,
            ):
                raise ReportingSnapshotSelectionValidationError(
                    "prior selection scope must match current selector scope."
                )
            if previous.selection_revision != selection_revision - 1:
                raise ReportingSnapshotSelectionValidationError(
                    "prior selection revision must immediately precede current."
                )

        object.__setattr__(self, "class_id", class_id)
        object.__setattr__(self, "definition_id", definition_id)
        object.__setattr__(self, "target_period", period)
        object.__setattr__(self, "calendar_revision", calendar_revision)
        object.__setattr__(self, "selection_revision", selection_revision)
        object.__setattr__(self, "snapshot_reference", snapshot_reference)
        object.__setattr__(self, "definition_reference", definition_reference)
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "decided_at", decided_at)
        object.__setattr__(self, "previous_selection", previous)


@dataclass(frozen=True, slots=True)
class StoredReportingSnapshotSelection:
    """One verified canonical current selector and exact bytes."""

    selection: ReportingSnapshotCurrentSelection
    selection_sha256: str
    path: Path = field(repr=False)
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.selection, ReportingSnapshotCurrentSelection):
            raise ReportingSnapshotSelectionValidationError(
                "selection must be ReportingSnapshotCurrentSelection."
            )
        digest = _sha256(self.selection_sha256, "selection_sha256")
        if type(self.content) is not bytes:
            raise ReportingSnapshotSelectionValidationError(
                "content must be immutable bytes."
            )
        if hashlib.sha256(self.content).hexdigest() != digest:
            raise ReportingSnapshotSelectionValidationError(
                "selection_sha256 does not match exact selector bytes."
            )
        try:
            decoded = reporting_snapshot_selection_from_json_bytes(self.content)
        except ReportingSnapshotSelectionError as error:
            raise ReportingSnapshotSelectionValidationError(
                "content is not a canonical current selector."
            ) from error
        if decoded != self.selection:
            raise ReportingSnapshotSelectionValidationError(
                "content does not decode to selection."
            )
        expected = reporting_snapshot_selection_relative_path(
            self.selection.class_id,
            self.selection.definition_id,
            self.selection.target_period,
            self.selection.calendar_revision,
        )
        if self.relative_path != expected:
            raise ReportingSnapshotSelectionValidationError(
                "relative_path is not the canonical selector location."
            )
        if self.path.name != "current.json":
            raise ReportingSnapshotSelectionValidationError(
                "selector path filename must be current.json."
            )
        object.__setattr__(self, "selection_sha256", digest)

    @property
    def reference(self) -> ReportingSnapshotSelectionReference:
        """Return the exact digest-bound selector state."""

        return ReportingSnapshotSelectionReference(
            class_id=self.selection.class_id,
            definition_id=self.selection.definition_id,
            target_period=self.selection.target_period,
            calendar_revision=self.selection.calendar_revision,
            selection_revision=self.selection.selection_revision,
            selection_sha256=self.selection_sha256,
        )


@dataclass(frozen=True, slots=True)
class ReportingSnapshotSelectionResult:
    """Result of an explicit digest-bound current-use selection."""

    disposition: ReportingSnapshotSelectionDisposition
    selection: StoredReportingSnapshotSelection
    snapshot: StoredReportingSnapshot

    def __post_init__(self) -> None:
        if self.disposition not in {"created", "updated", "existing"}:
            raise ReportingSnapshotSelectionValidationError(
                "selection disposition is invalid."
            )
        if not isinstance(self.selection, StoredReportingSnapshotSelection):
            raise ReportingSnapshotSelectionValidationError(
                "selection must be StoredReportingSnapshotSelection."
            )
        if not isinstance(self.snapshot, StoredReportingSnapshot):
            raise ReportingSnapshotSelectionValidationError(
                "snapshot must be StoredReportingSnapshot."
            )
        if self.selection.selection.snapshot_reference != self.snapshot.reference:
            raise ReportingSnapshotSelectionValidationError(
                "selection must identify the returned exact snapshot."
            )


def reporting_snapshot_selection_reference_to_dict(
    value: ReportingSnapshotSelectionReference,
) -> dict[str, object]:
    if not isinstance(value, ReportingSnapshotSelectionReference):
        raise ReportingSnapshotSelectionValidationError(
            "value must be ReportingSnapshotSelectionReference."
        )
    return {
        "class_id": value.class_id,
        "definition_id": value.definition_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "selection_revision": value.selection_revision,
        "selection_sha256": value.selection_sha256,
    }


def reporting_snapshot_selection_reference_from_dict(
    data: object,
) -> ReportingSnapshotSelectionReference:
    mapping = _exact_mapping(data, _REFERENCE_KEYS, "selection reference")
    try:
        period = academic_period_ref_from_dict(mapping["target_period"])
    except AcademicPeriodValidationError as error:
        raise ReportingSnapshotSelectionValidationError(
            f"selection reference target_period is invalid: {error}"
        ) from error
    return ReportingSnapshotSelectionReference(
        class_id=_require_str(mapping["class_id"], "class_id"),
        definition_id=_require_str(mapping["definition_id"], "definition_id"),
        target_period=period,
        calendar_revision=_require_int(
            mapping["calendar_revision"],
            "calendar_revision",
        ),
        selection_revision=_require_int(
            mapping["selection_revision"],
            "selection_revision",
        ),
        selection_sha256=_require_str(
            mapping["selection_sha256"],
            "selection_sha256",
        ),
    )


def reporting_snapshot_selection_to_dict(
    value: ReportingSnapshotCurrentSelection,
) -> dict[str, object]:
    if not isinstance(value, ReportingSnapshotCurrentSelection):
        raise ReportingSnapshotSelectionValidationError(
            "value must be ReportingSnapshotCurrentSelection."
        )
    return {
        "schema_version": value.schema_version,
        "record_type": value.record_type,
        "class_id": value.class_id,
        "definition_id": value.definition_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "selection_revision": value.selection_revision,
        "snapshot_reference": reporting_snapshot_reference_to_dict(
            value.snapshot_reference
        ),
        "definition_reference": reporting_definition_reference_to_dict(
            value.definition_reference
        ),
        "actor": {
            "kind": value.actor.kind,
            "actor_id": value.actor.actor_id,
        },
        "rationale": value.rationale,
        "decided_at": value.decided_at.astimezone(UTC).isoformat(),
        "previous_selection": (
            None
            if value.previous_selection is None
            else reporting_snapshot_selection_reference_to_dict(
                value.previous_selection
            )
        ),
    }


def reporting_snapshot_selection_from_dict(
    data: object,
) -> ReportingSnapshotCurrentSelection:
    mapping = _exact_mapping(data, _SELECTION_KEYS, "current selector")
    try:
        period = academic_period_ref_from_dict(mapping["target_period"])
        snapshot_reference = reporting_snapshot_reference_from_dict(
            mapping["snapshot_reference"]
        )
        definition_reference = reporting_definition_reference_from_dict(
            mapping["definition_reference"]
        )
    except (AcademicPeriodValidationError, ReportingSnapshotValidationError) as error:
        raise ReportingSnapshotSelectionValidationError(
            f"current selector contains an invalid exact reference: {error}"
        ) from error
    actor_mapping = _exact_mapping(mapping["actor"], _ACTOR_KEYS, "selection actor")
    try:
        actor = ReportingActor(
            kind=cast(Literal["teacher"], _require_str(actor_mapping["kind"], "kind")),
            actor_id=_require_str(actor_mapping["actor_id"], "actor_id"),
        )
    except ReportingSnapshotValidationError as error:
        raise ReportingSnapshotSelectionValidationError(
            f"selection actor is invalid: {error}"
        ) from error
    previous_data = mapping["previous_selection"]
    previous = (
        None
        if previous_data is None
        else reporting_snapshot_selection_reference_from_dict(previous_data)
    )
    return ReportingSnapshotCurrentSelection(
        schema_version=_require_str(mapping["schema_version"], "schema_version"),
        record_type=_require_str(mapping["record_type"], "record_type"),
        class_id=_require_str(mapping["class_id"], "class_id"),
        definition_id=_require_str(mapping["definition_id"], "definition_id"),
        target_period=period,
        calendar_revision=_require_int(
            mapping["calendar_revision"],
            "calendar_revision",
        ),
        selection_revision=_require_int(
            mapping["selection_revision"],
            "selection_revision",
        ),
        snapshot_reference=snapshot_reference,
        definition_reference=definition_reference,
        actor=actor,
        rationale=_optional_str(mapping["rationale"], "rationale"),
        decided_at=_datetime_from_text(mapping["decided_at"], "decided_at"),
        previous_selection=previous,
    )


def reporting_snapshot_selection_to_json_bytes(
    value: ReportingSnapshotCurrentSelection,
) -> bytes:
    return _canonical_json_bytes(reporting_snapshot_selection_to_dict(value))


def reporting_snapshot_selection_from_json_bytes(
    data: bytes,
) -> ReportingSnapshotCurrentSelection:
    decoded = _decode_json(data, "current selector")
    try:
        selection = reporting_snapshot_selection_from_dict(decoded)
    except ReportingSnapshotSelectionValidationError as error:
        raise ReportingSnapshotSelectionIntegrityError(
            f"Current selector is invalid: {error}"
        ) from error
    if reporting_snapshot_selection_to_json_bytes(selection) != data:
        raise ReportingSnapshotSelectionIntegrityError(
            "Current selector is not canonically encoded."
        )
    return selection


def reporting_snapshot_selection_sha256(
    value: ReportingSnapshotCurrentSelection,
) -> str:
    return hashlib.sha256(
        reporting_snapshot_selection_to_json_bytes(value)
    ).hexdigest()


def reporting_snapshot_selections_directory(
    workspace_root: str | Path,
    class_id: str,
) -> Path:
    return class_module_dir(
        workspace_root,
        _identifier(class_id, "class_id"),
        "meridian",
    ) / "reporting_snapshot_selections"


def reporting_snapshot_selection_scope_directory(
    workspace_root: str | Path,
    class_id: str,
    definition_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> Path:
    period = _period(target_period)
    return (
        reporting_snapshot_selections_directory(workspace_root, class_id)
        / _identifier(definition_id, "definition_id")
        / _identifier(period.school_year, "school_year")
        / _identifier(period.period_id, "period_id")
        / f"calendar_{_positive_int(calendar_revision, 'calendar_revision')}"
    )


def reporting_snapshot_selection_current_path(
    workspace_root: str | Path,
    class_id: str,
    definition_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> Path:
    return reporting_snapshot_selection_scope_directory(
        workspace_root,
        class_id,
        definition_id,
        target_period,
        calendar_revision,
    ) / "current.json"


def reporting_snapshot_selection_relative_path(
    class_id: str,
    definition_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> str:
    class_value = _identifier(class_id, "class_id")
    definition_value = _identifier(definition_id, "definition_id")
    period = _period(target_period)
    school_year = _identifier(period.school_year, "school_year")
    period_id = _identifier(period.period_id, "period_id")
    calendar = _positive_int(calendar_revision, "calendar_revision")
    return (
        f"classes/{class_value}/modules/meridian/reporting_snapshot_selections/"
        f"{definition_value}/{school_year}/{period_id}/calendar_{calendar}/"
        "current.json"
    )


def get_current_reporting_snapshot_selection_reference(
    workspace_root: str | Path,
    class_id: str,
    definition_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> ReportingSnapshotSelectionReference | None:
    """Return only explicit current-use selector authority for one scope."""

    stored = load_current_reporting_snapshot_selection(
        workspace_root,
        class_id,
        definition_id,
        target_period,
        calendar_revision,
    )
    return None if stored is None else stored.reference


def load_current_reporting_snapshot_selection(
    workspace_root: str | Path,
    class_id: str,
    definition_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> StoredReportingSnapshotSelection | None:
    """Load and verify one explicit current-use selector, if present."""

    root = _root(workspace_root)
    class_value = _identifier(class_id, "class_id")
    definition_value = _identifier(definition_id, "definition_id")
    period = _period(target_period)
    calendar = _positive_int(calendar_revision, "calendar_revision")
    _require_existing_core_class(root, class_value)
    scope = reporting_snapshot_selection_scope_directory(
        root,
        class_value,
        definition_value,
        period,
        calendar,
    )
    if not scope.exists():
        return None
    _validate_existing_directory_chain(root, scope)
    _validate_scope_directory(scope)
    path = scope / "current.json"
    if not path.exists():
        return None
    content = _read_bounded_regular_file(
        path,
        DEFAULT_MAXIMUM_REPORTING_SNAPSHOT_SELECTION_BYTES,
    )
    try:
        selection = reporting_snapshot_selection_from_json_bytes(content)
    except ReportingSnapshotSelectionError:
        raise
    except Exception as error:  # pragma: no cover - defensive boundary
        raise ReportingSnapshotSelectionIntegrityError(
            "Current selector is invalid."
        ) from error
    expected_scope = (
        class_value,
        definition_value,
        period.school_year,
        period.period_id,
        calendar,
    )
    if _selection_scope(selection) != expected_scope:
        raise ReportingSnapshotSelectionIntegrityError(
            "Current selector scope does not match its canonical path."
        )
    digest = hashlib.sha256(content).hexdigest()
    stored = StoredReportingSnapshotSelection(
        selection=selection,
        selection_sha256=digest,
        path=path,
        relative_path=reporting_snapshot_selection_relative_path(
            class_value,
            definition_value,
            period,
            calendar,
        ),
        content=content,
    )
    _verify_selected_snapshot(root, stored.selection)
    return stored


def load_current_reporting_snapshot(
    workspace_root: str | Path,
    class_id: str,
    definition_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
) -> StoredReportingSnapshot | None:
    """Load the exact snapshot explicitly selected for one reporting scope."""

    stored_selection = load_current_reporting_snapshot_selection(
        workspace_root,
        class_id,
        definition_id,
        target_period,
        calendar_revision,
    )
    if stored_selection is None:
        return None
    reference = stored_selection.selection.snapshot_reference
    try:
        stored_snapshot = load_reporting_snapshot(
            workspace_root,
            reference.class_id,
            reference.snapshot_id,
        )
    except ReportingSnapshotStorageError as error:
        raise ReportingSnapshotSelectionIntegrityError(
            "Selected ReportingSnapshot is unavailable or invalid."
        ) from error
    if stored_snapshot.snapshot_sha256 != reference.snapshot_sha256:
        raise ReportingSnapshotSelectionIntegrityError(
            "Selected ReportingSnapshot digest does not match selector."
        )
    return stored_snapshot


def select_reporting_snapshot(
    workspace_root: str | Path,
    snapshot_reference: ReportingSnapshotReference,
    *,
    actor: ReportingActor,
    rationale: str | None,
    decided_at: datetime,
    expected_current: ReportingSnapshotSelectionReference | None,
) -> ReportingSnapshotSelectionResult:
    """Explicitly select one exact stored snapshot using digest-bound CAS."""

    if not isinstance(snapshot_reference, ReportingSnapshotReference):
        raise ReportingSnapshotSelectionValidationError(
            "snapshot_reference must be ReportingSnapshotReference."
        )
    target_reference = ReportingSnapshotReference(
        class_id=snapshot_reference.class_id,
        snapshot_id=snapshot_reference.snapshot_id,
        snapshot_sha256=snapshot_reference.snapshot_sha256,
    )
    if not isinstance(actor, ReportingActor):
        raise ReportingSnapshotSelectionValidationError(
            "actor must be ReportingActor."
        )
    selected_actor = ReportingActor(actor.kind, actor.actor_id)
    selected_rationale = _optional_bounded_text(
        rationale,
        "rationale",
        MAXIMUM_REPORTING_SNAPSHOT_SELECTION_RATIONALE_LENGTH,
    )
    selected_at = _aware_utc_datetime(decided_at, "decided_at")

    root = _root(workspace_root)
    try:
        target = load_reporting_snapshot(
            root,
            target_reference.class_id,
            target_reference.snapshot_id,
        )
    except ReportingSnapshotStorageError as error:
        raise ReportingSnapshotSelectionConflictError(
            "Selected ReportingSnapshot is unavailable or invalid."
        ) from error
    if target.reference != target_reference:
        raise ReportingSnapshotSelectionConflictError(
            "Selected ReportingSnapshot digest does not match stored bytes."
        )
    snapshot = target.snapshot
    if selected_at < snapshot.created_at:
        raise ReportingSnapshotSelectionValidationError(
            "decided_at must not be earlier than selected snapshot creation."
        )
    definition_id = snapshot.definition_reference.definition_id
    period = snapshot.target_period
    calendar = snapshot.calendar_revision
    expected = _normalize_expected_current(
        expected_current,
        snapshot.class_id,
        definition_id,
        period,
        calendar,
    )

    scope = reporting_snapshot_selection_scope_directory(
        root,
        snapshot.class_id,
        definition_id,
        period,
        calendar,
    )
    _ensure_directory_chain(root, scope)
    lock = scope / ".write.lock"
    _acquire_lock(lock)
    try:
        _validate_scope_directory(scope)
        current = load_current_reporting_snapshot_selection(
            root,
            snapshot.class_id,
            definition_id,
            period,
            calendar,
        )
        actual_reference = None if current is None else current.reference
        if actual_reference != expected:
            raise ReportingSnapshotSelectionConflictError(
                "Current ReportingSnapshot selection changed before commit."
            )
        if (
            current is not None
            and current.selection.snapshot_reference == target_reference
        ):
            return ReportingSnapshotSelectionResult(
                "existing",
                current,
                target,
            )

        revision = 1 if current is None else current.selection.selection_revision + 1
        candidate = ReportingSnapshotCurrentSelection(
            schema_version=REPORTING_SNAPSHOT_SELECTION_SCHEMA_VERSION,
            record_type=REPORTING_SNAPSHOT_SELECTION_RECORD_TYPE,
            class_id=snapshot.class_id,
            definition_id=definition_id,
            target_period=period,
            calendar_revision=calendar,
            selection_revision=revision,
            snapshot_reference=target_reference,
            definition_reference=snapshot.definition_reference,
            actor=selected_actor,
            rationale=selected_rationale,
            decided_at=selected_at,
            previous_selection=actual_reference,
        )
        _publish_selection(scope / "current.json", candidate)
        reloaded = load_current_reporting_snapshot_selection(
            root,
            snapshot.class_id,
            definition_id,
            period,
            calendar,
        )
        if reloaded is None or reloaded.selection != candidate:
            raise ReportingSnapshotSelectionIntegrityError(
                "Published ReportingSnapshot selection could not be verified."
            )
        return ReportingSnapshotSelectionResult(
            "created" if current is None else "updated",
            reloaded,
            target,
        )
    finally:
        _remove_lock(lock)


def _normalize_expected_current(
    value: ReportingSnapshotSelectionReference | None,
    class_id: str,
    definition_id: str,
    period: AcademicPeriodRef,
    calendar_revision: int,
) -> ReportingSnapshotSelectionReference | None:
    if value is None:
        return None
    if not isinstance(value, ReportingSnapshotSelectionReference):
        raise ReportingSnapshotSelectionValidationError(
            "expected_current must be ReportingSnapshotSelectionReference or None."
        )
    expected = ReportingSnapshotSelectionReference(
        class_id=value.class_id,
        definition_id=value.definition_id,
        target_period=value.target_period,
        calendar_revision=value.calendar_revision,
        selection_revision=value.selection_revision,
        selection_sha256=value.selection_sha256,
    )
    if _selection_scope(expected) != (
        class_id,
        definition_id,
        period.school_year,
        period.period_id,
        calendar_revision,
    ):
        raise ReportingSnapshotSelectionValidationError(
            "expected_current belongs to a different reporting scope."
        )
    return expected


def _verify_selected_snapshot(
    root: Path,
    selection: ReportingSnapshotCurrentSelection,
) -> StoredReportingSnapshot:
    reference = selection.snapshot_reference
    try:
        stored = load_reporting_snapshot(
            root,
            reference.class_id,
            reference.snapshot_id,
        )
    except ReportingSnapshotStorageError as error:
        raise ReportingSnapshotSelectionIntegrityError(
            "Current selector identifies an unavailable ReportingSnapshot."
        ) from error
    if stored.snapshot_sha256 != reference.snapshot_sha256:
        raise ReportingSnapshotSelectionIntegrityError(
            "Current selector snapshot digest does not match stored bytes."
        )
    snapshot = stored.snapshot
    if snapshot.definition_reference != selection.definition_reference:
        raise ReportingSnapshotSelectionIntegrityError(
            "Current selector definition does not match selected snapshot."
        )
    if (
        snapshot.class_id != selection.class_id
        or snapshot.definition_reference.definition_id != selection.definition_id
        or snapshot.target_period != selection.target_period
        or snapshot.calendar_revision != selection.calendar_revision
    ):
        raise ReportingSnapshotSelectionIntegrityError(
            "Current selector reporting scope does not match selected snapshot."
        )
    if selection.decided_at < snapshot.created_at:
        raise ReportingSnapshotSelectionIntegrityError(
            "Current selector predates selected ReportingSnapshot creation."
        )
    return stored


def _selection_scope(
    value: ReportingSnapshotCurrentSelection | ReportingSnapshotSelectionReference,
) -> tuple[str, str, str, str, int]:
    return (
        value.class_id,
        value.definition_id,
        value.target_period.school_year,
        value.target_period.period_id,
        value.calendar_revision,
    )


def _publish_selection(
    path: Path,
    selection: ReportingSnapshotCurrentSelection,
) -> None:
    if path.is_symlink():
        raise ReportingSnapshotSelectionIntegrityError(
            "Current selector path must not be a symlink."
        )
    content = reporting_snapshot_selection_to_json_bytes(selection)
    if len(content) > DEFAULT_MAXIMUM_REPORTING_SNAPSHOT_SELECTION_BYTES:
        raise ReportingSnapshotSelectionWriteError(
            "Current selector exceeds the canonical byte limit."
        )
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
        _fsync_directory_if_supported(path.parent)
    except OSError as error:
        raise ReportingSnapshotSelectionWriteError(
            "Could not publish current ReportingSnapshot selection."
        ) from error
    finally:
        if temporary is not None:
            _remove_file(temporary)


def _validate_scope_directory(scope: Path) -> None:
    if scope.is_symlink() or not scope.is_dir():
        raise ReportingSnapshotSelectionIntegrityError(
            "ReportingSnapshot selector scope is unsafe or not a directory."
        )
    allowed = {"current.json", ".write.lock"}
    try:
        entries = tuple(scope.iterdir())
    except OSError as error:
        raise ReportingSnapshotSelectionReadError(
            "Could not inspect ReportingSnapshot selector scope."
        ) from error
    for entry in entries:
        if entry.name not in allowed:
            raise ReportingSnapshotSelectionIntegrityError(
                "ReportingSnapshot selector scope contains an unexpected entry."
            )
        if entry.is_symlink() or not entry.is_file():
            raise ReportingSnapshotSelectionIntegrityError(
                "ReportingSnapshot selector entries must be regular files."
            )


def _root(workspace_root: str | Path) -> Path:
    if not isinstance(workspace_root, (str, Path)):
        raise ReportingSnapshotSelectionValidationError(
            "workspace_root must be a string or Path."
        )
    root = Path(os.path.abspath(os.fspath(workspace_root)))
    if not root.exists():
        raise ReportingSnapshotSelectionReadError("Workspace root does not exist.")
    if root.is_symlink() or not root.is_dir():
        raise ReportingSnapshotSelectionIntegrityError(
            "Workspace root must be a real directory, not a symlink."
        )
    return root


def _require_existing_core_class(root: Path, class_id: str) -> None:
    path = class_dir(root, class_id)
    if not path.exists():
        raise ReportingSnapshotSelectionReadError(
            "Core class workspace does not exist."
        )
    _validate_existing_directory_chain(root, path)


def _ensure_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise ReportingSnapshotSelectionIntegrityError(
                    "ReportingSnapshot selector directory chain is unsafe."
                )
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise ReportingSnapshotSelectionWriteError(
                    "Could not create ReportingSnapshot selector directory chain."
                ) from error


def _validate_existing_directory_chain(root: Path, target: Path) -> None:
    _require_containment(root, target)
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        if not current.exists():
            raise ReportingSnapshotSelectionReadError(
                "Required ReportingSnapshot selector directory does not exist."
            )
        if current.is_symlink() or not current.is_dir():
            raise ReportingSnapshotSelectionIntegrityError(
                "ReportingSnapshot selector directory chain is unsafe."
            )


def _require_containment(root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ReportingSnapshotSelectionValidationError(
            "ReportingSnapshot selector path escapes workspace root."
        ) from error


def _read_bounded_regular_file(path: Path, maximum_bytes: int) -> bytes:
    maximum = _positive_int(maximum_bytes, "maximum_bytes")
    if path.is_symlink():
        raise ReportingSnapshotSelectionIntegrityError(
            "Current selector must not be a symlink."
        )
    try:
        with path.open("rb") as source:
            if not path.is_file():
                raise ReportingSnapshotSelectionIntegrityError(
                    "Current selector path must be a regular file."
                )
            content = source.read(maximum + 1)
    except ReportingSnapshotSelectionError:
        raise
    except FileNotFoundError as error:
        raise ReportingSnapshotSelectionReadError(
            "Current selector does not exist."
        ) from error
    except OSError as error:
        raise ReportingSnapshotSelectionReadError(
            "Could not read current ReportingSnapshot selector."
        ) from error
    if len(content) > maximum:
        raise ReportingSnapshotSelectionTooLargeError(
            "Current selector exceeds configured byte limit."
        )
    return content


def _acquire_lock(path: Path) -> None:
    try:
        with path.open("xb") as output:
            output.write(b"meridian reporting snapshot selection lock\n")
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise ReportingSnapshotSelectionLockError(
            "Another writer owns this ReportingSnapshot selector scope."
        ) from error
    except OSError as error:
        raise ReportingSnapshotSelectionWriteError(
            "Could not acquire ReportingSnapshot selector lock."
        ) from error


def _remove_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as error:
        raise ReportingSnapshotSelectionWriteError(
            "Could not remove ReportingSnapshot selector lock."
        ) from error


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _fsync_directory_if_supported(path: Path) -> None:
    flags = getattr(os, "O_RDONLY", 0)
    if hasattr(os, "O_DIRECTORY"):
        flags |= cast(int, getattr(os, "O_DIRECTORY"))
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
            separators=(",", ": "),
        )
    except (TypeError, ValueError) as error:
        raise ReportingSnapshotSelectionValidationError(
            "Current selector cannot be represented as canonical JSON."
        ) from error
    return (text + "\n").encode("utf-8")


def _decode_json(data: bytes, label: str) -> object:
    if type(data) is not bytes:
        raise ReportingSnapshotSelectionIntegrityError(
            f"{label} must be immutable bytes."
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReportingSnapshotSelectionIntegrityError(
            f"{label} is not valid UTF-8."
        ) from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ReportingSnapshotSelectionIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as error:
        raise ReportingSnapshotSelectionIntegrityError(
            f"{label} is not valid JSON."
        ) from error


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReportingSnapshotSelectionIntegrityError(
                f"Duplicate JSON object key is invalid: {key!r}."
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ReportingSnapshotSelectionIntegrityError(
        f"Nonfinite JSON number is invalid: {value}."
    )


def _exact_mapping(
    data: object,
    keys: frozenset[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ReportingSnapshotSelectionValidationError(
            f"{label} must be a JSON object."
        )
    if frozenset(data) != keys:
        raise ReportingSnapshotSelectionValidationError(
            f"{label} does not use the exact schema."
        )
    if any(not isinstance(key, str) for key in data):
        raise ReportingSnapshotSelectionValidationError(
            f"{label} keys must be strings."
        )
    return cast(dict[str, object], data)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportingSnapshotSelectionValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise ReportingSnapshotSelectionValidationError(str(error)) from error


def _period(value: object) -> AcademicPeriodRef:
    if not isinstance(value, AcademicPeriodRef):
        raise ReportingSnapshotSelectionValidationError(
            "target_period must be AcademicPeriodRef."
        )
    try:
        period = validate_academic_period_ref(value)
    except AcademicPeriodValidationError as error:
        raise ReportingSnapshotSelectionValidationError(
            f"target_period is invalid: {error}"
        ) from error
    _identifier(period.school_year, "school_year")
    _identifier(period.period_id, "period_id")
    return period


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReportingSnapshotSelectionValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReportingSnapshotSelectionValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


def _optional_bounded_text(
    value: object,
    field_name: str,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReportingSnapshotSelectionValidationError(
            f"{field_name} must be a string or None."
        )
    cleaned = value.strip()
    if not cleaned:
        raise ReportingSnapshotSelectionValidationError(
            f"{field_name} must not be blank."
        )
    if len(cleaned) > maximum:
        raise ReportingSnapshotSelectionValidationError(
            f"{field_name} exceeds maximum length {maximum}."
        )
    return cleaned


def _aware_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ReportingSnapshotSelectionValidationError(
            f"{field_name} must be datetime."
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReportingSnapshotSelectionValidationError(
            f"{field_name} must be timezone-aware."
        )
    return value.astimezone(UTC)


def _datetime_from_text(value: object, field_name: str) -> datetime:
    text = _require_str(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ReportingSnapshotSelectionValidationError(
            f"{field_name} must be ISO-8601 datetime text."
        ) from error
    return _aware_utc_datetime(parsed, field_name)


def _require_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReportingSnapshotSelectionValidationError(
            f"{field_name} must be a string."
        )
    return value


def _optional_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReportingSnapshotSelectionValidationError(
            f"{field_name} must be an integer."
        )
    return value
