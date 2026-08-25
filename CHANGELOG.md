# Changelog

## Unreleased

### Added

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
