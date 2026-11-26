# Meridian #126 — J3 coordinated v0.4.3 source release candidate

**Status:** Local version-migration candidate; not validated by complete
repository/CI gates, not merged, tagged or published.

**J2 parent required locally:** `cfa354f1a3efb9d779e829ef05d6a54459ee955d`
(evidence-only J2; 28 focused tests passed). **Merged code baseline:**
`698903fa1db4ad43c32664eb64211d69ba3f987c`.

## Scope and intent

- Promote the active version consistently from `0.4.2` to `0.4.3` in the
  authoritative `_version.py`, wheel/sdist validators, smoke programs,
  current-version test assertions and synthetic package fixtures.
- Preserve historical version references when they refer to released v0.4.2
  notes, audit, original SHA-256, source provenance, and the historical J1/J2
  acceptance ledgers. J2's unpublished installed `0.4.2`-labelled wheel is
  not interchangeable with the authenticated published v0.4.2 artifact.
- Add v0.4.3 candidate release notes to the documentation and sdist
  inventories without removing prior release notes or relaxing package
  allowlists. `pyproject.toml` continues to obtain its dynamic version from
  `meridian._version.__version__`.
- Update the current README/documentation headers to state **candidate**
  status, while retaining prior release/issue historical paragraphs.

## Tests and evidence boundary

The J3 guarded operator applies text changes only after exact J2 parent/clean
branch checks, runs focused packaging/version/older release regression tests
plus Ruff, and commits locally only if they pass. Focused tests do **not**
replace the authoritative clean full repository validator. Its official wheel
archive SHA-256 checks, full pytest, strict mypy, documentation, build, Twine,
package/sdist inventory, six installed dependency matrices and `pip check`
remain required before a release PR is qualified.

Historical `tests/test_issue126_slicej1_final_gate_contract.py` and
`tests/test_issue126_slicej2_postmerge_acceptance.py` continue to assert the
J1/J2 **historical** `0.4.2` evidence; they must not be rewritten merely
because the active version changes.

## Required next actions

1. Review exact J3 local commit and diff (no remote push in this handoff).
2. Run the complete validator using official authenticated dependency wheels
   in a **clean committed source** and compatible installed environment.
   Keep complete logs and actual pass/skip counts.
3. Obtain GitHub 8/8 Windows/Ubuntu × Python 3.11–3.14 on the **exact final PR
   head SHA**. A previous source/test run does not authorize merging.
4. Review/merge only after owner decision. Then create an exact release tag,
   build/publish wheel and sdist and independently download/check SHA-256,
   sizes, and package inventory to establish D3.
5. Separately check official-wheel Suite foreground launch and safe return
   (D4), physical ScoreForm evidence, and final A1–A18 release ledger. Keep
   Issue #126 open until relevant boundaries are attested.

## Non-goals

No automatic new scoring, correction provenance invention, modified Core or
producer policy, Office/Genesis/SIS posting, cross-repository write,
release tag, publication, or issue closure. Report 9 #133/#134 remain separate.
