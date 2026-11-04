# Meridian #124 — E2G3O8 installed five-wheel qualification

## Scope

This gate validates a **separate, non-editable, wheel-installed environment** for
PDS Core, ScoreForm, Quillan, Concord, and Meridian. Meridian is built from the
exact E2G3O7 branch commit; peers are built from verified `origin/main` commits
without changing their working trees. The runner records every source commit,
built wheel SHA-256, distribution version, Python interpreter, and pip state.

The isolated installation must pass `pip check`, verify all five imports originate
under the fresh environment's `site-packages`, validate relevant installed entry
points, and execute the existing synthetic canonical teacher-journey acceptance
suite against the **installed** modules. The tests must not accidentally import
Meridian or a peer from any source checkout.

The source-tree test `test_issue124_slicee2g3o8_installed_composition.py` skips
by default; it is enabled only by the runner in the isolated environment.

## Explicit limitations

- Built wheels from committed peer `main` snapshots are local compatibility
  candidates, **not** evidence that identical wheels have been released.
- E2G3O4–E2G3O7 include genuine Core and Meridian canonical storage, but their
  publication manifests are **synthetic placeholders**. Native ScoreForm,
  Quillan, and Concord producer-generated manifest interoperability remains an
  independent #124 acceptance requirement.
- This qualification does not infer evidence authorization or exercise actual
  student answers, OMR scans, standards scoring, 29-student grading, or an SIS.
- Windows/Ubuntu CI at the final candidate SHA, full repository qualification,
  historical Advanced/recovery regressions, and issue acceptance review remain
  prerequisites to merging or closing #124.

## Safety

The runner refuses a changed Meridian HEAD, remote branch, wrong origin, or dirty
Meridian worktree. For peers, it compares local `origin/main` to the true remote
`main` before building an archived commit. It does not invoke `git checkout`,
`reset`, `clean`, or force push. Build and test files live in a new OS-temporary
directory, not in any repository or classroom workspace. The runner commits
this document and its isolated test only if all installed checks pass and
remote HEAD has not advanced; its machine-readable evidence report is also
saved outside the repository.
