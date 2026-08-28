# ScoreForm adapter

Released Meridian v0.1.1 qualified ScoreForm v0.10.0. Beginning with issue
#34, current unreleased v0.2 development qualifies ScoreForm v0.11.0.
ScoreForm v0.11.0 preserves the public Academic Work, publication-manifest,
record-set, capability, and public-reader contracts used by this adapter, so
the projection semantics below are unchanged. This current qualification
update does not rewrite the released v0.1.1 baseline.

## Compatibility and installation

`meridian.scoreform_adapter` currently supports only completed `scoreform==0.11.0`,
publication kind `academic_result_set`, Academic Work contract
`scoreform_academic_work_v1`, manifest contract
`scoreform_academic_result_manifest_v1`, record set `academic_results`, no
source record, and exactly `points`, `question_evidence`, and
`multiple_attempts`.

Install the authenticated GitHub Release wheels before Meridian:

```powershell
python -m pip install .\pds_core-0.6.3-py3-none-any.whl
python -m pip install .\scoreform-0.11.0-py3-none-any.whl
python -m pip install ".[scoreform]"
python -m pip check
```

The active development base dependency is `pds-core>=0.6.3,<0.7`. The optional
extra pins `scoreform==0.11.0`; 0.10.0, 0.11.1, and every other version fail with
`adapters.reader_version_unsupported`. Absence fails with
`adapters.reader_unavailable`. Installing ScoreForm does not enable anything:

```python
from meridian.adapters import AdapterRegistry
from meridian.scoreform_adapter import ScoreFormAcademicResultAdapter

registry = AdapterRegistry((ScoreFormAcademicResultAdapter(),))
```

Import, descriptor inspection, registry construction, and selection do not
import ScoreForm. Only `project()` imports the public reader after the registry
has resolved the exact distribution version. There is no global registry,
adapter entry point, profile inference, or automatic registration.

## Validation and evidence mapping

The public reader receives Core-verified immutable bytes and remains
authoritative for canonical-byte validation and ScoreForm semantics. Meridian
does not decode JSON or reload assignment, result, scan, review, workspace,
catalog, registration, or publication files.

Meridian fails closed unless the exact adapter key, absent source record,
production record set, and exact capabilities agree. Manifest work
module/class/work identity and record-set ID/revision must equal the Core
Publication Record. Neither model is repaired.

Producer order is retained: students, attempts, then responses. Each attempt
emits `attempt_points` as `NativePointValue`, followed by `result_origin` as
`NativeScalarValue`. Each response emits its native semantic followed by
independent boolean `question_correctness`:

- selected: `selected_response` with the exact selected string;
- blank: `selected_response_state` with `NativeStateValue("blank")`;
- ambiguous: `selected_response_state` with
  `NativeStateValue("ambiguous")`.

Attempt targets are `attempt_N`. Question targets are `question_Q`, parented to
the attempt, and retain ordered `standard_ids` as alignments only. No standards
rating is created. Eligibility is always unevaluated.

Every attempt survives independently. The adapter applies no official,
current, latest, highest, best, replacement, selected, preferred, or
Grade-bearing policy. It calculates no percentage, rank, proficiency, mastery,
Grade, portfolio eligibility, or report state.

## Identity and provenance

Each item has projection `scoreform.academic_result`, projection contract `1`,
reader distribution `scoreform`, and reader version `0.11.0`, plus the exact
Publication Record, referenced registration, and matching withdrawal.

Item IDs are `scoreform_` plus 64 lowercase SHA-256 hex characters. The digest
uses length-delimited UTF-8 fields for producer, class, work, student, attempt,
question or the `attempt` sentinel, and result kind. Values, revisions, paths,
clocks, object identity, and hash randomization are excluded. Plaintext student
IDs do not appear in item IDs.

Every item retains digest-only `assignment_source_snapshot` and
`results_history_source_snapshot` artifacts and distinct
`manifest_generated_at` and `recorded_at` timestamps. Every item references its
attempt; question items also reference their question.

- `pds2_scan` retains issuance, generation, artifact, source-scan, and aligned
  page/route/logical-page/source-page references. The retained source is a
  metadata-only relative-path and SHA-256 artifact.
- `plain_paper_manual` adds no fabricated scan, page, route, artifact, or review
  reference.
- `scan_review_manual` retains the exact review failure reference and invents
  no absent scan provenance.

No artifact is opened, and producer-local snapshot filenames are not projected
as workspace paths.

## Errors, cache, privacy, and non-goals

Reader import, decode, validation, and cross-contract failures use controlled
`adapters.projection_failed` errors with chained causes. Routine messages omit
manifest bytes, student IDs, answers, paths, and native records.

The adapter creates no cache state. Normal orchestration prepares the request,
invokes the explicit registry, validates the inventory, then may cache it.
Cache identity records the exact adapter, projection contract, distribution,
and reader version; future version support requires explicit code and tests.

The adapter does not change ScoreForm or Core, support version ranges, publish,
withdraw, authorize, select attempts, evaluate eligibility, grade, calculate
proficiency, render reports, or open retained evidence.
