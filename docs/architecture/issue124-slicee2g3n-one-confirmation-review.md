# Issue #124 E2G3N — Teacher review boundary for one-confirmation setup

This increment adds `meridian/menu_teacher_assessment_setup_review.py`, a narrow presentation/controller boundary for an **already bound** D2 `PreparedAssessmentSetupComposite`. It does not silently route the existing teacher menu or create a new academic writer.

- Present verified reviewed assessment title, producer, class, publication status, Grade Item title/purpose, period and weighting notice. Canonical IDs, revisions and hashes are not requested from the teacher.
- For `create_and_link` or `use_existing`, request exactly one literal `APPLY` and call the prepared one-shot composite once. A cancellation invokes no academic or receipt callbacks.
- For `already_ready`, request no confirmation: independently run the composite's canonical no-write verification. Never infer ready from existing historical files alone.
- On a matching `ready` or `already_ready` result, preserve the exact selected work, publication reference (if present) and Grade Item in the active class session. Partial, unknown, conflicting, stale and mismatched results do not change navigation.
- Do not create/activate a Grade policy, consume protected evidence, select student attempts, calculate Grades, or authorize a published manifest. The controller only uses the existing D1/D2/#122 interfaces.

**Not yet complete:** E2G3N does not make this controller accessible from the normal teacher menu; E2G3O must connect a named assessment/period choice and the live binder while preserving E2 composite correlation and original action receipts. Full production acceptance must also test real publisher and teacher-profile evidence. This slice is a bounded functional checkpoint, not a claim that ticket #124's primary acceptance has passed.
