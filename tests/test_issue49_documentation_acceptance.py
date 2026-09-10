from __future__ import annotations

from pathlib import Path

from meridian.grade_policy import (
    GRADE_POLICY_RECORD_TYPE,
    GradePolicyReference,
    GradePolicyRevision,
)
from meridian.grade_policy_activation import (
    GRADE_POLICY_ACTIVATION_RECORD_TYPE,
    GradePolicyActivationDecision,
    GradePolicyActivationReference,
)
from meridian.grade_policy_activation_storage import (
    GradePolicyActivationResolution,
)
from meridian.grade_policy_storage import (
    GradePolicyCurrentSelection,
    StoredGradePolicyRevision,
)

ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT / "docs/architecture/grade-policy-models-storage-and-activation.md"


def test_issue49_architecture_document_is_indexed_and_preserves_boundaries() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    required = (
        "GradeItemRevision.weighting metadata != executable Grade policy",
        "GradePolicy family",
        "selected revision within that family",
        "activated GradePolicy for an Academic Period",
        "missing or unresolved state != numeric zero",
        "policy family's current revision changes",
        "!= active period policy changes",
        "unconfigured",
        "deactivated",
        "activated",
        "#50 conventional Grade calculation",
    )
    for token in required:
        assert token in text


def test_issue49_repository_overviews_name_the_implemented_boundary() -> None:
    readme = (ROOT / "README").read_text(encoding="utf-8")
    docs = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    for text in (readme, docs, changelog):
        assert "Issue #49" in text
        assert "Grade policy" in text or "Grade-policy" in text
    assert "grade-policy-models-storage-and-activation.md" in docs


def test_issue49_documentation_checker_requires_the_new_contract() -> None:
    checker = (ROOT / "scripts/check_documentation.py").read_text(encoding="utf-8")
    assert "grade-policy-models-storage-and-activation.md" in checker
    assert "GradePolicy family current != GradePolicy activation" in checker
    assert "missing or unresolved state != numeric zero" in checker


def test_policy_and_activation_are_distinct_public_record_families() -> None:
    assert GRADE_POLICY_RECORD_TYPE == "meridian_grade_policy"
    assert GRADE_POLICY_ACTIVATION_RECORD_TYPE == "meridian_grade_policy_activation"
    assert GradePolicyRevision is not GradePolicyActivationDecision
    assert GradePolicyReference is not GradePolicyActivationReference


def test_family_current_and_period_activation_have_distinct_models() -> None:
    assert GradePolicyCurrentSelection.__name__ == "GradePolicyCurrentSelection"
    assert GradePolicyActivationResolution.__name__ == "GradePolicyActivationResolution"
    assert StoredGradePolicyRevision.__name__ == "StoredGradePolicyRevision"


def test_issue49_does_not_claim_grade_calculation_runtime() -> None:
    readme = (ROOT / "README").read_text(encoding="utf-8")
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    assert "does not yet calculate conventional Grades" in readme
    assert "Issue #49 deliberately does not implement:" in architecture
    assert "- conventional Grade calculation;" in architecture
