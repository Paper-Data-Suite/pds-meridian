from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.cli as cli
from meridian.new_evidence_eligibility_workflow import (
    NewEvidenceEligibilityAuthoringStaleError,
)
from meridian.new_evidence_workflow import NewEvidenceReview

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
ITEM_ID = "scoreform_item_1"
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
        membership_state="included",
        membership_revision=2,
        academic_period_id="mp1",
        academic_period_calendar_revision=3,
        rows=(),
        status_summary=(),
        attention_count=0,
    )


def _decision_stub() -> object:
    return SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        source=SimpleNamespace(
            item_id=ITEM_ID,
            publication_id=PUBLICATION_ID,
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
            work=WORK,
        ),
        membership_revision=2,
        eligibility_revision=3,
        supersedes_revision=2,
        disposition="excluded",
        actor=SimpleNamespace(kind="teacher", actor_id="teacher_42"),
        policy=SimpleNamespace(
            policy_id="teacher_local_eligibility",
            policy_version="2",
        ),
        reason_codes=("eligibility.not_for_grade_item",),
        rationale="Not part of this Grade Item.",
        source_state=SimpleNamespace(state="current"),
        decided_at=datetime(2026, 9, 1, 22, 0, tzinfo=UTC),
    )


def _preview_stub() -> object:
    return SimpleNamespace(
        decision=_decision_stub(),
        selected_revision=1,
        candidate_revision=3,
        candidate_disposition="excluded",
    )


def _result_stub(*, changed: bool = False) -> object:
    before = 1
    after = 2 if changed else 1
    return SimpleNamespace(
        write_result=SimpleNamespace(
            disposition="created",
            stored=SimpleNamespace(decision=_decision_stub()),
        ),
        selected_revision_before_write=before,
        selected_revision_after_write=after,
        written_revision=3,
        written_disposition="excluded",
        selection_changed_during_write=changed,
    )


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "new-evidence-author",
        PUBLICATION_ID,
        CACHE_KEY,
        GRADE_ITEM_ID,
        ITEM_ID,
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        "--scope-student-id",
        "student_1",
        "--disposition",
        "excluded",
        "--actor-id",
        "teacher_42",
        "--policy-id",
        "teacher_local_eligibility",
        "--policy-version",
        "2",
        "--reason-code",
        "eligibility.not_for_grade_item",
        "--rationale",
        "Not part of this Grade Item.",
        *extra,
    )


def _install_read_path(
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    authorized = _authorized_stub()
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: SimpleNamespace(authorized=authorized),
    )
    monkeypatch.setattr(cli, "project_new_evidence_review", lambda *args: _review())
    return authorized


def test_workflow_help_exposes_explicit_author_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = capsys.readouterr().out
    assert "new-evidence-author" in output
    assert "Preview or write one teacher eligibility revision" in output


def test_without_confirmation_previews_and_performs_no_write(
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
        raise AssertionError("unconfirmed CLI action must not commit eligibility")

    monkeypatch.setattr(cli, "preview_new_evidence_eligibility_revision", fake_preview)
    monkeypatch.setattr(cli, "commit_new_evidence_eligibility_preview", unexpected)

    assert cli.main(_arguments(), dependencies=object()) == 0  # type: ignore[arg-type]
    output = capsys.readouterr().out

    args = observed["args"]
    kwargs = observed["kwargs"]
    assert args == ("synthetic-workspace", _review(), authorized)
    assert kwargs["item_id"] == ITEM_ID  # type: ignore[index]
    assert kwargs["disposition"] == "excluded"  # type: ignore[index]
    assert kwargs["actor_id"] == "teacher_42"  # type: ignore[index]
    assert kwargs["policy_id"] == "teacher_local_eligibility"  # type: ignore[index]
    assert kwargs["policy_version"] == "2"  # type: ignore[index]
    assert kwargs["reason_codes"] == (  # type: ignore[index]
        "eligibility.not_for_grade_item",
    )
    assert "Eligibility revision preview" in output
    assert "revision: 3" in output
    assert "confirmation supplied: no" in output
    assert "NO WRITE PERFORMED" in output


def test_confirm_write_commits_the_exact_preview_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _install_read_path(monkeypatch)
    preview = _preview_stub()
    result = _result_stub()
    monkeypatch.setattr(
        cli,
        "preview_new_evidence_eligibility_revision",
        lambda *args, **kwargs: preview,
    )
    observed: dict[str, object] = {}

    def fake_commit(*args: object) -> object:
        observed["args"] = args
        return result

    monkeypatch.setattr(cli, "commit_new_evidence_eligibility_preview", fake_commit)

    assert cli.main(
        _arguments("--confirm-write"), dependencies=object()  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert observed["args"] == ("synthetic-workspace", preview, authorized)
    assert "confirmation supplied: yes" in output
    assert "Write committed: eligibility revision 3" in output
    assert "selected eligibility revision remains: 1" in output
    assert "selection action: not performed" in output


def test_json_confirmation_reports_preview_and_commit_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_read_path(monkeypatch)
    monkeypatch.setattr(
        cli,
        "preview_new_evidence_eligibility_revision",
        lambda *args, **kwargs: _preview_stub(),
    )
    monkeypatch.setattr(
        cli,
        "commit_new_evidence_eligibility_preview",
        lambda *args: _result_stub(changed=True),
    )

    assert cli.main(
        _arguments("--confirm-write", "--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["mode"] == "written"
    assert payload["write_confirmed"] is True
    assert payload["preview"]["eligibility_revision"] == 3
    assert payload["result"]["write_disposition"] == "created"
    assert payload["result"]["selected_revision_before_write"] == 1
    assert payload["result"]["selected_revision_after_write"] == 2
    assert payload["result"]["selection_changed_during_write"] is True
    assert payload["result"]["selection_action"] == "not_performed"


def test_stale_authoring_preview_is_reported_as_workflow_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_read_path(monkeypatch)
    monkeypatch.setattr(
        cli,
        "preview_new_evidence_eligibility_revision",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            NewEvidenceEligibilityAuthoringStaleError("review changed")
        ),
    )

    assert cli.main(_arguments(), dependencies=object()) == 1  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "teacher_workflow.new_evidence.eligibility_authoring_stale" in captured.err
