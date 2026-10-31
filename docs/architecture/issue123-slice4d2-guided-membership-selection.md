# Meridian #123 — Slice 4D2: Guided selection of an existing work-membership decision

**Base:** `d13b5e275a3855c5c187f9ebf419c008caf835c4` on `123-teacher-first-navigation-existing-menus`.

## Scope

Add teacher-first **9. Use an existing work membership decision** to the Grade Items menu only when verified navigation context is available. The teacher chooses a class, existing Grade Item, currently registered producer work, and an existing authored membership version. Rows explain the existing `included`/`excluded` decision, date, marking period, compatibility with the currently selected Grade Item and Core registration, and whether it is eligible for normal use. The teacher reviews the exact choice, then explicitly types `USE` before a domain selection is attempted.

The existing `preview_grade_item_membership_selection` and `commit_grade_item_membership_selection_preview` remain the sole consequential boundary, including their immutable-history verification, exact dependency validation, and current-pointer CAS. No unselected candidate is silently adopted, no new decision is authored, and no incomplete or unavailable relationship is inferred. The direct CLI and six existing exact-record Grade Item operations are unchanged. The new menu option is not visible in direct legacy calls without a shared navigation context.

## Domain currentness and honest boundaries

- Class/roster/workspace/year are revalidated by Core, independently of the process-local navigation hint.
- The selected current Grade Item revision and digest must match the membership's exact Grade Item revision basis; the Core registered work's current revision and active/planned status must match the membership's exact work basis.
- An included membership must refer to the current, eligible Core marking-period calendar revision and an active Grade Item. Incompatible histories are still visible with **Historical basis · Advanced only**, not offered for routine use.
- Candidates use bounded 100-version histories, verified exact stored decision digests, Core registration witnesses, and current membership pointers. A revision change between display and confirmation triggers a refresh requirement.
- A canceled, unavailable, or already-current decision does not invoke the write service. The confirmed action selects *an existing immutable decision*, not a new revision, Grade, Score, publication, assessment, or distribution.
- The existing storage/selection workflow remains responsible for final exact dependency reads, lock and compare-and-swap. A failure after an attempted commit must direct the teacher to canonical inspection rather than claim rollback or guaranteed no write.

## Shared teacher experience boundary

Core #236 has merged its v1 **interface design**; Core #237 owns the actual shared green header and optional prompt-scoped `:notes` command. This slice only adds a domain-specific route, catalog and guarded confirmation. It does not add Core-style header rendering, shared command interception, Notes records/dispatch, shared roster editing, or Suite-wide control surfaces.

## Qualification

Run focused catalog/interaction tests for duplicate and unbounded histories, provenance mismatch, stale calendar/registration/current pointer, cancellation, already-current no-op, one confirmed commit, conflict results, original B/M/Q unwind, and Advanced route preservation. Retain Slice 1 exact 49-operation audit, #110 prompt quarantine, Slices 2–4D1, #121 preferences, #122 action recovery, existing Grade Item/Period/Reports regressions and Ruff/mypy checks. The data-only payload and separately supplied Python runner guard the exact baseline, archive hash and approved staged set before committing or pushing the current branch without force.
