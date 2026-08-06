# Changelog

## Unreleased

### Added

- Installable `pds-meridian` package at development version `0.1.1.dev0`.
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

The package does not yet implement real producer adapters, adapter invocation,
real producer projection, eligibility or selection policy, proficiency,
Grades, or reports.
