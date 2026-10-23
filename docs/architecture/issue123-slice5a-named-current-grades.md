# Meridian #123 Slice 5A — Named Current Grade Review

**Baseline:** `c3c380b` on `123-teacher-first-navigation-existing-menus`.

This deliberately narrow Grade-menu migration implements the ordinary **one current Grade** preview with authoritative class, marking-period, and roster choices. It does not change grade calculation, policy, evidence authorization, override, grading-family semantics, current Grade persistence, or reporting snapshots.

- Reuses a verified session class and marking period; otherwise chooses labeled current Core records. Selects a named student with exact roster identity and a calculation family with an explicit evidence-provider warning. A current Grade preview is strictly read-only.
- Rechecks Core school year, class roster and calendar witness plus the exact selected student before and after invoking the existing Grade-domain `current_grade_loader`; verifies returned target fields. A failed or unconfigured grade is **not** rendered as zero.
- Leaves the existing exact-ID current-grade preview available as **Advanced** option 3, the existing report as **Advanced** option 2; direct invocation without a navigation context preserves the original option numbers and services.
- No technical digest/ID appears on routine output. Source-dependent failures are redacted; exact provenance remains accessible through the existing Advanced route.
- Does not implement Core #237's shared green header, `:notes` parser, or shared menu API. Existing Meridian-local screen functions remain transitional.

## Acceptance and known bounds

This slice does not migrate bounded multi-student Grade reports, authorize conventional/hybrid work evidence on its own, or create missing grading policies. The current Grade service remains the source of truth; an unavailable provider/policy results in a **blocked, no-write** state. Further slices should address named roster subsets and report preview. Full installed-matrix acceptance remains issue-level work after these bounded migrations.
