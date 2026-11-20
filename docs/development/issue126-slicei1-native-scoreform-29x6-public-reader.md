# #126 — Slice I1: installed ScoreForm 29×6 public-reader classroom witness

## Baseline and scope

Parent: accepted #126 H2 commit `7bba80de753748b78e07e16bfbe49aafb18fd743` on branch `126-verified-correction-attempt-reassessment-management`.

**This slice is native at the released producer-reader/Core publication boundary, not a full teacher-journey or physical scan test.** It uses ScoreForm's *actual canonical public manifest constructors, serializer and reader*, Core's actual work registration, class roster, publication and catalog services, Meridian's installed-package adapter, and the ordinary authorized guided projection. The workspace and every identity are synthetic, temporary, and isolated.

## Synthetic case

- 29 students, one ScoreForm assignment, six one-point multiple-choice questions, and 186 recorded native question responses across 31 attempts.
- Student 01 has historical Attempt 1 (0/6, `pds2_scan`) and Attempt 2 (6/6, `scan_review_manual` with a review-failure reference). **The producer fields do not certify that Attempt 2 corrected Attempt 1's cause**; a teacher-reviewed academic decision is still required.
- Student 02 has two distinct manual observations, 4/6 then 5/6. This pair is not assumed a correction or a selected reassessment simply because it was recorded later.
- Students 03–29 have one synthetic 5/6 native observation each.
- One actual Core `academic_result_set` publication is registered with `multiple_attempts`, `points`, and `question_evidence`. Native attempt numbers remain distinct from the publication's record-set revision.
- Core roster contains exactly the 29 manifest subjects; all identifiers are artificial; there are no scanned papers, confidential records or actual student grades.

## Executable acceptance assertions

1. Actual installed ScoreForm canonical reader accepts serialized 29×6 data and preserves each attempt's points, origin and sequence.
2. Core publishes the exact manifest digest, and Meridian's authorized ScoreForm adapter emits 31 × 14 = 434 source items (one native point value, one origin and two source items per question).
3. Both 0/6 and 6/6 are present in the authorized projection; Attempt 2 retains its explicit scan-review provenance. Chronology, score or provenance is never converted to a verified causal correction.
4. An actual Core roster-backed teacher review includes all 29 exact authorized students and their published evidence.
5. The retake case preserves two native observations and the source manifest remains unchanged after read-only inspection.
6. A missing publication/evidence authorization blocks the same native reader path.
7. No #30 immutable attempt decision or current attempt pointer is authored by these read-only tests.

## Deliberate evidence limitations

The published Core 0.6.6 and installed ScoreForm distribution are identified by the runtime probe; this probe **does not prove publisher authenticity, release signing or wheel-file SHA-256**. The Meridian source checkout remains an editable development consumer and is **not** a released Meridian wheel qualification.

This I1 witness does **not** set up a Grade Item or #29 operative eligibility, execute #30/#31 academic Save/Use, complete the real keyboard-driven correction, verify full #122 recovery, or measure teacher completion time. Those are next-phase I2/I3 and final J gates, not silently represented by a successful source publication. A real source scan is absent. Cross-producer Quillan/Concord native boundaries remain separately qualified.

Report 9 generation and current-attempt item statistics remain owned by #133/#134. The result of this fixture must never be interpreted as a Report 9 fix, automatic proficiency grade, or producer-certified correction relation.

## Evidence grading

| Level | I1 result | Still outstanding |
| --- | --- | --- |
| D0 | #126 authority and Core/Suite contracts acknowledged | None for this test shape |
| D1 | Native synthetic test source and public-interface assertions | Native CI/wheel package on final SHA |
| D2 | Installed Core 0.6.6 and installed ScoreForm reader versions checked at test execution | Provenance/first published new Core UI version not attested |
| D3 | Meridian source checkout consumes actual installed producer/Core APIs | Official installed Meridian consumer wheel and live teacher Save/Use |
| D4 | Synthetic native public-reader/class-roster fixture checked | Full mixed-wheel, real teacher journey, Windows/Ubuntu CI on final PR SHA |

This separation must be retained in the Issue #126 A1–A18 ledger and before the branch merge.
