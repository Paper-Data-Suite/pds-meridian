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
## Slice 3 — first prepared Core migration

Slice 3 migrates the five program-backed Core-only historical wrappers from the
normal repository-validator path into one shared prepared `core` environment:

- grouping-signal generation;
- grouping-signal preview/review;
- grouping-signal export;
- teacher workflows;
- attention.

The standalone `smoke_test_*_wheel.py` wrappers remain available for direct
developer execution. The repository validator no longer invokes those wrappers;
it invokes `scripts.installed_qualification_core_programs` once.

The shared environment still launches **seven separate Python smoke processes**.
Generation, preview/review, and export each receive their own fresh working
directory. Teacher workflows intentionally run their export seed and workflow
process in one dedicated workspace. Attention intentionally runs its
preview/review seed and attention process in another dedicated workspace.
Neither paired workflow shares state with any other smoke.

This is the first intermediate structural reduction:

| Metric | Pre-#96 | After Slice 3 |
| --- | ---: | ---: |
| Temporary installed venvs in normal full validation | 24 | 20 |
| Historical program-backed Core wrapper venvs | 5 | 0 |
| Shared prepared Core venvs for that batch | 0 | 1 |

The remaining Core-only historical wrappers are not migrated by this slice.
They include the base wheel/foundation smoke, Grade Items, Academic Period
proficiency, grouping-signal contract, grouping-signal policy, and explanation
traces. Their isolation semantics will be migrated separately rather than
collapsed into this batch without audit.

## Slice 4 — remaining standalone Core workflow migration

Slice 4 moves five additional Core-only workflows into the same prepared `core`
environment introduced by Slice 3:

- Grade Items / evidence-eligibility interpretation;
- Academic Period proficiency;
- Core grouping-signal contract;
- grouping-signal derivation policy;
- explanation traces.

Each historical wrapper now exposes `run_prepared_smoke(...)`, which contains the
existing installed acceptance logic after environment setup. Direct execution
still follows the original standalone path:

```text
standalone wrapper
-> create temporary venv
-> install Core + candidate Meridian
-> pip check
-> run_prepared_smoke(...)
```

Repository qualification instead follows:

```text
prepared core matrix
-> install once
-> pip check once
-> fresh workflow root
-> run_prepared_smoke(...)
-> verify package fingerprint unchanged
```

The large inline smoke programs are not copied or rewritten; their existing
assertions are moved behind the reusable prepared boundary. Explanation-trace
CLI checks likewise continue to execute as fresh subprocesses against the
prepared environment's installed `meridian` executable.

The intermediate structural count is now:

| Metric | After Slice 3 | After Slice 4 |
| --- | ---: | ---: |
| Temporary installed venvs in normal full validation | 20 | 15 |
| Additional Core wrapper venvs removed in this slice | 0 | 5 |
| Prepared Core venvs | 1 | 1 |

The base wheel/foundation portion of `smoke_test_wheel.py` remains separate in
this slice because that historical wrapper also owns the ScoreForm-only,
Quillan-only, Concord-only, and all-adapters boundaries. It will be separated
when those adapter matrices are migrated rather than weakening their isolation.

## Slice 5 — central runner and embedded adapter matrix separation

Slice 5 removes the direct `smoke_test_wheel.py` execution from the normal
repository-validator path. Its five installed acceptance bodies are separated
from virtual-environment ownership and exposed as prepared helpers for:

- Core wheel/package/CLI foundation;
- ScoreForm-only adapter acceptance;
- Quillan-only adapter acceptance;
- Concord-only adapter acceptance;
- all-adapters composition.

The standalone `smoke_test_wheel.py` entry point still creates the same five
temporary environments when run directly. Repository qualification now uses
`scripts.installed_qualification_runner`, which owns prepared matrix lifetimes.

The central runner currently prepares these matrices in order:

```text
core
scoreform
quillan
concord
all-adapters
```

The Core matrix runs the wheel foundation and both Core batches from Slices 3
and 4 before that environment is destroyed. Each adapter acceptance runs in its
own exact package-presence boundary. The `scoreform-quillan` matrix is not opened
yet because its historical workflows are migrated in a later slice.

This changes the normal full-validator structural count from **15 to 14**
temporary installed environments:

| Metric | After Slice 4 | After Slice 5 |
| --- | ---: | ---: |
| Temporary installed venvs in normal full validation | 15 | 14 |
| Direct `smoke_test_wheel.py` internal venvs in validator | 5 | 0 |
| Prepared matrices owned by central runner | 1 | 5 |

The apparent increase from one to five prepared matrices is intentional: four
of those replace the historical adapter environments one-for-one, while the
Core foundation is folded into the already-required Core matrix. More important,
the matrix lifetime now has one central owner. Subsequent slices can move the
remaining ScoreForm, ScoreForm+Quillan, and all-adapters workflows into those
matrix scopes without introducing another venv.
