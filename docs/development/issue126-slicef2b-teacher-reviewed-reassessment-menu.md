# Meridian #126 — F2B: Teacher-reviewed reassessment and explicit #31 relationship

**Baseline:** accepted F2A `dbb1aafc06340c2853793cb26eece8d282bf4fd2` on `126-verified-correction-attempt-reassessment-management`.

## Teacher-facing contract

The assessment-bound F1 queue and F2A correction choice remain. A new `S. Review genuine reassessment` action is displayed on the student detail screen. This is **not** a producer-origin classification. It is teacher testimony about distinct performances, separately from source facts.

F2B requires at least two explicitly projected, currently operative eligible native observations; the teacher selects at least two by their displayed numbers. Meridian does **not** choose the newest/highest/lowest attempt. The exact selection is reviewed with the current policy and the reviewed teacher identity.

A separate #31 choice is required:

- **Retain:** contribute every explicitly selected performance, with no inferred arithmetic.
- **Replace:** choose a particular replacement and one or more particular performances it replaces. The replacement is directional, not inferred from chronology.
- **Combine:** select at least two members of one explicitly named semantic combination group; no averaging rule is introduced.
- **Recency:** supply a full explicit ordering and a separate set of contributors. Native attempt sequence is not treated as a recency rule.

All choices require a teacher rationale, which is text and never a shared-menu command (`:notes`, `B`, `M`, and `Q` are literal in rationale). No substantive change occurs before the final **Save and Use This Decision** confirmation.

## Existing academic authority reused

- F1 `project_assessment_attempt_inventory` is the read-only exact authorized source/roster/eligibility view.
- F2B uses `preview_attempt_interpretation` for attributable teacher testimony about genuinely distinct performances.
- #30 selection policy must already be current and compatible with the selected count. F2B has exactly one locally configured compatible one-or-more preset; it never creates or selects a policy.
- #31 policy must **already** be current under the configured `teacher_reassessment` policy identity. The ID is a configuration prerequisite, not a guess that the teacher has authorized a new policy. If absent or incompatible, no write occurs. Future policy discovery/setup is a separate qualified step.
- `preview_guided_attempt_decision` and `preview_reviewed_reassessment` bind the immutable #31 record to the exact *future* #30 candidate SHA-256. The reviewed clock value is frozen for both previews and for the coordinator's revalidation; it is not a source-order policy.
- `prepare_reviewed_multi_attempt_resolution` provides existing #122 two-stage guarded action, receipt journaling, CAS selectors and independent post-write verification. No new pointer or writer is added.

A successful screen requires `outcome.exact_pair_current`, `continue_to_standards_review`, and status `applied_current` or `already_current`. All other results, including partial #30 success and a written but unselected #31 revision, are labelled recovery/review required. There is no automatic retry. Return to F1 always triggers fresh inventory/current-state loading.

## Failure and privacy boundaries

Missing or stale publication, roster, Grade Item membership, eligibility, policy, teacher profile, #30 candidate, #31 history or CAS baseline block before Save. Cancellation generates no decision or receipt. Any exception after Save is an **uncertain mutation** and the teacher is instructed not to retry; exact #122 recovery is necessary. The workflow does not modify ScoreForm, Quillan, Concord, Core publication, #29 eligibility, Grade, Standard, proficiency, Report, or SIS.

Normal screens use student display names and brief attempt labels; no source IDs/digests are rendered. Existing F1 Technical Details is the authorized diagnostic surface.

## Evidence and exit gate

This slice provides a teacher menu, an F2A menu integration patch, focused synthetic interaction tests, and a guarded Windows runner. Focused tests verify all four relationship choices, invalid selections, independent contributor ordering, read-only/cancel behavior, pending policy and actor failures, exception results, and B/M/Q control behavior.

Accepted earlier D2B2/E1–E3B tests qualify coordinator and production/native storage behavior independently. **Full installed ScoreForm/Quillan/Concord classroom journeys, Core/Suite G D3/D4 integration, all A1–A18 gates and eight CI jobs remain open.** Acceptance on this slice is not a full release or merge authorization.

## Later F stages

F3 must supply the user-visible cross-process original-action recovery routes and Standards/eligibility/history continuation controls; G must qualify shared terminal capabilities. Genuine #31 policies are not silently created by F2B; policy discovery/qualification is a prerequisite for a usable multiple-attempt path.
