# Meridian #123 — Slice 11A: Live teacher-menu adoption and acceptance census

**Scope:** Additive acceptance evidence only. No runtime code, academic state, authorization, schema, package manifest, menu command, or persistence behavior changes.
**Verified branch baseline:** `cf1709ba3c97b0ad51e298cbee4973ab1557b440` (`#123`, Slice 10G).
**Tracked machine inventory:** `issue123-slice11a-live-adoption.json`.
**Static contract:** `tests/test_issue123_slice11a_live_adoption_contract.py`.

## Summary and scope

Issue #123's historical Slice 1 audit contains **49 legacy operations** across eight teacher menus and an independently frozen nine-report guided surface. After Slice 10G, the **live teacher-context menus** expose **83 entries**, of which **38** are named teacher routes and **45** are explicitly labeled Advanced. These counts include the nested Planning Signal submenu; it is not a tenth main-menu task. The original exact-ID routes remain deliberately available for compatible direct callers and technical operation.

The JSON inventory explicitly records the eight current menu files and entry functions; the exact current displayed label, option number and named handler for each teacher route; the original 49-route crosswalk; and Advanced-only exceptions. Each labeled entry is verified from the current source rather than claiming that the historic Slice 1 inventory describes today's behavior.

*This is a structural census.* A named option and a preserved canonical write gate **do not, by themselves, prove** a realistic human workflow is faster, correct across class switching, fully installed, or end-to-end usable. The runtime journey, authorization adversarial matrix and wheel/CI qualifications below remain open.

## Operation-by-operation status summary

| Original menu | Historic operations | Live named choices | Live Advanced choices | Known acceptance qualification |
| --- | ---: | ---: | ---: | --- |
| Grade Items | 6 | 5 | 4 | Browse/current revision and work-membership choices are named; exact authoring remains Advanced |
| Proficiency | 10 | 2 | 8 | Guided current views; direct calculation/author/select operations remain explicitly Advanced, with policy/scale configuration outside #123 |
| Grades | 2 | 2 | 2 | Current Grade and named-roster report available; verify session/period reuse |
| Overrides | 4 | 4 | 4 | Review, author, select and withdraw have deliberate named paths; verify restart/CAS/attribution |
| Snapshots | 6 | 5 | 6 | Browse/select/definition operations named; build-request JSON freeze remains Advanced |
| Export | 6 | 5 | 6 | Profile, receipt, preview and delivery named; manual profile authoring remains Advanced |
| Explain | 8 | 8 | 8 | All eight historical explanations have named paths; raw-ID variants remain Advanced |
| Planning Signal | 7 | 7 | 7 | All seven operations have named paths in the Proficiency-nested submenu |
| **Total** | **49** | **38** | **45** | **Further behavioral and installed acceptance required** |

Original-option crosswalk includes paths that are not one-to-one. For example, one historic report export now has separate named preview and delivery; the Planning Signal entry in Proficiency exposes a nested seven-stage named submenu. A legacy route's Advanced designation is not a claim that the underlying academic service is unsupported. Do not silently drop an Advanced route or promote it into ordinary menus without a supported named equivalent.

## Source-only checks introduced here

1. Compare the live teacher-context menu labels to the full eight-menu inventory; reject a newly unlabeled technical operation or a moved/renamed named route without an explicit update.
2. Verify the 49 original operations are accounted for and that their recorded named alternatives exist; preserve nine guided reports as independently owned #111 functionality.
3. Check that each recorded named handler occurs in the correct numbered branch of its menu controller, not merely somewhere in the module.
4. Verify Planning Signal remains nested under Proficiency with shared navigation context, and that the standalone legacy interface is still available.
5. Reject literal raw academic ID, revision, digest or cache-key prompts accidentally added to the named Planning Signal and named Explain controllers; preserve the existing teacher-identity attribution prompt and the independent #110 quarantine.

None of these checks scans student workspaces, runs a producer reader, or authorizes academic writes. This slice intentionally does **not** change the #110 historical count (188) or digest, because no legacy raw prompt is removed.

## Remaining #123 acceptance slices

**11B — Cross-menu synthetic interaction/latency evidence.** Use an injected, realistic 29-student roster containing duplicate and Unicode names, multiple periods, matching and archived Grade Items, and producer-titled work. Run one teacher session across the eight menus and Reports 1–9. Instrument actual keyboard inputs, duplicate scope prompts, bounded catalog reads and end-to-end latency. Confirm B/M/Q, cancellation and class/period/work invalidation. Avoid test-only shadow authority.

**11C — Authorization and stale-context adversarial proof.** Include permission revoked between list/action; withdrawn publication; current Grade Item or policy replacement; selection pointer changed at confirmation; wrong class/year/work relationships; missing roster metadata; misleading labels; and interrupted #122 actions. Confirm no implicit writes/reads, no academic fabrication and no durable student-name copy.

**11D — Installed build and end-to-end qualification.** Build wheel/sdist, install into isolated environments with released Core and supported producer wheels, verify package/module allowlist and direct CLI compatibility, and run synthetic cross-module journeys on Windows and Linux/Python CI. Record full observed results, exact commit, installed versions and any platform-constrained skips. A green source-tree pytest run cannot substitute for this gate.

**11E — Final closure reconciliation.** Update the teacher navigation guide and Advanced reference; publish measured before/after input counts and current #110 site inventory; reconcile remaining Advanced-only Proficiency/JSON construction against related issue scope; run final complete suite at the qualified commit. Close #123 only when its issue checkboxes have evidence or an explicitly accepted, correctly scoped follow-up.

## Review reminders

- Preserve released Core and producer contracts, #121 preference hints, #122 typed Save/Apply/recovery, and #111 Reports.
- `TeacherChoice` labels are presentation, never academic authority. Recheck exact identity/revision/digest/selection and authorization at each domain action.
- The CSV/Core/receipt export boundary has partial-success outcomes; no silent retry with a new generated signal identity after a possibly successful commit.
- User-facing copy must not imply a local Meridian export was accepted by SIS, LMS, Genesis, or Concord.
- No new general navigation framework or `:notes` shortcut should be invented before the shared Core teacher-experience contract is released.
