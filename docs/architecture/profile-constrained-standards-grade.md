# Profile-constrained standards Grade policy

Issue #99 adds the bounded `profile_constrained_mean` standards Grade strategy while preserving `weighted_mean`.

The architecture keeps two judgments separate:

```text
proficiency conversions + weights -> base weighted mean
profile groups + predicates -> eligible Grade band
eligible band + base mean -> floor / cap / unchanged -> final rounding
```

Profile significance is not encoded through extreme weights. Groups are generic policy concepts; Meridian does not hard-code Focus Standards or letter grades.

## Bounded profile authority

The only v1 predicates are `all_at_or_above`, `count_at_or_above`, and `proportion_at_or_above`. Predicates inside one band are conjunctive. There is no executable formula language. Proficiency order comes only from the exact immutable `ProficiencyScale` bound to the calculation.

Predicate results are `matched`, `not_matched`, or `indeterminate`. Missing or non-calculated proficiency stays unknown. In particular:

```text
numeric zero consequence != low proficiency judgment
```

A Grade-policy zero may participate in the base numeric mean while its profile member remains unknown.

## Band selection and numeric constraint

Bands are explicit, ordered, finite, non-overlapping ranges with one lowest-priority predicate-free fallback. A lower matched band may be selected only after every higher band is determinately ruled out. A higher `indeterminate` band prevents a silent downgrade.

After the base weighted mean is calculated, a value below the selected band is floored, a value above it is capped, and a value inside it is unchanged. Rounding occurs once after profile adjustment. The result preserves `base_unrounded_grade`, selected band and bounds, structured predicate evaluation, adjustment, and adjusted Grade.

## Hybrid, explanation, and snapshots

Hybrid Grade algorithm version 2 consumes the final unrounded standards component and does not reevaluate profile groups, predicates, or bands.

Explanations preserve the base mean, profile policy, predicate evidence, unknown standard IDs, selected band, bounds, adjustment, and rounding. Comparison distinguishes `base_mean_changed`, `profile_policy_changed`, `profile_predicates_changed`, `profile_band_changed`, and `profile_adjustment_changed`.

ReportingSnapshot reload validates frozen profile policy/evaluation and profile-specific comparison basis. Legacy weighted snapshots remain readable. Teacher overrides stay downstream; exports stay local and bounded; Issue #99 adds no SIS/LMS/district-gradebook write authority.

## Teacher application boundary

No new main-menu task is added. Existing `Preview Grades` and `Explain` routes already dispatch by Grade family. Profile-related attention remains issue #58; suite doctor/launcher/backup/attention integration remains issue #59.

## Installed and release qualification

The exact released compatibility set rechecked for Issue #99 is:

```text
pds-core 0.6.3
scoreform 0.11.0
quillan 0.10.3
pds-concord 0.3.0
```

Installed acceptance reuses the post-#96 `scoreform-quillan` prepared environment and proves an upward profile floor, immutable persistence/selection, canonical reproduction, and fresh-process reload. No seventh matrix is created.

Issue #60 cross-policy adversarial acceptance must cover both `weighted_mean` and `profile_constrained_mean`.

Issue #61 release audit must verify deterministic profile policy, no silent downgrade behind an indeterminate higher band, no invented proficiency, preserved weighted-mean semantics, ReportingSnapshot replay, exact installed artifacts, and the six prepared dependency matrices.
