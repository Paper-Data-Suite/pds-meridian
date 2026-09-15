from __future__ import annotations

from types import SimpleNamespace

import pytest

import meridian.academic_period_attention as attention_module
from meridian.academic_period_attention import (
    assess_selected_academic_period_proficiency_result_freshness,
)


def selected_result() -> SimpleNamespace:
    policy_reference = SimpleNamespace(policy_id="period_policy")
    scale_reference = SimpleNamespace(scale_id="teacher_scale")
    snapshot = SimpleNamespace(
        algorithm_version="1",
        class_id="synthetic_class_2026",
        student_id="s001",
        standard_id="STD.A",
        target_period=SimpleNamespace(
            period=SimpleNamespace(
                school_year="2026-2027",
                period_id="mp1",
            ),
            calendar_revision=1,
        ),
        policy_reference=policy_reference,
        target_scale=scale_reference,
        inputs=SimpleNamespace(entries=()),
    )
    return SimpleNamespace(
        snapshot=snapshot,
        result_sha256="a" * 64,
    )


def install_current_basis(
    monkeypatch: pytest.MonkeyPatch,
    stored: SimpleNamespace,
) -> None:
    snapshot = stored.snapshot
    monkeypatch.setattr(
        attention_module,
        "AcademicPeriodProficiencyResultSnapshot",
        SimpleNamespace,
    )
    monkeypatch.setattr(
        attention_module,
        "load_current_academic_period_proficiency_result",
        lambda *_args: stored,
    )
    monkeypatch.setattr(
        attention_module,
        "get_current_academic_period_calendar_revision",
        lambda *_args: 1,
    )
    monkeypatch.setattr(
        attention_module,
        "load_current_academic_period_proficiency_policy",
        lambda *_args: SimpleNamespace(reference=snapshot.policy_reference),
    )
    monkeypatch.setattr(
        attention_module,
        "load_current_proficiency_scale",
        lambda *_args: SimpleNamespace(reference=snapshot.target_scale),
    )


def test_selected_result_freshness_reports_current_exact_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = selected_result()
    install_current_basis(monkeypatch, stored)

    freshness = assess_selected_academic_period_proficiency_result_freshness(
        ".",
        stored,  # type: ignore[arg-type]
    )

    assert freshness.status == "current"
    assert freshness.reasons == ()


def test_selected_pointer_change_is_inputs_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = selected_result()
    install_current_basis(monkeypatch, stored)
    monkeypatch.setattr(
        attention_module,
        "load_current_academic_period_proficiency_result",
        lambda *_args: SimpleNamespace(
            snapshot=stored.snapshot,
            result_sha256="b" * 64,
        ),
    )

    freshness = assess_selected_academic_period_proficiency_result_freshness(
        ".",
        stored,  # type: ignore[arg-type]
    )

    assert freshness.status == "stale"
    assert freshness.reasons == ("inputs_changed",)


def test_freshness_reasons_use_canonical_deterministic_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = selected_result()
    install_current_basis(monkeypatch, stored)
    stored.snapshot.algorithm_version = "old"
    monkeypatch.setattr(
        attention_module,
        "load_current_academic_period_proficiency_result",
        lambda *_args: SimpleNamespace(
            snapshot=stored.snapshot,
            result_sha256="b" * 64,
        ),
    )
    monkeypatch.setattr(
        attention_module,
        "get_current_academic_period_calendar_revision",
        lambda *_args: 2,
    )
    monkeypatch.setattr(
        attention_module,
        "load_current_academic_period_proficiency_policy",
        lambda *_args: SimpleNamespace(reference=object()),
    )
    monkeypatch.setattr(
        attention_module,
        "load_current_proficiency_scale",
        lambda *_args: SimpleNamespace(reference=object()),
    )

    freshness = assess_selected_academic_period_proficiency_result_freshness(
        ".",
        stored,  # type: ignore[arg-type]
    )

    assert freshness.status == "stale"
    assert freshness.reasons == (
        "inputs_changed",
        "policy_changed",
        "scale_changed",
        "calendar_changed",
        "algorithm_changed",
    )
