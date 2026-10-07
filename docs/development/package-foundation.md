# Package and validation foundation

## Status

Meridian v0.3.1 is the prepared compatibility candidate for the released v0.3
teacher-controlled evidence-policy, standards-proficiency, Grade, explanation,
reporting, attention, and planning surface. Released v0.3.0, v0.2.0, and v0.1.1
packages remain historical release foundations.

The v0.3 package retains publication/evidence and proficiency authority while
adding conventional, standards-based, profile-constrained, and hybrid Grades,
teacher Grade overrides, deterministic Grade/report explanations,
ReportingSnapshots, explicit local exports/receipts, Grade/report attention,
Suite readiness integration, and bounded canonical storage paths.

## Requirements

- Python 3.11 or later
- the authenticated `pds-core` v0.6 line
- the exact Core v0.6.4 wheel for candidate qualification
- the exact authenticated ScoreForm v0.12.1 wheel for adapter validation
- the exact authenticated Quillan v0.10.5 wheel for adapter validation
- the exact authenticated Concord v0.3.0 wheel for adapter validation

The runtime dependency is:

```text
pds-core>=0.6.3,<0.7
```

## Development installation

Core v0.6.4 is distributed through its GitHub Release artifacts rather than
PyPI. Install the exact qualified wheels before installing Meridian:

```powershell
python -m pip install .\pds_core-0.6.4-py3-none-any.whl
python -m pip install .\scoreform-0.12.1-py3-none-any.whl
python -m pip install .\quillan-0.10.5-py3-none-any.whl
python -m pip install .\pds_concord-0.3.0-py3-none-any.whl
python -m pip install -e ".[dev]" --no-deps
python -m pip check
meridian --version
meridian --help
meridian publications --help
meridian evidence --help
```

## Local validation

From an activated repository virtual environment:

```powershell
.\run_tests.ps1 `
  -CoreWheel C:\path\to\pds_core-0.6.4-py3-none-any.whl `
  -ScoreFormWheel C:\path\to\scoreform-0.12.1-py3-none-any.whl `
  -QuillanWheel C:\path\to\quillan-0.10.5-py3-none-any.whl `
  -ConcordWheel C:\path\to\pds_concord-0.3.0-py3-none-any.whl
```

The cross-platform authority is:

```text
python scripts/validate_repository.py --core-wheel <core-wheel> --scoreform-wheel <scoreform-wheel> --quillan-wheel <quillan-wheel> --concord-wheel <concord-wheel>
```

Use `--allow-dirty` while developing. The default complete validation requires a
clean working tree.

The validator authenticates Core, ScoreForm, Quillan, and Concord, runs an
upstream dependency-direction audit proving those frozen distributions do not
depend on Meridian, and then performs installed dependency checks, pytest, Ruff,
strict mypy, documentation validation, package builds, and Twine checks. It
validates both the wheel boundary and source-distribution boundary, then runs
isolated base, per-producer, and all-adapter coexistence wheel smoke tests before
`git diff --check` and the final repository-cleanliness check.

## Entry-point boundary

This package declares only the `meridian` console script. It deliberately does
not declare:

```text
paper_data_suite.modules
paper_data_suite.publication_producers
```

It also exposes no adapter plugin group. Producer readers remain exact
optional dependencies composed explicitly by Meridian.

## Read-only baseline

Importing `meridian` or running help/version/group-help commands must not
discover a workspace, query Core, load producer packages, configure logging, or
write files. Publication metadata diagnostics are read-only. Persisted evidence
diagnostics additionally require deployment authorization before cache access.

## Projection-cache package boundary

The built wheel includes `meridian.evidence_serialization`,
`meridian.projection_cache`, `meridian.diagnostics`,
`meridian.scoreform_adapter`, `meridian.quillan_adapter`, and
`meridian.concord_adapter`. Importing these modules remains read-only and does
not resolve a workspace, create cache directories, discover producers, import
producer packages, invoke authorization, or write files. Core remains the only
unconditional runtime dependency; ScoreForm, Quillan, and Concord are exact and
optional.
