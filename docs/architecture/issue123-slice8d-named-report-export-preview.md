# Meridian #123 Slice 8D — Guided local report-export preview

**Base:** `333357b`
**Branch:** `123-teacher-first-navigation-existing-menus`

## Teacher task and safety boundary

The teacher-context Export menu adds **10. Preview a local report export by name**. It does not change options 1–9 or the no-context legacy options 1–6. The teacher chooses a Core-verified class, a verified current marking period, a named *immutable* ReportingSnapshot frozen for the exact school year/period/calendar revision, and a named Export Profile with an explicitly selected current version. All canonical IDs, digests, and revision witnesses remain internal and are revalidated. No data is retargeted merely because labels match.

The existing export preview builder (`ExportMenuDependencies.preview_builder`) retains sole responsibility for constructing the authorized, deterministic export from an exact snapshot digest and currently selected profile revision. The new controller cannot bypass the builder's canonical validation, bounded roster observation, data integrity checks, or source authorization requirements. It checks the preview's exact source IDs and digests, selected profile revision and digest, format, and bounded diagnostic shape. The builder runs twice, with source/selector rechecks, before the read-only summary is shown.

The ordinary teacher screen shows recognized report/profile names, marking period, column labels, file representation, row count, payload byte count, and diagnostic category count. **It deliberately does not print student-level payload text, full file contents, raw IDs, digests, or protected roster data** into routine terminal traces. The legacy Advanced route remains available for deliberate full-payload inspection and exact technical diagnostics.

## Non-effects

This slice **does not** create an ExportReceipt, produce/copy a file, change current profile/snapshot selections, calculate or post a Grade, or update any district/SIS system. A preview does not authorize later export automatically: the later consequential operation must revalidate the exact source and require explicit confirmation, attribution, and receipt disposition. It must not trust this menu's transient preview as write authority.

Currentness failures, unavailable/unsigned content, missing selected profiles, large inventories, mismatched preview fields, and source mutations fail closed. Raw storage exceptions or student content are never included in ordinary error output. Core `B/M/Q` navigation exceptions propagate. Exact original CLI and Advanced routes remain available.

## Qualification

Focused synthetic tests exercise class/period filtering, two reviewed immutable sources, selected profile version, preview identity/digest checks, two deterministic preview builds, cancellation, changed history, oversized catalogs, navigation, redaction, and no export writes. Guarded runner verifies the pinned baseline, unique menu anchors, payload SHA-256, Ruff, strict mypy, the frozen #123 route/report audit, Issue #110 raw-ID quarantine, and previous #123/#55/#56 regressions before any commit and normal push.
