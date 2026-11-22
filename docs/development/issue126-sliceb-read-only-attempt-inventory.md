# Meridian #126 — Slice B: read-only, source-scoped attempt inventory

**Dependency:** #126 Slice A accepted on Windows at `fa8d21e9ef97985929864cf20c39d03305051a95`; 43 baseline tests passed.

**Status:** Source-only implementation candidate. Qualification requires the supplied Windows runner against installed official dependencies before the branch is committed/pushed. No interactive menu, correction-decision writer, or persisted correction-interpretation schema is introduced in B.

## New public service

`meridian.assessment_attempt_inventory.project_assessment_attempt_inventory(workspace_root, grade_item_id=..., prepared=..., class_label=..., assessment_title=...)` uses the already qualified `GuidedProjectionResult` and reuses:

1. #125 `project_assessment_eligibility_review` for the exact authorized Core roster, source, membership, represented item IDs and operative eligibility.
2. The same immutable `prepared.authorized.stored.snapshot.inventory` for source-reported attempts, **including historical excluded evidence**. Source history is never guessed from score change or publication order.
3. #30 `project_attempt_decisions` for each **in-scope** student and actual current operative candidates and selected revisions. Stale/unsupported resolution remains explicit. Source or Grade Item not current means no apparent current selection.
4. #31 `resolve_current_reassessment` only when multiple operative attempts were selected, to expose a separate `resolved`/unresolved relationship state.
5. Pure `build_assessment_attempt_inventory` and `render_assessment_attempt_inventory` for deterministic tests, terminal-safe plain output, attention-first 20-row pagination, optional Technical Details, and no writes.

The model reconstructs the public producer-native attempt **identity** from explicit `target_kind="attempt"` or an explicit attempt parent, and exactly one native `attempt` provenance reference. It rejects conflicting target-to-native identities and candidates missing from the precise source. It does not import private ScoreForm storage, synthesize attempt numbers, or treat Quillan/Concord manifest revisions as attempts.

## Distinguishing facts from judgment

An attempt's `attempt_points` can display `0/6` or `6/6` as a **source fact**, never as a policy. ScoreForm `result_origin="scan_review_manual"` and the presence of a native `review_failure` reference describe producer provenance. Neither certifies which previous attempt was corrected or whether the student sat again. Multiple native attempts are marked `multiple_attempts_relationship_unverified` until Slice C/D obtains explicit teacher-reviewed academic interpretation and consequent selection.

#30 eligibility/selection and #31 reassessment are not folded into a single synthetic state: the output separately exposes source-reported history, `operative_eligible`, `current_selected`, `selection_status`, and optional `reassessment_status`. Excluded Attempt 1 can appear in audit history while corrected Attempt 2 alone is operative/current. Earlier results remain immutable.

## Scope/privacy/concurrency

- A #125 roster scope is enforced before emitting any student. Out-of-scope names and attempt bodies are not rendered, including in Technical Details.
- All source item IDs must equal the **exact** authorized #125 item set. Current projection must agree on student, Grade Item, work and immutable publication/cache/snapshot identity; missing or mixed-source projections fail closed.
- Shared and unmatched observations are counted but never fabricated as student attempts. Missing source projection coverage is reported as **unknown**, not a missed test or zero.
- Current status is observational only. This read-only view is **not** a commit authorization; Slice D must reload/revalidate roster, membership, source, candidate/eligibility, policy and CAS bases at the consequential write boundary.
- This view reads the native attempts preserved **within the selected authorized publication snapshot**. It does not traverse prior Core publications or promise historical aggregation across different source snapshots. That history remains with the canonical producer/Core lifecycle until qualified separate retrieval.
- Read-only operations do not write selection/eligibility, publish ScoreForm state, calculate Standards/proficiency/Grades or create #122 receipts.

## Synthetic focused tests

`tests/test_issue126_sliceb_attempt_inventory.py` covers a 29-student six-question synthetic ScoreForm projection with corrected scan-like `0/6` to `6/6` (original excluded, corrected current), distinct retake, #31 relationship separation, exact authorization scope, producer lacking attempt capability, mixed-source rejection, target/native collision, stale publication current-pointer suppression, paging/Technical Details, empty projection coverage and invalid reassessment scope.

The isolated tests cover **pure composition**. Installed native producer capability, source authorization drift, menu navigation, realistic interactive teacher timing, Windows and Ubuntu release wheels, full mypy and CI are NOT claimed by the source-only test. The Windows runner executes the focused matrix and static checks, then commits/pushes only after success.

## Scope left for future slices

- **C:** minimal attributable teacher interpretation of verified facts vs teacher assertion and genuinely unresolved cause.
- **D/E:** one reviewed write/select with canonical #30/#31, immutable CAS, idempotence and truthful recovery.
- **F:** actual assessment-level menu entry, navigation/continuation, student History and Technical Details UI.
- **G:** qualified Core/Suite header/command adoption; release-aware fallback.
- **H–J:** downstream contract, native installed acceptance and final A1–A18 ledger.

**A1–A18 status:** B supplies partial source-level evidence for A2, A4, A6–A10 and A12. No row is declared completely accepted, and A3 teacher completion, A13–A18 native/integration gates remain open.
