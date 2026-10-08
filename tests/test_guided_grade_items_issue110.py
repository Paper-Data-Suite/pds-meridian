from __future__ import annotations

from meridian.guided_grade_items import derive_grade_item_id


def test_grade_item_id_is_derived_internally_and_collision_safe() -> None:
    assert derive_grade_item_id("Unit 1 Writing", ()) == "gi_unit_1_writing"
    assert derive_grade_item_id(
        "Unit 1 Writing",
        ("gi_unit_1_writing",),
    ) == "gi_unit_1_writing_2"


def test_grade_item_id_fallback_handles_non_ascii_titles() -> None:
    value = derive_grade_item_id("日本語", ())
    assert value == "gi_grade_item"
    assert " " not in value
