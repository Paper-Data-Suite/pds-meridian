from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.grade_item_membership_selection_workflow as workflow
from meridian.grade_item_memberships import GradeItemMembershipDecision
from meridian.grade_items import GradeItemWorkReference

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
WORK = ModuleWorkRef(
    module_id="scoreform",
    class_id=CLASS_ID,
    work_id="test_1",
)
DECIDED = datetime(2026, 9, 1, 13, 0, tzinfo=UTC)


def _decision(
    revision: int,
    *,
    decision: str = "included",
    grade_item_revision: int = 1,
    registration_revision: int = 1,
) -> GradeItemMembershipDecision:
    return GradeItemMembershipDecision(
        schema_version="1",
        record_type="meridian_grade_item_membership",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=grade_item_revision,
        grade_item_revision_sha256="a" * 64,
        work_reference=GradeItemWorkReference(
            work=WORK,
            registration_revision=registration_revision,
        ),
        membership_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision=decision,  # type: ignore[arg-type]
        academic_period=None if decision == "excluded" else _assignment(),
        actor_id="teacher_local",
        rationale=None,
        decided_at=DECIDED,
    )


def _assignment() -> object:
    from pds_core.academic_periods import AcademicPeriodRef

    from meridian.grade_item_memberships import GradeItemAcademicPeriodAssignment

    return GradeItemAcademicPeriodAssignment(
        period=AcademicPeriodRef(
            school_year="2026-2027",
            period_id="mp1",
        ),
        calendar_revision=1,
    )


def _stored(
    revision: int,
    *,
    decision: str = "included",
    grade_item_revision: int = 1,
    registration_revision: int = 1,
    digest: str | None = None,
) -> object:
    value = _decision(
        revision,
        decision=decision,
        grade_item_revision=grade_item_revision,
        registration_revision=registration_revision,
    )
    actual = digest or hashlib.sha256(repr(value).encode()).hexdigest()
    return SimpleNamespace(
        decision=value,
        decision_sha256=actual,
        path=Path(f"{revision}.json"),
    )


def _install_state(
    monkeypatch: pytest.MonkeyPatch,
    *,
    history: tuple[int, ...] = (1, 2),
    current: int | None = 2,
    target: object | None = None,
) -> object:
    selected_target = target or _stored(
        1,
        decision="included",
        grade_item_revision=1,
        registration_revision=1,
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_revisions",
        lambda *args: history,
    )
    monkeypatch.setattr(
        workflow,
        "load_grade_item_membership_revision",
        lambda *args: selected_target,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_grade_item_membership_revision",
        lambda *args: current,
    )
    return selected_target


def test_preview_exact_historical_revision_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _install_state(monkeypatch, current=2)
    monkeypatch.setattr(
        workflow,
        "select_grade_item_membership_revision",
        lambda *args, **kwargs: pytest.fail("preview must not select"),
    )

    preview = workflow.preview_grade_item_membership_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        1,
    )

    assert preview.target is target
    assert preview.target_revision == 1
    assert preview.latest_revision == 2
    assert preview.target_is_latest is False
    assert preview.expected_current_membership_revision == 2
    assert preview.target_decision == "included"


def test_preview_allows_historical_grade_item_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _stored(
        1,
        decision="included",
        grade_item_revision=1,
        registration_revision=1,
    )
    _install_state(monkeypatch, current=2, target=target)

    preview = workflow.preview_grade_item_membership_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        1,
    )

    assert preview.target_grade_item_revision == 1
    assert preview.target_registration_revision == 1


def test_commit_selects_exact_target_with_membership_cas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _install_state(monkeypatch, current=2)
    preview = workflow.preview_grade_item_membership_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        1,
    )
    observed: dict[str, object] = {}

    def select(
        workspace_root: str,
        class_id: str,
        grade_item_id: str,
        work: ModuleWorkRef,
        membership_revision: int,
        *,
        expected_current_membership_revision: int | None,
    ) -> object:
        observed.update(
            workspace_root=workspace_root,
            class_id=class_id,
            grade_item_id=grade_item_id,
            work=work,
            membership_revision=membership_revision,
            expected_current_membership_revision=(
                expected_current_membership_revision
            ),
        )
        selection = SimpleNamespace(membership_revision=1)
        return SimpleNamespace(
            disposition="updated",
            selection=selection,
            stored=target,
        )

    monkeypatch.setattr(
        workflow,
        "select_grade_item_membership_revision",
        select,
    )

    result = workflow.commit_grade_item_membership_selection_preview(
        "workspace",
        preview,
    )

    assert observed == {
        "workspace_root": "workspace",
        "class_id": CLASS_ID,
        "grade_item_id": GRADE_ITEM_ID,
        "work": WORK,
        "membership_revision": 1,
        "expected_current_membership_revision": 2,
    }
    assert result.previous_current_membership_revision == 2
    assert result.selected_revision == 1
    assert result.selected_decision == "included"
    assert result.selection_disposition == "updated"
    assert result.authoring_action == "not_performed"


def test_commit_fails_if_history_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch, current=2)
    preview = workflow.preview_grade_item_membership_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        1,
    )
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_revisions",
        lambda *args: (1, 2, 3),
    )
    monkeypatch.setattr(
        workflow,
        "select_grade_item_membership_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not select"),
    )

    with pytest.raises(
        workflow.GradeItemMembershipSelectionStaleError,
        match="history",
    ):
        workflow.commit_grade_item_membership_selection_preview(
            "workspace",
            preview,
        )


def test_commit_fails_if_target_digest_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _install_state(monkeypatch, current=2)
    preview = workflow.preview_grade_item_membership_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        1,
    )
    changed = SimpleNamespace(
        decision=original.decision,
        decision_sha256="f" * 64,
        path=original.path,
    )
    monkeypatch.setattr(
        workflow,
        "load_grade_item_membership_revision",
        lambda *args: changed,
    )
    monkeypatch.setattr(
        workflow,
        "select_grade_item_membership_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not select"),
    )

    with pytest.raises(
        workflow.GradeItemMembershipSelectionStaleError,
        match="digest",
    ):
        workflow.commit_grade_item_membership_selection_preview(
            "workspace",
            preview,
        )


def test_commit_fails_if_current_selection_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_state(monkeypatch, current=2)
    preview = workflow.preview_grade_item_membership_selection(
        "workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
        WORK,
        1,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_grade_item_membership_revision",
        lambda *args: 1,
    )
    monkeypatch.setattr(
        workflow,
        "select_grade_item_membership_revision",
        lambda *args, **kwargs: pytest.fail("stale preview must not select"),
    )

    with pytest.raises(
        workflow.GradeItemMembershipSelectionStaleError,
        match="selection",
    ):
        workflow.commit_grade_item_membership_selection_preview(
            "workspace",
            preview,
        )


def test_invalid_or_missing_target_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "list_grade_item_membership_revisions",
        lambda *args: (1, 2),
    )

    with pytest.raises(
        workflow.GradeItemMembershipSelectionScopeError,
        match="positive",
    ):
        workflow.preview_grade_item_membership_selection(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            0,
        )

    with pytest.raises(
        workflow.GradeItemMembershipSelectionScopeError,
        match="not present",
    ):
        workflow.preview_grade_item_membership_selection(
            "workspace",
            CLASS_ID,
            GRADE_ITEM_ID,
            WORK,
            3,
        )
