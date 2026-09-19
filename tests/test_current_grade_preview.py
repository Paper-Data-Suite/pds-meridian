from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

import meridian.current_grade_preview as current
from meridian.conventional_grade import (
    calculate_conventional_grade,
    conventional_grade_result_reference,
    create_conventional_grade_result_snapshot,
)
from meridian.grade_preview_explanation import (
    GradePreviewCurrentnessConflictError,
    GradePreviewIntegrityError,
    GradePreviewSourceError,
    GradePreviewTarget,
    GradePreviewTargetError,
    GradePreviewTargetNotFoundError,
)
from meridian.hybrid_grade import calculate_hybrid_grade
from meridian.hybrid_grade_result import (
    HybridGradeResultReference,
    create_hybrid_grade_result_snapshot,
    hybrid_grade_result_snapshot_to_json_bytes,
)
from meridian.standards_grade import calculate_standards_grade
from meridian.standards_grade_result import (
    create_standards_grade_result_snapshot,
    standards_grade_result_reference,
)
from meridian.teacher_grade_override import GradeOverrideSourceResultReference
from meridian.teacher_grade_override_storage import (
    TeacherGradeOverrideStorageIntegrityError,
)
from meridian.teacher_grade_override_workflow import (
    TeacherGradeOverrideSelectedSource,
    TeacherGradeOverrideSourceResult,
)
from tests.issue52_hybrid_test_support import (
    CLASS_ID,
    NOW,
    PERIOD,
    STUDENT_ID,
    activation,
    conventional_input,
    hybrid_input,
    policy,
    standards_input,
)


def _target(family: str) -> GradePreviewTarget:
    return GradePreviewTarget(
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        family,  # type: ignore[arg-type]
    )


def _snapshots():
    value = policy()
    decision = activation(value)
    conventional_inputs = conventional_input(value, decision, earned="92")
    conventional_snapshot = create_conventional_grade_result_snapshot(
        conventional_inputs,
        calculate_conventional_grade(conventional_inputs),
        result_revision=1,
        calculated_at=NOW,
    )
    standards_inputs = standards_input(value, decision)
    standards_snapshot = create_standards_grade_result_snapshot(
        standards_inputs,
        calculate_standards_grade(standards_inputs),
        result_revision=1,
        calculated_at=NOW,
    )
    hybrid_inputs = hybrid_input(
        value,
        decision,
        conventional_inputs,
        standards_inputs,
    )
    hybrid_snapshot = create_hybrid_grade_result_snapshot(
        hybrid_inputs,
        calculate_hybrid_grade(hybrid_inputs),
        result_revision=1,
        calculated_at=NOW,
    )
    return value, decision, conventional_snapshot, standards_snapshot, hybrid_snapshot


def _hybrid_reference(snapshot) -> HybridGradeResultReference:
    digest = hashlib.sha256(
        hybrid_grade_result_snapshot_to_json_bytes(snapshot)
    ).hexdigest()
    return HybridGradeResultReference(
        snapshot.class_id,
        snapshot.student_id,
        snapshot.target_period.school_year,
        snapshot.target_period.period_id,
        snapshot.calendar_revision,
        snapshot.result_revision,
        digest,
    )


def _selected_source(family: str, reference) -> TeacherGradeOverrideSelectedSource:
    return TeacherGradeOverrideSelectedSource(
        source=TeacherGradeOverrideSourceResult(
            source_result=GradeOverrideSourceResultReference(
                family,  # type: ignore[arg-type]
                reference,
            ),
            source_status="calculated",
            base_grade=Decimal("90"),
        ),
        freshness_status="current",
        freshness_reasons=(),
    )


@pytest.mark.parametrize("family", ["conventional", "hybrid"])
def test_current_preview_requires_explicit_work_evidence(family: str) -> None:
    with pytest.raises(GradePreviewTargetError, match="work_evidence"):
        current.explain_current_grade_preview(Path("."), _target(family))


def test_standards_current_preview_rejects_work_evidence_argument() -> None:
    with pytest.raises(GradePreviewTargetError, match="does not accept"):
        current.explain_current_grade_preview(
            Path("."),
            _target("standards_based"),
            work_evidence=(),
        )


def test_stable_witness_returns_built_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, standards_snapshot, _ = _snapshots()
    witness = SimpleNamespace(effective=object())
    state = SimpleNamespace(snapshot=standards_snapshot, witness=witness)
    authority = object()
    built = object()
    calls: list[str] = []

    monkeypatch.setattr(
        current,
        "_capture_current_state",
        lambda *args, **kwargs: state,
    )
    monkeypatch.setattr(
        current,
        "_load_source_authority",
        lambda *args, **kwargs: authority,
    )

    def build(*args: object, **kwargs: object) -> object:
        calls.append("build")
        return built

    monkeypatch.setattr(current, "_build_family_explanation", build)

    result = current.explain_current_grade_preview(
        Path("."),
        _target("standards_based"),
    )

    assert result is built
    assert calls == ["build"]


def test_final_witness_change_is_currentness_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, standards_snapshot, _ = _snapshots()
    states = iter(
        (
            SimpleNamespace(
                snapshot=standards_snapshot,
                witness=SimpleNamespace(effective=object()),
            ),
            SimpleNamespace(
                snapshot=standards_snapshot,
                witness=SimpleNamespace(effective=object()),
            ),
        )
    )
    monkeypatch.setattr(
        current,
        "_capture_current_state",
        lambda *args, **kwargs: next(states),
    )
    monkeypatch.setattr(
        current,
        "_load_source_authority",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        current,
        "_build_family_explanation",
        lambda *args, **kwargs: object(),
    )

    with pytest.raises(GradePreviewCurrentnessConflictError):
        current.explain_current_grade_preview(
            Path("."),
            _target("standards_based"),
        )


def test_final_source_disappearance_is_currentness_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, standards_snapshot, _ = _snapshots()
    calls = 0

    def capture(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        if calls == 1:
            return SimpleNamespace(
                snapshot=standards_snapshot,
                witness=SimpleNamespace(effective=object()),
            )
        raise GradePreviewSourceError("selection disappeared")

    monkeypatch.setattr(current, "_capture_current_state", capture)
    monkeypatch.setattr(
        current,
        "_load_source_authority",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        current,
        "_build_family_explanation",
        lambda *args, **kwargs: object(),
    )

    with pytest.raises(GradePreviewCurrentnessConflictError):
        current.explain_current_grade_preview(
            Path("."),
            _target("standards_based"),
        )


def test_source_authority_uses_exact_historical_activation_and_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, decision, _, _, hybrid_snapshot = _snapshots()
    activation_calls: list[int] = []
    policy_calls: list[int] = []

    def load_activation(root, class_id, target_period, revision):
        del root, class_id, target_period
        activation_calls.append(revision)
        return SimpleNamespace(
            reference=hybrid_snapshot.activation_reference,
            decision=decision,
        )

    def load_policy(root, class_id, policy_id, revision):
        del root, class_id, policy_id
        policy_calls.append(revision)
        return SimpleNamespace(
            reference=hybrid_snapshot.policy_reference,
            policy=value,
        )

    monkeypatch.setattr(
        current,
        "load_grade_policy_activation_revision",
        load_activation,
    )
    monkeypatch.setattr(current, "load_grade_policy_revision", load_policy)

    authority = current._load_source_authority(
        Path("."),
        _target("hybrid"),
        hybrid_snapshot,
    )

    assert authority.activation == decision
    assert authority.policy == value
    assert activation_calls == [
        hybrid_snapshot.activation_reference.activation_revision
    ]
    assert policy_calls == [hybrid_snapshot.policy_reference.policy_revision]


def test_source_authority_digest_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value, decision, _, _, hybrid_snapshot = _snapshots()
    wrong_activation = SimpleNamespace(
        reference=hybrid_snapshot.activation_reference.__class__(
            hybrid_snapshot.activation_reference.class_id,
            hybrid_snapshot.activation_reference.school_year,
            hybrid_snapshot.activation_reference.period_id,
            hybrid_snapshot.activation_reference.activation_revision,
            "f" * 64,
        ),
        decision=decision,
    )
    monkeypatch.setattr(
        current,
        "load_grade_policy_activation_revision",
        lambda *args, **kwargs: wrong_activation,
    )
    monkeypatch.setattr(
        current,
        "load_grade_policy_revision",
        lambda *args, **kwargs: SimpleNamespace(
            reference=hybrid_snapshot.policy_reference,
            policy=value,
        ),
    )

    with pytest.raises(GradePreviewIntegrityError, match="activation digest"):
        current._load_source_authority(
            Path("."),
            _target("hybrid"),
            hybrid_snapshot,
        )


@pytest.mark.parametrize(
    ("family", "loader_name", "assembly_name", "snapshot_index"),
    [
        (
            "conventional",
            "load_current_conventional_grade_result",
            "assemble_conventional_grade_calculation",
            2,
        ),
        (
            "standards_based",
            "load_current_standards_grade_result",
            "assemble_standards_grade_calculation",
            3,
        ),
        (
            "hybrid",
            "load_current_hybrid_grade_result",
            "assemble_hybrid_grade_calculation",
            4,
        ),
    ],
)
def test_family_capture_uses_selected_snapshot_and_exact_current_basis(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    loader_name: str,
    assembly_name: str,
    snapshot_index: int,
) -> None:
    values = _snapshots()
    snapshot = values[snapshot_index]
    if family == "conventional":
        reference = conventional_grade_result_reference(snapshot)
    elif family == "standards_based":
        reference = standards_grade_result_reference(snapshot)
    else:
        reference = _hybrid_reference(snapshot)
    stored = SimpleNamespace(snapshot=snapshot, reference=reference)
    assembly = SimpleNamespace(
        inputs=snapshot.inputs,
        activation=SimpleNamespace(reference=snapshot.activation_reference),
        policy=SimpleNamespace(reference=snapshot.policy_reference),
    )
    monkeypatch.setattr(current, loader_name, lambda *args, **kwargs: stored)
    monkeypatch.setattr(current, assembly_name, lambda *args, **kwargs: assembly)
    monkeypatch.setattr(
        current,
        "_finish_current_witness",
        lambda *args, **kwargs: object(),
    )
    selector_guard = {
        "conventional": "_require_conventional_selection_unchanged",
        "standards_based": "_require_standards_selection_unchanged",
        "hybrid": "_require_hybrid_selection_unchanged",
    }[family]
    monkeypatch.setattr(current, selector_guard, lambda *args, **kwargs: None)

    target = _target(family)
    if family == "conventional":
        state = current._capture_conventional_state(Path("."), target, ())
    elif family == "standards_based":
        state = current._capture_standards_state(Path("."), target)
    else:
        state = current._capture_hybrid_state(Path("."), target, ())

    assert state.snapshot == snapshot


@pytest.mark.parametrize(
    ("family", "loader_name", "capture_name"),
    [
        (
            "conventional",
            "load_current_conventional_grade_result",
            "_capture_conventional_state",
        ),
        (
            "standards_based",
            "load_current_standards_grade_result",
            "_capture_standards_state",
        ),
        ("hybrid", "load_current_hybrid_grade_result", "_capture_hybrid_state"),
    ],
)
def test_missing_selected_result_is_explicit_target_not_found(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    loader_name: str,
    capture_name: str,
) -> None:
    monkeypatch.setattr(current, loader_name, lambda *args, **kwargs: None)
    capture = getattr(current, capture_name)
    args = [Path("."), _target(family)]
    if family in {"conventional", "hybrid"}:
        args.append(())

    with pytest.raises(
        GradePreviewTargetNotFoundError,
        match="no explicit current",
    ) as raised:
        capture(*args)
    assert raised.value.code == "grade_preview.target_not_found"


def test_override_pointer_movement_fails_currentness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, conventional_snapshot, _, _ = _snapshots()
    reference = conventional_grade_result_reference(conventional_snapshot)
    source = _selected_source("conventional", reference)
    monkeypatch.setattr(
        current,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        current,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: object(),
    )

    with pytest.raises(GradePreviewCurrentnessConflictError):
        current._resolve_effective(Path("."), _target("conventional"), source)


def test_override_storage_corruption_fails_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, conventional_snapshot, _, _ = _snapshots()
    source = _selected_source(
        "conventional",
        conventional_grade_result_reference(conventional_snapshot),
    )

    def corrupt(*args: object, **kwargs: object):
        raise TeacherGradeOverrideStorageIntegrityError("corrupt current selector")

    monkeypatch.setattr(current, "load_current_teacher_grade_override", corrupt)

    with pytest.raises(GradePreviewIntegrityError, match="override is invalid"):
        current._resolve_effective(Path("."), _target("conventional"), source)


def test_conventional_selector_movement_inside_capture_is_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, conventional_snapshot, _, _ = _snapshots()
    first_reference = conventional_grade_result_reference(conventional_snapshot)
    moved_reference = first_reference.__class__(
        first_reference.class_id,
        first_reference.student_id,
        first_reference.school_year,
        first_reference.period_id,
        first_reference.calendar_revision,
        2,
        "e" * 64,
    )
    reads = iter(
        (
            SimpleNamespace(
                snapshot=conventional_snapshot,
                reference=first_reference,
            ),
            SimpleNamespace(
                snapshot=conventional_snapshot,
                reference=moved_reference,
            ),
        )
    )
    monkeypatch.setattr(
        current,
        "load_current_conventional_grade_result",
        lambda *args, **kwargs: next(reads),
    )
    monkeypatch.setattr(
        current,
        "assemble_conventional_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(
            inputs=conventional_snapshot.inputs,
            activation=SimpleNamespace(
                reference=conventional_snapshot.activation_reference,
            ),
            policy=SimpleNamespace(reference=conventional_snapshot.policy_reference),
        ),
    )
    monkeypatch.setattr(
        current,
        "_finish_current_witness",
        lambda *args, **kwargs: object(),
    )

    with pytest.raises(GradePreviewCurrentnessConflictError):
        current._capture_conventional_state(
            Path("."),
            _target("conventional"),
            (),
        )


@pytest.mark.parametrize(
    ("family", "snapshot_index", "function_name"),
    [
        ("conventional", 2, "explain_conventional_grade_preview"),
        ("standards_based", 3, "explain_standards_grade_preview"),
        ("hybrid", 4, "explain_hybrid_grade_preview"),
    ],
)
def test_family_explanation_dispatch_uses_exact_selected_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    snapshot_index: int,
    function_name: str,
) -> None:
    values = _snapshots()
    snapshot = values[snapshot_index]
    authority = SimpleNamespace(policy=values[0], activation=values[1])
    sentinel = object()
    calls: list[object] = []

    def explain(root, selected, **kwargs):
        del root, kwargs
        calls.append(selected)
        return sentinel

    monkeypatch.setattr(current, function_name, explain)

    result = current._build_family_explanation(
        Path("."),
        snapshot,
        authority,
        object(),  # type: ignore[arg-type]
    )

    assert result is sentinel
    assert calls == [snapshot]
