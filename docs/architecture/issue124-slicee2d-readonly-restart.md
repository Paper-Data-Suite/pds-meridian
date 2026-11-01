# Meridian #124 — E2D: exact read-only restart reconciliation

**Pinned base:** `b92937be7b1d7bc4fd12553366205b6866d25694` (E2C). **Scope:** one additive read-only Meridian module, focused tests, this note, and exact package-inventory updates. No menu, academic mutation, journal writer, or resume command.

## Reconciliation contract

`inspect_stored_assessment_setup_restart(root, preview, actor)` requires an absolute workspace, typed C1 reviewed preview, saved #121 attribution, and full class-local E2B correlation and #122 receipt inventories. It rebuilds E2A's exact immutable intent fingerprint from the preview, workspace and actor; it never guesses an identity from titles, filenames, timestamps, or unrelated receipts. It demands exactly one stored matching intent and refuses other records claiming the same Grade Item or producer/work. Missing records, changed actor/profile/year/period/work/review, unreadable/corrupt inventory and ambiguous concurrent attempts all require review.

E1 reads the canonical registration, Grade Item, membership and original #122 receipts without writing; E2A correlates the exact stage action IDs and candidate digests with the **same** receipt snapshot. The service checks class inventories again after interpretation, refusing moving or incomplete observations. It returns `reviewed_not_started`, `original_grade_action_pending`, `original_membership_action_pending`, `ready_verified`, or `requires_review`, with the original action IDs and canonical state for review. `ready_verified` requires independently matching E1 canonical state and E2A action receipts, not a journal or correlation claim alone.

**Every disposition is advisory.** `may_resume_automatically`, `may_create_new_action`, and `may_select_academic_record` are always false. Even `reviewed_not_started` is **not** permission to manufacture or apply another action. E2D does not rebind #122 ports after restart and cannot prove a cross-process atomic snapshot against future concurrent changes. A later independently qualified, explicitly approved, exact-selection adapter must recheck canonical authority and call only #122's `resume_exact_teacher_selection` where its own conservative recovery contract allows it; it must never reauthor an immutable Grade Item or membership revision.

## Qualification

Targeted Ruff and strict mypy on the new module, documentation validation, focused E2D/E2C/E2B/E2A/E1/D2/D1/C1/#122/package regressions. No full repository pytest, release wheels, or installed matrices at this increment.
