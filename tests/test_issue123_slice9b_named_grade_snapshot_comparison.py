"""#123 Slice 9B: named frozen/current Grade comparison, read-only, scope-bound."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_explain_comparison as named

CLASS = "english_12_pd2"
STUDENT = "opaque-student"
YEAR = "2026-2027"
PERIOD = "mp1"
REV = 7
SNAPSHOT = "mk_" + "a" * 64
SHA = "b" * 64


def presentation(**updates):
    payload = dict(
        title="Prior / Current Grade Comparison",
        lines=(
            f"Student: {STUDENT}",
            "Relationship: comparable",
            "Changed: yes",
            "Reasons: effective Grade changed",
            "Effective Grade delta: 0.25",
        ),
        technical_lines=(
            f"snapshot_id: {SNAPSHOT}",
            f"snapshot_sha256: {SHA}",
            f"class_id: {CLASS}",
            f"calendar_revision: {REV}",
            "calculation_family: standards_based",
            "current_calculation_fingerprint: " + "c" * 64,
        ),
    )
    payload.update(updates)
    return SimpleNamespace(**payload)


def setup(tmp_path, monkeypatch, *, answers=("",), item_updates=None):
    student = SimpleNamespace(identity=(STUDENT,), label="Morgan Rivera")
    frozen = SimpleNamespace(
        identity=(SNAPSHOT,), label="MP1 Progress Report", witness=f"{SHA}:2:{REV}"
    )
    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    period = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=REV,
        label="Marking Period 1",
    )
    period_choice = SimpleNamespace(identity=(PERIOD,), label="Marking Period 1")
    item = SimpleNamespace(
        snapshot_id=SNAPSHOT,
        definition_id="definition",
        definition_revision=2,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=REV,
        row_count=8,
        created_at="2026-10-21T12:00:00+00:00",
        snapshot_sha256=SHA,
    )
    if item_updates:
        item = SimpleNamespace(**(vars(item) | item_updates))
    navigation = MagicMock()
    navigation.current_class.return_value = scope
    navigation.current_period.return_value = period
    class_catalog = MagicMock()
    period_catalog = MagicMock()
    frozen_catalog = MagicMock()
    frozen_catalog.options.return_value = (frozen,)
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "_marking_period", lambda *_a, **_kw: (period, period_choice)
    )
    monkeypatch.setattr(named, "_family", lambda **_kw: "standards_based")
    selected = iter((student, frozen))
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: next(selected))
    verify = MagicMock()
    monkeypatch.setattr(named, "_current_choice", verify)
    reader = MagicMock(return_value=presentation())
    seq = iter(answers)

    def input_fn(prompt=""):
        if prompt == "Press Enter to continue...":
            return ""
        return next(seq)

    output = StringIO()
    options = dict(
        navigation=navigation,
        snapshot_comparer=reader,
        input_fn=input_fn,
        output=output,
        clear_fn=lambda: None,
        snapshot_lister=MagicMock(return_value=(item,)),
        class_catalog=class_catalog,
        period_catalog=period_catalog,
        frozen_catalog=frozen_catalog,
    )
    return options, navigation, reader, verify, output, frozen, item


def test_named_comparison_read_only_and_exactly_bound(tmp_path, monkeypatch):
    args, navigation, reader, checks, output, _, _ = setup(tmp_path, monkeypatch)
    named.run_named_grade_snapshot_comparison(**args)
    rendered = output.getvalue()
    assert "Morgan Rivera" in rendered
    assert "Marking Period 1" in rendered
    assert "MP1 Progress Report" in rendered
    assert "0.25" in rendered
    assert "A missing or unavailable Grade is not zero." in rendered
    assert STUDENT not in rendered
    assert SNAPSHOT not in rendered
    assert SHA not in rendered
    reader.assert_called_once()
    assert reader.call_args.args[:5] == (tmp_path, CLASS, SNAPSHOT, SHA, STUDENT)
    assert reader.call_args.args[5].school_year == YEAR
    assert reader.call_args.args[5].period_id == PERIOD
    assert reader.call_args.args[6:] == (REV, "standards_based")
    assert checks.call_count >= 6
    navigation.session.select_student.assert_not_called()


def test_technical_details_only_after_t(tmp_path, monkeypatch):
    args, _, reader, _, output, _, _ = setup(tmp_path, monkeypatch, answers=("t", ""))
    named.run_named_grade_snapshot_comparison(**args)
    rendered = output.getvalue()
    assert SNAPSHOT in rendered
    assert SHA in rendered
    assert STUDENT in rendered
    reader.assert_called_once()


@pytest.mark.parametrize("stage", ["class", "period", "student", "family", "snapshot"])
def test_cancellation_does_not_read_comparison(tmp_path, monkeypatch, stage):
    args, _, reader, _, _, _, _ = setup(tmp_path, monkeypatch)
    if stage == "class":
        monkeypatch.setattr(named, "_class", lambda *_a, **_kw: None)
    elif stage == "period":
        monkeypatch.setattr(named, "_marking_period", lambda *_a, **_kw: None)
    elif stage == "family":
        monkeypatch.setattr(named, "_family", lambda **_kw: None)
    else:
        target = "student" if stage == "student" else "frozen_snapshot"

        def choose(**kw):
            if kw["scope"] == target:
                return None
            return SimpleNamespace(identity=(STUDENT,), label="Morgan")

        monkeypatch.setattr(named, "select_teacher_choice", choose)
    named.run_named_grade_snapshot_comparison(**args)
    reader.assert_not_called()


def test_initial_class_change_fails_before_read(tmp_path, monkeypatch):
    args, nav, reader, _, output, _, _ = setup(tmp_path, monkeypatch)
    nav.current_class.return_value = None
    named.run_named_grade_snapshot_comparison(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue()


def test_period_change_fails_before_read(tmp_path, monkeypatch):
    args, nav, reader, _, output, _, _ = setup(tmp_path, monkeypatch)
    nav.current_period.return_value = None
    named.run_named_grade_snapshot_comparison(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue()


def test_stale_student_or_snapshot_choice_fails_closed(tmp_path, monkeypatch):
    args, _, reader, verify, output, _, _ = setup(tmp_path, monkeypatch)
    verify.side_effect = named._ScopeChanged("stale")
    named.run_named_grade_snapshot_comparison(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue()


@pytest.mark.parametrize(
    "changes",
    [
        {"school_year": "2025-2026"},
        {"period_id": "mp2"},
        {"calendar_revision": REV + 1},
        {"snapshot_sha256": "d" * 64},
    ],
)
def test_incompatible_historical_snapshot_blocks(tmp_path, monkeypatch, changes):
    args, _, reader, _, output, _, _ = setup(
        tmp_path, monkeypatch, item_updates=changes
    )
    named.run_named_grade_snapshot_comparison(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue()


def test_missing_historical_snapshot_blocks(tmp_path, monkeypatch):
    args, _, reader, _, output, _, _ = setup(tmp_path, monkeypatch)
    args["snapshot_lister"].return_value = ()
    named.run_named_grade_snapshot_comparison(**args)
    reader.assert_not_called()
    assert "changed" in output.getvalue()


def test_comparison_change_during_read_never_displays_result(tmp_path, monkeypatch):
    args, _, reader, _, output, _, _ = setup(tmp_path, monkeypatch)
    lister = args["snapshot_lister"]
    original = lister.return_value
    lister.side_effect = [original, original, (), ()]
    named.run_named_grade_snapshot_comparison(**args)
    reader.assert_called_once()
    assert "Effective Grade delta: 0.25" not in output.getvalue()


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "Wrong title"},
        {
            "lines": (
                "Student: another",
                "Relationship: comparable",
                "Changed: no",
                "Reasons: none",
                "Effective Grade delta: 0",
            )
        },
        {
            "lines": (
                "Student: opaque-student",
                "Relationship: invented",
                "Changed: no",
                "Reasons: none",
                "Effective Grade delta: 0",
            )
        },
        {"technical_lines": ("snapshot_id: another",)},
        {
            "technical_lines": (
                f"snapshot_id: {SNAPSHOT}",
                f"snapshot_sha256: {'d' * 64}",
                f"class_id: {CLASS}",
                f"calendar_revision: {REV}",
                "calculation_family: standards_based",
                "current_calculation_fingerprint: " + "c" * 64,
            )
        },
        {"lines": ("Student: opaque-student", "Changed: no")},
    ],
)
def test_wrong_result_scope_redacted(tmp_path, monkeypatch, changes):
    args, _, reader, _, output, _, _ = setup(tmp_path, monkeypatch)
    reader.return_value = presentation(**changes)
    named.run_named_grade_snapshot_comparison(**args)
    assert "Effective Grade delta: 0.25" not in output.getvalue()
    assert "changed" in output.getvalue()


def test_errors_are_redacted(tmp_path, monkeypatch):
    args, _, reader, _, output, _, _ = setup(tmp_path, monkeypatch)
    reader.side_effect = RuntimeError("private/student/filename")
    named.run_named_grade_snapshot_comparison(**args)
    assert "private/student" not in output.getvalue()
    assert "could not be verified" in output.getvalue()


@pytest.mark.parametrize("error", [ReturnToMainMenu, QuitPDS])
def test_navigation_exceptions_propagate(tmp_path, monkeypatch, error):
    args, _, reader, _, _, _, _ = setup(tmp_path, monkeypatch)
    reader.side_effect = error
    with pytest.raises(error):
        named.run_named_grade_snapshot_comparison(**args)


def test_period_scoped_catalog_filters_incompatible_snapshots(tmp_path):
    valid = SimpleNamespace(identity=(SNAPSHOT,), label="Correct")
    other = SimpleNamespace(identity=("snapshot-2",), label="Other")
    inner = MagicMock()
    inner.options.return_value = (valid, other)
    entries = (
        SimpleNamespace(
            snapshot_id=SNAPSHOT,
            school_year=YEAR,
            period_id=PERIOD,
            calendar_revision=REV,
        ),
        SimpleNamespace(
            snapshot_id="snapshot-2",
            school_year=YEAR,
            period_id="mp2",
            calendar_revision=REV,
        ),
    )
    catalog = named._PeriodSnapshotCatalog(
        inner, lambda *_: entries, tmp_path, CLASS, YEAR, PERIOD, REV
    )
    assert catalog.options(scope="frozen_snapshot", selected={"class": CLASS}) == (
        valid,
    )


def test_period_scoped_catalog_rejects_wrong_scope(tmp_path):
    catalog = named._PeriodSnapshotCatalog(
        MagicMock(), MagicMock(), tmp_path, CLASS, YEAR, PERIOD, REV
    )
    with pytest.raises(named._ComparisonChanged):
        catalog.options(scope="other", selected={"class": CLASS})


def test_teacher_route_additive_and_legacy_routes_preserved():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_explain.py"
    ).read_text(encoding="utf-8")
    assert "10. Compare a current Grade to a saved checkpoint by name" in source
    assert "run_named_grade_snapshot_comparison(" in source
    assert '"9. Explain a current Grade by name"' in source
    assert '"2. Prior / current Grade comparison"' in source
    assert '"1. Current Grade"' in source
    assert '"Please choose 1-8, B, M, or Q."' in source


def test_no_raw_identifier_input_or_snapshot_writes():
    code = Path(named.__file__).read_text(encoding="utf-8")
    assert 'read_choice(input_fn, "Student ID' not in code
    assert 'read_choice(input_fn, "Snapshot ID' not in code
    assert 'read_choice(input_fn, "SHA' not in code
    assert "commit_" not in code
    assert "write_" not in code.replace("write_lines", "")
