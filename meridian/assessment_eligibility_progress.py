"""#125-E1: durable *non-authoritative* action linkage for eligibility batches.

A link is sealed before the corresponding #122 ``apply`` is entered.  It has
no eligibility-authoring or selector authority.  Fresh #122 receipt, source,
actor, authorization and canonical reads are essential before a restart claim.
Incomplete/corrupt links are deliberately not repaired automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, TypeAlias, cast

from pds_core.identifiers import IdentifierValidationError, validate_identifier
from pds_core.routes import class_module_dir

from meridian.assessment_eligibility_execution import (
    BatchEligibilityOutcome,
    _plan_digest,
    execute_batch_eligibility_plan,
)
from meridian.assessment_eligibility_plan import (
    BatchEligibilityPlanItem,
    BatchEligibilityReviewPlan,
)
from meridian.guided_eligibility import (
    GuidedEligibilityDependencies,
    GuidedEligibilityGradeItemChoice,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.teacher_action_guided import PreparedGuidedAction, _identity
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_action_restart_eligibility import (
    ActorChecker,
    AuthorizedLoader,
    inspect_restart_eligibility,
)

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ACTION = re.compile(r"[0-9a-f]{32}\Z")
_MAX_LINK_BYTES = 4096
_MAX_LINKS = 5000
RecoveryStatus: TypeAlias = Literal[
    "not_attempted",
    "already_applied",
    "written_not_current",
    "blocked_before_write",
    "current_unverified",
    "conflict_requires_review",
    "recovery_required",
]


class BatchEligibilityProgressError(RuntimeError):
    """Batch progress cannot be trusted; never replay an uncertain action."""

    code = "teacher_workflow.assessment_eligibility.progress_unsafe"


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _item_digest(item: BatchEligibilityPlanItem) -> str:
    s = item.source
    return _digest(
        [
            s.work.module_id,
            s.work.class_id,
            s.work.work_id,
            s.publication_id,
            s.cache_key,
            s.snapshot_digest,
            s.item_id,
        ]
    )


@dataclass(frozen=True, slots=True)
class SealedBatchActionLink:
    """Only an opaque action locator and immutable #122 intent/target hashes."""

    plan_sha256: str
    source_sha256: str
    action_id: str
    intent_sha256: str
    target_identity_sha256: str
    target_revision: int
    target_sha256: str
    expected_current_revision: int | None
    expected_current_sha256: str | None
    schema_version: int = 1

    def __post_init__(self) -> None:
        for key in (
            "plan_sha256",
            "source_sha256",
            "intent_sha256",
            "target_identity_sha256",
            "target_sha256",
        ):
            value = getattr(self, key)
            if not isinstance(value, str) or not _SHA.fullmatch(value):
                raise BatchEligibilityProgressError("Invalid sealed digest.")
        if not isinstance(self.action_id, str) or not _ACTION.fullmatch(self.action_id):
            raise BatchEligibilityProgressError("Invalid sealed action identity.")
        if type(self.target_revision) is not int or self.target_revision < 1:
            raise BatchEligibilityProgressError("Invalid sealed target revision.")
        if (self.expected_current_revision is None) != (
            self.expected_current_sha256 is None
        ):
            raise BatchEligibilityProgressError("Incomplete selected-pointer witness.")
        if self.expected_current_revision is not None and (
            type(self.expected_current_revision) is not int
            or self.expected_current_revision < 1
            or not isinstance(self.expected_current_sha256, str)
            or not _SHA.fullmatch(self.expected_current_sha256)
        ):
            raise BatchEligibilityProgressError("Invalid selected-pointer witness.")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise BatchEligibilityProgressError("Unsupported progress schema.")


@dataclass(frozen=True, slots=True)
class BatchActionRecoveryInspection:
    """Read-only #122 assessment; a link alone cannot establish any success."""

    source_item_id: str
    status: RecoveryStatus
    reason: str
    can_resume_exact_selection: bool
    action_id: str | None = None


class BatchEligibilityProgressStore:
    """Private class-local, create-once item links, no academic authority.

    The physical filename is a SHA-256 of source provenance, never a student ID,
    result label, or rationale. O_EXCL prevents overwriting another attempt.
    A partially written file is *unsafe*, not evidence of an absent action.
    """

    def __init__(self, workspace_root: str | Path, class_id: str) -> None:
        root = Path(workspace_root).absolute()
        try:
            identity = validate_identifier(class_id, "class_id")
        except IdentifierValidationError as error:
            raise BatchEligibilityProgressError("Invalid class identifier.") from error
        self.root = root
        self.class_id = identity
        self.directory = class_module_dir(root, identity, "meridian") / (
            "assessment_eligibility_progress"
        )

    def _directory(self, plan: BatchEligibilityReviewPlan, *, create: bool) -> Path:
        if plan.class_id != self.class_id or _plan_digest(plan) != plan.plan_sha256:
            raise BatchEligibilityProgressError("Plan scope/digest changed.")
        folder = self.directory / plan.plan_sha256
        if not self.root.is_dir() or self.root.is_symlink():
            raise BatchEligibilityProgressError("Unsafe workspace root.")
        relative = folder.relative_to(self.root)
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise BatchEligibilityProgressError("Link in progress directory chain.")
            if not current.exists():
                if not create:
                    return folder
                if current == self.root / "classes" / self.class_id:
                    raise BatchEligibilityProgressError(
                        "Progress cannot create an unregistered class."
                    )
                try:
                    current.mkdir(mode=0o700)
                except FileExistsError:
                    pass
                except OSError as error:
                    raise BatchEligibilityProgressError(
                        "Progress directory could not be created."
                    ) from error
            if not current.is_dir() or current.is_symlink():
                raise BatchEligibilityProgressError("Unsafe progress directory.")
        return folder

    def _path(
        self,
        plan: BatchEligibilityReviewPlan,
        item: BatchEligibilityPlanItem,
        *,
        create: bool,
    ) -> Path:
        if item.status != "action" or item not in plan.items:
            raise BatchEligibilityProgressError("Source is not a reviewed action.")
        if len(plan.items) > _MAX_LINKS:
            raise BatchEligibilityProgressError("Unbounded batch progress.")
        return self._directory(plan, create=create) / f"{_item_digest(item)}.json"

    def _read(
        self,
        path: Path,
        plan: BatchEligibilityReviewPlan,
        item: BatchEligibilityPlanItem,
    ) -> SealedBatchActionLink | None:
        if path.is_symlink():
            raise BatchEligibilityProgressError("Unsafe progress link file.")
        if not path.exists():
            return None
        try:
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise ValueError("Progress entry is not a regular file")
                content = handle.read(_MAX_LINK_BYTES + 1)
            if len(content) > _MAX_LINK_BYTES:
                raise ValueError("Progress entry exceeded bounded size")
            record = json.loads(content)
            if not isinstance(record, dict) or set(record) != {
                "link",
                "content_sha256",
            }:
                raise ValueError("Unrecognized progress envelope")
            data = record["link"]
            if not isinstance(data, dict) or _digest(data) != record["content_sha256"]:
                raise ValueError("Invalid progress checksum")
            if set(data) != set(SealedBatchActionLink.__dataclass_fields__):
                raise ValueError("Unrecognized progress fields")
            link = SealedBatchActionLink(**data)
        except (OSError, ValueError, TypeError, KeyError, UnicodeError) as error:
            raise BatchEligibilityProgressError("Corrupt progress link.") from error
        if link.plan_sha256 != plan.plan_sha256 or link.source_sha256 != _item_digest(
            item
        ):
            raise BatchEligibilityProgressError("Progress link identity mismatch.")
        return link

    def load(
        self, plan: BatchEligibilityReviewPlan, item: BatchEligibilityPlanItem
    ) -> SealedBatchActionLink | None:
        """Read without creating anything; missing means no *sealed* attempt."""
        path = self._path(plan, item, create=False)
        return self._read(path, plan, item)

    def seal(
        self,
        plan: BatchEligibilityReviewPlan,
        item: BatchEligibilityPlanItem,
        action: PreparedGuidedAction,
    ) -> SealedBatchActionLink:
        """Durably seal the exact prepared #122 action BEFORE calling apply."""
        if not isinstance(action, PreparedGuidedAction):
            raise BatchEligibilityProgressError("Expected prepared #122 action.")
        preview = action.preview
        target = preview.target
        expected_id = _identity(
            "eligibility",
            plan.class_id,
            plan.grade_item_id,
            plan.work.module_id,
            plan.work.work_id,
            item.source.publication_id,
            item.source.item_id,
        )
        if (
            preview.kind != "eligibility"
            or preview.actor != plan.actor
            or preview.scope.class_id != plan.class_id
            or preview.scope.grade_item_id != plan.grade_item_id
            or target.family != "eligibility"
            or target.identity_sha256 != expected_id
            or target.expected_current_revision != item.witness.selected_revision
            or target.expected_current_sha256 != item.witness.selected_sha256
            or not preview.make_current
        ):
            raise BatchEligibilityProgressError("#122 action differs from plan.")
        link = SealedBatchActionLink(
            plan.plan_sha256,
            _item_digest(item),
            preview.action_id,
            preview.intent_sha256,
            target.identity_sha256,
            target.revision,
            target.candidate_sha256,
            target.expected_current_revision,
            target.expected_current_sha256,
        )
        path = self._path(plan, item, create=True)
        data = asdict(link)
        payload = json.dumps(
            {"link": data, "content_sha256": _digest(data)},
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > _MAX_LINK_BYTES:
            raise BatchEligibilityProgressError("Oversized progress link.")
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            existing = self._read(path, plan, item)
            if existing != link:
                raise BatchEligibilityProgressError(
                    "Prior action sealed; do not mint a replacement action ID."
                )
            return link
        except OSError as error:
            raise BatchEligibilityProgressError("Progress seal refused.") from error
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
        except OSError as error:
            # Do not delete an uncertain or incomplete file after a failed fsync.
            raise BatchEligibilityProgressError(
                "Progress seal uncertain; inspect before any retry."
            ) from error
        return link


def execute_batch_with_sealed_progress(
    workspace_root: str | Path,
    plan: BatchEligibilityReviewPlan,
    *,
    confirmed: bool,
    prepared: GuidedProjectionResult,
    grade_item: GuidedEligibilityGradeItemChoice,
    dependencies: GuidedEligibilityDependencies,
) -> BatchEligibilityOutcome:
    """Use #125-D, sealing each action identity before any canonical write.

    This is a fresh execution entrypoint, NOT a resumed batch. A repeat after
    partial completion must use read-only inspection and #122 exact restart;
    it must not call this function to reauthor completed actions.
    """
    if not confirmed:
        return execute_batch_eligibility_plan(
            workspace_root,
            plan,
            confirmed=False,
            prepared=prepared,
            grade_item=grade_item,
            dependencies=dependencies,
        )
    store = BatchEligibilityProgressStore(workspace_root, plan.class_id)

    def seal_before_apply(
        reviewed_plan: BatchEligibilityReviewPlan,
        reviewed_item: BatchEligibilityPlanItem,
        action: PreparedGuidedAction,
    ) -> None:
        # #125-D ignores the callback result; the durable seal is the side effect.
        store.seal(reviewed_plan, reviewed_item, action)

    return execute_batch_eligibility_plan(
        store.root,
        plan,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=dependencies,
        before_apply=seal_before_apply,
    )


def inspect_sealed_batch_item(
    workspace_root: str | Path,
    plan: BatchEligibilityReviewPlan,
    item: BatchEligibilityPlanItem,
    *,
    authorized_loader: AuthorizedLoader,
    actor_checker: ActorChecker,
) -> BatchActionRecoveryInspection:
    """Only #122 fresh/canonical inspection can label a sealed attempt current."""
    store = BatchEligibilityProgressStore(workspace_root, plan.class_id)
    link = store.load(plan, item)
    if link is None:
        return BatchActionRecoveryInspection(
            item.source.item_id, "not_attempted", "no_sealed_action", False
        )
    receipts = TeacherActionReceiptStore(store.root, plan.class_id)
    try:
        receipt = receipts.load(link.action_id)
        if receipt is None:
            return BatchActionRecoveryInspection(
                item.source.item_id,
                "recovery_required",
                "missing_receipt",
                False,
                link.action_id,
            )
        p = receipt.preview
        t = p.target
        if (
            p.action_id != link.action_id
            or p.intent_sha256 != link.intent_sha256
            or p.actor != plan.actor
            or t.identity_sha256 != link.target_identity_sha256
            or t.revision != link.target_revision
            or t.candidate_sha256 != link.target_sha256
            or t.expected_current_revision != link.expected_current_revision
            or t.expected_current_sha256 != link.expected_current_sha256
        ):
            return BatchActionRecoveryInspection(
                item.source.item_id,
                "conflict_requires_review",
                "receipt_intent_mismatch",
                False,
                link.action_id,
            )
        inspected = inspect_restart_eligibility(
            store.root,
            receipts,
            receipt,
            authorized_loader=authorized_loader,
            actor_checker=actor_checker,
        )
        status = inspected.status
        if status == "applied":
            # Existing exact current record is intentionally called already_applied.
            status = "already_applied"
        if status not in {
            "already_applied",
            "written_not_current",
            "blocked_before_write",
            "current_unverified",
            "conflict_requires_review",
            "recovery_required",
        }:
            status = "recovery_required"
        return BatchActionRecoveryInspection(
            item.source.item_id,
            cast(RecoveryStatus, status),
            inspected.reason,
            inspected.can_resume,
            link.action_id,
        )
    except Exception:
        return BatchActionRecoveryInspection(
            item.source.item_id,
            "recovery_required",
            "canonical_or_receipt_inspection_failed",
            False,
            link.action_id,
        )


__all__ = (
    "BatchActionRecoveryInspection",
    "BatchEligibilityProgressError",
    "BatchEligibilityProgressStore",
    "SealedBatchActionLink",
    "execute_batch_with_sealed_progress",
    "inspect_sealed_batch_item",
)
