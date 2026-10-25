# Meridian #123 Slice 8E — Guided Local Report Export Delivery

**Base:** `886a0c35a123a386b843a711b3dd637bec0d813b`
**Branch:** `123-teacher-first-navigation-existing-menus`

## Teacher task and choices

The teacher-context Export menu adds **11. Deliver a local report export by name**. Teacher chooses verified class, current marking period, a named immutable ReportingSnapshot belonging to its exact period/calendar revision, and a named Export Profile with an explicitly selected revision. IDs, digests, and revision numbers are never typed. The existing bounded named choice catalogs remain the sources of canonical identity and currentness witnesses.

The controller invokes the established authorized export preview builder, cross-checks exact snapshot/profile identities, checks an independently rebuilt preview, and displays metadata only (format, column labels, rows, payload byte count, diagnostics). It neither prints student rows nor infers an export destination during the preview step. The teacher deliberately selects a local file path or copyable-text output and supplies the existing teacher attribution plus optional reason. Local file paths must be absolute. The teacher sees the destination, scope and privacy reminder, then must explicitly type `EXPORT`.

## Consequential boundary

Immediately before delivery the controller rechecks class, calendar, frozen snapshot, selected profile, and exact deterministic preview. A cryptographically random, path-safe opaque ExportReceipt ID is generated internally (128 bits) rather than requesting a teacher-entered identifier. The existing `ExportMenuDependencies.export_committer` performs the authoritative source rebuild, file handling, and immutable receipt persistence. It is the **only** service authorized to write the destination or receipt. Existing file protection forbids replacing different bytes; an identical existing file may be verified and reused. The controller never writes academic records or implements a competing transaction.

A successful committer result must match export identity, destination kind, artifact disposition, and receipt digest. The controller then reloads the exact canonical receipt and checks class-scoped source IDs, selected profile revision, output rows, exact payload digest, destination identity, teacher attribution, and timestamp. Only after receipt readback does the controller report success, and only then may it display copyable student-level text that the teacher deliberately selected. No clipboard automation occurs.

If any failure occurs **after** the committer is invoked, the terminal reports an **uncertain outcome** and directs the teacher to inspect receipts and the destination. A local file may have been written even if receipt persistence failed. Before the invocation, failures and cancellations report no export attempted. Internal exceptions are redacted; absolute file paths and student content are not logged in status messages.

## Scope and qualification

Existing Export menu options 1–10 keep their numbering, and legacy no-context options 1–6 remain. The new option is 11 in teacher context only. No changes to immutable schema, Core, preview/commit/receipt domain services, external LMS/SIS integrations, or direct CLI are introduced. No external system import, acceptance, or Grade update is claimed.

Focused synthetic tests verify file and copyable-text delivery, receipt readback, explicit authorization and cancellation, stale currentness, malformed previews, wrong result/receipt identity, local path validation, opaque ID generation, uncertainty and redaction. The guarded Windows runner checks the pinned Git baseline, reviewed patch anchor scope, payload hashes, Ruff, strict mypy, frozen navigation audit, historical export regressions and #110 raw prompt inventory before scoped commit and normal push. Real-workspace and external application acceptance remain outside this slice.
