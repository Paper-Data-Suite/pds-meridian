from __future__ import annotations

from pathlib import Path

from scripts import check_package, check_sdist

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT = REPO_ROOT / "docs/development/v0.3.0-release-audit.md"


def test_issue61_final_inventory_repetition_is_complete_and_unchanged() -> None:
    audit = AUDIT.read_text(encoding="utf-8")

    expected = (
        "Final inventory pass: **CONFORMS — 2026-10-06**",
        "`pds-core` | `v0.6.4` | `152d1c65064c4f8fe55249ff2ca3379d7c4d6ccb`",
        "`pds-scoreform` | `v0.12.0` | `5055829dd4e99b201d271bf1e35d8dd5bcbcd121`",
        "`pds-quillan` | `v0.10.5` | `b6cda6ecb23fbb7059ec7983e659afbd5d208d5e`",
        "`pds-concord` | `v0.3.0` | `fe37f9fca3dd7894a86f5a5c4e74bbe09c1e84ed`",
        "`pds-meridian` | `v0.2.0` | `027a35c45fcd7160d87f9ebed3b8400b4d91a2fc`",
        "`pds-vitrine` | `v0.3.0` | `27d28933c645cea1d57b5504362e8798eacee8fe`",
        (
            "`pds-paper-data-suite` | `v0.1.0` | "
            "`9c17888312a6346754d92a5393db91b3a959fc2b`"
        ),
        "`pds-portia` | no stable release",
        "`pds-clavis` | no stable release",
    )
    for item in expected:
        assert item in audit


def test_issue61_substantive_audit_closes_at_zero_blockers() -> None:
    audit = AUDIT.read_text(encoding="utf-8")

    assert (
        "Status: **RELEASE CANDIDATE PREPARED — QUALIFICATION PENDING**"
        in audit
    )
    assert "Substantive blocker count: **0**" in audit
    assert "Substantive audit status: **CONFORMS**" in audit
    assert "Release-preparation authorization: **AUTHORIZED**" in audit
    assert (
        "Version promotion to `0.3.0`: **COMPLETED**"
        in audit
    )
    assert "Tag/publication authorization: **PENDING**" in audit
    assert "Fresh-download verification: **PENDING**" in audit


def test_issue61_release_preparation_promotes_candidate_version() -> None:
    version = (REPO_ROOT / "meridian/_version.py").read_text(encoding="utf-8")

    assert '__version__: Final[str] = "0.3.0"' in version
    assert check_package.EXPECTED_VERSION == "0.3.0"
    assert check_sdist.EXPECTED_VERSION == "0.3.0"


def test_issue61_candidate_validator_owns_full_artifact_gate() -> None:
    validator = (REPO_ROOT / "scripts/validate_repository.py").read_text(
        encoding="utf-8"
    )

    for required in (
        '"pytest"',
        '"ruff"',
        '"mypy"',
        '"scripts/check_documentation.py"',
        '"build"',
        '"twine"',
        '"scripts/check_package.py"',
        '"scripts/check_sdist.py"',
        '"scripts.installed_qualification_runner"',
        '"diff"',
        '"--check"',
    ):
        assert required in validator

    assert validator.count('"scripts.installed_qualification_runner"') == 1
    assert validator.count('"scripts/check_package.py"') == 1
    assert validator.count('"scripts/check_sdist.py"') == 1


def test_issue61_repository_only_audit_stays_out_of_candidate_sdist() -> None:
    member = "docs/development/v0.3.0-release-audit.md"
    manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

    assert f"exclude {member}" in manifest
    assert member in check_sdist.FORBIDDEN_EXACT_MEMBERS
    assert member not in check_sdist.REQUIRED_MEMBERS


def test_issue61_release_preparation_worklist_is_explicit() -> None:
    audit = AUDIT.read_text(encoding="utf-8")

    for required in (
        "Release-preparation worklist",
        "promote the authoritative package version from `0.2.0` to `0.3.0`",
        "refresh the package summary",
        "refresh current-development README release/baseline wording",
        "create v0.3.0 release notes",
        "move CHANGELOG content into a dated `0.3.0` release section",
        "update package/sdist/version guards to expect `0.3.0`",
        "run the authoritative candidate validator",
        "record final source and artifact SHA-256 values",
    ):
        assert required in audit
