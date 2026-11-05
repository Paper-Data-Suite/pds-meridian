# Meridian #124 E2G3O12 — Evidence Inbox setup route

## Teacher behavior

The Evidence Inbox keeps numbered assessment entries for ordinary authorized evidence review. An additional **`S<number>`** choice, e.g. `S1`, opens the existing one-confirmation Grade Item setup for exactly that published assessment. It does not force all evidence reviewers through another intermediary screen. The only added scope selection is the teacher's named marking period.

The route uses the current class and the exact selected `ModuleWorkRef` and publication identity; it does not make the teacher search for the same assessment by name again. After a completed setup it returns to the same class-level Evidence Inbox; the session keeps the confirmed work, publication, and Grade Item. The ordinary numbered path and authorization requirements remain unchanged.

## Authority and privacy boundaries

- An Inbox entry identifies a candidate. Before offering a setup action, the route rechecks current Core `PublicationRecord` metadata, its current series head, the current class/year calendar, and the fresh named registration/academic setup inventory. It refuses stale, withdrawn, ambiguous, absent and mismatched publication references; no first title match is used.
- There are **zero protected manifest reads** in the assessment-setup path. Evidence Inbox's existing publication authorization, evidence preparation and student review remain separate. Setting up a Grade Item **never** grants access to evidence or decides eligibility, attempts, Standards, proficiency, policies or Grades.
- The route delegates all Grade Item and membership writes to the already-qualified reviewed E2G3O2/E2C correlated workflow, with its exact CAS/recovery and single `APPLY` boundary. The route cannot auto-publish producers.
- The setup option is not shown for an Inbox implementation that has no explicitly wired setup callback. Invalid `S<number>` entries and ambiguous display references are rejected without invoking the setup handler.

## Scope and qualification

Production changes: `meridian/menu_teacher_assessment_discovery.py` and `meridian/menu_teacher_evidence.py`; no new package dependencies, Core schemas or producer changes. Focused tests verify exact selection, denied evidence read on setup, missing wiring and invalid choices, end-to-end canonical setup with existing synthetic publication, zero-write reopening, and stale-publication refusal.

Full repo validator, wheel/dependency release matrix, authorization adversarial review and final candidate SHA CI remain separate issue #124 closing gates. Prior installed five-wheel native producer tests E2G3O8–O10 remain historical evidence, not proof about future changes to source or wheel pins.
