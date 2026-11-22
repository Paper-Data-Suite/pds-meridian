"""Read-only #126 I3B provenance census; NOT a release certification.

This script inspects only Python distribution metadata and public imported module
files. It never opens a PDS workspace, saves an academic decision or asserts
that source checkout is an installed Meridian release wheel.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

EXPECTED = (
    ("pds-core", "pds_core", "0.6.6", None),
    ("scoreform", "scoreform", "0.13.0", "academic_result_reader.py"),
    ("quillan", "quillan", "0.10.6", "academic_result_reader.py"),
    ("pds-concord", "concord", "0.3.2", "academic_result_reader.py"),
)


class ReleaseEvidenceError(RuntimeError):
    """A distribution/import claim cannot be grounded in the installed files."""


def editable_direct_url(raw: str | None) -> bool:
    """Fail closed for unparseable editable-origin metadata."""
    if raw is None:
        return False
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ReleaseEvidenceError("Unparseable direct_url.json metadata") from exc
    if not isinstance(parsed, dict):
        raise ReleaseEvidenceError("Invalid direct_url.json object")
    info = parsed.get("dir_info", {})
    if not isinstance(info, dict):
        raise ReleaseEvidenceError("Invalid direct_url.json dir_info")
    editable = info.get("editable", False)
    if not isinstance(editable, bool):
        raise ReleaseEvidenceError("Invalid editable origin flag")
    return editable


def classify_meridian_origin(imported_file: Path, repo: Path) -> str:
    """Classify the actual *module*, never the enclosing repository's .venv."""
    module = imported_file.resolve(strict=True)
    source = (repo / "meridian" / "__init__.py").resolve(strict=True)
    return "source_checkout" if module == source else "other_origin_unqualified"


def release_claims(*, meridian_origin: str) -> dict[str, str]:
    """Evidence levels are *not* inferred from successful imports alone."""
    return {
        "D0": "normative_contract_review_required",
        "D1": "targeted_source_tests_require_runner_result",
        "D2_new_core_ui": "not_attested_by_core_0_6_6",
        "D3_official_meridian_wheel": "not_attested",
        "D4_full_suite_composition": "not_attested",
        "human_classroom": "not_attested",
        "physical_scoreform_scan": "not_attested",
        "real_saved_teacher_profile": "not_attested",
        "A18_full_release_ci": "not_attested",
        "meridian_import": meridian_origin,
    }


def _distribution_ownership(
    distribution_name: str,
    import_package: str,
    expected_version: str,
    relative_file: str | None,
) -> dict[str, Any]:
    dist = metadata.distribution(distribution_name)
    if dist.version != expected_version:
        raise ReleaseEvidenceError(
            f"{distribution_name} version mismatch; expected {expected_version}"
        )
    if editable_direct_url(dist.read_text("direct_url.json")):
        raise ReleaseEvidenceError(
            f"{distribution_name} is editable, not wheel-owned evidence"
        )
    module_name = import_package
    if relative_file is not None:
        module_name = f"{import_package}.{relative_file.removesuffix('.py')}"
    imported = importlib.import_module(module_name)
    imported_path = getattr(imported, "__file__", None)
    if not isinstance(imported_path, str):
        raise ReleaseEvidenceError(f"{module_name} lacks a file origin")
    actual = Path(imported_path).resolve(strict=True)
    relpath = f"{import_package}/{relative_file or '__init__.py'}"
    expected = Path(str(dist.locate_file(relpath))).resolve(strict=True)
    if actual != expected:
        raise ReleaseEvidenceError(
            f"{distribution_name} imported module differs from distribution-owned file"
        )
    if not actual.is_relative_to(Path(sys.prefix).resolve(strict=True)):
        raise ReleaseEvidenceError(
            f"{distribution_name} reader is not in the active installed environment"
        )
    if relative_file is not None and not callable(
        getattr(imported, "read_academic_result_manifest", None)
    ):
        raise ReleaseEvidenceError(
            f"{distribution_name} public academic-result reader is unavailable"
        )
    return {
        "distribution": distribution_name,
        "version": dist.version,
        "reader_or_package_sha256": hashlib.sha256(actual.read_bytes()).hexdigest(),
        "module": module_name,
        "origin": "installed_distribution_owned_noneditable",
        "hash_kind": "installed_module_file_not_original_wheel_archive",
    }


def collect_evidence(repo: Path) -> dict[str, Any]:
    root = repo.resolve(strict=True)
    if not (root / "pyproject.toml").is_file():
        raise ReleaseEvidenceError("Meridian pyproject.toml is unavailable")
    installed = {
        name: _distribution_ownership(name, package, ver, relative)
        for name, package, ver, relative in EXPECTED
    }
    imported = importlib.import_module("meridian")
    module_file = getattr(imported, "__file__", None)
    if not isinstance(module_file, str):
        raise ReleaseEvidenceError("Meridian has no import origin")
    meridian_origin = classify_meridian_origin(Path(module_file), root)
    if meridian_origin != "source_checkout":
        raise ReleaseEvidenceError(
            "I3B is the source-checkout audit; a different Meridian origin "
            "requires a separate qualified installed-wheel matrix"
        )
    for name in (
        "meridian.menu_teacher_evidence",
        "meridian.menu_teacher_corrections",
        "meridian.menu_teacher_correction_decision",
    ):
        module = importlib.import_module(name)
        module_file = getattr(module, "__file__", None)
        if not isinstance(module_file, str):
            raise ReleaseEvidenceError(
                "Meridian teacher menu module has no file origin"
            )
        actual = Path(module_file).resolve(strict=True)
        expected = (root / "meridian" / (name.rsplit(".", 1)[-1] + ".py")).resolve(
            strict=True
        )
        if actual != expected:
            raise ReleaseEvidenceError(
                "Meridian teacher menu import differs from checkout"
            )
    try:
        version = metadata.version("pds-meridian")
    except metadata.PackageNotFoundError:
        version = "not_installed_as_distribution"
    return {
        "schema_version": 1,
        "purpose": "issue126_i3b_read_only_boundary_inventory",
        "synthetic_only": True,
        "installed": installed,
        "meridian": {
            "distribution_version_label": version,
            "source_origin": meridian_origin,
            "official_wheel_attested": False,
        },
        "evidence_levels": release_claims(meridian_origin=meridian_origin),
        "manual_acceptance_status": "not_executed_by_this_script",
        "requires_separate_release_evidence": [
            "published_core_header_capability",
            "official_noneditable_meridian_wheel_artifact_and_hash",
            "full_suite_launcher_composition",
            "saved_teacher_profile_and_real_teacher_navigation",
            "physical_scoreform_scan",
            "final_a1_a18_ledger_and_eight_ci_jobs",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = collect_evidence(args.repo)
    except (ReleaseEvidenceError, OSError, ImportError) as exc:
        print(f"I3B EVIDENCE ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2))
    print("I3B SOURCE-ORIGIN/INSTALLED-READERS PROVENANCE: VERIFIED")
    print("I3B D2 NEW CORE / D3 OFFICIAL MERIDIAN / D4 SUITE / MANUAL: NOT ATTESTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
