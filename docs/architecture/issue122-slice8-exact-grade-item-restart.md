# Meridian #122 — Slice 8: exact Grade Item restart selection

**Expected baseline:** `Paper-Data-Suite/pds-meridian`, commit `f2e39fc`.

## Supported restart operation

Only an **already persisted, exact Grade Item *creation* revision 1** can be resumed after a restart, from the class-scoped `R. Review Interrupted Saves` inbox. It is never an attempt to repeat the immutable authoring operation. All other record families remain inspection-only: their hash-minimal receipts cannot rehydrate original authorization, individual student/source identity and prerequisite dependencies without guessing.

A recovery action must preserve all of the following independently of journal text:

1. Exact workspace root and Core class registration; complete journal integrity and unchanged receipt generation since inbox display.
2. Original saved actor profile and fingerprint; temporary one-use attribution overrides **cannot** be replayed after restart. Identity labels an actor but does **not** grant evidence access.
3. Original Grade Item family identity, revision 1, candidate hash, typed actor/source basis and absence of work/period context. A revision 2+ or noncreation operation cannot be inferred from a minimal receipt.
4. Complete canonical Grade Item revision history, exactly `(1,)`, with digest sidecar and persisted revision loaded using the existing storage reader. A second/later revision blocks recovery.
5. Existing current pointer must still match the exact reviewed CAS baseline (none). A divergent pointer, corrupt history, altered actor, invalid journal or missing revision blocks selection.
6. A fresh **RESUME** typed by the teacher is required. The same checks are repeated at execution; `resume_exact_teacher_selection` uses the existing canonical selector and independent post-selection read. A concurrent change fails closed through CAS.
7. The restart port's `persist_exact` method **always raises**; the recovery route cannot author a new immutable Grade Item. It does not alter any result from ScoreForm, Quillan, Concord, Portia or Vitrine.

The inbox shows the exact saved Grade Item title **only after** independently loading the canonical record. It shows neither student details, raw identifiers, receipt hashes nor contents. Receipt checkpoints are still not considered canonical truth.

## Deliberate nonfeatures and release gate

- No automatic resume; no automatic retry of an absent or corrupt immutable revision.
- No resurrection of one-use Advanced identity overrides after a restart.
- No restart selection for memberships, eligibility, attempt policies/decisions, standards or proficiency. Those need separate per-family rehydration and permission proofs before the issue can be treated as fully complete.
- No version bump, merge, or release in this patch. A final installed-wheel qualification and full test/CI run remains a separate gate.

## Synthetic validation matrix

Exact creation + persisted revision + unchanged CAS + current saved profile can be resumed after typed confirmation. The tests also cover cancel, absent/corrupt target, alternate current selection, later history, forged family fingerprint, profile change, reused override, and a blocked restart writer. Tests never use the school OneDrive workspace.
