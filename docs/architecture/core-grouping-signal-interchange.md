# Core neutral grouping-signal interchange

Issue #36 formally adopts Core's neutral grouping-signal interchange as the
shared planning-signal boundary for Meridian v0.2 development.

The governing data flow is:

```text
Meridian private academic interpretation
        |
        | later teacher-controlled derivation
        v
Meridian private grouping-signal derivation state
        |
        | minimal explicit projection
        v
Core grouping_signal_set_v1
        |
        | exact immutable selection
        v
optional downstream planning consumer
```

The initial planned suite path is:

```text
Meridian
   |
   v
Core grouping_signal_set_v1
   |
   v
Concord
```

This is an interchange flow, not a direct Meridian-to-Concord runtime
dependency.

Issue #36 establishes and qualifies the contract boundary. It does not define
Meridian's grouping-signal derivation policy, calculate production grouping
signals, present an export preview, create Groups, or export a real planning
signal from Meridian-owned academic state.

## Release baseline

The `grouping_signal_set_v1` contract was introduced by `pds-core` 0.6.1.

Meridian's authoritative issue #36 qualification baseline is instead:

```text
distribution: pds-core
version:      0.6.3
wheel:        pds_core-0.6.3-py3-none-any.whl
wheel sha256: 98d7596ce0eed26e4d56a17bbbbd644db3014259b56a45783a173fe8237af5e5
```

These facts have different meanings:

```text
contract introduction history:
    pds-core 0.6.1

current Meridian qualification baseline:
    pds-core 0.6.3
```

Meridian already requires:

```text
pds-core>=0.6.3,<0.7
```

because earlier v0.2 work uses Core 0.6.3 standards-framework capabilities.
Issue #36 must therefore never lower the dependency floor to 0.6.1 merely
because that was the first Core release containing the signal contract.

Core 0.6.3 preserves established Core 0.6 APIs while adding newer standards
surfaces. No grouping-signal workspace, path, or schema migration is required
to move from 0.6.1 or 0.6.2 to 0.6.3.

The repository's exact Core wheel verifier remains the authority for release
qualification. An editable Core checkout, locally rebuilt wheel, unreleased
branch, or same-version wheel with different bytes is not equivalent to the
authenticated release artifact.

When implementation begins against a future PDS release state, the project-wide
rule still applies: use the most recent compatible released PDS dependency
rather than preserving a stale version only because an older ticket named it.

## Governing architectural decision

Core ADR 0004 adopts:

```text
grouping_signal_set_v1
```

as a strict, immutable, producer-neutral interchange for contextual ordinal
student planning signals.

Meridian adopts that decision rather than defining a sibling contract.

The academic and planning meanings remain distinct:

```text
producer evidence
!= Meridian evidence interpretation
!= Grade Item standards proficiency
!= Academic Period standards proficiency
!= Meridian grouping-signal derivation
!= Core grouping_signal_set_v1
!= Concord GroupPlan
!= Group
!= GroupMembership
!= Grade
```

No layer may silently absorb another layer's responsibility.

## Ownership boundary

### Core owns

Core is the sole shared authority for:

```text
grouping_signal_set_v1 contract identity
GroupingSignalSource
GroupingSignalDimension
GroupingSignalStudentBand
GroupingSignalSet

strict structural validation
canonical in-memory ordering
canonical JSON serialization/parsing
grouping_signal_csv_v1 conversion
immutable exchange persistence
canonical signal-byte SHA-256
signal replay/conflict behavior
exact class_id and student_id interpretation
workspace-aware roster diagnostics
grouping-signal exchange paths
```

Meridian uses those public APIs directly.

### Meridian owns

Meridian remains authoritative for the academic state that may eventually
produce a signal, including:

```text
which academic results are eligible
which exact result snapshots are selected
which Academic Period/context is selected
teacher-controlled derivation policy
academic dimension meaning
band count
band-boundary policy
tie handling
missing/insufficient academic-evidence policy
rich derivation provenance
derivation explanations
teacher rationale
freshness/staleness of derivation state
decision to offer/export a signal
```

Those executable behaviors begin in issues #37-#40. They are intentionally not
implemented by issue #36.

### Downstream planning consumers own

A downstream consumer such as Concord may own:

```text
exact signal selection
exact dimension selection
planning strategy
similar-signal or mixed-signal planning
manual adjustment
missing-signal planning decisions
GroupPlan preview
GroupPlan approval
Group creation
GroupMembership creation
```

Meridian does not perform those operations.

### Suite shell owns

The suite shell owns no academic derivation policy and no grouping algorithm.

## Public Core API boundary

Issue #36 qualifies the released public APIs from:

```python
pds_core.grouping_signals
pds_core.grouping_signal_csv
pds_core.grouping_signal_storage
pds_core.grouping_signal_diagnostics
```

Important public Core surfaces include:

```text
GroupingSignalSource
GroupingSignalDimension
GroupingSignalStudentBand
GroupingSignalSet

validate_grouping_signal_set
grouping_signal_set_to_dict
grouping_signal_set_from_dict
grouping_signal_set_to_json
grouping_signal_set_to_json_bytes
grouping_signal_set_from_json

GroupingSignalCsvDocument
parse_grouping_signal_csv
grouping_signal_csv_to_signal_set
grouping_signal_set_from_csv
grouping_signal_set_to_csv
grouping_signal_set_to_csv_bytes

StoredGroupingSignal
GroupingSignalWriteResult
calculate_grouping_signal_digest
write_grouping_signal
load_grouping_signal
list_grouping_signal_ids

GroupingSignalDiagnostic
GroupingSignalDimensionDiagnostics
GroupingSignalDiagnosticReport
diagnose_grouping_signal
```

Meridian must not reimplement these shared mechanics.

Issue #36 deliberately adds no `meridian.grouping_signals` runtime module merely
to rename Core concepts. Later Meridian-owned code should introduce a new
runtime abstraction only for genuinely Meridian-owned derivation state or
workflow behavior.

## No competing Meridian interchange

The following would violate this boundary when used as a shared wire model:

```text
MeridianGroupingSignal
MeridianSignalSet
MeridianPlanningBandSet
meridian_grouping_signal_v1
meridian_grouping_signal_set_v1
```

Meridian likewise must not create a competing:

```text
JSON codec
CSV contract/parser
signal digest algorithm
Core exchange-path grammar
immutable exchange store
roster-diagnostic engine
```

Production code must not manually open or write Core grouping-signal JSON,
manually manage `.json.sha256` sidecars, reconstruct Core exchange paths, or
copy Core's structural validation rules.

A thin Meridian helper is appropriate only when it owns Meridian semantics and
delegates the shared interchange mechanics to Core.

## Frozen version-1 identity

The exact shared contract identity is:

```text
contract:       grouping_signal_set_v1
schema_version: "1"
record_type:    grouping_signal_set
```

Version 1 has exactly these top-level fields:

```text
schema_version
record_type
signal_set_id
class_id
created_at
source
dimensions
student_bands
```

Unknown extension fields are invalid. The signal is intentionally too small to
serve as a generic metadata bag.

Rich Meridian academic state remains outside this record.

## Signal identity and immutability

One signal snapshot has exact logical identity:

```text
(class_id, signal_set_id)
```

It is immutable.

A material semantic change requires a new:

```text
signal_set_id
```

Material changes include:

```text
different student-band assignments
different student coverage
different dimension set
different band count
different upstream derivation snapshot
different academic interpretation
teacher edit
corrected signal
different band-boundary result
```

Version 1 has no:

```text
revision
supersedes
latest
current
active
head
mutable overwrite
```

semantics.

Meridian must not create convenience behavior equivalent to:

```text
load latest signal
select newest signal
select greatest signal_set_id
select newest created_at
follow current signal
overwrite an earlier signal
```

Discovery through `list_grouping_signal_ids(...)` is not selection. A consumer
must select an exact signal identity deliberately.

## `created_at` semantics

Core's required:

```text
created_at
```

is the creation/export time of that exact immutable signal snapshot.

It is not:

```text
an Academic Period boundary
an evidence timestamp
a Grade Item due date
a proficiency-result timestamp
a recency policy
proof that underlying academic activity happened then
```

No academic meaning or automatic selection may be inferred from it.

## Source provenance

Core version 1 permits exactly:

```text
teacher_authored
module_generated
```

source kinds.

A future Meridian-generated signal uses:

```text
source.kind = module_generated
source.module_id = meridian
```

and binds an exact opaque upstream snapshot through:

```text
source.snapshot_id
source.snapshot_digest_algorithm = sha256
source.snapshot_digest
```

Core does not define what the Meridian snapshot contains. The final
Meridian-owned derivation record is a later issue responsibility.

Do not encode rich academic or consumer state into Core `source`, including:

```text
Grade Item IDs
Academic Period result internals
standards evidence
proficiency labels
mapping profiles
attempt/reassessment details
band-boundary formulas
teacher rationale
Concord strategy
GroupPlan identity
filesystem paths
identity-bearing filenames
```

`source.snapshot_id` is an opaque source identity, not a local path.

Teacher-authored signals remain first-class Core values. Meridian's use of
`module_id="meridian"` must never be converted into a universal Core
requirement.

## Upstream source digest versus signal digest

Two different SHA-256 relationships exist.

For a module-generated signal:

```text
source.snapshot_digest
```

binds the exact upstream producer-owned source/derivation snapshot.

Separately:

```text
calculate_grouping_signal_digest(signal)
```

binds the canonical `grouping_signal_set_v1` JSON bytes stored by Core.

Conceptually:

```text
Meridian derivation snapshot
        |
        | SHA-256
        v
source.snapshot_digest


Core GroupingSignalSet
        |
        | canonical JSON UTF-8 bytes
        | SHA-256
        v
Core signal-record digest
```

The values are not interchangeable.

Never:

```text
copy the Core signal digest into source.snapshot_digest
use source.snapshot_digest to verify Core signal JSON
treat source.snapshot_digest as the .json.sha256 sidecar value
```

Issue #36 focused and installed acceptance explicitly qualifies this distinction.

## Rich Meridian state stays private to Meridian

A Core grouping signal is a deliberate minimal projection from richer producer
state.

The Core record must not contain:

```text
raw grades
percentages
point totals
producer-native scores
proficiency-category names
proficiency-result objects
Grade Item result objects
Academic Period result objects
standards evidence
questions or criteria
attempt histories
reassessment histories
eligibility decisions
mapping profiles
proficiency-scale definitions
calculation explanations
policy revisions
band-boundary formulas
tie decisions
missing-evidence rationale
teacher notes
freshness state
Concord strategy
GroupPlan identity
Group identity
GroupMembership identity
```

Later Meridian derivation records may retain enough exact provenance to explain
and reproduce an export. That detail remains on the producer side of the
interchange boundary.

## Contextual ordinal band semantics

For a dimension with:

```text
band_count = N
```

valid bands are:

```text
1..N
```

inclusive.

A band establishes ordinal order only within:

```text
that exact signal_set_id
+
that exact dimension_id
```

It does not establish equal numeric distance. For example, Core does not claim
that:

```text
4 - 3
```

has the same academic meaning as:

```text
2 - 1
```

A grouping-signal band is not:

```text
a Grade
a percentage
a point value
a rubric score
a shared proficiency category
a standardized score
an ability label
an intelligence label
a readiness label
a disability label
a language-status label
a behavior label
a demographic label
a permanent learner attribute
a Group
a GroupMembership
```

Meridian documentation and APIs must not relabel bands as universal `low`,
`medium`, `high`, `proficient`, `advanced`, `weak`, `struggling`, or ability
categories.

Issue #37 will define the teacher-controlled academic policy by which Meridian
may derive temporary contextual bands.

## Dimension semantics

A Core signal contains one or more dimensions. Each declares:

```text
dimension_id
band_count
```

A `dimension_id` is a stable machine identifier in the exact signal/provenance
context. It is not a Core global academic ontology.

Do not assume:

```text
first dimension == default
same dimension_id across signals == same scale
same band number across dimensions == equivalent meaning
```

Do not automatically:

```text
select the first dimension
average dimensions
merge dimensions
rank across dimensions
convert several dimensions into one numeric score
```

A downstream consumer that uses one dimension must select it explicitly.

The teacher-controlled rules for which Meridian dimension or dimensions to
derive belong to issue #37.

## Exact student identity

Signal entries use exact Core:

```text
student_id
```

identity.

Do not resolve entries using:

```text
student name
display name
email
roster order
case-insensitive guessing
prefix matching
fuzzy matching
producer-local display identity
```

Core's structural model validates identifier syntax. Core's workspace-aware
diagnostics compare those exact IDs to canonical rosters.

## Partial coverage and missing signals

Partial roster coverage is valid.

Absence of:

```text
(student_id, dimension_id)
```

means only:

> No signal band exists for that student in that dimension in that exact signal
> snapshot.

It does not mean:

```text
band 0
lowest band
failure
not proficient
absent
unenrolled
excluded
no ability
permission to drop the student from planning
```

Meridian must not create sentinel band values for missing state.

Core requires every declared dimension to have at least one entry, but a
represented dimension may omit any number of roster students.

Later Meridian policy may decide that insufficient academic evidence yields no
signal entry. Later teacher-facing preview must explain such omissions. A
downstream planning consumer must make an explicit planning decision rather than
silently inventing a band.

## Structural invalidity versus missing coverage

Valid partial coverage is distinct from structural errors such as:

```text
duplicate (student_id, dimension_id)
undeclared dimension reference
band outside 1..band_count
invalid identifier
unsupported schema version
wrong record type
noncanonical JSON wire bytes
```

Meridian must not convert those errors into missing-band state.

Core owns structural validation and rejects invalid records.

## Canonical ordering and JSON

Core owns deterministic version-1 ordering.

Canonical runtime ordering is:

```text
dimensions:
    dimension_id ascending

student_bands:
    dimension_id ascending
    then student_id ascending
```

List order does not encode priority.

Canonical JSON is emitted only by Core's public serializer. The strict Core
loader rejects semantically equivalent but byte-different wire representations,
including noncanonical list order, object ordering, whitespace, line endings,
timestamp form, duplicate keys, or final-newline differences.

Meridian does not provide a "helpful" normalization layer for invalid persisted
Core signal bytes.

The canonical bytes are the bytes used by Core's storage digest.

## Human-editable CSV boundary

Core also owns:

```text
grouping_signal_csv_v1
```

as a human-editable one-dimension representation.

CSV is not a second authoritative signal model. Canonical
`grouping_signal_set_v1` JSON remains authoritative, and Core storage hashes
canonical JSON rather than CSV.

### Complete single-dimension signal

A one-dimension signal may be represented as:

```text
representation_scope = complete_signal
```

When every canonical field is preserved unchanged, it can make an
identity-preserving CSV round trip.

### Multi-dimension projection

Selecting one dimension from a multi-dimension signal produces:

```text
representation_scope = dimension_projection
```

That projection is not the complete source signal.

Converting it into a standalone signal requires explicit fresh:

```text
new_signal_set_id
new_created_at
```

It must not reuse the immutable identity of the multi-dimension source.

### No alternate Meridian CSV

Meridian must not create a shared interchange format such as:

```text
meridian_grouping_signal.csv
Meridian-specific signal metadata headers
raw-academic-value columns
```

Issue #40's optional production CSV workflow must delegate to Core's public CSV
APIs.

## Immutable Core exchange storage

Core owns grouping-signal exchange persistence.

The version-1 logical path is:

```text
exchange/
└── grouping-signals/
    └── <class_id>/
        ├── <signal_set_id>.json
        └── <signal_set_id>.json.sha256
```

This path grammar is Core implementation authority. Meridian production code
must use public Core storage functions rather than reconstructing it.

Write semantics are:

```text
new exact identity
    -> created

same exact identity + same canonical bytes
    -> existing

same exact identity + different canonical bytes
    -> conflict
```

The store is create-only and immutable.

Core strictly verifies canonical bytes, sidecar shape, digest binding, path
identity, and visible storage entries. Invalid/incomplete/tampered state fails
closed and is not silently repaired.

Issue #36 uses synthetic storage writes only to qualify Core's released
interchange. Production Meridian export begins later.

## No `latest` or `current` signal pointer

Core version 1 deliberately has no signal-selection pointer.

Meridian must not create:

```text
current.json
latest.json
active.json
head.json
```

for Core grouping-signal exchange state.

It must not infer selection from:

```text
filesystem modification time
created_at
lexicographic signal_set_id order
directory enumeration order
```

Exact signal identity is selected explicitly.

## Workspace-aware Core diagnostics

Core owns roster-aware diagnostics through:

```python
diagnose_grouping_signal(...)
```

Current structured findings are:

```text
class_mismatch
wrong_class_student
unknown_student
missing_student_signal
```

The report also contains per-dimension:

```text
roster student count
signal-entry count
matched count
missing count
unknown count
wrong-class count
matched band counts
```

These diagnostics are:

```text
read-only
deterministic
non-repairing
```

They never fuzzy-match, remap, delete, or synthesize a student entry.

Issue #36 qualification covers:

```text
clean exact match
valid partial coverage
missing student signal
unknown student ID
student found in another class
explicit target-class mismatch
deterministic per-dimension band distribution
```

Teacher-facing Meridian preview of its own proposed academic export belongs to
issue #39, not to Core's neutral roster diagnostic layer.

## Producer neutrality and Concord independence

Core's contract does not require Meridian.

Teacher-authored signals remain valid with neither Meridian nor Concord
installed.

Likewise, Meridian's future signal-generation/export path must work when Concord
is absent.

Issue #36 installed-wheel acceptance therefore installs only:

```text
exact pds-core 0.6.3 release wheel
candidate pds-meridian wheel
```

for its grouping-signal contract smoke, and explicitly verifies that
`pds-concord` is absent.

The existing Meridian `concord_adapter` is a separate producer-ingestion concern
for Academic Result ingestion. It is not the grouping-signal interchange
mechanism and must not be repurposed into one.

The dependency direction remains:

```text
Meridian -> Core
```

for signal production/export and, independently:

```text
Concord -> Core
```

for later signal consumption.

Prohibited grouping-signal dependency directions include:

```text
Meridian -> Concord
Concord -> Meridian
Core -> Meridian
Core -> Concord
```

## No academic feedback loop

A grouping signal is an output/interchange projection.

It is not a new Meridian academic input merely because it exists in the shared
workspace.

Do not:

```text
ingest grouping_signal_set_v1 as standards evidence
convert a band into a proficiency level
convert a band into a Grade Item value
use a grouping signal to choose an attempt
use a grouping signal to select reassessment evidence
use a grouping signal to change Academic Period proficiency
```

The direction is:

```text
academic interpretation
    ->
optional planning signal
```

not:

```text
academic interpretation
    <->
planning signal
```

This prevents circular academic interpretation.

## Privacy boundary

A populated grouping signal is:

```text
teacher-restricted educational data
```

even though raw academic values are intentionally absent.

It still contains:

```text
class identity
student IDs
relative educational planning signals
source provenance
```

Signal values must not be reproduced by default in:

```text
application logs
crash reports
passive diagnostics
troubleshooting bundles
suite attention summaries
PDS2 QR payloads
route metadata
packet metadata
Artifact metadata
Academic Result manifests
Publication Records
public screenshots
public examples
```

Repository fixtures and acceptance examples must be synthetic.

Core's `.json.sha256` sidecar is an integrity binding for canonical bytes. It is
not an authentication signature against an attacker who can freely rewrite both
files.

## Issue #36 implementation shape

Because Core already owns the complete shared contract surface, issue #36 does
not need a new Meridian grouping-signal runtime subsystem.

The implementation is intentionally centered on:

```text
focused contract qualification
installed-wheel acceptance
source-distribution guards
authoritative validator wiring
architecture documentation
```

Focused tests qualify:

```text
typed model and contract identity
module-generated Meridian provenance
teacher-authored provenance
canonical ordering
partial coverage
strict invalid-state rejection
canonical JSON
CSV complete/projection behavior
immutable Core storage
digest separation
idempotent replay
identity conflicts
deterministic listing
tamper/incomplete-pair rejection
workspace roster diagnostics
```

The isolated installed-wheel smoke proves the same public Core boundary using
only Core plus Meridian, with Concord absent.

This is deliberate evidence that the correct implementation is contract
adoption, not a duplicate abstraction.

## Boundary to issue #37

Issue #36 leaves Meridian knowing:

```text
what neutral Core object later derivation must produce
how Core validates/canonicalizes it
how Core converts one dimension to/from CSV
how Core persists it immutably
how provenance and the two digests differ
how Core diagnoses roster identity/coverage
what information must not cross the boundary
```

Issue #36 does not yet define executable policy for:

```text
which exact proficiency snapshots to use
which academic dimension to derive
how many bands to create
where band boundaries fall
how ties are resolved
how missing academic evidence is treated
when derivation is confirmed
```

Those decisions belong to:

```text
#37 — Define teacher-controlled grouping-signal derivation policy
```

The expected later sequence remains:

```text
#37 policy
    ->
#38 deterministic derivation
    ->
#39 teacher preview/diagnostics
    ->
#40 explicit immutable Core/CSV export
```

## Non-goals

Issue #36 does not implement:

```text
teacher-controlled derivation policy
band-boundary policy
evidence-window policy
tie policy
missing-academic-evidence policy
rich Meridian derivation snapshots
deterministic production band generation
teacher-facing signal generation
teacher-facing export preview
production Core signal export
production CSV export
automatic signal creation
automatic signal regeneration
automatic export
automatic signal selection
automatic dimension selection
Concord launch
Concord planning
similar-signal grouping
mixed-signal grouping
GroupPlan
Group
GroupMembership
Grade calculation
weighted Grade execution
report generation
SIS synchronization
Core schema changes
producer schema changes
```

## Architectural invariants

The following invariants govern later Meridian grouping-signal work:

1. `grouping_signal_set_v1` is the sole shared grouping-signal contract.
2. Core owns shared model, JSON, CSV, storage, digest, and roster diagnostics.
3. Meridian owns academic derivation policy and rich provenance.
4. A downstream planning consumer owns planning and group formation.
5. Meridian and Concord do not import one another for this workflow.
6. Signal identity is exactly `(class_id, signal_set_id)`.
7. A material signal change requires a new `signal_set_id`.
8. No automatic latest/current signal selection exists.
9. `created_at` is creation/export time, not academic-period policy.
10. `source.snapshot_digest` and the Core canonical signal digest are different
    integrity bindings.
11. Raw academic values do not cross the neutral interchange.
12. Bands are contextual ordinal values, not Grades or permanent learner
    classifications.
13. Dimensions are independent and explicitly selected.
14. Student identity is exact `student_id`.
15. Partial coverage is valid and is never converted into a sentinel band.
16. Structural invalidity is not treated as missing coverage.
17. A multi-dimension CSV projection requires fresh identity/time when made
    standalone.
18. Core exchange writes are immutable and conflict on changed same-identity
    contents.
19. Core roster diagnostics are read-only and non-repairing.
20. Teacher-authored signals remain first-class.
21. Meridian signal qualification must work without Concord installed.
22. Grouping signals never feed back into Meridian academic interpretation.
23. Populated signals are teacher-restricted educational data.
24. Issue #36 introduces no production derivation/export behavior.
25. Issue #37 is the next executable-policy boundary.

## References

- Core `docs/decisions/0004-adopt-neutral-grouping-signal-interchange.md`
- Core `docs/grouping_signal_set_v1.md`
- Meridian
  `docs/decisions/0004-v02-evidence-policy-proficiency-and-planning-export-architecture.md`
- Meridian
  `docs/architecture/academic-period-proficiency-aggregation.md`
- Meridian issue #36
- Meridian umbrella issue #25
