from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import meridian.academic_period_result_selection_workflow as period_selection
import meridian.attempt_selection_storage as attempt_storage
import meridian.calculation_result_selection_workflow as result_selection
import meridian.ingestion as ingestion
import meridian.reassessment_storage as reassessment_storage
from meridian.attempt_selection import (
    AttemptSelectionPolicyReference,
    AttemptSelectionValidationError,
)
from meridian.conventional_grade import resolve_conventional_grade_item_input
from meridian.evidence import NativePointValue
from meridian.reassessment import (
    ReassessmentValidationError,
    ReplacementRelationship,
)
from tests import test_academic_period_result_selection_workflow as period_tests
from tests import test_attempt_selection as attempt_tests
from tests import test_attempt_selection_storage as attempt_storage_tests
from tests import test_calculation_result_selection_workflow as result_tests
from tests import test_conventional_grade as conventional
from tests import test_ingestion as ingestion_tests
from tests import test_reassessment_storage as reassessment_tests


@pytest.mark.parametrize("implicit_basis", ("latest", "highest", "newest"))
def test_issue61_attempt_and_reassessment_authority_is_explicit_only(
    implicit_basis: str,
) -> None:
    assert attempt_tests.policy().selection_basis == "explicit"
    with pytest.raises(AttemptSelectionValidationError, match="explicit"):
        replace(
            attempt_tests.policy(),
            selection_basis=implicit_basis,  # type: ignore[arg-type]
        )

    assert reassessment_tests.policy().relationship_basis == "explicit"
    with pytest.raises(ReassessmentValidationError, match="explicit"):
        replace(
            reassessment_tests.policy(),
            relationship_basis=implicit_basis,  # type: ignore[arg-type]
        )


def test_issue61_multiple_point_observations_do_not_self_rank() -> None:
    participation = conventional.total_item("issue61_multi_attempt", "10")
    resolved = resolve_conventional_grade_item_input(
        participation=participation,
        student_id=conventional.STUDENT_ID,
        target_period=conventional.PERIOD,
        calendar_revision=1,
        point_observations=(
            NativePointValue(9, 10),
            NativePointValue(10, 10),
        ),
        no_point_state="missing",
    )

    assert resolved.status == "unresolved"
    assert resolved.earned is None
    assert resolved.possible is None
    assert resolved.reason_codes == ("multiple_point_observations",)


def test_issue61_explicit_attempt_decision_can_select_older_sequence() -> None:
    values = (attempt_tests.candidate(1), attempt_tests.candidate(2))
    value = attempt_tests.decision(
        candidates=values,
        selected=(values[0].attempt,),
    )

    assert tuple(
        candidate.attempt.native.sequence for candidate in value.candidates
    ) == (1, 2)
    assert tuple(
        selected.native.sequence for selected in value.selected_attempts
    ) == (1,)


def test_issue61_publication_successor_makes_old_attempt_basis_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    policy = attempt_storage_tests.policy()
    policy_ref = AttemptSelectionPolicyReference(
        policy.policy_id,
        policy.policy_revision,
        "5" * 64,
    )
    decision = attempt_storage_tests.decision(policy_ref)
    selected = SimpleNamespace(
        decision=decision,
        decision_sha256="8" * 64,
    )
    successor_snapshot = replace(
        attempt_storage_tests.projection(),
        publication_id="pub_" + "9" * 32,
    )
    derivation = attempt_storage.AttemptCandidateDerivation(
        status="applicable",
        source_snapshot=successor_snapshot,
        student_id="student_1",
        candidates=attempt_storage_tests.candidates(),
    )

    monkeypatch.setattr(
        attempt_storage,
        "load_current_attempt_selection_decision",
        lambda *args: selected,
    )
    monkeypatch.setattr(
        attempt_storage,
        "derive_attempt_candidates",
        lambda *args, **kwargs: derivation,
    )

    result = attempt_storage.resolve_current_attempt_selection(
        attempt_storage_tests.root(tmp_path),
        attempt_storage_tests.CLASS_ID,
        attempt_storage_tests.GRADE_ITEM_ID,
        attempt_storage_tests.WORK,
        "student_1",
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )

    assert result.status == "candidate_set_stale"
    assert result.selected is selected
    assert result.operative_selection is False


def test_issue61_publication_lifecycle_stays_publication_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = ingestion_tests.publication()
    second = ingestion_tests.publication(
        publication_id="pub_" + "2" * 32,
        revision=2,
        predecessor=first.publication_id,
    )
    ingestion_tests.patch_context(
        monkeypatch,
        pub=first,
        records=(first, second),
    )
    historical = ingestion.load_canonical_publication_context(
        "workspace",
        first.publication_id,
    )

    assert historical.canonical_state == "historical"
    assert historical.series.successor_publication_id == second.publication_id
    assert historical.withdrawal is None

    withdrawn = ingestion_tests.withdrawal(second)
    ingestion_tests.patch_context(
        monkeypatch,
        pub=second,
        records=(first, second),
        withdrawals={second.publication_id: withdrawn},
    )
    withdrawn_head = ingestion.load_canonical_publication_context(
        "workspace",
        second.publication_id,
    )

    assert withdrawn_head.canonical_state == "withdrawn_head"
    assert withdrawn_head.withdrawal == withdrawn
    assert withdrawn_head.series.successor_publication_id is None


def test_issue61_multiple_selected_attempts_require_reassessment_decision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    workspace = reassessment_tests.root(tmp_path)
    source = reassessment_tests.upstream()

    monkeypatch.setattr(
        reassessment_storage,
        "load_current_reassessment_decision",
        lambda *args: None,
    )
    monkeypatch.setattr(
        reassessment_storage,
        "resolve_current_attempt_selection",
        lambda *args, **kwargs: source,
    )

    result = reassessment_storage.resolve_current_reassessment(
        workspace,
        reassessment_tests.CLASS_ID,
        reassessment_tests.GRADE_ITEM_ID,
        reassessment_tests.WORK,
        "student_1",
        authorized_snapshot=object(),  # type: ignore[arg-type]
    )

    assert result.status == "no_decision"
    assert result.contributing_attempts == ()
    assert result.operative_reassessment is False


def test_issue61_explicit_replacement_can_prefer_lower_sequence() -> None:
    first = reassessment_tests.attempt(1)
    second = reassessment_tests.attempt(2)
    reverse = replace(
        reassessment_tests.decision(),
        contributing_attempts=(first,),
        replacement_relationships=(
            ReplacementRelationship(first, (second,)),
        ),
    )

    reassessment_storage._validate_relationships_against_selected(
        reverse,
        (first, second),
    )

    assert reverse.contributing_attempts == (first,)
    assert reverse.replacement_relationships[0].replacement_attempt == first
    assert reverse.replacement_relationships[0].replaced_attempts == (second,)


def test_issue61_grade_item_result_selection_targets_exact_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = result_tests.stored(1)
    result_tests.install_state(
        monkeypatch,
        history=(1, 2, 3),
        current=3,
        target=target,
    )

    preview = result_selection.preview_calculation_result_selection(
        "workspace",
        result_tests.CLASS_ID,
        result_tests.GRADE_ITEM_ID,
        result_tests.STUDENT_ID,
        result_tests.STANDARD_ID,
        1,
    )

    assert preview.target is target
    assert preview.target_revision == 1
    assert preview.expected_current_result_revision == 3
    assert preview.target_is_latest is False
    assert preview.authoring_action == "not_performed"


def test_issue61_period_result_selection_targets_exact_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    period_tests.install_types(monkeypatch)
    target = period_tests.stored(1)
    monkeypatch.setattr(
        period_selection,
        "list_academic_period_proficiency_result_revisions",
        lambda *args, **kwargs: (1, 2, 3),
    )
    monkeypatch.setattr(
        period_selection,
        "load_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: target,
    )
    monkeypatch.setattr(
        period_selection,
        "get_current_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: 3,
    )

    preview = period_selection.preview_academic_period_result_selection(
        "workspace",
        period_tests.CLASS_ID,
        period_tests.SCHOOL_YEAR,
        period_tests.PERIOD_ID,
        period_tests.STUDENT_ID,
        period_tests.STANDARD_ID,
        1,
    )

    assert preview.target is target
    assert preview.target_revision == 1
    assert preview.expected_current_result_revision == 3
    assert preview.target_is_latest is False
    assert preview.authoring_action == "not_performed"
