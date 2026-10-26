"""#123 Slice 9D: named marking-period proficiency, exact-result, read-only."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_explain_period_proficiency as named

CLASS = "english_12_pd2"
STUDENT = "opaque-student"
YEAR = "2026-2027"
PERIOD = "mp1"
PERIOD_LABEL = "Marking Period 1"
STANDARD = "RL.TS.11-12.4"
CAL = 7
REV = 4
SHA = "c" * 64


def presentation(**changes):
    fields = dict(
        title="Academic Period Proficiency Explanation",
        lines=(
            f"Academic Period: {PERIOD_LABEL}",
            f"Student: {STUDENT}",
            f"Standard: {STANDARD}",
            "Result: calculated",
            "Proficiency: Meeting",
            "Policy: Current Period Policy",
            "Grade Items: 3 calculated, 1 insufficient, "
            "0 missing, 0 outside period scope",
            "Selection state: selected current",
        ),
        technical_lines=(
            f"class_id: {CLASS}",
            f"school_year: {YEAR}",
            f"period_id: {PERIOD}",
            f"calendar_revision: {CAL}",
            f"student_id: {STUDENT}",
            f"standard_id: {STANDARD}",
            f"result_revision: {REV}",
            f"result_sha256: {SHA}",
            "inputs_sha256: " + "a" * 64,
        ),
    )
    fields.update(changes)
    return SimpleNamespace(**fields)


def setup(tmp_path, monkeypatch, *, answers=("",), changes=None):
    initial_class = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    period = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=CAL,
        label=PERIOD_LABEL,
    )
    period_choice = SimpleNamespace(identity=(PERIOD,), label=PERIOD_LABEL)
    student = SimpleNamespace(identity=(STUDENT,), label="Morgan Rivera")
    standard = SimpleNamespace(
        identity=(STANDARD,), label=f"Standard {STANDARD}", witness=f"{REV}:{SHA}"
    )
    choices = {
        "period": (period, period_choice),
        "student": student,
        "standard": standard,
    }
    if changes:
        choices.update(changes)
    nav = MagicMock()
    nav.current_class.return_value = initial_class
    nav.current_period.return_value = period
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    monkeypatch.setattr(named, "_marking_period", lambda *_a, **_kw: choices["period"])
    monkeypatch.setattr(
        named,
        "select_teacher_choice",
        lambda **kw: (
            choices["student"] if kw["scope"] == "student" else choices["standard"]
        ),
    )
    verification = MagicMock()
    monkeypatch.setattr(named, "_current_choice", verification)
    reader = MagicMock(return_value=presentation())
    iterator = iter(answers)

    def get_input(prompt=""):
        if prompt == "Press Enter to continue...":
            return ""
        return next(iterator)

    output = StringIO()
    args = dict(
        navigation=nav,
        academic_period_explainer=reader,
        input_fn=get_input,
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        period_catalog=MagicMock(),
    )
    return args, nav, reader, verification, output


def test_current_result_reuses_authoritative_read_only_explainer(tmp_path, monkeypatch):
    args, navigation, reader, checks, output = setup(tmp_path, monkeypatch)
    named.run_named_academic_period_proficiency_explanation(**args)
    text = output.getvalue()
    assert "Morgan Rivera" in text
    assert PERIOD_LABEL in text
    assert f"Standard {STANDARD}" in text
    assert "Meeting" in text
    assert "Current Period Policy" in text
    assert "3 calculated" in text
    assert "not zero" in text
    assert STUDENT not in text
    assert f"period_id: {PERIOD}" not in text
    assert SHA not in text
    reader.assert_called_once_with(tmp_path, CLASS, YEAR, PERIOD, STUDENT, STANDARD)
    assert checks.call_count >= 9
    navigation.session.select_student.assert_not_called()
    navigation.session.select_grade_item.assert_not_called()


def test_technical_provenance_is_opt_in_only(tmp_path, monkeypatch):
    args, _, reader, checks, output = setup(tmp_path, monkeypatch, answers=("t", ""))
    named.run_named_academic_period_proficiency_explanation(**args)
    result = output.getvalue()
    assert f"student_id: {STUDENT}" in result
    assert f"period_id: {PERIOD}" in result
    assert f"result_sha256: {SHA}" in result
    reader.assert_called_once()
    assert checks.call_count >= 12


@pytest.mark.parametrize("step", ("class", "period", "student", "standard"))
def test_cancel_never_calls_explanation(tmp_path, monkeypatch, step):
    args, _, reader, _, _ = setup(tmp_path, monkeypatch)
    if step == "class":
        monkeypatch.setattr(named, "_class", lambda *_a, **_kw: None)
    elif step == "period":
        monkeypatch.setattr(named, "_marking_period", lambda *_a, **_kw: None)
    else:
        original = named.select_teacher_choice
        monkeypatch.setattr(
            named,
            "select_teacher_choice",
            lambda **kw: (
                None
                if kw["scope"]
                == ("student" if step == "student" else "period_standard")
                else original(**kw)
            ),
        )
    named.run_named_academic_period_proficiency_explanation(**args)
    reader.assert_not_called()


def test_unverified_class_blocks(tmp_path, monkeypatch):
    args, navigation, reader, _, output = setup(tmp_path, monkeypatch)
    navigation.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id="another", school_year=YEAR
    )
    named.run_named_academic_period_proficiency_explanation(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue()


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace", Path("another")),
        ("class_id", "another"),
        ("school_year", "2025-2026"),
    ],
)
def test_period_must_match_verified_class(tmp_path, monkeypatch, field, value):
    args, _, reader, _, output = setup(tmp_path, monkeypatch)
    existing = named._marking_period(
        args["navigation"],
        MagicMock(),
        class_id=CLASS,
        root=tmp_path,
        input_fn=args["input_fn"],
        output=output,
        clear_fn=lambda: None,
    )
    period, choice = existing
    props = vars(period) | {field: value}
    monkeypatch.setattr(
        named,
        "_marking_period",
        lambda *_a, **_kw: (SimpleNamespace(**props), choice),
    )
    named.run_named_academic_period_proficiency_explanation(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue()


@pytest.mark.parametrize("scope", ["period", "student", "period_standard"])
def test_stale_choice_blocks_prior_to_read(tmp_path, monkeypatch, scope):
    args, _, reader, checks, output = setup(tmp_path, monkeypatch)

    def changed(*_a, **kw):
        if kw["scope"] == scope:
            raise named._ScopeChanged("stale")

    checks.side_effect = changed
    named.run_named_academic_period_proficiency_explanation(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue()


@pytest.mark.parametrize(
    "witness",
    [
        None,
        "",
        "0:" + SHA,
        "02:" + SHA,
        "4:NOT-HEX",
        "4:" + "c" * 63,
        "4:" + "C" * 64,
        "4:" + SHA + ":old",
    ],
)
def test_invalid_result_witness_prevents_reader(tmp_path, monkeypatch, witness):
    chosen = SimpleNamespace(
        identity=(STANDARD,), label=f"Standard {STANDARD}", witness=witness
    )
    args, _, reader, _, output = setup(
        tmp_path, monkeypatch, changes={"standard": chosen}
    )
    named.run_named_academic_period_proficiency_explanation(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue()


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "Other Explanation"},
        {"lines": ("Wrong student",)},
        {
            "lines": (
                presentation().lines[:1]
                + ("Student: OTHER",)
                + presentation().lines[2:]
            )
        },
        {
            "lines": (
                presentation().lines[:2]
                + ("Standard: OTHER",)
                + presentation().lines[3:]
            )
        },
        {"lines": ("Academic Period: WRONG",) + presentation().lines[1:]},
        {"lines": presentation().lines[:-1] + ("Selection state: superseded",)},
        {"lines": presentation().lines[:3] + ("Result: ",) + presentation().lines[4:]},
        {"lines": presentation().lines + ("unexpected student_id: hidden",)},
        {
            "technical_lines": (
                presentation().technical_lines[:1]
                + ("school_year: 2025-2026",)
                + presentation().technical_lines[2:]
            )
        },
        {
            "technical_lines": (
                presentation().technical_lines[:2]
                + ("period_id: OTHER",)
                + presentation().technical_lines[3:]
            )
        },
        {
            "technical_lines": (
                presentation().technical_lines[:3]
                + ("calendar_revision: 9",)
                + presentation().technical_lines[4:]
            )
        },
        {
            "technical_lines": (
                presentation().technical_lines[:4]
                + ("student_id: OTHER",)
                + presentation().technical_lines[5:]
            )
        },
        {
            "technical_lines": (
                presentation().technical_lines[:5]
                + ("standard_id: OTHER",)
                + presentation().technical_lines[6:]
            )
        },
        {
            "technical_lines": (
                presentation().technical_lines[:6]
                + ("result_revision: 9",)
                + presentation().technical_lines[7:]
            )
        },
        {
            "technical_lines": (
                presentation().technical_lines[:7]
                + ("result_sha256: " + "d" * 64,)
                + presentation().technical_lines[8:]
            )
        },
        {"technical_lines": ()},
    ],
)
def test_wrong_provenance_cannot_display_grade(tmp_path, monkeypatch, changes):
    args, _, reader, _, output = setup(tmp_path, monkeypatch)
    reader.return_value = presentation(**changes)
    named.run_named_academic_period_proficiency_explanation(**args)
    text = output.getvalue()
    assert "Current Period Policy" not in text
    assert "changed" in text


def test_class_changes_after_read_prevents_output(tmp_path, monkeypatch):
    args, nav, reader, _, output = setup(tmp_path, monkeypatch)
    first = nav.current_class.return_value
    nav.current_class.side_effect = [first, first, None]
    named.run_named_academic_period_proficiency_explanation(**args)
    reader.assert_called_once()
    assert "Current Period Policy" not in output.getvalue()


def test_period_changes_after_read_prevents_output(tmp_path, monkeypatch):
    args, nav, reader, _, output = setup(tmp_path, monkeypatch)
    first = nav.current_period.return_value
    nav.current_period.side_effect = [first, None]
    named.run_named_academic_period_proficiency_explanation(**args)
    reader.assert_called_once()
    assert "Current Period Policy" not in output.getvalue()


def test_selection_changes_after_read_prevents_output(tmp_path, monkeypatch):
    args, _, reader, checks, output = setup(tmp_path, monkeypatch)
    count = 0

    def verify(*_a, **_kw):
        nonlocal count
        count += 1
        if count == 5:
            raise named._ScopeChanged("stale selection")

    checks.side_effect = verify
    named.run_named_academic_period_proficiency_explanation(**args)
    reader.assert_called_once()
    assert "Current Period Policy" not in output.getvalue()


def test_provenance_exception_details_are_redacted(tmp_path, monkeypatch):
    args, _, reader, _, output = setup(tmp_path, monkeypatch)
    reader.side_effect = RuntimeError("private/secret/student/path")
    named.run_named_academic_period_proficiency_explanation(**args)
    assert "secret" not in output.getvalue()
    assert "could not be verified safely" in output.getvalue()


@pytest.mark.parametrize("exception", [ReturnToMainMenu, QuitPDS])
def test_navigation_bubbles_up(tmp_path, monkeypatch, exception):
    args, _, reader, _, _ = setup(tmp_path, monkeypatch)
    reader.side_effect = exception
    with pytest.raises(exception):
        named.run_named_academic_period_proficiency_explanation(**args)


def test_menu_additive_preserves_old_routes():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_explain.py"
    ).read_text(encoding="utf-8")
    assert '"12. Explain Academic Period proficiency by name"' in source
    assert "run_named_academic_period_proficiency_explanation(" in source
    assert '"11. Explain Grade Item proficiency by name"' in source
    assert '"10. Compare a current Grade to a saved checkpoint by name"' in source
    assert '"9. Explain a current Grade by name"' in source
    assert '"4. Academic Period proficiency"' in source
    assert any(
        f'"Please choose 1-{last}, B, M, or Q."' in source for last in range(12, 100)
    )
    assert '"Please choose 1-8, B, M, or Q."' in source


def test_existing_explanation_technical_scope_is_extended():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_explain.py"
    ).read_text(encoding="utf-8")
    segment = source.split("def _academic_period(", 1)[1].split(
        "def _planning_derivation(", 1
    )[0]
    for name in (
        "class_id",
        "school_year",
        "period_id",
        "calendar_revision",
        "student_id",
        "standard_id",
        "result_revision",
        "result_sha256",
    ):
        assert f"{name}: " in segment


def test_controller_has_no_raw_scope_prompts_or_writes():
    source = Path(named.__file__).read_text(encoding="utf-8")
    for forbidden in (
        'read_choice(input_fn, "Class ID',
        'read_choice(input_fn, "Period ID',
        'read_choice(input_fn, "Student ID',
        'read_choice(input_fn, "Standard ID',
        "commit_",
        "write_result",
        "select_current_",
    ):
        assert forbidden not in source
