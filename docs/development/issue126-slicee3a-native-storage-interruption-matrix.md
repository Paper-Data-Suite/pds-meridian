# Meridian #126 — Slice E3A: native storage, journal and restart matrix

**Acceptance baseline:** `b33e5548d3073f16608ec73ae0a73b06ff29c471` on `126-verified-correction-attempt-reassessment-management`.

## Purpose and qualification boundary

This slice upgrades the earlier controlled service-outcome tests to exercise **actual temporary-workspace files** through the existing #30 and #31 immutable writers/readers, canonical current-pointer CAS, #31 dependency/resolution checks, #122 action orchestration, #122 class-local receipt store and `resume_exact_teacher_selection`.

The tests **do not** use an installed ScoreForm producer, real student records, real Core roster/authorization/eligibility or the full production teacher action preparation menu. The synthetic external #29 eligible-candidate derivation and current membership have intentionally narrow monkeypatches in `_world`; the #30/#31 persistence, digests, lock/pointer and #122 receipt/recovery algorithms are **not** monkeypatched. A minimal test domain port delegates to native #31 storage but is **not** the production `prepare_reviewed_reassessment_action` binder. Thus E3A is **native-storage qualification**, not final native dependency/wheel qualification. E3B will exercise the production port and higher-level entry/recovery dependency matrix before E can be marked finished.

## Real artifacts created under `tmp_path`

- A #30 multi-attempt selection policy revision and its current pointer.
- A #30 immutable student decision revision with two explicitly selected attempt references and, unless the case prevents it, an actual current pointer.
- A #31 explicit relationship policy revision and current pointer.
- A #31 immutable `retain` decision bound by the **actual #30 revision hash**, and (when selection succeeds) its current pointer.
- A #122 class-local durable action receipt with checked generation, stages and original action identity.

All data are synthetic; every test gets its own temporary workspace and no user repository runtime data is touched.

## Fault injection and expected evidence

| Interruption/reconciliation | Native observation | Required behavior |
| --- | --- | --- |
| Cancel before confirmation | No #31 history/current/receipt | No academic write |
| #30 not current | #30 revision exists but no selected pointer | #31 blocked before write |
| Basis withdrawn before #31 write | #31 history absent | Fail closed without success |
| Throw after #31 immutable writer | Exact #31 history exists, pointer absent | Uncertain; no false success or automatic reauthor |
| Throw before #31 pointer CAS | Exact #31 history, original receipt, pointer absent | Restart eligible **only after original receipt and canonical reconciliation** |
| Throw after #31 pointer CAS | #31 pointer may be current despite exception | Never infer success from an exception or receipt alone |
| Restart same original action | Exact #31 pointer selected, #30 untouched | No new immutable revision, original action only |
| Retry ordinary APPLY | Same #31 revision/current | No duplicate write |
| Missing or conflicting receipt | Stored #31 immutable revision may remain | No blind replay |
| Changed #30 current pointer | Existing #31 history preserved | Block original #31 selection |
| Changed #31 policy current | Existing #31 history preserved | Block original #31 selection |
| Tampered immutable #31 or pointer | Canonical digest/schema read fails | No success/unsafe repair |
| Stale journal generation | Receipt CAS conflict | No acceptance of stale checkpoint |
| Source revoked after pair applied | Prior records stay intact | Reconciliation cannot claim current authority |

## Expected acceptance

- Run the focused E3A matrix and existing E2B, E2A, E1, D2B2, D2B1, D2A, D1, C, B, A, #30/#31 storage, #122 and teacher attempt regressions against the **installed** work `.venv`.
- Qualify the new test file with Ruff import sorting, formatting and lint. Qualify the unchanged E2B/coordination service via strict mypy; validate docs.
- The guard requires the exact accepted baseline, an initially clean worktree, no same-path files, only two new files staged, and the same remote head before push. Failed qualification **does not commit or push**.

## Limits and next work

E3A does not prove official-wheel/native-scoreform interoperability, exhaust every real OS crash timing, or justify any A1–A18 closure beyond focused native-storage evidence. It also does not add a writer or alter a decision schema. **Next E3B:** qualify the production #31 action binder, actual #122 receipt restart and dual-domain/recovery entry with installed supported dependencies and targeted failure injection; then evaluate whether Slice E is complete.
