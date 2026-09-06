from __future__ import annotations

from pathlib import Path

DOC = "docs/architecture/proficiency-planning-export-explanation-traces.md"


def test_issue42_documentation_is_release_guarded() -> None:
    documentation_checker = Path("scripts/check_documentation.py").read_text(
        encoding="utf-8"
    )
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    assert DOC in documentation_checker
    assert DOC in sdist_checker
    assert "issue #42 — implemented" in documentation_checker
    assert "issue #43 — next" in documentation_checker


def test_issue42_status_is_consistent_across_release_docs() -> None:
    paths = (
        Path("README"),
        Path("docs/README.md"),
        Path("CHANGELOG.md"),
        Path(DOC),
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "#42" in text or "Issue #42" in text

    root = Path("README").read_text(encoding="utf-8")
    docs = Path("docs/README.md").read_text(encoding="utf-8")
    architecture = Path(DOC).read_text(encoding="utf-8")

    assert (
        "#42 proficiency and planning-export explanation/trace views — implemented"
        in root
    )
    assert "issue #42 — implemented" in docs
    assert "#43 Meridian proficiency attention summaries — next" in root
    assert "issue #43 — next" in docs
    assert "authorized_detail" in architecture
    assert "exported band != derived band" in architecture
