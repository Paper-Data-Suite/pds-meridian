"""Issue #117 Slice 2: explicit, fail-closed teacher-local policy authoring."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_records import PublicationRecord
from pds_core.routing_models import ModuleWorkRef

from meridian.ingestion import PublicationAuthorizationRequest
from meridian.publication_authorization import (
    AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE,
    default_authorization_policy_path,
    load_publication_authorizer,
)
from meridian.publication_authorization_setup import (
    PublicationAuthorizationSetupError,
    commit_publication_access,
    preview_publication_access,
)

NOW = datetime(2026, 10, 14, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_custom_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE, raising=False)


def _plan(
    root: Path,
    *,
    class_id: str = "class_1",
    producers: tuple[str, ...] = ("scoreform",),
    publications: tuple[str, ...] = ("pub_11111111111111111111111111111111",),
    future: bool = False,
):
    return preview_publication_access(
        root,
        class_id=class_id,
        producer_module_ids=producers,
        publication_ids=() if future else publications,
        include_future_publications=future,
    )


def _request(
    producer: str,
    *,
    students: tuple[str, ...],
    operation: str,
    purpose: str = "review_evidence",
    class_id: str = "class_1",
    publication_id: str = "pub_11111111111111111111111111111111",
) -> PublicationAuthorizationRequest:
    work = ModuleWorkRef(producer, class_id, "assignment_1")
    registration = AcademicWorkRegistration(
        "1", "academic_work_registration", work, 1,
        "assignment_contract_v1", "Benchmark", "assessment", "summative",
        "active", NOW, NOW, (),
    )
    publication = PublicationRecord(
        "1", "publication_record", publication_id, work, None,
        "academic_result_set", ("points",), "results", 1,
        "academic_result_manifest_v1",
        f"classes/{class_id}/modules/{producer}/work/assignment_1/result.json",
        "sha256", "a" * 64, NOW, 1, None,
    )
    return PublicationAuthorizationRequest(
        publication, registration, None, "current_selectable",
        operation, purpose, students,  # type: ignore[arg-type]
    )


def test_preview_is_read_only_and_requires_specific_scope(tmp_path: Path) -> None:
    path = default_authorization_policy_path(tmp_path)
    with pytest.raises(PublicationAuthorizationSetupError, match="must not be empty"):
        preview_publication_access(
            tmp_path, class_id="class_1", producer_module_ids=("scoreform",),
            publication_ids=(),
        )
    with pytest.raises(PublicationAuthorizationSetupError, match="not both"):
        preview_publication_access(
            tmp_path, class_id="class_1", producer_module_ids=("scoreform",),
            publication_ids=("pub_11111111111111111111111111111111",),
            include_future_publications=True,
        )
    plan = _plan(tmp_path)
    assert plan.changed
    assert plan.scope_label.startswith("Only")
    assert not path.exists()
    assert not path.parent.exists()


def test_confirmation_is_required_and_policy_is_atomic(tmp_path: Path) -> None:
    path = default_authorization_policy_path(tmp_path)
    plan = _plan(tmp_path)
    with pytest.raises(PublicationAuthorizationSetupError, match="AUTHORIZE"):
        commit_publication_access(plan, confirmation="yes")
    assert not path.exists()

    authorizer = commit_publication_access(plan, confirmation="AUTHORIZE")
    assert path.is_file()
    assert tuple(path.parent.glob(".policy-*.tmp")) == ()
    assert authorizer.policy_version == "1"
    assert authorizer.grants[0].student_ids == ()
    assert authorizer.grants[0].publication_ids == plan.publication_ids
    assert json.loads(path.read_text(encoding="utf-8"))["workspace_root"] == str(
        tmp_path.resolve()
    )


@pytest.mark.parametrize("operation", ["project_evidence", "read_projection_cache"])
@pytest.mark.parametrize("purpose", ["review_evidence", "teacher_reporting"])
@pytest.mark.parametrize("producer", ["scoreform", "quillan", "concord"])
def test_scope_is_enforced_for_each_producer_and_protected_operation(
    tmp_path: Path, producer: str, operation: str, purpose: str,
) -> None:
    plan = _plan(tmp_path, producers=(producer,))
    authorizer = commit_publication_access(plan, confirmation="AUTHORIZE")
    assert authorizer.authorize(
        _request(producer, students=(), operation=operation, purpose=purpose)
    ).allowed
    assert not authorizer.authorize(
        _request("other_producer", students=(), operation=operation, purpose=purpose)
    ).allowed
    assert not authorizer.authorize(
        _request(
            producer, students=(), operation=operation, purpose=purpose,
            publication_id="pub_22222222222222222222222222222222",
        )
    ).allowed
    assert not authorizer.authorize(
        _request(
            producer, students=(), operation=operation, purpose=purpose,
            class_id="class_2",
        )
    ).allowed


def test_future_scope_is_opt_in_and_remains_producer_bounded(tmp_path: Path) -> None:
    plan = _plan(tmp_path, producers=("concord", "quillan", "scoreform"), future=True)
    assert plan.scope_label.startswith("All current")
    authorizer = commit_publication_access(plan, confirmation="AUTHORIZE")
    for producer in ("scoreform", "quillan", "concord"):
        assert authorizer.authorize(
            _request(
                producer, students=(), operation="project_evidence",
                publication_id="pub_22222222222222222222222222222222",
            )
        ).allowed
    assert not authorizer.authorize(
        _request("portia", students=(), operation="project_evidence")
    ).allowed


def test_existing_restricted_grant_survives_and_no_implicit_widening(
    tmp_path: Path,
) -> None:
    initial = _plan(tmp_path)
    first = commit_publication_access(initial, confirmation="AUTHORIZE")
    assert len(first.grants) == 1
    new_plan = _plan(
        tmp_path,
        producers=("quillan",),
        publications=("pub_22222222222222222222222222222222",),
    )
    assert new_plan.changed and new_plan.policy_version == "2"
    after = commit_publication_access(new_plan, confirmation="AUTHORIZE")
    assert len(after.grants) == 2
    assert after.grants[0] == first.grants[0]
    assert not after.authorize(
        _request(
            "quillan", students=(), operation="project_evidence",
            publication_id="pub_33333333333333333333333333333333",
        )
    ).allowed
    again = _plan(
        tmp_path,
        producers=("quillan",),
        publications=("pub_22222222222222222222222222222222",),
    )
    assert not again.changed
    snapshot = default_authorization_policy_path(tmp_path).read_bytes()
    commit_publication_access(again, confirmation="AUTHORIZE")
    assert default_authorization_policy_path(tmp_path).read_bytes() == snapshot


def test_stale_preview_cannot_overwrite_existing_policy(tmp_path: Path) -> None:
    plan_a = _plan(tmp_path)
    plan_b = _plan(
        tmp_path, producers=("quillan",),
        publications=("pub_22222222222222222222222222222222",),
    )
    commit_publication_access(plan_a, confirmation="AUTHORIZE")
    before = default_authorization_policy_path(tmp_path).read_bytes()
    with pytest.raises(
        PublicationAuthorizationSetupError, match="changed since preview"
    ):
        commit_publication_access(plan_b, confirmation="AUTHORIZE")
    assert default_authorization_policy_path(tmp_path).read_bytes() == before


def test_invalid_policy_is_not_overwritten(tmp_path: Path) -> None:
    path = default_authorization_policy_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{invalid JSON", encoding="utf-8")
    with pytest.raises(PublicationAuthorizationSetupError, match="invalid"):
        _plan(tmp_path)
    assert path.read_text(encoding="utf-8") == "{invalid JSON"


def test_alternate_policy_configuration_is_not_silently_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        AUTHORIZATION_POLICY_ENVIRONMENT_VARIABLE,
        str(tmp_path / "custom-policy.json"),
    )
    with pytest.raises(PublicationAuthorizationSetupError, match="custom"):
        _plan(tmp_path)
    assert not default_authorization_policy_path(tmp_path).exists()


def test_symlinked_policy_directory_is_never_used(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    alias = tmp_path / ".pds"
    try:
        alias.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable to this test account")
    with pytest.raises(PublicationAuthorizationSetupError, match="symbolic link"):
        _plan(tmp_path)


def test_saved_policy_round_trips_through_existing_loader(tmp_path: Path) -> None:
    plan = _plan(tmp_path)
    saved = commit_publication_access(plan, confirmation="AUTHORIZE")
    loaded = load_publication_authorizer(
        default_authorization_policy_path(tmp_path), workspace_root=tmp_path,
    )
    assert loaded == saved


def test_existing_student_restricted_grant_remains_restricted(tmp_path: Path) -> None:
    path = default_authorization_policy_path(tmp_path)
    path.parent.mkdir(parents=True)
    old_policy = {
        "schema_version": "1",
        "record_type": "meridian_publication_authorization_policy",
        "policy_id": "teacher_local",
        "policy_version": "1",
        "workspace_root": str(tmp_path.resolve()),
        "grants": [{
            "class_id": "class_1",
            "operations": ["project_evidence", "read_projection_cache"],
            "purpose_ids": ["review_evidence"],
            "producer_module_ids": ["quillan"],
            "publication_ids": [],
            "student_ids": ["student_1"],
        }],
    }
    path.write_text(json.dumps(old_policy), encoding="utf-8")
    plan = _plan(tmp_path)
    saved = commit_publication_access(plan, confirmation="AUTHORIZE")
    assert len(saved.grants) == 2
    assert saved.grants[0].student_ids == ("student_1",)
    assert not saved.authorize(
        _request("quillan", students=(), operation="project_evidence")
    ).allowed
    assert saved.authorize(
        _request("quillan", students=("student_1",), operation="project_evidence")
    ).allowed
