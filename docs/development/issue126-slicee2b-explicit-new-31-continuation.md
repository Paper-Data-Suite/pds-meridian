# Meridian #126 — E2B: explicit new #31 continuation after verified #30

**Exact accepted baseline:** E2A `4691415cb050a0eff85924a6c308a7b7c76baa2e`.

## The missing-#31 branch is not a replay

E2A resumes the original #122 receipt after an immutable #31 decision has been **written but not selected**. E2B covers a different state: the exact teacher-selected #30 decision is independently operative current, but **the prospective #31 decision has not been written**, no current #31 pointer exists, and there is no corresponding #31 action receipt. These conditions must be established using canonical #30/#31 reads **and** bounded full-class #122 receipt enumeration. An absent receipt alone cannot establish that a write was never attempted.

`meridian/attempt_pair_new_continuation.py` provides a read-only new-action preparation and a **separate explicit teacher confirmation**. It binds the original Slice C teacher testimony, D2A #31 proposal, exact #30 candidate digest, #31 policy, roster/source applicability and #121 actor. It never authors another #30 revision, edits source scans, changes #29 evidence, computes grades or publishes. The only academic mutation is delegated to the established #31 `prepare_reviewed_reassessment_action` / `PreparedGuidedAction.apply` (#122 immutable writer, journal and CAS selector).

## Narrow preconditions, both before preparation and immediately before execution

1. Recompute the **exact** #30/#31 candidate and teacher binding using E1 `_validate_binding` and D2B2 `_aligned`; a different source, selected attempt, treatment, policy, rationale or actor blocks.
2. Reproject the current authorized student/source/eligibility and verify the exact operative selected #30 digest through the independent canonical resolver, not a receipt.
3. Require an independently selected, exact #31 policy and unchanged #31 revision history/previous current-pointer witness. A target already written is **not** E2B; use E2A or broader reconciliation.
4. Require E1 status `upstream_current_reassessment_missing`, a matching `in_progress` original #30 receipt, no target #31 receipt, and no observed current #31 relationship. Read the entire class-scoped #122 journal again. Require the original #30 receipt to match actor, canonical subject identity, digest, revision, completed write checkpoint, and observed exact record.
5. Reject **any** #31 receipt with the same canonical student/Grade Item/work identity, even if it references a different reassessment digest. That competing action must be reconciled; E2B cannot safely infer it is unrelated.
6. Prepare exactly one fresh #31 action. Verify its source binding, actor-profile basis, work/scope, current CAS baseline, target revision and digest. Preparation does **not** create a receipt or write an academic record.
7. On `confirmed=False`, consume the capability with no write. On `confirmed=True`, repeat the entire independent audit and then call the **#31-only** #122 action once. An exception could mean the revision was written: return `recovery_required`, never retry automatically.
8. Return `pair_current_verified` only if #122 supplies exact current proof, independent #31 resolution agrees, and post-action E1 readback verifies **both** canonical #30 and #31 records. If any read fails, return `current_unverified`, not a false success. Only a fully verified pair may continue toward Standards review.

E2B does not make cross-family writes atomic. The #122 journal remains subordinate to independently read canonical truth. A new action may leave immutable #31 history without current selection; E2A and E1 remain the recovery path. A missing or unsafe receipt does not authorize reconstructing a write. E2B does not silently create a policy or decide retain/replace/combine/recency; the teacher chooses those through D2A.

## Qualification

`tests/test_issue126_slicee2b_new_31_continuation.py` exercises synthetic teacher/source identities and injected authoritative/journal observation seams. The suite explicitly covers normal success, cancellation, one-use semantics, no #30 rewrite, loss/alteration of the original receipt, competing same-student #31 actions with different digests, unrelated student receipt, source/policy drift, CAS/history conflicts, failed or uncertain writes, and disagreement during independent readback. Established tests for D2B2, D2B1, E1, E2A, #30/#31 storage and #122 are also rerun.

Passing focused Windows tests does not constitute native ScoreForm release qualification, per-grade downstream verification, all A1–A18 acceptance gates, or final end-to-end classroom UI usability. Remaining Slice E work: native fault-injection/real-storage restart matrices and a consolidated recovery entry; subsequent F–J cover teacher menu, Core/Suite, downstream guards, installed wheels, and final acceptance.
