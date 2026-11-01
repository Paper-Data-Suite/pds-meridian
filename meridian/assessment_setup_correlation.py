"""#124 E2A: exact, serializable cross-action recovery correlation contract.

A correlation is an advisory witness, not an action receipt, authorization,
academic mutation or permission to resume. E2B must persist it before APPLY;
E2C must explicitly reconcile the original #122 action and canonical state.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, TypeAlias

from meridian.assessment_setup_preview import AssessmentSetupPreview
from meridian.assessment_setup_recovery import AssessmentSetupRecoveryInspection
from meridian.teacher_action_contract import TeacherActionActor
from meridian.teacher_action_guided import PreparedGuidedAction, _identity
from meridian.teacher_action_receipts import TeacherActionReceipt

CorrelationStage: TypeAlias = Literal["reviewed", "grade_bound", "membership_bound"]
CorrelationAdvice: TypeAlias = Literal[
    "not_started",
    "original_grade_action_pending",
    "original_membership_action_pending",
    "ready_verified",
    "requires_review",
]
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ACTION = re.compile(r"[0-9a-f]{32}\Z")
_MAX_BYTES = 8192
_SCHEMA = 1


class AssessmentSetupCorrelationError(ValueError):
    """Correlation cannot be proven against exact reviewed intent."""


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _strict_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise AssessmentSetupCorrelationError("Duplicate correlation JSON key.")
        result[key] = value
    return result


def _digest(value: str, field: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise AssessmentSetupCorrelationError(f"Invalid {field} digest.")
    return value


def _action(value: str | None, field: str) -> str | None:
    if value is not None and (
        not isinstance(value, str) or _ACTION.fullmatch(value) is None
    ):
        raise AssessmentSetupCorrelationError(f"Invalid {field} action ID.")
    return value


def _text(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not 0 < len(value) <= 256
        or value.strip() != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise AssessmentSetupCorrelationError(f"Invalid {field}.")
    return value


@dataclass(frozen=True, slots=True)
class AssessmentSetupCorrelation:
    """One exact reviewed setup, plus immutable #122 stage identifiers."""

    review_sha256: str
    workspace_sha256: str
    class_id: str
    school_year: str
    module_id: str
    work_id: str
    grade_item_id: str
    period_id: str
    registration_revision: int
    publication_id: str | None
    kind: Literal["create_and_link", "use_existing"]
    actor_id: str
    actor_profile_sha256: str
    grade_action_id: str | None
    grade_target_sha256: str | None
    membership_action_id: str | None
    membership_target_sha256: str | None
    schema_version: int = _SCHEMA

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != _SCHEMA:
            raise AssessmentSetupCorrelationError("Unsupported correlation schema.")
        for name in ("review_sha256", "workspace_sha256", "actor_profile_sha256"):
            _digest(getattr(self, name), name)
        for name in (
            "class_id",
            "school_year",
            "module_id",
            "work_id",
            "grade_item_id",
            "period_id",
            "actor_id",
        ):
            _text(getattr(self, name), name)
        if (
            type(self.registration_revision) is not int
            or self.registration_revision < 1
        ):
            raise AssessmentSetupCorrelationError("Invalid registration revision.")
        if self.kind not in ("create_and_link", "use_existing"):
            raise AssessmentSetupCorrelationError(
                "Only write-bearing setups are correlatable."
            )
        if self.publication_id is not None:
            _text(self.publication_id, "publication_id")
        _action(self.grade_action_id, "grade")
        _action(self.membership_action_id, "membership")
        if (self.grade_action_id is None) != (self.grade_target_sha256 is None):
            raise AssessmentSetupCorrelationError(
                "Incomplete Grade Item action witness."
            )
        if (self.membership_action_id is None) != (
            self.membership_target_sha256 is None
        ):
            raise AssessmentSetupCorrelationError(
                "Incomplete membership action witness."
            )
        if self.grade_target_sha256 is not None:
            _digest(self.grade_target_sha256, "grade_target")
        if self.membership_target_sha256 is not None:
            _digest(self.membership_target_sha256, "membership_target")
        if self.kind == "use_existing" and self.grade_action_id is not None:
            raise AssessmentSetupCorrelationError(
                "Existing setup cannot create a Grade Item."
            )
        if self.kind == "create_and_link" and (
            self.grade_action_id is None and self.membership_action_id is not None
        ):
            raise AssessmentSetupCorrelationError(
                "Membership cannot precede Grade Item binding."
            )
        if (
            self.grade_action_id is not None
            and self.grade_action_id == self.membership_action_id
        ):
            raise AssessmentSetupCorrelationError(
                "Both stages cannot share an action ID."
            )

    @property
    def stage(self) -> CorrelationStage:
        if self.membership_action_id is not None:
            return "membership_bound"
        if self.grade_action_id is not None:
            return "grade_bound"
        return "reviewed"

    @property
    def intent_sha256(self) -> str:
        """Stable across stage additions; excludes action IDs and target digests."""
        return hashlib.sha256(
            _json_bytes(
                {
                    "review": self.review_sha256,
                    "workspace": self.workspace_sha256,
                    "class": self.class_id,
                    "school_year": self.school_year,
                    "module": self.module_id,
                    "work": self.work_id,
                    "grade": self.grade_item_id,
                    "period": self.period_id,
                    "registration_revision": self.registration_revision,
                    "publication": self.publication_id,
                    "kind": self.kind,
                    "actor": self.actor_id,
                    "actor_profile": self.actor_profile_sha256,
                }
            )
        ).hexdigest()

    def to_json_bytes(self) -> bytes:
        payload: dict[str, object] = {
            key: getattr(self, key) for key in self.__dataclass_fields__
        }
        checksum = hashlib.sha256(_json_bytes(payload)).hexdigest()
        content = _json_bytes({"payload": payload, "payload_sha256": checksum})
        if len(content) > _MAX_BYTES:
            raise AssessmentSetupCorrelationError("Correlation exceeds size limit.")
        return content

    @classmethod
    def from_json_bytes(cls, content: bytes) -> AssessmentSetupCorrelation:
        if not isinstance(content, bytes) or not 0 < len(content) <= _MAX_BYTES:
            raise AssessmentSetupCorrelationError("Invalid correlation byte length.")
        try:
            value = json.loads(content.decode("ascii"), object_pairs_hook=_strict_pairs)
        except (UnicodeError, TypeError, ValueError) as error:
            raise AssessmentSetupCorrelationError(
                "Malformed correlation JSON."
            ) from error
        if not isinstance(value, dict) or set(value) != {"payload", "payload_sha256"}:
            raise AssessmentSetupCorrelationError("Invalid correlation envelope.")
        payload = value["payload"]
        if not isinstance(payload, dict) or set(payload) != set(
            cls.__dataclass_fields__
        ):
            raise AssessmentSetupCorrelationError("Unknown correlation payload fields.")
        if _json_bytes(value) != content:
            raise AssessmentSetupCorrelationError("Correlation JSON is noncanonical.")
        _digest(value["payload_sha256"], "payload")
        if hashlib.sha256(_json_bytes(payload)).hexdigest() != value["payload_sha256"]:
            raise AssessmentSetupCorrelationError("Correlation checksum mismatch.")
        try:
            return cls(**payload)
        except (TypeError, ValueError) as error:
            raise AssessmentSetupCorrelationError(
                "Invalid correlation fields."
            ) from error


def create_assessment_setup_correlation(
    workspace_root: Path,
    preview: AssessmentSetupPreview,
    actor: TeacherActionActor,
) -> AssessmentSetupCorrelation:
    """Bind review and saved actor without writing a receipt or academic state."""
    if not isinstance(workspace_root, Path) or not workspace_root.is_absolute():
        raise AssessmentSetupCorrelationError("Absolute workspace root required.")
    if not isinstance(preview, AssessmentSetupPreview) or not isinstance(
        actor, TeacherActionActor
    ):
        raise AssessmentSetupCorrelationError(
            "Reviewed setup and typed actor required."
        )
    if preview.kind not in ("create_and_link", "use_existing"):
        raise AssessmentSetupCorrelationError("Already-ready has no durable action.")
    if actor.source != "saved" or preview.actor_attribution != actor.actor_id:
        raise AssessmentSetupCorrelationError(
            "Recovery requires original saved attribution."
        )
    return AssessmentSetupCorrelation(
        review_sha256=preview.review_sha256,
        workspace_sha256=_identity("workspace", str(workspace_root.resolve())),
        class_id=preview.class_id,
        school_year=preview.school_year,
        module_id=preview.work.module_id,
        work_id=preview.work.work_id,
        grade_item_id=preview.grade_item_id,
        period_id=preview.marking_period_id,
        registration_revision=preview.registration_revision,
        publication_id=preview.publication_id,
        kind=preview.kind,
        actor_id=actor.actor_id,
        actor_profile_sha256=actor.profile_sha256,
        grade_action_id=None,
        grade_target_sha256=None,
        membership_action_id=None,
        membership_target_sha256=None,
    )


def verify_correlation_context(
    workspace_root: Path,
    correlation: AssessmentSetupCorrelation,
    preview: AssessmentSetupPreview,
    actor: TeacherActionActor,
) -> None:
    """Reconstruct immutable intent and compare it before any recovery choice."""
    current = create_assessment_setup_correlation(workspace_root, preview, actor)
    if correlation.intent_sha256 != current.intent_sha256:
        raise AssessmentSetupCorrelationError("Reviewed correlation intent changed.")


def bind_correlation_action(
    correlation: AssessmentSetupCorrelation,
    action: PreparedGuidedAction,
    *,
    family: Literal["grade_item", "grade_item_membership"],
) -> AssessmentSetupCorrelation:
    """Record original prepared action identity; never execute it here."""
    if not isinstance(correlation, AssessmentSetupCorrelation) or not isinstance(
        action, PreparedGuidedAction
    ):
        raise AssessmentSetupCorrelationError(
            "Typed correlation and #122 action required."
        )
    p = action.preview
    if (
        p.kind != family
        or p.target.family != family
        or p.scope.class_id != correlation.class_id
        or p.scope.workspace_sha256 != correlation.workspace_sha256
        or p.scope.grade_item_id != correlation.grade_item_id
        or p.actor.actor_id != correlation.actor_id
        or p.actor.source != "saved"
        or p.actor.profile_sha256 != correlation.actor_profile_sha256
    ):
        raise AssessmentSetupCorrelationError("#122 action scope/actor mismatch.")
    if family == "grade_item":
        if correlation.kind != "create_and_link" or correlation.stage != "reviewed":
            raise AssessmentSetupCorrelationError(
                "Grade Item stage already bound or invalid."
            )
        if p.target.revision != 1 or p.scope.school_year is not None:
            raise AssessmentSetupCorrelationError("Unexpected new Grade Item target.")
        return replace(
            correlation,
            grade_action_id=p.action_id,
            grade_target_sha256=p.target.candidate_sha256,
        )
    if correlation.membership_action_id is not None or (
        correlation.kind == "create_and_link" and correlation.grade_action_id is None
    ):
        raise AssessmentSetupCorrelationError("Membership stage is not available.")
    if (
        p.scope.school_year != correlation.school_year
        or p.scope.academic_period_id != correlation.period_id
        or p.scope.work_identity_sha256
        != _identity(
            "work",
            correlation.class_id,
            correlation.module_id,
            correlation.work_id,
        )
    ):
        raise AssessmentSetupCorrelationError("Membership scope changed.")
    return replace(
        correlation,
        membership_action_id=p.action_id,
        membership_target_sha256=p.target.candidate_sha256,
    )


@dataclass(frozen=True, slots=True)
class AssessmentSetupCorrelationInspection:
    """Pure advice; no property ever authorizes automatic selection or writing."""

    advice: CorrelationAdvice
    reason: str
    intent_sha256: str
    grade_action_id: str | None
    membership_action_id: str | None

    @property
    def may_resume_automatically(self) -> bool:
        return False


def inspect_assessment_setup_correlation(
    correlation: AssessmentSetupCorrelation,
    recovery: AssessmentSetupRecoveryInspection,
    receipts: tuple[TeacherActionReceipt, ...],
) -> AssessmentSetupCorrelationInspection:
    """Link exact stage receipts to E1 canonical classification, fail closed."""

    def verdict(
        advice: CorrelationAdvice, reason: str
    ) -> AssessmentSetupCorrelationInspection:
        return AssessmentSetupCorrelationInspection(
            advice,
            reason,
            correlation.intent_sha256,
            correlation.grade_action_id,
            correlation.membership_action_id,
        )

    if not isinstance(correlation, AssessmentSetupCorrelation) or not isinstance(
        recovery, AssessmentSetupRecoveryInspection
    ):
        raise AssessmentSetupCorrelationError(
            "Typed correlation and recovery required."
        )
    if (
        recovery.review_sha256 != correlation.review_sha256
        or recovery.grade_item_id != correlation.grade_item_id
    ):
        return verdict("requires_review", "recovery_context_changed")
    if recovery.state in (
        "inspection_unavailable",
        "source_changed",
        "relationship_needs_review",
        "receipts_need_review",
    ):
        return verdict("requires_review", "canonical_or_receipt_state_unsafe")
    if len(receipts) > 10000:
        return verdict("requires_review", "receipt_inventory_unbounded")
    exact: dict[str, TeacherActionReceipt] = {}
    for receipt in receipts:
        if not isinstance(receipt, TeacherActionReceipt):
            return verdict("requires_review", "untyped_receipt")
        if receipt.action_id in exact:
            return verdict("requires_review", "duplicate_receipt_id")
        exact[receipt.action_id] = receipt
    pairs = (
        (correlation.grade_action_id, correlation.grade_target_sha256, "grade_item"),
        (
            correlation.membership_action_id,
            correlation.membership_target_sha256,
            "grade_item_membership",
        ),
    )
    for action_id, target, family in pairs:
        if action_id is None:
            continue
        original_receipt = exact.get(action_id)
        if original_receipt is None:
            return verdict("requires_review", "original_action_receipt_missing")
        p = original_receipt.preview
        if (
            p.kind != family
            or p.target.family != family
            or p.target.candidate_sha256 != target
            or p.scope.class_id != correlation.class_id
            or p.scope.workspace_sha256 != correlation.workspace_sha256
            or p.scope.grade_item_id != correlation.grade_item_id
            or p.actor.actor_id != correlation.actor_id
            or p.actor.source != "saved"
            or p.actor.profile_sha256 != correlation.actor_profile_sha256
        ):
            return verdict("requires_review", "receipt_identity_mismatch")
        if family == "grade_item_membership" and (
            p.scope.school_year != correlation.school_year
            or p.scope.academic_period_id != correlation.period_id
            or p.scope.work_identity_sha256
            != _identity(
                "work",
                correlation.class_id,
                correlation.module_id,
                correlation.work_id,
            )
        ):
            return verdict("requires_review", "receipt_period_mismatch")
    if set(recovery.grade_action_ids) - (
        {correlation.grade_action_id}
        if correlation.grade_action_id is not None
        else set()
    ) or set(recovery.membership_action_ids) - (
        {correlation.membership_action_id}
        if correlation.membership_action_id is not None
        else set()
    ):
        return verdict("requires_review", "unlinked_action_attempt")
    if recovery.state == "ready_verified":
        if (
            correlation.kind == "create_and_link"
            and correlation.grade_action_id is None
        ):
            return verdict("requires_review", "grade_action_not_correlated")
        if correlation.membership_action_id is None:
            return verdict("requires_review", "membership_action_not_correlated")
        return verdict("ready_verified", "canonical_current_after_correlation")
    if recovery.state == "pristine" and correlation.stage == "reviewed":
        return verdict("not_started", "no_prior_canonical_action")
    if recovery.state in (
        "grade_item_written_not_selected",
        "grade_item_selected_link_missing",
    ):
        if correlation.kind != "create_and_link" or correlation.grade_action_id is None:
            return verdict("requires_review", "grade_history_not_correlated")
        if (
            recovery.state == "grade_item_selected_link_missing"
            and correlation.membership_action_id is not None
        ):
            return verdict("requires_review", "membership_action_without_membership")
        return verdict(
            "original_grade_action_pending"
            if recovery.state == "grade_item_written_not_selected"
            else "original_membership_action_pending",
            "partial_original_composite",
        )
    if (
        recovery.state == "membership_written_not_selected"
        and correlation.membership_action_id is not None
    ):
        return verdict(
            "original_membership_action_pending", "membership_selection_not_current"
        )
    return verdict("requires_review", "unrecognized_recovery_transition")


__all__ = (
    "AssessmentSetupCorrelation",
    "AssessmentSetupCorrelationError",
    "AssessmentSetupCorrelationInspection",
    "bind_correlation_action",
    "create_assessment_setup_correlation",
    "inspect_assessment_setup_correlation",
    "verify_correlation_context",
)
