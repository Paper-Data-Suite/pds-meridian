# Meridian #123 — Slice 11F: teacher guides and qualified acceptance ledger

**Source baseline:** `941f268ce090929aee951bbc6c21792aa6b3a227` (Slice 11E). **Scope:** Additive documentation and documentation-contract tests; no runtime, state, authorization, persistence, import, version or package-manifest change. The guide applies to this feature branch; no release or merge is claimed.

## Established evidence

| Gate | Observed status | Evidence and scope |
| --- | --- | --- |
| Live route census | Pass (Slice 11A source tests) | 49 historical operations; 38 named and 45 Advanced live teacher-context choices; nine guided reports preserved |
| Shared-menu journey | Pass (Slice 11B synthetic tests) | Real menu routing with read-only domain probes; expected and asserted 25 inputs, one class chooser, three initial catalog reads, zero normal technical-ID prompts, 29-student synthetic roster |
| Adversarial selection | Pass (Slice 11C synthetic tests) | Selected domain read-only controllers with synthetic canonical readers, stale witness, duplicate Unicode labels and denied-reader boundary |
| Installed menu navigation | Pass (Slice 11E wheel gate) | Source-isolated five-wheel installation and CLI/menu text/keyboard navigation. Candidate Meridian wheel SHA-256 `0cb215ef2c32815f8364a3bc6b5102dd95cc1b7a50aebba55ea9aa8c719a2b51` in that reported run |
| Exact package inventory | Pass (Slice 11E) | Explicit 272 file allowlist, rejects unreviewed modules |
| Windows targeted regressions | Pass (Slice 11E) | 1,752 passed, 8 skipped (Windows symlink permissions) |
| Full Windows repository validation | Pass (owner log after Slice 11E) | `scripts/validate_repository.py`: wheel and sdist build, twine, package checks, complete source validation, and six installed dependency matrices; final success message recorded |
| #110 raw prompt source quarantine | Preserved | 188 historic source prompt sites; unchanged SHA contract, no general bypass |

**Important measurement distinction:** The 25 inputs and three class catalog reads describe one *instrumented synthetic source-tree journey with read-only domain probes*. They are neither a timed classroom benchmark nor an equivalent legacy-UI before/after study. `latency_ms` remains null in the Slice 11B contract. The 188 sites measure legacy source occurrences, **not** a prior journey's input count. No numeric improvement percentage or general speedup is claimed.

## Open acceptance requirements, not yet signed off

1. **Richer end-to-end installed-domain journey.** The installed smoke proves menus from installed wheels and existing service smokes prove domain behaviors separately. Issue #123 still calls for a single realistic wheel-installed journey joining a 29-student/duplicate-name roster, multiple marking periods, producer-titled work, archived or renamed Grade Items, revoked evidence access and named Grade/proficiency/explanation/export or planning route, with class switching and no academic write on canceled/read-only actions. Existing Slice 11B probes are not a replacement.
2. **Measured before/after interaction baseline.** Need a comparable scripted legacy-route workload and current named-route workload with measured input counts, repeated scope prompts, bounded reads and end-to-end latency. No fabricated baseline; distinct machine/time/hardware should be annotated.
3. **Windows/Linux CI matrix.** Current `.github/workflows/ci.yml` runs ubuntu-latest and windows-latest on Python 3.11–3.14 through pull requests. No PR/CI pass has yet been recorded for this feature branch. Open a review PR and verify all eight jobs with exact authenticated wheel assets.
4. **Proficiency-to-planning discoverability.** Proficiency option 10 is labeled Advanced while nested Planning Signal 8–14 are named. Determine whether to add a normal entry without breaking the frozen route/crosswalk; do not claim it is already an ordinary unlabeled route. Direct calculation/author/select remains Advanced and may require explicit issue-scope reconciliation.
5. **Review and merge/closure decision.** Recheck this ledger after any new commits, rerun required tests at the final SHA, and record CI/owner acceptance before merging or closing #123. Related #124–#129 and #120 own excluded setup, batching and grading policy features.

## Teacher guides added

- `docs/teacher-navigation-guide-issue123.md` — actual nine-task entry, class retention, choice controls, named workflows and truthfully labeled Planning Signal entry.
- `docs/architecture/teacher-advanced-record-operations-issue123.md` — per-menu Advanced inventory, provenance/authorization boundaries, direct CLI and raw-prompt quarantine.

These documents should be reviewed as teaching-facing text and updated if the live route inventory changes. Passing a source-only guide test is not the same as student-data acceptance.
