# Meridian documentation

Meridian is in the v0.1.1 executable publication-ingestion foundation milestone.
The installable `0.1.1.dev0` package, strict typing, tests, CI, and validation
tooling are established. Evidence models, adapters, canonical ingestion,
grading, and reporting remain follow-on work.

## Recommended reading order

1. [Root README](../README)
2. [Package and validation foundation](development/package-foundation.md)
3. [Synthetic data policy](development/synthetic-data.md)
4. [Core v0.6 publication-ingestion architecture](architecture/core-v0.6-publication-ingestion.md)
5. [ADR index](decisions/README.md)
6. [ADR 0001](decisions/0001-policy-driven-standards-proficiency-and-grade-calculation.md)
7. [ADR 0002](decisions/0002-provenance-bound-report-snapshots-and-subscriptions.md)
8. [ADR 0003](decisions/0003-consumer-side-producer-adapters.md)

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

## Active architecture

The active ingestion architecture requires catalog candidate discovery followed
by canonical reload, compatibility evaluation, authorization, exact manifest
verification, producer-owned parsing, and Meridian-owned evidence projection.

The package foundation does not yet implement those stages.

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
2. package, testing, typing, and CI foundation — active;
3. typed evidence inventory;
4. adapter interface and registry;
5. Core discovery and canonical verification;
6. ScoreForm adapter;
7. Quillan adapter;
8. inventory and diagnostics commands;
9. exact cache and snapshot rules;
10. cross-producer scenarios;
11. foundation audit and release.

No complete Grade or proficiency engine is part of this milestone.
