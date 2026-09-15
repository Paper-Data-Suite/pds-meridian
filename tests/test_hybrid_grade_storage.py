from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

import meridian.hybrid_grade_storage as storage
from meridian.hybrid_grade import calculate_hybrid_grade
from meridian.hybrid_grade_result import create_hybrid_grade_result_snapshot
from meridian.hybrid_grade_storage import (
    HybridGradeResultDependencyError,
    HybridGradeStorageConflictError,
    HybridGradeStorageIntegrityError,
    get_current_hybrid_grade_result_revision,
    hybrid_grade_result_current_path,
    hybrid_grade_result_family_directory,
    list_hybrid_grade_result_revisions,
    load_current_hybrid_grade_result,
    load_hybrid_grade_result_revision,
    select_hybrid_grade_result_revision,
    write_hybrid_grade_result_revision,
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


def _workspace(tmp_path):
    (tmp_path / "classes" / CLASS_ID).mkdir(parents=True)
    return tmp_path


def _basis():
    value = policy()
    decision = activation(value)
    inputs = hybrid_input(
        value,
        decision,
        conventional_input(value, decision, earned="92"),
        standards_input(value, decision),
    )
    return inputs, calculate_hybrid_grade(inputs)


def _snapshot(revision: int = 1):
    inputs, outcome = _basis()
    return create_hybrid_grade_result_snapshot(
        inputs,
        outcome,
        result_revision=revision,
        calculated_at=NOW + timedelta(seconds=revision - 1),
    )


def _accept_current_basis(monkeypatch, snapshot, calls=None) -> None:
    def assemble(*args, **kwargs):
        if calls is not None:
            calls.append((args, kwargs))
        return SimpleNamespace(inputs=snapshot.inputs, outcome=snapshot.outcome)

    monkeypatch.setattr(storage, "assemble_hybrid_grade_calculation", assemble)


def test_write_is_immutable_private_path_and_does_not_select(
    tmp_path,
    monkeypatch,
) -> None:
    root = _workspace(tmp_path)
    snapshot = _snapshot()
    calls: list[object] = []
    _accept_current_basis(monkeypatch, snapshot, calls)

    written = write_hybrid_grade_result_revision(
        root,
        snapshot,
        work_evidence=(),
    )

    assert written.disposition == "created"
    assert written.stored.snapshot == snapshot
    assert list_hybrid_grade_result_revisions(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    ) == (1,)
    assert get_current_hybrid_grade_result_revision(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    ) is None
    assert load_current_hybrid_grade_result(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    ) is None
    assert len(calls) == 2
    for args, _kwargs in calls:
        assert args[-1] == ()

    family = hybrid_grade_result_family_directory(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    )
    assert family.name != STUDENT_ID
    assert STUDENT_ID not in str(family.relative_to(root))


def test_exact_write_retry_is_existing_but_changed_bytes_conflict(
    tmp_path,
    monkeypatch,
) -> None:
    root = _workspace(tmp_path)
    snapshot = _snapshot()
    _accept_current_basis(monkeypatch, snapshot)

    first = write_hybrid_grade_result_revision(root, snapshot, work_evidence=())
    second = write_hybrid_grade_result_revision(root, snapshot, work_evidence=())
    assert first.disposition == "created"
    assert second.disposition == "existing"

    changed = replace(snapshot, calculated_at=NOW + timedelta(seconds=10))
    with pytest.raises(HybridGradeStorageConflictError, match="different content"):
        write_hybrid_grade_result_revision(root, changed, work_evidence=())


def test_explicit_selection_uses_cas_and_allows_historical_reselection(
    tmp_path,
    monkeypatch,
) -> None:
    root = _workspace(tmp_path)
    first = _snapshot()
    _accept_current_basis(monkeypatch, first)
    write_hybrid_grade_result_revision(root, first, work_evidence=())

    second = _snapshot(2)
    _accept_current_basis(monkeypatch, second)
    write_hybrid_grade_result_revision(root, second, work_evidence=())

    monkeypatch.setattr(
        storage,
        "_validate_historical_dependencies",
        lambda *args: None,
    )
    selected1 = select_hybrid_grade_result_revision(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )
    assert selected1.disposition == "created"

    with pytest.raises(HybridGradeStorageConflictError, match="Expected current"):
        select_hybrid_grade_result_revision(
            root,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            2,
            expected_current_result_revision=None,
        )

    selected2 = select_hybrid_grade_result_revision(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        2,
        expected_current_result_revision=1,
    )
    assert selected2.disposition == "updated"
    reselected = select_hybrid_grade_result_revision(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        1,
        expected_current_result_revision=2,
    )
    assert reselected.disposition == "updated"
    current = load_current_hybrid_grade_result(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    )
    assert current is not None
    assert current.snapshot.result_revision == 1


def test_source_basis_change_before_commit_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    root = _workspace(tmp_path)
    snapshot = _snapshot()
    item = snapshot.inputs.conventional.items[0]
    changed_conventional = replace(
        snapshot.inputs.conventional,
        items=(replace(item, earned=item.earned - 1),),
    )
    changed_inputs = replace(
        snapshot.inputs,
        conventional=changed_conventional,
    )
    monkeypatch.setattr(
        storage,
        "assemble_hybrid_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(
            inputs=changed_inputs,
            outcome=calculate_hybrid_grade(changed_inputs),
        ),
    )

    with pytest.raises(HybridGradeStorageConflictError, match="inputs changed"):
        write_hybrid_grade_result_revision(root, snapshot, work_evidence=())


def test_corrupt_digest_and_pointer_are_rejected(tmp_path, monkeypatch) -> None:
    root = _workspace(tmp_path)
    snapshot = _snapshot()
    _accept_current_basis(monkeypatch, snapshot)
    written = write_hybrid_grade_result_revision(root, snapshot, work_evidence=())

    digest_path = written.stored.path.with_suffix(".json.sha256")
    original_digest = digest_path.read_bytes()
    digest_path.write_text("0" * 64 + "\n", encoding="ascii")
    with pytest.raises(HybridGradeStorageIntegrityError, match="digest"):
        load_hybrid_grade_result_revision(
            root,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            1,
        )
    digest_path.write_bytes(original_digest)

    monkeypatch.setattr(
        storage,
        "_validate_historical_dependencies",
        lambda *args: None,
    )
    select_hybrid_grade_result_revision(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )
    pointer = hybrid_grade_result_current_path(
        root,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
    )
    text = pointer.read_text(encoding="utf-8").replace(
        '"result_sha256": "',
        '"result_sha256": "f',
        1,
    )
    pointer.write_text(text, encoding="utf-8")
    with pytest.raises(HybridGradeStorageIntegrityError):
        load_current_hybrid_grade_result(
            root,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
        )


def test_historical_dependency_validation_uses_exact_immutable_dependencies(
    tmp_path,
    monkeypatch,
) -> None:
    root = _workspace(tmp_path)
    snapshot = _snapshot()
    configuration = snapshot.inputs.configuration
    item_ref = configuration.conventional.items[0].grade_item
    scale_ref = configuration.standards_based.target_scale
    standard = snapshot.inputs.standards_based.standards[0]
    assert standard.result_reference is not None

    monkeypatch.setattr(
        storage,
        "load_grade_policy_activation_revision",
        lambda *args: SimpleNamespace(
            activation_sha256=snapshot.activation_reference.activation_sha256,
            decision=SimpleNamespace(
                decision="activate",
                calendar_revision=snapshot.calendar_revision,
                policy_reference=snapshot.policy_reference,
            ),
        ),
    )
    monkeypatch.setattr(
        storage,
        "load_grade_policy_revision",
        lambda *args: SimpleNamespace(
            policy_sha256=snapshot.policy_reference.policy_sha256,
            policy=SimpleNamespace(
                calculation_family="hybrid",
                configuration=configuration,
            ),
        ),
    )
    monkeypatch.setattr(
        storage,
        "load_grade_item_revision",
        lambda *args: SimpleNamespace(
            revision_sha256=item_ref.grade_item_revision_sha256,
        ),
    )
    monkeypatch.setattr(
        storage,
        "load_proficiency_scale_revision",
        lambda *args: SimpleNamespace(scale_sha256=scale_ref.scale_sha256),
    )
    monkeypatch.setattr(
        storage,
        "load_academic_period_proficiency_result_revision",
        lambda *args: SimpleNamespace(
            result_sha256=standard.result_reference.result_sha256,
        ),
    )

    storage._validate_historical_dependencies(root, snapshot)

    monkeypatch.setattr(
        storage,
        "load_grade_item_revision",
        lambda *args: SimpleNamespace(revision_sha256="0" * 64),
    )
    with pytest.raises(HybridGradeResultDependencyError, match="Grade Item digest"):
        storage._validate_historical_dependencies(root, snapshot)
