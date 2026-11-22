# Issue #126 — F3B2: Original-receipt-only reassessment restart

## Scope and baseline

Baseline: accepted F3B1 commit `958f72bcb912434d00903d49807e4afe499e0295`, installed noneditable Core 0.6.6. Changes: one new teacher-menu service, its synthetic tests, this document, and a guarded edit to the assessment student menu. No canonical #30/#31 schema, producer result, Core, ScoreForm, Grade or Standards writer changes.

## The student-facing decision

From the assessment's authorized student review, `X` continues to perform the read-only reassessment diagnosis; `Z` begins the distinct **original-receipt selection restart**. The teacher may type `RESUME` exactly once after reviewing what will and will not change. Back/Main/Quit and every other response cancel without selecting an academic record. The screen deliberately does not prompt for infrastructure IDs or invent a replacement original receipt.

## Preflight and fail-closed boundaries

A fresh authorized projection and complete included Grade Item must match the selected class, work, publication, snapshot and authorized student. The exact canonical #30 decision must be current, selected for two or more operative attempts, and match its immutable source and teacher testimony. A unique #31 immutable revision must already be written, be the latest historical record, reference that same #30 digest and not be current. No other #31 pointer may remain operative. The saved teacher identity must match the original #30/#31 authorship.

The adapter reconstructs typed *historical review inputs* from immutable #30/#31 records and the original class #122 receipts, never a fresh decision candidate. It rejects absent/ambiguous original #31 receipts, missing/ambiguous original #30 receipts, changed actor, source, history, current pointer or receipt CAS baseline. The authoring/history objects are **not write authorization**. All confirmation authority comes from existing `prepare_exact_pair_restart` in E2A, which independently verifies original receipt checkpoints, fresh canonical policy/source, exact current #30, original #31 immutable write, intended CAS baseline, and actor attribution. E2A's original-receipt port prohibits immutable writes; it can select only that original #31 record, once.

A missing #31 write, no original receipt, ambiguous journal, previously selected #31, changed teacher profile or other conflict **cannot** be resolved by replaying the Save action through this menu. These cases are explicitly blocked and must be handled by separate reviewed workflows. This slice does not add E2B new-#31 continuation to the menu.

## Outcome and Standards handoff

Only E2A's `pair_current_verified` with `exact_pair_current=True` can report success. Post-write unknowns, readback disagreement and other outcomes direct the teacher to canonical history and original receipts without retry. Successful recovery returns to the assessment; the existing F3B1 `V` action will **recheck** current eligibility and #30/#31 before Standards review. No direct Standards write or proficiency/Grade inference is performed in F3B2.

## Qualification

The guarded acceptance runner checks exact branch/HEAD/blob, clean state and installed Core. It runs Ruff, strict mypy, the F3B2 menu/reconstruction suite, the accepted E2A original-receipt restart suite, F3B1/F3A/F2B/F2A/F1 and established #126/native regressions, documentation validation, staged path and whitespace checks. Only after all gates pass does it commit and push. There is no merge, issue closure or claim of A1–A18 final release acceptance.

## Follow-on

F3B2 completes the narrowly scoped **written-but-not-current #31** restart path. Slice G must qualify shared Core/Suite menu navigation and the installed entrypoint, followed by downstream contract and release acceptance in H–J.
