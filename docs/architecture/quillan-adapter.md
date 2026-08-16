# Quillan v0.9.0 adapter

## Exact boundary

`meridian.quillan_adapter` supports only the released `quillan==0.9.0` public
reader. Its authenticated GitHub Release wheel is
`quillan-0.9.0-py3-none-any.whl`, SHA-256
`4e3bf92287d1a140a6edc062abcb759c02eb811c9ba4e2212e9c4878d3a07f1c`.
The release tag is `v0.9.0`; its authorized commit is
`268fe0ab6f3d74848bf71f1aa1b939adbe242452`.
The base Meridian dependency remains `pds-core>=0.6,<0.7`; the `quillan` extra
pins the producer exactly and is independent of the ScoreForm extra.

The exact adapter key is:

```text
producer module:          quillan
publication kind:         academic_result_set
manifest contract:        quillan_academic_result_manifest_v1
producer contract:        quillan_academic_work_v1
source record kind:       None
source record contract:   None
capabilities:             standards_ratings
```

The adapter ID is `quillan.academic_result`, projection contract is `1`, reader
distribution is `quillan`, and reader version is `0.9.0`. Quillan 0.8.9 and all
future versions are unsupported until an explicit compatibility decision.
Missing and unsupported readers use Meridian's controlled reader errors.

Installing Quillan does not register anything. A deployment composes the
immutable registry explicitly. Importing Meridian, the adapter module,
descriptors, registries, selection, cache assessment, or CLI help does not
import Quillan. Only `QuillanAcademicResultAdapter.project()` lazily imports
`quillan.academic_result_reader.read_academic_result_manifest`.

## Reader and Core agreement

The adapter consumes only a verified immutable `AdapterProjectionRequest`. It
does not parse JSON itself, query Core, discover catalogs, open a Quillan
workspace, inspect source files, resolve artifacts, or invoke publication
workflows. The public reader owns canonical decoding and all producer-native
validation.

After reading once, Meridian fails closed unless the manifest agrees exactly
with the request's adapter key, registration presence, absent Publication Record
source record, `academic_results` record set, `standards_ratings` capability,
producer and manifest contracts, complete work identity, record-set identity,
and revision. Public failures are privacy-safe `AdapterProjectionError` values;
reader exceptions remain available as causes without exposing manifest bytes or
feedback.

## Evidence mapping and ordering

Producer order is retained: students; review state and exceptional disposition;
minimum-requirement status; review units and observations; then represented
teacher-entered overall ratings. Every item uses the exact `StudentSubject`,
exact Core publication/registration/withdrawal provenance, projection identity,
and `eligibility = unevaluated`.

| Result kind | Target | Value |
| --- | --- | --- |
| `review_state` | submission, no fabricated ID | exact `NativeStateValue` |
| `review_disposition` | submission, only for returned-without-full-review | `NativeStateValue("returned_without_full_review")` |
| `minimum_requirement_status` | submission | exact `NativeStateValue` |
| `standard_applicability` | exact review unit and Focus Standard | Boolean `NativeScalarValue` |
| `standard_evidence_presence` | exact review unit and Focus Standard | Boolean `NativeScalarValue`, omitted when null |
| `standard_observation_rating` | exact review unit and Focus Standard | exact `NativeScaledValue`, or `NativeStateValue("unrated")` for a null slot |
| `overall_standard_rating` | exact Focus Standard | exact teacher-entered `NativeScaledValue` |

`returned_without_full_review` is a workflow disposition, never a score. Minimum
statuses remain nonnumeric. Not applicable, evidence absent, evidence present
but unrated, a native minimum rating, and a missing overall rating remain
distinct. An absent overall rating emits no placeholder. Observation ratings
never become or calculate overall ratings.

Released Quillan native scale, review-unit, observation, and standard identities
use the generic producer-native text boundary. Meridian preserves spaces,
slashes, punctuation, Unicode, embedded formatting, and meaningful surrounding
whitespace exactly as returned by the validated public reader; it does not trim
or normalize them. Such identities remain data, not artifact paths or authority
to open producer files.

## Native scale

One `NativeScale` is constructed from the assignment snapshot. It preserves the
exact scale ID, producer level order, integer values, labels, and descriptions;
its contract version is `None`. Values such as `0, 2, 4` remain `0, 2, 4`.
Meridian introduces no normalization, percentage, proficiency threshold,
default scale, Grade meaning, or best/latest selection.

## Provenance and privacy

Every item retains the assignment, student submission, and student review source
snapshots as their exact public relative paths and SHA-256 digests. Review-unit
observations also retain unit ID, producer sequence, observation ID, and
standard ID; overall items retain standard ID. Timestamps remain separate as
`manifest_generated_at`, `minimum_requirement_updated_at`,
`observation_updated_at`, and `overall_rating_updated_at` when present.

Submission entry method is retained. Plain-paper results fabricate no digital
identity. PDS2 results may retain exact public issuance, generation, and artifact
envelope identifiers, but these are not attached as inferred support for an
individual review judgment. Source references are provenance, not authorization.

PublishedText dispositions (`absent`, `withheld`, and `included`) remain in the
Core-bound immutable producer manifest. This projection does not copy student
prompts, teacher notes, observation or overall rationale, feedback comments, or
any other long-form text into evidence. It cannot reconstruct private notes,
raw QR payloads, retained/routed paths, candidate evidence, workspace paths, or
other producer-private material.

Item IDs are `quillan_` plus a SHA-256 digest over length-delimited semantic
identity fields. They are deterministic, value-independent, preserve native
slot identity, and contain no plaintext student IDs. No wall-clock time enters
projection.

## Cache identity and non-goals

The existing generic projection cache accepts the inventory unchanged. Its
execution identity records adapter `quillan.academic_result`, contract `1`,
distribution `quillan`, and reader `0.9.0`; the adapter never reads or writes
cache state.

This adapter does not calculate proficiency, percentages, Grades, Grade-item or
Academic Period membership, eligibility, reassessment winners, or portfolio
policy. It does not advertise points, question evidence, criterion scores,
moderation, interventions, grading, proficiency, or portfolio capabilities.
