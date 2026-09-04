from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

import meridian.cli as cli
from meridian.grade_item_authoring_workflow import (
    GradeItemAuthoringPreview,
    GradeItemAuthoringResult,
)
from meridian.grade_items import (
    GRADE_ITEM_RECORD_TYPE,
    GRADE_ITEM_SCHEMA_VERSION,
    GradeItemRevision,
    grade_item_revision_to_json_bytes,
)

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
CREATED = datetime(2026, 8, 25, 18, tzinfo=UTC)


def _revision(
    number: int,
    *,
    title: str = "Unit 1",
    purpose: str = "standards_proficiency",
    status: str = "active",
) -> GradeItemRevision:
    return GradeItemRevision(
        schema_version=GRADE_ITEM_SCHEMA_VERSION,
        record_type=GRADE_ITEM_RECORD_TYPE,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        grade_item_revision=number,
        supersedes_revision=None if number == 1 else number - 1,
        title=title,
        purpose=purpose,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        weighting=None,
        created_at=CREATED,
        revised_at=CREATED + timedelta(hours=number - 1),
    )


def _preview(
    *,
    operation: str = "create",
    revision: GradeItemRevision | None = None,
) -> GradeItemAuthoringPreview:
    candidate = revision or _revision(1)
    history_before = tuple(range(1, candidate.grade_item_revision))
    digest = hashlib.sha256(
        grade_item_revision_to_json_bytes(candidate)
    ).hexdigest()
    return GradeItemAuthoringPreview(
        actor_id="teacher_local",
        operation=operation,  # type: ignore[arg-type]
        history_before=history_before,
        latest_revision_sha256_before=(
            None if not history_before else "a" * 64
        ),
        candidate=candidate,
        candidate_sha256=digest,
    )


def _base_arguments(operation: str, *extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "grade-items-author",
        CLASS_ID,
        GRADE_ITEM_ID,
        "--workspace",
        "synthetic-workspace",
        "--operation",
        operation,
        "--actor-id",
        "teacher_local",
        "--revised-at",
        "2026-08-25T18:00:00Z",
        *extra,
    )


def test_workflow_help_exposes_grade_item_authoring(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "grade-items-author" in output
    assert "Preview or write one immutable Grade Item revision" in output


def test_preview_is_write_free_and_forwards_weighting_metadata(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}
    preview = _preview()

    def fake_preview(*args: object, **kwargs: object) -> GradeItemAuthoringPreview:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return preview

    monkeypatch.setattr(cli, "preview_grade_item_authoring", fake_preview)
    monkeypatch.setattr(
        cli,
        "commit_grade_item_authoring_preview",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("preview without confirmation must not write")
        ),
    )

    assert cli.main(
        _base_arguments(
            "create",
            "--title",
            "Unit 1",
            "--purpose",
            "standards_proficiency",
            "--weighting-category-id",
            "summative",
            "--relative-weight",
            "2.5",
            "--format",
            "json",
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0

    kwargs = observed["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["operation"] == "create"
    assert kwargs["actor_id"] == "teacher_local"
    weighting = kwargs["weighting"]
    assert weighting is not None
    assert weighting.category_id == "summative"  # type: ignore[union-attr]
    assert weighting.relative_weight == Decimal("2.5")  # type: ignore[union-attr]

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "preview"
    assert payload["write_confirmed"] is False
    assert payload["selection_action"] == "not_performed"
    assert payload["preview"]["candidate"]["grade_item_revision"] == 1


def test_confirm_write_reports_written_revision_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate = _revision(2, title="Revised", purpose="reporting_only")
    preview = _preview(operation="revise", revision=candidate)
    result = GradeItemAuthoringResult(
        preview=preview,
        write_disposition="created",
        stored_revision_sha256=preview.candidate_sha256,
        selected_revision_after=1,
    )
    monkeypatch.setattr(
        cli,
        "preview_grade_item_authoring",
        lambda *args, **kwargs: preview,
    )
    observed: list[tuple[object, ...]] = []

    def fake_commit(*args: object) -> GradeItemAuthoringResult:
        observed.append(args)
        return result

    monkeypatch.setattr(cli, "commit_grade_item_authoring_preview", fake_commit)

    assert cli.main(
        _base_arguments(
            "revise",
            "--title",
            "Revised",
            "--purpose",
            "reporting_only",
            "--confirm-write",
            "--format",
            "json",
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0

    assert observed == [("synthetic-workspace", preview)]
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "written"
    assert payload["write_confirmed"] is True
    assert payload["result"]["write_disposition"] == "created"
    assert payload["result"]["written_revision"] == 2
    assert payload["result"]["selected_revision_after"] == 1
    assert payload["result"]["selection_action"] == "not_performed"


def test_archive_does_not_invent_configuration_changes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}
    preview = _preview(operation="archive", revision=_revision(2, status="archived"))

    def fake_preview(*args: object, **kwargs: object) -> GradeItemAuthoringPreview:
        observed.update(kwargs)
        return preview

    monkeypatch.setattr(cli, "preview_grade_item_authoring", fake_preview)

    assert cli.main(
        _base_arguments("archive", "--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    capsys.readouterr()

    assert observed["title"] is None
    assert observed["purpose"] is None
    assert observed["weighting"] is None

def test_invalid_weighting_is_reported_as_workflow_scope_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(
        _base_arguments(
            "create",
            "--title",
            "Unit 1",
            "--purpose",
            "standards_proficiency",
            "--relative-weight",
            "0",
        )
    ) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "teacher_workflow.grade_items.authoring_scope_invalid" in captured.err

def test_revise_omitted_weighting_uses_preserve_action(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}
    preview = _preview(operation="revise", revision=_revision(2))

    def fake_preview(*args: object, **kwargs: object) -> GradeItemAuthoringPreview:
        observed.update(kwargs)
        return preview

    monkeypatch.setattr(cli, "preview_grade_item_authoring", fake_preview)

    assert cli.main(
        _base_arguments(
            "revise",
            "--title",
            "Revised",
            "--purpose",
            "standards_proficiency",
            "--format",
            "json",
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    capsys.readouterr()

    assert observed["weighting"] is None
    assert observed["weighting_action"] == "preserve"


def test_clear_weighting_is_explicit_and_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}
    preview = _preview(operation="revise", revision=_revision(2))

    def fake_preview(*args: object, **kwargs: object) -> GradeItemAuthoringPreview:
        observed.update(kwargs)
        return preview

    monkeypatch.setattr(cli, "preview_grade_item_authoring", fake_preview)

    assert cli.main(
        _base_arguments(
            "revise",
            "--title",
            "Revised",
            "--purpose",
            "standards_proficiency",
            "--clear-weighting",
            "--format",
            "json",
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    capsys.readouterr()
    assert observed["weighting"] is None
    assert observed["weighting_action"] == "clear"

    assert cli.main(
        _base_arguments(
            "revise",
            "--title",
            "Revised",
            "--purpose",
            "standards_proficiency",
            "--clear-weighting",
            "--relative-weight",
            "2",
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "teacher_workflow.grade_items.authoring_scope_invalid" in captured.err


def test_weighting_replacement_uses_replace_action(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}
    preview = _preview(operation="revise", revision=_revision(2))

    def fake_preview(*args: object, **kwargs: object) -> GradeItemAuthoringPreview:
        observed.update(kwargs)
        return preview

    monkeypatch.setattr(cli, "preview_grade_item_authoring", fake_preview)

    assert cli.main(
        _base_arguments(
            "revise",
            "--title",
            "Revised",
            "--purpose",
            "standards_proficiency",
            "--weighting-category-id",
            "summative",
            "--relative-weight",
            "3",
            "--format",
            "json",
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    capsys.readouterr()

    assert observed["weighting_action"] == "replace"
    assert observed["weighting"] is not None
