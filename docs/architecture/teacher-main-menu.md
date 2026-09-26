# Teacher-facing Meridian main menu

Issue #57 makes Meridian's interactive teacher application the normal installed
entry point while preserving every existing academic, reporting, and export
authority boundary underneath it.

## Eight-task application surface

Bare `meridian`, explicit `meridian menu`, bare `python -m meridian`, and
`python -m meridian menu` enter the same teacher application:

```text
1. Review New Evidence
2. Manage Grade Items
3. Review Proficiency
4. Preview Grades
5. Overrides
6. Snapshots
7. Export
8. Explain

H. Help
Q. Quit
```

Menu numbering is presentation only. Internal routing uses stable symbolic task
identities. Named direct CLI commands remain noninteractive and continue to own
recovery, automation, qualification, and exact power-user surfaces.

## Shared navigation contract

Meridian uses `pds_core.menu_navigation`; it does not define competing meanings
for the Paper Data Suite navigation controls.

```text
B. Back      -> return one logical teacher-menu level
M. Main Menu -> unwind the current workflow to Meridian's main menu
Q. Quit      -> exit the interactive Meridian application cleanly
```

Ctrl+C and EOF also unwind without a traceback. The main menu omits B and M
because no higher Meridian screen exists. `H. Help` is concise, contextual, and
never becomes academic state.

## Clear/redraw and information density

The application clears/redraws when a teacher changes task or stage. A routine
screen retains only the information required for the current choice. Opaque
IDs, revisions, digests, storage paths, raw JSON, and deep provenance do not
lead ordinary screens.

## Technical details / provenance

Exact identity is not discarded. Where useful, read-only
`T. Technical details / provenance` exposes the canonical references underneath
a teacher-readable presentation. Consequential confirmation screens may show
exact transaction identity when preview-to-commit, replay, or compare-and-swap
safety requires it.

The invariant is:

```text
human-readable display != canonical authority
low information density != lost provenance
technical drill-down != workflow mutation
```

## Consequential actions

A numbered menu choice is never permission to write. Where the canonical service
supports preview/currentness/CAS protection, the teacher menu preserves that
boundary:

```text
collect explicit scope
-> build canonical preview
-> review consequence
-> explicit typed confirmation
-> final currentness / CAS revalidation
-> existing canonical commit/select/export service
```

Writing an immutable revision does not silently select it. Selecting a revision
does not silently perform a later export. Missing, unavailable, pending, or
insufficient academic state is never silently converted to numeric zero.
Teacher actor identity is supplied explicitly and is never inferred from the OS,
Git configuration, filesystem ownership, or student identity.

## Mapping existing capabilities into the menu

The menu is an orchestration layer over already implemented services:

```text
Review New Evidence
  -> #27-#33 / #41 evidence eligibility, attempts, reassessment, standards

Manage Grade Items
  -> #27-#28 / #41 Grade Item and work-membership workflows

Review Proficiency
  -> #33-#35 proficiency plus the complete #41 Create Planning Signal flow

Preview Grades
  -> #49-#54 Grade-policy, calculation, current-result, and explanation services

Overrides
  -> #53 immutable override authoring, selection, withdrawal, and freshness

Snapshots
  -> #55 Reporting Definition, freeze, inspect, compare, and current-use selection

Export
  -> #56 Export Profile, exact snapshot export preview/commit, and ExportReceipt

Explain
  -> existing Grade, proficiency, planning, snapshot, and export explanation views
```

The nested Create Planning Signal route remains deliberately staged:

```text
selected #37 policy
!= #38 derivation
!= #39 preview
!= teacher review
!= selected review
!= #40 Core grouping_signal_set_v1
!= optional Core-native CSV
```

No Meridian planning-signal menu action creates Concord `GroupPlan`, `Group`, or
`GroupMembership` state.

## Session context and authority

Any menu context is transient convenience only. It cannot become a source of
academic truth, replace exact canonical identity, authorize protected evidence,
or override currentness checks. Protected evidence continues to require the
deployment-provided authorization capability immediately before protected bytes
are opened or revalidated.

The interactive application owns navigation, presentation, bounded prompting,
and routing. Canonical services continue to own Grade policy semantics,
proficiency calculation, override precedence, ReportingSnapshot semantics,
export semantics, publication currentness, evidence eligibility, Core roster
identity, and immutable storage.

## Direct CLI parity

Meaningful durable capabilities retain direct CLI routes. `meridian --help`,
`meridian --version`, and every explicit named command remain deterministic and
noninteractive: they do not clear the screen, pause for Enter, call interactive
`input()`, or consume menu-only session state.

## #58 and #59 boundaries

Issue #57 introduces no new Grade/report attention taxonomy. That belongs to
#58. It also introduces no suite doctor, backup, suite-wide attention aggregation,
or suite navigation ownership; those remain #59/suite-shell concerns.

## Installed qualification

Issue #57's installed smoke runs outside the source checkout in a fresh virtual
environment and installs the candidate Meridian wheel with authenticated released
PDS dependencies. It proves:

- `pip check` passes;
- `meridian`, `meridian menu`, `python -m meridian`, and
  `python -m meridian menu` all launch the teacher application and Q exits 0;
- launch/quit creates no workspace or Meridian academic state;
- installed navigation can traverse
  `main -> Review Proficiency -> Create Planning Signal -> B -> M -> Q`;
- `--help`, `--version`, and a named direct command remain noninteractive; and
- menu modules resolve from the installed wheel rather than the source checkout.

Representative canonical v0.2/v0.3 workflow durability remains covered by the
existing installed proficiency, Grade/report, ReportingSnapshot, and export
smokes that run in repository validation. The teacher menu composes those same
services rather than creating parallel implementations.

## Final compatibility recheck

The final #57 compatibility recheck uses the newest compatible released sibling
contracts:

```text
pds-core     0.6.3
scoreform    0.11.0
quillan      0.10.2
pds-concord  0.3.0
```

Quillan v0.10.2 is a selected-review read-performance patch. Its release states
that it introduces no assignment, submission, review, feedback, diagnostic,
Academic Work, Academic Result, publication, routing, or PDS2 schema changes;
therefore Meridian's public Academic Result reader boundary remains compatible.
Meridian still pins one exact authenticated Quillan reader version so projection
provenance records one exact producer-reader identity.
