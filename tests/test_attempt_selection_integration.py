from __future__ import annotations

from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.attempt_selection_storage as storage
import meridian.projection_cache as projection_cache

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")
PUBLICATION_ID = "pub_" + "1" * 32
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64


class FakeAuthorizedSnapshot:
    def __init__(self, stored: object) -> None:
        self.stored = stored


def native_reference(number: int) -> SimpleNamespace:
    return SimpleNamespace(kind="attempt", identifier=None, sequence=number)


def item(
    item_id: str,
    number: int,
    *,
    child: bool = False,
    student_id: str = "student_1",
) -> SimpleNamespace:
    attempt_parent = SimpleNamespace(
        target_kind="attempt",
        target_id=f"attempt_{number}",
        owning_system=None,
        contract_version=None,
    )
    target = (
        SimpleNamespace(
            target_kind="question",
            target_id="question_1",
            parent_target=attempt_parent,
            owning_system=None,
            contract_version=None,
        )
        if child
        else SimpleNamespace(
            target_kind="attempt",
            target_id=f"attempt_{number}",
            parent_target=None,
            owning_system=None,
            contract_version=None,
        )
    )
    return SimpleNamespace(
        item_id=item_id,
        subject=SimpleNamespace(student_id=student_id),
        target=target,
        provenance=SimpleNamespace(
            native=SimpleNamespace(references=(native_reference(number),))
        ),
    )


def authorized(
    monkeypatch: pytest.MonkeyPatch,
    *,
    capabilities: tuple[str, ...] = (
        "points", "question_evidence", "multiple_attempts"
    ),
    items: tuple[SimpleNamespace, ...] = (),
) -> FakeAuthorizedSnapshot:
    monkeypatch.setattr(
        projection_cache,
        "AuthorizedProjectionSnapshot",
        FakeAuthorizedSnapshot,
    )
    publication = SimpleNamespace(
        work=WORK,
        publication_id=PUBLICATION_ID,
        capabilities=capabilities,
    )
    snapshot = SimpleNamespace(
        source=SimpleNamespace(publication=publication),
        inventory=SimpleNamespace(items=items),
    )
    return FakeAuthorizedSnapshot(
        SimpleNamespace(
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
            snapshot=snapshot,
        )
    )


def eligibility(
    *,
    operative: bool,
    status: str = "included",
    revision: int = 1,
) -> SimpleNamespace:
    selected = (
        SimpleNamespace(
            decision=SimpleNamespace(eligibility_revision=revision),
            decision_sha256="4" * 64,
        )
        if operative
        else None
    )
    return SimpleNamespace(
        operative_included=operative,
        status=status,
        selected=selected,
    )


def test_scoreform_like_attempt_and_child_evidence_group_without_ranking(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    values = (
        item("scoreform_attempt_2", 2),
        item("scoreform_question_2", 2, child=True),
        item("scoreform_attempt_1", 1),
    )
    snapshot = authorized(monkeypatch, items=values)
    monkeypatch.setattr(
        storage,
        "resolve_current_evidence_eligibility",
        lambda *args, **kwargs: eligibility(operative=True),
    )
    result = storage.derive_attempt_candidates(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        GRADE_ITEM_ID,
        "student_1",
        snapshot,  # type: ignore[arg-type]
    )
    assert result.status == "applicable"
    assert tuple(value.attempt.native.sequence for value in result.candidates) == (1, 2)
    assert len(result.candidates[0].eligible_evidence) == 1
    assert len(result.candidates[1].eligible_evidence) == 2
    assert not hasattr(result, "selected_attempts")


def test_candidate_derivation_uses_only_operative_included_eligibility(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    values = (item("included_item", 1), item("excluded_item", 2))
    snapshot = authorized(monkeypatch, items=values)

    def resolve(*args: object, **kwargs: object) -> SimpleNamespace:
        source = args[3]
        return eligibility(operative=getattr(source, "item_id") == "included_item")

    monkeypatch.setattr(storage, "resolve_current_evidence_eligibility", resolve)
    result = storage.derive_attempt_candidates(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        GRADE_ITEM_ID,
        "student_1",
        snapshot,  # type: ignore[arg-type]
    )
    assert tuple(value.attempt.native.sequence for value in result.candidates) == (1,)


def test_explicitly_included_superseded_source_remains_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    snapshot = authorized(monkeypatch, items=(item("historical_item", 1),))
    monkeypatch.setattr(
        storage,
        "resolve_current_evidence_eligibility",
        lambda *args, **kwargs: eligibility(
            operative=True, status="included_source_superseded"
        ),
    )
    result = storage.derive_attempt_candidates(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        GRADE_ITEM_ID,
        "student_1",
        snapshot,  # type: ignore[arg-type]
    )
    assert len(result.candidates) == 1


def test_withdrawn_or_pending_evidence_does_not_become_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    snapshot = authorized(monkeypatch, items=(item("blocked_item", 1),))
    for status in (
        "included_source_withdrawn",
        "pending",
        "unsupported",
        "no_decision",
    ):
        monkeypatch.setattr(
            storage,
            "resolve_current_evidence_eligibility",
            lambda *args, status=status, **kwargs: eligibility(
                operative=False, status=status
            ),
        )
        result = storage.derive_attempt_candidates(
            tmp_path,  # type: ignore[arg-type]
            CLASS_ID,
            GRADE_ITEM_ID,
            "student_1",
            snapshot,  # type: ignore[arg-type]
        )
        assert result.status == "applicable"
        assert result.candidates == ()


def test_quillan_and_concord_shapes_are_not_wrapped_in_fake_attempts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    malformed = SimpleNamespace(
        item_id="native_item",
        subject=SimpleNamespace(student_id="student_1"),
        target=SimpleNamespace(target_kind="review_unit", parent_target=None),
    )
    for capabilities in (
        ("standards_ratings",),
        ("criterion_scores", "moderated_scores"),
    ):
        snapshot = authorized(
            monkeypatch, capabilities=capabilities, items=(malformed,)
        )
        result = storage.derive_attempt_candidates(
            tmp_path,  # type: ignore[arg-type]
            CLASS_ID,
            GRADE_ITEM_ID,
            "student_1",
            snapshot,  # type: ignore[arg-type]
        )
        assert result.status == "not_applicable"
        assert result.candidates == ()


def test_multiple_attempt_capability_with_eligible_unsafe_shape_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    malformed = item("unsafe_item", 1)
    malformed.target = SimpleNamespace(
        target_kind="submission",
        target_id="submission_1",
        parent_target=None,
        owning_system=None,
        contract_version=None,
    )
    snapshot = authorized(monkeypatch, items=(malformed,))
    monkeypatch.setattr(
        storage,
        "resolve_current_evidence_eligibility",
        lambda *args, **kwargs: eligibility(operative=True),
    )
    result = storage.derive_attempt_candidates(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        GRADE_ITEM_ID,
        "student_1",
        snapshot,  # type: ignore[arg-type]
    )
    assert result.status == "unsupported_attempt_shape"
    assert result.candidates == ()


def test_numeric_value_and_recorded_time_are_never_needed_for_candidate_derivation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: object,
) -> None:
    # These synthetic items deliberately expose no `value`, score, or recorded_at.
    # Candidate derivation succeeds because attempt identity and #29 eligibility,
    # not educational magnitude or recency, are the only #30 inputs.
    snapshot = authorized(
        monkeypatch,
        items=(item("low_old_attempt", 1), item("high_new_attempt", 2)),
    )
    monkeypatch.setattr(
        storage,
        "resolve_current_evidence_eligibility",
        lambda *args, **kwargs: eligibility(operative=True),
    )
    result = storage.derive_attempt_candidates(
        tmp_path,  # type: ignore[arg-type]
        CLASS_ID,
        GRADE_ITEM_ID,
        "student_1",
        snapshot,  # type: ignore[arg-type]
    )
    assert tuple(value.attempt.native.sequence for value in result.candidates) == (1, 2)
