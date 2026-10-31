# Meridian #123 — Slice 7A: Named Frozen ReportingSnapshot Browser

**Baseline:** `bbfff8f0bfcdc76a9ce82974678ac92ba9f89aac` on `123-teacher-first-navigation-existing-menus`.

## Teacher path

The context-aware Snapshots menu adds **7. Browse frozen reporting checkpoints by name**. The existing six exact-record operations remain reachable with their numeric identities and are labeled **Advanced** in the contextual menu. The no-context menu is left unchanged.

The browser chooses a class with the existing verified class chooser, enumerates up to 200 immutable ReportingSnapshots through the existing `SnapshotMenuDependencies.lister`, and resolves each snapshot's title from the *exact* immutable Reporting Definition revision using `load_reporting_definition_revision`. It shows a human-readable report title, school year, creation timestamp, row count, and an informative non-authoritative status. `TeacherChoice` stores the exact snapshot ID and digest in private identity/witness fields rather than prompting for them or printing them in routine review. Existing search, paging, disambiguation and Advanced per-choice technical details remain owned by `select_teacher_choice`.

Selecting a row triggers repeated Core class validation, bounded authoritative list/currentness reads, and **two** calls to the preexisting `SnapshotMenuDependencies.inspector`; an exact item mismatch, changed selection status, or disappeared choice fails closed. Inspection cannot select, freeze, author, export, or mutate a snapshot, grading result, or SIS. A frozen snapshot need not be *currently selected*; the screen states that explicitly.

## Contract and boundary

- A report title comes from the immutable `ReportingDefinitionRevision.title`, never from a snapshot/definition identifier or an inferred file name. Missing/unverifiable definitions block rather than silently guessing a label.
- Catalog enumeration is bounded at 200 class-scoped items and rereads canonical data on selection. It does not cache student records or retain a snapshot as an authority-bearing session property.
- Reporting selection status is read from Meridian's established `inspector`, not inferred from list order, the newest timestamp or history length.
- No protected producer evidence, publication, build request, or authorization is opened by this menu. The existing preview/storage layer owns snapshot integrity and reads.
- Existing exact-ID browsing, selection, definition authoring and JSON build-request freezing remain Advanced. These consequential operations require separate guided workflows and confirmation boundaries in later slices.
- No `read_choice` raw-ID prompt sites are added; the Issue #110 frozen prompt baseline remains unchanged. No global header or shared `:notes` implementation is introduced here; those are Core-owned (#237 implementation, later adoption).

## Qualification

Focused regression coverage includes canonical title provenance; absence of IDs/hashes on routine display; true current/not-current labeling; cancellation before reads; class, snapshot ID/digest, and current-selector invalidation; mid-review disappearing choice; redaction of storage errors; finite scope; B/M/Q propagation; and Advanced/no-context route preservation. The separately packaged guarded runner pins the branch, HEAD, remote, menu blob, exact addition inventory and archive checksum; it runs Ruff, strict mypy, historical navigation audit and three regression groups before conditional commit/push.

**Not completed here:** named snapshot selection and current-definition history views; guarded teacher-driven definition authoring; build-request generation/Freeze; full teacher-first Export/Explain/Planning Signal paths; Core shared header adoption. These remain distinct #123 slices or owner-milestone work.
