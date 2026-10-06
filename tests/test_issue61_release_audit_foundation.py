from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT = Path("docs/development/v0.3.0-release-audit.md")


def test_issue61_release_audit_freezes_starting_source_and_inventory() -> None:
    audit = (REPO_ROOT / AUDIT).read_text(encoding="utf-8")

    expected = (
        "Status: **IN PROGRESS — PRE-PROMOTION**",
        "5671883e41977f60ae235e3584a51cbdf5768734",
        "87a44e6d31feeceead0bfa7bc1a87306cf5278da",
        "`pds-core` | direct runtime / six-matrix baseline | `v0.6.4`",
        "`pds-scoreform` | direct optional producer reader | `v0.12.0`",
        "`pds-quillan` | direct optional producer reader | `v0.10.5`",
        "`pds-concord` | direct optional producer reader | `v0.3.0`",
        "`pds-vitrine` | ecosystem coexistence only | `v0.3.0`",
        "`pds-paper-data-suite` | ecosystem coexistence only | `v0.1.0`",
        "`pds-portia` | no released-artifact qualification | no stable release",
        "`pds-clavis` | no Meridian release dependency | no stable release",
        "Substantive blocker count: **PENDING**",
        "The full authoritative latest-release validator: **CONFORMS — attempt 2**",
        "Authoritative validator attempt 1 — NON-BLOCKING RELEASE CORRECTION",
        "3065 passed",
        "22 skipped",
        "4 failed",
        "Authoritative validator attempt 2 — CONFORMS",
        "6823e3554093df49ef10b1fa95e7de14c245e931",
        "3069 passed",
        "22 skipped",
        "Issue #96 prepared installed qualification passed.",
        "Calculation-state and silent-zero audit — CONFORMS",
        "Zero is therefore a policy consequence, not a fallback",
        "Selection and authority audit — CONFORMS",
        "selection_basis=\"explicit\"",
        "relationship_basis=\"explicit\"",
        "Override authority and source binding audit — CONFORMS",
        "does not float to a later result revision",
        "Withdrawal is itself exact authority, not deletion.",
        "Historical explanation and provenance audit — CONFORMS",
        "selection=\"revision\"",
        "does not substitute the current activation or policy revision.",
        "ReportingSnapshot current-use audit — CONFORMS",
        "Predecessor metadata does not move current use.",
        "Current-use selection does not create Grade authority.",
        "Export and source-mutation audit — CONFORMS",
        "Teacher approval is a byte-boundary.",
        "local export provenance, not evidence that a gradebook",
        "Privacy and source-custody audit — CONFORMS",
        "Protected projection-cache access remains authorization-first.",
        "Reporting v1 remains teacher-only.",
        "do not embed producer-private payload bytes",
        "Arithmetic, denominator, and rounding audit — CONFORMS AFTER CORRECTION",
        "conventional ambient Decimal precision leak",
        "Status: **CONFORMS AFTER CORRECTION**",
        "Storage-path and operational safety audit — CONFORMS",
        "Core module operations remain read-only.",
        "Installed dependency isolation remains exactly the six established matrices",
        "Interoperability and ecosystem-coexistence audit — CONFORMS",
        "This spot check does not satisfy the required final inventory repetition gate",
        "Portia and Clavis still have no stable release.",
        "Version promotion to `0.3.0`: **NOT AUTHORIZED**",
    )
    for item in expected:
        assert item in audit


def test_issue61_release_audit_is_repository_only() -> None:
    member = AUDIT.as_posix()
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    sdist_checker = (REPO_ROOT / "scripts/check_sdist.py").read_text(
        encoding="utf-8"
    )

    assert f"exclude {member}" in manifest
    assert member in sdist_checker


def test_issue61_documentation_checker_requires_release_audit() -> None:
    checker = (REPO_ROOT / "scripts/check_documentation.py").read_text(
        encoding="utf-8"
    )

    assert 'Path("docs/development/v0.3.0-release-audit.md")' in checker
    assert "Substantive blocker count: **PENDING**" in checker
    assert (
        "full authoritative latest-release validator: **CONFORMS — attempt 2**"
        in checker
    )


def test_issue61_release_audit_does_not_promote_package_version() -> None:
    version_file = (REPO_ROOT / "meridian/_version.py").read_text(encoding="utf-8")

    assert '__version__: Final[str] = "0.2.0"' in version_file
    assert '__version__: Final[str] = "0.3.0"' not in version_file
