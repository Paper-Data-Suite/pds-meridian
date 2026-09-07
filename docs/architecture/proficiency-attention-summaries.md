# Proficiency attention summaries

## Status

Meridian issue #43 implements deterministic, read-only, privacy-minimal
proficiency attention over current authoritative Core/Meridian state.

It answers:

```text
What Meridian work currently needs my attention?
```

Issue #41 remains the task/action layer. Issue #42 remains the exact
historical/current explanation layer. Issue #43 is the current-state cross-task
summary layer. The next v0.2 boundary is issue #44:
ScoreForm/Quillan/Concord cross-producer proficiency scenarios.

## Architecture

The implemented direction is:

```text
current Core/Meridian canonical state
        |
        v
Meridian attention projection
        |
        +------------------+
        |                  |
        v                  v
native Meridian CLI   Core v1 adapter
                           |
                           v
                ModuleAttentionReport
```

The Meridian-native model is primary. Core's shared `ModuleAttentionReport` is
a bounded adapter result rather than Meridian's domain model.

Runtime modules are:

```text
meridian.proficiency_attention
meridian.planning_attention
meridian.academic_period_attention
meridian.attention_service
meridian.attention_provider
meridian.pds_operations
```

## Core module-operations profile

Meridian registers exactly one entry point under:

```text
paper_data_suite.module_operations
```

with:

```text
meridian = meridian.pds_operations:get_module_operations_profile
```

The profile declares Core operations contract version `1`, exposes attention,
and leaves readiness absent. Issue #43 does not invent Meridian readiness.

## Stable task routing and ordering

Attention routes only to the seven issue #41 task identities:

```text
new-evidence
grade-items
attempt-decisions
exclusions
standards-review
calculation-preview
create-planning-signal
```

Ordering is deterministic navigation/presentation policy only. It is not
urgency, severity, risk, educational importance, student ranking, or
cross-module ranking.

## Stable attention catalog

Meridian owns these stable machine codes:

```text
meridian_evidence_review_pending
meridian_membership_review_pending
meridian_attempt_decision_pending
meridian_contract_unsupported
meridian_source_withdrawn
meridian_source_superseded
meridian_native_value_unmapped
meridian_grade_item_calculation_stale
meridian_academic_period_calculation_stale
meridian_planning_review_pending
meridian_planning_review_selection_pending
meridian_planning_review_stale
```

There is deliberately no `meridian_export_pending`: export eligibility is not an
export request.

The catalog defines vocabulary, count units, #41 task routing, and owner-action
identities. An evaluation emits a category only when current canonical state can
safely prove it applies.

## Observable absence is not attention

The fundamental rule is:

```text
mechanically observable absence != teacher action required
```

Therefore no Grade Item membership, no attempt decision, no mapping profile, no
current proficiency result, no #38 derivation, no #39 preview, or no Core
signal is not automatically an attention item.

## Planning attention

Planning attention reuses canonical #38/#39 currentness and review semantics.
Representative states are:

```text
current derivation + no review
    -> meridian_planning_review_pending

current derivation + review history + no selected review
    -> meridian_planning_review_selection_pending

stale selected review
    -> meridian_planning_review_stale
```

Historical unresolved previews alone do not create current attention. Missing
planning state is not itself attention, and lack of export is never an attention
category.

## Academic Period calculation attention

Issue #43 can safely assess selected #35 Academic Period proficiency currentness
because the result persists exact bounded dependencies. A selected result may
be stale when its recorded algorithm, calendar, policy, proficiency scale,
Grade Item basis, membership basis, or recorded #34 result reference changes.

Missing #35 result is not stale, and historical unselected results are not
attention. The category routes to Calculation Preview as:

```text
meridian_academic_period_calculation_stale
```

## Protected-evidence authorization boundary

This boundary is mandatory.

Core v1 `ModuleOperationsRequest` carries only workspace root, active school
year, and class ID. It does not carry Meridian's deployment-provided protected
evidence authorization capability.

The neutral provider therefore never opens protected evidence merely to make an
attention dashboard appear exhaustive. Authorization-bound paths such as
current attempt applicability, native-value mapping over protected evidence, and
#34 Grade Item freshness reconstruction remain behind the existing
`AuthorizedProjectionSnapshot` boundary.

Where privacy-minimal canonical state safely proves a category, Meridian may
emit it. Where the required detailed inference crosses protected evidence, the
truthful v1 behavior is to emit only a broader safe fact if one is actually
proved, mark an independently failing scope partial/unavailable when
appropriate, or omit the unsupported detailed inference.

Possession of a cache key, digest, item ID, publication path, or student ID is
not authorization. Drill-down returns to the existing #41 workflow and its
normal authorization boundary.

## Grade Item freshness boundary

#34 Grade Item proficiency freshness requires rebuilding the exact current
aggregation input set. That reconstruction depends on authorization-bound
current candidate bindings and therefore cannot be performed by the neutral
Core request merely to populate `meridian_grade_item_calculation_stale`.

The stable code remains Meridian vocabulary for contexts that can legitimately
establish #34 freshness. The neutral installed provider emits only what its
request can safely prove.

## Current-state and integrity semantics

Current comes from canonical selectors and currentness/freshness services, never
highest revision, newest timestamp, filesystem mtime, lexical filename order,
or directory order.

Malformed canonical JSON, digest mismatch, impossible provenance, corrupt
pointer state, or unsafe path state remain integrity/operational failures rather
than teacher-attention categories.

A scope that cannot be inspected safely is unavailable. Workspace-wide
evaluation may be partial when independent class failures coexist with
successful classes. Successful empty evaluation remains distinct from
unavailable evaluation.

## Workspace and class scope

Native evaluation supports workspace scope, optional active school year, and
optional exact class. Exact-class requests never fall back to another class.
Workspace evaluation discovers valid classes deterministically and merges equal
codes by their documented count unit without inventing an arbitrary class
identity. School year is never inferred from today's date.

## Core-facing privacy

The Core adapter emits only bounded v1 fields: code, label, optional count,
optional class/work context, and owner action. It does not expose student names
or IDs, scores, percentages, proficiency values, grouping bands, raw evidence,
rationale bodies, rosters, digests, paths, or credentials.

Low proficiency is never translated into attention severity or risk.

## Native CLI

Meridian exposes:

```text
meridian attention --workspace PATH
                   [--school-year YYYY-YYYY]
                   [--class-id CLASS_ID]
                   [--format text|json]
```

Text and JSON use deterministic task/category ordering. Unreadable scope fails
closed with a bounded safe message. CLI evaluation performs no writes.

## Producer neutrality and Concord boundary

Generic attention runtime does not import ScoreForm, Quillan, Concord, Portia,
Vitrine, or the Paper Data Suite shell. It does not inspect Concord GroupPlans,
Groups, or GroupMembership and does not expose grouping-signal band values.

## Installed qualification

The focused issue #43 smoke installs only exact `pds-core 0.6.3` and the
candidate `pds-meridian 0.1.1` wheel with `--no-deps`, outside the source
checkout. It proves `pip check`, Core provider discovery/validation, attention
present, readiness absent, exact-class filtering, successful empty versus
unavailable, privacy-minimal output, deterministic native text/JSON,
producer/Concord absence, and no provider/CLI workspace mutation.

## Issue boundaries

```text
#41 teacher eligibility, proficiency, and planning-export workflows — implemented
#42 proficiency and planning-export explanation/trace views — implemented
#43 Meridian proficiency attention summaries — implemented
#44 ScoreForm/Quillan/Concord cross-producer proficiency scenarios — implemented
#45 installed proficiency and signal-export acceptance without Concord — next
#46 final v0.2.0 audit
```

Issue #45 owns the later full installed proficiency/signal-export acceptance
without Concord. Issue #46 owns the final v0.2.0 policy, fairness, privacy,
interoperability, and release audit.
