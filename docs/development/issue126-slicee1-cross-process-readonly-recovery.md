# Meridian #126 — Slice E1: cross-process reconciliation without replay

**Baseline:** D2B2 accepted as `17366ba42512af8c1b186fa3a09a793ef4c72923`, branch `126-verified-correction-attempt-reassessment-management`.

## Why a separate E1 gate

D2B2 implements two individually guarded #122 actions, but they are **not an atomic cross-domain transaction**. A machine failure may occur before #30, after #30 is selected, after #31's immutable revision is written, or after #31's CAS selection. A new process must not confuse a journal event with a current academic record; nor may it generate a new #30 decision revision because the previous attempt could have succeeded.

The existing `assess_multi_attempt_recovery` reads the exact #30 and #31 current authorities against the original typed preview. E1's `inspect_durable_pair_recovery` adds an independently read **class-scoped #122 journal** to that canonical assessment. `TeacherActionReceiptStore.list_receipts()` is the only production journal reader. It validates complete bounded journal membership and fails closed on unknown entries, corrupt files or other unsafe state. E1 performs no filesystem write, creates no receipt, and constructs no in-memory #122 action.

## Immutable scope and independent trust

- A caller supplies an exact D2A `ProspectiveReassessmentReview` and its associated immutable #30 `AttemptDecisionAuthoringPreview`. E1 computes the canonical bytes and SHA-256 for *both* candidates, checks the revision/digest cross-link, teacher and student, Grade Item, work and number of selected attempts.
- The canonical inspector reads #30/#31 authority with the supplied authorized projection; a receipt is **never** used to substitute for a failed canonical read. Historical receipts are not current permission or an actor credential.
- For each candidate digest, the journal matcher verifies the action family, workspace/class/Grade Item/work fingerprint, actor ID, exact target identity/revision, original current-pointer witness, #122 canonical-source binding and actor-profile binding. A matching family/digest with contradictory scope yields `journal_unverifiable`, not silent omission.
- Zero matches means **receipt missing**, *not* proof no write occurred. More than one exact match means **journal ambiguous**, not an assumed newest action. Full-journal read failure means `journal_unverifiable` even when an exact canonical pair can be independently observed; it is a recovery workflow issue.
- Current `#30` alone cannot make a multi-attempt Grade operative. A `#31` decision written but not selected remains incomplete. The only `may_continue_to_standards` state is exact `pair_current_verified` after independent canonical checks, without ambiguous/unsafe receipt evidence. Missing receipts do not independently invalidate an exact canonical academic pair, but remain visible as missing audit evidence.

## Dispositions

| E1 disposition | Meaning | Automatic retry |
| --- | --- | --- |
| `upstream_not_current` | Exact reviewed #30 selection is not operative | Never |
| `upstream_current_reassessment_missing` | #30 is current but reviewed #31 target is not present | Never |
| `reassessment_written_not_current` | #31 immutable revision exists; its current selector does not match | Never |
| `pair_current_verified` | Both canonical records and exact relationship independently current | No write needed |
| `conflict_requires_review` | A policy, history, or selector witness drifted | Never |
| `canonical_unverifiable` | Required canonical read or resolver failed | Never |
| `journal_unverifiable` / `journal_ambiguous` | Scoped receipts cannot be used as faithful recovery evidence | Never |

`ActionReceiptWitness` includes an internal action ID for a future recovery controller but hides it from `repr` and the plain-text renderer. The renderer never prints student IDs, action IDs, native identifiers or Grades. It does not treat stage names as proof of writes.

## E2 is still required

E1 **does not** make a fresh process able to reconstruct the teacher's lost, unpersisted D2A preview if #31 was never written. The #122 receipt contains an exact target digest but not a complete, independently authorized new teacher decision. An automatic replay API would therefore be unsafe. E2 must design and qualify a durable *non-authoritative* reviewed-intent handoff (or a teacher-driven rereview), exact original-action reconciliation, and a resume route that reuses canonical immutable history/CAS while never reauthoring a completed #30 or manufacturing a new #31 policy. A failure must remain inspectable until explicit teacher reconfirmation and live authority checks.

## Tests and limitations

`tests/test_issue126_slicee1_durable_pair_recovery.py` uses the synthetic D2B2 fixture and checks empty/matching/duplicated/wrong-bound receipts, verified pair, #30-only, #31-written-not-current, current policy drift, failed canonical/journal reads, no-write behavior, safe text rendering and replay refusal. It does not exercise an actual Windows process crash or disk-level receipt corruption. Those remain E2 and the final A1–A18/native acceptance gates. Existing #122 journal storage tests must remain in the focused Windows acceptance run.

**No collateral mutations:** #29 eligibility, #30, #31, Core, ScoreForm, Standards associations, Grades and SIS remain unchanged by E1.
