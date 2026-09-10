from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest
from pds_core.academic_periods import AcademicPeriodRef

from meridian.grade_policy import GradePolicyActor, GradePolicyReference
from meridian.grade_policy_activation import (
    GRADE_POLICY_ACTIVATION_RECORD_TYPE,
    GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
    GradePolicyActivationDecision,
    GradePolicyActivationSerializationError,
    GradePolicyActivationValidationError,
    grade_policy_activation_decision_from_dict,
    grade_policy_activation_decision_from_json_bytes,
    grade_policy_activation_decision_to_dict,
    grade_policy_activation_decision_to_json_bytes,
    grade_policy_activation_reference,
    grade_policy_activation_reference_from_dict,
    grade_policy_activation_reference_to_dict,
    validate_grade_policy_activation_transition,
)

CLASS_ID = "synthetic_class_2026"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 9, 22, 0, tzinfo=UTC)


def policy_ref(
    *,
    revision: int = 1,
    digest: str = "a" * 64,
    class_id: str = CLASS_ID,
) -> GradePolicyReference:
    return GradePolicyReference(
        class_id,
        "course_grade_policy",
        revision,
        digest,
    )


def activation(
    revision: int = 1,
    *,
    decision: str = "activate",
    policy: GradePolicyReference | None = None,
    calendar_revision: int = 1,
    decided_at: datetime | None = None,
) -> GradePolicyActivationDecision:
    if policy is None and decision == "activate":
        policy = policy_ref()
    return GradePolicyActivationDecision(
        schema_version=GRADE_POLICY_ACTIVATION_SCHEMA_VERSION,
        record_type=GRADE_POLICY_ACTIVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=calendar_revision,
        activation_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision=decision,  # type: ignore[arg-type]
        policy_reference=policy,
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=None,
        decided_at=decided_at
        or NOW + timedelta(hours=revision - 1),
    )


def test_activation_is_frozen_and_slotted() -> None:
    value = activation()
    with pytest.raises(FrozenInstanceError):
        value.decision = "deactivate"  # type: ignore[misc]
    assert not hasattr(value, "__dict__")


def test_activate_requires_exact_policy_reference() -> None:
    with pytest.raises(GradePolicyActivationValidationError):
        activation(policy=None, decision="activate").__class__(
            schema_version="1",
            record_type="meridian_grade_policy_activation",
            class_id=CLASS_ID,
            target_period=PERIOD,
            calendar_revision=1,
            activation_revision=1,
            supersedes_revision=None,
            decision="activate",
            policy_reference=None,
            actor=GradePolicyActor("teacher", "teacher_local"),
            rationale=None,
            decided_at=NOW,
        )


def test_deactivate_requires_null_policy_reference() -> None:
    with pytest.raises(GradePolicyActivationValidationError):
        activation(decision="deactivate", policy=policy_ref())


def test_deactivate_is_valid_without_policy() -> None:
    value = activation(decision="deactivate", policy=None)
    assert value.policy_reference is None


def test_cross_class_policy_reference_is_rejected() -> None:
    with pytest.raises(GradePolicyActivationValidationError):
        activation(policy=policy_ref(class_id="other_class"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2"),
        ("record_type", "other"),
        ("class_id", "../bad"),
        ("calendar_revision", 0),
        ("activation_revision", 0),
        ("decision", "latest"),
    ],
)
def test_invalid_fields_fail(field: str, value: object) -> None:
    data = grade_policy_activation_decision_to_dict(activation())
    data[field] = value
    with pytest.raises(GradePolicyActivationValidationError):
        grade_policy_activation_decision_from_dict(data)


def test_revision_lineage_is_contiguous() -> None:
    old = activation()
    new = activation(2, decision="deactivate", policy=None)
    assert validate_grade_policy_activation_transition(old, new) == new

    skipped = replace(
        new,
        activation_revision=3,
        supersedes_revision=2,
    )
    with pytest.raises(GradePolicyActivationValidationError):
        validate_grade_policy_activation_transition(old, skipped)


def test_transition_keeps_logical_period_identity() -> None:
    old = activation()
    other = replace(
        activation(2),
        target_period=AcademicPeriodRef("2026-2027", "mp2"),
    )
    with pytest.raises(GradePolicyActivationValidationError):
        validate_grade_policy_activation_transition(old, other)


def test_transition_may_bind_new_calendar_revision() -> None:
    old = activation(calendar_revision=1)
    new = activation(2, calendar_revision=2)
    assert validate_grade_policy_activation_transition(old, new) == new


def test_transition_rejects_time_regression() -> None:
    old = activation()
    new = activation(
        2,
        decided_at=NOW - timedelta(seconds=1),
    )
    with pytest.raises(GradePolicyActivationValidationError):
        validate_grade_policy_activation_transition(old, new)


def test_canonical_round_trip_and_reference_digest() -> None:
    value = activation()
    content = grade_policy_activation_decision_to_json_bytes(value)
    assert content.endswith(b"\n")
    assert grade_policy_activation_decision_from_json_bytes(content) == value
    reference = grade_policy_activation_reference(value)
    assert reference.activation_sha256 == hashlib.sha256(content).hexdigest()
    assert grade_policy_activation_reference_from_dict(
        grade_policy_activation_reference_to_dict(reference)
    ) == reference


def test_noncanonical_duplicate_unknown_and_missing_json_fail() -> None:
    value = activation()
    canonical = grade_policy_activation_decision_to_json_bytes(value).decode(
        "utf-8"
    )
    duplicate = canonical.replace(
        '  "class_id": "synthetic_class_2026",',
        '  "class_id": "synthetic_class_2026",\n'
        '  "class_id": "synthetic_class_2026",',
        1,
    ).encode("utf-8")
    with pytest.raises(
        GradePolicyActivationSerializationError,
        match="duplicate JSON object key",
    ):
        grade_policy_activation_decision_from_json_bytes(duplicate)

    data = grade_policy_activation_decision_to_dict(value)
    with pytest.raises(GradePolicyActivationValidationError):
        grade_policy_activation_decision_from_dict({**data, "extra": True})

    missing = dict(data)
    del missing["calendar_revision"]
    with pytest.raises(GradePolicyActivationValidationError):
        grade_policy_activation_decision_from_dict(missing)

    compact = json.dumps(data).encode("utf-8")
    with pytest.raises(
        GradePolicyActivationSerializationError,
        match="canonical encoding",
    ):
        grade_policy_activation_decision_from_json_bytes(compact)


def test_naive_decision_time_is_rejected() -> None:
    with pytest.raises(GradePolicyActivationValidationError):
        activation(decided_at=datetime(2026, 9, 9, 22, 0))
