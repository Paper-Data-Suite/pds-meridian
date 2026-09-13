from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pds_core.academic_periods import AcademicPeriodRef

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
from meridian.conventional_grade import (
    calculate_conventional_grade,
    conventional_grade_result_snapshot_from_json_bytes,
    conventional_grade_result_snapshot_to_json_bytes,
    create_conventional_grade_result_snapshot,
)
from meridian.conventional_grade_assembly import (
    ConventionalGradeWorkEvidenceSpec,
    assemble_conventional_grade_calculation,
)
from meridian.conventional_grade_storage import (
    get_current_conventional_grade_result_revision,
    load_current_conventional_grade_result,
    select_conventional_grade_result_revision,
    write_conventional_grade_result_revision,
)
from meridian.evidence import NativePointValue, NativeScaledValue
from meridian.evidence_eligibility import (
    EVIDENCE_ELIGIBILITY_RECORD_TYPE,
    EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
    EvidenceDecisionActor,
    EvidenceEligibilityDecision,
    EvidenceEligibilityPolicyReference,
    EvidenceSourceStateObservation,
)
from meridian.grade_item_membership_storage import (
    select_grade_item_membership_revision,
    write_grade_item_membership_revision,
)
from meridian.grade_item_memberships import (
    GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
    GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_item_storage import (
    select_grade_item_revision,
    write_grade_item_revision,
)
from meridian.grade_items import (
    GRADE_ITEM_RECORD_TYPE,
    GRADE_ITEM_SCHEMA_VERSION,
    GradeItemRevision,
    GradeItemWorkReference,
)
from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GRADE_POLICY_SCHEMA_VERSION,
    ConventionalGradeConfiguration,
    GradePolicyActor,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyRevision,
    GradeReassessmentHandling,
    GradeRoundingPolicy,
    GradeStateTreatment,
)
from meridian.grade_policy_activation import (
    GRADE_POLICY_ACTIVATION_RECORD_TYPE,
    GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
    GradePolicyActivationDecision,
)
from meridian.grade_policy_activation_storage import (
    select_grade_policy_activation_revision,
    write_grade_policy_activation_revision,
)
from meridian.grade_policy_storage import write_grade_policy_revision
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
from tests.cross_producer_attempts_support import (
    Issue44AttemptWorkspace,
    prepare_attempt_workspace,
)
from tests.cross_producer_proficiency_support import (
    ACTOR_ID,
    NOW,
    PERIOD_ID,
    SCHOOL_YEAR,
    representative_items,
    source_reference,
)
from tests.cross_producer_test_support import SHARED_STUDENT_ID
from tests.cross_producer_workspace_support import CLASS_ID, SCOREFORM_WORK

GRADE_ITEM_ID = "issue50_conventional_grade"
GRADE_POLICY_ID = "issue50_total_points"
ELIGIBILITY_POLICY_ID = "issue50_explicit_eligibility"
ATTEMPT_POLICY_ID = "issue50_explicit_attempts"
REASSESSMENT_POLICY_ID = "issue50_explicit_reassessment"
PERIOD = AcademicPeriodRef(SCHOOL_YEAR, PERIOD_ID)
CALENDAR_REVISION = 1
RESULT_TIME = datetime(2026, 9, 10, 23, 0, tzinfo=UTC)


def _tree_bytes(root: Path, module_id: str) -> dict[str, bytes]:
    base = root / "classes" / CLASS_ID / "modules" / module_id
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def _state_treatment() -> GradeStateTreatment:
    return GradeStateTreatment(
        missing="blocking",
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="blocking",
        unavailable="blocking",
        withdrawn="exclude",
        invalid="exclude",
        unresolved="blocking",
    )


def _install_conventional_grade_item(root: Path) -> tuple[GradeItemRevision, str]:
    item = GradeItemRevision(
        schema_version=GRADE_ITEM_SCHEMA_VERSION,
        record_type=GRADE_ITEM_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=1,
        supersedes_revision=None,
        title="Issue 50 conventional ScoreForm Grade Item",
        purpose="conventional_grade",
        status="active",
        weighting=None,
        created_at=NOW,
        revised_at=NOW,
    )
    stored = write_grade_item_revision(root, item).stored
    select_grade_item_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        1,
        expected_current_revision=None,
    )
    return item, stored.revision_sha256


def _install_membership(
    root: Path,
    item: GradeItemRevision,
    item_sha256: str,
) -> tuple[GradeItemMembershipDecision, str]:
    membership = GradeItemMembershipDecision(
        schema_version=GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
        record_type=GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=item.grade_item_revision,
        grade_item_revision_sha256=item_sha256,
        work_reference=GradeItemWorkReference(
            work=SCOREFORM_WORK,
            registration_revision=1,
        ),
        membership_revision=1,
        supersedes_revision=None,
        decision="included",
        academic_period=GradeItemAcademicPeriodAssignment(
            period=PERIOD,
            calendar_revision=CALENDAR_REVISION,
        ),
        actor_id=ACTOR_ID,
        rationale="Explicit issue #50 ScoreForm work membership.",
        decided_at=NOW,
    )
    stored = write_grade_item_membership_revision(root, membership).stored
    select_grade_item_membership_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        SCOREFORM_WORK,
        1,
        expected_current_membership_revision=None,
    )
    return membership, stored.decision_sha256


def _install_eligibility(
    root: Path,
    scenario: Issue44AttemptWorkspace,
    membership: GradeItemMembershipDecision,
    membership_sha256: str,
) -> None:
    projection = scenario.projected["scoreform"]
    authorized = scenario.authorized["scoreform"]
    for item in projection.inventory.items:
        if item.subject is None or item.subject.student_id != SHARED_STUDENT_ID:
            continue
        source = source_reference(projection, item)
        decision = EvidenceEligibilityDecision(
            schema_version=EVIDENCE_ELIGIBILITY_SCHEMA_VERSION,
            record_type=EVIDENCE_ELIGIBILITY_RECORD_TYPE,
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            source=source,
            membership_revision=membership.membership_revision,
            membership_revision_sha256=membership_sha256,
            eligibility_revision=1,
            supersedes_revision=None,
            disposition="included",
            actor=EvidenceDecisionActor("teacher", ACTOR_ID),
            policy=EvidenceEligibilityPolicyReference(
                ELIGIBILITY_POLICY_ID,
                "1",
            ),
            reason_codes=(),
            rationale="Explicit issue #50 conventional-Grade inclusion.",
            source_state=EvidenceSourceStateObservation(
                state="current",
                head_publication_id=source.publication_id,
                successor_publication_id=None,
                withdrawn_at=None,
            ),
            decided_at=NOW,
        )
        eligibility_storage.write_evidence_eligibility_revision(
            root,
            decision,
            authorized_snapshot=authorized,
        )
        eligibility_storage.select_evidence_eligibility_revision(
            root,
            CLASS_ID,
            GRADE_ITEM_ID,
            source,
            1,
            authorized_snapshot=authorized,
            expected_current_eligibility_revision=None,
        )


def _install_attempt_and_reassessment(
    root: Path,
    scenario: Issue44AttemptWorkspace,
    membership_sha256: str,
) -> None:
    authorized = scenario.authorized["scoreform"]
    derivation = attempt_storage.derive_attempt_candidates(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        SHARED_STUDENT_ID,
        authorized,
    )
    assert len(derivation.candidates) == 2

    attempt_policy = AttemptSelectionPolicy(
        schema_version=ATTEMPT_SELECTION_POLICY_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=SCOREFORM_WORK,
        policy_id=ATTEMPT_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        selection_basis="explicit",
        minimum_selected=2,
        maximum_selected=2,
        actor=AttemptSelectionActor("teacher", ACTOR_ID),
        rationale="Issue #50 explicitly retains both native attempts for #31.",
        revised_at=NOW,
    )
    stored_attempt_policy = attempt_storage.write_attempt_selection_policy_revision(
        root,
        attempt_policy,
    ).stored
    attempt_storage.select_attempt_selection_policy_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        SCOREFORM_WORK,
        ATTEMPT_POLICY_ID,
        1,
        expected_current_policy_revision=None,
    )
    selection = AttemptSelectionDecision(
        schema_version=ATTEMPT_SELECTION_DECISION_SCHEMA_VERSION,
        record_type=ATTEMPT_SELECTION_DECISION_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=SCOREFORM_WORK,
        student_id=SHARED_STUDENT_ID,
        membership_revision=1,
        membership_revision_sha256=membership_sha256,
        policy=AttemptSelectionPolicyReference(
            ATTEMPT_POLICY_ID,
            1,
            stored_attempt_policy.policy_sha256,
        ),
        source_snapshot=derivation.source_snapshot,
        candidates=derivation.candidates,
        selected_attempts=tuple(item.attempt for item in derivation.candidates),
        decision_revision=1,
        supersedes_revision=None,
        actor=AttemptSelectionActor("teacher", ACTOR_ID),
        rationale="Both attempts are explicitly selected before reassessment.",
        decided_at=NOW,
    )
    stored_selection = attempt_storage.write_attempt_selection_decision_revision(
        root,
        selection,
        authorized_snapshot=authorized,
    ).stored
    attempt_storage.select_attempt_selection_decision_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        SCOREFORM_WORK,
        SHARED_STUDENT_ID,
        1,
        authorized_snapshot=authorized,
        expected_current_decision_revision=None,
    )

    by_sequence = {
        item.attempt.native.sequence: item.attempt for item in derivation.candidates
    }
    first = by_sequence[1]
    second = by_sequence[2]
    reassessment_policy = ReassessmentPolicy(
        schema_version=REASSESSMENT_POLICY_SCHEMA_VERSION,
        record_type=REASSESSMENT_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=SCOREFORM_WORK,
        policy_id=REASSESSMENT_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        relationship_basis="explicit",
        allowed_modes=("replace",),
        actor=ReassessmentActor("teacher", ACTOR_ID),
        rationale="Issue #50 exact replacement policy.",
        revised_at=NOW,
    )
    stored_reassessment_policy = (
        reassessment_storage.write_reassessment_policy_revision(
            root,
            reassessment_policy,
        ).stored
    )
    reassessment_storage.select_reassessment_policy_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        SCOREFORM_WORK,
        REASSESSMENT_POLICY_ID,
        1,
        expected_current_policy_revision=None,
    )
    decision = ReassessmentDecision(
        schema_version=REASSESSMENT_DECISION_SCHEMA_VERSION,
        record_type=REASSESSMENT_DECISION_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=SCOREFORM_WORK,
        student_id=SHARED_STUDENT_ID,
        attempt_selection=AttemptSelectionDecisionReference(
            stored_selection.decision.decision_revision,
            stored_selection.decision_sha256,
        ),
        policy=ReassessmentPolicyReference(
            REASSESSMENT_POLICY_ID,
            1,
            stored_reassessment_policy.policy_sha256,
        ),
        mode="replace",
        contributing_attempts=(second,),
        replacement_relationships=(ReplacementRelationship(second, (first,)),),
        combinations=(),
        recency_order=(),
        decision_revision=1,
        supersedes_revision=None,
        actor=ReassessmentActor("teacher", ACTOR_ID),
        rationale="Attempt 2 explicitly replaces attempt 1.",
        decided_at=NOW,
    )
    reassessment_storage.write_reassessment_decision_revision(
        root,
        decision,
        authorized_snapshot=authorized,
    )
    reassessment_storage.select_reassessment_decision_revision(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        SCOREFORM_WORK,
        SHARED_STUDENT_ID,
        1,
        authorized_snapshot=authorized,
        expected_current_decision_revision=None,
    )
    resolved = reassessment_storage.resolve_current_reassessment(
        root,
        CLASS_ID,
        GRADE_ITEM_ID,
        SCOREFORM_WORK,
        SHARED_STUDENT_ID,
        authorized_snapshot=authorized,
    )
    assert resolved.status == "resolved"
    assert resolved.contributing_attempts == (second,)


def _install_grade_policy(root: Path, item_sha256: str) -> None:
    policy = GradePolicyRevision(
        schema_version=GRADE_POLICY_SCHEMA_VERSION,
        record_type=GRADE_POLICY_RECORD_TYPE,
        class_id=CLASS_ID,
        policy_id=GRADE_POLICY_ID,
        policy_revision=1,
        supersedes_revision=None,
        title="Issue 50 total-points policy",
        calculation_family="conventional",
        configuration=ConventionalGradeConfiguration(
            mode="total_points",
            items=(
                GradePolicyItemParticipation(
                    grade_item=GradePolicyItemReference(
                        CLASS_ID,
                        GRADE_ITEM_ID,
                        1,
                        item_sha256,
                    ),
                    category_id=None,
                    weight=None,
                    possible_points=Decimal("3"),
                ),
            ),
            categories=(),
        ),
        state_treatment=_state_treatment(),
        reassessment_handling=GradeReassessmentHandling(
            "v02_attempt_and_reassessment_state",
            "blocking",
        ),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale="Issue #50 installed-style conventional Grade acceptance.",
        revised_at=NOW,
    )
    stored_policy = write_grade_policy_revision(root, policy).stored
    activation = GradePolicyActivationDecision(
        schema_version=GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
        record_type=GRADE_POLICY_ACTIVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=CALENDAR_REVISION,
        activation_revision=1,
        supersedes_revision=None,
        decision="activate",
        policy_reference=stored_policy.reference,
        actor=GradePolicyActor("teacher", ACTOR_ID),
        rationale="Explicitly activate the exact issue #50 Grade policy.",
        decided_at=NOW,
    )
    write_grade_policy_activation_revision(root, activation)
    select_grade_policy_activation_revision(
        root,
        CLASS_ID,
        PERIOD,
        1,
        expected_current_revision=None,
    )


def test_released_scoreform_points_flow_through_v02_authority_and_result_history(
    tmp_path: Path,
) -> None:
    scenario = prepare_attempt_workspace(tmp_path)
    root = scenario.mixed.root
    producer_before = {
        module_id: _tree_bytes(root, module_id)
        for module_id in ("scoreform", "quillan", "concord")
    }

    item, item_sha256 = _install_conventional_grade_item(root)
    membership, membership_sha256 = _install_membership(root, item, item_sha256)
    _install_eligibility(root, scenario, membership, membership_sha256)
    _install_attempt_and_reassessment(root, scenario, membership_sha256)
    _install_grade_policy(root, item_sha256)

    work_evidence = (
        ConventionalGradeWorkEvidenceSpec(
            grade_item_id=GRADE_ITEM_ID,
            work=SCOREFORM_WORK,
            status="available",
            authorized_snapshots=(scenario.authorized["scoreform"],),
        ),
    )
    assembly = assemble_conventional_grade_calculation(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
        work_evidence,
    )
    assert assembly.outcome.status == "calculated"
    assert assembly.outcome.rounded_grade == Decimal("33.33")
    assert len(assembly.inputs.items) == 1
    exact = assembly.inputs.items[0]
    assert exact.status == "points"
    assert exact.earned == Decimal("1")
    assert exact.possible == Decimal("3")
    provenance_kinds = {item.kind for item in exact.provenance}
    assert {
        "source",
        "membership",
        "eligibility",
        "attempt_selection",
        "reassessment",
    }.issubset(provenance_kinds)

    snapshot = create_conventional_grade_result_snapshot(
        assembly.inputs,
        assembly.outcome,
        result_revision=1,
        calculated_at=RESULT_TIME,
    )
    written = write_conventional_grade_result_revision(
        root,
        snapshot,
        work_evidence=work_evidence,
    )
    assert written.disposition == "created"
    assert get_current_conventional_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    ) is None

    selected = select_conventional_grade_result_revision(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
        1,
        expected_current_result_revision=None,
    )
    assert selected.disposition == "created"
    reloaded = load_current_conventional_grade_result(
        root,
        CLASS_ID,
        SHARED_STUDENT_ID,
        PERIOD,
        CALENDAR_REVISION,
    )
    assert reloaded is not None
    assert reloaded.reference == selected.stored.reference
    assert calculate_conventional_grade(reloaded.snapshot.inputs) == (
        reloaded.snapshot.outcome
    )
    canonical = conventional_grade_result_snapshot_to_json_bytes(reloaded.snapshot)
    assert conventional_grade_result_snapshot_from_json_bytes(canonical) == (
        reloaded.snapshot
    )
    assert conventional_grade_result_snapshot_to_json_bytes(
        conventional_grade_result_snapshot_from_json_bytes(canonical)
    ) == canonical

    producer_after = {
        module_id: _tree_bytes(root, module_id)
        for module_id in ("scoreform", "quillan", "concord")
    }
    assert producer_after == producer_before


def test_released_producer_semantics_do_not_create_generic_conventional_points(
    tmp_path: Path,
) -> None:
    scenario = prepare_attempt_workspace(tmp_path)
    items = representative_items(scenario.projected)

    assert isinstance(items.scoreform_points.value, NativePointValue)
    assert items.scoreform_points.value.earned == 2
    assert items.scoreform_points.value.possible == 3

    assert isinstance(items.quillan_overall.value, NativeScaledValue)
    assert not isinstance(items.quillan_overall.value, NativePointValue)

    assert isinstance(items.concord_student.value, NativeScaledValue)
    assert not isinstance(items.concord_student.value, NativePointValue)
    assert items.concord_group_current.subject is None
    assert isinstance(items.concord_group_current.value, NativeScaledValue)
