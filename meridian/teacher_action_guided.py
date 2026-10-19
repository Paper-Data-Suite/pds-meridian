"""#122 guided Grade Item, membership and eligibility action adapters.

No academic state is stored here. Each adapter delegates to the existing
immutable author, CAS selector and independent canonical loaders; the journal
remains subordinate to those authorities.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pds_core.academic_period_storage import load_current_academic_period_calendar
from pds_core.academic_periods import academic_period_calendar_to_dict
from pds_core.class_metadata import load_class_metadata
from pds_core.routes import class_metadata_path

from meridian.evidence_eligibility import evidence_eligibility_decision_to_json_bytes
from meridian.evidence_eligibility_storage import (
    list_evidence_eligibility_revisions,
    load_current_evidence_eligibility_decision,
    load_evidence_eligibility_revision,
    validate_evidence_eligibility_dependencies,
)
from meridian.grade_item_authoring_workflow import GradeItemAuthoringPreview
from meridian.grade_item_membership_authoring_workflow import (
    GradeItemMembershipAuthoringPreview,
)
from meridian.grade_item_membership_storage import (
    list_grade_item_membership_revisions,
    load_current_grade_item_membership_decision,
    load_grade_item_membership_revision,
    validate_grade_item_membership_dependencies,
)
from meridian.grade_item_memberships import (
    grade_item_membership_decision_to_json_bytes,
)
from meridian.grade_item_storage import (
    list_grade_item_revisions,
    load_current_grade_item_revision,
    load_grade_item_revision,
)
from meridian.guided_eligibility import (
    GuidedEligibilityContext,
    GuidedEligibilityDependencies,
    commit_guided_eligibility,
    commit_guided_eligibility_selection,
    preview_guided_eligibility_selection,
)
from meridian.guided_grade_items import (
    GuidedGradeItemBridgeDependencies,
    commit_membership_link,
    commit_new_grade_item,
)
from meridian.guided_projection import GuidedProjectionResult
from meridian.new_evidence_eligibility_workflow import (
    NewEvidenceEligibilityAuthoringPreview,
)
from meridian.teacher_action_contract import (
    ActionKind,
    SelectionDisposition,
    TeacherActionActor,
    TeacherActionBasis,
    TeacherActionPreview,
    TeacherActionRecord,
    TeacherActionResult,
    TeacherActionScope,
    TeacherActionTarget,
)
from meridian.teacher_action_orchestration import (
    TeacherActionConflictError,
    apply_reviewed_existing_policy_selection,
    apply_reviewed_teacher_action,
    resume_exact_teacher_selection,
)
from meridian.teacher_action_receipts import (
    CanonicalActionObservation,
    TeacherActionReceiptStore,
)
from meridian.teacher_profile import TeacherIdentityProvider, TeacherProfileStore


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _identity(*parts: str) -> str:
    return _sha("\x1f".join(parts).encode("utf-8"))


def _root(value: Path) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise TeacherActionConflictError("An absolute workspace is required.")
    return value


def _calendar_digest(root: Path, school_year: str, revision: int) -> str:
    calendar = load_current_academic_period_calendar(root, school_year)
    if calendar is None or calendar.calendar_revision != revision:
        raise TeacherActionConflictError("Academic calendar changed since review.")
    content = json.dumps(
        academic_period_calendar_to_dict(calendar),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha(content)


def _actor_now(actor: TeacherActionActor) -> None:
    """Saved profile identity is attribution, NEVER publication permission."""
    _, digest = TeacherIdentityProvider(
        TeacherProfileStore()
    ).resolve_with_fingerprint()
    if digest != actor.profile_sha256:
        raise TeacherActionConflictError("Teacher profile changed since review.")


def resolve_menu_actor(actor_id: str, input_fn: object) -> TeacherActionActor:
    """Consume only the matching #121 one-request attribution observation.

    A standalone controller may use a saved profile, but cannot manufacture an
    Advanced override. The menu adapter's consumed token is deliberately
    single use and profile-bound.
    """
    getter = getattr(input_fn, "take_last_attribution", None)
    observed = getter() if callable(getter) else None
    if observed is not None:
        identity, profile_sha256 = observed
        if identity.actor_id != actor_id:
            raise TeacherActionConflictError("Attribution request changed.")
        return bind_reviewed_actor(
            actor_id,
            identity_source=identity.source,
            profile_sha256=profile_sha256,
        )
    return bind_reviewed_actor(actor_id)


def bind_reviewed_actor(
    actor_id: str,
    *,
    identity_source: Literal["saved", "temporary"] = "saved",
    profile_sha256: str | None = None,
) -> TeacherActionActor:
    """Bind an explicit already-resolved #121 actor, never a display name."""
    identity, digest = TeacherIdentityProvider(
        TeacherProfileStore()
    ).resolve_with_fingerprint()
    if identity_source == "saved" and actor_id != identity.actor_id:
        raise TeacherActionConflictError("Saved actor ID does not match attribution.")
    if identity_source == "temporary" and profile_sha256 is None:
        raise TeacherActionConflictError("Unverified temporary attribution.")
    if profile_sha256 is not None and digest != profile_sha256:
        raise TeacherActionConflictError("Profile changed after attribution review.")
    return TeacherActionActor(actor_id, digest, identity_source)


Observation = tuple[str | None, int | None, str | None, Literal["current", "stale"]]


class _GuidedPort:
    """One *closed* canonical operation, not a generic arbitrary command runner."""

    def __init__(
        self,
        *,
        kind: ActionKind,
        revalidate: Callable[[], None],
        read: Callable[[], Observation],
        write: Callable[[], Literal["created", "existing"]],
        select: Callable[[], SelectionDisposition],
    ) -> None:
        self.kind = kind
        self._revalidate = revalidate
        self._read = read
        self._write = write
        self._select = select
        self._bound: TeacherActionPreview | None = None

    def bind(self, preview: TeacherActionPreview) -> None:
        if self._bound is not None:
            raise TeacherActionConflictError("Domain port is already bound.")
        if preview.kind != self.kind:
            raise TeacherActionConflictError("Bound action has the wrong kind.")
        self._bound = preview

    def _require_bound(self, preview: TeacherActionPreview) -> None:
        if self._bound is None or preview != self._bound:
            raise TeacherActionConflictError("Reviewed action token has changed.")

    def revalidate_basis(self, preview: TeacherActionPreview) -> None:
        self._require_bound(preview)
        self._revalidate()

    def observe(self, preview: TeacherActionPreview) -> CanonicalActionObservation:
        self._require_bound(preview)
        digest, revision, current_digest, state = self._read()
        return CanonicalActionObservation(
            target_sha256=digest,
            current_revision=revision,
            current_sha256=current_digest,
            current_basis=state,
        )

    def persist_exact(self, preview: TeacherActionPreview) -> TeacherActionRecord:
        self._require_bound(preview)
        disposition = self._write()
        digest, _, _, _ = self._read()
        if digest != preview.target.candidate_sha256:
            raise TeacherActionConflictError("Immutable write digest differs.")
        return TeacherActionRecord(
            self.kind,
            preview.target.identity_sha256,
            preview.target.revision,
            preview.target.candidate_sha256,
            disposition,
        )

    def select_exact(
        self, preview: TeacherActionPreview, record: TeacherActionRecord
    ) -> SelectionDisposition:
        self._require_bound(preview)
        if not record.matches_target(preview.target):
            raise TeacherActionConflictError("Selection record differs from review.")
        return self._select()


@dataclass(frozen=True, slots=True)
class PreparedGuidedAction:
    """Single reviewed teacher choice; a separate RESUME never reauthors."""

    preview: TeacherActionPreview
    port: _GuidedPort
    store: TeacherActionReceiptStore
    existing_policy_selection: bool = False

    def apply(self, *, confirmed: bool) -> TeacherActionResult:
        if self.existing_policy_selection:
            if self.preview.kind != "attempt_policy":
                raise TeacherActionConflictError(
                    "Existing-only selection is not available for this family."
                )
            return apply_reviewed_existing_policy_selection(
                self.preview,
                self.port,
                self.store,
                confirmation="APPLY" if confirmed else "CANCEL",
            )
        return apply_reviewed_teacher_action(
            self.preview,
            self.port,
            self.store,
            confirmation="APPLY" if confirmed else "CANCEL",
        )

    def resume(self, *, confirmed: bool) -> TeacherActionResult:
        return resume_exact_teacher_selection(
            self.preview,
            self.port,
            self.store,
            confirmation="RESUME" if confirmed else "CANCEL",
        )


def _prepare(
    *,
    root: Path,
    class_id: str,
    grade_item_id: str,
    actor: TeacherActionActor,
    kind: ActionKind,
    revision: int,
    candidate_sha256: str,
    current_revision: int | None,
    current_sha256: str | None,
    identity: str,
    source_binding: str,
    port: _GuidedPort,
    existing_policy_selection: bool = False,
    school_year: str | None = None,
    academic_period_id: str | None = None,
    calendar_sha256: str | None = None,
    work_identity_sha256: str | None = None,
) -> PreparedGuidedAction:
    scope = TeacherActionScope(
        workspace_sha256=_identity("workspace", str(root)),
        class_id=class_id,
        grade_item_id=grade_item_id,
        school_year=school_year,
        academic_period_id=academic_period_id,
        calendar_sha256=calendar_sha256,
        work_identity_sha256=work_identity_sha256,
    )
    target = TeacherActionTarget(
        family=kind,
        identity_sha256=identity,
        revision=revision,
        candidate_sha256=candidate_sha256,
        expected_current_revision=current_revision,
        expected_current_sha256=current_sha256,
    )
    # Source-binding is not authorization; domain revalidation must verify it.
    basis = (
        TeacherActionBasis(
            "actor_profile", _identity(actor.actor_id), actor.profile_sha256
        ),
        TeacherActionBasis("canonical_source", identity, source_binding),
    )
    preview = TeacherActionPreview(
        action_id=uuid.uuid4().hex,
        kind=kind,
        scope=scope,
        actor=actor,
        target=target,
        basis=basis,
        reviewed_decision_sha256=candidate_sha256,
    )
    port.bind(preview)
    return PreparedGuidedAction(
        preview,
        port,
        TeacherActionReceiptStore(root, class_id),
        existing_policy_selection,
    )


def prepare_grade_item_action(
    root: Path,
    authoring: GradeItemAuthoringPreview,
    actor: TeacherActionActor,
    dependencies: GuidedGradeItemBridgeDependencies,
) -> PreparedGuidedAction:
    """Bind one exact new Grade Item to current selection in one APPLY."""
    root = _root(root)
    candidate = authoring.candidate
    class_id, gi = candidate.class_id, candidate.grade_item_id
    if authoring.actor_id != actor.actor_id:
        raise TeacherActionConflictError("Grade Item author and actor differ.")
    previous = load_current_grade_item_revision(root, class_id, gi)
    current_rev = None if previous is None else previous.revision.grade_item_revision
    current_sha = None if previous is None else previous.revision_sha256
    if current_rev is not None:
        raise TeacherActionConflictError("New Grade Item is already current.")

    def validate() -> None:
        _actor_now(actor)
        metadata = load_class_metadata(class_metadata_path(root, class_id))
        if metadata.class_id != class_id:
            raise TeacherActionConflictError("Class registration changed.")
        revisions = list_grade_item_revisions(root, class_id, gi)
        if revisions not in (
            authoring.history_before,
            (*authoring.history_before, candidate.grade_item_revision),
        ):
            raise TeacherActionConflictError("Grade Item history changed.")

    def read() -> Observation:
        history = list_grade_item_revisions(root, class_id, gi)
        target = (
            load_grade_item_revision(root, class_id, gi, candidate.grade_item_revision)
            if candidate.grade_item_revision in history
            else None
        )
        current = load_current_grade_item_revision(root, class_id, gi)
        try:
            _actor_now(actor)
            metadata = load_class_metadata(class_metadata_path(root, class_id))
            state: Literal["current", "stale"] = (
                "current" if metadata.class_id == class_id else "stale"
            )
        except Exception:
            state = "stale"
        return (
            None if target is None else target.revision_sha256,
            None if current is None else current.revision.grade_item_revision,
            None if current is None else current.revision_sha256,
            state,
        )

    def write() -> Literal["created", "existing"]:
        result = commit_new_grade_item(root, authoring, dependencies=dependencies)
        return result.write_disposition

    def select() -> SelectionDisposition:
        reviewed = dependencies.grade_item_selection_previewer(
            root,
            class_id,
            gi,
            candidate.grade_item_revision,
        )
        if (
            reviewed.target.revision_sha256 != authoring.candidate_sha256
            or reviewed.expected_current_revision != current_rev
        ):
            raise TeacherActionConflictError("Grade Item selector baseline changed.")
        result = dependencies.grade_item_selection_committer(root, reviewed)
        value = result.selection_disposition
        if value not in ("created", "updated", "existing"):
            raise TeacherActionConflictError(
                "Unexpected canonical selector disposition."
            )
        if value == "created":
            return "created"
        if value == "updated":
            return "updated"
        return "existing"

    kind: ActionKind = "grade_item"
    return _prepare(
        root=root,
        class_id=class_id,
        grade_item_id=gi,
        actor=actor,
        kind=kind,
        revision=candidate.grade_item_revision,
        candidate_sha256=authoring.candidate_sha256,
        current_revision=current_rev,
        current_sha256=current_sha,
        identity=_identity("grade_item", class_id, gi),
        source_binding=_identity("grade_item_candidate", authoring.candidate_sha256),
        port=_GuidedPort(
            kind=kind,
            revalidate=validate,
            read=read,
            write=write,
            select=select,
        ),
    )


def prepare_membership_action(
    root: Path,
    authoring: GradeItemMembershipAuthoringPreview,
    actor: TeacherActionActor,
    dependencies: GuidedGradeItemBridgeDependencies,
) -> PreparedGuidedAction:
    """Bind the included work relationship, period and revision exactly."""
    root = _root(root)
    candidate = authoring.candidate
    class_id, gi, work = candidate.class_id, candidate.grade_item_id, authoring.work
    if candidate.actor_id != actor.actor_id:
        raise TeacherActionConflictError("Membership author and actor differ.")
    digest = _sha(grade_item_membership_decision_to_json_bytes(candidate))
    assignment = candidate.academic_period
    if candidate.decision != "included" or assignment is None:
        raise TeacherActionConflictError("Guided membership must be included.")
    period = assignment.period
    calendar_sha = _calendar_digest(
        root,
        period.school_year,
        assignment.calendar_revision,
    )
    previous = load_current_grade_item_membership_decision(root, class_id, gi, work)
    previous_rev = None if previous is None else previous.decision.membership_revision
    previous_sha = None if previous is None else previous.decision_sha256
    if previous_rev != authoring.expected_current_membership_revision:
        raise TeacherActionConflictError("Membership selection changed since review.")

    def validate() -> None:
        _actor_now(actor)
        validate_grade_item_membership_dependencies(root, candidate)
        if (
            _calendar_digest(
                root,
                period.school_year,
                assignment.calendar_revision,
            )
            != calendar_sha
        ):
            raise TeacherActionConflictError("Academic calendar contents changed.")
        revisions = list_grade_item_membership_revisions(root, class_id, gi, work)
        if revisions not in (
            authoring.history,
            (*authoring.history, candidate.membership_revision),
        ):
            raise TeacherActionConflictError("Membership history changed.")

    def read() -> Observation:
        history = list_grade_item_membership_revisions(root, class_id, gi, work)
        target = (
            load_grade_item_membership_revision(
                root,
                class_id,
                gi,
                work,
                candidate.membership_revision,
            )
            if candidate.membership_revision in history
            else None
        )
        current = load_current_grade_item_membership_decision(root, class_id, gi, work)
        try:
            _actor_now(actor)
            validate_grade_item_membership_dependencies(root, candidate)
            if (
                _calendar_digest(
                    root,
                    period.school_year,
                    assignment.calendar_revision,
                )
                != calendar_sha
            ):
                raise TeacherActionConflictError("Academic calendar changed.")
            state: Literal["current", "stale"] = "current"
        except Exception:
            state = "stale"
        return (
            None if target is None else target.decision_sha256,
            None if current is None else current.decision.membership_revision,
            None if current is None else current.decision_sha256,
            state,
        )

    def write() -> Literal["created", "existing"]:
        result = commit_membership_link(root, authoring, dependencies=dependencies)
        if result.write_disposition == "created":
            return "created"
        if result.write_disposition == "existing":
            return "existing"
        raise TeacherActionConflictError("Unexpected canonical write disposition.")

    def select() -> SelectionDisposition:
        reviewed = dependencies.membership_selection_previewer(
            root,
            class_id,
            gi,
            work,
            candidate.membership_revision,
        )
        if (
            reviewed.target.decision_sha256 != digest
            or reviewed.expected_current_membership_revision != previous_rev
        ):
            raise TeacherActionConflictError("Membership selector baseline changed.")
        result = dependencies.membership_selection_committer(root, reviewed)
        value = result.selection_disposition
        if value not in ("created", "updated", "existing"):
            raise TeacherActionConflictError(
                "Unexpected canonical selector disposition."
            )
        if value == "created":
            return "created"
        if value == "updated":
            return "updated"
        return "existing"

    kind: ActionKind = "grade_item_membership"
    return _prepare(
        root=root,
        class_id=class_id,
        grade_item_id=gi,
        actor=actor,
        kind=kind,
        revision=candidate.membership_revision,
        candidate_sha256=digest,
        current_revision=previous_rev,
        current_sha256=previous_sha,
        identity=_identity("membership", class_id, gi, work.module_id, work.work_id),
        source_binding=_identity("membership_candidate", digest),
        school_year=period.school_year,
        academic_period_id=period.period_id,
        calendar_sha256=calendar_sha,
        work_identity_sha256=_identity("work", class_id, work.module_id, work.work_id),
        port=_GuidedPort(
            kind=kind,
            revalidate=validate,
            read=read,
            write=write,
            select=select,
        ),
    )


def prepare_eligibility_action(
    root: Path,
    prepared: GuidedProjectionResult,
    context: GuidedEligibilityContext,
    authoring: NewEvidenceEligibilityAuthoringPreview,
    actor: TeacherActionActor,
    dependencies: GuidedEligibilityDependencies,
) -> PreparedGuidedAction:
    """Bind one teacher-chosen eligibility decision and authorized projection."""
    root = _root(root)
    candidate = authoring.decision
    class_id, gi, source = candidate.class_id, candidate.grade_item_id, candidate.source
    if candidate.actor.actor_id != actor.actor_id or candidate.actor.kind != "teacher":
        raise TeacherActionConflictError("Eligibility actor differs from review.")
    digest = _sha(evidence_eligibility_decision_to_json_bytes(candidate))
    membership = load_current_grade_item_membership_decision(
        root,
        class_id,
        gi,
        source.work,
    )
    if membership is None or (
        membership.decision.membership_revision != candidate.membership_revision
        or membership.decision_sha256 != candidate.membership_revision_sha256
    ):
        raise TeacherActionConflictError("Grade Item membership changed.")
    assignment = membership.decision.academic_period
    if membership.decision.decision != "included" or assignment is None:
        raise TeacherActionConflictError("Eligibility membership is not included.")
    period = assignment.period
    calendar_revision = assignment.calendar_revision
    calendar_sha = _calendar_digest(root, period.school_year, calendar_revision)
    previous = load_current_evidence_eligibility_decision(root, class_id, gi, source)
    previous_rev = None if previous is None else previous.decision.eligibility_revision
    previous_sha = None if previous is None else previous.decision_sha256
    if previous_rev != authoring.selected_revision:
        raise TeacherActionConflictError("Eligibility selection changed since review.")

    def validate() -> None:
        _actor_now(actor)
        validate_evidence_eligibility_dependencies(
            root,
            candidate,
            prepared.authorized,
            require_current_membership=True,
            require_authored_source_state=True,
        )
        validate_grade_item_membership_dependencies(root, membership.decision)
        if (
            _calendar_digest(root, period.school_year, calendar_revision)
            != calendar_sha
        ):
            raise TeacherActionConflictError("Academic period changed.")
        revisions = list_evidence_eligibility_revisions(root, class_id, gi, source)
        expected = tuple(range(1, candidate.eligibility_revision))
        if revisions not in (expected, (*expected, candidate.eligibility_revision)):
            raise TeacherActionConflictError("Eligibility history changed.")

    def read() -> Observation:
        history = list_evidence_eligibility_revisions(root, class_id, gi, source)
        target = (
            load_evidence_eligibility_revision(
                root,
                class_id,
                gi,
                source,
                candidate.eligibility_revision,
            )
            if candidate.eligibility_revision in history
            else None
        )
        current = load_current_evidence_eligibility_decision(root, class_id, gi, source)
        try:
            _actor_now(actor)
            validate_evidence_eligibility_dependencies(
                root,
                candidate,
                prepared.authorized,
                require_current_membership=True,
                require_authored_source_state=True,
            )
            validate_grade_item_membership_dependencies(root, membership.decision)
            if (
                _calendar_digest(
                    root,
                    period.school_year,
                    calendar_revision,
                )
                != calendar_sha
            ):
                raise TeacherActionConflictError("Academic period changed.")
            state: Literal["current", "stale"] = "current"
        except Exception:
            state = "stale"
        return (
            None if target is None else target.decision_sha256,
            None if current is None else current.decision.eligibility_revision,
            None if current is None else current.decision_sha256,
            state,
        )

    def write() -> Literal["created", "existing"]:
        result = commit_guided_eligibility(
            root,
            prepared,
            authoring,
            dependencies=dependencies,
        )
        if result.write_result.disposition == "created":
            return "created"
        if result.write_result.disposition == "existing":
            return "existing"
        raise TeacherActionConflictError("Unexpected canonical write disposition.")

    def select() -> SelectionDisposition:
        reviewed = preview_guided_eligibility_selection(
            root,
            prepared,
            context,
            candidate.eligibility_revision,
            dependencies=dependencies,
        )
        if (
            reviewed.target.decision_sha256 != digest
            or reviewed.expected_current_revision != previous_rev
        ):
            raise TeacherActionConflictError("Eligibility selector baseline changed.")
        result = commit_guided_eligibility_selection(
            root,
            prepared,
            reviewed,
            dependencies=dependencies,
        )
        value = result.selection_disposition
        if value not in ("created", "updated", "existing"):
            raise TeacherActionConflictError(
                "Unexpected canonical selector disposition."
            )
        if value == "created":
            return "created"
        if value == "updated":
            return "updated"
        return "existing"

    kind: ActionKind = "eligibility"
    return _prepare(
        root=root,
        class_id=class_id,
        grade_item_id=gi,
        actor=actor,
        kind=kind,
        revision=candidate.eligibility_revision,
        candidate_sha256=digest,
        current_revision=previous_rev,
        current_sha256=previous_sha,
        identity=_identity(
            "eligibility",
            class_id,
            gi,
            source.work.module_id,
            source.work.work_id,
            source.publication_id,
            source.item_id,
        ),
        source_binding=_identity(
            "source",
            source.publication_id,
            source.cache_key,
            source.snapshot_digest,
            candidate.membership_revision_sha256,
        ),
        school_year=period.school_year,
        academic_period_id=period.period_id,
        calendar_sha256=calendar_sha,
        work_identity_sha256=_identity(
            "work",
            class_id,
            source.work.module_id,
            source.work.work_id,
        ),
        port=_GuidedPort(
            kind=kind,
            revalidate=validate,
            read=read,
            write=write,
            select=select,
        ),
    )


__all__ = (
    "PreparedGuidedAction",
    "bind_reviewed_actor",
    "resolve_menu_actor",
    "prepare_grade_item_action",
    "prepare_membership_action",
    "prepare_eligibility_action",
)
