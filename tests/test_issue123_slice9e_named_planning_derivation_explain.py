"""#123 Slice 9E: name-based immutable Planning Derivation explanations."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_explain_derivation as named

CLASS = "english_12_pd2"
YEAR = "2026-2027"
DERIVATION = "gsd_" + "a" * 64
DIGEST = "b" * 64
POLICY = "policy1"
POLICY_SHA = "c" * 64
FINGERPRINT = "d" * 64


def summary(**changes):
    initial = dict(
        derivation_id=DERIVATION,
        derivation_sha256=DIGEST,
        title="MP1 Contextual Groups",
        period_label="Marking Period 1",
        school_year=YEAR,
        standard_id="RL.TS.11-12.4",
        dimension_id="readiness",
        band_count=4,
        student_count=29,
        policy_id=POLICY,
        policy_revision=3,
        policy_sha256=POLICY_SHA,
        calculation_fingerprint=FINGERPRINT,
        revised_at="2026-10-25T15:00:00+00:00",
    )
    initial.update(changes)
    return named.PlanningDerivationSummary(**initial)


def explanation(**changes):
    data = dict(
        title="Planning Derivation Explanation",
        lines=(
            "Policy: MP1 Contextual Groups",
            "Academic Period: Marking Period 1",
            "Standard: RL.TS.11-12.4",
            "Dimension: readiness",
            "Bands: 4",
            "Roster students: 29",
            "Contributing students: 22",
            "Noncontributing students: 7",
        ),
        technical_lines=(
            f"class_id: {CLASS}",
            f"derivation_id: {DERIVATION}",
            f"derivation_sha256: {DIGEST}",
            "algorithm_version: academic_period_proficiency_band_v1",
            f"calculation_fingerprint: {FINGERPRINT}",
            f"policy_id: {POLICY}",
            "policy_revision: 3",
            f"policy_sha256: {POLICY_SHA}",
        ),
    )
    data.update(changes)
    return SimpleNamespace(**data)


def setup(tmp_path, monkeypatch, *, answers=("",)):
    navigation = MagicMock()
    chosen_class = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    navigation.current_class.return_value = chosen_class
    cat = MagicMock()
    item = summary()
    cat.inspect.return_value = item
    catalog = MagicMock()
    monkeypatch.setattr(named, "_class", lambda *_a, **_kw: (tmp_path, CLASS))
    monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: item.choice())
    current_choice = MagicMock()
    monkeypatch.setattr(named, "_current_choice", current_choice)
    reader = MagicMock(return_value=explanation())
    seq = iter(answers)

    def input_fn(prompt=""):
        if prompt == "Press Enter to continue...":
            return ""
        return next(seq)

    output = StringIO()
    params = dict(
        navigation=navigation,
        planning_derivation_explainer=reader,
        input_fn=input_fn,
        output=output,
        clear_fn=lambda: None,
        class_catalog=catalog,
        derivation_catalog=cat,
    )
    return params, navigation, reader, cat, current_choice, output


def test_named_derivation_uses_exact_readonly_reader(tmp_path, monkeypatch):
    args, navigation, reader, cat, checks, output = setup(tmp_path, monkeypatch)
    named.run_named_planning_derivation_explanation(**args)
    reader.assert_called_once_with(tmp_path, CLASS, DERIVATION)
    assert cat.inspect.call_count >= 3
    assert checks.call_count >= 3
    assert "MP1 Contextual Groups" in output.getvalue()
    assert "Marking Period 1" in output.getvalue()
    assert "Contributing students: 22" in output.getvalue()
    assert "A saved derivation is not a current grouping decision" in output.getvalue()
    assert DERIVATION not in output.getvalue()
    assert DIGEST not in output.getvalue()
    navigation.session.select_class.assert_not_called()
    navigation.session.select_student.assert_not_called()


def test_technical_details_require_explicit_t(tmp_path, monkeypatch):
    args, _, reader, _, _, output = setup(tmp_path, monkeypatch, answers=("t", ""))
    named.run_named_planning_derivation_explanation(**args)
    assert DIGEST in output.getvalue()
    assert "policy_id: " + POLICY in output.getvalue()
    reader.assert_called_once()


@pytest.mark.parametrize("step", ["class", "derivation"])
def test_back_before_selection_never_reads_provenance(tmp_path, monkeypatch, step):
    args, _, reader, _, _, _ = setup(tmp_path, monkeypatch)
    if step == "class":
        monkeypatch.setattr(named, "_class", lambda *_a, **_kw: None)
    else:
        monkeypatch.setattr(named, "select_teacher_choice", lambda **_kw: None)
    named.run_named_planning_derivation_explanation(**args)
    reader.assert_not_called()


def test_inconsistent_class_blocks_before_reader(tmp_path, monkeypatch):
    args, nav, reader, _, _, out = setup(tmp_path, monkeypatch)
    nav.current_class.return_value.class_id = "other"
    named.run_named_planning_derivation_explanation(**args)
    reader.assert_not_called()
    assert "changed" in out.getvalue()


def test_missing_class_blocks_before_reader(tmp_path, monkeypatch):
    args, nav, reader, _, _, out = setup(tmp_path, monkeypatch)
    nav.current_class.return_value = None
    named.run_named_planning_derivation_explanation(**args)
    reader.assert_not_called()
    assert "changed" in out.getvalue()


def test_change_in_choice_blocks_before_reader(tmp_path, monkeypatch):
    args, _, reader, _, checks, out = setup(tmp_path, monkeypatch)
    checks.side_effect = named._ScopeChanged("stale")
    named.run_named_planning_derivation_explanation(**args)
    reader.assert_not_called()
    assert "changed" in out.getvalue()


@pytest.mark.parametrize(
    "change",
    [
        {"derivation_sha256": "e" * 64},
        {"policy_sha256": "f" * 64},
        {"derivation_id": "gsd_" + "e" * 64},
        {"school_year": "2025-2026"},
    ],
)
def test_changed_exact_witness_blocks_before_read(tmp_path, monkeypatch, change):
    args, _, reader, cat, _, out = setup(tmp_path, monkeypatch)
    cat.inspect.return_value = summary(**change)
    named.run_named_planning_derivation_explanation(**args)
    reader.assert_not_called()
    assert "changed" in out.getvalue()


@pytest.mark.parametrize(
    "change",
    [
        {"title": "Other explanation"},
        {"lines": ("Unexpected raw student ID",)},
        {"lines": explanation().lines[:-1]},
        {"technical_lines": ()},
        {"technical_lines": ("class_id: another",)},
        {
            "lines": explanation().lines[:-2]
            + ("Contributing students: 24", "Noncontributing students: 7")
        },
        {
            "lines": explanation().lines[:-2]
            + ("Contributing students: 2x", "Noncontributing students: 7")
        },
        {
            "lines": explanation().lines[:-2]
            + ("Contributing students: 022", "Noncontributing students: 7")
        },
    ],
)
def test_mismatched_provenance_is_not_displayed(tmp_path, monkeypatch, change):
    args, _, reader, _, _, out = setup(tmp_path, monkeypatch)
    reader.return_value = explanation(**change)
    named.run_named_planning_derivation_explanation(**args)
    assert "Contributing students: 22" not in out.getvalue()
    assert "changed" in out.getvalue()


def test_class_change_during_read_blocks_display(tmp_path, monkeypatch):
    args, nav, reader, _, _, out = setup(tmp_path, monkeypatch)
    original = nav.current_class.return_value
    nav.current_class.side_effect = [original, original, None]
    named.run_named_planning_derivation_explanation(**args)
    reader.assert_called_once()
    assert "Contributing students: 22" not in out.getvalue()


def test_derivation_change_during_read_blocks_display(tmp_path, monkeypatch):
    args, _, reader, cat, _, out = setup(tmp_path, monkeypatch)
    cat.inspect.side_effect = [summary(), summary(derivation_sha256="e" * 64)]
    named.run_named_planning_derivation_explanation(**args)
    reader.assert_called_once()
    assert "Contributing students: 22" not in out.getvalue()


def test_errors_redact_private_path(tmp_path, monkeypatch):
    args, _, reader, _, _, out = setup(tmp_path, monkeypatch)
    reader.side_effect = RuntimeError("private/student/files")
    named.run_named_planning_derivation_explanation(**args)
    assert "private/student" not in out.getvalue()
    assert "could not be verified" in out.getvalue()


@pytest.mark.parametrize("exc", [ReturnToMainMenu, QuitPDS])
def test_shared_navigation_propagates(tmp_path, monkeypatch, exc):
    args, _, reader, _, _, _ = setup(tmp_path, monkeypatch)
    reader.side_effect = exc
    with pytest.raises(exc):
        named.run_named_planning_derivation_explanation(**args)


def test_summary_name_and_witness_are_distinct():
    item = summary()
    choice = item.choice()
    assert choice.identity == (DERIVATION,)
    assert choice.label == item.title
    assert choice.witness == DIGEST + ":" + POLICY_SHA
    assert DERIVATION not in choice.display
    assert DIGEST not in choice.display


def storage_stubs(*, wrong_policy=False, old_year=False):
    policy_ref = SimpleNamespace(
        class_id=CLASS, policy_id=POLICY, policy_revision=3, policy_sha256=POLICY_SHA
    )
    snapshot = SimpleNamespace(
        class_id=CLASS,
        derivation_id=DERIVATION,
        policy_reference=policy_ref,
        dimension_id="readiness",
        band_count=4,
        student_derivations=(1,) * 29,
        calculation_fingerprint=FINGERPRINT,
    )
    stored = SimpleNamespace(
        snapshot=snapshot,
        derivation_sha256=DIGEST,
        reference=SimpleNamespace(
            class_id=CLASS, derivation_id=DERIVATION, derivation_sha256=DIGEST
        ),
    )
    period_ref = SimpleNamespace(
        school_year="2025-2026" if old_year else YEAR,
        period_id="mp1",
    )
    basis = SimpleNamespace(
        target_period=SimpleNamespace(period=period_ref, calendar_revision=7),
        standard_id="RL.TS.11-12.4",
    )
    policy = SimpleNamespace(
        class_id=CLASS,
        policy_id=POLICY,
        policy_revision=3,
        academic_basis=basis,
        dimension_id="readiness",
        band_count=4,
        title="MP1 Contextual Groups",
        revised_at=SimpleNamespace(isoformat=lambda: "2026-10-25T15:00:00+00:00"),
    )
    linked = SimpleNamespace(
        reference=policy_ref
        if not wrong_policy
        else SimpleNamespace(policy_id="other"),
        policy=policy,
    )
    readers = named.PlanningDerivationReaders(
        lister=lambda *_: (DERIVATION,),
        derivation_loader=lambda *_: stored,
        policy_loader=lambda *_: linked,
        calendar_loader=lambda *_: object(),
        period_lookup=lambda *_: SimpleNamespace(
            period_id="mp1", label="Marking Period 1"
        ),
    )
    return readers


def test_verified_catalog_returns_human_labels(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    cat = named.PlanningDerivationChoiceCatalog(nav, storage_stubs())
    assert cat.options(scope="planning_derivation", selected={"class": CLASS}) == (
        summary().choice(),
    )


def test_catalog_filters_unrelated_school_year(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    cat = named.PlanningDerivationChoiceCatalog(nav, storage_stubs(old_year=True))
    assert cat.options(scope="planning_derivation", selected={"class": CLASS}) == ()


@pytest.mark.parametrize("scope", ["wrong", "", "student"])
def test_catalog_rejects_wrong_scope(tmp_path, scope):
    cat = named.PlanningDerivationChoiceCatalog(MagicMock(), storage_stubs())
    with pytest.raises(named.TeacherChoiceUnavailable):
        cat.options(scope=scope, selected={"class": CLASS})


def test_catalog_rejects_modified_policy(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    cat = named.PlanningDerivationChoiceCatalog(nav, storage_stubs(wrong_policy=True))
    with pytest.raises(named.TeacherChoiceUnavailable):
        cat.options(scope="planning_derivation", selected={"class": CLASS})


def test_catalog_rejects_more_than_200_records(tmp_path):
    nav = MagicMock()
    nav.current_class.return_value = SimpleNamespace(
        workspace=tmp_path, class_id=CLASS, school_year=YEAR
    )
    readers = replace(
        storage_stubs(), lister=lambda *_: tuple(f"gsd_{i:064x}" for i in range(201))
    )
    with pytest.raises(named.TeacherChoiceUnavailable):
        named.PlanningDerivationChoiceCatalog(nav, readers).options(
            scope="planning_derivation", selected={"class": CLASS}
        )


def test_menu_appends_route_without_replacing_advanced():
    source = (
        Path(__file__).resolve().parents[1] / "meridian/menu_explain.py"
    ).read_text(encoding="utf-8")
    assert '"13. Explain a saved Planning Derivation by name"' in source
    assert "run_named_planning_derivation_explanation(" in source
    assert '"12. Explain Academic Period proficiency by name"' in source
    assert '"5. Planning derivation"' in source
    assert '"5. Advanced: Planning derivation"' in source
    assert any(
        f'"Please choose 1-{end}, B, M, or Q."' in source for end in range(13, 100)
    )
    assert '"Please choose 1-8, B, M, or Q."' in source


def test_controller_has_no_raw_identifiers_or_mutation():
    source = Path(named.__file__).read_text(encoding="utf-8")
    for disallowed in (
        'read_choice(input_fn, "Class ID',
        'read_choice(input_fn, "Derivation ID',
        'read_choice(input_fn, "SHA',
        '"write_"',
        "commit_planning",
        "select_current_",
    ):
        assert disallowed not in source
