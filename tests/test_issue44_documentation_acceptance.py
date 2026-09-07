from pathlib import Path

DOC = "docs/architecture/cross-producer-proficiency-scenarios.md"
IMPLEMENTED = (
    "#44 ScoreForm/Quillan/Concord cross-producer proficiency "
    "scenarios — implemented"
)
NEXT = (
    "#45 installed proficiency and signal-export acceptance without "
    "Concord — next"
)


def test_issue44_documentation_is_release_guarded() -> None:
    checker = Path("scripts/check_documentation.py").read_text(
        encoding="utf-8"
    )
    sdist = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    assert DOC in checker
    assert DOC in sdist
    assert "tests/test_issue44_documentation_acceptance.py" in sdist


def test_issue44_handoff_is_current() -> None:
    targets = (
        Path("README"),
        Path("docs/README.md"),
        Path(
            "docs/architecture/"
            "teacher-eligibility-proficiency-planning-workflows.md"
        ),
        Path(
            "docs/architecture/"
            "proficiency-planning-export-explanation-traces.md"
        ),
        Path("docs/architecture/proficiency-attention-summaries.md"),
    )
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert IMPLEMENTED in text
        assert NEXT in text


def test_issue44_docs_preserve_cross_producer_boundaries() -> None:
    text = Path(DOC).read_text(encoding="utf-8")
    required = (
        "same numeric value\n    != same native scale",
        "selected_response_state",
        "returned_without_full_review",
        "excluded: nonstudent_target",
        "NativePointValue",
        "NativeScaledValue",
        "blocking_native_state",
        "Core publication lifecycle remains canonical.",
        "Historical trace selection never substitutes",
        "No grouping circularity",
        "GroupMembership",
        "Producer-neutral runtime and dependency direction",
        "pds-core>=0.6.3,<0.7",
        "Synthetic-data boundary",
        "#45 installed proficiency and signal-export acceptance",
    )
    for value in required:
        assert value in text


def test_issue44_is_linked_from_root_and_documentation_index() -> None:
    for path in (Path("README"), Path("docs/README.md")):
        text = path.read_text(encoding="utf-8")
        assert "cross-producer-proficiency-scenarios.md" in text

    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    assert (
        "Issue #44 ScoreForm/Quillan/Concord cross-producer "
        "proficiency scenarios"
    ) in changelog
