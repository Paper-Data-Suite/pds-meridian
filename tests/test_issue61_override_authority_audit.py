from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

import meridian.effective_grade as effective
import meridian.teacher_grade_override_lifecycle as lifecycle
from meridian.teacher_grade_override import (
    teacher_grade_override_reference,
)
from meridian.teacher_grade_override_storage import (
    get_current_teacher_grade_override_reference,
    load_current_teacher_grade_override,
    select_teacher_grade_override_revision,
    write_teacher_grade_override_revision,
)
from tests import test_effective_grade as effective_support
from tests import test_teacher_grade_override_lifecycle as lifecycle_support
from tests import test_teacher_grade_override_storage as storage_support


@pytest.mark.parametrize(
    "family",
    ("conventional", "standards_based", "hybrid"),
)
def test_issue61_override_does_not_float_to_new_result_revision(
    family: str,
) -> None:
    first = effective_support.selected_source(
        family,
        revision=1,
        digest="a" * 64,
        grade=Decimal("88.25"),
    )
    decision = effective_support.active_override(
        first.source_result,
        replacement=Decimal("95"),
    )
    second = effective_support.selected_source(
        family,
        revision=2,
        digest="b" * 64,
        grade=Decimal("88.25"),
    )

    result = effective.resolve_effective_grade(
        second,
        selected_override_reference=teacher_grade_override_reference(decision),
        selected_override=decision,
    )

    assert result.base_grade == Decimal("88.25")
    assert result.override_applicability == "source_result_changed"
    assert result.override_reasons == ("source_result_mismatch",)
    assert result.effective_grade == Decimal("88.25")
    assert result.effective_source == "base"


@pytest.mark.parametrize(
    "family",
    ("conventional", "standards_based", "hybrid"),
)
def test_issue61_override_binding_includes_source_digest(
    family: str,
) -> None:
    first = effective_support.selected_source(
        family,
        revision=1,
        digest="a" * 64,
    )
    decision = effective_support.active_override(first.source_result)
    same_revision_changed_bytes = effective_support.selected_source(
        family,
        revision=1,
        digest="b" * 64,
    )

    result = effective.resolve_effective_grade(
        same_revision_changed_bytes,
        selected_override_reference=teacher_grade_override_reference(decision),
        selected_override=decision,
    )

    assert result.override_applicability == "source_result_changed"
    assert result.override_reasons == ("source_result_mismatch",)
    assert result.effective_source == "base"


@pytest.mark.parametrize(
    "family",
    ("conventional", "standards_based", "hybrid"),
)
def test_issue61_exact_override_cannot_make_stale_source_current(
    family: str,
) -> None:
    source = effective_support.selected_source(
        family,
        freshness="stale",
        reasons=("policy_changed",),
    )
    decision = effective_support.active_override(source.source_result)

    result = effective.resolve_effective_grade(
        source,
        selected_override_reference=teacher_grade_override_reference(decision),
        selected_override=decision,
    )

    assert result.base_freshness_status == "stale"
    assert result.override_applicability == "source_result_stale"
    assert result.override_reasons == ("source_result_stale",)
    assert result.effective_grade is None
    assert result.effective_source == "none"


def test_issue61_override_reference_must_bind_exact_decision_bytes() -> None:
    source = effective_support.selected_source()
    decision = effective_support.active_override(source.source_result)
    wrong = replace(
        teacher_grade_override_reference(decision),
        override_sha256="f" * 64,
    )

    with pytest.raises(effective.EffectiveGradeScopeError):
        effective.resolve_effective_grade(
            source,
            selected_override_reference=wrong,
            selected_override=decision,
        )


def test_issue61_teacher_workflow_rejects_historical_override_reselection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical = lifecycle_support.active_override()
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1, 2),
    )

    with pytest.raises(lifecycle.TeacherGradeOverrideSelectionScopeError):
        lifecycle.preview_teacher_grade_override_selection(
            Path("."),
            teacher_grade_override_reference(historical),
        )


def test_issue61_withdrawal_write_is_inert_until_explicit_selection(
    tmp_path: Path,
) -> None:
    root = storage_support.make_workspace(tmp_path)
    active = storage_support.override_decision()
    stored_active = write_teacher_grade_override_revision(root, active).stored
    select_teacher_grade_override_revision(
        root,
        stored_active.reference,
        expected_current=None,
    )

    withdrawal = storage_support.withdrawal(
        active,
        revision=2,
        withdrawn_reference=stored_active.reference,
    )
    stored_withdrawal = write_teacher_grade_override_revision(
        root,
        withdrawal,
    ).stored

    assert get_current_teacher_grade_override_reference(
        root,
        storage_support.CLASS_ID,
        storage_support.STUDENT_ID,
        storage_support.PERIOD,
        1,
        "conventional",
    ) == stored_active.reference

    select_teacher_grade_override_revision(
        root,
        stored_withdrawal.reference,
        expected_current=stored_active.reference,
    )
    selected = load_current_teacher_grade_override(
        root,
        storage_support.CLASS_ID,
        storage_support.STUDENT_ID,
        storage_support.PERIOD,
        1,
        "conventional",
    )

    assert selected is not None
    assert selected.reference == stored_withdrawal.reference
    assert selected.decision.decision == "withdraw"


def test_issue61_selected_withdrawal_restores_only_current_base_authority() -> None:
    current = effective_support.selected_source()
    prior = effective_support.active_override(
        current.source_result,
        replacement=Decimal("95"),
    )
    withdrawal = effective_support.withdrawal(prior)

    result = effective.resolve_effective_grade(
        current,
        selected_override_reference=teacher_grade_override_reference(withdrawal),
        selected_override=withdrawal,
    )

    assert result.override_applicability == "withdrawn"
    assert result.override_reasons == ("selected_override_withdrawn",)
    assert result.effective_grade == current.base_grade
    assert result.effective_source == "base"

    stale = effective_support.selected_source(
        freshness="stale",
        reasons=("inputs_changed",),
    )
    stale_prior = effective_support.active_override(stale.source_result)
    stale_withdrawal = effective_support.withdrawal(stale_prior)

    stale_result = effective.resolve_effective_grade(
        stale,
        selected_override_reference=teacher_grade_override_reference(
            stale_withdrawal
        ),
        selected_override=stale_withdrawal,
    )

    assert stale_result.override_applicability == "withdrawn"
    assert stale_result.effective_grade is None
    assert stale_result.effective_source == "none"


def test_issue61_withdrawal_is_bound_to_exact_active_override(
    tmp_path: Path,
) -> None:
    root = storage_support.make_workspace(tmp_path)
    active = storage_support.override_decision()
    stored = write_teacher_grade_override_revision(root, active).stored

    wrong_reference = replace(
        stored.reference,
        override_sha256="b" * 64,
    )
    candidate = storage_support.withdrawal(
        active,
        withdrawn_reference=wrong_reference,
    )

    with pytest.raises(
        storage_support.TeacherGradeOverrideStorageConflictError
    ):
        write_teacher_grade_override_revision(root, candidate)
