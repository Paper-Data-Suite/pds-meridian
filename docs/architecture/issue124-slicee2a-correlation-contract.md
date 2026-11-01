# Meridian #124 — E2A: exact composite recovery correlation contract

**Base:** `2353c6fe62da1bd66ea4d2f06cb5d40f65e1de92` (E1). **Scope:** one additive source module, isolated tests, this architecture note, and exact package-inventory updates. No CLI/menu integration or academic writes.

## Core distinction

D2 binds two independently durable #122 actions. E1 reports the selected canonical Grade Item and relationship, plus nearby receipts, but two nearby receipts do **not** establish one approved combined setup. E2A therefore adds a typed, checksum-protected, canonical JSON **correlation contract** anchored to the exact C1 `review_sha256`, work/class/year/period/registration/publication, Grade Item, the normalized workspace root fingerprint, and **saved** #121 actor/profile fingerprint. It carries only the original #122 action IDs and target fingerprints; it neither stores, executes, nor authorizes an action. The stable `intent_sha256` excludes the later action IDs so preparation may bind first Grade Item then membership without changing the reviewed intent.

The stage order is strict: `reviewed` → `grade_bound` → `membership_bound` for a new Grade Item; `reviewed` → `membership_bound` for an existing Grade Item. The membership action must reference the reviewed exact `work_identity_sha256`, year, period, actor profile, class and Grade Item. Any changed actor, target, class, year, period, work or conflicting action ID is refused. A `use_existing` proposal cannot carry a Grade Item creation action, and a `create_and_link` membership cannot be bound without the original creation action.

## Serialization and interpretation

`create_assessment_setup_correlation(workspace_root, preview, actor)` requires an absolute workspace path; stage binding also compares the exact #122 workspace hash. `AssessmentSetupCorrelation.to_json_bytes()` emits bounded canonical JSON with a SHA-256 checksum. `from_json_bytes()` refuses unknown schema fields, duplicate JSON keys, noncanonical bytes, digest mismatch and oversize content. **The bytes are a proposed future persistent record format, not a persisted record in E2A.** No disk writer/reader is introduced yet.

`inspect_assessment_setup_correlation()` requires a matching E1 canonical inspection and exact #122 receipt objects for **every** bound action. It checks each receipt against the bound original stage ID, target digest, actor fingerprint, class, Grade Item, and membership period/work. It refuses missing/other action attempts, source or selected-state drift and unrelated receipts. It can advise `not_started`, `original_grade_action_pending`, `original_membership_action_pending`, `ready_verified`, or `requires_review`, but `may_resume_automatically` **always returns false**. This is **not** a cross-process proof of safe recovery unless a later writer persisted the correlation *before* the first academic action and each subsequent action binding; the #122 canonical records remain authoritative.

## Next qualification gates

**E2B:** safe Meridian-owned filesystem persistence with exact CAS, creation before first academic action, stage advancement before the next academic action, restrictive directory/file checks and restart enumeration. No reconstructing a missing record from filenames/titles or a pair of unrelated #122 receipts. Require tests for power loss before/during correlation write and collision on the same reviewed intent.

**E2C/E3:** bind D2 and #122 recovery adapters to the stored correlation. Resume only the same immutable revision and existing exact selected-pointer operation when explicitly approved, never a second creation. Cross-process tests must cover crash after each `receipt_prepared`, write, selection, verification, changes to actor/calendar/registration/publication, conflicting concurrent selections, and corrupt records. Do not expose teacher menu until supported state is unambiguously replay-safe.

Targeted changed-file Ruff, strict mypy, documentation and focused E2A/E1/#122/package regressions qualify this increment. Full repository suite, wheels and installed producer matrices remain integration/final gates only.
