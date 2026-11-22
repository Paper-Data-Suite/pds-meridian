# Issue #126 / Slice I3A — installed producer readers and source-checkout teacher journeys

**Issue branch:** `126-verified-correction-attempt-reassessment-management`
**Accepted parent:** `8c1f632ff5fb32645b6c00d8a4b591ef941aeef2`
**Status:** candidate for native Windows qualification; not a release qualification or merge authorization.

## Goal and boundaries

Qualify synthetic teacher-facing journey evidence against the **actually installed** Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6 and Concord 0.3.2 public readers and the **current Meridian source checkout**. Do not replace the public readers with fake providers. No production edits, publishing, grades, release-wheel substitution, or live classroom records.

I3A is source-checkout acceptance, not the final I3/D3/D4 proof. Existing I1/I2A/I2B tests retain their full native #29/#30/#122 coverage, and this slice adds integration/authorization/cross-producer witnesses.

## Test matrix

| Path | Executed contract | Expected evidence |
|---|---|---|
| ScoreForm public reader | Canonical Core publication → authorized projection → real teacher evidence inbox/menu | Source identity, teacher selection, no silent write |
| Quillan public reader | Canonical Core publication → authorized projection → real teacher evidence inbox/menu | Native standards ratings preserved; no ScoreForm attempt inference |
| Concord public reader | Canonical Core publication → authorized projection → real teacher evidence inbox/menu | Native group/criterion evidence preserved; no ScoreForm attempt inference |
| Cache access denied (all three) | Publication still identifiable, no authorized evidence drill-down | No active publication context and no hidden ID exposure |
| Teacher moves between producer work | Process-local session scope cleanup | Class/work/publication/student context cannot leak across work |
| ScoreForm 29×6 with #29, #30 and #122 | Existing native fixture → inbox → actual teacher correction menu → receipt/current pointer → **fresh** publication projection | Exactly Attempt 2 current, original 0/6 preserved, distinct 4/6→5/6 retake unselected |
| Publication authorization revoked | New projection attempted after a valid historical decision | Access denied, no automatic repeat, prior immutable receipt retained |

Runtime probe verifies noneditable Core, ScoreForm, Quillan, Concord distributions and that public reader imports resolve to paths owned by those distributions. It prints Meridian's checkout/wheel discrepancy instead of conflating them.

## Academic safety

- **#29** inclusion precedes #30; only authorized included evidence may become a candidate.
- **#30** Save/Use requires a reviewed teacher action; score magnitude and timestamp never select a result.
- **#122** receipt and independent CAS current pointer are required for success. Cancels, conflicts and interrupted actions remain covered by prior native regressions.
- Quillan/Concord lack ScoreForm `multiple_attempts` semantics; neither is converted into synthetic attempts.
- The original ScoreForm manifest and alternate attempts remain auditable. A correction is **teacher-reviewed**, not automatically certified by scanning provenance.

## Release-evidence and manual acceptance ledger (not attested by I3A)

1. **D1 source checkout with installed dependencies:** qualified only after this script and the selected regressions pass; observe exact paths and versions in printed probe.
2. **D2 future published Core UI capability:** not attested by installed Core 0.6.6. G1's documented plain fallback is the installed behavior.
3. **D3 noneditable officially built Meridian release wheel:** **not attested** by a source-checkout `.venv` import even if `pds-meridian 0.4.2` metadata exists.
4. **D4 full Paper Data Suite launcher/composition:** **not attested**; requires separately controlled launcher, installed wheel, and cross-module teacher session evidence.
5. **Live #121 saved teacher attribution:** synthetic fingerprint injection in I2B/I3A is not a saved-person identity proof.
6. **Physical scanning and provenance:** synthetic ScoreForm manifest is not a paper scan, device-driver validation, or diagnosis of a scan failure.
7. **Real teacher observation of the complete UI:** no automated pytest menu simulation substitutes for hands-on validation, accessibility, class/period changes, and out-of-session restart.
8. **Report 9 #133/#134:** separate owners; H1 documents the unresolved correction-aware item-statistics gap. Do not report 29/29 post-correction results without #134 qualification.
9. **A1–A18 final issue ledger:** J must reconcile each independent gate and preserve unresolved blockers instead of silently marking them accepted.

## Operator handoff

In an isolated synthetic workspace, run the published user-facing program and verify B/M/Q, no unexpected `:notes` command interception, source review labels, selected student/work carryover, original #122 receipt, and fresh Standards continuation. Capture the actual imported wheel paths, complete test counts, errors/skips, and any session ambiguity. No real student data are required.

The I3A runner stages exactly one test file and this note only, on accepted I2B HEAD; it refuses unrelated dirty/staged files or a changed remote. It commits/pushes only after qualification; it never merges or closes the issue.
