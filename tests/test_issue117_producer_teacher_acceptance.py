"""#117 Slice 5: real Core publication -> authorized three-producer teacher view.

Uses synthetic-only manifests from the repo's existing producer test support;
reads through actual installed producer reader contracts and Meridian adapters.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from concord.academic_result_manifest import derive_manifest_capabilities
from concord.academic_result_reader import read_academic_result_manifest
from pds_core.academic_catalog import rebuild_academic_catalog
from pds_core.classes import ensure_class_folder, write_class_roster
from pds_core.registry_services import (
    AcademicWorkRegistrationRequest,
    PublicationManifestRequest,
    publish_manifest_revision,
    register_academic_work,
)
from pds_core.rosters import create_roster
from pds_core.routes import module_work_dir
from pds_core.routing_models import ModuleRecordRef, ModuleWorkRef

from meridian.diagnostics import default_diagnostics_dependencies
from meridian.guided_projection import (
    default_guided_projection_dependencies,
    prepare_guided_evidence_projection,
)
from meridian.menu_teacher_evidence import (
    default_teacher_evidence_inbox_menu_dependencies,
    run_teacher_evidence_inbox_menu,
)
from meridian.publication_authorization import (
    PublicationAuthorizationGrant,
    TeacherLocalPublicationAuthorizer,
)
from meridian.teacher_evidence_inbox import load_teacher_evidence_inbox
from meridian.teacher_evidence_review import project_teacher_evidence_review
from meridian.teacher_session import TeacherSessionContext
from tests.concord_test_support import (
    SOURCE as CONCORD_SOURCE,
)
from tests.concord_test_support import (
    WORK as CONCORD_WORK,
)
from tests.concord_test_support import (
    concord_manifest_bytes,
)
from tests.quillan_test_support import (
    WORK as QUILLAN_WORK,
)
from tests.quillan_test_support import (
    quillan_manifest_bytes,
)
from tests.scoreform_test_support import (
    WORK as SCOREFORM_WORK,
)
from tests.scoreform_test_support import (
    scoreform_manifest_bytes,
)

PRODUCERS = ("scoreform", "quillan", "concord")


def _input(*choices: str):
    selected = iter(choices)
    return lambda _prompt="": next(selected)


def _published_workspace(
    tmp_path: Path, producer: str,
) -> tuple[Path, ModuleWorkRef, str, str]:
    root = tmp_path / "workspace"
    root.mkdir()
    source: ModuleRecordRef | None = None
    if producer == "scoreform":
        work = SCOREFORM_WORK
        manifest = scoreform_manifest_bytes()
        capabilities = ("points", "question_evidence", "multiple_attempts")
        producer_contract = "scoreform_academic_work_v1"
        manifest_contract = "scoreform_academic_result_manifest_v1"
        work_kind = "assignment"
        title = "Synthetic ScoreForm Quiz"
    elif producer == "quillan":
        work = QUILLAN_WORK
        manifest = quillan_manifest_bytes()
        capabilities = ("standards_ratings",)
        producer_contract = "quillan_academic_work_v1"
        manifest_contract = "quillan_academic_result_manifest_v1"
        work_kind = "assignment"
        title = "Synthetic Quillan Essay"
    else:
        assert producer == "concord"
        work = CONCORD_WORK
        source = CONCORD_SOURCE
        manifest = concord_manifest_bytes()
        capabilities = derive_manifest_capabilities(
            read_academic_result_manifest(manifest)
        )
        producer_contract = "concord_academic_work_v1"
        manifest_contract = "concord_academic_result_manifest_v1"
        work_kind = "collaborative_activity"
        title = "Synthetic Concord Activity"

    ensure_class_folder(root, work.class_id)
    roster = create_roster(
        work.class_id,
        (
            {
                "student_id": "student_synthetic_001",
                "first_name": "Alex",
                "last_name": "Rivera",
                "period": "2",
            },
            {
                "student_id": "student_synthetic_002",
                "first_name": "Jordan",
                "last_name": "Lee",
                "period": "2",
            },
            {
                "student_id": "student_1",
                "first_name": "Morgan",
                "last_name": "Chen",
                "period": "2",
            },
            {
                "student_id": "student_2",
                "first_name": "Taylor",
                "last_name": "Park",
                "period": "2",
            },
        ),
    )
    write_class_roster(root, roster)
    work_dir = module_work_dir(root, work)
    work_dir.mkdir(parents=True)
    registered = register_academic_work(
        root,
        AcademicWorkRegistrationRequest(
            work=work,
            producer_contract_version=producer_contract,
            title=title,
            work_kind=work_kind,
            academic_intent="formative",
            lifecycle="active",
            source_records=((source,) if source is not None else ()),
        ),
    )
    assert registered.registration.registration_revision == 1
    rel = (
        f"classes/{work.class_id}/modules/{producer}/work/{work.work_id}/"
        "publications/academic_results/1.json"
    )
    manifest_path = root.joinpath(*rel.split("/"))
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(manifest)
    published = publish_manifest_revision(
        root,
        PublicationManifestRequest(
            work=work,
            source_record=source,
            publication_kind="academic_result_set",
            capabilities=capabilities,
            record_set_id="academic_results",
            record_set_revision=1,
            manifest_contract_version=manifest_contract,
            manifest_path=rel,
            academic_work_registration_revision=1,
            expected_manifest_digest=hashlib.sha256(manifest).hexdigest(),
        ),
    )
    rebuild_academic_catalog(root)
    return root, work, published.publication.publication_id, title


def _grant(
    root: Path,
    work: ModuleWorkRef,
    *,
    operations: tuple[str, ...] = ("project_evidence", "read_projection_cache"),
) -> TeacherLocalPublicationAuthorizer:
    return TeacherLocalPublicationAuthorizer(
        root,
        "synthetic_policy",
        "1",
        (
            PublicationAuthorizationGrant(
                class_id=work.class_id,
                operations=operations,
                purpose_ids=("review_evidence", "teacher_reporting"),
                producer_module_ids=(work.module_id,),
                publication_ids=(),
                student_ids=(),
            ),
        ),
    )


@pytest.mark.parametrize("producer", PRODUCERS)
def test_canonical_to_actual_reader_to_teacher_review(
    tmp_path: Path, producer: str,
) -> None:
    root, work, publication_id, title = _published_workspace(tmp_path, producer)
    diagnostics = default_diagnostics_dependencies(
        workspace_root=root, authorizer=_grant(root, work),
    )
    inbox = load_teacher_evidence_inbox(root, diagnostics)
    assert len(inbox.items) == 1
    item = inbox.items[0]
    assert item.publication_id == publication_id
    assert item.status_code == "ready_to_review"
    assert item.work_title == title
    assert item.producer_label.casefold() == producer

    prepared = prepare_guided_evidence_projection(
        root,
        work,
        publication_id,
        dependencies=default_guided_projection_dependencies(diagnostics=diagnostics),
    )
    assert prepared.purpose_id == "review_evidence"
    assert prepared.requested_student_ids == ()
    assert prepared.evidence_count > 0
    review = project_teacher_evidence_review(root, prepared)
    assert review.work == work
    assert review.publication_id == publication_id
    assert review.students or review.shared_items

    output = StringIO()
    session = TeacherSessionContext()
    run_teacher_evidence_inbox_menu(
        dependencies=replace(
            default_teacher_evidence_inbox_menu_dependencies(
                diagnostics=diagnostics
            ),
            workspace_resolver=lambda: root,
        ),
        session_context=session,
        input_fn=_input("1", "1", "b", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )
    rendered = output.getvalue()
    assert "Review New Evidence" in rendered
    assert "Evidence Review" in rendered
    assert title in rendered
    assert item.producer_label in rendered
    assert publication_id not in rendered
    assert session.active_work == work
    assert session.active_publication_id == publication_id


@pytest.mark.parametrize("producer", PRODUCERS)
def test_missing_cache_permission_never_claims_ready(
    tmp_path: Path, producer: str,
) -> None:
    root, work, publication_id, _title = _published_workspace(tmp_path, producer)
    diagnostics = default_diagnostics_dependencies(
        workspace_root=root,
        authorizer=_grant(root, work, operations=("project_evidence",)),
    )
    inbox = load_teacher_evidence_inbox(root, diagnostics)
    assert len(inbox.items) == 1
    assert inbox.items[0].publication_id == publication_id
    assert inbox.items[0].status_code == "access_not_granted"
    assert inbox.items[0].actionability == "blocked"

    output = StringIO()
    session = TeacherSessionContext()
    run_teacher_evidence_inbox_menu(
        dependencies=replace(
            default_teacher_evidence_inbox_menu_dependencies(
                diagnostics=diagnostics
            ),
            workspace_resolver=lambda: root,
        ),
        session_context=session,
        input_fn=_input("1", "1", "b", "b", "b"),
        output=output,
        clear_fn=lambda: None,
    )
    assert "Evidence Not Ready" in output.getvalue()
    assert "access" in output.getvalue().casefold()
    assert publication_id not in output.getvalue()
    assert session.active_publication_id is None
