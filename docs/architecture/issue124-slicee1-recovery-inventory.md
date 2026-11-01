# Meridian #124 — E1: read-only composite restart inspection

**Base:** `05e5a879a4ab1cec23b2feb35cd20c65df5bbaaf` (D2). **Scope:** one read-only recovery inventory, synthetic tests, this architecture note, and the two package inventory updates.

## What is verified

`inspect_assessment_setup_recovery(root, preview)` rereads B1/B2 canonical registration/publication state, the Meridian Grade Item + selected membership projection and the complete strict #122 class receipt inventory. The exact reviewed work, school year, registration revision, marking period/calendar revision, publication reference, Grade Item ID, purpose and current selected membership are compared. A written but unselected Grade Item, selected Grade Item with missing work link, persisted-but-unselected membership, or mismatched included membership cannot be called ready. A matching current selected relationship requires both the canonical Grade Item projection **and** B1/B2 readiness to agree.

Receipt information is **advisory**, never authority. The E1 reader preserves exact preexisting #122 action IDs by target Grade Item and checks actor/workspace/work/year/period scope. Multiple attempts, unrecognized scope, corrupt/unavailable journals, missing authority and source drift fail closed. No source scans, student work, manifest reads, Grade Item writes, selectors, receipt writes, or new academic database are introduced. No prior partial action can be silently treated as a pristine new Grade Item just because the current pointer is missing.

## Deliberate limits and next steps

E1 is read-only *restart diagnosis*. It cannot infer a durable cross-action composite intent solely from two independently durable #122 receipts. Consequently, `can_resume_without_review` is **always false**, even for verified ready state, and `pristine` is an observation rather than permission to commit. E2 must bind the original composite proposal to exact receipt IDs and independently revalidate current state before any explicit RESUME; it must never derive a new Grade Item ID to replay an uncertain create. A verified ready result requires no write at all. E3 should adversarially test crashes after each #122 write/selector and concurrent CAS/source drift before menu exposure. No public teacher menu is wired by E1.

## Validation cadence

Changed-file Ruff, strict mypy, docs, and focused E1/D2/D1/#122/package regressions. No per-slice full suite, wheel builds or installed matrices. Reserve them for meaningful integration and final PR gates.
