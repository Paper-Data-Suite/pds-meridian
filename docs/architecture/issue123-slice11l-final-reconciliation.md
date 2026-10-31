# Meridian #123 — Slice 11L: final acceptance evidence and decision boundary

**Pre-slice baseline:** `106c5bf0b222ca373e55b2cfa1ced0d70979fd87` (11K, GitHub CI #139, 8/8 jobs passed). **State:** draft PR #142, no release or merge is claimed. This slice reconciles documentation and adds source-level tests only. It makes **no production behavior, academic-record, authorization, or package change**.

## Verified evidence crosswalk

1. **Routes:** The Slice 11A live inventory, amended by 11J, records 49 historical operations, 39 named and 44 Advanced teacher-context entries (83 total), plus nine independently guided Reports. Proficiency option 10 is a named gateway to the nested Planning Signal menu, whose options 1–7 remain Advanced and 8–14 named.
2. **Interaction:** Slice 11B's source-tree composed-menu exercise uses 25 inputs, one class chooser and three initial class-catalog reads, without a paired legacy control. Slice 11H supplies the separate matched workload: 16 legacy inputs vs 13 named inputs, 12 vs zero technical-ID prompts and three vs zero repeated class-ID prompts, with two Grade Item and two proficiency reads per mode. The 11H harness measures local latencies on execution, but no hardware-independent latency result or improvement percentage is claimed. The 11B `latency_ms` field remains null.
3. **Installed behavior:** 11G uses an isolated installed five-wheel synthetic domain fixture with 29 students, duplicate student names, archived Grade Item, registered producer titles, current selected proficiency and class/calendar invalidation. 11K adds a joined read-only Grade Item → proficiency → Grade review → explanation → Planning Signal readiness route in one retained `TeacherNavigationContext`. It verifies no technical identifier prompt, no unintended academic file change and class-switch invalidation.
4. **Safety:** #110's 188 historical raw-prompt source sites remain frozen. Earlier selection/authorization tests and 11G's denial test cover specific synthetic negative cases. These are **not** proof of all possible protected-publication authorization changes within the joined 11K journey.
5. **CI:** GitHub CI #137 (11I), #138 (11J) and #139 (11K) each passed all eight Windows/Ubuntu Python 3.11–3.14 jobs. This states historical verified results only; the new 11L head must pass CI again.

## Scope limits that prohibit an unqualified closure claim

- **Configured Grade outcome:** The 11K seed does not create a current Grade policy. Grade review may correctly report *not configured*. A successful configured Grade calculation is **not demonstrated** by that journey.
- **Planning action:** The joined journey observes a selected Planning Signal policy and readiness. It does **not** write a derivation, author/select a review or export a Core grouping signal. Legitimate readiness blockers remain blockers, never inferred Grades or grouping outcomes.
- **Snapshots and exports:** 11K does **not** freeze a ReportingSnapshot or commit a local export/receipt. Their existing domain tests are separate; a fully joined Grade → snapshot/export transaction has not been shown.
- **Evidence permissions:** The joined 11K test does not open protected producer student answers or exercise access revoked between every navigation step. Separate tests cover narrower authorization and stale-witness scenarios.
- **Performance:** The 11H comparison covers two read-only controllers under synthetic injected readers; neither a complete workflow latency nor real classroom hardware/producer latency is established.

## Recommended disposition

**Do not merge PR #142, release Meridian 0.4.2, or close #123 automatically from this documentation slice.** After the 11L commit's own Windows/Linux CI is green, request an explicit owner decision: (a) accept the specified read-only Planning Signal endpoint and documented configuration/authorization blockers as sufficient for #123, with consequential live-boundary acceptance scoped separately; or (b) retain #123 open and add a focused installed configured-Grade plus snapshot/export or Planning Signal action acceptance. No unchecked issue criterion may be silently marked complete. This decision is distinct from #124–#129's separately owned assessment onboarding, grading-policy setup and batching.
