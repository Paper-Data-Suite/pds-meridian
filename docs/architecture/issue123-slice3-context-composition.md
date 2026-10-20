# Issue #123 — Slice 3: navigation context composition and compatibility

**Base:** `aea11fa` on `123-teacher-first-navigation-existing-menus`
**Scope:** Read-only verified context and dependency threading, not named workflow migration

## Change set

- Add `TeacherNavigationContext`, a process-local companion to the existing
  `TeacherSessionContext`. It never persists students or periods to teacher
  preferences and never treats a session value as academic authority.
- Validate class identity, active year and roster using released Core APIs.
  Validate an explicitly selected marking period from the current verified Core
  Academic Catalog, carrying its exact calendar revision in memory.
- Revalidate each requested scope; fail closed and clear a stale period if the
  class, active year, workspace, calendar revision, period lifecycle or label
  changes. No automatic retargeting, actor identity, permission grant, or write.
- Compose one navigation context alongside the existing shared session in
  `default_teacher_menu_dependencies`. Pass the *same object* to eight top-level
  legacy controllers and Reports. Thread it into the existing nested Planning
  Signal controller via Proficiency option 10.
- Add an optional keyword-only `navigation_context` parameter to each legacy
  controller, preserving current injected tests and direct call sites without
  silently changing their prompt or academic-execution semantics.
- Keep #121's verified resume path in Teacher Settings intact: resumed class
  and work remain hints until a controller explicitly requests fresh Core
  validation. Keep existing #122 Save/Apply/receipt/recovery boundaries intact.

## Historical audit integrity

Slice 1 recorded 49 source-level routes, nine Reports, and line-specific prompt
sites against `0e9afa0`. The snapshot is not a mutable picture of HEAD. It is
reconstructed from that *exact* local Git commit with its recorded 17 source
blob hashes; any missing/corrupt original tree blocks verification. A separate
live-source review gate accepts drift only in the ten expressly reviewed
composition files, compares prompt fingerprints without line positions, and
still checks every documented menu operation. #110's independent 188-site
quarantine remains untouched and must pass.

## Boundaries and deferred adoption

This slice supplies and threads a context object; existing legacy prompts are
**not yet replaced**. Later slices must use the injected service and Slice 2
selectors to present named, current records and update the routine/Advanced
route inventory deliberately. A selected period is a convenience witness, not
a replacement for domain-specific revision/CAS/currentness checks.

## Verification

- Focused tests: lazy Core reads, class and roster mismatch, missing active year,
  exact marking period revalidation, calendar/workspace/class switch,
  cancellation/no side effects, optional handler injection and composition.
- Slice 1 historical inventory identical, #110 raw-ID contract unchanged,
  #111 report selection and #121 preferences/#122 action recovery preserved.
- Ruff, strict mypy and relevant pytest contracts run in the guarded runner.
