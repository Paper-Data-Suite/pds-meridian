# #124 E2G3F — Opt-in interactive recovery navigation

**Baseline:** `6e88efde7da234ed0ac48d124cfbca16b48db0f3`.

The existing recovery menu now accepts an optional, typed `assessment_bridge_dependencies` argument. When supplied and no explicit reconstructed loader overrides it, it constructs the E2G3E teacher-choice provider and E2G3D fresh-review loader. The E2G3C receipt and canonical verification remain mandatory before E2G1 may present an explicit `RESUME` prompt. No dependencies means the existing #122 recovery remains unchanged.

The menu also corrects a fall-through bug: a handled verified composite assessment action must not subsequently invoke the individual #122 selection path.

**Limit:** This parameter must still be passed by the top-level teacher menu for default interactive activation. No academic write is added by this slice; test with synthetic fixtures before production.
