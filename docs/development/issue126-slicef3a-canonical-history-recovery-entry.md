# Meridian #126 — F3A: Canonical decision history and bounded recovery entry

**Branch baseline:** `39c9d85f4140628d98df2ce8cb0af991ffc03935` (accepted F2B)
**Scope:** Meridian-owned interactive teacher menus and read-only #30/#31 storage.
**Evidence level:** D1 source and targeted Windows tests pending execution; *not* an installed end-to-end classroom-journey claim.

## Teacher outcome

The authorized **Review Corrections & Attempts** queue continues to present the native source history under `H`. F3A adds **D. Canonical #30/#31 decision history** inside each authorized student review. This is deliberately distinct from the ScoreForm attempt history: an attempt is producer evidence, while a #30/#31 record is the teacher-attributed, immutable academic interpretation. F3A does not rewrite either.

Both the queue and the student screen add **I. Review interrupted saves**. This opens the *existing*, class-scoped #122 journal only after an explicit second choice. The menu states that the journal spans the class, is not canonical proof, and its current direct resume choices do not include #31. It does not manufacture a new #31 recovery authority. The #122 menu retains its original, individually confirmed #30 recovery semantics.

## Read-only history invariants

1. Require an absolute root, typed authorized projection, current reusable publication, included membership, exact source snapshot/cache/work, and one student already present in the authorized roster projection. Never enumerate other students, or infer any student identity from native attempt labels.
2. Reuse the **public canonical storage** `list_*_decision_revisions`, `load_*_decision_revision`, and `load_current_*_decision` APIs; no private ScoreForm/Quillan/Concord reads. All histories must be contiguous, bounded to 128 revisions per family and match class, Grade Item, work, student and revision. One invalid record fails the whole view closed.
3. Corroborate stored current-pointer revision/digest against the loaded immutable history. Detect a #30 current-pointer drift from the assessment inventory before showing history. Reject a #31 revision whose exact #30 revision/digest is not in the student's validated immutable history.
4. Mark a stored pointer only as a *pointer*. It does **not** mean that its source remains operatively eligible or its reassessment relationship is academically current. Label historical #30 source snapshots different from the reviewed publication. Do not declare a #31 relationship resolved from a pointer alone.
5. Do not reveal exact digests by default. Technical Details require explicit `T`; ordinary view shows bounded teacher labels, revisions, selected-count and relationship mode, never raw student IDs, receipt IDs, actor profile digests or rationales. Sanitize terminal-control characters and bound paging to 12 records.
6. Returning from decision history or the class journal forces a fresh authorized assessment inventory projection; no stale queue selection is reused.

## Recovery boundary

- **F3A:** link to existing class-wide #122 receipt inspection, with explicit caveat for #31 and cancellation. The class journal is not student-specific, and its receipt phases are recovery clues only.
- **F3B (not yet implemented):** reconstitute exact reviewed #30/#31 intention, original #31 receipt and authoritative current source for the E1/E2A/E2B cross-process recovery services. Do not offer a `RESUME` option from a checkpoint without the original token, exact CAS baseline and current dependency revalidation. Independently verify both selections before Standards continuation.
- **No policy write / no Grade write:** F3A has no author, selection, ScoreForm publication, evidence eligibility, Standards or Grade mutation port.

## Navigation and UI

- Student: `C` explicit correction, `S` explicit reassessment, `H` native source history, `D` canonical #30/#31 history, `I` class journal, `T` existing Technical Details, `R` refresh, and shared `B/M/Q`.
- Queue: `I` class journal, `A/E` view toggle, `N/P` bounded pages, `R` refresh, `B/M/Q` standard navigation.
- History: `T` exact-digest display for the authorized student, `N/P` bounded pagination, `B/M/Q`. Free-text rationale and shared `:notes` are never intercepted.
- Recovery: a separate explicit `1` opens the established #122 menu; `2`/`B` cancel with no action; `M/Q` propagate via Core.

## Targeted acceptance and deferred gates

Synthetic regression fixtures cover typed history composition, exact source and student scope, hidden digest, historical source mismatch, current-pointer drift, missing upstream #30 provenance, corrupted read, history bounds and pagination, technical toggle, class-journal explicit entry/cancel and preflight rejection, F1 queue/student dispatch and refresh, and Core navigation. Regressions include F2A/B, the F1 Evidence Inbox and prior #126 interruption/receipt tests.

This source-focused acceptance provides partial evidence toward A8, A11, A12, A14 and A16. **Not qualified by F3A:** native installed ScoreForm 29×6 scenario (A3/I), full #31 restart UI (A14), Standards handoff (A12/F3B), Core shared UI D2/D3 (A16/G), Report 9 consumers (A17/H), complete installed-wheel/CI matrix (A18/J).

**Expected accepted commit:** `feat(meridian): review canonical student history and class recovery entry (#126 F3A)`; no merge or issue closure.
