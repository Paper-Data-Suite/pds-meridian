# Teacher-first Reports navigation — Issue #111 Slice 12.1

**Status: implementation slice; not a completed teacher-report generation workflow.**

The eight existing read-only report generators remain authoritative. This slice
adds a teacher-friendly selection layer with these boundaries:

- The menu starts with questions teachers ask, not report type identifiers.
- The gradebook reconciliation report is **SIS agnostic**. It uses an explicit
  teacher-owned mapping revision, not a Genesis or other vendor integration.
- All eight report families retain their stable internal report-kind identities.
- Advanced CLI help is available on request but is not the primary menu label.
- The selection controller accepts *only* distinct canonical choices supplied
  by an injected catalog, with bounded display labels. It does not accept free
  typed IDs, guess roster identities, or scan directories ad hoc.
- Scope order is class, marking period, then the exact student, Grade Item,
  checkpoint, or gradebook mapping when that report requires it.
- Back removes one selection; Main Menu and Quit use Core's shared navigation
  exceptions. A choice is revalidated before acceptance.
- A prepared selection is transient process state, **not** a report, saved
  preview, Grade calculation, publication, or SIS update.
- Without a canonical provider the teacher menu explicitly reports that guided
  discovery is not connected yet; it must not fabricate results.

## Next increments

Slice 12.2 will connect class, period, student, Grade Item, checkpoint, and
mapping choices to established canonical Meridian/Core read-only provider APIs
and then invoke their existing report-specific request boundaries. A later Slice
12 increment will render previews and offer verified local non-overwriting export.

## Acceptance

Focused tests exercise stable report identities, SIS-neutral wording, distinct
labels, exact source identities, step-back behavior, Core M/Q navigation,
ambiguous catalogs, missing choices, and existing advanced CLI discoverability.
All eight existing report engines remain unmodified by this slice.
