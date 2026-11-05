# Meridian #124 — E2G3O10 native scored-Concord acceptance

## Intent

Qualify native Concord 0.3.4 scored-result publication against the installed five-wheel environment previously built for E2G3O8, then exercise Meridian's ordinary teacher assessment discovery and one-confirmation Grade Item/membership setup against the resulting canonical Core Publication Record. This is a test-only slice; no producer or academic schema changes.

## Exact production boundaries

- Concord creates the Activity, Scoring Scale, local Criterion Set, Score Record and explicit Academic Work Registration. Its `publish_concord_academic_results` generates a native, SHA-256-bound `concord_academic_result_manifest_v1` and invokes Core publication/catalog services.
- Meridian discovers the canonical publication by title and selected class/marking period, then delegates its one-APPLY Grade Item and included-membership setup through existing #122 and E2C actions; canonical receipt/correlation counts, period identity, and zero-write reentry are asserted.
- Two scored targets are tested separately: `core_student` and `concord_group`. A Group Score stays a Group Score in the native producer manifest; no individual score or Grade is inferred.
- An `evidence_only` Concord Activity is explicitly registered but cannot publish a fabricated `academic_result_set`; Meridian Grade Item setup remains untouched.
- The source-tree pytest module intentionally skips unless `PDS_ISSUE124_CONCORD_NATIVE_TEST=1`. Its installed execution uses the retained five-wheel environment and no editable producer source.

## Exclusions and follow-up

This test proves an installed native Concord scored publication and Grade Item relationship, not authorization to read protected student work or grading/proficiency calculation. It does not assert a final Ubuntu/Windows candidate-SHA CI run or replace #125–#129. Final release gate remains responsible for package and CI matrix, adversarial authorization coverage, and explicit issue acceptance review. Any producer contract incompatibility must be resolved in its owner repository rather than patched ad hoc in this Meridian branch.
