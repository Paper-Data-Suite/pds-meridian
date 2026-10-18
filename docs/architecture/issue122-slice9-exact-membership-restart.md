# Meridian #122 — Slice 9: exact work-membership selection after restart

## Scope and boundary

Extend **R. Review Interrupted Saves** with a separate, explicit, restart-safe `RESUME` option for a previously **persisted, included Grade Item/work membership** decision. No new membership revision, Grade Item, work registration, assessment, or academic calendar is authored by this path. The original immutable revision, current pointer, and Core registration/calendar remain authoritative. This is not a cross-file atomic transaction or a general replay engine.

Slice 8's narrowly scoped new-Grade-Item recovery remains unchanged. Eligibility, attempt policy and decisions, Standard association, and proficiency result **remain inspection-only after restart**. Their privacy-minimal journal fingerprints do not reconstruct authorization/producer-derived source contexts; no guessing, default granting, or `latest` selection is permitted.

## Rehydration and authority

1. Validate the exact receipt is unchanged since inbox inspection and belongs to the absolute workspace and requested class.
2. Require persistent **saved** teacher attribution, the original actor/profile fingerprint, exact action kind, exact scope, both original dependency-basis fingerprints and selected-academic-period scope. A temporary one-use override cannot be revived across a restart.
3. Enumerate canonical Grade Item/work relationships using the existing validated storage API (bounded at 2,048 candidates). Match both the per-work and relationship identity fingerprints. Reject zero or ambiguous matches and any invalid/reparse entries surfaced by the canonical API. Do not reconstruct raw IDs by reversing hashes, or use an arbitrary scanner.
4. Load the unique immutable candidate and contiguous history. Require its SHA-256, actor, Grade Item identity, exact work, revision and included disposition to match the reviewed receipt; block a subsequent appended revision.
5. Revalidate the current selected Grade Item revision/digest, active work registration revision, Core membership dependencies, exact academic period and current-calendar digest. The canonical reader must perform this independently of the journal.
6. Use `assess_teacher_action_recovery` with the live domain port. Only an exact present-but-not-current target with an unchanged prior current pointer can offer explicit `RESUME`.
7. After that confirmation, call only the existing membership selection preview and CAS commit for the exact immutable target, and independently verify current state through the shared orchestration kernel. No fallback authoring, no retry on a changed pointer and no silent selection of the newest revision.

## Adversarial coverage

Focused synthetic tests include cancel-before-selection, genuine one-time exact selection, disabled revision writer, changed Grade Item, calendar, registration, actor, digest, work reference, added history, changed receipt generation and bounded enumeration. Route/menu regressions and prior receipt/orchestration tests run with the guarded Windows runner. Follow with final #122 full-suite, installed wheel, Windows/Linux CI and cross-producer qualification; do not claim those before execution.

## Teacher wording

The journal-only entry remains explicitly **not academic truth**. A user sees a `RESUME` prompt only after independent canonical verification; otherwise the correct response is to review current Grade Item memberships manually. Completion is reported only after exact canonical current status is verified.
