"""#126 I3A: installed public-reader journeys and native ScoreForm #122 isolation.

Only synthetic classes/data; installed Core/ScoreForm/Quillan/Concord readers and
Meridian source-checkout services are real. An injected synthetic #121 profile
fingerprint remains a test seam; no release-wheel/D4/paper-scan claim is made.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from pds_core.routes import module_work_dir
from test_issue117_producer_teacher_acceptance import (
    PRODUCERS,
    _grant,
    _input,
    _published_workspace,
)
from test_issue126_slicei1_native_scoreform_29x6 import FIRST, RETAKE, WORK, _read
from test_issue126_slicei2a_native_correction_current import GRADE_ITEM
from test_issue126_slicei2b_native_teacher_receipt_menu import (
    _current,
    _history,
    _receipt_store,
    _run,
    _world,
)

from meridian.assessment_attempt_inventory import project_assessment_attempt_inventory
from meridian.attempt_selection_storage import derive_attempt_candidates
from meridian.diagnostics import default_diagnostics_dependencies
from meridian.guided_projection import (
    GuidedProjectionAuthorizationDeniedError,
    default_guided_projection_dependencies,
    prepare_guided_evidence_projection,
)
from meridian.menu_teacher_evidence import (
    default_teacher_evidence_inbox_menu_dependencies,
    run_teacher_evidence_inbox_menu,
)
from meridian.publication_authorization import (
    PublicationAuthorizationGrant,
    TeacherLocalPublicationAuthorizer,
)
from meridian.teacher_evidence_inbox import load_teacher_evidence_inbox
from meridian.teacher_evidence_review import project_teacher_evidence_review
from meridian.teacher_session import TeacherSessionContext


def _published_review(root: Path, work, publication_id: str):
    diagnostics = default_diagnostics_dependencies(
        workspace_root=root,
        authorizer=_grant(root, work),
    )
    prepared = prepare_guided_evidence_projection(
        root,
        work,
        publication_id,
        dependencies=default_guided_projection_dependencies(diagnostics=diagnostics),
    )
    return diagnostics, prepared, project_teacher_evidence_review(root, prepared)


@pytest.mark.parametrize("producer", PRODUCERS)
def test_each_installed_producer_enters_actual_teacher_inbox_without_writing(
    tmp_path: Path, producer: str
) -> None:
    root, work, publication_id, title = _published_workspace(tmp_path, producer)
    diagnostics, prepared, review = _published_review(root, work, publication_id)
    assert prepared.authorized.current_context.publication.work == work
    assert (
        prepared.authorized.current_context.publication.publication_id == publication_id
    )
    assert review.work == work and review.publication_id == publication_id
    assert review.evidence_count > 0
    inbox = load_teacher_evidence_inbox(root, diagnostics)
    assert len(inbox.items) == 1
    assert inbox.items[0].status_code == "ready_to_review"
    assert inbox.items[0].work == work
    output = StringIO()
    session = TeacherSessionContext()
    run_teacher_evidence_inbox_menu(
        dependencies=replace(
            default_teacher_evidence_inbox_menu_dependencies(diagnostics=diagnostics),
            workspace_resolver=lambda: root,
        ),
        session_context=session,
        input_fn=_input("1", "1", "b", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )
    assert session.active_work == work
    assert session.active_publication_id == publication_id
    assert "Evidence Review" in output.getvalue()
    assert title in output.getvalue()
    assert publication_id not in output.getvalue()
    assert not (
        root
        / "classes"
        / work.class_id
        / "modules"
        / "meridian"
        / "teacher_action_receipts"
    ).exists()


@pytest.mark.parametrize("producer", ("quillan", "concord"))
def test_non_attempt_producer_never_becomes_scoreform_attempt(
    tmp_path: Path, producer: str
) -> None:
    root, work, publication_id, _ = _published_workspace(tmp_path, producer)
    _, prepared, review = _published_review(root, work, publication_id)
    assert review.evidence_count > 0
    publication = prepared.authorized.current_context.publication
    assert "multiple_attempts" not in publication.capabilities
    for student in ("student_synthetic_001", "student_1"):
        result = derive_attempt_candidates(
            root, work.class_id, "synthetic_grade_item", student, prepared.authorized
        )
        assert result.status == "not_applicable"
        assert result.candidates == ()
        assert result.source_snapshot.publication_id == publication_id
    assert not (
        root / "classes" / work.class_id / "modules" / "meridian" / "attempts"
    ).exists()


@pytest.mark.parametrize("producer", PRODUCERS)
def test_denied_cache_permission_cannot_expose_or_select_other_producer(
    tmp_path: Path, producer: str
) -> None:
    root, work, publication_id, _ = _published_workspace(tmp_path, producer)
    diagnostics = default_diagnostics_dependencies(
        workspace_root=root,
        authorizer=_grant(root, work, operations=("project_evidence",)),
    )
    inbox = load_teacher_evidence_inbox(root, diagnostics)
    assert len(inbox.items) == 1
    assert inbox.items[0].status_code == "access_not_granted"
    session = TeacherSessionContext()
    output = StringIO()
    run_teacher_evidence_inbox_menu(
        dependencies=replace(
            default_teacher_evidence_inbox_menu_dependencies(diagnostics=diagnostics),
            workspace_resolver=lambda: root,
        ),
        session_context=session,
        input_fn=_input("1", "1", "b", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )
    assert "Evidence Not Ready" in output.getvalue()
    assert publication_id not in output.getvalue()
    assert session.active_publication_id is None


def test_teacher_navigation_clears_stale_student_and_grade_item_between_producers():
    from pds_core.routing_models import ModuleWorkRef

    session = TeacherSessionContext()
    a = ModuleWorkRef("scoreform", "synthetic_class_2026", "quiz_1")
    b = ModuleWorkRef("quillan", "synthetic_class_2026", "essay_1")
    c = ModuleWorkRef("concord", "synthetic_class_other", "activity_1")
    session.select_work(a)
    session.select_publication("pub_" + "1" * 32)
    session.select_grade_item("assessment")
    session.select_student("student_synthetic_001")
    session.select_work(b)
    assert session.active_class_id == a.class_id
    assert session.active_work == b
    assert session.active_publication_id is None
    assert session.active_grade_item_id is None
    assert session.active_student_id is None
    session.select_publication("pub_" + "2" * 32)
    session.select_student("student_synthetic_001")
    session.select_work(c)
    assert session.active_class_id == c.class_id
    assert session.active_publication_id is None
    assert session.active_student_id is None


def test_scoreform_29x6_authorized_inbox_then_real_122_teacher_save_use(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scenario, inventory, row = _world(tmp_path)
    diag = default_diagnostics_dependencies(
        workspace_root=scenario.root,
        authorizer=TeacherLocalPublicationAuthorizer(
            scenario.root,
            "synthetic_i3a_policy",
            "1",
            (
                PublicationAuthorizationGrant(
                    class_id=WORK.class_id,
                    operations=("project_evidence", "read_projection_cache"),
                    purpose_ids=("review_evidence",),
                    producer_module_ids=("scoreform",),
                    publication_ids=(),
                    student_ids=(),
                ),
            ),
        ),
    )
    inbox = load_teacher_evidence_inbox(scenario.root, diag)
    assert inbox.ready_count == 1
    assert inbox.items[0].work == WORK
    assert inbox.items[0].publication_id == scenario.publication_id
    assert len(inventory.students) == 29
    assert _history(scenario) == ()
    assert not _receipt_store(scenario).list_receipts()
    content, scripted = _run(
        monkeypatch,
        scenario,
        inventory,
        row,
        ("1", "1", "Reviewed original source; attempt 2 is corrected.", "1", ""),
    )
    assert scripted.requests == 5
    assert "Current Verified" in content
    assert _history(scenario) == (1,)
    current = _current(scenario)
    assert current is not None
    assert tuple(a.native.sequence for a in current.decision.selected_attempts) == (2,)
    (receipt,) = _receipt_store(scenario).list_receipts()
    assert receipt.preview.target.candidate_sha256 == current.decision_sha256
    assert receipt.checkpoints[-1].stage == "receipt_finalized"
    assert receipt.preview.kind == "attempt_decision"
    refreshed = _read(scenario.root, scenario.publication_id)
    refreshed_inventory = project_assessment_attempt_inventory(
        scenario.root,
        grade_item_id=GRADE_ITEM,
        prepared=refreshed,
    )
    (selected,) = (
        student
        for student in refreshed_inventory.students
        if student.student_id == FIRST
    )
    assert selected.selection_status == "selected"
    assert tuple(
        attempt.attempt.native.sequence
        for attempt in selected.attempts
        if attempt.current_selected
    ) == (2,)
    assert not any(
        attempt.current_selected
        for student in refreshed_inventory.students
        if student.student_id == RETAKE
        for attempt in student.attempts
    )
    manifest_path = (
        module_work_dir(scenario.root, WORK)
        / "publications"
        / "academic_results"
        / "1.json"
    )
    assert (
        hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        == hashlib.sha256(scenario.original_data).hexdigest()
    )


def test_scoreform_saved_decision_does_not_override_later_publication_permission_denial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scenario, inventory, row = _world(tmp_path)
    content, _ = _run(
        monkeypatch,
        scenario,
        inventory,
        row,
        ("1", "1", "Teacher inspected source and verified correction.", "1", ""),
    )
    assert "Current Verified" in content
    denied = TeacherLocalPublicationAuthorizer(
        scenario.root,
        "synthetic_i3a_denied",
        "1",
        (
            PublicationAuthorizationGrant(
                class_id=WORK.class_id,
                operations=("read_projection_cache",),
                purpose_ids=("review_evidence",),
                producer_module_ids=("scoreform",),
                publication_ids=(),
                student_ids=(),
            ),
        ),
    )
    diagnostics = default_diagnostics_dependencies(
        workspace_root=scenario.root, authorizer=denied
    )
    with pytest.raises(GuidedProjectionAuthorizationDeniedError):
        prepare_guided_evidence_projection(
            scenario.root,
            WORK,
            scenario.publication_id,
            dependencies=default_guided_projection_dependencies(
                diagnostics=diagnostics
            ),
        )
    assert _history(scenario) == (1,)
    assert _current(scenario) is not None
    assert len(_receipt_store(scenario).list_receipts()) == 1
