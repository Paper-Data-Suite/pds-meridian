from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.conventional_grade_storage as storage
from meridian.conventional_grade import (
    ConventionalGradeCalculationInput,
    ConventionalGradeItemInput,
    calculate_conventional_grade,
    create_conventional_grade_result_snapshot,
)
from meridian.grade_policy import (
    ConventionalGradeConfiguration,
    GradePolicyItemParticipation,
    GradePolicyItemReference,
    GradePolicyReference,
    GradeRoundingPolicy,
    GradeStateTreatment,
)
from meridian.grade_policy_activation import GradePolicyActivationReference

CLASS_ID = "synthetic_class_2026"
STUDENT_ID = "s001"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _treatment() -> GradeStateTreatment:
    return GradeStateTreatment(
        missing="blocking",
        pending="blocking",
        incomplete="blocking",
        excused="exclude",
        excluded="exclude",
        not_applicable="exclude",
        insufficient_evidence="blocking",
        unavailable="blocking",
        withdrawn="exclude",
        invalid="exclude",
        unresolved="blocking",
    )


def _input(*, earned: str = "8") -> ConventionalGradeCalculationInput:
    item_ref = GradePolicyItemReference(CLASS_ID, "quiz", 1, SHA_C)
    participation = GradePolicyItemParticipation(
        item_ref,
        None,
        None,
        Decimal("10"),
    )
    item = ConventionalGradeItemInput(
        participation=participation,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        status="points",
        earned=Decimal(earned),
        possible=Decimal("10"),
    )
    return ConventionalGradeCalculationInput(
        class_id=CLASS_ID,
        student_id=STUDENT_ID,
        target_period=PERIOD,
        calendar_revision=1,
        activation_reference=GradePolicyActivationReference(
            CLASS_ID,
            PERIOD.school_year,
            PERIOD.period_id,
            1,
            SHA_A,
        ),
        policy_reference=GradePolicyReference(
            CLASS_ID,
            "grade_policy",
            1,
            SHA_B,
        ),
        configuration=ConventionalGradeConfiguration(
            "total_points",
            (participation,),
            (),
        ),
        state_treatment=_treatment(),
        rounding=GradeRoundingPolicy(Decimal("0.01"), "half_up", "final"),
        items=(item,),
    )


def _result(
    revision: int = 1,
    *,
    earned: str = "8",
    calculated_at: datetime | None = None,
):
    inputs = _input(earned=earned)
    return create_conventional_grade_result_snapshot(
        inputs,
        calculate_conventional_grade(inputs),
        result_revision=revision,
        calculated_at=calculated_at or NOW,
    )


def _workspace(tmp_path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "classes" / CLASS_ID).mkdir(parents=True)

    def refresh(*args: object, **kwargs: object) -> object:
        snapshot = kwargs.pop("_snapshot", None)
        del args, kwargs, snapshot
        raise AssertionError("refresh stub must be replaced per test")

    monkeypatch.setattr(storage, "_validate_historical_dependencies", lambda *a: None)
    return tmp_path


def _allow_refresh(monkeypatch: pytest.MonkeyPatch, snapshot) -> None:
    monkeypatch.setattr(
        storage,
        "assemble_conventional_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(
            inputs=snapshot.inputs,
            outcome=snapshot.outcome,
        ),
    )


def _write(tmp_path, monkeypatch: pytest.MonkeyPatch, snapshot):
    _allow_refresh(monkeypatch, snapshot)
    return storage.write_conventional_grade_result_revision(
        tmp_path,
        snapshot,
        work_evidence=(),
    )


def test_write_is_immutable_idempotent_and_does_not_select(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    result = _result()
    created = _write(tmp_path, monkeypatch, result)
    assert created.disposition == "created"
    assert storage.get_current_conventional_grade_result_revision(
        tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1
    ) is None
    replay = _write(tmp_path, monkeypatch, result)
    assert replay.disposition == "existing"
    assert replay.stored.result_sha256 == created.stored.result_sha256


def test_subject_path_is_hashed_and_result_retains_student_identity(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    stored = _write(tmp_path, monkeypatch, _result()).stored
    subject_key = storage.conventional_grade_subject_key(
        CLASS_ID, STUDENT_ID, PERIOD, 1
    )
    assert len(subject_key) == 64
    assert STUDENT_ID not in stored.relative_path
    assert f"/students/{subject_key}/" in stored.relative_path
    assert stored.snapshot.student_id == STUDENT_ID


def test_same_revision_different_bytes_conflicts(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    _write(tmp_path, monkeypatch, _result())
    with pytest.raises(storage.ConventionalGradeStorageConflictError):
        _write(tmp_path, monkeypatch, _result(earned="7"))


def test_revision_history_is_contiguous_and_exactly_replayable(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    first = _result()
    second = _result(
        2,
        earned="7",
        calculated_at=NOW + timedelta(minutes=1),
    )
    _write(tmp_path, monkeypatch, first)
    _write(tmp_path, monkeypatch, second)
    assert storage.list_conventional_grade_result_revisions(
        tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1
    ) == (1, 2)
    loaded = storage.load_conventional_grade_result_revision(
        tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1, 2
    )
    assert loaded.snapshot == second


def test_current_selection_is_explicit_cas_and_historical_reselection_works(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    first = _result()
    second = _result(
        2,
        earned="7",
        calculated_at=NOW + timedelta(minutes=1),
    )
    _write(tmp_path, monkeypatch, first)
    _write(tmp_path, monkeypatch, second)
    assert storage.get_current_conventional_grade_result_revision(
        tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1
    ) is None

    selected = storage.select_conventional_grade_result_revision(
        tmp_path,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        2,
        expected_current_result_revision=None,
    )
    assert selected.disposition == "created"
    assert storage.load_current_conventional_grade_result(
        tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1
    ).snapshot.result_revision == 2

    with pytest.raises(storage.ConventionalGradeStorageConflictError):
        storage.select_conventional_grade_result_revision(
            tmp_path,
            CLASS_ID,
            STUDENT_ID,
            PERIOD,
            1,
            1,
            expected_current_result_revision=None,
        )

    historical = storage.select_conventional_grade_result_revision(
        tmp_path,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        1,
        expected_current_result_revision=2,
    )
    assert historical.disposition == "updated"
    assert historical.stored.snapshot.result_revision == 1


def test_new_write_fails_when_exact_reassembly_changes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    snapshot = _result()
    other = _result(earned="7")
    monkeypatch.setattr(
        storage,
        "assemble_conventional_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(
            inputs=other.inputs,
            outcome=other.outcome,
        ),
    )
    with pytest.raises(storage.ConventionalGradeStorageConflictError, match="changed"):
        storage.write_conventional_grade_result_revision(
            tmp_path,
            snapshot,
            work_evidence=(),
        )


def test_tampered_result_bytes_are_detected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    stored = _write(tmp_path, monkeypatch, _result()).stored
    stored.path.write_bytes(stored.content.replace(
            b'"rounded_grade": "80"', b'"rounded_grade": "81"'
        ))
    with pytest.raises(storage.ConventionalGradeStorageIntegrityError):
        storage.load_conventional_grade_result_revision(
            tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1, 1
        )


def test_tampered_digest_is_detected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    stored = _write(tmp_path, monkeypatch, _result()).stored
    (stored.path.parent / "1.json.sha256").write_text("0" * 64 + "\n")
    with pytest.raises(storage.ConventionalGradeStorageIntegrityError):
        storage.load_conventional_grade_result_revision(
            tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1, 1
        )


def test_malformed_pointer_is_detected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    _write(tmp_path, monkeypatch, _result())
    storage.select_conventional_grade_result_revision(
        tmp_path,
        CLASS_ID,
        STUDENT_ID,
        PERIOD,
        1,
        1,
        expected_current_result_revision=None,
    )
    pointer = storage.conventional_grade_result_current_path(
        tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1
    )
    pointer.write_text('{"record_type":"broken"}\n')
    with pytest.raises(storage.ConventionalGradeStorageIntegrityError):
        storage.load_current_conventional_grade_result(
            tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1
        )


def test_unexpected_family_entry_is_detected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    stored = _write(tmp_path, monkeypatch, _result()).stored
    stored.path.parent.parent.joinpath("surprise.txt").write_text("x")
    with pytest.raises(storage.ConventionalGradeStorageIntegrityError):
        storage.list_conventional_grade_result_revisions(
            tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1
        )


def test_incomplete_revision_pair_is_detected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    stored = _write(tmp_path, monkeypatch, _result()).stored
    (stored.path.parent / "1.json.sha256").unlink()
    with pytest.raises(
        storage.ConventionalGradeStorageIntegrityError, match="incomplete"
    ):
        storage.list_conventional_grade_result_revisions(
            tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1
        )


def test_bounded_result_read_fails_before_unbounded_parse(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    _write(tmp_path, monkeypatch, _result())
    monkeypatch.setattr(storage, "DEFAULT_MAXIMUM_CONVENTIONAL_GRADE_RESULT_BYTES", 1)
    with pytest.raises(storage.ConventionalGradeStorageTooLargeError):
        storage.load_conventional_grade_result_revision(
            tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1, 1
        )


def test_symlinked_result_revision_is_rejected_when_supported(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    stored = _write(tmp_path, monkeypatch, _result()).stored
    original = stored.path
    replacement = original.with_name("outside.json")
    replacement.write_bytes(stored.content)
    original.unlink()
    try:
        original.symlink_to(replacement)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform")
    with pytest.raises(storage.ConventionalGradeStorageIntegrityError):
        storage.load_conventional_grade_result_revision(
            tmp_path, CLASS_ID, STUDENT_ID, PERIOD, 1, 1
        )


def test_digest_written_is_lowercase_sha256_of_exact_bytes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _workspace(tmp_path, monkeypatch)
    stored = _write(tmp_path, monkeypatch, _result()).stored
    digest_text = (stored.path.parent / "1.json.sha256").read_text().strip()
    assert digest_text == hashlib.sha256(stored.content).hexdigest()
    assert digest_text == digest_text.lower()
