"""#123 Slice 11C: adverse teacher catalog and read-only route acceptance.

Real selector, navigation, Grade Item and proficiency controllers are invoked.
Synthetic authoritative readers stand in for Core and domain storage; this
slice does not claim protected-publication or installed-wheel acceptance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from meridian.menu_teacher_named_review import (
    run_named_grade_item_proficiency,
    run_named_grade_item_review,
)
from meridian.teacher_navigation_choices import (
    TeacherChoice,
    TeacherChoiceUnavailable,
    load_teacher_choices,
)
from meridian.teacher_navigation_context import (
    TeacherNavigationContext,
    TeacherNavigationReaders,
)
from meridian.teacher_navigation_terminal import select_teacher_choice
from meridian.teacher_session import TeacherSessionContext

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/architecture/issue123-slice11c-adversarial-matrix.json"


@dataclass
class Answers:
    items: list[str]
    prompts: list[str] = field(default_factory=list)

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        if not self.items:
            raise AssertionError("Unexpected teacher input prompt: " + prompt)
        return self.items.pop(0)


@dataclass
class CoreStub:
    root: Path
    school_year: str = "2026-2027"
    metadata_year: str = "2026-2027"
    workspace: Path | None = None
    fail_roster: bool = False
    reads: dict[str, int] = field(default_factory=dict)

    def record(self, key: str) -> None:
        self.reads[key] = self.reads.get(key, 0) + 1

    def root_reader(self) -> Path:
        self.record("workspace")
        return self.workspace or self.root

    def year_reader(self, root: Path) -> str:
        self.record("year")
        return self.school_year

    def metadata_reader(self, root: Path, class_id: str) -> SimpleNamespace:
        self.record("metadata")
        return SimpleNamespace(class_id=class_id, school_year=self.metadata_year)

    def roster_reader(self, root: Path, class_id: str) -> SimpleNamespace:
        self.record("roster")
        if self.fail_roster:
            raise PermissionError("private student roster details")
        return SimpleNamespace(class_id=class_id, students=())

    def period_reader(self, root: Path, year: str) -> tuple[object, ...]:
        self.record("period")
        return ()


def navigation(tmp_path: Path) -> tuple[TeacherNavigationContext, CoreStub]:
    stub = CoreStub(root=tmp_path)
    nav = TeacherNavigationContext(
        session=TeacherSessionContext(),
        readers=TeacherNavigationReaders(
            workspace_resolver=stub.root_reader,
            active_year_loader=stub.year_reader,
            class_metadata_loader=stub.metadata_reader,
            roster_loader=stub.roster_reader,
            period_lister=stub.period_reader,  # type: ignore[arg-type]
        ),
    )
    nav.choose_class("class_12")
    return nav, stub


@dataclass
class Catalog:
    drift: str = ""
    drift_at: int = 99
    unauthorized: str = ""
    bad_duplicate: bool = False
    calls: dict[str, int] = field(default_factory=dict)

    def options(self, *, scope: str, selected: Any) -> tuple[TeacherChoice, ...]:
        self.calls[scope] = self.calls.get(scope, 0) + 1
        if scope == self.unauthorized:
            raise PermissionError("private record/token/binding")
        assert selected.get("class") == "class_12"
        if scope == "grade_item":
            result = TeacherChoice(
                ("item_01",),
                "Atlas Project",
                "Active assignment",
                witness="grade-revision-1",
            )
        elif scope == "student":
            assert selected.get("grade_item") in (None, "item_01")
            result = TeacherChoice(
                ("student_07",),
                "José García",
                "English 12, roster 07",
                witness="roster-revision-1",
            )
        elif scope == "standard":
            assert selected.get("student") == "student_07"
            result = TeacherChoice(
                ("standard_1",),
                "RL.CS.11–12.4",
                "Current selected result",
                witness="proficiency-revision-1",
            )
        else:
            raise AssertionError("Unexpected domain scope: " + scope)
        if self.bad_duplicate and scope == "student":
            return (result, TeacherChoice(("student_21",), result.label, result.detail))
        if scope == self.drift and self.calls[scope] >= self.drift_at:
            result = TeacherChoice(
                result.identity,
                result.label,
                result.detail,
                witness="changed-source-currentness",
            )
        return (result,)


def grade_review(
    class_id: str = "class_12", *, available: bool = True
) -> SimpleNamespace:
    return SimpleNamespace(
        class_id=class_id,
        items=(
            SimpleNamespace(
                grade_item_id="item_01" if available else "other_item",
                title="Atlas Project",
                status="active",
                selection_state="selected",
                purpose="assessment",
                memberships=(),
            ),
        ),
    )


def show_grade(
    nav: TeacherNavigationContext,
    catalog: Catalog,
    reader: Any,
    answers: Answers,
) -> StringIO:
    output = StringIO()
    run_named_grade_item_review(
        navigation=nav,
        catalog=catalog,
        review_loader=reader,
        input_fn=answers,
        output=output,
        clear_fn=lambda: None,
    )
    return output


def show_proficiency(
    nav: TeacherNavigationContext,
    catalog: Catalog,
    reader: Any,
    answers: Answers,
) -> StringIO:
    output = StringIO()
    run_named_grade_item_proficiency(
        navigation=nav,
        catalog=catalog,
        load_proficiency=reader,
        input_fn=answers,
        output=output,
        clear_fn=lambda: None,
    )
    return output


def proficiency_result() -> SimpleNamespace:
    return SimpleNamespace(
        status="current",
        proficiency_label="Meeting",
        policy_title="Class rubric",
        scale_title="Four-level scale",
    )


def test_named_grade_item_success_is_read_only_and_remembers_verified_choice(
    tmp_path: Path,
) -> None:
    nav, core = navigation(tmp_path)
    read_calls: list[tuple[Path, str]] = []

    def read(root: Path, class_id: str) -> SimpleNamespace:
        read_calls.append((root, class_id))
        return grade_review()

    typed = Answers(["1", ""])
    result = show_grade(nav, Catalog(), read, typed)
    assert read_calls == [(tmp_path, "class_12")]
    assert nav.session.active_grade_item_id == "item_01"
    assert nav.session.active_student_id is None
    assert "Read-only. No Grade Item revision" in result.getvalue()
    assert not any("item_01" in item for item in typed.prompts)
    assert core.reads["roster"] >= 2


@pytest.mark.parametrize("variant", ["wrong_class", "missing_item", "changed_choice"])
def test_grade_item_wrong_or_changed_provenance_never_updates_session(
    tmp_path: Path,
    variant: str,
) -> None:
    nav, _ = navigation(tmp_path)
    catalog = (
        Catalog(drift="grade_item", drift_at=3)
        if variant == "changed_choice"
        else Catalog()
    )
    calls: list[str] = []

    def read(root: Path, class_id: str) -> SimpleNamespace:
        calls.append(class_id)
        if variant == "wrong_class":
            return grade_review("other_class")
        return grade_review(available=variant != "missing_item")

    screen = show_grade(nav, catalog, read, Answers(["1", ""]))
    assert calls == ["class_12"]
    assert nav.session.active_grade_item_id is None
    assert "could not be reverified safely" in screen.getvalue()


def test_grade_item_authoritative_year_change_blocks_read(
    tmp_path: Path,
) -> None:
    nav, core = navigation(tmp_path)
    core.metadata_year = "2025-2026"
    calls: list[str] = []
    screen = show_grade(nav, Catalog(), lambda *_: calls.append("read"), Answers([""]))
    assert not calls
    assert "could not be reverified safely" in screen.getvalue()
    assert nav.session.active_grade_item_id is None


def test_grade_item_unavailable_roster_blocks_read_and_redacts_error(
    tmp_path: Path,
) -> None:
    nav, core = navigation(tmp_path)
    core.fail_roster = True
    calls: list[str] = []
    screen = show_grade(nav, Catalog(), lambda *_: calls.append("read"), Answers([""]))
    assert not calls
    assert "private student roster details" not in screen.getvalue()
    assert "could not be reverified safely" in screen.getvalue()


def test_grade_item_source_permission_denial_does_not_invoke_reader(
    tmp_path: Path,
) -> None:
    nav, _ = navigation(tmp_path)
    calls: list[str] = []
    screen = show_grade(
        nav,
        Catalog(unauthorized="grade_item"),
        lambda *_: calls.append("read"),
        Answers([]),
    )
    assert not calls
    assert "private record" not in screen.getvalue()
    assert nav.session.active_grade_item_id is None


def test_named_proficiency_success_reads_exact_selected_result(
    tmp_path: Path,
) -> None:
    nav, _ = navigation(tmp_path)
    calls: list[tuple[Any, ...]] = []

    def read(*args: Any) -> SimpleNamespace:
        calls.append(args)
        return proficiency_result()

    catalog = Catalog()
    screen = show_proficiency(nav, catalog, read, Answers(["1", "1", "1", ""]))
    assert calls == [(tmp_path, "class_12", "item_01", "student_07", "standard_1")]
    assert nav.session.active_grade_item_id == "item_01"
    assert nav.session.active_student_id == "student_07"
    assert "Current proficiency: Meeting" in screen.getvalue()
    assert "No Grade or proficiency was created" in screen.getvalue()
    assert catalog.calls == {"grade_item": 3, "student": 3, "standard": 4}


@pytest.mark.parametrize("drift", ["grade_item", "student", "standard"])
def test_changed_proficiency_scope_never_silently_retargets(
    tmp_path: Path,
    drift: str,
) -> None:
    nav, _ = navigation(tmp_path)
    calls: list[str] = []
    # First two list reads make the named selection; subsequent guard detects drift.
    catalog = Catalog(drift=drift, drift_at=3)
    screen = show_proficiency(
        nav,
        catalog,
        lambda *_: calls.append("read"),
        Answers(["1", "1", "1", ""]),
    )
    assert calls == []
    assert nav.session.active_student_id is None
    assert nav.session.active_grade_item_id is None
    assert "could not be verified" in screen.getvalue()


def test_revoked_proficiency_evidence_reader_does_not_update_selected_context(
    tmp_path: Path,
) -> None:
    nav, _ = navigation(tmp_path)
    calls: list[str] = []

    def denied(*args: Any) -> None:
        calls.append("denied")
        raise PermissionError("private publication bearer token")

    screen = show_proficiency(nav, Catalog(), denied, Answers(["1", "1", "1", ""]))
    assert calls == ["denied"]
    assert nav.session.active_grade_item_id is None
    assert nav.session.active_student_id is None
    assert "private publication bearer token" not in screen.getvalue()
    assert "could not be verified" in screen.getvalue()


def test_proficiency_reader_changes_selected_standard_after_read(
    tmp_path: Path,
) -> None:
    nav, _ = navigation(tmp_path)
    catalog = Catalog(drift="standard", drift_at=4)
    calls: list[str] = []

    def reader(*args: Any) -> SimpleNamespace:
        calls.append("read")
        return proficiency_result()

    screen = show_proficiency(nav, catalog, reader, Answers(["1", "1", "1", ""]))
    assert calls == ["read"]
    assert nav.session.active_grade_item_id is None
    assert nav.session.active_student_id is None
    assert "could not be verified" in screen.getvalue()


def test_proficiency_no_student_permission_does_not_infer_result(
    tmp_path: Path,
) -> None:
    nav, _ = navigation(tmp_path)
    called: list[str] = []
    screen = show_proficiency(
        nav,
        Catalog(unauthorized="student"),
        lambda *_: called.append("read"),
        Answers(["1"]),
    )
    assert called == []
    assert nav.session.active_student_id is None
    assert "could not be verified safely" in screen.getvalue().lower()


def test_cross_domain_indistinguishable_student_names_fail_without_choosing(
    tmp_path: Path,
) -> None:
    nav, _ = navigation(tmp_path)
    called: list[str] = []
    screen = show_proficiency(
        nav,
        Catalog(bad_duplicate=True),
        lambda *_: called.append("read"),
        Answers(["1"]),
    )
    assert not called
    assert nav.session.active_student_id is None
    assert "No record was selected or changed" in screen.getvalue()


@pytest.mark.parametrize("forbidden", ["\u200b", "\n", "\r", "\x1b"])
def test_control_bearing_student_label_is_rejected(forbidden: str) -> None:
    with pytest.raises(ValueError):
        TeacherChoice(("student_01",), "Student" + forbidden + "Name")


def test_unicode_compatibility_duplicate_is_not_identity() -> None:
    class TwinCatalog:
        def options(self, *, scope: str, selected: Any) -> tuple[TeacherChoice, ...]:
            return (
                TeacherChoice(("a",), "ＡＬＥＸ", "11th grade"),
                TeacherChoice(("b",), "alex", "11th grade"),
            )

    with pytest.raises(TeacherChoiceUnavailable, match="indistinguishable"):
        load_teacher_choices(TwinCatalog(), scope="student")


def test_oversized_catalog_fails_before_rendering_any_identity() -> None:
    class Huge:
        def options(self, *, scope: str, selected: Any) -> tuple[TeacherChoice, ...]:
            return tuple(
                TeacherChoice((f"student_{n}",), f"Student {n}") for n in range(501)
            )

    output = StringIO()
    chosen = select_teacher_choice(
        catalog=Huge(),
        scope="student",
        title="Students",
        question="Choose",
        input_fn=Answers([]),
        output=output,
        clear_fn=lambda: None,
    )
    assert chosen is None
    assert "student_500" not in output.getvalue()
    assert "could not be verified safely" in output.getvalue()


def test_only_available_student_is_not_auto_selected() -> None:
    class Solo:
        def options(self, *, scope: str, selected: Any) -> tuple[TeacherChoice, ...]:
            return (TeacherChoice(("student_01",), "One Student"),)

    output = StringIO()
    typed = Answers(["B"])
    assert (
        select_teacher_choice(
            catalog=Solo(),
            scope="student",
            title="Students",
            question="Choose",
            input_fn=typed,
            output=output,
            clear_fn=lambda: None,
        )
        is None
    )
    assert typed.prompts == ["Choice: "]
    assert "student_01" not in output.getvalue()


def test_adversarial_matrix_declares_remaining_external_boundaries() -> None:
    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert data["schema"] == "pds.meridian.issue123.adversarial_matrix.v1"
    assert data["source_base"] == "dd35b044d5d566a6c560d9d5c09cd1ba4a89fe6f"
    assert len(data["adversarial_scenarios"]) >= 10
    assert data["installed_wheel"] == "not qualified in Slice 11C"
    assert data["protected_publication_authorization"] == "not qualified in Slice 11C"
    assert data["write_side_cas_and_receipts"] == (
        "existing #122/#39/#40 tests remain separate qualification"
    )
