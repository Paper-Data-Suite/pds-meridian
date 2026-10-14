# Class Standards Profile and Student Proficiency Growth — Issue #111 Slice 9

Slice 9 adds two deterministic read-only teacher reports over Meridian's
existing Academic Period proficiency authority.

## Class Standards Profile

The class profile resolves the currently activated standards-based or hybrid
Grade policy only to identify the reporting-standard set, exact target
proficiency scale, and any policy-defined profile groups. It does not use the
Grade policy to manufacture proficiency.

The matrix includes every current Core-roster student unless a teacher filter is
supplied. For each reporting standard a cell is one of:

- the exact configured proficiency display label for the selected result;
- `Insufficient evidence` when that is the exact selected result state; or
- `No current judgment` when no result is selected.

`No current judgment` is absence. It is never converted to Developing, zero, or
the scale's lowest level.

Distribution rows use the actual configured proficiency levels in scale
position order and additionally count insufficient and no-current states.

Supported direct filters are:

- exact standard;
- exact student;
- exact proficiency-level ID;
- a policy-defined profile group, when one exists.

Live generation observes the active policy/activation, bounded roster display
names, and every material current result selector before generation and again
after generation. Material movement fails with a currentness conflict.

## Student Proficiency Growth / Trajectory

The trajectory report enumerates immutable Academic Period proficiency result
families and revisions directly from canonical Meridian history, including
families that currently have no selected revision.

Rows are ordered by standard and exact contiguous result revision. They show:

- result revision and calculation time;
- result calendar revision;
- exact proficiency label or insufficient state;
- upward, downward, unchanged, state-changed, or scale-changed movement;
- current-selection and supersession lineage;
- participating Grade Items;
- whether the exact input/evidence basis changed;
- exact aggregation-policy title, revision, actor, and rationale.

Up/down comparisons are made only when both revisions use the same exact
proficiency scale. A scale change is reported as `SCALE_CHANGED` rather than
forcing a cross-scale ordinal inference.

Meridian's result storage records immutable result lineage and the current
selector. It does not retain a selector-event log proving which historical
revisions were selected at every past moment. The report therefore marks the
current selected revision and does not invent past selection events.

Historical attempts are not averaged.

## Authority and privacy

Both reports:

- are derived artifacts, not new academic authority;
- read exact stored result revisions and current selectors;
- preserve durable `student_id` identity;
- use only bounded Core roster display-name observations;
- include exact digest-bound source references;
- do not reproduce raw student work;
- do not mutate Grade, proficiency, evidence, policy, snapshot, Core, producer,
  SIS, or LMS state;
- may write only through Meridian's existing safe local artifact writer.
