"""Real #30/#31 cross-producer acceptance support for Meridian issue #44."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pds_core.academic_period_storage import write_academic_period_calendar
from pds_core.academic_periods import AcademicPeriod, AcademicPeriodCalendar
from pds_core.class_metadata import ClassMetadata, write_class_metadata
from pds_core.routes import class_metadata_path

import meridian.attempt_selection_storage as attempt_storage
import meridian.evidence_eligibility_storage as eligibility_storage
import meridian.reassessment_storage as reassessment_storage
from meridian.attempt_selection import (
    ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
    ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
    ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
    ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
    AttemptSelectionActor,
    AttemptSelectionDecision,
    AttemptSelectionPolicy,
    AttemptSelectionPolicyReference,
)
from meridian.grade_item_membership_storage import (
    select_grade_item_membership_revision,
    write_grade_item_membership_revision,
)
from meridian.grade_item_storage import write_grade_item_revision
from meridian.projection_cache import (
    AuthorizedProjectionSnapshot,
    load_authorized_projection_snapshot,
)
from meridian.reassessment import (
    REASSESSMENT_DECISION_RECORD_TYPE,
    REASSESSMENT_DECISION_SCHEMA_VERSION,
    REASSESSMENT_POLICY_RECORD_TYPE,
    REASSESSMENT_POLICY_SCHEMA_VERSION,
    AttemptSelectionDecisionReference,
    ReassessmentActor,
    ReassessmentDecision,
    ReassessmentPolicy,
    ReassessmentPolicyReference,
    ReplacementRelationship,
)
from tests.cross_producer_proficiency_support import (
    ACTOR_ID,
    GRADE_ITEM_ID,
    NOW,
    PERIOD_ID,
    SCHOOL_YEAR,
    cross_producer_grade_item,
    cross_producer_memberships,
    included_eligibility,
    membership_for_module,
    source_reference,
)
from tests.cross_producer_test_support import (
    SHARED_STUDENT_ID,
    exact_reader_version,
)
from tests.cross_producer_workspace_support import (
    CachedProjection,
    MixedWorkspace,
    build_mixed_workspace,
    prepare_all,
    project_and_cache_all,
)

ATTEMPT_POLICY_ID = "issue44_explicit_attempts"
REASSESSMENT_POLICY_ID = "issue44_explicit_reassessment"


@dataclass(frozen=True, slots=True)
class Issue44AttemptWorkspace:
    """One real mixed workspace prepared through current #28-#31 seams."""

    mixed: MixedWorkspace
    projected: dict[str, CachedProjection]
    authorized: dict[str, AuthorizedProjectionSnapshot]
    membership_digests: dict[str, str]


def _install_academic_context(root: Path) -> None:
    metadata = ClassMetadata(
        class_id=next(iter(cross_producer_memberships())).class_id,
        school_year=SCHOOL_YEAR,
        created_at=NOW,
        updated_at=NOW,
        module_details={},
    )
    write_class_metadata(class_metadata_path(root, metadata.class_id), metadata)
    calendar = AcademicPeriodCalendar(
        schema_version="1",
        record_type="academic_period_calendar",
        school_year=SCHOOL_YEAR,
        calendar_revision=1,
        created_at=NOW,
        updated_at=NOW,
        periods=(
            AcademicPeriod(
                period_id=PERIOD_ID,
                period_type="quarter",
                label="Quarter 1",
                start_date=date(2026, 9, 1),
                end_date=date(2026, 11, 6),
                parent_period_id=None,
                sequence=1,
                lifecycle="active",
            ),
        ),
    )
    write_academic_period_calendar(
        root,
        calendar,
        expected_current_revision=None,
    )


def _authorized_projection(
    mixed: MixedWorkspace,
    projected: CachedProjection,
    module_id: str,
) -> AuthorizedProjectionSnapshot:
    return load_authorized_projection_snapshot(
        mixed.root,
        mixed.publications[module_id].publication_id,
        projected.cached.stored.cache_key,
        authorizer=mixed.authorizer,
        authorization_purpose_id="grading_import",
        producer_registry=mixed.producer_registry,
        adapter_registry=mixed.adapter_registry,
        distribution_version_resolver=exact_reader_version,
    )


def prepare_attempt_workspace(tmp_path: Path) -> Issue44AttemptWorkspace:
    """Persist real #28/#29 state and return exact authorized producer snapshots."""
    mixed = build_mixed_workspace(tmp_path)
    _install_academic_context(mixed.root)

    item = cross_producer_grade_item()
    stored_item = write_grade_item_revision(mixed.root, item).stored
    memberships = cross_producer_memberships(item)
    membership_digests: dict[str, str] = {}
    for membership in memberships:
        module_id = membership.work_reference.work.module_id
        written = write_grade_item_membership_revision(
            mixed.root,
            membership,
        ).stored
        select_grade_item_membership_revision(
            mixed.root,
            membership.class_id,
            membership.grade_item_id,
            membership.work_reference.work,
            membership.membership_revision,
            expected_current_membership_revision=None,
        )
        membership_digests[module_id] = written.decision_sha256

    if not stored_item.revision_sha256:
        raise AssertionError("Grade Item storage must expose an exact digest.")

    projected = project_and_cache_all(mixed, prepare_all(mixed))
    authorized = {
        module_id: _authorized_projection(
            mixed,
            projected[module_id],
            module_id,
        )
        for module_id in ("scoreform", "quillan", "concord")
    }

    scoreform_membership = membership_for_module(memberships, "scoreform")
    for evidence_item in projected["scoreform"].inventory.items:
        subject = evidence_item.subject
        if subject is None or subject.student_id != SHARED_STUDENT_ID:
            continue
        source = source_reference(projected["scoreform"], evidence_item)
        decision = included_eligibility(source, scoreform_membership)
        eligibility_storage.write_evidence_eligibility_revision(
            mixed.root,
            decision,
            authorized_snapshot=authorized["scoreform"],
        )
        eligibility_storage.select_evidence_eligibility_revision(
            mixed.root,
            decision.class_id,
            decision.grade_item_id,
            decision.source,
            decision.eligibility_revision,
            authorized_snapshot=authorized["scoreform"],
            expected_current_eligibility_revision=None,
        )

    return Issue44AttemptWorkspace(
        mixed=mixed,
        projected=projected,
        authorized=authorized,
        membership_digests=membership_digests,
    )


def derive_scoreform_attempts(
    scenario: Issue44AttemptWorkspace,
) -> attempt_storage.AttemptCandidateDerivation:
    """Derive exact ScoreForm attempts from current selected eligibility."""
    return attempt_storage.derive_attempt_candidates(
        scenario.mixed.root,
        scenario.mixed.publications["scoreform"].work.class_id,
        GRADE_ITEM_ID,
        SHARED_STUDENT_ID,
        scenario.authorized["scoreform"],
    )


def select_both_scoreform_attempts(
    scenario: Issue44AttemptWorkspace,
    derivation: attempt_storage.AttemptCandidateDerivation,
) -> attempt_storage.AttemptSelectionResolution:
    """Persist/select an explicit #30 decision containing both exact attempts."""
    work = scenario.mixed.publications["scoreform"].work
    policy = AttemptSelectionPolicy(
        schema_version=ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
        class_id=work.class_id,
        grade_item_id=GRADE_ITEM_ID,
        work=work,
        policy_id=ATTEMPT_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        selection_basis="explicit",
        minimum_selected=2,
        maximum_selected=2,
        actor=AttemptSelectionActor("teacher", ACTOR_ID),
        rationale="Issue #44 selects both producer-native attempts explicitly.",
        revised_at=NOW,
    )
    stored_policy = attempt_storage.write_attempt_selection_policy_revision(
        scenario.mixed.root,
        policy,
    ).stored
    attempt_storage.select_attempt_selection_policy_revision(
        scenario.mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        policy.policy_id,
        policy.policy_revision,
        expected_current_policy_revision=None,
    )

    decision = AttemptSelectionDecision(
        schema_version=ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
        class_id=work.class_id,
        grade_item_id=GRADE_ITEM_ID,
        work=work,
        student_id=SHARED_STUDENT_ID,
        membership_revision=1,
        membership_revision_sha256=scenario.membership_digests["scoreform"],
        policy=AttemptSelectionPolicyReference(
            policy_id=policy.policy_id,
            policy_revision=policy.policy_revision,
            policy_revision_sha256=stored_policy.policy_sha256,
        ),
        source_snapshot=derivation.source_snapshot,
        candidates=derivation.candidates,
        selected_attempts=tuple(
            candidate.attempt for candidate in derivation.candidates
        ),
        decision_revision=1,
        supersedes_revision=None,
        actor=AttemptSelectionActor("teacher", ACTOR_ID),
        rationale="Both attempts remain selected before reassessment.",
        decided_at=NOW,
    )
    attempt_storage.write_attempt_selection_decision_revision(
        scenario.mixed.root,
        decision,
        authorized_snapshot=scenario.authorized["scoreform"],
    )
    attempt_storage.select_attempt_selection_decision_revision(
        scenario.mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        decision.decision_revision,
        authorized_snapshot=scenario.authorized["scoreform"],
        expected_current_decision_revision=None,
    )
    return attempt_storage.resolve_current_attempt_selection(
        scenario.mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        authorized_snapshot=scenario.authorized["scoreform"],
    )


def replace_first_with_second_attempt(
    scenario: Issue44AttemptWorkspace,
    selection: attempt_storage.AttemptSelectionResolution,
) -> reassessment_storage.ReassessmentResolution:
    """Persist/select an explicit #31 replacement and resolve current use."""
    assert selection.selected is not None
    work = scenario.mixed.publications["scoreform"].work
    selected_attempts = selection.selected.decision.selected_attempts
    by_sequence = {
        attempt.native.sequence: attempt
        for attempt in selected_attempts
    }
    first = by_sequence[1]
    second = by_sequence[2]

    policy = ReassessmentPolicy(
        schema_version=REASSESSMENT_POLICY_SCHEMA_VERSION,
        record_type=REASSESSMENT_POLICY_RECORD_TYPE,
        class_id=work.class_id,
        grade_item_id=GRADE_ITEM_ID,
        work=work,
        policy_id=REASSESSMENT_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        relationship_basis="explicit",
        allowed_modes=("replace",),
        actor=ReassessmentActor("teacher", ACTOR_ID),
        rationale="Issue #44 explicit replacement policy.",
        revised_at=NOW,
    )
    stored_policy = reassessment_storage.write_reassessment_policy_revision(
        scenario.mixed.root,
        policy,
    ).stored
    reassessment_storage.select_reassessment_policy_revision(
        scenario.mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        policy.policy_id,
        policy.policy_revision,
        expected_current_policy_revision=None,
    )

    decision = ReassessmentDecision(
        schema_version=REASSESSMENT_DECISION_SCHEMA_VERSION,
        record_type=REASSESSMENT_DECISION_RECORD_TYPE,
        class_id=work.class_id,
        grade_item_id=GRADE_ITEM_ID,
        work=work,
        student_id=SHARED_STUDENT_ID,
        attempt_selection=AttemptSelectionDecisionReference(
            selection.selected.decision.decision_revision,
            selection.selected.decision_sha256,
        ),
        policy=ReassessmentPolicyReference(
            policy.policy_id,
            policy.policy_revision,
            stored_policy.policy_sha256,
        ),
        mode="replace",
        contributing_attempts=(second,),
        replacement_relationships=(
            ReplacementRelationship(second, (first,)),
        ),
        combinations=(),
        recency_order=(),
        decision_revision=1,
        supersedes_revision=None,
        actor=ReassessmentActor("teacher", ACTOR_ID),
        rationale=(
            "Attempt 2 explicitly replaces attempt 1; no score or chronology "
            "inference is used."
        ),
        decided_at=NOW,
    )
    reassessment_storage.write_reassessment_decision_revision(
        scenario.mixed.root,
        decision,
        authorized_snapshot=scenario.authorized["scoreform"],
    )
    reassessment_storage.select_reassessment_decision_revision(
        scenario.mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        decision.decision_revision,
        authorized_snapshot=scenario.authorized["scoreform"],
        expected_current_decision_revision=None,
    )
    return reassessment_storage.resolve_current_reassessment(
        scenario.mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        authorized_snapshot=scenario.authorized["scoreform"],
    )
