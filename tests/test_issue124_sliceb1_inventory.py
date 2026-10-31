"""#124 B1: isolated, no-write registry/Grade Item setup discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pds_core.academic_catalog import (
    CatalogAcademicWorkRegistration,
    CatalogPublication,
)
from pds_core.academic_periods import AcademicPeriodCalendar
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_records import PublicationRecord
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_inventory import (
    AssessmentSetupInventoryError,
    AssessmentSetupReaders,
    discover_assessment_setup_inventory,
)
from meridian.grade_items_workflow import GradeItemsReview

WORK = ModuleWorkRef("scoreform", "english12", "scene_check")
YEAR = "2026-2027"


@dataclass
class Fixture:
    regs: tuple[Any, ...]
    pubs: tuple[Any, ...]
    rows: tuple[Any, ...]
    period: str = "mp1"
    lifecycle: str = "active"
    updated: bool = False

    def readers(self) -> AssessmentSetupReaders:
        def registrations(
            root: Path, query: Any
        ) -> tuple[CatalogAcademicWorkRegistration, ...]:
            assert query.class_id == "english12" and query.current_only
            assert query.limit == 501
            return cast(tuple[CatalogAcademicWorkRegistration, ...], self.regs)

        def publications(root: Path, query: Any) -> tuple[CatalogPublication, ...]:
            assert (
                query.publication_kind == "academic_result_set"
                and query.state == "current"
            )
            return cast(tuple[CatalogPublication, ...], self.pubs)

        def registration(
            root: Path, work: ModuleWorkRef
        ) -> AcademicWorkRegistration | None:
            assert work == WORK
            return cast(
                AcademicWorkRegistration,
                SimpleNamespace(
                    work=work,
                    registration_revision=2 if self.updated else 1,
                    title="Scene Check",
                    work_kind="assignment",
                    academic_intent="summative",
                    lifecycle=self.lifecycle,
                    producer_contract_version="scoreform_academic_work_v1",
                    source_records=(),
                ),
            )

        def publication(
            root: Path, work: ModuleWorkRef, kind: str, record_set: str
        ) -> PublicationRecord | None:
            assert work == WORK and kind == "academic_result_set"
            return cast(
                PublicationRecord,
                SimpleNamespace(
                    publication_id="pub_" + "a" * 32,
                    work=WORK,
                    publication_kind="academic_result_set",
                    manifest_digest="d" * 64,
                    record_set_revision=1,
                    academic_work_registration_revision=1,
                ),
            )

        def calendar(root: Path, year: str) -> AcademicPeriodCalendar | None:
            assert year == YEAR
            return cast(
                AcademicPeriodCalendar,
                SimpleNamespace(
                    school_year=YEAR,
                    calendar_revision=3,
                    periods=(
                        SimpleNamespace(
                            period_id=self.period,
                            period_type="marking_period",
                            lifecycle="active",
                        ),
                    ),
                ),
            )

        def grade_items(root: Path, class_id: str) -> GradeItemsReview:
            assert class_id == "english12"
            return cast(
                GradeItemsReview, SimpleNamespace(class_id=class_id, items=self.rows)
            )

        return AssessmentSetupReaders(
            registrations=registrations,
            publications=publications,
            current_registration=registration,
            current_publication=publication,
            calendar=calendar,
            grade_items=grade_items,
        )

    def discover(self, root: Path = Path("/synthetic/no-write")) -> tuple[Any, ...]:
        return discover_assessment_setup_inventory(
            root,
            class_id="english12",
            school_year=YEAR,
            period_id="mp1",
            readers=self.readers(),
        )


def registered() -> Any:
    return SimpleNamespace(
        work=WORK,
        school_year=YEAR,
        is_current_registration=True,
        registration_revision=1,
        title="Scene Check",
        work_kind="assignment",
        academic_intent="summative",
        lifecycle="active",
        producer_contract_version="scoreform_academic_work_v1",
        source_records=(),
    )


def publication() -> Any:
    return SimpleNamespace(
        publication_id="pub_" + "a" * 32,
        work=WORK,
        manifest_digest="d" * 64,
        record_set_revision=1,
        academic_work_registration_revision=1,
        record_set_id="academic_results",
    )


def grade_item(
    *,
    related: bool,
    decision: str = "included",
    revision: int = 1,
    period: str = "mp1",
    active: bool = True,
) -> Any:
    links = (
        (
            SimpleNamespace(
                work=WORK,
                selected_revision=1,
                decision=decision,
                grade_item_basis_state="matches_current_grade_item",
                registration_revision=revision,
                academic_period_school_year=YEAR,
                academic_period_id=period,
                academic_period_calendar_revision=3,
            ),
        )
        if related
        else ()
    )
    return SimpleNamespace(
        grade_item_id="grade_check",
        selected_revision=1,
        status="active" if active else "archived",
        memberships=links,
    )


def test_registered_only_does_not_imply_publication_or_grade() -> None:
    case = Fixture((registered(),), (), ())
    (one,) = case.discover()
    assert one.publication_state == "no_current_catalog_result"
    assert one.setup_state == "needs_create"
    assert one.publication_id is None and not one.grade_item_ready


def test_current_published_grade_item_and_period_are_exact() -> None:
    case = Fixture((registered(),), (publication(),), (grade_item(related=True),))
    (one,) = case.discover()
    assert one.publication_state == "catalog_current_verified"
    assert one.ready_grade_item_id == "grade_check"
    assert one.grade_item_ready
    assert one.registration_revision == 1 and one.calendar_revision == 3


@pytest.mark.parametrize(
    "link",
    [
        grade_item(related=True, decision="excluded"),
        grade_item(related=True, revision=2),
        grade_item(related=True, period="mp2"),
        grade_item(related=True, active=False),
    ],
)
def test_inoperative_membership_requires_review(link: Any) -> None:
    case = Fixture((registered(),), (), (link,))
    (one,) = case.discover()
    assert one.setup_state == "review_relationship"
    assert not one.grade_item_ready


def test_unlinked_existing_is_not_auto_selected() -> None:
    case = Fixture((registered(),), (), (grade_item(related=False),))
    (one,) = case.discover()
    assert one.setup_state == "choose_existing"
    assert one.active_unlinked_grade_item_ids == ("grade_check",)


def test_duplicate_ready_relationships_are_ambiguous() -> None:
    a = grade_item(related=True)
    b = SimpleNamespace(**{**vars(a), "grade_item_id": "grade_second"})
    (one,) = Fixture((registered(),), (), (a, b)).discover()
    assert one.setup_state == "ambiguous" and one.ready_grade_item_id is None


def test_stale_registration_denied_before_setup() -> None:
    case = Fixture((registered(),), (), (), updated=True)
    with pytest.raises(AssessmentSetupInventoryError, match="refresh"):
        case.discover()


def test_cancelled_registration_cannot_be_called_ready() -> None:
    reg = registered()
    reg.lifecycle = "cancelled"
    case = Fixture((reg,), (), (grade_item(related=True),), lifecycle="cancelled")
    (one,) = case.discover()
    assert one.setup_state == "review_relationship" and one.ready_grade_item_id is None


def test_period_drift_fails_closed() -> None:
    with pytest.raises(AssessmentSetupInventoryError, match="period"):
        Fixture((registered(),), (), (), period="mp2").discover()


def test_catalog_publication_mismatch_fails_closed() -> None:
    wrong = publication()
    wrong.manifest_digest = "f" * 64
    with pytest.raises(AssessmentSetupInventoryError, match="refresh"):
        Fixture((registered(),), (wrong,), ()).discover()


def test_publication_ambiguity_no_first_match() -> None:
    other = publication()
    other.publication_id = "pub_" + "b" * 32
    (one,) = Fixture((registered(),), (publication(), other), ()).discover()
    assert one.publication_state == "ambiguous_publication"
    assert one.publication_id is None


def test_source_is_strictly_read_only() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "meridian"
        / "assessment_setup_inventory.py"
    ).read_text(encoding="utf-8")
    assert "verify_publication_manifest(" not in source
    assert "write_publication_record(" not in source
    assert "commit_grade_item" not in source
    assert "rebuild_academic_catalog(" not in source


def test_injected_discovery_does_not_create_files(tmp_path: Path) -> None:
    case = Fixture((registered(),), (publication(),), (grade_item(related=True),))
    assert case.discover(tmp_path)[0].grade_item_ready
    assert list(tmp_path.iterdir()) == []
