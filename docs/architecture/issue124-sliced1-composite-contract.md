# Meridian #124 — D1: bounded single-confirmation #122 composition contract

**Pinned base:** `4bfb9c1533297890c98d4e91129fbd28f057d35a` (C1). **Scope:** one new coordinator, one isolated test module, this note, and the two exact package-inventory updates. This is not a teacher-menu integration or installed producer qualification.

## Behavior

`PreparedAssessmentSetupComposite.apply(confirmation="APPLY")` consumes one immutable C1 reviewed proposal and runs only already prepared #122 `PreparedGuidedAction` operations. Cancellation (anything other than exact `APPLY`) invokes *zero* validation readers, action ports, receipts or writers. Before any action, a fresh C1 canonical-read callback must reproduce the exact reviewed object and SHA-256. On an `already_ready` proposal, the coordinator only checks current canonical readiness; it makes no writes.

On `create_and_link`, the bound #122 Grade Item Save+Select completes before the coordinator asks an injected, separately revalidated *membership factory* to prepare an exact #122 included-membership Save+Select. On `use_existing`, only the membership action is prepared/executed. The action kinds, exact class, Grade Item identity, actor, and membership period/year are checked before each step. A missing/failing/interrupted first step prevents the second from running. Failure after any step retains its returned #122 result/action IDs and never fabricates an overall ready state. **Final ready requires a separate injected canonical current-state reload.** This is a sequence of independently durable #122 actions, **not** an atomic transaction or new record authority.

D1 does **not** construct the live #122 authoring previews or validate the calendar/source/actor on its own. The injected `fresh_review`, `after_grade_read`, and `verify_ready` functions **must** use canonical Core/Meridian records, not cached labels or synthetic booleans, before this coordinator can be wired to a classroom entry point. No new arbitrary writer is provided and no producer manifest, student answer or eligibility is read by this module.

## Recovery limitation and forthcoming work

This initial coordinator is intentionally **one-shot in-process**; the second `APPLY` on the same object is rejected without writing. It is **not** a durable multi-process restart mechanism. If a process exits or an outcome is unknown, the caller must use an explicit #122 exact-receipt recovery path; it must **not** recompute a new Grade Item ID and reauthor the same setup. That durable correlation and crash-at-boundary qualification are #124-E, after D2 live preparation binds exact existing source/action readers.

### D1 acceptance boundary

22 isolated source-level tests cover cancelled/no callbacks, ready/no-write, create+link, existing-only, stale preflight, mismatched action context, first-stage failure, intermediate stale check, second-stage failure, final canonical read failure and one-shot repeat suppression. Local isolated execution does not claim installed qualification. Changed-file Ruff, strict mypy on the new module, documentation validation and selected #122/C1/packaging regressions qualify the Windows increment. Full repository pytest, wheel builds and installed matrices remain reserved for meaningful integration and final PR qualification.
