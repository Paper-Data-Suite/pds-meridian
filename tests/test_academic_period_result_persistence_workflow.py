from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import meridian.academic_period_result_persistence_workflow as workflow

NOW = datetime(2026, 9, 3, 2, 30, tzinfo=UTC)


def reviewed() -> object:
    period = SimpleNamespace(
        school_year="2026-2027",
        period_id="mp1",
    )
    target = SimpleNamespace(period=period, calendar_revision=4)
    outcome = SimpleNamespace(
        status="calculated",
        proficiency_level_id="proficient",
    )
    policy_reference = SimpleNamespace(
        class_id="class_2026",
        policy_id="period_policy",
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
        class_id="class_2026",
        target_period=target,
        student_id="student_001",
        standard_id="NJSLSA.R1",
    )
    return SimpleNamespace(
        target_period=target,
        candidate_specs=("candidate",),
        inputs=inputs,
        calculation=calculation,
        result_write_performed=False,
        result_selection_performed=False,
    )


def snapshot() -> object:
    period = SimpleNamespace(
        school_year="2026-2027",
        period_id="mp1",
    )
    return SimpleNamespace(
        class_id="class_2026",
        target_period=SimpleNamespace(
            period=period,
            calendar_revision=4,
        ),
        student_id="student_001",
        standard_id="NJSLSA.R1",
        result_revision=3,
        calculated_at=NOW,
        outcome=SimpleNamespace(
            status="calculated",
            proficiency_level_id="proficient",
        ),
        calculation_fingerprint="b" * 64,
    )


def install_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "BoundedAcademicPeriodCalculationPreview",
        SimpleNamespace,
    )


def install_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    history: tuple[int, ...] = (1, 2),
    selected: int | None = 1,
    latest_digest: str = "c" * 64,
) -> None:
    monkeypatch.setattr(
        workflow,
        "list_academic_period_proficiency_result_revisions",
        lambda *args, **kwargs: history,
    )
    monkeypatch.setattr(
        workflow,
        "load_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: SimpleNamespace(
            result_sha256=latest_digest,
        ),
    )
    monkeypatch.setattr(
        workflow,
        "get_current_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: selected,
    )


def test_preview_freezes_exact_next_period_snapshot_without_write(
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
        "create_academic_period_proficiency_result_snapshot",
        create,
    )
    monkeypatch.setattr(
        workflow,
        "write_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail("preview must not write"),
    )

    preview = workflow.preview_academic_period_result_persistence(
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
    assert preview.latest_result_sha256_before == "c" * 64
    assert preview.selected_revision_before == 1
    assert preview.candidate_revision == 3
    assert preview.selection_action == "not_performed"


def test_preview_rejects_history_drift_from_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    install_state(monkeypatch, history=(1, 2, 3))

    with pytest.raises(
        workflow.AcademicPeriodResultPersistenceStaleError,
        match="history changed",
    ):
        workflow.preview_academic_period_result_persistence(
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
        workflow.AcademicPeriodResultPersistenceStaleError,
        match="selection changed",
    ):
        workflow.preview_academic_period_result_persistence(
            "workspace",
            reviewed(),
            actor_id="teacher_42",
            calculated_at=NOW,
        )


def test_commit_rebuilds_exact_period_calculation_and_writes_candidate_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    install_state(monkeypatch)
    exact = reviewed()
    candidate = snapshot()
    monkeypatch.setattr(
        workflow,
        "create_academic_period_proficiency_result_snapshot",
        lambda *args, **kwargs: candidate,
    )
    preview = workflow.preview_academic_period_result_persistence(
        "workspace",
        exact,
        actor_id="teacher_42",
        calculated_at=NOW,
    )
    monkeypatch.setattr(
        workflow,
        "build_bounded_academic_period_calculation_preview",
        lambda *args, **kwargs: exact,
    )
    observed: list[object] = []

    def write(workspace: object, value: object) -> object:
        observed.extend((workspace, value))
        return SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(
                snapshot=candidate,
                result_sha256="d" * 64,
            ),
        )

    monkeypatch.setattr(
        workflow,
        "write_academic_period_proficiency_result_revision",
        write,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: 1,
    )

    result = workflow.commit_academic_period_result_persistence_preview(
        "workspace",
        preview,
    )

    assert observed == ["workspace", candidate]
    assert result.written_revision == 3
    assert result.written_result_sha256 == "d" * 64
    assert result.written_status == "calculated"
    assert result.written_proficiency_level_id == "proficient"
    assert result.selected_revision_after_write == 1
    assert result.selection_changed_during_write is False
    assert result.selection_action == "not_performed"


def test_commit_rejects_exact_period_input_drift_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    install_state(monkeypatch)
    exact = reviewed()
    candidate = snapshot()
    monkeypatch.setattr(
        workflow,
        "create_academic_period_proficiency_result_snapshot",
        lambda *args, **kwargs: candidate,
    )
    preview = workflow.preview_academic_period_result_persistence(
        "workspace",
        exact,
        actor_id="teacher_42",
        calculated_at=NOW,
    )
    changed = reviewed()
    changed.inputs = SimpleNamespace(
        class_id=exact.inputs.class_id,
        target_period=exact.inputs.target_period,
        student_id=exact.inputs.student_id,
        standard_id=exact.inputs.standard_id,
        changed=True,
    )
    monkeypatch.setattr(
        workflow,
        "build_bounded_academic_period_calculation_preview",
        lambda *args, **kwargs: changed,
    )
    monkeypatch.setattr(
        workflow,
        "write_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail("stale inputs must not write"),
    )

    with pytest.raises(
        workflow.AcademicPeriodResultPersistenceStaleError,
        match="aggregation inputs changed",
    ):
        workflow.commit_academic_period_result_persistence_preview(
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
        "create_academic_period_proficiency_result_snapshot",
        lambda *args, **kwargs: candidate,
    )
    preview = workflow.preview_academic_period_result_persistence(
        "workspace",
        exact,
        actor_id="teacher_42",
        calculated_at=NOW,
    )
    monkeypatch.setattr(
        workflow,
        "build_bounded_academic_period_calculation_preview",
        lambda *args, **kwargs: exact,
    )
    monkeypatch.setattr(
        workflow,
        "list_academic_period_proficiency_result_revisions",
        lambda *args, **kwargs: (1, 2, 3),
    )
    monkeypatch.setattr(
        workflow,
        "write_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: pytest.fail("stale history must not write"),
    )

    with pytest.raises(
        workflow.AcademicPeriodResultPersistenceStaleError,
        match="history changed",
    ):
        workflow.commit_academic_period_result_persistence_preview(
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
        "create_academic_period_proficiency_result_snapshot",
        lambda *args, **kwargs: candidate,
    )
    preview = workflow.preview_academic_period_result_persistence(
        "workspace",
        exact,
        actor_id="teacher_42",
        calculated_at=NOW,
    )
    monkeypatch.setattr(
        workflow,
        "build_bounded_academic_period_calculation_preview",
        lambda *args, **kwargs: exact,
    )
    calls = iter((1, 2))
    monkeypatch.setattr(
        workflow,
        "get_current_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: next(calls),
    )
    monkeypatch.setattr(
        workflow,
        "write_academic_period_proficiency_result_revision",
        lambda *args, **kwargs: SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(
                snapshot=candidate,
                result_sha256="d" * 64,
            ),
        ),
    )

    result = workflow.commit_academic_period_result_persistence_preview(
        "workspace",
        preview,
    )

    assert result.selected_revision_after_write == 2
    assert result.selection_changed_during_write is True
    assert result.selection_action == "not_performed"
