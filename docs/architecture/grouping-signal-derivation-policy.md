# Teacher-controlled grouping-signal derivation policy

Issue #37 defines Meridian's canonical policy boundary for turning one exact
Academic Period standards-proficiency interpretation into temporary contextual
planning bands. It does **not** derive student bands, create a Meridian
derivation snapshot, create or write a Core grouping signal, preview a class
distribution, export CSV, or perform Concord group planning.

The governing separation is:

```text
Academic Period proficiency
!=
grouping-signal policy
!=
grouping-signal derivation
!=
Core signal export
!=
GroupPlan
```

Likewise:

```text
Meridian band count != Concord target group count
```

## Ownership and handoff

The v0.2 planning path is intentionally staged:

```text
exact #35 Academic Period proficiency results
        |
        | exact academic basis
        v
selected #37 grouping-signal derivation-policy revision
        |
        | issue #38
        v
immutable Meridian derivation snapshot
        |
        | issue #39
        v
preview and diagnostics
        |
        | issue #40 explicit export
        v
Core grouping_signal_set_v1
        |
        v
optional downstream planning consumer
```

Core owns class and roster identity, Academic Period definitions, standards
identity, `grouping_signal_set_v1`, canonical signal JSON/CSV, immutable signal
exchange storage, the Core signal-record digest, and roster diagnostics.
Meridian owns academic interpretation, exact proficiency provenance, the
teacher-controlled derivation policy, later rich derivation provenance, and the
explicit decision to request, preview, and export planning signals. Concord owns
selection of an exported signal/dimension and all GroupPlan semantics, including
similar/mixed-signal strategy, target group size/count, missing-signal placement,
manual changes, approval, Group, and GroupMembership.

`meridian.grouping_signal_policy` and
`meridian.grouping_signal_policy_storage` therefore have no Concord dependency
and do not call Core grouping-signal generation or exchange-storage APIs.

## V1 academic source

The only v1 basis kind is:

```text
academic_period_proficiency
```

The immediate source is the exact persisted #35
`AcademicPeriodProficiencyResultSnapshot` state. Grouping policy does not
reconstruct proficiency from raw producer values, percentages, points,
`EvidenceItem`, attempt numbers, Grade Item raw scores, native rubric values,
question correctness, reassessment history, or another grouping signal.

This preserves the interpretation chain:

```text
producer-native evidence
    -> Meridian evidence policy
    -> Meridian proficiency
    -> Meridian grouping-signal policy
```

A direct Grade Item grouping basis or rolling/custom evidence window would be a
new explicit policy contract rather than an overloaded v1 behavior.

## Exact Academic Period is the v1 window

The v1 derivation window is the exact Core Academic Period already represented
by `AcademicPeriodProficiencyTarget`:

```text
AcademicPeriodRef
+
calendar_revision
```

No second date filter exists. In particular, v1 does not use `last N days`,
calculation timestamps, publication timestamps, Grade Item due dates, filesystem
mtime, the current date, or whichever result happened to be written most
recently. The immutable #35 result already records the Grade Item/result basis
that produced period proficiency; #37 binds that exact period context.

## Exact academic basis

`GroupingSignalAcademicBasis` binds:

```text
basis_kind
target_period
standard_id
source_policy
target_scale
```

where:

- `basis_kind` is exactly `academic_period_proficiency`;
- `target_period` is one exact `AcademicPeriodProficiencyTarget`;
- `standard_id` is the durable Core-resolved standard interpreted by #35;
- `source_policy` is one exact
  `AcademicPeriodProficiencyAggregationPolicyReference`; and
- `target_scale` is one exact `ProficiencyScaleReference`.

All references must belong to the same class. Storage verifies the Core class
metadata, exact Academic Period Calendar revision and period, current Core
standards library resolution, exact persisted #35 policy revision/digest, and
exact persisted proficiency-scale revision/digest before a new grouping policy
revision is written or explicitly selected.

The #37 record stores exact references and digests rather than copying the full
#35 policy or proficiency-scale body.

## Academic dimension identity

Meridian v0.2 uses one explicitly selected academic dimension per derivation.
The policy keeps these concepts separate:

```text
dimension_id
```

and:

```text
standard_id + Academic Period + source policy + proficiency scale
```

`dimension_id` is an explicit path-safe contextual identifier. It is not a Core
standards identifier and Meridian does not assume `dimension_id == standard_id`.
The future Core signal needs only the minimal contextual `dimension_id` and
`band_count`; the future Meridian derivation snapshot retains the richer academic
meaning.

## Proficiency scale is the ordinal source

The exact target `ProficiencyScale` defines contiguous criterion-referenced
positions:

```text
1..N
```

Grouping policy uses only that explicit order. It does not inspect underlying
points, percentages, rubric numbers, native score magnitudes, or producer result
formats to create planning bands.

The transformation boundary is:

```text
exact #35 proficiency_level_id
        |
        v
exact position on the exact scale revision
        |
        v
teacher-defined contextual band
```

A proficiency level remains a criterion-referenced academic interpretation. A
planning band is a temporary contextual ordinal projection. They are not the
same record or semantic layer.

## Teacher-defined contiguous band boundaries

`GroupingSignalBandDefinition` records:

```text
band
minimum_scale_position
maximum_scale_position
```

For a policy with `band_count = B`:

- `B >= 2`;
- `B` cannot exceed the number of levels on the exact source scale;
- band numbers are exactly `1..B`;
- scale positions are a complete contiguous partition of `1..N`;
- no position may be omitted or duplicated;
- ranges may not overlap;
- ranges may not be reversed; and
- serialized/validated band ordering is deterministic.

For a four-level scale, this is valid:

```text
band 1 -> positions 1..1
band 2 -> positions 2..3
band 3 -> positions 4..4
```

These boundaries are explicit teacher policy. Meridian does not infer them from
class rank, observed class size, or an existing proficiency threshold.

## Same-level/same-band tie rule

V1 fixes tie handling to:

```text
same_level_same_band
```

Students with the same exact source proficiency level must map to the same
contextual planning band. A later derivation must not split ties using student
ID, name, roster order, timestamp, randomization, evidence count, or another
secondary characteristic.

V1 does not implement percentile, quantile, equal-population, bottom/middle/top
third, quartile, or other class-relative banding. A student's band is therefore
not a function of classmates' proficiency values.

## No hidden proficiency-threshold boundary

`ProficiencyScale.proficiency_threshold_level_id` is academic proficiency
metadata. It is **not** automatically a grouping boundary. A teacher can choose
band boundaries that happen to align with that threshold, but the relationship
must be explicit in `band_definitions`; no threshold-derived shortcut or hidden
default exists.

## Missing and insufficient results

Absence and insufficient evidence remain distinct from low proficiency:

```text
absence != low proficiency
insufficient evidence != low proficiency
```

The policy independently controls:

```text
missing_result_handling
insufficient_result_handling
```

Each uses the closed v1 vocabulary:

```text
noncontributing
blocking
```

`noncontributing` means the later derived Core dimension receives no student band
entry for that condition. This is valid partial coverage. It does **not** mean
Band 0, Band 1, lowest proficiency, failure, absence from the class, or exclusion
from downstream planning.

`blocking` means the later class-level derivation cannot complete while an
applicable roster student remains in that condition. It does not repair, mutate,
or replace the underlying #35 result.

No hidden fallback may convert missing or insufficient state to a numeric band or
to scale position 1.

## Exact #35 result eligibility for issue #38

Issue #37 freezes the eligibility rule that #38 must execute. For one roster
student, a v1 source result must be:

1. one exact persisted #35 result revision;
2. explicitly selected through #35's result-selection boundary;
3. an exact match for class, target period, durable standard, source #35 policy,
   and target proficiency-scale references in the selected #37 policy;
4. valid under exact stored-byte/digest integrity checking;
5. current under the existing #35 freshness semantics when a new derivation is
   requested; and
6. interpreted according to its explicit outcome status.

A calculated result must carry a valid `proficiency_level_id` on the exact bound
scale before it can contribute a band. An `insufficient_evidence` result follows
`insufficient_result_handling`. Absence of an explicitly selected matching #35
result follows `missing_result_handling`.

#38 must not choose a source result by highest revision, latest timestamp, newest
file, latest Academic Period, first matching standard, or any other implicit
"latest" rule. Historical #35 results remain valid history but are not
implicitly eligible for a new derivation.

## Immutable policy identity and revision history

`GroupingSignalDerivationPolicy` is immutable, frozen, and revisioned. Its
logical identity is:

```text
class_id + policy_id
```

A normal revision transition requires:

```text
candidate.policy_revision == previous.policy_revision + 1
candidate.supersedes_revision == previous.policy_revision
candidate.revised_at >= previous.revised_at
```

Class and logical policy identity cannot change across a revision transition.
Each revision includes its title, exact academic basis, explicit `dimension_id`,
band count/boundaries, fixed tie rule, independent missing/insufficient handling,
teacher/policy actor, optional rationale, and revision timestamp.

The policy record deliberately does not contain a Core `signal_set_id`, signal
`created_at`, student-to-band assignments, Concord strategy, target group size,
target group count, Group, or GroupMembership.

## Canonical serialization, digest, and reference

Policy JSON uses Meridian's strict canonical encoding and rejects missing,
unknown, duplicate, noncanonical, or invalid fields. The SHA-256 is calculated
over the exact canonical policy bytes.

`GroupingSignalDerivationPolicyReference` binds:

```text
class_id
policy_id
policy_revision
policy_sha256
```

The future #38 derivation snapshot must bind this exact reference rather than a
bare policy ID or revision number.

## Canonical storage and explicit selection

Policy revisions are stored in Meridian-owned class/module state rather than
Core's grouping-signal exchange tree:

```text
classes/
  <class_id>/
    modules/
      meridian/
        grouping_signal_policies/
          <policy_id>/
            current.json
            revisions/
              1.json
              1.json.sha256
              2.json
              2.json.sha256
```

Revision JSON and SHA-256 sidecars are immutable. Exact replay is idempotent;
same identity with different bytes conflicts; histories must be contiguous; and
reads fail closed on malformed JSON, malformed/tampered digests, noncanonical
bytes, unsafe paths, symlinks, incomplete pairs, or unexpected visible entries.

Creating revision `N+1` does not activate it. `current.json` contains only
identity/digest data for one explicitly selected revision. Selection uses
compare-and-swap through `expected_current_policy_revision`; a stale expectation
fails. Historical reselection is allowed only when the exact policy and its
academic dependencies still validate.

Explicit policy selection is #37's teacher-confirmation boundary. There is no
separate vague `confirmed = true` flag, and selecting a policy does not generate,
preview, or export a signal.

## Contextual ordinal semantics

Planning bands are temporary contextual ordinals. They are not persisted
ability labels, disability/support labels, Grades, proficiency labels, permanent
learner traits, or recommendations about a student's worth or potential.

The same proficiency result can legitimately participate in different policy
revisions with different teacher-chosen band partitions for different planning
contexts. That flexibility is precisely why Meridian preserves the richer
academic basis and treats Core's exported band as a minimal planning signal.

## Privacy and fairness guardrails

Grouping policy stores no roster and no individual student assignments. Policy
creation and selection therefore do not require scanning student results or
writing student-level planning state.

V1 fairness constraints are structural:

- no class-relative percentile or equal-population banding;
- no tie splitting by student identity or roster position;
- no missing/insufficient-to-low fallback;
- no hidden proficiency-threshold boundary;
- no automatic grouping from behavior, protected traits, or unrelated signals;
- no Concord planning policy embedded in academic interpretation; and
- no automatic export merely because a policy was created or selected.

Teachers remain responsible for the educational purpose and appropriateness of a
particular policy and for reviewing later #39 diagnostics before #40 export.

## No academic feedback loop

A grouping signal is downstream planning data. It must not become evidence used
to calculate the proficiency that generated it. The prohibited loop is:

```text
Meridian proficiency
    -> grouping signal
    -> group placement
    -X-> evidence used to recalculate the same proficiency
```

If future workflows generate new independent academic evidence while students
work in groups, that evidence must enter Meridian through the normal producer,
registration, eligibility, association, and interpretation boundaries. Group
membership itself is not proficiency evidence.

## Read-only import boundary

Importing:

```text
meridian.grouping_signal_policy
meridian.grouping_signal_policy_storage
```

must not create directories, open a workspace, load Core state, read environment
configuration, discover Concord, write policy files, select policy revisions, or
produce grouping signals. All storage and dependency validation occurs only
through explicit function calls.

## Issue handoff

After completion of issue #38, the progression is:

```text
#35 Academic Period proficiency aggregation — implemented
#36 Core neutral grouping-signal contract — implemented
#37 teacher-controlled grouping-signal derivation policy — implemented
#38 deterministic grouping-signal generation — implemented
#39 grouping-signal preview and diagnostics — next
#40 Core/CSV export — later
```

Issue #38 now resolves exact selected/current #35 results under one explicitly
selected #37 policy and produces an immutable rich Meridian derivation snapshot.
Issue #39 owns preview and diagnostics over an actual derivation. Issue #40 owns
explicit conversion/export to Core `grouping_signal_set_v1` and optional
`grouping_signal_csv_v1` output. None of those responsibilities are pulled into
#37.
