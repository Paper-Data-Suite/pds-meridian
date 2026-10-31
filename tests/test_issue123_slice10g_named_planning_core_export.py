"""#123 Slice 10G: name-based explicit Core/receipt/optional CSV export."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_planning_export as named

CLASS = "class_2"
YEAR = "2026-2027"
PREVIEW = "gsp_" + "a" * 64
PREVIEW_SHA = "b" * 64
DERIVATION = "gsd_" + "c" * 64
DERIVATION_SHA = "d" * 64
REVIEW_SHA = "e" * 64
SIGNAL_ID = "meridian_signal_" + "f" * 32
WHEN = datetime(2026, 10, 26, 21, 0, tzinfo=UTC)


class FakeCoreResult:
    def __init__(self, **data):
        self.__dict__.update(data)


class FakeExportResult:
    def __init__(self, *, core, csv):
        self.core = core
        self.csv = csv


def summary(**changes):
    data = dict(
        preview_id=PREVIEW,
        preview_sha256=PREVIEW_SHA,
        derivation_id=DERIVATION,
        derivation_sha256=DERIVATION_SHA,
        policy_id="policy_1",
        policy_revision=3,
        policy_sha256="0" * 64,
        title="Reading Progress Groups",
        period_label="Marking Period 1",
        school_year=YEAR,
        period_id="mp1",
        calendar_revision=7,
        standard_id="RL.TS.11-12.4",
        dimension_id="readiness",
        band_count=3,
        roster_count=29,
        selected_review_revision=2,
        selected_review_sha256=REVIEW_SHA,
    )
    data.update(changes)
    return named.PlanningPreviewSummary(**data)


def projection(**changes):
    derivation = SimpleNamespace(
        class_id=CLASS, derivation_id=DERIVATION, derivation_sha256=DERIVATION_SHA
    )
    preview = SimpleNamespace(
        class_id=CLASS, preview_id=PREVIEW, preview_sha256=PREVIEW_SHA
    )
    review = SimpleNamespace(
        class_id=CLASS,
        derivation_id=DERIVATION,
        review_revision=2,
        review_sha256=REVIEW_SHA,
    )
    data = dict(
        class_id=CLASS,
        preview_reference=preview,
        derivation_reference=derivation,
        policy_reference=SimpleNamespace(
            class_id=CLASS,
            policy_id="policy_1",
            policy_revision=3,
            policy_sha256="0" * 64,
        ),
        policy_title="Reading Progress Groups",
        school_year=YEAR,
        period_id="mp1",
        calendar_revision=7,
        standard_id="RL.TS.11-12.4",
        dimension_id="readiness",
        band_count=3,
        live_currentness=SimpleNamespace(state="current"),
        coverage=SimpleNamespace(
            roster_student_count=29,
            contributing_student_count=25,
            noncontributing_student_count=4,
        ),
        band_summaries=tuple(
            SimpleNamespace(band=i, label=f"Band {i}", student_count=n)
            for i, n in ((1, 11), (2, 10), (3, 4))
        ),
        diagnostics=(),
        review_status=SimpleNamespace(
            selected_review_reference=review,
            decision="accepted_for_export",
            applicability=SimpleNamespace(status="current"),
        ),
        student_assignments=(),
        noncontributing_students=(),
    )
    data.update(changes)
    return SimpleNamespace(**data)


def prepared(**changes):
    p = projection()
    data = dict(
        projection=p,
        eligibility=SimpleNamespace(
            preview_reference=p.preview_reference,
            derivation_reference=p.derivation_reference,
            review_reference=p.review_status.selected_review_reference,
            currentness=SimpleNamespace(
                state="current", current_derivation_reference=p.derivation_reference
            ),
        ),
        signal_set=SimpleNamespace(
            class_id=CLASS,
            signal_set_id=SIGNAL_ID,
            created_at=WHEN,
            source=SimpleNamespace(
                kind="module_generated",
                module_id="meridian",
                snapshot_id=DERIVATION,
                snapshot_digest=DERIVATION_SHA,
            ),
            dimensions=(SimpleNamespace(dimension_id="readiness", band_count=3),),
        ),
        final_core_revalidation_required=True,
        contributing_student_ids=tuple(f"s{i}" for i in range(25)),
        noncontributing_student_ids=tuple(f"s{i}" for i in range(25, 29)),
    )
    data.update(changes)
    return SimpleNamespace(**data)


def committed(plan, destination=None, **changes):
    data = dict(
        preview=plan,
        core_write_disposition="created",
        receipt_write_disposition="created",
        core_signal_digest="1" * 64,
        receipt_sha256="2" * 64,
        core_export_action="performed",
        export_receipt_action="performed",
        review_write_action="not_performed",
        review_selection_action="not_performed",
        csv_export_action="not_performed",
        concord_action="not_performed",
    )
    data.update(changes)
    core = named.PlanningSignalCoreExportCommitResult(**data)
    if destination is None:
        return core
    csv = SimpleNamespace(
        class_id=CLASS,
        signal_set_id=SIGNAL_ID,
        destination=destination,
        disposition="created",
    )
    return named.PlanningSignalExportCommitResult(core=core, csv=csv)


def setup(tmp_path, monkeypatch, *, answers=("1", "B"), chosen=True, parent=None):
    s = summary() if parent is None else parent
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    catalog = MagicMock()
    catalog.inspect.return_value = s
    selector = MagicMock(return_value=s.choice() if chosen else None)
    maker = MagicMock(return_value=prepared())
    writer = MagicMock(side_effect=lambda root, p, path: committed(p, path))
    monkeypatch.setattr(named, "PlanningSignalCoreExportCommitResult", FakeCoreResult)
    monkeypatch.setattr(named, "PlanningSignalExportCommitResult", FakeExportResult)
    monkeypatch.setattr(named, "_class", lambda *args, **kwargs: (tmp_path, CLASS))
    monkeypatch.setattr(named, "select_teacher_choice", selector)
    monkeypatch.setattr(named, "_current_choice", MagicMock())
    monkeypatch.setattr(named, "_checked_projection", MagicMock())
    iterator = iter(answers)
    prompts = []

    def user_input(prompt=""):
        prompts.append(prompt)
        return next(iterator, "")

    output = StringIO()
    args = dict(
        navigation=nav,
        export_previewer=maker,
        export_committer=writer,
        clock=lambda: WHEN,
        input_fn=user_input,
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        preview_catalog=catalog,
        id_factory=lambda: SIGNAL_ID,
    )
    return args, output, maker, writer, catalog, nav, prompts


def run(args):
    named.run_named_planning_core_export(**args)


def test_core_export_requires_confirmation(tmp_path, monkeypatch):
    args, output, maker, writer, _, _, prompts = setup(
        tmp_path, monkeypatch, answers=("1", "EXPORT", "")
    )
    run(args)
    maker.assert_called_once_with(
        tmp_path, CLASS, "policy_1", PREVIEW, PREVIEW_SHA, SIGNAL_ID, WHEN
    )
    writer.assert_called_once_with(tmp_path, maker.return_value, None)
    assert "Planning Signal Export Completed" in output.getvalue()
    assert PREVIEW_SHA not in output.getvalue()
    assert SIGNAL_ID not in output.getvalue()
    assert not any("signal-set ID" in p or "sha256" in p for p in prompts)


def test_csv_export_checks_canonical_destination(tmp_path, monkeypatch):
    target = tmp_path / "groups.csv"
    args, output, maker, writer, *_ = setup(
        tmp_path, monkeypatch, answers=("2", str(target), "EXPORT", "")
    )
    run(args)
    writer.assert_called_once_with(tmp_path, maker.return_value, target)
    assert "Local CSV: created" in output.getvalue()


@pytest.mark.parametrize("value", ["", "B", "export", "YES", "SELECT", "1", "WRITE"])
def test_export_confirmation_is_exact(tmp_path, monkeypatch, value):
    args, output, _, writer, *_ = setup(tmp_path, monkeypatch, answers=("1", value, ""))
    run(args)
    writer.assert_not_called()
    assert "Export Completed" not in output.getvalue()


@pytest.mark.parametrize("answer", ["", "B", "3", "EXPORT", "no"])
def test_unselected_output_never_prepares(tmp_path, monkeypatch, answer):
    args, _, maker, writer, *_ = setup(tmp_path, monkeypatch, answers=(answer, ""))
    run(args)
    maker.assert_not_called()
    writer.assert_not_called()


@pytest.mark.parametrize("answer", ["", "B", "report.txt", "noext"])
def test_invalid_or_cancelled_csv_never_prepares(tmp_path, monkeypatch, answer):
    args, _, maker, writer, *_ = setup(tmp_path, monkeypatch, answers=("2", answer, ""))
    run(args)
    maker.assert_not_called()
    writer.assert_not_called()


def test_cancelled_named_preview_never_prepares(tmp_path, monkeypatch):
    args, _, maker, writer, *_ = setup(tmp_path, monkeypatch, chosen=False)
    run(args)
    maker.assert_not_called()
    writer.assert_not_called()


def test_unselected_review_is_reported_without_export(tmp_path, monkeypatch):
    args, output, maker, writer, *_ = setup(
        tmp_path,
        monkeypatch,
        parent=summary(selected_review_revision=None, selected_review_sha256=None),
    )
    run(args)
    maker.assert_not_called()
    writer.assert_not_called()
    assert "No Planning Review is selected" in output.getvalue()


def test_technical_details_opt_in(tmp_path, monkeypatch):
    args, output, _, writer, *_ = setup(
        tmp_path, monkeypatch, answers=("1", "T", "", "B")
    )
    run(args)
    writer.assert_not_called()
    assert SIGNAL_ID in output.getvalue()
    assert PREVIEW_SHA in output.getvalue()
    assert WHEN.isoformat() in output.getvalue()


@pytest.mark.parametrize(
    "field,value",
    [
        ("school_year", "2025-2026"),
        ("preview_sha256", "3" * 64),
        ("selected_review_sha256", "4" * 64),
        ("selected_review_revision", None),
    ],
)
def test_changed_preview_witness_blocks_preparation(
    tmp_path, monkeypatch, field, value
):
    args, output, maker, writer, catalog, *_ = setup(tmp_path, monkeypatch)
    catalog.inspect.return_value = summary(**{field: value})
    run(args)
    maker.assert_not_called()
    writer.assert_not_called()
    assert "changed" in output.getvalue().lower()


def test_class_switch_during_preview_blocks_commit(tmp_path, monkeypatch):
    args, output, maker, writer, _, nav, *_ = setup(
        tmp_path, monkeypatch, answers=("1", "EXPORT", "")
    )

    def swap(*args):
        nav.current_class.return_value = SimpleNamespace(
            workspace=tmp_path, class_id="other", school_year=YEAR
        )
        return prepared()

    maker.side_effect = swap
    run(args)
    writer.assert_not_called()
    assert "changed" in output.getvalue().lower()


@pytest.mark.parametrize(
    "field,value",
    [
        ("class_id", "other"),
        ("signal_set_id", "meridian_signal_" + "a" * 32),
        ("created_at", datetime(2026, 10, 25, tzinfo=UTC)),
    ],
)
def test_wrong_core_signal_blocks_commit(tmp_path, monkeypatch, field, value):
    args, output, maker, writer, *_ = setup(tmp_path, monkeypatch)
    base = prepared()
    item = SimpleNamespace(**vars(base.signal_set))
    setattr(item, field, value)
    maker.return_value = prepared(signal_set=item)
    run(args)
    writer.assert_not_called()
    assert "changed" in output.getvalue().lower()


@pytest.mark.parametrize(
    "field,value",
    [
        ("decision", "rejected"),
        ("applicability", SimpleNamespace(status="stale")),
    ],
)
def test_review_ineligible_never_commits(tmp_path, monkeypatch, field, value):
    args, _, maker, writer, *_ = setup(tmp_path, monkeypatch)
    p = prepared()
    r = SimpleNamespace(**vars(p.projection.review_status))
    setattr(r, field, value)
    proj = SimpleNamespace(**vars(p.projection))
    proj.review_status = r
    maker.return_value = prepared(projection=proj)
    run(args)
    writer.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("preview_reference", SimpleNamespace(preview_id="wrong")),
        (
            "review_reference",
            SimpleNamespace(review_revision=99, review_sha256="0" * 64),
        ),
        (
            "currentness",
            SimpleNamespace(state="stale", current_derivation_reference=None),
        ),
    ],
)
def test_wrong_export_eligibility_never_commits(tmp_path, monkeypatch, field, value):
    args, _, maker, writer, *_ = setup(tmp_path, monkeypatch)
    p = prepared()
    e = SimpleNamespace(**vars(p.eligibility))
    setattr(e, field, value)
    maker.return_value = prepared(eligibility=e)
    run(args)
    writer.assert_not_called()


@pytest.mark.parametrize(
    "identity",
    [
        "a",
        "",
        "meridian_signal_" + "g" * 32,
        "meridian_signal_" + "1" * 31,
        "wrong_" + "1" * 32,
    ],
)
def test_bad_generated_identity_blocks_preparation(tmp_path, monkeypatch, identity):
    args, _, maker, writer, *_ = setup(tmp_path, monkeypatch)
    args["id_factory"] = lambda: identity
    run(args)
    maker.assert_not_called()
    writer.assert_not_called()


@pytest.mark.parametrize("date", [datetime(2026, 10, 26), "2026-10-26"])
def test_bad_export_clock_blocks_preparation(tmp_path, monkeypatch, date):
    args, _, maker, writer, *_ = setup(tmp_path, monkeypatch)
    args["clock"] = lambda: date
    run(args)
    maker.assert_not_called()
    writer.assert_not_called()


def test_preparer_error_is_redacted_without_claim_of_write(tmp_path, monkeypatch):
    args, output, maker, writer, *_ = setup(tmp_path, monkeypatch)
    maker.side_effect = RuntimeError("secret core location and student names")
    run(args)
    writer.assert_not_called()
    assert "secret core location" not in output.getvalue()
    assert "No export requested" in output.getvalue()


def test_commit_failure_acknowledges_partial_core_write(tmp_path, monkeypatch):
    args, output, _, writer, *_ = setup(
        tmp_path, monkeypatch, answers=("1", "EXPORT", "")
    )
    writer.side_effect = RuntimeError("private storage location")
    run(args)
    assert "may be durable" in output.getvalue()
    assert "private storage" not in output.getvalue()
    assert "Export Completed" not in output.getvalue()


@pytest.mark.parametrize(
    "field,value",
    [
        ("core_write_disposition", "different"),
        ("receipt_write_disposition", "invalid"),
        ("core_signal_digest", "not-a-hash"),
        ("core_export_action", "not_performed"),
        ("concord_action", "performed"),
    ],
)
def test_bad_commit_result_never_claims_success(tmp_path, monkeypatch, field, value):
    args, output, maker, writer, *_ = setup(
        tmp_path, monkeypatch, answers=("1", "EXPORT", "")
    )
    writer.side_effect = lambda root, p, path: committed(p, path, **{field: value})
    run(args)
    assert "Export Completed" not in output.getvalue()
    assert "inspect saved exports" in output.getvalue()


def test_wrong_csv_result_never_claims_success(tmp_path, monkeypatch):
    target = tmp_path / "groups.csv"
    args, output, maker, writer, *_ = setup(
        tmp_path, monkeypatch, answers=("2", str(target), "EXPORT", "")
    )

    def wrong_result(root, p, path):
        item = committed(p, path)
        item.csv.destination = tmp_path / "another.csv"
        return item

    writer.side_effect = wrong_result
    run(args)
    assert "Export Completed" not in output.getvalue()


def test_unexpected_csv_with_core_only_never_claims_success(tmp_path, monkeypatch):
    args, output, _, writer, *_ = setup(
        tmp_path, monkeypatch, answers=("1", "EXPORT", "")
    )
    writer.side_effect = lambda root, p, path: committed(p, tmp_path / "surprise.csv")
    run(args)
    assert "Export Completed" not in output.getvalue()


@pytest.mark.parametrize("error", [ReturnToMainMenu, QuitPDS])
def test_navigation_propagates(tmp_path, monkeypatch, error):
    args, output, maker, writer, *_ = setup(tmp_path, monkeypatch)

    def raises(prompt=""):
        raise error

    args["input_fn"] = raises
    with pytest.raises(error):
        run(args)
    writer.assert_not_called()


def test_menu_appends_named_option_without_removing_advanced():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_planning_signal.py"
    ).read_text(encoding="utf-8")
    assert '"14. Export accepted Planning Signal to Core by name"' in source
    assert '"7. Advanced: Export accepted signal to Core"' in source
    assert '"7. Export accepted signal to Core"' in source
    assert "run_named_planning_core_export(" in source
    assert any(f'"Please choose 1-{n}, B, M, or Q."' in source for n in range(14, 100))
    assert '"Please choose 1-7, B, M, or Q."' in source


def test_controller_never_requests_canonical_ids_or_writes_directly():
    source = Path(named.__file__).read_text(encoding="utf-8")
    for token in (
        'read_choice(input_fn, "Class ID',
        'read_choice(input_fn, "Core signal-set ID',
        'read_choice(input_fn, "Planning preview ID',
        'read_choice(input_fn, "Review sha256',
        "write_grouping_signal(",
        "write_grouping_signal_export_receipt(",
        "select_grouping_signal_review_revision(",
        "export_grouping_signal_csv(",
        "commit_planning_signal_core_export(",
    ):
        assert token not in source
