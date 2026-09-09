from pathlib import Path

DOC = "docs/architecture/installed-proficiency-signal-export-acceptance.md"
IMPLEMENTED = (
    "#45 installed proficiency and signal-export acceptance without "
    "Concord — implemented"
)
NEXT = "#46 final v0.2.0 audit — implemented; release preparation qualified"


def test_issue45_documentation_is_release_guarded() -> None:
    checker = Path("scripts/check_documentation.py").read_text(
        encoding="utf-8"
    )
    sdist = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    assert DOC in checker
    assert DOC in sdist
    assert "tests/test_issue45_documentation_acceptance.py" in sdist


def test_issue45_handoff_is_current() -> None:
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
        Path("docs/architecture/cross-producer-proficiency-scenarios.md"),
        Path(DOC),
    )
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert IMPLEMENTED in text
        assert NEXT in text


def test_issue45_docs_preserve_installed_acceptance_boundaries() -> None:
    text = Path(DOC).read_text(encoding="utf-8")
    required = (
        "pds-core     0.6.3",
        "scoreform    0.11.0",
        "quillan      0.10.0",
        "no `pds-concord`",
        "CONCORD_WHEEL",
        "student_synthetic_002",
        "reassessment_noncontributing",
        "insufficient_evidence",
        "grouping_signal_set_v1",
        "Core canonical JSON bytes",
        "grouping_signal_csv_v1",
        "Fresh-process persisted-history reload",
        "Producer-source and publication immutability",
        "privacy/minimality",
        "does not introduce a second",
        "Issue #46 owns the final v0.2.0",
    )
    for value in required:
        assert value in text


def test_issue45_is_linked_from_release_docs() -> None:
    for path in (Path("README"), Path("docs/README.md")):
        text = path.read_text(encoding="utf-8")
        assert "installed-proficiency-signal-export-acceptance.md" in text

    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    assert (
        "Issue #45 installed proficiency and signal-export acceptance "
        "without Concord"
    ) in changelog
