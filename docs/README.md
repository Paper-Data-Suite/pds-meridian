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
verified no-grading boundary. Current unreleased v0.2 development now
qualifies ScoreForm v0.11.0 while preserving that historical v0.1.1 fact.

Phase 2 now builds on that released foundation. ADR 0004 adopts the v0.2
evidence-policy, proficiency, and planning-export architecture. Issues #27
through #35 add the executable v0.2 interpretation records: immutable
Grade Item revisions, canonical digest-bound Grade Item storage,
revisioned Grade Item membership with exact Core Academic Period assignment,
canonical evidence-eligibility decision history over exact authorized projection
sources, explicit versioned attempt-selection policy/decisions, explicit
reassessment/replacement relationships over exact #30 selections,
teacher-defined proficiency scales/native-value mapping profiles, explicit
standards-evidence association and bounded aggregation inputs, and pure
Grade Item-level standards-proficiency policy/calculation/result persistence
with explicit selection and staleness diagnostics, plus exact Academic Period
proficiency aggregation over immutable #34 results. Issue #36 formally adopts
Core's neutral `grouping_signal_set_v1` contract against exact Core 0.6.3, and
issue #37 now adds the separate immutable teacher-controlled grouping-signal
derivation-policy layer without assigning students to bands or writing Core
signals. Issue #38 deterministic generation is the next boundary. The package
version remains `0.1.1` until the v0.2 release sequence reaches its release
issue.

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
16. [Grade Item standards-proficiency calculation](architecture/standards-proficiency-calculation.md)
17. [Academic Period standards-proficiency aggregation](architecture/academic-period-proficiency-aggregation.md)
18. [Core neutral grouping-signal interchange](architecture/core-grouping-signal-interchange.md)
19. [Teacher-controlled grouping-signal derivation policy](architecture/grouping-signal-derivation-policy.md)
20. [Core v0.6 publication-ingestion architecture](architecture/core-v0.6-publication-ingestion.md)
21. [ScoreForm adapter](architecture/scoreform-adapter.md)
22. [Quillan v0.10.0 adapter](architecture/quillan-adapter.md)
23. [Concord v0.2.0 adapter](architecture/concord-adapter.md)
24. [Cross-producer synthetic ingestion acceptance](architecture/cross-producer-synthetic-ingestion.md)
25. [v0.1.1 foundation release audit](development/v0.1.1-release-audit.md)
26. [ADR index](decisions/README.md)
27. [ADR 0001](decisions/0001-policy-driven-standards-proficiency-and-grade-calculation.md)
28. [ADR 0002](decisions/0002-provenance-bound-report-snapshots-and-subscriptions.md)
29. [ADR 0003](decisions/0003-consumer-side-producer-adapters.md)
30. [ADR 0004](decisions/0004-v02-evidence-policy-proficiency-and-planning-export-architecture.md)

## Development foundation

The package foundation provides:

- Python `>=3.11` support;
- `pds-core>=0.6.3,<0.7` as the only unconditional runtime dependency;
- exact optional `scoreform==0.11.0` adapter support;
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

## Grade Item standards-proficiency calculation

`meridian.standards_proficiency` implements the pure #34 reduction boundary over
one exact `StandardAggregationInputs` body, exact policy revision, exact target
scale revision, and algorithm version. Supported v1 strategies are `highest`,
`lowest`, `median`, and `mode`; insufficient evidence remains a structured
academic state rather than a zero or lowest-level substitution.

`meridian.standards_proficiency_storage` persists immutable policy/result
histories with SHA-256 sidecars and explicit compare-and-swap selectors.
Results embed their exact #33 inputs, and pure freshness diagnostics report
input/policy/scale/algorithm drift without mutation or automatic recalculation.

See [Grade Item standards-proficiency calculation](architecture/standards-proficiency-calculation.md).

## Academic Period standards-proficiency aggregation

`meridian.academic_period_proficiency` implements the pure #35 boundary over
exact immutable #34 Grade Item proficiency results and exact #28 membership
basis. `direct` and `descendants` scope are explicit policy choices over one
exact Core calendar revision; mixed sibling periods, calendar mismatches, and
unrelated overlapping periods remain explicit `period_scope_mismatch` states.

Missing #34 results and #34 `insufficient_evidence` results remain distinct
from an actual low proficiency level. Policy independently chooses whether
missing and insufficient entries are noncontributing or blocking, while
period-scope mismatch is always blocking in schema version 1.

`meridian.academic_period_proficiency_storage` persists immutable policy and
result histories with SHA-256 sidecars and explicit compare-and-swap current
selectors. Results embed exact #35 inputs and preserve exact #34 result
references; freshness is diagnostic only and never rewrites history.

See [Academic Period standards-proficiency aggregation](architecture/academic-period-proficiency-aggregation.md).

## Core neutral grouping-signal interchange

Issue #36 adopts Core's released `grouping_signal_set_v1` as Meridian's only
shared planning-signal interchange. The contract first shipped in Core 0.6.1,
while Meridian qualifies it against exact Core 0.6.3 and preserves the active
`pds-core>=0.6.3,<0.7` floor.

Core remains authoritative for the typed signal model, strict canonical JSON,
`grouping_signal_csv_v1`, immutable exchange storage and canonical signal
digest, and workspace-aware roster diagnostics. Meridian adds no competing
signal wire model, serializer, CSV format, storage layer, or roster matcher.

The contract boundary is:

```text
Meridian private academic derivation
    -> Core grouping_signal_set_v1
    -> optional downstream planning consumer
```

Bands remain contextual ordinal planning signals, not Grades, proficiency
labels, ability classifications, or permanent learner attributes. Partial
coverage is explicit; exact `student_id` identity is required; signal snapshots
are immutable; no `current`/`latest` pointer exists; and
`source.snapshot_digest` remains distinct from Core's canonical signal-byte
digest.

Issue #36 qualifies the contract with synthetic focused tests and an isolated
installed-wheel smoke containing Core plus Meridian with Concord absent. It does
not produce a production signal. Issue #37 now defines the separate
teacher-controlled derivation-policy layer.

See [Core neutral grouping-signal interchange](architecture/core-grouping-signal-interchange.md).

## Teacher-controlled grouping-signal derivation policy

`meridian.grouping_signal_policy` binds one exact #35 Academic Period proficiency
basis to one explicit contextual `dimension_id` and a teacher-defined contiguous
partition of exact proficiency-scale positions. V1 fixes
`same_level_same_band`, rejects percentile/equal-population derivation, never
uses the proficiency threshold as a hidden boundary, and independently preserves
missing versus insufficient results as `noncontributing` or `blocking`.

`meridian.grouping_signal_policy_storage` persists immutable SHA-256-bound policy
history in Meridian-owned class state with explicit compare-and-swap selection.
Exact Core class/Academic Period/standard and exact #35 policy/proficiency-scale
dependencies are verified before writes and selections. Policy creation and
selection do not scan students, assign bands, create Core signals, export CSV,
or invoke Concord.

See [Teacher-controlled grouping-signal derivation policy](architecture/grouping-signal-derivation-policy.md).

## Adapter interface and registry

`meridian.adapters` defines exact keys, immutable descriptors and projection
requests, an explicit deterministic registry, lazy distribution-version checks,
and fail-closed invocation validation. Registry construction and selection do
not discover entry points, import producer packages, open files, or authorize
student-record access.

The registry has real optional ScoreForm v0.11.0, Quillan v0.10.0, and
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
through #35 now implement Grade Item definition/storage, explicit work membership
and Academic Period assignment, canonical eligibility decisions over exact
projection sources, explicit attempt-selection policy/decisions, explicit
reassessment/replacement relationships, teacher-defined proficiency
scales/native-value mappings, standards-evidence association/bounded aggregation
inputs, and pure Grade Item-level standards-proficiency calculation with
immutable result persistence, explicit selection, and staleness diagnostics,
plus exact Academic Period proficiency aggregation over immutable #34 results.
Issue #36 adopts Core's neutral `grouping_signal_set_v1` contract as the
shared planning-signal boundary. Issue #37 now implements the separate
teacher-controlled grouping-signal derivation policy. Deterministic generation,
preview, and export remain explicit later work beginning with issue #38.

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
9. pure standards-proficiency calculation — issue #34 — implemented;
10. Academic Period proficiency aggregation — issue #35 — implemented;
11. Core grouping-signal adoption — issue #36 — implemented;
12. teacher-controlled grouping-signal derivation policy — issue #37 — implemented;
13. deterministic grouping-signal generation — issue #38 — next;
14. teacher workflows, explanations, and attention summaries;
15. cross-producer and installed acceptance; and
16. the v0.2.0 policy, fairness, privacy, interoperability, and release audit.

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
