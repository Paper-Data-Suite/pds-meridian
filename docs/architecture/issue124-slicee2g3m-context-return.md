# Meridian #124 E2G3M — Verified Recovery Session Continuation

## Scope

Preserve the selected teacher task context only after the original composite recovery prompt returns `ready_verified`. This is **navigation state**, not an authorization or academic write. E2G3L already qualifies the persisted canonical and correlated original-action paths; E2G3M qualifies the menu boundary after those checks.

## Behavior

- Verified recovery selects the exact reviewed work and Grade Item in `TeacherSessionContext` and retains the reviewed publication ID only when present.
- A session already bound to a *different* publication for the selected work fails closed before the recovery prompt; an existing different work/Grade Item continues to be rejected.
- Cancelled, incomplete, unverified, and partially selected recovery outcomes leave the session unchanged and do not claim the assessment is ready.
- No Grade Item, membership, producer evidence, receipt, or authorization record is written by session retention.
- The menu directs the teacher to return to Grade Items or evidence to continue; this slice does not automatically open protected evidence or start grading.

## Regression boundary

Targeted tests cover positive published/registration-only readiness, negative outcomes, mismatched publication, existing Grade Item mismatch and the fresh-review handoff. The existing #124 E2G3F–L regression gate remains in the focused runner. No new academic writer or automatic `RESUME` route is introduced.
