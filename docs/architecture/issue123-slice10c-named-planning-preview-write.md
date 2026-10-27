# Meridian #123 — Slice 10C: Save Planning Preview by derivation name

## Boundary

The teacher chooses a verified class and **one saved immutable Planning Derivation** via `PlanningDerivationChoiceCatalog` (the title of the bound grouping policy, historical marking period and school year, Standard, cohort size, band count). No current-policy guess or automatic recent-derivation selection is permitted. The transient `TeacherChoice` retains the canonical derivation identity and both derivation/policy SHA-256 hashes; no raw ID entry occurs.

The existing `PlanningSignalPreviewWritePreview` service loads and verifies the **exact saved** derivation reference, and the existing `commit_planning_signal_preview_write` rereads its exact immutable source before the #39 preview generation. The new controller checks class/year and choice witness before and after preparing, and again immediately before invoking the committer. A changed choice blocks the operation rather than substituting a newer saved derivation.

## Teacher action

A clear review screen displays the policy title, period, Standard, dimension, bands, roster/contributing/noncontributing counts and the fact that this is a *saved* source. The only accepted authorization is exactly `WRITE`, not `write`, `Y`, or a row selection. `T` displays technical source identifiers, hashes, and calculation fingerprint; `B`/blank cancels; `M`/`Q` retain Core navigation semantics.

The existing persistence service remains the *sole* authority for source validation and canonical #39 writes. No review is authored, selected or inferred; no Core signal, CSV, or Concord grouping is created. A confirmed write may have happened even if a post-commit explanation check fails; the teacher is told to inspect saved previews before retrying, not incorrectly told that no mutation occurred.

## Compatibility and qualification

- Existing Planning Signal actions 1–7 remain unchanged and marked Advanced when teacher navigation is available; uncontextualized legacy callers retain original choices.
- New teacher-context option **10. Save Planning Preview by derivation name** is additive to options 8 and 9.
- Existing #110 prompt quarantine, #121 teacher context, #122 action recovery, and cross-module teacher reports remain unchanged.
- Tests cover cancel, explicit confirmation, technical view, prepared source mismatch, stale exact choice, policy/revision/derivation digests, bad result semantics, Core navigation, safe error handling, and menu compatibility.
- No new persistence schema, public Core APIs, academic inference, or automatic teacher group creation.

## Next

Slice 10D: teacher-named saved Planning Preview diagnostics, before named teacher review authoring, review selection, and exact Core export. Issue #123 requires additional final cross-menu and installed-wheel acceptance beyond this slice.
