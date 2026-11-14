# Issue #125 — acceptance ledger (H3D4 review candidate)

**Status: OPEN — not a release or merge authorization.** This is a factual
reconciliation of observed synthetic qualifications through H3D3 at PR #144
commit `cc18d3b89725c4847e864032dae21ce9feeb61ac` (November 12, 2026).
The ledger identifies evidence *and* the limits of that evidence. The final
commit's CI job must complete before A18 can be marked passed. No classroom
identifiers, assessment results, teacher identities, or private records appear.

**Review baseline:** [Meridian #125](https://github.com/Paper-Data-Suite/pds-meridian/issues/125)
· [draft PR #144](https://github.com/Paper-Data-Suite/pds-meridian/pull/144)
· [exact-SHA CI run 43350235461](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43350235461).

Status meanings: **Qualified** = observed test or installed acceptance of the
stated bounded case; **Partial** = some observed evidence, but an explicitly
required variant remains unqualified; **Pending** = a required final gate has
not been completed. These are not binary issue-closure approvals.

## A1–A18 evidence and outstanding obligations

| Criterion | Assessment | Evidence; precise residual |
| --- | --- | --- |
| **A1 — Assessment entry/context** | **Qualified, bounded** | #124-integrated inbox, selected existing current Grade Item/work and academic period; F1/F2 flow checks, G1/G2 native installed checks. No implicit Grade Item creation. Confirm production teacher walkthrough in final gate. |
| **A2 — Exact roster grouping** | **Qualified** | B grouped Core roster, duplicate-name disambiguation, absent/unmatched/shared sources; G1 installed ScoreForm/Quillan/Concord; 29 students × 6 correctness targets. |
| **A3 — Faithful status/coverage** | **Partial** | B/G1 separate no-result (never zero), no decision, lifecycle, membership, prior decisions and authorization; H3D3 read-only queue with safe authorization counts. Complete cross-producer display check distinguishing denied authorization vs unsupported/not-projected and uncertain rows remains unverified. |
| **A4 — Review exceptions first** | **Partial** | H3D3 exception-first paginated queue, reason and human-readable route; B duplicate/unknown/group/source exception classification; #126 unresolved attempts not silently chosen. Final manual route-by-route walkthrough for all required unsupported, withdrawn, invalid history and denied conditions remains open. |
| **A5 — Batch Include** | **Qualified** | H3C3C1 official-wheel synthetic ScoreForm full-class gate: 174 exact selected-current canonical decisions and 174 unique receipts from one fixed reviewed plan; 232 other source items untouched. |
| **A6 — Non-Include dispositions** | **Qualified, bounded** | H3D1: ScoreForm Exclude, Quillan Pending, Concord Unsupported; reasoned, attributable current decisions; invalid implicit non-Include refusals. Not interchangeable with source lifecycle. |
| **A7 — Specific exceptions** | **Qualified, bounded** | H3D1: student/item precedence, exact Include/Exclude/Pending/Defer overrides with native ScoreForm action results and untouched peer items. Frozen source-item expansion; no persistent student rule. |
| **A8 — Existing decisions** | **Qualified, bounded** | F2 explicit reviewed replacement and exclusion of unsafe prior decisions; H3B2/H3C3C1 stale replay fails closed and fresh equivalent review yields zero new writes/receipts. |
| **A9 — Single confirmation/cancellation** | **Qualified** | F1/F2 exact `APPLY`, other responses cancel; G2B 174-item cancellation causes zero writes; H3C3C1 one reviewed action batch. No per-item teacher confirmations. |
| **A10 — Scope/authority revalidation** | **Qualified, bounded** | D/E authorization and preflight, G1 permission denial, G2A Core roster drift and G2B current publication/membership checks. No authorization widening observed. A full matrix of every possible stale period/manifest transition is not claimed. |
| **A11 — Per-item CAS / storage adversity** | **Partial** | H3D2 early/middle/late controlled pointer drift stops later writes, and corrupted progress links cannot be silently resealed; canonical #122 CAS/receipt checks remain intact. Independently competing processes and locked/corrupt *canonical* storage at each position are not yet demonstrated. |
| **A12 — Partial/crash recovery** | **Qualified, bounded** | E1/E2 exact sealed-action recovery; G2B interrupted selection reconciles known attempts without replay; H3D2 early/middle/late seal failure and apply uncertainty label partial state correctly. Does not assert simulated failure is equivalent to power loss or a disk-wide failure. |
| **A13 — Idempotency** | **Qualified** | H3C3C1 stale plan replay blocked; fresh equivalent 174-item plan results in 174 unchanged, zero new writes/receipts; two complete read-only reconciliations verify currentness. Compound repeat timing is not a single UI latency. |
| **A14 — Producer semantics** | **Qualified, bounded** | Native official ScoreForm/Quillan/Concord synthetic source projection and per-producer decisions; scored vs evidence-only/group Concord distinctions are not silently made individual scores. Unsupported variants remain limitations, not invented results. |
| **A15 — No collateral academic action** | **Qualified, bounded** | H3B2/H3C3C1 before/after synthetic workspace inventories; H3D2 six native prewrite-fault variants had **zero** changes outside eligibility, receipts and private progress. This monitors the test workspace, not all OS state. |
| **A16 — Classroom usability** | **Partial** | Installed ScoreForm scenario: 29 students, 406 total native evidence items, 174 correctness targets, 232 other items untouched. One explicit reviewed set, zero pasted canonical IDs, one substantive `APPLY`; 174 actions took **60.777 s** on the measured Windows acceptance run. The **600.456 s** repeat compound includes stale reentry, equivalent no-op review, and two 174-item reconciliations; not one ordinary menu action. A measured, same-machine individual-workflow baseline and a completed teacher interaction-count comparison are still missing. |
| **A17 — Shared menu/navigation** | **Partial** | F1/F2 and H3D3 test bounded paging, B/M/Q unwind, safe labels, cancellation, and inert `:notes` (never Apply) in unsupported contexts. Still require full installed Core 0.6.6 NO_COLOR/plain-text, advertised header/notes capability-fallback and return-to-caller context matrix; do not claim an unavailable Notes service. |
| **A18 — Final full qualification** | **Pending** | H2 earlier full validator: 5,777 passed, 65 skipped; Ruff, mypy, docs, artifacts, Twine and six installed matrices. H3D3 new candidate wheel `pds_meridian-0.4.2-py3-none-any.whl` SHA-256 `f49cb077e7bab86b33a67c6473faddff33a8f74c4931d4796e1c4f73ecd56bfa` passed 108 installed tests, zero skipped, using exact qualified official wheels. All 8 CI jobs passed for preceding H3D2 SHA `8ac12cd13bfa04b20c81aa27e04746b8a1fd5c43`. **H3D3 exact final PR SHA** `cc18d3b89725c4847e864032dae21ce9feeb61ac` CI run `43350235461` was in progress at this ledger's preparation; record outcome only when verified. Full validator has not yet been rerun against H3D3 final SHA. |

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

CI runs: [H3C3C1 — 43124792701](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43124792701)
(8/8 green), [H3D1 — 43144362346](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43144362346)
(8/8 green), [H3D2 — 43148866396](https://github.com/Paper-Data-Suite/pds-meridian/actions/runs/43148866396)
(8/8 green); H3D3 run 43350235461 not yet final at preparation.

## Remaining closure decisions, in order

1. **A11:** qualify deliberate competing-process/locked or corrupt canonical store cases where safely reproducible; explicitly document any environment-dependent Windows lock limitation. Never accept corrupt progress as proof of correct academic state.
2. **A3/A4:** targeted installed teacher-facing denial/unsupported/source-withdrawal/invalid-history route matrix using synthetic data. Do not expose denied detail while distinguishing unavailable vs truly missing.
3. **A17:** Core 0.6.6-capability-aware plain-text (`NO_COLOR`), header fallback, `:notes` prompts only where supported, B/M/Q and return-context walkthrough. Preserve safe behavior when optional capability absent.
4. **A16:** document the actual menu input count and, if available, a like-for-like manual individual-workflow timing baseline. Current benchmark demonstrates one substantive confirmation and full-class canonical execution, not a validated speed ratio.
5. **A18:** final exact-SHA eight-job CI; targeted post-H3D3 static/type/docs/build/full validator (once, not each slice), wheel+sdist/Twine and official-wheel candidate install. Update the ledger with *observed* outputs; do not mark it complete from prior green SHAs.
6. Maintain [PR #144](https://github.com/Paper-Data-Suite/pds-meridian/pull/144) as **draft** and [Issue #125](https://github.com/Paper-Data-Suite/pds-meridian/issues/125) as **open** until any required gaps are actually closed or explicitly triaged. Obtain a separate merge decision. Do not modify Core, Suite or producer contracts from this gate.

## Boundary of the ledger

This document records acceptance evidence, **not** a substitute for real gates.
A 'Qualified' row means only the exact bounded case stated in that row passed.
No green CI run on an earlier commit qualifies a later changed production file.
