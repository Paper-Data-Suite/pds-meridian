from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"
SCALE_ID = "four_level"
SCALE_REVISION = 3
SCALE_SHA256 = "a" * 64
POLICY_ID = "teacher_default"
POLICY_REVISION = 2
POLICY_SHA256 = "b" * 64
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
ITEM_ID = "item_001"


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "calculation-preview",
        CLASS_ID,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        SCALE_ID,
        str(SCALE_REVISION),
        SCALE_SHA256,
        POLICY_ID,
        str(POLICY_REVISION),
        POLICY_SHA256,
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        "--scope-student-id",
        STUDENT_ID,
        *extra,
    )


def _authorized(
    publication_id: str = PUBLICATION_ID,
    cache_key: str = CACHE_KEY,
) -> object:
    work = SimpleNamespace(
        module_id="scoreform",
        class_id=CLASS_ID,
        work_id="assessment_1",
    )
    publication = SimpleNamespace(
        work=work,
        publication_id=publication_id,
    )
    return SimpleNamespace(
        stored=SimpleNamespace(
            cache_key=cache_key,
            snapshot_digest="3" * 64,
            snapshot=SimpleNamespace(
                source=SimpleNamespace(publication=publication),
            ),
        )
    )


def _preview() -> object:
    scale = SimpleNamespace(
        scale_id=SCALE_ID,
        scale_revision=SCALE_REVISION,
        scale_sha256=SCALE_SHA256,
    )
    policy = SimpleNamespace(
        policy_id=POLICY_ID,
        policy_revision=POLICY_REVISION,
        policy_sha256=POLICY_SHA256,
    )
    outcome = SimpleNamespace(
        status="insufficient_evidence",
        proficiency_level_id=None,
        calculation_fingerprint="d" * 64,
        performance_observation_count=0,
        native_state_count=0,
        excluded_count=1,
        insufficiency_reasons=(
            SimpleNamespace(
                kind="blocking_exclusion",
                source_keys=("e" * 64,),
                required_observations=None,
                actual_observations=None,
            ),
        ),
        tie_resolution=None,
    )
    calculation = SimpleNamespace(
        policy_reference=policy,
        policy_title="Teacher default",
        strategy="median",
        minimum_performance_observations=2,
        mode_tie_rule=None,
        median_even_rule="higher",
        blocking_exclusion_reasons=("mapping_unmapped",),
        native_state_handling="blocking",
        input_entry_count=1,
        exclusion_reason_counts=(("mapping_unmapped", 1),),
        outcome=outcome,
        status=outcome.status,
        proficiency_level_id=None,
        calculation_fingerprint=outcome.calculation_fingerprint,
        result_history=(1, 2),
        next_result_revision=3,
        current_result_revision=1,
        result_write_performed=False,
        result_selection_performed=False,
    )
    basis = SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=4,
        grade_item_revision_sha256="f" * 64,
    )
    inputs = SimpleNamespace(
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        target_scale=scale,
        sha256="9" * 64,
    )
    return SimpleNamespace(
        grade_item_basis=basis,
        bindings=(),
        inputs=inputs,
        calculation=calculation,
        source_keys=(),
        binding_count=0,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        result_write_performed=False,
        result_selection_performed=False,
    )


def _install_cli_factories(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "EvidenceSourceReference",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(
        cli,
        "StandardAggregationCandidateBinding",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )


def test_workflow_help_exposes_calculation_preview(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "calculation-preview" in output
    assert "Preview one bounded Grade Item standards-proficiency calculation" in output


def test_zero_bindings_never_access_protected_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: pytest.fail(
            "zero-binding preview must not access protected evidence"
        ),
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def build(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _preview()

    monkeypatch.setattr(cli, "build_bounded_calculation_preview", build)

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert len(observed) == 1
    args, kwargs = observed[0]
    assert args[0:4] == (
        "synthetic-workspace",
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
    )
    assert args[5] == ()
    assert args[4].class_id == CLASS_ID
    assert args[4].scale_id == SCALE_ID
    assert args[6].class_id == CLASS_ID
    assert args[6].policy_id == POLICY_ID
    assert kwargs == {}
    assert "binding count: 0" in output
    assert "NO PROFICIENCY RESULT WRITTEN" in output
    assert "NO CURRENT RESULT SELECTION CHANGED" in output


def test_explicit_binding_and_profile_preserve_exact_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_cli_factories(monkeypatch)
    authorized = _authorized()
    observed: dict[str, object] = {}

    def inspect(*args: object, **kwargs: object) -> object:
        observed["inspect"] = (args, kwargs)
        return SimpleNamespace(
            authorized=authorized,
            items=(SimpleNamespace(item_id=ITEM_ID),),
        )

    def build(*args: object, **kwargs: object) -> object:
        observed["build"] = (args, kwargs)
        return _preview()

    monkeypatch.setattr(cli, "inspect_evidence_diagnostic", inspect)
    monkeypatch.setattr(cli, "build_bounded_calculation_preview", build)

    assert cli.main(
        _arguments(
            "--binding",
            PUBLICATION_ID,
            CACHE_KEY,
            ITEM_ID,
            "--binding-profile",
            PUBLICATION_ID,
            CACHE_KEY,
            ITEM_ID,
            SCALE_ID,
            "scoreform_points",
            "4",
            "c" * 64,
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0

    inspect_args, inspect_kwargs = observed["inspect"]
    assert inspect_args[0:3] == (
        "synthetic-workspace",
        PUBLICATION_ID,
        CACHE_KEY,
    )
    assert inspect_kwargs["authorization_purpose_id"] == "teacher_review"
    assert inspect_kwargs["requested_student_ids"] == (STUDENT_ID,)
    assert inspect_kwargs["filters"].item_ids == (ITEM_ID,)

    build_args, build_kwargs = observed["build"]
    assert build_kwargs == {}
    bindings = build_args[5]
    assert len(bindings) == 1
    candidate = bindings[0]
    assert candidate.source.item_id == ITEM_ID
    assert candidate.authorized_snapshot is authorized
    assert candidate.attempt is None
    assert candidate.mapping_profile.class_id == CLASS_ID
    assert candidate.mapping_profile.scale_id == SCALE_ID
    assert candidate.mapping_profile.profile_id == "scoreform_points"
    assert candidate.mapping_profile.profile_revision == 4
    assert candidate.mapping_profile.profile_sha256 == "c" * 64


def test_orphan_profile_fails_before_evidence_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: pytest.fail(
            "orphan profile must fail before protected evidence access"
        ),
    )

    assert cli.main(
        _arguments(
            "--binding-profile",
            PUBLICATION_ID,
            CACHE_KEY,
            ITEM_ID,
            SCALE_ID,
            "scoreform_points",
            "4",
            "c" * 64,
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 1


def test_duplicate_binding_fails_before_evidence_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: pytest.fail(
            "duplicate binding must fail before protected evidence access"
        ),
    )

    assert cli.main(
        _arguments(
            "--binding",
            PUBLICATION_ID,
            CACHE_KEY,
            ITEM_ID,
            "--binding",
            PUBLICATION_ID,
            CACHE_KEY,
            ITEM_ID,
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 1


def test_json_output_preserves_calculation_write_select_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "build_bounded_calculation_preview",
        lambda *args, **kwargs: _preview(),
    )

    assert cli.main(
        _arguments("--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["scope"]["class_id"] == CLASS_ID
    assert data["scope"]["grade_item_revision"] == 4
    assert data["bindings"]["count"] == 0
    assert data["inputs"]["sha256"] == "9" * 64
    assert data["policy"]["policy_id"] == POLICY_ID
    assert data["outcome"]["status"] == "insufficient_evidence"
    assert data["result_state"]["history"] == [1, 2]
    assert data["result_state"]["next_revision"] == 3
    assert data["result_state"]["current_revision"] == 1
    assert data["result_write_performed"] is False
    assert data["result_selection_performed"] is False
