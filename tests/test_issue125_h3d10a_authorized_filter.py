"""#125-H3D10A: display-label-only search/filter for bounded safe evidence.

No source identifiers or authorization expansion are permitted by filtering.
The usual exact review and APPLY boundary remain unchanged.
"""

from __future__ import annotations

from io import StringIO
from typing import cast

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu
from test_issue125_slicef1_assessment_menu import inputs, review, ui

import meridian.menu_teacher_assessment_eligibility as menu


def test_filter_matches_student_display_only_within_safe_scope() -> None:
    data = review(3, 2)
    data.students[0].items[0].candidate_for_explicit_review = False
    data.students[1].within_requested_authorization = False
    chosen = menu._choose_source_ids(
        cast(object, data),
        input_fn=inputs("F", "sample STUDENT 1", "1", "D"),
        **ui(),
    )
    assert chosen == ("s1-q2",)


def test_filter_matches_evidence_label_across_students() -> None:
    chosen = menu._choose_source_ids(
        cast(object, review(2, 3)),
        input_fn=inputs("F", "question 2", "1,2", "D"),
        **ui(),
    )
    assert chosen == ("s1-q2", "s2-q2")


def test_filter_unicode_label_casefold() -> None:
    data = review(2, 2)
    data.students[0].display_label = "Zoë Sample"
    assert menu._filter_safe_candidates(
        menu._enumerate_candidates(cast(object, data)), "ZOË"
    ) == (("s1-q1", "Zoë Sample", "Question 1"), ("s1-q2", "Zoë Sample", "Question 2"))


def test_filter_does_not_search_private_source_id() -> None:
    data = review(1, 1)
    data.students[0].items[0].source.item_id = "PRIVATE_CANONICAL_ID"
    output = StringIO()
    chosen = menu._choose_source_ids(
        cast(object, data),
        input_fn=inputs("F", "PRIVATE_CANONICAL_ID", "", "B"),
        output=output,
        clear_fn=lambda: None,
    )
    assert chosen is None
    assert "PRIVATE_CANONICAL_ID" not in output.getvalue()
    assert "No safe, authorized evidence matches" in output.getvalue()


def test_filter_no_match_never_selects_all() -> None:
    output = StringIO()
    selected = menu._choose_source_ids(
        cast(object, review(29, 6)),
        input_fn=inputs("F", "unavailable subject", "", "B"),
        output=output,
        clear_fn=lambda: None,
    )
    assert selected is None
    assert "No item was selected or changed" in output.getvalue()


def test_filter_blank_and_back_return_to_scope_without_selection() -> None:
    data = cast(object, review(1, 1))
    assert menu._choose_source_ids(data, input_fn=inputs("F", "", "B"), **ui()) is None
    assert menu._choose_source_ids(data, input_fn=inputs("F", "B", "B"), **ui()) is None


def test_filter_paged_back_never_authorizes_selection() -> None:
    selected = menu._choose_source_ids(
        cast(object, review(29, 6)),
        input_fn=inputs("F", "Question 1", "B", "B"),
        **ui(),
    )
    assert selected is None


@pytest.mark.parametrize(
    ("navigation", "error"),
    (("M", ReturnToMainMenu), ("Q", QuitPDS)),
)
def test_core_navigation_during_filter_propagates(
    navigation: str, error: type[Exception]
) -> None:
    with pytest.raises(error):
        menu._choose_source_ids(
            cast(object, review(1, 1)),
            input_fn=inputs("F", navigation),
            **ui(),
        )


def test_filter_rejects_control_and_unbounded_search_terms() -> None:
    candidates = menu._enumerate_candidates(cast(object, review(1, 1)))
    assert not menu._filter_safe_candidates(candidates, " " * 3)
    assert not menu._filter_safe_candidates(candidates, "A" * 81)
    assert not menu._filter_safe_candidates(candidates, "Question\x01")


def test_filter_can_select_one_exact_item_from_174() -> None:
    data = cast(object, review(29, 6))
    selected = menu._choose_source_ids(
        data,
        input_fn=inputs("F", "Sample Student 29", "6", "D"),
        **ui(),
    )
    assert selected == ("s29-q6",)
