from __future__ import annotations

import json
from pathlib import Path

import pytest

import meridian.cli as cli
from meridian.attention_service import (
    MeridianAttentionInspection,
    MeridianAttentionReadError,
)
from meridian.proficiency_attention import (
    MeridianAttentionItem,
    build_meridian_attention_summary,
)


def _inspection(
    items: tuple[MeridianAttentionItem, ...],
    *,
    evaluated_class_count: int = 1,
    failed_scope_count: int = 0,
) -> MeridianAttentionInspection:
    return MeridianAttentionInspection(
        summary=build_meridian_attention_summary(items),
        partial=failed_scope_count > 0,
        evaluated_class_count=evaluated_class_count,
        failed_scope_count=failed_scope_count,
    )


def test_attention_parser_accepts_scope_and_format_flags(tmp_path: Path) -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        (
            "attention",
            "--workspace",
            str(tmp_path.resolve()),
            "--school-year",
            "2026-2027",
            "--class-id",
            "class-a",
            "--format",
            "json",
        )
    )

    assert args.command_group == "attention"
    assert args.workspace == tmp_path.resolve()
    assert args.school_year == "2026-2027"
    assert args.class_id == "class-a"
    assert args.format == "json"
    assert args.handler is cli._handle_attention


def test_attention_json_is_deterministic_and_forwards_exact_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = _inspection(
        (
            MeridianAttentionItem(
                "meridian_planning_review_pending",
                1,
                "class-a",
            ),
            MeridianAttentionItem(
                "meridian_academic_period_calculation_stale",
                2,
                "class-a",
            ),
        )
    )
    captured: dict[str, object] = {}

    def fake_inspect(
        workspace_root: str | Path,
        *,
        class_id: str | None = None,
        active_school_year: str | None = None,
    ) -> MeridianAttentionInspection:
        captured["workspace_root"] = workspace_root
        captured["class_id"] = class_id
        captured["active_school_year"] = active_school_year
        return expected

    monkeypatch.setattr(cli, "inspect_meridian_attention", fake_inspect)

    status = cli.main(
        (
            "attention",
            "--workspace",
            str(tmp_path.resolve()),
            "--school-year",
            "2026-2027",
            "--class-id",
            "class-a",
            "--format",
            "json",
        )
    )
    assert status == 0
    assert captured == {
        "workspace_root": tmp_path.resolve(),
        "class_id": "class-a",
        "active_school_year": "2026-2027",
    }

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "coverage": {
            "evaluated_class_count": 1,
            "failed_scope_count": 0,
            "partial": False,
        },
        "evaluation": "evaluated",
        "items": [
            {
                "action_id": "open_calculation_preview",
                "class_id": "class-a",
                "code": "meridian_academic_period_calculation_stale",
                "count": 2,
                "count_unit": "academic_period_proficiency_targets",
                "label": "Academic Period proficiency calculations are stale",
                "task_id": "calculation-preview",
            },
            {
                "action_id": "open_create_planning_signal",
                "class_id": "class-a",
                "code": "meridian_planning_review_pending",
                "count": 1,
                "count_unit": "planning_review_scopes",
                "label": "Planning previews are awaiting teacher review",
                "task_id": "create-planning-signal",
            },
        ],
        "schema_version": 1,
        "scope": {
            "active_school_year": "2026-2027",
            "class_id": "class-a",
        },
    }


def test_attention_text_uses_canonical_order_not_count_priority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = _inspection(
        (
            MeridianAttentionItem(
                "meridian_planning_review_pending",
                50,
                "class-a",
            ),
            MeridianAttentionItem(
                "meridian_academic_period_calculation_stale",
                1,
                "class-a",
            ),
        )
    )
    monkeypatch.setattr(
        cli,
        "inspect_meridian_attention",
        lambda *args, **kwargs: expected,
    )

    status = cli.main(
        (
            "attention",
            "--workspace",
            str(tmp_path.resolve()),
            "--class-id",
            "class-a",
        )
    )
    assert status == 0
    output = capsys.readouterr().out
    assert output.startswith(
        "Meridian attention\n"
        "scope: class-a\n"
        "school_year: all\n"
        "coverage: 1 class(es) evaluated; 0 failed scope(s)\n"
        "partial: no\n"
        "items:\n"
    )
    academic = output.index(
        "meridian_academic_period_calculation_stale"
    )
    planning = output.index("meridian_planning_review_pending")
    assert academic < planning
    assert "count=1 academic_period_proficiency_targets" in output
    assert "count=50 planning_review_scopes" in output


def test_attention_partial_json_exposes_only_bounded_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = _inspection(
        (
            MeridianAttentionItem(
                "meridian_planning_review_pending",
                3,
                None,
            ),
        ),
        evaluated_class_count=2,
        failed_scope_count=1,
    )
    monkeypatch.setattr(
        cli,
        "inspect_meridian_attention",
        lambda *args, **kwargs: expected,
    )

    status = cli.main(
        (
            "attention",
            "--workspace",
            str(tmp_path.resolve()),
            "--format",
            "json",
        )
    )
    assert status == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["coverage"] == {
        "evaluated_class_count": 2,
        "failed_scope_count": 1,
        "partial": True,
    }
    assert payload["items"][0]["class_id"] is None
    for forbidden in (
        "student_id",
        "student_name",
        "score",
        "percentage",
        "proficiency_level",
        "grouping_band",
        "digest",
        "failed_class",
    ):
        assert forbidden not in output


def test_attention_unreadable_scope_returns_safe_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise MeridianAttentionReadError(
            "student-a private internal dependency detail"
        )

    monkeypatch.setattr(cli, "inspect_meridian_attention", fail)

    status = cli.main(
        (
            "attention",
            "--workspace",
            str(tmp_path.resolve()),
        )
    )
    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert (
        captured.err
        == "Meridian attention scope could not be inspected safely.\n"
    )
    assert "student-a" not in captured.err
    assert "private internal" not in captured.err


def test_attention_empty_workspace_is_successful_and_read_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = tuple(
        sorted(
            path.relative_to(tmp_path).as_posix()
            for path in tmp_path.rglob("*")
        )
    )

    status = cli.main(
        (
            "attention",
            "--workspace",
            str(tmp_path.resolve()),
            "--format",
            "json",
        )
    )
    assert status == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "coverage": {
            "evaluated_class_count": 0,
            "failed_scope_count": 0,
            "partial": False,
        },
        "evaluation": "evaluated",
        "items": [],
        "schema_version": 1,
        "scope": {
            "active_school_year": None,
            "class_id": None,
        },
    }

    after = tuple(
        sorted(
            path.relative_to(tmp_path).as_posix()
            for path in tmp_path.rglob("*")
        )
    )
    assert after == before
