"""#126 J1: no invented final acceptance; link to authoritative validator."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/development/issue126-slicej1-a1-a18-ledger.json"
AUDIT = ROOT / "docs/development/issue126-slicej1-full-qualification-audit.md"


def _ledger() -> dict[str, object]:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_j1_all_eighteen_gate_ids_are_exact_and_unique() -> None:
    data = _ledger()
    assert data["issue"] == 126
    entries = data["acceptance"]
    assert [row["id"] for row in entries] == [f"A{i}" for i in range(1, 19)]
    assert len({row["gate"] for row in entries}) == 18


@pytest.mark.parametrize("gate_id", [f"A{i}" for i in range(1, 19)])
def test_every_gate_has_supported_and_explicitly_unresolved_variants(
    gate_id: str,
) -> None:
    data = _ledger()
    row = next(item for item in data["acceptance"] if item["id"] == gate_id)
    assert row["overall_status"] == "partial_source_qualified_not_final_release"
    for name in (
        "gate",
        "qualified_variant",
        "conditional_variant",
        "unsupported_variant",
        "deferred_variant",
    ):
        assert isinstance(row[name], str) and row[name].strip()
    refs = row["evidence_paths"]
    assert refs and len(refs) == len(set(refs))
    for ref in refs:
        assert ref.startswith("tests/test_")
        assert (ROOT / ref).is_file(), f"Missing exact issue evidence: {ref}"


def test_release_and_human_claims_remain_unattested() -> None:
    data = _ledger()
    assert data["provenance"]["meridian_runtime"] == "source_checkout"
    assert data["provenance"]["official_meridian_release_wheel"] == "not_attested"
    for level in ("D2", "D3", "D4"):
        assert "not_attested" in data["d_levels"][level]
    outstanding = data["outstanding_release_gates"]
    assert len(outstanding) >= 8
    for word in (
        "eight_GitHub_CI_jobs_exact_final_PR_SHA",
        "real_saved_teacher_profile",
        "physical_ScoreForm_scan",
        "full_Suite_composition",
    ):
        assert word in outstanding
    assert "Report9_issues_133_134_separate" in outstanding


def test_version_labels_are_source_provenance_not_a_fake_wheel() -> None:
    data = _ledger()
    assert data["environment"] == {
        "pds-core": "0.6.6",
        "scoreform": "0.13.0",
        "quillan": "0.10.6",
        "pds-concord": "0.3.2",
        "meridian_source_label": "0.4.2",
    }
    assert "not_an_official" in data["provenance"]["candidate_built_wheel"]


def test_exact_existing_full_validator_is_the_only_j1_full_gate() -> None:
    validator = (ROOT / "scripts/validate_repository.py").read_text(encoding="utf-8")
    tree = ast.parse(validator)
    # Verify actual Python command lists, not a fragile whitespace spelling of
    # their arguments. An invocation may span multiple formatted source lines.
    commands = tuple(
        tuple(
            item.value
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
            else None
            for item in node.elts
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.List)
    )
    required = (
        ("-m", "pytest"),
        ("-m", "ruff", "check"),
        ("-m", "ruff", "format"),
        ("-m", "mypy"),
        ("scripts/check_documentation.py",),
        ("-m", "build"),
        ("-m", "twine", "check"),
        ("scripts/check_package.py",),
        ("scripts/check_sdist.py",),
        ("-m", "scripts.installed_qualification_runner"),
    )
    for parts in required:
        assert any(
            command[index : index + len(parts)] == parts
            for command in commands
            for index in range(len(command) - len(parts) + 1)
        ), f"Full validator is missing an exact command: {parts!r}"
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        and any(
            isinstance(argument, ast.Constant) and argument.value == "--allow-dirty"
            for argument in node.args
        )
        for node in ast.walk(tree)
    )


def test_expected_ci_matrix_has_exactly_eight_os_python_combinations() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "os: [ubuntu-latest, windows-latest]" in workflow
    assert 'python: ["3.11", "3.12", "3.13", "3.14"]' in workflow
    assert "pull_request:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "scripts/validate_repository.py" in workflow


def test_factual_audit_has_no_release_promotion_or_human_claim() -> None:
    note = AUDIT.read_text(encoding="utf-8")
    assert "133 passed" in note
    assert "temporary" in note
    assert "not a human usability measure" in note
    assert "Do not merge/close" in note
    assert "not an official published release" in note
    for code in ("A1", "A18", "D2", "D3", "D4", "#133", "#134"):
        assert code in note
