# Issue #126 — Slice D2A: exact future #30/#31 multi-attempt review

**Baseline:** `76f4ba9baae8119bf4bf3a8375442e8d35a3bdd8` (D1 accepted)

**Scope:** Reassessment *preparation* only. `meridian/attempt_reassessment_review.py` is a pure, read-only construction of one typed immutable `ReassessmentDecision` proposal with a digest-bound reference to the candidate `AttemptSelectionDecision`. This slice **does not** add a second current pointer, select a policy, create a policy, or write #30/#31/ScoreForm/Grade/Standards state.

## Boundary verified before implementation

- #30 owns the canonical *operative* selected attempts, exact current authorization/eligibility and CAS selection. D1 can save one selected attempt using #122.
- #31's released implementation provides `ReassessmentPolicy`, `ReassessmentDecision`, immutable revision storage, exact #30 dependency checking, and a CAS current selector. A #31 relationship may be written only **after the referenced #30 revision is persisted, selected, and operative**.
- Existing #122 `ActionKind` / `TeacherActionDomainPort` and `prepare_attempt_decision_action` cover `attempt_decision`, **not** a `reassessment_decision` action. Implicitly treating a raw #31 write as a #122 action would misrepresent receipts and recovery.
- A multi-record #30 then #31 workflow is **not an atomic transaction**. After the #30 write/select but before the #31 selection, the teacher's desired multi-attempt academic interpretation is incomplete. Success must never be reported until #31 is independently verified current and the exact referenced #30 selection remains operative.

## D2A implementation contract

`preview_reviewed_reassessment` requires:

1. A typed Slice C teacher interpretation for **genuine separate performances** with at least two explicitly selected exact authorized attempts; correction treatment selecting one corrected result is handled by D1.
2. An exact #30 authoring preview whose student, source, membership/policy bindings, selected attempts, actor, rationale and reviewed selection pointer agree with that interpretation. The SHA-256 is calculated over the existing canonical `attempt_selection_decision_to_json_bytes` representation.
3. An immutable `StoredReassessmentPolicy` whose scope and permitted modes match, supplied by the existing Core-authorized/current policy read. **D2A does not assert that a previously loaded policy remains current.** Any new/changed policy must be separately reviewed and selected.
4. An exact contiguous #31 history tuple and optional typed current pointer witness. These are observations for the later executor to re-check, not permission to write.
5. An explicitly chosen relationship, with no score/timestamp/attempt-number inference:
   - `retain`: each selected attempt remains contributing;
   - `replace`: explicit replacement edges, contributors equal selected attempts *minus the explicitly replaced targets*;
   - `combine`: explicit named combination groups, all selected attempts remain contributing, **no averaging or weight**;
   - `recency`: **teacher-specified full exact order** and explicitly nominated contiguous suffix of contributing attempts; no automatic latest choice.
6. Saved #121 teacher identity and review timestamp; both bind the future immutable #31 candidate, while neither grants source authority.

A `ProspectiveReassessmentReview` returns the canonical candidate object, its exact digest, the #30 candidate digest, the required #31 policy digest and the observed current-pointer revision/digest. It states `may_execute_without_revalidation = False`. Its renderer does not disclose student IDs and says **NOT SAVED**.

## Security and correctness

- Reject unsupported modes, duplicate or foreign relationship attempts, mismatched teacher intent/actor, wrong scope, invalid policy, non-contiguous revision history and current-pointer inconsistency.
- Never infer a producer-verified correction from ScoreForm manual-scan provenance.
- A change to #30 candidate bytes changes the future #31 upstream-reference digest.
- Without operative #30 currentness, an exact #31 source dependency check cannot succeed. D2A deliberately does **not** attempt persistence or select any pointer.
- No attempt, eligibility, policy or Grade mutation is authorized by this read-only preview. The tests use only synthetic roster and native IDs.

## Next delivery: D2B / execution and recovery

Before any multi-attempt Save-and-Use is exposed in the teacher UI:

1. Extend the **#122 reviewed-action family** for #31 (or a separately documented, equivalently canonical/guarded service) with exact candidate digest, selected pointer CAS witness, current policy and #30 revision/digest source basis, actor fingerprint, receipt/restart, and independent readback.
2. Bind the explicit D2A `ReassessmentDecision` to that service; check #30 prospective digest again before the first write.
3. Compose the #30 writer and #31 writer with **one reviewed teacher intention**, truthful success only after both canonical reads; an interrupted run must distinguish no write, #30 current/#31 missing, #31 immutable but not current, and uncertain state. Repeated requests must never reauthor blindly.
4. Add failure injection for concurrent #30, policy, roster/authorization, #31 CAS drift, journal interruption, source withdrawal and independent readback failure. Do not let an incomplete #31 state quietly feed Standards/Grade computation.
5. Qualify native ScoreForm and then teacher menu in subsequent slices.

**Acceptance level:** D1/source+focused synthetic tests upon Windows runner pass. D2A is **not** D2 cross-record execution qualification or any of A1–A18's final gates. D2B is required before actual multi-attempt write functionality.
