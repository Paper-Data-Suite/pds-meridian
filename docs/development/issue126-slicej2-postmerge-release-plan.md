# Meridian #126 J2 — accepted installed workflows and next release candidate

**Status:** candidate acceptance reconciled, **not** a publish/merge authorization.
**Exact merged baseline:** `698903fa1db4ad43c32664eb64211d69ba3f987c` (November 23, 2026).
**Machine-readable ledger:** `issue126-slicej2-a1-a18-ledger.json`. The J1 ledger remains immutable historical source-stage evidence.

## Accepted installed synthetic teacher scenarios

1. **Correction (0/6 -> 6/6):** Synthetic 29 x 6 ScoreForm publication; teacher-reviewed original/corrected attempts; #30 corrected Attempt 2 selected, Attempt 1 preserved, one final #122 receipt; fresh independent readback excludes historical Attempt 1 from current Standards use. Source publication unchanged.
2. **Finding 4 wording and positive retake:** Human confirmed the two revised prompts are understandable. An independent installed, cancel-only menu replay confirmed `Which attempt was the original?`, `Which attempt is the corrected version?` and both numbered/point-labelled choices. **Limitation:** original operator session transcript omitted all four strings; the original FAIL_OR_INCOMPLETE report remains retained, while the qualified reconciliation result is `PASS_WITH_TRANSCRIPT_LIMITATION`. Separately, the teacher selected an independent synthetic retake (4/6 original, 5/6 second sitting), selected both attempts and chose #31 `replace`, specifically Attempt 2 replaces Attempt 1. Fresh-process readback confirmed one #30 revision, one #31 revision, two final receipts and Standards selected-items-only continuation.
3. **Deliberate interrupted save and exact restart:** Fresh disposable 29 x 6 workspace; controlled installed process exit **73** after #31 immutable write/receipt checkpoint and before #31 selection CAS. Fresh read-only inspection reported `WRITTEN_NOT_CURRENT_READY`; #30 already current, #31 written-but-not-current, the original two receipts available. A single explicit case-sensitive `RESUME` in the original-receipt-only menu selected the original #31 revision. Fresh independent verification reported **`candidate_interrupted_save_gate: PASS`**, unchanged source, no duplicate #30/#31 revisions, no replacement receipts, and verified Standards continuation. A deliberate process exit is not physical loss-of-power certification.

All operator scenarios used **synthetic data only**. The installed Meridian wheel was locally built, **unpublished**, and noneditable; SHA-256 `070eb11636830027b746e788f138a59f31487d0604e40e4c29a29684e2073024`. Package code was based on merged source SHA above. Its `0.4.2` internal label is **not** equivalent to the **published** v0.4.2 wheel (SHA-256 `484f0ba3d7ca47d392bae26573c299eb02089d23a5caa3bd11c3ce3ddb45ead5`). Do not upload the local candidate under a published version or represent it as D3.

## D0–D4 and distribution boundaries

- **D0/D1:** Source contracts and targeted native installed acceptance are recorded. Core #237 source-only symbols cannot be treated as the installed Core 0.6.6 capability.
- **D2:** Published Core 0.6.6 supports the qualified plain/default header/navigation fallback. A newly published Core shared-header/`:notes` symbol contract is **NOT ATTESTED**; it is not a blocker for the existing fallback path.
- **D3:** A newly versioned, officially released, independently downloaded Meridian wheel with authenticated original wheel SHA-256 and installed six-matrix qualification remains **NOT ATTESTED**.
- **D4:** Suite native launcher and exact mixed-wheel foreground/return integration remains **NOT ATTESTED**. Synthetic CLI/menu calls are not a Suite launcher test.
- **Other separate evidence:** Physical ScoreForm scanning/OMR and producer-owned causal facts are untested; Report 9 issues **#133/#134** remain separately owned; no Grade/SIS/LMS writes have been certified.

## Critical version-migration finding

`pyproject.toml` declares a dynamic version; its value comes from `meridian/_version.py`. The repository's **active** release guards and installed scripts still pin `0.4.2`: e.g. `scripts/check_package.py`, `scripts/check_sdist.py`, `tests/test_version.py`, `tests/test_v040_release_preparation.py`, `tests/test_v031_release_preparation.py`, `tests/test_issue117_release_candidate_contracts.py`, and installed smoke scripts. Changing `_version.py` alone would break packaging and/or CI. The local J2 preflight enumerates all active Python occurrences for the subsequent migration.

**J2 changes are intentionally evidence-only.** They do not bump the version or publish anything. The proposed next software version is **0.4.3**, subject to exact pin-migration and release notes review. The new release will contain merged teacher workflow work from **#123, #124, #125, and #126**, not just the final #126 slice. Historical v0.4.2 release notes/audit, hashes, tags, and security advisory are not to be rewritten.

## Ordered J3 release-candidate procedure

1. On the J2 reconciled branch/commit, inventory **all active exact 0.4.2 assertions, smoke scripts, artifact checkers**, and package-inventory contracts; keep historical v0.4.2 strings in retrospective release records. Verify source and official previous-release provenance before editing.
2. In a **separate guarded version migration**, update `_version.py`, current `check_package.py`, `check_sdist.py`, version assertions, installed smoke scripts and any current release-inventory tests consistently to **0.4.3**. Add **v0.4.3 candidate** release notes covering #123–#126, limitations, Core fallback and exact producer dependency floors. Add notes to `check_sdist.REQUIRED_MEMBERS` and document/inventory checks without weakening historical membership obligations. Update changelog Unreleased only as appropriate; preserve v0.4.2 history. Do not claim release hashes before building.
3. Run **focused version/package tests first**, then the existing *complete* `scripts/validate_repository.py` with official Core 0.6.6, ScoreForm 0.13.0, Quillan 0.10.6, Concord 0.3.2 archives. The final validator covers full pytest, Ruff check/format, strict mypy, docs, wheel/sdist/Twine, dependencies and all six installed matrices. Avoid repeated full-repo runs before the migration is ready.
4. Commit/push a reviewable PR only after local qualification, obtain **8/8 GitHub Actions jobs on the exact final PR head SHA** (Ubuntu/Windows × Python 3.11–3.14), retain exact runs and skips, and reconcile A1–A18 before any merge authorization.
5. After explicit review/merge decision, build/release from the authorized exact merged source tree, create version tag, publish authentic wheel/sdist, independently download and verify SHA-256/bytes against the prepublication artifacts, then conduct D3 installed acceptance. No unpublished wheel may masquerade as the official asset.
6. Independently qualify **D4 Suite mixed-wheel launcher**, physical ScoreForm evidence and any additional required human timing/identity gates. Do not close #126 on synthetic success alone.

## J2 authorization boundary

A J2 commit on a feature branch is permitted as evidence reconciliation. **No automatic pushes, merges, tags, version bump or release publication** are authorized by this package. The owner may review the commit and direct subsequent J3 implementation. Do not rerun the accepted human correction/retake saves simply because the release version changes; verify the *new* official build and integration boundaries separately.
