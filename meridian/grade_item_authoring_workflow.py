"""Teacher-facing Grade Item immutable-revision authoring workflow."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Literal, TypeAlias

from pds_core.class_metadata import ClassMetadataError, load_class_metadata
from pds_core.routes import class_metadata_path

from meridian.grade_item_storage import (
    GradeItemStorageError,
    GradeItemWriteDisposition,
    list_grade_item_revisions,
    load_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import (
    GRADE_ITEM_RECORD_TYPE,
    GRADE_ITEM_SCHEMA_VERSION,
    GradeItemPurpose,
    GradeItemRevision,
    GradeItemWeightingMetadata,
    grade_item_revision_to_json_bytes,
)

MAXIMUM_GRADE_ITEM_WORKFLOW_ACTOR_ID_LENGTH: Final[int] = 256

GradeItemAuthoringOperation: TypeAlias = Literal[
    "create",
    "revise",
    "archive",
    "reactivate",
]
GradeItemWeightingAction: TypeAlias = Literal[
    "preserve",
    "clear",
    "replace",
]


class GradeItemAuthoringWorkflowError(RuntimeError):
    """Base error for teacher-facing Grade Item authoring."""

    code: str = "teacher_workflow.grade_items.authoring_error"


class GradeItemAuthoringScopeError(GradeItemAuthoringWorkflowError, ValueError):
    """Raised when requested authoring scope or operation is invalid."""

    code = "teacher_workflow.grade_items.authoring_scope_invalid"


class GradeItemAuthoringStaleError(GradeItemAuthoringWorkflowError):
    """Raised when canonical history changed after authoring preview."""

    code = "teacher_workflow.grade_items.authoring_stale"


@dataclass(frozen=True, slots=True)
class GradeItemAuthoringPreview:
    """Exact immutable Grade Item revision candidate reviewed before writing."""

    actor_id: str
    operation: GradeItemAuthoringOperation
    history_before: tuple[int, ...]
    latest_revision_sha256_before: str | None
    candidate: GradeItemRevision
    candidate_sha256: str

    def __post_init__(self) -> None:
        actor_id = _actor_id(self.actor_id)
        object.__setattr__(self, "actor_id", actor_id)
        if self.operation not in {"create", "revise", "archive", "reactivate"}:
            raise GradeItemAuthoringScopeError(
                "Grade Item authoring operation is invalid."
            )
        expected_history = tuple(range(1, self.candidate.grade_item_revision))
        if self.history_before != expected_history:
            raise GradeItemAuthoringScopeError(
                "history_before must exactly precede the candidate revision."
            )
        if bool(self.history_before) != bool(self.latest_revision_sha256_before):
            raise GradeItemAuthoringScopeError(
                "latest revision digest presence must match history presence."
            )
        expected_digest = hashlib.sha256(
            grade_item_revision_to_json_bytes(self.candidate)
        ).hexdigest()
        if self.candidate_sha256 != expected_digest:
            raise GradeItemAuthoringScopeError(
                "candidate_sha256 must bind the exact candidate revision bytes."
            )


@dataclass(frozen=True, slots=True)
class GradeItemAuthoringResult:
    """Result of writing the exact previewed immutable Grade Item revision."""

    preview: GradeItemAuthoringPreview
    write_disposition: GradeItemWriteDisposition
    stored_revision_sha256: str
    selected_revision_after: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.preview, GradeItemAuthoringPreview):
            raise GradeItemAuthoringScopeError(
                "preview must be a GradeItemAuthoringPreview."
            )
        if self.write_disposition not in {"created", "existing"}:
            raise GradeItemAuthoringScopeError("write_disposition is invalid.")
        if self.stored_revision_sha256 != self.preview.candidate_sha256:
            raise GradeItemAuthoringScopeError(
                "stored revision digest must match the exact previewed candidate."
            )


def preview_grade_item_authoring(
    workspace_root: str | Path,
    class_id: str,
    grade_item_id: str,
    *,
    operation: GradeItemAuthoringOperation,
    actor_id: str,
    revised_at: datetime,
    title: str | None = None,
    purpose: GradeItemPurpose | None = None,
    weighting: GradeItemWeightingMetadata | None = None,
    weighting_action: GradeItemWeightingAction | None = None,
) -> GradeItemAuthoringPreview:
    """Prepare one exact Grade Item revision candidate without writing it."""
    actor = _actor_id(actor_id)
    resolved_weighting_action: GradeItemWeightingAction
    if weighting_action is None:
        resolved_weighting_action = (
            "replace" if weighting is not None else "preserve"
        )
    else:
        resolved_weighting_action = weighting_action
    if resolved_weighting_action not in {"preserve", "clear", "replace"}:
        raise GradeItemAuthoringScopeError(
            "weighting_action must be preserve, clear, or replace."
        )
    if resolved_weighting_action == "replace" and weighting is None:
        raise GradeItemAuthoringScopeError(
            "Replacing weighting requires explicit weighting metadata."
        )
    if resolved_weighting_action != "replace" and weighting is not None:
        raise GradeItemAuthoringScopeError(
            "Weighting metadata may only be supplied for replace."
        )
    _require_class(workspace_root, class_id)
    history = list_grade_item_revisions(workspace_root, class_id, grade_item_id)
    latest = (
        None
        if not history
        else load_grade_item_revision(
            workspace_root,
            class_id,
            grade_item_id,
            history[-1],
        )
    )

    if operation == "create":
        if history:
            raise GradeItemAuthoringScopeError(
                "Create requires a Grade Item with no immutable revision history."
            )
        if title is None or purpose is None:
            raise GradeItemAuthoringScopeError(
                "Create requires explicit title and purpose."
            )
        if resolved_weighting_action == "clear":
            raise GradeItemAuthoringScopeError(
                "Create cannot clear weighting because no prior revision exists."
            )
        candidate = GradeItemRevision(
            schema_version=GRADE_ITEM_SCHEMA_VERSION,
            record_type=GRADE_ITEM_RECORD_TYPE,
            class_id=class_id,
            grade_item_id=grade_item_id,
            grade_item_revision=1,
            supersedes_revision=None,
            title=title,
            purpose=purpose,
            status="active",
            weighting=(
                weighting
                if resolved_weighting_action == "replace"
                else None
            ),
            created_at=revised_at,
            revised_at=revised_at,
        )
    else:
        if latest is None:
            raise GradeItemAuthoringScopeError(
                f"{operation} requires existing Grade Item revision history."
            )
        previous = latest.revision
        if operation == "revise":
            if title is None or purpose is None:
                raise GradeItemAuthoringScopeError(
                    "Revise requires explicit title and purpose."
                )
            candidate_title = title
            candidate_purpose = purpose
            if resolved_weighting_action == "preserve":
                candidate_weighting = previous.weighting
            elif resolved_weighting_action == "clear":
                candidate_weighting = None
            else:
                candidate_weighting = weighting
            candidate_status = previous.status
        else:
            if (
                title is not None
                or purpose is not None
                or resolved_weighting_action != "preserve"
            ):
                raise GradeItemAuthoringScopeError(
                    "Archive/reactivate only changes lifecycle status; use revise for "
                    "other Grade Item configuration changes."
                )
            if operation == "archive":
                if previous.status != "active":
                    raise GradeItemAuthoringScopeError(
                        "Archive requires the latest Grade Item revision to be active."
                    )
                candidate_status = "archived"
            elif operation == "reactivate":
                if previous.status != "archived":
                    raise GradeItemAuthoringScopeError(
                        "Reactivate requires the latest Grade Item revision to be "
                        "archived."
                    )
                candidate_status = "active"
            else:
                raise GradeItemAuthoringScopeError(
                    "Grade Item authoring operation is invalid."
                )
            candidate_title = previous.title
            candidate_purpose = previous.purpose
            candidate_weighting = previous.weighting

        candidate = GradeItemRevision(
            schema_version=GRADE_ITEM_SCHEMA_VERSION,
            record_type=GRADE_ITEM_RECORD_TYPE,
            class_id=previous.class_id,
            grade_item_id=previous.grade_item_id,
            grade_item_revision=previous.grade_item_revision + 1,
            supersedes_revision=previous.grade_item_revision,
            title=candidate_title,
            purpose=candidate_purpose,
            status=candidate_status,
            weighting=candidate_weighting,
            created_at=previous.created_at,
            revised_at=revised_at,
        )

    candidate_sha256 = hashlib.sha256(
        grade_item_revision_to_json_bytes(candidate)
    ).hexdigest()
    return GradeItemAuthoringPreview(
        actor_id=actor,
        operation=operation,
        history_before=history,
        latest_revision_sha256_before=(
            None if latest is None else latest.revision_sha256
        ),
        candidate=candidate,
        candidate_sha256=candidate_sha256,
    )


def commit_grade_item_authoring_preview(
    workspace_root: str | Path,
    preview: GradeItemAuthoringPreview,
) -> GradeItemAuthoringResult:
    """Write the exact previewed revision without changing current selection."""
    if not isinstance(preview, GradeItemAuthoringPreview):
        raise GradeItemAuthoringScopeError(
            "preview must be a GradeItemAuthoringPreview."
        )
    candidate = preview.candidate
    _require_class(workspace_root, candidate.class_id)

    history = list_grade_item_revisions(
        workspace_root,
        candidate.class_id,
        candidate.grade_item_id,
    )
    if history != preview.history_before:
        raise GradeItemAuthoringStaleError(
            "Grade Item revision history changed after authoring preview."
        )
    if history:
        latest = load_grade_item_revision(
            workspace_root,
            candidate.class_id,
            candidate.grade_item_id,
            history[-1],
        )
        if latest.revision_sha256 != preview.latest_revision_sha256_before:
            raise GradeItemAuthoringStaleError(
                "Latest Grade Item revision changed after authoring preview."
            )

    try:
        written = write_grade_item_revision(workspace_root, candidate)
    except GradeItemStorageError as error:
        raise GradeItemAuthoringWorkflowError(str(error)) from error
    if written.stored.revision != candidate:
        raise GradeItemAuthoringWorkflowError(
            "Persisted Grade Item revision differs from the previewed candidate."
        )
    if written.stored.revision_sha256 != preview.candidate_sha256:
        raise GradeItemAuthoringWorkflowError(
            "Persisted Grade Item digest differs from the previewed candidate."
        )

    # Deliberately read only after the immutable write. This workflow never calls
    # select_grade_item_revision; write and select remain independent operations.
    from meridian.grade_item_storage import get_current_grade_item_revision

    selected_after = get_current_grade_item_revision(
        workspace_root,
        candidate.class_id,
        candidate.grade_item_id,
    )
    return GradeItemAuthoringResult(
        preview=preview,
        write_disposition=written.disposition,
        stored_revision_sha256=written.stored.revision_sha256,
        selected_revision_after=selected_after,
    )


def _require_class(workspace_root: str | Path, class_id: str) -> None:
    path = class_metadata_path(Path(workspace_root), class_id)
    try:
        metadata = load_class_metadata(path)
    except ClassMetadataError as error:
        raise GradeItemAuthoringScopeError(
            f"Core class metadata could not be validated: {error}"
        ) from error
    if metadata.class_id != class_id:
        raise GradeItemAuthoringScopeError(
            "Core class metadata identity does not match requested class_id."
        )


def _actor_id(value: str) -> str:
    if not isinstance(value, str):
        raise GradeItemAuthoringScopeError("actor_id must be a string.")
    normalized = unicodedata.normalize("NFC", value)
    if not normalized or normalized != normalized.strip():
        raise GradeItemAuthoringScopeError(
            "actor_id must be nonempty and must not have surrounding whitespace."
        )
    if len(normalized) > MAXIMUM_GRADE_ITEM_WORKFLOW_ACTOR_ID_LENGTH:
        raise GradeItemAuthoringScopeError(
            "actor_id exceeds the workflow length limit."
        )
    return normalized
