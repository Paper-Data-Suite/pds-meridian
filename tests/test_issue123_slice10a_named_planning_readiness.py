"""#123 Slice 10A: teacher-named, selected-policy Planning Signal readiness."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

import meridian.menu_teacher_named_planning_readiness as named

CLASS = "english_12_pd2"
YEAR = "2026-2027"
POLICY = "private_policy_1"
DIGEST = "a" * 64


def summary(**changes):
    values = dict(
        policy_id=POLICY,
        policy_revision=3,
        policy_sha256=DIGEST,
        title="Reading progress groups",
        school_year=YEAR,
        period_label="Marking Period 1",
        period_id="mp1",
        calendar_revision=4,
        standard_id="RL.TS.11-12.4",
        dimension_id="readiness",
        band_count=4,
        revised_at="2026-10-25T16:00:00+00:00",
    )
    values.update(changes)
    return named.PlanningReadinessPolicySummary(**values)


def projection(**changes):
    s = summary()
    values = dict(
        class_id=CLASS,
        policy_id=POLICY,
        policy=SimpleNamespace(
            reference=SimpleNamespace(
                class_id=CLASS,
                policy_id=POLICY,
                policy_revision=3,
                policy_sha256=DIGEST,
            ),
            title=s.title,
            target_period=SimpleNamespace(
                period=SimpleNamespace(school_year=YEAR, period_id="mp1"),
                calendar_revision=4,
            ),
            standard_id=s.standard_id,
            dimension_id=s.dimension_id,
            band_count=s.band_count,
        ),
        generation_status="generated",
        blocker_codes=(),
        roster_student_count=29,
        contributing_student_count=25,
        noncontributing_student_count=4,
    )
    values.update(changes)
    return SimpleNamespace(**values)


def setup(tmp_path, monkeypatch, *, answers=("",)):
    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    navigation = MagicMock()
    navigation.current_class.return_value = scope
    catalog = MagicMock()
    catalog.inspect.return_value = summary()
    selected = summary().choice()
    picker = MagicMock(return_value=selected)
    projector = MagicMock(return_value=projection())
    monkeypatch.setattr(named, "_class", lambda *a, **k: (tmp_path, CLASS))
    monkeypatch.setattr(named, "select_teacher_choice", picker)
    monkeypatch.setattr(named, "_current_choice", MagicMock(return_value=selected))
    input_values = iter(answers)

    def get_input(prompt=""):
        return next(input_values, "")

    output = StringIO()
    arguments = dict(
        navigation=navigation,
        readiness_projector=projector,
        input_fn=get_input,
        output=output,
        clear_fn=lambda: None,
        class_catalog=MagicMock(),
        policy_catalog=catalog,
    )
    return arguments, output, projector, catalog, navigation, picker


def test_named_ready_policy_calls_existing_projector(tmp_path, monkeypatch):
    args, output, projector, _, _, picker = setup(tmp_path, monkeypatch)
    named.run_named_planning_readiness(**args)
    projector.assert_called_once_with(tmp_path, CLASS, POLICY)
    assert picker.call_args.kwargs["scope"] == "planning_readiness_policy"
    text = output.getvalue()
    assert "Reading progress groups" in text
    assert "25 contributing" in text
    assert "Readiness: generated" in text
    assert "Read-only: no derivation" in text
    assert POLICY not in text and DIGEST not in text


def test_technical_witness_only_after_explicit_t(tmp_path, monkeypatch):
    args, output, _, _, _, _ = setup(tmp_path, monkeypatch, answers=("T", "", "B"))
    named.run_named_planning_readiness(**args)
    text = output.getvalue()
    assert f"policy_sha256: {DIGEST}" in text
    assert f"policy_id: {POLICY}" in text


@pytest.mark.parametrize("step", ["class", "policy"])
def test_cancel_before_projection(tmp_path, monkeypatch, step):
    args, _, projector, _, _, picker = setup(tmp_path, monkeypatch)
    if step == "class":
        monkeypatch.setattr(named, "_class", lambda *a, **k: None)
    else:
        picker.return_value = None
    named.run_named_planning_readiness(**args)
    projector.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace", Path("/wrong")),
        ("class_id", "other"),
        ("school_year", "2025-2026"),
    ],
)
def test_changed_class_scope_blocks_projection(tmp_path, monkeypatch, field, value):
    args, output, projector, _, nav, _ = setup(tmp_path, monkeypatch)
    original = nav.current_class.return_value
    nav.current_class.side_effect = [
        original,
        SimpleNamespace(**{**vars(original), field: value}),
    ]
    named.run_named_planning_readiness(**args)
    projector.assert_not_called()
    assert "changed" in output.getvalue()


@pytest.mark.parametrize(
    "field,value",
    [
        ("policy_sha256", "b" * 64),
        ("policy_revision", 4),
        ("period_label", "Marking Period 2"),
        ("standard_id", "RL.CI.11-12.2"),
        ("school_year", "2025-2026"),
    ],
)
def test_changed_selected_policy_blocks_projection(tmp_path, monkeypatch, field, value):
    args, output, projector, catalog, _, _ = setup(tmp_path, monkeypatch)
    catalog.inspect.return_value = replace(summary(), **{field: value})
    named.run_named_planning_readiness(**args)
    projector.assert_not_called()
    assert "changed" in output.getvalue()


@pytest.mark.parametrize(
    "field,value",
    [
        ("class_id", "wrong"),
        ("policy_id", "wrong"),
        ("generation_status", "invalid\nstatus"),
        ("blocker_codes", ("private/path",)),
        ("roster_student_count", 30),
        ("noncontributing_student_count", 5),
    ],
)
def test_wrong_projector_result_never_displays_readiness(
    tmp_path, monkeypatch, field, value
):
    args, output, projector, _, _, _ = setup(tmp_path, monkeypatch)
    projector.return_value = projection(**{field: value})
    named.run_named_planning_readiness(**args)
    assert "Readiness: generated" not in output.getvalue()
    assert (
        "could not be verified" in output.getvalue() or "changed" in output.getvalue()
    )


def test_wrong_policy_projection_prevents_output(tmp_path, monkeypatch):
    args, output, projector, _, _, _ = setup(tmp_path, monkeypatch)
    value = projection()
    value.policy.reference.policy_sha256 = "b" * 64
    projector.return_value = value
    named.run_named_planning_readiness(**args)
    assert "Readiness: generated" not in output.getvalue()


def test_policy_change_after_projection_blocks_display(tmp_path, monkeypatch):
    args, output, projector, catalog, _, _ = setup(tmp_path, monkeypatch)
    catalog.inspect.side_effect = [summary(), summary(policy_revision=4)]
    named.run_named_planning_readiness(**args)
    projector.assert_called_once()
    assert "Readiness: generated" not in output.getvalue()


def test_blocked_status_shows_readable_codes(tmp_path, monkeypatch):
    args, output, projector, _, _, _ = setup(tmp_path, monkeypatch)
    projector.return_value = projection(
        generation_status="blocked",
        blocker_codes=("insufficient_current_proficiency",),
        roster_student_count=None,
        contributing_student_count=None,
        noncontributing_student_count=None,
    )
    named.run_named_planning_readiness(**args)
    assert "insufficient current proficiency" in output.getvalue()
    assert "Readiness: blocked" in output.getvalue()
    assert "Students:" not in output.getvalue()


def test_redacts_private_exception(tmp_path, monkeypatch):
    args, output, projector, _, _, _ = setup(tmp_path, monkeypatch)
    projector.side_effect = RuntimeError("C:/Sensitive/teacher/data/private.pdf")
    named.run_named_planning_readiness(**args)
    assert "private.pdf" not in output.getvalue()
    assert "could not be verified safely" in output.getvalue()


@pytest.mark.parametrize("nav_exception", [QuitPDS, ReturnToMainMenu])
def test_main_quit_preserved(tmp_path, monkeypatch, nav_exception):
    args, _, projector, _, _, _ = setup(tmp_path, monkeypatch)
    projector.side_effect = nav_exception
    with pytest.raises(nav_exception):
        named.run_named_planning_readiness(**args)


def test_choice_is_name_and_selected_digest_witness():
    choice = summary().choice()
    assert choice.identity == (POLICY,)
    assert choice.witness == f"3:{DIGEST}"
    assert POLICY not in choice.display
    assert DIGEST not in choice.display


def policy_storage_stub(**changes):
    s = summary()
    target = SimpleNamespace(
        period=SimpleNamespace(school_year=YEAR, period_id="mp1"),
        calendar_revision=4,
    )
    policy = SimpleNamespace(
        class_id=CLASS,
        policy_id=POLICY,
        policy_revision=3,
        title=s.title,
        academic_basis=SimpleNamespace(target_period=target, standard_id=s.standard_id),
        dimension_id=s.dimension_id,
        band_count=4,
        revised_at=datetime(2026, 10, 26, tzinfo=UTC),
    )
    record = SimpleNamespace(
        policy=policy,
        policy_sha256=DIGEST,
        reference=SimpleNamespace(
            class_id=CLASS,
            policy_id=POLICY,
            policy_revision=3,
            policy_sha256=DIGEST,
        ),
    )
    for name, value in changes.items():
        if name.startswith("ref_"):
            setattr(record.reference, name[4:], value)
        elif name.startswith("policy_"):
            setattr(policy, name[7:], value)
        else:
            setattr(record, name, value)
    return record


def storage_catalog(tmp_path, *, stored=None, school_year=YEAR):
    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=school_year)
    navigation = MagicMock()
    navigation.current_class.return_value = scope
    stored = policy_storage_stub() if stored is None else stored
    readers = named.PlanningReadinessPolicyReaders(
        lister=MagicMock(return_value=(POLICY,)),
        current_loader=MagicMock(return_value=stored),
        calendar_loader=MagicMock(return_value=SimpleNamespace()),
        period_lookup=MagicMock(
            return_value=SimpleNamespace(period_id="mp1", label="Marking Period 1")
        ),
    )
    return named.PlanningReadinessPolicyCatalog(navigation, readers), readers


def test_policy_catalog_uses_current_revision_and_calendar(tmp_path):
    catalog, readers = storage_catalog(tmp_path)
    items = catalog.options(
        scope="planning_readiness_policy", selected={"class": CLASS}
    )
    assert len(items) == 1
    assert items[0].label == "Reading progress groups"
    assert items[0].witness == f"3:{DIGEST}"
    readers.calendar_loader.assert_called_with(tmp_path, YEAR, 4)


def test_no_current_policy_is_not_auto_selected(tmp_path):
    catalog, readers = storage_catalog(tmp_path)
    readers.current_loader.return_value = None
    assert (
        catalog.options(scope="planning_readiness_policy", selected={"class": CLASS})
        == ()
    )


def test_old_school_year_is_filtered(tmp_path):
    catalog, _ = storage_catalog(tmp_path, school_year="2025-2026")
    assert (
        catalog.options(scope="planning_readiness_policy", selected={"class": CLASS})
        == ()
    )


@pytest.mark.parametrize(
    "incorrect",
    [
        {"ref_policy_revision": 4},
        {"ref_policy_sha256": "b" * 64},
        {"policy_class_id": "other"},
    ],
)
def test_catalog_rejects_wrong_current_reference(tmp_path, incorrect):
    catalog, _ = storage_catalog(tmp_path, stored=policy_storage_stub(**incorrect))
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="planning_readiness_policy", selected={"class": CLASS})


def test_catalog_rejects_wrong_period(tmp_path):
    catalog, readers = storage_catalog(tmp_path)
    readers.period_lookup.return_value = SimpleNamespace(
        period_id="mp2", label="Marking Period 2"
    )
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="planning_readiness_policy", selected={"class": CLASS})


@pytest.mark.parametrize("ids", [tuple(str(i) for i in range(201)), (POLICY, POLICY)])
def test_policy_catalog_rejects_unbounded_or_duplicate_inventory(tmp_path, ids):
    catalog, readers = storage_catalog(tmp_path)
    readers.lister.return_value = ids
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope="planning_readiness_policy", selected={"class": CLASS})


@pytest.mark.parametrize(
    "scope,selected",
    [
        ("other", {"class": CLASS}),
        ("planning_readiness_policy", {"class": "other"}),
        ("planning_readiness_policy", {}),
    ],
)
def test_catalog_rejects_wrong_scope(tmp_path, scope, selected):
    catalog, _ = storage_catalog(tmp_path)
    with pytest.raises(named.TeacherChoiceUnavailable):
        catalog.options(scope=scope, selected=selected)


def test_planning_menu_preserves_legacy_and_appends_named():
    menu = (
        Path(__file__).resolve().parents[1] / "meridian/menu_planning_signal.py"
    ).read_text(encoding="utf-8")
    assert '"8. Review Planning Signal readiness by policy name"' in menu
    assert "run_named_planning_readiness(" in menu
    for label in (
        "2. Advanced: Write exact derivation",
        "3. Advanced: Write planning preview",
        "5. Advanced: Write teacher review",
        "6. Advanced: Select teacher review",
        "7. Advanced: Export accepted signal to Core",
    ):
        assert f'"{label}"' in menu
    assert '"1. Review readiness"' in menu
    assert '"Please choose 1-7, B, M, or Q."' in menu
    assert '"Please choose 1-8, B, M, or Q."' in menu


def test_named_controller_never_writes_or_prompts_technical_ids():
    source = Path(named.__file__).read_text(encoding="utf-8")
    for forbidden in (
        'read_choice(input_fn, "Class ID',
        'read_choice(input_fn, "Grouping-signal policy ID',
        "commit_planning_signal",
        "select_grouping_signal_policy_revision",
        "write_grouping_signal",
        "export_grouping_signal",
    ):
        assert forbidden not in source
