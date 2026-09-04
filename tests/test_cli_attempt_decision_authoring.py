from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
POLICY_ID = "explicit_one"
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "attempt-decision-author",
        PUBLICATION_ID,
        CACHE_KEY,
        GRADE_ITEM_ID,
        STUDENT_ID,
        POLICY_ID,
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        "--actor-id",
        "teacher_local",
        "--decided-at",
        "2026-09-02T15:00:00+00:00",
        *extra,
    )


def _work() -> object:
    return SimpleNamespace(
        module_id="scoreform",
        class_id=CLASS_ID,
        work_id="test_1",
    )


def _authorized() -> object:
    publication = SimpleNamespace(
        work=_work(),
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


def _attempt(
    *,
    sequence: int | None,
    identifier: str | None,
    target_id: str,
) -> object:
    return SimpleNamespace(
        native=SimpleNamespace(
            sequence=sequence,
            identifier=identifier,
        ),
        target=SimpleNamespace(
            target_kind="attempt",
            target_id=target_id,
            owning_system="scoreform",
            contract_version="v1",
        ),
    )


def _derivation() -> object:
    return SimpleNamespace(
        status="applicable",
        candidates=(
            SimpleNamespace(
                attempt=_attempt(
                    sequence=1,
                    identifier="first",
                    target_id="attempt_1",
                ),
                eligible_evidence=(object(),),
            ),
            SimpleNamespace(
                attempt=_attempt(
                    sequence=2,
                    identifier="second",
                    target_id="attempt_2",
                ),
                eligible_evidence=(object(), object()),
            ),
        ),
    )


def _preview(selected_attempts: tuple[object, ...]) -> object:
    candidate = SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=_work(),
        student_id=STUDENT_ID,
        policy=SimpleNamespace(
            policy_id=POLICY_ID,
            policy_revision=2,
            policy_revision_sha256="a" * 64,
        ),
        source_snapshot=SimpleNamespace(
            publication_id=PUBLICATION_ID,
            cache_key=CACHE_KEY,
            snapshot_digest=SNAPSHOT_DIGEST,
        ),
        candidates=_derivation().candidates,
        selected_attempts=selected_attempts,
        decision_revision=1,
        supersedes_revision=None,
        membership_revision=3,
        membership_revision_sha256="b" * 64,
        actor=SimpleNamespace(kind="teacher", actor_id="teacher_local"),
        rationale=None,
        decided_at=datetime(2026, 9, 2, 15, 0, tzinfo=UTC),
    )
    return SimpleNamespace(
        candidate=candidate,
        history=(),
        latest_persisted_decision_sha256=None,
        reviewed_current_decision_revision=None,
        expected_membership_revision=3,
        expected_membership_sha256="b" * 64,
        expected_policy_revision=2,
        expected_policy_sha256="a" * 64,
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=candidate.work,
        student_id=STUDENT_ID,
        decision_revision=1,
        selected_count=len(selected_attempts),
        candidate_count=2,
    )


def _result() -> object:
    return SimpleNamespace(
        written_revision=1,
        write_disposition="created",
        selection_action="not_performed",
    )


def _install_authorization(monkeypatch: pytest.MonkeyPatch) -> object:
    authorized = _authorized()
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: SimpleNamespace(authorized=authorized),
    )
    return authorized


def test_workflow_help_exposes_attempt_decision_author_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "attempt-decision-author" in output
    assert "Preview or write one explicit student attempt decision" in output


def test_preview_resolves_native_selectors_and_does_not_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _install_authorization(monkeypatch)
    derivation = _derivation()
    monkeypatch.setattr(
        cli,
        "derive_attempt_candidates",
        lambda *args: derivation,
    )
    observed: dict[str, object] = {}

    def fake_preview(*args: object, **kwargs: object) -> object:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return _preview(kwargs["selected_attempts"])  # type: ignore[index]

    monkeypatch.setattr(cli, "preview_attempt_decision_authoring", fake_preview)
    monkeypatch.setattr(
        cli,
        "commit_attempt_decision_authoring_preview",
        lambda *args, **kwargs: pytest.fail("preview must not commit"),
    )

    assert cli.main(
        _arguments(
            "--select-identifier",
            "second",
            "--select-sequence",
            "1",
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    kwargs = observed["kwargs"]
    assert kwargs["authorized_snapshot"] is authorized  # type: ignore[index]
    assert kwargs["selected_attempts"] == (  # type: ignore[index]
        derivation.candidates[0].attempt,
        derivation.candidates[1].attempt,
    )
    assert "Attempt-decision authoring preview" in output
    assert "selected attempts: 2" in output
    assert "confirmation supplied: no" in output
    assert "NO DECISION WRITE PERFORMED" in output


def test_authorization_is_exactly_student_scoped(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _authorized()
    observed: dict[str, object] = {}

    def inspect(*args: object, **kwargs: object) -> object:
        observed["inspect"] = (args, kwargs)
        return SimpleNamespace(authorized=authorized)

    monkeypatch.setattr(cli, "inspect_evidence_diagnostic", inspect)
    monkeypatch.setattr(
        cli,
        "derive_attempt_candidates",
        lambda *args: _derivation(),
    )
    monkeypatch.setattr(
        cli,
        "preview_attempt_decision_authoring",
        lambda *args, **kwargs: _preview(()),
    )

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    capsys.readouterr()

    _, kwargs = observed["inspect"]
    assert kwargs["authorization_purpose_id"] == "teacher_review"  # type: ignore[index]
    assert kwargs["requested_student_ids"] == (STUDENT_ID,)  # type: ignore[index]


def test_duplicate_selectors_for_same_candidate_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_authorization(monkeypatch)
    monkeypatch.setattr(
        cli,
        "derive_attempt_candidates",
        lambda *args: _derivation(),
    )

    assert cli.main(
        _arguments(
            "--select-sequence",
            "1",
            "--select-identifier",
            "first",
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "decision_authoring_invalid" in captured.err
    assert captured.err == (
        "error: "
        "teacher_workflow.attempt_decisions.decision_authoring_invalid\n"
    )


def test_unmatched_selector_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_authorization(monkeypatch)
    monkeypatch.setattr(
        cli,
        "derive_attempt_candidates",
        lambda *args: _derivation(),
    )

    assert cli.main(
        _arguments("--select-sequence", "9"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "decision_authoring_invalid" in captured.err
    assert captured.err == (
        "error: "
        "teacher_workflow.attempt_decisions.decision_authoring_invalid\n"
    )


def test_confirm_write_commits_preview_but_does_not_select(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _install_authorization(monkeypatch)
    derivation = _derivation()
    monkeypatch.setattr(
        cli,
        "derive_attempt_candidates",
        lambda *args: derivation,
    )
    preview = _preview((derivation.candidates[0].attempt,))
    monkeypatch.setattr(
        cli,
        "preview_attempt_decision_authoring",
        lambda *args, **kwargs: preview,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_attempt_decision_authoring_preview",
        commit,
    )

    assert cli.main(
        _arguments("--select-sequence", "1", "--confirm-write"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert observed == [
        (
            ("synthetic-workspace", preview),
            {"authorized_snapshot": authorized},
        )
    ]
    assert "Decision write committed: revision 1" in output
    assert "current-decision selection: not performed" in output


def test_json_output_preserves_exact_selected_candidate_identity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_authorization(monkeypatch)
    derivation = _derivation()
    monkeypatch.setattr(
        cli,
        "derive_attempt_candidates",
        lambda *args: derivation,
    )
    monkeypatch.setattr(
        cli,
        "preview_attempt_decision_authoring",
        lambda *args, **kwargs: _preview(
            (derivation.candidates[1].attempt,)
        ),
    )

    assert cli.main(
        _arguments(
            "--select-identifier",
            "second",
            "--format",
            "json",
        ),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "preview"
    assert data["write_confirmed"] is False
    assert data["preview"]["selected_count"] == 1
    assert data["preview"]["candidates"][1]["native"] == {
        "identifier": "second",
        "sequence": 2,
    }
    assert data["preview"]["candidates"][1]["selected"] is True
    assert data["selection_action"] == "not_performed"
