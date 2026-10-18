# Meridian #122 — Slice 2: durable receipts and canonical reconciliation

Status: supporting service only; no teacher menu, canonical academic record, or Core contract is changed in this slice.
Baseline: Meridian branch `Paper-Data-Suite/pds-meridian`, commit `32c3b845b80c37f8741e554a423de73d0d5df57a`.

## Purpose and authority boundary

`meridian.teacher_action_receipts` provides a small, typed, workspace-local journal for the Slice 1 `TeacherActionPreview`. It records the *attempt* and a bounded sequence of checkpoints. It is deliberately **not** an academic transaction log, an evidence authorization, a Grade Item or eligibility authority, or a substitute for canonical record selection.

The separate `assess_teacher_action_recovery` function invokes a domain-provided canonical loader on every invocation. It compares the exact reviewed target revision/digest with canonical history and the actual current pointer, then checks the reviewed dependencies' currency. The journal alone cannot report *already applied*, instruct a retry, or claim a successful selection.

This slice does **not** execute a write or current selection. Slice 3 connects the domain-specific authoring, selection-preview, CAS commit and independent verification services to this journal. Until then, the `CanonicalActionObservation` contract is an input that must be implemented by those authoritative adapters, **not** a proof that its supplied fields are true.

## Location, privacy, and crash safety

The journal lives under Core's class module route:

`<workspace>/classes/<class-id>/modules/meridian/teacher_action_receipts/<32-hex-action-id>.json`

A receipt contains only exact action ID, reviewed scope/actor identifiers and their digests, proposed target revision and hashes, source-basis references/hashes, UTC timestamps, checkpoint states and small observed-record references. It contains no student answers, scans, copied publications, evidence payloads or report bodies. The candidate payload is not embedded.

- A class directory must already exist. Preparing a receipt cannot create a new class.
- Every directory component is checked without following symlinks or reparse points; action ID and class ID are validated before entering filesystem paths. The private receipt directory uses mode `0700` on POSIX and receipt/lock files use `0600`.
- Journal JSON is exact-schema, duplicate-key rejecting, canonical UTF-8 and capped at 32 KiB. Each envelope includes a canonical-payload SHA-256 checksum (corruption detection, not cryptographic authentication). Checkpoints and observed records are count-limited.
- Each update runs under a stable class-scoped OS lock (`flock` on POSIX, `msvcrt.locking` on Windows); processes release the lock automatically on exit/crash. No stale lock-file deletion is needed. The update uses a journal generation compare-and-swap.
- A new receipt is written by temp file, flushed/fsynced, atomically replaced, and parent directory fsynced where supported. File and directory link/regularity checks occur before and during operations.
- Receipt preparation must succeed before any future academic write begins. A journal failure *after* an academic mutation must become an indeterminate/partial report, never an assertion that the academic write did not happen.
- At most 10,000 `.json` action receipts can exist per class under this storage contract. Exhaustion blocks preparation; automated deletion/pruning is not implemented.

Atomicity is **only per receipt-file replacement**. Neither the receipt, Core registry, nor any group of immutable academic revisions is treated as one atomic transaction.

## Ordered API

1. `TeacherActionReceiptStore(root, class_id).prepare(preview)` creates generation 1 with the reviewed preview and `receipt_prepared` checkpoint. Repeating the exact preview with the same opaque ID is a no-op; a different preview with that ID conflicts.
2. `record_checkpoint(preview, expected_generation=..., checkpoint=..., observed_records=...)` performs a locked CAS append. Checkpoints cannot go backwards and previously recorded immutable identities cannot disappear. This records observation, not academic authority.
3. `load(action_id)` performs a read-only load, including schema/hash/path safety. It never creates a receipt or journal directory.
4. `assess_teacher_action_recovery(store, preview, canonical_loader)` inspects the exact receipt and calls the loader for fresh canonical history/currentness. It never changes academic records or journal files.

No automatic retry or selection API exists in Slice 2. The eventual teacher-facing *Resume applying this exact reviewed decision* path requires a fresh source/actor/currentness preflight and the existing domain compare-and-swap selection commit.

## Conservative reconciliation matrix

| Live canonical state (and journal state) | Assessment | Resume suggestion |
| --- | --- | --- |
| Receipt prepared, target revision absent, no write attempted | `blocked_before_write` | No; review intent before any write |
| Target revision has reviewed digest, current pointer still exactly prior reviewed pointer, basis current | `written_not_current` | **Eligible** to offer exact selection after fresh revalidation |
| Target revision has reviewed digest, exact pointer selected, basis current | `already_applied` | No; already current |
| Receipt missing, even when target revision already exists | `recovery_required` | No automatic replay; reconstruct and review |
| Receipt unsafe/corrupt | `recovery_required` | No automatic replay; preserve files and diagnose |
| Canonical reader fails or cannot verify history | `recovery_required` | No; current is indeterminate |
| Target revision digest mismatch | `conflict_requires_review` | No; different immutable revision |
| Source membership/publication/policy/actor/period basis changed | `conflict_requires_review` | No; fresh teacher review |
| Current pointer changed from reviewed prior pointer | `conflict_requires_review` | No silent override |
| Current pointer/source validity unknown | `current_unverified` or `recovery_required` | No |
| Journal claims observed write, but canonical target is missing | `recovery_required` | No; journal is non-authoritative |
| Journal contains multiple record families | `recovery_required` | No; domain-specific progress reconciliation required |

A read-only `already_applied` assessment is **not** an orchestration result and cannot substitute for the Slice 1 `TeacherActionResult` verified postcondition. A `can_resume_exact_selection=True` field is an advisory recovery affordance only and never authorizes a selection.

## Failure windows and tests

Focused tests cover absence/no read side effect; repeated preparation; cross-process-like generation conflict; checkpoint ordering/record retention; restart round-trip; same action ID with different attribution; malformed and oversized files; duplicate JSON keys; file/directory symlink and outside-path guards; a missing class; crash after immutable write but before receipt update; crash after selection but before receipt update; changed current pointer; changed basis; conflicting target digest; canonical loader failure; canonical/receipt disagreement; and safe refusal of a second journal writer. All scenarios use synthetic temporary classes.

Tests for real Grade Item, eligibility, attempts, standards and proficiency canonical loaders, multi-record Grade Item/linkage recovery, actual selection retry, multi-process installed-wheel exercise, path reparse adversaries on Windows and class-scale UI recovery belong to Slices 3–7. They must not be claimed complete here.

## Packaging and integration

Add `meridian/teacher_action_receipts.py` to `scripts/check_package.py`'s exact required-wheel member set. The new module depends only on `pds_core` and Meridian's Slice 1 contract; optional ScoreForm, Quillan, or Concord installations are not required. Existing producer publication/withdrawal and Core academic authority stay unchanged.

The Slice 2 runner checks the **exact** Slice 1 commit and the user's established branch, rejects a dirty checkout, copies only this module/test/doc, updates the wheel allowlist, executes focused Ruff/strict mypy/pytest, checks staged whitespace and scope, then commits and pushes when green. The full suite is deferred to final #122 qualification.
