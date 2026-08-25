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

### ADR 0004

[Adopt v0.2 Evidence Policy, Proficiency, and Planning Export Architecture](0004-v02-evidence-policy-proficiency-and-planning-export-architecture.md)

Meridian v0.2 adds an explicit academic interpretation layer over typed producer
evidence. Stable identities, immutable revisions, explicit decisions, pure
proficiency calculation, reproducible history, and teacher-confirmed planning
derivation remain Meridian-owned. Core owns the neutral
`grouping_signal_set_v1` interchange, while Concord owns Group planning and
application.

## Decision relationship

ADR 0003 supplements ADRs 0001 and 0002 by freezing the consumer-side producer
handoff. ADR 0004 specializes ADRs 0001 and 0003 for the v0.2 evidence-policy,
proficiency, and planning-export implementation sequence.

ADR 0004 does not supersede ADR 0001's broader assignment of policy-driven
proficiency and Grade authority to Meridian, nor ADR 0003's one-way producer
adapter boundary. It narrows the v0.2 implementation to proficiency and planning
export while deferring conventional/hybrid Grade preview and result overrides to
later work.

The accepted amendment documents record narrow Core v0.6 terminology and
provenance clarification without replacing the original decisions.

## Status vocabulary

- **Proposed**: under review and not yet governing implementation.
- **Accepted**: governs later contracts and implementation unless superseded.
- **Superseded**: replaced by an explicit later decision.
- **Rejected**: considered but not adopted.

Accepted ADRs describe decisions, not proof of implementation completeness.
