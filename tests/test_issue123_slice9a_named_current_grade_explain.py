"""#123 Slice 9A: class-scoped current Grade explanation; no technical inputs."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_explain_grade as named

CLASS = "english_12_pd2"
STUDENT = "student-hidden"
YEAR = "2026-2027"
PERIOD = "mp1"
REV = 7


def presentation(**changes):
    data = dict(
        title="Current Grade Explanation",
        lines=(
            f"Student: {STUDENT}",
            f"Academic Period: {YEAR} / {PERIOD}",
            "Calculation family: standards based",
            "Policy: District SBG",
            "Base result: unassessed",
            "Base Grade: not numeric",
            "Effective Grade: not numeric",
            "Effective source: no grade",
            "Override: not applicable",
            "Standards considered: 4",
        ),
        technical_lines=(
            f"class_id: {CLASS}",
            f"student_id: {STUDENT}",
            f"calendar_revision: {REV}",
            "policy_sha256: " + "a" * 64,
        ),
    )
    data.update(changes)
    return SimpleNamespace(**data)


def prepare(tmp_path, monkeypatch, *, answers=("",)):
    navigation = MagicMock()
    verified = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    period = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=REV,
        label="Marking Period 1",
    )
    navigation.current_class.return_value = verified
    navigation.current_period.return_value = period
    student = SimpleNamespace(identity=(STUDENT,), label="Morgan Rivera")
    period_choice = SimpleNamespace(identity=(PERIOD,), label="Marking Period 1")
    catalog = MagicMock()
    periods = MagicMock()
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "_marking_period", lambda *_a, **_kw: (period, period_choice)
    )
    monkeypatch.setattr(named, "_family", lambda **_kw: "standards_based")
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: student)
    checks = MagicMock()
    monkeypatch.setattr(named, "_current_choice", checks)
    reader = MagicMock(return_value=presentation())
    iterator = iter(answers)

    def read_input(prompt=""):
        if prompt == "Press Enter to continue...":
            return ""
        return next(iterator)

    out = StringIO()
    args = dict(
        navigation=navigation,
        current_grade_explainer=reader,
        input_fn=read_input,
        output=out,
        clear_fn=lambda: None,
        class_catalog=catalog,
        period_catalog=periods,
    )
    return args, navigation, reader, checks, student, period, out


def test_named_result_uses_readonly_authoritative_reader(tmp_path, monkeypatch):
    args, nav, reader, _, _, _, out = prepare(tmp_path, monkeypatch)
    named.run_named_current_grade_explanation(**args)
    text = out.getvalue()
    assert "Morgan Rivera" in text
    assert "Marking Period 1" in text
    assert "District SBG" in text
    assert "not numeric" in text
    assert "unassessed" in text
    assert STUDENT not in text
    assert "policy_sha256:" not in text
    assert "No academic" not in text
    assert "no Grade or evidence record was changed" in text
    reader.assert_called_once()
    assert reader.call_args.args[:3] == (tmp_path, CLASS, STUDENT)
    assert reader.call_args.args[3].school_year == YEAR
    assert reader.call_args.args[3].period_id == PERIOD
    assert reader.call_args.args[4:] == (REV, "standards_based")
    nav.session.select_student.assert_not_called()


def test_technical_provenance_requires_t(tmp_path, monkeypatch):
    args, _, reader, checks, _, _, out = prepare(
        tmp_path, monkeypatch, answers=("t", "")
    )
    named.run_named_current_grade_explanation(**args)
    text = out.getvalue()
    assert "policy_sha256:" in text
    assert STUDENT in text
    assert checks.call_count >= 4
    reader.assert_called_once()


def test_cancel_without_class_never_reads_grade(tmp_path, monkeypatch):
    args, _, reader, _, _, _, _ = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: None)
    named.run_named_current_grade_explanation(**args)
    reader.assert_not_called()


def test_cancel_without_period_never_reads_grade(tmp_path, monkeypatch):
    args, _, reader, _, _, _, _ = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(named, "_marking_period", lambda *_a, **_kw: None)
    named.run_named_current_grade_explanation(**args)
    reader.assert_not_called()


def test_cancel_without_student_never_reads_grade(tmp_path, monkeypatch):
    args, _, reader, _, _, _, _ = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: None)
    named.run_named_current_grade_explanation(**args)
    reader.assert_not_called()


def test_cancel_without_family_never_reads_grade(tmp_path, monkeypatch):
    args, _, reader, _, _, _, _ = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(named, "_family", lambda **_kw: None)
    named.run_named_current_grade_explanation(**args)
    reader.assert_not_called()


def test_wrong_initial_class_never_reads_grade(tmp_path, monkeypatch):
    args, nav, reader, _, _, _, out = prepare(tmp_path, monkeypatch)
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id="other", school_year=YEAR
    )
    named.run_named_current_grade_explanation(**args)
    reader.assert_not_called()
    assert "changed" in out.getvalue()


def test_stale_period_never_reads_grade(tmp_path, monkeypatch):
    args, nav, reader, _, _, _, out = prepare(tmp_path, monkeypatch)
    nav.current_period.return_value = None
    named.run_named_current_grade_explanation(**args)
    reader.assert_not_called()
    assert "changed" in out.getvalue()


def test_stale_student_witness_never_reads_grade(tmp_path, monkeypatch):
    args, _, reader, checks, _, _, out = prepare(tmp_path, monkeypatch)
    checks.side_effect = named._ScopeChanged("stale student")
    named.run_named_current_grade_explanation(**args)
    reader.assert_not_called()
    assert "changed" in out.getvalue()


def test_class_changes_during_read_blocks_display(tmp_path, monkeypatch):
    args, nav, reader, _, _, _, out = prepare(tmp_path, monkeypatch)
    old = nav.current_class.return_value
    nav.current_class.side_effect = [old, old, None]
    named.run_named_current_grade_explanation(**args)
    reader.assert_called_once()
    assert "District SBG" not in out.getvalue()


@pytest.mark.parametrize(
    "alter",
    [
        {"title": "Other Grade Explanation"},
        {"lines": ("Other Student",)},
        {"lines": ("Student: student-hidden", "Academic Period: 2026-2027 / mp1")},
        {"technical_lines": ("student_id: other",)},
        {"technical_lines": ()},
        {
            "technical_lines": (
                "class_id: another",
                "student_id: student-hidden",
                "calendar_revision: 7",
            )
        },
    ],
)
def test_mismatched_presentation_fails_closed(tmp_path, monkeypatch, alter):
    args, _, reader, _, _, _, out = prepare(tmp_path, monkeypatch)
    reader.return_value = presentation(**alter)
    named.run_named_current_grade_explanation(**args)
    text = out.getvalue()
    assert "District SBG" not in text
    assert "changed" in text


def test_error_details_redacted(tmp_path, monkeypatch):
    args, _, reader, _, _, _, out = prepare(tmp_path, monkeypatch)
    reader.side_effect = RuntimeError("secret/student/private/path")
    named.run_named_current_grade_explanation(**args)
    assert "secret/student" not in out.getvalue()
    assert "unavailable" in out.getvalue()


@pytest.mark.parametrize("error", [ReturnToMainMenu, QuitPDS])
def test_core_navigation_bubbles_up(tmp_path, monkeypatch, error):
    args, _, reader, _, _, _, _ = prepare(tmp_path, monkeypatch)
    reader.side_effect = error
    with pytest.raises(error):
        named.run_named_current_grade_explanation(**args)


def test_no_raw_identifier_prompt_or_writes():
    code = Path(named.__file__).read_text(encoding="utf-8")
    assert 'read_choice(input_fn, "Class ID' not in code
    assert 'read_choice(input_fn, "Student ID' not in code
    assert "write_" not in code.replace("write_lines", "")
    assert "commit_" not in code


def test_explain_menu_append_only_route_present():
    source = Path(__file__).resolve().parents[1] / "meridian/menu_explain.py"
    text = source.read_text(encoding="utf-8")
    assert "9. Explain a current Grade by name" in text
    assert "run_named_current_grade_explanation(" in text
    assert '"8. ExportReceipt provenance"' in text
    assert '"1. Current Grade"' in text
    # Option 9 must persist even when future named routes append.
    assert "Please choose 1-8, B, M, or Q." in text
