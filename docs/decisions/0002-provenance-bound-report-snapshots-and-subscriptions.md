# ADR 0002: Provenance-Bound Report Snapshots and Subscriptions

* Status: Accepted
* Date: 2026-07-28

## Context

Paper Data Suite separates canonical academic records, producer-native results, grading policy, report composition, and report delivery across distinct modules.

PDS Core owns shared canonical infrastructure, including:

* Academic Period calendars;
* academic work registrations;
* immutable Publication Records;
* publication series and withdrawals;
* manifest references and digests;
* shared routing identities;
* producer compatibility metadata;
* and the disposable academic registry catalog.

Producer modules such as ScoreForm, Quillan, Concord, Portia, and future Paper Data Suite modules own their native records and domain-specific interpretation.

PDS Meridian owns policy-driven aggregation and reporting.

Meridian may eventually consume authorized publications containing:

* assessment results;
* rubric and criterion results;
* standards-aligned evidence;
* calculated standards proficiency;
* Grade-item results;
* conventional Grades;
* written feedback;
* intervention information;
* progress indicators;
* and other authorized producer outputs.

Those sources may change over time through:

* new publications;
* superseding publications;
* withdrawals;
* reassessments;
* corrected producer records;
* grading-policy changes;
* Academic Period calendar revisions;
* teacher overrides;
* and report-definition changes.

A report produced from those sources must remain explainable after it has been issued.

An always-live report that silently changes whenever its inputs change cannot reliably answer:

* what information was shown;
* which source publications were selected;
* which grading policy was applied;
* which Academic Period definitions were used;
* which overrides were active;
* who the intended audience was;
* or whether the report was later refreshed, corrected, or superseded.

Likewise, a rendered document alone does not preserve enough structured provenance to explain how it was created.

Meridian therefore requires an explicit reporting model that distinguishes:

* report definitions;
* report-generation requests;
* report snapshots;
* refreshable report views;
* subscriptions;
* delivery attempts;
* and rendered artifacts.

The architecture must also preserve the semantic distinction between academic-result publications and intervention publications.

A report may present information from both domains when authorized, but the act of presenting them together must not transform intervention information into Grade evidence or academic-result data.

## Decision

PDS Meridian will use provenance-bound report snapshots as its authoritative reporting model.

A report snapshot will be a reproducible, identifiable derived result associated with:

* an explicit report definition;
* an explicit source selection;
* exact policy versions;
* exact Academic Period context;
* authorized overrides;
* generation time;
* intended audience;
* and delivery state where applicable.

Subscriptions will represent requests for repeated or condition-based report generation.

A subscription will not itself become an academic data source or an issued report.

Meridian will distinguish report composition from delivery so that calculation and provenance do not depend on one communication channel.

### Reports Are Derived Products

A Meridian report is a derived product.

It does not replace, rewrite, or mutate:

* Core-owned Academic Period definitions;
* academic work registrations;
* Publication Records;
* publication withdrawals;
* producer-native records;
* producer manifests;
* Meridian grading evidence;
* or authorized teacher overrides.

A report refers to those sources and records the policy decisions used to select and present them.

A report may summarize, aggregate, explain, or format source information, but it must preserve enough provenance to trace every material displayed result back to its origin.

### Explicit Report Definitions

Report generation must be governed by an explicit report definition.

A report definition should eventually identify, as applicable:

* report type;
* report purpose;
* intended audience;
* student, class, course, or cohort scope;
* Academic Period scope;
* included academic-result sources;
* included intervention sources;
* applicable grading policy;
* applicable evidence-selection policy;
* report-composition policy;
* authorization requirements;
* presentation requirements;
* delivery eligibility;
* and version.

A report definition is not itself a generated report.

Changing a report definition must create a new identifiable version rather than silently changing the meaning of previously issued snapshots.

A report definition may describe products such as:

* standards-proficiency reports;
* marking-period Grade reports;
* cumulative course reports;
* assignment-progress reports;
* intervention summaries;
* parent or guardian progress reports;
* teacher dashboards;
* student-facing progress reports;
* administrative reports;
* or other authorized report types.

This ADR does not define the final report-definition schema or enumerate every supported report type.

### Report Snapshots

A generated report must be represented as a snapshot with structured provenance.

A report snapshot should eventually identify:

* snapshot ID;
* report-definition ID and version;
* source Publication Record IDs;
* source publication series and withdrawal state;
* relevant academic work registration revisions;
* relevant Academic Period calendar revision;
* grading-policy versions;
* evidence-selection policy versions;
* report-composition policy version;
* authorized overrides;
* generation request;
* generation time;
* subject scope;
* intended audience;
* rendering state;
* delivery state;
* supersession state;
* and integrity metadata.

The snapshot represents the result of one report-generation observation.

It must not silently change after issuance.

A correction, refresh, or policy change must produce a new snapshot or snapshot revision linked to the earlier result.

### Structured Snapshot and Rendered Artifact

A report snapshot and its rendered artifact are distinct concepts.

The structured snapshot preserves:

* selected sources;
* derived values;
* policy versions;
* audience;
* provenance;
* and report structure.

A rendered artifact presents that snapshot through a particular format, such as:

* HTML;
* PDF;
* printable output;
* an application view;
* a data export;
* or another authorized format.

One structured snapshot may support multiple rendered artifacts.

A rendered artifact must not become the only surviving representation of the report’s provenance.

A rendered artifact should eventually identify the snapshot from which it was produced.

### Frozen Snapshots

A frozen snapshot records what was generated or issued at a particular time.

Once frozen, it must not be silently rewritten because:

* a source publication was superseded;
* a withdrawal was recorded;
* a Grade was recalculated;
* a grading policy changed;
* an Academic Period calendar was revised;
* an override was added;
* an override was revoked;
* or the report definition changed.

A frozen snapshot may later be marked:

* superseded;
* corrected;
* withdrawn from active use;
* or no longer current.

Its original contents and provenance must remain historically explainable, subject to lawful retention and deletion requirements that will be defined separately.

### Refreshable Views

Meridian may also provide refreshable report views.

A refreshable view represents the current result of applying a report definition to current authorized source state.

It is not equivalent to an issued frozen snapshot.

Refreshing a view must:

1. evaluate the current report definition;
2. select current authorized sources;
3. apply current applicable policies;
4. create a new identifiable generation result;
5. preserve its provenance;
6. and avoid altering previously frozen snapshots.

A user interface may present the latest generated result as a current view, but Meridian must preserve the distinction between:

* the latest view;
* a previously issued snapshot;
* and a superseded snapshot.

### Source Selection

Report source selection must be explicit and reproducible.

Meridian must eventually record:

* which candidate publications were considered;
* which publications were selected;
* which publications were excluded where material;
* which publication series heads were used;
* which withdrawn publications were excluded or historically retained;
* which Grade or proficiency calculations were selected;
* which intervention records were included;
* and which policy determined those choices.

A report must not depend on undocumented database ordering, filesystem ordering, or whichever publication was encountered first.

Source selection must be deterministic.

### Publication Supersession

When a Publication Record is superseded:

* previously issued report snapshots remain traceable to the source publication they used;
* current refreshable views may select the new series head under the applicable policy;
* a refreshed report creates a new result;
* and the relationship between earlier and later reports remains identifiable.

Supersession does not automatically make an earlier report fraudulent or invalid.

It means the earlier snapshot reflects an earlier source state.

The report or its metadata should make that historical status clear when relevant.

### Publication Withdrawal

When a source publication is withdrawn:

* new report generation must apply the current withdrawal policy;
* current views must not treat the withdrawn publication as ordinarily selectable;
* previously issued snapshots remain historically explainable;
* and Meridian must not silently erase the fact that the withdrawn source was previously used.

A withdrawal may require:

* a corrected report;
* a superseding snapshot;
* a warning;
* active delivery cancellation;
* or another policy-driven response.

This ADR does not require automatic deletion of all historical reports that referenced a later-withdrawn publication.

Retention, correction, and legal deletion requirements will be addressed separately.

### Grading-Policy Changes

A grading-policy change must not silently rewrite an issued report.

If the same source evidence is recalculated under a new policy:

* the new result must identify the new policy version;
* the earlier result must retain its original policy provenance;
* and any refreshed report must create a new snapshot or generation result.

A report should eventually be able to distinguish:

* source changes;
* policy changes;
* override changes;
* report-definition changes;
* and presentation-only changes.

### Academic Period Context

Reports associated with an Academic Period must identify the exact Core-owned calendar revision used.

A report must not rely only on a period label such as `Quarter 1` or `Semester 1`.

It should eventually identify:

* school year;
* Academic Period ID;
* Academic Period calendar revision;
* applicable parent period where relevant;
* and any policy governing late or reassessed evidence.

If the Academic Period calendar is later revised, an earlier report remains bound to the calendar revision used when it was generated.

### Academic and Intervention Separation

Academic-result publications and intervention publications must remain semantically distinct within reports.

A report may include both when:

* the report definition permits it;
* the intended audience is authorized;
* the information is necessary for the report’s purpose;
* and the presentation preserves the distinction.

Intervention records must not automatically alter:

* standards proficiency;
* Grade-item membership;
* Grade calculations;
* evidence selection;
* assessment-attempt selection;
* or conventional Grade conversion.

A report that includes intervention information should distinguish sections or fields such as:

* academic progress;
* standards proficiency;
* Grade information;
* intervention history;
* support status;
* recommendations;
* or other appropriately labeled domains.

Meridian must not flatten academic and intervention information into a single undifferentiated result.

### Audience-Aware Composition

Every report must be composed for an intended audience.

Possible audiences may include:

* student;
* parent or guardian;
* teacher;
* counselor;
* case manager;
* school administrator;
* district administrator;
* support team;
* or another authorized role.

The intended audience affects:

* which sources may be included;
* which fields may be displayed;
* level of detail;
* explanation depth;
* intervention visibility;
* override visibility;
* and permitted delivery channels.

A report authorized for one audience must not automatically be available to every other audience.

Audience authorization must be evaluated during report generation and, where required, again during delivery or access.

### Data Minimization

A report must include only information necessary for its defined purpose and authorized audience.

The availability of a source record does not imply that every field should appear in every report.

Report composition must support:

* field minimization;
* section minimization;
* audience-specific views;
* exclusion of unrelated producer data;
* and separation of sensitive intervention information.

Meridian must not create broad cross-module data exports by default.

### Authorization

Authorization must apply to:

* report-definition access;
* source selection;
* report generation;
* report viewing;
* snapshot retrieval;
* rendering;
* subscription management;
* delivery;
* correction;
* supersession;
* and cancellation where applicable.

A user authorized to view one source publication is not necessarily authorized to create or receive every report containing it.

A subscription must not bypass current authorization requirements.

Future implementation must define whether authorization is evaluated:

* when the subscription is created;
* when each generation occurs;
* when each delivery occurs;
* and when a stored report is later accessed.

At minimum, generation and delivery must not rely solely on stale historical authorization.

### Report Subscriptions

A report subscription represents an instruction to request report generation repeatedly or when an explicit condition occurs.

A subscription should eventually identify:

* subscription ID;
* report-definition ID and version or version-selection policy;
* subject scope;
* intended audience;
* trigger policy;
* delivery preferences;
* subscriber or responsible actor;
* authorization context;
* activation state;
* creation time;
* update time;
* and cancellation state.

A subscription does not contain authoritative Grade or academic data.

It refers to a report definition and generation policy.

### Subscription Triggers

Meridian should support explicit subscription triggers.

Potential triggers include:

* fixed schedule;
* Academic Period opening;
* Academic Period closing;
* progress-report milestone;
* new eligible publication;
* publication withdrawal;
* report-definition change;
* grading-policy change;
* teacher request;
* administrator request;
* student or guardian request where authorized;
* or another explicit event.

This ADR does not require every trigger type to be implemented initially.

Triggers must be deterministic and auditable.

A subscription must not infer significant reporting events from arbitrary filesystem activity or undocumented polling behavior.

### Scheduled Generation

A scheduled subscription may request report generation:

* daily;
* weekly;
* at a marking-period milestone;
* at a configured date and time;
* or according to another approved schedule.

The schedule should be represented explicitly.

Meridian must eventually account for:

* timezone;
* daylight-saving transitions;
* missed executions;
* retries;
* disabled subscriptions;
* and schedule changes.

A schedule change must not alter the provenance of reports generated under the earlier schedule.

### Event-Driven Generation

An event-driven subscription may request generation when a relevant state change occurs.

Relevant events may include:

* an eligible publication becoming available;
* a selected publication being withdrawn;
* a Grade calculation being completed;
* a report definition being approved;
* an Academic Period reaching a milestone;
* or an authorized manual request.

Meridian must avoid generating reports from unvalidated or incomplete source state.

Event-driven generation must not treat every producer record change as automatically reportable.

The report definition and trigger policy determine relevance.

### Idempotency

Repeated processing of the same trigger and unchanged source state must not create uncontrolled duplicate report snapshots or deliveries.

The eventual implementation should support an idempotency identity derived from appropriate inputs, such as:

* subscription;
* trigger occurrence;
* report-definition version;
* subject scope;
* source-selection identity;
* policy versions;
* and intended audience.

Idempotency must not incorrectly merge genuinely different reports.

For example, reports generated from different:

* policy versions;
* source publication sets;
* Academic Period calendar revisions;
* audience definitions;
* or override states

must remain distinct.

### Generation Requests

A report-generation request should be identifiable independently of the final report snapshot.

A request may originate from:

* a subscription;
* a manual command;
* a user interface;
* an API request;
* a scheduled job;
* or an authorized system event.

The request should eventually record:

* requesting actor or system;
* report definition;
* subject scope;
* intended audience;
* trigger;
* requested time;
* policy-selection context;
* and idempotency identity.

A request may:

* succeed;
* fail;
* be canceled;
* be superseded;
* or be determined to produce no report.

### Atomic Generation

Report generation must be atomic from the perspective of issuance.

A failed generation must not partially issue a misleading report.

Meridian should:

1. validate the report definition;
2. validate authorization;
3. capture the relevant source observation;
4. apply grading and composition policies;
5. construct the structured snapshot;
6. validate the resulting snapshot;
7. render requested artifacts;
8. finalize the snapshot;
9. and only then make the report eligible for delivery or access.

If a source changes during generation, Meridian must either:

* restart from a new coherent observation;
* or fail the generation with a stable explanation.

It must not combine source state from different observations.

### Failure Handling

A failed report generation should preserve enough diagnostic information to explain:

* which report definition was requested;
* which trigger initiated it;
* which subject scope was involved;
* which source-selection stage failed;
* which policy failed;
* whether rendering began;
* whether any delivery was attempted;
* and whether a prior valid report remains current.

Failures must not expose sensitive source data to unauthorized error channels.

A failure must not create a snapshot that appears successfully issued.

### Delivery Coordination

Meridian may coordinate report delivery, but report calculation and report delivery are distinct responsibilities.

Meridian may eventually:

* invoke an authorized delivery adapter;
* place a finalized report into a delivery queue;
* publish a report-availability event;
* provide a secure access link;
* or expose the snapshot to another authorized component.

Meridian’s calculation engine does not need to own:

* email transport;
* SMS transport;
* every notification channel;
* user-directory management;
* or all presentation interfaces.

Delivery components must not alter the report snapshot’s academic content or provenance.

### Delivery Attempts

A delivery attempt should eventually identify:

* report snapshot;
* intended recipient or audience scope;
* delivery channel;
* delivery adapter;
* attempt time;
* outcome;
* retry state;
* and failure reason where applicable.

A successful report snapshot and a successful delivery are separate facts.

A report may be generated successfully but not delivered.

A delivery failure must not invalidate the report snapshot itself.

### Multiple Delivery Formats

One report snapshot may support multiple delivery formats or presentations.

For example, the same snapshot may be:

* displayed in an application;
* rendered as PDF;
* rendered as accessible HTML;
* exported under an approved data contract;
* exported as CSV or JSON for district grading software;
* or printed.

Format differences must not silently change the underlying academic meaning.

When a format cannot represent all structured information, the limitation must be explicit.

### Accessibility

Future report rendering should account for accessibility requirements.

The structured snapshot should preserve enough semantic structure to support:

* meaningful headings;
* table relationships;
* labels;
* reading order;
* non-color indicators;
* text alternatives where applicable;
* and multiple presentation formats.

Accessibility is not merely a property of a final PDF.

It should influence the structured report model and rendering contracts.

### Report Corrections

When a previously issued report requires correction:

* the original snapshot remains identifiable;
* the corrected snapshot identifies the original;
* the reason for correction is recorded;
* delivery state is tracked separately;
* and the corrected report does not silently replace historical provenance.

A correction may result from:

* source publication correction;
* withdrawal;
* policy error;
* authorization error;
* rendering defect;
* report-definition defect;
* or manual administrative action.

The eventual model must distinguish:

* academic correction;
* policy correction;
* presentation-only correction;
* and delivery correction.

### Snapshot Supersession

A report snapshot may be superseded by another snapshot.

Supersession should eventually record:

* earlier snapshot;
* later snapshot;
* supersession reason;
* time;
* and responsible actor or automated policy.

A superseded report remains historically explainable.

A user interface may emphasize the current snapshot while still preserving authorized access to prior versions where appropriate.

### Snapshot Withdrawal

Meridian may need a mechanism to mark a report snapshot as withdrawn from active use.

Snapshot withdrawal is distinct from source-publication withdrawal.

A report may be withdrawn because:

* it was delivered to an incorrect audience;
* its source selection was invalid;
* an authorization defect occurred;
* its rendering was materially misleading;
* or policy requires active removal.

Withdrawal must not silently erase provenance.

Retention and secure deletion requirements will be defined separately.

### Provenance

Every material report result must be traceable.

A displayed proficiency, Grade, intervention indicator, narrative summary, or aggregate should be attributable to one or more of:

* source Publication Records;
* a Meridian calculation result;
* a report-composition rule;
* an authorized teacher override;
* an explicit report-definition field;
* or another documented derived operation.

Provenance should eventually support explanations such as:

* why a publication was selected;
* why another publication was excluded;
* which standards contributed;
* which Grade policy applied;
* how an override affected the result;
* why a report changed;
* and why two audiences received different presentations.

### Explainability

Meridian reports must be explainable at an appropriate level for their audience.

An administrator, teacher, student, and parent or guardian may require different explanation detail.

The architecture should support both:

* concise presentation;
* and deeper authorized provenance inspection.

Explainability does not require exposing confidential internal implementation details or information the audience is not authorized to see.

### Determinism

Given the same:

* report definition;
* source Publication Records;
* publication and withdrawal state;
* registration revisions;
* Academic Period calendar revision;
* grading policies;
* report-composition policies;
* overrides;
* audience;
* and rendering version,

Meridian should produce the same structured report snapshot.

Deterministic behavior must include:

* source ordering;
* section ordering;
* tie resolution;
* timestamp interpretation;
* duplicate suppression;
* numeric formatting;
* and stable handling of missing optional data.

### Integrity

A report snapshot should eventually have integrity metadata sufficient to detect unintended modification.

Potential mechanisms may include:

* canonical serialization;
* content digests;
* source-set digests;
* artifact digests;
* immutable identifiers;
* or signed attestations where warranted.

This ADR does not mandate a cryptographic-signature scheme.

It establishes that issued report integrity must be verifiable and linked to provenance.

### Privacy and Minimization

Meridian reports are expected to contain sensitive educational information.

Future implementation must minimize:

* source data loaded;
* data retained;
* data rendered;
* data delivered;
* and diagnostic data exposed.

A report snapshot should not include complete producer-native records when only selected derived fields are necessary.

Sensitive intervention information requires particularly careful authorization and audience selection.

### Retention

Report snapshot retention must eventually be governed by explicit policy.

Retention policy may vary based on:

* report type;
* audience;
* delivery status;
* correction state;
* institutional requirements;
* and applicable legal obligations.

This ADR does not define a universal retention period.

Retention decisions must not be inferred from technical storage convenience alone.

### Derived Authority

A Meridian report snapshot is authoritative as a record of what Meridian generated under a particular report definition and source observation.

It is not authoritative over:

* Core’s canonical registrations;
* Publication Records;
* publication withdrawals;
* producer-native records;
* canonical Academic Period definitions;
* or the underlying facts owned by another system.

A report snapshot may be authoritative as an issued communication while remaining a derived product.

Its authority depends on its:

* source provenance;
* policy provenance;
* audience;
* issuance state;
* and supersession state.

### Possible Meridian Publications

Meridian may eventually publish its own report or derived-result records through Core’s publication registry.

This ADR does not require that design.

Any future decision to publish Meridian-generated artifacts through Core must define:

* publication kind;
* manifest contract;
* source-record references;
* registration requirements;
* revision and supersession behavior;
* withdrawal behavior;
* and whether report snapshots or rendered artifacts are represented.

That decision requires a later ADR or implementation-specific architectural review.

## Consequences

### Benefits

#### Reports Remain Historically Explainable

An issued report can be understood even after:

* source publications change;
* policies change;
* calendars change;
* or a newer report supersedes it.

The exact source and policy context remains identifiable.

#### Live Views and Issued Reports Are Not Confused

Meridian can offer current refreshable views without silently changing what was previously issued.

This supports both operational usefulness and historical integrity.

#### Cross-Module Reporting Remains Safe

Meridian can combine authorized information from multiple producers while preserving:

* producer ownership;
* source semantics;
* revision history;
* and domain distinctions.

No producer must become the owner of final cross-module reports.

#### Academic and Intervention Meaning Is Preserved

Reports can include both academic and intervention information without treating intervention records as Grade evidence.

This supports useful progress reporting while preserving grading boundaries.

#### Multiple Audiences Are Supported

Audience-aware definitions allow Meridian to produce appropriately scoped reports for:

* students;
* families;
* teachers;
* support teams;
* and administrators.

Data minimization can be enforced as part of report composition.

#### Subscriptions Become Auditable

Scheduled and event-driven generation can be tied to:

* explicit definitions;
* triggers;
* authorization;
* generation requests;
* and delivery attempts.

This avoids opaque background reporting behavior.

#### Delivery Is Decoupled

Meridian can remain focused on:

* calculation;
* composition;
* provenance;
* and report finalization

while integrating with multiple delivery channels.

#### Corrections Do Not Destroy History

Corrected and superseding reports can be linked to earlier snapshots without silently rewriting prior output.

#### Idempotency Reduces Duplicate Reports

Stable generation identities can prevent repeated triggers from creating uncontrolled duplicates.

### Costs

#### Snapshot Persistence Is Required

Meridian will need durable storage for:

* report definitions;
* generation requests;
* snapshots;
* provenance;
* supersession links;
* rendering state;
* and delivery state.

#### Report Definitions Require Versioning

Changes to:

* source selection;
* presentation;
* audience;
* policy;
* or delivery behavior

must be identifiable through definition versions or equivalent immutable records.

#### Source Selection Becomes Explicit

Meridian cannot simply query current data and render it without recording which sources were used.

This increases implementation complexity.

#### Authorization Must Be Evaluated in Multiple Stages

Authorization may need to be checked during:

* subscription management;
* generation;
* access;
* rendering;
* and delivery.

Stale authorization must not silently persist forever.

#### Refresh Semantics Are More Complex

Meridian must distinguish:

* current views;
* generated results;
* issued reports;
* corrected reports;
* superseded reports;
* and withdrawn reports.

#### Delivery Tracking Adds Operational State

Report production and report delivery require separate states and failure handling.

#### Data Retention Requires Policy

Historical explainability must be balanced against:

* privacy;
* minimization;
* storage;
* and legal retention requirements.

#### Cross-Module Reports Require Careful Mapping

Combining academic and intervention information without flattening meaning requires explicit report contracts and presentation rules.

#### Rendering Must Preserve Semantic Structure

Supporting multiple formats and accessibility requires structured report models rather than one-off templates.

## Alternatives Considered

### Always-Live Reports Without Snapshots

Under this alternative, every report would display the current result of querying the latest source state.

This was rejected because an earlier issued report could become impossible to reproduce.

A Grade, proficiency level, source publication, policy, or override could change without any durable record of what was previously shown.

Always-live views may still exist, but they must not replace snapshot semantics for issued reports.

### Producers Generate Final Cross-Module Reports

Under this alternative, individual producers would create final reports containing information from multiple modules.

This was rejected because:

* a producer does not own other producers’ records;
* a producer does not own Meridian grading policy;
* authorization could become inconsistent;
* report logic would be duplicated;
* and cross-module provenance would fragment.

Producers should publish faithful domain-owned results.

Meridian should compose authorized cross-module reports.

### Flatten All Producer Data Into One Reporting Table

Under this alternative, producer records would be copied into one universal reporting table.

This was rejected because flattening would discard:

* producer semantics;
* publication identity;
* revision relationships;
* withdrawal state;
* manifest provenance;
* domain-specific structure;
* and distinctions between academic and intervention information.

A derived catalog or projection may support efficient queries, but it must not become the sole reporting authority.

### Treat Intervention Records as Grade Inputs

Under this alternative, intervention records included in a report could automatically influence standards proficiency or Grade calculation.

This was rejected because intervention publications and academic-result publications have different meanings.

Intervention context may be valuable for instructional decisions, but it must not silently become academic evidence.

Any exceptional policy must be explicit and separately authorized.

### Store Only Rendered Files

Under this alternative, Meridian would retain only PDF, HTML, or other final artifacts.

This was rejected because rendered files alone do not preserve enough structured provenance to:

* regenerate the report;
* render another format;
* explain source selection;
* verify policy versions;
* inspect overrides;
* or identify delivery-specific differences.

Rendered artifacts must remain linked to structured snapshots.

### Rewrite a Report in Place When Refreshed

Under this alternative, refreshing a report would replace the earlier stored report.

This was rejected because it destroys historical explainability and makes corrections or disputes difficult to audit.

Refreshes must produce new identifiable results.

### Subscription Is the Report

Under this alternative, a subscription record would be treated as a continuously updated report.

This was rejected because a subscription is an instruction for future generation, not a completed report or academic result.

A subscription may produce many snapshots or none.

### Meridian Owns Every Delivery Channel

Under this alternative, Meridian would directly implement all email, messaging, portal, export, and notification delivery.

This was rejected because it couples report calculation to communication infrastructure and makes secure channel integration harder.

Meridian may coordinate delivery through explicit adapters or authorized components.

### No Idempotency

Under this alternative, every trigger execution would produce a new snapshot and delivery regardless of whether anything changed.

This was rejected because retries and duplicate events could create uncontrolled duplicate reports.

Generation identity must account for meaningful source and policy state.

### Delete Historical Reports Whenever a Source Is Withdrawn

Under this alternative, source-publication withdrawal would automatically delete every report that referenced it.

This was rejected because withdrawal does not erase historical fact.

Some reports may need correction, supersession, restricted access, or deletion, but those actions require explicit report and retention policy.

## Follow-Up Questions

This ADR establishes the reporting model and ownership boundaries. It does not define the final implementation.

Future ADRs or issues must resolve the following questions.

### Report Definitions

* What schema represents a report definition?
* Are report definitions immutable revisions?
* How are definitions approved and activated?
* Can one report definition inherit from another?
* How are audience-specific variants represented?
* Which definition changes require a new version?
* How are presentation-only changes distinguished from semantic changes?

### Snapshot Storage

* What storage model holds structured report snapshots?
* Are snapshots immutable?
* How are snapshots indexed?
* How are supersession relationships represented?
* How are large reports partitioned?
* How are artifact digests associated with snapshots?
* Are snapshots stored in Meridian, Core, or both?

### Source Selection

* How are eligible Publication Records selected?
* Does Meridian store candidate and excluded source sets?
* How are publication-series heads resolved?
* How are withdrawals applied?
* How are corrected or superseded calculations selected?
* How are source-selection explanations generated?
* How are ties resolved?

### Grade and Proficiency Sources

* Does a report consume raw producer evidence, Meridian calculation snapshots, or both?
* How are provisional and final Grades distinguished?
* How are teacher overrides represented in reports?
* Can a report freeze a Grade calculation independently from the current Grade view?
* How are insufficient-evidence states displayed?

### Academic Periods

* Which Academic Period revision is selected for each report?
* How are reports handled when the calendar changes?
* Can a report span multiple periods?
* How are cumulative and period-specific sections represented?
* What happens when late evidence is assigned to an earlier period?

### Intervention Information

* Which report types may include Portia publications?
* Which audiences may view intervention information?
* How is intervention information minimized?
* How are academic and intervention sections separated?
* Can intervention information be omitted while retaining the same academic snapshot?
* How are intervention corrections and withdrawals handled?

### Authorization

* What service owns identity and role resolution?
* How are report audiences represented?
* Is authorization evaluated at generation, access, delivery, or all three?
* How are guardian relationships verified?
* How are support-team memberships represented?
* How are authorization changes applied to stored reports?
* Can access to a previously issued report be revoked?

### Subscriptions

* What schema represents a subscription?
* Which trigger types are supported initially?
* How are schedules represented?
* Which timezone applies?
* How are missed schedules handled?
* How are subscriptions paused, resumed, and canceled?
* Can a subscription follow the latest report-definition version?
* Can it remain pinned to one definition version?

### Event Processing

* Which component publishes reportable events?
* How are duplicate events detected?
* How are retries handled?
* How are out-of-order events handled?
* How are trigger occurrences identified?
* Does an event cause immediate generation or enqueue a request?

### Idempotency

* What fields form the idempotency key?
* Does a presentation-format change create a new snapshot or only a new artifact?
* Does a delivery retry reuse the same snapshot?
* When does a changed source set require a new report?
* How are manual forced regenerations represented?

### Rendering

* Which component renders reports?
* Which formats are initially supported?
* How are templates versioned?
* How is accessibility tested?
* How are localization and date formats handled?
* How are long tables, charts, and narrative sections represented?
* How are rendering failures separated from calculation failures?

### Delivery

* Which delivery adapters are needed?
* Does Meridian store recipient addresses or use another identity service?
* How are secure links generated?
* How are expired links handled?
* How are delivery receipts represented?
* How are bounce, rejection, and retry states handled?
* How is unintended delivery remediated?

### Corrections and Supersession

* Who may correct or withdraw a report?
* Which correction reasons are supported?
* Must a correction be delivered automatically?
* How are recipients notified?
* Can a presentation-only correction reuse the same structured snapshot?
* How are withdrawn reports displayed in user interfaces?

### Retention and Deletion

* How long are snapshots retained?
* How long are rendered artifacts retained?
* Are delivery logs retained separately?
* How are lawful deletion requests handled?
* Can a snapshot be cryptographically erased while retaining non-sensitive audit metadata?
* How are backups handled?

### Integrity

* Should snapshots use canonical JSON?
* Which digest algorithm is used?
* Are rendered artifacts hashed?
* Are signatures required?
* How are signing keys managed?
* How is integrity verified when reports are downloaded or delivered?

### Meridian Publications

* Should Meridian publish report snapshots through Core?
* Should rendered reports use Publication Records?
* What publication kind would apply?
* Which registration would own report production?
* How would supersession and withdrawal work?
* Would a report manifest contain structured data, rendered artifacts, or both?

### Security

* How are student-level report records encrypted at rest?
* How are report exports protected?
* How are sensitive intervention sections authorized?
* How are subscription credentials secured?
* How are delivery secrets managed?
* How are report-generation and delivery actions audited?
* How are cross-tenant or cross-class data leaks prevented?

### Testing

* What synthetic fixtures represent academic and intervention publications?
* How are snapshot reproducibility and determinism tested?
* How are authorization boundaries tested?
* How are subscription retries and duplicate events tested?
* How are source changes during generation tested?
* How are correction, supersession, and withdrawal tested?
* How are rendering and delivery failures tested?
* How are data-minimization requirements verified?
