"""#124 C1: one read-only, teacher-reviewed Grade Item setup proposal.

These frozen witnesses are a review basis, not write authority. #124 D must
reload canonical registration, Grade Item selection and membership, calendar,
publication (when relied upon) and actor before applying any operation.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias, cast

from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_choices import (
    NamedAssessment,
    NamedAssessmentList,
    load_named_assessment_choices,
)
from meridian.grade_items import GRADE_ITEM_PURPOSES, GradeItemPurpose
from meridian.guided_grade_items import (
    GuidedGradeItemBridgeContext,
    GuidedGradeItemBridgeDependencies,
    derive_grade_item_id,
    load_guided_grade_item_bridge_context,
)

SetupPlanKind: TypeAlias = Literal["already_ready", "use_existing", "create_and_link"]


class AssessmentSetupPreviewError(ValueError):
    """A safe single reviewed proposal cannot be offered."""


@dataclass(frozen=True, slots=True)
class AssessmentSetupPreview:
    """No-write proposal, bounded to exact work, period and selection witnesses."""

    kind: SetupPlanKind
    work: ModuleWorkRef
    class_id: str
    school_year: str
    registration_revision: int
    registration_lifecycle: str
    assessment_title: str
    producer_label: str
    publication_label: str
    publication_id: str | None
    grade_item_id: str
    grade_item_title: str
    grade_item_purpose: GradeItemPurpose
    selected_grade_item_revision: int | None
    marking_period_id: str
    marking_period_label: str
    calendar_revision: int
    actor_attribution: str | None
    rationale: str | None
    operations: tuple[str, ...]
    weighting_message: str
    review_sha256: str

    @property
    def needs_confirmation(self) -> bool:
        return self.kind != "already_ready"


def _visible(value: str, field: str, limit: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or value != value.strip()
        or any(
            unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            for char in value
        )
    ):
        raise AssessmentSetupPreviewError(
            f"{field} must be nonempty, bounded and single-line."
        )
    return value


def _digest(data: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            data, sort_keys=True, ensure_ascii=True, separators=(",", ":")
        ).encode("ascii")
    ).hexdigest()


def prepare_assessment_setup_preview(
    assessments: NamedAssessmentList,
    bridge: GuidedGradeItemBridgeContext,
    *,
    work: ModuleWorkRef,
    purpose: GradeItemPurpose | None = None,
    existing_grade_item_id: str | None = None,
    new_title: str | None = None,
    actor_attribution: str | None = None,
    rationale: str | None = None,
) -> AssessmentSetupPreview:
    """Propose, without writing, the smallest legitimate Grade Item setup.

    The class/year/marking period were selected before this call. The teacher
    explicitly chooses an existing Grade Item or the purpose for a new one.
    There is no default intent-to-purpose conversion or protected evidence read.
    """
    if not isinstance(assessments, NamedAssessmentList):
        raise AssessmentSetupPreviewError("A verified assessment list is required.")
    if bridge.work != work or work.class_id != assessments.class_id:
        raise AssessmentSetupPreviewError(
            "Assessment and Grade Item class/work disagree."
        )
    matches: tuple[NamedAssessment, ...] = tuple(
        item for item in assessments.items if item.candidate.work == work
    )
    if len(matches) != 1:
        raise AssessmentSetupPreviewError("Select one exact assessment before setup.")
    named = matches[0]
    candidate = named.candidate
    if (
        candidate.school_year != assessments.school_year
        or candidate.period_id != assessments.period_id
        or candidate.registration_revision != bridge.registration_revision
        or candidate.title != bridge.work_title
    ):
        raise AssessmentSetupPreviewError(
            "Assessment registration or period changed; refresh."
        )
    if (named.publication_state == "current_results_verified") != (
        candidate.publication_id is not None
    ) and named.publication_state not in ("multiple_current_results",):
        raise AssessmentSetupPreviewError(
            "Publication reference differs from source status."
        )
    if candidate.lifecycle not in ("active", "planned"):
        raise AssessmentSetupPreviewError("Only active/planned work may enter setup.")
    if named.publication_state in (
        "multiple_current_results",
        "historical_results_only",
        "withdrawn_results",
    ):
        raise AssessmentSetupPreviewError(
            "Publication history needs review before setup."
        )
    if (
        work.module_id == "concord"
        and named.publication_state != "current_results_verified"
    ):
        raise AssessmentSetupPreviewError(
            "Unpublished Concord work needs source review."
        )
    if work.module_id not in ("scoreform", "quillan", "concord"):
        raise AssessmentSetupPreviewError(
            "This producer is not qualified for automatic setup."
        )
    if candidate.setup_state in ("ambiguous", "review_relationship"):
        raise AssessmentSetupPreviewError(
            "Existing Grade Item relationship needs review."
        )
    if candidate.setup_state not in ("ready", "needs_create", "choose_existing"):
        raise AssessmentSetupPreviewError("Unsupported Grade Item setup state.")

    periods = tuple(
        p
        for p in bridge.periods
        if p.assignment.period.school_year == assessments.school_year
        and p.assignment.period.period_id == assessments.period_id
        and p.assignment.calendar_revision == candidate.calendar_revision
        and p.period_type == "marking_period"
    )
    if len(periods) != 1:
        raise AssessmentSetupPreviewError(
            "Selected marking period/calendar changed; refresh."
        )
    period = periods[0]
    grade_choices = {item.grade_item_id: item for item in bridge.existing_grade_items}
    if len(grade_choices) != len(bridge.existing_grade_items):
        raise AssessmentSetupPreviewError(
            "Duplicate Grade Item identity; review required."
        )

    actor: str | None = None
    reason: str | None = None
    chosen_purpose: GradeItemPurpose
    if candidate.setup_state == "ready":
        grade_item_id = candidate.ready_grade_item_id
        if grade_item_id is None or grade_item_id not in grade_choices:
            raise AssessmentSetupPreviewError(
                "Ready Grade Item is not selected/current."
            )
        selected = grade_choices[grade_item_id]
        if existing_grade_item_id not in (None, grade_item_id):
            raise AssessmentSetupPreviewError(
                "Ready relationship cannot be retargeted."
            )
        if purpose is not None and purpose != selected.purpose:
            raise AssessmentSetupPreviewError(
                "Ready Grade Item purpose differs from review."
            )
        if new_title is not None or rationale is not None:
            raise AssessmentSetupPreviewError(
                "Already ready requires no new authoring."
            )
        kind: SetupPlanKind = "already_ready"
        title, chosen_purpose = selected.title, cast(GradeItemPurpose, selected.purpose)
        revision: int | None = selected.selected_revision
        operations: tuple[str, ...] = ()
    else:
        if actor_attribution is None:
            raise AssessmentSetupPreviewError(
                "Teacher attribution is required for changes."
            )
        actor = _visible(actor_attribution, "actor attribution", limit=120)
        reason = None if rationale is None else _visible(rationale, "rationale")
        if purpose not in GRADE_ITEM_PURPOSES:
            raise AssessmentSetupPreviewError(
                "Teacher must choose an explicit Grade Item purpose."
            )
        chosen_purpose = purpose
        if candidate.setup_state == "choose_existing":
            if existing_grade_item_id is None or new_title is not None:
                raise AssessmentSetupPreviewError(
                    "Choose one existing active Grade Item."
                )
            existing_choice = grade_choices.get(existing_grade_item_id)
            if (
                existing_choice is None
                or existing_grade_item_id
                not in candidate.active_unlinked_grade_item_ids
            ):
                raise AssessmentSetupPreviewError(
                    "Existing Grade Item is not a safe unlinked choice."
                )
            if existing_choice.purpose != chosen_purpose:
                raise AssessmentSetupPreviewError(
                    "Existing Grade Item purpose differs; review required."
                )
            kind = "use_existing"
            grade_item_id = existing_choice.grade_item_id
            title, revision = existing_choice.title, existing_choice.selected_revision
            operations = (
                "Author included work/period membership",
                "Select exact membership revision",
            )
        else:
            if existing_grade_item_id is not None:
                raise AssessmentSetupPreviewError(
                    "No verified existing Grade Item is offered."
                )
            kind = "create_and_link"
            title = _visible(new_title or candidate.title, "new Grade Item title")
            grade_item_id = derive_grade_item_id(title, bridge.existing_grade_item_ids)
            if grade_item_id in bridge.existing_grade_item_ids:
                raise AssessmentSetupPreviewError(
                    "New Grade Item identity is occupied."
                )
            revision = None
            operations = (
                "Author new unweighted Grade Item revision",
                "Select new Grade Item revision",
                "Author included work/period membership",
                "Select exact membership revision",
            )

    display = named.choice
    data: dict[str, object] = {
        "kind": kind,
        "work": [work.module_id, work.class_id, work.work_id],
        "school_year": assessments.school_year,
        "registration_revision": candidate.registration_revision,
        "registration_lifecycle": candidate.lifecycle,
        "publication_state": named.publication_state,
        "publication_id": candidate.publication_id,
        "grade_item_id": grade_item_id,
        "grade_item_title": title,
        "purpose": chosen_purpose,
        "selected_revision": revision,
        "period_id": assessments.period_id,
        "calendar_revision": candidate.calendar_revision,
        "choice_witness": display.witness,
        "actor_attribution": actor,
        "rationale": reason,
        "operations": list(operations),
    }
    return AssessmentSetupPreview(
        kind=kind,
        work=work,
        class_id=assessments.class_id,
        school_year=assessments.school_year,
        registration_revision=candidate.registration_revision,
        registration_lifecycle=candidate.lifecycle,
        assessment_title=candidate.title,
        producer_label=display.source or work.module_id,
        publication_label=display.status or named.publication_state,
        publication_id=candidate.publication_id,
        grade_item_id=grade_item_id,
        grade_item_title=title,
        grade_item_purpose=chosen_purpose,
        selected_grade_item_revision=revision,
        marking_period_id=assessments.period_id,
        marking_period_label=period.display_label,
        calendar_revision=candidate.calendar_revision,
        actor_attribution=actor,
        rationale=reason,
        operations=operations,
        weighting_message="Weighting is not configured by assessment setup.",
        review_sha256=_digest(data),
    )


def load_assessment_setup_preview(
    workspace_root: str | Path,
    *,
    class_id: str,
    school_year: str,
    period_id: str,
    work: ModuleWorkRef,
    dependencies: GuidedGradeItemBridgeDependencies,
    purpose: GradeItemPurpose | None = None,
    existing_grade_item_id: str | None = None,
    new_title: str | None = None,
    actor_attribution: str | None = None,
    rationale: str | None = None,
) -> AssessmentSetupPreview:
    """Fresh B1/B2 inventory and canonical bridge read; still zero writes."""
    named = load_named_assessment_choices(
        workspace_root, class_id=class_id, school_year=school_year, period_id=period_id
    )
    bridge = load_guided_grade_item_bridge_context(
        workspace_root, work, dependencies=dependencies
    )
    return prepare_assessment_setup_preview(
        named,
        bridge,
        work=work,
        purpose=purpose,
        existing_grade_item_id=existing_grade_item_id,
        new_title=new_title,
        actor_attribution=actor_attribution,
        rationale=rationale,
    )


__all__ = (
    "AssessmentSetupPreview",
    "AssessmentSetupPreviewError",
    "SetupPlanKind",
    "load_assessment_setup_preview",
    "prepare_assessment_setup_preview",
)
