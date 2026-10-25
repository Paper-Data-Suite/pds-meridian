# Meridian #123 Slice 7D — Guided Reporting Definition Revision

**Base:** `a172d0128cb5590e4d1a8a94d91f61dc9ef532c3`
**Branch:** `123-teacher-first-navigation-existing-menus`

## Teacher task

The teacher-context Snapshots menu adds **10. Revise an existing reporting definition by name**. The existing routes 1–9 retain their numbering. The legacy no-context menu retains routes 1–6. Option 5 remains Advanced for exact-record authoring, including deliberate creation of a new definition family.

Choose a verified class and current marking period, then a named latest Reporting Definition revision. The chooser uses the existing bounded, refreshed `NamedDefinitionCatalog` and displays title, purpose, period, revision, and update time. The selected canonical family identity and digest remain internal. Definitions with no frozen ReportingSnapshot are eligible. Only definitions belonging to the chosen school year/period are listed; another period is never silently substituted.

Enter a new title and/or purpose. Enter retains an unchanged field; changing neither does not write a revision. Supply an optional rationale and the existing saved teacher attribution. The exact `Teacher actor ID: ` adapter prompt is bound to a symbolic constant rather than adding a literal raw-ID prompt site under frozen Issue #110.

## Authority and write boundary

The new controller injects existing `SnapshotMenuDependencies.definition_previewer`, `definition_committer`, and clock. It never authors a source record itself and never performs a direct filesystem write. Before display, before and after preview, and after confirmation it revalidates verified class/current period, period choice, and the latest exact named definition revision/digest.

The canonical existing preview builds an immutable candidate bound to the existing family with `definition_revision = prior + 1` and the exact `supersedes_revision`. The controller cross-checks its candidate, teacher, rationale, title, purpose, period, timestamp, calculated reference digest, and prior revision. After `WRITE`, it regenerates the exact preview and rejects any change. The existing storage committer enforces contiguous immutable history and conflicts on changed prior history. No UI-side CAS shortcut or actor impersonation is introduced.

A successful write is confirmed with a fresh authoritative definition lister read matching the new revision, digest, title, purpose, and period. Failures after invoking the committer are described as **uncertain**, never as a rollback or definite absence of a write. Before invocation, failures report **no write attempted**. No snapshot freeze, current-use selection, report export, district/SIS update, or protected producer-evidence read occurs.

## Compatibility and tests

- New narrow controller and focused adversarial tests; no changes to canonical schema, storage, Core navigation, or existing `B/M/Q` behavior.
- Maintains existing Snapshots options 1–9 and no-context options 1–6.
- Updates the historical Slice 7B static menu-range assertion to require a valid, numbered range covering its original option 8, without pinning future appended options.
- Frozen Issue #110 raw-ID prompt inventory remains unchanged; technical ids/digests are not teacher-entered.
- Twenty-three focused synthetic tests exercise create/keep/cancel, stale and mismatched previews, teacher attribution, digest/currentness, failed/uncertain writes, no snapshot mutations, and global navigation.
- The guarded Windows runner qualifies Ruff, strict mypy, frozen Slice 1 audit, focused tests, and historical regression groups before an exact-scope commit and normal push. Full repository qualification is performed by the teacher workstation.

## Deferred

The creation of a **new** definition family without manually entering a canonical ID needs a separately reviewed identity-generation seam. Building or freezing snapshots from a complete guided report request remains Advanced-only until its authorization and canonical request inputs are fully supported.
