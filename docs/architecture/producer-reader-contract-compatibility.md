# Producer reader-contract compatibility — Issue #111

Status: Slice 3 compatibility-model baseline. Core v0.6.5 and all three
academic-result producer reader contracts are released. **Runtime producer
acceptance remains legacy exact-version-only until Slice 4.**

## Authority boundaries

The identities below are independent; matching one does not imply matching another.

| Identity | Authority | Example |
| --- | --- | --- |
| Producer distribution/version | Exact installed code and projection replay/cache identity | `scoreform` / `0.13.0` |
| Manifest contract | Canonical serialized producer evidence | `scoreform_academic_result_manifest_v1` |
| Public reader contract | Stable public reader API, model shape, exceptions and semantics | `scoreform_academic_result_reader_v1` |
| Meridian projection contract | Consumer-side mapping into neutral evidence | adapter projection contract `1` |
| Exact qualification artifact | Historical evidence of tested release, wheel, hash | exact SHA-256 recorded during release audit |

**Exact release artifacts prove what Meridian tested. Reader contracts determine what Meridian may consume.** Exact producer distribution versions still belong in `ProjectionIdentity` and cache keys, even when the same reader contract is supported across versions.

A declared reader contract is not publication authorization. Keep Core publication/profile compatibility, manifest path containment and SHA-256 verification, reader validation, projection validation, source currentness and teacher authorization independently enforced.

## Released restart baseline

Core v0.6.5 is now the minimum active Meridian Core runtime and exposes metadata-only `PublicationReaderSupport` plus exact `lookup_publication_reader_support(...)` lookup. Core never imports or invokes the producer reader during metadata discovery.

The producer-side prerequisites are released:

| Producer | Released artifact used as restart authority | Manifest / Academic Work contracts | Declared public reader contract |
| --- | --- | --- | --- |
| ScoreForm | `scoreform 0.13.0` | `scoreform_academic_result_manifest_v1` / `scoreform_academic_work_v1` | `scoreform_academic_result_reader_v1` |
| Quillan | `quillan 0.10.6` | `quillan_academic_result_manifest_v1` / `quillan_academic_work_v1` | `quillan_academic_result_reader_v1` |
| Concord | `pds-concord 0.3.2` | `concord_academic_result_manifest_v1` / `concord_academic_work_v1`; source `concord_activity_v1` | `concord_academic_result_reader_v1` |

Concord v0.3.2 preserves the reader and manifest contracts introduced by v0.3.1 while reconciling the shared ZXing-C++ 3.x dependency used alongside ScoreForm v0.13.0.

Portia v0.2.0 is not a Meridian #111 producer prerequisite: it advertises no publication-producer capability in that release.

## Existing reader dependency inventory

The completed Slice 1 audit remains authoritative for what Meridian consumes from each producer public model. All three readers expose `read_academic_result_manifest(value: bytes)`, validate canonical immutable manifest bytes, and return producer-owned typed public models. Meridian lazily imports them during authorized projection rather than during profile discovery.

Direct manifest attributes used by the existing adapters remain:

- ScoreForm: `assignment`, `contract_version`, `generated_at`, `producer_module_id`, `record_set`, `source_snapshot`, `students`, `work`.
- Quillan: `assignment`, `contract_version`, `generated_at`, `producer_module_id`, `record_set`, `source_snapshot`, `students`, `work`.
- Concord: `activity_context`, `contract_version`, `generated_at`, `moderation_records`, `producer_module_id`, `projection`, `record_set`, `score_evidence_links`, `scores`, `scoring_scales`, `source_activity`, `work`.

Concord also uses the public `derive_manifest_capabilities` helper. Its released reader contract and producer qualification remain the source of producer semantics; Meridian does not reimplement Concord validation.

## Slice 2 boundary

Slice 2 adopts Core v0.6.5 as Meridian's active Core floor and may observe exact reader metadata through Core's public lookup API. It **does not yet** replace the existing exact producer-version acceptance gate.

Therefore, after Slice 2:

```text
Core reader metadata: observable
Meridian contract compatibility model: not yet authoritative
legacy exact producer versions: still the runtime acceptance rule
new contract-advertising producer versions: still rejected until Slice 4
```

That temporary state is deliberate. It proves Meridian can build and test against the released Core API without accidentally broadening producer acceptance before the compatibility result model and precedence rules exist.

## Slice 3 compatibility model and bounded legacy path

Slice 3 introduces an explicit semantic split:

```text
ProducerReaderRuntimeIdentity
    distribution_name
    installed_distribution_version

ProducerReaderContractIdentity
    manifest_contract_version
    reader_contract_version

ProducerReaderCompatibility
    mode
    support_state
    stable reason_code
    runtime_identity
    contract_identity
```

Stable compatibility modes are `contract`, `legacy_exact`, `unsupported`, and
`unavailable`. The bounded legacy table is now explicit on each adapter
descriptor:

| Producer distribution | Legacy exact version | Declared supported reader contract |
| --- | --- | --- |
| `scoreform` | `0.12.1` | `scoreform_academic_result_reader_v1` |
| `quillan` | `0.10.5` | `quillan_academic_result_reader_v1` |
| `pds-concord` | `0.3.0` | `concord_academic_result_reader_v1` |

In Slice 3, contract identities are descriptive adapter capability only.
`resolve_producer_reader_version(...)` still delegates to the bounded legacy
path, so ScoreForm 0.13.0, Quillan 0.10.6, and Concord 0.3.2 remain rejected.
Contract-first metadata precedence is deliberately deferred to Slice 4.

## Transitional compatibility rules for later slices

1. Prefer producer-profile metadata declaring an exact supported public reader contract; explicit unsupported or invalid metadata fails closed.
2. Only when reader metadata is absent, accept a historically qualified `(distribution, exact version)` pair: `scoreform/0.12.1`, `quillan/0.10.5`, `pds-concord/0.3.0`.
3. Never infer compatibility from distribution name, import success, newer/nearby version, or manifest contract alone.
4. Never use exact qualification artifact lists as a runtime compatibility allowlist.
5. Retain exact installed distribution version in persisted projection identity and cache keys.
6. Preserve Core-only deployments and the Issue #110 teacher-facing support abstraction. Blocked publications remain discoverable even if not actionable.

## Sequencing / handoff

- **Slice 1:** architecture/dependency audit — complete at `f44dae711d1dfe1317d147bfbbd9d4a70f3e4122`.
- **Slice 2:** Core v0.6.5 floor, exact Core reader-metadata observation, current qualification baseline — complete at `0c5c35b44345b5774628536a1982bc13f530c694`.
- **Slice 3:** Meridian reader runtime/contract identity, compatibility state/reason codes, bounded legacy exact table — this slice.
- **Slice 4:** contract-first acceptance of the three released reader contracts; explicit metadata precedence; exact package version remains projection/cache provenance.
- **Slice 5:** diagnostics, Issue #110 integration, and optional dependency relaxation.
- **Slices 6-16:** teacher reporting suite, installed cross-producer qualification, release audit, and Meridian release as described by Issue #111.

Do not rewrite v0.3.0/v0.3.1 historical release evidence and do not import producer readers during profile discovery.
