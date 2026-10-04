# Suite operations integration

Issue #59 integrates Meridian with Paper Data Suite operations without moving
Meridian policy, academic authority, or canonical storage ownership into the
Suite shell.

The central rule is:

```text
Suite orchestration != Meridian policy ownership
```

The integration uses public Core contracts plus Meridian's existing public
console boundary. Meridian does not import the Suite package.

## Shared operations profile

Meridian publishes exactly one entry point in the Core v1 operations group:

```text
paper_data_suite.module_operations
    meridian = meridian.pds_operations:get_module_operations_profile
```

That one `ModuleOperationsProfile` exposes both independent capabilities:

- `readiness_provider` evaluates whether the supplied workspace/class context is
  structurally usable for Meridian.
- `attention_provider` projects Meridian-owned teacher work through the existing
  privacy-minimal issue #43/#58 attention contract.

Readiness and attention are independent. Readiness does not call attention, and
a ready context may still contain attention work.

Core owns the neutral request/result contract and provider validation. Meridian
owns the meaning of Meridian readiness and Meridian attention. Suite may
discover and invoke the profile through Core; it must not reproduce Meridian
storage logic or reinterpret private Meridian records.

## Readiness semantics

Readiness is structural, bounded, read-only, and fail-closed.

The stable notice codes are:

```text
meridian_readiness_unavailable
meridian_workspace_not_ready
meridian_class_not_ready
```

The current semantics are:

- no supplied workspace -> `unavailable` / `ready=None`;
- missing supplied workspace -> `unavailable` / `ready=None`, with no creation;
- linked or otherwise unsafe/uninspectable workspace -> `unavailable` /
  `ready=None`;
- existing non-directory or demonstrably non-writable ordinary workspace ->
  evaluated / `ready=False`;
- existing usable empty workspace with no class request -> evaluated /
  `ready=True`;
- exact class request -> inspect that class only; never substitute another class;
- valid Core class metadata plus valid authoritative Core roster -> evaluated /
  `ready=True`, even when no Meridian records exist yet;
- safely established missing or structurally invalid requested class -> evaluated
  / `ready=False`;
- unreadable or unsafe requested-class state -> `unavailable` / `ready=None`.

`active_school_year` is neutral context. It does not by itself turn a structurally
ready class into not-ready state.

Readiness does not require Grade Items, policies, evidence, proficiency results,
Grades, ReportingSnapshots, Export Profiles, ExportReceipts, or any other
Meridian record. It never requests protected evidence authorization and performs
zero writes.

## Attention remains Meridian-owned

Issue #59 consumes the issue #43/#58 attention provider as-is. It does not
redefine category semantics, priority, privacy, or evidence authorization.

The Core-facing attention projection remains privacy-minimal. Suite can aggregate
and present the bounded summaries but does not receive private Grade/evidence
details merely to render a dashboard.

Stable owner action IDs are Meridian-owned opaque routing identifiers:

```text
open_new_evidence
open_grade_items
open_attempt_decisions
open_exclusions
open_standards_review
open_calculation_preview
open_preview_grades
open_snapshots
open_create_planning_signal
```

They map to stable Meridian-owned destination IDs, but they are deliberately not
commands, filesystem paths, URLs, menu numbers, or callables.

## Suite doctor ownership

Suite doctor and shared operations views own cross-module orchestration and
presentation.

For Meridian, Suite may:

1. discover the single Core v1 operations profile;
2. invoke readiness and attention independently through Core;
3. present the resulting bounded status/attention information; and
4. retain an opaque Meridian owner action for a later owner-routed handoff.

Suite doctor must not parse Meridian canonical storage, calculate Meridian
readiness from filenames, duplicate attention derivation, or infer academic
state from private records.

Meridian defines no Suite-specific doctor API.

## Launcher boundary

The public installed launcher remains exactly:

```text
meridian = meridian.cli:main
```

Suite owns current-environment launcher resolution and foreground process
execution. Meridian owns the behavior behind its public console entry point.

Issue #59 does not add a hidden shell command, URL protocol, menu-number
contract, or deep-link flag. The owner action IDs remain inert routing identity;
they do not themselves execute navigation.

Installed qualification proves that the candidate wheel exposes the exact
console-script metadata and that the installed `meridian --version` and
`meridian --help` boundaries execute successfully from the isolated environment.

## Whole-workspace backup boundary

Suite owns backup/restore orchestration as opaque whole-workspace byte custody.

Meridian therefore defines no:

- module-specific backup provider;
- Meridian backup manifest;
- Meridian exclusion list;
- restore hook; or
- Suite-specific backup dependency.

Canonical Meridian records remain descendants of the supplied PDS workspace.
That includes representative selected Grade state, ReportingDefinitions,
ReportingSnapshots and their current-use selection, Export Profiles and their
selection, and ExportReceipts.

Issue #59 qualification copies a representative workspace byte-for-byte, removes
the original workspace, and reloads those canonical Meridian records through
ordinary Meridian storage APIs from the copied workspace alone.

Teacher-selected external report files are not canonical Meridian backup state.
An ExportReceipt is canonical workspace state and may retain the safe destination
basename and exact export provenance, but the external payload itself may be
deleted without making the restored Meridian workspace structurally incomplete.

## Dependency direction

Meridian retains exactly one unconditional runtime dependency:

```text
pds-core>=0.6.3,<0.7
```

There is no `paper-data-suite` runtime dependency.

The compatible runtime floor and exact qualification target are separate. Issue
#59 final installed qualification uses released **Core 0.6.4** while preserving
the existing compatible Core range.

Generic readiness qualification requires only Core plus Meridian. ScoreForm,
Quillan, Concord, Portia, Vitrine, and Paper Data Suite are not prerequisites for
evaluating structural Meridian readiness.

## Installed and repository qualification

Issue #59 installed acceptance runs inside the existing issue #96 prepared
Core-only matrix. It verifies:

- exact Core 0.6.4 plus the candidate Meridian wheel;
- source/package isolation;
- exactly one valid `paper_data_suite.module_operations` Meridian entry point;
- both readiness and attention providers;
- representative ready/not-ready/unavailable readiness outcomes;
- readiness/attention independence and zero inspection writes;
- bounded owner actions;
- absence of ScoreForm, Quillan, Concord, Portia, Vitrine, and Paper Data Suite;
- exact `meridian.cli:main` console metadata; and
- installed `meridian --version` / `meridian --help` behavior.

The repository validator already executes the shared prepared installed
qualification runner. The Core matrix runner invokes the issue #59 operations
smoke, so normal repository qualification includes this installed boundary
rather than maintaining a parallel one-off environment.

## Responsibility split

```text
Meridian canonical state
    -> Meridian readiness + Meridian attention
    -> Core ModuleOperationsProfile
    -> Suite doctor/dashboard orchestration

Meridian owner action ID
    -> Suite owner-routing decision
    -> public Meridian launcher boundary
    -> Meridian-owned navigation/workflow

PDS workspace bytes
    -> Suite opaque backup custody
    -> copied/restored workspace bytes
    -> ordinary Meridian loaders
```

Core owns the shared interoperability contracts. Meridian owns Meridian policy,
canonical state semantics, readiness, attention, and application behavior.
Suite owns cross-module presentation, launcher orchestration, and whole-workspace
backup custody.

Issue #59 Suite operations integration — implemented and qualified.
