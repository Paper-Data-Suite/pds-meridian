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
        "exclusions",
        PUBLICATION_ID,
        CACHE_KEY,
        GRADE_ITEM_ID,
        "--workspace",
        "synthetic-workspace",
        "--purpose-id",
        "teacher_review",
        "--scope-student-id",
        "student_001",
        "--scope-student-id",
        "student_002",
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


def _source(item_id: str) -> object:
    return SimpleNamespace(
        item_id=item_id,
        publication_id=PUBLICATION_ID,
    )


def _projection() -> object:
    rows = (
        SimpleNamespace(
            source=_source("attempt_1"),
            item_id="attempt_1",
            student_id="student_001",
            selected_disposition="included",
            selected_eligibility_revision=2,
            selected_decision_sha256="a" * 64,
            reviewed_membership_revision=3,
            current_membership_revision=3,
            reason_codes=(),
            rationale=None,
            actor_kind="teacher",
            actor_id="teacher_local",
            policy_id="teacher_local_eligibility",
            policy_version="1",
            reviewed_source_state="current",
            source_state="superseded",
            successor_publication_id="pub_" + ("4" * 32),
            head_publication_id="pub_" + ("5" * 32),
            operative_included=True,
            review_state="current",
        ),
        SimpleNamespace(
            source=_source("attempt_2"),
            item_id="attempt_2",
            student_id="student_002",
            selected_disposition="included",
            selected_eligibility_revision=1,
            selected_decision_sha256="b" * 64,
            reviewed_membership_revision=3,
            current_membership_revision=3,
            reason_codes=(),
            rationale=None,
            actor_kind="teacher",
            actor_id="teacher_local",
            policy_id="teacher_local_eligibility",
            policy_version="1",
            reviewed_source_state="current",
            source_state="withdrawn",
            successor_publication_id=None,
            head_publication_id=PUBLICATION_ID,
            operative_included=False,
            review_state="source_blocked",
        ),
        SimpleNamespace(
            source=_source("attempt_3"),
            item_id="attempt_3",
            student_id="student_002",
            selected_disposition=None,
            selected_eligibility_revision=None,
            selected_decision_sha256=None,
            reviewed_membership_revision=None,
            current_membership_revision=3,
            reason_codes=(),
            rationale=None,
            actor_kind=None,
            actor_id=None,
            policy_id=None,
            policy_version=None,
            reviewed_source_state=None,
            source_state="current",
            successor_publication_id=None,
            head_publication_id=PUBLICATION_ID,
            operative_included=False,
            review_state="no_decision",
        ),
    )
    return SimpleNamespace(
        class_id=CLASS_ID,
        grade_item_id=GRADE_ITEM_ID,
        rows=rows,
        counts={
            "included": 2,
            "excluded": 0,
            "pending": 0,
            "unsupported": 0,
            "superseded": 0,
            "withdrawn": 0,
            "no_decision": 1,
            "stale": 0,
            "source_blocked": 1,
            "source_unverifiable": 0,
        },
    )


def test_workflow_help_exposes_exclusions_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("workflow",)) == 0
    output = " ".join(capsys.readouterr().out.split())
    assert "exclusions" in output
    assert "Review academic eligibility separately from source lifecycle" in output


def test_exclusions_cli_uses_exact_authorization_scope_and_projection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _authorized()
    observed: dict[str, object] = {}

    def inspect(*args: object, **kwargs: object) -> object:
        observed["inspect"] = (args, kwargs)
        return SimpleNamespace(authorized=authorized)

    def build(*args: object, **kwargs: object) -> object:
        observed["build"] = (args, kwargs)
        return _projection()

    monkeypatch.setattr(cli, "inspect_evidence_diagnostic", inspect)
    monkeypatch.setattr(cli, "build_exclusions_projection", build)

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    output = capsys.readouterr().out

    inspect_args, inspect_kwargs = observed["inspect"]
    assert inspect_args[0:3] == (
        "synthetic-workspace",
        PUBLICATION_ID,
        CACHE_KEY,
    )
    assert inspect_kwargs["authorization_purpose_id"] == "teacher_review"
    assert inspect_kwargs["requested_student_ids"] == (
        "student_001",
        "student_002",
    )
    assert isinstance(inspect_kwargs["filters"], cli.EvidenceFilters)

    assert observed["build"] == (
        ("synthetic-workspace", GRADE_ITEM_ID),
        {"authorized_snapshot": authorized},
    )
    assert "Exclusions review" in output
    assert "attempt_1" in output
    assert "included | current | superseded | yes" in output
    assert "attempt_2" in output
    assert "included | source_blocked | withdrawn | no" in output
    assert "attempt_3" in output
    assert "none | no_decision | current | no" in output


def test_exclusions_json_keeps_disposition_and_source_state_separate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _authorized()
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: SimpleNamespace(authorized=authorized),
    )
    monkeypatch.setattr(
        cli,
        "build_exclusions_projection",
        lambda *args, **kwargs: _projection(),
    )

    assert cli.main(
        _arguments("--format", "json"),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["class_id"] == CLASS_ID
    assert data["grade_item_id"] == GRADE_ITEM_ID
    assert data["counts"]["no_decision"] == 1
    assert data["counts"]["source_blocked"] == 1

    first, second, third = data["rows"]
    assert first["academic_disposition"] == "included"
    assert first["source_state"] == "superseded"
    assert first["operative_included"] is True
    assert first["reason_codes"] == []
    assert first["actor_kind"] == "teacher"
    assert first["policy_id"] == "teacher_local_eligibility"
    assert first["reviewed_source_state"] == "current"
    assert second["academic_disposition"] == "included"
    assert second["source_state"] == "withdrawn"
    assert second["review_state"] == "source_blocked"
    assert second["operative_included"] is False
    assert third["academic_disposition"] is None
    assert third["review_state"] == "no_decision"


def test_exclusions_cli_does_not_mutate_eligibility_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorized = _authorized()
    monkeypatch.setattr(
        cli,
        "inspect_evidence_diagnostic",
        lambda *args, **kwargs: SimpleNamespace(authorized=authorized),
    )
    monkeypatch.setattr(
        cli,
        "build_exclusions_projection",
        lambda *args, **kwargs: _projection(),
    )

    for name in (
        "write_evidence_eligibility_revision",
        "select_evidence_eligibility_revision",
    ):
        assert not hasattr(cli, name)

    assert cli.main(
        _arguments(),
        dependencies=object(),  # type: ignore[arg-type]
    ) == 0
    capsys.readouterr()
