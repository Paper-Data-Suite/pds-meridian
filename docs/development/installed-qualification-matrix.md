# Installed qualification matrix — Issue #96

Issue #96 optimizes setup duplication in Meridian's installed-wheel qualification
without reducing the acceptance evidence. This document records the audited
dependency boundaries before environment reuse is introduced.

## Baseline inventory

The post-#57 validator invokes nineteen standalone one-venv smoke wrappers.
`scripts/smoke_test_wheel.py` additionally creates five isolated environments
internally: Core/Meridian, ScoreForm, Quillan, Concord, and all adapters.

Therefore the pre-#96 normal full-validation path creates:

- **24** installed virtual environments;
- **24** installed-package setup operations;
- **24** `pip check` runs.

Those 24 setups represent six true dependency-isolation boundaries.

| Matrix | Producer packages present | Producer packages intentionally absent |
| --- | --- | --- |
| `core` | none | ScoreForm, Quillan, Concord |
| `scoreform` | ScoreForm | Quillan, Concord |
| `quillan` | Quillan | ScoreForm, Concord |
| `concord` | Concord | ScoreForm, Quillan |
| `scoreform-quillan` | ScoreForm, Quillan | Concord |
| `all-adapters` | ScoreForm, Quillan, Concord | none |

Core and the exact candidate Meridian wheel are required in every matrix.

## Smoke-to-matrix inventory

`core`

- wheel/package/CLI foundation
- Grade Items
- Academic Period proficiency
- grouping-signal contract
- grouping-signal policy
- grouping-signal generation
- grouping-signal preview/review
- grouping-signal export
- explanation traces
- teacher workflows
- attention

`scoreform`

- ScoreForm adapter
- conventional Grade
- teacher Grade override

`quillan`

- Quillan adapter

`concord`

- Concord adapter

`scoreform-quillan`

- proficiency/signal export
- standards Grade
- hybrid Grade

`all-adapters`

- all-adapter composition
- Grade report preview
- ReportingSnapshot
- report exports
- teacher menu

## Isolation contract

The matrix is about installed package identity only. Later #96 slices may share
one prepared venv among smokes assigned to the same matrix, but they must retain:

- exact candidate Meridian-wheel installation;
- exact supplied sibling-wheel installation;
- package absence for excluded producers;
- source-tree isolation;
- one `pip check` per prepared matrix;
- an immutable package set after setup;
- separate smoke processes;
- fresh workflow/workspace state where the existing acceptance requires it;
- fresh-process reload companions where they currently exist.

In particular, `scoreform-quillan` must continue to prove that Concord is
physically absent. Producer-specific adapter qualification must not be moved into
the all-adapters matrix.

## Slice status

Slice 1 records and tests this matrix only. It intentionally leaves all existing
smoke wrappers and `scripts/validate_repository.py` execution unchanged. The
pre-optimization count remains 24 until a later slice introduces the shared
prepared-environment harness.

## Prepared-environment harness

Slice 2 adds `scripts/installed_qualification_harness.py`. It is deliberately
not wired into the full repository validator yet.

For one matrix, the harness:

1. validates the exact local wheel inputs before creating a venv;
2. creates one bounded temporary virtual environment;
3. installs Core, the matrix's exact producer wheels, and the candidate Meridian
   wheel exactly once;
4. runs `pip check` once;
5. verifies installed origins with isolated Python and proves excluded producers
   are not importable;
6. captures a sorted `pip freeze --all` package fingerprint;
7. exposes a fresh empty working directory for each smoke process;
8. launches each smoke as a separate subprocess;
9. rechecks the package fingerprint after each smoke and fails closed on mutation;
10. cleans the complete temporary matrix root on context exit or setup failure.

The harness also neutralizes `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`,
user-site visibility, and ambient sibling-wheel environment variables for its
subprocesses.

This establishes the lifecycle needed for later wrapper migration while
preserving the Slice 1 rule:

```text
shared dependency environment
!= shared workflow state

reuse environment
!= reuse process
```

Until the validator is migrated in a later slice, the pre-#96 full-validation
execution count remains unchanged.
