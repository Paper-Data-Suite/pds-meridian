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
        "attempt-decision-select",
        PUBLICATION_ID,
        CACHE_KEY,
        GRADE_ITEM_ID,
        STUDENT_ID,
        "1",
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
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
    sequence: int,
    identifier: str,
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


def _preview() -> object:
    attempts = (
        _attempt(sequence=1, identifier="first", target_id="attempt_1"),
        _attempt(sequence=2, identifier="second", target_id="attempt_2"),
    )
    decision = SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=_work(),
        student_id=STUDENT_ID,
        decision_revision=1,
        supersedes_revision=None,
        policy=SimpleNamespace(
            policy_id="explicit_one",
            policy_revision=2,
            policy_revision_sha256="a" * 64,
        ),
        membership_revision=3,
        membership_revision_sha256="b" * 64,
        candidates=(
            SimpleNamespace(
                attempt=attempts[0],
                eligible_evidence=(object(),),
            ),
            SimpleNamespace(
                attempt=attempts[1],
                eligible_evidence=(object(), object()),
            ),
        ),
        selected_attempts=(attempts[1],),
    )
    target = SimpleNamespace(
        decision=decision,
        decision_sha256="c" * 64,
    )
    return SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        work=decision.work,
        student_id=STUDENT_ID,
        target=target,
        history=(1, 2),
        expected_current_decision_revision=2,
        target_revision=1,
        target_sha256="c" * 64,
        latest_revision=2,
        target_is_latest=False,
    )


def _result() -> object:
    return SimpleNamespace(
        selected_revision=1,
        selected_decision_sha256="c" * 64,
        selection_disposition="updated",
        previous_current_decision_revision=2,
        authoring_action="not_performed",
    )


def _install_authorization(monkeypatch: pytest.MonkeyPatch) -> object:
    authorized = _authorized()
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: SimpleNamespace(authorized=authorized),
    )
    return authorized


def test_workflow_help_exposes_attempt_decision_select_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "attempt-decision-select" in output
    assert "Preview or select one persisted student attempt decision" in output


def test_without_confirmation_previews_and_performs_no_selection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _install_authorization(monkeypatch)
    preview = _preview()
    observed: dict[str, object] = {}

    def fake_preview(*args: object, **kwargs: object) -> object:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return preview

    monkeypatch.setattr(cli, "preview_attempt_decision_selection", fake_preview)
    monkeypatch.setattr(
        cli,
        "commit_attempt_decision_selection_preview",
        lambda *args, **kwargs: pytest.fail(
            "unconfirmed decision selection must not commit"
        ),
    )

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    routed = observed["args"]
    assert routed[0:3] == (
        "synthetic-workspace",
        CLASS_ID,
        GRADE_ITEM_ID,
    )
    work = routed[3]
    assert work.module_id == "scoreform"
    assert work.class_id == CLASS_ID
    assert work.work_id == "test_1"
    assert routed[4:] == (STUDENT_ID, 1)
    assert observed["kwargs"] == {"authorized_snapshot": authorized}
    assert "Attempt-decision selection preview" in output
    assert "target decision revision: 1" in output
    assert "latest persisted decision revision: 2" in output
    assert "target is latest: no" in output
    assert "currently selected decision revision: 2" in output
    assert "confirmation supplied: no" in output
    assert "NO DECISION SELECTION PERFORMED" in output


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
        "preview_attempt_decision_selection",
        lambda *args, **kwargs: _preview(),
    )

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    capsys.readouterr()

    _, kwargs = observed["inspect"]
    assert kwargs["authorization_purpose_id"] == "teacher_review"  # type: ignore[index]
    assert kwargs["requested_student_ids"] == (STUDENT_ID,)  # type: ignore[index]


def test_confirm_select_commits_exact_preview_without_authoring(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _install_authorization(monkeypatch)
    preview = _preview()
    monkeypatch.setattr(
        cli,
        "preview_attempt_decision_selection",
        lambda *args, **kwargs: preview,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_attempt_decision_selection_preview",
        commit,
    )

    assert cli.main(
        _arguments("--confirm-select"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    assert observed == [
        (
            ("synthetic-workspace", preview),
            {"authorized_snapshot": authorized},
        )
    ]
    assert "confirmation supplied: yes" in output
    assert "Decision selection committed: revision 1" in output
    assert "decision authoring: not performed" in output


def test_json_output_reports_historical_target_and_selected_attempts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_authorization(monkeypatch)
    monkeypatch.setattr(
        cli,
        "preview_attempt_decision_selection",
        lambda *args, **kwargs: _preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_attempt_decision_selection_preview",
        lambda *args, **kwargs: _result(),
    )

    assert cli.main(
        _arguments("--confirm-select", "--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "selected"
    assert data["selection_confirmed"] is True
    assert data["preview"]["target_revision"] == 1
    assert data["preview"]["latest_revision"] == 2
    assert data["preview"]["target_is_latest"] is False
    assert data["preview"]["expected_current_decision_revision"] == 2
    assert data["preview"]["selected_count"] == 1
    assert data["preview"]["candidates"][1]["selected"] is True
    assert data["result"]["selected_revision"] == 1
    assert data["result"]["authoring_action"] == "not_performed"
