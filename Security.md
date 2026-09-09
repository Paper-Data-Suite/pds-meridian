# Security Policy

PDS Meridian processes academic evidence and teacher-authored interpretation
state that may contain sensitive educational information. The v0.2 release
line includes publication/evidence diagnostics, authorization-gated protected
evidence inspection, teacher-controlled proficiency calculation, explanation
traces, planning-signal review/export, and privacy-minimal attention summaries.

Meridian v0.2 does not calculate conventional Grades, issue reports, or provide
institutional authentication or authorization policy.

## Supported versions

Security fixes for the v0.2 line target the latest `0.2.x` release.

The `0.1.1` line is historical and is not the active maintenance target.
This policy does not establish a service-level commitment.

## Reporting a vulnerability

Do not open a public GitHub issue for a suspected security vulnerability.

Use GitHub private vulnerability reporting or a private GitHub Security
Advisory for this repository.

Include only the minimum information needed to reproduce and assess the issue:

- affected component, version, branch, or commit;
- description and reproduction steps;
- expected and observed behavior;
- potential impact and prerequisites;
- suggested mitigation, when available; and
- disclosure status.

Do not include real educational data, credentials, private repository material,
exploit secrets, confidential reports, or sensitive deployment information in
public issues, pull requests, discussions, screenshots, or CI logs.

## Sensitive educational data

Use synthetic data whenever possible.

Do not publish real:

- names or student identifiers;
- email addresses or contact information;
- dates of birth;
- accommodations or intervention information;
- Grades or standards-proficiency records;
- scans, submissions, manifests, or report contents;
- school or district identifiers; or
- workstation or network-share paths.

See the [synthetic data policy](docs/development/synthetic-data.md).

## Current security-sensitive surface

The v0.2 package includes:

- exact Core and optional producer dependency/artifact qualification;
- bounded Core publication discovery and canonical verification;
- immutable projection snapshots and authorization-gated protected reads;
- teacher-authored Grade Item, membership, eligibility, attempt, reassessment,
  Standard association, mapping, proficiency, and planning policy state;
- immutable Grade Item and Academic Period proficiency result history with
  explicit current selectors;
- read-only explanation traces over exact historical provenance;
- contextual grouping-signal preview/review and final live export revalidation;
- privacy-minimal Core `grouping_signal_set_v1` export plus Meridian receipt;
- optional Core-native `grouping_signal_csv_v1` export from exact stored state;
- privacy-minimal aggregate attention through Core module operations;
- package/repository/documentation validators and installed-wheel smoke tests;
  and
- GitHub Actions release qualification.

Reports are appropriate for demonstrated issues such as:

- authorization bypass or protected-evidence disclosure;
- dependency or artifact-verification bypass;
- package-content substitution;
- path traversal, symlink escape, or unsafe temporary-file handling;
- untrusted archive handling;
- command injection in scripts or CI;
- mutation of immutable or historical academic state;
- silent current-selection substitution;
- privacy-sensitive data leaking into Core grouping signals, attention, logs,
  or diagnostics;
- source-checkout shadowing that defeats installed-package verification; or
- export occurring without the required explicit review/currentness boundary.

## Authorization boundary

Publication metadata access is not student evidence access.

Commands that list or verify publication identity and compatibility use
privacy-minimized Core/publication metadata. Protected projection/evidence
reads require a deployment-provided `PublicationAuthorizer` through Meridian's
projection-cache authorization boundary before protected snapshot bytes are
opened.

Possession of a cache key, filesystem access, package installation, a matching
student ID, or a purpose string is not authorization. A missing authorization
provider fails closed.

Base proficiency explanations and Core-facing attention do not bypass this
boundary. Optional richer evidence detail reuses the authorized diagnostics /
projection-cache path.

Meridian defines enforcement points and typed decisions but does not implement
production authentication or institutional identity, role, legal, audience, or
disclosure policy.

## Producer and Concord Artifact boundary

Meridian adapters read only producer-owned released Academic Result
manifest/reader contracts. Producer files and Core Publication Records remain
producer/Core-owned state.

The Concord v0.3.0 Academic Result adapter does not import or call Concord's
separately authorization-gated Artifact reader. Preserve:

```text
manifest authorization != Artifact authorization
evidence reference != permission to read Artifact bytes
```

Concord group-target evidence is not promoted to student evidence merely
because student identities appear in provenance context.

## Grouping-signal privacy boundary

The shared Core `grouping_signal_set_v1` is a deliberately minimal planning
interchange. Meridian-local academic provenance must not be copied into that
signal.

In particular, the Core signal must not expose raw grades, percentages, point
totals, producer-native ratings, Grade Item or Academic Period calculation
internals, attempts, reassessment state, eligibility state, mapping bodies,
teacher rationale, explanations, student names, Concord strategy/Groups, or
local filesystem paths.

Planning bands are contextual instructional-planning signals, not ability or
permanent student labels.

## Consequential export boundary

Preview, diagnostics, warning acknowledgment, review, and explanation are
distinct from export.

Core grouping-signal persistence requires an explicitly selected accepted
review plus final live currentness/eligibility revalidation. Optional CSV is
derived only from the exact stored Core signal and matching Meridian receipt.

The v0.2 path does not create Concord `GroupPlan`, `Group`, or
`GroupMembership` state.

## Later security-sensitive areas

Later Meridian work requires particular care around:

- conventional and hybrid Grade policy;
- missing-work treatment, weighting, and rounding;
- teacher overrides and precedence;
- report audiences and delivery;
- immutable reporting snapshots;
- subscriptions and notifications;
- SIS/report-card exports;
- retention and backups; and
- integration secrets.

Discovery, package installation, profile compatibility, and filesystem
readability must never be treated as authorization.

## Coordinated disclosure

Allow maintainers a reasonable opportunity to confirm, assess, correct, test,
and communicate a vulnerability before public disclosure.

Response and remediation time depends on severity, scope, and reproducibility.
This policy does not establish a guaranteed service-level agreement.

## Out of scope

The following are not security vulnerabilities by themselves:

- disagreement with an explicitly configured academic policy;
- expected differences among grading/proficiency models;
- missing features;
- unsupported deployment configurations;
- hypothetical behavior absent from the repository; or
- social-engineering claims without a demonstrated Meridian weakness.

Do not perform testing that accesses unauthorized data, disrupts service,
alters or destroys data, targets users, or violates applicable law or policy.

## Good-faith research

Good-faith research should minimize access, stop when sensitive data is
encountered, avoid persistence and destruction, report privately, and allow a
reasonable remediation opportunity.

This statement reflects repository intent and is not legal advice or a
guarantee about third-party systems or authorities.
