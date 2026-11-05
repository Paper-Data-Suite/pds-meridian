# Issue #124 · E2G3O3 — Normal teacher assessment setup activation

## Scope and contract

The existing main-menu **D. Discover Registered Assessments** route now supplies the same trusted `GuidedGradeItemBridgeDependencies` used for teacher recovery. The existing discovery menu remains class-scoped and marking-period-scoped and now allows a teacher to select one named registered assessment, then explicitly choose **S. Review setup or verify current relationship** on its detail screen. A catalog row is never write authority.

The new bounded choice collector in `menu_teacher_assessment_discovery.py` calls existing Core/Grade Item readers and `load_assessment_setup_preview`, which independently reloads registration, period, publication status, and exact Grade Item conditions. A write-bearing setup requires the teacher to specify a purpose and new Grade Item title, or choose an active existing unlinked Grade Item, plus saved teacher attribution. The collector does not infer the purpose from an assessment's intent. An already-ready assessment proceeds to canonical verification without a write actor.

The sole execution handoff is to `review_correlated_assessment_setup_once` (E2G3O2), which delegates to `bind_correlated_live_assessment_setup` (E2C). E2C persists the initial intent and each exact original #122 action ID/target digest *before* the respective academic operation, and rereads original receipts and canonical state before declaring ready. Existing user-visible **APPLY** remains the single confirmation for the composite; no new academic writer, evidence authorization, or grade-policy activation is introduced here.

## Negative and partial outcomes

Absent class/calendar, ambiguous or stale registration, withdrawn/historical publication, unsafe Grade Item relationship, missing saved attribution, unexpected session context, and unavailable Core/Grade Item reads are refused. **B** cancels choice collection before action binding. **M** and **Q** retain global navigation semantics. A canceled composite returns to the list without claiming progress. Any non-canceled outcome closes the discovery snapshot; the teacher must reopen fresh discovery to review again. For interrupted writes, use **R. Review Interrupted Saves** and its original receipt/correlation path, never a new create attempt.

Catalog labels and Grade Item status descriptions are informational. Selection is applied to process-local teacher session navigation only when the independently verified composite reports readiness. The one-shot original #122 actions remain separate, so the operation is not multi-record atomic.

## Qualification

Targeted Ruff, strict mypy, scoped new teacher-journey tests and existing #124 discovery/composite/recovery regression tests must all pass. The exact Meridian wheel inventory is unchanged: no new runtime module is added. The patch is constrained to the existing main-menu and assessment-discovery modules, this test file, and this architecture note.
