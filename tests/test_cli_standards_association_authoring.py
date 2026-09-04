from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import meridian.cli as cli
from meridian.proficiency_mapping import ProficiencyScaleReference

CLASS_ID = "synthetic_class_2026"
GRADE_ITEM_ID = "unit1_assessment"
STUDENT_ID = "student_001"
STANDARD_ID = "NJSLSA.R1"
ITEM_ID = "scoreform_item_1"
PUBLICATION_ID = "pub_" + ("1" * 32)
CACHE_KEY = "2" * 64
SNAPSHOT_DIGEST = "3" * 64
SCALE_ID = "four_level"
SCALE_REVISION = 2
SCALE_SHA256 = "a" * 64
NOW = datetime(2026, 9, 2, 19, 0, tzinfo=UTC)


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "standards-association-author",
        PUBLICATION_ID,
        CACHE_KEY,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        ITEM_ID,
        SCALE_ID,
        str(SCALE_REVISION),
        SCALE_SHA256,
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        "--scope-student-id",
        STUDENT_ID,
        "--operation",
        "create",
        "--disposition",
        "associated",
        "--basis",
        "explicit",
        "--actor-id",
        "teacher_42",
        "--rationale",
        "Teacher reviewed the evidence-standard relationship.",
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


def _review_projection() -> object:
    return SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        student_id=STUDENT_ID,
        standard_id=STANDARD_ID,
        item_id=ITEM_ID,
    )


def _preview() -> object:
    candidate = SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        standard_id=STANDARD_ID,
        source=SimpleNamespace(item_id=ITEM_ID),
        association_revision=3,
        supersedes_revision=2,
        disposition="associated",
        basis="explicit",
        actor=SimpleNamespace(kind="teacher", actor_id="teacher_42"),
        rationale="Teacher reviewed the evidence-standard relationship.",
        decided_at=NOW,
    )
    return SimpleNamespace(
        projection=_review_projection(),
        operation="create",
        candidate=candidate,
        candidate_revision=3,
        candidate_disposition="associated",
        candidate_basis="explicit",
        history=(1, 2),
        latest_revision_sha256="b" * 64,
        expected_current_association_revision=1,
        grade_item_revision=4,
        grade_item_revision_sha256="c" * 64,
        membership_revision=5,
        membership_revision_sha256="d" * 64,
        standard_resolved=True,
        standard_active=True,
        selection_action="not_performed",
    )


def _result() -> object:
    return SimpleNamespace(
        written_revision=3,
        written_disposition="associated",
        written_basis="explicit",
        selected_revision_before_write=1,
        selected_revision_after_write=1,
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


def test_workflow_help_exposes_standards_association_author(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "standards-association-author" in output
    assert "Preview or write one standards-evidence association revision" in output


def test_preview_uses_review_scope_and_does_not_write(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _authorized()
    review = _review_projection()
    preview = _preview()
    observed: dict[str, object] = {}

    def inspect(*args: object, **kwargs: object) -> object:
        observed["inspect"] = (args, kwargs)
        return SimpleNamespace(authorized=authorized)

    def build(*args: object, **kwargs: object) -> object:
        observed["build"] = (args, kwargs)
        return review

    def author(*args: object, **kwargs: object) -> object:
        observed["author"] = (args, kwargs)
        return preview

    monkeypatch.setattr(cli, "inspect_evidence_diagnostic", inspect)
    monkeypatch.setattr(cli, "build_standards_review_projection", build)
    monkeypatch.setattr(
        cli,
        "preview_standards_association_authoring",
        author,
    )
    monkeypatch.setattr(
        cli,
        "commit_standards_association_authoring_preview",
        lambda *args, **kwargs: pytest.fail("preview must not write"),
    )

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    _, inspect_kwargs = observed["inspect"]
    assert inspect_kwargs["authorization_purpose_id"] == "teacher_review"
    assert inspect_kwargs["requested_student_ids"] == (STUDENT_ID,)

    build_args, build_kwargs = observed["build"]
    assert build_args == (
        "synthetic-workspace",
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        ITEM_ID,
        ProficiencyScaleReference(
            class_id=CLASS_ID,
            scale_id=SCALE_ID,
            scale_revision=SCALE_REVISION,
            scale_sha256=SCALE_SHA256,
        ),
    )
    assert build_kwargs["authorized_snapshot"] is authorized
    assert build_kwargs["mapping_profile"] is None
    assert build_kwargs["attempt"] is None

    author_args, author_kwargs = observed["author"]
    assert author_args == ("synthetic-workspace", review)
    assert author_kwargs == {
        "authorized_snapshot": authorized,
        "operation": "create",
        "disposition": "associated",
        "basis": "explicit",
        "actor_id": "teacher_42",
        "rationale": "Teacher reviewed the evidence-standard relationship.",
        "decided_at": NOW,
    }

    assert "Standards association authoring preview" in output
    assert "candidate revision: 3" in output
    assert "association: associated" in output
    assert "basis: explicit" in output
    assert "confirmation supplied: no" in output
    assert "NO ASSOCIATION REVISION WRITTEN" in output
    assert "NO CURRENT ASSOCIATION SELECTION CHANGED" in output


def test_confirm_write_commits_exact_preview_without_selecting(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _install_authorization(monkeypatch)
    review = _review_projection()
    preview = _preview()
    monkeypatch.setattr(
        cli,
        "build_standards_review_projection",
        lambda *args, **kwargs: review,
    )
    monkeypatch.setattr(
        cli,
        "preview_standards_association_authoring",
        lambda *args, **kwargs: preview,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_standards_association_authoring_preview",
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
    assert "Association revision written: 3" in output
    assert "current selection before write: 1" in output
    assert "current selection after write: 1" in output
    assert "selection action: not performed" in output


def test_json_output_preserves_write_selection_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_authorization(monkeypatch)
    monkeypatch.setattr(
        cli,
        "build_standards_review_projection",
        lambda *args, **kwargs: _review_projection(),
    )
    monkeypatch.setattr(
        cli,
        "preview_standards_association_authoring",
        lambda *args, **kwargs: _preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_standards_association_authoring_preview",
        lambda *args, **kwargs: _result(),
    )

    assert cli.main(
        _arguments("--confirm-write", "--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["mode"] == "written"
    assert data["write_confirmed"] is True
    assert data["preview"]["operation"] == "create"
    assert data["preview"]["candidate_revision"] == 3
    assert data["preview"]["disposition"] == "associated"
    assert data["preview"]["basis"] == "explicit"
    assert data["result"]["written_revision"] == 3
    assert data["result"]["selected_revision_before_write"] == 1
    assert data["result"]["selected_revision_after_write"] == 1
    assert data["result"]["selection_action"] == "not_performed"
