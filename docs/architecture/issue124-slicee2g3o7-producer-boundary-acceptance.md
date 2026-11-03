# Meridian #124 — E2G3O7 producer provenance and drift acceptance

**Required parent:** E2G3O6 HEAD `48e849ec94a061e36687b8f6e8efe1b17593f983`.

## Why this slice exists

E2G3O6 qualified 112 focused tests and measured single-confirmation interaction counts. The issue acceptance ledger still identifies a producer-specific gap: Quillan published standards ratings, Concord scored versus evidence-only distinction, and exact publication/calendar drift just before APPLY. This slice adds eight synthetic **Core canonical-provenance** tests. No new production writer, privileged file reader, authorization path, package module, or second academic action engine is introduced.

## What the tests actually prove

- Current Quillan Core registration and a synthetic publication record with `standards_ratings` capability appear by a human title; a *formative* registration does not silently select a Grade Item purpose. Explicit teacher selection and one `APPLY` create an included Grade Item/work/period relationship using original #122 operations and E2C correlation; reopening is zero-write.
- A Concord Core publication record with `criterion_scores` capability (synthetically labelled scored) reaches the exact same verified Grade Item relationship only when the teacher explicitly chooses a purpose. This does **not** assert criterion-to-standards equivalence or individual student attribution.
- Concord registration without a current scored publication is not silently elevated into an `academic_result_set`, and setup is blocked without Grade Item/receipt/correlation writes.
- Identical assessment titles across ScoreForm and Quillan remain visibly distinct by producer without disclosing canonical identifiers or selecting the first by title.
- A Quillan withdrawal and a Core academic-period calendar revision introduced at the final confirmation stop before new Grade Item and original #122 receipts are created.

All cases use a pytest temporary workspace. Synthetic publication manifests contain **no student records** and serve only as SHA-256-verified placeholders required by Core publication storage. They are not producer-generated ScoreForm/Quillan/Concord academic result manifests. Tests do not inspect protected result contents.

## Unresolved acceptance gates

- **A13 remains open**: build and install compatible release wheels for Core, ScoreForm, Quillan, Concord, Meridian into a fresh isolated five-wheel environment. A real producer-generated Quillan manifest and a genuine scored Concord manifest must pass their own producer contracts before claiming end-to-end interoperability. This slice tests Core-facing provenance shape, not publisher execution.
- **A7/A9/A10 partial**: further CAS, archive/excluded membership and all interruption-boundary tests remain to review against the issue matrix.
- **A14 partial**: E2G3O6 measured current menu interaction counts; historical baseline, 29-student/six-question synthetic assessment and return-to-inbox demonstration are pending.
- **A15 remains open**: a candidate wheel build/install, full scoped Ruff, strict mypy, package inventory, Windows/Ubuntu Python CI at the final SHA, and explicit PR acceptance review are still required. Do not merge or close automatically.

This slice changes only one new test module and this architecture note. It reuses E2G3O4/O5 real Core/Meridian synthetic fixtures and their receipt/correlation checks rather than stubbing the Grade Item domain.
