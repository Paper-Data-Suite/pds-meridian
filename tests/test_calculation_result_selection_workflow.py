from __future__ import annotations

from types import SimpleNamespace

import pytest

import meridian.calculation_result_selection_workflow as workflow

CLASS_ID = "class_2026"
GRADE_ITEM_ID = "unit1"
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"


def stored(revision: int = 2, digest: str = "a" * 64) -> object:
    snapshot = SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
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
        "CalculationResultSelectionPreview",
        workflow.CalculationResultSelectionPreview,
    )


def install_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    history: tuple[int, ...] = (1, 2, 3),
    current: int | None = 1,
    target: object | None = None,
) -> object:
    exact = stored() if target is None else target
    monkeypatch.setattr(
        workflow,
        "list_standard_proficiency_result_revisions",
        lambda *args, **kwargs: history,
    )
    monkeypatch.setattr(
        workflow,
        "load_standard_proficiency_result_revision",
        lambda *args, **kwargs: exact,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_standard_proficiency_result_revision",
        lambda *args, **kwargs: current,
    )
    return exact


def test_preview_targets_exact_historical_revision_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact = install_state(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "select_standard_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail("preview must not select"),
    )

    preview = workflow.preview_calculation_result_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        2,
    )

    assert preview.target is exact
    assert preview.history == (1, 2, 3)
    assert preview.expected_current_result_revision == 1
    assert preview.target_revision == 2
    assert preview.target_result_sha256 == "a" * 64
    assert preview.target_status == "calculated"
    assert preview.target_proficiency_level_id == "proficient"
    assert preview.target_is_latest is False
    assert preview.authoring_action == "not_performed"


def test_preview_allows_latest_or_historical_but_not_missing_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_state(monkeypatch, history=(1, 2, 3))

    with pytest.raises(
        workflow.CalculationResultSelectionScopeError,
        match="persisted historical revision",
    ):
        workflow.preview_calculation_result_selection(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            4,
        )


def test_commit_selects_exact_target_with_current_pointer_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact = install_state(monkeypatch)
    preview = workflow.preview_calculation_result_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        2,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def select(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return SimpleNamespace(
            disposition="updated",
            stored=exact,
        )

    monkeypatch.setattr(
        workflow,
        "select_standard_proficiency_result_revision",
        select,
    )

    result = workflow.commit_calculation_result_selection_preview(
        "workspace",
        preview,
    )

    assert observed == [
        (
            (
                "workspace",
                CLASS_ID,
                GRADE_ITEM_ID,
                STUDENT_ID,
                STANDARD_ID,
                2,
            ),
            {"expected_current_result_revision": 1},
        )
    ]
    assert result.previous_current_result_revision == 1
    assert result.selected_revision == 2
    assert result.selected_result_sha256 == "a" * 64
    assert result.selected_status == "calculated"
    assert result.selected_proficiency_level_id == "proficient"
    assert result.selection_disposition == "updated"
    assert result.authoring_action == "not_performed"


def test_commit_rejects_history_drift_before_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact = install_state(monkeypatch)
    preview = workflow.preview_calculation_result_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        2,
    )
    monkeypatch.setattr(
        workflow,
        "list_standard_proficiency_result_revisions",
        lambda *args, **kwargs: (1, 2, 3, 4),
    )
    monkeypatch.setattr(
        workflow,
        "select_standard_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail("stale history must not select"),
    )

    with pytest.raises(
        workflow.CalculationResultSelectionStaleError,
        match="history changed",
    ):
        workflow.commit_calculation_result_selection_preview(
            "workspace",
            preview,
        )

    assert exact is preview.target


def test_commit_rejects_target_digest_or_content_drift_before_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_state(monkeypatch)
    preview = workflow.preview_calculation_result_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        2,
    )
    changed = stored(digest="f" * 64)
    monkeypatch.setattr(
        workflow,
        "load_standard_proficiency_result_revision",
        lambda *args, **kwargs: changed,
    )
    monkeypatch.setattr(
        workflow,
        "select_standard_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail("changed target must not select"),
    )

    with pytest.raises(
        workflow.CalculationResultSelectionStaleError,
        match="Target proficiency result changed",
    ):
        workflow.commit_calculation_result_selection_preview(
            "workspace",
            preview,
        )


def test_commit_translates_cas_conflict_to_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_state(monkeypatch)
    preview = workflow.preview_calculation_result_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        2,
    )

    def conflict(*args: object, **kwargs: object) -> object:
        raise workflow.StandardProficiencyStorageConflictError(
            "Expected current standards-proficiency result revision "
            "does not match stored selection."
        )

    monkeypatch.setattr(
        workflow,
        "select_standard_proficiency_result_revision",
        conflict,
    )

    with pytest.raises(
        workflow.CalculationResultSelectionStaleError,
        match="Expected current",
    ):
        workflow.commit_calculation_result_selection_preview(
            "workspace",
            preview,
        )
