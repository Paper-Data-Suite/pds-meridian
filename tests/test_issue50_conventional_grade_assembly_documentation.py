from pathlib import Path


def test_issue50_assembly_architecture_freezes_authority_and_state_boundaries() -> None:
    text = Path("docs/architecture/conventional-grade-calculation.md").read_text(
        encoding="utf-8"
    )
    required = (
        "Storage-aware exact input assembly",
        "ConventionalGradeWorkEvidenceSpec",
        "AuthorizedProjectionSnapshot",
        "resolve_current_evidence_eligibility()",
        "resolve_current_reassessment()",
        "multiple_operative_reassessment_snapshots",
        "Nonstudent evidence remains",
        "unresolved\n> invalid\n> unavailable",
        "cannot collapse to `missing`",
        "It performs no writes",
    )
    for token in required:
        assert token in text
