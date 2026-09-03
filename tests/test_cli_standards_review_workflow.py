from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli
from meridian.proficiency_mapping import (
    NativeValueMappingProfileReference,
    ProficiencyScaleReference,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"
ITEM_ID = "scoreform_item_1"
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
SCALE_ID = "four_level"
SCALE_REVISION = 2
SCALE_SHA256 = "a" * 64
PROFILE_SCALE_ID = "four_level"
PROFILE_ID = "scoreform_points"
PROFILE_REVISION = 3
PROFILE_SHA256 = "b" * 64


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "standards-review",
        PUBLICATION_ID,
        CACHE_KEY,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        ITEM_ID,
        SCALE_ID,
        str(SCALE_REVISION),
        SCALE_SHA256,
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        "--scope-student-id",
        STUDENT_ID,
        *extra,
    )


def _authorized() -> object:
    work = SimpleNamespace(
        module_id="scoreform",
        class_id=CLASS_ID,
        work_id="test_1",
    )
    publication = SimpleNamespace(
        work=work,
        publication_id=PUBLICATION_ID,
    )
    return SimpleNamespace(
        stored=SimpleNamespace(
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
            snapshot=SimpleNamespace(
                source=SimpleNamespace(publication=publication),
            ),
        )
    )


def _standard_resolution() -> object:
    return SimpleNamespace(
        resolved=True,
        active=True,
    )


def _projection(
    *,
    mapping_profile: NativeValueMappingProfileReference | None = None,
    mapping_status: str | None = "mapped",
    aggregation_status: str = "performance",
    exclusion_reason: str | None = None,
) -> object:
    target_scale = ProficiencyScaleReference(
        class_id=CLASS_ID,
        scale_id=SCALE_ID,
        scale_revision=SCALE_REVISION,
        scale_sha256=SCALE_SHA256,
    )
    return SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        item_id=ITEM_ID,
        source=SimpleNamespace(item_id=ITEM_ID),
        producer_declared_standard_ids=(STANDARD_ID, "NJSLSA.R2"),
        producer_declares_standard=True,
        standard_resolution=_standard_resolution(),
        association_status="associated",
        association_revision=2,
        association_sha256="c" * 64,
        association_disposition="associated",
        association_basis="explicit",
        association_actor_kind="teacher",
        association_actor_id="teacher_42",
        association_rationale="Exact teacher association.",
        operative_associated=True,
        target_scale=target_scale,
        mapping_profile=mapping_profile,
        mapping_profile_supplied=mapping_profile is not None,
        mapping_status=mapping_status,
        mapped_proficiency_level_id=(
            "meets" if mapping_status == "mapped" else None
        ),
        native_state=None,
        mapping_unsupported_reason=None,
        result_kind="score",
        target_kind="standard",
        subject_kind="student",
        subject_student_id=STUDENT_ID,
        eligibility_state="included",
        attempt_state="selected",
        reassessment_state="contributing",
        aggregation_status=aggregation_status,
        aggregation_exclusion_reason=exclusion_reason,
        membership_revision=5,
        eligibility_revision=6,
        attempt_selection_revision=7,
        reassessment_revision=8,
        calculation_performed=False,
    )


def _install_authorization(monkeypatch: pytest.MonkeyPatch) -> object:
    authorized = _authorized()
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: SimpleNamespace(authorized=authorized),
    )
    return authorized


def test_workflow_help_exposes_standards_review_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "standards-review" in output
    assert "Review one exact evidence-to-standard interpretation path" in output


def test_review_uses_exact_authorization_and_scale_without_profile(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _authorized()
    observed: dict[str, object] = {}

    def inspect(*args: object, **kwargs: object) -> object:
        observed["inspect"] = (args, kwargs)
        return SimpleNamespace(authorized=authorized)

    def build(*args: object, **kwargs: object) -> object:
        observed["build"] = (args, kwargs)
        return _projection(
            mapping_profile=None,
            mapping_status=None,
            aggregation_status="excluded",
            exclusion_reason="mapping_not_supplied",
        )

    monkeypatch.setattr(cli, "inspect_evidence_diagnostic", inspect)
    monkeypatch.setattr(cli, "build_standards_review_projection", build)

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    _, inspect_kwargs = observed["inspect"]
    assert inspect_kwargs["authorization_purpose_id"] == "teacher_review"
    assert inspect_kwargs["requested_student_ids"] == (STUDENT_ID,)

    build_args, build_kwargs = observed["build"]
    assert build_args == (
        "synthetic-workspace",
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        ITEM_ID,
        ProficiencyScaleReference(
            class_id=CLASS_ID,
            scale_id=SCALE_ID,
            scale_revision=SCALE_REVISION,
            scale_sha256=SCALE_SHA256,
        ),
    )
    assert build_kwargs["authorized_snapshot"] is authorized
    assert build_kwargs["mapping_profile"] is None
    assert build_kwargs["attempt"] is None

    assert "Standards Review" in output
    assert "producer declares requested standard: yes" in output
    assert "association: associated" in output
    assert "mapping profile: none supplied" in output
    assert "aggregation: excluded (mapping_not_supplied)" in output
    assert "proficiency calculation performed: no" in output


def test_review_constructs_exact_mapping_profile_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorized = _install_authorization(monkeypatch)
    observed: dict[str, object] = {}

    def build(*args: object, **kwargs: object) -> object:
        observed["kwargs"] = kwargs
        profile = kwargs["mapping_profile"]
        return _projection(mapping_profile=profile)

    monkeypatch.setattr(cli, "build_standards_review_projection", build)

    assert cli.main(
        _arguments(
            "--mapping-profile-scale-id",
            PROFILE_SCALE_ID,
            "--mapping-profile-id",
            PROFILE_ID,
            "--mapping-profile-revision",
            str(PROFILE_REVISION),
            "--mapping-profile-sha256",
            PROFILE_SHA256,
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0

    profile = observed["kwargs"]["mapping_profile"]
    assert profile == NativeValueMappingProfileReference(
        class_id=CLASS_ID,
        scale_id=PROFILE_SCALE_ID,
        profile_id=PROFILE_ID,
        profile_revision=PROFILE_REVISION,
        profile_sha256=PROFILE_SHA256,
    )
    assert observed["kwargs"]["authorized_snapshot"] is authorized


def test_json_preserves_interpretation_layers_without_calculation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_authorization(monkeypatch)
    profile = NativeValueMappingProfileReference(
        class_id=CLASS_ID,
        scale_id=PROFILE_SCALE_ID,
        profile_id=PROFILE_ID,
        profile_revision=PROFILE_REVISION,
        profile_sha256=PROFILE_SHA256,
    )
    monkeypatch.setattr(
        cli,
        "build_standards_review_projection",
        lambda *args, **kwargs: _projection(mapping_profile=profile),
    )

    assert cli.main(
        _arguments(
            "--mapping-profile-scale-id",
            PROFILE_SCALE_ID,
            "--mapping-profile-id",
            PROFILE_ID,
            "--mapping-profile-revision",
            str(PROFILE_REVISION),
            "--mapping-profile-sha256",
            PROFILE_SHA256,
            "--format",
            "json",
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["producer_alignment"]["declares_requested_standard"] is True
    assert data["association"]["status"] == "associated"
    assert data["association"]["basis"] == "explicit"
    assert data["mapping"]["profile"]["profile_id"] == PROFILE_ID
    assert data["mapping"]["status"] == "mapped"
    assert data["upstream"]["eligibility_state"] == "included"
    assert data["aggregation"]["status"] == "performance"
    assert data["calculation_performed"] is False


def test_partial_mapping_profile_fails_before_evidence_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: pytest.fail(
            "partial profile identity must fail before protected evidence access"
        ),
    )

    assert cli.main(
        _arguments(
            "--mapping-profile-id",
            PROFILE_ID,
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 1
