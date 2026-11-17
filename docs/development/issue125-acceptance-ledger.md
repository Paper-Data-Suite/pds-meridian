# Issue #125 — acceptance ledger (A17 closure candidate)

**Status: OPEN — not a release or merge authorization.** This is a factual
reconciliation of observed synthetic qualifications through the A16 PR #144
baseline `dd466ff5ca961103ead1770921dfd2032e899ab5` (November 16, 2026), plus
the isolated local A17 candidate evidence recorded below. The ledger identifies
evidence *and* the limits of that evidence. The final PR SHA CI and exact final
local validator must pass before A18 can be qualified. No classroom identifiers,
assessment results, teacher identities, or private records appear.

**Review baseline:** [Meridian #125](https://github.com/Paper-Data-Suite/pds-meridian/issues/125)
· [draft PR #144](https://github.com/Paper-Data-Suite/pds-meridian/pull/144)
· [A16 integration eight-job green CI run 43984803358](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43984803358)
for exact baseline `dd466ff5ca961103ead1770921dfd2032e899ab5`.

Status meanings: **Qualified** = observed test or installed acceptance of the
stated bounded case; **Partial** = some observed evidence, but an explicitly
required variant remains unqualified; **Pending** = a required final gate has
not been completed. These are not binary issue-closure approvals.

## A1–A18 evidence and outstanding obligations

| Criterion | Assessment | Evidence; precise residual |
| --- | --- | --- |
| **A1 — Assessment entry/context** | **Qualified, bounded** | #124-integrated inbox, selected existing current Grade Item/work and academic period; F1/F2 flow checks, G1/G2 native installed checks. No implicit Grade Item creation. Confirm production teacher walkthrough in final gate. |
| **A2 — Exact roster grouping** | **Qualified** | B grouped Core roster, duplicate-name disambiguation, absent/unmatched/shared sources; G1 installed ScoreForm/Quillan/Concord; 29 students × 6 correctness targets. |
| **A3 — Faithful status/coverage** | **Qualified, supported boundaries** | A3 closure matrix: affected source checks **148 passed, 4 native-gated skipped**; isolated official-wheel candidate checks **46 passed, no skip** with Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6, Concord 0.3.2 and Meridian 0.4.2 candidate SHA-256 `debacdda66e26072bb3ac6989a447cc6897ba83bb67bee1ec7586879ca58588d`. Distinct canonical no-decision/Include/Exclude/Pending/Unsupported, source superseded/withdrawn, stale membership, unverifiable/conflicting pointers, empty projection and authorization denial all fail closed without zero or protected detail. The released readers do not supply complete roster coverage or an absence reason, so roster subtraction is now labeled **projection coverage unavailable**, never invented as either no returned result or not projected. Exact matrix and limitation: `docs/development/issue125-a3-acceptance-matrix.md`. |
| **A4 — Review exceptions first** | **Qualified, supported boundaries** | A4 closure matrix: source-focused checks **59 passed, 12 explicit native-gated skipped**; isolated official-wheel candidate checks **77 passed, no skip** with Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6, Concord 0.3.2 and Meridian 0.4.2 candidate SHA-256 `02d4e30c5e6e93fdcc47427e985aa8fb492dbf0e82e8f17c5c89e19130fa6dc8`. A genuine installed ScoreForm corrected-attempt walkthrough shows the exception queue before selection, routes competing attempts to #126, keeps unrelated items safe, and cancels with a byte-identical workspace. Installed boundaries also qualify unreadable-scan failure before publication, Concord evidence-only availability, local student target, group/shared target, and three-producer denied access. Duplicate exact identity now receives a redacted integrity-specific stop. Withdrawn source, stale membership, unknown roster, conflicting/unverifiable selection, all seven routes, pagination, B/M/Q, and individual/Advanced recovery remain fail-closed. Pre-publication failures are not fabricated as Meridian rows. Exact matrix and limitations: `docs/development/issue125-a4-acceptance-matrix.md`. |
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
| **A16 — Classroom usability** | **Qualified** | A16 installed native benchmark used two independent fresh 29-student × six-question ScoreForm workspaces, each with 406 source items, exactly 174 correctness targets, and the same final 167 Include / 6 Exclude / 1 Pending outcomes. The real individual inbox/menu path measured **1,805 inputs, 1,631 screens, 174 confirmations, 174 repeated Grade Item/policy/attribution interactions, 1,345.371 s automated full-menu elapsed, and 37.229 s summed canonical applies**. The real assessment batch path measured **40 inputs, 38 screens, one `APPLY`, one Grade Item/policy/attribution interaction, 44.507 s automated full-menu elapsed, and 42.473 s sealed canonical execution**. Both produced 174 selected-current revision-1 decisions and receipts, entered zero evidence/Grade Item canonical IDs, left all 232 other source items untouched, and changed no collateral workspace domain. A display-only correction disambiguates same-question ScoreForm result kinds so teachers can select correctness without hidden ordering. Timings are single-run scripted Windows measurements, not human completion times or a claimed speedup ratio. Exact method, environment, hashes, results, and limitations: `docs/development/issue125-a16-usability-benchmark.md`. |
| **A17 — Shared menu/navigation** | **Qualified, supported boundaries** | A17 focused source checks **115 passed, 1 explicit installed-native skip**; source-free official-wheel checks **116 passed, no skip** with Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6, Concord 0.3.2 and Meridian 0.4.2 candidate SHA-256 `1f36d398d97e79052f198b7a72300bea701932b1b4544e1bb666bf5828cb26e4`. The real 29-student/406-item ScoreForm inbox walkthrough verifies B/M/Q boundaries, explicit exception/coverage review, bounded authorized display-label filter, failed-search safety, stable cross-page identity and cancellation, plain `NO_COLOR`, Advanced receipt recovery and individual re-entry with exact retained context, zero entered/rendered canonical IDs, unchanged receipts and a byte-identical workspace. Installed Core exposes shared navigation but no public module-facing header or Notes capability, so the qualified boundary is Meridian's plain header and inert `:notes`; no private Core API, Notes provider, Suite dependency, or academic action was added. Exact matrix and limitations: `docs/development/issue125-a17-acceptance-matrix.md`. | |
| **A18 — Final full qualification** | **Pending** | The A16 integration baseline `dd466ff5ca961103ead1770921dfd2032e899ab5` passed all eight CI jobs in run `43984803358`. A17 is qualified only in its isolated local candidate and has not been integrated or run through exact-final-SHA CI. The final clean-tree validator (`pytest`, Ruff, mypy, docs, wheel/sdist/Twine, installed official-release qualification), 8/8 CI against the eventual last PR commit, and explicit acceptance/merge decision remain required; earlier green SHAs and focused A17 checks do not substitute. | |

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
H3D6 [43617071896](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43617071896),
H3D7 [43637549995](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43637549995),
and A16 integration [43984803358](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43984803358)
all completed 8/8 green at their recorded exact SHAs. These are **not** the
eventual A18 final-commit CI.

## Remaining closure decisions, in order

1. **A11 boundary:** retain H3D6 and H3D7 as bounded true interprocess evidence (lock, corruption, conflicting selection/immutable revision and independent unrelated source). Do not claim untested power-loss, process-kill or OS-wide filesystem failure modes; no new CAS slice is required absent a reproducible defect.
2. **A18:** after A17 integration, run final **clean-tree** `scripts/validate_repository.py` once with pinned exact official Core/ScoreForm/Quillan/Concord wheel paths; capture actual full pytest, Ruff, mypy, docs, wheel+sdist, Twine, installed qualification, and wheel hashes. Verify 8/8 CI against the **last** PR commit. Do not treat earlier runs or prior-wheel qualification as an exact-final-SHA substitute.
3. Keep PR #144 draft and Issue #125 open until A18 and the explicit merge decision. Do not modify Core, Suite or producers under this ticket.

## Boundary of the ledger

This document records acceptance evidence, **not** a substitute for real gates.
A 'Qualified' row means only the exact bounded case stated in that row passed.
No green CI run on an earlier commit qualifies a later changed production file.
