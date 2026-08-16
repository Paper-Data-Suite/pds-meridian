from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pds_core.academic_catalog import PublicationCatalogQuery
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_compatibility import PublicationProducerRegistry
from pds_core.publication_records import PublicationRecord
from pds_core.routing_models import ModuleWorkRef

import meridian.cli as cli
import meridian.diagnostics as diagnostics
from meridian.adapters import AdapterRegistry
from meridian.ingestion import (
    CanonicalPublicationContext,
    PublicationDiscoveryRequest,
    PublicationSeriesMember,
    PublicationSeriesObservation,
)

NOW = datetime(2026, 8, 16, 18, tzinfo=UTC)
WORK = ModuleWorkRef("synthetic", "class_2026", "work_1")
PUB_ID = "pub_11111111111111111111111111111111"


def registration() -> AcademicWorkRegistration:
    return AcademicWorkRegistration(
        "1",
        "academic_work_registration",
        WORK,
        1,
        "assignment_v1",
        "Synthetic Work",
        "assignment",
        "summative",
        "active",
        NOW,
        NOW,
        (),
    )


def publication() -> PublicationRecord:
    return PublicationRecord(
        "1",
        "publication_record",
        PUB_ID,
        WORK,
        None,
        "academic_result_set",
        ("points",),
        "academic_results",
        1,
        "synthetic_manifest_v1",
        (
            "classes/class_2026/modules/synthetic/work/work_1/exports/"
            "manifests/academic_results/1.json"
        ),
        "sha256",
        "a" * 64,
        NOW,
        1,
        None,
    )


def context() -> CanonicalPublicationContext:
    pub = publication()
    reg = registration()
    return CanonicalPublicationContext(
        pub,
        reg,
        reg,
        PublicationSeriesObservation(
            (PublicationSeriesMember(pub, None),),
            pub.publication_id,
            0,
            pub.publication_id,
            "current_selectable",
            None,
        ),
        None,
    )


def empty_dependencies() -> diagnostics.DiagnosticsDependencies:
    return diagnostics.DiagnosticsDependencies(
        producer_registry=PublicationProducerRegistry(()),
        adapter_registry=AdapterRegistry(()),
    )


def test_publication_list_cli_builds_bounded_full_filter_query(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_list(
        workspace: str,
        request: PublicationDiscoveryRequest,
        dependencies: diagnostics.DiagnosticsDependencies,
    ) -> diagnostics.PublicationListDiagnostic:
        captured["workspace"] = workspace
        captured["query"] = request.query
        return diagnostics.PublicationListDiagnostic(request, ())

    monkeypatch.setattr(cli, "list_publication_diagnostics", fake_list)
    assert (
        cli.main(
            (
                "publications",
                "list",
                "--workspace",
                "synthetic-workspace",
                "--school-year",
                "2026-2027",
                "--class-id",
                "class_2026",
                "--module-id",
                "scoreform",
                "--work-id",
                "work_1",
                "--publication-kind",
                "academic_result_set",
                "--capability",
                "points",
                "--producer-contract-version",
                "scoreform_academic_work_v1",
                "--manifest-contract-version",
                "scoreform_academic_result_manifest_v1",
                "--record-set-id",
                "academic_results",
                "--minimum-record-set-revision",
                "2",
                "--state",
                "all",
                "--limit",
                "7",
                "--offset",
                "3",
            ),
            dependencies=empty_dependencies(),
        )
        == 0
    )
    query = captured["query"]
    assert isinstance(query, PublicationCatalogQuery)
    assert query.school_year == "2026-2027"
    assert query.class_id == "class_2026"
    assert query.module_id == "scoreform"
    assert query.work_id == "work_1"
    assert query.publication_kind == "academic_result_set"
    assert query.required_capabilities == ("points",)
    assert query.minimum_record_set_revision == 2
    assert query.state == "all"
    assert query.limit == 7
    assert query.offset == 3
    assert "No publication candidates" in capsys.readouterr().out


def test_publication_list_cli_default_limit_is_finite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, int | None] = {}

    def fake_list(
        workspace: str,
        request: PublicationDiscoveryRequest,
        dependencies: diagnostics.DiagnosticsDependencies,
    ) -> diagnostics.PublicationListDiagnostic:
        captured["limit"] = request.query.limit
        return diagnostics.PublicationListDiagnostic(request, ())

    monkeypatch.setattr(cli, "list_publication_diagnostics", fake_list)
    assert cli.main(
        ("publications", "list", "--workspace", "synthetic-workspace"),
        dependencies=empty_dependencies(),
    ) == 0
    assert captured["limit"] == 50


def test_verify_text_explicitly_says_manifest_was_not_read(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    support = diagnostics.PublicationSupportDiagnostic(
        profile_state="missing",
        compatibility_state="not_evaluated",
        compatibility_codes=(),
        adapter_state="missing",
        adapter_key=None,
        adapter_id=None,
        adapter_interface_version=None,
        projection_contract_version=None,
        adapter_supported_capabilities=(),
        reader_state="not_evaluated",
        reader_distribution=None,
        installed_reader_version=None,
        supported_reader_versions=(),
        overall_state="support_unsupported",
        reason_codes=("adapters.not_found", "ingestion.profile_missing"),
    )
    monkeypatch.setattr(
        cli,
        "verify_publication_diagnostic",
        lambda workspace, publication_id, dependencies: (
            diagnostics.PublicationVerificationDiagnostic(context(), support)
        ),
    )
    assert cli.main(
        ("publications", "verify", PUB_ID, "--workspace", "synthetic-workspace"),
        dependencies=empty_dependencies(),
    ) == 0
    output = capsys.readouterr().out
    assert "manifest access: not requested" in output
    assert "manifest bytes: not checked" in output
    assert "support status: support_unsupported" in output


def test_verify_json_is_one_deterministic_document(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    support = diagnostics.PublicationSupportDiagnostic(
        profile_state="missing",
        compatibility_state="not_evaluated",
        compatibility_codes=(),
        adapter_state="missing",
        adapter_key=None,
        adapter_id=None,
        adapter_interface_version=None,
        projection_contract_version=None,
        adapter_supported_capabilities=(),
        reader_state="not_evaluated",
        reader_distribution=None,
        installed_reader_version=None,
        supported_reader_versions=(),
        overall_state="support_unsupported",
        reason_codes=("adapters.not_found", "ingestion.profile_missing"),
    )
    result = diagnostics.PublicationVerificationDiagnostic(context(), support)
    monkeypatch.setattr(
        cli,
        "verify_publication_diagnostic",
        lambda workspace, publication_id, dependencies: result,
    )
    assert cli.main(
        (
            "publications",
            "verify",
            PUB_ID,
            "--workspace",
            "synthetic-workspace",
            "--format",
            "json",
        ),
        dependencies=empty_dependencies(),
    ) == 0
    output = capsys.readouterr().out
    decoded = json.loads(output)
    assert decoded["diagnostic_output_version"] == "1"
    assert decoded["kind"] == "publication_verification"
    assert decoded["canonical"]["manifest"]["access"] == "not_requested"
    assert decoded["canonical"]["manifest"]["bytes_checked"] is False
    assert output.endswith("\n")


def test_evidence_group_help_is_read_only_placeholder(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(("evidence",)) == 0
    assert "usage: meridian evidence" in capsys.readouterr().out
