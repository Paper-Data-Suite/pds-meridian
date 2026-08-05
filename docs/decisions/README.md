# Meridian Architecture Decision Records

## Accepted decisions

### ADR 0001

[Policy-Driven Standards Proficiency and Grade Calculation](0001-policy-driven-standards-proficiency-and-grade-calculation.md)

Meridian owns explicit, versioned evidence-selection, proficiency, Grade, and
override policy while Core and producers retain their separate authority.

Core v0.6 ingestion terminology and exact provenance are reconciled by the
[accepted amendment](amendments/0001-core-v0.6-ingestion-reconciliation.md).

### ADR 0002

[Provenance-Bound Report Snapshots and Subscriptions](0002-provenance-bound-report-snapshots-and-subscriptions.md)

Issued reports are immutable, provenance-bound snapshots distinct from
refreshable views, rendering, subscriptions, and delivery attempts.

Core v0.6 source binding and refresh verification are reconciled by the
[accepted amendment](amendments/0002-core-v0.6-ingestion-reconciliation.md).

### ADR 0003

[Adopt Consumer-Side Producer Adapters for Core Publications](0003-consumer-side-producer-adapters.md)

Meridian selects consumer-side adapters by exact contracts and invokes
producer-owned public readers. Core profiles remain metadata-only, and producer
packages do not depend on Meridian.

## Decision relationship

ADR 0003 supplements ADRs 0001 and 0002. It does not move producer-native
validation into Meridian or grading policy into Core.

The accepted amendment documents record narrow Core v0.6 terminology and
provenance clarification without replacing the original decisions.

## Status vocabulary

- **Proposed**: under review and not yet governing implementation.
- **Accepted**: governs later contracts and implementation unless superseded.
- **Superseded**: replaced by an explicit later decision.
- **Rejected**: considered but not adopted.

Accepted ADRs describe decisions, not proof of implementation completeness.
