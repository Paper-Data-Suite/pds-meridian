# Issue #122 · Slice 6 — Guided proficiency single-save

**Scope:** Teacher-guided proficiency result only. Builds on commits `32c3b84` (typed contract), `fd9c8e0` (durable receipts), `ea422bf` (orchestration), `4123e6a` (Grade Items/eligibility), and `9806d8c` (attempts/Standards).

## Teacher-facing behavior

A read-only calculation preview remains available without any academic mutation. A teacher who chooses to continue supplies existing #121 attribution and sees one final **Save and make current** choice. That one confirmation orchestrates immutable persistence, exact current selection, independent verification, and durable action receipt checkpoints. No separate post-write **Make Current** prompt appears. Only an interrupted `written_not_current` action may explicitly offer **Resume selecting this exact saved decision**, never a blind re-write.

One exact student, Grade Item, Standard, calculation policy, mapping source, source publication, scale, and reviewed calculation are bound. This guided adapter explicitly requires exactly one evidence binding; advanced workflows retain their independent multi-evidence calculation capabilities. A calculated result does not acquire a different interpretation, policy, or proficiency level by this UI change.

## Domain authority and recovery

- The canonical immutable snapshot is serialized by `standard_proficiency_result_snapshot_to_json_bytes`; its SHA-256 is the reviewed write/selection target. Journal receipts are not academic source-of-truth.
- The existing `commit_guided_proficiency_result` revalidates its bounded calculation before writing; `preview_guided_proficiency_selection` and `commit_guided_proficiency_selection` use the existing CAS-protected current pointer. Rechecking the selector baseline and returned digest is mandatory.
- The revalidation port requires the saved #121 identity fingerprint, selected Grade Item digest, included work membership and its academic calendar, current policy and scale references, and fresh exact calculation/evidence bindings to match the reviewed input and outcome. A new immutable history revision is tolerated only when it is the exact reviewed target (for interrupted-write reconciliation).
- Canonical current loading and the exact persisted digest independently verify a successful selection; user-visible success is not inferred from a journal checkpoint or menu navigation.
- Recovery does **not** repeat the authoring call if the target already exists. Conflicts, corrupt receipts, changing policy/membership/publication, stale selectors, or missing permissions require review. The filesystem is not represented as a multi-file atomic transaction.
- The `TeacherActionReceiptStore` lives beneath the explicitly selected workspace and class, with its own path and lock guards. No district/student real data is used by these slice tests.

## Compatibility and qualification

This slice only changes the guided proficiency menu and adds one adapter and synthetic tests. The advanced CLI author/select entry points and historic revisions remain unchanged. The exact wheel runtime allowlist gains `meridian/teacher_action_proficiency.py`. The baseline gate requires a clean, unmodified branch `Paper-Data-Suite/pds-meridian` at `9806d8cd074ec4a3a34f64a78084a4454098053f`. Ruff, strict mypy, focused tests, and staged diff validation must pass before auto-commit/push. Full suite and installed-wheel qualification belong in the final release slice.

**Known remaining integration gap:** Cross-process discovery and human-readable navigation of interrupted receipt records after a restart are not exposed by this slice. Slices 7+ must close that gap before #122 is considered complete. Separate policy creation/change remains a distinct, explicitly authorized academic decision.
