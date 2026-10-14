# Benchmark analysis and instructional response

Meridian's ninth teacher report is a district-neutral planning view over
verified existing evidence. It extends the common `TeacherReportPreview`
contract; it is not a second grading or proficiency system.

## Authority and currentness

The guided and direct live paths select one Class, Academic Period, Grade Item,
and current ReportingSnapshot checkpoint. Every protected projection named by
that checkpoint is independently reauthorized for the `teacher_reporting`
purpose. Its exact digest must still match and its cache assessment must remain
reusable for current use. The executor observes the selection witness before
and after generation and fails if a material source changes.

The report uses a single verified configured proficiency-scale revision. A
student is shown in a selected proficiency category only when the current
assessment-level standard results provide one unambiguous selected level. Raw
scores are never converted into proficiency. Multiple or unavailable scale
authorities fail safely.

## Denominators and producer semantics

Roster, expected, tested, valid-result, not-assessed, missing-result,
insufficient-evidence, and invalid/unresolved counts are distinct. Native scores
are retained as native text. Missing or insufficient evidence is not a zero and
is not assigned a proficiency label.

ScoreForm question correctness is aggregated only when a student/work pair has
one unambiguous observed attempt. Blank and ambiguous responses are counted
separately and excluded from the correct/incorrect denominator. Meridian does
not infer question type when the producer has not supplied it. Quillan,
Concord, and other supported native standards evidence may contribute without
being converted into invented percentage-correct values.

Standards are classified as strong or challenging only when a caller supplies
an explicit comparable basis. The normal live report therefore preserves
native level counts and leaves comparative interpretation unclassified.

## Teacher-authored planning

Optional groups, including a group labeled Bubble, are planning metadata only.
They do not change selected proficiency, Grade calculations, evidence,
producer records, or external systems. Reteach, revisit, small-group,
enrichment, and extension responses carry explicit student targets, dates,
resources, rework/retest targets, status, and teacher reflection. Follow-up records retain
their comparison basis and do not claim instructional causation.

Confirmed plans use append-only `BenchmarkPlanRevision` storage. Stable plan,
teacher, class, and assessment identity is preserved; each later revision is
chained to the exact SHA-256 of its predecessor. Original revisions remain
available. A saved plan is not an official SIS or LMS record.

## Output

Markdown uses four print-friendly sections: Assessment Data; Standards and
Item Analysis; Instructional Response; and Results from Targeted Instruction.
JSON, Markdown, CSV, and TSV remain deterministic common report renderings.
Exports state that they have not been officially submitted or approved.
