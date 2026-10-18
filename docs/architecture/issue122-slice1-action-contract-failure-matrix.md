# Issue #122 — Slice 1: teacher action contract and failure matrix

**Status:** contract foundation; no teacher menu is switched in this slice.

**Baseline inspected:** Meridian `main` at `f64428071bd87766a2cd0871979590ded99c907a`; Core `main` at `bf3e6c08dd3f51e47cdbe56b11a3873a9d4491b3`; Concord `main` at `6472215e43a740d195257ecbe6b099b2d0648df5`; ScoreForm `main` at `dbb4159bb2c4d04889742de746be42a394130170`; Quillan `main` at `93cf0ae84887d79377e6f77c1d0c818af24688a5`. Confirm the branch's effective base before subsequent changes.

**Related:** #120, #121 (saved actor/one-use override), #123 (navigation), #124 (discovery), #61, #110.

**Purpose:** one teacher confirmation eventually authorizes the existing authoritative write, exact CAS selection, and independent current-state verification. **This is not a filesystem transaction.**

## 1. Existing authority and two-confirmation inventory

| Ordinary entrypoint | Existing read/author services | Existing select services | Canonical invariants that must survive | Adoption slice |
| --- | --- | --- | --- | --- |
| `menu_teacher_grade_items.py` → `guided_grade_items.py` | `preview_new_grade_item` / `commit_new_grade_item` → `grade_item_authoring_workflow.py`; `preview_membership_link` / `commit_membership_link` → `grade_item_membership_authoring_workflow.py` | `select_new_grade_item` → `grade_item_selection_workflow.py`; `select_membership_link` → `grade_item_membership_selection_workflow.py` | candidate revision digest; contiguous history; class/work registration; prior Grade Item and membership pointers; exact target revision/digest; membership current applicability | 4 |
| `menu_teacher_eligibility.py` → `guided_eligibility.py` | `preview_guided_eligibility` / `commit_guided_eligibility` → `new_evidence_eligibility_workflow.py` | `preview_guided_eligibility_selection` / `commit_guided_eligibility_selection` → `new_evidence_eligibility_selection_workflow.py` | authorized projection snapshot, publication/cache/snapshot digest, membership revision/digest, current Core source state, prior selector | 4 |
| `menu_teacher_attempts.py` → `guided_attempts.py` | policy plan/apply plus `preview_guided_attempt_decision` / `commit_guided_attempt_decision` → `attempt_policy_authoring_workflow.py` and `attempt_decision_authoring_workflow.py` | `attempt_policy_selection_workflow.py`; `preview_guided_attempt_selection` / `commit_guided_attempt_selection` → `attempt_decision_selection_workflow.py` | policy ID/revision/digest and selected policy, eligible attempt source, membership digest, exact teacher-chosen attempt set, prior policy/decision CAS pointer | 5 |
| `menu_teacher_standards.py` → `guided_standards.py` | `preview_guided_standard_association` / `commit_guided_standard_association` → `standards_association_authoring_workflow.py` | `preview_guided_standard_selection` / `commit_guided_standard_selection` → `standards_association_selection_workflow.py` | teacher's explicit association basis, evidence source authorization/currentness, association revision/digest, prior selector, standard library/scale basis | 5 |
| `menu_teacher_proficiency.py` → `guided_proficiency.py` | `preview_guided_proficiency_result` / `commit_guided_proficiency_result` → `calculation_result_persistence_workflow.py` | `preview_guided_proficiency_selection` / `commit_guided_proficiency_selection` → `calculation_result_selection_workflow.py` | authorized source, selected inputs, calculation/mapping/policy basis, exact persisted result digest and prior selector | 6 |
| `menu_grade_items.py` and direct CLI write/select commands | explicit standalone authoring services | explicit standalone selection services | keep **advanced** write-only and select-only contracts and tests unchanged | preserve |

Each listed guided route currently has a separate *write* and *make current* teacher confirmation. Grade Item setup can include **two linked records**, Grade Item followed by membership; a failed second step must not advertise the entire setup as finished. The issue's request for one ordinary Save/Apply confirmation does **not** authorize silently choosing a policy, attempt, Grade Item, student owner, standard, grade, or eligibility disposition.

Additional candidate routes using independent author/select contracts should be recorded for later adoption rather than implicitly considered covered: academic-period result persistence/selection, new evidence eligibility advanced routing, exclusions eligibility, planning reviews, reporting snapshot selection, Grade overrides, and technical menu Grade Item actions. Confirm their ordinary-versus-advanced status in Slice 6; do not regress existing CLI behavior.

## 2. Canonical record semantics and baseline checks

- `grade_item_authoring_workflow.GradeItemAuthoringPreview` already binds candidate bytes in `candidate_sha256`, expected contiguous history, and previous latest-revision SHA. The store distinguishes `created`/`existing`; immutable authoring **does not select**.
- `grade_item_selection_workflow.GradeItemSelectionPreview` holds exact target, history, `expected_current_revision`. Commit reloads target revision and SHA, verifies history and current pointer, and invokes `select_grade_item_revision(..., expected_current_revision=...)`. Underlying storage locks the target and verifies the selected revision before returning. `existing` selection means a no-op pointer; don't count it as an update.
- Membership authoring validates the current Grade Item revision and work registration. Membership selection similarly compares exact decision digest, history and expected selected revision. `verify_current_membership_link` currently checks the projected included relationship, current Grade Item basis and registration; future postcondition verification must also compare **the selected target revision and digest**, not just a generally eligible relationship.
- Eligibility selection binds a persisted eligibility revision, source publication ID, cache key/snapshot digest, membership digest, observed Core source lifecycle and previous selector; commit checks them again. This is the pattern for source-sensitive adapters.
- Attempt policy/decision, standards association and proficiency result selection each have revision/digest and expected-current checks. An adapter must supply its specific authoritative loaders; a generic `get_latest()` is not sufficient.
- #121's `TeacherAttributionInput` substitutes an exact saved **actor ID** for known input prompts. `OneActionAttributionOverride.resolve_next()` consumes an override on its next attribution request even if later academic writing fails. An action preview must bind resolved actor ID, source (`saved`/`temporary`) and exact profile SHA. **Do not call `resolve_next` twice** for write and selection. Saved profile attribution is not Core evidence authorization.
- Core `registry_audit.py` checks registry health and locks; it is **not** the teacher transaction journal. Core supplies class/module routes and academic registry/publication authorities. ScoreForm and Quillan each own `academic_result_publication.py`, `academic_result_reader.py` and publication revision policy; Concord likewise owns academic-result publication and reader contracts. Meridian `adapters.py` validates the publication manifest digest against Core and negotiates producer reader compatibility; `concord_adapter.py` projects represented scores without choosing the teacher's grading policy. Meridian must not alter producer-owned revision histories, and an evidence-only Concord artifact is not automatically scored evidence.
- Existing Meridian receipt modules (`report_export_receipt.py`, `grouping_signal_export_receipt.py`) contain useful canonical serialization/digest, containment, locking and corruption-fail-closed patterns, but are semantically different receipts. `teacher_profile.py` additionally shows private user-config path and Windows/POSIX lock handling. Do not reuse any receipt as a substitute for authoritative current selection.

## 3. Typed in-memory contract introduced in this slice

`meridian/teacher_action_contract.py` provides frozen, typed, immutable-value structures:

1. **`TeacherActionScope`** — workspace fingerprint, class, Grade Item, optional school year/period/calendar and exact work identity fingerprints.
2. **`TeacherActionActor`** — stable actor ID, saved profile SHA and saved/temporary source (identity only).
3. **`TeacherActionBasis`** — sorted, uniquely role-keyed identity/digest bindings for authorization, source publication, policy, mapping, membership, selection pointers, etc. A role is a declaration of *what must be revalidated*, not a permission grant.
4. **`TeacherActionTarget`** — canonical family, logical target identity digest, exact proposed revision and digest, and previous selected revision/digest CAS baseline. Values come from the **existing domain authoring previews**; adapters must not invent canonical bytes.
5. **`TeacherActionPreview`** — opaque action ID, exact resolved actor, scope, target, bound observations, digest of reviewed academic decision and ordinary make-current intention. Its canonical `intent_sha256` excludes the fresh action ID, enabling precise duplicate detection **only after** canonical state is inspected.
6. **`TeacherActionRecord`**, **`TeacherActionCheckpoint`**, **`TeacherActionResult`** — exact persisted/reused record identity and digest, explicit stage outcomes, selected-record observation, selection disposition, and lifecycle status. Constructors reject several internally contradictory success/partial claims. A `matches` current-state field must only be supplied after an **independent canonical loader** has verified that exact selected record and current applicability.
7. `teacher_action_outcome_message()` — cautious default teacher language; individual routes can provide more useful named context after safely reloading it.

**Important contract boundary:** The SHA digests represent independently observed canonical data and reviewed intent. An in-memory dataclass is **not** a durable journal, an authority token, a committed transaction, or a proof that a separate actor has not changed state. This module does not perform I/O or introduce implicit permissions. A domain adapter must pass its original native preview objects through preflight and compare exact canonical values under existing workflow CAS rules.

## 4. Execution / crash / recovery state matrix

| Window / observation | Required result | Recovery and prohibition |
| --- | --- | --- |
| Preview cancelled, profile missing, authorization denied, unsafe journal path **before** writing | `blocked_before_write` (only when no canonical mutation was attempted) | No write/select; no academic side effect. Re-review or fix configuration. |
| Context/permission/actor/policy/source/period/selected pointer changes before the canonical write | `conflict_requires_review` | Invalidate preview; do not retry with a silently refreshed revision. |
| Journal prepared and authoritative write fails with confirmed no new record | `blocked_before_write` or `conflict_requires_review` according to independently established state | Never assume arbitrary write exceptions mean no mutation. Unknown outcome enters recovery. |
| Immutable write succeeds; process fails before selection preview | `written_not_current` if canonical selector known not to target the new revision; otherwise `current_unverified` / `recovery_required` | Reconcile exact persisted revision SHA and current selector; offer *Resume exact selection*, *Review changes*, *Leave unselected*. |
| Selection-preview construction fails after write | `written_not_current` only with verified non-current selector; otherwise `current_unverified` | Preserve immutable revision; no duplicate authoring on retry. |
| Selection CAS conflict after write (another teacher/process selected a different target) | `conflict_requires_review` with persisted steps preserved | Do not overwrite a newer selector or auto-rebase. Refresh teacher review. |
| Selection commit throws or process terminates mid-commit | `current_unverified` or `recovery_required` | Reload canonical selector; never infer success from a return code or receipt alone. |
| Selector reaches correct target, but authoritative reload/source applicability is stale or fails | `current_unverified` or `conflict_requires_review` (basis changed) | Explain uncertain/invalid effect, retain history, require current authoritative checks before success. |
| Exact target exists, canonical selector matches exact revision/digest and all dependencies remain applicable | `applied` (new work done) or `already_applied` (both persisted record and selection are unchanged) | Display success after fresh reload; do not create history on repeated Save. |
| Receipt unreadable/corrupt/unsafe link, or reconciliation cannot prove identity | `recovery_required` unless safely blocked before mutation | Fail closed; do not follow link, overwrite receipt, silently choose newest, or destroy immutable history. |
| Receipt write fails *after* canonical write/select | `current_unverified` or `recovery_required`, qualified by fresh canonical observation | Keep primary academic record authoritative; preserve diagnostics. Never mislabel as "nothing changed". |
| Multi-record Grade Item setup: Grade Item current but membership not current | `written_not_current` / `recovery_required` for incomplete **overall** setup | Track progress per canonical record family. Clearly say which part is operative. |

**No atomicity claim:** there is no single filesystem transaction across canonical write, pointer update, journal update and verify. The journal records attempted/observed steps; it does not make them atomic.

## 5. Storage proposal for Slice 2 (not implemented yet)

Use a **Meridian-owned class-local collection**, such as:

`class_module_dir(workspace_root, class_id, "meridian") / "teacher-actions" / "v1"`

This is a proposed location, **not yet a published storage contract**. Core `class_module_dir` must construct it; scope keys should be bounded SHA-based directory/file names rather than raw work IDs. Keep one action ID per confirmed attempt and bind canonical scope SHA plus intent SHA. Store only schema/version, actor ID, record family/opaque logical key, revision/digests, selection baseline, UTC stage timestamps, per-step state and reason codes. No absolute paths, student work, answers, scan images or raw academic rationale. An optional preview summary digest is not a substitute for immutable canonical content. Enforce exact-key JSON, <=64 KiB/action file (subject to fixture findings), duplicate-key rejection, bounded number of files, SHA sidecar or equivalent integrity, symlink/reparse/hardlink/path containment checks and durable replace/fsync. Audit the existing grade item and receipt lock helpers before choosing a lock primitive; avoid nesting locks in an inconsistent order. Verify permissions on Windows and POSIX.

Every recovery check must compare **canonical history and selection pointers** even when the receipt says `applied`. An absent, corrupt or stale receipt must never be enough to create a duplicate or choose a changed candidate. On receipt preparation failure before write, refuse the academic write. On post-mutation journal failure, return an indeterminate/partial result and recover via canonical evidence, not journal-only data. Do not store arbitrary command strings.

## 6. Proposed domain execution skeleton for Slice 3

1. Review exact native authoring preview, resolve #121 attribution **once**, gather live basis digests and prior selector, and show human-readable effect, including becoming current. Preview is read-only.
2. On single explicit `SAVE` / `APPLY`, guard receipt location; prepare durable attempt journal; revalidate actor profile and each domain-dependent Core/producer source; compare the reviewed authoring preview and current pointers. Fail closed before mutation on changed meaning.
3. Invoke authoritative immutable authoring commit. On return or uncertain exception, reload exact history/record SHA rather than blind-write again. Journal the observed record family/revision/disposition.
4. Build authoritative **selection preview for that exact written revision**, compare digest and reviewed pointer baseline, then invoke the native selection commit with CAS. Record created/updated/existing disposition.
5. Independently reload the canonical selected revision **and relevant dependencies** (publication, authorization, membership, policy, mapping, period/calendar, etc.). Return `applied` only after verifying exact target and current applicability. Use `already_applied` only if both record and pointer already existed unchanged.
6. On partial/unknown result, expose a teacher recovery menu without falsely claiming rollback, atomicity or new access. Resume only exact reviewed target after renewed authority and source checks and confirmation that current selection has not diverged.

Atomic journal preparation is **not** sufficient to lock the underlying canonical records; use native CAS and revalidation. A request's one-time override must be consumed according to #121 semantics even if later write fails; cancellation *before* attribution resolution should not consume it. If the existing menu adapter resolves attribution earlier than this, document the limitation and fix it while adapting the guided menus.

## 7. Tests / gates

**Slice 1 only:** standalone contract fixtures verify deterministic intent SHA, actor/period/source/policy/selection sensitivity, sorted unique source bindings, pointer/digest validation, no invented successful state, distinct partial/unknown/conflict/already-applied status, checkpoint typing and default teacher language. Run `ruff check --fix`, `ruff format`, clean Ruff verification, strict mypy on the new module, and focused pytest; update exact wheel allowlist for this new runtime module. Do **not** run full suite or installed-wheel acceptance on a contract-only slice.

**Subsequent acceptance:** fault-inject before write, after write, during selection preview/CAS, during reload and receipt fsync; kill/restart process between steps; corrupt/replace receipt with symlink/reparse, duplicate JSON keys or oversized files; stale actor override, Core publication revocation, expired authorization, changed academic calendar, mapping/policy and enrollment/current membership; evaluate ScoreForm, Quillan and Concord synthetic read-only producer fixtures. Preserve per-family revision/digest and no duplicate writes. Final clean installed-wheel and Windows/Linux CI plus one full-suite run at the final qualified commit.

## 8. Actual user-effort target

Count explicit teacher affirmative confirmations, not arbitrary navigation choices or decisions. Current guided paths ask *Write?* and *Make current?* independently. After integration: exactly one *Save/Apply* for each reviewed academic decision, with post-confirmation authoring, selection and verification automatic. Grade Item creation and work linkage remain **distinct academic choices**; a single click covering both is only valid if the combined review explicitly presents both operations and their separate failure boundary. #122 does not claim to solve per-student or per-question batching.
