# Meridian #123 — Slice 5B: named bounded Grade report preview

**Baseline:** `27c0626ff69f994d90555466254a86f4c878dfd1`.
**Scope:** teacher-first, read-only **Grades** report selection over a current Core roster.

## Teacher journey

1. Reuse a verified current class and marking period (or select by the existing named catalog).
2. Select **all** current roster students when at most 50, or build a deliberate named subset of up to 20; no comma-separated student IDs. Duplicate names retain roster-position details.
3. Choose the supported Grade family through existing Meridian family choices.
4. Revalidate the exact class, marking-period calendar witness and every roster candidate before evidence evaluation.
5. Delegate to the **unchanged** `GradeMenuDependencies.report_loader`, including evidence authorization, policy/activation and per-student explanation.
6. Verify exact report scope, order, row count and availability counts. Reread roster and marking-period witnesses **after** evaluation, before displaying any student result.
7. Display human names in locally paginated groups of ten, clearly distinguishing no numeric Grade, literal numeric zero, unavailable result, stale result and override counts. This is **not** a ReportingSnapshot or a persisted Grade.

## Safety and limits

- Entire roster maximum: **50** students. Named subset maximum: **20** students.
- Ambiguous labels, changed roster candidates, changed active period, out-of-scope result, duplicate row, or wrong count fail closed; only canonical IDs go to existing domain loaders.
- No Grade is **not** zero. Missing policy / missing authorized work evidence is not silently inferred or attached. An unavailable row does not expose a private provider exception.
- `B/M/Q`, existing selector search/refresh/page shortcuts and the original exact-record Grades reports remain available; non-composed direct callers keep the original 1/2 menu.
- No Core #237 renderer, shared colon-command parser, Notes service, or global navigation framework is implemented. This local report pagination uses Meridian's existing N/P convention pending adoption of a qualified Core interface.

## Qualification

Focused tests cover bounded roster/subset selection, names vs opaque identities, 29-student paging without repeated evidence reads, explicit zero vs absence, unavailable status, tamper/stale failures, early cancellation, exception redaction, B/M/Q unwind, and Advanced/direct-menu compatibility. The original navigation route and reports/quarantine tests are regression requirements. No core/version upgrade or academic write.
