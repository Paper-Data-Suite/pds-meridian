# Meridian #124 — E2E: explicit original #122 exact-selection RESUME

**Pinned base:** `2732179dfea79b996e7b291578855a435bb1ff24` (E2D). **Scope:** one additive, non-menu exact-resume adapter, focused isolated tests, this architecture note, and the two exact package-inventory updates. E2A/E2B/E2C/E2D, #122, and Core academic writers are unchanged.

## Limited authorization

`resume_original_assessment_setup_selection(root, reviewed_preview, saved_actor, original_action=..., confirmation="RESUME")` requires a **caller-supplied, already-bound original #122 `PreparedGuidedAction`** with the same action ID, immutable candidate digest, workspace/class/Grade Item, saved attribution/profile, and membership period/work. It does **not** regenerate a new action ID, reconstruct domain dependencies from a receipt, or author a new immutable revision. Merely possessing a correlation file or a readable restart inspection never grants execution authority.

Without the literal `RESUME` confirmation the function makes no observations and no writes. On confirmation, it reloads the exact stored E2B correlation and E2D reconciliation; only the exact original Grade Item at `grade_item_written_not_selected` or the exact original membership at `membership_written_not_selected` can proceed. Missing or competing correlations, unrelated action ID, incorrect stage, changed actor/source/revision, unproven target history, wrong journal, or changed receipt generation refuse selection.

Before invoking #122, the adapter rereads the original receipt and calls #122's read-only `assess_teacher_action_recovery()`. It requires `eligible_to_resume` and `can_resume_exact_selection=True`, rechecks the E2D snapshot, and calls the **base** `PreparedGuidedAction.resume(..., confirmed=True)` only. The #122 kernel repeats live basis, canonical target, pointer baseline and CAS checks and invokes only its exact selection path, not `persist_exact()`. A race after the wrapper's checks must still be rejected by #122, and the wrapper's follow-up E2D inspection must independently confirm the resulting state. An original Grade Item selection leaves the correlated membership pending; membership selection can report `ready_verified` only when E1/E2A/E2D confirm canonical readiness. A returned #122 success alone is insufficient.

## Explicit limitations

**Not wired to menus, and not yet a complete cross-process restart UX.** E2E cannot rebuild an original trustworthy #122 prepared port/preview from the original journal and current canonical domain source. A fresh preparation with a new action ID must be refused. A later adapter must establish the original action/port binding under fresh domain authority before invoking this gateway. E2E also does not turn a crash-time correlation/receipt write into an atomic multi-record transaction. No automatic retry, no new Grade Item or membership creation, no arbitrary academic selection, and no student/producer record mutation.

The exact-confirmation gate, typed #122 return, advisory E2D state, and its post-selection verification are distinct from any claimed blanket retry permission. Unknown or failing outcomes require independent review.

## Qualification

Targeted Ruff lint/format, strict mypy on the new adapter, documentation validation and focused E2E/E2D/E2C/E2B/E2A/E1/D2/D1/C1/#122/package tests. Full repository pytest, wheels, and installed matrices remain final-integration gates only.
