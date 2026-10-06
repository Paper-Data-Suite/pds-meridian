from pathlib import Path

DOC = Path("docs/architecture/cross-policy-adversarial-acceptance.md")


def test_issue60_architecture_document_records_adversarial_boundaries() -> None:
    text = DOC.read_text(encoding="utf-8")

    for token in (
        "adversarial acceptance != new policy authority",
        "source state != policy consequence",
        "empty != zero",
        "unknown proficiency != low proficiency",
        "publication supersession != reassessment replacement",
        "publication withdrawal != override withdrawal",
        "written Grade result != selected Grade result",
        "teacher override != mutation of base Grade",
        "ReportingSnapshot predecessor/supersession != current-use selection",
        "profile eligibility != weighted mean",
        "intermediate rounding != final rounding",
        "group evidence != student evidence",
        "readiness != academic success",
        "profile_constrained_mean",
        "indeterminate",
        "nonstudent_target",
        "pds-core      0.6.4",
        "scoreform     0.11.0",
        "quillan       0.10.3",
        "pds-concord   0.3.0",
        "pds-core>=0.6.3,<0.7",
        "No seventh environment is created.",
        "all-adapters",
        "scripts/installed_qualification_runner.py",
        "Issue #61",
        "implemented and",
        "qualified.",
    ):
        assert token in text


def test_issue60_active_docs_and_changelog_link_contract() -> None:
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    readme = Path("README").read_text(encoding="utf-8")
    docs_index = Path("docs/README.md").read_text(encoding="utf-8")
    matrix_doc = Path(
        "docs/development/installed-qualification-matrix.md"
    ).read_text(encoding="utf-8")
    documentation_checker = Path(
        "scripts/check_documentation.py"
    ).read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    filename = "cross-policy-adversarial-acceptance.md"
    document = f"docs/architecture/{filename}"

    assert "Issue #60" in changelog
    assert "cross-policy adversarial" in changelog
    assert filename in readme
    assert filename in docs_index
    assert "Issue #60 cross-policy adversarial acceptance" in matrix_doc
    assert document in documentation_checker
    assert document in sdist_checker
    assert "tests/test_issue60_documentation_acceptance.py" in sdist_checker


def test_issue60_documentation_preserves_followup_release_audit_boundary() -> None:
    text = DOC.read_text(encoding="utf-8")

    assert "Issue #61 remains responsible for the release-wide audit" in text
    assert "safe exports" in text
    assert "exact release artifacts" in text
    assert "no official-system authority claims" in text
