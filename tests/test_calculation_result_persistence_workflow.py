from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import meridian.calculation_result_persistence_workflow as workflow

NOW = datetime(2026, 9, 2, 20, 30, tzinfo=UTC)


def reviewed() -> object:
    outcome = SimpleNamespace(
        status="calculated",
        proficiency_level_id="proficient",
    )
    policy_reference = SimpleNamespace(
        class_id="class_2026",
        policy_id="default",
        policy_revision=2,
        policy_sha256="a" * 64,
    )
    calculation = SimpleNamespace(
        outcome=outcome,
        policy_reference=policy_reference,
        result_history=(1, 2),
        next_result_revision=3,
        current_result_revision=1,
    )
    inputs = SimpleNamespace(
        target_scale=SimpleNamespace(
            class_id="class_2026",
            scale_id="four_level",
            scale_revision=4,
            scale_sha256="b" * 64,
        )
    )
    return SimpleNamespace(
        class_id="class_2026",
        grade_item_id="unit1",
        student_id="student_001",
        standard_id="NJSLSA.R1",
        grade_item_basis=SimpleNamespace(
            class_id="class_2026",
            grade_item_id="unit1",
            grade_item_revision=5,
            grade_item_revision_sha256="c" * 64,
        ),
        inputs=inputs,
        bindings=("binding",),
        source_keys=("d" * 64,),
        calculation=calculation,
        result_write_performed=False,
        result_selection_performed=False,
    )


def snapshot() -> object:
    return SimpleNamespace(
        class_id="class_2026",
        grade_item_id="unit1",
        student_id="student_001",
        standard_id="NJSLSA.R1",
        result_revision=3,
        calculated_at=NOW,
        outcome=SimpleNamespace(
            status="calculated",
            proficiency_level_id="proficient",
        ),
        calculation_fingerprint="e" * 64,
    )


def install_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "BoundedCalculationPreview",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "CalculationResultPersistencePreview",
        workflow.CalculationResultPersistencePreview,
    )


def install_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    history: tuple[int, ...] = (1, 2),
    selected: int | None = 1,
    latest_digest: str = "f" * 64,
) -> None:
    monkeypatch.setattr(
        workflow,
        "list_standard_proficiency_result_revisions",
        lambda *args, **kwargs: history,
    )
    monkeypatch.setattr(
        workflow,
        "load_standard_proficiency_result_revision",
        lambda *args, **kwargs: SimpleNamespace(
            result_sha256=latest_digest,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_standard_proficiency_result_revision",
        lambda *args, **kwargs: selected,
    )


def test_preview_freezes_next_exact_snapshot_without_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    install_state(monkeypatch)
    exact = reviewed()
    candidate = snapshot()
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def create(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return candidate

    monkeypatch.setattr(
        workflow,
        "create_standard_proficiency_result_snapshot",
        create,
    )
    monkeypatch.setattr(
        workflow,
        "write_standard_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail("preview must not write"),
    )

    preview = workflow.preview_calculation_result_persistence(
        "workspace",
        exact,
        actor_id=" teacher_42 ",
        calculated_at=NOW,
    )

    assert observed == [
        (
            (exact.inputs, exact.calculation.outcome),
            {
                "result_revision": 3,
                "calculated_at": NOW,
            },
        )
    ]
    assert preview.actor_id == "teacher_42"
    assert preview.candidate is candidate
    assert preview.history_before == (1, 2)
    assert preview.latest_result_sha256_before == "f" * 64
    assert preview.selected_revision_before == 1
    assert preview.candidate_revision == 3
    assert preview.selection_action == "not_performed"


def test_preview_rejects_result_history_drift_from_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    install_state(monkeypatch, history=(1, 2, 3))

    with pytest.raises(
        workflow.CalculationResultPersistenceStaleError,
        match="history changed",
    ):
        workflow.preview_calculation_result_persistence(
            "workspace",
            reviewed(),
            actor_id="teacher_42",
            calculated_at=NOW,
        )


def test_preview_rejects_current_selection_drift_from_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    install_state(monkeypatch, selected=2)

    with pytest.raises(
        workflow.CalculationResultPersistenceStaleError,
        match="selection changed",
    ):
        workflow.preview_calculation_result_persistence(
            "workspace",
            reviewed(),
            actor_id="teacher_42",
            calculated_at=NOW,
        )


def test_commit_rebuilds_exact_calculation_and_writes_candidate_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    install_state(monkeypatch)
    exact = reviewed()
    candidate = snapshot()
    monkeypatch.setattr(
        workflow,
        "create_standard_proficiency_result_snapshot",
        lambda *args, **kwargs: candidate,
    )
    preview = workflow.preview_calculation_result_persistence(
        "workspace",
        exact,
        actor_id="teacher_42",
        calculated_at=NOW,
    )
    monkeypatch.setattr(
        workflow,
        "build_bounded_calculation_preview",
        lambda *args, **kwargs: exact,
    )
    observed: list[object] = []

    def write(workspace: object, value: object) -> object:
        observed.extend((workspace, value))
        return SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(
                snapshot=candidate,
                result_sha256="9" * 64,
            ),
        )

    monkeypatch.setattr(
        workflow,
        "write_standard_proficiency_result_revision",
        write,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_standard_proficiency_result_revision",
        lambda *args, **kwargs: 1,
    )

    result = workflow.commit_calculation_result_persistence_preview(
        "workspace",
        preview,
    )

    assert observed == ["workspace", candidate]
    assert result.written_revision == 3
    assert result.written_result_sha256 == "9" * 64
    assert result.written_status == "calculated"
    assert result.written_proficiency_level_id == "proficient"
    assert result.selected_revision_after_write == 1
    assert result.selection_changed_during_write is False
    assert result.selection_action == "not_performed"


def test_commit_rejects_aggregation_input_drift_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    install_state(monkeypatch)
    exact = reviewed()
    candidate = snapshot()
    monkeypatch.setattr(
        workflow,
        "create_standard_proficiency_result_snapshot",
        lambda *args, **kwargs: candidate,
    )
    preview = workflow.preview_calculation_result_persistence(
        "workspace",
        exact,
        actor_id="teacher_42",
        calculated_at=NOW,
    )
    changed = reviewed()
    changed.inputs = SimpleNamespace(
        target_scale=exact.inputs.target_scale,
        changed=True,
    )
    monkeypatch.setattr(
        workflow,
        "build_bounded_calculation_preview",
        lambda *args, **kwargs: changed,
    )
    monkeypatch.setattr(
        workflow,
        "write_standard_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail("stale inputs must not write"),
    )

    with pytest.raises(
        workflow.CalculationResultPersistenceStaleError,
        match="aggregation inputs changed",
    ):
        workflow.commit_calculation_result_persistence_preview(
            "workspace",
            preview,
        )


def test_commit_rejects_result_history_drift_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    install_state(monkeypatch)
    exact = reviewed()
    candidate = snapshot()
    monkeypatch.setattr(
        workflow,
        "create_standard_proficiency_result_snapshot",
        lambda *args, **kwargs: candidate,
    )
    preview = workflow.preview_calculation_result_persistence(
        "workspace",
        exact,
        actor_id="teacher_42",
        calculated_at=NOW,
    )
    monkeypatch.setattr(
        workflow,
        "build_bounded_calculation_preview",
        lambda *args, **kwargs: exact,
    )
    monkeypatch.setattr(
        workflow,
        "list_standard_proficiency_result_revisions",
        lambda *args, **kwargs: (1, 2, 3),
    )
    monkeypatch.setattr(
        workflow,
        "write_standard_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail("stale history must not write"),
    )

    with pytest.raises(
        workflow.CalculationResultPersistenceStaleError,
        match="history changed",
    ):
        workflow.commit_calculation_result_persistence_preview(
            "workspace",
            preview,
        )


def test_commit_reports_concurrent_selection_change_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    install_state(monkeypatch)
    exact = reviewed()
    candidate = snapshot()
    monkeypatch.setattr(
        workflow,
        "create_standard_proficiency_result_snapshot",
        lambda *args, **kwargs: candidate,
    )
    preview = workflow.preview_calculation_result_persistence(
        "workspace",
        exact,
        actor_id="teacher_42",
        calculated_at=NOW,
    )
    monkeypatch.setattr(
        workflow,
        "build_bounded_calculation_preview",
        lambda *args, **kwargs: exact,
    )
    calls = iter((1, 2))
    monkeypatch.setattr(
        workflow,
        "get_current_standard_proficiency_result_revision",
        lambda *args, **kwargs: next(calls),
    )
    monkeypatch.setattr(
        workflow,
        "write_standard_proficiency_result_revision",
        lambda *args, **kwargs: SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(
                snapshot=candidate,
                result_sha256="9" * 64,
            ),
        ),
    )

    result = workflow.commit_calculation_result_persistence_preview(
        "workspace",
        preview,
    )

    assert result.selected_revision_after_write == 2
    assert result.selection_changed_during_write is True
    assert result.selection_action == "not_performed"
