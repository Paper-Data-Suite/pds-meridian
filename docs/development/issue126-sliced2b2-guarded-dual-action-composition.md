# Meridian #126 — Slice D2B2: guarded #30/#31 dual-action composition

**Required accepted baseline:** `3463b81518166d6db61da8e25dc35bf99b26f6a6`, branch `126-verified-correction-attempt-reassessment-management`. D2B1 qualified on Windows: **131 passed, one OS symlink-permission skip**, targeted mypy/Ruff/docs clean. This slice does **not** mark D/E, native end-to-end, or acceptance gates A1–A18 complete.

## Canonical boundaries

`meridian/attempt_resolution_coordinator.py` is an orchestration shell. It owns neither #30 nor #31 immutable history, current pointer, permission, Core roster, policy, journal, Grade, Standards, nor producer records. Each actual write stays in its existing #122 `PreparedGuidedAction` using the established writer, CAS selection, receipt and independent canonical readback. #30's record is already required to be selected and operative **before** D2B1 may prepare #31. No new academic transaction engine or implicit relationship store is introduced.

### Preparation — read-only

1. Accept the typed C teacher testimony (`teacher_reviewed_reassessment`), exact A/B authorized view, one selected #30 policy preset already `ready`, typed prospective D2A #31 review and #121 attribution. Check publication currentness and exact work/source identity.
2. Reconstruct C's exact testimony from the *current authorized inventory*. Reject any mismatch in roster identity, evidence, selected current decision, original/corrected interpretation or projected source.
3. Check current separately selected #31 policy **and** its mode, exact decision history and CAS pointer witness. Any already-persisted target requires **recovery**, not a newly forged authoring preview.
4. Request the existing #30 immutable authoring preview and #122 action, verify their exact proposed revision/digest/actor/policy/previous selection, and verify D2A's future #31 revision/digest binds those exact bytes. No #31 action is prepared here because its canonical dependency (#30 current) does not yet exist.

### One confirmation, two independently verified writes

- Cancel delegates to #122 cancellation of #30; it cannot write either record. One in-memory plan is single-use to avoid a second author operation.
- Immediately before a confirmed save, repeat exact inventory/teacher-witness and #31 policy/history/current checks. #30's guarded #122 action then runs *once*.
- Require the #30 action's canonical `current_state == matches` with exact record, then re-read the current #30 projection (revision, digest, source, operative eligibility, selected attempt **identities**). An error, stale record, unverified selection or selected count alone cannot proceed to #31.
- Only after verified #30 currentness, prepare D2B1's #31 action. D2B1 independently checks actor, selected #30 digest, #31 policy, period/membership/current source and revision/CAS witnesses. Apply that #31 action once.
- Require D2B1's independent #31 observation and one more pair of independent #30/#31 canonical reads before returning `applied_current` or `already_current`. Neither the #122 receipt nor a success string is sufficient to claim success.
- All ambiguous outcomes, #31 history collision, independent readback errors, CAS drift or a #31 immutable write without current selection return **not successful**. No Grade, Standard or result publication is invoked.

### Partial writes and recovery

The two writes are **not atomic**. A process can stop with #30 current and #31 absent, or with #31 written but not current. This is not a rollback. This slice includes two deliberately different capabilities:

1. `PreparedMultiAttemptResolution.resume(confirmed=True)` continues the **same in-memory reviewed plan** only after it previously verified #30 as operative current and after it rechecks that exact current #30. It never calls #30 authoring or selection again. If the #31 action was already attempted, it uses the original `PreparedGuidedAction.resume` / #122 exact-selection recovery rather than `apply` again. If #31 was not yet prepared and has no history target, it may prepare the first #31 action against the unchanged original review. It requires a separate explicit confirmation.
2. `assess_multi_attempt_recovery` is **read-only** for process restart, classifying `upstream_not_current`, `upstream_current_reassessment_missing`, `reassessment_written_not_current`, `pair_current`, `conflict_requires_review`, and `current_unverified`. It never emits a replay permit (`can_replay_automatically == False`), never reconstructs an action ID or journal, and never edits either pointer. An operator must use #122 canonical receipt/recovery and E's subsequently qualified restart workflow before restarting a mutation.

A source withdrawal, roster authorization or selected-revision change must invalidate an apparent prior review; simply reusing old `GuidedProjectionResult` does not grant fresh authorization. The existing #30/#31 resolvers are the source of truth. All source observations are treated as historical unless revalidated for current use by their canonical services.

### Tests and limits

`tests/test_issue126_sliced2b2_multi_attempt_coordinator.py` uses synthetic 29×6 ScoreForm scenario IDs and fake action ports to exercise confirmation, exact two-stage readback, cancellation, upstream failure/exception/uncertainty, #31 preparation failure, #31 writer interruption, #31 written-not-current resume, cross-action no-repeat, source/policy drift, and read-only recovery classifications. Existing focused #30/#31/#122 storage suites remain indispensable for canonical journal, filesystem and Windows behavior. These synthetic tests **do not** constitute a real native ScoreForm classroom journey, Windows receipt interruption test, or end-to-end implementation of issue #126.

**Next:** Slice E — durable cross-process receipt discovery, restart/reconciliation, and native interruption acceptance. Slices F–J remain necessary for teacher navigation, Core/Suite, downstream evidence, release wheels and final A1–A18 acceptance.
