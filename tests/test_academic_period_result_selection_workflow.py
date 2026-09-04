from __future__ import annotations

from types import SimpleNamespace

import pytest

import meridian.academic_period_result_selection_workflow as workflow

CLASS_ID = "class_2026"
SCHOOL_YEAR = "2026-2027"
PERIOD_ID = "mp1"
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"


def stored(
    revision: int = 2,
    *,
    digest: str = "a" * 64,
) -> object:
    snapshot = SimpleNamespace(
        class_id=CLASS_ID,
        target_period=SimpleNamespace(
            period=SimpleNamespace(
                school_year=SCHOOL_YEAR,
                period_id=PERIOD_ID,
            ),
            calendar_revision=4,
        ),
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        result_revision=revision,
        outcome=SimpleNamespace(
            status="calculated",
            proficiency_level_id="proficient",
        ),
        calculation_fingerprint="b" * 64,
    )
    return SimpleNamespace(
        snapshot=snapshot,
        result_sha256=digest,
        content=f"result-{revision}".encode(),
    )


def install_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "StoredAcademicPeriodProficiencyResult",
        SimpleNamespace,
    )


def test_preview_allows_exact_historical_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    target = stored(2)
    monkeypatch.setattr(
        workflow,
        "list_academic_period_proficiency_result_revisions",
        lambda *args, **kwargs: (1, 2, 3),
    )
    monkeypatch.setattr(
        workflow,
        "load_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: target,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: 3,
    )

    preview = workflow.preview_academic_period_result_selection(
        "workspace",
        CLASS_ID,
        SCHOOL_YEAR,
        PERIOD_ID,
        STUDENT_ID,
        STANDARD_ID,
        2,
    )

    assert preview.target is target
    assert preview.history == (1, 2, 3)
    assert preview.expected_current_result_revision == 3
    assert preview.target_revision == 2
    assert preview.target_is_latest is False
    assert preview.calendar_revision == 4
    assert preview.target_status == "calculated"
    assert preview.target_proficiency_level_id == "proficient"
    assert preview.authoring_action == "not_performed"


def test_preview_rejects_nonpersisted_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "list_academic_period_proficiency_result_revisions",
        lambda *args, **kwargs: (1, 2),
    )
    monkeypatch.setattr(
        workflow,
        "load_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail(
            "nonpersisted target must fail before load"
        ),
    )

    with pytest.raises(
        workflow.AcademicPeriodResultSelectionScopeError,
        match="exact persisted historical revision",
    ):
        workflow.preview_academic_period_result_selection(
            "workspace",
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            STUDENT_ID,
            STANDARD_ID,
            3,
        )


def test_preview_rejects_nonpositive_revision() -> None:
    with pytest.raises(
        workflow.AcademicPeriodResultSelectionScopeError,
        match="positive integer",
    ):
        workflow.preview_academic_period_result_selection(
            "workspace",
            CLASS_ID,
            SCHOOL_YEAR,
            PERIOD_ID,
            STUDENT_ID,
            STANDARD_ID,
            0,
        )


def test_commit_rejects_history_drift_before_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    target = stored(2)
    preview = SimpleNamespace(
        class_id=CLASS_ID,
        school_year=SCHOOL_YEAR,
        period_id=PERIOD_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_revision=2,
        target=target,
        history=(1, 2),
        expected_current_result_revision=1,
    )
    monkeypatch.setattr(
        workflow,
        "AcademicPeriodResultSelectionPreview",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "list_academic_period_proficiency_result_revisions",
        lambda *args, **kwargs: (1, 2, 3),
    )
    monkeypatch.setattr(
        workflow,
        "select_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail("stale history must not select"),
    )

    with pytest.raises(
        workflow.AcademicPeriodResultSelectionStaleError,
        match="history changed",
    ):
        workflow.commit_academic_period_result_selection_preview(
            "workspace",
            preview,
        )


def test_commit_rejects_target_content_drift_before_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    target = stored(2)
    preview = SimpleNamespace(
        class_id=CLASS_ID,
        school_year=SCHOOL_YEAR,
        period_id=PERIOD_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_revision=2,
        target=target,
        history=(1, 2),
        expected_current_result_revision=1,
    )
    monkeypatch.setattr(
        workflow,
        "AcademicPeriodResultSelectionPreview",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "list_academic_period_proficiency_result_revisions",
        lambda *args, **kwargs: (1, 2),
    )
    monkeypatch.setattr(
        workflow,
        "load_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: stored(2, digest="c" * 64),
    )
    monkeypatch.setattr(
        workflow,
        "select_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail("changed target must not select"),
    )

    with pytest.raises(
        workflow.AcademicPeriodResultSelectionStaleError,
        match="result changed",
    ):
        workflow.commit_academic_period_result_selection_preview(
            "workspace",
            preview,
        )


def test_commit_uses_exact_expected_current_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    target = stored(2)
    preview = SimpleNamespace(
        class_id=CLASS_ID,
        school_year=SCHOOL_YEAR,
        period_id=PERIOD_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_revision=2,
        target=target,
        history=(1, 2, 3),
        expected_current_result_revision=3,
    )
    monkeypatch.setattr(
        workflow,
        "AcademicPeriodResultSelectionPreview",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "list_academic_period_proficiency_result_revisions",
        lambda *args, **kwargs: (1, 2, 3),
    )
    monkeypatch.setattr(
        workflow,
        "load_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: target,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def select(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return SimpleNamespace(
            disposition="updated",
            stored=target,
        )

    monkeypatch.setattr(
        workflow,
        "select_academic_period_proficiency_result_revision",
        select,
    )

    result = workflow.commit_academic_period_result_selection_preview(
        "workspace",
        preview,
    )

    assert observed == [
        (
            (
                "workspace",
                CLASS_ID,
                SCHOOL_YEAR,
                PERIOD_ID,
                STUDENT_ID,
                STANDARD_ID,
                2,
            ),
            {"expected_current_result_revision": 3},
        )
    ]
    assert result.previous_current_result_revision == 3
    assert result.selected_revision == 2
    assert result.selected_result_sha256 == "a" * 64
    assert result.selection_disposition == "updated"
    assert result.authoring_action == "not_performed"


def test_commit_translates_cas_conflict_to_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    target = stored(2)
    preview = SimpleNamespace(
        class_id=CLASS_ID,
        school_year=SCHOOL_YEAR,
        period_id=PERIOD_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_revision=2,
        target=target,
        history=(1, 2),
        expected_current_result_revision=1,
    )
    monkeypatch.setattr(
        workflow,
        "AcademicPeriodResultSelectionPreview",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "list_academic_period_proficiency_result_revisions",
        lambda *args, **kwargs: (1, 2),
    )
    monkeypatch.setattr(
        workflow,
        "load_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: target,
    )
    monkeypatch.setattr(
        workflow,
        "select_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            workflow.AcademicPeriodProficiencyStorageConflictError(
                "current changed"
            )
        ),
    )

    with pytest.raises(
        workflow.AcademicPeriodResultSelectionStaleError,
        match="current changed",
    ):
        workflow.commit_academic_period_result_selection_preview(
            "workspace",
            preview,
        )
