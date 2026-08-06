# Meridian documentation

Meridian is in the v0.1.1 executable publication-ingestion foundation milestone.
The installable `0.1.1.dev0` package, strict typing, tests, CI, validation
tooling, and immutable typed evidence inventory are established. Producer
adapters, canonical ingestion, eligibility policy, grading, and reporting remain
follow-on work.

## Recommended reading order

1. [Root README](../README)
2. [Package and validation foundation](development/package-foundation.md)
3. [Synthetic data policy](development/synthetic-data.md)
4. [Typed evidence inventory](architecture/typed-evidence-inventory.md)
5. [Core v0.6 publication-ingestion architecture](architecture/core-v0.6-publication-ingestion.md)
6. [ADR index](decisions/README.md)
7. [ADR 0001](decisions/0001-policy-driven-standards-proficiency-and-grade-calculation.md)
8. [ADR 0002](decisions/0002-provenance-bound-report-snapshots-and-subscriptions.md)
9. [ADR 0003](decisions/0003-consumer-side-producer-adapters.md)

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

`meridian.evidence` defines frozen, slotted, producer-neutral models for:

- exact Core publication, registration, withdrawal, and manifest provenance;
- explicit adapter projection and producer-reader identity;
- privacy-minimal student subjects;
- producer-native targets and standard alignment;
- native result kinds;
- exact scalar, point, scaled, and non-score-state values;
- ordered native record, artifact, and timestamp provenance;
- explicit `unevaluated`, `eligible`, and `ineligible` status; and
- ordered inventories with pure, order-preserving filters.

The inventory does not normalize producer values into one score. It does not
select attempts, evaluate eligibility policy, map native scales, calculate
proficiency, calculate Grades, or ingest real producer manifests.

See
[Typed evidence inventory](architecture/typed-evidence-inventory.md)
for the model boundary and synthetic examples.

## Active architecture

The active ingestion architecture requires catalog candidate discovery followed
by canonical reload, compatibility evaluation, authorization, exact manifest
verification, producer-owned parsing, and Meridian-owned evidence projection.

The typed inventory now defines the projection destination. The package does not
yet implement the adapters or orchestration that populate it from real producer
public contracts.

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
4. adapter interface and registry;
5. Core discovery and canonical verification;
6. ScoreForm adapter;
7. Quillan adapter;
8. inventory and diagnostics commands;
9. exact cache and snapshot rules;
10. cross-producer scenarios;
11. foundation audit and release.

No complete Grade or proficiency engine is part of this milestone.
