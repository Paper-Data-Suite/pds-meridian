# Student Current Grade Justification — Issue #111 Slice 8

Slice 8 adds a concise, read-only explanation report for one student's Grade.

## Current mode

Current mode delegates to Meridian's existing `explain_current_grade_preview`
service. The report does not recalculate a second Grade, select another result,
change a policy, or write an override.

Standards-based current reports are directly available through the CLI because
they do not require caller-supplied producer work evidence. Conventional and
hybrid current reports remain supported by the report API only when the caller
supplies an explicit authorized `ConventionalGradeWorkEvidenceSpec` tuple. The
direct CLI refuses to open protected evidence implicitly.

## Historical mode

Historical mode loads one exact digest-bound `ReportingSnapshot`, locates one
frozen student/family row, and consumes the exact `GradePreviewObservation` and
rich Grade explanation bytes already retained by the snapshot.

Historical justification therefore does not consult or replay current Grade
state.

## Report content

The report summarizes, when applicable:

- effective Grade and source;
- base Grade status and freshness;
- exact Grade policy and activation;
- selected teacher override state and rationale;
- conventional Grade Item participation;
- standards proficiency judgments and bounded nested Grade Item counts;
- standards profile band/floor/cap state;
- hybrid component status;
- material reason codes;
- exact digest-bound source references;
- live generation time or historical snapshot timestamp.

Raw protected student work is not reproduced.

The report is a derived local artifact. It creates no new Grade, proficiency,
policy, override, ReportingSnapshot, evidence decision, SIS record, or LMS
record.
