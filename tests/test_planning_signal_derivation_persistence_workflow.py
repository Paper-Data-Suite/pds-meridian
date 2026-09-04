from __future__ import annotations

from types import SimpleNamespace

import pytest

import meridian.planning_signal_derivation_persistence_workflow as workflow


def candidate(
    *,
    fingerprint: str = "a" * 64,
    policy_reference: object | None = None,
) -> object:
    policy_reference = policy_reference or SimpleNamespace(
        class_id="class_2026",
        policy_id="reading_groups",
        policy_revision=2,
        policy_sha256="b" * 64,
    )
    return SimpleNamespace(
        class_id="class_2026",
        policy_reference=policy_reference,
        derivation_id="gsd_" + "c" * 64,
        calculation_fingerprint=fingerprint,
        roster_basis=SimpleNamespace(
            student_ids=("student_001", "student_002"),
        ),
        student_derivations=(
            SimpleNamespace(disposition="contributing"),
            SimpleNamespace(disposition="noncontributing"),
        ),
    )


def readiness(
    *,
    ready: bool = True,
    snapshot: object | None = None,
    policy: object | None = None,
) -> object:
    reference = SimpleNamespace(
        class_id="class_2026",
        policy_id="reading_groups",
        policy_revision=2,
        policy_sha256="b" * 64,
    )
    if policy is None:
        policy = SimpleNamespace(reference=reference)
    if snapshot is None and ready:
        snapshot = candidate(policy_reference=reference)
    return SimpleNamespace(
        class_id="class_2026",
        policy_id="reading_groups",
        policy=policy,
        generation=SimpleNamespace(
            status="generated" if ready else "blocked",
            blockers=(),
            snapshot=snapshot,
        ),
        ready_for_derivation_persistence=ready,
    )


def install_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "PlanningSignalReadinessProjection",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "GroupingSignalDerivationSnapshot",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        workflow,
        "StoredGroupingSignalDerivation",
        SimpleNamespace,
    )


def test_preview_freezes_exact_ready_candidate_without_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    reviewed = readiness()
    monkeypatch.setattr(
        workflow,
        "write_grouping_signal_derivation",
        lambda *args, **kwargs: pytest.fail("preview must not write"),
    )

    preview = workflow.preview_planning_signal_derivation_persistence(
        reviewed
    )

    assert preview.readiness is reviewed
    assert preview.candidate is reviewed.generation.snapshot
    assert preview.class_id == "class_2026"
    assert preview.policy_id == "reading_groups"
    assert preview.derivation_id == "gsd_" + "c" * 64
    assert preview.roster_student_count == 2
    assert preview.contributing_student_count == 1
    assert preview.noncontributing_student_count == 1
    assert preview.derivation_write_action == "not_performed"
    assert preview.preview_write_action == "not_performed"
    assert preview.core_export_action == "not_performed"


def test_preview_rejects_blocked_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)

    with pytest.raises(
        workflow.PlanningSignalDerivationPersistenceScopeError,
        match="readiness is blocked",
    ):
        workflow.preview_planning_signal_derivation_persistence(
            readiness(ready=False)
        )


def test_preview_requires_candidate_to_bind_selected_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    wrong = SimpleNamespace(
        class_id="class_2026",
        policy_id="reading_groups",
        policy_revision=3,
        policy_sha256="d" * 64,
    )

    with pytest.raises(
        workflow.PlanningSignalDerivationPersistenceScopeError,
        match="does not bind",
    ):
        workflow.preview_planning_signal_derivation_persistence(
            readiness(snapshot=candidate(policy_reference=wrong))
        )


def test_commit_rebuilds_readiness_and_writes_exact_reviewed_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    reviewed = readiness()
    preview = workflow.preview_planning_signal_derivation_persistence(
        reviewed
    )
    monkeypatch.setattr(
        workflow,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: reviewed,
    )
    observed: list[object] = []

    def write(workspace: object, snapshot: object) -> object:
        observed.extend((workspace, snapshot))
        return SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(
                snapshot=snapshot,
                derivation_sha256="e" * 64,
            ),
        )

    monkeypatch.setattr(
        workflow,
        "write_grouping_signal_derivation",
        write,
    )

    result = workflow.commit_planning_signal_derivation_persistence_preview(
        "workspace",
        preview,
    )

    assert observed == ["workspace", preview.candidate]
    assert result.write_disposition == "created"
    assert result.derivation_id == "gsd_" + "c" * 64
    assert result.derivation_sha256 == "e" * 64
    assert result.calculation_fingerprint == "a" * 64
    assert result.preview_write_action == "not_performed"
    assert result.review_write_action == "not_performed"
    assert result.review_selection_action == "not_performed"
    assert result.core_export_action == "not_performed"
    assert result.csv_export_action == "not_performed"


def test_commit_rejects_new_blocker_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    preview = workflow.preview_planning_signal_derivation_persistence(
        readiness()
    )
    monkeypatch.setattr(
        workflow,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: readiness(ready=False),
    )
    monkeypatch.setattr(
        workflow,
        "write_grouping_signal_derivation",
        lambda *args, **kwargs: pytest.fail("blocked state must not write"),
    )

    with pytest.raises(
        workflow.PlanningSignalDerivationPersistenceStaleError,
        match="became blocked",
    ):
        workflow.commit_planning_signal_derivation_persistence_preview(
            "workspace",
            preview,
        )


def test_commit_rejects_policy_change_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    reviewed = readiness()
    preview = workflow.preview_planning_signal_derivation_persistence(
        reviewed
    )
    changed_policy = SimpleNamespace(
        reference=SimpleNamespace(
            class_id="class_2026",
            policy_id="reading_groups",
            policy_revision=3,
            policy_sha256="f" * 64,
        )
    )
    fresh = readiness(
        snapshot=candidate(policy_reference=changed_policy.reference),
        policy=changed_policy,
    )
    monkeypatch.setattr(
        workflow,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: fresh,
    )
    monkeypatch.setattr(
        workflow,
        "write_grouping_signal_derivation",
        lambda *args, **kwargs: pytest.fail("changed policy must not write"),
    )

    with pytest.raises(
        workflow.PlanningSignalDerivationPersistenceStaleError,
        match="policy changed",
    ):
        workflow.commit_planning_signal_derivation_persistence_preview(
            "workspace",
            preview,
        )


def test_commit_rejects_candidate_change_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_types(monkeypatch)
    reviewed = readiness()
    preview = workflow.preview_planning_signal_derivation_persistence(
        reviewed
    )
    fresh = readiness(
        snapshot=candidate(fingerprint="f" * 64),
        policy=reviewed.policy,
    )
    monkeypatch.setattr(
        workflow,
        "project_planning_signal_readiness",
        lambda *args, **kwargs: fresh,
    )
    monkeypatch.setattr(
        workflow,
        "write_grouping_signal_derivation",
        lambda *args, **kwargs: pytest.fail("changed candidate must not write"),
    )

    with pytest.raises(
        workflow.PlanningSignalDerivationPersistenceStaleError,
        match="candidate changed",
    ):
        workflow.commit_planning_signal_derivation_persistence_preview(
            "workspace",
            preview,
        )
