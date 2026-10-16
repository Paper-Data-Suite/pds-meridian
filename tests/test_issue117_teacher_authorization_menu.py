"""Issue #117 Slice 3: teacher access setup and same-session activation."""
from __future__ import annotations

import io
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from pds_core.routing_models import ModuleWorkRef

import meridian.menu as main_menu
from meridian.diagnostics import DiagnosticsDependencies
from meridian.menu_teacher_authorization import (
    _classes,
    run_teacher_evidence_authorization_menu,
)
from meridian.publication_authorization import (
    AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE,
    TeacherLocalPublicationAuthorizer,
    default_authorization_policy_path,
)
from meridian.teacher_evidence_inbox import (
    TeacherEvidenceClassGroup,
    TeacherEvidenceInbox,
    TeacherEvidenceInboxItem,
)


@pytest.fixture(autouse=True)
def clear_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE, raising=False)


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "classes" / "english_12_pd2").mkdir(parents=True)
    (tmp_path / "classes" / "english_10_pd4").mkdir()
    return tmp_path


def _script(*choices: str):
    answers = iter(choices)
    return lambda _prompt="": next(answers)


def _diagnostics() -> DiagnosticsDependencies:
    # The future-producer path needs no discovery or protected evidence.
    return cast(DiagnosticsDependencies, object())


def _run(root: Path, *answers: str, inbox_loader=None):
    stream = io.StringIO()
    kwargs = {}
    if inbox_loader is not None:
        kwargs["inbox_loader"] = inbox_loader
    result = run_teacher_evidence_authorization_menu(
        diagnostics=_diagnostics(),
        workspace_resolver=lambda: root,
        input_fn=_script(*answers),
        output=stream,
        clear_fn=lambda: None,
        **kwargs,
    )
    return result, stream.getvalue()


def _item(producer: str, title: str, publication_id: str) -> TeacherEvidenceInboxItem:
    return TeacherEvidenceInboxItem(
        publication_id=publication_id,
        work=ModuleWorkRef(producer, "english_12_pd2", "work_1"),
        school_year="2026-2027",
        class_label="english_12_pd2",
        work_title=title,
        producer_label=producer.title(),
        actionability="ready",
        status_code="ready_to_review",
        canonical_state="current_selectable",
        canonical_error_code=None,
        drift_fields=(),
        support_reason_codes=(),
    )


def _inbox(*items: TeacherEvidenceInboxItem) -> TeacherEvidenceInbox:
    return TeacherEvidenceInbox((TeacherEvidenceClassGroup(
        "english_12_pd2", "2026-2027", "english_12_pd2", tuple(items)
    ),))


def test_class_discovery_uses_existing_valid_directories(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (root / "classes" / "notes.txt").write_text("x", encoding="utf-8")
    assert _classes(root) == ("english_10_pd4", "english_12_pd2")
    assert not (root / ".pds").exists()


@pytest.mark.parametrize(
    ("option", "expected"),
    [
        ("1", ("scoreform",)),
        ("2", ("quillan",)),
        ("3", ("concord",)),
        ("4", ("concord", "quillan", "scoreform")),
    ],
)
def test_teacher_can_authorize_all_current_and_future_producer_evidence(
    tmp_path: Path, option: str, expected: tuple[str, ...],
) -> None:
    root = _workspace(tmp_path)
    authorized, display = _run(root, "2", option, "AUTHORIZE", "")
    assert isinstance(authorized, TeacherLocalPublicationAuthorizer)
    assert authorized.grants[0].class_id == "english_12_pd2"
    assert authorized.grants[0].producer_module_ids == expected
    assert authorized.grants[0].publication_ids == ()
    assert authorized.grants[0].student_ids == ()
    assert "protected student evidence" in display
    assert "No access" not in display


def test_cancel_before_confirmation_does_not_write_policy(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    authorized, display = _run(root, "2", "4", "B", "")
    assert authorized is None
    assert "Access was not changed" in display or "Confirmation" in display
    assert not default_authorization_policy_path(root).exists()


def test_authorize_one_current_publication_by_title_not_id(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    item = _item("quillan", "College Essay", "pub_11111111111111111111111111111111")
    authorized, display = _run(
        root, "2", "5", "1", "AUTHORIZE", "",
        inbox_loader=lambda _root, _deps: _inbox(item),
    )
    assert authorized is not None
    assert authorized.grants[0].producer_module_ids == ("quillan",)
    assert authorized.grants[0].publication_ids == (item.publication_id,)
    assert "College Essay" in display
    assert item.publication_id not in display


def test_stale_published_selection_is_not_authorized(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    item = _item("scoreform", "Memory Quiz", "pub_22222222222222222222222222222222")
    calls = 0

    def changing_loader(
        _root: Path, _deps: DiagnosticsDependencies
    ) -> TeacherEvidenceInbox:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _inbox(item)
        return _inbox(
            replace(
                item, canonical_state="historical",
                status_code="no_longer_current", actionability="blocked",
            )
        )

    authorized, display = _run(
        root, "2", "5", "1", "AUTHORIZE", "",
        inbox_loader=changing_loader,
    )
    assert authorized is None
    assert "changed or is no longer current" in display
    assert not default_authorization_policy_path(root).exists()


def test_alternate_configuration_blocks_save_and_preserves_external_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.setenv(
        AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE,
        str(root / "external-policy.json"),
    )
    authorized, display = _run(root, "2", "4", "", "B")
    assert authorized is None
    assert "custom MERIDIAN_AUTHORIZATION_POLICY" in display
    assert not default_authorization_policy_path(root).exists()


def test_no_classes_does_not_create_authorization(tmp_path: Path) -> None:
    authorized, display = _run(tmp_path, "")
    assert authorized is None
    assert "No existing PDS classes" in display
    assert not default_authorization_policy_path(tmp_path).exists()


def test_saved_policy_contains_no_student_payload(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _run(root, "2", "4", "AUTHORIZE", "")
    data = json.loads(default_authorization_policy_path(root).read_text("utf-8"))
    assert data["grants"][0]["student_ids"] == []
    assert set(data["grants"][0]["purpose_ids"]) == {
        "review_evidence", "teacher_reporting",
    }


def test_main_menu_activation_recomposes_authorizer_in_same_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    authorized, _ = _run(root, "2", "4", "AUTHORIZE", "")
    assert authorized is not None
    called: list[TeacherLocalPublicationAuthorizer] = []

    actions = [lambda: None for _ in range(9)]
    deps = main_menu.TeacherMenuDependencies(
        *actions, setup_evidence_access=lambda: authorized,
    )

    def fake_default(**kwargs):
        assert kwargs["diagnostics"].authorizer is authorized
        called.append(authorized)
        return deps

    monkeypatch.setattr(main_menu, "default_teacher_menu_dependencies", fake_default)
    assert main_menu.run_menu(
        dependencies=deps, input_fn=_script("A", "Q"),
        output=io.StringIO(), clear_fn=lambda: None,
    ) == 0
    assert called == [authorized]
