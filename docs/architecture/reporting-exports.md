# Reporting exports

Issue #56 implements Meridian v0.3's teacher-controlled local Grade/report
export boundary on top of the immutable ReportingSnapshot runtime from issue
#55. The exported representation is downstream of frozen reporting authority;
it is not another Grade calculation and it is not an official school-system
record.

The governing flow is:

```text
exact immutable ReportingSnapshot
+ exact immutable ExportProfile revision
+ exact bounded Core roster observation when selected fields require it
-> deterministic ExportPreview
-> final exact-source revalidation
-> explicit teacher local export
-> exact local file or copyable payload
-> immutable ExportReceipt
```

The authority distinctions remain explicit:

```text
ReportingSnapshot != ExportProfile
ExportProfile != ExportPreview
ExportPreview != exported artifact
exported artifact != ExportReceipt
ExportReceipt != official SIS/LMS/gradebook record
external-system write = no
external-system acceptance claim = no
```

## Exact snapshot source

Every export starts from one exact `ReportingSnapshotReference` containing the
class ID, snapshot ID, and SHA-256. The exporter loads that exact immutable
snapshot through the issue #55 storage boundary. It does not export from a live
Grade calculation, live Grade preview, current Grade-policy selection, current
override selection, or a newest-snapshot inference.

A teacher may deliberately export an older snapshot by exact reference. Changing
the ReportingSnapshot current-use selector after preview does not substitute a
new source for the approved export.

## Immutable Export Profiles

`ExportProfileRevision` is class-local immutable configuration. Each revision
binds a stable profile identity, linear revision history, title and purpose,
explicit ordered columns, representation settings, teacher actor/rationale/time,
and source-field registry version. Its exact `ExportProfileReference` binds:

```text
class_id
profile_id
profile_revision
profile_sha256
```

Writing a profile revision does not select it. `ExportProfileCurrentSelection`
is separate mutable convenience state protected by compare-and-swap. Exports
always bind the exact profile revision that was previewed; they never infer the
highest revision or silently follow the current selector.

## Closed source-field registry

Profile columns are explicit `source_field` plus `output_name` pairs. Column
order is semantic output order and duplicate output names are rejected. There
is no Python expression, template language, JSONPath, formula language,
arbitrary traversal, or wildcard roster selection.

The v1 snapshot-native registry includes stable fields for snapshot identity,
Grade target identity, row state, frozen base/effective Grade state, and exact
Grade-policy identity. Roster-backed fields are bounded to:

```text
roster.first_name
roster.last_name
roster.display_name
roster.period
roster.extra:<exact_column_name>
```

`roster.extra:<exact_column_name>` must name one real canonical optional Core
roster column. `roster.extra:*`, `roster.*`, and equivalent wildcards are not
supported. Core roster `period` and reporting `target.period_id` remain distinct
concepts.

## Privacy-bounded Core roster observation

Snapshot-native profiles do not consult the roster. When a selected profile
uses roster-backed fields, Meridian creates an `ExportRosterObservation` using
the public Core v0.6.3 roster contract.

The observation contains only the exact class, the exact selected roster source
fields, the distinct student IDs already present in the frozen snapshot, and the
selected values for those students. Students are canonicalized by durable
`student_id`; selected fields are canonicalized by field identity. It does not
copy the full roster, unselected optional fields, file paths, mtimes, or roster
row order.

`roster.display_name` delegates to Core's public `student_display_name()`
semantics, including `preferred_name` when Core makes it applicable. Meridian
does not duplicate preferred-name selection logic.

This makes currentness material rather than incidental. Roster row reordering,
an edit to an unselected field, or a change to an unselected student leaves the
observation digest unchanged. A selected name, roster period, display name, or
selected optional value changes the digest and makes the approved preview stale.
A roster-backed preview also fails closed if the canonical roster is unavailable,
a snapshot student is absent, or an explicitly selected optional column is
absent.

## Grade representation

Export is representation, not another grading-policy layer. It does not
recalculate Grades, change weights, rerun reassessment, select a different
override, convert proficiency, or apply new rounding.

Numeric Grade fields are serialized directly from the frozen Decimal value using
plain deterministic decimal text. Binary float and locale formatting are not
used. In particular:

```text
missing / blocked / insufficient / unavailable != numeric zero
```

A missing numeric field renders as an empty tabular field while status columns
remain available to preserve the distinction. An actual frozen numeric zero is
still zero.

## CSV and TSV representation

V1 supports deterministic UTF-8 CSV and TSV/copy-friendly text. The immutable
profile controls `include_header`, `line_ending = lf | crlf`, and UTF-8 BOM
presence. CSV uses comma delimiter and deterministic quoting. TSV rejects unsafe
embedded tab/newline values rather than inventing an escaping language.

Snapshot row scope and canonical #55 target order are preserved exactly. The
exporter neither expands rows from the current roster nor drops unavailable
snapshot rows. Multiple Grade calculation families for one student remain
separate rows. If such rows exist and a profile omits
`target.calculation_family`, preview emits an ambiguity diagnostic instead of
silently collapsing them.

## Mandatory ExportPreview

`ExportPreview` is a read-only teacher-review object. It binds the exact
ReportingSnapshot reference, exact ExportProfile reference, exact bounded roster
observation reference when required, export algorithm/version, representation,
ordered output schema, row count, exact logical rows, payload SHA-256, payload
byte length, structured diagnostics, and `preview_sha256`.

`preview_sha256` binds the complete reviewed export observation. The same digest
therefore means the same exact source references, same material roster values,
same schema, and same exact outgoing bytes. Preview performs no write to the
snapshot, roster, profile selection, destination, receipt collection, or any
external system.

## Final revalidation and commit

An export commit requires the exact teacher-reviewed `preview_sha256`.
Immediately before any export side effect, Meridian reloads the exact
ReportingSnapshot, reloads the exact ExportProfile revision, re-observes only the
material roster values when required, rebuilds the complete preview, and
requires the rebuilt canonical preview to match the approved identity.

Changing a current snapshot or profile selector does not matter when the exact
previewed immutable revision remains available. Changing selected roster data
does matter and fails closed before a receipt claims success.

## File and copyable-payload behavior

File export is non-overwriting. An absent destination may be created; an exact
existing file is idempotently reusable; a different existing file is a conflict.
Symlinks, directories, unsafe parents, concurrent contradictory creation, and
readback mismatches fail closed. The exported file is reread and verified against
the exact payload bytes and SHA-256.

Copyable-text export returns the exact UTF-8 payload text and does not invoke an
OS clipboard API. A successful local copyable export still creates an immutable
receipt, but does not claim that another application received or accepted the
text.

Partial success is deterministic. If the exact artifact exists but the receipt
write previously failed, an exact retry may verify the artifact and create the
missing receipt. If a receipt already exists for a file-backed export and the
artifact is missing or differs, reload/replay fails integrity rather than
silently recreating or overwriting the destination.

## Immutable ExportReceipt

Every committed export is recorded by an immutable class-local `ExportReceipt`.
The receipt binds the exact snapshot/profile references, serializer version,
output format and schema, preview SHA-256, payload SHA-256 and byte count, row
count, destination kind, teacher actor/rationale/time, and the exact bounded
roster observation plus its digest when roster data was required.

Historical roster-backed exports therefore remain explainable after the live
roster changes. Snapshot-native receipts store no roster observation. Receipts
never store an absolute destination path; file-backed provenance retains only a
safe basename and destination kind.

The canonical receipt location is class-local under
`classes/<class_id>/modules/meridian/reporting_exports/<export_id>.json` with a
SHA-256 sidecar. Writes are create-only with exact replay/conflict behavior,
strict canonical JSON, bounded reads, and path/symlink guards.

## Direct CLI

The bounded development CLI extends `meridian reporting` with these surfaces:

```text
meridian reporting export-profiles list|inspect|write|current|select
meridian reporting exports preview|commit
meridian reporting export-receipts list|inspect
```

Profile write/selection and export commit require explicit confirmation flags.
Without confirmation, the commands are read-only previews. Text and JSON output
use local-authority wording: frozen Meridian ReportingSnapshot, local immutable
ExportProfile, local payload/artifact, and local immutable ExportReceipt. They do
not use `posted`, `synced`, `accepted`, or other language that implies external
school-system authority.

Issue #57 remains responsible for the final teacher-facing main-menu
orchestration; issue #56 does not create a competing main menu.

## Dependency and authority boundary

Issue #56 is qualified against current compatible stable sibling releases:

```text
pds-core 0.6.3
scoreform 0.11.0
quillan 0.10.1
pds-concord 0.3.0
```

Quillan 0.10.1 preserves the public publication/reader boundary used by Meridian;
its unrelated feedback-batch additions do not alter export semantics. Vitrine
v0.3.0 remains interoperability context only and is not a Meridian runtime
dependency.

The implementation mutates only #56-owned profile selection and export receipt
state plus the teacher-selected local destination artifact. Core roster/class/
Academic Period/publication state, producer data, Grade Items, membership,
eligibility, attempt/reassessment decisions, proficiency results, Grade
policies/activations/results, teacher overrides, ReportingSnapshots, and
ReportingSnapshot current-use selection remain unchanged by preview or export.
