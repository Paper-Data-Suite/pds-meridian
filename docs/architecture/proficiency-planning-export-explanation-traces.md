# Proficiency and planning-export explanation traces

## Status

Meridian issue #42 implements a deterministic, read-only explanation layer over
canonical #27-#40 academic and planning state. It answers:

```text
Why exactly did Meridian reach this result?
```

without creating a second academic truth, recalculating results, changing
selection, exporting new state, or persisting an explanation log.

The next v0.2 boundary is issue #43: Meridian proficiency attention summaries.

## Trace surfaces

The installed CLI exposes five independently invocable trace targets:

```text
meridian trace grade-item-proficiency ...
meridian trace academic-period-proficiency ...
meridian trace planning-derivation ...
meridian trace planning-preview-review ...
meridian trace planning-export ...
```

Each command supports deterministic teacher-readable text and structured JSON.
Application-layer explanation functions remain reusable outside terminal
rendering.

## Exact-target semantics

Explanation begins from an explicit canonical target. Revisioned Grade Item and
Academic Period results support either:

```text
explicit exact historical revision
```

or:

```text
explicitly requested current selected revision
```

Current means the canonical explicit current pointer. Meridian never chooses a
result by highest revision, newest timestamp, filename order, directory order,
or apparent recency.

Grouping derivations and previews are immutable content-addressed artifacts and
therefore require exact IDs. They have no inferred latest/current selector.

Export traces require exact:

```text
class_id
signal_set_id
```

The export receipt then supplies the exact historical review, preview, and
#38 derivation lineage.

## Integrity model

Every provenance edge is verified using the exact stored identity and digest
where the contract supplies one. Examples include:

```text
result_sha256
policy_sha256
scale_sha256
decision_sha256
profile_sha256
derivation_sha256
preview/review digest
Core signal digest
```

A missing exact dependency, digest mismatch, noncanonical persisted record,
impossible lineage, scope mismatch, or exported-band disagreement is an
integrity failure. It is not translated into a friendly academic status.

Historical state remains explainable from its immutable bound inputs even when
newer state is selected now.

## Grade Item proficiency trace

`meridian.grade_item_proficiency_explanation` resolves one exact #34 result and
verifies its exact #33 aggregation input body, Grade Item, calculation policy,
proficiency scale, and each applicable upstream decision.

For every exact aggregation entry, the projection preserves:

```text
source identity
result kind
target kind
performance / native_state / excluded
contributed or did not contribute
exclusion reason
mapping status
mapped proficiency level or native state
```

Applicable provenance is resolved through exact stored references for:

```text
Grade Item membership
canonical evidence eligibility
attempt selection
reassessment
Standard association
native-value mapping profile
```

Absence and nonapplicability remain distinct. For example, `not_applicable`
attempt selection is not reported as a missing attempt decision.

The calculation projection preserves exact strategy, observation counts,
per-level counts, minimum evidence requirement, tie state, structured
insufficiency reasons, and final result status. In particular:

```text
insufficient evidence != lowest proficiency
missing evidence != zero
native non-score state != zero
excluded evidence != zero
```

## Academic Period proficiency trace

`meridian.academic_period_proficiency_explanation` resolves one exact #35 result,
its exact calendar revision, target period, policy, scale, and every candidate
Grade Item basis.

Each Grade Item remains one of the canonical contribution states, including:

```text
calculated and contributing
insufficient Grade Item result
missing Grade Item result
period-scope mismatch
```

Period-scope mismatch preserves its exact reason rather than inferring period
membership from dates.

Where #35 stores an exact #34 reference, the nested Grade Item trace follows that
historical reference rather than whatever #34 result happens to be current now.

## Planning derivation trace

`meridian.planning_signal_derivation_explanation` resolves one exact #38
content-addressed derivation, exact #37 policy, exact Core roster basis, target
#35 policy/scale, contextual bands, and per-student derivation state.

For a contributor, the trace makes the mapping explicit:

```text
exact #35 Academic Period result
    -> proficiency level
    -> proficiency-scale position
    -> matching #37 band-definition range
    -> contextual ordinal band
```

For a noncontributor, missing and insufficient #35 state remain distinct and no
sentinel band is invented.

The nested trace continues through exact #35 and #34 references when present.

## Planning preview/review trace

`meridian.planning_signal_preview_review_explanation` explains one exact #39
preview together with either the canonical selected review or one explicit
historical review revision.

The projection preserves preview diagnostics, warning IDs, acknowledgments,
review decision and actor, live #38 currentness, #40 export eligibility, and a
deterministic path state such as:

```text
ready_for_review
blocked
accepted_but_not_selected
selected_but_stale
selected_and_export_eligible
not_export_eligible
```

It reuses #39/#40 currentness and export-eligibility services. Blocking
conditions are not reclassified as acknowledged warnings.

Review schema v1 has no rationale field. The explanation marks that absence
explicitly rather than inventing rationale text.

## Export trace

`meridian.planning_signal_export_explanation` starts from one exact Core
`grouping_signal_set_v1` identity and verifies:

```text
Core grouping signal
    -> Meridian export receipt
    -> exact historical #39 review
    -> exact #39 preview
    -> exact #38 derivation
    -> exact #35 result
    -> exact #34 result(s)
    -> exact #33 evidence/decision provenance
```

The receipt-bound review revision is historical export provenance. A different
review selected later does not rewrite the authorization history of an already
persisted export.

The resolver also deterministically rebuilds the expected #38-to-Core
projection. Every Core exported band must equal the corresponding contributing
#38 derived band.

Normal absent export entries are permitted only for exact #38
noncontributors. These states remain distinct:

```text
missing Academic Period proficiency result
insufficient Academic Period proficiency result
```

A contributing #38 student missing from Core, an unexpected Core student entry,
or `exported band != derived band` is an integrity failure.

## Core remains minimal

Issue #42 does not modify Core `grouping_signal_set_v1`. The shared record remains
limited to signal/class identity, timestamp, minimal source snapshot identity,
dimensions, and student bands.

Meridian-specific academic detail remains recoverable from the exact
`source.snapshot_id` / `source.snapshot_digest` plus the privacy-minimal Meridian
export receipt. There is no alternate verbose shared signal format.

## Authorization and privacy

Default trace projections are useful without opening raw producer evidence. A
Grade Item source row includes privacy-minimal canonical identity and an
`authorized_detail` state.

The machine-readable states are:

```text
not_requested
available
denied
unavailable
```

Default trace generation uses `not_requested` and does not open protected cache
content.

The optional application-layer
`expand_grade_item_evidence_detail(...)` operation delegates to Meridian's
existing authorized evidence diagnostic/cache-reader boundary. It requires the
existing deployment-provided authorization capability and verifies exact
publication, work, cache key, snapshot digest, evidence item, and student scope
before exposing a bounded projected evidence item.

Authorization denial or unavailable authorization does not become academic
missing, exclusion, unsupported evidence, or zero. The canonical source
reference and decision chain remain explainable independently.

No trace command prints raw essays, responses, guardian data, accommodations,
protected traits, or a persistent student-name trace log.

## Read-only guarantee

Trace generation performs no academic or planning writes. It does not:

```text
write or select a result
write or select a policy
change eligibility or attempt decisions
change reassessment or Standard association
write a grouping derivation or preview
acknowledge warnings
write or select a review
export a Core signal or CSV
persist an explanation log
```

The focused installed-wheel smoke compares the synthetic workspace before and
after explanation to prove trace calls do not mutate it.

## Producer neutrality and Concord boundary

Generic trace modules explain already-persisted Meridian/Core state. They do not
import ScoreForm, Quillan, Concord, Portia, or Vitrine to reconstruct producer
semantics.

The focused #42 installed smoke intentionally installs only:

```text
pds-core 0.6.3
candidate pds-meridian wheel
```

and executes outside the source checkout. Producer packages and Concord remain
absent.

Issue #42 ends at Meridian's exported Core signal. It does not explain a
downstream Concord grouping decision and does not create a GroupPlan, Group, or
GroupMembership.

## Installed qualification

The focused installed smoke exercises a synthetic persisted chain:

```text
exact historical #34 explanation
    -> exact #35 nested explanation
    -> exact #38 student-band explanation
    -> exact Meridian/Core export trace
```

It verifies deterministic text/JSON, exact historical traceability after newer
revisions become current, Core minimality, producer/Concord independence, and
no explanation-induced writes.

This acceptance is intentionally narrower than #45, which owns the later full
installed end-to-end proficiency and signal-export acceptance.

## Issue boundaries

Issue #41 remains the task/action layer:

```text
What do I need to decide or do next?
```

Issue #42 is the exact trace layer:

```text
Why is this state this way?
What contributed?
Which exact decisions, mappings, policies, scales, and reviews produced it?
```

Issue #43 owns Meridian-wide attention summaries rather than one selected exact
trace. Issue #44 owns the broad cross-producer adversarial scenario matrix, and
#45 owns the full installed end-to-end acceptance.

At completion:

```text
#41 teacher eligibility, proficiency, and planning-export workflows — implemented
#42 proficiency and planning-export explanation/trace views — implemented
#43 Meridian proficiency attention summaries — next
```
