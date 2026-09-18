from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.teacher_grade_override_lifecycle as lifecycle
from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.grade_policy import GradePolicyActor
from meridian.teacher_grade_override import (
    TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
    TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideDecision,
    TeacherGradeOverrideReference,
    teacher_grade_override_decision_to_json_bytes,
    teacher_grade_override_reference,
)
from meridian.teacher_grade_override_lifecycle import (
    TeacherGradeOverrideSelectionScopeError,
    TeacherGradeOverrideSelectionStaleError,
    TeacherGradeOverrideWithdrawalScopeError,
    TeacherGradeOverrideWithdrawalStaleError,
    commit_teacher_grade_override_selection_preview,
    commit_teacher_grade_override_withdrawal_preview,
    preview_teacher_grade_override_selection,
    preview_teacher_grade_override_withdrawal,
)
from meridian.teacher_grade_override_storage import (
    TeacherGradeOverrideStorageConflictError,
)
from meridian.teacher_grade_override_workflow import (
    TeacherGradeOverrideSourceResult,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "student_001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 17, 18, 0, tzinfo=UTC)


def source_reference(
    *,
    revision: int = 1,
    digest: str = "a" * 64,
) -> GradeOverrideSourceResultReference:
    return GradeOverrideSourceResultReference(
        "conventional",
        ConventionalGradeResultReference(
            class_id=CLASS_ID,
            student_id=STUDENT_ID,
            school_year=PERIOD.school_year,
            period_id=PERIOD.period_id,
            calendar_revision=1,
            result_revision=revision,
            result_sha256=digest,
        ),
    )


def active_override(
    *,
    revision: int = 1,
    source: GradeOverrideSourceResultReference | None = None,
    replacement: str = "90",
    decided_at: datetime = NOW,
) -> TeacherGradeOverrideDecision:
    exact_source = source or source_reference()
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="conventional",
        override_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision="override",
        source_result=exact_source,
        replacement_grade=Decimal(replacement),
        withdrawn_override_reference=None,
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=f"Active override revision {revision}.",
        decided_at=decided_at,
    )


def withdrawal(
    selected: TeacherGradeOverrideDecision,
    *,
    revision: int,
    supersedes: int,
    decided_at: datetime,
) -> TeacherGradeOverrideDecision:
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="conventional",
        override_revision=revision,
        supersedes_revision=supersedes,
        decision="withdraw",
        source_result=selected.source_result,
        replacement_grade=None,
        withdrawn_override_reference=teacher_grade_override_reference(selected),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Withdraw exact selected override.",
        decided_at=decided_at,
    )


def stored(decision: TeacherGradeOverrideDecision) -> SimpleNamespace:
    reference = teacher_grade_override_reference(decision)
    return SimpleNamespace(
        decision=decision,
        reference=reference,
        override_sha256=reference.override_sha256,
    )


def exact_source(
    reference: GradeOverrideSourceResultReference | None = None,
) -> TeacherGradeOverrideSourceResult:
    return TeacherGradeOverrideSourceResult(
        source_result=reference or source_reference(),
        source_status="calculated",
        base_grade=Decimal("76.5"),
    )


def selection_preview(
    *,
    current: TeacherGradeOverrideReference | None = None,
) -> lifecycle.TeacherGradeOverrideSelectionPreview:
    target = active_override()
    return lifecycle.TeacherGradeOverrideSelectionPreview(
        target_reference=teacher_grade_override_reference(target),
        target_decision=target,
        history=(1,),
        expected_current=current,
    )


def withdrawal_preview() -> lifecycle.TeacherGradeOverrideWithdrawalPreview:
    selected = active_override()
    candidate = withdrawal(
        selected,
        revision=2,
        supersedes=1,
        decided_at=NOW + timedelta(minutes=1),
    )
    content = teacher_grade_override_decision_to_json_bytes(candidate)
    return lifecycle.TeacherGradeOverrideWithdrawalPreview(
        selected_override_reference=teacher_grade_override_reference(selected),
        selected_override_decision=selected,
        source=exact_source(selected.source_result),
        history_before=(1,),
        latest_override_sha256_before=teacher_grade_override_reference(
            selected
        ).override_sha256,
        candidate=candidate,
        candidate_sha256=hashlib.sha256(content).hexdigest(),
    )


def test_selection_preview_binds_latest_exact_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = active_override(revision=2, decided_at=NOW + timedelta(minutes=1))
    current = teacher_grade_override_reference(active_override())
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1, 2),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: stored(target),
    )
    monkeypatch.setattr(
        lifecycle,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: current,
    )

    preview = preview_teacher_grade_override_selection(
        Path("."),
        teacher_grade_override_reference(target),
    )

    assert preview.target_reference == teacher_grade_override_reference(target)
    assert preview.target_decision == target
    assert preview.history == (1, 2)
    assert preview.expected_current == current


def test_selection_preview_rejects_historical_revision_even_if_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical = active_override()
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1, 2),
    )

    with pytest.raises(TeacherGradeOverrideSelectionScopeError):
        preview_teacher_grade_override_selection(
            Path("."),
            teacher_grade_override_reference(historical),
        )


def test_selection_preview_rejects_wrong_digest_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = active_override()
    wrong = replace(
        teacher_grade_override_reference(target),
        override_sha256="f" * 64,
    )
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: stored(target),
    )
    monkeypatch.setattr(
        lifecycle,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(TeacherGradeOverrideSelectionScopeError):
        preview_teacher_grade_override_selection(Path("."), wrong)


def test_selection_commit_uses_exact_cas_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_decision = active_override(
        replacement="88",
    )
    current = teacher_grade_override_reference(current_decision)
    target = active_override(
        revision=2,
        replacement="92",
        decided_at=NOW + timedelta(minutes=1),
    )
    preview = lifecycle.TeacherGradeOverrideSelectionPreview(
        target_reference=teacher_grade_override_reference(target),
        target_decision=target,
        history=(1, 2),
        expected_current=current,
    )
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1, 2),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: stored(target),
    )
    monkeypatch.setattr(
        lifecycle,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: current,
    )
    observed: list[TeacherGradeOverrideReference | None] = []

    def select(
        root: object,
        reference: TeacherGradeOverrideReference,
        *,
        expected_current: TeacherGradeOverrideReference | None,
    ) -> SimpleNamespace:
        observed.append(expected_current)
        return SimpleNamespace(
            disposition="updated",
            stored=stored(target),
        )

    monkeypatch.setattr(lifecycle, "select_teacher_grade_override_revision", select)

    result = commit_teacher_grade_override_selection_preview(Path("."), preview)

    assert observed == [current]
    assert result.target_reference == teacher_grade_override_reference(target)
    assert result.previous_current == current
    assert result.selection_disposition == "updated"


def test_selection_commit_detects_history_change_before_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = selection_preview()
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1, 2),
    )

    with pytest.raises(TeacherGradeOverrideSelectionStaleError):
        commit_teacher_grade_override_selection_preview(Path("."), preview)


def test_selection_commit_detects_current_change_before_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = selection_preview()
    changed = TeacherGradeOverrideReference(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        school_year=PERIOD.school_year,
        period_id=PERIOD.period_id,
        calendar_revision=1,
        calculation_family="conventional",
        override_revision=1,
        override_sha256="f" * 64,
    )
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: stored(preview.target_decision),
    )
    monkeypatch.setattr(
        lifecycle,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: changed,
    )

    with pytest.raises(TeacherGradeOverrideSelectionStaleError):
        commit_teacher_grade_override_selection_preview(Path("."), preview)


def test_selection_storage_cas_conflict_maps_to_workflow_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = selection_preview()
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: stored(preview.target_decision),
    )
    monkeypatch.setattr(
        lifecycle,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: None,
    )

    def conflict(*args: object, **kwargs: object) -> None:
        raise TeacherGradeOverrideStorageConflictError("CAS conflict")

    monkeypatch.setattr(
        lifecycle,
        "select_teacher_grade_override_revision",
        conflict,
    )

    with pytest.raises(TeacherGradeOverrideSelectionStaleError):
        commit_teacher_grade_override_selection_preview(Path("."), preview)


def test_latest_withdrawal_decision_can_be_explicitly_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = active_override()
    target = withdrawal(
        selected,
        revision=2,
        supersedes=1,
        decided_at=NOW + timedelta(minutes=1),
    )
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1, 2),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: stored(target),
    )
    monkeypatch.setattr(
        lifecycle,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: teacher_grade_override_reference(selected),
    )

    preview = preview_teacher_grade_override_selection(
        Path("."),
        teacher_grade_override_reference(target),
    )

    assert preview.target_decision.decision == "withdraw"


def test_withdrawal_preview_requires_selected_active_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lifecycle,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(TeacherGradeOverrideWithdrawalScopeError):
        preview_teacher_grade_override_withdrawal(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            "conventional",
            actor_id="teacher_local",
            rationale="Withdraw.",
            decided_at=NOW,
        )


def test_withdrawal_preview_rejects_selected_withdrawal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = active_override()
    withdrawn = withdrawal(
        active,
        revision=2,
        supersedes=1,
        decided_at=NOW + timedelta(minutes=1),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: stored(withdrawn),
    )

    with pytest.raises(TeacherGradeOverrideWithdrawalScopeError):
        preview_teacher_grade_override_withdrawal(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            "conventional",
            actor_id="teacher_local",
            rationale="Cannot withdraw a withdrawal.",
            decided_at=NOW + timedelta(minutes=2),
        )


def test_withdrawal_can_target_selected_historical_active_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = active_override()
    latest = active_override(
        revision=2,
        source=source_reference(revision=2, digest="b" * 64),
        replacement="91",
        decided_at=NOW + timedelta(minutes=1),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: stored(selected),
    )
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1, 2),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: stored(latest),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_source_result",
        lambda *args, **kwargs: exact_source(selected.source_result),
    )

    preview = preview_teacher_grade_override_withdrawal(
        Path("."),
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        "conventional",
        actor_id="teacher_local",
        rationale="Withdraw currently selected historical authority.",
        decided_at=NOW + timedelta(minutes=2),
    )

    assert preview.candidate.override_revision == 3
    assert preview.candidate.supersedes_revision == 2
    assert preview.candidate.withdrawn_override_reference == (
        teacher_grade_override_reference(selected)
    )
    assert preview.candidate.source_result == selected.source_result


def test_withdrawal_preview_loads_exact_source_not_selected_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = active_override()
    monkeypatch.setattr(
        lifecycle,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: stored(selected),
    )
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: stored(selected),
    )
    observed: list[GradeOverrideSourceResultReference] = []

    def load_source(
        root: object,
        reference: GradeOverrideSourceResultReference,
    ) -> TeacherGradeOverrideSourceResult:
        observed.append(reference)
        return exact_source(reference)

    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_source_result",
        load_source,
    )

    preview_teacher_grade_override_withdrawal(
        Path("."),
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        "conventional",
        actor_id="teacher_local",
        rationale="Source may no longer be selected but remains exact history.",
        decided_at=NOW + timedelta(minutes=1),
    )

    assert observed == [selected.source_result]


def test_withdrawal_preview_rejects_backwards_chronology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = active_override(decided_at=NOW + timedelta(minutes=10))
    monkeypatch.setattr(
        lifecycle,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: stored(selected),
    )
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: stored(selected),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_source_result",
        lambda *args, **kwargs: exact_source(selected.source_result),
    )

    with pytest.raises(TeacherGradeOverrideWithdrawalScopeError):
        preview_teacher_grade_override_withdrawal(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            "conventional",
            actor_id="teacher_local",
            rationale="Chronology must remain monotonic.",
            decided_at=NOW + timedelta(minutes=1),
        )


def test_withdrawal_commit_revalidates_selected_active_inside_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = withdrawal_preview()
    selected = stored(preview.selected_override_decision)
    current_calls: list[int] = []
    source_calls: list[int] = []
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: selected,
    )

    def load_current(*args: object, **kwargs: object) -> SimpleNamespace:
        current_calls.append(1)
        return selected

    def load_source(
        *args: object, **kwargs: object
    ) -> TeacherGradeOverrideSourceResult:
        source_calls.append(1)
        return preview.source

    monkeypatch.setattr(lifecycle, "load_current_teacher_grade_override", load_current)
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_source_result",
        load_source,
    )

    def write(
        root: object,
        candidate: TeacherGradeOverrideDecision,
        *,
        precommit_guard: object,
    ) -> SimpleNamespace:
        assert callable(precommit_guard)
        precommit_guard()
        return SimpleNamespace(
            disposition="created",
            stored=stored(candidate),
        )

    monkeypatch.setattr(lifecycle, "write_teacher_grade_override_revision", write)
    monkeypatch.setattr(
        lifecycle,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: preview.selected_override_reference,
    )

    result = commit_teacher_grade_override_withdrawal_preview(Path("."), preview)

    assert result.write_disposition == "created"
    assert result.selected_override_after == preview.selected_override_reference
    assert current_calls == [1, 1]
    assert source_calls == [1, 1, 1]


def test_withdrawal_commit_does_not_require_source_to_remain_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = withdrawal_preview()
    selected = stored(preview.selected_override_decision)
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: selected,
    )
    monkeypatch.setattr(
        lifecycle,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: selected,
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_source_result",
        lambda *args, **kwargs: preview.source,
    )

    def write(
        root: object,
        candidate: TeacherGradeOverrideDecision,
        *,
        precommit_guard: object,
    ) -> SimpleNamespace:
        assert callable(precommit_guard)
        precommit_guard()
        return SimpleNamespace(disposition="created", stored=stored(candidate))

    monkeypatch.setattr(lifecycle, "write_teacher_grade_override_revision", write)
    monkeypatch.setattr(
        lifecycle,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: preview.selected_override_reference,
    )
    assert not hasattr(lifecycle, "load_selected_teacher_grade_override_source")

    result = commit_teacher_grade_override_withdrawal_preview(Path("."), preview)

    assert result.stored_reference == teacher_grade_override_reference(
        preview.candidate
    )


def test_withdrawal_commit_blocks_if_selected_override_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = withdrawal_preview()
    changed = stored(
        active_override(
            revision=2,
            source=source_reference(revision=2, digest="b" * 64),
            replacement="91",
            decided_at=NOW + timedelta(minutes=1),
        )
    )
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: stored(preview.selected_override_decision),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_source_result",
        lambda *args, **kwargs: preview.source,
    )
    monkeypatch.setattr(
        lifecycle,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: changed,
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("changed selection must block withdrawal write")

    monkeypatch.setattr(lifecycle, "write_teacher_grade_override_revision", forbidden)

    with pytest.raises(TeacherGradeOverrideWithdrawalStaleError):
        commit_teacher_grade_override_withdrawal_preview(Path("."), preview)


def test_withdrawal_guard_detects_selection_change_under_write_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = withdrawal_preview()
    original = stored(preview.selected_override_decision)
    changed = stored(
        active_override(
            revision=2,
            source=source_reference(revision=2, digest="b" * 64),
            replacement="91",
            decided_at=NOW + timedelta(minutes=1),
        )
    )
    values = iter((original, changed))
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: original,
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_source_result",
        lambda *args, **kwargs: preview.source,
    )
    monkeypatch.setattr(
        lifecycle,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: next(values),
    )

    def write(
        root: object,
        candidate: TeacherGradeOverrideDecision,
        *,
        precommit_guard: object,
    ) -> None:
        assert callable(precommit_guard)
        precommit_guard()
        raise AssertionError("stale guard should have raised")

    monkeypatch.setattr(lifecycle, "write_teacher_grade_override_revision", write)

    with pytest.raises(TeacherGradeOverrideWithdrawalStaleError):
        commit_teacher_grade_override_withdrawal_preview(Path("."), preview)


def test_withdrawal_commit_detects_selection_change_after_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = withdrawal_preview()
    original = stored(preview.selected_override_decision)
    changed_ref = teacher_grade_override_reference(preview.candidate)
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: original,
    )
    monkeypatch.setattr(
        lifecycle,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: original,
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_source_result",
        lambda *args, **kwargs: preview.source,
    )

    def write(
        root: object,
        candidate: TeacherGradeOverrideDecision,
        *,
        precommit_guard: object,
    ) -> SimpleNamespace:
        assert callable(precommit_guard)
        precommit_guard()
        return SimpleNamespace(disposition="created", stored=stored(candidate))

    monkeypatch.setattr(lifecycle, "write_teacher_grade_override_revision", write)
    monkeypatch.setattr(
        lifecycle,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: changed_ref,
    )

    with pytest.raises(TeacherGradeOverrideWithdrawalStaleError):
        commit_teacher_grade_override_withdrawal_preview(Path("."), preview)


def test_exact_withdrawal_replay_is_idempotent_without_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = withdrawal_preview()
    candidate_stored = stored(preview.candidate)
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1, 2),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: candidate_stored,
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_source_result",
        lambda *args, **kwargs: preview.source,
    )

    def write(
        root: object,
        candidate: TeacherGradeOverrideDecision,
        *,
        precommit_guard: object,
    ) -> SimpleNamespace:
        assert precommit_guard is None
        return SimpleNamespace(disposition="existing", stored=candidate_stored)

    monkeypatch.setattr(lifecycle, "write_teacher_grade_override_revision", write)
    monkeypatch.setattr(
        lifecycle,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: teacher_grade_override_reference(preview.candidate),
    )

    result = commit_teacher_grade_override_withdrawal_preview(Path("."), preview)

    assert result.write_disposition == "existing"
    assert result.stored_reference == teacher_grade_override_reference(
        preview.candidate
    )
    assert result.selected_override_after == teacher_grade_override_reference(
        preview.candidate
    )


def test_exact_withdrawal_replay_rejects_different_existing_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = withdrawal_preview()
    different = replace(preview.candidate, rationale="Different persisted rationale.")
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1, 2),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: stored(different),
    )

    with pytest.raises(TeacherGradeOverrideWithdrawalStaleError):
        commit_teacher_grade_override_withdrawal_preview(Path("."), preview)


def test_withdrawal_write_does_not_select_new_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = withdrawal_preview()
    original = stored(preview.selected_override_decision)
    monkeypatch.setattr(
        lifecycle,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: original,
    )
    monkeypatch.setattr(
        lifecycle,
        "load_current_teacher_grade_override",
        lambda *args, **kwargs: original,
    )
    monkeypatch.setattr(
        lifecycle,
        "load_teacher_grade_override_source_result",
        lambda *args, **kwargs: preview.source,
    )

    def write(
        root: object,
        candidate: TeacherGradeOverrideDecision,
        *,
        precommit_guard: object,
    ) -> SimpleNamespace:
        assert callable(precommit_guard)
        precommit_guard()
        return SimpleNamespace(disposition="created", stored=stored(candidate))

    monkeypatch.setattr(lifecycle, "write_teacher_grade_override_revision", write)
    monkeypatch.setattr(
        lifecycle,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: preview.selected_override_reference,
    )

    result = commit_teacher_grade_override_withdrawal_preview(Path("."), preview)

    assert result.selected_override_after == preview.selected_override_reference
    assert result.stored_reference != result.selected_override_after
