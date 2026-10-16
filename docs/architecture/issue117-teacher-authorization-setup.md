# Issue #117 Slice 2 — Previewed teacher-local authorization setup

This slice introduces a deliberately bounded policy-authoring service for the
normal teacher workflow being wired in the following slice. The service does
**not** expose its own teacher menu yet. In particular, this slice alone does
not resolve the misleading Ready to review inbox state or enable automatic
reauthorization during the current Meridian menu session.

## Teacher-facing contract

A caller carries the selected canonical class, producer(s), and publication(s)
from Core discovery. The teacher must choose one of two different scopes:

1. **Selected existing publications only** — exact publication ID filter,
   supplied from the selected Core items, not free-typed in the ordinary menu.
2. **Current and future publications from the explicitly selected producer(s)**
   — no publication filter, but retains exact class and producer boundaries.

Both choices authorize whole-assignment evidence for the selected class and
producers. Student-restricted grants already on disk remain untouched. The
teacher must confirm with `AUTHORIZE`, following a preview clearly naming the
scope, class, producers, and protected purposes/operations. The menu must never
silently choose the wider future-publications option.

The grant contains only:

- operations: `project_evidence`, `read_projection_cache`
- purposes: `review_evidence`, `teacher_reporting`
- the exact class and producer filters selected above
- either exact publication IDs or an explicitly chosen unrestricted publication
  filter; `student_ids=[]` denotes whole-assignment access (as fixed in Slice 1)

**No academic decisions** are made, no evidence is read, and no credentials,
student content, or teacher personally identifying details are stored.

## Persistence and recovery

The existing `meridian_publication_authorization_policy` schema v1 remains
unchanged and readable by the existing loader. Setup writes the default policy
at `<workspace>/.pds/meridian/authorization-policy.json`. It refuses to modify a
custom `MERIDIAN_AUTHORIZATION_POLICY` path, linked/nonregular policy or parent,
or a malformed existing policy. Existing grants are preserved in order. Duplicate
identical grants produce a no-op. New grants change `policy_version` so that
protected downstream caches retain a distinguishable authorization identity.

A save compares the source policy digest with the previewed digest before
replacing the file. A changed policy requires re-preview. A temporary file in
the same directory is flushed and atomically replaced; a failed attempt cleans
up its own temporary file. System-level concurrent writer locking remains
outside this slice; do not claim this is a global multi-process transaction.

## Next integration boundary

The next slice must connect preview/commit to the ordinary class-first evidence
menu, show the selected class and publication titles rather than opaque IDs,
require an explicit broad-scope choice and confirmation, and refresh the
resolved authorization dependencies after a successful save. Before that
integration, the new module is an API, **not a finished teacher-facing flow**.

## Validation

Focused source pytest covers preview safety, confirmation, round-trip loader,
ScoreForm/Quillan/Concord scope checks for both protected operations and both
purposes, future-scope opt-in, persistence, concurrency observation, no-op replay,
malformed policy refusal, alternate-config refusal, and symlink protection.
Also run Ruff, strict mypy for the modified/new authorization modules, and
git diff --check. Do not run the full suite or six installed matrices until the
assembled release candidate is ready.
