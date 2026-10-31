"""Issue #123 Slice 2: read-only common choice model and terminal contract."""

from __future__ import annotations

from io import StringIO
from types import MappingProxyType
from typing import Mapping

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

from meridian.report_guided_selection import ReportOption
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceUnavailable,
    choices_from_report_options,
    load_teacher_choices,
    page_teacher_choices,
    search_teacher_choices,
)
from meridian.teacher_navigation_terminal import select_teacher_choice


class Catalog:
    def __init__(self, *snapshots: tuple[TeacherChoice, ...]) -> None:
        self.snapshots = snapshots
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.writes = 0

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        assert isinstance(selected, MappingProxyType)
        self.calls.append((scope, dict(selected)))
        return self.snapshots[min(len(self.calls) - 1, len(self.snapshots) - 1)]


def item(
    identity: str,
    label: str,
    *,
    detail: str | None = None,
    witness: str | None = "rev-1",
) -> TeacherChoice:
    return TeacherChoice(
        identity=(identity,), label=label, detail=detail, witness=witness
    )


def session(
    catalog: Catalog,
    *answers: str,
    page_size: int = 10,
    selected: Mapping[str, str] | None = None,
) -> tuple[TeacherChoice | None, str, list[str]]:
    stream = StringIO()
    typed = iter(answers)
    prompts: list[str] = []

    def input_fn(prompt: str) -> str:
        prompts.append(prompt)
        return next(typed)

    result = select_teacher_choice(
        catalog=catalog,
        scope="student",
        title="Choose student",
        question="Which student?",
        input_fn=input_fn,
        output=stream,
        clear_fn=lambda: None,
        page_size=page_size,
        selected=selected,
    )
    return result, stream.getvalue(), prompts


def test_identity_is_opaque_and_witness_never_in_normal_labels() -> None:
    candidate = item("private-student-id", "Alicia", witness="sha256-marker")
    assert candidate.display == "Alicia"
    picked, display, _ = session(Catalog((candidate,)), "1")
    assert picked == candidate
    assert "private-student-id" not in display
    assert "sha256-marker" not in display


def test_only_available_choice_requires_explicit_selection() -> None:
    picked, _, _ = session(Catalog((item("A", "Sasha"),)), "B")
    assert picked is None


@pytest.mark.parametrize("identity", [(), ("",), ("a\nwrong",), "string"])
def test_unacceptable_identity_rejected(identity: object) -> None:
    with pytest.raises(ValueError):
        TeacherChoice(identity=identity, label="Good")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "label", ["\x1b[31mRED", "A\nB", "A\u202eB", "A\u200bB", " hi "]
)
def test_terminal_control_and_invisible_labels_rejected(label: str) -> None:
    with pytest.raises(ValueError):
        item("safe-id", label)


def test_legitimate_unicode_and_pathlike_name_stays_display_only() -> None:
    candidate = item("core-id", "Renée/../\u00c9lodie", detail="Marking Period 1")
    options = load_teacher_choices(Catalog((candidate,)), scope="student")
    assert options == (candidate,)
    assert search_teacher_choices(options, "rENÉE/") == options


def test_unicode_casefold_compatibility_search() -> None:
    options = (item("a", "Straße"), item("b", "ＡＬＩＣＥ"))
    assert search_teacher_choices(options, "STRASSE") == (options[0],)
    assert search_teacher_choices(options, "alice") == (options[1],)


def test_duplicate_names_require_meaningful_disambiguation() -> None:
    catalog = Catalog((item("id-a", "Alex"), item("id-b", "Alex")))
    with pytest.raises(TeacherChoiceUnavailable, match="indistinguishable"):
        load_teacher_choices(catalog, scope="student")
    selected, rendered, _ = session(catalog)
    assert selected is None
    assert "No record was selected" in rendered


def test_duplicate_unicode_equivalent_display_blocks() -> None:
    catalog = Catalog((item("a", "Café"), item("b", "Cafe\u0301")))
    with pytest.raises(TeacherChoiceUnavailable):
        load_teacher_choices(catalog, scope="student")


def test_details_disambiguate_without_surrogate_identity() -> None:
    a, b = item("s1", "Alex", detail="Room 101"), item("s2", "Alex", detail="Room 102")
    selected, display, _ = session(Catalog((b, a)), "2")
    assert selected == b
    assert "Room 101" in display and "Room 102" in display


def test_duplicate_identity_fails_even_if_display_differs() -> None:
    with pytest.raises(TeacherChoiceUnavailable, match="exact identity"):
        load_teacher_choices(
            Catalog((item("same", "One"), item("same", "Two"))), scope="student"
        )


def test_pagination_uses_visible_row_numbers_and_stable_order() -> None:
    records = tuple(item(f"id{i:02d}", f"Student {i:02d}") for i in range(13, 0, -1))
    selected, display, _ = session(Catalog(records), "N", "1", page_size=5)
    assert selected is not None and selected.identity == ("id06",)
    assert "Page 2/3" in display
    assert "id06" not in display


def test_previous_page_never_selects_hidden_row() -> None:
    records = tuple(item(str(i), f"Student {i:02d}") for i in range(7))
    selected, _, _ = session(Catalog(records), "N", "P", "1", page_size=3)
    assert selected is not None and selected.identity == ("0",)


def test_search_stays_within_visible_metadata() -> None:
    records = (item("secret-match", "Alice"), item("id2", "Bob"))
    selected, display, _ = session(Catalog(records), "S", "secret", "B")
    assert selected is None
    assert "No matching current choices" in display
    assert "secret-match" not in display


def test_search_can_clear_and_select() -> None:
    records = (item("one", "Alice"), item("two", "Bob"))
    selected, _, _ = session(Catalog(records), "S", "bob", "C", "2")
    assert selected is not None and selected.identity == ("two",)


def test_search_back_cancels_search_not_whole_task() -> None:
    selected, _, _ = session(Catalog((item("x", "Alice"),)), "S", "B", "1")
    assert selected is not None and selected.identity == ("x",)


def test_invalid_search_is_rejected_without_leaking_details() -> None:
    selected, display, _ = session(Catalog((item("x", "Alice"),)), "S", "\u202e", "B")
    assert selected is None
    assert "not supported" in display


def test_advanced_details_are_explicit_and_single_row_only() -> None:
    records = (
        item("secret-one", "Alice", witness="digest-one"),
        item("secret-two", "Bob", witness="digest-two"),
    )
    selected, display, _ = session(Catalog(records), "T", "1", "", "B")
    assert selected is None
    assert "secret-one" in display and "digest-one" in display
    assert "secret-two" not in display and "digest-two" not in display


def test_selection_stale_witness_requires_teacher_to_rechoose() -> None:
    old = item("a", "Alice", witness="rev-1")
    current = item("a", "Alice", witness="rev-2")
    selected, display, _ = session(Catalog((old,), (current,)), "1", "B")
    assert selected is None
    assert "Stale choice" in display


def test_selection_stale_label_cannot_silently_retarget() -> None:
    old = item("a", "Alice")
    changed = item("a", "Alice (renamed)")
    selected, display, _ = session(Catalog((old,), (changed,)), "1", "B")
    assert selected is None
    assert "Stale choice" in display


def test_changed_identity_with_matching_label_not_auto_selected() -> None:
    selected, display, _ = session(
        Catalog((item("before", "Alice"),), (item("after", "Alice"),)), "1", "B"
    )
    assert selected is None
    assert "Stale choice" in display


def test_reselection_after_stale_refresh_requires_new_number() -> None:
    selected, display, _ = session(
        Catalog((item("old", "Alice"),), (item("new", "Alice"),)), "1", "1"
    )
    assert selected is not None and selected.identity == ("new",)
    assert "Stale choice" in display


def test_refresh_is_opt_in_and_reenumerates() -> None:
    c = Catalog((item("a", "Alice"),), (item("b", "Bob"),))
    selected, display, _ = session(c, "R", "1")
    assert selected is not None and selected.identity == ("b",)
    assert len(c.calls) == 3
    assert "Bob" in display


def test_empty_choices_have_exit_and_refresh() -> None:
    selected, display, _ = session(Catalog(()), "B")
    assert selected is None
    assert "No matching current choices" in display


def test_unknown_and_oversized_catalogs_fail_closed() -> None:
    for catalog in (Catalog(tuple(item(str(i), str(i)) for i in range(501))),):
        selected, display, _ = session(catalog)
        assert selected is None and "could not be verified" in display


def test_catalog_errors_are_sanitized() -> None:
    class Fails:
        def options(
            self, *, scope: str, selected: Mapping[str, str]
        ) -> tuple[TeacherChoice, ...]:
            raise RuntimeError("PRIVATE-ERROR-TEXT")

    stream = StringIO()
    result = select_teacher_choice(
        catalog=Fails(),
        scope="student",
        title="Students",
        question="Who?",
        input_fn=lambda _: "B",
        output=stream,
        clear_fn=lambda: None,
    )
    assert result is None
    assert "PRIVATE-ERROR-TEXT" not in stream.getvalue()


def test_main_and_quit_propagate_core_navigation() -> None:
    c = Catalog((item("x", "Alice"),))
    with pytest.raises(ReturnToMainMenu):
        session(c, "M")
    with pytest.raises(QuitPDS):
        session(c, "Q")


def test_explicit_context_is_read_only_and_passed_to_catalog() -> None:
    c = Catalog((item("a", "Alice"),))
    result, _, _ = session(c, "1", selected={"class": "english_12_pd2"})
    assert result is not None
    assert c.calls == [
        ("student", {"class": "english_12_pd2"}),
        ("student", {"class": "english_12_pd2"}),
    ]


def test_report_adapter_preserves_existing_option_identity_and_labels() -> None:
    options = (ReportOption("class-identity", "English 12", "Period 2"),)
    adapted = choices_from_report_options(options)
    assert adapted[0].identity == ("class-identity",)
    assert adapted[0].display == "English 12 — Period 2 — Reports"
    assert options[0].value == "class-identity"  # #111 unchanged


def test_page_size_and_search_bounds() -> None:
    with pytest.raises(ValueError):
        page_teacher_choices((item("x", "Alice"),), page_size=0)
    with pytest.raises(ValueError):
        search_teacher_choices((item("x", "Alice"),), "x" * 121)


def test_no_unauthorized_read_or_write_from_pure_selector() -> None:
    c = Catalog((item("a", "Alice"),))
    selected, _, prompts = session(c, "B")
    assert selected is None and c.writes == 0
    assert len(c.calls) == 1
    assert prompts == ["Choice: "]


def test_huge_decimal_row_does_not_crash_selector() -> None:
    result, rendered, _ = session(Catalog((item("a", "Alice"),)), "1" * 5000, "B")
    assert result is None
    assert "Choose a visible number" in rendered
