# Changelog

## Unreleased

### Added

- Teacher-controlled grouping-signal derivation policy over one exact #35
  Academic Period proficiency basis, with an explicit planning dimension,
  teacher-defined contiguous proficiency-scale-position bands, fixed
  `same_level_same_band` tie handling, and independent `noncontributing`/
  `blocking` handling for missing and insufficient results.
- Canonical immutable grouping-signal policy storage with SHA-256 sidecars,
  contiguous revision history, exact replay/conflict semantics, explicit
  compare-and-swap `current.json` selection, historical reselection, and exact
  Core class/Academic Period/standard plus #35 policy/scale dependency checks.
- Focused, hardening, integration, package-boundary, read-only-import, and
  isolated installed-wheel qualification for #37, explicitly proving that policy
  creation/selection does not assign students, create a Core grouping signal,
  export CSV, or require Concord.
- Formal adoption of Core's neutral immutable `grouping_signal_set_v1` as
  Meridian's sole shared planning-signal interchange, qualified against exact
  Core v0.6.3 while preserving `pds-core>=0.6.3,<0.7` and introducing no direct
  Meridian-to-Concord runtime dependency.
- Focused qualification of Core's typed signal model/canonical JSON,
  `grouping_signal_csv_v1`, immutable exchange storage and canonical signal-byte
  digest, and workspace-aware roster diagnostics, including partial coverage,
  exact student identity, immutable replay/conflict semantics, and the
  distinction between upstream `source.snapshot_digest` and Core's signal
  digest.
- Isolated installed-wheel grouping-signal acceptance using only exact Core
  v0.6.3 plus the candidate Meridian wheel, explicitly proving Concord is absent
  and that #36 adds contract adoption rather than production derivation or
  export behavior.
- Academic Period standards-proficiency aggregation over exact immutable #34
  Grade Item result snapshots and exact #28 membership provenance, with
  explicit `direct` and `descendants` scope over one exact Core calendar
  revision and deterministic `highest`, `lowest`, `median`, and `mode`
  strategies.
- Explicit always-blocking `period_scope_mismatch` handling for mixed sibling,
  outside-target, calendar-revision, and school-year mismatches without date
  or current-period inference.
- Separate `missing_result`, #34 `insufficient_evidence`, and calculated low
  proficiency states, with independent noncontributing/blocking policy for
  missing and insufficient results.
- Immutable SHA-256-bound Academic Period proficiency policy/result histories,
  explicit compare-and-swap current selection, deterministic replay and
  explanations, pure freshness diagnostics, package/sdist guards, and isolated
  installed-wheel acceptance.
- Current unreleased ScoreForm qualification updated to exact v0.11.0,
  preserving the existing `scoreform_academic_work_v1`,
  `scoreform_academic_result_manifest_v1`, `academic_results`, and public
  reader projection semantics while retaining v0.10.0 as the released
  Meridian v0.1.1 historical baseline.
- Pure deterministic Grade Item-level standards-proficiency calculation over
  exact #33 aggregation inputs, exact proficiency-scale/policy revisions, and
  algorithm version 1, with explicit `highest`, `lowest`, `median`, and `mode`
  strategies and structured insufficient-evidence/tie behavior.
- Immutable SHA-256-bound standards-proficiency calculation-policy and result
  histories with canonical JSON, exact embedded aggregation inputs, explicit
  compare-and-swap `current.json` selection, historical reselection, and
  deterministic calculation fingerprints/explanations.
- Pure standards-proficiency freshness diagnostics distinguishing
  `inputs_changed`, `policy_changed`, `scale_changed`, and `algorithm_changed`
  without mutating history or automatically recalculating/selecting results.
- Integration acceptance proving calculate -> persist -> explicit select ->
  reload -> reproduce -> stale-input detection, including zero-performance
  input remaining `insufficient_evidence` rather than zero/lowest proficiency.
- Canonical teacher/policy standards-evidence association decisions over exact
  projection sources and durable Core standard IDs, with explicit
  producer-declared/explicit bases, immutable SHA-256-bound revision history,
  and compare-and-swap current selection.
- Deterministic bounded Grade Item/student/standard/scale aggregation inputs
  preserving exact upstream references, mapped performance, native non-score
  states, and closed explainable exclusions without proficiency arithmetic.
- Core v0.6.3 standards-framework resolution and current release qualification,
  plus Quillan v0.10.0 exact-reader qualification with unchanged adapter
  projection semantics.

- Canonical immutable teacher-defined proficiency scales with ordered criterion-referenced
  levels, explicit proficiency thresholds, SHA-256-bound revision history, and
  compare-and-swap current selectors without fixed four-level semantics.
- Producer-neutral native-value mapping profiles with exact source signatures and
  explicit `exact_scalar`, `exact_native_scale`, and `raw_points` modes; mapped,
  unmapped, unsupported, and native-state outcomes remain distinct.
- Exact native-scale snapshot binding, non-inverting ordered mappings, denominator-bound
  raw-point ranges without percentage normalization, and package/installed-smoke
  coverage preserving ScoreForm, Quillan, and Concord semantic separation.

- Canonical immutable reassessment policy and student relationship decision
  records over one exact operative #30 attempt-selection decision, with explicit
  `retain`, directed `replace`, semantic `combine`, and explicit `recency` modes.
- Exact contributing-attempt provenance, preserved replaced history, deterministic
  combination groups, explicit recency order, and fail-closed multi-attempt
  `no_decision` behavior without numeric ranking or reduction.
- SHA-256-bound reassessment policy/decision history with explicit compare-and-swap
  current selectors, #30 and #31 policy staleness resolution, single/none
  pass-through states, and Quillan/Concord non-applicability that preserves
  producer-native correction and supersession semantics.

- Canonical immutable attempt-selection policy and student decision records with
  explicit-only selection semantics, bounded zero/one/set cardinality, and
  independent SHA-256-bound policy/decision revision history.
- Producer-neutral exact attempt observation identity over one immutable
  projection snapshot, plus deterministic candidate derivation from exact #29
  `operative_included` eligibility revisions without score or recency ranking.
- Explicit compare-and-swap policy/decision selection, stale
  membership/policy/eligibility/candidate resolution, ScoreForm
  `multiple_attempts` applicability, and explicit Quillan/Concord
  non-applicability without fabricated attempts.

- Canonical immutable evidence-eligibility decision records scoped to one exact
  Grade Item and projection-snapshot evidence source, with distinct `included`,
  `excluded`, `pending`, `unsupported`, `superseded`, and `withdrawn` semantics.
- Exact source provenance binding Core work/publication identity, projection
  `cache_key`, snapshot SHA-256, and evidence `item_id`, plus exact included
  Grade Item membership revision/digest provenance.
- SHA-256-bound eligibility history with deterministic source keys, explicit
  compare-and-swap `current.json` selection, source-lifecycle resolution,
  authorization-gated evidence validation, and fail-closed storage safety.

- Immutable Grade Item membership decisions with explicit `included`/`excluded`
  state, exact Grade Item revision/digest provenance, exact Core Academic Work
  Registration revisions, exact Academic Period Calendar revisions, teacher
  attribution, and historical supersession.
- Canonical membership storage beneath each Grade Item with SHA-256-bound
  revisions, explicit compare-and-swap `current.json` selection, deterministic
  relationship queries, Core-backed dependency validation, and fail-closed path
  and integrity checks.
- Academic Period assignment that binds Core `AcademicPeriodRef` plus exact
  calendar revision without date-based inference, hierarchy propagation, or
  publication-driven membership.

- Immutable Meridian Grade Item revisions with stable logical identity, closed
  purpose/status contracts, exact reserved weighting metadata, and reusable
  Core registered-work revision references used by the separate membership layer.
- Canonical Grade Item persistence under each Core class with contiguous
  immutable revision history, SHA-256 sidecars, bounded integrity-checked reads,
  explicit `current.json` selection, compare-and-swap updates, and fail-closed
  path/symlink/storage validation.
- Grade Item model/storage documentation and focused regression coverage that
  preserves the boundary between Grade Item definition, membership, evidence
  eligibility, proficiency, and later Grade calculation.

## 0.1.1 — 2026-08-18

### Added

- Cross-producer synthetic ingestion acceptance covering ScoreForm v0.10.0,
  Quillan v0.9.0, and Concord v0.2.0 together in one Core workspace, including
  semantic separation, cache isolation, multiple Academic Periods, diagnostics,
  authorization isolation, deterministic replay, and failure privacy.
- Cross-producer acceptance documentation confirming that no new runtime,
  cache-schema, grading-policy, or producer-contract changes were required.

- Exact optional `pds-concord==0.2.0` adapter using Concord's released
  consumer-neutral Academic Result reader, dynamic capability derivation,
  non-individualized Group Scores, exact target ownership/version, rich native
  Scoring Scales, Score history, Evidence Link and Moderation provenance, and
  explicit unevaluated eligibility.
- Concord release-wheel authentication, installed adapter smoke validation,
  exact package-extra validation, and producer-neutral evidence/cache/diagnostic
  support for non-student evidence.
- Read-only `meridian publications list` and `meridian publications verify`
  diagnostics with bounded Core discovery, canonical reload, exact producer
  compatibility, adapter support, and reader readiness reporting.
- Authorization-gated `meridian evidence inspect` and `meridian evidence explain`
  diagnostics over exact immutable projection snapshots, including deterministic
  filters, typed value output, existing `EvidenceEligibility`, and `cache.*`
  current-use explanations without new grading policy.
- Producer-neutral `meridian.diagnostics` runtime models, deterministic text/JSON
  rendering, installed-wheel diagnostic smoke coverage, and security/package
  validation for the new read-only command surface.

- Exact optional `quillan==0.9.0` adapter using the released public reader,
  native writing-review states and scale, deterministic private IDs, public
  producer provenance, explicit composition, and unchanged cache boundary.
- Quillan wheel authentication, real-reader integration coverage, installed
  adapter smoke validation, and exact release-wheel CI setup.

- Exact optional `scoreform==0.10.0` adapter using the released public reader,
  deterministic projection, explicit registry composition, and native
  provenance for all three ScoreForm result origins.
- ScoreForm wheel authentication, Core-to-cache integration coverage, installed
  adapter smoke validation, and exact release-wheel CI setup.

- Installable `pds-meridian` package at version `0.1.1`.
- Required `pds-core>=0.6,<0.7` runtime dependency.
- Side-effect-free `meridian` command with help and version output.
- Strict typing, linting, tests, cross-platform CI, package checks, and isolated
  wheel smoke testing.
- Exact authentication of the official Core v0.6.0 wheel used by baseline CI.
- Synthetic-data policy and privacy-safe Core-contract fixtures.
- Reusable documentation and repository validation tooling.
- Immutable `meridian.evidence` inventory models with exact Core provenance,
  producer-native targets, result kinds, scales, non-score states, projection
  identity, and explicit eligibility status.
- ScoreForm-shaped and Quillan-shaped synthetic inventory tests that preserve
  attempts, question states, review dispositions, and native scale identity
  without importing either producer package.
- Immutable `meridian.adapters` interface, exact contract key, descriptor,
  projection request, explicit registry, and stable fail-closed errors.
- Lazy producer-reader distribution checks and strict validation that projected
  inventories retain the requested Core provenance and selected projection
  identity.
- Synthetic adapter tests covering exact no-fallback selection, capability
  rejection, reader availability, controlled failures, and contract violations.

- Immutable `meridian.ingestion` models for bounded discovery, canonical
  publication context, publication-series observation, authorization, and
  prepared adapter requests.
- Core Academic Catalog candidate discovery that never promotes catalog rows to
  canonical authority or rebuilds derived state automatically.
- Exact canonical Publication Record, referenced/current registration, series,
  and withdrawal reload with deterministic candidate-drift rejection.
- Core-owned producer compatibility evaluation followed by exact Meridian
  adapter selection and non-importing producer-reader readiness checks.
- Explicit deployment authorization before manifest access, Core path/digest
  verification, bounded immutable byte loading, and in-memory SHA-256 handoff.
- Final canonical-state rechecking that rejects withdrawal, supersession,
  registration, disappearance, or integrity changes during preparation.
- Synthetic ingestion tests covering catalog failures, drift, registration,
  historical and withdrawn series state, compatibility, authorization ordering,
  manifest integrity and bounds, race detection, and no adapter invocation.
- Exact evidence mapping conversion preserving native scalar types, scales,
  non-score states, provenance, eligibility, and deterministic order.
- Immutable projection snapshots with canonical JSON, exact cache identity,
  digest-bound storage, bounded reads, locking, exact replay, and explicit
  nondeterminism failures.
- Fresh authorization before persisted cache reads and read-only current-state
  assessment for supersession, withdrawal, registration, profile, adapter,
  reader, manifest, and authorization changes.

### Fixed

- Projection-cache replay nondeterminism now compares canonical serialized
  inventory bytes rather than Python object equality, preserving
  serialization-significant distinctions such as signed zero and timezone-offset
  representation.
- Projection-cache reads now bind the freshly authorized purpose/student scope
  before protected snapshot bytes are opened.
- Release-facing package and CLI descriptions now state only the implemented
  publication-ingestion and typed-evidence diagnostics surface.

### Release qualification

- Added frozen-upstream dependency-direction verification, explicit
  source-distribution boundary validation, source-tree-isolated installed-wheel
  smoke environments, and one-environment ScoreForm/Quillan/Concord coexistence
  qualification.
- Added the durable v0.1.1 foundation release-audit record and direct regressions
  for audit-discovered release blockers.

The package does not yet implement the remaining Portia/Vitrine producer adapters,
eligibility or selection policy, proficiency, Grades, or reports.
