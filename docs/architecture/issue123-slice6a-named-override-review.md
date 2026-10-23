# Meridian #123 — Slice 6A: named, current Grade override review

A routine Overrides menu now offers a **read-only** review through verified class, marking period, roster student, and Grade calculation family. It delegates exact current-state reads to the previously published OverrideReviewLoader. No new storage schema, policy, family calculation, authorization, or academic write is introduced.

- Reuse the period and Grade-family selection introduced in Slice 5A; use only currently verified Core roster students.
- Revalidate scope and names before and after two exact current-state reads. A changed current selected override/withdrawal is not silently substituted.
- Distinguish **no selected override**, selected **override** (including an actual zero replacement), and selected **withdraw**. A withdrawal is not an active replacement Grade.
- Keep opaque student/class/period IDs, hashes, actor IDs, raw rationale and diagnostic paths out of the routine output. Technical detail, authoring, selection, and withdrawal remain explicitly labeled **Advanced**.
- Preserve direct/no-navigation menu numbering and semantics. Maintain B/M/Q and current local shortcuts. No Core #237 shared-header or `:notes` implementation occurs here.
- No Grade, override, selected revision, receipt, or producer evidence publication is written by read-only review.

Full installed Meridian qualification, including the historical #123 audit and #121/#122 regressions, is required before commit or push.
