# Meridian #123 — Slice 10E: Author a teacher Planning Review by saved-preview name

## Scope and authority

The teacher-context Planning Signal menu adds **12. Author Planning Review by preview name**. The seven original exact-ID commands remain reachable and labeled Advanced; direct callers without the teacher context preserve their existing menu contract.

A teacher chooses a verified class and a saved Planning Preview using the existing `PlanningPreviewChoiceCatalog` (read-only verified immutable preview and derivation/policy lineage plus selected-review pointer). Choice labels use the actual policy title, period, Standard, cohort, and bands; no manual preview ID or digest is required. Existing `TeacherAttributionInput` supplies the active teacher identity through its established `Teacher actor ID: ` interception; direct callers retain the exact legacy attribution prompt.

## Deliberate, separate decisions

1. Reload the exact selected preview, policy/derivation lineage, historical class and school-year context, and selected-review pointer.
2. Project live diagnostics using the existing read-only `PlanningSignalPreviewDiagnostics` service and verify exact provenance, band coverage, warning/blocking rows and selected-review binding through the Slice 10D checker.
3. Teacher decides **Accept for Core export** or **Reject**. Acceptance is unavailable for a noncurrent/blocked preview. Every warning is displayed and acceptance requires typing `ACK` to acknowledge **all** warning diagnostic IDs; rejection does not acknowledge them.
4. Resolve teacher attribution with existing #121 interception. Invoke existing `preview_planning_signal_review_authoring` with exact immutable preview reference and intentional decision, warning tuple, actor, and timestamp.
5. Revalidate the returned typed candidate against the originally projected preview, decision, warning acknowledgment, actor, review lineage, and selected-review revision. Re-read the class and saved-preview choice.
6. The teacher must type **`WRITE`**, exactly, after reviewing the candidate. Recheck context again and invoke existing `commit_planning_signal_review_authoring`, which itself verifies review history, selected pointer and recorded preview before writing one immutable review revision.
7. Check the returned record and ensure **no selected-review pointer or Core-export action was changed**. If a post-write check fails, report that the write *may* have occurred and instruct the teacher to inspect history before retrying; never misstate it as definitely unwritten.

The candidate and underlying writer, not the display label or temporary UI selection, authorize persistence. A newly authored review is **not selected or exported**; using/selecting a review and Core export remain separate consequential tasks.

## Security/compatibility

- No Core, Concord or other producer APIs are modified. No scan of student private evidence and no student records persist in preferences.
- No new prompts ask teachers for class ID, policy ID, derivation ID, preview ID, review revision, or SHA-256. Technical IDs appear only under **T. Technical details**.
- B/blank cancels; M/Q propagate through the shared menu-navigation exceptions. Incorrect decisions, missing warning ACK, missing actor, and non-`WRITE` confirmation cannot call the commit function.
- Exact stale scopes, changed selected reviews, mismatched candidate authorizations, and inconsistent results fail closed. Source exceptions and sensitive diagnostics are not printed into user-facing error text.
- Retains frozen Issue #123 route/prompt audit (49 routes, 9 reports) and legacy #110 prompt quarantine; tests exercise related #121 attribution and #122 recovery.

## Test focus

The new behavioral test file covers accept/reject, warning acknowledgment, noncurrent/blocked conditions, exact confirmation, cancellation, B/M/Q, changed current class/preview/review pointer, spoofed projection/candidate/result, private exception redaction and no UI-side write. The qualified runner also includes the canonical review-authoring workflow, review storage and workflow, CLI review authoring and earlier Planning Signal/teacher navigation regression groups.

## Follow-up

The remaining teacher-first Planning Signal operations are **selected-review application** and **Core grouping-signal export**, followed by the complete eight-menu adoption inventory and installed cross-menu acceptance for Issue #123. This slice is not independently a sign-off for the full issue.
