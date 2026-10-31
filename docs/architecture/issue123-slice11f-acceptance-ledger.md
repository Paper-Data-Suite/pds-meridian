# Meridian #123 — acceptance ledger (Slice 11F, reconciled in Slice 11L)

**Evidence baseline:** `106c5bf0b222ca373e55b2cfa1ced0d70979fd87` (Slice 11K). **PR:** draft PR #142 on `123-teacher-first-navigation-existing-menus`. **Scope:** historical acceptance reconciliation before the proposed documentation-only 11L change; no release or merge is claimed. This is not permission to alter academic state, authorization, record semantics or producer interfaces. **11L CI pending** at the next commit; the CI results below belong to their stated historical SHAs.

## Established evidence

| Gate | Verified status | Evidence and exact scope |
| --- | --- | --- |
| Live teacher-route census | Passed through 11J | 49 historical operations; **39 named** and **44 Advanced** teacher-context choices, 83 combined; **nine** independently guided Reports. Proficiency option 10 is a named gateway, not a tenth main-menu task; nested Planning Signal 8–14 named and 1–7 Advanced. |
| Historical menu composition | Passed in 11A/11B | Source-level route crosswalk, nine Reports preserved, synthetic composed menu with 25 inputs, one class chooser, three initial class-catalog reads, zero routine technical-ID prompts and 29-student synthetic roster. These are synthetic tests, not real student outcomes. |
| Stale and adverse choices | Passed within tested scopes (11C and 11G) | Selected read-only controllers test duplicate/Unicode labels, stale record witnesses, denied reader and retained class/calendar invalidation. No blanket permission-read guarantee is claimed. |
| Installed domain baseline | Passed in 11G | Isolated Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6, Concord 0.3.2 and candidate Meridian 0.4.2 wheels, 29-student roster with duplicate names, archived Grade Item and producer-titled work, persisted selected proficiency and protected denial branch. |
| Joined installed read-only journey | Passed in 11K | One verified class across named Grade Item → proficiency → Grade review → selected-result explanation → Planning Signal readiness, then class switching and child-context invalidation. Read-only academic files unchanged. Grade review may correctly be **not configured**; no numeric Grade is inferred. |
| Measured before/after interaction baseline | Paired limited workload passed in 11H | Actual legacy and named read-only controllers, identical injected synthetic records: **16 vs 13** input calls; **12 vs 0** technical canonical ID prompts; **3 vs 0** repeated class-ID prompts; equivalent two Grade Item and two proficiency reads per mode. Local timing is sampled but is not representative installed end-to-end latency. |
| CI at historical feature SHAs | Passed | GitHub CI #137 (11I `1bd3723`), #138 (11J `e2c164c`), and #139 (11K `106c5bf`) each **8/8** Windows/Ubuntu jobs passed for Python 3.11, 3.12, 3.13 and 3.14. The proposed 11L head must be checked independently. |
| Packaging and source validation | Passed through 11K | Full CI-mirrored repository validator, wheel/sdist and allowlist validation, installed five-wheel checks; the 11K candidate wheel was validated without changing Meridian's production package inventory. |
| Historical Windows checkpoint | Passed in 11E | **1,752 passed, 8 skipped**, with symlink-related Windows skips; this is a historical result, not the 11K test count. |
| #110 raw technical prompt-site quarantine | Preserved | 188 historical source prompt sites and original frozen hash; counts are static source locations, **not** teacher keystrokes. |

**Measurement integrity.** The 11B `latency_ms` **remains null** and its 25 inputs have no matched legacy baseline. Use **11H**, not 11B, for the 16/13 and 12/0 paired comparison. Those observations cover two representative read-only controllers with synthetic in-memory readers, not every menu or a complete installed workload. No numeric improvement percentage or hardware-independent performance gain is claimed. A catalog re-read for exact currentness is not automatically waste.

## Open acceptance requirements and owner decision

1. **Richer end-to-end installed-domain journey — read-only portion qualified, consequential boundary incomplete.** 11K genuinely joins Grade Item, selected proficiency, Grade review, explanation and **Planning Signal readiness** in one installed five-wheel process. The Grade step can report *not configured* because no Grade policy was created. This demonstrates truthful navigation and a blocker, **not** successful configured Grade calculation or an invented zero. The Planning Signal step selects a current policy but does not write/export a signal. The full Grade → ReportingSnapshot/export-commit production chain was not exercised in the joined journey.
2. **Protected authorization and stale scope — partial domain tests, not an exhaustive joined action matrix.** Earlier denial/stale tests are valuable, but a publication revoked between every joined-step read and a consequential #122 CAS/restart mutation are not demonstrated by 11K. Missing Grade/period/policy/evidence remain blockers, not silently selected alternatives.
3. **Measured before/after interaction baseline — representative paired study qualified, full-workflow latency open.** Slice 11H measures two read-only controllers and locally sampled timings. It does not establish installed five-wheel end-to-end latency, real classroom hardware responsiveness or a district-scale performance threshold. 11B's `latency_ms` remains null.
4. **Final commit CI — pending for 11L.** CI #139 is **8/8** at 11K, not prospective acceptance of an unpublished 11L SHA. Run all eight Windows/Ubuntu Python jobs after this source-only documentation change.
5. **Owner sign-off and issue disposition — not granted by this ledger.** Keep **draft PR #142** open and **do not merge**, publish a release, or close #123 until the owner explicitly decides whether the read-only Planning Signal endpoint and documented blockers satisfy the issue's ordinary-navigation criterion, or a follow-up installed configured Grade and snapshot/export/Planning action acceptance must run first. #124–#129 and later #120 children continue to own new assessment/policy/batching behaviors outside #123.

## Teacher-facing references

- `docs/teacher-navigation-guide-issue123.md` — actual nine-entry Meridian teacher menu, search/keyboard navigation, class-context retention and named Planning Signal gateway.
- `docs/architecture/teacher-advanced-record-operations-issue123.md` — 44 Advanced choices, exact-record/CLI access and immutable authorization/write boundaries.
- `docs/architecture/issue123-slice11h-comparative-interaction.md` — paired controller workload and its latency limitations.
- `docs/architecture/issue123-slice11k-joined-installed-acceptance.md` — truthful installed read-only journey and exclusions.
- `docs/architecture/issue123-slice11l-final-reconciliation.md` — final pre-merge decision matrix and explicit nonclaims.

The guides describe a **candidate feature branch**, not an official district gradebook integration; a local Meridian export is not an SIS, LMS or Genesis posting. Source documentation tests are not a replacement for a qualified installed runtime.
