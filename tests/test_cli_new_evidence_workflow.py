from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.cli as cli
from meridian.new_evidence_workflow import NewEvidenceReview

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
PUBLICATION_ID = "pub_" + "1" * 32
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
WORK = ModuleWorkRef(module_id="scoreform", class_id=CLASS_ID, work_id="test_1")


def _authorized_stub() -> object:
    return SimpleNamespace(
        stored=SimpleNamespace(
            snapshot=SimpleNamespace(
                source=SimpleNamespace(
                    publication=SimpleNamespace(work=WORK),
                )
            )
        )
    )


def _review() -> NewEvidenceReview:
    return NewEvidenceReview(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=WORK,
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
        projection_source_status="current",
        membership_state="no_decision",
        membership_revision=None,
        academic_period_id=None,
        academic_period_calendar_revision=None,
        rows=(),
        status_summary=(),
        attention_count=0,
    )


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "new-evidence",
        PUBLICATION_ID,
        CACHE_KEY,
        GRADE_ITEM_ID,
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        "--scope-student-id",
        "student_1",
        *extra,
    )


def test_workflow_help_exposes_new_evidence_task(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = capsys.readouterr().out
    assert "new-evidence" in output
    assert "Review one authorized evidence projection" in output


def test_new_evidence_cli_reuses_authorized_diagnostic_read(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _authorized_stub()
    observed: dict[str, object] = {}

    def fake_inspect(
        workspace_root: str,
        publication_id: str,
        cache_key: str,
        *,
        authorization_purpose_id: str,
        requested_student_ids: tuple[str, ...],
        filters: object,
        dependencies: object,
    ) -> object:
        observed.update(
            workspace_root=workspace_root,
            publication_id=publication_id,
            cache_key=cache_key,
            authorization_purpose_id=authorization_purpose_id,
            requested_student_ids=requested_student_ids,
            filters=filters,
            dependencies=dependencies,
        )
        return SimpleNamespace(authorized=authorized)

    def fake_project(
        workspace_root: str,
        class_id: str,
        grade_item_id: str,
        authorized_snapshot: object,
    ) -> NewEvidenceReview:
        assert workspace_root == "synthetic-workspace"
        assert class_id == CLASS_ID
        assert grade_item_id == GRADE_ITEM_ID
        assert authorized_snapshot is authorized
        return _review()

    monkeypatch.setattr(cli, "inspect_evidence_diagnostic", fake_inspect)
    monkeypatch.setattr(cli, "project_new_evidence_review", fake_project)
    dependencies = object()

    assert cli.main(_arguments(), dependencies=dependencies) == 0  # type: ignore[arg-type]
    output = capsys.readouterr().out

    assert observed["publication_id"] == PUBLICATION_ID
    assert observed["cache_key"] == CACHE_KEY
    assert observed["authorization_purpose_id"] == "teacher_review"
    assert observed["requested_student_ids"] == ("student_1",)
    assert observed["dependencies"] is dependencies
    assert "New Evidence review" in output
    assert f"Grade Item: {GRADE_ITEM_ID}" in output
    assert "membership: no_decision" in output
    assert "read-only; no Meridian or Core state was written" in output


def test_new_evidence_json_uses_projection_serializer(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _authorized_stub()
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: SimpleNamespace(authorized=authorized),
    )
    monkeypatch.setattr(cli, "project_new_evidence_review", lambda *args: _review())

    assert cli.main(_arguments("--format", "json"), dependencies=object()) == 0  # type: ignore[arg-type]
    payload = json.loads(capsys.readouterr().out)

    assert payload["class_id"] == CLASS_ID
    assert payload["grade_item_id"] == GRADE_ITEM_ID
    assert payload["publication_id"] == PUBLICATION_ID
    assert payload["cache_key"] == CACHE_KEY
    assert payload["snapshot_digest"] == SNAPSHOT_DIGEST
    assert payload["rows"] == []


def test_new_evidence_without_deployment_authorizer_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = list(_arguments())
    workspace_index = arguments.index("--workspace") + 1
    arguments[workspace_index] = str(tmp_path)

    assert cli.main(tuple(arguments)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "diagnostics.authorization_provider_required" in captured.err
    assert tuple(tmp_path.iterdir()) == ()
