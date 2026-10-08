# Producer reader-contract compatibility — Issue #111

Status: Slice 1 architecture and dependency audit. **No runtime acceptance changes.**

## Authority boundaries

The identities below are independent; matching one does not imply matching another.

| Identity | Authority | Example |
| --- | --- | --- |
| Producer distribution/version | Exact installed code and projection replay/cache identity | `scoreform` / `0.12.1` |
| Manifest contract | Canonical serialized producer evidence | `scoreform_academic_result_manifest_v1` |
| Public reader contract | Stable public reader API, model shape, exceptions and semantics | `scoreform_academic_result_reader_v1` (proposed) |
| Meridian projection contract | Consumer-side mapping into neutral evidence | adapter projection contract `1` |
| Exact qualification artifact | Historical evidence of tested release, wheel, hash | exact SHA-256 recorded during release audit |

**Exact release artifacts prove what Meridian tested. Reader contracts determine what Meridian may consume.** Exact producer distribution versions still belong in `ProjectionIdentity` and cache keys, even when the same reader contract is supported across versions.

A declared reader contract is not publication authorization. Keep Core publication/profile compatibility, manifest path containment and SHA-256 verification, reader validation, projection validation, source currentness and teacher authorization independently enforced.

## Current reader dependency inventory

Observed in Meridian's `main` adapters at the Slice 1 baseline (`848c0c959dab69314f58c856f31e58c3c3eceeac`); suggested reader-contract names are proposals, **not yet declared by released producers**.

| Adapter | Public reader entry point | Manifest / Academic Work contracts | Exact legacy wheel version | Additional consumer surfaces |
| --- | --- | --- | --- | --- |
| ScoreForm | `scoreform.academic_result_reader.read_academic_result_manifest` | `scoreform_academic_result_manifest_v1` / `scoreform_academic_work_v1` | `scoreform==0.12.1` | `AcademicResultManifest`, `Attempt`; assignment questions and student attempts/responses; source snapshots and standards/profile identity |
| Quillan | `quillan.academic_result_reader.read_academic_result_manifest` | `quillan_academic_result_manifest_v1` / `quillan_academic_work_v1` | `quillan==0.10.5` | `AcademicResultManifest`, `StudentResult` and manifest-owned review/rating, source snapshot and evidence structures |
| Concord | `concord.academic_result_reader.read_academic_result_manifest` | `concord_academic_result_manifest_v1` / `concord_academic_work_v1`; source `concord_activity_v1` | `pds-concord==0.3.0` | `AcademicResultManifest`, criterion/scales/scores/moderation/evidence-link models **and** `concord.academic_result_manifest.derive_manifest_capabilities` |

Proposed public reader contract identities (not yet advertised by the released producers):

- ScoreForm: `scoreform_academic_result_reader_v1`.
- Quillan: `quillan_academic_result_reader_v1`.
- Concord: `concord_academic_result_reader_v1`.

### Direct manifest attributes referenced

This list records direct `manifest.<attribute>` access (nested public model access also occurs and must be covered by reader v1 contract tests):

- ScoreForm: `assignment`, `contract_version`, `generated_at`, `producer_module_id`, `record_set`, `source_snapshot`, `students`, `work`.
- Quillan: `assignment`, `contract_version`, `generated_at`, `producer_module_id`, `record_set`, `source_snapshot`, `students`, `work`.
- Concord: `activity_context`, `contract_version`, `generated_at`, `moderation_records`, `producer_module_id`, `projection`, `record_set`, `score_evidence_links`, `scores`, `scoring_scales`, `source_activity`, `work`.

### Public reader audit findings

All three producer source readers currently expose `read_academic_result_manifest(value: bytes)`, require **exact** immutable `bytes`, deserialize and validate the producer's canonical manifest, and expose distinct public reader error classes (base, validation, decode, not-found). The Meridian adapter lazily imports each reader during projection rather than registry discovery. Reader imports and contract-agreement checks must continue to remain separate from metadata-only compatibility discovery.

- **Already public/stable surface to qualify:** canonical immutable-bytes reading and returned typed manifest models; producer-owned reader error hierarchy.
- **Needs producer documentation and installed-wheel contract tests:** complete nested model attributes consumed by Meridian, versioned public reader contract identity, mutation-free/workspace-free semantics, imported helper stability, manifest-identity and exception stability across releases.
- **Potential hardening:** Concord `derive_manifest_capabilities` is imported from the manifest module rather than reader module; confirm its explicit supported consumer contract or expose a stable reader-module facade without changing producer semantics.
- **Must not become a dependency:** internal manifest construction helpers, workspace files, producer CLI menus, selection/grading policies, or producer imports of Meridian.

Meridian presently catches import failures separately from reader/projection execution failures; the later diagnostic model must distinguish import, execution, manifest-contract disagreement and projection-contract failure without leaking student data.

## Transitional compatibility rules (future slices; not enabled by this slice)

1. Prefer producer-profile metadata declaring an exact supported public reader contract; explicit unsupported or invalid metadata **fails closed**.
2. Only when reader metadata is **absent**, accept a historically qualified `(distribution, exact version)` pair: `scoreform/0.12.1`, `quillan/0.10.5`, `pds-concord/0.3.0`.
3. Never infer compatibility from distribution name, import success, newer/nearby version, or manifest contract alone.
4. Never use exact qualification artifact lists as a runtime compatibility allowlist.
5. Retain exact installed distribution version in the persisted projection identity; do not migrate historical snapshots solely to record reader-contract metadata.
6. Preserve Core-only deployments and the existing #110 teacher-facing support abstraction. Blocked publications remain discoverable even if not actionable.

## Sequencing / handoff

- **Slice 1:** this document and source-contract guard tests only; no runtime behavior changes.
- **Slice 2:** Core's optional metadata-only reader-support declaration (backward compatible), then old/new producer-profile tests. Release Core before depending on its added metadata.
- **Slice 3:** Meridian reader runtime identity, reader contract identity, compatibility state/reason codes.
- **Slice 4:** explicit bounded legacy exact-version table preserving the 0.3.1 qualified combinations.
- **Slice 5:** contract-first compatibility; invalid/unsupported declarations never fall through to legacy.
- **Slice 6:** exact version remains projection/cache identity, test same-contract/different-version behavior.
- **Slice 7:** publish richer technical diagnostics while preserving #110 presentation boundaries.
- **Slice 8:** relax optional extras only after actual upstream contract-advertising releases, without guessing versions.
- **Slices 9–12:** six installed matrices, released wheels (not sibling editables), adversarial cases, exact wheel hashes, documentation/release acceptance.

Do not rewrite v0.3.0/v0.3.1 historical evidence and do not import producer readers during profile discovery.
