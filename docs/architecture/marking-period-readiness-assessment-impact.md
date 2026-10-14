# Marking-Period Readiness and Assessment Impact — Issue #111 Slice 11

Slice 11 completes the two report-specific generators that remain in the
Issue #111 teacher-report suite.

## Marking-Period Readiness

The readiness report is a bounded pre-close audit. It does **not** create a new
finalization authority.

It observes:

- one live Grade row per current roster student;
- base Grade status (`calculated`, `blocked`, `insufficient`, or no selected
  Grade);
- live Grade freshness;
- active teacher override use;
- pending/unresolved conventional evidence states already present in Grade
  explanation;
- current proficiency insufficiency;
- pending eligibility, unmapped evidence, unresolved attempt selection, and
  unresolved reassessment already present in exact proficiency provenance;
- the exact current-use ReportingSnapshot selection, when one exists;
- the existing Grade/report attention summary, including stale Grade,
  publication-change, snapshot-refresh, and snapshot-selection-pending states;
- optional changes from one exact digest-bound prior ReportingSnapshot.

The overall wording is deliberately bounded:

- `No unresolved Meridian reporting blockers detected`; or
- `Review needed before external marking-period close`.

The report never claims that the official Grade is finalized, an SIS is ready,
a district has approved a Grade, or a report card has been posted.

Absence of a current-use checkpoint is surfaced but does not by itself create a
new attention category or infer that the teacher intended to export/finalize.

Live generation follows optimistic whole-report currentness discipline:

1. observe the exact live Grade report;
2. observe bounded roster display identity;
3. observe existing Grade/report attention;
4. observe current-use ReportingSnapshot selection;
5. compose the deterministic report;
6. re-observe all material live sources;
7. fail if any material source moved.

## Grade Item / Assessment Impact

Assessment Impact is descriptive and provenance-based. It answers what one
current Grade Item participates in, not what it *caused*.

The report synthesizes:

- exact current Grade Item revision and title;
- standards whose Academic Period proficiency lineage contains the Grade Item;
- exact selected proficiency results in which the Grade Item is a candidate or
  contributing Grade Item;
- exact predecessor/successor result revisions where the Grade Item entered the
  proficiency basis;
- conventional Grade Item policy action, source state, weight/category, and
  numeric contribution when exposed by the current conventional result;
- the conventional component of a hybrid Grade;
- standards participation inside standards-based and hybrid Grade explanations;
- exact eligibility/excluded/pending/unmapped facts exposed by nested
  proficiency provenance;
- optional checkpoint Grade basis changes while the Grade Item participates.

Checkpoint wording is intentionally non-causal. For example:

> Material Grade basis changed while this Grade Item participates; concurrent
> inputs may also have changed.

The report does not say that an assignment caused a Grade to increase or
decrease.

Assessment Impact revalidates:

- the selected Grade Item revision;
- the live Grade report digest;
- the bounded roster display observation; and
- all inspected Academic Period proficiency histories and current selectors.

Any material movement fails closed with a stable currentness error.

## CLI and menu surface

Slice 11 adds technical direct commands:

```text
meridian reports readiness <BUILD_REQUEST>
meridian reports impact <GRADE_ITEM_ID> <BUILD_REQUEST>
```

Both accept exact optional prior ReportingSnapshot identity and the same
authorization-gated projection inputs required by ReportingSnapshot live
preview. Guided teacher selectors remain Slice 12 work.

All eight report families are now report-generator complete. Slice 12 hardens
the teacher menu/CLI workflow rather than adding another report semantic model.

## Authority boundary

Meridian reports explain teacher-controlled Meridian state. They do not become
official SIS/LMS records and do not write to external systems.
