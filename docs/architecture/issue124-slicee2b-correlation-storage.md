# Meridian #124 — E2B: durable guarded assessment-setup correlation storage

**Pinned base:** `18c9ce5fe978c11a29a1e13680efc443bbc47e98` (E2A). **Scope:** one source module, isolated filesystem tests, this note, and two exact package-inventory updates. No teacher-menu entry point, canonical academic writer, replay/resume, wheel, or producer matrix.

## Authority boundary and progression

`AssessmentSetupCorrelationStore(root, class_id)` stores the exact E2A canonical JSON under a separate class-scoped Meridian folder, using the stable `intent_sha256` as the sole filename identity. `create_reviewed(value)` accepts **only** an initial `reviewed` correlation with no action IDs and persists it before any caller executes a #122 action. Repeated exact initial create reports `existing` without a write; if the intent already advanced, it refuses reinitialization. The caller must not interpret the existence of a correlation as permission to perform any academic action. This slice does not connect storage to D2 or #122 actions; E2C must enforce the persist-before-APPLY ordering at the actual call boundary.

`advance_exact(expected=..., updated=...)` performs a lock-protected full-byte CAS and allows only one monotonically added original #122 action witness: `reviewed → grade_bound → membership_bound` for `create_and_link`, or `reviewed → membership_bound` for `use_existing`. It rejects changed intent, actor, target of a previously bound stage, reordered stages, missing exact baseline, or competing updates. Every stage is written before its corresponding stage's academic APPLY, when later integrated. An existing Grade Item relationship is not reauthored or silently recreated on restart.

## Filesystem and interruption contract

The class directory must already exist. The new namespace uses #122's guarded directory/file, link/reparse, file-identity, and nonblocking platform lock primitives, a restrictive private directory on POSIX, a bounded complete inventory, a separate `.correlation.lock`, temporary-file write + fsync + atomic replace, and directory fsync when supported. It will not create a class or alter the #122 receipt directory. Reads do not create locks or folders. An unknown file, dangling link, oversized or corrupt canonical JSON, unexpected filename, or abandoned `.tmp` entry causes a fail-closed refusal of enumeration and any subsequent mutation rather than reconstruction from file names or unrelated receipts.

Power loss **before** rename leaves either the previous complete generation or no record, possibly an abandoned temporary file that requires manual investigation. Power loss **after** rename can leave the new complete generation; the stage advancement is not an academic transaction. Filesystem-specific power-loss durability depends on OS/filesystem guarantees and must be verified in integration. The store never deletes unrecognized files or repairs them automatically. On Windows, filesystem protection uses the existing #122 reparse/file-identity and CRT lock conventions; stronger platform ACL custody belongs to deployment qualification.

## Explicit remaining work

**E2C:** integrate the store with D2's one-confirmation coordinator, persist the review and exact stage action ID **before** calling each #122 APPLY, compare canonical registration/actor/period/current-pointer between stages, and reopen the original correlation after a restart. **E3:** exercise crash injection, CAS conflict, rehydrated exact #122 selector-only resumes, and receipt/correlation divergence with synthetic workspaces and final integration validation. Never synthesize a new action ID after uncertain execution; no automatic replay is introduced by E2B.

Qualification: changed-file Ruff, strict mypy, docs validator, focused E2B/E2A/E1/D2/D1/C1/#122/package tests. No per-slice full suite, release wheel or installed producer matrix.
