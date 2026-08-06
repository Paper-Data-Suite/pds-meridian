# Meridian documentation

Meridian is in the v0.1.1 executable publication-ingestion foundation milestone.
The installable `0.1.1.dev0` package, strict typing, tests, CI, validation
tooling, immutable typed evidence inventory, and exact consumer adapter
interface and registry are established. Real producer adapters, canonical
ingestion, eligibility policy, grading, and reporting remain follow-on work.

## Recommended reading order

1. [Root README](../README)
2. [Package and validation foundation](development/package-foundation.md)
3. [Synthetic data policy](development/synthetic-data.md)
4. [Typed evidence inventory](architecture/typed-evidence-inventory.md)
5. [Adapter interface and registry](architecture/adapter-interface-and-registry.md)
6. [Core v0.6 publication-ingestion architecture](architecture/core-v0.6-publication-ingestion.md)
7. [ADR index](decisions/README.md)
8. [ADR 0001](decisions/0001-policy-driven-standards-proficiency-and-grade-calculation.md)
9. [ADR 0002](decisions/0002-provenance-bound-report-snapshots-and-subscriptions.md)
10. [ADR 0003](decisions/0003-consumer-side-producer-adapters.md)

## Development foundation

The package foundation provides:

- Python `>=3.11` support;
- `pds-core>=0.6,<0.7` as the only runtime dependency;
- exact authentication of the official Core v0.6.0 wheel in baseline CI;
- a side-effect-free `meridian` help/version CLI;
- strict mypy and Ruff checks;
- privacy-safe fixtures and tests;
- wheel and source-distribution checks;
- isolated installed-wheel smoke testing; and
- Ubuntu/Windows CI for Python 3.11 through 3.14.

The package deliberately declares no PDS2 routing profile, publication producer
profile, producer dependency, or adapter plugin group.

## Typed evidence inventory

`meridian.evidence` defines frozen, slotted, producer-neutral models for exact
Core provenance, projection identity, privacy-minimal student subjects,
producer-native targets and values, non-score states, eligibility status, and
ordered inventories with pure filters.

The inventory does not normalize producer values into one score. It does not
select attempts, evaluate eligibility policy, map native scales, calculate
proficiency, calculate Grades, or ingest real producer manifests.

See
[Typed evidence inventory](architecture/typed-evidence-inventory.md)
for the model boundary and synthetic examples.

## Adapter interface and registry

`meridian.adapters` defines exact keys, immutable descriptors and projection
requests, an explicit deterministic registry, lazy distribution-version checks,
and fail-closed invocation validation. Registry construction and selection do
not discover entry points, import producer packages, open files, or authorize
student-record access.

The foundation uses synthetic adapters only. Real ScoreForm and Quillan readers
and projections remain later work.

See
[Adapter interface and registry](architecture/adapter-interface-and-registry.md)
for the exact-match, no-fallback, reader, projection, error, and security
contracts.

## Active architecture

The active ingestion architecture requires catalog candidate discovery followed
by canonical reload, compatibility evaluation, authorization, exact manifest
verification, producer-owned parsing, and Meridian-owned evidence projection.

The typed inventory defines the projection destination and the adapter registry
defines exact selection and invocation. The package does not yet implement
canonical ingestion orchestration or real producer adapters that populate the
inventory.

## Architecture decisions

Three accepted ADRs govern the repository:

- ADR 0001 assigns policy-driven proficiency and Grade calculation to Meridian.
- ADR 0002 adopts provenance-bound report snapshots and subscriptions.
- ADR 0003 adopts consumer-side producer adapters and one-way dependencies.

The Core v0.6 reconciliation amendments remain part of the accepted context for
ADRs 0001 and 0002.

## Current implementation sequence

The v0.1.1 milestone proceeds through:

1. architecture reconciliation — complete;
2. package, testing, typing, and CI foundation — complete;
3. typed evidence inventory — implemented;
4. adapter interface and registry — implemented;
5. Core discovery and canonical verification;
6. ScoreForm adapter;
7. Quillan adapter;
8. inventory and diagnostics commands;
9. exact cache and snapshot rules;
10. cross-producer scenarios;
11. foundation audit and release.

No complete Grade or proficiency engine is part of this milestone.
