# Meridian #124 — Slice A: audited source and interaction contract

**Issue:** [#124 — Automatic assessment discovery and Grade Item setup](https://github.com/Paper-Data-Suite/pds-meridian/issues/124)
**Parent:** [#120](https://github.com/Paper-Data-Suite/pds-meridian/issues/120)
**Branch:** `124-automatic-assessment-discovery-grade-item-setup`
**Base commit:** `c69e4e5ca9603ffe4b9295a6ac9f6e4fbe924a29` (merged #123, CI #141 passed at the #123 source head)
**Slice type:** read-only source inventory, executable drift guard, and planning acceptance. **No production code, state transition or academic schema change.**

## Audited source topology (not an implementation of #124)

| Concern | Real current owner and entry point | Boundary and implication |
| --- | --- | --- |
| Teacher evidence discovery | `teacher_evidence_inbox.teacher_evidence_discovery_request()` and `menu_teacher_evidence.py` | Only *current `academic_result_set`* publications are discovered today. Preflight labels do not grant access to producer manifests, protected student work, or publication bytes. #124-B must also support registered-only work. |
| Current registered work and academic period | `guided_grade_items.load_guided_grade_item_bridge_context()` | Reads canonical **current** Core Academic Work Registration, class metadata, current Academic Period Calendar, and Grade Items projection for the exact `ModuleWorkRef`. A catalog listing is not execution authority. |
| Grade Item readiness projection | `grade_items_workflow.project_grade_items_review()` | Exposes selected/current and persisted-only revisions, active/archived status, included/excluded/unselected membership, revision basis, registration revision and period assignment. Title similarity never proves membership. |
| Existing/new Grade Item selection | `menu_teacher_grade_items._choose_existing_or_new()` | Teacher chooses existing/new, then the old create path and membership path are separate review screens. |
| Grade Item create + select | `menu_teacher_grade_items._create_grade_item()` → `prepare_grade_item_action` → `_review_apply()` | One `Save and make current` confirmation for this **single** #122 action. |
| Membership write + select | `menu_teacher_grade_items._link_work()` → `prepare_membership_action` → `_review_apply()` | Another `Save and make current` confirmation for the **separate** membership action, even after a new Grade Item was created. |
| Continuation | `teacher_evidence_continuation.resolve_teacher_evidence_continuation()` | Missing/ambiguous relationship routes toward eligibility, without creating records; #124 must return to this assessment after exact selection and verification. |
| Actor attribution and recovery | #121 teacher profile and #122 `teacher_action_*` durable receipts/restart | Saved actor is attribution, **not authentication**. Two independent writes/selections require explicit partial-state tracking; no imaginary multi-file atomic transaction. |
| Teacher navigation | #123 `TeacherNavigationContext` / `TeacherSessionContext` | Selected class/work is a convenience subject to canonical revalidation, not a bypass of source/auth requirements. |

### Structural legacy interaction baseline

The reproducible `scripts/issue124_slicea_baseline_audit.py` uses Python's AST parser on **six allowlisted source files only**. It finds **two distinct `_review_apply` call sites** on the new Grade Item flow: one for create/select and one for membership write/select. Thus the old *create-and-link* workflow has **two teacher-facing substantive Save confirmations** before any additional eligibility, attempt or Standards decisions. The #124 goal is **one confirmation for the entire reviewed create-and-link task** (zero for already ready).

This is **not a paired runtime benchmark**: the AST audit does not measure total `input_fn` calls, keystrokes, elapsed time, repeated context requests or behavior for every branch. It does not replay a real publication: no protected assessment data is opened. Baseline measurement of completed interactive scenarios—including required title/purpose/period/attribution choices—belongs to #124-H (and selected synthetic tests before then). Do not claim an exact reduction in overall inputs or latency from these two structural call sites.

## Cross-repository contract inventory

1. **Core:** `AcademicWorkRegistrationCatalogQuery` / `query_academic_work_registration_catalog` discover current registrations by class/year/module/intent/lifecycle. `PublicationCatalogQuery` / `query_publication_catalog` discover publication state; both are derived indexes. Revalidate against `load_current_academic_work_registration`, current calendar and canonical Publication Records. Core `academic_intent` (formative, summative, diagnostic, practice, feedback_only, reporting_only) is not a Grade Item `purpose`.
2. **ScoreForm:** producer owns assignment registration and explicit `academic_result_set` publication; capabilities include points, question evidence and multiple attempts. Meridian cannot publish or select an Attempt just by listing work.
3. **Quillan:** producer owns assignment registration, immutable result manifest and explicit publication, including standards ratings. A registered assignment alone is not published or ready to consume as evidence.
4. **Concord:** scored Activity publications use producer-owned record and manifest contracts. `scoring_orientation="evidence_only"` **cannot** generate the scored `academic_result_set` manifest; no score, individual attribution or Grade can be invented to make it appear discoverable.
5. **Suite:** teacher-facing *choose → review → confirm → report → continue* language only; no new cross-suite service or Notes & Tasks authority.

Pinned cross-repository `main` revisions, current Meridian source Git blobs, `pyproject.toml` constraints and `.github/workflows/ci.yml` released wheels are recorded in `issue124-slicea-baseline.json`. These are *audited snapshot references*, not claims that they are the latest available releases forever.

## Read/write contract for next implementation

- **Discovery is read-only and bounded**: class/year scope, recognizable title, explicit producer and lifecycle, duplicate-label disambiguation, registered-only versus currently published, and truthful unsupported/stale/revoked conditions. Do not open producer manifests, scans, answers, feedback, private student records or per-student eligibility simply to render a chooser.
- **Existing readiness is selected canonical state**: a selected **active** Grade Item and an included, **current** membership referencing that exact work, registration revision, Grade Item revision, chosen academic period and calendar. Merely persisted revisions, title coincidence, a stale catalog, or a prior `excluded` link are not ready.
- **Proposal is teacher-authorized**: `academic_intent` does not authorize `GradeItemPurpose`; teacher explicitly chooses purpose and period. Existing ambiguous, excluded or archived candidates need deliberate review. No automatic Grade, zero, proficiency, mapping, policy, weighting or publication authorization.
- **Composite result is not atomic**: after exactly one teacher confirmation, apply the existing Grade Item Save/Select then membership Save/Select with fresh preflight per step, correlate #122 receipt IDs, reload current records and report `Ready` only on complete verification. Partial states must be durable and recover the *same* item, not allocate a `gi_*_2` duplicate.
- **Context is revalidated, not presumed**: a changed Core registration, withdrawal, calendar revision, actor, Grade Item selection, membership CAS or work scope requires refreshed review. Cancellation before confirmation must yield no academic writes or receipt.
- **No producer writes**: #124 cannot register/publish/supersede/withdraw producer academic results or grant protected reads. Concord evidence-only remains separate cross-repository #120 scope.

## Planned execution boundaries

| Slice | Implementation / proof |
| --- | --- |
| **124-B** | Bounded, typed registered work/publication discovery and canonical Grade Item/work/period readiness projections; synthetic/no-read/no-write adversarial fixtures. |
| **124-C** | Teacher-readable proposal with explicit Grade Item purpose/period, existing-vs-new plan, read-only preview, no-write cancellation. |
| **124-D** | Single confirmed composite over existing #122 per-domain Save/Select and canonical reload. |
| **124-E** | Exact restart, CAS conflict, prior selection, retry/idempotency and crash-at-each-boundary tests. |
| **124-F** | Entry from inbox and Grade Items; safe retained context and continuation, ordinary B/M/Q and Advanced preservation. |
| **124-G** | Real synthetic producer installed five-wheel E2E, supported Concord scored and evidence-only blocker, 29×6 scope, revocation/stale adversarial tests. |
| **124-H** | Paired teacher-input counts, one confirmation measured, docs, wheel allowlist, full CI matrix at final commit; owner review before merge. |

### Slice A acceptance and exit gate

- Source-inventory and two confirmation call sites are executable, deterministic and fail if the audited shape changes unexpectedly; none of the source inventory code imports producer/private evidence modules.
- Pin exact clean branch HEAD and source Git blobs before applying any payload. Run full Ruff, mypy, focused tests, repository-wide validation and existing installed smoke matrix using verified released dependency wheels. CI must independently qualify the pushed commit.
- Leave issue #124 open and do not mark the branch as ready/merged until later slices satisfy the full issue's acceptance matrix. Slice A is **foundation only**, not a completed assessment-onboarding feature.
