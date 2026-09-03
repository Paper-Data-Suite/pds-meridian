from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import meridian.cli as cli

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
NOW = datetime(2026, 9, 2, 16, 30, tzinfo=UTC)


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "exclusions-author",
        PUBLICATION_ID,
        CACHE_KEY,
        GRADE_ITEM_ID,
        "scoreform_item_1",
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        "--scope-student-id",
        "student_001",
        "--disposition",
        "excluded",
        "--actor-id",
        "teacher_42",
        "--policy-id",
        "teacher_local_eligibility",
        "--policy-version",
        "1",
        "--reason-code",
        "eligibility.teacher_exclusion",
        "--rationale",
        "Do not use this observation for this Grade Item.",
        "--decided-at",
        NOW.isoformat(),
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
    candidate = SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        eligibility_revision=3,
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
        source_state=SimpleNamespace(state="superseded"),
        membership_revision=4,
        decided_at=NOW,
    )
    return SimpleNamespace(
        projection=_projection(),
        item_id="scoreform_item_1",
        candidate=candidate,
        candidate_revision=3,
        candidate_disposition="excluded",
        history=(1, 2),
        expected_current_eligibility_revision=2,
        membership_revision=4,
        membership_revision_sha256="a" * 64,
        source_state="superseded",
        selection_action="not_performed",
    )


def _result() -> object:
    return SimpleNamespace(
        written_revision=3,
        written_disposition="excluded",
        selected_revision_before_write=2,
        selected_revision_after_write=2,
        selection_changed_during_write=False,
        selection_action="not_performed",
        write_result=SimpleNamespace(disposition="created"),
    )


def _install_authorization(monkeypatch: pytest.MonkeyPatch) -> object:
    authorized = _authorized()
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: SimpleNamespace(authorized=authorized),
    )
    return authorized


def test_workflow_help_exposes_exclusions_author_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "exclusions-author" in output
    assert "Preview or write one teacher academic eligibility revision" in output


def test_preview_uses_exact_authorization_and_does_not_write(
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

    def author(*args: object, **kwargs: object) -> object:
        observed["author"] = (args, kwargs)
        return preview

    monkeypatch.setattr(cli, "inspect_evidence_diagnostic", inspect)
    monkeypatch.setattr(cli, "build_exclusions_projection", build)
    monkeypatch.setattr(
        cli,
        "preview_exclusion_eligibility_authoring",
        author,
    )
    monkeypatch.setattr(
        cli,
        "commit_exclusion_eligibility_authoring_preview",
        lambda *args, **kwargs: pytest.fail("preview must not write"),
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

    author_args, author_kwargs = observed["author"]
    assert author_args == ("synthetic-workspace", projection)
    assert author_kwargs["authorized_snapshot"] is authorized
    assert author_kwargs["item_id"] == "scoreform_item_1"
    assert author_kwargs["disposition"] == "excluded"
    assert author_kwargs["actor_id"] == "teacher_42"
    assert author_kwargs["policy_id"] == "teacher_local_eligibility"
    assert author_kwargs["policy_version"] == "1"
    assert author_kwargs["reason_codes"] == (
        "eligibility.teacher_exclusion",
    )
    assert author_kwargs["decided_at"] == NOW

    assert "Exclusions eligibility authoring preview" in output
    assert "candidate revision: 3" in output
    assert "source state: superseded" in output
    assert "confirmation supplied: no" in output
    assert "NO ELIGIBILITY REVISION WRITTEN" in output
    assert "NO CURRENT SELECTION CHANGED" in output


def test_confirm_write_commits_preview_but_never_selects(
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
        "preview_exclusion_eligibility_authoring",
        lambda *args, **kwargs: preview,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_exclusion_eligibility_authoring_preview",
        commit,
    )

    assert cli.main(
        _arguments("--confirm-write"),
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
    assert "Eligibility revision written: 3" in output
    assert "current selection before write: 2" in output
    assert "current selection after write: 2" in output
    assert "selection action: not performed" in output


def test_json_output_preserves_write_and_selection_boundary(
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
        "preview_exclusion_eligibility_authoring",
        lambda *args, **kwargs: _preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_exclusion_eligibility_authoring_preview",
        lambda *args, **kwargs: _result(),
    )

    assert cli.main(
        _arguments("--confirm-write", "--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "written"
    assert data["write_confirmed"] is True
    assert data["preview"]["candidate_revision"] == 3
    assert data["preview"]["disposition"] == "excluded"
    assert data["preview"]["source_state"] == "superseded"
    assert data["preview"]["reason_codes"] == [
        "eligibility.teacher_exclusion"
    ]
    assert data["result"]["written_revision"] == 3
    assert data["result"]["selected_revision_before_write"] == 2
    assert data["result"]["selected_revision_after_write"] == 2
    assert data["result"]["selection_action"] == "not_performed"


def test_cli_rejects_source_lifecycle_dispositions_before_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: pytest.fail(
            "invalid parser disposition must fail before evidence access"
        ),
    )

    with pytest.raises(SystemExit):
        cli.main(
            _arguments(
                "--disposition",
                "withdrawn",
            ),
            dependencies=object(),  # type: ignore[arg-type]
        )
