# Meridian #123 Slice 8C — Named Local ExportReceipt Browsing

**Base:** `47c00bd147cec552056e0d046be0ec3f5abf0bda`
**Branch:** `123-teacher-first-navigation-existing-menus`

## Teacher task

Teacher-context Export menu gains **9. Browse past local exports by name**. Options 1–8 retain their numbers; options 1–6 remain Advanced exact-input routes. The non-context Export menu remains unchanged. A teacher chooses a verified Core class, then one stored local ExportReceipt by its export date, file basename (if applicable), row count, and Export Profile version. The exact immutable export ID and receipt digest are carried only in transient choice identity/currentness witness. A copyable-text export is distinguished from a saved-file export; only a file basename, never an absolute destination path, is shown. The UI does not display Grades, a CSV/TSV payload, student names, or technical digests.

## Authority boundary

The new controller uses existing injected `ExportMenuDependencies.receipt_lister` and `receipt_loader`; the latter loads an exact immutable, validated ExportReceipt using Meridian's canonical receipt storage reader. Bounded catalogs reject duplicated or excessive canonical receipt identities. Metadata are revalidated against their requested export ID, digest, destination representation, source identities, date, profile revision and row count. `select_teacher_choice` refreshes the choice; a second domain revalidation reloads its metadata and the verified Core class. Changed, ambiguous, missing or unverified receipts fail closed with redacted errors. The browser never writes an ExportReceipt, replay payload, copyable text, new file, selector, Grade or SIS/LMS record.

A local ExportReceipt is **provenance of the local Meridian export action only**. It does not attest that a file still exists on disk, or that any district/SIS system imported or accepted the data. For exact identity and technical diagnostics, teachers use Advanced.

## Compatibility and qualification

- Existing menu and public injected Export dependencies are retained; no new Core or producer contract.
- Existing direct CLI and no-context Export routes remain unchanged.
- Issue #110's frozen raw-ID prompt inventory remains unchanged; the new module has no raw identifier prompt.
- Thirty-two focused adversarial tests cover named discovery, immutable digest and ID mismatches, bounded inventories, copyable text, stale class and receipt handling, exception redaction, navigation, cancellation and no writes.
- The guarded source-only payload and separate runner pin the exact Git base and menu blob; the runner qualifies Ruff, strict mypy, frozen #123 route audit, receipt/export regressions and earlier teacher navigation before an exact-scope commit and normal push.

## Deferred

Guided preparation of a report export and local artifact/receipt creation remain separate subsequent slices. A receipt browser is not a substitute for the explicit export preview/commit authorization and cannot imply external integration.
