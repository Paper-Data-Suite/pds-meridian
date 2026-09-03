from __future__ import annotations

from types import SimpleNamespace

import pytest

import meridian.planning_signal_preview_generation_workflow as workflow

CLASS_ID = "class_2026"
DERIVATION_ID = "gsd_" + "a" * 64
DERIVATION_SHA256 = "b" * 64
PREVIEW_ID = "gsp_" + "c" * 64
PREVIEW_SHA256 = "d" * 64


def _reference() -> object:
    return SimpleNamespace(
        class_id=CLASS_ID,
        derivation_id=DERIVATION_ID,
        derivation_sha256=DERIVATION_SHA256,
    )


def _generation_result(
    *,
    derivation_reference: object | None = None,
    currentness: str = "current",
    reasons: tuple[str, ...] = (),
    diagnostics: tuple[object, ...] = (),
) -> object:
    reference = derivation_reference or _reference()
    snapshot = SimpleNamespace(
        derivation_reference=reference,
        preview_id=PREVIEW_ID,
        preview_fingerprint="e" * 64,
        currentness=SimpleNamespace(
            state=currentness,
            reason_codes=reasons,
        ),
        diagnostics=diagnostics,
        coverage=SimpleNamespace(
            roster_student_count=24,
            contributing_student_count=21,
            noncontributing_student_count=3,
        ),
    )
    stored = SimpleNamespace(
        snapshot=snapshot,
        preview_sha256=PREVIEW_SHA256,
        reference=SimpleNamespace(
            class_id=CLASS_ID,
            preview_id=PREVIEW_ID,
            preview_sha256=PREVIEW_SHA256,
        ),
    )
    return SimpleNamespace(
        stored=stored,
        write_disposition="created",
    )


def _install_types(monkeypatch: pytest.MonkeyPatch) -> object:
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

    monkeypatch.setattr(
        workflow,
        "GroupingSignalDerivationReference",
        FakeReference,
    )
    monkeypatch.setattr(
        workflow,
        "GroupingSignalPreviewGenerationResult",
        SimpleNamespace,
    )
    return FakeReference(
        class_id=CLASS_ID,
        derivation_id=DERIVATION_ID,
        derivation_sha256=DERIVATION_SHA256,
    )


def test_generation_uses_exact_derivation_reference_and_wraps_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact = _install_types(monkeypatch)
    canonical = _generation_result(derivation_reference=exact)
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def generate(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return canonical

    monkeypatch.setattr(
        workflow,
        "generate_grouping_signal_preview",
        generate,
    )

    result = workflow.generate_planning_signal_preview(
        "workspace",
        CLASS_ID,
        DERIVATION_ID,
        DERIVATION_SHA256,
    )

    assert observed == [(("workspace", exact), {})]
    assert result.derivation_reference == exact
    assert result.generation_result is canonical
    assert result.write_disposition == "created"
    assert result.preview_id == PREVIEW_ID
    assert result.preview_sha256 == PREVIEW_SHA256
    assert result.preview_fingerprint == "e" * 64
    assert result.currentness_state == "current"
    assert result.currentness_reason_codes == ()
    assert result.roster_student_count == 24
    assert result.contributing_student_count == 21
    assert result.noncontributing_student_count == 3
    assert result.review_write_action == "not_performed"
    assert result.review_selection_action == "not_performed"
    assert result.core_export_action == "not_performed"
    assert result.csv_export_action == "not_performed"


def test_warning_and_blocking_diagnostics_are_preserved_not_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact = _install_types(monkeypatch)
    diagnostics = (
        SimpleNamespace(
            diagnostic_id="gpd_" + "1" * 64,
            severity="warning",
        ),
        SimpleNamespace(
            diagnostic_id="gpd_" + "2" * 64,
            severity="blocking",
        ),
    )
    canonical = _generation_result(
        derivation_reference=exact,
        currentness="stale",
        reasons=("derivation_not_current",),
        diagnostics=diagnostics,
    )
    monkeypatch.setattr(
        workflow,
        "generate_grouping_signal_preview",
        lambda *args, **kwargs: canonical,
    )

    result = workflow.generate_planning_signal_preview(
        "workspace",
        CLASS_ID,
        DERIVATION_ID,
        DERIVATION_SHA256,
    )

    assert result.currentness_state == "stale"
    assert result.currentness_reason_codes == ("derivation_not_current",)
    assert result.diagnostic_count == 2
    assert result.warning_diagnostic_ids == ("gpd_" + "1" * 64,)
    assert result.blocking_diagnostic_ids == ("gpd_" + "2" * 64,)


def test_persisted_preview_must_bind_exact_requested_derivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_types(monkeypatch)
    wrong = workflow.GroupingSignalDerivationReference(
        class_id=CLASS_ID,
        derivation_id="gsd_" + "f" * 64,
        derivation_sha256="0" * 64,
    )
    monkeypatch.setattr(
        workflow,
        "generate_grouping_signal_preview",
        lambda *args, **kwargs: _generation_result(
            derivation_reference=wrong
        ),
    )

    with pytest.raises(
        workflow.PlanningSignalPreviewGenerationError,
        match="does not bind",
    ):
        workflow.generate_planning_signal_preview(
            "workspace",
            CLASS_ID,
            DERIVATION_ID,
            DERIVATION_SHA256,
        )


def test_canonical_generation_failure_is_translated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_types(monkeypatch)
    monkeypatch.setattr(
        workflow,
        "generate_grouping_signal_preview",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            workflow.GroupingSignalPreviewGenerationError(
                "preview dependencies unavailable"
            )
        ),
    )

    with pytest.raises(
        workflow.PlanningSignalPreviewGenerationDependencyError,
        match="preview dependencies unavailable",
    ):
        workflow.generate_planning_signal_preview(
            "workspace",
            CLASS_ID,
            DERIVATION_ID,
            DERIVATION_SHA256,
        )
