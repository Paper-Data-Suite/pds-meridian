# Meridian #126 — E2A: exact original #31 selection after process restart

**Accepted baseline:** `da18f841e9e0b609abb67e2067aad5ec90e72ece` (E1). **Branch:** `126-verified-correction-attempt-reassessment-management`.

## One narrow, executable recovery case

E1's read-only `inspect_durable_pair_recovery` identifies whether #30 is current and whether #31 is absent, written but not selected, or already operative. E2A implements one **explicitly confirmed** continuation **only when the exact immutable #31 decision exists and is verified written but not current**. It does not revive the original in-memory coordinator or author a new #30/#31 decision.

A recovered #31 receipt must be the single unambiguous original class-scoped #122 action and must have:

- The reviewed candidate revision/digest, prior current-pointer revision/digest and teacher attribution.
- A completed `write` checkpoint and an exact observed immutable target record. `prepared` alone, an uncertain write, or a missing/duplicate receipt is insufficient.
- Canonical current #30 source, included eligibility and an independently current reassessment policy, as revalidated by existing #31 services.
- A canonical `reassessment_written_not_current` E1 assessment, with no source/current-pointer/journal ambiguity.

The service reads the **original** action ID; it never creates a substitute durable receipt or interprets a fresh action ID as equivalent. It builds a new *read-only* current #31 port using the canonical `prepare_reviewed_reassessment_action`, which independently revalidates actor, work, source, academic period, policy and #30 selected decision. Every field of the newly computed `TeacherActionPreview` must equal the original journal's preview **except the random action ID**; the deterministic intention digest must be identical. A constrained recovery port forwards only `revalidate_basis`, `observe`, and `select_exact` to that freshly verified authority; it **rejects immutable authoring**. The existing `resume_exact_teacher_selection` engine then reloads and checks the original receipt, exact immutable revision, and CAS baseline before any selection.

Immediately before resuming, E2A rereads E1's complete canonical/journal assessment and the original receipt, requiring identical receipt content and the original exact action ID. A second execution of the same prepared recovery object is refused. Cancellation never touches canonical or journal state.

After resume, E2A requires an applied/already-applied typed #122 result with exact target confirmation, independent #31 operative readback, and an independent **pair** assessment in which both canonical #30/#31 records are exact/current. Only then may the teacher proceed toward Standards review. Unknown write/selection outcomes, changed generation, new CAS state, withdrawn projection, missing authorization, unreadable journal or failed readback are never reported as applied.

## Important limits

- **No automatic retries.** Confirmation is explicit; a failed/uncertain attempt requires renewed inspection and review.
- **No new #31 decision after restart.** When #31 was never written, E2A cannot invent a recovery token. That case needs a separate reviewed new-action flow (subsequent E2B). Likewise E2A does not resume a #30 write; it requires the exact #30 decision already current.
- **No two-record atomicity.** #30 and #31 remain distinct authoritative records and CAS pointers; the journal is subordinate recovery evidence. No grade, Standard, proficiency, producer, SIS or Note write is performed here.
- **No menu/installed-native claim.** E2A is an internal service, not the teacher-facing queue. Real ScoreForm and official-wheel qualification, simulated process crashes and final A1–A18 acceptance remain pending later slices.

## Acceptance and regressions

`tests/test_issue126_slicee2a_exact_restart.py` exercises a synthetic #30/#31 review and typed #122 receipt, exact source/actor binding, original ID forwarding, cancellation, one-use guard, absent/ambiguous/replaced journal, write-checkpoint requirements, changed current #30, changed action preview, denial/exception and postresume independent readback. It uses controlled service seams to avoid mutating a real teacher workspace; canonical #122 and #31 storage regressions remain part of the Windows qualification runner.

The service is purposely smaller than a new cross-record transaction manager. E2B will support a separate **new** #31 action when #30 is verified current but #31 was genuinely never written, without replaying an unknown prior #31 writer. Slice E's native fault-injection qualification remains open until E2B and restart tests are accepted.
