# Issue #126 — I2A native #29/#30 correction selection and Standards gate

**Parent:** `f4e63e7ab24f4199067caae11f80a91108b0d10b` (I1 accepted).
**Scope:** test/documentation only. No production changes, no publication, source correction, Grade, Standard, or Report mutation. No real student records.

## Source / canonical chain

This slice reuses the accepted I1 **29-student, 6-question, 31-attempt ScoreForm manifest** through the installed ScoreForm public reader and Core's actual published-manifest services. On an isolated synthetic workspace, it additionally creates:

1. Current Core class metadata and Academic Period Calendar; an active Meridian Grade Item; an immutable and CAS-selected included Grade Item membership bound to the registered ScoreForm work.
2. Two **actual #29 immutable, CAS-selected included decisions**, each referring to one exact attempt-point item from the verified authorized projection (both original 0/6 and corrected 6/6 remain historically inspectable).
3. A separately authored and CAS-selected canonical **#30 explicit exactly-one policy**.
4. One immutable #30 selection decision, author-attributed and explicitly choosing **Attempt 2** (6/6) after declared teacher source review; no highest/latest rule. Source attempt 1 is not deleted, and the separate retake student is not selected.
5. Independent #30 resolver and #126 F3B1 `verify_student_current_use` Standards gate, with a fresh authorized ScoreForm reader projection. Only Attempt 2 included evidence may pass the gate; the gate itself never writes Standards.

## Acceptance variants

- Exact native #29/#30 author and CAS select, independent source and pointer check, unchanged ScoreForm bytes, no #31 for one selected attempt.
- Immutable decision **written but not current** remains unavailable for current academic use.
- A stale `expected_current_decision_revision` fails without moving the pointer; history is preserved.
- Exact immutable same-byte retry is idempotent; no duplicate decision.
- An unrelated real retake pair never receives an inferred #30 decision.

## Honest limits / next increment

I2A calls published native storage APIs to qualify the **actual canonical state**. It does **not** automate a teacher's `Save and Use This Decision` keystrokes or exercise the #122 receipt/orchestration bridge. Those are I2B's explicit acceptance objectives; I2A must not be described as installed teacher-interface Save/Use qualification or as a complete D4 mixed-wheel journey.

The F3B1 Standards gate is exercised for independent currentness, not a new Standards association. Full proficiency, Report 9 #133/#134, all producer boundary fixtures, elapsed human interactions, and final official-wheel and CI acceptance remain separate.

Accepted installed baseline: Core 0.6.6, ScoreForm 0.13.0 (version/runtime verified by runner); other installed components must be listed without claiming their fixture was exercised in this slice. Previous #126 regression suite remains required.
