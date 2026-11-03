# Issue #124 — E2G3O4: synthetic canonical teacher-journey acceptance

## Purpose and provenance

Qualify the *activated* E2G3O3 normal teacher discovery-to-setup path against genuine, temporary Core and Meridian canonical storage, including the existing #122 teacher-action journal and #124 E2C correlation store. This is **acceptance evidence**, not another academic writer or new menu feature.

E2G3O3's prior menu tests injected outcomes at the review boundary. E2G3K/L exercised canonical state, original receipts and selection-only recovery independently. This slice exercises the actual teacher menu, preview loader, E2C binder and domain writer chain together on an isolated synthetic workspace.

## In scope

- An actual Core synthetic class, school-year calendar and registered ScoreForm work, with the derived academic catalog rebuilt from those records.
- Teacher choices **D → marking period → assessment → S**, explicit Grade Item purpose and title, synthetic saved attribution, and exactly one `APPLY` through the real controller.
- Both immutable Grade Item and included membership revisions, both selected current, with exact period assignment.
- Durable correlation persisted with *two distinct original* #122 action IDs, original journal receipts, read-only restart classification as `ready_verified`, and session continuation to the selected work/Grade Item.
- Reopening the current assessment as `already_ready`: no `APPLY`, no receipt, revision, selection, or correlation write.
- Cancel at the final review and at an earlier purpose choice: zero canonical/receipt/correlation writes.
- Registration revision changed *at* confirmation: refuse before the first #122 action writes, with no fabricated correlation or selected record.
- A simulated **Grade Item selection failure** after its immutable write, and separately a **membership selection failure** after its immutable write. Each must retain its original correlation/receipt, report not-ready, refuse automatic restart, and block a second fresh confirmation of the same reviewed action.

## Boundary and safety

Only the teacher **profile identity provider** is replaced with a minimal synthetic witness; the Core records, Meridian read/preview services, guided Grade Item and membership authoring/selection, action orchestration, receipt storage, correlation store and restart inspection are the actual existing implementations. The two deliberate interruption cases replace **only one selection committer**, after the corresponding immutable write. Production user profiles, student records, scans, manifests and protected evidence are neither required nor read.

The original #122 selection-only restart ports are already regression-tested in E2G3L. E2G3O4 verifies their *read-only restart diagnosis* and non-replay precondition at the integrated teacher boundary; it does not create a new restart executor.

## Acceptance limitation

The synthetic assessment is **registered-only ScoreForm work** without a student result publication. This verifies the menu's registration-only path and Grade Item relationship without implying that evidence has been published or authorized. Published ScoreForm/Quillan and scored Concord compatibility, withdrawn publication handling, multiple exact teacher choices and any production deployment or installation acceptance remain separate acceptance obligations. No complete ticket closure or wheel qualification is claimed by this slice alone.

## Qualification

New additive files only: this architecture note and `tests/test_issue124_slicee2g3o4_canonical_teacher_acceptance.py`. Targeted Ruff, focused pytest against E2G3O3 / E2G3O2 / E2G3L / E2G3K and package inventory. Exact base commit `b71f03668f58cd603d9269ca321e6fb8c111313d`; guarded non-force push after all checks pass. Full-repository validation is intentionally deferred.
