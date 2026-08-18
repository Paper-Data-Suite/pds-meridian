# Package and validation foundation

## Status

Meridian has an installable development package at `0.1.1.dev0`. The package is
an executable foundation with exact optional ScoreForm, Quillan, and Concord
adapters and a read-only `meridian.diagnostics` publication/evidence command surface. It does
not calculate proficiency or Grades or generate reports.

## Requirements

- Python 3.11 or later
- the authenticated `pds-core` v0.6 line
- the exact Core v0.6.0 wheel for baseline CI and release-reproducibility checks
- the exact authenticated ScoreForm v0.10.0 wheel for adapter validation
- the exact authenticated Quillan v0.9.0 wheel for adapter validation
- the exact authenticated Concord v0.2.0 wheel for adapter validation

The runtime dependency is:

```text
pds-core>=0.6,<0.7
```

## Development installation

Core v0.6.0 is distributed through its GitHub Release artifacts rather than
PyPI. Install the verified wheel before installing Meridian:

```powershell
python -m pip install .\pds_core-0.6.0-py3-none-any.whl
python -m pip install .\scoreform-0.10.0-py3-none-any.whl
python -m pip install .\quillan-0.9.0-py3-none-any.whl
python -m pip install .\pds_concord-0.2.0-py3-none-any.whl
python -m pip install -e ".[dev,scoreform,quillan,concord]"
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
  -CoreWheel C:\path\to\pds_core-0.6.0-py3-none-any.whl `
  -ScoreFormWheel C:\path\to\scoreform-0.10.0-py3-none-any.whl `
  -QuillanWheel C:\path\to\quillan-0.9.0-py3-none-any.whl `
  -ConcordWheel C:\path\to\pds_concord-0.2.0-py3-none-any.whl
```

The cross-platform authority is:

```text
python scripts/validate_repository.py --core-wheel <core-wheel> --scoreform-wheel <scoreform-wheel> --quillan-wheel <quillan-wheel> --concord-wheel <concord-wheel>
```

Use `--allow-dirty` while developing. The default complete validation requires a
clean working tree.

The validator authenticates Core, ScoreForm, Quillan, and Concord before installed
dependency checks, pytest, Ruff, strict mypy, documentation validation, package
builds, Twine checks, wheel
inspection, isolated wheel smoke testing, `git diff --check`, and repository
cleanliness checks.

## Entry-point boundary

This package declares only the `meridian` console script. It deliberately does
not declare:

```text
paper_data_suite.modules
paper_data_suite.publication_producers
```

It also exposes no adapter plugin group in this foundation issue. Adapter
selection and loading belong to issue #7.

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
