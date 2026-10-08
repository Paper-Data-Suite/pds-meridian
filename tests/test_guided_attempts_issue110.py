from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

from pds_core.routing_models import ModuleWorkRef

from meridian.attempt_selection_storage import StoredAttemptSelectionPolicy
from meridian.guided_attempts import (
    GuidedAttemptDependencies,
    GuidedAttemptPolicyPreset,
    plan_guided_attempt_policy,
)

WORK = ModuleWorkRef("scoreform", "english_12_pd2", "memory_snapshot")
PRESET = GuidedAttemptPolicyPreset(
    title="Select exactly one attempt",
    description="Use one explicit attempt.",
    policy_id="hidden_policy",
    minimum_selected=1,
    maximum_selected=1,
)


def _stored(minimum: int, maximum: int | None) -> StoredAttemptSelectionPolicy:
    policy = SimpleNamespace(
        minimum_selected=minimum,
        maximum_selected=maximum,
        selection_basis="explicit",
    )
    return cast(
        StoredAttemptSelectionPolicy,
        SimpleNamespace(policy=policy),
    )


def test_policy_plan_reuses_matching_current_policy() -> None:
    deps = GuidedAttemptDependencies(
        current_policy_loader=lambda *_args: _stored(1, 1),
        policy_history_loader=lambda *_args: (1,),
    )

    plan = plan_guided_attempt_policy(
        Path("workspace"),
        class_id=WORK.class_id,
        grade_item_id="hidden_grade",
        work=WORK,
        preset=PRESET,
        dependencies=deps,
    )

    assert plan.action == "ready"
    assert plan.target_revision is None


def test_policy_plan_creates_when_no_history_exists() -> None:
    deps = GuidedAttemptDependencies(
        current_policy_loader=lambda *_args: None,
        policy_history_loader=lambda *_args: (),
    )

    plan = plan_guided_attempt_policy(
        Path("workspace"),
        class_id=WORK.class_id,
        grade_item_id="hidden_grade",
        work=WORK,
        preset=PRESET,
        dependencies=deps,
    )

    assert plan.action == "create"


def test_policy_plan_selects_matching_existing_history() -> None:
    deps = GuidedAttemptDependencies(
        current_policy_loader=lambda *_args: None,
        policy_history_loader=lambda *_args: (1, 2),
        policy_revision_loader=lambda *_args: _stored(1, 1),
    )

    plan = plan_guided_attempt_policy(
        Path("workspace"),
        class_id=WORK.class_id,
        grade_item_id="hidden_grade",
        work=WORK,
        preset=PRESET,
        dependencies=deps,
    )

    assert plan.action == "select_existing"
    assert plan.target_revision == 2


def test_policy_plan_revises_when_current_semantics_differ() -> None:
    deps = GuidedAttemptDependencies(
        current_policy_loader=lambda *_args: _stored(0, None),
        policy_history_loader=lambda *_args: (1,),
        policy_revision_loader=lambda *_args: _stored(0, None),
    )

    plan = plan_guided_attempt_policy(
        Path("workspace"),
        class_id=WORK.class_id,
        grade_item_id="hidden_grade",
        work=WORK,
        preset=PRESET,
        dependencies=deps,
    )

    assert plan.action == "revise"
