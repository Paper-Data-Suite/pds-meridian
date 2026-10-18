# Issue #122 — Slice 7: safe post-restart action discovery

**Baseline:** `Paper-Data-Suite/pds-meridian` at `1f0d2a6` (Slice 6).

## Purpose

A teacher can now open **R. Review Interrupted Saves** from the main menu,
including after restarting the program. This screen is an **inspection-only
recovery inbox**, deliberately not a new way to authorize writes or to invoke
a second selection. All nine existing task numbers remain unchanged.

### Safety boundary

- The class is chosen from the existing transient classroom context or entered
  explicitly, and its Core class metadata is validated.
- The class-local receipt journal is enumerated without creating directories,
  lock files, new receipts, or academic files. JSON must be bounded, canonical,
  digest-verified and class-scoped. Unknown filenames, incomplete temp files,
  symlinks/reparse points, oversized records and malformed entries fail closed;
  there is **no partial-success inventory** that hides unreadable actions.
- Entries present **checkpoint history**, not verified academic outcomes.
  An apparently finalized receipt is *not* proof that the current canonical
  record is still selected. Copied journals whose workspace-path fingerprint
  differs are flagged for manual review.
- The list contains no student identifiers, teacher actor names, source
  publications, evidence contents, canonical decision IDs or source hashes.
  Selection is by transient ordinal, not copied filesystem identifiers.
- The screen does not apply, resume, delete, repair, infer permissions,
  create new revisions, or alter current pointers.

### Unresolved before #122 completion

Hash-only receipts intentionally cannot reconstruct every authorization scope,
student identity and source binding on restart. **This slice does not implement
post-restart automatic RESUME.** A later qualification slice must define and
test exact-source rehydration for each action family with fresh Core,
publication-authorization, membership, actor and canonical CAS verification.
Until then, teacher-facing advice is to inspect the relevant current workflow
before considering any new write. The in-session exact-action recovery paths
from Slices 4–6 remain available unchanged.

### Focused acceptance

1. Normal current program tasks and advanced author/select commands retain
   their existing routes.
2. Empty journal scans do not create any directory or lock.
3. Interrupted saves appear after constructing a fresh store instance.
4. A finalized checkpoint is labeled as a journal observation, not a verified
   current academic outcome.
5. Corrupt/linked/unexpected journal entries cause the complete scan to fail
   closed; the UI does not silently claim no interrupted saves exist.
6. No student, teacher, source or decision identities leak into the screen.
7. Tests are synthetic and never resolve the district OneDrive workspace.
