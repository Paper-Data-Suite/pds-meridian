# Issue #126 / Slice I3B — installed artifact boundaries and teacher acceptance

**Issue branch:** `126-verified-correction-attempt-reassessment-management`
**Accepted parent:** `0db2f7db1d98b647c98893b145954626acb21b3c`
**Status:** candidate I3B evidence qualification; *not* official Meridian release, Suite D4, human acceptance, or final merge authorization.

## Purpose and delivered evidence

I3A qualified the source-checkout teacher routes against **installed, noneditable** Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6 and Concord 0.3.2 public readers. I2A/I2B also qualified a synthetic 29-student, six-question 0/6→6/6 correction using the actual #29/#30 stores, #122 action/receipt and current-pointer CAS. I3B records precisely what those tests can and cannot establish.

`python -B scripts/issue126_i3b_release_evidence.py --repo .` is a read-only provenance census. It checks exact distribution versions and the owned files imported for Core and the three public readers, rejects editable/mismatched reader imports and computes SHA-256 for each **installed module file**. Those hashes do **not** certify original wheel archives, nor the producer's upstream release identity. It checks that the Meridian menu actually imports from this source checkout rather than incorrectly treating an in-repository `.venv` path as Meridian source.

The additional I3B regression measures **scripted** menu behavior on an isolated synthetic ScoreForm 29×6 case: five input responses (original, correction, rationale, single Save/Use confirmation, display pause), five identifiable task screens, one current #30 selection, one finalized #122 receipt, preservation of original source bytes and a fresh Standards-included evidence check. This is an **automated keypress count**, not a human usability/time measurement and not full launcher/composition acceptance.

## D0–D4 release-evidence truth

| Level | Current evidence | Additional acceptance required |
| --- | --- | --- |
| D0 contract | Exact #126 source, Core/Suite teacher-UX design, cross-repository matrix reviewed | Final J reconciliation against currently published dependencies |
| D1 Meridian source | I1–I3A native tests, source modules and G1/G2 menu tests; I3B targeted retest pending | Final exact SHA validators and CI |
| D2 shared Core UI | Installed Core **0.6.6** supports existing B/M/Q; **plain header fallback** verified | A published installed Core artifact advertising `terminal.header.v1`, verified independently; not assumed |
| D3 Meridian release | Current `pds-meridian` metadata may carry a version label, but imports resolve to this **source checkout** | Official **noneditable** wheel, release artifact digest, isolated wheel install and teacher-menu qualification |
| D4 Suite composition | Current scripts exercise imported Meridian modules directly; do not prove foreground suite launcher or return | Qualified pinned mixed-wheel Suite, launcher, session/return/authorization and teacher navigation evidence |

**A later source tree, `dist-info` version label, locally built candidate wheel, or simulated menu is not proof of a published official release.** The source-checkout script intentionally reports D2 new Core UI, D3, D4, saved-profile, physical-scan and human acceptance as *not attested*.

## I3B measured synthetic witness (not human timing)

- Classroom: **29 synthetic students**, **6 questions**, two native observations for the affected student (original 0/6 and teacher-reviewed 6/6), separate retake case preserved but not automatically selected.
- Menu: screen/task descriptions for choosing original observation, choosing corrected result, recording rationale, reviewing decision and verifying current state.
- **Five scripted input responses**, including exactly one consequential `Save and Use This Decision` confirmation; this does not include earlier assessment/inbox setup and does not measure a human's elapsed time.
- **One** persisted current #30 revision for affected student, **one** finalized #122 action receipt; source manifest digest unchanged.
- Reopening the current ScoreForm projection shows only Attempt 2 as selected; the independent retake student's choices remain undecided. Verified Standards continuation exposes only the selected attempt's evidence; **no Standards association, proficiency, Grade or report is written**.
- Independent evidence: the I3B test inspects actual persisted records and manifest bytes; it cannot observe teacher comprehension or touch scanned paper.

## Human classroom qualification worksheet — explicitly outstanding

The separate `I3B_MANUAL_ACCEPTANCE_WORKSHEET.md` in the transfer archive supplies a blank operator form. Perform only on a **synthetic disposable workspace**, never a real student class, and record the exact artifact provenance before claiming release acceptance. The operator must run via the actual Suite foreground launcher using the qualifying **noneditable Meridian wheel**, select the assessment, review the exceptions queue, distinguish correction from retake/unknown causality, perform one Save/Use, inspect receipt/current selection, reopen via Standards, navigate B/M/Q, test no-color/non-TTY and prompt-scoped `:notes`, then exit/restart and inspect durable state. Capture actual keypresses/screens and **measured human time**, plus failures/skip reasons. If wheel, launcher, saved attribution or physical source is unavailable, mark the corresponding check **BLOCKED/NOT TESTED**, not PASS.

The test profile is synthetic, not a saved real #121 teacher fingerprint. The ScoreForm fixture is a producer public manifest, **not** a physical scanner/OMR acceptance. A teacher can verify the intended original-paper correction only in a separately authorized hands-on scenario.

## A1–A18 interim ledger (not a final acceptance sign-off)

| Gate | Evidence held | Remaining limitation |
| --- | --- | --- |
| A1 entry | F1 and I3A teacher entry integration | Complete installed Suite entry not attested |
| A2 provenance | B/C and native I1 source attributes | Actual paper-derived causal proof not attested |
| A3 0/6→6/6 | I1, I2A, I2B, I3A native synthetic current #30 and receipt | Human-operated one-task path not attested |
| A4 retake | B/C/I3A distinct second sitting and no automatic selection | Human distinction pending |
| A5 multi-attempt | D2/E3 typed #31 retain/replace/combine/recency, recovery | Downstream arithmetic separately owned |
| A6 publication | A/B/I1 exact published reader and source state | Physical republish untested |
| A7 cross-producer | I3A installed Quillan/Concord reader isolation | Future capabilities must be qualified separately |
| A8 history | E3/I2A/I2B original attempts and immutable decisions | Source documents unexamined |
| A9 noncontamination | F3B1/H2/I2B current evidence gate | Report 9 gap remains #134 |
| A10 authorization | F/H/I3A operative included and denied access | Full Suite permission wiring outstanding |
| A11 staleness | E1–E3/F3 CAS and drift regressions | Cross-process human scenario outstanding |
| A12 usability | F/G and I3B synthetic five-input witness | Saved live #121 and human elapsed-time study outstanding |
| A13 cancel | D/F/I2B cancel tests | Human exit exercise outstanding |
| A14 recovery | E/F original #122 receipt and restart matrices | Operator interruption/restart exercise outstanding |
| A15 idempotency | E3 native replay tests | Real hardware/process restart outstanding |
| A16 UX | G1/G2 Core 0.6.6 fallback/navigation, `:notes` literal | New published Core capability D2, Meridian D3 and Suite D4 unverified |
| A17 downstream | H1/H2 exact consumer contract handoff | Report 9 #133/#134 and broader proficiency policy not resolved by #126 |
| A18 qualification | Selected source/installed-reader tests have passed on Windows | Full validator, wheel/sdist/Twine, 8 CI jobs on final SHA, official wheel matrix and ledger still required |

## Required final-J evidence

Record exact accepted branch SHA, dependency versions **and wheel artifact hashes where retained** (do not mislabel module hashes as wheel hashes), skips, tested OS/Python, mypy/Ruff/format/docs/pytest, build/sdist/Twine output, full six prepared official-wheel matrices and final eight CI jobs (Ubuntu/Windows × Python 3.11–3.14) **on the exact final PR SHA**. Preserve all Not Tested/Blocked variants in A1–A18. Draft PR stays unmerged; issue stays open until explicit review and approval.

## Non-goals and safety

No production code changes or cross-repository mutations; no new scoring rules, Report 9 fixes, source-private reads, live SIS/LMS writes or new academic store. Script reads only local installed package metadata and importable public module files. The manual checklist is a handoff, not a fabricated qualification result. #133 and #134 remain separate issue owners.
