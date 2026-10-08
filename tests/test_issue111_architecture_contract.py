"""Slice 1 guards: record *existing* boundaries without changing runtime policy."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/architecture/producer-reader-contract-compatibility.md"

PRODUCERS = {
    "scoreform": ("scoreform", "0.12.1", "scoreform_academic_result_manifest_v1"),
    "quillan": ("quillan", "0.10.5", "quillan_academic_result_manifest_v1"),
    "concord": ("pds-concord", "0.3.0", "concord_academic_result_manifest_v1"),
}


def _source(producer: str) -> str:
    return (ROOT / "meridian" / f"{producer}_adapter.py").read_text(encoding="utf-8")


def test_architecture_distinguishes_five_authorities() -> None:
    text = DOC.read_text(encoding="utf-8")
    for required in (
        "Producer distribution/version",
        "Manifest contract",
        "Public reader contract",
        "Meridian projection contract",
        "Exact qualification artifact",
        "Exact release artifacts prove what Meridian tested.",
        "Reader contracts determine what Meridian may consume.",
        "ProjectionIdentity",
        "legacy",
    ):
        assert required in text


def test_existing_reader_interfaces_and_versions_are_audited() -> None:
    document = DOC.read_text(encoding="utf-8")
    for producer, (distribution, version, manifest_contract) in PRODUCERS.items():
        source = _source(producer)
        tree = ast.parse(source)
        reader_imports = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == f"{producer}.academic_result_reader"
        ]
        assert reader_imports
        assert any(
            alias.name == "read_academic_result_manifest"
            for node in reader_imports for alias in node.names
        )
        assert "supported_producer_reader_versions=" in source
        assert repr(version) in source or f'"{version}"' in source
        assert manifest_contract in source
        expected_tokens = (
            distribution,
            version,
            manifest_contract,
            f"{producer}_academic_result_reader_v1",
        )
        for token in expected_tokens:
            assert token in document


def test_concord_extra_helper_dependency_is_not_hidden() -> None:
    tree = ast.parse(_source("concord"))
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "concord.academic_result_manifest"
        and any(alias.name == "derive_manifest_capabilities" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert "derive_manifest_capabilities" in DOC.read_text(encoding="utf-8")


def test_projection_identity_preserves_exact_distribution_version() -> None:
    source = (ROOT / "meridian" / "adapters.py").read_text(encoding="utf-8")
    assert "producer_reader_distribution" in source
    assert "producer_reader_version" in source
    assert "projection_identity_from_descriptor" in source
    assert "resolve_producer_reader_version" in source
