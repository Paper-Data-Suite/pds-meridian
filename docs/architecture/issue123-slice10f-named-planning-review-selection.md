# Issue #123 Slice 10F — Select a saved Planning Review by name

## Scope

Adds the teacher-context **13. Select a saved Planning Review by name** operation to the existing Create Planning Signal menu. Existing exact-record choice **6. Advanced: Select teacher review** and all other legacy routes remain accessible, with their injected dependencies and CLI semantics unchanged. No new top-level menu is introduced.

## Read authority and selection

- Use Core-authoritative verified class/year context through `TeacherNavigationContext` and `TeacherAcademicChoiceCatalog`.
- Choose a verified saved Planning Preview by policy title, academic period, Standard, band configuration and cohort count through the existing read-only `PlanningPreviewChoiceCatalog`.
- Read immutable review history from `list_grouping_signal_review_revisions`; load exact revisions through `load_grouping_signal_review_revision`, filtering revisions to the *exact selected preview*, not merely the same derivation. A different preview can share a derivation's review history.
- Revalidate the saved preview/derivation/policy lineage and explicitly selected review pointer, and carry the exact review revision, digest, decision, timestamp and current selector internally. Display does not use canonical identifiers for routine selection.
- Preserve bounded, Unicode-safe search, pagination, back/main/quit and technical details under `T`.

## Consequential boundary

The teacher sees the exact historical decision, revision, currently selected revision and **live applicability**. A historically accepted decision may be stale; selecting it does not imply current Core-export eligibility. Only exact `SELECT` authorizes the stored-review selection. The existing `preview_planning_signal_review_selection` service validates the canonical target and applicability; `commit_planning_signal_review_selection` performs the canonical CAS against the expected current revision.

The UI does not write a review, call `select_grouping_signal_review_revision` directly, export a signal to Core, generate CSV, create Concord clusters, alter Grades or invent assignments. After a commit attempt with unverifiable outcome, the teacher is explicitly warned to check current selection before retrying.

## Qualification

A focused suite covers exact happy-path selection, cancellation, exact `SELECT`, technical provenance, historical revision filtering, wrong class/year/preview/derivation, malformed or changing witnesses, projected target/currentness mismatch, stale selector before confirmation, result mismatch, fail-closed redaction, canonical navigation propagation and preservation of Advanced route. The guarded runner adds the canonical review-selection workflow, CLI and review-storage regressions to the existing Slice 10E suites. All baseline Ruff, strict mypy, frozen #123 audit and three regression groups must pass before commit.
