# Meridian #123 — Slice 11H: paired legacy/named controller measurements

**Baseline:** `169a7db3566b260f056bad8ede0421bb23adf0fc` (qualified Slice 11G). **Scope:** additive, source-tree synthetic measurement harness, regression tests and this documentation. No changes to production menus, Core/producer services, academic state, published packages or permissions.

## Exact paired workload

`python -m scripts.issue123_interaction_benchmark --repeats 21 --pairs 2 --warmups 3` exercises **the actual read-only legacy controller functions** `menu_grade_items._review_one_grade_item` and `menu_proficiency._review_grade_item` and **their ordinary named counterparts** `menu_teacher_named_review.run_named_grade_item_review` and `run_named_grade_item_proficiency`.

Both paths review the **same synthetic Grade Item** and the **same selected student's Standard proficiency** twice each, using equivalent injected pure read loaders. The named path uses the actual `TeacherNavigationContext`, `TeacherChoice` sorting/identity/witness verification and choice renderer. Its synthetic choice catalog exposes 29 student options, including two distinct *Alex Rivera* entries with seat disambiguators. The legacy path uses the actual manual ID-entry controller, not an estimated number of prompts.

For each mode the script captures actual `input_fn` calls, technical-ID prompts, repeated class-ID prompts, catalog reads by scope, Core-reader calls, and domain-loader invocations. Only the synthetic in-memory adapters are substituted; both sides must complete the same two domain reads per pair. A retained named class and student must remain the exact requested records. The output contains a monotonic elapsed-time median, p95, min and max across ordered-pair runs, with warm-ups excluded and alternating legacy/named order.

## Deterministic input contract

For **two pairs** (four completed domain read actions per mode), the test asserts:

| Controller measure | Legacy exact-entry route | Ordinary named route |
| --- | ---: | ---: |
| Input calls, including pauses/back | 16 | 13 |
| Technical canonical ID prompts | 12 | 0 |
| Repeated `Class ID` prompts beyond first | 3 | 0 |
| Grade Item/proficiency domain reads | 2 + 2 | 2 + 2 |
| Named catalog reads | 0 | **Measured**, expected nonzero due fresh witness checks |

The legacy comparison represents a **repeated review of a teacher-known exact record**. It does **not** include any extra lookup or copying needed to discover legacy IDs; the named result includes its actual bounded choice and currentness re-reads. This makes the baseline conservative as to manual lookup friction, but not comparable to authorization-restricted live-evidence discovery.

## Latency interpretation and limits

The harness samples local controller execution under an injected synthetic Core/Grade Item/proficiency reader. It is a **source-tree interaction microbenchmark**, not a benchmark of the installed five-wheel system, real disk/producer access, protected evidence, a physical terminal, or a student's actual data. The number of catalog re-reads is deliberately observable rather than counted as a defect: currentness checks are required. No fixed machine-independent latency threshold, time savings or percent speedup is asserted. Review runtime JSON rather than treating an expected input contract as observed timing.

Run the command in the activated Meridian development environment, capture JSON and record the Python/runtime/OS metadata when reviewing results. On each qualified run the safeguarded Slice 11H runner will execute the same command and print its measured results. No benchmark JSON, source workspace, selected user data or persistent teacher preferences are committed. The earlier Slice 11B (25 input calls) is **not** a paired legacy baseline and must not be used as the denominator.

## Still open for final #123 reconciliation

The controlled comparisons cover two representative read-only domain tasks, **not** every advanced author/select or the full Grade-to-snapshot/export/planning workflow. Slice 11G independently verifies an actual installed five-wheel domain journey, but this microbenchmark does not extend that coverage. CI and final ledger reconciliation must be evaluated at the resulting commit. The Proficiency → Planning Signal ordinary discoverability decision remains outstanding and should not be quietly recategorized by this measurement-only slice.
