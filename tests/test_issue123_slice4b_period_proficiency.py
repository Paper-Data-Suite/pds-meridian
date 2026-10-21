"""#123 Slice 4B: selected period results only; no grade/selection writes."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from meridian.menu_teacher_named_period import run_named_period_proficiency
from meridian.teacher_navigation_choices import (
    TeacherChoiceUnavailable,
    load_teacher_choices,
)
from meridian.teacher_navigation_domain import (
    TeacherAcademicChoiceCatalog,
    TeacherAcademicChoiceReaders,
)
from meridian.teacher_navigation_period import (
    PeriodChoiceReaders,
    PeriodProficiencyChoiceCatalog,
)
from meridian.teacher_session import TeacherSessionContext

YEAR = "2026-2027"
CLASS = "english-12"
STUDENT = "opaque-student"
STANDARD = "RL.CR.11-12.1"
PERIOD = "mp-1"


def fixture(tmp_path: Path):
    session = TeacherSessionContext()
    session.select_class(CLASS)
    nav = MagicMock()
    nav.session = session
    scope = SimpleNamespace(workspace=tmp_path, class_id=CLASS, school_year=YEAR)
    period_scope = SimpleNamespace(
        workspace=tmp_path,
        class_id=CLASS,
        school_year=YEAR,
        period_id=PERIOD,
        calendar_revision=2,
        label="First Marking Period",
    )
    nav.current_class.return_value = scope
    nav.verify_class.return_value = scope
    nav.current_period.return_value = period_scope
    nav.verify_period.return_value = period_scope
    nav.choose_period.return_value = period_scope
    nav.readers.workspace_resolver.return_value = tmp_path
    nav.readers.active_year_loader.return_value = YEAR
    nav.readers.roster_loader.return_value = SimpleNamespace(
        class_id=CLASS,
        students=(
            SimpleNamespace(
                student_id=STUDENT,
                first_name="Alex",
                last_name="Rivera",
                period="2",
                extra_fields={},
            ),
        ),
    )
    entry = SimpleNamespace(
        school_year=YEAR,
        calendar_revision=2,
        is_current_calendar=True,
        calendar_updated_at=SimpleNamespace(isoformat=lambda: "2026-09-01T12:00:00Z"),
        period=SimpleNamespace(
            period_id=PERIOD,
            period_type="marking_period",
            lifecycle="open",
            label="First Marking Period",
            start_date=SimpleNamespace(isoformat=lambda: "2026-09-07"),
            end_date=SimpleNamespace(isoformat=lambda: "2026-11-06"),
        ),
    )
    nav.readers.period_lister.return_value = (entry,)
    selected = SimpleNamespace(
        snapshot=SimpleNamespace(
            class_id=CLASS,
            student_id=STUDENT,
            standard_id=STANDARD,
            result_revision=3,
            target_period=SimpleNamespace(
                period=SimpleNamespace(school_year=YEAR, period_id=PERIOD),
                calendar_revision=2,
            ),
        ),
        result_sha256="b" * 64,
    )
    standard_lister = MagicMock(return_value=(STANDARD,))
    stored_loader = MagicMock(return_value=selected)
    period_catalog = PeriodProficiencyChoiceCatalog(
        nav,
        PeriodChoiceReaders(
            standard_lister=standard_lister,
            result_loader=stored_loader,
        ),
    )
    academic_catalog = TeacherAcademicChoiceCatalog(
        nav,
        TeacherAcademicChoiceReaders(
            class_lister=lambda _root: (),
            grade_item_reviewer=MagicMock(),
            result_identity_lister=MagicMock(),
            result_loader=MagicMock(),
        ),
    )
    return nav, academic_catalog, period_catalog, standard_lister, stored_loader


def answers(*values: str):
    iterable = iter(values)
    return lambda _: next(iterable)


def test_period_is_named_dated_and_carries_hidden_exact_witness(
    tmp_path: Path,
) -> None:
    _, _, period_catalog, _, _ = fixture(tmp_path)
    choices = load_teacher_choices(
        period_catalog, scope="period", selected={"class": CLASS}
    )
    assert len(choices) == 1
    assert choices[0].identity == (PERIOD,)
    assert "First Marking Period" in choices[0].display
    assert "2026-09-07 to 2026-11-06" in choices[0].display
    assert "mp-1" not in choices[0].display
    assert "2026-2027:2:" in str(choices[0].witness)


def test_period_standard_requires_exact_student_period_and_selected_pointer(
    tmp_path: Path,
) -> None:
    _, _, catalog, _, loader = fixture(tmp_path)
    context = {"class": CLASS, "period": PERIOD, "student": STUDENT}
    choices = load_teacher_choices(catalog, scope="period_standard", selected=context)
    assert choices[0].identity == (STANDARD,)
    assert "b" * 64 not in choices[0].display
    loader.return_value = None
    assert (
        load_teacher_choices(catalog, scope="period_standard", selected=context) == ()
    )


def test_foreign_class_and_departed_roster_student_fail_closed(tmp_path: Path) -> None:
    nav, _, catalog, lister, _ = fixture(tmp_path)
    with pytest.raises(TeacherChoiceUnavailable):
        load_teacher_choices(catalog, scope="period", selected={"class": "other"})
    with pytest.raises(TeacherChoiceUnavailable):
        load_teacher_choices(
            catalog,
            scope="period_standard",
            selected={"class": CLASS, "period": PERIOD, "student": "not-in-class"},
        )
    lister.assert_not_called()
    nav.current_period.return_value = None
    with pytest.raises(TeacherChoiceUnavailable):
        load_teacher_choices(
            catalog,
            scope="period_standard",
            selected={"class": CLASS, "period": PERIOD, "student": STUDENT},
        )


def test_stale_calendar_or_result_state_is_never_offered(
    tmp_path: Path,
) -> None:
    nav, _, catalog, _, loader = fixture(tmp_path)
    context = {"class": CLASS, "period": PERIOD, "student": STUDENT}
    loader.return_value.snapshot.target_period.calendar_revision = 1
    with pytest.raises(TeacherChoiceUnavailable, match="does not match"):
        catalog.options(scope="period_standard", selected=context)
    nav.readers.period_lister.return_value[0].calendar_revision = 3
    with pytest.raises(TeacherChoiceUnavailable, match="changed"):
        catalog.options(scope="period", selected={"class": CLASS})


def test_duplicate_standard_histories_and_unbounded_list_block(
    tmp_path: Path,
) -> None:
    _, _, catalog, lister, _ = fixture(tmp_path)
    context = {"class": CLASS, "period": PERIOD, "student": STUDENT}
    lister.return_value = (STANDARD, STANDARD)
    with pytest.raises(TeacherChoiceUnavailable, match="repeats"):
        catalog.options(scope="period_standard", selected=context)
    lister.return_value = tuple(f"standard-{i}" for i in range(501))
    with pytest.raises(TeacherChoiceUnavailable, match="bound"):
        catalog.options(scope="period_standard", selected=context)


def test_named_period_result_keeps_canonical_student_id_off_screen(
    tmp_path: Path,
) -> None:
    nav, academic, catalog, _, _ = fixture(tmp_path)
    out = StringIO()
    explanation = MagicMock(
        return_value=SimpleNamespace(
            status="calculated",
            proficiency_label="Meeting",
            policy_title="Quarter policy",
            scale_title="Four-level scale",
        )
    )
    run_named_period_proficiency(
        navigation=nav,
        catalog=academic,
        period_catalog=catalog,
        load_proficiency=explanation,
        input_fn=answers("1", "1", "1", ""),
        output=out,
        clear_fn=lambda: None,
    )
    value = out.getvalue()
    assert "First Marking Period" in value
    assert "Alex Rivera" in value
    assert "Current proficiency: Meeting" in value
    assert STUDENT not in value
    assert "b" * 64 not in value
    assert nav.session.active_student_id == STUDENT
    explanation.assert_called_once_with(
        tmp_path, CLASS, YEAR, PERIOD, STUDENT, STANDARD
    )


def test_explanation_failure_is_safe_and_does_not_select_student(
    tmp_path: Path,
) -> None:
    nav, academic, catalog, _, _ = fixture(tmp_path)
    out = StringIO()
    explanation = MagicMock(side_effect=RuntimeError("protected source revoked"))
    run_named_period_proficiency(
        navigation=nav,
        catalog=academic,
        period_catalog=catalog,
        load_proficiency=explanation,
        input_fn=answers("1", "1", "1", ""),
        output=out,
        clear_fn=lambda: None,
    )
    assert "could not be verified safely" in out.getvalue()
    assert "protected source revoked" not in out.getvalue()
    assert nav.session.active_student_id is None


def test_cancel_before_student_and_main_quit_unwind_without_writes(
    tmp_path: Path,
) -> None:
    from pds_core.menu_navigation import QuitPDS, ReturnToMainMenu

    nav, academic, catalog, _, _ = fixture(tmp_path)
    loader = MagicMock()
    run_named_period_proficiency(
        navigation=nav,
        catalog=academic,
        period_catalog=catalog,
        load_proficiency=loader,
        input_fn=answers("1", "B"),
        output=StringIO(),
        clear_fn=lambda: None,
    )
    loader.assert_not_called()
    for command, exception in (("M", ReturnToMainMenu), ("Q", QuitPDS)):
        with pytest.raises(exception):
            run_named_period_proficiency(
                navigation=nav,
                catalog=academic,
                period_catalog=catalog,
                load_proficiency=loader,
                input_fn=answers(command),
                output=StringIO(),
                clear_fn=lambda: None,
            )


def test_menu_2_has_named_composed_path_and_keeps_explicit_direct_compatibility() -> (
    None
):
    source = Path(__file__).resolve().parents[1] / "meridian/menu_proficiency.py"
    text = source.read_text(encoding="utf-8")
    assert "run_named_period_proficiency(" in text
    assert "if navigation_context is not None:" in text
    assert '"2. Review current Academic Period proficiency by name"' in text
    assert "_review_academic_period(" in text
    assert '"7. Advanced: Preview Academic Period calculation"' in text


def test_selector_redacts_internal_period_catalog_failure(tmp_path: Path) -> None:
    _, _, catalog, _, loader = fixture(tmp_path)
    loader.return_value.snapshot.target_period.calendar_revision = 1
    with pytest.raises(
        TeacherChoiceUnavailable,
        match=r"^Verified choices could not be listed\.$",
    ) as failure:
        load_teacher_choices(
            catalog,
            scope="period_standard",
            selected={"class": CLASS, "period": PERIOD, "student": STUDENT},
        )
    assert isinstance(failure.value.__cause__, TeacherChoiceUnavailable)
    assert "does not match" in str(failure.value.__cause__)
