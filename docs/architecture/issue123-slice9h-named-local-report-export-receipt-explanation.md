# Meridian #123 — Slice 9H: Named Local Report ExportReceipt Explanation

## Scope and reason

The existing Explain option **8. Advanced: ExportReceipt provenance** requires a raw export ID. Slice 9H adds option **16. Explain a saved local Report ExportReceipt by name** for a read-only, everyday explanation of existing local report-export provenance. Planning Signal/Core grouping exports are a separate record family handled by Slice 9G. The original eight exact-ID Explain operations remain available as Advanced or as the unchanged no-context menu.

## Existing authorities and presentation

* The verified Core class and active school year are supplied by `TeacherNavigationContext` and `TeacherAcademicChoiceCatalog`.
* `list_export_receipt_ids` and `load_export_receipt` enumerate/read immutable **local report** receipts. Neither listing nor selection writes or replays an export.
* The exact receipt-bound `ReportingSnapshot` and historical `ExportProfileRevision` are loaded through their existing storage readers. Every canonical snapshot/profile reference must match, including SHA-256, class, and revision.
* The historical Core calendar revision provides the genuine academic-period label; records from a different school year are not offered in the current-year named menu.
* The teacher sees the Export Profile title, actual period/year, export timestamp, local destination type/file basename and row count. The backend never guesses an export's relationship to a district SIS or LMS.
* `TeacherChoice.witness` is a **domain-separated SHA-256 of the complete immutable source tuple**, not a long concatenation of hashes. This conforms to the common 256-character field bound, keeps opaque IDs out of normal display, and changes if any material source field changes.
* The exact existing `deps.export_receipt` adapter exclusively owns explanation content. The name-based controller compares all eight ordinary lines and seven technical-provenance lines against the selected receipt before displaying curated teacher-facing lines. Technical details are opt-in with **T** and show the raw export/snapshot/profile IDs and digests.
* Reverify class, candidate identity, receipt, snapshot, profile, calendar, and witness before the explanation call, afterward, before each screen, and before technical details. Changed or ambiguous candidates fail closed.

## Safety / exclusions

No report, profile, grade, snapshot, receipt or file is created or selected. A local ExportReceipt does **not** certify that a local file still exists, has not been moved, or was accepted by any external destination. Do not infer a school-year scope from the export timestamp; use the exact frozen snapshot period. Do not substitute current Export Profiles for the historical receipt-bound revision. Preserve B/M/Q, the original no-context menu, noninteractive APIs, Advanced access, and #110's raw-prompt baseline. No producer evidence or protected student answers are read.

## Qualification

Run new adversarial/catalog/teacher-menu tests, Slice 9G–9A regressions, existing receipt/Export Profile/ReportingSnapshot and #110/#111/#121/#122 tests, Ruff, strict mypy, the frozen 49-route/9-report navigation audit, and installed acceptance in the final issue qualification. No commit/push on any failed gate. The slice runner pins source blobs, SHA-256 bundle inventory, branch/HEAD/origin and exact staged files; it never resets/rebases/force-pushes.
