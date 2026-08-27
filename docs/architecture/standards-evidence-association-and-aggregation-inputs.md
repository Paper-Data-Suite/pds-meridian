# Standards-evidence association and aggregation inputs

Issue #33 implements the last two interpretation stages before pure standards
proficiency calculation:

```text
producer-declared alignment
!= Meridian standards-evidence association
!= bounded operative aggregation inputs
!= calculated standards proficiency
```

It preserves the separate #27 Grade Item, #28 membership, #29 eligibility, #30
attempt-selection, #31 reassessment, and #32 native-value mapping contracts. No
persisted schema from those issues changes. The #28 membership-directory
validator only admits the new exact `standards_evidence/` child.

## Association model

`meridian.standards_evidence.StandardEvidenceAssociationDecision` is frozen and
slotted. One logical family binds `class_id`, `grade_item_id`, the complete
`EvidenceSourceReference`, and durable Core `standard_id`. This supports both
directions of the many-to-many relationship and keeps separate producer result
kinds separate.

Persisted disposition is exactly `associated` or `not_associated`; absence of a
selected revision is `no_decision`. Basis is `producer_declared` or `explicit`.
Both bases remain teacher/policy-owned through `StandardEvidenceActor`; there is
no producer actor and no inferred actor identity.

`producer_declared` is validated only by exact membership of `standard_id` in
the exact projected item's `EvidenceTarget.standard_ids`. Codes, descriptions,
criterion names, sibling items, Focus Standards, and hierarchy are never used
to infer the relationship. `explicit` permits a teacher/policy association to a
currently resolvable durable Core standard without changing the producer target.

Revisions are contiguous. Revision 1 supersedes nothing; revision N supersedes
N-1. A transition may change disposition, valid basis, actor, rationale, and
decision time, but not logical identity.

## Core v0.6.3 authority

New writes use Core's public `StandardsLibrary`, `find_standard_definition`,
`filter_standards_frameworks`, and workspace standards loading API. Durable
`standard_id` is the identity. `StandardDefinition.active` and current
`StandardsFrameworkMetadata` are resolution diagnostics, not persisted
calculation identity.

An inactive definition remains resolved. If a definition later disappears, the
historical association remains loadable and resolution reports
`standard_unresolved`; no similar code is substituted. Framework adoption or
supersession does not rewrite identity. Meridian emits no `StandardUsageEvent`.

## Canonical storage

Association storage is nested under exact #28 work membership:

```text
classes/<class_id>/modules/meridian/grade_items/<grade_item_id>/
  memberships/<producer_module_id>/<work_id>/standards_evidence/
    associations/<association_key>/
      current.json
      revisions/<N>.json
      revisions/<N>.json.sha256
```

`association_key` is SHA-256 of canonical JSON containing class, Grade Item,
the complete exact source reference, and real `standard_id`. Raw standard IDs
never become path components, including IDs containing Windows-hostile
punctuation.

Revision bytes are canonical UTF-8 JSON with one LF. Revisions and SHA-256
sidecars are immutable, histories are contiguous and replayed exactly, reads are
bounded, and model/path identities are checked. Directory containment,
unexpected entries, nonregular files, and symlinks fail closed. A narrow
per-association lock protects writes and selection. Writing does not select.
`current.json` binds revision and exact SHA-256, is replaced atomically, and is
changed only through compare-and-swap. Historical revisions may be reselected;
no highest revision, timestamp, mtime, or directory ordering becomes current.

Exact replay of already-persisted bytes occurs before new-write dependency
validation so later source/Core drift cannot destroy reproducibility.

## Resolution

`resolve_current_standard_evidence_association(...)` reports distinct
`no_decision`, `associated`, `not_associated`, `source_unverifiable`, and
`standard_unresolved` states. It exposes the selected stored decision, exact
association reference/digest, basis, current standard resolution, active state,
matching current framework metadata, and source verifiability. Eligibility,
attempt, and reassessment are deliberately absent from association status.

## Bounded aggregation inputs

`build_standard_aggregation_inputs(...)` is pure. It accepts one exact
`GradeItemAggregationBasis`, student, durable standard, exact
`ProficiencyScaleReference`, and a caller-supplied set of already-resolved
`ResolvedStandardAggregationCandidate` values. It performs no filesystem
discovery, time lookup, profile selection, policy choice, or arithmetic.

The candidate limit is `MAXIMUM_STANDARD_AGGREGATION_CANDIDATES == 1000`.
Over-limit and duplicate exact source/standard presentation are rejected.
Entries are ordered only by the stable exact source key; order has no recency,
quality, attempt, or preference meaning.

Every candidate produces exactly one `StandardAggregationInputEntry`:

| Condition | Status | Reason/value |
| --- | --- | --- |
| associated, operative upstream state, exact mapped target scale | `performance` | exact `proficiency_level_id` |
| same, mapping returns `NativeStateValue` | `native_state` | exact native state |
| no selected association | `excluded` | `association_unresolved` |
| selected rejection | `excluded` | `not_associated` |
| eligibility unresolved/not included | `excluded` | `eligibility_unresolved` / `eligibility_not_included` |
| attempt unresolved/not selected | `excluded` | `attempt_selection_unresolved` / `attempt_not_selected` |
| reassessment unresolved/noncontributing | `excluded` | `reassessment_unresolved` / `reassessment_noncontributing` |
| no exact profile supplied | `excluded` | `mapping_not_supplied` |
| unmapped/unsupported profile result | `excluded` | `mapping_unmapped` / `mapping_unsupported` |
| profile targets another exact scale | `excluded` | `scale_mismatch` |
| source/standard cannot resolve | `excluded` | `source_unverifiable` / `standard_unresolved` |
| nonstudent/wrong student | `excluded` | `nonstudent_target` / `student_mismatch` |

`resolve_standard_aggregation_inputs(...)` is the narrow storage-aware layer. It
loads only explicit `StandardAggregationCandidateBinding` values, resolves the
current upstream decisions, loads only the supplied exact mapping-profile
revision/digest and its exact scale, maps the exact value, then delegates to the
pure builder. It never selects a current/newest/matching profile.

Aggregation serialization includes the exact Grade Item basis, student,
standard, target scale, ordered entries, statuses/reasons, exact source and
upstream references, profile provenance, and mapped level or native state.
`standard_aggregation_inputs_sha256(...)` provides the stable digest that #34
may bind. Mutable Core display/framework metadata is excluded. There is no
`current_aggregation.json`; persisted calculated snapshots belong to #34.

## Producer semantics and privacy

- ScoreForm v0.10.0 question `standard_ids` remain candidate alignment.
  Correctness, selected response, selected-response state, and attempt totals
  remain separate; attempts inherit no child standards and blank/ambiguous
  states do not become zero.
- Quillan v0.10.0 uses the unchanged released v1 public reader contract with an
  updated exact reader identity. Focus Standards do not associate holistic
  review state. Standard applicability, evidence presence, observation rating,
  and overall rating remain distinct; `unrated` remains native state.
- Concord v0.2.0 criterion IDs are not Core standard IDs. Standard-backed score
  alignment may support `producer_declared`; criterion evidence may use
  `explicit`. Group/nonstudent evidence is not individualized.

Records contain only durable identity and exact provenance needed for the
decision/input. They do not copy answers, feedback, accommodations,
demographics, images, producer artifacts, roster names, or full Core standard
descriptions. Generic runtime/storage imports no producer package.

## Boundary to #34

#33 does not calculate means, highest/latest values, weighted values,
percentages, sufficiency, Grades, or proficiency. Issue #34 is next and owns the
pure policy-driven standards-proficiency calculation over these exact inputs.
