from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "exclusions-select",
        PUBLICATION_ID,
        CACHE_KEY,
        GRADE_ITEM_ID,
        "scoreform_item_1",
        "1",
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        "--scope-student-id",
        "student_001",
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
    return SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
    )


def _preview() -> object:
    decision = SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        eligibility_revision=1,
        disposition="excluded",
        actor=SimpleNamespace(
            kind="teacher",
            actor_id="teacher_42",
        ),
        policy=SimpleNamespace(
            policy_id="teacher_local_eligibility",
            policy_version="1",
        ),
        reason_codes=("eligibility.teacher_exclusion",),
        rationale="Do not use this observation for this Grade Item.",
        source_state=SimpleNamespace(state="current"),
    )
    return SimpleNamespace(
        projection=_projection(),
        item_id="scoreform_item_1",
        target=SimpleNamespace(
            decision=decision,
            decision_sha256="a" * 64,
        ),
        target_revision=1,
        target_disposition="excluded",
        target_sha256="a" * 64,
        expected_current_revision=2,
        membership_revision=4,
        membership_revision_sha256="b" * 64,
        source_state=SimpleNamespace(state="superseded"),
        authoring_action="not_performed",
    )


def _result() -> object:
    return SimpleNamespace(
        selected_revision=1,
        selected_disposition="excluded",
        selected_decision_sha256="a" * 64,
        selection_disposition="updated",
        previous_current_revision=2,
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


def test_workflow_help_exposes_exclusions_select_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "exclusions-select" in output
    assert "Preview or select one persisted eligibility revision" in output


def test_preview_uses_exact_authorization_and_does_not_select(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _install_authorization(monkeypatch)
    projection = _projection()
    preview = _preview()
    observed: dict[str, object] = {}

    def inspect(*args: object, **kwargs: object) -> object:
        observed["inspect"] = (args, kwargs)
        return SimpleNamespace(authorized=authorized)

    def build(*args: object, **kwargs: object) -> object:
        observed["build"] = (args, kwargs)
        return projection

    def select_preview(*args: object, **kwargs: object) -> object:
        observed["preview"] = (args, kwargs)
        return preview

    monkeypatch.setattr(cli, "inspect_evidence_diagnostic", inspect)
    monkeypatch.setattr(cli, "build_exclusions_projection", build)
    monkeypatch.setattr(
        cli,
        "preview_exclusion_eligibility_selection",
        select_preview,
    )
    monkeypatch.setattr(
        cli,
        "commit_exclusion_eligibility_selection_preview",
        lambda *args, **kwargs: pytest.fail("preview must not select"),
    )

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    _, inspect_kwargs = observed["inspect"]
    assert inspect_kwargs["authorization_purpose_id"] == "teacher_review"
    assert inspect_kwargs["requested_student_ids"] == ("student_001",)
    assert observed["build"] == (
        ("synthetic-workspace", GRADE_ITEM_ID),
        {"authorized_snapshot": authorized},
    )
    preview_args, preview_kwargs = observed["preview"]
    assert preview_args == ("synthetic-workspace", projection)
    assert preview_kwargs == {
        "authorized_snapshot": authorized,
        "item_id": "scoreform_item_1",
        "eligibility_revision": 1,
    }

    assert "Exclusions eligibility selection preview" in output
    assert "target revision: 1" in output
    assert "target disposition: excluded" in output
    assert "current source state: superseded" in output
    assert "currently selected eligibility revision: 2" in output
    assert "confirmation supplied: no" in output
    assert "NO CURRENT ELIGIBILITY SELECTION CHANGED" in output
    assert "NO ELIGIBILITY REVISION AUTHORED" in output


def test_confirm_select_commits_exact_preview_without_authoring(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _install_authorization(monkeypatch)
    projection = _projection()
    preview = _preview()
    monkeypatch.setattr(
        cli,
        "build_exclusions_projection",
        lambda *args, **kwargs: projection,
    )
    monkeypatch.setattr(
        cli,
        "preview_exclusion_eligibility_selection",
        lambda *args, **kwargs: preview,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_exclusion_eligibility_selection_preview",
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
    assert "Eligibility selection committed: revision 1" in output
    assert "previous current eligibility revision: 2" in output
    assert "eligibility authoring: not performed" in output


def test_json_output_preserves_selection_and_authoring_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_authorization(monkeypatch)
    monkeypatch.setattr(
        cli,
        "build_exclusions_projection",
        lambda *args, **kwargs: _projection(),
    )
    monkeypatch.setattr(
        cli,
        "preview_exclusion_eligibility_selection",
        lambda *args, **kwargs: _preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_exclusion_eligibility_selection_preview",
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
    assert data["preview"]["target_disposition"] == "excluded"
    assert data["preview"]["authored_source_state"] == "current"
    assert data["preview"]["current_source_state"] == "superseded"
    assert data["preview"]["expected_current_revision"] == 2
    assert data["result"]["selected_revision"] == 1
    assert data["result"]["previous_current_revision"] == 2
    assert data["result"]["authoring_action"] == "not_performed"


def test_revision_must_be_positive_before_evidence_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: pytest.fail(
            "invalid revision must fail before evidence access"
        ),
    )

    arguments = list(_arguments())
    arguments[6] = "0"
    with pytest.raises(SystemExit):
        cli.main(
            tuple(arguments),
            dependencies=object(),  # type: ignore[arg-type]
        )
