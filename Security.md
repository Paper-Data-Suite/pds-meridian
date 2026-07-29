# Security Policy

PDS Meridian is currently in its initial architecture and documentation phase. It does not yet contain a production application or supported release.

Even at this early stage, security reports should be handled privately because Meridian is expected to process sensitive educational information, Grade calculations, standards proficiency, report snapshots, and authorized cross-module data.

## Supported Versions

No production version of PDS Meridian is currently supported.

Once Meridian has released versions, this section will identify which versions receive security updates.

## Reporting a Vulnerability

Do not open a public GitHub issue for a suspected security vulnerability.

Use GitHub’s private vulnerability-reporting feature or open a private GitHub Security Advisory for this repository.

When reporting a vulnerability, include as much of the following information as can be shared safely:

* the affected component or document;
* the relevant version, branch, or commit;
* a clear description of the vulnerability;
* reproduction steps;
* expected and observed behavior;
* potential impact;
* known prerequisites;
* suggested mitigation, when available;
* and whether the issue has been disclosed elsewhere.

Do not include any of the following in public issues, pull requests, discussions, or screenshots:

* real student information;
* credentials;
* access tokens;
* private keys;
* session data;
* private repository contents;
* exploit details;
* confidential report output;
* or sensitive deployment information.

Allow the maintainers a reasonable opportunity to investigate and coordinate remediation before public disclosure.

The repository owner should enable GitHub private vulnerability reporting in the repository security settings.

## Sensitive Educational Data

Do not use real student data when demonstrating or reproducing a vulnerability.

Use synthetic data whenever possible.

When synthetic data cannot reproduce the issue, thoroughly redact:

* names;
* student identifiers;
* email addresses;
* dates of birth;
* accommodations;
* Grades;
* standards-proficiency records;
* intervention records;
* report contents;
* and any other identifying or sensitive information.

A security report should include only the minimum data necessary to explain the vulnerability.

## Security-Sensitive Areas

Future Meridian implementations are expected to include security-sensitive behavior involving:

* authentication and authorization;
* student-record access;
* teacher and administrator permissions;
* report audience selection;
* source-Publication Record access;
* Grade and standards-proficiency integrity;
* grading-policy configuration;
* teacher overrides;
* override authorization and provenance;
* report-definition authorization;
* report snapshot provenance;
* report delivery;
* subscription triggers;
* exported files;
* cross-module integrations;
* secrets used by integrations;
* and protection against unauthorized recalculation or report generation.

Particular care is required anywhere Meridian could:

* expose information to the wrong audience;
* calculate a Grade from unauthorized or invalid evidence;
* omit relevant withdrawal or supersession state;
* accept an unauthorized override;
* alter report provenance;
* deliver a report more broadly than intended;
* or combine academic and intervention information without preserving their separate meanings and access requirements.

## Response Process

The maintainers will attempt to:

1. acknowledge the report privately;
2. review the available reproduction information;
3. assess severity and scope;
4. request additional information when needed;
5. identify affected versions or components;
6. coordinate remediation;
7. validate the correction;
8. and communicate appropriate disclosure timing.

Response and remediation times depend on the nature, severity, and reproducibility of the report.

This policy does not establish a guaranteed service-level agreement.

## Coordinated Disclosure

Please avoid public disclosure until the maintainers have had a reasonable opportunity to:

* confirm the issue;
* understand its impact;
* develop a correction or mitigation;
* test the correction;
* and notify affected users or maintainers where necessary.

When public disclosure is appropriate, the maintainers may coordinate:

* the timing of disclosure;
* the technical description;
* affected-version information;
* mitigation guidance;
* and acknowledgement of the reporter.

## Scope

Security reports are appropriate for issues such as:

* unauthorized access to student or report data;
* authentication or authorization bypass;
* exposure of credentials or secrets;
* Grade or proficiency manipulation;
* unauthorized teacher overrides;
* report-audience leakage;
* report-delivery vulnerabilities;
* provenance tampering;
* unsafe file handling;
* injection vulnerabilities;
* path traversal;
* insecure deserialization;
* dependency vulnerabilities with a demonstrated Meridian impact;
* and vulnerabilities in future APIs, command-line tools, exports, or integrations.

The following should normally use a public GitHub issue, provided no sensitive information is included:

* ordinary software defects;
* documentation corrections;
* feature requests;
* user-interface problems;
* grading-policy disagreements;
* expected policy behavior questions;
* calculation-rule proposals;
* and problems that do not create a confidentiality, integrity, or availability risk.

When uncertain whether a report is security-sensitive, use the private reporting channel.

## Out of Scope

The following are not, by themselves, security vulnerabilities:

* disagreement with an explicitly configured grading policy;
* expected differences between standards-based and conventional Grade calculations;
* missing product features;
* unsupported deployment configurations;
* reports based entirely on hypothetical behavior that does not exist in the repository;
* and social-engineering claims without a demonstrated Meridian weakness.

Do not perform testing that:

* accesses data without authorization;
* disrupts services;
* destroys or alters data;
* sends unsolicited communications;
* degrades availability;
* targets users;
* or violates applicable law or policy.

## Good-Faith Security Research

Good-faith security research should:

* avoid harm;
* respect privacy;
* use the minimum access necessary;
* stop when sensitive data is encountered;
* avoid persistence;
* avoid data destruction;
* report findings privately;
* and provide maintainers a reasonable opportunity to respond.

The maintainers intend to work constructively with researchers who follow these principles.

This statement reflects the repository’s intent and is not legal advice or a guarantee regarding third-party systems, organizations, or authorities.

## Repository Status

PDS Meridian currently contains architectural and repository documentation only.

Future implementation work should update this policy as Meridian gains:

* supported releases;
* runtime services;
* persistence;
* APIs;
* report-generation capabilities;
* delivery integrations;
* deployment guidance;
* and a formal security-support lifecycle.
