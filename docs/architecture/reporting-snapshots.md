# Immutable ReportingSnapshots

Issue #55 implements Meridian v0.3's canonical, immutable reporting-snapshot
boundary over the read-only Grade/report preview layer completed by issue #54.
The implementation freezes what a teacher deliberately observed; it does not
create a second Grade calculation, reinterpret producer evidence, or become an
official school-system record.

The governing separation is:

```text
producer evidence
    != Meridian interpretation
    != proficiency
    != Grade calculation
    != teacher override
    != Grade preview/explanation
    != ReportingSnapshot
    != export artifact
    != official school-system record
```

A later upstream change creates a later observation. It never rewrites an
existing ReportingSnapshot.

## Ownership and dependency boundary

`ReportingSnapshot` is Meridian-owned canonical state. It is not a Core
Publication Record, a producer publication, a Vitrine Portfolio Snapshot /
Edition, an export receipt, a CSV file, or an SIS/LMS write. No new Core
publication kind is introduced, and the runtime has no `pds-vitrine`, Portia,
ScoreForm, Quillan, or Concord dependency.

The implementation continues to consume released Core 0.6.x contracts through
Meridian's existing Core boundary. Producer-specific source access remains
behind the already-authorized projection path; issue #55 does not crawl producer
private storage.

## Bounded v1 report definitions

`meridian.reporting_snapshot` defines immutable
`ReportingDefinitionRevision` records and exact
`ReportingDefinitionReference` values. The v1 contract is deliberately narrow:

```text
report_kind        = grade_report
intended_audience  = teacher
actor.kind          = teacher
```

A definition binds one class, one `AcademicPeriodRef`, a stable definition ID,
an immutable positive revision, title/purpose, actor, rationale, and revision
time. Later definition changes create another immutable revision; they do not
edit an earlier one.

Definition storage is class-local and revisioned:

```text
classes/<class_id>/modules/meridian/reporting_definitions/
  <definition_id>/revisions/<revision>.json
  <definition_id>/revisions/<revision>.json.sha256
```

There is no implicit "highest revision is current" rule.

## Explicit build request

`ReportingSnapshotBuildRequest` is a versioned, data-only record of the exact
reporting request. It binds:

- the exact `ReportingDefinitionReference`;
- explicit `GradePreviewTarget` values rather than roster discovery;
- exact caller-bounded work-evidence identities for conventional/hybrid rows;
- requesting `ReportingActor`;
- request rationale and timestamp; and
- optional exact predecessor relationship.

The build request stores projection identities as exact
`publication_id`/`cache_key`/`snapshot_digest` references rather than protected
producer payloads. Available conventional/hybrid work evidence requires an
explicit bounded projection set; missing/unavailable evidence remains explicit.
Standards-based rows reject irrelevant conventional work evidence.

## Frozen #54 report content

Issue #55 does not rebuild a parallel presentation model. It freezes the exact
structured `GradeReportPreview` produced by issue #54. The snapshot-owned strict
reload representation preserves:

- available and `no_selected_grade` rows;
- family-specific Grade explanation detail;
- exact `GradePreviewObservation` for every available row;
- base Grade and base-result status;
- freshness status/reasons;
- policy and calculation identity;
- override applicability and replacement Grade;
- effective Grade and effective source; and
- deterministic report summary counts.

Unavailable remains unavailable. Blocked/insufficient remains nonnumeric. No
missing state becomes silent numeric zero.

## Two digest identities

The canonical record deliberately distinguishes two SHA-256 identities:

```text
payload_sha256
    = semantic ReportingSnapshot payload before the integrity envelope

ReportingSnapshotReference.snapshot_sha256
    = exact SHA-256 of the final canonical stored snapshot bytes
```

The snapshot additionally binds the canonical build-request digest, frozen
report-preview digest, and exact per-row observation digests. Strict reload
recomputes and verifies all of those identities. Duplicate JSON keys, unknown
schema shapes, malformed digests, or noncanonical encodings fail closed.

## Deep provenance binding

`ReportingSnapshotProvenanceBinding` keeps provenance typed and digest-bound.
The freeze workflow derives bindings for applicable authority including:

- exact Core Academic Period calendar revision;
- Core Publication Records and observed publication lifecycle/currentness;
- exact authorized projection identities;
- Grade Item revisions;
- membership decisions;
- evidence-eligibility decisions;
- attempt-selection decisions;
- reassessment decisions;
- proficiency mappings and nested proficiency results;
- exact Grade-policy activation;
- exact Grade-policy revision;
- persisted final Grade result; and
- selected teacher Grade override state.

Opaque provenance reference keys remain opaque. Issue #55 does not reverse-parse
an opaque digest/key into stronger authority than the producing contract
actually supplies. Necessary structured reporting/provenance is frozen; arbitrary
protected source evidence is not copied into the snapshot.

## Immutable storage and historical loading

`meridian.reporting_snapshot_storage` owns class-local immutable persistence:

```text
classes/<class_id>/modules/meridian/reporting_snapshots/
  <snapshot_id>.json
  <snapshot_id>.json.sha256
```

`snapshot_id` is opaque and is the only snapshot filename identity. Raw student
IDs are not introduced as per-student directories or filenames.

A successful first write is create-only. Exact replay is idempotent; contradictory
reuse of one snapshot ID is a conflict. Every load verifies the digest sidecar,
canonical JSON, internal payload digest, exact definition reference, exact
predecessor reference, report-preview digest, and row observation digests.
Historical loading does not consult current-use selection.

Storage rejects symlink/path escape, malformed directory shape, oversized reads,
missing digest sidecars, and corrupt canonical bytes. Definition and snapshot
writes use class-local locks and fsync-compatible write discipline without
mutating any upstream academic authority.

## Atomic freeze workflow and whole-report currentness

`freeze_reporting_snapshot(...)` in `meridian.reporting_snapshot_freeze` is the
high-level issue #55 service boundary. Its sequence is deliberately optimistic
rather than a global academic-state lock:

```text
validate live #54 requests == canonical build request
verify exact definition
verify exact Core Academic Period calendar revision
revalidate exact authorized projection bytes + Core publication/manifest state
build initial #54 GradeReportPreview
freeze exact canonical report bytes
extract typed provenance
compose candidate ReportingSnapshot
reverify exact definition/calendar dependencies
revalidate exact authorized projection bytes + Core publication/manifest state
rebuild the same #54 report as the final optimistic witness
require byte-identical whole-report observation
commit immutable snapshot
reload/verify through storage
```

Each issue #54 row already performs its own currentness re-observation. Issue #55
adds the second report-level observation so a multi-row report cannot knowingly
splice rows around a material authority change. Before both report observations,
freeze also reopens the exact already-authorized projection-cache bytes, verifies
their digest and canonical decode, reloads the canonical Core publication state,
and verifies the bound publication manifest. This revalidation does not grant or
repeat authorization; authorization remains a deployment/caller responsibility.

Corrupt or unreadable exact projection/Core provenance fails as an integrity
error. If canonical publication/projection authority legitimately moves between
the candidate observation and the final witness, freeze raises
`reporting_snapshot.currentness_conflict`. If the final report bytes differ, the
same currentness conflict is raised. In either case no canonical snapshot is
written.

Snapshot generation is read-only with respect to producer state, Core
Publication Records/withdrawals/registrations/calendars, Grade Items, membership,
eligibility, attempt selection, reassessment, mappings, proficiency results,
Grade policies/activation, Grade result selection, and teacher overrides.

## Current-use selection is separate mutable authority

Freeze does not select. `meridian.reporting_snapshot_selection` owns an explicit
current-use selector scoped by:

```text
class
+ definition family (definition_id)
+ exact AcademicPeriodRef
+ exact calendar_revision
```

The current selector is stored separately:

```text
classes/<class_id>/modules/meridian/reporting_snapshot_selections/
  <definition_id>/<school_year>/<period_id>/calendar_<revision>/current.json
```

`ReportingSnapshotCurrentSelection` binds the exact selected
`ReportingSnapshotReference`, exact selected definition reference, teacher actor,
rationale, decision time, monotonically increasing selection revision, and exact
prior selection reference where applicable.

Selection uses compare-and-swap protection. Newest timestamp, largest snapshot
ID, directory order, and predecessor relationship never define current use.
Selecting an older historical snapshot intentionally is valid when the caller
supplies the exact expected prior selection.

## Correction and predecessor relationships

A new snapshot may point to an earlier exact snapshot with one of:

```text
supersedes
corrects
replaces_for_current_use
```

The predecessor is never edited. Relationship metadata is historical context,
not selection authority:

```text
B supersedes A
    !=
B is currently selected
```

Only the explicit current-use selector grants that local reporting-use status.

## Historical comparison reuses issue #54

`meridian.reporting_snapshot_comparison` is an adapter, not another diff engine.
Available frozen observations are converted through
`prior_reporting_snapshot_grade_basis_from_observation(...)`, then compared only
through issue #54's `compare_grade_preview_basis(...)`.

That preserves #54 semantics for:

- unchanged comparable observations;
- effective Grade change with exact Decimal delta;
- policy/activation changes;
- weighting changes;
- evidence/proficiency-basis changes;
- override and applicability changes;
- freshness changes;
- calculation-family changes in one logical student/period scope; and
- deterministic new/removed targets.

The acceptance boundary is therefore:

```text
freeze real ReportingSnapshot
load real ReportingSnapshot
extract frozen GradePreviewObservation
adapt through #55 -> #54 boundary
compare through existing #54 engine
```

No `PriorReportingSnapshotGradeBasis` needs to be manufactured by callers, and
no second comparison implementation exists.

## Bounded development CLI

Issue #55 exposes a bounded development/qualification CLI without taking over
issue #57's final teacher-facing menu design. The supported operations are:

```text
meridian reporting definitions list
meridian reporting definitions inspect
meridian reporting definitions write

meridian reporting snapshots list
meridian reporting snapshots inspect
meridian reporting snapshots freeze
meridian reporting snapshots compare

meridian reporting selection show
meridian reporting selection select
```

Definition writes, snapshot freezes, and selection changes are fail-safe by
default and require their explicit confirmation flags before mutation. Snapshot
freeze still delegates to `freeze_reporting_snapshot(...)`; CLI code does not
reimplement Grade calculations, override precedence, comparison semantics, or
snapshot storage.

Conventional/hybrid CLI freeze and comparison reopen evidence only through the
existing authorization-gated projection-cache loader. Supplying projection IDs
or scope on the command line is not itself authorization. Output distinguishes
live/current Grade preview, frozen `ReportingSnapshot`, the explicitly selected
snapshot for reporting use, and any separate official district/SIS Grade. A
Meridian snapshot is never labeled posted, submitted, or official.

## Installed-wheel qualification

The issue #55 installed acceptance builds a candidate Meridian wheel/sdist and
uses a clean isolated environment with released Core and producer wheels. The
smoke runs `pip check`, verifies relevant imports resolve from installed
`site-packages` rather than editable sibling repositories, builds real released
producer/Core/Meridian Grade state, freezes a real ReportingSnapshot, and starts
a fresh process to reload exact definition/snapshot digests and compare the
frozen observation against a newly explained #54 observation. The fresh-process
comparison is read-only with respect to the persisted workspace.

## Privacy and minimality

Snapshots necessarily contain student identifiers inside protected structured
report content because the report itself identifies its subjects. That does not
justify placing those identifiers in newly introduced filesystem topology.

Provenance prefers exact digest-bound references when a reference is sufficient.
The frozen report retains only derived explanation/report content needed to
reproduce what the teacher observed; it is not an evidence archive.

## Export, Vitrine, and official-system boundaries

Issue #55 stops at immutable reporting state:

```text
ReportingSnapshot
    != ExportProfile
    != CSV/copy payload
    != export receipt
    != SIS/LMS write
```

Issue #56 may derive an export from an exact immutable snapshot and bind that
snapshot in its own receipt. It must not mutate the snapshot to add later export
metadata.

Likewise, Meridian ReportingSnapshot is not a Vitrine Portfolio Snapshot /
Edition. Any future Vitrine consumption must use a reviewed explicit contract,
not private Meridian storage crawling.

A ReportingSnapshot remains advisory/local reporting state and is never labeled
"posted", "submitted", or "official" merely because it was frozen or selected.

## Error distinctions

Issue #55 preserves meaningful failure classes rather than collapsing everything
into "not found":

- malformed definition/request/scope -> validation error;
- requested Grade row absent -> explicit frozen `no_selected_grade` row;
- corrupt definition/snapshot/provenance -> integrity failure;
- report basis moves during freeze -> `reporting_snapshot.currentness_conflict`;
- contradictory immutable identity reuse -> storage conflict;
- stale current-selection writer -> selection conflict; and
- explicitly requested historical snapshot absent -> not found.

## Implementation modules

The issue #55 runtime is split by authority rather than placed in one large
module:

```text
meridian.reporting_snapshot
meridian.reporting_snapshot_preview
meridian.reporting_snapshot_record
meridian.reporting_snapshot_storage
meridian.reporting_snapshot_selection
meridian.reporting_snapshot_freeze
meridian.reporting_snapshot_comparison
meridian.reporting_snapshot_cli
```

The runtime, bounded development CLI, adversarial/historical qualification, and
isolated installed-wheel/fresh-process ReportingSnapshot smoke are implemented.
Repository-wide regression/release qualification remains a validation gate, not
another ReportingSnapshot runtime authority.
