from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.routing_models import ModuleWorkRef

import meridian.conventional_grade_assembly as assembly
from meridian.evidence import (
    EvidenceItem,
    NativePointValue,
    NativeScalarValue,
    NativeStateValue,
)
from meridian.evidence_eligibility_storage import EvidenceEligibilityResolution
from meridian.grade_item_membership_storage import StoredGradeItemMembershipDecision
from meridian.grade_item_memberships import (
    GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
    GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
    GradeItemAcademicPeriodAssignment,
    GradeItemMembershipDecision,
)
from meridian.grade_items import GradeItemWorkReference
from meridian.grade_policy import GradePolicyItemParticipation, GradePolicyItemReference
from meridian.projection_cache import AuthorizedProjectionSnapshot
from meridian.reassessment_storage import ReassessmentResolution

CLASS_ID = "class_001"
STUDENT_ID = "student_001"
GRADE_ITEM_ID = "quiz_001"
GRADE_ITEM_SHA = "a" * 64
MEMBERSHIP_SHA = "b" * 64
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
OTHER_PERIOD = AcademicPeriodRef("2026-2027", "mp2")
NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


def _work(work_id: str = "work_001") -> ModuleWorkRef:
    return ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id=work_id)


def _participation() -> GradePolicyItemParticipation:
    return GradePolicyItemParticipation(
        grade_item=GradePolicyItemReference(
            CLASS_ID,
            GRADE_ITEM_ID,
            1,
            GRADE_ITEM_SHA,
        ),
        category_id=None,
        weight=None,
        possible_points=Decimal("100"),
    )


def _stored_membership(
    *,
    work: ModuleWorkRef | None = None,
    period: AcademicPeriodRef = PERIOD,
    calendar_revision: int = 1,
    grade_item_sha: str = GRADE_ITEM_SHA,
) -> StoredGradeItemMembershipDecision:
    relation = _work() if work is None else work
    decision = GradeItemMembershipDecision(
        schema_version=GRADE_ITEM_MEMBERSHIP_SCHEMA_VERSION,
        record_type=GRADE_ITEM_MEMBERSHIP_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=1,
        grade_item_revision_sha256=grade_item_sha,
        work_reference=GradeItemWorkReference(relation, 1),
        membership_revision=1,
        supersedes_revision=None,
        decision="included",
        academic_period=GradeItemAcademicPeriodAssignment(period, calendar_revision),
        actor_id="teacher_001",
        rationale=None,
        decided_at=NOW,
    )
    stored = object.__new__(StoredGradeItemMembershipDecision)
    object.__setattr__(stored, "decision", decision)
    object.__setattr__(stored, "decision_sha256", MEMBERSHIP_SHA)
    return stored


def _item_with_value(value: object) -> EvidenceItem:
    item = object.__new__(EvidenceItem)
    object.__setattr__(item, "value", value)
    return item


def _resolution(
    status: str,
    *,
    operative: bool = False,
) -> EvidenceEligibilityResolution:
    return EvidenceEligibilityResolution(
        status=cast(object, status),
        selected=None,
        current_source_state=None,
        current_membership_revision=1,
        operative_included=operative,
    )


def _reassessment(status: str, *, operative: bool = False) -> ReassessmentResolution:
    value = object.__new__(ReassessmentResolution)
    object.__setattr__(value, "status", status)
    object.__setattr__(value, "operative_reassessment", operative)
    return value


def _snapshot_resolution(
    status: str,
    *,
    operative: bool = False,
) -> assembly._SnapshotResolution:
    return assembly._SnapshotResolution(
        snapshot=cast(AuthorizedProjectionSnapshot, object()),
        reassessment=_reassessment(status, operative=operative),
        allowed_sources=frozenset(),
        provenance=(),
    )


def test_fail_closed_state_precedence_is_deterministic() -> None:
    signals = [
        assembly._StateSignal("missing", "missing", (), False),
        assembly._StateSignal("pending", "pending", (), True),
        assembly._StateSignal("unavailable", "unavailable", (), True),
        assembly._StateSignal("unresolved", "unresolved", (), True),
    ]
    assert assembly._strongest_state(signals, default="missing") == "unresolved"
    assert assembly.CONVENTIONAL_GRADE_STATE_PRECEDENCE[0] == "unresolved"
    assert assembly.CONVENTIONAL_GRADE_STATE_PRECEDENCE[-1] == "missing"


def test_pending_point_eligibility_blocks_but_pending_nonpoint_does_not() -> None:
    point = _item_with_value(NativePointValue(80, 100))
    scalar = _item_with_value(NativeScalarValue(80))
    pending = _resolution("pending")

    point_signal = assembly._eligibility_signal(point, pending, ())
    scalar_signal = assembly._eligibility_signal(scalar, pending, ())

    assert point_signal is not None
    assert point_signal.state == "pending"
    assert point_signal.blocks_numeric
    assert scalar_signal is not None
    assert scalar_signal.state == "pending"
    assert not scalar_signal.blocks_numeric


def test_native_values_are_never_coerced_into_points() -> None:
    pending = assembly._nonpoint_value_signal(
        _item_with_value(NativeStateValue("pending")),
        (),
    )
    scalar = assembly._nonpoint_value_signal(
        _item_with_value(NativeScalarValue(4)),
        (),
    )
    unknown_state = assembly._nonpoint_value_signal(
        _item_with_value(NativeStateValue("absent")),
        (),
    )

    assert (pending.state, pending.reason_code) == ("pending", "native_state_pending")
    assert scalar.state == "insufficient_evidence"
    assert scalar.reason_code == "native_value_not_points"
    assert unknown_state.state == "insufficient_evidence"
    assert unknown_state.reason_code == "native_state_not_points"


def test_attempt_not_applicable_does_not_fabricate_selection() -> None:
    allowed, signal, provenance = assembly._resolve_work_attempt_scope(
        (_snapshot_resolution("not_applicable"),)
    )
    assert allowed is None
    assert signal is None
    assert provenance == ()


def test_selected_none_and_unresolved_reassessment_remain_nonnumeric() -> None:
    allowed, signal, _ = assembly._resolve_work_attempt_scope(
        (_snapshot_resolution("selected_none"),)
    )
    assert allowed == frozenset()
    assert signal is not None
    assert signal.state == "insufficient_evidence"
    assert signal.reason_code == "attempt_selection_selected_none"

    allowed, signal, _ = assembly._resolve_work_attempt_scope(
        (_snapshot_resolution("no_decision"),)
    )
    assert allowed == frozenset()
    assert signal is not None
    assert signal.state == "unresolved"
    assert signal.blocks_numeric
    assert signal.reason_code == "reassessment_no_decision"


def test_single_selected_reassessment_uses_only_explicit_allowed_sources() -> None:
    resolved = _snapshot_resolution("single_selected", operative=True)
    allowed, signal, _ = assembly._resolve_work_attempt_scope((resolved,))
    assert allowed == frozenset()
    assert signal is None


def test_exact_target_membership_missing_evidence_stays_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored_membership()
    monkeypatch.setattr(
        assembly,
        "list_grade_item_membership_work_refs",
        lambda *_args: (_work(),),
    )
    monkeypatch.setattr(
        assembly,
        "load_current_grade_item_membership_decision",
        lambda *_args: stored,
    )

    result = assembly._assemble_policy_item(
        root=Path("."),
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        participation=_participation(),
        work_evidence=(
            assembly.ConventionalGradeWorkEvidenceSpec(
                GRADE_ITEM_ID,
                _work(),
                "missing",
            ),
        ),
    )

    assert result.status == "missing"
    assert result.reason_codes == ("work_has_no_student_evidence",)
    assert result.earned is None
    assert result.possible is None


def test_same_period_different_calendar_revision_is_not_applicable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored_membership(calendar_revision=2)
    monkeypatch.setattr(
        assembly,
        "list_grade_item_membership_work_refs",
        lambda *_args: (_work(),),
    )
    monkeypatch.setattr(
        assembly,
        "load_current_grade_item_membership_decision",
        lambda *_args: stored,
    )

    result = assembly._assemble_policy_item(
        root=Path("."),
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        participation=_participation(),
        work_evidence=(),
    )

    assert result.status == "not_applicable"
    assert "membership_calendar_mismatch" in result.reason_codes


def test_other_period_is_not_inherited(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = _stored_membership(period=OTHER_PERIOD)
    monkeypatch.setattr(
        assembly,
        "list_grade_item_membership_work_refs",
        lambda *_args: (_work(),),
    )
    monkeypatch.setattr(
        assembly,
        "load_current_grade_item_membership_decision",
        lambda *_args: stored,
    )

    result = assembly._assemble_policy_item(
        root=Path("."),
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        participation=_participation(),
        work_evidence=(),
    )

    assert result.status == "not_applicable"
    assert "membership_period_mismatch" in result.reason_codes


def test_membership_bound_to_another_grade_item_revision_is_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored_membership(grade_item_sha="c" * 64)
    monkeypatch.setattr(
        assembly,
        "list_grade_item_membership_work_refs",
        lambda *_args: (_work(),),
    )
    monkeypatch.setattr(
        assembly,
        "load_current_grade_item_membership_decision",
        lambda *_args: stored,
    )

    result = assembly._assemble_policy_item(
        root=Path("."),
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        participation=_participation(),
        work_evidence=(),
    )

    assert result.status == "unresolved"
    assert result.reason_codes == ("membership_grade_item_basis_mismatch",)


def test_exact_membership_without_authorized_material_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _stored_membership()
    monkeypatch.setattr(
        assembly,
        "list_grade_item_membership_work_refs",
        lambda *_args: (_work(),),
    )
    monkeypatch.setattr(
        assembly,
        "load_current_grade_item_membership_decision",
        lambda *_args: stored,
    )

    result = assembly._assemble_policy_item(
        root=Path("."),
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        participation=_participation(),
        work_evidence=(
            assembly.ConventionalGradeWorkEvidenceSpec(
                GRADE_ITEM_ID,
                _work(),
                "unavailable",
            ),
        ),
    )

    assert result.status == "unavailable"
    assert result.reason_codes == ("authorized_projection_unavailable",)


def test_unconfigured_activation_cannot_calculate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        assembly,
        "resolve_grade_policy_activation",
        lambda *_args: SimpleNamespace(
            status="unconfigured",
            activation=None,
            policy_reference=None,
        ),
    )
    with pytest.raises(
        assembly.ConventionalGradeAssemblyDependencyError,
        match="explicitly activated",
    ):
        assembly.assemble_conventional_grade_calculation(
            tmp_path,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            (),
        )


def test_activation_calendar_revision_must_match_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        assembly,
        "resolve_grade_policy_activation",
        lambda *_args: SimpleNamespace(
            status="activated",
            activation=SimpleNamespace(
                decision=SimpleNamespace(calendar_revision=2)
            ),
            policy_reference=object(),
        ),
    )
    with pytest.raises(
        assembly.ConventionalGradeAssemblyScopeError,
        match="calendar_revision",
    ):
        assembly.assemble_conventional_grade_calculation(
            tmp_path,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            (),
        )
