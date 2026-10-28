# Meridian #123 — Slice 11C: cross-domain adversarial read-only acceptance

**Pinned branch base:** `dd35b044d5d566a6c560d9d5c09cd1ba4a89fe6f`.
**Scope:** Additional tests and an auditable matrix only. No changes to menu code, canonical records, permissions, packaging, Core contracts or producer readers.

## Purpose

Slice 11A froze the 49-original/83-current route adoption census. Slice 11B qualified synthetic menu composition and interaction counts. Slice 11C adds adversarial checks against the *real* shared teacher-choice selector, `TeacherNavigationContext`, and the two existing read-only `run_named_grade_item_review` and `run_named_grade_item_proficiency` controllers. Only the backing Core metadata, roster, Grade Item and proficiency read APIs are synthetic.

The cases focus on critical scope boundaries: wrong class and year, missing Grade Item relationships, denied reader access, stale grade item/student/Standard choice witnesses both before and after source reads, duplicate Unicode labels, hidden identity tokens, unsafe/control-bearing text, bounded catalogs, and no implicit selection of a singleton.

A resulting error must neither retarget an academic record nor update the verified teacher-session student/Grade Item context. An unavailable catalog remains a blocker, not permission to inspect protected publications or manufacture Grades.

## Academic integrity and test semantics

- Successful Grade Item/proficiency observations call injected **read-only** domain loaders, use exact opaque identities internally, and show named teacher-facing details. They cannot author new revisions, grant evidence authorization, select a current result or export.
- Failure tests check that the source reader is not called when the catalog or verified class fails, and that no session state is updated if a post-read provenance check fails.
- Some tests deliberately call a synthetic reader that raises `PermissionError`. This verifies redaction/absence of downstream writes **at the menu boundary**, not a live protected-publication authorization flow.
- Previously qualified canonical currentness, CAS, export receipt and #122 interrupted-save tests remain in the regression groups; these synthetic acceptance tests do not replace them.
- Linux/Windows wheel installation, actual producer authorization, execution on real school data, cross-domain fully populated workflows, and supported-Python CI remain explicit open #123 gates.

## Qualification

The source-only runner must pin the clean branch, SHA and 18 unchanged source blobs, verify all payload checksums, reject unsafe archive entries, run Ruff and strict mypy, preserve the 49-route/9-report frozen audit, execute three cumulative regression groups, stage exactly three additions, reject whitespace issues, then commit and push without force.

No existing route, prompt contract, runtime module, or academic data path is modified. Matrix file: `docs/architecture/issue123-slice11c-adversarial-matrix.json`.
