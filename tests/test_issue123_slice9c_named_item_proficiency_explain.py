"""#123 Slice 9C: explain existing Grade Item proficiency with named choices."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_explain_item_proficiency as named

CLASS = "english_12_pd2"
ITEM = "gradeitem_hidden"
STUDENT = "student_hidden"
STANDARD = "RL.TS.11-12.4"
REV = 5
SHA = "b" * 64


def presentation(**updates):
    payload = dict(
        title="Grade Item Proficiency Explanation",
        lines=(
            "Grade Item: Scene, Summary, and Pacing Check",
            f"Student: {STUDENT}",
            f"Standard: {STANDARD}",
            "Result: calculated",
            "Proficiency: Meeting",
            "Policy: Current Standards Policy",
            "Evidence: 3 performance, 0 native state, 1 excluded",
            "Selection state: selected current",
        ),
        technical_lines=(
            f"class_id: {CLASS}",
            f"grade_item_id: {ITEM}",
            f"result_revision: {REV}",
            f"result_sha256: {SHA}",
            "inputs_sha256: " + "c" * 64,
        ),
    )
    payload.update(updates)
    return SimpleNamespace(**payload)


def setup(tmp_path, monkeypatch, *, answers=("",), changes=None):
    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year="2026-2027")
    navigation = MagicMock()
    navigation.current_class.return_value = scope
    grade_item = SimpleNamespace(
        identity=(ITEM,), label="Scene, Summary, and Pacing Check"
    )
    student = SimpleNamespace(identity=(STUDENT,), label="Morgan Rivera")
    standard = SimpleNamespace(
        identity=(STANDARD,), label="Standard RL.TS.11-12.4", witness=f"{REV}:{SHA}"
    )
    choices = (grade_item, student, standard)
    if changes is not None:
        choices = tuple(
            changes.get(k, v) for k, v in zip(("item", "student", "standard"), choices)
        )
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    monkeypatch.setattr(named, "_grade_item", lambda *_a, **_kw: choices[0])
    selected = iter(choices[1:])
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: next(selected))
    verify = MagicMock()
    monkeypatch.setattr(named, "_current_choice", verify)
    reader = MagicMock(return_value=presentation())
    response = iter(answers)

    def read_input(prompt=""):
        if prompt == "Press Enter to continue...":
            return ""
        return next(response)

    out = StringIO()
    kwargs = dict(
        navigation=navigation,
        grade_item_explainer=reader,
        input_fn=read_input,
        output=out,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
    )
    return kwargs, navigation, reader, verify, out


def test_named_read_uses_existing_readonly_explainer(tmp_path, monkeypatch):
    kw, nav, reader, verifier, out = setup(tmp_path, monkeypatch)
    named.run_named_grade_item_proficiency_explanation(**kw)
    rendered = out.getvalue()
    assert "Morgan Rivera" in rendered
    assert "Scene, Summary, and Pacing Check" in rendered
    assert "Standard RL.TS.11-12.4" in rendered
    assert "Meeting" in rendered
    assert "Current Standards Policy" in rendered
    assert "not zero" in rendered
    assert STUDENT not in rendered
    assert ITEM not in rendered
    assert SHA not in rendered
    reader.assert_called_once_with(tmp_path, CLASS, ITEM, STUDENT, STANDARD)
    assert verifier.call_count >= 6
    nav.session.select_student.assert_not_called()
    nav.session.select_grade_item.assert_not_called()


def test_technical_details_only_after_t(tmp_path, monkeypatch):
    kw, _, reader, verify, out = setup(tmp_path, monkeypatch, answers=("t", ""))
    named.run_named_grade_item_proficiency_explanation(**kw)
    txt = out.getvalue()
    assert f"student_id: {STUDENT}" in txt
    assert f"grade_item_id: {ITEM}" in txt
    assert f"result_sha256: {SHA}" in txt
    reader.assert_called_once()
    assert verify.call_count >= 9


@pytest.mark.parametrize("cancel", ("class", "item", "student", "standard"))
def test_cancellation_never_loads_proficiency(tmp_path, monkeypatch, cancel):
    kw, _, reader, _, _ = setup(tmp_path, monkeypatch)
    if cancel == "class":
        monkeypatch.setattr(named, "_class", lambda *_a, **_kw: None)
    if cancel == "item":
        monkeypatch.setattr(named, "_grade_item", lambda *_a, **_kw: None)
    if cancel in {"student", "standard"}:
        monkeypatch.setattr(
            named,
            "select_teacher_choice",
            lambda **_kw: (
                None
                if cancel == "student" or _kw["scope"] == "standard"
                else SimpleNamespace(identity=(STUDENT,), label="Morgan Rivera")
            ),
        )
    named.run_named_grade_item_proficiency_explanation(**kw)
    reader.assert_not_called()


def test_changed_class_blocks_before_reader(tmp_path, monkeypatch):
    kw, nav, reader, _, out = setup(tmp_path, monkeypatch)
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id="other", school_year="2026-2027"
    )
    named.run_named_grade_item_proficiency_explanation(**kw)
    reader.assert_not_called()
    assert "changed" in out.getvalue()


@pytest.mark.parametrize("stage", [0, 1, 2])
def test_stale_choice_blocks_before_reader(tmp_path, monkeypatch, stage):
    kw, _, reader, check, out = setup(tmp_path, monkeypatch)

    def verify(*_a, **arguments):
        if arguments["scope"] == ("grade_item", "student", "standard")[stage]:
            raise named._ScopeChanged("out of date")

    check.side_effect = verify
    named.run_named_grade_item_proficiency_explanation(**kw)
    reader.assert_not_called()
    assert "changed" in out.getvalue()


@pytest.mark.parametrize(
    "bad",
    (
        None,
        "",
        "0:" + SHA,
        "05:" + SHA,
        "1:XYZ",
        "1:" + "A" * 64,
        "1:" + "b" * 63,
        "1:some:hash",
    ),
)
def test_bad_witness_blocks_result_read(tmp_path, monkeypatch, bad):
    standard = SimpleNamespace(
        identity=(STANDARD,), label="Standard RL.TS.11-12.4", witness=bad
    )
    kw, _, reader, _, out = setup(tmp_path, monkeypatch, changes={"standard": standard})
    named.run_named_grade_item_proficiency_explanation(**kw)
    reader.assert_not_called()
    assert "changed" in out.getvalue()


@pytest.mark.parametrize(
    "alter",
    [
        {"title": "Another Explanation"},
        {"lines": ("Wrong student",)},
        {
            "lines": (
                "Grade Item: Other",
                f"Student: {STUDENT}",
                f"Standard: {STANDARD}",
                "Result: calculated",
                "Selection state: selected current",
            )
        },
        {
            "lines": (
                "Grade Item: Scene, Summary, and Pacing Check",
                f"Student: {STUDENT}",
                "Standard: OTHER",
                "Result: calculated",
                "Selection state: selected current",
            )
        },
        {
            "technical_lines": (
                f"class_id: {CLASS}",
                f"grade_item_id: {ITEM}",
                f"result_revision: {REV}",
                "result_sha256: " + "d" * 64,
            )
        },
        {
            "technical_lines": (
                "class_id: OTHER",
                f"grade_item_id: {ITEM}",
                f"result_revision: {REV}",
                f"result_sha256: {SHA}",
            )
        },
        {
            "technical_lines": (
                f"class_id: {CLASS}",
                f"grade_item_id: {ITEM}",
                "result_revision: 9",
                f"result_sha256: {SHA}",
            )
        },
        {"technical_lines": ()},
        {
            "lines": (
                f"Student: {STUDENT}",
                f"Standard: {STANDARD}",
                "Grade Item: Scene, Summary, and Pacing Check",
                "Selection state: selected current",
            )
        },
    ],
)
def test_wrong_presentation_fails_closed(tmp_path, monkeypatch, alter):
    kw, _, reader, _, out = setup(tmp_path, monkeypatch)
    reader.return_value = presentation(**alter)
    named.run_named_grade_item_proficiency_explanation(**kw)
    assert "Current Standards Policy" not in out.getvalue()
    assert "changed" in out.getvalue()


def test_class_changes_during_provenance_read(tmp_path, monkeypatch):
    kw, nav, reader, _, out = setup(tmp_path, monkeypatch)
    old = nav.current_class.return_value
    nav.current_class.side_effect = [old, old, None]
    named.run_named_grade_item_proficiency_explanation(**kw)
    reader.assert_called_once()
    assert "Current Standards Policy" not in out.getvalue()


def test_result_selection_changes_after_loading(tmp_path, monkeypatch):
    kw, _, reader, checks, out = setup(tmp_path, monkeypatch)
    counter = 0

    def change_after(*_a, **args):
        nonlocal counter
        counter += 1
        if counter == 6:
            raise named._ScopeChanged("result changed")

    checks.side_effect = change_after
    named.run_named_grade_item_proficiency_explanation(**kw)
    reader.assert_called_once()
    assert "Current Standards Policy" not in out.getvalue()


def test_runtime_failure_redacts_raw_error(tmp_path, monkeypatch):
    kw, _, reader, _, out = setup(tmp_path, monkeypatch)
    reader.side_effect = RuntimeError("secret/student/private/path")
    named.run_named_grade_item_proficiency_explanation(**kw)
    assert "secret/student" not in out.getvalue()
    assert "could not be verified safely" in out.getvalue()


@pytest.mark.parametrize("exc", [ReturnToMainMenu, QuitPDS])
def test_core_navigation_bubbles_up(tmp_path, monkeypatch, exc):
    kw, _, reader, _, _ = setup(tmp_path, monkeypatch)
    reader.side_effect = exc
    with pytest.raises(exc):
        named.run_named_grade_item_proficiency_explanation(**kw)


def test_menu_additive_and_all_old_routes_preserved():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_explain.py"
    ).read_text(encoding="utf-8")
    assert '"11. Explain Grade Item proficiency by name"' in source
    assert "run_named_grade_item_proficiency_explanation(" in source
    assert '"10. Compare a current Grade to a saved checkpoint by name"' in source
    assert '"9. Explain a current Grade by name"' in source
    assert '"3. Grade Item proficiency"' in source
    assert '"Please choose 1-11, B, M, or Q."' in source
    assert '"Please choose 1-8, B, M, or Q."' in source


def test_no_raw_identifiers_or_writes_in_controller():
    source = Path(named.__file__).read_text(encoding="utf-8")
    for marker in (
        'read_choice(input_fn, "Student ID',
        'read_choice(input_fn, "Grade Item ID',
        'read_choice(input_fn, "Standard ID',
        "write_",
        "commit_",
        "select_current_",
    ):
        if marker == "write_":
            assert source.count(marker) == source.count("write_lines")
        else:
            assert marker not in source
