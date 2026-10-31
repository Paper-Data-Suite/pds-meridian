# Meridian #123 — Slice 7E: Create a Reporting Definition by Name

**Base:** `c3304a47a5909ad9aa775c881206432d322bc208`
**Branch:** `123-teacher-first-navigation-existing-menus`

## Teacher workflow

The teacher-context Snapshots menu appends **11. Create a new reporting definition**. Teachers choose a verified Core class and marking period, enter a human-readable report title and purpose, provide an optional creation reason, and supply attribution through the existing teacher-identity adapter. No class ID, academic-period ID, definition-family ID, revision, hash, or filesystem path is manually entered. If an existing definition has the same title in that class/period (case-insensitive), creation fails closed with guidance to review or revise existing definitions.

A locally generated `report-` plus 32 lowercase hexadecimal digits uses 128 bits of OS-backed cryptographic randomness via Python `secrets.token_hex(16)`. This path-safe opaque identity is checked before use and never displayed as a teacher input. The generated identity is fixed across both previews; collisions with existing definition families block the write rather than silently generate or target another record. This requires no Core schema change or new service contract.

## Write boundary and verification

The controller delegates to the existing injected `SnapshotMenuDependencies.definition_previewer`, `definition_committer`, and clock. The canonical preview constructs revision **1**, no predecessor, teacher audience, grade-report kind, selected period, explicit actor, rationale, and exact title and purpose. The controller validates both plan fields and canonical candidate/reference digest, then rereads class/period availability and the definition inventory before and after review. `WRITE` is required for any write. After confirmation it repeats preview and checks exact equality, including timestamp and digest.

The existing immutable storage service supplies atomic relation locking, canonical-byte conflict checks, and first-revision validation. A newly written revision is confirmed via fresh canonical definition enumeration with exact identity, revision, digest, title, purpose and period. Any unexpected disposition or post-write read failure is reported as **uncertain**, never as a rollback or proof of absence. No ReportingSnapshot freeze, current-selection change, protected producer evidence read, export, or district/SIS update occurs.

The generated opaque family identity is not persisted in teacher preferences. The process-local class and period retain the existing currentness invalidation and standard B/M/Q handling. Historical Snapshots options 1–10 and no-context options 1–6 remain unchanged. Advanced exact-record creation remains supported.

## Qualification

- New controller, focused synthetic tests, architecture note and one anchored edit to `meridian/menu_snapshots.py`.
- No new literal raw-ID prompt sites: existing `Teacher actor ID: ` bridge is referenced via a constant. The Issue #110 baseline remains unchanged.
- Focused tests cover successful creation, purpose and actor binding, cancel/no-op, duplicate titles and IDs, invalid generated identities, stale scope/preview, malformed digest, uncertain writes and post-write verification, navigation exceptions, and absence of silent snapshot changes.
- The separately distributed runner requires the exact pinned Git branch/base/source blob, clean worktree and remote equality; verifies ZIP and manifest content digests; runs Ruff, strict mypy, frozen #123 route inventory and three regression groups; checks exact staged scope/whitespace before committing or normal push.

## Deferred

Construction/freezing of a ReportingSnapshot from a fully guided build request remains explicitly Advanced until all source, authorization, and evidence requirements can be captured without weakening the canonical workflow. Export, Explain, and Planning Signal navigation remain separate portions of #123.
