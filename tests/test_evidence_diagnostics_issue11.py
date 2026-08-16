from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from pds_core.academic_work_registrations import AcademicWorkRegistration
from pds_core.publication_compatibility import PublicationProducerRegistry
from pds_core.publication_records import PublicationRecord
from pds_core.routing_models import ModuleWorkRef

import meridian.diagnostics as diagnostics
from meridian.adapters import AdapterRegistry
from meridian.evidence import (
    EvidenceEligibility,
    EvidenceInventory,
    EvidenceItem,
    EvidenceProvenance,
    EvidenceTarget,
    NativePointValue,
    NativeProvenance,
    NativeReference,
    NativeScalarValue,
    NativeScale,
    NativeScaledValue,
    NativeScaleLevel,
    NativeStateValue,
    ProjectionIdentity,
    StudentSubject,
)
from meridian.ingestion import (
    PublicationAuthorizationDecision,
    PublicationAuthorizationRequest,
)
from meridian.projection_cache import AuthorizedProjectionSnapshot

NOW = datetime(2026, 8, 16, 20, tzinfo=UTC)
WORK = ModuleWorkRef("synthetic", "class_2026", "work_1")
MANIFEST_BYTES = b"synthetic manifest\n"
DIGEST = hashlib.sha256(MANIFEST_BYTES).hexdigest()
PUB_ID = "pub_11111111111111111111111111111111"
CACHE_KEY = "a" * 64


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
        "classes/class_2026/modules/synthetic/work/work_1/manifest.json",
        "sha256",
        DIGEST,
        NOW,
        1,
        None,
    )


def provenance() -> EvidenceProvenance:
    return EvidenceProvenance(
        publication(),
        registration(),
        None,
        ProjectionIdentity("synthetic.adapter", "1", "synthetic-reader", "1.0.0"),
        NativeProvenance((NativeReference("record", "native_1"),)),
    )


def item(
    item_id: str,
    student_id: str,
    result_kind: str,
    value: object,
    *,
    standard_ids: tuple[str, ...] = (),
    eligibility: EvidenceEligibility | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        item_id=item_id,
        subject=StudentSubject(student_id),
        target=EvidenceTarget(
            "question",
            f"target_{item_id}",
            standard_ids=standard_ids,
        ),
        result_kind=result_kind,
        value=value,  # type: ignore[arg-type]
        provenance=provenance(),
        eligibility=(
            EvidenceEligibility.unevaluated() if eligibility is None else eligibility
        ),
    )


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


def fake_authorized(inventory: EvidenceInventory) -> AuthorizedProjectionSnapshot:
    assessment = SimpleNamespace(
        source_status="current",
        reuse_status="reusable",
        reason_codes=(),
        observed_canonical_state="current_selectable",
        current_canonical_state="current_selectable",
        observed_head_publication_id=PUB_ID,
        current_head_publication_id=PUB_ID,
        observed_current_registration_revision=1,
        current_registration_revision=1,
    )
    snapshot = SimpleNamespace(
        source=SimpleNamespace(publication=publication()),
        cache_key=CACHE_KEY,
        authorization=SimpleNamespace(
            purpose_id="grading_import",
            requested_student_ids=("student_1", "student_2"),
        ),
        inventory=inventory,
    )
    return cast(
        AuthorizedProjectionSnapshot,
        SimpleNamespace(
            stored=SimpleNamespace(snapshot=snapshot),
            assessment=assessment,
        ),
    )


def test_missing_authorizer_fails_before_cache_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("cache loader must not run")

    monkeypatch.setattr(
        diagnostics, "load_authorized_projection_snapshot", fail_if_called
    )
    with pytest.raises(diagnostics.DiagnosticsAuthorizationProviderRequiredError):
        diagnostics.inspect_evidence_diagnostic(
            "workspace",
            PUB_ID,
            CACHE_KEY,
            authorization_purpose_id="grading_import",
            requested_student_ids=("student_1",),
            filters=diagnostics.EvidenceFilters(),
            dependencies=dependencies(authorizer=None),
        )
    assert called is False


def test_inspection_forwards_exact_authorization_scope_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = EvidenceInventory(
        (
            item("evidence_1", "student_1", "score", NativeScalarValue(1)),
            item("evidence_2", "student_2", "state", NativeStateValue("absent")),
            item("evidence_3", "student_1", "score", NativeScalarValue(2)),
        )
    )
    authorized = fake_authorized(inventory)
    observed: dict[str, object] = {}

    def loader(*args: object, **kwargs: object) -> AuthorizedProjectionSnapshot:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return authorized

    monkeypatch.setattr(diagnostics, "load_authorized_projection_snapshot", loader)
    result = diagnostics.inspect_evidence_diagnostic(
        "workspace",
        PUB_ID,
        CACHE_KEY,
        authorization_purpose_id="grading_import",
        requested_student_ids=("student_2", "student_1"),
        filters=diagnostics.EvidenceFilters(
            student_ids=("student_1",), result_kinds=("score",)
        ),
        dependencies=dependencies(authorizer=AllowAuthorizer()),
    )
    assert [value.item_id for value in result.items] == ["evidence_1", "evidence_3"]
    kwargs = cast(dict[str, object], observed["kwargs"])
    assert kwargs["authorization_purpose_id"] == "grading_import"
    assert kwargs["requested_student_ids"] == ("student_2", "student_1")
    assert kwargs["authorizer"] is not None


def test_filter_dimensions_combine_with_and_and_repeated_values_use_or(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = EvidenceInventory(
        (
            item(
                "evidence_1",
                "student_1",
                "score",
                NativeScalarValue(1),
                standard_ids=("std_a",),
            ),
            item(
                "evidence_2",
                "student_1",
                "score",
                NativeScalarValue(2),
                standard_ids=("std_b",),
            ),
            item(
                "evidence_3",
                "student_2",
                "score",
                NativeScalarValue(3),
                standard_ids=("std_a",),
            ),
        )
    )
    monkeypatch.setattr(
        diagnostics,
        "load_authorized_projection_snapshot",
        lambda *args, **kwargs: fake_authorized(inventory),
    )
    result = diagnostics.inspect_evidence_diagnostic(
        "workspace",
        PUB_ID,
        CACHE_KEY,
        authorization_purpose_id="grading_import",
        requested_student_ids=(),
        filters=diagnostics.EvidenceFilters(
            student_ids=("student_1",),
            standard_ids=("std_a", "std_b"),
            result_kinds=("score",),
        ),
        dependencies=dependencies(authorizer=AllowAuthorizer()),
    )
    assert [value.item_id for value in result.items] == ["evidence_1", "evidence_2"]


def test_json_preserves_native_scalar_types_and_value_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scale = NativeScale(
        "native_scale",
        (
            NativeScaleLevel(0, "Zero"),
            NativeScaleLevel(2, "Two"),
        ),
    )
    inventory = EvidenceInventory(
        (
            item("bool_item", "student_1", "bool_result", NativeScalarValue(True)),
            item("int_item", "student_1", "int_result", NativeScalarValue(1)),
            item("float_item", "student_1", "float_result", NativeScalarValue(1.0)),
            item("str_item", "student_1", "str_result", NativeScalarValue("1")),
            item("points_item", "student_1", "points", NativePointValue(1, 2)),
            item("scaled_item", "student_1", "rating", NativeScaledValue(0, scale)),
            item("state_item", "student_1", "state", NativeStateValue("absent")),
        )
    )
    monkeypatch.setattr(
        diagnostics,
        "load_authorized_projection_snapshot",
        lambda *args, **kwargs: fake_authorized(inventory),
    )
    result = diagnostics.inspect_evidence_diagnostic(
        "workspace",
        PUB_ID,
        CACHE_KEY,
        authorization_purpose_id="grading_import",
        requested_student_ids=(),
        filters=diagnostics.EvidenceFilters(),
        dependencies=dependencies(authorizer=AllowAuthorizer()),
    )
    payload = diagnostics.evidence_inspection_to_dict(result)
    values = {
        cast(dict[str, object], entry)["item_id"]: cast(
            dict[str, object], entry
        )["value"]
        for entry in cast(list[object], payload["items"])
    }

    def scalar_type(item_id: str) -> object:
        wrapper = cast(dict[str, object], values[item_id])
        scalar = cast(dict[str, object], wrapper["value"])
        return scalar["type"]

    assert scalar_type("bool_item") == "boolean"
    assert scalar_type("int_item") == "integer"
    assert scalar_type("float_item") == "float"
    assert scalar_type("str_item") == "string"
    assert cast(dict[str, object], values["points_item"])["kind"] == "points"
    assert cast(dict[str, object], values["scaled_item"])["kind"] == "scaled"
    assert cast(dict[str, object], values["state_item"])["kind"] == "state"


def test_explanation_reports_existing_eligibility_without_recalculation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = EvidenceInventory(
        (
            item("unevaluated_item", "student_1", "score", NativeScalarValue(1)),
            item(
                "ineligible_item",
                "student_2",
                "score",
                NativeScalarValue(2),
                eligibility=EvidenceEligibility.ineligible(
                    policy_id="district_policy",
                    policy_version="1",
                    reason_codes=("eligibility.outside_window",),
                ),
            ),
        )
    )
    monkeypatch.setattr(
        diagnostics,
        "load_authorized_projection_snapshot",
        lambda *args, **kwargs: fake_authorized(inventory),
    )
    result = diagnostics.explain_evidence_diagnostic(
        "workspace",
        PUB_ID,
        CACHE_KEY,
        authorization_purpose_id="grading_import",
        requested_student_ids=(),
        dependencies=dependencies(authorizer=AllowAuthorizer()),
    )
    payload = diagnostics.evidence_explanation_to_dict(result)
    eligibility = cast(list[dict[str, object]], payload["eligibility"])
    assert eligibility[0] == {
        "item_id": "unevaluated_item",
        "status": "unevaluated",
        "policy_id": None,
        "policy_version": None,
        "reason_codes": [],
    }
    assert eligibility[1]["status"] == "ineligible"
    assert eligibility[1]["reason_codes"] == ["eligibility.outside_window"]
    assert result.authorized.stored.snapshot.inventory == inventory
