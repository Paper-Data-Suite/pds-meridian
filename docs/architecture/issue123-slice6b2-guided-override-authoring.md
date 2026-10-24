# Meridian #123 — Slice 6B2: teacher-named replacement Grade decision authoring

**Base:** `7ac0781b2b309026261967cbe218edd95e392348` on `123-teacher-first-navigation-existing-menus`.

## Teacher workflow

Teacher-context Overrides offers **7. Record a replacement Grade decision by student**. It selects a verified class, Core marking period, roster student, and calculation family by readable choices, asks for a numeric replacement Grade and explanation, and uses the composed `TeacherAttributionInput` via its established exact `Teacher actor ID: ` prompt. The teacher reviews the current canonical source result and confirms **WRITE**.

WRITE calls Meridian's existing `OverrideMenuDependencies.authoring_committer` once. **It writes an immutable override revision but does not select it.** The existing #123 Slice 6B1 option **6. Use the latest authored override decision by student** remains the deliberate, separate current-selection step. This is not a grade-calculation API, an implicit activation, a withdrawal, or an academic policy change. No new actor authority or persistent context is created.

## Currentness and durability

Class/year/roster, period/calendar, and the chosen student are checked before preview, after preview, and before commit. `OverrideAuthoringPlan` is checked against its immutable canonical candidate (identities, calculation family, numeric replacement, actor, rationale, source result, and digest). A repeated preview with the **same timestamp** is required to match before commit; immutable history/source change blocks the write. Domain-level authoring CAS/integrity checks remain authoritative.

Before the committer is called, errors and cancellation mean no write was attempted. After entering the committer, an error or unknown return value is **indeterminate**: the screen instructs the teacher to inspect history and never asserts rollback. Confirmed `created`/`existing` returns state that an override decision is recorded but not current.

No selected Grade result is silently assumed. Missing authorized evidence, policy configuration, or source result is reported as unavailable with domain exceptions redacted, not as a Grade of zero. A numeric `0.00` is valid and displayed as such.

## Core #237 boundary and compatibility

No header renderer, notes parser, global shortcuts, roster editing, or shared Core menu is implemented. Only existing Meridian local named selection, `B/M/Q`, and the preexisting teacher-attribution input adapter are used. Core #236 v1 contracts remain the planned integration boundary; Core #237 is not assumed released.

Legacy direct/no-navigation menu options 1–4 and teacher-context options 1–6 remain identical. Technical diagnostics, exact-record authoring, latest selection, and withdrawal remain discoverable under Advanced. No producer evidence permissions, teacher identity claims, Grade computation, direct CLI flags, storage, schema, or release contracts change.

## Acceptance evidence

Focused tests cover zero replacement, write-only semantics, explicit confirmation/cancellation, missing rationale and attribution, invalid/nonfinite values, canonical preview mismatch, changed immutable state, changed scope, uncertain write outcome, unavailable evidence, M/Q unwind, and Advanced-route preservation. Runner qualification performs Ruff, strict mypy, frozen inventory audit, existing #123 navigation/Grade/override regressions, and platform-sensitive tests before exact staging/commit/push.
