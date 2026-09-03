from __future__ import annotations

import json
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
SCALE_ID = "four_level"
SCALE_REVISION = 2
SCALE_SHA256 = "a" * 64


def _arguments(*extra: str) -> tuple[str, ...]:
    return (
        "workflow",
        "standards-association-select",
        PUBLICATION_ID,
        CACHE_KEY,
        GRADE_ITEM_ID,
        STUDENT_ID,
        STANDARD_ID,
        ITEM_ID,
        SCALE_ID,
        str(SCALE_REVISION),
        SCALE_SHA256,
        "1",
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        "--scope-student-id",
        STUDENT_ID,
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
            snapshot_digest="3" * 64,
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
    decision = SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        standard_id=STANDARD_ID,
        source=SimpleNamespace(item_id=ITEM_ID),
        association_revision=1,
        disposition="not_associated",
        basis="explicit",
        actor=SimpleNamespace(
            kind="teacher",
            actor_id="teacher_42",
        ),
        rationale="Historical teacher decision.",
    )
    return SimpleNamespace(
        projection=_review_projection(),
        target=SimpleNamespace(
            decision=decision,
            decision_sha256="b" * 64,
        ),
        target_revision=1,
        target_disposition="not_associated",
        target_basis="explicit",
        target_sha256="b" * 64,
        history=(1, 2),
        expected_current_association_revision=2,
        attempt=None,
        authoring_action="not_performed",
    )


def _result() -> object:
    return SimpleNamespace(
        selected_revision=1,
        selected_disposition="not_associated",
        selected_basis="explicit",
        selected_decision_sha256="b" * 64,
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


def test_workflow_help_exposes_standards_association_select(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "standards-association-select" in output
    assert "Preview or select one persisted standards association revision" in output


def test_preview_uses_exact_review_scope_and_does_not_select(
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

    def select_preview(*args: object, **kwargs: object) -> object:
        observed["preview"] = (args, kwargs)
        return preview

    monkeypatch.setattr(cli, "inspect_evidence_diagnostic", inspect)
    monkeypatch.setattr(cli, "build_standards_review_projection", build)
    monkeypatch.setattr(
        cli,
        "preview_standards_association_selection",
        select_preview,
    )
    monkeypatch.setattr(
        cli,
        "commit_standards_association_selection_preview",
        lambda *args, **kwargs: pytest.fail("preview must not select"),
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

    preview_args, preview_kwargs = observed["preview"]
    assert preview_args == ("synthetic-workspace", review)
    assert preview_kwargs == {
        "authorized_snapshot": authorized,
        "association_revision": 1,
        "attempt": None,
    }

    assert "Standards association selection preview" in output
    assert "target revision: 1" in output
    assert "target association: not_associated" in output
    assert "target basis: explicit" in output
    assert "currently selected association revision: 2" in output
    assert "confirmation supplied: no" in output
    assert "NO CURRENT ASSOCIATION SELECTION CHANGED" in output
    assert "NO ASSOCIATION REVISION AUTHORED" in output


def test_confirm_select_commits_exact_preview_without_authoring(
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
        "preview_standards_association_selection",
        lambda *args, **kwargs: preview,
    )
    observed: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def commit(*args: object, **kwargs: object) -> object:
        observed.append((args, kwargs))
        return _result()

    monkeypatch.setattr(
        cli,
        "commit_standards_association_selection_preview",
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
    assert "Association selection committed: revision 1" in output
    assert "previous current association revision: 2" in output
    assert "association authoring: not performed" in output


def test_json_output_preserves_selection_authoring_boundary(
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
        "preview_standards_association_selection",
        lambda *args, **kwargs: _preview(),
    )
    monkeypatch.setattr(
        cli,
        "commit_standards_association_selection_preview",
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
    assert data["preview"]["target_disposition"] == "not_associated"
    assert data["preview"]["target_basis"] == "explicit"
    assert data["preview"]["expected_current_association_revision"] == 2
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
            "invalid revision must fail before protected evidence access"
        ),
    )
    arguments = list(_arguments())
    arguments[11] = "0"

    with pytest.raises(SystemExit):
        cli.main(
            tuple(arguments),
            dependencies=object(),  # type: ignore[arg-type]
        )
