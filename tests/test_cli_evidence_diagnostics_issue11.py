from __future__ import annotations

from typing import cast

import pytest
from pds_core.publication_compatibility import PublicationProducerRegistry

import meridian.cli as cli
import meridian.diagnostics as diagnostics
from meridian.adapters import AdapterRegistry
from meridian.ingestion import (
    PublicationAuthorizationDecision,
    PublicationAuthorizationRequest,
)

PUB_ID = "pub_11111111111111111111111111111111"
CACHE_KEY = "a" * 64


class AllowAuthorizer:
    def authorize(
        self, request: PublicationAuthorizationRequest
    ) -> PublicationAuthorizationDecision:
        return PublicationAuthorizationDecision(True, "district_policy", "1", ())


def dependencies(*, authorizer: object | None) -> diagnostics.DiagnosticsDependencies:
    return diagnostics.DiagnosticsDependencies(
        producer_registry=PublicationProducerRegistry(()),
        adapter_registry=AdapterRegistry(()),
        authorizer=cast(object, authorizer),  # type: ignore[arg-type]
        distribution_version_resolver=lambda name: "1.0.0",
    )


def test_evidence_group_exposes_inspect_and_explain_without_data_access(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["evidence"]) == 0
    output = capsys.readouterr().out
    assert "inspect" in output
    assert "explain" in output


def test_stock_evidence_command_fails_closed_without_authorizer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli.main(
        [
            "evidence",
            "inspect",
            PUB_ID,
            CACHE_KEY,
            "--workspace",
            "workspace",
            "--purpose-id",
            "grading_import",
        ],
        dependencies=dependencies(authorizer=None),
    )
    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "diagnostics.authorization_provider_required" in captured.err


def test_inspect_cli_forwards_exact_filters_and_scope(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, object] = {}

    def inspect(*args: object, **kwargs: object) -> object:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(cli, "inspect_evidence_diagnostic", inspect)
    monkeypatch.setattr(cli, "_render_evidence_inspection", lambda value, fmt: None)
    result = cli.main(
        [
            "evidence",
            "inspect",
            PUB_ID,
            CACHE_KEY,
            "--workspace",
            "workspace",
            "--purpose-id",
            "grading_import",
            "--scope-student-id",
            "student_2",
            "--scope-student-id",
            "student_1",
            "--student-id",
            "student_1",
            "--standard-id",
            "std_a",
            "--standard-id",
            "std_b",
            "--result-kind",
            "score",
            "--eligibility",
            "unevaluated",
            "--format",
            "json",
        ],
        dependencies=dependencies(authorizer=AllowAuthorizer()),
    )
    assert result == 0
    assert capsys.readouterr().err == ""
    kwargs = cast(dict[str, object], observed["kwargs"])
    assert kwargs["authorization_purpose_id"] == "grading_import"
    assert kwargs["requested_student_ids"] == ("student_2", "student_1")
    filters = cast(diagnostics.EvidenceFilters, kwargs["filters"])
    assert filters.student_ids == ("student_1",)
    assert filters.standard_ids == ("std_a", "std_b")
    assert filters.result_kinds == ("score",)
    assert filters.eligibility_statuses == ("unevaluated",)


def test_explain_cli_forwards_exact_authorization_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def explain(*args: object, **kwargs: object) -> object:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(cli, "explain_evidence_diagnostic", explain)
    monkeypatch.setattr(cli, "_render_evidence_explanation", lambda value, fmt: None)
    result = cli.main(
        [
            "evidence",
            "explain",
            PUB_ID,
            CACHE_KEY,
            "--workspace",
            "workspace",
            "--purpose-id",
            "grading_import",
            "--scope-student-id",
            "student_1",
        ],
        dependencies=dependencies(authorizer=AllowAuthorizer()),
    )
    assert result == 0
    kwargs = cast(dict[str, object], observed["kwargs"])
    assert kwargs["authorization_purpose_id"] == "grading_import"
    assert kwargs["requested_student_ids"] == ("student_1",)
