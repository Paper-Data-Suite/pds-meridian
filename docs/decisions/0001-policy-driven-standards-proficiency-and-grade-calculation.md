# ADR 0001: Policy-Driven Standards Proficiency and Grade Calculation

* Status: Accepted
* Date: 2026-07-28

## Context

Paper Data Suite separates the production of academic evidence from the policies used to calculate standards proficiency and Grades.

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

Those producers may publish:

* assessment scores;
* rubric results;
* criterion ratings;
* standards-aligned observations;
* written feedback;
* revision histories;
* intervention records;
* and other producer-native results.

Neither Core nor an individual producer should determine the authoritative cumulative standards proficiency or course Grade for a student.

Core cannot own those decisions without becoming coupled to grading policy. Individual producers cannot own them without duplicating policy, creating conflicting results, or gaining inappropriate authority over evidence from other modules.

Meridian therefore requires an explicit architectural decision about:

* which evidence is eligible for grading;
* how evidence is associated with standards;
* how repeated observations are selected or combined;
* how reassessment is handled;
* how standards proficiency is calculated;
* how Grade-item results are calculated;
* how results are associated with Academic Periods;
* how conventional Grades are produced when required;
* and how every derived result remains reproducible and explainable.

Standards-based grading must be supported as a first-class calculation model. It must not be reduced to a display layered over a conventional points ledger.

## Decision

PDS Meridian will own policy-driven standards proficiency and Grade calculation.

Meridian will consume authorized Core-governed registrations and Publication Records, select eligible evidence, and apply explicit, versioned grading policies to produce derived academic results.

Meridian-derived results will remain distinct from producer-native records and from Core-owned canonical registry state.

### Evidence Does Not Automatically Become a Grade

A producer publication represents evidence or a producer-owned result.

The existence of a Publication Record does not, by itself, determine:

* Grade-item membership;
* standards-evidence eligibility;
* attempt selection;
* reporting-period membership;
* category membership;
* weighting;
* standards proficiency;
* assignment Grade;
* or course Grade contribution.

Meridian must apply an explicit policy before a publication contributes to a derived academic result.

Publication validity and Grade eligibility are separate questions.

A publication may be:

* structurally valid;
* correctly registered;
* available through Core;
* and still ineligible for a particular Meridian calculation.

### Explicit Grade-Item Membership

Meridian must eventually represent whether and how registered academic work participates in Grade and proficiency calculations.

Grade-item membership must be explicit or derived from an explicit Meridian-owned policy.

It must not be inferred solely from:

* the presence of a Publication Record;
* the publication kind;
* the producer module;
* the presence of a manifest;
* a numeric field;
* a score-like capability;
* or the fact that a work was assigned.

A registered work may contribute to:

* standards proficiency only;
* a conventional Grade only;
* both standards proficiency and a conventional Grade;
* a report without contributing to a Grade;
* or neither.

The policy governing that participation must be identifiable and versioned.

### Focus Standards and Standards Evidence

Academic work may identify one or more focus standards.

Meridian must support the use of producer-published evidence associated with those standards.

A single work may:

* provide evidence for one standard;
* provide evidence for several standards;
* provide different evidence strengths for different standards;
* or provide a producer-native result that is not eligible as standards evidence.

Meridian must not require every producer to use the same native rubric, criterion structure, scale, or storage format.

Instead, producer integrations must expose sufficient shared contract information for Meridian to determine:

* which standard is addressed;
* what observation or result was produced;
* what scale or interpretation applies;
* which work and publication supplied the evidence;
* and whether the evidence is eligible under the active policy.

Meridian must preserve the source and meaning of the original producer evidence.

### Configurable Evidence-Selection Policy

Repeated observations of a standard must be interpreted under an explicit evidence-selection policy.

Meridian must support multiple policy strategies rather than embedding one universal rule.

Possible strategies include:

* most recent evidence;
* highest evidence;
* decaying average;
* weighted evidence;
* bounded evidence windows;
* replacement after reassessment;
* teacher-selected evidence;
* selected best-fit evidence;
* minimum-count rules;
* and future institution-specific strategies.

This ADR does not select one strategy as universally correct.

Each calculation must identify the evidence-selection policy that was applied.

The policy must define, as applicable:

* which evidence is eligible;
* which evidence is excluded;
* how evidence is ordered;
* how reassessment affects earlier evidence;
* how ties are resolved;
* how missing evidence is treated;
* and how much evidence is required.

### Reassessment and Attempt Handling

Meridian must support reassessment without assuming that every later attempt automatically replaces every earlier attempt.

Attempt-selection policy may consider:

* publication chronology;
* logical attempt identity;
* revision or supersession relationships;
* teacher selection;
* recency;
* highest demonstrated proficiency;
* bounded replacement rules;
* or other configured strategies.

A producer may publish multiple valid results for the same work.

Meridian determines which of those results contribute to a specific calculation.

Earlier evidence must remain available for provenance even when it is no longer selected.

### Configurable Proficiency Scales

Meridian must support configurable proficiency scales.

A four-level proficiency scale must be supported as a first-class use case.

The architecture must not assume that every course, school, or district uses:

* four levels;
* the same level names;
* the same numeric representations;
* the same thresholds;
* the same descriptors;
* or the same relationship between proficiency and a conventional Grade.

A proficiency scale may use labels such as:

* beginning;
* developing;
* proficient;
* advanced;

but those labels are configuration, not universal Meridian constants.

A scale definition must eventually identify:

* its levels;
* ordering;
* labels;
* interpretation;
* allowable source mappings;
* and version.

### Distinct Academic Concepts

Meridian must preserve distinctions among the following concepts:

1. **Producer-native result**
   The result emitted and owned by a producer module.

2. **Work performance**
   A Meridian interpretation of performance on one registered academic work.

3. **Standards evidence**
   An observation eligible to inform proficiency for a particular standard.

4. **Calculated standard proficiency**
   A policy-derived judgment about demonstrated proficiency on one standard.

5. **Grade-item result**
   The result attributed to one Grade-bearing work under the active policy.

6. **Academic Period Grade**
   A Grade calculated for a Core-defined Academic Period.

7. **Cumulative course Grade**
   A Grade calculated across the applicable course scope.

8. **Report presentation**
   The format and context in which any of the preceding results are communicated.

These concepts must not be collapsed into a single generic `score` field.

A numeric producer score is not automatically:

* a standards-proficiency level;
* a Grade-item result;
* an Academic Period Grade;
* or a cumulative course Grade.

### Insufficient and Non-Grade States

Meridian must represent meaningful non-Grade and non-proficiency states.

The eventual model must distinguish, as applicable:

* insufficient evidence;
* not yet assessed;
* missing;
* incomplete;
* excused;
* excluded;
* withdrawn evidence;
* invalid evidence;
* unavailable evidence;
* and not applicable.

These states must not automatically become zero.

A policy may explicitly assign a consequence to one of these states, but that consequence must be deliberate and visible.

For example:

* `missing` may be excluded temporarily;
* `incomplete` may remain unresolved;
* `excused` may never count against the student;
* `insufficient evidence` may prevent proficiency calculation;
* and `invalid evidence` must not contribute at all.

### Academic Periods

Meridian will use Core-owned Academic Period definitions.

Core remains authoritative for:

* school-year calendars;
* semesters;
* quarters;
* marking periods;
* terms;
* parent-child period relationships;
* date boundaries;
* and calendar revisions.

Meridian owns the policy determining how eligible work and evidence contribute to calculations associated with those periods.

Meridian must not redefine or silently reinterpret the canonical Academic Period calendar.

A calculation must eventually identify the exact Academic Period calendar revision used.

Meridian policy may determine:

* which Grade items belong to a period;
* whether evidence carries forward;
* whether cumulative proficiency spans periods;
* how late or reassessed work is assigned;
* and whether a reporting-period Grade is frozen or recalculated.

### Pure Standards-Based Grading

Meridian must support grading models in which standards proficiency is the primary academic result.

Under a pure standards-based policy:

* proficiency is calculated by standard;
* evidence-selection rules are explicit;
* insufficient-evidence states remain distinct;
* and no conventional percentage or letter Grade is required unless another policy explicitly derives one.

Standards proficiency must not be treated merely as a reformatted assignment average.

### Conventional Grading

Meridian may support conventional grading where required.

A conventional policy may calculate results using:

* points;
* percentages;
* weighted categories;
* assignment weights;
* dropped items;
* or other institution-approved rules.

Conventional grading must still use explicit Grade-item membership and versioned calculation policy.

The existence of conventional grading support must not weaken standards-based grading as an independent model.

### Hybrid Grading

Meridian may support hybrid policies that derive a conventional Grade from standards proficiency or combine standards and conventional components.

Any conversion from standards proficiency to a conventional Grade must be:

* explicit;
* configured;
* versioned;
* deterministic;
* institution-specific;
* and visible in provenance.

Meridian must not silently convert proficiency levels into percentages or letter Grades.

A hybrid policy must identify:

* the source proficiency scale;
* the conversion rule;
* any weighting among standards;
* minimum-evidence requirements;
* rounding rules;
* and the version of the conversion policy.

### Policy Versioning

Every material grading decision must be governed by an identifiable policy version.

Policies may include:

* Grade-item membership policy;
* evidence-eligibility policy;
* attempt-selection policy;
* standards aggregation policy;
* proficiency scale;
* conventional Grade policy;
* standards-to-Grade conversion policy;
* missing-work policy;
* reassessment policy;
* and rounding policy.

A policy change must not silently alter the provenance of a previously calculated or issued result.

Recalculation under a new policy must produce a result that identifies the new policy and its source evidence.

### Recalculation and Reproducibility

Meridian calculations must be reproducible.

Given the same:

* canonical registrations;
* Publication Records;
* publication and withdrawal state;
* standards mappings;
* Academic Period definitions;
* grading policies;
* evidence-selection policies;
* and authorized overrides,

Meridian should produce the same derived result.

Each calculated result must eventually preserve enough provenance to identify:

* source Publication Record IDs;
* relevant registration revisions;
* selected evidence;
* excluded evidence where material;
* applicable standards;
* Academic Period calendar revision;
* grading-policy versions;
* override state;
* and calculation time.

A later calculation may supersede an earlier calculation, but it must not erase the basis of the earlier result.

### Teacher Overrides

Meridian may support authorized teacher overrides.

An override must not mutate or erase producer-native evidence.

An override must eventually preserve:

* the derived value before the override;
* the replacement value;
* the scope of the override;
* the responsible actor;
* the time of the override;
* an optional or required rationale;
* and the policy governing override authorization.

An override may apply to:

* selected evidence;
* a standard-proficiency result;
* a Grade-item result;
* an Academic Period Grade;
* or another explicitly supported derived result.

Overrides must remain visible in provenance and reporting.

### Determinism

Meridian calculation behavior must be deterministic.

Where policy permits discretion, that discretion must be made explicit through configuration or an authorized human decision.

Meridian must define deterministic handling for:

* ties;
* equal timestamps;
* equivalent evidence;
* rounding;
* missing optional data;
* duplicate processing;
* and ordering.

Filesystem order, database row order, or nondeterministic iteration must not change a derived result.

### Producer Neutrality

Meridian must remain producer-neutral at the architectural level.

It may support producer-specific adapters or mappings, but it must not transfer a producer’s complete business logic into Meridian.

Producer modules remain responsible for:

* native record validity;
* native scoring or rubric interpretation;
* native feedback;
* and faithful publication of their results.

Meridian is responsible for:

* selecting authorized evidence;
* applying shared or configured mappings;
* aggregating evidence;
* calculating proficiency;
* calculating Grades;
* and preserving provenance.

Meridian must not silently parse arbitrary producer files to infer grading semantics.

Producer-specific evidence must enter Meridian through an explicit integration contract.

### Academic and Intervention Separation

Academic-result publications and intervention publications have different meanings.

Intervention records may contribute to:

* support reports;
* progress reports;
* instructional context;
* intervention summaries;
* or authorized decision-support views.

They do not automatically become:

* Grade items;
* standards evidence;
* assessment attempts;
* proficiency observations;
* or conventional Grade components.

Any future policy allowing a nontraditional source to influence a Grade must be explicit, narrowly defined, authorized, and documented.

The default architecture preserves academic and intervention separation.

### Derived Authority

Meridian-derived results are authoritative only within the scope of the Meridian policy and calculation that produced them.

They do not replace:

* Core’s canonical Academic Period definitions;
* Core’s academic work registrations;
* Core’s Publication Records;
* producer-native records;
* publication withdrawal state;
* or producer ownership of native semantics.

Meridian may persist derived results or snapshots in the future, but their authority must remain traceable to their source records and policies.

## Consequences

### Benefits

#### Standards-Based Grading Is Architecturally Primary

Meridian can represent standards proficiency directly rather than reconstructing it from a conventional gradebook.

This supports:

* focus standards;
* repeated evidence;
* reassessment;
* recency;
* proficiency scales;
* insufficient-evidence states;
* and standard-level reporting.

#### Results Remain Explainable

A Grade or proficiency level can be traced to:

* source publications;
* selected evidence;
* policy decisions;
* Academic Period definitions;
* and overrides.

This improves auditability and teacher trust.

#### Producers Remain Independent

ScoreForm, Quillan, Concord, and future producers can retain their own native semantics.

They need not implement cumulative grading logic.

Meridian can aggregate across producers without requiring one producer to understand another producer’s records.

#### Multiple Grading Models Are Supported

The architecture supports:

* pure standards-based grading;
* conventional grading;
* hybrid grading;
* and institution-specific policy.

Meridian is not locked into one grading philosophy.

#### Reassessment Is Explicit

Reassessment can be handled through policy rather than accidental timestamp or revision behavior.

Earlier evidence remains visible even when later evidence is selected.

#### Policy Changes Are Reproducible

Versioned policies allow Meridian to explain why two calculations using the same evidence may differ.

Previously issued results can remain historically understandable.

#### Core Remains Module-Neutral

Core does not gain grading formulas, proficiency scales, weighting rules, or student-level calculated results.

This preserves Core’s role as shared canonical infrastructure.

### Costs

#### Additional Policy Models

Meridian will require explicit models for:

* evidence eligibility;
* Grade-item membership;
* standards aggregation;
* attempt selection;
* proficiency scales;
* missing-work handling;
* conventional Grades;
* and conversions.

#### Integration Contracts Must Be Clear

Producer outputs must expose enough structured meaning for Meridian to use them safely.

Loose numeric normalization will not be sufficient.

#### Insufficient-Evidence Handling Is More Complex

Meridian cannot treat every unresolved state as zero.

Policies and interfaces must represent multiple non-Grade states accurately.

#### Versioning Increases Persistence Requirements

Calculated results must identify the policies and source evidence used.

This requires durable provenance and careful supersession semantics.

#### Teacher Overrides Require Authorization and Auditability

Overrides introduce security, authorization, and provenance requirements.

They cannot be implemented as silent data edits.

#### Hybrid Policies Can Be Difficult to Explain

Conversions from standards proficiency to conventional Grades may be institution-specific and controversial.

Meridian must make those conversions visible rather than presenting them as inherent truths.

#### Cross-Producer Mapping Requires Discipline

Meridian may need adapters or shared evidence contracts for different producer result types.

This creates integration work but avoids lossy universal normalization.

## Alternatives Considered

### Core Calculates Grades

Under this alternative, PDS Core would own standards aggregation and Grade calculation.

This was rejected because Core must remain module-neutral infrastructure.

Adding grading policy to Core would couple it to:

* proficiency scales;
* Grade-item membership;
* evidence selection;
* course policy;
* teacher overrides;
* and institution-specific reporting rules.

It would also introduce student-level derived calculations into a module whose primary responsibility is canonical infrastructure and registry authority.

### Each Producer Calculates the Course Grade

Under this alternative, ScoreForm, Quillan, Concord, and other producers would independently calculate Grades from their own records.

This was rejected because:

* no producer has authority over every other producer’s evidence;
* policies would be duplicated;
* results could conflict;
* cross-module aggregation would be fragmented;
* reassessment handling could differ by producer;
* and changing producers could change grading behavior.

Producer modules should publish faithful evidence, not own the cumulative course Grade.

### Universal Numeric-Score Normalization

Under this alternative, every producer result would be converted into one universal numeric score before aggregation.

This was rejected because it would discard important distinctions among:

* points;
* rubric ratings;
* criterion results;
* standards evidence;
* holistic ratings;
* narrative feedback;
* intervention records;
* incomplete states;
* and invalid or insufficient evidence.

A universal numeric field would create apparent interoperability by erasing meaning.

### Conventional Gradebook First, Standards View Second

Under this alternative, Meridian would first calculate a conventional points or percentage Grade and then derive standards displays from that ledger.

This was rejected because standards proficiency would become a lossy presentation over assignment totals.

That approach would make it difficult or impossible to represent:

* multiple observations per standard;
* reassessment;
* recency;
* evidence selection;
* insufficient evidence;
* and direct standard-level proficiency.

Standards-based grading must be a first-class calculation model.

### Latest Evidence Always Wins

Under this alternative, the newest observation would universally replace all earlier evidence.

This was rejected because recency is one legitimate policy, not an architectural truth.

Some contexts may require:

* highest evidence;
* multiple recent observations;
* decaying averages;
* teacher selection;
* or minimum evidence sets.

Meridian must support configurable evidence-selection policy.

### Highest Evidence Always Wins

Under this alternative, the highest demonstrated result would universally determine proficiency.

This was rejected for the same reason.

It may be appropriate in some courses but may overstate proficiency where evidence is inconsistent, outdated, or not comparable.

### Store Only Final Grades

Under this alternative, Meridian would persist only the final proficiency or Grade without preserving the selected evidence and policy provenance.

This was rejected because the result would not be reproducible or explainable.

Policy changes, publication withdrawals, corrections, and overrides would become difficult to audit.

## Follow-Up Questions

This ADR establishes architectural ownership and principles. It does not define the final implementation.

Future ADRs or issues must resolve the following questions.

### Policy Representation

* What schema represents a grading policy?
* Are policies stored as immutable revisions?
* How are policies activated for a course, section, or Academic Period?
* How are policy changes scheduled?
* Can different standards use different evidence-selection policies?

### Grade-Item Membership

* How is Grade-item membership registered?
* Does membership belong to a course configuration, work registration extension, Meridian policy, or separate Meridian record?
* Can membership vary by Academic Period?
* Can one work participate differently in standards and conventional calculations?

### Standards Identification

* Which canonical identifiers represent standards?
* How are framework versions handled?
* How are local standards or competencies represented?
* How are retired or revised standards handled?
* How does Meridian verify producer-provided standard references?

### Evidence Contracts

* What shared contract must a producer expose for standards evidence?
* How are rubric and criterion results mapped?
* How are holistic scores mapped?
* Can narrative evidence contribute without a numeric level?
* How are evidence confidence and evidence quality represented?
* How are contradictory observations handled?

### Attempt and Reassessment Identity

* How are attempts identified across publication revisions?
* What distinguishes correction, reassessment, replacement, and resubmission?
* How does withdrawal affect attempt selection?
* How are late publications assigned to Academic Periods?

### Proficiency Calculation

* Which aggregation strategies are initially implemented?
* How are scale mappings configured?
* How is insufficient evidence determined?
* How are ties handled?
* How are mixed-scale observations reconciled?
* Can proficiency be calculated hierarchically across standards?

### Conventional Grade Calculation

* Which conventional models are initially supported?
* How are points, percentages, categories, and weights represented?
* How are dropped items handled?
* How are extra-credit items represented?
* How are missing and incomplete states treated?

### Hybrid Conversion

* How are standards converted to conventional Grades?
* Can conversion occur at the standard, category, period, or course level?
* How are standards weighted?
* What rounding rules apply?
* How are minimum-evidence rules enforced?

### Academic Period Membership

* Is period membership based on due date, completion date, publication date, teacher selection, or explicit assignment?
* How are reassessments spanning periods handled?
* Can evidence carry forward?
* Can a Grade be frozen at period close?
* How are calendar revisions handled after calculation?

### Overrides

* Which roles may create overrides?
* Which result types may be overridden?
* Is a rationale mandatory?
* Can an override expire?
* Can an override itself be superseded?
* How are override permissions audited?

### Persistence

* Does Meridian persist each calculation result?
* Are results immutable snapshots or recalculable projections?
* How are superseded calculations linked?
* How long is provenance retained?
* Does Meridian publish derived Grade or report records through Core?

### Security and Authorization

* Who may view source evidence?
* Who may configure grading policies?
* Who may recalculate Grades?
* Who may issue or revoke overrides?
* How are unauthorized evidence and reports excluded?
* How are sensitive student-level results protected?

### Interfaces

* Which calculation APIs will Meridian expose?
* Which commands, services, or user interfaces are required?
* How are explanations rendered?
* How can teachers inspect selected and excluded evidence?
* How are provisional and final results distinguished?

### Testing

* What synthetic producer fixtures are required?
* How are deterministic calculations tested?
* How are policy migrations tested?
* How are provenance and override behaviors verified?
* How are standards-based and conventional models tested independently?
