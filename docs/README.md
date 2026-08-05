# Meridian documentation

Meridian is in its architecture and publication-ingestion foundation phase.
These documents define responsibility, dependency direction, source authority,
and provenance requirements before executable ingestion and grading work begins.

## Active architecture

- [Core v0.6 publication-ingestion architecture](architecture/core-v0.6-publication-ingestion.md)
  defines candidate discovery, canonical verification, authorization, producer
  compatibility, consumer adapters, native evidence projection, diagnostics,
  and exact provenance binding.

## Architecture Decision Records

- [ADR index](decisions/README.md)
- [ADR 0001: Policy-Driven Standards Proficiency and Grade Calculation](decisions/0001-policy-driven-standards-proficiency-and-grade-calculation.md)
- [ADR 0002: Provenance-Bound Report Snapshots and Subscriptions](decisions/0002-provenance-bound-report-snapshots-and-subscriptions.md)
- [ADR 0003: Adopt Consumer-Side Producer Adapters for Core Publications](decisions/0003-consumer-side-producer-adapters.md)

The accepted Core v0.6 reconciliation amendments are:

- [ADR 0001 amendment](decisions/amendments/0001-core-v0.6-ingestion-reconciliation.md)
- [ADR 0002 amendment](decisions/amendments/0002-core-v0.6-ingestion-reconciliation.md)

## Document authority

When documents disagree:

1. an accepted, later ADR governs the decision it explicitly addresses;
2. an accepted amendment governs the narrow reconciliation it records;
3. active architecture documents consolidate accepted decisions and current
   external contracts;
4. implementation documentation describes behavior that actually exists; and
5. issue descriptions guide work but are not runtime contracts.

A document describing a planned ScoreForm, Quillan, Concord, or Portia feature
must not be treated as proof that the producer contract, profile, reader, or
publication workflow exists on the producer's default branch.

## External authoritative references

Meridian depends on public contracts owned by sibling repositories. The active
starting points are:

- [Core v0.6 academic registry integration guide](https://github.com/Paper-Data-Suite/pds-core/blob/main/docs/academic_registry_integration.md)
- [Core v0.6 recovery guide](https://github.com/Paper-Data-Suite/pds-core/blob/main/docs/academic_registry_recovery.md)
- [Core v0.6 release notes](https://github.com/Paper-Data-Suite/pds-core/blob/main/docs/releases/v0.6.0.md)
- [ScoreForm Academic Result Manifest v1](https://github.com/Paper-Data-Suite/pds-scoreform/blob/main/docs/academic_result_manifest_v1.md)
- [ScoreForm publication revision policy](https://github.com/Paper-Data-Suite/pds-scoreform/blob/main/docs/publication_revision_policy.md)
- [Quillan assignment contract](https://github.com/Paper-Data-Suite/pds-quillan/blob/main/docs/assignment_contract.md)
- [Quillan review record contract](https://github.com/Paper-Data-Suite/pds-quillan/blob/main/docs/review_record_contract.md)
- [Quillan v0.9.0 publication umbrella](https://github.com/Paper-Data-Suite/pds-quillan/issues/355)

External links identify authority; they do not vendor or freeze sibling
contracts. Meridian adapters must declare exact supported versions.
