from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "attempt-decisions",
        PUBLICATION_ID,
        CACHE_KEY,
        GRADE_ITEM_ID,
        STUDENT_ID,
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        *extra,
    )


def _authorized() -> object:
    work = SimpleNamespace(
        module_id="scoreform",
        class_id=CLASS_ID,
        work_id="test_1",
    )
    publication = SimpleNamespace(
        work=work,
        publication_id=PUBLICATION_ID,
    )
    return SimpleNamespace(
        stored=SimpleNamespace(
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
            snapshot=SimpleNamespace(
                source=SimpleNamespace(publication=publication),
            ),
        )
    )


def _projection() -> object:
    work = SimpleNamespace(
        module_id="scoreform",
        class_id=CLASS_ID,
        work_id="test_1",
    )
    source_snapshot = SimpleNamespace(
        publication_id=PUBLICATION_ID,
        cache_key=CACHE_KEY,
        snapshot_digest=SNAPSHOT_DIGEST,
    )
    first_attempt = SimpleNamespace(
        target=SimpleNamespace(
            target_kind="attempt",
            target_id="attempt_1",
            owning_system="scoreform",
            contract_version="v1",
        ),
        native=SimpleNamespace(identifier=None, sequence=1),
    )
    second_attempt = SimpleNamespace(
        target=SimpleNamespace(
            target_kind="attempt",
            target_id="attempt_2",
            owning_system="scoreform",
            contract_version="v1",
        ),
        native=SimpleNamespace(identifier=None, sequence=2),
    )
    return SimpleNamespace(
        status="selected",
        resolution_status="selected",
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=work,
        student_id=STUDENT_ID,
        source_snapshot=source_snapshot,
        candidates=(
            SimpleNamespace(
                attempt=first_attempt,
                target_id="attempt_1",
                native_identifier=None,
                native_sequence=1,
                eligible_evidence_count=3,
                selected_in_reviewed_decision=False,
            ),
            SimpleNamespace(
                attempt=second_attempt,
                target_id="attempt_2",
                native_identifier=None,
                native_sequence=2,
                eligible_evidence_count=2,
                selected_in_reviewed_decision=True,
            ),
        ),
        reviewed_selected_attempts=(second_attempt,),
        selected_decision_revision=4,
        selected_decision_sha256="4" * 64,
        current_policy_id="explicit_one",
        current_policy_revision=2,
        current_policy_sha256="5" * 64,
        minimum_selected=1,
        maximum_selected=1,
        operative_selection=True,
        stale_reason=None,
        candidate_count=2,
        reviewed_selected_count=1,
    )


def test_workflow_help_exposes_read_only_attempt_decisions_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "attempt-decisions" in output
    assert "Review explicit attempt candidates and current selection" in output


def test_attempt_decisions_uses_exact_student_authorization_and_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _authorized()
    observed: dict[str, object] = {}

    def fake_inspect(
        workspace_root: str,
        publication_id: str,
        cache_key: str,
        **kwargs: object,
    ) -> object:
        observed["inspect"] = (
            workspace_root,
            publication_id,
            cache_key,
            kwargs,
        )
        return SimpleNamespace(authorized=authorized)

    def fake_project(
        workspace_root: str,
        class_id: str,
        grade_item_id: str,
        work: object,
        student_id: str,
        *,
        authorized_snapshot: object,
    ) -> object:
        observed["project"] = (
            workspace_root,
            class_id,
            grade_item_id,
            work,
            student_id,
            authorized_snapshot,
        )
        return _projection()

    monkeypatch.setattr(cli, "inspect_evidence_diagnostic", fake_inspect)
    monkeypatch.setattr(cli, "project_attempt_decisions", fake_project)

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    inspect_call = observed["inspect"]
    kwargs = inspect_call[3]  # type: ignore[index]
    assert inspect_call[:3] == (  # type: ignore[index]
        "synthetic-workspace",
        PUBLICATION_ID,
        CACHE_KEY,
    )
    assert kwargs["authorization_purpose_id"] == "teacher_review"
    assert kwargs["requested_student_ids"] == (STUDENT_ID,)

    project_call = observed["project"]
    assert project_call[0:3] == (  # type: ignore[index]
        "synthetic-workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
    )
    assert project_call[4] == STUDENT_ID  # type: ignore[index]
    assert project_call[5] is authorized  # type: ignore[index]

    assert "Attempt Decisions review" in output
    assert "status: selected" in output
    assert "candidate count: 2" in output
    assert "native_sequence | target | eligible_sources | reviewed_selected" in output
    assert "1 | attempt_1 | 3 | no" in output
    assert "2 | attempt_2 | 2 | yes" in output
    assert "read-only; no attempt-selection state was written" in output


def test_json_output_preserves_status_policy_and_attempt_identity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: SimpleNamespace(authorized=_authorized()),
    )
    monkeypatch.setattr(
        cli,
        "project_attempt_decisions",
        lambda *args, **kwargs: _projection(),
    )

    assert cli.main(
        _arguments("--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "selected"
    assert data["resolution_status"] == "selected"
    assert data["student_id"] == STUDENT_ID
    assert data["source_snapshot"]["publication_id"] == PUBLICATION_ID
    assert data["candidate_count"] == 2
    assert data["reviewed_selected_count"] == 1
    assert data["policy"] == {
        "policy_id": "explicit_one",
        "policy_revision": 2,
        "policy_sha256": "5" * 64,
        "minimum_selected": 1,
        "maximum_selected": 1,
    }
    assert data["candidates"][0]["native"] == {
        "identifier": None,
        "sequence": 1,
    }
    assert data["candidates"][1]["selected_in_reviewed_decision"] is True
    assert data["read_only"] is True


def test_stale_text_output_preserves_exact_reason(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    projection = _projection()
    projection.status = "stale"
    projection.resolution_status = "eligibility_stale"
    projection.operative_selection = False
    projection.stale_reason = "eligibility_stale"
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: SimpleNamespace(authorized=_authorized()),
    )
    monkeypatch.setattr(
        cli,
        "project_attempt_decisions",
        lambda *args, **kwargs: projection,
    )

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out
    assert "status: stale" in output
    assert "stale reason: eligibility_stale" in output
    assert "operative selection: no" in output
