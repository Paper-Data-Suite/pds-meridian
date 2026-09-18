from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.teacher_grade_override_workflow as workflow
from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.conventional_grade_assembly import ConventionalGradeAssemblyError
from meridian.conventional_grade_storage import (
    ConventionalGradeStorageIntegrityError,
)
from meridian.grade_policy import GradePolicyActor
from meridian.hybrid_grade_result import HybridGradeResultReference
from meridian.standards_grade_result import StandardsGradeResultReference
from meridian.teacher_grade_override import (
    TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
    TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideDecision,
    TeacherGradeOverrideReference,
    teacher_grade_override_decision_to_json_bytes,
    teacher_grade_override_reference,
)
from meridian.teacher_grade_override_workflow import (
    TeacherGradeOverrideAuthoringPreview,
    TeacherGradeOverrideAuthoringStaleError,
    TeacherGradeOverrideSelectedSource,
    TeacherGradeOverrideSourceCurrentnessError,
    TeacherGradeOverrideSourceIntegrityError,
    TeacherGradeOverrideSourceResult,
    TeacherGradeOverrideSourceUnavailableError,
    TeacherGradeOverrideWorkflowScopeError,
    assess_teacher_grade_override_applicability,
    commit_teacher_grade_override_authoring_preview,
    load_selected_teacher_grade_override_source,
    load_teacher_grade_override_source_result,
    preview_teacher_grade_override_authoring,
    resolve_selected_teacher_grade_override_source,
)

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "student_001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 17, 22, 0, tzinfo=UTC)


def source_reference(
    family: str = "conventional",
    *,
    revision: int = 1,
    digest: str = "a" * 64,
) -> GradeOverrideSourceResultReference:
    kwargs = {
        "class_id": CLASS_ID,
        "student_id": STUDENT_ID,
        "school_year": PERIOD.school_year,
        "period_id": PERIOD.period_id,
        "calendar_revision": 1,
        "result_revision": revision,
        "result_sha256": digest,
    }
    if family == "conventional":
        reference = ConventionalGradeResultReference(**kwargs)
    elif family == "standards_based":
        reference = StandardsGradeResultReference(**kwargs)
    elif family == "hybrid":
        reference = HybridGradeResultReference(**kwargs)
    else:
        raise AssertionError("unsupported test family")
    return GradeOverrideSourceResultReference(
        family,  # type: ignore[arg-type]
        reference,
    )


def exact_source(
    family: str = "conventional",
    *,
    status: str = "calculated",
    grade: Decimal | None = Decimal("76.5"),
    revision: int = 1,
    digest: str = "a" * 64,
) -> TeacherGradeOverrideSourceResult:
    if status != "calculated":
        grade = None
    return TeacherGradeOverrideSourceResult(
        source_result=source_reference(
            family,
            revision=revision,
            digest=digest,
        ),
        source_status=status,  # type: ignore[arg-type]
        base_grade=grade,
    )


def selected_source(
    family: str = "conventional",
    *,
    status: str = "calculated",
    grade: Decimal | None = Decimal("76.5"),
    freshness: str = "current",
    reasons: tuple[str, ...] = (),
    revision: int = 1,
    digest: str = "a" * 64,
) -> TeacherGradeOverrideSelectedSource:
    return TeacherGradeOverrideSelectedSource(
        source=exact_source(
            family,
            status=status,
            grade=grade,
            revision=revision,
            digest=digest,
        ),
        freshness_status=freshness,  # type: ignore[arg-type]
        freshness_reasons=reasons,
    )


def active_override(
    source: GradeOverrideSourceResultReference,
    *,
    revision: int = 1,
    replacement: Decimal = Decimal("88"),
) -> TeacherGradeOverrideDecision:
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family=source.family,
        override_revision=revision,
        supersedes_revision=None if revision == 1 else revision - 1,
        decision="override",
        source_result=source,
        replacement_grade=replacement,
        withdrawn_override_reference=None,
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale=f"Synthetic active override revision {revision}.",
        decided_at=NOW + timedelta(minutes=revision - 1),
    )


def withdrawal(
    active: TeacherGradeOverrideDecision,
    *,
    revision: int = 2,
) -> TeacherGradeOverrideDecision:
    return TeacherGradeOverrideDecision(
        schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
        record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
        class_id=active.class_id,
        student_id=active.student_id,
        target_period=active.target_period,
        calendar_revision=active.calendar_revision,
        calculation_family=active.calculation_family,
        override_revision=revision,
        supersedes_revision=revision - 1,
        decision="withdraw",
        source_result=active.source_result,
        replacement_grade=None,
        withdrawn_override_reference=teacher_grade_override_reference(active),
        actor=GradePolicyActor("teacher", "teacher_local"),
        rationale="Synthetic withdrawal.",
        decided_at=NOW + timedelta(minutes=revision - 1),
    )


def fake_stored(
    family: str,
    *,
    status: str = "calculated",
    grade: Decimal | None = Decimal("76.5"),
    revision: int = 1,
    digest: str = "a" * 64,
) -> SimpleNamespace:
    source = source_reference(family, revision=revision, digest=digest)
    if status != "calculated":
        grade = None
    return SimpleNamespace(
        reference=source.reference,
        snapshot=SimpleNamespace(
            outcome=SimpleNamespace(status=status, rounded_grade=grade)
        ),
    )


def make_preview(
    source: TeacherGradeOverrideSelectedSource | None = None,
    *,
    history: tuple[int, ...] = (),
    latest_digest: str | None = None,
) -> TeacherGradeOverrideAuthoringPreview:
    reviewed = source or selected_source()
    revision = len(history) + 1
    candidate = active_override(
        reviewed.source_result,
        revision=revision,
        replacement=Decimal("105.25"),
    )
    digest = hashlib.sha256(
        teacher_grade_override_decision_to_json_bytes(candidate)
    ).hexdigest()
    return TeacherGradeOverrideAuthoringPreview(
        source=reviewed,
        history_before=history,
        latest_override_sha256_before=latest_digest,
        candidate=candidate,
        candidate_sha256=digest,
    )


@pytest.mark.parametrize(
    ("family", "loader_name"),
    [
        ("conventional", "load_current_conventional_grade_result"),
        ("standards_based", "load_current_standards_grade_result"),
        ("hybrid", "load_current_hybrid_grade_result"),
    ],
)
def test_selected_source_dispatches_only_to_explicit_family(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    loader_name: str,
) -> None:
    stored = fake_stored(family)
    called: list[str] = []

    def selected_loader(*args: object, **kwargs: object) -> SimpleNamespace:
        called.append(loader_name)
        return stored

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("wrong Grade-result family loader was called")

    for name in (
        "load_current_conventional_grade_result",
        "load_current_standards_grade_result",
        "load_current_hybrid_grade_result",
    ):
        monkeypatch.setattr(
            workflow,
            name,
            selected_loader if name == loader_name else forbidden,
        )

    result = load_selected_teacher_grade_override_source(
        Path("."),
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        family,  # type: ignore[arg-type]
    )

    assert result.source_result.family == family
    assert result.source_status == "calculated"
    assert result.base_grade == Decimal("76.5")
    assert called == [loader_name]


@pytest.mark.parametrize(
    ("family", "loader_name"),
    [
        ("conventional", "load_current_conventional_grade_result"),
        ("standards_based", "load_current_standards_grade_result"),
        ("hybrid", "load_current_hybrid_grade_result"),
    ],
)
def test_missing_explicit_source_selection_is_not_latest_fallback(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    loader_name: str,
) -> None:
    monkeypatch.setattr(workflow, loader_name, lambda *args, **kwargs: None)

    with pytest.raises(TeacherGradeOverrideSourceUnavailableError):
        load_selected_teacher_grade_override_source(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            family,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("family", "loader_name"),
    [
        ("conventional", "load_conventional_grade_result_revision"),
        ("standards_based", "load_standards_grade_result_revision"),
        ("hybrid", "load_hybrid_grade_result_revision"),
    ],
)
def test_exact_source_load_requires_reference_digest_equality(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    loader_name: str,
) -> None:
    requested = source_reference(family, digest="a" * 64)
    monkeypatch.setattr(
        workflow,
        loader_name,
        lambda *args, **kwargs: fake_stored(family, digest="b" * 64),
    )

    with pytest.raises(TeacherGradeOverrideSourceIntegrityError):
        load_teacher_grade_override_source_result(Path("."), requested)


def test_source_storage_integrity_failure_is_not_source_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise ConventionalGradeStorageIntegrityError("tampered current pointer")

    monkeypatch.setattr(
        workflow,
        "load_current_conventional_grade_result",
        broken,
    )

    with pytest.raises(TeacherGradeOverrideSourceIntegrityError):
        load_selected_teacher_grade_override_source(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            "conventional",
        )


@pytest.mark.parametrize(
    ("family", "current_loader", "assembler", "assessor", "work_evidence"),
    [
        (
            "conventional",
            "load_current_conventional_grade_result",
            "assemble_conventional_grade_calculation",
            "assess_conventional_grade_result_freshness",
            (),
        ),
        (
            "standards_based",
            "load_current_standards_grade_result",
            "assemble_standards_grade_calculation",
            "assess_standards_grade_result_freshness",
            None,
        ),
        (
            "hybrid",
            "load_current_hybrid_grade_result",
            "assemble_hybrid_grade_calculation",
            "assess_hybrid_grade_result_freshness",
            (),
        ),
    ],
)
def test_selected_source_reuses_family_freshness_contract(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    current_loader: str,
    assembler: str,
    assessor: str,
    work_evidence: tuple[object, ...] | None,
) -> None:
    stored = fake_stored(family)
    monkeypatch.setattr(workflow, current_loader, lambda *args, **kwargs: stored)
    monkeypatch.setattr(
        workflow,
        assembler,
        lambda *args, **kwargs: SimpleNamespace(inputs=object()),
    )
    monkeypatch.setattr(
        workflow,
        assessor,
        lambda *args, **kwargs: SimpleNamespace(
            status="stale",
            reasons=("policy_changed",),
        ),
    )

    kwargs: dict[str, object] = {}
    if work_evidence is not None:
        kwargs["work_evidence"] = work_evidence
    result = resolve_selected_teacher_grade_override_source(
        Path("."),
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        family,  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )

    assert result.source_result.family == family
    assert result.freshness_status == "stale"
    assert result.freshness_reasons == ("policy_changed",)


@pytest.mark.parametrize("family", ["conventional", "hybrid"])
def test_evidence_bounded_families_require_explicit_work_evidence(
    monkeypatch: pytest.MonkeyPatch,
    family: str,
) -> None:
    loader_name = (
        "load_current_conventional_grade_result"
        if family == "conventional"
        else "load_current_hybrid_grade_result"
    )
    monkeypatch.setattr(
        workflow,
        loader_name,
        lambda *args, **kwargs: fake_stored(family),
    )

    with pytest.raises(TeacherGradeOverrideWorkflowScopeError):
        resolve_selected_teacher_grade_override_source(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            family,  # type: ignore[arg-type]
        )


def test_standards_freshness_rejects_conventional_work_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "load_current_standards_grade_result",
        lambda *args, **kwargs: fake_stored("standards_based"),
    )

    with pytest.raises(TeacherGradeOverrideWorkflowScopeError):
        resolve_selected_teacher_grade_override_source(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            "standards_based",
            work_evidence=(object(),),  # type: ignore[arg-type]
        )


def test_source_selection_change_during_freshness_is_explicit_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = fake_stored("conventional", revision=1, digest="a" * 64)
    second = fake_stored("conventional", revision=2, digest="b" * 64)
    values = iter((first, second))
    monkeypatch.setattr(
        workflow,
        "load_current_conventional_grade_result",
        lambda *args, **kwargs: next(values),
    )
    monkeypatch.setattr(
        workflow,
        "assemble_conventional_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(inputs=object()),
    )

    with pytest.raises(TeacherGradeOverrideAuthoringStaleError):
        resolve_selected_teacher_grade_override_source(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            "conventional",
            work_evidence=(),
        )


def test_family_assembly_failure_does_not_claim_source_is_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        workflow,
        "load_current_conventional_grade_result",
        lambda *args, **kwargs: fake_stored("conventional"),
    )

    def failed_assembly(*args: object, **kwargs: object) -> None:
        raise ConventionalGradeAssemblyError("current basis unavailable")

    monkeypatch.setattr(
        workflow,
        "assemble_conventional_grade_calculation",
        failed_assembly,
    )

    with pytest.raises(TeacherGradeOverrideSourceCurrentnessError):
        resolve_selected_teacher_grade_override_source(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            "conventional",
            work_evidence=(),
        )


@pytest.mark.parametrize("status", ["calculated", "blocked", "insufficient"])
def test_source_contract_preserves_all_supported_base_statuses(status: str) -> None:
    source = exact_source(
        status=status,
        grade=Decimal("74.5") if status == "calculated" else None,
    )

    assert source.source_status == status
    assert source.base_grade == (
        Decimal("74.5") if status == "calculated" else None
    )


def test_applicability_is_exact_reference_based_and_non_floating() -> None:
    current = selected_source(revision=2, digest="b" * 64)
    old = active_override(source_reference(revision=1, digest="a" * 64))

    result = assess_teacher_grade_override_applicability(current, old)

    assert result.status == "source_mismatch"
    assert result.reasons == ("source_result_mismatch",)


def test_same_selected_source_and_current_freshness_is_applicable() -> None:
    current = selected_source()
    active = active_override(current.source_result)

    result = assess_teacher_grade_override_applicability(current, active)

    assert result.status == "applicable"
    assert result.reasons == ()


def test_stale_selected_source_makes_matching_active_override_nonapplicable() -> None:
    current = selected_source(
        freshness="stale",
        reasons=("policy_changed",),
    )
    active = active_override(current.source_result)

    result = assess_teacher_grade_override_applicability(current, active)

    assert result.status == "source_stale"
    assert result.reasons == ("source_result_stale",)


def test_selected_withdrawal_has_no_active_override_precedence() -> None:
    current = selected_source()
    active = active_override(current.source_result)
    withdrawn = withdrawal(active)

    result = assess_teacher_grade_override_applicability(current, withdrawn)

    assert result.status == "withdrawn"
    assert result.reasons == ("selected_override_withdrawn",)


@pytest.mark.parametrize("status", ["calculated", "blocked", "insufficient"])
def test_authoring_preview_binds_exact_selected_source_for_all_base_statuses(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    reviewed = selected_source(
        status=status,
        grade=Decimal("76.5") if status == "calculated" else None,
    )
    monkeypatch.setattr(
        workflow,
        "resolve_selected_teacher_grade_override_source",
        lambda *args, **kwargs: reviewed,
    )
    monkeypatch.setattr(
        workflow,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (),
    )

    preview = preview_teacher_grade_override_authoring(
        Path("."),
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        "conventional",
        replacement_grade=Decimal("105.25"),
        actor_id="teacher_local",
        rationale="Documented teacher decision.",
        decided_at=NOW,
        work_evidence=(),
    )

    assert preview.candidate.override_revision == 1
    assert preview.candidate.source_result == reviewed.source_result
    assert preview.candidate.replacement_grade == Decimal("105.25")
    assert preview.candidate.actor == GradePolicyActor("teacher", "teacher_local")
    assert preview.source.source_status == status


def test_authoring_preview_allows_stale_source_but_preserves_warning_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = selected_source(
        freshness="stale",
        reasons=("inputs_changed",),
    )
    monkeypatch.setattr(
        workflow,
        "resolve_selected_teacher_grade_override_source",
        lambda *args, **kwargs: reviewed,
    )
    monkeypatch.setattr(
        workflow,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (),
    )

    preview = preview_teacher_grade_override_authoring(
        Path("."),
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        "conventional",
        replacement_grade=Decimal("90"),
        actor_id="teacher_local",
        rationale="Recorded despite stale selected calculation.",
        decided_at=NOW,
        work_evidence=(),
    )

    assert preview.source.freshness_status == "stale"
    assert assess_teacher_grade_override_applicability(
        preview.source,
        preview.candidate,
    ).status == "source_stale"


def test_authoring_preview_appends_to_latest_history_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = selected_source()
    monkeypatch.setattr(
        workflow,
        "resolve_selected_teacher_grade_override_source",
        lambda *args, **kwargs: reviewed,
    )
    monkeypatch.setattr(
        workflow,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    prior = active_override(
        reviewed.source_result,
        revision=1,
        replacement=Decimal("88"),
    )
    monkeypatch.setattr(
        workflow,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: SimpleNamespace(
            decision=prior,
            override_sha256="d" * 64,
        ),
    )

    preview = preview_teacher_grade_override_authoring(
        Path("."),
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        "conventional",
        replacement_grade=Decimal("92"),
        actor_id="teacher_local",
        rationale="Correction creates another immutable decision.",
        decided_at=NOW + timedelta(minutes=1),
        work_evidence=(),
    )

    assert preview.history_before == (1,)
    assert preview.latest_override_sha256_before == "d" * 64
    assert preview.candidate.override_revision == 2
    assert preview.candidate.supersedes_revision == 1


def test_commit_rechecks_source_before_inside_and_after_guarded_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = make_preview()
    selected_calls: list[int] = []
    guard_calls: list[str] = []
    monkeypatch.setattr(
        workflow,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (),
    )

    def selected(*args: object, **kwargs: object) -> TeacherGradeOverrideSourceResult:
        selected_calls.append(1)
        return preview.source.source

    monkeypatch.setattr(
        workflow,
        "load_selected_teacher_grade_override_source",
        selected,
    )

    def write(
        root: object,
        candidate: TeacherGradeOverrideDecision,
        *,
        precommit_guard: object,
    ) -> SimpleNamespace:
        assert callable(precommit_guard)
        precommit_guard()
        guard_calls.append("inside")
        return SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(
                decision=candidate,
                override_sha256=preview.candidate_sha256,
                reference=teacher_grade_override_reference(candidate),
            ),
        )

    monkeypatch.setattr(workflow, "write_teacher_grade_override_revision", write)
    monkeypatch.setattr(
        workflow,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: None,
    )

    result = commit_teacher_grade_override_authoring_preview(Path("."), preview)

    assert result.write_disposition == "created"
    assert result.selected_override_after is None
    assert selected_calls == [1, 1, 1]
    assert guard_calls == ["inside"]


def test_commit_fails_if_source_selection_changed_before_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = make_preview()
    changed = exact_source(revision=2, digest="b" * 64)
    monkeypatch.setattr(
        workflow,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        workflow,
        "load_selected_teacher_grade_override_source",
        lambda *args, **kwargs: changed,
    )

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("stale source must block override write")

    monkeypatch.setattr(workflow, "write_teacher_grade_override_revision", forbidden)

    with pytest.raises(TeacherGradeOverrideAuthoringStaleError):
        commit_teacher_grade_override_authoring_preview(Path("."), preview)


def test_commit_fails_if_source_moves_inside_precommit_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = make_preview()
    changed = exact_source(revision=2, digest="b" * 64)
    values = iter((preview.source.source, changed))
    monkeypatch.setattr(
        workflow,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        workflow,
        "load_selected_teacher_grade_override_source",
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
        raise AssertionError("guard should have raised stale")

    monkeypatch.setattr(workflow, "write_teacher_grade_override_revision", write)

    with pytest.raises(TeacherGradeOverrideAuthoringStaleError):
        commit_teacher_grade_override_authoring_preview(Path("."), preview)


def test_commit_fails_closed_if_source_moves_after_immutable_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = make_preview()
    changed = exact_source(revision=2, digest="b" * 64)
    values = iter((preview.source.source, preview.source.source, changed))
    monkeypatch.setattr(
        workflow,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        workflow,
        "load_selected_teacher_grade_override_source",
        lambda *args, **kwargs: next(values),
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
            stored=SimpleNamespace(
                decision=candidate,
                override_sha256=preview.candidate_sha256,
                reference=teacher_grade_override_reference(candidate),
            ),
        )

    monkeypatch.setattr(workflow, "write_teacher_grade_override_revision", write)

    with pytest.raises(TeacherGradeOverrideAuthoringStaleError):
        commit_teacher_grade_override_authoring_preview(Path("."), preview)


def test_commit_rejects_override_history_change_after_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = make_preview()
    monkeypatch.setattr(
        workflow,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1, 2),
    )

    with pytest.raises(TeacherGradeOverrideAuthoringStaleError):
        commit_teacher_grade_override_authoring_preview(Path("."), preview)


def test_exact_commit_replay_remains_idempotent_without_rerunning_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = make_preview()
    stored_reference = teacher_grade_override_reference(preview.candidate)
    monkeypatch.setattr(
        workflow,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        workflow,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: SimpleNamespace(
            decision=preview.candidate,
            override_sha256=preview.candidate_sha256,
        ),
    )

    def write(
        root: object,
        candidate: TeacherGradeOverrideDecision,
        *,
        precommit_guard: object,
    ) -> SimpleNamespace:
        assert precommit_guard is None
        return SimpleNamespace(
            disposition="existing",
            stored=SimpleNamespace(
                decision=candidate,
                override_sha256=preview.candidate_sha256,
                reference=stored_reference,
            ),
        )

    monkeypatch.setattr(workflow, "write_teacher_grade_override_revision", write)
    monkeypatch.setattr(
        workflow,
        "load_selected_teacher_grade_override_source",
        lambda *args, **kwargs: preview.source.source,
    )
    monkeypatch.setattr(
        workflow,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: None,
    )

    result = commit_teacher_grade_override_authoring_preview(Path("."), preview)

    assert result.write_disposition == "existing"
    assert result.stored_reference == stored_reference


def test_exact_replay_with_different_existing_bytes_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = make_preview()
    different = replace(preview.candidate, rationale="Different persisted rationale.")
    monkeypatch.setattr(
        workflow,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        workflow,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: SimpleNamespace(
            decision=different,
            override_sha256="f" * 64,
        ),
    )

    with pytest.raises(TeacherGradeOverrideAuthoringStaleError):
        commit_teacher_grade_override_authoring_preview(Path("."), preview)


def test_authoring_result_can_report_unchanged_existing_override_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = make_preview()
    old_selection = TeacherGradeOverrideReference(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        school_year=PERIOD.school_year,
        period_id=PERIOD.period_id,
        calendar_revision=1,
        calculation_family="conventional",
        override_revision=7,
        override_sha256="e" * 64,
    )
    monkeypatch.setattr(
        workflow,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        workflow,
        "load_selected_teacher_grade_override_source",
        lambda *args, **kwargs: preview.source.source,
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
            stored=SimpleNamespace(
                decision=candidate,
                override_sha256=preview.candidate_sha256,
                reference=teacher_grade_override_reference(candidate),
            ),
        )

    monkeypatch.setattr(workflow, "write_teacher_grade_override_revision", write)
    monkeypatch.setattr(
        workflow,
        "get_current_teacher_grade_override_reference",
        lambda *args, **kwargs: old_selection,
    )

    result = commit_teacher_grade_override_authoring_preview(Path("."), preview)

    assert result.selected_override_after == old_selection
    assert result.stored_reference != old_selection


def test_authoring_preview_rejects_backwards_decision_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = selected_source()
    prior = replace(
        active_override(reviewed.source_result),
        decided_at=NOW + timedelta(minutes=10),
    )
    monkeypatch.setattr(
        workflow,
        "resolve_selected_teacher_grade_override_source",
        lambda *args, **kwargs: reviewed,
    )
    monkeypatch.setattr(
        workflow,
        "list_teacher_grade_override_revisions",
        lambda *args, **kwargs: (1,),
    )
    monkeypatch.setattr(
        workflow,
        "load_teacher_grade_override_revision",
        lambda *args, **kwargs: SimpleNamespace(
            decision=prior,
            override_sha256="d" * 64,
        ),
    )

    with pytest.raises(TeacherGradeOverrideWorkflowScopeError):
        preview_teacher_grade_override_authoring(
            Path("."),
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            "conventional",
            replacement_grade=Decimal("90"),
            actor_id="teacher_local",
            rationale="Chronology regression should fail in preview.",
            decided_at=NOW + timedelta(minutes=1),
            work_evidence=(),
        )
