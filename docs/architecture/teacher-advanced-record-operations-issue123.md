# Meridian #123 — Advanced / exact record operations

**Status:** Feature-branch reference for Meridian v0.4.2 candidate. This is not a substitute for service-level authorization, a release approval, or official district gradebook access.

## When Advanced is appropriate

The teacher-first path uses named choices with internal canonical identities. Advanced operations deliberately expose exact IDs, revisions, digests, historic selection pointers, and technical build inputs for support, migration and diagnostic use. They are **optional**, not an ordinary teacher's required next step. An Advanced route cannot bypass the same currentness, Core/producer permission, typed Save/Apply, or immutable-record constraints as the underlying service.

For a single displayed row in the shared selector, use `T` to inspect its exact identity and currentness witness without making a selection. The separate `meridian --help` CLI retains noninteractive expert commands. Do not paste confidential student answers or protected publication metadata into issue logs.

## Live Advanced menu inventory

This table describes the **teacher-context** menu as inventoried in `issue123-slice11a-live-adoption.json`. Numbering is local to each submenu; it is not an API contract.

| Menu | Advanced choice numbers | Exact/technical purposes |
| --- | --- | --- |
| Grade Items | 3–6 | Author Grade Item revision, select Grade Item revision, author work-membership revision, select membership revision |
| Proficiency | 3–10 | Planning readiness, Grade Item calculation preview/write/select, Academic Period calculation preview/write/select, and the nested Create Planning Signal entry |
| Grades | 3–4 | Bounded Grade-report preview; current Grade preview with exact records |
| Overrides | 2–5 | Author, select, withdraw, or inspect current override using exact records |
| Snapshots | 1–6 | List/inspect/select frozen checkpoints, current reporting-use selection, reporting-definition revision, build-request-JSON freeze |
| Export | 1–6 | List/inspect/author/select Export Profiles, exact ReportingSnapshot export, inspect ExportReceipts |
| Explain | 1–8 | Exact-identity Grade, comparison, Grade Item/period proficiency, planning derivation/preview/export, and ExportReceipt explanations |
| Planning Signal (nested under Proficiency 10) | 1–7 | Exact policy readiness, derivation/preview writes, preview diagnostics, review author/select, accepted Core export |

The eight historical menus expose **45 explicitly Advanced choices** and **38 named choices** in teacher context, not counting the nine separately guided Reports. The nested Planning Signal menu is not a new top-level main-menu task. `Proficiency 10` is currently Advanced-labeled but leads to named Planning Signal choices 8–14; this limitation is documented rather than hidden.

## Academic operation boundaries

- **Identity and status:** Class, year, work, Grade Item, student, Standard, policy, period, snapshot, revision and digest must be read from authoritative Core/Meridian contracts, never reconstructed from visible titles.
- **Producer evidence:** A Core registration or publication listing does not authorize protected student evidence. ScoreForm, Quillan and Concord readers remain behind the existing authorization and producer-compatibility gates. Concord evidence-only activities never become inferred student scores.
- **Proficiency and Grades:** A calculated preview is not the selected official current result. No evidence or an unassessed state is not a numerical zero. Scale/policy/mapping configuration belongs to the relevant separate issues.
- **Overrides:** Authoring, current-use selection and withdrawal are distinct deliberate operations, with teacher attribution and exact currentness checks. An interrupted action is recovered through #122's verified receipt workflow.
- **Snapshots and exports:** A ReportingSnapshot freeze is separate from current-use selection; a local file export is separate from any district/SIS/LMS write. Exact snapshot fingerprint and destination review remain required.
- **Planning Signal:** Derivation, preview, teacher review, selected review, Core grouping-signal-set export, optional CSV, and Concord GroupPlan are different records or actions. Do not infer one from another.

## Technical prompt quarantine

The historical issue #110 `188` raw-ID prompt-site inventory and SHA-256 contract remain frozen. It counts legacy source sites; it is **not** an observed count of teacher keystrokes. Named routes must not be wired to those prompts inadvertently. Changing an Advanced route or removing raw prompts requires a deliberate source and audit update rather than weakening the quarantine.

For the complete operation-by-operation crosswalk consult `docs/architecture/issue123-slice11a-live-adoption.json`. This guide is not permission to delete a legacy route, silently rewrite provenance, or relabel an unsupported operation as routine.
