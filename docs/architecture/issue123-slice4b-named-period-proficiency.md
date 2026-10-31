# Meridian #123 — Slice 4B: named Academic Period proficiency review

## Scope

This slice replaces the **ordinary teacher-composed** Proficiency option 2 with
class → named current marking period → roster student → Standard having an
explicitly selected current Academic Period proficiency result. It does not
change the direct/legacy injected menu route, and leaves all write, select,
planning, and policy operations in explicit Advanced paths.

## Read-only, exact sources

- The selected class is reverified by the Slice 3 `TeacherNavigationContext`
  against Core's current class metadata, active year, and roster.
- Marking-period labels, inclusive dates, lifecycle, and exact calendar revision
  come exclusively from Core's current Academic Period catalog. A teacher
  explicitly chooses the period; a single row is **never** auto-selected.
- Student labels come from the current Core class roster, not free-typed IDs.
- Standards are discovered from Meridian's existing immutable result-family
  reader, then filtered to **explicitly selected** results. Results belonging
  to a different class, student, period or calendar revision block selection.
- Explanation is still performed by Meridian's existing period proficiency
  explanation service. Its authorization, dependency, and exact source checks
  are not replaced by the selector or a session context hint.
- The chosen period and selected result are reloaded during and after selection.
  A stale choice cannot be silently mapped to a different canonical result.
- Cancel/Back performs no academic write. M/Q continue to unwind through Core.

## Compatibility and limits

- No new Grade Item, score, proficiency, policy, selection pointer, receipt,
  publication authorization or grade is authored by these menus.
- Neither Core nor any producer repository was changed.
- The existing #110 188-site raw-prompt quarantine and frozen 49-operation
  Slice 1 **historical** inventory remain unchanged. The former direct route is
  preserved for programmatic/Advanced access and remains visible to direct
  callers without the composed `navigation_context` argument.
- Discovery uses the public `list_academic_period_proficiency_result_standard_ids`
  API and checks at most 500 results per presented choice list. The underlying
  storage service scans result histories without a caller-supplied scan limit;
  large-storage performance is a follow-up for a future bounded read contract.
- Missing current result is **not** interpreted as zero or an inferred level;
  the Standard is simply unavailable and the teacher can leave the route.
- Technical identities, revision numbers, and digests remain internal to
  selection; no protected student detail is added to preferences or logs.

## Qualification

Run the included guarded runner from the existing issue branch at the exact
Slice 4A commit. It will preflight hashes and patch anchors, then run Ruff,
strict mypy, this slice's tests, #123 prior-slice tests, independent #110,
reporting and #121/#122 compatibility tests. No commit/push follows a failure.

## Remaining Slice 4 work

Named current work-registration titles and membership periods; complete
Proficiency author/preview/select guided equivalents preserving #122 Save/Apply
and CAS receipts; migration of any remaining routine Grade Item operations.
The existing exact-record routes stay explicitly Advanced until replaced.
