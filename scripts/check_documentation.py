"""Validate Meridian documentation links, status, decisions, and text hygiene."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = (
    Path("README"),
    Path("Security.md"),
    Path("CHANGELOG.md"),
    Path("docs/README.md"),
    Path("docs/development/package-foundation.md"),
    Path("docs/development/synthetic-data.md"),
    Path("docs/development/v0.1.1-release-audit.md"),
    Path("docs/architecture/core-v0.6-publication-ingestion.md"),
    Path("docs/architecture/typed-evidence-inventory.md"),
    Path("docs/architecture/adapter-interface-and-registry.md"),
    Path("docs/architecture/catalog-discovery-and-canonical-verification.md"),
    Path("docs/architecture/exact-projection-snapshots-and-cache.md"),
    Path("docs/architecture/evidence-inventory-and-diagnostics.md"),
    Path("docs/architecture/scoreform-adapter.md"),
    Path("docs/architecture/quillan-adapter.md"),
    Path("docs/architecture/concord-adapter.md"),
    Path("docs/architecture/cross-producer-synthetic-ingestion.md"),
    Path("docs/architecture/attempt-selection-policy-and-decisions.md"),
    Path("docs/architecture/reassessment-and-replacement-relationships.md"),
    Path("docs/architecture/evidence-eligibility-decisions.md"),
    Path("docs/architecture/grade-items-and-canonical-storage.md"),
    Path(
        "docs/architecture/"
        "grade-item-membership-and-academic-period-assignment.md"
    ),
    Path("docs/decisions/README.md"),
    Path(
        "docs/decisions/"
        "0001-policy-driven-standards-proficiency-and-grade-calculation.md"
    ),
    Path("docs/decisions/0002-provenance-bound-report-snapshots-and-subscriptions.md"),
    Path("docs/decisions/0003-consumer-side-producer-adapters.md"),
    Path(
        "docs/decisions/"
        "0004-v02-evidence-policy-proficiency-and-planning-export-architecture.md"
    ),
    Path("docs/decisions/amendments/0001-core-v0.6-ingestion-reconciliation.md"),
    Path("docs/decisions/amendments/0002-core-v0.6-ingestion-reconciliation.md"),
)
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
REQUIRED_TEXT = {
    Path("CHANGELOG.md"): (
        "## Unreleased",
        "Canonical immutable reassessment policy and student relationship decision",
        "Canonical immutable attempt-selection policy and student decision records",
        "Canonical immutable evidence-eligibility decision records",
        "Immutable Meridian Grade Item",
        "## 0.1.1 — 2026-08-18",
        "canonical serialized",
        "before protected snapshot bytes are opened",
        "Release qualification",
    ),
    Path("README"): (
        "0.1.1",
        "pds-core>=0.6,<0.7",
        "Package installation alone does not enable publication ingestion.",
        "Discovery is not authorization.",
        "producer-owned public manifest contract or reader",
        "meridian.evidence",
        "meridian.adapters",
        "meridian.ingestion",
        "meridian.diagnostics",
    ),
    Path("docs/README.md"): (
        "Four accepted ADRs govern the repository:",
        "ADR 0004",
        "pds-core>=0.6.1,<0.7",
        "foundation audit and v0.1.1 release — complete",
        "Grade Item creation != membership",
        "membership != evidence eligibility",
        "issue #27 — implemented",
        "issue #28 — implemented",
        "issue #29 — implemented",
        "issue #30 — implemented",
        "issue #31 — implemented",
        "issue #32 — next",
        "projection != canonical eligibility decision",
    ),
    Path("docs/architecture/core-v0.6-publication-ingestion.md"): (
        "Canonical verification precedes producer parsing",
        "Failure taxonomy",
        "Producer readiness matrix",
        "Concord v0.2.0",
    ),
    Path("docs/architecture/typed-evidence-inventory.md"): (
        "Validity, eligibility, and selection are separate questions.",
        "NativeStateValue",
        "do not flatten",
        "returned_without_full_review",
    ),
    Path("docs/architecture/adapter-interface-and-registry.md"): (
        "exact typed equality",
        "adapters.reader_unavailable",
        "adapters.projection_contract_violation",
        "Discovery is not authorization.",
    ),
    Path("docs/architecture/catalog-discovery-and-canonical-verification.md"): (
        "Catalog rows are candidate observations only.",
        "Authorization precedes manifest access.",
        "PreparedPublicationInvocation",
        "ingestion.canonical_state_changed",
    ),
    Path("docs/architecture/exact-projection-snapshots-and-cache.md"): (
        "cache.projection_nondeterministic",
        "read_projection_cache",
        "authorization_scope_digest",
        "before opening snapshot bytes",
        "canonical serialized inventory bytes",
        "Historical immutability",
        "report snapshots",
        "Concord v0.2.0",
    ),
    Path("docs/architecture/evidence-inventory-and-diagnostics.md"): (
        "Catalog rows remain observations rather than canonical authority.",
        "diagnostics.authorization_provider_required",
        "read_projection_cache",
        "EvidenceEligibility",
        "Concord v0.2.0",
    ),
    Path("docs/architecture/concord-adapter.md"): (
        "concord.academic_result",
        "pds-concord==0.2.0",
        "Group versus student evidence",
        "manifest authorization != Artifact authorization",
        'EvidenceEligibility(status="unevaluated")',
    ),
    Path("docs/architecture/cross-producer-synthetic-ingestion.md"): (
        "producer-neutral != producer-semantic flattening",
        "ScoreForm attempt != Concord Score history",
        "native zero != non-score state",
        "Academic Period definition != ingestion-time Grade-period assignment",
        "Authorization isolation",
        "verified producer-neutral ingestion foundation",
    ),
    Path("docs/architecture/grade-items-and-canonical-storage.md"): (
        "stable grade_item_id",
        "GradeItemWorkReference",
        "issue #28 now implements that separate record/storage family",
        "relative_weight: Decimal | null",
        "current.json",
        "revision_sha256",
        "Grade Item creation != membership",
    ),
    Path(
        "docs/architecture/"
        "grade-item-membership-and-academic-period-assignment.md"
    ): (
        "GradeItemAcademicPeriodAssignment",
        "GradeItemMembershipDecision",
        "no decision != excluded",
        "publication appears -X-> Grade Item membership",
        "highest membership revision -X-> current membership",
        "pds-core>=0.6,<0.7",
        "membership != evidence eligibility",
        "Issue #29 now implements the separate canonical evidence-eligibility",
    ),
    Path("docs/architecture/evidence-eligibility-decisions.md"): (
        "EvidenceSourceReference",
        "`item_id` alone is not immutable source identity",
        "projection != canonical eligibility decision",
        "membership != evidence eligibility",
        "eligibility != attempt selection",
        "included_source_withdrawn",
        "pds-core>=0.6,<0.7",
        "Possession of a cache key, digest, path, or item ID is not authorization.",
        "attempt selection != reassessment",
    ),
    Path("docs/architecture/attempt-selection-policy-and-decisions.md"): (
        "AttemptObservationReference",
        "selection_basis = \"explicit\"",
        "operative_included == true",
        "ScoreForm v0.10.0 -> applicable",
        "Quillan v0.9.0   -> not_applicable",
        "Concord v0.2.0   -> not_applicable",
        "higher score -X-> preferred attempt",
        "attempt selection != reassessment",
        "pds-core>=0.6,<0.7",
    ),
    Path("docs/architecture/reassessment-and-replacement-relationships.md"): (
        "AttemptSelectionDecisionReference",
        'relationship_basis = "explicit"',
        "attempt selection != reassessment",
        "reassessment != native-value mapping",
        "selected_none",
        "single_selected",
        "no_decision",
        "score_supersedes",
        "Quillan v0.9.0",
        "Concord v0.2.0",
        "pds-core>=0.6,<0.7",
    ),
    Path("docs/decisions/0003-consumer-side-producer-adapters.md"): (
        "Status:** Accepted",
        "Unsupported states fail closed",
        "producer package -X-> pds-meridian",
    ),
    Path(
        "docs/decisions/"
        "0004-v02-evidence-policy-proficiency-and-planning-export-architecture.md"
    ): (
        "Status:** Accepted",
        "publication validity != evidence eligibility",
        "producer-native result != Meridian proficiency category",
        "absence != zero",
        "pds-core>=0.6.1,<0.7",
        "Meridian planning export -X-> Concord runtime",
        "No automatic signal export is permitted.",
        "One Meridian v0.2 derivation/export uses one explicitly selected academic",
        "v0.2 stops before Grade preview and issued reporting",
    ),
    Path("docs/development/package-foundation.md"): (
        "0.1.1",
        "paper_data_suite.modules",
        "paper_data_suite.publication_producers",
        "meridian.diagnostics",
        "upstream dependency-direction audit",
        "source-distribution boundary",
        "all-adapter coexistence",
    ),
    Path("docs/development/synthetic-data.md"): (
        "real student",
        "synthetic_class_2026",
        "Producer-contract fixtures",
    ),
    Path("docs/development/v0.1.1-release-audit.md"): (
        "Substantive audit: **passed**",
        "643608680e7ae7f3da2bc34a53e6923b568a76e7",
        "b3715a2be0d3ddbefe5c0fb489417f407fbf4dc9",
        "275/275",
        "release blocker",
        "Release-candidate version: `0.1.1`",
        "Clean committed release-candidate qualification",
        "f19f5149ca6d700c27c085abff985669be1cc418",
        "277/277",
        "Pull request and GitHub Actions qualification",
        "PR #64",
        "32212895904",
        "905addfdfa4a8cdc874b6263929b2ac99360bad7",
        "all eight GitHub Actions matrix jobs",
        "final docs-only PR",
    ),
}
STALE_ACTIVE_PHRASES = (
    "currently contains architectural and repository documentation only",
    "does not yet contain a Meridian Python package",
    "No application development workflow has been established yet",
    "The dependency declaration will be introduced by the package-foundation issue",
)
FORBIDDEN_PRIVACY_MARKERS = (
    "C:\\Users\\",
    "/home/",
    "student@example.com",
    "teacher@example.com",
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def documentation_files() -> tuple[Path, ...]:
    discovered = {
        Path("README"),
        Path("Security.md"),
        Path("CHANGELOG.md"),
        *(path.relative_to(ROOT) for path in (ROOT / "docs").rglob("*.md")),
    }
    return tuple(sorted(discovered, key=lambda path: path.as_posix()))


def check_expected() -> None:
    for relative in EXPECTED:
        if not (ROOT / relative).is_file():
            fail(f"missing expected file: {relative.as_posix()}")
    if (ROOT / "verify_issue_4.py").exists():
        fail("verify_issue_4.py must be replaced by generalized validation tooling")


def check_required_text() -> None:
    for relative, needles in REQUIRED_TEXT.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                fail(f"{relative.as_posix()} is missing required text: {needle!r}")


def check_links() -> None:
    failures: list[str] = []
    root = ROOT.resolve()
    for relative in documentation_files():
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        for target in LINK.findall(text):
            target = target.strip()
            if not target or target.startswith(
                ("http://", "https://", "mailto:", "#")
            ):
                continue
            clean = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not clean:
                continue
            resolved = (path.parent / clean).resolve()
            if not resolved.is_relative_to(root):
                failures.append(
                    f"{relative.as_posix()}: link escapes repository: {target}"
                )
            elif not resolved.exists():
                failures.append(
                    f"{relative.as_posix()}: missing link target: {target}"
                )
    if failures:
        fail("broken repository-relative links:\n  " + "\n  ".join(failures))


def check_decisions() -> None:
    index = (ROOT / "docs/decisions/README.md").read_text(encoding="utf-8")
    decisions = (
        "0001-policy-driven-standards-proficiency-and-grade-calculation.md",
        "0002-provenance-bound-report-snapshots-and-subscriptions.md",
        "0003-consumer-side-producer-adapters.md",
        "0004-v02-evidence-policy-proficiency-and-planning-export-architecture.md",
    )
    for filename in decisions:
        if filename not in index:
            fail(f"ADR index does not link {filename}")
        text = (ROOT / "docs/decisions" / filename).read_text(encoding="utf-8")
        if "Status:** Accepted" not in text and "Status: Accepted" not in text:
            fail(f"{filename} is not marked Accepted")
    for amendment in (
        "amendments/0001-core-v0.6-ingestion-reconciliation.md",
        "amendments/0002-core-v0.6-ingestion-reconciliation.md",
    ):
        if amendment not in index:
            fail(f"ADR index does not link {amendment}")


def check_current_status() -> None:
    active = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (Path("README"), Path("Security.md"), Path("docs/README.md"))
    )
    for phrase in STALE_ACTIVE_PHRASES:
        if phrase in active:
            fail(f"active documentation contains stale status text: {phrase!r}")
    required = (
        "installable",
        "0.1.1.dev0",
        "typed evidence inventory",
        "adapter",
        "canonical verification",
        "Grade",
    )
    for phrase in required:
        if phrase not in active:
            fail(f"active package status is missing {phrase!r}")


def check_privacy() -> None:
    candidates = list(documentation_files())
    candidates.extend(
        path.relative_to(ROOT)
        for path in (ROOT / "tests/fixtures").rglob("*.json")
    )
    for relative in candidates:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for marker in FORBIDDEN_PRIVACY_MARKERS:
            if marker in text:
                fail(
                    f"{relative.as_posix()} contains a private-path/data marker: "
                    f"{marker}"
                )


def check_text_hygiene() -> None:
    for relative in documentation_files():
        data = (ROOT / relative).read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            fail(f"{relative.as_posix()} is not valid UTF-8: {error}")
        if "\r" in text.replace("\r\n", ""):
            fail(f"{relative.as_posix()} contains bare CR characters")
        if not text.endswith("\n"):
            fail(f"{relative.as_posix()} must end with one newline")
        for number, line in enumerate(text.splitlines(), start=1):
            if line.rstrip() != line:
                fail(f"{relative.as_posix()}:{number} contains trailing whitespace")


def main() -> int:
    """Run all documentation checks."""
    check_expected()
    check_required_text()
    check_links()
    check_decisions()
    check_current_status()
    check_privacy()
    check_text_hygiene()
    print("Meridian documentation validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
