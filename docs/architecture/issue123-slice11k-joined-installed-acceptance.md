# Meridian #123 — Slice 11K: joined installed teacher acceptance

**Baseline:** `e2c164cf767c22fa223cbc87c223da001193d2ab` (11J, CI #138 eight jobs green). **Scope:** Additive synthetic installed-domain qualification, source tests and this evidence description. No production menu, schema, permission, write, producer-contract or packaging modification.

## Journey to be proven

A new isolated five-wheel environment runs a standalone source-side acceptance script from outside the repository against only installed Core/Meridian/ScoreForm/Quillan/Concord distributions. The synthetic source fixture is the qualified Slice 11G 29-student Grade Item and selected proficiency record, including exact persisted #42 evidence provenance. The script explicitly seeds a current Planning Signal policy **before** starting the read-only teacher session. Seeding does not access live teacher or student records.

One process-local verified `TeacherNavigationContext` then exercises the **real installed** Grade Item review, current Grade Item proficiency, current Grade preview, selected Grade Item proficiency explanation, and named Planning Signal readiness controllers. It checks exact named output, the class selected only once, roster duplication/disambiguation, absence of technical-ID prompts, unchanged academic file digests through every read, and class-switch invalidation. The Grade preview may correctly report *not configured* because the source fixture does not invent a current Grade policy; it must never report an invented numeric zero. Planning readiness may show a genuine blocker from the selected synthetic policy; observing a policy and its exact readiness status does **not** constitute exporting a Planning Signal, creating Concord groups, or generating Grades.

The program proves a joined **read-only Grade Item → Proficiency → Grade review → Explanation → Planning readiness** experience. It does **not** prove consequential Grade writes, ReportingSnapshot freeze, export/receipt commits, authorized producer evidence access or the entire Grade → snapshot/export production chain. Those require their own independent acceptance before #123 closure if the issue's full end-to-end criterion is enforced literally. This distinction must remain visible in the final ledger.

## Acceptance gates

- Strict Python/Ruff/mypy and 11K harness tests; complete CI-mirrored repository validator.
- Wheel/sdist/package allowlist unchanged; build an exact candidate Meridian wheel from committed baseline plus additive 11K sources.
- Install five pinned released distributions in a new isolated venv; execute the joined program with `PYTHONPATH` removed and an external working directory; confirm success marker, read-only workspace and unchanged installed packages.
- Run all eight GitHub CI matrix jobs at the resulting commit; do not merge or close on only local passes.
