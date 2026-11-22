# Meridian #126 — J1 full validator and interim A1–A18 acceptance ledger

**Status:** candidate only; final PR/CI, released-wheel, Suite D4 and manual acceptance not claimed.
**Exact accepted parent:** `0dacf27e7bb58336f36bc94cec73e9f64a7588b4`
**Validation date:** 2026-11-21 (pending local J1 run).

## Decisive distinction

The accepted I3B log reported **133 passed** (targeted), with installed Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6 and Concord 0.3.2. `meridian` itself was imported from the working source checkout (`0.4.2` package label), **not** a separately released noneditable Meridian wheel. Installed module file SHA-256 values are **not original wheel archive hashes**. The script's manual-acceptance field remained `not_executed_by_this_script`.

J1 is the **first final-slice full local qualification** of the exact candidate. The canonical command is `scripts/validate_repository.py --allow-dirty` before the candidate ledger/test files are committed. It authenticates the four official dependency archives, validates the installed dependencies, performs full pytest, Ruff check/format, strict mypy, docs, wheel/sdist build, Twine check, package and sdist boundaries, and existing prepared installed-wheel matrices. Do not replace it with a small test subset. The candidate Meridian wheel is **source-built and temporary**, not an official published release.

## A1–A18 evidence, classified rather than flattened

Machine-readable ledger: `docs/development/issue126-slicej1-a1-a18-ledger.json`.

| Gate | Qualified at source/native boundary | Remaining limitation |
|---|---|---|
| A1 — Assessment-level entry | Synthetic current-assessment entry and teacher-readable queue are covered. | Human end-to-end navigation and independent session observation remain open. |
| A2 — Provenance fidelity | Teacher-reviewed interpretation is distinct from producer-certified provenance and unresolved states. | Physical original source inspection and producer-owned causal metadata are not certified by these tests. |
| A3 — Classroom correction | Synthetic 29x6 ScoreForm 0/6 to 6/6 correction; selected #30 Attempt 2 and finalized #122 receipt. | Full installed Meridian wheel, live saved profile, physical paper and human timing remain open. |
| A4 — Real reassessment | Distinct synthetic retake remains unselected; separate #31 actions have source regression coverage. | A real second sitting and end-to-end human reassessment treatment remain unverified. |
| A5 — Multiple attempts | Explicit multi-attempt relationship and #31 guarded composition covered in source/native tests. | No automatic arithmetic or universal proficiency policy; installed production journey for each #31 mode remains conditional. |
| A6 — Source revisions | Synthetic native attempt identity separated from publication and cache snapshots. | Producer-managed physical correction cause remains outside #126. |
| A7 — Cross-producer honesty | Installed Quillan and Concord public readers do not create ScoreForm-style attempt candidates. | Live producer corrected-publication and Concord group-only variants require separate human/native proof. |
| A8 — Historical preservation | Original manifest and immutable #30/#31 histories retained during synthetic selection. | No real classroom records, SIS, or producer history mutations were exercised. |
| A9 — No contamination | Selected Attempt 2 only feeds verified Standards continuation; historical Attempt 1 remains audit-only there. | Report 9 multi-attempt item statistics are separately owned by #134 and are not qualified here. |
| A10 — Authorization and eligibility | Exact current Core publication, authorized snapshot, membership and selected #29 inclusion required. | Full Suite authorization/role provider and live teacher permission remain unverified. |
| A11 — Staleness | Native CAS conflicts, interrupted operations, and stale dependencies fail closed. | Adversarial human concurrent edits across separately installed processes remain conditional. |
| A12 — Usability | Scripted synthetic journey used five responses and exactly one actionable Save/Use choice. | Not a human timing study or proof of live saved #121 attribution or shortcut accessibility. |
| A13 — Cancellation | Menu cancel cases create no canonical #30 revision or #122 receipt in synthetic workspace. | Separate real-world cancellation after external side effects is not a source-only guarantee. |
| A14 — Recovery | Native write-before-CAS, restart and receipt behavior preserve uncertain/not-current states. | Human cross-process restart on final installed wheel remains unverified. |
| A15 — Idempotency | Immutable identity retries, duplicate prevention and exact restart are covered. | Unobserved cross-repository failure cannot be certified as atomic. |
| A16 — Core and Suite shared UX | Installed Core 0.6.6 supports qualified plain header/navigation fallback; D1 source tests passed. | New Core shared UI D2, installed Meridian D3, and full Suite D4 are not attested. |
| A17 — Downstream consumer contract | Exact selected-evidence/attempt contract and downstream Report 9 gap regression documented. | Report 9 generation #133 and multi-attempt statistics #134 require independently owned fixes. |
| A18 — Exact qualification | Earlier targeted source/native Windows tests qualified; J1 is the full local-validator candidate. | Full official-wheel local validator, eight CI jobs on final PR SHA, original artifact hashes, and human acceptance remain unverified until executed. |

## Final gate order

1. Run J1's exact guarded runner on the accepted I3B SHA, with the working tree initially clean. The runner installs nothing into the checkout; official wheels are downloaded to a separate Downloads directory and their fixed release hashes validated by existing repository scripts.
2. The complete `validate_repository.py --allow-dirty` command must exit zero. Save its **local transcript**; a partial success is not acceptance. This includes candidate packaging and the existing six installed-environment matrices.
3. Only then commit/push J1's three source-owned acceptance artifacts (ledger JSON, audit note, test). **Do not merge/close**.
4. On the *post-commit* SHA, open or update a PR and obtain all eight workflow jobs (Windows/Ubuntu × Python 3.11/3.12/3.13/3.14). Record exact run URL, commit SHA and per-job outcomes in J2. CI on an older SHA is not sufficient.
5. Conduct the separate synthetic/manual operator worksheet on an appropriate installed deployment with saved teacher attribution. Record inputs, confirmations, paths, human times, accessibility and any prohibited writes. A script's five responses are not a human usability measure.
6. D2 needs a newly *published* Core shared-UI version (Core 0.6.6's plain fallback is valid). D3 needs official installed Meridian wheel and original artifact hash. D4 needs complete Suite composition. Do not mark them passed from checkout metadata.
7. #133 and #134 Report 9 changes, physical scanning and any producer-owned missing correction-cause contract remain separately owned; no unreviewed cross-repository edits.

## Decision rule

A1–A18 source regression *coverage* does not equal all A1–A18 *final acceptance*. J1 can establish `local_full_validator_qualified` after the actual command succeeds, not `release_ready`. Leave any unsupported, deferred or human-required row unresolved and show it to the reviewer. No fabricated Grades, silent latest/highest selection, duplicate current pointer, or producer-private access.

## Evidence retention

The I3B source-origin JSON and I3B manual worksheet remain separate artifacts. J1 saves a PowerShell transcript under Downloads with the complete validator output. The candidate wheel/sdist archive bytes are temporary inside the existing validator; their build passing does not prove an official published release hash. Archive hashes for official dependencies are checked by the repository's own fixed-release verifiers (do not substitute installed module-file digests).
