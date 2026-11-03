# Meridian #124 — E2G3O6 teacher-interaction benchmark and acceptance ledger

Baseline for this slice: `69af32e736e8e425ec6109d0be00d2c3b4b8427b`.

## Scope

This slice adds executable **post-implementation** teacher-interaction measurements to the synthetic Core/Meridian canonical path and records unresolved acceptance gates. No runtime changes, publishing, producer access, profile changes, or package allowlist changes. Input counts include selection and final acknowledgement; the class is already selected in session. The old teacher flow's prompt count is **not** reconstructed by guesswork.

| Journey | Expected terminal inputs | Academic confirmations | Manual academic IDs | Exact path |
| --- | ---: | ---: | ---: | --- |
| Registered assessment, create+link | 9 | 1 | 0 | period → work → setup → purpose → title → rationale → attribution → APPLY → acknowledge |
| Published assessment, create+link | 9 | 1 | 0 | Same; publication retained in session |
| Existing Grade Item, link | 8 | 1 | 0 | period → work → setup → existing choice → rationale → attribution → APPLY → acknowledge |
| Already-ready assessment | 4 | 0 | 0 | period → work → setup → acknowledge |
| Registration changes at APPLY | 9 | 1 attempted | 0 | Final review fails closed; no new academic actions |
| Ambiguous setup classification | 0 within setup handler | 0 | 0 | Stop before presenting a proposal |

The attribution **ID** prompt remains a teacher identity input, not a raw academic record ID. These counts are candidate assertions until Windows qualification reports them. The 29-student/six-question fixture, full historical before measurement, and end-to-end eligibility continuation are **not established** by this benchmark.

## Acceptance audit — do not mistake focused tests for issue closure

- **A1 — Partial:** named ScoreForm via main menu, Core catalog; Quillan/Concord and arrival from existing evidence/Grade Items screens require final qualification.
- **A2 — Partial:** registration-only, synthetic published, withdrawal and missing-catalog behaviors covered; complete producer-specific unsupported states still pending.
- **A3–A5 — Demonstrated synthetically:** already-ready no-op, link existing, create and link, canonical currentness and original receipts in E2G3O4/O5.
- **A6 — Substantially covered:** explicit purpose, period and one APPLY; no Grade or standards mapping granted.
- **A7 — Partial:** ambiguous setup fail-closed; complete duplicate-name/excluded/archive matrix pending.
- **A8 — Substantially covered:** cancellation before purpose and at final confirmation, both new and existing paths.
- **A9 — Partial:** registration drift, publication withdrawal, session conflicts; full supersession/calendar/CAS adversarial matrix pending.
- **A10–A11 — Substantially covered:** original-action interrupted selection, stored receipt/correlation inspection, no duplicate reentry, no-op reopening. All crash boundary and exact-resume scenarios remain to review.
- **A12 — Partial:** catalog/published synthetic context requires no student manifest read or evidence authorization; denied protected-evidence tests require explicit evidence-reader gating.
- **A13 — Open:** fresh, isolated **five-wheel** (Core, ScoreForm, Quillan, Concord, Meridian) installed composition and tested published producer contract compatibility. No mock should stand in for this gate.
- **A14 — Partial pending qualification of this slice:** current path input count/confirmation benchmark; historical before count, 29×6 synthetic classroom context and repeated-scope comparison still needed.
- **A15 — Open:** targeted tests are green through E2G3O5. Full suitable Ruff/mypy/tests, packaging/wheel validation, final SHA's Windows+Ubuntu CI and dependency matrix are still required.

## Next qualification gates

1. Qualify E2G3O6's exact input assertions on the target Windows environment. If counts differ, fix the measurement after examining actual prompts, not by weakening academic constraints.
2. Complete producer compatibility/blocked-source matrix (including Quillan and scored/evidence-only Concord), navigation origin and collision scenarios.
3. Perform the installed five-wheel integration with compatible pinned versions, runtime evidence and 29×6 synthetic context.
4. Run final lint/type/tests/package validation with a release candidate; require all required CI jobs at the final SHA. Produce acceptance report and PR; **do not automatically merge or close #124**.

Full issue criteria: https://github.com/Paper-Data-Suite/pds-meridian/issues/124
