# Teacher report foundation — Issue #111 Slice 6

Slice 6 adds the common, read-only foundation used by the eight teacher reports
owned by Issue #111. It intentionally performs no report-specific academic
inference.

The common preview envelope binds report kind, class, Academic Period, calendar
revision, exact digest-bound material sources, deterministic rows/diagnostics,
and a canonical preview SHA-256. Common renderers provide deterministic JSON
plus practical Markdown, CSV, and TSV representations.

Local file output reuses Meridian's existing verified, non-overwriting
report-export artifact writer. Bounded display-name observation reuses the
existing Core-roster observation model rather than copying a full roster into
report state.

The top-level teacher menu gains `9. Reports` without renumbering existing
tasks, and `meridian reports` provides the direct CLI shell. Report-specific
generators are deliberately deferred to later Issue #111 slices.

Authority remains unchanged:

> Meridian reports are read-only derived views over existing Meridian academic
> authority. They do not create Grades, proficiency, evidence eligibility,
> attempt decisions, overrides, or official SIS/LMS records.

A local report artifact proves only what Meridian rendered locally. It does not
claim that an external application received, accepted, or synchronized it.
