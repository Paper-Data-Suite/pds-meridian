# Issue #125 — skeptical acceptance ledger (H1)

**Status: OPEN — not a release authorization.** Evidence below describes the
committed development branch at `e5b06df74210ca66dc9270b237102063dfd1556c`
and the logs from its bounded, synthetic qualification. It does not establish
that the final PR SHA, the candidate wheel, or all supported CI jobs pass.

All test fixtures use fabricated students, assessments, and teacher identities.
No classroom information belongs in this ledger or its CI output.

## Evidence and unresolved obligations

| Criterion | Status | Evidence and remaining qualification |
| --- | --- | --- |
| A1 | Targeted | F1 inbox hook tests and F2 teacher menu; full candidate-wheel navigation remains unverified. |
| A2 | Targeted | B read-only roster tests and G1 real ScoreForm/Quillan/Concord source projection. |
| A3 | Partial | B source and absence distinctions and G1 native coverage; full denied-versus-unsupported teacher display remains to be audited. |
| A4 | Partial | B duplicate/native exception tests, F2 replacement, G1 competing attempts; complete source-correction routing matrix needs final review. |
| A5 | Native targeted | G2A native ScoreForm/Quillan/Concord canonical decisions and G2B six-action acceptance. |
| A6 | Targeted | C disposition/reason tests and D per-item bridge; complete native non-Include matrix not separately qualified. |
| A7 | Targeted | C student/item fixed-selection tests and F1/F2 exception menu tests; native override combination remains to be audited. |
| A8 | Targeted | C and F2 preserved current decisions and explicit replacement behavior; final adversarial review pending. |
| A9 | Native targeted | F1 exact APPLY/cancel and G2B 174-action cancellation with zero academic writes. |
| A10 | Native targeted | D preflight, E2 authorization-first recovery, G1 authorization denial and G2A roster drift. |
| A11 | Targeted | D and E2 CAS/conflict tests; native early/middle/late collision matrix remains incomplete. |
| A12 | Native targeted | E1/E2 restart tests; G2B post-write interruption recovered two current, one unattempted, zero replays. |
| A13 | Native targeted | E2 idempotency and G2B no-replay after interrupted action; whole-class rerun still requires explicit check. |
| A14 | Native targeted | G1 installed ScoreForm 29-by-6, Quillan absent students, Concord scored/group/evidence-only; G2A canonical native decisions. |
| A15 | Partial | Targeted test isolation of eligibility authoring; a complete collateral-mutation inventory is still pending. |
| A16 | Partial | 29 students, six questions: 406 total ScoreForm native evidence items, 174 correctness items; one input to select all correctness candidates; 174-item plan/cancel and six-action timing. No empirical 174-item canonical execution or individual-action interaction baseline; neither is claimed. |
| A17 | Partial | F1/F2 navigation and paging regressions; final `:notes`, NO_COLOR, and full terminal-fallback matrix pending. |
| A18 | **OPEN** | Full lint, format, mypy, documentation, pytest, build, Twine, wheel/sdist, isolated official-release four-producer candidate smoke and final PR SHA Windows/Ubuntu 3.11–3.14 CI are not yet qualified. |

## Observed G2 results; performance caveat

G2A: native canonical eligibility and reconciliation passed for ScoreForm,
Quillan and student-scored Concord; authorization and roster-denial cases
passed. G2B: six synthetic ScoreForm actions took approximately 53.446 seconds;
post-write interruption took 18.551 seconds for two attempts; the 174-item
correctness review plan took 0.143 seconds and **wrote nothing** on cancellation.
The measured one-input selection time was 0.424 ms in G2A. These values
measure different operations; a full-class execution time cannot be derived
reliably by treating the selection benchmark as the execution benchmark.

## Final qualification sequence (H2 and H3)

1. Verify official released Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6,
   Concord 0.3.2 wheels with the repository's own exact hash verifiers. Record
   SHA-256 for each supplied artifact; never accept only an installed version.
2. Run `scripts/validate_repository.py` with all four explicit official-wheel
   paths. This includes full pytest, Ruff lint and now format, mypy,
   documentation, wheel and sdist build/inspection, Twine and six isolated
   installed-qualification matrices. Do not use editable/source-installed
   Meridian as a substitute for the built candidate wheel.
3. Perform candidate-wheel **#125-specific** native teacher eligibility
   acceptance with official-release dependencies and verify imported Meridian
   is actually in the temporary wheel environment. Existing G1/G2 tests ran
   under the Meridian source tree, so that earlier success alone is insufficient.
4. Review remaining A3/A4/A6/A7/A11/A13/A15/A16/A17 edge cases explicitly,
   recording a blocker or targeted test as needed; keep #125 open for any
   unresolved substantive defect.
5. Open the PR from the final candidate branch, require all **eight** CI
   Windows/Ubuntu Python 3.11–3.14 jobs on the **final PR SHA**, and record
   exact outcomes. The original branch presently has no open PR or CI run
   recorded; green local tests do not establish green PR CI.
6. Confirm clean working tree, review the complete A1–A18 ledger, obtain an
   explicit merge decision, then squash/merge only after required checks pass.
   Do not release or change Suite, Core, or producer repositories from this gate.

The final acceptance owner must replace provisional statuses with observed
results and concrete links. This ledger is a review instrument, not a way to
mark an acceptance criterion complete without executing its gate.
