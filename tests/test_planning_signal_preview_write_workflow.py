from __future__ import annotations

from types import SimpleNamespace

import pytest

import meridian.planning_signal_preview_write_workflow as workflow

CLASS_ID = "class_2026"
POLICY_ID = "reading_groups"
DERIVATION_ID = "gsd_" + "a" * 64
DERIVATION_SHA256 = "b" * 64


def _install_types(monkeypatch: pytest.MonkeyPatch) -> type[object]:
    class FakeReference:
        def __init__(
            self,
            *,
            class_id: str,
            derivation_id: str,
            derivation_sha256: str,
        ) -> None:
            self.class_id = class_id
            self.derivation_id = derivation_id
            self.derivation_sha256 = derivation_sha256

        def __eq__(self, other: object) -> bool:
            if not isinstance(other, FakeReference):
                return NotImplemented
            return (
                self.class_id,
                self.derivation_id,
                self.derivation_sha256,
            ) == (
                other.class_id,
                other.derivation_id,
                other.derivation_sha256,
            )

    monkeypatch.setattr(workflow, "GroupingSignalDerivationReference", FakeReference)
    monkeypatch.setattr(workflow, "StoredGroupingSignalDerivation", SimpleNamespace)
    return FakeReference


def _reference(reference_type: type[object]) -> object:
    return reference_type(
        class_id=CLASS_ID,
        derivation_id=DERIVATION_ID,
        derivation_sha256=DERIVATION_SHA256,
    )


def _stored(reference: object, *, policy_id: str = POLICY_ID) -> object:
    return SimpleNamespace(
        snapshot=SimpleNamespace(
            class_id=CLASS_ID,
            derivation_id=DERIVATION_ID,
            policy_reference=SimpleNamespace(
                class_id=CLASS_ID,
                policy_id=policy_id,
                policy_revision=2,
                policy_sha256="c" * 64,
            ),
            calculation_fingerprint="d" * 64,
            roster_basis=SimpleNamespace(
                student_ids=("student_001", "student_002"),
            ),
            student_derivations=(
                SimpleNamespace(disposition="contributing"),
                SimpleNamespace(disposition="noncontributing"),
            ),
        ),
        derivation_sha256=DERIVATION_SHA256,
        reference=reference,
    )


def _generation(reference: object) -> object:
    return SimpleNamespace(
        derivation_reference=reference,
        write_disposition="created",
        preview_id="gsp_" + "e" * 64,
        preview_sha256="f" * 64,
        preview_fingerprint="0" * 64,
        currentness_state="current",
        currentness_reason_codes=(),
        diagnostic_count=1,
        warning_diagnostic_ids=("gpd_" + "1" * 64,),
        blocking_diagnostic_ids=(),
        roster_student_count=2,
        contributing_student_count=1,
        noncontributing_student_count=1,
    )


def test_preflight_loads_exact_source_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_type = _install_types(monkeypatch)
    exact = _reference(reference_type)
    stored = _stored(exact)
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def load(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return stored

    monkeypatch.setattr(
        workflow,
        "load_grouping_signal_derivation_reference",
        load,
    )
    monkeypatch.setattr(
        workflow,
        "generate_planning_signal_preview",
        lambda *args, **kwargs: pytest.fail("preflight must not create #39"),
    )

    preview = workflow.preview_planning_signal_preview_write(
        "workspace",
        CLASS_ID,
        POLICY_ID,
        DERIVATION_ID,
        DERIVATION_SHA256,
    )

    assert observed == [(("workspace", exact), {})]
    assert preview.derivation_reference == exact
    assert preview.policy_reference.policy_id == POLICY_ID
    assert preview.roster_student_count == 2
    assert preview.contributing_student_count == 1
    assert preview.noncontributing_student_count == 1
    assert preview.preview_write_action == "not_performed"
    assert preview.review_write_action == "not_performed"
    assert preview.core_export_action == "not_performed"


def test_preflight_rejects_wrong_policy_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_type = _install_types(monkeypatch)
    exact = _reference(reference_type)
    monkeypatch.setattr(
        workflow,
        "load_grouping_signal_derivation_reference",
        lambda *args, **kwargs: _stored(exact, policy_id="other_policy"),
    )

    with pytest.raises(
        workflow.PlanningSignalPreviewWriteScopeError,
        match="different #37 policy family",
    ):
        workflow.preview_planning_signal_preview_write(
            "workspace",
            CLASS_ID,
            POLICY_ID,
            DERIVATION_ID,
            DERIVATION_SHA256,
        )


def test_commit_revalidates_source_then_delegates_canonical_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_type = _install_types(monkeypatch)
    exact = _reference(reference_type)
    stored = _stored(exact)
    monkeypatch.setattr(
        workflow,
        "load_grouping_signal_derivation_reference",
        lambda *args, **kwargs: stored,
    )
    preview = workflow.preview_planning_signal_preview_write(
        "workspace",
        CLASS_ID,
        POLICY_ID,
        DERIVATION_ID,
        DERIVATION_SHA256,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def generate(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _generation(exact)

    monkeypatch.setattr(
        workflow,
        "generate_planning_signal_preview",
        generate,
    )

    result = workflow.commit_planning_signal_preview_write(
        "workspace",
        preview,
    )

    assert observed == [
        (
            (
                "workspace",
                CLASS_ID,
                DERIVATION_ID,
                DERIVATION_SHA256,
            ),
            {},
        )
    ]
    assert result.preview_id == "gsp_" + "e" * 64
    assert result.write_disposition == "created"
    assert result.warning_diagnostic_ids == ("gpd_" + "1" * 64,)
    assert result.review_write_action == "not_performed"
    assert result.review_selection_action == "not_performed"
    assert result.core_export_action == "not_performed"
    assert result.csv_export_action == "not_performed"


def test_commit_rejects_source_drift_before_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_type = _install_types(monkeypatch)
    exact = _reference(reference_type)
    stored = _stored(exact)
    changed = _stored(exact)
    changed.snapshot.calculation_fingerprint = "9" * 64
    calls = iter((stored, changed))
    monkeypatch.setattr(
        workflow,
        "load_grouping_signal_derivation_reference",
        lambda *args, **kwargs: next(calls),
    )
    preview = workflow.preview_planning_signal_preview_write(
        "workspace",
        CLASS_ID,
        POLICY_ID,
        DERIVATION_ID,
        DERIVATION_SHA256,
    )
    monkeypatch.setattr(
        workflow,
        "generate_planning_signal_preview",
        lambda *args, **kwargs: pytest.fail("stale source must not create #39"),
    )

    with pytest.raises(
        workflow.PlanningSignalPreviewWriteStaleError,
        match="changed after",
    ):
        workflow.commit_planning_signal_preview_write(
            "workspace",
            preview,
        )
