from __future__ import annotations

from dataclasses import replace

import pytest

from meridian.adapters import (
    AdapterNotFoundError,
    ProducerReaderVersionUnsupportedError,
)
from meridian.evidence import NativePointValue, NativeScaledValue, NativeStateValue
from tests.cross_producer_test_support import (
    SHARED_STANDARD_ID,
    SHARED_STUDENT_ID,
    cross_producer_registry,
    cross_producer_requests,
    exact_reader_version,
)


def _reference_codes(item: object, kind: str) -> tuple[str, ...]:
    provenance = getattr(item, "provenance")
    return tuple(
        reference.identifier
        for reference in provenance.native.references
        if reference.kind == kind and reference.identifier is not None
    )


def test_three_exact_adapters_project_deterministically_without_selection() -> None:
    requests = cross_producer_requests()
    registry = cross_producer_registry()
    expected_adapters = (
        "scoreform.academic_result",
        "quillan.academic_result",
        "concord.academic_result",
    )

    all_item_ids: list[str] = []
    for request, expected_adapter in zip(
        requests.ordered,
        expected_adapters,
        strict=True,
    ):
        match = registry.select(request.publication, request.registration)
        assert match.descriptor.adapter_id == expected_adapter

        first = registry.invoke(request, exact_reader_version)
        second = registry.invoke(request, exact_reader_version)
        assert first == second
        assert first.items
        assert all(item.eligibility.status == "unevaluated" for item in first.items)
        all_item_ids.extend(item.item_id for item in first.items)

    assert len(all_item_ids) == len(set(all_item_ids))


def test_same_standard_id_preserves_three_different_native_semantics() -> None:
    requests = cross_producer_requests()
    registry = cross_producer_registry()

    scoreform = registry.invoke(requests.scoreform, exact_reader_version)
    quillan = registry.invoke(requests.quillan, exact_reader_version)
    concord = registry.invoke(requests.concord, exact_reader_version)

    scoreform_standard_items = [
        item
        for item in scoreform.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and SHARED_STANDARD_ID in item.target.standard_ids
    ]
    assert scoreform_standard_items
    assert {item.result_kind for item in scoreform_standard_items} <= {
        "selected_response",
        "selected_response_state",
        "question_correctness",
    }
    assert not any(
        item.result_kind in {"standard_observation_rating", "overall_standard_rating"}
        for item in scoreform_standard_items
    )

    quillan_observation = next(
        item
        for item in quillan.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "standard_observation_rating"
        and SHARED_STANDARD_ID in item.target.standard_ids
        and isinstance(item.value, NativeScaledValue)
    )
    quillan_overall = next(
        item
        for item in quillan.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "overall_standard_rating"
        and SHARED_STANDARD_ID in item.target.standard_ids
    )

    concord_standard = next(
        item
        for item in concord.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "standard_backed_score"
        and SHARED_STANDARD_ID in item.target.standard_ids
    )

    assert quillan_observation.result_kind != quillan_overall.result_kind
    assert concord_standard.result_kind == "standard_backed_score"
    assert scoreform_standard_items[0].result_kind != concord_standard.result_kind


def test_equal_looking_two_stays_points_or_its_exact_native_scale() -> None:
    requests = cross_producer_requests()
    registry = cross_producer_registry()

    scoreform = registry.invoke(requests.scoreform, exact_reader_version)
    quillan = registry.invoke(requests.quillan, exact_reader_version)
    concord = registry.invoke(requests.concord, exact_reader_version)

    scoreform_points = next(
        item.value
        for item in scoreform.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "attempt_points"
        and isinstance(item.value, NativePointValue)
        and item.value.earned == 2
    )
    quillan_rating = next(
        item.value
        for item in quillan.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "overall_standard_rating"
        and isinstance(item.value, NativeScaledValue)
    )
    concord_rating = next(
        item.value
        for item in concord.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "standard_backed_score"
        and isinstance(item.value, NativeScaledValue)
    )

    assert scoreform_points.earned == 2
    assert scoreform_points.possible == 3
    assert quillan_rating.value == 2
    assert concord_rating.value == 2

    assert quillan_rating.scale.scale_id == "synthetic_0_2_4"
    assert concord_rating.scale.scale_id == "scale_2"
    assert quillan_rating.scale != concord_rating.scale
    assert quillan_rating.scale.lineage_id is None
    assert concord_rating.scale.lineage_id == "scale_lineage_1"
    assert concord_rating.scale.revision == 2
    assert [level.position for level in concord_rating.scale.levels] == [1, 3, 7]


def test_attempts_history_zero_and_non_score_states_stay_distinct() -> None:
    requests = cross_producer_requests()
    registry = cross_producer_registry()

    scoreform = registry.invoke(requests.scoreform, exact_reader_version)
    quillan = registry.invoke(requests.quillan, exact_reader_version)
    concord = registry.invoke(requests.concord, exact_reader_version)

    attempt_points = [
        item
        for item in scoreform.items
        if item.subject is not None
        and item.subject.student_id == SHARED_STUDENT_ID
        and item.result_kind == "attempt_points"
    ]
    assert [item.target.target_id for item in attempt_points] == [
        "attempt_1",
        "attempt_2",
    ]

    group_scores = [
        item
        for item in concord.items
        if item.subject is None and item.result_kind == "local_score"
    ]
    assert len(group_scores) == 2
    predecessor, current = group_scores
    assert isinstance(predecessor.value, NativeScaledValue)
    assert predecessor.value.value == 0
    assert _reference_codes(predecessor, "score_current_state") == ("superseded",)
    assert _reference_codes(current, "score_current_state") == ("current",)
    assert _reference_codes(current, "score_supersedes") == ("score_001",)

    scoreform_states = {
        item.value.code
        for item in scoreform.items
        if isinstance(item.value, NativeStateValue)
    }
    quillan_states = {
        item.value.code
        for item in quillan.items
        if isinstance(item.value, NativeStateValue)
    }
    concord_states = {
        item.value.code
        for item in concord.items
        if isinstance(item.value, NativeStateValue)
    }

    assert {"blank", "ambiguous"} <= scoreform_states
    assert "unrated" in quillan_states
    assert "returned_without_full_review" in quillan_states
    assert "absent" in concord_states
    assert all(item.eligibility.status == "unevaluated" for item in group_scores)


def test_unsupported_reader_version_is_local_to_selected_producer() -> None:
    requests = cross_producer_requests()
    registry = cross_producer_registry()

    versions = {
        "scoreform": "0.10.0",
        "quillan": "0.9.1",
        "pds-concord": "0.2.0",
    }

    with pytest.raises(ProducerReaderVersionUnsupportedError) as caught:
        registry.invoke(requests.quillan, versions.__getitem__)

    assert caught.value.adapter_id == "quillan.academic_result"
    assert caught.value.distribution_name == "quillan"
    assert caught.value.installed_version == "0.9.1"

    assert registry.invoke(requests.scoreform, versions.__getitem__).items
    assert registry.invoke(requests.concord, versions.__getitem__).items


def test_unsupported_contract_does_not_fall_through_to_another_adapter() -> None:
    requests = cross_producer_requests()
    registry = cross_producer_registry()
    future = replace(
        requests.quillan.publication,
        manifest_contract_version="quillan_academic_result_manifest_v2",
    )

    with pytest.raises(AdapterNotFoundError) as caught:
        registry.select(future, requests.quillan.registration)

    assert caught.value.key.producer_module_id == "quillan"
    assert caught.value.key.manifest_contract_version == (
        "quillan_academic_result_manifest_v2"
    )
