# Meridian #124 E2G3O9 — Native ScoreForm and Quillan publication-to-setup acceptance

This increment qualifies installed **producer-generated manifests**, not fabricated JSON publication placeholders. The E2G3O8 Windows x64 / Python 3.14.1 five-wheel environment is reused and its wheel SHA-256 hashes, installed versions and source commit identities are guarded.

## Synthetic scenarios

1. ScoreForm creates a six-question assessment for **29 entirely synthetic students** through `ScoreFormRoutedResult` and the producer's normal export service. It registers the current work, runs its native manifest-generation service and explicitly publishes the manifest through the ScoreForm publication controller. Meridian's named discovery must show one verified current publication. One teacher `APPLY` creates and selects the Grade Item and included period-correct membership. The same assessment reopened is read-only and requires no confirmation or new receipts.
2. Quillan creates a synthetic assignment, standards profile, plain-paper submission and review record using Quillan's native structures. The producer's manifest-generation and publication controllers create the canonical Quillan publication. Meridian verifies the exact publication and performs the same one-confirmation setup and no-write reentry.

In both scenarios only a synthetic teacher-identity witness is substituted for the real profile, consistent with the preceding E2G3O4–O7 synthetic tests. Production Grade Item, membership, action receipt, correlation, registration and publication state are genuine canonical test-workspace writes. The fixture **does not authorize reading student evidence**, map standards automatically, compute grades, or exercise image/scanner correction.

## Qualification and limits

The runner accepts only Meridian commit `a381f14f295c43dabb64675b4f0c647024c6dab5` on branch `124-automatic-assessment-discovery-grade-item-setup`, exactly matching origin and an entirely clean worktree. It independently verifies four peer source refs, all five existing wheel digests, package versions and `pip check`. It uses `python -I -m pytest` from a separate scratch test suite populated by pinned `git show` fixture modules plus this test. It cannot pick up source checkout imports or uncommitted files. No peer repo is modified and no build is repeated.

The source-tree pytest case is explicitly skipped outside the isolated runner so it does not claim an installed contract when running in a developer environment. After installed qualification, Ruff and a focused local skip check must pass; only then exactly these two new files are staged, committed and non-force-pushed. Failures preserve scratch evidence and the uncommitted checkout state; no reset/clean/force push.

## What remains open after a pass

A native *scored* Concord activity/manifest-to-Meridian path, adversarial/permission cross-product, final candidate-SHA full lint/type/tests and package inspection, Windows + Ubuntu CI, and GitHub issue acceptance review. No real classroom or identifiable student data is used or printed.
