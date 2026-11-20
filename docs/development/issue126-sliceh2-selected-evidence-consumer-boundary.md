# Meridian #126 H2 — selected-evidence consumer contract and bounded authority review

**Accepted baseline:** `6fb1bb398085ef33d8aa54564018dac79269b44f` (H1).

**Scope:** Source-level and installed-Core/source-checkout contract witness. This slice adds synthetic tests and a boundary note. It does not change canonical #29/#30/#31 stores, Grade Items, Standards/proficiency calculations, Report 9, Core, Suite, or producer modules.

## 1. Three different authorities must not be conflated

1. **Producer-native evidence item:** `TeacherEvidenceReviewItem.item_id` is exact evidence identity in one authorized snapshot. Selecting a row is not an operative academic-attempt decision.
2. **Canonical operative attempt:** `resolve_current_attempt_selection` and current #30 storage determine which producer-native attempt is currently operative, with #29 inclusion and precise source/policy/membership checks. Multiple operative attempts require a separately exact #31 relationship; neither number nor score defines treatment.
3. **Downstream consumer:** A Standards review, calculation preview, or benchmark report must revalidate its own authorization and applicable exact source/canonical selection. A mere selected row, prior menu status, or receipt cannot be substituted for current #30/#31 verification.

The F3B1 `verify_student_current_use` function reauthorizes and checks the exact selected #30 revision, #31 when multi-selected, and included evidence per selected attempt. `_review_evidence` subsequently filters to the selected student's included item IDs and rejects duplicate/ambiguous/out-of-source choices. These guarantees are **local to the verified F3B1 continuation**; they are not automatically inherited by another menu or report.

## 2. Actual H2 consumer boundaries

| Consumer | Exact observed behavior | Safe claim / limitation |
| --- | --- | --- |
| `attempt_decisions_workflow.project_attempt_decisions` | Resolves #30 via `resolve_current_attempt_selection(..., authorized_snapshot=...)`, preserves typed selected/none/stale/unsupported distinctions | Read-only canonical status; no new selection or Grade |
| `menu_teacher_verified_continuation.verify_student_current_use` | Fresh authorized assessment, current #30, #31 if multi-selected, per-attempt included #29 evidence | Validated **entry** to the existing Standards menu; not transferable authority for future calculations |
| `menu_teacher_verified_continuation._review_evidence` | Filters an exact `TeacherEvidenceReview` to currently included selected item IDs for one authorized student; checks work and publication | Historical, shared, foreign-student, duplicate and oversized rows never become offered choices |
| `guided_proficiency._selected_evidence_item` | Resolves a teacher-selected item ID exactly within the *supplied* projection and matches its student | Does **not** independently resolve #30, #31 or #29; an item lookup alone is not a current attempt decision |
| `guided_proficiency.build_guided_proficiency_preview` | Sends exactly one item-bound `StandardAggregationCandidateBinding` with `attempt=None` to the existing #34 preview builder | Represents a teacher-chosen item-specific preview; does **not** certify multi-attempt weighting/replacement or an automatically operative attempt |
| `report_menu_execution._benchmark_item_observations` and `benchmark_current_analysis` | Respect distinct native targets and conservatively omit ambiguous multi-attempt question observations | #133 owns Report 9 generation; #134 owns positive corrected-Attempt-2 item/statistical calculation, not #126 H2 |

No audited path establishes that `attempt=None` is equivalent to the #30 selected attempt, or that a selected Standards evidence row alone can authorize a proficiency result for several performances. **Do not present that as qualified.** If a future #34 consumer requires a genuinely attempt-level aggregation, it must bind the exact #30 (and #31 where applicable) through a separately reviewed change and focused positive tests. Existing directly chosen evidence behavior is not broadened by H2.

## 3. Executable H2 regression bounds

`tests/test_issue126_sliceh2_selected_evidence_consumer_contract.py` covers:

- Exact item and student identity; missing, duplicate, shared and cross-student rejection in the guided item lookup.
- Strict F3B1 Standards choice filtering: historical item remains visible in source history but is never offered as an operative choice; another student's row is not inherited; duplicates, mismatched publication and empty choices fail closed.
- The item-specific guided proficiency preview passes a single exact source and an explicitly attempt-neutral binding into its existing preview-builder seam; no persistence or academic action is invoked.

This is a **negative/contract boundary test**, not a generated Grade or a native end-to-end ScoreForm run. It intentionally does not claim that generic guided proficiency, Report 9, or a published Core teacher-UI release is fully #30/#31-aware. H1 separately owns the reproducible 29-by-six Report 9 counterexample and #133/#134 handoff.

## 4. Ownership and closure ledger

**H2 complete when:** source contracts and synthetic regression are accepted against the exact H1 baseline; the existing Core 0.6.6 and Meridian checkout are probed; no academic source file changes; docs/Ruff/mypy/pytest/Git gates pass. This closes **Slice H's source-audit and boundary-contract work**, not Issues #133/#134, and not #126's A1–A18 overall release acceptance.

**Remaining:** Slice I must run installed synthetic/native ScoreForm 29-student six-question corrections and Quillan/Concord boundaries, measure menu interactions, and verify no collateral writes. Slice J requires the complete validator, wheel/sdist/Twine, official-wheel composition, CI matrix, and final A1–A18 evidence ledger. D2 future published Core v1 header, D3 released Meridian consumer and D4 mixed Suite wheels remain separately qualified or explicitly unsupported until tested.
