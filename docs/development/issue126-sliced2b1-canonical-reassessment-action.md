# Meridian #126 — Slice D2B1: #31 guarded Save/Select action

**Baseline:** accepted D2A `1431e3753978503459285e071295b3a20433e670`. Branch: `126-verified-correction-attempt-reassessment-management`.

## What this delivers

D2B1 registers `reassessment_decision` as an explicit #122 academic action kind (two small guarded changes to the existing contract and orchestration supported-kind set) and adds `meridian/teacher_action_reassessment.py`. This is a **single** canonical #31 action, not an atomic two-record #30/#31 operation.

A teacher's already-reviewed D2A `ProspectiveReassessmentReview` and a verified #121 attribution are necessary but not sufficient. The #31 action can only be prepared after the corresponding #30 candidate is **independently operative and current**; the #30 selected revision/digest must match exactly the future reference in the #31 candidate. In addition, the exact current #31 policy and allowed mode, included Grade Item membership, academic period/calendar, history witness, selected #31 pointer, source publication, immutable candidate digest, and teacher attribution must agree.

The adapter uses the **existing** #122 `_GuidedPort`/`_prepare` and `PreparedGuidedAction.apply(confirmed=...)`. It does not create a bespoke journal or current-selection store. The write delegates to `write_reassessment_decision_revision` and the CAS selection delegates to `select_reassessment_decision_revision`, both with the exact original `AuthorizedProjectionSnapshot`. Independent `resolve_current_reassessment` readback is required before `observe_reviewed_reassessment_action` reports `applied_current` or `already_current`. Receipts alone never confer authority.

The unchanged #122 recovery interface `PreparedGuidedAction.resume(confirmed=...)` can inspect and resume the **same bound #31 action** after an interrupted author/select, subject to the exact original action identity and canonical checks. On restart, an absent in-memory preview must not be reconstructed from a newest/highest attempt, and an old receipt must not be assumed to be successful merely because the target revision exists. Separate recovery work remains for Slice E.

## Boundaries and recovery

- **Not atomic:** #30 and #31 are separate immutable histories and current pointers. If #30 becomes operative while #31 is missing or not current, the entire teacher task is **incomplete**; do not proceed to Grades, Standards, proficiency or reporting as if reassessment had been resolved.
- **No implicit policy:** #31 policy creation/revision/selection and #30 policy setup are separate teacher decisions. This action requires an existing exact selected #31 policy.
- **No auto-retry:** a returned `written_not_current`, `current_unverified`, `recovery_required`, or unknown exception requires canonical recovery. Never author a fresh #31 revision to compensate for an uncertain earlier write.
- **No producer causality inference:** scan-review provenance does not prove a correction; D2A teacher testimony is not a producer correction assertion.
- **No automatic averages, recency, or grade changes:** `retain`, `replace`, `combine`, `recency` use the explicit D2A relationship shape and canonical #31 validation, not numerical ordering or score policy.
- **No new schema:** one registered action kind; underlying #31 policy/decision persistence is unchanged.

D2B1 **does not** expose a menu path that writes both #30 and #31 with a single teacher confirmation. **Next D2B2** must compose the existing #30/D1 and new #31 ports into one reviewed intention with strict ordering, independent readback, truthful intermediate states and restart-safe **cross-action** reconciliation; because the two stores are not transactionally atomic, a partial run cannot be labeled applied. D2B2 must also guard against a policy/source/authorization change between stages. Slice E then qualifies restart recovery and interruption matrix.

## Qualification

New synthetic tests cover correct #122 registration, preparation with zero writes, explicit #31 author/select, missing or changed #30, source drift, #31 policy change, included membership drift, immutable collision, CAS pointer drift, independent canonical readback, cancellation, and replace mode. Focused installed regressions include A/B/C/D1/D2A, canonical attempt-selection and reassessment suites, and #122 action tests where present. Windows runner qualifies mypy/Ruff and documentation before committing/pushing; final classroom A1–A18 gates remain open.
