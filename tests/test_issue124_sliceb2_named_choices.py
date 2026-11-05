"""#124 B2: named, paged, no-write assessment choices and safe history states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pds_core.academic_catalog import CatalogPublication, PublicationCatalogQuery
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_records import PublicationRecord, PublicationWithdrawal
from pds_core.routing_models import ModuleWorkRef

from meridian.assessment_setup_choices import (
    AssessmentChoiceReaders,
    project_named_assessment_choices,
)
from meridian.assessment_setup_inventory import (
    AssessmentSetupCandidate,
    AssessmentSetupInventoryError,
)
from meridian.teacher_navigation_choices import (
    TeacherChoiceUnavailable,
    page_teacher_choices,
)

ROOT = Path("/synthetic/read-only")
YEAR = "2026-2027"
DATE = datetime(2026, 10, 22, 15, 30, tzinfo=UTC)


def candidate(
    work_id: str = "scene_check",
    *,
    module: str = "scoreform",
    title: str = "Scene Check",
    publication_state: str = "no_current_catalog_result",
    publication_id: str | None = None,
    lifecycle: str = "active",
    setup: str = "needs_create",
) -> AssessmentSetupCandidate:
    return AssessmentSetupCandidate(
        work=ModuleWorkRef(module, "english12", work_id),
        school_year=YEAR,
        title=title,
        work_kind="assignment",
        academic_intent="summative",
        lifecycle=lifecycle,
        registration_revision=1,
        publication_state=cast(Any, publication_state),
        publication_id=publication_id,
        setup_state=cast(Any, setup),
        ready_grade_item_id="grade1" if setup == "ready" else None,
        related_grade_item_ids=(),
        active_unlinked_grade_item_ids=(),
        period_id="mp1",
        calendar_revision=3,
    )


def publication(
    work: ModuleWorkRef,
    *,
    pub_id: str = "pub_" + "a" * 32,
    withdrawn: bool = False,
    current: bool = True,
    record_set_id: str = "assessment",
) -> Any:
    return SimpleNamespace(
        school_year=YEAR,
        publication_id=pub_id,
        work=work,
        publication_kind="academic_result_set",
        record_set_id=record_set_id,
        record_set_revision=1,
        academic_work_registration_revision=1,
        manifest_digest="a" * 64,
        published_at=DATE,
        supersedes_publication_id=None,
        is_series_head=True,
        is_withdrawn=withdrawn,
        is_current_selectable=current,
    )


@dataclass
class Fixture:
    candidates: tuple[AssessmentSetupCandidate, ...]
    histories: tuple[Any, ...] = ()
    created: tuple[datetime, ...] = ()
    wrong_digest: bool = False
    missing_withdrawal: bool = False
    current_is_missing: bool = False
    calls: list[str] | None = None

    def readers(self) -> AssessmentChoiceReaders:
        if self.calls is None:
            self.calls = []
        calls = self.calls
        by_work = {c.work: i for i, c in enumerate(self.candidates)}
        rows_by_id = {item.publication_id: item for item in self.histories}

        def registration(
            root: Path, work: ModuleWorkRef
        ) -> AcademicWorkRegistration | None:
            calls.append("registration")
            assert root == ROOT
            index = by_work[work]
            c = self.candidates[index]
            date = self.created[index] if self.created else DATE
            return cast(
                AcademicWorkRegistration,
                SimpleNamespace(
                    work=work,
                    title=c.title,
                    registration_revision=c.registration_revision,
                    lifecycle=c.lifecycle,
                    academic_intent=c.academic_intent,
                    created_at=date,
                ),
            )

        def pubs(
            root: Path, query: PublicationCatalogQuery
        ) -> tuple[CatalogPublication, ...]:
            calls.append("catalog")
            assert root == ROOT
            assert query.class_id == "english12" and query.school_year == YEAR
            assert query.state == "all" and query.limit == 501
            return cast(tuple[CatalogPublication, ...], self.histories)

        def pub(root: Path, pub_id: str) -> PublicationRecord:
            calls.append("publication")
            row = rows_by_id[pub_id]
            return cast(
                PublicationRecord,
                SimpleNamespace(
                    publication_id=pub_id,
                    work=row.work,
                    publication_kind="academic_result_set",
                    record_set_id=row.record_set_id,
                    record_set_revision=row.record_set_revision,
                    academic_work_registration_revision=row.academic_work_registration_revision,
                    manifest_digest="f" * 64
                    if self.wrong_digest
                    else row.manifest_digest,
                    published_at=row.published_at,
                    supersedes_publication_id=row.supersedes_publication_id,
                ),
            )

        def withdrawal(root: Path, pub_id: str) -> PublicationWithdrawal | None:
            calls.append("withdrawal")
            row = rows_by_id[pub_id]
            if row.is_withdrawn and not self.missing_withdrawal:
                return cast(
                    PublicationWithdrawal, SimpleNamespace(publication_id=pub_id)
                )
            return None

        def current_series(
            root: Path, work: ModuleWorkRef, kind: str, record_set: str
        ) -> PublicationRecord | None:
            calls.append("current_series")
            if self.current_is_missing:
                return None
            rows = [
                r
                for r in self.histories
                if r.work == work
                and r.record_set_id == record_set
                and r.is_series_head
                and not r.is_withdrawn
            ]
            return pub(root, rows[0].publication_id) if rows else None

        return AssessmentChoiceReaders(
            registration=registration,
            publications=pubs,
            publication=pub,
            withdrawal=withdrawal,
            current_series=cast(Any, current_series),
        )

    def project(self) -> Any:
        return project_named_assessment_choices(
            ROOT,
            self.candidates,
            class_id="english12",
            school_year=YEAR,
            period_id="mp1",
            readers=self.readers(),
        )


def test_registered_only_is_not_claimed_never_published() -> None:
    case = Fixture((candidate(),))
    result = case.project()
    assert result.items[0].publication_state == "no_results_indexed"
    assert "No published results indexed" in result.choices[0].display
    assert "scene_check" not in result.choices[0].display
    assert "grade1" not in result.choices[0].display
    assert "registered 2026-10-22" in result.choices[0].display
    assert "manifest" not in (case.calls or ())


def test_verified_publication_has_same_hidden_identity_as_b1() -> None:
    one = candidate(
        publication_state="catalog_current_verified",
        publication_id="pub_" + "a" * 32,
        setup="ready",
    )
    case = Fixture((one,), (publication(one.work),))
    result = case.project()
    assert result.items[0].publication_state == "current_results_verified"
    assert result.choices[0].identity == ("english12", "scoreform", "scene_check")
    assert "Grade Item ready" in result.choices[0].display
    assert "pub_" not in result.choices[0].display


def test_withdrawn_head_requires_actual_canonical_withdrawal() -> None:
    one = candidate()
    history = (publication(one.work, withdrawn=True, current=False),)
    case = Fixture((one,), history)
    assert case.project().items[0].publication_state == "withdrawn_results"
    with pytest.raises(AssessmentSetupInventoryError, match="withdrawal"):
        Fixture((one,), history, missing_withdrawal=True).project()


def test_catalog_staleness_and_tampering_fail_closed() -> None:
    one = candidate()
    history = (publication(one.work, current=True),)
    with pytest.raises(AssessmentSetupInventoryError, match="missing from the current"):
        Fixture((one,), history).project()
    with pytest.raises(
        AssessmentSetupInventoryError, match="Publication history changed"
    ):
        Fixture((one,), history, wrong_digest=True).project()
    with pytest.raises(AssessmentSetupInventoryError, match="current series"):
        Fixture((one,), history, current_is_missing=True).project()


def test_ambiguous_current_series_is_not_silently_selected() -> None:
    one = candidate(publication_state="ambiguous_publication")
    case = Fixture((one,))
    result = case.project()
    assert result.items[0].publication_state == "multiple_current_results"
    assert "review" in result.choices[0].display


def test_same_title_different_producers_is_disambiguated_without_ids() -> None:
    a = candidate()
    b = candidate("essay", module="quillan")
    result = Fixture((a, b)).project()
    assert len(result.items) == 2
    assert {c.source for c in result.choices} == {"ScoreForm", "Quillan"}
    assert all("scene_check" not in choice.display for choice in result.choices)


def test_same_title_same_producer_distinct_dates_is_disambiguated() -> None:
    a = candidate()
    b = candidate("scene_check2")
    result = Fixture((a, b), created=(DATE, DATE + timedelta(days=2))).project()
    assert len(result.choices) == 2
    assert result.choices[0].display != result.choices[1].display


def test_indistinguishable_descriptions_fail_closed_no_index_guess() -> None:
    a = candidate()
    b = candidate("scene_check2")
    with pytest.raises(TeacherChoiceUnavailable, match="indistinguishable"):
        Fixture((a, b)).project()


def test_paging_search_reuses_existing_teacher_choices() -> None:
    items = tuple(
        candidate(f"a_{i:02d}", title=f"Assignment {i:02d}") for i in range(13)
    )
    dates = tuple(DATE + timedelta(minutes=i) for i in range(13))
    result = Fixture(items, created=dates).project()
    assert len(result.page()) == 10
    assert len(result.page(page_index=1)) == 3
    page = page_teacher_choices(result.choices, query="Assignment 12")
    assert page.match_count == 1 and page.items[0].label == "Assignment 12"


def test_cancelled_does_not_advertise_grade_item_setup_as_ready() -> None:
    one = candidate(lifecycle="cancelled", setup="review_relationship")
    assert "setup blocked" in Fixture((one,)).project().choices[0].display


def test_wrong_class_or_year_is_rejected() -> None:
    one = candidate()
    with pytest.raises(AssessmentSetupInventoryError, match="class/year/period"):
        project_named_assessment_choices(
            ROOT,
            (one,),
            class_id="other",
            school_year=YEAR,
            period_id="mp1",
            readers=Fixture((one,)).readers(),
        )


def test_duplicate_history_and_history_limits_are_rejected() -> None:
    one = candidate()
    row = publication(one.work)
    with pytest.raises(AssessmentSetupInventoryError, match="Duplicate publication"):
        Fixture((one,), (row, row)).project()
    with pytest.raises(AssessmentSetupInventoryError, match="too large"):
        Fixture((one,), tuple(row for _ in range(502))).project()


def test_no_producer_evidence_access_and_no_mutations() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "meridian" / "assessment_setup_choices.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "verify_publication_manifest(",
        "open_manifest(",
        "read_bytes(",
        "write_publication_record(",
        "commit_grade_item",
        "authorize_publication(",
        "rebuild_academic_catalog(",
    ):
        assert forbidden not in source
