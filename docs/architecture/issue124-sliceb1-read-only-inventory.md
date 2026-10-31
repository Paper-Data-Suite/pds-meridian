# Meridian #124 — Slice B1: canonical read-only assessment setup inventory

**Base:** `39db0cffc35b27bb288170792ca0c173d16b3738` (#124 Slice A). **Scope:** one additive Meridian read service, the package allowlist update, synthetic isolated unit tests, this note. No menu wiring, Grade Item write, membership write, actor mutation, publisher operation, or evidence authorization.

## Read and trust boundaries

`discover_assessment_setup_inventory(root, class_id, school_year, period_id)` requires an already selected **exact** class/year/marking period. It queries Core's derived Academic Work Registration and current `academic_result_set` Publication catalog, checks both bounded result counts, reloads the canonical current registration for every returned work, reads the selected Core academic calendar and Meridian Grade Item projection, and validates the exact selected included work relationship against Grade Item revision, registration revision, period ID, school year and calendar revision. A current catalog publication **candidate** is independently compared to the canonical current publication-series head; this does not authorize opening its manifest or declaring its results readable. A missing catalog publication is labeled *no current catalog result*, not proof that publication never occurred.

The returned immutable candidate stores technical identities for later verification but separates publication state from Grade Item setup state. `ready` requires exactly one matching selected active Grade Item with the exact operative included membership, and no competing related Grade Item. Reused titles never establish identity. Excluded, archived, unselected, historical-basis, registration-drift, or period-drift relations are **not** ready. Multiple ostensibly ready relations are ambiguous. Cancelled registration is not described as setup-ready. No default Grade Item purpose or academic judgment is selected.

## Follow-on work

B2: distinguish registered-only and withdrawn history with precise canonical series semantics, add named/paged choices and teacher-facing recovery states. C: one read-only setup proposal with explicit teacher purpose/period. D/E: combine canonical #122 actions and exact partial-state recovery. F: integrate inbox/Grade Items menu and return-to-origin. G/H: installed producer and classroom qualification. **B1 alone does not complete acceptance A1–A15**, nor does it claim real producer installed acceptance. The source-level unit tests use injected read adapters; production defaults call released Core/Meridian APIs.
