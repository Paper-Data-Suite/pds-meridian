# Meridian Issue #117 — Slice 8: Source-bound benchmark-draft restoration

## Teacher-facing behavior

**Reports → 9 → P** retains the original `1. Replace all planning notes` route (the explicit, complete-replacement workflow) and adds `4. Edit latest plan (keep saved sections by default)` when a prior revision exists.

For a Slice-8 saved plan, editing loads an integrity-checked, typed annotation record for the exact latest revision, after the existing source and publication-authorization revalidation. The teacher can keep each previous section with Enter/Y, or enter N and replace it. Sections include interpretation, teacher-classified standards with comparability/basis, complete named roster groups and member identities, teaching responses (status, dates, member identities, rework/retest items and reflection), and follow-up observations. The unchanged sections are carried forward byte-for-byte at the dataclass level. The teacher sees the unsaved preview, then must type **SAVE PLAN**. The normal append-only SHA-256 predecessor and source checks still apply.

An older plan whose original revision lacks the new typed-note record remains readable in the historical plan view; **Edit latest** refuses lossless restoration with a clear message. The teacher can choose action **1** to author a complete replacement revision, retaining full history. No student membership, intervention, or follow-up content is guessed from the lossy existing preview rows.

## Record and compatibility

- Existing `BenchmarkPlanRevision` schema, report serialization, academic data, and all other eight reports remain unchanged.
- Typed annotations are stored in a separate sibling directory of the plan's canonical revision folder, `teacher_annotations/<revision>.json`. This does not pollute `revisions/`, whose exact enumerator rejects unfamiliar entries.
- The canonical JSON is bounded, uses unique keys and exact shape checks, and is bound to the immutable `plan_id`, revision number, **exact saved revision SHA-256**, and the fully typed annotations. Each document has its own SHA-256 sidecar; reads reject checksum mismatch, malformed/noncanonical JSON, symlinks, unexpected content, or missing half-pairs. No plain-text source scans, external exporter, viewer-opening operations, or SIS edits are introduced.
- The annotation save independently verifies that re-rendering the notes exactly reproduces the saved teacher report preview digest. Revisions are immutable and different annotation bytes cannot replace existing notes. Legacy revision paths without both annotation files return **None**; a partially written/invalid pair always fails closed.
- This is an *additive companion record*, not a migration of previously saved plans. Exact student IDs in typed notes are accessible only through the same current authorized benchmark flow; the normal report remains suitable for human-readable/printable exports without hidden metadata rows.

## Transaction qualification and known boundary

The authoritative plan revision writer runs first, followed by the annotation companion write. Both are append-only, but they do **not** form a single atomic transaction. If the plan revision saves and annotation storage subsequently fails (I/O, disk full), the menu explicitly reports that **the revision was saved but its editable draft was not retained**. The saved report remains in history and can be replaced with a complete new draft; it is never falsely reported as wholly unsaved. Interrupted or corrupt annotation commits fail closed at reopen. An eventual combined transactional API could remove this crash window without changing the release's conservative behavior.

No authorization is granted or inferred by the companion record. Every editor entry and source-history operation still uses current `revalidate`, and copied student IDs are checked again against the current Core roster when composing the next revision.

## Tests

Run the new typed-restoration tests plus existing Slice 7 menu and Slice 6 authoring regression tests, followed by scoped Ruff, strict mypy and `git diff --check`. Reserve installed-wheel, Windows workspace, and any conditional Concord #134 viewer-open acceptance for final release qualification. This feature adds no native opener.
