# Meridian documentation

Meridian v0.1.1 is the released executable publication-ingestion and typed-evidence
diagnostics foundation. The installable `0.1.1` package, strict typing, tests, CI,
validation tooling, immutable typed evidence inventory, exact consumer adapter
registry, bounded Core discovery and canonical verification, exact evidence
serialization, immutable projection-cache layers, and the read-only
publication/evidence diagnostics surface are established. The exact optional
ScoreForm v0.10.0, Quillan v0.9.0, and Concord v0.2.0 adapters were implemented
in the released v0.1.1 foundation,
and the cross-producer synthetic ingestion acceptance suite documents the
verified no-grading boundary.

Phase 2 now builds on that released foundation. ADR 0004 adopts the v0.2
evidence-policy, proficiency, and planning-export architecture. Issues #27
through #33 add the executable v0.2 interpretation records: immutable
Grade Item revisions, canonical digest-bound Grade Item storage,
revisioned Grade Item membership with exact Core Academic Period assignment,
canonical evidence-eligibility decision history over exact authorized projection
sources, explicit versioned attempt-selection policy/decisions, explicit
reassessment/replacement relationships over exact #30 selections, and
teacher-defined proficiency scales/native-value mapping profiles, explicit
standards-evidence association, and bounded aggregation inputs. Pure proficiency
calculation and planning-signal export remain later implementation work. The package version
remains `0.1.1` until the v0.2 release sequence reaches its release issue.

## Recommended reading order

1. [Root README](../README)
2. [Package and validation foundation](development/package-foundation.md)
3. [Synthetic data policy](development/synthetic-data.md)
4. [Typed evidence inventory](architecture/typed-evidence-inventory.md)
5. [Adapter interface and registry](architecture/adapter-interface-and-registry.md)
6. [Catalog discovery and canonical verification](architecture/catalog-discovery-and-canonical-verification.md)
7. [Exact projection snapshots and cache](architecture/exact-projection-snapshots-and-cache.md)
8. [Evidence inventory and diagnostics](architecture/evidence-inventory-and-diagnostics.md)
9. [Grade Items and canonical storage](architecture/grade-items-and-canonical-storage.md)
10. [Grade Item membership and Academic Period assignment](architecture/grade-item-membership-and-academic-period-assignment.md)
11. [Evidence eligibility decisions](architecture/evidence-eligibility-decisions.md)
12. [Attempt-selection policy and decisions](architecture/attempt-selection-policy-and-decisions.md)
13. [Reassessment and replacement relationships](architecture/reassessment-and-replacement-relationships.md)
14. [Proficiency scales and native-value mapping profiles](architecture/proficiency-scales-and-native-value-mapping-profiles.md)
15. [Standards-evidence association and aggregation inputs](architecture/standards-evidence-association-and-aggregation-inputs.md)
16. [Core v0.6 publication-ingestion architecture](architecture/core-v0.6-publication-ingestion.md)
17. [ScoreForm v0.10.0 adapter](architecture/scoreform-adapter.md)
18. [Quillan v0.10.0 adapter](architecture/quillan-adapter.md)
19. [Concord v0.2.0 adapter](architecture/concord-adapter.md)
20. [Cross-producer synthetic ingestion acceptance](architecture/cross-producer-synthetic-ingestion.md)
21. [v0.1.1 foundation release audit](development/v0.1.1-release-audit.md)
22. [ADR index](decisions/README.md)
23. [ADR 0001](decisions/0001-policy-driven-standards-proficiency-and-grade-calculation.md)
24. [ADR 0002](decisions/0002-provenance-bound-report-snapshots-and-subscriptions.md)
25. [ADR 0003](decisions/0003-consumer-side-producer-adapters.md)
26. [ADR 0004](decisions/0004-v02-evidence-policy-proficiency-and-planning-export-architecture.md)

## Development foundation

The package foundation provides:

- Python `>=3.11` support;
- `pds-core>=0.6.3,<0.7` as the only unconditional runtime dependency;
- exact optional `scoreform==0.10.0` adapter support;
- exact optional `quillan==0.10.0` adapter support;
- exact optional `pds-concord==0.2.0` adapter support;
- exact authentication of the official Core v0.6.3 wheel in baseline CI;
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

Issue #33 raises the supported Core floor to `pds-core>=0.6.3,<0.7` so current
standards-framework metadata and durable standard resolution are available.

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

## Grade Items and canonical storage

`meridian.grade_items` defines the first executable v0.2 academic-interpretation
record family. A Grade Item has a stable `grade_item_id` and immutable integer
revisions. Title, purpose, lifecycle status, and reserved future weighting
metadata belong to an exact revision. Weighting is stored with exact `Decimal`
semantics and is not executed as conventional or hybrid Grade policy.

`meridian.grade_item_storage` persists Grade Item revisions beneath the existing
Core class's Meridian module directory. Historical revisions use canonical JSON
and SHA-256 sidecars. `current.json` is a separate identity-and-digest pointer;
creating a newer revision never silently selects it. Selection uses explicit
compare-and-swap semantics and may deliberately select an older valid revision.

A reusable `GradeItemWorkReference` identifies a Core `ModuleWorkRef` plus exact
Academic Work Registration revision. It is intentionally not embedded as a
membership collection on `GradeItemRevision`. Issue #28 now implements the
separate Grade Item membership and Academic Period assignment family, preserving
the boundary:

```text
Grade Item creation != membership
membership != evidence eligibility
```

See
[Grade Items and canonical storage](architecture/grade-items-and-canonical-storage.md)
for the complete Grade Item model, storage, integrity, path-safety, and privacy
boundary.

## Grade Item membership and Academic Period assignment

`meridian.grade_item_memberships` defines explicit immutable membership decisions
between one Grade Item and one exact Core-registered work. A decision is
`included` or `excluded`; no decision remains distinct from explicit exclusion.
Included decisions bind an exact Core `AcademicPeriodRef` plus immutable Academic
Period Calendar revision rather than inferring period meaning from dates or the
currently active calendar.

`meridian.grade_item_membership_storage` persists contiguous SHA-256-bound
membership history beneath the Grade Item's `memberships/` subtree and uses a
separate `current.json` pointer with compare-and-swap selection. Exact Grade Item,
Academic Work Registration, class school-year, and Academic Period dependencies
are validated through Core before a decision is selected. Publication availability
does not create membership, and period hierarchy does not propagate membership.

The runtime boundary remains:

```text
Grade Item creation != membership
membership != evidence eligibility
```

See
[Grade Item membership and Academic Period assignment](architecture/grade-item-membership-and-academic-period-assignment.md)
for the exact decision, provenance, storage, and conflict contracts.

## Evidence eligibility decisions

`meridian.evidence_eligibility` defines canonical v0.2 eligibility history over
one exact `EvidenceSourceReference`: Core work/publication identity plus projection
`cache_key`, snapshot digest, and evidence `item_id`. The older immutable
`EvidenceItem.eligibility` value remains projection annotation and is never
rewritten or automatically migrated.

`meridian.evidence_eligibility_storage` persists SHA-256-bound revisions beneath
one #28 membership relationship. `included`, `excluded`, `pending`, and
`unsupported` remain academic interpretation states while `superseded` and
`withdrawn` preserve Core source lifecycle without masquerading as teacher
exclusions. Selection is explicit/CAS-protected and current-use resolution
revalidates the exact included membership, authorized snapshot, and Core source
lifecycle.

The boundary is:

```text
projection != canonical eligibility decision
membership != evidence eligibility
eligibility != attempt selection
```

See [Evidence eligibility decisions](architecture/evidence-eligibility-decisions.md).

## Attempt-selection policy and decisions

`meridian.attempt_selection` defines producer-neutral exact attempt observation
identity, candidate eligibility provenance, immutable explicit-selection policy
revisions, and immutable student selection decisions. Current ScoreForm
`multiple_attempts` evidence is applicable when its projected target/native
attempt identity is safe; current Quillan and Concord projections are explicitly
`not_applicable` rather than wrapped in fabricated attempts.

`meridian.attempt_selection_storage` persists SHA-256-bound policy and decision
history beneath the #28 membership relationship. Policy and student decision
`current.json` selectors are separate CAS-protected state. Candidate derivation
uses only #29 evidence with `operative_included == true`, and current-use
resolution reports stale membership, policy, eligibility, or candidate state
without changing historical decisions.

The boundary is:

```text
eligibility != attempt selection
attempt selection != reassessment
```

See [Attempt-selection policy and decisions](architecture/attempt-selection-policy-and-decisions.md).

## Reassessment and replacement relationships

`meridian.reassessment` defines immutable explicit reassessment policy revisions,
exact #30 decision references, directed replacement relationships, semantic
combination groups, explicit recency order, and immutable student relationship
decisions. Current ScoreForm multi-attempt selections are the first-class v1 use
case; current Quillan and Concord correction/supersession histories remain
producer-native and therefore #31 `not_applicable`.

`meridian.reassessment_storage` persists SHA-256-bound policy and decision history
beneath `attempt_selection/reassessment/`. Zero selected attempts and one selected
attempt are resolver pass-through states. Two or more selected attempts require an
explicit #31 decision before reassessment is operative. Current-use resolution
reuses #30 authorization/state and reports stale #30 selection or #31 policy
without rewriting history.

The boundary is:

```text
attempt selection != reassessment
reassessment != native-value mapping
```

See [Reassessment and replacement relationships](architecture/reassessment-and-replacement-relationships.md).

## Proficiency scales and native-value mapping profiles

`meridian.proficiency_mapping` defines immutable teacher-authored proficiency-scale
revisions, exact source-semantic signatures, explicit scalar/native-scale/raw-point
mapping profiles, and typed `mapped`, `unmapped`, `unsupported`, and `native_state`
outcomes. Four-level scales are first-class but not universal; level positions are
ordinal policy rather than values safe for arithmetic.

`meridian.proficiency_mapping_storage` persists class-local SHA-256-bound scale and
profile histories with separate compare-and-swap `current.json` selectors. Mapping
profiles bind exact target scale revisions and exact producer-native scale/point
semantics. Raw-point profiles bind the denominator directly; no percentage or ratio
normalization is introduced.

The boundary is:

```text
reassessment != native-value mapping
native-value mapping != standards evidence association
```

See [Proficiency scales and native-value mapping profiles](architecture/proficiency-scales-and-native-value-mapping-profiles.md).

## Adapter interface and registry

`meridian.adapters` defines exact keys, immutable descriptors and projection
requests, an explicit deterministic registry, lazy distribution-version checks,
and fail-closed invocation validation. Registry construction and selection do
not discover entry points, import producer packages, open files, or authorize
student-record access.

The registry has real optional ScoreForm v0.10.0, Quillan v0.10.0, and
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
ScoreForm, Quillan, or Concord composition populates the evidence inventory.

ADR 0004 adds the governing architecture for the interpretation layer. Valid typed
evidence does not automatically become Grade Item membership, eligible standards
evidence, a selected attempt, proficiency, or a grouping signal. Issues #27
through #33 now implement Grade Item definition/storage, explicit work membership
and Academic Period assignment, canonical eligibility decisions over exact
projection sources, explicit attempt-selection policy/decisions, explicit
reassessment/replacement relationships, and teacher-defined proficiency
scales/native-value mappings, standards-evidence association, and bounded
aggregation inputs. Calculation and export remain explicit later work.

## Architecture decisions

Four accepted ADRs govern the repository:

- ADR 0001 assigns policy-driven proficiency and Grade calculation to Meridian.
- ADR 0002 adopts provenance-bound report snapshots and subscriptions.
- ADR 0003 adopts consumer-side producer adapters and one-way dependencies.
- ADR 0004 adopts the v0.2 evidence-policy, proficiency, and planning-export
  architecture, including immutable revision history, pure deterministic
  proficiency calculation, and the Meridian -> Core -> optional Concord
  planning boundary.

ADR 0004 specializes ADRs 0001 and 0003; it does not supersede either one. The
Core v0.6 reconciliation amendments remain part of the accepted context for
ADRs 0001 and 0002.

## Implementation sequence

The v0.1.1 foundation is complete and released:

1. architecture reconciliation — complete;
2. package, testing, typing, and CI foundation — complete;
3. typed evidence inventory — complete;
4. adapter interface and registry — complete;
5. Core discovery and canonical verification — complete;
6. ScoreForm adapter — complete;
7. Quillan adapter — complete;
8. inventory and diagnostics commands — complete;
9. exact cache and snapshot rules — complete;
10. Concord adapter — complete;
11. cross-producer scenarios — complete; and
12. foundation audit and v0.1.1 release — complete.

The v0.2.0 implementation sequence now begins:

1. evidence-policy, proficiency, and planning-export architecture — ADR 0004 — complete;
2. immutable Grade Item models and canonical storage — issue #27 — implemented;
3. Grade Item membership and Academic Period assignment — issue #28 — implemented;
4. evidence eligibility decision records — issue #29 — implemented;
5. explicit attempt selection — issue #30 — implemented;
6. reassessment and replacement relationships — issue #31 — implemented;
7. proficiency/native-value mapping — issue #32 — implemented;
8. standards evidence association and aggregation inputs — issue #33 — implemented;
9. pure standards-proficiency calculation — issue #34 — next;
10. Core grouping-signal adoption and teacher-controlled derivation/export;
11. teacher workflows, explanations, and attention summaries;
12. cross-producer and installed acceptance; and
13. the v0.2.0 policy, fairness, privacy, interoperability, and release audit.

Implementing Grade Item membership does not make evidence eligibility, attempt
selection, reassessment, proficiency, Grade calculation, or planning export
runtime capabilities.

## Exact projection snapshots and cache

`meridian.evidence_serialization` and `meridian.projection_cache` persist exact
validated inventories as immutable canonical JSON bound to Core source, adapter,
reader, purpose, scope, and authorization-policy identity. Cache access requires
fresh authorization, and current-state assessment never rewrites historical
snapshot bytes.

See [Exact projection snapshots and cache](architecture/exact-projection-snapshots-and-cache.md).
