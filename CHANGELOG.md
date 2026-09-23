# Changelog

## Unreleased

- Issue #57 teacher-facing main-menu foundation: adds a low-information-density
  eight-task Meridian menu contract over stable symbolic workflow identities,
  shared Core B/M/Q navigation semantics, application-owned clear/redraw helpers,
  concise teacher help, injected task routing, and clean nested/terminal unwind
  behavior. Read-only Review New Evidence and Manage Grade Items controllers now
  reuse the #41 application services, keep exact identifiers behind bounded
  technical drill-down where possible, and preserve the deployment-provided
  protected-evidence authorization boundary by failing closed when no authorizer
  is available. The public entry switch remains deferred until all primary task
  controllers are composed.

- Issue #56 reusable Export Profiles and local Grade/report exports: immutable
  class-local profile revisions with explicit CAS current selection now drive a
  closed source-field registry over exact frozen #55 ReportingSnapshots.
  Snapshot-only exports avoid roster access; roster-backed profiles bind only
  selected Core roster fields for exact snapshot students and preserve Core
  display-name semantics. Deterministic UTF-8 CSV/TSV previews preserve frozen
  Decimal values and nonnumeric state, bind exact outgoing rows/bytes and
  diagnostics, and require exact preview identity at commit. Explicit local file
  or copyable-text export uses non-overwrite/exact-replay recovery semantics and
  creates immutable roster-aware ExportReceipts without claiming SIS/LMS or
  external-system acceptance. Direct `meridian reporting` commands expose the
  bounded profile/preview/commit/receipt surface; package qualification now
  requires the complete #56 runtime and updates active Quillan compatibility to
  Quillan v0.10.1.

- Issue #55 immutable ReportingSnapshot core runtime: bounded v1 report
  definitions and explicit build requests now freeze exact #54 Grade/report
  observations into Meridian-owned canonical snapshots with two-level digest
  identity, strict historical reload, typed deep provenance, privacy-safe
  class-local storage, explicit digest-bound current-use selection with CAS,
  optimistic whole-report currentness revalidation, predecessor/correction
  relationships, and a real #55 -> #54 comparison handoff that reuses the
  existing semantic comparison engine. The architecture and distribution guards
  now cover the complete #55 runtime, bounded development CLI, adversarial and
  historical qualification, and isolated installed-wheel/fresh-process smoke;
  repository-wide BV validation remains the final completion gate.

- Issue #54 Grade/report preview explanations: deterministic read-only current
  Grade previews now explain exact conventional, standards-based, and hybrid
  persisted results; exact historical policy/activation, family formula and
  participation, non-Grade-state consequences, Decimal rounding, #53 override
  applicability, and effective Grade provenance; and optimistic reread detects
  moving current authority instead of returning mixed observations. Compact
  privacy-minimal `GradePreviewObservation` values feed explicit deterministic
  report rows and snapshot-neutral prior-observation comparison without creating
  #55 ReportingSnapshot or export state. Source-level regression covers all
  families, report/comparison behavior, and adversarial currentness; installed
  candidate-wheel qualification uses exact Core 0.6.3 + ScoreForm 0.11.0 +
  Quillan 0.10.0 + Concord 0.3.0, proves an applicable 105.25 override, whole-
  workspace immutability, and fresh-process deterministic reproduction.

- Issue #53 teacher Grade overrides and effective Grade precedence: immutable
  teacher decisions now bind one exact selected final Academic Period Grade
  result from the `conventional`, `standards_based`, or `hybrid` family by exact
  revision and SHA-256. Numeric replacement uses finite nonnegative Decimal
  semantics without a hidden 0-100 clamp. Canonical privacy-minimal append-only
  override history keeps writing separate from explicit CAS current selection;
  the teacher lifecycle rejects audit-free historical rollback, represents
  withdrawal as another immutable decision, and requires deliberate new
  authoring for correction/reactivation. Exact source currentness remains
  separate from selection, old overrides never float onto later recalculations,
  expected non-applicability is structured, and corrupt canonical state fails
  closed. Read-only effective Grade resolution preserves exact base, selected
  override, applicability, effective value, and `base`/`override`/`none` source
  provenance for #54/#55. Source-level all-family adversarial regression plus an
  isolated Core 0.6.3 + ScoreForm 0.11.0 candidate-wheel lifecycle proves
  write-versus-select, fresh-process active authority, immutable withdrawal,
  fresh-process return to base precedence, `pip check`, and source/result byte
  immutability.

- Issue #52 bounded hybrid Grade calculation: one exact activated
  `hybrid` policy now reassembles the accepted #50 conventional and #51
  standards-based component inputs directly under its embedded configurations
  instead of consuming standalone Grade-result histories. Calculated components
  contribute exact unrounded Grades; blocked components remain blocking;
  insufficient components follow exact `insufficient_evidence` treatment;
  explicit exclusion renormalizes active weight; calculated zero retains weight;
  and final rounding occurs once with no hidden 0-100 clamp. Immutable hybrid
  result revisions use SHA-bound history, explicit CAS selection, commit-time
  full-basis reassembly, historical dependency verification, and freshness that
  distinguishes conventional-input from proficiency-result drift. Source-level
  ScoreForm/Quillan/Concord acceptance plus installed Core 0.6.3 + ScoreForm
  0.11.0 + Quillan 0.10.0 fresh-process qualification preserve producer/v0.2
  source immutability while Concord remains optional. Teacher overrides are
  implemented by the issue #53 entry above.

- Issue #51 standards-based Grade calculation: exact activated
  `standards_based` policy now consumes only explicitly selected/current #35
  Academic Period proficiency for participating Standards, applies exact
  policy-owned level-to-Decimal Grade conversions and weights, renormalizes the
  active weighted mean after exclusions, preserves explicit-zero weight without
  manufacturing calculated evidence, enforces `minimum_calculated_results`,
  performs final-only rounding, and introduces no hidden 0-100 clamp. Immutable
  Grade-result revisions use SHA-bound history plus explicit CAS selection and
  pure freshness across calendar, activation, policy, proficiency-result, and
  algorithm changes. Source-level ScoreForm/Quillan/Concord qualification and
  installed Core 0.6.3 + ScoreForm 0.11.0 + Quillan 0.10.0 fresh-process
  acceptance preserve producer/v0.2 source immutability while Concord remains
  optional.

- Issue #50 conventional points/percentage Grade calculation: exact activated
  conventional Grade policies now consume exact Academic Period/calendar scope,
  exact Grade Item membership, canonical evidence eligibility, and existing
  #30/#31 attempt/reassessment authority to calculate total-points, weighted-item,
  and weighted-category Grades with exact Decimal arithmetic and final-only
  rounding. Only `NativePointValue` is conventional points; policy-owned
  `possible_points` must match points-based producer denominators. Results are
  immutable SHA-bound histories with explicit CAS selection and pure freshness
  diagnostics. Released ScoreForm v0.11.0 acceptance covers authorization through
  explicit reassessment, persistence, selection, fresh-process reproduction, and
  producer-source immutability; Quillan v0.10.0 and Concord v0.3.0 regressions
  preserve scaled/nonstudent evidence as non-points.

- Issue #49 versioned Grade-policy models and storage: immutable canonical
  `conventional`, `standards_based`, and bounded `hybrid` policy revisions;
  exact Grade Item/scale/standard dependencies; explicit Decimal weighting,
  non-Grade state treatment, reassessment authority, and final rounding;
  SHA-256-bound canonical storage with CAS family-current selection; and a
  separate immutable Core Academic-Period activation history with explicit
  `unconfigured`, `deactivated`, and `activated` resolution. GradePolicy family
  current != GradePolicy activation, and #49 performs no Grade calculation.

- Issue #48 v0.3 Grade-preview and ReportingSnapshot architecture: accepted
  explicit Grade-policy/calculation authority, advisory Grade-preview semantics,
  immutable override precedence, Meridian-owned immutable ReportingSnapshots,
  coherent snapshot generation, snapshot/export separation, teacher-controlled
  local transfer, official-system non-authority, and latest-release
  requalification. The reviewed baseline is Core v0.6.3, ScoreForm v0.11.0,
  Quillan v0.10.0, Concord v0.3.0, and released Meridian v0.2.0.


## 0.2.0 — 2026-09-07

### Added

- Issue #46 v0.2.0 release audit: skeptical policy, fairness, privacy, history, interoperability, workflow, explanation, packaging, and v0.3-boundary review completed with zero substantive blockers; release preparation promotes the package to 0.2.0 while final post-merge artifact hashes remain pending.

- Issue #45 installed proficiency and signal-export acceptance without Concord:
  one connected isolated-wheel acceptance from real released ScoreForm v0.11.0
  and Quillan v0.10.0 producer publications through exact Core v0.6.3,
  installed Meridian projection, explicit Grade Item membership/eligibility,
  ScoreForm attempt selection and reassessment, Standard association,
  source-scoped mappings, persisted/explained #34 Grade Item and #35 Academic
  Period proficiency, #37-#40 grouping-signal policy/derivation/preview/review,
  immutable privacy-minimal Core `grouping_signal_set_v1`, canonical Core JSON
  and `grouping_signal_csv_v1` round trips, and a fresh-process persisted-history
  reload. The contributing student is exported while the deliberately
  insufficient second roster student remains noncontributing with no sentinel
  band. Producer-owned source/manifests and original Core Publication Records
  are byte/digest stable across the full workflow. The dedicated smoke installs
  no `pds-concord`, has no Concord wheel parameter, and proves `concord` remains
  unimportable, while repository-wide validation retains exact Concord v0.3.0
  adapter qualification. The new smoke/tests/documentation are sdist-guarded
  and do not enlarge the runtime wheel or unconditional dependency set.

- Issue #44 ScoreForm/Quillan/Concord cross-producer proficiency scenarios:
  source-level qualification of the released ScoreForm v0.11.0, Quillan
  v0.10.0, and Concord v0.3.0 academic-result contracts through Meridian's
  existing teacher-controlled Grade Item and Academic Period proficiency
  pipeline. Acceptance preserves repeated attempts, native non-score states,
  exact source-signature/scale mappings, student/nonstudent Concord targets,
  explicit reassessment, deterministic mixed-producer calculation, Core
  correction/withdrawal history, and exact #42 historical/current traces.
  Boundary guards prove `nonstudent_target` anti-circularity, producer-neutral
  proficiency runtime/dependency direction, optional producer readers, and
  synthetic-only scenario identities. The installed proficiency and
  signal-export acceptance is completed by issue #45 above.

- Issue #43 Meridian proficiency attention summaries: deterministic read-only
  workspace/class attention with stable #41 task routing, canonical planning and
  Academic Period currentness, privacy-minimal Core v1 module-operations
  adaptation, and deterministic `meridian attention` text/JSON. Protected
  evidence authorization is never bypassed to populate attention. Focused
  installed-wheel acceptance uses only exact Core 0.6.3 plus the candidate
  Meridian wheel, validates Core provider discovery/invocation, keeps readiness
  absent, proves successful-empty versus unavailable, keeps producer/Concord
  packages absent, passes `pip check`, and verifies zero provider/CLI writes.

- Issue #42 proficiency and planning-export explanation/trace views: five
  deterministic read-only text/JSON trace targets covering exact Grade Item and
  Academic Period proficiency, content-addressed planning derivation, exact
  preview/review state, and one exact Meridian-generated Core grouping signal.
  The trace layer verifies digest-bound #33-#40 provenance, preserves explicit
  historical/current selection semantics, distinguishes academic
  noncontribution from integrity failure, reconciles every exported Core band
  against its exact #38 derivation, and adds optional authorization-gated
  evidence-detail availability without opening raw producer evidence by default.
  Focused installed-wheel acceptance uses only Core 0.6.3 plus the candidate
  Meridian wheel outside the source checkout and proves deterministic output,
  historical traceability, producer/Concord independence, Core signal
  minimality, and zero trace-induced writes.

- Issue #41 task-oriented teacher workflows: seven independently invocable
  `meridian workflow` tasks over canonical #27-#40 services, preserving explicit
  teacher actor provenance, authorization, immutable revision/write versus
  current-selection boundaries, read-only calculation previews, CAS-protected
  selection, fail-closed preview/commit drift, and producer-neutral controllers.
  Create Planning Signal now composes #37-#40 through derivation, #39
  preview/diagnostics, warning acknowledgment, accepted review, explicit review
  selection, final live export revalidation, immutable Core
  `grouping_signal_set_v1` plus privacy-minimal Meridian receipt, and optional
  Core-native `grouping_signal_csv_v1` from exact stored Core state, with no
  Concord runtime dependency or GroupPlan/Group/GroupMembership creation.

- Issue #40 immutable Core/CSV grouping-signal export: explicit selected-review eligibility and final currentness revalidation, pure #38-to-Core projection, Core roster diagnostics, immutable Core persistence, digest-bound Meridian export receipts with partial-write recovery, and optional Core-native `grouping_signal_csv_v1` complete-signal round-trip with non-overwriting file semantics and no Concord dependency.

- Issue #39 grouping-signal preview and diagnostics: deterministic content-addressed previews over exact #38 derivations, read-only currentness, structured coverage/tie/noncontributor diagnostics, immutable teacher review revisions with exact warning acknowledgments and explicit selection, live acceptance revalidation, and a read-only teacher projection with transient Core roster display names. Previewing and accepting do not export; Core/CSV export remains issue #40.
- Current unreleased Concord qualification updated to exact v0.3.0
  (`pds-concord==0.3.0`) while preserving Concord v0.2.0 as the released
  Meridian v0.1.1 historical baseline. The v0.3.0 academic-result manifest,
  public reader, and publication-profile modules are byte-identical to their
  v0.2.0 counterparts, so the adapter's projection semantics remain unchanged.
- Deterministic content-addressed grouping-signal generation from one exact Core
  roster, one explicitly selected #37 policy, exact selected/current #35
  Academic Period proficiency results, and exact rebuilt current #35 input basis.
- Rich privacy-minimal per-student derivation provenance preserving calculated,
  missing, and insufficient states without raw grades, percentages, evidence
  details, student names, or Concord planning strategy.
- Immutable class-local grouping-signal derivation storage using canonical JSON,
  SHA-256 sidecars, exact replay, content-addressed `gsd_<fingerprint>` identity,
  bounded reads, locking, and fail-closed path/symlink/tamper validation.
- Workspace generation orchestration with structured `no_selected_policy`,
  `missing_result`, `insufficient_evidence`, `stale_result`,
  `selected_result_mismatch`, and `current_basis_unavailable` blockers while
  reusing #35 freshness semantics and writing no Core grouping signal or CSV.
- Isolated installed-wheel #38 generation acceptance using only exact Core
  v0.6.3 plus the candidate Meridian wheel, exercising the persisted
  Grade Item -> #34 -> #35 -> #37 -> #38 calculated path, deterministic
  replay, and explicit absence of Core signal writes and Concord.
- Teacher-controlled grouping-signal derivation policy over one exact #35
  Academic Period proficiency basis, with an explicit planning dimension,
  teacher-defined contiguous proficiency-scale-position bands, fixed
  `same_level_same_band` tie handling, and independent `noncontributing`/
  `blocking` handling for missing and insufficient results.
- Canonical immutable grouping-signal policy storage with SHA-256 sidecars,
  contiguous revision history, exact replay/conflict semantics, explicit
  compare-and-swap `current.json` selection, historical reselection, and exact
  Core class/Academic Period/standard plus #35 policy/scale dependency checks.
- Focused, hardening, integration, package-boundary, read-only-import, and
  isolated installed-wheel qualification for #37, explicitly proving that policy
  creation/selection does not assign students, create a Core grouping signal,
  export CSV, or require Concord.
- Formal adoption of Core's neutral immutable `grouping_signal_set_v1` as
  Meridian's sole shared planning-signal interchange, qualified against exact
  Core v0.6.3 while preserving `pds-core>=0.6.3,<0.7` and introducing no direct
  Meridian-to-Concord runtime dependency.
- Focused qualification of Core's typed signal model/canonical JSON,
  `grouping_signal_csv_v1`, immutable exchange storage and canonical signal-byte
  digest, and workspace-aware roster diagnostics, including partial coverage,
  exact student identity, immutable replay/conflict semantics, and the
  distinction between upstream `source.snapshot_digest` and Core's signal
  digest.
- Isolated installed-wheel grouping-signal acceptance using only exact Core
  v0.6.3 plus the candidate Meridian wheel, explicitly proving Concord is absent
  and that #36 adds contract adoption rather than production derivation or
  export behavior.
- Academic Period standards-proficiency aggregation over exact immutable #34
  Grade Item result snapshots and exact #28 membership provenance, with
  explicit `direct` and `descendants` scope over one exact Core calendar
  revision and deterministic `highest`, `lowest`, `median`, and `mode`
  strategies.
- Explicit always-blocking `period_scope_mismatch` handling for mixed sibling,
  outside-target, calendar-revision, and school-year mismatches without date
  or current-period inference.
- Separate `missing_result`, #34 `insufficient_evidence`, and calculated low
  proficiency states, with independent noncontributing/blocking policy for
  missing and insufficient results.
- Immutable SHA-256-bound Academic Period proficiency policy/result histories,
  explicit compare-and-swap current selection, deterministic replay and
  explanations, pure freshness diagnostics, package/sdist guards, and isolated
  installed-wheel acceptance.
- Current unreleased ScoreForm qualification updated to exact v0.11.0,
  preserving the existing `scoreform_academic_work_v1`,
  `scoreform_academic_result_manifest_v1`, `academic_results`, and public
  reader projection semantics while retaining v0.10.0 as the released
  Meridian v0.1.1 historical baseline.
- Pure deterministic Grade Item-level standards-proficiency calculation over
  exact #33 aggregation inputs, exact proficiency-scale/policy revisions, and
  algorithm version 1, with explicit `highest`, `lowest`, `median`, and `mode`
  strategies and structured insufficient-evidence/tie behavior.
- Immutable SHA-256-bound standards-proficiency calculation-policy and result
  histories with canonical JSON, exact embedded aggregation inputs, explicit
  compare-and-swap `current.json` selection, historical reselection, and
  deterministic calculation fingerprints/explanations.
- Pure standards-proficiency freshness diagnostics distinguishing
  `inputs_changed`, `policy_changed`, `scale_changed`, and `algorithm_changed`
  without mutating history or automatically recalculating/selecting results.
- Integration acceptance proving calculate -> persist -> explicit select ->
  reload -> reproduce -> stale-input detection, including zero-performance
  input remaining `insufficient_evidence` rather than zero/lowest proficiency.
- Canonical teacher/policy standards-evidence association decisions over exact
  projection sources and durable Core standard IDs, with explicit
  producer-declared/explicit bases, immutable SHA-256-bound revision history,
  and compare-and-swap current selection.
- Deterministic bounded Grade Item/student/standard/scale aggregation inputs
  preserving exact upstream references, mapped performance, native non-score
  states, and closed explainable exclusions without proficiency arithmetic.
- Core v0.6.3 standards-framework resolution and current release qualification,
  plus Quillan v0.10.0 exact-reader qualification with unchanged adapter
  projection semantics.

- Canonical immutable teacher-defined proficiency scales with ordered criterion-referenced
  levels, explicit proficiency thresholds, SHA-256-bound revision history, and
  compare-and-swap current selectors without fixed four-level semantics.
- Producer-neutral native-value mapping profiles with exact source signatures and
  explicit `exact_scalar`, `exact_native_scale`, and `raw_points` modes; mapped,
  unmapped, unsupported, and native-state outcomes remain distinct.
- Exact native-scale snapshot binding, non-inverting ordered mappings, denominator-bound
  raw-point ranges without percentage normalization, and package/installed-smoke
  coverage preserving ScoreForm, Quillan, and Concord semantic separation.

- Canonical immutable reassessment policy and student relationship decision
  records over one exact operative #30 attempt-selection decision, with explicit
  `retain`, directed `replace`, semantic `combine`, and explicit `recency` modes.
- Exact contributing-attempt provenance, preserved replaced history, deterministic
  combination groups, explicit recency order, and fail-closed multi-attempt
  `no_decision` behavior without numeric ranking or reduction.
- SHA-256-bound reassessment policy/decision history with explicit compare-and-swap
  current selectors, #30 and #31 policy staleness resolution, single/none
  pass-through states, and Quillan/Concord non-applicability that preserves
  producer-native correction and supersession semantics.

- Canonical immutable attempt-selection policy and student decision records with
  explicit-only selection semantics, bounded zero/one/set cardinality, and
  independent SHA-256-bound policy/decision revision history.
- Producer-neutral exact attempt observation identity over one immutable
  projection snapshot, plus deterministic candidate derivation from exact #29
  `operative_included` eligibility revisions without score or recency ranking.
- Explicit compare-and-swap policy/decision selection, stale
  membership/policy/eligibility/candidate resolution, ScoreForm
  `multiple_attempts` applicability, and explicit Quillan/Concord
  non-applicability without fabricated attempts.

- Canonical immutable evidence-eligibility decision records scoped to one exact
  Grade Item and projection-snapshot evidence source, with distinct `included`,
  `excluded`, `pending`, `unsupported`, `superseded`, and `withdrawn` semantics.
- Exact source provenance binding Core work/publication identity, projection
  `cache_key`, snapshot SHA-256, and evidence `item_id`, plus exact included
  Grade Item membership revision/digest provenance.
- SHA-256-bound eligibility history with deterministic source keys, explicit
  compare-and-swap `current.json` selection, source-lifecycle resolution,
  authorization-gated evidence validation, and fail-closed storage safety.

- Immutable Grade Item membership decisions with explicit `included`/`excluded`
  state, exact Grade Item revision/digest provenance, exact Core Academic Work
  Registration revisions, exact Academic Period Calendar revisions, teacher
  attribution, and historical supersession.
- Canonical membership storage beneath each Grade Item with SHA-256-bound
  revisions, explicit compare-and-swap `current.json` selection, deterministic
  relationship queries, Core-backed dependency validation, and fail-closed path
  and integrity checks.
- Academic Period assignment that binds Core `AcademicPeriodRef` plus exact
  calendar revision without date-based inference, hierarchy propagation, or
  publication-driven membership.

- Immutable Meridian Grade Item revisions with stable logical identity, closed
  purpose/status contracts, exact reserved weighting metadata, and reusable
  Core registered-work revision references used by the separate membership layer.
- Canonical Grade Item persistence under each Core class with contiguous
  immutable revision history, SHA-256 sidecars, bounded integrity-checked reads,
  explicit `current.json` selection, compare-and-swap updates, and fail-closed
  path/symlink/storage validation.
- Grade Item model/storage documentation and focused regression coverage that
  preserves the boundary between Grade Item definition, membership, evidence
  eligibility, proficiency, and later Grade calculation.

## 0.1.1 — 2026-08-18

### Added

- Cross-producer synthetic ingestion acceptance covering ScoreForm v0.10.0,
  Quillan v0.9.0, and Concord v0.2.0 together in one Core workspace, including
  semantic separation, cache isolation, multiple Academic Periods, diagnostics,
  authorization isolation, deterministic replay, and failure privacy.
- Cross-producer acceptance documentation confirming that no new runtime,
  cache-schema, grading-policy, or producer-contract changes were required.

- Exact optional `pds-concord==0.2.0` adapter using Concord's released
  consumer-neutral Academic Result reader, dynamic capability derivation,
  non-individualized Group Scores, exact target ownership/version, rich native
  Scoring Scales, Score history, Evidence Link and Moderation provenance, and
  explicit unevaluated eligibility.
- Concord release-wheel authentication, installed adapter smoke validation,
  exact package-extra validation, and producer-neutral evidence/cache/diagnostic
  support for non-student evidence.
- Read-only `meridian publications list` and `meridian publications verify`
  diagnostics with bounded Core discovery, canonical reload, exact producer
  compatibility, adapter support, and reader readiness reporting.
- Authorization-gated `meridian evidence inspect` and `meridian evidence explain`
  diagnostics over exact immutable projection snapshots, including deterministic
  filters, typed value output, existing `EvidenceEligibility`, and `cache.*`
  current-use explanations without new grading policy.
- Producer-neutral `meridian.diagnostics` runtime models, deterministic text/JSON
  rendering, installed-wheel diagnostic smoke coverage, and security/package
  validation for the new read-only command surface.

- Exact optional `quillan==0.9.0` adapter using the released public reader,
  native writing-review states and scale, deterministic private IDs, public
  producer provenance, explicit composition, and unchanged cache boundary.
- Quillan wheel authentication, real-reader integration coverage, installed
  adapter smoke validation, and exact release-wheel CI setup.

- Exact optional `scoreform==0.10.0` adapter using the released public reader,
  deterministic projection, explicit registry composition, and native
  provenance for all three ScoreForm result origins.
- ScoreForm wheel authentication, Core-to-cache integration coverage, installed
  adapter smoke validation, and exact release-wheel CI setup.

- Installable `pds-meridian` package at version `0.1.1`.
- Required `pds-core>=0.6,<0.7` runtime dependency.
- Side-effect-free `meridian` command with help and version output.
- Strict typing, linting, tests, cross-platform CI, package checks, and isolated
  wheel smoke testing.
- Exact authentication of the official Core v0.6.0 wheel used by baseline CI.
- Synthetic-data policy and privacy-safe Core-contract fixtures.
- Reusable documentation and repository validation tooling.
- Immutable `meridian.evidence` inventory models with exact Core provenance,
  producer-native targets, result kinds, scales, non-score states, projection
  identity, and explicit eligibility status.
- ScoreForm-shaped and Quillan-shaped synthetic inventory tests that preserve
  attempts, question states, review dispositions, and native scale identity
  without importing either producer package.
- Immutable `meridian.adapters` interface, exact contract key, descriptor,
  projection request, explicit registry, and stable fail-closed errors.
- Lazy producer-reader distribution checks and strict validation that projected
  inventories retain the requested Core provenance and selected projection
  identity.
- Synthetic adapter tests covering exact no-fallback selection, capability
  rejection, reader availability, controlled failures, and contract violations.

- Immutable `meridian.ingestion` models for bounded discovery, canonical
  publication context, publication-series observation, authorization, and
  prepared adapter requests.
- Core Academic Catalog candidate discovery that never promotes catalog rows to
  canonical authority or rebuilds derived state automatically.
- Exact canonical Publication Record, referenced/current registration, series,
  and withdrawal reload with deterministic candidate-drift rejection.
- Core-owned producer compatibility evaluation followed by exact Meridian
  adapter selection and non-importing producer-reader readiness checks.
- Explicit deployment authorization before manifest access, Core path/digest
  verification, bounded immutable byte loading, and in-memory SHA-256 handoff.
- Final canonical-state rechecking that rejects withdrawal, supersession,
  registration, disappearance, or integrity changes during preparation.
- Synthetic ingestion tests covering catalog failures, drift, registration,
  historical and withdrawn series state, compatibility, authorization ordering,
  manifest integrity and bounds, race detection, and no adapter invocation.
- Exact evidence mapping conversion preserving native scalar types, scales,
  non-score states, provenance, eligibility, and deterministic order.
- Immutable projection snapshots with canonical JSON, exact cache identity,
  digest-bound storage, bounded reads, locking, exact replay, and explicit
  nondeterminism failures.
- Fresh authorization before persisted cache reads and read-only current-state
  assessment for supersession, withdrawal, registration, profile, adapter,
  reader, manifest, and authorization changes.

### Fixed

- Projection-cache replay nondeterminism now compares canonical serialized
  inventory bytes rather than Python object equality, preserving
  serialization-significant distinctions such as signed zero and timezone-offset
  representation.
- Projection-cache reads now bind the freshly authorized purpose/student scope
  before protected snapshot bytes are opened.
- Release-facing package and CLI descriptions now state only the implemented
  publication-ingestion and typed-evidence diagnostics surface.

### Release qualification

- Added frozen-upstream dependency-direction verification, explicit
  source-distribution boundary validation, source-tree-isolated installed-wheel
  smoke environments, and one-environment ScoreForm/Quillan/Concord coexistence
  qualification.
- Added the durable v0.1.1 foundation release-audit record and direct regressions
  for audit-discovered release blockers.

The package does not yet implement the remaining Portia/Vitrine producer adapters,
eligibility or selection policy, proficiency, Grades, or reports.
