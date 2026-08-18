# Synthetic data policy

Meridian processes educational records and must use synthetic information in
public source code, tests, examples, issue reproduction material, CI artifacts,
and package-validation fixtures.

## Required practice

Use obviously synthetic identifiers such as:

```text
synthetic_class_2026
synthetic_assignment_alpha
synthetic_record_set
synthetic_profile
fixture_contract_1
```

Prefer impersonal identifiers over realistic names. Keep fixtures compact and
limited to the contract behavior being tested.

## Prohibited repository content

Do not commit:

- real student, teacher, guardian, or administrator names;
- student IDs, roster exports, email addresses, or contact information;
- real school, district, class, or course identifiers;
- Grades, proficiency results, accommodations, or intervention information;
- scans, submissions, answer sheets, writing samples, or report exports;
- producer manifests containing real records;
- credentials, tokens, private keys, session data, or private URLs;
- usernames, home-directory paths, workstation paths, or network-share paths;
- private issue attachments or confidential deployment information.

A value is not safe merely because it has been partially redacted. Replace the
entire identity and surrounding context with synthetic data whenever possible.

## Producer-contract fixtures

Core-owned synthetic producer fixtures demonstrate Core architecture. They are
not Meridian-owned producer contracts.

Meridian adapter and cross-producer tests may use the exact released producer
public models, fixture builders, and readers needed to create valid synthetic
manifest bytes. Shared synthetic identities may be parameterized across
producers when a scenario deliberately tests semantic separation.

Do not copy private workspaces or create hand-maintained shadow producer
schemas. Producer-native semantics remain owned by the producer contract even
when Meridian projects them into producer-neutral evidence models.

## Failure diagnostics

Tests and validation scripts must not dump manifest bodies or educational data
when parsing fails. Prefer stable error categories, field names, and synthetic
identifiers.
