from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.grade_report_attention as attention
from meridian.grade_preview_explanation import (
    GradePreviewSourceError,
    GradePreviewTarget,
)
from meridian.proficiency_attention import build_meridian_attention_summary

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")


def _target(family: str, student_id: str) -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=student_id,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family=family,  # type: ignore[arg-type]
    )


def _snapshot(*targets: GradePreviewTarget):
    return SimpleNamespace(
        build_request=SimpleNamespace(
            grade_requests=tuple(SimpleNamespace(target=target) for target in targets)
        )
    )


def test_refresh_helper_compares_only_neutrally_observable_standards_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conventional = _target("conventional", "student_001")
    standards = _target("standards_based", "student_002")
    hybrid = _target("hybrid", "student_003")
    seen: list[GradePreviewTarget] = []

    monkeypatch.setattr(
        attention,
        "reporting_snapshot_prior_grade_basis",
        lambda _snapshot, target: SimpleNamespace(observation=target),
    )

    def explain(_root, requests):
        assert len(requests) == 1
        seen.append(requests[0].target)
        return SimpleNamespace(
            rows=(
                SimpleNamespace(
                    target=requests[0].target,
                    observation=object(),
                ),
            )
        )

    monkeypatch.setattr(attention, "explain_grade_report_preview", explain)
    monkeypatch.setattr(
        attention,
        "compare_grade_preview_basis",
        lambda current, prior: SimpleNamespace(changed=True),
    )

    assert attention._selected_reporting_snapshot_needs_refresh(
        Path("."), _snapshot(conventional, standards, hybrid)  # type: ignore[arg-type]
    )
    assert seen == [standards]


def test_refresh_helper_does_not_invent_change_when_basis_is_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    standards = _target("standards_based", "student_001")
    monkeypatch.setattr(
        attention,
        "reporting_snapshot_prior_grade_basis",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        attention,
        "explain_grade_report_preview",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            GradePreviewSourceError("current basis unavailable")
        ),
    )

    assert not attention._selected_reporting_snapshot_needs_refresh(
        Path("."), _snapshot(standards)  # type: ignore[arg-type]
    )


def test_refresh_helper_treats_prior_and_current_unavailable_as_no_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    standards = _target("standards_based", "student_001")
    monkeypatch.setattr(
        attention,
        "reporting_snapshot_prior_grade_basis",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        attention,
        "explain_grade_report_preview",
        lambda _root, requests: SimpleNamespace(
            rows=(
                SimpleNamespace(target=requests[0].target, observation=None),
            )
        ),
    )

    def unexpected_compare(*_args, **_kwargs):
        raise AssertionError(
            "comparison is unnecessary when both sides are unavailable"
        )

    monkeypatch.setattr(attention, "compare_grade_preview_basis", unexpected_compare)

    assert not attention._selected_reporting_snapshot_needs_refresh(
        Path("."), _snapshot(standards)  # type: ignore[arg-type]
    )


def test_class_inspection_counts_one_refresh_per_selected_reporting_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    (root / "classes" / CLASS_ID).mkdir(parents=True)

    snapshot_reference = SimpleNamespace(snapshot_id="snapshot_current")
    selection_reference = object()
    snapshot = SimpleNamespace(
        definition_reference=SimpleNamespace(definition_id="quarter_grade_report"),
        target_period=PERIOD,
        calendar_revision=1,
        predecessor=None,
        provenance_bindings=(),
        build_request=SimpleNamespace(grade_requests=()),
    )
    stored = SimpleNamespace(snapshot=snapshot, reference=snapshot_reference)
    selection = SimpleNamespace(
        selection=SimpleNamespace(snapshot_reference=snapshot_reference),
        reference=selection_reference,
    )

    monkeypatch.setattr(
        attention,
        "_discover_current_standards_grade_results",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        attention,
        "list_reporting_snapshot_ids",
        lambda *_args, **_kwargs: ("snapshot_current",),
    )
    monkeypatch.setattr(
        attention,
        "load_reporting_snapshot",
        lambda *_args, **_kwargs: stored,
    )
    monkeypatch.setattr(
        attention,
        "load_current_reporting_snapshot_selection",
        lambda *_args, **_kwargs: selection,
    )
    monkeypatch.setattr(
        attention,
        "_selected_reporting_snapshot_needs_refresh",
        lambda *_args, **_kwargs: True,
    )

    summary = attention.inspect_grade_report_attention_for_class(root, CLASS_ID)

    assert tuple((item.code, item.count) for item in summary.items) == (
        ("meridian_reporting_snapshot_refresh_needed", 1),
    )


def test_unselected_snapshot_scope_is_not_refresh_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    (root / "classes" / CLASS_ID).mkdir(parents=True)
    snapshot = SimpleNamespace(
        definition_reference=SimpleNamespace(definition_id="quarter_grade_report"),
        target_period=PERIOD,
        calendar_revision=1,
        predecessor=None,
        build_request=SimpleNamespace(grade_requests=()),
    )
    stored = SimpleNamespace(snapshot=snapshot, reference=object())

    monkeypatch.setattr(
        attention,
        "_discover_current_standards_grade_results",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        attention,
        "list_reporting_snapshot_ids",
        lambda *_args, **_kwargs: ("snapshot_historical",),
    )
    monkeypatch.setattr(
        attention,
        "load_reporting_snapshot",
        lambda *_args, **_kwargs: stored,
    )
    monkeypatch.setattr(
        attention,
        "load_current_reporting_snapshot_selection",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        attention,
        "_selected_reporting_snapshot_needs_refresh",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unselected historical snapshot must not be compared")
        ),
    )

    summary = attention.inspect_grade_report_attention_for_class(root, CLASS_ID)

    assert summary == build_meridian_attention_summary(())
