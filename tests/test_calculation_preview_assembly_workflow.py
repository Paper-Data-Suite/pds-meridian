from __future__ import annotations

from types import SimpleNamespace

import pytest

import meridian.calculation_preview_assembly_workflow as workflow
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.standards_proficiency import (
    StandardProficiencyCalculationPolicyReference,
)

CLASS_ID = "class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"
TARGET_SCALE = ProficiencyScaleReference(
    class_id=CLASS_ID,
    scale_id="four_level",
    scale_revision=3,
    scale_sha256="a" * 64,
)
POLICY_REF = StandardProficiencyCalculationPolicyReference(
    class_id=CLASS_ID,
    policy_id="default_four_level",
    policy_revision=2,
    policy_sha256="b" * 64,
)


def binding(item_id: str) -> object:
    source = SimpleNamespace(
        work=SimpleNamespace(class_id=CLASS_ID),
        item_id=item_id,
    )
    return SimpleNamespace(source=source)


def selected_grade_item() -> object:
    return SimpleNamespace(
        revision=SimpleNamespace(grade_item_revision=4),
        revision_sha256="c" * 64,
    )


def exact_inputs() -> object:
    return SimpleNamespace(
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
    )


def calculation() -> object:
    return SimpleNamespace(
        result_write_performed=False,
        result_selection_performed=False,
    )


def install_runtime_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workflow,
        "StandardAggregationCandidateBinding",
        SimpleNamespace,
    )


def install_common(monkeypatch: pytest.MonkeyPatch) -> None:
    install_runtime_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "evidence_source_key",
        lambda source: f"source:{source.item_id}",
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_revision",
        lambda *args, **kwargs: selected_grade_item(),
    )


def test_assembly_resolves_only_explicit_bindings_then_calculates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_common(monkeypatch)
    bindings = (binding("item_1"), binding("item_2"))
    observed: dict[str, object] = {}

    def resolve(*args: object, **kwargs: object) -> object:
        observed["resolve"] = (args, kwargs)
        return exact_inputs()

    def preview(*args: object, **kwargs: object) -> object:
        observed["preview"] = (args, kwargs)
        return calculation()

    monkeypatch.setattr(
        workflow,
        "resolve_standard_aggregation_inputs",
        resolve,
    )
    monkeypatch.setattr(
        workflow,
        "build_calculation_preview_projection",
        preview,
    )

    result = workflow.build_bounded_calculation_preview(
        "workspace",
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        TARGET_SCALE,
        bindings,
        POLICY_REF,
    )

    resolve_args, resolve_kwargs = observed["resolve"]
    assert resolve_args[0] == "workspace"
    basis = resolve_args[1]
    assert basis.class_id == CLASS_ID
    assert basis.grade_item_id == GRADE_ITEM_ID
    assert basis.grade_item_revision == 4
    assert basis.grade_item_revision_sha256 == "c" * 64
    assert resolve_args[2:] == (
        STUDENT_ID,
        STANDARD_ID,
        TARGET_SCALE,
        bindings,
    )
    assert resolve_kwargs == {}

    assert observed["preview"] == (
        ("workspace", result.inputs, POLICY_REF),
        {},
    )
    assert result.bindings == bindings
    assert result.binding_count == 2
    assert result.source_keys == ("source:item_1", "source:item_2")
    assert result.result_write_performed is False
    assert result.result_selection_performed is False


def test_empty_explicit_binding_set_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_common(monkeypatch)
    observed: list[tuple[object, ...]] = []

    def resolve(*args: object, **kwargs: object) -> object:
        del kwargs
        observed.append(args)
        return exact_inputs()

    monkeypatch.setattr(
        workflow,
        "resolve_standard_aggregation_inputs",
        resolve,
    )
    monkeypatch.setattr(
        workflow,
        "build_calculation_preview_projection",
        lambda *args, **kwargs: calculation(),
    )

    result = workflow.build_bounded_calculation_preview(
        "workspace",
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        TARGET_SCALE,
        (),
        POLICY_REF,
    )

    assert observed[0][-1] == ()
    assert result.binding_count == 0
    assert result.source_keys == ()


def test_duplicate_source_is_rejected_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_common(monkeypatch)
    duplicate = binding("item_1")
    monkeypatch.setattr(
        workflow,
        "resolve_standard_aggregation_inputs",
        lambda *args, **kwargs: pytest.fail(
            "duplicate bindings must fail before canonical resolution"
        ),
    )

    with pytest.raises(
        workflow.CalculationPreviewAssemblyScopeError,
        match="must not duplicate",
    ):
        workflow.build_bounded_calculation_preview(
            "workspace",
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            TARGET_SCALE,
            (duplicate, duplicate),
            POLICY_REF,
        )


def test_missing_selected_grade_item_blocks_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_runtime_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "evidence_source_key",
        lambda source: f"source:{source.item_id}",
    )
    monkeypatch.setattr(
        workflow,
        "load_current_grade_item_revision",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        workflow,
        "resolve_standard_aggregation_inputs",
        lambda *args, **kwargs: pytest.fail(
            "missing selected Grade Item must block #33 resolution"
        ),
    )

    with pytest.raises(
        workflow.CalculationPreviewAssemblyDependencyError,
        match="explicitly selected Grade Item",
    ):
        workflow.build_bounded_calculation_preview(
            "workspace",
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            TARGET_SCALE,
            (binding("item_1"),),
            POLICY_REF,
        )


def test_cross_class_binding_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_runtime_types(monkeypatch)
    foreign = SimpleNamespace(
        source=SimpleNamespace(
            work=SimpleNamespace(class_id="other_class"),
            item_id="item_1",
        )
    )

    with pytest.raises(
        workflow.CalculationPreviewAssemblyScopeError,
        match="target class",
    ):
        workflow.build_bounded_calculation_preview(
            "workspace",
            GRADE_ITEM_ID,
            STUDENT_ID,
            STANDARD_ID,
            TARGET_SCALE,
            (foreign,),
            POLICY_REF,
        )
