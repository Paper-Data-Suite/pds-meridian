# Meridian documentation

Meridian is in the v0.1.1 executable publication-ingestion foundation
milestone. The installable `0.1.1` package, strict typing, tests, CI,
validation tooling, immutable typed evidence inventory, exact consumer adapter
registry, bounded Core discovery and canonical-verification preparation, exact
evidence serialization, immutable projection-cache layers, and the read-only
publication/evidence diagnostics surface are established. The exact optional
ScoreForm v0.10.0, Quillan v0.9.0, and Concord v0.2.0 adapters are implemented.
The cross-producer synthetic ingestion acceptance suite is also implemented and
documents the verified no-grading boundary. Additional producer adapters,
grading, and reporting remain follow-on work.

## Recommended reading order

1. [Root README](../README)
2. [Package and validation foundation](development/package-foundation.md)
3. [Synthetic data policy](development/synthetic-data.md)
4. [Typed evidence inventory](architecture/typed-evidence-inventory.md)
5. [Adapter interface and registry](architecture/adapter-interface-and-registry.md)
6. [Catalog discovery and canonical verification](architecture/catalog-discovery-and-canonical-verification.md)
7. [Exact projection snapshots and cache](architecture/exact-projection-snapshots-and-cache.md)
8. [Evidence inventory and diagnostics](architecture/evidence-inventory-and-diagnostics.md)
9. [Core v0.6 publication-ingestion architecture](architecture/core-v0.6-publication-ingestion.md)
10. [ScoreForm v0.10.0 adapter](architecture/scoreform-adapter.md)
11. [Quillan v0.9.0 adapter](architecture/quillan-adapter.md)
12. [Concord v0.2.0 adapter](architecture/concord-adapter.md)
13. [Cross-producer synthetic ingestion acceptance](architecture/cross-producer-synthetic-ingestion.md)
14. [v0.1.1 foundation release audit](development/v0.1.1-release-audit.md)
15. [ADR index](decisions/README.md)
16. [ADR 0001](decisions/0001-policy-driven-standards-proficiency-and-grade-calculation.md)
17. [ADR 0002](decisions/0002-provenance-bound-report-snapshots-and-subscriptions.md)
18. [ADR 0003](decisions/0003-consumer-side-producer-adapters.md)

## Development foundation

The package foundation provides:

- Python `>=3.11` support;
- `pds-core>=0.6,<0.7` as the only unconditional runtime dependency;
- exact optional `scoreform==0.10.0` adapter support;
- exact optional `quillan==0.9.0` adapter support;
- exact optional `pds-concord==0.2.0` adapter support;
- exact authentication of the official Core v0.6.0 wheel in baseline CI;
- a side-effect-free `meridian` help/version CLI;
- strict mypy and Ruff checks;
- privacy-safe fixtures and tests;
- wheel and source-distribution checks;
- isolated installed-wheel smoke testing; and
- Ubuntu/Windows CI for Python 3.11 through 3.14.

The package deliberately declares no PDS2 routing profile, publication producer
profile, unconditional producer dependency, or adapter plugin group. ScoreForm,
Quillan, and Concord are exact optional dependencies with explicit adapter
composition.

## Typed evidence inventory

`meridian.evidence` defines frozen, slotted, producer-neutral models for exact
Core provenance, projection identity, privacy-minimal student subjects,
producer-native targets and values, non-score states, eligibility status, and
ordered inventories with pure filters.

The inventory does not normalize producer values into one score. It does not
select attempts, evaluate eligibility policy, map native scales, calculate
proficiency, calculate Grades, or select attempts.

See
[Typed evidence inventory](architecture/typed-evidence-inventory.md)
for the model boundary and synthetic examples.

## Adapter interface and registry

`meridian.adapters` defines exact keys, immutable descriptors and projection
requests, an explicit deterministic registry, lazy distribution-version checks,
and fail-closed invocation validation. Registry construction and selection do
not discover entry points, import producer packages, open files, or authorize
student-record access.

The registry has real optional ScoreForm v0.10.0, Quillan v0.9.0, and
Concord v0.2.0 adapters. Other producer projections remain later work.

See
[Adapter interface and registry](architecture/adapter-interface-and-registry.md)
for the exact-match, no-fallback, reader, projection, error, and security
contracts.

## Catalog discovery and canonical verification

`meridian.ingestion` requires finite Core catalog queries, retains typed catalog
rows only as candidate observations, and reloads exact canonical publication,
registration, series, and withdrawal state. It fails closed on deterministic
candidate drift.

The layer delegates compatibility to Core, selects the exact Meridian adapter,
checks reader readiness without producer import, and requires explicit
deployment authorization before Core manifest verification or byte access. It
then reads bounded immutable bytes, builds `AdapterProjectionRequest`, and
rechecks canonical state before returning `PreparedPublicationInvocation`.

The production service does not invoke an adapter or decode producer data.

See
[Catalog discovery and canonical verification](architecture/catalog-discovery-and-canonical-verification.md)
for the executable sequence and failure taxonomy.

## Evidence inventory and diagnostics

`meridian.diagnostics` exposes bounded publication metadata diagnostics and
freshly authorized inspection of existing immutable projection snapshots.
Publication metadata does not require student-manifest authorization and never
opens producer manifests. Persisted evidence access delegates to the existing
`read_projection_cache` authorization boundary before cache-file access.

Source/current-use cache state and `EvidenceEligibility` remain separate.
Diagnostics explain existing state but do not create eligibility, selection,
proficiency, Grade, or report policy.

See
[Evidence inventory and diagnostics](architecture/evidence-inventory-and-diagnostics.md).

## Active architecture

The active ingestion architecture requires bounded catalog discovery followed by
canonical reload, drift detection, compatibility evaluation, exact adapter
selection, authorization, exact manifest verification, producer-owned parsing,
and Meridian-owned evidence projection.

The package implements every preparation stage through a coherent hidden-byte
`AdapterProjectionRequest` and `PreparedPublicationInvocation`; explicit
ScoreForm, Quillan, or Concord composition now populates the evidence inventory.

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
5. Core discovery and canonical verification — implemented;
6. ScoreForm adapter — implemented;
7. Quillan adapter — implemented;
8. inventory and diagnostics commands — implemented;
9. exact cache and snapshot rules — implemented;
10. Concord adapter — implemented;
11. cross-producer scenarios — implemented;
12. foundation audit — release candidate prepared; final validation pending.

No complete Grade or proficiency engine is part of this milestone.

## Exact projection snapshots and cache

`meridian.evidence_serialization` and `meridian.projection_cache` persist exact
validated inventories as immutable canonical JSON bound to Core source, adapter,
reader, purpose, scope, and authorization-policy identity. Cache access requires
fresh authorization, and current-state assessment never rewrites historical
snapshot bytes.

See [Exact projection snapshots and cache](architecture/exact-projection-snapshots-and-cache.md).
