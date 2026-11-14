"""#125-G2A: native producers -> exact eligibility decisions and #122 recovery.

All data are synthetic. Real producer-owned fixtures create published results;
Meridian writes only its canonical eligibility history and existing #122 receipts.
Installed tests require the pinned native test environment and are never
counted as passed merely because an ordinary source collection skipped them.
"""

from __future__ import annotations

import os
from functools import partial
from io import StringIO
from pathlib import Path
from time import perf_counter

import pytest
from test_issue125_slicef1_assessment_menu import review as synthetic_review

from meridian import menu_teacher_assessment_eligibility as menu
from meridian.assessment_eligibility_plan import (
    BatchEligibilitySelection,
    build_batch_eligibility_plan,
    capture_batch_pointer_witnesses,
)
from meridian.assessment_eligibility_progress import (
    BatchEligibilityProgressStore,
    execute_batch_with_sealed_progress,
)
from meridian.assessment_eligibility_recovery import (
    reconcile_sealed_eligibility_batch,
)
from meridian.assessment_eligibility_review import (
    project_assessment_eligibility_review,
)
from meridian.diagnostics import default_diagnostics_dependencies
from meridian.evidence_eligibility_storage import (
    load_current_evidence_eligibility_decision,
)
from meridian.guided_eligibility import (
    GuidedEligibilityDependencies,
    discover_guided_eligibility_grade_items,
)
from meridian.guided_projection import (
    default_guided_projection_dependencies,
    prepare_guided_evidence_projection,
)
from meridian.teacher_action_receipts import TeacherActionReceiptStore
from meridian.teacher_action_restart_eligibility import (
    load_fresh_restart_authorization,
)

_NATIVE = os.environ.get("PDS_ISSUE125_G2_NATIVE_TEST") == "1"


def test_29_by_6_benchmark_one_explicit_all_selection() -> None:
    """Measure menu selection rather than silently accepting the entire roster."""
    observed: list[str] = []

    def choose(prompt: str) -> str:
        observed.append(prompt)
        return "A"

    started = perf_counter()
    selection = menu._choose_source_ids(
        synthetic_review(),
        input_fn=choose,
        output=StringIO(),
        clear_fn=lambda: None,
    )
    elapsed_ms = (perf_counter() - started) * 1000.0
    assert selection is not None and len(selection) == 174
    assert len(set(selection)) == 174
    assert observed == ["Choice: "]
    print(
        f"G2A_29X6_SELECTION items={len(selection)} "
        f"inputs={len(observed)} elapsed_ms={elapsed_ms:.3f}"
    )
    assert elapsed_ms >= 0.0


def test_zero_confirmation_cannot_authorize_a_batch() -> None:
    """The public executor requires an explicit Boolean, not a truthy string."""
    from meridian.assessment_eligibility_execution import (
        BatchEligibilityExecutionError,
        execute_batch_eligibility_plan,
    )

    with pytest.raises(BatchEligibilityExecutionError, match="Invalid batch plan"):
        execute_batch_eligibility_plan(
            Path("/not-a-workspace"),
            None,  # type: ignore[arg-type]
            confirmed=True,
            prepared=None,  # type: ignore[arg-type]
            grade_item=None,  # type: ignore[arg-type]
            dependencies=GuidedEligibilityDependencies(),
        )


def test_recovery_requires_explicit_actor_checker() -> None:
    """E2 cannot proceed with an absent current teacher identity verifier."""
    from test_issue125_slicec_batch_review_plan import make_review, plan

    from meridian.assessment_eligibility_recovery import (
        BatchEligibilityRecoveryError,
        reconcile_sealed_eligibility_batch,
    )

    proposal = plan(make_review())
    with pytest.raises(BatchEligibilityRecoveryError):
        reconcile_sealed_eligibility_batch(
            Path("/not-a-workspace"),
            proposal,
            authorized_loader=lambda *_: None,
            actor_checker=None,  # type: ignore[arg-type]
        )


def _ready_native(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    producer: str,
):
    from test_issue124_slicee2g3k_composite_canonical import ACTOR
    from test_issue124_slicee2g3o4_canonical_teacher_acceptance import _journey
    from test_issue124_slicee2g3o9_native_producer_acceptance import (
        _native_workspace,
        _quillan_publication,
        _scoreform_publication,
    )
    from test_issue125_sliceg1_native_source_acceptance import _native_roster

    from scripts.smoke_program_guided_evidence_issue110 import AllowInstalledAcceptance

    root = _native_workspace(tmp_path)
    if producer == "concord":
        from test_issue124_slicee2g3o10_native_concord_acceptance import (
            _native_scored_publication,
        )

        publication = _native_scored_publication(root, group=False)
        work, publication_id = publication.work, publication.publication_id
    else:
        _native_roster(root, 29)
        work, publication_id = (
            _scoreform_publication(root)
            if producer == "scoreform"
            else _quillan_publication(root)
        )
    answers = (
        "1",
        "1",
        "S",
        "1",
        f"Synthetic {producer} Batch",
        "",
        ACTOR.actor_id,
        "APPLY",
        "",
    )
    setup = _journey(root, monkeypatch, answers)
    assert setup.session.active_publication_id == publication_id
    grade_id = setup.session.active_grade_item_id
    assert grade_id is not None
    diagnostics = default_diagnostics_dependencies(
        authorizer=AllowInstalledAcceptance()
    )
    prepared = prepare_guided_evidence_projection(
        root,
        work,
        publication_id,
        dependencies=default_guided_projection_dependencies(diagnostics=diagnostics),
    )
    review = project_assessment_eligibility_review(
        root, grade_item_id=grade_id, prepared=prepared
    )
    deps = GuidedEligibilityDependencies()
    choices = discover_guided_eligibility_grade_items(root, work, dependencies=deps)
    grade_item = next(choice for choice in choices if choice.grade_item_id == grade_id)
    return root, grade_id, prepared, review, deps, grade_item, diagnostics, ACTOR


def _build_plan(
    root: Path,
    prepared: object,
    review: object,
    deps: object,
    actor: object,
    selected: tuple[str, ...],
):
    choice = BatchEligibilitySelection(
        selected_item_ids=selected, disposition="included"
    )
    return build_batch_eligibility_plan(
        review,
        choice,
        actor=actor,
        policy=deps.policies[0],
        witnesses=capture_batch_pointer_witnesses(
            root, review, prepared.authorized, selected
        ),
        qualified_policies=deps.policies,
    )


@pytest.mark.skipif(
    not _NATIVE, reason="Requires pinned installed native producer matrix"
)
@pytest.mark.parametrize(
    ("producer", "limit"),
    (("scoreform", 3), ("quillan", 1), ("concord", 1)),
)
def test_installed_native_producer_real_batch_decisions_and_exact_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    producer: str,
    limit: int,
) -> None:
    from test_issue124_slicee2g3k_composite_canonical import CLASS, _all_bytes

    from meridian.teacher_action_guided import _actor_now

    root, grade_id, prepared, review, deps, grade_item, diagnostics, actor = (
        _ready_native(tmp_path, monkeypatch, producer)
    )
    options = sorted(
        (
            item
            for s in review.students
            for item in s.items
            if item.candidate_for_explicit_review
        ),
        key=lambda item: item.source.item_id,
    )
    assert len(options) >= limit
    if producer == "scoreform":
        assert review.projected_item_count == 406
        options = [
            item for item in options if item.result_kind == "question_correctness"
        ]
        assert len(options) == 174
    selected = tuple(item.source.item_id for item in options[:limit])
    plan = _build_plan(root, prepared, review, deps, actor, selected)
    assert plan.action_count == limit
    initial = _all_bytes(root)
    cancelled = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=False,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert not cancelled.confirmed
    assert _all_bytes(root) == initial
    assert TeacherActionReceiptStore(root, CLASS).list_receipts()
    started = perf_counter()
    outcome = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    elapsed = perf_counter() - started
    assert not outcome.stopped, (outcome.stop_reason, outcome.counts)
    assert outcome.verified_current_count == limit
    assert {x.source_item_id for x in outcome.items} == set(selected)
    receipt_store = TeacherActionReceiptStore(root, CLASS)
    for result in outcome.items:
        assert result.action_id is not None
        receipt = receipt_store.load(result.action_id)
        assert receipt is not None and receipt.action_id == result.action_id
    for exact in plan.items:
        stored = load_current_evidence_eligibility_decision(
            root, CLASS, grade_id, exact.source
        )
        assert stored is not None
        assert stored.decision.disposition == "included"
        assert stored.decision.eligibility_revision == 1
        assert BatchEligibilityProgressStore(root, CLASS).load(plan, exact) is not None
    loader = partial(load_fresh_restart_authorization, diagnostics=diagnostics)
    reconciled = reconcile_sealed_eligibility_batch(
        root, plan, authorized_loader=loader, actor_checker=_actor_now
    )
    assert reconciled.verified_action_count == limit
    assert reconciled.selection_resume_count == 0
    assert not reconciled.requires_attention
    print(
        f"G2A_NATIVE producer={producer} actions={limit} "
        f"elapsed_seconds={elapsed:.3f} "
        f"canonical_verified={reconciled.verified_action_count}"
    )


@pytest.mark.skipif(
    not _NATIVE, reason="Requires pinned installed native producer matrix"
)
def test_installed_native_scoreform_roster_drift_blocks_all_actions_before_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pds_core.classes import write_class_roster
    from pds_core.rosters import create_roster
    from test_issue124_slicee2g3k_composite_canonical import CLASS, _all_bytes

    root, _, prepared, review, deps, grade_item, _, actor = _ready_native(
        tmp_path, monkeypatch, "scoreform"
    )
    selected = tuple(
        item.source.item_id
        for s in review.students
        for item in s.items
        if item.result_kind == "question_correctness"
    )[:2]
    assert len(selected) == 2
    plan = _build_plan(root, prepared, review, deps, actor, selected)
    write_class_roster(
        root,
        create_roster(
            CLASS,
            tuple(
                {
                    "student_id": f"student{i:03d}",
                    "first_name": "Synthetic",
                    "last_name": f"Learner{i:03d}",
                    "period": "1",
                }
                for i in range(1, 31)
            ),
        ),
        overwrite=True,
    )
    before = _all_bytes(root)
    outcome = execute_batch_with_sealed_progress(
        root,
        plan,
        confirmed=True,
        prepared=prepared,
        grade_item=grade_item,
        dependencies=deps,
    )
    assert outcome.stopped and outcome.stop_reason == "batch_preflight_failed"
    assert outcome.verified_current_count == 0
    assert _all_bytes(root) == before
