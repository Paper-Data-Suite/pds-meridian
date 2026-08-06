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

The package does not yet implement real producer adapters, canonical publication
verification, real producer projection, eligibility or selection policy,
proficiency, Grades, or reports.
