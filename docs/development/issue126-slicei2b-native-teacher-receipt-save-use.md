# Issue #126 — I2B native #122 teacher-menu Save/Use qualification

## Acceptance baseline

- Parent: `c52bc903be9cd6cbbe6dcac5795df30368f9cf90` (I2A accepted).
- Branch: `126-verified-correction-attempt-reassessment-management`.
- Scope: **tests and development documentation only**. Do not edit the implementation, Core, or ScoreForm; do not merge the branch or close the issue.
- Installed tested dependencies: Core 0.6.6 and ScoreForm 0.13.0 noneditable distributions; Meridian source checkout at issue #126.

## What this slice qualifies

The 29-student, six-question, 31-attempt / 186-response ScoreForm native fixture built in I1 is registered through Core. I2A creates a current Grade Item, selected included Grade Item membership, two independently persisted and selected #29 included eligibility decisions, and an independently selected exactly-one attempt policy.

I2B drives `run_teacher_correction_decision_menu` with a **teacher's explicit** original observation, corrected observation, source-inspection rationale, and exactly one Save/Use confirmation. It invokes the production `prepare_reviewed_attempt_resolution` bridge, canonical `prepare_attempt_decision_action`, #122 `apply_reviewed_teacher_action`, native immutable #30 decision and CAS selector, and the real class-local `TeacherActionReceiptStore`. No menu-facing fake action or fake persistence callback is used.

Successful qualification requires all of the following to agree independently:

- The menu displays **Current Verified**, not simply an attempted write.
- The only selected #30 attempt is ScoreForm native Attempt 2 (6/6). Attempt 1 (0/6) remains present, and the separate genuine-retake student remains unselected.
- Exactly one #30 immutable revision exists, and the current #30 pointer is verified against the authorized current projection.
- Exactly one real #122 receipt exists, with the correct actor, Grade Item, academic period, action kind, revision and exact candidate SHA-256, a final verified checkpoint, and a matching observed immutable record.
- The original producer manifest bytes remain unchanged.
- Reopened Standards continuation accepts only independently verified included evidence from selected Attempt 2. In this test the final Standards *handler is a read-only call recorder*, so **no Standard or grade is written**.
- Cancellation before confirmation never creates an academic decision or action receipt; a changed synthetic identity fingerprint before confirmation cannot claim success; an interrupted selection leaves a written-but-not-current revision subject to separate #122 recovery and does not retry blindly.

## Explicit synthetic/test seams and nonclaims

The installed classroom cannot supply the teacher's personal #121 saved profile to an automated test using fabricated students. I2B therefore supplies a **synthetic TeacherActionActor** and substitutes only the profile-currentness query in `meridian.teacher_action_attempt_standards._actor_now` with an actor-bound synthetic guard. This is NOT evidence of real teacher authentication, identity attestation, or authorization. The Core publication and authorization from I1, all canonical Grade Item/#29/#30 state, #122 journal/selection machinery, and ScoreForm native reader remain production implementation.

Only the downstream Standards menu handler is replaced by a recorder in the Standards-navigation test to avoid writing a new academic association. The actual fresh F3B1 current-source and included-evidence gate runs.

This slice does **not** qualify scanned paper, reader hardware, a released Meridian wheel, future Core shared-header wheels, complete Suite/D4 installed composition, Report 9 #133/#134, or a real human-operated teacher profile. Those remain separate, visible release gates.

## Qualification and safety

Runner enforces exact parent HEAD and matching remote; accepted source-file Git blobs; clean or exactly two approved untracked paths; noneditable Core and ScoreForm; archive member hashes; source/test semantics; Ruff, strict mypy, focused 29×6 I2B tests plus prior #126 regressions; documentation and staged Git hygiene. Commit/push are conditional on every test passing. No automatic merge, issue closure, production editing, or hidden reapplication after a failed run.

A failed gate is **not** evidence that a decision was rolled back. The real write/CAS interruption test deliberately leaves a written-but-unselected revision in an isolated temporary synthetic workspace, never in the user's production PDS data.
