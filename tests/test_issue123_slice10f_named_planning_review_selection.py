"""#123 Slice 10F: exact selected historical Planning Review by named preview."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_planning_review_selection as named

CLASS = "class_2"
YEAR = "2026-2027"
PREVIEW = "gsp_" + "a" * 64
PREVIEW_SHA = "b" * 64
DERIVATION = "gsd_" + "c" * 64
DERIVATION_SHA = "d" * 64
POLICY_SHA = "e" * 64
REVIEW_SHA = "f" * 64
WHEN = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def preview(**changes):
    data = dict(
        preview_id=PREVIEW,
        preview_sha256=PREVIEW_SHA,
        derivation_id=DERIVATION,
        derivation_sha256=DERIVATION_SHA,
        policy_id="policy_1",
        policy_revision=3,
        policy_sha256=POLICY_SHA,
        title="Reading Progress Groups",
        period_label="Marking Period 1",
        school_year=YEAR,
        period_id="mp1",
        calendar_revision=7,
        standard_id="RL.TS.11-12.4",
        dimension_id="readiness",
        band_count=3,
        roster_count=29,
        selected_review_revision=1,
        selected_review_sha256="1" * 64,
    )
    data.update(changes)
    return named.PlanningPreviewSummary(**data)


def review(**changes):
    data = dict(
        preview=preview(),
        revision=2,
        sha256=REVIEW_SHA,
        decision="accepted_for_export",
        reviewed_at=WHEN.isoformat(),
        selected_revision=1,
    )
    data.update(changes)
    return named.NamedPlanningReviewSummary(**data)


def projection():
    derivation = SimpleNamespace(
        class_id=CLASS, derivation_id=DERIVATION, derivation_sha256=DERIVATION_SHA
    )
    return SimpleNamespace(
        class_id=CLASS,
        preview_reference=SimpleNamespace(
            class_id=CLASS, preview_id=PREVIEW, preview_sha256=PREVIEW_SHA
        ),
        derivation_reference=derivation,
        policy_reference=SimpleNamespace(
            class_id=CLASS,
            policy_id="policy_1",
            policy_revision=3,
            policy_sha256=POLICY_SHA,
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
            selected_review_reference=SimpleNamespace(
                class_id=CLASS,
                derivation_id=DERIVATION,
                review_revision=1,
                review_sha256="1" * 64,
            ),
            decision="rejected",
            applicability=SimpleNamespace(status="not_accepted"),
        ),
    )


def plan(**changes):
    target_record = SimpleNamespace(
        class_id=CLASS,
        preview_reference=projection().preview_reference,
        derivation_reference=projection().derivation_reference,
        review_revision=2,
        decision="accepted_for_export",
        reviewed_at=WHEN,
    )
    target = SimpleNamespace(
        reference=SimpleNamespace(review_sha256=REVIEW_SHA),
        review=target_record,
    )
    data = dict(
        projection=projection(),
        target=target,
        class_id=CLASS,
        derivation_id=DERIVATION,
        target_review_revision=2,
        target_review_sha256=REVIEW_SHA,
        target_decision="accepted_for_export",
        expected_current_review_revision=1,
        target_applicability=SimpleNamespace(status="current"),
    )
    data.update(changes)
    return SimpleNamespace(**data)


def result(intent, **changes):
    data = dict(
        preview=intent,
        selected_review_revision=2,
        selected_review_sha256=REVIEW_SHA,
        selected_decision="accepted_for_export",
        previous_current_review_revision=1,
        selection_disposition="updated",
        review_selection_action="performed",
        review_write_action="not_performed",
        core_export_action="not_performed",
        csv_export_action="not_performed",
    )
    data.update(changes)
    return SimpleNamespace(**data)


def setup(
    tmp_path, monkeypatch, *, answers=("B",), chosen_preview=True, chosen_review=True
):
    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    navigation = MagicMock()
    navigation.current_class.return_value = scope
    parent = preview()
    item = review()
    previews = MagicMock()
    previews.inspect.return_value = parent
    catalog = MagicMock()
    catalog.inspect.return_value = item
    picks = [parent.choice() if chosen_preview else None]
    if chosen_preview:
        picks.append(item.choice() if chosen_review else None)
    chooser = MagicMock(side_effect=picks)
    preparer = MagicMock(return_value=plan())
    committer = MagicMock(side_effect=lambda root, i: result(i))
    monkeypatch.setattr(named, "_class", lambda *a, **kw: (tmp_path, CLASS))
    monkeypatch.setattr(named, "select_teacher_choice", chooser)
    monkeypatch.setattr(named, "_current_choice", MagicMock())
    prompts = []
    answers_iter = iter(answers)

    def user_input(prompt=""):
        prompts.append(prompt)
        return next(answers_iter, "")

    output = StringIO()
    args = dict(
        navigation=navigation,
        selection_preparer=preparer,
        selection_committer=committer,
        input_fn=user_input,
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        preview_catalog=previews,
        review_catalog=catalog,
    )
    return args, output, preparer, committer, catalog, previews, navigation, prompts


def run(args):
    named.run_named_planning_review_selection(**args)


def test_explicit_select_applies_exact_historical_revision(tmp_path, monkeypatch):
    args, output, preparer, committer, _, _, _, prompts = setup(
        tmp_path, monkeypatch, answers=("SELECT", "")
    )
    run(args)
    preparer.assert_called_once_with(
        tmp_path, CLASS, "policy_1", PREVIEW, PREVIEW_SHA, 2, REVIEW_SHA
    )
    committer.assert_called_once()
    assert "Planning Review Selected" in output.getvalue()
    assert REVIEW_SHA not in output.getvalue()
    assert not any("Review sha256:" in p for p in prompts)


@pytest.mark.parametrize("answer", ["B", "", "select", "yes", "WRITE", "1"])
def test_nonexact_confirmation_does_not_select(tmp_path, monkeypatch, answer):
    args, output, _, committer, *_ = setup(tmp_path, monkeypatch, answers=(answer, ""))
    run(args)
    committer.assert_not_called()
    assert "Planning Review Selected" not in output.getvalue()


def test_technical_details_opt_in(tmp_path, monkeypatch):
    args, output, _, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("T", "", "B")
    )
    run(args)
    assert "review_sha256: " + REVIEW_SHA in output.getvalue()
    committer.assert_not_called()


@pytest.mark.parametrize(
    "preview_chosen,review_chosen", [(False, False), (True, False)]
)
def test_cancel_in_selector_no_preparer(
    tmp_path, monkeypatch, preview_chosen, review_chosen
):
    args, _, preparer, committer, *_ = setup(
        tmp_path,
        monkeypatch,
        chosen_preview=preview_chosen,
        chosen_review=review_chosen,
    )
    run(args)
    preparer.assert_not_called()
    committer.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("school_year", "2025-2026"),
        ("preview_sha256", "0" * 64),
        ("selected_review_revision", 9),
    ],
)
def test_preview_witness_change_blocks(tmp_path, monkeypatch, field, value):
    args, output, preparer, committer, _, previews, *_ = setup(tmp_path, monkeypatch)
    previews.inspect.return_value = preview(**{field: value})
    run(args)
    preparer.assert_not_called()
    committer.assert_not_called()
    assert "changed" in output.getvalue().lower()


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha256", "0" * 64),
        ("decision", "rejected"),
        ("reviewed_at", "2025-01-01T00:00:00+00:00"),
        ("selected_revision", None),
    ],
)
def test_historical_review_witness_change_blocks(tmp_path, monkeypatch, field, value):
    args, output, preparer, committer, catalog, *_ = setup(tmp_path, monkeypatch)
    catalog.inspect.return_value = review(**{field: value})
    run(args)
    preparer.assert_not_called()
    committer.assert_not_called()
    assert "changed" in output.getvalue().lower()


@pytest.mark.parametrize(
    "field,value",
    [
        ("class_id", "other"),
        ("derivation_id", "wrong"),
        ("target_review_revision", 8),
        ("target_review_sha256", "0" * 64),
        ("target_decision", "rejected"),
        ("expected_current_review_revision", 9),
    ],
)
def test_mismatched_prepared_intent_blocks(tmp_path, monkeypatch, field, value):
    args, output, preparer, committer, *_ = setup(tmp_path, monkeypatch)
    preparer.return_value = plan(**{field: value})
    run(args)
    committer.assert_not_called()
    assert "Planning Review Selected" not in output.getvalue()


@pytest.mark.parametrize("status", ["current", "stale", "not_accepted"])
def test_displays_live_applicability_without_exporting(tmp_path, monkeypatch, status):
    args, output, preparer, committer, *_ = setup(tmp_path, monkeypatch, answers=("B",))
    prepared = plan(target_applicability=SimpleNamespace(status=status))
    preparer.return_value = prepared
    run(args)
    assert f"Live applicability: {status.replace('_', ' ')}" in output.getvalue()
    committer.assert_not_called()


def test_changed_class_blocks_before_preparation(tmp_path, monkeypatch):
    args, output, preparer, committer, _, _, navigation, _ = setup(
        tmp_path, monkeypatch
    )
    navigation.current_class.side_effect = [
        SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR),
        SimpleNamespace(workspace=tmp_path, class_id="other", school_year=YEAR),
    ]
    run(args)
    preparer.assert_not_called()
    committer.assert_not_called()


def test_change_at_confirmation_blocks_cas(tmp_path, monkeypatch):
    args, output, preparer, committer, catalog, *_ = setup(
        tmp_path, monkeypatch, answers=("SELECT", "")
    )
    calls = 0

    def change(*a):
        nonlocal calls
        calls += 1
        return review(sha256="0" * 64) if calls >= 4 else review()

    catalog.inspect.side_effect = change
    run(args)
    committer.assert_not_called()
    assert "Planning Review Selected" not in output.getvalue()


@pytest.mark.parametrize(
    "field,value",
    [
        ("selected_review_sha256", "0" * 64),
        ("selected_review_revision", 10),
        ("selected_decision", "rejected"),
        ("selection_disposition", "unreviewed"),
        ("review_selection_action", "not_performed"),
    ],
)
def test_result_mismatch_never_claims_selected(tmp_path, monkeypatch, field, value):
    args, output, preparer, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("SELECT", "")
    )
    committer.side_effect = lambda root, p: result(p, **{field: value})
    run(args)
    assert "Planning Review Selected" not in output.getvalue()
    assert "may have completed" in output.getvalue()


def test_committer_failure_expresses_uncertain_outcome(tmp_path, monkeypatch):
    args, output, _, committer, *_ = setup(
        tmp_path, monkeypatch, answers=("SELECT", "")
    )
    committer.side_effect = RuntimeError("private_review_identifier")
    run(args)
    assert "may have completed" in output.getvalue()
    assert "private_review_identifier" not in output.getvalue()


def test_preparer_failure_redacted(tmp_path, monkeypatch):
    args, output, preparer, committer, *_ = setup(tmp_path, monkeypatch)
    preparer.side_effect = RuntimeError("private_policy_identifier")
    run(args)
    committer.assert_not_called()
    assert "private_policy_identifier" not in output.getvalue()


@pytest.mark.parametrize("error", [QuitPDS, ReturnToMainMenu])
def test_navigation_propagates(tmp_path, monkeypatch, error):
    args, _, _, committer, *_ = setup(tmp_path, monkeypatch)

    def nav(*a, **kw):
        raise error

    monkeypatch.setattr(named, "select_teacher_choice", nav)
    with pytest.raises(error):
        run(args)
    committer.assert_not_called()


def stored_review(
    *,
    revision=2,
    decision="accepted_for_export",
    preview_id=PREVIEW,
    derivation_sha=DERIVATION_SHA,
):
    p = SimpleNamespace(
        class_id=CLASS,
        review_revision=revision,
        decision=decision,
        derivation_reference=SimpleNamespace(
            derivation_id=DERIVATION, derivation_sha256=derivation_sha
        ),
        preview_reference=SimpleNamespace(
            preview_id=preview_id, preview_sha256=PREVIEW_SHA
        ),
        reviewed_at=WHEN,
    )
    return SimpleNamespace(
        review=p,
        review_sha256=REVIEW_SHA,
        reference=SimpleNamespace(
            class_id=CLASS,
            derivation_id=DERIVATION,
            review_revision=revision,
            review_sha256=REVIEW_SHA,
        ),
    )


def storage_catalog(tmp_path, *, history=(1, 2), saved=None):
    navigation = MagicMock()
    navigation.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    previews = MagicMock()
    previews.inspect.return_value = preview()
    loader = MagicMock(
        side_effect=lambda root, cls, deriv, rev: stored_review(revision=rev)
    )
    readers = named.PlanningReviewSelectionReaders(
        lister=MagicMock(return_value=history),
        loader=loader,
        selected=MagicMock(return_value=1),
    )
    catalog = named.NamedPlanningReviewCatalog(navigation, previews, readers)
    return catalog, previews, readers, navigation


def test_catalog_lists_historical_revisions(tmp_path):
    catalog, _, _, _ = storage_catalog(tmp_path)
    choices = catalog.options(
        scope="planning_review_selection", selected={"class": CLASS, "preview": PREVIEW}
    )
    assert tuple(c.identity[1] for c in choices) == ("1", "2")
    assert all(len(c.witness or "") <= 256 for c in choices)
    assert all(REVIEW_SHA not in c.display for c in choices)


def test_catalog_skips_reviews_for_other_saved_preview(tmp_path):
    catalog, _, readers, _ = storage_catalog(tmp_path)

    def load(root, cls, deriv, revision):
        if revision == 1:
            return stored_review(revision=1, preview_id="gsp_other")
        return stored_review(revision=2)

    readers.loader.side_effect = load
    result = catalog.options(
        scope="planning_review_selection", selected={"class": CLASS, "preview": PREVIEW}
    )
    assert tuple(item.identity[1] for item in result) == ("2",)


@pytest.mark.parametrize(
    "revision,method",
    [
        ((), "lister"),
        (tuple(range(1, 202)), "lister"),
        ((1, 1), "lister"),
    ],
)
def test_catalog_inventory_controls(tmp_path, revision, method):
    catalog, _, readers, _ = storage_catalog(tmp_path)
    readers.lister.return_value = revision
    if revision == ():
        assert (
            catalog.options(
                scope="planning_review_selection",
                selected={"class": CLASS, "preview": PREVIEW},
            )
            == ()
        )
    else:
        with pytest.raises(named.TeacherChoiceUnavailable):
            catalog.options(
                scope="planning_review_selection",
                selected={"class": CLASS, "preview": PREVIEW},
            )


@pytest.mark.parametrize(
    "change",
    [
        "wrong_derivation",
        "wrong_review_digest",
        "wrong_preview_id",
        "selected_pointer_changed",
        "wrong_class",
    ],
)
def test_catalog_provenance_failure(tmp_path, change):
    catalog, _, readers, _ = storage_catalog(tmp_path)
    if change == "selected_pointer_changed":
        readers.selected.return_value = 9
    else:
        altered = stored_review()
        if change == "wrong_derivation":
            altered.review.derivation_reference.derivation_sha256 = "0" * 64
        elif change == "wrong_review_digest":
            altered.reference.review_sha256 = "0" * 64
        elif change == "wrong_preview_id":
            altered.review.preview_reference.preview_id = "gsp_another"
        elif change == "wrong_class":
            altered.review.class_id = "other"
        readers.loader.return_value = altered
        readers.loader.side_effect = None
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.inspect(tmp_path, CLASS, preview(), 2)


def test_catalog_rejects_wrong_year_and_scope(tmp_path):
    catalog, previews, _, _ = storage_catalog(tmp_path)
    previews.inspect.return_value = preview(school_year="2025-2026")
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(
            scope="planning_review_selection",
            selected={"class": CLASS, "preview": PREVIEW},
        )
    for selected in ({"class": "other", "preview": PREVIEW}, {"class": CLASS}):
        with pytest.raises(named.TeacherChoiceUnavailable):
            catalog.options(scope="planning_review_selection", selected=selected)


def test_menu_additive_and_advanced_stay_reachable():
    text = (
        Path(__file__).resolve().parents[1] / "meridian/menu_planning_signal.py"
    ).read_text(encoding="utf-8")
    assert '"13. Select a saved Planning Review by name"' in text
    assert "run_named_planning_review_selection(" in text
    assert '"6. Advanced: Select teacher review"' in text
    assert '"6. Select teacher review"' in text
    assert any(f'"Please choose 1-{n}, B, M, or Q."' in text for n in range(13, 100))


def test_controller_has_no_manual_ids_or_canonical_writes():
    text = Path(named.__file__).read_text(encoding="utf-8")
    for phrase in (
        'read_choice(input_fn, "Class ID',
        'read_choice(input_fn, "Review sha256',
        "select_grouping_signal_review_revision(",
        "write_grouping_signal_review_revision(",
        "commit_planning_signal_core_export(",
    ):
        assert phrase not in text
