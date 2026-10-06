from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import meridian.conventional_grade_explanation as conventional_explanation
import meridian.current_grade_preview as current_preview
import meridian.hybrid_grade_explanation as hybrid_explanation
import meridian.standards_grade_explanation as standards_explanation
from meridian.grade_preview_explanation import (
    GradePreviewCurrentnessConflictError,
    GradePreviewIntegrityError,
)
from tests import test_conventional_grade_explanation as conventional_support
from tests import test_current_grade_preview as current_support
from tests import test_hybrid_grade_explanation as hybrid_support
from tests import test_standards_grade_explanation as standards_support


def test_issue61_current_preview_uses_snapshot_policy_history_not_current_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, decision, _, _, snapshot = current_support._snapshots()
    activation_revisions: list[int] = []
    policy_revisions: list[int] = []

    def load_activation(_root, _class_id, _period, revision):
        activation_revisions.append(revision)
        return SimpleNamespace(
            reference=snapshot.activation_reference,
            decision=decision,
        )

    def load_policy(_root, _class_id, _policy_id, revision):
        policy_revisions.append(revision)
        return SimpleNamespace(
            reference=snapshot.policy_reference,
            policy=value,
        )

    monkeypatch.setattr(
        current_preview,
        "load_grade_policy_activation_revision",
        load_activation,
    )
    monkeypatch.setattr(
        current_preview,
        "load_grade_policy_revision",
        load_policy,
    )
    monkeypatch.setattr(
        current_preview,
        "load_current_grade_policy_activation",
        lambda *args, **kwargs: pytest.fail(
            "historical authority reconstruction must not use current activation"
        ),
    )

    authority = current_preview._load_source_authority(
        Path("."),
        current_support._target("hybrid"),
        snapshot,
    )

    assert authority.activation == decision
    assert authority.policy == value
    assert activation_revisions == [
        snapshot.activation_reference.activation_revision
    ]
    assert policy_revisions == [snapshot.policy_reference.policy_revision]


def test_issue61_historical_policy_digest_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, decision, _, _, snapshot = current_support._snapshots()
    wrong_policy = replace(
        snapshot.policy_reference,
        policy_sha256="f" * 64,
    )

    monkeypatch.setattr(
        current_preview,
        "load_grade_policy_activation_revision",
        lambda *args, **kwargs: SimpleNamespace(
            reference=snapshot.activation_reference,
            decision=decision,
        ),
    )
    monkeypatch.setattr(
        current_preview,
        "load_grade_policy_revision",
        lambda *args, **kwargs: SimpleNamespace(
            reference=wrong_policy,
            policy=value,
        ),
    )

    with pytest.raises(GradePreviewIntegrityError, match="policy digest"):
        current_preview._load_source_authority(
            Path("."),
            current_support._target("hybrid"),
            snapshot,
        )


def test_issue61_current_preview_rejects_mixed_time_witness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, snapshot, _ = current_support._snapshots()
    effective = object()
    first_witness = SimpleNamespace(
        source_result="source-r1",
        current_basis_sha256="a" * 64,
        effective=effective,
    )
    second_witness = SimpleNamespace(
        source_result="source-r2",
        current_basis_sha256="b" * 64,
        effective=effective,
    )
    states = iter(
        (
            SimpleNamespace(snapshot=snapshot, witness=first_witness),
            SimpleNamespace(snapshot=snapshot, witness=second_witness),
        )
    )

    monkeypatch.setattr(
        current_preview,
        "_capture_current_state",
        lambda *args, **kwargs: next(states),
    )
    monkeypatch.setattr(
        current_preview,
        "_load_source_authority",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        current_preview,
        "_build_family_explanation",
        lambda *args, **kwargs: object(),
    )

    with pytest.raises(GradePreviewCurrentnessConflictError):
        current_preview.explain_current_grade_preview(
            Path("."),
            current_support._target("standards_based"),
        )


def test_issue61_conventional_explanation_requires_exact_grade_item_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    item_ref = conventional_support._item_ref("essay", "1")
    item = conventional_support.GradePolicyItemParticipation(
        item_ref,
        None,
        None,
        conventional_support.Decimal("10"),
    )
    policy = conventional_support._policy(
        conventional_support.ConventionalGradeConfiguration(
            "total_points",
            (item,),
            (),
        )
    )
    snapshot, activation = conventional_support._snapshot(
        policy,
        conventional_support._input(
            item,
            earned="8",
            possible="10",
        ),
    )

    monkeypatch.setattr(
        conventional_explanation,
        "load_grade_item_revision",
        lambda *args, **kwargs: SimpleNamespace(
            revision=conventional_support._grade_item_revision(item_ref),
            revision_sha256="f" * 64,
        ),
    )

    with pytest.raises(GradePreviewIntegrityError, match="digest"):
        conventional_explanation.explain_conventional_grade_preview(
            tmp_path,
            snapshot,
            policy=policy,
            activation=activation,
            effective=conventional_support._effective(snapshot),
        )


def test_issue61_standards_explanation_requests_exact_historical_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = standards_support._configuration(
        ("std.a", "0.75"),
        ("std.b", "0.25"),
        minimum=2,
    )
    policy = standards_support._policy(config)
    first = standards_support._calculated(
        config.standards[0],
        "advanced",
        revision=3,
    )
    second = standards_support._calculated(
        config.standards[1],
        "beginning",
        revision=2,
        digest="d" * 64,
    )
    snapshot = standards_support._snapshot(policy, first, second)
    requested: list[object] = []
    by_standard = {
        "std.a": standards_support._nested_for(first),
        "std.b": standards_support._nested_for(second),
    }

    def nested(_root, target):
        requested.append(target)
        return by_standard[target.standard_id]

    monkeypatch.setattr(
        standards_explanation,
        "explain_academic_period_proficiency",
        nested,
    )

    standards_explanation.explain_standards_grade_preview(
        ".",
        snapshot,
        policy=policy,
        activation=standards_support._activation(policy),
        effective=standards_support._effective(snapshot),
    )

    assert [
        (target.selection, target.result_revision)
        for target in requested
    ] == [
        ("revision", 3),
        ("revision", 2),
    ]


def test_issue61_standards_nested_digest_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = standards_support._configuration(("std.a", "1"), minimum=1)
    policy = standards_support._policy(config)
    standard = standards_support._calculated(
        config.standards[0],
        "proficient",
        revision=4,
    )
    snapshot = standards_support._snapshot(policy, standard)

    monkeypatch.setattr(
        standards_explanation,
        "explain_academic_period_proficiency",
        lambda *args, **kwargs: standards_support._nested_for(
            standard,
            digest="f" * 64,
        ),
    )

    with pytest.raises(GradePreviewIntegrityError, match="exact Grade reference"):
        standards_explanation.explain_standards_grade_preview(
            ".",
            snapshot,
            policy=policy,
            activation=standards_support._activation(policy),
            effective=standards_support._effective(snapshot),
        )


def test_issue61_hybrid_explanation_uses_embedded_component_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, decision, snapshot = hybrid_support._snapshot()
    calls = hybrid_support._stub_component_builders(monkeypatch, snapshot)

    hybrid_explanation.explain_hybrid_grade_preview(
        Path("unused"),
        snapshot,
        policy=value,
        activation=decision,
        effective=hybrid_support._effective(snapshot),
    )

    assert calls["conventional_inputs"] is snapshot.inputs.conventional
    assert calls["standards_inputs"] is snapshot.inputs.standards_based


def test_issue61_hybrid_component_fingerprint_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, decision, snapshot = hybrid_support._snapshot()
    hybrid_support._stub_component_builders(monkeypatch, snapshot)
    exact = hybrid_support.calculate_conventional_grade(
        snapshot.inputs.conventional
    )
    changed = replace(
        exact,
        calculation_fingerprint="f" * 64,
    )
    monkeypatch.setattr(
        hybrid_explanation,
        "calculate_conventional_grade",
        lambda inputs: changed,
    )

    with pytest.raises(GradePreviewIntegrityError, match="fingerprint"):
        hybrid_explanation.explain_hybrid_grade_preview(
            Path("unused"),
            snapshot,
            policy=value,
            activation=decision,
            effective=hybrid_support._effective(snapshot),
        )
