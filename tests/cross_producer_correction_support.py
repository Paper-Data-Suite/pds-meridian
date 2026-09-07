"""ScoreForm Core-correction support for Meridian issue #44."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from pds_core.academic_catalog import PublicationCatalogQuery, rebuild_academic_catalog

import meridian.attempt_selection_storage as attempt_storage
import meridian.evidence_eligibility_storage as eligibility_storage
import meridian.ingestion as ingestion
import meridian.reassessment_storage as reassessment_storage
import meridian.standards_evidence_storage as standards_storage
from meridian.evidence import EvidenceItem, NativeScalarValue, NativeStateValue
from meridian.projection_cache import (
    AuthorizedProjectionSnapshot,
    cache_projected_inventory,
    load_authorized_projection_snapshot,
)
from meridian.reassessment import (
    AttemptSelectionDecisionReference,
    ReplacementRelationship,
)
from tests.cross_producer_academic_period_support import Issue44PeriodScenario
from tests.cross_producer_proficiency_support import (
    GRADE_ITEM_ID,
    NOW,
    associated_standard,
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
    supersede_scoreform,
)


@dataclass(frozen=True, slots=True)
class CorrectedScoreFormScenario:
    """Exact Core successor plus freshly persisted #29-#31 interpretation."""

    successor: object
    projection: CachedProjection
    authorized: AuthorizedProjectionSnapshot
    first_correctness: EvidenceItem
    second_ambiguous: EvidenceItem
    bindings: tuple[standards_storage.StandardAggregationCandidateBinding, ...]


def _native_sequence(item: EvidenceItem, kind: str) -> int | None:
    values = tuple(
        reference.sequence
        for reference in item.provenance.native.references
        if reference.kind == kind
    )
    if len(values) != 1:
        raise AssertionError(f"Expected exactly one {kind} native reference.")
    return values[0]


def _successor_projection(
    scenario: Issue44PeriodScenario,
) -> tuple[object, CachedProjection, AuthorizedProjectionSnapshot]:
    aggregation = scenario.aggregation
    workspace = aggregation.workspace
    mixed = workspace.mixed
    successor = supersede_scoreform(mixed)
    rebuild_academic_catalog(mixed.root)

    discovered = ingestion.discover_publication_candidates(
        mixed.root,
        ingestion.PublicationDiscoveryRequest(
            PublicationCatalogQuery(
                module_id="scoreform",
                state="current",
                limit=10,
            )
        ),
    )
    if len(discovered.candidates) != 1:
        raise AssertionError("ScoreForm correction must have one current publication.")
    candidate = discovered.candidates[0]
    if candidate.publication_id != successor.publication_id:
        raise AssertionError("Core catalog must select the exact ScoreForm successor.")

    prepared = ingestion.prepare_publication_invocation(
        mixed.root,
        candidate,
        producer_registry=mixed.producer_registry,
        adapter_registry=mixed.adapter_registry,
        authorizer=mixed.authorizer,
        authorization_purpose_id="grading_import",
        requested_student_ids=(),
        distribution_version_resolver=exact_reader_version,
    )
    inventory = mixed.adapter_registry.invoke(
        prepared.projection_request,
        exact_reader_version,
    )
    cached = cache_projected_inventory(
        mixed.root,
        prepared,
        inventory,
        authorizer=mixed.authorizer,
    )
    projection = CachedProjection(prepared, inventory, cached)
    authorized = load_authorized_projection_snapshot(
        mixed.root,
        successor.publication_id,
        cached.stored.cache_key,
        authorizer=mixed.authorizer,
        authorization_purpose_id="grading_import",
        producer_registry=mixed.producer_registry,
        adapter_registry=mixed.adapter_registry,
        distribution_version_resolver=exact_reader_version,
    )
    return successor, projection, authorized


def _scoreform_items(
    projection: CachedProjection,
) -> tuple[EvidenceItem, EvidenceItem]:
    first_correctness = next(
        item
        for item in projection.inventory.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "question_correctness"
        and item.target.target_id == "question_1"
        and _native_sequence(item, "attempt") == 1
        and isinstance(item.value, NativeScalarValue)
        and item.value.value is True
    )
    second_ambiguous = next(
        item
        for item in projection.inventory.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "selected_response_state"
        and item.target.target_id == "question_1"
        and _native_sequence(item, "attempt") == 2
        and isinstance(item.value, NativeStateValue)
        and item.value.code == "ambiguous"
    )
    return first_correctness, second_ambiguous


def _persist_successor_eligibility(
    scenario: Issue44PeriodScenario,
    projection: CachedProjection,
    authorized: AuthorizedProjectionSnapshot,
) -> None:
    workspace = scenario.aggregation.workspace
    membership = membership_for_module(
        cross_producer_memberships(),
        "scoreform",
    )
    for item in projection.inventory.items:
        if item.subject is None or item.subject.student_id != SHARED_STUDENT_ID:
            continue
        source = source_reference(projection, item)
        decision = included_eligibility(source, membership)
        eligibility_storage.write_evidence_eligibility_revision(
            workspace.mixed.root,
            decision,
            authorized_snapshot=authorized,
        )
        eligibility_storage.select_evidence_eligibility_revision(
            workspace.mixed.root,
            decision.class_id,
            decision.grade_item_id,
            decision.source,
            decision.eligibility_revision,
            authorized_snapshot=authorized,
            expected_current_eligibility_revision=None,
        )


def _refresh_attempt_selection(
    scenario: Issue44PeriodScenario,
    authorized: AuthorizedProjectionSnapshot,
) -> attempt_storage.AttemptSelectionResolution:
    workspace = scenario.aggregation.workspace
    mixed = workspace.mixed
    work = mixed.publications["scoreform"].work
    old = attempt_storage.load_attempt_selection_decision_revision(
        mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        1,
    )
    derivation = attempt_storage.derive_attempt_candidates(
        mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        SHARED_STUDENT_ID,
        authorized,
    )
    if derivation.status != "applicable" or len(derivation.candidates) != 2:
        raise AssertionError("Corrected ScoreForm must expose both exact attempts.")

    decision = replace(
        old.decision,
        source_snapshot=derivation.source_snapshot,
        candidates=derivation.candidates,
        selected_attempts=tuple(
            candidate.attempt for candidate in derivation.candidates
        ),
        decision_revision=2,
        supersedes_revision=1,
        rationale=(
            "Rebind the unchanged explicit two-attempt selection to the exact "
            "Core correction."
        ),
        decided_at=NOW + timedelta(minutes=1),
    )
    written = attempt_storage.write_attempt_selection_decision_revision(
        mixed.root,
        decision,
        authorized_snapshot=authorized,
    ).stored
    attempt_storage.select_attempt_selection_decision_revision(
        mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        decision.decision_revision,
        authorized_snapshot=authorized,
        expected_current_decision_revision=1,
    )
    resolution = attempt_storage.resolve_current_attempt_selection(
        mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        authorized_snapshot=authorized,
    )
    if resolution.selected is None:
        raise AssertionError("Corrected ScoreForm attempt selection must resolve.")
    if resolution.selected.decision_sha256 != written.decision_sha256:
        raise AssertionError("Selected corrected attempt decision must be exact.")
    return resolution


def _refresh_reassessment(
    scenario: Issue44PeriodScenario,
    selection: attempt_storage.AttemptSelectionResolution,
    authorized: AuthorizedProjectionSnapshot,
) -> reassessment_storage.ReassessmentResolution:
    workspace = scenario.aggregation.workspace
    mixed = workspace.mixed
    work = mixed.publications["scoreform"].work
    old = reassessment_storage.load_reassessment_decision_revision(
        mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        1,
    )
    if selection.selected is None:
        raise AssertionError("Corrected reassessment requires selected attempts.")
    selected = selection.selected.decision.selected_attempts
    by_sequence = {attempt.native.sequence: attempt for attempt in selected}
    first = by_sequence[1]
    second = by_sequence[2]

    decision = replace(
        old.decision,
        attempt_selection=AttemptSelectionDecisionReference(
            selection.selected.decision.decision_revision,
            selection.selected.decision_sha256,
        ),
        contributing_attempts=(second,),
        replacement_relationships=(
            ReplacementRelationship(second, (first,)),
        ),
        decision_revision=2,
        supersedes_revision=1,
        rationale=(
            "Rebind the explicit attempt-2-replaces-attempt-1 decision to the "
            "Core correction."
        ),
        decided_at=NOW + timedelta(minutes=2),
    )
    written = reassessment_storage.write_reassessment_decision_revision(
        mixed.root,
        decision,
        authorized_snapshot=authorized,
    ).stored
    reassessment_storage.select_reassessment_decision_revision(
        mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        decision.decision_revision,
        authorized_snapshot=authorized,
        expected_current_decision_revision=1,
    )
    resolution = reassessment_storage.resolve_current_reassessment(
        mixed.root,
        work.class_id,
        GRADE_ITEM_ID,
        work,
        SHARED_STUDENT_ID,
        authorized_snapshot=authorized,
    )
    if resolution.selected is None:
        raise AssertionError("Corrected ScoreForm reassessment must resolve.")
    if resolution.selected.decision_sha256 != written.decision_sha256:
        raise AssertionError("Selected corrected reassessment must be exact.")
    return resolution


def _persist_successor_associations(
    scenario: Issue44PeriodScenario,
    projection: CachedProjection,
    authorized: AuthorizedProjectionSnapshot,
    items: tuple[EvidenceItem, EvidenceItem],
) -> None:
    root = scenario.aggregation.workspace.mixed.root
    library = scenario.aggregation.standard_library
    for item in items:
        source = source_reference(projection, item)
        decision = associated_standard(
            source,
            basis="producer_declared",
        )
        standards_storage.write_standard_evidence_association_revision(
            root,
            decision,
            authorized_snapshot=authorized,
            standards_library=library,
        )
        standards_storage.select_standard_evidence_association_revision(
            root,
            decision.class_id,
            decision.grade_item_id,
            decision.source,
            decision.standard_id,
            decision.association_revision,
            expected_current_association_revision=None,
        )


def _replacement_bindings(
    scenario: Issue44PeriodScenario,
    projection: CachedProjection,
    authorized: AuthorizedProjectionSnapshot,
    first: EvidenceItem,
    second: EvidenceItem,
) -> tuple[standards_storage.StandardAggregationCandidateBinding, ...]:
    old = scenario.aggregation
    old_scoreform_sources = {
        source_reference(
            old.workspace.projected["scoreform"],
            old.scoreform_first_correctness,
        ),
        source_reference(
            old.workspace.projected["scoreform"],
            old.scoreform_second_ambiguous,
        ),
    }
    old_scoreform_bindings = tuple(
        binding
        for binding in old.bindings
        if binding.source in old_scoreform_sources
    )
    if len(old_scoreform_bindings) != 2:
        raise AssertionError("Expected two original ScoreForm aggregation bindings.")

    profile_by_item_id = {
        binding.source.item_id: binding.mapping_profile
        for binding in old_scoreform_bindings
    }
    first_profile = profile_by_item_id[old.scoreform_first_correctness.item_id]
    second_profile = profile_by_item_id[old.scoreform_second_ambiguous.item_id]
    if first_profile is None or second_profile is None:
        raise AssertionError("ScoreForm correction requires explicit mappings.")

    corrected = (
        standards_storage.StandardAggregationCandidateBinding(
            source_reference(projection, first),
            authorized,
            first_profile,
        ),
        standards_storage.StandardAggregationCandidateBinding(
            source_reference(projection, second),
            authorized,
            second_profile,
        ),
    )
    unchanged = tuple(
        binding
        for binding in old.bindings
        if binding.source.work.module_id != "scoreform"
    )
    return corrected + unchanged


def prepare_corrected_scoreform(
    scenario: Issue44PeriodScenario,
) -> CorrectedScoreFormScenario:
    """Project and interpret the exact Core ScoreForm successor from scratch."""
    successor, projection, authorized = _successor_projection(scenario)
    first, second = _scoreform_items(projection)
    _persist_successor_eligibility(scenario, projection, authorized)
    selection = _refresh_attempt_selection(scenario, authorized)
    reassessment = _refresh_reassessment(
        scenario,
        selection,
        authorized,
    )
    if reassessment.status != "resolved":
        raise AssertionError("Corrected ScoreForm reassessment must be operative.")
    _persist_successor_associations(
        scenario,
        projection,
        authorized,
        (first, second),
    )
    bindings = _replacement_bindings(
        scenario,
        projection,
        authorized,
        first,
        second,
    )
    return CorrectedScoreFormScenario(
        successor=successor,
        projection=projection,
        authorized=authorized,
        first_correctness=first,
        second_ambiguous=second,
        bindings=bindings,
    )
