# Meridian #123 — Slice 7B: Select a named frozen ReportingSnapshot

**Base:** `d12869b` on `123-teacher-first-navigation-existing-menus`
**Scope:** One additive teacher-first selection controller and one reviewed `menu_snapshots.py` patch.
**Guard:** Snapshot selection is local current-use authority only; no SIS, district gradebook, report freezing, or producer evidence authorization.

## Ordinary workflow

The context-aware **Snapshots** menu adds **8. Use a frozen reporting checkpoint by name**. Existing options 1–7 and the legacy no-context menu are unchanged. The teacher:

1. Chooses or reuses a Core-verified class, then chooses or reuses a verified current marking period.
2. Sees existing frozen checkpoints for **that exact school year, period and calendar revision** via the prior 7A title/record catalog; no manually typed IDs, hashes, or revisions.
3. Selects one immutable checkpoint. Meridian reloads the snapshot and validates its digest, definition, row count, scope and current-use state.
4. Supplies an optional rationale and the canonical existing `Teacher actor ID: ` attribution prompt (handled by the composed `TeacherAttributionInput` bridge when configured).
5. Reviews title, named period, creation date, row count, local reporting-only boundary, and current-selection status. Exact `USE` is required.
6. Meridian rechecks Core class/period, canonical snapshot catalog, immutable item, and fresh domain selection preview; only then delegates to the existing `SnapshotSelectionCommitter`, which owns the exact CAS selection. A final canonical inspector read must observe the selected checkpoint before success is displayed.

An already-current checkpoint produces no write; an empty/invalid catalog fails closed. No unexpected target is silently substituted.

## Invariants and outcome reporting

- A choice label is not authority. Exact immutable `snapshot_id`/digest stays inside reviewed record references; the displayed period and title come from the Core/Reporting Definition records.
- The bounded catalog (at most 200 snapshots in the class) rejects stale/ambiguous choices rather than silently paging past unauthorized data.
- The preview is bound to the selected immutable snapshot, actor, rationale, timestamp, expected current selector, and exact class/definition/period/calendar scope. Equality of fresh and reviewed plan blocks changes between confirmation and commit.
- No override, reporting definition, snapshot, grade, export, or SIS record is authored here. **Only the local ReportingSnapshot current-use selector** may change.
- A failed/unknown post-commit result is **uncertain** even when a write may already have occurred; the teacher is instructed to inspect current state before retry. No claim of rollback.
- Existing Advanced exact-ID, definition authoring, freeze JSON and direct CLI routes stay intact. The Issue #110 frozen legacy prompt inventory is not expanded; the teacher-attribution adapter prompt is referenced by a named constant rather than a new literal `read_choice` call site.
- No Core #237–#240 shared terminal UI, Notes, or cross-app command behavior is implemented.

## Test plan and qualification

`tests/test_issue123_slice7b_named_snapshot_selection.py` tests named choice, exact selection and non-SIS wording, missing/canceled teacher attribution/confirmation, invalid period/class, changed snapshot digest, already-current state, modified preview scope/hash/rationale, changed post-confirmation preview/current selection, stale period, error redaction, commit exception, unknown disposition, failed postcommit read, B/M/Q unwind and legacy/Advanced route preservation.

Run Ruff import and full checks, Ruff format, strict mypy for the new controller and existing menu, frozen #123 Slice 1 navigation audit, focused tests and previously-qualified #123/Issue #110/#55/#57/#121/#122 regression groups. The guarded runner stages **only** the four reviewed slice files, commits only after success, and pushes without force after ensuring the remote has not advanced.

**Out of scope:** A richer construction wizard for reporting definitions/freeze inputs, external SIS publishing, and Core shared terminal/header adoption.
