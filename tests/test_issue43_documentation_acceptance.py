from pathlib import Path

DOC = "docs/architecture/proficiency-attention-summaries.md"


def test_issue43_documentation_is_release_guarded() -> None:
    checker = Path("scripts/check_documentation.py").read_text(
        encoding="utf-8"
    )
    sdist = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    assert DOC in checker
    assert DOC in sdist
    assert "tests/test_issue43_documentation_acceptance.py" in sdist


def test_issue43_handoff_is_current() -> None:
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
        Path(DOC),
    )
    implemented = (
        "#43 Meridian proficiency attention summaries — implemented"
    )
    issue44 = (
        "#44 ScoreForm/Quillan/Concord cross-producer proficiency "
        "scenarios — implemented"
    )
    next_item = (
        "#45 installed proficiency and signal-export acceptance without "
        "Concord — implemented"
    )
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert implemented in text
        assert issue44 in text
        assert next_item in text
        assert (
            "#46 final v0.2.0 audit — implemented; "
            "release preparation qualified"
        ) in text


def test_issue43_docs_preserve_required_boundaries() -> None:
    text = Path(DOC).read_text(encoding="utf-8")
    for required in (
        "mechanically observable absence != teacher action required",
        "Protected-evidence authorization boundary",
        "AuthorizedProjectionSnapshot",
        "meridian_export_pending",
        "Successful empty evaluation remains distinct from",
        "readiness absent",
        (
            "Low proficiency is never translated into attention "
            "severity or risk."
        ),
        "producer/Concord absence",
    ):
        assert required in text
