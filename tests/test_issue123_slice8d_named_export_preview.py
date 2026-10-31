"""Issue #123 Slice 8D: guarded named export preview; no output or receipt write."""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_export_preview as named

CLASS = "opaque-class"
SNAPSHOT = "opaque-frozen-report"
PROFILE = "opaque-profile"
SHA1 = "a" * 64
SHA2 = "b" * 64
PERIOD = "mp1"


def snapshot(**changes):
    state = dict(
        snapshot_id=SNAPSHOT,
        snapshot_sha256=SHA1,
        school_year="2026-2027",
        period_id=PERIOD,
        calendar_revision=4,
        definition_id="hidden-def",
        definition_revision=1,
        row_count=29,
        created_at="2026-10-25T15:00:00+00:00",
    )
    state.update(changes)
    return SimpleNamespace(**state)


def profile_row(**changes):
    state = dict(
        profile_id=PROFILE,
        title="Grade Copy",
        latest_revision=4,
        current_revision=3,
    )
    state.update(changes)
    return SimpleNamespace(**state)


def profile(**changes):
    state = dict(
        class_id=CLASS,
        profile_id=PROFILE,
        revision=3,
        profile_sha256=SHA2,
        format="csv",
        columns=(("roster.display_name", "Student"), ("grade.base_grade", "Grade")),
    )
    state.update(changes)
    return SimpleNamespace(**state)


def preview(**changes):
    state = dict(
        class_id=CLASS,
        snapshot_id=SNAPSHOT,
        snapshot_sha256=SHA1,
        profile_id=PROFILE,
        profile_revision=3,
        profile_sha256=SHA2,
        format="csv",
        row_count=29,
        payload_byte_length=1400,
        payload_sha256="c" * 64,
        preview_sha256="d" * 64,
        diagnostic_lines=(),
        payload_text="SECRET_STUDENT_ROW",
        built=object(),
    )
    state.update(changes)
    return SimpleNamespace(**state)


def setup(tmp_path, monkeypatch, *, choices=("frozen_snapshot", "export_profile")):
    nav = MagicMock()
    school_year = "2026-2027"
    verified = SimpleNamespace(
        class_id=CLASS, workspace=tmp_path, school_year=school_year
    )
    period = SimpleNamespace(
        school_year=school_year, period_id=PERIOD, calendar_revision=4, label="MP1"
    )
    period_choice = SimpleNamespace(identity=(PERIOD,), label="MP1")
    nav.current_class.return_value = verified
    nav.current_period.return_value = period
    lister = MagicMock(return_value=(snapshot(),))
    profiles = MagicMock(return_value=(profile_row(),))
    loader = MagicMock(return_value=profile())
    builder = MagicMock(return_value=preview())
    monkeypatch.setattr(named, "_class", lambda *_a, **_k: (tmp_path, CLASS))
    monkeypatch.setattr(
        named, "_marking_period", lambda *_a, **_k: (period, period_choice)
    )
    monkeypatch.setattr(
        named, "load_teacher_choices", lambda *_a, **_k: (period_choice,)
    )
    monkeypatch.setattr(named, "_snapshot_revalidate", MagicMock())
    monkeypatch.setattr(named, "_profile_revalidate", MagicMock())
    snapshot_choice = SimpleNamespace(identity=(SNAPSHOT,), label="Semester Report")
    profile_choice = SimpleNamespace(identity=(PROFILE,), label="Grade Copy")
    remaining = iter(choices)

    def choose(*, scope, **_kwargs):
        assert scope == next(remaining)
        return snapshot_choice if scope == "frozen_snapshot" else profile_choice

    monkeypatch.setattr(named, "select_teacher_choice", choose)
    out = StringIO()
    args = dict(
        navigation=nav,
        snapshot_lister=lister,
        profile_lister=profiles,
        profile_loader=loader,
        preview_builder=builder,
        input_fn=lambda _question="": "",
        output=out,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        period_catalog=MagicMock(),
        snapshot_catalog=MagicMock(),
        profile_catalog=MagicMock(),
    )
    return args, nav, period, lister, profiles, loader, builder, out


def test_named_preview_shows_metadata_not_student_payload(tmp_path, monkeypatch):
    args, _, _, _, _, _, builder, out = setup(tmp_path, monkeypatch)
    named.run_named_report_export_preview(**args)
    text = out.getvalue()
    assert "Semester Report" in text
    assert "Grade Copy" in text
    assert "MP1" in text
    assert "Rows: 29" in text
    assert "Student, Grade" in text
    assert "SECRET_STUDENT_ROW" not in text
    assert "No export file, receipt" in text
    assert builder.call_count == 2
    builder.assert_called_with(tmp_path, CLASS, SNAPSHOT, SHA1, PROFILE)


@pytest.mark.parametrize(
    "changed",
    [
        {"class_id": "other"},
        {"snapshot_id": "other"},
        {"snapshot_sha256": SHA2},
        {"profile_id": "other"},
        {"profile_revision": 2},
        {"profile_sha256": SHA1},
        {"format": "tsv"},
        {"row_count": -1},
        {"payload_byte_length": -1},
        {"preview_sha256": "invalid"},
        {"payload_sha256": "invalid"},
        {"diagnostic_lines": tuple(str(i) for i in range(101))},
    ],
)
def test_wrong_preview_identity_is_blocked(tmp_path, monkeypatch, changed):
    args, _, _, _, _, _, builder, out = setup(tmp_path, monkeypatch)
    builder.return_value = preview(**changed)
    named.run_named_report_export_preview(**args)
    assert "Rows: 29" not in out.getvalue()
    assert "changed" in out.getvalue().lower()


def test_wrong_current_profile_is_blocked(tmp_path, monkeypatch):
    args, _, _, _, _, loader, builder, out = setup(tmp_path, monkeypatch)
    loader.return_value = profile(revision=4)
    named.run_named_report_export_preview(**args)
    builder.assert_not_called()
    assert "changed" in out.getvalue().lower()


def test_unselected_profile_is_not_a_choice(tmp_path, monkeypatch):
    args, _, _, _, profiles, _, builder, out = setup(tmp_path, monkeypatch)
    profiles.return_value = (profile_row(current_revision=None),)
    named.run_named_report_export_preview(**args)
    builder.assert_not_called()
    assert "changed" in out.getvalue().lower()


def test_wrong_period_filters_out_frozen_report(tmp_path, monkeypatch):
    args, _, _, lister, _, _, builder, out = setup(tmp_path, monkeypatch)
    lister.return_value = (snapshot(period_id="mp2"),)
    named.run_named_report_export_preview(**args)
    builder.assert_not_called()
    assert "changed" in out.getvalue().lower()


def test_wrong_calendar_filters_out_frozen_report(tmp_path, monkeypatch):
    args, _, _, lister, _, _, builder, out = setup(tmp_path, monkeypatch)
    lister.return_value = (snapshot(calendar_revision=3),)
    named.run_named_report_export_preview(**args)
    builder.assert_not_called()
    assert "changed" in out.getvalue().lower()


def test_changed_preview_between_reads_blocks_display(tmp_path, monkeypatch):
    args, _, _, _, _, _, builder, out = setup(tmp_path, monkeypatch)
    builder.side_effect = [preview(), preview(payload_sha256="e" * 64)]
    named.run_named_report_export_preview(**args)
    assert "Rows: 29" not in out.getvalue()
    assert "changed" in out.getvalue().lower()


def test_changed_current_class_blocks_builder(tmp_path, monkeypatch):
    args, nav, _, _, _, _, builder, out = setup(tmp_path, monkeypatch)
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id="wrong", school_year="2026-2027"
    )
    named.run_named_report_export_preview(**args)
    builder.assert_not_called()
    assert "changed" in out.getvalue().lower()


def test_missing_period_stops_before_preview(tmp_path, monkeypatch):
    args, _, _, _, _, _, builder, _ = setup(tmp_path, monkeypatch, choices=())
    monkeypatch.setattr(named, "_marking_period", lambda *_a, **_k: None)
    named.run_named_report_export_preview(**args)
    builder.assert_not_called()


def test_cancel_snapshot_stops_before_preview(tmp_path, monkeypatch):
    args, _, _, _, _, _, builder, _ = setup(tmp_path, monkeypatch, choices=())
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kwargs: None)
    named.run_named_report_export_preview(**args)
    builder.assert_not_called()


def test_cancel_profile_stops_before_preview(tmp_path, monkeypatch):
    args, _, _, _, _, _, builder, _ = setup(tmp_path, monkeypatch, choices=())
    counter = 0

    def choose(**_kwargs):
        nonlocal counter
        counter += 1
        return (
            SimpleNamespace(identity=(SNAPSHOT,), label="Semester Report")
            if counter == 1
            else None
        )

    monkeypatch.setattr(named, "select_teacher_choice", choose)
    named.run_named_report_export_preview(**args)
    builder.assert_not_called()


def test_sensitive_builder_error_is_not_printed(tmp_path, monkeypatch):
    args, _, _, _, _, _, builder, out = setup(tmp_path, monkeypatch)
    builder.side_effect = RuntimeError("sensitive /students/private/grade")
    named.run_named_report_export_preview(**args)
    assert "/students/" not in out.getvalue()
    assert "could not be verified" in out.getvalue()


@pytest.mark.parametrize("signal", (ReturnToMainMenu, QuitPDS))
def test_navigation_errors_propagate(tmp_path, monkeypatch, signal):
    args, _, _, _, _, _, builder, _ = setup(tmp_path, monkeypatch, choices=())
    monkeypatch.setattr(named, "_class", MagicMock(side_effect=signal))
    with pytest.raises(signal):
        named.run_named_report_export_preview(**args)
    builder.assert_not_called()


def test_bounded_snapshot_inventory(tmp_path, monkeypatch):
    args, _, _, lister, _, _, builder, out = setup(tmp_path, monkeypatch)
    lister.return_value = (snapshot(),) * 201
    named.run_named_report_export_preview(**args)
    builder.assert_not_called()
    assert "changed" in out.getvalue().lower()


def test_bounded_profile_inventory(tmp_path, monkeypatch):
    args, _, _, _, profiles, _, builder, out = setup(tmp_path, monkeypatch)
    profiles.return_value = (profile_row(),) * 201
    named.run_named_report_export_preview(**args)
    builder.assert_not_called()
    assert "changed" in out.getvalue().lower()


def test_exact_sources_rechecked_before_display(tmp_path, monkeypatch):
    args, _, _, snapshots, profiles, loader, _, out = setup(tmp_path, monkeypatch)
    named.run_named_report_export_preview(**args)
    assert "Rows: 29" in out.getvalue()
    assert snapshots.call_count >= 3
    assert profiles.call_count >= 3
    assert loader.call_count >= 2


def test_no_new_identifier_prompt_or_legacy_export_writes():
    text = Path(named.__file__).read_text(encoding="utf-8")
    assert "read_choice(" not in text
    assert "commit_report_export(" not in text
    assert "write_export_profile_revision(" not in text
    assert "select_export_profile(" not in text
    assert "payload_text" not in text


def test_existing_export_routes_preserved_and_new_preview_present():
    menu = (Path(__file__).resolve().parents[1] / "meridian/menu_export.py").read_text(
        encoding="utf-8"
    )
    assert "10. Preview a local report export by name" in menu
    assert "run_named_report_export_preview(" in menu
    assert "9. Browse past local exports by name" in menu
    assert '"5": _prepare_export' in menu
    bounds = re.findall(r"Please choose 1-(\d+), B, M, or Q\.", menu)
    assert any(int(bound) >= 10 for bound in bounds)
    assert "Please choose 1-6, B, M, or Q." in menu
