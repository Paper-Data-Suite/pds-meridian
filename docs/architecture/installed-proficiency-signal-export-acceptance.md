# Installed proficiency and signal-export acceptance without Concord

## Status and scope

Issue #45 is the installed end-to-end composition acceptance for Meridian v0.2.

It proves that the released producer/Core artifacts and the candidate Meridian
wheel compose through the complete academic-interpretation and planning-export
chain without requiring Concord:

```text
pds-core     0.6.3
scoreform    0.11.0
quillan      0.10.0
candidate pds-meridian
```

The dedicated acceptance environment deliberately contains no `pds-concord`
distribution and no importable `concord` package.

Issue #45 is an acceptance/composition issue. It reuses the production behavior
implemented in issues #27 through #44; it does not introduce a second
proficiency model, planning model, serializer, storage family, or orchestration
API.

## Installed-environment boundary

`scripts/smoke_test_proficiency_signal_export_wheel.py` creates a fresh virtual
environment outside the repository checkout and installs the four supplied PDS
wheels:

```text
candidate Meridian
pds-core 0.6.3
ScoreForm 0.11.0
Quillan 0.10.0
```

Ordinary third-party dependencies required by the released producer wheels are
resolved normally. The acceptance does not use `--system-site-packages`.

The subprocess environment removes inherited:

```text
PYTHONPATH
PYTHONHOME
PYTHONSTARTUP
CONCORD_WHEEL
```

and sets `PYTHONNOUSERSITE=1`. The installed program verifies exact distribution
versions, verifies that all imported PDS modules resolve inside the isolated
environment, and verifies both before and after execution that:

```text
pds-concord distribution absent
concord import package absent
concord not loaded in sys.modules
```

The repository-wide validator still receives and verifies the released Concord
wheel for the complete supported adapter set. That qualification is separate
from the issue #45 smoke, which receives only Meridian, Core, ScoreForm, and
Quillan wheel arguments.

## Synthetic producer publication

The scenario uses only synthetic identities:

```text
class                  synthetic_class_2026
contributing student   student_synthetic_001
noncontributor         student_synthetic_002
Standard               standard_ela_1
ScoreForm work          synthetic_quiz_alpha
Quillan work            synthetic_essay_alpha
```

ScoreForm producer state is created through the released ScoreForm assignment,
result, Academic Work Registration, immutable result-manifest, and Core
publication APIs. The contributing student has two genuine ScoreForm attempts.

Quillan producer state is created through the released assignment, submission,
review, Standard-rating, Academic Work Registration, immutable result-manifest,
and Core publication APIs. The contributing student has one real
Standard-backed Quillan native rating.

The smoke does not fabricate final `EvidenceItem` values to bypass producer
publication.

Immediately after publication it captures immutable baselines for:

```text
producer-owned native source bytes
producer-owned manifest bytes
canonical Core Publication Records
manifest digests and publication identities
```

## Installed projection and authorization

Meridian discovers the two canonical Core publications and composes only:

```text
ScoreForm producer profile + ScoreForm adapter
Quillan producer profile + Quillan adapter
```

No Concord producer profile or adapter is constructed.

Each exact publication is projected through the installed producer reader and
cached through Meridian's ordinary projection-cache boundary. The authorization
scope is explicit:

```text
purpose = grading_import
students = (
    student_synthetic_001,
    student_synthetic_002,
)
```

Fresh cache reload replays that exact purpose and student scope. The acceptance
therefore verifies the cache's authorization-scope binding instead of relying on
possession of a cache key or path.

## Teacher-controlled Grade Item interpretation

One explicit Grade Item revision includes both published works.

The scenario then authors the normal Meridian decisions in order:

```text
Grade Item membership
    != evidence eligibility

eligibility
    != attempt selection

attempt selection
    != reassessment

producer-declared Standard alignment
    != Meridian Standard association

producer-native value
    != Meridian proficiency
```

Evidence eligibility is explicitly included for the exact ScoreForm/Quillan
source references.

Both ScoreForm attempts remain present. An explicit attempt-selection policy and
decision select the finite intended attempt set. An explicit reassessment
decision uses `replace` semantics so attempt 2 replaces attempt 1. Attempt 1 is
therefore retained in history and explanation as
`reassessment_noncontributing`; chronology or score never chooses it
implicitly.

Exact Standard associations are then authored for the contributing ScoreForm
question-correctness observations and the Quillan overall Standard rating.

Source-scoped native-value mapping profiles remain distinct:

```text
ScoreForm scalar correctness
    -> exact scalar mapping

Quillan native Standard rating
    -> exact native-scale mapping
```

There is no universal intermediate numeric normalization layer.

## Grade Item proficiency and explanation

The production #33 aggregation resolver builds the bounded calculation inputs.
The production #34 engine calculates the contributing student's Grade Item
proficiency and persists/selects the exact result.

The installed scenario proves:

```text
student_synthetic_001
    status = calculated
    proficiency = proficient
    contributing observations = 2

student_synthetic_002
    status = insufficient_evidence
    proficiency_level_id = None
    reason = no_performance_evidence
```

The second student is not converted into beginning proficiency, zero, or another
synthetic low state.

The issue #42 Grade Item explanation is then resolved from persisted state. It
retains the exact producer sources, membership, eligibility, ScoreForm attempt
selection, ScoreForm reassessment, Standard association, mapping profiles,
calculation policy, target scale, result revision, and exclusion reason for the
replaced attempt.

Explanation is read-only and does not recalculate or repair state.

## Academic Period proficiency and explanation

The Grade Item is explicitly assigned to one exact Core Academic Period and
calendar revision.

The production #35 aggregation consumes the selected #34 result. Membership
bases are supplied in the deterministic `(module_id, work_id)` order required by
the #35 contract.

The contributing student persists/selects a calculated Academic Period result.
The noncontributing student persists/selects an actual insufficient Academic
Period result with no proficiency level.

The issue #42 Academic Period explanation verifies the exact #35 policy,
calendar/membership basis, and nested exact #34 result digest. It never
substitutes whatever #34 revision might later become current.

## Grouping-signal policy and deterministic derivation

One explicit #37 policy binds the exact selected #35 basis, target scale, and
durable Standard. Its planning dimension is contextual rather than a permanent
learner classification.

The policy uses deterministic scale-position bands and configures insufficient
results as noncontributing.

The production #38 generator creates one immutable, content-addressed
derivation. Both roster students remain represented in Meridian's private
derivation:

```text
student_synthetic_001
    source_state = calculated
    disposition = contributing
    band = assigned

student_synthetic_002
    source_state = insufficient_evidence
    disposition = noncontributing
    band = None
```

The second student receives no sentinel band.

Repeated generation from unchanged state agrees with the stored derivation
identity and fingerprint.

## Preview, diagnostics, and explicit review

The production #39 path creates the exact preview over the stored derivation.
Coverage exposes one contributor and one noncontributor.

Any warning diagnostics produced by that real preview are acknowledged by exact
diagnostic ID. The scenario authors an explicit `accepted_for_export` review and
explicitly selects that review revision.

Preview is not review, and accepted review is not export.

## Core export and privacy/minimality

The production #40 export workflow performs live revalidation and writes Core's
released `grouping_signal_set_v1`.

The source binding is exactly:

```text
source.kind = module_generated
source.module_id = meridian
source.snapshot_id = exact derivation_id
source.snapshot_digest_algorithm = sha256
source.snapshot_digest = exact derivation SHA-256
```

Only the contributing student appears in Core `student_bands`.
`student_synthetic_002` is absent rather than assigned a low/null/sentinel band.

The Core signal is explicitly checked not to leak Meridian-private academic
state such as:

```text
raw ScoreForm answers or points
Quillan native ratings
proficiency_level_id or proficiency labels
scale positions
Standard IDs
Grade Item IDs
Academic Period result details
attempt or reassessment rationale
teacher actor identity
preview diagnostics
review acknowledgments
student display names
```

Core remains the neutral interchange; rich provenance remains in Meridian.

## Canonical Core JSON round trip

The exact stored Core signal is loaded through Core storage.

The acceptance verifies:

```text
GroupingSignalSet
    -> Core canonical JSON bytes
    -> Core canonical parser
    -> equal GroupingSignalSet
    -> identical canonical JSON bytes
```

The Core storage digest equals SHA-256 of those exact canonical bytes.

No Meridian grouping-signal serializer is introduced.

## Core-native CSV round trip

Meridian's optional CSV export is generated from the exact stored Core signal
and its matching Meridian receipt.

Core's public CSV parser and reconstruction APIs then prove:

```text
stored Core signal
    -> grouping_signal_csv_v1
    -> Core CSV parser
    -> Core signal reconstruction
    -> exact same GroupingSignalSet
    -> identical canonical JSON bytes
```

Because the scenario exports one dimension, the CSV representation is complete
for that signal. Exact replay to the same destination reconciles without
overwriting different bytes.

The CSV contains no private proficiency fields or student display names.

## Fresh-process persisted-history reload

The installed acceptance does not stop with first-process objects.

After writing the complete chain, the wrapper launches
`scripts/smoke_program_proficiency_signal_export_reload.py` in a second Python
process in the same isolated virtual environment.

The first process writes a bounded acceptance witness containing only exact
identities/digests needed for verification. The second process then reloads from
disk:

```text
ScoreForm Core Publication Record and manifest
Quillan Core Publication Record and manifest
authorized projection caches
Grade Item proficiency result and explanation chain
Academic Period proficiency result and nested Grade Item trace
grouping-signal policy/derivation
preview and selected review
Meridian export receipt
Core grouping signal
CSV bytes
```

The second process reopens both projection caches under the original exact
authorization scope. It traces the Core export backward through:

```text
Core signal
    -> Meridian receipt
    -> exact review
    -> exact preview
    -> exact derivation
    -> exact #35 result
    -> exact #34 result
```

No Python object identity or process-local cache is accepted as proof.

## Producer-source and publication immutability

After the full workflow and fresh-process reload, producer-owned source files and
immutable producer manifests are re-hashed and compared with the immediate
post-publication baseline.

The original Core Publication Records are reloaded by exact publication ID and
must equal the original immutable publication identities/digests.

Meridian does not:

```text
rewrite ScoreForm evidence
rewrite Quillan evidence
mark an attempt selected inside producer storage
write proficiency back to a producer
write grouping-band state back to a producer
change producer record-set revisions
change publication IDs or manifest digests
```

Teacher interpretation remains downstream Meridian state.

## Installed acceptance versus focused tests

Earlier issues retain focused unit, integration, and installed-wheel tests for
their individual boundaries. Issue #44 retains the broader source-level
cross-producer semantic matrix, including Concord.

Issue #45 does not replace those tests. Its separate responsibility is to prove
one connected production-like installed workspace whose exact producer
publications, teacher decisions, calculations, explanations, derivation, review,
Core signal, CSV, and reload history all bind the same provenance chain.

## Repository qualification

`scripts/validate_repository.py` retains its required `--concord-wheel`
repository-wide input and existing complete-adapter qualification.

It additionally invokes the dedicated issue #45 smoke with only:

```text
candidate Meridian wheel
Core wheel
ScoreForm wheel
Quillan wheel
```

The issue #45 wrapper itself strips any inherited `CONCORD_WHEEL` before the
installed program runs.

The smoke program, reload program, architecture document, and issue #45
acceptance tests are source-distribution guarded. They do not become runtime
wheel members.

The runtime dependency boundary remains:

```text
pds-core>=0.6.3,<0.7
```

with exact optional producer readers:

```text
scoreform==0.11.0
quillan==0.10.0
pds-concord==0.3.0
```

## Boundary with issue #46

Issue #45 proves installed composition, provenance continuity, privacy-minimal
Core export, producer immutability, Concord independence for the target path,
and fresh-process reload.

Issue #46 owns the final v0.2.0 policy, fairness, privacy, interoperability,
artifact, and release audit. Issue #45 does not preempt that final audit.

## Handoff

```text
#42 explanation/trace views — implemented
#43 Meridian proficiency attention summaries — implemented
#44 cross-producer proficiency scenarios — implemented
#45 installed proficiency and signal-export acceptance without Concord — implemented
#46 final v0.2.0 audit — implemented; release preparation qualified
```
