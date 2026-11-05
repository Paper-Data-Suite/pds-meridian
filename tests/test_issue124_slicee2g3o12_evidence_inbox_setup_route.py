"""#124 E2G3O12: exact published-work setup from the Evidence Inbox.

No protected producer manifest, scan, authorization grant or student record
is needed to choose Grade Item setup from an indexed publication.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef
from test_issue124_slicee2g3k_composite_canonical import (
    ACTOR,
    CLASS,
    WORK,
    _all_bytes,
    _workspace,
)
from test_issue124_slicee2g3o5_published_existing_acceptance import (
    _publish,
)

from meridian import menu_teacher_assessment_discovery as discovery
from meridian import teacher_action_guided
from meridian.grade_item_membership_storage import (
    load_current_grade_item_membership_decision,
)
from meridian.grade_item_storage import get_current_grade_item_revision
from meridian.guided_grade_items import GuidedGradeItemBridgeDependencies
from meridian.menu_teacher_evidence import _run_class_evidence_menu
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_session import TeacherSessionContext


def _responses(items: tuple[str, ...], prompts: list[str]):
    iterator = iter(items)

    def read(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(iterator)

    return read


def _inbox_fixture(*, work: ModuleWorkRef = WORK, publication_id: str = "pub_test"):
    item = SimpleNamespace(
        work=work,
        publication_id=publication_id,
        work_title="Synthetic Scene Study",
        producer_label="ScoreForm",
        status_label="Evidence access not configured",
        status_code="access_not_configured",
        actionability="blocked",
    )
    return SimpleNamespace(class_id=CLASS, class_label="English 12", items=(item,))


def test_inbox_s_number_selects_exact_work_without_opening_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    group = _inbox_fixture()
    calls: list[tuple[ModuleWorkRef, str, TeacherSessionContext]] = []
    session = TeacherSessionContext(active_class_id=CLASS)
    prompts: list[str] = []
    out = StringIO()

    def no_evidence(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("S-number setup must not open protected evidence")

    dependencies = SimpleNamespace(
        setup_published_assessment=(
            lambda _root, work, publication, context, *_args: calls.append(
                (work, publication, context)
            )
        ),
        projection_preparer=no_evidence,
    )
    _run_class_evidence_menu(
        root=root,
        group=group,
        dependencies=dependencies,
        session_context=session,
        input_fn=_responses(("s1", "b"), prompts),
        output=out,
        clear_fn=lambda: None,
    )
    assert calls == [(WORK, "pub_test", session)]
    assert "S1" in out.getvalue()
    assert "Confirmation: " not in prompts


def test_inbox_invalid_setup_number_never_resolves_a_work(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    session = TeacherSessionContext(active_class_id=CLASS)
    calls: list[str] = []
    out = StringIO()
    _run_class_evidence_menu(
        root=root,
        group=_inbox_fixture(),
        dependencies=SimpleNamespace(
            setup_published_assessment=lambda *_args: calls.append("setup")
        ),
        session_context=session,
        input_fn=_responses(("s2", "", "b"), []),
        output=out,
        clear_fn=lambda: None,
    )
    assert calls == []
    assert "No assessment matches that setup number" in out.getvalue()
    assert session.active_work is None


def test_inbox_does_not_advertise_unwired_setup(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    out = StringIO()
    _run_class_evidence_menu(
        root=root,
        group=_inbox_fixture(),
        dependencies=SimpleNamespace(setup_published_assessment=None),
        session_context=TeacherSessionContext(active_class_id=CLASS),
        input_fn=_responses(("s1", "", "b"), []),
        output=out,
        clear_fn=lambda: None,
    )
    assert "S1. Set Up Grade Item" not in out.getvalue()


def test_exact_published_route_onboards_and_reopens_without_evidence_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    publication = _publish(root)
    from test_issue124_slicee2g3o4_canonical_teacher_acceptance import (
        _SyntheticIdentityProvider,
    )

    monkeypatch.setattr(
        teacher_action_guided,
        "TeacherIdentityProvider",
        _SyntheticIdentityProvider,
    )
    monkeypatch.setattr(discovery, "resolve_menu_actor", lambda *_: ACTOR)
    prompts: list[str] = []
    output = StringIO()
    session = TeacherSessionContext(active_class_id=CLASS)
    discovery.run_teacher_published_assessment_setup(
        root,
        WORK,
        publication.publication_id,
        session,
        input_fn=_responses(
            ("1", "1", "Scene", "", ACTOR.actor_id, "APPLY", ""), prompts
        ),
        output=output,
        clear_fn=lambda: None,
        assessment_bridge_dependencies=GuidedGradeItemBridgeDependencies(),
    )
    assert "Assessment relationship verified current." in output.getvalue()
    assert prompts.count("Confirmation: ") == 1
    assert session.active_publication_id == publication.publication_id
    grade = session.active_grade_item_id
    assert grade is not None
    assert get_current_grade_item_revision(root, CLASS, grade) == 1
    membership = load_current_grade_item_membership_decision(root, CLASS, grade, WORK)
    assert membership is not None and membership.decision.decision == "included"
    assert membership.decision.academic_period is not None
    assert membership.decision.academic_period.period.period_id == "mp1"
    assert len(TeacherActionReceiptStore(root, CLASS).list_receipts()) == 2
    before = _all_bytes(root)
    again: list[str] = []
    discovery.run_teacher_published_assessment_setup(
        root,
        WORK,
        publication.publication_id,
        session,
        input_fn=_responses(("1", ""), again),
        output=StringIO(),
        clear_fn=lambda: None,
        assessment_bridge_dependencies=GuidedGradeItemBridgeDependencies(),
    )
    assert "Confirmation: " not in again
    assert _all_bytes(root) == before


def test_selected_publication_changed_refuses_before_any_academic_write(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    _publish(root)
    session = TeacherSessionContext(active_class_id=CLASS)
    before = _all_bytes(root)
    output = StringIO()
    prompts: list[str] = []
    discovery.run_teacher_published_assessment_setup(
        root,
        WORK,
        "pub_" + "d" * 32,
        session,
        input_fn=_responses(("",), prompts),
        output=output,
        clear_fn=lambda: None,
        assessment_bridge_dependencies=GuidedGradeItemBridgeDependencies(),
    )
    assert "no longer current" in output.getvalue().lower()
    assert "Confirmation: " not in prompts
    assert session.active_grade_item_id is None
    assert _all_bytes(root) == before
