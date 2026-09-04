from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.cli as cli
from meridian.new_evidence_eligibility_selection_workflow import (
    NewEvidenceEligibilitySelectionStaleError,
)
from meridian.new_evidence_workflow import NewEvidenceReview

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
ITEM_ID = "scoreform_item_1"
PUBLICATION_ID = "pub_" + "1" * 32
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
TARGET_DIGEST = "4" * 64
MEMBERSHIP_DIGEST = "5" * 64
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
        membership_state="included",
        membership_revision=3,
        academic_period_id="mp1",
        academic_period_calendar_revision=4,
        rows=(),
        status_summary=(),
        attention_count=0,
    )


def _target_stub() -> object:
    return SimpleNamespace(
        decision=SimpleNamespace(
            class_id=CLASS_ID,
            grade_item_id=GRADE_ITEM_ID,
            source=SimpleNamespace(
                item_id=ITEM_ID,
                publication_id=PUBLICATION_ID,
                cache_key=CACHE_KEY,
                snapshot_digest=SNAPSHOT_DIGEST,
                work=WORK,
            ),
            eligibility_revision=1,
            disposition="included",
        ),
        decision_sha256=TARGET_DIGEST,
    )


def _preview_stub() -> object:
    return SimpleNamespace(
        target=_target_stub(),
        target_revision=1,
        target_disposition="included",
        expected_current_revision=2,
        membership_revision=3,
        membership_revision_sha256=MEMBERSHIP_DIGEST,
        source_state=SimpleNamespace(state="current"),
    )


def _result_stub() -> object:
    return SimpleNamespace(
        previous_current_revision=2,
        selected_revision=1,
        selected_disposition="included",
        selection_disposition="updated",
    )


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "new-evidence-select",
        PUBLICATION_ID,
        CACHE_KEY,
        GRADE_ITEM_ID,
        ITEM_ID,
        "1",
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        "--scope-student-id",
        "student_1",
        *extra,
    )


def _install_read_path(monkeypatch: pytest.MonkeyPatch) -> object:
    authorized = _authorized_stub()
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: SimpleNamespace(authorized=authorized),
    )
    monkeypatch.setattr(cli, "project_new_evidence_review", lambda *args: _review())
    return authorized


def test_workflow_help_exposes_explicit_selection_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = capsys.readouterr().out
    assert "new-evidence-select" in output
    assert "Preview or select one persisted eligibility revision" in output


def test_without_confirmation_previews_and_performs_no_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _install_read_path(monkeypatch)
    preview = _preview_stub()
    observed: dict[str, object] = {}

    def fake_preview(*args: object, **kwargs: object) -> object:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return preview

    def unexpected(*args: object, **kwargs: object) -> object:
        raise AssertionError("unconfirmed CLI action must not select eligibility")

    monkeypatch.setattr(cli, "preview_new_evidence_eligibility_selection", fake_preview)
    monkeypatch.setattr(
        cli,
        "commit_new_evidence_eligibility_selection_preview",
        unexpected,
    )

    assert cli.main(_arguments(), dependencies=object()) == 0  # type: ignore[arg-type]
    output = capsys.readouterr().out

    assert observed["args"] == ("synthetic-workspace", _review(), authorized)
    assert observed["kwargs"] == {  # type: ignore[comparison-overlap]
        "item_id": ITEM_ID,
        "eligibility_revision": 1,
    }
    assert "Eligibility current-selection preview" in output
    assert "target revision: 1" in output
    assert "currently selected revision: 2" in output
    assert "confirmation supplied: no" in output
    assert "NO SELECTION PERFORMED" in output


def test_confirm_select_commits_exact_preview_without_authoring(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _install_read_path(monkeypatch)
    preview = _preview_stub()
    result = _result_stub()
    monkeypatch.setattr(
        cli,
        "preview_new_evidence_eligibility_selection",
        lambda *args, **kwargs: preview,
    )
    observed: dict[str, object] = {}

    def fake_commit(*args: object) -> object:
        observed["args"] = args
        return result

    monkeypatch.setattr(
        cli,
        "commit_new_evidence_eligibility_selection_preview",
        fake_commit,
    )

    assert cli.main(
        _arguments("--confirm-select"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert observed["args"] == ("synthetic-workspace", preview, authorized)
    assert "confirmation supplied: yes" in output
    assert "Selection committed: eligibility revision 1" in output
    assert "previous current revision: 2" in output
    assert "selected disposition: included" in output
    assert "authoring action: not performed" in output


def test_json_confirmation_reports_exact_selection_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_read_path(monkeypatch)
    monkeypatch.setattr(
        cli,
        "preview_new_evidence_eligibility_selection",
        lambda *args, **kwargs: _preview_stub(),
    )
    monkeypatch.setattr(
        cli,
        "commit_new_evidence_eligibility_selection_preview",
        lambda *args: _result_stub(),
    )

    assert cli.main(
        _arguments("--confirm-select", "--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["mode"] == "selected"
    assert payload["selection_confirmed"] is True
    assert payload["preview"]["target_revision"] == 1
    assert payload["preview"]["target_revision_sha256"] == TARGET_DIGEST
    assert payload["preview"]["expected_current_revision"] == 2
    assert payload["result"]["selection_disposition"] == "updated"
    assert payload["result"]["previous_current_revision"] == 2
    assert payload["result"]["selected_revision"] == 1
    assert payload["result"]["selected_disposition"] == "included"
    assert payload["result"]["authoring_action"] == "not_performed"


def test_stale_selection_preview_is_reported_as_workflow_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_read_path(monkeypatch)
    monkeypatch.setattr(
        cli,
        "preview_new_evidence_eligibility_selection",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            NewEvidenceEligibilitySelectionStaleError("review changed")
        ),
    )

    assert cli.main(_arguments(), dependencies=object()) == 1  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "teacher_workflow.new_evidence.eligibility_selection_stale" in captured.err
