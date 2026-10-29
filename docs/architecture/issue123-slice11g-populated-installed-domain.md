# Meridian #123 — Slice 11G: populated installed-domain acceptance

**Qualified base:** `c6d241aeb87181718e09f82b397ca0dd72cbf865` (CI history fix, 8/8 checks successful).  **Scope:** Three additive qualification scripts/tests and this document; no changes to production menus, public APIs, storage, dependencies, CI matrix, or Grade/proficiency algorithms.

## Real installed boundaries exercised

This slice adds `scripts/smoke_test_issue123_populated_domain_wheel.py` as an **explicit**, independent all-adapters prepared-wheel entry point. The child program `scripts/smoke_program_issue123_populated_domain.py` runs **from outside the source checkout** and verifies that Meridian and Core runtime imports come from the freshly installed virtual environment. It reuses the existing #42 explanation-trace fixture as a **source-only fixture generator**, not a production runtime import or second authority. The existing #96 matrix runner and 11D menu-only smoke remain untouched.

All records are created under a new temporary synthetic workspace. The child constructs:

- Two genuine persisted Core classes, including a 29-student primary roster with two distinct students named **Alex Rivera**, distinguished by roster position, and a second class for scope-switch testing.
- Genuine persisted selected Meridian Grade Item and standards-proficiency records from the existing #42 explanation-trace fixture, including the actual persisted membership, evidence eligibility, Standard association, mapping profile, policy and scale required by the explanation loader. An additional selected archived Grade Item is distinguishable from the active assessment.
- Registered, **unpublished** ScoreForm/Quillan work titles in Core; registered work is not evidence access. A Core marking-period calendar is deliberately advanced from one to two periods to challenge cached period witnesses.

It calls the real installed `TeacherAcademicChoiceCatalog`, `TeacherNavigationContext`, `run_named_grade_item_review`, and `run_named_grade_item_proficiency` with Core/Meridian's actual persisted readers and the existing Grade Item explanation loader. It checks current selected-result filtering, distinct duplicate-name options, no raw-ID prompts, no changed academic bytes during read-only navigation, and exact student/session context. An injected **denied explanation callback** verifies that the ordinary controller redacts an authorization-style error and retains no student selection; it is **not** a simulated real producer authorization revocation. Calendar revision change must invalidate the previously selected period, and switching classes must clear Grade Item/student/period context.

Six local tests validate subprocess isolation, fail-closed error handling, fresh synthetic-root enforcement, and exact reuse of the all-adapters installed environment; they do not substitute for the actual five-wheel run.

## What this slice does not establish

- A fully joined Grade -> snapshot/export or planning **execution** journey through every supported domain. The program traverses real persisted Grade Item/proficiency readers and shared context; other domain controllers remain covered separately.
- Live protected publication revocation or authorized producer manifest reads; the denial case uses an injected loader, and the source fixture's evidence references do not grant manifest access. The #42 fixture uses test-scoped validation mocks only while seeding synthetic provenance records, never while executing the installed explanation loader; this smoke does not claim live producer authorization.
- Current class-year auto-discovery or a teacher login/profile; a deterministic active-year reader is injected, while Core class metadata, rosters, Grade Items, calendar, and selected proficiency are physically persisted and re-read.
- Comparable legacy versus current input counts, teacher usability or performance thresholds, or acceptance on real student data.
- CI at the post-11G commit until a PR check run completes.

These gaps remain explicitly open in the #123 acceptance ledger for later 11G follow-on/11H reconciliation. **Do not mark issue #123 complete solely because this smoke passes.** No source data or prior immutable academic records are modified except the purpose-built synthetic fixture.

## Invocation

After obtaining an exact authenticated Meridian candidate wheel and the four pinned producer/Core wheels, run:

```text
python -m scripts.smoke_test_issue123_populated_domain_wheel <meridian-wheel> <core-wheel> <scoreform-wheel> <quillan-wheel> <concord-wheel>
```

The separate guarded Slice 11G runner builds the candidate from the pinned committed base in a temporary Git archive, validates the wheel, runs the prepared all-adapters smoke before committing, then pushes only after complete qualification. CI will rerun on the resulting PR commit.
