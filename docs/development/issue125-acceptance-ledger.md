# Issue #125 — acceptance ledger (H3D8 final-review candidate)

**Status: OPEN — not a release or merge authorization.** This is a factual
reconciliation of observed synthetic qualifications through H3D7 at PR #144
commit `7b4acd43b0e9d7336fa24a178754c075c4b5b741` (November 14, 2026).
The ledger identifies evidence *and* the limits of that evidence. The final
PR SHA CI and exact final local validator must pass before A18 can be qualified. No classroom
identifiers, assessment results, teacher identities, or private records appear.

**Review baseline:** [Meridian #125](https://github.com/Paper-Data-Suite/pds-meridian/issues/125)
· [draft PR #144](https://github.com/Paper-Data-Suite/pds-meridian/pull/144)
· [H3D6 eight-job green CI run 43617071896](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43617071896)
· [H3D7 run 43637549995](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43637549995) (queued when this ledger was prepared).

Status meanings: **Qualified** = observed test or installed acceptance of the
stated bounded case; **Partial** = some observed evidence, but an explicitly
required variant remains unqualified; **Pending** = a required final gate has
not been completed. These are not binary issue-closure approvals.

## A1–A18 evidence and outstanding obligations

| Criterion | Assessment | Evidence; precise residual |
| --- | --- | --- |
| **A1 — Assessment entry/context** | **Qualified, bounded** | #124-integrated inbox, selected existing current Grade Item/work and academic period; F1/F2 flow checks, G1/G2 native installed checks. No implicit Grade Item creation. Confirm production teacher walkthrough in final gate. |
| **A2 — Exact roster grouping** | **Qualified** | B grouped Core roster, duplicate-name disambiguation, absent/unmatched/shared sources; G1 installed ScoreForm/Quillan/Concord; 29 students × 6 correctness targets. |
| **A3 — Faithful status/coverage** | **Partial** | H3D5 (24/24 source and 24/24 isolated installed; no skip) distinguishes no-result from Unsupported/no-decision/current Include/Exclude/Pending, withdrawn source, missing membership, inconsistent selection and denied/unavailable projection (without leaking protected details). It does **not** complete the full installed cross-producer matrix for **not projected** versus unauthorized and uncertain per-item states; never infer zero or evidence from denial. | |
| **A4 — Review exceptions first** | **Partial** | H3D3 exception-first pagination plus H3D5 source/installed route checks show all seven teacher-readable next actions, withdrawn source, stale Grade Item membership, conflicting selection, duplicate-target attempts (#126), unknown roster student and group/nonstudent evidence without silently selecting them. Still lacks one complete installed teacher walkthrough of invalid-scan, Concord evidence-only/local/group, and all withheld/denied conditions. | |
| **A5 — Batch Include** | **Qualified** | H3C3C1 official-wheel synthetic ScoreForm full-class gate: 174 exact selected-current canonical decisions and 174 unique receipts from one fixed reviewed plan; 232 other source items untouched. |
| **A6 — Non-Include dispositions** | **Qualified, bounded** | H3D1: ScoreForm Exclude, Quillan Pending, Concord Unsupported; reasoned, attributable current decisions; invalid implicit non-Include refusals. Not interchangeable with source lifecycle. |
| **A7 — Specific exceptions** | **Qualified, bounded** | H3D1: student/item precedence, exact Include/Exclude/Pending/Defer overrides with native ScoreForm action results and untouched peer items. Frozen source-item expansion; no persistent student rule. |
| **A8 — Existing decisions** | **Qualified, bounded** | F2 explicit reviewed replacement and exclusion of unsafe prior decisions; H3B2/H3C3C1 stale replay fails closed and fresh equivalent review yields zero new writes/receipts. |
| **A9 — Single confirmation/cancellation** | **Qualified** | F1/F2 exact `APPLY`, other responses cancel; G2B 174-item cancellation causes zero writes; H3C3C1 one reviewed action batch. No per-item teacher confirmations. |
| **A10 — Scope/authority revalidation** | **Qualified, bounded** | D/E authorization and preflight, G1 permission denial, G2A Core roster drift and G2B current publication/membership checks. No authorization widening observed. A full matrix of every possible stale period/manifest transition is not claimed. |
| **A11 — Per-item CAS / storage adversity** | **Qualified, bounded** | H3D2 controlled early/middle/late CAS drift, seal failure and corrupt progress; H3D6 **4 source tests + 7 isolated installed tests**, true foreign-process `.write.lock`, canonical pointer/digest corruption, and native batch locks at all three positions (selected-current 0/1/2, no collateral academic writes); H3D7 **4 source + 4 isolated installed tests**, coordinated independent-process races for first selection, replacement CAS, incompatible immutable revision 2, and unrelated-source independence. A loser may report conflict/lock; an apply interrupted by lock reports recovery-required, never false nonwrite certainty. Not a proof of crash/power-loss atomicity or all filesystem-level failures. | |
| **A12 — Partial/crash recovery** | **Qualified, bounded** | E1/E2 exact sealed-action recovery; G2B interrupted selection reconciles known attempts without replay; H3D2 early/middle/late seal failure and apply uncertainty label partial state correctly. Does not assert simulated failure is equivalent to power loss or a disk-wide failure. |
| **A13 — Idempotency** | **Qualified** | H3C3C1 stale plan replay blocked; fresh equivalent 174-item plan results in 174 unchanged, zero new writes/receipts; two complete read-only reconciliations verify currentness. Compound repeat timing is not a single UI latency. |
| **A14 — Producer semantics** | **Qualified, bounded** | Native official ScoreForm/Quillan/Concord synthetic source projection and per-producer decisions; scored vs evidence-only/group Concord distinctions are not silently made individual scores. Unsupported variants remain limitations, not invented results. |
| **A15 — No collateral academic action** | **Qualified, bounded** | H3B2/H3C3C1 workspace inventories; H3D2 six native prewrite-fault variants had zero changes outside eligibility/receipts/private progress; H3D6 three installed early/middle/late real-lock variants also showed zero collateral changes. Inventory is limited to synthetic workspace, not all OS state. | |
| **A16 — Classroom usability** | **Partial** | Installed ScoreForm scenario: **29 students**, **406** native source items, **174** correctness targets and 232 untouched alternatives. One explicit reviewed set, zero pasted canonical IDs, one substantive `APPLY`; full 174 canonical actions in **60.777 s** on measured Windows acceptance. The **600.456 s** compound repeat included stale replay, equivalent no-op review and two complete read-only reconciliations; it is **not** an ordinary single menu action. Source selection fixture observed one explicit all-item selection input; a completed teacher-facing interaction tally and comparable timed 174-item manual workflow baseline are still missing. Do not invent a speedup ratio. | |
| **A17 — Shared menu/navigation** | **Partial** | F1/F2/H3D3 and H3D5 source + isolated installed Core 0.6.6 (24/24) demonstrate B/M/Q unwinding, paginated read-only exception display, plain-text `NO_COLOR` without escape codes, inert `:notes` in unsupported prompts, and selection retaining exactly the reviewed Grade Item/assessment context. Optional Core v1 header and Notes-capability-available branches, individual/Advanced reentry and search/filter full installed menu walkthrough still require explicit verification; no Notes academic action or Core/Suite API change is claimed. | |
| **A18 — Final full qualification** | **Pending** | H2 prior full validator: 5,777 passed, 65 skipped plus Ruff, mypy, docs, artifacts/Twine and six installed matrices; H3D3 exact candidate Meridian 0.4.2 wheel SHA-256 `f49cb077e7bab86b33a67c6473faddff33a8f74c4931d4796e1c4f73ecd56bfa` had 108/108 isolated installed regression checks. Confirmed **8/8** CI for H3D3 `43350235461`, H3D4-CI `43611029662`, H3D5 `43612579158`, and H3D6 `43617071896`. H3D7 exact-SHA run `43637549995` was queued during preparation. **H3D8 final PR SHA** remains to be established after this ledger commit; final clean-tree validator (`pytest`, Ruff, mypy, docs, wheel/sdist/Twine, installed official-release qualification), 8/8 exact-final-SHA CI and final acceptance/merge decision are required; earlier green SHAs do not substitute. | |

## Native artifact identities and provenance

Official wheels used in the isolated installed qualification:

| Distribution | Version | SHA-256 |
| --- | --- | --- |
| `pds-core` | 0.6.6 | `d6d21e426092b0329bcfd69b6fbee44c345edc46794a914d847d5ea73a2b7301` |
| `scoreform` | 0.13.0 | `4a4d158fda6e899f1835f3312ca8291622e2b1c7da219b349adf5e88b9b7c9b7` |
| `quillan` | 0.10.6 | `7dbe975c969e60cfda9a8489154450f95c4dc58a8d75afcfad92e7a3c026afbb` |
| `pds-concord` | 0.3.2 | `825b27bc6142cc8bce8c3b9381a3337c4a55e983f6f3f2e7e4b1a10f980e83ce` |

H3C3C1 full-174 candidate wheel SHA-256:
`d3a42d8a2d176a020b127749dbcef13023e9d9dbbbec51a063c682e5fddffc59`.

H3D3 candidate wheel SHA-256:
`f49cb077e7bab86b33a67c6473faddff33a8f74c4931d4796e1c4f73ecd56bfa`.

Local machine evidence directories (not shipped with the repository):

- `meridian125_h3c3c1_full174_20261112T002455Z_4104db6b`: 174 writes, 174 receipts, source identity and idempotency proof.
- `meridian125_h3d1_native_20261112T021158Z_287bf67f`: 8/8 native non-Include/override tests.
- `meridian125_h3d2_native_20261112T031556Z_ffdf0fc3`: 18/18 native adversarial tests and zero collateral writes.
- `meridian125_h3d3_installed_20261112T040708Z_e960e1f3`: 108/108 isolated updated-menu regression tests.
- `meridian125_h3d5_native_20261114T154429Z_93d64dc5`: 24/24 isolated status/route/terminal checks; source 24/24.
- `meridian125_h3d6_native_20261114T163207Z_d8c55c63`: 7/7 isolated canonical lock/corruption checks; source 4/4 with 3 native-only skips. The legacy runner final marker erroneously said 24; the pytest count and summary are 7.
- `meridian125_h3d7_native_20261114T195214Z_bce9ebe6`: 4/4 true competing-process CAS installed checks; source 4/4.

CI qualification: H3D3 [43350235461](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43350235461),
H3D4-CI [43611029662](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43611029662),
H3D5 [43612579158](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43612579158),
H3D6 [43617071896](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43617071896)
all completed 8/8 green. H3D7 [43637549995](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43637549995)
was queued when the H3D8 source was prepared. This is **not** the eventual H3D8 final-commit CI.

## Remaining closure decisions, in order

1. **A3/A4:** complete or explicitly triage outstanding teacher-facing not-projected vs unauthorized vs uncertain status and unavailable-scan/Concord source exception variants. H3D5 established the read-only route matrix, **not** all installed producer/authorization interactions.
2. **A17:** verify optional Core header/Notes-capability-present branch, individual/Advanced reentry, and search/filter walkthrough, or record precise supported fallback limitations. Never introduce a new Notes provider or Suite dependency.
3. **A16:** complete the teacher input/screen count and same-machine manual individual-review timing baseline **if** a credible comparator exists. Evidence already proves 174 exact selected-current decisions with one substantive confirmation, but it is not a quantified manual-to-batch speedup.
4. **A11:** retain H3D6 and H3D7 as bounded true interprocess evidence (lock, corruption, conflicting selection/immutable revision and independent unrelated source). Do not claim untested power-loss, process-kill or OS-wide filesystem failure modes; no new CAS slice needed absent a reproducible defect.
5. **A18:** run final **clean-tree** `scripts/validate_repository.py` once with pinned exact official Core/ScoreForm/Quillan/Concord wheel paths; capture actual full pytest, Ruff, mypy, docs, wheel+sdist, Twine, installed qualification, and wheel hashes. Verify 8/8 CI against the **last** PR commit after the ledger update. Do not treat earlier runs or prior-wheel qualification as an exact-final-SHA substitute.
6. Keep PR #144 draft and Issue #125 open until genuine residuals are qualified or specifically accepted as limitations; require an explicit merge decision. Do not modify Core, Suite or producers under this ticket.

## Boundary of the ledger

This document records acceptance evidence, **not** a substitute for real gates.
A 'Qualified' row means only the exact bounded case stated in that row passed.
No green CI run on an earlier commit qualifies a later changed production file.
