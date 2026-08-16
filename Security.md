# Security Policy

PDS Meridian has an installable pre-release development package but no supported
production release. The current package provides read-only publication
diagnostics and authorization-gated inspection of existing Meridian projection
snapshots; it does not calculate Grades or generate reports.

Security reports should still be handled privately because Meridian is expected
to process sensitive educational information in later implementation stages.

## Supported versions

No production version is currently supported.

The `0.1.1.dev0` package is a development foundation and does not establish a
security-support lifecycle or service-level commitment.

## Reporting a vulnerability

Do not open a public GitHub issue for a suspected security vulnerability.

Use GitHub private vulnerability reporting or a private GitHub Security Advisory
for this repository.

Include only the minimum information needed to reproduce and assess the issue:

- affected component, version, branch, or commit;
- description and reproduction steps;
- expected and observed behavior;
- potential impact and prerequisites;
- suggested mitigation, when available;
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
- school or district identifiers;
- workstation or network-share paths.

See the [synthetic data policy](docs/development/synthetic-data.md).

## Current security-sensitive surface

The current development package includes:

- Python package metadata and dependency declarations;
- a console script and `python -m` entry point;
- privacy-minimized publication metadata diagnostics;
- authorization-gated persisted-evidence inspection and cache assessment;
- Core wheel authentication and installed-package verification;
- repository, documentation, and package validators;
- build and smoke-test automation;
- GitHub Actions workflows.

Reports are appropriate for demonstrated issues such as:

- dependency or artifact-verification bypass;
- package-content substitution;
- path traversal or unsafe temporary-file handling in validation tooling;
- untrusted archive handling;
- command injection in scripts or CI;
- unintended filesystem mutation during import or baseline CLI use;
- credential or private-data disclosure;
- source-checkout shadowing that defeats dependency verification.

## Diagnostic authorization boundary

Publication metadata access is not student evidence access.

Commands that list or verify publication identity and compatibility use
privacy-minimized Core/publication metadata and do not open producer manifests.
Commands that inspect or explain an existing projection snapshot may expose
student evidence and therefore require a deployment-provided
`PublicationAuthorizer` through the existing `read_projection_cache` boundary
before cache-file access.

Possession of a cache key, filesystem access, package installation, a matching
student ID, or a purpose string is not authorization. The stock Meridian console
application ships no production allow-all authorizer and provides no unsafe
bypass. A missing authorization provider fails closed.

Meridian defines enforcement points and typed decisions but does not implement
production authentication or institutional identity, role, legal, audience, or
disclosure policy.

## Future security-sensitive areas

Later Meridian implementation will require particular care around:

- authentication and authorization;
- student-record and source-publication access;
- producer code loading;
- manifest verification and parsing;
- Grade and proficiency integrity;
- grading-policy configuration;
- teacher overrides;
- report audiences and delivery;
- snapshot provenance;
- subscription triggers;
- exports, retention, and backups;
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

- disagreement with an explicitly configured future grading policy;
- expected differences among grading models;
- missing features;
- unsupported deployment configurations;
- hypothetical behavior absent from the repository;
- social-engineering claims without a demonstrated Meridian weakness.

Do not perform testing that accesses unauthorized data, disrupts service, alters
or destroys data, targets users, or violates applicable law or policy.

## Good-faith research

Good-faith research should minimize access, stop when sensitive data is
encountered, avoid persistence and destruction, report privately, and allow a
reasonable remediation opportunity.

This statement reflects repository intent and is not legal advice or a guarantee
about third-party systems or authorities.
