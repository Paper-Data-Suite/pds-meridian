"""Installed-wheel guided evidence acceptance for Meridian Issue #110."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import sys
from io import StringIO
from pathlib import Path
from typing import Final

from pds_core.academic_catalog import rebuild_academic_catalog
from pds_core.classes import ensure_class_folder, write_class_roster
from pds_core.publication_records import PublicationCapability
from pds_core.registry_services import (
    AcademicWorkRegistrationRequest,
    PublicationManifestRequest,
    publish_manifest_revision,
    register_academic_work,
)
from pds_core.rosters import create_roster
from pds_core.routes import module_work_dir
from pds_core.routing_models import ModuleWorkRef

from meridian.diagnostics import default_diagnostics_dependencies
from meridian.ingestion import (
    PublicationAuthorizationDecision,
    PublicationAuthorizationRequest,
)
from meridian.menu_teacher_evidence import (
    default_teacher_evidence_inbox_menu_dependencies,
    run_teacher_evidence_inbox_menu,
)
from meridian.teacher_session import TeacherSessionContext

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
FIXTURE_DIR: Final[Path] = ROOT / "tests" / "fixtures" / "issue110"


class ScriptedInput:
    def __init__(self, *responses: str) -> None:
        self._responses = iter(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self._responses)


class AllowInstalledAcceptance:
    """Explicit test deployment authorization for installed acceptance."""

    def authorize(
        self,
        request: PublicationAuthorizationRequest,
    ) -> PublicationAuthorizationDecision:
        if request.purpose_id != "review_evidence":
            raise AssertionError("Unexpected guided authorization purpose.")
        return PublicationAuthorizationDecision(
            True,
            "issue110_installed_acceptance",
            "1",
        )


def _assert_installed_origin(module: object) -> None:
    file_value = getattr(module, "__file__", None)
    if not isinstance(file_value, str):
        raise AssertionError("Installed module does not expose __file__.")
    path = Path(file_value).resolve()
    if not path.is_relative_to(Path(sys.prefix).resolve()):
        raise AssertionError(f"Module did not load from installed environment: {path}")


ProducerManifest = tuple[
    bytes,
    ModuleWorkRef,
    str,
    tuple[PublicationCapability, ...],
]


def _scoreform_manifest() -> ProducerManifest:
    import scoreform
    from scoreform import academic_result_manifest as scoreform_manifest

    _assert_installed_origin(scoreform)
    if importlib.metadata.version("scoreform") != "0.12.1":
        raise AssertionError("ScoreForm installed version must be exactly 0.12.1.")

    raw = (FIXTURE_DIR / "scoreform_manifest_issue110.json").read_bytes()
    manifest = scoreform_manifest.manifest_from_json_bytes(raw)
    canonical = scoreform_manifest.manifest_to_canonical_json_bytes(manifest)
    work = ModuleWorkRef(
        manifest.work.module_id,
        manifest.work.class_id,
        manifest.work.work_id,
    )
    capabilities: tuple[PublicationCapability, ...] = (
        "multiple_attempts",
        "points",
        "question_evidence",
    )
    return canonical, work, "scoreform_academic_work_v1", capabilities


def _quillan_manifest() -> ProducerManifest:
    import quillan
    from quillan import academic_result_manifest as quillan_manifest

    _assert_installed_origin(quillan)
    if importlib.metadata.version("quillan") != "0.10.5":
        raise AssertionError("Quillan installed version must be exactly 0.10.5.")

    raw = (FIXTURE_DIR / "quillan_manifest_issue110.json").read_bytes()
    manifest = quillan_manifest.manifest_from_json_bytes(raw)
    canonical = quillan_manifest.manifest_to_canonical_json_bytes(manifest)
    work = ModuleWorkRef(
        manifest.work.module_id,
        manifest.work.class_id,
        manifest.work.work_id,
    )
    capabilities: tuple[PublicationCapability, ...] = ("standards_ratings",)
    return canonical, work, "quillan_academic_work_v1", capabilities


def _producer_manifest(producer: str) -> ProducerManifest:
    if producer == "scoreform":
        return _scoreform_manifest()
    if producer == "quillan":
        return _quillan_manifest()
    raise AssertionError(f"Unsupported producer: {producer}")


def _setup_workspace(
    workspace: Path,
    producer: str,
) -> tuple[ModuleWorkRef, str, str]:
    canonical, work, producer_contract, capabilities = _producer_manifest(producer)
    title = (
        "Installed ScoreForm Reading Check"
        if producer == "scoreform"
        else "Installed Quillan Memoir Analysis"
    )

    workspace.mkdir(parents=True)
    ensure_class_folder(workspace, work.class_id)
    roster = create_roster(
        work.class_id,
        (
            {
                "student_id": "student_alpha",
                "last_name": "Rivera",
                "first_name": "Alex",
                "period": "2",
            },
        ),
    )
    write_class_roster(workspace, roster)

    work_root = module_work_dir(workspace, work)
    work_root.mkdir(parents=True, exist_ok=False)

    registration = register_academic_work(
        workspace,
        AcademicWorkRegistrationRequest(
            work=work,
            producer_contract_version=producer_contract,
            title=title,
            work_kind="assignment",
            academic_intent="summative",
            lifecycle="active",
            source_records=(),
        ),
    )
    if registration.registration.registration_revision != 1:
        raise AssertionError("Installed acceptance expected registration revision 1.")

    manifest_path = (
        work_root
        / "exports"
        / "manifests"
        / "academic_results"
        / "1.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(canonical)
    relative = manifest_path.relative_to(workspace).as_posix()

    published = publish_manifest_revision(
        workspace,
        PublicationManifestRequest(
            work=work,
            source_record=None,
            publication_kind="academic_result_set",
            capabilities=capabilities,
            record_set_id="academic_results",
            record_set_revision=1,
            manifest_contract_version=(
                "scoreform_academic_result_manifest_v1"
                if producer == "scoreform"
                else "quillan_academic_result_manifest_v1"
            ),
            manifest_path=relative,
            academic_work_registration_revision=1,
            expected_manifest_digest=hashlib.sha256(canonical).hexdigest(),
        ),
    )
    rebuild_academic_catalog(workspace)
    return work, published.publication.publication_id, title


def _run_teacher_journey(
    workspace: Path,
    producer: str,
    publication_id: str,
    title: str,
) -> None:
    os.environ["PDS_WORKSPACE_ROOT"] = str(workspace)
    diagnostics = default_diagnostics_dependencies(
        authorizer=AllowInstalledAcceptance()
    )
    dependencies = default_teacher_evidence_inbox_menu_dependencies(
        diagnostics=diagnostics
    )

    scripted = ScriptedInput(
        "1",
        "1",
        "1",
        "1",
        "1",
        "b",
        "b",
        "b",
        "b",
        "b",
        "b",
    )
    output = StringIO()
    session = TeacherSessionContext()
    run_teacher_evidence_inbox_menu(
        dependencies=dependencies,
        session_context=session,
        input_fn=scripted,
        output=output,
        clear_fn=lambda: None,
    )

    rendered = output.getvalue()
    expected_source = "ScoreForm" if producer == "scoreform" else "Quillan"
    for expected in (
        "Review New Evidence",
        "Choose a class.",
        "english_12_pd2",
        title,
        expected_source,
        "Alex Rivera",
        "Evidence Detail",
        "Recommended next step:",
        "Set up Grade Item and review eligibility",
    ):
        if expected not in rendered:
            raise AssertionError(f"Missing guided teacher presentation: {expected!r}")

    forbidden = (
        publication_id,
        "Projection cache key:",
        "Authorization purpose ID:",
        "Grade Item ID:",
        "Student ID:",
        "Evidence item ID:",
        "Teacher actor ID:",
        "Policy ID:",
        "Target proficiency scale ID:",
        "Target scale revision:",
        "Target scale sha256:",
    )
    prompt_text = "\n".join(scripted.prompts)
    for value in forbidden:
        if value in rendered or value in prompt_text:
            raise AssertionError(
                f"Opaque identity leaked into ordinary guided route: {value!r}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("producer", choices=("scoreform", "quillan"))
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args(argv)

    import pds_core

    import meridian

    _assert_installed_origin(meridian)
    _assert_installed_origin(pds_core)
    if importlib.metadata.version("pds-core") != "0.6.4":
        raise AssertionError("Core installed version must be exactly 0.6.4.")

    _, publication_id, title = _setup_workspace(args.workspace, args.producer)
    _run_teacher_journey(
        args.workspace,
        args.producer,
        publication_id,
        title,
    )
    print(
        f"Issue #110 installed guided {args.producer} teacher journey passed.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
