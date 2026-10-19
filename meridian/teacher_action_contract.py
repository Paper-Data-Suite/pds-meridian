"""Typed, side-effect-free contract for #122 teacher actions.

This module does not read, write, authorize, select, or verify canonical state.
A future domain adapter must independently revalidate the bound authorities and
load the selected canonical record before constructing a verified outcome.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Final, Literal, TypeAlias

ActionKind: TypeAlias = Literal[
    "grade_item",
    "grade_item_membership",
    "eligibility",
    "attempt_policy",
    "attempt_decision",
    "standards_association",
    "proficiency_result",
]
ActionStatus: TypeAlias = Literal[
    "blocked_before_write",
    "written_not_current",
    "current_unverified",
    "applied",
    "already_applied",
    "conflict_requires_review",
    "recovery_required",
]
CurrentState: TypeAlias = Literal["not_checked", "not_current", "unknown", "matches"]
SelectionDisposition: TypeAlias = Literal[
    "not_attempted", "created", "updated", "existing", "unknown"
]
WriteDisposition: TypeAlias = Literal["created", "existing"]
ActionStage: TypeAlias = Literal[
    "preflight",
    "receipt_prepared",
    "write",
    "selection_preview",
    "selection_commit",
    "verification",
    "receipt_finalized",
]
StageDisposition: TypeAlias = Literal["completed", "blocked", "unknown"]
ActorSource: TypeAlias = Literal["saved", "temporary"]

_SHA256: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}\Z")
_KEY: Final[re.Pattern[str]] = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_ACTION_ID: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{32}\Z")
_STATUS: Final[frozenset[str]] = frozenset(
    {
        "blocked_before_write",
        "written_not_current",
        "current_unverified",
        "applied",
        "already_applied",
        "conflict_requires_review",
        "recovery_required",
    }
)
_KINDS: Final[frozenset[str]] = frozenset(
    {
        "grade_item",
        "grade_item_membership",
        "eligibility",
        "attempt_policy",
        "attempt_decision",
        "standards_association",
        "proficiency_result",
    }
)
_STAGES: Final[frozenset[str]] = frozenset(
    {
        "preflight",
        "receipt_prepared",
        "write",
        "selection_preview",
        "selection_commit",
        "verification",
        "receipt_finalized",
    }
)


class TeacherActionContractError(ValueError):
    """The in-memory reviewed-action/result contract is invalid."""

    code = "teacher_action.contract_invalid"


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise TeacherActionContractError(f"{name} must be lowercase SHA-256.")
    return value


def _key(value: object, name: str) -> str:
    if not isinstance(value, str) or _KEY.fullmatch(value) is None:
        raise TeacherActionContractError(f"{name} must be a bounded key.")
    return value


def _id(value: object, name: str) -> str:
    # Values are *data*, never filesystem path components. Domain adapters must
    # also apply their Core/canonical identifiers and authority validations.
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or value != value.strip()
        or unicodedata.normalize("NFC", value) != value
        or any(unicodedata.category(ch).startswith("C") for ch in value)
    ):
        raise TeacherActionContractError(f"{name} is not a bounded identifier.")
    return value


def _revision(value: object, name: str) -> int:
    if type(value) is not int or not 1 <= value <= 1_000_000_000:
        raise TeacherActionContractError(f"{name} must be a positive revision.")
    return value


def _optional_revision(value: object, name: str) -> int | None:
    return None if value is None else _revision(value, name)


def _pointer(revision: int | None, digest: str | None, name: str) -> None:
    if (revision is None) != (digest is None):
        raise TeacherActionContractError(
            f"{name} needs both revision and digest, or neither."
        )
    _optional_revision(revision, f"{name} revision")
    if digest is not None:
        _digest(digest, f"{name} digest")


@dataclass(frozen=True, slots=True)
class TeacherActionScope:
    """One class and academic context; fingerprint is NOT authorization."""

    workspace_sha256: str
    class_id: str
    grade_item_id: str
    school_year: str | None = None
    academic_period_id: str | None = None
    calendar_sha256: str | None = None
    work_identity_sha256: str | None = None

    def __post_init__(self) -> None:
        _digest(self.workspace_sha256, "workspace_sha256")
        _id(self.class_id, "class_id")
        _id(self.grade_item_id, "grade_item_id")
        if self.school_year is not None:
            _id(self.school_year, "school_year")
        if self.academic_period_id is not None:
            _id(self.academic_period_id, "academic_period_id")
            if self.school_year is None or self.calendar_sha256 is None:
                raise TeacherActionContractError(
                    "Academic period requires a school year and calendar digest."
                )
        if self.calendar_sha256 is not None:
            _digest(self.calendar_sha256, "calendar_sha256")
        if self.work_identity_sha256 is not None:
            _digest(self.work_identity_sha256, "work_identity_sha256")


@dataclass(frozen=True, slots=True)
class TeacherActionActor:
    """Stable #121 attribution binding; neither identity nor profile grants access."""

    actor_id: str
    profile_sha256: str
    source: ActorSource

    def __post_init__(self) -> None:
        _id(self.actor_id, "actor_id")
        _digest(self.profile_sha256, "profile_sha256")
        if self.source not in ("saved", "temporary"):
            raise TeacherActionContractError("Unknown actor source.")


@dataclass(frozen=True, slots=True)
class TeacherActionBasis:
    """One exact dependency: source, permission, period, or policy observation."""

    role: str
    identity_sha256: str
    content_sha256: str
    revision: int | None = None
    selected_revision: int | None = None
    selected_sha256: str | None = None

    def __post_init__(self) -> None:
        _key(self.role, "basis role")
        _digest(self.identity_sha256, "basis identity_sha256")
        _digest(self.content_sha256, "basis content_sha256")
        _optional_revision(self.revision, "basis revision")
        _pointer(self.selected_revision, self.selected_sha256, "basis selection")


@dataclass(frozen=True, slots=True)
class TeacherActionTarget:
    """Exact proposed immutable revision and reviewed CAS selection baseline."""

    family: ActionKind
    identity_sha256: str
    revision: int
    candidate_sha256: str
    expected_current_revision: int | None
    expected_current_sha256: str | None

    def __post_init__(self) -> None:
        if self.family not in _KINDS:
            raise TeacherActionContractError("Unknown action target family.")
        _digest(self.identity_sha256, "target identity_sha256")
        _revision(self.revision, "target revision")
        _digest(self.candidate_sha256, "target candidate_sha256")
        _pointer(
            self.expected_current_revision,
            self.expected_current_sha256,
            "expected current target",
        )


@dataclass(frozen=True, slots=True)
class TeacherActionPreview:
    """Read-only review token. Execution must use the bound domain preview too.

    A fingerprint alone is not permission to execute, proof of a persisted
    revision, or a substitute for a live Core/producer/current-selection read.
    """

    action_id: str
    kind: ActionKind
    scope: TeacherActionScope
    actor: TeacherActionActor
    target: TeacherActionTarget
    basis: tuple[TeacherActionBasis, ...]
    reviewed_decision_sha256: str
    make_current: bool = True
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not _ACTION_ID.fullmatch(
            self.action_id
        ):
            raise TeacherActionContractError(
                "action_id must be 32 lowercase hex digits."
            )
        if self.schema_version != 1 or type(self.schema_version) is not int:
            raise TeacherActionContractError("Unsupported action preview schema.")
        if self.kind not in _KINDS or self.kind != self.target.family:
            raise TeacherActionContractError("Action and target families differ.")
        if not isinstance(self.scope, TeacherActionScope):
            raise TeacherActionContractError("scope must be TeacherActionScope.")
        if not isinstance(self.actor, TeacherActionActor):
            raise TeacherActionContractError("actor must be TeacherActionActor.")
        if not isinstance(self.target, TeacherActionTarget):
            raise TeacherActionContractError("target must be TeacherActionTarget.")
        if not isinstance(self.basis, tuple) or not self.basis:
            raise TeacherActionContractError("Exact dependency bindings are required.")
        if any(not isinstance(item, TeacherActionBasis) for item in self.basis):
            raise TeacherActionContractError("Every basis must be a typed binding.")
        roles = tuple(item.role for item in self.basis)
        if len(roles) != len(set(roles)) or tuple(sorted(roles)) != roles:
            raise TeacherActionContractError(
                "Basis roles must be unique and deterministically sorted."
            )
        _digest(self.reviewed_decision_sha256, "reviewed_decision_sha256")
        if type(self.make_current) is not bool:
            raise TeacherActionContractError("make_current must be boolean.")

    @property
    def intent_sha256(self) -> str:
        """Deterministic scope/actor/intent digest across process restarts.

        The opaque action_id is intentionally excluded so independent attempts
        can detect an identical reviewed intent. Adapters still compare every
        canonical source and selected record before reusing history.
        """
        content = {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "scope": asdict(self.scope),
            "actor": asdict(self.actor),
            "target": asdict(self.target),
            "basis": [asdict(item) for item in self.basis],
            "reviewed_decision_sha256": self.reviewed_decision_sha256,
            "make_current": self.make_current,
        }
        raw = json.dumps(
            content, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class TeacherActionRecord:
    """Exact canonical record observed as written or already persisted."""

    family: ActionKind
    identity_sha256: str
    revision: int
    sha256: str
    write_disposition: WriteDisposition

    def __post_init__(self) -> None:
        if self.family not in _KINDS:
            raise TeacherActionContractError("Unknown stored record family.")
        _digest(self.identity_sha256, "record identity_sha256")
        _revision(self.revision, "record revision")
        _digest(self.sha256, "record sha256")
        if self.write_disposition not in ("created", "existing"):
            raise TeacherActionContractError("Unknown record write disposition.")

    def matches_target(self, target: TeacherActionTarget) -> bool:
        return (
            self.family == target.family
            and self.identity_sha256 == target.identity_sha256
            and self.revision == target.revision
            and self.sha256 == target.candidate_sha256
        )


@dataclass(frozen=True, slots=True)
class TeacherActionCheckpoint:
    """Privacy-minimal stage trace for the eventual durable receipt."""

    stage: ActionStage
    disposition: StageDisposition
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in _STAGES:
            raise TeacherActionContractError("Unknown checkpoint stage.")
        if self.disposition not in ("completed", "blocked", "unknown"):
            raise TeacherActionContractError("Unknown checkpoint disposition.")
        if self.reason_code is not None:
            _key(self.reason_code, "checkpoint reason_code")


@dataclass(frozen=True, slots=True)
class TeacherActionResult:
    """Truthful lifecycle result; verification must come from canonical reads."""

    action_id: str
    intent_sha256: str
    target: TeacherActionTarget
    status: ActionStatus
    persisted: tuple[TeacherActionRecord, ...]
    current_state: CurrentState
    current_record: TeacherActionRecord | None
    selection_disposition: SelectionDisposition
    checkpoints: tuple[TeacherActionCheckpoint, ...] = ()
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, str) or not _ACTION_ID.fullmatch(
            self.action_id
        ):
            raise TeacherActionContractError("Invalid outcome action_id.")
        _digest(self.intent_sha256, "intent_sha256")
        if not isinstance(self.target, TeacherActionTarget):
            raise TeacherActionContractError("Invalid outcome target.")
        if self.status not in _STATUS:
            raise TeacherActionContractError("Unknown action result status.")
        if not isinstance(self.persisted, tuple) or any(
            not isinstance(item, TeacherActionRecord) for item in self.persisted
        ):
            raise TeacherActionContractError("Persisted records must be a typed tuple.")
        identities = {
            (item.family, item.identity_sha256, item.revision)
            for item in self.persisted
        }
        if len(identities) != len(self.persisted):
            raise TeacherActionContractError("Duplicate persisted record identity.")
        if self.current_state not in (
            "not_checked",
            "not_current",
            "unknown",
            "matches",
        ):
            raise TeacherActionContractError("Unknown canonical current state.")
        if self.selection_disposition not in (
            "not_attempted",
            "created",
            "updated",
            "existing",
            "unknown",
        ):
            raise TeacherActionContractError("Unknown selection disposition.")
        if self.current_record is not None and not isinstance(
            self.current_record, TeacherActionRecord
        ):
            raise TeacherActionContractError("Invalid canonical current record.")
        if not isinstance(self.checkpoints, tuple) or any(
            not isinstance(item, TeacherActionCheckpoint) for item in self.checkpoints
        ):
            raise TeacherActionContractError("Invalid checkpoint trace.")
        if self.reason_code is not None:
            _key(self.reason_code, "reason_code")
        match = self.current_record is not None and self.current_record.matches_target(
            self.target
        )
        if self.current_state == "matches" and not match:
            raise TeacherActionContractError(
                "Canonical match requires the exact target revision and digest."
            )
        if self.current_state == "not_current" and match:
            raise TeacherActionContractError(
                "Exact canonical current target contradicts not_current."
            )
        if self.current_state in ("not_checked", "unknown") and self.current_record:
            raise TeacherActionContractError(
                "Unverified current state must not carry a claimed current record."
            )
        target_persisted = any(x.matches_target(self.target) for x in self.persisted)
        success = self.status in ("applied", "already_applied")
        if success:
            if (
                not target_persisted
                or self.current_state != "matches"
                or self.selection_disposition not in ("created", "updated", "existing")
                or self.reason_code is not None
            ):
                raise TeacherActionContractError(
                    "Applied outcomes require an exact persisted and verified current "
                    "target with a known selection disposition."
                )
            if self.status == "already_applied" and (
                self.selection_disposition != "existing"
                or not any(
                    item.matches_target(self.target)
                    and item.write_disposition == "existing"
                    for item in self.persisted
                )
            ):
                raise TeacherActionContractError(
                    "Already-applied requires existing canonical record and selection."
                )
        elif self.reason_code is None:
            raise TeacherActionContractError("Non-success outcomes need a reason_code.")
        if self.status == "blocked_before_write" and (
            self.persisted
            or self.selection_disposition != "not_attempted"
            or self.current_state != "not_checked"
        ):
            raise TeacherActionContractError(
                "A pre-write block cannot claim a canonical mutation or inspection."
            )
        if self.status == "written_not_current" and (
            not target_persisted or self.current_state != "not_current"
        ):
            raise TeacherActionContractError(
                "Written-not-current requires exact persistence and "
                "canonical non-current."
            )
        if self.status == "current_unverified" and (
            not target_persisted or self.current_state != "unknown"
        ):
            raise TeacherActionContractError(
                "Current-unverified requires exact persistence and uncertain current."
            )
        if self.status in ("conflict_requires_review", "recovery_required") and (
            self.current_state == "matches"
        ):
            raise TeacherActionContractError(
                "An unresolved result cannot claim fully verified application."
            )

    @property
    def succeeded(self) -> bool:
        return self.status in ("applied", "already_applied")


def teacher_action_outcome_message(result: TeacherActionResult) -> str:
    """Safe terse teacher copy, never inferred grades or source data."""
    if result.status == "applied":
        return "Saved and made current. The exact current record was verified."
    if result.status == "already_applied":
        return "Already applied. The exact current record was verified."
    if result.status == "blocked_before_write":
        return "Blocked before writing. No action record was changed."
    if result.status == "written_not_current":
        return (
            "Saved, but not current. This new decision is not yet the selected "
            "decision. Review changes or resume the exact selection."
        )
    if result.status == "current_unverified":
        return (
            "Saved, but current status could not be verified. "
            "Refresh canonical state before proceeding."
        )
    if result.status == "conflict_requires_review":
        return "The reviewed basis changed. Review a fresh preview before applying."
    return "Recovery required. Check canonical history before retrying."


__all__ = (
    "ActionKind",
    "ActionStatus",
    "TeacherActionActor",
    "TeacherActionBasis",
    "TeacherActionCheckpoint",
    "TeacherActionContractError",
    "TeacherActionPreview",
    "TeacherActionRecord",
    "TeacherActionResult",
    "TeacherActionScope",
    "TeacherActionTarget",
    "teacher_action_outcome_message",
)
